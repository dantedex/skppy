# Imported Scene Organization

The importer keeps every import inside one top-level Blender collection. Its
name is the stem of the `.skp` filename, or `SKP Import` when the model has no
source path. The options **Import by Layers** and **Flatten Hierarchy** control
two independent parts of the result:

- collections describe SketchUp layers/tags;
- object parenting describes component, group, and image nesting.

Changing one does not implicitly change the other.

## Default layout

With **Import by Layers** and **Flatten Hierarchy** both disabled, an import can
look like this. The names are illustrative, but the object types and parent
relationships reflect the importer rules.

```text
Scene Collection
\- house
   +- RootGeometry [Mesh]
   +- Chair A [Mesh]
   +- Room [Empty]
   |  +- Room:faces [Mesh]
   |  +- Chair B [Mesh]
   |  \- Text_42 [Font]
   +- GuidePoint_7 [Empty]
   \- Front View [Camera]
```

`RootGeometry` contains ungrouped faces from the SketchUp model root. A
component, group, or image definition that contains only its own face geometry
is represented directly by a Mesh object, such as `Chair A`; an unnecessary
Empty is not added. A definition that also contains nested instances,
construction entities, or annotations gets an Empty at the instance transform.
Its direct faces become an identity-transform child named `<instance>:faces`,
and its other contents are parented below the same Empty.

Component definitions are converted to Blender Mesh datablocks, not to
collections of their own. Instances of the same definition reuse a Mesh
datablock when their effective inherited material permits it. Editing shared
mesh data in Blender therefore affects every object using that data; use
Blender's **Make Single User** command first when an instance must diverge.

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
| Component, group, or image with faces only | Mesh object using cached definition data | Instance transform |
| Container with nested or auxiliary content | Empty plus optional `<name>:faces` Mesh | Parent-child hierarchy |
| Guide point | Spherical, in-front Empty | Source point |
| Guide line | Non-rendering Mesh edge | Source line, displayed with finite extent |
| Section plane | Oriented cube-display Empty | Source plane; does not enable clipping |
| Text | Font object and, when visible, a leader Mesh | Model-space anchor and leader |
| Linear/radial dimension | Font object plus recoverable line Meshes | Model-space dimension geometry |
| Camera or saved-scene camera | Camera object | Always in the top-level import collection |

Ordinary SketchUp edges are used to construct face topology; loose ordinary
edges are not emitted as separate Blender curve or mesh objects. Guide and
annotation lines are the explicit line-object exceptions.

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

