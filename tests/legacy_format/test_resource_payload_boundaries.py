# SPDX-License-Identifier: MIT
"""Legacy image, material, layer, style, and metadata boundary fixtures."""

from __future__ import annotations

import io
import struct
from types import SimpleNamespace

import pytest

from skppy.data_structure.layers import LayerFolder
from skppy.data_structure.model_metadata import LineStyle, RenderingOptions
from skppy.parser_legacy.binary import (
    ArchiveObjectHandle,
    ArchiveObjectTag,
    LegacyArchiveReader,
)
from skppy.parser_legacy.camera_payloads import (
    _try_read_inline_dib,
    read_camera,
    read_root_camera_section,
)
from skppy.parser_legacy.geometry_payloads import (
    read_curve_payload,
    read_drawing_element_body,
    read_section_plane_payload,
)
from skppy.parser_legacy.image_payloads import (
    looks_like_dib_image,
    read_dib_preview,
    read_dib_payload,
    read_texture,
    read_texture_body,
    read_texture_preview,
    read_thumbnail,
    read_thumbnail_body,
    skip_dib_payload,
)
from skppy.parser_legacy.layer_payloads import (
    read_layer_manager,
    read_layer_manager_body,
    read_layer_manager_preview,
    read_layer_preview,
    read_layer_group,
)
from skppy.parser_legacy.line_style_payloads import (
    read_custom_line_style,
    read_line_style_manager,
)
from skppy.parser_legacy.material_payloads import (
    read_material_manager_body,
    read_material_payload,
    read_material_preview,
)
from skppy.parser_legacy.metadata_payloads import (
    _read_npr_edge,
    _read_style_variant,
    read_axes_payload,
    read_dimension_style_payload,
    read_font_manager_body,
    read_font_payload,
    read_shadow_payload,
    read_style_manager_body,
    read_style_payload,
    read_text_style_fields,
)
from skppy.parser_legacy.parser_types import DibState, EntityHeaderState
from skppy.parser_legacy.rendering_options import (
    _RenderingValues,
    _read_appended_rendering_fields,
    read_rendering_options_payload,
)

from ._fixtures import (
    _camera_payload_bytes,
    _layer_preview_payload_bytes,
    _legacy_string,
    _material_preview_bytes,
    _new_class_tag,
    _texture_preview_payload_bytes,
)


def _reader(data: bytes = b"") -> LegacyArchiveReader:
    return LegacyArchiveReader(io.BytesIO(data))


def _entity_header() -> EntityHeaderState:
    return EntityHeaderState(3, 0, None, None, None, 0)


def test_camera_schema_requirements_tagged_read_and_inline_dib_recovery():
    with pytest.raises(ValueError, match="requires a CCamera schema"):
        read_root_camera_section(io.BytesIO(), model_class_version=21, camera_class_version=None)
    with pytest.raises(ValueError, match="requires a CCamera schema"):
        read_root_camera_section(io.BytesIO(), model_class_version=11, camera_class_version=None)

    camera = read_camera(
        io.BytesIO(_new_class_tag("CCamera", schema=5) + _camera_payload_bytes()),
        camera_class_version=5,
    )
    assert camera.eye.to_tuple() == (10.0, 20.0, 30.0)

    tag = ArchiveObjectTag("new_class", 0xFFFF, schema=3, class_name="CDib")
    truncated = io.BytesIO(b"\x01")
    assert _try_read_inline_dib(truncated, object_tag=tag) is None
    assert truncated.tell() == 0

    unrecognized = io.BytesIO(struct.pack("<II", 4, 1) + b"x")
    assert _try_read_inline_dib(unrecognized, object_tag=tag) is None
    assert unrecognized.tell() == 0


def test_dib_preview_trailing_scalar_signatures_and_skip_paths():
    preview = read_dib_preview(
        io.BytesIO(_new_class_tag("CDib", schema=3) + struct.pack("<II", 1, 3) + b"PNG" + struct.pack("<I", 7)),
        dib_class_version=3,
    )
    assert preview.trailing_u32 == 7
    assert looks_like_dib_image(preview)

    empty = read_dib_payload(io.BytesIO(), object_tag=ArchiveObjectTag("null", 0), dib_class_version=0)
    assert not looks_like_dib_image(empty)
    stream = io.BytesIO(b"unchanged")
    skip_dib_payload(stream, class_version=None)
    assert stream.tell() == 0
    stream = io.BytesIO(struct.pack("<II", 1, 3) + b"PNG" + struct.pack("<I", 9))
    skip_dib_payload(stream, class_version=3)
    assert stream.tell() == len(stream.getvalue())


