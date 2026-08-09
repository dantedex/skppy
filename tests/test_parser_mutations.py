# SPDX-License-Identifier: MIT
"""Deterministic mutation tests for binary parser boundaries."""

from __future__ import annotations

import io
import random
import struct
import zipfile

import pytest

from skppy.parser.material_parser import _parse_material_xml
from skppy.parser.tlv import (
    find_model_root,
    iter_record_prefix,
    read_record,
    read_utf8,
)
from skppy.parser_legacy.binary import (
    ArchiveIndexTable,
    ArchiveObjectTag,
    LegacyArchiveBuffer,
    LegacyArchiveReader,
)


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_tlv_length_mutations_stop_at_record_boundaries() -> None:
    """Reject or stop on mutated lengths without reading beyond the buffer."""
    original = _record(1, b"abc") + _record(2, b"defg")
    mutations = []
    for offset in (2, 3, 4, 5, 11, 12, 13, 14):
        for replacement in (0x00, 0x01, 0x7F, 0xFF):
            mutated = bytearray(original)
            mutated[offset] = replacement
            mutations.append(bytes(mutated))

    for mutated in mutations:
        records = list(iter_record_prefix(mutated))
        assert all(isinstance(tag, int) and isinstance(payload, bytes) for tag, payload in records)
        assert sum(len(payload) + 6 for _, payload in records) <= len(mutated)

    with pytest.raises(ValueError, match="Truncated payload"):
        read_record(_record(1, b"abc")[:-1], 0)


def test_random_tlv_inputs_fail_only_at_documented_root_boundary() -> None:
    """Fuzz arbitrary TLV bytes without exposing struct or index errors."""
    random_source = random.Random(0x5A17)
    for _ in range(500):
        data = random_source.randbytes(random_source.randrange(0, 96))
        list(iter_record_prefix(data))
        with pytest.raises(ValueError, match="Could not locate model root"):
            find_model_root(data)


def test_carchive_reference_mutations_have_bounded_failures() -> None:
    """Decode mutated archive tags or report only expected input failures."""
    random_source = random.Random(0xCA11)
    for _ in range(500):
        data = random_source.randbytes(random_source.randrange(0, 12))
        reader = LegacyArchiveReader(LegacyArchiveBuffer(data))
        try:
            tag = reader.read_object_tag()
        except (EOFError, UnicodeDecodeError):
            continue
        assert tag.kind in {"null", "object_ref", "new_class", "class_ref"}

    table = ArchiveIndexTable()
    for index in (1, 0x7FFF, 0x7FFFFFFF):
        tag = ArchiveObjectTag("object_ref", index, index)
        handle = table.resolve_or_register_object_tag(tag)
        assert handle.kind == "object_ref"
        assert handle.object_index == index
        assert handle.class_name is None


def test_string_encoding_mutations_are_explicit() -> None:
    """Decode supported encodings and reject malformed legacy framing."""
    little = b"\xff\xfe\xff\x03A\x00B\x00C\x00"
    big = b"\xfe\xff\xff\x03\x00A\x00B\x00C"
    assert LegacyArchiveReader(io.BytesIO(little)).read_legacy_utf16_string("name") == "ABC"
    assert LegacyArchiveReader(io.BytesIO(big)).read_legacy_utf16_string("name") == "ABC"

    malformed = (
        b"\x00\x00\xff\x00",
        b"\xff\xfe\x00\x00",
        b"\xff\xfe\xff\x03A\x00",
    )
    for payload in malformed:
        with pytest.raises((EOFError, ValueError)):
            LegacyArchiveReader(io.BytesIO(payload)).read_legacy_utf16_string("name")

    assert read_utf8(b"valid") == "valid"
    assert read_utf8(b"bad\xfftext") == "bad\ufffdtext"


@pytest.mark.parametrize(
    "resource_path",
    [
        "./missing.png",
        "materials/Paint/missing.png",
        "nested/missing.png",
        "../outside.png",
    ],
)
def test_missing_mutated_zip_resource_paths_remain_nonfatal(resource_path: str) -> None:
    """Preserve texture intent when mutated ZIP-relative resources are absent."""
    xml = f"""<materialDocument><material hasTexture="1">
      <texture textureFilename="missing.png">
        <images><image path="{resource_path}" /></images>
      </texture>
    </material></materialDocument>"""
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("unrelated", b"data")
    archive_bytes.seek(0)

    with zipfile.ZipFile(archive_bytes) as archive:
        material = _parse_material_xml(xml.encode(), "Paint", archive, {})

    assert material.has_texture is True
    assert material.texture is not None
    assert material.texture.filename == "missing.png"
    assert material.texture.data is None


def test_zip_resource_crc_corruption_raises_archive_error() -> None:
    """Expose corrupt resource bytes as ``BadZipFile`` rather than partial data."""
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("resource.bin", b"known resource bytes")
    corrupted = bytearray(archive_bytes.getvalue())
    payload_offset = corrupted.find(b"known resource bytes")
    assert payload_offset >= 0
    corrupted[payload_offset] ^= 0xFF

    with zipfile.ZipFile(io.BytesIO(corrupted)) as archive:
        with pytest.raises(zipfile.BadZipFile, match="Bad CRC-32"):
            archive.read("resource.bin")
