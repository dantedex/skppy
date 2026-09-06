# SPDX-License-Identifier: MIT
"""Finalize legacy materials and layers into the shared model."""

from __future__ import annotations

from dataclasses import replace
from functools import partial

from .._cancellation import check_cancelled
from ..data_structure.images import Texture
from ..data_structure.materials import Material
from ..data_structure.model import Model
from ..data_structure.layers import LayerFolder
from ..parser.enscape_materials import apply_enscape_attributes
from ..parser.material_parser import _parse_bounded_xml
from ..parser.vray_materials import apply_vray_attribute_dictionaries

from .parser_types import MaterialState
from .provenance import ArchiveProvenance


def apply_renderer_materials(model: Model, *, max_xml_bytes: int) -> None:
    """Enrich legacy appearances without following external texture paths."""
    parse_xml = partial(_parse_bounded_xml, max_bytes=max_xml_bytes)
    for material in model.materials:
        check_cancelled()
        dictionaries = model.attribute_dictionaries_by_object_id.get(material.id, ())
        resolve_texture = partial(_resolve_material_texture, material)
        if not apply_enscape_attributes(material, dictionaries, parse_xml=parse_xml, resolve_texture=resolve_texture):
            apply_vray_attribute_dictionaries(material, dictionaries)


def _resolve_material_texture(material: Material, filename: str, brightness: float, inverted: bool) -> Texture:
    """Reuse only this material's embedded image; retain other maps as references."""
    basename = filename.replace("\\", "/").split("/")[-1]
    base = material.texture
    if base is not None:
        matches = base.filename.replace("\\", "/").split("/")[-1].casefold() == basename.casefold()
        return replace(
            base,
            filename=basename,
            brightness=brightness,
            inverted=inverted,
            data=base.data if matches else None,
            uv_scale=(1.0, 1.0),
        )
    return Texture(filename=basename, brightness=brightness, inverted=inverted)


def collect_materials(provenance: ArchiveProvenance) -> tuple[MaterialState, ...]:
    """Collect root-component and directly serialized materials."""
    materials = list(provenance.root_component_materials)
    for payload in provenance.root_objects:
        if isinstance(payload, MaterialState):
            materials.append(payload)
        elif isinstance(payload, tuple):
            materials.extend(value for value in payload if isinstance(value, MaterialState))
    return tuple(materials)


def populate_materials(model: Model, materials: tuple[MaterialState, ...]) -> None:
    """Append unique shared materials while retaining payload identity."""
    seen_names = {material.name for material in model.materials}
    for archived in materials:
        if archived.material.name in seen_names:
            continue
        archived.material.id = model._alloc_id()
        model.materials.append(archived.material)
        seen_names.add(archived.material.name)


def material_ids_by_archive_index(
    model: Model,
    provenance: ArchiveProvenance,
    material_states: tuple[MaterialState, ...] | None = None,
) -> dict[int, int]:
    """Map private archive object indexes to allocated shared material IDs."""
    materials = material_states if material_states is not None else collect_materials(provenance)
    material_by_name = {material.name: material for material in model.materials}
    serialized_indices = [
        entry.index
        for entry in provenance.archive_index_entries
        if entry.kind == "object" and entry.class_name == "CMaterial"
    ]
    result: dict[int, int] = {}
    direct_payload_ids = {id(value) for _, value in provenance.archive_objects if isinstance(value, MaterialState)}
    for object_index, archived in provenance.archive_objects:
        if isinstance(archived, MaterialState):
            material = material_by_name.get(archived.material.name)
            if material is not None:
                result[object_index] = material.id

    unresolved = [index for index in serialized_indices if index not in result]
    recovered = [value for value in materials if id(value) not in direct_payload_ids]
    for object_index, archived in zip(unresolved, recovered):
        material = material_by_name.get(archived.material.name)
        if material is not None:
            result[object_index] = material.id
    return result


def populate_layers(model: Model, provenance: ArchiveProvenance) -> None:
    """Append shared layers and resolve the active layer archive reference."""
    layer_id_by_archive_index: dict[int, int] = {}
    for archived in provenance.archived_layers:
        archived.layer.id = model._alloc_id()
        if archived.material is not None:
            archived.layer.material = archived.material.material
        model.layers.append(archived.layer)
        if archived.object_tag.index is not None:
            layer_id_by_archive_index[archived.object_tag.index] = archived.layer.id
    active = provenance.active_layer_tag
    if active is not None and active.index is not None:
        model.active_layer_id = layer_id_by_archive_index.get(active.index)
    for folder in provenance.layer_folders:
        _resolve_folder_layer_ids(folder, layer_id_by_archive_index)
        model.layer_folders.append(folder)


def _resolve_folder_layer_ids(folder: LayerFolder, layer_id_by_archive_index: dict[int, int]) -> None:
    """Replace temporary archive indexes with shared model layer IDs."""
    folder.child_layer_ids = [
        layer_id_by_archive_index[index] for index in folder.child_layer_ids if index in layer_id_by_archive_index
    ]
    for child in folder.child_folders:
        _resolve_folder_layer_ids(child, layer_id_by_archive_index)
