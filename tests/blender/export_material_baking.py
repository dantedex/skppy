# SPDX-License-Identifier: MIT
"""Isolated live CPU Cycles material-baking assertions; callable by the parent runner."""

from __future__ import annotations

import importlib
import struct
import zlib
from typing import Any
from unittest.mock import patch

import bpy
import numpy as np


def _datablocks() -> tuple[Any, ...]:
    return tuple(
        tuple(item.as_pointer() for item in collection)
        for collection in (
            bpy.data.scenes,
            bpy.data.objects,
            bpy.data.meshes,
            bpy.data.materials,
            bpy.data.images,
            bpy.data.actions,
            bpy.data.curves,
            bpy.data.node_groups,
        )
    )


def _snapshot(obj: Any, material: Any) -> tuple[Any, ...]:
    mesh = obj.data
    tree = material.node_tree
    return (
        _datablocks(),
        bpy.context.scene.as_pointer(),
        bpy.context.scene.render.engine,
        bpy.context.scene.frame_current,
        bpy.context.scene.frame_subframe,
        bpy.context.mode,
        tuple(item.as_pointer() for item in bpy.context.selected_objects),
        bpy.context.view_layer.objects.active,
        tuple(tuple(row) for row in obj.matrix_world),
        tuple(vertex.co[:] for vertex in mesh.vertices),
        tuple((tuple(face.vertices), face.material_index) for face in mesh.polygons),
        tuple(
            (layer.name, layer.active_render, tuple(value.uv[:] for value in layer.data)) for layer in mesh.uv_layers
        ),
        mesh.uv_layers.active_index,
        tuple((node.name, node.select) for node in tree.nodes),
        tree.nodes.active,
        tuple((link.from_socket.as_pointer(), link.to_socket.as_pointer()) for link in tree.links),
        tuple((slot.link, slot.material) for slot in obj.material_slots),
    )


def _decode_png(data: bytes) -> np.ndarray:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    compressed = b""
    width = height = 0
    while offset < len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + size]
        crc = struct.unpack_from(">I", data, offset + 8 + size)[0]
        assert zlib.crc32(kind + payload) == crc
        if kind == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            assert (depth, color, compression, filtering, interlace) == (8, 6, 0, 0, 0)
        elif kind == b"IDAT":
            compressed += payload
        offset += size + 12
    raw = np.frombuffer(zlib.decompress(compressed), dtype=np.uint8).reshape(height, width * 4 + 1)
    assert not raw[:, 0].any()
    return raw[:, 1:].reshape(height, width, 4)


def _assert_pixel(pixels: np.ndarray, x: int, y: int, expected: tuple[int, ...], tolerance: int = 2) -> None:
    actual = pixels[y, x].astype(int)
    assert np.max(np.abs(actual - expected)) <= tolerance, (x, y, actual, expected)


