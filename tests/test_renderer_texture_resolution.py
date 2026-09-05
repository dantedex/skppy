# SPDX-License-Identifier: MIT
"""Resolve renderer images using independently authored material packages."""

import io
import zipfile

import pytest

from skppy.parser.material_parser import _parse_material_xml


@pytest.mark.parametrize(
    ("filename", "entries", "expected"),
    [
        ("rough.png", {"materials/A/rough.png": b"A", "materials/B/rough.png": b"B"}, b"B"),
        ("materials/A/rough.png", {"materials/A/rough.png": b"A", "materials/B/rough.png": b"B"}, b"A"),
        ("C:\\maps\\rough.png", {"materials/B/ROUGH.PNG": b"B"}, b"B"),
        ("rough.png", {"other/rough.png": b"unique"}, b"unique"),
        ("rough.png", {"A/rough.png": b"A", "C/rough.png": b"C"}, None),
        ("rough.png", {"rough.png/": b""}, None),
        ("/maps/rough.png", {}, None),
        ("../rough.png", {}, None),
    ],
)
def test_resolves_renderer_map_without_cross_material_collisions(filename, entries, expected, caplog) -> None:
    xml = f"""<materialDocument><material name="B">
      <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
        <SketchupMaterial><RoughnessTexture><Filepath>{filename}</Filepath></RoughnessTexture></SketchupMaterial>
      ]]></Attribute></AttributeDictionary>
    </material></materialDocument>""".encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for path, data in entries.items():
            archive.writestr(path, data)
    with zipfile.ZipFile(stream) as archive:
        material = _parse_material_xml(xml, "B", archive, {}, import_vray_materials=True)

    assert material.roughness_texture is not None
    assert material.roughness_texture.data == expected
    if "C/rough.png" in entries:
        assert "Ambiguous renderer texture" in caplog.text
