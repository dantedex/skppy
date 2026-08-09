# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern style-registry serialization."""

from __future__ import annotations

import struct

import pytest

from skppy.data_structure.model_metadata import (
    StyleDescriptor,
    StylesRegistry,
    Watermark,
    WatermarkManager,
)
from skppy.writer.styles import encode_style_xml, encode_styles_registry, style_entries


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_styles_registry_matches_raw_expected_bytes() -> None:
    style = StyleDescriptor(
        guid=bytes(range(16)),
        display_name="Writer Style",
        file_name="WriterStyle",
    )
    registry = StylesRegistry(styles=[style], active_style_ref=1, selected_style_dirty=True)
    descriptor = b"".join(
        (
            _raw_record(0x05DC, _raw_record(0x05DE, b"\x01")),
            _raw_record(0x6B6D, bytes(range(16))),
            _raw_record(0x6B6E, b"Writer Style"),
            _raw_record(0x6B6F, b"WriterStyle"),
            _raw_record(0x6B70),
        )
    )
    expected = _raw_record(
        0x6978,
        _raw_record(0x6979, _raw_record(0x6B6C, descriptor))
        + _raw_record(0x697A, b"\x01")
        + _raw_record(0x697C, b"\x01"),
    )
    assert encode_styles_registry(registry) == expected
    assert "styles/WriterStyle/style.xml" in style_entries(registry)


def test_style_watermark_references_use_packed_global_ids() -> None:
    registry = StylesRegistry(
        styles=[
            StyleDescriptor(
                guid=bytes(range(16)),
                file_name="WatermarkStyle",
                watermark_reference_ids=[1],
            )
        ],
        active_style_ref=1,
    )

    encoded = encode_styles_registry(registry, watermark_id_map={1: 0x12})

    assert _raw_record(0x6B70, b"\x01\x12") in encoded


def _style(**changes) -> StyleDescriptor:
    style = StyleDescriptor(guid=bytes(range(16)), display_name="Style", file_name="Style")
    for field, value in changes.items():
        setattr(style, field, value)
    return style


def test_inline_style_override_matches_raw_descriptor_and_resource() -> None:
    inline = _style(file_name="Inline", xml_data=b"<raw-style/>")
    registry = StylesRegistry(styles=[_style()], active_style_ref=1, inline_style_override=inline)
    encoded = encode_styles_registry(registry)

    assert _raw_record(0x697B)[:2] in encoded
    assert style_entries(registry)["styles/Inline/style.xml"] == b"<raw-style/>"
    assert style_entries(None) == {}


def test_style_xml_embeds_png_and_jpeg_watermark_references() -> None:
    style = _style(watermark_reference_ids=[1, 2])
    manager = WatermarkManager(
        watermarks=[
            Watermark(id=1, name="Overlay", image_data=b"\x89PNG\r\n\x1a\nraw"),
            Watermark(id=2, name="Photo", image_data=b"\xff\xd8raw", position=5),
        ]
    )
    xml = encode_style_xml(style, manager)

    assert b'path="watermarks/Overlay.png"' in xml
    assert b'path="watermarks/Photo.jpg"' in xml
    assert b'tiled="1"' in xml
    assert b'maintainAR="0"' in xml


@pytest.mark.parametrize(
    ("registry", "message"),
    [
        (StylesRegistry(), "at least one style"),
        (
            StylesRegistry(styles=[_style(), _style()], active_style_ref=1),
            "file names must be unique",
        ),
        (
            StylesRegistry(styles=[_style(guid=b"short")], active_style_ref=1),
            "GUIDs must contain 16 bytes",
        ),
        (
            StylesRegistry(styles=[_style(file_name="bad/name")], active_style_ref=1),
            "file names must be non-empty and path-safe",
        ),
        (StylesRegistry(styles=[_style()], active_style_ref=2), "must identify"),
    ],
)
def test_style_registry_rejects_invalid_identity(registry: StylesRegistry, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        encode_styles_registry(registry)


def test_style_watermark_references_require_known_manager_entries() -> None:
    style = _style(watermark_reference_ids=[1])
    with pytest.raises(ValueError, match="require a watermark manager"):
        encode_style_xml(style)
    with pytest.raises(ValueError, match="Unknown style watermark"):
        encode_style_xml(style, WatermarkManager())

    positional = Watermark(name="Positional", image_data=b"\xff\xd8raw")
    xml = encode_style_xml(style, WatermarkManager(watermarks=[positional]))
    assert b'path="watermarks/Positional.jpg"' in xml


def test_style_rejects_invalid_watermark_image_data() -> None:
    style = _style(watermark_reference_ids=[1])
    manager = WatermarkManager(watermarks=[Watermark(id=1, name="Bad", image_data=b"")])
    with pytest.raises(ValueError, match="must be PNG or JPEG"):
        encode_style_xml(style, manager)
