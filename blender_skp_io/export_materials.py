# SPDX-License-Identifier: MIT
"""Analyze the active Cycles surface without modifying the original material."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct
from typing import Any
import zlib

import bpy
import numpy as np


@dataclass
class SurfaceState:
    """Export approximation and original top-level destination inputs for baking.

    ``image`` is a byte-backed, unmodified direct sRGB color image, not an arbitrary
    upstream image. Named UV maps still require validation against the export mesh.
    Bake flags describe linked expressions; the builder reports losses if baking
    is disabled. Socket references belong to the caller's material and are not copies.
    ``preserve_image_alpha`` means the same texture node drives color and opacity;
    otherwise direct-image bytes must omit intrinsic alpha via ``direct_image_bytes``.
    """

    base_color: tuple[float, float, float, float]
    metallic: float
    roughness: float
    alpha: float
    color_socket: Any | None = None
    alpha_socket: Any | None = None
    image: Any | None = None
    bake_color: bool = False
    bake_alpha: bool = False
    warnings: list[str] = field(default_factory=list)
    preserve_image_alpha: bool = False


_COLOR_SHADERS = {
    "ShaderNodeBsdfPrincipled": "Base Color",
    "ShaderNodeBsdfDiffuse": "Color",
    "ShaderNodeBsdfGlossy": "Color",
    "ShaderNodeBsdfAnisotropic": "Color",
    "ShaderNodeBsdfTranslucent": "Color",
    "ShaderNodeBsdfTransparent": "Color",
    "ShaderNodeBsdfGlass": "Color",
    "ShaderNodeBsdfRefraction": "Color",
    "ShaderNodeEmission": "Color",
}
_CONTEXT_NODES = {
    "ShaderNodeObjectInfo",
    "ShaderNodeCameraData",
    "ShaderNodeLightPath",
    "ShaderNodeShaderToRGB",
}


def _source(socket: Any | None) -> Any | None:
    """Resolve input reroutes, retaining the actual source output socket."""
    visited = set()
    while socket is not None and socket.is_linked:
        source = socket.links[0].from_socket
        node = source.node
        if node.bl_idname != "NodeReroute":
            return source
        pointer = node.as_pointer()
        if pointer in visited:
            return None
        visited.add(pointer)
        socket = node.inputs[0]
    return None


def _active_output(tree: Any, warnings: list[str]) -> Any | None:
    # is_active_output is shared across engines; Blender resolves target-specific
    # outputs even when the UI's active output belongs to a different engine.
    output = tree.get_output_node("CYCLES")
    if output is None or output.target not in {"CYCLES", "ALL"}:
        warnings.append("No active Cycles/ALL Material Output (output target mismatch); using viewport fallback")
        return None
    viewport_output = tree.get_output_node("EEVEE")
    if viewport_output is not None and viewport_output != output:
        warnings.append("Material Output target mismatch: export uses the active Cycles surface, not Eevee")
    return output


def _has_image_bytes(image: Any) -> bool:
    if image.is_dirty or image.source != "FILE":
        return False
    if image.packed_file is not None and image.packed_file.size:
        return True
    if not image.filepath:
        return False
    path = Path(bpy.path.abspath(image.filepath, library=image.library))
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _opaque_png(pixels: np.ndarray, width: int, height: int, *, linear_rgb: bool) -> bytes:
    rgb = np.clip(pixels[:, :, :3], 0.0, 1.0)
    # Byte-backed sRGB image pixels are already encoded, unlike linear float buffers.
    if linear_rgb:
        rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)
    rgba = np.full((height, width, 4), 255, dtype=np.uint8)
    rgba[:, :, :3] = np.rint(rgb * 255).astype(np.uint8)
    # Blender stores bottom-up rows; PNG scanlines start at the top.
    rows = b"".join(b"\x00" + row.tobytes() for row in rgba[::-1])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def direct_image_bytes(image: Any, preserve_alpha: bool = False) -> bytes | None:
    """Return export bytes for an unchanged direct sRGB/STRAIGHT image.

    Preserve the original bytes when alpha is requested or every pixel is opaque.
    Otherwise encode an opaque RGBA PNG, converting linear float RGB to sRGB
    while retaining already encoded byte RGB. Never change the source image,
    its packed bytes, or its file. Return ``None`` for unavailable
    bytes or an image requiring baking. Re-encoded bytes are PNG regardless of the
    source filename; the builder must select a matching export filename.
    """
    if image.colorspace_settings.name != "sRGB" or image.alpha_mode != "STRAIGHT" or not _has_image_bytes(image):
        return None
    try:
        data = (
            bytes(image.packed_file.data)
            if image.packed_file is not None
            else Path(bpy.path.abspath(image.filepath, library=image.library)).read_bytes()
        )
    except OSError:
        return None
    if preserve_alpha:
        return data
    width, height = image.size
    channels = image.channels
    if width <= 0 or height <= 0:
        return None
    if channels != 4:
        return data if channels in {1, 3} else None
    pixels = np.empty(width * height * channels, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, channels)
    if np.all(pixels[:, :, 3] == 1.0):
        return data
    return _opaque_png(pixels, width, height, linear_rgb=image.is_float)


def _direct_image(socket: Any) -> Any | None:
    source = _source(socket)
    if source is None or source.node.bl_idname != "ShaderNodeTexImage":
        return None
    node = source.node
    if source != node.outputs.get("Color") or node.image is None:
        return None
    if (
        node.projection != "FLAT"
        or node.extension != "REPEAT"
        or node.image.colorspace_settings.name != "sRGB"
        or node.image.alpha_mode != "STRAIGHT"
        or not _has_image_bytes(node.image)
    ):
        return None
    vector = node.inputs["Vector"]
    coordinates = _source(vector)
    if vector.is_linked:
        if coordinates is None:
            return None
        kind = coordinates.node.bl_idname
        if kind == "ShaderNodeUVMap":
            if coordinates.node.from_instancer:
                return None
        elif (
            kind != "ShaderNodeTexCoord"
            or coordinates != coordinates.node.outputs.get("UV")
            or coordinates.node.from_instancer
        ):
            return None
    return node.image


def _context_warnings(socket: Any, warnings: list[str]) -> None:
    """Flag unsafe bake dependencies, including dependencies inside expression groups."""
    source = _source(socket)
    pending = [source.node] if source is not None else []
    visited = set()
    while pending:
        node = pending.pop()
        pointer = node.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)
        if node.bl_idname in _CONTEXT_NODES:
            warning = f"Context-dependent baking source {node.bl_idname} is unsupported; baker must reject it"
            if warning not in warnings:
                warnings.append(warning)
        if node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None:
            pending.extend(node.node_tree.nodes)
        for socket_input in node.inputs:
            upstream = _source(socket_input)
            if upstream is not None:
                pending.append(upstream.node)


def _scalar(node: Any, name: str, fallback: float, warnings: list[str]) -> float:
    socket = node.inputs.get(name)
    if socket is None:
        return fallback
    if socket.is_linked:
        warnings.append(f"{name} map is unsupported; using the socket default")
    return float(socket.default_value)


def _parameter_warnings(node: Any, warnings: list[str]) -> None:
    normal = node.inputs.get("Normal")
    if normal is not None and normal.is_linked:
        warnings.append("Normal map is unsupported")
    for name, default in (
        ("IOR", 1.5),
        ("IOR Level", 0.5),
        ("Specular IOR Level", 0.5),
        ("Transmission Weight", 0.0),
        ("Transmission", 0.0),
        ("Coat Weight", 0.0),
        ("Clearcoat", 0.0),
        ("Subsurface Weight", 0.0),
        ("Subsurface", 0.0),
        ("Sheen Weight", 0.0),
        ("Sheen", 0.0),
        ("Anisotropic", 0.0),
        ("Anisotropic IOR Level", 0.0),
    ):
        socket = node.inputs.get(name)
        if socket is not None and (socket.is_linked or abs(float(socket.default_value) - default) > 1e-6):
            warnings.append(f"{name} is unsupported")
    emission = node.inputs.get("Emission Color")
    if emission is None:
        emission = node.inputs.get("Emission")
    strength = node.inputs.get("Emission Strength")
    if emission is not None and (
        emission.is_linked
        or (strength is not None and strength.is_linked)
        or (any(emission.default_value[:3]) and (strength is None or strength.default_value != 0))
    ):
        warnings.append("emission energy is unsupported")


def _transparent_alpha(color_socket: Any, warnings: list[str]) -> float:
    if not color_socket.is_linked and all(component == 1.0 for component in color_socket.default_value[:3]):
        return 0.0
    warnings.append("Unsupported tinted transmission: Transparent BSDF uses an opaque color approximation")
    return 1.0


def _analyze_color(state: SurfaceState) -> None:
    if not state.color_socket.is_linked:
        return
    state.image = _direct_image(state.color_socket)
    state.bake_color = state.image is None
    if state.bake_color:
        _context_warnings(state.color_socket, state.warnings)
        return
    color_source = _source(state.color_socket)
    alpha_source = _source(state.alpha_socket)
    if alpha_source is not None and alpha_source == color_source.node.outputs.get("Alpha"):
        state.preserve_image_alpha = True
        state.bake_alpha = False
        state.alpha = 1.0


def _closure_state(node: Any, state: SurfaceState) -> None:
    kind = node.bl_idname
    state.color_socket = node.inputs[_COLOR_SHADERS[kind]]
    state.base_color = tuple(state.color_socket.default_value)
    state.metallic = 1.0 if kind in {"ShaderNodeBsdfGlossy", "ShaderNodeBsdfAnisotropic"} else 0.0
    state.roughness = _scalar(node, "Roughness", 0.0, state.warnings)
    state.alpha = _transparent_alpha(state.color_socket, state.warnings) if kind == "ShaderNodeBsdfTransparent" else 1.0
    if kind in {"ShaderNodeBsdfGlossy", "ShaderNodeBsdfAnisotropic"}:
        state.warnings.append(
            "Glossy/Anisotropic uses a metallic=1 approximation; not physically equivalent in general"
        )
    if kind == "ShaderNodeBsdfPrincipled":
        state.metallic = _scalar(node, "Metallic", 0.0, state.warnings)
        state.alpha_socket = node.inputs.get("Alpha")
        if state.alpha_socket is not None:
            state.alpha = float(state.alpha_socket.default_value)
            state.bake_alpha = state.alpha_socket.is_linked
            if state.bake_alpha:
                _context_warnings(state.alpha_socket, state.warnings)
    if kind in {"ShaderNodeBsdfGlass", "ShaderNodeBsdfRefraction", "ShaderNodeBsdfTranslucent"}:
        state.warnings.append(
            "Transmission is lost: using an opaque color/roughness approximation, not alpha transparency"
        )
    if kind == "ShaderNodeEmission":
        state.warnings.append("emission energy is lost: using a color approximation only")
    _parameter_warnings(node, state.warnings)
    _analyze_color(state)


def analyze_material(material: Any) -> SurfaceState:
    """Return a read-only Cycles surface analysis, with explicit viewport fallback.

    Only a single supported top-level closure is approximated. Shader composition,
    shader groups, and volume outputs are not flattened. Color/alpha expressions
    (including node groups) retain their destination sockets for the bake adapter.
    """
    diffuse = tuple(material.diffuse_color)
    state = SurfaceState(
        base_color=diffuse,
        metallic=float(getattr(material, "metallic", 0.0)),
        roughness=float(getattr(material, "roughness", 1.0)),
        alpha=float(diffuse[3]),
    )
    if not material.use_nodes or material.node_tree is None:
        return state
    output = _active_output(material.node_tree, state.warnings)
    if output is None:
        return state
    if output.inputs["Displacement"].is_linked:
        state.warnings.append("displacement is unsupported")
    if output.inputs["Volume"].is_linked:
        state.warnings.append("Unsupported volume output; using viewport fallback")
        return state
    source = _source(output.inputs["Surface"])
    if source is None or source.node.bl_idname not in _COLOR_SHADERS:
        kind = source.node.bl_idname if source is not None else "unconnected Surface"
        state.warnings.append(f"Unsupported shader graph ({kind}); using viewport fallback")
        return state
    _closure_state(source.node, state)
    return state
