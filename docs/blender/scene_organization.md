# Imported Scene Organization

The importer keeps every import inside one top-level Blender collection. Its
name is the stem of the `.skp` filename, or `SKP Import` when the model has no
source path. **Reuse Component Collections**, **Import by Layers**, and
**Flatten Hierarchy** control how the result is represented:

- collection reuse avoids expanding repeated component hierarchies;
- layer collections describe SketchUp layers/tags;
- flattening removes object parenting from expanded imports.

Layer grouping or flattening requires expanded objects and therefore disables
collection reuse for that import.

## Default layout

With collection reuse enabled, each component definition is built once in an
unlinked source collection. Only its placements appear in the imported scene:

```text
Scene Collection
\- house
   +- RootGeometry [Mesh]
   +- Chair A [Collection Instance]
   +- Room [Collection Instance]
   +- GuidePoint_7 [Empty]
   \- Front View [Camera]
```

`RootGeometry` contains ungrouped root faces and visible loose edges. Nested
components, construction geometry, and annotations live once in the source
definition collection and appear through every placement. The source
collections remain unlinked so their contents are not displayed a second time.

Disable **Reuse Component Collections** to obtain the expanded Empty/Mesh
parent hierarchy. Instances still share compatible Mesh datablocks in that
mode, but every placement receives its own Blender object tree.

## With layer collections

Enabling **Import by Layers** creates one direct child collection for every
SketchUp layer/tag:

```text
Scene Collection
\- house
   +- Walls
   +- Furniture
   \- Hidden Reference
```

The layer collections are flat: SketchUp layer-folder nesting is not recreated.
A hidden SketchUp layer has `hide_viewport` enabled on its collection.

Root faces are grouped by layer because a Blender mesh object cannot assign a
different collection per polygon. They are named `RootGeometry:<layer>`;
untagged root faces remain in `RootGeometry` in the import collection.
Instances, images, guides, section planes, text, and dimensions use their
explicit source layer. A nested entity without an explicit layer stays in its
parent's collection. Cameras always remain directly in the import collection.

Collection membership and object parenting remain independent. For example, a
nested chair may be stored in the `Furniture` collection while its Blender
parent is the `Room` Empty.

## With a flattened hierarchy

Enabling **Flatten Hierarchy** removes component/group Empty parents. Each
renderable mesh and helper receives the accumulated transform
`parent_world @ local_matrix` directly:

```text
Scene Collection
\- house
   +- RootGeometry [Mesh]
   +- Room [Mesh]
   +- Chair B [Mesh]
   \- Text_42 [Font]
```

Container-only instances disappear because there is no Empty to represent
them, while their descendant geometry remains. Object parenting and the
editable component tree are lost, but compatible instances still reuse their
Mesh datablocks. Layer collections can be enabled at the same time; flattening
changes transforms and parenting, not collection assignment.

## Entity mapping

| SketchUp content | Blender result | Placement |
|---|---|---|
| Ungrouped root faces | One `RootGeometry` Mesh, or one Mesh per layer | Identity/world origin |
| Component, group, or image | Collection-instance Empty by default | Instance transform |
| Expanded component hierarchy | Mesh leaf or Empty plus optional `<name>:faces` Mesh | Parent-child hierarchy |
| Guide point | Spherical, in-front Empty | Source point |
| Guide line | Non-rendering Mesh edge | Source line, displayed with finite extent |
| Section plane | Oriented cube-display Empty | Source plane; does not enable clipping |
| Text | Font object and, when visible, a leader Mesh | Model-space anchor and leader |
| Linear/radial dimension | Font object plus recoverable line Meshes | Model-space dimension geometry |
| Camera or saved-scene camera | Camera object | Always in the top-level import collection |

Visible SketchUp edges not used by a face are emitted as edges in the owning
Blender mesh. This preserves 2D CAD linework and line-only component
definitions without creating one object per segment. Guide and annotation
lines remain explicit helper objects.

## Materials, textures, and saved scenes

Materials, textures, meshes, cameras, and fonts also appear in Blender's data
views even though only objects and collections appear in the scene hierarchy.
Imported textures are packed into their Blender images. Unpainted faces use the
shared `SKP Default` material when material import is enabled.

A standalone SketchUp camera becomes one Blender Camera object. A camera owned
only by a saved scene/page also becomes a Camera named from that scene. The
scene ID, description, hidden entity/layer IDs, active section plane IDs, and
slideshow flag are retained as custom properties; SketchUp pages do not become
Blender scenes or collections.
