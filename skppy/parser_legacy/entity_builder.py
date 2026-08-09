# SPDX-License-Identifier: MIT
"""Finalize legacy archive entities into the shared entity graph."""

from __future__ import annotations

from collections.abc import Mapping

from ..data_structure.annotations import (
    ArcGeometry,
    Dimension,
    DrawingElementProperties,
    LinearDimension,
    PointReference,
    RadialDimension,
    Text,
)
from ..data_structure.construction import GuideLine, GuidePoint, SectionPlane
from ..data_structure.entities import (
    ArcCurve,
    ComponentDefinition,
    ComponentInstance,
    Curve,
    Edge,
    Entities,
    Face,
    Group,
    Image,
    Vertex,
)
from ..data_structure.model import Model
from ..data_structure.model_metadata import EntityRelationship
from ..data_structure.primitives import Vector2D, Vector3D

from .parser_types import (
    DimensionLinearPayload,
    DimensionPayload,
    DimensionRadialPayload,
    DrawingElementState,
    EdgeState,
    PointRefPayload,
    RelationshipCollection,
    SupportedObjectPayload,
    TextPayload,
)
from .attribute_builder import attribute_dictionaries_by_owner_id
from .material_builder import material_ids_by_archive_index
from .provenance import ArchiveProvenance


def populate_root_entities(
    model: Model,
    provenance: ArchiveProvenance,
    *,
    definition_by_object_index: dict[int, ComponentDefinition] | None = None,
    material_id_by_object_index: dict[int, int] | None = None,
    archive_indices_by_identity: dict[int, tuple[int, ...]] | None = None,
    objects_by_archive_index: Mapping[int, SupportedObjectPayload] | None = None,
) -> None:
    """Populate root entities, including nonduplicated archive edge payloads."""
    root_payloads = provenance.root_objects
    # Edges reached recursively from faces/curves are absent from the root list.
    # Add only those distinct objects; comparing identity avoids duplicating an
    # edge whose technical state appears in both collections.
    referenced_edges = tuple(
        value for value in provenance.root_edge_previews if all(value is not root_value for root_value in root_payloads)
    )
    populate_entities(
        model.entities,
        (*root_payloads, *referenced_edges),
        definition_by_object_index=definition_by_object_index,
        curve_by_object_index=curve_payloads_by_archive_index(provenance),
        material_id_by_object_index=(
            material_id_by_object_index
            if material_id_by_object_index is not None
            else material_ids_by_archive_index(model, provenance)
        ),
        layer_id_by_object_index={
            state.object_tag.index: state.layer.id
            for state in provenance.archived_layers
            if state.object_tag.index is not None
        },
        relationships=provenance.root_relationships,
        archive_objects=provenance.archive_objects,
        archive_indices_by_identity=archive_indices_by_identity,
        objects_by_archive_index=objects_by_archive_index,
        attribute_container_indices_by_owner=(provenance.attribute_container_indices_by_owner),
    )


