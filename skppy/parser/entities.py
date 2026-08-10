# SPDX-License-Identifier: MIT
"""
Parser for the entities section (tag 0x1388) of model.dat.

Produces populated Entities, Vertex, Edge, Face, Loop, EdgeUse,
ComponentInstance, Group, and Image objects.
"""

from __future__ import annotations

import struct
from typing import List, Optional

from ..data_structure.annotations import (
    ArcGeometry,
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
    EdgeUse,
    Entities,
    Face,
    FaceUVProjection,
    Group,
    Image,
    Loop,
    UVPin,
    Vertex,
)
from ..data_structure.primitives import Vector2D, Vector3D
from ..data_structure.model_metadata import AttributeDictionary
from .attributes import parse_attribute_dictionaries, parse_entity_attribute_dictionaries
from .tlv import (
    TlvTag,
    find_child,
    index_children,
    iter_records,
    read_bool,
    read_compact_int,
    read_f64_le,
    read_guid,
    read_transform13,
    read_utf8,
    read_vec3,
    read_vec4,
)

# Modern entity flags share one packed field across all drawing elements.
# Bits 1 and 2 are generic edge display state, not SketchUp soft/smooth flags.
# Normalize the format-specific bits here so callers see one representation.
_MODERN_ENTITY_HIDDEN = 0x01
_MODERN_ENTITY_CASTS_SHADOWS = 0x02
_MODERN_ENTITY_RECEIVES_SHADOWS = 0x04
_MODERN_EDGE_SOFT = 0x08
_MODERN_EDGE_SMOOTH = 0x10


def _normalize_modern_edge_flags(raw_flags: int) -> int:
    """Map packed modern drawing-element flags to public edge semantics."""
    flags = 0
    if raw_flags & _MODERN_ENTITY_HIDDEN:
        flags |= EDGE_FLAG_HIDDEN
    if raw_flags & _MODERN_EDGE_SOFT:
        flags |= EDGE_FLAG_SOFT
    if raw_flags & _MODERN_EDGE_SMOOTH:
        flags |= EDGE_FLAG_SMOOTH
    return flags


def _read_face_uv_projection(
    entity_base_payload: bytes, side_tag: int = TlvTag.TEX_PROJ_FRONT
) -> Optional[FaceUVProjection]:
    """
    Extract texture projection transform for the given side from entity_base.

    Path: entity_base -> id_wrapper (0x05DC) -> ext_payload (0x05DD)
          -> attr_dicts_root (0x36B1) -> attr_dict (0x36B2)
          -> tex_proj_pair (0x2710) -> tex_proj_front/back (0x2711/0x2712)
          -> tex_proj_payload (0x2713) -> transform (0x2715) + origin (0x2716)
             + optional control points (0x2717)

    Parameters
    ----------
    entity_base_payload : bytes
        Raw payload of the entity_base TLV record.
    side_tag : int, optional
        TlvTag.TEX_PROJ_FRONT (0x2711) or TlvTag.TEX_PROJ_BACK (0x2712).
        Defaults to TlvTag.TEX_PROJ_FRONT.

    Returns
    -------
    FaceUVProjection or None
        Parsed projection data, or None when absent or disabled.
    """
    projections = _read_face_uv_projections(entity_base_payload)
    return projections[0] if side_tag == TlvTag.TEX_PROJ_FRONT else projections[1]


def _read_face_uv_projections(
    entity_base_payload: bytes,
) -> tuple[Optional[FaceUVProjection], Optional[FaceUVProjection]]:
    """Read both face-side projections while traversing shared wrappers once."""
    id_wrapper = index_children(entity_base_payload).get(TlvTag.ID_WRAPPER)
    if not id_wrapper:
        return None, None
    ext_payload = index_children(id_wrapper).get(TlvTag.ID_EXT_PAYLOAD)
    if not ext_payload:
        return None, None
    attr_root = index_children(ext_payload).get(TlvTag.ATTR_DICTS_ROOT)
    if not attr_root:
        return None, None
    attr_dict = index_children(attr_root).get(TlvTag.ATTR_DICT_RECORD)
    if not attr_dict:
        return None, None
    tex_pair = index_children(attr_dict).get(TlvTag.TEX_PROJ_PAIR)
    if not tex_pair:
        return None, None
    sides = index_children(tex_pair)
    return (
        _read_face_uv_side(sides.get(TlvTag.TEX_PROJ_FRONT)),
        _read_face_uv_side(sides.get(TlvTag.TEX_PROJ_BACK)),
    )


