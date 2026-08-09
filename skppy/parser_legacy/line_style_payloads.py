# SPDX-License-Identifier: MIT
"""Version-aware custom line-style readers for legacy archives."""

from __future__ import annotations

from ..data_structure.model_metadata import LineStyle

from .read_context import ObjectReadContext


def read_custom_line_style(context: ObjectReadContext, *, class_version: int) -> LineStyle:
    """Read one ``CCustomLineStyle`` into the shared line-style type."""
    if class_version not in {1, 2, 3, 4}:
        raise NotImplementedError(f"Unsupported CCustomLineStyle schema {class_version}.")
    context.read_entity()
    if class_version < 3:
        # Older schemas retain a historical second CEntity body.
        context.read_entity()

    reader = context.session.reader
    style = LineStyle()
    style.color = 0
    style.name = reader.read_legacy_utf16_string("CCustomLineStyle name")
    if class_version == 1:
        style.dash_pattern = str(reader.read_u16())
    else:
        style.dash_pattern = reader.read_legacy_utf16_string("CCustomLineStyle dash pattern")
    style.line_width_points = reader.read_f64()
    if class_version > 1:
        style.stipple_scale = reader.read_f64()
    if class_version in {2, 3}:
        reader.read_f64()  # Superseded width field.
    elif class_version >= 4:
        style.color = reader.read_u32()
        style.mutability = bool(reader.read_u8())
    return style


def read_line_style_manager(context: ObjectReadContext) -> tuple[LineStyle, ...]:
    """Read the implicit model line-style manager and its style objects."""
    context.read_entity()
    styles: list[LineStyle] = []
    for _ in range(context.session.reader.read_u32()):
        _, value = context.read_object()
        if isinstance(value, LineStyle):
            styles.append(value)
    return tuple(styles)