def test_thumbnail_and_texture_version_paths():
    with pytest.raises(NotImplementedError, match="CThumbnail"):
        read_thumbnail_body(_reader(), class_version=2, read_object=lambda: None)
    calls = iter((object(), DibState(ArchiveObjectTag("null", 0), 3, 0, 4, b"PNG", None, 0)))
    assert read_thumbnail_body(_reader(), class_version=1, read_object=lambda: next(calls)) == b"PNG"
    with pytest.raises(NotImplementedError, match="CTexture"):
        read_texture_body(_reader(), class_version=5, dib=None)

    texture = read_texture_preview(
        io.BytesIO(_texture_preview_payload_bytes()),
        entity_class_version=3,
        texture_class_version=6,
        class_versions={"CDib": 3},
    )
    assert texture.data == b"PNG"


def test_thumbnail_old_camera_context_adapter_and_inline_texture_paths():
    old_camera = (
        struct.pack("<9d", *range(9))
        + struct.pack("<2d", 0.1, 100.0)
        + b"\x01"
        + struct.pack("<2d", 35.0, 20.0)
        + struct.pack("<3d", 0.0, 0.0, 0.0)
    )
    dib = DibState(ArchiveObjectTag("null", 0), 3, 0, 4, b"PNG", None, 0)
    assert read_thumbnail_body(_reader(old_camera), class_version=0, read_object=lambda: dib) == b"PNG"

    objects = iter((object(), dib))
    thumbnail_context = SimpleNamespace(
        session=SimpleNamespace(reader=_reader()),
        read_entity=lambda: None,
        read_object=lambda: (ArchiveObjectTag("null", 0), next(objects)),
    )
    assert read_thumbnail(thumbnail_context, class_version=1) == b"PNG"

    texture_body = (
        struct.pack("<II", 4, 3)
        + b"PNG"
        + struct.pack("<2d", 2.0, 3.0)
        + _legacy_string("old.png")
        + bytes((1, 2, 3, 255))
    )
    stream = io.BytesIO(b"\x01" + texture_body)
    texture_context = SimpleNamespace(
        session=SimpleNamespace(stream=stream, reader=_reader(stream.getvalue())),
        class_versions={"CDib": 3},
    )
    # One reader must share the stream cursor with the nested CDib reader.
    texture_context.session.reader = LegacyArchiveReader(stream)
    texture = read_texture(texture_context, class_version=4)
    assert (texture.filename, texture.data) == ("old.png", b"PNG")

    preview = read_texture_preview(
        io.BytesIO(b"\x01" + texture_body),
        entity_class_version=3,
        texture_class_version=4,
        class_versions={"CDib": 3},
    )
    assert preview.data == b"PNG"


def test_geometry_reference_and_versioned_name_branches():
    references = []
    body = read_drawing_element_body(
        _reader(b"\x00\x01"),
        2,
        read_reference=lambda: references.append(True) or ArchiveObjectTag("null", 0),
    )
    assert references == [True] and body[-1] is None

    curve_refs = []
    curve = read_curve_payload(
        _reader(b"\x01" + struct.pack("<I", 2)),
        class_version=3,
        read_reference=lambda: curve_refs.append(True) or ArchiveObjectTag("null", 0),
    )
    assert len(curve_refs) == 2 and curve.edge_ids == [0, 0]

    plane = read_section_plane_payload(
        _reader(struct.pack("<4d", 0.0, 0.0, 1.0, 0.0) + _legacy_string("Cut") + _legacy_string("A")),
        class_version=3,
        file_version="18.0",
    )
    assert (plane.name, plane.symbol) == ("Cut", "A")


