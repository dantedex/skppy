# SPDX-License-Identifier: MIT
"""Read little-endian primitives and MFC-style object tags from legacy SKP.

Pre-ZIP files use one ordered index namespace for both runtime classes and
objects. :class:`ArchiveIndexTable` preserves that identity model, while
:class:`LegacyArchiveReader` decodes scalar values, legacy UTF-16 strings, and
compact or extended object/class tags. Higher-level legacy readers should use
one shared archive session rather than constructing independent tables.

Example
-------
::

    import io

    reader = LegacyArchiveReader(io.BytesIO(b"\x2a\x00\x00\x00"))
    assert reader.read_u32() == 42
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from typing import Any, BinaryIO, Literal

from .._cancellation import check_cancelled

ArchiveTagKind = Literal["null", "object_ref", "new_class", "class_ref"]
ArchiveIndexEntryKind = Literal["class", "object"]
ArchiveObjectHandleKind = Literal["null", "object_ref", "new_object"]


class LegacyArchiveBuffer(io.RawIOBase):
    """Seekable in-memory stream with allocation-free scalar decoding."""

    def __init__(self, data: bytes) -> None:
        """Wrap immutable archive bytes and start at offset zero."""
        super().__init__()
        self._data = data
        self._position = 0

    def readable(self) -> bool:
        """Return whether this stream supports reading."""
        return True

    def seekable(self) -> bool:
        """Return whether this stream supports random access."""
        return True

    def read(self, size: int = -1) -> bytes:
        """Read at most *size* bytes and advance the cursor."""
        self._checkClosed()
        if size is None or size < 0:
            end = len(self._data)
        else:
            end = min(self._position + size, len(self._data))
        data = self._data[self._position : end]
        self._position = end
        return data

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Move the cursor using standard binary-stream seek semantics."""
        self._checkClosed()
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self._position + offset
        elif whence == io.SEEK_END:
            position = len(self._data) + offset
        else:
            raise ValueError(f"Invalid seek mode: {whence}")
        if position < 0:
            raise ValueError("Negative seek position")
        self._position = position
        return position

    def tell(self) -> int:
        """Return the current byte offset."""
        self._checkClosed()
        return self._position

    def unpack_scalar(self, fmt: str, size: int) -> Any:
        """Decode one scalar at the cursor without allocating a byte slice."""
        end = self._position + size
        if end > len(self._data):
            raise EOFError(f"Unexpected end of file while reading {fmt}.")
        value = struct.unpack_from(fmt, self._data, self._position)[0]
        self._position = end
        return value


@dataclass(frozen=True, slots=True)
class ArchiveObjectTag:
    """Decoded object/class tag from an old MFC-style archive."""

    kind: ArchiveTagKind
    raw_tag: int
    index: int | None = None
    schema: int | None = None
    class_name: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveIndexEntry:
    """One entry in the shared CArchive class/object index table."""

    index: int
    kind: ArchiveIndexEntryKind
    class_name: str | None
    schema: int | None


@dataclass(frozen=True, slots=True)
class ArchiveObjectRegistration:
    """Indices allocated while reading one new object payload."""

    class_index: int | None
    object_index: int
    class_name: str | None
    schema: int | None


@dataclass(frozen=True, slots=True)
class ArchiveObjectHandle:
    """Object-context tag resolved against the archive index table."""

    kind: ArchiveObjectHandleKind
    tag: ArchiveObjectTag
    object_index: int | None
    class_index: int | None
    class_name: str | None
    schema: int | None


