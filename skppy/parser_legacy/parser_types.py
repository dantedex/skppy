# SPDX-License-Identifier: MIT
"""Technical state and payload aliases for pre-ZIP SketchUp parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, TypeAlias

from ..data_structure.construction import (
    Camera,
    GuideLine,
    GuidePoint,
    SectionPlane,
    ShadowInfo,
)
from ..data_structure.entities import (
    ArcCurve,
    ComponentInstance,
    ComponentDefinition,
    Curve,
    Edge,
    EdgeUse,
    Face,
    FaceUVProjection,
    Group,
    Image,
    Loop,
    Vertex,
)
from ..data_structure.images import Texture
from ..data_structure.layers import Layer, LayerFolder
from ..data_structure.materials import Material
from ..data_structure.model_metadata import (
    Font,
    LineStyle,
    ModelViewAxes,
    RenderingOptions,
)
from ..data_structure.model_metadata import (
    AttributeDictionary,
    DimensionStyle,
    StyleDescriptor,
    StylesRegistry,
    TextStyle,
    Watermark,
    WatermarkManager,
)
from ..data_structure.scene_data import PageBackgroundImage, Scene

from .binary import ArchiveObjectHandle, ArchiveObjectTag


@dataclass
class RootModelPrefixState:
    """Version-selected prefix fields from a legacy ``CSketchUpModel``."""

    class_version: int = 0
    payload_start_offset: int = 0
    unknown_u32_a: int | None = None
    unknown_u32_b: int | None = None
    license_product_family: int | None = None
    next_persistent_id: int | None = None
    thumbnail_object_tag: ArchiveObjectTag | None = None
    thumbnail: DibState | None = None
    redefine_thumbnail_on_save: bool | None = None
    prefix_end_offset: int = 0


@dataclass(frozen=True, slots=True)
class EntityHeaderState:
    """Shared ``CEntity`` prefix read before concrete entity payload fields."""

    class_version: int
    payload_start_offset: int
    legacy_flags_u32: int | None
    attribute_container_tag: ArchiveObjectTag | None
    persistent_id: int | None
    header_end_offset: int
    attribute_container_object_index: int | None = None


@dataclass(frozen=True, slots=True)
class ComponentBehaviorState:
    """Decoded placement, opening, scaling, and billboard behavior flags."""

    class_version: int
    object_tag: ArchiveObjectTag | None
    payload_start_offset: int
    entity_header: EntityHeaderState
    is_2d: bool
    cuts_opening: bool
    snap_to: int
    always_face_camera: bool
    shadows_face_sun: bool
    no_scale_mask: int
    payload_end_offset: int


ModelPreamblePayload: TypeAlias = tuple[int, ComponentBehaviorState, str, int]


AttributeContainerPayload: TypeAlias = tuple[
    ArchiveObjectTag,
    tuple[ArchiveObjectTag, ...],
    tuple[AttributeDictionary, ...],
    int,
    int,
]


DefinitionListPayload: TypeAlias = tuple[tuple[ArchiveObjectTag, ...], int, int]


class PostRenderingPayload(NamedTuple):
    """Root scalars between rendering options and the root component."""

    payload_start_offset: int
    obsolete_vertex_count: int
    validity_check_performed: int | None
    payload_end_offset: int


@dataclass(frozen=True, slots=True)
class DibState:
    """Archive metadata and encoded bytes from a legacy ``CDib`` payload."""

    object_tag: ArchiveObjectTag
    class_version: int
    payload_start_offset: int
    image_format: int | None
    image_bytes: bytes
    trailing_u32: int | None
    payload_end_offset: int


CameraSectionPayload: TypeAlias = tuple[ArchiveObjectTag, ArchiveObjectTag, Camera, int, DibState | None]


@dataclass(frozen=True, slots=True)
class MaterialState:
    """Shared material plus legacy archive metadata needed during resolution."""

    class_version: int
    payload_start_offset: int
    entity_header: EntityHeaderState
    material: Material
    used_by_layer: bool | None
    color: tuple[int, int, int, int] | None
    string_90: str | None
    material_type: int | None
    colorize_type: int | None
    transparency: float | None
    use_transparency: bool | None
    payload_end_offset: int


@dataclass(frozen=True, slots=True)
class LayerState:
    """Shared layer plus archive references needed during model assembly."""

    object_tag: ArchiveObjectTag
    payload_start_offset: int
    entity_header: EntityHeaderState
    layer: Layer
    material: MaterialState | None
    payload_end_offset: int


LayerManagerPayload: TypeAlias = tuple[
    tuple[LayerState, ...],
    ArchiveObjectTag | None,
    tuple[LayerFolder, ...],
    int,
    int,
]


@dataclass
class SceneState:
    """Shared scene plus legacy page snapshots and archive references."""

    object_tag: ArchiveObjectTag
    class_version: int
    scene: Scene
    payload_start_offset: int = 0
    camera_tag: ArchiveObjectTag | None = None
    rendering_options: RenderingOptions | None = None
    style_tag: ArchiveObjectTag | None = None
    shadow_info_tag: ArchiveObjectTag | None = None
    shadow_info: ShadowInfo | None = None
    shadow_info_display_shadows: bool | None = None
    axes_tag: ArchiveObjectTag | None = None
    axes: ModelViewAxes | None = None
    axes_display: bool | None = None
    hidden_entity_tags: tuple[ArchiveObjectTag, ...] = ()
    hidden_layer_tags: tuple[ArchiveObjectTag, ...] = ()
    active_section_plane_tags: tuple[ArchiveObjectTag, ...] = ()
    transition_time: float = -1.0
    delay_time: float = -1.0
    background_image_tag: ArchiveObjectTag | None = None
    image_rep_present: bool = False
    image_rep: bytes | None = None
    use_camera: bool = False
    use_rendering_options: bool = False
    use_shadow_info: bool = False
    use_axes: bool = False
    use_hidden: bool = False
    use_layer_visibility: bool = False
    use_section_planes: bool = False
    payload_end_offset: int = 0


RootComponentPayload: TypeAlias = tuple[int, int, int, int | None]


@dataclass(frozen=True, slots=True)
class ComponentDefinitionState:
    """Shared component definition plus unresolved archive-owned entities."""

    object_tag: ArchiveObjectTag
    object_index: int | None
    definition: ComponentDefinition
    entity_payloads: tuple[SupportedObjectPayload, ...]
    material_manager: tuple[MaterialState, ...] | None = None
    relationships: RelationshipCollection = ()


@dataclass(frozen=True, slots=True)
class DrawingElementState:
    """Decoded visibility, shadow, edge-shading, and lock base fields."""

    payload_start_offset: int
    entity_header: EntityHeaderState
    material_tag: ArchiveObjectTag
    hidden: bool
    casts_shadows: bool
    receives_shadows: bool
    soft: bool
    smooth: bool
    locked: bool
    layer_tag: ArchiveObjectTag | None
    payload_end_offset: int


Arc3dPayload: TypeAlias = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    float,
    float,
    tuple[float, float, float] | None,
]


@dataclass(frozen=True, slots=True)
class EdgeState:
    """Shared edge plus unresolved legacy geometry references."""

    object_tag: ArchiveObjectTag
    object_index: int | None
    payload_start_offset: int
    drawing_element: DrawingElementState
    edge: Edge
    start_vertex: Vertex
    end_vertex: Vertex
    curve_tag: ArchiveObjectTag | None
    payload_end_offset: int
    curve: Curve | ArcCurve | None = None


Polyline3dPayload: TypeAlias = tuple[DrawingElementState, tuple[tuple[float, float, float], ...]]


class DimensionPayload(NamedTuple):
    """Named common fields serialized by ``CDimension``."""

    drawing_element: DrawingElementState
    text: str
    font_tag: ArchiveObjectTag
    font: Font | None
    is_3d_text: bool
    arrow_type: int


class PointRefPayload(NamedTuple):
    """Named ``CPointRef`` geometry and archive-reference fields."""

    kind: int
    format_version: int
    position: tuple[float, float, float]
    leaf_tag: ArchiveObjectTag
    secondary_leaf_tag: ArchiveObjectTag | None
    instance_path: tuple[ArchiveObjectTag, ...]
    secondary_instance_path: tuple[ArchiveObjectTag, ...]


class DimensionLinearPayload(NamedTuple):
    """Named fields serialized by ``CDimensionLinear``."""

    dimension: DimensionPayload
    start_ref: PointRefPayload
    end_ref: PointRefPayload
    normal: tuple[float, float, float]
    x_axis: tuple[float, float, float]
    dimension_type: int
    y_position: float
    x_position: float
    text_position: int


class DimensionRadialPayload(NamedTuple):
    """Named fields serialized by ``CDimensionRadial``."""

    dimension: DimensionPayload
    target_tag: ArchiveObjectTag
    target: EdgeState | None
    parameter: float
    radius_ratio: float
    is_diameter: bool
    arc: Arc3dPayload | None


class TextPayload(NamedTuple):
    """Named fields serialized by ``CText`` version 9."""

    drawing_element: DrawingElementState
    font_tag: ArchiveObjectTag
    font: Font | None
    screen_x: float
    screen_y: float
    point_ref: PointRefPayload
    leader_vector: tuple[float, float, float]
    view_direction: tuple[float, float, float]
    leader_type: int
    line_weight: int
    point_ref_front: bool
    hide_out_of_plane: bool
    arrow_type: int
    display_leader: bool
    text: str
    convert_to_screen_on_explode: bool
    hidden_leader_direction: int


FaceTextureCoordsPayload: TypeAlias = tuple[
    int,
    FaceUVProjection,
    FaceUVProjection | None,
    int | None,
    int | None,
]


RelationshipReferences: TypeAlias = tuple[ArchiveObjectTag, ArchiveObjectTag]
RelationshipCollection: TypeAlias = tuple[RelationshipReferences, ...]


SupportedObjectPayload: TypeAlias = (
    ArchiveObjectHandle
    | DibState
    | bytes
    | Texture
    | int
    | AttributeContainerPayload
    | AttributeDictionary
    | ComponentBehaviorState
    | Camera
    | RenderingOptions
    | Vertex
    | Curve
    | ArcCurve
    | EdgeState
    | DrawingElementState
    | EdgeUse
    | Loop
    | Face
    | GuidePoint
    | Polyline3dPayload
    | GuideLine
    | SectionPlane
    | ComponentDefinitionState
    | ComponentInstance
    | Group
    | Image
    | PageBackgroundImage
    | DimensionPayload
    | DimensionStyle
    | DimensionLinearPayload
    | DimensionRadialPayload
    | Font
    | LineStyle
    | tuple[Font, ...]
    | TextPayload
    | TextStyle
    | StyleDescriptor
    | StylesRegistry
    | Watermark
    | WatermarkManager
    | FaceTextureCoordsPayload
    | RelationshipReferences
    | RelationshipCollection
    | DefinitionListPayload
    | MaterialState
    | tuple[MaterialState, ...]
    | LayerState
    | LayerFolder
    | LayerManagerPayload
    | tuple[Scene, ...]
    | Scene
    | SceneState
    | ModelViewAxes
    | ShadowInfo
)
