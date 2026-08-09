# SPDX-License-Identifier: MIT
"""Heuristic metadata scanners for SketchUp 8 legacy streams."""

from __future__ import annotations

import io
import math
import struct
from dataclasses import dataclass

from ..data_structure.construction import ShadowInfo
from ..data_structure.model_metadata import Font, ModelViewAxes, StyleDescriptor

from .binary import LegacyArchiveReader
from .scene_pages import (
    RecoveredSceneState,
    looks_like_scene_name,
    looks_like_scene_page_tail,
    read_view_page_preview_from_span,
)


@dataclass(frozen=True, slots=True)
class RecoveredShadowInfo:
    """Shared shadow data plus bounded recovery provenance."""

    payload_start_offset: int
    value: ShadowInfo
    payload_end_offset: int


@dataclass(frozen=True, slots=True)
class RecoveredModelViewAxes:
    """Shared model axes plus bounded recovery provenance."""

    payload_start_offset: int
    value: ModelViewAxes
    payload_end_offset: int


POST_LAYER_HEURISTIC_SCAN_BYTES = 1_048_576
SHADOW_AXES_HEURISTIC_SCAN_BYTES = 65_536
LEGACY_UTF16_STRING_PREFIXES = (b"\xff\xfe\xff", b"\xfe\xff\xff")
DEFAULT_MODEL_VIEW_AXES_BYTES = struct.pack(
    "<9d",
    1.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    1.0,
)


def _scan_scene_previews(data: bytes, *, absolute_start: int) -> tuple[RecoveredSceneState, ...]:
    previews: list[RecoveredSceneState] = []
    class_name = b"CViewPage"
    offset = _next_runtime_class_candidate(data, class_name, 0)
    while offset is not None:
        # A byte match is only a candidate. Validate the complete leading tag,
        # entity base, and two strings before treating it as a scene boundary.
        current_offset = offset
        stream = io.BytesIO(data[current_offset:])
        reader = LegacyArchiveReader(stream)
        try:
            reader.read_object_tag()
            entity_tag = reader.read_object_tag()
            if entity_tag.kind != "null":
                offset = _next_runtime_class_candidate(data, class_name, current_offset + 1)
                continue
            reader.read_legacy_utf16_string("CViewPage name")
            reader.read_legacy_utf16_string("CViewPage description")
            raw_tail_start = current_offset + reader.tell()
        except (EOFError, UnicodeDecodeError, ValueError):
            offset = _next_runtime_class_candidate(data, class_name, current_offset + 1)
            continue

        # Old page arrays may reuse a class_ref instead of spelling CViewPage
        # again. The next credible object marker bounds this page's raw tail.
        next_scene_ref_offset = _next_scene_page_ref_candidate(data, raw_tail_start)
        next_runtime_offset = _next_runtime_class_tag_offset(data, raw_tail_start)
        candidate_offsets = [value for value in (next_scene_ref_offset, next_runtime_offset) if value is not None]
        next_payload_offset = min(candidate_offsets) if candidate_offsets else len(data)
        try:
            previews.append(
                read_view_page_preview_from_span(
                    data,
                    tag_offset=current_offset,
                    payload_end_offset=next_payload_offset,
                    absolute_start=absolute_start,
                )
            )
        except (EOFError, UnicodeDecodeError, ValueError):
            offset = _next_runtime_class_candidate(data, class_name, current_offset + 1)
            continue
        if next_scene_ref_offset == next_payload_offset:
            offset = next_scene_ref_offset
        else:
            offset = _next_runtime_class_candidate(data, class_name, max(next_payload_offset, current_offset + 1))
    return tuple(previews)


def _next_scene_page_ref_candidate(data: bytes, start: int) -> int | None:
    offset = start
    while offset <= len(data) - 23:
        if data[offset + 1] & 0x80:
            stream = io.BytesIO(data[offset:])
            reader = LegacyArchiveReader(stream)
            try:
                tag = reader.read_object_tag()
                entity_tag = reader.read_object_tag()
                name = reader.read_legacy_utf16_string("CViewPage name")
                reader.read_legacy_utf16_string("CViewPage description")
                tail_start = offset + reader.tell()
            except (EOFError, UnicodeDecodeError, ValueError):
                offset += 1
                continue

            if (
                tag.kind == "class_ref"
                and entity_tag.kind == "null"
                and looks_like_scene_name(name)
                and looks_like_scene_page_tail(data[tail_start:])
            ):
                return offset
        offset += 1
    return None


