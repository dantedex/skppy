# SPDX-License-Identifier: MIT
"""Infer face openings created by glued cutting-component instances."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .entities import ComponentDefinition, ComponentInstance, Entities, Group
from .primitives import Transform

Position3D = tuple[float, float, float]
Position2D = tuple[float, float]
_TOLERANCE = 1.0e-7


def infer_cutting_openings(
    entities: Entities,
    definitions: dict[int, ComponentDefinition],
) -> dict[int, list[list[Position3D]]]:
    """Return transformed cutting contours grouped by their host face ID."""
    face_geometry = _resolved_face_geometry(entities)
    openings: dict[int, list[list[Position3D]]] = defaultdict(list)
    instances: list[ComponentInstance | Group] = [*entities.component_instances, *entities.groups]
    for instance in instances:
        definition = definitions.get(instance.definition_id)
        if definition is None or not definition.behavior_cuts_opening:
            continue
        outline = _cutting_outline(definition)
        if not outline:
            continue
        matrix = Transform(instance.transform).matrix
        transformed = [_transform_point(matrix, point) for point in outline]
        target = _find_host_face(transformed, face_geometry)
        if target is not None:
            face_id, contour = target
            openings[face_id].append(contour)
    return dict(openings)


def _cutting_outline(definition: ComponentDefinition) -> list[Position3D]:
    """Trace the largest planar face boundary in a cutting definition's glue plane."""
    vertices = {vertex.id: vertex.position for vertex in definition.entities.vertices}
    adjacency: dict[int, list[int]] = defaultdict(list)
    for edge in definition.entities.edges:
        start_position = vertices.get(edge.start_vertex_id)
        end_position = vertices.get(edge.end_vertex_id)
        if (
            start_position is None
            or end_position is None
            or abs(start_position.z) > _TOLERANCE
            or abs(end_position.z) > _TOLERANCE
        ):
            continue
        adjacency[edge.start_vertex_id].append(edge.end_vertex_id)
        adjacency[edge.end_vertex_id].append(edge.start_vertex_id)
    if not adjacency:
        return []

    ordered = {
        vertex_id: sorted(
            neighbors,
            key=lambda neighbor: math.atan2(
                vertices[neighbor].y - vertices[vertex_id].y,
                vertices[neighbor].x - vertices[vertex_id].x,
            ),
        )
        for vertex_id, neighbors in adjacency.items()
    }
    loops: list[tuple[float, list[int]]] = []
    visited: set[tuple[int, int]] = set()
    for directed_start, neighbors in ordered.items():
        for directed_end in neighbors:
            if (directed_start, directed_end) in visited:
                continue
            loop: list[int] = []
            previous, current = directed_start, directed_end
            while (previous, current) not in visited:
                visited.add((previous, current))
                loop.append(previous)
                current_neighbors = ordered[current]
                incoming = current_neighbors.index(previous)
                previous, current = current, current_neighbors[(incoming - 1) % len(current_neighbors)]
            if len(loop) >= 3:
                points = [(vertices[index].x, vertices[index].y) for index in loop]
                loops.append((_signed_area(points), loop))
    if not loops:
        return []
    _area, boundary = max(loops, key=lambda item: abs(item[0]))
    return [(vertices[index].x, vertices[index].y, 0.0) for index in boundary]


def _resolved_face_geometry(
    entities: Entities,
) -> list[tuple[int, tuple[float, float, float, float], list[Position3D]]]:
    """Resolve host face planes and outer-loop positions once."""
    edges = {edge.id: (edge.start_vertex_id, edge.end_vertex_id) for edge in entities.edges}
    vertices = {vertex.id: vertex.position.to_tuple() for vertex in entities.vertices}
    result = []
    for face in entities.faces:
        vertex_ids = face.outer_loop.vertex_ids(edges)
        if len(vertex_ids) >= 3 and all(vertex_id in vertices for vertex_id in vertex_ids):
            result.append((face.id, face.plane, [vertices[vertex_id] for vertex_id in vertex_ids]))
    return result


