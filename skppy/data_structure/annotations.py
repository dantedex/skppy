# SPDX-License-Identifier: MIT
"""Text, leader, and dimension entities shared by both SKP parsers.

Annotations use the same entity IDs, layer IDs, and font registry as model
geometry. A :class:`PointReference` preserves both its model-space position
and the optional entity/instance path that makes the annotation associative.

Example
-------
::

    import skppy

    note = skppy.Text(
        text="Entrance",
        anchor=skppy.PointReference(position=skppy.Vector3D(24, 12, 0)),
    )
    model.entities.texts.append(note)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .primitives import Vector2D, Vector3D

if TYPE_CHECKING:
    from .model_metadata import Font


@dataclass(slots=True)
class DrawingElementProperties:
    """Appearance and visibility shared by drawable annotation entities."""

    material_id: int | None = None
    layer_id: int | None = None
    hidden: bool = False
    casts_shadows: bool = True
    receives_shadows: bool = True
    soft: bool = False
    smooth: bool = False
    locked: bool = False


@dataclass(slots=True)
class PointReference:
    """A model position optionally associated with an entity or instance path."""

    kind: int = 0
    position: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    entity_id: int | None = None
    secondary_entity_id: int | None = None
    instance_path_ids: list[int] = field(default_factory=list)
    secondary_instance_path_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Text:
    """A text annotation and its leader placement."""

    id: int = 0
    text: str = ""
    anchor: PointReference = field(default_factory=PointReference)
    font: Font | None = None
    font_id: int | None = None
    screen_position: Vector2D = field(default_factory=lambda: Vector2D(0.0, 0.0))
    leader_vector: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    view_direction: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 1.0))
    leader_type: int = 0
    line_weight: int = 0
    anchor_in_front: bool = False
    hide_out_of_plane: bool = False
    arrow_type: int = 0
    display_leader: bool = True
    convert_to_screen_on_explode: bool = False
    hidden_leader_direction: int = 0
    drawing: DrawingElementProperties = field(default_factory=DrawingElementProperties)


@dataclass(slots=True)
class Dimension:
    """Fields common to linear and radial dimension entities."""

    id: int = 0
    text: str = ""
    font: Font | None = None
    font_id: int | None = None
    is_3d_text: bool = False
    arrow_type: int = 0
    drawing: DrawingElementProperties = field(default_factory=DrawingElementProperties)


@dataclass(slots=True)
class LinearDimension(Dimension):
    """A dimension between two model point references."""

    start: PointReference = field(default_factory=PointReference)
    end: PointReference = field(default_factory=PointReference)
    direction: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 1.0))
    render_direction: Vector3D = field(default_factory=lambda: Vector3D(1.0, 0.0, 0.0))
    mode: int = 0
    offset: float = 0.0
    line_position: float = 0.0
    alignment: int = 0


@dataclass(slots=True)
class ArcGeometry:
    """Standalone arc geometry embedded by an unassociated radial dimension."""

    center: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    normal: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 1.0))
    x_axis: Vector3D = field(default_factory=lambda: Vector3D(1.0, 0.0, 0.0))
    start_angle: float = 0.0
    end_angle: float = 0.0
    y_axis: Vector3D | None = None


@dataclass(slots=True)
class RadialDimension(Dimension):
    """A radius or diameter dimension associated with an edge or embedded arc."""

    target_entity_id: int | None = None
    parameter: float = 0.0
    radius_ratio: float = 1.0
    is_diameter: bool = False
    arc: ArcGeometry | None = None
