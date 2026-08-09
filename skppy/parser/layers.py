# SPDX-License-Identifier: MIT
"""
Parser for the layers section (TlvTag.LAYERS_CONTAINER = 0x3A98) of model.dat.

Produces :class:`~skppy.data_structure.layers.Layer` and
:class:`~skppy.data_structure.layers.LayerFolder` objects.
"""

from __future__ import annotations

import zipfile
from typing import List, Mapping, Tuple

from ..data_structure.layers import Layer, LayerFolder
from ..data_structure.model_metadata import AttributeDictionary
from .attributes import parse_entity_attribute_dictionaries
from .material_parser import parse_material_record
from .tlv import (
    TlvTag,
    find_child,
    iter_records,
    read_bool,
    read_compact_int,
    read_utf8,
    read_id_from_wrapper,
    read_record,
)


def parse_layers(
    layers_container_payload: bytes,
    zip_file: zipfile.ZipFile | None = None,
    *,
    zip_name_map: Mapping[str, str] | None = None,
    attribute_dictionaries_by_object_id: dict[int, list[AttributeDictionary]] | None = None,
    import_vray_materials: bool = False,
) -> Tuple[List[Layer], List[LayerFolder]]:
    """
    Parse the layers-container section (tag 0x3A98) of model.dat.

    Parameters
    ----------
    layers_container_payload : bytes
        Raw payload bytes of the 0x3A98 layers-container record.

    Returns
    -------
    layers : list of Layer
        All layers (called "Tags" in modern SketchUp) in document order.
    layer_folders : list of LayerFolder
        Folder hierarchy for grouping layers, if any.
    """
    layer_list_p = find_child(layers_container_payload, TlvTag.LAYER_LIST)
    layers = _parse_layer_list(
        layer_list_p or b"",
        zip_file=zip_file,
        zip_name_map=zip_name_map,
        attribute_dictionaries_by_object_id=attribute_dictionaries_by_object_id,
        import_vray_materials=import_vray_materials,
    )

    folder_tree_p = find_child(layers_container_payload, TlvTag.LAYER_FOLDER_TREE)
    folders = _parse_folder_tree(folder_tree_p or b"")

    return layers, folders


def _parse_layer_list(
    payload: bytes,
    zip_file: zipfile.ZipFile | None = None,
    *,
    zip_name_map: Mapping[str, str] | None = None,
    attribute_dictionaries_by_object_id: dict[int, list[AttributeDictionary]] | None = None,
    import_vray_materials: bool = False,
) -> List[Layer]:
    """Parse the LAYER_LIST (0x3A99) payload into Layer objects.

    Parameters
    ----------
    payload : bytes
        Raw payload of the LAYER_LIST TLV record.

    Returns
    -------
    list of Layer
        Parsed layers in document order.
    """
    layers: List[Layer] = []
    for tag, layer_p in iter_records(payload):
        if tag != TlvTag.LAYER_RECORD:
            continue

        layer = Layer()
        id_wrap = find_child(layer_p, TlvTag.ID_WRAPPER)
        layer.id = read_id_from_wrapper(id_wrap) if id_wrap else 0
        attributes = parse_entity_attribute_dictionaries(layer_p)
        if attributes and attribute_dictionaries_by_object_id is not None:
            attribute_dictionaries_by_object_id[layer.id] = attributes

        name_p = find_child(layer_p, TlvTag.LAYER_NAME)
        layer.name = read_utf8(name_p) if name_p else ""

        vis_p = find_child(layer_p, TlvTag.LAYER_VISIBLE)
        # The wire value is a hidden bit: SDK-produced visible layers store 0.
        layer.visible = not read_bool(vis_p) if vis_p is not None else True

        mat_p = find_child(layer_p, TlvTag.LAYER_MATERIAL)
        if mat_p:
            material_record = None
            if len(mat_p) >= 6 and int.from_bytes(mat_p[:2], "little") == int(TlvTag.MATERIAL_RECORD):
                _, material_record, next_offset = read_record(mat_p, 0)
                if next_offset != len(mat_p):
                    raise ValueError("Layer material contains trailing TLV data")
            if material_record is not None:
                # Modern files embed the complete layer display material here,
                # rather than referencing the global material manager.
                material = parse_material_record(
                    material_record,
                    fallback_id=layer.id,
                    zip_file=zip_file,
                    zip_name_map=zip_name_map,
                    attribute_dictionaries_by_object_id=(attribute_dictionaries_by_object_id),
                    import_vray_materials=import_vray_materials,
                )
                layer.material_id = material.id
                layer.material = material
            else:
                # Early variants may contain only the referenced compact ID.
                layer.material_id = read_compact_int(mat_p)

        flags_p = find_child(layer_p, TlvTag.LAYER_SCENE_FLAGS)
        layer.page_behavior = read_compact_int(flags_p) if flags_p else 0

        layers.append(layer)
    return layers


