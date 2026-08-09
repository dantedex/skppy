# Getting Started

Quick introduction to the two components of the project.

---

## Loading a SketchUp file

```python
import skppy

model = skppy.load("my_model.skp")
```

`load()` returns a `Model` containing all geometry, materials, layers,
component definitions, and cameras:

```python
print(model.header.product_name)    # "SketchUp 2023"
print(model.header.version_string)  # "{23.1.340}"

# Layers
for layer in model.layers:
    print(f"  layer: {layer.name!r}, visible={layer.visible}")

# Materials
for mat in model.materials:
    print(f"  mat: {mat.name!r}, color={mat.color}")

# Component definitions
for defn in model.definitions:
    print(f"  defn: {defn.name!r}, faces={len(defn.entities.faces)}")

# Saved cameras / scenes
for cam in model.cameras:
    print(f"  cam: {cam.name!r}, eye={cam.eye}")
```

---

## Traversing geometry

Root-level geometry lives in `model.entities`. Nested geometry is inside
component definitions accessed via `model.definitions`.

```python
entities = model.entities

# Raw geometry (all lengths in inches)
for vertex in entities.vertices:
    print(vertex.id, vertex.position)   # Vector3D(x, y, z)

for edge in entities.edges:
    print(edge.start_vertex_id, "->", edge.end_vertex_id)

for face in entities.faces:
    print(face.id, "plane:", face.plane)
    print("  front material id:", face.front_material_id)

# Instances at the root
for inst in entities.component_instances:
    defn = next(d for d in model.definitions if d.id == inst.definition_id)
    print(f"instance {inst.name!r} -> definition {defn.name!r}")

for grp in entities.groups:
    defn = next(d for d in model.definitions if d.id == grp.definition_id)
    print(f"group {grp.name!r} -> definition {defn.name!r}")
```

---

## Preparing geometry for importers

`Entities.prepare_mesh()` resolves material inheritance from instances and
returns a `PreparedMesh` suitable for use in any 3D engine. It keeps simple
polygons as polygons; faces with holes are triangulated by default, or a
single-hole face can be split into two simple n-gons with
`split_holes_to_ngons=True`:

```python
material_lookup = {m.id: m for m in model.materials}

mesh = model.entities.prepare_mesh(
    name="root",
    material_lookup=material_lookup,
    inherited_material_id=None,
    split_holes_to_ngons=True,
)

for face in mesh.faces:
    # Positions as (x, y, z) tuples in inches
    for pos in face.vertex_positions:
        print(pos)
    # UV as (u, v) tuples, present when the resolved material is textured
    for uv in face.vertex_uvs or []:
        print(uv)
    print("material:", face.material_name)
```

For importer backends that need indexed geometry, convert the prepared mesh to
the general mesh form:

```python
indexed = mesh.to_indexed(merge_vertices=True, triangulate=True)
print(indexed.vertex_positions)
print(indexed.faces)
print(indexed.face_material_ids)
print(indexed.face_uvs)
```

---

## Creating a model from scratch

```python
import skppy

# Start with an empty model
model = skppy.new_model()

# Add a layer and a material
floor_layer = model.add_layer("Floor", visible=True)
concrete = model.add_material(
    "Concrete",
    color=skppy.Color(180, 180, 180),
    roughness=0.9,
)

# Define a component: a simple square
slab = model.add_definition("Slab")
e = slab.entities

v0 = e.add_vertex(0,   0,   0)
v1 = e.add_vertex(200, 0,   0)
v2 = e.add_vertex(200, 200, 0)
v3 = e.add_vertex(0,   200, 0)

e.add_edge(v0.id, v1.id)
e.add_edge(v1.id, v2.id)
e.add_edge(v2.id, v3.id)
e.add_edge(v3.id, v0.id)
e.add_face([v0, v1, v2, v3], material_id=concrete.id)

# Place two instances
t1 = skppy.Transform.from_translation(0, 0, 0)
t2 = skppy.Transform.from_translation(250, 0, 0)
model.entities.add_instance(slab, t1, name="Slab-A")
model.entities.add_instance(slab, t2, name="Slab-B")

skppy.save(model, "two_slabs.skp")
```

---

## Handling legacy files

Pre-ZIP files use a CArchive binary format. `skppy.load()` detects this
container and maps its supported geometry, materials, layers, definitions,
instances, cameras, and
metadata into the same public classes used by modern files:

```python
model = skppy.load("legacy.skp")
if model.legacy_archive is not None:
    print(model.header.version_string)
    print(len(model.legacy_archive.version_map))
```

---

## Using the Blender addon

After installing (see
[Installing the Blender Addon](blender/installing.md)):

1. Open Blender and go to **File -> Import -> SketchUp (.skp)**.
2. Select a `.skp` file.
3. Adjust import options in the side panel (scale, materials, cameras, etc.).
4. Click **Import SketchUp**.

The model will appear as a collection of mesh objects.

For a full description of each import option see
[Blender Addon -> Import options](blender/import_options.md).

---

## Next steps

| Document | Description |
|----------|-------------|
| [API Reference](api/index.rst) | Complete class and function reference |
| [How-To Guides](guides/index.md) | Tutorials for specific tasks |
| [Blender Addon](blender/index.md) | Detailed addon documentation |
| [File Format](format/index.md) | SKP binary format internals |
