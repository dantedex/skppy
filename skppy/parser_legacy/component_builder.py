# SPDX-License-Identifier: MIT
"""Finalize legacy component definitions into the shared model graph."""

from __future__ import annotations

from collections.abc import Mapping

from ..data_structure.entities import (
    ComponentDefinition,
)
from ..data_structure.model import Model

from .parser_types import ComponentDefinitionState
from .parser_types import SupportedObjectPayload
from .entity_builder import (
    curve_payloads_by_archive_index,
    index_archive_object_identities,
    populate_entities,
)
from .material_builder import material_ids_by_archive_index
from .provenance import ArchiveProvenance


def populate_definitions(
    model: Model,
    provenance: ArchiveProvenance,
    *,
    material_id_by_object_index: dict[int, int] | None = None,
    archive_indices_by_identity: dict[int, tuple[int, ...]] | None = None,
    objects_by_archive_index: Mapping[int, SupportedObjectPayload] | None = None,
) -> dict[int, ComponentDefinition]:
    """Allocate definitions and return their archive-index lookup.

    Component placement belongs to the entity collections serialized by the
    archive. A definition being unreferenced by another definition does not
    imply that SketchUp placed one identity-transformed instance at model root.
    """
    archived_definitions: list[tuple[ComponentDefinitionState, ComponentDefinition]] = []
    definitions_by_archive_index: dict[int, ComponentDefinition] = {}
    definitions_by_guid: dict[bytes, ComponentDefinition] = {}
    for state in _definition_payloads(provenance):
        if state.object_index in definitions_by_archive_index:
            continue
        existing = definitions_by_guid.get(state.definition.guid)
        if existing is not None:
            if state.object_index is not None:
                definitions_by_archive_index[state.object_index] = existing
            continue
        definition = state.definition
        definitions_by_guid[definition.guid] = definition
        definition.id = model._alloc_id()
        model.definitions.append(definition)
        archived_definitions.append((state, definition))
        if state.object_index is not None:
            definitions_by_archive_index[state.object_index] = definition

    materials = (
        material_id_by_object_index
        if material_id_by_object_index is not None
        else material_ids_by_archive_index(model, provenance)
    )
    curves = curve_payloads_by_archive_index(provenance)
    object_indices = (
        archive_indices_by_identity
        if archive_indices_by_identity is not None
        else index_archive_object_identities(provenance.archive_objects)
    )
    archived_objects = (
        objects_by_archive_index if objects_by_archive_index is not None else dict(provenance.archive_objects)
    )
    layers = {
        state.object_tag.index: state.layer.id
        for state in provenance.archived_layers
        if state.object_tag.index is not None
    }
    for state, definition in archived_definitions:
        populate_entities(
            definition.entities,
            state.entity_payloads,
            definitions_by_archive_index,
            material_id_by_object_index=materials,
            curve_by_object_index=curves,
            layer_id_by_object_index=layers,
            relationships=state.relationships,
            archive_objects=provenance.archive_objects,
            archive_indices_by_identity=object_indices,
            objects_by_archive_index=archived_objects,
            attribute_container_indices_by_owner=(provenance.attribute_container_indices_by_owner),
        )
    return definitions_by_archive_index


def _definition_payloads(
    provenance: ArchiveProvenance,
) -> tuple[ComponentDefinitionState, ...]:
    direct = tuple(
        payload for _, payload in provenance.archive_objects if isinstance(payload, ComponentDefinitionState)
    )
    direct_ids = {id(payload) for payload in direct}
    return direct + tuple(
        payload
        for payload in provenance.root_objects
        if isinstance(payload, ComponentDefinitionState) and id(payload) not in direct_ids
    )
