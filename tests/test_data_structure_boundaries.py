# SPDX-License-Identifier: MIT
"""Boundary coverage for renderer-neutral data structures and geometry helpers."""

from __future__ import annotations

import math

import numpy as np
import pytest

from skppy.data_structure.document import SkpDocument
from skppy.data_structure.entities import (
    Edge,
    EdgeUse,
    Entities,
    Face,
    FaceUVProjection,
    Loop,
    _compute_plane,
    _invert_3x3,
    _point_values,
    _project_points_for_uv,
)
from skppy.data_structure.images import Texture
from skppy.data_structure.materials import Material
from skppy.data_structure.mesh_indexing import _MeshIndexer
from skppy.data_structure.mesh_preparation import (
    _FaceGeometry,
    _LoopGeometry,
    _MeshPreparer,
    _face_uvs,
)
from skppy.data_structure.model import Model
from skppy.data_structure.model_metadata import RenderingOptions
from skppy.data_structure.primitives import Vector3D
from skppy.data_structure.scene import (
    IndexedPreparedMesh,
    PreparedFace,
    PreparedMesh,
    _planar_uv,
    _require_aligned_length,
    _require_finite_rows,
    _unit_normal,
)
from skppy.exceptions import OldFormatError


def _triangle_face(**changes: object) -> PreparedFace:
    values: dict[str, object] = {
        "vertex_positions": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        "vertex_uvs": None,
        "normal": (0.0, 0.0, 1.0),
        "material_name": None,
    }
    values.update(changes)
    return PreparedFace(**values)  # type: ignore[arg-type]


def _indexed(**changes: object) -> IndexedPreparedMesh:
    values: dict[str, object] = {
        "vertex_positions": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        "faces": [[0, 1, 2]],
        "face_uvs": [None],
        "face_normals": [(0.0, 0.0, 1.0)],
        "face_material_names": [None],
        "face_material_ids": [None],
        "source_face_ids": [None],
        "layer_ids": [None],
        "face_edge_ids": [[None, None, None]],
        "face_edge_flags": [[0, 0, 0]],
    }
    values.update(changes)
    return IndexedPreparedMesh(**values)  # type: ignore[arg-type]


def test_projection_helpers_cover_empty_short_and_unprojected_inputs(monkeypatch):
    assert FaceUVProjection().compute_uvs([], 1.0, 1.0) == []
    assert _invert_3x3([1.0]) is None
    assert _project_points_for_uv([(1.0, 2.0, 3.0)], None).tolist() == [[1.0, 2.0]]

    monkeypatch.setattr(np.linalg, "det", lambda _matrix: (_ for _ in ()).throw(np.linalg.LinAlgError()))
    assert _invert_3x3([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]) is None


def test_projection_helper_handles_inverse_failure(monkeypatch):
    monkeypatch.setattr(np.linalg, "det", lambda _matrix: 1.0)
    monkeypatch.setattr(np.linalg, "inv", lambda _matrix: (_ for _ in ()).throw(np.linalg.LinAlgError()))
    assert _invert_3x3([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]) is None


def test_face_methods_and_point_helpers_accept_all_public_point_forms():
    entities = Entities()
    first = entities.add_vertex(0.0, 0.0, 0.0)
    face = entities.add_face([first, Vector3D(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])

    assert face.triangulate(entities) == [(first.id, entities.vertices[1].id, entities.vertices[2].id)]
    assert face.normal().to_tuple() == pytest.approx((0.0, 0.0, 1.0))
    assert _point_values(first) == (0.0, 0.0, 0.0)
    assert _point_values(Vector3D(1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0)
    assert _compute_plane([]) == (0.0, 0.0, 0.0, 0.0)
    assert Face(1, (0.0, 0.0, 1.0, 0.0), Loop(), []).triangulate(Entities()) == []


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (((0, 0, 0), (0, 0, 1), 1.0, 0.0, 1.0, 0), "at least one segment"),
        (((0, 0, 0), (0, 0, 1), 0.0, 0.0, 1.0, 1), "positive finite radius"),
        (((0, 0, 0), (0, 0, 1), 1.0, math.nan, 1.0, 1), "angles must be finite"),
        (((0, 0, 0), (0, 0, 1), 1.0, 1.0, 0.0, 1), "end angle"),
        (((0, 0, 0), (0, 0, 0), 1.0, 0.0, 1.0, 1), "normal must be non-zero"),
    ],
)
def test_add_arc_curve_rejects_invalid_geometry(arguments, message):
    with pytest.raises(ValueError, match=message):
        Entities().add_arc_curve(*arguments)


def test_add_arc_curve_builds_non_horizontal_basis():
    entities = Entities()
    arc = entities.add_arc_curve((0, 0, 0), (1, 1, 1), 2.0, 0.0, math.pi, 2)

    assert arc.normal == pytest.approx((1 / math.sqrt(3),) * 3)
    assert len(arc.edge_ids) == 2


def test_add_arc_curve_from_edges_rejects_invalid_ownership_and_geometry():
    entities = Entities(edges=[Edge(1, 1, 2), Edge(2, 2, 3, curve_id=9)])
    cases = [
        ([], (0, 0, 0), (0, 0, 1), 1.0, 0.0, 1.0, "at least one edge"),
        ([99], (0, 0, 0), (0, 0, 1), 1.0, 0.0, 1.0, "outside this scope"),
        ([1, 1], (0, 0, 0), (0, 0, 1), 1.0, 0.0, 1.0, "duplicate edges"),
        ([2], (0, 0, 0), (0, 0, 1), 1.0, 0.0, 1.0, "already belongs"),
        ([1], (0, 0, 0), (0, 0, 1), -1.0, 0.0, 1.0, "positive finite radius"),
        ([1], (0, 0, 0), (0, 0, 1), 1.0, math.inf, 1.0, "angles must be finite"),
        ([1], (0, 0, 0), (0, 0, 1), 1.0, 1.0, 0.0, "end angle"),
        ([1], (0, 0, 0), (0, 0, 0), 1.0, 0.0, 1.0, "normal must be non-zero"),
    ]
    for edge_ids, center, normal, radius, start, end, message in cases:
        with pytest.raises(ValueError, match=message):
            entities.add_arc_curve_from_edges(edge_ids, center, normal, radius, start, end)


