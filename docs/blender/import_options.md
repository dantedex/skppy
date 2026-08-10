# Import Options

Full reference for every option in the SketchUp import dialog
(**File -> Import -> SketchUp (.skp)**).

Options that affect collections and object parenting are illustrated together
in [Imported Scene Organization](scene_organization.md).

---

## Scale

**Property:** `scale`
**Type:** Float
**Default:** `0.0254`
**Range:** `0.0001` - `100.0`

Conversion factor from SketchUp inches to Blender metres.
The default `0.0254` corresponds to 1 inch = 0.0254 m (the standard SI conversion).

| Value | Effect |
|-------|--------|
| `0.0254` | 1 SKP inch = 0.0254 Blender units (metres in the default Blender unit setup) |
| `1.0` | 1 SKP inch = 1 Blender unit (no conversion - useful for abstract models) |
| `0.001` | 1 SKP inch = 0.001 Blender units (a deliberate custom scale) |

**When to change it:** If your Blender scene uses a unit scale other than
metres, or if you deliberately want to scale the model up/down on import.

---

## Merge Vertices

**Property:** `merge_vertices`
**Type:** Boolean
**Default:** `True`

After building the mesh, run `bmesh.ops.remove_doubles` with a distance
threshold of `1e-4` Blender units. This welds coincident vertices that result
from SketchUp's per-face vertex storage.

**Enable** (recommended): Produces clean, weld-free topology. Normals are
shared between adjacent faces. SketchUp smooth/soft edge shading also requires
shared vertices to interpolate normals across smoothed edges.
**Disable:** Keeps every vertex separate. Useful for troubleshooting or when
you need exact per-face normals with no interpolation.

---

## Smooth Edges

**Property:** `smooth_edges`
**Type:** Boolean
**Default:** `True`

Apply SketchUp smooth/soft edge shading where the source edge flags and adjacent
face normals indicate a real smoothed transition.

**Enable** (recommended): Cylinders, arcs, and softened curved surfaces shade
smooth while hard boundaries such as caps stay sharp.
**Disable:** Keep imported faces flat shaded and do not mark additional sharp
edges from SketchUp edge smoothing data. Useful for debugging topology or when
you want a faceted look.

This option works best with **Merge Vertices** enabled. If coincident vertices
remain split, Blender cannot interpolate normals across adjacent faces.

---

## Import Materials

**Property:** `import_materials`
**Type:** Boolean
**Default:** `True`

Create Blender materials from the SKP material definitions.

Each material uses a **Principled BSDF** node tree:

| skppy attribute | Blender node input |
|-----------------|-------------------|
| `color` (float 0-1) | Base Color |
| `alpha` | Alpha |
| `metallic` | Metallic |
| `roughness` | Roughness |
| `texture.data` | Image Texture node (packed into the .blend) |

Transparent materials (`alpha < 1.0`) use:
- Blender 4.2+: `material.surface_render_method = "DITHERED"`
- Older: `material.blend_method = "HASHED"` when supported, otherwise `BLEND`

**Disable**: All objects receive Blender's default material (grey). Useful for
quick mesh inspection without shader overhead.

---

## Use V-Ray Materials

**Property:** `import_vray_materials`
**Type:** Boolean
**Default:** `False`

Prefer PBR appearance values stored by V-Ray when a material contains supported
V-Ray metadata. Currently this includes diffuse colour, metallic, and roughness
values from V-Ray material graphs. Materials without supported V-Ray metadata
continue to use their SketchUp appearance.

**Disable** (default): Use SketchUp colour, texture, opacity, and native PBR
values. This preserves the appearance shown by SketchUp.

**Enable**: Override supported SketchUp appearance values with their V-Ray PBR
counterparts when present. Texture and other unsupported V-Ray graph inputs
continue to fall back to the SketchUp material.

This option affects material parsing even when **Import Materials** is disabled,
but the parsed materials are only created in Blender when **Import Materials**
is enabled.

---

## Import Cameras

**Property:** `import_cameras`
**Type:** Boolean
**Default:** `True`

Create Blender Camera objects from the saved scenes/views in the SKP file.

Each standalone `Camera` and each camera stored only by a saved scene becomes a
Blender camera object placed in the import collection. Scene-owned cameras use
the scene name and preserve page visibility/section/slideshow state as custom
properties.
The camera matrix is derived from the `eye`, `target`, and `up` vectors:

1. Forward: `F = normalize(target - eye)`
2. Right: `R = normalize(F x up)`
3. Up (re-orthogonalised): `U = R x F`
4. Blender matrix: column-major, `-Z` forward, `+Y` up.

