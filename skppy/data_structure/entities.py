# SPDX-License-Identifier: MIT
"""Geometry, topology, components, and scoped entity builder methods.

An :class:`Entities` object owns one independent ID scope. The model root and
every :class:`ComponentDefinition` therefore have separate vertex, edge, face,
annotation, and placement collections. Faces reference loops, loops reference
directed edge uses, and edges reference vertices by ID.

Use the builder methods when creating geometry; they allocate consistent IDs
and construct the required topology.

Example
-------
::

    import skppy

    model = skppy.new_model()
    floor = model.entities.add_face(
        [(0, 0, 0), (120, 0, 0), (120, 96, 0), (0, 96, 0)]
    )
    print(floor.id, len(model.entities.edges))  # one boundary edge per corner
"""

from __future__ import annotations

import math
import uuid as _uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .construction import GuideLine, GuidePoint, SectionPlane
from .images import normalize_texture_scale
from .primitives import Transform, Vector2D, Vector3D

if TYPE_CHECKING:
    from .annotations import LinearDimension, RadialDimension, Text
    from .materials import Material
    from .model_metadata import AttributeDictionary, EntityRelationship
    from .scene import PreparedMesh

EDGE_FLAG_HIDDEN = 0x01
EDGE_FLAG_SOFT = 0x02
EDGE_FLAG_SMOOTH = 0x04


@dataclass(slots=True)
class Vertex:
    """A 3-D point in an Entities scope (SUVertex).

    Vertices are the lowest-level geometry primitive.  Edges and faces
    reference vertices by their integer *id*.

    Attributes
    ----------
    id : int
        Unique vertex ID within the Entities scope.
    position : Vector3D
        Position in SketchUp inches.
    """

    id: int
    position: Vector3D


@dataclass(slots=True)
class EdgeUse:
    """One directed edge reference within a face loop (SUEdgeUse).

    An edge use records not just which edge is part of a loop, but also
    the traversal direction.  When *reversed* is ``True`` the edge is
    traversed from its end vertex toward its start vertex.

    Attributes
    ----------
    edge_id : int
        ID of the referenced :class:`Edge`.
    reversed : bool
        ``True`` if the edge direction is opposite to the loop winding.
    """

    edge_id: int
    reversed: bool


@dataclass(slots=True)
class Loop:
    """An ordered, closed sequence of edge uses (SULoop).

    A loop defines the boundary of a face.  The outer loop winds
    counter-clockwise when viewed from the front face normal; inner loops
    (holes) wind clockwise.

    Attributes
    ----------
    edge_uses : list of EdgeUse
        Ordered edge references that form the closed loop.
    is_outer : bool
        Whether SketchUp marks this as the face's outer boundary.
    is_convex : bool or None
        Legacy convexity cache. ``None`` when the source format omits it.
    """

    edge_uses: List[EdgeUse] = field(default_factory=list)
    is_outer: bool = False
    is_convex: Optional[bool] = None

    def vertex_ids(self, edge_map: Dict[int, Tuple[int, int]]) -> List[int]:
        """
        Resolve edge uses to an ordered list of vertex IDs.

        Parameters
        ----------
        edge_map : dict
            Mapping of ``edge_id -> (start_vertex_id, end_vertex_id)``.

        Returns
        -------
        list of int
            Vertex IDs in loop traversal order.  Edges missing from
            *edge_map* are silently skipped.
        """
        vids: List[int] = []
        for eu in self.edge_uses:
            edge = edge_map.get(eu.edge_id)
            if edge is None:
                continue
            start_vid, end_vid = edge
            vids.append(end_vid if eu.reversed else start_vid)
        return vids


@dataclass(slots=True)
class Edge:
    """A line segment between two vertices (SUEdge).

    Attributes
    ----------
    id : int
        Unique edge ID within the Entities scope.
    start_vertex_id : int
        ID of the start vertex.
    end_vertex_id : int
        ID of the end vertex.
    flags : int
        Bitmask of edge flags (e.g. smooth, soft, hidden).
    curve_id : int or None
        ID of the parent :class:`Curve` if this edge belongs to a
        polyline, otherwise ``None``.
    layer_id : int or None
        Owning layer/tag ID.
    """

    id: int
    start_vertex_id: int
    end_vertex_id: int
    flags: int = 0
    curve_id: Optional[int] = None
    layer_id: Optional[int] = None

    @property
    def is_hidden(self) -> bool:
        """Return True when SketchUp marks this edge hidden.

        Returns
        -------
        bool
            ``True`` when the hidden bit is set.
        """
        return bool(self.flags & EDGE_FLAG_HIDDEN)

    @property
    def is_soft(self) -> bool:
        """Return True when SketchUp marks this edge soft.

        Returns
        -------
        bool
            ``True`` when the soft bit is set.
        """
        return bool(self.flags & EDGE_FLAG_SOFT)

    @property
    def is_smooth(self) -> bool:
        """Return True when SketchUp marks this edge smooth.

        Returns
        -------
        bool
            ``True`` when the smooth bit is set.
        """
        return bool(self.flags & EDGE_FLAG_SMOOTH)


