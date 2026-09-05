# SPDX-License-Identifier: MIT
"""Load independently encoded legacy material dictionaries through the public API."""

import io
import struct
import zipfile

import pytest

import skppy
from ._fixtures import _legacy_file_bytes, _legacy_string, _material_preview_bytes, _new_class_tag
from ._fixtures import _texture_preview_payload_bytes


def _legacy_material(metadata: str, *, textured: bool = True, vray: bool = False) -> bytes:
    dictionary = b"".join(
        [
            _new_class_tag("CAttributeContainer", schema=0),
            b"\x00\x00",
            _new_class_tag("CAttributeNamed", schema=1),
            b"\x00\x00",
            struct.pack("<I", 0),
            _legacy_string("Enscape.Material"),
            _legacy_string("MaterialData"),
            b"\x0a",
            _legacy_string(metadata),
            _legacy_string(""),
            struct.pack("<I", 0),
            b"\x00\x00",
        ]
    )
    if vray:
        plugin = '{"name":"/M","class":"BRDFVRayMtl","params":{"metalness":"1"}}'
        dictionary = dictionary[:-2] + b"".join(
            [
                _new_class_tag("CAttributeNamed", schema=1),
                b"\x00\x00",
                struct.pack("<I", 0),
                _legacy_string("VRayPlugins"),
                _legacy_string("/M"),
                b"\x0a",
                _legacy_string(plugin),
                _legacy_string(""),
                struct.pack("<I", 0),
                b"\x00\x00",
            ]
        )
    material = _material_preview_bytes(
        name="Enscape", texture_payload=_texture_preview_payload_bytes() if textured else None
    )
    return _legacy_file_bytes(
        saved_path="enscape.skp",
        root_entity_count=1,
        root_entity_payload=_new_class_tag("CMaterial", schema=12) + dictionary + material[2:],
    )


@pytest.mark.parametrize("appended_zip", [False, True])
def test_legacy_enscape_import_preserves_opt_in_and_embedded_map_bytes(tmp_path, appended_zip) -> None:
    metadata = """<SketchupMaterial Version="4"><DiffuseColor>#123456</DiffuseColor><Opacity>0.4</Opacity>
      <Metallic>0.7</Metallic><Roughness>0.2</Roughness><Specular>0.6</Specular><IndexOfRefraction>1.8</IndexOfRefraction>
      <BumpMapType>NORMAL</BumpMapType><NormalMapIntensity>0.3</NormalMapIntensity>
      <BumpTexture><Filepath>C:\\maps\\missing.png</Filepath></BumpTexture>
      <RoughnessTexture><Filepath>C:\\maps\\TEXTURE.PNG</Filepath><Brightness>0.5</Brightness></RoughnessTexture>
    </SketchupMaterial>"""
    data = _legacy_material(metadata)
    if appended_zip:
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("document.xml", "<classificationDocument/>")
        data += archive_bytes.getvalue()
    path = tmp_path / "legacy.skp"
    path.write_bytes(data)

    original = skppy.load(path).materials[0]
    material = skppy.load(path, import_vray_materials=True).materials[0]

    assert original.color == skppy.Color(255, 84, 84)
    assert (original.alpha, original.metallic, original.roughness) == (1, 0, 1)
    assert original.roughness_texture is None
    assert material.color == skppy.Color(18, 52, 86)
    assert (material.alpha, material.metallic, material.roughness, material.specular, material.ior) == pytest.approx(
        (0.4, 0.7, 0.2, 0.6, 1.8)
    )
    assert material.texture.data == b"PNG"
    assert material.roughness_texture.data == b"PNG"
    assert material.roughness_texture.brightness == 0.5
    assert (material.roughness_texture.x_scale, material.roughness_texture.y_scale) == (12, 24)
    assert material.normal_texture.filename == "missing.png"
    assert material.normal_texture.data is None
    assert material.normal_scale == pytest.approx(0.3)


def test_legacy_enscape_applies_xml_budget_without_discarding_geometry(tmp_path) -> None:
    metadata = "<SketchupMaterial><Metallic>0.7</Metallic></SketchupMaterial>"
    path = tmp_path / "legacy.skp"
    path.write_bytes(_legacy_material(metadata))

    limited = skppy.load(path, import_vray_materials=True, limits=skppy.LoadLimits(max_xml_bytes=20))
    permitted = skppy.load(path, import_vray_materials=True, limits=skppy.LoadLimits(max_xml_bytes=len(metadata)))

    assert limited.materials[0].metallic == 0
    assert permitted.materials[0].metallic == pytest.approx(0.7)


def test_legacy_enscape_keeps_missing_map_without_a_base_texture(tmp_path) -> None:
    path = tmp_path / "legacy.skp"
    path.write_bytes(
        _legacy_material(
            """<SketchupMaterial><BumpMapType>BUMP</BumpMapType><BumpAmount>0.4</BumpAmount>
        <BumpTexture><Filepath>/maps/missing.png</Filepath></BumpTexture></SketchupMaterial>""",
            textured=False,
        )
    )

    material = skppy.load(path, import_vray_materials=True).materials[0]

    assert not material.has_texture
    assert material.bump_texture.filename == "missing.png"
    assert material.bump_texture.data is None
    assert material.bump_strength == pytest.approx(0.4)


@pytest.mark.parametrize(("metadata", "metallic"), [("<broken", 1), ("<SketchupMaterial/>", 0)])
def test_legacy_enscape_and_vray_use_the_same_precedence_as_skm(tmp_path, metadata, metallic) -> None:
    path = tmp_path / "mixed.skp"
    path.write_bytes(_legacy_material(metadata, vray=True))

    material = skppy.load(path, import_vray_materials=True).materials[0]

    assert material.metallic == metallic
