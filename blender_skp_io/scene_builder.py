# SPDX-License-Identifier: MIT
"""
BlenderSceneBuilder -- Converts a parsed skppy.Model into Blender objects.

Requires the Blender Python environment (bpy).  Import only from within
a running Blender session or the addon's execute() callback.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from .annotation_builder import BlenderAnnotationBuilder
from .skppy.data_structure.openings import infer_cutting_openings
from .skppy.exceptions import ComponentCycleError

__all__ = ["BlenderSceneBuilder"]

logger = logging.getLogger(__name__)

# SketchUp stores positions in internal inches; default scale converts to metres.
_DEFAULT_SCALE = 0.0254
_MINIMUM_CAMERA_CLIP_END = 100_000.0
_EDGE_FLAG_SMOOTH = 0x04
_SMOOTH_EDGE_MAX_ANGLE = math.radians(40.0)


@dataclass(slots=True)
class _InstanceBuildState:
    """Resolved state shared by flat and hierarchical instance builders."""

    collection: Any
    local_matrix: Matrix
    definition: Any
    child_path: tuple[int, ...]
    name: str
    effective_material_id: int | None
    material: Any
    mesh: Any
    children: list[Any]
    has_construction: bool
    has_annotations: bool


class BlenderSceneBuilder:
    """
    Build a Blender scene from a skppy Model.

    Parameters
    ----------
    model            : Parsed skppy.Model.
    context          : Active bpy.context.
    scale            : Unit scale (default 0.0254 = inches -> metres).
    import_materials : If True, create Blender materials from skppy Materials.
    merge_vertices   : If True, call bmesh.ops.remove_doubles after building each mesh.
    smooth_edges     : If True, apply SketchUp smooth/soft edge shading.
    use_collection_instances : If True, reuse definition collections instead of expanding every placement.
    """

    def __init__(
        self,
        model,
        context,
        scale: float = _DEFAULT_SCALE,
        import_materials: bool = True,
        merge_vertices: bool = True,
        smooth_edges: bool = True,
        import_cameras: bool = True,
        triangulation_mode: str = "NGONS",
        import_by_layers: bool = False,
        flatten_hierarchy: bool = False,
        use_collection_instances: bool = False,
        progress_callback: Callable[[float, str], None] | None = None,
    ):
        self.model = model
        self.context = context
        self.scale = scale
        self.import_materials = import_materials
        self.merge_vertices = merge_vertices
        self.smooth_edges = smooth_edges
        self.import_cameras = import_cameras
        self.triangulation_mode = triangulation_mode
        self.import_by_layers = import_by_layers
        self.flatten_hierarchy = flatten_hierarchy
        self.use_collection_instances = use_collection_instances
        self._progress_callback = progress_callback

        # Maps skppy IDs to Blender data-blocks
        self._bl_materials: Dict[int, bpy.types.Material] = {}
        # mat_name -> Blender material (populated after _build_materials)
        self._bl_mat_by_name: Dict[str, bpy.types.Material] = {}
        # skppy material_id -> skppy Material (for passing to prepare_mesh)
        self._mat_by_id: Dict[int, Any] = {}
        # definition_id -> Mesh (not Object; Objects are created per-instance)
        # Also keyed by (definition_id, effective_material_id) for variants.
        self._bl_meshes: Dict[Any, bpy.types.Mesh] = {}
        # (definition_id, inherited_material_id) -> reusable component collection.
        self._bl_definition_collections: Dict[tuple[int, int | None], bpy.types.Collection] = {}
        # Entities identity -> visible edges which are not used by a face.
        self._loose_edges: Dict[int, list[Any]] = {}
        self._cutting_openings: Dict[int, dict[int, list[list[tuple[float, float, float]]]]] = {}
        self._layer_collections: Dict[int, bpy.types.Collection] = {}
        # definition_id -> ComponentDefinition (for recursive instantiation)
        self._definition_map: Dict[int, Any] = {}
        # All Blender Objects created during build() - for reporting and selection
        self.created_objects: List[bpy.types.Object] = []
        self._annotation_builder = BlenderAnnotationBuilder(self)

    # -
    # Public API
    # -

    def build(self) -> None:
        """Build the full scene."""
        self._report_progress(0.0, "Preparing Blender scene")
        filepath = getattr(getattr(self.model, "document", None), "filepath", None)
        col_name = os.path.splitext(os.path.basename(filepath))[0] if filepath else "SKP Import"
        self._import_col = bpy.data.collections.new(col_name)
        self.context.scene.collection.children.link(self._import_col)

        if self.import_by_layers:
            self._build_layer_collections()
        self._report_progress(0.05, "Building materials")

        if self.import_materials:
            self._build_materials()
        else:
            self._mat_by_id = {mat.id: mat for mat in self.model.materials}
        self._report_progress(0.25, "Building component definitions")
        self._build_definitions()
        self._report_progress(0.70, "Building root geometry")
        self._build_root_geometry()
        self._build_root_construction()
        self._build_root_annotations()
        self._report_progress(0.80, "Creating component instances")
        self._build_root_instances()

        if self.import_cameras:
            self._report_progress(0.92, "Creating cameras")
            self._build_cameras()

        # Replace None slot-0 material placeholders
        self._report_progress(0.97, "Finalizing materials")
        if self.import_materials:
            default_mat = self._get_default_material()
            for mesh in bpy.data.meshes:
                if mesh.materials and mesh.materials[0] is None:
                    mesh.materials[0] = default_mat
        self._report_progress(1.0, "Import complete")

    def _report_progress(self, fraction: float, message: str) -> None:
        """Report normalized build progress when the caller supplied a callback."""
        if self._progress_callback is not None:
            self._progress_callback(min(max(fraction, 0.0), 1.0), message)

    # -
    # Materials
    # -

    def _build_materials(self) -> None:
        material_count = len(self.model.materials)
        for material_index, mat in enumerate(self.model.materials, start=1):
            # Reuse an existing Blender material with the same name so that
            # re-importing the same file doesn't create "Name.001" duplicates.
            bl_mat = bpy.data.materials.get(mat.name)
            if bl_mat is None:
                bl_mat = bpy.data.materials.new(name=mat.name)
            bl_mat.use_nodes = True

            bsdf = bl_mat.node_tree.nodes.get("Principled BSDF")
            has_texture_alpha = False
            if bsdf:
                r = mat.color.r / 255.0
                g = mat.color.g / 255.0
                b = mat.color.b / 255.0
                self._set_principled_input(bsdf, "Base Color", (r, g, b, 1.0))
                self._set_principled_input(bsdf, "Alpha", mat.alpha)
                self._set_principled_input(bsdf, "Metallic", mat.metallic)
                self._set_principled_input(bsdf, "Roughness", mat.roughness)

                if mat.has_texture and mat.texture and mat.texture.data:
                    has_texture_alpha = self._attach_texture(bl_mat, mat.texture, alpha_factor=mat.alpha)

            if mat.alpha < 1.0 or has_texture_alpha:
                self._set_transparency_method(bl_mat)

            self._bl_materials[mat.id] = bl_mat
            self._bl_mat_by_name[mat.name] = bl_mat
            logger.debug("Created material %r (id=%d)", mat.name, mat.id)
            if material_count:
                fraction = 0.05 + 0.20 * material_index / material_count
                self._report_progress(
                    fraction,
                    f"Building materials ({material_index}/{material_count})",
                )

        self._mat_by_id = {mat.id: mat for mat in self.model.materials}

    def _get_default_material(self) -> "bpy.types.Material":
        """Return a shared neutral gray material used as the slot-0 placeholder."""
        name = "SKP Default"
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = bpy.data.materials.new(name)
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1.0)
        return mat

    def _attach_texture(
        self,
        bl_mat: bpy.types.Material,
        texture,
        alpha_factor: float = 1.0,
    ) -> bool:
        """Load texture image data into a Blender image texture node.

        Returns True when the loaded image alpha channel contains transparency.
        """
        ext = os.path.splitext(texture.filename)[1] if texture.filename else ".png"
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(tmp_fd, "wb") as tmp:
                tmp.write(texture.data)
            image = bpy.data.images.load(tmp_path, check_existing=False)
            # Pack while the temp file is still on disk, then rename for clarity.
            image.pack()
            if texture.filename:
                image.name = os.path.basename(texture.filename)
            image.filepath_raw = ""  # drop the now-deleted temp path
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        tree = bl_mat.node_tree
        nodes = tree.nodes
        links = tree.links

        # Texture Coordinate node - use UV when per-face UV data is available,
        # with Generated as a fallback.
        tex_coord = nodes.new("ShaderNodeTexCoord")
        tex_coord.location = (-500, 200)

        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = image
        tex_node.location = (-280, 200)

        links.new(tex_coord.outputs["UV"], tex_node.inputs["Vector"])

        bsdf = nodes.get("Principled BSDF")
        if bsdf:
            self._link_principled_input(links, tex_node.outputs.get("Color"), bsdf, "Base Color")
            self._link_texture_alpha(
                nodes,
                links,
                tex_node.outputs.get("Alpha"),
                bsdf,
                alpha_factor,
            )

        return self._image_uses_alpha(image)

    @staticmethod
    def _set_principled_input(
        bsdf: "bpy.types.Node",
        socket_name: str,
        value,
    ) -> None:
        socket = bsdf.inputs.get(socket_name)
        if socket is not None:
            socket.default_value = value

    @staticmethod
    def _link_principled_input(
        links: "bpy.types.NodeLinks",
        output_socket,
        bsdf: "bpy.types.Node",
        socket_name: str,
    ) -> None:
        input_socket = bsdf.inputs.get(socket_name)
        if output_socket is not None and input_socket is not None:
            links.new(output_socket, input_socket)

    @staticmethod
    def _link_texture_alpha(
        nodes: "bpy.types.Nodes",
        links: "bpy.types.NodeLinks",
        alpha_output,
        bsdf: "bpy.types.Node",
        alpha_factor: float,
    ) -> None:
        alpha_input = bsdf.inputs.get("Alpha")
        if alpha_output is None or alpha_input is None:
            return

        if alpha_factor < 1.0:
            multiply = nodes.new("ShaderNodeMath")
            multiply.operation = "MULTIPLY"
            multiply.location = (-40, -120)
            multiply.inputs[1].default_value = alpha_factor
            links.new(alpha_output, multiply.inputs[0])
            links.new(multiply.outputs["Value"], alpha_input)
            return

        links.new(alpha_output, alpha_input)

    @staticmethod
    def _image_uses_alpha(image: "bpy.types.Image") -> bool:
        """Return True when the image alpha channel contains transparency."""
        channels = getattr(image, "channels", 0)
        if channels < 4:
            return False

        pixels = getattr(image, "pixels", None)
        if pixels is None:
            return True

        pixel_count = len(pixels)
        values_np = np.empty(pixel_count, dtype=np.float32)
        pixels.foreach_get(values_np)
        return bool(np.any(values_np[3::channels] < 0.999))

    @staticmethod
    def _set_transparency_method(bl_mat: "bpy.types.Material") -> None:
        # Blender 4.2+ (EEVEE Next) uses surface_render_method and supports
        # DITHERED. Older versions use blend_method, where HASHED is the
        # closest dithered transparency equivalent.
        if hasattr(bl_mat, "surface_render_method"):
            try:
                bl_mat.surface_render_method = "DITHERED"
                return
            except (TypeError, ValueError):
                bl_mat.surface_render_method = "BLENDED"
                return

        try:
            bl_mat.blend_method = "HASHED"
        except (TypeError, ValueError):
            bl_mat.blend_method = "BLEND"

    # -
    # Edge flags
    # -

    # -
    # Definitions -> Blender mesh data
    # -

    def _build_definitions(self) -> None:
        """Index definitions; mesh data is built lazily for reachable instances."""
        for defn in self.model.definitions:
            self._definition_map[defn.id] = defn
        self._report_progress(0.70, f"Indexed {len(self.model.definitions)} component definitions")

    def _get_or_build_mesh(
        self,
        defn,
        effective_material_id: Optional[int],
    ) -> Optional["bpy.types.Mesh"]:
        """
        Return (or lazily build) a Blender mesh for *defn* using the given
        effective material for faces that carry no explicit material.

        When *effective_material_id* is None (or when no face in the definition
        needs an inherited material), the shared cached mesh is used.  When the
        definition has unpainted faces and an effective textured material
        override is present, a variant mesh keyed by
        ``(defn.id, effective_material_id)`` is built and cached.
        """
        loose_edges = self._visible_loose_edges(defn.entities)
        if not defn.entities.faces and not loose_edges:
            return None

        # Check whether any face needs the inherited material.
        needs_inherited = effective_material_id is not None and any(
            f.front_material_id is None and f.back_material_id is None for f in defn.entities.faces
        )
        if not needs_inherited and defn.id in self._bl_meshes:
            return self._bl_meshes[defn.id]

        # Build or return a per-(definition, effective_material) variant.
        cache_key = (defn.id, effective_material_id) if needs_inherited else defn.id
        if cache_key in self._bl_meshes:
            return self._bl_meshes[cache_key]

        variant_name = f"{defn.name}:{effective_material_id}"
        prepared = defn.entities.prepare_mesh(
            variant_name,
            self._mat_by_id,
            inherited_material_id=effective_material_id,
            split_holes_to_ngons=self.triangulation_mode == "NGONS",
            opening_positions_by_face_id=self._openings_for(defn.entities),
        )
        mesh_data = self._build_mesh_from_prepared(prepared, defn.entities, loose_edges)
        if mesh_data is not None:
            self._bl_meshes[cache_key] = mesh_data
        return mesh_data

    def _openings_for(self, entities) -> dict[int, list[list[tuple[float, float, float]]]]:
        """Return cached face cuts inferred from glued child components."""
        cache_key = id(entities)
        cached = self._cutting_openings.get(cache_key)
        if cached is None:
            cached = infer_cutting_openings(entities, self._definition_map)
            self._cutting_openings[cache_key] = cached
        return cached

    def _build_mesh_from_prepared(
        self,
        prepared,  # skppy.PreparedMesh
        entities=None,
        loose_edges=None,
    ) -> Optional["bpy.types.Mesh"]:
        """
        Build a Blender mesh from PreparedMesh geometry.

        The geometry, material resolution, and UV calculation come from skppy's
        renderer-neutral PreparedMesh/IndexedPreparedMesh output.  This method
        only adapts that data to Blender datablocks.
        """
        indexed = prepared.to_indexed(
            merge_vertices=self.merge_vertices,
            triangulate=self.triangulation_mode == "TRIS",
        )
        loose_edges = loose_edges if loose_edges is not None else self._visible_loose_edges(entities)
        line_edges = self._append_loose_edge_geometry(indexed, entities, loose_edges)
        if not indexed.faces and not line_edges:
            return None

        has_default_faces, mat_slot_map = self._material_slot_layout(indexed)
        mesh = bpy.data.meshes.new(prepared.name)
        self._append_material_slots(mesh, has_default_faces, mat_slot_map)
        scaled_vertices = [
            (px * self.scale, py * self.scale, pz * self.scale) for px, py, pz in indexed.vertex_positions
        ]
        mesh.from_pydata(scaled_vertices, line_edges, indexed.faces)
        mesh.update(calc_edges=True)

        self._assign_face_materials(mesh, indexed, mat_slot_map)
        self._assign_uv_layer(mesh, indexed)

        if self.triangulation_mode == "QUADS":
            self._convert_mesh_to_quads(mesh)

        if self.smooth_edges:
            self._apply_edge_shading(mesh, indexed)

        self._compact_material_slots(mesh)
        return mesh

    def _visible_loose_edges(self, entities) -> list[Any]:
        """Return cached visible source edges which are not face boundaries."""
        if entities is None:
            return []
        cache_key = id(entities)
        cached = self._loose_edges.get(cache_key)
        if cached is not None:
            return cached
        face_edge_ids = {
            edge_use.edge_id
            for face in entities.faces
            for loop in (face.outer_loop, *face.inner_loops)
            for edge_use in loop.edge_uses
        }
        edges = [edge for edge in entities.edges if edge.id not in face_edge_ids and not edge.is_hidden]
        self._loose_edges[cache_key] = edges
        return edges

    def _append_loose_edge_geometry(self, indexed, entities, loose_edges) -> list[tuple[int, int]]:
        """Append endpoints for loose SKP edges and return indexed Blender edges."""
        if entities is None or not loose_edges:
            return []
        vertices = {vertex.id: vertex.position for vertex in entities.vertices}
        source_indices: dict[int, int] = {}
        position_indices = (
            {self._position_key(position): index for index, position in enumerate(indexed.vertex_positions)}
            if self.merge_vertices
            else None
        )
        occupied = {
            self._edge_key(face[index], face[(index + 1) % len(face)])
            for face in indexed.faces
            for index in range(len(face))
        }
        output: list[tuple[int, int]] = []
        for edge in loose_edges:
            start = self._loose_vertex_index(
                edge.start_vertex_id, vertices, source_indices, indexed.vertex_positions, position_indices
            )
            end = self._loose_vertex_index(
                edge.end_vertex_id, vertices, source_indices, indexed.vertex_positions, position_indices
            )
            if start is None or end is None or start == end:
                continue
            key = self._edge_key(start, end)
            if key in occupied:
                continue
            occupied.add(key)
            output.append((start, end))
        return output

    def _loose_vertex_index(self, vertex_id, vertices, source_indices, positions, position_indices) -> int | None:
        """Resolve one source vertex, reusing source IDs and optionally positions."""
        if vertex_id in source_indices:
            return source_indices[vertex_id]
        point = vertices.get(vertex_id)
        if point is None:
            return None
        position = self._xyz(point)
        key = self._position_key(position)
        index = position_indices.get(key) if position_indices is not None else None
        if index is None:
            index = len(positions)
            positions.append(position)
            if position_indices is not None:
                position_indices[key] = index
        source_indices[vertex_id] = index
        return index

    @staticmethod
    def _position_key(position) -> tuple[float, float, float]:
        """Return the same positional key used by PreparedMesh indexing."""
        return tuple(round(float(value), 9) for value in position)

    def _material_slot_layout(self, indexed) -> tuple[bool, Dict[str, int]]:
        """Map source material names to stable Blender slot indices."""
        if not self.import_materials:
            return False, {}
        has_default_faces = any(
            name is None or name not in self._bl_mat_by_name for name in indexed.face_material_names
        )
        slot_offset = int(has_default_faces)
        material_slots: Dict[str, int] = {}
        for name in indexed.face_material_names:
            if name is not None and name in self._bl_mat_by_name and name not in material_slots:
                material_slots[name] = len(material_slots) + slot_offset
        return has_default_faces, material_slots

    def _append_material_slots(
        self,
        mesh: "bpy.types.Mesh",
        has_default_faces: bool,
        material_slots: Dict[str, int],
    ) -> None:
        """Create Blender material slots in the assigned layout."""
        if has_default_faces:
            mesh.materials.append(None)
        for name, _index in sorted(material_slots.items(), key=lambda item: item[1]):
            mesh.materials.append(self._bl_mat_by_name[name])

    def _assign_face_materials(self, mesh, indexed, material_slots) -> None:
        """Assign every polygon to its aligned material slot."""
        if not self.import_materials or not mesh.materials:
            return
        for polygon, name in zip(mesh.polygons, indexed.face_material_names, strict=True):
            polygon.material_index = material_slots.get(name, 0)

    @staticmethod
    def _assign_uv_layer(mesh, indexed) -> None:
        """Copy validated per-loop UVs into one Blender UV layer."""
        if not any(uvs is not None for uvs in indexed.face_uvs):
            return
        uv_layer = mesh.uv_layers.new(name="SKP UV")
        for polygon, face_uvs in zip(mesh.polygons, indexed.face_uvs, strict=True):
            if face_uvs is None:
                continue
            for loop_index, uv in zip(polygon.loop_indices, face_uvs, strict=True):
                uv_layer.data[loop_index].uv = uv

    def _compact_material_slots(self, mesh: "bpy.types.Mesh") -> None:
        """Remove unused slots and remap polygons without changing materials."""
        if not self.import_materials or not mesh.materials:
            return
        used_indices = sorted({polygon.material_index for polygon in mesh.polygons})
        if len(used_indices) == len(mesh.materials):
            return
        remap = {old: new for new, old in enumerate(used_indices)}
        materials = [mesh.materials[index] for index in used_indices]
        for polygon in mesh.polygons:
            polygon.material_index = remap[polygon.material_index]
        mesh.materials.clear()
        for material in materials:
            mesh.materials.append(material)
        mesh.update()

    def _apply_edge_shading(self, mesh: "bpy.types.Mesh", indexed) -> None:
        """
        Apply SketchUp edge smoothing to Blender polygons and sharp edges.

        SketchUp stores soft/smooth intent on edges.  Arc-curve boundary edges
        can carry the smooth flag even when they separate a cylinder side from
        a cap, so the importer also checks the dihedral angle between adjacent
        source faces.  Edges over the threshold remain sharp.
        """

        smooth_keys, boundary_sharp_keys = self._mesh_edge_shading_keys(indexed)
        if not smooth_keys:
            return

        for poly in mesh.polygons:
            vertices = list(poly.vertices)
            poly.use_smooth = any(
                self._edge_key(v1, v2) in smooth_keys for v1, v2 in zip(vertices, vertices[1:] + vertices[:1])
            )

        smooth_keys.difference_update(boundary_sharp_keys)
        for edge in mesh.edges:
            edge_key = self._edge_key(edge.vertices[0], edge.vertices[1])
            edge.use_edge_sharp = edge_key in boundary_sharp_keys
        mesh.update()

    def _mesh_edge_shading_keys(self, indexed) -> tuple[set[Tuple[int, int]], set[Tuple[int, int]]]:
        """Return ``(smooth_edge_keys, sharp_edge_keys)`` for a Blender mesh."""
        face_refs, edge_flags = self._source_edge_metadata(indexed)
        source_edge_smooth = self._classify_source_edge_smoothing(indexed, face_refs, edge_flags)
        if not any(source_edge_smooth.values()):
            return set(), set()
        return self._blender_shading_keys(indexed, source_edge_smooth)

    @staticmethod
    def _source_edge_metadata(indexed) -> tuple[Dict[int, List[int]], Dict[int, int]]:
        """Collect adjacent face indices and flags for each source edge."""
        face_refs_by_source_edge: Dict[int, List[int]] = {}
        flags_by_source_edge: Dict[int, int] = {}
        for face_index, (edge_ids, edge_flags) in enumerate(
            zip(indexed.face_edge_ids, indexed.face_edge_flags, strict=True)
        ):
            for edge_id, edge_flag in zip(edge_ids, edge_flags, strict=True):
                if edge_id is None:
                    continue
                face_refs_by_source_edge.setdefault(edge_id, []).append(face_index)
                flags_by_source_edge[edge_id] = edge_flag
        return face_refs_by_source_edge, flags_by_source_edge

    def _classify_source_edge_smoothing(
        self,
        indexed,
        face_refs_by_source_edge: Dict[int, List[int]],
        flags_by_source_edge: Dict[int, int],
    ) -> Dict[int, bool]:
        """Apply source flags and the cap-boundary angle safeguard."""
        source_edge_smooth: Dict[int, bool] = {}
        min_dot = math.cos(_SMOOTH_EDGE_MAX_ANGLE)
        for edge_id, face_indices in face_refs_by_source_edge.items():
            edge_flag = flags_by_source_edge.get(edge_id, 0)
            if not (edge_flag & _EDGE_FLAG_SMOOTH) or len(face_indices) < 2:
                source_edge_smooth[edge_id] = False
                continue

            smooth = False
            normals = [indexed.face_normals[idx] for idx in face_indices]
            for i, normal_a in enumerate(normals):
                for normal_b in normals[i + 1 :]:
                    if self._normal_dot(normal_a, normal_b) >= min_dot:
                        smooth = True
                        break
                if smooth:
                    break
            source_edge_smooth[edge_id] = smooth
        return source_edge_smooth

    def _blender_shading_keys(
        self, indexed, source_edge_smooth: Dict[int, bool]
    ) -> tuple[set[Tuple[int, int]], set[Tuple[int, int]]]:
        """Translate classified source edges to indexed Blender edge keys."""
        smooth_keys: set[Tuple[int, int]] = set()
        boundary_sharp_keys: set[Tuple[int, int]] = set()
        for face, edge_ids in zip(indexed.faces, indexed.face_edge_ids, strict=True):
            face_smooth_keys: set[Tuple[int, int]] = set()
            face_non_smooth_source_keys: set[Tuple[int, int]] = set()
            for i, edge_id in enumerate(edge_ids):
                if edge_id is None:
                    continue
                edge_key = self._edge_key(face[i], face[(i + 1) % len(face)])
                if source_edge_smooth.get(edge_id, False):
                    face_smooth_keys.add(edge_key)
                else:
                    face_non_smooth_source_keys.add(edge_key)

            if face_smooth_keys:
                smooth_keys.update(face_smooth_keys)
                boundary_sharp_keys.update(face_non_smooth_source_keys)

        smooth_keys.difference_update(boundary_sharp_keys)
        return smooth_keys, boundary_sharp_keys

    @staticmethod
    def _edge_key(a: int, b: int) -> Tuple[int, int]:
        return (a, b) if a <= b else (b, a)

    @staticmethod
    def _normal_dot(normal_a: Tuple[float, float, float], normal_b: Tuple[float, float, float]) -> float:
        return float(np.dot(normal_a, normal_b))

    def _convert_mesh_to_quads(self, mesh: "bpy.types.Mesh") -> None:
        """Triangulate then join triangles while preserving material and UV seams."""
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.faces.ensure_lookup_table()
            bmesh.ops.triangulate(bm, faces=bm.faces[:])
            bm.faces.ensure_lookup_table()
            bmesh.ops.join_triangles(
                bm,
                faces=bm.faces[:],
                cmp_seam=False,
                cmp_sharp=False,
                cmp_uvs=True,
                cmp_vcols=False,
                cmp_materials=True,
                angle_face_threshold=0.698,
                angle_shape_threshold=0.698,
            )
            bm.to_mesh(mesh)
            mesh.update()
        finally:
            bm.free()

    # -
    # Root geometry (ungrouped faces at the model's root level)
    # -

    def _build_root_geometry(self) -> None:
        """Build meshes for ungrouped faces and loose edges at model root."""
        ent = self.model.entities
        loose_edges = self._visible_loose_edges(ent)
        if not ent.faces and not loose_edges:
            return
        prepared = ent.prepare_mesh(
            "RootGeometry",
            self._mat_by_id,
            split_holes_to_ngons=self.triangulation_mode == "NGONS",
            opening_positions_by_face_id=self._openings_for(ent),
        )
        faces_by_layer: dict[int | None, list] = {}
        for face in prepared.faces:
            layer_id = face.layer_id if self.import_by_layers else None
            faces_by_layer.setdefault(layer_id, []).append(face)
        edges_by_layer: dict[int | None, list[Any]] = {}
        for edge in loose_edges:
            layer_id = edge.layer_id if self.import_by_layers else None
            edges_by_layer.setdefault(layer_id, []).append(edge)
        layer_ids = dict.fromkeys((*faces_by_layer, *edges_by_layer))
        for layer_id in layer_ids:
            faces = faces_by_layer.get(layer_id, [])
            layer_collection = self._collection_for_layer(layer_id, self._import_col)
            object_name = (
                f"RootGeometry:{layer_collection.name}" if layer_collection is not self._import_col else "RootGeometry"
            )
            layer_mesh = type(prepared)(name=object_name, faces=faces)
            mesh_data = self._build_mesh_from_prepared(layer_mesh, ent, edges_by_layer.get(layer_id, []))
            if mesh_data is None:
                continue
            obj = bpy.data.objects.new(object_name, mesh_data)
            obj.matrix_world = Matrix.Identity(4)
            layer_collection.objects.link(obj)
            self.created_objects.append(obj)
        logger.debug("Built root geometry mesh (%d faces, %d loose edges)", len(ent.faces), len(loose_edges))

    # -
    # Instances
    # -

    def _build_root_instances(self) -> None:
        """Create root-level component instances, groups, and images."""
        if self.use_collection_instances and not self.flatten_hierarchy and not self.import_by_layers:
            for instance in (
                *self.model.entities.component_instances,
                *self.model.entities.groups,
                *self.model.entities.images,
            ):
                self._instantiate_collection(instance, self._import_col)
            return
        flat_world = Matrix.Identity(4) if self.flatten_hierarchy else None
        for inst in self.model.entities.component_instances:
            self._instantiate(inst, self._import_col, parent_obj=None, world_matrix=flat_world)
        for group in self.model.entities.groups:
            self._instantiate(group, self._import_col, parent_obj=None, world_matrix=flat_world)
        for image in self.model.entities.images:
            self._instantiate(image, self._import_col, parent_obj=None, world_matrix=flat_world)

    def _instantiate_collection(
        self,
        instance,
        collection: "bpy.types.Collection",
        inherited_material_id: int | None = None,
        active_definition_ids: tuple[int, ...] = (),
    ) -> Optional["bpy.types.Object"]:
        """Create one Blender collection instance for a reusable SKP definition."""
        definition = self._definition_map.get(instance.definition_id)
        self._reject_component_cycle(definition, instance.definition_id, active_definition_ids)
        if definition is None:
            return None
        own_material_id = getattr(instance, "material_id", None)
        material_id = own_material_id if own_material_id is not None else inherited_material_id
        definition_collection = self._get_or_build_definition_collection(
            definition,
            material_id,
            (*active_definition_ids, instance.definition_id),
        )
        name = instance.name or definition.name or f"Instance_{instance.id}"
        obj = bpy.data.objects.new(name, None)
        obj.instance_type = "COLLECTION"
        obj.instance_collection = definition_collection
        obj.empty_display_type = "PLAIN_AXES"
        obj.empty_display_size = 0.1
        obj.matrix_world = self._transform_to_matrix(instance.transform)
        collection.objects.link(obj)
        self.created_objects.append(obj)
        return obj

    def _get_or_build_definition_collection(
        self,
        definition,
        inherited_material_id: int | None,
        active_definition_ids: tuple[int, ...],
    ) -> "bpy.types.Collection":
        """Build one reusable collection for a definition/material variant."""
        cache_key = (definition.id, inherited_material_id)
        cached = self._bl_definition_collections.get(cache_key)
        if cached is not None:
            return cached

        suffix = f":{inherited_material_id}" if inherited_material_id is not None else ""
        collection = bpy.data.collections.new(f"SKP:{definition.name}{suffix}")
        self._bl_definition_collections[cache_key] = collection
        material = self._bl_materials.get(inherited_material_id) if inherited_material_id is not None else None
        mesh = self._get_or_build_mesh(definition, inherited_material_id)
        if mesh is not None:
            mesh_obj = bpy.data.objects.new(f"{definition.name}:geometry", mesh)
            collection.objects.link(mesh_obj)
            self._apply_material_override(mesh_obj, material)

        created_start = len(self.created_objects)
        self._build_construction_entities(definition.entities, collection)
        self._build_annotation_entities(definition.entities, collection)
        del self.created_objects[created_start:]

        for child in (
            *definition.entities.groups,
            *definition.entities.component_instances,
            *definition.entities.images,
        ):
            child_definition = self._definition_map.get(child.definition_id)
            self._reject_component_cycle(child_definition, child.definition_id, active_definition_ids)
            if child_definition is None:
                continue
            own_material_id = getattr(child, "material_id", None)
            material_id = own_material_id if own_material_id is not None else inherited_material_id
            child_collection = self._get_or_build_definition_collection(
                child_definition,
                material_id,
                (*active_definition_ids, child.definition_id),
            )
            name = child.name or child_definition.name or f"Instance_{child.id}"
            child_obj = bpy.data.objects.new(name, None)
            child_obj.instance_type = "COLLECTION"
            child_obj.instance_collection = child_collection
            child_obj.empty_display_type = "PLAIN_AXES"
            child_obj.empty_display_size = 0.1
            child_obj.matrix_world = self._transform_to_matrix(child.transform)
            collection.objects.link(child_obj)
        return collection

    def _build_root_construction(self) -> None:
        """Create root-level guides and section planes."""
        self._build_construction_entities(self.model.entities, self._import_col)

    def _build_root_annotations(self) -> None:
        """Create root-level text and dimension objects."""
        self._build_annotation_entities(self.model.entities, self._import_col)

    def _instantiate(
        self,
        inst,
        collection: "bpy.types.Collection",
        parent_obj: Optional["bpy.types.Object"] = None,
        inherited_material_id: Optional[int] = None,
        world_matrix: Optional[Matrix] = None,
        active_definition_ids: tuple[int, ...] = (),
    ) -> Optional["bpy.types.Object"]:
        """
        Recursively instantiate a component instance, group, or image.

        When *world_matrix* is not None, hierarchy is flattened: no Empty parents
        are created and each mesh object is placed at the accumulated world
        transform (world_matrix @ local_matrix).

        Parameters
        ----------
        world_matrix
            When provided (flatten mode), the accumulated world transform up to
            this instance.  ``None`` means use normal parent-child hierarchy.
        inherited_material_id
            Effective material inherited from the parent scope.
        """
        state = self._instance_build_state(
            inst,
            collection,
            inherited_material_id,
            active_definition_ids,
        )
        if world_matrix is not None:
            self._instantiate_flattened(state, world_matrix)
            return None
        return self._instantiate_hierarchical(state, parent_obj)

    def _instance_build_state(
        self,
        instance,
        collection: "bpy.types.Collection",
        inherited_material_id: int | None,
        active_definition_ids: tuple[int, ...],
    ) -> _InstanceBuildState:
        """Resolve definition, material, children, and cycle state once."""
        collection = self._collection_for_layer(getattr(instance, "layer_id", None), collection)
        definition = self._definition_map.get(instance.definition_id)
        self._reject_component_cycle(definition, instance.definition_id, active_definition_ids)
        child_path = active_definition_ids
        children: list[Any] = []
        has_construction = has_annotations = False
        if definition is not None:
            child_path = (*active_definition_ids, instance.definition_id)
            children = (
                list(definition.entities.groups)
                + list(definition.entities.component_instances)
                + list(definition.entities.images)
            )
            has_construction = bool(
                definition.entities.guide_points
                or definition.entities.guide_lines
                or definition.entities.section_planes
            )
            has_annotations = bool(
                definition.entities.texts
                or definition.entities.linear_dimensions
                or definition.entities.radial_dimensions
            )
        own_material_id = getattr(instance, "material_id", None)
        material_id = own_material_id if own_material_id is not None else inherited_material_id
        material = self._bl_materials.get(material_id) if material_id is not None else None
        mesh = self._get_or_build_mesh(definition, material_id) if definition is not None else None
        return _InstanceBuildState(
            collection=collection,
            local_matrix=self._transform_to_matrix(instance.transform),
            definition=definition,
            child_path=child_path,
            name=instance.name or (definition.name if definition is not None else None) or f"Instance_{instance.id}",
            effective_material_id=material_id,
            material=material,
            mesh=mesh,
            children=children,
            has_construction=has_construction,
            has_annotations=has_annotations,
        )

    @staticmethod
    def _reject_component_cycle(definition, definition_id: int, active_definition_ids: tuple[int, ...]) -> None:
        """Reject recursion on the current branch while allowing shared instances."""
        if definition is None or definition_id not in active_definition_ids:
            return
        cycle = (*active_definition_ids, definition_id)
        raise ComponentCycleError("Recursive component definition path: " + " -> ".join(str(value) for value in cycle))

    @staticmethod
    def _apply_material_override(obj: "bpy.types.Object", material) -> None:
        """Apply inherited material only to an intentionally empty first slot."""
        if material is not None and obj.data and obj.material_slots and obj.material_slots[0].material is None:
            obj.material_slots[0].link = "OBJECT"
            obj.material_slots[0].material = material

    def _instantiate_flattened(self, state: _InstanceBuildState, world_matrix: Matrix) -> None:
        """Create geometry at accumulated world transforms without Empty parents."""
        effective_world = world_matrix @ state.local_matrix
        if state.mesh is not None:
            mesh_obj = bpy.data.objects.new(state.name, state.mesh)
            state.collection.objects.link(mesh_obj)
            mesh_obj.matrix_world = effective_world
            self._apply_material_override(mesh_obj, state.material)
            self.created_objects.append(mesh_obj)
        for child in state.children:
            self._instantiate(
                child,
                state.collection,
                inherited_material_id=state.effective_material_id,
                world_matrix=effective_world,
                active_definition_ids=state.child_path,
            )
        if state.has_construction:
            self._build_construction_entities(
                state.definition.entities,
                state.collection,
                world_matrix=effective_world,
            )
        if state.has_annotations:
            self._build_annotation_entities(
                state.definition.entities,
                state.collection,
                world_matrix=effective_world,
            )

    def _instantiate_hierarchical(
        self,
        state: _InstanceBuildState,
        parent_obj: "bpy.types.Object" | None,
    ) -> "bpy.types.Object":
        """Create an object hierarchy that mirrors SketchUp components."""
        is_mesh_leaf = (
            state.mesh is not None and not state.children and not state.has_construction and not state.has_annotations
        )
        if is_mesh_leaf:
            obj = bpy.data.objects.new(state.name, state.mesh)
            state.collection.objects.link(obj)
            self._place(obj, parent_obj, state.local_matrix)
            self._apply_material_override(obj, state.material)
            self.created_objects.append(obj)
            return obj

        empty = bpy.data.objects.new(state.name, None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.1
        state.collection.objects.link(empty)
        self._place(empty, parent_obj, state.local_matrix)
        self.created_objects.append(empty)

        if state.mesh is not None:
            mesh_obj = bpy.data.objects.new(f"{state.name}:faces", state.mesh)
            state.collection.objects.link(mesh_obj)
            self._place(mesh_obj, empty, Matrix.Identity(4))
            self._apply_material_override(mesh_obj, state.material)
            self.created_objects.append(mesh_obj)

        if state.has_construction:
            self._build_construction_entities(
                state.definition.entities,
                state.collection,
                parent_obj=empty,
            )
        if state.has_annotations:
            self._build_annotation_entities(
                state.definition.entities,
                state.collection,
                parent_obj=empty,
            )
        for child in state.children:
            self._instantiate(
                child,
                state.collection,
                parent_obj=empty,
                inherited_material_id=state.effective_material_id,
                active_definition_ids=state.child_path,
            )
        return empty

    def _build_construction_entities(
        self,
        entities,
        collection: "bpy.types.Collection",
        *,
        parent_obj: Optional["bpy.types.Object"] = None,
        world_matrix: Optional[Matrix] = None,
    ) -> None:
        """Create non-rendering Blender helpers for construction entities."""
        for point in entities.guide_points:
            target = self._collection_for_layer(point.layer_id, collection)
            obj = bpy.data.objects.new(f"GuidePoint_{point.id}", None)
            obj.empty_display_type = "SPHERE"
            obj.empty_display_size = 0.05
            obj.show_in_front = True
            local = Matrix.Translation(Vector(self._xyz(point.position)) * self.scale)
            self._place_auxiliary(obj, parent_obj, local, world_matrix)
            target.objects.link(obj)
            self.created_objects.append(obj)

        for line in entities.guide_lines:
            target = self._collection_for_layer(line.layer_id, collection)
            direction = Vector(self._xyz(line.direction))
            if direction.length_squared == 0.0:
                continue
            direction.normalize()
            point = Vector(self._xyz(line.point))
            extent = 1000.0
            vertices = [
                tuple((point - direction * extent) * self.scale),
                tuple((point + direction * extent) * self.scale),
            ]
            mesh = bpy.data.meshes.new(f"GuideLine_{line.id}")
            mesh.from_pydata(vertices, [(0, 1)], [])
            mesh.update()
            obj = bpy.data.objects.new(f"GuideLine_{line.id}", mesh)
            obj.hide_render = True
            obj.show_in_front = True
            self._place_auxiliary(obj, parent_obj, Matrix.Identity(4), world_matrix)
            target.objects.link(obj)
            self.created_objects.append(obj)

        for section in entities.section_planes:
            target = self._collection_for_layer(section.layer_id, collection)
            obj = bpy.data.objects.new(section.name or f"SectionPlane_{section.id}", None)
            obj.empty_display_type = "CUBE"
            obj.empty_display_size = 1.0
            obj.show_in_front = True
            obj["skppy_section_plane"] = tuple(section.plane)
            if section.symbol:
                obj["skppy_section_symbol"] = section.symbol
            local = self._section_plane_matrix(section.plane)
            self._place_auxiliary(obj, parent_obj, local, world_matrix)
            target.objects.link(obj)
            self.created_objects.append(obj)

    def _build_annotation_entities(
        self,
        entities,
        collection: "bpy.types.Collection",
        *,
        parent_obj: Optional["bpy.types.Object"] = None,
        world_matrix: Optional[Matrix] = None,
    ) -> None:
        """Create Blender text and line objects from shared annotations."""
        self._annotation_builder.build(
            entities,
            collection,
            parent_obj=parent_obj,
            world_matrix=world_matrix,
        )

    def _place_auxiliary(
        self,
        obj: "bpy.types.Object",
        parent_obj: Optional["bpy.types.Object"],
        local_matrix: Matrix,
        world_matrix: Optional[Matrix],
    ) -> None:
        """Place one helper in hierarchy or flattened world space."""
        if world_matrix is not None:
            obj.matrix_world = world_matrix @ local_matrix
        else:
            self._place(obj, parent_obj, local_matrix)

    def _section_plane_matrix(self, plane: tuple[float, float, float, float]) -> Matrix:
        """Return a transform whose local Z axis and origin describe a plane."""
        normal = Vector(plane[:3])
        if normal.length_squared == 0.0:
            return Matrix.Identity(4)
        distance = -plane[3] / normal.length_squared
        origin = normal * distance * self.scale
        normal.normalize()
        matrix = normal.to_track_quat("Z", "Y").to_matrix().to_4x4()
        matrix.translation = origin
        return matrix

    @staticmethod
    def _xyz(value) -> tuple[float, float, float]:
        """Normalize shared vector or tuple storage for Blender mathutils."""
        if hasattr(value, "to_tuple"):
            return value.to_tuple()
        return tuple(value)

    def _place(
        self,
        obj: "bpy.types.Object",
        parent: Optional["bpy.types.Object"],
        local_matrix: Matrix,
    ) -> None:
        """Set object transform, optionally under a parent object."""
        if parent is not None:
            obj.parent = parent
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_local = local_matrix
        else:
            obj.matrix_world = local_matrix

    # -
    # Layers -> Collections
    # -

    def _build_layer_collections(self) -> None:
        """Map each skppy layer to a collection inside the import collection."""
        for layer in self.model.layers:
            col = bpy.data.collections.new(layer.name)
            col.hide_viewport = not layer.visible
            self._import_col.children.link(col)
            self._layer_collections[layer.id] = col
            logger.debug("Created collection %r (visible=%s)", layer.name, layer.visible)

    def _collection_for_layer(
        self,
        layer_id: int | None,
        fallback: "bpy.types.Collection",
    ) -> "bpy.types.Collection":
        """Return a layer collection when layer grouping is enabled."""
        if not self.import_by_layers or layer_id is None:
            return fallback
        return self._layer_collections.get(layer_id, fallback)

    def _build_cameras(self) -> None:
        """Create Blender cameras from model views and saved scene pages."""
        sources = [(camera, camera.name, None) for camera in self.model.cameras]
        seen_cameras = {id(camera) for camera in self.model.cameras}
        for scene in self.model.scenes:
            if scene.camera is None or id(scene.camera) in seen_cameras:
                continue
            sources.append((scene.camera, scene.name, scene))
            seen_cameras.add(id(scene.camera))

        for index, (camera, preferred_name, scene) in enumerate(sources, start=1):
            name = preferred_name or camera.name or f"SKP Camera {index}"
            cam_obj = self._build_camera(camera, name)
            if scene is not None:
                cam_obj["skppy_scene_id"] = scene.id
                cam_obj["skppy_scene_description"] = scene.description
                cam_obj["skppy_hidden_entity_ids"] = scene.hidden_entity_ids
                cam_obj["skppy_hidden_layer_ids"] = scene.hidden_layer_ids
                cam_obj["skppy_active_section_plane_ids"] = scene.active_section_plane_ids
                cam_obj["skppy_show_in_slideshow"] = scene.show_in_slideshow

    def _build_camera(self, cam, name: str) -> "bpy.types.Object":
        """Create one Blender camera object from a shared Camera value."""
        cam_data = bpy.data.cameras.new(name)
        cam_data.type = "PERSP" if cam.is_perspective else "ORTHO"

        # Convert FOV to Blender lens angle.
        # cam.fov is vertical FOV in degrees (fov_is_height=True) or horizontal.
        if cam.is_perspective:
            fov_rad = math.radians(cam.fov)
            if cam.fov_is_height:
                cam_data.angle_y = fov_rad
                cam_data.lens_unit = "FOV"
            else:
                cam_data.angle_x = fov_rad
                cam_data.lens_unit = "FOV"
        elif cam.ortho_height is not None and cam.ortho_height > 0.0:
            cam_data.ortho_scale = cam.ortho_height * self.scale
        else:
            logger.warning(
                "Camera %r has no valid orthographic height; using Blender default",
                name,
            )

        cam_data.clip_start = cam.near * self.scale
        cam_data.clip_end = max(cam.far * self.scale, _MINIMUM_CAMERA_CLIP_END)

        cam_obj = bpy.data.objects.new(name, cam_data)
        self._import_col.objects.link(cam_obj)

        # Blender cameras look down local -Z; reconstruct the orthonormal basis
        # from SketchUp's eye/target/up representation.
        eye_v = Vector(cam.eye.to_tuple()) * self.scale
        target_v = Vector(cam.target.to_tuple()) * self.scale
        up_v = Vector(cam.up.to_tuple()).normalized()
        forward = (target_v - eye_v).normalized()
        right = forward.cross(up_v).normalized()
        cam_up = right.cross(forward).normalized()

        rot_mat = Matrix(
            (
                (right.x, right.y, right.z, 0.0),
                (cam_up.x, cam_up.y, cam_up.z, 0.0),
                (-forward.x, -forward.y, -forward.z, 0.0),
                (0.0, 0.0, 0.0, 1.0),
            )
        ).transposed()
        rot_mat.translation = eye_v
        cam_obj.matrix_world = rot_mat

        self.created_objects.append(cam_obj)
        logger.debug(
            "Created camera %r at eye=(%.2f,%.2f,%.2f) fov=%.1f",
            cam_obj.name,
            eye_v.x,
            eye_v.y,
            eye_v.z,
            cam.fov,
        )
        return cam_obj

    # -
    # Helpers
    # -

    def _transform_to_matrix(self, transform_13d: List[float]) -> Matrix:
        """
        Convert a 13-float SUTransformation to a mathutils.Matrix,
        applying the unit scale to the translation component.
        """
        if not transform_13d or len(transform_13d) < 13:
            return Matrix.Identity(4)

        v = transform_13d
        # Row-major storage in SKP TLV SUTransformation:
        # [row0_x, row0_y, row0_z,  row1_x, row1_y, row1_z,
        #  row2_x, row2_y, row2_z,  tx, ty, tz, w]
        mat = Matrix(
            [
                [v[0], v[1], v[2], v[9] * self.scale],
                [v[3], v[4], v[5], v[10] * self.scale],
                [v[6], v[7], v[8], v[11] * self.scale],
                [0.0, 0.0, 0.0, v[12]],
            ]
        )
        return mat
