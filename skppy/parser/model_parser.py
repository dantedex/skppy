# SPDX-License-Identifier: MIT
"""
Full model.dat -> Model pipeline.

Usage::

    import zipfile
    from skppy.parser.model_parser import parse_model

    with zipfile.ZipFile(filepath) as zf:
        data = zf.read("model.dat")
    model = parse_model(data, zf, header, document)
"""

from __future__ import annotations

import logging
import struct
import zipfile as _zipfile
from typing import TYPE_CHECKING

from ..data_structure.construction import ShadowInfo
from ..data_structure.model import Model
from ..data_structure.model_metadata import (
    AttributeDictionary,
    DimensionStyle,
    EnvironmentData,
    EnvironmentEntry,
    Font,
    LineStyle,
    ModelViewAxes,
    OptionsManager,
    OptionsProvider,
    StyleDescriptor,
    StylesRegistry,
    SunData,
    TextStyle,
    Watermark,
    WatermarkManager,
)
from .attributes import parse_attribute_dictionaries
from .background_images import parse_background_images
from .camera_parser import parse_cameras
from .definitions import parse_definitions
from .entities import parse_entities
from .layers import parse_layers
from .material_parser import build_zip_name_map, parse_materials
from .rendering_options import parse_rendering_options
from .scenes_parser import parse_scenes
from .tlv import (
    TlvTag,
    find_child,
    find_model_root,
    index_children,
    iter_records,
    read_bool,
    read_compact_int,
    read_f64_le,
    read_id_from_wrapper,
    read_record,
    read_utf8,
    read_vec3,
)

if TYPE_CHECKING:
    from ..data_structure.document import SkpDocument
    from ..data_structure.header import SkpHeader

logger = logging.getLogger(__name__)


def parse_model(
    data: bytes,
    zip_file: _zipfile.ZipFile,
    header: "SkpHeader",
    document: "SkpDocument",
    *,
    import_vray_materials: bool = False,
) -> Model:
    """
    Decode a model.dat byte string and return a fully populated Model.

    Parameters
    ----------
    data : bytes
        Raw bytes of the model.dat entry from the .skp ZIP archive.
    zip_file : zipfile.ZipFile
        Open ZIP handle used to load embedded texture images.
    header : SkpHeader
        Parsed header returned by ``parse_header()``.
    document : SkpDocument
        Parsed document metadata (version, guid, etc.).

    Returns
    -------
    Model
        Fully assembled model containing entities, materials, layers,
        definitions, cameras, scenes, and rendering options.
    """
    root_offset = find_model_root(data)
    _, root_payload, _ = read_record(data, root_offset)
    root_fields = index_children(root_payload)
    attribute_dictionaries_by_object_id: dict[int, list[AttributeDictionary]] = {}
    # Model is the mutable public result. Keep construction near the parsing
    # boundary and install each independently decoded section below.
    model = Model(header=header, document=document)

    _install_geometry_and_resources(
        model,
        root_fields,
        zip_file,
        attribute_dictionaries_by_object_id,
        import_vray_materials=import_vray_materials,
    )
    _install_visual_metadata(model, root_fields, zip_file)
    _install_annotation_metadata(model, root_fields)
    _install_environment_metadata(model, root_fields)
    _install_document_metadata(model, root_fields, zip_file)

    model.attribute_dictionaries_by_object_id = attribute_dictionaries_by_object_id
    _post_process(model)
    return model


