# SPDX-License-Identifier: MIT
"""Runtime-class support catalog for the legacy SketchUp parser."""

from .schema import LEGACY_CLASS_SCHEMAS

SUPPORTED_LEGACY_OBJECT_CLASSES: frozenset[str] = frozenset(LEGACY_CLASS_SCHEMAS)
"""Legacy classes with direct dispatch or confirmed base-payload support."""

SUPPORTED_PRE_ZIP_OBJECT_CLASSES: frozenset[str] = frozenset(
    (*SUPPORTED_LEGACY_OBJECT_CLASSES, "CCustomLineStyle", "CLayerGroup")
)
"""Classes directly supported across all pre-ZIP save targets."""


HEURISTIC_LEGACY_OBJECT_CLASSES: frozenset[str] = frozenset()
"""Legacy classes recovered by bounded scans instead of full dispatch."""
