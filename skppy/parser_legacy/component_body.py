# SPDX-License-Identifier: MIT
"""Version-aware reader for the common SketchUp 8 ``CComponent`` body."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeGuard

from ..data_structure.layers import LayerFolder

from .binary import ArchiveObjectTag
from .component_payloads import read_definition_list_payload
from .layer_payloads import read_layer_manager
from .material_payloads import read_material_manager
from .parser_types import (
    DrawingElementState,
    LayerState,
    MaterialState,
    RelationshipCollection,
    RelationshipReferences,
    SupportedObjectPayload,
)
from .read_context import ObjectReadContext


@dataclass
class ComponentBodyState:
    """Decoded collections plus technical references owned by a component."""

    payload_start_offset: int
    drawing_element: DrawingElementState
    materials: tuple[MaterialState, ...] = ()
    layers: tuple[LayerState, ...] = ()
    layer_folders: tuple[LayerFolder, ...] = ()
    active_layer_tag: ArchiveObjectTag | None = None
    layer_manager_start_offset: int = 0
    layer_manager_end_offset: int = 0
    definition_tags: tuple[ArchiveObjectTag, ...] = ()
    definition_list_start_offset: int = 0
    definition_list_end_offset: int = 0
    entity_count: int = 0
    entities: tuple[SupportedObjectPayload, ...] = ()
    entity_children: tuple[SupportedObjectPayload, ...] = ()
    relationships: RelationshipCollection = ()
    active_section_plane_tag: ArchiveObjectTag | None = None
    payload_end_offset: int = 0


def read_component_body(context: ObjectReadContext) -> ComponentBodyState:
    """Read the complete common body serialized by SketchUp 8 CComponent v11."""
    session = context.session
    versions = context.class_versions
    # CComponent is a serialized owner, not just an entity list. Its managers
    # and definition table precede geometry and share the surrounding archive
    # object table with every nested value.
    state = ComponentBodyState(
        payload_start_offset=session.tell(),
        drawing_element=context.read_drawing_element(),
    )
    state.materials = read_material_manager(
        context,
        class_version=versions.get("CMaterialManager", 4),
    )
    (
        state.layers,
        state.active_layer_tag,
        state.layer_folders,
        state.layer_manager_start_offset,
        state.layer_manager_end_offset,
    ) = read_layer_manager(context, class_version=versions.get("CLayerManager", 4))
    (
        state.definition_tags,
        state.definition_list_start_offset,
        state.definition_list_end_offset,
    ) = read_definition_list_payload(
        session,
        class_version=versions.get("CDefinitionList", 0),
        resolve=context.resolve,
    )
    state.entity_count = session.reader.read_u32()
    entities: list[SupportedObjectPayload] = []
    entity_children: list[SupportedObjectPayload] = []
    for _ in range(state.entity_count):
        # One top-level entity can recursively decode vertices, edges, curves,
        # or attributes. Preserve those children for later graph assembly even
        # though only the requested object belongs in `entities`.
        object_checkpoint = session.object_checkpoint()
        value = context.read_object()[1]
        entities.append(value)
        entity_children.extend(child for child in session.objects_since(object_checkpoint) if child is not value)
    state.entities = tuple(entities)
    state.entity_children = tuple(entity_children)

    # Relationships are archive bookkeeping consumed after the visible entity
    # sequence. Keep valid pairs but do not expose malformed payload shapes.
    relationship_count = session.reader.read_u32()
    state.relationships = tuple(
        value for _ in range(relationship_count) if _is_relationship((value := context.read_object()[1]))
    )
    # This final reference marks the end of CComponent v11 and may introduce
    # the section plane inline on first use.
    state.active_section_plane_tag = context.read_reference(resolve_new=True)
    state.payload_end_offset = session.tell()
    return state


def _is_relationship(value: object) -> TypeGuard[RelationshipReferences]:
    """Return whether a resolved payload is one relationship reference pair."""
    return isinstance(value, tuple) and len(value) == 2 and all(isinstance(item, ArchiveObjectTag) for item in value)
