# SPDX-License-Identifier: MIT
"""Inspect parser support and failures for pre-ZIP SketchUp files.

Diagnostics distinguish three questions: whether a complete model parses,
whether every class declared by its ``CVersionMap`` is supported, and which
runtime-class tags actually occur in the object graph. The file helpers do not
modify their input.

Example
-------
::

    report = diagnose_legacy_class_coverage_file("legacy.skp")
    for entry in report.missing_entries:
        print(entry.class_name, entry.version)
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .class_support import (
    HEURISTIC_LEGACY_OBJECT_CLASSES,
    SUPPORTED_PRE_ZIP_OBJECT_CLASSES,
)
from .errors import UnsupportedLegacyObjectError
from .envelope import VersionMapEntry, read_legacy_envelope
from .parser import parse_legacy_model


@dataclass(frozen=True, slots=True)
class LegacyDiagnosticIssue:
    """One diagnostic issue found while parsing a legacy stream."""

    kind: str
    message: str
    class_name: str | None = None
    offset: int | None = None
    schema: int | None = None
    class_index: int | None = None
    object_index: int | None = None
    tag_kind: str | None = None


@dataclass(frozen=True, slots=True)
class LegacyDiagnosticReport:
    """Summary of parser-coverage issues for one legacy stream."""

    issues: tuple[LegacyDiagnosticIssue, ...]

    @property
    def ok(self) -> bool:
        """Return ``True`` when the stream parsed without diagnostic issues."""
        return not self.issues


@dataclass(frozen=True, slots=True)
class LegacyClassCoverageEntry:
    """Support status for one class in a legacy version map."""

    class_name: str
    version: int
    status: str


@dataclass(frozen=True, slots=True)
class LegacyClassCoverageReport:
    """Coverage summary for classes declared by a legacy version map."""

    entries: tuple[LegacyClassCoverageEntry, ...]
    issues: tuple[LegacyDiagnosticIssue, ...] = ()

    @property
    def ok(self) -> bool:
        """Return ``True`` when the version map was read without issues."""
        return not self.issues

    @property
    def missing_entries(self) -> tuple[LegacyClassCoverageEntry, ...]:
        """Return version-map classes without parser support yet."""
        return tuple(entry for entry in self.entries if entry.status == "missing")

    @property
    def heuristic_entries(self) -> tuple[LegacyClassCoverageEntry, ...]:
        """Return version-map classes currently recovered heuristically."""
        return tuple(entry for entry in self.entries if entry.status == "heuristic")

    @property
    def supported_entries(self) -> tuple[LegacyClassCoverageEntry, ...]:
        """Return version-map classes with direct parser support."""
        return tuple(entry for entry in self.entries if entry.status == "supported")


@dataclass(frozen=True, slots=True)
class LegacyRuntimeClassObservation:
    """Observed runtime-class tags for one class declared by a legacy version map."""

    class_name: str
    version: int
    status: str
    count: int
    first_offset: int | None


@dataclass(frozen=True, slots=True)
class LegacyRuntimeClassReport:
    """Runtime-class tag observations for one legacy stream."""

    entries: tuple[LegacyRuntimeClassObservation, ...]
    issues: tuple[LegacyDiagnosticIssue, ...] = ()

    @property
    def ok(self) -> bool:
        """Return ``True`` when runtime-class observations were read cleanly."""
        return not self.issues

    @property
    def observed_entries(self) -> tuple[LegacyRuntimeClassObservation, ...]:
        """Return classes whose runtime-class tag appears in the stream."""
        return tuple(entry for entry in self.entries if entry.count > 0)

    @property
    def missing_observed_entries(self) -> tuple[LegacyRuntimeClassObservation, ...]:
        """Return observed runtime classes without direct parser support."""
        return tuple(entry for entry in self.entries if entry.count > 0 and entry.status == "missing")

    @property
    def heuristic_observed_entries(self) -> tuple[LegacyRuntimeClassObservation, ...]:
        """Return observed runtime classes currently recovered heuristically."""
        return tuple(entry for entry in self.entries if entry.count > 0 and entry.status == "heuristic")


def diagnose_legacy_stream(stream: BinaryIO) -> LegacyDiagnosticReport:
    """Parse a legacy stream and return unsupported-class diagnostics."""
    # Convert only expected format/parser boundaries. Unrelated programming
    # errors must escape instead of being mislabeled as corrupt user files.
    try:
        parse_legacy_model(stream)
    except UnsupportedLegacyObjectError as exc:
        return LegacyDiagnosticReport(
            issues=(
                LegacyDiagnosticIssue(
                    kind="unsupported_object",
                    message=str(exc),
                    class_name=exc.class_name,
                    offset=exc.offset,
                    schema=exc.schema,
                    class_index=exc.class_index,
                    object_index=exc.object_index,
                    tag_kind=exc.tag_kind,
                ),
            )
        )
    except NotImplementedError as exc:
        return LegacyDiagnosticReport(
            issues=(
                LegacyDiagnosticIssue(
                    kind="not_implemented",
                    message=str(exc),
                ),
            )
        )
    except (EOFError, UnicodeDecodeError, ValueError) as exc:
        return LegacyDiagnosticReport(
            issues=(_invalid_legacy_envelope_issue(exc),),
        )
    return LegacyDiagnosticReport(issues=())


def diagnose_legacy_bytes(data: bytes) -> LegacyDiagnosticReport:
    """Parse legacy bytes and return unsupported-class diagnostics."""
    return diagnose_legacy_stream(io.BytesIO(data))


def diagnose_legacy_file(path: str | Path) -> LegacyDiagnosticReport:
    """Parse a legacy file and return unsupported-class diagnostics."""
    with Path(path).open("rb") as stream:
        return diagnose_legacy_stream(stream)


def diagnose_legacy_class_coverage_stream(
    stream: BinaryIO,
) -> LegacyClassCoverageReport:
    """Read the legacy version map and report per-class support coverage."""
    try:
        version_map = _read_legacy_version_map_only(stream)
    except (EOFError, UnicodeDecodeError, ValueError) as exc:
        return LegacyClassCoverageReport(
            entries=(),
            issues=(_invalid_legacy_envelope_issue(exc),),
        )
    # CVersionMap describes what the file may instantiate, not what it actually
    # contains. Runtime observations below answer that separate question.
    entries = tuple(
        LegacyClassCoverageEntry(
            class_name=entry.class_name,
            version=entry.version,
            status=_class_support_status(entry.class_name),
        )
        for entry in version_map
        if entry.class_name != "End-Of-Version-Map"
    )
    return LegacyClassCoverageReport(entries=entries)


def diagnose_legacy_class_coverage_bytes(data: bytes) -> LegacyClassCoverageReport:
    """Read legacy bytes and report per-class support coverage."""
    return diagnose_legacy_class_coverage_stream(io.BytesIO(data))


def diagnose_legacy_class_coverage_file(path: str | Path) -> LegacyClassCoverageReport:
    """Read a legacy file and report per-class support coverage."""
    with Path(path).open("rb") as stream:
        return diagnose_legacy_class_coverage_stream(stream)


def diagnose_legacy_runtime_classes_stream(
    stream: BinaryIO,
) -> LegacyRuntimeClassReport:
    """Report runtime-class tags actually observed in a legacy stream."""
    # Runtime tag discovery needs random byte searches, so snapshot the stream
    # once. This diagnostic path is not used by normal model loads.
    data = stream.read()
    try:
        version_map = _read_legacy_version_map_only(io.BytesIO(data))
    except (EOFError, UnicodeDecodeError, ValueError) as exc:
        return LegacyRuntimeClassReport(
            entries=(),
            issues=(_invalid_legacy_envelope_issue(exc),),
        )
    entries = tuple(
        _runtime_class_observation(data, entry) for entry in version_map if entry.class_name != "End-Of-Version-Map"
    )
    return LegacyRuntimeClassReport(entries=entries)


def diagnose_legacy_runtime_classes_bytes(data: bytes) -> LegacyRuntimeClassReport:
    """Report runtime-class tags actually observed in legacy bytes."""
    return diagnose_legacy_runtime_classes_stream(io.BytesIO(data))


def diagnose_legacy_runtime_classes_file(path: str | Path) -> LegacyRuntimeClassReport:
    """Report runtime-class tags actually observed in a legacy file."""
    with Path(path).open("rb") as stream:
        return diagnose_legacy_runtime_classes_stream(stream)


def _read_legacy_version_map_only(stream: BinaryIO) -> list[VersionMapEntry]:
    return list(read_legacy_envelope(stream).version_map)


def _class_support_status(class_name: str) -> str:
    if class_name in SUPPORTED_PRE_ZIP_OBJECT_CLASSES:
        return "supported"
    if class_name in HEURISTIC_LEGACY_OBJECT_CLASSES:
        return "heuristic"
    return "missing"


def _invalid_legacy_envelope_issue(exc: Exception) -> LegacyDiagnosticIssue:
    return LegacyDiagnosticIssue(
        kind="invalid_legacy_envelope",
        message=str(exc),
    )


def _runtime_class_observation(data: bytes, entry: VersionMapEntry) -> LegacyRuntimeClassObservation:
    offsets = _runtime_class_offsets(data, entry.class_name)
    return LegacyRuntimeClassObservation(
        class_name=entry.class_name,
        version=entry.version,
        status=_class_support_status(entry.class_name),
        count=len(offsets),
        first_offset=offsets[0] if offsets else None,
    )


def _runtime_class_offsets(data: bytes, class_name: str) -> tuple[int, ...]:
    encoded_name = class_name.encode("ascii")
    name_header = len(encoded_name).to_bytes(2, "little") + encoded_name
    offsets: list[int] = []
    header_offset = data.find(name_header, 0)
    while header_offset >= 4:
        tag_offset = header_offset - 4
        # Require the CArchive new-class marker before the length/name pair to
        # avoid counting ordinary strings that equal a runtime class name.
        if data[tag_offset : tag_offset + 2] == b"\xff\xff":
            offsets.append(tag_offset)
        header_offset = data.find(name_header, header_offset + 1)
    return tuple(offsets)
