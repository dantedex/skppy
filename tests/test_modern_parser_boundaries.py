# SPDX-License-Identifier: MIT
"""Defensive boundary cases shared by the smaller modern parser modules."""

from __future__ import annotations

import io
import struct
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

import skppy.parser.definitions as definition_parser
import skppy.parser.layers as layer_parser
import skppy.parser.material_parser as material_parser
from skppy.data_structure.entities import ComponentDefinition
from skppy.data_structure.model_metadata import AttributeDictionary
from skppy.parser.attributes import (
    parse_attribute_dictionary_root,
    parse_entity_attribute_dictionaries,
)
from skppy.parser.camera_parser import parse_camera_record
from skppy.parser.header_parser import (
    _read_prefixed_utf16_string,
    _read_raw_utf16le_header,
)
from skppy.parser.meta_parser import _strip_type_suffix, parse_meta_info
from skppy.parser.rendering_options import parse_rendering_options
from skppy.parser.scenes_parser import parse_scenes
from skppy.parser.tlv import (
    find_all_children,
    read_entity_id,
    read_u32_le,
)
from skppy.writer.tlv import encode_record


class TlvTag:
    """Literal observed wire tags; intentionally independent of production."""

    MODEL_EMPTY_MARKER = 0x0201
    ID_WRAPPER = 0x05DC
    ID_VALUE = 0x05DE
    DEFINITION_RECORD = 0x157C
    DEFINITIONS_LIST = 0x1771
    MATERIALS_LIST = 0x30D5
    MATERIAL_RECORD = 0x32C8
    CAMERA_EYE = 0x34BD
    CAMERA_TARGET = 0x34BE
    ATTR_DICT_RECORD = 0x36B2
    ATTR_DICT_NAME = 0x36B4
    LAYER_RECORD = 0x3C8C
    LAYER_MATERIAL = 0x3C8F
    SCENES_CONTAINER = 0x6D60
    SCENES_LIST = 0x6D61


def _record(tag: int, payload: bytes = b"") -> bytes:
    return encode_record(tag, payload)


def test_attribute_parser_ignores_missing_and_technical_records():
    assert parse_entity_attribute_dictionaries(b"") == []
    root = b"".join(
        (
            _record(TlvTag.MODEL_EMPTY_MARKER),
            _record(TlvTag.ATTR_DICT_RECORD, _record(TlvTag.ATTR_DICT_NAME, b"UV")),
        )
    )
    assert parse_attribute_dictionary_root(root) == []


@pytest.mark.parametrize(
    "payload",
    [
        _record(TlvTag.CAMERA_TARGET, struct.pack("<ddd", 0.0, 0.0, 0.0)),
        _record(TlvTag.CAMERA_EYE, struct.pack("<ddd", 0.0, 0.0, 0.0))
        + _record(TlvTag.CAMERA_TARGET, struct.pack("<ddd", 0.0, 0.0, 0.0)),
    ],
)
def test_camera_parser_rejects_missing_required_vectors(payload):
    assert parse_camera_record(payload) is None


def test_definition_parser_publishes_definition_attributes(monkeypatch):
    definition = ComponentDefinition(id=42)
    attributes = [AttributeDictionary(name="custom")]
    monkeypatch.setattr(definition_parser, "_parse_definition", lambda _payload: definition)
    monkeypatch.setattr(definition_parser, "_parse_definition_attributes", lambda _payload: attributes)
    payload = _record(
        TlvTag.DEFINITIONS_LIST,
        _record(TlvTag.MODEL_EMPTY_MARKER) + _record(TlvTag.DEFINITION_RECORD),
    )
    by_id = {}

    assert definition_parser.parse_definitions(payload, attribute_dictionaries_by_object_id=by_id) == [definition]
    assert by_id == {42: attributes}


def test_header_helpers_cover_default_raw_size_and_invalid_bom():
    stream = io.BytesIO(b"A" * 80)
    assert _read_raw_utf16le_header(stream) == b"A" * 64
    assert stream.tell() == 64

    with pytest.raises(ValueError, match="Unexpected UTF-16 BOM"):
        _read_prefixed_utf16_string(io.BytesIO(b"NO\x01\x00"), "field")


def test_layer_parser_tracks_attributes_and_rejects_bad_nested_data(monkeypatch):
    attributes = [AttributeDictionary(name="layer")]
    monkeypatch.setattr(layer_parser, "parse_entity_attribute_dictionaries", lambda _payload: attributes)
    layer_payload = _record(TlvTag.ID_WRAPPER, _record(TlvTag.ID_VALUE, b"\x07"))
    by_id = {}
    layers = layer_parser._parse_layer_list(
        _record(TlvTag.LAYER_RECORD, layer_payload),
        attribute_dictionaries_by_object_id=by_id,
    )
    assert layers[0].id == 7
    assert by_id == {7: attributes}

    nested_material = _record(TlvTag.MATERIAL_RECORD) + b"trailing"
    with pytest.raises(ValueError, match="trailing TLV data"):
        layer_parser._parse_layer_list(
            _record(
                TlvTag.LAYER_RECORD,
                _record(TlvTag.LAYER_MATERIAL, nested_material),
            )
        )


