# SPDX-License-Identifier: MIT
"""
Model-level metadata data structures for skppy.

These classes represent non-geometric model data: rendering options,
watermarks, styles, fonts, text styles, dimension styles, line styles,
options manager, environment data, sun data, model view axes, and
attribute dictionaries.

All classes are pure data containers (no parsing logic).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# -
# Rendering options
# -


@dataclass(slots=True)
class RenderingOptions:
    """
    Rendering and display options normalized across SKP container versions.

    Modern files store these values in the ``0x01FB`` block; legacy files use
    a versioned ``CRenderingOptions`` body.

    Controls edge display, face colors, fog, sky, ground, shadows,
    section cuts, transparency, ambient occlusion, and many other
    visual settings.

    All color fields are encoded as 32-bit ARGB integers
    (``0xAARRGGBB``).  Distances are in SketchUp inches.

    Attributes
    ----------
    render_mode : int
        Render mode enum.
    model_transparency : bool
        Enable model-level transparency.
    material_transparency : bool
        Enable material-level transparency.
    texture : bool
        Whether textures are displayed.
    edge_display_mode : int
        Edge display mode.
    edge_type : int
        Edge type enum.
    display_sketch_axes : bool
        Whether sketch axes are shown.
    display_text : bool
        Whether text entities are shown.
    display_dims : bool
        Whether dimension entities are shown.
    hide_construction_geometry : bool
        Hide construction geometry.
    display_color_by_layer : bool
        Color faces by their layer assignment.
    edge_color_mode : int
        Edge color mode.
    face_color_mode : int
        Legacy face color mode enum.
    display_instance_axes : bool
        Show component instance axes.
    jitter_edges : bool
        Jitter extension lines.
    line_style_edges : bool
        Use line-style edges.
    extend_lines : bool
        Extend lines past endpoints.
    line_extension : int
        Extension length.
    draw_silhouettes : bool
        Draw silhouette edges.
    silhouette_width : int
        Silhouette edge width.
    draw_depth_que : bool
        Draw depth cue.
    depth_que_width : int
        Depth cue line width.
    draw_line_ends : bool
        Draw line endpoints.
    line_end_width : int
        Line end width.
    draw_profiles_only : bool
        Draw profiles only.
    draw_back_edges : bool
        Draw back-facing edges.
    background_color : int
        ARGB background color.
    foreground_color : int
        ARGB foreground color.
    highlight_color : int
        ARGB highlight color.
    locked_color : int
        ARGB locked-element color.
    construction_color : int
        ARGB construction geometry color.
    face_front_color : int
        ARGB front-face color.
    face_back_color : int
        ARGB back-face color.
    display_watermarks : bool
        Show watermarks.
    display_fog : bool
        Show fog.
    fog_color : int
        ARGB fog color.
    fog_use_background_color : bool
        Use background color for fog.
    fog_start_dist : float
        Fog start distance (inches).
    fog_end_dist : float
        Fog end distance (inches).
    fog_hint_mode : int
        Fog hint mode.
    sky_color : int
        ARGB sky color.
    horizon_color : int
        ARGB horizon color.
    ground_color : int
        ARGB ground color.
    draw_horizon : bool
        Draw horizon line.
    draw_ground : bool
        Draw ground plane.
    draw_underground : bool
        Draw underground.
    ground_transparency : int
        Ground plane transparency.
    inactive_fade : float
        Fade factor for inactive entities.
    instance_fade : float
        Fade factor for instances.
    inactive_hidden : bool
        Hide inactive entities.
    instance_hidden : bool
        Hide instances.
    section_active_color : int
        ARGB active section cut color.
    section_inactive_color : int
        ARGB inactive section color.
    section_default_cut_color : int
        ARGB default cut color.
    section_default_fill_color : int
        ARGB default fill color.
    section_cut_width : int
        Section cut line width.
    section_display_mode : int
        Section display bitmask. Bit 0 controls section planes and bit 1
        controls section cuts.
    display_section_planes : bool
        Whether section planes are displayed.
    display_section_cuts : bool
        Whether section cuts are displayed.
    section_cut_filled : bool
        Whether section cuts are filled.
    transparency_sort : int
        Transparency sort order.
    xray_opacity : float
        X-ray mode opacity.
    draw_soft_edges : bool
        Whether edges marked soft are hidden.
    soft_edge_limit : float
        Angular soft-edge limit in radians.
    draw_smooth_edges : bool
        Whether edges marked smooth affect displayed normals.
    photomatch_draw_background : bool
        Draw photomatch background.
    photomatch_background_opacity : float
        Photomatch background opacity.
    photomatch_draw_overlay : bool
        Draw photomatch overlay.
    photomatch_overlay_opacity : float
        Photomatch overlay opacity.
    draw_hidden_geometry : bool
        Draw hidden geometry.
    draw_hidden_objects : bool
        Draw hidden objects.
    hide_custom_control_points : bool
        Hide custom control points.
    ambient_occlusion : bool
        Enable ambient occlusion.
    ao_distance : int
        AO sampling distance.
    ao_intensity : int
        AO intensity.
    ao_multiplier : int
        AO multiplier.
    ao_color : int
        ARGB AO color.
    ao_color_enabled : bool
        Whether AO color is enabled.
    """

    render_mode: int = 0
    model_transparency: bool = False
    material_transparency: bool = False
    texture: bool = True
    edge_display_mode: int = 0
    edge_type: int = 0
    display_sketch_axes: bool = False
    display_text: bool = True
    display_dims: bool = True
    hide_construction_geometry: bool = False
    display_color_by_layer: bool = False
    edge_color_mode: int = 0
    face_color_mode: int = 0
    display_instance_axes: bool = False
    jitter_edges: bool = False
    line_style_edges: bool = False
    extend_lines: bool = False
    line_extension: int = 0
    draw_silhouettes: bool = False
    silhouette_width: int = 0
    draw_depth_que: bool = False
    depth_que_width: int = 0
    draw_line_ends: bool = False
    line_end_width: int = 0
    draw_profiles_only: bool = False
    draw_back_edges: bool = False
    background_color: int = 0xFFFFFFFF
    foreground_color: int = 0xFF000000
    highlight_color: int = 0xFF00FF00
    locked_color: int = 0xFF808080
    construction_color: int = 0xFF808080
    face_front_color: int = 0xFFFFFFFF
    face_back_color: int = 0xFFCCCCCC
    display_watermarks: bool = False
    display_fog: bool = False
    fog_color: int = 0xFFCCCCCC
    fog_use_background_color: bool = False
    fog_start_dist: float = 0.0
    fog_end_dist: float = 0.0
    fog_hint_mode: int = 0
    sky_color: int = 0xFF87CEEB
    horizon_color: int = 0xFFC0D8E8
    ground_color: int = 0xFF8B4513
    draw_horizon: bool = False
    draw_ground: bool = False
    draw_underground: bool = False
    ground_transparency: int = 0
    inactive_fade: float = 0.0
    instance_fade: float = 0.0
    inactive_hidden: bool = False
    instance_hidden: bool = False
    section_active_color: int = 0xFF000000
    section_inactive_color: int = 0xFF808080
    section_default_cut_color: int = 0xFF000000
    section_default_fill_color: int = 0x00000000
    section_cut_width: int = 0
    section_display_mode: int = 0
    section_cut_filled: bool = False
    transparency_sort: int = 0
    xray_opacity: float = 0.0
    draw_soft_edges: bool = False
    soft_edge_limit: float = 0.0
    draw_smooth_edges: bool = False
    photomatch_draw_background: bool = False
    photomatch_background_opacity: float = 0.0
    photomatch_draw_overlay: bool = False
    photomatch_overlay_opacity: float = 0.0
    draw_hidden_geometry: bool = False
    draw_hidden_objects: bool = False
    hide_custom_control_points: bool = False
    ambient_occlusion: bool = False
    ao_distance: int = 0
    ao_intensity: int = 0
    ao_multiplier: int = 0
    ao_color: int = 0xFFFFFFFF
    ao_color_enabled: bool = False

    @property
    def display_section_planes(self) -> bool:
        """Return whether section planes are displayed."""
        return bool(self.section_display_mode & 0x1)

    @display_section_planes.setter
    def display_section_planes(self, value: bool) -> None:
        """Update the section-plane bit without changing section cuts."""
        if value:
            self.section_display_mode |= 0x1
        else:
            self.section_display_mode &= ~0x1

    @property
    def display_section_cuts(self) -> bool:
        """Return whether section cuts are displayed."""
        return bool(self.section_display_mode & 0x2)

    @display_section_cuts.setter
    def display_section_cuts(self, value: bool) -> None:
        """Update the section-cut bit without changing section planes."""
        if value:
            self.section_display_mode |= 0x2
        else:
            self.section_display_mode &= ~0x2


# -
# Watermarks
# -


@dataclass(slots=True)
class Watermark:
    """
    A single watermark definition (SUWatermark).

    Watermarks are overlay images displayed on the model viewport.

    Attributes
    ----------
    name : str
        Watermark display name.
    image_data : bytes or None
        Raw image data (PNG/JPEG bytes), or None if not loaded.
    opacity : float
        Opacity from 0.0 (fully transparent) to 1.0 (fully opaque).
    position : int
        Position enum (0 = center, 1 = top-left, 2 = top-right,
        3 = bottom-left, 4 = bottom-right, 5 = tile).
    id : int
        Persistent entity ID when decoded from a modern file.
    """

    name: str = ""
    image_data: Optional[bytes] = None
    opacity: float = 1.0
    position: int = 0
    id: int = 0


@dataclass(slots=True)
class WatermarkManager:
    """
    Watermark manager storing all watermarks (SUWatermarkManager).

    Modern files store this manager in the ``0x0203`` block.

    Attributes
    ----------
    watermarks : list of Watermark
        All watermark definitions in the model.
    serialized_count : int
        Serialized watermark count from the file.
    """

    watermarks: List[Watermark] = field(default_factory=list)
    serialized_count: int = 0


# -
# Styles
# -


@dataclass(slots=True)
class StyleDescriptor:
    """
    A single style descriptor within the styles registry.

    Each style references a .style file and optionally a set of
    watermark references.

    Attributes
    ----------
    guid : bytes
        16-byte GUID blob identifying the style.
    display_name : str
        Human-readable style name.
    file_name : str
        Path to the .style file on disk.
    watermark_reference_ids : list of int
        IDs of watermarks associated with this style.
    xml_data : bytes or None
        Optional complete style XML resource used by the writer.
    """

    guid: bytes = b"\x00" * 16
    display_name: str = ""
    file_name: str = ""
    watermark_reference_ids: List[int] = field(default_factory=list)
    xml_data: Optional[bytes] = field(default=None, repr=False)


@dataclass(slots=True)
class StylesRegistry:
    """
    Styles registry (SUStyles).

    Modern files store this registry in the ``0x0206`` block. It contains all
    styles available in the model and a reference to the active style.

    Attributes
    ----------
    styles : list of StyleDescriptor
        All style descriptors.
    active_style_ref : int
        Reference ID of the currently active style.
    inline_style_override : StyleDescriptor or None
        Inline style override, if any.
    selected_style_dirty : bool
        Whether the selected style has unsaved changes.
    """

    styles: List[StyleDescriptor] = field(default_factory=list)
    active_style_ref: int = 0
    inline_style_override: Optional[StyleDescriptor] = None
    selected_style_dirty: bool = False


# -
# Fonts
# -


@dataclass(slots=True)
class Font:
    """
    A font definition (SUFont).

    Modern files store fonts in the ``0x01FD`` block.

    Attributes
    ----------
    face_name : str
        Font family name (e.g. ``"Arial"``, ``"Times New Roman"``).
    bold : bool
        Whether the font is bold.
    italic : bool
        Whether the font is italic.
    point_size : int
        Font size in points.
    use_world_size : bool
        If True, ``world_size`` is used instead of ``point_size``.
    world_size : float
        Font size in SketchUp inches (used when ``use_world_size`` is True).
    """

    face_name: str = ""
    bold: bool = False
    italic: bool = False
    point_size: int = 0
    use_world_size: bool = False
    world_size: float = 0.0


# -
# Text style
# -


@dataclass(slots=True)
class TextStyle:
    """
    Text style settings (SUTextStyle).

    Modern files store this style in the ``0x01FE`` block. It controls how text
    entities are rendered (font, color, leader behavior, etc.).

    Attributes
    ----------
    font_ref : int
        Reference to the font definition.
    screen_font_ref : int
        Reference to the screen-space font.
    arrow_type : int
        Arrow type enum (0 = none, 1 = dot, 2 = closed, 3 = open).
    line_weight : int
        Line weight for leaders.
    hide_out_of_plane : bool
        Hide text that is out of the viewing plane.
    leader_type : int
        Leader type enum (0 = none, 1 = view-based, 2 = pushpin).
    display_leader : bool
        Whether leaders are displayed.
    color : int
        ARGB text color.
    screen_color : int
        ARGB screen-space text color.
    """

    font_ref: int = 0
    screen_font_ref: int = 0
    arrow_type: int = 0
    line_weight: int = 0
    hide_out_of_plane: bool = False
    leader_type: int = 0
    display_leader: bool = True
    color: int = 0xFF000000
    screen_color: int = 0xFF000000


# -
# Dimension style
# -


@dataclass(slots=True)
class DimensionStyle:
    """
    Dimension style settings (SUDimensionStyle).

    Modern files store this style in the ``0x01FF`` block. It controls how
    dimension entities are rendered.

    Attributes
    ----------
    font_ref : int
        Reference to the font definition.
    text_3d : bool
        Whether dimension text is 3-D.
    always_readable : bool
        Whether text is always readable (auto-orient).
    extension_offset : int
        Extension line offset.
    extension_overshoot : int
        Extension line overshoot past dimension line.
    line_weight : int
        Dimension line weight.
    arrow_type : int
        Arrow type enum (0 = none, 1 = dot, 2 = closed, 3 = open).
    arrow_size : int
        Arrow size.
    highlight_non_associative : bool
        Highlight non-associative dimensions.
    highlight_non_associative_color : int
        ARGB highlight color for non-associative dims.
    show_radial_diameter_prefix : bool
        Show radial/diameter prefix.
    hide_out_of_plane : bool
        Hide dimensions out of the viewing plane.
    hide_out_of_plane_value : float
        Threshold angle for hiding (radians).
    hide_small : bool
        Hide dimensions smaller than a threshold.
    hide_small_value : float
        Small dimension threshold (inches).
    color : int
        ARGB dimension line color.
    text_color : int
        ARGB dimension text color.
    text_position : int
        Text position enum (0 = above, 1 = inline, 2 = below).
    """

    font_ref: int = 0
    text_3d: bool = False
    always_readable: bool = False
    extension_offset: int = 0
    extension_overshoot: int = 0
    line_weight: int = 0
    arrow_type: int = 0
    arrow_size: int = 0
    highlight_non_associative: bool = False
    highlight_non_associative_color: int = 0xFF00FF00
    show_radial_diameter_prefix: bool = False
    hide_out_of_plane: bool = False
    hide_out_of_plane_value: float = 0.0
    hide_small: bool = False
    hide_small_value: float = 0.0
    color: int = 0xFF000000
    text_color: int = 0xFF000000
    text_position: int = 0


# -
# Line styles
# -


@dataclass(slots=True)
class LineStyle:
    """
    A line style definition (SULineStyle).

    Modern files store these values in the ``0x0208`` block. They define custom
    dash patterns and stipple styles for edges.

    Attributes
    ----------
    name : str
        Style name.
    dash_pattern : str
        Dash pattern string (e.g. ``"-.-"``).
    stipple_scale : float
        Stipple pattern scale factor.
    line_width_points : float
        Line width in points.
    color : int
        ARGB line color.
    mutability : bool
        Whether the style can be modified by the user.
    """

    name: str = ""
    dash_pattern: str = ""
    stipple_scale: float = 1.0
    line_width_points: float = 1.0
    color: int = 0xFF000000
    mutability: bool = True


# -
# Options manager
# -


@dataclass(slots=True)
class OptionsProvider:
    """
    A single options provider within the options manager.

    Each provider groups a set of key-value configuration options
    (e.g. ``"UnitsOptions"``, ``"PageOptions"``).

    Attributes
    ----------
    name : str
        Provider name (e.g. ``"UnitsOptions"``).
    keys : dict of str to bool, int, float, or str
        Key-value option pairs.
    """

    name: str = ""
    keys: Dict[str, bool | int | float | str] = field(default_factory=dict)


@dataclass(slots=True)
class OptionsManager:
    """
    Options manager (SUOptionsManager).

    Modern files store this manager in the ``0x0200`` block. It contains all
    options providers that store application-level settings.

    Attributes
    ----------
    providers : list of OptionsProvider
        All options providers.
    """

    providers: List[OptionsProvider] = field(default_factory=list)


# -
# Environment data
# -


@dataclass(slots=True)
class EnvironmentEntry:
    """
    A single environment entry.

    Represents a sky/ground/environment preset.

    Attributes
    ----------
    id : int
        Entry ID.
    name : str
        Display name of the environment.
    thumbnail_path : str
        Path to the thumbnail image file.
    image_filename : str
        Basename of the HDR or EXR image stored with the environment.
    image_data : bytes or None
        Image bytes used when writing the environment resource.
    thumbnail_data : bytes or None
        Optional thumbnail bytes stored at ``thumbnail_path``.
    description : str
        Human-readable environment description.
    use_as_skydome : bool
        Whether the image is enabled as the model skydome.
    use_for_reflections : bool
        Whether the image is enabled for image-based reflections.
    rotation : float
        Horizontal image rotation in degrees.
    skydome_exposure : float
        Skydome exposure multiplier.
    reflection_exposure : float
        Reflection exposure multiplier.
    """

    id: int = 0
    name: str = ""
    thumbnail_path: str = ""
    image_filename: str = ""
    image_data: Optional[bytes] = field(default=None, repr=False)
    thumbnail_data: Optional[bytes] = field(default=None, repr=False)
    description: str = ""
    use_as_skydome: bool = False
    use_for_reflections: bool = False
    rotation: float = 0.0
    skydome_exposure: float = 1.0
    reflection_exposure: float = 1.0


@dataclass(slots=True)
class EnvironmentData:
    """
    Environment data (SUEnvironment).

    Modern files store this data in the ``0x0210`` block. It contains
    environment presets (sky/ground settings).

    Attributes
    ----------
    selected : EnvironmentEntry or None
        The currently selected environment entry.
    entries : list of EnvironmentEntry
        All available environment entries.
    """

    selected: Optional[EnvironmentEntry] = None
    entries: List[EnvironmentEntry] = field(default_factory=list)


# -
# Sun data
# -


@dataclass(slots=True)
class SunData:
    """
    Sun data (SUSunData).

    Modern files store this data in the ``0x0213`` block. The internal format
    is not yet fully mapped; the raw TLV payload is preserved for inspection.

    Attributes
    ----------
    raw_payload : bytes or None
        Raw TLV payload bytes of the sun data record.
    """

    raw_payload: Optional[bytes] = None


# -
# Model view / sketch axes
# -


@dataclass(slots=True)
class ModelViewAxes:
    """
    Sketch axes origin and orientation (SUAxes).

    Modern files store these axes in the ``0x01FC`` block. They define the
    model-space coordinate system axes displayed in the viewport.

    All positions are in SketchUp inches.

    Attributes
    ----------
    origin : tuple of float
        Axes origin ``(x, y, z)`` in model space (inches).
    x_axis : tuple of float
        X-axis direction unit vector ``(dx, dy, dz)``.
    y_axis : tuple of float
        Y-axis direction unit vector ``(dx, dy, dz)``.
    z_axis : tuple of float
        Z-axis direction unit vector ``(dx, dy, dz)``.
    flags : int
        Display flags bitmask.
    """

    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    x_axis: Tuple[float, float, float] = (1.0, 0.0, 0.0)
    y_axis: Tuple[float, float, float] = (0.0, 1.0, 0.0)
    z_axis: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    flags: int = 0


# -
# Attribute dictionaries
# -


@dataclass(slots=True)
class AttributeDictionaryEntry:
    """
    A single typed key-value entry in an attribute dictionary.

    Values are stored in a type-tagged union.  The ``value_type`` field
    determines which value field is valid:

    * 0 -- ``int_value``
    * 1 -- ``float_value``
    * 2 -- ``bool_value``
    * 3 -- ``string_value``
    * 4 -- ``nested_payload`` (nested TLV blob)

    Attributes
    ----------
    key : str
        Entry key name.
    flags : int
        Entry flags bitmask.
    value_type : int
        Type code (0 = int, 1 = float, 2 = bool, 3 = string, 4 = nested).
    int_value : int
        Integer payload (valid when ``value_type == 0``).
    float_value : float
        Float64 payload (valid when ``value_type == 1``).
    bool_value : bool
        Boolean payload (valid when ``value_type == 2``).
    string_value : str
        String payload (valid when ``value_type == 3``).
    nested_payload : bytes or None
        Nested TLV blob (valid when ``value_type == 4``).
    """

    key: str = ""
    flags: int = 0
    value_type: int = 0
    int_value: int = 0
    float_value: float = 0.0
    bool_value: bool = False
    string_value: str = ""
    nested_payload: Optional[bytes] = None


@dataclass(slots=True)
class AttributeDictionary:
    """
    A named attribute dictionary (SUAttributeDictionary).

    Modern files store these dictionaries in the ``0x0209`` model-properties
    block. Each dictionary
    has a name and a list of typed key-value entries.

    Attributes
    ----------
    name : str
        Dictionary name.
    entries : list of AttributeDictionaryEntry
        Typed key-value entries.
    """

    name: str = ""
    entries: List[AttributeDictionaryEntry] = field(default_factory=list)


@dataclass(slots=True)
class EntityRelationship:
    """A directed relationship between two entities in the same scope."""

    source_id: int | None = None
    target_id: int | None = None
