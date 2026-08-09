# SPDX-License-Identifier: MIT
"""SketchUp 8 scene/page preview readers."""

from __future__ import annotations

import io
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import BinaryIO

from ..data_structure.construction import Camera, ShadowInfo
from ..data_structure.model_metadata import ModelViewAxes
from ..data_structure.scene_data import PageBackgroundImage, Scene

from .binary import ArchiveObjectHandle, ArchiveObjectTag, LegacyArchiveReader
from .camera_payloads import read_old_camera_payload
from .parser_types import SceneState
from .metadata_payloads import read_axes_payload, read_shadow_payload
from .read_context import ObjectReadContext
from .rendering_options import read_rendering_options_payload
from .session import LegacyArchiveSession

SCENE_FLAG_USE_CAMERA = 0x0001
SCENE_FLAG_USE_RENDERING_OPTIONS = 0x0002
SCENE_FLAG_USE_SHADOW_INFO = 0x0004
SCENE_FLAG_USE_AXES = 0x0008
SCENE_FLAG_USE_HIDDEN = 0x0010
SCENE_FLAG_USE_LAYER_VISIBILITY = 0x0020
SCENE_FLAG_USE_SECTION_PLANES = 0x0040


def read_scene_identity(reader: LegacyArchiveReader, *, class_version: int) -> Scene:
    """Read the shared name and description from a ``CSketchUpPage`` body."""
    if class_version != 1:
        raise NotImplementedError("Only SketchUp 8 CSketchUpPage version 1 is decoded.")
    return Scene(
        id=0,
        name=reader.read_legacy_utf16_string("CSketchUpPage name"),
        description=reader.read_legacy_utf16_string("CSketchUpPage description"),
    )


def read_image_rep_payload(stream: BinaryIO) -> bytes:
    """Read the ImageFileRep payload embedded in a legacy ``CViewPage``."""
    reader = LegacyArchiveReader(stream)
    if not reader.read_bool():
        return b""
    image_size = reader.read_u32()
    return reader.read_exact(image_size, "CViewPage ImageRep bytes")


def read_optional_object_refs(session: LegacyArchiveSession, *, present: bool) -> tuple[ArchiveObjectTag, ...]:
    """Read a conditional array of archive object references."""
    if not present:
        return ()
    count = session.reader.read_u32()
    return tuple(session.read_object_handle().tag for _ in range(count))


def read_page_list_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_object: Callable[[], object],
) -> tuple[Scene, ...]:
    """Read a ``CPageList`` body after its entity header."""
    if class_version != 1:
        raise NotImplementedError("Only SketchUp 8 CPageList version 1 is decoded.")
    page_count = reader.read_u32()
    pages: list[Scene] = []
    for _ in range(page_count):
        value = read_object()
        if isinstance(value, Scene):
            pages.append(value)
        elif isinstance(value, SceneState):
            pages.append(value.scene)
    read_object()  # Active page runtime state has no shared model field.
    return tuple(pages)


def read_page(context: ObjectReadContext, *, class_version: int) -> Scene:
    """Read a SketchUp page directly into the shared scene type."""
    context.read_entity()
    return read_scene_identity(context.session.reader, class_version=class_version)


def read_page_list(context: ObjectReadContext, *, class_version: int) -> tuple[Scene, ...]:
    """Read a page list into a sequence of shared scenes."""
    context.read_entity()
    return read_page_list_body(
        context.session.reader,
        class_version=class_version,
        read_object=lambda: context.read_object()[1],
    )


def read_axes(context: ObjectReadContext, *, class_version: int) -> ModelViewAxes:
    """Read model axes directly into shared metadata."""
    context.read_drawing_element()
    return read_axes_payload(context.session.reader, class_version)


def read_shadow_info(context: ObjectReadContext, *, class_version: int) -> ShadowInfo:
    """Read shadow settings after their common entity prefix."""
    context.read_entity()
    return read_shadow_payload(context.session.reader, class_version)