def _install_geometry_and_resources(
    model: Model,
    root_fields: dict[int, bytes],
    zip_file: _zipfile.ZipFile,
    attributes_by_object_id: dict[int, list[AttributeDictionary]],
    *,
    import_vray_materials: bool = False,
) -> None:
    """Decode geometry, reusable definitions, materials, and layer ownership."""
    zip_name_map = build_zip_name_map(zip_file)
    entities_block = root_fields.get(TlvTag.ENTITIES_BLOCK)
    if entities_block:
        payload = find_child(entities_block, TlvTag.ENTITIES)
        if payload:
            model.entities = parse_entities(payload)
            logger.debug(
                "Root entities: %d vertices, %d edges, %d faces, %d instances, %d groups",
                len(model.entities.vertices),
                len(model.entities.edges),
                len(model.entities.faces),
                len(model.entities.component_instances),
                len(model.entities.groups),
            )

    materials_block = root_fields.get(TlvTag.MATERIALS_BLOCK)
    if materials_block:
        container = find_child(materials_block, TlvTag.MATERIALS_CONTAINER)
        if container:
            model.materials = parse_materials(
                container,
                zip_file,
                zip_name_map=zip_name_map,
                attribute_dictionaries_by_object_id=attributes_by_object_id,
                import_vray_materials=import_vray_materials,
            )
            logger.debug("Parsed %d materials", len(model.materials))

    layers_block = root_fields.get(TlvTag.LAYERS_BLOCK)
    if layers_block:
        container = find_child(layers_block, TlvTag.LAYERS_CONTAINER)
        if container:
            model.layers, model.layer_folders = parse_layers(
                container,
                zip_file,
                zip_name_map=zip_name_map,
                attribute_dictionaries_by_object_id=attributes_by_object_id,
                import_vray_materials=import_vray_materials,
            )
            logger.debug(
                "Parsed %d layers, %d folders, %d inline materials",
                len(model.layers),
                len(model.layer_folders),
                sum(layer.material is not None for layer in model.layers),
            )
        # Real modern files place ACTIVE_LAYER_ID inside LAYERS_CONTAINER.
        # Keep the outer lookup as a compatibility fallback for early variants.
        active_payload = (find_child(container, TlvTag.ACTIVE_LAYER_ID) if container else None) or find_child(
            layers_block, TlvTag.ACTIVE_LAYER_ID
        )
        if active_payload:
            model.active_layer_id = read_compact_int(active_payload)

    definitions_block = root_fields.get(TlvTag.DEFINITIONS_BLOCK)
    if definitions_block:
        container = find_child(definitions_block, TlvTag.DEFINITIONS_CONTAINER)
        if container:
            model.definitions = parse_definitions(
                container,
                attribute_dictionaries_by_object_id=attributes_by_object_id,
            )
            logger.debug(
                "Parsed %d definitions (%d total verts, %d total faces)",
                len(model.definitions),
                sum(len(item.entities.vertices) for item in model.definitions),
                sum(len(item.entities.faces) for item in model.definitions),
            )


def _install_visual_metadata(
    model: Model,
    root_fields: dict[int, bytes],
    zip_file: _zipfile.ZipFile,
) -> None:
    """Decode cameras and visual settings that affect the modeled viewport."""
    if payload := root_fields.get(TlvTag.CAMERA_BLOCK):
        model.cameras = parse_cameras(payload)
        logger.debug("Parsed %d camera(s)", len(model.cameras))
    if payload := root_fields.get(TlvTag.RENDERING_OPTIONS):
        model.rendering_options = parse_rendering_options(payload)
    if payload := root_fields.get(TlvTag.SHADOW_INFO_BLOCK):
        model.shadow_info = _parse_shadow_info(payload)
    if payload := root_fields.get(TlvTag.WATERMARKS_BLOCK):
        model.watermark_manager = _parse_watermarks(payload, zip_file)
    if payload := root_fields.get(TlvTag.STYLES_REGISTRY_BLOCK):
        model.styles_registry = _parse_styles_registry(payload, zip_file)


def _install_annotation_metadata(model: Model, root_fields: dict[int, bytes]) -> None:
    """Decode font, text, dimension, and line-style registries."""
    if payload := root_fields.get(TlvTag.FONTS):
        model.fonts = _parse_fonts(payload)
    if payload := root_fields.get(TlvTag.TEXT_STYLE_BLOCK):
        model.text_style = _parse_text_style(payload)
    if payload := root_fields.get(TlvTag.DIMENSION_STYLE_BLOCK):
        model.dimension_style = _parse_dimension_style(payload)
    if payload := root_fields.get(TlvTag.LINE_STYLES_BLOCK):
        model.line_styles = _parse_line_styles(payload)


