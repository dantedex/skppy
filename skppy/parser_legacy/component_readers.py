# SPDX-License-Identifier: MIT
"""Archive adapters for legacy component instances and derived entities."""

from __future__ import annotations

from ..data_structure.entities import (
    ComponentDefinition,
    ComponentInstance,
    Group,
    Image,
)

from .parser_types import ComponentDefinitionState
from .base_payloads import read_component_behavior_body
from .binary import ArchiveObjectTag
from .component_payloads import (
    component_instance_as_group,
    component_instance_as_image,
    read_component_instance_body,
)
from .component_body import read_component_body
from .read_context import ObjectReadContext


def read_component_definition(
    context: ObjectReadContext,
    *,
    object_tag: ArchiveObjectTag,
    object_index: int | None,
    component_class_version: int,
    class_version: int,
) -> ComponentDefinitionState:
    """Read a component definition and retain unresolved child entities."""
    if component_class_version != 11:
        raise NotImplementedError("Only SketchUp 8 CComponent version 11 is decoded.")
    if class_version not in {10, 11}:
        raise NotImplementedError("Only CComponentDefinition versions 10 and 11 are decoded.")

    reader = context.session.reader
    component = read_component_body(context)
    definition = ComponentDefinition()
    definition.guid = reader.read_exact(16, "component definition guid")
    definition.name = reader.read_legacy_utf16_string("component definition name")
    definition.description = reader.read_legacy_utf16_string("component definition description")
    definition.loaded_from = reader.read_legacy_utf16_string("component definition path")
    definition.timestamp = reader.read_u32()
    definition.modified = reader.read_bool()
    reader.read_vec3_f64()
    behavior_start = reader.tell()
    behavior_entity = context.read_entity()
    behavior = read_component_behavior_body(
        reader,
        class_version=context.class_versions.get("CComponentBehavior", 5),
        object_tag=None,
        payload_start_offset=behavior_start,
        entity_header=behavior_entity,
    )
    definition.definition_type = reader.read_u32()
    _, thumbnail_object = context.read_object()
    if isinstance(thumbnail_object, bytes):
        definition.packed_payload = thumbnail_object
    definition.behavior_snap_mode = behavior.snap_to
    definition.behavior_no_scale_mask = behavior.no_scale_mask
    definition.behavior_snap_enabled = behavior.is_2d or bool(behavior.snap_to)
    definition.behavior_cuts_opening = behavior.cuts_opening
    definition.behavior_always_face_camera = behavior.always_face_camera
    # The public definition remains mutable, while this immutable wrapper binds
    # it to archive identity and the complete unresolved entity collection.
    return ComponentDefinitionState(
        object_tag=object_tag,
        object_index=object_index,
        definition=definition,
        entity_payloads=component.entities,
        material_manager=component.materials,
        relationships=component.relationships,
    )


def read_component_instance(
    context: ObjectReadContext,
    *,
    class_version: int,
) -> ComponentInstance:
    """Read a component instance into the shared entity type."""
    drawing_element = context.read_drawing_element()
    definition_tag, _ = context.read_object()
    instance = read_component_instance_body(
        context.session.reader,
        class_version=class_version,
        definition_id=definition_tag.index or 0,
        material_id=drawing_element.material_tag.index or None,
    )
    instance.layer_id = drawing_element.layer_tag.index if drawing_element.layer_tag is not None else None
    return instance


def read_group(
    context: ObjectReadContext,
    *,
    class_version: int,
    component_instance_version: int,
) -> Group:
    """Read the component-instance base of a group."""
    return component_instance_as_group(
        read_component_instance(
            context,
            class_version=component_instance_version,
        ),
        class_version=class_version,
    )


def read_image(
    context: ObjectReadContext,
    *,
    class_version: int,
    component_instance_version: int,
) -> Image:
    """Read the component-instance base of an image entity."""
    return component_instance_as_image(
        read_component_instance(
            context,
            class_version=component_instance_version,
        ),
        class_version=class_version,
    )
