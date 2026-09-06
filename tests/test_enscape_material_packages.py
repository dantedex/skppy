# SPDX-License-Identifier: MIT
"""Enscape appearance and renderer precedence in independent SKM packages."""

import io
import struct
import zipfile

import pytest

import skppy


@pytest.mark.parametrize("metadata", ["<SketchupMaterial><Roughness>0.8</Roughness></SketchupMaterial>", "<broken"])
def test_enscape_precedes_vray_only_when_metadata_is_valid(tmp_path, metadata) -> None:
    xml = f"""<materialDocument><material name="Mixed" colorRed="10" colorGreen="20" colorBlue="30">
      <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
        {metadata}
      ]]></Attribute></AttributeDictionary>
      <AttributeDictionary name="VRayPlugins"><Attribute key="/M"><![CDATA[
        {{"name":"/M","class":"BRDFVRayMtl","params":{{"metalness":"1",
          "option_use_roughness":"1","reflect_glossiness":"0.2","diffuse":"Color(1,0,0)"}}}}
      ]]></Attribute></AttributeDictionary>
    </material></materialDocument>"""
    path = tmp_path / "mixed.skm"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.xml", xml)

    material = skppy.load_material(path, import_vray_materials=True)

    if metadata == "<broken":
        assert material.roughness == pytest.approx(0.2)
        assert material.metallic == 1
        assert material.color == skppy.Color(255, 0, 0)
    else:
        assert material.roughness == pytest.approx(0.8)
        assert material.metallic == 0
        assert material.color == skppy.Color(10, 20, 30)


@pytest.mark.parametrize(
    ("filename", "entries", "expected", "brightness"),
    [
        ("new.png", {"ref/new.png": b"renderer pixels"}, b"renderer pixels", 0.7),
        ("C:\\maps\\ORIGINAL.PNG", {}, b"base pixels", 0.7),
        ("missing.png", {}, b"base pixels", 1.0),
    ],
)
def test_enscape_diffuse_uses_embedded_images_and_keeps_missing_map_fallback(
    tmp_path, filename, entries, expected, brightness
) -> None:
    xml = f"""<materialDocument><material name="Diffuse" hasTexture="1">
      <texture textureFilename="original.png" xScale="12" yScale="24">
        <images><image path="texture_1.png"/></images>
      </texture>
      <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
        <SketchupMaterial Version="4"><DiffuseTexture><Filepath>{filename}</Filepath>
          <Brightness>0.7</Brightness><IsInverted>true</IsInverted>
        </DiffuseTexture></SketchupMaterial>
      ]]></Attribute></AttributeDictionary>
    </material></materialDocument>"""
    path = tmp_path / "diffuse.skm"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.xml", xml)
        archive.writestr("ref/texture_1.png", b"base pixels")
        for name, data in entries.items():
            archive.writestr(name, data)

    material = skppy.load_material(path, import_vray_materials=True)

    assert material.has_texture
    assert material.texture.data == expected
    assert material.texture.brightness == pytest.approx(brightness)
    assert material.texture.inverted == (brightness != 1.0)
    assert (material.texture.x_scale, material.texture.y_scale) == (12, 24)


def test_modern_skp_public_loader_applies_enscape_material_xml(tmp_path) -> None:
    def record(tag: int, payload: bytes) -> bytes:
        return struct.pack("<HI", tag, len(payload)) + payload

    material = record(0x32C8, record(0x32CC, b"PBR"))
    materials = record(0x01F7, record(0x30D4, record(0x30D5, material)))
    model = record(0x01F4, record(0x01F5, bytes(100)) + materials)
    xml = """<materialDocument><material name="PBR" colorRed="10" colorGreen="20" colorBlue="30">
      <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
        <SketchupMaterial Version="4"><DiffuseColor>#102030</DiffuseColor><Opacity>0.6</Opacity>
          <Roughness>0.3</Roughness><BumpMapType>NORMAL</BumpMapType><NormalMapIntensity>0.7</NormalMapIntensity>
          <BumpTexture><Filepath>normal.png</Filepath></BumpTexture>
        </SketchupMaterial>
      ]]></Attribute></AttributeDictionary>
    </material></materialDocument>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("model.dat", model)
        archive.writestr("materials/PBR/material.xml", xml)
        archive.writestr("materials/PBR/normal.png", b"normal pixels")
    path = tmp_path / "modern.skp"
    path.write_bytes("SketchUp Model {26.0.0}\n".encode("utf-16le") + buffer.getvalue())

    plain = skppy.load(path).materials[0]
    material = skppy.load(path, import_vray_materials=True).materials[0]

    assert plain.color == skppy.Color(10, 20, 30)
    assert plain.normal_texture is None
    assert material.color == skppy.Color(16, 32, 48)
    assert (material.alpha, material.roughness, material.normal_scale) == pytest.approx((0.6, 0.3, 0.7))
    assert material.normal_texture.data == b"normal pixels"


@pytest.mark.parametrize("opacity", [0.0, 0.2, 1.0])
@pytest.mark.parametrize("material_type", ["GENERIC", "GLASS"])
def test_glass_transmits_light_without_removing_surface_coverage(tmp_path, opacity, material_type) -> None:
    xml = f"""<materialDocument><material name="Glass" useTrans="1" trans="0.8">
      <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
        <SketchupMaterial Version="5"><Type>GENERIC</Type><TypeV5>{material_type}</TypeV5>
          <Opacity>{opacity}</Opacity><IndexOfRefraction>2.25606796116505</IndexOfRefraction><Roughness>0.238</Roughness>
        </SketchupMaterial>
      ]]></Attribute></AttributeDictionary>
    </material></materialDocument>"""
    path = tmp_path / "glass.skm"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.xml", xml)

    material = skppy.load_material(path, import_vray_materials=True)
    plain = skppy.load_material(path)

    assert plain.alpha == pytest.approx(0.2)
    assert plain.transmission == 0
    assert material.alpha == pytest.approx(1 if material_type == "GLASS" else opacity)
    assert material.transmission == pytest.approx(1 - opacity if material_type == "GLASS" else 0)
    assert material.ior == pytest.approx(2.25606796116505)
    assert material.roughness == pytest.approx(0.238)