def populate_entities(
    entities: Entities,
    payloads: tuple[SupportedObjectPayload, ...],
    definition_by_object_index: dict[int, ComponentDefinition] | None = None,
    material_id_by_object_index: dict[int, int] | None = None,
    curve_by_object_index: dict[int, Curve | ArcCurve] | None = None,
    layer_id_by_object_index: dict[int, int] | None = None,
    relationships: RelationshipCollection = (),
    archive_objects: tuple[tuple[int, SupportedObjectPayload], ...] = (),
    archive_indices_by_identity: dict[int, tuple[int, ...]] | None = None,
    objects_by_archive_index: Mapping[int, SupportedObjectPayload] | None = None,
    attribute_container_indices_by_owner: tuple[tuple[int, int], ...] = (),
) -> None:
    """Resolve archive IDs and append shared objects to an entity collection."""
    definitions = definition_by_object_index or {}
    materials = material_id_by_object_index or {}
    archived_curves = curve_by_object_index or {}
    layers = layer_id_by_object_index or {}
    edge_id_by_archive_index: dict[int, int] = {}
    edge_ids_by_curve: dict[int, list[int]] = {}
    curves: dict[int, Curve | ArcCurve] = {}
    converted_entity_ids: dict[int, int] = {}
    # Faces and curves refer to archive object indices, while the public graph
    # uses newly allocated entity IDs. Build the translation map from edges
    # before touching any dependent topology.
    edge_payloads = tuple(value for value in payloads if isinstance(value, EdgeState))

    # Legacy edges embed/reference Vertex objects independently. Equal positions
    # represent one public vertex in an entities scope, matching SketchUp's
    # welded topology rather than the temporary archive object identity.
    vertex_by_position: dict[tuple[float, float, float], int] = {}
    for archived_edge in edge_payloads:
        edge = _add_edge(entities, archived_edge, vertex_by_position, layers)
        if archived_edge.object_index is not None:
            edge_id_by_archive_index[archived_edge.object_index] = edge.id
        curve = archived_edge.curve
        if curve is None and archived_edge.curve_tag is not None:
            curve = archived_curves.get(archived_edge.curve_tag.index or 0)
        if curve is not None:
            # Resolved references return the same Python object. Identity is a
            # stable key even before the curve receives its final entity ID.
            curve_key = id(curve)
            curves[curve_key] = curve
            edge_ids_by_curve.setdefault(curve_key, []).append(edge.id)
    _add_curves(entities, curves, edge_ids_by_curve)

    # With edge and curve IDs finalized, dependent loops can now be translated.
    for face in (value for value in payloads if isinstance(value, Face)):
        _add_face(entities, face, edge_id_by_archive_index, materials, layers)

    _add_placements_and_construction(
        entities,
        payloads,
        definitions,
        materials,
        layers,
    )

    # Annotation point references can target edges read earlier in the same
    # scope. Convert them only after topology IDs have reached their final form.
    converted_entity_ids = _add_annotations(
        entities,
        payloads,
        edge_id_by_archive_index,
        materials,
        layers,
    )

    # Relationship records are serialized after their entities. Resolve them
    # only now, when archive object identities can be translated to stable IDs.
    entity_ids = _entity_ids_by_archive_index(
        entities,
        payloads,
        archive_indices_by_identity=(
            archive_indices_by_identity
            if archive_indices_by_identity is not None
            else index_archive_object_identities(archive_objects)
        ),
        converted_entity_ids=converted_entity_ids,
    )
    _append_relationships(entities, relationships, entity_ids)
    _append_entity_attribute_dictionaries(
        entities,
        attribute_container_indices_by_owner,
        archive_objects,
        entity_ids,
        objects_by_archive_index=objects_by_archive_index,
    )


def _add_placements_and_construction(
    entities: Entities,
    payloads: tuple[SupportedObjectPayload, ...],
    definitions: dict[int, ComponentDefinition],
    materials: dict[int, int],
    layers: dict[int, int],
) -> None:
    """Append placements and construction entities after topology is stable."""
    for payload in payloads:
        if isinstance(payload, (ComponentInstance, Group, Image)):
            _add_instance(entities, payload, definitions, materials, layers)
        elif isinstance(payload, GuidePoint):
            _resolve_construction_layer(payload, layers)
            payload.id = entities._alloc_id()
            entities.guide_points.append(payload)
        elif isinstance(payload, GuideLine):
            _resolve_construction_layer(payload, layers)
            payload.id = entities._alloc_id()
            entities.guide_lines.append(payload)
        elif isinstance(payload, SectionPlane):
            _resolve_construction_layer(payload, layers)
            payload.id = entities._alloc_id()
            entities.section_planes.append(payload)


def _resolve_construction_layer(
    payload: GuidePoint | GuideLine | SectionPlane,
    layers: dict[int, int],
) -> None:
    """Translate one construction entity's archive layer index in place."""
    if payload.layer_id is not None:
        payload.layer_id = layers.get(payload.layer_id)


