# SPDX-License-Identifier: MIT
"""Modern layer and layer-folder serialization."""

from __future__ import annotations

import struct
from collections.abc import Iterable, Mapping

from ..data_structure.layers import Layer, LayerFolder
from ..data_structure.materials import Color, Material
from ..data_structure.model_metadata import AttributeDictionary
from ..parser.tlv import TlvTag
from .attributes import encode_attribute_dictionaries
from .materials import encode_material_record, material_entries
from .tlv import encode_bool, encode_compact_int, encode_record, encode_records


def encode_layers(
    layers: Iterable[Layer],
    folders: Iterable[LayerFolder],
    *,
    layer_id_map: Mapping[int, int],
    display_material_id_map: Mapping[int, int],
    first_folder_id: int,
    active_layer_id: int | None,
    attribute_dictionaries_by_object_id: Mapping[int, Iterable[AttributeDictionary]] | None = None,
) -> bytes:
    """Encode a complete modern layers-container record."""
    layer_list = list(layers)
    folder_list = list(folders)
    _validate_layers(layer_list, layer_id_map, display_material_id_map)
    fields: list[tuple[int, bytes]] = [
        (
            TlvTag.LAYER_LIST,
            encode_records(
                (
                    TlvTag.LAYER_RECORD,
                    _encode_layer(
                        layer,
                        layer_id_map[layer.id],
                        display_material_id_map[layer.id],
                        (attribute_dictionaries_by_object_id or {}).get(layer.id, ()),
                    ),
                )
                for layer in layer_list
            ),
        )
    ]
    resolved_active_id = active_layer_id
    if resolved_active_id is None and layer_list:
        resolved_active_id = layer_list[0].id
    if resolved_active_id is not None:
        try:
            serialized_active_id = layer_id_map[resolved_active_id]
        except KeyError as exc:
            raise ValueError("Active layer does not exist in the model") from exc
        fields.append((TlvTag.ACTIVE_LAYER_ID, encode_compact_int(serialized_active_id)))
    folder_ids = iter(range(first_folder_id, first_folder_id + _folder_count(folder_list)))
    fields.append(
        (
            TlvTag.LAYER_FOLDER_TREE,
            encode_record(
                TlvTag.FOLDER_NODE,
                _encode_folder_root(folder_list, layer_id_map, folder_ids),
            ),
        )
    )
    return encode_record(TlvTag.LAYERS_CONTAINER, encode_records(fields))


def layer_material_entries(layers: Iterable[Layer], display_material_id_map: Mapping[int, int]) -> dict[str, bytes]:
    """Return XML resources for each embedded color-by-layer material."""
    materials = [_display_material(layer, display_material_id_map[layer.id]) for layer in layers]
    return material_entries(materials)


def count_layer_folders(folders: Iterable[LayerFolder]) -> int:
    """Return the recursive number of layer folders."""
    return _folder_count(list(folders))


def _encode_layer(
    layer: Layer,
    serialized_id: int,
    material_id: int,
    attribute_dictionaries: Iterable[AttributeDictionary],
) -> bytes:
    identity = encode_record(TlvTag.ID_VALUE, encode_compact_int(serialized_id))
    dictionaries = list(attribute_dictionaries)
    if dictionaries:
        identity += encode_record(
            TlvTag.ID_EXT_PAYLOAD,
            encode_attribute_dictionaries(dictionaries),
        )
    display_material = _display_material(layer, material_id)
    material_record = encode_record(
        TlvTag.MATERIAL_RECORD,
        encode_material_record(display_material, material_id, embedded=True),
    )
    return encode_records(
        (
            (TlvTag.ID_WRAPPER, identity),
            (TlvTag.LAYER_NAME, layer.name.encode("utf-8")),
            # The on-disk field is a hidden bit despite its historical tag
            # name in the parser. Zero means visible and one means hidden.
            (TlvTag.LAYER_VISIBLE, encode_bool(not layer.visible)),
            (TlvTag.LAYER_MATERIAL, material_record),
            (TlvTag.LAYER_SCENE_FLAGS, struct.pack("<I", layer.page_behavior)),
        )
    )