def _next_runtime_class_candidate(data: bytes, class_name: bytes, start: int) -> int | None:
    name_header = len(class_name).to_bytes(2, "little") + class_name
    header_offset = data.find(name_header, start + 4)
    while header_offset >= 4:
        tag_offset = header_offset - 4
        if data[tag_offset : tag_offset + 2] == b"\xff\xff":
            return tag_offset
        header_offset = data.find(name_header, header_offset + 1)
    return None


def _next_runtime_class_tag_offset(data: bytes, start: int) -> int | None:
    offset = data.find(b"\xff\xff", start)
    while offset != -1 and offset <= len(data) - 6:
        schema = int.from_bytes(data[offset + 2 : offset + 4], "little")
        name_length = int.from_bytes(data[offset + 4 : offset + 6], "little")
        name_start = offset + 6
        name_end = name_start + name_length
        # 0xFFFF also appears naturally in arbitrary payloads. Schema, length,
        # bounds, and identifier shape together make a credible class marker.
        if (
            0 < schema < 10_000
            and 0 < name_length < 256
            and name_end <= len(data)
            and _looks_like_legacy_class_name(data[name_start:name_end])
        ):
            return offset
        offset = data.find(b"\xff\xff", offset + 1)
    return None


def _looks_like_legacy_class_name(name: bytes) -> bool:
    return name.startswith(b"C") and all(
        byte == ord("_") or ord("0") <= byte <= ord("9") or ord("A") <= byte <= ord("Z") or ord("a") <= byte <= ord("z")
        for byte in name
    )


def _scan_shadow_info(data: bytes, *, absolute_start: int) -> RecoveredShadowInfo | None:
    offset = _next_legacy_string_candidate(data, 0)
    while offset is not None and offset < len(data) - 32:
        stream = io.BytesIO(data[offset:])
        reader = LegacyArchiveReader(stream)
        try:
            city = reader.read_legacy_utf16_string("shadow city")
            country = reader.read_legacy_utf16_string("shadow country")
            longitude = reader.read_f64()
            latitude = reader.read_f64()
            timezone_offset = reader.read_f64()
        except (EOFError, UnicodeDecodeError, ValueError):
            offset += 1
            continue

        # Two valid strings are insufficient in arbitrary bytes; geographic
        # ranges and a country-code shape provide the semantic guard.
        if _looks_like_shadow_location(city, country, latitude, longitude):
            return RecoveredShadowInfo(
                payload_start_offset=absolute_start + offset,
                value=ShadowInfo(
                    city=city.encode("utf-8"),
                    country=country.encode("utf-8"),
                    longitude=longitude,
                    latitude=latitude,
                    timezone_offset=timezone_offset,
                ),
                payload_end_offset=absolute_start + offset + reader.tell(),
            )
        offset = _next_legacy_string_candidate(data, offset + 1)
    return None


def _next_legacy_string_candidate(data: bytes, start: int) -> int | None:
    offsets = [offset for prefix in LEGACY_UTF16_STRING_PREFIXES if (offset := data.find(prefix, start)) != -1]
    if not offsets:
        return None
    return min(offsets)


