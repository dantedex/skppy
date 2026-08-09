# SPDX-License-Identifier: MIT
"""Shared binary fixture builders for SketchUp legacy parser tests."""

# ruff: noqa: F401

from __future__ import annotations

import struct
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import skppy
import skppy.parser_legacy.parser_types as parser_types
import skppy.parser_legacy.scene_pages as scene_pages
from skppy.data_structure.construction import Camera, SectionPlane, ShadowInfo
from skppy.data_structure.entities import (
    ArcCurve,
    ComponentDefinition,
    ComponentInstance,
    Curve,
    Entities,
    Face,
    Group,
    Image,
)
from skppy.data_structure.images import Texture
from skppy.data_structure.layers import LayerFolder
from skppy.data_structure.materials import Color
from skppy.data_structure.model import Model
from skppy.data_structure.scene_data import PageBackgroundImage, Scene
from skppy.data_structure.model_metadata import (
    AttributeDictionary,
    DimensionStyle,
    Font,
    LineStyle,
    ModelViewAxes,
    OptionsManager,
    OptionsProvider,
    RenderingOptions,
    StyleDescriptor,
    StylesRegistry,
    TextStyle,
    Watermark,
    WatermarkManager,
)
from skppy.parser_legacy.geometry_readers import (
    read_edge_preview,
    read_edge_preview_from_session,
    read_edge_use_preview,
    read_face_preview,
    read_loop_preview,
)
from skppy.parser_legacy.object_dispatch import (
    read_supported_object,
)
from skppy.parser_legacy.base_payloads import read_root_model_prefix
from skppy.parser_legacy.camera_payloads import read_camera_section
from skppy.parser_legacy.class_support import (
    SUPPORTED_PRE_ZIP_OBJECT_CLASSES,
    SUPPORTED_LEGACY_OBJECT_CLASSES,
)
from skppy.parser_legacy.parser_types import (
    EdgeState,
    LayerState,
    MaterialState,
    SceneState,
    ComponentBehaviorState,
    ComponentDefinitionState,
)
from skppy.parser_legacy.binary import (
    ArchiveIndexTable,
    ArchiveObjectHandle,
    ArchiveObjectTag,
    LegacyArchiveReader,
)
from skppy.parser_legacy.diagnostics import (
    diagnose_legacy_bytes,
    diagnose_legacy_class_coverage_bytes,
    diagnose_legacy_runtime_classes_bytes,
)
from skppy.parser_legacy.errors import (
    UnsupportedLegacySchemaError,
    UnsupportedLegacyObjectError,
)
from skppy.parser_legacy.root_payloads import read_post_rendering_model_data
from skppy.parser_legacy.session import LegacyArchiveSession
from skppy.parser_legacy.parser import (
    _seed_known_archive_entries,
    parse_legacy_bytes,
)
from skppy.parser_legacy.component_builder import populate_definitions
from skppy.parser_legacy.entity_builder import populate_root_entities
from skppy.parser_legacy.provenance import ArchiveProvenance
from skppy.parser_legacy.model_builder import ModelBuilder
from skppy.parser_legacy.model_tail import ModelTailState
from skppy.parser_legacy.schema import (
    ArchiveSchema,
    LEGACY_CLASS_SCHEMAS,
    SketchUpFormatVersion,
)
from skppy.parser_legacy.recovery import (
    _scan_model_view_axes,
    _scan_scene_previews,
    _scan_shadow_info,
    scan_font_previews,
    scan_style_previews,
)
from skppy.parser_legacy.scene_pages import read_view_page_preview_from_span