def _add_annotations(
    entities: Entities,
    payloads: tuple[SupportedObjectPayload, ...],
    edge_id_by_archive_index: dict[int, int],
    materials: dict[int, int],
    layers: dict[int, int],
) -> dict[int, int]:
    """Convert annotations and map temporary payload identity to public ID."""
    converted_entity_ids: dict[int, int] = {}
    for payload in payloads:
        if isinstance(payload, TextPayload):
            text = _text_from_payload(payload, edge_id_by_archive_index, materials, layers)
            text.id = entities._alloc_id()
            entities.texts.append(text)
            public_id = text.id
        elif isinstance(payload, DimensionLinearPayload):
            linear_dimension = _linear_dimension_from_payload(payload, edge_id_by_archive_index, materials, layers)
            linear_dimension.id = entities._alloc_id()
            entities.linear_dimensions.append(linear_dimension)
            public_id = linear_dimension.id
        elif isinstance(payload, DimensionRadialPayload):
            radial_dimension = _radial_dimension_from_payload(payload, edge_id_by_archive_index, materials, layers)
            radial_dimension.id = entities._alloc_id()
            entities.radial_dimensions.append(radial_dimension)
            public_id = radial_dimension.id
        else:
            continue
        converted_entity_ids[id(payload)] = public_id
    return converted_entity_ids


def curve_payloads_by_archive_index(
    provenance: ArchiveProvenance,
) -> dict[int, Curve | ArcCurve]:
    """Index curves needed to resolve recursive SU3 edge references."""
    return {
        archive_index: payload
        for archive_index, payload in provenance.archive_objects
        if isinstance(payload, (Curve, ArcCurve))
    }


def index_archive_object_identities(
    archive_objects: tuple[tuple[int, SupportedObjectPayload], ...],
) -> dict[int, tuple[int, ...]]:
    """Map object identity to all archive indices that resolve to that object."""
    mutable: dict[int, list[int]] = {}
    for archive_index, payload in archive_objects:
        mutable.setdefault(id(payload), []).append(archive_index)
    return {identity: tuple(indices) for identity, indices in mutable.items()}


def _add_edge(
    entities: Entities,
    archived_edge: EdgeState,
    vertex_by_position: dict[tuple[float, float, float], int],
    layer_id_by_object_index: dict[int, int],
) -> Edge:
    edge = archived_edge.edge
    edge.id = entities._alloc_id()
    edge.start_vertex_id = _vertex_id(entities, archived_edge.start_vertex, vertex_by_position)
    edge.end_vertex_id = _vertex_id(entities, archived_edge.end_vertex, vertex_by_position)
    if edge.layer_id is not None:
        edge.layer_id = layer_id_by_object_index.get(edge.layer_id)
    entities.edges.append(edge)
    return edge


def _vertex_id(
    entities: Entities,
    vertex: Vertex,
    vertex_by_position: dict[tuple[float, float, float], int],
) -> int:
    position = vertex.position.to_tuple()
    vertex_id = vertex_by_position.get(position)
    if vertex_id is None:
        vertex.id = entities._alloc_id()
        entities.vertices.append(vertex)
        vertex_id = vertex.id
        vertex_by_position[position] = vertex_id
    else:
        # Preserve archive-reference resolution when a separately serialized
        # vertex is welded to an existing public vertex at the same position.
        vertex.id = vertex_id
    return vertex_id


def _entity_ids_by_archive_index(
    entities: Entities,
    payloads: tuple[SupportedObjectPayload, ...],
    *,
    archive_indices_by_identity: dict[int, tuple[int, ...]],
    converted_entity_ids: dict[int, int],
) -> dict[int, int]:
    """Map archive object indices to finalized IDs in the shared graph."""
    scoped_entities: tuple[
        Vertex
        | Edge
        | Face
        | ComponentInstance
        | Group
        | Image
        | Curve
        | ArcCurve
        | GuidePoint
        | GuideLine
        | SectionPlane,
        ...,
    ] = (
        *entities.vertices,
        *entities.edges,
        *entities.faces,
        *entities.component_instances,
        *entities.groups,
        *entities.images,
        *entities.curves,
        *entities.arc_curves,
        *entities.guide_points,
        *entities.guide_lines,
        *entities.section_planes,
    )
    public_id_by_identity = {id(entity): entity.id for entity in scoped_entities}
    for payload in payloads:
        if not isinstance(payload, EdgeState):
            continue
        # Welded archive vertices may not be the object retained in the public
        # list, but _vertex_id() assigns them the retained vertex's ID.
        public_id_by_identity[id(payload.start_vertex)] = payload.start_vertex.id
        public_id_by_identity[id(payload.end_vertex)] = payload.end_vertex.id
        public_id_by_identity[id(payload)] = payload.edge.id
    public_id_by_identity.update(converted_entity_ids)

    entity_ids: dict[int, int] = {}
    for identity, public_id in public_id_by_identity.items():
        if public_id <= 0:
            continue
        for archive_index in archive_indices_by_identity.get(identity, ()):
            entity_ids[archive_index] = public_id
    return entity_ids


