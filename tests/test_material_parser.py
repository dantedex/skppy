# SPDX-License-Identifier: MIT
import io
import struct
import zipfile

import pytest

from skppy.parser.material_parser import _parse_material_xml, parse_materials

# 0x30D5 is the serialized material list; 0x32C8 and 0x32CA-0x32CD encode one
# material record. 0x32CA distinguishes global from layer-embedded records;
# texture and opacity state come from the optional material XML resource.


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _material_container(*records: bytes) -> bytes:
    return _record(0x30D5, b"".join(records))


def _material_record(
    name: str,
    *,
    material_id: int = 1,
    embedded: bool = False,
    auxiliary_value: int = 0,
) -> bytes:
    payload = b"".join(
        (
            _record(
                0x05DC,
                _record(0x05DE, struct.pack("<H", material_id)),
            ),
            _record(0x32CC, name.encode()),
            _record(0x32CA, bytes((embedded,))),
            _record(
                0x32CD,
                struct.pack("<I", auxiliary_value),
            ),
        )
    )
    return _record(0x32C8, payload)


def _parse(xml: str, tmp_path):
    archive_path = tmp_path / "materials.skp"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("dummy", b"")
    with zipfile.ZipFile(archive_path) as zf:
        return _parse_material_xml(xml.encode("utf-8"), "Paint", zf, {})


