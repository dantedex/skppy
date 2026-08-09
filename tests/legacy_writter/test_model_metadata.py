# SPDX-License-Identifier: MIT
"""Raw SU2017 shadow and model-axis writer fixtures."""

import skppy
from skppy.legacy_writter.model import _LegacyModelEncoder


def test_shadow_info_matches_raw_carchive_payload() -> None:
    model = skppy.Model.new()
    encoder = _LegacyModelEncoder(model, model.entities)
    encoder.data.clear()
    encoder._write_shadow_info(
        skppy.ShadowInfo(
            time=123,
            daylight_savings=True,
            country=b"BR",
            city=b"SP",
            longitude=-1.0,
            latitude=-2.0,
            timezone_offset=-3.0,
            north_direction=(0.0, 1.0, 0.0),
            display_shadows=True,
            display_north=True,
            display_on_all_faces=True,
            display_on_ground_plane=True,
            light=80,
            dark=20,
            use_sun_for_all_shading=True,
        )
    )
    expected = bytes.fromhex(
        "0000007b00000001fffeff0242005200fffeff0253005000000000000000f0bf00000000000000c000000000000008c000"
        "00000000000000000000000000f03f000000000000000001010101500000001400000001"
    )

    assert encoder.data == expected


def test_model_axes_match_raw_carchive_payload() -> None:
    model = skppy.Model.new()
    encoder = _LegacyModelEncoder(model, model.entities)
    encoder.data.clear()
    encoder._write_model_axes(
        skppy.ModelViewAxes(
            origin=(1.0, 2.0, 3.0),
            x_axis=(0.0, 1.0, 0.0),
            y_axis=(-1.0, 0.0, 0.0),
            z_axis=(0.0, 0.0, 1.0),
        )
    )
    expected = bytes.fromhex(
        "00000000000001010000000000000000000000f03f000000000000004000000000000008400000000000000000000000"
        "000000f03f0000000000000000000000000000f0bf000000000000000000000000000000000000000000000000000000"
        "0000000000000000000000f03f"
    )

    assert encoder.data == expected
