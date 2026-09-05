# Creating Models In Memory

`skppy` includes builder APIs for constructing `Model`, `Material`,
`ComponentDefinition`, and geometry objects in memory and saving the supported
graph to a modern `.skp` container or genuine SketchUp Make 2017 geometry.

The snippets below build one model progressively: start with **Minimal model**,
then run only the sections needed for your file. Object references always use
the returned object's `id`; list positions are not stable identifiers.

Low-level modern TLV, core geometry, and VFF/ZIP encoders now live in
`skppy.writer`. They back the supported `skppy.save()` and `Model.save()` entry
points and remain available for focused format testing.

The current writer preserves vertices, edges, faces, directed loops, segmented
curves and arc curves, simple
front/back material references, hidden/soft/smooth edge flags, PBR materials,
embedded texture images, face-side UV projections and pins, layers,
active-layer state, nested layer folders, component definitions, nested
instances, groups, GUIDs, transforms, and layer ownership for edges, faces,
instances, groups, guide points, finite/infinite guide lines, and section
planes. Model-level custom axes, geolocation/shadow data, and rendering options
(including section-plane and section-cut display state) are also serialized.
Typed attribute dictionaries can be attached to model properties, definitions,
materials, layers, and every modern entity family represented by the public
model. Placed image entities are supported when backed by an image-type
component definition and textured material. Named scenes preserve their UTF-8
name, description, flags, visibility references, animation state, and camera
snapshot. Match-photo/background images preserve their external PNG/JPEG
resource, dimensions, calibration points, visibility, opacity, and scene
association. The current model camera can also be written through
``model.cameras``. The writer also supports multiple HDR/EXR environment
entries, including their XML descriptors, image resources, thumbnails, skydome
state, reflection state, and selected environment. Custom line styles are
serialized alongside SketchUp's 12
canonical built-in patterns, preserving width, pattern scale, color, and
mutability. Model text and dimension styles preserve their font references,
leader/arrow settings, display flags, tolerances, and colors. Named visual
styles preserve their registry descriptors and optional original XML; new
descriptors receive a canonical SketchUp-compatible style resource. PNG/JPEG
watermarks preserve their name, opacity, placement, image resource, and visual
style association. Text annotations, linear dimensions, and radial dimensions
preserve their text, registered font object or font ID, drawing state, anchors,
vectors, presentation fields, and associations. Annotation anchors may refer to
root entities or leaves reached through nested component-instance paths.
Unsupported legacy-only state is rejected instead of producing a lossy file.

Material export supports base color, opacity, metallic/roughness factors, and
an unadjusted base-color image. Additional renderer properties (including IOR,
emission and auxiliary maps) raise `ValueError` when set to unsupported values,
even with V-Ray export enabled. Material names must be unique. Resolve these
errors explicitly rather than assuming that everything imported can be saved.

Saving replaces the destination only after serialization and writing complete.
A failed write leaves an existing destination intact and removes its temporary
file. Existing file permission bits and symlink targets are retained.

Generated geometry, materials, texture resources, layers, nested components,
and model metadata have been validated by opening the resulting files through
the public SketchUp C API.

---

## Minimal model

Create the shared root object before adding resources or geometry:

```python
import skppy

model = skppy.new_model()
```

The new model starts with empty entity and resource collections plus writer
defaults for metadata. IDs are allocated when builder methods add objects.

---

## Adding materials

The material builder allocates IDs and appends each returned material to the
model registry:

```python
red = model.add_material("Red", color=skppy.Color(220, 30, 30))
blue = model.add_material("Blue", color=skppy.Color(30, 80, 220))
glass = model.add_material("Glass", color=skppy.Color(200, 230, 255), alpha=0.3)
metal = model.add_material(
    "Steel",
    color=skppy.Color(180, 180, 190),
    metallic=1.0,
    roughness=0.15,
)
```

`alpha` is opacity (`0.0` transparent, `1.0` opaque). Metallic and roughness
are normalized PBR factors. Keep material names unique because face references
are written by ID but SketchUp also exposes materials by name.

---

## Adding layers

Layers and edges/faces are separate objects, so ownership is assigned by ID:

```python
arch = model.add_layer("Architecture", visible=True)
struct = model.add_layer("Structure", visible=True)
hidden = model.add_layer("Reference", visible=False)

face = model.entities.add_face([(0, 0, 0), (12, 0, 0), (0, 12, 0)])
face.layer_id = arch.id
model.entities.edges[0].layer_id = struct.id  # only the first boundary edge
```

Layer ownership is stored per entity; assigning a layer to a face does not
automatically retag its boundary edges. Set each edge explicitly when the edge
layer matters. `visible=False` stores the layer's global visibility state.

---

## Defining and placing components

A definition owns reusable local geometry; placements refer to it by ID:

