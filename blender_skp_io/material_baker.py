# SPDX-License-Identifier: MIT
"""Bake export-only base color and scalar alpha in an isolated CPU Cycles scene."""

from __future__ import annotations

import math
import struct
import zlib
from typing import Any

import bpy
import numpy as np

from .export_materials import SurfaceState


_CONTEXT_NODES = {
    "ShaderNodeObjectInfo",
    "ShaderNodeCameraData",
    "ShaderNodeLightPath",
    "ShaderNodeShaderToRGB",
    "ShaderNodeParticleInfo",
    "ShaderNodeHairInfo",
}
_UV_EPSILON = 1e-10
_MAX_UV_PAIR_CHECKS = 1_000_000


def _validate_settings(resolution: int, margin: int) -> None:
    if type(resolution) is not int or not 16 <= resolution <= 4096:
        raise ValueError("Material bake resolution must be an integer in [16, 4096]")
    if type(margin) is not int or not 0 <= margin <= resolution:
        raise ValueError("Material bake margin must be an integer in [0, resolution]")


def _validate_drivers(datablock: Any) -> None:
    animation = datablock.animation_data
    if animation is not None and animation.drivers:
        # Drivers can read the original scene or bpy.context via expressions.
        # Their dependency semantics are not preserved by copying into a scene.
        raise ValueError(f"Material baking does not support drivers on {datablock.name!r}")


def _validate_expression_source(source: Any) -> None:
    node = source.node
    kind = node.bl_idname
    _validate_drivers(source.id_data)
    unsafe = kind in _CONTEXT_NODES
    unsafe |= kind == "ShaderNodeNewGeometry" and source.name in {"Position", "Normal", "True Normal", "Incoming"}
    unsafe |= kind == "ShaderNodeTexCoord" and (
        node.from_instancer or source.name in {"Camera", "Window", "Reflection", "Normal"}
    )
    unsafe |= kind == "ShaderNodeUVMap" and node.from_instancer
    if unsafe:
        raise ValueError(f"Context-dependent material bake source {kind}.{source.name} is unsupported")
    if kind == "ShaderNodeTexImage" and node.image is not None and node.image.source in {"SEQUENCE", "MOVIE", "TILED"}:
        raise ValueError(f"Material baking does not support {node.image.source} image textures (sequence/movie/UDIM)")


def _validate_expression(socket: Any | None) -> None:
    pending = [link.from_socket for link in socket.links] if socket is not None else []
    visited = set()
    while pending:
        source = pending.pop()
        node = source.node
        key = source.as_pointer()
        if key in visited:
            continue
        visited.add(key)
        _validate_expression_source(source)
        if node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None:
            _validate_drivers(node.node_tree)
            # Shared group trees remain read-only. Conservatively inspect their
            # outputs as well as the external group inputs, including nested groups.
            for child in node.node_tree.nodes:
                if child.bl_idname == "NodeGroupOutput" and child.is_active_output:
                    pending.extend(link.from_socket for value in child.inputs for link in value.links)
        pending.extend(link.from_socket for value in node.inputs for link in value.links)


def _triangles_overlap(first: np.ndarray, second: np.ndarray) -> bool:
    for triangle in (first, second):
        for index in range(3):
            edge = triangle[(index + 1) % 3] - triangle[index]
            axis = np.array((-edge[1], edge[0]))
            a = first @ axis
            b = second @ axis
            # Boundary contact is valid; only positive-area intersections conflict.
            if min(a.max(), b.max()) - max(a.min(), b.min()) <= _UV_EPSILON:
                return False
    return True


def _validate_overlaps(triangles: list[Any]) -> None:
    # Sweep U within V bins: vertically separated islands must not trigger a
    # quadratic number of NumPy SAT tests. Bound bucket scans too, not just SAT.
    bin_count = min(256, max(1, math.isqrt(len(triangles))))
    buckets: dict[int, dict[int, Any]] = {}
    work = 0
    for index, (left, right, bottom, top, points) in enumerate(sorted(triangles, key=lambda item: item[0])):
        candidates = {}
        first = min(bin_count - 1, int(bottom * bin_count))
        last = min(bin_count - 1, int(top * bin_count))
        for key in range(first, last + 1):
            previous = buckets.get(key, {})
            work += len(previous) + 1
            if work > _MAX_UV_PAIR_CHECKS:
                raise ValueError(
                    "Material bake UV overlap validation exceeds its candidate-work limit; simplify UV islands"
                )
            active = {other: bounds for other, bounds in previous.items() if bounds[0] > left + _UV_EPSILON}
            candidates.update(active)
            active[index] = (right, bottom, top, points)
            buckets[key] = active
        for _end, low, high, other in candidates.values():
            if high <= bottom + _UV_EPSILON or low >= top - _UV_EPSILON:
                continue
            if _triangles_overlap(points, other):
                raise ValueError("Conflicting overlapping destination UV triangles cannot be baked unambiguously")


