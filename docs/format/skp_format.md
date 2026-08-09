# SKP File Format Reference

This document describes the modern ZIP/VFF `.skp` format emitted by SketchUp
2021 and later in the observed save-version matrix. For the earlier CArchive format, see
[Old Binary Format](old_format.md).

The authoritative machine-readable tag map is in [`../skp_tags.yaml`](../skp_tags.yaml).

## Container Layout

An `.skp` file is a ZIP archive preceded by a text header:

```
+-------+
|  Text Header (UTF-16-like bytes)    |
|  - "SketchUp Model"                 |
|  - Version string "{major.minor.build}" |
+-------+
|  ZIP Archive                        |
|  +- model.dat        (required)    |
|  +- meta/meta.dat    (optional)    |
|  +- styles/*/style.xml             |
|  \- materials/*/                   |
|      +- material.xml               |
|      \- <texture files>            |
\-------+
```

### Text Header

- Begins with a UTF-16LE-prefixed product string (`"SketchUp Model"`).
- Followed by a version string like `"{21.0.0}"`.
- The ZIP payload starts at the first `PK\x03\x04` signature.

### ZIP Entries

| Entry | Required | Description |
|-------|----------|-------------|
| `model.dat` | Yes | Binary TLV stream containing the model graph |
| `meta/meta.dat` | No | Model metadata |
| `styles/*/style.xml` | No | Visual style definitions |
| `materials/*/material.xml` | No | Material definitions (XML) |
| `materials/*/<textures>` | No | Texture image files |

`model.dat` is typically stored with deflate compression (method = 8).

## `model.dat` - TLV Encoding

`model.dat` is a binary **Tag-Length-Value** (TLV) stream. Records are nested
recursively.

### Record Layout

```
+--+--+----+
|  tag     |  length  |  payload        |
|  u16 LE  |  u32 LE  |  length bytes   |
\--+--+----+
```

- **tag** (`u16` little-endian): Identifies the record type.
- **length** (`u32` little-endian): Byte count of the payload.
- **payload**: Either raw data or nested TLV children.

### Top-Level Structure

The file always begins with a single root record:

| Tag | Name | Description |
|-----|------|-------------|
| `0x01F4` | `model_root` | Root container for the entire model |

### Primitive Payload Conventions

| Payload Size | Typical Type | Examples |
|-------------|-------------|----------|
| 1 byte | Boolean / byte flag | `0` or `1` |
| 4 bytes | `i32` / `u32` | IDs, enums, bitmasks |
| 8 bytes | `f64` / `i64` | Distances, angles, scales |
| 16 bytes | 2 x `f64` | UV coordinates |
| 24 bytes | 3 x `f64` | Points, vectors, axes (xyz) |
| 32 bytes | 4 x `f64` | Plane equation (abcd) |
| 48 bytes | 6 x `f64` | Bounding box (min/max triplets) |
| 72 bytes | 9 x `f64` | 3x3 projection matrix |
| 104 bytes | 13 x `f64` | Transform (see below) |

### Variable-Length Integers

Many IDs, counters, and references are stored as **compact little-endian
integers** (1-4 bytes depending on value range). A value like `6` may occupy
a single byte, while larger values use 2, 3, or 4 bytes.

### ID Encoding

IDs are commonly wrapped in a two-level structure:

```
0x05DC (id_wrapper)
  \- 0x05DE (id_value) -> compact little-endian integer
```

Some records use an extended payload form:

```
0x05DC (id_wrapper)
  +- 0x05DD (id_extended_payload) -> nested TLV blob
  \- 0x05DE (id_value) -> compact little-endian integer
```

## Root Tag Map (`0x01F4` Children)

The root record contains these top-level blocks:

