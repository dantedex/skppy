# `skppy` — SketchUp `.skp` Toolkit

`skppy` (reads "skippy") is a Python toolkit for reading SketchUp (`.skp`)
files and writing the confirmed modern-format public model graph. It does not
require SketchUp or its C API, and it uses NumPy for vector, matrix, UV, and
image-alpha operations.

It provides a Pythonic object model independent of SketchUp's C API. It reads
the ZIP/VFF container used by newer files and the earlier CArchive container.
Compatibility samples cover the supported save generations and verify format
detection and version dispatch; semantic coverage still varies by class and
version. `skppy.load()` detects the container and selects the correct parser
automatically.

Continuous integration tests Python 3.11 through 3.14 on Linux, macOS, and
Windows. The Blender addon requires Blender 4.2 or newer; its headless
integration suite runs against Blender 4.5 LTS and Blender 5.2 LTS.

In addition to the `skppy` library, this repo contains a self-contained Blender
addon for importing and exporting `.skp` files. The addon converts geometry,
reusable components, collection instances, materials/textures, UVs, tags,
cameras/scenes, text annotations, and scalar custom properties.

## Documentation

The complete documentation is published at
[dantedex.github.io/skppy](https://dantedex.github.io/skppy/). Use
[latest](https://dantedex.github.io/skppy/latest/) for the current development
documentation or select a stable release such as
[0.9.1](https://dantedex.github.io/skppy/0.9.1/) from the version menu.

Documentation sources live in [`docs/`](docs/). Build the current sources with
`make docs`, or build all documented releases and `main` with
`make docs-versioned`.

## Features

- **Read** ZIP/VFF `.skp` files emitted for SketchUp 2021 and later
- **Read** pre-ZIP CArchive `.skp` files into the same public model classes
- **Read** standalone `.skm` material packages, including embedded textures and opt-in V-Ray PBR values
- **Parse** geometry (vertices, edges, faces, curves, arc curves, guide points/lines, section planes)
- **Parse** component definitions and instances (including nested groups and images)
- **Parse** materials with colors, textures, and PBR properties (metallic, roughness)
- **Parse** layers (tags) and layer folders
- **Parse** cameras, scenes (saved views), rendering options, shadow info, axes
- **Parse** edge flags (soft/smooth/hidden bits)
- **Parse** face UV projections and front/back materials
- **Parse** line styles, fonts, text styles, dimension styles
- **Parse** environment data, sun data, options manager, attribute dictionaries
- **Triangulate** faces with holes, or split single-hole faces into two n-gons
- **Builder and writer API** for modern models and SketchUp Make 2017 geometry
- **Blender addon** for importing and exporting `.skp` files through Blender's File menu

## Quick Start

```bash
pip install skppy
```

```python
import skppy

# Load a .skp file
model = skppy.load("my_model.skp")
print(model.header.version_string)       # e.g. "{26.1.103}"
print(len(model.entities.faces))         # number of root-level faces
print(len(model.materials))              # number of materials
print(len(model.definitions))            # number of component definitions

# Traverse geometry
for face in model.entities.faces:
    print(face.id, face.plane, face.front_material_id)
    triangles = face.triangulate(model.entities)

# Inspect materials
for mat in model.materials:
    print(f"{mat.name}: color={mat.color}, metallic={mat.metallic}")

# Load a standalone SketchUp material package
material = skppy.load_material("stone.skm")
print(material.name, material.texture.filename if material.texture else None)

# Look at component definitions
for defn in model.definitions:
    print(f"{defn.name}: {len(defn.entities.faces)} faces")
```

## Creating a model from scratch

```python
import skppy

model = skppy.new_model()
brick = model.add_material("Brick", color=skppy.Color(180, 80, 60))
defn = model.add_definition("Wall")
face = defn.entities.add_face([(0,0,0),(300,0,0),(300,250,0),(0,250,0)])
face.front_material_id = brick.id
model.entities.add_instance(defn, transform=skppy.Transform.identity())
model.save("wall.skp")
```

## Running tests

```bash
make test
```

Run the isolated Blender extension integration with `make test-blender`.

Release notes are maintained in [CHANGELOG.md](CHANGELOG.md). Version tags
build and test both the Python distribution and bundled Blender extension
before publishing their artifacts.

## Project

- **Author and maintainer:** Dante Dex
  ([dante.dex.arch@gmail.com](mailto:dante.dex.arch@gmail.com))
- **Source:** [dantedex/skppy](https://github.com/dantedex/skppy)
- **Documentation:** [dantedex.github.io/skppy](https://dantedex.github.io/skppy/)
- **Conformance suite:**
  [dantedex/skppy-tests](https://github.com/dantedex/skppy-tests)

## Development and AI Usage

This package used AI assistance during research, implementation, tests, and
documentation. All AI-assisted changes were reviewed and edited by a human
developer, who also defined the overall design and architecture.

Format support is an independent interoperability implementation based on
files produced through documented public interfaces and on observable file
behavior. The project contains only original source code and redistributable
test assets.

## License

`skppy` is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Legal Disclaimer

`skppy` is an independent interoperability project and is not affiliated with
or endorsed by Trimble Inc., the company that develops SketchUp. SketchUp is a
trademark of its respective owner.
