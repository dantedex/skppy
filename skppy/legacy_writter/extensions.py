# SPDX-License-Identifier: MIT
"""Preserve post-2017 model features in a native legacy attribute dictionary."""

from __future__ import annotations

import base64
import json
from math import isfinite
from pathlib import PurePosixPath
from typing import Any

from ..data_structure.entities import Entities
from ..data_structure.layers import LayerFolder
from ..data_structure.model import Model
from ..data_structure.model_metadata import AttributeDictionary, AttributeDictionaryEntry, EnvironmentEntry, LineStyle

EXTENSION_DICTIONARY_NAME = "SkppyLegacyExtensions"
EXTENSION_PAYLOAD_KEY = "PayloadV1"

_BUILTIN_LINE_STYLE_DATA = (
    ("Solid Basic", "16.0"),
    ("Short dash", "6.0, -6.0"),
    ("Dash", "12.0, -6.0"),
    ("Dot", "1.0, -6.0"),
    ("Dash dot", "12.0, -6.0, 1.0, -6.0"),
    ("Dash double-dot", "12.0, -6.0, 1.0, -6.0, 1.0, -6.0"),
    ("Dash triple-dot", "12.0, -6.0, 1.0, -6.0, 1.0, -6.0, 1.0, -6.0"),
    ("Double-dash dot", "12.0, -6.0, 12.0, -6.0, 1.0, -6.0"),
    ("Double-dash double-dot", "12.0, -6.0, 12.0, -6.0, 1.0, -6.0, 1.0, -6.0"),
    ("Double-dash triple-dot", "12.0, -6.0, 12.0, -6.0, 1.0, -6.0, 1.0, -6.0, 1.0, -6.0"),
    ("Long-dash dash", "36.0, -10.0, 12.0, -10.0"),
    ("Long-dash double-dash", "36.0, -10.0, 12.0, -10.0, 12.0, -10.0"),
)
_BUILTIN_LINE_STYLES = {
    name: LineStyle(name=name, dash_pattern=pattern, mutability=False) for name, pattern in _BUILTIN_LINE_STYLE_DATA
}


def extension_dictionary(model: Model) -> AttributeDictionary | None:
    """Return a deterministic compatibility dictionary when modern-only state exists."""
    if any(dictionary.name == EXTENSION_DICTIONARY_NAME for dictionary in model.attribute_dictionaries):
        raise ValueError(f"{EXTENSION_DICTIONARY_NAME!r} is reserved by the legacy writer")
    payload = _extension_payload(model)
    if not payload:
        return None
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return AttributeDictionary(
        name=EXTENSION_DICTIONARY_NAME,
        entries=[
            AttributeDictionaryEntry(
                key=EXTENSION_PAYLOAD_KEY,
                value_type=3,
                string_value=serialized,
            ),
        ],
    )


def _extension_payload(model: Model) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _add_resource_extensions(payload, model)
    _add_view_extensions(payload, model)
    return payload


def _add_resource_extensions(payload: dict[str, Any], model: Model) -> None:
    line_styles = _user_line_styles(model.line_styles)
    if line_styles:
        payload["line_styles"] = [_line_style(style) for style in line_styles]
    if model.layer_folders:
        layers_by_id = {layer.id: layer.name for layer in model.layers}
        payload["layer_folders"] = [_layer_folder(folder, layers_by_id, set()) for folder in model.layer_folders]
    material_pbr = {
        material.name: [material.metallic, material.roughness]
        for material in model.materials
        if material.metallic != 0.0 or material.roughness != 1.0
    }
    if material_pbr:
        payload["material_pbr"] = material_pbr
    layer_material_pbr = {
        layer.name: [layer.material.metallic, layer.material.roughness]
        for layer in model.layers
        if layer.material is not None and (layer.material.metallic != 0.0 or layer.material.roughness != 1.0)
    }
    if layer_material_pbr:
        payload["layer_material_pbr"] = layer_material_pbr
    if model.environment_data is not None:
        payload["environment"] = _environment(model)
    if model.sun_data is not None:
        payload["sun"] = _bytes(model.sun_data.raw_payload)
    definitions = {
        definition.name: {"packed_payload": _bytes(definition.packed_payload)}
        for definition in model.definitions
        if definition.packed_payload is not None
    }
    if definitions:
        payload["definitions"] = definitions
    scopes = _entity_scope_extensions(model)
    if scopes:
        payload["entity_scopes"] = scopes


