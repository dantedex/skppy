# SPDX-License-Identifier: MIT
"""Write genuine pre-ZIP SketchUp Make 2017 CArchive geometry."""

from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np

from ..data_structure.annotations import (
    ArcGeometry,
    Dimension,
    DrawingElementProperties,
    LinearDimension,
    PointReference,
    RadialDimension,
    Text,
)
from ..data_structure.construction import Camera, GuideLine, GuidePoint, SectionPlane, ShadowInfo
from ..data_structure.entities import (
    EDGE_FLAG_HIDDEN,
    EDGE_FLAG_SMOOTH,
    EDGE_FLAG_SOFT,
    ArcCurve,
    ComponentDefinition,
    ComponentInstance,
    Curve,
    Edge,
    Entities,
    Face,
    FaceUVProjection,
    Group,
    Image,
    Loop,
)
from ..data_structure.model import Model
from ..data_structure.layers import Layer
from ..data_structure.materials import Color, Material
from ..data_structure.model_metadata import (
    AttributeDictionary,
    AttributeDictionaryEntry,
    DimensionStyle,
    EntityRelationship,
    Font,
    ModelViewAxes,
    RenderingOptions,
    StyleDescriptor,
    StylesRegistry,
    TextStyle,
    Watermark,
    WatermarkManager,
)
from ..data_structure.primitives import Transform, Vector3D
from ..data_structure.scene_data import PageBackgroundImage, Scene
from .._material_validation import validate_material_export, validate_material_names
from .._atomic_io import atomic_write
from .envelope import _rendering_options, build_legacy_2017_prefix
from .extensions import extension_dictionary

_FIRST_DYNAMIC_ARCHIVE_INDEX = 11


