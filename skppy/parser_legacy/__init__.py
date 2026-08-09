# SPDX-License-Identifier: MIT
"""Version-aware parser for pre-ZIP SketchUp binary files."""

from .binary import ArchiveObjectTag, LegacyArchiveReader
from .diagnostics import (
    LegacyClassCoverageEntry,
    LegacyClassCoverageReport,
    LegacyDiagnosticIssue,
    LegacyDiagnosticReport,
    LegacyRuntimeClassObservation,
    LegacyRuntimeClassReport,
    diagnose_legacy_class_coverage_bytes,
    diagnose_legacy_class_coverage_file,
    diagnose_legacy_class_coverage_stream,
    diagnose_legacy_bytes,
    diagnose_legacy_file,
    diagnose_legacy_runtime_classes_bytes,
    diagnose_legacy_runtime_classes_file,
    diagnose_legacy_runtime_classes_stream,
    diagnose_legacy_stream,
)
from .envelope import VersionMapEntry
from .errors import (
    MissingLegacySchemaError,
    UnsupportedLegacyObjectError,
    UnsupportedLegacySchemaError,
)
from .parser import parse_legacy_model
from .parser_types import RootModelPrefixState
from .provenance import ArchiveProvenance

__all__ = [
    "ArchiveObjectTag",
    "ArchiveProvenance",
    "LegacyArchiveReader",
    "LegacyClassCoverageEntry",
    "LegacyClassCoverageReport",
    "LegacyDiagnosticIssue",
    "LegacyDiagnosticReport",
    "LegacyRuntimeClassObservation",
    "LegacyRuntimeClassReport",
    "MissingLegacySchemaError",
    "RootModelPrefixState",
    "UnsupportedLegacyObjectError",
    "UnsupportedLegacySchemaError",
    "VersionMapEntry",
    "diagnose_legacy_bytes",
    "diagnose_legacy_class_coverage_bytes",
    "diagnose_legacy_class_coverage_file",
    "diagnose_legacy_class_coverage_stream",
    "diagnose_legacy_file",
    "diagnose_legacy_runtime_classes_bytes",
    "diagnose_legacy_runtime_classes_file",
    "diagnose_legacy_runtime_classes_stream",
    "diagnose_legacy_stream",
    "parse_legacy_model",
]