def _validate_uv(mesh: Any, slots: set[int]) -> str:
    uv = mesh.uv_layers.active
    if uv is None:
        raise ValueError(
            "Material baking requires an existing active destination UV map; automatic unwrap is unsupported"
        )
    mesh.calc_loop_triangles()
    triangles = []
    for triangle in mesh.loop_triangles:
        if triangle.material_index not in slots:
            continue
        points = np.array([uv.data[index].uv[:] for index in triangle.loops], dtype=np.float64)
        if not np.isfinite(points).all() or (points < 0).any() or (points > 1).any():
            raise ValueError("Material bake destination UV coordinates must be finite and inside [0, 1]")
        a, b = points[1] - points[0], points[2] - points[0]
        if abs(a[0] * b[1] - a[1] * b[0]) <= _UV_EPSILON or triangle.area <= 1e-20:
            raise ValueError("Material baking requires nondegenerate geometry and destination UV triangles")
        low = points.min(axis=0)
        high = points.max(axis=0)
        triangles.append((float(low[0]), float(high[0]), float(low[1]), float(high[1]), points))
    if not triangles:
        raise ValueError("Material baking found no faces assigned to the requested material")
    _validate_overlaps(triangles)
    return uv.name


def _copied_input(tree: Any, socket: Any | None) -> Any | None:
    if socket is None:
        return None
    node = tree.nodes.get(socket.node.name)
    if node is not None:
        for candidate in node.inputs:
            if candidate.identifier == socket.identifier:
                return candidate
    raise ValueError("Material bake state does not reference an input of the supplied material")


def _destination(material: Any, image: Any) -> None:
    tree = material.node_tree
    for node in tree.nodes:
        node.select = False
    destination = tree.nodes.new("ShaderNodeTexImage")
    destination.image = image
    destination.select = True
    tree.nodes.active = destination


def _prepare_target(material: Any, image: Any, state: SurfaceState) -> tuple[Any, Any, Any]:
    material.use_nodes = True
    tree = material.node_tree
    color = _copied_input(tree, state.color_socket)
    alpha = _copied_input(tree, state.alpha_socket)
    for node in list(tree.nodes):
        if node.bl_idname == "ShaderNodeOutputMaterial":
            tree.nodes.remove(node)
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.target = "CYCLES"
    output.is_active_output = True
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1
    tree.links.new(emission.outputs[0], output.inputs["Surface"])
    if color is not None and color.is_linked:
        tree.links.new(color.links[0].from_socket, emission.inputs["Color"])
    else:
        emission.inputs["Color"].default_value = state.base_color
    scalar = tree.nodes.new("ShaderNodeMath")
    scalar.operation = "MULTIPLY"
    scalar.use_clamp = True
    scalar.inputs[1].default_value = 1
    if alpha is not None and alpha.is_linked:
        tree.links.new(alpha.links[0].from_socket, scalar.inputs[0])
    else:
        scalar.inputs[0].default_value = state.alpha
    _destination(material, image)
    return tree, emission, scalar


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def _encode_png(color: np.ndarray, alpha: np.ndarray, resolution: int) -> bytes:
    if not np.isfinite(color).all() or not np.isfinite(alpha).all():
        raise ValueError("Material bake produced nonfinite image pixels")
    rgb = np.clip(color.reshape(resolution, resolution, 4)[:, :, :3], 0, 1)
    srgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)
    rgba = np.empty((resolution, resolution, 4), dtype=np.uint8)
    rgba[:, :, :3] = np.rint(srgb * 255).astype(np.uint8)
    rgba[:, :, 3] = np.rint(np.clip(alpha.reshape(resolution, resolution, 4)[:, :, 0], 0, 1) * 255).astype(np.uint8)
    # Blender rows start at the bottom; PNG rows start at the top. Alpha is
    # straight, linear coverage, never a view-transformed or sRGB channel.
    rows = b"".join(b"\0" + row.tobytes() for row in rgba[::-1])
    header = struct.pack(">IIBBBBB", resolution, resolution, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows))
        + _png_chunk(b"IEND", b"")
    )


def _bake_pass(context: Any, scene: Any, obj: Any, image: Any, uv_name: str, margin: int) -> np.ndarray:
    layer = scene.view_layers[0]
    layer.objects.active = obj
    obj.select_set(True, view_layer=layer)
    with context.temp_override(
        scene=scene,
        view_layer=layer,
        active_object=obj,
        object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    ):
        result = bpy.ops.object.bake(
            type="EMIT",
            use_selected_to_active=False,
            use_clear=True,
            margin=margin,
            margin_type="EXTEND",
            uv_layer=uv_name,
        )
    if "FINISHED" not in result:
        raise ValueError(f"Cycles material bake did not finish: {result}")
    pixels = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels


def _configure_scene(scene: Any) -> None:
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.render.bake.use_selected_to_active = False
    scene.render.bake.use_clear = True


def _copy_object(obj: Any, mesh: Any, scene: Any) -> Any:
    copied = obj.copy() if obj.type == "MESH" else bpy.data.objects.new("SKP converted bake object", mesh)
    # Link immediately so the owning scene can clean up even if setup fails.
    scene.collection.objects.link(copied)
    copied.data = mesh
    transform = obj.matrix_world.copy()
    copied.animation_data_clear()
    copied.parent = None
    copied.constraints.clear()
    copied.modifiers.clear()
    copied.matrix_world = transform
    copied.hide_render = False
    copied.hide_viewport = False
    copied.hide_set(False, view_layer=scene.view_layers[0])
    return copied


