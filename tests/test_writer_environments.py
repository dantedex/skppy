# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern environment serialization."""

from __future__ import annotations

import struct

import pytest

from skppy.data_structure.model_metadata import EnvironmentData, EnvironmentEntry
from skppy.writer.environments import (
    encode_environment_data,
    environment_entries,
)


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _environment() -> tuple[EnvironmentData, EnvironmentEntry]:
    entry = EnvironmentEntry(
        id=1,
        name="StudioEnvironment",
        image_filename="studio.exr",
        image_data=b"raw exr bytes",
        thumbnail_data=b"raw thumbnail bytes",
        use_as_skydome=True,
        use_for_reflections=True,
    )
    return EnvironmentData(selected=entry, entries=[entry]), entry


def test_environment_data_matches_raw_expected_bytes() -> None:
    environment, _ = _environment()
    entry = b"".join(
        (
            _raw_record(0x05DC, _raw_record(0x05DE, b"\x12")),
            _raw_record(0x7B0D, b"StudioEnvironment"),
            _raw_record(
                0x7B0E,
                _raw_record(
                    0x2134,
                    b"environments/StudioEnvironment/thumbnail.jpg",
                ),
            ),
        )
    )
    expected = _raw_record(
        0x7918,
        _raw_record(0x7919, _raw_record(0x7B0C, entry)),
    )
    assert encode_environment_data(environment, {1: 18}) == expected


def test_environment_resources_have_canonical_paths_and_xml() -> None:
    environment, _ = _environment()
    entries = environment_entries(environment)

    assert entries["environments/StudioEnvironment/studio.exr"] == b"raw exr bytes"
    assert entries["environments/StudioEnvironment/thumbnail.jpg"] == (b"raw thumbnail bytes")
    xml = entries["environments/StudioEnvironment/environment.xml"]
    assert b'name="StudioEnvironment"' in xml
    assert b'ibl_enabled="1"' in xml
    assert b'skybox_enabled="1"' in xml
    assert b'ibl_filename="studio.exr"' in xml
    assert b'path="./studio.exr"' in xml


def test_multiple_environment_entries_match_repeated_raw_records() -> None:
    environment, first = _environment()
    second = EnvironmentEntry(
        id=2,
        name="ReflectionEnvironment",
        image_filename="reflection.exr",
        image_data=b"second exr",
    )
    environment.entries.append(second)

    encoded = encode_environment_data(environment, {1: 18, 2: 19})

    assert encoded.count(_raw_record(0x05DE, b"\x12")) == 1
    assert encoded.count(_raw_record(0x05DE, b"\x13")) == 1
    assert _raw_record(0x7B0D, first.name.encode()) in encoded
    assert _raw_record(0x7B0D, second.name.encode()) in encoded
    resources = environment_entries(environment)
    assert resources["environments/ReflectionEnvironment/reflection.exr"] == (b"second exr")


def test_environment_selection_and_identity_are_consistent() -> None:
    with pytest.raises(ValueError, match="requires a selected"):
        encode_environment_data(EnvironmentData(), {})

    _, selected = _environment()
    other = EnvironmentEntry(id=2, name="Other", image_filename="other.exr", image_data=b"raw")
    with pytest.raises(ValueError, match="must be present"):
        encode_environment_data(EnvironmentData(selected=selected, entries=[other]), {})

    duplicate_id = EnvironmentEntry(
        id=selected.id,
        name="Different",
        image_filename="other.exr",
        image_data=b"raw",
    )
    with pytest.raises(ValueError, match="IDs must be unique"):
        encode_environment_data(
            EnvironmentData(selected=selected, entries=[selected, duplicate_id]),
            {1: 18},
        )

    duplicate_name = EnvironmentEntry(
        id=2,
        name=selected.name,
        image_filename="other.exr",
        image_data=b"raw",
    )
    with pytest.raises(ValueError, match="names must be unique"):
        encode_environment_data(
            EnvironmentData(selected=selected, entries=[selected, duplicate_name]),
            {1: 18, 2: 19},
        )


@pytest.mark.parametrize(
    ("changes", "id_map", "message"),
    [
        ({"id": 0}, {0: 18}, "IDs must be positive and mapped"),
        ({}, {}, "IDs must be positive and mapped"),
        ({"name": "bad/name"}, {1: 18}, "name must be non-empty and path-safe"),
        (
            {"image_filename": "../bad.exr"},
            {1: 18},
            "filename must be non-empty and path-safe",
        ),
        ({"image_data": None}, {1: 18}, "image data is required"),
        ({"thumbnail_path": "/absolute.jpg"}, {1: 18}, "archive-relative"),
        ({"rotation": float("nan")}, {1: 18}, "numeric values must be finite"),
        ({"rotation": 360.0}, {1: 18}, "rotation must be in"),
        ({"skydome_exposure": 21.0}, {1: 18}, "skydome exposure must be in"),
        (
            {"reflection_exposure": -1.0},
            {1: 18},
            "reflection exposure must be in",
        ),
    ],
)
def test_environment_rejects_unrepresentable_values(changes: dict, id_map: dict[int, int], message: str) -> None:
    environment, entry = _environment()
    for field, value in changes.items():
        setattr(entry, field, value)
    with pytest.raises(ValueError, match=message):
        encode_environment_data(environment, id_map)
