# SPDX-License-Identifier: MIT
"""Deterministic V-Ray material metadata writer tests."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from skppy import AttributeDictionary, AttributeDictionaryEntry, Color, Material, Texture
from skppy.writer.vray_materials import (
    _xml_entry_value,
    append_vray_xml,
    replace_vray_dictionaries,
    vray_material_dictionaries,
)

_TYPES_NAMESPACE = "http://sketchup.google.com/schemas/1.0/types"


def _values(dictionary: AttributeDictionary) -> dict[str, str | int]:
    return {entry.key: entry.string_value if entry.value_type == 3 else entry.int_value for entry in dictionary.entries}


def test_modern_vray_graph_matches_expected_plugin_json() -> None:
    material = Material(name="Metal Paint", color=Color(128, 64, 0), alpha=0.75, metallic=0.8, roughness=0.25)

    info, plugins = vray_material_dictionaries(material, target="modern")
    info_values = _values(info)
    plugin_values = _values(plugins)

    assert info_values == {
        "class": "MtlSingleBRDF",
        "main_plugin": "/Metal Paint",
        "type": "material",
        "version": 72002,
    }
    assert list(plugin_values) == ["/Metal Paint", "/Metal Paint/VRay Mtl"]
    assert plugin_values["/Metal Paint"] == (
        '{"name":"/Metal Paint","class":"MtlSingleBRDF","type":"material","version":23,'
        '"params":{"scene_name":"List(Metal Paint)","filter":"Color(1,1,1)",'
        '"brdf":"/Metal Paint/VRay Mtl","double_sided":"1","allow_negative_colors":"0",'
        '"channels":"List()"},"userData":{"materialID":"","swatch_type":"generic",'
        '"effected_by_mtl_override":"1","displacement":"","bind_texture_on":"1","bind_texture_mode":"4",'
        '"bind_opacity_on":"1","bump":"","bind_all_on":"0","bind_color_on":"1","viewport_texture":"",'
        '"renderStats":"","ui_tags":"List()"}}'
    )
    brdf = json.loads(str(plugin_values["/Metal Paint/VRay Mtl"]))
    assert brdf == {
        "name": "/Metal Paint/VRay Mtl",
        "class": "BRDFVRayMtl",
        "type": "BRDF",
        "version": 23,
        "params": {
            "diffuse": "Color(0.21586050011389926,0.051269458374043238,0)",
            "metalness": "0.80000000000000004",
            "option_use_roughness": "1",
            "reflect_glossiness": "0.25",
            "opacity": "0.75",
            "opacity_color": "AColor(0.75,0.75,0.75,0.75)",
            "opacity_mode": "2",
            "option_double_sided": "1",
        },
        "userData": {
            "diffuse_color": "Color(0.21586050011389926,0.051269458374043238,0)",
            "diffuse_tex": "",
            "diffuse_tex_mult": "1",
            "metalness_float": "0.80000000000000004",
            "reflect_glossiness_float": "0.25",
            "opacity_float": "0.75",
            "diffuse_tex_on": "0",
            "metalness_tex_on": "0",
            "reflect_glossiness_tex_on": "0",
            "opacity_tex_on": "0",
            "linear_workflow": "1",
            "texture_multiplier_mode": "1",
        },
    }


def test_legacy_vray_graph_uses_observed_2017_versions_and_scene_name() -> None:
    material = Material(name="Paint", color=Color(255, 255, 255))

    info, plugins = vray_material_dictionaries(material, target="sketchup_2017")
    wrapper = json.loads(str(_values(plugins)["/Paint"]))
    brdf = json.loads(str(_values(plugins)["/Paint/VRay Mtl"]))

    assert _values(info)["version"] == 42003
    assert wrapper["version"] == 16
    assert wrapper["params"]["scene_name"] == "ListString(Paint)"
    assert "channels" not in wrapper["params"]
    assert "ui_tags" not in wrapper["userData"]
    assert brdf["version"] == 16


@pytest.mark.parametrize(
    ("target", "version", "color_space"),
    [("modern", 23, ("rgb_color_space", "raw")), ("sketchup_2017", 16, ("color_space", "2"))],
)
def test_textured_vray_graph_connects_embedded_image_to_uv_channel(target, version, color_space) -> None:
    material = Material(
        name="Tile",
        color=Color(128, 128, 128),
        has_texture=True,
        texture=Texture(filename=r"C:\textures\tile.png", data=b"image"),
    )

    _, dictionary = vray_material_dictionaries(material, target=target)
    plugins = {key: json.loads(str(value)) for key, value in _values(dictionary).items()}
    brdf = plugins["/Tile/VRay Mtl"]
    texture = plugins["/Tile/VRay Mtl/Bitmap"]
    bitmap = plugins["/Tile/VRay Mtl/Bitmap/Bitmap"]
    uvw = plugins["/Tile/VRay Mtl/Bitmap/UVW"]

    assert [plugin["class"] for plugin in plugins.values()] == [
        "MtlSingleBRDF",
        "BRDFVRayMtl",
        "TexBitmap",
        "BitmapBuffer",
        "UVWGenChannel",
    ]
    assert brdf["params"]["diffuse"] == "/Tile/VRay Mtl/Bitmap"
    assert brdf["userData"]["diffuse_tex_on"] == "1"
    assert texture["version"] == bitmap["version"] == uvw["version"] == version
    assert texture["params"]["bitmap"] == "/Tile/VRay Mtl/Bitmap/Bitmap"
    assert texture["params"]["uvwgen"] == "/Tile/VRay Mtl/Bitmap/UVW"
    assert bitmap["params"]["file"] == "tile.png"
    assert bitmap["params"][color_space[0]] == color_space[1]
    assert uvw["params"]["uvw_channel"] == "1"


def test_replaces_only_vray_owned_dictionaries() -> None:
    retained = AttributeDictionary(
        name="UserData",
        entries=[AttributeDictionaryEntry(key="key", value_type=3, string_value="value")],
    )
    stale = AttributeDictionary(name="VRayInfo")

    dictionaries = replace_vray_dictionaries([stale, retained], Material(name="Paint"), target="modern")

    assert [dictionary.name for dictionary in dictionaries] == ["UserData", "VRayInfo", "VRayPlugins"]
    assert dictionaries[0] is retained


def test_appends_typed_vray_dictionaries_to_modern_material_xml() -> None:
    material_element = ET.Element("material")

    append_vray_xml(material_element, Material(name="Paint", color=Color(255, 0, 0)))
    reparsed = ET.fromstring(ET.tostring(material_element))
    container = reparsed.find(f"{{{_TYPES_NAMESPACE}}}AttributeDictionaries")

    assert container is not None
    assert container.attrib == {"count": "2"}
    dictionaries = list(container)
    assert [(item.attrib["name"], item.attrib["count"]) for item in dictionaries] == [
        ("VRayInfo", "4"),
        ("VRayPlugins", "2"),
    ]
    version = next(entry for entry in dictionaries[0] if entry.attrib["key"] == "version")
    assert (version.attrib["type"], version.text) == ("4", "72002")
    assert all(entry.attrib["type"] == "10" for entry in dictionaries[1])


def test_rejects_unknown_vray_target() -> None:
    with pytest.raises(ValueError, match="Unsupported V-Ray material target"):
        vray_material_dictionaries(Material(name="Paint"), target="future")  # type: ignore[arg-type]


def test_rejects_unsupported_vray_xml_value_type() -> None:
    invalid = AttributeDictionary(name="VRayInfo", entries=[AttributeDictionaryEntry(key="flag", value_type=2)])

    with pytest.raises(ValueError, match="Unsupported V-Ray XML attribute value type"):
        _xml_entry_value(invalid.entries[0])