def _apply_scene_flags(state: SceneState, flags: int) -> None:
    """Expose the serialized snapshot-presence mask as named booleans."""
    state.use_camera = bool(flags & SCENE_FLAG_USE_CAMERA)
    state.use_rendering_options = bool(flags & SCENE_FLAG_USE_RENDERING_OPTIONS)
    state.use_shadow_info = bool(flags & SCENE_FLAG_USE_SHADOW_INFO)
    state.use_axes = bool(flags & SCENE_FLAG_USE_AXES)
    state.use_hidden = bool(flags & SCENE_FLAG_USE_HIDDEN)
    state.use_layer_visibility = bool(flags & SCENE_FLAG_USE_LAYER_VISIBILITY)
    state.use_section_planes = bool(flags & SCENE_FLAG_USE_SECTION_PLANES)


def _read_scene_snapshots(context: ObjectReadContext, state: SceneState, class_version: int) -> None:
    """Read only snapshots whose flags say their bytes are present."""
    reader = context.session.reader
    if state.use_camera:
        if class_version < 7:
            state.camera_tag = _implicit_tag("CCamera", 0)
            state.scene.camera = read_old_camera_payload(reader)
        else:
            state.camera_tag, camera_object = context.read_object()
            state.scene.camera = camera_object if isinstance(camera_object, Camera) else None
    if state.use_rendering_options:
        context.read_entity()
        state.rendering_options = read_rendering_options_payload(
            reader,
            context.class_versions.get("CRenderingOptions", 36),
        )
        if class_version > 9:
            style_handle = context.session.read_object_handle()
            if style_handle.kind == "new_object":
                context.resolve(style_handle)
            state.style_tag = replace(style_handle.tag, index=style_handle.object_index)
    if state.use_shadow_info:
        state.shadow_info_tag = _implicit_tag("CShadowInfo", context.class_versions.get("CShadowInfo", 7))
        state.shadow_info = read_shadow_info(
            context,
            class_version=context.class_versions.get("CShadowInfo", 7),
        )
        state.shadow_info_display_shadows = reader.read_bool()
    if state.use_axes:
        state.axes_tag = _implicit_tag("CSketchCS", context.class_versions.get("CSketchCS", 0))
        state.axes = read_axes(
            context,
            class_version=context.class_versions.get("CSketchCS", 0),
        )
        state.axes_display = reader.read_bool()


def _read_scene_reference_sets(context: ObjectReadContext, state: SceneState) -> None:
    """Read the three conditional counted reference arrays in wire order."""
    state.hidden_entity_tags = read_optional_object_refs(context.session, present=state.use_hidden)
    state.hidden_layer_tags = read_optional_object_refs(context.session, present=state.use_layer_visibility)
    state.active_section_plane_tags = read_optional_object_refs(context.session, present=state.use_section_planes)


def _read_scene_slideshow_fields(reader: LegacyArchiveReader, state: SceneState, class_version: int) -> None:
    """Read slideshow visibility, historical watermark, and timing values."""
    state.scene.show_in_slideshow = reader.read_bool()
    if 6 <= class_version <= 10:
        reader.read_bool()  # Historical display-watermarks scene setting.
    if class_version >= 8:
        state.transition_time = reader.read_f64()
    if class_version >= 9:
        state.delay_time = reader.read_f64()


def _read_scene_background(context: ObjectReadContext, state: SceneState, class_version: int) -> None:
    """Read optional background references and the schema-12 image snapshot."""
    handle = _null_handle()
    background_image = None
    if class_version > 9:
        handle, value = context.read_handle()
        background_image = value if isinstance(value, PageBackgroundImage) else None
    state.background_image_tag = handle.tag
    if class_version >= 12:
        state.scene.display_background_image = context.session.reader.read_bool()
        state.image_rep_present = context.session.reader.read_bool()
        state.image_rep = read_image_rep_payload(context.session.stream) if state.image_rep_present else None
    state.scene.style_reference = (state.style_tag.index or 0) if state.style_tag is not None else 0
    state.scene.background_image_ref = handle.object_index or 0
    state.scene.background_image = background_image


