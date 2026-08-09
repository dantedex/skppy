# Building the Distribution ZIP

The build script packages the Blender addon into a ZIP file ready for
installation in Blender.

---

## Running the build

```bash
python build_blender_addon.py
```

Output: `dist/blender_skp_io-<version>.zip`

---

## What the script does

1. Derives the same public Python package version as `skppy` from Git tags,
   such as `vX.Y.Z` or `X.Y.(Z+1).devN`.
2. Creates `dist/blender_skp_io-<version>.zip`.
3. Adds the addon source tree (`blender_skp_io/`).
4. Adds the bundled `skppy` library (`skppy/`).
5. Writes a Blender-compatible version into the bundled
   `blender_manifest.toml`.
6. Writes the Git-derived Python package version to the bundled
   `skppy/_version.py`.
7. Excludes:
   - `__pycache__/`, `*.pyc`, `*.pyo`
   - `.git/`, `.mypy_cache/`, `.pytest_cache/`
   - `*.egg-info/`

The resulting ZIP is compatible with Blender's **Extension** system
(manifest schema 1.0.0, `blender_version_min = "4.2.0"`).

---

## ZIP contents

```
blender_skp_io-<version>.zip
+- blender_manifest.toml
+- __init__.py
+- export_builder.py
+- scene_builder.py
+- operators/
|   +- __init__.py
|   +- export_skp.py
|   +- import_skp.py
\- skppy/
    +- __init__.py
    +- loader.py
    +- triangulation.py
    +- utils.py
    +- data_structure/
    |   \- ...
    +- parser/
    |   \- ...
```

---

## Versioning

Version numbers are defined by Git tags through `setuptools-scm`. The bundled
Python package uses the same public version as `skppy`, including development
versions such as `0.8.1.dev12`.

Blender extension manifests require semantic-version-compatible values, so the
packaged `blender_manifest.toml` converts PEP 440 development versions to a
SemVer prerelease form. For example, `0.8.1.dev12` becomes
`0.8.1-dev.12` in the manifest while bundled `skppy/_version.py` keeps
`0.8.1.dev12`.

For a release build, tag the commit:

```bash
git tag vX.Y.Z
python build_blender_addon.py
```

The source `blender_manifest.toml` keeps a valid placeholder version so Blender
can read the checkout during development. The packaged ZIP receives the
Git-derived version, with the manifest normalization described above. Source
archives without Git metadata fall back to `0.0.0`. Use the environment
variable `SKPPY_VERSION` or the build script's `--version` option only when an
explicit build override is required.

---

## Continuous integration

To automate the build:

```yaml
# .github/workflows/build.yml
- name: Build Blender addon
  run: |
    python build_blender_addon.py
- name: Upload artifact
  uses: actions/upload-artifact@v4
  with:
    name: blender_skp_io
    path: dist/*.zip
```