class ArchiveIndexTable:
    """Shared CArchive index table for runtime classes and object instances.

    MFC uses one monotonically increasing index space for both entry kinds.
    Splitting this into independent class and object counters shifts every
    subsequent back-reference and usually corrupts face topology much later.
    """

    def __init__(self) -> None:
        """Create an empty table with index zero reserved for null objects."""
        self._entries = [ArchiveIndexEntry(0, "object", None, None)]
        self._next_index = 1

    def register_implicit_object(self, class_name: str, schema: int | None = None) -> ArchiveObjectRegistration:
        """Register an implicit root-like object not preceded by an archive tag."""
        class_index = self.register_class(class_name, schema)
        object_index = self.register_object(class_name, schema)
        return ArchiveObjectRegistration(
            class_index=class_index,
            object_index=object_index,
            class_name=class_name,
            schema=schema,
        )

    def register_new_object_tag(self, tag: ArchiveObjectTag) -> ArchiveObjectRegistration | None:
        """Register table entries implied by an object-context archive tag."""
        if tag.kind in {"null", "object_ref"}:
            return None
        if tag.kind == "new_class":
            # A new runtime class declaration also introduces its first object;
            # both consume slots in the single shared index namespace.
            class_index = self.register_class(tag.class_name, tag.schema)
            object_index = self.register_object(tag.class_name, tag.schema)
            return ArchiveObjectRegistration(
                class_index=class_index,
                object_index=object_index,
                class_name=tag.class_name,
                schema=tag.schema,
            )
        # A class_ref means "new object of an already declared runtime class".
        # Some malformed/old streams point at an object slot carrying the same
        # class metadata, so retain the fallback observed in legacy archives.
        class_entry = self.resolve_class(tag.index) or self.resolve_object(tag.index)
        class_name = class_entry.class_name if class_entry else None
        schema = class_entry.schema if class_entry else None
        return ArchiveObjectRegistration(
            class_index=tag.index,
            object_index=self.register_object(class_name, schema),
            class_name=class_name,
            schema=schema,
        )

    def resolve_or_register_object_tag(self, tag: ArchiveObjectTag) -> ArchiveObjectHandle:
        """Resolve an object tag, registering new entries in archive order."""
        if tag.kind == "null":
            return ArchiveObjectHandle("null", tag, 0, None, None, None)
        if tag.kind == "object_ref":
            object_entry = self.resolve_object(tag.index)
            return ArchiveObjectHandle(
                "object_ref",
                tag,
                tag.index,
                None,
                object_entry.class_name if object_entry else None,
                object_entry.schema if object_entry else None,
            )
        registration = self.register_new_object_tag(tag)
        assert registration is not None
        return ArchiveObjectHandle(
            "new_object",
            tag,
            registration.object_index,
            registration.class_index,
            registration.class_name,
            registration.schema,
        )

    def register_class(self, class_name: str | None, schema: int | None) -> int:
        """Append a runtime-class entry and return its archive index."""
        return self._append_entry("class", class_name, schema)

    def register_object(self, class_name: str | None, schema: int | None) -> int:
        """Append an object-instance entry and return its archive index."""
        return self._append_entry("object", class_name, schema)

    def resolve_class(self, index: int | None) -> ArchiveIndexEntry | None:
        """Return a class entry by index, or ``None`` when it is unknown."""
        entry = self._entry_at(index)
        return entry if entry is not None and entry.kind == "class" else None

    def resolve_object(self, index: int | None) -> ArchiveIndexEntry | None:
        """Return an object entry by index, or ``None`` when it is unknown."""
        entry = self._entry_at(index)
        return entry if entry is not None and entry.kind == "object" else None

    @property
    def entries(self) -> tuple[ArchiveIndexEntry, ...]:
        """Return entries in archive-index order."""
        return tuple(self._entries[1:])

    def _entry_at(self, index: int | None) -> ArchiveIndexEntry | None:
        if index is None or index <= 0 or index >= len(self._entries):
            return None
        return self._entries[index]

    def _append_entry(
        self,
        kind: ArchiveIndexEntryKind,
        class_name: str | None,
        schema: int | None,
    ) -> int:
        index = self._next_index
        self._entries.append(ArchiveIndexEntry(index, kind, class_name, schema))
        self._next_index += 1
        return index