def _read_face_uv_side(side: bytes | None) -> Optional[FaceUVProjection]:
    """Decode one face-side projection from an already selected side payload."""
    if not side:
        return None
    proj_payload = index_children(side).get(TlvTag.TEX_PROJ_PAYLOAD)
    if not proj_payload:
        return None

    projection_fields = index_children(proj_payload)
    enabled_p = projection_fields.get(TlvTag.TEX_PROJ_ENABLED)
    if not enabled_p or read_compact_int(enabled_p) == 0:
        return None

    transform_p = projection_fields.get(TlvTag.TEX_PROJ_TRANSFORM)
    origin_p = projection_fields.get(TlvTag.TEX_PROJ_ORIGIN)
    if not transform_p or len(transform_p) < 72:
        return None
    if not origin_p or len(origin_p) < 24:
        return None

    projection = FaceUVProjection()
    projection.transform = list(struct.unpack_from("<9d", transform_p))
    projection.origin = struct.unpack_from("<3d", origin_p)
    pins_payload = projection_fields.get(TlvTag.TEX_PROJ_PINS)
    if pins_payload:
        for tag, pin_payload in iter_records(pins_payload):
            if tag != TlvTag.TEX_PROJ_PIN:
                continue
            pin_fields = index_children(pin_payload)
            texture_payload = pin_fields.get(TlvTag.TEX_PROJ_PIN_TEXTURE_POSITION)
            model_payload = pin_fields.get(TlvTag.TEX_PROJ_PIN_MODEL_POSITION)
            if texture_payload is None or len(texture_payload) < 16 or model_payload is None or len(model_payload) < 16:
                continue
            pin = UVPin()
            pin.texture_position = Vector2D(*struct.unpack_from("<2d", texture_payload))
            pin.model_position = Vector2D(*struct.unpack_from("<2d", model_payload))
            projection.pins.append(pin)
    return projection


def parse_entities(payload: bytes) -> Entities:
    """
    Parse a 0x1388 entities payload and return an Entities object.

    Parameters
    ----------
    payload : bytes
        Raw payload bytes of a TlvTag.ENTITIES (0x1388) TLV record.

    Returns
    -------
    Entities
        Populated Entities object.  Any section absent in the payload
        yields an empty list in the corresponding attribute.
    """
    sections = index_children(payload)
    # Entities is the mutable public scope. Fill it as sections are decoded so
    # an omitted optional section naturally retains the shared empty default.
    entities = Entities()
    attributes: dict[int, list[AttributeDictionary]] = {}
    entities.vertices = _parse_vertices(sections.get(TlvTag.VERTICES, b""), attributes)
    entities.edges = _parse_edges(sections.get(TlvTag.EDGES, b""), attributes)
    entities.faces = _parse_faces(sections.get(TlvTag.FACES, b""), attributes)
    entities.component_instances = _parse_component_instances(sections.get(TlvTag.COMPONENT_INSTANCES, b""), attributes)
    entities.groups = _parse_groups(sections.get(TlvTag.GROUPS, b""))
    entities.images = _parse_images(sections.get(TlvTag.IMAGES, b""))
    entities.curves = _parse_curves(sections.get(TlvTag.CURVES, b""))
    entities.arc_curves = _parse_arc_curves(sections.get(TlvTag.ARC_CURVES, b""))
    _resolve_curve_edge_membership(entities)
    entities.guide_points = _parse_guide_points(sections.get(TlvTag.GUIDE_POINTS, b""))
    entities.guide_lines = _parse_guide_lines(sections.get(TlvTag.GUIDE_LINES, b""))
    entities.section_planes = _parse_section_planes(sections.get(TlvTag.SECTION_PLANES, b""))
    entities.texts = _parse_texts(sections.get(TlvTag.TEXTS, b""))
    entities.linear_dimensions = _parse_dimensions(sections.get(TlvTag.DIMENSIONS, b""))
    entities.radial_dimensions = _parse_radial_dimensions(sections.get(TlvTag.RADIAL_DIMENSIONS, b""))
    attributes.update(
        _parse_scoped_attribute_dictionaries(
            sections,
            excluded_sections={TlvTag.VERTICES, TlvTag.EDGES, TlvTag.FACES, TlvTag.COMPONENT_INSTANCES},
        )
    )
    entities.attribute_dictionaries_by_entity_id = attributes
    return entities


def _resolve_curve_edge_membership(entities: Entities) -> None:
    """Prefer explicit edge ownership over the curve record's ID span.

    SketchUp interleaves vertex, edge, and arc IDs. Consequently, the first and
    last IDs in a curve record are bounds rather than a contiguous membership
    list; each edge's ``curve_id`` is authoritative.
    """
    edge_ids_by_curve: dict[int, list[int]] = {}
    for edge in entities.edges:
        if edge.curve_id is not None:
            edge_ids_by_curve.setdefault(edge.curve_id, []).append(edge.id)
    curves: tuple[Curve | ArcCurve, ...] = (
        *entities.curves,
        *entities.arc_curves,
    )
    for curve in curves:
        if curve.id in edge_ids_by_curve:
            curve.edge_ids = edge_ids_by_curve[curve.id]


# -
# Entity-ID helper
# -


def _read_entity_id(entity_base_payload: bytes) -> int:
    return _read_entity_id_and_attributes(index_children(entity_base_payload), None)


def _read_entity_id_and_attributes(
    entity_fields: dict[int, bytes],
    attributes: dict[int, list[AttributeDictionary]] | None,
) -> int:
    """Decode identity and collect dictionaries from one indexed entity base."""
    id_wrapper = entity_fields.get(TlvTag.ID_WRAPPER)
    if not id_wrapper:
        return 0
    id_fields = index_children(id_wrapper)
    id_value = id_fields.get(TlvTag.ID_VALUE)
    entity_id = read_compact_int(id_value) if id_value else 0
    extended = id_fields.get(TlvTag.ID_EXT_PAYLOAD)
    if attributes is not None and entity_id > 0 and extended is not None:
        dictionaries = parse_attribute_dictionaries(extended)
        if dictionaries:
            attributes[entity_id] = dictionaries
    return entity_id


def _read_entity_layer_id(entity_base_payload: bytes) -> int | None:
    layer = find_child(entity_base_payload, TlvTag.ENTITY_LAYER_REF)
    return read_compact_int(layer) if layer is not None else None


