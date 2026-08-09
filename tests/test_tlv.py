# SPDX-License-Identifier: MIT
"""Tests for shared modern TLV traversal helpers."""

from __future__ import annotations

import struct

import pytest

from skppy.parser.tlv import (
    find_model_root,
    format_guid,
    index_children,
    iter_record_prefix,
    iter_records,
    read_bool,
    read_compact_int,
    read_record,
    read_u32_le,
)

# Tag literals are independent expectations: 0x01F4 is model root and 0x01F5
# is its ID-counter child. Generic tags 1 and 2 exercise traversal mechanics.


def _record(tag: int, payload: bytes) -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_index_children_keeps_first_duplicate_payload() -> None:
    """Match find_child semantics when a parent repeats a tag."""
    payload = _record(1, b"first") + _record(2, b"other") + _record(1, b"second")

    assert index_children(payload) == {1: b"first", 2: b"other"}


def test_index_children_rejects_truncated_trailing_record() -> None:
    """Reject a corrupt nested container instead of returning partial state."""
    payload = _record(1, b"valid") + struct.pack("<HI", 2, 20) + b"short"

    with pytest.raises(ValueError, match="Truncated payload"):
        index_children(payload)


def test_read_record_rejects_truncated_header_and_payload() -> None:
    """Distinguish incomplete headers from declared payload overruns."""
    with pytest.raises(ValueError, match="Truncated header"):
        read_record(b"\x01", 0)
    with pytest.raises(ValueError, match="Truncated payload"):
        read_record(struct.pack("<HI", 1, 10) + b"short", 0)


def test_strict_and_recovery_record_iterators_have_distinct_contracts() -> None:
    """Keep partial traversal confined to the explicitly named recovery API."""
    payload = _record(1, b"ok") + struct.pack("<HI", 2, 50) + b"short"

    with pytest.raises(ValueError, match="Truncated payload"):
        list(iter_records(payload))
    assert list(iter_record_prefix(payload)) == [(1, b"ok")]


def test_find_model_root_supports_prefix_and_rejects_invalid_data() -> None:
    """Find a plausible root after a prefix but reject undersized lookalikes."""
    child = _record(0x01F5, bytes(100))
    root = _record(0x01F4, child)

    assert find_model_root(root) == 0
    assert find_model_root(b"prefix" + root) == len(b"prefix")
    with pytest.raises(ValueError, match="Could not locate"):
        find_model_root(_record(0x01F4, b"too short"))


def test_scalar_and_guid_helpers_handle_short_payloads() -> None:
    """Cover empty/short scalar behavior and GUID zero padding."""
    assert read_compact_int(b"") == 0
    assert read_compact_int(b"\x34\x12") == 0x1234
    with pytest.raises(ValueError, match="at most 4 bytes"):
        read_compact_int(bytes(5))
    assert read_bool(b"") is False
    assert read_bool(b"\x02") is True
    assert read_u32_le(b"\x34\x12") == 0x1234
    assert format_guid(bytes.fromhex("33221100554477668899aabbccddeeff")) == ("00112233-4455-6677-8899-aabbccddeeff")
    assert format_guid(b"\x01") == "00000001-0000-0000-0000-000000000000"
