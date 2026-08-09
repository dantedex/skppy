# SPDX-License-Identifier: MIT
"""Shared-model construction state for pre-ZIP SketchUp archives."""

from __future__ import annotations

from collections.abc import Callable

from ..data_structure.construction import Camera, ShadowInfo
from ..data_structure.header import SkpHeader
from ..data_structure.model import Model
from ..data_structure.model_metadata import (
    DimensionStyle,
    AttributeDictionary,
    EnvironmentData,
    Font,
    LineStyle,
    ModelViewAxes,
    OptionsManager,
    RenderingOptions,
    StyleDescriptor,
    StylesRegistry,
    TextStyle,
    WatermarkManager,
)
from ..data_structure.scene_data import PageBackgroundImage


_LEGACY_BUILT_IN_LINE_STYLES: tuple[tuple[str, str], ...] = (
    ("Solid Basic", "16.0"),
    ("Short dash", "6.0, -6.0"),
    ("Dash", "12.0, -6.0"),
    ("Dot", "1.0, -6.0"),
    ("Dash dot", "12.0, -6.0, 1.0, -6.0"),
    ("Dash double-dot", "12.0, -6.0, 1.0, -6.0, 1.0, -6.0"),
    ("Dash triple-dot", "12.0, -6.0, 1.0, -6.0, 1.0, -6.0, 1.0, -6.0"),
    ("Double-dash dot", "12.0, -6.0, 12.0, -6.0, 1.0, -6.0"),
    ("Double-dash double-dot", "12.0, -6.0, 12.0, -6.0, 1.0, -6.0, 1.0, -6.0"),
    (
        "Double-dash triple-dot",
        "12.0, -6.0, 12.0, -6.0, 1.0, -6.0, 1.0, -6.0, 1.0, -6.0",
    ),
    ("Long-dash dash", "36.0, -10.0, 12.0, -10.0"),
    ("Long-dash double-dash", "36.0, -10.0, 12.0, -10.0, 12.0, -10.0"),
)