| Tag | Name | Description |
|-----|------|-------------|
| `0x0063` | `legacy_version_marker` | Legacy version marker (u32, observed 0) |
| `0x01F5` | `model_id_counter_block` | ID counter seed |
| `0x01F6` | `entities_block` | Root-level entities (vertices, edges, faces, instances, etc.) |
| `0x01F7` | `materials_block` | Material definitions |
| `0x01F8` | `layers_block` | Layers and layer folders |
| `0x01F9` | `component_definitions_block` | Component definitions |
| `0x01FA` | `model_camera_block` | Model camera snapshot |
| `0x01FB` | `rendering_options_block` | Rendering/display options |
| `0x01FC` | `model_view_settings_block` | Sketch axes / coordinate system |
| `0x01FD` | `fonts_block` | Font definitions |
| `0x01FE` | `text_style_block` | Text style defaults |
| `0x01FF` | `dimension_style_block` | Dimension style defaults |
| `0x0200` | `options_manager_block` | Named options providers |
| `0x0203` | `watermarks_block` | Watermark definitions |
| `0x0204` | `shadow_info_block` | Shadow/geo-reference settings |
| `0x0205` | `active_schemata_block` | Active schema zip-file references |
| `0x0206` | `styles_registry_block` | Visual styles registry |
| `0x0207` | `scenes_block` | Saved scenes/pages |
| `0x0208` | `line_styles_block` | Custom line styles |
| `0x0209` | `model_properties_block` | Attribute dictionaries |
| `0x020A` | `metadata_path_entry` | Path to `meta/meta.dat` |
| `0x020C` | `use_mipmaps_flag` | Mipmap usage flag |
| `0x020D` | `section_plane_name_index_seed` | Section plane naming counter |
| `0x020E` | `component_behavior_defaults_block` | Default component behaviors |
| `0x020F` | `default_image_reference_state` | Default image reference |
| `0x0210` | `environment_data_block` | Environment/lighting data |
| `0x0213` | `sun_data_block` | Sun data |
| `0x0214` | `face_reversal_migration_done_flag` | Migration flag |

## Entities (`0x01F6`)

The entities block (`0x1388`) contains all geometric and non-geometric objects
in the model.

### Entity Sub-Blocks

| Tag | Name | Description |
|-----|------|-------------|
| `0x1389` | `vertices` | Vertex positions |
| `0x138A` | `edges` | Edge connectivity |
| `0x138B` | `faces` | Face geometry with loops |
| `0x138C` | `component_instances` | Component instance placements |
| `0x138D` | `groups` | Group instances |
| `0x138E` | `drawing_elements_ref_pid_container` | Drawing element references |
| `0x1390` | `images` | Image entities |
| `0x1391` | `guide_lines` | Construction guide lines |
| `0x1392` | `guide_points` | Construction guide points |
| `0x1393` | `section_planes` | Section plane entities |
| `0x1394` | `active_section_plane_ref` | Active section plane reference |
| `0x1396` | `curves` | Polyline curves |
| `0x1397` | `arc_curves` | Arc curves |
| `0x1399` | `dimensions` | Dimension entities |
| `0x139B` | `entities_metadata_block` | Entity metadata |
| `0x139D` | `openings` | Opening entities |
| `0x139E` | `entities_sentinel` | Sentinel marker |
| `0x139F` | `component_state_flags` | Component state bitfield |
| `0x13A0` | `definition_entities_bounds` | Bounding box for definition entities |

### Vertices

Each vertex record (`0x09C4`) contains:

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x05DC` -> `0x05DE` | compact int | Vertex ID |
| `0x09C5` | 3 x f64 | Position (x, y, z) in inches |

### Edges

Each edge record (`0x0BB8`) contains:

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x07D0` | nested | Entity base (IDs, flags) |
| `0x0BB9` | compact int | Start vertex ID |
| `0x0BBA` | compact int | End vertex ID |
| `0x0BBB` | compact int | Optional curve ID |

The entity base can include `0x07D1` for a material reference, `0x07D2` for
the owning layer/tag, and `0x07D3` for the compact integer edge flag bitfield.
Raw modern bits are `0x01` hidden, `0x02` casts shadows, `0x04` receives
shadows, `0x08` soft, and `0x10` smooth. Public `Edge.flags` normalizes the
three edge properties to `0x01`, `0x02`, and `0x04` respectively.
See [Edge Shading Flags](edge_shading.md) for how these flags map to importer
normal smoothing.

### Faces

Each face record (`0x0DAC`) contains:

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x07D0` | nested | Entity base (ID, front material, layer/tag, flags) |
| `0x0DAD` | 4 x f64 | Plane equation (a, b, c, d) |
| `0x0DAE` | nested | Loop container |
| `0x0DAF` | compact int | Back-material ID |

Loops (`0x0DAE`) contain repeated loop records (`0x1194`), each with edge-use
entries (`0x1195` -> `0x0FA0`):

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x0FA1` | compact int | Edge ID |
| `0x0FA2` | bool | Reversed flag |

