# SPDX-License-Identifier: MIT
"""Archive adapters for shared legacy vertex and curve objects."""

from __future__ import annotations

from collections.abc import Callable
from typing import BinaryIO, cast

from ..data_structure.construction import GuideLine, GuidePoint, SectionPlane
from ..data_structure.entities import (
    EDGE_FLAG_HIDDEN,
    EDGE_FLAG_SMOOTH,
    EDGE_FLAG_SOFT,
    ArcCurve,
    Curve,
    Edge,
    EdgeUse,
    Face,
    Loop,
    Vertex,
)

from .parser_types import (
    AttributeContainerPayload,
    EdgeState,
    DrawingElementState,
    EntityHeaderState,
    FaceTextureCoordsPayload,
    Polyline3dPayload,
    SupportedObjectPayload,
)
from .base_payloads import read_entity_header_body
from .binary import ArchiveObjectHandle, ArchiveObjectTag, LegacyArchiveReader
from .geometry_payloads import (
    build_edge_use,
    build_face,
    read_arc_curve_payload,
    read_curve_payload,
    read_drawing_element_body,
    read_guide_line_payload,
    read_guide_point_payload,
    read_loop_prefix,
    read_polyline_points,
    read_section_plane_payload,
    read_vertex_payload,
)
from .read_context import ObjectReadContext
from .session import LegacyArchiveSession


def read_vertex(stream: BinaryIO, *, entity_class_version: int) -> Vertex:
    """Read a tagged vertex without an archive session."""
    reader = LegacyArchiveReader(stream)
    object_tag = reader.read_object_tag()
    return read_vertex_body(
        reader,
        object_tag=object_tag,
        read_entity=lambda: read_entity_header_body(
            reader,
            class_version=entity_class_version,
            read_reference=reader.read_object_tag,
        ),
    )


def read_vertex_body(
    reader: LegacyArchiveReader,
    *,
    object_tag: ArchiveObjectTag,
    read_entity: Callable[[], EntityHeaderState],
) -> Vertex:
    """Read a vertex body with injected entity-header handling."""
    del object_tag
    read_entity()
    return read_vertex_payload(reader)


def read_curve(stream: BinaryIO, *, entity_class_version: int, class_version: int) -> Curve:
    """Read a tagged curve without an archive session."""
    reader = LegacyArchiveReader(stream)
    reader.read_object_tag()
    return read_curve_body(
        reader,
        class_version=class_version,
        read_reference=reader.read_object_tag,
        read_entity=lambda: read_entity_header_body(
            reader,
            class_version=entity_class_version,
            read_reference=reader.read_object_tag,
        ),
    )


def read_curve_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_entity: Callable[[], EntityHeaderState],
    read_reference: Callable[[], ArchiveObjectTag] | None = None,
) -> Curve:
    """Read a curve body with injected entity-header handling."""
    read_entity()
    return read_curve_payload(
        reader,
        class_version=class_version,
        read_reference=read_reference,
    )


def read_arc_curve_body(
    reader: LegacyArchiveReader,
    *,
    curve_class_version: int,
    arc_class_version: int,
    read_entity: Callable[[], EntityHeaderState],
    read_reference: Callable[[], ArchiveObjectTag] | None = None,
) -> ArcCurve:
    """Read an arc curve body with its shared curve base."""
    curve = read_curve_body(
        reader,
        class_version=curve_class_version,
        read_entity=read_entity,
        read_reference=read_reference,
    )
    return read_arc_curve_payload(
        reader,
        class_version=arc_class_version,
        curve=curve,
    )


