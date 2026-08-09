# SPDX-License-Identifier: MIT
"""Integration tests for modern ``model.dat`` model assembly."""

from __future__ import annotations

import io
import struct
import zipfile

from skppy.data_structure.document import SkpDocument
from skppy.data_structure.header import SkpHeader
from skppy.parser.model_parser import (
    _parse_dimension_style,
    _parse_environment_data,
    _parse_fonts,
    _parse_line_styles,
    _parse_model_view_axes,
    _parse_options_manager,
    _parse_shadow_info,
    _parse_styles_registry,
    _parse_sun_data,
    _parse_text_style,
    _parse_watermarks,
    parse_model,
)
from skppy.parser.camera_parser import parse_cameras

# The integration fixture deliberately uses raw model.dat tags. Root blocks are
# 0x01F4-0x0213; nested comments and variable names identify entities, layers,
# cameras, rendering, styles, annotations, environments, axes, and scenes.


def _record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def _vec3(x: float, y: float, z: float) -> bytes:
    return struct.pack("<3d", x, y, z)


def _f64(value: float) -> bytes:
    return struct.pack("<d", value)


def _header() -> SkpHeader:
    return SkpHeader(
        product_name="SketchUp",
        version_string="{26.0.0}",
        version_tuple=(26, 0, 0),
        vff_magic="VFF",
        vff_field_1=0,
        vff_field_2=0,
        vff_field_3=0,
        vff_field_4=0,
        zip_offset=0,
    )


def _camera_record() -> bytes:
    # 0x34BC camera record with vector, clipping, projection, and 2-D fields.
    return _record(
        0x34BC,
        b"".join(
            (
                _record(0x34BD, _vec3(1, 2, 3)),
                _record(0x34BE, _vec3(4, 5, 6)),
                _record(0x34BF, _vec3(0, 0, 1)),
                _record(0x34C0, _f64(0.25)),
                _record(0x34C1, _f64(500.0)),
                _record(0x34C2, b"\x00"),
                _record(0x34C4, _f64(42.0)),
                _record(0x34C6, b"\x00"),
                _record(0x34C8, b"Saved camera"),
                _record(0x34C3, _f64(12.0)),
                _record(0x34C5, _f64(16 / 9)),
                _record(0x34C7, b"\x01"),
                _record(0x34C9, _f64(1920.0)),
                _record(0x34CA, b"\x01"),
                _record(0x34CB, _f64(2.0)),
                _record(0x34CC, _f64(10.0)),
                _record(0x34CD, _f64(20.0)),
                _record(0x34CE, b"\x00"),
            )
        ),
    )


