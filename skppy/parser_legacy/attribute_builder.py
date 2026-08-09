# SPDX-License-Identifier: MIT
"""Resolve legacy attribute-container ownership into shared model mappings."""

from __future__ import annotations

from collections.abc import Mapping

from ..data_structure.model_metadata import AttributeDictionary

from .parser_types import SupportedObjectPayload


def attribute_dictionaries_by_owner_id(
    container_indices_by_owner: tuple[tuple[int, int], ...],
    archive_objects: tuple[tuple[int, SupportedObjectPayload], ...],
    owner_ids_by_archive_index: dict[int, int],
    *,
    objects_by_archive_index: Mapping[int, SupportedObjectPayload] | None = None,
) -> dict[int, list[AttributeDictionary]]:
    """Return named dictionaries grouped by a resolved public owner ID."""
    objects_by_index = objects_by_archive_index if objects_by_archive_index is not None else dict(archive_objects)
    dictionaries_by_owner_id: dict[int, list[AttributeDictionary]] = {}
    for owner_index, container_index in container_indices_by_owner:
        owner_id = owner_ids_by_archive_index.get(owner_index)
        if owner_id is None:
            continue
        dictionaries = attribute_dictionaries_for_container_index(container_index, objects_by_index)
        if dictionaries:
            dictionaries_by_owner_id.setdefault(owner_id, []).extend(dictionaries)
    return dictionaries_by_owner_id


def attribute_dictionaries_for_container_index(
    container_index: int | None,
    objects_by_index: Mapping[int, SupportedObjectPayload],
) -> list[AttributeDictionary]:
    """Return validated named dictionaries from one attribute container."""
    if container_index is None:
        return []
    container = objects_by_index.get(container_index)
    if not isinstance(container, tuple) or len(container) != 5:
        return []
    dictionaries = container[2]
    if not isinstance(dictionaries, tuple):
        return []
    named = [dictionary for dictionary in dictionaries if isinstance(dictionary, AttributeDictionary)]
    return named if len(named) == len(dictionaries) else []
