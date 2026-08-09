# SPDX-License-Identifier: MIT
"""Raw SU2017 compatibility-extension fixtures for layer folders."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def test_layer_folder_matches_raw_legacy_extension_payload() -> None:
    model = skppy.Model.new()
    layer = model.add_layer("Walls")
    model.layer_folders = [
        skppy.LayerFolder(
            name="Folder",
            visible=False,
            child_layer_ids=[layer.id],
        ),
    ]
    expected = ('{"layer_folders":[{"children":[],"layers":["Walls"],"name":"Folder","visible":false}]}').encode(
        "utf-16le"
    )

    assert expected in build_legacy_2017_model(model)


def test_rejects_invalid_layer_folder_trees() -> None:
    missing = skppy.Model.new()
    missing.layer_folders = [skppy.LayerFolder(name="Missing", child_layer_ids=[99])]
    with pytest.raises(ValueError, match="unknown layer 99"):
        build_legacy_2017_model(missing)

    cyclic = skppy.Model.new()
    folder = skppy.LayerFolder(name="Cycle")
    folder.child_folders.append(folder)
    cyclic.layer_folders = [folder]
    with pytest.raises(ValueError, match="contains a cycle"):
        build_legacy_2017_model(cyclic)