def _install_environment_metadata(model: Model, root_fields: dict[int, bytes]) -> None:
    """Decode options, environment lighting, sun, and sketch-axis settings."""
    if payload := root_fields.get(TlvTag.OPTIONS_MANAGER_BLOCK):
        model.options_manager = _parse_options_manager(payload)
    if payload := root_fields.get(TlvTag.ENVIRONMENT_DATA_BLOCK):
        model.environment_data = _parse_environment_data(payload)
    if payload := root_fields.get(TlvTag.SUN_DATA_BLOCK):
        model.sun_data = _parse_sun_data(payload)
    if payload := root_fields.get(TlvTag.MODEL_VIEW):
        model.model_view_axes = _parse_model_view_axes(payload)


def _install_document_metadata(
    model: Model,
    root_fields: dict[int, bytes],
    zip_file: _zipfile.ZipFile,
) -> None:
    """Decode model-level attribute dictionaries and named scenes."""
    background_images = {}
    background_payload = root_fields.get(TlvTag.BACKGROUND_IMAGES_BLOCK)
    if background_payload is not None:
        background_images = parse_background_images(background_payload, zip_file)
    active_background = root_fields.get(TlvTag.ACTIVE_BACKGROUND_IMAGE_REF)
    if active_background:
        model.background_image = background_images.get(read_compact_int(active_background))
    if payload := root_fields.get(TlvTag.MODEL_PROPERTIES_BLOCK):
        model.attribute_dictionaries = parse_attribute_dictionaries(payload)
    if payload := root_fields.get(TlvTag.SCENES_BLOCK):
        model.scenes = parse_scenes(payload)
        for scene in model.scenes:
            image = background_images.get(scene.background_image_ref)
            if image is not None:
                scene.background_image = image
                scene.display_background_image = image.visible


def _post_process(model: Model) -> None:
    """Sync all ID counters so new entities can be added without ID conflicts."""
    model.entities._sync_id_counter()
    for defn in model.definitions:
        defn.entities._sync_id_counter()
    model._sync_id_counter()


def _parse_shadow_info(shadow_block_payload: bytes) -> ShadowInfo:
    """
    Parse TlvTag.SHADOW_INFO_BLOCK (0x0204) and return a ShadowInfo object.

    The shadow info block contains geo-referenced location data (latitude,
    longitude, timezone) and display settings for shadow calculation.

    Parameters
    ----------
    shadow_block_payload : bytes
        Raw payload of the 0x0204 shadow-info-block TLV record.

    Returns
    -------
    ShadowInfo
        Parsed shadow information.  Fields not present in the file
        retain their default values.
    """
    shadow = ShadowInfo()
    rec_p = find_child(shadow_block_payload, TlvTag.SHADOW_INFO_RECORD)
    if not rec_p:
        return shadow

    def _float(tag: int, default: float = 0.0) -> float:
        p = find_child(rec_p, tag)
        return read_f64_le(p) if p and len(p) >= 8 else default

    def _int(tag: int, default: int = 0) -> int:
        p = find_child(rec_p, tag)
        return read_compact_int(p) if p else default

    def _bool(tag: int, default: bool = False) -> bool:
        p = find_child(rec_p, tag)
        return read_bool(p) if p else default

    shadow.latitude = _float(TlvTag.SHADOW_INFO_LATITUDE)
    shadow.longitude = _float(TlvTag.SHADOW_INFO_LONGITUDE)
    shadow.time = _int(TlvTag.SHADOW_INFO_TIME)
    shadow.daylight_savings = _bool(TlvTag.SHADOW_INFO_DAYLIGHT_SAVINGS)
    shadow.city = find_child(rec_p, TlvTag.SHADOW_INFO_CITY) or b""
    shadow.country = find_child(rec_p, TlvTag.SHADOW_INFO_COUNTRY) or b""
    shadow.timezone_offset = _float(TlvTag.SHADOW_INFO_TIMEZONE_OFFSET)
    north_p = find_child(rec_p, TlvTag.SHADOW_INFO_NORTH_DIRECTION)
    if north_p and len(north_p) >= 24:
        shadow.north_direction = read_vec3(north_p)
    shadow.display_shadows = _bool(TlvTag.SHADOW_INFO_DISPLAY_SHADOWS)
    shadow.display_north = _bool(TlvTag.SHADOW_INFO_DISPLAY_NORTH)
    shadow.display_on_all_faces = _bool(TlvTag.SHADOW_INFO_DISPLAY_ON_ALL_FACES)
    shadow.display_on_ground_plane = _bool(TlvTag.SHADOW_INFO_DISPLAY_ON_GROUND)
    shadow.edges_cast_shadows = _bool(TlvTag.SHADOW_INFO_EDGES_CAST_SHADOWS)
    shadow.light = _int(TlvTag.SHADOW_INFO_LIGHT)
    shadow.dark = _int(TlvTag.SHADOW_INFO_DARK)
    shadow.use_sun_for_all_shading = _bool(TlvTag.SHADOW_INFO_USE_SUN_FOR_ALL_SHADING)
    return shadow


