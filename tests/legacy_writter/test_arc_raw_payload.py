# SPDX-License-Identifier: MIT
"""Raw SU2017 compatibility fixture for opaque modern arc payloads."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def test_raw_arc_payload_matches_raw_legacy_extension_bytes() -> None:
    model = skppy.Model.new()
    start = model.entities.add_vertex(0, 0, 0)
    end = model.entities.add_vertex(1, 0, 0)
    edge = model.entities.add_edge(start, end)
    edge.curve_id = 10
    model.entities.arc_curves = [skppy.ArcCurve(id=10, edge_ids=[edge.id], raw_arc_payload=bytes(range(128)))]
    expected = (
        '{"entity_scopes":{"root":{"raw_arcs":[{"edges":[0],"payload":"'
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8gISIjJCUmJygpKissLS4vMDEyMzQ1Njc4OTo7PD0+P0BBQkNERUZH"
        'SElKS0xNTk9QUVJTVFVWV1hZWltcXV5fYGFiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6e3x9fn8="}]}}}'
    ).encode("utf-16le")

    assert expected in build_legacy_2017_model(model)


def test_rejects_invalid_raw_arc_payload() -> None:
    model = skppy.Model.new()
    model.entities.arc_curves = [skppy.ArcCurve(id=10, raw_arc_payload=b"short")]

    with pytest.raises(ValueError, match="needs a 128-byte raw payload"):
        build_legacy_2017_model(model)


def test_rejects_missing_raw_arc_edge() -> None:
    model = skppy.Model.new()
    model.entities.arc_curves = [skppy.ArcCurve(id=10, edge_ids=[99], raw_arc_payload=bytes(128))]

    with pytest.raises(ValueError, match="references missing edge ID 99"):
        build_legacy_2017_model(model)
