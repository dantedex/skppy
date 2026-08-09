# SPDX-License-Identifier: MIT
"""Archive adapters for legacy fonts, styles, and watermarks."""

from __future__ import annotations

from ..data_structure.model_metadata import (
    DimensionStyle,
    Font,
    StyleDescriptor,
    StylesRegistry,
    TextStyle,
    Watermark,
    WatermarkManager,
)

from .parser_types import DibState
from .metadata_payloads import (
    read_dimension_style_payload,
    read_font_manager_body,
    read_font_payload,
    read_style_manager_body,
    read_style_payload,
    read_text_style_fields,
)
from .read_context import ObjectReadContext
from .visual_payloads import read_watermark_fields, read_watermark_manager_body


def read_font(context: ObjectReadContext, *, class_version: int) -> Font:
    """Read one legacy font directly into the shared metadata type."""
    context.read_entity()
    return read_font_payload(context.session.reader, class_version)


def read_font_manager(context: ObjectReadContext, *, class_version: int) -> tuple[Font, ...]:
    """Read the font manager as a simple sequence of shared fonts."""
    context.read_entity()
    return read_font_manager_body(
        context.session.reader,
        class_version=class_version,
        read_object=lambda: context.read_object()[1],
    )


def read_text_style(context: ObjectReadContext, *, class_version: int) -> TextStyle:
    """Read a text style and preserve its two font archive references."""
    context.read_entity()
    font_handle, _ = context.read_handle()
    fields = read_text_style_fields(
        context.session.reader,
        class_version=class_version,
    )
    screen_font_handle = font_handle
    if class_version > 4:
        screen_font_handle, _ = context.read_handle()
    return TextStyle(
        font_ref=font_handle.object_index or 0,
        screen_font_ref=screen_font_handle.object_index or 0,
        **fields,
    )


def read_dimension_style(context: ObjectReadContext, *, class_version: int) -> DimensionStyle:
    """Read a dimension style and its font reference."""
    context.read_entity()
    context.session.reader.read_u32()
    font_handle, _ = context.read_handle()
    return read_dimension_style_payload(
        context.session.reader,
        class_version=class_version,
        font_ref=font_handle.object_index or 0,
    )


def read_style(context: ObjectReadContext, *, class_version: int) -> StyleDescriptor:
    """Read one shared style descriptor."""
    context.read_entity()
    return read_style_payload(
        context.session.reader,
        class_version,
        read_object=lambda: context.read_object()[1],
    )


def read_style_manager(context: ObjectReadContext, *, class_version: int) -> StylesRegistry:
    """Read the style registry and resolve contained styles."""
    context.read_entity()
    return read_style_manager_body(
        context.session.reader,
        class_version=class_version,
        read_object=lambda: context.read_object()[1],
        read_tagged_object=context.read_object,
    )


def read_watermark(context: ObjectReadContext, *, class_version: int) -> Watermark:
    """Read a watermark and resolve its embedded image bytes."""
    context.read_entity()
    fields = read_watermark_fields(
        context.session.reader,
        class_version=class_version,
    )
    _, dib_object = context.read_object()
    image_data = dib_object.image_bytes if isinstance(dib_object, DibState) else None
    return Watermark(image_data=image_data, **fields)


def read_watermark_manager(context: ObjectReadContext, *, class_version: int) -> WatermarkManager:
    """Read a watermark manager into the shared registry type."""
    context.read_entity()
    return read_watermark_manager_body(
        context.session.reader,
        class_version=class_version,
        read_object=lambda: context.read_object()[1],
    )
