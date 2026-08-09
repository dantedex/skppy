# SPDX-License-Identifier: MIT
"""Index validated prepared faces without coupling importers to SKP entities."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..triangulation import triangulate_face_3d
from .scene import IndexedPreparedMesh, PreparedFace, PreparedMesh

Position3D = tuple[float, float, float]
UV = tuple[float, float]


@dataclass(slots=True)
class _MeshIndexer:
    """Accumulate indexed geometry and aligned face metadata."""

    merge_vertices: bool
    triangulate: bool
    precision: int
    vertices: list[Position3D] = field(default_factory=list)
    faces: list[list[int]] = field(default_factory=list)
    face_uvs: list[list[UV] | None] = field(default_factory=list)
    face_normals: list[Position3D] = field(default_factory=list)
    face_material_names: list[str | None] = field(default_factory=list)
    face_material_ids: list[int | None] = field(default_factory=list)
    source_face_ids: list[int | None] = field(default_factory=list)
    layer_ids: list[int | None] = field(default_factory=list)
    face_edge_ids: list[list[int | None]] = field(default_factory=list)
    face_edge_flags: list[list[int]] = field(default_factory=list)
    vertex_lookup: dict[Position3D, int] = field(default_factory=dict)

    def convert(self, mesh: PreparedMesh) -> IndexedPreparedMesh:
        """Append every output polygon and return the validated indexed result."""
        for prepared_face in mesh.faces:
            for corners in self._corner_groups(prepared_face):
                self._append_face(prepared_face, corners)
        return IndexedPreparedMesh(
            vertex_positions=self.vertices,
            faces=self.faces,
            face_uvs=self.face_uvs,
            face_normals=self.face_normals,
            face_material_names=self.face_material_names,
            face_material_ids=self.face_material_ids,
            source_face_ids=self.source_face_ids,
            layer_ids=self.layer_ids,
            face_edge_ids=self.face_edge_ids,
            face_edge_flags=self.face_edge_flags,
        )

    def _append_face(self, prepared_face: PreparedFace, corners: list[int]) -> None:
        """Append one polygon and every metadata entry in the same operation."""
        self.faces.append([self._vertex_index(prepared_face.vertex_positions[corner]) for corner in corners])
        self.face_uvs.append(
            [prepared_face.vertex_uvs[corner] for corner in corners] if prepared_face.vertex_uvs is not None else None
        )
        self.face_normals.append(prepared_face.normal)
        self.face_material_names.append(prepared_face.material_name)
        self.face_material_ids.append(prepared_face.material_id)
        self.source_face_ids.append(prepared_face.source_face_id)
        self.layer_ids.append(prepared_face.layer_id)
        edge_ids, edge_flags = _edge_metadata_for_corners(prepared_face, corners)
        self.face_edge_ids.append(edge_ids)
        self.face_edge_flags.append(edge_flags)

    def _vertex_index(self, position: Position3D) -> int:
        """Append one corner or reuse its rounded position when requested."""
        if not self.merge_vertices:
            self.vertices.append(position)
            return len(self.vertices) - 1
        key = (
            round(position[0], self.precision),
            round(position[1], self.precision),
            round(position[2], self.precision),
        )
        index = self.vertex_lookup.get(key)
        if index is None:
            index = len(self.vertices)
            self.vertex_lookup[key] = index
            self.vertices.append(position)
        return index

    def _corner_groups(self, face: PreparedFace) -> list[list[int]]:
        """Return one polygon or triangulated corner groups for a face."""
        count = len(face.vertex_positions)
        if not self.triangulate or count == 3:
            return [list(range(count))]
        triangles = triangulate_face_3d(face.vertex_positions, normal=face.normal)
        if triangles:
            return [list(triangle) for triangle in triangles]
        return [[0, index, index + 1] for index in range(1, count - 1)]


def _edge_metadata_for_corners(face: PreparedFace, corners: list[int]) -> tuple[list[int | None], list[int]]:
    """Preserve source edges and mark generated triangulation edges."""
    if face.edge_ids is None or face.edge_flags is None:
        return [None for _ in corners], [0 for _ in corners]

    by_corner_pair: dict[tuple[int, int], tuple[int | None, int]] = {}
    corner_count = len(face.vertex_positions)
    for index, (edge_id, edge_flag) in enumerate(zip(face.edge_ids, face.edge_flags, strict=True)):
        following = (index + 1) % corner_count
        by_corner_pair[(index, following)] = (edge_id, edge_flag)
        by_corner_pair[(following, index)] = (edge_id, edge_flag)

    ids: list[int | None] = []
    flags: list[int] = []
    for index, corner in enumerate(corners):
        following = corners[(index + 1) % len(corners)]
        edge_id, edge_flag = by_corner_pair.get((corner, following), (None, 0))
        ids.append(edge_id)
        flags.append(edge_flag)
    return ids, flags


def index_prepared_mesh(
    mesh: PreparedMesh,
    *,
    merge_vertices: bool,
    triangulate: bool,
    precision: int,
) -> IndexedPreparedMesh:
    """Convert a prepared mesh to indexed geometry through one state owner."""
    return _MeshIndexer(merge_vertices, triangulate, precision).convert(mesh)
