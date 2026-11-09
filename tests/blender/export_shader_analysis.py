# SPDX-License-Identifier: MIT
"""Live Blender assertions for output-driven export surface analysis."""

from __future__ import annotations

import importlib
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from typing import Any
import zlib

import bpy
import numpy as np


def _material(kind: str) -> tuple[Any, Any, Any]:
    material = bpy.data.materials.new("Shader analysis")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    shader = tree.nodes.new(kind)
    tree.links.new(shader.outputs[0], output.inputs["Surface"])
    return material, shader, output


def _supported(analyze: Any) -> None:
    for kind in (
        "ShaderNodeBsdfPrincipled",
        "ShaderNodeBsdfDiffuse",
        "ShaderNodeBsdfGlossy",
        "ShaderNodeBsdfAnisotropic",
        "ShaderNodeBsdfTranslucent",
        "ShaderNodeBsdfTransparent",
        "ShaderNodeBsdfGlass",
        "ShaderNodeBsdfRefraction",
        "ShaderNodeEmission",
    ):
        material, shader, output = _material(kind)
        try:
            shader.name = "Renamed closure"
            color = shader.inputs.get("Base Color") if kind == "ShaderNodeBsdfPrincipled" else shader.inputs["Color"]
            color.default_value = (0.2, 0.4, 0.6, 1)
            if shader.inputs.get("Roughness") is not None:
                shader.inputs["Roughness"].default_value = 0.31
            if kind != "ShaderNodeBsdfPrincipled":
                material.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
            state = analyze(material)
            assert state.color_socket == color and not state.color_socket.is_output
            assert all(abs(actual - expected) < 1e-6 for actual, expected in zip(state.base_color, (0.2, 0.4, 0.6, 1)))
            assert state.alpha == 1
            assert state.metallic == (1 if kind in {"ShaderNodeBsdfGlossy", "ShaderNodeBsdfAnisotropic"} else 0)
            assert not state.bake_color and not state.bake_alpha and state.image is None
            if shader.inputs.get("Roughness") is not None:
                assert abs(state.roughness - 0.31) < 1e-6
            if kind in {"ShaderNodeBsdfGlass", "ShaderNodeBsdfRefraction", "ShaderNodeBsdfTranslucent"}:
                assert any("Transmission" in warning and "opaque" in warning for warning in state.warnings)
            if kind == "ShaderNodeEmission":
                assert any("emission energy" in warning for warning in state.warnings)
            if kind in {"ShaderNodeBsdfGlossy", "ShaderNodeBsdfAnisotropic"}:
                assert any("metallic=1 approximation" in warning for warning in state.warnings)
            if kind == "ShaderNodeBsdfPrincipled":
                assert state.alpha_socket == shader.inputs["Alpha"]
                tree = material.node_tree
                reroute = tree.nodes.new("NodeReroute")
                tree.links.new(shader.outputs[0], reroute.inputs[0])
                tree.links.new(reroute.outputs[0], output.inputs["Surface"])
                assert analyze(material).color_socket == color
        finally:
            bpy.data.materials.remove(material)


def _transparent(analyze: Any) -> None:
    material, shader, _output = _material("ShaderNodeBsdfTransparent")
    try:
        color = shader.inputs["Color"]
        color.default_value = (1, 1, 1, 1)
        state = analyze(material)
        assert state.alpha == 0 and not state.bake_alpha
        assert not any("tinted transmission" in warning for warning in state.warnings)
        for rgba in ((0, 0, 0, 1), (0.5, 0.5, 0.5, 1), (0.2, 0.4, 0.6, 1)):
            color.default_value = rgba
            state = analyze(material)
            assert state.alpha == 1 and not state.bake_alpha
            assert state.base_color == tuple(color.default_value)
            assert not state.bake_color
            assert any("tinted transmission" in warning and "opaque" in warning for warning in state.warnings)
        color.default_value = (1, 1, 1, 1)
        tree = material.node_tree
        rgb = tree.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = (1, 1, 1, 1)
        tree.links.new(rgb.outputs[0], color)
        state = analyze(material)
        assert state.alpha == 1 and not state.bake_alpha
        assert state.bake_color and state.color_socket == color
        assert any("tinted transmission" in warning and "opaque" in warning for warning in state.warnings)
    finally:
        bpy.data.materials.remove(material)


