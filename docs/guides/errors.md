# Error Handling

Common errors, how to detect them, and recommended handling strategies.

---

## Legacy format

Pre-ZIP files use a CArchive binary format. Compatibility samples confirm this
container through SketchUp 2020. `skppy.load()` decodes its envelope and
`CVersionMap`. The generated version matrix verifies loading for save targets from
SketchUp 3 through 2020, but an unfamiliar class schema can still be unsupported
even when the container and most of the model are otherwise understood.

```python
import skppy

model = skppy.load("file.skp")
if model.legacy_archive is not None:
    print("Legacy archive starts at", model.legacy_archive.archive_offset)
```

`legacy_archive` is provenance and diagnostic state. Application code can keep
using `model.entities`, `model.materials`, and the other shared collections.

Unsupported class layouts raise an explicit parser exception. Re-save those
files as SketchUp 2021 or later when conversion is available.

Strict runtime schemas are listed in the
[legacy format reference](../format/old_format.md). Other
known classes are version-aware: their `CVersionMap` entry and file generation
select the reader. An unregistered runtime class is unsupported even when its
numeric schema matches a known class.

---

## File not found / permission errors

`skppy.load()` calls Python's built-in `open()`, so standard Python `IOError`
/ `FileNotFoundError` apply:

```python
try:
    model = skppy.load("missing.skp")
except FileNotFoundError as exc:
    print(f"File does not exist: {exc.filename}")
except PermissionError as exc:
    print(f"No read access: {exc.filename}")
```

Catch these before `InvalidSkpError`: opening the path failed, so no SKP bytes
were available for format validation.

---

## Corrupt or truncated files

When an existing file cannot be decoded as SKP, `skppy.load()` raises
`skppy.InvalidSkpError`. Its exception cause retains the low-level failure for
diagnostics. This gives applications one stable error boundary for malformed
modern and legacy input.

Parser-level functions may still raise one of:

| Exception | Cause |
|-----------|-------|
| `zipfile.BadZipFile` | The embedded ZIP is corrupt. |
| `EOFError` | A legacy binary primitive is shorter than expected. |
| `ValueError` | A TLV record, string, or required value is malformed. |
| `UnicodeDecodeError` | A UTF-8 string payload is invalid. |
| `KeyError` | A cross-reference (e.g. vertex ID) does not resolve. |
| `UnsupportedLegacySchemaError` | A known legacy class uses an unverified schema. |
| `UnsupportedLegacyObjectError` | A legacy runtime class has no reader. |

A ZIP container without the required `model.dat` entry is invalid input and
raises `InvalidSkpError`; it is not treated as a legacy file or allowed to
leak the lower-level `KeyError` from `zipfile`.

Catch the structured legacy errors separately when a user-facing tool can
recommend re-saving the file in a newer SketchUp version:

```python
from skppy.parser_legacy import (
    UnsupportedLegacyObjectError,
    UnsupportedLegacySchemaError,
)

path = "legacy.skp"
try:
    model = skppy.load(path)
except (UnsupportedLegacyObjectError, UnsupportedLegacySchemaError) as exc:
    # This is a valid legacy container beyond the current class coverage.
    print(f"Ask the user to re-save {path!r} in a newer format: {exc}")
except skppy.InvalidSkpError as exc:
    # __cause__ retains the low-level parser failure for logs and bug reports.
    print(f"Could not decode {path!r}: {exc}")
    print(f"Underlying error: {exc.__cause__!r}")
```

`OldFormatError` is an internal dispatch signal from the ZIP header reader. A
normal `skppy.load()` call detects the CArchive container first and does not
raise it merely because the input is a supported legacy file.

---

## Write/export status

`skppy.save()` raises `NotImplementedError` when a shared legacy-only field has
no confirmed modern representation. The destination remains untouched because
serialization completes in memory first. The Blender exporter reports
unsupported Blender object families and conversion warnings in the operator
result.

```python
try:
    skppy.save(model, "output.skp")
except NotImplementedError as exc:
    print(f"This model cannot be represented without loss: {exc}")
```

Validation errors such as duplicate IDs or dangling references are reported as
`ValueError`. In either case, serialization fails before replacing an existing
destination.

---

## Common pitfalls

### Duplicate material names

If two materials share the same name, `model.get_material(name)` returns only
the first one. Use unique names when creating materials.

### Coordinate units

All positions in `skppy` are in **inches**. Forgetting to convert can produce
models that are 39.37x too large or too small:

```python
INCHES = 1.0
MM = 1.0 / 25.4    # 1 mm in inches
CM = 1.0 / 2.54

vertex = e.add_vertex(500 * MM, 0, 0)   # 500 mm ~= 19.69 inches
```

Apply the conversion to positions and physical texture scales. Direction
vectors, normalized factors, and angles are unitless.

### Faces with no vertices

If `face.triangulate(entities)` returns an empty list, the face is degenerate
(fewer than 3 unique non-collinear vertices). This is normal for some
SketchUp models that contain zero-area faces used as construction geometry.

### Nested instances not flattened

`model.entities` only contains root-level objects. Nested instances inside
definitions are in `definition.entities`. Always recurse to find all geometry.
See [guides/components.md](components.md) for a recursive walker.
