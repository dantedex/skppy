# SPDX-License-Identifier: MIT
"""Enscape explicit grayscale masks and safe missing-image fallback."""

import zipfile

import pytest

import skppy


@pytest.mark.parametrize("embedded", [False, True])
@pytest.mark.parametrize("source", ["TEXTURE_PATH_ABSOLUTE", "SKETCHUP"])
def test_imports_explicit_opacity_mask_but_does_not_guess_host_mask_channels(
    tmp_path, caplog, embedded, source
) -> None:
    xml = f"""<materialDocument><material name="Masked">
      <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
        <SketchupMaterial Version="5"><Opacity>0.6</Opacity>
          <MaskTexture><Source>{source}</Source><Filepath>C:\\maps\\mask.png</Filepath>
            <Brightness>0.8</Brightness><IsInverted>true</IsInverted>
            <UseExplicitTransformation>true</UseExplicitTransformation><Width>0.0127</Width><Height>0.0254</Height>
          </MaskTexture>
        </SketchupMaterial>
      ]]></Attribute></AttributeDictionary>
    </material></materialDocument>"""
    path = tmp_path / "mask.skm"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.xml", xml)
        if embedded:
            archive.writestr("ref/mask.png", b"mask pixels")

    plain = skppy.load_material(path)
    material = skppy.load_material(path, import_vray_materials=True)

    assert plain.opacity_texture is None
    assert material.alpha == pytest.approx(0.6)
    if source == "SKETCHUP":
        assert material.opacity_texture is None
        assert "host-derived opacity mask" in caplog.text
    else:
        texture = material.opacity_texture
        assert texture.filename == "mask.png"
        assert texture.data == (b"mask pixels" if embedded else None)
        assert texture.brightness == pytest.approx(0.8)
        assert texture.inverted
        assert texture.uv_scale == pytest.approx((2, 1))
