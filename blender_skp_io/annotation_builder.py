# SPDX-License-Identifier: MIT
"""Convert shared skppy annotation entities into Blender objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import bpy
from mathutils import Matrix, Vector

if TYPE_CHECKING:
    from .scene_builder import BlenderSceneBuilder


class BlenderAnnotationBuilder:
    """Build text and dimension objects for a :class:`BlenderSceneBuilder`."""

    def __init__(self, scene_builder: "BlenderSceneBuilder") -> None:
        self.scene = scene_builder

    def build(
        self,
        entities,
        collection: "bpy.types.Collection",
        *,
        parent_obj: Optional["bpy.types.Object"] = None,
        world_matrix: Optional[Matrix] = None,
    ) -> None:
        """Create Blender text and line objects from shared annotations."""
        for text in entities.texts:
            drawing = text.drawing
            target = self.scene._collection_for_layer(drawing.layer_id, collection)
            anchor = Vector(self.scene._xyz(text.anchor.position))
            label_position = anchor + Vector(self.scene._xyz(text.leader_vector))
            label = self._new_text_object(
                f"Text_{text.id}",
                text.text,
                text.font,
                drawing,
                label_position,
                Vector(self.scene._xyz(text.view_direction)),
                target,
                parent_obj,
                world_matrix,
            )
            label["skppy_annotation_type"] = "text"
            label["skppy_screen_position"] = (
                text.screen_position.x,
                text.screen_position.y,
            )
            label["skppy_leader_type"] = text.leader_type
            label["skppy_arrow_type"] = text.arrow_type
            if text.display_leader and (label_position - anchor).length_squared > 0.0:
                self._new_line_object(
                    f"TextLeader_{text.id}",
                    ((anchor, label_position),),
                    drawing,
                    target,
                    parent_obj,
                    world_matrix,
                )

        for dimension in entities.linear_dimensions:
            self._build_linear_dimension(
                dimension,
                collection,
                parent_obj,
                world_matrix,
            )

        for dimension in entities.radial_dimensions:
            self._build_radial_dimension(
                dimension,
                entities,
                collection,
                parent_obj,
                world_matrix,
            )

    def _build_linear_dimension(
        self,
        dimension,
        collection: "bpy.types.Collection",
        parent_obj: Optional["bpy.types.Object"],
        world_matrix: Optional[Matrix],
    ) -> None:
        """Create one linear dimension from its model-space construction data."""
        drawing = dimension.drawing
        target = self.scene._collection_for_layer(drawing.layer_id, collection)
        start = Vector(self.scene._xyz(dimension.start.position))
        end = Vector(self.scene._xyz(dimension.end.position))
        x_axis = Vector(self.scene._xyz(dimension.render_direction))
        if x_axis.length_squared == 0.0:
            x_axis = end - start
        if x_axis.length_squared == 0.0:
            x_axis = Vector((1.0, 0.0, 0.0))
        x_axis.normalize()

        normal = Vector(self.scene._xyz(dimension.direction))
        if normal.length_squared == 0.0:
            normal = Vector((0.0, 0.0, 1.0))
        normal.normalize()
        offset_axis = normal.cross(x_axis)
        if offset_axis.length_squared == 0.0:
            offset_axis = x_axis.orthogonal()
        offset_axis.normalize()

        line_start = start + offset_axis * dimension.offset
        line_end = end + offset_axis * dimension.offset
        self._new_line_object(
            f"LinearDimension_{dimension.id}:lines",
            ((start, line_start), (line_start, line_end), (end, line_end)),
            drawing,
            target,
            parent_obj,
            world_matrix,
        )

        text_position = line_start + x_axis * dimension.line_position
        if dimension.line_position == 0.0:
            text_position = (line_start + line_end) * 0.5
        label = self._new_text_object(
            f"LinearDimension_{dimension.id}:text",
            dimension.text or f"{(end - start).length:g}",
            dimension.font,
            drawing,
            text_position,
            normal,
            target,
            parent_obj,
            world_matrix,
        )
        label["skppy_annotation_type"] = "linear_dimension"
        label["skppy_dimension_mode"] = dimension.mode
        label["skppy_arrow_type"] = dimension.arrow_type
        label["skppy_alignment"] = dimension.alignment

    def _build_radial_dimension(
        self,
        dimension,
        entities,
        collection: "bpy.types.Collection",
        parent_obj: Optional["bpy.types.Object"],
        world_matrix: Optional[Matrix],
    ) -> None:
        """Create a radial label and the geometry recoverable from its payload."""
        drawing = dimension.drawing
        target = self.scene._collection_for_layer(drawing.layer_id, collection)
        center, anchor, normal = self._radial_dimension_points(dimension, entities)
        if center is not None and anchor is not None:
            self._new_line_object(
                f"RadialDimension_{dimension.id}:lines",
                ((center, anchor),),
                drawing,
                target,
                parent_obj,
                world_matrix,
            )
        position = anchor if anchor is not None else center if center is not None else Vector((0.0, 0.0, 0.0))
        label = self._new_text_object(
            f"RadialDimension_{dimension.id}:text",
            dimension.text or ("Diameter" if dimension.is_diameter else "Radius"),
            dimension.font,
            drawing,
            position,
            normal,
            target,
            parent_obj,
            world_matrix,
        )
        label["skppy_annotation_type"] = "radial_dimension"
        label["skppy_parameter"] = dimension.parameter
        label["skppy_radius_ratio"] = dimension.radius_ratio
        label["skppy_is_diameter"] = dimension.is_diameter
        label["skppy_arrow_type"] = dimension.arrow_type

    def _radial_dimension_points(self, dimension, entities):
        """Return the best available center, anchor, and normal for a radial label."""
        if dimension.arc is not None:
            center = Vector(self.scene._xyz(dimension.arc.center))
            normal = Vector(self.scene._xyz(dimension.arc.normal))
            x_axis = Vector(self.scene._xyz(dimension.arc.x_axis))
            if x_axis.length_squared == 0.0:
                x_axis = Vector((1.0, 0.0, 0.0))
            x_axis.normalize()
            return center, center + x_axis * dimension.radius_ratio, normal

        edge = next(
            (edge for edge in entities.edges if edge.id == dimension.target_entity_id),
            None,
        )
        if edge is not None:
            vertices = {vertex.id: vertex for vertex in entities.vertices}
            start = vertices.get(edge.start_vertex_id)
            end = vertices.get(edge.end_vertex_id)
            if start is not None and end is not None:
                start_point = Vector(self.scene._xyz(start.position))
                end_point = Vector(self.scene._xyz(end.position))
                anchor = start_point.lerp(end_point, dimension.parameter)
                return None, anchor, Vector((0.0, 0.0, 1.0))
        return None, None, Vector((0.0, 0.0, 1.0))

    def _new_text_object(
        self,
        name: str,
        body: str,
        font,
        drawing,
        position: Vector,
        normal: Vector,
        collection: "bpy.types.Collection",
        parent_obj: Optional["bpy.types.Object"],
        world_matrix: Optional[Matrix],
    ) -> "bpy.types.Object":
        """Create and place a Blender Font object for one annotation label."""
        curve = bpy.data.curves.new(name, type="FONT")
        curve.body = body
        curve.align_x = "CENTER"
        curve.align_y = "CENTER"
        curve.size = self._font_size(font)
        self._assign_material(curve, drawing)
        obj = bpy.data.objects.new(name, curve)
        self._apply_visibility(obj, drawing)
        obj["skppy_font_face"] = font.face_name if font is not None else ""
        local = self._oriented_matrix(position, normal)
        self.scene._place_auxiliary(obj, parent_obj, local, world_matrix)
        collection.objects.link(obj)
        self.scene.created_objects.append(obj)
        return obj

    def _new_line_object(
        self,
        name: str,
        segments,
        drawing,
        collection: "bpy.types.Collection",
        parent_obj: Optional["bpy.types.Object"],
        world_matrix: Optional[Matrix],
    ) -> "bpy.types.Object":
        """Create a lightweight mesh containing independent annotation segments."""
        vertices: list[tuple[float, float, float]] = []
        edges: list[tuple[int, int]] = []
        for start, end in segments:
            index = len(vertices)
            vertices.extend(
                (
                    tuple(component * self.scene.scale for component in start),
                    tuple(component * self.scene.scale for component in end),
                )
            )
            edges.append((index, index + 1))
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, edges, [])
        mesh.update()
        self._assign_material(mesh, drawing)
        obj = bpy.data.objects.new(name, mesh)
        self._apply_visibility(obj, drawing)
        self.scene._place_auxiliary(obj, parent_obj, Matrix.Identity(4), world_matrix)
        collection.objects.link(obj)
        self.scene.created_objects.append(obj)
        return obj

    def _font_size(self, font) -> float:
        """Convert world or point font size to Blender scene units."""
        if font is not None and font.use_world_size and font.world_size > 0.0:
            return font.world_size * self.scene.scale
        point_size = font.point_size if font is not None and font.point_size > 0 else 12
        return point_size / 72.0 * self.scene.scale

    def _assign_material(self, data, drawing) -> None:
        """Attach the source drawing material when material import is enabled."""
        material = self.scene._bl_materials.get(drawing.material_id)
        if material is not None:
            data.materials.append(material)

    @staticmethod
    def _apply_visibility(obj: "bpy.types.Object", drawing) -> None:
        """Apply the source hidden state without overriding layer visibility."""
        obj.hide_viewport = drawing.hidden
        obj.hide_render = drawing.hidden

    def _oriented_matrix(self, position: Vector, normal: Vector) -> Matrix:
        """Place an annotation in its model plane using local Z as the normal."""
        if normal.length_squared == 0.0:
            normal = Vector((0.0, 0.0, 1.0))
        normal.normalize()
        matrix = normal.to_track_quat("Z", "Y").to_matrix().to_4x4()
        matrix.translation = position * self.scene.scale
        return matrix