```python
# 1. Create a reusable definition with definition-local geometry.
column = model.add_definition("Column", description="Square column")
e = column.entities

h = 100.0  # inches

# This compact example creates the bottom and top caps. Add four side faces
# for a closed solid; each add_face() call creates its boundary topology.
for points in [
    ((0, 0, 0), (12, 0, 0), (12, 12, 0), (0, 12, 0)),
    ((0, 0, h), (0, 12, h), (12, 12, h), (12, 0, h)),
]:
    verts = [e.add_vertex(*point) for point in points]
    e.add_face(verts, material_id=red.id)

# 2. Place the same definition three times with different local transforms.
for i, (x, y, z) in enumerate([(0, 0, 0), (200, 0, 0), (400, 0, 0)]):
    transform = skppy.Transform.from_translation(x, y, z)
    model.entities.add_instance(column, transform, name=f"Col-{i + 1}")
```

Definition coordinates remain local. Each instance stores a 13-value
SketchUp transform, so editing `column.entities` changes all three placements.

---

## Using groups

Groups are similar to component instances but their definition is anonymous.
Use `model.add_group()` for convenience:

```python
transform = skppy.Transform.from_translation(0, 0, 0)
definition, group = model.add_group("Furniture cluster", transform=transform)

# Add geometry to the anonymous group definition.
definition.entities.add_face([(0, 0, 0), (24, 0, 0), (24, 24, 0), (0, 24, 0)])
```

`add_group()` returns both objects because the group placement is registered
immediately while geometry belongs to its anonymous definition.

---

## Adding arcs and circles

Angles are radians and `segments` controls the straight-edge approximation:

```python
import math

arc = model.entities.add_arc_curve(
    center=(0, 0, 0),
    normal=(0, 0, 1),
    radius=10.0,
    start_angle=0.0,
    end_angle=math.pi / 2,
    segments=12,
)

circle = model.entities.add_arc_curve(
    center=(30, 0, 0),
    normal=(0, 0, 1),
    radius=10.0,
    start_angle=0.0,
    end_angle=2 * math.pi,
    segments=24,
)
```

Both calls create the segmented vertices and edges as well as the owning
`ArcCurve`. A full circle repeats the closing position so its last segment can
connect back to the first point.

---

## Adding an environment

Environment images are embedded from bytes rather than read later from the
saved source path:

```python
from pathlib import Path

studio = skppy.EnvironmentEntry(
    id=1,
    name="StudioEnvironment",
    image_filename="studio.exr",
    image_data=Path("studio.exr").read_bytes(),
    thumbnail_data=Path("studio-thumbnail.jpg").read_bytes(),
    use_as_skydome=True,
    use_for_reflections=True,
)
model.environment_data = skppy.EnvironmentData(
    selected=studio,
    entries=[studio],
)
```

Every environment entry requires its image bytes. Thumbnail bytes are optional;
when present, they are stored at the canonical environment thumbnail path. The
selected entry must be included in ``entries``.

---

## Saving

Both public entry points invoke the same validated writer:

```python
skppy.save(model, "output.skp")
# Equivalent convenience method on the same model:
model.save("output.skp")

# Genuine pre-ZIP SketchUp Make 2017 geometry:
model.save("output-2017.skp", format="sketchup_2017")

# Add V-Ray PBR metadata while retaining the normal SketchUp material:
model.save("output-vray.skp", export_vray_materials=True)
```

`export_vray_materials` defaults to `False`. When enabled, it maps material
colour, opacity, metallic, and roughness into a V-Ray material graph for either
output format. Native SketchUp appearance and PBR fields remain present as a
fallback. Embedded base-colour images are connected to a V-Ray bitmap graph
using UV channel 1 while remaining available as native SketchUp textures.

The 2017 writer preserves polygon and edge geometry, face holes, edge flags,
reusable component definitions, and transformed component placements in the
legacy object archive. Use the default modern format when cameras, annotations,
scenes, and document metadata without equivalent legacy output support must
remain editable.

The writer validates and builds the full container before touching the
destination. It raises `NotImplementedError` for state that exists only in the
shared legacy model and has no confirmed modern representation, rather than
silently discarding that data. This currently covers legacy entity
relationships, orphaned radial-dimension arcs, the historical text
explode-conversion flag, and soft/smooth/locked flags on annotations.

---

## Best practices

- **All coordinates in inches.** SketchUp's internal unit is the inch.
  For metric models, convert: `100 cm = 100 / 2.54 ~= 39.37 inches`.
- **Unique material names.** Duplicate names make later material lookup
  ambiguous.
- **Add edges for each face boundary** if you need explicit edge display data.
  The convenience `add_face()` path creates enough geometry for prepared mesh
  output. The low-level geometry writer validates every edge and loop reference
  before encoding it.
- **Definition names and model object IDs must be unique.** The writer validates
  both before producing the container.
