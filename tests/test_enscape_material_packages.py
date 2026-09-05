# SPDX-License-Identifier: MIT
"""Enscape appearance and renderer precedence in independent SKM packages."""

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
