# SPDX-License-Identifier: MIT
"""Independent SketchUp Make 2017 envelope and root-model prefix writer."""

from __future__ import annotations

import struct

from ..data_structure.construction import Camera
from ..data_structure.model import Model
from ..data_structure.model_metadata import OptionsManager, RenderingOptions
from ..data_structure.primitives import Vector3D

_VERSION_MAP: tuple[tuple[str, int], ...] = (
    ("CArcCurve", 3),
    ("CAttribute", 0),
    ("CAttributeContainer", 0),
    ("CAttributeNamed", 1),
    ("CBackgroundImage", 10),
    ("CCamera", 5),
    ("CComponent", 11),
    ("CComponentBehavior", 5),
    ("CComponentDefinition", 10),
    ("CComponentInstance", 5),
    ("CConstructionGeometry", 0),
    ("CConstructionLine", 1),
    ("CConstructionPoint", 0),
    ("CCurve", 4),
    ("CDefinitionList", 0),
    ("CDib", 3),
    ("CDimension", 1),
    ("CDimensionLinear", 6),
    ("CDimensionRadial", 2),
    ("CDimensionStyle", 4),
    ("CDrawingElement", 9),
    ("CEdge", 2),
    ("CEdgeUse", 1),
    ("CEntity", 5),
    ("CFace", 3),
    ("CFaceTextureCoords", 4),
    ("CFontManager", 0),
    ("CGroup", 1),
    ("CImage", 1),
    ("CLayer", 2),
    ("CLayerManager", 4),
    ("CLoop", 1),
    ("CMaterial", 12),
    ("CMaterialManager", 4),
    ("CPageList", 1),
    ("CPolyline3d", 0),
    ("CRelationship", 0),
    ("CRelationshipMap", 0),
    ("CRenderingOptions", 36),
    ("CSchemaFile", 1),
    ("CSchemaFilterFile", 0),
    ("CSchemaZipFile", 1),
    ("CSectionPlane", 2),
    ("CShadowInfo", 7),
    ("CSkFont", 1),
    ("CSketchCS", 0),
    ("CSketchUpModel", 26),
    ("CSketchUpPage", 1),
    ("CSkpStyle", 1),
    ("CSkpStyleManager", 2),
    ("CText", 9),
    ("CTextStyle", 5),
    ("CTexture", 6),
    ("CThumbnail", 1),
    ("CVertex", 0),
    ("CViewPage", 12),
    ("CWatermark", 1),
    ("CWatermarkManager", 2),
    ("End-Of-Version-Map", 0),
)


def build_legacy_2017_prefix(model: Model, next_persistent_id: int) -> bytes:
    """Return the complete envelope preceding the root ``CComponent`` body."""
    data = bytearray()
    data += _legacy_string("SketchUp Model")
    data += _legacy_string("{17.0.1}")
    data += _model_guid(model)
    data += _legacy_string("")
    data += struct.pack("<I", _legacy_timestamp(model))
    data += _version_map()
    data += struct.pack("<IIIQ", 1, 1200, 0, next_persistent_id)
    data += struct.pack("<HB", 0, True)
    data += _entity_header(0)
    data += bytes((False, False)) + struct.pack("<IBI", 0, 0, 0)
    data += _legacy_string(_model_description(model))
    data += _options_manager(model.options_manager or OptionsManager())
    data += _default_model_properties()
    data += struct.pack("<H", 0)
    data += _new_class("CCamera", 5)
    data += _camera_body(_current_camera(model))
    data += _entity_header(0)
    data += _rendering_options(model.rendering_options or RenderingOptions())
    data += struct.pack("<II", 0, 1)
    return bytes(data)


def _version_map() -> bytes:
    data = bytearray(struct.pack("<4sH", b"\xff\xff\x00\x00", len("CVersionMap")))
    data += b"CVersionMap"
    for class_name, version in _VERSION_MAP:
        data += _legacy_string(class_name)
        data += struct.pack("<I", version)
    return bytes(data)


def _model_guid(model: Model) -> bytes:
    model_guid = model.header.model_guid if model.header is not None else None
    if model_guid is not None and len(model_guid) == 16:
        return model_guid
    return bytes(16)


def _legacy_timestamp(model: Model) -> int:
    provenance = model.legacy_archive
    value = getattr(provenance, "timestamp", 0) if provenance is not None else 0
    return value if isinstance(value, int) and 0 <= value <= 0xFFFFFFFF else 0


def _model_description(model: Model) -> str:
    provenance = model.legacy_archive
    value = getattr(provenance, "model_description", "") if provenance is not None else ""
    return value if isinstance(value, str) else ""


def _current_camera(model: Model) -> Camera:
    if len(model.cameras) > 1:
        raise ValueError("A legacy model can contain only one current camera")
    if model.cameras:
        return model.cameras[0]
    return Camera(
        eye=Vector3D(0.0, 0.0, 500.0),
        target=Vector3D(0.0, 0.0, 0.0),
        up=Vector3D(0.0, 1.0, 0.0),
        fov=30.0,
        near=1.0,
        far=1000.0,
        ortho_height=133.0,
    )