def read_edge_body(
    reader: LegacyArchiveReader,
    *,
    object_tag: ArchiveObjectTag,
    object_index: int | None,
    class_version: int,
    read_drawing_element: Callable[[], DrawingElementState],
    read_vertex_object: Callable[[], object],
    read_curve_object: Callable[[], tuple[ArchiveObjectTag, object]] | None = None,
    previous_edge: EdgeState | None = None,
) -> EdgeState:
    """Read an edge using injected archive-reference resolution."""
    start = reader.tell()
    drawing_element = read_drawing_element()
    start_value = read_vertex_object()
    end_value = read_vertex_object()
    if not isinstance(start_value, Vertex) or not isinstance(end_value, Vertex):
        # SU3 can encode a chained edge by referencing the previous CEdge where
        # a start vertex is expected. The chain means "reuse previous end";
        # accepting any other unresolved handle would hide stream corruption.
        if (
            isinstance(start_value, ArchiveObjectHandle)
            and start_value.class_name == "CEdge"
            and isinstance(end_value, Vertex)
            and previous_edge is not None
        ):
            start_value = previous_edge.end_vertex
        else:
            raise ValueError("CEdge vertex references did not resolve to CVertex.")

    curve_tag = None
    curve = None
    if class_version >= 2 and read_curve_object is not None:
        curve_tag, curve_value = read_curve_object()
        if isinstance(curve_value, (Curve, ArcCurve)):
            curve = curve_value
    # Normalize drawing-element booleans immediately to the bit layout shared
    # with modern edges and consumed by Blender's smoothing path.
    edge_flags = 0
    if drawing_element.hidden:
        edge_flags |= EDGE_FLAG_HIDDEN
    if drawing_element.soft:
        edge_flags |= EDGE_FLAG_SOFT
    if drawing_element.smooth:
        edge_flags |= EDGE_FLAG_SMOOTH
    # EdgeState must preserve one consistent snapshot of public geometry and
    # unresolved archive references, so this immutable state is built at once.
    return EdgeState(
        object_tag=object_tag,
        object_index=object_index,
        payload_start_offset=start,
        drawing_element=drawing_element,
        edge=Edge(
            id=0,
            start_vertex_id=0,
            end_vertex_id=0,
            flags=edge_flags,
            layer_id=(drawing_element.layer_tag.index if drawing_element.layer_tag is not None else None),
        ),
        start_vertex=start_value,
        end_vertex=end_value,
        curve_tag=curve_tag,
        payload_end_offset=reader.tell(),
        curve=curve,
    )


def read_edge(
    context: ObjectReadContext,
    *,
    object_tag: ArchiveObjectTag,
    object_index: int | None,
    class_version: int,
) -> EdgeState:
    """Read an edge and resolve its vertices and optional curve."""

    def read_curve_object() -> tuple[ArchiveObjectTag, object]:
        return context.read_object()

    edge = read_edge_body(
        context.session.reader,
        object_tag=object_tag,
        object_index=object_index,
        class_version=class_version,
        read_drawing_element=context.read_drawing_element,
        read_vertex_object=lambda: context.read_object()[1],
        read_curve_object=read_curve_object,
        previous_edge=context.session.last_edge,
    )
    context.session.last_edge = edge
    return edge


def read_edge_use_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_entity: Callable[[], EntityHeaderState],
    read_edge: Callable[[], int],
    read_reference: Callable[[], ArchiveObjectTag],
) -> EdgeUse:
    """Read edge-use topology after injecting archive-reference handling."""
    read_entity()
    edge_index = read_edge()
    reversed_flag = reader.read_bool()
    read_reference()
    if class_version == 0:
        read_reference()
        read_reference()
    return build_edge_use(edge_id=edge_index, reversed_flag=reversed_flag)


def read_edge_use(context: ObjectReadContext, *, class_version: int) -> EdgeUse:
    """Read an edge use and resolve its edge reference."""

    def read_edge_reference() -> int:
        tag, value = context.read_object()
        # EdgeUse stores the archive index for now. Entity assembly translates
        # it after all edges have received stable public IDs.
        if isinstance(value, EdgeState) and value.object_index is not None:
            return value.object_index
        return tag.index or 0

    return read_edge_use_body(
        context.session.reader,
        class_version=class_version,
        read_entity=context.read_entity,
        read_edge=read_edge_reference,
        read_reference=context.read_reference,
    )


def read_loop_body(
    reader: LegacyArchiveReader,
    *,
    read_entity: Callable[[], EntityHeaderState],
    read_edge_use: Callable[[], tuple[ArchiveObjectTag, object]],
) -> Loop:
    """Read a loop and retain resolved shared edge uses."""
    read_entity()
    loop = Loop()
    loop.is_outer, loop.is_convex = read_loop_prefix(reader)
    # CLoop uses a null object tag as its terminator rather than serializing an
    # edge-use count. The null tag is consumed by read_object().
    while True:
        tag, value = read_edge_use()
        if tag.kind == "null":
            return loop
        if isinstance(value, EdgeUse):
            loop.edge_uses.append(value)


def read_loop(context: ObjectReadContext) -> Loop:
    """Read a loop and resolve its null-terminated edge-use sequence."""
    return read_loop_body(
        context.session.reader,
        read_entity=context.read_entity,
        read_edge_use=context.read_object,
    )