def _parse_scoped_attribute_dictionaries(
    sections: dict[int, bytes],
    excluded_sections: set[int] | None = None,
) -> dict[int, list[AttributeDictionary]]:
    """Collect named dictionaries from every supported entity section."""
    dictionaries_by_entity_id: dict[int, list[AttributeDictionary]] = {}
    section_specs = (
        (TlvTag.VERTICES, TlvTag.VERTEX_RECORD, ()),
        (TlvTag.EDGES, TlvTag.EDGE_RECORD, (TlvTag.ENTITY_BASE,)),
        (TlvTag.FACES, TlvTag.FACE_RECORD, (TlvTag.ENTITY_BASE,)),
        (
            TlvTag.COMPONENT_INSTANCES,
            TlvTag.INSTANCE_RECORD,
            (TlvTag.ENTITY_BASE,),
        ),
        (
            TlvTag.GROUPS,
            TlvTag.GROUP_RECORD,
            (TlvTag.INSTANCE_RECORD, TlvTag.ENTITY_BASE),
        ),
        (
            TlvTag.IMAGES,
            TlvTag.IMAGE_RECORD,
            (TlvTag.INSTANCE_RECORD, TlvTag.ENTITY_BASE),
        ),
        (TlvTag.CURVES, TlvTag.CURVE_RECORD, ()),
        (
            TlvTag.ARC_CURVES,
            TlvTag.ARC_CURVE_RECORD,
            (TlvTag.CURVE_RECORD,),
        ),
        (
            TlvTag.GUIDE_POINTS,
            TlvTag.GUIDE_POINT_RECORD,
            (TlvTag.CONSTRUCTION_GEOMETRY_BASE, TlvTag.ENTITY_BASE),
        ),
        (
            TlvTag.GUIDE_LINES,
            TlvTag.GUIDE_LINE_RECORD,
            (TlvTag.CONSTRUCTION_GEOMETRY_BASE, TlvTag.ENTITY_BASE),
        ),
        (
            TlvTag.SECTION_PLANES,
            TlvTag.SECTION_PLANE_RECORD,
            (TlvTag.ENTITY_BASE,),
        ),
        (
            TlvTag.TEXTS,
            TlvTag.TEXT_RECORD,
            (TlvTag.ENTITY_BASE,),
        ),
        (
            TlvTag.DIMENSIONS,
            TlvTag.DIMENSION_RECORD,
            (TlvTag.DIMENSION_BASE, TlvTag.ENTITY_BASE),
        ),
        (
            TlvTag.RADIAL_DIMENSIONS,
            TlvTag.RADIAL_DIMENSION_RECORD,
            (TlvTag.DIMENSION_BASE, TlvTag.ENTITY_BASE),
        ),
    )
    for section_tag, record_tag, base_path in section_specs:
        if excluded_sections is not None and section_tag in excluded_sections:
            continue
        section = sections.get(section_tag)
        if section is None:
            continue
        for tag, record in iter_records(section):
            if tag != record_tag:
                continue
            entity_base = record
            for base_tag in base_path:
                nested = find_child(entity_base, base_tag)
                if nested is None:
                    entity_base = b""
                    break
                entity_base = nested
            if not entity_base:
                continue
            entity_id = _read_entity_id(entity_base)
            dictionaries = parse_entity_attribute_dictionaries(entity_base)
            if entity_id > 0 and dictionaries:
                dictionaries_by_entity_id[entity_id] = dictionaries
    return dictionaries_by_entity_id


# -
# Vertices
# -


def _parse_vertices(
    section_payload: bytes,
    attributes: dict[int, list[AttributeDictionary]] | None = None,
) -> List[Vertex]:
    vertices: List[Vertex] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.VERTEX_RECORD:
            continue
        # ID: 0x05DC -> 0x05DE
        fields = index_children(rec_p)
        vid = _read_entity_id_and_attributes(fields, attributes)

        pos_p = fields.get(TlvTag.VERTEX_POSITION)
        if pos_p and len(pos_p) >= 24:
            x, y, z = read_vec3(pos_p)
            vertices.append(Vertex(id=vid, position=Vector3D(x, y, z)))
    return vertices


# -
# Edges
# -


def _parse_edges(
    section_payload: bytes,
    attributes: dict[int, list[AttributeDictionary]] | None = None,
) -> List[Edge]:
    edges: List[Edge] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.EDGE_RECORD:
            continue
        # ID and flags live in entity base 0x07D0 -> 0x05DC -> 0x05DE
        eid = 0
        flags = 0
        fields = index_children(rec_p)
        eb = fields.get(TlvTag.ENTITY_BASE)
        if eb:
            entity_fields = index_children(eb)
            eid = _read_entity_id_and_attributes(entity_fields, attributes)
            flags_p = entity_fields.get(TlvTag.ENTITY_FLAGS)
            if flags_p:
                flags = read_compact_int(flags_p)
            layer_p = entity_fields.get(TlvTag.ENTITY_LAYER_REF)
            layer_id = read_compact_int(layer_p) if layer_p else None
        else:
            layer_id = None

        start_p = fields.get(TlvTag.EDGE_START_VERTEX)
        end_p = fields.get(TlvTag.EDGE_END_VERTEX)
        curve_p = fields.get(TlvTag.EDGE_CURVE_ID)

        edges.append(
            Edge(
                id=eid,
                start_vertex_id=read_compact_int(start_p) if start_p else 0,
                end_vertex_id=read_compact_int(end_p) if end_p else 0,
                flags=_normalize_modern_edge_flags(flags),
                curve_id=read_compact_int(curve_p) if curve_p else None,
                layer_id=layer_id,
            )
        )
    return edges


