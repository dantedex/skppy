# Code Style

This standard applies to all new and modified code in `skppy`, `blender_skp_io`, build scripts, and tests.

The keywords **must**, **should**, and **may** are intentional:

- **Must**: required; exceptions need a code comment or commit explanation.
- **Should**: the normal choice; deviate only when the alternative is clearer.
- **May**: optional and context-dependent.

## Core principles

Code must be compact without becoming cryptic. Optimize for the next reader, not for the fewest characters.

- Keep behavior explicit, local, typed, and easy to test.
- Prefer straightforward data flow over clever abstractions or hidden state.
- Reject invalid data at the boundary where it becomes known.
- Preserve public compatibility unless the task intentionally changes the documented contract.
- Make the smallest coherent change and keep unrelated edits out of the commit.

## Formatting

- The default maximum line length is 120 characters. Break earlier when a line contains multiple ideas.
- Ruff is authoritative for Python formatting. Do not hand-format against Ruff.
- Use four spaces, double quotes, trailing commas in multiline constructs, and one statement per line.
- Use parentheses for multiline expressions. Do not use backslash continuations.
- Separate top-level definitions with two blank lines and method definitions with one blank line.
- Do not align assignments or arguments with manual padding; it creates noisy diffs.

Preferred:

```python
material_id = material_ids_by_archive_index.get(
    drawing_element.material_tag.index or 0,
)
```

Also preferred when it remains easy to scan:

```python
material_id = material_ids_by_archive_index.get(drawing_element.material_tag.index or 0)
```

Avoid packing separate operations onto one line:

```python
material = read_material(reader); model.materials.append(material)
```

## File layout and imports

Python source files must normally use this order:

1. Shebang, when executable.
2. One-line SPDX identifier.
3. Module docstring.
4. `from __future__ import annotations`, when needed.
5. Standard-library imports.
6. Third-party imports.
7. Local imports.
8. Constants, types, classes, and functions.

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate one writer conformance fixture."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from skppy.data_structure.model import Model
```

- Imports must remain at module scope unless deferring an import prevents a real cycle or optional dependency failure.
- Import names directly when that improves clarity. Avoid wildcard imports outside deliberately centralized test
  fixtures.
- Remove unused imports. Do not retain imports for undocumented side effects.
- The first non-shebang source line must be `# SPDX-License-Identifier: MIT`; C/C++ files use
  `// SPDX-License-Identifier: MIT`.

## Naming

- Modules, functions, methods, and variables use descriptive `snake_case`.
- Classes and type aliases use `PascalCase`.
- Constants use `UPPER_CASE`.
- Private implementation details start with one underscore.
- Boolean names should read as predicates: `is_visible`, `has_texture`, `should_retry`, `can_resolve`.
- Collections should describe their members: `layers_by_id`, `material_ids`, `pending_references`.
- Include units when ambiguity is possible: `offset_bytes`, `angle_radians`, `width_points`.
- Retain wire-format names when they are the clearest connection to verified format evidence.

Preferred:

```python
materials_by_archive_index: dict[int, Material] = {}
payload_end_offset = reader.tell()
is_perspective = reader.read_bool()
```

Avoid vague or encoded names:

```python
d = {}
x2 = reader.tell()
flag = reader.read_bool()
```

Single-letter names are acceptable only for conventional, tiny scopes such as `x`, `y`, `z`, or a short comprehension.

## Types and data models

- Public APIs and nontrivial internal boundaries must be typed.
- Prefer precise unions and protocols over `Any`. Use `Any` only at a genuinely dynamic boundary.
- Use `T | None`, built-in generics such as `list[int]`, and postponed annotations.
- Use dataclasses for records with named fields. Use tuples only for small, stable, self-evident groupings.
- Use frozen dataclasses for immutable parse state and mutable dataclasses for public model objects that users edit.
- Do not use mutable default arguments. Use `field(default_factory=list)` or `None` plus explicit initialization.
- Narrow dynamic values with `isinstance()` before accessing type-specific fields.
- Do not use `cast()` to hide a runtime uncertainty that should be validated.

Preferred:

```python
def resolve_material(material_id: int, materials: dict[int, Material]) -> Material | None:
    return materials.get(material_id)
```

Avoid:

```python
def resolve_material(material_id, materials) -> Any:
    return materials.get(material_id)
```

Preferred mutable default:

```python
@dataclass
class LayerFolder:
    child_layer_ids: list[int] = field(default_factory=list)
```

Avoid:

```python
def collect_layers(layers: list[Layer] = []) -> list[Layer]:
    return layers
```

## Functions and control flow

