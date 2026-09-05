# SPDX-License-Identifier: MIT
"""Modern material TLV and XML serialization."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from math import isfinite
from pathlib import PurePosixPath

from .._material_validation import validate_material_export, validate_material_names
from ..data_structure.materials import Material
from ..data_structure.model_metadata import AttributeDictionary
from ..parser.tlv import TlvTag
from .attributes import encode_attribute_dictionaries
from .tlv import encode_bool, encode_compact_int, encode_record, encode_records
from .vray_materials import append_vray_xml

_MATERIAL_NAMESPACE = "http://sketchup.google.com/schemas/sketchup/1.0/material"


def encode_materials(
    materials: Iterable[Material],
    id_map: Mapping[int, int],
    attribute_dictionaries_by_object_id: Mapping[int, Iterable[AttributeDictionary]] | None = None,
) -> bytes:
    """Encode the payload of a modern root materials block."""
    material_list = list(materials)
    _validate_materials(material_list, id_map)
    records = []
    for material in material_list:
        records.append(
            (
                TlvTag.MATERIAL_RECORD,
                encode_material_record(
                    material,
                    id_map[material.id],
                    attribute_dictionaries=(attribute_dictionaries_by_object_id or {}).get(material.id, ()),
                ),
            )
        )
    material_records = encode_record(TlvTag.MATERIALS_LIST, encode_records(records))
    return encode_record(TlvTag.MATERIALS_CONTAINER, material_records)


def encode_material_record(
    material: Material,
    serialized_id: int,
    *,
    embedded: bool = False,
    attribute_dictionaries: Iterable[AttributeDictionary] = (),
) -> bytes:
    """Encode one material-record payload for global or embedded use."""
    _validate_material(material)
    if serialized_id <= 0:
        raise ValueError("Serialized material ID must be positive")
    identity_fields = encode_record(TlvTag.ID_VALUE, encode_compact_int(serialized_id))
    dictionaries = list(attribute_dictionaries)
    if dictionaries:
        identity_fields += encode_record(
            TlvTag.ID_EXT_PAYLOAD,
            encode_attribute_dictionaries(dictionaries),
        )
    return encode_records(
        (
            (TlvTag.ID_WRAPPER, identity_fields),
            (TlvTag.MATERIAL_NAME, material.name.encode("utf-8")),
            (
                TlvTag.MATERIAL_EMBEDDED,
                encode_bool(embedded),
            ),
            (TlvTag.MATERIAL_TEX_PAYLOAD, b""),
        )
    )


def material_entries(materials: Iterable[Material], *, export_vray_materials: bool = False) -> dict[str, bytes]:
    """Return deterministic ZIP entries containing material XML documents."""
    materials = list(materials)
    validate_material_names(materials)
    entries = {}
    for material in materials:
        _validate_material(material)
        entries[f"materials/{material.name}/material.xml"] = encode_material_xml(
            material,
            export_vray_materials=export_vray_materials,
        )
        if material.texture is not None:
            filename = _texture_filename(material)
            assert material.texture.data is not None
            entries[f"materials/{material.name}/{filename}"] = material.texture.data
    return entries


def encode_material_xml(material: Material, *, export_vray_materials: bool = False) -> bytes:
    """Encode one material appearance document using the public XML schema."""
    _validate_material(material)
    # SketchUp's material reader recognizes the canonical document shape: an
    # unprefixed root in the default namespace and `mat:`-prefixed descendants.
    # A generic `ns0:` serialization is equivalent XML, but the official reader
    # falls back to an automatically named material when it encounters it.
    document = ET.Element(
        "materialDocument",
        {"xmlns": _MATERIAL_NAMESPACE, "xmlns:mat": _MATERIAL_NAMESPACE},
    )
    material_element = ET.SubElement(
        document,
        "mat:material",
        {
            "name": material.name,
            "type": "1" if material.texture is not None else "0",
            "workflow": "0",
            "colorRed": str(material.color.r),
            "colorGreen": str(material.color.g),
            "colorBlue": str(material.color.b),
            "colorizeType": "0",
            "trans": _format_factor(1.0 - material.alpha),
            "useTrans": "1" if material.alpha < 1.0 else "0",
            "pbrPromoState": "0",
            "hasTexture": "1" if material.texture is not None else "0",
        },
    )
    if material.texture is not None:
        filename = _texture_filename(material)
        texture = ET.SubElement(
            material_element,
            "mat:texture",
            {
                "textureFilename": filename,
                "xScale": _format_factor(material.texture.x_scale),
                "yScale": _format_factor(material.texture.y_scale),
                "avgColor": str(_packed_color(material)),
            },
        )
        images = ET.SubElement(texture, "mat:images")
        ET.SubElement(
            images,
            "mat:image",
            {"id": "1", "path": f"./{filename}", "file_name": filename},
        )
    pbr = ET.SubElement(
        material_element,
        "mat:pbrMR",
        {"xScale": "1", "yScale": "1"},
    )
    values = {
        "enable_metalness": "1" if material.metallic != 0.0 else "0",
        "enable_roughness": "1" if material.roughness != 1.0 else "0",
        "roughness_texture_invert": "0",
        "enable_normal": "0",
        "enable_occlusion": "0",
        "metallicFactor": _format_factor(material.metallic),
        "roughnessFactor": _format_factor(material.roughness),
        "normalMapStyle": "1",
        "normalScale": "1",
        "occlusionStrength": "1",
        "baseColorFactor": "4294967295",
    }
    for name, value in values.items():
        ET.SubElement(pbr, f"mat:{name}").text = value
    if export_vray_materials:
        append_vray_xml(material_element, material)
    ET.indent(document, space="  ")
    encoded: bytes = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    return encoded


def _validate_materials(materials: list[Material], id_map: Mapping[int, int]) -> None:
    validate_material_names(materials)
    ids = [material.id for material in materials]
    if any(material_id <= 0 for material_id in ids):
        raise ValueError("Material IDs must be positive")
    if len(ids) != len(set(ids)):
        raise ValueError("Material IDs must be unique")
    if any(material_id not in id_map for material_id in ids):
        raise ValueError("Material ID map does not cover every material")
    mapped = [id_map[material_id] for material_id in ids]
    if any(material_id <= 0 for material_id in mapped) or len(mapped) != len(set(mapped)):
        raise ValueError("Mapped material IDs must be positive and unique")
    for material in materials:
        _validate_material(material)


def _validate_material(material: Material) -> None:
    validate_material_export(material)
    if not material.name or material.name in {".", ".."} or any(char in material.name for char in "/\\"):
        raise ValueError("Material name must be non-empty and path-safe")
    channels = (
        material.color.r,
        material.color.g,
        material.color.b,
        material.color.a,
    )
    if any(not isinstance(channel, int) or not 0 <= channel <= 255 for channel in channels):
        raise ValueError("Material color channels must be integers in [0, 255]")
    factors = (material.alpha, material.metallic, material.roughness)
    if any(not isfinite(value) or not 0.0 <= value <= 1.0 for value in factors):
        raise ValueError("Material factors must be finite values in [0, 1]")
    if material.has_texture != (material.texture is not None):
        raise ValueError("Material texture flag and texture object must agree")
    if material.texture is not None:
        _texture_filename(material)
        if material.texture.data is None:
            raise ValueError("Texture image data is required for writing")
        scales = (material.texture.x_scale, material.texture.y_scale)
        if any(not isfinite(value) or abs(value) < 1e-12 for value in scales):
            raise ValueError("Texture scales must be finite and non-zero")


def _format_factor(value: float) -> str:
    return format(value, ".17g")


def _texture_filename(material: Material) -> str:
    assert material.texture is not None
    filename = PurePosixPath(material.texture.filename.replace("\\", "/")).name
    if not filename or filename in {".", "..", "material.xml"}:
        raise ValueError("Texture filename must contain a safe basename")
    return filename


def _packed_color(material: Material) -> int:
    color = material.color
    return (color.a << 24) | (color.r << 16) | (color.g << 8) | color.b
