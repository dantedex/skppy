# SPDX-License-Identifier: MIT
"""Modern named-scene serialization."""

from __future__ import annotations

import struct
from collections.abc import Iterable, Mapping

from ..data_structure.scene_data import Scene
from ..parser.tlv import TlvTag
from ..parser.tlv import iter_records
from .cameras import encode_camera_record
from .tlv import encode_bool, encode_compact_int, encode_record, encode_records


def _mapped_references(
    values: Iterable[int],
    id_map: Mapping[int, int],
    label: str,
) -> list[int]:
    mapped = []
    for value in values:
        try:
            mapped.append(id_map[value])
        except KeyError as exc:
            raise ValueError(f"Scene has unknown {label} reference {value}") from exc
    return mapped


def _encode_scene(
    scene: Scene,
    scene_id_map: Mapping[int, int],
    entity_id_map: Mapping[int, int],
    layer_id_map: Mapping[int, int],
    background_image_object_ids: Mapping[int, int],
    background_image_reference_ids: Mapping[int, int],
) -> bytes:
    if scene.flags & 0x1 and scene.camera is None:
        raise ValueError("A scene using its camera requires a camera snapshot")
    if scene.camera is not None and not scene.flags & 0x1:
        raise ValueError("A scene camera snapshot requires the use-camera flag")
    if scene.display_background_image and not (scene.background_image is not None or scene.background_image_ref):
        raise ValueError("A displayed scene background image requires an image")
    base = encode_records(
        (
            (
                TlvTag.ID_WRAPPER,
                encode_record(
                    TlvTag.ID_VALUE,
                    encode_compact_int(scene_id_map[scene.id]),
                ),
            ),
            (TlvTag.SCENE_NAME, scene.name.encode("utf-8")),
            (TlvTag.SCENE_DESCRIPTION, scene.description.encode("utf-8")),
        )
    )
    fields: list[tuple[int, bytes]] = [
        (TlvTag.SCENE_BASE, base),
        (TlvTag.SCENE_FLAGS, struct.pack("<I", scene.flags)),
    ]
    if scene.camera is not None and scene.flags & 0x1:
        fields.append((TlvTag.SCENE_CAMERA_SNAPSHOT, encode_camera_record(scene.camera)))
    fields.extend(
        (TlvTag.SCENE_HIDDEN_ENTITY_IDS, encode_compact_int(value))
        for value in _mapped_references(scene.hidden_entity_ids, entity_id_map, "hidden entity")
    )
    if scene.style_reference:
        fields.append((TlvTag.SCENE_STYLE_REF, encode_compact_int(scene.style_reference)))
    fields.extend(
        (TlvTag.SCENE_HIDDEN_LAYER_IDS, encode_compact_int(value))
        for value in _mapped_references(scene.hidden_layer_ids, layer_id_map, "hidden layer")
    )
    fields.extend(
        (TlvTag.SCENE_ACTIVE_SECTION_PLANE_IDS, encode_compact_int(value))
        for value in _mapped_references(scene.active_section_plane_ids, entity_id_map, "section plane")
    )
    fields.extend(
        (
            (TlvTag.SCENE_SHOW_IN_SLIDESHOW, encode_bool(scene.show_in_slideshow)),
            (TlvTag.SCENE_RESERVED_STRING, b""),
            (TlvTag.SCENE_TRANSITION_TIME, struct.pack("<d", -1.0)),
            (TlvTag.SCENE_DELAY_TIME, struct.pack("<d", -1.0)),
        )
    )
    background_reference = _background_reference(scene, background_image_object_ids, background_image_reference_ids)
    if background_reference:
        fields.append(
            (
                TlvTag.SCENE_BACKGROUND_IMAGE_REF,
                encode_compact_int(background_reference),
            )
        )
    fields.extend(
        (
            (TlvTag.SCENE_FOREGROUND_IMAGE_IDS, b""),
            (TlvTag.SCENE_USE_THUMBNAIL, b"\x01"),
        )
    )
    return encode_record(
        TlvTag.SCENE_RECORD,
        _merge_scene_payload(fields, scene.raw_payload),
    )


def _merge_scene_payload(generated_fields: list[tuple[int, bytes]], raw_payload: bytes | None) -> bytes:
    """Replace modeled fields while retaining unmodeled scene snapshots."""
    if raw_payload is None:
        return encode_records(generated_fields)

    generated_by_tag: dict[int, list[bytes]] = {}
    generated_order: list[int] = []
    for tag, payload in generated_fields:
        if tag not in generated_by_tag:
            generated_order.append(tag)
        generated_by_tag.setdefault(tag, []).append(payload)

    modeled_tags = {
        TlvTag.SCENE_BASE,
        TlvTag.SCENE_FLAGS,
        TlvTag.SCENE_CAMERA_SNAPSHOT,
        TlvTag.SCENE_HIDDEN_ENTITY_IDS,
        TlvTag.SCENE_STYLE_REF,
        TlvTag.SCENE_HIDDEN_LAYER_IDS,
        TlvTag.SCENE_ACTIVE_SECTION_PLANE_IDS,
        TlvTag.SCENE_SHOW_IN_SLIDESHOW,
        TlvTag.SCENE_RESERVED_STRING,
        TlvTag.SCENE_TRANSITION_TIME,
        TlvTag.SCENE_DELAY_TIME,
        TlvTag.SCENE_BACKGROUND_IMAGE_REF,
        TlvTag.SCENE_FOREGROUND_IMAGE_IDS,
        TlvTag.SCENE_USE_THUMBNAIL,
    }
    try:
        source_records = list(iter_records(raw_payload))
    except ValueError as exc:
        raise ValueError("Scene raw payload is not a valid TLV record stream") from exc

    emitted: set[int] = set()
    records = bytearray()
    for tag, payload in source_records:
        if tag not in modeled_tags:
            records.extend(encode_record(tag, payload))
            continue
        if tag in emitted:
            continue
        records.extend(encode_records((tag, value) for value in generated_by_tag.get(tag, ())))
        emitted.add(tag)

    for tag in generated_order:
        if tag in emitted:
            continue
        records.extend(encode_records((tag, value) for value in generated_by_tag[tag]))
    return bytes(records)


def _background_reference(
    scene: Scene,
    object_ids: Mapping[int, int],
    reference_ids: Mapping[int, int],
) -> int:
    if scene.background_image is not None:
        return object_ids[id(scene.background_image)]
    if not scene.background_image_ref:
        return 0
    try:
        return reference_ids[scene.background_image_ref]
    except KeyError as exc:
        raise ValueError(f"Scene has unknown background image reference {scene.background_image_ref}") from exc


def encode_scenes(
    scenes: Iterable[Scene],
    *,
    scene_id_map: Mapping[int, int],
    entity_id_map: Mapping[int, int],
    layer_id_map: Mapping[int, int],
    background_image_object_ids: Mapping[int, int] | None = None,
    background_image_reference_ids: Mapping[int, int] | None = None,
) -> bytes:
    """Encode a complete modern named-scenes container."""
    values = list(scenes)
    ids = [scene.id for scene in values]
    names = [scene.name for scene in values]
    if any(value <= 0 for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Scene IDs must be positive and unique")
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Scene names must be non-empty and unique")
    records = b"".join(
        _encode_scene(
            scene,
            scene_id_map,
            entity_id_map,
            layer_id_map,
            background_image_object_ids or {},
            background_image_reference_ids or {},
        )
        for scene in values
    )
    return encode_record(
        TlvTag.SCENES_CONTAINER,
        encode_record(TlvTag.SCENES_LIST, records),
    )