- A function should perform one coherent operation at one abstraction level.
- Prefer guard clauses and early returns over nested condition pyramids.
- Extract a helper when it names a real concept, removes duplication, or isolates a complex boundary.
- Do not extract one-line helpers that merely rename obvious syntax.
- Prefer keyword-only arguments when multiple adjacent values have the same type or meaning could be confused.
- Keep side effects visible in the function name and close to the owning object.
- Return a value instead of mutating an output argument unless identity preservation is part of the contract.
- Avoid boolean parameters that radically change behavior; separate functions are often clearer.

Preferred:

```python
def resolve_object(handle: ArchiveObjectHandle) -> object | None:
    if handle.kind == "null":
        return None
    if handle.kind == "object_ref":
        return objects.get(handle.object_index)
    return read_new_object(handle)
```

Avoid:

```python
def resolve_object(handle: ArchiveObjectHandle) -> object | None:
    if handle.kind != "null":
        if handle.kind == "object_ref":
            return objects.get(handle.object_index)
        else:
            return read_new_object(handle)
    else:
        return None
```

Use comprehensions for simple transformations, not for multi-step control flow.

Preferred:

```python
visible_layers = [layer for layer in layers if layer.visible]
```

Avoid:

```python
results = [convert(value) for value in values if validate(value) and update_cache(value)]
```

## Exceptions and validation

- Validate external bytes, paths, schemas, indexes, and public arguments before relying on them.
- Raise the most specific useful exception with the failing value and context.
- Use `NotImplementedError` for recognized but unsupported format variants.
- Use `ValueError` for malformed values or inconsistent payloads.
- Use `EOFError` for truncated binary input.
- Never use bare `except:`. Catch only errors that can be handled at that layer.
- Preserve the original exception with `raise ... from exc` when translating error domains.
- Do not silently guess missing wire data or substitute modern defaults for absent historical fields.

Preferred:

```python
if class_version not in {4, 6}:
    raise NotImplementedError(f"CTexture version {class_version} is not decoded.")
```

Avoid:

```python
try:
    return parse_texture(reader)
except Exception:
    return Texture()
```

Assertions are for programmer invariants, not user-controlled data validation.

```python
registration = index_table.register_new_object_tag(tag)
assert registration is not None  # The null/reference cases returned above.
```

## State, mutation, and dependencies

- Keep mutable state owned by the narrowest practical object.
- Do not add module globals that change during parsing, writing, or tests.
- Make mutation obvious: use verbs such as `append`, `register`, `populate`, `apply`, or `update`.
- Copy caller-owned collections only when isolation is required; otherwise document retained ownership.
- Avoid speculative caching. Add caches only with a measured or structurally clear benefit and an invalidation strategy.
- Reuse existing dependencies. A new runtime dependency requires a clear user benefit and maintenance justification.
- Keep pure-Python `skppy` independent from Blender; Blender-specific code belongs in `blender_skp_io`.

Preferred dependency direction:

```text
blender_skp_io -> skppy -> Python standard library / NumPy
```

Forbidden dependency direction:

```text
skppy -> bpy or blender_skp_io
```

## Public APIs and compatibility

- Public names, signatures, defaults, serialized output, and model semantics are compatibility contracts.
- Add optional parameters as keyword-only unless positional use is intentionally supported.
- Keep internal archive indexes separate from public model IDs.
- Preserve object identity when references represent the same archived object.
- Document intentional breaking changes and update tests and user documentation in the same commit series.
- Do not expose parser-only state through public model classes when provenance can retain it privately.

Preferred extension:

```python
def save(model: Model, destination: BinaryIO, *, target_version: int | None = None) -> None:
    ...
```

Avoid an ambiguous positional extension:

```python
def save(model, destination, target_version=None):
    ...
```

## Comments and docstrings

- Comments explain why, invariants, evidence, ownership, or a surprising constraint.
- Do not narrate syntax or preserve implementation history in comments.
- Public modules, classes, and functions must have concise docstrings.
- A docstring should state the contract, units, mutation, returned value, and expected failures when relevant.
- Link canonical documentation instead of duplicating long format tables in code comments.
- Put user guidance in `docs/`, durable contributor rules in `.agents/`, and implementation history in Git.

Preferred comment:

```python
# Class and object entries share one index space; separate counters shift every later reference.
object_index = index_table.register_object(class_name, schema)
```

Avoid:

```python
# Register the object.
object_index = index_table.register_object(class_name, schema)
```

Preferred docstring:

```python
def read_exact(self, size: int, label: str) -> bytes:
    """Read exactly *size* bytes or raise ``EOFError`` naming *label*."""
```

## Binary I/O

- Treat the wire format as untrusted input.
- Read and write fields in serialized order; keep version gates adjacent to the affected fields.
- Use explicit little-endian widths: `<B`, `<H`, `<I`, `<Q`, `<f`, and `<d`.
- Name offsets by what they delimit: `payload_start_offset`, `header_end_offset`, `zip_offset`.
- Check lengths before allocation or slicing, and reject unsafe container entries.
- Preserve unknown bytes only when their exact boundary is proven.
- Separate archive identity resolution from construction of public model IDs.
- Cite observed evidence in tests or format documentation; do not infer layouts from nearby versions.

