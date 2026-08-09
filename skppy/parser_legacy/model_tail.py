# SPDX-License-Identifier: MIT
"""Structured reader for model metadata following the root component."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data_structure.construction import ShadowInfo
from ..data_structure.model_metadata import (
    DimensionStyle,
    Font,
    LineStyle,
    ModelViewAxes,
    StylesRegistry,
    TextStyle,
    WatermarkManager,
    OptionsManager,
)
from ..data_structure.scene_data import PageBackgroundImage, Scene

from .metadata_payloads import read_axes_payload
from .metadata_readers import (
    read_dimension_style,
    read_font_manager,
    read_style_manager,
    read_text_style,
    read_watermark_manager,
)
from .read_context import ObjectReadContext
from .scene_pages import read_page_list, read_shadow_info
from .options_payloads import read_options_manager
from .line_style_payloads import read_line_style_manager


@dataclass
class ModelTailState:
    """Shared model metadata plus serialized model state fields."""

    payload_start_offset: int = 0
    shadow_info: ShadowInfo = field(default_factory=ShadowInfo)
    scenes: tuple[Scene, ...] = ()
    model_view_axes: ModelViewAxes = field(default_factory=ModelViewAxes)
    state_u32: tuple[int, ...] = ()
    options_manager: OptionsManager | None = None
    dimension_style: DimensionStyle = field(default_factory=DimensionStyle)
    text_style: TextStyle = field(default_factory=TextStyle)
    fonts: tuple[Font, ...] = ()
    line_styles: tuple[LineStyle, ...] = ()
    background_image: PageBackgroundImage | None = None
    styles_registry: StylesRegistry = field(default_factory=StylesRegistry)
    watermark_manager: WatermarkManager = field(default_factory=WatermarkManager)
    final_u32: int = 0
    final_bool: bool = False
    payload_end_offset: int = 0


def read_model_tail(context: ObjectReadContext, *, model_class_version: int) -> ModelTailState:
    """Read model metadata in the order selected by ``CSketchUpModel``."""
    reader = context.session.reader
    versions = context.class_versions
    state = ModelTailState()
    state.payload_start_offset = reader.tell()
    # The tail is serialized as an inheritance-era field sequence, not tagged
    # sections. Every gate below must consume exactly the fields introduced by
    # that CSketchUpModel schema before moving to the next block.
    state.shadow_info = read_shadow_info(
        context,
        class_version=versions.get("CShadowInfo", 7),
    )
    # CPageList replaced the inline counted page array at model schema 12.
    if model_class_version >= 12:
        state.scenes = read_page_list(
            context,
            class_version=versions.get("CPageList", 1),
        )
    else:
        state.scenes = _read_legacy_page_array(context)
    context.read_drawing_element()
    state.model_view_axes = read_axes_payload(reader, versions.get("CSketchCS", 0))
    state.state_u32 = tuple(reader.read_u32() for _ in range(16))
    # At schema 21 this manager moved to the model prefix; reading it twice
    # would shift every annotation/style object in newer files.
    state.options_manager = read_options_manager(reader.stream) if model_class_version < 21 else None
    state.dimension_style = (
        read_dimension_style(
            context,
            class_version=versions.get("CDimensionStyle", 4),
        )
        if model_class_version >= 8
        else DimensionStyle()
    )
    state.text_style = (
        read_text_style(
            context,
            class_version=versions.get("CTextStyle", 5),
        )
        if model_class_version >= 10
        else TextStyle()
    )
    state.fonts = read_font_manager(
        context,
        class_version=versions.get("CFontManager", 0),
    )
    if model_class_version >= 29:
        state.line_styles = read_line_style_manager(context)
    # Schema 14 is the lone observed version that omits this object between the
    # line-style manager and style registry.
    if model_class_version == 13 or model_class_version > 14:
        _, background = context.read_object()
        if isinstance(background, PageBackgroundImage):
            state.background_image = background
    state.styles_registry = (
        read_style_manager(
            context,
            class_version=versions.get("CSkpStyleManager", 2),
        )
        if model_class_version >= 14
        else StylesRegistry()
    )
    state.watermark_manager = (
        read_watermark_manager(
            context,
            class_version=versions.get("CWatermarkManager", 2),
        )
        if model_class_version >= 16
        else WatermarkManager()
    )
    if model_class_version >= 20:
        state.final_u32 = reader.read_u32()
    if model_class_version >= 22:
        state.final_bool = reader.read_bool()
    state.payload_end_offset = reader.tell()
    return state


def _read_legacy_page_array(context: ObjectReadContext) -> tuple[Scene, ...]:
    """Read pages stored directly before CPageList became a model field."""
    pages: list[Scene] = []
    for _ in range(context.session.reader.read_u32()):
        _, value = context.read_object()
        if isinstance(value, Scene):
            pages.append(value)
    return tuple(pages)
