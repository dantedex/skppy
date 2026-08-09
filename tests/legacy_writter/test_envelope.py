# SPDX-License-Identifier: MIT
"""Raw SU2017 independent archive-envelope fixtures."""

import struct
from types import SimpleNamespace

import skppy
from skppy.legacy_writter.envelope import _legacy_string, build_legacy_2017_prefix


def test_independent_envelope_has_expected_raw_header_and_root_boundary() -> None:
    model = skppy.Model.new()
    prefix = build_legacy_2017_prefix(model, 0x1234)
    expected_header = bytes.fromhex(
        "fffeff0e53006b0065007400630068005500700020004d006f00640065006c00"
        "fffeff087b00310037002e0030002e0031007d00"
        "00000000000000000000000000000000fffeff0000000000"
    )

    assert prefix.startswith(expected_header)
    assert struct.unpack_from("<Q", prefix, 1987) == (0x1234,)
    assert prefix.endswith(bytes.fromhex("0000000001000000"))
    assert b"CAttributeContainer" in prefix
    assert b"CRenderingOptions" not in prefix


def test_envelope_preserves_available_guid_provenance_and_current_camera() -> None:
    model = skppy.Model.new()
    model.header = SimpleNamespace(model_guid=bytes(range(16)))
    model.legacy_archive = SimpleNamespace(timestamp=42, model_description="Description")
    model.cameras.append(skppy.Camera(name="Current"))

    prefix = build_legacy_2017_prefix(model, 18)

    assert prefix[52:68] == bytes(range(16))
    assert struct.unpack_from("<I", prefix, 72) == (42,)
    assert "Description".encode("utf-16le") in prefix
    assert "Current".encode("utf-16le") in prefix


def test_legacy_string_uses_extended_raw_length_fields() -> None:
    medium = _legacy_string("a" * 0xFF)
    large = _legacy_string("b" * 0xFFFF)

    assert medium[:6] == b"\xff\xfe\xff\xff\xff\x00"
    assert large[:10] == b"\xff\xfe\xff\xff\xff\xff\xff\xff\x00\x00"