def read_view_page(
    context: ObjectReadContext,
    *,
    object_tag: ArchiveObjectTag,
    class_version: int,
    page_class_version: int,
) -> SceneState:
    """Read a version-aware pre-ZIP view page and its optional snapshots."""
    if class_version not in {6, 9, 11, 12, 13}:
        raise NotImplementedError("Only observed pre-ZIP CViewPage versions 6, 9, 11, 12, and 13 are decoded.")

    reader = context.session.reader
    start = reader.tell()
    page = read_page(context, class_version=page_class_version)
    flags = reader.read_u32()
    state = SceneState(
        object_tag=object_tag,
        class_version=class_version,
        scene=page,
        payload_start_offset=start,
    )
    _apply_scene_flags(state, flags)
    # Presence flags control whether snapshot bytes exist at all; a disabled
    # field has no placeholder and therefore must not advance the stream.
    _read_scene_snapshots(context, state, class_version)
    _read_scene_reference_sets(context, state)
    # Hidden sets are counted object-reference arrays. Their members may be
    # absent from the final public graph but still occupy archive table slots.
    _read_scene_slideshow_fields(reader, state, class_version)
    _read_scene_background(context, state, class_version)
    page.flags = flags
    state.payload_end_offset = reader.tell()
    return state


def _implicit_tag(class_name: str, schema: int) -> ArchiveObjectTag:
    return ArchiveObjectTag(
        kind="new_class",
        raw_tag=0xFFFF,
        schema=schema,
        class_name=class_name,
    )


def _null_handle() -> ArchiveObjectHandle:
    """Return the same null handle shape produced by archive sessions."""
    return ArchiveObjectHandle("null", ArchiveObjectTag("null", 0, 0), 0, None, None, None)


@dataclass(frozen=True, slots=True)
class RecoveredSceneState:
    """Minimal preview of a SketchUp 8 scene/page object."""

    object_tag: ArchiveObjectTag
    payload_start_offset: int
    name: str
    description: str
    flags_u32: int | None
    include_in_animation: bool | None
    transition_time: float | None
    delay_time: float | None
    timing_offset: int | None
    use_camera: bool | None
    use_rendering_options: bool | None
    use_shadow_info: bool | None
    use_axes: bool | None
    use_hidden: bool | None
    use_layer_visibility: bool | None
    use_section_planes: bool | None
    raw_tail_payload: bytes
    payload_end_offset: int


