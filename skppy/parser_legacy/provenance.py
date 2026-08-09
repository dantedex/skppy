# SPDX-License-Identifier: MIT
"""Decoded envelope and archive provenance for legacy SketchUp files."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..data_structure.construction import Camera, ShadowInfo
from ..data_structure.entities import Face
from ..data_structure.header import SkpHeader
from ..data_structure.layers import LayerFolder
from ..data_structure.model_metadata import (
    AttributeDictionary,
    Font,
    LineStyle,
    ModelViewAxes,
    OptionsManager,
    RenderingOptions,
    StyleDescriptor,
    StylesRegistry,
    TextStyle,
    DimensionStyle,
    WatermarkManager,
)
from ..data_structure.scene_data import PageBackgroundImage
from ..parser.header_parser import _parse_version_tuple

from .parser_types import (
    EdgeState,
    LayerState,
    MaterialState,
    SceneState,
    ComponentBehaviorState,
    DibState,
    RootModelPrefixState,
    SupportedObjectPayload,
)
from .binary import ArchiveIndexEntry, ArchiveObjectTag
from .envelope import VersionMapEntry
from .scene_pages import RecoveredSceneState
from .schema import ArchiveSchema, SketchUpFormatVersion


@dataclass
class ArchiveProvenance:
    """Decoded pre-archive envelope and technical legacy parse state."""

    product_name: str = ""
    version_string: str = ""
    model_guid: bytes = b""
    saved_path: str = ""
    timestamp: int = 0
    version_map: tuple[VersionMapEntry, ...] = ()
    archive_offset: int = 0
    format_version: SketchUpFormatVersion = field(default_factory=lambda: SketchUpFormatVersion(8, 0, 0))
    archive_schema: ArchiveSchema = field(
        default_factory=lambda: ArchiveSchema.from_pairs(SketchUpFormatVersion(8, 0, 0), ())
    )
    root_prefix: RootModelPrefixState | None = None
    model_preamble_payload_start_offset: int | None = None
    root_component_behavior: ComponentBehaviorState | None = None
    model_description: str = ""
    model_preamble_payload_end_offset: int | None = None
    options_manager: OptionsManager | None = None
    options_manager_payload_end_offset: int | None = None
    model_properties: tuple[AttributeDictionary, ...] = ()
    model_properties_object_tag: ArchiveObjectTag | None = None
    model_property_tags: tuple[ArchiveObjectTag, ...] = ()
    model_properties_payload_start_offset: int | None = None
    model_properties_payload_end_offset: int | None = None
    camera_section_leading_tag: ArchiveObjectTag | None = None
    root_camera_tag: ArchiveObjectTag | None = None
    root_camera: Camera | None = None
    root_camera_payload_end_offset: int | None = None
    camera_section_leading_dib: DibState | None = None
    rendering_options: RenderingOptions | None = None
    rendering_options_payload_end_offset: int | None = None
    post_rendering_payload_start_offset: int | None = None
    obsolete_vertex_count: int | None = None
    validity_check_performed: int | None = None
    definition_tags: tuple[ArchiveObjectTag, ...] = ()
    definition_list_start_offset: int | None = None
    definition_list_end_offset: int | None = None
    root_component_materials: tuple[MaterialState, ...] = ()
    layer_manager_start_offset: int | None = None
    archived_layers: tuple[LayerState, ...] = ()
    layer_folders: tuple[LayerFolder, ...] = ()
    active_layer_tag: ArchiveObjectTag | None = None
    layer_manager_payload_start_offset: int | None = None
    layer_manager_payload_end_offset: int | None = None
    root_component_payload_start_offset: int | None = None
    root_attribute_container_index: int | None = None
    root_entity_count: int = 0
    root_component_payload_end_offset: int | None = None
    root_objects: tuple[SupportedObjectPayload, ...] = ()
    root_relationships: tuple[tuple[ArchiveObjectTag, ArchiveObjectTag], ...] = ()
    root_edge_previews: tuple[EdgeState, ...] = ()
    root_faces: tuple[Face, ...] = ()
    archived_scenes: tuple[SceneState, ...] = ()
    scene_previews: tuple[RecoveredSceneState, ...] = ()
    shadow_info: ShadowInfo | None = None
    model_view_axes: ModelViewAxes | None = None
    font_previews: tuple[Font, ...] = ()
    style_previews: tuple[StyleDescriptor, ...] = ()
    line_styles: tuple[LineStyle, ...] = ()
    styles_registry: StylesRegistry | None = None
    watermark_manager: WatermarkManager | None = None
    text_style: TextStyle | None = None
    dimension_style: DimensionStyle | None = None
    background_image: PageBackgroundImage | None = None
    model_tail_state_u32: tuple[int, ...] = ()
    model_tail_final_u32: int | None = None
    model_tail_final_bool: bool | None = None
    model_tail_payload_end_offset: int | None = None
    archive_index_entries: tuple[ArchiveIndexEntry, ...] = ()
    archive_objects: tuple[tuple[int, SupportedObjectPayload], ...] = ()
    attribute_container_indices_by_owner: tuple[tuple[int, int], ...] = ()

    @property
    def saved_at(self) -> datetime:
        """Return the header timestamp as a timezone-aware UTC datetime."""
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)

    def to_skp_header(self) -> SkpHeader:
        """Convert the legacy envelope into the shared header dataclass."""
        return SkpHeader(
            product_name=self.product_name,
            version_string=self.version_string,
            version_tuple=_parse_version_tuple(self.version_string),
            vff_magic="",
            vff_field_1=0,
            vff_field_2=0,
            vff_field_3=0,
            vff_field_4=0,
            zip_offset=None,
            model_guid=self.model_guid,
        )
