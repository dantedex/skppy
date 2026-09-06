# SPDX-License-Identifier: MIT
"""Explicit Enscape map dimensions preserve the SketchUp mesh UV basis."""

import zipfile

import pytest

import skppy


@pytest.mark.parametrize("source", ["SKETCHUP", "TEXTURE_PATH_ABSOLUTE"])
@pytest.mark.parametrize(
    ("explicit", "width", "height", "rotation", "expected"),
    [
        ("true", "0.254", "0.1016", "0", (2, 5)),
        ("true", "0.254", "0.1016", "45", (2, 5)),
        ("false", "0.254", "0.1016", "0", (1, 1)),
        ("true", "nan", "0.1", "0", (1, 1)),
        ("true", "-1", "0.1", "0", (1, 1)),
        ("true", "0.1", "0", "0", (1, 1)),
    ],
)
def test_imports_explicit_sizes_for_each_map_without_rescaling_mesh_uvs(
    tmp_path, caplog, source, explicit, width, height, rotation, expected
) -> None:
    xml = f"""<materialDocument><material name="Sized" hasTexture="1">
      <texture textureFilename="base.png" xScale="20" yScale="20"><images><image path="base.png"/></images></texture>
      <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
        <SketchupMaterial><DiffuseTexture><Source>{source}</Source><Filepath>base.png</Filepath>
          <UseExplicitTransformation>{explicit}</UseExplicitTransformation><Width>{width}</Width><Height>{height}</Height>
          <Rotation>{rotation}</Rotation></DiffuseTexture>
          <RoughnessTexture><Source>SKETCHUP</Source><UseExplicitTransformation>true</UseExplicitTransformation>
            <Width>0.508</Width><Height>0.254</Height></RoughnessTexture>
        </SketchupMaterial>
      ]]></Attribute></AttributeDictionary>
    </material></materialDocument>"""
    path = tmp_path / "size.skm"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.xml", xml)
        archive.writestr("ref/base.png", b"pixels")

    material = skppy.load_material(path, import_vray_materials=True)

    assert material.texture.uv_scale == pytest.approx(expected)
    assert material.roughness_texture.uv_scale == pytest.approx((1, 2))
    assert (material.texture.x_scale, material.texture.y_scale) == (20, 20)
    assert (material.roughness_texture.x_scale, material.roughness_texture.y_scale) == (20, 20)
    if rotation != "0":
        assert "rotation is not yet supported" in caplog.text
    if explicit == "true" and expected == (1, 1):
        assert "Invalid Enscape texture size" in caplog.text


@pytest.mark.parametrize("scale", [(1,), (0, 1), (float("inf"), 1), (1, float("nan"))])
def test_texture_rejects_invalid_uv_multipliers(scale) -> None:
    with pytest.raises(ValueError, match="uv_scale"):
        skppy.Texture(uv_scale=scale)


@pytest.mark.parametrize(("x_scale", "y_scale"), [("1e308", "20"), ("20", "1e308")])
def test_overflowing_explicit_size_retains_native_mapping(tmp_path, caplog, x_scale, y_scale) -> None:
    xml = f'''<materialDocument><material name="Huge" hasTexture="1">
      <texture textureFilename="base.png" xScale="{x_scale}" yScale="{y_scale}">
        <images><image path="base.png"/></images>
      </texture>
      <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
        <SketchupMaterial Version="5"><Roughness>0.25</Roughness>
          <DiffuseTexture><Source>SKETCHUP</Source><UseExplicitTransformation>true</UseExplicitTransformation>
            <Width>1e-11</Width><Height>1e-11</Height>
          </DiffuseTexture>
        </SketchupMaterial>
      ]]></Attribute></AttributeDictionary>
    </material></materialDocument>'''
    path = tmp_path / "overflow.skm"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.xml", xml)
        archive.writestr("ref/base.png", b"pixels")

    material = skppy.load_material(path, import_vray_materials=True)

    assert material.texture.uv_scale == (1, 1)
    assert (material.texture.x_scale, material.texture.y_scale) == (float(x_scale), float(y_scale))
    assert material.roughness == 0.25
    assert "Enscape texture size produces invalid UV multipliers" in caplog.text