@dataclass(slots=True)
class UVPin:
    """Exact texture control point stored for a face projection.

    ``texture_position`` is in raw texture-space inches and
    ``model_position`` is the corresponding point in the face's projected 2-D
    coordinate system. The physical texture scale converts the former to the
    normalized UV coordinates used by renderers.
    """

    texture_position: Vector2D = field(default_factory=lambda: Vector2D(0.0, 0.0))
    model_position: Vector2D = field(default_factory=lambda: Vector2D(0.0, 0.0))


@dataclass(slots=True)
class FaceUVProjection:
    """
    Per-face texture projection transform parsed from the SKP TLV (tag 0x2715).

    ``transform`` is a 3x3 row-major affine matrix stored as 9 ``float64``
    values.  In observed modern files it maps raw texture-space coordinates to
    projected face coordinates using row-vector convention::

        [sx sy 1] = [u_raw v_raw 1] * transform

    ``compute_uv()`` inverts this matrix, projects the 3-D vertex to the face's
    2-D coordinate pair, then divides by the material texture scale.

    ``origin`` (tag 0x2716) is retained for inspection. Legacy projected
    textures additionally expose their projection vector through
    ``projection_direction``; modern files observed so far do not need it.

    See ``docs/format/uv_projection.md`` for details.

    Attributes
    ----------
    transform : list of float
        Nine doubles storing a row-major 3x3 affine UV matrix.
    origin : tuple of float
        Raw projection origin retained for diagnostics.
    projection_direction : tuple of float or None
        Legacy projection direction. When present, it defines the 2-D basis
        used before applying the texture matrix instead of the face normal.
    pins : list of UVPin
        Exact texture coordinates for control points manipulated with the
        texture-positioning tool.
    """

    transform: List[float] = field(default_factory=lambda: [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0])
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    projection_direction: Optional[Tuple[float, float, float]] = None
    pins: List[UVPin] = field(default_factory=list)
    _inverse_source: Optional[Tuple[float, ...]] = field(default=None, init=False, repr=False)
    _inverse_transform: Optional[np.ndarray] = field(default=None, init=False, repr=False)

    def inverse_transform(self) -> Optional[np.ndarray]:
        """Return the cached inverse of SketchUp's UV affine matrix.

        Returns
        -------
        numpy.ndarray or None
            Inverse 3x3 matrix, or ``None`` when the transform is singular.
        """
        source = tuple(float(value) for value in self.transform[:9])
        if self._inverse_source != source:
            self._inverse_transform = _invert_3x3(self.transform)
            self._inverse_source = source
        return self._inverse_transform

    def is_singular(self) -> bool:
        """Return whether the stored UV transform cannot be inverted.

        Returns
        -------
        bool
            ``True`` when the transform has no stable inverse.
        """
        return self.inverse_transform() is None

    def compute_uv(
        self,
        px: float,
        py: float,
        pz: float,
        x_scale: float,
        y_scale: float,
        normal: Optional[Tuple[float, float, float]] = None,
    ) -> Tuple[float, float]:
        """
        Compute ``(u, v)`` for a vertex at local position ``(px, py, pz)``.

        Parameters
        ----------
        px, py, pz
            Vertex position in **SketchUp inches**, definition-local space.
            Do **not** apply any world/instance transform before calling this.
        x_scale
            Texture width in inches  (``material.texture.width  / 0.0254``).
        y_scale
            Texture height in inches (``material.texture.height / 0.0254``).
        normal
            Optional face normal used to project the vertex into SketchUp's
            2-D face-local basis before applying the texture transform.

        Returns
        -------
        tuple[float, float]
            ``(u, v)`` texture coordinates.
        """
        return self.compute_uvs([(px, py, pz)], x_scale, y_scale, normal)[0]

    def compute_uvs(
        self,
        positions: List[Tuple[float, float, float]],
        x_scale: float,
        y_scale: float,
        normal: Optional[Tuple[float, float, float]] = None,
    ) -> List[Tuple[float, float]]:
        """
        Compute UV coordinates for multiple local SKP-inch positions.

        This is the preferred path for importers because it inverts the stored
        affine matrix once and projects all corners with NumPy in one batch.

        Parameters
        ----------
        positions : list of tuple of float
            Vertex positions in definition-local SketchUp inches.
        x_scale : float
            Texture width in SketchUp inches.
        y_scale : float
            Texture height in SketchUp inches.
        normal : tuple of float, optional
            Face normal used for orientation-aware projection.

        Returns
        -------
        list of tuple of float
            UV coordinates matching *positions* order.
        """
        if not positions:
            return []

        inv = self.inverse_transform()
        if inv is None:
            return [(0.0, 0.0)] * len(positions)

        basis_normal = self.projection_direction or normal
        projected = _project_points_for_uv(positions, basis_normal)
        coords = np.column_stack((projected, np.ones(len(projected))))
        raw = coords @ inv
        # Projected textures use a projective 3x3 transform. SketchUp's
        # SUUVHelper returns UVQ and divides U/V by Q; affine mappings simply
        # have Q=1, so the same path is valid for both forms.
        q = raw[:, 2]
        valid_q = np.abs(q) >= 1e-12
        uv = np.zeros((len(raw), 2), dtype=float)
        uv[valid_q] = raw[valid_q, :2] / q[valid_q, None]

        # The projection matrix interpolates the face mapping, but explicitly
        # positioned control points carry the authoritative corner UV. Match
        # them in the same 2-D face basis used by the matrix so small binary
        # round-off does not prevent an exact override.
        if self.pins:
            pin_positions = np.array(
                [[pin.model_position.x, pin.model_position.y] for pin in self.pins],
                dtype=float,
            )
            pin_uvs = np.array(
                [[pin.texture_position.x, pin.texture_position.y] for pin in self.pins],
                dtype=float,
            )
            distances = np.sum(
                (projected[:, None, :] - pin_positions[None, :, :]) ** 2,
                axis=2,
            )
            nearest = np.argmin(distances, axis=1)
            nearest_positions = pin_positions[nearest]
            matches = np.all(
                np.isclose(
                    projected,
                    nearest_positions,
                    rtol=1e-9,
                    atol=1e-7,
                ),
                axis=1,
            )
            uv[matches] = pin_uvs[nearest[matches]]
        uv /= np.array(
            [normalize_texture_scale(x_scale), normalize_texture_scale(y_scale)],
            dtype=float,
        )
        return [(float(u), float(v)) for u, v in uv]


