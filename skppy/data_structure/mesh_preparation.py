# SPDX-License-Identifier: MIT
"""Convert entity graphs into validated renderer-neutral prepared meshes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..triangulation import (
    merge_triangles_to_ngons,
    split_single_hole_face_3d,
    triangulate_face_3d,
)
from .entities import Edge, Entities, Face, FaceUVProjection, Loop
from .materials import Material
from .scene import PreparedFace, PreparedMesh, _planar_uv, _unit_normal

Position3D = tuple[float, float, float]
Normal3D = tuple[float, float, float]

# Greedy triangle-group merging is intentionally bounded: its repeated
# adjacency search becomes prohibitively expensive on CAD faces with hundreds
# of boundary vertices and several holes.
_MAX_NGON_MERGE_TRIANGLES = 256


@dataclass(slots=True)
class _LoopGeometry:
    """Resolved positions and source edge IDs for one valid face loop."""

    positions: list[Position3D]
    edge_ids: list[int]


@dataclass(slots=True)
class _FaceGeometry:
    """All resolved state needed to emit polygons for one source face."""

    source: Face
    normal: Normal3D
    material_id: int | None
    material: Material | None
    projection: FaceUVProjection | None
    outer: _LoopGeometry
    holes: list[_LoopGeometry]


@dataclass(slots=True)
class _MeshPreparer:
    """Resolve one entities scope while keeping conversion state local."""

    entities: Entities
    materials: dict[int, Material]
    inherited_material_id: int | None
    split_holes_to_ngons: bool
    edge_map: dict[int, tuple[int, int]] = field(init=False)
    edges: dict[int, Edge] = field(init=False)
    vertices: dict[int, Position3D] = field(init=False)

    def __post_init__(self) -> None:
        self.edge_map = {edge.id: (edge.start_vertex_id, edge.end_vertex_id) for edge in self.entities.edges}
        self.edges = {edge.id: edge for edge in self.entities.edges}
        self.vertices = {
            vertex.id: (
                vertex.position.x,
                vertex.position.y,
                vertex.position.z,
            )
            for vertex in self.entities.vertices
        }

    def prepare(self, name: str) -> PreparedMesh:
        """Prepare every valid source face in serialization order."""
        prepared_faces: list[PreparedFace] = []
        for face in self.entities.faces:
            geometry = self._resolve_face(face)
            if geometry is None:
                continue
            if geometry.holes:
                self._append_face_with_holes(prepared_faces, geometry)
            else:
                self._append_polygon(
                    prepared_faces,
                    geometry,
                    geometry.outer.positions,
                    list(geometry.outer.edge_ids),
                )
        return PreparedMesh(name=name, faces=prepared_faces)

    def _resolve_face(self, face: Face) -> _FaceGeometry | None:
        """Resolve references and appearance without emitting output polygons."""
        outer = self._resolve_loop(face.outer_loop)
        if outer is None:
            return None

        holes = [resolved for loop in face.inner_loops if (resolved := self._resolve_loop(loop)) is not None]
        material_id, projection = face.resolve_material_mapping(self.inherited_material_id)
        if projection is not None and projection.is_singular():
            projection = None
        a, b, c, _d = face.plane
        return _FaceGeometry(
            source=face,
            normal=_unit_normal(a, b, c),
            material_id=material_id,
            material=(self.materials.get(material_id) if material_id is not None else None),
            projection=projection,
            outer=outer,
            holes=holes,
        )

    def _resolve_loop(self, loop: Loop) -> _LoopGeometry | None:
        """Resolve a complete loop or reject it when any reference is dangling."""
        vertex_ids = loop.vertex_ids(self.edge_map)
        edge_ids = [edge_use.edge_id for edge_use in loop.edge_uses]
        if len(vertex_ids) < 3 or len(edge_ids) != len(vertex_ids):
            return None
        if any(vertex_id not in self.vertices for vertex_id in vertex_ids):
            return None
        if any(edge_id not in self.edges for edge_id in edge_ids):
            return None
        return _LoopGeometry(
            positions=[self.vertices[vertex_id] for vertex_id in vertex_ids],
            edge_ids=edge_ids,
        )

    def _append_face_with_holes(self, output: list[PreparedFace], geometry: _FaceGeometry) -> None:
        """Tessellate a holed face and preserve source boundary metadata."""
        hole_positions = [hole.positions for hole in geometry.holes]
        all_positions = geometry.outer.positions + [point for positions in hole_positions for point in positions]
        boundary_edges = _boundary_edge_lookup([geometry.outer, *geometry.holes])
        polygons = self._minimum_polygons(geometry, all_positions, hole_positions)
        for corners in polygons:
            edge_ids = [
                boundary_edges.get((corner, corners[(index + 1) % len(corners)]))
                for index, corner in enumerate(corners)
            ]
            self._append_polygon(
                output,
                geometry,
                [all_positions[index] for index in corners],
                edge_ids,
            )

    def _minimum_polygons(
        self,
        geometry: _FaceGeometry,
        all_positions: list[Position3D],
        hole_positions: list[list[Position3D]],
    ) -> list[list[int]]:
        """Return n-gons when requested, otherwise the triangulated fallback."""
        if self.split_holes_to_ngons and len(hole_positions) == 1:
            polygons = split_single_hole_face_3d(
                geometry.outer.positions,
                hole_positions[0],
                geometry.normal,
            )
            if polygons:
                return polygons

        triangles = triangulate_face_3d(
            geometry.outer.positions,
            hole_positions,
            geometry.normal,
        )
        if self.split_holes_to_ngons and len(hole_positions) > 1 and len(triangles) <= _MAX_NGON_MERGE_TRIANGLES:
            polygons = merge_triangles_to_ngons(triangles, all_positions, geometry.normal)
            if polygons:
                return polygons
        return [list(triangle) for triangle in triangles]

    def _append_polygon(
        self,
        output: list[PreparedFace],
        geometry: _FaceGeometry,
        positions: list[Position3D],
        edge_ids: list[int | None],
    ) -> None:
        """Create one validated prepared polygon from resolved face state."""
        if len(positions) < 3:
            return
        output.append(
            PreparedFace(
                vertex_positions=positions,
                vertex_uvs=_face_uvs(geometry, positions),
                normal=geometry.normal,
                material_name=(geometry.material.name if geometry.material is not None else None),
                material_id=geometry.material_id,
                source_face_id=geometry.source.id,
                layer_id=geometry.source.layer_id,
                edge_ids=edge_ids,
                edge_flags=[
                    self.edges[edge_id].flags if edge_id is not None and edge_id in self.edges else 0
                    for edge_id in edge_ids
                ],
            )
        )


def _boundary_edge_lookup(loops: list[_LoopGeometry]) -> dict[tuple[int, int], int]:
    """Map combined-loop corner pairs back to serialized source edge IDs."""
    lookup: dict[tuple[int, int], int] = {}
    offset = 0
    for loop in loops:
        length = len(loop.positions)
        for index, edge_id in enumerate(loop.edge_ids):
            start = offset + index
            end = offset + ((index + 1) % length)
            lookup[(start, end)] = edge_id
            lookup[(end, start)] = edge_id
        offset += length
    return lookup


def _face_uvs(geometry: _FaceGeometry, positions: list[Position3D]) -> Optional[list[tuple[float, float]]]:
    """Compute projected or planar UVs only for textured appearances."""
    material = geometry.material
    if material is None or not material.has_texture or material.texture is None:
        return None
    texture = material.texture
    if geometry.projection is not None:
        return geometry.projection.compute_uvs(
            positions,
            texture.x_scale,
            texture.y_scale,
            geometry.normal,
        )
    return _planar_uv(
        positions,
        geometry.normal,
        texture.x_scale,
        texture.y_scale,
    )


def prepare_entities_mesh(
    entities: Entities,
    name: str,
    material_lookup: dict[int, Material],
    inherited_material_id: int | None = None,
    split_holes_to_ngons: bool = False,
) -> PreparedMesh:
    """Build a prepared mesh from one format-neutral entities scope."""
    return _MeshPreparer(
        entities,
        material_lookup,
        inherited_material_id,
        split_holes_to_ngons,
    ).prepare(name)
