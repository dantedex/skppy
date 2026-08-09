# SPDX-License-Identifier: MIT
"""Annotation and dimension payload bodies for legacy SketchUp archives."""

from __future__ import annotations

from typing import NamedTuple

from .parser_types import Arc3dPayload
from .binary import LegacyArchiveReader
from .geometry_payloads import read_arc3d_payload


class DimensionRadialFields(NamedTuple):
    """Radial placement fields following the referenced arc edge."""

    parameter: float
    radius_ratio: float
    is_diameter: bool
    arc: Arc3dPayload | None


class TextTail(NamedTuple):
    """Named ``CText`` fields following its point reference."""

    leader_vector: tuple[float, float, float]
    view_direction: tuple[float, float, float]
    leader_type: int
    line_weight: int
    point_ref_front: bool
    hide_out_of_plane: bool
    arrow_type: int
    display_leader: bool
    text: str
    convert_to_screen_on_explode: bool
    hidden_leader_direction: int


def read_dimension_radial_fields(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    target_is_null: bool,
) -> DimensionRadialFields:
    """Read ``CDimensionRadial`` fields following its target edge reference."""
    if class_version != 2:
        raise NotImplementedError("Only SketchUp 8 CDimensionRadial version 2 is decoded.")
    parameter = reader.read_f64()
    radius_ratio = reader.read_f64()
    is_diameter = reader.read_bool()
    arc = read_arc3d_payload(reader, include_y_axis=class_version > 1) if target_is_null else None
    return DimensionRadialFields(parameter, radius_ratio, is_diameter, arc)


def read_point_ref_prefix(
    reader: LegacyArchiveReader,
) -> tuple[int, int, tuple[float, float, float]]:
    """Read point-reference fields preceding its archive object references."""
    return reader.read_u32(), reader.read_u32(), reader.read_vec3_f64()


def read_text_offsets(reader: LegacyArchiveReader) -> tuple[float, float]:
    """Read ``CText`` offsets preceding its point reference."""
    return reader.read_f64(), reader.read_f64()


def read_text_tail(reader: LegacyArchiveReader) -> TextTail:
    """Read ``CText`` fields following its point reference."""
    return TextTail(
        reader.read_vec3_f64(),
        reader.read_vec3_f64(),
        reader.read_u32(),
        reader.read_u32(),
        reader.read_bool(),
        reader.read_bool(),
        reader.read_u32(),
        reader.read_bool(),
        reader.read_legacy_utf16_string("CText text"),
        reader.read_bool(),
        reader.read_u32(),
    )
