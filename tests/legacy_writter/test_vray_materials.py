# SPDX-License-Identifier: MIT
"""Raw SketchUp 2017 V-Ray material metadata writer fixtures."""

from __future__ import annotations

import struct

import skppy
from skppy.legacy_writter import build_legacy_2017_model


def _legacy_string(value: str) -> bytes:
    encoded = value.encode("utf-16le")
    length = len(value)
    prefix = bytes((length,)) if length < 0xFF else b"\xff" + struct.pack("<H", length)
    return b"\xff\xfe\xff" + prefix + encoded


def test_legacy_vray_option_writes_raw_material_dictionary_values() -> None:
    model = skppy.Model.new()
    model.add_material("Paint", color=skppy.Color(255, 0, 0), metallic=0.5, roughness=0.25)
    wrapper_json = (
        '{"name":"/Paint","class":"MtlSingleBRDF","type":"material","version":16,'
        '"params":{"scene_name":"ListString(Paint)","filter":"Color(1,1,1)",'
        '"brdf":"/Paint/VRay Mtl","double_sided":"1","allow_negative_colors":"0"},'
        '"userData":{"materialID":"","swatch_type":"generic","effected_by_mtl_override":"1",'
        '"displacement":"","bind_texture_on":"1","bind_texture_mode":"4","bind_opacity_on":"1",'
        '"bump":"","bind_all_on":"0","bind_color_on":"1","viewport_texture":"","renderStats":""}}'
    )
    expected_version = _legacy_string("version") + bytes((4,)) + struct.pack("<I", 42003)
    expected_plugin = _legacy_string("/Paint") + bytes((10,)) + _legacy_string(wrapper_json)

    sketchup_bytes = build_legacy_2017_model(model)
    vray_bytes = build_legacy_2017_model(model, export_vray_materials=True)

    assert _legacy_string("VRayInfo") not in sketchup_bytes
    assert _legacy_string("VRayInfo") in vray_bytes
    assert expected_version in vray_bytes
    assert expected_plugin in vray_bytes
    assert '"diffuse":"Color(1,0,0)"'.encode("utf-16le") in vray_bytes
    assert '"metalness":"0.5"'.encode("utf-16le") in vray_bytes
    assert '"reflect_glossiness":"0.25"'.encode("utf-16le") in vray_bytes


def test_legacy_vray_option_replaces_stale_vray_dictionaries_without_mutating_model() -> None:
    model = skppy.Model.new()
    material = model.add_material("Paint")
    stale_info = skppy.AttributeDictionary(
        name="VRayInfo",
        entries=[skppy.AttributeDictionaryEntry(key="stale", value_type=3, string_value="old graph")],
    )
    retained = skppy.AttributeDictionary(
        name="UserData",
        entries=[skppy.AttributeDictionaryEntry(key="owner", value_type=3, string_value="Blender")],
    )
    model.attribute_dictionaries_by_object_id[material.id] = [stale_info, retained]

    encoded = build_legacy_2017_model(model, export_vray_materials=True)

    assert "old graph".encode("utf-16le") not in encoded
    assert _legacy_string("UserData") in encoded
    assert model.attribute_dictionaries_by_object_id[material.id] == [stale_info, retained]


def test_legacy_vray_texture_graph_matches_raw_plugin_values() -> None:
    model = skppy.Model.new()
    material = model.add_material("Tile")
    material.has_texture = True
    material.texture = skppy.Texture(filename="tile.png", data=b"image")

    encoded = build_legacy_2017_model(model, export_vray_materials=True)

    for expected in (
        '"diffuse":"/Tile/VRay Mtl/Bitmap"',
        '"class":"TexBitmap"',
        '"bitmap":"/Tile/VRay Mtl/Bitmap/Bitmap"',
        '"class":"BitmapBuffer"',
        '"file":"tile.png"',
        '"class":"UVWGenChannel"',
        '"uvw_channel":"1"',
    ):
        assert expected.encode("utf-16le") in encoded
