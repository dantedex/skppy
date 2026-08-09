# SPDX-License-Identifier: MIT
"""Classic VFF header and deterministic ZIP container construction."""

from __future__ import annotations

import io
import struct
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from ..data_structure.header import SkpHeader

_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def encode_classic_header(header: SkpHeader) -> bytes:
    """Encode the BOM-prefixed VFF header used by modern SKP files."""
    if header.vff_magic != "VFF":
        raise ValueError("Modern SKP output requires a VFF header")
    fields = struct.pack(
        "<HHHI",
        header.vff_field_1,
        header.vff_field_2,
        header.vff_field_3,
        header.vff_field_4,
    )
    return _encode_prefixed_utf16(header.product_name) + _encode_prefixed_utf16(header.version_string) + b"VFF" + fields


def build_modern_container(
    entries: Mapping[str, bytes],
    header: SkpHeader,
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    """Build a deterministic prefixed ZIP container containing ``model.dat``."""
    if "model.dat" not in entries:
        raise ValueError("Modern SKP output requires a model.dat entry")

    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        for name, payload in entries.items():
            _validate_entry_name(name)
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
            info.compress_type = compression
            archive.writestr(info, payload)
    return encode_classic_header(header) + archive_bytes.getvalue()


def write_modern_container(
    filepath: str | Path,
    entries: Mapping[str, bytes],
    header: SkpHeader,
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> Path:
    """Write a modern container and return its destination path."""
    path = Path(filepath)
    path.write_bytes(build_modern_container(entries, header, compression=compression))
    return path


def _encode_prefixed_utf16(value: str) -> bytes:
    """Encode the short BOM/marker/length form emitted by modern SketchUp."""
    if len(value) > 0xFF:
        raise ValueError("VFF header strings cannot exceed 255 UTF-16 code units")
    encoded = value.encode("utf-16-le")
    if len(encoded) != len(value) * 2:
        raise ValueError("VFF header strings must use BMP Unicode characters")
    return b"\xff\xfe\xff" + bytes((len(value),)) + encoded


def _validate_entry_name(name: str) -> None:
    """Reject absolute and parent-relative ZIP names at the write boundary."""
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
        raise ValueError(f"Unsafe SKP ZIP entry name: {name!r}")
