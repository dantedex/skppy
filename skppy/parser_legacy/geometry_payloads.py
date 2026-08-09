# SPDX-License-Identifier: MIT
"""Pure version-aware readers for legacy geometry payload bodies."""

from __future__ import annotations

from collections.abc import Callable

from ..data_structure.construction import GuideLine, GuidePoint, SectionPlane
from ..data_structure.entities import ArcCurve, Curve, EdgeUse, Face, Loop, Vertex
from ..data_structure.primitives import Vector3D

from .parser_types import Arc3dPayload
from .binary import ArchiveObjectTag, LegacyArchiveReader

DrawingElementBody = tuple[bool, bool, bool, bool, bool, bool, ArchiveObjectTag | None]


def read_drawing_element_body(
    reader: LegacyArchiveReader,
    class_version: int,
    read_reference: Callable[[], ArchiveObjectTag] | None = None,
) -> DrawingElementBody:
    """Read version-gated ``CDrawingElement`` flags and layer reference."""
    # CDrawingElement's constructor enables both shadow flags. Older schemas
    # omit those fields, so a standalone reader must reproduce that default.
    flags = [False, True, True, False, False, False]
    layer_tag = None

    if class_version != 0:
        flags[0] = reader.read_bool()
        if class_version > 5:
            flags[1] = reader.read_bool()
            flags[2] = reader.read_bool()
            if class_version != 6:
                flags[3] = reader.read_bool()
                if class_version != 7:
                    flags[4] = reader.read_bool()
        else:
            flags[4] = flags[3]

    if class_version > 8:
        flags[5] = reader.read_bool()

    read_tag = read_reference or reader.read_object_tag
    if class_version == 2:
        if reader.read_bool():
            read_tag()
    elif class_version > 3:
        layer_tag = read_tag()

    return (
        flags[0],
        flags[1],
        flags[2],
        flags[3],
        flags[4],
        flags[5],
        layer_tag,
    )


def read_arc3d_payload(reader: LegacyArchiveReader, *, include_y_axis: bool) -> Arc3dPayload:
    """Read the vector and angle fields of an embedded ``CArc3d``."""
    center = reader.read_vec3_f64()
    normal = reader.read_vec3_f64()
    x_axis = reader.read_vec3_f64()
    start_angle = reader.read_f64()
    end_angle = reader.read_f64()
    y_axis = reader.read_vec3_f64() if include_y_axis else None
    return center, normal, x_axis, start_angle, end_angle, y_axis


def read_vertex_payload(reader: LegacyArchiveReader) -> Vertex:
    """Read a ``CVertex`` body after its entity header."""
    return Vertex(id=0, position=Vector3D(*reader.read_vec3_f64()))


def read_curve_payload(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_reference: Callable[[], ArchiveObjectTag] | None = None,
) -> Curve:
    """Read a ``CCurve`` body after its entity header."""
    if class_version not in {3, 4}:
        raise NotImplementedError(f"CCurve version {class_version} is not decoded.")
    if class_version == 3:
        read_tag = read_reference or reader.read_object_tag
        read_tag()
        read_tag()
    curve = Curve()
    curve.is_polygon = reader.read_bool()
    curve.edge_ids = [0] * reader.read_u32()
    return curve


def read_arc_curve_payload(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    curve: Curve,
) -> ArcCurve:
    """Read a ``CArcCurve`` body following its shared ``CCurve`` base."""
    if class_version < 1:
        raise NotImplementedError("CArcCurve version 0 is not decoded.")
    arc = read_arc3d_payload(reader, include_y_axis=True)
    arc_curve = ArcCurve(edge_ids=curve.edge_ids)
    arc_curve.center = arc[0]
    arc_curve.normal = arc[1]
    arc_curve.radius = sum(component * component for component in arc[2]) ** 0.5
    arc_curve.start_angle = arc[3]
    arc_curve.end_angle = arc[4]
    return arc_curve


def read_guide_point_payload(reader: LegacyArchiveReader, *, class_version: int) -> GuidePoint:
    """Read a ``CConstructionPoint`` body after its drawing-element base."""
    if class_version != 0:
        raise NotImplementedError("Only SketchUp 8 CConstructionPoint version 0 is decoded.")
    point = GuidePoint()
    point.position = Vector3D(*reader.read_vec3_f64())
    reference_point = Vector3D(*reader.read_vec3_f64())
    if reader.read_bool():
        point.reference_point = reference_point
    return point


def read_guide_line_payload(reader: LegacyArchiveReader, *, class_version: int, file_version: str = "8") -> GuideLine:
    """Read a ``CConstructionLine`` body after its drawing-element base."""
    if class_version not in {0, 1}:
        raise NotImplementedError("Only pre-ZIP CConstructionLine versions 0 and 1 are decoded.")
    line = GuideLine()
    line.point = Vector3D(*reader.read_vec3_f64())
    line.direction = Vector3D(*reader.read_vec3_f64())
    if class_version == 0 or file_version.split(".", 1)[0] == "3":
        return line
    line.start_parameter = reader.read_f64()
    line.end_parameter = reader.read_f64()
    line.stipple_pattern = reader.read_u32()
    return line


def read_section_plane_payload(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    file_version: str = "18",
) -> SectionPlane:
    """Read a ``CSectionPlane`` body after its drawing-element base."""
    if class_version not in {2, 3}:
        raise NotImplementedError("Only SketchUp 8 CSectionPlane versions 2 and 3 are decoded.")
    section = SectionPlane()
    section.plane = reader.read_vec4_f64()
    major_text = file_version.split(".", 1)[0]
    file_major = int(major_text) if major_text.isdigit() else 0
    if class_version >= 3 and file_major >= 18:
        section.name = reader.read_legacy_utf16_string("CSectionPlane name")
        section.symbol = reader.read_legacy_utf16_string("CSectionPlane symbol")
    return section


def read_loop_prefix(reader: LegacyArchiveReader) -> tuple[bool, bool]:
    """Read the outer-boundary and cached-convexity loop flags."""
    return reader.read_bool(), reader.read_bool()


def build_edge_use(*, edge_id: int, reversed_flag: bool) -> EdgeUse:
    """Build a shared edge use from resolved legacy topology fields."""
    return EdgeUse(edge_id=edge_id, reversed=reversed_flag)


def build_face(
    *,
    face_id: int,
    plane: tuple[float, float, float, float],
    loops: list[Loop],
    front_material_id: int | None,
    back_material_id: int | None,
) -> Face:
    """Build a shared face from resolved legacy loop and material references."""
    empty_loop = Loop(edge_uses=[], is_outer=True)
    outer_loop = next((loop for loop in loops if loop.is_outer), None)
    if outer_loop is None:
        outer_loop = loops[0] if loops else empty_loop
    return Face(
        id=face_id,
        plane=plane,
        outer_loop=outer_loop,
        inner_loops=[loop for loop in loops if loop is not outer_loop],
        front_material_id=front_material_id,
        back_material_id=back_material_id,
    )


def read_polyline_points(reader: LegacyArchiveReader, *, class_version: int) -> tuple[tuple[float, float, float], ...]:
    """Read the point array following a ``CPolyline3d`` drawing-element base."""
    if class_version != 0:
        raise NotImplementedError("Only SketchUp 8 CPolyline3d version 0 is decoded.")
    point_count = reader.read_u32()
    return tuple(reader.read_vec3_f64() for _ in range(point_count))
