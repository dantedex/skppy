# SPDX-License-Identifier: MIT
"""Raw SU2017 compatibility fixture for opaque definition payloads."""

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def test_definition_payload_matches_raw_legacy_extension_bytes() -> None:
    model = skppy.Model.new()
    definition = model.add_definition("Packed")
    definition.packed_payload = b"blob"
    expected = '{"definitions":{"Packed":{"packed_payload":"YmxvYg=="}}}'.encode("utf-16le")

    assert expected in build_legacy_2017_model(model)