def read_face_body(
    reader: LegacyArchiveReader,
    *,
    object_tag: ArchiveObjectTag,
    class_version: int,
    read_drawing_element: Callable[[], DrawingElementState],
    read_loop: Callable[[], object],
    read_reference: Callable[[], ArchiveObjectTag],
    apply_texture_coords: Callable[[Face, DrawingElementState], None] | None = None,
) -> Face:
    """Read a face and retain resolved shared loops."""
    drawing_element = read_drawing_element()
    plane = reader.read_vec4_f64()
    loop_count = reader.read_u32()
    # SketchUp serializes the outer loop first; build_face relies on that order
    # when splitting the list into outer and inner loops.
    loops = [loop for _ in range(loop_count) if isinstance((loop := read_loop()), Loop)]
    back_material = read_reference() if class_version > 2 else None
    face = build_face(
        face_id=object_tag.index or 0,
        plane=plane,
        loops=loops,
        front_material_id=drawing_element.material_tag.index,
        back_material_id=back_material.index if back_material is not None else None,
    )
    face.layer_id = drawing_element.layer_tag.index if drawing_element.layer_tag is not None else None
    if apply_texture_coords is not None:
        apply_texture_coords(face, drawing_element)
    return face


def read_face(
    context: ObjectReadContext,
    *,
    object_tag: ArchiveObjectTag,
    class_version: int,
) -> Face:
    """Read a face and resolve its loops and material references."""
    return read_face_body(
        context.session.reader,
        object_tag=object_tag,
        class_version=class_version,
        read_drawing_element=context.read_drawing_element,
        read_loop=lambda: context.read_object()[1],
        read_reference=context.read_reference,
        apply_texture_coords=lambda face, drawing_element: _apply_face_texture_coords(context, face, drawing_element),
    )


def _apply_face_texture_coords(
    context: ObjectReadContext,
    face: Face,
    drawing_element: DrawingElementState,
) -> None:
    """Attach a face's technical UV payload from its attribute container."""
    texture_payload = _resolve_face_texture_payload(context, drawing_element)
    if texture_payload is None:
        return
    _attribute_flags, front_uv, back_uv, front_flags, back_flags = texture_payload
    if front_flags is None or front_flags & 0x01:
        face.front_uv = front_uv
    if back_uv is not None and (back_flags is None or back_flags & 0x01):
        face.back_uv = back_uv


def _resolve_face_texture_payload(
    context: ObjectReadContext,
    drawing_element: DrawingElementState,
) -> FaceTextureCoordsPayload | None:
    """Resolve the face UV attribute already stored in the archive session."""
    entity_header = drawing_element.entity_header
    container_index = entity_header.attribute_container_object_index
    if container_index is None:
        container_tag = entity_header.attribute_container_tag
        if container_tag is not None and container_tag.kind == "object_ref":
            container_index = container_tag.index
    if container_index is None:
        return None
    container = context.session.objects.get(container_index)
    # Attribute containers and their entries were decoded recursively while the
    # face's CEntity prefix was read, so UV lookup must use the session table
    # rather than consume more bytes from the current face body.
    if not isinstance(container, tuple) or len(container) != 5:
        return None
    container_payload = cast(AttributeContainerPayload, container)

    for entry_tag in container_payload[1]:
        if entry_tag.index is None:
            continue
        entry = context.session.index_table.resolve_object(entry_tag.index)
        if entry is None or entry.class_name != "CFaceTextureCoords":
            continue
        payload = context.session.objects.get(entry_tag.index)
        if not isinstance(payload, tuple) or len(payload) != 5:
            continue
        return cast(FaceTextureCoordsPayload, payload)
    return None


def read_guide_point_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_drawing_element: Callable[[], DrawingElementState],
) -> GuidePoint:
    """Read a construction point after consuming its drawing-element base."""
    drawing_element = read_drawing_element()
    point = read_guide_point_payload(reader, class_version=class_version)
    point.layer_id = drawing_element.layer_tag.index if drawing_element.layer_tag is not None else None
    return point


def read_guide_line_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    file_version: str = "8",
    read_drawing_element: Callable[[], DrawingElementState],
) -> GuideLine:
    """Read a construction line after consuming its drawing-element base."""
    drawing_element = read_drawing_element()
    line = read_guide_line_payload(
        reader,
        class_version=class_version,
        file_version=file_version,
    )
    line.layer_id = drawing_element.layer_tag.index if drawing_element.layer_tag is not None else None
    return line


def read_section_plane_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    file_version: str = "18",
    read_drawing_element: Callable[[], DrawingElementState],
) -> SectionPlane:
    """Read a section plane after consuming its drawing-element base."""
    drawing_element = read_drawing_element()
    section = read_section_plane_payload(
        reader,
        class_version=class_version,
        file_version=file_version,
    )
    section.layer_id = drawing_element.layer_tag.index if drawing_element.layer_tag is not None else None
    return section


def read_construction_geometry_body(
    *,
    class_version: int,
    read_drawing_element: Callable[[], DrawingElementState],
) -> DrawingElementState:
    """Read the base-only ``CConstructionGeometry`` payload."""
    if class_version != 0:
        raise NotImplementedError("Only SketchUp 8 CConstructionGeometry version 0 is decoded.")
    return read_drawing_element()


