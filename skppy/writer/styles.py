# SPDX-License-Identifier: MIT
"""Modern style-registry TLV and resource serialization."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping

from ..data_structure.model_metadata import (
    StyleDescriptor,
    StylesRegistry,
    Watermark,
    WatermarkManager,
)
from ..parser.tlv import TlvTag
from .tlv import encode_bool, encode_compact_int, encode_record, encode_records

_STYLE_NAMESPACE = "http://sketchup.google.com/schemas/sketchup/1.0/style"
_TYPE_NAMESPACE = "http://sketchup.google.com/schemas/1.0/types"
_WATERMARK_LIST_NAMESPACE = "http://sketchup.google.com/schemas/sketchup/1.0/wmlist"

# SketchUp rejects an empty style document.  These are the canonical defaults
# emitted by a newly-created style; callers that need exact custom settings can
# preserve a complete document through ``StyleDescriptor.xml_data``.
_DEFAULT_STYLE_ITEMS: tuple[tuple[int, int, str], ...] = (
    (1000, 4, "1"),
    (1001, 4, "0"),
    (1002, 4, "1"),
    (1004, 1, "0"),
    (1005, 4, "8"),
    (1006, 1, "1"),
    (1007, 4, "3"),
    (1008, 1, "0"),
    (1009, 4, "4"),
    (1010, 1, "0"),
    (1011, 4, "5"),
    (1012, 1, "0"),
    (1014, 4, "-16777216"),
    (1015, 1, "0"),
    (1016, 1, "1"),
    (2001, 4, "2"),
    (2002, 4, "-3612191"),
    (2003, 4, "-3637120"),
    (2004, 1, "0"),
    (2005, 1, "1"),
    (2006, 4, "0"),
    (2007, 1, "1"),
    (2008, 7, "0.65000000000000002"),
    (4000, 4, "-1"),
    (4001, 4, "-23156"),
    (4002, 1, "0"),
    (4003, 4, "-12610753"),
    (4004, 1, "0"),
    (4005, 4, "50"),
    (4006, 1, "1"),
    (4007, 4, "0"),
    (5000, 1, "1"),
    (7000, 4, "-16711681"),
    (7001, 4, "-16776961"),
    (7002, 4, "-8355712"),
    (7003, 4, "-7508378"),
    (7004, 4, "-4144960"),
    (7005, 4, "-16776961"),
    (7008, 1, "1"),
    (7010, 1, "0"),
    (7011, 1, "0"),
    (7012, 1, "0"),
    (7013, 4, "3"),
    (7014, 4, "4"),
    (7015, 1, "0"),
    (7016, 4, "-16777216"),
    (7017, 1, "0"),
    (7018, 1, "0"),
    (8000, 1, "1"),
    (8001, 7, "1"),
    (8002, 1, "1"),
    (8003, 7, "0.80000000000000004"),
    (8100, 1, "0"),
    (8102, 6, "10"),
    (8103, 6, "0"),
    (8105, 1, "0"),
    (8106, 4, "-16777216"),
    (8107, 6, "1"),
)


def encode_styles_registry(
    registry: StylesRegistry,
    watermark_id_map: Mapping[int, int] | None = None,
) -> bytes:
    """Encode the payload of the root styles-registry block."""
    _validate_registry(registry)
    records = b"".join(
        encode_record(
            TlvTag.STYLE_DESCRIPTOR,
            _encode_descriptor(
                style,
                style_id=index,
                watermark_id_map=watermark_id_map,
            ),
        )
        for index, style in enumerate(registry.styles, start=1)
    )
    fields: list[tuple[int, bytes]] = [
        (TlvTag.STYLE_LIST, records),
        (TlvTag.ACTIVE_STYLE_REF, encode_compact_int(registry.active_style_ref)),
    ]
    if registry.inline_style_override is not None:
        fields.append(
            (
                TlvTag.INLINE_STYLE_OVERRIDE,
                encode_record(
                    TlvTag.STYLE_DESCRIPTOR,
                    _encode_descriptor(
                        registry.inline_style_override,
                        watermark_id_map=watermark_id_map,
                    ),
                ),
            )
        )
    fields.append((TlvTag.STYLE_MANAGER_DIRTY, encode_bool(registry.selected_style_dirty)))
    return encode_record(TlvTag.STYLES_REGISTRY, encode_records(fields))


def style_entries(
    registry: StylesRegistry | None,
    watermark_manager: WatermarkManager | None = None,
) -> dict[str, bytes]:
    """Return deterministic ``styles/*/style.xml`` ZIP resources."""
    if registry is None:
        return {}
    _validate_registry(registry)
    styles = [*registry.styles]
    if registry.inline_style_override is not None:
        styles.append(registry.inline_style_override)
    entries: dict[str, bytes] = {}
    for style in styles:
        _referenced_watermarks(style, watermark_manager)
        entries[f"styles/{style.file_name}/style.xml"] = (
            style.xml_data if style.xml_data is not None else encode_style_xml(style, watermark_manager)
        )
    return entries


def encode_style_xml(
    style: StyleDescriptor,
    watermark_manager: WatermarkManager | None = None,
) -> bytes:
    """Encode a canonical default style document accepted by SketchUp."""
    document = ET.Element(
        "styleDocument",
        {"xmlns": _STYLE_NAMESPACE, "xmlns:sty": _STYLE_NAMESPACE},
    )
    style_element = ET.SubElement(
        document,
        "sty:style",
        {
            "xmlns:t": _TYPE_NAMESPACE,
            "name": style.file_name,
            "desc": style.display_name,
        },
    )
    referenced = _referenced_watermarks(style, watermark_manager)
    for item_id, variant_type, value in _DEFAULT_STYLE_ITEMS:
        item = ET.SubElement(style_element, "sty:item", {"id": str(item_id)})
        ET.SubElement(item, "t:variant", {"type": str(variant_type)}).text = value
        if item_id == 5000:
            _append_watermark_item(style_element, referenced)
    ET.indent(document, space="  ")
    encoded: bytes = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    return encoded


def _append_watermark_item(style_element: ET.Element, referenced: list[tuple[int, Watermark]]) -> None:
    watermark_item = ET.SubElement(style_element, "sty:item", {"id": "5001"})
    watermark_variant = ET.SubElement(
        watermark_item,
        "t:variant",
        {"type": "13", "xmlns:n0": _WATERMARK_LIST_NAMESPACE},
    )
    watermark_list = ET.SubElement(
        watermark_variant,
        "n0:wmlist",
        {"count": str(len(referenced) + 1) if referenced else "0"},
    )
    if referenced:
        screen_images = ET.SubElement(watermark_list, "n0:screenimages")
        ET.SubElement(screen_images, "n0:screenimage", {"name": "<MODEL SPACE>"})
        for reference_id, watermark in referenced:
            tiled = watermark.position == 5
            screen_image = ET.SubElement(
                screen_images,
                "n0:screenimage",
                {
                    "alphaScale": format(watermark.opacity, ".17g"),
                    "background": "0",
                    "info_filename": "",
                    "info_found": "0",
                    "info_time": "0",
                    "intensForAlpha": "1",
                    "maintainAR": "0" if tiled else "1",
                    "name": watermark.name,
                    "position": str(4 if tiled else watermark.position),
                    "fittingType": "0" if tiled else "2",
                    "stretchType": "0" if tiled else "1",
                    "scale": "1",
                    "stretched": "0",
                    "tiled": "1" if tiled else "0",
                },
            )
            images = ET.SubElement(screen_image, "n0:images")
            extension = _image_extension(watermark.image_data)
            ET.SubElement(
                images,
                "n0:image",
                {
                    "id": str(reference_id),
                    "path": f"watermarks/{watermark.name}.{extension}",
                    "file_name": f"{watermark.name}.{extension}",
                },
            )


def _encode_descriptor(
    style: StyleDescriptor,
    style_id: int | None = None,
    watermark_id_map: Mapping[int, int] | None = None,
) -> bytes:
    fields: list[tuple[int, bytes]] = []
    if style_id is not None:
        fields.append(
            (
                TlvTag.ID_WRAPPER,
                encode_record(TlvTag.ID_VALUE, encode_compact_int(style_id)),
            )
        )
    fields.extend(
        (
            (TlvTag.STYLE_GUID, style.guid),
            (TlvTag.STYLE_DISPLAY_NAME, style.display_name.encode("utf-8")),
            (TlvTag.STYLE_FILE_NAME, style.file_name.encode("utf-8")),
        )
    )
    if style_id is not None or style.watermark_reference_ids:
        fields.append(
            (
                TlvTag.STYLE_WATERMARK_REFS,
                _encode_id_vector(
                    [
                        watermark_id_map[value] if watermark_id_map is not None else value
                        for value in style.watermark_reference_ids
                    ]
                ),
            )
        )
    return encode_records(fields)


def _validate_registry(registry: StylesRegistry) -> None:
    if not registry.styles:
        raise ValueError("A styles registry must contain at least one style")
    names = [style.file_name for style in registry.styles]
    if len(names) != len(set(names)):
        raise ValueError("Style file names must be unique")
    for style in [*registry.styles, registry.inline_style_override]:
        if style is None:
            continue
        if len(style.guid) != 16:
            raise ValueError("Style GUIDs must contain 16 bytes")
        if not style.file_name or any(char in style.file_name for char in "/\\"):
            raise ValueError("Style file names must be non-empty and path-safe")
    if not 1 <= registry.active_style_ref <= len(registry.styles):
        raise ValueError("Active style reference must identify a registered style")


def _referenced_watermarks(style: StyleDescriptor, manager: WatermarkManager | None) -> list[tuple[int, Watermark]]:
    if not style.watermark_reference_ids:
        return []
    if manager is None:
        raise ValueError("Style watermark references require a watermark manager")
    referenced: list[tuple[int, Watermark]] = []
    for reference_id in style.watermark_reference_ids:
        watermark = next((item for item in manager.watermarks if item.id == reference_id), None)
        if watermark is None and 1 <= reference_id <= len(manager.watermarks):
            watermark = manager.watermarks[reference_id - 1]
        if watermark is None:
            raise ValueError(f"Unknown style watermark reference: {reference_id}")
        referenced.append((reference_id, watermark))
    return referenced


def _image_extension(image_data: bytes | None) -> str:
    if image_data is not None and image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if image_data is not None and image_data.startswith(b"\xff\xd8"):
        return "jpg"
    raise ValueError("Watermark image data must be PNG or JPEG")


def _encode_id_vector(values: list[int]) -> bytes:
    encoded = bytearray()
    for value in values:
        scalar = encode_compact_int(value)
        encoded.append(len(scalar))
        encoded.extend(scalar)
    return bytes(encoded)