def test_material_preview_payload_and_manager_version_guards():
    material = read_material_preview(
        io.BytesIO(_material_preview_bytes()),
        entity_class_version=3,
        material_class_version=12,
    )
    assert material.material.name == "Layer_Layer0"
    with pytest.raises(NotImplementedError, match="CMaterial version"):
        read_material_payload(
            _reader(),
            class_version=11,
            payload_start_offset=0,
            entity_header=_entity_header(),
            read_texture=lambda: None,
        )
    with pytest.raises(NotImplementedError, match="CMaterialManager"):
        read_material_manager_body(_reader(), class_version=3, read_object=lambda: None)


def test_layer_preview_manager_folders_and_group_version_guard():
    layer = read_layer_preview(
        io.BytesIO(b"\x00\x00" + _layer_preview_payload_bytes("Layer", hidden=False, flags=3)),
        entity_class_version=3,
        layer_class_version=2,
        material_class_version=12,
    )
    assert layer.layer.name == "Layer"

    manager = read_layer_manager_preview(
        io.BytesIO(b"\x00\x00" + struct.pack("<I", 0)),
        entity_class_version=3,
        layer_manager_class_version=4,
        layer_class_version=2,
        material_class_version=12,
    )
    assert manager[0] == ()

    folder = LayerFolder(name="Folder")
    manager = read_layer_manager_body(
        _reader(struct.pack("<II", 0, 1)),
        class_version=6,
        payload_start_offset=0,
        read_layer=lambda: None,
        read_reference=lambda: ArchiveObjectTag("null", 0),
        read_layer_group=lambda: folder,
    )
    assert manager[2] == (folder,)
    with pytest.raises(ValueError, match="requires a root CLayerGroup"):
        read_layer_manager_body(
            _reader(struct.pack("<I", 0)),
            class_version=7,
            payload_start_offset=0,
            read_layer=lambda: None,
            read_reference=lambda: ArchiveObjectTag("null", 0),
        )

    context = SimpleNamespace(class_versions={"CLayerGroup": 4})
    with pytest.raises(NotImplementedError, match="CLayerGroup"):
        read_layer_group(context)


def test_layer_manager_object_groups_and_layer_group_handles():
    folder = LayerFolder(name="Folder")

    def manager_context(value):
        return SimpleNamespace(
            session=SimpleNamespace(reader=_reader(struct.pack("<II", 0, 1))),
            read_entity=lambda: None,
            read_object=lambda: (ArchiveObjectTag("null", 0), value),
            read_reference=lambda: ArchiveObjectTag("null", 0),
        )

    assert read_layer_manager(manager_context(folder), class_version=6)[2] == (folder,)
    with pytest.raises(ValueError, match="Expected a CLayerGroup"):
        read_layer_manager(manager_context(object()), class_version=6)

    handle = ArchiveObjectHandle(
        "object_ref",
        ArchiveObjectTag("object_ref", 9, index=9),
        9,
        None,
        "CLayer",
        3,
    )
    group_context = SimpleNamespace(
        class_versions={"CLayerGroup": 1},
        session=SimpleNamespace(reader=_reader(_legacy_string("Group") + struct.pack("<II", 0, 1))),
        read_entity=lambda: None,
        read_handle=lambda: (handle, object()),
    )
    group = read_layer_group(group_context)
    assert group.child_layer_ids == [9]


def _line_context(data: bytes, objects=()):
    values = iter(objects)
    return SimpleNamespace(
        session=SimpleNamespace(reader=_reader(data)),
        read_entity=lambda: None,
        read_object=lambda: (ArchiveObjectTag("null", 0), next(values)),
    )


def test_line_style_schema_variants_and_manager_filtering():
    with pytest.raises(NotImplementedError, match="CCustomLineStyle"):
        read_custom_line_style(_line_context(b""), class_version=0)

    v1 = read_custom_line_style(
        _line_context(_legacy_string("Dash") + struct.pack("<Hd", 12, 1.5)),
        class_version=1,
    )
    assert v1.dash_pattern == "12"

    v4 = read_custom_line_style(
        _line_context(_legacy_string("Color") + _legacy_string("--") + struct.pack("<ddIB", 1.0, 2.0, 0xAABBCCDD, 1)),
        class_version=4,
    )
    assert v4.color == 0xAABBCCDD and v4.mutability is True

    manager = read_line_style_manager(_line_context(struct.pack("<I", 2), objects=(object(), LineStyle(name="kept"))))
    assert [style.name for style in manager] == ["kept"]