def read_polyline_body(
    reader: LegacyArchiveReader,
    *,
    class_version: int,
    read_drawing_element: Callable[[], DrawingElementState],
) -> Polyline3dPayload:
    """Read a polyline and its shared drawing-element base."""
    drawing_element = read_drawing_element()
    return drawing_element, read_polyline_points(reader, class_version=class_version)


def read_edge_preview(stream: BinaryIO, *, entity_class_version: int, edge_class_version: int) -> EdgeState:
    """Read a tagged standalone edge fixture."""
    reader = LegacyArchiveReader(stream)
    object_tag = reader.read_object_tag()
    return read_edge_body(
        reader,
        object_tag=object_tag,
        object_index=None,
        class_version=edge_class_version,
        read_drawing_element=lambda: _read_standalone_drawing_element(reader, entity_class_version),
        read_vertex_object=lambda: read_vertex(stream, entity_class_version=entity_class_version),
        read_curve_object=lambda: (reader.read_object_tag(), None),
    )


def read_edge_preview_from_session(
    session: LegacyArchiveSession, *, entity_class_version: int, edge_class_version: int
) -> EdgeState:
    """Read an edge fixture while retaining session object-table identity."""
    handle = session.read_object_handle()
    context: ObjectReadContext

    def resolve(child: ArchiveObjectHandle) -> SupportedObjectPayload:
        if child.kind == "object_ref" and child.object_index is not None:
            return session.objects.get(child.object_index, child)
        if child.kind == "new_object" and child.class_name == "CVertex":
            value = read_vertex_body(
                session.reader,
                object_tag=child.tag,
                read_entity=context.read_entity,
            )
            if child.object_index is not None:
                session.store_object(child.object_index, value)
            return value
        return child

    context = ObjectReadContext(
        session,
        {"CEntity": entity_class_version, "CDrawingElement": 9},
        resolve,
    )
    return read_edge(
        context,
        object_tag=handle.tag,
        object_index=handle.object_index,
        class_version=edge_class_version,
    )


def read_edge_use_preview(stream: BinaryIO, *, entity_class_version: int, edge_use_class_version: int) -> EdgeUse:
    """Read a tagged standalone edge-use fixture."""
    reader = LegacyArchiveReader(stream)
    reader.read_object_tag()
    return read_edge_use_body(
        reader,
        class_version=edge_use_class_version,
        read_entity=lambda: _read_standalone_entity(reader, entity_class_version),
        read_edge=lambda: reader.read_object_tag().index or 0,
        read_reference=reader.read_object_tag,
    )


def read_loop_preview(stream: BinaryIO, *, entity_class_version: int) -> Loop:
    """Read a tagged standalone loop fixture."""
    reader = LegacyArchiveReader(stream)
    reader.read_object_tag()
    return read_loop_body(
        reader,
        read_entity=lambda: _read_standalone_entity(reader, entity_class_version),
        read_edge_use=lambda: (reader.read_object_tag(), None),
    )


def read_face_preview(
    stream: BinaryIO,
    *,
    entity_class_version: int,
    face_class_version: int,
) -> Face:
    """Read a tagged standalone face fixture."""
    reader = LegacyArchiveReader(stream)
    object_tag = reader.read_object_tag()
    return read_face_body(
        reader,
        object_tag=object_tag,
        class_version=face_class_version,
        read_drawing_element=lambda: _read_standalone_drawing_element(reader, entity_class_version),
        read_loop=lambda: (reader.read_object_tag(), None)[1],
        read_reference=reader.read_object_tag,
    )


def _read_standalone_entity(reader: LegacyArchiveReader, class_version: int) -> EntityHeaderState:
    return read_entity_header_body(
        reader,
        class_version=class_version,
        read_reference=reader.read_object_tag,
    )


def _read_standalone_drawing_element(reader: LegacyArchiveReader, entity_class_version: int) -> DrawingElementState:
    start = reader.tell()
    entity = _read_standalone_entity(reader, entity_class_version)
    material_tag = reader.read_object_tag()
    body = read_drawing_element_body(reader, 9)
    # Keep this fallback state atomic for the same reason as the normal context
    # path: downstream readers must never observe a half-decoded entity base.
    return DrawingElementState(
        payload_start_offset=start,
        entity_header=entity,
        material_tag=material_tag,
        hidden=body[0],
        casts_shadows=body[1],
        receives_shadows=body[2],
        soft=body[3],
        smooth=body[4],
        locked=body[5],
        layer_tag=body[6],
        payload_end_offset=reader.tell(),
    )