def _find_host_face(
    contour: list[Position3D],
    faces: list[tuple[int, tuple[float, float, float, float], list[Position3D]]],
) -> tuple[int, list[Position3D]] | None:
    """Choose the smallest coplanar face containing the opening centroid."""
    centroid = (
        sum(point[0] for point in contour) / len(contour),
        sum(point[1] for point in contour) / len(contour),
        sum(point[2] for point in contour) / len(contour),
    )
    candidates = []
    for face_id, plane, outer in faces:
        a, b, c, d = plane
        if any(abs(a * x + b * y + c * z + d) > _TOLERANCE for x, y, z in contour):
            continue
        drop_axis = max(range(3), key=lambda axis: abs(plane[axis]))
        outer_2d = [_drop_axis(point, drop_axis) for point in outer]
        if not _point_in_polygon(_drop_axis(centroid, drop_axis), outer_2d):
            continue
        candidates.append((abs(_signed_area(outer_2d)), face_id, drop_axis, plane, outer_2d))
    if not candidates:
        return None

    _area, face_id, drop_axis, plane, outer_2d = min(candidates)
    contour_2d = [_drop_axis(point, drop_axis) for point in contour]
    if not all(_point_in_polygon(point, outer_2d, include_boundary=True) for point in contour_2d):
        if not _is_convex(outer_2d):
            return None
        contour_2d = _clip_to_convex_polygon(contour_2d, outer_2d)
        if len(contour_2d) < 3:
            return None
        contour = [_restore_plane_point(point, drop_axis, plane) for point in contour_2d]
    if _signed_area(contour_2d) * _signed_area(outer_2d) > 0.0:
        contour.reverse()
    return face_id, contour


def _transform_point(matrix: np.ndarray, point: Position3D) -> Position3D:
    transformed = matrix @ np.array([*point, 1.0])
    return float(transformed[0]), float(transformed[1]), float(transformed[2])


def _drop_axis(point: Position3D, axis: int) -> Position2D:
    return tuple(value for index, value in enumerate(point) if index != axis)  # type: ignore[return-value]


def _restore_plane_point(
    point: Position2D,
    drop_axis: int,
    plane: tuple[float, float, float, float],
) -> Position3D:
    values = list(point)
    values.insert(drop_axis, 0.0)
    a, b, c, d = plane
    normal = (a, b, c)
    values[drop_axis] = (
        -(d + sum(normal[index] * values[index] for index in range(3) if index != drop_axis)) / normal[drop_axis]
    )
    return float(values[0]), float(values[1]), float(values[2])


def _signed_area(points: list[Position2D]) -> float:
    return 0.5 * sum(
        first[0] * second[1] - first[1] * second[0] for first, second in zip(points, points[1:] + points[:1])
    )


def _point_in_polygon(point: Position2D, polygon: list[Position2D], *, include_boundary: bool = False) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if include_boundary and _point_on_segment(point, previous, current):
            return True
        if (current[1] > y) != (previous[1] > y):
            crossing = (previous[0] - current[0]) * (y - current[1]) / (previous[1] - current[1]) + current[0]
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def _point_on_segment(point: Position2D, start: Position2D, end: Position2D) -> bool:
    cross = (point[0] - start[0]) * (end[1] - start[1]) - (point[1] - start[1]) * (end[0] - start[0])
    dot = (point[0] - start[0]) * (point[0] - end[0]) + (point[1] - start[1]) * (point[1] - end[1])
    return abs(cross) <= _TOLERANCE and dot <= _TOLERANCE


def _is_convex(polygon: list[Position2D]) -> bool:
    signs = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        following = polygon[(index + 1) % len(polygon)]
        cross = (current[0] - previous[0]) * (following[1] - current[1]) - (current[1] - previous[1]) * (
            following[0] - current[0]
        )
        if abs(cross) > _TOLERANCE:
            signs.append(cross > 0.0)
    return bool(signs) and all(sign == signs[0] for sign in signs)


def _clip_to_convex_polygon(subject: list[Position2D], clip: list[Position2D]) -> list[Position2D]:
    orientation = 1.0 if _signed_area(clip) > 0.0 else -1.0
    output = subject
    for edge_start, edge_end in zip(clip, clip[1:] + clip[:1]):
        source = output
        output = []
        if not source:
            break
        previous = source[-1]
        previous_inside = _inside_clip_edge(previous, edge_start, edge_end, orientation)
        for current in source:
            current_inside = _inside_clip_edge(current, edge_start, edge_end, orientation)
            if current_inside != previous_inside:
                output.append(_line_intersection(previous, current, edge_start, edge_end))
            if current_inside:
                output.append(current)
            previous, previous_inside = current, current_inside
    return output


def _inside_clip_edge(point: Position2D, start: Position2D, end: Position2D, orientation: float) -> bool:
    cross = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])
    return orientation * cross >= -_TOLERANCE


def _line_intersection(start: Position2D, end: Position2D, clip_start: Position2D, clip_end: Position2D) -> Position2D:
    dx, dy = end[0] - start[0], end[1] - start[1]
    ex, ey = clip_end[0] - clip_start[0], clip_end[1] - clip_start[1]
    denominator = dx * ey - dy * ex
    t = ((clip_start[0] - start[0]) * ey - (clip_start[1] - start[1]) * ex) / denominator
    return start[0] + t * dx, start[1] + t * dy
