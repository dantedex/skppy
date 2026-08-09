# SPDX-License-Identifier: MIT
"""Raw SU2017 style-registry and watermark writer fixtures."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyModelEncoder


def test_style_and_watermark_match_raw_carchive_payloads() -> None:
    model = skppy.Model.new()
    watermark = skppy.Watermark(name="Logo", image_data=b"PNG", opacity=0.5, position=5, id=7)
    manager = skppy.WatermarkManager([watermark], 1)
    style = skppy.StyleDescriptor(
        guid=bytes(range(16)),
        display_name="Display",
        file_name="Style",
        watermark_reference_ids=[7],
    )
    encoder = _LegacyModelEncoder(model, model.entities)
    encoder.data.clear()
    encoder._write_style(style, manager)
    expected = bytes.fromhex(
        "ffff0200090043536b705374796c6500000101000102030405060708090a0b0c0d0e0ffffeff055300740079006c00650003000000fffeff05530074"
        "0079006c006500fffeff055300740079006c006500010000008913000001000000ffff01000a004357617465726d61726b0000010700fffeff044c00"
        "6f0067006f0000000000040000000100000001000000000000e03f000000000000e03ffffeff00ffff03000400434469620400000003000000504e47"
    )

    assert encoder.data == expected

    encoder.data.clear()
    encoder._write_watermark_manager(manager)
    assert encoder.data == bytes.fromhex("000000010000000c00")


def test_writes_inline_style_override() -> None:
    model = skppy.Model.new()
    model.styles_registry = skppy.StylesRegistry(
        styles=[skppy.StyleDescriptor(guid=bytes(16), file_name="Main")],
        active_style_ref=1,
        inline_style_override=skppy.StyleDescriptor(guid=bytes(range(16)), file_name="Inline"),
        selected_style_dirty=True,
    )

    encoded = build_legacy_2017_model(model)

    assert "Main".encode("utf-16le") in encoded
    assert "Inline".encode("utf-16le") in encoded


@pytest.mark.parametrize(
    ("registry", "message"),
    [
        (skppy.StylesRegistry(), "contain at least one style"),
        (
            skppy.StylesRegistry(styles=[skppy.StyleDescriptor(guid=bytes(16), file_name="Style")]),
            "active style reference",
        ),
        (
            skppy.StylesRegistry(
                styles=[skppy.StyleDescriptor(guid=b"short", file_name="Style")],
                active_style_ref=1,
            ),
            "GUIDs must contain 16 bytes",
        ),
        (
            skppy.StylesRegistry(
                styles=[skppy.StyleDescriptor(guid=bytes(16), file_name="bad/name")],
                active_style_ref=1,
            ),
            "path-safe",
        ),
    ],
)
def test_rejects_invalid_style_registries(registry: skppy.StylesRegistry, message: str) -> None:
    model = skppy.Model.new()
    model.styles_registry = registry

    with pytest.raises(ValueError, match=message):
        build_legacy_2017_model(model)


def test_rejects_unknown_style_watermark_references() -> None:
    model = skppy.Model.new()
    model.watermark_manager = skppy.WatermarkManager()
    model.styles_registry = skppy.StylesRegistry(
        styles=[skppy.StyleDescriptor(guid=bytes(16), file_name="Style", watermark_reference_ids=[9])],
        active_style_ref=1,
    )

    with pytest.raises(ValueError, match="unknown watermark reference 9"):
        build_legacy_2017_model(model)


@pytest.mark.parametrize(
    ("manager", "message"),
    [
        (skppy.WatermarkManager([], 1), "count must match"),
        (skppy.WatermarkManager([skppy.Watermark(image_data=b"PNG")]), "names must be non-empty"),
        (
            skppy.WatermarkManager([skppy.Watermark(name="bad/name", image_data=b"PNG")]),
            "names must be non-empty",
        ),
        (skppy.WatermarkManager([skppy.Watermark(name="Missing")]), "require image data"),
        (
            skppy.WatermarkManager([skppy.Watermark(name="Opacity", image_data=b"PNG", opacity=2.0)]),
            "outside its supported range",
        ),
    ],
)
def test_rejects_invalid_watermarks(manager: skppy.WatermarkManager, message: str) -> None:
    model = skppy.Model.new()
    model.watermark_manager = manager

    with pytest.raises(ValueError, match=message):
        build_legacy_2017_model(model)
