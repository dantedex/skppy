# SPDX-License-Identifier: MIT
"""
Data structures for skppy.

.. module:: skppy.data_structure
   :synopsis: Data structures for parsed SketchUp models

This module re-exports all data-structure classes from their submodules:
- :mod:`skppy.data_structure.annotations` -- text and dimension entities
- :mod:`skppy.data_structure.primitives` -- vectors and transforms
- :mod:`skppy.data_structure.entities` -- geometry entities and containers
- :mod:`skppy.data_structure.construction` -- construction, camera and shadow data
- :mod:`skppy.data_structure.model` -- top-level model container
- :mod:`skppy.data_structure.materials` -- materials, colors, textures
- :mod:`skppy.data_structure.layers` -- layers and layer folders
- :mod:`skppy.data_structure.header` -- binary file header
- :mod:`skppy.data_structure.document` -- ZIP container metadata
- :mod:`skppy.data_structure.images` -- texture data
- :mod:`skppy.data_structure.meta` -- model metadata
- :mod:`skppy.data_structure.model_metadata` -- rendering options, styles, etc.
- :mod:`skppy.data_structure.scene` -- intermediate scene representation
- :mod:`skppy.data_structure.scene_data` -- named scenes
"""

from .annotations import (
    ArcGeometry,
    Dimension,
    DrawingElementProperties,
    LinearDimension,
    PointReference,
    RadialDimension,
    Text,
)
from .construction import Camera, GuideLine, GuidePoint, SectionPlane, ShadowInfo
from .document import SkpDocument, SkpZipEntry
from .entities import (
    ArcCurve,
    ComponentDefinition,
    ComponentInstance,
    Curve,
    Edge,
    EdgeUse,
    Entities,
    Face,
    FaceUVProjection,
    Group,
    Image,
    Loop,
    UVPin,
    Vertex,
)
from .header import SkpHeader
from .images import Texture
from .layers import Layer, LayerFolder
from .materials import (
    Color,
    Material,
)
from .meta import SkpMetaInfo
from .model import Model
from .model_metadata import (
    AttributeDictionary,
    AttributeDictionaryEntry,
    DimensionStyle,
    EntityRelationship,
    EnvironmentData,
    EnvironmentEntry,
    Font,
    LineStyle,
    ModelViewAxes,
    OptionsManager,
    OptionsProvider,
    RenderingOptions,
    StyleDescriptor,
    StylesRegistry,
    SunData,
    TextStyle,
    Watermark,
    WatermarkManager,
)
from .primitives import Transform, Vector2D, Vector3D
from .scene_data import PageBackgroundImage, Scene
from .scene import IndexedPreparedMesh, PreparedFace, PreparedMesh, SceneNode

__all__ = [
    "ArcCurve",
    "ArcGeometry",
    "AttributeDictionary",
    "AttributeDictionaryEntry",
    "Camera",
    "Color",
    "ComponentDefinition",
    "ComponentInstance",
    "Curve",
    "Dimension",
    "DimensionStyle",
    "DrawingElementProperties",
    "Edge",
    "EdgeUse",
    "Entities",
    "EntityRelationship",
    "EnvironmentData",
    "EnvironmentEntry",
    "Face",
    "FaceUVProjection",
    "Font",
    "Group",
    "GuideLine",
    "GuidePoint",
    "Image",
    "IndexedPreparedMesh",
    "Layer",
    "LayerFolder",
    "LineStyle",
    "LinearDimension",
    "Loop",
    "Material",
    "Model",
    "ModelViewAxes",
    "OptionsManager",
    "OptionsProvider",
    "PageBackgroundImage",
    "PointReference",
    "PreparedFace",
    "PreparedMesh",
    "RadialDimension",
    "RenderingOptions",
    "Scene",
    "SceneNode",
    "SectionPlane",
    "ShadowInfo",
    "SkpDocument",
    "SkpHeader",
    "SkpMetaInfo",
    "SkpZipEntry",
    "StyleDescriptor",
    "StylesRegistry",
    "SunData",
    "Text",
    "TextStyle",
    "Texture",
    "Transform",
    "UVPin",
    "Vector2D",
    "Vector3D",
    "Vertex",
    "Watermark",
    "WatermarkManager",
]
