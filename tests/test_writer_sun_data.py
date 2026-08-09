# SPDX-License-Identifier: MIT
"""Raw-byte checks for opaque modern sun-data preservation."""

from __future__ import annotations

import struct

from skppy.data_structure.model import Model
from skppy.data_structure.model_metadata import SunData
from skppy.writer.model_data import encode_model_data
from skppy.writer.sun_data import encode_sun_data


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_sun_data_matches_raw_expected_bytes() -> None:
    expected = _raw_record(0x7D64, _raw_record(0x7D65))
    sun = SunData(raw_payload=_raw_record(0x7D65))
    assert encode_sun_data(sun) == expected

    model = Model.new()
    model.sun_data = sun
    assert _raw_record(0x0213, expected) in encode_model_data(model)


def test_default_sun_data_matches_raw_empty_extra_record() -> None:
    assert encode_sun_data(SunData()) == _raw_record(0x7D64, _raw_record(0x7D65))
