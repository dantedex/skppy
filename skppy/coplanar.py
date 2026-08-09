# SPDX-License-Identifier: MIT
"""Pure topology helpers for merging adjacent coplanar mesh polygons."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose


@dataclass(frozen=True, slots=True)
class PolygonBoundary:
    """Minimal polygon data needed by the coplanar region builder."""

    index: int
    vertices: tuple[int, ...]
    edges: tuple[int, ...]
    normal: tuple[float, float, float]
    plane_offset: float
    material_index: int
    projection_key: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class DirectedBoundary:
    """One retained mesh edge and its direction around a region boundary."""

    edge_index: int
    start_vertex: int
    end_vertex: int


@dataclass(frozen=True, slots=True)
class CoplanarRegion:
    """Connected coplanar polygons represented by their closed boundaries."""

    polygons: tuple[int, ...]
    loops: tuple[tuple[DirectedBoundary, ...], ...]


def merge_coplanar_polygons(
    polygons: list[PolygonBoundary],
    positions: dict[int, tuple[float, float, float]],
    *,
    normal_tolerance: float = 1.0e-6,
    distance_tolerance: float = 1.0e-6,
) -> list[CoplanarRegion]:
    """Merge edge-connected polygons with matching planes and materials."""
    polygon_by_index = {polygon.index: polygon for polygon in polygons}
    edge_owners: dict[int, list[int]] = {}
    for polygon in polygons:
        for edge in polygon.edges:
            edge_owners.setdefault(edge, []).append(polygon.index)

    neighbors: dict[int, set[int]] = {polygon.index: set() for polygon in polygons}
    for owners in edge_owners.values():
        for index, owner in enumerate(owners):
            for other in owners[index + 1 :]:
                if _compatible(polygon_by_index[owner], polygon_by_index[other], normal_tolerance, distance_tolerance):
                    neighbors[owner].add(other)
                    neighbors[other].add(owner)

    regions: list[CoplanarRegion] = []
    remaining = set(polygon_by_index)
    while remaining:
        seed = min(remaining)
        members: set[int] = set()
        pending = [seed]
        while pending:
            current = pending.pop()
            if current in members:
                continue
            members.add(current)
            pending.extend(neighbors[current] - members)
        remaining -= members
        region_polygons = [polygon_by_index[index] for index in sorted(members)]
        loops = _boundary_loops(region_polygons)
        loops.sort(key=lambda loop: abs(_projected_area(loop, positions, region_polygons[0].normal)), reverse=True)
        regions.append(CoplanarRegion(tuple(sorted(members)), tuple(loops)))
    return regions


def _compatible(
    left: PolygonBoundary,
    right: PolygonBoundary,
    normal_tolerance: float,
    distance_tolerance: float,
) -> bool:
    return (
        left.material_index == right.material_index
        and left.projection_key == right.projection_key
        and all(isclose(a, b, abs_tol=normal_tolerance) for a, b in zip(left.normal, right.normal))
        and isclose(left.plane_offset, right.plane_offset, abs_tol=distance_tolerance)
    )


def _boundary_loops(polygons: list[PolygonBoundary]) -> list[tuple[DirectedBoundary, ...]]:
    occurrences: dict[int, list[DirectedBoundary]] = {}
    for polygon in polygons:
        for offset, edge_index in enumerate(polygon.edges):
            boundary = DirectedBoundary(
                edge_index,
                polygon.vertices[offset],
                polygon.vertices[(offset + 1) % len(polygon.vertices)],
            )
            occurrences.setdefault(edge_index, []).append(boundary)

    boundary_edges = [values[0] for values in occurrences.values() if len(values) == 1]
    outgoing: dict[int, list[DirectedBoundary]] = {}
    for boundary in boundary_edges:
        outgoing.setdefault(boundary.start_vertex, []).append(boundary)
    for values in outgoing.values():
        values.sort(key=lambda item: (item.end_vertex, item.edge_index), reverse=True)

    unused = {boundary.edge_index for boundary in boundary_edges}
    loops: list[tuple[DirectedBoundary, ...]] = []
    while unused:
        first = min(
            (boundary for boundary in boundary_edges if boundary.edge_index in unused), key=lambda item: item.edge_index
        )
        loop = [first]
        unused.remove(first.edge_index)
        current = first.end_vertex
        while current != first.start_vertex:
            candidates = [boundary for boundary in outgoing.get(current, ()) if boundary.edge_index in unused]
            if not candidates:
                raise ValueError("Coplanar region has an open or non-manifold boundary")
            boundary = candidates[-1]
            loop.append(boundary)
            unused.remove(boundary.edge_index)
            current = boundary.end_vertex
        loops.append(tuple(loop))
    return loops


def _projected_area(
    loop: tuple[DirectedBoundary, ...],
    positions: dict[int, tuple[float, float, float]],
    normal: tuple[float, float, float],
) -> float:
    axis = max(range(3), key=lambda index: abs(normal[index]))
    coordinates = [positions[edge.start_vertex] for edge in loop]
    dimensions = tuple(index for index in range(3) if index != axis)
    return 0.5 * sum(
        left[dimensions[0]] * right[dimensions[1]] - right[dimensions[0]] * left[dimensions[1]]
        for left, right in zip(coordinates, coordinates[1:] + coordinates[:1])
    )
