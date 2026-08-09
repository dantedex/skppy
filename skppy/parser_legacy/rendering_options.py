# SPDX-License-Identifier: MIT
"""Decode version-gated pre-ZIP rendering options in strict wire order.

Unlike modern tagged records, legacy rendering bodies are sequential. The
class schema therefore controls which booleans, colors, integers, and floating
values are present. Supported generations map to the shared
:class:`~skppy.data_structure.model_metadata.RenderingOptions` defaults and
fail explicitly at an unknown schema boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data_structure.model_metadata import RenderingOptions
from .binary import LegacyArchiveReader
from .colors import rgba_bytes_to_argb


# These schemas are present in observed save-version maps from SU3
# through SU2020. Intermediate numbers in the Serialize version gates below
# describe field evolution, but were not emitted as complete public schemas.
_SUPPORTED_SCHEMAS = frozenset({22, 25, 28, 32, 35, 36, 37, 38, 39})


@dataclass(slots=True)
class _RenderingValues:
    """Read sequential wire values directly into shared rendering options."""

    reader: LegacyArchiveReader
    options: RenderingOptions

    def boolean(self, name: str) -> None:
        setattr(self.options, name, self.reader.read_bool())

    def color(self, name: str) -> None:
        setattr(self.options, name, rgba_bytes_to_argb(self.reader.read_rgba()))

    def float64(self, name: str) -> None:
        setattr(self.options, name, self.reader.read_f64())

    def uint32(self, name: str) -> None:
        setattr(self.options, name, self.reader.read_u32())


def _read_core_display(values: _RenderingValues, class_version: int) -> None:
    """Read the stable display prefix through instance fading."""
    options = values.options
    values.uint32("render_mode")
    values.boolean("model_transparency")
    values.boolean("material_transparency")
    values.boolean("jitter_edges")
    if class_version > 37:
        values.boolean("line_style_edges")
    else:
        # Older readers initialized this option to true when it was absent.
        options.line_style_edges = True
    values.uint32("edge_display_mode")
    values.color("background_color")
    values.color("foreground_color")
    values.color("highlight_color")
    values.color("construction_color")
    values.reader.read_bool()  # Obsolete, unnamed display flag.
    values.boolean("display_instance_axes")
    values.boolean("display_color_by_layer")
    values.boolean("texture")
    values.uint32("edge_color_mode")
    values.boolean("extend_lines")
    values.uint32("line_extension")
    values.boolean("draw_silhouettes")
    values.uint32("silhouette_width")
    if class_version >= 26:
        values.boolean("draw_depth_que")
        values.uint32("depth_que_width")
        values.boolean("draw_line_ends")
        values.uint32("line_end_width")
        if class_version >= 28:
            values.boolean("draw_profiles_only")
    values.boolean("draw_hidden_geometry")
    if class_version >= 39:
        values.boolean("draw_hidden_objects")
    else:
        options.draw_hidden_objects = options.draw_hidden_geometry
    values.uint32("face_color_mode")
    values.color("face_front_color")
    values.color("face_back_color")
    values.float64("inactive_fade")
    values.float64("instance_fade")
    values.boolean("inactive_hidden")
    values.boolean("instance_hidden")


def _read_fog_and_auxiliary_display(values: _RenderingValues, class_version: int) -> None:
    """Read the optional fog and auxiliary-visibility generation."""
    if class_version < 29:
        return
    values.boolean("display_fog")
    values.color("fog_color")
    values.boolean("fog_use_background_color")
    values.float64("fog_start_dist")
    values.float64("fog_end_dist")
    if class_version != 29:
        values.uint32("fog_hint_mode")
    if class_version > 30:
        values.uint32("edge_type")
        values.boolean("display_sketch_axes")
        values.boolean("display_text")
        values.boolean("display_dims")
        values.boolean("hide_construction_geometry")


def _read_environment_and_sections(values: _RenderingValues, class_version: int) -> None:
    """Read sky, ground, section, transparency, and smooth-edge fields."""
    values.color("sky_color")
    if class_version >= 24:
        values.color("horizon_color")
    values.color("ground_color")
    values.boolean("draw_horizon")
    values.boolean("draw_ground")
    values.boolean("draw_underground")
    values.uint32("ground_transparency")
    values.color("section_active_color")
    values.color("section_inactive_color")
    values.color("section_default_cut_color")
    values.uint32("section_cut_width")
    # This is the same bitmask used by modern files: bit 0 displays section
    # planes and bit 1 displays section cuts. RenderingOptions exposes both as
    # named properties while retaining the source mask.
    values.uint32("section_display_mode")
    if class_version > 36:
        values.color("section_default_fill_color")
        values.boolean("section_cut_filled")
    values.uint32("transparency_sort")
    values.boolean("draw_soft_edges")
    values.float64("soft_edge_limit")
    values.boolean("draw_smooth_edges")


def _read_appended_rendering_fields(values: _RenderingValues, class_version: int) -> None:
    """Read the append-only tail, stopping at each historical schema boundary."""
    if class_version <= 22:
        return
    if class_version in {23, 24}:
        values.reader.read_bool()  # Model-level mipmap option, moved elsewhere.
        return
    if class_version < 27:
        return
    values.color("locked_color")
    if class_version < 32:
        return
    values.boolean("display_watermarks")
    if class_version == 33:
        values.reader.read_bool()  # Model-level mipmap option, moved elsewhere.
        return
    if class_version < 35:
        return
    values.float64("xray_opacity")
    if class_version == 35:
        return
    values.boolean("draw_back_edges")
    values.boolean("photomatch_draw_background")
    values.float64("photomatch_background_opacity")
    values.boolean("photomatch_draw_overlay")
    values.float64("photomatch_overlay_opacity")


def read_rendering_options_payload(reader: LegacyArchiveReader, class_version: int) -> RenderingOptions:
    """Consume a ``CRenderingOptions`` body and return shared metadata."""
    if class_version not in _SUPPORTED_SCHEMAS:
        raise NotImplementedError(f"CRenderingOptions version {class_version} is not decoded.")
    options = RenderingOptions()
    values = _RenderingValues(reader, options)
    _read_core_display(values, class_version)
    _read_fog_and_auxiliary_display(values, class_version)
    _read_environment_and_sections(values, class_version)
    _read_appended_rendering_fields(values, class_version)
    return options
