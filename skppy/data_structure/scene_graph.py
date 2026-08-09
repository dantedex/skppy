# SPDX-License-Identifier: MIT
"""Build renderer-neutral scene trees from parsed models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..exceptions import ComponentCycleError
from .entities import ComponentDefinition, ComponentInstance, Group
from .primitives import Transform
from .scene import PreparedMesh, SceneNode

if TYPE_CHECKING:
    from .materials import Material
    from .model import Model


@dataclass(slots=True)
class _SceneGraphBuilder:
    """Own lookup tables and recursion state while expanding one model."""

    model: Model
    materials: dict[int, Material] = field(init=False)
    definitions: dict[int, ComponentDefinition] = field(init=False)
    definition_meshes: dict[int, PreparedMesh | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.materials = {material.id: material for material in self.model.materials}
        self.definitions = {definition.id: definition for definition in self.model.definitions}

    def build(self) -> SceneNode:
        """Return the complete scene hierarchy in source entity order."""
        identity = Transform.identity().to_list()
        children: list[SceneNode] = []
        if self.model.entities.faces:
            children.append(
                SceneNode(
                    name="RootGeometry",
                    transform=list(identity),
                    mesh=self.model.entities.prepare_mesh("RootGeometry", self.materials),
                    children=[],
                )
            )
        children.extend(self._build_instance(instance, ()) for instance in self.model.entities.component_instances)
        children.extend(self._build_instance(group, ()) for group in self.model.entities.groups)
        return SceneNode("Scene", list(identity), None, children)

    def _build_instance(
        self,
        instance: ComponentInstance | Group,
        active_definition_ids: tuple[int, ...],
    ) -> SceneNode:
        """Expand one instance while keeping cycle detection path-local."""
        definition = self.definitions.get(instance.definition_id)
        self._reject_definition_cycle(definition, active_definition_ids)

        child_path = active_definition_ids
        children: list[SceneNode] = []
        if definition is not None:
            child_path = (*active_definition_ids, definition.id)
            children.extend(
                self._build_instance(child, child_path) for child in definition.entities.component_instances
            )
            children.extend(self._build_instance(group, child_path) for group in definition.entities.groups)

        material = self.materials.get(instance.material_id) if instance.material_id is not None else None
        return SceneNode(
            name=self._instance_name(instance, definition),
            transform=list(instance.transform),
            mesh=self._definition_mesh(instance.definition_id),
            children=children,
            material_name=material.name if material is not None else None,
        )

    def _definition_mesh(self, definition_id: int) -> PreparedMesh | None:
        """Prepare definition geometry once and share it among its instances."""
        if definition_id not in self.definition_meshes:
            definition = self.definitions.get(definition_id)
            self.definition_meshes[definition_id] = (
                definition.entities.prepare_mesh(definition.name, self.materials)
                if definition is not None and definition.entities.faces
                else None
            )
        return self.definition_meshes[definition_id]

    @staticmethod
    def _instance_name(
        instance: ComponentInstance | Group,
        definition: ComponentDefinition | None,
    ) -> str:
        """Resolve the same stable display-name fallback used by importers."""
        return instance.name or (definition.name if definition is not None else "") or f"Instance_{instance.id}"

    @staticmethod
    def _reject_definition_cycle(
        definition: ComponentDefinition | None,
        active_definition_ids: tuple[int, ...],
    ) -> None:
        """Reject only recursion on the current path, preserving valid reuse."""
        if definition is None or definition.id not in active_definition_ids:
            return
        cycle = (*active_definition_ids, definition.id)
        raise ComponentCycleError("Recursive component definition path: " + " -> ".join(str(value) for value in cycle))


def build_scene_graph(model: Model) -> SceneNode:
    """Build the public scene representation for *model*."""
    return _SceneGraphBuilder(model).build()