def _slot_materials(obj: Any, mesh: Any) -> list[Any]:
    return [
        obj.material_slots[index].material
        if index < len(obj.material_slots) and obj.material_slots[index].link == "OBJECT"
        else source
        for index, source in enumerate(mesh.materials)
    ]


def _copy_slots(mesh: Any, sources: list[Any], material: Any, scratch: Any, owned: list[Any]) -> Any:
    target_copy = material.copy()
    owned.append(target_copy)
    dummy = None
    # Object-linked overrides take precedence over mesh slots, but evaluated
    # meshes may contain additional slots not present on the original object.
    for index, source in enumerate(sources):
        if source == material:
            mesh.materials[index] = target_copy
        else:
            if dummy is None:
                dummy = bpy.data.materials.new("SKP bake scratch")
                owned.append(dummy)
                dummy.use_nodes = True
                _destination(dummy, scratch)
            mesh.materials[index] = dummy
    return target_copy


def _validate_state(obj: Any, material: Any, state: SurfaceState) -> None:
    if not (state.bake_color or state.bake_alpha):
        raise ValueError("Material baking requires a color or alpha bake flag")
    if obj.mode != "OBJECT":
        raise ValueError("Material baking requires the source object in Object mode")
    if material.node_tree is None:
        raise ValueError("Material baking requires a material node tree")
    _validate_drivers(material)
    _validate_drivers(material.node_tree)
    for socket, required in ((state.color_socket, state.bake_color), (state.alpha_socket, state.bake_alpha)):
        if socket is not None and (socket.is_output or socket.id_data != material.node_tree):
            raise ValueError("Material bake state must reference the supplied material's top-level destination inputs")
        if required and (socket is None or not socket.is_linked):
            raise ValueError("Material bake flag requires a linked destination input socket")
        _validate_expression(socket)
    if state.image is not None and state.color_socket is None:
        raise ValueError("Direct image resampling requires the original color destination input socket")
    if not all(math.isfinite(value) for value in (*state.base_color, state.alpha)):
        raise ValueError("Material bake constants must be finite")


def bake_material(
    context: Any,
    obj: Any,
    mesh: Any,
    material: Any,
    state: SurfaceState,
    *,
    resolution: int,
    margin: int,
) -> bytes:
    """Return an RGBA PNG containing the complete final base color and alpha.

    ``mesh`` must be the final export mesh with a valid active destination UV.
    Its active-render UV remains the source for implicit texture UV references.
    Source frame/subframe is retained for keyframed expressions; drivers and
    sequence/movie/UDIM textures are unsupported. No unwrap, source mutations,
    view transform, or fallback is performed. The
    caller must use white base color and alpha 1 with the returned texture, not
    multiply the original constants into these already-complete baked channels.
    """
    _validate_settings(resolution, margin)
    _validate_state(obj, material, state)
    scene = None
    copied_mesh = None
    materials: list[Any] = []
    images: list[Any] = []
    try:
        copied_mesh = mesh.copy()
        sources = _slot_materials(obj, copied_mesh)
        slots = {index for index, source in enumerate(sources) if source == material}
        uv_name = _validate_uv(copied_mesh, slots)
        scene = bpy.data.scenes.new("SKP material bake")
        _configure_scene(scene)
        copied = _copy_object(obj, copied_mesh, scene)
        for _index in range(2):
            image = bpy.data.images.new(
                "SKP bake pixels", width=resolution, height=resolution, alpha=True, float_buffer=True
            )
            images.append(image)
            image.colorspace_settings.name = "Non-Color"
            image.alpha_mode = "STRAIGHT"
        target, scratch = images
        copied_material = _copy_slots(copied_mesh, sources, material, scratch, materials)
        # Clear object-linked overrides on the copy only.
        for slot in copied.material_slots:
            slot.link = "DATA"
        tree, emission, scalar = _prepare_target(copied_material, target, state)
        # Evaluate only after the copied graph and object are linked, including
        # fractional time. Setting the scene's frame before these exist is not enough.
        scene.frame_set(context.scene.frame_current, subframe=context.scene.frame_subframe)
        color = _bake_pass(context, scene, copied, target, uv_name, margin)
        tree.links.new(scalar.outputs[0], emission.inputs["Color"])
        alpha = _bake_pass(context, scene, copied, target, uv_name, margin)
        return _encode_png(color, alpha, resolution)
    except RuntimeError as exc:
        raise ValueError(f"Cycles material baking failed: {exc}") from exc
    finally:
        if scene is not None:
            for temporary in list(scene.objects):
                bpy.data.objects.remove(temporary, do_unlink=True)
            bpy.data.scenes.remove(scene)
        if copied_mesh is not None:
            bpy.data.meshes.remove(copied_mesh)
        for temporary in materials:
            bpy.data.materials.remove(temporary)
        for temporary in images:
            bpy.data.images.remove(temporary)