def _legacy_file_bytes(
    saved_path: str,
    *,
    root_entity_count: int = 0,
    root_entity_payload: bytes = b"",
    extra_version_entries: list[tuple[str, int]] | None = None,
    trailing_archive_payload: bytes = b"",
) -> bytes:
    entries = [
        ("CAttributeContainer", 0),
        ("CAttributeNamed", 1),
        ("CCamera", 5),
        ("CEntity", 3),
        ("CComponentBehavior", 5),
        ("CComponent", 11),
        ("CDrawingElement", 9),
        ("CMaterialManager", 4),
        ("CDefinitionList", 0),
        ("CRenderingOptions", 36),
        ("CShadowInfo", 7),
        ("CPageList", 1),
        ("CSketchCS", 0),
        ("CDimensionStyle", 4),
        ("CTextStyle", 5),
        ("CFontManager", 0),
        ("CSkpStyleManager", 2),
        ("CWatermarkManager", 2),
        ("CLayer", 2),
        ("CLayerManager", 4),
        ("CMaterial", 12),
        ("CEdge", 2),
        ("CVertex", 0),
        ("CSketchUpModel", 22),
    ]
    entries.extend(extra_version_entries or [])
    entries.append(("End-Of-Version-Map", 0))
    version_map = bytearray(b"\xff\xff\x00\x00")
    version_map += struct.pack("<H", len("CVersionMap"))
    version_map += b"CVersionMap"
    for class_name, version in entries:
        version_map += _legacy_string(class_name)
        version_map += struct.pack("<I", version)

    return b"".join(
        [
            _legacy_string("SketchUp Model"),
            _legacy_string("{8.0.1}"),
            bytes(range(16)),
            _legacy_string(saved_path),
            struct.pack("<I", 1_700_000_000),
            bytes(version_map),
            _root_model_prefix_bytes(),
            _component_behavior_bytes(),
            _legacy_string(""),
            _options_manager_bytes(),
            _model_properties_bytes(),
            _camera_section_bytes(),
            _rendering_options_bytes(),
            _post_rendering_model_data_bytes(),
            _layer_manager_prefix_bytes(),
            struct.pack("<I", 0),
            struct.pack("<I", root_entity_count),
            root_entity_payload,
            struct.pack("<I", 0),
            b"\x00\x00",
            _model_tail_bytes(),
            trailing_archive_payload,
            b"ARCHIVE",
        ]
    )


def _legacy_string(text: str) -> bytes:
    # CArchive strings use a UTF-16 BOM, 0xFF marker, then a compact code-unit
    # count. This is intentionally encoded here instead of by parser helpers.
    payload = text.encode("utf-16le")
    code_units = len(text)
    if code_units < 0xFF:
        prefix = b"\xff\xfe\xff" + bytes([code_units])
    else:
        prefix = b"\xff\xfe\xff\xff" + struct.pack("<H", code_units)
    return prefix + payload


def _root_model_prefix_bytes() -> bytes:
    return b"".join(
        [
            struct.pack("<I", 1),
            struct.pack("<I", 0x4B0),
            struct.pack("<I", 0),
            b"\x00\x00",
            b"\x01",
        ]
    )


def _component_behavior_bytes(
    *,
    is_2d: bool = False,
    cuts_opening: bool = False,
    snap_to: int = 0,
    always_face_camera: bool = False,
    shadows_face_sun: bool = False,
    no_scale_mask: int = 0,
) -> bytes:
    # The two camera-facing booleans share bits 0 and 1 of one serialized byte.
    camera_flags = int(always_face_camera) | (int(shadows_face_sun) << 1)
    return b"".join(
        [
            b"\x00\x00",
            bytes([is_2d]),
            bytes([cuts_opening]),
            struct.pack("<I", snap_to),
            bytes([camera_flags]),
            struct.pack("<I", no_scale_mask),
        ]
    )


def _options_manager_bytes() -> bytes:
    return b"".join(
        [
            struct.pack("<I", 3),
            struct.pack("<I", 1),
            _legacy_string("PageOptions"),
            _legacy_string("ShowTransition"),
            b"\x07\x01",
            _legacy_string("TransitionTime"),
            b"\x06",
            struct.pack("<d", 1.5),
            _legacy_string(""),
        ]
    )


def _model_properties_bytes() -> bytes:
    return b"".join(
        [
            _new_class_tag("CAttributeContainer", schema=0),
            b"\x00\x00",
            _new_class_tag("CAttributeNamed", schema=1),
            b"\x00\x00",
            struct.pack("<I", 0),
            _legacy_string("ModelProperties"),
            _legacy_string("IsClassified"),
            b"\x07\x00",
            _legacy_string(""),
            struct.pack("<I", 0),
            b"\x00\x00",
        ]
    )


def _camera_section_bytes() -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            _new_class_tag("CCamera", schema=5),
            _camera_payload_bytes(),
        ]
    )


