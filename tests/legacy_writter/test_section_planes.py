# SPDX-License-Identifier: MIT
"""Raw SU2017 compatibility fixture for modern section-plane metadata."""

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def test_section_metadata_matches_raw_legacy_extension_bytes() -> None:
    model = skppy.Model.new()
    model.entities.section_planes = [skppy.SectionPlane(id=20, name="Cut", symbol="A")]
    expected = '{"entity_scopes":{"root":{"sections":{"0":{"name":"Cut","symbol":"A"}}}}}'.encode("utf-16le")

    assert expected in build_legacy_2017_model(model)


def test_definition_section_metadata_matches_raw_legacy_extension_bytes() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Part")
    definition.entities.section_planes = [skppy.SectionPlane(id=20, symbol="B")]
    expected = ('{"entity_scopes":{"definitions":{"Part":{"sections":{"0":{"name":"","symbol":"B"}}}}}}').encode(
        "utf-16le"
    )

    assert expected in build_legacy_2017_model(model)
