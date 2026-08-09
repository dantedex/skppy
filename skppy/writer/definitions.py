# SPDX-License-Identifier: MIT
"""Modern component-definition serialization."""

from __future__ import annotations

import struct
from collections.abc import Iterable, Mapping

from ..data_structure.entities import ComponentDefinition
from ..data_structure.model_metadata import AttributeDictionary
from ..parser.tlv import TlvTag
from .entities import PointReferenceIdResolver, encode_entities
from .tlv import encode_bool, encode_record, encode_records


def encode_definitions(
    definitions: Iterable[ComponentDefinition],
    *,
    definition_id_map: Mapping[int, int],
    entity_id_maps: Mapping[int, Mapping[int, int]],
    material_id_map: Mapping[int, int],
    layer_id_map: Mapping[int, int],
    attribute_dictionaries_by_object_id: Mapping[int, Iterable[AttributeDictionary]],
    point_reference_id_resolvers: Mapping[int, PointReferenceIdResolver] | None = None,
    font_id_map: Mapping[int, int] | None = None,
) -> bytes:
    """Encode the complete modern component-definitions container."""
    definition_list = list(definitions)
    _validate_definitions(definition_list, definition_id_map, entity_id_maps)
    records: list[tuple[int, bytes]] = [(TlvTag.LEGACY_VERSION_MARKER, b"\x00" * 4)]
    records.extend(
        (
            TlvTag.DEFINITION_RECORD,
            _encode_definition(
                definition,
                definition_id_map,
                entity_id_maps[definition.id],
                material_id_map,
                layer_id_map,
                attribute_dictionaries_by_object_id.get(definition.id, ()),
                (point_reference_id_resolvers.get(definition.id) if point_reference_id_resolvers is not None else None),
                font_id_map,
            ),
        )
        for definition in definition_list
    )
    container_payload = encode_records(
        (
            (TlvTag.LEGACY_VERSION_MARKER, b"\x00" * 4),
            (TlvTag.DEFINITIONS_LIST, encode_records(records)),
        )
    )
    return encode_record(TlvTag.DEFINITIONS_CONTAINER, container_payload)


def _encode_definition(
    definition: ComponentDefinition,
    definition_id_map: Mapping[int, int],
    entity_id_map: Mapping[int, int],
    material_id_map: Mapping[int, int],
    layer_id_map: Mapping[int, int],
    attribute_dictionaries: Iterable[AttributeDictionary],
    point_reference_id_resolver: PointReferenceIdResolver | None,
    font_id_map: Mapping[int, int] | None,
) -> bytes:
    behavior = encode_records(
        (
            (
                TlvTag.BEHAVIOR_SNAP_MODE,
                struct.pack("<I", definition.behavior_snap_mode),
            ),
            (
                TlvTag.BEHAVIOR_NO_SCALE_MASK,
                struct.pack("<I", definition.behavior_no_scale_mask),
            ),
            (
                TlvTag.BEHAVIOR_SNAP_ENABLED,
                encode_bool(definition.behavior_snap_enabled),
            ),
            (
                TlvTag.BEHAVIOR_CUTS_OPENING,
                encode_bool(definition.behavior_cuts_opening),
            ),
            (
                TlvTag.BEHAVIOR_ALWAYS_FACE_CAMERA,
                encode_bool(definition.behavior_always_face_camera),
            ),
            (
                TlvTag.BEHAVIOR_SHADOWS_FACE_SUN,
                encode_bool(definition.behavior_shadows_face_sun),
            ),
        )
    )
    fields: list[tuple[int, bytes]] = [
        (
            TlvTag.ENTITIES,
            encode_entities(
                definition.entities,
                id_map=entity_id_map,
                material_id_map=material_id_map,
                layer_id_map=layer_id_map,
                definition_id_map=definition_id_map,
                font_id_map=font_id_map,
                scope_id=definition_id_map[definition.id],
                scope_attribute_dictionaries=attribute_dictionaries,
                point_reference_id_resolver=point_reference_id_resolver,
            )[6:],
        ),
        (TlvTag.DEFINITION_GUID, definition.guid),
        (TlvTag.DEFINITION_NAME, definition.name.encode("utf-8")),
        (TlvTag.DEFINITION_DESC, definition.description.encode("utf-8")),
        (TlvTag.DEFINITION_LOADED_FROM, definition.loaded_from.encode("utf-8")),
        (TlvTag.DEFINITION_MODIFIED, encode_bool(definition.modified)),
        (TlvTag.DEFINITION_TYPE, struct.pack("<I", definition.definition_type)),
        (TlvTag.DEFINITION_TIMESTAMP, struct.pack("<I", definition.timestamp)),
        (TlvTag.COMPONENT_BEHAVIOR_BLOCK, behavior),
    ]
    if definition.packed_payload is not None:
        fields.append((TlvTag.DEFINITION_PACKED_PAYLOAD, definition.packed_payload))
    return encode_records(fields)


def _validate_definitions(
    definitions: list[ComponentDefinition],
    definition_id_map: Mapping[int, int],
    entity_id_maps: Mapping[int, Mapping[int, int]],
) -> None:
    ids = [definition.id for definition in definitions]
    if any(definition_id <= 0 for definition_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("Definition IDs must be positive and unique")
    names = [definition.name for definition in definitions]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Definition names must be non-empty and unique")
    if any(definition_id not in definition_id_map for definition_id in ids):
        raise ValueError("Definition ID map does not cover every definition")
    if any(definition_id not in entity_id_maps for definition_id in ids):
        raise ValueError("Entity ID maps do not cover every definition")
    for definition in definitions:
        if len(definition.guid) != 16:
            raise ValueError("Definition GUID must contain 16 bytes")
        scalars = (
            definition.timestamp,
            definition.definition_type,
            definition.behavior_snap_mode,
            definition.behavior_no_scale_mask,
        )
        if any(not 0 <= value <= 0xFFFFFFFF for value in scalars):
            raise ValueError("Definition integer fields must fit in u32")
