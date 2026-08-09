# SPDX-License-Identifier: MIT
"""Literal fixtures for modern model-section parser boundaries."""

from __future__ import annotations

import struct
from types import SimpleNamespace

import skppy.parser.model_parser as model_parser
from skppy.data_structure.entities import ComponentDefinition
from skppy.data_structure.materials import Material
from skppy.data_structure.model import Model
from skppy.data_structure.model_metadata import AttributeDictionary
from skppy.data_structure.scene_data import PageBackgroundImage, Scene
from skppy.parser.tlv import read_entity_id
from skppy.writer.tlv import encode_record


class Tag:
    """Observed wire tags kept independent of the production tag enum."""

    UNKNOWN = 0xFFFF
    MATERIALS_BLOCK = 0x01F7
    DEFINITIONS_BLOCK = 0x01F9
    BACKGROUND_IMAGES_BLOCK = 0x0201
    ACTIVE_BACKGROUND_IMAGE_REF = 0x0202
    SCENES_BLOCK = 0x0207
    MODEL_PROPERTIES_BLOCK = 0x0209
    ID_WRAPPER = 0x05DC
    ID_VALUE = 0x05DE
    ENVIRONMENT_THUMBNAIL_PATH = 0x2134
    DIB_RECORD = 0x2328
    DIB_EXTERNAL_PATH = 0x232A
    DIB_BINARY = 0x232B
    WATERMARK_MANAGER_RECORD = 0x2CEC
    WATERMARK_LIST = 0x2CED
    WATERMARK_SERIALIZED_COUNT = 0x2CEE
    WATERMARK_RECORD = 0x2EE0
    WATERMARK_FILE_NAME = 0x2EE4
    WATERMARK_POSITION = 0x2EE5
    WATERMARK_IMAGE = 0x2EE6
    WATERMARK_OPACITY = 0x2EED
    WATERMARK_FITTING_TYPE = 0x2EEE
    MATERIALS_CONTAINER = 0x30D4
    ATTR_TYPED_VALUE_TYPE = 0x38A7
    ATTR_TYPED_VALUE_F64 = 0x38A9
    ATTR_TYPED_VALUE_BOOL = 0x38AA
    ATTR_TYPED_VALUE_STRING = 0x38AD
    LINE_STYLES_RECORD = 0x4074
    LINE_STYLE_LIST = 0x4075
    LINE_STYLE_RECORD = 0x4076
    LINE_STYLE_COLOR = 0x407B
    SKETCH_AXES_Y_AXIS = 0x4653
    SKETCH_AXES_Z_AXIS = 0x4654
    MODEL_VIEW_RECORD = 0x4650
    FONTS_CONTAINER = 0x4E20
    FONTS_LIST = 0x4E21
    TEXT_STYLE_RECORD = 0x57E4
    TEXT_STYLE_COLOR = 0x57EC
    DIMENSION_STYLE_RECORD = 0x5FB4
    DIMENSION_STYLE_COLOR = 0x5FC4
    OPTIONS_MANAGER_RECORD = 0x61A8
    OPTIONS_PROVIDER_LIST = 0x61A9
    OPTIONS_PROVIDER_RECORD = 0x61AA
    OPTIONS_PROVIDER_NAME = 0x61AB
    OPTIONS_KEY_TABLE = 0x61AC
    OPTIONS_KEY_NAME = 0x61AD
    STYLES_REGISTRY = 0x6978
    STYLE_LIST = 0x6979
    INLINE_STYLE_OVERRIDE = 0x697B
    STYLE_DESCRIPTOR = 0x6B6C
    STYLE_FILE_NAME = 0x6B6F
    STYLE_WATERMARK_REFS = 0x6B70
    ENVIRONMENT_DATA_RECORD = 0x7918
    ENVIRONMENT_SELECTED_RECORD = 0x7919
    ENVIRONMENT_ENTRY = 0x7B0C
    ENVIRONMENT_THUMBNAIL_REF = 0x7B0E
    DEFINITIONS_CONTAINER = 0x1770


def _record(tag: int, payload: bytes = b"") -> bytes:
    return encode_record(tag, payload)


def test_geometry_resource_installer_decodes_materials_and_definitions(monkeypatch):
    model = Model()
    material = Material(id=4, name="Paint")
    definition = ComponentDefinition(id=5, name="Part")
    archive = SimpleNamespace(infolist=lambda: [])
    monkeypatch.setattr(model_parser, "build_zip_name_map", lambda _archive: {})
    monkeypatch.setattr(model_parser, "parse_materials", lambda *_args, **_kwargs: [material])
    monkeypatch.setattr(model_parser, "parse_definitions", lambda *_args, **_kwargs: [definition])
    fields = {
        Tag.MATERIALS_BLOCK: _record(Tag.MATERIALS_CONTAINER, b"materials"),
        Tag.DEFINITIONS_BLOCK: _record(Tag.DEFINITIONS_CONTAINER, b"definitions"),
    }

    model_parser._install_geometry_and_resources(model, fields, archive, {})

    assert model.materials == [material]
    assert model.definitions == [definition]


