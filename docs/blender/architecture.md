# Addon Architecture

How `blender_skp_io` converts between a `skppy` model and a Blender scene.

---

## Module overview

```
blender_skp_io/blender_skp_io/
+- __init__.py          # Registration and bl_info
+- annotation_builder.py# Text and dimension conversion
+- blender_manifest.toml# Extension manifest (version, Blender minimum)
+- export_builder.py    # BlenderModelBuilder - Blender to public Model
+- scene_builder.py     # BlenderSceneBuilder - main conversion logic
\- operators/
    +- export_skp.py    # EXPORT_OT_skp operator + export properties
    +- import_skp.py    # IMPORT_OT_skp operator + property declarations
```

---

## Import pipeline

When the user clicks **Import SketchUp**:

1. **`IMPORT_OT_skp`** (`operators/import_skp.py`)
   - Imports started through Blender's file browser run `skppy.load(filepath)`
     in a worker thread. The operator remains modal while parsing, so Blender's
     event loop, redraws, and status-bar progress remain responsive.
   - Only parsing runs in the worker. All `bpy` access and scene construction
     stay on Blender's main thread.
   - Direct Python calls such as `bpy.ops.import_scene.skp(...)` retain
     synchronous `execute()` semantics and return only after the scene is
     available. Background-mode Blender also uses this synchronous path.
   - The library detects the container automatically: ZIP/VFF files use the
     modern parser and pre-ZIP CArchive files use
     `parser_legacy`. The Blender operator does not expose or require a format
     selector.
   - Instantiates `BlenderSceneBuilder` with all import options.
   - Calls `builder.build()`.

The status bar shows parsing time while the worker is active. Once parsing
finishes, `BlenderSceneBuilder` reports normalized progress for collections,
materials, definitions, root geometry, instances, cameras, and finalization.
Mesh and datablock creation must remain on Blender's main thread; individual
large mesh operations can therefore still pause interaction briefly, but the
long parser phase no longer blocks the UI.

The release ZIP contains the complete `skppy` package, including
`skppy/parser_legacy`. Development installs must likewise place or symlink the
library inside `blender_skp_io/skppy`; otherwise the addon's relative import
cannot resolve either parser.

## Export pipeline

When the user clicks **Export SketchUp**, `EXPORT_OT_skp` creates a
`BlenderModelBuilder` with the file-browser settings. The builder:

1. Resolves the selected, visible, or complete scene object scope.
2. Creates SketchUp tags from collections and materials from Principled BSDF
   state, including packed or file-backed texture images.
3. Converts Blender mesh data to shared SKP component definitions. Repeated
   unmodified mesh datablocks reuse one definition; evaluated modifier results
   receive independent definitions when necessary.
4. Places objects as root instances with inch-scaled world transforms and maps
   collection-instance Empties to definitions containing nested instances.
   Collection members use parent-relative transforms and the collection's
   instance offset, and child definitions are emitted before their container.
5. Converts Font objects, cameras, timeline camera markers, and scalar custom
   properties to text annotations, camera/scene records, and attribute
   dictionaries.
6. Calls `Model.save()`, which validates and assembles the complete container
   before replacing the destination.

Mesh conversion keeps one SKP vertex and edge per Blender mesh element and
builds directed face loops from Blender loop edge indices. Active per-loop UVs
are fitted to each face's projective SKP mapping, with exact control points for
the first four corners. A retained edge receives SketchUp's soft and smooth
flags only when it has exactly two adjacent polygons, both polygons are
smooth-shaded, and the Blender edge is not explicitly sharp. Boundary,
non-manifold, sharp, and smooth/flat-transition edges remain hard.

Collection-instance conversion does not depend on evaluated `matrix_world`
values for objects that live only in an unlinked source collection. It composes
each member's `matrix_parent_inverse @ matrix_basis` through the parent chain,
subtracts `Collection.instance_offset`, and deduplicates objects by Blender
datablock identity when they are linked through multiple collection paths.
Definitions are serialized dependency-first because official SketchUp readers
must encounter child mesh or collection definitions before a containing
definition references them. Parent and collection cycles are reported as
conversion errors. Unsupported Blender object families are counted and
reported by the operator.

2. **`BlenderSceneBuilder.build()`** (`scene_builder.py`)
   - Creates a top-level import collection named after the file.
   - Calls each build step in order:
     1. `_build_layer_collections()`
     2. `_build_materials()`
     3. `_build_definitions()`
     4. `_build_root_geometry()`
     5. `_build_root_construction()`
     6. `_build_root_annotations()`
     7. `_build_root_instances()`
     8. `_build_cameras()`
   - In the default collection-instance mode, reachable definition/material
     variants are built once and nested component references reuse those
     unlinked source collections. Layer or flattened imports use expanded
     objects instead.
   - Calls the optional progress callback between phases and after each
     material and component definition.

---

## Layer collections

`_build_layer_collections()` runs only when `import_by_layers=True`.

- One Blender collection per `Layer` object.
- `col.hide_viewport = not layer.visible`.
- Collections are stored in a dict keyed by `layer.id`.
- Root faces are split into one mesh object per layer and linked to that
  collection. Untagged faces remain in the top-level import collection.
- Component, group, and image objects use their own layer collection; nested
  objects without an explicit layer remain with their parent's collection.
- Guide points, guide lines, and section-plane helpers follow the same layer
  assignment, including when they belong to a component definition.

---

## Construction entities

`_build_root_construction()` and `_build_construction_entities()` preserve
non-rendering SketchUp construction geometry as Blender viewport helpers:

- Guide points become spherical Empty objects at their stored positions.
- Guide lines become non-rendering mesh edges. Because Blender has no infinite
  line primitive, the viewport representation extends 1000 SketchUp inches in
  each direction from the stored point.
