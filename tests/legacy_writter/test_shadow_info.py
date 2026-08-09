# SPDX-License-Identifier: MIT
"""Raw SU2017 compatibility fixture for modern shadow metadata."""

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def test_shadow_extension_matches_raw_legacy_extension_bytes() -> None:
    model = skppy.Model.new()
    model.shadow_info = skppy.ShadowInfo(edges_cast_shadows=True)
    expected = '{"shadow_edges_cast_shadows":true}'.encode("utf-16le")

    assert expected in build_legacy_2017_model(model)
