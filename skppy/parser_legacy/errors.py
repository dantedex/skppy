# SPDX-License-Identifier: MIT
"""Structured errors raised while reading pre-ZIP SketchUp archives."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UnsupportedLegacySchemaError(NotImplementedError):
    """A known archive class uses a schema without a verified reader."""

    class_name: str
    schema: int
    file_version: str
    offset: int | None = None
    object_index: int | None = None

    def __str__(self) -> str:
        """Return a diagnostic message with the archive context."""
        context = [
            f"SketchUp {self.file_version}",
            self.class_name,
            f"schema {self.schema}",
        ]
        if self.object_index is not None:
            context.append(f"object {self.object_index}")
        if self.offset is not None:
            context.append(f"offset 0x{self.offset:X}")
        return "Unsupported legacy archive schema: " + ", ".join(context)


@dataclass(frozen=True, slots=True)
class MissingLegacySchemaError(ValueError):
    """A required runtime class is absent from the file CVersionMap."""

    class_name: str
    file_version: str

    def __str__(self) -> str:
        """Return a diagnostic message identifying the missing class."""
        return f"{self.class_name} is missing from the CVersionMap for SketchUp {self.file_version}."


class UnsupportedLegacyObjectError(NotImplementedError):
    """Unsupported runtime-class error with archive context fields."""

    def __init__(
        self,
        *,
        class_name: str | None,
        offset: int,
        schema: int | None,
        class_index: int | None,
        object_index: int | None,
        tag_kind: str,
    ) -> None:
        """Build an unsupported-object error with machine-readable context."""
        self.class_name = class_name
        self.offset = offset
        self.schema = schema
        self.class_index = class_index
        self.object_index = object_index
        self.tag_kind = tag_kind
        super().__init__(
            "Unsupported legacy object class "
            f"{class_name!r} at offset {offset} "
            f"(schema={schema!r}, class_index={class_index!r}, "
            f"object_index={object_index!r}, tag_kind={tag_kind!r})."
        )
