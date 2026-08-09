# SPDX-License-Identifier: MIT
"""
Parser for the SketchUp file header.

The header precedes the embedded ZIP archive and encodes product name,
version string, and VFF fields.

Entry point::

    from skppy.parser.header_parser import parse_header

    with open(filepath, "rb") as fh:
        header = parse_header(fh)

Raises
------
OldFormatError
    If this ZIP-specific parser receives a legacy pre-ZIP binary format. Use
    :func:`skppy.load` for automatic dispatch.
"""

from __future__ import annotations

import io
import struct
from typing import Optional, Tuple

from ..data_structure.header import SkpHeader
from ..exceptions import OldFormatError


def parse_header(stream: io.BufferedReader, locate_zip: bool = True) -> SkpHeader:
    """
    Parse the SketchUp file header from *stream* and return a :class:`SkpHeader`.

    Detects two header variants automatically:

    1. **Classic header** -- BOM (0xFF 0xFE or 0xFE 0xFF) followed by
       length-prefixed UTF-16 product name + version string, then a 10-byte
       VFF block.
    2. **Alternative header** -- Raw UTF-16-LE string
       ``"SketchUp Model {X.Y.Z}\\n"`` without BOM, zero-padded to 64 bytes.
       The ZIP archive starts immediately after.

    Parameters
    ----------
    stream:
        Open binary file positioned at byte 0.
    locate_zip:
        When True, scan ahead to confirm the ZIP signature (PK\\x03\\x04) and
        record the byte offset in :attr:`SkpHeader.zip_offset`.

    Returns
    -------
    SkpHeader
        Populated header dataclass.

    Raises
    ------
    EOFError
        If the file is too short to contain a valid header.
    ValueError
        If the header bytes cannot be decoded.
    """
    probe = stream.read(2)
    if len(probe) < 2:
        raise EOFError("File is too short to be a valid .skp file.")

    if probe[:2] in (b"\xff\xfe", b"\xfe\xff"):
        # Classic SketchUp header:
        #   BOM + length-prefixed UTF-16 product name
        #   BOM + length-prefixed UTF-16 version string
        #   "VFF" magic + 10-byte VFF field block
        stream.seek(0)
        product_name = _read_prefixed_utf16_string(stream, "product name")
        version_string = _read_prefixed_utf16_string(stream, "version string")

        vff_magic = _read_exact(stream, 3, "VFF magic")
        if vff_magic != b"VFF":
            # This is the legacy format (no VFF marker after the two strings)
            raise OldFormatError(
                "Legacy non-ZIP SKP passed to the ZIP header parser; use skppy.load() for automatic CArchive dispatch.",
                filepath=getattr(stream, "name", None),
            )

        vff_fields = _read_exact(stream, 10, "VFF fields")
        vff_f1, vff_f2, vff_f3, vff_f4 = struct.unpack("<HHHI", vff_fields)
    else:
        # Alternative header: raw UTF-16-LE, no BOM, no prefix.
        stream.seek(0)
        raw_header = _read_raw_utf16le_header(stream)
        product_name, version_string = _parse_raw_utf16le_strings(raw_header)
        vff_f1, vff_f2, vff_f3, vff_f4 = 0, 0, 0, 0
        vff_magic = b"---"

    zip_offset = None
    if locate_zip:
        zip_offset = stream.tell()
        signature = stream.read(4)
        if signature != b"PK\x03\x04":
            found = _find_zip_offset(stream)
            zip_offset = found if found is not None else None
        if zip_offset is not None:
            stream.seek(zip_offset)

    version_tuple = _parse_version_tuple(version_string)

    return SkpHeader(
        product_name=product_name,
        version_string=version_string,
        version_tuple=version_tuple,
        vff_magic=vff_magic if isinstance(vff_magic, str) else vff_magic.decode("ascii", errors="replace"),
        vff_field_1=vff_f1,
        vff_field_2=vff_f2,
        vff_field_3=vff_f3,
        vff_field_4=vff_f4,
        zip_offset=zip_offset,
    )


# -
# Raw UTF-16-LE header helpers
# -


def _read_raw_utf16le_header(stream: io.BufferedReader, max_scan: int = 512) -> bytes:
    """
    Read bytes until the ZIP signature is found and return the pre-ZIP header.

    Parameters
    ----------
    stream : io.BufferedReader
        Open binary file; will be repositioned to the ZIP signature offset.
    max_scan : int, optional
        Maximum number of bytes to scan for the ZIP signature.  Default 512.

    Returns
    -------
    bytes
        Raw header bytes preceding the ZIP signature.
    """
    stream.seek(0)
    probe = stream.read(max_scan)
    pk_offset = probe.find(b"PK\x03\x04")
    if pk_offset == -1:
        pk_offset = 64
    header_bytes = probe[:pk_offset]
    stream.seek(pk_offset)
    return header_bytes


