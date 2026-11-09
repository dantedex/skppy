# Export Options

The addon registers `export_scene.skp` under **File -> Export -> SketchUp
(.skp)**. It converts Blender data to the public `skppy.Model` graph and writes
either a modern SKP container or a genuine pre-ZIP SketchUp Make 2017 file
without requiring the SketchUp SDK.

The complete model is validated and serialized before the destination is
replaced. A conversion or writer failure therefore leaves an existing output
file untouched.

```{figure} ../_static/screenshots/export-options.png
:alt: Blender 4.5 SketchUp export dialog before the procedural baking controls were added.

Earlier Blender 4.5 LTS export dialog. The new baking controls are described
in the table below but are not shown in this capture. Some labels are shortened
by the file browser.
```

## Settings

| Option | Default | Behavior |
|--------|---------|----------|
| **File Format** | Modern | Writes the current ZIP-based format or the legacy SketchUp Make 2017 CArchive format. |
| **Objects** | Visible | Export visible objects, selected objects, or every object in the active scene. |
| **Inches per Blender Unit** | 39.37007874 | Converts Blender coordinates to SketchUp's internal inch unit. Use `1` when Blender units already represent inches. |
| **Apply Modifiers** | On | Uses evaluated mesh data with the current modifier stack. Unmodified shared mesh data remains one reusable SKP definition. |
| **Merge Coplanar Faces** | On | Merges adjacent polygons on the same plane when their material and UV projection match. Internal edges are removed and enclosed boundaries become face holes. |
| **Materials and PBR** | On | Exports supported color, opacity, metallic, and roughness from the active Cycles surface, with explicit warnings for approximations. |
| **Embedded Textures** | On | Embeds compatible direct images or optional baked color/alpha textures. |
| **Bake Procedural Color and Alpha** (`bake_materials`) | Off (`False`) | Uses CPU Cycles to bake supported linked color/alpha expressions when needed. Requires Materials and PBR, Embedded Textures, and UV Coordinates. |
| **Bake Resolution** (`bake_resolution`) | 1024 | Width and height in pixels; integer range [16, 4096]. |
| **Bake Margin** (`bake_margin`) | 16 | UV-island padding in pixels; integer range [0, resolution]. |
| **UV Coordinates** | On | Converts the active UV layer to per-face SKP projections and control points. |
| **Collections as Tags** | On | Uses `skppy_layer_name` when present; otherwise uses the object's first collection. |
| **Cameras and Markers** | On | Exports cameras and timeline camera markers as saved SketchUp scenes. |
| **Text as Annotations** | On | Converts Blender Font objects to model-space SketchUp text annotations. |
| **Custom Properties** | On | Writes scalar bool, unsigned integer, finite float, and string properties to a `Blender` attribute dictionary. |

## Geometry and instances

Mesh, Curve, Surface, and Meta objects are converted to SKP mesh definitions.
Objects sharing the same unmodified Blender data and material slots reuse one
definition and become separate component instances with their world transforms.
When modifiers change evaluated geometry, the affected object receives its own
definition.

Collection-instance Empty objects become component definitions containing
nested instances. The Empty's world transform places the component, while the
source members keep their collection-local hierarchy and Blender's
`instance_offset`. This also works for source collections that are not linked
directly into the active scene, where Blender may not have evaluated useful
`matrix_world` values for their objects.

An object linked through more than one path in the same collection hierarchy is
exported once, following Blender's evaluated-instance behavior. Child mesh and
nested-collection definitions are written before the collection definition
that references them; this dependency order is required by official SketchUp
readers. Object-parent and nested-collection cycles are rejected explicitly.
Ordinary Empty objects, lights, armatures, and other object families without a
direct SKP representation are counted as ignored in the completion report.

Blender mesh vertices and edges remain shared inside each definition. Polygon
loop direction, smooth/sharp state, material slots, and active UV data are
preserved. Blender supports arbitrary per-loop UVs while one SKP face stores a
single projective mapping; non-affine n-gon mappings are fitted and reported as
conversion warnings for ordinary materials. Baked materials instead reject
non-affine polygon UVs: triangulate the affected polygons before export.