def _fixture() -> tuple[Any, Any, Any, Any, Any]:
    material = bpy.data.materials.new("Bake helper target")
    material.use_nodes = True
    tree = material.node_tree
    shader = tree.nodes.get("Principled BSDF")
    shader.name = "Renamed bake closure"
    image = bpy.data.images.new("Bake helper asymmetric checker", width=2, height=2, alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "STRAIGHT"
    image.pixels[:] = (1, 0, 0.25, 0.2, 0, 1, 0.5, 0.4, 0.25, 0.5, 1, 0.6, 0.5, 0.25, 0, 0.8)
    image.update()
    texture = tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Closest"
    tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    mesh = bpy.data.meshes.new("Bake helper final mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    source = mesh.uv_layers.new(name="Source render UV")
    destination = mesh.uv_layers.new(name="Destination bake UV")
    for index, uv in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        source.data[index].uv = (1 - uv[0], uv[1])
        destination.data[index].uv = uv
    source.active_render = True
    mesh.uv_layers.active_index = 1
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Bake helper source", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (7, -3, 2)
    obj.rotation_euler = (0.2, 0.3, 0.4)
    obj.scale = (2, 3, 1)
    bpy.context.view_layer.update()
    return obj, material, shader, texture, image


def _bake_unchanged(baker: Any, obj: Any, material: Any, state: Any, **settings: Any) -> np.ndarray:
    before = _snapshot(obj, material)
    result = baker.bake_material(bpy.context, obj, obj.data, material, state, **settings)
    assert _snapshot(obj, material) == before, "Bake mutated source/context or leaked temporary datablocks"
    return _decode_png(result)


def _expect_failure(baker: Any, obj: Any, material: Any, state: Any, fragment: str, **settings: Any) -> None:
    before = _snapshot(obj, material)
    try:
        baker.bake_material(bpy.context, obj, obj.data, material, state, **settings)
    except ValueError as exc:
        assert fragment.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError(f"Expected material bake failure containing {fragment!r}")
    assert _snapshot(obj, material) == before, "Failed bake mutated source/context or leaked datablocks"


def _colors_and_alpha(baker: Any, analyze: Any, obj: Any, material: Any, shader: Any, texture: Any) -> None:
    state = analyze(material)
    pixels = _bake_unchanged(baker, obj, material, state, resolution=32, margin=0)
    _assert_pixel(pixels, 8, 8, (188, 137, 0, 204))
    _assert_pixel(pixels, 24, 8, (137, 188, 255, 153))
    _assert_pixel(pixels, 8, 24, (0, 255, 188, 102))
    _assert_pixel(pixels, 24, 24, (255, 0, 137, 51))

    tree = material.node_tree
    tree.links.remove(shader.inputs["Alpha"].links[0])
    shader.inputs["Alpha"].default_value = 0.25
    pixels = _bake_unchanged(baker, obj, material, analyze(material), resolution=32, margin=2)
    _assert_pixel(pixels, 8, 8, (188, 137, 0, 64))

    tree.links.remove(shader.inputs["Base Color"].links[0])
    shader.inputs["Base Color"].default_value = (0.25, 0.5, 1, 0.1)
    tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    pixels = _bake_unchanged(baker, obj, material, analyze(material), resolution=32, margin=0)
    _assert_pixel(pixels, 8, 8, (137, 188, 255, 204))
    _assert_pixel(pixels, 24, 24, (137, 188, 255, 51))

    # A direct image color must also be fully resampled when only alpha needs baking.
    tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    state = analyze(material)
    state.bake_color = False
    state.image = texture.image
    pixels = _bake_unchanged(baker, obj, material, state, resolution=32, margin=0)
    _assert_pixel(pixels, 8, 8, (188, 137, 0, 204))

    # Color-to-float conversion must happen before emission, not by extracting red.
    tree.links.new(texture.outputs["Color"], shader.inputs["Alpha"])
    pixels = _bake_unchanged(baker, obj, material, analyze(material), resolution=32, margin=0)
    # Cycles converts color to linear luminance: 0.2126 * 0.5 + 0.7152 * 0.25.
    _assert_pixel(pixels, 8, 8, (188, 137, 0, 73))
    value = tree.nodes.new("ShaderNodeValue")
    for scalar, expected in ((-0.5, 0), (1.5, 255)):
        value.outputs[0].default_value = scalar
        tree.links.new(value.outputs[0], shader.inputs["Alpha"])
        pixels = _bake_unchanged(baker, obj, material, analyze(material), resolution=16, margin=0)
        _assert_pixel(pixels, 4, 4, (188, 137, 0, expected))
    tree.nodes.remove(value)
    tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])


def _groups(baker: Any, analyze: Any, obj: Any, material: Any, shader: Any, texture: Any) -> None:
    group = bpy.data.node_groups.new("Bake helper expression group", "ShaderNodeTree")
    group.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    output = group.nodes.new("NodeGroupOutput")
    color = group.nodes.new("ShaderNodeRGB")
    color.outputs[0].default_value = (0.25, 0.5, 1, 1)
    group.links.new(color.outputs[0], output.inputs["Color"])
    tree = material.node_tree
    node = tree.nodes.new("ShaderNodeGroup")
    node.node_tree = group
    tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
    try:
        pixels = _bake_unchanged(baker, obj, material, analyze(material), resolution=16, margin=0)
        _assert_pixel(pixels, 4, 4, (137, 188, 255, 204))
        unsafe = group.nodes.new("ShaderNodeObjectInfo")
        group.links.new(unsafe.outputs["Color"], output.inputs["Color"])
        _expect_failure(baker, obj, material, analyze(material), "context-dependent", resolution=16, margin=0)
    finally:
        tree.nodes.remove(node)
        bpy.data.node_groups.remove(group)
        tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])


