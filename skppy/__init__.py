# SPDX-License-Identifier: MIT
"""
Python toolkit for reading and writing SketchUp (.skp) files.

.. module:: skppy
   :synopsis: Python toolkit for reading and writing SketchUp .skp files

This package parses modern versionless ZIP-based .skp files (SketchUp 2021+)
and earlier CArchive files. Both paths produce
:class:`Model` objects containing geometry, materials, layers, component
definitions, cameras, scenes, and all model metadata.

Quick Start
-----------
::

    import skppy

    model = skppy.load("my_model.skp")
    print(model.header.version_string)       # e.g. "{26.1.103}"
    print(len(model.entities.faces))         # number of root-level faces
    print(len(model.materials))              # number of materials

    for face in model.entities.faces:
        print(face.id, face.plane)
        triangles = face.triangulate(model.entities)

See the `full documentation <https://dantedex.github.io/skppy/>`_ for details.
"""

from importlib.metadata import PackageNotFoundError, version as _metadata_version
from pathlib import Path
from typing import Literal

from .load_limits import LoadLimits
from .data_structure import (
    ArcCurve,
    ArcGeometry,
    AttributeDictionary,
    AttributeDictionaryEntry,
    Camera,
    Color,
    ComponentDefinition,
    ComponentInstance,
    Curve,
    Dimension,
    DimensionStyle,
    DrawingElementProperties,
    Edge,
    EdgeUse,
    Entities,
    EntityRelationship,
    EnvironmentData,
    EnvironmentEntry,
    Face,
    FaceUVProjection,
    Font,
    Group,
    GuideLine,
    GuidePoint,
    Image,
    Layer,
    LayerFolder,
    LinearDimension,
    LineStyle,
    Loop,
    Material,
    Model,
    ModelViewAxes,
    OptionsManager,
    OptionsProvider,
    PageBackgroundImage,
    PointReference,
    RadialDimension,
    RenderingOptions,
    Scene,
    SectionPlane,
    ShadowInfo,
    SkpDocument,
    SkpHeader,
    SkpZipEntry,
    StyleDescriptor,
    StylesRegistry,
    Texture,
    Text,
    TextStyle,
    Transform,
    UVPin,
    Vector2D,
    Vector3D,
    Vertex,
    Watermark,
    WatermarkManager,
)
from .data_structure.scene import (
    IndexedPreparedMesh,
    PreparedFace,
    PreparedMesh,
    SceneNode,
)
from .exceptions import (
    ComponentCycleError,
    InvalidSkmError,
    InvalidSkpError,
    LoadCancelledError,
    OldFormatError,
)
from .loader import load
from .material_loader import load_material

try:
    # The generated module is bundled into the Blender add-on, where package
    # metadata may refer to an unrelated system installation of skppy.
    from ._version import __version__
except (AttributeError, ImportError):
    try:
        __version__ = _metadata_version("skppy")
    except PackageNotFoundError:
        __version__ = "0+unknown"

__all__ = [
    "ArcCurve",
    "ArcGeometry",
    "AttributeDictionary",
    "AttributeDictionaryEntry",
    "Camera",
    "Color",
    "ComponentCycleError",
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
    "InvalidSkmError",
    "InvalidSkpError",
    "Layer",
    "LayerFolder",
    "LineStyle",
    "LinearDimension",
    "LoadCancelledError",
    "LoadLimits",
    "Loop",
    "Material",
    "Model",
    "ModelViewAxes",
    "OldFormatError",
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
    "SkpZipEntry",
    "StyleDescriptor",
    "StylesRegistry",
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
    "__version__",
    "load",
    "load_material",
    "new_model",
    "save",
]


def new_model() -> Model:
    """
    Create a new, empty :class:`Model`.

    This is a convenience alias for :meth:`Model.new`.

    Returns
    -------
    Model
        An empty model with default header and empty containers.

    Example
    -------
    ::

        model = skppy.new_model()
        brick = model.add_material("Brick", color=skppy.Color(180, 80, 60))
        defn = model.add_definition("Wall")
        face = defn.entities.add_face([(0,0,0),(300,0,0),(300,250,0),(0,250,0)])
        face.front_material_id = brick.id
        model.entities.add_instance(defn)
    """
    return Model.new()


def save(
    model: Model,
    filepath: str | Path,
    *,
    header: SkpHeader | None = None,
    format: Literal["modern", "sketchup_2017"] = "modern",
) -> Path:
    """
    Save a SketchUp model to a .skp file.

    Parameters
    ----------
    model : Model
        The model to serialize.
    filepath : str or pathlib.Path
        Destination file path.
    header : SkpHeader or None, optional
        Explicit modern VFF header. The validated writer default is used when
        omitted.
    format : {"modern", "sketchup_2017"}, optional
        Output container. ``"modern"`` writes the current ZIP/VFF format;
        ``"sketchup_2017"`` writes the pre-ZIP SketchUp Make 2017 format.

    Returns
    -------
    pathlib.Path
        Destination path after the complete model has been serialized.

    Example
    -------
    ::

        skppy.save(model, "output.skp")
    """
    if format == "modern":
        from .writer import write_modern_model

        return write_modern_model(
            model,
            filepath,
            header=header,
        )
    if format == "sketchup_2017":
        if header is not None:
            raise ValueError("A modern VFF header cannot be used with SketchUp 2017 format")
        from .legacy_writter import write_legacy_2017_model

        return write_legacy_2017_model(
            model,
            filepath,
        )
    raise ValueError(f"Unknown SKP output format: {format!r}")