# -
# Faces
# -


def _face_base_values(
    entity_base: bytes | None,
    attributes: dict[int, list[AttributeDictionary]] | None = None,
) -> tuple[
    int,
    Optional[int],
    Optional[int],
    Optional[FaceUVProjection],
    Optional[FaceUVProjection],
]:
    """Decode face identity, front material, layer, and UV projections."""
    if entity_base is None:
        return 0, None, None, None, None
    fields = index_children(entity_base)
    front_material = fields.get(TlvTag.ENTITY_MATERIAL_REF)
    layer = fields.get(TlvTag.ENTITY_LAYER_REF)
    front_uv, back_uv = _read_face_uv_projections(entity_base)
    return (
        _read_entity_id_and_attributes(fields, attributes),
        read_compact_int(front_material) if front_material else None,
        read_compact_int(layer) if layer else None,
        front_uv,
        back_uv,
    )


def _face_back_material(extra_payload: bytes | None) -> int | None:
    """Decode the face-record-level back-material reference."""
    return read_compact_int(extra_payload) if extra_payload is not None else None


def _face_loops(payload: bytes | None) -> tuple[Loop, List[Loop]]:
    """Return a marked outer loop and any remaining inner loops."""
    if payload is None:
        return Loop([], is_outer=True), []
    loops = _parse_loops(payload)
    if not loops:
        return Loop([], is_outer=True), []
    outer_loop = loops[0]
    outer_loop.is_outer = True
    return outer_loop, loops[1:]


def _parse_faces(
    section_payload: bytes,
    attributes: dict[int, list[AttributeDictionary]] | None = None,
) -> List[Face]:
    faces: List[Face] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.FACE_RECORD:
            continue
        fields = index_children(rec_p)
        fid, front_material_id, layer_id, front_uv, back_uv = _face_base_values(
            fields.get(TlvTag.ENTITY_BASE), attributes
        )
        # 0x0DAF is the back-material reference. The adjacent entity-base
        # 0x07D2 field belongs to the drawing element's layer instead.
        back_material_id = _face_back_material(fields.get(TlvTag.FACE_EXTRA_FLAG))
        plane_p = fields.get(TlvTag.FACE_PLANE)
        plane = read_vec4(plane_p) if plane_p and len(plane_p) >= 32 else (0.0, 0.0, 1.0, 0.0)
        outer_loop, inner_loops = _face_loops(fields.get(TlvTag.FACE_LOOPS))
        # Face topology is atomic: publishing a partially decoded loop would
        # create invalid references in every downstream mesh conversion.
        faces.append(
            Face(
                id=fid,
                plane=plane,
                outer_loop=outer_loop,
                inner_loops=inner_loops,
                front_material_id=front_material_id,
                back_material_id=back_material_id,
                front_uv=front_uv,
                back_uv=back_uv,
                layer_id=layer_id,
            )
        )
    return faces


def _parse_loops(loops_payload: bytes) -> List[Loop]:
    loops: List[Loop] = []
    for tag, loop_p in iter_records(loops_payload):
        if tag != TlvTag.LOOP_RECORD:
            continue
        edge_uses_p = index_children(loop_p).get(TlvTag.EDGE_USES)
        if not edge_uses_p:
            loops.append(Loop([]))
            continue
        edge_uses: List[EdgeUse] = []
        for eu_tag, eu_p in iter_records(edge_uses_p):
            if eu_tag != TlvTag.EDGE_USE:
                continue
            fields = index_children(eu_p)
            eid_p = fields.get(TlvTag.EDGE_USE_ID)
            erev_p = fields.get(TlvTag.EDGE_USE_REVERSED)
            edge_uses.append(
                EdgeUse(
                    edge_id=read_compact_int(eid_p) if eid_p else 0,
                    reversed=read_bool(erev_p) if erev_p is not None else False,
                )
            )
        loops.append(Loop(edge_uses))
    return loops


# -
# Component instances / groups / images
# -


def _populate_instance_record(
    instance: ComponentInstance | Group | Image,
    payload_1964: bytes,
    attributes: dict[int, list[AttributeDictionary]] | None = None,
) -> None:
    """Apply a shared instance record to any instance-like public entity."""
    fields = index_children(payload_1964)
    eb = fields.get(TlvTag.ENTITY_BASE)
    if eb:
        entity_fields = index_children(eb)
        instance.id = _read_entity_id_and_attributes(entity_fields, attributes)
        mat_ref_p = entity_fields.get(TlvTag.ENTITY_MATERIAL_REF)
        if mat_ref_p:
            instance.material_id = read_compact_int(mat_ref_p)
        layer_ref_p = entity_fields.get(TlvTag.ENTITY_LAYER_REF)
        if layer_ref_p:
            instance.layer_id = read_compact_int(layer_ref_p)

    name_p = fields.get(TlvTag.INSTANCE_NAME)
    if name_p:
        instance.name = read_utf8(name_p)

    xform_p = fields.get(TlvTag.INSTANCE_TRANSFORM)
    if xform_p and len(xform_p) >= 104:
        instance.transform = read_transform13(xform_p)

    def_id_p = fields.get(TlvTag.INSTANCE_DEF_ID)
    if def_id_p:
        instance.definition_id = read_compact_int(def_id_p)

    guid_p = fields.get(TlvTag.INSTANCE_GUID)
    if guid_p:
        instance.guid = read_guid(guid_p)