def test_document_metadata_links_active_and_scene_background_images(monkeypatch):
    model = Model()
    image = PageBackgroundImage(id=5, visible=True)
    scene = Scene(id=1, name="Photo", background_image_ref=5)
    dictionaries = [AttributeDictionary(name="model")]
    monkeypatch.setattr(model_parser, "parse_background_images", lambda *_args: {5: image})
    monkeypatch.setattr(model_parser, "parse_attribute_dictionaries", lambda _payload: dictionaries)
    monkeypatch.setattr(model_parser, "parse_scenes", lambda _payload: [scene])
    fields = {
        Tag.BACKGROUND_IMAGES_BLOCK: b"backgrounds",
        Tag.ACTIVE_BACKGROUND_IMAGE_REF: b"\x05",
        Tag.MODEL_PROPERTIES_BLOCK: b"properties",
        Tag.SCENES_BLOCK: b"scenes",
    }

    model_parser._install_document_metadata(model, fields, SimpleNamespace())

    assert model.background_image is image
    assert model.attribute_dictionaries == dictionaries
    assert scene.background_image is image
    assert scene.display_background_image is True


def test_post_process_syncs_definition_entity_scopes():
    model = Model(definitions=[ComponentDefinition(id=10)])
    model.definitions[0].entities.add_vertex(0.0, 0.0, 0.0)
    model_parser._post_process(model)
    assert model.definitions[0].entities._next_id == 2


def test_watermark_parser_decodes_embedded_and_missing_external_images():
    embedded = b"".join(
        (
            _record(Tag.WATERMARK_FILE_NAME, b"Logo"),
            _record(Tag.ID_WRAPPER, _record(Tag.ID_VALUE, b"\x07")),
            _record(Tag.WATERMARK_POSITION, struct.pack("<i", 2)),
            _record(Tag.WATERMARK_FITTING_TYPE, struct.pack("<i", 0)),
            _record(Tag.WATERMARK_OPACITY, struct.pack("<d", 0.5)),
            _record(
                Tag.WATERMARK_IMAGE,
                _record(Tag.DIB_RECORD, _record(Tag.DIB_BINARY, b"pixels")),
            ),
        )
    )
    external = _record(
        Tag.WATERMARK_IMAGE,
        _record(Tag.DIB_RECORD, _record(Tag.DIB_EXTERNAL_PATH, b"missing.png")),
    )
    manager_record = b"".join(
        (
            _record(
                Tag.WATERMARK_LIST,
                _record(Tag.UNKNOWN)
                + _record(Tag.WATERMARK_RECORD, embedded)
                + _record(Tag.WATERMARK_RECORD, external),
            ),
            _record(Tag.WATERMARK_SERIALIZED_COUNT, b"\x02"),
        )
    )
    archive = SimpleNamespace(read=lambda path: (_ for _ in ()).throw(KeyError(path)))

    manager = model_parser._parse_watermarks(_record(Tag.WATERMARK_MANAGER_RECORD, manager_record), archive)

    assert manager.serialized_count == 2
    assert manager.watermarks[0].name == "Logo"
    assert manager.watermarks[0].image_data == b"pixels"
    assert manager.watermarks[0].position == 5
    assert manager.watermarks[0].opacity == 0.5
    assert manager.watermarks[0].id == 7
    assert manager.watermarks[1].image_data is None


def test_style_registry_skips_other_records_and_decodes_inline_override():
    descriptor = _record(Tag.STYLE_FILE_NAME, b"Draft")
    registry_payload = b"".join(
        (
            _record(Tag.STYLE_LIST, _record(Tag.UNKNOWN)),
            _record(
                Tag.INLINE_STYLE_OVERRIDE,
                _record(Tag.STYLE_DESCRIPTOR, descriptor),
            ),
        )
    )
    registry = model_parser._parse_styles_registry(_record(Tag.STYLES_REGISTRY, registry_payload))
    assert registry.styles == []
    assert registry.inline_style_override is not None
    assert registry.inline_style_override.file_name == "Draft"


def test_style_descriptor_stops_at_invalid_watermark_reference_width():
    descriptor = b"".join(
        (
            _record(Tag.STYLE_FILE_NAME, b"Style"),
            _record(Tag.STYLE_WATERMARK_REFS, b"\x01\x05\x00"),
        )
    )
    style = model_parser._parse_style_descriptor(descriptor, None)
    assert style.watermark_reference_ids == [5]