def read_view_page_preview_from_span(
    data: bytes,
    *,
    tag_offset: int,
    payload_end_offset: int,
    absolute_start: int,
) -> RecoveredSceneState:
    """Read the confirmed prefix of a ``CViewPage`` record from a byte span."""
    stream = io.BytesIO(data[tag_offset:payload_end_offset])
    reader = LegacyArchiveReader(stream)
    tag = reader.read_object_tag()
    if tag.kind == "new_class" and tag.class_name != "CViewPage":
        raise ValueError(f"Expected CViewPage, got {tag.class_name!r}.")
    if tag.kind not in {"new_class", "class_ref"}:
        raise ValueError(f"Expected CViewPage object tag, got {tag.kind!r}.")

    payload_start = absolute_start + tag_offset + reader.tell()
    entity_tag = reader.read_object_tag()
    if entity_tag.kind != "null":
        raise ValueError("Only CViewPage records with a null CEntity tag are decoded.")

    name = reader.read_legacy_utf16_string("CViewPage name")
    description = reader.read_legacy_utf16_string("CViewPage description")
    raw_tail_start = tag_offset + reader.tell()
    raw_tail_payload = data[raw_tail_start:payload_end_offset]
    flags_u32, include_in_animation, transition_time, delay_time, timing_offset = read_scene_page_timing(
        raw_tail_payload
    )
    return RecoveredSceneState(
        object_tag=tag,
        payload_start_offset=payload_start,
        name=name,
        description=description,
        flags_u32=flags_u32,
        include_in_animation=include_in_animation,
        transition_time=transition_time,
        delay_time=delay_time,
        timing_offset=timing_offset,
        use_camera=_flag_enabled(flags_u32, SCENE_FLAG_USE_CAMERA),
        use_rendering_options=_flag_enabled(flags_u32, SCENE_FLAG_USE_RENDERING_OPTIONS),
        use_shadow_info=_flag_enabled(flags_u32, SCENE_FLAG_USE_SHADOW_INFO),
        use_axes=_flag_enabled(flags_u32, SCENE_FLAG_USE_AXES),
        use_hidden=_flag_enabled(flags_u32, SCENE_FLAG_USE_HIDDEN),
        use_layer_visibility=_flag_enabled(flags_u32, SCENE_FLAG_USE_LAYER_VISIBILITY),
        use_section_planes=_flag_enabled(flags_u32, SCENE_FLAG_USE_SECTION_PLANES),
        raw_tail_payload=raw_tail_payload,
        payload_end_offset=absolute_start + payload_end_offset,
    )


def read_scene_page_timing(
    raw_tail_payload: bytes,
) -> tuple[int | None, bool | None, float | None, float | None, int | None]:
    """Read confirmed scene flags and timing values from a ``CViewPage`` tail."""
    if len(raw_tail_payload) < 4:
        return (None, None, None, None, None)
    flags_u32 = struct.unpack_from("<I", raw_tail_payload, 0)[0]
    if not looks_like_scene_flags(flags_u32):
        return (None, None, None, None, None)

    timing = _find_scene_timing(raw_tail_payload)
    if timing is None:
        return (flags_u32, None, None, None, None)
    timing_offset, include_in_animation, transition_time, delay_time = timing
    return (
        flags_u32,
        include_in_animation,
        transition_time,
        delay_time,
        timing_offset,
    )


def looks_like_scene_name(name: str) -> bool:
    """Return whether a string looks like a plausible scene name."""
    return 1 <= len(name) <= 256 and name.isprintable()


def looks_like_scene_page_tail(raw_tail_payload: bytes) -> bool:
    """Return whether a byte span starts like the confirmed ``CViewPage`` tail."""
    if len(raw_tail_payload) < 4:
        return False
    return looks_like_scene_flags(struct.unpack_from("<I", raw_tail_payload, 0)[0])


def looks_like_scene_flags(value: int) -> bool:
    """Return whether a scene flag word is within the observed SketchUp 8 range."""
    return 0 <= value <= 0xFFFF


def _flag_enabled(flags: int | None, flag: int) -> bool | None:
    if flags is None:
        return None
    return bool(flags & flag)


def _find_scene_timing(
    raw_tail_payload: bytes,
) -> tuple[int, bool, float, float] | None:
    candidates: list[tuple[int, bool, float, float]] = []
    for offset in range(4, len(raw_tail_payload) - 16):
        include_raw = raw_tail_payload[offset]
        if include_raw not in {0, 1}:
            continue
        transition_time = struct.unpack_from("<d", raw_tail_payload, offset + 1)[0]
        delay_time = struct.unpack_from("<d", raw_tail_payload, offset + 9)[0]
        if _looks_like_scene_time(transition_time) and _looks_like_scene_time(delay_time):
            candidate = (offset, bool(include_raw), transition_time, delay_time)
            if transition_time == -1.0 and delay_time == -1.0:
                return candidate
            candidates.append(candidate)
    return candidates[0] if candidates else None


def _looks_like_scene_time(value: float) -> bool:
    return math.isfinite(value) and (value == -1.0 or value == 0.0 or 1.0e-6 <= value <= 86_400.0)