def _invert_3x3(values: List[float]) -> Optional[np.ndarray]:
    """Return the inverse of a row-major 3x3 matrix, or None if singular."""
    if len(values) < 9:
        return None

    matrix = np.asarray(values[:9], dtype=float).reshape((3, 3))
    if not np.isfinite(matrix).all():
        return None
    try:
        det = float(np.linalg.det(matrix))
    except np.linalg.LinAlgError:
        return None
    if abs(det) < 1e-12:
        return None
    try:
        return np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return None


def _project_points_for_uv(
    positions: List[Tuple[float, float, float]],
    normal: Optional[Tuple[float, float, float]],
) -> np.ndarray:
    """Project 3-D points to 2-D coordinate pairs used by SKP UV matrices."""
    points = np.asarray(positions, dtype=float)
    if normal is None:
        return points[:, :2]

    nx, ny, nz = normal
    tangent_x = -ny
    tangent_y = nx
    tangent_len = math.sqrt(tangent_x * tangent_x + tangent_y * tangent_y)
    if tangent_len < 1e-12:
        return points[:, :2]

    tangent_x /= tangent_len
    tangent_y /= tangent_len
    tangent = np.array([tangent_x, tangent_y, 0.0], dtype=float)
    bitangent = np.array(
        [
            -nz * tangent_y,
            nz * tangent_x,
            nx * tangent_y - ny * tangent_x,
        ],
        dtype=float,
    )

    return np.column_stack((points @ tangent, points @ bitangent))