Hole faces are represented as multiple loop records within the same face.

### Component Instances, Groups, and Images

All three share a common `0x1964` instance record structure:

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x07D0` | nested | Entity base |
| `0x1965` | UTF-8 string | Name (optional) |
| `0x1966` | 13 x f64 | Transform matrix |
| `0x1967` | compact int | Definition ID |
| `0x1968` | 16 bytes | GUID-like blob |

**Transform encoding** (`0x1966`): 13 doubles in SketchUp `SUTransformation`
storage order:

```
[m00, m01, m02, m10, m11, m12, m20, m21, m22, tx, ty, tz, w]
```

To reconstruct a row-major 4x4 matrix:

```python
matrix = [
    [m00, m01, m02, tx],
    [m10, m11, m12, ty],
    [m20, m21, m22, tz],
    [0.0, 0.0, 0.0, w],
]
```

- Component instance: `0x138C` -> `0x1964`
- Group: `0x138D` -> `0x1D4C` -> nested `0x1964`
- Image: `0x1390` -> `0x1F40` -> nested `0x1964`

### Curves

| Tag | Name | Description |
|-----|------|-------------|
| `0x1396` | `curves` | Container -> `0x4A38` records |
| `0x4A39` | `edge_count` | Number of edges in curve |
| `0x4A3A` | `curve_polygon_flag` | Polygon flag |
| `0x4A3B` | `first_edge_id` | First edge ID |
| `0x4A3C` | `last_edge_id` | Last edge ID |

### Arc Curves

`0x1397` -> `0x4C2C` contains a nested `0x4A38` curve record plus arc-specific
payload `0x4C2D`. The payload is 16 little-endian `float64` values: center (3),
unit normal (3), plane distance (1), radius-scaled X axis (3), radius-scaled Y
axis (3), radius (1), start angle (1), and end angle (1). Curve and arc-curve
sections precede `EDGES`; the public SDK rejects an edge-to-curve reference when
the owning curve section is serialized afterward.

### Section Planes

`0x1393` -> `0x445C` with plane (`0x445D`), name (`0x445E`), and symbol
(`0x445F`).

### Construction Guides

Guide lines use `0x1391` -> `0x4269`. Their `0x4268` field contains a nested
entity base, `0x426A` stores a point, a unit direction, and two parameter
bounds as eight doubles, and `0x426B` stores a u16 stipple pattern. Infinite
lines use bounds `-1e30` and `+1e30`.

Guide points use `0x1392` -> `0x426C`, with the same nested construction/entity
base, position `0x426D`, optional reference position `0x426E`, and its enable
flag `0x426F`. Construction and section entities carry layer ownership in the
entity-base `0x07D2` field.

### Dimensions

Linear dimensions use `0x1399` -> `0x5BCC` with base data (`0x59D8`) and
anchor records (`0x5BCD`, `0x5BCE`). Each anchor contains a `0x5208` point
reference: kind `0x5209`, position `0x520A`, and primary/secondary association
wrappers `0x520B`/`0x520C`. An association wrapper `0x53FC` contains an
optional leaf entity ID `0x53FD` and a width-prefixed outer-to-inner instance
path in `0x53FE`.

These records map to the same public `LinearDimension` and `PointReference`
classes used for legacy files. The parser retains text, font reference, 3-D
text and arrow settings, anchors, direction vectors, mode, offset, alignment,
and dimension-line position.

Radial dimensions use `0x139A` -> `0x5DC0`, with the same common dimension
base, associated target ID `0x5DC1`, curve parameter `0x5DC3`, radius ratio
`0x5DC4`, and diameter boolean `0x5DC5`. Modern writer conformance covers the
associated form. The parser also retains historical inline arc payloads in
`0x5DC2`; no accepted modern writer representation for orphaned arcs has been
confirmed.

### Openings

`0x139D` -> repeated `0x7530` records with origin, axes, and flags.

## Materials (`0x01F7`)

Binary structure:

```
0x01F7 -> 0x30D4 -> 0x30D5 -> repeated 0x32C8 (material records)
```

Each material record (`0x32C8`) contains:

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x32CA` | bool | Record context: global (`0`) or layer-embedded (`1`) |
| `0x32CB` | blob | Texture payload |
| `0x32CC` | UTF-8 string | Material name |
| `0x32CD` | compact int | Optional auxiliary value; semantics unconfirmed |

