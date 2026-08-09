# SketchUp legacy parser tests

This directory keeps the pre-ZIP parser tests grouped by the boundary under
test instead of collecting the complete archive implementation in one module.

| Module | Responsibility |
|--------|----------------|
| `test_model_loading.py` | Public loading, envelope parsing, and shared model metadata |
| `test_archive.py` | MFC CArchive tags, indexes, sessions, and schema guards |
| `test_diagnostics.py` | Non-raising diagnostics and class-coverage reports |
| `test_object_dispatch.py` | Core object dispatch for geometry, materials, layers, and pages |
| `test_scenes_metadata.py` | Scene recovery, cameras, shadows, fonts, and styles |
| `test_annotations.py` | Text, dimensions, and construction annotations |
| `test_auxiliary_objects.py` | Styles, watermarks, components, images, UVs, and relationships |
| `test_geometry.py` | Face topology and root geometry integration |
| `test_model_assembly.py` | Definitions, instances, groups, and images in the final model |

`_fixtures.py` is the single source for compact synthetic archive payloads.
Helpers there deliberately encode fields explicitly so tests describe archive
layout without committing generated binary files. Real-file corpus checks are
kept outside the distributed suite unless their redistribution rights are
explicitly documented.
