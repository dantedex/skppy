# SPDX-License-Identifier: MIT
"""
Scene (named page / saved view) data class.

.. module:: skppy.data_structure.scene_data
   :synopsis: Scene data structure

A separate module is used to avoid naming conflicts with
:mod:`skppy.data_structure.scene` (which contains rendering utilities).

Example
-------
::

    scene = Scene(id=1, name="Scene 1", description="Main view")
    print(scene.name, scene.show_in_slideshow)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .construction import Camera
from .primitives import Vector3D


@dataclass(slots=True)
class PageBackgroundImage:
    """An image used as a scene background or match-photo overlay."""

    path: str = ""
    reference_state: int = 0
    image_data: bytes | None = None
    width: int = 0
    height: int = 0
    file_size: int = 0
    timestamp: int = 0
    visible: bool = False
    opacity: float = 1.0
    grip_points: list[Vector3D] = field(default_factory=list)
    principal_point_delta: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    radial_distortion_k1: float = 0.0
    image_source: int = 0
    id: int = 0


@dataclass(slots=True)
class Scene:
    """
    A SketchUp named scene / page (a saved camera + layer state).

    Most scene attributes are stored inside the TAG_SCENES_BLOCK (0x0207)
    section of model.dat.  Unknown sub-payloads are preserved verbatim in
    ``raw_payload`` so no information is lost.

    Parameters
    ----------
    id : int
        Persistent scene ID, or a sequential 1-based fallback for records that
        do not store one.
    name : str
        Display name of the scene (e.g. ``"Scene 1"``).
    description : str, optional
        Optional user description / notes.
    flags : int, optional
        Bitmask of scene flags (TAG_SCENE_FLAGS, 0x7149).
    hidden_entity_ids : list of int, optional
        Entity IDs hidden in this scene (TAG_SCENE_HIDDEN_ENTITY_IDS, 0x714B).
    hidden_layer_ids : list of int, optional
        Layer IDs hidden in this scene (TAG_SCENE_HIDDEN_LAYER_IDS, 0x7150).
    active_section_plane_ids : list of int, optional
        Section plane IDs active in this scene
        (TAG_SCENE_ACTIVE_SECTION_PLANE_IDS, 0x7151).
    show_in_slideshow : bool, optional
        Whether the scene is included in slideshow playback
        (TAG_SCENE_SHOW_IN_SLIDESHOW, 0x7152).
    camera : Camera or None, optional
        Saved camera snapshot when the scene stores one.
    style_reference : int, optional
        Style reference ID (TAG_SCENE_STYLE_REF, 0x714C).
    background_image_ref : int, optional
        Background image reference ID (TAG_SCENE_BACKGROUND_IMAGE_REF, 0x7156).
    background_image : PageBackgroundImage or None, optional
        Decoded background/match-photo image when the source stores it inline.
    display_background_image : bool, optional
        Whether the image is enabled for this saved scene.
    raw_payload : bytes or None, optional
        The full binary payload of the scene record, preserved for future
        parsing and round-tripping.

    Examples
    --------
    >>> scene = Scene(id=1, name="Scene 1", description="Main view")
    >>> scene.name
    'Scene 1'
    """

    id: int
    name: str
    description: str = ""
    flags: int = 0
    hidden_entity_ids: List[int] = field(default_factory=list)
    hidden_layer_ids: List[int] = field(default_factory=list)
    active_section_plane_ids: List[int] = field(default_factory=list)
    show_in_slideshow: bool = True
    camera: Optional[Camera] = None
    style_reference: int = 0
    background_image_ref: int = 0
    background_image: Optional[PageBackgroundImage] = None
    display_background_image: bool = False
    raw_payload: Optional[bytes] = None