def _model_data() -> bytes:
    # 0x01F6 -> 0x1388 -> 0x1389 is root entities -> scope -> vertices.
    vertex = _record(
        0x09C4,
        _record(0x05DC, _record(0x05DE, b"\x0b")) + _record(0x09C5, _vec3(1, 2, 3)),
    )
    entities = _record(
        0x01F6,
        _record(0x1388, _record(0x1389, vertex)),
    )

    # 0x01F8 -> 0x3A98 -> 0x3A99 is the layers block/container/list.
    layer = _record(
        0x3C8C,
        _record(0x05DC, _record(0x05DE, b"\x07"))
        + _record(0x3C8D, b"Geometry")
        # Layer visibility is stored as a hidden bit.
        + _record(0x3C8E, b"\x01")
        # 0x3C8F embeds a regular 0x32C8 material record for layer display.
        + _record(
            0x3C8F,
            _record(
                0x32C8,
                _record(0x05DC, _record(0x05DE, b"\x2a")) + _record(0x32CC, b"Layer_Geometry"),
            ),
        ),
    )
    layers = _record(
        0x01F8,
        _record(
            0x3A98,
            _record(0x3A99, layer),
        )
        + _record(0x3A9A, b"\x07"),
    )

    # Model metadata blocks retain their literal root tags to catch enum drift.
    rendering = _record(
        0x01FB,
        _record(
            0x733C,
            _record(0x7340, b"\x00") + _record(0x7362, _f64(12.5)) + _record(0x7357, b"\x11\x22\x33\x44"),
        ),
    )
    shadow = _record(
        0x0204,
        _record(
            0x6590,
            _record(0x6596, _f64(-23.5))
            + _record(0x6595, _f64(-46.6))
            + _record(0x6591, b"\x0c")
            + _record(0x6593, b"Sao Paulo")
            + _record(0x6594, b"Brasil")
            + _record(0x6598, _vec3(0, 1, 0))
            + _record(0x6599, b"\x01"),
        ),
    )
    watermarks = _record(
        0x0203,
        _record(
            0x2CEC,
            _record(0x2CEE, b"\x02"),
        ),
    )

    style_guid = bytes(range(16))
    style = _record(
        0x6B6C,
        _record(0x6B6D, style_guid) + _record(0x6B6E, b"Draft") + _record(0x6B6F, b"draft.style"),
    )
    styles = _record(
        0x0206,
        _record(
            0x6978,
            _record(0x6979, style) + _record(0x697A, b"\x03") + _record(0x697C, b"\x01"),
        ),
    )

    font = _record(
        0x5014,
        _record(0x5015, b"Liberation Sans")
        + _record(0x5016, b"\x01")
        + _record(0x5017, b"\x00")
        + _record(0x5018, b"\x0e")
        + _record(0x5019, b"\x01")
        + _record(0x501A, _f64(3.5)),
    )
    fonts = _record(
        0x01FD,
        _record(0x4E20, _record(0x4E21, font)),
    )
    text_style = _record(
        0x01FE,
        _record(
            0x57E4,
            _record(0x57E5, b"\x04") + _record(0x57EB, b"\x01") + _record(0x57EC, b"\x55"),
        ),
    )
    dimension_style = _record(
        0x01FF,
        _record(
            0x5FB4,
            _record(0x5FB5, b"\x04") + _record(0x5FB6, b"\x01") + _record(0x5FC3, _f64(0.75)),
        ),
    )

    line_style = _record(
        0x4076,
        _record(0x4077, b"Dashed")
        + _record(0x4078, b"-.-")
        + _record(0x4079, _f64(1.5))
        + _record(0x407A, _f64(2.5))
        + _record(0x407B, b"\x33")
        + _record(0x407C, b"\x00"),
    )
    line_styles = _record(
        0x0208,
        _record(
            0x4074,
            _record(0x4075, line_style),
        ),
    )

    provider = _record(
        0x61AA,
        _record(0x61AB, b"UnitsOptions")
        + _record(
            0x61AC,
            _record(0x61AD, b"LengthUnit"),
        ),
    )
    options = _record(
        0x0200,
        _record(
            0x61A8,
            _record(0x61A9, provider),
        ),
    )

    environment = _record(
        0x0210,
        _record(
            0x7918,
            _record(
                0x7919,
                _record(0x05DE, b"\x09") + _record(0x7B0D, b"Studio") + _record(0x2134, b"thumb.png"),
            ),
        ),
    )
    sun = _record(
        0x0213,
        _record(0x7D64, b"sun payload"),
    )
    axes = _record(
        0x01FC,
        _record(
            0x4650,
            _record(0x4651, _vec3(5, 6, 7)) + _record(0x4652, _vec3(0, 1, 0)) + _record(0x3FF0, b"\x03"),
        ),
    )

    # 0x0207 -> 0x6D60 -> 0x6D61 -> 0x7148 is the saved-scene hierarchy.
    scene = _record(
        0x7148,
        _record(
            0x6F54,
            _record(0x6F55, b"Presentation") + _record(0x6F56, b"Saved view"),
        )
        + _record(0x7149, b"\x05")
        + _record(0x714C, b"\x03")
        + _record(0x7152, b"\x00"),
    )
    scenes = _record(
        0x0207,
        _record(
            0x6D60,
            _record(0x6D61, scene),
        ),
    )

    root_payload = b"".join(
        (
            _record(0x01F5, b"\x00"),
            entities,
            layers,
            _record(0x01FA, _camera_record()),
            rendering,
            shadow,
            watermarks,
            styles,
            fonts,
            text_style,
            dimension_style,
            line_styles,
            options,
            environment,
            sun,
            axes,
            scenes,
        )
    )
    return _record(0x01F4, root_payload)


