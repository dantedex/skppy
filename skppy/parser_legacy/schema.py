# SPDX-License-Identifier: MIT
"""Represent product versions and per-file class schemas for legacy SKP.

Every pre-ZIP file carries a ``CVersionMap``. :class:`ArchiveSchema` keeps its
ordered entries and provides contextual lookup errors, while
:func:`require_verified_schema` rejects strict-layout classes before their
unknown bytes can disturb archive alignment.

Example
-------
::

    version = SketchUpFormatVersion.parse("{8.0.1}")
    assert version.is_pre_zip
    assert str(version) == "8.0.1"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .errors import MissingLegacySchemaError, UnsupportedLegacySchemaError


_VERSION_PATTERN = re.compile(r"\{?(\d+)(?:\.(\d+))?(?:\.(\d+))?\}?")

LEGACY_CLASS_SCHEMAS: dict[str, int] = {
    "CArcCurve": 1,
    "CAttribute": 0,
    "CAttributeContainer": 0,
    "CAttributeNamed": 1,
    "CBackgroundImage": 10,
    "CCamera": 5,
    "CComponent": 11,
    "CComponentBehavior": 5,
    "CComponentDefinition": 10,
    "CComponentInstance": 4,
    "CConstructionGeometry": 0,
    "CConstructionLine": 1,
    "CConstructionPoint": 0,
    "CCurve": 4,
    "CDefinitionList": 0,
    "CDib": 3,
    "CDimension": 1,
    "CDimensionLinear": 6,
    "CDimensionRadial": 2,
    "CDimensionStyle": 4,
    "CDrawingElement": 9,
    "CEdge": 2,
    "CEdgeUse": 1,
    "CEntity": 3,
    "CFace": 3,
    "CFaceTextureCoords": 4,
    "CFontManager": 0,
    "CGroup": 1,
    "CImage": 1,
    "CLayer": 2,
    "CLayerManager": 4,
    "CLoop": 1,
    "CMaterial": 12,
    "CMaterialManager": 4,
    "CPageList": 1,
    "CPolyline3d": 0,
    "CRelationship": 0,
    "CRelationshipMap": 0,
    "CRenderingOptions": 36,
    "CSectionPlane": 2,
    "CShadowInfo": 7,
    "CSkFont": 1,
    "CSketchCS": 0,
    "CSketchUpModel": 22,
    "CSketchUpPage": 1,
    "CSkpStyle": 1,
    "CSkpStyleManager": 2,
    "CText": 9,
    "CTextStyle": 5,
    "CTexture": 6,
    "CThumbnail": 1,
    "CVertex": 0,
    "CViewPage": 12,
    "CWatermark": 1,
    "CWatermarkManager": 2,
}
"""Complete class schema map observed in SketchUp 8 archives."""

VERIFIED_CLASS_SCHEMAS: dict[str, frozenset[int]] = {
    "CBackgroundImage": frozenset({10}),
    "CComponent": frozenset({11}),
    # Current SDKs can emit runtime schema 11 while a model saved as SU8 still
    # declares and serializes the version-10 payload through CVersionMap.
    "CComponentDefinition": frozenset({10, 11}),
    # Runtime schema 6 from current SDKs is down-saved using the SU8 v4 body.
    "CComponentInstance": frozenset({4, 6}),
    "CConstructionGeometry": frozenset({0}),
    "CDefinitionList": frozenset({0}),
    "CDimension": frozenset({1}),
    "CDimensionLinear": frozenset({6}),
    "CDimensionRadial": frozenset({2}),
    "CFontManager": frozenset({0}),
    "CPageList": frozenset({1}),
    "CPolyline3d": frozenset({0}),
    "CRelationshipMap": frozenset({0}),
    "CSkpStyleManager": frozenset({2}),
    "CText": frozenset({9}),
    "CThumbnail": frozenset({1}),
    "CWatermark": frozenset({1}),
    "CWatermarkManager": frozenset({2}),
}


def require_verified_schema(
    class_name: str,
    schema: int,
    *,
    file_version: str,
    offset: int,
    object_index: int | None,
) -> None:
    """Reject a known strict-layout class before consuming its payload."""
    supported = VERIFIED_CLASS_SCHEMAS.get(class_name)
    if supported is not None and schema not in supported:
        raise UnsupportedLegacySchemaError(
            class_name=class_name,
            schema=schema,
            file_version=file_version,
            offset=offset,
            object_index=object_index,
        )


@dataclass(frozen=True, order=True, slots=True)
class SketchUpFormatVersion:
    """Parsed SketchUp product version from a legacy file envelope."""

    major: int
    minor: int = 0
    build: int = 0

    @classmethod
    def parse(cls, value: str) -> "SketchUpFormatVersion":
        """Parse a product version such as ``"{8.0.1}"``."""
        match = _VERSION_PATTERN.fullmatch(value.strip())
        if match is None:
            raise ValueError(f"Unsupported SketchUp version string: {value!r}")
        major, minor, build = match.groups(default="0")
        return cls(major=int(major), minor=int(minor), build=int(build))

    @property
    def is_pre_zip(self) -> bool:
        """Return whether this is a known MFC/CArchive-era SketchUp version."""
        return 3 <= self.major <= 20

    def __str__(self) -> str:
        """Return the normalized dotted version string."""
        return f"{self.major}.{self.minor}.{self.build}"


@dataclass(frozen=True, slots=True)
class ArchiveClassSchema:
    """One runtime-class schema declared by a CVersionMap."""

    class_name: str
    version: int


@dataclass(frozen=True, slots=True)
class ArchiveSchema:
    """Immutable per-file runtime-class schema lookup."""

    file_version: SketchUpFormatVersion
    entries: tuple[ArchiveClassSchema, ...]

    @classmethod
    def from_pairs(
        cls,
        file_version: SketchUpFormatVersion,
        entries: Iterable[tuple[str, int]],
    ) -> "ArchiveSchema":
        """Create a schema from ordered CVersionMap class/version pairs."""
        return cls(
            file_version=file_version,
            entries=tuple(
                ArchiveClassSchema(class_name=class_name, version=version) for class_name, version in entries
            ),
        )

    def version_for(self, class_name: str) -> int:
        """Return one runtime-class schema or raise a contextual missing error."""
        for entry in self.entries:
            if entry.class_name == class_name:
                return entry.version
        raise MissingLegacySchemaError(class_name, str(self.file_version))

    @property
    def versions(self) -> dict[str, int]:
        """Return runtime-class schemas keyed by class name."""
        return {entry.class_name: entry.version for entry in self.entries}