def _append_relationships(
    entities: Entities,
    relationships: RelationshipCollection,
    entity_ids: dict[int, int],
) -> None:
    """Append relationships after translating their archive references."""
    for source_tag, target_tag in relationships:
        source_index = source_tag.index
        target_index = target_tag.index
        entities.relationships.append(
            EntityRelationship(
                source_id=(entity_ids.get(source_index) if source_index is not None else None),
                target_id=(entity_ids.get(target_index) if target_index is not None else None),
            )
        )


def _append_entity_attribute_dictionaries(
    entities: Entities,
    container_indices_by_owner: tuple[tuple[int, int], ...],
    archive_objects: tuple[tuple[int, SupportedObjectPayload], ...],
    entity_ids: dict[int, int],
    *,
    objects_by_archive_index: Mapping[int, SupportedObjectPayload] | None,
) -> None:
    """Attach named dictionaries to their resolved owner in this scope."""
    entities.attribute_dictionaries_by_entity_id.update(
        attribute_dictionaries_by_owner_id(
            container_indices_by_owner,
            archive_objects,
            entity_ids,
            objects_by_archive_index=objects_by_archive_index,
        )
    )


def _add_curves(
    entities: Entities,
    curves: dict[int, Curve | ArcCurve],
    edge_ids_by_curve: dict[int, list[int]],
) -> None:
    edges_by_id = {edge.id: edge for edge in entities.edges}
    for curve_key, edge_ids in edge_ids_by_curve.items():
        curve = curves[curve_key]
        curve.id = entities._alloc_id()
        curve.edge_ids = list(edge_ids)
        if isinstance(curve, ArcCurve):
            entities.arc_curves.append(curve)
        else:
            entities.curves.append(curve)
        for edge_id in edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is not None:
                edge.curve_id = curve.id


def _add_face(
    entities: Entities,
    face: Face,
    edge_id_by_archive_index: dict[int, int],
    material_id_by_object_index: dict[int, int],
    layer_id_by_object_index: dict[int, int],
) -> None:
    for loop in (face.outer_loop, *face.inner_loops):
        for edge_use in loop.edge_uses:
            edge_use.edge_id = edge_id_by_archive_index.get(edge_use.edge_id, edge_use.edge_id)
    face.id = entities._alloc_id()
    face.front_material_id = material_id_by_object_index.get(face.front_material_id or 0)
    face.back_material_id = material_id_by_object_index.get(face.back_material_id or 0)
    if face.layer_id is not None:
        face.layer_id = layer_id_by_object_index.get(face.layer_id)
    entities.faces.append(face)


def _add_instance(
    entities: Entities,
    instance: ComponentInstance | Group | Image,
    definition_by_object_index: dict[int, ComponentDefinition],
    material_id_by_object_index: dict[int, int],
    layer_id_by_object_index: dict[int, int],
) -> None:
    definition = definition_by_object_index.get(instance.definition_id)
    if definition is None:
        # A dangling archive reference cannot be represented safely in the
        # public graph, where definition_id must point at an installed object.
        return
    instance.id = entities._alloc_id()
    instance.definition_id = definition.id
    if instance.material_id is not None:
        instance.material_id = material_id_by_object_index.get(instance.material_id)
    if instance.layer_id is not None:
        instance.layer_id = layer_id_by_object_index.get(instance.layer_id)
    if isinstance(instance, Group):
        entities.groups.append(instance)
    elif isinstance(instance, Image):
        entities.images.append(instance)
    else:
        entities.component_instances.append(instance)


def _drawing_properties(
    state: DrawingElementState,
    materials: dict[int, int],
    layers: dict[int, int],
) -> DrawingElementProperties:
    """Translate archive references in a drawing-element base to public IDs."""
    return DrawingElementProperties(
        material_id=materials.get(state.material_tag.index or 0),
        layer_id=layers.get(state.layer_tag.index or 0) if state.layer_tag else None,
        hidden=state.hidden,
        casts_shadows=state.casts_shadows,
        receives_shadows=state.receives_shadows,
        soft=state.soft,
        smooth=state.smooth,
        locked=state.locked,
    )


