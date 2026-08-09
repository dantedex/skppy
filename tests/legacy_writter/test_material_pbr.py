# SPDX-License-Identifier: MIT
"""Raw SU2017 compatibility-extension fixtures for PBR factors."""

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def test_material_and_layer_pbr_match_raw_legacy_extension_payload() -> None:
    model = skppy.Model.new()
    material = model.add_material("Steel")
    material.metallic = 0.8
    material.roughness = 0.2
    layer = model.add_layer("Walls")
    layer.material = skppy.Material(name="Display", metallic=0.3, roughness=0.4)
    expected = ('{"layer_material_pbr":{"Walls":[0.3,0.4]},"material_pbr":{"Steel":[0.8,0.2]}}').encode("utf-16le")

    assert expected in build_legacy_2017_model(model)
