# SPDX-License-Identifier: MIT
"""Versioned shared-metadata payload readers for legacy archives."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from ..data_structure.construction import Camera, ShadowInfo
from ..data_structure.model_metadata import (
    DimensionStyle,
    Font,
    ModelViewAxes,
    StyleDescriptor,
    StylesRegistry,
)
from ..data_structure.primitives import Vector3D

from .binary import ArchiveObjectTag, LegacyArchiveReader
from .colors import rgba_bytes_to_argb


class TextStyleFields(TypedDict):
    """Decoded fields preceding a ``CTextStyle`` screen-font reference."""

    arrow_type: int
    line_weight: int
    hide_out_of_plane: bool
    leader_type: int
    display_leader: bool
    color: int
    screen_color: int


def read_camera_payload(reader: LegacyArchiveReader, class_version: int) -> Camera:
    """Consume a ``CCamera`` body and return the shared camera."""
    camera = Camera()
    camera.eye = Vector3D(*reader.read_vec3_f64())
    camera.target = Vector3D(*reader.read_vec3_f64())
    camera.up = Vector3D(*reader.read_vec3_f64())
    camera.near = reader.read_f64()
    camera.far = reader.read_f64()
    camera.is_perspective = reader.read_bool()
    camera.fov = reader.read_f64()
    camera.ortho_height = reader.read_f64()
    reader.read_vec3_f64()  # Obsolete camera vector retained for alignment.
    camera.aspect_ratio = reader.read_f64()
    camera.fov_is_height = reader.read_bool()
    if class_version >= 2:
        camera.legacy_flag = reader.read_bool()
    if class_version > 2:
        camera.name = reader.read_legacy_utf16_string("camera name")
    if class_version > 3:
        camera.image_width = reader.read_f64()
        if class_version != 4:
            camera.is_2d = reader.read_bool()
            camera.scale_2d = reader.read_f64()
            camera.center_2d_x = reader.read_f64()
            camera.center_2d_y = reader.read_f64()
    return camera


def read_font_payload(reader: LegacyArchiveReader, class_version: int) -> Font:
    """Consume a ``CSkFont`` body and return the shared font."""
    if class_version not in {0, 1}:
        raise NotImplementedError(f"CSkFont version {class_version} is not decoded.")
    font = Font()
    font.face_name = reader.read_legacy_utf16_string("CSkFont face name")
    font.bold = reader.read_bool()
    font.italic = reader.read_bool()
    font.point_size = reader.read_u32()
    if class_version > 0:
        font.use_world_size = reader.read_bool()
        font.world_size = reader.read_f64()
    return font


def read_font_manager_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_object: Callable[[], object],
) -> tuple[Font, ...]:
    """Read a font manager body after its entity header."""
    if class_version != 0:
        raise NotImplementedError("Only SketchUp 8 CFontManager version 0 is decoded.")
    count = reader.read_u32()
    return tuple(font for _ in range(count) if isinstance((font := read_object()), Font))


def read_style_payload(
    reader: LegacyArchiveReader,
    class_version: int,
    *,
    read_object: Callable[[], object],
) -> StyleDescriptor:
    """Consume a ``CSkpStyle`` body and return the shared descriptor."""
    if class_version not in {1, 2}:
        raise NotImplementedError("Only observed SketchUp 8 CSkpStyle versions 1 and 2 are decoded.")
    style = StyleDescriptor()
    style.guid = reader.read_exact(16, "CSkpStyle GUID")
    initial_file_name = reader.read_legacy_utf16_string("CSkpStyle initial file name")
    style_version = reader.read_u32()
    style.display_name = reader.read_legacy_utf16_string("CSkpStyle display name")
    style.file_name = reader.read_legacy_utf16_string("CSkpStyle file name")
    if not style.file_name:
        style.file_name = initial_file_name
    option_count = reader.read_u32()
    for _ in range(option_count):
        option_key = reader.read_u32()
        # Style options are a heterogeneous key/value stream rather than a
        # fixed struct. Known object-bearing keys need recursive resolution;
        # scalar variants use the generic reader below.
        if option_key == 0x3F5:
            _read_npr_edge(reader, read_object=read_object)
        elif option_key == 0x1389:
            watermark_count = reader.read_u32() if style_version > 2 else 0
            for _ in range(watermark_count):
                read_object()
        else:
            _read_style_variant(reader)
    return style


def _read_style_variant(reader: LegacyArchiveReader) -> object:
    """Read one Atlast style Variant and return a simple native value."""
    reader.read_u32()  # Variant serialization version.
    value_type = reader.read_u32()
    if value_type == 0:
        return None
    if value_type in {1, 2}:
        return reader.read_u8()
    if value_type == 3:
        return reader.read_u16()
    if value_type in {4, 5, 14}:
        return reader.read_u32()
    if value_type == 6:
        return reader.read_f32()
    if value_type == 7:
        return reader.read_f64()
    if value_type in {9, 10, 11}:
        return reader.read_vec3_f64()
    if value_type == 12:
        return tuple(reader.read_f64() for _ in range(16))
    raise ValueError(f"Unsupported Atlast style Variant type {value_type}.")


def _read_npr_edge(reader: LegacyArchiveReader, *, read_object: Callable[[], object]) -> None:
    """Consume the NPREdge payload stored under style option ``0x3f5``."""
    npr_version = reader.read_u32()
    if npr_version < 2:
        reader.read_u32()
        reader.read_u32()
    else:
        reader.read_f64()
        reader.read_f64()
    reader.read_u32()
    reader.read_bool()
    reader.read_u32()
    reader.read_u32()
    for _ in range(reader.read_u32()):
        reader.read_u32()
    for _ in range(reader.read_u32()):
        read_object()


def read_style_manager_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_object: Callable[[], object],
    read_tagged_object: Callable[[], tuple[ArchiveObjectTag, object]],
) -> StylesRegistry:
    """Read a style manager body after its entity header."""
    if class_version != 2:
        raise NotImplementedError("Only SketchUp 8 CSkpStyleManager version 2 is decoded.")
    count = reader.read_u32()
    styles = [style for _ in range(count) if isinstance((style := read_object()), StyleDescriptor)]
    if not count:
        return StylesRegistry()
    active_style, _ = read_tagged_object()
    read_tagged_object()
    return StylesRegistry(
        styles=styles,
        active_style_ref=active_style.index or 0,
        selected_style_dirty=reader.read_bool(),
    )


def read_text_style_fields(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
) -> TextStyleFields:
    """Consume the ``CTextStyle`` fields preceding its screen-font reference."""
    if class_version not in {4, 5}:
        raise NotImplementedError(f"CTextStyle version {class_version} is not decoded.")
    arrow_type = reader.read_u32()
    line_weight = reader.read_u32()
    hide_out_of_plane = reader.read_bool()
    leader_type = reader.read_u32()
    display_leader = reader.read_bool()
    color = reader.read_rgba()
    screen_color = reader.read_rgba() if class_version > 4 else color
    return {
        "arrow_type": arrow_type,
        "line_weight": line_weight,
        "hide_out_of_plane": hide_out_of_plane,
        "leader_type": leader_type,
        "display_leader": display_leader,
        "color": rgba_bytes_to_argb(color),
        "screen_color": rgba_bytes_to_argb(screen_color),
    }


def read_dimension_style_payload(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    font_ref: int,
) -> DimensionStyle:
    """Consume a ``CDimensionStyle`` body after its font reference."""
    if class_version != 4:
        raise NotImplementedError("Only SketchUp 8 CDimensionStyle version 4 is decoded.")
    style = DimensionStyle(font_ref=font_ref)
    style.text_3d = reader.read_bool()
    style.always_readable = reader.read_bool()
    style.extension_offset = reader.read_u32()
    style.extension_overshoot = reader.read_u32()
    style.line_weight = reader.read_u32()
    style.arrow_type = reader.read_u32()
    style.arrow_size = reader.read_u32()
    style.highlight_non_associative = reader.read_bool()
    style.highlight_non_associative_color = rgba_bytes_to_argb(reader.read_rgba())
    style.show_radial_diameter_prefix = reader.read_bool()
    style.hide_out_of_plane = reader.read_bool()
    style.hide_out_of_plane_value = reader.read_f64()
    style.hide_small = reader.read_bool()
    style.hide_small_value = reader.read_f64()
    style.color = rgba_bytes_to_argb(reader.read_rgba())
    style.text_color = rgba_bytes_to_argb(reader.read_rgba())
    style.text_position = reader.read_u32()
    return style


def read_axes_payload(reader: LegacyArchiveReader, class_version: int) -> ModelViewAxes:
    """Consume a ``CSketchCS`` body and return shared model axes."""
    if class_version != 0:
        raise NotImplementedError("Only SketchUp 8 CSketchCS version 0 is decoded.")
    return ModelViewAxes(
        origin=reader.read_vec3_f64(),
        x_axis=reader.read_vec3_f64(),
        y_axis=reader.read_vec3_f64(),
        z_axis=reader.read_vec3_f64(),
    )


def read_shadow_payload(reader: LegacyArchiveReader, class_version: int) -> ShadowInfo:
    """Consume a ``CShadowInfo`` body after its entity header."""
    if class_version != 7:
        raise NotImplementedError("Only SketchUp 8 CShadowInfo version 7 is decoded.")
    shadow = ShadowInfo()
    shadow.time = reader.read_u32()
    shadow.daylight_savings = reader.read_bool()
    shadow.country = reader.read_legacy_utf16_string("CShadowInfo country").encode("utf-8")
    shadow.city = reader.read_legacy_utf16_string("CShadowInfo city").encode("utf-8")
    shadow.longitude = reader.read_f64()
    shadow.latitude = reader.read_f64()
    shadow.timezone_offset = reader.read_f64()
    shadow.north_direction = reader.read_vec3_f64()
    shadow.display_shadows = reader.read_bool()
    shadow.display_north = reader.read_bool()
    shadow.display_on_all_faces = reader.read_bool()
    shadow.display_on_ground_plane = reader.read_bool()
    shadow.light = reader.read_i32()
    shadow.dark = reader.read_i32()
    shadow.use_sun_for_all_shading = reader.read_bool()
    return shadow
