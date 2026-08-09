# SPDX-License-Identifier: MIT
"""Modern environment TLV, XML, and resource serialization."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from math import isfinite
from pathlib import PurePosixPath

from ..data_structure.model_metadata import EnvironmentData, EnvironmentEntry
from ..parser.tlv import TlvTag
from .tlv import encode_compact_int, encode_record

_ENVIRONMENT_NAMESPACE = "http://sketchup.com/schemas/sketchup/1.0/environment"


def encode_environment_data(environment: EnvironmentData, id_map: Mapping[int, int]) -> bytes:
    """Encode the payload of the modern root environment block."""
    entries = _environment_entries(environment)
    encoded_entries = b"".join(_encode_environment_entry(entry, id_map) for entry in entries)
    return encode_record(
        TlvTag.ENVIRONMENT_DATA_RECORD,
        encode_record(TlvTag.ENVIRONMENT_SELECTED_RECORD, encoded_entries),
    )


def _encode_environment_entry(entry: EnvironmentEntry, id_map: Mapping[int, int]) -> bytes:
    _validate_entry(entry, id_map)
    identity = encode_record(
        TlvTag.ID_WRAPPER,
        encode_record(TlvTag.ID_VALUE, encode_compact_int(id_map[entry.id])),
    )
    thumbnail = encode_record(
        TlvTag.ENVIRONMENT_THUMBNAIL_REF,
        encode_record(
            TlvTag.ENVIRONMENT_THUMBNAIL_PATH,
            _thumbnail_path(entry).encode("utf-8"),
        ),
    )
    return encode_record(
        TlvTag.ENVIRONMENT_ENTRY,
        identity + encode_record(TlvTag.ENVIRONMENT_NAME, entry.name.encode("utf-8")) + thumbnail,
    )


def environment_entries(environment: EnvironmentData | None) -> dict[str, bytes]:
    """Return the ZIP resources for a supported environment."""
    if environment is None:
        return {}
    archive_entries: dict[str, bytes] = {}
    for entry in _environment_entries(environment):
        _validate_entry(entry, {entry.id: 1})
        assert entry.image_data is not None
        root = f"environments/{entry.name}"
        archive_entries[f"{root}/{entry.image_filename}"] = entry.image_data
        archive_entries[f"{root}/environment.xml"] = encode_environment_xml(entry)
        if entry.thumbnail_data is not None:
            archive_entries[_thumbnail_path(entry)] = entry.thumbnail_data
    return archive_entries


def encode_environment_xml(entry: EnvironmentEntry) -> bytes:
    """Encode the canonical environment resource document."""
    _validate_entry(entry, {entry.id: 1})
    document = ET.Element(
        "environmentDocument",
        {"xmlns": _ENVIRONMENT_NAMESPACE, "xmlns:env": _ENVIRONMENT_NAMESPACE},
    )
    environment = ET.SubElement(
        document,
        "env:environment",
        {
            "name": entry.name,
            "description": entry.description,
            "ibl_enabled": "1" if entry.use_for_reflections else "0",
            "rotation_angle": _format_number(entry.rotation),
            "skybox_enabled": "1" if entry.use_as_skydome else "0",
            "skybox_gain": _format_number(entry.skydome_exposure),
            "reflection_gain": _format_number(entry.reflection_exposure),
            "shadow_light_enabled": "0",
            "shadow_light_positionX": "0",
            "shadow_light_positionY": "0",
            "ibl_filename": entry.image_filename,
        },
    )
    ET.SubElement(
        environment,
        "ibl_image",
        {
            "id": "1",
            "path": f"./{entry.image_filename}",
            "file_name": entry.image_filename,
        },
    )
    ET.indent(document, space="  ")
    encoded: bytes = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    return encoded


def _environment_entries(environment: EnvironmentData) -> list[EnvironmentEntry]:
    if environment.selected is None:
        raise ValueError("Writing environment data requires a selected environment")
    entries = environment.entries or [environment.selected]
    if environment.selected not in entries:
        raise ValueError("Selected environment must be present in entries")
    ids = [entry.id for entry in entries]
    names = [entry.name for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("Environment IDs must be unique")
    if len(names) != len(set(names)):
        raise ValueError("Environment names must be unique")
    return list(entries)


def _validate_entry(entry: EnvironmentEntry, id_map: Mapping[int, int]) -> None:
    if entry.id <= 0 or entry.id not in id_map or id_map[entry.id] <= 0:
        raise ValueError("Environment IDs must be positive and mapped")
    if not entry.name or not _path_safe_name(entry.name):
        raise ValueError("Environment name must be non-empty and path-safe")
    if not entry.image_filename or not _path_safe_name(entry.image_filename):
        raise ValueError("Environment image filename must be non-empty and path-safe")
    if entry.image_data is None:
        raise ValueError("Environment image data is required for writing")
    if entry.thumbnail_path:
        path = PurePosixPath(entry.thumbnail_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Environment thumbnail path must be archive-relative")
    _validate_numeric_values(entry)


def _validate_numeric_values(entry: EnvironmentEntry) -> None:
    values = (entry.rotation, entry.skydome_exposure, entry.reflection_exposure)
    if any(not isfinite(value) for value in values):
        raise ValueError("Environment numeric values must be finite")
    if not 0.0 <= entry.rotation < 360.0:
        raise ValueError("Environment rotation must be in [0, 360)")
    if not 0.0 <= entry.skydome_exposure <= 20.0:
        raise ValueError("Environment skydome exposure must be in [0, 20]")
    if not 0.0 <= entry.reflection_exposure <= 20.0:
        raise ValueError("Environment reflection exposure must be in [0, 20]")


def _thumbnail_path(entry: EnvironmentEntry) -> str:
    return entry.thumbnail_path or f"environments/{entry.name}/thumbnail.jpg"


def _path_safe_name(value: str) -> bool:
    return value not in {".", ".."} and not any(char in value for char in "/\\")


def _format_number(value: float) -> str:
    return format(value, ".15g")
