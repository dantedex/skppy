# SPDX-License-Identifier: MIT
"""Common legacy model and entity payload bodies."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, BinaryIO

from ..data_structure.model_metadata import RenderingOptions

from .parser_types import (
    ComponentBehaviorState,
    EntityHeaderState,
    ModelPreamblePayload,
    RootModelPrefixState,
)
from .binary import ArchiveObjectTag, LegacyArchiveReader
from .image_payloads import read_dib_payload
from .rendering_options import read_rendering_options_payload

if TYPE_CHECKING:
    from .read_context import ObjectReadContext


def read_root_model_prefix(stream: BinaryIO, model_class_version: int) -> RootModelPrefixState:
    """Read the confirmed leading fields of a legacy model payload."""
    reader = LegacyArchiveReader(stream)
    state = RootModelPrefixState()
    state.class_version = model_class_version
    state.payload_start_offset = reader.tell()
    if model_class_version >= 7:
        state.unknown_u32_a = reader.read_u32()
        state.unknown_u32_b = reader.read_u32()
    if model_class_version >= 18:
        state.license_product_family = reader.read_u32()
    if model_class_version >= 26:
        state.next_persistent_id = reader.read_u64()
    if model_class_version > 3:
        state.thumbnail_object_tag = reader.read_object_tag()
        # The root thumbnail predates normal session dispatch and is serialized
        # inline, but its class/object slots are seeded later in parser.py.
        if state.thumbnail_object_tag.kind == "new_class" and state.thumbnail_object_tag.class_name == "CDib":
            state.thumbnail = read_dib_payload(
                stream,
                object_tag=state.thumbnail_object_tag,
                dib_class_version=state.thumbnail_object_tag.schema or 0,
            )
        state.redefine_thumbnail_on_save = reader.read_bool()
    state.prefix_end_offset = reader.tell()
    return state


def read_entity_header_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_reference: Callable[[], ArchiveObjectTag],
) -> EntityHeaderState:
    """Read common ``CEntity`` fields with injected reference handling."""
    start = reader.tell()
    legacy_flags = None
    attribute_tag = None
    persistent_id = None
    if class_version == 1:
        legacy_flags = reader.read_u32()
    elif class_version > 2:
        # The attribute container may be null, a back-reference, or a complete
        # inline object. ObjectReadContext supplies the resolver-aware callback.
        attribute_tag = read_reference()
        if class_version == 4:
            persistent_id = reader.read_u64()
        elif class_version > 4:
            persistent_id = _read_sparse_u64(reader)
    # EntityHeaderState is shared by many derived payloads. Atomic construction
    # prevents a partially read base from escaping into one of those objects.
    return EntityHeaderState(
        class_version=class_version,
        payload_start_offset=start,
        legacy_flags_u32=legacy_flags,
        attribute_container_tag=attribute_tag,
        persistent_id=persistent_id,
        header_end_offset=reader.tell(),
    )


def _read_sparse_u64(reader: LegacyArchiveReader) -> int:
    """Decode the sparse eight-byte integer representation."""
    populated_bytes = reader.read_u8()
    value = 0
    # Each bit announces whether the corresponding little-endian byte follows;
    # absent bytes are zero and consume no stream space.
    for byte_index in range(8):
        if populated_bytes & (1 << byte_index):
            value |= reader.read_u8() << (byte_index * 8)
    return value


def read_component_behavior_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    object_tag: ArchiveObjectTag | None,
    payload_start_offset: int,
    entity_header: EntityHeaderState,
) -> ComponentBehaviorState:
    """Read ``CComponentBehavior`` fields after its entity header."""
    if class_version < 3:
        # Older constructors implied 2-D behavior instead of serializing it.
        is_2d = True
        cuts_opening = reader.read_bool()
        snap_to = reader.read_u32() if class_version == 2 else 0
    else:
        is_2d = reader.read_bool()
        cuts_opening = reader.read_bool()
        snap_to = reader.read_u32()
    # Bit 0 is always-face-camera; bit 1 makes billboard shadows face the sun.
    camera_flags = reader.read_u8() if class_version > 3 else 0
    no_scale_mask = reader.read_u32() if class_version >= 5 else 0
    # This technical state is immutable once decoded; all version-gated fields
    # must therefore be consumed before constructing it.
    return ComponentBehaviorState(
        class_version=class_version,
        object_tag=object_tag,
        payload_start_offset=payload_start_offset,
        entity_header=entity_header,
        is_2d=is_2d,
        cuts_opening=cuts_opening,
        snap_to=snap_to,
        always_face_camera=bool(camera_flags & 0x01),
        shadows_face_sun=bool(camera_flags & 0x02),
        no_scale_mask=no_scale_mask,
        payload_end_offset=reader.tell(),
    )


def read_component_behavior(
    context: ObjectReadContext,
    *,
    object_tag: ArchiveObjectTag | None,
    class_version: int,
) -> ComponentBehaviorState:
    """Read an archive component-behavior object with its entity base."""
    start = context.session.reader.tell()
    return read_component_behavior_body(
        context.session.reader,
        class_version=class_version,
        object_tag=object_tag,
        payload_start_offset=start,
        entity_header=context.read_entity(),
    )


def read_model_payload_preamble(
    stream: BinaryIO,
    *,
    entity_class_version: int,
    component_behavior_class_version: int,
) -> ModelPreamblePayload:
    """Read root component behavior and the model description."""
    reader = LegacyArchiveReader(stream)
    start = reader.tell()
    behavior_start = reader.tell()
    entity_header = read_entity_header_body(
        reader,
        class_version=entity_class_version,
        read_reference=reader.read_object_tag,
    )
    behavior = read_component_behavior_body(
        reader,
        class_version=component_behavior_class_version,
        object_tag=None,
        payload_start_offset=behavior_start,
        entity_header=entity_header,
    )
    description = reader.read_legacy_utf16_string("model description")
    return start, behavior, description, reader.tell()


def read_rendering_options(
    stream: BinaryIO,
    *,
    entity_class_version: int,
    rendering_options_class_version: int,
) -> RenderingOptions:
    """Read untagged rendering options from the root model payload."""
    reader = LegacyArchiveReader(stream)
    read_entity_header_body(
        reader,
        class_version=entity_class_version,
        read_reference=reader.read_object_tag,
    )
    return read_rendering_options_payload(reader, rendering_options_class_version)
