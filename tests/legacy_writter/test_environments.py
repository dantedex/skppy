# SPDX-License-Identifier: MIT
"""Raw SU2017 compatibility-extension fixtures for environment and sun data."""

import math

import pytest

import skppy
from skppy.data_structure.model_metadata import SunData
from skppy.legacy_writter import build_legacy_2017_model


def test_environment_and_sun_match_raw_legacy_extension_payload() -> None:
    model = skppy.Model.new()
    environment = skppy.EnvironmentEntry(
        id=7,
        name="Studio",
        image_filename="studio.hdr",
        image_data=b"HDR",
    )
    model.environment_data = skppy.EnvironmentData(environment, [environment])
    model.sun_data = SunData(b"raw")
    expected = (
        '{"environment":{"entries":[{"description":"","id":7,"image_data":"SERS",'
        '"image_filename":"studio.hdr","name":"Studio","reflection_exposure":1.0,"rotation":0.0,'
        '"skydome_exposure":1.0,"thumbnail_data":null,"thumbnail_path":"","use_as_skydome":false,'
        '"use_for_reflections":false}],"selected":7},"sun":"cmF3"}'
    ).encode("utf-16le")

    assert expected in build_legacy_2017_model(model)


def _environment_model(entry: skppy.EnvironmentEntry) -> skppy.Model:
    model = skppy.Model.new()
    model.environment_data = skppy.EnvironmentData(entry, [entry])
    return model


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (skppy.EnvironmentEntry(id=0, name="Env", image_filename="env.hdr", image_data=b"x"), "IDs must be"),
        (skppy.EnvironmentEntry(id=1, name="", image_filename="env.hdr", image_data=b"x"), "path-safe"),
        (skppy.EnvironmentEntry(id=1, name="Env", image_filename="env.hdr"), "image data is required"),
        (
            skppy.EnvironmentEntry(
                id=1,
                name="Env",
                image_filename="env.hdr",
                image_data=b"x",
                thumbnail_path="../thumb.jpg",
            ),
            "archive-relative",
        ),
        (
            skppy.EnvironmentEntry(id=1, name="Env", image_filename="env.hdr", image_data=b"x", rotation=math.inf),
            "must be finite",
        ),
        (
            skppy.EnvironmentEntry(id=1, name="Env", image_filename="env.hdr", image_data=b"x", rotation=360),
            "rotation must be",
        ),
        (
            skppy.EnvironmentEntry(
                id=1,
                name="Env",
                image_filename="env.hdr",
                image_data=b"x",
                skydome_exposure=21,
            ),
            "exposure must be",
        ),
    ],
)
def test_rejects_invalid_environment_entries(entry: skppy.EnvironmentEntry, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_legacy_2017_model(_environment_model(entry))


def test_rejects_invalid_environment_collections() -> None:
    missing = skppy.Model.new()
    missing.environment_data = skppy.EnvironmentData()
    with pytest.raises(ValueError, match="requires a selected"):
        build_legacy_2017_model(missing)

    selected = skppy.EnvironmentEntry(id=1, name="Selected", image_filename="selected.hdr", image_data=b"x")
    other = skppy.EnvironmentEntry(id=2, name="Other", image_filename="other.hdr", image_data=b"x")
    absent = skppy.Model.new()
    absent.environment_data = skppy.EnvironmentData(selected, [other])
    with pytest.raises(ValueError, match="must be present"):
        build_legacy_2017_model(absent)

    duplicate_id = skppy.Model.new()
    duplicate_id.environment_data = skppy.EnvironmentData(selected, [selected, selected])
    with pytest.raises(ValueError, match="IDs must be"):
        build_legacy_2017_model(duplicate_id)

    same_name = skppy.EnvironmentEntry(id=2, name="Selected", image_filename="other.hdr", image_data=b"x")
    duplicate_name = skppy.Model.new()
    duplicate_name.environment_data = skppy.EnvironmentData(selected, [selected, same_name])
    with pytest.raises(ValueError, match="names must be unique"):
        build_legacy_2017_model(duplicate_name)