FOV is applied to `camera.data.angle_x` or `camera.data.angle_y`; orthographic
views use `camera.data.ortho_scale`.

**Disable**: No cameras are created. Use this if the file has many saved scenes
that you do not need in Blender.

---

## Triangulation Mode

**Property:** `triangulation_mode`
**Type:** Enum
**Default:** `NGONS`
**Options:** `NGONS`, `QUADS`, `TRIS`

Controls how polygons are tessellated after import.

| Value | Effect | Recommended for |
|-------|--------|-----------------|
| `NGONS` | Keep n-gons where possible. Single-hole faces are split into two simple n-gons because Blender meshes cannot store true holes. | Rendering, subdivision |
| `TRIS` | Triangulate faces through skppy's generated indexed mesh output. | Game engines, rigid export pipelines |
| `QUADS` | Generate skppy geometry, then use Blender to join triangle pairs where possible (angle threshold 40 deg). | Subdivision surfaces, clean topology |

**Note:** SketchUp faces with multiple holes are still triangulated internally
by `skppy` before Blender mesh creation. Blender cannot natively represent
holey polygons, and two simple n-gons only cover the single-hole case.

---

## Import by Layers

**Property:** `import_by_layers`
**Type:** Boolean
**Default:** `False`

Organise imported objects into separate Blender collections, one per SKP layer
(Tag).

| Value | Collection layout |
|-------|------------------|
| `False` | All objects in one import collection. |
| `True` | Sub-collection per layer, e.g. `MyModel/Walls`, `MyModel/Structure`. |

Faces, component instances, groups, images, guide points, guide lines, and
section-plane helpers are assigned to their source layer collection. Untagged
objects remain in the parent import collection.

## Construction Geometry

Guide points and guide lines are imported as viewport helpers and do not
render. Section planes are imported as oriented Empty objects with their source
plane equation preserved as a custom property; they do not automatically enable
Blender clipping. These entities follow component transforms and layer
visibility like ordinary imported objects.

## Text and Dimensions

Model text and linear/radial dimensions are imported as Blender Font objects
with lightweight mesh lines for leaders and recoverable dimension geometry.
They follow source layers, materials, visibility, component transforms, and the
**Flatten Hierarchy** setting.

SketchUp screen-space labels have no direct Blender equivalent. The importer
places them in model space using their anchor and leader data. Point font sizes
are converted from points through SketchUp inches and the selected import
scale; world-sized fonts use their stored model size. Font family names and
dimension properties without native Blender equivalents are retained as custom
properties. Arrowheads and automatic Blender measurements are not generated.

Hidden layers (`layer.visible = False`) have `col.hide_viewport = True` in
Blender.

Root geometry is split by source layer because one Blender object cannot belong
to different collections per polygon. Component, group, and image objects are
linked according to their entity layer. Untagged entities stay in the main
import collection.

**Limitation:** Layer folder hierarchy is not reproduced - all layers appear as
flat sub-collections.

---

## Reuse Component Collections

**Property:** `use_collection_instances`
**Type:** Boolean
**Default:** `True`

Build every reachable SketchUp component definition once in an unlinked
Blender collection. Component placements become collection-instance Empties,
including nested placements. Repeated definitions therefore reuse both mesh
data and their stored child hierarchy instead of creating another object tree.

This is the recommended mode for large architectural models and imported CAD
drawings. Disable it when every nested component must become a directly
editable Blender object. **Import by Layers** and **Flatten Hierarchy** require
expanded objects and therefore take precedence over this option.

---

## Flatten Hierarchy

**Property:** `flatten_hierarchy`
**Type:** Boolean
**Default:** `False`

Controls whether component, group, and image hierarchy is preserved with
Blender object parenting.

| Value | Effect |
|-------|--------|
| `False` | Keep collection instances when reuse is enabled. With reuse disabled, mesh-only leaves become Mesh objects and containers become Empty parents. |
| `True` | No Empty parents. Each mesh object is placed directly in world space using the accumulated `world_matrix = parent_world @ local_matrix`. Simpler scene graph, but loses component structure. |

**Use `False`** when you need to re-export or edit components individually.
**Use `True`** when you need a flat scene for rendering or game engines.

> **Note on shared definitions:** Compatible instances reuse the same Blender
> Mesh datablock in both modes. An inherited material needed by unpainted faces
> can create a distinct `(definition_id, effective_material_id)` mesh variant.