`0x30D6` holds the current/active material reference.

Texture, opacity, color, and PBR appearance come from the optional material XML.
When that resource is absent or invalid, the parser retains TLV identity/name
and uses neutral appearance defaults.

### Material XML

Rich material data is stored in `materials/<name>/material.xml` inside the ZIP:

```text
<mat:material name="Brick" type="..." workflow="..."
             colorRed="180" colorGreen="80" colorBlue="60"
             trans="0" useTrans="0" hasTexture="1">
  <mat:texture textureFilename="brick.jpg" xScale="100" yScale="100">
    <mat:image path="..." file_name="brick.jpg"/>
  </mat:texture>
  <mat:pbrMR enable_metalness="0" enable_roughness="1"
             roughnessFactor="0.5" .../>
</mat:material>
```

## Layers (`0x01F8`)

```
0x01F8 -> 0x3A98
  +- 0x3A99: layer list -> repeated 0x3C8C
  +- 0x3A9A: active layer ID
  \- 0x3A9B: folder tree -> anonymous 0x3E80 root -> public 0x3E80 nodes
```

Layer record (`0x3C8C`):

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x05DC` | nested | ID wrapper |
| `0x3C8D` | UTF-8 string | Layer name |
| `0x3C8E` | bool | Visible flag |
| `0x3C8F` | nested | Inline `0x32C8` layer display material; compact ID in early variants |
| `0x3C90` | bitmask | Scene behavior flags |
| `0x3C91` | compact int | Custom line style reference |

Folder nodes (`0x3E80`) can nest through `0x3E83`. Their `0x3E84` membership
payload is a packed sequence: each layer ID is preceded by a one-byte width
(1-4), followed by the little-endian ID bytes.

## Component Definitions (`0x01F9`)

```
0x01F9 -> 0x1770 -> 0x1771 -> repeated 0x157C
```

Definition record (`0x157C`):

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x07D0` | nested | Definition base (contains ID) |
| `0x1388` | nested | Definition-local entities |
| `0x157D` | 16 bytes | GUID blob |
| `0x157E` | UTF-8 string | Name |
| `0x157F` | UTF-8 string | Description |
| `0x1580` | UTF-8 string | Loaded-from path |
| `0x1581` | compact int | Timestamp |
| `0x1582` | bool | Modified flag |
| `0x1583` | compact int | Definition type |
| `0x1585` | nested | Packed payload (thumbnail, etc.) |
| `0x1B58` | nested | Component behavior defaults |

The instance-to-definition join uses `0x1967` (instance) matching the
definition ID inside `0x157C` -> `0x07D0` -> `0x05DC` -> `0x05DE`.

## Camera (`0x01FA`)

