# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern model metadata encoders."""

from __future__ import annotations

import struct
import math

import pytest

from skppy.data_structure.construction import ShadowInfo
from skppy.data_structure.model import Model
from skppy.data_structure.model_metadata import ModelViewAxes, RenderingOptions
from skppy.writer.model_data import encode_model_data
from skppy.writer.model_metadata import (
    encode_model_view_axes,
    encode_rendering_options,
    encode_shadow_info,
)


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_model_view_axes_match_raw_expected_bytes() -> None:
    axes = ModelViewAxes(
        origin=(10, 10, 10),
        x_axis=(1, 1, 0),
        y_axis=(-1, 1, 0),
        z_axis=(0, 0, 1),
    )
    diagonal = 1.0 / math.sqrt(2.0)
    payload = b"".join(
        (
            _raw_record(0x07D0, _raw_record(0x07D3, b"\x06")),
            _raw_record(0x4651, struct.pack("<3d", 10, 10, 10)),
            _raw_record(0x4652, struct.pack("<3d", diagonal, diagonal, 0)),
            _raw_record(0x4653, struct.pack("<3d", -diagonal, diagonal, 0)),
            _raw_record(0x4654, struct.pack("<3d", 0, 0, 1)),
        )
    )
    assert encode_model_view_axes(axes) == _raw_record(0x4650, payload)


def test_rendering_options_emit_raw_target_values() -> None:
    options = RenderingOptions(edge_display_mode=0, draw_ground=True)
    encoded = encode_rendering_options(options)
    assert _raw_record(0x7341, struct.pack("<I", 0)) in encoded
    assert _raw_record(0x7369, b"\x01") in encoded

    options.display_section_planes = True
    options.display_section_cuts = True
    assert _raw_record(0x7375, struct.pack("<I", 3)) in encode_rendering_options(options)


def test_shadow_info_matches_raw_location_records() -> None:
    encoded = encode_shadow_info(ShadowInfo(latitude=45.0, longitude=-120.0))
    assert _raw_record(0x6595, struct.pack("<d", -120.0)) in encoded
    assert _raw_record(0x6596, struct.pack("<d", 45.0)) in encoded


def test_model_root_contains_raw_metadata_blocks() -> None:
    model = Model.new()
    model.rendering_options = RenderingOptions(draw_ground=True)
    model.model_view_axes = ModelViewAxes(origin=(10, 10, 10))
    model.shadow_info = ShadowInfo(latitude=45.0, longitude=-120.0)
    encoded = encode_model_data(model)

    assert _raw_record(0x7369, b"\x01") in encoded
    assert _raw_record(0x4651, struct.pack("<3d", 10, 10, 10)) in encoded
    assert _raw_record(0x6596, struct.pack("<d", 45.0)) in encoded


def test_model_axes_reject_invalid_vectors() -> None:
    with pytest.raises(ValueError, match="three finite values"):
        encode_model_view_axes(ModelViewAxes(origin=(1.0, 2.0)))
    with pytest.raises(ValueError, match="must not be zero"):
        encode_model_view_axes(ModelViewAxes(x_axis=(0.0, 0.0, 0.0)))


def test_rendering_options_reject_invalid_scalars_and_colors() -> None:
    with pytest.raises(ValueError, match="render_mode must fit in u32"):
        encode_rendering_options(RenderingOptions(render_mode=-1))
    with pytest.raises(ValueError, match="fog_start_dist must be finite"):
        encode_rendering_options(RenderingOptions(fog_start_dist=float("nan")))
    with pytest.raises(ValueError, match="color must fit in u32"):
        encode_rendering_options(RenderingOptions(background_color=-1))


def test_shadow_info_rejects_non_finite_location() -> None:
    with pytest.raises(ValueError, match="location values must be finite"):
        encode_shadow_info(ShadowInfo(latitude=float("nan")))