def _parse_component_instances(
    section_payload: bytes,
    attributes: dict[int, list[AttributeDictionary]] | None = None,
) -> List[ComponentInstance]:
    instances: List[ComponentInstance] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.INSTANCE_RECORD:
            continue
        instance = ComponentInstance()
        _populate_instance_record(instance, rec_p, attributes)
        instances.append(instance)
    return instances


def _parse_groups(section_payload: bytes) -> List[Group]:
    groups: List[Group] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.GROUP_RECORD:
            continue
        inst_p = find_child(rec_p, TlvTag.INSTANCE_RECORD)
        if not inst_p:
            continue
        group = Group()
        _populate_instance_record(group, inst_p)
        groups.append(group)
    return groups


def _parse_images(section_payload: bytes) -> List[Image]:
    images: List[Image] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.IMAGE_RECORD:
            continue
        inst_p = find_child(rec_p, TlvTag.INSTANCE_RECORD)
        if not inst_p:
            continue
        image = Image()
        _populate_instance_record(image, inst_p)
        images.append(image)
    return images


def _parse_curves(section_payload: bytes) -> List[Curve]:
    """
    Parse the TlvTag.CURVES (0x1396) section.

    Parameters
    ----------
    section_payload : bytes
        Raw payload of the 0x1396 curves-section TLV record.

    Returns
    -------
    list[Curve]
        One Curve per 0x1399 curve record.  Records missing first or
        last edge ID tags are silently skipped.
    """
    curves: List[Curve] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.CURVE_RECORD:
            continue
        curve = Curve()
        curve.id = _read_entity_id(rec_p)
        count_p = find_child(rec_p, TlvTag.CURVE_EDGE_COUNT)
        first_p = find_child(rec_p, TlvTag.CURVE_FIRST_EDGE_ID)
        last_p = find_child(rec_p, TlvTag.CURVE_LAST_EDGE_ID)

        if count_p:
            num_edges = read_compact_int(count_p)
            first_id = read_compact_int(first_p) if first_p else 0
            curve.edge_ids = list(range(first_id, first_id + num_edges))
        elif first_p and last_p:
            first_id = read_compact_int(first_p)
            last_id = read_compact_int(last_p)
            curve.edge_ids = list(range(first_id, last_id + 1))
        else:
            continue

        poly_p = find_child(rec_p, TlvTag.CURVE_POLYGON_FLAG)
        if poly_p:
            curve.is_polygon = bool(read_compact_int(poly_p))
        curves.append(curve)
    return curves


def _parse_arc_curves(section_payload: bytes) -> List[ArcCurve]:
    """
    Parse the TlvTag.ARC_CURVES (0x1397) section.

    Parameters
    ----------
    section_payload : bytes
        Raw payload of the 0x1397 arc-curves-section TLV record.

    Returns
    -------
    list[ArcCurve]
        One ArcCurve per 0x139A arc-curve record.  Records missing the
        embedded curve sub-record are silently skipped.

    Notes
    -----
    Each arc-curve record embeds a regular curve record (providing edge IDs)
    and adds an arc-specific payload (0x139B) whose internal format is not yet
    fully mapped.  The raw bytes are preserved in ArcCurve.raw_arc_payload.
    """
    arc_curves: List[ArcCurve] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.ARC_CURVE_RECORD:
            continue
        # The embedded curve record gives us the ID and edge IDs.
        curve_rec_p = find_child(rec_p, TlvTag.CURVE_RECORD)
        if curve_rec_p is None:
            continue
        arc = ArcCurve()
        arc.id = _read_entity_id(curve_rec_p)
        count_p = find_child(curve_rec_p, TlvTag.CURVE_EDGE_COUNT)
        first_p = find_child(curve_rec_p, TlvTag.CURVE_FIRST_EDGE_ID)
        last_p = find_child(curve_rec_p, TlvTag.CURVE_LAST_EDGE_ID)
        if count_p:
            num_edges = read_compact_int(count_p)
            first_id = read_compact_int(first_p) if first_p else 0
            arc.edge_ids = list(range(first_id, first_id + num_edges))
        elif first_p and last_p:
            arc.edge_ids = list(range(read_compact_int(first_p), read_compact_int(last_p) + 1))

        arc.raw_arc_payload = find_child(rec_p, TlvTag.ARC_SPECIFIC_PAYLOAD)
        arc_curves.append(arc)
    return arc_curves


# -
# Guide points
# -


