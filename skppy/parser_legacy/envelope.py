# SPDX-License-Identifier: MIT
"""Parse the legacy file envelope and its authoritative class-version map.

The envelope precedes the root object graph and records product/version text,
the model GUID, an informational saved path, timestamp, and ``CVersionMap``.
Later readers select every class layout from the returned
:class:`~skppy.parser_legacy.schema.ArchiveSchema`; they never infer a layout
from neighboring bytes. Use :func:`skppy.load` for normal model loading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from .binary import LegacyArchiveReader
from .schema import ArchiveSchema, SketchUpFormatVersion


@dataclass(frozen=True, slots=True)
class VersionMapEntry:
    """Class-version entry from a legacy ``CVersionMap`` block."""

    class_name: str
    version: int


@dataclass(frozen=True, slots=True)
class ParsedLegacyEnvelope:
    """Versioned file metadata preceding the root archive payload."""

    product_name: str
    version_string: str
    format_version: SketchUpFormatVersion
    model_guid: bytes
    saved_path: str
    timestamp: int
    version_map: tuple[VersionMapEntry, ...]
    archive_schema: ArchiveSchema
    archive_offset: int


def read_legacy_envelope(stream: BinaryIO) -> ParsedLegacyEnvelope:
    """Read the product envelope and authoritative per-file class schema."""
    reader = LegacyArchiveReader(stream)
    product_name = reader.read_legacy_utf16_string("product name")
    version_string = reader.read_legacy_utf16_string("version string")
    format_version = SketchUpFormatVersion.parse(version_string)
    # ZIP-era files have a different container and must never be probed as an
    # MFC CArchive: many early strings would otherwise look superficially valid.
    if not format_version.is_pre_zip:
        raise ValueError(f"SketchUp {format_version} is not a pre-ZIP CArchive file.")
    model_guid = reader.read_exact(16, "model UUID")
    saved_path = reader.read_legacy_utf16_string("saved path")
    timestamp = reader.read_u32()
    # CVersionMap is authoritative per file. Two files saved by the same product
    # can still carry different class schemas after down-saving.
    version_map = _read_version_map(reader)
    archive_schema = ArchiveSchema.from_pairs(
        format_version,
        ((entry.class_name, entry.version) for entry in version_map),
    )
    # The envelope is immutable parser input for every later reader. Construct
    # it only after the complete prefix and version map have been validated.
    return ParsedLegacyEnvelope(
        product_name=product_name,
        version_string=version_string,
        format_version=format_version,
        model_guid=model_guid,
        saved_path=saved_path,
        timestamp=timestamp,
        version_map=version_map,
        archive_schema=archive_schema,
        archive_offset=reader.tell(),
    )


def _read_version_map(reader: LegacyArchiveReader) -> tuple[VersionMapEntry, ...]:
    magic = reader.read_exact(4, "CVersionMap magic")
    if magic != b"\xff\xff\x00\x00":
        raise ValueError(f"Unexpected CVersionMap magic: {magic.hex()}")
    name_len = reader.read_u16()
    name = reader.read_exact(name_len, "CVersionMap name").decode("ascii")
    if name != "CVersionMap":
        raise ValueError(f"Unexpected version map block name: {name!r}")

    entries: list[VersionMapEntry] = []
    while True:
        class_name = reader.read_legacy_utf16_string("version-map class name")
        entry = VersionMapEntry(class_name=class_name, version=reader.read_u32())
        entries.append(entry)
        # The sentinel has a version word like every normal entry and therefore
        # must be read in full before the root archive offset is established.
        if class_name == "End-Of-Version-Map":
            return tuple(entries)