def _add_view_extensions(payload: dict[str, Any], model: Model) -> None:
    if model.model_view_axes is not None and model.model_view_axes.flags:
        payload["axes_flags"] = model.model_view_axes.flags
    if model.cameras and not model.cameras[0].allow_clipping:
        payload["camera_allow_clipping"] = False
    if model.shadow_info is not None and model.shadow_info.edges_cast_shadows:
        payload["shadow_edges_cast_shadows"] = True
    scene_extensions = {
        scene.name: {
            **({"allow_clipping": False} if scene.camera is not None and not scene.camera.allow_clipping else {}),
            **({"raw_payload": _bytes(scene.raw_payload)} if scene.raw_payload is not None else {}),
        }
        for scene in model.scenes
        if (scene.camera is not None and not scene.camera.allow_clipping) or scene.raw_payload is not None
    }
    if scene_extensions:
        payload["scenes"] = scene_extensions
    if model.rendering_options is not None:
        rendering = model.rendering_options
        payload["rendering"] = {
            "ambient_occlusion": rendering.ambient_occlusion,
            "ao_color": rendering.ao_color,
            "ao_color_enabled": rendering.ao_color_enabled,
            "ao_distance": rendering.ao_distance,
            "ao_intensity": rendering.ao_intensity,
            "ao_multiplier": rendering.ao_multiplier,
            "draw_hidden_objects": rendering.draw_hidden_objects,
            "hide_custom_control_points": rendering.hide_custom_control_points,
            "line_style_edges": rendering.line_style_edges,
            "section_cut_filled": rendering.section_cut_filled,
            "section_default_fill_color": rendering.section_default_fill_color,
        }
    style_extensions = _style_extensions(model)
    if style_extensions:
        payload["styles"] = style_extensions


def _user_line_styles(styles: list[LineStyle]) -> list[LineStyle]:
    builtins = [style for style in styles if style.name in _BUILTIN_LINE_STYLES]
    if any(style != _BUILTIN_LINE_STYLES[style.name] for style in builtins):
        raise ValueError("Legacy built-in line styles cannot be modified")
    users = [style for style in styles if style.name not in _BUILTIN_LINE_STYLES]
    names = [style.name for style in users]
    if len(names) != len(set(names)):
        raise ValueError("Legacy user line-style names must be unique")
    for style in users:
        values = (style.stipple_scale, style.line_width_points)
        if not style.name or "\x00" in style.name:
            raise ValueError("Legacy line-style names must be non-empty and contain no NUL")
        if not style.dash_pattern or "\x00" in style.dash_pattern:
            raise ValueError("Legacy line-style dash patterns must be non-empty")
        if any(not isfinite(value) for value in values) or style.stipple_scale == 0.0 or style.line_width_points <= 0.0:
            raise ValueError("Legacy line-style scales and widths must be finite and non-zero")
        if not isinstance(style.color, int) or not 0 <= style.color <= 0xFFFFFFFF:
            raise ValueError("Legacy line-style color must fit in u32")
    return users


def _line_style(style: LineStyle) -> dict[str, Any]:
    return {
        "color": style.color,
        "dash_pattern": style.dash_pattern,
        "line_width_points": style.line_width_points,
        "mutability": style.mutability,
        "name": style.name,
        "stipple_scale": style.stipple_scale,
    }


def _layer_folder(folder: LayerFolder, layers_by_id: dict[int, str], ancestors: set[int]) -> dict[str, Any]:
    if id(folder) in ancestors:
        raise ValueError("Legacy layer-folder hierarchy contains a cycle")
    missing = next((layer_id for layer_id in folder.child_layer_ids if layer_id not in layers_by_id), None)
    if missing is not None:
        raise ValueError(f"Legacy layer folder references unknown layer {missing}")
    descendants = {*ancestors, id(folder)}
    return {
        "children": [_layer_folder(child, layers_by_id, descendants) for child in folder.child_folders],
        "layers": [layers_by_id[layer_id] for layer_id in folder.child_layer_ids],
        "name": folder.name,
        "visible": folder.visible,
    }


