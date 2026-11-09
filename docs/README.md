# skppy documentation

The public documentation is built with Sphinx and published through GitHub
Pages at <https://dantedex.github.io/skppy/>.

## Organization

| Path | Purpose |
| --- | --- |
| `getting_started.md` | Short end-to-end introduction |
| `guides/` | Task-oriented library guides and executable examples |
| `blender/` | Addon installation, options, architecture, packaging, and material-export status/roadmap |
| `_static/screenshots/` | Real Blender UI captures using an original demo scene |
| `capture_screenshots.py` | Reproducible foreground Blender capture helper |
| `api/` | Generated Python API reference |
| `format/` | Interoperability notes and wire-format references |
| `format/reference/` | Detailed legacy tables and field layouts |
| `skp_tags.yaml` | Machine-readable modern TLV tag map |

Keep introductory pages focused on public usage. Detailed byte layouts and
schema matrices belong under `format/reference/`.

## Build and test

Install the project development dependencies, then run from the repository
root:

```bash
make docs
make doctest
```

Both commands treat Sphinx warnings as errors. `make doctest` executes the
examples in `guides/examples.md`.

## Screenshots

The current images were captured in Blender 4.5.11 LTS using the packaged
addon. They show real import/export dialogs, a constant-input Principled
material, and an original three-sphere scene. The Solid viewport scene is
**not** an import/export fidelity comparison. No third-party model or texture
assets are used.

To refresh them, build the addon, then run a **new, disposable foreground
Blender process** from the repository root. Replace the version in the command
with the artifact name printed by the build:

```bash
python build_blender_addon.py
BLENDER_USER_RESOURCES=/tmp/skppy-docs-blender blender \
  --factory-startup -noaudio --window-geometry 0 0 1440 1000 \
  --python-exit-code 1 --python docs/capture_screenshots.py -- \
  --addon dist/blender_skp_io-<version>.zip \
  --output docs/_static/screenshots
```

The helper creates its own scene, loads the addon from the supplied local ZIP,
opens file selectors without importing/exporting, captures only Blender's
windows, then exits. It does not install the addon or save preferences. Do not
run it in a session containing unsaved work. A working graphical display is
required; background Blender cannot capture these UI images.

Review all four images before publishing: check framing, label readability,
splash/popover overlays, and accidental user paths. Keep alternative text and
captions accurate, include the Blender version, and do not present mockups as
screenshots. If installation or organization behavior changes, add matching
Preferences/Outliner captures. The current export-dialog capture predates the
optional color/alpha baking controls; refresh it when a graphical capture is
available. Source-versus-export material comparisons remain useful follow-up
illustrations; the existing Solid viewport image is not evidence of bake
fidelity or support for arbitrary shader graphs.

## Review scope

The original Blender documentation review corrected extension installation
guidance, menu labels, and material-export fidelity claims. Subsequent
implementation added active-output shader analysis, basic shader adapters,
and opt-in CPU Cycles color/alpha baking; the Python writer remains unchanged.
Current behavior and limitations live in `blender/export_options.md` and
`blender/architecture.md`. `blender/material_export_plan.md` now separates the
delivered subset, historical review findings, and remaining proposals. Keep
these distinctions explicit rather than describing the entire roadmap as
unimplemented or promising general shader fidelity.
