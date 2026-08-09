# SPDX-License-Identifier: MIT
"""Restore skppy post-2017 metadata preserved in legacy attribute dictionaries."""

from __future__ import annotations

import base64
import json
from typing import Any

from ..data_structure.entities import ArcCurve, Entities
from ..data_structure.layers import LayerFolder
from ..data_structure.model import Model
from ..data_structure.model_metadata import EnvironmentData, EnvironmentEntry, LineStyle, SunData

_DICTIONARY_NAME = "SkppyLegacyExtensions"
_PAYLOAD_KEY = "PayloadV1"


def apply_legacy_extensions(model: Model) -> None:
    """Apply and remove the reserved skppy compatibility dictionary."""
    matches = [dictionary for dictionary in model.attribute_dictionaries if dictionary.name == _DICTIONARY_NAME]
    if not matches:
        return
    if len(matches) != 1:
        raise ValueError("Legacy model contains duplicate skppy extension dictionaries")
    entries = [entry for entry in matches[0].entries if entry.key == _PAYLOAD_KEY]
    if len(entries) != 1 or entries[0].value_type != 3:
        raise ValueError("Legacy skppy extension dictionary has an invalid payload entry")
    try:
        payload = json.loads(entries[0].string_value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Legacy skppy extension payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Legacy skppy extension payload must be an object")
    _apply_payload(model, payload)
    model.attribute_dictionaries.remove(matches[0])


def _apply_payload(model: Model, payload: dict[str, Any]) -> None:
    if "line_styles" in payload:
        model.line_styles = [LineStyle(**_object(value, "line style")) for value in _array(payload["line_styles"])]
    if "layer_folders" in payload:
        layer_ids_by_name = {layer.name: layer.id for layer in model.layers}
        model.layer_folders = [
            _layer_folder(_object(value, "layer folder"), layer_ids_by_name)
            for value in _array(payload["layer_folders"])
        ]
    _apply_pbr(model, payload)
    if "environment" in payload:
        model.environment_data = _environment(_object(payload["environment"], "environment"))
    if "sun" in payload:
        model.sun_data = SunData(raw_payload=_bytes(payload["sun"]))
    _apply_definition_extensions(model, payload.get("definitions"))
    _apply_entity_scope_extensions(model, payload.get("entity_scopes"))
    if "axes_flags" in payload and model.model_view_axes is not None:
        model.model_view_axes.flags = _integer(payload["axes_flags"], "axes flags")
    if "camera_allow_clipping" in payload and model.cameras:
        model.cameras[0].allow_clipping = bool(payload["camera_allow_clipping"])
    if "shadow_edges_cast_shadows" in payload and model.shadow_info is not None:
        model.shadow_info.edges_cast_shadows = bool(payload["shadow_edges_cast_shadows"])
    _apply_scene_extensions(model, payload.get("scenes"))
    _apply_rendering_extensions(model, payload.get("rendering"))
    _apply_style_extensions(model, payload.get("styles"))


def _layer_folder(value: dict[str, Any], layer_ids_by_name: dict[str, int]) -> LayerFolder:
    try:
        child_layer_ids = [layer_ids_by_name[str(name)] for name in _array(value.get("layers", []))]
    except KeyError as exc:
        raise ValueError(f"Legacy skppy layer folder references missing layer {exc.args[0]!r}") from exc
    return LayerFolder(
        name=str(value.get("name", "")),
        visible=bool(value.get("visible", True)),
        child_layer_ids=child_layer_ids,
        child_folders=[
            _layer_folder(_object(child, "layer folder"), layer_ids_by_name)
            for child in _array(value.get("children", []))
        ],
    )


def _apply_pbr(model: Model, payload: dict[str, Any]) -> None:
    material_pbr = _object(payload.get("material_pbr", {}), "material PBR map")
    materials_by_name = {material.name: material for material in model.materials}
    for name, factors in material_pbr.items():
        material = materials_by_name.get(name)
        if material is not None:
            material.metallic, material.roughness = _factors(factors)
    layer_pbr = _object(payload.get("layer_material_pbr", {}), "layer material PBR map")
    layers_by_name = {layer.name: layer for layer in model.layers}
    for name, factors in layer_pbr.items():
        layer = layers_by_name.get(name)
        if layer is not None and layer.material is not None:
            layer.material.metallic, layer.material.roughness = _factors(factors)


def _environment(value: dict[str, Any]) -> EnvironmentData:
    entries = [_environment_entry(_object(entry, "environment entry")) for entry in _array(value.get("entries", []))]
    selected_id = _integer(value.get("selected"), "selected environment ID")
    selected = next((entry for entry in entries if entry.id == selected_id), None)
    if selected is None:
        raise ValueError("Legacy skppy extension references a missing selected environment")
    return EnvironmentData(selected=selected, entries=entries)


def _environment_entry(value: dict[str, Any]) -> EnvironmentEntry:
    return EnvironmentEntry(
        id=_integer(value.get("id"), "environment ID"),
        name=str(value.get("name", "")),
        thumbnail_path=str(value.get("thumbnail_path", "")),
        image_filename=str(value.get("image_filename", "")),
        image_data=_required_bytes(value.get("image_data"), "environment image"),
        thumbnail_data=_bytes(value.get("thumbnail_data")),
        description=str(value.get("description", "")),
        use_as_skydome=bool(value.get("use_as_skydome", False)),
        use_for_reflections=bool(value.get("use_for_reflections", False)),
        rotation=float(value.get("rotation", 0.0)),
        skydome_exposure=float(value.get("skydome_exposure", 1.0)),
        reflection_exposure=float(value.get("reflection_exposure", 1.0)),
    )


def _apply_scene_extensions(model: Model, value: Any) -> None:
    if value is None:
        return
    extensions = _object(value, "scene extensions")
    scenes_by_name = {scene.name: scene for scene in model.scenes}
    for name, raw_extension in extensions.items():
        scene = scenes_by_name.get(name)
        if scene is None:
            continue
        extension = _object(raw_extension, "scene extension")
        if scene.camera is not None and "allow_clipping" in extension:
            scene.camera.allow_clipping = bool(extension["allow_clipping"])
        if "raw_payload" in extension:
            scene.raw_payload = _bytes(extension["raw_payload"])


def _apply_rendering_extensions(model: Model, value: Any) -> None:
    if value is None or model.rendering_options is None:
        return
    for name, field_value in _object(value, "rendering extensions").items():
        if not hasattr(model.rendering_options, name):
            raise ValueError(f"Unknown legacy skppy rendering extension {name!r}")
        setattr(model.rendering_options, name, field_value)


def _apply_style_extensions(model: Model, value: Any) -> None:
    if value is None or model.styles_registry is None:
        return
    styles = [*model.styles_registry.styles]
    if model.styles_registry.inline_style_override is not None:
        styles.append(model.styles_registry.inline_style_override)
    for raw_index, raw_extension in _object(value, "style extensions").items():
        index = int(raw_index) - 1
        if not 0 <= index < len(styles):
            raise ValueError("Legacy skppy style extension index is out of range")
        extension = _object(raw_extension, "style extension")
        styles[index].display_name = str(extension.get("display_name", ""))
        styles[index].xml_data = _bytes(extension.get("xml_data"))


def _apply_definition_extensions(model: Model, value: Any) -> None:
    if value is None:
        return
    definitions_by_name = {definition.name: definition for definition in model.definitions}
    for name, raw_extension in _object(value, "definition extensions").items():
        definition = definitions_by_name.get(name)
        if definition is None:
            continue
        extension = _object(raw_extension, "definition extension")
        definition.packed_payload = _bytes(extension.get("packed_payload"))


def _apply_entity_scope_extensions(model: Model, value: Any) -> None:
    if value is None:
        return
    scopes = _object(value, "entity-scope extensions")
    if "root" in scopes:
        _apply_entity_scope(model.entities, _object(scopes["root"], "root entity scope"))
    definitions = _object(scopes.get("definitions", {}), "definition entity scopes")
    definitions_by_name = {definition.name: definition for definition in model.definitions}
    for name, raw_scope in definitions.items():
        definition = definitions_by_name.get(name)
        if definition is not None:
            _apply_entity_scope(definition.entities, _object(raw_scope, "definition entity scope"))


def _apply_entity_scope(entities: Entities, scope: dict[str, Any]) -> None:
    for raw_arc in _array(scope.get("raw_arcs", [])):
        arc = _object(raw_arc, "raw arc")
        positions = [_integer(position, "raw arc edge position") for position in _array(arc.get("edges", []))]
        try:
            edge_ids = [entities.edges[position].id for position in positions]
        except IndexError as exc:
            raise ValueError("Legacy skppy raw arc edge position is out of range") from exc
        curve = next((candidate for candidate in entities.curves if candidate.edge_ids == edge_ids), None)
        if curve is None:
            raise ValueError("Legacy skppy raw arc has no matching curve")
        entities.curves.remove(curve)
        entities.arc_curves.append(
            ArcCurve(
                id=curve.id,
                edge_ids=curve.edge_ids,
                raw_arc_payload=_required_bytes(arc.get("payload"), "raw arc payload"),
            ),
        )
    for raw_index, raw_section in _object(scope.get("sections", {}), "section extensions").items():
        index = int(raw_index)
        if not 0 <= index < len(entities.section_planes):
            raise ValueError("Legacy skppy section extension index is out of range")
        section = entities.section_planes[index]
        extension = _object(raw_section, "section extension")
        section.name = str(extension.get("name", ""))
        section.symbol = str(extension.get("symbol", ""))


def _factors(value: Any) -> tuple[float, float]:
    values = _array(value)
    if len(values) != 2:
        raise ValueError("Legacy skppy PBR factors must contain two values")
    return float(values[0]), float(values[1])


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Legacy skppy {label} must be an object")
    return value


def _array(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("Legacy skppy extension value must be an array")
    return value


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"Legacy skppy {label} must be an integer")
    return value


def _bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Legacy skppy binary value must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError("Legacy skppy binary value is not valid base64") from exc


def _required_bytes(value: Any, label: str) -> bytes:
    decoded = _bytes(value)
    if decoded is None:
        raise ValueError(f"Legacy skppy {label} is required")
    return decoded