def _camera_payload_bytes(class_version: int = 5) -> bytes:
    camera_values = [
        (10.0, 20.0, 30.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    return b"".join(
        [
            *(struct.pack("<3d", *values) for values in camera_values),
            struct.pack("<d", 35.0),
            struct.pack("<d", 45.0),
            b"\x01",
            struct.pack("<d", 0.1),
            struct.pack("<d", 1000.0),
            struct.pack("<3d", 0.0, 0.0, 0.0),
            struct.pack("<d", 1.0),
            b"\x00",
            b"\x01",
            _legacy_string(""),
            struct.pack("<d", 2.0),
            b"\x00" if class_version > 4 else b"",
            struct.pack("<d", 3.0) if class_version > 4 else b"",
            struct.pack("<d", 4.0) if class_version > 4 else b"",
            struct.pack("<d", 5.0) if class_version > 4 else b"",
        ]
    )


def _rendering_options_bytes(class_version: int = 36) -> bytes:
    payload = bytearray(b"\x00\x00")
    payload += struct.pack("<I", 2)
    payload += b"\x01\x00\x01"
    if class_version > 37:
        payload += b"\x01"
    payload += struct.pack("<I", 1)
    payload += _rgba(255, 255, 255, 255)
    payload += _rgba(128, 128, 128, 255)
    payload += _rgba(0, 0, 0, 255)
    payload += _rgba(64, 64, 64, 255)
    payload += b"\x01\x00\x01\x00"
    payload += struct.pack("<I", 8)
    payload += b"\x01" + struct.pack("<I", 3)
    payload += b"\x00" + struct.pack("<I", 4)
    if class_version >= 26:
        payload += b"\x01" + struct.pack("<I", 5)
        payload += b"\x00" + struct.pack("<I", 6)
        if class_version >= 28:
            payload += b"\x01"
    payload += b"\x00"
    if class_version >= 39:
        payload += b"\x00"
    payload += struct.pack("<I", 0)
    payload += _rgba(225, 225, 200, 255)
    payload += _rgba(128, 128, 200, 255)
    payload += struct.pack("<2d", 0.75, 0.5)
    payload += b"\x00\x01"
    if class_version >= 29:
        payload += b"\x00" + _rgba(255, 0, 0, 255) + b"\x01"
        payload += struct.pack("<2d", 0.25, 0.125)
        if class_version != 29:
            payload += struct.pack("<I", 50)
        if class_version > 30:
            payload += struct.pack("<I", 2) + b"\x01\x00\x01\x00"
    payload += _rgba(192, 192, 192, 255)
    if class_version >= 24:
        payload += _rgba(255, 0, 0, 255)
    payload += _rgba(0, 255, 0, 255)
    payload += b"\x01\x01\x00" + struct.pack("<I", 4)
    payload += _rgba(3, 0, 0, 0)
    payload += _rgba(1, 0, 0, 0)
    payload += _rgba(2, 0, 0, 0)
    payload += struct.pack("<2I", 1, 2)
    if class_version > 36:
        payload += _rgba(4, 5, 6, 255) + b"\x01"
    payload += struct.pack("<I", 3)
    payload += b"\x01" + struct.pack("<d", 0.33) + b"\x00"
    if class_version <= 22:
        return bytes(payload)
    if class_version in {23, 24}:
        return bytes(payload + b"\x00")
    if class_version < 27:
        return bytes(payload)
    payload += _rgba(1, 2, 3, 4)
    if class_version < 32:
        return bytes(payload)
    payload += b"\x01"
    if class_version == 33:
        return bytes(payload + b"\x00")
    if class_version < 35:
        return bytes(payload)
    payload += struct.pack("<d", 0.66)
    if class_version == 35:
        return bytes(payload)
    payload += b"\x01\x00" + struct.pack("<d", 0.99)
    payload += b"\x01" + struct.pack("<d", 1.2)
    return bytes(payload)


def _rgba(red: int, green: int, blue: int, alpha: int) -> bytes:
    return bytes((red, green, blue, alpha))


def _post_rendering_model_data_bytes() -> bytes:
    return b"".join(
        [
            struct.pack("<I", 0),
            struct.pack("<I", 1),
            b"\x00\x00",
            b"\x00\x00",
            b"\x00\x00\x00\x00\x00\x00",
            b"\x00\x00",
            b"\x00\x00",
            struct.pack("<I", 0),
            b"\x00\x00",
        ]
    )


def _layer_manager_prefix_bytes() -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            struct.pack("<I", 1),
            _new_class_tag("CLayer", schema=2),
            b"\x00\x00",
            _legacy_string("Layer0"),
            b"\x00",
            _material_preview_bytes(),
            struct.pack("<I", 0),
            struct.pack("<H", 10),
        ]
    )