@dataclass(slots=True)
class Face:
    """A planar polygon with an outer loop and optional inner loops (SUFace).

    Attributes
    ----------
    id : int
        Unique face ID within the Entities scope.
    plane : tuple
        Plane equation ``(a, b, c, d)``.
    outer_loop : Loop
        Boundary loop for the face exterior.
    inner_loops : list of Loop
        Hole loops, if any.
    front_material_id, back_material_id : int or None
        Material IDs assigned to each side.
    front_uv, back_uv : FaceUVProjection or None
        Per-side texture projection data.
    layer_id : int or None
        Owning layer/tag ID.
    """

    id: int
    plane: Tuple[float, float, float, float]
    outer_loop: Loop
    inner_loops: List[Loop]
    front_material_id: Optional[int] = None
    back_material_id: Optional[int] = None
    front_uv: Optional[FaceUVProjection] = None
    back_uv: Optional[FaceUVProjection] = None
    layer_id: Optional[int] = None

    def resolve_material_mapping(
        self,
        inherited_material_id: Optional[int] = None,
    ) -> Tuple[Optional[int], Optional[FaceUVProjection]]:
        """Resolve the single material and UV mapping used by mesh consumers.

        A SketchUp face can have independent front and back appearances, while
        common polygon meshes expose one material and UV set. The shared policy
        is front-first: an explicit front material wins, an explicit back
        material is used only when the front is unpainted, and an inherited
        material is used only when neither side is painted.

        A projection from the opposite side is reusable only when both sides
        reference the same material. Inherited materials may use either stored
        projection because neither face side owns an explicit material.

        Parameters
        ----------
        inherited_material_id : int, optional
            Material supplied by a containing instance or group.

        Returns
        -------
        tuple
            Effective material ID and applicable UV projection.
        """
        if self.front_material_id is not None:
            projection = self.front_uv
            if projection is None and self.back_material_id == self.front_material_id:
                projection = self.back_uv
            return self.front_material_id, projection

        if self.back_material_id is not None:
            return self.back_material_id, self.back_uv

        if inherited_material_id is not None:
            return inherited_material_id, self.front_uv or self.back_uv

        return None, None

    def triangulate(self, entities: "Entities") -> List[Tuple[int, int, int]]:
        """Fan-triangulate the outer loop.

        Parameters
        ----------
        entities : Entities
            The parent entities container (used to resolve edge->vertex
            mappings).

        Returns
        -------
        list of (int, int, int)
            List of vertex-ID triples forming triangles.

        Notes
        -----
        This is a simple fan triangulation from the first vertex.  Inner
        loops (holes) are **not** handled -- use
        :func:`skppy.triangulation.triangulate_face_3d` for proper
        ear-clipping with hole support.
        """
        edge_map: Dict[int, Tuple[int, int]] = {e.id: (e.start_vertex_id, e.end_vertex_id) for e in entities.edges}
        vids = self.outer_loop.vertex_ids(edge_map)
        if len(vids) < 3:
            return []
        v0 = vids[0]
        return [(v0, vids[i], vids[i + 1]) for i in range(1, len(vids) - 1)]

    def normal(self) -> Vector3D:
        """Return the face normal.

        Returns
        -------
        Vector3D
            The ``(a, b, c)`` component of the face plane.
        """
        return Vector3D(self.plane[0], self.plane[1], self.plane[2])


# -
# Instances / groups / images (reference a ComponentDefinition by ID)
# -


@dataclass(slots=True)
class ComponentInstance:
    """An instance of a ComponentDefinition (SUComponentInstance).

    Attributes
    ----------
    id : int
        Unique instance ID within the Entities scope.
    guid : bytes
        16-byte GUID that identifies this instance across save/load cycles.
    name : str or None
        Optional instance name.
    definition_id : int
        ID of the :class:`ComponentDefinition` this instance references.
    transform : list of float
        13-float SUTransformation (row-major 4x4 with perspective omitted).
    material_id : int or None
        Override material applied to all un-materialed faces in the
        definition, or ``None``.
    layer_id : int or None
        Owning layer/tag ID.
    """

    id: int = 0
    guid: bytes = b"\x00" * 16
    name: Optional[str] = None
    definition_id: int = 0
    transform: List[float] = field(default_factory=lambda: Transform.identity().to_list())
    material_id: Optional[int] = None  # override material inherited by un-materialed faces
    layer_id: Optional[int] = None


@dataclass(slots=True)
class Group:
    """A group, which is a special single-use ComponentInstance (SUGroup).

    Groups are internally represented as a component definition with a
    single instance, but are semantically distinct in SketchUp.

    Attributes
    ----------
    id : int
        Unique group ID within the Entities scope.
    guid : bytes
        16-byte GUID.
    name : str or None
        Optional group name.
    definition_id : int
        ID of the internal :class:`ComponentDefinition`.
    transform : list of float
        13-float SUTransformation.
    material_id : int or None
        Override material, or ``None``.
    layer_id : int or None
        Owning layer/tag ID.
    """

    id: int = 0
    guid: bytes = b"\x00" * 16
    name: Optional[str] = None
    definition_id: int = 0
    transform: List[float] = field(default_factory=lambda: Transform.identity().to_list())
    material_id: Optional[int] = None
    layer_id: Optional[int] = None


@dataclass(slots=True)
class Image:
    """An image entity placed in 3-D space (SUImage).

    Images are standalone raster images placed in the model at a specific
    position and orientation.

    Attributes
    ----------
    id : int
        Unique image ID within the Entities scope.
    guid : bytes
        16-byte GUID.
    name : str or None
        Optional image name.
    definition_id : int
        ID of the internal :class:`ComponentDefinition`.
    transform : list of float
        13-float SUTransformation.
    material_id : int or None
        Override material, or ``None``.
    layer_id : int or None
        Owning layer/tag ID.
    """

    id: int = 0
    guid: bytes = b"\x00" * 16
    name: Optional[str] = None
    definition_id: int = 0
    transform: List[float] = field(default_factory=lambda: Transform.identity().to_list())
    material_id: Optional[int] = None
    layer_id: Optional[int] = None


# -
# Entities container
# -