def _failures(baker: Any, analyze: Any, obj: Any, material: Any, shader: Any, texture: Any) -> None:
    settings = {"resolution": 16, "margin": 0}
    state = analyze(material)
    for resolution in (False, 15, 4097, 16.5):
        _expect_failure(baker, obj, material, state, "resolution", resolution=resolution, margin=0)
    for margin in (-1, 17, 0.5, True):
        _expect_failure(baker, obj, material, state, "margin", resolution=16, margin=margin)
    uv = obj.data.uv_layers.active
    original = uv.data[0].uv[:]
    uv.data[0].uv = (-0.1, 0)
    _expect_failure(baker, obj, material, state, "inside", **settings)
    uv.data[0].uv = uv.data[1].uv
    _expect_failure(baker, obj, material, state, "nondegenerate", **settings)
    uv.data[0].uv = original
    tree = material.node_tree
    for kind, output in (
        ("ShaderNodeObjectInfo", "Color"),
        ("ShaderNodeLightPath", "Is Camera Ray"),
        ("ShaderNodeShaderToRGB", "Color"),
        ("ShaderNodeCameraData", "View Vector"),
        ("ShaderNodeNewGeometry", "Position"),
        ("ShaderNodeNewGeometry", "Normal"),
    ):
        node = tree.nodes.new(kind)
        tree.links.new(node.outputs[output], shader.inputs["Base Color"])
        _expect_failure(baker, obj, material, analyze(material), "context-dependent", **settings)
        tree.nodes.remove(node)
    tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    # Inject failures both before baking and after successful context overrides.
    for helper in ("_bake_pass", "_encode_png"):
        with patch.object(baker, helper, side_effect=RuntimeError("injected Cycles failure")):
            _expect_failure(baker, obj, material, analyze(material), "injected Cycles", **settings)


def _source_time(baker: Any, analyze: Any, obj: Any, material: Any, shader: Any, texture: Any) -> None:
    scene = bpy.context.scene
    original_time = (scene.frame_current, scene.frame_subframe)
    tree = material.node_tree
    color = tree.nodes.new("ShaderNodeRGB")
    value = tree.nodes.new("ShaderNodeValue")
    try:
        for frame, rgb, alpha in ((19, (0, 0, 1, 1), 0.2), (20, (0.5, 1, 1, 1), 0.6)):
            color.outputs[0].default_value = rgb
            color.outputs[0].keyframe_insert("default_value", frame=frame)
            value.outputs[0].default_value = alpha
            value.outputs[0].keyframe_insert("default_value", frame=frame)
        tree.links.new(color.outputs[0], shader.inputs["Base Color"])
        tree.links.new(value.outputs[0], shader.inputs["Alpha"])
        scene.frame_set(19, subframe=0.5)
        pixels = _bake_unchanged(baker, obj, material, analyze(material), resolution=16, margin=0)
        _assert_pixel(pixels, 4, 4, (137, 188, 255, 102))
    finally:
        action = tree.animation_data.action if tree.animation_data else None
        tree.animation_data_clear()
        tree.nodes.remove(color)
        tree.nodes.remove(value)
        if action is not None:
            bpy.data.actions.remove(action)
        tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
        scene.frame_set(original_time[0], subframe=original_time[1])


