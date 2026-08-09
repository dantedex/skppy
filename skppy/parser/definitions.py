# SPDX-License-Identifier: MIT
"""Decode component definitions and their independent entity scopes.

The modern ``model.dat`` definitions section contains identity and behavior
metadata followed by a nested entities block. :func:`parse_definitions`
returns :class:`~skppy.data_structure.entities.ComponentDefinition` objects
whose vertex and entity IDs are local to each definition. Normal applications
should use :func:`skppy.load`; this module is the bounded section decoder used
by the full model pipeline.
"""

from __future__ import annotations

from typing import List

from ..data_structure.model_metadata import AttributeDictionary
from .attributes import parse_entity_attribute_dictionaries
from .entities import parse_entities
from ..data_structure.entities import ComponentDefinition, Entities
from .tlv import (
    TlvTag,
    find_child,
    iter_records,
    read_bool,
    read_compact_int,
    read_guid,
    read_utf8,
)


def parse_definitions(
    definitions_container_payload: bytes,
    *,
    attribute_dictionaries_by_object_id: dict[int, list[AttributeDictionary]] | None = None,
) -> List[ComponentDefinition]:
    """Parse the component definitions section (tag 0x01F9) of model.dat.

    Parameters
    ----------
    definitions_container_payload : bytes
        Raw payload of the DEFINITIONS_CONTAINER (0x1770) TLV record.

    Returns
    -------
    list of ComponentDefinition
        Fully parsed component definitions, each with its own Entities.
    """
    list_p = find_child(definitions_container_payload, TlvTag.DEFINITIONS_LIST)
    if not list_p:
        return []

    definitions: List[ComponentDefinition] = []
    for tag, def_p in iter_records(list_p):
        if tag != TlvTag.DEFINITION_RECORD:
            continue
        defn = _parse_definition(def_p)
        definitions.append(defn)
        attributes = _parse_definition_attributes(def_p)
        if attributes and attribute_dictionaries_by_object_id is not None:
            attribute_dictionaries_by_object_id[defn.id] = attributes
    return definitions


def _parse_definition_attributes(payload: bytes) -> list[AttributeDictionary]:
    """Read dictionaries from the entity base that owns a definition."""
    entities = find_child(payload, TlvTag.ENTITIES)
    entity_base = find_child(entities, TlvTag.ENTITY_BASE) if entities is not None else None
    return parse_entity_attribute_dictionaries(entity_base) if entity_base is not None else []


def _parse_definition(payload: bytes) -> ComponentDefinition:
    definition = ComponentDefinition()
    # - ID: entity base lives inside TlvTag.ENTITIES (0x1388), not directly in
    #     the definition record.  Path: 0x1388 -> 0x07D0 -> 0x05DC -> 0x05DE -
    entities_p = find_child(payload, TlvTag.ENTITIES)
    if entities_p:
        eb = find_child(entities_p, TlvTag.ENTITY_BASE)
        if eb:
            id_wrap = find_child(eb, TlvTag.ID_WRAPPER)
            if id_wrap:
                id_val = find_child(id_wrap, TlvTag.ID_VALUE)
                if id_val:
                    definition.id = read_compact_int(id_val)

    guid_p = find_child(payload, TlvTag.DEFINITION_GUID)
    definition.guid = read_guid(guid_p) if guid_p else b"\x00" * 16

    name_p = find_child(payload, TlvTag.DEFINITION_NAME)
    definition.name = read_utf8(name_p) if name_p else f"definition_{definition.id}"

    desc_p = find_child(payload, TlvTag.DEFINITION_DESC)
    definition.description = read_utf8(desc_p) if desc_p else ""

    # - Definition extras -
    loaded_from_p = find_child(payload, TlvTag.DEFINITION_LOADED_FROM)
    definition.loaded_from = read_utf8(loaded_from_p) if loaded_from_p else ""

    ts_p = find_child(payload, TlvTag.DEFINITION_TIMESTAMP)
    definition.timestamp = read_compact_int(ts_p) if ts_p else 0

    mod_p = find_child(payload, TlvTag.DEFINITION_MODIFIED)
    definition.modified = read_bool(mod_p) if mod_p else False

    type_p = find_child(payload, TlvTag.DEFINITION_TYPE)
    definition.definition_type = read_compact_int(type_p) if type_p else 0

    packed_p = find_child(payload, TlvTag.DEFINITION_PACKED_PAYLOAD)
    definition.packed_payload = packed_p if packed_p else None

    # - Component behavior (0x1B58) -
    behavior_p = find_child(payload, TlvTag.COMPONENT_BEHAVIOR_BLOCK)
    if behavior_p:
        sm = find_child(behavior_p, TlvTag.BEHAVIOR_SNAP_MODE)
        definition.behavior_snap_mode = read_compact_int(sm) if sm else 0
        nsm = find_child(behavior_p, TlvTag.BEHAVIOR_NO_SCALE_MASK)
        definition.behavior_no_scale_mask = read_compact_int(nsm) if nsm else 0
        se = find_child(behavior_p, TlvTag.BEHAVIOR_SNAP_ENABLED)
        definition.behavior_snap_enabled = read_bool(se) if se else False
        co = find_child(behavior_p, TlvTag.BEHAVIOR_CUTS_OPENING)
        definition.behavior_cuts_opening = read_bool(co) if co else False
        afc = find_child(behavior_p, TlvTag.BEHAVIOR_ALWAYS_FACE_CAMERA)
        definition.behavior_always_face_camera = read_bool(afc) if afc else False
        sfs = find_child(behavior_p, TlvTag.BEHAVIOR_SHADOWS_FACE_SUN)
        definition.behavior_shadows_face_sun = read_bool(sfs) if sfs else False

    # - Entities (0x1388 nested inside the definition) -
    definition.entities = parse_entities(entities_p) if entities_p else Entities()
    return definition
