# Edge Shading Flags

SketchUp stores soft/smooth display intent on `Edge` entities, not directly on
faces. The observed modern TLV path is:

```text
entities (0x1388)
  edges (0x138A)
    edge record (0x0BB8)
      entity base (0x07D0)
        entity flags (0x07D3)
```

`0x07D3` is a compact integer bitfield. The bits relevant to edge display are:

| Bit | Name | Meaning |
|-----|------|---------|
| `0x01` | hidden | Edge is hidden from normal display |
| `0x02` | casts shadows | Generic drawing-element shadow state |
| `0x04` | receives shadows | Generic drawing-element shadow state |
| `0x08` | soft | Edge is softened |
| `0x10` | smooth | Adjacent faces may share smoothed normals across the edge |

The normal visible drawing-element baseline is `0x06`. Smoothed cylindrical
geometry, for example, can use `0x1E` on longitudinal edges (`0x08 | 0x10`
plus the baseline) and `0x06` on hard circular boundaries.

The public `Edge.flags` field intentionally uses a normalized three-bit layout:
`0x01` hidden, `0x02` soft, and `0x04` smooth. Parsing and writing translate
between that public representation and the modern wire bits above.

## Curved-Surface Behavior

Both edge classes carry the public `smooth` bit (`0x04`). The visual behavior
is still not "smooth every flagged edge": vertical edges should shade smooth
between neighboring side faces, while horizontal ring edges should remain a
hard break between side faces and the top/bottom caps.

The importer therefore treats the SKP smooth bit as permission to smooth, then
checks adjacent face normals. If the dihedral angle is above the smoothing
threshold, the edge remains sharp. With the current 40 degree threshold:

- side-to-side cylinder edges (~15 degrees) shade smooth
- cap-to-side ring edges (90 degrees) shade flat/sharp

Generated triangulation diagonals do not correspond to SKP edges and should not
be treated as source edge-shading instructions.

## Importer Mapping

`Entities.prepare_mesh()` carries source edge IDs and flags into
`PreparedFace`. `PreparedMesh.to_indexed()` preserves that data in
`IndexedPreparedMesh.face_edge_ids` and `face_edge_flags`.

The Blender importer uses those arrays to:

1. Find adjacent faces for each source edge.
2. Check whether the source edge has the smooth bit.
3. Compare adjacent face normals.
4. If at least one edge actually needs smoothing, set Blender polygon smoothing
   for all generated polygons and mark every non-smooth source boundary sharp.
   Generated diagonals remain non-sharp, preserving the normal fan across
   triangles of the same source face. Quads conversion retains sharp edges.

This keeps cylindrical sides smooth without rounding cap edges.
If no source edge requires smoothing, the Blender importer leaves the mesh in
Blender's default flat-shaded state and does not mark extra sharp edges.
The Blender importer exposes this behavior as the `smooth_edges` import option;
disable it to keep all imported faces flat shaded.

When vertices are not merged by the consuming importer, adjacent faces cannot
share normals even if the source edge is smooth. The Blender add-on enables
vertex merging by default, which allows the imported edge-shading data to take
effect.

## Blender Export Mapping

Export uses Blender's authored shading state rather than reversing the
importer's angle-based interpretation. For every edge that remains after mesh
conversion, the exporter counts adjacent polygons and maps the state as
follows:

| Blender condition | Public `Edge.flags` | SketchUp result |
|-------------------|---------------------|-----------------|
| Exactly two adjacent faces, both `use_smooth`, edge not `use_edge_sharp` | `0x02 | 0x04` | Soft and smooth |
| Either adjacent face has `use_smooth = False` | `0x00` | Hard |
| Edge has `use_edge_sharp = True` | `0x00` | Hard |
| Fewer than two adjacent faces | `0x00` | Hard boundary |
| More than two adjacent faces | `0x00` | Hard non-manifold boundary |

Requiring both adjacent faces prevents a smooth polygon from rounding its
boundary with a flat polygon. Requiring exactly two faces also prevents
boundary and non-manifold edges from becoming invisible soft edges. Hidden
state is independent and may be combined with these normalized public flags
when present in a hand-authored `skppy` model.

The exporter deliberately does not apply the importer's 40 degree threshold.
If Blender displays two smooth faces across a non-sharp edge, the corresponding
SketchUp edge is soft and smooth regardless of angle. Conversely, an explicit
sharp mark always wins. Coplanar merging can remove eligible internal edges
before this mapping; retained material, UV, outer, hole, non-manifold, and
non-coplanar boundaries receive the flags described above.
