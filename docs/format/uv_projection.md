# SketchUp UV Projection

This document explains how SketchUp's texture projection works and how it is
parsed by `skppy`. It covers the binary TLV structure, the projection matrix
math, and the UV computation formula.

## Overview

SketchUp assigns texture coordinates per face through a 3x3 transform. Most
mappings are affine, while legacy projected textures use the homogeneous
coordinate as UVQ. Modern files store the transform in TLV records; pre-ZIP
files store the equivalent `CFaceTextureCoords` object in the face's technical
attribute container.

## TLV Path

```
entity_base (0x07D0)
  \- id_wrapper (0x05DC)
       \- ext_payload (0x05DD)
            \- attr_dicts_root (0x36B1)
                 \- attr_dict (0x36B2)
                      \- tex_proj_pair (0x2710)
                           +- tex_proj_front (0x2711)   <- front-face projection
                           \- tex_proj_back  (0x2712)   <- back-face projection
```

Each side (`0x2711` / `0x2712`) contains a `tex_proj_payload` (`0x2713`) that
holds:

| Tag | Content | Size |
|-----|---------|------|
| `0x2714` | `enabled` flag (compact int, 0 or 1) | variable |
| `0x2715` | projection matrix (9 x `f64`) | 72 bytes |
| `0x2716` | adjacent vector, retained for inspection | 24 bytes |

When `enabled == 0`, the face inherits its UV from its material's default
tiling (untreated planar mapping). When `enabled == 1`, the matrix below is
used.

## The Projection Matrix (tag `0x2715`)

Nine `f64` values are stored **row-major** and represent a **3 x 3 matrix** `M`:

For observed modern files, `M` is a 2-D affine transform stored in row-vector
form:

```
[sx sy 1] = [u_raw v_raw 1] * M
```

where `(sx, sy)` is the point expressed in SketchUp's 2-D face-local basis,
and `(u_raw, v_raw)` is the unnormalised texture-space coordinate in inches.

In the common affine case, `m[2]` and `m[5]` are zero and `m[8]` is one:

```
sx = u_raw * m[0] + v_raw * m[3] + m[6]
sy = u_raw * m[1] + v_raw * m[4] + m[7]
```

`m[6]` and `m[7]` are therefore translation terms in the direct transform,
not a 3-D anchor point to subtract from each vertex.

## UV Formula

Given a vertex at position `P = (px, py, pz)` in local SKP inches:

1. Choose the 2-D face coordinates `(sx, sy)` in the face-local basis:
   - for non-horizontal faces, `s_axis = normalize(cross((0, 0, 1), normal))`
     and `t_axis = cross(normal, s_axis)`
   - `sx = dot(P, s_axis)` and `sy = dot(P, t_axis)`
   - for horizontal faces, the basis falls back to `(x, y)`
2. Invert the 3 x 3 matrix from `0x2715`.
3. Compute:

   [u_raw v_raw q] = [sx sy 1] * inverse(M)
   u = u_raw / (q * W)
   v = v_raw / (q * H)

   where W/H are the material texture width/height in inches. Affine
   transforms have `q == 1`; the division is significant for projected legacy
   textures.

**Important:** Vertex positions must be in the **same coordinate space as the
matrix** - local space, in SketchUp inches. No world transform should be
applied before computing UVs.

### Code Example

```python
from skppy.data_structure.entities import FaceUVProjection

proj = FaceUVProjection(
    transform=[...],  # 9 floats from tag 0x2715
    origin=(0, 0, 0), # 3 floats from tag 0x2716, retained for inspection
)

# Compute UV for a vertex at (10, 20, 0) inches on an XY face
u, v = proj.compute_uv(
    px=10,
    py=20,
    pz=0,
    x_scale=100,
    y_scale=100,
    normal=(0, 0, 1),
)
```

## Role of tag `0x2716`

Tag `0x2716` carries a 3-vector adjacent to the projection matrix. Its role is
not required for UV reconstruction in the observed modern files; for example,
some projected textured faces store `(0, 0, 0)` in that field.
`skppy` stores it in `FaceUVProjection.origin` for inspection but does not use
it in the UV formula.

## Legacy `CFaceTextureCoords`