def test_font_line_style_and_color_decoders_cover_empty_and_unrelated_lists():
    assert model_parser._parse_fonts(_record(Tag.FONTS_CONTAINER, _record(Tag.UNKNOWN))) == []
    assert model_parser._parse_fonts(_record(Tag.FONTS_CONTAINER, _record(Tag.FONTS_LIST, _record(Tag.UNKNOWN)))) == []
    assert model_parser._parse_line_styles(_record(Tag.LINE_STYLES_RECORD, _record(Tag.UNKNOWN))) == []
    assert (
        model_parser._parse_line_styles(
            _record(
                Tag.LINE_STYLES_RECORD,
                _record(Tag.LINE_STYLE_LIST, _record(Tag.UNKNOWN)),
            )
        )
        == []
    )

    line = model_parser._parse_line_styles(
        _record(
            Tag.LINE_STYLES_RECORD,
            _record(
                Tag.LINE_STYLE_LIST,
                _record(
                    Tag.LINE_STYLE_RECORD,
                    _record(Tag.LINE_STYLE_COLOR, b"\x01\x02\x03\x04"),
                ),
            ),
        )
    )[0]
    assert line.color == 0x04010203


def test_text_and_dimension_styles_decode_rgba_colors():
    text = model_parser._parse_text_style(
        _record(Tag.TEXT_STYLE_RECORD, _record(Tag.TEXT_STYLE_COLOR, b"\x01\x02\x03\x04"))
    )
    dimension = model_parser._parse_dimension_style(
        _record(
            Tag.DIMENSION_STYLE_RECORD,
            _record(Tag.DIMENSION_STYLE_COLOR, b"\x05\x06\x07\x08"),
        )
    )
    assert text.color == 0x04010203
    assert dimension.color == 0x08050607


def test_options_manager_skips_other_records_and_decodes_typed_values():
    key_table = b"".join(
        (
            _record(Tag.OPTIONS_KEY_NAME, b"Enabled"),
            _record(
                0x38A4,
                _record(Tag.ATTR_TYPED_VALUE_BOOL, b"\x01"),
            ),
        )
    )
    providers = _record(Tag.UNKNOWN) + _record(
        Tag.OPTIONS_PROVIDER_RECORD,
        _record(Tag.OPTIONS_PROVIDER_NAME, b"Page") + _record(Tag.OPTIONS_KEY_TABLE, key_table),
    )
    manager = model_parser._parse_options_manager(
        _record(
            Tag.OPTIONS_MANAGER_RECORD,
            _record(Tag.OPTIONS_PROVIDER_LIST, providers),
        )
    )
    assert manager.providers[0].keys == {"Enabled": True}

    assert model_parser._parse_option_value(_record(Tag.ATTR_TYPED_VALUE_F64, struct.pack("<d", 1.25))) == 1.25
    assert model_parser._parse_option_value(_record(Tag.ATTR_TYPED_VALUE_TYPE, struct.pack("<i", -2))) == -2
    assert model_parser._parse_option_value(_record(Tag.ATTR_TYPED_VALUE_STRING, b"value")) == "value"
    assert model_parser._parse_option_value(b"") == ""


def test_environment_nested_thumbnail_and_model_view_yz_axes():
    entry = _record(
        Tag.ENVIRONMENT_THUMBNAIL_REF,
        _record(Tag.ENVIRONMENT_THUMBNAIL_PATH, b"thumb.png"),
    )
    environment = model_parser._parse_environment_data(
        _record(
            Tag.ENVIRONMENT_DATA_RECORD,
            _record(
                Tag.ENVIRONMENT_SELECTED_RECORD,
                _record(Tag.ENVIRONMENT_ENTRY, entry),
            ),
        )
    )
    assert environment.selected is not None
    assert environment.selected.thumbnail_path == "thumb.png"

    axes = model_parser._parse_model_view_axes(
        _record(
            Tag.MODEL_VIEW_RECORD,
            _record(Tag.SKETCH_AXES_Y_AXIS, struct.pack("<3d", 0.0, 1.0, 0.0))
            + _record(Tag.SKETCH_AXES_Z_AXIS, struct.pack("<3d", 0.0, 0.0, 1.0)),
        )
    )
    assert axes.y_axis == (0.0, 1.0, 0.0)
    assert axes.z_axis == (0.0, 0.0, 1.0)


def test_tlv_entity_id_success_path():
    payload = _record(Tag.ID_WRAPPER, _record(Tag.ID_VALUE, b"\x2a"))
    assert read_entity_id(payload) == 42
