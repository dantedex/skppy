# Material Export Roadmap

**Status: graph analysis, basic shader adapters, and opt-in color/alpha baking
are delivered as a bounded subset.** [Export Options](export_options.md) is the
user-facing contract. Native PBR maps, broader shader conversion, and
Enscape/V-Ray export remain deferred. The Python writer is unchanged.

## Historical review findings

The original documentation review identified the following problems in the
pre-baking adapter. These are historical findings, not a description of today's
implementation:

- `_material_state()` in `export_builder.py` selected a node named `Principled
  BSDF`, even if disconnected. Renaming could cause viewport fallback. This is
  replaced by active Cycles/ALL output discovery and shader-type analysis.
- `_linked_image()` searched upstream for the first image without evaluating
  color operations or mapping. Direct transfer now requires a compatible image
  and matching UVs; other supported color/alpha expressions can be baked.
- `_image_bytes()` copied packed/file bytes rather than current pixels.
  Generated/dirty images now require the optional bake path, not direct transfer.
- Exported active UVs could differ from shader UVs, and independently linked
  Alpha was not evaluated. UV compatibility is now checked, and optional baking
  evaluates color and scalar Alpha into one RGBA texture.
- Omission reporting was incomplete. The analyzer now explicitly warns about
  unsupported channels and closure approximations. A successful export still
  does not prove general visual equivalence.

Multiple Blender material slots already exported as face assignments; this is
not the same as supporting multiple shader closures within one material.

The review's writer finding remains current: the public `Material` model has
more import fields than the writer can serialize. `skppy/writer/materials.py`
writes base color, one base texture, opacity, and metallic/roughness factors.
`skppy/_material_validation.py` rejects unsupported maps/renderer fields.
That explicit-failure contract has not been relaxed.

## Delivered conversion policy

Analyze first, copy compatible direct images where possible, and bake only
supported color/alpha expressions when explicitly enabled. No arbitrary
upstream-image selection or general BSDF parameter averaging is performed.

| Control | Delivered behavior |
| --- | --- |
| Bake Procedural Color and Alpha (`bake_materials`) | Off by default (`False`); requires materials, embedded textures, and UV export. |
| Bake Resolution (`bake_resolution`) | 1024; integer [16, 4096], square image dimensions. |
| Bake Margin (`bake_margin`) | 16 pixels; integer [0, resolution]. |
| Evaluation | Synchronous CPU Cycles; no modal progress/cancellation guarantee or device selector. |
| UV policy | Existing active, finite, nondegenerate, non-overlapping UV triangles inside 0–1; no automatic unwrap. Source object must be in Object mode. |
| Unsupported appearance | Explicit warnings and documented approximations/socket defaults; no strict-mode selector. Bake validation/evaluation errors abort. |
| Reporting | Completion warning count, all warnings printed to the console, first three shown by the operator. No full structured conversion report yet. |

### Shader handling matrix

| Source | Delivered treatment |
| --- | --- |
| Single Principled | Base Color and Alpha, constant Metallic/Roughness. Node names are irrelevant. |
| Compatible direct Image Texture | Packed/file-backed, unmodified sRGB/straight-alpha bytes; flat/repeat mapping matching exported active UVs. |
| Reroutes | Follow actual socket links for supported closure and image paths. |
| Color ramps, math/mixes, procedural textures, color-expression groups | Optional color/alpha baking; baking off uses warned socket defaults for unrepresented expressions. |
| Diffuse BSDF | Opaque color/roughness, metallic 0. |
| Glossy / Anisotropic BSDF | Metallic 1 color/roughness approximation, explicitly warned as not physically equivalent. |
| Translucent / Glass / Refraction BSDF | Opaque color/roughness approximation; transmission loss warned, not mapped to alpha. |
| Transparent BSDF | Constant white gives alpha 0; tinted/linked color becomes a warned opaque approximation. |
| Emission | Color approximation only; energy/strength loss warned. |
| Shader-closure groups, Mix Shader, Add Shader, other closures | Warned viewport fallback, even with baking enabled. |
| Volume output | Warned viewport fallback. |
| Normal/bump, displacement, IOR/specular, transmission, subsurface, coat/sheen, emission energy | Unsupported behavior reported; no lossless promise. |

## Phase 1 — Graph analysis: delivered subset

`export_materials.py` resolves the active Material Output for Cycles, accepting
Cycles/ALL targets. It warns if Eevee chooses a different output. The connected
surface is identified by node type through reroutes, not by its display name;
disconnected Principled nodes are not selected just because of their name.
Missing/incompatible outputs and unsupported closure graphs use a warned
viewport fallback.

`SurfaceState` separates analysis from public model creation, retaining exact
top-level color/alpha destination sockets for baking. Color-expression groups
are preserved for Cycles evaluation, but shader-closure group traversal and
general Mix/Add closure analysis are **not delivered**. Linked Metallic and
Roughness still use socket defaults with explicit warnings, not evaluated maps.

## Phase 2 — Opt-in color and opacity baking: delivered subset

A representative supported case is:

```text
Generated -> Mapping -> Noise Texture -> Color Ramp -> Principled Base Color
Noise Texture -> Map Range -------------------------> Principled Alpha
Principled BSDF ------------------------------------> Cycles/ALL Output Surface
```

Noise/Voronoi/Brick/Checker, ramps, and supported math/color mixes are evaluated
by Blender, not reimplemented in Python. Adding a procedural Roughness input
does not make it exportable: it remains a warned socket-default approximation.
Procedural Roughness alone does not force a color bake.

### Bake job and alpha semantics