def _model_tail_bytes() -> bytes:
    dimension_style = b"".join(
        [
            b"\x00\x00",
            struct.pack("<I", 0),
            b"\x00\x00",
            b"\x01\x00",
            struct.pack("<IIIII", 10, 11, 12, 13, 14),
            b"\x01",
            _rgba(10, 20, 30, 255),
            b"\x00\x01",
            struct.pack("<d", 1.25),
            b"\x00",
            struct.pack("<d", 2.5),
            _rgba(40, 50, 60, 255),
            _rgba(70, 80, 90, 255),
            struct.pack("<I", 15),
        ]
    )
    text_style = b"".join(
        [
            b"\x00\x00",
            b"\x00\x00",
            struct.pack("<II", 2, 3),
            b"\x01",
            struct.pack("<I", 4),
            b"\x00",
            _rgba(10, 20, 30, 255),
            _rgba(40, 50, 60, 255),
            b"\x00\x00",
        ]
    )
    return b"".join(
        [
            _shadow_info_payload_bytes(),
            b"\x00\x00",
            struct.pack("<I", 0),
            b"\x00\x00",
            _drawing_element_payload_bytes(),
            _sketch_cs_payload_bytes(),
            bytes(16 * 4),
            dimension_style,
            text_style,
            b"\x00\x00",
            struct.pack("<I", 0),
            b"\x00\x00",
            b"\x00\x00",
            struct.pack("<I", 0),
            b"\x00\x00",
            struct.pack("<I", 0),
            struct.pack("<I", 0),
            b"\x01",
        ]
    )


def _material_preview_bytes(
    name: str = "Layer_Layer0",
    texture_payload: bytes | None = None,
    *,
    transparency: float = 0.5,
    use_transparency: bool = False,
) -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            _legacy_string(name),
            b"\x01" if texture_payload is not None else b"\x00",
            texture_payload or b"",
            b"\x01",
            _rgba(255, 84, 84, 255),
            _legacy_string(""),
            struct.pack("<I", 0),
            struct.pack("<I", 0),
            struct.pack("<d", transparency),
            b"\x01" if use_transparency else b"\x00",
        ]
    )


def _layer_preview_payload_bytes(name: str, *, hidden: bool, flags: int) -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            _legacy_string(name),
            b"\x01" if hidden else b"\x00",
            _material_preview_bytes(name=f"{name} Material"),
            struct.pack("<I", flags),
        ]
    )


def _named_attribute_payload_bytes(attribute_name: str, key: str) -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            struct.pack("<I", 0),
            _legacy_string(attribute_name),
            _legacy_string(key),
            b"\x07\x01",
            _legacy_string(""),
            struct.pack("<I", 0),
        ]
    )


def _texture_preview_payload_bytes() -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            _new_class_tag("CDib", schema=3),
            _dib_preview_payload_bytes(),
            struct.pack("<d", 12.0),
            struct.pack("<d", 24.0),
            _legacy_string("texture.png"),
            _rgba(10, 20, 30, 255),
        ]
    )


def _dib_preview_payload_bytes() -> bytes:
    return b"".join(
        [
            struct.pack("<I", 4),
            struct.pack("<I", 3),
            b"PNG",
        ]
    )


def _new_class_tag(class_name: str, *, schema: int) -> bytes:
    # 0xFFFF declares a runtime class: u16 schema, u16 ASCII length, then name.
    return b"".join(
        [
            b"\xff\xff",
            struct.pack("<H", schema),
            struct.pack("<H", len(class_name)),
            class_name.encode("ascii"),
        ]
    )


def _class_ref_tag(index: int) -> bytes:
    # The high bit marks an existing runtime class that introduces a new object.
    return struct.pack("<H", 0x8000 | index)


def _object_ref_tag(index: int) -> bytes:
    # A plain nonzero 15-bit value refers to an existing object-table entry.
    return struct.pack("<H", index)


def _read_object_tags(data: bytes):
    reader = LegacyArchiveReader(io.BytesIO(data))
    tags = []
    while reader.tell() < len(data):
        tags.append(reader.read_object_tag())
    return tags