def _parse_watermarks(wm_block_payload: bytes, zip_file: _zipfile.ZipFile | None = None) -> WatermarkManager:
    """
    Parse TlvTag.WATERMARKS_BLOCK (0x0203) and return a WatermarkManager object.
    """
    manager = WatermarkManager()
    rec_p = find_child(wm_block_payload, TlvTag.WATERMARK_MANAGER_RECORD)
    if not rec_p:
        return manager

    list_p = find_child(rec_p, TlvTag.WATERMARK_LIST)
    if list_p:
        for tag, watermark_p in iter_records(list_p):
            if tag != TlvTag.WATERMARK_RECORD:
                continue
            name_p = find_child(watermark_p, TlvTag.WATERMARK_FILE_NAME)
            identity_p = find_child(watermark_p, TlvTag.ID_WRAPPER)
            position_p = find_child(watermark_p, TlvTag.WATERMARK_POSITION)
            fitting_p = find_child(watermark_p, TlvTag.WATERMARK_FITTING_TYPE)
            opacity_p = find_child(watermark_p, TlvTag.WATERMARK_OPACITY)
            image_p = find_child(watermark_p, TlvTag.WATERMARK_IMAGE)
            dib_p = find_child(image_p, TlvTag.DIB_RECORD) if image_p else None
            binary_p = find_child(dib_p, TlvTag.DIB_BINARY) if dib_p else None
            external_p = find_child(dib_p, TlvTag.DIB_EXTERNAL_PATH) if dib_p else None
            image_data = binary_p
            if image_data is None and external_p and zip_file is not None:
                try:
                    image_data = zip_file.read(read_utf8(external_p))
                except KeyError:
                    pass
            manager.watermarks.append(
                Watermark(
                    name=read_utf8(name_p) if name_p else "",
                    image_data=image_data,
                    position=(
                        5
                        if fitting_p and len(fitting_p) >= 4 and struct.unpack_from("<i", fitting_p)[0] == 0
                        else (struct.unpack_from("<i", position_p)[0] if position_p and len(position_p) >= 4 else 0)
                    ),
                    opacity=(read_f64_le(opacity_p) if opacity_p and len(opacity_p) >= 8 else 1.0),
                    id=read_id_from_wrapper(identity_p) if identity_p else 0,
                )
            )
    count_p = find_child(rec_p, TlvTag.WATERMARK_SERIALIZED_COUNT)
    manager.serialized_count = read_compact_int(count_p) if count_p else 0
    return manager


def _parse_styles_registry(sr_block_payload: bytes, zip_file: _zipfile.ZipFile | None = None) -> StylesRegistry:
    """
    Parse TlvTag.STYLES_REGISTRY_BLOCK (0x0206) and return a StylesRegistry object.
    """
    registry = StylesRegistry()
    rec_p = find_child(sr_block_payload, TlvTag.STYLES_REGISTRY)
    if not rec_p:
        return registry

    list_p = find_child(rec_p, TlvTag.STYLE_LIST)
    if list_p:
        for tag, style_p in iter_records(list_p):
            if tag != TlvTag.STYLE_DESCRIPTOR:
                continue
            registry.styles.append(_parse_style_descriptor(style_p, zip_file))

    active_p = find_child(rec_p, TlvTag.ACTIVE_STYLE_REF)
    registry.active_style_ref = read_compact_int(active_p) if active_p else 0

    inline_p = find_child(rec_p, TlvTag.INLINE_STYLE_OVERRIDE)
    if inline_p:
        descriptor_p = find_child(inline_p, TlvTag.STYLE_DESCRIPTOR)
        if descriptor_p:
            registry.inline_style_override = _parse_style_descriptor(descriptor_p, zip_file)

    dirty_p = find_child(rec_p, TlvTag.STYLE_MANAGER_DIRTY)
    registry.selected_style_dirty = read_bool(dirty_p) if dirty_p else False
    return registry


