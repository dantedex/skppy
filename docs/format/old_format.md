# Legacy SKP Format (SketchUp 3–2020)

SketchUp save targets from version 3 through 2020 use a pre-ZIP serialized
object graph. SketchUp 2021 and later use the ZIP/VFF container described in
[Modern SKP format](skp_format.md).

This page is the entry point for legacy-format users and contributors. Detailed
wire layouts have been moved into focused references:

| Reference | Contents |
| --- | --- |
| [Container and archive](reference/legacy_container.md) | Header, strings, version map, references, primitive values, and root order |
| [Class catalog](reference/legacy_classes.md) | Class-to-model mapping and schema tables by save generation |
| [Field layouts](reference/legacy_fields.md) | Confirmed entity, material, scene, and rendering fields |

## Evidence and scope

The implementation is an independent interoperability effort based on files
created through documented public APIs, user-owned compatibility samples, and
observable file behavior. These notes are not an official specification.

Every statement in the detailed reference is either:

- confirmed by controlled fixture generation or a cross-version sample;
- required to consume a complete file without losing stream alignment; or
- explicitly marked unknown or inferred.

Unobserved class/schema combinations fail with a specific legacy-format error.
They are not decoded using a nearby layout.

## Identifying the container

Both container families begin with legacy UTF-16 product and version strings.
The bytes immediately after those strings distinguish them:

| Property | Legacy (3–2020) | Modern (2021+) |
| --- | --- | --- |
| Boundary after product/version | 16-byte model identifier | `VFF` marker |
| Main body | Serialized object graph | ZIP containing `model.dat` |
| Per-file schema selection | `CVersionMap` | TLV tags and namespaces |

`skppy.load()` performs this check automatically. File extension and product
text alone are insufficient.

## Parser model

The archive is a graph, not a list of independent records. Class definitions,
class references, object references, and null values share one ordered archive
session. A later entity may point to a vertex, edge, material, definition, or
layer decoded earlier.

The parser therefore has three stages:

1. Read the header and the file's `CVersionMap`.
2. Decode the graph while preserving archive identity and unresolved links.
3. Resolve links into the same public `Model` classes used by the modern
   parser.

Technical archive indexes never become public entity IDs. Public IDs are
allocated during model assembly and references are translated afterward.

## Public model coverage

| Legacy data | Public `skppy` result |
| --- | --- |
| Vertices, edges, loops, faces, curves, arcs | `Entities` geometry |
| Definitions, instances, groups, placed images | Component/entity classes |
| Materials, textures, embedded image data | `Material` and `Texture` |
| Layers and SU2020 layer groups | `Layer` and `LayerFolder` |
| Guides and section planes | Construction entity classes |
| Cameras and saved pages | `Camera` and `Scene` |
| Rendering, shadows, axes, options | Shared model metadata |
| Text, dimensions, fonts, styles | Annotation and style classes |
| Attribute and relationship maps | Public dictionaries and entity relationships |

Parser-only state is retained only when needed for graph identity, unresolved
references, exact payload boundaries, or data without a lossless public owner.

## Version-aware behavior

The file's `CVersionMap` is the primary selector for body layouts. The target
generation is also required for a small number of confirmed down-save
differences, including early construction lines and section-plane names.

Important public capability boundaries include:

| Capability | First confirmed save target |
| --- | --- |
| Entity-owned attribute dictionaries | SketchUp 4 |
| Component-instance names | SketchUp 5 |
| Model-level dictionaries | SketchUp 7 |
| Named section planes | SketchUp 2018 |
| Custom line styles | SketchUp 2019 |
| Layer folders | SketchUp 2020 |
| Generated folder membership retained by current public fixture path | SketchUp 2021 (modern container) |

Older files keep older semantics; the parser does not synthesize a modern
value merely to make versions look alike.

## Validation

The companion [skppy-tests](https://github.com/dantedex/skppy-tests) repository
generates controlled save targets with the documented SketchUp C API and runs
version-aware semantic checks. Focused raw-byte tests cover wire branches that
the public API cannot generate directly.

When adding legacy support:

1. add an independent raw fixture or controlled generated sample;
2. record the schema boundary in the class reference;
3. assert complete payload consumption;
4. verify the resulting public model rather than archive-only state; and
5. reject layouts for which evidence is incomplete.

## Known boundaries

- The legacy writer is intentionally out of scope; `skppy` writes the confirmed
  modern container.
- Some historical runtime-only values have no public model counterpart and are
  consumed without assigning speculative names.
- Interactive-only texture control points are covered by raw fixtures because
  the documented geometry API emits affine projections.
- Embedded thumbnails are metadata and are not treated as model textures.

See the [class catalog](reference/legacy_classes.md) for the supported schema
matrix and [field layouts](reference/legacy_fields.md) for confirmed details.
