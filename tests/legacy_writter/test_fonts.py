# SPDX-License-Identifier: MIT
"""Raw SU2017 font-manager writer fixtures."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyModelEncoder


def test_font_styles_and_manager_match_raw_carchive_payloads() -> None:
    model = skppy.Model.new()
    model.fonts = [
        skppy.Font(
            "Courier New",
            bold=True,
            point_size=14,
            use_world_size=True,
            world_size=2.5,
        )
    ]
    encoder = _LegacyModelEncoder(model, model.entities)
    encoder.data.clear()
    encoder._write_dimension_style(
        skppy.DimensionStyle(
            font_ref=2,
            text_3d=True,
            always_readable=True,
            extension_offset=2,
            extension_overshoot=3,
            line_weight=4,
            arrow_type=5,
            arrow_size=6,
            highlight_non_associative=True,
            highlight_non_associative_color=0xFF102030,
            show_radial_diameter_prefix=True,
            hide_out_of_plane=True,
            hide_out_of_plane_value=0.4,
            hide_small=True,
            hide_small_value=2.0,
            color=0xFF010203,
            text_color=0xFF040506,
            text_position=2,
        )
    )
    expected_dimension = bytes.fromhex(
        "00000000000000ffff0100070043536b466f6e7400000102fffeff0b43006f007500720069006500720020004e00650077"
        "0001000e0000000100000000000004400101020000000300000004000000050000000600000001102030ff01019a999999"
        "9999d93f010000000000000040010203ff040506ff02000000"
    )

    assert encoder.data == expected_dimension

    encoder.data.clear()
    encoder._write_text_style(
        skppy.TextStyle(
            font_ref=2,
            screen_font_ref=2,
            arrow_type=4,
            line_weight=7,
            hide_out_of_plane=True,
            leader_type=2,
            display_leader=False,
            color=0xFF112233,
            screen_color=0x80445566,
        )
    )
    assert encoder.data == bytes.fromhex("0000000a000400000007000000010200000000112233ff445566800a00")

    encoder.data.clear()
    encoder._write_font_manager()
    assert encoder.data == bytes.fromhex("000000010000000a00")


def test_rejects_invalid_style_font_references_and_colors() -> None:
    model = skppy.Model.new()
    model.fonts = [skppy.Font("Arial")]
    model.text_style = skppy.TextStyle(font_ref=3, screen_font_ref=2)

    with pytest.raises(ValueError, match="Text style font reference"):
        build_legacy_2017_model(model)

    encoder = _LegacyModelEncoder(model, model.entities)
    with pytest.raises(ValueError, match="colors must fit in u32"):
        encoder._write_text_style(skppy.TextStyle(font_ref=2, screen_font_ref=2, color=-1))
