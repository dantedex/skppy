# Executable Examples

The examples on this page are executed by Sphinx whenever `make doctest` runs.
They intentionally avoid external SKP fixtures so the documentation remains
self-contained.

## Vectors

Vectors support common arithmetic directly. `normalized()` returns a new value
and leaves the original unchanged:

```{doctest}
>>> from skppy import Vector3D
>>> vector = Vector3D(3.0, 4.0, 0.0)
>>> vector.length()
5.0
>>> vector.normalized().to_tuple()
(0.6, 0.8, 0.0)
>>> vector.dot(Vector3D(1.0, 0.0, 0.0))
3.0
```

## Building geometry

All model coordinates use SketchUp's internal inch unit. `add_face()` creates
the required vertices, boundary edges, loop, and face in one entity scope:

```{doctest}
>>> import skppy
>>> model = skppy.new_model()
>>> blue = model.add_material("Blue", color=skppy.Color(20, 80, 200))
>>> face = model.entities.add_face(
...     [(0, 0, 0), (12, 0, 0), (0, 12, 0)],
...     material_id=blue.id,
... )
>>> (len(model.entities.vertices), len(model.entities.edges))
(3, 3)
>>> len(model.entities.faces)
1
>>> face.front_material_id == blue.id
True
```

## Reusable definitions

This block continues with the model created above. Definition geometry remains
local; the instance transform controls only its placement in the parent scope:

```{doctest}
>>> definition = model.add_definition("Triangle")
>>> _ = definition.entities.add_face(
...     [(0, 0, 0), (6, 0, 0), (0, 6, 0)]
... )
>>> transform = skppy.Transform.from_translation(24, 0, 0)
>>> instance = model.entities.add_instance(
...     definition, transform, name="Triangle-01"
... )
>>> instance.name
'Triangle-01'
>>> instance.definition_id == definition.id
True
```

These tests complement the raw-byte writer tests; they verify the public
construction API shown in the guides, not serialized wire conformance.