@dataclass
class Entities:
    """
    Container for all geometry in a scope (root model or component definition).

    Builder API
    -----------
    Create vertices, edges, and faces programmatically::

        ents = Entities()
        face = ents.add_face([(0,0,0),(100,0,0),(100,100,0),(0,100,0)])

    Attributes
    ----------
    vertices, edges, faces : list
        Raw geometric primitives in this scope.
    component_instances, groups, images : list
        Entity references to component definitions.
    curves, arc_curves : list
        Edge grouping metadata.
    guide_points, guide_lines, section_planes : list
        Construction and section entities.
    texts, linear_dimensions, radial_dimensions : list
        Shared annotation entities, independent of the source SKP container.
    relationships : list of EntityRelationship
        Directed references between entities in this scope.
    attribute_dictionaries_by_entity_id : dict
        Attribute dictionaries grouped by their owning entity ID.
    """

    vertices: List[Vertex] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    faces: List[Face] = field(default_factory=list)
    component_instances: List[ComponentInstance] = field(default_factory=list)
    groups: List[Group] = field(default_factory=list)
    images: List[Image] = field(default_factory=list)
    curves: List[Curve] = field(default_factory=list)
    arc_curves: List[ArcCurve] = field(default_factory=list)
    guide_points: List[GuidePoint] = field(default_factory=list)
    guide_lines: List[GuideLine] = field(default_factory=list)
    section_planes: List[SectionPlane] = field(default_factory=list)
    texts: List["Text"] = field(default_factory=list)
    linear_dimensions: List["LinearDimension"] = field(default_factory=list)
    radial_dimensions: List["RadialDimension"] = field(default_factory=list)
    relationships: List["EntityRelationship"] = field(default_factory=list)
    attribute_dictionaries_by_entity_id: Dict[int, List["AttributeDictionary"]] = field(default_factory=dict)
    _next_id: int = field(default=1, init=False, repr=False, compare=False)

    # - ID management ---------

    def _alloc_id(self) -> int:
        """Allocate and return the next entity ID.

        Returns
        -------
        int
            A unique integer ID within this Entities scope.
        """
        eid = self._next_id
        self._next_id += 1
        return eid

    def _sync_id_counter(self) -> None:
        """Reset the ID counter to max(all entity IDs) + 1 after loading."""
        all_ids = (
            [v.id for v in self.vertices]
            + [e.id for e in self.edges]
            + [f.id for f in self.faces]
            + [c.id for c in self.component_instances]
            + [g.id for g in self.groups]
            + [i.id for i in self.images]
            + [c.id for c in self.curves]
            + [a.id for a in self.arc_curves]
            + [p.id for p in self.guide_points]
            + [line.id for line in self.guide_lines]
            + [plane.id for plane in self.section_planes]
            + [text.id for text in self.texts]
            + [dimension.id for dimension in self.linear_dimensions]
            + [dimension.id for dimension in self.radial_dimensions]
        )
        if all_ids:
            self._next_id = max(all_ids) + 1

    # - Builder methods ---------

    def add_vertex(self, x: float, y: float, z: float) -> Vertex:
        """
        Create a new vertex at the given position and add it to this container.

        Parameters
        ----------
        x, y, z : float
            Position in SketchUp inches.

        Returns
        -------
        Vertex
            The newly created vertex.
        """
        v = Vertex(id=self._alloc_id(), position=Vector3D(x, y, z))
        self.vertices.append(v)
        return v

    def add_edge(
        self,
        v1: Union["Vertex", int],
        v2: Union["Vertex", int],
    ) -> Edge:
        """
        Create an edge between two vertices and add it to this container.

        Parameters
        ----------
        v1 : Vertex or int
            First vertex (or its ID).
        v2 : Vertex or int
            Second vertex (or its ID).

        Returns
        -------
        Edge
            The newly created edge.
        """
        start_id = v1.id if isinstance(v1, Vertex) else v1
        end_id = v2.id if isinstance(v2, Vertex) else v2
        e = Edge(id=self._alloc_id(), start_vertex_id=start_id, end_vertex_id=end_id)
        self.edges.append(e)
        return e

    def add_arc_curve(
        self,
        center: _PointLike,
        normal: _PointLike,
        radius: float,
        start_angle: float,
        end_angle: float,
        segments: int,
    ) -> ArcCurve:
        """Create a segmented circular arc and its owning arc-curve entity.

        Angles are expressed in radians in the arc plane. A span of
        ``2 * pi`` creates a full circle with a duplicated closing vertex,
        matching SketchUp's public API representation.
        """
        if segments < 1:
            raise ValueError("An arc curve requires at least one segment.")
        if not math.isfinite(radius) or radius <= 0.0:
            raise ValueError("An arc curve requires a positive finite radius.")
        if not all(math.isfinite(value) for value in (start_angle, end_angle)):
            raise ValueError("Arc curve angles must be finite.")
        if end_angle <= start_angle:
            raise ValueError("Arc curve end angle must follow its start angle.")

        center_values = _point_values(center)
        normal_values = _point_values(normal)
        normal_length = math.sqrt(sum(value * value for value in normal_values))
        if normal_length < 1.0e-12:
            raise ValueError("Arc curve normal must be non-zero.")
        unit_normal = tuple(value / normal_length for value in normal_values)
        nx, ny, nz = unit_normal
        if abs(nz) > 0.999999:
            x_axis = (1.0, 0.0, 0.0)
        else:
            tangent_length = math.sqrt(nx * nx + ny * ny)
            x_axis = (-ny / tangent_length, nx / tangent_length, 0.0)
        y_axis = (
            ny * x_axis[2] - nz * x_axis[1],
            nz * x_axis[0] - nx * x_axis[2],
            nx * x_axis[1] - ny * x_axis[0],
        )

        vertices = []
        for index in range(segments + 1):
            angle = start_angle + (end_angle - start_angle) * index / segments
            cosine = math.cos(angle)
            sine = math.sin(angle)
            vertices.append(
                self.add_vertex(
                    center_values[0] + radius * (x_axis[0] * cosine + y_axis[0] * sine),
                    center_values[1] + radius * (x_axis[1] * cosine + y_axis[1] * sine),
                    center_values[2] + radius * (x_axis[2] * cosine + y_axis[2] * sine),
                )
            )
        edges = [self.add_edge(vertices[index], vertices[index + 1]) for index in range(segments)]
        arc = ArcCurve(
            id=self._alloc_id(),
            edge_ids=[edge.id for edge in edges],
            center=center_values,
            normal=(unit_normal[0], unit_normal[1], unit_normal[2]),
            radius=radius,
            start_angle=start_angle,
            end_angle=end_angle,
        )
        for edge in edges:
            edge.curve_id = arc.id
        self.arc_curves.append(arc)
        return arc

    def add_arc_curve_from_edges(
        self,
        edge_ids: Sequence[int],
        center: _PointLike,
        normal: _PointLike,
        radius: float,
        start_angle: float,
        end_angle: float,
    ) -> ArcCurve:
        """Group existing segmented edges into a circular arc.

        This is useful when an arc boundary is shared with faces, such as the
        four circular seams of a hollow cylinder.
        """
        if not edge_ids:
            raise ValueError("An arc curve requires at least one edge.")
        edges_by_id = {edge.id: edge for edge in self.edges}
        if any(edge_id not in edges_by_id for edge_id in edge_ids):
            raise ValueError("An arc curve references an edge outside this scope.")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("An arc curve cannot contain duplicate edges.")
        owned = [edge_id for edge_id in edge_ids if edges_by_id[edge_id].curve_id]
        if owned:
            raise ValueError(f"Edge {owned[0]} already belongs to a curve.")
        if not math.isfinite(radius) or radius <= 0.0:
            raise ValueError("An arc curve requires a positive finite radius.")
        if not all(math.isfinite(value) for value in (start_angle, end_angle)):
            raise ValueError("Arc curve angles must be finite.")
        if end_angle <= start_angle:
            raise ValueError("Arc curve end angle must follow its start angle.")
        center_values = _point_values(center)
        normal_values = _point_values(normal)
        normal_length = math.sqrt(sum(value * value for value in normal_values))
        if normal_length < 1.0e-12:
            raise ValueError("Arc curve normal must be non-zero.")
        arc = ArcCurve(
            id=self._alloc_id(),
            edge_ids=list(edge_ids),
            center=center_values,
            normal=(
                normal_values[0] / normal_length,
                normal_values[1] / normal_length,
                normal_values[2] / normal_length,
            ),
            radius=float(radius),
            start_angle=float(start_angle),
            end_angle=float(end_angle),
        )
        for edge_id in edge_ids:
            edge = edges_by_id[edge_id]
            edge.curve_id = arc.id
        self.arc_curves.append(arc)
        return arc

    def add_face(
        self,
        points: Sequence["_PointLike"],
        material_id: Optional[int] = None,
        back_material_id: Optional[int] = None,
    ) -> Face:
        """
        Create a polygon face from an ordered list of corner points.

        Vertices and edges are created automatically for each corner.  Points
        may be :class:`Vertex` objects, :class:`Vector3D` objects, or plain
        ``(x, y, z)`` tuples.  The face normal is computed using Newell's
        method, and a plane equation is stored on the face.

        Parameters
        ----------
        points : list
            Ordered corner positions (minimum 3).  Counter-clockwise winding
            when viewed from the front (outward normal) is the SketchUp
            convention.
        material_id : int, optional
            ID of the front-face material.
        back_material_id : int, optional
            ID of the back-face material.

        Returns
        -------
        Face
            The newly created face.

        Raises
        ------
        ValueError
            If fewer than three points are supplied.
        """
        if len(points) < 3:
            raise ValueError("A face requires at least 3 points.")

        # Normalise input to Vertex objects
        verts: List[Vertex] = []
        for p in points:
            if isinstance(p, Vertex):
                verts.append(p)
            elif isinstance(p, Vector3D):
                verts.append(self.add_vertex(p.x, p.y, p.z))
            else:
                verts.append(self.add_vertex(float(p[0]), float(p[1]), float(p[2])))

        # Create edges (wrapping around)
        n = len(verts)
        edges = [self.add_edge(verts[i], verts[(i + 1) % n]) for i in range(n)]

        # Build outer loop (forward direction for each edge)
        outer_loop = Loop(edge_uses=[EdgeUse(edge_id=e.id, reversed=False) for e in edges])

        # Compute face plane using Newell's method
        positions = [v.position for v in verts]
        plane = _compute_plane(positions)

        face = Face(
            id=self._alloc_id(),
            plane=plane,
            outer_loop=outer_loop,
            inner_loops=[],
            front_material_id=material_id,
            back_material_id=back_material_id,
        )
        self.faces.append(face)
        return face

    def add_instance(
        self,
        definition: "ComponentDefinition",
        transform: Optional[Transform] = None,
        name: Optional[str] = None,
    ) -> ComponentInstance:
        """
        Place a component definition into this scope as a component instance.

        Parameters
        ----------
        definition : ComponentDefinition
            The definition to instantiate.
        transform : Transform, optional
            Placement transform (position, rotation, scale).  Defaults to
            the identity transform.
        name : str, optional
            Display name for this instance.

        Returns
        -------
        ComponentInstance
        """
        xform = (transform or Transform.identity()).to_list()
        inst = ComponentInstance(
            id=self._alloc_id(),
            guid=_uuid.uuid4().bytes,
            name=name,
            definition_id=definition.id,
            transform=xform,
        )
        self.component_instances.append(inst)
        return inst

    # - Mesh preparation --------

    def prepare_mesh(
        self,
        name: str,
        material_lookup: Dict[int, "Material"],  # mat_id -> Material
        inherited_material_id: Optional[int] = None,
        split_holes_to_ngons: bool = False,
    ) -> "PreparedMesh":
        """
        Build a :class:`~skppy.data_structure.scene.PreparedMesh` from this
        entities scope.

        All geometry is resolved to plain Python tuples so the caller does not
        need to know about the SKP TLV format.  Positions are in SketchUp
        inches (definition-local space; no world transform is applied here).

        Parameters
        ----------
        name : str
            Display name for the resulting mesh (e.g. the definition name, or
            ``"RootGeometry"`` for root-level geometry).
        material_lookup : dict
            Mapping from material ID (int) to a
            :class:`~skppy.data_structure.materials.Material` object.  Used to
            resolve material names and texture tile dimensions for UV
            computation.
        inherited_material_id : int, optional
            Effective material from a parent instance or group override,
            applied to faces that have no front or back material set.
        split_holes_to_ngons : bool, optional
            When True, faces with exactly one inner loop are represented as two
            simple n-gons joined by generated bridge edges.  Faces with
            multiple holes still fall back to triangulation.

        Returns
        -------
        PreparedMesh
            All faces from this scope resolved and ready for import.
        """
        from .mesh_preparation import prepare_entities_mesh

        return prepare_entities_mesh(
            self,
            name,
            material_lookup,
            inherited_material_id,
            split_holes_to_ngons,
        )