def _parse_raw_utf16le_strings(header_bytes: bytes) -> Tuple[str, str]:
    """
    Decode a raw UTF-16-LE header block into product_name and version_string.

    Parameters
    ----------
    header_bytes : bytes
        Raw bytes of the pre-ZIP header.

    Returns
    -------
    tuple[str, str]
        ``(product_name, version_string)`` where version_string is the brace-
        enclosed portion such as ``"{21.1.331}"``.
    """
    n = len(header_bytes)
    if n % 2 == 1:
        header_bytes = header_bytes[:-1]
    # ``errors="replace"`` makes arbitrary truncated header bytes decodable;
    # no broad fallback is needed here and programming errors should surface.
    text = header_bytes.decode("utf-16-le", errors="replace").strip("\x00\r\n ").strip()

    brace_pos = text.find("{")
    if brace_pos != -1:
        product_name = text[:brace_pos].strip()
        version_part = text[brace_pos:].strip().rstrip("\n").rstrip("\r")
    else:
        product_name = text.strip()
        version_part = ""

    return product_name, version_part


# -
# Classic header helpers
# -


def _read_exact(stream: io.BufferedReader, size: int, label: str) -> bytes:
    """
    Read exactly *size* bytes from *stream* or raise EOFError.

    Parameters
    ----------
    stream : io.BufferedReader
        Open binary file.
    size : int
        Number of bytes to read.
    label : str
        Human-readable field name used in the error message.

    Returns
    -------
    bytes
        Exactly *size* bytes.

    Raises
    ------
    EOFError
        If fewer than *size* bytes are available.
    """
    data = stream.read(size)
    if len(data) != size:
        raise EOFError(f"Unexpected end of file while reading {label}.")
    return data


def _read_prefixed_utf16_string(stream: io.BufferedReader, label: str) -> str:
    """Read a BOM-prefixed, length-prefixed UTF-16 string from *stream*.

    The wire format is::

        BOM (2 bytes) + length (2 bytes) + UTF-16 data (length * 2 bytes)

    Parameters
    ----------
    stream : io.BufferedReader
        Open binary file.
    label : str
        Human-readable field name for error messages.

    Returns
    -------
    str
        Decoded string.

    Raises
    ------
    ValueError
        If the BOM is unrecognised or the length is invalid.
    """
    prefix = _read_exact(stream, 4, f"{label} prefix")
    bom = prefix[:2]

    if bom == b"\xff\xfe":
        encoding = "utf-16le"
        length = _decode_prefixed_length(prefix[2:], little_endian=True)
    elif bom == b"\xfe\xff":
        encoding = "utf-16be"
        length = _decode_prefixed_length(prefix[2:], little_endian=False)
    else:
        raise ValueError(f"Unexpected UTF-16 BOM while reading {label}: {bom.hex()}")

    data = _read_exact(stream, length * 2, label)
    return data.decode(encoding)


def _decode_prefixed_length(length_bytes: bytes, little_endian: bool) -> int:
    if len(length_bytes) != 2:
        raise ValueError("Length prefix must be 2 bytes.")
    if length_bytes[0] == 0xFF:
        return length_bytes[1]
    return int.from_bytes(length_bytes, "little" if little_endian else "big")


def _parse_version_tuple(version_string: str) -> Optional[Tuple[int, ...]]:
    """Parse a SketchUp version string into a tuple of integers.

    Accepts strings like ``"{21.1.331}"`` or ``"2021.1.331"`` and
    returns ``(21, 1, 331)`` or ``None`` if parsing fails.

    Parameters
    ----------
    version_string : str
        Raw version string from the file header.

    Returns
    -------
    tuple of int or None
        Parsed version components, or *None* if the string is malformed.
    """
    cleaned = version_string.strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        cleaned = cleaned[1:-1]
    if not cleaned:
        return None
    parts = cleaned.split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _find_zip_offset(stream: io.BufferedReader, max_scan: int = 4096) -> Optional[int]:
    """
    Scan up to *max_scan* bytes for the ZIP local-file signature ``PK\x03\x04``.

    Parameters
    ----------
    stream : io.BufferedReader
        Open binary file.  Stream position is restored after the scan.
    max_scan : int, optional
        Maximum bytes to read when searching.  Default 4096.

    Returns
    -------
    int or None
        Byte offset of the ZIP signature, or None if not found.
    """
    current = stream.tell()
    try:
        stream.seek(0)
        data = stream.read(max_scan)
        idx = data.find(b"PK\x03\x04")
        return None if idx == -1 else idx
    finally:
        stream.seek(current)