def _point_reference(
    payload: PointRefPayload,
    entity_ids: dict[int, int],
) -> PointReference:
    """Drop archive tag mechanics while retaining every resolvable reference."""
    return PointReference(
        kind=payload.kind,
        position=Vector3D(*payload.position),
        entity_id=entity_ids.get(payload.leaf_tag.index or 0),
        secondary_entity_id=(
            entity_ids.get(payload.secondary_leaf_tag.index or 0) if payload.secondary_leaf_tag is not None else None
        ),
        instance_path_ids=[
            entity_id for tag in payload.instance_path if (entity_id := entity_ids.get(tag.index or 0)) is not None
        ],
        secondary_instance_path_ids=[
            entity_id
            for tag in payload.secondary_instance_path
            if (entity_id := entity_ids.get(tag.index or 0)) is not None
        ],
    )


def _dimension_from_payload(
    payload: DimensionPayload,
    materials: dict[int, int],
    layers: dict[int, int],
) -> Dimension:
    return Dimension(
        text=payload.text,
        font=payload.font,
        font_id=payload.font_tag.index,
        is_3d_text=payload.is_3d_text,
        arrow_type=payload.arrow_type,
        drawing=_drawing_properties(payload.drawing_element, materials, layers),
    )


def _linear_dimension_from_payload(
    payload: DimensionLinearPayload,
    entity_ids: dict[int, int],
    materials: dict[int, int],
    layers: dict[int, int],
) -> LinearDimension:
    base = _dimension_from_payload(payload.dimension, materials, layers)
    return LinearDimension(
        text=base.text,
        font=base.font,
        font_id=base.font_id,
        is_3d_text=base.is_3d_text,
        arrow_type=base.arrow_type,
        drawing=base.drawing,
        start=_point_reference(payload.start_ref, entity_ids),
        end=_point_reference(payload.end_ref, entity_ids),
        direction=Vector3D(*payload.normal),
        render_direction=Vector3D(*payload.x_axis),
        mode=payload.dimension_type,
        offset=payload.y_position,
        line_position=payload.x_position,
        alignment=payload.text_position,
    )


def _radial_dimension_from_payload(
    payload: DimensionRadialPayload,
    entity_ids: dict[int, int],
    materials: dict[int, int],
    layers: dict[int, int],
) -> RadialDimension:
    base = _dimension_from_payload(payload.dimension, materials, layers)
    arc = payload.arc
    public_arc = (
        ArcGeometry(
            center=Vector3D(*arc[0]),
            normal=Vector3D(*arc[1]),
            x_axis=Vector3D(*arc[2]),
            start_angle=arc[3],
            end_angle=arc[4],
            y_axis=Vector3D(*arc[5]) if arc[5] is not None else None,
        )
        if arc is not None
        else None
    )
    return RadialDimension(
        text=base.text,
        font=base.font,
        font_id=base.font_id,
        is_3d_text=base.is_3d_text,
        arrow_type=base.arrow_type,
        drawing=base.drawing,
        target_entity_id=entity_ids.get(payload.target_tag.index or 0),
        parameter=payload.parameter,
        radius_ratio=payload.radius_ratio,
        is_diameter=payload.is_diameter,
        arc=public_arc,
    )


def _text_from_payload(
    payload: TextPayload,
    entity_ids: dict[int, int],
    materials: dict[int, int],
    layers: dict[int, int],
) -> Text:
    return Text(
        text=payload.text,
        anchor=_point_reference(payload.point_ref, entity_ids),
        font=payload.font,
        font_id=payload.font_tag.index,
        screen_position=Vector2D(payload.screen_x, payload.screen_y),
        leader_vector=Vector3D(*payload.leader_vector),
        view_direction=Vector3D(*payload.view_direction),
        leader_type=payload.leader_type,
        line_weight=payload.line_weight,
        anchor_in_front=payload.point_ref_front,
        hide_out_of_plane=payload.hide_out_of_plane,
        arrow_type=payload.arrow_type,
        display_leader=payload.display_leader,
        convert_to_screen_on_explode=payload.convert_to_screen_on_explode,
        hidden_leader_direction=payload.hidden_leader_direction,
        drawing=_drawing_properties(payload.drawing_element, materials, layers),
    )
