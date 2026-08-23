# SPDX-License-Identifier: MIT
"""
blender_skp_io -- Blender addon for SketchUp .skp IO and .skm material import.

skppy is bundled inside this addon (under skppy/) and does not need to be
installed separately in Blender's Python environment.
"""

bl_info = {
    "name": "SketchUp IO (.skp/.skm)",
    "author": "Dante Dex",
    "version": (0, 10, 0),
    "blender": (4, 2, 0),
    "location": "File > Import/Export > SketchUp (.skp/.skm)",
    "description": "Import SketchUp .skp/.skm files and export .skp files without the SDK",
    "category": "Import-Export",
    "doc_url": "https://dantedex.github.io/skppy/",
    "tracker_url": "https://github.com/dantedex/skppy/issues",
}

import bpy  # noqa: E402

from . import skppy as skppy  # noqa: E402
from .operators.export_skp import EXPORT_OT_skp  # noqa: E402
from .operators.import_skp import IMPORT_OT_skp  # noqa: E402
from .skppy import load, new_model, save  # noqa: E402
from .skppy._version import __version__ as _bundled_skppy_version  # noqa: E402

# A separately installed skppy distribution must not override the version
# generated for this self-contained extension archive.
skppy.__version__ = _bundled_skppy_version

_CLASSES = [
    IMPORT_OT_skp,
    EXPORT_OT_skp,
]


def _menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_skp.bl_idname, text="SketchUp (.skp/.skm)")


def _menu_func_export(self, context):
    self.layout.operator(EXPORT_OT_skp.bl_idname, text="SketchUp (.skp)")


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_func_import)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