Pre-ZIP files place `CFaceTextureCoords` among the entries owned by a face's
`CAttributeContainer`. It is a technical entry rather than a named
`AttributeDictionary`; parsers must preserve its archive object identity and
associate it with the owning `CFace`.

Version 4 stores a flags word per side:

- bit `0x01`: the side has an explicit texture transform
- bit `0x02`: the side is projected and the adjacent 3-vector is the
  projection direction

When bit `0x02` is set, SketchUp builds `(sx, sy)` from the projection
direction instead of the face normal. The shared `FaceUVProjection` exposes it
as `projection_direction`. This behavior and the UVQ division were confirmed
against UVQ values returned by the documented SketchUp C API.

## Tag `0x2717` - Texture Control Points

When a user positions a texture on a face, its control points are stored in a
`0x2717` sub-record within the `tex_proj_payload`. Each pin is a pair:

```
0x2718  <- texture control-point record
  0x2719  <- raw texture position (2 x f64, texture-space inches)
  0x271A  <- model position (2 x f64, projected face coordinates)
```

The shared `FaceUVProjection.pins` keeps these pairs as `UVPin` values. The
projection matrix remains the general mapping for the face. When a mesh corner
coincides with a control point, its raw texture position is authoritative and
is divided by the material's physical texture scale before being sent to the
renderer. Control points do not have to coincide with face vertices.

## Degenerate UV Handling

`skppy` falls back to orientation-aware planar UV mapping when the `0x2715`
matrix is singular and cannot be inverted.

## Coordinate System Notes

- SketchUp's internal unit is the **inch** (`1.0 = 1 inch`).
- Blender uses **metres**. The default import scale is `0.0254` (m/inch).
- To convert a Blender-space vertex position back to local inches for UV
  computation, divide by the scale factor: `local_inch = blender_metres / 0.0254`.
- UV computation must stay in local space; applying a group/instance world
  transform before UV computation would yield wrong results.

## Material Texture Scale

The `x_scale` and `y_scale` parameters in `compute_uv()` come from the
material's texture definition:

```python
x_in = mat.texture.x_scale  # texture width in inches
y_in = mat.texture.y_scale  # texture height in inches
```

These values are stored in the `material.xml` file inside the SKP ZIP archive
and represent the real-world size of one texture tile.

### Projection Selection by Effective Material

A per-face projection can still be present when the effective material comes
from a containing group or component instance. The importer must apply that
projection using the inherited material's texture scale; falling back to
planar UVs in this case turns normalized image mappings into tiled mappings.

Blender exposes one material and UV set for both sides of a polygon. When the
same SketchUp material is assigned to both sides but only one side contains a
projection, the importer uses that available projection. This preserves the
visible texture placement instead of discarding it solely because the selected
material reference came from the other side.

`Face.resolve_material_mapping()` defines the shared front/back policy used by
mesh preparation and the Blender addon. An explicit front material wins. The
back material is selected only when the front is unpainted, and an inherited
material is selected only when neither side is painted. A projection from the
opposite side is reused only for the same material; inherited materials may use
either stored projection.

SketchUp's Collada exporter is not an authoritative UV reference for these
cases. An observed export contains separate front/back geometry with a tiled
mapping on one side and a near-one-tile mapping on the other, so the side shown
by a Collada viewer can differ from SketchUp's intended appearance. Visual
verification should use SketchUp or UVQ results from its documented C API.

Compatibility comparisons confirmed that the historical failure was not in
the 3x3 matrix calculation: mesh preparation discarded an applicable
projection after decoding. Keeping the effective side and projection together
prevents that regression for both modern and legacy models.

Projection coordinates may retain an integer tile offset, such as a one-tile
span around `u=-8`. Do not normalize that offset merely to force coordinates
into `0..1`; repeating textures render integer-shifted UVs equivalently, while
removing a non-integer phase changes the intended placement.

## Fallback: Planar UV (`_planar_uv`)

When no projection exists (or when the projection is singular), `skppy`
computes UV by dropping the dominant face-normal axis and dividing the
remaining coordinates by the material texture scale:

- mostly +/-Z normal -> `(x / x_scale, y / y_scale)`
- mostly +/-X normal -> `(y / x_scale, z / y_scale)`
- mostly +/-Y normal -> `(x / x_scale, z / y_scale)`

This produces deterministic UV tiling for faces where no explicit projection
was stored.
