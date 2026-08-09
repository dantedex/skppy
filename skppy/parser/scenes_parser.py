# SPDX-License-Identifier: MIT
"""
Parser for the scenes block (TlvTag.SCENES_BLOCK = 0x0207) of model.dat.

SketchUp scenes (named pages) store camera positions, layer visibility,
rendering settings, and other view-state data.

Internal hierarchy::

    0x0207 (scenes_block)
      -> 0x6D60 (scenes_container)
        -> 0x6D61 (scenes_list)
          -> 0x7148 (scene_record) [repeated]
            -> 0x6F54 (scene_base_record)
              -> 0x05DC (id_wrapper) -> 0x05DE (id_value)
              -> 0x6F55 (scene_name)
              -> 0x6F56 (scene_description)
            -> 0x7149 (scene_flags_u32)
            -> 0x714A (scene_camera_snapshot) -> 0x34BC (camera_record)
            -> 0x714B (scene_hidden_entities_ref_ids)
            -> 0x714C (scene_style_ref)
            -> 0x7150 (scene_hidden_layers_ref_ids)
            -> 0x7151 (scene_active_section_planes_ref_ids)
            -> 0x7152 (scene_show_in_slideshow)
            -> 0x7156 (scene_background_image_ref)

Entry point::

    from skppy.parser.scenes_parser import parse_scenes
"""

from __future__ import annotations

import logging
from typing import List

from ..data_structure.scene_data import Scene
from .camera_parser import parse_cameras
from .tlv import (
    TlvTag,
    find_child,
    index_children,
    iter_records,
    read_compact_int,
    read_bool,
    read_id_from_wrapper,
    read_utf8,
)

logger = logging.getLogger(__name__)


def parse_scenes(scenes_block_payload: bytes) -> List[Scene]:
    """
    Parse the TlvTag.SCENES_BLOCK (0x0207) payload and return a list of
    :class:`Scene`.

    The parser follows the correct tag hierarchy:
    0x0207 -> 0x6D60 -> 0x6D61 -> repeated 0x7148.

    Each scene record is parsed for persistent ID, name, description, flags,
    camera, hidden entity/layer IDs, active section plane IDs, slideshow flag,
    style reference, and background image reference. The full raw payload of
    every record is stored in :attr:`Scene.raw_payload` so that future parsers
    can extract additional fields without needing to re-read the file.

    Parameters
    ----------
    scenes_block_payload:
        Raw bytes of the 0x0207 scenes-block record payload.

    Returns
    -------
    list[Scene]
        One entry per named scene, in the order they appear in the file.
    """
    scenes: List[Scene] = []
    fallback_id = 1

    # Navigate the hierarchy: 0x0207 -> 0x6D60 -> 0x6D61 -> 0x7148...
    container_p = find_child(scenes_block_payload, TlvTag.SCENES_CONTAINER)
    if not container_p:
        logger.debug("No scenes container (0x6D60) found in scenes block")
        return scenes

    list_p = find_child(container_p, TlvTag.SCENES_LIST)
    if not list_p:
        logger.debug("No scenes list (0x6D61) found in scenes container")
        return scenes

    for tag, rec_payload in iter_records(list_p):
        if tag != TlvTag.SCENE_RECORD:
            continue

        scene = _parse_scene_record(rec_payload, fallback_id)
        scenes.append(scene)
        fallback_id += 1

    logger.debug("Parsed %d scene(s)", len(scenes))
    return scenes


def _first_record(records: dict[int, list[bytes]], tag: int) -> bytes | None:
    """Return the first occurrence of a scene field."""
    values = records.get(tag)
    return values[0] if values else None


def _apply_scene_base(scene: Scene, records: dict[int, list[bytes]]) -> None:
    """Decode the nested identity, name, and description record."""
    payload = _first_record(records, TlvTag.SCENE_BASE)
    if payload is None:
        return
    fields = index_children(payload)
    id_wrapper = fields.get(TlvTag.ID_WRAPPER)
    persistent_id = read_id_from_wrapper(id_wrapper) if id_wrapper else 0
    if persistent_id:
        scene.id = persistent_id
    name = fields.get(TlvTag.SCENE_NAME)
    scene.name = read_utf8(name) if name is not None else ""
    description = fields.get(TlvTag.SCENE_DESCRIPTION)
    scene.description = read_utf8(description) if description is not None else ""


def _scene_reference_ids(records: dict[int, list[bytes]], tag: int) -> list[int]:
    """Decode repeated scalar references without merging record boundaries."""
    return [read_compact_int(value) for value in records.get(tag, [])]


def _apply_scene_optional_fields(scene: Scene, records: dict[int, list[bytes]]) -> None:
    """Decode optional scalar fields and repeated entity references."""
    optional_scalars = (
        (TlvTag.SCENE_FLAGS, "flags", read_compact_int),
        (TlvTag.SCENE_SHOW_IN_SLIDESHOW, "show_in_slideshow", read_bool),
        (TlvTag.SCENE_STYLE_REF, "style_reference", read_compact_int),
        (
            TlvTag.SCENE_BACKGROUND_IMAGE_REF,
            "background_image_ref",
            read_compact_int,
        ),
    )
    for tag, field, decoder in optional_scalars:
        payload = _first_record(records, tag)
        if payload is not None:
            setattr(scene, field, decoder(payload))
    scene.hidden_entity_ids = _scene_reference_ids(records, TlvTag.SCENE_HIDDEN_ENTITY_IDS)
    scene.hidden_layer_ids = _scene_reference_ids(records, TlvTag.SCENE_HIDDEN_LAYER_IDS)
    scene.active_section_plane_ids = _scene_reference_ids(records, TlvTag.SCENE_ACTIVE_SECTION_PLANE_IDS)


def _parse_scene_record(rec_payload: bytes, fallback_id: int) -> Scene:
    """
    Parse a single scene record (0x7148).

    Parameters
    ----------
    rec_payload : bytes
        Raw payload of the scene record.
    fallback_id : int
        Sequential ID used only when the record has no persistent ID.

    Returns
    -------
    Scene
    """
    # - Base record (0x6F54): name and description -
    records: dict[int, list[bytes]] = {}
    for tag, payload in iter_records(rec_payload):
        records.setdefault(tag, []).append(payload)

    scene = Scene(id=fallback_id, name="")
    _apply_scene_base(scene, records)
    if not scene.name:
        scene.name = f"Scene {scene.id}"
    _apply_scene_optional_fields(scene, records)
    camera_payload = _first_record(records, TlvTag.SCENE_CAMERA_SNAPSHOT)
    if camera_payload is not None:
        cameras = parse_cameras(camera_payload)
        scene.camera = cameras[0] if cameras else None
    scene.raw_payload = rec_payload
    return scene
