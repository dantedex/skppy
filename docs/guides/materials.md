# Materials and Textures

Guide to reading, creating, and working with materials and their textures. The
reading snippets assume a `model` returned by `skppy.load()`; creation snippets
use a model created with `skppy.new_model()`.

---

## Reading materials

The material registry exposes stored color plus normalized PBR values:

```python
for mat in model.materials:
    r, g, b, a = mat.color.r, mat.color.g, mat.color.b, mat.color.a
    print(f"{mat.name!r}")
    print(f"  RGBA: ({r}, {g}, {b}, {a})")
    print(f"  alpha:     {mat.alpha:.2f}")
    print(f"  metallic:  {mat.metallic:.2f}")
    print(f"  roughness: {mat.roughness:.2f}")
    print(f"  specular:  {mat.specular:.2f}")
    print(f"  IOR:       {mat.ior:.2f}")
    print(f"  textured:  {mat.has_texture}")
```

`mat.color.a` is the stored color-channel alpha, while `mat.alpha` is the
normalized material opacity used by importers. Faces reference `mat.id`.

## Loading standalone SKM materials

Use `load_material()` for a material saved from SketchUp or downloaded from a
material library:

```python
import skppy

material = skppy.load_material("stone.skm")
print(material.name, material.color)
if material.texture and material.texture.data:
    print(material.texture.filename, len(material.texture.data))
```

The loader detects the material package from its ZIP contents rather than its
extension. This also handles downloads incorrectly named `.skp` when their
contents are actually an SKM package with `document.xml` and `ref/` resources.
Malformed packages raise `skppy.InvalidSkmError`.

Standalone packages can contain V-Ray and Enscape attribute dictionaries.
SketchUp color and texture values remain authoritative by default; pass
`import_vray_materials=True` to prefer supported renderer PBR values and maps:

```python
material = skppy.load_material("stone.skm", import_vray_materials=True)
```

The compatibility keyword retains its original name, but enables both V-Ray
and Enscape metadata. Valid Enscape metadata takes precedence when both are
present; malformed or absent Enscape metadata permits the V-Ray fallback.
This same option is accepted by `skppy.load()` for modern and legacy SKP files.

(enscape-import-coverage)=
### Enscape import coverage

The decoder handles the `Enscape.Material` dictionary's `MaterialData` XML,
including the `SketchupMaterial Version="4"` layout observed in compatibility
samples. No external renderer or plugin is needed.

| Enscape control | Imported value / Blender behavior |
| --- | --- |
| `DiffuseColor`, `Opacity` | Base color and opacity; opacity multiplies diffuse image alpha |
| `TintColor`, `ImageFade` | Multiply the diffuse image by its tint, then blend it with the untextured base color |
| `Metallic`, `Roughness`, `Specular` | Metallic, roughness, and specular scalar values |
| `IndexOfRefraction` | Principled IOR |
| `TypeV5=GLASS` (or `Type=GLASS`) | Glass opacity becomes transmission (`1 - Opacity`); surface alpha remains opaque so reflections survive |
| `EmissiveColor`, `EmissiveStrength` | Emission color and strength |
| `DiffuseTexture` | Embedded diffuse image; retain the SketchUp image when the replacement is missing |
| Texture `Source=SKETCHUP` | Use the material's own embedded image, ignoring a stale renderer filename |
| `RoughnessTexture` | Non-Color roughness map |
| `BumpMapType=BUMP`, `BumpAmount` | Height map through a Bump node |
| `BumpMapType=NORMAL`, `NormalMapIntensity` | Tangent-space Normal Map node |
| `BumpMapType=DISPLACEMENT`, `BumpAmount` | Displacement node; actual geometry displacement depends on Blender render settings |
| `Brightness`, `IsInverted` | Preserved per map; applied to diffuse and scalar-map node chains |

Enscape metallic **maps** are not decoded, despite the shared `Material` model
having a `metallic_texture` slot. Water, grass, foliage,
clearcoat and explicit per-map size/rotation are not
translated. Map UVs use the existing SketchUp texture scale. Normal-map color
brightness/inversion is retained as metadata but is not applied to normal
vectors; normal intensity is supported. Enscape export is not implemented.

Glass uses a Principled transmission approximation, with imported roughness
and IOR. It does not reproduce Enscape's thin/solid-glass distinction or
renderer-specific caustics. Refraction quality depends on Blender's render
engine, settings, and the imported geometry. The newer `TypeV5` field takes
precedence over its older `Type` fallback, as observed in version-5 materials.

