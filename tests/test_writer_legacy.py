# SPDX-License-Identifier: MIT
"""Raw-byte tests for the SketchUp Make 2017 writer."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import cast

import pytest

import skppy
from skppy.data_structure.entities import Edge, EdgeUse, Face, Image, Loop, Vertex
from skppy.data_structure.primitives import Transform, Vector3D
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyGeometryEncoder, _encode_sparse_u64


def _square_model() -> skppy.Model:
    model = skppy.Model.new()
    model.entities.add_face([(0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0)])
    return model


def test_empty_model_writes_dynamic_metadata_into_raw_sdk_envelope() -> None:
    encoded = build_legacy_2017_model(skppy.Model.new())

    assert len(encoded) == 3305
    assert struct.unpack_from("<Q", encoded, 1987) == (18,)
    assert encoded[-5:] == bytes.fromhex("0100000000")
    assert "Arial".encode("utf-16le") in encoded
    assert "Tahoma".encode("utf-16le") in encoded


def test_face_matches_raw_sdk_carchive_geometry() -> None:
    expected = bytes.fromhex(
        "05000000ffff030005004346616365000001120000000101000000000000000000000000000000000000000000000000"
        "000000f03f000000000000008001000000ffff01000500434c6f6f700000000101ffff01000800434564676555736500"
        "0000ffff0200050043456467650000011300000001010000000000ffff00000700435665727465780000011400000000"
        "000000000000000000000000000000000000000013800000011500000000000059400000000000000000000000000000"
        "00000000000e000f80000000118000000116000000010100000000001500138000000117000000000000594000000000"
        "0000594000000000000000000000000e000f800000001180000001180000000101000000000018001380000001190000"
        "000000000000000000000000594000000000000000000000000e000f8000000011800000011a00000001010000000000"
        "1b0014000000000e0000000000120017001a001d00000000000000"
    )

    encoded = _LegacyGeometryEncoder(_square_model().entities).encode()

    assert encoded[: len(expected)] == expected


def test_public_save_selects_legacy_and_keeps_modern_default(tmp_path: Path) -> None:
    model = _square_model()
    legacy_path = tmp_path / "legacy.skp"
    modern_path = tmp_path / "modern.skp"

    assert skppy.save(model, legacy_path, format="sketchup_2017") == legacy_path
    assert model.save(modern_path) == modern_path
    assert legacy_path.read_bytes().startswith(b"\xff\xfe\xff\x0e")
    assert b"VFF" not in legacy_path.read_bytes()[:100]
    assert b"VFF" in modern_path.read_bytes()[:100]


def test_rejects_unknown_format_and_legacy_modern_header(tmp_path: Path) -> None:
    model = skppy.Model.new()
    with pytest.raises(ValueError, match="Unknown SKP output format"):
        skppy.save(model, tmp_path / "unknown.skp", format=cast("str", "future"))
    with pytest.raises(ValueError, match="modern VFF header"):
        skppy.save(
            model,
            tmp_path / "legacy.skp",
            format="sketchup_2017",
            header=skppy.writer.default_modern_header(),
        )


def test_writes_native_component_geometry_and_transform() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Square")
    definition.entities.add_face([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    model.entities.add_instance(definition, Transform.from_translation(10, 20, 30))

    encoded = build_legacy_2017_model(model)

    assert struct.pack("<3d", 10, 20, 30) in encoded
    assert struct.pack("<3d", 1, 1, 0) in encoded
    assert b"CComponentDefinition" in encoded
    assert b"CComponentInstance" in encoded


def test_serializes_inner_loops_and_edge_flags_as_raw_fields() -> None:
    model = _square_model()
    face = model.entities.faces[0]
    vertices = [model.entities.add_vertex(*point) for point in ((25, 25, 0), (25, 75, 0), (75, 75, 0), (75, 25, 0))]
    edges = [model.entities.add_edge(vertices[index], vertices[(index + 1) % 4]) for index in range(4)]
    edges[0].flags = 0x07
    face.inner_loops = [Loop([EdgeUse(edge.id, False) for edge in edges], is_outer=False, is_convex=False)]

    encoded = _LegacyGeometryEncoder(model.entities).encode()

    assert struct.pack("<I", 2) in encoded
    assert b"\x01\x01\x01\x01\x01\x00" in encoded
    assert b"\x00\x00" in encoded


def test_sparse_persistent_ids_use_only_populated_bytes() -> None:
    assert _encode_sparse_u64(0) == b"\x00"
    assert _encode_sparse_u64(1) == b"\x01\x01"
    assert _encode_sparse_u64(0x0102) == b"\x03\x02\x01"


def test_raw_encoder_handles_standalone_and_shared_edges() -> None:
    standalone = skppy.Entities(
        vertices=[Vertex(1, Vector3D(0, 0, 0)), Vertex(2, Vector3D(1, 0, 0))],
        edges=[Edge(3, 1, 2)],
    )
    assert _LegacyGeometryEncoder(standalone).encode().startswith(struct.pack("<I", 1))

    shared = _square_model().entities
    original = shared.faces[0]
    shared.faces.append(Face(99, original.plane, original.outer_loop, []))
    assert _LegacyGeometryEncoder(shared).encode().startswith(struct.pack("<I", 6))


def test_raw_encoder_rejects_missing_nested_references() -> None:
    missing_vertex = skppy.Entities(vertices=[Vertex(1, Vector3D(0, 0, 0))], edges=[Edge(2, 1, 9)])
    with pytest.raises(ValueError, match="missing vertex ID 9"):
        _LegacyGeometryEncoder(missing_vertex).encode()

    missing_edge = skppy.Entities(faces=[Face(1, (0, 0, 1, 0), Loop([EdgeUse(9, False)]), [])])
    with pytest.raises(ValueError, match="missing edge ID 9"):
        _LegacyGeometryEncoder(missing_edge).encode()


def test_rejects_short_and_degenerate_face_boundaries() -> None:
    short = skppy.Model.new()
    vertices = [short.entities.add_vertex(index, 0, 0) for index in range(2)]
    edge = short.entities.add_edge(*vertices)
    short.entities.faces.append(Face(4, (0, 0, 1, 0), Loop([EdgeUse(edge.id, False)]), []))
    with pytest.raises(ValueError, match="at least three edges"):
        build_legacy_2017_model(short)

    degenerate = skppy.Model.new()
    degenerate.entities.add_face([(0, 0, 0), (1, 0, 0), (2, 0, 0)])
    with pytest.raises(ValueError, match="outer loop is degenerate"):
        build_legacy_2017_model(degenerate)


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (
            skppy.Model(entities=skppy.Entities(vertices=[Vertex(1, Vector3D(0, 0, 0))], edges=[Edge(2, 1, 9)])),
            "missing vertex",
        ),
        (
            skppy.Model(
                entities=skppy.Entities(
                    vertices=[Vertex(1, Vector3D(0, 0, 0)), Vertex(2, Vector3D(1, 0, 0))],
                    edges=[Edge(3, 1, 2)],
                    faces=[Face(4, (0, 0, 1, 0), Loop([EdgeUse(9, False)]), [])],
                )
            ),
            "missing edge",
        ),
        (skppy.Model(entities=skppy.Entities(images=[Image()])), "missing definition ID 0"),
    ],
)
def test_rejects_invalid_or_unsupported_legacy_geometry(model: skppy.Model, message: str) -> None:
    with pytest.raises((ValueError, NotImplementedError), match=message):
        build_legacy_2017_model(model)


def test_rejects_missing_definitions_and_component_cycles() -> None:
    missing = skppy.Model.new()
    missing.entities.component_instances.append(skppy.ComponentInstance(definition_id=42))
    with pytest.raises(ValueError, match="missing definition ID 42"):
        build_legacy_2017_model(missing)

    cyclic = skppy.Model.new()
    definition = cyclic.add_definition("Cycle")
    definition.entities.add_instance(definition)
    cyclic.entities.add_instance(definition)
    with pytest.raises(ValueError, match="component cycle"):
        build_legacy_2017_model(cyclic)
