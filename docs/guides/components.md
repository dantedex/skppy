# Components and Groups

Practical guide to working with SketchUp's component and group system. Unless a
snippet creates its own model, assume `model = skppy.load("model.skp")` and
`import skppy` have already run.

---

## Definitions vs. instances

| Concept | `skppy` class | Description |
|---------|---------------|-------------|
| Component definition | `ComponentDefinition` | Named geometry template. Stored once. |
| Component instance | `ComponentInstance` | Placed reference. Many instances -> one definition. |
| Group | `Group` | One-off instance with an anonymous definition. |
| Image | `Image` | A flat image entity. Backed by a definition with one face. |

---

## Iterating all instances recursively

Definitions may contain more instances and groups, and the same definition can
legitimately appear on multiple sibling paths. Track only the active recursion
path to detect a true component cycle while allowing normal reuse:

```python
def iter_instances(entities, defn_map, parent_matrix=None, active_ids=()):
    """Yield placed entity, definition, and composed 4x4 world matrix."""
    import skppy

    if parent_matrix is None:
        parent_matrix = skppy.Transform.identity().matrix

    placed_entities = [*entities.component_instances, *entities.groups]
    for placed in placed_entities:
        defn = defn_map.get(placed.definition_id)
        if defn is None:
            continue
        if defn.id in active_ids:
            path = " -> ".join(str(value) for value in (*active_ids, defn.id))
            raise skppy.ComponentCycleError(f"Recursive definition path: {path}")

        local_matrix = skppy.Transform(placed.transform).matrix
        world_matrix = parent_matrix @ local_matrix
        yield placed, defn, world_matrix
        yield from iter_instances(
            defn.entities,
            defn_map,
            world_matrix,
            (*active_ids, defn.id),
        )


defn_map = {d.id: d for d in model.definitions}
for placed, defn, world_matrix in iter_instances(model.entities, defn_map):
    position = world_matrix[:3, 3]
    print(f"{placed.name!r} -> {defn.name!r} at {position}")
```

Matrix composition uses `parent @ local`, matching the transform hierarchy.
Geometry inside `defn.entities` remains definition-local until the composed
matrix is applied.

---

## Material inheritance

When a component instance has a `material_id` set, faces inside its definition
that have `front_material_id = None` use the instance's material.

```python
lookup = {m.id: m for m in model.materials}

for inst in model.entities.component_instances:
    defn = defn_map[inst.definition_id]
    mesh = defn.entities.prepare_mesh(
        name=inst.name or defn.name,
        material_lookup=lookup,
        inherited_material_id=inst.material_id,
    )
    for face in mesh.faces:
        print(face.material_name or "no material")
```

This prepares one definition for one placement. Nested placements repeat the
same rule with the effective parent material; explicitly painted faces always
win over the instance override.

---

## Detecting shared definitions

A definition used by more than one instance is shared:

```python
from collections import Counter

counts = Counter(
    placed.definition_id
    for placed, _defn, _world in iter_instances(model.entities, defn_map)
)

for defn_id, count in counts.most_common():
    defn = defn_map[defn_id]
    print(f"{defn.name!r}: {count} instances")
```

Counting the recursive iterator includes nested instances and groups. Counting
only `model.entities.component_instances` would describe root placements only.

---

## Creating components with transforms

Compose rotation and translation matrices explicitly before creating each
placement:

```python
import math, skppy

model = skppy.new_model()
pillar = model.add_definition("Pillar")
e = pillar.entities
e.add_face([(0, 0, 0), (12, 0, 0), (12, 12, 0), (0, 12, 0)])

# Rotate each pillar 45 degrees around its local Z axis.
rot = skppy.Transform.from_rotation_z(math.radians(45))
for row in range(3):
    for col in range(3):
        translation = skppy.Transform.from_translation(row * 200, col * 200, 0)
        # Apply local rotation first, then move the result into the grid.
        placement = skppy.Transform(translation.matrix @ rot.matrix)
        model.entities.add_instance(pillar, placement, name=f"P-{row}-{col}")

model.save("pillars.skp")
```

`Transform` stores a NumPy 4x4 matrix internally. Passing the composed matrix
back to `Transform()` converts it to the 13-value representation stored on the
instance.

---

## Groups

Groups are created the same way as instances but skppy represents them
separately. Use `Entities.groups` to iterate:

```python
for grp in model.entities.groups:
    defn = defn_map[grp.definition_id]
    t = skppy.Transform(grp.transform).translation()
    print(f"Group {grp.name!r} at ({t.x:.1f}, {t.y:.1f}, {t.z:.1f})")
    print(f"  {len(defn.entities.faces)} faces inside")
```

`Group.transform` and `ComponentInstance.transform` are stored as plain
13-value lists. Wrap either in `Transform` before using matrix helpers.

---

## Entity relationships

Some models store directed relationships between entities in the same root or
component-definition scope. They are available through
`Entities.relationships` after loading:

```python
for relationship in model.entities.relationships:
    print(relationship.source_id, "->", relationship.target_id)
```

The IDs refer to entities in that `Entities` collection. An endpoint is `None`
when the source file contains a dangling reference.

---

## Attribute dictionaries

Model properties are available in `model.attribute_dictionaries`. Dictionaries
owned by a definition, material, or layer use the model-level ID map:

```python
for definition in model.definitions:
    dictionaries = model.attribute_dictionaries_by_object_id.get(definition.id, [])
    for dictionary in dictionaries:
        print(definition.name, dictionary.name)
```

Geometry and instance attributes belong to an `Entities` scope:

```python
for instance in model.entities.component_instances:
    dictionaries = model.entities.attribute_dictionaries_by_entity_id.get(
        instance.id, []
    )
    for dictionary in dictionaries:
        print(instance.name, dictionary.name)
```

These maps keep ownership explicit without exposing archive object indices.
