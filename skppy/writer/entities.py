# SPDX-License-Identifier: MIT
"""Modern ``model.dat`` encoders for core geometric entities."""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterable, Mapping
from math import cos, isfinite, sin

from ..data_structure.annotations import (
    Dimension,
    LinearDimension,
    PointReference,
    RadialDimension,
    Text,
)
from ..data_structure.construction import GuideLine, GuidePoint, SectionPlane
from ..data_structure.entities import (
    EDGE_FLAG_HIDDEN,
    EDGE_FLAG_SMOOTH,
    EDGE_FLAG_SOFT,
    ArcCurve,
    ComponentInstance,
    Curve,
    Edge,
    Entities,
    Face,
    FaceUVProjection,
    Group,
    Image,
    Loop,
    Vertex,
)
from ..data_structure.primitives import Vector3D
from ..data_structure.model_metadata import AttributeDictionary
from ..parser.tlv import TlvTag
from .tlv import encode_bool, encode_compact_int, encode_record, encode_records
from .attributes import encode_attribute_dictionary_records

# Parser and writer share the numeric schema through TlvTag, while their byte
# operations remain independent so round-trip tests can catch framing defects.
_BASELINE_ENTITY_FLAGS = 0x06
_MODERN_ENTITY_HIDDEN = 0x01
_MODERN_ENTITY_CASTS_SHADOWS = 0x02
_MODERN_ENTITY_RECEIVES_SHADOWS = 0x04
_MODERN_EDGE_SOFT = 0x08
_MODERN_EDGE_SMOOTH = 0x10

PointReferenceIdResolver = Callable[[int, tuple[int, ...]], tuple[int, tuple[int, ...]]]