def _parse_guide_points(section_payload: bytes) -> List[GuidePoint]:
    """
    Parse the guide-points section.

    Each ``0x426C`` record contains an entity base, its position, an optional
    reference position, and a boolean that enables the segment between them.

    Parameters
    ----------
    section_payload : bytes
        Raw payload of the section that actually contains guide points.

    Returns
    -------
    list[GuidePoint]
        One GuidePoint per ``0x426C`` record found.
    """
    guide_points: List[GuidePoint] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.GUIDE_POINT_RECORD:
            continue
        point = GuidePoint()
        # Modern readers historically expose construction vectors as tuples,
        # including the zero fallback used by an incomplete record.
        point.position = Vector3D(0.0, 0.0, 0.0).to_tuple()
        base_p = find_child(rec_p, TlvTag.CONSTRUCTION_GEOMETRY_BASE)
        if base_p:
            entity_base = find_child(base_p, TlvTag.ENTITY_BASE)
            point.id = _read_entity_id(entity_base or base_p)
            if entity_base is not None:
                point.layer_id = _read_entity_layer_id(entity_base)
        pos_p = find_child(rec_p, TlvTag.GUIDE_POINT_POSITION)
        if pos_p and len(pos_p) >= 24:
            point.position = Vector3D(*read_vec3(pos_p)).to_tuple()
        reference_p = find_child(rec_p, TlvTag.GUIDE_POINT_REFERENCE_POSITION)
        has_reference_p = find_child(rec_p, TlvTag.GUIDE_POINT_HAS_REFERENCE_POSITION)
        if reference_p and len(reference_p) >= 24 and has_reference_p and read_compact_int(has_reference_p):
            point.reference_point = Vector3D(*read_vec3(reference_p)).to_tuple()
        guide_points.append(point)
    return guide_points


# -
# Guide lines
# -


def _parse_guide_lines(section_payload: bytes) -> List[GuideLine]:
    """
    Parse the guide-lines section.

    Each ``0x4269`` record contains an entity base, a ``CLine3d`` geometry
    field, and its 16-bit stipple pattern.

    Parameters
    ----------
    section_payload : bytes
        Raw payload of the section that actually contains guide lines.

    Returns
    -------
    list[GuideLine]
        One GuideLine per ``0x4269`` record found.
    """
    guide_lines: List[GuideLine] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.GUIDE_LINE_RECORD:
            continue
        line = GuideLine()
        # A missing CLine3d has no meaningful direction. Do not inherit the
        # public new-object default, which represents a valid X-axis line.
        line.point = Vector3D(0.0, 0.0, 0.0).to_tuple()
        line.direction = Vector3D(0.0, 0.0, 0.0).to_tuple()
        base_p = find_child(rec_p, TlvTag.CONSTRUCTION_GEOMETRY_BASE)
        if base_p:
            entity_base = find_child(base_p, TlvTag.ENTITY_BASE)
            line.id = _read_entity_id(entity_base or base_p)
            if entity_base is not None:
                line.layer_id = _read_entity_layer_id(entity_base)
        # The line geometry is a single 0x426A field carrying 6+ doubles:
        #   [0:3] = a point on the line
        #   [3:6] = unit direction vector
        #   [6:]  = trailing scalars (finite-line length / extent)
        geom_p = find_child(rec_p, TlvTag.GUIDE_LINE_GEOMETRY)
        if geom_p and len(geom_p) >= 48:
            vals = struct.unpack_from("<6d", geom_p)
            line.point = Vector3D(vals[0], vals[1], vals[2]).to_tuple()
            line.direction = Vector3D(vals[3], vals[4], vals[5]).to_tuple()
            if len(geom_p) >= 64:
                line.start_parameter, line.end_parameter = struct.unpack_from("<2d", geom_p, 48)
        stipple_p = find_child(rec_p, TlvTag.GUIDE_LINE_STIPPLE)
        if stipple_p:
            line.stipple_pattern = read_compact_int(stipple_p)
        guide_lines.append(line)
    return guide_lines


# -
# Section planes
# -


def _parse_section_planes(section_payload: bytes) -> List[SectionPlane]:
    """
    Parse the TlvTag.SECTION_PLANES (0x1393) section.

    Each section plane record (0x445C) contains a plane equation (0x445D),
    a name (0x445E), and a symbol string (0x445F).

    Parameters
    ----------
    section_payload : bytes
        Raw payload of the 0x1393 section-planes-section TLV record.

    Returns
    -------
    list[SectionPlane]
        One SectionPlane per 0x445C record found.
    """
    section_planes: List[SectionPlane] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.SECTION_PLANE_RECORD:
            continue
        plane = SectionPlane()
        eb = find_child(rec_p, TlvTag.ENTITY_BASE)
        if eb:
            plane.id = _read_entity_id(eb)
            plane.layer_id = _read_entity_layer_id(eb)
        plane_p = find_child(rec_p, TlvTag.SECTION_PLANE_PLANE)
        if plane_p and len(plane_p) >= 32:
            plane.plane = read_vec4(plane_p)
        name_p = find_child(rec_p, TlvTag.SECTION_PLANE_NAME)
        if name_p:
            plane.name = read_utf8(name_p)
        symbol_p = find_child(rec_p, TlvTag.SECTION_PLANE_SYMBOL)
        if symbol_p:
            plane.symbol = read_utf8(symbol_p)
        section_planes.append(plane)
    return section_planes


# -
# Dimensions
# -


def _parse_dimension_anchor(payload: bytes) -> PointReference:
    """Read the public portion of a modern point-reference record."""
    reference = PointReference()
    point_ref = find_child(payload, TlvTag.POINT_REFERENCE) or payload
    enabled_p = find_child(point_ref, TlvTag.DIMENSION_ANCHOR_ENABLED)
    point_p = find_child(point_ref, TlvTag.DIMENSION_ANCHOR_POINT)
    if enabled_p is not None and not read_bool(enabled_p):
        return reference
    if enabled_p is not None:
        reference.kind = read_compact_int(enabled_p)
    if point_p is not None and len(point_p) >= 24:
        reference.position = Vector3D(*read_vec3(point_p))
    reference.entity_id, reference.instance_path_ids = _parse_point_reference_style(
        find_child(point_ref, TlvTag.DIMENSION_ANCHOR_STYLE_A)
    )
    (
        reference.secondary_entity_id,
        reference.secondary_instance_path_ids,
    ) = _parse_point_reference_style(find_child(point_ref, TlvTag.DIMENSION_ANCHOR_STYLE_B))
    return reference


