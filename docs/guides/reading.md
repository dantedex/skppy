# Reading SKP Files

Practical patterns for loading and extracting data from `.skp` files. Except
for the first snippet, the examples build on the loaded `model` variable.

## Resource limits and cancellation

`load()` and `load_material()` accept a `LoadLimits` value. Defaults allow 1 GiB
per uncompressed resource (or entire legacy file), 4 GiB of cumulative ZIP
reads, and 8 MiB per XML resource. Repeated reads count toward the cumulative
budget. Limits constrain input bytes, not total memory used by the decoded
geometry, images, or Python object graph.

```python
import skppy

limits = skppy.LoadLimits(max_entry_bytes=256 * 1024 * 1024, max_total_bytes=1024 * 1024 * 1024)
model = skppy.load("building.skp", limits=limits)
```

Increase limits deliberately for trusted large files. Oversized resources are
rejected before extraction with `InvalidSkpError` or `InvalidSkmError`; inspect
the exception's `__cause__` for the resource and budget. Both loaders also
accept `cancellation_check`, checked between read chunks. Cancellation raises
`LoadCancelledError` rather than becoming an invalid-file error.

---

## Basic load

Import the package and pass a filesystem path to the single public loader:

```python
import skppy

model = skppy.load("model.skp")
```

`load()` detects the modern ZIP and legacy pre-ZIP containers automatically.
It returns the same `Model` API for both; malformed existing files raise
`skppy.InvalidSkpError`.

---

## Inspecting the header

Loaded models retain both parsed header fields and source-container metadata:

```python
h = model.header
print(h.product_name)     # "SketchUp 2023"
print(h.version_string)   # "{23.1.340}"
print(h.version_tuple)    # (23, 1, 340)
if model.document is not None:
    print(model.document.filepath)  # path passed to skppy.load()
```

`header` describes the SKP envelope. `document` describes the embedded ZIP and
is available for modern files; legacy-specific provenance is instead exposed
through `model.legacy_archive`.

---

## Listing materials

Iterate the model registry to inspect normalized appearance values:

```python
for mat in model.materials:
    print(f"  {mat.name!r}")
    print(f"    color:    {mat.color}")
    print(f"    alpha:    {mat.alpha}")
    print(f"    metallic: {mat.metallic}")
    print(f"    roughness:{mat.roughness}")
    if mat.has_texture and mat.texture:
        t = mat.texture
        print(f"    texture:  {t.filename!r} ({t.x_scale:.1f} x {t.y_scale:.1f} in)")
```

Material IDs, not list positions, are used by faces and component instances.
Build an `{id: material}` dictionary when resolving many references.

---

## Listing layers

Visibility is stored on each layer independently of entity visibility:

```python
for layer in model.layers:
    print(f"  {'[ok]' if layer.visible else '[x]'}  {layer.name}")
```

Layers are called Tags in current SketchUp versions. Entity `layer_id` values
refer to `Layer.id`; a missing ID means the default/untagged layer state.

---

## Walking the instance hierarchy

Root-level instances reference definitions:

```python
defn_map = {d.id: d for d in model.definitions}

def walk(entities, depth=0, active_definition_ids=()):
    """Print component/group nesting while stopping recursive definitions."""
    indent = "  " * depth
    placed_entities = [*entities.component_instances, *entities.groups]
    for placed in placed_entities:
        defn = defn_map.get(placed.definition_id)
        if defn is None:
            print(f"{indent}Missing definition {placed.definition_id}")
            continue
        if defn.id in active_definition_ids:
            print(f"{indent}Recursive reference to {defn.name!r}; stopped")
            continue

        kind = type(placed).__name__
        local = skppy.Transform(placed.transform).translation()
        print(f"{indent}{kind} {placed.name!r} -> {defn.name!r}")
        print(f"{indent}  local translation: {local.to_tuple()} inches")
        walk(defn.entities, depth + 1, (*active_definition_ids, defn.id))

walk(model.entities)
```

Each stored transform is local to its parent. To calculate world coordinates,
compose the matrices along the current recursion path as shown in
[Working with Geometry](geometry.md), especially its world-space example.

---

## Extracting all face geometry

The renderer-neutral scene graph expands nested placements while keeping each
mesh in definition-local coordinates:

```python
def walk_nodes(node):
    """Yield a SceneNode and all descendants in depth-first order."""
    yield node
    for child in node.children:
        yield from walk_nodes(child)


# to_scene() expands nested components and groups with cycle detection.
for node in walk_nodes(model.to_scene()):
    if node.mesh is None:
        continue
    for face in node.mesh.faces:
        # A face material wins; otherwise use the instance-level override.
        effective_material = face.material_name or node.material_name
        print(node.name, face.vertex_positions, effective_material)
```

`PreparedFace.vertex_positions` remain local to their `SceneNode`. Apply the
node transform and all parent transforms for world-space coordinates. Keeping
them local allows repeated component definitions to share one prepared mesh.

---

## Dumping textures to disk

Texture objects retain encoded image bytes when the source resource was
available. Treat serialized filenames as untrusted metadata:

```python
from pathlib import Path, PureWindowsPath

output_dir = Path("textures_out")
output_dir.mkdir(exist_ok=True)

for mat in model.materials:
    if mat.has_texture and mat.texture and mat.texture.data:
        # Serialized filenames are informational and may contain directories.
        safe_name = PureWindowsPath(mat.texture.filename).name or f"material-{mat.id}"
        path = output_dir / safe_name
        path.write_bytes(mat.texture.data)
        print(f"Saved {path}")
```

Using only the final filename component prevents a stored source path from
escaping `textures_out`. Applications should also choose a collision policy
when two materials use the same filename.

---

## Inspecting the raw ZIP

Modern files expose ZIP entry metadata through `model.document`. Legacy files
set this field to `None` because their CArchive container has no ZIP entries.

```python
if model.document is not None:
    for entry in model.document.zip_entries:
        print(f"  {entry.name}: {entry.file_size} bytes")
```

`SkpZipEntry` stores metadata, not an eager copy of every resource. Use
`dump_zip()` when the actual entries are needed:

To extract everything from a modern model:

```python
model.dump_zip("/tmp/skp_extracted/")
```