def test_parse_model_assembles_modern_metadata() -> None:
    """Assemble representative modern model blocks into the shared model."""
    header = _header()
    document = SkpDocument("synthetic.skp", header, [], None)
    with zipfile.ZipFile(io.BytesIO(), "w") as archive:
        model = parse_model(_model_data(), archive, header, document)

    assert model.entities.vertices[0].id == 11
    assert model.entities.vertices[0].position.to_tuple() == (1.0, 2.0, 3.0)
    assert model.layers[0].name == "Geometry"
    assert model.layers[0].visible is False
    assert model.layers[0].material_id == 42
    assert model.layers[0].material is not None
    assert model.layers[0].material.name == "Layer_Geometry"
    assert model.materials == []
    assert model.active_layer_id == 7

    camera = model.cameras[0]
    assert camera.name == "Saved camera"
    assert camera.eye.to_tuple() == (1.0, 2.0, 3.0)
    assert camera.is_perspective is False
    assert camera.allow_clipping is False
    assert camera.aspect_ratio == 16 / 9

    assert model.rendering_options is not None
    assert model.rendering_options.texture is False
    assert model.rendering_options.fog_start_dist == 12.5
    assert model.rendering_options.background_color == 0x44112233
    assert model.shadow_info is not None
    assert model.shadow_info.city == b"Sao Paulo"
    assert model.shadow_info.country == b"Brasil"
    assert model.shadow_info.display_shadows is True
    assert model.watermark_manager is not None
    assert model.watermark_manager.serialized_count == 2

    assert model.styles_registry is not None
    assert model.styles_registry.styles[0].display_name == "Draft"
    assert model.styles_registry.active_style_ref == 3
    assert model.styles_registry.selected_style_dirty is True
    assert model.fonts[0].face_name == "Liberation Sans"
    assert model.fonts[0].bold is True
    assert model.fonts[0].world_size == 3.5
    assert model.text_style is not None
    assert model.text_style.font_ref == 4
    assert model.text_style.display_leader is True
    assert model.dimension_style is not None
    assert model.dimension_style.text_3d is True
    assert model.dimension_style.hide_small_value == 0.75

    assert model.line_styles[0].dash_pattern == "-.-"
    assert model.line_styles[0].mutability is False
    assert model.options_manager is not None
    assert model.options_manager.providers[0].keys == {"LengthUnit": ""}
    assert model.environment_data is not None
    assert model.environment_data.selected is not None
    assert model.environment_data.selected.name == "Studio"
    assert model.environment_data.entries == [model.environment_data.selected]
    assert model.sun_data is not None
    assert model.sun_data.raw_payload == b"sun payload"
    assert model.model_view_axes is not None
    assert model.model_view_axes.origin == (5.0, 6.0, 7.0)
    assert model.model_view_axes.y_axis == (0.0, 1.0, 0.0)

    assert model.scenes[0].name == "Presentation"
    assert model.scenes[0].show_in_slideshow is False
    assert model.scenes[0].style_reference == 3


def test_metadata_parsers_default_incomplete_blocks() -> None:
    """Keep public defaults when an outer block has no expected record."""
    malformed = _record(0x7FFF, b"ignored")

    assert parse_cameras(malformed) == []
    assert _parse_shadow_info(malformed).latitude == 0.0
    assert _parse_watermarks(malformed).serialized_count == 0
    assert _parse_styles_registry(malformed).styles == []
    assert _parse_fonts(malformed) == []
    assert _parse_text_style(malformed).font_ref == 0
    assert _parse_dimension_style(malformed).font_ref == 0
    assert _parse_line_styles(malformed) == []
    assert _parse_options_manager(malformed).providers == []
    assert _parse_environment_data(malformed).selected is None
    assert _parse_sun_data(malformed).raw_payload is None
    assert _parse_model_view_axes(malformed).origin == (0.0, 0.0, 0.0)


def test_metadata_parsers_preserve_wire_defaults_for_missing_fields() -> None:
    """Keep record fallbacks distinct from new-object display defaults."""
    # 0x5FB4 is the dimension-style record.
    dimension = _parse_dimension_style(
        # An unknown child keeps the record present while all mapped fields are absent.
        _record(0x5FB4, _record(0x7FFF, b"ignored"))
    )
    line_styles = _parse_line_styles(
        # 0x4074 -> 0x4075 -> 0x4076 is record -> list -> one line style.
        _record(0x4074, _record(0x4075, _record(0x4076, b"")))
    )

    assert dimension.highlight_non_associative_color == 0
    assert dimension.color == 0
    assert dimension.text_color == 0
    assert line_styles[0].color == 0
    assert line_styles[0].stipple_scale == 1.0
    assert line_styles[0].line_width_points == 1.0
    assert line_styles[0].mutability is True


def test_camera_parser_skips_records_missing_required_vectors() -> None:
    """Reject partial cameras instead of inventing required geometry."""
    incomplete = _record(
        0x34BC,
        _record(0x34BD, _vec3(1, 2, 3)),
    )

    assert parse_cameras(incomplete) == []
