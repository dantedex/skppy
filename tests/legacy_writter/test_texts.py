# SPDX-License-Identifier: MIT
"""Raw SU2017 text-annotation writer fixtures."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyGeometryEncoder


def test_text_matches_raw_carchive_payload() -> None:
    entities = skppy.Entities()
    entities.texts.append(
        skppy.Text(
            id=1,
            text="Label",
            anchor=skppy.PointReference(kind=1, position=skppy.Vector3D(1, 2, 3)),
            screen_position=skppy.Vector2D(0.25, 0.5),
            leader_vector=skppy.Vector3D(1, 2, 3),
            view_direction=skppy.Vector3D(0, 0, 1),
            leader_type=2,
            line_weight=3,
            anchor_in_front=True,
            arrow_type=4,
            hidden_leader_direction=5,
        )
    )
    expected = bytes.fromhex(
        "01000000ffff0900050043546578740000011200000001010000000000ffff0100070043536b466f6e7400000113fffeff"
        "0541007200690061006c0000000c00000000000000000000f03f000000000000d03f000000000000e03f010000000000"
        "0000000000000000f03f00000000000000400000000000000840000000000000000000000000f03f0000000000000040"
        "000000000000084000000000000000000000000000000000000000000000f03f020000000300000001000400000001ff"
        "feff054c006100620065006c000005000000000000000000"
    )

    assert _LegacyGeometryEncoder(entities).encode() == expected


def test_writes_registered_annotation_fonts_and_rejects_conflicting_references() -> None:
    font = skppy.Font("Courier New", point_size=14)
    model = skppy.Model.new()
    model.fonts = [font]
    model.entities.texts.append(skppy.Text(id=1, font=font, font_id=2))

    encoded = build_legacy_2017_model(model)

    assert "Courier New".encode("utf-16le") in encoded

    model.entities.texts[0].font = skppy.Font("Arial")
    with pytest.raises(ValueError, match="identify different fonts"):
        build_legacy_2017_model(model)

    model.entities.texts[0].font_id = 3
    with pytest.raises(ValueError, match="does not identify"):
        _LegacyGeometryEncoder(model.entities).encode()

    unresolved = skppy.Entities(texts=[skppy.Text(id=1, font_id=2)])
    with pytest.raises(ValueError, match="does not identify"):
        _LegacyGeometryEncoder(unresolved).encode()


def test_writes_font_id_without_font_object_and_rejects_invalid_model_font_ids() -> None:
    model = skppy.Model.new()
    model.fonts = [skppy.Font("Arial", point_size=11)]
    model.entities.texts.append(skppy.Text(id=1, font_id=2))

    assert "Arial".encode("utf-16le") in build_legacy_2017_model(model)

    model.entities.texts[0].font_id = 3
    with pytest.raises(ValueError, match="does not identify"):
        build_legacy_2017_model(model)


def test_writes_default_font_id_without_explicit_model_fonts() -> None:
    model = skppy.Model.new()
    model.entities.texts.append(skppy.Text(id=1, font_id=2))

    encoded = build_legacy_2017_model(model)

    assert "Arial".encode("utf-16le") in encoded