def test_material_xml_reads_enabled_pbr_child_factors(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<materialDocument xmlns="http://sketchup.google.com/schemas/sketchup/1.0/material"
                  xmlns:mat="http://sketchup.google.com/schemas/sketchup/1.0/material">
  <mat:material colorRed="10" colorGreen="20" colorBlue="30" hasTexture="0">
    <mat:pbrMR>
      <mat:enable_metalness>1</mat:enable_metalness>
      <mat:enable_roughness>1</mat:enable_roughness>
      <mat:metallicFactor>0.65</mat:metallicFactor>
      <mat:roughnessFactor>0.35</mat:roughnessFactor>
    </mat:pbrMR>
  </mat:material>
</materialDocument>
"""

    material = _parse(xml, tmp_path)

    assert material.metallic == pytest.approx(0.65)
    assert material.roughness == pytest.approx(0.35)


def test_material_xml_ignores_disabled_pbr_child_factors(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<materialDocument xmlns="http://sketchup.google.com/schemas/sketchup/1.0/material"
                  xmlns:mat="http://sketchup.google.com/schemas/sketchup/1.0/material">
  <mat:material colorRed="10" colorGreen="20" colorBlue="30" hasTexture="0">
    <mat:pbrMR>
      <mat:enable_metalness>0</mat:enable_metalness>
      <mat:enable_roughness>0</mat:enable_roughness>
      <mat:metallicFactor>1</mat:metallicFactor>
      <mat:roughnessFactor>0</mat:roughnessFactor>
    </mat:pbrMR>
  </mat:material>
</materialDocument>
"""

    material = _parse(xml, tmp_path)

    assert material.metallic == pytest.approx(0.0)
    assert material.roughness == pytest.approx(1.0)


def test_material_xml_reads_legacy_pbr_factor_attributes(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<materialDocument>
  <material colorRed="10" colorGreen="20" colorBlue="30" hasTexture="0">
    <pbrMR metallicFactor="0.25" roughnessFactor="0.75" />
  </material>
</materialDocument>
"""

    material = _parse(xml, tmp_path)

    assert material.metallic == pytest.approx(0.25)
    assert material.roughness == pytest.approx(0.75)


def test_materials_do_not_infer_appearance_from_context_fields() -> None:
    """Keep neutral appearance when no material XML resource is available."""
    payload = _material_container(
        _record(0x7FFF, b"ignored"),
        _material_record("Paint", material_id=42, embedded=True, auxiliary_value=25),
    )

    material = parse_materials(payload)[0]

    assert material.id == 42
    assert material.name == "Paint"
    assert material.has_texture is False
    assert material.texture is None
    assert material.alpha == 1.0


def test_material_xml_overrides_tlv_fallback_and_loads_texture() -> None:
    """Prefer rich XML properties and load its ZIP-relative image bytes."""
    xml = b"""<materialDocument>
  <material colorRed="10" colorGreen="20" colorBlue="30"
            useTrans="1" trans="0.25" hasTexture="1">
    <texture textureFilename="C:\\textures\\paint.png" xScale="2" yScale="3">
      <images><image path="./paint.png" /></images>
    </texture>
  </material>
</materialDocument>"""
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("materials/Paint/material.xml", xml)
        archive.writestr("materials/Paint/paint.png", b"image data")
    archive_bytes.seek(0)

    payload = _material_container(
        _material_record("Paint", embedded=False, auxiliary_value=10),
    )
    with zipfile.ZipFile(archive_bytes) as archive:
        material = parse_materials(payload, archive)[0]

    assert (material.color.r, material.color.g, material.color.b) == (10, 20, 30)
    assert material.alpha == pytest.approx(0.75)
    assert material.has_texture is True
    assert material.texture is not None
    assert material.texture.filename == "paint.png"
    assert material.texture.data == b"image data"
    assert (material.texture.x_scale, material.texture.y_scale) == (2.0, 3.0)


def test_material_xml_transparency_defaults_to_opaque_and_clamps(tmp_path) -> None:
    """Do not invent half transparency when an enabled value is absent."""
    missing = """<materialDocument><material useTrans="1" /></materialDocument>"""
    excessive = """<materialDocument>
      <material useTrans="1" trans="2.0" />
    </materialDocument>"""

    assert _parse(missing, tmp_path).alpha == 1.0
    assert _parse(excessive, tmp_path).alpha == 0.0


def test_malformed_material_xml_preserves_tlv_fallback() -> None:
    """Keep material identity and neutral appearance after optional XML fails."""
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("materials/Paint/material.xml", b"<broken")
    archive_bytes.seek(0)
    payload = _material_container(
        _material_record("Paint", embedded=True, auxiliary_value=40),
    )

    with zipfile.ZipFile(archive_bytes) as archive:
        material = parse_materials(payload, archive)[0]

    assert material.has_texture is False
    assert material.alpha == 1.0


def test_material_xml_rejects_entity_declarations(tmp_path) -> None:
    """Do not expand entities from untrusted material metadata."""
    xml = """<!DOCTYPE materialDocument [<!ENTITY repeated "expanded">]>
    <materialDocument><material colorRed="&repeated;" /></materialDocument>"""

    with pytest.raises(ValueError, match="DTD and entity declarations"):
        _parse(xml, tmp_path)


def test_corrupt_texture_keeps_complete_tlv_material_fallback() -> None:
    """Commit no XML fields when a referenced texture fails its CRC check."""
    xml = b"""<materialDocument>
      <material colorRed="10" colorGreen="20" colorBlue="30"
                useTrans="1" trans="0.25" hasTexture="1">
        <texture textureFilename="paint.png">
          <images><image path="./paint.png" /></images>
        </texture>
      </material>
    </materialDocument>"""
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("materials/Paint/material.xml", xml)
        archive.writestr("materials/Paint/paint.png", b"known texture bytes")
    corrupted = bytearray(archive_bytes.getvalue())
    payload_offset = corrupted.find(b"known texture bytes")
    assert payload_offset >= 0
    corrupted[payload_offset] ^= 0xFF

    payload = _material_container(
        _material_record("Paint", embedded=True, auxiliary_value=40),
    )
    with zipfile.ZipFile(io.BytesIO(corrupted)) as archive:
        material = parse_materials(payload, archive)[0]

    assert material.color.r == 128
    assert material.alpha == 1.0
    assert material.has_texture is False
    assert material.texture is None


def test_invalid_material_xml_numbers_preserve_field_fallbacks() -> None:
    """Ignore malformed optional numbers without leaving partial state."""
    xml = b"""<materialDocument>
      <material colorRed="invalid" useTrans="1" trans="invalid" hasTexture="1">
        <texture textureFilename="paint.png" xScale="invalid" yScale="invalid" />
      </material>
    </materialDocument>"""
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("materials/Paint/material.xml", xml)
    archive_bytes.seek(0)
    payload = _material_container(
        _material_record("Paint", embedded=True, auxiliary_value=40),
    )

    with zipfile.ZipFile(archive_bytes) as archive:
        material = parse_materials(payload, archive)[0]

    assert material.color.r == 128
    assert material.alpha == 1.0
    assert material.texture is not None
    assert material.texture.x_scale == 1.0
    assert material.texture.y_scale == 1.0