def _edge_preview_bytes(*, hidden: bool = False, soft: bool = False, smooth: bool = False) -> bytes:
    return b"".join(
        [
            _new_class_tag("CEdge", schema=2),
            b"\x00\x00",
            b"\x00\x00",
            bytes([hidden]),
            b"\x01",
            b"\x01",
            bytes([soft]),
            bytes([smooth]),
            b"\x00",
            b"\x00\x00",
            _new_class_tag("CVertex", schema=0),
            b"\x00\x00",
            struct.pack("<3d", 0.0, 0.0, 0.0),
            _class_ref_tag(13),
            b"\x00\x00",
            struct.pack("<3d", 10.0, 10.0, 10.0),
            b"\x00\x00",
        ]
    )


def _edge_preview_with_curve_bytes() -> bytes:
    return b"".join(
        [
            _new_class_tag("CEdge", schema=2),
            b"\x00\x00",
            b"\x00\x00",
            b"\x00",
            b"\x01",
            b"\x01",
            struct.pack("<I", 0),
            b"\x00",
            _new_class_tag("CVertex", schema=0),
            b"\x00\x00",
            struct.pack("<3d", 0.0, 0.0, 0.0),
            _class_ref_tag(3),
            b"\x00\x00",
            struct.pack("<3d", 10.0, 0.0, 0.0),
            _new_class_tag("CCurve", schema=4),
            b"\x00\x00",
            b"\x01",
            struct.pack("<I", 3),
        ]
    )


def _arc3d_preview_payload_bytes() -> bytes:
    return b"".join(
        [
            struct.pack("<3d", 1.0, 2.0, 3.0),
            struct.pack("<3d", 0.0, 0.0, 1.0),
            struct.pack("<3d", 1.0, 0.0, 0.0),
            struct.pack("<d", 0.25),
            struct.pack("<d", 1.25),
            struct.pack("<3d", 0.0, 1.0, 0.0),
        ]
    )


def _nested_face_preview_bytes() -> bytes:
    return b"".join(
        [
            _new_class_tag("CFace", schema=3),
            b"\x00\x00",
            b"\x00\x00",
            b"\x00",
            b"\x01",
            b"\x01",
            struct.pack("<I", 0),
            b"\x00",
            struct.pack("<4d", 0.0, 0.0, 1.0, 0.0),
            struct.pack("<I", 1),
            _new_class_tag("CLoop", schema=1),
            b"\x00\x00",
            b"\x01",
            b"\x00",
            _new_class_tag("CEdgeUse", schema=1),
            b"\x00\x00",
            _new_class_tag("CEdge", schema=2),
            b"\x00\x00",
            b"\x00\x00",
            b"\x00",
            b"\x01",
            b"\x01",
            struct.pack("<I", 0),
            b"\x00",
            _new_class_tag("CVertex", schema=0),
            b"\x00\x00",
            struct.pack("<3d", 0.0, 0.0, 0.0),
            _class_ref_tag(9),
            b"\x00\x00",
            struct.pack("<3d", 10.0, 0.0, 0.0),
            b"\x00\x00",
            b"\x00",
            _object_ref_tag(4),
            b"\x00\x00",
            b"\x00\x00",
        ]
    )


def _nested_triangle_face_preview_bytes() -> bytes:
    return b"".join(
        [
            _new_class_tag("CFace", schema=3),
            b"\x00\x00",
            b"\x00\x00",
            b"\x00",
            b"\x01",
            b"\x01",
            struct.pack("<I", 0),
            b"\x00",
            struct.pack("<4d", 0.0, 0.0, 1.0, 0.0),
            struct.pack("<I", 1),
            _new_class_tag("CLoop", schema=1),
            b"\x00\x00",
            b"\x01",
            b"\x00",
            _new_class_tag("CEdgeUse", schema=1),
            b"\x00\x00",
            _new_class_tag("CEdge", schema=2),
            _edge_payload_bytes(
                (0.0, 0.0, 0.0),
                (10.0, 0.0, 0.0),
                _new_class_tag("CVertex", schema=0),
                _class_ref_tag(19),
            ),
            b"\x00",
            _object_ref_tag(14),
            _class_ref_tag(15),
            b"\x00\x00",
            _class_ref_tag(17),
            _edge_payload_bytes(
                (10.0, 0.0, 0.0),
                (0.0, 10.0, 0.0),
                _class_ref_tag(19),
                _class_ref_tag(19),
            ),
            b"\x00",
            _object_ref_tag(14),
            _class_ref_tag(15),
            b"\x00\x00",
            _class_ref_tag(17),
            _edge_payload_bytes(
                (0.0, 10.0, 0.0),
                (0.0, 0.0, 0.0),
                _class_ref_tag(19),
                _class_ref_tag(19),
            ),
            b"\x00",
            _object_ref_tag(14),
            b"\x00\x00",
            b"\x00\x00",
        ]
    )