def _scan_model_view_axes(
    data: bytes,
    *,
    absolute_start: int,
    shadow_info: RecoveredShadowInfo | None,
) -> RecoveredModelViewAxes | None:
    offset = 0
    if shadow_info is not None:
        offset = max(0, shadow_info.payload_end_offset - absolute_start)

    fallback_offset = offset
    # Default axes have a distinctive 3x3 identity basis. Search that fast path
    # first, then validate the preceding origin and all four vectors.
    basis_offset = data.find(DEFAULT_MODEL_VIEW_AXES_BYTES, offset + 24)
    while basis_offset >= 24:
        offset = basis_offset - 24
        stream = io.BytesIO(data[offset:])
        reader = LegacyArchiveReader(stream)
        origin = reader.read_vec3_f64()
        x_axis = reader.read_vec3_f64()
        y_axis = reader.read_vec3_f64()
        z_axis = reader.read_vec3_f64()

        if _looks_like_model_view_axes(origin, x_axis, y_axis, z_axis):
            return RecoveredModelViewAxes(
                payload_start_offset=absolute_start + offset,
                value=ModelViewAxes(
                    origin=origin,
                    x_axis=x_axis,
                    y_axis=y_axis,
                    z_axis=z_axis,
                ),
                payload_end_offset=absolute_start + offset + reader.tell(),
            )
        basis_offset = data.find(DEFAULT_MODEL_VIEW_AXES_BYTES, basis_offset + 1)

    # Rotated/custom axes lack the identity signature, so use the slower scan
    # with orthonormality checks only after the fast path fails.
    offset = fallback_offset
    while offset <= len(data) - 96:
        stream = io.BytesIO(data[offset:])
        reader = LegacyArchiveReader(stream)
        origin = reader.read_vec3_f64()
        x_axis = reader.read_vec3_f64()
        y_axis = reader.read_vec3_f64()
        z_axis = reader.read_vec3_f64()

        if _looks_like_model_view_axes(origin, x_axis, y_axis, z_axis):
            return RecoveredModelViewAxes(
                payload_start_offset=absolute_start + offset,
                value=ModelViewAxes(
                    origin=origin,
                    x_axis=x_axis,
                    y_axis=y_axis,
                    z_axis=z_axis,
                ),
                payload_end_offset=absolute_start + offset + reader.tell(),
            )
        offset += 1
    return None


def _looks_like_model_view_axes(
    origin: tuple[float, float, float],
    x_axis: tuple[float, float, float],
    y_axis: tuple[float, float, float],
    z_axis: tuple[float, float, float],
) -> bool:
    values = (*origin, *x_axis, *y_axis, *z_axis)
    if not all(math.isfinite(value) and abs(value) < 1.0e9 for value in values):
        return False
    return (
        _is_unit_vector(x_axis)
        and _is_unit_vector(y_axis)
        and _is_unit_vector(z_axis)
        and abs(_dot3(x_axis, y_axis)) < 1.0e-6
        and abs(_dot3(x_axis, z_axis)) < 1.0e-6
        and abs(_dot3(y_axis, z_axis)) < 1.0e-6
    )


def _is_unit_vector(vector: tuple[float, float, float]) -> bool:
    return abs(math.sqrt(_dot3(vector, vector)) - 1.0) < 1.0e-6