class ModelBuilder:
    """Build one shared :class:`Model` while retaining archive-reference state."""

    def __init__(
        self,
        header: SkpHeader,
        provenance: object,
        *,
        archive_objects: tuple[tuple[int, object], ...] = (),
    ) -> None:
        """Create the public model and empty archive-reference registry."""
        self.model = Model(header=header, legacy_archive=provenance)
        self.objects: dict[int, object] = {}
        self._indices_by_payload_identity = {id(payload): archive_index for archive_index, payload in archive_objects}
        self._pending: list[tuple[int, Callable[[object], None]]] = []

    def register(self, archive_index: int, value: object) -> None:
        """Register a parsed archive object and satisfy waiting references."""
        self.objects[archive_index] = value
        remaining: list[tuple[int, Callable[[object], None]]] = []
        for index, assign in self._pending:
            if index == archive_index:
                assign(value)
            else:
                remaining.append((index, assign))
        self._pending = remaining

    def register_archive_value(self, payload: object, value: object) -> int | None:
        """Associate parser-only state with its shared public object."""
        archive_index = self._indices_by_payload_identity.get(id(payload))
        if archive_index is not None:
            self.register(archive_index, value)
        return archive_index

    def reference(self, archive_index: int, assign: Callable[[object], None]) -> None:
        """Assign a resolved archive object now or defer it until registration."""
        value = self.objects.get(archive_index)
        if value is None:
            self._pending.append((archive_index, assign))
        else:
            assign(value)

    def apply_metadata(
        self,
        *,
        camera: Camera | None = None,
        rendering_options: RenderingOptions | None = None,
        shadow_info: ShadowInfo | None = None,
        model_view_axes: ModelViewAxes | None = None,
    ) -> None:
        """Attach already-decoded shared metadata without rebuilding it."""
        if camera is not None:
            self.model.cameras.append(camera)
        if rendering_options is not None:
            self.model.rendering_options = rendering_options
        if shadow_info is not None:
            self.model.shadow_info = shadow_info
        if model_view_axes is not None:
            self.model.model_view_axes = model_view_axes

    def add_fonts(self, fonts: tuple[Font, ...]) -> None:
        """Append fonts while preserving the model's semantic uniqueness."""
        seen = {
            (
                font.face_name,
                font.bold,
                font.italic,
                font.point_size,
                font.use_world_size,
                font.world_size,
            )
            for font in self.model.fonts
        }
        for font in fonts:
            key = (
                font.face_name,
                font.bold,
                font.italic,
                font.point_size,
                font.use_world_size,
                font.world_size,
            )
            if key not in seen:
                self.model.fonts.append(font)
                seen.add(key)

    def add_styles(self, styles: tuple[StyleDescriptor, ...]) -> None:
        """Append style descriptors while preserving semantic uniqueness."""
        if not styles:
            return
        if self.model.styles_registry is None:
            self.model.styles_registry = StylesRegistry()
        seen = {(style.guid, style.display_name, style.file_name) for style in self.model.styles_registry.styles}
        for style in styles:
            key = (style.guid, style.display_name, style.file_name)
            if key not in seen:
                self.model.styles_registry.styles.append(style)
                seen.add(key)

    def add_line_styles(self, styles: tuple[LineStyle, ...]) -> None:
        """Append decoded line styles while preserving their unique names."""
        seen = {style.name for style in self.model.line_styles}
        for style in styles:
            if style.name not in seen:
                self.model.line_styles.append(style)
                seen.add(style.name)

    def apply_styles_registry(self, registry: StylesRegistry | None) -> None:
        """Attach a directly decoded styles registry without rebuilding it."""
        if registry is not None:
            self.model.styles_registry = registry

    def normalize_style_references(self, archive_objects: tuple[tuple[int, object], ...]) -> None:
        """Replace internal CArchive style indices with public registry positions."""
        registry = self.model.styles_registry
        if registry is None:
            return
        positions_by_identity = {id(style): position for position, style in enumerate(registry.styles, start=1)}
        positions_by_archive_index = {
            archive_index: positions_by_identity[id(value)]
            for archive_index, value in archive_objects
            if id(value) in positions_by_identity
        }
        registry.active_style_ref = positions_by_archive_index.get(
            registry.active_style_ref,
            registry.active_style_ref,
        )
        for scene in self.model.scenes:
            scene.style_reference = positions_by_archive_index.get(scene.style_reference, scene.style_reference)

    def apply_watermark_manager(self, manager: WatermarkManager | None) -> None:
        """Attach a directly decoded watermark manager by identity."""
        if manager is not None:
            self.model.watermark_manager = manager

    def apply_annotation_styles(
        self,
        *,
        text_style: TextStyle | None,
        dimension_style: DimensionStyle | None,
    ) -> None:
        """Attach directly decoded annotation styles by identity."""
        if text_style is not None:
            self.model.text_style = text_style
        if dimension_style is not None:
            self.model.dimension_style = dimension_style

    def apply_background_image(self, image: PageBackgroundImage | None) -> None:
        """Attach the model's default page background image by identity."""
        if image is not None:
            self.model.background_image = image

    def apply_options_manager(self, manager: OptionsManager | None) -> None:
        """Attach the directly decoded options manager by identity."""
        if manager is not None:
            self.model.options_manager = manager

    def add_attribute_dictionaries(self, dictionaries: tuple[AttributeDictionary, ...]) -> None:
        """Append attribute dictionaries already decoded into shared objects."""
        self.model.attribute_dictionaries.extend(dictionaries)

    def apply_legacy_defaults(self, *, has_post_rendering_data: bool) -> None:
        """Attach shared defaults implied by a decoded post-rendering section."""
        if not has_post_rendering_data:
            return
        self.model.environment_data = EnvironmentData()
        if not self.model.line_styles:
            self.model.line_styles.extend(
                LineStyle(
                    name=name,
                    dash_pattern=dash_pattern,
                    line_width_points=1.0,
                    mutability=False,
                )
                for name, dash_pattern in _LEGACY_BUILT_IN_LINE_STYLES
            )

    def finalize(self) -> Model:
        """Return the shared model after verifying no reference is unresolved."""
        if self._pending:
            indexes = sorted({index for index, _ in self._pending})
            raise ValueError(f"Unresolved CArchive object references: {indexes}")
        return self.model
