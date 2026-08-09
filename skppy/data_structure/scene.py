# SPDX-License-Identifier: MIT
"""
Scene output data structures.

.. module:: skppy.data_structure.scene
   :synopsis: Intermediate scene representation for importers

These classes provide a format-agnostic representation of a SketchUp model,
suitable for consumption by any renderer or importer. Geometry, UVs,
normals, and material names are already resolved to plain Python data.

All spatial coordinates are in **SketchUp inches** (the native unit).  The
consuming application is responsible for converting to its own unit system.

Example
-------
::

    def walk(node):
        yield node
        for child in node.children:
            yield from walk(child)

    scene = skppy.load("input.skp").to_scene()
    for node in walk(scene):
        if node.mesh:
            for face in node.mesh.faces:
                print(face.material_name, face.vertex_positions)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from .images import normalize_texture_scale

# -
# Geometry atoms
# -


def _require_aligned_length(name: str, values: object, expected: int) -> None:
    """Raise a descriptive error when a parallel sequence is misaligned."""
    try:
        actual = len(values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"{name} must be a sized sequence") from exc
    if actual != expected:
        raise ValueError(f"{name} must contain {expected} entries, got {actual}")


def _require_finite_rows(name: str, rows: object, *, width: int) -> None:
    """Validate a rectangular numeric sequence without retaining NumPy arrays."""
    array = np.asarray(rows, dtype=float)
    if array.size == 0:
        return
    if array.ndim != 2 or array.shape[1] != width:
        raise ValueError(f"{name} must contain rows of {width} numeric values")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite numeric values")


@dataclass(slots=True)
class PreparedFace:
    """
    A single planar polygon face, fully resolved and ready for export.

    Parameters
    ----------
    vertex_positions : list of (float, float, float)
        Ordered corner positions in definition-local SketchUp inches.
    vertex_uvs : list of (float, float) or None
        Per-corner UV coordinates ``(u, v)`` in tile-fraction space
        (repeating at every integer boundary). ``None`` when the face
        carries no textured material.
    normal : (float, float, float)
        Outward-facing unit normal ``(nx, ny, nz)`` from the face's plane
        equation ``ax + by + cz + d = 0``.
    material_name : str or None
        Name of the front-face material, or ``None`` for un-materialed faces.
    material_id : int or None
        Resolved effective material ID, or ``None`` for the default material.
    source_face_id : int or None
        Original SKP face ID that produced this prepared face.
    layer_id : int or None
        Reserved for the source layer/tag ID when entity-level layer data is
        available.
    edge_ids : list of int or None, optional
        Source SKP edge IDs for each polygon boundary edge. Entry ``i``
        describes the edge from corner ``i`` to corner ``(i + 1) % n``.
        ``None`` marks generated edges such as triangulation diagonals.
    edge_flags : list of int, optional
        Source SKP edge flags aligned with ``edge_ids``. Generated edges use
        ``0``.
    """

    vertex_positions: List[Tuple[float, float, float]]
    vertex_uvs: Optional[List[Tuple[float, float]]]
    normal: Tuple[float, float, float]
    material_name: Optional[str]
    material_id: Optional[int] = None
    source_face_id: Optional[int] = None
    layer_id: Optional[int] = None
    edge_ids: Optional[List[Optional[int]]] = None
    edge_flags: Optional[List[int]] = None

    def __post_init__(self) -> None:
        """Validate per-corner data before it reaches an importer."""
        corner_count = len(self.vertex_positions)
        if corner_count < 3:
            raise ValueError("PreparedFace requires at least three vertices")
        _require_finite_rows("vertex_positions", self.vertex_positions, width=3)
        _require_finite_rows("normal", [self.normal], width=3)
        if self.vertex_uvs is not None:
            _require_aligned_length("vertex_uvs", self.vertex_uvs, corner_count)
            _require_finite_rows("vertex_uvs", self.vertex_uvs, width=2)
        if self.edge_ids is not None:
            _require_aligned_length("edge_ids", self.edge_ids, corner_count)
        if self.edge_flags is not None:
            _require_aligned_length("edge_flags", self.edge_flags, corner_count)


@dataclass(slots=True)
class IndexedPreparedMesh:
    """
    Indexed, renderer-neutral mesh generated from :class:`PreparedMesh`.

    This is the most general mesh output skppy provides to importers.  It keeps
    geometry indexed while preserving per-face material, UV, normal, layer, and
    source-face metadata in parallel arrays.

    Parameters
    ----------
    vertex_positions : list of (float, float, float)
        Unique or per-corner vertex positions in SketchUp inches.
    faces : list of list of int
        Polygon corner indices into ``vertex_positions``.
    face_uvs : list of list of (float, float) or None
        Per-loop UVs for each face.  Entries align with ``faces``.
    face_normals : list of (float, float, float)
        Face normals aligned with ``faces``.
    face_material_names : list of str or None
        Resolved material names aligned with ``faces``.
    face_material_ids : list of int or None
        Resolved material IDs aligned with ``faces``.
    source_face_ids : list of int or None
        Original SKP face IDs aligned with ``faces``.
    layer_ids : list of int or None
        Source layer/tag IDs aligned with ``faces`` when known.
    face_edge_ids : list of list of int or None
        Source SKP edge IDs for each indexed face boundary edge. Entries align
        with ``faces``.
    face_edge_flags : list of list of int
        Source SKP edge flags aligned with ``face_edge_ids``.
    """

    vertex_positions: List[Tuple[float, float, float]]
    faces: List[List[int]]
    face_uvs: List[Optional[List[Tuple[float, float]]]]
    face_normals: List[Tuple[float, float, float]]
    face_material_names: List[Optional[str]]
    face_material_ids: List[Optional[int]]
    source_face_ids: List[Optional[int]]
    layer_ids: List[Optional[int]]
    face_edge_ids: List[List[Optional[int]]]
    face_edge_flags: List[List[int]]

    def __post_init__(self) -> None:
        """Validate indexed geometry and all face-aligned metadata arrays."""
        _require_finite_rows("vertex_positions", self.vertex_positions, width=3)
        face_count = len(self.faces)
        aligned = {
            "face_uvs": self.face_uvs,
            "face_normals": self.face_normals,
            "face_material_names": self.face_material_names,
            "face_material_ids": self.face_material_ids,
            "source_face_ids": self.source_face_ids,
            "layer_ids": self.layer_ids,
            "face_edge_ids": self.face_edge_ids,
            "face_edge_flags": self.face_edge_flags,
        }
        for name, values in aligned.items():
            _require_aligned_length(name, values, face_count)

        _require_finite_rows("face_normals", self.face_normals, width=3)
        vertex_count = len(self.vertex_positions)
        for face_index, face in enumerate(self.faces):
            if len(face) < 3:
                raise ValueError(f"faces[{face_index}] requires at least three indices")
            if any(index < 0 or index >= vertex_count for index in face):
                raise ValueError(f"faces[{face_index}] contains an index outside 0..{vertex_count - 1}")
            uvs = self.face_uvs[face_index]
            if uvs is not None:
                _require_aligned_length(f"face_uvs[{face_index}]", uvs, len(face))
                _require_finite_rows(f"face_uvs[{face_index}]", uvs, width=2)
            _require_aligned_length(
                f"face_edge_ids[{face_index}]",
                self.face_edge_ids[face_index],
                len(face),
            )
            _require_aligned_length(
                f"face_edge_flags[{face_index}]",
                self.face_edge_flags[face_index],
                len(face),
            )


@dataclass(slots=True)
class PreparedMesh:
    """
    All faces belonging to one entities scope (a definition or root level).

    Faces share no vertex array -- each face owns its corner list.  This
    mirrors the SKP model structure and simplifies importer code that works
    face-by-face (e.g. Blender bmesh insertion).

    Parameters
    ----------
    name : str
        Human-readable name (definition name or ``"RootGeometry"``).
    faces : list of PreparedFace
        Ordered list of prepared faces.
    """

    name: str
    faces: List[PreparedFace] = field(default_factory=list)

    def to_indexed(
        self,
        *,
        merge_vertices: bool = False,
        triangulate: bool = False,
        precision: int = 9,
    ) -> IndexedPreparedMesh:
        """
        Convert this face-owned mesh into an indexed mesh.

        Parameters
        ----------
        merge_vertices : bool, optional
            Reuse vertices at identical positions.  UVs remain per-loop, so
            texture seams are preserved even when positions are shared.
        triangulate : bool, optional
            Emit triangles for faces with more than three corners using the
            skppy triangulator.  Faces that cannot be triangulated fall back to
            a simple fan.
        precision : int, optional
            Decimal places used when comparing positions for vertex merging.

        Returns
        -------
        IndexedPreparedMesh
            Indexed geometry plus per-face metadata, still in SketchUp inches.
        """
        from .mesh_indexing import index_prepared_mesh

        return index_prepared_mesh(
            self,
            merge_vertices=merge_vertices,
            triangulate=triangulate,
            precision=precision,
        )


# -
# Scene hierarchy node
# -


@dataclass(slots=True)
class SceneNode:
    """
    A node in the import scene hierarchy.

    The tree mirrors the SketchUp component instance / group nesting:

    * The root node has ``transform = identity``, ``mesh = None``, and
      children for ``RootGeometry`` and every top-level instance/group.
    * A leaf node has a ``mesh`` and no children (or both, for mixed
      definitions).
    * Container nodes have children but may have ``mesh = None``.

    Parameters
    ----------
    name : str
        Display name (instance name or definition name).
    transform : list of float
        13-float row-major SUTransformation as stored in the SKP TLV.
        The root node uses the identity transform.
    mesh : PreparedMesh or None
        Pre-computed geometry for this node's definition scope, or ``None``
        if the definition has no direct faces.
    children : list of SceneNode
        Sub-nodes for nested instances and groups, in the order they appear
        in the parent's entities.
    material_name : str or None
        Instance-level material override (applied to un-materialed faces in
        ``mesh``). ``None`` if no override is set.
    """

    name: str
    transform: List[float]
    mesh: Optional[PreparedMesh]
    children: List["SceneNode"]
    material_name: Optional[str] = None


# -
# Internal helpers (used by Entities.prepare_mesh)
# -


def _unit_normal(a: float, b: float, c: float) -> Tuple[float, float, float]:
    """Normalise a plane normal ``(a, b, c)`` to a unit vector."""
    length = math.sqrt(a * a + b * b + c * c)
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    return (a / length, b / length, c / length)


def _planar_uv(
    positions: List[Tuple[float, float, float]],
    normal: Tuple[float, float, float],
    x_scale: float,
    y_scale: float,
) -> List[Tuple[float, float]]:
    """
    Compute orientation-aware planar UV coordinates.

    Used as a fallback when no stored UV projection is available or the stored
    projection matrix is singular.

    Parameters
    ----------
    positions : list of (float, float, float)
        Vertex positions in SketchUp inches.
    normal : (float, float, float)
        Face normal unit vector.
    x_scale : float
        Texture tile width in inches.
    y_scale : float
        Texture tile height in inches.

    Returns
    -------
    list of (float, float)
        UV coordinates for each vertex.
    """
    if not positions:
        return []

    x_scale = normalize_texture_scale(x_scale)
    y_scale = normalize_texture_scale(y_scale)
    nx, ny, nz = normal
    points = np.asarray(positions, dtype=float)
    # Choose the dominant axis to drop
    abs_nx, abs_ny, abs_nz = abs(nx), abs(ny), abs(nz)
    if abs_nz >= abs_nx and abs_nz >= abs_ny:
        # Drop Z: use X and Y
        uv = points[:, [0, 1]] / np.array([x_scale, y_scale], dtype=float)
    elif abs_nx >= abs_ny:
        # Drop X: use Y and Z
        uv = points[:, [1, 2]] / np.array([x_scale, y_scale], dtype=float)
    else:
        # Drop Y: use X and Z
        uv = points[:, [0, 2]] / np.array([x_scale, y_scale], dtype=float)
    return [(float(u), float(v)) for u, v in uv]
