# SPDX-License-Identifier: MIT
"""
Utility helpers for working with parsed SketchUp models.

Functions
---------
inches_to_meters        : Convert SketchUp internal units to Blender meters.
triangulate_face        : Fan-triangulate a Face's outer loop.
transform_to_matrix4x4  : Convert SUTransformation 13-float list to a 4x4 matrix.
"""

from __future__ import annotations

from typing import Dict, List, Tuple, cast

from .data_structure.entities import (
    Entities,
    Face,
)
from .data_structure.primitives import (
    Transform,
)

_INCHES_PER_METER = 39.3700787402


def inches_to_meters(value: float) -> float:
    """Convert SketchUp internal units (inches) to metres.

    Parameters
    ----------
    value : float
        Length in SketchUp inches.

    Returns
    -------
    float
        Length in metres.
    """
    return value / _INCHES_PER_METER


def meters_to_inches(value: float) -> float:
    """Convert metres to SketchUp internal units (inches).

    Parameters
    ----------
    value : float
        Length in metres.

    Returns
    -------
    float
        Length in SketchUp inches.
    """
    return value * _INCHES_PER_METER


def triangulate_face(
    face: Face,
    entities: Entities,
) -> List[Tuple[int, int, int]]:
    """
    Fan-triangulate the outer loop of *face*.

    Parameters
    ----------
    face      : Face to triangulate.
    entities  : Entities object that owns the edges referenced by the face.

    Returns
    -------
    list of (int, int, int)
        Vertex-ID triples forming triangles.

    Notes
    -----
    This is a simple fan triangulation from the first vertex.  Inner loops
    (holes) are **not** handled.  For proper ear-clipping with hole support
    use :func:`skppy.triangulation.triangulate_face_3d`.
    """
    edge_map: Dict[int, Tuple[int, int]] = {e.id: (e.start_vertex_id, e.end_vertex_id) for e in entities.edges}
    vids = face.outer_loop.vertex_ids(edge_map)
    if len(vids) < 3:
        return []

    # Simple fan triangulation from the first vertex
    triangles: List[Tuple[int, int, int]] = []
    v0 = vids[0]
    for i in range(1, len(vids) - 1):
        triangles.append((v0, vids[i], vids[i + 1]))
    return triangles


# -
# Transform helper
# -


def transform_to_matrix4x4(transform_13d: List[float]) -> List[List[float]]:
    """Convert a 13-float SUTransformation to a 4x4 row-major matrix.

    The 13-float layout is::

        [m00, m01, m02,  m10, m11, m12,  m20, m21, m22,  tx, ty, tz,  w]

    Parameters
    ----------
    transform_13d : list of float
        13-float SUTransformation.

    Returns
    -------
    list of list of float
        4x4 row-major matrix.
    """
    return cast(List[List[float]], Transform(transform_13d).matrix.tolist())
