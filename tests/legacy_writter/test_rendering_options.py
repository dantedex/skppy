# SPDX-License-Identifier: MIT
"""Raw SU2017 rendering-options writer fixtures."""

import pytest

from skppy import RenderingOptions
from skppy.legacy_writter.envelope import _rendering_options


def test_rendering_options_match_raw_sdk_carchive_payload() -> None:
    options = RenderingOptions(
        render_mode=3,
        texture=False,
        background_color=0x11223344,
        edge_color_mode=2,
        draw_silhouettes=True,
        silhouette_width=5,
        display_fog=True,
        fog_start_dist=12.5,
        fog_end_dist=45.5,
        draw_ground=True,
        ground_transparency=25,
        xray_opacity=0.375,
        photomatch_draw_overlay=True,
        photomatch_overlay_opacity=0.75,
    )
    expected = bytes.fromhex(
        "030000000000000000000022334411000000ff00ff00ff808080ff000000000200000000000000000105000000000000"
        "00000000000000000000000000ffffffffccccccff00000000000000000000000000000000000001ccccccff00000000"
        "00000029400000000000c0464000000000000000000001010087ceebffc0d8e8ff8b4513ff00010019000000000000ff"
        "808080ff000000ff00000000000000000000000000000000000000000000808080ff00000000000000d83f0000000000"
        "000000000001000000000000e83f"
    )

    assert _rendering_options(options) == expected


def test_rendering_options_reject_out_of_range_colors() -> None:
    with pytest.raises(ValueError, match="colors must fit in u32"):
        _rendering_options(RenderingOptions(background_color=-1))