- Section planes become cube-display Empty objects whose local Z axis matches
  the plane normal. Their source plane equation and optional symbol are kept
  in custom properties.

Helpers inside component definitions inherit the same hierarchy and transforms
as definition geometry. In flat-hierarchy mode, their transforms are accumulated
into world space. A section-plane helper preserves source data but does not
activate Blender clipping, whose behavior and scope differ from SketchUp's.

---

## Text and dimensions

`BlenderAnnotationBuilder` converts the shared, container-independent
annotation classes into Blender objects:

- Text labels become Font objects, with a mesh segment for a visible leader.
- Linear dimensions use a Font object plus mesh segments for the dimension and
  extension lines.
- Radial dimensions use a Font object and add a radial segment when the shared
  model contains enough placement geometry.

Annotation objects retain source layer assignment, material, hidden state,
component hierarchy, and flattened world transforms. Fields without a Blender
counterpart, including arrow kind and dimension mode, remain available as
custom properties. Blender does not provide SketchUp's screen-space text or
dimension system, so point-sized text is represented in model space and stored
font family names are not resolved to operating-system font files automatically.

---

## Material creation

`_build_materials()` iterates `model.materials`:

- Skips materials already present in `bpy.data.materials` by name (idempotent).
- Creates a new `bpy.data.materials.new(name)`.
- Enables `use_nodes = True` and sets up a **Principled BSDF** node tree.
- Maps `color`, `alpha`, `metallic`, `roughness` to the BSDF inputs.
- For textured materials:
  1. Writes texture bytes to a temporary file.
  2. Loads the image with `bpy.data.images.load(temp_path)`.
  3. Packs the image into the `.blend` with `image.pack()`.
  4. Deletes the temp file.
  5. Connects an `Image Texture` node to the BSDF Base Color and Alpha.
- Sets `surface_render_method = "DITHERED"` (Blender 4.2+) or `blend_method = "HASHED"` when transparency is needed, falling back to `BLEND` only when the dithered option is unavailable.

---

## Mesh and definition caching

`_build_definitions()` prepares skppy meshes for component definitions and
passes them to `_build_mesh_from_prepared()`.

The cache key ensures that when the same definition is placed with different
instance material overrides, separate Blender meshes are created (they would
otherwise have different vertex colours / material assignments).

`_build_mesh_from_prepared()`:
1. Calls `PreparedMesh.to_indexed()` to get renderer-neutral indexed geometry
   from skppy.
2. Creates a `bpy.data.meshes.new()` and fills it with `mesh.from_pydata()`.
3. Assigns material slots from the resolved face material names.
4. Writes a Blender UV layer from skppy's per-loop UV data when present.
5. Applies Blender-specific quad conversion when `triangulation_mode="QUADS"`.

`TRIS` uses skppy's triangulation before Blender sees the mesh. `NGONS` keeps
skppy's prepared polygons as-is where possible; single-hole SKP faces are split
into two simple n-gons because Blender mesh faces cannot store holes.

---

## Cameras and scenes

`_build_cameras()` creates cameras from both `model.cameras` and cameras owned
only by saved `Scene` pages. A scene-owned camera uses the page name and keeps
the scene ID, description, hidden entity/layer IDs, active section planes, and
slideshow flag as custom properties. Scene cameras already present by identity
in `model.cameras` are not duplicated.

Perspective field of view and orthographic height are converted to Blender
camera settings. Eye, target, and up vectors form an orthonormal transform with
Blender's local `-Z` viewing direction.

---

## Instance hierarchy

`_build_root_instances()` processes `model.entities.component_instances`
and `.groups`.

**Normal mode (`flatten_hierarchy=False`):** A definition containing only its
own faces becomes a Mesh object directly at the instance transform. Definitions
that contain children, construction geometry, or annotations use this layout:

```
Empty (at instance transform)
  +- Mesh object for direct faces (at identity transform)
  \- Nested instance/helper/annotation objects
```

- The Empty uses the instance's `Transform` as its `matrix_local`.
- Direct faces use an identity-transform child named `<instance>:faces`.
- Nested contents inherit the transform through the parent-child relationship.
- Mesh-only leaves omit the redundant Empty.
- Compatible instances share the same `Mesh` datablock.

**Flat mode (`flatten_hierarchy=True`):**

- Accumulates `world_matrix = parent_world @ local_matrix`.
- Creates a standalone mesh object with `matrix_world = world_matrix`.
- No Empty parents.
- Container-only nodes disappear, but their descendant geometry remains.
- Compatible instances still share their cached `Mesh` datablock.

Layer collection membership is independent of object parenting in either mode.
See [Imported Scene Organization](scene_organization.md) for complete layouts
and the mapping of SketchUp entity types to Blender objects.

---

## Camera conversion

`_build_cameras()` creates one Blender camera per `Camera` in `model.cameras`:

1. Compute the right-hand basis:
   - `F = normalize(target - eye)`
   - `R = normalize(F x up)`
   - `U = R x F`
2. Build a Blender `Matrix` (column-major, `-Z` forward, `+Y` up):
   ```
   [ Rx  Ux  -Fx  eye.x * scale ]
   [ Ry  Uy  -Fy  eye.y * scale ]
   [ Rz  Uz  -Fz  eye.z * scale ]
   [  0   0    0        1        ]
   ```
3. Set `camera_obj.matrix_world`.
4. Set `camera.data.lens` from FOV.
5. Set `camera.data.type = "PERSP"` or `"ORTHO"`.

---

## Default material

Objects that have faces with no resolved material receive a slot filled with a
material named **"SKP Default"** (base colour 0.8, 0.8, 0.8, roughness 1.0).
This material is created once and reused.
