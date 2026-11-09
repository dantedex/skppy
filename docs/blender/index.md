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
| [Material export roadmap](material_export_plan.md) | Delivered shader adapters and color/alpha baking, plus remaining native PBR-map work |
| [Architecture](architecture.md) | How the addon converts SKP to Blender objects |
| [Building](building.md) | Packaging the distribution ZIP |

```{toctree}
:hidden:

import_options
scene_organization
export_options
material_export_plan
architecture
building
```

---

## Quick start

1. Build: `python build_blender_addon.py`
2. Install: **Edit -> Preferences -> Add-ons -> menu -> Install from Disk...** -> select the ZIP; enable the extension if needed.
3. Import: **File -> Import -> SketchUp (.skp/.skm)**
4. Export: **File -> Export -> SketchUp (.skp)**

```{figure} ../_static/screenshots/material-demo.png
:alt: Original three-sphere demonstration scene with terracotta, metal, and blue-paint material names in Blender.

An original Blender scene used for the documentation captures. This is a Solid
viewport illustration, not an SKP import result or a rendered PBR comparison.
```

The importer creates a Blender collection named after the file. See
[Imported Scene Organization](scene_organization.md) for the resulting
collections, component hierarchy, objects, and shared data.
