# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern options-manager serialization."""

from __future__ import annotations

import struct

import pytest

from skppy.data_structure.model_metadata import OptionsManager, OptionsProvider
from skppy.writer.options import encode_options_manager


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_options_manager_matches_raw_expected_bytes() -> None:
    manager = OptionsManager(
        providers=[
            OptionsProvider(
                name="UnitsOptions",
                keys={
                    "LengthUnit": 2,
                    "LengthSnapEnabled": True,
                    "LengthSnapLength": 0.25,
                },
            )
        ]
    )
    keys = b"".join(
        (
            _raw_record(0x61AD, b"LengthUnit"),
            _raw_record(0x38A4, _raw_record(0x38A7, struct.pack("<i", 2))),
            _raw_record(0x61AD, b"LengthSnapEnabled"),
            _raw_record(0x38A4, _raw_record(0x38AA, b"\x01")),
            _raw_record(0x61AD, b"LengthSnapLength"),
            _raw_record(0x38A4, _raw_record(0x38A9, struct.pack("<d", 0.25))),
        )
    )
    provider = _raw_record(
        0x61AA,
        _raw_record(0x61AB, b"UnitsOptions") + _raw_record(0x61AC, keys),
    )
    expected = _raw_record(0x61A8, _raw_record(0x61A9, provider))
    assert encode_options_manager(manager) == expected


def test_string_option_matches_raw_expected_bytes() -> None:
    manager = OptionsManager(providers=[OptionsProvider(name="PageOptions", keys={"Name": "Cover"})])
    key = _raw_record(0x61AD, b"Name") + _raw_record(0x38A4, _raw_record(0x38AD, b"Cover"))
    provider = _raw_record(
        0x61AA,
        _raw_record(0x61AB, b"PageOptions") + _raw_record(0x61AC, key),
    )
    assert encode_options_manager(manager) == _raw_record(0x61A8, _raw_record(0x61A9, provider))


@pytest.mark.parametrize(
    "providers",
    [
        [OptionsProvider(name="")],
        [OptionsProvider(name="Same"), OptionsProvider(name="Same")],
    ],
)
def test_option_provider_names_must_be_non_empty_and_unique(providers) -> None:
    with pytest.raises(ValueError, match="non-empty and unique"):
        encode_options_manager(OptionsManager(providers=providers))


def test_option_keys_and_values_must_be_serializable() -> None:
    with pytest.raises(ValueError, match="keys must be non-empty"):
        encode_options_manager(OptionsManager(providers=[OptionsProvider(name="Data", keys={"": True})]))
    with pytest.raises(ValueError, match="fit in i32"):
        encode_options_manager(OptionsManager(providers=[OptionsProvider(name="Data", keys={"TooLarge": 2**31})]))
    with pytest.raises(TypeError, match="Unsupported option value type"):
        encode_options_manager(
            OptionsManager(
                providers=[OptionsProvider(name="Data", keys={"Bad": b"bytes"})]  # type: ignore[dict-item]
            )
        )
