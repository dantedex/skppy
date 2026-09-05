# SPDX-License-Identifier: MIT
"""Verify imported image bytes survive standard Blender exporters (issue #2)."""

import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote

import bpy


def run(module_name: str, png_bytes: bytes, *, alpha: float = 1.0) -> None:
    """Inspect actual FBX resource paths/content and glTF image output."""
    skppy = importlib.import_module(module_name).skppy
    builder_type = importlib.import_module(f"{module_name}.scene_builder").BlenderSceneBuilder
    material = builder_type.build_material(
        skppy.Material(
            name="Interchange",
            alpha=alpha,
            has_texture=True,
            texture=skppy.Texture(filename="same.png", data=png_bytes),
        )
    )
    image = next(node.image for node in material.node_tree.nodes if node.type == "TEX_IMAGE")
    assert image.packed_file is not None
    assert Path(image.filepath_raw).read_bytes() == png_bytes
    assert bytes(image.packed_file.data) == png_bytes

    bpy.ops.object.select_all(action="DESELECT")
    mesh = bpy.data.meshes.new("Interchange triangle")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    uv = mesh.uv_layers.new()
    for loop, value in zip(uv.data, [(0, 0), (1, 0), (0, 1)], strict=True):
        loop.uv = value
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Interchange triangle", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.preferences.addon_enable(module="io_scene_fbx")
    bpy.ops.preferences.addon_enable(module="io_scene_gltf2")
    parse_fbx = importlib.import_module("io_scene_fbx.parse_fbx")
    with TemporaryDirectory(prefix="skppy-interchange-") as directory:
        output = Path(directory)
        for path_mode, embed in [("AUTO", False), ("COPY", True)]:
            fbx_path = output / f"{path_mode}.fbx"
            assert bpy.ops.export_scene.fbx(
                filepath=str(fbx_path),
                use_selection=True,
                path_mode=path_mode,
                embed_textures=embed,
            ) == {"FINISHED"}
            root, _ = parse_fbx.parse(str(fbx_path))
            objects = next(child for child in root.elems if child.id == b"Objects")
            videos = [child for child in objects.elems if child.id == b"Video"]
            assert videos, path_mode
            if alpha != 1.0:
                exported_material = next(child for child in objects.elems if child.id == b"Material")
                properties = next(child for child in exported_material.elems if child.id == b"Properties70")
                opacity = next(child.props[-1] for child in properties.elems if child.props[0] == b"Opacity")
                assert abs(opacity - alpha) < 1e-6
            for video in videos:
                fields = {child.id: child.props for child in video.elems}
                if embed:
                    assert fields[b"Content"][0] == png_bytes
                else:
                    assert Path(fields[b"Filename"][0].decode()).read_bytes() == png_bytes

        gltf_path = output / "scene.gltf"
        assert bpy.ops.export_scene.gltf(
            filepath=str(gltf_path),
            export_format="GLTF_SEPARATE",
            use_selection=True,
        ) == {"FINISHED"}
        document = json.loads(gltf_path.read_text())
        assert document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]
        if alpha != 1.0:
            assert abs(document["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][3] - alpha) < 1e-6
        assert len(document["images"]) == 1
        assert (output / unquote(document["images"][0]["uri"])).read_bytes() == png_bytes