def _camera_body(camera: Camera) -> bytes:
    data = bytearray()
    for vector in (camera.eye, camera.target, camera.up):
        data += struct.pack("<3d", vector.x, vector.y, vector.z)
    data += struct.pack("<2dB", camera.near, camera.far, camera.is_perspective)
    data += struct.pack("<2d", camera.fov, camera.ortho_height if camera.ortho_height is not None else 1.0)
    data += struct.pack("<3d", 0.0, 0.0, 0.0)
    data += struct.pack("<dBB", camera.aspect_ratio or 0.0, camera.fov_is_height, camera.legacy_flag)
    data += _legacy_string(camera.name)
    data += struct.pack("<dB", camera.image_width or 0.0, camera.is_2d)
    data += struct.pack(
        "<3d",
        camera.scale_2d if camera.scale_2d is not None else 1.0,
        camera.center_2d_x or 0.0,
        camera.center_2d_y or 0.0,
    )
    return bytes(data)


def _options_manager(manager: OptionsManager) -> bytes:
    data = bytearray(struct.pack("<II", 0, len(manager.providers)))
    for provider in manager.providers:
        if not provider.name:
            raise ValueError("Legacy option provider names must not be empty")
        data += _legacy_string(provider.name)
        for key, value in provider.keys.items():
            if not key:
                raise ValueError("Legacy option names must not be empty")
            data += _legacy_string(key)
            data += _typed_option(value)
        data += _legacy_string("")
    return bytes(data)


def _typed_option(value: bool | int | float | str) -> bytes:
    if isinstance(value, bool):
        return bytes((7, value))
    if isinstance(value, int):
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("Legacy integer options must fit in u32")
        return bytes((4,)) + struct.pack("<I", value)
    if isinstance(value, float):
        return bytes((6,)) + struct.pack("<d", value)
    return bytes((10,)) + _legacy_string(value)


def _default_model_properties() -> bytes:
    data = bytearray(_new_class("CAttributeContainer", 0))
    data += _entity_header(0)
    data += _new_class("CAttributeNamed", 1)
    data += _entity_header(0)
    data += struct.pack("<I", 0)
    data += _legacy_string("ModelProperties")
    for key in ("IsClassified", "IsDynamic", "IsLive"):
        data += _legacy_string(key) + bytes((7, False))
    data += _legacy_string("") + struct.pack("<I", 0)
    data += struct.pack("<H", 0)
    return bytes(data)


def _rendering_options(options: RenderingOptions) -> bytes:
    data = bytearray(
        struct.pack(
            "<IBBBI",
            options.render_mode,
            options.model_transparency,
            options.material_transparency,
            options.jitter_edges,
            options.edge_display_mode,
        ),
    )
    for color in (
        options.background_color,
        options.foreground_color,
        options.highlight_color,
        options.construction_color,
    ):
        data += _argb(color)
    data += bytes((False, options.display_instance_axes, options.display_color_by_layer, options.texture))
    data += struct.pack(
        "<IBIBI",
        options.edge_color_mode,
        options.extend_lines,
        options.line_extension,
        options.draw_silhouettes,
        options.silhouette_width,
    )
    data += struct.pack(
        "<BIBI",
        options.draw_depth_que,
        options.depth_que_width,
        options.draw_line_ends,
        options.line_end_width,
    )
    data += bytes((options.draw_profiles_only, options.draw_hidden_geometry))
    data += struct.pack("<I", options.face_color_mode)
    data += _argb(options.face_front_color) + _argb(options.face_back_color)
    data += struct.pack(
        "<2dBB",
        options.inactive_fade,
        options.instance_fade,
        options.inactive_hidden,
        options.instance_hidden,
    )
    data += bytes((options.display_fog,)) + _argb(options.fog_color) + bytes((options.fog_use_background_color,))
    data += struct.pack("<2dII", options.fog_start_dist, options.fog_end_dist, options.fog_hint_mode, options.edge_type)
    data += bytes(
        (
            options.display_sketch_axes,
            options.display_text,
            options.display_dims,
            options.hide_construction_geometry,
        ),
    )
    data += _argb(options.sky_color) + _argb(options.horizon_color) + _argb(options.ground_color)
    data += bytes((options.draw_horizon, options.draw_ground, options.draw_underground))
    data += struct.pack("<I", options.ground_transparency)
    data += _argb(options.section_active_color) + _argb(options.section_inactive_color)
    data += _argb(options.section_default_cut_color)
    data += struct.pack(
        "<IIIBdB",
        options.section_cut_width,
        options.section_display_mode,
        options.transparency_sort,
        options.draw_soft_edges,
        options.soft_edge_limit,
        options.draw_smooth_edges,
    )
    data += _argb(options.locked_color)
    data += bytes((options.display_watermarks,))
    data += struct.pack(
        "<dBBdBd",
        options.xray_opacity,
        options.draw_back_edges,
        options.photomatch_draw_background,
        options.photomatch_background_opacity,
        options.photomatch_draw_overlay,
        options.photomatch_overlay_opacity,
    )
    return bytes(data)


def _argb(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("Legacy rendering colors must fit in u32")
    return bytes(((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, (value >> 24) & 0xFF))


def _entity_header(persistent_id: int) -> bytes:
    return struct.pack("<HB", 0, 0) if persistent_id == 0 else struct.pack("<HB", 0, 1) + bytes((persistent_id,))


def _new_class(class_name: str, schema: int) -> bytes:
    encoded = class_name.encode("ascii")
    return struct.pack("<HHH", 0xFFFF, schema, len(encoded)) + encoded


def _legacy_string(value: str) -> bytes:
    encoded = value.encode("utf-16le")
    length = len(encoded) // 2
    if length < 0xFF:
        prefix = bytes((length,))
    elif length < 0xFFFF:
        prefix = b"\xff" + struct.pack("<H", length)
    else:
        prefix = b"\xff\xff\xff" + struct.pack("<I", length)
    return b"\xff\xfe\xff" + prefix + encoded