def _dot3(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _looks_like_shadow_location(city: str, country: str, latitude: float, longitude: float) -> bool:
    return (
        bool(city)
        and 2 <= len(country) <= 3
        and country.isupper()
        and -90.0 <= latitude <= 90.0
        and -180.0 <= longitude <= 180.0
    )


def scan_font_previews(data: bytes, *, absolute_start: int) -> tuple[Font, ...]:
    """Scan bounded post-layer bytes for observed SketchUp 8 font records."""
    previews: list[Font] = []
    # Fonts have no reliable standalone runtime-class marker in every observed
    # tail. Start from CString signatures and reject candidates semantically.
    offset = _next_legacy_string_candidate(data, 0)
    while offset is not None and offset < len(data) - 18:
        stream = io.BytesIO(data[offset:])
        reader = LegacyArchiveReader(stream)
        try:
            face_name = reader.read_legacy_utf16_string("CSkFont face name")
            bold_flag = reader.read_u8()
            italic_flag = reader.read_u8()
            point_size = reader.read_u32()
            use_world_size_flag = reader.read_u8()
            world_size = reader.read_f64()
        except (EOFError, UnicodeDecodeError, ValueError):
            offset = _next_legacy_string_candidate(data, offset + 1)
            continue

        if _looks_like_font_record(
            face_name,
            bold_flag=bold_flag,
            italic_flag=italic_flag,
            point_size=point_size,
            use_world_size_flag=use_world_size_flag,
            world_size=world_size,
        ):
            previews.append(
                Font(
                    face_name=face_name,
                    bold=bool(bold_flag),
                    italic=bool(italic_flag),
                    point_size=point_size,
                    use_world_size=bool(use_world_size_flag),
                    world_size=world_size,
                )
            )
            offset = _next_legacy_string_candidate(data, offset + max(reader.tell(), 1))
            continue

        offset = _next_legacy_string_candidate(data, offset + 1)
    return tuple(previews)


def scan_style_previews(data: bytes, *, absolute_start: int) -> tuple[StyleDescriptor, ...]:
    """Scan bounded post-layer bytes for observed SketchUp 8 style records."""
    previews: list[StyleDescriptor] = []
    class_name = b"CSkpStyle"
    offset = _next_runtime_class_candidate(data, class_name, 0)
    while offset is not None:
        current_offset = offset
        stream = io.BytesIO(data[current_offset:])
        reader = LegacyArchiveReader(stream)
        try:
            reader.read_object_tag()
            entity_tag = reader.read_object_tag()
            guid = reader.read_exact(16, "CSkpStyle GUID")
            initial_file_name = reader.read_legacy_utf16_string("CSkpStyle initial file name")
            style_version = reader.read_u32()
            display_name = reader.read_legacy_utf16_string("CSkpStyle display name")
            file_name = reader.read_legacy_utf16_string("CSkpStyle file name")
            option_count = reader.read_u32()
        except (EOFError, UnicodeDecodeError, ValueError):
            offset = _next_runtime_class_candidate(data, class_name, current_offset + 1)
            continue

        if (
            entity_tag.kind == "null"
            and len(guid) == 16
            and _looks_like_style_record(display_name, style_version, option_count)
        ):
            previews.append(
                StyleDescriptor(
                    guid=guid,
                    display_name=display_name,
                    file_name=file_name or initial_file_name,
                )
            )
            offset = _next_runtime_class_candidate(data, class_name, current_offset + max(reader.tell(), 1))
            continue

        offset = _next_runtime_class_candidate(data, class_name, current_offset + 1)
    return tuple(previews)


def _looks_like_style_record(display_name: str, style_version: int, option_count: int) -> bool:
    return (
        1 <= len(display_name) <= 256
        and display_name.isprintable()
        and 0 <= style_version <= 100
        and 0 <= option_count <= 10_000
    )


def _looks_like_font_record(
    face_name: str,
    *,
    bold_flag: int,
    italic_flag: int,
    point_size: int,
    use_world_size_flag: int,
    world_size: float,
) -> bool:
    return (
        1 <= len(face_name) <= 128
        and face_name.isprintable()
        and bold_flag in (0, 1)
        and italic_flag in (0, 1)
        and 1 <= point_size <= 512
        and use_world_size_flag in (0, 1)
        and math.isfinite(world_size)
        and 0.0 <= world_size <= 1.0e6
    )


def scan_post_layer_previews(
    data: bytes, *, absolute_start: int
) -> tuple[
    tuple[RecoveredSceneState, ...],
    ShadowInfo | None,
    ModelViewAxes | None,
]:
    """Scan bounded post-layer bytes for optional scene/shadow/axes previews."""
    # The caller already bounds `data` to the unconsumed suffix. Keep the more
    # permissive shadow/axes scan tighter still to limit false positives.
    scene_previews = _scan_scene_previews(data, absolute_start=absolute_start)
    shadow_axes_scan = data[:SHADOW_AXES_HEURISTIC_SCAN_BYTES]
    shadow_info = _scan_shadow_info(shadow_axes_scan, absolute_start=absolute_start)
    model_view_axes = _scan_model_view_axes(
        shadow_axes_scan,
        absolute_start=absolute_start,
        shadow_info=shadow_info,
    )
    return (
        scene_previews,
        shadow_info.value if shadow_info is not None else None,
        (model_view_axes.value if model_view_axes is not None else None),
    )
