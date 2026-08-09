# SPDX-License-Identifier: MIT
"""Encoders for modern model-level display and location metadata."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable

from ..data_structure.construction import ShadowInfo
from ..data_structure.model_metadata import ModelViewAxes, RenderingOptions
from ..parser.tlv import TlvTag
from .tlv import encode_bool, encode_record, encode_records

_Field = tuple[TlvTag, str]

_INTEGER_FIELDS: tuple[_Field, ...] = (
    (TlvTag.REND_OPT_RENDER_MODE, "render_mode"),
    (TlvTag.REND_OPT_EDGE_DISPLAY_MODE, "edge_display_mode"),
    (TlvTag.REND_OPT_EDGE_TYPE, "edge_type"),
    (TlvTag.REND_OPT_EDGE_COLOR_MODE, "edge_color_mode"),
    (TlvTag.REND_OPT_LINE_EXTENSION, "line_extension"),
    (TlvTag.REND_OPT_SILHOUETTE_WIDTH, "silhouette_width"),
    (TlvTag.REND_OPT_DEPTH_QUE_WIDTH, "depth_que_width"),
    (TlvTag.REND_OPT_LINE_END_WIDTH, "line_end_width"),
    (TlvTag.REND_OPT_FOG_HINT_MODE, "fog_hint_mode"),
    (TlvTag.REND_OPT_GROUND_TRANSPARENCY, "ground_transparency"),
    (TlvTag.REND_OPT_SECTION_CUT_WIDTH, "section_cut_width"),
    (TlvTag.REND_OPT_SECTION_DISPLAY_MODE, "section_display_mode"),
    (TlvTag.REND_OPT_TRANSPARENCY_SORT, "transparency_sort"),
    (TlvTag.REND_OPT_AO_DISTANCE, "ao_distance"),
    (TlvTag.REND_OPT_AO_INTENSITY, "ao_intensity"),
    (TlvTag.REND_OPT_AO_MULTIPLIER, "ao_multiplier"),
)

_FLOAT_FIELDS: tuple[_Field, ...] = (
    (TlvTag.REND_OPT_FOG_START_DIST, "fog_start_dist"),
    (TlvTag.REND_OPT_FOG_END_DIST, "fog_end_dist"),
    (TlvTag.REND_OPT_INACTIVE_FADE, "inactive_fade"),
    (TlvTag.REND_OPT_INSTANCE_FADE, "instance_fade"),
    (TlvTag.REND_OPT_XRAY_OPACITY, "xray_opacity"),
    (TlvTag.REND_OPT_SOFT_EDGE_LIMIT, "soft_edge_limit"),
    (TlvTag.REND_OPT_PHOTOMATCH_BG_OPACITY, "photomatch_background_opacity"),
    (
        TlvTag.REND_OPT_PHOTOMATCH_OVERLAY_OPACITY,
        "photomatch_overlay_opacity",
    ),
)

_BOOLEAN_FIELDS: tuple[_Field, ...] = (
    (TlvTag.REND_OPT_MODEL_TRANSPARENCY, "model_transparency"),
    (TlvTag.REND_OPT_MATERIAL_TRANSPARENCY, "material_transparency"),
    (TlvTag.REND_OPT_TEXTURE, "texture"),
    (TlvTag.REND_OPT_DISPLAY_SKETCH_AXES, "display_sketch_axes"),
    (TlvTag.REND_OPT_DISPLAY_TEXT, "display_text"),
    (TlvTag.REND_OPT_DISPLAY_DIMS, "display_dims"),
    (TlvTag.REND_OPT_HIDE_CONSTRUCTION_GEOMETRY, "hide_construction_geometry"),
    (TlvTag.REND_OPT_DISPLAY_COLOR_BY_LAYER, "display_color_by_layer"),
    (TlvTag.REND_OPT_DISPLAY_INSTANCE_AXES, "display_instance_axes"),
    (TlvTag.REND_OPT_JITTER_EDGES, "jitter_edges"),
    (TlvTag.REND_OPT_LINE_STYLE_EDGES, "line_style_edges"),
    (TlvTag.REND_OPT_EXTEND_LINES, "extend_lines"),
    (TlvTag.REND_OPT_DRAW_SILHOUETTES, "draw_silhouettes"),
    (TlvTag.REND_OPT_DRAW_DEPTH_QUE, "draw_depth_que"),
    (TlvTag.REND_OPT_DRAW_LINE_ENDS, "draw_line_ends"),
    (TlvTag.REND_OPT_DRAW_PROFILES_ONLY, "draw_profiles_only"),
    (TlvTag.REND_OPT_DRAW_BACK_EDGES, "draw_back_edges"),
    (TlvTag.REND_OPT_DISPLAY_WATERMARKS, "display_watermarks"),
    (TlvTag.REND_OPT_DISPLAY_FOG, "display_fog"),
    (TlvTag.REND_OPT_FOG_USE_BACKGROUND_COLOR, "fog_use_background_color"),
    (TlvTag.REND_OPT_DRAW_HORIZON, "draw_horizon"),
    (TlvTag.REND_OPT_DRAW_GROUND, "draw_ground"),
    (TlvTag.REND_OPT_DRAW_UNDERGROUND, "draw_underground"),
    (TlvTag.REND_OPT_INACTIVE_HIDDEN, "inactive_hidden"),
    (TlvTag.REND_OPT_INSTANCE_HIDDEN, "instance_hidden"),
    (TlvTag.REND_OPT_SECTION_CUT_FILLED, "section_cut_filled"),
    (TlvTag.REND_OPT_DRAW_SOFT_EDGES, "draw_soft_edges"),
    (TlvTag.REND_OPT_DRAW_SMOOTH_EDGES, "draw_smooth_edges"),
    (TlvTag.REND_OPT_PHOTOMATCH_DRAW_BG, "photomatch_draw_background"),
    (TlvTag.REND_OPT_PHOTOMATCH_DRAW_OVERLAY, "photomatch_draw_overlay"),
    (TlvTag.REND_OPT_DRAW_HIDDEN_GEOMETRY, "draw_hidden_geometry"),
    (TlvTag.REND_OPT_DRAW_HIDDEN_OBJECTS, "draw_hidden_objects"),
    (TlvTag.REND_OPT_HIDE_CUSTOM_CONTROL_POINTS, "hide_custom_control_points"),
    (TlvTag.REND_OPT_AMBIENT_OCCLUSION, "ambient_occlusion"),
    (TlvTag.REND_OPT_AO_COLOR_ENABLED, "ao_color_enabled"),
)

_COLOR_FIELDS: tuple[_Field, ...] = (
    (TlvTag.REND_OPT_BACKGROUND_COLOR, "background_color"),
    (TlvTag.REND_OPT_FOREGROUND_COLOR, "foreground_color"),
    (TlvTag.REND_OPT_HIGHLIGHT_COLOR, "highlight_color"),
    (TlvTag.REND_OPT_LOCKED_COLOR, "locked_color"),
    (TlvTag.REND_OPT_CONSTRUCTION_COLOR, "construction_color"),
    (TlvTag.REND_OPT_FACE_FRONT_COLOR, "face_front_color"),
    (TlvTag.REND_OPT_FACE_BACK_COLOR, "face_back_color"),
    (TlvTag.REND_OPT_FOG_COLOR, "fog_color"),
    (TlvTag.REND_OPT_SKY_COLOR, "sky_color"),
    (TlvTag.REND_OPT_HORIZON_COLOR, "horizon_color"),
    (TlvTag.REND_OPT_GROUND_COLOR, "ground_color"),
    (TlvTag.REND_OPT_SECTION_ACTIVE_COLOR, "section_active_color"),
    (TlvTag.REND_OPT_SECTION_INACTIVE_COLOR, "section_inactive_color"),
    (TlvTag.REND_OPT_SECTION_DEFAULT_CUT_COLOR, "section_default_cut_color"),
    (TlvTag.REND_OPT_SECTION_DEFAULT_FILL_COLOR, "section_default_fill_color"),
    (TlvTag.REND_OPT_AO_COLOR, "ao_color"),
)


def _validate_finite(values: Iterable[float], label: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != 3 or not all(math.isfinite(value) for value in result):
        raise ValueError(f"{label} must contain three finite values")
    return result


def _encode_argb_color(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("Rendering color must fit in u32")
    alpha = (value >> 24) & 0xFF
    red = (value >> 16) & 0xFF
    green = (value >> 8) & 0xFF
    blue = value & 0xFF
    return struct.pack("<I", red | (green << 8) | (blue << 16) | (alpha << 24))


def _normalize_axis(values: Iterable[float], label: str) -> tuple[float, ...]:
    axis = _validate_finite(values, label)
    length = math.sqrt(sum(value * value for value in axis))
    if length == 0.0:
        raise ValueError(f"{label} must not be zero")
    return tuple(value / length for value in axis)


def encode_rendering_options(options: RenderingOptions) -> bytes:
    """Encode the complete modern rendering-options record."""
    fields: list[tuple[int, bytes]] = []
    for tag, name in _INTEGER_FIELDS:
        value = int(getattr(options, name))
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"Rendering option {name} must fit in u32")
        fields.append((tag, struct.pack("<I", value)))
    for tag, name in _FLOAT_FIELDS:
        float_value = float(getattr(options, name))
        if not math.isfinite(float_value):
            raise ValueError(f"Rendering option {name} must be finite")
        fields.append((tag, struct.pack("<d", float_value)))
    for tag, name in _BOOLEAN_FIELDS:
        fields.append((tag, encode_bool(bool(getattr(options, name)))))
    for tag, name in _COLOR_FIELDS:
        fields.append((tag, _encode_argb_color(int(getattr(options, name)))))
    return encode_record(TlvTag.RENDERING_OPTIONS_RECORD, encode_records(fields))


def encode_model_view_axes(axes: ModelViewAxes) -> bytes:
    """Encode custom model axes using fixed-width little-endian vectors."""
    origin = _validate_finite(axes.origin, "Axes origin")
    x_axis = _normalize_axis(axes.x_axis, "Axes X vector")
    y_axis = _normalize_axis(axes.y_axis, "Axes Y vector")
    z_axis = _normalize_axis(axes.z_axis, "Axes Z vector")
    fields = (
        (
            TlvTag.ENTITY_BASE,
            encode_record(TlvTag.ENTITY_FLAGS, b"\x06"),
        ),
        (TlvTag.SKETCH_AXES_ORIGIN, struct.pack("<3d", *origin)),
        (TlvTag.SKETCH_AXES_X_AXIS, struct.pack("<3d", *x_axis)),
        (TlvTag.SKETCH_AXES_Y_AXIS, struct.pack("<3d", *y_axis)),
        (TlvTag.SKETCH_AXES_Z_AXIS, struct.pack("<3d", *z_axis)),
    )
    return encode_record(TlvTag.MODEL_VIEW_RECORD, encode_records(fields))


def encode_shadow_info(shadow: ShadowInfo) -> bytes:
    """Encode geolocation and shadow display settings."""
    floats = (shadow.latitude, shadow.longitude, shadow.timezone_offset)
    if not all(math.isfinite(value) for value in floats):
        raise ValueError("Shadow location values must be finite")
    north = _validate_finite(shadow.north_direction, "North direction")
    fields = (
        (TlvTag.SHADOW_INFO_TIME, struct.pack("<I", shadow.time)),
        (TlvTag.SHADOW_INFO_DAYLIGHT_SAVINGS, encode_bool(shadow.daylight_savings)),
        (TlvTag.SHADOW_INFO_CITY, bytes(shadow.city)),
        (TlvTag.SHADOW_INFO_COUNTRY, bytes(shadow.country)),
        (TlvTag.SHADOW_INFO_LONGITUDE, struct.pack("<d", shadow.longitude)),
        (TlvTag.SHADOW_INFO_LATITUDE, struct.pack("<d", shadow.latitude)),
        (TlvTag.SHADOW_INFO_TIMEZONE_OFFSET, struct.pack("<d", shadow.timezone_offset)),
        (TlvTag.SHADOW_INFO_NORTH_DIRECTION, struct.pack("<3d", *north)),
        (TlvTag.SHADOW_INFO_DISPLAY_SHADOWS, encode_bool(shadow.display_shadows)),
        (TlvTag.SHADOW_INFO_DISPLAY_NORTH, encode_bool(shadow.display_north)),
        (
            TlvTag.SHADOW_INFO_DISPLAY_ON_ALL_FACES,
            encode_bool(shadow.display_on_all_faces),
        ),
        (
            TlvTag.SHADOW_INFO_DISPLAY_ON_GROUND,
            encode_bool(shadow.display_on_ground_plane),
        ),
        (TlvTag.SHADOW_INFO_EDGES_CAST_SHADOWS, encode_bool(shadow.edges_cast_shadows)),
        (TlvTag.SHADOW_INFO_LIGHT, struct.pack("<I", shadow.light)),
        (TlvTag.SHADOW_INFO_DARK, struct.pack("<I", shadow.dark)),
        (
            TlvTag.SHADOW_INFO_USE_SUN_FOR_ALL_SHADING,
            encode_bool(shadow.use_sun_for_all_shading),
        ),
    )
    return encode_record(TlvTag.SHADOW_INFO_RECORD, encode_records(fields))