Coplanar merging only joins edge-connected polygons with matching orientation,
plane, material slot, and affine UV projection. Material boundaries, UV seams,
non-coplanar edges, and non-manifold boundaries therefore remain separate.
Closed interior cycles are emitted as SketchUp inner loops rather than being
filled.

### Edge shading

For every retained mesh edge, the exporter maps Blender's actual face and edge
shading state to SketchUp's public `Edge.flags`:

| Blender edge state | SketchUp flags | Exported result |
|--------------------|----------------|-----------------|
| Exactly two adjacent smooth-shaded faces and no explicit sharp mark | `soft` + `smooth` | Smooth shared boundary |
| Either adjacent face is flat-shaded | none | Hard boundary |
| Explicitly marked sharp | none | Hard boundary |
| Boundary edge with fewer than two adjacent faces | none | Hard, visible boundary |
| Non-manifold edge with more than two adjacent faces | none | Hard boundary |

This rule preserves smooth/flat transitions instead of smoothing an edge when
only one adjacent polygon is smooth. It does not apply the importer's angle
threshold: Blender's authored `use_smooth` and `use_edge_sharp` state is the
source of truth during export. When coplanar merging removes an eligible
internal edge, no SketchUp edge remains to carry shading flags; all retained
edges use the mapping above.

The SketchUp 2017 path writes the legacy object archive while preserving
reusable component definitions, placements, geometry, transforms, edge flags,
face holes, materials, textures, and tags. Modern export remains the choice for
cameras, annotations, scenes, and custom properties that do not have equivalent
legacy output support.

## Materials and textures

The exporter follows the **active Cycles/ALL Material Output** Surface link,
resolves reroutes, and identifies shaders by type: node names are irrelevant.
If Cycles and Eevee select different outputs, a warning explains that Cycles
wins. Missing/incompatible outputs, shader-closure node groups, Mix Shader,
Add Shader, unsupported closures, and volume outputs use a warned viewport
fallback; they are not flattened into an equivalent shader. Multiple material
slots still export as separate face assignments.

| Active surface | Export approximation |
| --- | --- |
| Principled BSDF | Base Color, Alpha, constant Metallic and Roughness; other features are not generally representable. |
| Diffuse BSDF | Opaque color/roughness, metallic 0. |
| Glossy / Anisotropic BSDF | Color/roughness, metallic 1, with a warning that this is not physically equivalent. |
| Translucent, Glass, Refraction BSDF | Opaque color/roughness; transmission is lost and warned, not converted to opacity. |
| Transparent BSDF | Constant white becomes alpha 0; tinted or linked color uses an opaque color approximation with a warning. |
| Emission | Color only; emission strength/energy is lost and warned. |

Compatible direct images are copied without baking: packed or file-backed,
unmodified sRGB/straight-alpha images using flat projection, repeat extension,
and UV coordinates matching the exported active UV layer. Reroutes are allowed.
The exporter no longer selects an arbitrary image hidden upstream. Mapping,
color math, mixed images, alternate UVs, generated images, or dirty pixel buffers
require evaluation through the optional bake path; with baking off, omitted
color/alpha expressions use socket defaults with explicit warnings.

Image alpha is preserved directly only when that same Image Texture's Alpha
output drives the shader Alpha input. Otherwise the color image is exported
opaque (re-encoded if necessary), and scalar shader opacity remains separate.
An unused image alpha channel or a color socket's fourth component is not an
implicit opacity mask.

```{figure} ../_static/screenshots/principled-material.png
:alt: Blue paint material with constant Base Color, Metallic, Roughness, and Alpha on a Principled BSDF.

A simple constant-input material exports without baking. The Principled node
may be renamed; it must feed the active Cycles/ALL output. IOR and other
unsupported shader features are not part of the exported subset.
```

### Preparing a material today

1. Connect a supported single shader to the active Cycles/ALL Material Output.
2. Prefer constants and compatible direct images when possible. Save or pack
   intended image bytes for direct transfer.
3. For procedural color or Alpha, enable **Bake Procedural Color and Alpha**,
   along with materials, textures, and UV export. Set resolution and margin.
4. Put the source object in **Object mode**. Supply an existing active UV map
   with finite, nondegenerate, non-overlapping destination triangles inside
   **0–1**. There is **no automatic unwrap**. Triangulate polygons whose UVs
   cannot be represented by an affine per-face mapping.