1. Use the final export mesh (evaluated when requested) and copy it, the object,
   and material into an isolated temporary scene. Keep the current frame/subframe.
2. Require an existing active destination UV map. Preserve source UV layers and
   coordinate semantics rather than replacing them with an automatic unwrap.
3. Add a disconnected active Image Texture bake target to copied materials.
   Route the original color expression through strength-1 Emission and bake
   the Emit pass with CPU Cycles. This is unlit color, not a Combined render.
4. Evaluate the original Alpha destination as a clamped scalar in a second
   emission pass, preserving Blender's color-to-scalar conversion. Combine
   complete color and alpha into one straight-alpha RGBA PNG: sRGB RGB, linear
   coverage alpha, no AgX/display look baked into the pixels.
5. Embed through the existing `skppy.Texture` path. Set exported color to white
   and opacity to 1 because the baked pixels already include those inputs.
   Keep constant metallic/roughness factors separately.
6. Remove temporary scene, objects, meshes, materials, and images on success or
   exception. Source images/preferences are not overwritten. Export executes
   synchronously; cleanup on errors is not a cancellation guarantee.

For direct images, intrinsic alpha is preserved only when the same Image
Texture's Alpha output drives the shader Alpha input. Otherwise the color
image is made opaque if necessary and shader scalar opacity stays separate.
Unused image alpha and the fourth color component do not imply coverage.
Glass/transmission is never treated as equivalent to surface opacity.

### Boundaries, variants, and failures

- Destination UV triangles must be finite, nondegenerate, non-overlapping,
  and inside [0, 1]. Boundary contact is allowed; overlapping interiors are
  rejected. Validation has a bounded candidate-work budget and can reject
  overly complex UV layouts. There is no automatic unwrap.
- Baked polygons must have nonsingular, affine per-face UV projections.
  Non-affine baked polygons are rejected: triangulate before export. Ordinary
  unbaked materials can still receive UV-fitting warnings/approximations.
- Context-dependent nodes are rejected, including Object Info, Camera Data,
  Light Path, Shader to RGB, particle/hair information, unsafe Geometry outputs,
  and camera/window/reflection/normal or instancer coordinates. Drivers on
  materials/node trees and inspected expression groups are rejected, as are
  sequence, movie, and tiled/UDIM images. This is not a promise to support every
  Cycles node or external shader implementation.
- Baking creates per-object/material variants and separate affected component
  definitions, even when objects share mesh/material data. This conservatively
  prevents cross-object procedural-pattern reuse but increases time, memory,
  texture count, and file size. Proven object-independent bake reuse and atlasing
  are not implemented. Direct compatible materials retain normal reuse.
- Cycles failures and invalid bake inputs abort without an unrelated-image
  fallback. Conversion finishes before `Model.save()`; validation/serialization
  finishes before replacement. Errors leave an existing destination intact.

## Phase 3 — Verified native PBR maps: deferred

The public SketchUp material API documents metallic, roughness, normal, and AO
texture support from SketchUp 2025 (API 13.0), including single-channel 8-bit
scalar maps, three-channel 24-bit normals, normal scale, and OpenGL/DirectX
convention. Destination APIs do **not** establish an implemented wire layout
or compatibility with every older modern-format reader.

Before enabling these exports:

- Produce applied-material public-SDK fixtures one channel at a time and
  establish target-version resource/serialization behavior.
- Add independent raw writer expectations and strict SDK output validators.
- Extend the public model where needed (including AO and normal convention),
  then relax validation only for verified fields.
- Negotiate capabilities separately from the modern/2017 container switch.
  A modern container alone does not guarantee PBR-map support.

Acceptance must check enable flags, factors, embedded dimensions/pixels,
normal scale/convention, AO strength, UVs, and version fallback. Use materials
applied to faces: unused-material normalization is not a correctness oracle.
SketchUp 2017 remains classic color/texture/opacity; legacy `skppy` PBR
compatibility metadata does not make it a native PBR renderer.

## Phase 4 — Broader channels, closures, and workflow: remaining work

- Metallic/roughness map baking and tangent-space normals depend on Phase 3.
  Verify tangent basis, UV orientation, negative transforms, normal convention,
  and bump conversion. AO must be optional, not silently multiplied into color.
  Geometry displacement needs its own mesh-export policy.
- Expand shader adapters only for explicit tested cases. Closure groups and
  restricted Mix Shader/Transparent coverage patterns remain future work;
  interpolating parameters is not generally equivalent to mixing BSDFs.
- Export-only automatic unwrap, safe object-independent bake caching, atlasing,
  memory/image-count budgets, strict approximation policy, target-capability UI,
  device selection, structured reporting, progress, and cancellation remain
  proposals, not current settings.
- Renderer-specific metadata preservation/export is separate from native
  material fidelity; Enscape and V-Ray export remain deferred.

## Validation and documentation

The implementation includes live Blender scenarios in
`tests/blender/export_shader_analysis.py`, `export_material_baking.py`, and
`export_material_integration.py`, integrated by `run_integration.py`. Graph
selection, independent expected color/alpha pixels, UV/input rejection,
per-object variants, direct images, and failure cleanup are relevant checks.
Their presence does not substitute for running the required parent gates on
supported Blender versions; cancellation support is not claimed.

Keep the supported-channel matrix, warnings, UV/cost limits, and real UI
screenshots synchronized with implementation. Source-versus-export material
comparisons should supplement numerical checks, not replace them. Future
serialized-map changes also require independent public-SDK fixtures and
producer/validator pairs in the conformance suite, rather than relying only
on writer-to-parser agreement.
