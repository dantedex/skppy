# SPDX-License-Identifier: MIT
"""
Polygon triangulation with hole support for skppy.

This module keeps the topology-heavy triangulation logic local to skppy and
uses NumPy for projection and polygon-area vector operations. NumPy is a core
project dependency and is bundled with supported Blender versions.

Algorithm
---------
1. Project the 3-D polygon to 2-D using the face normal as the projection axis.
2. For each inner loop (hole), find a bridge edge to the outer polygon by
   locating the hole vertex with the maximum X coordinate and ray-casting
   horizontally to find a visible outer vertex.
3. Merge all loops into a single simple polygon using the bridge edges.
4. Run quality-guided ear-clipping on the merged simple polygon.

Usage
-----
::

    from skppy.triangulation import triangulate_face_3d

    tris = triangulate_face_3d(
        outer_positions=[(x0,y0,z0), ...],
        hole_positions=[[(x,y,z), ...], ...],   # one list per hole
        normal=(nx, ny, nz),
    )
    # tris is a list of (i, j, k) index triples into outer + hole vertices
    # concatenated in the same order as supplied.

Edge Cases and Known Strategies
--------------------------------
Self-touching outer polygon
    SketchUp occasionally stores an outer boundary that visits the same 3-D
    point twice (e.g. a wall with a rectangular notch where the boundary
    doubles back).  In 2-D projection this creates a polygon where
    v[i] == v[j] for i != j.  Standard ear-clipping can stall because no
    strictly-convex ear exists at the touching vertices. When the ear-clip
    loop fails to make progress, repeated bridge vertices split its remainder
    into cycles. Counter-clockwise filled cycles are triangulated recursively;
    clockwise hole cycles are discarded so overlapping triangles cannot cover
    an opening in Blender.

Bridge-duplicate vertices (multiple holes sharing an outer vertex)
    After merging the first hole the merged polygon contains the chosen outer
    bridge vertex *twice* (once from each side of the bridge).  When a second
    hole tries to bridge to the same outer vertex it would create a *triple*
    occurrence, which ear-clipping cannot resolve.  Strategy: the
    ``_find_bridge_target`` function uses a ``Counter`` to track how many times
    each outer vertex already appears and prefers vertices with the lowest
    occurrence count (ties broken by polar angle from the hole's rightmost
    point).  The early-return path is only taken when the ray-cast candidate
    has occurrence count == 1.

Collinear bridge candidates
    When the +X ray from the hole's rightmost vertex hits an outer edge exactly
    at a collinear outer vertex (a vertex lying exactly on the ray), the
    triangle formed by (m, p_collinear, p_next) may have zero area.  The
    ``_has_collinear_better`` check detects whether a closer collinear vertex
    exists; if so the early-return is skipped and the polar-angle scan finds the
    geometrically correct nearest vertex.

Strict point-in-triangle test
    ``_point_in_triangle`` uses a **strict** test (all three signed areas > 0).
    Boundary points (d == 0) are treated as *outside* the triangle.  This is
    intentional: bridge-duplicate vertices produce collinear triplets, and
    treating them as "inside" would incorrectly invalidate valid ears adjacent
    to touching points.

Degenerate polygons
    Fewer than 3 outer vertices, zero-area outer polygon, or a normal vector of
    zero magnitude all return an empty triangle list without raising an
    exception.  Hole lists containing fewer than 3 vertices are silently
    ignored.

2-D projection
    The face normal determines the drop axis (the axis most parallel to the
    normal is eliminated).  Two orthogonal axes on the face plane are computed
    via cross products.  If the normal has near-zero magnitude the fallback is
    the XY plane.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import List, Optional, Tuple

import numpy as np

# SketchUp coordinates are stored in inches. Keep dimensional tolerances named
# so length, squared-length, and projected-area comparisons cannot be mixed by
# accident when the triangulator evolves.
_LENGTH_EPSILON = 1e-12
_SQUARED_LENGTH_EPSILON = _LENGTH_EPSILON**2
_PROJECTED_AREA_EPSILON = 1e-12

# Scanning every candidate ear and every remaining vertex is cubic. Preserve
# quality selection for ordinary model faces and use deterministic first-ear
# clipping for large CAD boundaries.
_MAX_QUALITY_GUIDED_EAR_VERTICES = 256

# -
# Public API
# -


def triangulate_face_3d(
    outer_positions: List[Tuple[float, float, float]],
    hole_positions: Optional[List[List[Tuple[float, float, float]]]] = None,
    normal: Tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> List[Tuple[int, int, int]]:
    """
    Triangulate a 3-D polygon (with optional holes) and return index triples.

    Parameters
    ----------
    outer_positions
        Ordered 3-D vertices of the outer polygon.
    hole_positions
        Optional list of holes; each hole is an ordered list of 3-D vertices.
        Hole winding should be opposite to the outer polygon winding.
    normal
        Face outward normal used to choose the projection plane.

    Returns
    -------
    list of (i, j, k)
        Triangle index triples.  Indices 0 ... len(outer)-1 refer to
        *outer_positions*; indices len(outer) ... refer to the hole vertices
        concatenated in the order they were supplied.
        Returns an empty list for degenerate input.
    """
    if len(outer_positions) < 3:
        return []

    holes = hole_positions or []
    has_holes = bool(holes)

    # Build a flat global vertex list: outer first, then each hole in order.
    all_positions: List[Tuple[float, float, float]] = list(outer_positions)
    hole_starts: List[int] = []
    if has_holes:
        for hp in holes:
            hole_starts.append(len(all_positions))
            all_positions.extend(hp)

    # - 1. Project to 2-D ---------
    pts2d = _project_to_2d(all_positions, normal)

    outer_count = len(outer_positions)
    outer_ids = list(range(outer_count))

    hole_id_lists: List[List[int]] = []
    if has_holes:
        for start, hp in zip(hole_starts, holes):
            hole_id_lists.append(list(range(start, start + len(hp))))

    # - 2. Split multiple holes into simple polygons when possible -----
    if len(hole_id_lists) > 1:
        polygons = _split_holes_into_simple_polygons(outer_ids, hole_id_lists, pts2d)
        if polygons is not None:
            triangles = [triangle for polygon in polygons for triangle in _ear_clip(polygon, pts2d)]
            return _nondegenerate_triangles(triangles, pts2d)

    # - 3. Merge remaining holes into a weakly simple polygon -----
    merged = _merge_holes(outer_ids, hole_id_lists, pts2d)
    # - 4. Ear-clip the merged polygon ------
    return _ear_clip(merged, pts2d)


def split_single_hole_face_3d(
    outer_positions: List[Tuple[float, float, float]],
    hole_positions: List[Tuple[float, float, float]],
    normal: Tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> List[List[int]]:
    """
    Split a polygon with one hole into two simple polygons.

    Blender meshes cannot represent a face with a true hole.  For n-gon import
    modes, a single-hole face can still be represented as two simple n-gons by
    inserting two generated bridge edges between the outer loop and the inner
    loop.  The returned indices refer to ``outer_positions + hole_positions``.

    Parameters
    ----------
    outer_positions : list of tuple of float
        Exterior loop positions in 3-D.
    hole_positions : list of tuple of float
        Single interior loop positions in 3-D.
    normal : tuple of float, optional
        Face normal used to choose the 2-D projection plane.

    Returns
    -------
    list of list of int
        Two n-gon index loops on success.  Returns an empty list when a safe
        pair of bridge edges cannot be found.  Multi-hole faces must still be
        triangulated.
    """
    if len(outer_positions) < 3 or len(hole_positions) < 3:
        return []

    all_positions = list(outer_positions) + list(hole_positions)
    pts = _project_to_2d(all_positions, normal)
    outer = list(range(len(outer_positions)))
    hole_start = len(outer_positions)
    hole = list(range(hole_start, hole_start + len(hole_positions)))

    bridge_pair = _find_split_bridge_pair(outer, hole, pts)
    if bridge_pair is None:
        return []

    outer_a, hole_a, outer_b, hole_b = bridge_pair
    outer_area = _signed_polygon_area2([pts[idx] for idx in outer])
    target_sign = 1.0 if outer_area >= 0.0 else -1.0

    first = _loop_arc(outer, outer_a, outer_b) + _loop_arc(hole, hole_b, hole_a)
    second = _loop_arc(outer, outer_b, outer_a) + _loop_arc(hole, hole_a, hole_b)

    polygons: List[List[int]] = []
    for poly in (first, second):
        if len(set(poly)) < 3:
            return []
        area = _signed_polygon_area2([pts[idx] for idx in poly])
        if abs(area) < _PROJECTED_AREA_EPSILON:
            return []
        if area * target_sign < 0.0:
            poly = list(reversed(poly))
        polygons.append(poly)
    return polygons


def _triangle_group_adjacency(
    groups: dict[int, set[int]],
    triangles: List[Tuple[int, int, int]],
    pts: List[Tuple[float, float]],
) -> set[Tuple[int, int]]:
    """Return group pairs that share at least one current boundary edge."""
    edge_to_groups: dict[Tuple[int, int], set[int]] = {}
    for group_id, triangle_ids in groups.items():
        loop = _boundary_loop_for_triangle_group(triangle_ids, triangles, pts)
        if loop is None:
            continue
        for edge in _loop_edges(loop):
            edge_to_groups.setdefault(_edge_key(*edge), set()).add(group_id)

    candidates: set[Tuple[int, int]] = set()
    for owners in edge_to_groups.values():
        owner_list = sorted(owners)
        candidates.update((left, right) for index, left in enumerate(owner_list) for right in owner_list[index + 1 :])
    return candidates


def _best_triangle_group_merge(
    candidates: set[Tuple[int, int]],
    groups: dict[int, set[int]],
    triangles: List[Tuple[int, int, int]],
    pts: List[Tuple[float, float]],
) -> tuple[int, int, set[int]] | None:
    """Choose the valid adjacent union containing the most source triangles."""
    best: tuple[int, int, set[int]] | None = None
    best_size = -1
    for left, right in sorted(candidates):
        merged_ids = groups[left] | groups[right]
        if _boundary_loop_for_triangle_group(merged_ids, triangles, pts) is None:
            continue
        if len(merged_ids) > best_size:
            best = left, right, merged_ids
            best_size = len(merged_ids)
    return best


def _triangle_group_loops(
    groups: dict[int, set[int]],
    triangles: List[Tuple[int, int, int]],
    pts: List[Tuple[float, float]],
) -> List[List[int]]:
    """Convert final groups to loops, retaining triangles for invalid unions."""
    loops: List[List[int]] = []
    for triangle_ids in groups.values():
        loop = _boundary_loop_for_triangle_group(triangle_ids, triangles, pts)
        if loop is not None:
            loops.append(loop)
            continue
        loops.extend(list(triangles[index]) for index in sorted(triangle_ids))
    loops.sort(key=lambda loop: (-len(loop), min(loop)))
    return loops


def merge_triangles_to_ngons(
    triangles: List[Tuple[int, int, int]],
    positions: List[Tuple[float, float, float]],
    normal: Tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> List[List[int]]:
    """
    Merge adjacent triangles into the smallest simple n-gons found greedily.

    The input triangle indices must reference *positions*.  The result contains
    one boundary loop per merged polygon.  A merge is accepted only when the
    union boundary is a single non-self-intersecting loop with no repeated
    vertices; unions that would still contain a hole are therefore rejected.

    Parameters
    ----------
    triangles : list of tuple of int
        Triangle index triples.
    positions : list of tuple of float
        3-D vertex positions referenced by *triangles*.
    normal : tuple of float, optional
        Face normal used to project vertices for simple-polygon checks.

    Returns
    -------
    list of list of int
        Merged polygon loops.  If no merge is possible each triangle is
        returned as a 3-vertex loop.
    """
    if not triangles:
        return []

    pts2d = _project_to_2d(positions, normal)
    groups: dict[int, set[int]] = {idx: {idx} for idx in range(len(triangles))}
    next_group_id = len(groups)

    while True:
        candidates = _triangle_group_adjacency(groups, triangles, pts2d)
        best = _best_triangle_group_merge(candidates, groups, triangles, pts2d)
        if best is None:
            break
        left, right, merged_tri_ids = best
        del groups[left]
        del groups[right]
        groups[next_group_id] = merged_tri_ids
        next_group_id += 1
    return _triangle_group_loops(groups, triangles, pts2d)


def _edge_key(a: int, b: int) -> Tuple[int, int]:
    """Return an orientation-independent edge key."""
    return (a, b) if a < b else (b, a)


def _loop_edges(loop: List[int]) -> List[Tuple[int, int]]:
    """Return directed edges around *loop*."""
    return [(loop[i], loop[(i + 1) % len(loop)]) for i in range(len(loop))]


def _triangle_group_boundary_edges(
    tri_ids: set[int],
    triangles: List[Tuple[int, int, int]],
) -> list[Tuple[int, int]]:
    """Return undirected edges used by exactly one triangle in a group."""
    edge_counts: dict[Tuple[int, int], int] = {}
    for tri_id in tri_ids:
        tri = triangles[tri_id]
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = _edge_key(a, b)
            edge_counts[key] = edge_counts.get(key, 0) + 1
    return [edge for edge, count in edge_counts.items() if count == 1]


def _boundary_adjacency(
    boundary_edges: list[Tuple[int, int]],
) -> dict[int, list[int]] | None:
    """Build a degree-two adjacency map for one closed boundary."""
    if len(boundary_edges) < 3:
        return None
    adjacency: dict[int, list[int]] = {}
    for a, b in boundary_edges:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    if any(len(neighbors) != 2 for neighbors in adjacency.values()):
        return None
    return adjacency


def _trace_boundary_loop(adjacency: dict[int, list[int]], edge_count: int) -> List[int] | None:
    """Walk one degree-two component and reject disconnected boundaries."""
    start = min(adjacency)
    prev: int | None = None
    current = start
    loop: List[int] = []
    for _ in range(edge_count + 1):
        loop.append(current)
        neighbors = adjacency[current]
        nxt = neighbors[0] if neighbors[0] != prev else neighbors[1]
        prev, current = current, nxt
        if current == start:
            break
    else:
        return None

    if len(loop) != len(adjacency) or len(set(loop)) != len(loop) or current != start:
        return None
    return loop


def _boundary_loop_for_triangle_group(
    tri_ids: set[int],
    triangles: List[Tuple[int, int, int]],
    pts: List[Tuple[float, float]],
) -> List[int] | None:
    """Return a single simple boundary loop for a set of triangles, if possible."""
    boundary_edges = _triangle_group_boundary_edges(tri_ids, triangles)
    adjacency = _boundary_adjacency(boundary_edges)
    if adjacency is None:
        return None
    loop = _trace_boundary_loop(adjacency, len(boundary_edges))
    if loop is None or not _is_simple_boundary_loop(loop, pts):
        return None

    area = _signed_polygon_area2([pts[idx] for idx in loop])
    if abs(area) < _PROJECTED_AREA_EPSILON:
        return None
    if area < 0.0:
        loop.reverse()
    return loop


def _boundary_edges_conflict(
    first: Tuple[int, int],
    second: Tuple[int, int],
    pts: List[Tuple[float, float]],
) -> bool:
    """Return whether non-adjacent edges intersect or touch internally."""
    a, b = first
    c, d = second
    if a in (c, d) or b in (c, d):
        return False
    ax, ay = pts[a]
    bx, by = pts[b]
    cx, cy = pts[c]
    dx, dy = pts[d]
    return any(
        (
            _segments_intersect(ax, ay, bx, by, cx, cy, dx, dy),
            _point_on_segment(cx, cy, ax, ay, bx, by),
            _point_on_segment(dx, dy, ax, ay, bx, by),
            _point_on_segment(ax, ay, cx, cy, dx, dy),
            _point_on_segment(bx, by, cx, cy, dx, dy),
        )
    )


def _is_simple_boundary_loop(
    loop: List[int],
    pts: List[Tuple[float, float]],
) -> bool:
    """Return True when *loop* is a non-self-intersecting polygon boundary."""
    if len(loop) < 3:
        return False

    edges = _loop_edges(loop)
    for index, first in enumerate(edges):
        for second in edges[index + 1 :]:
            if _boundary_edges_conflict(first, second, pts):
                return False
    return True


# -
# 2-D projection
# -


def _project_to_2d(
    positions: List[Tuple[float, float, float]],
    normal: Tuple[float, float, float],
) -> List[Tuple[float, float]]:
    """
    Project 3-D points onto the plane perpendicular to *normal*.

    We choose two orthogonal axes (u, v) on that plane and return 2-D
    coordinates for each point.
    """
    pts = np.asarray(positions, dtype=float)
    n = np.asarray(normal, dtype=float)
    n_len = np.linalg.norm(n)
    if n_len < _LENGTH_EPSILON:
        # Degenerate normal: fall back to XY plane.
        return [(float(p[0]), float(p[1])) for p in positions]
    n = n / n_len

    # Build a local u axis perpendicular to the normal.
    abs_n = np.abs(n)
    if abs_n[0] <= abs_n[1] and abs_n[0] <= abs_n[2]:
        ref = np.array([1.0, 0.0, 0.0])
    elif abs_n[1] <= abs_n[2]:
        ref = np.array([0.0, 1.0, 0.0])
    else:
        ref = np.array([0.0, 0.0, 1.0])

    # u = ref x n  (normalised)
    u = np.cross(ref, n)
    u = u / np.linalg.norm(u)

    # v = n x u
    v = np.cross(n, u)

    # Project all points at once
    coords = np.column_stack((pts @ u, pts @ v))
    return [(float(x), float(y)) for x, y in coords]


def _find_split_bridge_pair(
    outer: List[int],
    hole: List[int],
    pts: List[Tuple[float, float]],
    obstacle_loops: Optional[List[List[int]]] = None,
) -> Optional[Tuple[int, int, int, int]]:
    """Return two visible bridge pairs for splitting one hole into two faces."""
    candidates: List[Tuple[int, int, float]] = []
    loops = [outer, hole, *(obstacle_loops or [])]
    for outer_pos, outer_idx in enumerate(outer):
        for hole_pos, hole_idx in enumerate(hole):
            if _bridge_visible_between_loops(outer_idx, hole_idx, loops, pts):
                candidates.append((outer_pos, hole_pos, _dist2(pts[outer_idx], pts[hole_idx])))

    best_pair: Optional[Tuple[int, int, int, int]] = None
    best_score: Optional[Tuple[float, float, float]] = None
    outer_count = len(outer)
    hole_count = len(hole)

    for i, (outer_a, hole_a, len_a) in enumerate(candidates):
        for outer_b, hole_b, len_b in candidates[i + 1 :]:
            if outer_a == outer_b or hole_a == hole_b:
                continue
            if _segments_intersect(
                pts[outer[outer_a]][0],
                pts[outer[outer_a]][1],
                pts[hole[hole_a]][0],
                pts[hole[hole_a]][1],
                pts[outer[outer_b]][0],
                pts[outer[outer_b]][1],
                pts[hole[hole_b]][0],
                pts[hole[hole_b]][1],
            ):
                continue

            outer_forward = (outer_b - outer_a) % outer_count
            hole_forward = (hole_b - hole_a) % hole_count
            outer_sep = min(outer_forward, outer_count - outer_forward) / outer_count
            hole_sep = min(hole_forward, hole_count - hole_forward) / hole_count
            # Prefer bridges on opposite sides of both loops; tie-break toward
            # shorter generated edges so the artificial cuts stay unobtrusive.
            score = (
                min(outer_sep, hole_sep),
                outer_sep + hole_sep,
                -(len_a + len_b),
            )
            if best_score is None or score > best_score:
                best_score = score
                best_pair = (outer_a, hole_a, outer_b, hole_b)

    return best_pair


def _split_holes_into_simple_polygons(
    outer: List[int],
    holes: List[List[int]],
    pts: List[Tuple[float, float]],
) -> Optional[List[List[int]]]:
    """Remove several holes by splitting their containing polygon twice."""
    polygons = [list(outer)]
    for hole_index, hole in enumerate(holes):
        polygon_index = next(
            (index for index, polygon in enumerate(polygons) if _point_in_polygon(pts[hole[0]], polygon, pts)),
            None,
        )
        if polygon_index is None:
            return None

        polygon = polygons.pop(polygon_index)
        bridge_pair = _find_split_bridge_pair(polygon, hole, pts, holes[hole_index + 1 :])
        if bridge_pair is None:
            return None

        outer_a, hole_a, outer_b, hole_b = bridge_pair
        split_polygons = [
            _loop_arc(polygon, outer_a, outer_b) + _loop_arc(hole, hole_b, hole_a),
            _loop_arc(polygon, outer_b, outer_a) + _loop_arc(hole, hole_a, hole_b),
        ]
        for split_polygon in split_polygons:
            area = _signed_polygon_area2([pts[index] for index in split_polygon])
            if abs(area) < _PROJECTED_AREA_EPSILON:
                return None
            if area < 0.0:
                split_polygon.reverse()
        polygons[polygon_index:polygon_index] = split_polygons
    return polygons


def _bridge_visible_between_loops(
    a: int,
    b: int,
    loops: List[List[int]],
    pts: List[Tuple[float, float]],
) -> bool:
    """Return True when segment a-b does not cross either source loop."""
    ax, ay = pts[a]
    bx, by = pts[b]
    mid = ((ax + bx) * 0.5, (ay + by) * 0.5)
    if not _point_in_polygon(mid, loops[0], pts):
        return False
    for hole in loops[1:]:
        if _point_in_polygon(mid, hole, pts):
            return False

    for loop in loops:
        for pos, c in enumerate(loop):
            d = loop[(pos + 1) % len(loop)]
            if c == a or c == b or d == a or d == b:
                continue
            cx, cy = pts[c]
            dx, dy = pts[d]
            if _segments_intersect(ax, ay, bx, by, cx, cy, dx, dy):
                return False
            if _point_on_segment(cx, cy, ax, ay, bx, by) or _point_on_segment(dx, dy, ax, ay, bx, by):
                return False
    return True


def _loop_arc(loop: List[int], start_pos: int, end_pos: int) -> List[int]:
    """Return an inclusive forward arc through a circular loop."""
    arc = [loop[start_pos]]
    pos = start_pos
    while pos != end_pos:
        pos = (pos + 1) % len(loop)
        arc.append(loop[pos])
    return arc


def _signed_polygon_area2(points: List[Tuple[float, float]]) -> float:
    """Return twice the signed polygon area."""
    pts = np.asarray(points, dtype=float)
    if len(pts) < 3:
        return 0.0
    rolled = np.roll(pts, -1, axis=0)
    return float(np.sum(pts[:, 0] * rolled[:, 1] - pts[:, 1] * rolled[:, 0]))


def _point_in_polygon(
    point: Tuple[float, float],
    loop: List[int],
    pts: List[Tuple[float, float]],
) -> bool:
    """Return True when point is strictly inside a polygon loop."""
    px, py = point
    inside = False
    j = len(loop) - 1
    for i, curr in enumerate(loop):
        prev = loop[j]
        xi, yi = pts[curr]
        xj, yj = pts[prev]
        if (yi > py) != (yj > py):
            x_intersect = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < x_intersect:
                inside = not inside
        j = i
    return inside


def _point_on_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> bool:
    """Return True when p lies on segment a-b, excluding segment endpoints."""
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > _PROJECTED_AREA_EPSILON:
        return False
    dot = (px - ax) * (px - bx) + (py - ay) * (py - by)
    return dot < -_SQUARED_LENGTH_EPSILON


# -
# Hole merging (bridge edges)
# -


def _merge_holes(
    outer: List[int],
    holes: List[List[int]],
    pts: List[Tuple[float, float]],
) -> List[int]:
    """
    Merge each hole into the outer polygon by inserting bridge edges.

    For each hole (sorted by the X coord of their rightmost vertex, descending)
    we find a visible vertex on the outer/current polygon and cut a bridge.
    The result is a single simple polygon (possibly with repeated vertices at
    the bridge points).
    """
    poly = list(outer)
    for hole in sorted(holes, key=lambda h: -max(pts[i][0] for i in h)):
        poly = _cut_bridge(poly, hole, pts)
    return poly


def _cut_bridge(
    outer: List[int],
    hole: List[int],
    pts: List[Tuple[float, float]],
) -> List[int]:
    """
    Insert *hole* into *outer* using a bridge edge.

    The bridge connects:
    - ``m_idx``  -- the index within *hole* of its rightmost vertex.
    - ``p_idx``  -- the index within *outer* of the best visible outer vertex.

    The merged polygon is:
        outer[0..p] + [outer[p], hole[m], hole[m+1], ..., hole[m] (wrap), outer[p], outer[p+1..]]
    """
    # Find the rightmost vertex of the hole.
    m_local = max(range(len(hole)), key=lambda i: pts[hole[i]][0])
    m_global = hole[m_local]
    _mx, _my = pts[m_global]

    # Find the best visible vertex on the outer polygon.
    p_local = _find_bridge_target(m_global, outer, pts)
    p_global = outer[p_local]

    # Rotate the hole so that m_local is at position 0.
    rotated_hole = hole[m_local:] + hole[:m_local]

    # Build the merged polygon.
    before = outer[: p_local + 1]
    after = outer[p_local:]
    merged = before + rotated_hole + [m_global, p_global] + after[1:]
    return merged


def _ray_bridge_target(
    m: int,
    outer: List[int],
    pts: List[Tuple[float, float]],
) -> int | None:
    """Return the preferred endpoint of the nearest positive-X edge hit."""
    mx, my = pts[m]
    best_ix = math.inf
    best_local: int | None = None
    best_x = -math.inf
    n = len(outer)
    for i in range(n):
        a = outer[i]
        b = outer[(i + 1) % n]
        ax, ay = pts[a]
        bx, by = pts[b]

        if not (min(ay, by) <= my <= max(ay, by)):
            continue
        if ay == by:
            continue

        t = (my - ay) / (by - ay)
        ix = ax + t * (bx - ax)
        if ix < mx:
            continue

        ref_local = i if ax >= bx else (i + 1) % n
        ref_x = pts[outer[ref_local]][0]

        if ix < best_ix or (ix == best_ix and ref_x > best_x):
            best_ix = ix
            best_local = ref_local
            best_x = ref_x
    return best_local


def _best_visible_bridge_target(
    m: int,
    outer: List[int],
    pts: List[Tuple[float, float]],
    initial: int,
    initial_visible: bool,
    occurrences: Counter[int],
) -> int:
    """Prefer a visible, less-reused vertex and then the smallest polar angle."""
    mx, my = pts[m]
    initial_vertex = outer[initial]
    best_tangent = _polar_tan(mx, my, pts[initial_vertex]) if initial_visible else math.inf
    best_occurrences = occurrences[initial_vertex]
    chosen = initial
    for index, vertex in enumerate(outer):
        if pts[vertex][0] < mx or not _segment_visible(m, vertex, outer, pts):
            continue
        tangent = _polar_tan(mx, my, pts[vertex])
        candidate = occurrences[vertex], tangent
        if candidate < (best_occurrences, best_tangent):
            best_occurrences, best_tangent = candidate
            chosen = index
    return chosen


def _find_bridge_target(
    m: int,
    outer: List[int],
    pts: List[Tuple[float, float]],
) -> int:
    """
    Find the index within *outer* of the best vertex to bridge to from *m*.

    The nearest +X ray hit supplies the initial candidate. Visibility,
    occurrence count, and polar angle then avoid self-touching bridge reuse.
    """
    mx, my = pts[m]
    best_local = _ray_bridge_target(m, outer, pts)

    if best_local is None:
        return min(range(len(outer)), key=lambda i: _dist2(pts[outer[i]], (mx, my)))

    # After the first hole is merged the outer polygon may contain repeated
    # vertices (bridge duplicates).  The nearest-intersection heuristic can
    # then pick a vertex that is geometrically occluded by an already-merged
    # inner boundary.  Always verify actual visibility before accepting the
    # candidate; if it is occluded, fall back to the polar-angle scan.
    p = outer[best_local]
    p_visible = _segment_visible(m, p, outer, pts)

    # Compute occurrence counts early so the early-return path can also prefer
    # less-used bridge vertices.  Accepting a candidate that is already a
    # bridge duplicate (occ > 1) can force a triple occurrence and create a
    # self-touching topology that stalls ear-clipping; fall through to the
    # polar scan instead so a less-used vertex can be found.
    occ_count = Counter(outer)
    if p_visible and not _has_collinear_better(m, p, outer, pts, mx, my):
        if occ_count[p] == 1:
            return best_local

    # Scan for the outer vertex that forms the smallest polar angle from m
    # and is actually visible.  Start tan_ref from the initial candidate when
    # it is visible (collinear-better case), or from +inf when it is occluded.
    #
    # Tie-breaking: prefer vertices that appear FEWER TIMES in the outer
    # polygon.  When the same outer vertex is used as a bridge target for
    # multiple holes it becomes a "touching point" and appears in the polygon
    # more than once.  Triple (or higher) occurrences create self-touching
    # topologies that defeat standard ear-clipping.  By choosing a less-used
    # vertex when one is available and visible we keep the merged polygon as
    # simple as possible.

    return _best_visible_bridge_target(m, outer, pts, best_local, p_visible, occ_count)


def _has_collinear_better(
    m: int,
    p: int,
    outer: List[int],
    pts: List[Tuple[float, float]],
    mx: float,
    my: float,
) -> bool:
    """True if a collinear outer vertex closer to (mx, my) exists."""
    px, _py = pts[p]
    px_diff = abs(px - mx)
    for v in outer:
        if v == p:
            continue
        vx, vy = pts[v]
        if abs(vy - my) < _LENGTH_EPSILON and vx > mx and abs(vx - mx) < px_diff:
            return True
    return False


def _polar_tan(mx: float, my: float, pt: Tuple[float, float]) -> float:
    """Tangent of angle from (mx,my) to pt, used for angular ordering."""
    dx = pt[0] - mx
    dy = pt[1] - my
    if abs(dx) < _LENGTH_EPSILON:
        return math.inf if dy >= 0 else -math.inf
    return dy / dx


def _segment_visible(
    a: int,
    b: int,
    outer: List[int],
    pts: List[Tuple[float, float]],
) -> bool:
    """
    Return True if the segment (pts[a], pts[b]) does not cross any outer edge.
    """
    ax, ay = pts[a]
    bx, by = pts[b]
    n = len(outer)
    for i in range(n):
        c = outer[i]
        d = outer[(i + 1) % n]
        if c == a or c == b or d == a or d == b:
            continue
        if _segments_intersect(ax, ay, bx, by, pts[c][0], pts[c][1], pts[d][0], pts[d][1]):
            return False
    return True


def _dist2(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _segments_intersect(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> bool:
    """Strict intersection test (shared endpoints excluded)."""

    def _cross(ox: float, oy: float, ux: float, uy: float, vx: float, vy: float) -> float:
        return (ux - ox) * (vy - oy) - (uy - oy) * (vx - ox)

    d1 = _cross(cx, cy, dx, dy, ax, ay)
    d2 = _cross(cx, cy, dx, dy, bx, by)
    d3 = _cross(ax, ay, bx, by, cx, cy)
    d4 = _cross(ax, ay, bx, by, dx, dy)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    # Collinear cases: treat as non-intersecting (shared vertex segments).
    return False


# -
# Ear clipping
# -


def _best_ear(vertices: List[int], pts: List[Tuple[float, float]]) -> tuple[int, int, int] | None:
    """Return positions of the highest-quality valid ear."""
    best: tuple[int, int, int] | None = None
    best_quality = -1.0
    count = len(vertices)
    for current in range(count):
        previous = (current - 1) % count
        following = (current + 1) % count
        if not _is_ear(previous, current, following, vertices, pts):
            continue
        quality = _triangle_shape_quality(
            pts[vertices[previous]],
            pts[vertices[current]],
            pts[vertices[following]],
        )
        if quality > best_quality:
            best_quality = quality
            best = previous, current, following
    return best


def _first_ear(vertices: List[int], pts: List[Tuple[float, float]]) -> tuple[int, int, int] | None:
    """Return the first valid ear without the cubic quality scan."""
    count = len(vertices)
    for current in range(count):
        previous = (current - 1) % count
        following = (current + 1) % count
        if _is_ear(previous, current, following, vertices, pts):
            return previous, current, following
    return None


def _fan_triangles(vertices: List[int]) -> List[Tuple[int, int, int]]:
    """Return the deterministic fallback fan for a degenerate remainder."""
    return [(vertices[0], vertices[index], vertices[index + 1]) for index in range(1, len(vertices) - 1)]


def _nondegenerate_triangles(
    triangles: List[Tuple[int, int, int]],
    pts: List[Tuple[float, float]],
) -> List[Tuple[int, int, int]]:
    """Remove zero-area triangles introduced by collinear generated cuts."""
    return [
        triangle
        for triangle in triangles
        if abs(_signed_polygon_area2([pts[index] for index in triangle])) > _PROJECTED_AREA_EPSILON
    ]


def _split_repeated_vertex_cycle(vertices: List[int]) -> tuple[List[int], List[int]] | None:
    """Split a self-touching loop into two cycles at its first repeated vertex."""
    first_positions: dict[int, int] = {}
    for current, vertex in enumerate(vertices):
        first = first_positions.get(vertex)
        if first is None:
            first_positions[vertex] = current
            continue

        inside = vertices[first:current]
        outside = vertices[current:] + vertices[:first]
        if len(inside) >= 3 and len(outside) >= 3:
            return inside, outside
    return None


def _triangulate_positive_cycles(vertices: List[int], pts: List[Tuple[float, float]]) -> List[Tuple[int, int, int]]:
    """Triangulate filled cycles and discard clockwise hole cycles in a bridged remainder."""
    split = _split_repeated_vertex_cycle(vertices)
    if split is None:
        return _fan_triangles(vertices)

    triangles: List[Tuple[int, int, int]] = []
    for cycle in split:
        if _signed_polygon_area2([pts[index] for index in cycle]) > _PROJECTED_AREA_EPSILON:
            triangles.extend(_ear_clip(cycle, pts))
    return triangles


def _ear_clip(
    poly: List[int],
    pts: List[Tuple[float, float]],
) -> List[Tuple[int, int, int]]:
    """
    Quality-guided ear-clipping triangulation of a simple polygon.

    *poly* is an ordered list of global vertex indices (may have repeated
    vertices at bridge points from hole merging).
    *pts* maps global index -> (x, y).

    Returns a list of (i, j, k) index triples.

    At each step all valid ears are scanned and the triangle with the best
    scale-independent shape quality is clipped.  This keeps the triangulator
    deterministic while avoiding many long, skinny triangles that come from
    clipping the first valid ear in polygon order.
    """
    n = len(poly)
    if n < 3:
        return []
    if n == 3:
        return [(poly[0], poly[1], poly[2])]

    # Work with a mutable list of vertex indices.
    verts = list(poly)
    triangles: List[Tuple[int, int, int]] = []

    while len(verts) > 3:
        best_ear = _best_ear(verts, pts) if len(verts) <= _MAX_QUALITY_GUIDED_EAR_VERTICES else _first_ear(verts, pts)
        if best_ear is None:
            # A bridged multi-hole loop can retain self-touching sub-cycles after
            # valid ears are clipped. Keep only its counter-clockwise filled cycles.
            triangles.extend(_triangulate_positive_cycles(verts, pts))
            break

        prev_pos, curr_pos, next_pos = best_ear
        triangles.append((verts[prev_pos], verts[curr_pos], verts[next_pos]))
        verts.pop(curr_pos)

    if len(verts) == 3:
        triangles.append((verts[0], verts[1], verts[2]))

    return triangles


def _triangle_shape_quality(
    a: Tuple[float, float],
    b: Tuple[float, float],
    c: Tuple[float, float],
) -> float:
    """
    Return a scale-independent triangle quality score in the range [0, 1].

    The score is ``4 * sqrt(3) * area / sum(edge_length^2)``.  It is 1.0 for
    an equilateral triangle and approaches 0.0 as a triangle becomes long,
    skinny, or degenerate.
    """
    ax, ay = a
    bx, by = b
    cx, cy = c
    ab2 = (bx - ax) * (bx - ax) + (by - ay) * (by - ay)
    bc2 = (cx - bx) * (cx - bx) + (cy - by) * (cy - by)
    ca2 = (ax - cx) * (ax - cx) + (ay - cy) * (ay - cy)
    denom = ab2 + bc2 + ca2
    if denom <= _SQUARED_LENGTH_EPSILON:
        return 0.0

    area2 = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
    return (2.0 * math.sqrt(3.0) * area2) / denom


def _is_ear(
    prev_pos: int,
    curr_pos: int,
    next_pos: int,
    verts: List[int],
    pts: List[Tuple[float, float]],
) -> bool:
    """
    Return True if the vertex at position *curr_pos* in *verts* is a valid ear tip.

    Arguments are LIST POSITIONS into *verts*, not vertex indices.  This is
    critical for self-touching polygons produced by hole-bridge merging, where
    the same vertex index can appear at several distinct positions.  Using
    positions (rather than indices) ensures that each occurrence is treated as an
    independent entity during both the containment test and the diagonal check.

    Conditions:
    1. The triangle is convex (counter-clockwise winding relative to the polygon).
    2. No vertex at any OTHER position lies strictly inside the triangle.
    3. The new diagonal (verts[prev_pos] -> verts[next_pos]) does not strictly
       cross any existing polygon edge, skipping only those edges that share a
       position endpoint with the diagonal (i.e. the edges physically adjacent to
       prev_pos and next_pos, regardless of their vertex index).
    """
    n = len(verts)
    ax, ay = pts[verts[prev_pos]]
    bx, by = pts[verts[curr_pos]]
    cx, cy = pts[verts[next_pos]]

    # Condition 1: triangle must be convex (positive signed area for CCW polygon).
    area2 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if area2 <= 0:
        return False

    # Condition 2: no vertex at a different position may lie strictly inside the
    # triangle.  We iterate by POSITION so that duplicate vertex indices are each
    # tested independently.
    for pos in range(n):
        if pos == prev_pos or pos == curr_pos or pos == next_pos:
            continue
        if _point_in_triangle(pts[verts[pos]], (ax, ay), (bx, by), (cx, cy)):
            return False

    # Condition 3: the new diagonal must not strictly cross any existing edge.
    # We skip edges that share a POSITION endpoint with the diagonal (not just a
    # vertex index), so that duplicate-vertex bridge edges that happen to share an
    # index but are at a different list position are still checked.
    for pos in range(n):
        npos = (pos + 1) % n
        if pos == prev_pos or npos == prev_pos or pos == next_pos or npos == next_pos:
            continue
        ex, ey = pts[verts[pos]]
        fx, fy = pts[verts[npos]]
        if _segments_intersect(ax, ay, cx, cy, ex, ey, fx, fy):
            return False

    return True


def _point_in_triangle(
    p: Tuple[float, float],
    a: Tuple[float, float],
    b: Tuple[float, float],
    c: Tuple[float, float],
) -> bool:
    """Return True if point *p* is strictly inside triangle (a, b, c)."""

    def _sign(
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        p3: Tuple[float, float],
    ) -> float:
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1 = _sign(p, a, b)
    d2 = _sign(p, b, c)
    d3 = _sign(p, c, a)

    # A point is strictly inside a CCW triangle when all three signed areas are
    # positive.  Using not(has_neg and has_pos) incorrectly treats boundary
    # points (where one d == 0) as "inside", which can block valid ears in
    # polygons with bridge-duplicate vertices.
    return d1 > 0 and d2 > 0 and d3 > 0