def _parse_point_reference_style(payload: bytes | None) -> tuple[int | None, list[int]]:
    if payload is None:
        return None, []
    wrapper = find_child(payload, TlvTag.DIMENSION_ANCHOR_STYLE_WRAPPER) or payload
    entity_p = find_child(wrapper, TlvTag.DIMENSION_ANCHOR_STYLE_ENTITY)
    path_p = find_child(wrapper, TlvTag.DIMENSION_ANCHOR_STYLE_VALUE)
    return (
        read_compact_int(entity_p) if entity_p is not None else None,
        _read_width_prefixed_ids(path_p or b""),
    )


def _read_width_prefixed_ids(payload: bytes) -> list[int]:
    ids: list[int] = []
    offset = 0
    while offset < len(payload):
        width = payload[offset]
        offset += 1
        if not 1 <= width <= 4:
            raise ValueError(f"Entity path ID width must be 1-4 bytes, got {width}")
        end = offset + width
        if end > len(payload):
            raise ValueError("Truncated entity path ID sequence")
        ids.append(int.from_bytes(payload[offset:end], "little"))
        offset = end
    return ids


def _parse_texts(section_payload: bytes) -> List[Text]:
    """Parse modern text annotation records."""
    texts: List[Text] = []
    for tag, payload in iter_records(section_payload):
        if tag != TlvTag.TEXT_RECORD:
            continue
        fields = index_children(payload)
        text = Text()
        entity_base = fields.get(TlvTag.ENTITY_BASE)
        if entity_base is not None:
            text.id = _read_entity_id(entity_base)
            text.drawing.layer_id = _read_entity_layer_id(entity_base)
            base_fields = index_children(entity_base)
            material = base_fields.get(TlvTag.ENTITY_MATERIAL_REF)
            if material is not None:
                text.drawing.material_id = read_compact_int(material)
            flags = base_fields.get(TlvTag.ENTITY_FLAGS)
            if flags is not None:
                raw_flags = read_compact_int(flags)
                text.drawing.hidden = bool(raw_flags & _MODERN_ENTITY_HIDDEN)
                text.drawing.casts_shadows = bool(raw_flags & _MODERN_ENTITY_CASTS_SHADOWS)
                text.drawing.receives_shadows = bool(raw_flags & _MODERN_ENTITY_RECEIVES_SHADOWS)
        scalar_fields = (
            (TlvTag.TEXT_VALUE, "text", read_utf8),
            (TlvTag.TEXT_FONT_REF, "font_id", read_compact_int),
            (TlvTag.TEXT_LINE_WEIGHT, "line_weight", read_compact_int),
            (TlvTag.TEXT_LEADER_TYPE, "leader_type", read_compact_int),
            (TlvTag.TEXT_ARROW_TYPE, "arrow_type", read_compact_int),
            (
                TlvTag.TEXT_HIDDEN_LEADER_DIRECTION,
                "hidden_leader_direction",
                read_compact_int,
            ),
            (TlvTag.TEXT_ANCHOR_IN_FRONT, "anchor_in_front", read_bool),
            (TlvTag.TEXT_HIDE_OUT_OF_PLANE, "hide_out_of_plane", read_bool),
            (TlvTag.TEXT_DISPLAY_LEADER, "display_leader", read_bool),
        )
        for field_tag, name, decoder in scalar_fields:
            value = fields.get(field_tag)
            if value is not None:
                setattr(text, name, decoder(value))
        screen_x = fields.get(TlvTag.TEXT_SCREEN_X)
        screen_y = fields.get(TlvTag.TEXT_SCREEN_Y)
        text.screen_position = Vector2D(
            read_f64_le(screen_x) if screen_x is not None else 0.0,
            read_f64_le(screen_y) if screen_y is not None else 0.0,
        )
        anchor = fields.get(TlvTag.TEXT_ANCHOR)
        if anchor is not None:
            text.anchor = _parse_dimension_anchor(anchor)
        text.leader_vector = _dimension_vector(payload, TlvTag.TEXT_LEADER_VECTOR, (0.0, 0.0, 0.0))
        text.view_direction = _dimension_vector(payload, TlvTag.TEXT_VIEW_DIRECTION, (0.0, 0.0, 1.0))
        texts.append(text)
    return texts


def _dimension_scalar(payload: bytes, tag: TlvTag) -> float:
    value = find_child(payload, tag)
    return read_f64_le(value) if value is not None and len(value) >= 8 else 0.0


def _dimension_vector(
    payload: bytes,
    tag: TlvTag,
    default: tuple[float, float, float],
) -> Vector3D:
    value = find_child(payload, tag)
    return Vector3D(*read_vec3(value)) if value is not None and len(value) >= 24 else Vector3D(*default)