def _edge_payload_bytes(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    start_vertex_tag: bytes,
    end_vertex_tag: bytes,
) -> bytes:
    return b"".join(
        [
            _drawing_element_payload_bytes(),
            start_vertex_tag,
            b"\x00\x00",
            struct.pack("<3d", *start),
            end_vertex_tag,
            b"\x00\x00",
            struct.pack("<3d", *end),
            b"\x00\x00",
        ]
    )


def _component_definition_preview(
    *,
    object_index: int,
    guid: bytes,
    name: str,
    entity_payloads: tuple[Any, ...],
    definition_type: int = 0,
) -> ComponentDefinitionState:
    return ComponentDefinitionState(
        object_tag=ArchiveObjectTag(kind="new_class", raw_tag=0xFFFF),
        object_index=object_index,
        definition=ComponentDefinition(
            id=0,
            guid=guid,
            name=name,
            description="",
            entities=Entities(),
            definition_type=definition_type,
            behavior_snap_mode=2,
            behavior_no_scale_mask=0,
            behavior_snap_enabled=True,
            behavior_cuts_opening=True,
            behavior_always_face_camera=True,
        ),
        entity_payloads=cast(tuple[Any, ...], entity_payloads),
    )


def _component_behavior_preview(
    *,
    is_2d: bool = False,
    cuts_opening: bool = False,
    snap_to: int = 0,
    always_face_camera: bool = False,
    shadows_face_sun: bool = False,
) -> ComponentBehaviorState:
    return ComponentBehaviorState(
        class_version=5,
        object_tag=None,
        payload_start_offset=0,
        entity_header=cast(Any, None),
        is_2d=is_2d,
        cuts_opening=cuts_opening,
        snap_to=snap_to,
        always_face_camera=always_face_camera,
        shadows_face_sun=shadows_face_sun,
        no_scale_mask=0,
        payload_end_offset=0,
    )


def _drawing_element_payload_bytes() -> bytes:
    # Entity/material refs are null (0x0000), followed by the eight schema-9
    # booleans: hidden, casts, receives, soft, smooth, locked, then layer ref.
    return b"".join(
        [
            b"\x00\x00",
            b"\x00\x00",
            b"\x00",
            b"\x01",
            b"\x01",
            b"\x00",
            b"\x00",
            b"\x01",
            b"\x00\x00",
        ]
    )


def _component_instance_payload_bytes(name: str) -> bytes:
    return b"".join(
        [
            _drawing_element_payload_bytes(),
            b"\x00\x00",
            struct.pack("<13d", *_component_instance_transform_values()),
            _legacy_string(name),
        ]
    )


def _background_image_payload_bytes() -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            _legacy_string("match-photo.png"),
            struct.pack("<I", 1),
            _new_class_tag("CDib", schema=3),
            _dib_preview_payload_bytes(),
            struct.pack("<IIII", 640, 480, 12_345, 1_700_000_000),
            b"\x01",
            struct.pack("<d", 0.75),
            struct.pack("<I", 2),
            struct.pack("<3d", 1.0, 2.0, 3.0),
            struct.pack("<3d", 4.0, 5.0, 6.0),
            struct.pack("<3d", 0.0, 0.0, 1.0),
            struct.pack("<d", -2.5),
            struct.pack("<I", 0x12),
        ]
    )


def _sketch_cs_payload_bytes() -> bytes:
    return struct.pack(
        "<12d",
        10.0,
        10.0,
        10.0,
        2**-0.5,
        2**-0.5,
        0.0,
        -(2**-0.5),
        2**-0.5,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _shadow_info_payload_bytes() -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            struct.pack("<I", 1_700_000_000),
            b"\x01",
            _legacy_string("USA"),
            _legacy_string("Boulder (CO)"),
            struct.pack("<d", -120.0),
            struct.pack("<d", 45.0),
            struct.pack("<d", -7.0),
            struct.pack("<3d", 0.0, 1.0, 0.0),
            b"\x01\x00\x01\x00",
            struct.pack("<i", 80),
            struct.pack("<i", 20),
            b"\x01",
        ]
    )