Preferred:

```python
expected = struct.pack("<I3d", 3, 1.0, 2.0, 3.0)
count, x, y, z = struct.unpack("<I3d", expected)
```

Avoid platform-dependent widths or byte order:

```python
value = struct.pack("I", count)
```

Version gates should be linear and local:

```python
name = reader.read_legacy_utf16_string("component name")
if class_version >= 5:
    guid = reader.read_exact(16, "component GUID")
```

## Tests

- Each test should demonstrate one behavior or one tightly related boundary table.
- Test names should describe the input condition and observable result.
- Use Arrange/Act/Assert structure without adding those comments when the phases are already obvious.
- Assert public behavior and meaningful state, not incidental implementation calls.
- Cover valid boundaries, malformed lengths, truncation, unsupported schemas, and unresolved references.
- Keep fixtures small. Place a helper in a shared fixture module only when multiple test files genuinely need it.
- Use `pytest.mark.parametrize` for the same behavior across data cases.
- Do not weaken assertions merely to make a test pass.

### Parser fixtures

Parser fixtures must be independent from production serializers, tag enums, masks, schemas, and defaults.

Preferred:

```python
payload = b"".join(
    [
        struct.pack("<I", 2),
        struct.pack("<3d", 1.0, 2.0, 3.0),
        struct.pack("<3d", 4.0, 5.0, 6.0),
    ]
)

points = read_points(io.BytesIO(payload))

assert [point.to_tuple() for point in points] == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
```

Avoid constructing expected input with production code:

```python
payload = skppy.writer.write_points(expected_points)
assert read_points(io.BytesIO(payload)) == expected_points
```

### Writer fixtures

Writer tests must compare generated bytes with independently authored raw expected bytes. Parser/writer round trips are
not correctness tests because the same misunderstanding can exist on both sides.

Preferred:

```python
expected = struct.pack("<HI", 0x01FB, 4) + b"data"

actual = write_record(tag=0x01FB, payload=b"data")

assert actual == expected
```

Avoid:

```python
actual = write_model(model)
assert parse_model(actual) == model
```

Round trips may exist as smoke tests only when independent byte-level tests already establish correctness.

### Test doubles

- Prefer real small values and `io.BytesIO` over mocks.
- Use a stub or `SimpleNamespace` when the test needs a narrow protocol boundary.
- Use monkeypatching to isolate expensive/external behavior, not to reproduce the implementation under test.
- Never access the network in unit tests.

## Blender addon code

- Keep `bpy` imports and Blender object manipulation inside `blender_skp_io`.
- Convert Blender state to/from shared `skppy` model objects at explicit adapter boundaries.
- Avoid relying on the interactive context when a data API operation is available.
- Preserve hierarchy, transforms, materials, UVs, visibility, and shared mesh identity explicitly.
- Integration behavior must be tested in every supported live Blender LTS version from the minimum supported version.

Preferred boundary:

```python
def build_model_from_scene(scene: bpy.types.Scene) -> Model:
    model = Model()
    populate_model_entities(model, scene.objects)
    return model
```

Avoid importing Blender into the library:

```python
# skppy/data_structure/model.py
import bpy
```

## Performance

- Choose clear linear passes and indexed lookups before micro-optimizing syntax.
- Avoid repeated full scans inside loops when an identity or ID map can be built once.
- Do not optimize without preserving readable invariants and equivalent tests.
- Benchmark changes to triangulation, large-model parsing, mesh preparation, or serialization when performance motivates
  the change.

Preferred:

```python
materials_by_name = {material.name: material for material in model.materials}
for archived in archived_materials:
    material = materials_by_name.get(archived.material.name)
```

Avoid:

```python
for archived in archived_materials:
    material = next((item for item in model.materials if item.name == archived.material.name), None)
```

## Required checks

Follow `.agents/TESTING.md`. At minimum, relevant changes must pass:

```bash
make test
make coverage
make quality
```

Run documentation, doctest, Blender, and public SDK conformance gates when the changed area requires them. A change is
not complete while any relevant formatting, lint, typing, test, coverage, documentation, or integration check fails.

## Review checklist

Before committing, verify:

- The code is no more complex than the behavior requires.
- Names expose intent and units.
- Public and nontrivial boundaries are typed.
- Invalid input fails explicitly and with context.
- Binary fields use explicit widths and verified ordering.
- Tests are independent and cover both success and failure boundaries.
- Comments explain constraints rather than syntax.
- Lines are at most 120 characters by default, and Ruff is clean.
- The commit contains one coherent package and preserves unrelated changes.
