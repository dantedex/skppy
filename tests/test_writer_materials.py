# SPDX-License-Identifier: MIT
"""Tests for modern material TLV and XML serialization."""

from __future__ import annotations

import io
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

import pytest

from skppy import Color, new_model
from skppy.data_structure.images import Texture
from skppy.data_structure.materials import Material
from skppy.writer.materials import (
    encode_material_record,
    encode_material_xml,
    encode_materials,
)
from skppy.writer.model_data import build_model_container

_NAMESPACE = "http://sketchup.google.com/schemas/sketchup/1.0/material"


def _one_pixel_png() -> bytes:
    """Return a valid one-pixel RGBA PNG using only standard-library codecs."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(bytes((0, 127, 127, 127, 255)))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    """Construct expected records without using writer encoding helpers."""
    return struct.pack("<HI", tag, len(payload)) + payload


def test_material_tlv_uses_mapped_identity_and_binary_fallbacks() -> None:
    """Keep identity and lookup fields in model.dat independent from XML."""
    material = Material(id=4, name="Red", color=Color(255, 0, 0))
    identity = _raw_record(0x05DC, _raw_record(0x05DE, b"\x12"))
    payload = b"".join(
        (
            identity,
            _raw_record(0x32CC, b"Red"),  # Material name.
            _raw_record(0x32CA, b"\x00"),  # Global-material context flag.
            _raw_record(0x32CB),  # Empty texture payload for an untextured material.
        )
    )
    expected = _raw_record(0x30D4, _raw_record(0x30D5, _raw_record(0x32C8, payload)))

    assert encode_materials([material], {4: 18}) == expected


def test_textured_global_material_keeps_global_context_flag() -> None:
    """Do not confuse XML texture state with the binary record context."""
    material = Material(
        id=4,
        name="Tile",
        color=Color(127, 127, 127),
        has_texture=True,
        texture=Texture(filename="tile.png", data=_one_pixel_png()),
    )

    encoded = encode_materials([material], {4: 18})

    assert _raw_record(0x32CA, b"\x00") in encoded
    assert _raw_record(0x32CA, b"\x01") not in encoded


def test_material_xml_preserves_color_opacity_and_pbr_factors() -> None:
    """Represent appearance fields through the namespaced material document."""
    material = Material(
        id=1,
        name="Paint",
        color=Color(12, 34, 56),
        alpha=0.25,
        metallic=0.75,
        roughness=0.125,
    )
    root = ET.fromstring(encode_material_xml(material))
    element = root.find(f"{{{_NAMESPACE}}}material")
    assert element is not None
    assert element.attrib["colorRed"] == "12"
    assert element.attrib["colorGreen"] == "34"
    assert element.attrib["colorBlue"] == "56"
    assert element.attrib["trans"] == "0.75"
    assert element.attrib["useTrans"] == "1"
    pbr = element.find(f"{{{_NAMESPACE}}}pbrMR")
    assert pbr is not None
    assert pbr.findtext(f"{{{_NAMESPACE}}}metallicFactor") == "0.75"
    assert pbr.findtext(f"{{{_NAMESPACE}}}roughnessFactor") == "0.125"


def test_modern_vray_option_appends_raw_material_xml_metadata() -> None:
    material = Material(id=1, name="Paint", color=Color(255, 0, 0), metallic=0.5, roughness=0.25)

    sketchup_xml = encode_material_xml(material)
    vray_xml = encode_material_xml(material, export_vray_materials=True)

    assert b"VRayInfo" not in sketchup_xml
    assert b'xmlns:n0="http://sketchup.google.com/schemas/1.0/types"' in vray_xml
    assert b'<n0:AttributeDictionary name="VRayInfo" count="4">' in vray_xml
    assert b'<n0:Attribute key="version" type="4">72002</n0:Attribute>' in vray_xml
    assert b'<n0:AttributeDictionary name="VRayPlugins" count="2">' in vray_xml
    assert b'"class":"BRDFVRayMtl"' in vray_xml
    assert b'"diffuse":"Color(1,0,0)"' in vray_xml
    assert b'"metalness":"0.5"' in vray_xml
    assert b'"reflect_glossiness":"0.25"' in vray_xml


def test_modern_container_threads_vray_option_to_material_entries() -> None:
    model = new_model()
    model.add_material("Paint", color=Color(20, 40, 60))

    raw = build_model_container(model, export_vray_materials=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        material_xml = archive.read("materials/Paint/material.xml")

    assert b'<n0:AttributeDictionary name="VRayInfo" count="4">' in material_xml


def test_modern_vray_texture_graph_matches_raw_plugin_references() -> None:
    material = Material(
        id=1,
        name="Tile",
        color=Color(127, 127, 127),
        has_texture=True,
        texture=Texture(filename="tile.png", data=_one_pixel_png()),
    )

    material_xml = encode_material_xml(material, export_vray_materials=True)

    assert b'"diffuse":"/Tile/VRay Mtl/Bitmap"' in material_xml
    assert b'"class":"TexBitmap"' in material_xml
    assert b'"bitmap":"/Tile/VRay Mtl/Bitmap/Bitmap"' in material_xml
    assert b'"class":"BitmapBuffer"' in material_xml
    assert b'"file":"tile.png"' in material_xml
    assert b'"class":"UVWGenChannel"' in material_xml
    assert b'"uvw_channel":"1"' in material_xml


def test_materialized_face_matches_raw_remapped_reference() -> None:
    """Keep face and material IDs coherent after global file-ID allocation."""
    model = new_model()
    material = model.add_material("Paint", color=Color(20, 40, 60), alpha=0.4, metallic=0.2, roughness=0.7)
    face = model.entities.add_face([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    face.front_material_id = material.id
    raw = build_model_container(model)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        model_data = archive.read("model.dat")
        material_xml = archive.read("materials/Paint/material.xml")

    assert _raw_record(0x32CC, b"Paint") in model_data
    assert _raw_record(0x07D1, b"\x12") in model_data
    assert b'colorRed="20"' in material_xml
    assert b'colorGreen="40"' in material_xml
    assert b'colorBlue="60"' in material_xml
    assert b'trans="0.59999999999999998"' in material_xml
    assert b"<mat:metallicFactor>0.20000000000000001</mat:metallicFactor>" in material_xml
    assert b"<mat:roughnessFactor>0.69999999999999996</mat:roughnessFactor>" in material_xml


def test_material_writer_rejects_lossy_or_unsafe_values() -> None:
    """Reject resource paths and texture data not covered by this milestone."""
    invalid_name = Material(id=1, name="bad/name", color=Color(0, 0, 0))
    with pytest.raises(ValueError, match="path-safe"):
        encode_material_xml(invalid_name)

    textured = Material(id=1, name="Texture", color=Color(0, 0, 0), has_texture=True)
    with pytest.raises(ValueError, match="must agree"):
        encode_material_xml(textured)


def test_embedded_texture_matches_raw_scale_and_image_entry() -> None:
    """Write texture metadata and bytes under the material resource folder."""
    model = new_model()
    material = model.add_material("Tile", color=Color(127, 127, 127))
    material.has_texture = True
    material.texture = Texture(filename="tile.png", x_scale=2.5, y_scale=4.0, data=_one_pixel_png())
    raw = build_model_container(model)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        material_xml = archive.read("materials/Tile/material.xml")
        image_data = archive.read("materials/Tile/tile.png")

    assert b'textureFilename="tile.png"' in material_xml
    assert b'xScale="2.5"' in material_xml
    assert b'yScale="4"' in material_xml
    assert image_data == _one_pixel_png()


def test_material_identity_maps_must_be_complete_and_unique() -> None:
    first = Material(id=1, name="First")
    second = Material(id=2, name="Second")
    cases = (
        ([Material(id=0, name="Bad")], {0: 18}, "IDs must be positive"),
        ([first, Material(id=1, name="Other")], {1: 18}, "IDs must be unique"),
        ([first], {}, "ID map does not cover"),
        ([first, second], {1: 18, 2: 18}, "Mapped material IDs"),
    )
    for materials, id_map, message in cases:
        with pytest.raises(ValueError, match=message):
            encode_materials(materials, id_map)

    with pytest.raises(ValueError, match="Serialized material ID must be positive"):
        encode_material_record(first, 0)


@pytest.mark.parametrize(
    ("material", "message"),
    [
        (Material(id=1, name="", color=Color(0, 0, 0)), "name must be non-empty"),
        (
            Material(id=1, name="Bad", color=Color(-1, 0, 0)),
            "color channels must be integers",
        ),
        (
            Material(id=1, name="Bad", color=Color(0, 0, 0), alpha=float("nan")),
            "factors must be finite",
        ),
        (
            Material(
                id=1,
                name="Bad",
                color=Color(0, 0, 0),
                has_texture=True,
                texture=Texture(filename="tile.png"),
            ),
            "image data is required",
        ),
        (
            Material(
                id=1,
                name="Bad",
                color=Color(0, 0, 0),
                has_texture=True,
                texture=Texture(filename="tile.png", data=b"raw"),
            ),
            "scales must be finite and non-zero",
        ),
        (
            Material(
                id=1,
                name="Bad",
                color=Color(0, 0, 0),
                has_texture=True,
                texture=Texture(filename=".", data=b"raw"),
            ),
            "safe basename",
        ),
    ],
)
def test_materials_reject_unrepresentable_values(material: Material, message: str) -> None:
    if message == "scales must be finite and non-zero":
        assert material.texture is not None
        material.texture.x_scale = 0.0
    with pytest.raises(ValueError, match=message):
        encode_material_xml(material)