5. Review warnings and inspect the result in the target SketchUp version.
   Successful conversion is not a promise of full shader fidelity.

### Optional baking: scope and cost

Only supported **color and alpha expressions** are baked, including procedural
textures, ramps, math/mixes, and color-expression node groups. Shader-closure
groups and Mix/Add Shader networks remain unsupported even with baking enabled.
Linked Metallic/Roughness use their socket defaults with explicit warnings;
normal/bump, displacement, transmission, coat, sheen, subsurface, IOR/specular,
and emission energy are not preserved by a color bake.

Baking runs **synchronously on CPU Cycles**, even for an Eevee source scene.
Expect export time and memory use to grow with resolution and object/material
count. There is no modal progress or cancellation guarantee. The baker uses
export-only mesh/material copies and a temporary scene, cleans up on success
or error, and does not overwrite source images or change user preferences.
Color and scalar alpha are evaluated separately through unlit emission passes,
then encoded as an sRGB-color, straight-alpha RGBA PNG; alpha is linear coverage,
not display-transformed. A separate Alpha graph is combined into that image.
The exported color and opacity multipliers become white and 1, avoiding double
multiplication. Transmission is not coverage.

The result freezes appearance at the current frame/subframe. Procedural bakes
create **per-object/material variants**, and affected shared meshes lose
cross-object component-definition reuse. Compatible direct materials retain
reuse; this is not an atlas or a general object-independent bake cache.

The baker rejects context-dependent sources such as Object Info, Camera Data,
Light Path, Shader to RGB, particle/hair information, unsafe Geometry outputs,
and camera/window/reflection/normal or instancer coordinates. Material/node-tree
drivers (including expression groups), sequence/movie images, and tiled/UDIM
images are unsupported. Invalid/overlapping UVs, excessive UV-validation work,
Cycles failures, singular projections, and non-affine baked polygons also abort
rather than silently substituting an unrelated image. Conversion/bake errors
occur before saving, so an existing destination remains intact.

Optional material custom properties `skppy_x_scale` and `skppy_y_scale` set the
physical texture tile size in SketchUp inches. Both default to `1.0`.

Enscape and V-Ray materials are supported for import only. Renderer-specific
export is deferred to a future feature; this exporter writes native SketchUp
materials.

The export material subset is Base Color, Alpha, Metallic, Roughness, and the
base-color image. Import support for renderer maps does not imply export
support for those maps. The Python writer rejects unsupported public material
properties rather than silently discarding them; it also rejects duplicate
material names.
The Blender adapter reports omitted renderer maps, non-default IOR/specular,
emission, and displacement as conversion warnings before returning its supported
material subset. Review these warnings when exporting imported render materials.

Modern files carry metallic/roughness factors. The legacy path can retain these
as `skppy` compatibility metadata, but that does not make SketchUp 2017 a native
PBR renderer. Use classic color/texture/opacity expectations for that target.

The Python writer is unchanged: baking uses its existing base-texture support.
Native PBR-map writing and renderer-specific export remain deferred. See the
[Material Export Roadmap](material_export_plan.md) for the delivered subset,
historical review, and remaining work.

## Tags, cameras, and text

An object's `skppy_layer_name` string takes precedence over collection mapping.
Otherwise the first collection becomes its SketchUp tag. Collection visibility
initializes tag visibility.

Every exported camera retains its projection, orientation, clipping distances,
field of view, and orthographic height. A timeline marker with a camera becomes
a named SketchUp scene using that camera snapshot.

Font objects retain their body, world position, view direction, material, tag,
visibility, and scalar custom properties. Blender font files and typography do
not map directly to SketchUp's installed font registry, so the modern writer
uses SketchUp's required default font unless the public model is authored with
an explicit registered font.

## Validation

The headless integration suite installs the packaged addon in Blender, exports
a scene containing reusable meshes, a standalone collection source with an
instance offset and nested transforms, smooth, sharp, boundary, and
smooth/flat-transition edges, texture/UV data, PBR state, tags, text,
attributes, and a camera-marker scene, then inspects the result. Separate C
validators open both the modern and SketchUp 2017 Blender-generated files
through the public SketchUp SDK and verify geometry, collection dependency
ordering, edge flags, and container versions.
