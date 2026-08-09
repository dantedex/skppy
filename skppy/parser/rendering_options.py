# SPDX-License-Identifier: MIT
"""Decode modern TLV display settings into shared rendering options.

Rendering records are append-friendly: every field is optional and unknown
tags can be skipped by length. :func:`parse_rendering_options` starts from the
documented public defaults, applies the first occurrence of each known field,
and normalizes packed RGBA colors to ARGB integers. It is used for both model
state and saved-scene snapshots.
"""

from __future__ import annotations

from collections.abc import Callable

from ..data_structure.model_metadata import RenderingOptions
from .tlv import (
    TlvTag,
    find_child,
    iter_records,
    read_bool,
    read_compact_int,
    read_f64_le,
)

_Field = tuple[TlvTag, str]

_INTEGER_FIELDS: tuple[_Field, ...] = (
    (TlvTag.REND_OPT_RENDER_MODE, "render_mode"),
    (TlvTag.REND_OPT_EDGE_DISPLAY_MODE, "edge_display_mode"),
    (TlvTag.REND_OPT_EDGE_TYPE, "edge_type"),
    (TlvTag.REND_OPT_EDGE_COLOR_MODE, "edge_color_mode"),
    (TlvTag.REND_OPT_FACE_COLOR_MODE, "face_color_mode"),
    (TlvTag.REND_OPT_LINE_EXTENSION, "line_extension"),
    (TlvTag.REND_OPT_SILHOUETTE_WIDTH, "silhouette_width"),
    (TlvTag.REND_OPT_DEPTH_QUE_WIDTH, "depth_que_width"),
    (TlvTag.REND_OPT_LINE_END_WIDTH, "line_end_width"),
    (TlvTag.REND_OPT_FOG_HINT_MODE, "fog_hint_mode"),
    (TlvTag.REND_OPT_GROUND_TRANSPARENCY, "ground_transparency"),
    (TlvTag.REND_OPT_SECTION_CUT_WIDTH, "section_cut_width"),
    # Bit 0 is DisplaySectionPlanes and bit 1 is DisplaySectionCuts. The
    # shared class exposes synchronized named properties over this raw mask.
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


def _optional_scalar(
    options: RenderingOptions,
    records: dict[int, bytes],
    tag: int,
    field: str,
    decoder: Callable[[bytes], int],
) -> int:
    """Decode a present field or retain its meaningful public default."""
    payload = records.get(tag)
    return decoder(payload) if payload is not None else int(getattr(options, field))


def _float_value(options: RenderingOptions, records: dict[int, bytes], tag: int, field: str) -> float:
    """Decode a complete f64 or preserve the field default."""
    payload = records.get(tag)
    return read_f64_le(payload) if payload is not None and len(payload) >= 8 else float(getattr(options, field))


def _color_value(options: RenderingOptions, records: dict[int, bytes], tag: int, field: str) -> int:
    """Normalize packed modern RGBA bytes to the shared ARGB integer."""
    payload = records.get(tag)
    if payload is None:
        return int(getattr(options, field))
    rgba = read_compact_int(payload)
    red = rgba & 0xFF
    green = (rgba >> 8) & 0xFF
    blue = (rgba >> 16) & 0xFF
    alpha = (rgba >> 24) & 0xFF
    return (alpha << 24) | (red << 16) | (green << 8) | blue


def parse_rendering_options(block_payload: bytes) -> RenderingOptions:
    """Parse modern ``0x01FB -> 0x733C`` rendering options."""
    options = RenderingOptions()
    record = find_child(block_payload, TlvTag.RENDERING_OPTIONS_RECORD)
    if record is None:
        return options

    # Fields are optional and new versions append tags. Absence therefore means
    # the shared semantic default, while the first duplicate is authoritative.
    records: dict[int, bytes] = {}
    for tag, payload in iter_records(record):
        records.setdefault(tag, payload)

    for tag, field in _INTEGER_FIELDS:
        value = _optional_scalar(options, records, tag, field, read_compact_int)
        setattr(options, field, value)
    for tag, field in _FLOAT_FIELDS:
        setattr(options, field, _float_value(options, records, tag, field))
    for tag, field in _BOOLEAN_FIELDS:
        value = _optional_scalar(options, records, tag, field, read_bool)
        setattr(options, field, bool(value))
    for tag, field in _COLOR_FIELDS:
        setattr(options, field, _color_value(options, records, tag, field))
    return options
