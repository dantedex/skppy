# SPDX-License-Identifier: MIT
"""Real corner-normal regressions for GitHub issue #1."""

import importlib
import math

import bpy


def run(module_name: str) -> None:
    """Keep triangulation fans continuous and every hard source edge sharp."""
    skppy = importlib.import_module(module_name).skppy
    builder_type = importlib.import_module(f"{module_name}.scene_builder").BlenderSceneBuilder
    height = math.tan(math.radians(25))
    positions = [
        [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)],
        [(2, 0, 0), (3, 0, height), (3, 2, height), (2, 2, 0)],
        [(0, -1, 0), (2, -1, 0), (2, 0, 0), (0, 0, 0)],
    ]
    normals = [(0, 0, 1), (-math.sin(math.radians(25)), 0, math.cos(math.radians(25))), (0, 0, 1)]
    edge_ids = [[10, 11, 12, 13], [14, 15, 16, 11], [17, 18, 10, 19]]

    def position_key(position):
        return tuple(round(value, 6) for value in position)
    prepared = skppy.PreparedMesh(
        name="Shading regression",
        faces=[
            skppy.PreparedFace(
                vertex_positions=points,
                vertex_uvs=None,
                material_name=None,
                normal=normal,
                source_face_id=index,
                edge_ids=ids,
                edge_flags=[4 if edge == 11 else 0 for edge in ids],
            )
            for index, (points, normal, ids) in enumerate(zip(positions, normals, edge_ids, strict=True))
        ],
    )
    for mode in ("NGONS", "TRIS", "QUADS"):
        builder = builder_type(skppy.Model.new(), bpy.context, import_materials=False, triangulation_mode=mode, scale=1)
        mesh = builder._build_mesh_from_prepared(prepared)
        assert all(face.use_smooth for face in mesh.polygons), mode
        source_edges = {
            tuple(sorted((position_key(points[i]), position_key(points[(i + 1) % len(points)])))): edge
            for points, ids in zip(positions, edge_ids, strict=True)
            for i, edge in enumerate(ids)
        }
        for edge in mesh.edges:
            key = tuple(sorted(position_key(mesh.vertices[index].co) for index in edge.vertices))
            source_id = source_edges.get(key)
            assert edge.use_edge_sharp == (source_id is not None and source_id != 11), (mode, key)
        # The lower rectangle has only hard boundaries and must stay flat,
        # including the vertex that also touches the smoothed upper pair.
        for polygon in mesh.polygons:
            if polygon.center.y < 0:
                for loop in polygon.loop_indices:
                    assert mesh.corner_normals[loop].vector.dot(polygon.normal) > 0.99999, mode
        if mode == "TRIS":
            # Both triangles of the upper rectangle share identical corner
            # normals at each endpoint of the generated diagonal.
            by_vertex = {}
            for polygon in mesh.polygons:
                if abs(polygon.normal.z - 1) < 1e-6 and polygon.center.y > 0:
                    for loop in polygon.loop_indices:
                        vertex = mesh.loops[loop].vertex_index
                        normal = mesh.corner_normals[loop].vector.copy()
                        if vertex in by_vertex:
                            assert normal.dot(by_vertex[vertex]) > 0.99999
                        by_vertex[vertex] = normal