class _LegacyGeometryEncoder:
    """Encode root geometry while maintaining the shared CArchive index table."""

    def __init__(self, entities: Entities, *, first_archive_index: int = _FIRST_DYNAMIC_ARCHIVE_INDEX) -> None:
        self.entities = entities
        self.data = bytearray()
        self.first_archive_index = first_archive_index
        self.next_index = first_archive_index
        self.class_indices: dict[str, int] = {
            "CAttributeContainer": 3,
            "CAttributeNamed": 5,
            "CCamera": 7,
        }
        self.vertex_indices: dict[int, int] = {}
        self.edge_indices: dict[int, int] = {}
        self.vertices = {vertex.id: vertex for vertex in entities.vertices}
        self.edges = {edge.id: edge for edge in entities.edges}
        self.curves: dict[int, Curve | ArcCurve] = {
            **{curve.id: curve for curve in entities.curves},
            **{curve.id: curve for curve in entities.arc_curves},
        }
        self.curve_indices: dict[int, int] = {}
        self.entity_indices: dict[int, int] = {}
        self.next_persistent_id = 18
        self.material_indices: dict[int, int] = {}
        self.layer_indices: dict[int, int] = {}
        self.attribute_dictionaries_by_entity_id = entities.attribute_dictionaries_by_entity_id
        self.fonts: list[Font] = []
        self.font_indices: dict[int, int] = {}
        self.watermark_indices: dict[int, int] = {}
        self.style_indices: dict[int, int] = {}
        self.background_image_indices: dict[int, int] = {}
        self.next_style_persistent_id = 1
        self.definitions_by_id: dict[int, ComponentDefinition] = {}
        self.definition_entity_indices: dict[int, dict[int, int]] = {}

    def encode(self) -> bytes:
        """Return faces followed by their SDK-style top-level edge references."""
        _validate_entity_scope(self.entities)
        self.data += struct.pack("<I", self._entity_count())
        self._write_top_level_entities()
        self.data += struct.pack("<I", len(self.entities.relationships))
        for relationship in self.entities.relationships:
            self._write_relationship(relationship)
        self._write_reference(None)
        return bytes(self.data)

    def _entity_count(self) -> int:
        return (
            len(self.entities.edges)
            + len(self.entities.faces)
            + len(self.entities.guide_points)
            + len(self.entities.guide_lines)
            + len(self.entities.section_planes)
            + len(self.entities.component_instances)
            + len(self.entities.groups)
            + len(self.entities.images)
            + len(self.entities.texts)
            + len(self.entities.linear_dimensions)
            + len(self.entities.radial_dimensions)
        )

    def _write_top_level_entities(self) -> None:
        for face in self.entities.faces:
            self._write_face(face)
        for edge in self.entities.edges:
            object_index = self.edge_indices.get(edge.id)
            if object_index is None:
                self._write_edge(edge)
            else:
                self._write_reference(object_index)
        for point in self.entities.guide_points:
            self._write_guide_point(point)
        for line in self.entities.guide_lines:
            self._write_guide_line(line)
        for section in self.entities.section_planes:
            self._write_section_plane(section)
        for instance in self.entities.component_instances:
            self._write_component_placement(instance, "CComponentInstance", 6)
        for group in self.entities.groups:
            self._write_component_placement(group, "CGroup", 1)
        for image in self.entities.images:
            self._write_component_placement(image, "CImage", 1)
        self._write_annotations()

    def _write_annotations(self) -> None:
        for text in self.entities.texts:
            self._write_text(text)
        for linear_dimension in self.entities.linear_dimensions:
            self._write_linear_dimension(linear_dimension)
        for radial_dimension in self.entities.radial_dimensions:
            self._write_radial_dimension(radial_dimension)

    def _write_component_placement(
        self,
        placement: ComponentInstance | Group | Image,
        class_name: str,
        schema: int,
    ) -> None:
        del placement, class_name, schema
        raise NotImplementedError("Component placements require a model-level legacy encoder")

    def _write_edge(self, edge: Edge) -> None:
        object_index = self._write_new_object("CEdge", 2)
        self.edge_indices[edge.id] = object_index
        self._register_entity(edge.id, object_index)
        self._write_drawing_element(flags=edge.flags, layer_id=edge.layer_id, entity_id=edge.id)
        self._write_vertex(edge.start_vertex_id)
        self._write_vertex(edge.end_vertex_id)
        self._write_curve_reference(edge.curve_id)

    def _write_vertex(self, vertex_id: int) -> None:
        if vertex_id in self.vertex_indices:
            self._write_reference(self.vertex_indices[vertex_id])
            return
        vertex = self.vertices[vertex_id]
        object_index = self._write_new_object("CVertex", 0)
        self.vertex_indices[vertex_id] = object_index
        self._register_entity(vertex_id, object_index)
        self._write_entity(dictionaries=self.attribute_dictionaries_by_entity_id.get(vertex.id, ()))
        self.data += struct.pack("<3d", vertex.position.x, vertex.position.y, vertex.position.z)

    def _write_curve_reference(self, curve_id: int | None) -> None:
        if curve_id is None:
            self._write_reference(None)
            return
        if curve_id in self.curve_indices:
            self._write_reference(self.curve_indices[curve_id])
            return
        curve = self.curves[curve_id]
        is_semantic_arc = isinstance(curve, ArcCurve) and curve.center is not None
        class_name, schema = ("CArcCurve", 3) if is_semantic_arc else ("CCurve", 4)
        self.curve_indices[curve_id] = self._write_new_object(class_name, schema)
        self._register_entity(curve_id, self.curve_indices[curve_id])
        self._write_entity(dictionaries=self.attribute_dictionaries_by_entity_id.get(curve.id, ()))
        self.data += bytes((getattr(curve, "is_polygon", False),))
        self.data += struct.pack("<I", len(curve.edge_ids))
        if is_semantic_arc:
            assert isinstance(curve, ArcCurve)
            self._write_arc_geometry(curve)

    def _write_arc_geometry(self, curve: ArcCurve) -> None:
        assert curve.center is not None and curve.normal is not None
        assert curve.radius is not None and curve.start_angle is not None and curve.end_angle is not None
        center = np.asarray(curve.center, dtype=float)
        normal = _normalized(np.asarray(curve.normal, dtype=float), "arc normal")
        first_edge = self.edges[curve.edge_ids[0]]
        first_vertex = self.vertices[first_edge.start_vertex_id]
        radial = _normalized(np.asarray(first_vertex.position.to_tuple()) - center, "arc start radius")
        tangent = np.cross(normal, radial)
        x_direction = radial * np.cos(curve.start_angle) - tangent * np.sin(curve.start_angle)
        x_axis = x_direction * curve.radius
        y_axis = np.cross(normal, x_direction) * curve.radius
        self.data += struct.pack("<3d", *center)
        self.data += struct.pack("<3d", *normal)
        self.data += struct.pack("<3d", *x_axis)
        self.data += struct.pack("<2d", curve.start_angle, curve.end_angle)
        self.data += struct.pack("<3d", *y_axis)

    def _write_face(self, face: Face) -> None:
        self._register_entity(face.id, self._write_new_object("CFace", 3))
        self._write_drawing_element(
            material_id=face.front_material_id,
            layer_id=face.layer_id,
            front_uv=face.front_uv,
            back_uv=face.back_uv,
            entity_id=face.id,
        )
        self.data += struct.pack("<4d", *face.plane)
        loops = [face.outer_loop, *face.inner_loops]
        self.data += struct.pack("<I", len(loops))
        for index, loop in enumerate(loops):
            self._write_loop(loop, is_outer=index == 0)
        self._write_reference_for(self.material_indices, face.back_material_id, "material")

    def _write_loop(self, loop: Loop, *, is_outer: bool) -> None:
        loop_index = self._write_new_object("CLoop", 1)
        self._write_entity(persistent=False)
        self.data += bytes((is_outer, loop.is_convex is not False))
        for edge_use in loop.edge_uses:
            edge_index = self.edge_indices.get(edge_use.edge_id)
            if edge_index is None:
                edge = self.edges[edge_use.edge_id]
            self._write_new_object("CEdgeUse", 1)
            self._write_entity(persistent=False)
            if edge_index is None:
                assert edge is not None
                self._write_edge(edge)
                edge_index = self.edge_indices[edge_use.edge_id]
            else:
                self._write_reference(edge_index)
            self.data += bytes((edge_use.reversed,))
            self._write_reference(loop_index)
        self._write_reference(None)

    def _write_drawing_element(
        self,
        *,
        flags: int = 0,
        material_id: int | None = None,
        layer_id: int | None = None,
        persistent: bool = True,
        front_uv: FaceUVProjection | None = None,
        back_uv: FaceUVProjection | None = None,
        entity_id: int | None = None,
        drawing: DrawingElementProperties | None = None,
    ) -> None:
        dictionaries = self.attribute_dictionaries_by_entity_id.get(entity_id, ()) if entity_id is not None else ()
        self._write_entity(
            persistent=persistent,
            front_uv=front_uv,
            back_uv=back_uv,
            dictionaries=dictionaries,
        )
        self._write_reference_for(self.material_indices, material_id, "material")
        self.data += bytes(
            (
                drawing.hidden if drawing is not None else bool(flags & EDGE_FLAG_HIDDEN),
                drawing.casts_shadows if drawing is not None else True,
                drawing.receives_shadows if drawing is not None else True,
                drawing.soft if drawing is not None else bool(flags & EDGE_FLAG_SOFT),
                drawing.smooth if drawing is not None else bool(flags & EDGE_FLAG_SMOOTH),
                drawing.locked if drawing is not None else False,
            )
        )
        self._write_reference_for(self.layer_indices, layer_id, "layer")

    def _write_guide_point(self, point: GuidePoint) -> None:
        self._register_entity(point.id, self._write_new_object("CConstructionPoint", 0))
        self._write_drawing_element(layer_id=point.layer_id, entity_id=point.id)
        self.data += struct.pack("<3d", *_vector3_values(point.position))
        reference = point.reference_point or (0.0, 0.0, 0.0)
        self.data += struct.pack("<3d", *_vector3_values(reference))
        self.data += bytes((point.reference_point is not None,))

    def _write_guide_line(self, line: GuideLine) -> None:
        self._register_entity(line.id, self._write_new_object("CConstructionLine", 1))
        self._write_drawing_element(layer_id=line.layer_id, entity_id=line.id)
        self.data += struct.pack("<3d", *_vector3_values(line.point))
        self.data += struct.pack("<3d", *_vector3_values(line.direction))
        self.data += struct.pack("<ddI", line.start_parameter, line.end_parameter, line.stipple_pattern)

    def _write_section_plane(self, section: SectionPlane) -> None:
        self._register_entity(section.id, self._write_new_object("CSectionPlane", 3))
        self._write_drawing_element(layer_id=section.layer_id, entity_id=section.id)
        self.data += struct.pack("<4d", *section.plane)

    def _write_text(self, text: Text) -> None:
        self._register_entity(text.id, self._write_new_object("CText", 9))
        self._write_drawing_element(
            material_id=text.drawing.material_id,
            layer_id=text.drawing.layer_id,
            entity_id=text.id,
            drawing=text.drawing,
        )
        self._write_font(self._annotation_font(text))
        self.data += struct.pack("<2d", text.screen_position.x, text.screen_position.y)
        self._write_point_reference(text.anchor)
        self.data += struct.pack("<3d", *_vector3_values(text.leader_vector))
        self.data += struct.pack("<3d", *_vector3_values(text.view_direction))
        self.data += struct.pack("<II", text.leader_type, text.line_weight)
        self.data += bytes((text.anchor_in_front, text.hide_out_of_plane))
        self.data += struct.pack("<I", text.arrow_type)
        self.data += bytes((text.display_leader,))
        self.data += _encode_legacy_string(text.text)
        self.data += bytes((text.convert_to_screen_on_explode,))
        self.data += struct.pack("<I", text.hidden_leader_direction)

    def _write_linear_dimension(self, dimension: LinearDimension) -> None:
        self._register_entity(dimension.id, self._write_new_object("CDimensionLinear", 6))
        self._write_dimension(dimension)
        self._write_point_reference(dimension.start, force_version_4=True)
        self._write_point_reference(dimension.end, force_version_4=True)
        self.data += struct.pack("<3d", *_vector3_values(dimension.direction))
        self.data += struct.pack("<3d", *_vector3_values(dimension.render_direction))
        self.data += struct.pack(
            "<IddI",
            dimension.mode,
            dimension.offset,
            dimension.line_position,
            dimension.alignment,
        )

    def _write_radial_dimension(self, dimension: RadialDimension) -> None:
        self._register_entity(dimension.id, self._write_new_object("CDimensionRadial", 2))
        self._write_dimension(dimension)
        if dimension.target_entity_id is None:
            self._write_reference(None)
        else:
            self._write_entity_reference(dimension.target_entity_id, "radial-dimension target")
        self.data += struct.pack("<2dB", dimension.parameter, dimension.radius_ratio, dimension.is_diameter)
        if dimension.target_entity_id is None:
            self._write_embedded_arc(dimension.arc)

    def _write_dimension(self, dimension: Dimension) -> None:
        self._write_drawing_element(
            material_id=dimension.drawing.material_id,
            layer_id=dimension.drawing.layer_id,
            entity_id=dimension.id,
            drawing=dimension.drawing,
        )
        self.data += _encode_legacy_string(dimension.text)
        self._write_font(self._annotation_font(dimension))
        self.data += bytes((dimension.is_3d_text,))
        self.data += struct.pack("<I", dimension.arrow_type)

    def _annotation_font(self, annotation: Dimension | Text) -> Font:
        if annotation.font is not None:
            if annotation.font_id is not None:
                try:
                    indexed_font = self.fonts[annotation.font_id - 2]
                except IndexError as exc:
                    raise ValueError("Annotation font_id does not identify a written model font") from exc
                if indexed_font is not annotation.font:
                    raise ValueError("Annotation font and font_id identify different fonts")
            return annotation.font
        if annotation.font_id is not None:
            try:
                return self.fonts[annotation.font_id - 2]
            except IndexError as exc:
                raise ValueError("Annotation font_id does not identify a written model font") from exc
        return Font("Arial", point_size=12, world_size=1.0)

    def _write_font(self, font: Font) -> None:
        existing_index = self.font_indices.get(id(font))
        if existing_index is not None:
            self._write_reference(existing_index)
            return
        object_index = self._write_new_object("CSkFont", 1)
        self.font_indices[id(font)] = object_index
        persistent_id = next((index + 2 for index, item in enumerate(self.fonts) if item is font), None)
        self._write_entity(persistent_id=persistent_id)
        self.data += _encode_legacy_string(font.face_name)
        self.data += bytes((font.bold, font.italic))
        self.data += struct.pack("<I", font.point_size)
        self.data += bytes((font.use_world_size,))
        self.data += struct.pack("<d", font.world_size)

    def _write_point_reference(self, reference: PointReference, *, force_version_4: bool = False) -> None:
        kind = reference.kind or (5 if reference.entity_id is not None else 1)
        uses_extended_graph = any(
            (
                reference.secondary_entity_id is not None,
                reference.instance_path_ids,
                reference.secondary_instance_path_ids,
            )
        )
        format_version = 4 if force_version_4 or uses_extended_graph else 0
        self.data += struct.pack("<II3d", kind, format_version, *_vector3_values(reference.position))
        leaf_index, path_indices = self._resolve_point_reference(reference.entity_id, reference.instance_path_ids)
        self._write_reference(leaf_index)
        if format_version > 0:
            secondary_leaf_index, secondary_path_indices = self._resolve_point_reference(
                reference.secondary_entity_id,
                reference.secondary_instance_path_ids,
            )
            self._write_reference(secondary_leaf_index)
        self._write_reference_path(path_indices)
        if format_version > 3:
            self._write_reference_path(secondary_path_indices)

    def _resolve_point_reference(self, entity_id: int | None, path_ids: list[int]) -> tuple[int | None, list[int]]:
        scope_entities = self.entities
        scope_indices = self.entity_indices
        path_indices: list[int] = []
        for placement_id in path_ids:
            placement_index = scope_indices.get(placement_id)
            if placement_index is None:
                raise ValueError(f"Legacy point-reference path references missing placement ID {placement_id}")
            path_indices.append(placement_index)
            placements: list[ComponentInstance | Group | Image] = [
                *scope_entities.component_instances,
                *scope_entities.groups,
                *scope_entities.images,
            ]
            placement = next((item for item in placements if item.id == placement_id), None)
            if placement is None:
                raise ValueError(f"Legacy point-reference path ID {placement_id} is not a component placement")
            definition = self.definitions_by_id.get(placement.definition_id)
            scope_indices = self.definition_entity_indices.get(placement.definition_id, {})
            if definition is None or not scope_indices:
                raise ValueError(
                    f"Legacy point-reference path uses unavailable definition ID {placement.definition_id}"
                )
            scope_entities = definition.entities
        if entity_id is None:
            return None, path_indices
        leaf_index = scope_indices.get(entity_id)
        if leaf_index is None:
            raise ValueError(f"Legacy point-reference leaf references missing entity ID {entity_id}")
        return leaf_index, path_indices

    def _write_reference_path(self, object_indices: list[int]) -> None:
        self.data += struct.pack("<I", len(object_indices))
        for object_index in object_indices:
            self._write_reference(object_index)

    def _write_entity_reference(self, entity_id: int, label: str) -> None:
        object_index = self.entity_indices.get(entity_id)
        if object_index is None:
            raise ValueError(f"Legacy {label} references missing entity ID {entity_id}")
        self._write_reference(object_index)

    def _write_embedded_arc(self, arc: ArcGeometry | None) -> None:
        if arc is None:
            raise ValueError("Unassociated legacy radial dimensions require embedded arc geometry")
        self.data += struct.pack("<3d", *_vector3_values(arc.center))
        self.data += struct.pack("<3d", *_vector3_values(arc.normal))
        self.data += struct.pack("<3d", *_vector3_values(arc.x_axis))
        self.data += struct.pack("<2d", arc.start_angle, arc.end_angle)
        y_axis = arc.y_axis or Vector3D(0.0, 1.0, 0.0)
        self.data += struct.pack("<3d", *_vector3_values(y_axis))

    def _register_entity(self, entity_id: int, object_index: int) -> None:
        self.entity_indices[entity_id] = object_index

    def _write_relationship(self, relationship: EntityRelationship) -> None:
        if relationship.source_id is None or relationship.target_id is None:
            raise ValueError("Legacy relationships require source and target IDs")
        source_index = self.entity_indices.get(relationship.source_id)
        target_index = self.entity_indices.get(relationship.target_id)
        if source_index is None or target_index is None:
            raise ValueError(
                f"Legacy relationship references missing entity IDs {relationship.source_id}, {relationship.target_id}"
            )
        self._write_new_object("CRelationship", 0)
        self._write_entity()
        self._write_reference(source_index)
        self._write_reference(target_index)

    def _write_entity(
        self,
        *,
        persistent: bool = True,
        persistent_id: int | None = None,
        front_uv: FaceUVProjection | None = None,
        back_uv: FaceUVProjection | None = None,
        dictionaries: tuple[AttributeDictionary, ...] | list[AttributeDictionary] = (),
    ) -> None:
        if front_uv is None and back_uv is None and not dictionaries:
            self._write_reference(None)
        else:
            self._write_attribute_container(dictionaries, front_uv, back_uv)
        if persistent:
            value = self.next_persistent_id if persistent_id is None else persistent_id
            self.data += _encode_sparse_u64(value)
            if persistent_id is None:
                self.next_persistent_id += 1
        else:
            self.data.append(0)

    def _write_attribute_container(
        self,
        dictionaries: tuple[AttributeDictionary, ...] | list[AttributeDictionary],
        front_uv: FaceUVProjection | None,
        back_uv: FaceUVProjection | None,
    ) -> None:
        self._write_new_object("CAttributeContainer", 0)
        self._write_entity(persistent=False)
        for dictionary in dictionaries:
            self._write_named_attribute(dictionary)
        if front_uv is not None or back_uv is not None:
            self._write_new_object("CFaceTextureCoords", 4)
            self._write_entity(persistent=False)
            self.data += struct.pack("<I", 0)
            self._write_uv_projection(front_uv)
            self._write_uv_projection(back_uv)
            self._write_uv_pins(front_uv)
            self._write_uv_pins(back_uv)
            self.data += struct.pack("<II", _uv_flags(front_uv), _uv_flags(back_uv))
        self._write_reference(None)

    def _write_named_attribute(self, dictionary: AttributeDictionary) -> None:
        if not dictionary.name:
            raise ValueError("Legacy attribute dictionary names must not be empty")
        self._write_new_object("CAttributeNamed", 1)
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", 0)
        self.data += _encode_legacy_string(dictionary.name)
        for entry in dictionary.entries:
            if not entry.key:
                raise ValueError("Legacy attribute dictionary keys must not be empty")
            self.data += _encode_legacy_string(entry.key)
            self.data += _encode_legacy_typed_value(entry)
            if entry.flags:
                self.data += _encode_legacy_string(f"__skppy_flags__:{entry.key}")
                self.data += bytes((4,)) + struct.pack("<I", entry.flags)
        self.data += _encode_legacy_string("")
        self.data += struct.pack("<I", 0)

    def _write_uv_projection(self, projection: FaceUVProjection | None) -> None:
        transform = projection.transform if projection is not None else [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        if len(transform) != 9:
            raise ValueError("Legacy face UV transform must contain nine values")
        self.data += struct.pack("<9d", *transform)
        origin = (0.0, 0.0, 0.0)
        if projection is not None:
            origin = projection.projection_direction or projection.origin or origin
        self.data += struct.pack("<3d", *_vector3_values(origin))

    def _write_uv_pins(self, projection: FaceUVProjection | None) -> None:
        pins = projection.pins if projection is not None else []
        self.data += struct.pack("<I", len(pins))
        for pin in pins:
            self.data += struct.pack(
                "<4d",
                pin.texture_position.x,
                pin.texture_position.y,
                pin.model_position.x,
                pin.model_position.y,
            )

    def _write_new_object(self, class_name: str, schema: int) -> int:
        class_index = self.class_indices.get(class_name)
        if class_index is None:
            encoded_name = class_name.encode("ascii")
            self.data += struct.pack("<HHH", 0xFFFF, schema, len(encoded_name)) + encoded_name
            class_index = self.next_index
            self.class_indices[class_name] = class_index
            self.next_index += 1
        else:
            self.data += struct.pack("<H", 0x8000 | class_index)
        object_index = self.next_index
        self.next_index += 1
        return object_index

    def _write_reference(self, object_index: int | None) -> None:
        self.data += struct.pack("<H", object_index or 0)

    def _write_reference_for(self, indices: dict[int, int], value_id: int | None, label: str) -> None:
        if value_id is None:
            self._write_reference(None)
            return
        object_index = indices.get(value_id)
        if object_index is None:
            raise ValueError(f"Legacy entity references missing {label} ID {value_id}")
        self._write_reference(object_index)


class _LegacyModelEncoder(_LegacyGeometryEncoder):
    """Encode the complete root component and its shared resource registries."""

    def __init__(self, model: Model, entities: Entities) -> None:
        super().__init__(entities, first_archive_index=9)
        self.model = model
        self.fonts = model.fonts or _default_fonts()
        self.definitions_by_id = {definition.id: definition for definition in model.definitions}
        self.definition_indices: dict[int, int] = {}
        extension = extension_dictionary(model)
        self.root_dictionaries = [*model.attribute_dictionaries, *([extension] if extension is not None else [])]

    def encode(self) -> bytes:
        """Return the root component from its drawing-element base onward."""
        self._write_entity(persistent=False, dictionaries=self.root_dictionaries)
        self._write_reference(None)
        self.data += bytes((False, True, True, False, False, False))
        self._write_reference(None)
        self._write_material_manager()
        self._write_layer_manager()
        self._write_definition_list()
        super().encode()
        self._write_model_metadata_prefix()
        return bytes(self.data)

    def _write_model_metadata_prefix(self) -> None:
        self._write_shadow_info(self.model.shadow_info or ShadowInfo())
        self._write_page_list()
        self._write_model_axes(self.model.model_view_axes or ModelViewAxes())
        self.data += bytes(16 * 4)
        self._write_dimension_style(self.model.dimension_style or _default_dimension_style())
        default_text_font_id = 3 if len(self.fonts) > 1 else 2
        self._write_text_style(self.model.text_style or _default_text_style(default_text_font_id))
        self._write_font_manager()
        self._write_visual_metadata_tail()

    def _write_visual_metadata_tail(self) -> None:
        self._write_background_image_reference(self.model.background_image)
        registry = self.model.styles_registry or _default_styles_registry()
        manager = self.model.watermark_manager or WatermarkManager()
        self._write_styles_registry(registry, manager)
        self._write_watermark_manager(manager)
        self.data += struct.pack("<IBI", 0, True, 0)

    def _write_styles_registry(self, registry: StylesRegistry, manager: WatermarkManager) -> None:
        if not registry.styles:
            raise ValueError("A legacy styles registry must contain at least one style")
        if not 1 <= registry.active_style_ref <= len(registry.styles):
            raise ValueError("Legacy active style reference must identify a registered style")
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", len(registry.styles))
        style_indices = [self._write_style(style, manager) for style in registry.styles]
        self._write_reference(style_indices[registry.active_style_ref - 1])
        if registry.inline_style_override is None:
            self._write_reference(None)
        else:
            self._write_style(registry.inline_style_override, manager)
        self.data += bytes((registry.selected_style_dirty,))

    def _write_style(self, style: StyleDescriptor, manager: WatermarkManager) -> int:
        existing_index = self.style_indices.get(id(style))
        if existing_index is not None:
            self._write_reference(existing_index)
            return existing_index
        if len(style.guid) != 16:
            raise ValueError("Legacy style GUIDs must contain 16 bytes")
        if not style.file_name or any(character in style.file_name for character in "/\\"):
            raise ValueError("Legacy style file names must be non-empty and path-safe")
        object_index = self._write_new_object("CSkpStyle", 2)
        self.style_indices[id(style)] = object_index
        self._write_entity(persistent_id=self.next_style_persistent_id)
        self.next_style_persistent_id += 1
        self.data += style.guid
        self.data += _encode_legacy_string(style.file_name)
        self.data += struct.pack("<I", 3)
        self.data += _encode_legacy_string(style.file_name)
        self.data += _encode_legacy_string(style.file_name)
        self.data += struct.pack("<I", int(bool(style.watermark_reference_ids)))
        if style.watermark_reference_ids:
            self.data += struct.pack("<II", 0x1389, len(style.watermark_reference_ids))
            for watermark_id in style.watermark_reference_ids:
                self._write_watermark_id_reference(watermark_id, manager)
        return object_index

    def _write_watermark_manager(self, manager: WatermarkManager) -> None:
        if manager.serialized_count not in (0, len(manager.watermarks)):
            raise ValueError("Legacy serialized watermark count must match the watermark list")
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", len(manager.watermarks))
        for watermark in manager.watermarks:
            self._write_watermark(watermark)

    def _write_watermark_id_reference(self, watermark_id: int, manager: WatermarkManager) -> None:
        watermark = next(
            (mark for index, mark in enumerate(manager.watermarks, start=1) if (mark.id or index) == watermark_id),
            None,
        )
        if watermark is None:
            raise ValueError(f"Legacy style has unknown watermark reference {watermark_id}")
        self._write_watermark(watermark)

    def _write_watermark(self, watermark: Watermark) -> None:
        existing_index = self.watermark_indices.get(id(watermark))
        if existing_index is not None:
            self._write_reference(existing_index)
            return
        if not watermark.name or any(character in watermark.name for character in "/\\"):
            raise ValueError("Legacy watermark names must be non-empty and path-safe")
        if watermark.image_data is None:
            raise ValueError("Legacy watermarks require image data")
        if not 0.0 <= watermark.opacity <= 1.0 or not 0 <= watermark.position <= 5:
            raise ValueError("Legacy watermark opacity or position is outside its supported range")
        object_index = self._write_new_object("CWatermark", 1)
        self.watermark_indices[id(watermark)] = object_index
        self._write_entity(persistent_id=watermark.id if watermark.id > 0 else None)
        tiled = watermark.position == 5
        self.data += bytes((False,))
        self.data += _encode_legacy_string(watermark.name)
        self.data += struct.pack("<II", 0, 4 if tiled else watermark.position)
        self.data += bytes((tiled, False, not tiled, False, True))
        self.data += struct.pack("<2d", 0.5, watermark.opacity)
        self.data += _encode_legacy_string("")
        self._write_dib(watermark.image_data)

    def _write_dib(self, image_data: bytes) -> None:
        self._write_new_object("CDib", 3)
        self.data += struct.pack("<II", 4, len(image_data))
        self.data += image_data

    def _write_shadow_info(self, shadow: ShadowInfo) -> None:
        self._write_entity(persistent=False)
        self.data += struct.pack("<IB", shadow.time, shadow.daylight_savings)
        self.data += _encode_legacy_string(shadow.country.decode("utf-8"))
        self.data += _encode_legacy_string(shadow.city.decode("utf-8"))
        self.data += struct.pack("<3d", shadow.longitude, shadow.latitude, shadow.timezone_offset)
        self.data += struct.pack("<3d", *_vector3_values(shadow.north_direction))
        self.data += bytes(
            (
                shadow.display_shadows,
                shadow.display_north,
                shadow.display_on_all_faces,
                shadow.display_on_ground_plane,
            )
        )
        self.data += struct.pack("<iiB", shadow.light, shadow.dark, shadow.use_sun_for_all_shading)

    def _write_page_list(self) -> None:
        scene_ids = [scene.id for scene in self.model.scenes]
        scene_names = [scene.name for scene in self.model.scenes]
        if any(scene_id <= 0 for scene_id in scene_ids) or len(scene_ids) != len(set(scene_ids)):
            raise ValueError("Legacy scene IDs must be positive and unique")
        if any(not name for name in scene_names) or len(scene_names) != len(set(scene_names)):
            raise ValueError("Legacy scene names must be non-empty and unique")
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", len(self.model.scenes))
        scene_indices = [self._write_scene(scene) for scene in self.model.scenes]
        self._write_reference(scene_indices[0] if scene_indices else None)

    def _write_scene(self, scene: Scene) -> int:
        self._validate_scene(scene)
        object_index = self._write_new_object("CViewPage", 13)
        self._write_entity(persistent_id=scene.id if scene.id > 0 else None)
        self.data += _encode_legacy_string(scene.name)
        self.data += _encode_legacy_string(scene.description)
        self.data += struct.pack("<I", scene.flags)
        self._write_scene_snapshots(scene)
        self._write_scene_reference_sets(scene)
        self.data += bytes((scene.show_in_slideshow,))
        self.data += struct.pack("<2d", -1.0, -1.0)
        self._write_background_image_reference(self._scene_background_image(scene))
        self.data += bytes((scene.display_background_image, False))
        return object_index

    def _validate_scene(self, scene: Scene) -> None:
        if scene.style_reference and not scene.flags & 0x2:
            raise ValueError("A legacy scene style reference requires the use-rendering-options flag")
        if scene.display_background_image and scene.background_image is None and not scene.background_image_ref:
            raise ValueError("A displayed legacy scene background image requires an image")
        reference_sets = (
            (scene.hidden_entity_ids, 0x10, "hidden entities"),
            (scene.hidden_layer_ids, 0x20, "hidden layers"),
            (scene.active_section_plane_ids, 0x40, "active section planes"),
        )
        for values, flag, label in reference_sets:
            if values and not scene.flags & flag:
                raise ValueError(f"Legacy scene {label} require their use flag")

    def _scene_background_image(self, scene: Scene) -> PageBackgroundImage | None:
        if scene.background_image is not None:
            return scene.background_image
        if not scene.background_image_ref:
            return None
        candidates = [self.model.background_image, *(item.background_image for item in self.model.scenes)]
        image = next((item for item in candidates if item is not None and item.id == scene.background_image_ref), None)
        if image is None:
            raise ValueError(f"Legacy scene has unknown background image reference {scene.background_image_ref}")
        return image

    def _write_background_image_reference(self, image: PageBackgroundImage | None) -> None:
        if image is None:
            self._write_reference(None)
            return
        existing_index = self.background_image_indices.get(id(image))
        if existing_index is not None:
            self._write_reference(existing_index)
            return
        if image.image_data is None:
            raise ValueError("Legacy background images require image data")
        scalar_values = (
            image.reference_state,
            image.width,
            image.height,
            image.file_size,
            image.timestamp,
            image.image_source,
        )
        if any(not 0 <= value <= 0xFFFFFFFF for value in scalar_values):
            raise ValueError("Legacy background image integer fields must fit in u32")
        if not 0.0 <= image.opacity <= 1.0:
            raise ValueError("Legacy background image opacity must be between 0 and 1")
        object_index = self._write_new_object("CBackgroundImage", 10)
        self.background_image_indices[id(image)] = object_index
        self._write_entity(persistent_id=image.id if image.id > 0 else None)
        self.data += _encode_legacy_string(image.path)
        self.data += struct.pack("<I", image.reference_state)
        self._write_dib(image.image_data)
        self.data += struct.pack("<4I", image.width, image.height, image.file_size, image.timestamp)
        self.data += struct.pack("<BdI", image.visible, image.opacity, len(image.grip_points))
        for point in image.grip_points:
            self.data += struct.pack("<3d", *_vector3_values(point))
        self.data += struct.pack("<3d", *_vector3_values(image.principal_point_delta))
        self.data += struct.pack("<dI", image.radial_distortion_k1, image.image_source)

    def _write_scene_snapshots(self, scene: Scene) -> None:
        if scene.flags & 0x1:
            if scene.camera is None:
                raise ValueError("A legacy scene using its camera requires a camera snapshot")
            self._write_camera(scene.camera)
        elif scene.camera is not None:
            raise ValueError("A legacy scene camera snapshot requires the use-camera flag")
        if scene.flags & 0x2:
            self._write_entity(persistent=False)
            self.data += _rendering_options(self.model.rendering_options or RenderingOptions())
            self._write_scene_style_reference(scene)
        if scene.flags & 0x4:
            self._write_shadow_info(self.model.shadow_info or ShadowInfo())
            self.data += bytes(((self.model.shadow_info or ShadowInfo()).display_shadows,))
        if scene.flags & 0x8:
            self._write_model_axes(self.model.model_view_axes or ModelViewAxes())
            self.data += bytes((True,))

    def _write_scene_style_reference(self, scene: Scene) -> None:
        if scene.style_reference == 0:
            self._write_reference(None)
            return
        registry = self.model.styles_registry or _default_styles_registry()
        if not 1 <= scene.style_reference <= len(registry.styles):
            raise ValueError("Legacy scene style reference must identify a registered style")
        self._write_style(
            registry.styles[scene.style_reference - 1],
            self.model.watermark_manager or WatermarkManager(),
        )

    def _write_scene_reference_sets(self, scene: Scene) -> None:
        if scene.flags & 0x10:
            self._write_scene_references(scene.hidden_entity_ids, self.entity_indices, "entity")
        if scene.flags & 0x20:
            self._write_scene_references(scene.hidden_layer_ids, self.layer_indices, "layer")
        if scene.flags & 0x40:
            self._write_scene_references(scene.active_section_plane_ids, self.entity_indices, "section plane")

    def _write_scene_references(self, values: list[int], indices: dict[int, int], label: str) -> None:
        self.data += struct.pack("<I", len(values))
        for value in values:
            object_index = indices.get(value)
            if object_index is None:
                raise ValueError(f"Legacy scene has unknown {label} reference {value}")
            self._write_reference(object_index)

    def _write_camera(self, camera: Camera) -> None:
        self._write_new_object("CCamera", 5)
        for vector in (camera.eye, camera.target, camera.up):
            self.data += struct.pack("<3d", *_vector3_values(vector))
        self.data += struct.pack("<2dB", camera.near, camera.far, camera.is_perspective)
        self.data += struct.pack("<2d", camera.fov, camera.ortho_height if camera.ortho_height is not None else 1.0)
        self.data += struct.pack("<3d", 0.0, 0.0, 0.0)
        self.data += struct.pack("<dBB", camera.aspect_ratio or 0.0, camera.fov_is_height, camera.legacy_flag)
        self.data += _encode_legacy_string(camera.name)
        self.data += struct.pack("<dB", camera.image_width or 0.0, camera.is_2d)
        self.data += struct.pack(
            "<3d",
            camera.scale_2d if camera.scale_2d is not None else 1.0,
            camera.center_2d_x or 0.0,
            camera.center_2d_y or 0.0,
        )

    def _write_model_axes(self, axes: ModelViewAxes) -> None:
        self._write_drawing_element(persistent=False)
        for vector in (axes.origin, axes.x_axis, axes.y_axis, axes.z_axis):
            self.data += struct.pack("<3d", *_vector3_values(vector))

    def _write_dimension_style(self, style: DimensionStyle) -> None:
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", 0)
        self._write_font_id_reference(style.font_ref or 2, "Dimension style")
        self.data += bytes((style.text_3d, style.always_readable))
        self.data += struct.pack(
            "<IIIII",
            style.extension_offset,
            style.extension_overshoot,
            style.line_weight,
            style.arrow_type,
            style.arrow_size,
        )
        self.data += bytes((style.highlight_non_associative,))
        self.data += _encode_argb(style.highlight_non_associative_color)
        self.data += bytes((style.show_radial_diameter_prefix, style.hide_out_of_plane))
        self.data += struct.pack("<dB", style.hide_out_of_plane_value, style.hide_small)
        self.data += struct.pack("<d", style.hide_small_value)
        self.data += _encode_argb(style.color)
        self.data += _encode_argb(style.text_color)
        self.data += struct.pack("<I", style.text_position)

    def _write_text_style(self, style: TextStyle) -> None:
        self._write_entity(persistent=False)
        default_font_id = 3 if len(self.fonts) > 1 else 2
        self._write_font_id_reference(style.font_ref or default_font_id, "Text style")
        self.data += struct.pack("<II", style.arrow_type, style.line_weight)
        self.data += bytes((style.hide_out_of_plane,))
        self.data += struct.pack("<I", style.leader_type)
        self.data += bytes((style.display_leader,))
        self.data += _encode_argb(style.color)
        self.data += _encode_argb(style.screen_color)
        self._write_font_id_reference(style.screen_font_ref or default_font_id, "Screen text style")

    def _write_font_manager(self) -> None:
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", len(self.fonts))
        for font in self.fonts:
            self._write_font(font)

    def _write_font_id_reference(self, font_id: int, label: str) -> None:
        font_index = font_id - 2
        if not 0 <= font_index < len(self.fonts):
            raise ValueError(f"{label} font reference does not identify a written model font")
        self._write_font(self.fonts[font_index])

    def _write_material_manager(self) -> None:
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", len(self.model.materials))
        for material in self.model.materials:
            object_index = self._write_new_object("CMaterial", 12)
            self.material_indices[material.id] = object_index
            dictionaries = self.model.attribute_dictionaries_by_object_id.get(material.id, ())
            self._write_material(
                material,
                dictionaries=dictionaries,
            )
        self._write_reference(None)

    def _write_layer_manager(self) -> None:
        existing_default = next((layer for layer in self.model.layers if layer.name == "Layer0"), None)
        has_synthetic_default = existing_default is None
        default_layer = existing_default or Layer(name="Layer0")
        layers = [default_layer, *(layer for layer in self.model.layers if layer is not existing_default)]
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", len(layers))
        default_layer_index = 0
        for index, layer in enumerate(layers):
            object_index = self._write_new_object("CLayer", 3)
            self.layer_indices[layer.id] = object_index
            if index == 0:
                default_layer_index = object_index
            self._write_layer(layer, is_default=has_synthetic_default and index == 0)
        if self.model.active_layer_id is not None and self.model.active_layer_id not in self.layer_indices:
            raise ValueError(f"Legacy model references missing active layer ID {self.model.active_layer_id}")
        active_layer_index = self.layer_indices.get(self.model.active_layer_id or -1, default_layer_index)
        self._write_reference(active_layer_index)

    def _write_layer(self, layer: Layer, *, is_default: bool) -> None:
        dictionaries = self.model.attribute_dictionaries_by_object_id.get(layer.id, ())
        self._write_entity(persistent_id=4 if is_default else None, dictionaries=dictionaries)
        self.data += _encode_legacy_string(layer.name)
        self.data += bytes((not layer.visible,))
        display_material = layer.material or Material(
            name=f"Layer_{layer.name}",
            color=Color(255, 84, 84),
        )
        self._write_material(display_material, used_by_layer=True, persistent_id=5 if is_default else None)
        self.data += struct.pack("<I", layer.page_behavior)

    def _write_material(
        self,
        material: Material,
        *,
        used_by_layer: bool = False,
        persistent_id: int | None = None,
        dictionaries: tuple[AttributeDictionary, ...] | list[AttributeDictionary] = (),
    ) -> None:
        validate_material_export(material)
        self._write_entity(persistent_id=persistent_id, dictionaries=dictionaries)
        self.data += _encode_legacy_string(material.name)
        has_texture = material.texture is not None
        if material.has_texture and not has_texture:
            raise ValueError(f"Legacy material {material.name!r} declares a missing texture")
        self.data += bytes((has_texture,))
        if material.texture is not None:
            self._write_texture(material)
        self.data += bytes((used_by_layer,))
        self.data += bytes((material.color.r, material.color.g, material.color.b, material.color.a))
        self.data += _encode_legacy_string("")
        self.data += struct.pack("<II", 0, 0)
        use_transparency = material.alpha < 1.0
        transparency = min(max(1.0 - material.alpha, 0.0), 1.0) if use_transparency else 0.5
        self.data += struct.pack("<d", transparency)
        self.data += bytes((use_transparency,))

    def _write_definition_list(self) -> None:
        definitions = self._ordered_definitions()
        self.data += struct.pack("<I", len(definitions))
        for definition in definitions:
            self.definition_indices[definition.id] = self._write_new_object("CComponentDefinition", 11)
            self._write_definition(definition)

    def _ordered_definitions(self) -> list[ComponentDefinition]:
        definitions = {definition.id: definition for definition in self.model.definitions}
        ordered: list[ComponentDefinition] = []
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(definition_id: int) -> None:
            if definition_id in visited:
                return
            if definition_id in visiting:
                raise ValueError(f"Legacy component cycle includes definition ID {definition_id}")
            definition = definitions.get(definition_id)
            if definition is None:
                raise ValueError(f"Legacy placement references missing definition ID {definition_id}")
            visiting.add(definition_id)
            placements: list[ComponentInstance | Group | Image] = [
                *definition.entities.component_instances,
                *definition.entities.groups,
                *definition.entities.images,
            ]
            for placement in placements:
                visit(placement.definition_id)
            visiting.remove(definition_id)
            visited.add(definition_id)
            ordered.append(definition)

        for definition_id in definitions:
            visit(definition_id)
        return ordered

    def _write_definition(self, definition: ComponentDefinition) -> None:
        dictionaries = self.model.attribute_dictionaries_by_object_id.get(definition.id, ())
        self._write_entity(persistent=False, dictionaries=dictionaries)
        self._write_reference(None)
        self.data += bytes((False, True, True, False, False, False))
        self._write_reference(None)
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", 0)
        self._write_reference(None)
        self._write_entity(persistent=False)
        self.data += struct.pack("<I", 1)
        layer_index = self._write_new_object("CLayer", 3)
        self._write_layer(Layer(name="Layer0"), is_default=False)
        self._write_reference(layer_index)
        self.data += struct.pack("<I", 0)
        self.definition_entity_indices[definition.id] = self._write_entity_scope(definition.entities)
        guid = definition.guid if len(definition.guid) == 16 else bytes(16)
        self.data += guid
        self.data += _encode_legacy_string(definition.name)
        self.data += _encode_legacy_string(definition.description)
        self.data += _encode_legacy_string(definition.loaded_from)
        self.data += struct.pack("<I", definition.timestamp)
        self.data += bytes((definition.modified,))
        self.data += struct.pack("<3d", 0.0, 0.0, 0.0)
        self._write_entity(persistent=False)
        camera_flags = int(definition.behavior_always_face_camera) | (int(definition.behavior_shadows_face_sun) << 1)
        self.data += bytes((definition.behavior_snap_enabled, definition.behavior_cuts_opening))
        self.data += struct.pack("<IBI", definition.behavior_snap_mode, camera_flags, definition.behavior_no_scale_mask)
        self.data += struct.pack("<I", definition.definition_type)
        self._write_reference(None)

    def _write_entity_scope(self, entities: Entities) -> dict[int, int]:
        previous = (
            self.entities,
            self.vertices,
            self.edges,
            self.curves,
            self.vertex_indices,
            self.edge_indices,
            self.curve_indices,
            self.entity_indices,
            self.attribute_dictionaries_by_entity_id,
        )
        self.entities = entities
        self.vertices = {vertex.id: vertex for vertex in entities.vertices}
        self.edges = {edge.id: edge for edge in entities.edges}
        self.curves = {
            **{curve.id: curve for curve in entities.curves},
            **{curve.id: curve for curve in entities.arc_curves},
        }
        self.vertex_indices = {}
        self.edge_indices = {}
        self.curve_indices = {}
        self.entity_indices = {}
        self.attribute_dictionaries_by_entity_id = entities.attribute_dictionaries_by_entity_id
        super().encode()
        written_entity_indices = dict(self.entity_indices)
        (
            self.entities,
            self.vertices,
            self.edges,
            self.curves,
            self.vertex_indices,
            self.edge_indices,
            self.curve_indices,
            self.entity_indices,
            self.attribute_dictionaries_by_entity_id,
        ) = previous
        return written_entity_indices

    def _write_component_placement(
        self,
        placement: ComponentInstance | Group | Image,
        class_name: str,
        schema: int,
    ) -> None:
        self._register_entity(placement.id, self._write_new_object(class_name, schema))
        self._write_drawing_element(
            material_id=placement.material_id,
            layer_id=placement.layer_id,
            entity_id=placement.id,
        )
        definition_index = self.definition_indices.get(placement.definition_id)
        if definition_index is None:
            raise ValueError(f"Legacy placement references missing definition ID {placement.definition_id}")
        self._write_reference(definition_index)
        transform = Transform(placement.transform).to_list()
        self.data += struct.pack("<13d", *transform)
        self.data += _encode_legacy_string(placement.name or "")
        self.data += placement.guid if len(placement.guid) == 16 else bytes(16)

    def _write_texture(self, material: Material) -> None:
        texture = material.texture
        assert texture is not None
        if not texture.data:
            raise ValueError(f"Legacy material {material.name!r} texture has no embedded image data")
        self._write_entity(persistent=False)
        self._write_new_object("CDib", 3)
        self.data += struct.pack("<II", 4, len(texture.data))
        self.data += texture.data
        self.data += struct.pack("<dd", texture.x_scale, texture.y_scale)
        self.data += _encode_legacy_string(texture.filename)
        self.data += bytes((material.color.r, material.color.g, material.color.b, material.color.a))


def build_legacy_2017_model(model: Model) -> bytes:
    """Build a genuine SketchUp Make 2017 stream for root geometry."""
    validate_material_names(model.materials)
    _validate_legacy_geometry(model)
    encoder = _LegacyModelEncoder(model, model.entities)
    root = encoder.encode()
    prefix = build_legacy_2017_prefix(model, encoder.next_persistent_id)
    return prefix + root


def write_legacy_2017_model(model: Model, filepath: str | Path) -> Path:
    """Write a model as a pre-ZIP SketchUp Make 2017 file."""
    path = Path(filepath)
    encoded = build_legacy_2017_model(model)
    atomic_write(path, encoded)
    return path


def _encode_sparse_u64(value: int) -> bytes:
    mask = sum(1 << index for index in range(8) if value & (0xFF << (index * 8)))
    populated = bytes((value >> (index * 8)) & 0xFF for index in range(8) if mask & (1 << index))
    return bytes((mask,)) + populated


def _encode_legacy_string(value: str) -> bytes:
    encoded = value.encode("utf-16le")
    length = len(encoded) // 2
    if length < 0xFF:
        prefix = bytes((length,))
    elif length < 0xFFFF:
        prefix = b"\xff" + struct.pack("<H", length)
    else:
        prefix = b"\xff\xff\xff" + struct.pack("<I", length)
    return b"\xff\xfe\xff" + prefix + encoded


def _encode_argb(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("Legacy annotation style colors must fit in u32")
    return bytes(((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, (value >> 24) & 0xFF))


def _default_fonts() -> list[Font]:
    return [
        Font("Arial", point_size=12, world_size=1.0),
        Font("Tahoma", point_size=12, world_size=1.0),
    ]


def _default_dimension_style() -> DimensionStyle:
    return DimensionStyle(
        font_ref=2,
        always_readable=True,
        extension_offset=5,
        extension_overshoot=10,
        line_weight=1,
        arrow_type=3,
        arrow_size=10,
        highlight_non_associative_color=0xFFFF0000,
        show_radial_diameter_prefix=True,
        hide_out_of_plane_value=0.6,
        hide_small_value=10.0,
        color=0xFF404040,
        text_color=0,
        text_position=1,
    )


def _default_text_style(font_id: int) -> TextStyle:
    return TextStyle(font_ref=font_id, screen_font_ref=font_id, arrow_type=2, line_weight=1, leader_type=3)


def _default_styles_registry() -> StylesRegistry:
    style = StyleDescriptor(
        guid=bytes.fromhex("331be05afeed0c43bd047715611134f7"),
        display_name="Style",
        file_name="Style",
    )
    return StylesRegistry(styles=[style], active_style_ref=1)


def _encode_legacy_typed_value(entry: AttributeDictionaryEntry) -> bytes:
    if entry.value_type == 0:
        if not 0 <= entry.int_value <= 0xFFFFFFFF:
            raise ValueError("Legacy attribute integer values must fit in u32")
        return bytes((4,)) + struct.pack("<I", entry.int_value)
    if entry.value_type == 1:
        if not math.isfinite(entry.float_value):
            raise ValueError("Legacy attribute float values must be finite")
        return bytes((6,)) + struct.pack("<d", entry.float_value)
    if entry.value_type == 2:
        return bytes((7, entry.bool_value))
    if entry.value_type == 3:
        return bytes((10,)) + _encode_legacy_string(entry.string_value)
    if entry.value_type == 4:
        if entry.nested_payload is None:
            raise ValueError("Legacy nested attribute values require a payload")
        values = b"".join(bytes((2, value)) for value in entry.nested_payload)
        return bytes((11,)) + struct.pack("<I", len(entry.nested_payload)) + values
    raise ValueError(f"Unsupported legacy attribute value type: {entry.value_type}")


def _validate_legacy_geometry(model: Model) -> None:
    fonts = model.fonts or _default_fonts()
    for entities in (model.entities, *(definition.entities for definition in model.definitions)):
        _validate_annotations(entities, fonts)


def _validate_entity_scope(entities: Entities) -> None:
    vertex_ids = {vertex.id for vertex in entities.vertices}
    edge_ids = {edge.id for edge in entities.edges}
    curve_ids = {curve.id for curve in entities.curves}
    curve_ids.update(curve.id for curve in entities.arc_curves)
    for edge in entities.edges:
        if edge.start_vertex_id not in vertex_ids or edge.end_vertex_id not in vertex_ids:
            missing = edge.start_vertex_id if edge.start_vertex_id not in vertex_ids else edge.end_vertex_id
            raise ValueError(f"Legacy edge references missing vertex ID {missing}")
        if edge.curve_id is not None and edge.curve_id not in curve_ids:
            raise ValueError(f"Legacy edge references missing curve ID {edge.curve_id}")
    _validate_faces(entities, edge_ids)
    _validate_arcs(entities, edge_ids)


def _validate_annotations(entities: Entities, fonts: list[Font]) -> None:
    for text in entities.texts:
        _validate_annotation_font_id(text.font_id, fonts)
    for linear_dimension in entities.linear_dimensions:
        _validate_annotation_font_id(linear_dimension.font_id, fonts)
    for radial_dimension in entities.radial_dimensions:
        _validate_annotation_font_id(radial_dimension.font_id, fonts)
    for radial_dimension in entities.radial_dimensions:
        if radial_dimension.target_entity_id is None and radial_dimension.arc is None:
            raise ValueError("Unassociated legacy radial dimensions require embedded arc geometry")


def _validate_annotation_font_id(font_id: int | None, fonts: list[Font]) -> None:
    if font_id is not None and not 2 <= font_id < 2 + len(fonts):
        raise ValueError("Annotation font_id does not identify a written model font")


def _validate_faces(entities: Entities, edge_ids: set[int]) -> None:
    for face in entities.faces:
        for loop in (face.outer_loop, *face.inner_loops):
            if any(edge_use.edge_id not in edge_ids for edge_use in loop.edge_uses):
                missing = next(edge_use.edge_id for edge_use in loop.edge_uses if edge_use.edge_id not in edge_ids)
                raise ValueError(f"Legacy loop references missing edge ID {missing}")
            if len(loop.edge_uses) < 3:
                raise ValueError("Legacy face outer loop must contain at least three edges")
        _plane_from_loop(entities, face.outer_loop)


def _validate_arcs(entities: Entities, edge_ids: set[int]) -> None:
    for arc in entities.arc_curves:
        semantic = (arc.center, arc.normal, arc.radius, arc.start_angle, arc.end_angle)
        if arc.raw_arc_payload is not None and all(value is None for value in semantic):
            continue
        if None in (arc.center, arc.normal, arc.radius, arc.start_angle, arc.end_angle):
            raise ValueError(f"Legacy arc curve {arc.id} has incomplete geometric parameters")
        if not arc.edge_ids or arc.edge_ids[0] not in edge_ids:
            raise ValueError(f"Legacy arc curve {arc.id} has no resolvable first edge")
        assert arc.center is not None and arc.normal is not None
        first_edge = next(edge for edge in entities.edges if edge.id == arc.edge_ids[0])
        first_vertex = next(vertex for vertex in entities.vertices if vertex.id == first_edge.start_vertex_id)
        _normalized(np.asarray(arc.normal, dtype=float), "arc normal")
        _normalized(np.asarray(first_vertex.position.to_tuple()) - np.asarray(arc.center), "arc start radius")


def _vector3_values(value: tuple[float, float, float] | Vector3D) -> tuple[float, float, float]:
    return value.to_tuple() if isinstance(value, Vector3D) else value


def _uv_flags(projection: FaceUVProjection | None) -> int:
    if projection is None:
        return 0
    return 1 | (2 if projection.projection_direction is not None else 0)


def _normalized(vector: np.ndarray, label: str) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length < 1.0e-12:
        raise ValueError(f"Legacy {label} is degenerate")
    return vector / length


def _plane_from_loop(entities: Entities, loop: Loop) -> tuple[float, float, float, float]:
    edge_map = {edge.id: (edge.start_vertex_id, edge.end_vertex_id) for edge in entities.edges}
    vertex_map = {vertex.id: vertex.position for vertex in entities.vertices}
    points = [vertex_map[vertex_id] for vertex_id in loop.vertex_ids(edge_map)]
    normal = np.zeros(3)
    for current, following in zip(points, points[1:] + points[:1]):
        normal += (
            (current.y - following.y) * (current.z + following.z),
            (current.z - following.z) * (current.x + following.x),
            (current.x - following.x) * (current.y + following.y),
        )
    length = float(np.linalg.norm(normal))
    if length < 1.0e-12:
        raise ValueError("Legacy face outer loop is degenerate")
    normal /= length
    point = points[0]
    offset = -float(normal @ np.array((point.x, point.y, point.z)))
    return float(normal[0]), float(normal[1]), float(normal[2]), offset
