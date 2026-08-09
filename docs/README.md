# skppy documentation

The public documentation is built with Sphinx and published through GitHub
Pages at <https://dantedex.github.io/skppy/>.

## Organization

| Path | Purpose |
| --- | --- |
| `getting_started.md` | Short end-to-end introduction |
| `guides/` | Task-oriented library guides and executable examples |
| `blender/` | Addon installation, options, architecture, and packaging |
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