def encode_entities(
    entities: Entities,
    *,
    id_map: Mapping[int, int] | None = None,
    material_id_map: Mapping[int, int] | None = None,
    layer_id_map: Mapping[int, int] | None = None,
    definition_id_map: Mapping[int, int] | None = None,
    font_id_map: Mapping[int, int] | None = None,
    scope_id: int | None = None,
    scope_attribute_dictionaries: Iterable[AttributeDictionary] = (),
    point_reference_id_resolver: PointReferenceIdResolver | None = None,
) -> bytes:
    """Encode core geometry as a complete modern ``ENTITIES`` TLV record.

    The writer supports vertices, edges, faces, curves, arc curves, instances,
    groups, their material/layer references, face UV projections, and edge
    display flags.
    Unsupported entity families are rejected explicitly so saving cannot
    silently lose model data.
    """
    _validate_supported_scope(entities)
    _validate_geometry(entities)
    resolved_ids = _validated_id_map(entities, id_map)
    reference_id_resolver = point_reference_id_resolver or (
        lambda entity_id, path_ids: (
            resolved_ids[entity_id],
            tuple(resolved_ids[path_id] for path_id in path_ids),
        )
    )
    fields: list[tuple[int, bytes]] = [
        (
            TlvTag.ENTITY_BASE,
            _entity_base_payload(
                scope_id,
                attribute_dictionaries=scope_attribute_dictionaries,
            ),
        ),
        (
            TlvTag.VERTICES,
            _encode_vertices(
                entities.vertices,
                resolved_ids,
                entities.attribute_dictionaries_by_entity_id,
            ),
        ),
    ]
    # Curves precede their edge records in SketchUp's canonical scope order.
    # The SDK rejects otherwise valid files when an edge refers backward to a
    # curve section emitted after EDGES.
    if entities.curves:
        fields.append(
            (
                TlvTag.CURVES,
                _encode_curves(
                    entities.curves,
                    resolved_ids,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            )
        )
    if entities.arc_curves:
        fields.append(
            (
                TlvTag.ARC_CURVES,
                _encode_arc_curves(
                    entities,
                    resolved_ids,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            )
        )
    fields.extend(
        [
            (
                TlvTag.EDGES,
                _encode_edges(
                    entities.edges,
                    resolved_ids,
                    layer_id_map,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            ),
            (
                TlvTag.FACES,
                _encode_faces(
                    entities.faces,
                    resolved_ids,
                    material_id_map,
                    layer_id_map,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            ),
            (
                TlvTag.COMPONENT_INSTANCES,
                _encode_instances(
                    entities.component_instances,
                    resolved_ids,
                    material_id_map,
                    layer_id_map,
                    definition_id_map,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            ),
            (
                TlvTag.GROUPS,
                _encode_groups(
                    entities.groups,
                    resolved_ids,
                    material_id_map,
                    layer_id_map,
                    definition_id_map,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            ),
        ]
    )
    if entities.images:
        fields.append(
            (
                TlvTag.IMAGES,
                _encode_images(
                    entities.images,
                    resolved_ids,
                    material_id_map,
                    layer_id_map,
                    definition_id_map,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            )
        )
    if entities.guide_lines:
        fields.append(
            (
                TlvTag.GUIDE_LINES,
                _encode_guide_lines(
                    entities.guide_lines,
                    resolved_ids,
                    layer_id_map,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            )
        )
    if entities.guide_points:
        fields.append(
            (
                TlvTag.GUIDE_POINTS,
                _encode_guide_points(
                    entities.guide_points,
                    resolved_ids,
                    layer_id_map,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            )
        )
    if entities.section_planes:
        fields.append(
            (
                TlvTag.SECTION_PLANES,
                _encode_section_planes(
                    entities.section_planes,
                    resolved_ids,
                    layer_id_map,
                    entities.attribute_dictionaries_by_entity_id,
                ),
            )
        )
    fields.extend(
        _annotation_sections(
            entities,
            resolved_ids,
            material_id_map,
            layer_id_map,
            entities.attribute_dictionaries_by_entity_id,
            reference_id_resolver,
            font_id_map,
        )
    )
    fields.append((TlvTag.ENTITIES_SENTINEL, b""))
    drawing_order = [face.id for face in entities.faces]
    drawing_order.extend(edge.id for edge in entities.edges)
    drawing_order.extend(instance.id for instance in entities.component_instances)
    drawing_order.extend(group.id for group in entities.groups)
    drawing_order.extend(image.id for image in entities.images)
    drawing_order.extend(line.id for line in entities.guide_lines)
    drawing_order.extend(point.id for point in entities.guide_points)
    drawing_order.extend(plane.id for plane in entities.section_planes)
    drawing_order.extend(text.id for text in entities.texts)
    drawing_order.extend(dimension.id for dimension in entities.linear_dimensions)
    drawing_order.extend(dimension.id for dimension in entities.radial_dimensions)
    if drawing_order:
        fields.append(
            (
                TlvTag.DRAW_ELEM_REF,
                _encode_width_prefixed_ids(drawing_order, resolved_ids),
            )
        )
    metadata = encode_records(
        (
            (TlvTag.ENTITIES_METADATA_RECORD, b""),
            (TlvTag.ENTITIES_METADATA_PAYLOAD, b""),
        )
    )
    fields.extend(
        (
            (TlvTag.ENTITIES_METADATA_BLOCK, metadata),
            (TlvTag.COMPONENT_STATE_FLAGS, b"\x00"),
        )
    )
    return encode_record(TlvTag.ENTITIES, encode_records(fields))


def _annotation_sections(
    entities: Entities,
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
    point_reference_id_resolver: PointReferenceIdResolver,
    font_id_map: Mapping[int, int] | None,
) -> list[tuple[int, bytes]]:
    sections: list[tuple[int, bytes]] = []
    if entities.texts:
        sections.append(
            (
                TlvTag.TEXTS,
                _encode_texts(
                    entities.texts,
                    id_map,
                    material_id_map,
                    layer_id_map,
                    attribute_dictionaries_by_entity_id,
                    point_reference_id_resolver,
                    font_id_map,
                ),
            )
        )
    if entities.linear_dimensions:
        sections.append(
            (
                TlvTag.DIMENSIONS,
                _encode_linear_dimensions(
                    entities.linear_dimensions,
                    id_map,
                    material_id_map,
                    layer_id_map,
                    attribute_dictionaries_by_entity_id,
                    point_reference_id_resolver,
                    font_id_map,
                ),
            )
        )
    if entities.radial_dimensions:
        sections.append(
            (
                TlvTag.RADIAL_DIMENSIONS,
                _encode_radial_dimensions(
                    entities.radial_dimensions,
                    id_map,
                    material_id_map,
                    layer_id_map,
                    attribute_dictionaries_by_entity_id,
                    point_reference_id_resolver,
                    font_id_map,
                ),
            )
        )
    return sections


def _encode_instances(
    instances: Iterable[ComponentInstance],
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    definition_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    records = []
    for instance in instances:
        records.append(
            (
                TlvTag.INSTANCE_RECORD,
                _encode_instance_payload(
                    instance,
                    id_map,
                    material_id_map,
                    layer_id_map,
                    definition_id_map,
                    attribute_dictionaries_by_entity_id,
                ),
            )
        )
    return encode_records(records)


def _encode_groups(
    groups: Iterable[Group],
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    definition_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    records = []
    for group in groups:
        instance_payload = _encode_instance_payload(
            group,
            id_map,
            material_id_map,
            layer_id_map,
            definition_id_map,
            attribute_dictionaries_by_entity_id,
        )
        records.append(
            (
                TlvTag.GROUP_RECORD,
                encode_record(TlvTag.INSTANCE_RECORD, instance_payload),
            )
        )
    return encode_records(records)


def _encode_images(
    images: Iterable[Image],
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    definition_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    records = []
    for image in images:
        instance_payload = _encode_instance_payload(
            image,
            id_map,
            material_id_map,
            layer_id_map,
            definition_id_map,
            attribute_dictionaries_by_entity_id,
        )
        records.append(
            (
                TlvTag.IMAGE_RECORD,
                encode_record(TlvTag.INSTANCE_RECORD, instance_payload),
            )
        )
    return encode_records(records)


def _encode_instance_payload(
    instance: ComponentInstance | Group | Image,
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    definition_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    if definition_id_map is None or instance.definition_id not in definition_id_map:
        raise ValueError(f"Missing definition ID mapping for {instance.definition_id}")
    return encode_records(
        (
            (
                TlvTag.ENTITY_BASE,
                _entity_base_payload(
                    id_map[instance.id],
                    front_material_id=_mapped_optional_id(instance.material_id, material_id_map, "material"),
                    layer_id=_mapped_optional_id(instance.layer_id, layer_id_map, "layer"),
                    attribute_dictionaries=attribute_dictionaries_by_entity_id.get(instance.id, ()),
                ),
            ),
            (TlvTag.INSTANCE_NAME, (instance.name or "").encode("utf-8")),
            (TlvTag.INSTANCE_TRANSFORM, struct.pack("<13d", *instance.transform)),
            (
                TlvTag.INSTANCE_DEF_ID,
                encode_compact_int(definition_id_map[instance.definition_id]),
            ),
            (TlvTag.INSTANCE_GUID, instance.guid),
        )
    )


def _encode_vertices(
    vertices: Iterable[Vertex],
    id_map: Mapping[int, int],
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    records = []
    for vertex in vertices:
        payload = encode_records(
            (
                (
                    TlvTag.ID_WRAPPER,
                    _id_wrapper(
                        id_map[vertex.id],
                        _encode_id_extension(
                            None,
                            None,
                            attribute_dictionaries_by_entity_id.get(vertex.id, ()),
                        ),
                    ),
                ),
                (
                    TlvTag.VERTEX_POSITION,
                    struct.pack(
                        "<3d",
                        vertex.position.x,
                        vertex.position.y,
                        vertex.position.z,
                    ),
                ),
            )
        )
        records.append((TlvTag.VERTEX_RECORD, payload))
    return encode_records(records)


def _encode_edges(
    edges: Iterable[Edge],
    id_map: Mapping[int, int],
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    records = []
    for edge in edges:
        fields: list[tuple[int, bytes]] = [
            (
                TlvTag.ENTITY_BASE,
                _entity_base_payload(
                    id_map[edge.id],
                    flags=_encode_edge_flags(edge.flags),
                    layer_id=_mapped_optional_id(edge.layer_id, layer_id_map, "layer"),
                    attribute_dictionaries=attribute_dictionaries_by_entity_id.get(edge.id, ()),
                ),
            ),
            (
                TlvTag.EDGE_START_VERTEX,
                encode_compact_int(id_map[edge.start_vertex_id]),
            ),
            (TlvTag.EDGE_END_VERTEX, encode_compact_int(id_map[edge.end_vertex_id])),
        ]
        if edge.curve_id is not None:
            fields.append((TlvTag.EDGE_CURVE_ID, encode_compact_int(id_map[edge.curve_id])))
        records.append((TlvTag.EDGE_RECORD, encode_records(fields)))
    return encode_records(records)


def _encode_curves(
    curves: Iterable[Curve],
    id_map: Mapping[int, int],
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    return encode_records(
        (
            TlvTag.CURVE_RECORD,
            _encode_curve_payload(curve, id_map, attribute_dictionaries_by_entity_id),
        )
        for curve in curves
    )


def _encode_arc_curves(
    entities: Entities,
    id_map: Mapping[int, int],
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    vertices = {vertex.id: vertex.position for vertex in entities.vertices}
    edges = {edge.id: edge for edge in entities.edges}
    records = []
    for arc in entities.arc_curves:
        payload = encode_records(
            (
                (
                    TlvTag.CURVE_RECORD,
                    _encode_curve_payload(arc, id_map, attribute_dictionaries_by_entity_id),
                ),
                (
                    TlvTag.ARC_SPECIFIC_PAYLOAD,
                    _encode_arc_geometry(arc, vertices, edges),
                ),
            )
        )
        records.append((TlvTag.ARC_CURVE_RECORD, payload))
    return encode_records(records)


def _encode_curve_payload(
    curve: Curve | ArcCurve,
    id_map: Mapping[int, int],
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    mapped_edges = [id_map[edge_id] for edge_id in curve.edge_ids]
    fields: list[tuple[int, bytes]] = [
        (
            TlvTag.ID_WRAPPER,
            _id_wrapper(
                id_map[curve.id],
                _encode_id_extension(
                    None,
                    None,
                    attribute_dictionaries_by_entity_id.get(curve.id, ()),
                ),
            ),
        ),
        (TlvTag.CURVE_EDGE_COUNT, struct.pack("<I", len(mapped_edges))),
        (
            TlvTag.CURVE_POLYGON_FLAG,
            encode_bool(isinstance(curve, Curve) and curve.is_polygon),
        ),
    ]
    if mapped_edges:
        fields.extend(
            (
                (TlvTag.CURVE_FIRST_EDGE_ID, encode_compact_int(mapped_edges[0])),
                (TlvTag.CURVE_LAST_EDGE_ID, encode_compact_int(mapped_edges[-1])),
            )
        )
    return encode_records(fields)


def _encode_arc_geometry(
    arc: ArcCurve,
    vertices: Mapping[int, Vector3D],
    edges: Mapping[int, Edge],
) -> bytes:
    semantic_values = (
        arc.center,
        arc.normal,
        arc.radius,
        arc.start_angle,
        arc.end_angle,
    )
    if any(value is None for value in semantic_values):
        # ``_validate_arc_curve`` guarantees this invariant before encoding.
        assert arc.raw_arc_payload is not None
        return arc.raw_arc_payload

    assert arc.center is not None
    assert arc.normal is not None
    assert arc.radius is not None
    assert arc.start_angle is not None
    assert arc.end_angle is not None
    first_edge = edges[arc.edge_ids[0]]
    first_point = vertices[first_edge.start_vertex_id]
    center = arc.center
    normal = arc.normal
    radial = (
        first_point.x - center[0],
        first_point.y - center[1],
        first_point.z - center[2],
    )
    cross = (
        normal[1] * radial[2] - normal[2] * radial[1],
        normal[2] * radial[0] - normal[0] * radial[2],
        normal[0] * radial[1] - normal[1] * radial[0],
    )
    cosine = cos(arc.start_angle)
    sine = sin(arc.start_angle)
    x_axis = tuple(radial[index] * cosine - cross[index] * sine for index in range(3))
    y_axis = (
        normal[1] * x_axis[2] - normal[2] * x_axis[1],
        normal[2] * x_axis[0] - normal[0] * x_axis[2],
        normal[0] * x_axis[1] - normal[1] * x_axis[0],
    )
    plane_distance = -sum(normal[index] * center[index] for index in range(3))
    return struct.pack(
        "<16d",
        *center,
        *normal,
        plane_distance,
        *x_axis,
        *y_axis,
        arc.radius,
        arc.start_angle,
        arc.end_angle,
    )


def _encode_faces(
    faces: Iterable[Face],
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    records = []
    for face in faces:
        fields = [
            (
                TlvTag.ENTITY_BASE,
                _entity_base_payload(
                    id_map[face.id],
                    front_material_id=_mapped_optional_id(face.front_material_id, material_id_map, "material"),
                    layer_id=_mapped_optional_id(face.layer_id, layer_id_map, "layer"),
                    front_uv=face.front_uv,
                    back_uv=face.back_uv,
                    attribute_dictionaries=attribute_dictionaries_by_entity_id.get(face.id, ()),
                ),
            ),
        ]
        back_material_id = _mapped_optional_id(face.back_material_id, material_id_map, "material")
        if back_material_id is not None:
            fields.append((TlvTag.FACE_EXTRA_FLAG, encode_compact_int(back_material_id)))
        fields.extend(
            (
                (TlvTag.FACE_PLANE, struct.pack("<4d", *face.plane)),
                (
                    TlvTag.FACE_LOOPS,
                    _encode_loops((face.outer_loop, *face.inner_loops), id_map),
                ),
            )
        )
        records.append((TlvTag.FACE_RECORD, encode_records(fields)))
    return encode_records(records)


def _encode_loops(loops: Iterable[Loop], id_map: Mapping[int, int]) -> bytes:
    records = []
    for loop in loops:
        edge_uses = []
        for edge_use in loop.edge_uses:
            payload = encode_records(
                (
                    (
                        TlvTag.EDGE_USE_ID,
                        encode_compact_int(id_map[edge_use.edge_id]),
                    ),
                    (TlvTag.EDGE_USE_REVERSED, encode_bool(edge_use.reversed)),
                )
            )
            edge_uses.append((TlvTag.EDGE_USE, payload))
        loop_payload = encode_record(TlvTag.EDGE_USES, encode_records(edge_uses))
        records.append((TlvTag.LOOP_RECORD, loop_payload))
    return encode_records(records)


def _encode_guide_lines(
    lines: Iterable[GuideLine],
    id_map: Mapping[int, int],
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    records = []
    for line in lines:
        point = _vector3_values(line.point)
        direction = _vector3_values(line.direction)
        geometry = struct.pack(
            "<8d",
            *point,
            *direction,
            line.start_parameter,
            line.end_parameter,
        )
        construction_base = encode_record(
            TlvTag.ENTITY_BASE,
            _entity_base_payload(
                id_map[line.id],
                layer_id=_mapped_optional_id(line.layer_id, layer_id_map, "layer"),
                attribute_dictionaries=attribute_dictionaries_by_entity_id.get(line.id, ()),
            ),
        )
        payload = encode_records(
            (
                (TlvTag.CONSTRUCTION_GEOMETRY_BASE, construction_base),
                (TlvTag.GUIDE_LINE_GEOMETRY, geometry),
                (TlvTag.GUIDE_LINE_STIPPLE, struct.pack("<H", line.stipple_pattern)),
            )
        )
        records.append((TlvTag.GUIDE_LINE_RECORD, payload))
    return encode_records(records)


def _encode_guide_points(
    points: Iterable[GuidePoint],
    id_map: Mapping[int, int],
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    records = []
    for point in points:
        construction_base = encode_record(
            TlvTag.ENTITY_BASE,
            _entity_base_payload(
                id_map[point.id],
                layer_id=_mapped_optional_id(point.layer_id, layer_id_map, "layer"),
                attribute_dictionaries=attribute_dictionaries_by_entity_id.get(point.id, ()),
            ),
        )
        reference = _vector3_values(point.reference_point) if point.reference_point is not None else (0.0, 0.0, 0.0)
        payload = encode_records(
            (
                (TlvTag.CONSTRUCTION_GEOMETRY_BASE, construction_base),
                (
                    TlvTag.GUIDE_POINT_POSITION,
                    struct.pack("<3d", *_vector3_values(point.position)),
                ),
                (
                    TlvTag.GUIDE_POINT_REFERENCE_POSITION,
                    struct.pack("<3d", *reference),
                ),
                (
                    TlvTag.GUIDE_POINT_HAS_REFERENCE_POSITION,
                    encode_bool(point.reference_point is not None),
                ),
            )
        )
        records.append((TlvTag.GUIDE_POINT_RECORD, payload))
    return encode_records(records)


def _encode_section_planes(
    planes: Iterable[SectionPlane],
    id_map: Mapping[int, int],
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
) -> bytes:
    records = []
    for plane in planes:
        payload = encode_records(
            (
                (
                    TlvTag.ENTITY_BASE,
                    _entity_base_payload(
                        id_map[plane.id],
                        layer_id=_mapped_optional_id(plane.layer_id, layer_id_map, "layer"),
                        attribute_dictionaries=attribute_dictionaries_by_entity_id.get(plane.id, ()),
                    ),
                ),
                (TlvTag.SECTION_PLANE_PLANE, struct.pack("<4d", *plane.plane)),
                (TlvTag.SECTION_PLANE_NAME, plane.name.encode("utf-8")),
                (TlvTag.SECTION_PLANE_SYMBOL, plane.symbol.encode("utf-8")),
            )
        )
        records.append((TlvTag.SECTION_PLANE_RECORD, payload))
    return encode_records(records)


def _vector3_values(
    value: tuple[float, float, float] | Vector3D,
) -> tuple[float, float, float]:
    if isinstance(value, Vector3D):
        return value.x, value.y, value.z
    return value


def _encode_linear_dimensions(
    dimensions: Iterable[LinearDimension],
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
    point_reference_id_resolver: PointReferenceIdResolver,
    font_id_map: Mapping[int, int] | None,
) -> bytes:
    records: list[tuple[int, bytes]] = []
    for dimension in dimensions:
        common = _dimension_common_payload(
            dimension,
            id_map,
            material_id_map,
            layer_id_map,
            attribute_dictionaries_by_entity_id,
            font_id_map,
        )
        payload = encode_records(
            (
                (TlvTag.DIMENSION_BASE, common),
                (
                    TlvTag.DIMENSION_ANCHOR_A,
                    _encode_point_reference(dimension.start, point_reference_id_resolver),
                ),
                (
                    TlvTag.DIMENSION_ANCHOR_B,
                    _encode_point_reference(dimension.end, point_reference_id_resolver),
                ),
                (
                    TlvTag.DIMENSION_DIRECTION,
                    struct.pack("<3d", *_vector3_values(dimension.direction)),
                ),
                (
                    TlvTag.DIMENSION_RENDER_DIR,
                    struct.pack("<3d", *_vector3_values(dimension.render_direction)),
                ),
                (TlvTag.DIMENSION_MODE, struct.pack("<I", dimension.mode)),
                (TlvTag.DIMENSION_OFFSET, struct.pack("<d", dimension.offset)),
                (
                    TlvTag.DIMENSION_LINE_POS,
                    struct.pack("<d", dimension.line_position),
                ),
                (TlvTag.DIMENSION_ALIGNMENT, struct.pack("<I", dimension.alignment)),
            )
        )
        records.append((TlvTag.DIMENSION_RECORD, payload))
    return encode_records(records)


def _encode_radial_dimensions(
    dimensions: Iterable[RadialDimension],
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
    point_reference_id_resolver: PointReferenceIdResolver,
    font_id_map: Mapping[int, int] | None,
) -> bytes:
    records: list[tuple[int, bytes]] = []
    for dimension in dimensions:
        target_entity_id = dimension.target_entity_id
        if target_entity_id is None:
            raise NotImplementedError("Modern radial dimensions currently require an associated arc")
        if dimension.arc is not None:
            raise ValueError("Associated radial dimensions cannot also contain an inline arc")
        target_id = _mapped_optional_id(target_entity_id, id_map, "radial dimension target")
        assert target_id is not None
        payload = encode_records(
            (
                (
                    TlvTag.DIMENSION_BASE,
                    _dimension_common_payload(
                        dimension,
                        id_map,
                        material_id_map,
                        layer_id_map,
                        attribute_dictionaries_by_entity_id,
                        font_id_map,
                    ),
                ),
                (
                    TlvTag.RADIAL_DIMENSION_TARGET_REF,
                    encode_compact_int(target_id),
                ),
                (
                    TlvTag.RADIAL_DIMENSION_PARAMETER,
                    struct.pack("<d", dimension.parameter),
                ),
                (
                    TlvTag.RADIAL_DIMENSION_RADIUS_RATIO,
                    struct.pack("<d", dimension.radius_ratio),
                ),
                (
                    TlvTag.RADIAL_DIMENSION_IS_DIAMETER,
                    encode_bool(dimension.is_diameter),
                ),
            )
        )
        records.append((TlvTag.RADIAL_DIMENSION_RECORD, payload))
    return encode_records(records)


def _dimension_common_payload(
    dimension: Dimension,
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
    font_id_map: Mapping[int, int] | None,
) -> bytes:
    font_id = _annotation_font_id(dimension, font_id_map)
    return encode_records(
        (
            (
                TlvTag.ENTITY_BASE,
                _entity_base_payload(
                    id_map[dimension.id],
                    baseline_flags=_annotation_flags(dimension),
                    front_material_id=_mapped_optional_id(
                        dimension.drawing.material_id,
                        material_id_map,
                        "material",
                    ),
                    layer_id=_mapped_optional_id(dimension.drawing.layer_id, layer_id_map, "layer"),
                    attribute_dictionaries=attribute_dictionaries_by_entity_id.get(dimension.id, ()),
                ),
            ),
            (TlvTag.DIMENSION_TEXT, dimension.text.encode("utf-8")),
            *(
                (
                    (
                        TlvTag.DIMENSION_FONT_REF,
                        encode_compact_int(font_id),
                    ),
                )
                if font_id is not None
                else ()
            ),
            (TlvTag.DIMENSION_3D_TEXT, encode_bool(dimension.is_3d_text)),
            (
                TlvTag.DIMENSION_ARROW_TYPE,
                struct.pack("<I", dimension.arrow_type),
            ),
        )
    )


def _encode_texts(
    texts: Iterable[Text],
    id_map: Mapping[int, int],
    material_id_map: Mapping[int, int] | None,
    layer_id_map: Mapping[int, int] | None,
    attribute_dictionaries_by_entity_id: Mapping[int, Iterable[AttributeDictionary]],
    point_reference_id_resolver: PointReferenceIdResolver,
    font_id_map: Mapping[int, int] | None,
) -> bytes:
    records: list[tuple[int, bytes]] = []
    for text in texts:
        _validate_text(text)
        fields: list[tuple[int, bytes]] = [
            (
                TlvTag.ENTITY_BASE,
                _entity_base_payload(
                    id_map[text.id],
                    baseline_flags=_annotation_flags(text),
                    front_material_id=_mapped_optional_id(text.drawing.material_id, material_id_map, "material"),
                    layer_id=_mapped_optional_id(text.drawing.layer_id, layer_id_map, "layer"),
                    attribute_dictionaries=attribute_dictionaries_by_entity_id.get(text.id, ()),
                ),
            ),
            (TlvTag.TEXT_VALUE, text.text.encode("utf-8")),
            (TlvTag.TEXT_SCREEN_X, struct.pack("<d", text.screen_position.x)),
            (TlvTag.TEXT_SCREEN_Y, struct.pack("<d", text.screen_position.y)),
            (
                TlvTag.TEXT_ANCHOR,
                _encode_point_reference(text.anchor, point_reference_id_resolver),
            ),
            (
                TlvTag.TEXT_LEADER_VECTOR,
                struct.pack("<3d", *_vector3_values(text.leader_vector)),
            ),
            (TlvTag.TEXT_ANCHOR_IN_FRONT, encode_bool(text.anchor_in_front)),
            (
                TlvTag.TEXT_VIEW_DIRECTION,
                struct.pack("<3d", *_vector3_values(text.view_direction)),
            ),
            (TlvTag.TEXT_HIDE_OUT_OF_PLANE, encode_bool(text.hide_out_of_plane)),
        ]
        font_id = _annotation_font_id(text, font_id_map)
        if font_id is not None:
            fields.append((TlvTag.TEXT_FONT_REF, encode_compact_int(font_id)))
        fields.extend(
            (
                (TlvTag.TEXT_LINE_WEIGHT, struct.pack("<I", text.line_weight)),
                (TlvTag.TEXT_LEADER_TYPE, struct.pack("<I", text.leader_type)),
                (TlvTag.TEXT_DISPLAY_LEADER, encode_bool(text.display_leader)),
                (TlvTag.TEXT_ARROW_TYPE, struct.pack("<I", text.arrow_type)),
                (
                    TlvTag.TEXT_HIDDEN_LEADER_DIRECTION,
                    struct.pack("<I", text.hidden_leader_direction),
                ),
            )
        )
        records.append((TlvTag.TEXT_RECORD, encode_records(fields)))
    return encode_records(records)


def _validate_text(text: Text) -> None:
    values = (
        text.screen_position.x,
        text.screen_position.y,
        *_vector3_values(text.leader_vector),
        *_vector3_values(text.view_direction),
    )
    if not all(isfinite(value) for value in values):
        raise ValueError("Text placement must contain finite values")
    integer_fields = (
        text.line_weight,
        text.leader_type,
        text.arrow_type,
        text.hidden_leader_direction,
    )
    if any(value < 0 or value > 0xFFFFFFFF for value in integer_fields):
        raise ValueError("Text enum and weight values must fit in u32")
    if text.convert_to_screen_on_explode:
        raise NotImplementedError("Modern text records do not expose convert-to-screen-on-explode")


def _annotation_font_id(
    annotation: Dimension | Text,
    font_id_map: Mapping[int, int] | None,
) -> int:
    font_id = annotation.font_id
    if annotation.font is not None:
        if font_id_map is None:
            raise ValueError("Annotation font objects require a model font mapping")
        try:
            mapped_font_id = font_id_map[id(annotation.font)]
        except KeyError as exc:
            raise ValueError("Annotation font is not registered in the model") from exc
        if font_id is not None and font_id != mapped_font_id:
            raise ValueError("Annotation font and font_id identify different fonts")
        font_id = mapped_font_id
    if font_id is None:
        # The official modern reader requires every annotation to reference a
        # font. Full model writes always install at least one font at ID 2.
        font_id = 2
    if not 1 <= font_id <= 0xFFFFFFFF:
        raise ValueError("Annotation font ID must fit in a positive u32")
    return font_id


def _encode_point_reference(
    reference: PointReference,
    id_resolver: PointReferenceIdResolver,
) -> bytes:
    if not 0 <= reference.kind <= 0xFFFFFFFF:
        raise ValueError("Point-reference kind must fit in u32")
    associated = reference.entity_id is not None or reference.secondary_entity_id is not None
    kind = reference.kind or (5 if associated else 1)
    point_reference = encode_records(
        (
            (TlvTag.DIMENSION_ANCHOR_ENABLED, struct.pack("<I", kind)),
            (
                TlvTag.DIMENSION_ANCHOR_POINT,
                struct.pack("<3d", *_vector3_values(reference.position)),
            ),
            (
                TlvTag.DIMENSION_ANCHOR_STYLE_A,
                _encode_point_reference_style(
                    reference.entity_id,
                    reference.instance_path_ids,
                    id_resolver,
                ),
            ),
            (
                TlvTag.DIMENSION_ANCHOR_STYLE_B,
                _encode_point_reference_style(
                    reference.secondary_entity_id,
                    reference.secondary_instance_path_ids,
                    id_resolver,
                ),
            ),
        )
    )
    return encode_record(TlvTag.POINT_REFERENCE, point_reference)


def _encode_point_reference_style(
    entity_id: int | None,
    instance_path_ids: Iterable[int],
    id_resolver: PointReferenceIdResolver,
) -> bytes:
    path_ids = tuple(instance_path_ids)
    if entity_id is None:
        if path_ids:
            raise ValueError("Point-reference paths require an associated entity")
        mapped_entity_id = None
        mapped_path_ids: tuple[int, ...] = ()
    else:
        try:
            mapped_entity_id, mapped_path_ids = id_resolver(entity_id, path_ids)
        except KeyError as exc:
            raise ValueError(f"Point reference contains an unknown entity ID: {exc.args[0]}") from exc
    style_fields: list[tuple[int, bytes]] = []
    if mapped_entity_id is not None:
        style_fields.append((TlvTag.DIMENSION_ANCHOR_STYLE_ENTITY, encode_compact_int(mapped_entity_id)))
    style_fields.append(
        (
            TlvTag.DIMENSION_ANCHOR_STYLE_VALUE,
            _encode_mapped_width_prefixed_ids(mapped_path_ids),
        )
    )
    return encode_record(
        TlvTag.DIMENSION_ANCHOR_STYLE_WRAPPER,
        encode_records(style_fields),
    )


def _annotation_flags(annotation: Dimension | Text) -> int:
    drawing = annotation.drawing
    if drawing.soft or drawing.smooth or drawing.locked:
        raise NotImplementedError("Modern annotation writer does not yet support soft, smooth, or locked state")
    flags = _MODERN_ENTITY_HIDDEN if drawing.hidden else 0
    if drawing.casts_shadows:
        flags |= _MODERN_ENTITY_CASTS_SHADOWS
    if drawing.receives_shadows:
        flags |= _MODERN_ENTITY_RECEIVES_SHADOWS
    return flags


def _entity_base_payload(
    entity_id: int | None = None,
    *,
    flags: int = 0,
    baseline_flags: int = _BASELINE_ENTITY_FLAGS,
    front_material_id: int | None = None,
    layer_id: int | None = None,
    front_uv: FaceUVProjection | None = None,
    back_uv: FaceUVProjection | None = None,
    attribute_dictionaries: Iterable[AttributeDictionary] = (),
) -> bytes:
    fields: list[tuple[int, bytes]] = []
    if entity_id is not None:
        extension = _encode_id_extension(
            front_uv,
            back_uv,
            attribute_dictionaries,
        )
        fields.append((TlvTag.ID_WRAPPER, _id_wrapper(entity_id, extension)))
    elif extension := _encode_id_extension(front_uv, back_uv, attribute_dictionaries):
        fields.append(
            (
                TlvTag.ID_WRAPPER,
                encode_record(TlvTag.ID_EXT_PAYLOAD, extension),
            )
        )
    if front_material_id is not None:
        fields.append((TlvTag.ENTITY_MATERIAL_REF, encode_compact_int(front_material_id)))
    if layer_id is not None:
        fields.append((TlvTag.ENTITY_LAYER_REF, encode_compact_int(layer_id)))
    fields.append((TlvTag.ENTITY_FLAGS, encode_compact_int(baseline_flags | flags)))
    return encode_records(fields)


def _id_wrapper(entity_id: int, extension: bytes | None) -> bytes:
    fields: list[tuple[int, bytes]] = [(TlvTag.ID_VALUE, encode_compact_int(entity_id))]
    if extension is not None:
        fields.append((TlvTag.ID_EXT_PAYLOAD, extension))
    return encode_records(fields)


def _encode_id_extension(
    front: FaceUVProjection | None,
    back: FaceUVProjection | None,
    dictionaries: Iterable[AttributeDictionary],
) -> bytes | None:
    dictionary_list = list(dictionaries)
    if front is None and back is None and not dictionary_list:
        return None
    records = b""
    if front is not None or back is not None:
        projection_pair = encode_records(
            (
                (TlvTag.ATTR_DICT_HEADER, b""),
                (TlvTag.TEX_PROJ_FRONT, _encode_uv_side(front)),
                (TlvTag.TEX_PROJ_BACK, _encode_uv_side(back)),
            )
        )
        attribute = encode_record(TlvTag.TEX_PROJ_PAIR, projection_pair)
        records += encode_record(TlvTag.ATTR_DICT_RECORD, attribute)
    records += encode_attribute_dictionary_records(dictionary_list)
    return encode_record(TlvTag.ATTR_DICTS_ROOT, records)


def _encode_uv_side(projection: FaceUVProjection | None) -> bytes:
    if projection is None:
        transform = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        origin = (0.0, 0.0, 0.0)
        pins: list[tuple[int, bytes]] = []
    else:
        _validate_projection(projection)
        transform = projection.transform
        origin = projection.origin
        pins = []
        for pin in projection.pins:
            pin_payload = encode_records(
                (
                    (
                        TlvTag.TEX_PROJ_PIN_TEXTURE_POSITION,
                        struct.pack("<2d", pin.texture_position.x, pin.texture_position.y),
                    ),
                    (
                        TlvTag.TEX_PROJ_PIN_MODEL_POSITION,
                        struct.pack("<2d", pin.model_position.x, pin.model_position.y),
                    ),
                )
            )
            pins.append((TlvTag.TEX_PROJ_PIN, pin_payload))
    payload = encode_records(
        (
            (TlvTag.TEX_PROJ_ENABLED, struct.pack("<I", projection is not None)),
            (TlvTag.TEX_PROJ_TRANSFORM, struct.pack("<9d", *transform)),
            (TlvTag.TEX_PROJ_ORIGIN, struct.pack("<3d", *origin)),
            (TlvTag.TEX_PROJ_PINS, encode_records(pins)),
        )
    )
    return encode_record(TlvTag.TEX_PROJ_PAYLOAD, payload)


def _validate_projection(projection: FaceUVProjection) -> None:
    if len(projection.transform) != 9 or not all(isfinite(value) for value in projection.transform):
        raise ValueError("UV projection transform must contain 9 finite values")
    if len(projection.origin) != 3 or not all(isfinite(value) for value in projection.origin):
        raise ValueError("UV projection origin must contain 3 finite values")
    for pin in projection.pins:
        values = (
            pin.texture_position.x,
            pin.texture_position.y,
            pin.model_position.x,
            pin.model_position.y,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("UV projection pins must contain finite values")


def _encode_edge_flags(flags: int) -> int:
    supported = EDGE_FLAG_HIDDEN | EDGE_FLAG_SOFT | EDGE_FLAG_SMOOTH
    unknown = flags & ~supported
    if unknown:
        raise ValueError(f"Edge flags contain unsupported bits: {unknown:#x}")
    encoded = 0
    if flags & EDGE_FLAG_HIDDEN:
        encoded |= _MODERN_ENTITY_HIDDEN
    if flags & EDGE_FLAG_SOFT:
        encoded |= _MODERN_EDGE_SOFT
    if flags & EDGE_FLAG_SMOOTH:
        encoded |= _MODERN_EDGE_SMOOTH
    return encoded


def _encode_width_prefixed_ids(entity_ids: Iterable[int], id_map: Mapping[int, int]) -> bytes:
    return _encode_mapped_width_prefixed_ids(id_map[entity_id] for entity_id in entity_ids)


def _encode_mapped_width_prefixed_ids(entity_ids: Iterable[int]) -> bytes:
    encoded = bytearray()
    for entity_id in entity_ids:
        value = encode_compact_int(entity_id)
        encoded.append(len(value))
        encoded.extend(value)
    return bytes(encoded)


def _validated_id_map(entities: Entities, supplied: Mapping[int, int] | None) -> Mapping[int, int]:
    source_ids = [vertex.id for vertex in entities.vertices]
    source_ids.extend(edge.id for edge in entities.edges)
    source_ids.extend(face.id for face in entities.faces)
    source_ids.extend(instance.id for instance in entities.component_instances)
    source_ids.extend(group.id for group in entities.groups)
    source_ids.extend(image.id for image in entities.images)
    source_ids.extend(curve.id for curve in entities.curves)
    source_ids.extend(arc.id for arc in entities.arc_curves)
    source_ids.extend(line.id for line in entities.guide_lines)
    source_ids.extend(point.id for point in entities.guide_points)
    source_ids.extend(plane.id for plane in entities.section_planes)
    source_ids.extend(text.id for text in entities.texts)
    source_ids.extend(dimension.id for dimension in entities.linear_dimensions)
    source_ids.extend(dimension.id for dimension in entities.radial_dimensions)
    if supplied is None:
        return {entity_id: entity_id for entity_id in source_ids}
    if any(entity_id not in supplied for entity_id in source_ids):
        raise ValueError("Entity ID map does not cover the complete geometry scope")
    mapped_ids = [supplied[entity_id] for entity_id in source_ids]
    if any(entity_id <= 0 for entity_id in mapped_ids):
        raise ValueError("Mapped entity IDs must be positive")
    if len(mapped_ids) != len(set(mapped_ids)):
        raise ValueError("Mapped entity IDs must be unique")
    return supplied


def _mapped_optional_id(
    source_id: int | None,
    id_map: Mapping[int, int] | None,
    kind: str,
) -> int | None:
    if source_id is None or id_map is None:
        return source_id
    try:
        return id_map[source_id]
    except KeyError as exc:
        raise ValueError(f"Missing {kind} ID mapping for {source_id}") from exc


def _validate_supported_scope(entities: Entities) -> None:
    unsupported = {
        "relationships": entities.relationships,
    }
    present = [name for name, values in unsupported.items() if values]
    if present:
        raise NotImplementedError("Modern entity writer does not support: " + ", ".join(present))

    supported_attribute_owners = {
        item.id
        for collection in (
            entities.vertices,
            entities.edges,
            entities.faces,
            entities.component_instances,
            entities.groups,
            entities.images,
            entities.curves,
            entities.arc_curves,
            entities.guide_points,
            entities.guide_lines,
            entities.section_planes,
            entities.texts,
            entities.linear_dimensions,
            entities.radial_dimensions,
        )
        for item in collection
    }
    unsupported_attribute_owners = set(entities.attribute_dictionaries_by_entity_id) - supported_attribute_owners
    if unsupported_attribute_owners:
        raise ValueError(f"Attribute dictionaries reference unknown entity IDs: {sorted(unsupported_attribute_owners)}")

    for edge in entities.edges:
        _validate_layer_reference(edge.layer_id, f"Edge {edge.id}")
    for face in entities.faces:
        _validate_layer_reference(face.layer_id, f"Face {face.id}")
    _validate_instance_data((*entities.component_instances, *entities.groups, *entities.images))
    _validate_construction_data(entities)


def _validate_instance_data(
    instances: Iterable[ComponentInstance | Group | Image],
) -> None:
    for instance in instances:
        _validate_layer_reference(instance.layer_id, f"Instance {instance.id}")
        if len(instance.transform) != 13 or not all(isfinite(value) for value in instance.transform):
            raise ValueError("Instance transform must contain 13 finite values")
        if len(instance.guid) != 16:
            raise ValueError("Instance GUID must contain 16 bytes")


def _validate_layer_reference(layer_id: int | None, owner: str) -> None:
    if layer_id is not None and layer_id <= 0:
        raise ValueError(f"{owner} has an invalid layer reference")


def _validate_construction_data(entities: Entities) -> None:
    for point in entities.guide_points:
        _validate_guide_point(point)
    for line in entities.guide_lines:
        _validate_guide_line(line)
    for plane in entities.section_planes:
        _validate_section_plane(plane)


def _validate_guide_point(point: GuidePoint) -> None:
    values = _vector3_values(point.position)
    if not all(isfinite(value) for value in values):
        raise ValueError(f"Guide point {point.id} has a non-finite position")
    if point.reference_point is not None and not all(
        isfinite(value) for value in _vector3_values(point.reference_point)
    ):
        raise ValueError(f"Guide point {point.id} has a non-finite reference")
    _validate_layer_reference(point.layer_id, f"Guide point {point.id}")


def _validate_guide_line(line: GuideLine) -> None:
    point = _vector3_values(line.point)
    direction = _vector3_values(line.direction)
    if not all(isfinite(value) for value in (*point, *direction)):
        raise ValueError(f"Guide line {line.id} has non-finite geometry")
    magnitude = sum(value * value for value in direction) ** 0.5
    if not isfinite(magnitude) or abs(magnitude - 1.0) > 1.0e-9:
        raise ValueError(f"Guide line {line.id} direction must be a unit vector")
    if not 0 <= line.stipple_pattern <= 0xFFFF:
        raise ValueError(f"Guide line {line.id} stipple must fit in u16")
    if (
        not isfinite(line.start_parameter)
        or not isfinite(line.end_parameter)
        or line.start_parameter >= line.end_parameter
    ):
        raise ValueError(f"Guide line {line.id} has invalid parameter bounds")
    _validate_layer_reference(line.layer_id, f"Guide line {line.id}")


def _validate_section_plane(plane: SectionPlane) -> None:
    if len(plane.plane) != 4 or not all(isfinite(value) for value in plane.plane):
        raise ValueError(f"Section plane {plane.id} has an invalid plane")
    if plane.plane[:3] == (0.0, 0.0, 0.0):
        raise ValueError(f"Section plane {plane.id} has a zero normal")
    _validate_layer_reference(plane.layer_id, f"Section plane {plane.id}")


def _validate_geometry(entities: Entities) -> None:
    _validate_entity_ids(entities)
    _validate_vertices(entities.vertices)
    edges_by_id = _validate_edges(entities.edges, entities.vertices)
    _validate_curves(entities, edges_by_id)
    _validate_faces(entities.faces, edges_by_id)


def _validate_entity_ids(entities: Entities) -> None:
    all_ids = [vertex.id for vertex in entities.vertices]
    all_ids.extend(edge.id for edge in entities.edges)
    all_ids.extend(face.id for face in entities.faces)
    all_ids.extend(instance.id for instance in entities.component_instances)
    all_ids.extend(group.id for group in entities.groups)
    all_ids.extend(image.id for image in entities.images)
    all_ids.extend(curve.id for curve in entities.curves)
    all_ids.extend(arc.id for arc in entities.arc_curves)
    all_ids.extend(line.id for line in entities.guide_lines)
    all_ids.extend(point.id for point in entities.guide_points)
    all_ids.extend(plane.id for plane in entities.section_planes)
    all_ids.extend(text.id for text in entities.texts)
    all_ids.extend(dimension.id for dimension in entities.linear_dimensions)
    all_ids.extend(dimension.id for dimension in entities.radial_dimensions)
    if any(entity_id <= 0 for entity_id in all_ids):
        raise ValueError("Geometry entity IDs must be positive")
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Geometry entity IDs must be unique within their scope")


def _validate_vertices(vertices: Iterable[Vertex]) -> None:
    for vertex in vertices:
        coordinates = (vertex.position.x, vertex.position.y, vertex.position.z)
        if not all(isfinite(value) for value in coordinates):
            raise ValueError(f"Vertex {vertex.id} has a non-finite position")


def _validate_edges(edges: Iterable[Edge], vertices: Iterable[Vertex]) -> dict[int, Edge]:
    vertex_ids = {vertex.id for vertex in vertices}
    edges_by_id = {edge.id: edge for edge in edges}
    for edge in edges_by_id.values():
        vertices_exist = edge.start_vertex_id in vertex_ids and edge.end_vertex_id in vertex_ids
        if not vertices_exist:
            raise ValueError(f"Edge {edge.id} references a missing vertex")
        if edge.start_vertex_id == edge.end_vertex_id:
            raise ValueError(f"Edge {edge.id} has identical endpoints")
    return edges_by_id


def _validate_curves(entities: Entities, edges_by_id: dict[int, Edge]) -> None:
    curves: list[Curve | ArcCurve] = [*entities.curves, *entities.arc_curves]
    curve_ids = {curve.id for curve in curves}
    for curve in curves:
        if not curve.edge_ids:
            raise ValueError(f"Curve {curve.id} must contain at least one edge")
        if len(curve.edge_ids) != len(set(curve.edge_ids)):
            raise ValueError(f"Curve {curve.id} contains duplicate edges")
        for edge_id in curve.edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is None:
                raise ValueError(f"Curve {curve.id} references missing edge {edge_id}")
            if edge.curve_id != curve.id:
                raise ValueError(f"Edge {edge_id} does not reference owning curve {curve.id}")
    for edge in edges_by_id.values():
        if edge.curve_id is not None and edge.curve_id not in curve_ids:
            raise ValueError(f"Edge {edge.id} references missing curve {edge.curve_id}")
    for arc in entities.arc_curves:
        _validate_arc_curve(arc)


def _validate_arc_curve(arc: ArcCurve) -> None:
    semantic = (arc.center, arc.normal, arc.radius, arc.start_angle, arc.end_angle)
    if all(value is None for value in semantic):
        if arc.raw_arc_payload is None or len(arc.raw_arc_payload) != 128:
            raise ValueError(f"Arc curve {arc.id} needs a 128-byte raw payload")
        return
    if any(value is None for value in semantic):
        raise ValueError(f"Arc curve {arc.id} has incomplete geometry")
    assert arc.center is not None and arc.normal is not None
    assert arc.radius is not None
    assert arc.start_angle is not None and arc.end_angle is not None
    values = (*arc.center, *arc.normal, arc.radius, arc.start_angle, arc.end_angle)
    if not all(isfinite(value) for value in values):
        raise ValueError(f"Arc curve {arc.id} has non-finite geometry")
    normal_length = sum(value * value for value in arc.normal) ** 0.5
    if abs(normal_length - 1.0) > 1.0e-9:
        raise ValueError(f"Arc curve {arc.id} normal must be a unit vector")
    if arc.radius <= 0.0 or arc.end_angle <= arc.start_angle:
        raise ValueError(f"Arc curve {arc.id} has invalid radius or angles")


def _validate_faces(faces: Iterable[Face], edges_by_id: dict[int, Edge]) -> None:
    for face in faces:
        if len(face.plane) != 4 or not all(isfinite(value) for value in face.plane):
            raise ValueError(f"Face {face.id} has an invalid plane")
        material_ids = (face.front_material_id, face.back_material_id)
        if any(value is not None and value <= 0 for value in material_ids):
            raise ValueError(f"Face {face.id} has an invalid material reference")
        loops = (face.outer_loop, *face.inner_loops)
        for loop in loops:
            if len(loop.edge_uses) < 3:
                raise ValueError(f"Face {face.id} has a loop with fewer than 3 edges")
            for edge_use in loop.edge_uses:
                if edge_use.edge_id not in edges_by_id:
                    raise ValueError(f"Face {face.id} references missing edge {edge_use.edge_id}")
            _validate_closed_loop(face.id, loop, edges_by_id)


def _validate_closed_loop(face_id: int, loop: Loop, edges_by_id: dict[int, Edge]) -> None:
    directed_edges = []
    for edge_use in loop.edge_uses:
        edge = edges_by_id[edge_use.edge_id]
        endpoints = (edge.start_vertex_id, edge.end_vertex_id)
        directed_edges.append(endpoints[::-1] if edge_use.reversed else endpoints)
    for current, following in zip(directed_edges, directed_edges[1:] + directed_edges[:1]):
        if current[1] != following[0]:
            raise ValueError(f"Face {face_id} contains a disconnected loop")
    (ArcCurve,)