def _apply_dimension_common(dimension: Dimension, payload: bytes) -> None:
    """Decode text presentation shared by modern dimension records."""
    fields = index_children(payload) if payload else {}
    optional_fields = (
        (TlvTag.DIMENSION_TEXT, "text", read_utf8),
        (TlvTag.DIMENSION_FONT_REF, "font_id", read_compact_int),
        (TlvTag.DIMENSION_3D_TEXT, "is_3d_text", read_bool),
        (TlvTag.DIMENSION_ARROW_TYPE, "arrow_type", read_compact_int),
    )
    for tag, field, decoder in optional_fields:
        value = fields.get(tag)
        if value is not None:
            setattr(dimension, field, decoder(value))


def _apply_dimension_entity_base(dimension: Dimension, entity_base: bytes | None) -> None:
    """Decode entity identity and drawing state when the base is present."""
    if entity_base is None:
        return
    dimension.id = _read_entity_id(entity_base)
    fields = index_children(entity_base)
    material = fields.get(TlvTag.ENTITY_MATERIAL_REF)
    if material is not None:
        dimension.drawing.material_id = read_compact_int(material)
    dimension.drawing.layer_id = _read_entity_layer_id(entity_base)
    flags = fields.get(TlvTag.ENTITY_FLAGS)
    if flags is not None:
        raw_flags = read_compact_int(flags)
        dimension.drawing.hidden = bool(raw_flags & _MODERN_ENTITY_HIDDEN)
        dimension.drawing.casts_shadows = bool(raw_flags & _MODERN_ENTITY_CASTS_SHADOWS)
        dimension.drawing.receives_shadows = bool(raw_flags & _MODERN_ENTITY_RECEIVES_SHADOWS)


def _apply_dimension_geometry(dimension: LinearDimension, payload: bytes) -> None:
    """Decode anchors, directions, placement, and alignment."""
    dimension.start = _parse_dimension_anchor(find_child(payload, TlvTag.DIMENSION_ANCHOR_A) or b"")
    dimension.end = _parse_dimension_anchor(find_child(payload, TlvTag.DIMENSION_ANCHOR_B) or b"")
    dimension.direction = _dimension_vector(payload, TlvTag.DIMENSION_DIRECTION, (0.0, 0.0, 1.0))
    dimension.render_direction = _dimension_vector(payload, TlvTag.DIMENSION_RENDER_DIR, (1.0, 0.0, 0.0))
    mode = find_child(payload, TlvTag.DIMENSION_MODE)
    if mode is not None:
        dimension.mode = read_compact_int(mode)
    dimension.offset = _dimension_scalar(payload, TlvTag.DIMENSION_OFFSET)
    dimension.line_position = _dimension_scalar(payload, TlvTag.DIMENSION_LINE_POS)
    alignment = find_child(payload, TlvTag.DIMENSION_ALIGNMENT)
    if alignment is not None:
        dimension.alignment = read_compact_int(alignment)


def _parse_dimensions(section_payload: bytes) -> List[LinearDimension]:
    """Parse modern linear dimensions into the shared annotation model."""
    dimensions: List[LinearDimension] = []
    for tag, rec_p in iter_records(section_payload):
        if tag != TlvTag.DIMENSION_RECORD:
            continue

        dimension = LinearDimension()
        common = find_child(rec_p, TlvTag.DIMENSION_BASE) or b""
        _apply_dimension_common(dimension, common)
        _apply_dimension_entity_base(
            dimension,
            find_child(common, TlvTag.ENTITY_BASE) or find_child(rec_p, TlvTag.ENTITY_BASE),
        )
        _apply_dimension_geometry(dimension, rec_p)
        dimensions.append(dimension)
    return dimensions


def _parse_radial_dimensions(section_payload: bytes) -> List[RadialDimension]:
    """Parse modern radial dimensions and their optional inline arcs."""
    dimensions: List[RadialDimension] = []
    for tag, payload in iter_records(section_payload):
        if tag != TlvTag.RADIAL_DIMENSION_RECORD:
            continue
        dimension = RadialDimension()
        common = find_child(payload, TlvTag.DIMENSION_BASE) or b""
        _apply_dimension_common(dimension, common)
        _apply_dimension_entity_base(dimension, find_child(common, TlvTag.ENTITY_BASE))
        fields = index_children(payload)
        target = fields.get(TlvTag.RADIAL_DIMENSION_TARGET_REF)
        if target is not None:
            dimension.target_entity_id = read_compact_int(target)
        parameter = fields.get(TlvTag.RADIAL_DIMENSION_PARAMETER)
        if parameter is not None:
            dimension.parameter = read_f64_le(parameter)
        ratio = fields.get(TlvTag.RADIAL_DIMENSION_RADIUS_RATIO)
        if ratio is not None:
            dimension.radius_ratio = read_f64_le(ratio)
        diameter = fields.get(TlvTag.RADIAL_DIMENSION_IS_DIAMETER)
        if diameter is not None:
            dimension.is_diameter = read_bool(diameter)
        arc = fields.get(TlvTag.RADIAL_DIMENSION_ARC)
        if arc is not None and len(arc) >= 88:
            values = struct.unpack_from("<11d", arc)
            y_axis = Vector3D(*struct.unpack_from("<3d", arc, 88)) if len(arc) >= 112 else None
            dimension.arc = ArcGeometry(
                center=Vector3D(*values[0:3]),
                normal=Vector3D(*values[3:6]),
                x_axis=Vector3D(*values[6:9]),
                start_angle=values[9],
                end_angle=values[10],
                y_axis=y_axis,
            )
        dimensions.append(dimension)
    return dimensions