def _parse_folder_tree(payload: bytes) -> List[LayerFolder]:
    """Parse the LAYER_FOLDER_TREE (0x3A9B) payload into LayerFolder objects.

    Parameters
    ----------
    payload : bytes
        Raw payload of the LAYER_FOLDER_TREE TLV record.

    Returns
    -------
    list of LayerFolder
        Top-level layer folders.
    """
    folders = _parse_folder_nodes(payload)
    # Modern files serialize one anonymous structural root. It is not a public
    # tag folder: the C API exposes its children as model-owned roots, matching
    # the legacy parser's normalization of its equivalent root group.
    if len(folders) == 1 and not folders[0].name and not folders[0].child_layer_ids:
        return folders[0].child_folders
    return folders


def _parse_folder_nodes(payload: bytes) -> List[LayerFolder]:
    """Decode folder nodes without applying root-container normalization."""
    folders: List[LayerFolder] = []
    for tag, node_p in iter_records(payload):
        if tag != TlvTag.FOLDER_NODE:
            continue
        folders.append(_parse_folder_node(node_p))
    return folders


def _parse_folder_node(payload: bytes) -> LayerFolder:
    """Parse a single FOLDER_NODE (0x3E80) into a LayerFolder.

    Parameters
    ----------
    payload : bytes
        Raw payload of the FOLDER_NODE TLV record.

    Returns
    -------
    LayerFolder
        Parsed folder with name, visibility, child layers, and sub-folders.
    """
    folder = LayerFolder()
    name_p = find_child(payload, TlvTag.FOLDER_NAME)
    folder.name = read_utf8(name_p) if name_p else ""

    vis_p = find_child(payload, TlvTag.FOLDER_VISIBLE)
    folder.visible = not read_bool(vis_p) if vis_p is not None else True

    child_ids_p = find_child(payload, TlvTag.FOLDER_CHILD_LAYER_IDS)
    if child_ids_p:
        folder.child_layer_ids = _read_length_prefixed_ids(child_ids_p)

    child_folders_p = find_child(payload, TlvTag.FOLDER_CHILD_GROUPS)
    if child_folders_p:
        folder.child_folders = _parse_folder_nodes(child_folders_p)

    return folder


def _read_length_prefixed_ids(payload: bytes) -> list[int]:
    """Decode the packed layer-ID sequence stored by a folder node.

    Unlike most modern collections, tag 0x3E84 does not contain child TLV
    records. Each ID is encoded as a one-byte payload length followed by that
    many little-endian bytes. Keeping this decoder local prevents treating the
    format as a general TLV primitive without evidence from other sections.
    """
    ids: list[int] = []
    offset = 0
    while offset < len(payload):
        width = payload[offset]
        offset += 1
        if not 1 <= width <= 4:
            raise ValueError(f"Layer folder ID width must be 1-4 bytes, got {width}")
        end = offset + width
        if end > len(payload):
            raise ValueError("Truncated layer folder ID sequence")
        ids.append(int.from_bytes(payload[offset:end], "little"))
        offset = end
    return ids