def _dimension_base_payload_bytes(text: str = "") -> bytes:
    return b"".join(
        [
            _drawing_element_payload_bytes(),
            _legacy_string(text),
            b"\x00\x00",
            b"\x00",
            struct.pack("<I", 0),
        ]
    )


def _point_ref_preview_bytes() -> bytes:
    return b"".join(
        [
            struct.pack("<I", 1),
            struct.pack("<I", 0),
            struct.pack("<3d", 1.0, 2.0, 3.0),
            b"\x00\x00",
            struct.pack("<I", 0),
        ]
    )


def _dimension_linear_preview_bytes() -> bytes:
    observed_root_bytes = b"".join(
        [
            _new_class_tag("CDimensionLinear", schema=6),
            _dimension_base_payload_bytes(),
            bytes.fromhex(
                "0100000004000000000000000000000000000000000000000000000000000000000000000000000000000000010000000400000000000000000059400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f03f000000000000f03f000000000000000000000000000000000000000000000000000000000000000000000000010000000000000000"
            ),
        ]
    )
    # The final bool/u32 belong to the enclosing root component, not the
    # CDimensionLinear body described by its V8 Serialize method.
    return observed_root_bytes[:-5]


def _font_preview_payload_bytes(face_name: str, *, bold: bool = False, italic: bool = False) -> bytes:
    return b"".join(
        [
            _legacy_string(face_name),
            bytes([int(bold), int(italic)]),
            struct.pack("<I", 12),
            b"\x00",
            struct.pack("<d", 1.0),
        ]
    )


def _style_preview_payload_bytes(
    *,
    guid: bytes,
    display_name: str,
    file_name: str,
    initial_file_name: str = "",
    style_version: int = 3,
    option_count: int = 53,
) -> bytes:
    options = b"".join(struct.pack("<IIII", 0x6000 + index, 1, 4, index) for index in range(option_count))
    return b"".join(
        [
            _new_class_tag("CSkpStyle", schema=2),
            b"\x00\x00",
            guid,
            _legacy_string(initial_file_name),
            struct.pack("<I", style_version),
            _legacy_string(display_name),
            _legacy_string(file_name),
            struct.pack("<I", option_count),
            options,
        ]
    )


def _watermark_preview_payload_bytes(
    *,
    name: str = "Watermark",
    path: str = "watermark.png",
) -> bytes:
    return b"".join(
        [
            _new_class_tag("CWatermark", schema=1),
            b"\x00\x00",
            b"\x01",
            _legacy_string(name),
            struct.pack("<I", 1_700_000_000),
            struct.pack("<I", 3),
            b"\x01\x00\x01\x00\x01",
            struct.pack("<d", 0.25),
            struct.pack("<d", 0.75),
            _legacy_string(path),
            _new_class_tag("CDib", schema=3),
            _dib_preview_payload_bytes(),
        ]
    )


def _scene_page_tail_bytes(
    *,
    flags: int,
    include_in_animation: bool,
    transition_time: float,
    delay_time: float,
    trailing_payload: bytes = b"",
) -> bytes:
    return b"".join(
        [
            struct.pack("<I", flags),
            _scene_timing_bytes(
                include_in_animation=include_in_animation,
                transition_time=transition_time,
                delay_time=delay_time,
            ),
            trailing_payload,
        ]
    )


def _scene_timing_bytes(
    *,
    include_in_animation: bool,
    transition_time: float,
    delay_time: float,
) -> bytes:
    return b"".join(
        [
            bytes([int(include_in_animation)]),
            struct.pack("<d", transition_time),
            struct.pack("<d", delay_time),
        ]
    )


def _component_instance_transform_values() -> tuple[float, ...]:
    return (
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        10.0,
        20.0,
        30.0,
        1.0,
    )


def _face_texture_coords_payload_bytes() -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            struct.pack("<I", 0),
            struct.pack("<9d", *_identity_matrix3_values()),
            struct.pack("<3d", 0.0, 0.0, 1.0),
            struct.pack("<9d", *_identity_matrix3_values()),
            struct.pack("<3d", 0.0, 0.0, -1.0),
            struct.pack("<I", 1),
            struct.pack("<4d", 1.0, 2.0, 3.0, 4.0),
            struct.pack("<I", 0),
            struct.pack("<I", 1),
            struct.pack("<I", 2),
        ]
    )


def _identity_matrix3_values() -> tuple[float, ...]:
    return (
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


__all__ = [name for name in globals() if not name.startswith("__")]
