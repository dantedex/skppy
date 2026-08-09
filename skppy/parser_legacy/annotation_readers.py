# SPDX-License-Identifier: MIT
"""Archive adapters for legacy text and dimension objects."""

from __future__ import annotations

from ..data_structure.model_metadata import Font

from .annotation_payloads import (
    read_dimension_radial_fields,
    read_point_ref_prefix,
    read_text_offsets,
    read_text_tail,
)
from .parser_types import (
    EdgeState,
    DimensionLinearPayload,
    DimensionPayload,
    DimensionRadialPayload,
    PointRefPayload,
    TextPayload,
)
from .binary import ArchiveObjectTag
from .read_context import ObjectReadContext


def read_dimension(
    context: ObjectReadContext,
    *,
    class_version: int,
) -> DimensionPayload:
    """Read a dimension base into shared drawing/font values."""
    if class_version not in {0, 1}:
        raise NotImplementedError("Only pre-ZIP CDimension versions 0 and 1 are decoded.")

    reader = context.session.reader
    # Dimensions serialize their CEntity/CDrawingElement bases first, then add
    # text and font state according to the derived class version.
    drawing_element = context.read_drawing_element()
    text = reader.read_legacy_utf16_string("CDimension text")
    if class_version == 0:
        return DimensionPayload(
            drawing_element,
            text,
            ArchiveObjectTag("null", 0, 0),
            None,
            False,
            0,
        )
    font_tag, font_object = context.read_object()
    font = font_object if isinstance(font_object, Font) else None
    return DimensionPayload(
        drawing_element,
        text,
        font_tag,
        font,
        reader.read_bool(),
        reader.read_u32(),
    )


def read_dimension_linear(
    context: ObjectReadContext,
    *,
    class_version: int,
) -> DimensionLinearPayload:
    """Read confirmed V8 linear-dimension anchors and geometry fields."""
    if class_version not in {4, 6}:
        raise NotImplementedError("Only pre-ZIP CDimensionLinear versions 4 and 6 are decoded.")
    base = read_dimension(
        context,
        class_version=context.class_versions.get("CDimension", 1),
    )
    reader = context.session.reader
    return DimensionLinearPayload(
        base,
        read_point_ref(context),
        read_point_ref(context),
        reader.read_vec3_f64(),
        reader.read_vec3_f64(),
        reader.read_u32(),
        reader.read_f64(),
        reader.read_f64(),
        reader.read_u32() if class_version > 5 else 0,
    )


def read_dimension_radial(
    context: ObjectReadContext,
    *,
    class_version: int,
) -> DimensionRadialPayload:
    """Read a radial dimension and resolve its optional edge target."""
    base = read_dimension(
        context,
        class_version=context.class_versions.get("CDimension", 1),
    )
    # A radial dimension either references an existing arc edge or embeds the
    # historical CArc3d geometry when the target tag is null.
    target_tag, target_object = context.read_object()
    target = target_object if isinstance(target_object, EdgeState) else None
    fields = read_dimension_radial_fields(
        context.session.reader,
        class_version=class_version,
        target_is_null=target_tag.kind == "null",
    )
    return DimensionRadialPayload(
        base,
        target_tag,
        target,
        fields.parameter,
        fields.radius_ratio,
        fields.is_diameter,
        fields.arc,
    )


def read_point_ref(context: ObjectReadContext) -> PointRefPayload:
    """Read a point reference and both optional component-instance paths."""
    reader = context.session.reader
    kind, format_version, position = read_point_ref_prefix(reader)
    # Point refs can carry two independent leaf/path pairs (for example a
    # dimension spanning nested instances). Preserve both archive paths until
    # a higher-level consumer can resolve model ownership.
    leaf_tag, _ = context.read_object()

    secondary_leaf_tag = None
    if format_version > 0:
        secondary_leaf_tag, _ = context.read_object()

    instance_path = _read_instance_path(context)
    secondary_instance_path: tuple[ArchiveObjectTag, ...] = ()
    if format_version > 3:
        secondary_instance_path = _read_instance_path(context)

    return PointRefPayload(
        kind,
        format_version,
        position,
        leaf_tag,
        secondary_leaf_tag,
        instance_path,
        secondary_instance_path,
    )


def _read_instance_path(
    context: ObjectReadContext,
) -> tuple[ArchiveObjectTag, ...]:
    reader = context.session.reader
    return tuple(context.read_object()[0] for _ in range(reader.read_u32()))


def read_text(
    context: ObjectReadContext,
    *,
    class_version: int,
) -> TextPayload:
    """Read text annotation data and its point-reference graph."""
    if class_version != 9:
        raise NotImplementedError("Only SketchUp 8 CText version 9 is decoded.")

    reader = context.session.reader
    drawing_element = context.read_drawing_element()
    # The font is an archive object, not an inline font payload. Keep both its
    # technical tag and resolved shared Font for diagnostics and normal use.
    font_tag, font_object = context.read_object()
    font = font_object if isinstance(font_object, Font) else None
    x_offset, y_offset = read_text_offsets(reader)
    point_ref = read_point_ref(context)
    return TextPayload(
        drawing_element,
        font_tag,
        font,
        x_offset,
        y_offset,
        point_ref,
        *read_text_tail(reader),
    )
