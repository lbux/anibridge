"""Sync client for episodic shows using provider abstractions."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime

import msgspec
from anibridge.library import HistoryEntry, LibraryEpisode, LibrarySeason, LibraryShow
from anibridge.list import ListEntry, ListMediaType, ListStatus
from anibridge.utils.cache import lru_cache
from anibridge.utils.mappings import (
    AnibridgeDescriptorMapping,
    AnibridgeMapping,
    descriptor_key,
)
from anibridge.utils.types import MappingDescriptor

from anibridge.app.core.sync.base import BaseSyncClient
from anibridge.app.core.sync.stats import ItemIdentifier
from anibridge.app.core.sync.targeting import (
    ResolvedListTarget,
    SyncTarget,
    find_best_search_result,
    resolve_list_targets_batch,
)

__all__ = ["ShowSyncClient"]


class _SeasonGroup(msgspec.Struct):
    child_item: LibrarySeason
    first_index: int
    episodes: list[LibraryEpisode]
    entry: ListEntry
    media_key: str
    mappings: dict[
        tuple[str, str, tuple[tuple[str, str], ...]],
        AnibridgeDescriptorMapping,
    ]


class _ResolvedSeasonTargets(msgspec.Struct):
    season_index: int
    season: LibrarySeason
    episodes: tuple[LibraryEpisode, ...]
    targets: tuple[ResolvedListTarget, ...]


type _SeasonPayload = tuple[
    int,
    LibrarySeason,
    tuple[LibraryEpisode, ...],
    tuple[MappingDescriptor, ...],
]


class ShowSyncClient(BaseSyncClient[LibraryShow, LibrarySeason, LibraryEpisode]):
    """Synchronize show items between a library provider and a list provider."""

    async def clear_cache(self) -> None:
        """Clear all sync client caches."""
        await super().clear_cache()
        self.search_media.cache_clear()
        self._calculate_progress.cache_clear()
        self._wanted_season_payloads.cache_clear()
        self._resolve_season_targets.cache_clear()
        self.__get_wanted_episodes.cache_clear()
        self.__get_wanted_seasons.cache_clear()
        self._filter_history_by_episodes.cache_clear()

    async def resolve_mapping_targets(
        self, item: LibraryShow
    ) -> Sequence[tuple[LibrarySeason, Sequence[LibraryEpisode], SyncTarget]]:
        """Resolve deterministic mapping targets for a show."""
        groups: dict[str, _SeasonGroup] = {}

        for resolved in await self._resolve_season_targets(item):
            viable_targets = self._resolve_active_targets(
                item=item,
                season=resolved.season,
                season_episodes=resolved.episodes,
                resolved_targets=resolved.targets,
            )
            self._untrack_skipped_episodes(
                season_episodes=resolved.episodes,
                viable_targets=viable_targets,
                resolved_targets=resolved.targets,
            )

            for target, filtered in viable_targets:
                entry = await self._cache.get_entry(target.list_media_key)
                if entry is None:
                    continue
                media_key = entry.media().key
                if (group := groups.get(media_key)) is None:
                    groups[media_key] = _SeasonGroup(
                        child_item=resolved.season,
                        first_index=resolved.season_index,
                        episodes=filtered,
                        entry=entry,
                        media_key=media_key,
                        mappings={
                            self._mapping_signature(mapping_rule): mapping_rule
                            for mapping_rule in target.mappings
                        },
                    )
                    continue

                if resolved.season_index < group.first_index:
                    group.child_item, group.first_index = (
                        resolved.season,
                        resolved.season_index,
                    )
                group.episodes.extend(filtered)
                group.entry = entry
                for mapping_rule in target.mappings:
                    group.mappings.setdefault(
                        self._mapping_signature(mapping_rule),
                        mapping_rule,
                    )

        return tuple(
            (
                group.child_item,
                tuple(
                    sorted(group.episodes, key=lambda ep: (ep.season_index, ep.index))
                ),
                SyncTarget(
                    list_media_key=group.media_key,
                    entry=group.entry,
                    mappings=tuple(group.mappings.values()),
                ),
            )
            for group in sorted(groups.values(), key=lambda g: g.first_index)
        )

    async def resolve_search_targets(
        self, item: LibraryShow
    ) -> Sequence[tuple[LibrarySeason, Sequence[LibraryEpisode], SyncTarget]]:
        """Resolve explicit search fallback targets for a show."""
        groups: dict[str, _SeasonGroup] = {}
        for (
            season_index,
            season,
            episodes,
            _descriptors,
        ) in self._wanted_season_payloads(item):
            entry = await self.search_media(item, season)
            if entry is None:
                continue

            self._cache.cache_entry(entry)
            media_key = entry.media().key
            if (group := groups.get(media_key)) is None:
                groups[media_key] = _SeasonGroup(
                    child_item=season,
                    first_index=season_index,
                    episodes=list(episodes),
                    entry=entry,
                    media_key=media_key,
                    mappings={},
                )
                continue

            if season_index < group.first_index:
                group.child_item, group.first_index = season, season_index
            group.episodes.extend(episodes)

        return tuple(
            (
                group.child_item,
                tuple(
                    sorted(group.episodes, key=lambda ep: (ep.season_index, ep.index))
                ),
                SyncTarget(
                    list_media_key=group.media_key,
                    entry=group.entry,
                ),
            )
            for group in sorted(groups.values(), key=lambda g: g.first_index)
        )

    @lru_cache(maxsize=64)
    async def search_media(
        self, item: LibraryShow, child_item: LibrarySeason
    ) -> ListEntry | None:
        """Return the best search fallback target for a season."""
        if child_item.index == 0:
            return None

        episode_count = len(tuple(child_item.episodes()))
        results = await self.list_provider.search(item.title)
        tv_results: list[ListEntry] = []
        filtered: list[ListEntry] = []
        for entry in results:
            media = entry.media()
            if media.media_type != ListMediaType.TV:
                continue
            tv_results.append(entry)
            if media.total_units is None or media.total_units == episode_count:
                filtered.append(entry)

        return find_best_search_result(
            item.title,
            filtered or tv_results,
            self.search_fallback_threshold,
        )

    @staticmethod
    def _mapping_signature(
        mapping: AnibridgeDescriptorMapping,
    ) -> tuple[str, str, tuple[tuple[str, str], ...]]:
        """Return a stable key for deduplicating descriptor mappings."""
        return (
            descriptor_key(mapping.source),
            descriptor_key(mapping.target),
            tuple(
                (mapping_entry.source_key, mapping_entry.target_value)
                for mapping_entry in mapping.mappings
            ),
        )

    def _filter_episodes_by_ranges(
        self,
        episodes: Sequence[LibraryEpisode],
        mappings: Sequence[AnibridgeDescriptorMapping],
    ) -> list[LibraryEpisode]:
        """Filter episodes using source mapping ranges."""
        if not mappings:
            return list(episodes)

        all_source_ranges = [
            mapping_entry.source_range
            for descriptor_mapping in mappings
            for mapping_entry in descriptor_mapping.mappings
        ]
        if not all_source_ranges:
            return []
        return [
            episode
            for episode in episodes
            if any(
                source_range.contains(episode.index)
                for source_range in all_source_ranges
            )
        ]

    async def _get_all_trackable_items(
        self, item: LibraryShow
    ) -> Sequence[ItemIdentifier]:
        episodes = self.__get_wanted_episodes(item)
        if not episodes:
            return []
        return ItemIdentifier.from_items(episodes)

    async def _collect_prefetch_keys(self, item: LibraryShow) -> Sequence[str]:
        collected = {
            str(target.list_media_key)
            for resolved in await self._resolve_season_targets(item)
            for target in resolved.targets
        }
        return tuple(sorted(collected))

    @lru_cache(maxsize=32)
    def _wanted_season_payloads(self, item: LibraryShow) -> tuple[_SeasonPayload, ...]:
        """Return eligible seasons with episodes and descriptor sets."""
        seasons = self.__get_wanted_seasons(item)
        if not seasons:
            return ()

        episodes_by_season: dict[int, list[LibraryEpisode]] = defaultdict(list)
        for episode in self.__get_wanted_episodes(item):
            if episode.season_index in seasons:
                episodes_by_season[episode.season_index].append(episode)

        payloads = []
        for season_index in sorted(seasons):
            episodes = episodes_by_season.get(season_index)
            if not episodes:
                continue

            season = seasons[season_index]
            raw_item = getattr(season, "_item", getattr(season, "item", None))
            pids = getattr(
                season, "provider_ids", getattr(raw_item, "provider_ids", {})
            )

            s_anidb = None
            if isinstance(pids, dict):
                s_anidb = pids.get("anidb") or pids.get("AniDB") or pids.get("Anidb")
            if s_anidb:
                final_descriptors = (("anidb", str(s_anidb), "R"),)
            else:
                final_descriptors = (
                    *season.mapping_descriptors(),
                    *item.mapping_descriptors(),
                )
            payloads.append(
                (
                    season_index,
                    season,
                    tuple(episodes),
                    final_descriptors,
                )
            )

        return tuple(payloads)

    @lru_cache(maxsize=32)
    async def _resolve_season_targets(
        self, item: LibraryShow
    ) -> tuple[_ResolvedSeasonTargets, ...]:
        """Resolve mapping targets for each eligible season once per cache cycle."""
        season_payloads = self._wanted_season_payloads(item)
        if not season_payloads:
            return ()

        resolved_batches = await resolve_list_targets_batch(
            animap_client=self.animap_client,
            list_provider=self.list_provider,
            descriptor_sets=[payload[3] for payload in season_payloads],
        )
        return tuple(
            _ResolvedSeasonTargets(
                season_index=season_index,
                season=season,
                episodes=season_episodes,
                targets=resolved_targets,
            )
            for (season_index, season, season_episodes, _), resolved_targets in zip(
                season_payloads,
                resolved_batches,
                strict=False,
            )
        )

    def _resolve_active_targets(
        self,
        *,
        item: LibraryShow,
        season: LibrarySeason,
        season_episodes: Sequence[LibraryEpisode],
        resolved_targets: Sequence[ResolvedListTarget],
    ) -> list[tuple[ResolvedListTarget, list[LibraryEpisode]]]:
        """Return resolved targets whose mapped episodes should be considered."""
        active_targets: list[tuple[ResolvedListTarget, list[LibraryEpisode]]] = []
        for target in resolved_targets:
            filtered = self._episodes_for_target(
                item=item,
                season=season,
                season_episodes=season_episodes,
                target=target,
            )
            if filtered:
                active_targets.append((target, filtered))
        return active_targets

    def _untrack_skipped_episodes(
        self,
        *,
        season_episodes: Sequence[LibraryEpisode],
        viable_targets: Sequence[tuple[ResolvedListTarget, list[LibraryEpisode]]],
        resolved_targets: Sequence[ResolvedListTarget],
    ) -> None:
        """Remove mapped episodes from stats when they were excluded from sync."""
        if not resolved_targets:
            return

        included_keys = {
            episode.key for _target, episodes in viable_targets for episode in episodes
        }
        skipped = [
            episode for episode in season_episodes if episode.key not in included_keys
        ]
        if skipped:
            self.sync_stats.untrack_items(ItemIdentifier.from_items(skipped))

    def _episodes_for_target(
        self,
        *,
        item: LibraryShow,
        season: LibrarySeason,
        season_episodes: Sequence[LibraryEpisode],
        target: ResolvedListTarget,
    ) -> list[LibraryEpisode]:
        """Return episodes that should be considered for a resolved target."""
        filtered = self._filter_episodes_by_ranges(
            season_episodes,
            target.mappings,
        )
        if not filtered:
            return []
        if self._should_skip_inactive_mapping_range(item, season, filtered, target):
            return []
        return filtered

    def _should_skip_inactive_mapping_range(
        self,
        item: LibraryShow,
        season: LibrarySeason,
        episodes: Sequence[LibraryEpisode],
        target: ResolvedListTarget,
    ) -> bool:
        """Skip mapped subranges that have no actionable activity."""
        if not target.mappings:
            return False
        if self.full_scan or self.destructive_sync or self.empty_sync:
            return False
        if item.on_watching:
            return False
        if item.on_watchlist or season.on_watchlist:
            return False
        if not self._sync_rule_engine.is_disabled("user_rating") and (
            item.user_rating is not None or season.user_rating is not None
        ):
            return False
        return not any(
            episode.view_count
            # or episode.on_watchlist
            # or episode.review is not None
            # or episode.user_rating is not None
            # ==========================================================================
            # It is highly unlikely for a provider to allow an episode to be on the
            # watchlist without the parent season/show also being on the watchlist.
            #
            # User ratings and reviews are gated by the completed status, so without
            # watch activity it's unlikely to be used.
            for episode in episodes
        )

    async def _calculate_status(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
        mappings: Sequence[AnibridgeDescriptorMapping] | None = None,
    ) -> ListStatus | None:
        watched_units = self._calculate_watched_units(grandchild_items, mappings)
        watched_episode_count = sum(
            1 for episode in grandchild_items if episode.view_count
        )
        min_view_count = min(
            (episode.view_count for episode in grandchild_items if episode.view_count),
            default=0,
        )
        on_watching = item.on_watching and any(
            episode.on_watching for episode in grandchild_items
        )
        is_finished = len(grandchild_items) == watched_episode_count
        _total_units = entry.media().total_units
        is_completed = _total_units is not None and watched_units >= _total_units

        # We've watched all required episodes at least once
        if is_completed:
            # We're in the middle of re-watching
            if on_watching and min_view_count >= 1:
                return ListStatus.REPEATING
            return ListStatus.COMPLETED

        # We're in the middle of the first watchthrough
        if on_watching:
            return ListStatus.CURRENT

        # We've stopped watching partway through or have no more available episodes
        if watched_units:
            # Either the list or library has incomplete data; assume current
            if is_finished:  # and not is_completed
                return ListStatus.CURRENT
            # We've dropped the show but the user still wants to watch it later
            if item.on_watchlist or child_item.on_watchlist:
                return ListStatus.PAUSED
            return ListStatus.DROPPED

        # We've had no activity on this show yet but it's on the watchlist
        if item.on_watchlist or child_item.on_watchlist:
            return ListStatus.PLANNING

        if self.empty_sync and entry.status is None:
            return ListStatus.PLANNING

        # No activity; leave it untracked
        return None

    async def _calculate_user_rating(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
        mappings: Sequence[AnibridgeDescriptorMapping] | None = None,
    ) -> int | None:
        scores = [
            episode.user_rating for episode in grandchild_items if episode.user_rating
        ]
        # If more than half of the episodes have ratings, calculate an average.
        # Otherwise, defer to season/show rating.
        if len(scores) >= (len(grandchild_items) + 1) / 2:
            return round(sum(scores) / len(scores))
        if child_item.user_rating:
            return child_item.user_rating
        if item.user_rating:
            return item.user_rating
        return None

    @lru_cache(maxsize=1)  # De-duplicate call from status
    async def _calculate_progress(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
        mappings: Sequence[AnibridgeDescriptorMapping] | None = None,
    ) -> int | None:
        watched = self._calculate_watched_units(grandchild_items, mappings)
        total_units = entry.media().total_units or len(grandchild_items)
        if total_units:
            return min(watched, total_units)
        return watched or None

    async def _calculate_repeats(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
        mappings: Sequence[AnibridgeDescriptorMapping] | None = None,
    ) -> int | None:
        view_counts = [
            episode.view_count for episode in grandchild_items if episode.view_count
        ]
        return min(view_counts) - 1 if view_counts else None

    async def _calculate_started_at(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
        mappings: Sequence[AnibridgeDescriptorMapping] | None = None,
    ) -> datetime | None:
        history = await self._filter_history_by_episodes(item, grandchild_items)
        if not history:
            return None
        return min(record.viewed_at for record in history)

    async def _calculate_finished_at(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
        mappings: Sequence[AnibridgeDescriptorMapping] | None = None,
    ) -> datetime | None:
        history = await self._filter_history_by_episodes(item, grandchild_items)
        if not history:
            return None
        return max(record.viewed_at for record in history)

    async def _calculate_review(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
        mappings: Sequence[AnibridgeDescriptorMapping] | None = None,
    ) -> str | None:
        if entry.media().total_units == 1 and len(grandchild_items) == 1:
            review = await grandchild_items[0].review
            if review:
                return review
        return await child_item.review or await item.review

    def _calculate_watched_units(
        self,
        episodes: Sequence[LibraryEpisode],
        mappings: Sequence[AnibridgeDescriptorMapping] | None,
    ) -> int:
        """Calculate the number of watched units, taking mapping ratios into account."""
        watched_episodes = [episode for episode in episodes if episode.view_count]
        watched_count = len(watched_episodes)
        if watched_count == 0:
            return 0
        if not mappings:
            return watched_count

        entries_by_source: dict[
            MappingDescriptor,
            list[AnibridgeMapping],
        ] = defaultdict(list)
        for descriptor_mapping in mappings:
            entries_by_source[descriptor_mapping.source].extend(
                descriptor_mapping.mappings
            )

        mapping_entries = [
            mapping_entry
            for entries in entries_by_source.values()
            for mapping_entry in entries
        ]
        if not mapping_entries:
            return watched_count

        if all(mapping_entry.source_weight == 1.0 for mapping_entry in mapping_entries):
            # Basic case where there's no ratio weight
            return watched_count

        watched_units = sum(
            self._mapping_weight_for_episode(
                episode,
                entries_by_source,
                mapping_entries,
            )
            for episode in watched_episodes
        )
        return int(watched_units + 1e-9)

    @staticmethod
    def _mapping_weight_for_episode(
        episode: LibraryEpisode,
        entries_by_source: Mapping[MappingDescriptor, Sequence[AnibridgeMapping]],
        fallback_entries: Sequence[AnibridgeMapping],
    ) -> float:
        """Return the most specific mapping weight for an episode."""
        source_entries = [
            entry
            for descriptor in dict.fromkeys(episode.mapping_descriptors())
            for entry in entries_by_source.get(descriptor, ())
        ]
        mapping = min(
            (
                entry
                for entry in (source_entries or fallback_entries)
                if entry.source_range.contains(episode.index)
            ),
            key=lambda entry: entry.source_range.length or float("inf"),
            default=None,
        )
        return 1.0 if mapping is None else mapping.source_weight

    def _debug_log_title(
        self,
        item: LibraryShow,
        child_item: LibrarySeason | None = None,
    ) -> str:
        return (
            f"$$'{item.title}'$$"
            if child_item is None
            else f"$$'{item.title} (S{child_item.index})'$$"
        )

    def _debug_log_ids(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason | None,
        entry: ListEntry | None,
        media_key: str | None,
    ) -> str:
        formatted: list[str] = []
        if media_key:
            formatted.append(
                descriptor_key((self.list_provider.NAMESPACE, str(media_key), None))
            )
        formatted.extend(
            descriptor_key(descriptor) for descriptor in item.mapping_descriptors()
        )
        return f"$${{{', '.join(formatted)}}}$$"

    @lru_cache(maxsize=1)
    def __get_wanted_seasons(self, item: LibraryShow) -> dict[int, LibrarySeason]:
        """Return seasons that should participate in sync."""
        seasons: dict[int, LibrarySeason] = {}
        for season in item.seasons():
            episodes = season.episodes()
            if not episodes:
                continue
            if (
                self.full_scan
                or self.destructive_sync
                or any(episode.view_count for episode in episodes)
            ):
                seasons[season.index] = season
        return seasons

    @lru_cache(maxsize=1)
    def __get_wanted_episodes(self, item: LibraryShow) -> list[LibraryEpisode]:
        """Return episodes belonging to wanted seasons."""
        seasons = self.__get_wanted_seasons(item)
        if not seasons:
            return []
        return [
            episode for episode in item.episodes() if episode.season_index in seasons
        ]

    @lru_cache(maxsize=32)
    async def _filter_history_by_episodes(
        self, item: LibraryShow, episodes: Sequence[LibraryEpisode]
    ) -> list[HistoryEntry]:
        """Return history entries that belong to the supplied episodes."""
        episode_keys = {episode.key for episode in episodes}
        history = await item.history()
        filtered = [entry for entry in history if entry.library_key in episode_keys]
        filtered.sort(key=lambda record: record.viewed_at)
        return filtered