def _environment(model: Model) -> dict[str, Any]:
    environment = model.environment_data
    assert environment is not None
    if environment.selected is None:
        raise ValueError("Writing legacy environment data requires a selected environment")
    entries = environment.entries or [environment.selected]
    if environment.selected not in entries:
        raise ValueError("Selected legacy environment must be present in entries")
    ids = [entry.id for entry in entries]
    names = [entry.name for entry in entries]
    if len(ids) != len(set(ids)) or any(entry_id <= 0 for entry_id in ids):
        raise ValueError("Legacy environment IDs must be positive and unique")
    if len(names) != len(set(names)):
        raise ValueError("Legacy environment names must be unique")
    return {
        "entries": [_environment_entry(entry) for entry in entries],
        "selected": environment.selected.id,
    }


def _environment_entry(entry: EnvironmentEntry) -> dict[str, Any]:
    if not entry.name or not _safe_name(entry.name) or not entry.image_filename or not _safe_name(entry.image_filename):
        raise ValueError("Legacy environment names and image filenames must be non-empty and path-safe")
    if entry.image_data is None:
        raise ValueError("Legacy environment image data is required for writing")
    thumbnail = PurePosixPath(entry.thumbnail_path)
    if entry.thumbnail_path and (thumbnail.is_absolute() or ".." in thumbnail.parts):
        raise ValueError("Legacy environment thumbnail paths must be archive-relative")
    values = (entry.rotation, entry.skydome_exposure, entry.reflection_exposure)
    if any(not isfinite(value) for value in values):
        raise ValueError("Legacy environment numeric values must be finite")
    if not 0.0 <= entry.rotation < 360.0:
        raise ValueError("Legacy environment rotation must be in [0, 360)")
    if not 0.0 <= entry.skydome_exposure <= 20.0 or not 0.0 <= entry.reflection_exposure <= 20.0:
        raise ValueError("Legacy environment exposure must be in [0, 20]")
    return {
        "description": entry.description,
        "id": entry.id,
        "image_data": _bytes(entry.image_data),
        "image_filename": entry.image_filename,
        "name": entry.name,
        "reflection_exposure": entry.reflection_exposure,
        "rotation": entry.rotation,
        "skydome_exposure": entry.skydome_exposure,
        "thumbnail_data": _bytes(entry.thumbnail_data),
        "thumbnail_path": entry.thumbnail_path,
        "use_as_skydome": entry.use_as_skydome,
        "use_for_reflections": entry.use_for_reflections,
    }


def _style_extensions(model: Model) -> dict[str, Any]:
    registry = model.styles_registry
    if registry is None:
        return {}
    styles = [*registry.styles]
    if registry.inline_style_override is not None:
        styles.append(registry.inline_style_override)
    return {
        str(index): {
            "display_name": style.display_name,
            "xml_data": _bytes(style.xml_data),
        }
        for index, style in enumerate(styles, start=1)
        if style.display_name != style.file_name or style.xml_data is not None
    }


def _entity_scope_extensions(model: Model) -> dict[str, Any]:
    scopes: dict[str, Any] = {}
    root = _entity_scope(model.entities)
    if root:
        scopes["root"] = root
    definitions = {
        definition.name: scope for definition in model.definitions if (scope := _entity_scope(definition.entities))
    }
    if definitions:
        scopes["definitions"] = definitions
    return scopes


def _entity_scope(entities: Entities) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    edge_positions = {edge.id: index for index, edge in enumerate(entities.edges)}
    raw_arcs = []
    for arc in entities.arc_curves:
        semantic = (arc.center, arc.normal, arc.radius, arc.start_angle, arc.end_angle)
        if arc.raw_arc_payload is not None and all(value is None for value in semantic):
            if len(arc.raw_arc_payload) != 128:
                raise ValueError(f"Legacy arc curve {arc.id} needs a 128-byte raw payload")
            try:
                positions = [edge_positions[edge_id] for edge_id in arc.edge_ids]
            except KeyError as exc:
                raise ValueError(f"Legacy raw arc references missing edge ID {exc.args[0]}") from exc
            raw_arcs.append({"edges": positions, "payload": _bytes(arc.raw_arc_payload)})
    if raw_arcs:
        scope["raw_arcs"] = raw_arcs
    sections = {
        str(index): {"name": section.name, "symbol": section.symbol}
        for index, section in enumerate(entities.section_planes)
        if section.name or section.symbol
    }
    if sections:
        scope["sections"] = sections
    return scope


def _bytes(value: bytes | None) -> str | None:
    return base64.b64encode(value).decode("ascii") if value is not None else None


def _safe_name(value: str) -> bool:
    return value not in {".", ".."} and not any(character in value for character in "/\\")