def _display_material(layer: Layer, material_id: int) -> Material:
    if layer.material is not None:
        source = layer.material
        return Material(
            id=material_id,
            name=source.name,
            color=source.color,
            alpha=source.alpha,
            has_texture=source.has_texture,
            texture=source.texture,
            metallic=source.metallic,
            roughness=source.roughness,
        )
    return Material(
        id=material_id,
        name=f"Layer_{layer.name}",
        color=Color(255, 84, 84),
    )


def _encode_folder_tree(
    folders: list[LayerFolder],
    layer_id_map: Mapping[int, int],
    folder_ids: Iterable[int],
) -> bytes:
    records = []
    folder_id_iterator = iter(folder_ids)
    for folder in folders:
        records.append(
            (
                TlvTag.FOLDER_NODE,
                _encode_folder(folder, layer_id_map, folder_id_iterator),
            )
        )
    return encode_records(records)


def _encode_folder_root(
    folders: list[LayerFolder],
    layer_id_map: Mapping[int, int],
    folder_ids: Iterable[int],
) -> bytes:
    """Encode the anonymous structural root required by the official reader."""
    return encode_records(
        (
            (TlvTag.FOLDER_NAME, b""),
            (
                TlvTag.FOLDER_CHILD_GROUPS,
                _encode_folder_tree(folders, layer_id_map, folder_ids),
            ),
            (TlvTag.FOLDER_CHILD_LAYER_IDS, b""),
            (TlvTag.FOLDER_VISIBLE, b"\x00"),
            (TlvTag.FOLDER_VISIBLE_ON_NEW_SCENES, b"\x00"),
        )
    )


def _encode_folder(
    folder: LayerFolder,
    layer_id_map: Mapping[int, int],
    folder_ids: Iterable[int],
) -> bytes:
    folder_id_iterator = iter(folder_ids)
    try:
        folder_id = next(folder_id_iterator)
    except StopIteration as exc:
        raise ValueError("Layer folder ID allocation is incomplete") from exc
    identity = encode_record(TlvTag.ID_VALUE, encode_compact_int(folder_id))
    try:
        child_ids = [layer_id_map[layer_id] for layer_id in folder.child_layer_ids]
    except KeyError as exc:
        raise ValueError(f"Layer folder references unknown layer {exc.args[0]}") from exc
    return encode_records(
        (
            (TlvTag.ID_WRAPPER, identity),
            (TlvTag.FOLDER_NAME, folder.name.encode("utf-8")),
            (
                TlvTag.FOLDER_CHILD_GROUPS,
                _encode_folder_tree(folder.child_folders, layer_id_map, folder_id_iterator),
            ),
            (TlvTag.FOLDER_CHILD_LAYER_IDS, _encode_packed_ids(child_ids)),
            (TlvTag.FOLDER_VISIBLE, encode_bool(not folder.visible)),
            (TlvTag.FOLDER_VISIBLE_ON_NEW_SCENES, b"\x00"),
        )
    )


def _encode_packed_ids(ids: Iterable[int]) -> bytes:
    output = bytearray()
    for value in ids:
        encoded = encode_compact_int(value)
        output.append(len(encoded))
        output.extend(encoded)
    return bytes(output)


def _folder_count(folders: list[LayerFolder]) -> int:
    return sum(1 + _folder_count(folder.child_folders) for folder in folders)


def _validate_layers(
    layers: list[Layer],
    layer_id_map: Mapping[int, int],
    material_id_map: Mapping[int, int],
) -> None:
    ids = [layer.id for layer in layers]
    if any(layer_id <= 0 for layer_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("Layer IDs must be positive and unique")
    names = [layer.name for layer in layers]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Layer names must be non-empty and unique")
    if any(layer_id not in layer_id_map for layer_id in ids):
        raise ValueError("Layer ID map does not cover every layer")
    if any(layer_id not in material_id_map for layer_id in ids):
        raise ValueError("Layer material ID map does not cover every layer")
    if any(not 0 <= layer.page_behavior <= 0xFFFFFFFF for layer in layers):
        raise ValueError("Layer page behavior must fit in u32")