def _fallbacks(analyze: Any) -> None:
    for kind in ("ShaderNodeMixShader", "ShaderNodeAddShader", "ShaderNodeGroup", "ShaderNodeVolumePrincipled"):
        material, _shader, output = _material("ShaderNodeBsdfPrincipled")
        group = None
        try:
            material.diffuse_color = (0.15, 0.25, 0.35, 0.45)
            tree = material.node_tree
            unsupported = tree.nodes.new(kind)
            if kind == "ShaderNodeGroup":
                group = bpy.data.node_groups.new("Unsupported closure", "ShaderNodeTree")
                group.interface.new_socket(name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
                unsupported.node_tree = group
            if kind == "ShaderNodeVolumePrincipled":
                tree.links.new(unsupported.outputs[0], output.inputs["Volume"])
            else:
                tree.links.new(unsupported.outputs[0], output.inputs["Surface"])
            state = analyze(material)
            assert state.base_color == tuple(material.diffuse_color)
            assert state.color_socket is None and state.alpha_socket is None
            assert state.image is None and not state.bake_color and not state.bake_alpha
            assert any("viewport fallback" in warning for warning in state.warnings)
        finally:
            bpy.data.materials.remove(material)
            if group is not None:
                bpy.data.node_groups.remove(group)
    material, _shader, output = _material("ShaderNodeBsdfPrincipled")
    try:
        material.node_tree.links.remove(output.inputs["Surface"].links[0])
        assert any("viewport fallback" in warning for warning in analyze(material).warnings)
        output.target = "EEVEE"
        assert any("Cycles/ALL" in warning for warning in analyze(material).warnings)
        cycles = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
        cycles.target = "CYCLES"
        cycles.is_active_output = True
        diffuse = material.node_tree.nodes.new("ShaderNodeBsdfDiffuse")
        material.node_tree.links.new(diffuse.outputs[0], cycles.inputs["Surface"])
        state = analyze(material)
        assert state.color_socket == diffuse.inputs["Color"]
        assert any("target mismatch" in warning for warning in state.warnings)
        output.is_active_output = True
        assert analyze(material).color_socket == diffuse.inputs["Color"]
    finally:
        bpy.data.materials.remove(material)


def _expressions(analyze: Any) -> None:
    material, shader, output = _material("ShaderNodeBsdfPrincipled")
    group = None
    try:
        tree = material.node_tree
        noise = tree.nodes.new("ShaderNodeTexNoise")
        reroute = tree.nodes.new("NodeReroute")
        tree.links.new(noise.outputs["Color"], reroute.inputs[0])
        tree.links.new(reroute.outputs[0], shader.inputs["Base Color"])
        tree.links.new(noise.outputs["Fac"], shader.inputs["Alpha"])
        tree.links.new(noise.outputs["Fac"], shader.inputs["Metallic"])
        tree.links.new(noise.outputs["Fac"], shader.inputs["Roughness"])
        tree.links.new(noise.outputs["Color"], shader.inputs["Normal"])
        tree.links.new(noise.outputs["Fac"], output.inputs["Displacement"])
        shader.inputs["IOR"].default_value = 2
        shader.inputs["Emission Color"].default_value = (1, 0, 0, 1)
        shader.inputs["Emission Strength"].default_value = 2
        shader.inputs["Metallic"].default_value = 0.27
        shader.inputs["Roughness"].default_value = 0.63
        state = analyze(material)
        assert state.bake_color and state.bake_alpha and state.image is None
        assert state.color_socket == shader.inputs["Base Color"]
        assert state.alpha_socket == shader.inputs["Alpha"]
        assert abs(state.metallic - 0.27) < 1e-6 and abs(state.roughness - 0.63) < 1e-6
        for fragment in ("Metallic map", "Roughness map", "Normal map", "displacement", "IOR", "emission"):
            assert any(fragment in warning for warning in state.warnings), fragment
        group = bpy.data.node_groups.new("Color expression", "ShaderNodeTree")
        group.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        group_output = group.nodes.new("NodeGroupOutput")
        group_noise = group.nodes.new("ShaderNodeTexNoise")
        group.links.new(group_noise.outputs["Color"], group_output.inputs["Color"])
        expression = tree.nodes.new("ShaderNodeGroup")
        expression.node_tree = group
        tree.links.new(expression.outputs["Color"], shader.inputs["Base Color"])
        state = analyze(material)
        assert state.bake_color and not any("viewport fallback" in warning for warning in state.warnings)
        for kind, socket_name in (
            ("ShaderNodeObjectInfo", "Color"),
            ("ShaderNodeCameraData", "View Vector"),
            ("ShaderNodeLightPath", "Is Camera Ray"),
            ("ShaderNodeShaderToRGB", "Color"),
        ):
            context = tree.nodes.new(kind)
            tree.links.new(context.outputs[socket_name], shader.inputs["Base Color"])
            state = analyze(material)
            assert state.bake_color
            assert any(kind in warning and "Context-dependent" in warning for warning in state.warnings)
    finally:
        bpy.data.materials.remove(material)
        if group is not None:
            bpy.data.node_groups.remove(group)


def _images(analyze: Any) -> None:
    material, shader, _output = _material("ShaderNodeBsdfPrincipled")
    generated = bpy.data.images.new("Generated analysis pixels", width=2, height=2)
    loaded = None
    try:
        tree = material.node_tree
        image_node = tree.nodes.new("ShaderNodeTexImage")
        image_node.image = generated
        tree.links.new(image_node.outputs["Color"], shader.inputs["Base Color"])
        assert analyze(material).bake_color and analyze(material).image is None
        with TemporaryDirectory(prefix="skppy-shader-analysis-") as directory:
            generated.filepath_raw = str(Path(directory) / "color.png")
            generated.file_format = "PNG"
            generated.save()
            loaded = bpy.data.images.load(generated.filepath_raw, check_existing=False)
            loaded.pack()
            image_node.image = loaded
            reroute = tree.nodes.new("NodeReroute")
            tree.links.new(image_node.outputs["Color"], reroute.inputs[0])
            tree.links.new(reroute.outputs[0], shader.inputs["Base Color"])
            state = analyze(material)
            assert state.image == loaded and not state.bake_color
            for color_space in ("Non-Color", "Linear Rec.709"):
                loaded.colorspace_settings.name = color_space
                state = analyze(material)
                assert state.image is None and state.bake_color
                assert state.color_socket == shader.inputs["Base Color"]
            loaded.colorspace_settings.name = "sRGB"
            state = analyze(material)
            assert state.image == loaded and not state.bake_color
            tree.links.new(image_node.outputs["Alpha"], shader.inputs["Alpha"])
            state = analyze(material)
            assert state.preserve_image_alpha and not state.bake_alpha and state.alpha == 1
            tree.links.new(image_node.outputs["Alpha"], shader.inputs["Base Color"])
            assert analyze(material).bake_color and analyze(material).image is None
            tree.links.new(reroute.outputs[0], shader.inputs["Base Color"])
            coordinates = tree.nodes.new("ShaderNodeTexCoord")
            vector_route = tree.nodes.new("NodeReroute")
            tree.links.new(coordinates.outputs["UV"], vector_route.inputs[0])
            tree.links.new(vector_route.outputs[0], image_node.inputs["Vector"])
            assert analyze(material).image == loaded
            tree.links.new(coordinates.outputs["Generated"], vector_route.inputs[0])
            assert analyze(material).bake_color
            uv = tree.nodes.new("ShaderNodeUVMap")
            uv.uv_map = "Builder must validate this UV map"
            tree.links.new(uv.outputs["UV"], vector_route.inputs[0])
            assert analyze(material).image == loaded
            mapping = tree.nodes.new("ShaderNodeMapping")
            tree.links.new(mapping.outputs[0], image_node.inputs["Vector"])
            assert analyze(material).bake_color and analyze(material).image is None
            tree.links.remove(image_node.inputs["Vector"].links[0])
            invert = tree.nodes.new("ShaderNodeInvert")
            tree.links.new(image_node.outputs["Color"], invert.inputs["Color"])
            tree.links.new(invert.outputs[0], shader.inputs["Base Color"])
            assert analyze(material).bake_color and analyze(material).image is None
            tree.links.new(image_node.outputs["Color"], shader.inputs["Base Color"])
            loaded.pixels[0] = 0.5
            loaded.update()
            assert loaded.is_dirty
            assert analyze(material).bake_color and analyze(material).image is None
    finally:
        bpy.data.materials.remove(material)
        bpy.data.images.remove(generated)
        if loaded is not None:
            bpy.data.images.remove(loaded)


def _rgba_png(width: int, height: int, rows: bytes) -> bytes:
    """Build an independent unfiltered RGBA fixture in top-down PNG row order."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def _assert_opaque_png(data: bytes, source_rows: bytes) -> None:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    compressed = bytearray()
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        checksum = struct.unpack_from(">I", data, offset + 8 + length)[0]
        assert checksum == zlib.crc32(kind + payload)
        if kind == b"IHDR":
            assert struct.unpack(">IIBBBBB", payload) == (3, 2, 8, 6, 0, 0, 0)
        if kind == b"IDAT":
            compressed.extend(payload)
        offset += 12 + length
    assert offset == len(data)
    rows = zlib.decompress(compressed)
    assert len(rows) == len(source_rows) == 26
    for start in (0, 13):
        assert rows[start] == 0
        for pixel in range(3):
            index = start + 1 + pixel * 4
            assert all(abs(rows[index + channel] - source_rows[index + channel]) <= 1 for channel in range(3))
            assert rows[index + 3] == 255


def _image_alpha(module: Any) -> None:
    material, shader, _output = _material("ShaderNodeBsdfPrincipled")
    images = []
    rows = bytes(
        (0, 64, 128, 192, 0, 255, 0, 128, 64, 12, 90, 200, 255, 0, 0, 255, 0, 128, 180, 100, 20, 200, 128, 64, 32, 255)
    )
    original = _rgba_png(3, 2, rows)
    opaque_rows = bytearray(rows)
    for start in (0, 13):
        for pixel in range(3):
            opaque_rows[start + 4 + pixel * 4] = 255
    opaque_original = _rgba_png(3, 2, opaque_rows)
    try:
        with TemporaryDirectory(prefix="skppy-image-alpha-") as directory:
            path = Path(directory) / "transparent.png"
            path.write_bytes(original)
            image = bpy.data.images.load(str(path), check_existing=False)
            images.append(image)
            assert module.direct_image_bytes(image, preserve_alpha=True) == original
            image.pack()
            pixels = tuple(image.pixels)
            dirty = image.is_dirty
            tree = material.node_tree
            texture = tree.nodes.new("ShaderNodeTexImage")
            texture.image = image
            tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
            shader.inputs["Alpha"].default_value = 0.8
            state = module.analyze_material(material)
            assert state.image == image and not state.bake_color and not state.bake_alpha
            assert not state.preserve_image_alpha and abs(state.alpha - 0.8) < 1e-6
            exported = module.direct_image_bytes(image)
            _assert_opaque_png(exported, rows)
            assert path.read_bytes() == original and bytes(image.packed_file.data) == original
            assert tuple(image.pixels) == pixels and image.is_dirty == dirty
            assert module.direct_image_bytes(image, preserve_alpha=True) == original
            route = tree.nodes.new("NodeReroute")
            tree.links.new(texture.outputs["Alpha"], route.inputs[0])
            tree.links.new(route.outputs[0], shader.inputs["Alpha"])
            state = module.analyze_material(material)
            assert state.preserve_image_alpha and not state.bake_alpha and state.alpha == 1
            assert state.alpha_socket == shader.inputs["Alpha"]
            assert module.direct_image_bytes(image, preserve_alpha=state.preserve_image_alpha) == original
            multiply = tree.nodes.new("ShaderNodeMath")
            multiply.operation = "MULTIPLY"
            tree.links.new(route.outputs[0], multiply.inputs[0])
            tree.links.new(multiply.outputs[0], shader.inputs["Alpha"])
            state = module.analyze_material(material)
            assert state.bake_alpha and not state.preserve_image_alpha and state.image == image
            other_texture = tree.nodes.new("ShaderNodeTexImage")
            other_texture.image = image
            tree.links.new(other_texture.outputs["Alpha"], shader.inputs["Alpha"])
            state = module.analyze_material(material)
            assert state.bake_alpha and not state.preserve_image_alpha
            for alpha_mode in ("PREMUL", "CHANNEL_PACKED", "NONE"):
                image.alpha_mode = alpha_mode
                state = module.analyze_material(material)
                assert state.bake_color and state.image is None and not state.preserve_image_alpha
                assert module.direct_image_bytes(image) is None
            image.alpha_mode = "STRAIGHT"
            assert path.read_bytes() == original and bytes(image.packed_file.data) == original
            opaque_path = Path(directory) / "opaque.png"
            opaque_path.write_bytes(opaque_original)
            opaque = bpy.data.images.load(str(opaque_path), check_existing=False)
            images.append(opaque)
            assert module.direct_image_bytes(opaque) == opaque_original
            opaque.pack()
            assert module.direct_image_bytes(opaque) == opaque_original
            linear_pixels = np.tile([0.5, 0.21404114, 0.0031308, 0.25], (2, 3, 1))
            expected_rows = bytes([0] + [188, 128, 10, 255] * 3) * 2
            _assert_opaque_png(module._opaque_png(linear_pixels, 3, 2, linear_rgb=True), expected_rows)
    finally:
        bpy.data.materials.remove(material)
        for image in images:
            bpy.data.images.remove(image)


def run(module_name: str) -> None:
    """Check supported closures, output selection, fallbacks, and bake classification."""
    module = importlib.import_module(f"{module_name}.export_materials")
    analyze = module.analyze_material
    _supported(analyze)
    _transparent(analyze)
    _fallbacks(analyze)
    _expressions(analyze)
    _images(analyze)
    _image_alpha(module)