def test_scene_validators_cover_unsized_empty_and_invalid_rows():
    with pytest.raises(ValueError, match="sized sequence"):
        _require_aligned_length("items", object(), 1)
    _require_finite_rows("items", [], width=3)
    with pytest.raises(ValueError, match="rows of 3"):
        _require_finite_rows("items", [(1.0, 2.0)], width=3)
    with pytest.raises(ValueError, match="at least three"):
        _triangle_face(vertex_positions=[(0.0, 0.0, 0.0)])
    with pytest.raises(ValueError, match="edge_flags must contain 3 entries"):
        _triangle_face(edge_flags=[0])


def test_indexed_mesh_rejects_short_faces_and_out_of_range_indices():
    with pytest.raises(ValueError, match="at least three"):
        _indexed(faces=[[0, 1]], face_edge_ids=[[None, None]], face_edge_flags=[[0, 0]])
    with pytest.raises(ValueError, match=r"outside 0\.\.2"):
        _indexed(faces=[[0, 1, 3]])


def test_planar_uv_covers_zero_normal_and_each_dominant_axis():
    assert _unit_normal(0.0, 0.0, 0.0) == (0.0, 0.0, 1.0)
    assert _planar_uv([], (0.0, 0.0, 1.0), 1.0, 1.0) == []
    assert _planar_uv([(2.0, 3.0, 5.0)], (0.0, 0.0, 1.0), 2.0, 1.0) == [(1.0, 3.0)]
    assert _planar_uv([(2.0, 3.0, 5.0)], (1.0, 0.0, 0.0), 3.0, 5.0) == [(1.0, 1.0)]
    assert _planar_uv([(2.0, 3.0, 5.0)], (0.0, 1.0, 0.0), 2.0, 5.0) == [(1.0, 1.0)]


def test_mesh_indexer_falls_back_to_fan_and_synthesizes_edge_metadata(monkeypatch):
    face = _triangle_face(
        vertex_positions=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ]
    )
    monkeypatch.setattr(
        "skppy.data_structure.mesh_indexing.triangulate_face_3d",
        lambda *_args, **_kwargs: [],
    )

    indexed = _MeshIndexer(False, True, 9).convert(PreparedMesh("quad", [face]))

    assert indexed.faces == [[0, 1, 2], [3, 4, 5]]
    assert indexed.face_edge_ids == [[None, None, None], [None, None, None]]
    assert indexed.face_edge_flags == [[0, 0, 0], [0, 0, 0]]


def test_mesh_preparer_skips_unresolved_faces_and_invalid_loops():
    face = Face(10, (0.0, 0.0, 1.0, 0.0), Loop([EdgeUse(99, False)]), [])
    preparer = _MeshPreparer(Entities(faces=[face]), {}, None, False)
    assert preparer.prepare("invalid").faces == []

    assert preparer._resolve_loop(Loop()) is None
    preparer.edge_map = {1: (1, 2), 2: (2, 3), 3: (3, 1)}
    assert preparer._resolve_loop(Loop([EdgeUse(1, False), EdgeUse(2, False), EdgeUse(3, False)])) is None
    preparer.vertices = {1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0), 3: (0.0, 1.0, 0.0)}
    assert preparer._resolve_loop(Loop([EdgeUse(1, False), EdgeUse(2, False), EdgeUse(3, False)])) is None


def test_mesh_preparer_discards_singular_projection_and_short_polygon():
    entities = Entities()
    face = entities.add_face([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    face.front_uv = FaceUVProjection(transform=[0.0] * 9)
    face.front_material_id = 7
    preparer = _MeshPreparer(entities, {}, None, False)
    geometry = preparer._resolve_face(face)
    assert geometry is not None and geometry.projection is None

    output = []
    preparer._append_polygon(output, geometry, geometry.outer.positions[:2], [None, None])
    assert output == []


def test_face_uvs_uses_planar_fallback_for_textured_material():
    material = Material(
        id=7,
        name="Tile",
        has_texture=True,
        texture=Texture(filename="tile.png", x_scale=2.0, y_scale=4.0),
    )
    face = Face(1, (0.0, 0.0, 1.0, 0.0), Loop(), [])
    loop = _LoopGeometry([(2.0, 4.0, 0.0)] * 3, [1, 2, 3])
    geometry = _FaceGeometry(face, (0.0, 0.0, 1.0), 7, material, None, loop, [])
    assert _face_uvs(geometry, loop.positions) == [(1.0, 1.0)] * 3


def test_model_dump_zip_delegates_to_document(tmp_path, monkeypatch):
    document = SkpDocument(filepath="model.skp", header=None, zip_entries=[], model_entry=None)
    expected = tmp_path / "out"
    monkeypatch.setattr(SkpDocument, "dump_zip", lambda self, output: expected)
    assert Model(document=document).dump_zip(str(expected)) == expected


def test_metadata_and_exception_false_branches():
    options = RenderingOptions(section_display_mode=3)
    options.display_section_planes = False
    assert options.section_display_mode == 2
    assert str(OldFormatError("legacy format")) == "legacy format"
