# SPDX-License-Identifier: MIT
"""Top-level SketchUp document model and its high-level builder API.

:class:`Model` is returned by :func:`skppy.load` and accepted by
:func:`skppy.save`. It owns root entities plus document-wide registries such as
materials, layers, component definitions, scenes, cameras, styles, and fonts.
Builder methods allocate stable model IDs and should be preferred over manually
appending objects to those registries.

Example
-------
::

    import skppy

    model = skppy.new_model()
    walls = model.add_layer("Walls")
    paint = model.add_material("Paint", skppy.Color(230, 230, 220))
    face = model.entities.add_face(
        [(0, 0, 0), (144, 0, 0), (144, 0, 96), (0, 0, 96)]
    )
    face.layer_id = walls.id
    face.front_material_id = paint.id
    skppy.save(model, "wall.skp")
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

from .construction import Camera, ShadowInfo
from .entities import ComponentDefinition, Entities, Group
from .model_metadata import (
    AttributeDictionary,
    DimensionStyle,
    EnvironmentData,
    Font,
    LineStyle,
    ModelViewAxes,
    OptionsManager,
    RenderingOptions,
    StylesRegistry,
    SunData,
    TextStyle,
    WatermarkManager,
)
from .primitives import Transform

if TYPE_CHECKING:
    from .document import SkpDocument
    from .header import SkpHeader
    from .layers import Layer, LayerFolder
    from .materials import Color, Material
    from .scene import SceneNode
    from .scene_data import PageBackgroundImage, Scene


@dataclass
class Model:
    """
    Fully parsed SketchUp model.

    Top-level container returned by :func:`skppy.load()`.  Holds the entire
    document: geometry, materials, layers, component definitions, cameras,
    scenes, and all model metadata.

    Attributes
    ----------
    header : SkpHeader or None
        Binary file header -- version string, timestamps, UUID.
    document : SkpDocument or None
        ZIP container metadata and raw entry access.
    entities : Entities
        Root-level geometry (vertices, edges, faces, instances, groups, images).
    definitions : list of ComponentDefinition
        All component definitions in the document.
    materials : list of Material
        All materials.
    layers : list of Layer
        All layers (called "Tags" in modern SketchUp).
    layer_folders : list of LayerFolder
        Layer folder hierarchy.
    cameras : list of Camera
        Camera records stored in the file.
    active_layer_id : int or None
        ID of the layer that was active when the file was saved.
    scenes : list of Scene
        Named scenes (pages / saved views).
    background_image : PageBackgroundImage or None
        Default model-level background/match-photo image when present.
    rendering_options : RenderingOptions or None
        Parsed rendering/display options from either container format.
    shadow_info : ShadowInfo or None
        Geo-referenced shadow settings (0x0204).
    watermark_manager : WatermarkManager or None
        Watermark manager (0x0203).
    styles_registry : StylesRegistry or None
        Styles registry (0x0206).
    fonts : list of Font
        Font definitions (0x01FD).
    text_style : TextStyle or None
        Text style settings (0x01FE).
    dimension_style : DimensionStyle or None
        Dimension style settings (0x01FF).
    line_styles : list of LineStyle
        Line style definitions (0x0208).
    options_manager : OptionsManager or None
        Options manager (0x0200).
    environment_data : EnvironmentData or None
        Environment data (0x0210).
    sun_data : SunData or None
        Sun data (0x0213).
    model_view_axes : ModelViewAxes or None
        Sketch axes orientation (0x01FC).
    attribute_dictionaries : list of AttributeDictionary
        Attribute dictionaries (0x0209).
    attribute_dictionaries_by_object_id : dict
        Attribute dictionaries grouped by model-level definition, material, or
        layer ID.
    legacy_archive : object or None
        Parser provenance decoded from a pre-ZIP legacy binary envelope.

    Builder API
    -----------
    Create a new model and populate it programmatically::

        model = Model.new()
        layer = model.add_layer("Walls")
        brick = model.add_material("Brick", color=Color(180, 80, 60))
        defn  = model.add_definition("MyCube")
        face  = defn.entities.add_face([(0,0,0),(100,0,0),(100,100,0),(0,100,0)])
        model.entities.add_instance(defn)
        model.save("output.skp")
    """

    header: Optional["SkpHeader"] = None
    document: Optional["SkpDocument"] = None
    entities: Entities = field(default_factory=Entities)
    definitions: List[ComponentDefinition] = field(default_factory=list)
    materials: List["Material"] = field(default_factory=list)
    layers: List["Layer"] = field(default_factory=list)
    layer_folders: List["LayerFolder"] = field(default_factory=list)
    cameras: List[Camera] = field(default_factory=list)
    active_layer_id: Optional[int] = None  # ID of the currently active layer
    scenes: List["Scene"] = field(default_factory=list)  # named scenes / pages
    background_image: Optional["PageBackgroundImage"] = None
    rendering_options: Optional[RenderingOptions] = None  # 0x01FB rendering/display options
    shadow_info: Optional[ShadowInfo] = None  # 0x0204 geo-referenced shadow settings
    watermark_manager: Optional[WatermarkManager] = None  # 0x0203 watermark manager
    styles_registry: Optional[StylesRegistry] = None  # 0x0206 styles registry
    fonts: List[Font] = field(default_factory=list)  # 0x01FD font definitions
    text_style: Optional[TextStyle] = None  # 0x01FE text style
    dimension_style: Optional[DimensionStyle] = None  # 0x01FF dimension style
    line_styles: List[LineStyle] = field(default_factory=list)  # 0x0208 line styles
    options_manager: Optional[OptionsManager] = None  # 0x0200 options manager
    environment_data: Optional[EnvironmentData] = None  # 0x0210 environment data
    sun_data: Optional[SunData] = None  # 0x0213 sun data
    model_view_axes: Optional[ModelViewAxes] = None  # 0x01FC sketch axes
    attribute_dictionaries: List[AttributeDictionary] = field(default_factory=list)  # 0x0209
    attribute_dictionaries_by_object_id: Dict[int, List[AttributeDictionary]] = field(default_factory=dict)
    legacy_archive: Optional[Any] = None
    _next_id: int = field(default=1, init=False, repr=False, compare=False)

    # - Factory ----------

    @classmethod
    def new(cls) -> "Model":
        """Create an empty Model ready to receive geometry.

        Returns
        -------
        Model
            New model with empty containers and default metadata fields.
        """
        return cls()

    # - ID management ---------

    def _alloc_id(self) -> int:
        """Allocate a model-level entity ID (for layers, materials, definitions).

        Returns
        -------
        int
            A unique integer ID within this Model scope.
        """
        eid = self._next_id
        self._next_id += 1
        return eid

    def _sync_id_counter(self) -> None:
        """
        Synchronise the model-level ID counter after loading from a file.

        Must be called after :func:`parse_model` so that newly added entities
        receive IDs that don't conflict with the loaded ones.
        """
        all_ids = [m.id for m in self.materials] + [lyr.id for lyr in self.layers] + [d.id for d in self.definitions]
        if all_ids:
            self._next_id = max(all_ids) + 1

    # - Layer builders --------

    def add_layer(self, name: str, visible: bool = True) -> "Layer":
        """
        Create a new layer and add it to this model.

        Parameters
        ----------
        name : str
            Display name (called "Tag" in SketchUp 2020+).
        visible : bool, optional
            Initial visibility state.  Defaults to ``True``.

        Returns
        -------
        Layer
        """
        from .layers import Layer

        lyr = Layer(id=self._alloc_id(), name=name, visible=visible)
        self.layers.append(lyr)
        return lyr

    def get_layer(self, name: str) -> Optional["Layer"]:
        """
        Return the first layer whose name matches, or ``None``.

        Parameters
        ----------
        name : str
            Layer name to search for.

        Returns
        -------
        Layer or None
        """
        return next((lyr for lyr in self.layers if lyr.name == name), None)

    # - Material builders --------

    def add_material(
        self,
        name: str,
        color: Optional["Color"] = None,
        alpha: float = 1.0,
        metallic: float = 0.0,
        roughness: float = 1.0,
    ) -> "Material":
        """
        Create a new material and add it to this model.

        Parameters
        ----------
        name : str
            Unique display name.
        color : Color, optional
            Base diffuse colour.  Defaults to white ``(255, 255, 255)``.
        alpha : float, optional
            Opacity: 0.0 = fully transparent, 1.0 = fully opaque.
        metallic : float, optional
            PBR metallic factor (0.0 to 1.0).
        roughness : float, optional
            PBR roughness factor (0.0 to 1.0).

        Returns
        -------
        Material
        """
        from .materials import Color, Material

        if color is None:
            color = Color(r=255, g=255, b=255)
        mat = Material(
            id=self._alloc_id(),
            name=name,
            color=color,
            alpha=alpha,
            metallic=metallic,
            roughness=roughness,
        )
        self.materials.append(mat)
        return mat

    def get_material(self, name: str) -> Optional["Material"]:
        """
        Return the first material whose name matches, or ``None``.

        Parameters
        ----------
        name : str
            Material name to search for.

        Returns
        -------
        Material or None
        """
        return next((m for m in self.materials if m.name == name), None)

    # - Definition builders --------

    def add_definition(
        self,
        name: str,
        description: str = "",
    ) -> ComponentDefinition:
        """
        Create a new component definition with empty geometry and add it to the
        model.

        After calling this method, populate the definition's geometry via
        ``defn.entities.add_face(...)`` and then place instances with
        ``model.entities.add_instance(defn, ...)``.  Alternatively use
        :meth:`add_group` for a single-use inline group.

        Parameters
        ----------
        name : str
            Display name for the definition (shown in the Components panel).
        description : str, optional
            Optional description text.

        Returns
        -------
        ComponentDefinition
        """
        defn = ComponentDefinition(
            id=self._alloc_id(),
            guid=_uuid.uuid4().bytes,
            name=name,
            description=description,
            entities=Entities(),
        )
        self.definitions.append(defn)
        return defn

    def get_definition(self, name: str) -> Optional[ComponentDefinition]:
        """
        Return the first component definition whose name matches, or ``None``.

        Parameters
        ----------
        name : str
            Definition name to search for.

        Returns
        -------
        ComponentDefinition or None
        """
        return next((d for d in self.definitions if d.name == name), None)

    def add_group(
        self,
        name: Optional[str] = None,
        transform: Optional[Transform] = None,
    ) -> tuple[ComponentDefinition, Group]:
        """
        Create a named group (an immediately-placed anonymous definition).

        A new :class:`ComponentDefinition` is created and a :class:`Group`
        instance is placed in ``self.entities.groups`` at the given transform.

        Parameters
        ----------
        name : str, optional
            Display name.  Defaults to ``"Group#N"`` where N is the current
            definition count.
        transform : Transform, optional
            Placement transform.  Defaults to the identity transform.

        Returns
        -------
        tuple of (ComponentDefinition, Group)
            Add geometry to ``defn.entities``; the group is already registered
            in ``self.entities.groups``.
        """
        defn = self.add_definition(name or f"Group#{len(self.definitions)}")
        # Modern files classify group-owned definitions separately from reusable
        # component definitions. The instance record alone is not sufficient for
        # the SDK to expose it through the group-definition collection.
        defn.definition_type = 1
        xform = (transform or Transform.identity()).to_list()
        grp = Group(
            id=self.entities._alloc_id(),
            guid=_uuid.uuid4().bytes,
            name=name,
            definition_id=defn.id,
            transform=xform,
        )
        self.entities.groups.append(grp)
        return defn, grp

    # - Persistence ---------

    def save(
        self,
        filepath: str | Path,
        *,
        header: Optional["SkpHeader"] = None,
        format: Literal["modern", "sketchup_2017"] = "modern",
    ) -> Path:
        """
        Write this model to a SketchUp .skp file.

        Parameters
        ----------
        filepath : str or pathlib.Path
            Destination file path.
        header : SkpHeader or None, optional
            Explicit modern VFF header.
        format : {"modern", "sketchup_2017"}, optional
            Output container format.

        Returns
        -------
        pathlib.Path
            Destination path after serialization.
        """
        from .. import save as _save

        return _save(
            self,
            filepath,
            header=header,
            format=format,
        )

    def dump_zip(self, output_dir: str) -> Path:
        """Extract the ZIP contents of the loaded .skp file to *output_dir*.

        Parameters
        ----------
        output_dir : str
            Destination directory for the extracted files.

        Raises
        ------
        RuntimeError
            If the model was not loaded from a .skp file (i.e. created
            programmatically with :meth:`new`).

        See Also
        --------
        SkpDocument.dump_zip : Underlying implementation.
        """
        if self.document is None:
            raise RuntimeError("dump_zip() is only available on models loaded from a .skp file.")
        return self.document.dump_zip(output_dir)

    # - Scene export ---------

    def to_scene(self) -> "SceneNode":
        """
        Convert this Model into a
        :class:`~skppy.data_structure.scene.SceneNode` tree ready for any
        importer or exporter.

        The returned tree has the following structure::

            SceneNode("Scene")           <- root, identity transform, no mesh
            +-- SceneNode("RootGeometry") <- root-level faces (if any)
            +-- SceneNode(inst.name)      <- one per root instance / group
                +-- mesh                  <- pre-computed PreparedMesh
                +-- children             <- nested instances / groups

        All spatial coordinates are in **SketchUp inches** (definition-local).
        Transforms are the 13-float row-major ``SUTransformation`` as stored
        in the TLV (identity transform for the root and RootGeometry nodes).

        Returns
        -------
        SceneNode
            Root of the scene hierarchy.
        """
        from .scene_graph import build_scene_graph

        return build_scene_graph(self)