def _parse_style_descriptor(payload: bytes, zip_file: _zipfile.ZipFile | None) -> StyleDescriptor:
    guid_p = find_child(payload, TlvTag.STYLE_GUID)
    display_p = find_child(payload, TlvTag.STYLE_DISPLAY_NAME)
    file_p = find_child(payload, TlvTag.STYLE_FILE_NAME)
    style = StyleDescriptor(
        guid=guid_p[:16] if guid_p else b"\x00" * 16,
        display_name=read_utf8(display_p) if display_p else "",
        file_name=read_utf8(file_p) if file_p else "",
    )
    refs_p = find_child(payload, TlvTag.STYLE_WATERMARK_REFS)
    if refs_p:
        offset = 0
        while offset < len(refs_p):
            width = refs_p[offset]
            offset += 1
            if width == 0 or offset + width > len(refs_p):
                break
            style.watermark_reference_ids.append(int.from_bytes(refs_p[offset : offset + width], "little"))
            offset += width
    resource_name = f"styles/{style.file_name}/style.xml"
    if zip_file is not None and style.file_name:
        try:
            style.xml_data = zip_file.read(resource_name)
        except KeyError:
            pass
    return style


def _parse_fonts(fonts_block_payload: bytes) -> list[Font]:
    """Parse TlvTag.FONTS (0x01FD) and return a list of Font objects."""
    container_p = find_child(fonts_block_payload, TlvTag.FONTS_CONTAINER)
    if not container_p:
        return []
    list_p = find_child(container_p, TlvTag.FONTS_LIST)
    if not list_p:
        return []

    fonts: list[Font] = []
    for tag, rec_p in iter_records(list_p):
        if tag != TlvTag.FONT_RECORD:
            continue
        font = Font()
        face_p = find_child(rec_p, TlvTag.FONT_FACE_NAME)
        font.face_name = read_utf8(face_p) if face_p else ""
        bold_p = find_child(rec_p, TlvTag.FONT_BOLD_FLAG)
        font.bold = read_bool(bold_p) if bold_p else False
        italic_p = find_child(rec_p, TlvTag.FONT_ITALIC_FLAG)
        font.italic = read_bool(italic_p) if italic_p else False
        ps_p = find_child(rec_p, TlvTag.FONT_POINT_SIZE)
        font.point_size = read_compact_int(ps_p) if ps_p else 0
        uws_p = find_child(rec_p, TlvTag.FONT_USE_WORLD_SIZE)
        font.use_world_size = read_bool(uws_p) if uws_p else False
        ws_p = find_child(rec_p, TlvTag.FONT_WORLD_SIZE)
        font.world_size = read_f64_le(ws_p) if ws_p and len(ws_p) >= 8 else 0.0
        fonts.append(font)
    return fonts


