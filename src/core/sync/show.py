"""Sync client for episodic shows using provider abstractions."""

from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime

from anibridge.library import (
    HistoryEntry,
    LibraryEpisode,
    LibrarySeason,
    LibraryShow,
)
from anibridge.list import ListEntry, ListMediaType, ListStatus, MappingDescriptor
from src.core.animap import descriptor_key
from src.core.sync.base import (
    BaseSyncClient,
    ResolvedListTarget,
    SourceRangeMapping,
    SyncTarget,
)
from src.core.sync.stats import ItemIdentifier
from src.utils.cache import gattl_cache, glru_cache
from src.utils.mapping_ranges import SourceRange

__all__ = ["ShowSyncClient"]


@dataclass(slots=True)
class _SeasonGroup:
    child_item: LibrarySeason
    first_index: int
    episodes: list[LibraryEpisode]
    entry: ListEntry
    media_key: str
    mapping_descriptors: set[MappingDescriptor]


class ShowSyncClient(BaseSyncClient[LibraryShow, LibrarySeason, LibraryEpisode]):
    """Synchronize show items between a library provider and a list provider."""

    @staticmethod
    def _scope_matches_season(scope: str | None, season_index: int) -> bool:
        """Return True when the mapping scope applies to the given season."""
        if scope is None:
            return True
        if scope.startswith("s") and scope[1:].isdigit():
            return int(scope[1:]) == season_index
        return True

    def _filter_episodes_by_ranges(
        self,
        episodes: Sequence[LibraryEpisode],
        season_index: int,
        source_mappings: Sequence[SourceRangeMapping],
    ) -> list[LibraryEpisode]:
        """Filter episodes based on mapping source ranges."""
        if not source_mappings:
            return list(episodes)

        ranges: list[SourceRange] = []
        for mapping in source_mappings:
            if self._scope_matches_season(mapping.descriptor[2], season_index):
                ranges.extend(mapping.ranges)

        if not ranges:
            return list(episodes)

        return [
            episode
            for episode in episodes
            if any(range_.contains(episode.index) for range_ in ranges)
        ]

    async def map_media(
        self, item: LibraryShow
    ) -> AsyncIterator[
        tuple[
            LibrarySeason,
            Sequence[LibraryEpisode],
            SyncTarget,
        ]
    ]:
        """Yield mapping candidates for the provided show item."""
        seasons = self.__get_wanted_seasons(item)
        if not seasons:
            return

        wanted_indexes = set(seasons)
        episodes_by_season: dict[int, list[LibraryEpisode]] = defaultdict(list)
        for ep in self.__get_wanted_episodes(item):
            if ep.season_index in wanted_indexes:
                episodes_by_season[ep.season_index].append(ep)

        season_payloads = [
            (
                season_index,
                season,
                season_episodes,
                list(season.mapping_descriptors()) + list(item.mapping_descriptors()),
            )
            for season_index in sorted(wanted_indexes)
            if (season_episodes := episodes_by_season.get(season_index))
            and (season := seasons[season_index])
        ]

        resolved_batches = await self._resolve_list_targets_batch(
            [payload[3] for payload in season_payloads]
        )

        groups: dict[str, _SeasonGroup] = {}

        for (season_index, season, season_episodes, _), resolved_targets in zip(
            season_payloads,
            resolved_batches,
            strict=False,
        ):
            targets: list[tuple[ResolvedListTarget, ListEntry]] = []
            if resolved_targets:
                for target in resolved_targets:
                    entry = await self._get_entry_cached(target.list_media_key)
                    if entry is None:
                        continue
                    targets.append((target, entry))

            if not targets:
                entry = await self.search_media(item, season)
                if entry:
                    key = str(entry.media().key)
                    self._cache_list_entry(entry)
                    targets = [
                        (
                            ResolvedListTarget(
                                list_media_key=key,
                                mapping_descriptors=(),
                                source_mappings=(),
                            ),
                            entry,
                        )
                    ]

            if not targets:
                continue

            for target, entry in targets:
                filtered = self._filter_episodes_by_ranges(
                    season_episodes,
                    season_index,
                    target.source_mappings,
                )
                if not filtered:
                    continue

                media_key = entry.media().key
                if (group := groups.get(media_key)) is None:
                    groups[media_key] = _SeasonGroup(
                        child_item=season,
                        first_index=season_index,
                        episodes=list(filtered),
                        entry=entry,
                        media_key=media_key,
                        mapping_descriptors=set(target.mapping_descriptors),
                    )
                    continue

                if season_index < group.first_index:
                    group.child_item, group.first_index = season, season_index
                group.episodes.extend(filtered)
                group.entry = entry
                group.mapping_descriptors.update(target.mapping_descriptors)

        for group in sorted(groups.values(), key=lambda g: g.first_index):
            eps = sorted(group.episodes, key=lambda ep: (ep.season_index, ep.index))
            yield (
                group.child_item,
                tuple(eps),
                SyncTarget(
                    list_media_key=group.media_key,
                    entry=group.entry,
                    mapping_descriptors=tuple(
                        sorted(group.mapping_descriptors, key=descriptor_key)
                    ),
                ),
            )

    async def search_media(
        self, item: LibraryShow, child_item: LibrarySeason
    ) -> ListEntry | None:
        """Locate a fallback list entry for the given season."""
        if self.search_fallback_threshold < 0 or child_item.index == 0:
            return None

        results = await self.list_provider.search(item.title)
        tv_results = [
            entry for entry in results if entry.media().media_type == ListMediaType.TV
        ]
        episode_count = len(child_item.episodes())
        filtered = [
            entry
            for entry in tv_results
            if entry.media().total_units is None
            or entry.media().total_units == episode_count
        ]
        candidates = filtered or tv_results
        return self._best_search_result(item.title, candidates)

    async def _get_all_trackable_items(
        self, item: LibraryShow
    ) -> Sequence[ItemIdentifier]:
        episodes = self.__get_wanted_episodes(item)
        if not episodes:
            return []
        return ItemIdentifier.from_items(episodes)

    async def _collect_prefetch_keys(self, item: LibraryShow) -> Sequence[str]:
        seasons = self.__get_wanted_seasons(item)
        if not seasons:
            return []
        descriptor_sets = [
            list(season.mapping_descriptors()) + list(item.mapping_descriptors())
            for season in seasons.values()
        ]
        resolved_batches = await self._resolve_list_targets_batch(descriptor_sets)
        collected = {
            str(target.list_media_key)
            for targets in resolved_batches
            for target in targets
        }
        return tuple(sorted(collected))

    async def _calculate_status(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
    ) -> ListStatus | None:
        watched_count = len(
            [episode for episode in grandchild_items if episode.view_count]
        )
        min_view_count = min(
            (episode.view_count for episode in grandchild_items if episode.view_count),
            default=0,
        )
        on_watching = item.on_watching and any(
            episode.on_watching for episode in grandchild_items
        )
        is_finished = len(grandchild_items) == watched_count
        _total_units = entry.media().total_units
        is_completed = _total_units is not None and watched_count >= _total_units

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
        if watched_count:
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

        # No activity; leave it untracked
        return None

    async def _calculate_user_rating(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
    ) -> int | None:
        scores = [
            episode.user_rating for episode in grandchild_items if episode.user_rating
        ]
        if scores:
            return round(sum(scores) / len(scores))
        if child_item.user_rating:
            return child_item.user_rating
        if item.user_rating:
            return item.user_rating
        return None

    async def _calculate_progress(
        self,
        *,
        item: LibraryShow,
        child_item: LibrarySeason,
        grandchild_items: Sequence[LibraryEpisode],
        entry: ListEntry,
    ) -> int | None:
        watched = len([episode for episode in grandchild_items if episode.view_count])
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
    ) -> str | None:
        if entry.media().total_units == 1 and len(grandchild_items) == 1:
            review = await grandchild_items[0].review
            if review:
                return review
        return await child_item.review or await item.review

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

    @glru_cache(maxsize=32, key=lambda self, item: item)
    def __get_wanted_seasons(self, item: LibraryShow) -> dict[int, LibrarySeason]:
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

    @glru_cache(maxsize=32, key=lambda self, item: item)
    def __get_wanted_episodes(self, item: LibraryShow) -> list[LibraryEpisode]:
        seasons = self.__get_wanted_seasons(item)
        if not seasons:
            return []
        return [
            episode for episode in item.episodes() if episode.season_index in seasons
        ]

    @gattl_cache(ttl=15, key=lambda self, item, episodes: (item, tuple(episodes)))
    async def _filter_history_by_episodes(
        self, item: LibraryShow, episodes: Sequence[LibraryEpisode]
    ) -> list[HistoryEntry]:
        episode_keys = {episode.key for episode in episodes}
        history = await item.history()
        filtered = [entry for entry in history if entry.library_key in episode_keys]
        filtered.sort(key=lambda record: record.viewed_at)
        return filtered