def test_layer_folder_parser_skips_other_records_and_rejects_bad_width():
    assert layer_parser._parse_folder_nodes(_record(TlvTag.MODEL_EMPTY_MARKER)) == []
    with pytest.raises(ValueError, match="width must be 1-4"):
        layer_parser._read_length_prefixed_ids(b"\x00")


def test_material_security_zip_and_xml_fallback_helpers(monkeypatch):
    with pytest.raises(ValueError, match="exceeds the maximum"):
        material_parser._parse_bounded_xml(b"xx", max_bytes=1)

    fake_zip = SimpleNamespace(
        infolist=lambda: [
            SimpleNamespace(filename="├⌐.png"),
            SimpleNamespace(filename="€.png"),
        ]
    )
    assert material_parser.build_zip_name_map(fake_zip) == {"é.png": "├⌐.png"}

    reader = SimpleNamespace(read=lambda path: b"mapped" if path == "stored" else (_ for _ in ()).throw(KeyError(path)))
    assert material_parser._zip_read(reader, "wanted", {"wanted": "stored"}) == b"mapped"


def test_material_parser_empty_and_explicit_map_paths():
    assert material_parser.parse_materials(b"") == []
    payload = _record(TlvTag.MATERIALS_LIST, _record(TlvTag.MODEL_EMPTY_MARKER))
    assert material_parser.parse_materials(payload, zip_name_map={"a": "b"}) == []


def test_material_record_tracks_attributes(monkeypatch):
    attributes = [AttributeDictionary(name="material")]
    monkeypatch.setattr(
        material_parser,
        "parse_entity_attribute_dictionaries",
        lambda _payload: attributes,
    )
    by_id = {}
    material = material_parser.parse_material_record(
        _record(TlvTag.ID_WRAPPER, _record(TlvTag.ID_VALUE, b"\x09")),
        fallback_id=1,
        attribute_dictionaries_by_object_id=by_id,
    )
    assert material.id == 9
    assert by_id == {9: attributes}


def test_material_xml_helpers_cover_absent_elements_and_invalid_values(tmp_path):
    root = ET.fromstring("<root />")
    assert (
        material_parser._parse_material_xml(
            b"<root />",
            "",
            None,  # type: ignore[arg-type]
        ).name
        == ""
    )
    ns = {"mat": material_parser._MAT_NS}
    assert (
        material_parser._parse_texture_xml(
            root,
            ns,
            "name",
            None,
            {},  # type: ignore[arg-type]
        )
        is None
    )

    child = ET.fromstring("<root><factor>bad</factor></root>")
    assert material_parser._child_float(child, ns, "factor", default=2.0) == 2.0


def test_declared_texture_images_skip_empty_paths_and_fill_filename(monkeypatch):
    texture_element = ET.fromstring(
        "<texture><images><image/><image path='image.png' file_name='display.png'/></images></texture>"
    )
    texture = material_parser.Texture()
    monkeypatch.setattr(material_parser, "_zip_read", lambda *_args: b"pixels")
    ns = {"mat": material_parser._MAT_NS}
    material_parser._load_declared_texture_image(
        texture,
        texture_element,
        ns,
        "Material",
        None,
        {},  # type: ignore[arg-type]
    )
    assert texture.data == b"pixels"
    assert texture.filename == "display.png"


def test_meta_classifier_filters_meta_paths_and_generic_paths():
    info = parse_meta_info(b"meta/itemP\x00C:/models/file.skpP\x00AliceP\x00")
    assert info.contributors == ["Alice"]
    assert _strip_type_suffix("ABC") == "ABC"


def test_rendering_options_and_scenes_return_defaults_for_missing_containers():
    assert parse_rendering_options(b"").display_section_planes is False
    assert parse_scenes(_record(TlvTag.SCENES_CONTAINER, _record(TlvTag.MODEL_EMPTY_MARKER))) == []
    scenes_payload = _record(
        TlvTag.SCENES_CONTAINER,
        _record(
            TlvTag.SCENES_LIST,
            _record(TlvTag.MODEL_EMPTY_MARKER),
        ),
    )
    assert parse_scenes(scenes_payload) == []


def test_tlv_collection_scalar_and_nested_id_helpers():
    payload = _record(7, b"a") + _record(8, b"b") + _record(7, b"c")
    assert find_all_children(payload, 7) == [b"a", b"c"]
    assert read_u32_le(b"\x78\x56\x34\x12extra") == 0x12345678
    assert read_entity_id(b"") == 0
    assert read_entity_id(_record(TlvTag.ID_WRAPPER, _record(TlvTag.MODEL_EMPTY_MARKER))) == 0
