# Export Options

The addon registers `export_scene.skp` under **File -> Export -> SketchUp
(.skp)**. It converts Blender data to the public `skppy.Model` graph and writes
either a modern SKP container or a genuine pre-ZIP SketchUp Make 2017 file
without requiring the SketchUp SDK.

The complete model is validated and serialized before the destination is
replaced. A conversion or writer failure therefore leaves an existing output
file untouched.

## Settings

| Option | Default | Behavior |
|--------|---------|----------|
| **File Format** | Modern | Writes the current ZIP-based format or the legacy SketchUp Make 2017 CArchive format. |
| **Objects** | Visible | Export visible objects, selected objects, or every object in the active scene. |
| **Inches per Blender Unit** | 39.37007874 | Converts Blender coordinates to SketchUp's internal inch unit. Use `1` when Blender units already represent inches. |
| **Apply Modifiers** | On | Uses evaluated mesh data with the current modifier stack. Unmodified shared mesh data remains one reusable SKP definition. |
| **Merge Coplanar Faces** | On | Merges adjacent polygons on the same plane when their material and UV projection match. Internal edges are removed and enclosed boundaries become face holes. |
| **Materials and PBR** | On | Preserves Base Color, Alpha, Metallic, and Roughness from the Principled BSDF. |
| **V-Ray Materials** | Off | Generates V-Ray material graphs from Base Color, Alpha, Metallic, and Roughness while retaining the normal SketchUp appearance as a fallback. |
| **Embedded Textures** | On | Embeds packed or file-backed images linked to Base Color. Procedural-only node graphs are not baked. |
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
conversion warnings.

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

By default, the exporter reads the Principled BSDF when available and falls back to the
material's viewport diffuse state. Linked Image Texture nodes are followed
through intermediate nodes. Packed images and existing image files are embedded
in the SKP; generated or procedural images without bytes produce a warning and
leave the material untextured.

Optional material custom properties `skppy_x_scale` and `skppy_y_scale` set the
physical texture tile size in SketchUp inches. Both default to `1.0`.

### Enscape Materials (Experimental)

This opt-in setting writes Enscape metadata in both modern and 2017 SKP files.
It cannot be enabled together with **V-Ray Materials**. Disable **Materials
and PBR** to disable both renderer options.

The Enscape adapter follows the active Material Output's direct Principled
surface connection, including renamed shaders. It copies base color, alpha,
metallic, roughness, specular IOR level, IOR, transmission, emission color and
emission strength. Materials without nodes use their viewport appearance
(Blender 4.5); Blender 5.2's node-based materials use their active shader.
Colors are converted from Blender's linear values to serialized sRGB bytes.

Base-color Image Textures are supported with a static sRGB image,
flat/repeating mapping, linear interpolation and the active UV coordinates.
Image alpha may connect directly to Principled Alpha, or through multiplication
by a constant opacity. Transparent image pixels require that alpha connection.
Packed or file-backed bytes are embedded when **Embedded Textures** is enabled;
unavailable bytes cause an error in this mode.

The importer-created diffuse adjustment chain is also supported:

`Image → Invert → Multiply brightness/tint → Mix with base color → Principled`

Each adjustment is optional. Invert must use full strength; up to two MixRGB
Multiply nodes must use factor `1` and constant color multipliers. An optional
outer MixRGB Mix node supplies the constant base color and image-fade factor.
Clamping, alpha-dependent factors, linked multipliers and other operation
orders are rejected. Node labels do not affect recognition. Equal RGB
multipliers are combined into brightness, so neutral tints may be represented
by an equivalent brightness value. Other tint colors use Enscape's 8-bit sRGB
representation. Image pixels and their separate alpha are left unchanged.

This option is stricter than the default exporter: unsupported base-color
graphs outside this chain, auxiliary maps, UV
transforms, linked scalar inputs, alternate surface shaders, volume and
displacement graphs cause an error before replacing the destination. Coat,
sheen, subsurface, anisotropy, thin film, thin-wall settings and diffuse
roughness are not translated. RGB values outside `[0, 1]` are rejected; use
emission strength for high intensity. Glass plus emission, or independent
alpha plus transmission, are also rejected by the writer.

Independent tests exercise Blender 4.5/5.2 and check the resulting files through
the SketchUp SDK. This proves file and metadata readability, not Enscape
rendering parity. See {ref}`enscape-export-coverage` for the Python writer's
separate supported subset.

### V-Ray Materials

When **V-Ray Materials** is enabled, the exporter adds a deterministic
`MtlSingleBRDF` -> `BRDFVRayMtl` graph to every exported material. Base colour
is converted from sRGB to V-Ray's linear colour representation; opacity,
metallic, and roughness remain normalized factors. The graph targets the V-Ray
metadata generation observed for each output container: plugin version 23 for
modern SKP and version 16 for SketchUp Make 2017.

The ordinary SketchUp material and native PBR block are always written too, so
SketchUp and importers without V-Ray retain a useful appearance. An embedded
base-colour image is also connected through a V-Ray `TexBitmap`,
`BitmapBuffer`, and `UVWGenChannel` graph. The bitmap uses the same embedded
image basename and face UV channel as the native SketchUp texture.

The export material subset is Base Color, Alpha, Metallic, Roughness, and the
base-color image. Import support for renderer maps does not imply export
support for those maps. The Python writer rejects unsupported public material
properties rather than silently discarding them; it also rejects duplicate
material names. V-Ray export does not broaden this subset.
The Blender adapter reports omitted renderer maps, non-default IOR/specular,
emission, and displacement as conversion warnings before returning its supported
material subset. Review these warnings when exporting imported render materials.

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