def _parse_text_style(ts_block_payload: bytes) -> TextStyle:
    """Parse TlvTag.TEXT_STYLE_BLOCK (0x01FE) and return a TextStyle object."""
    style = TextStyle()
    rec_p = find_child(ts_block_payload, TlvTag.TEXT_STYLE_RECORD)
    if not rec_p:
        return style

    def _int(tag: int, default: int = 0) -> int:
        p = find_child(rec_p, tag)
        return read_compact_int(p) if p else default

    def _bool(tag: int, default: bool = False) -> bool:
        p = find_child(rec_p, tag)
        return read_bool(p) if p else default

    def _color(tag: int) -> int:
        p = find_child(rec_p, tag)
        if p is None or len(p) < 4:
            return 0
        red, green, blue, alpha = p[:4]
        return (alpha << 24) | (red << 16) | (green << 8) | blue

    # This record predates the shared display defaults. Its omitted scalar
    # fields decode as zero, including display_leader.
    style.font_ref = _int(TlvTag.TEXT_STYLE_FONT_REF)
    style.screen_font_ref = _int(TlvTag.TEXT_STYLE_SCREEN_FONT_REF)
    style.arrow_type = _int(TlvTag.TEXT_STYLE_ARROW_TYPE)
    style.line_weight = _int(TlvTag.TEXT_STYLE_LINE_WEIGHT)
    style.hide_out_of_plane = _bool(TlvTag.TEXT_STYLE_HIDE_OUT_OF_PLANE)
    style.leader_type = _int(TlvTag.TEXT_STYLE_LEADER_TYPE)
    style.display_leader = _bool(TlvTag.TEXT_STYLE_DISPLAY_LEADER)
    style.color = _color(TlvTag.TEXT_STYLE_COLOR)
    style.screen_color = _color(TlvTag.TEXT_STYLE_SCREEN_COLOR)
    return style


def _parse_dimension_style(ds_block_payload: bytes) -> DimensionStyle:
    """Parse TlvTag.DIMENSION_STYLE_BLOCK (0x01FF) and return a DimensionStyle object."""
    style = DimensionStyle()
    rec_p = find_child(ds_block_payload, TlvTag.DIMENSION_STYLE_RECORD)
    if not rec_p:
        return style

    def _int(tag: int, default: int = 0) -> int:
        p = find_child(rec_p, tag)
        return read_compact_int(p) if p else default

    def _bool(tag: int, default: bool = False) -> bool:
        p = find_child(rec_p, tag)
        return read_bool(p) if p else default

    def _float(tag: int, default: float = 0.0) -> float:
        p = find_child(rec_p, tag)
        return read_f64_le(p) if p and len(p) >= 8 else default

    def _color(tag: int) -> int:
        p = find_child(rec_p, tag)
        if p is None or len(p) < 4:
            return 0
        red, green, blue, alpha = p[:4]
        return (alpha << 24) | (red << 16) | (green << 8) | blue

    # Missing dimension-style fields use zero in this record. Assign that wire
    # fallback directly instead of inheriting new-object display defaults.
    style.font_ref = _int(TlvTag.DIMENSION_STYLE_FONT_REF)
    style.text_3d = _bool(TlvTag.DIMENSION_STYLE_3D_TEXT)
    style.always_readable = _bool(TlvTag.DIMENSION_STYLE_ALWAYS_READABLE)
    style.extension_offset = _int(TlvTag.DIMENSION_STYLE_EXTENSION_OFFSET)
    style.extension_overshoot = _int(TlvTag.DIMENSION_STYLE_EXTENSION_OVERSHOOT)
    style.line_weight = _int(TlvTag.DIMENSION_STYLE_LINE_WEIGHT)
    style.arrow_type = _int(TlvTag.DIMENSION_STYLE_ARROW_TYPE)
    style.arrow_size = _int(TlvTag.DIMENSION_STYLE_ARROW_SIZE)
    style.highlight_non_associative = _bool(TlvTag.DIMENSION_STYLE_HIGHLIGHT_NON_ASSOC)
    style.highlight_non_associative_color = _color(TlvTag.DIMENSION_STYLE_HIGHLIGHT_NON_ASSOC_COLOR)
    style.show_radial_diameter_prefix = _bool(TlvTag.DIMENSION_STYLE_SHOW_RADIAL_PREFIX)
    style.hide_out_of_plane = _bool(TlvTag.DIMENSION_STYLE_HIDE_OUT_OF_PLANE)
    style.hide_out_of_plane_value = _float(TlvTag.DIMENSION_STYLE_HIDE_OUT_OF_PLANE_VALUE)
    style.hide_small = _bool(TlvTag.DIMENSION_STYLE_HIDE_SMALL)
    style.hide_small_value = _float(TlvTag.DIMENSION_STYLE_HIDE_SMALL_VALUE)
    style.color = _color(TlvTag.DIMENSION_STYLE_COLOR)
    style.text_color = _color(TlvTag.DIMENSION_STYLE_TEXT_COLOR)
    style.text_position = _int(TlvTag.DIMENSION_STYLE_TEXT_POSITION)
    return style