@pytest.mark.parametrize(
    ("function", "kwargs", "message"),
    [
        (read_font_payload, {"class_version": 2}, "CSkFont"),
        (
            read_font_manager_body,
            {"class_version": 1, "read_object": lambda: None},
            "CFontManager",
        ),
        (
            read_style_payload,
            {"class_version": 3, "read_object": lambda: None},
            "CSkpStyle",
        ),
        (
            read_style_manager_body,
            {
                "class_version": 1,
                "read_object": lambda: None,
                "read_tagged_object": lambda: None,
            },
            "CSkpStyleManager",
        ),
        (read_text_style_fields, {"class_version": 3}, "CTextStyle"),
        (
            read_dimension_style_payload,
            {"class_version": 3, "font_ref": 0},
            "CDimensionStyle",
        ),
        (read_axes_payload, {"class_version": 1}, "CSketchCS"),
        (read_shadow_payload, {"class_version": 6}, "CShadowInfo"),
        (read_rendering_options_payload, {"class_version": 999}, "CRenderingOptions"),
    ],
)
def test_metadata_readers_reject_unmapped_schemas(function, kwargs, message):
    with pytest.raises(NotImplementedError, match=message):
        function(_reader(), **kwargs)


@pytest.mark.parametrize(
    ("value_type", "payload", "expected"),
    [
        (0, b"", None),
        (1, b"\x07", 7),
        (3, struct.pack("<H", 8), 8),
        (4, struct.pack("<I", 9), 9),
        (6, struct.pack("<f", 1.5), pytest.approx(1.5)),
        (7, struct.pack("<d", 2.5), 2.5),
        (9, struct.pack("<3d", 1.0, 2.0, 3.0), (1.0, 2.0, 3.0)),
        (12, struct.pack("<16d", *range(16)), tuple(float(i) for i in range(16))),
    ],
)
def test_style_variant_scalar_types(value_type, payload, expected):
    value = _read_style_variant(_reader(struct.pack("<II", 1, value_type) + payload))
    assert value == expected


def test_style_variant_unknown_and_npr_edge_versions():
    with pytest.raises(ValueError, match="Variant type"):
        _read_style_variant(_reader(struct.pack("<II", 1, 99)))

    legacy = struct.pack("<IIIII", 1, 0, 0, 0, 0) + b"\x00" + struct.pack("<III", 0, 0, 0)
    _read_npr_edge(_reader(legacy), read_object=lambda: None)
    modern = struct.pack("<IddI", 2, 1.0, 2.0, 0) + b"\x00" + struct.pack("<IIII", 0, 0, 0, 0)
    _read_npr_edge(_reader(modern), read_object=lambda: None)

    resolved = []
    counted = struct.pack("<IddI", 2, 1.0, 2.0, 0) + b"\x00" + struct.pack("<IIIII", 0, 0, 1, 7, 1)
    _read_npr_edge(_reader(counted), read_object=lambda: resolved.append(True))
    assert resolved == [True]


def test_style_file_fallback_object_options_and_rendering_boundary_tails():
    npr = struct.pack("<IddI", 2, 1.0, 2.0, 0) + b"\x00" + struct.pack("<IIII", 0, 0, 0, 1)
    payload = b"".join(
        [
            b"g" * 16,
            _legacy_string("initial.style"),
            struct.pack("<I", 3),
            _legacy_string("Display"),
            _legacy_string(""),
            struct.pack("<II", 2, 0x3F5),
            npr,
            struct.pack("<II", 0x1389, 1),
        ]
    )
    objects = []
    style = read_style_payload(_reader(payload), class_version=2, read_object=lambda: objects.append(True))
    assert style.file_name == "initial.style"
    assert objects == [True, True]

    values = _RenderingValues(_reader(b"\x01"), RenderingOptions())
    _read_appended_rendering_fields(values, 23)

    options = RenderingOptions()
    values = _RenderingValues(_reader(bytes((1, 2, 3, 4, 1, 0))), options)
    _read_appended_rendering_fields(values, 33)
    assert options.display_watermarks is True
