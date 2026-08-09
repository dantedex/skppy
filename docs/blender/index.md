# Blender Addon

The Blender addon (`blender_skp_io`) lets you import and export SketchUp `.skp`
files directly in Blender. It bundles `skppy` so no extra Python packages are
required.

| Page | Description |
|------|-------------|
| [Installing](installing.md) | How to build and install the addon in Blender |
| [Imported scene organization](scene_organization.md) | Collections, object hierarchy, layers, and entity mapping |
| [Import options](import_options.md) | Complete reference for all import settings |
| [Export options](export_options.md) | Complete reference for Blender-to-SKP settings |
| [Architecture](architecture.md) | How the addon converts SKP to Blender objects |
| [Building](building.md) | Packaging the distribution ZIP |

```{toctree}
:hidden:

import_options
scene_organization
export_options
architecture
building
```

---

## Quick start

1. Build: `python build_blender_addon.py`
2. Install: **Edit -> Preferences -> Add-ons -> Install...** -> select the ZIP.
3. Import: **File -> Import -> SketchUp (.skp)**
4. Export: **File -> Export -> SketchUp (.skp)**

The importer creates a Blender collection named after the file. See
[Imported Scene Organization](scene_organization.md) for the resulting
collections, component hierarchy, objects, and shared data.