The tint/image-fade conversion follows the controls described in the
[Enscape material manual](https://docs-chaos.atlassian.net/wiki/spaces/enscape/pages/841252963/Material+Types).
Colors are converted from serialized sRGB to Blender scene-linear values;
image adjustments use editable shader nodes and do not alter the packed pixels.

Legacy SKP decoding reuses a material's own embedded texture only when the map
filename matches (case-insensitively). Other maps remain missing references;
images from unrelated materials are not substituted. Invalid or oversized
optional Enscape XML is ignored, leaving the SketchUp/V-Ray fallback intact.
The XML budget is configurable through `skppy.LoadLimits(max_xml_bytes=...)`.

Some SKM libraries reference auxiliary images through creator-machine paths
without embedding those images. skppy retains the safe basename and renderer
settings while leaving `texture.data` as `None`:

```python
roughness = material.roughness_texture
if roughness:
    print(roughness.filename, roughness.brightness, roughness.inverted)
    if roughness.data is None:
        print("The SKM references this map but does not contain its pixels")
```

Only embedded images are eligible for automatic loading. skppy never opens an
absolute path serialized by another machine. In SKM/modern SKP packages, a
declared safe ZIP path takes precedence over the current material's folder and
an unambiguous basename match. Ambiguous images are not guessed.

---

## Accessing texture data

A texture combines physical tile size, its informational filename, optional
encoded image bytes, and renderer brightness/inversion settings:

```python
for mat in model.materials:
    if mat.has_texture and mat.texture:
        tex = mat.texture
        print(f"  filename: {tex.filename!r}")
        print(f"  size:     {tex.x_scale:.1f} x {tex.y_scale:.1f} inches/tile")
        if tex.data:
            print(f"  bytes:    {len(tex.data)}")
```

`x_scale` and `y_scale` represent the **real-world size** of one texture tile
in inches. A value of `100.0` means one tile spans 100 inches (~= 2.54 m).

## PBR factors

SketchUp's `pbrMR` XML block can provide metallic and roughness factors. skppy
applies these only when the matching `enable_metalness` or `enable_roughness`
flag is active; disabled factors fall back to Blender-friendly defaults
(`metallic=0.0`, `roughness=1.0`).

---

## Saving textures to files

Write retained bytes without decoding them, while sanitizing the resource
name before joining it to the output directory:

```python
from pathlib import Path, PureWindowsPath

out = Path("extracted_textures")
out.mkdir(exist_ok=True)

for mat in model.materials:
    if mat.has_texture and mat.texture and mat.texture.data:
        # Discard any serialized source directories before creating a path.
        safe_name = PureWindowsPath(mat.texture.filename).name or f"material-{mat.id}"
        dest = out / safe_name
        dest.write_bytes(mat.texture.data)
        print(f"Saved {dest}")
```

Two materials can refer to the same filename. Production extractors should
decide whether to deduplicate identical bytes or generate unique names.

---

## Creating textured materials in memory

You can attach a `Texture` object to a material in memory and persist it through
the modern writer:

```python
from pathlib import Path
import skppy

# Keep the encoded PNG/JPEG bytes; skppy does not transcode the image.
texture_bytes = Path("brick.jpg").read_bytes()

brick = model.add_material("Brick", color=skppy.Color(180, 80, 60))
brick.has_texture = True
brick.texture = skppy.Texture(
    filename="brick.jpg",
    x_scale=100.0,   # 100 inches per tile
    y_scale=100.0,
    data=texture_bytes,
)
```

The physical scales control tiling independently of pixel dimensions. The
writer embeds `texture.data`; `filename` is the resource name stored in the
container.

---

## UV coordinates

UV coordinates are computed per face from the `FaceUVProjection` object. See
[format/uv_projection.md](../format/uv_projection.md) for the full formula.

Quick summary:
- UV projection is active only when `face.front_uv` (or `back_uv`) is not `None`.
- Without a projection, `skppy` falls back to planar UV tiling.
- UV values are computed in local space (SketchUp inches), then divided by
  `texture.x_scale` / `texture.y_scale` to normalise.

```python
def front_uv(face, vertex, material):
    """Return one local-space front UV, or None for an untextured face."""
    projection = face.front_uv
    texture = material.texture
    if projection is None or texture is None:
        return None
    return projection.compute_uv(
        px=vertex.position.x,
        py=vertex.position.y,
        pz=vertex.position.z,
        x_scale=texture.x_scale,
        y_scale=texture.y_scale,
        normal=face.normal().to_tuple(),
    )
```

The vertex must come from the same definition-local scope as the face. Do not
apply an instance transform before computing stored UV projections.

---

## Transparent materials

In SketchUp, `alpha < 1.0` means the material is semi-transparent. In Blender
the addon sets:

- `Blender 4.2+`: `material.surface_render_method = "DITHERED"`
- Older Blender: `material.blend_method = "HASHED"` when supported, otherwise
  `BLEND`

When a diffuse texture's alpha channel contains transparent pixels, the Blender
addon connects the image texture's `Alpha` output to the Principled BSDF
`Alpha` input and enables the same transparent material mode.

---

## Material inheritance

A face with `front_material_id = None` inherits the material of its parent
component instance. Use `Entities.prepare_mesh()` to resolve this:

```python
lookup = {m.id: m for m in model.materials}
mesh = defn.entities.prepare_mesh(
    name="my_instance",
    material_lookup=lookup,
    inherited_material_id=instance.material_id,  # may be None
)

for face in mesh.faces:
    # None means neither the face nor the parent instance has a material.
    print(face.material_name or "default material")
```

Pass the parent instance's effective material ID at each nesting level. The
method resolves both material names and the texture scale needed for UVs.
