# SPDX-License-Identifier: MIT
"""
Layer and LayerFolder data classes.

.. module:: skppy.data_structure.layers
   :synopsis: Layer and layer folder data structures

Layers (called "Tags" in modern SketchUp) control entity visibility.
LayerFolders group layers hierarchically.

Example
-------
::

    layer = Layer(id=1, name="Walls", visible=True)
    folder = LayerFolder(name="Architecture", visible=True)
    folder.child_layer_ids = [1, 2]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .materials import Material


@dataclass(slots=True)
class Layer:
    """
    A SketchUp layer (called "Tag" in modern SketchUp).

    Layers control entity visibility. Each entity in a SketchUp model
    is assigned to exactly one layer.

    Parameters
    ----------
    id : int
        Unique layer ID.
    name : str
        Display name.
    visible : bool
        Whether the layer is visible.
    material_id : int or None, optional
        Serialized ID of the layer display material.
    material : Material or None, optional
        Layer display material used by color-by-layer rendering. Modern files
        may embed this resource directly in the layer record.
    page_behavior : int, optional
        Serialized layer page behavior (TAG_LAYER_SCENE_FLAGS).

    Examples
    --------
    >>> layer = Layer(id=1, name="Walls", visible=True)
    >>> layer.name
    'Walls'
    """

    id: int = 0
    name: str = ""
    visible: bool = True
    material_id: Optional[int] = None
    material: Optional["Material"] = None
    page_behavior: int = 0


@dataclass(slots=True)
class LayerFolder:
    """
    A folder for grouping layers hierarchically.

    Parameters
    ----------
    name : str
        Display name.
    visible : bool
        Whether the folder is visible.
    child_layer_ids : list of int, optional
        IDs of layers directly contained in this folder.
    child_folders : list of LayerFolder, optional
        Nested sub-folders.

    Examples
    --------
    >>> folder = LayerFolder(name="Architecture", visible=True)
    >>> folder.child_layer_ids = [1, 2, 3]
    """

    name: str = ""
    visible: bool = True
    child_layer_ids: List[int] = field(default_factory=list)
    child_folders: List["LayerFolder"] = field(default_factory=list)