```
0x01FA -> 0x34BC
```

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x34BD` | 3 x f64 | Eye position |
| `0x34BE` | 3 x f64 | Target position |
| `0x34BF` | 3 x f64 | Up vector |
| `0x34C0` | f64 | Near clipping distance |
| `0x34C1` | f64 | Far clipping distance |
| `0x34C2` | bool | Perspective flag |
| `0x34C3` | f64 | Orthographic height |
| `0x34C4` | f64 | Perspective FOV |
| `0x34C5` | f64 | Aspect ratio |
| `0x34C6` | bool | FOV-is-height flag |
| `0x34C7` | bool | Legacy camera flag |
| `0x34C8` | UTF-8 string | Description |
| `0x34C9` | f64 | Image width |
| `0x34CA` | bool | 2D camera flag |
| `0x34CB` | f64 | 2D scale |
| `0x34CC` | f64 | 2D center X |
| `0x34CD` | f64 | 2D center Y |
| `0x34CE` | bool | Allow clipping in parallel projection |

## Rendering Options (`0x01FB`)

```
0x01FB -> 0x733C
```

Contains ~50+ fields controlling display: render mode, transparency, edge
display, colors (background, foreground, highlight, face front/back, fog, sky,
ground, section cuts), fog settings, ambient occlusion, photomatch, and legacy
compatibility flags.

Section display record `0x7375` is a bitmask shared with legacy rendering
options. Bit `0x1` controls section-plane visibility and bit `0x2` controls
section-cut visibility. The public model exposes these as
`display_section_planes` and `display_section_cuts` while preserving the raw
`section_display_mode` value.

## Scenes (`0x0207`)

```
0x0207 -> 0x6D60 -> 0x6D61 -> repeated 0x7148
```

Each scene record contains:

| Tag | Description |
|-----|-------------|
| `0x6F54` | Base scene (ID, name, description) |
| `0x7149` | Flags |
| `0x714A` | Camera snapshot |
| `0x714B` | Hidden entity IDs |
| `0x714C` | Style reference |
| `0x714D` | Rendering options snapshot |
| `0x714E` | Shadow info snapshot |
| `0x714F` | Axes snapshot |
| `0x7150` | Hidden layer IDs |
| `0x7151` | Active section plane IDs |
| `0x7152` | Show in slideshow |
| `0x7154`-`0x7155` | Transition/delay overrides |
| `0x7156` | Background image reference |
| `0x7158` | Thumbnail image |
| `0x7159` | Hidden layer folder IDs |
| `0x715A`-`0x715B` | Environment reference/settings |
| `0x715C` | Foreground image IDs |

The ID stored in the base scene is preserved. Camera snapshots are decoded to
the same public `Camera` class used by model-level cameras. Collections such as
hidden entities, hidden layers, and active section planes use repeated scalar
TLV records; each repeated record contributes one public reference ID.

## Shadow Info / Geo-Reference (`0x0204`)

```
0x0204 -> 0x6590
```

| Tag | Payload | Description |
|-----|---------|-------------|
| `0x6591` | compact int | Time |
| `0x6592` | bool | Daylight savings |
| `0x6593` | raw | City name |
| `0x6594` | compact int | Country |
| `0x6595` | f64 | Longitude (degrees) |
| `0x6596` | f64 | Latitude (degrees) |
| `0x6597` | f64 | Timezone offset |
| `0x6598` | 3 x f64 | North direction |
| `0x6599`-`0x65A0` | various | Display flags, light/dark settings |

## Attribute Dictionaries (`0x0209`)

```
0x0209 -> 0x36B1 -> 0x36B2 (dictionary records)
```

Each dictionary contains:

| Tag | Description |
|-----|-------------|
| `0x36B4` | Dictionary name |
| `0x36B5` | Entries -> `0x36B6` (key) + `0x38A4` (typed value) |

Typed values (`0x38A4`) carry a type code (`0x38A7`) and one of:
- `0x38A8`: int32 payload
- `0x38A9`: f64 payload
- `0x38AA`: bool payload
- `0x38AD`: string payload
- `0x38AE`: nested blob

The same dictionary root can appear inside an entity's `0x05DD` extended ID
payload. Named records are exposed through
`Entities.attribute_dictionaries_by_entity_id`; definition, material, and layer
records use `Model.attribute_dictionaries_by_object_id`. Technical records in
that root, including texture projections, are handled separately and do not
become empty named dictionaries.

Texture projection data is also stored in attribute dictionaries; see
[UV Projection](uv_projection.md).

## Physical Units

- **Geometric lengths**: stored in SketchUp internal units (inches).
- **Lat/long**: degrees (f64).
- **Camera FOV/legacy scalar**: radians.
- **Colors**: 4-byte packed ARGB (u32, little-endian).
- **Timestamps**: compact integer (epoch-like semantics).

## Parser Gotchas

1. **Not all payloads are nested TLV.** Fixed-size numeric blobs (24, 32, 104
   bytes) can accidentally look like valid tags if decoded heuristically.
2. **Pseudo-tags** like `0x0000` and some `0x40xx` values may appear from raw
   f64 geometry payload bytes - always parse based on known tag semantics.
3. **Variable-length IDs** must be supported (not fixed u32 only).
4. **Legacy (non-ZIP) SKP files** cannot be read through the `model.dat` ZIP
   extraction path.

## Tag Coverage

The tag map in [`../skp_tags.yaml`](../skp_tags.yaml) covers:

- **422** mapped tags
- **298** leaf tags with explicit payload/type annotations
- **124** container-only tags (no payload type)

Inference basis: analysis of observed `.skp` files with cross-check against
record lengths and value distributions.
