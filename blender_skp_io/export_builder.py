# SPDX-License-Identifier: MIT
"""Convert Blender scene data into the public :mod:`skppy` model graph."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import skppy
from .skppy.coplanar import CoplanarRegion, PolygonBoundary, merge_coplanar_polygons

_GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "META"}
_SAFE_NAME = re.compile(r"[^\w .()-]+", re.UNICODE)
_EDGE_FLAG_HIDDEN = 0x01
_EDGE_FLAG_SOFT = 0x02
_EDGE_FLAG_SMOOTH = 0x04


class BlenderModelBuilder:
    """Build a modern-writable :class:`skppy.Model` from a Blender scene."""

    def __init__(
        self,
        context: Any,
        *,
        export_scope: str = "VISIBLE",
        inches_per_unit: float = 39.37007874015748,
        apply_modifiers: bool = True,
        export_materials: bool = True,
        export_textures: bool = True,
        export_uvs: bool = True,
        export_layers: bool = True,
        export_cameras: bool = True,
        export_text: bool = True,
        export_custom_properties: bool = True,
        merge_coplanar_faces: bool = True,
    ) -> None:
        self.context = context
        self.export_scope = export_scope
        self.inches_per_unit = inches_per_unit
        self.apply_modifiers = apply_modifiers
        self.export_materials = export_materials
        self.export_textures = export_textures
        self.export_uvs = export_uvs
        self.export_layers = export_layers
        self.export_cameras = export_cameras
        self.export_text = export_text
        self.export_custom_properties = export_custom_properties
        self.merge_coplanar_faces = merge_coplanar_faces
        self.model = skppy.Model.new()
        self.warnings: list[str] = []
        self.exported_objects = 0
        self.ignored_objects = 0

        self._material_map: dict[int, skppy.Material] = {}
        self._layer_map: dict[str, skppy.Layer] = {}
        self._definition_map: dict[tuple[Any, ...], skppy.ComponentDefinition] = {}
        self._collection_definitions: dict[int, skppy.ComponentDefinition] = {}
        self._collection_object_matrices: dict[int, Matrix] = {}
        self._definition_names: set[str] = set()
        self._material_names: set[str] = set()

    def build(self) -> skppy.Model:
        """Convert the configured Blender object scope into a writable model."""
        if not math.isfinite(self.inches_per_unit) or self.inches_per_unit <= 0.0:
            raise ValueError("Inches per Blender unit must be positive and finite")

        objects = list(self._objects_to_export())
        if self.export_layers:
            for obj in objects:
                self._layer_for_object(obj)
        if self.export_materials:
            self._build_materials(objects)

        for obj in objects:
            self._export_object(obj)

        if self.export_cameras:
            self._export_cameras(objects)
        return self.model

    def _export_object(self, obj: Any) -> None:
        """Dispatch one Blender object into its public model representation."""
        if obj.type in _GEOMETRY_TYPES:
            self._export_geometry_object(obj, self.model.entities)
        elif obj.type == "FONT" and self.export_text:
            self._export_text_object(obj, self.model.entities)
        elif obj.type == "EMPTY" and getattr(obj, "instance_collection", None):
            self._export_collection_instance(obj, self.model.entities, set())
        elif obj.type != "CAMERA":
            self.ignored_objects += 1

    def _objects_to_export(self) -> Iterable[Any]:
        scene_objects = list(self.context.scene.objects)
        if self.export_scope == "SELECTED":
            return list(self.context.selected_objects)
        if self.export_scope == "SCENE":
            return scene_objects
        if self.export_scope != "VISIBLE":
            raise ValueError(f"Unknown export scope: {self.export_scope}")
        return [
            obj for obj in scene_objects if obj.visible_get(view_layer=self.context.view_layer) and not obj.hide_render
        ]

    def _build_materials(self, objects: Iterable[Any]) -> None:
        for obj in objects:
            for material in self._object_materials(obj):
                self._material_for(material)

    def _object_materials(self, obj: Any) -> Iterable[Any]:
        """Yield non-null materials reachable from an export object."""
        for slot in getattr(obj, "material_slots", ()):
            if slot.material is not None:
                yield slot.material
        if obj.type == "FONT" and getattr(obj.data, "materials", None):
            yield from (material for material in obj.data.materials if material is not None)
        if obj.type == "EMPTY" and getattr(obj, "instance_collection", None):
            for member in self._collection_objects(obj.instance_collection):
                for slot in getattr(member, "material_slots", ()):
                    if slot.material is not None:
                        yield slot.material

    def _material_for(self, material: Any) -> skppy.Material:
        key = material.as_pointer()
        if key in self._material_map:
            return self._material_map[key]

        name = self._unique_name(material.name or "Material", self._material_names)
        skp_material = self.model.add_material(name)
        base_color, metallic, roughness, alpha, image = self._material_state(material)
        skp_material.color = skppy.Color(*(self._channel(value) for value in base_color[:3]))
        skp_material.alpha = min(max(float(alpha), 0.0), 1.0)
        skp_material.metallic = min(max(float(metallic), 0.0), 1.0)
        skp_material.roughness = min(max(float(roughness), 0.0), 1.0)
        if self.export_textures and image is not None:
            image_data = self._image_bytes(image)
            if image_data is not None:
                filename = self._safe_filename(image)
                skp_material.has_texture = True
                skp_material.texture = skppy.Texture(
                    filename=filename,
                    x_scale=self._positive_custom(material, "skppy_x_scale", 1.0),
                    y_scale=self._positive_custom(material, "skppy_y_scale", 1.0),
                    data=image_data,
                )
            else:
                self.warnings.append(f"Material {material.name!r}: linked image bytes are unavailable")
        self._material_map[key] = skp_material
        return skp_material

    def _material_state(
        self, material: Any
    ) -> tuple[tuple[float, float, float, float], float, float, float, Any | None]:
        diffuse = tuple(material.diffuse_color)
        base_color = diffuse
        metallic = float(getattr(material, "metallic", 0.0))
        roughness = float(getattr(material, "roughness", 1.0))
        alpha = float(diffuse[3])
        image = None
        if material.use_nodes and material.node_tree is not None:
            bsdf = material.node_tree.nodes.get("Principled BSDF")
            if bsdf is not None:
                self._warn_material_loss(material, bsdf)
                base = bsdf.inputs.get("Base Color")
                alpha_input = bsdf.inputs.get("Alpha")
                metallic_input = bsdf.inputs.get("Metallic")
                roughness_input = bsdf.inputs.get("Roughness")
                if base is not None:
                    base_color = tuple(base.default_value)
                    image = self._linked_image(base)
                if alpha_input is not None:
                    alpha = float(alpha_input.default_value)
                if metallic_input is not None:
                    metallic = float(metallic_input.default_value)
                if roughness_input is not None:
                    roughness = float(roughness_input.default_value)
        return base_color, metallic, roughness, alpha, image

    def _warn_material_loss(self, material: Any, bsdf: Any) -> None:
        """Make unsupported renderer conversion visible in export reports."""
        omitted = self._texture_graph_losses(material)
        base = bsdf.inputs.get("Base Color")
        if base is not None and base.is_linked and base.links[0].from_node.type != "TEX_IMAGE":
            omitted.append("base-color node graph")
        for name in ("Metallic", "Roughness", "Normal"):
            socket = bsdf.inputs.get(name)
            if socket is not None and socket.is_linked:
                omitted.append(f"{name} map")
        for name, default in (
            ("IOR", 1.5),
            ("IOR Level", 0.5),
            ("Specular IOR Level", 0.5),
            ("Transmission Weight", 0.0),
        ):
            socket = bsdf.inputs.get(name)
            if socket is not None and (socket.is_linked or abs(socket.default_value - default) > 1e-6):
                omitted.append(name)
        emission = bsdf.inputs.get("Emission Color")
        strength = bsdf.inputs.get("Emission Strength")
        if (
            emission is not None
            and strength is not None
            and (
                emission.is_linked or strength.is_linked or (strength.default_value and any(emission.default_value[:3]))
            )
        ):
            omitted.append("emission")
        for node in material.node_tree.nodes:
            if node.type == "OUTPUT_MATERIAL" and node.inputs["Displacement"].is_linked:
                omitted.append("displacement")
                break
        if omitted:
            self.warnings.append(f"Material {material.name!r}: export omits {', '.join(omitted)}")

    @staticmethod
    def _texture_graph_losses(material: Any) -> list[str]:
        """Notice opacity graphs and UV adjustments which are not baked on export."""
        losses = []
        bsdf = material.node_tree.nodes["Principled BSDF"]
        alpha = bsdf.inputs["Alpha"]
        if alpha.is_linked and alpha.links[0].from_node.type != "TEX_IMAGE":
            losses.append("opacity node graph")
        for node in material.node_tree.nodes:
            if node.type != "TEX_IMAGE":
                continue
            vector = node.inputs["Vector"]
            if vector.is_linked and vector.links[0].from_node.type not in {"TEX_COORD", "UVMAP"}:
                return [*losses, "texture mapping"]
        return losses

    def _linked_image(self, socket: Any, visited: set[int] | None = None) -> Any | None:
        visited = visited or set()
        for link in socket.links:
            node = link.from_node
            pointer = node.as_pointer()
            if pointer in visited:
                continue
            visited.add(pointer)
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                return node.image
            for node_input in node.inputs:
                image = self._linked_image(node_input, visited)
                if image is not None:
                    return image
        return None

    def _image_bytes(self, image: Any) -> bytes | None:
        if image.packed_file is not None:
            return bytes(image.packed_file.data)
        filepath = bpy.path.abspath(image.filepath, library=image.library)
        if filepath and Path(filepath).is_file():
            return Path(filepath).read_bytes()
        return None

    def _safe_filename(self, image: Any) -> str:
        source = os.path.basename(image.filepath) or image.name or "texture.png"
        name = self._clean_name(source, "texture.png")
        if "." not in name:
            name += ".png"
        return name

    def _layer_for_object(self, obj: Any) -> skppy.Layer | None:
        if not self.export_layers:
            return None
        explicit = obj.get("skppy_layer_name")
        if isinstance(explicit, str) and explicit.strip():
            name = explicit.strip()
        else:
            collections = [
                collection.name for collection in obj.users_collection if collection != self.context.scene.collection
            ]
            name = collections[0] if collections else "Untagged"
        if name not in self._layer_map:
            layer = self.model.add_layer(name, visible=not obj.hide_viewport)
            self._layer_map[name] = layer
        return self._layer_map[name]

    def _export_geometry_object(self, obj: Any, target: skppy.Entities) -> None:
        definition = self._definition_for_object(obj)
        instance = target.add_instance(
            definition,
            self._transform(obj.matrix_world),
            name=obj.name,
        )
        layer = self._layer_for_object(obj)
        instance.layer_id = layer.id if layer is not None else None
        self._attach_custom_properties(target, instance.id, obj)
        self.exported_objects += 1

    def _definition_for_object(self, obj: Any) -> skppy.ComponentDefinition:
        material_key = tuple(
            slot.material.as_pointer() if slot.material is not None else 0
            for slot in getattr(obj, "material_slots", ())
        )
        if self.apply_modifiers and len(obj.modifiers):
            key: tuple[Any, ...] = ("evaluated", obj.as_pointer(), material_key)
        else:
            data_pointer = obj.data.as_pointer() if obj.data is not None else obj.as_pointer()
            key = ("data", data_pointer, material_key, obj.type)
        if key in self._definition_map:
            return self._definition_map[key]

        definition = self.model.add_definition(
            self._unique_name(
                obj.data.name if obj.data is not None else obj.name,
                self._definition_names,
            )
        )
        self._definition_map[key] = definition
        mesh, owner = self._mesh_for_object(obj)
        try:
            self._populate_mesh(definition.entities, mesh, obj)
        finally:
            if owner is not None:
                owner.to_mesh_clear()
        return definition

    def _mesh_for_object(self, obj: Any) -> tuple[Any, Any | None]:
        if obj.type == "MESH" and not self.apply_modifiers:
            return obj.data, None
        evaluated = obj.evaluated_get(self.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh(
            preserve_all_data_layers=True,
            depsgraph=self.context.evaluated_depsgraph_get(),
        )
        if mesh is None:
            raise ValueError(f"Object {obj.name!r} could not be converted to a mesh")
        return mesh, evaluated

    def _populate_mesh(self, entities: skppy.Entities, mesh: Any, obj: Any) -> None:
        vertex_map = {
            vertex.index: entities.add_vertex(
                vertex.co.x * self.inches_per_unit,
                vertex.co.y * self.inches_per_unit,
                vertex.co.z * self.inches_per_unit,
            )
            for vertex in mesh.vertices
        }
        if self.merge_coplanar_faces:
            self._populate_merged_mesh(entities, mesh, obj, vertex_map)
            return

        smooth_edges = self._smooth_edge_indices(mesh)
        edge_map: dict[int, skppy.Edge] = {}
        for edge in mesh.edges:
            start, end = edge.vertices
            if start == end:
                self.warnings.append(f"Object {obj.name!r}: ignored degenerate edge")
                continue
            skp_edge = entities.add_edge(vertex_map[start], vertex_map[end])
            flags = _EDGE_FLAG_HIDDEN if getattr(edge, "hide", False) else 0
            if edge.index in smooth_edges:
                flags |= _EDGE_FLAG_SOFT | _EDGE_FLAG_SMOOTH
            skp_edge.flags = flags
            edge_map[edge.index] = skp_edge

        uv_data = self._mesh_uv_data(mesh)
        for polygon in mesh.polygons:
            self._populate_polygon(entities, mesh, obj, polygon, vertex_map, edge_map, uv_data)

    def _populate_merged_mesh(
        self,
        entities: skppy.Entities,
        mesh: Any,
        obj: Any,
        vertex_map: dict[int, skppy.Vertex],
    ) -> None:
        """Merge compatible coplanar polygons and emit only retained edges."""
        uv_data = self._mesh_uv_data(mesh)
        projections: dict[int, skppy.FaceUVProjection] = {}
        boundaries, positions = self._coplanar_boundaries(mesh, obj, uv_data, projections)
        regions = merge_coplanar_polygons(boundaries, positions)
        edge_map = self._merged_edge_map(entities, mesh, obj, vertex_map, boundaries, regions)
        polygon_by_index = {polygon.index: polygon for polygon in mesh.polygons}
        for region in regions:
            self._populate_region(entities, mesh, obj, region, polygon_by_index, vertex_map, edge_map, projections)

    def _mesh_uv_data(self, mesh: Any) -> Any | None:
        """Return the active UV data when texture-coordinate export is enabled."""
        if not self.export_uvs:
            return None
        layer = mesh.uv_layers.active
        return layer.data if layer is not None else None

    def _coplanar_boundaries(
        self,
        mesh: Any,
        obj: Any,
        uv_data: Any | None,
        projections: dict[int, skppy.FaceUVProjection],
    ) -> tuple[list[PolygonBoundary], dict[int, tuple[float, float, float]]]:
        """Collect valid polygon planes and appearance compatibility keys."""
        boundaries: list[PolygonBoundary] = []
        positions = {
            vertex.index: tuple(float(value) * self.inches_per_unit for value in vertex.co) for vertex in mesh.vertices
        }
        for polygon in mesh.polygons:
            if len(polygon.loop_indices) < 3:
                self.warnings.append(f"Object {obj.name!r}: ignored degenerate polygon")
                continue
            normal = Vector(polygon.normal)
            if normal.length_squared == 0.0:
                self.warnings.append(f"Object {obj.name!r}: ignored zero-area polygon")
                continue
            normal.normalize()
            point = mesh.vertices[polygon.vertices[0]].co * self.inches_per_unit
            material_id = self._polygon_material_id(obj, polygon.material_index)
            projection_key = None
            if uv_data is not None and material_id is not None:
                projection = self._face_uv_projection(mesh, polygon, uv_data, normal, material_id)
                projections[polygon.index] = projection
                projection_key = tuple(round(value, 8) for value in projection.transform)
            boundaries.append(
                PolygonBoundary(
                    polygon.index,
                    tuple(polygon.vertices),
                    tuple(mesh.loops[index].edge_index for index in polygon.loop_indices),
                    tuple(float(value) for value in normal),
                    -float(normal.dot(point)),
                    polygon.material_index,
                    projection_key,
                )
            )
        return boundaries, positions

    def _merged_edge_map(
        self,
        entities: skppy.Entities,
        mesh: Any,
        obj: Any,
        vertex_map: dict[int, skppy.Vertex],
        boundaries: list[PolygonBoundary],
        regions: list[CoplanarRegion],
    ) -> dict[int, skppy.Edge]:
        """Create mesh edges except internal edges removed by region merging."""
        internal_edges: set[int] = set()
        boundary_by_polygon = {boundary.index: boundary for boundary in boundaries}
        for region in regions:
            occurrences: dict[int, int] = {}
            for polygon_index in region.polygons:
                for edge_index in boundary_by_polygon[polygon_index].edges:
                    occurrences[edge_index] = occurrences.get(edge_index, 0) + 1
            internal_edges.update(edge_index for edge_index, count in occurrences.items() if count > 1)

        smooth_edges = self._smooth_edge_indices(mesh)
        edge_map: dict[int, skppy.Edge] = {}
        for edge in mesh.edges:
            if edge.index in internal_edges:
                continue
            start, end = edge.vertices
            if start == end:
                self.warnings.append(f"Object {obj.name!r}: ignored degenerate edge")
                continue
            skp_edge = entities.add_edge(vertex_map[start], vertex_map[end])
            flags = _EDGE_FLAG_HIDDEN if getattr(edge, "hide", False) else 0
            if edge.index in smooth_edges:
                flags |= _EDGE_FLAG_SOFT | _EDGE_FLAG_SMOOTH
            skp_edge.flags = flags
            edge_map[edge.index] = skp_edge
        return edge_map

    def _populate_region(
        self,
        entities: skppy.Entities,
        mesh: Any,
        obj: Any,
        region: CoplanarRegion,
        polygon_by_index: dict[int, Any],
        vertex_map: dict[int, skppy.Vertex],
        edge_map: dict[int, skppy.Edge],
        projections: dict[int, skppy.FaceUVProjection],
    ) -> None:
        """Convert one merged region and all of its boundary cycles to a face."""
        polygon = polygon_by_index[region.polygons[0]]
        normal = Vector(polygon.normal).normalized()
        point = mesh.vertices[polygon.vertices[0]].co * self.inches_per_unit
        loops = [
            skppy.Loop(
                edge_uses=[
                    skppy.EdgeUse(
                        edge_map[boundary.edge_index].id,
                        not (
                            edge_map[boundary.edge_index].start_vertex_id == vertex_map[boundary.start_vertex].id
                            and edge_map[boundary.edge_index].end_vertex_id == vertex_map[boundary.end_vertex].id
                        ),
                    )
                    for boundary in boundary_loop
                ],
                is_outer=loop_index == 0,
            )
            for loop_index, boundary_loop in enumerate(region.loops)
        ]
        face = skppy.Face(
            id=entities._alloc_id(),
            plane=(normal.x, normal.y, normal.z, -normal.dot(point)),
            outer_loop=loops[0],
            inner_loops=loops[1:],
            front_material_id=self._polygon_material_id(obj, polygon.material_index),
        )
        face.front_uv = projections.get(polygon.index)
        entities.faces.append(face)

    def _populate_polygon(
        self,
        entities: skppy.Entities,
        mesh: Any,
        obj: Any,
        polygon: Any,
        vertex_map: dict[int, skppy.Vertex],
        edge_map: dict[int, skppy.Edge],
        uv_data: Any | None,
    ) -> None:
        """Convert one Blender polygon into one directed SKP face loop."""
        if len(polygon.loop_indices) < 3:
            self.warnings.append(f"Object {obj.name!r}: ignored degenerate polygon")
            return
        edge_uses = self._polygon_edge_uses(mesh, polygon, vertex_map, edge_map)
        if edge_uses is None:
            self.warnings.append(f"Object {obj.name!r}: polygon references an invalid edge")
            return
        normal = Vector(polygon.normal)
        if normal.length_squared == 0.0:
            self.warnings.append(f"Object {obj.name!r}: ignored zero-area polygon")
            return
        normal.normalize()
        point = mesh.vertices[polygon.vertices[0]].co * self.inches_per_unit
        material_id = self._polygon_material_id(obj, polygon.material_index)
        face = skppy.Face(
            id=entities._alloc_id(),
            plane=(normal.x, normal.y, normal.z, -normal.dot(point)),
            outer_loop=skppy.Loop(edge_uses=edge_uses, is_outer=True),
            inner_loops=[],
            front_material_id=material_id,
        )
        if uv_data is not None and material_id is not None:
            face.front_uv = self._face_uv_projection(mesh, polygon, uv_data, normal, material_id)
        entities.faces.append(face)

    @staticmethod
    def _polygon_edge_uses(
        mesh: Any,
        polygon: Any,
        vertex_map: dict[int, skppy.Vertex],
        edge_map: dict[int, skppy.Edge],
    ) -> list[skppy.EdgeUse] | None:
        """Resolve polygon loops to directed references into the edge table."""
        edge_uses: list[skppy.EdgeUse] = []
        loops = list(polygon.loop_indices)
        for offset, loop_index in enumerate(loops):
            loop = mesh.loops[loop_index]
            skp_edge = edge_map.get(loop.edge_index)
            if skp_edge is None:
                return None
            start_id = vertex_map[loop.vertex_index].id
            next_loop = mesh.loops[loops[(offset + 1) % len(loops)]]
            end_id = vertex_map[next_loop.vertex_index].id
            reversed_edge = not (skp_edge.start_vertex_id == start_id and skp_edge.end_vertex_id == end_id)
            edge_uses.append(skppy.EdgeUse(skp_edge.id, reversed_edge))
        return edge_uses

    def _smooth_edge_indices(self, mesh: Any) -> set[int]:
        adjacent_faces: dict[int, list[bool]] = {edge.index: [] for edge in mesh.edges}
        for polygon in mesh.polygons:
            for loop_index in polygon.loop_indices:
                adjacent_faces[mesh.loops[loop_index].edge_index].append(polygon.use_smooth)
        return {
            edge.index
            for edge in mesh.edges
            if len(adjacent_faces[edge.index]) == 2
            and all(adjacent_faces[edge.index])
            and not getattr(edge, "use_edge_sharp", False)
        }

    def _polygon_material_id(self, obj: Any, index: int) -> int | None:
        if not self.export_materials or index >= len(obj.material_slots):
            return None
        material = obj.material_slots[index].material
        if material is None:
            return None
        return self._material_for(material).id

    def _face_uv_projection(
        self,
        mesh: Any,
        polygon: Any,
        uv_data: Any,
        normal: Vector,
        material_id: int,
    ) -> skppy.FaceUVProjection:
        positions = [
            tuple(mesh.vertices[mesh.loops[index].vertex_index].co * self.inches_per_unit)
            for index in polygon.loop_indices
        ]
        projected = self._project_points(positions, normal)
        normalized_uvs = np.asarray([tuple(uv_data[index].uv) for index in polygon.loop_indices])
        material = next(value for value in self.model.materials if value.id == material_id)
        texture_scale = (
            np.asarray((material.texture.x_scale, material.texture.y_scale))
            if material.texture is not None
            else np.ones(2)
        )
        uvs = normalized_uvs * texture_scale
        coordinates = np.column_stack((projected, np.ones(len(projected))))
        coefficients, *_ = np.linalg.lstsq(coordinates, uvs, rcond=None)
        mapping = np.column_stack((coefficients, np.array((0.0, 0.0, 1.0))))
        try:
            transform = np.linalg.inv(mapping)
        except np.linalg.LinAlgError:
            transform = np.eye(3)
            self.warnings.append("Singular UV mapping replaced by identity projection")
        fitted = coordinates @ mapping
        if np.max(np.abs(fitted[:, :2] - uvs)) > 1.0e-5:
            self.warnings.append("Non-affine polygon UVs were approximated")
        pins = [
            skppy.UVPin(
                texture_position=skppy.Vector2D(float(uv[0]), float(uv[1])),
                model_position=skppy.Vector2D(float(point[0]), float(point[1])),
            )
            for point, uv in zip(projected[:4], uvs[:4])
        ]
        return skppy.FaceUVProjection(
            transform=[float(value) for value in transform.ravel()],
            origin=positions[0],
            pins=pins,
        )

    @staticmethod
    def _project_points(positions: list[tuple[float, float, float]], normal: Vector) -> np.ndarray:
        points = np.asarray(positions, dtype=float)
        tangent = Vector((-normal.y, normal.x, 0.0))
        if tangent.length_squared < 1.0e-12:
            return points[:, :2]
        tangent.normalize()
        bitangent = Vector(
            (
                -normal.z * tangent.y,
                normal.z * tangent.x,
                normal.x * tangent.y - normal.y * tangent.x,
            )
        )
        return np.column_stack((points @ np.asarray(tuple(tangent)), points @ np.asarray(tuple(bitangent))))

    def _export_collection_instance(self, obj: Any, target: skppy.Entities, stack: set[int]) -> None:
        definition = self._collection_definition(obj.instance_collection, stack)
        instance = target.add_instance(definition, self._transform(obj.matrix_world), obj.name)
        layer = self._layer_for_object(obj)
        instance.layer_id = layer.id if layer is not None else None
        self._attach_custom_properties(target, instance.id, obj)
        self.exported_objects += 1

    def _collection_definition(self, collection: Any, stack: set[int]) -> skppy.ComponentDefinition:
        pointer = collection.as_pointer()
        if pointer in stack:
            raise ValueError(f"Collection instance cycle at {collection.name!r}")
        if pointer in self._collection_definitions:
            return self._collection_definitions[pointer]
        stack = {*stack, pointer}
        definition_name = self._unique_name(collection.name, self._definition_names)
        members = list(self._collection_objects(collection))
        child_definitions: dict[int, skppy.ComponentDefinition] = {}
        for member in members:
            if member.type in _GEOMETRY_TYPES:
                child_definitions[member.as_pointer()] = self._definition_for_object(member)
            elif member.type == "EMPTY" and getattr(member, "instance_collection", None):
                child_definitions[member.as_pointer()] = self._collection_definition(member.instance_collection, stack)

        definition = self.model.add_definition(definition_name)
        self._collection_definitions[pointer] = definition
        collection_offset = Matrix.Translation(-Vector(collection.instance_offset))
        for member in members:
            local_matrix = collection_offset @ self._collection_object_matrix(member)
            if member.type in _GEOMETRY_TYPES:
                instance = definition.entities.add_instance(
                    child_definitions[member.as_pointer()], self._transform(local_matrix), member.name
                )
                layer = self._layer_for_object(member)
                instance.layer_id = layer.id if layer is not None else None
                self._attach_custom_properties(definition.entities, instance.id, member)
            elif member.type == "FONT" and self.export_text:
                self._export_text_object(member, definition.entities, local_matrix)
            elif member.type == "EMPTY" and getattr(member, "instance_collection", None):
                definition.entities.add_instance(
                    child_definitions[member.as_pointer()], self._transform(local_matrix), member.name
                )
        return definition

    def _collection_objects(self, collection: Any) -> Iterable[Any]:
        """Yield each object in a collection hierarchy exactly once."""
        seen_collections: set[int] = set()
        seen_objects: set[int] = set()

        def walk(current: Any) -> Iterable[Any]:
            collection_pointer = current.as_pointer()
            if collection_pointer in seen_collections:
                return
            seen_collections.add(collection_pointer)
            for obj in current.objects:
                object_pointer = obj.as_pointer()
                if object_pointer not in seen_objects:
                    seen_objects.add(object_pointer)
                    yield obj
            for child in current.children:
                yield from walk(child)

        yield from walk(collection)

    def _collection_object_matrix(self, obj: Any, stack: set[int] | None = None) -> Matrix:
        """Return a source object's transform even when its collection is not evaluated."""
        pointer = obj.as_pointer()
        if pointer in self._collection_object_matrices:
            return self._collection_object_matrices[pointer].copy()
        stack = stack or set()
        if pointer in stack:
            raise ValueError(f"Object parent cycle at {obj.name!r}")
        parent = getattr(obj, "parent", None)
        matrix = obj.matrix_parent_inverse @ obj.matrix_basis
        if parent is not None:
            matrix = self._collection_object_matrix(parent, {*stack, pointer}) @ matrix
        self._collection_object_matrices[pointer] = matrix.copy()
        return matrix

    def _export_text_object(self, obj: Any, target: skppy.Entities, matrix: Matrix | None = None) -> None:
        if matrix is None:
            matrix = obj.matrix_world
        position = matrix.translation * self.inches_per_unit
        direction = matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))
        material_id = None
        if self.export_materials and obj.data.materials:
            material = obj.data.materials[0]
            if material is not None:
                material_id = self._material_for(material).id
        layer = self._layer_for_object(obj)
        text = skppy.Text(
            id=target._alloc_id(),
            text=obj.data.body,
            anchor=skppy.PointReference(
                position=skppy.Vector3D(*position),
            ),
            view_direction=skppy.Vector3D(*direction.normalized()),
            drawing=skppy.DrawingElementProperties(
                material_id=material_id,
                layer_id=layer.id if layer is not None else None,
                hidden=obj.hide_viewport or obj.hide_render,
            ),
        )
        target.texts.append(text)
        self._attach_custom_properties(target, text.id, obj)
        self.exported_objects += 1

    def _export_cameras(self, objects: Iterable[Any]) -> None:
        camera_by_pointer: dict[int, skppy.Camera] = {}
        for obj in objects:
            if obj.type != "CAMERA":
                continue
            camera = self._camera_from_object(obj)
            self.model.cameras.append(camera)
            camera_by_pointer[obj.as_pointer()] = camera
        for marker in self.context.scene.timeline_markers:
            if marker.camera is None:
                continue
            camera = camera_by_pointer.get(marker.camera.as_pointer())
            if camera is None:
                camera = self._camera_from_object(marker.camera)
                self.model.cameras.append(camera)
                camera_by_pointer[marker.camera.as_pointer()] = camera
            self.model.scenes.append(
                skppy.Scene(
                    id=len(self.model.scenes) + 1,
                    name=marker.name or f"Scene {len(self.model.scenes) + 1}",
                    flags=0x1,
                    camera=camera,
                )
            )

    def _camera_from_object(self, obj: Any) -> skppy.Camera:
        matrix = obj.matrix_world
        eye = matrix.translation * self.inches_per_unit
        forward = -(matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        up = (matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
        distance = max(float(obj.data.dof.focus_distance), 1.0) * self.inches_per_unit
        target = eye + forward * distance
        perspective = obj.data.type != "ORTHO"
        return skppy.Camera(
            eye=skppy.Vector3D(*eye),
            target=skppy.Vector3D(*target),
            up=skppy.Vector3D(*up),
            fov=math.degrees(float(obj.data.angle_y)),
            fov_is_height=True,
            is_perspective=perspective,
            near=max(float(obj.data.clip_start) * self.inches_per_unit, 1.0e-6),
            far=max(float(obj.data.clip_end) * self.inches_per_unit, 1.0),
            name=obj.name,
            ortho_height=(float(obj.data.ortho_scale) * self.inches_per_unit if not perspective else None),
        )

    def _transform(self, matrix: Matrix) -> skppy.Transform:
        values = np.asarray(matrix, dtype=float).copy()
        values[:3, 3] *= self.inches_per_unit
        return skppy.Transform(values)

    def _attach_custom_properties(self, entities: skppy.Entities, entity_id: int, obj: Any) -> None:
        if not self.export_custom_properties:
            return
        entries = []
        for key in obj.keys():
            if key.startswith("_") or key == "skppy_layer_name":
                continue
            entry = self._attribute_entry(key, obj[key])
            if entry is not None:
                entries.append(entry)
        if entries:
            entities.attribute_dictionaries_by_entity_id[entity_id] = [
                skppy.AttributeDictionary(name="Blender", entries=entries)
            ]

    @staticmethod
    def _attribute_entry(key: str, value: Any) -> skppy.AttributeDictionaryEntry | None:
        if isinstance(value, bool):
            return skppy.AttributeDictionaryEntry(key=key, value_type=2, bool_value=value)
        if isinstance(value, int) and 0 <= value <= 0xFFFFFFFF:
            return skppy.AttributeDictionaryEntry(key=key, value_type=0, int_value=value)
        if isinstance(value, float) and math.isfinite(value):
            return skppy.AttributeDictionaryEntry(key=key, value_type=1, float_value=value)
        if isinstance(value, str):
            return skppy.AttributeDictionaryEntry(key=key, value_type=3, string_value=value)
        return None

    @staticmethod
    def _positive_custom(owner: Any, key: str, default: float) -> float:
        value = float(owner.get(key, default))
        return value if math.isfinite(value) and value > 0.0 else default

    @staticmethod
    def _channel(linear: float) -> int:
        value = min(max(float(linear), 0.0), 1.0)
        srgb = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
        return round(srgb * 255.0)

    def _unique_name(self, value: str, used: set[str]) -> str:
        base = self._clean_name(value, "Object")
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base} {suffix}"
            suffix += 1
        used.add(candidate)
        return candidate

    @staticmethod
    def _clean_name(value: str, fallback: str) -> str:
        cleaned = _SAFE_NAME.sub("_", value).strip(" .")
        return cleaned or fallback
