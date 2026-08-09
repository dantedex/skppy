# SPDX-License-Identifier: MIT
"""Raw SU2017 construction-geometry writer fixtures."""

import math

import numpy as np

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyGeometryEncoder


def test_guides_match_raw_sdk_carchive_payload() -> None:
    model = skppy.Model.new()
    model.entities.guide_points.append(skppy.GuidePoint(id=1, position=(10, 20, 30)))
    model.entities.guide_lines.append(
        skppy.GuideLine(
            id=2,
            point=(0, 0, 0),
            direction=tuple(1 / math.sqrt(3) for _ in range(3)),
            start_parameter=0.0,
            end_parameter=173.20508075688775,
            stipple_pattern=0,
        )
    )
    expected = bytes.fromhex(
        "02000000ffff0000120043436f6e737472756374696f6e506f696e740000011200000001010000000000000000000000"
        "244000000000000034400000000000003e4000000000000000000000000000000000000000000000000000ffff010011"
        "0043436f6e737472756374696f6e4c696e65000001130000000101000000000000000000000000000000000000000000"
        "00000000000000001d339045a779e23f1d339045a779e23f1d339045a779e23f0000000000000000e6fb840590a66540"
        "00000000000000000000"
    )

    encoded = _LegacyGeometryEncoder(model.entities).encode()

    assert encoded[: len(expected)] == expected


def test_section_plane_matches_raw_sdk_carchive_payload() -> None:
    model = skppy.Model.new()
    model.entities.section_planes.append(skppy.SectionPlane(id=1, plane=(0, 0, 1, 0), name="TestSection"))
    expected = bytes.fromhex(
        "01000000ffff03000d004353656374696f6e506c616e6500000112000000010100000000000000000000000000000000"
        "0000000000000000000000f03f0000000000000000000000000000"
    )

    encoded = _LegacyGeometryEncoder(model.entities).encode()

    assert encoded[: len(expected)] == expected


def test_keeps_nested_construction_geometry_in_definition_coordinates() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Guides")
    definition.entities.guide_points.append(skppy.GuidePoint(id=1, position=(1, 2, 3), reference_point=(4, 5, 6)))
    definition.entities.guide_lines.append(skppy.GuideLine(id=2, point=(1, 0, 0), direction=(1, 0, 0)))
    definition.entities.section_planes.append(skppy.SectionPlane(id=3, plane=(0, 0, 1, -3)))
    model.entities.add_instance(definition, skppy.Transform.from_translation(10, 20, 30))

    encoded = build_legacy_2017_model(model)

    assert np.array((1.0, 2.0, 3.0), dtype="<f8").tobytes() in encoded
    assert np.array((10.0, 20.0, 30.0), dtype="<f8").tobytes() in encoded


def test_preserves_degenerate_instance_transform_without_collapsing_definition() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Guide")
    definition.entities.guide_lines.append(skppy.GuideLine(id=1, direction=(1, 0, 0)))
    model.entities.add_instance(definition, skppy.Transform(np.zeros((4, 4))))

    encoded = build_legacy_2017_model(model)

    assert np.zeros(13, dtype="<f8").tobytes() in encoded