class LegacyArchiveReader:
    """Cursor for primitive values and CArchive object/class tags."""

    def __init__(self, stream: BinaryIO) -> None:
        """Store the binary stream used by this reader."""
        self.stream = stream

    def tell(self) -> int:
        """Return the current stream offset."""
        return self.stream.tell()

    def read_u8(self) -> int:
        """Read one unsigned byte."""
        return int(self._read_struct("<B", 1))

    def read_u16(self) -> int:
        """Read one little-endian unsigned 16-bit integer."""
        return int(self._read_struct("<H", 2))

    def read_u32(self) -> int:
        """Read one little-endian unsigned 32-bit integer."""
        return int(self._read_struct("<I", 4))

    def read_i32(self) -> int:
        """Read one little-endian signed 32-bit integer."""
        return int(self._read_struct("<i", 4))

    def read_u64(self) -> int:
        """Read one little-endian unsigned 64-bit integer."""
        return int(self._read_struct("<Q", 8))

    def read_f32(self) -> float:
        """Read one little-endian 32-bit float."""
        return float(self._read_struct("<f", 4))

    def read_f64(self) -> float:
        """Read one little-endian 64-bit float."""
        return float(self._read_struct("<d", 8))

    def read_bool(self) -> bool:
        """Read the one-byte boolean representation used by ``CArchive``."""
        return bool(self.read_u8())

    def read_vec3_f64(self) -> tuple[float, float, float]:
        """Read a point/vector/unit-vector triple of doubles."""
        return (self.read_f64(), self.read_f64(), self.read_f64())

    def read_vec4_f64(self) -> tuple[float, float, float, float]:
        """Read four doubles such as a SketchUp plane equation."""
        return (self.read_f64(), self.read_f64(), self.read_f64(), self.read_f64())

    def read_rgba(self) -> tuple[int, int, int, int]:
        """Read a four-byte ``CColor`` payload as RGBA bytes."""
        return (self.read_u8(), self.read_u8(), self.read_u8(), self.read_u8())

    def read_legacy_utf16_string(self, label: str) -> str:
        """Read the old BOM-prefixed SketchUp UTF-16 string format."""
        bom = self._read_exact(2, f"{label} BOM")
        if bom == b"\xff\xfe":
            byteorder, encoding = "little", "utf-16le"
        elif bom == b"\xfe\xff":
            byteorder, encoding = "big", "utf-16be"
        else:
            raise ValueError(f"Unexpected UTF-16 BOM while reading {label}: {bom.hex()}")
        if self._read_exact(1, f"{label} string marker") != b"\xff":
            raise ValueError(f"Unexpected legacy string marker while reading {label}.")
        # MFC CString uses a compact one-byte length, then 0xFF + u16, with
        # 0xFFFF + u32 as the large-string escape. Length counts UTF-16 units.
        length_marker = self._read_exact(1, f"{label} string length")
        if length_marker != b"\xff":
            length = length_marker[0]
        else:
            length = self._read_struct(">H" if byteorder == "big" else "<H", 2)
            if length == 0xFFFF:
                length = self._read_struct(">I" if byteorder == "big" else "<I", 4)
        return self._read_exact(length * 2, label).decode(encoding)

    def read_object_tag(self) -> ArchiveObjectTag:
        """Read a CArchive object/class marker without consuming payload data."""
        tag = self.read_u16()
        # 0x7FFF escapes the compact 15-bit index space. The high bit of the
        # following u32 distinguishes an existing class from an object ref.
        if tag == 0x7FFF:
            extended = self.read_u32()
            if extended & 0x80000000:
                return ArchiveObjectTag("class_ref", extended, extended & 0x7FFFFFFF)
            return ArchiveObjectTag("object_ref", extended, extended)
        if tag == 0xFFFF:
            # New runtime class: schema and ASCII class name are inline; the
            # object's body starts immediately after the name.
            schema = self.read_u16()
            name_length = self.read_u16()
            class_name = self._read_exact(name_length, "runtime class name").decode("ascii")
            return ArchiveObjectTag("new_class", tag, schema=schema, class_name=class_name)
        if tag & 0x8000:
            # Compact existing-class reference: this still introduces a new
            # object body, unlike the plain object reference below.
            return ArchiveObjectTag("class_ref", tag, tag & 0x7FFF)
        if tag == 0:
            return ArchiveObjectTag("null", tag, 0)
        return ArchiveObjectTag("object_ref", tag, tag)

    def read_exact(self, size: int, label: str) -> bytes:
        """Read an exact byte span from the current stream position."""
        return self._read_exact(size, label)

    def _read_struct(self, fmt: str, size: int) -> Any:
        if isinstance(self.stream, LegacyArchiveBuffer):
            check_cancelled()
            return self.stream.unpack_scalar(fmt, size)
        return struct.unpack(fmt, self._read_exact(size, fmt))[0]

    def _read_exact(self, size: int, label: str) -> bytes:
        check_cancelled()
        data = self.stream.read(size)
        if len(data) != size:
            raise EOFError(f"Unexpected end of file while reading {label}.")
        return data
