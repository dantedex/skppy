# Blender integration tests

These tests run inside Blender's Python process and therefore are not collected
by the regular `pytest` suite. Run them from the repository root with:

```bash
make test-blender
```

The runner builds and installs the current extension in an isolated Blender
user directory. Its synthetic models check topology, exact UV coordinates,
texture scale, PBR and alpha nodes, layers, construction entities, annotations,
cameras, saved scenes, shared component meshes, nested and flattened hierarchy,
cycle rejection, and all three face topology modes. Self-contained minimal
modern ZIP/TLV and legacy CArchive fixtures exercise automatic format detection
through both `skppy.load()` and the Blender import operator on every run.

An existing SKP can additionally exercise geometry import through the operator:

```bash
make test-blender BLENDER_FIXTURE=/path/to/generated-fixture.skp
```

Keep fixture paths outside committed commands and documentation. Generated
fixtures from [skppy-tests](https://github.com/dantedex/skppy-tests) are
suitable inputs.

CI runs the same integration runner against every supported LTS line: Blender
4.5 and 5.2. The workflow caches each extracted Blender installation.