@dataclass(slots=True)
class Curve:
    """A polyline curve grouping a sequence of edges (SUCurve).

    Curves are stored as a contiguous range of edge IDs.  When
    *is_polygon* is ``True`` the edges form a closed polygon.

    Attributes
    ----------
    id : int
        Unique curve ID.
    edge_ids : list of int
        Ordered list of edge IDs that form the polyline.
    is_polygon : bool
        ``True`` when the edges form a closed polygon.
    """

    id: int = 0
    edge_ids: List[int] = field(default_factory=list)
    is_polygon: bool = False


@dataclass(slots=True)
class ArcCurve:
    """An arc-curve entity grouping a circular arc sequence of edges (SUArcCurve).

    Arc curves represent circular arcs (including full circles). Legacy files
    expose mapped geometric parameters when their schema is known. The modern
    parser currently preserves its unresolved arc-specific payload verbatim and
    leaves those optional parameters absent.

    Attributes
    ----------
    id : int
        Unique arc-curve ID.
    edge_ids : list of int
        Ordered list of edge IDs approximating the arc.
    center : tuple of float or None
        3-D center position ``(x, y, z)`` in SketchUp inches.
    normal : tuple of float or None
        Axis normal unit vector.
    radius : float or None
        Arc radius in SketchUp inches.
    start_angle : float or None
        Start angle in radians.
    end_angle : float or None
        End angle in radians.
    raw_arc_payload : bytes or None
        Raw TAG_ARC_SPECIFIC_PAYLOAD bytes, preserved when geometric
        parameter extraction fails.
    """

    id: int = 0
    edge_ids: List[int] = field(default_factory=list)
    center: Optional[Tuple[float, float, float]] = None
    normal: Optional[Tuple[float, float, float]] = None
    radius: Optional[float] = None
    start_angle: Optional[float] = None
    end_angle: Optional[float] = None
    raw_arc_payload: Optional[bytes] = None