def _parse_line_styles(ls_block_payload: bytes) -> list[LineStyle]:
    """Parse TlvTag.LINE_STYLES_BLOCK (0x0208) and return a list of LineStyle objects."""
    rec_p = find_child(ls_block_payload, TlvTag.LINE_STYLES_RECORD)
    if not rec_p:
        return []
    list_p = find_child(rec_p, TlvTag.LINE_STYLE_LIST)
    if not list_p:
        return []

    styles: list[LineStyle] = []
    for tag, ls_p in iter_records(list_p):
        if tag != TlvTag.LINE_STYLE_RECORD:
            continue
        style = LineStyle()
        name_p = find_child(ls_p, TlvTag.LINE_STYLE_NAME)
        style.name = read_utf8(name_p) if name_p else style.name
        dash_p = find_child(ls_p, TlvTag.LINE_STYLE_DASH_PATTERN)
        style.dash_pattern = read_utf8(dash_p) if dash_p else style.dash_pattern
        ss_p = find_child(ls_p, TlvTag.LINE_STYLE_STIPPLE_SCALE)
        if ss_p and len(ss_p) >= 8:
            style.stipple_scale = read_f64_le(ss_p)
        lw_p = find_child(ls_p, TlvTag.LINE_STYLE_LINE_WIDTH)
        if lw_p and len(lw_p) >= 8:
            style.line_width_points = read_f64_le(lw_p)
        c_p = find_child(ls_p, TlvTag.LINE_STYLE_COLOR)
        if c_p and len(c_p) >= 4:
            red, green, blue, alpha = c_p[:4]
            style.color = (alpha << 24) | (red << 16) | (green << 8) | blue
        else:
            style.color = 0
        m_p = find_child(ls_p, TlvTag.LINE_STYLE_MUTABILITY)
        if m_p is not None:
            style.mutability = read_bool(m_p)
        styles.append(style)
    return styles


def _parse_options_manager(om_block_payload: bytes) -> OptionsManager:
    """Parse TlvTag.OPTIONS_MANAGER_BLOCK (0x0200) and return an OptionsManager object."""
    manager = OptionsManager()
    rec_p = find_child(om_block_payload, TlvTag.OPTIONS_MANAGER_RECORD)
    if not rec_p:
        return manager

    plist_p = find_child(rec_p, TlvTag.OPTIONS_PROVIDER_LIST)
    if plist_p:
        for tag, prov_p in iter_records(plist_p):
            if tag != TlvTag.OPTIONS_PROVIDER_RECORD:
                continue
            provider = OptionsProvider()
            name_p = find_child(prov_p, TlvTag.OPTIONS_PROVIDER_NAME)
            provider.name = read_utf8(name_p) if name_p else provider.name
            kt_p = find_child(prov_p, TlvTag.OPTIONS_KEY_TABLE)
            if kt_p:
                key_name = ""
                for kt_tag, kt_rec_p in iter_records(kt_p):
                    if kt_tag == TlvTag.OPTIONS_KEY_NAME:
                        key_name = read_utf8(kt_rec_p) if kt_rec_p else ""
                        if key_name:
                            provider.keys[key_name] = ""
                    elif kt_tag == TlvTag.ATTR_TYPED_VALUE and key_name:
                        provider.keys[key_name] = _parse_option_value(kt_rec_p)
            manager.providers.append(provider)

    return manager


def _parse_option_value(payload: bytes) -> bool | int | float | str:
    fields = index_children(payload)
    if value := fields.get(TlvTag.ATTR_TYPED_VALUE_BOOL):
        return read_bool(value)
    if value := fields.get(TlvTag.ATTR_TYPED_VALUE_F64):
        return read_f64_le(value)
    if value := fields.get(TlvTag.ATTR_TYPED_VALUE_TYPE):
        return int(struct.unpack_from("<i", value)[0])
    value = fields.get(TlvTag.ATTR_TYPED_VALUE_STRING)
    return str(read_utf8(value)) if value is not None else ""


