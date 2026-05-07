"""Helpers for resolving deterministic list targets from library mappings."""

from collections.abc import Iterable, Sequence
from typing import Any

import msgspec
from anibridge.library import LibraryEntry
from anibridge.list import ListEntry, ListProvider
from anibridge.utils.mappings import AnibridgeDescriptorMapping, descriptor_key
from anibridge.utils.types import MappingDescriptor

from anibridge.app.core.animap import AnimapClient
from anibridge.app.core.sync.stats import EntrySnapshot

__all__ = [
    "ResolvedListTarget",
    "SyncTarget",
    "diff_snapshots",
    "find_best_search_result",
    "resolve_list_targets",
    "resolve_list_targets_batch",
]


def diff_snapshots(
    before: EntrySnapshot | None,
    after: EntrySnapshot | None,
    fields: Iterable[str],
) -> dict[str, tuple[Any, Any]]:
    """Compute differences between two snapshots."""
    diff: dict[str, tuple[Any, Any]] = {}
    before_map = msgspec.structs.asdict(before) if before else {}
    after_map = msgspec.structs.asdict(after) if after else {}
    for field in fields:
        if before_map.get(field) != after_map.get(field):
            diff[field] = (before_map.get(field), after_map.get(field))
    return diff


def find_best_search_result(
    title: str,
    results: Sequence[ListEntry],
    threshold: int,
) -> ListEntry | None:
    """Return the highest-scoring fuzzy match for a title."""
    from rapidfuzz import fuzz

    best_entry: ListEntry | None = None
    best_ratio = 0
    for entry in results:
        candidates = {entry.title}
        media_title = entry.media().title
        if media_title:
            candidates.add(media_title)
        for candidate in candidates:
            if not candidate:
                continue
            ratio = fuzz.ratio(title, candidate)
            if ratio > best_ratio:
                best_ratio = ratio
                best_entry = entry
    if best_ratio < threshold:
        return None
    return best_entry


class SyncTarget(msgspec.Struct, frozen=True):
    """Resolved list target for a library media item."""

    list_media_key: str
    entry: ListEntry
    mappings: tuple[AnibridgeDescriptorMapping, ...] = ()


class ResolvedListTarget(msgspec.Struct, frozen=True):
    """Resolved list key with explicit descriptor mappings."""

    list_media_key: str
    mappings: tuple[AnibridgeDescriptorMapping, ...] = ()


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


def _build_mappings_by_target(
    grouped_edges: dict[
        MappingDescriptor,
        dict[MappingDescriptor, list[tuple[str, str | None]]],
    ],
) -> dict[MappingDescriptor, dict[MappingDescriptor, AnibridgeDescriptorMapping]]:
    """Convert grouped animap edges into explicit descriptor mappings."""
    mappings_by_target: dict[
        MappingDescriptor,
        dict[MappingDescriptor, AnibridgeDescriptorMapping],
    ] = {}
    for target_descriptor, sources in grouped_edges.items():
        source_map: dict[MappingDescriptor, AnibridgeDescriptorMapping] = {}
        for source_descriptor, source_ranges in sources.items():
            descriptor_mapping = AnibridgeDescriptorMapping(
                source=source_descriptor,
                target=target_descriptor,
            )
            for source_range, destination_range in source_ranges:
                if destination_range is None:
                    continue
                descriptor_mapping.add_mapping(
                    source_range=source_range,
                    target_ranges=destination_range,
                )
            descriptor_mapping.mappings[:] = [
                mapping_entry
                for mapping_entry in descriptor_mapping.mappings
                if mapping_entry.target_ratio != 0
            ]
            if descriptor_mapping.mappings:
                source_map[source_descriptor] = descriptor_mapping
        if source_map:
            mappings_by_target[target_descriptor] = source_map
    return mappings_by_target


async def resolve_list_targets_batch(
    *,
    animap_client: AnimapClient,
    list_provider: ListProvider,
    descriptor_sets: Sequence[Sequence[MappingDescriptor]],
) -> list[tuple[ResolvedListTarget, ...]]:
    """Resolve mapping descriptors into deterministic list targets."""
    normalized: list[tuple[MappingDescriptor, ...]] = []
    all_descriptors: set[MappingDescriptor] = set()
    for descriptor_set in descriptor_sets:
        ordered = tuple(dict.fromkeys(descriptor_set))
        normalized.append(ordered)
        all_descriptors.update(ordered)

    if not all_descriptors:
        return [tuple() for _ in normalized]

    grouped_edges = animap_client.resolve_edges_grouped(
        tuple(all_descriptors),
        target_providers=list_provider.MAPPING_PROVIDERS,
    )
    mappings_by_target = _build_mappings_by_target(grouped_edges)

    direct_targets = {
        descriptor
        for descriptor in all_descriptors
        if descriptor[0] in list_provider.MAPPING_PROVIDERS
    }
    target_descriptors = {*mappings_by_target.keys(), *direct_targets}
    if not target_descriptors:
        return [tuple() for _ in normalized]

    resolved_targets = await list_provider.resolve_mapping_descriptors(
        tuple(target_descriptors)
    )

    results: list[tuple[ResolvedListTarget, ...]] = []
    for descriptor_set in normalized:
        wanted = set(descriptor_set)
        descriptor_order = {
            descriptor: index for index, descriptor in enumerate(descriptor_set)
        }
        grouped_mapping_key = tuple[str, str, tuple[tuple[str, str], ...]]
        grouped: dict[
            str,
            dict[grouped_mapping_key, AnibridgeDescriptorMapping],
        ] = {}

        for target in resolved_targets:
            selected_mappings = [
                mapping
                for source_descriptor, mapping in mappings_by_target.get(
                    target.descriptor, {}
                ).items()
                if source_descriptor in wanted
            ]
            if target.descriptor not in wanted and not selected_mappings:
                continue

            group = grouped.setdefault(target.media_key, {})
            for mapping in selected_mappings:
                group.setdefault(_mapping_signature(mapping), mapping)

        results.append(
            tuple(
                ResolvedListTarget(
                    list_media_key=media_key,
                    mappings=tuple(
                        sorted(
                            grouped[media_key].values(),
                            key=lambda mapping: (
                                descriptor_order.get(
                                    mapping.source,
                                    len(descriptor_order),
                                ),
                                descriptor_key(mapping.target),
                            ),
                        )
                    ),
                )
                for media_key in sorted(grouped)
            )
        )

    return results


async def resolve_list_targets(
    *,
    animap_client: AnimapClient,
    list_provider: ListProvider,
    media_items: Sequence[LibraryEntry],
) -> tuple[ResolvedListTarget, ...]:
    """Resolve mapping descriptors for one logical media item."""
    descriptors: list[MappingDescriptor] = []
    for media in media_items:
        descriptors.extend(media.mapping_descriptors())
    resolved = await resolve_list_targets_batch(
        animap_client=animap_client,
        list_provider=list_provider,
        descriptor_sets=[descriptors],
    )
    return resolved[0] if resolved else tuple()
