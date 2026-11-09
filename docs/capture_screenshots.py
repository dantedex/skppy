# SPDX-License-Identifier: MIT
"""Capture documentation images in a disposable, foreground Blender session.

Run with factory startup and isolated BLENDER_USER_RESOURCES; see docs/README.md.
The script registers a freshly built addon without installing it permanently.
"""

import argparse
import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import traceback
import zipfile

import bpy
from mathutils import Quaternion


arguments = argparse.ArgumentParser(description=__doc__)
arguments.add_argument("--addon", required=True, type=Path)
arguments.add_argument("--output", required=True, type=Path)
options = arguments.parse_args(sys.argv[sys.argv.index("--") + 1 :])
options.output.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.view.show_splash = False
workspace = TemporaryDirectory(prefix="skppy-docs-")
addon_directory = Path(workspace.name) / "blender_skp_io"
with zipfile.ZipFile(options.addon) as archive:
    archive.extractall(addon_directory)
sys.path.insert(0, workspace.name)
importlib.import_module("blender_skp_io").register()

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for index, (name, color, metallic, roughness) in enumerate(
    (
        ("Terracotta", (0.55, 0.12, 0.04, 1.0), 0.0, 0.8),
        ("Brushed metal", (0.4, 0.5, 0.6, 1.0), 0.9, 0.3),
        ("Blue paint", (0.025, 0.2, 0.65, 1.0), 0.0, 0.4),
    )
):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=(index * 2.6 - 2.6, 0, 0))
    obj = bpy.context.object
    obj.name = name
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = color
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.location = (0, 0)
    material.node_tree.nodes.get("Material Output").location = (360, 0)
    obj.data.materials.append(material)

area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
area.spaces.active.shading.color_type = "MATERIAL"
area.spaces.active.region_3d.view_distance = 13
area.spaces.active.region_3d.view_location = (0, 0, 0)
area.spaces.active.region_3d.view_rotation = Quaternion((0.88, 0.38, 0.12, 0.25)).normalized()


def screenshot(name):
    """Capture only the Blender window, not the surrounding desktop."""
    window = next(
        (
            window
            for window in bpy.context.window_manager.windows
            if any(area.type == "FILE_BROWSER" for area in window.screen.areas)
        ),
        bpy.context.window,
    )
    with bpy.context.temp_override(window=window):
        bpy.ops.screen.screenshot(filepath=str((options.output / name).resolve()))


def cancel_browser():
    """Close the file selector without reading or writing a model."""
    for window in bpy.context.window_manager.windows:
        for browser in window.screen.areas:
            if browser.type == "FILE_BROWSER":
                with bpy.context.temp_override(window=window, area=browser):
                    bpy.ops.file.cancel()
                return
    raise RuntimeError("File selector did not open")


def viewport():
    screenshot("material-demo.png")
    area.type = "NODE_EDITOR"
    area.ui_type = "ShaderNodeTree"
    area.spaces.active.shader_type = "OBJECT"
    area.spaces.active.show_region_ui = False


def frame_nodes():
    """Frame the graph after the new editor has completed its first redraw."""
    region = next(region for region in area.regions if region.type == "WINDOW")
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.node.view_all()
        bpy.ops.view2d.zoom_out()
        bpy.ops.view2d.zoom_out()


def nodes():
    screenshot("principled-material.png")
    area.type = "VIEW_3D"
    bpy.ops.import_scene.skp("INVOKE_DEFAULT", filepath=str(Path(workspace.name) / "demo.skp"))


def import_options():
    screenshot("import-options.png")
    cancel_browser()


def open_export():
    bpy.ops.export_scene.skp("INVOKE_DEFAULT", filepath=str(Path(workspace.name) / "demo.skp"))


def export_options():
    screenshot("export-options.png")
    cancel_browser()


steps = iter((viewport, frame_nodes, nodes, import_options, open_export, export_options))


def advance():
    """Wait for UI redraw between captures and always terminate the session."""
    try:
        step = next(steps, None)
        if step is None:
            workspace.cleanup()
            bpy.ops.wm.quit_blender()
            return None
        step()
        return 3.0
    except Exception:
        traceback.print_exc()
        workspace.cleanup()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(advance, first_interval=5.0)
