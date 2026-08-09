# SPDX-License-Identifier: MIT
"""Construction geometry, camera, and georeferenced shadow settings.

Guide points, guide lines, and section planes live in an
:class:`~skppy.data_structure.entities.Entities` scope. Cameras and
:class:`ShadowInfo` are model metadata. Positions and distances use SketchUp's
native inch unit; direction vectors are unitless.

Example
-------
::

    import skppy

    model = skppy.new_model()
    model.entities.guide_points.append(
        skppy.GuidePoint(id=1, position=skppy.Vector3D(12, 0, 0))
    )
    model.cameras.append(
        skppy.Camera(
            eye=skppy.Vector3D(120, 120, 96),
            target=skppy.Vector3D(0, 0, 0),
        )
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from .primitives import Vector3D


@dataclass(slots=True)
class GuidePoint:
    """
    A construction guide point (SUGuidePoint).

    Guide points are reference points that can be placed in the model
    to assist with precision modeling.  They are stored in the
    TAG_GUIDE_POINTS (0x1392) section of the entities block.

    Attributes
    ----------
    id : int
        Entity ID extracted from the entity base record.
    position : tuple of float or Vector3D
        3-D position ``(x, y, z)`` in SketchUp inches.
    reference_point : tuple of float or Vector3D, optional
        Optional endpoint of the construction segment drawn to the guide point.
    layer_id : int or None
        Owning layer/tag ID.
    """

    id: int = 0
    position: Tuple[float, float, float] | Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    reference_point: Optional[Tuple[float, float, float] | Vector3D] = None
    layer_id: Optional[int] = None


@dataclass(slots=True)
class GuideLine:
    """
    A construction guide line (SUGuideLine).

    Guide lines are infinite or finite reference lines.  They are stored
    in the TAG_GUIDE_LINES (0x1391) section of the entities block.

    Attributes
    ----------
    id : int
        Entity ID extracted from the entity base record.
    point : tuple of float or Vector3D
        A point on the line ``(x, y, z)`` in SketchUp inches.
    direction : tuple of float or Vector3D
        Direction vector ``(dx, dy, dz)`` (unit vector).
    stipple_pattern : int
        16-bit line stipple pattern used to draw the guide.
    start_parameter, end_parameter : float
        Bounds along the unit direction. ``-1e30``/``+1e30`` represent an
        infinite line; finite bounds preserve construction segments.
    layer_id : int or None
        Owning layer/tag ID.
    """

    id: int = 0
    point: Tuple[float, float, float] | Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    direction: Tuple[float, float, float] | Vector3D = field(default_factory=lambda: Vector3D(1.0, 0.0, 0.0))
    stipple_pattern: int = 0
    start_parameter: float = -1.0e30
    end_parameter: float = 1.0e30
    layer_id: Optional[int] = None


@dataclass(slots=True)
class SectionPlane:
    """
    A section plane (SUSectionPlane).

    Section planes define a cutting plane that can hide geometry on one
    side.  They are stored in the TAG_SECTION_PLANES (0x1393) section of
    the entities block.

    Attributes
    ----------
    id : int
        Entity ID extracted from the entity base record.
    plane : tuple of float
        Plane equation ``(a, b, c, d)`` where ``ax + by + cz + d = 0``.
    name : str
        Display name of the section plane.
    symbol : str
        Symbol string (often empty).
    layer_id : int or None
        Owning layer/tag ID.
    """

    id: int = 0
    plane: Tuple[float, float, float, float] = (0.0, 0.0, 1.0, 0.0)
    name: str = ""
    symbol: str = ""
    layer_id: Optional[int] = None


# -
# Shadow info
# -


@dataclass(slots=True)
class ShadowInfo:
    """
    Geo-referenced shadow settings (SUShadowInfo).

    Stored in the TAG_SHADOW_INFO_BLOCK (0x0204) section of model.dat.
    Contains location, time, and display settings for shadow calculation.

    Attributes
    ----------
    latitude : float
        Latitude in degrees.
    longitude : float
        Longitude in degrees.
    time : int
        Time value (compact int, internal representation).
    daylight_savings : bool
        Whether daylight savings time is active.
    city : bytes
        Raw city name bytes (encoding unresolved).
    country : bytes
        Raw UTF-8 country name bytes.
    timezone_offset : float
        Timezone offset in hours.
    north_direction : tuple of float
        North direction vector ``(x, y, z)`` in model space.
    display_shadows : bool
        Whether shadows are displayed.
    display_north : bool
        Whether the north direction is displayed.
    display_on_all_faces : bool
        Whether shadows are cast on all faces.
    display_on_ground_plane : bool
        Whether shadows are cast on the ground plane.
    edges_cast_shadows : bool
        Whether edges cast shadows.
    light : int
        Light intensity (compact int).
    dark : int
        Dark intensity (compact int).
    use_sun_for_all_shading : bool
        Whether the sun is used for all shading.
    """

    latitude: float = 0.0
    longitude: float = 0.0
    time: int = 0
    daylight_savings: bool = False
    city: bytes = b""
    country: bytes = b""
    timezone_offset: float = 0.0
    north_direction: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    display_shadows: bool = False
    display_north: bool = False
    display_on_all_faces: bool = False
    display_on_ground_plane: bool = False
    edges_cast_shadows: bool = False
    light: int = 0
    dark: int = 0
    use_sun_for_all_shading: bool = False


# -
# Camera
# -


@dataclass(slots=True)
class Camera:
    """
    A SketchUp camera (saved view).

    Positions are stored in SketchUp internal units (inches).
    Use a scale factor when converting to Blender.

    Attributes
    ----------
    eye : Vector3D
        Camera position ``(x, y, z)`` in inches.
    target : Vector3D
        Look-at point ``(x, y, z)`` in inches.
    up : Vector3D
        Up direction unit vector ``(x, y, z)``.
    fov : float
        Field of view in degrees (vertical if ``fov_is_height``,
        otherwise horizontal).  Default 35.0.
    fov_is_height : bool
        If True, ``fov`` is vertical FOV; otherwise horizontal.
    is_perspective : bool
        True for perspective, False for parallel/ortho projection.
    near : float
        Near clipping distance (inches).  Default 1.0.
    far : float
        Far clipping distance (inches).  Default 10000.0.
    name : str
        Optional camera/scene name.
    ortho_height : float or None
        Parallel-projection viewport height (inches).
    aspect_ratio : float or None
        Viewport aspect ratio (width / height).
    legacy_flag : bool
        Legacy camera flag (0x34C7).
    image_width : float or None
        Camera image width (0x34C9).
    is_2d : bool
        Whether the camera is in 2-D mode (0x34CA).
    scale_2d : float or None
        2-D camera scale factor (0x34CB).
    center_2d_x : float or None
        2-D camera center X (0x34CC).
    center_2d_y : float or None
        2-D camera center Y (0x34CD).
    allow_clipping : bool
        Whether clipping is allowed in parallel projection (0x34CE).
    """

    eye: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    target: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, -1.0))
    up: Vector3D = field(default_factory=lambda: Vector3D(0.0, 1.0, 0.0))
    fov: float = 35.0  # degrees
    fov_is_height: bool = True
    is_perspective: bool = True
    near: float = 1.0  # inches
    far: float = 10000.0  # inches
    name: str = ""
    ortho_height: Optional[float] = None  # parallel-projection viewport height (inches)
    aspect_ratio: Optional[float] = None  # viewport aspect ratio (width / height)
    legacy_flag: bool = False  # TAG_CAMERA_LEGACY_FLAG (0x34C7)
    image_width: Optional[float] = None  # TAG_CAMERA_IMAGE_WIDTH (0x34C9)
    is_2d: bool = False  # TAG_CAMERA_IS_2D (0x34CA)
    scale_2d: Optional[float] = None  # TAG_CAMERA_2D_SCALE (0x34CB)
    center_2d_x: Optional[float] = None  # TAG_CAMERA_2D_CENTER_X (0x34CC)
    center_2d_y: Optional[float] = None  # TAG_CAMERA_2D_CENTER_Y (0x34CD)
    allow_clipping: bool = True  # TAG_CAMERA_ALLOW_CLIPPING (0x34CE)
