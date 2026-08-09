# Working with Geometry

Detailed guide to vertices, edges, faces, loops, and the triangulation system.
The snippets assume `model = skppy.load("model.skp")` and use its root
`Entities` scope unless stated otherwise.

---

## Vertex IDs and lookup

Every `Vertex`, `Edge`, and `Face` has an integer `id` unique within its
entity scope. Cross-references (e.g., edge start/end, loop edge-uses) use
these IDs.

```python
e = model.entities

# Build a quick lookup map
vertex_map = {v.id: v for v in e.vertices}
edge_map = {ed.id: (ed.start_vertex_id, ed.end_vertex_id) for ed in e.edges}

# Resolve an edge
for edge in e.edges:
    start = vertex_map[edge.start_vertex_id]
    end   = vertex_map[edge.end_vertex_id]
    print(f"Edge {edge.id}: {start.position} -> {end.position}")
```

Do not use `entities.vertices[id]`: IDs need not be contiguous or zero-based,
especially after loading a file or deleting objects in memory.

---

## Traversing face loops

Each `Face` has an `outer_loop` and zero or more `inner_loops` (holes).
Loops contain `EdgeUse` objects that specify an edge and traversal direction.

```python
for face in e.faces:
    # Outer boundary vertex IDs
    outer_ids = face.outer_loop.vertex_ids(edge_map)
    print(f"Face {face.id} outer:", outer_ids)

    for i, hole in enumerate(face.inner_loops):
        hole_ids = hole.vertex_ids(edge_map)
        print(f"  hole {i}:", hole_ids)
```

`Loop.vertex_ids()` handles reversed `EdgeUse` entries and follows the stored
loop traversal. Valid outer loops normally follow front-face winding, but the
method does not repair malformed source topology.

---

## Face normals and planes

The plane equation `(a, b, c, d)` satisfies `ax + by + cz + d = 0`.
The normal is the unit vector `(a, b, c)`:

```python
for face in e.faces:
    n = face.normal()   # Vector3D
    print(f"Face {face.id} normal: ({n.x:.3f}, {n.y:.3f}, {n.z:.3f})")
```

---

## Triangulating faces

Use `Face.triangulate()` for a simple fan of the outer boundary. The result is
a list of `(a, b, c)` **vertex-ID triples**, not list indices:

```python
for face in e.faces:
    triangles = face.triangulate(e)
    for a_id, b_id, c_id in triangles:
        va = vertex_map[a_id]
        vb = vertex_map[b_id]
        vc = vertex_map[c_id]
        print(va.position, vb.position, vc.position)
```

`Face.triangulate()` intentionally ignores inner loops. For importer-ready
faces with holes, call `Entities.prepare_mesh()`: it merges loops with bridge
edges and uses ear clipping. Importers that prefer n-gons can pass
`split_holes_to_ngons=True` to represent a single-hole face as two simple
n-gons; multiple-hole faces still triangulate.

---

## Degenerate faces

`Face.triangulate()` returns an empty list only when fewer than three outer-loop
edge uses resolve. It is a topology convenience and does not test collinearity
or self-intersection. The `prepare_mesh()` path performs the stronger geometric
processing used by the Blender importer and may omit faces that cannot produce
valid polygons.

---

## Working in world space

Vertex positions in a `ComponentDefinition` are in **definition-local space**.
To transform to world space, multiply by the instance transform chain:

```python
import numpy as np

def local_to_world(
    position: skppy.Vector3D, world_matrix: np.ndarray
) -> skppy.Vector3D:
    """Apply rotation, scale, translation, and homogeneous division."""
    point = world_matrix @ np.array([position.x, position.y, position.z, 1.0])
    if abs(point[3]) > 1.0e-12:
        point = point / point[3]
    return skppy.Vector3D(float(point[0]), float(point[1]), float(point[2]))

for inst in model.entities.component_instances:
    defn = defn_map[inst.definition_id]
    world_matrix = skppy.Transform(inst.transform).matrix
    for v in defn.entities.vertices:
        world_pos = local_to_world(v.position, world_matrix)
        print(world_pos)
```

For a nested instance, compose matrices in parent-to-child order:
`child_world = parent_world @ Transform(child.transform).matrix`. Reusing this
matrix for all vertices in a placement avoids repeated conversion of the
13-value representation.

---

## Curves and arcs

Edges that belong to a curve have a non-`None` `curve_id`. SketchUp arcs and
circles are stored as collections of straight edges sharing a `curve_id`:

```python
from collections import defaultdict

curves = defaultdict(list)
for edge in e.edges:
    if edge.curve_id is not None:
        curves[edge.curve_id].append(edge)

for curve_id, edges in curves.items():
    print(f"Curve {curve_id}: {len(edges)} segments")
```

Use `entities.curves` and `entities.arc_curves` when you also need polygon
state or circular parameters such as center, normal, radius, and angles.

---

## Text and dimensions

Both SKP container families expose annotations through the same entity lists:

```python
for text in e.texts:
    print(text.text, text.anchor.position, text.font)

for dimension in e.linear_dimensions:
    print(dimension.start.position, dimension.end.position, dimension.text)

for dimension in e.radial_dimensions:
    print(dimension.target_entity_id, dimension.radius_ratio, dimension.is_diameter)
```

Fonts are shared model resources. `font_id` retains the reference even when a
source file does not provide a resolvable `Font` object.

`PointReference.entity_id` is populated when the source annotation points to an
entity that can be resolved in the same scope. A null or unavailable association
leaves it as `None` while preserving the measured position. `drawing` contains
the normalized material, layer, visibility, shadow, smoothing, and lock state.