def _unsupported_images_and_drivers(
    baker: Any, analyze: Any, obj: Any, material: Any, shader: Any, texture: Any
) -> None:
    original_image = texture.image
    image = bpy.data.images.new("Bake helper unsupported source", width=2, height=2)
    try:
        texture.image = image
        for source in ("SEQUENCE", "MOVIE", "TILED"):
            image.source = source
            _expect_failure(baker, obj, material, analyze(material), source, resolution=16, margin=0)
    finally:
        texture.image = original_image
        bpy.data.images.remove(image)
    # Scene-ID variables are a concrete original-scene dependency. Scripted
    # bpy.context expressions are also rejected, without attempting to execute them.
    tree = material.node_tree
    value = tree.nodes.new("ShaderNodeValue")
    tree.links.new(value.outputs[0], shader.inputs["Alpha"])
    try:
        curve = value.outputs[0].driver_add("default_value")
        variable = curve.driver.variables.new()
        variable.name = "source_frame"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id_type = "SCENE"
        variable.targets[0].id = bpy.context.scene
        variable.targets[0].data_path = "frame_current"
        curve.driver.expression = "source_frame / 100"
        _expect_failure(baker, obj, material, analyze(material), "drivers", resolution=16, margin=0)
        curve.driver.expression = "bpy.context.scene.frame_current / 100"
        _expect_failure(baker, obj, material, analyze(material), "drivers", resolution=16, margin=0)
    finally:
        value.outputs[0].driver_remove("default_value")
        tree.animation_data_clear()
        tree.nodes.remove(value)
        tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    driver = material.driver_add("diffuse_color", 0)
    driver.driver.expression = "0.25"
    try:
        _expect_failure(baker, obj, material, analyze(material), "drivers", resolution=16, margin=0)
    finally:
        material.driver_remove("diffuse_color", 0)
        material.animation_data_clear()


def _vertical_uvs(baker: Any, analyze: Any, obj: Any, material: Any) -> None:
    original = obj.data
    mesh = bpy.data.meshes.new("Bake helper vertical islands")
    count = 2048
    vertices = []
    for index in range(count):
        bottom = index / count
        top = (index + 0.5) / count
        vertices.extend(((0, bottom, 0), (1, bottom, 0), (0, top, 0)))
    try:
        mesh.from_pydata(vertices, [], [(index * 3, index * 3 + 1, index * 3 + 2) for index in range(count)])
        mesh.materials.append(material)
        uv = mesh.uv_layers.new(name="Vertically disjoint")
        for index, vertex in enumerate(vertices):
            uv.data[index].uv = vertex[:2]
        obj.data = mesh
        # U bounds coincide for every island, but no pair has overlapping V.
        with patch.object(baker, "_triangles_overlap", side_effect=AssertionError("Unnecessary NumPy SAT test")):
            assert baker._validate_uv(mesh, {0}) == uv.name
        with patch.object(baker, "_MAX_UV_PAIR_CHECKS", 1):
            _expect_failure(baker, obj, material, analyze(material), "candidate-work limit", resolution=16, margin=0)
    finally:
        obj.data = original
        bpy.data.meshes.remove(mesh)


def _converted_curve(baker: Any, analyze: Any, material: Any) -> None:
    curve = bpy.data.curves.new("Bake helper source curve", "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    spline = curve.splines.new("POLY")
    spline.points.add(3)
    for point, xy in zip(spline.points, ((0, 0), (1, 0), (1, 1), (0, 1))):
        point.co = (*xy, 0, 1)
    spline.use_cyclic_u = True
    curve.materials.append(material)
    obj = bpy.data.objects.new("Bake helper converted curve", curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (7, -5, 3)
    obj.rotation_euler = (0.2, 0.3, 0.4)
    obj.scale = (2, 3, 1)
    mesh = None
    try:
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), depsgraph=depsgraph)
        uv = mesh.uv_layers.new(name="Converted destination")
        mesh.uv_layers.active_index = len(mesh.uv_layers) - 1
        uv.active_render = True
        for loop in mesh.loops:
            uv.data[loop.index].uv = mesh.vertices[loop.vertex_index].co[:2]
        before = _datablocks()
        transform = tuple(tuple(row) for row in obj.matrix_world)
        points = tuple(point.co[:] for point in spline.points)
        source_time = (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe)
        pixels = _decode_png(
            baker.bake_material(
                bpy.context,
                obj,
                mesh,
                material,
                analyze(material),
                resolution=16,
                margin=0,
            )
        )
        _assert_pixel(pixels, 4, 4, (137, 188, 255, 153))
        assert _datablocks() == before
        assert obj.type == "CURVE" and obj.data == curve
        assert tuple(tuple(row) for row in obj.matrix_world) == transform
        assert tuple(point.co[:] for point in spline.points) == points
        assert (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe) == source_time
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None:
            bpy.data.meshes.remove(mesh)
        bpy.data.curves.remove(curve)