def _parse_environment_data(env_block_payload: bytes) -> EnvironmentData:
    """Parse TlvTag.ENVIRONMENT_DATA_BLOCK (0x0210) and return an EnvironmentData object."""
    environment = EnvironmentData()
    rec_p = find_child(env_block_payload, TlvTag.ENVIRONMENT_DATA_RECORD)
    if not rec_p:
        return environment

    selected_payload = find_child(rec_p, TlvTag.ENVIRONMENT_SELECTED_RECORD)
    if selected_payload:
        entry_payloads = [payload for tag, payload in iter_records(selected_payload) if tag == TlvTag.ENVIRONMENT_ENTRY]
        if not entry_payloads:
            entry_payloads = [selected_payload]
        for entry_p in entry_payloads:
            entry = _parse_environment_entry(entry_p)
            environment.entries.append(entry)
        environment.selected = environment.entries[0]

    return environment


def _parse_environment_entry(payload: bytes) -> EnvironmentEntry:
    """Decode one environment registry entry."""
    selected = EnvironmentEntry()
    wrapper_p = find_child(payload, TlvTag.ID_WRAPPER)
    id_p = find_child(wrapper_p, TlvTag.ID_VALUE) if wrapper_p else None
    if id_p is None:
        id_p = find_child(payload, TlvTag.ID_VALUE)
    selected.id = read_compact_int(id_p) if id_p else selected.id
    name_p = find_child(payload, TlvTag.ENVIRONMENT_NAME)
    selected.name = read_utf8(name_p) if name_p else selected.name
    thumb_p = find_child(payload, TlvTag.ENVIRONMENT_THUMBNAIL_PATH)
    selected.thumbnail_path = read_utf8(thumb_p) if thumb_p else ""
    if not selected.thumbnail_path:
        thumb_ref_p = find_child(payload, TlvTag.ENVIRONMENT_THUMBNAIL_REF)
        thumb_path_p = find_child(thumb_ref_p, TlvTag.ENVIRONMENT_THUMBNAIL_PATH) if thumb_ref_p else None
        if thumb_path_p:
            selected.thumbnail_path = read_utf8(thumb_path_p)
    return selected


def _parse_sun_data(sun_block_payload: bytes) -> SunData:
    """Parse TlvTag.SUN_DATA_BLOCK (0x0213) and return a SunData object."""
    sun = SunData()
    rec_p = find_child(sun_block_payload, TlvTag.SUN_DATA_RECORD)
    sun.raw_payload = rec_p if rec_p else None
    return sun


def _parse_model_view_axes(mv_block_payload: bytes) -> ModelViewAxes:
    """Parse TlvTag.MODEL_VIEW (0x01FC) and return a ModelViewAxes object."""
    axes = ModelViewAxes()
    rec_p = find_child(mv_block_payload, TlvTag.MODEL_VIEW_RECORD)
    if not rec_p:
        return axes

    origin_p = find_child(rec_p, TlvTag.SKETCH_AXES_ORIGIN)
    if origin_p and len(origin_p) >= 24:
        axes.origin = read_vec3(origin_p)

    x_p = find_child(rec_p, TlvTag.SKETCH_AXES_X_AXIS)
    if x_p and len(x_p) >= 24:
        axes.x_axis = read_vec3(x_p)

    y_p = find_child(rec_p, TlvTag.SKETCH_AXES_Y_AXIS)
    if y_p and len(y_p) >= 24:
        axes.y_axis = read_vec3(y_p)

    z_p = find_child(rec_p, TlvTag.SKETCH_AXES_Z_AXIS)
    if z_p and len(z_p) >= 24:
        axes.z_axis = read_vec3(z_p)

    flags_p = find_child(rec_p, TlvTag.SKETCH_AXES_FLAGS)
    if flags_p:
        axes.flags = read_compact_int(flags_p)

    return axes