# -
# Component definition
# -


@dataclass(slots=True)
class ComponentDefinition:
    """
    A reusable named component definition (SUComponentDefinition).

    Instances are placed via :py:meth:`Entities.add_instance`.

    Attributes
    ----------
    id : int
        Unique definition ID.
    guid : bytes
        16-byte GUID blob.
    name : str
        Definition name.
    description : str
        Optional description.
    entities : Entities
        Geometry contained in this definition.
    loaded_from : str
        Path from which the definition was loaded (0x1580).
    timestamp : int
        Timestamp of last modification (0x1581).
    modified : bool
        Whether the definition has been modified (0x1582).
    definition_type : int
        Definition type enum (0x1583).
    packed_payload : bytes or None
        Packed payload blob containing thumbnails (0x1585).
    behavior_snap_mode : int
        Snap mode for component behavior (0x1B59).
    behavior_no_scale_mask : int
        No-scale mask for component behavior (0x1B5A).
    behavior_snap_enabled : bool
        Whether snap is enabled (0x1B5B).
    behavior_cuts_opening : bool
        Whether the component cuts openings (0x1B5C).
    behavior_always_face_camera : bool
        Whether the component always faces the camera (0x1B5D).
    behavior_shadows_face_sun : bool
        Whether shadows face the sun (0x1B5E).
    """

    id: int = 0
    guid: bytes = b"\x00" * 16
    name: str = ""
    description: str = ""
    entities: Entities = field(default_factory=Entities)
    loaded_from: str = ""  # TAG_DEFINITION_LOADED_FROM (0x1580)
    timestamp: int = 0  # TAG_DEFINITION_TIMESTAMP (0x1581)
    modified: bool = False  # TAG_DEFINITION_MODIFIED (0x1582)
    definition_type: int = 0  # TAG_DEFINITION_TYPE (0x1583)
    packed_payload: Optional[bytes] = None  # TAG_DEFINITION_PACKED_PAYLOAD (0x1585)
    behavior_snap_mode: int = 0  # TAG_BEHAVIOR_SNAP_MODE (0x1B59)
    behavior_no_scale_mask: int = 0  # TAG_BEHAVIOR_NO_SCALE_MASK (0x1B5A)
    behavior_snap_enabled: bool = False  # TAG_BEHAVIOR_SNAP_ENABLED (0x1B5B)
    behavior_cuts_opening: bool = False  # TAG_BEHAVIOR_CUTS_OPENING (0x1B5C)
    behavior_always_face_camera: bool = False  # TAG_BEHAVIOR_ALWAYS_FACE_CAMERA (0x1B5D)
    behavior_shadows_face_sun: bool = False  # TAG_BEHAVIOR_SHADOWS_FACE_SUN (0x1B5E)