def _generated_and_slots(baker: Any, analyze: Any, obj: Any, material: Any, shader: Any) -> None:
    tree = material.node_tree
    coordinates = tree.nodes.new("ShaderNodeTexCoord")
    tree.links.new(coordinates.outputs["Generated"], shader.inputs["Base Color"])
    tree.links.remove(shader.inputs["Alpha"].links[0])
    shader.inputs["Alpha"].default_value = 1
    dummy = bpy.data.materials.new("Bake helper other slot")
    dummy.diffuse_color = (1, 0, 1, 1)
    original = obj.data
    mesh = bpy.data.meshes.new("Bake helper complete bounds")
    second = bpy.data.objects.new("Bake helper second context", original)
    bpy.context.scene.collection.objects.link(second)
    second.location = (-4, 11, -3)
    second.rotation_euler = (-0.1, 0.5, 0.7)
    second.scale = (3, 1, 2)
    bpy.context.view_layer.update()
    try:
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (3, 0, 0), (4, 0, 0), (4, 1, 0), (3, 1, 0)],
            [],
            [(0, 1, 2, 3), (4, 5, 6, 7)],
        )
        uv = mesh.uv_layers.new(name="Generated destination")
        for index, point in enumerate(((0, 0), (1, 0), (1, 1), (0, 1)) * 2):
            uv.data[index].uv = point
        mesh.materials.append(material)
        mesh.materials.append(dummy)
        mesh.materials.append(material)
        mesh.polygons[0].material_index = 2
        mesh.polygons[1].material_index = 1
        obj.data = mesh
        pixels = _bake_unchanged(baker, obj, material, analyze(material), resolution=32, margin=0)
        # UV center is local x=0.515625, Generated x=0.12890625 because
        # non-target geometry extends the complete bounds to x=4.
        _assert_pixel(pixels, 16, 15, (101, 190, 188, 255), tolerance=3)
        # Object-linked material overrides must be honored without mutation.
        obj.material_slots[2].link = "OBJECT"
        obj.material_slots[2].material = material
        mesh.materials[2] = dummy
        _bake_unchanged(baker, obj, material, analyze(material), resolution=16, margin=0)
        obj.material_slots[2].link = "DATA"
        mesh.materials[2] = material
        # The same material on another object has different Generated bounds.
        pixels = _bake_unchanged(baker, second, material, analyze(material), resolution=32, margin=0)
        _assert_pixel(pixels, 16, 15, (190, 190, 188, 255), tolerance=3)
        # Default Object coordinates must remain object-local despite distinct transforms.
        tree.links.new(coordinates.outputs["Object"], shader.inputs["Base Color"])
        pixels = _bake_unchanged(baker, second, material, analyze(material), resolution=32, margin=0)
        _assert_pixel(pixels, 16, 15, (190, 190, 0, 255), tolerance=3)
        tree.links.new(coordinates.outputs["Generated"], shader.inputs["Base Color"])
        mesh.polygons[1].material_index = 0
        _expect_failure(baker, obj, material, analyze(material), "overlapping", resolution=16, margin=0)
        mesh.polygons[1].material_index = 1
        mesh.uv_layers.remove(uv)
        _expect_failure(baker, obj, material, analyze(material), "existing active", resolution=16, margin=0)
    finally:
        obj.data = original
        bpy.data.objects.remove(second, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        bpy.data.materials.remove(dummy)
        tree.nodes.remove(coordinates)


def run(module_name: str) -> None:
    """Check pixel orientation, scalar alpha, UV/slot isolation, errors, and cleanup."""
    baker = importlib.import_module(f"{module_name}.material_baker")
    analyze = importlib.import_module(f"{module_name}.export_materials").analyze_material
    baseline = _datablocks()
    obj, material, shader, texture, image = _fixture()
    mesh = obj.data
    try:
        _colors_and_alpha(baker, analyze, obj, material, shader, texture)
        _groups(baker, analyze, obj, material, shader, texture)
        _failures(baker, analyze, obj, material, shader, texture)
        _source_time(baker, analyze, obj, material, shader, texture)
        _unsupported_images_and_drivers(baker, analyze, obj, material, shader, texture)
        _vertical_uvs(baker, analyze, obj, material)
        _converted_curve(baker, analyze, material)
        _generated_and_slots(baker, analyze, obj, material, shader)
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        bpy.data.materials.remove(material)
        bpy.data.images.remove(image)
    assert _datablocks() == baseline, "Material bake live helper leaked its own fixtures"
