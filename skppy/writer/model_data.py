# SPDX-License-Identifier: MIT
"""Assembly of the modern ``model.dat`` root record."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .._atomic_io import atomic_write
from ..data_structure.annotations import Dimension, Text
from ..data_structure.entities import (
    ArcCurve,
    ComponentInstance,
    Curve,
    Entities,
    Group,
    Image,
)
from ..data_structure.header import SkpHeader
from ..data_structure.model import Model
from ..data_structure.model_metadata import Font, WatermarkManager
from ..data_structure.scene_data import PageBackgroundImage
from ..parser.tlv import TlvTag
from .annotation_styles import encode_dimension_style, encode_text_style
from .background_images import background_image_entries, encode_background_images
from .container import build_modern_container
from .cameras import encode_cameras
from .definitions import encode_definitions
from .entities import PointReferenceIdResolver, encode_entities
from .environments import encode_environment_data, environment_entries
from .fonts import default_fonts, encode_fonts
from .layers import (
    count_layer_folders,
    encode_layers,
    layer_material_entries,
)
from .line_styles import encode_line_styles, user_line_styles
from .materials import encode_materials, material_entries
from .model_metadata import (
    encode_model_view_axes,
    encode_rendering_options,
    encode_shadow_info,
)
from .options import encode_options_manager
from .scenes import encode_scenes
from .sun_data import encode_sun_data
from .styles import encode_styles_registry, style_entries
from .tlv import encode_compact_int, encode_record, encode_records
from .watermarks import encode_watermark_manager, watermark_entries


@dataclass(frozen=True, slots=True)
class _ModelIdPlan:
    material_ids: dict[int, int]
    layer_ids: dict[int, int]
    display_material_ids: dict[int, int]
    first_folder_id: int
    definition_ids: dict[int, int]
    definition_entity_ids: dict[int, dict[int, int]]
    geometry_ids: dict[int, int]
    scene_ids: dict[int, int]
    environment_ids: dict[int, int]
    line_style_ids: dict[int, int]
    watermark_ids: dict[int, int]
    background_image_object_ids: dict[int, int]
    background_image_reference_ids: dict[int, int]


def default_modern_header() -> SkpHeader:
    """Return the modern VFF header used by the current writer target."""
    return SkpHeader(
        product_name="SketchUp Model",
        version_string="{26.1.103}",
        version_tuple=(26, 1, 103),
        vff_magic="VFF",
        vff_field_1=8,
        vff_field_2=1,
        vff_field_3=17,
        vff_field_4=0x2CAA_A153,
        zip_offset=None,
    )


def encode_model_data(model: Model) -> bytes:
    """Encode the supported model graph as a complete ``model.dat`` stream."""
    fonts = model.fonts or default_fonts()
    _validate_supported_model(model, fonts)
    font_id_map = {id(font): font_id for font_id, font in enumerate(fonts, start=2)}
    id_plan = _create_id_plan(model)

    fields: list[tuple[int, bytes]] = []
    if model.materials:
        fields.append(
            (
                TlvTag.MATERIALS_BLOCK,
                encode_materials(
                    model.materials,
                    id_plan.material_ids,
                    model.attribute_dictionaries_by_object_id,
                ),
            )
        )
    if model.layers or model.layer_folders:
        fields.append(
            (
                TlvTag.LAYERS_BLOCK,
                encode_layers(
                    model.layers,
                    model.layer_folders,
                    layer_id_map=id_plan.layer_ids,
                    display_material_id_map=id_plan.display_material_ids,
                    first_folder_id=id_plan.first_folder_id,
                    active_layer_id=model.active_layer_id,
                    attribute_dictionaries_by_object_id=(model.attribute_dictionaries_by_object_id),
                ),
            )
        )
    if model.definitions:
        fields.append(
            (
                TlvTag.DEFINITIONS_BLOCK,
                encode_definitions(
                    model.definitions,
                    definition_id_map=id_plan.definition_ids,
                    entity_id_maps=id_plan.definition_entity_ids,
                    material_id_map=id_plan.material_ids,
                    layer_id_map=id_plan.layer_ids,
                    attribute_dictionaries_by_object_id=(model.attribute_dictionaries_by_object_id),
                    point_reference_id_resolvers={
                        definition.id: _point_reference_id_resolver(
                            model,
                            id_plan,
                            definition_id=definition.id,
                        )
                        for definition in model.definitions
                    },
                    font_id_map=font_id_map,
                ),
            )
        )
    if model.cameras:
        fields.append((TlvTag.CAMERA_BLOCK, encode_cameras(model.cameras)))
    if model.rendering_options is not None:
        fields.append(
            (
                TlvTag.RENDERING_OPTIONS,
                encode_rendering_options(model.rendering_options),
            )
        )
    fields.extend(_option_fields(model))
    if model.model_view_axes is not None:
        fields.append((TlvTag.MODEL_VIEW, encode_model_view_axes(model.model_view_axes)))
    fields.extend(_line_style_fields(model, id_plan))
    fields.append((TlvTag.FONTS, encode_fonts(fonts)))
    fields.extend(_annotation_style_fields(model, len(fonts)))
    fields.extend(_background_image_fields(model, id_plan))
    fields.extend(_watermark_fields(model, id_plan))
    if model.shadow_info is not None:
        fields.append((TlvTag.SHADOW_INFO_BLOCK, encode_shadow_info(model.shadow_info)))
    fields.extend(_sun_fields(model))
    if model.scenes:
        fields.append(
            (
                TlvTag.SCENES_BLOCK,
                encode_scenes(
                    model.scenes,
                    scene_id_map=id_plan.scene_ids,
                    entity_id_map=id_plan.geometry_ids,
                    layer_id_map=id_plan.layer_ids,
                    background_image_object_ids=(id_plan.background_image_object_ids),
                    background_image_reference_ids=(id_plan.background_image_reference_ids),
                ),
            )
        )
    if model.environment_data is not None:
        fields.append(
            (
                TlvTag.ENVIRONMENT_DATA_BLOCK,
                encode_environment_data(model.environment_data, id_plan.environment_ids),
            )
        )
    fields.append(
        (
            TlvTag.ENTITIES_BLOCK,
            encode_entities(
                model.entities,
                id_map=id_plan.geometry_ids,
                material_id_map=id_plan.material_ids,
                layer_id_map=id_plan.layer_ids,
                definition_id_map=id_plan.definition_ids,
                font_id_map=font_id_map,
                scope_attribute_dictionaries=model.attribute_dictionaries,
                point_reference_id_resolver=_point_reference_id_resolver(model, id_plan),
            ),
        )
    )
    fields.extend(_style_fields(model, id_plan))
    root_payload = encode_records(fields)
    return encode_record(TlvTag.MODEL_ROOT, root_payload)


def _line_style_fields(model: Model, id_plan: _ModelIdPlan) -> list[tuple[int, bytes]]:
    if not model.line_styles:
        return []
    return [
        (
            TlvTag.LINE_STYLES_BLOCK,
            encode_line_styles(model.line_styles, id_plan.line_style_ids),
        )
    ]


def _annotation_style_fields(model: Model, font_count: int) -> list[tuple[int, bytes]]:
    fields: list[tuple[int, bytes]] = []
    if model.text_style is not None:
        fields.append((TlvTag.TEXT_STYLE_BLOCK, encode_text_style(model.text_style, font_count)))
    if model.dimension_style is not None:
        fields.append(
            (
                TlvTag.DIMENSION_STYLE_BLOCK,
                encode_dimension_style(model.dimension_style, font_count),
            )
        )
    return fields


def _option_fields(model: Model) -> list[tuple[int, bytes]]:
    if model.options_manager is None:
        return []
    return [
        (
            TlvTag.OPTIONS_MANAGER_BLOCK,
            encode_options_manager(model.options_manager),
        )
    ]


def _sun_fields(model: Model) -> list[tuple[int, bytes]]:
    if model.sun_data is None:
        return []
    return [(TlvTag.SUN_DATA_BLOCK, encode_sun_data(model.sun_data))]


def _watermark_fields(model: Model, id_plan: _ModelIdPlan) -> list[tuple[int, bytes]]:
    if model.watermark_manager is None and model.styles_registry is None:
        return []
    return [
        (
            TlvTag.WATERMARKS_BLOCK,
            encode_watermark_manager(model.watermark_manager or WatermarkManager(), id_plan.watermark_ids),
        )
    ]


def _background_image_fields(model: Model, id_plan: _ModelIdPlan) -> list[tuple[int, bytes]]:
    images = _background_images(model)
    if not images:
        return []
    fields: list[tuple[int, bytes]] = [
        (
            TlvTag.BACKGROUND_IMAGES_BLOCK,
            encode_background_images(images, id_plan.background_image_object_ids),
        )
    ]
    if model.background_image is not None:
        fields.append(
            (
                TlvTag.ACTIVE_BACKGROUND_IMAGE_REF,
                encode_compact_int(id_plan.background_image_object_ids[id(model.background_image)]),
            )
        )
    return fields


def _style_fields(model: Model, id_plan: _ModelIdPlan) -> list[tuple[int, bytes]]:
    if model.styles_registry is None:
        return []
    return [
        (
            TlvTag.STYLES_REGISTRY_BLOCK,
            encode_styles_registry(model.styles_registry, id_plan.watermark_ids),
        )
    ]


def _scope_id_map(entities: Entities, *, first_id: int) -> dict[int, int]:
    source_ids = [vertex.id for vertex in entities.vertices]
    curves: tuple[Curve | ArcCurve, ...] = (
        *entities.curves,
        *entities.arc_curves,
    )
    curve_edge_ids = [edge_id for curve in curves for edge_id in curve.edge_ids]
    curve_edge_id_set = set(curve_edge_ids)
    source_ids.extend(curve_edge_ids)
    source_ids.extend(edge.id for edge in entities.edges if edge.id not in curve_edge_id_set)
    source_ids.extend(face.id for face in entities.faces)
    source_ids.extend(instance.id for instance in entities.component_instances)
    source_ids.extend(group.id for group in entities.groups)
    source_ids.extend(image.id for image in entities.images)
    source_ids.extend(curve.id for curve in entities.curves)
    source_ids.extend(arc.id for arc in entities.arc_curves)
    source_ids.extend(line.id for line in entities.guide_lines)
    source_ids.extend(point.id for point in entities.guide_points)
    source_ids.extend(plane.id for plane in entities.section_planes)
    source_ids.extend(text.id for text in entities.texts)
    source_ids.extend(dimension.id for dimension in entities.linear_dimensions)
    source_ids.extend(dimension.id for dimension in entities.radial_dimensions)
    return {source_id: generated_id for generated_id, source_id in enumerate(source_ids, start=first_id)}


def _model_id_map(objects: Iterable[object], *, first_id: int) -> dict[int, int]:
    return {
        source_id: generated_id
        for generated_id, source_id in enumerate((getattr(item, "id") for item in objects), start=first_id)
    }


def _create_id_plan(model: Model) -> _ModelIdPlan:
    next_id = 18
    line_style_ids = {id(style): next_id + index for index, style in enumerate(user_line_styles(model.line_styles))}
    next_id += len(line_style_ids)
    material_ids = _model_id_map(model.materials, first_id=next_id)
    next_id += len(material_ids)
    layer_ids = _model_id_map(model.layers, first_id=next_id)
    next_id += len(layer_ids)
    display_material_ids = {layer.id: next_id + index for index, layer in enumerate(model.layers)}
    next_id += len(display_material_ids)
    first_folder_id = next_id
    next_id += count_layer_folders(model.layer_folders)
    definition_ids = _model_id_map(model.definitions, first_id=next_id)
    next_id += len(definition_ids)
    definition_entity_ids = {}
    for definition in model.definitions:
        entity_ids = _scope_id_map(definition.entities, first_id=next_id)
        definition_entity_ids[definition.id] = entity_ids
        next_id += len(entity_ids)
    geometry_ids = _scope_id_map(model.entities, first_id=next_id)
    next_id += len(geometry_ids)
    scene_ids = _model_id_map(model.scenes, first_id=next_id)
    next_id += len(scene_ids)
    environment_entries_to_map = []
    if model.environment_data is not None and model.environment_data.selected is not None:
        environment_entries_to_map = model.environment_data.entries or [model.environment_data.selected]
    environment_ids = _model_id_map(environment_entries_to_map, first_id=next_id)
    next_id += len(environment_ids)
    watermarks = model.watermark_manager.watermarks if model.watermark_manager is not None else []
    watermark_ids = {watermark.id or index: next_id + index - 1 for index, watermark in enumerate(watermarks, start=1)}
    next_id += len(watermark_ids)
    background_images = _background_images(model)
    background_image_object_ids = {id(image): next_id + index for index, image in enumerate(background_images)}
    background_image_reference_ids = {
        image.id: background_image_object_ids[id(image)] for image in background_images if image.id
    }
    return _ModelIdPlan(
        material_ids=material_ids,
        layer_ids=layer_ids,
        display_material_ids=display_material_ids,
        first_folder_id=first_folder_id,
        definition_ids=definition_ids,
        definition_entity_ids=definition_entity_ids,
        geometry_ids=geometry_ids,
        scene_ids=scene_ids,
        environment_ids=environment_ids,
        line_style_ids=line_style_ids,
        watermark_ids=watermark_ids,
        background_image_object_ids=background_image_object_ids,
        background_image_reference_ids=background_image_reference_ids,
    )


def _point_reference_id_resolver(
    model: Model,
    id_plan: _ModelIdPlan,
    *,
    definition_id: int | None = None,
) -> PointReferenceIdResolver:
    definitions = {definition.id: definition for definition in model.definitions}

    def resolve(entity_id: int, instance_path_ids: tuple[int, ...]) -> tuple[int, tuple[int, ...]]:
        if definition_id is None:
            entities = model.entities
            entity_id_map = id_plan.geometry_ids
        else:
            try:
                entities = definitions[definition_id].entities
                entity_id_map = id_plan.definition_entity_ids[definition_id]
            except KeyError as exc:
                raise ValueError(f"Unknown point-reference definition ID {definition_id}") from exc

        mapped_path: list[int] = []
        for instance_id in instance_path_ids:
            try:
                mapped_path.append(entity_id_map[instance_id])
            except KeyError as exc:
                raise ValueError(f"Point-reference path contains unknown entity ID {instance_id}") from exc
            instances: tuple[ComponentInstance | Group | Image, ...] = (
                *entities.component_instances,
                *entities.groups,
                *entities.images,
            )
            instance = next(
                (candidate for candidate in instances if candidate.id == instance_id),
                None,
            )
            if instance is None:
                raise ValueError(f"Point-reference path entity {instance_id} is not an instance")
            try:
                definition = definitions[instance.definition_id]
                entity_id_map = id_plan.definition_entity_ids[instance.definition_id]
            except KeyError as exc:
                raise ValueError(
                    f"Point-reference path instance references unknown definition {instance.definition_id}"
                ) from exc
            entities = definition.entities

        try:
            mapped_entity_id = entity_id_map[entity_id]
        except KeyError as exc:
            raise ValueError(f"Point reference contains unknown leaf entity ID {entity_id}") from exc
        return mapped_entity_id, tuple(mapped_path)

    return resolve


def build_model_container(
    model: Model,
    *,
    header: SkpHeader | None = None,
    extra_entries: Mapping[str, bytes] | None = None,
) -> bytes:
    """Build a modern SKP container from the currently supported model graph."""
    entries = _model_entries(model, extra_entries)
    return build_modern_container(entries, header or default_modern_header())


def write_model(
    model: Model,
    filepath: str | Path,
    *,
    header: SkpHeader | None = None,
) -> Path:
    """Validate, serialize, and write a model to a modern SKP file."""
    path = Path(filepath)
    encoded = build_model_container(
        model,
        header=header,
    )
    atomic_write(path, encoded)
    return path


def _model_entries(
    model: Model,
    extra_entries: Mapping[str, bytes] | None,
) -> dict[str, bytes]:
    entries = dict(extra_entries or {})
    if "model.dat" in entries:
        raise ValueError("extra_entries cannot replace generated model.dat")
    entries["model.dat"] = encode_model_data(model)
    for name, payload in material_entries(model.materials).items():
        if name in entries:
            raise ValueError(f"extra_entries conflicts with generated entry: {name}")
        entries[name] = payload
    id_plan = _create_id_plan(model)
    for name, payload in layer_material_entries(
        model.layers,
        id_plan.display_material_ids,
    ).items():
        if name in entries:
            raise ValueError(f"Generated ZIP entries conflict at: {name}")
        entries[name] = payload
    _merge_entries(entries, environment_entries(model.environment_data))
    _merge_entries(entries, style_entries(model.styles_registry, model.watermark_manager))
    _merge_entries(entries, watermark_entries(model.watermark_manager))
    _merge_entries(entries, background_image_entries(_background_images(model)))
    return entries


def _merge_entries(target: dict[str, bytes], generated: Mapping[str, bytes]) -> None:
    for name, payload in generated.items():
        if name in target:
            raise ValueError(f"Generated ZIP entries conflict at: {name}")
        target[name] = payload


def _validate_supported_model(model: Model, fonts: list[Font]) -> None:
    _validate_model_object_ids(model)
    _validate_model_attribute_owners(model)
    _validate_annotation_fonts(model, fonts)
    _validate_scene_references(model)


def _validate_model_object_ids(model: Model) -> None:
    model_object_ids = [definition.id for definition in model.definitions]
    model_object_ids.extend(material.id for material in model.materials)
    model_object_ids.extend(layer.id for layer in model.layers)
    if any(object_id <= 0 for object_id in model_object_ids):
        raise ValueError("Model object IDs must be positive")
    if len(model_object_ids) != len(set(model_object_ids)):
        raise ValueError("Definition, material, and layer IDs must be globally unique")
    layer_ids = {layer.id for layer in model.layers}
    if model.active_layer_id is not None and model.active_layer_id not in layer_ids:
        raise ValueError("Active layer does not exist in the model")


def _validate_model_attribute_owners(model: Model) -> None:
    supported_ids = {definition.id for definition in model.definitions}
    supported_ids.update(material.id for material in model.materials)
    supported_ids.update(layer.id for layer in model.layers)
    unsupported_attribute_owners = set(model.attribute_dictionaries_by_object_id) - supported_ids
    if unsupported_attribute_owners:
        raise NotImplementedError(
            "Modern model writer does not support attribute dictionaries for "
            f"object IDs: {sorted(unsupported_attribute_owners)}"
        )


def _validate_annotation_fonts(model: Model, fonts: list[Font]) -> None:
    font_id_map = {id(font): font_id for font_id, font in enumerate(fonts, start=2)}
    valid_font_ids = set(font_id_map.values())
    scopes = [
        model.entities,
        *(definition.entities for definition in model.definitions),
    ]
    for scope in scopes:
        annotations: tuple[Dimension | Text, ...] = (
            *scope.texts,
            *scope.linear_dimensions,
            *scope.radial_dimensions,
        )
        for annotation in annotations:
            mapped_font_id = font_id_map.get(id(annotation.font)) if annotation.font is not None else None
            if annotation.font is not None and mapped_font_id is None:
                raise ValueError("Annotation font is not registered in model.fonts")
            if annotation.font_id is not None and annotation.font_id not in valid_font_ids:
                raise ValueError("Annotation font_id does not identify a written model font")
            if mapped_font_id is not None and annotation.font_id is not None and annotation.font_id != mapped_font_id:
                raise ValueError("Annotation font and font_id identify different fonts")


def _validate_scene_references(model: Model) -> None:
    style_count = len(model.styles_registry.styles) if model.styles_registry is not None else 0
    background_images = {image.id: image for image in _background_images(model) if image.id}
    for scene in model.scenes:
        if scene.style_reference and not 1 <= scene.style_reference <= style_count:
            raise ValueError("Scene style reference does not identify a written style")
        background_image = scene.background_image
        if background_image is None and scene.background_image_ref:
            background_image = background_images.get(scene.background_image_ref)
        if background_image is not None and scene.display_background_image != background_image.visible:
            raise ValueError("Scene background display state must match its background image")


def _background_images(model: Model) -> list[PageBackgroundImage]:
    images: list[PageBackgroundImage] = []
    seen: set[int] = set()
    candidates = [
        model.background_image,
        *(scene.background_image for scene in model.scenes),
    ]
    for image in candidates:
        if image is None or id(image) in seen:
            continue
        seen.add(id(image))
        images.append(image)
    return images