# -
# Geometry helpers  (used by Entities.add_face and Face.normal)
# -

_PointLike = Union[Vertex, Vector3D, Tuple[float, float, float]]


def _point_values(point: _PointLike) -> Tuple[float, float, float]:
    if isinstance(point, Vertex):
        point = point.position
    if isinstance(point, Vector3D):
        return point.x, point.y, point.z
    return float(point[0]), float(point[1]), float(point[2])


def _compute_plane(
    positions: List[Vector3D],
) -> Tuple[float, float, float, float]:
    """Compute the best-fit plane for a polygon using Newell's method.

    Parameters
    ----------
    positions : list of Vector3D
        Ordered vertex positions of the polygon.

    Returns
    -------
    tuple of float
        Plane equation ``(a, b, c, d)`` where ``ax + by + cz + d = 0``.
        The normal ``(a, b, c)`` is unit-length.

    Notes
    -----
    Newell's method is robust for non-planar and concave polygons.
    For degenerate (zero-area) polygons the normal may be unreliable.
    """
    n = len(positions)
    if n == 0:
        return (0.0, 0.0, 0.0, 0.0)

    coords = np.array([p.to_tuple() for p in positions], dtype=float)
    next_coords = np.roll(coords, -1, axis=0)
    newell = np.array(
        [
            np.sum((coords[:, 1] - next_coords[:, 1]) * (coords[:, 2] + next_coords[:, 2])),
            np.sum((coords[:, 2] - next_coords[:, 2]) * (coords[:, 0] + next_coords[:, 0])),
            np.sum((coords[:, 0] - next_coords[:, 0]) * (coords[:, 1] + next_coords[:, 1])),
        ],
        dtype=float,
    )
    length = float(np.linalg.norm(newell))
    if length > 1e-12:
        newell /= length
    centroid = coords.mean(axis=0)
    d = -float(np.dot(newell, centroid))
    return (float(newell[0]), float(newell[1]), float(newell[2]), d)
