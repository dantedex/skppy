# SPDX-License-Identifier: MIT
"""Build isolated Blender materials and packed renderer image nodes."""

from __future__ import annotations

import os
import tempfile
from hashlib import sha256
from pathlib import Path

import bpy
import numpy as np

from .skppy._atomic_io import atomic_write
from .skppy.data_structure.images import Texture
from .skppy.data_structure.materials import Color, Material


def _linear_color(color: Color) -> tuple[float, float, float, float]:
    """Convert serialized sRGB bytes to Blender's scene-linear socket values."""
    channels = [channel / 255.0 for channel in (color.r, color.g, color.b)]
    red, green, blue = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return red, green, blue, 1.0


class BlenderMaterialBuilder:
    """Translate material appearances without modifying existing data-blocks."""

    @classmethod
    def build_material(cls, mat) -> "bpy.types.Material":
        """Create a fresh material; name collisions never authorize updates."""
        bl_mat = bpy.data.materials.new(name=mat.name)
        bl_mat.use_nodes = True

        bsdf = bl_mat.node_tree.nodes.get("Principled BSDF")
        has_texture_alpha = False
        if bsdf:
            cls._set_principled_input(bsdf, "Base Color", _linear_color(mat.color))
            cls._set_principled_input(bsdf, "Alpha", mat.alpha)
            cls._set_principled_input(bsdf, "Metallic", mat.metallic)
            cls._set_principled_input(bsdf, "Roughness", mat.roughness)
            cls._set_principled_input(bsdf, "IOR", mat.ior)
            cls._set_first_principled_input(bsdf, ("Transmission Weight", "Transmission"), mat.transmission)
            cls._set_first_principled_input(bsdf, ("IOR Level", "Specular IOR Level"), mat.specular)
            emission = _linear_color(mat.emission_color)
            cls._set_first_principled_input(bsdf, ("Emission Color", "Emission"), emission)
            cls._set_principled_input(bsdf, "Emission Strength", mat.emission_strength)

            if mat.has_texture and mat.texture and mat.texture.data:
                has_texture_alpha = cls._attach_texture(bl_mat, mat)
                bl_mat["skppy_x_scale"] = mat.texture.x_scale
                bl_mat["skppy_y_scale"] = mat.texture.y_scale
            cls._attach_pbr_textures(bl_mat, mat, bsdf)

        cls._store_pbr_metadata(bl_mat, mat)

        if mat.alpha < 1.0 or has_texture_alpha:
            cls._set_transparency_method(bl_mat)
        return bl_mat

    @classmethod
    def _attach_texture(
        cls,
        bl_mat: bpy.types.Material,
        material: Material,
    ) -> bool:
        """Load texture image data into a Blender image texture node.

        Returns True when the loaded image alpha channel contains transparency.
        """
        texture = material.texture
        assert texture is not None  # The caller checks the embedded image slot.
        image = cls._load_texture_image(texture)
        tex_node = cls._new_image_texture_node(bl_mat, image, location=(-280, 200))

        tree = bl_mat.node_tree
        nodes = tree.nodes
        links = tree.links
        bsdf = nodes.get("Principled BSDF")
        if bsdf:
            color = cls._adjust_diffuse_texture(bl_mat, tex_node.outputs["Color"], texture)
            color = cls._tint_and_fade(bl_mat, color, material)
            cls._link_principled_input(links, color, bsdf, "Base Color")
            cls._link_texture_alpha(
                nodes,
                links,
                tex_node.outputs.get("Alpha"),
                bsdf,
                material.alpha,
            )

        return cls._image_uses_alpha(image)

    @staticmethod
    def _adjust_diffuse_texture(
        bl_mat: bpy.types.Material, output: bpy.types.NodeSocket, texture: Texture
    ) -> bpy.types.NodeSocket:
        """Apply renderer color adjustments without modifying the texture alpha."""
        nodes = bl_mat.node_tree.nodes
        links = bl_mat.node_tree.links
        if texture.inverted:
            invert = nodes.new("ShaderNodeInvert")
            invert.label = "SKP Diffuse Invert"
            invert.location = (-40, 300)
            invert.inputs["Fac"].default_value = 1.0
            links.new(output, invert.inputs["Color"])
            output = invert.outputs["Color"]
        if texture.brightness != 1.0:
            multiply = nodes.new("ShaderNodeMixRGB")
            multiply.blend_type = "MULTIPLY"
            multiply.label = "SKP Diffuse Brightness"
            multiply.location = (160, 300)
            multiply.inputs[0].default_value = 1.0
            multiply.inputs[2].default_value = (texture.brightness,) * 3 + (1.0,)
            links.new(output, multiply.inputs[1])
            output = multiply.outputs["Color"]
        return output

    @staticmethod
    def _tint_and_fade(
        bl_mat: bpy.types.Material, output: bpy.types.NodeSocket, material: Material
    ) -> bpy.types.NodeSocket:
        """Blend a tinted diffuse image with the material's untextured color."""
        nodes = bl_mat.node_tree.nodes
        links = bl_mat.node_tree.links
        if material.tint_color != Color(255, 255, 255):
            tint = nodes.new("ShaderNodeMixRGB")
            tint.blend_type = "MULTIPLY"
            tint.label = "SKP Texture Tint"
            tint.inputs[0].default_value = 1.0
            tint.inputs[2].default_value = _linear_color(material.tint_color)
            links.new(output, tint.inputs[1])
            output = tint.outputs["Color"]
        if material.texture_fade != 1.0:
            fade = nodes.new("ShaderNodeMixRGB")
            fade.blend_type = "MIX"
            fade.label = "SKP Image Fade"
            fade.inputs[0].default_value = material.texture_fade
            fade.inputs[1].default_value = _linear_color(material.color)
            links.new(output, fade.inputs[2])
            output = fade.outputs["Color"]
        return output

    @staticmethod
    def _load_texture_image(texture, *, non_color: bool = False) -> "bpy.types.Image":
        """Load and pack one in-memory texture image."""
        ext = os.path.splitext(texture.filename)[1] if texture.filename else ".png"
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(tmp_fd, "wb") as tmp:
                tmp.write(texture.data)
            image = bpy.data.images.load(tmp_path, check_existing=False)
            if not all(image.size):
                raise ValueError(f"Could not decode texture {texture.filename!r}")
            # Packed data keeps .blend files self-contained. A real persistent
            # path also lets file-based exporters copy/reference the image.
            directory = Path(bpy.utils.user_resource("DATAFILES", path="skppy/textures", create=True))
            suffix = {
                "PNG": ".png",
                "JPEG": ".jpg",
                "TIFF": ".tif",
                "BMP": ".bmp",
                "TARGA": ".tga",
                "TARGA_RAW": ".tga",
                "OPEN_EXR": ".exr",
                "HDR": ".hdr",
                "JPEG2000": ".jp2",
            }.get(image.file_format, ".png")
            cached = directory / f"{sha256(texture.data).hexdigest()}{suffix}"
            if not cached.is_file() or cached.read_bytes() != texture.data:
                atomic_write(cached, texture.data)
            image.filepath_raw = str(cached)
            image.pack()
            if texture.filename:
                image.name = os.path.basename(texture.filename)
            if non_color:
                image.colorspace_settings.name = "Non-Color"
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return image

    @staticmethod
    def _new_image_texture_node(bl_mat, image, *, location: tuple[int, int]):
        """Create a UV-driven image node for a packed image."""
        tree = bl_mat.node_tree
        nodes = tree.nodes
        links = tree.links
        tex_coord = nodes.new("ShaderNodeTexCoord")
        tex_coord.location = (location[0] - 220, location[1])

        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = image
        tex_node.location = location

        links.new(tex_coord.outputs["UV"], tex_node.inputs["Vector"])
        return tex_node

    @classmethod
    def _attach_pbr_textures(cls, bl_mat, mat, bsdf) -> None:
        """Build Blender nodes for embedded scalar and relief maps."""
        nodes = bl_mat.node_tree.nodes
        links = bl_mat.node_tree.links
        for index, (slot_name, socket_name) in enumerate(
            (("metallic_texture", "Metallic"), ("roughness_texture", "Roughness"))
        ):
            texture = getattr(mat, slot_name)
            if texture is None or texture.data is None:
                continue
            output = cls._attach_scalar_texture(bl_mat, texture, location=(-280, -40 - index * 240))
            cls._link_principled_input(links, output, bsdf, socket_name)

        normal_output = None
        if mat.normal_texture is not None and mat.normal_texture.data is not None:
            tex_node = cls._pbr_image_node(bl_mat, mat.normal_texture, location=(-280, -520))
            normal_map = nodes.new("ShaderNodeNormalMap")
            normal_map.label = "SKP Normal"
            normal_map.location = (-40, -520)
            normal_map.inputs["Strength"].default_value = mat.normal_scale
            links.new(tex_node.outputs["Color"], normal_map.inputs["Color"])
            normal_output = normal_map.outputs["Normal"]

        if mat.bump_texture is not None and mat.bump_texture.data is not None:
            height = cls._attach_scalar_texture(bl_mat, mat.bump_texture, location=(-280, -760))
            bump = nodes.new("ShaderNodeBump")
            bump.label = "SKP Bump"
            bump.location = (-40, -680)
            bump.inputs["Strength"].default_value = mat.bump_strength
            links.new(height, bump.inputs["Height"])
            if normal_output is not None:
                links.new(normal_output, bump.inputs["Normal"])
            normal_output = bump.outputs["Normal"]
        if normal_output is not None:
            cls._link_principled_input(links, normal_output, bsdf, "Normal")

        if mat.displacement_texture is not None and mat.displacement_texture.data is not None:
            height = cls._attach_scalar_texture(bl_mat, mat.displacement_texture, location=(-280, -1000))
            displacement = nodes.new("ShaderNodeDisplacement")
            displacement.label = "SKP Displacement"
            displacement.location = (0, -920)
            displacement.inputs["Scale"].default_value = mat.displacement_scale
            links.new(height, displacement.inputs["Height"])
            material_output = nodes.get("Material Output")
            if material_output is not None:
                links.new(displacement.outputs["Displacement"], material_output.inputs["Displacement"])

    @classmethod
    def _attach_scalar_texture(cls, bl_mat, texture, *, location: tuple[int, int]):
        """Create a non-color texture chain with source inversion and brightness."""
        tex_node = cls._pbr_image_node(bl_mat, texture, location=location)
        output = tex_node.outputs["Color"]
        nodes = bl_mat.node_tree.nodes
        links = bl_mat.node_tree.links
        if texture.inverted:
            invert = nodes.new("ShaderNodeMath")
            invert.operation = "SUBTRACT"
            invert.label = "SKP Invert"
            invert.inputs[0].default_value = 1.0
            invert.location = (location[0] + 200, location[1])
            links.new(output, invert.inputs[1])
            output = invert.outputs["Value"]
        if texture.brightness != 1.0:
            multiply = nodes.new("ShaderNodeMath")
            multiply.operation = "MULTIPLY"
            multiply.label = "SKP Brightness"
            multiply.inputs[1].default_value = texture.brightness
            multiply.location = (location[0] + 400, location[1])
            links.new(output, multiply.inputs[0])
            output = multiply.outputs["Value"]
        return output

    @classmethod
    def _pbr_image_node(cls, bl_mat, texture, *, location: tuple[int, int]):
        image = cls._load_texture_image(texture, non_color=True)
        tex_node = cls._new_image_texture_node(bl_mat, image, location=location)
        tex_node.label = f"SKP {os.path.basename(texture.filename)}"
        return tex_node

    @staticmethod
    def _store_pbr_metadata(bl_mat, mat) -> None:
        """Keep source PBR parameters and missing map references inspectable."""
        values = {
            "skppy_transmission": mat.transmission,
            "skppy_texture_fade": mat.texture_fade,
            "skppy_tint_color": (mat.tint_color.r, mat.tint_color.g, mat.tint_color.b),
            "skppy_specular": mat.specular,
            "skppy_ior": mat.ior,
            "skppy_emission_strength": mat.emission_strength,
            "skppy_bump_map_type": mat.bump_map_type,
            "skppy_bump_strength": mat.bump_strength,
            "skppy_normal_scale": mat.normal_scale,
            "skppy_displacement_scale": mat.displacement_scale,
        }
        for key, value in values.items():
            bl_mat[key] = value
        for slot_name in (
            "metallic_texture",
            "roughness_texture",
            "bump_texture",
            "normal_texture",
            "displacement_texture",
        ):
            texture = getattr(mat, slot_name)
            key = f"skppy_{slot_name}"
            if texture is not None:
                bl_mat[key] = texture.filename
            elif key in bl_mat:
                del bl_mat[key]

    @staticmethod
    def _set_principled_input(
        bsdf: "bpy.types.Node",
        socket_name: str,
        value,
    ) -> None:
        socket = bsdf.inputs.get(socket_name)
        if socket is not None:
            socket.default_value = value

    @staticmethod
    def _set_first_principled_input(bsdf: "bpy.types.Node", socket_names: tuple[str, ...], value) -> None:
        for socket_name in socket_names:
            socket = bsdf.inputs.get(socket_name)
            if socket is not None:
                socket.default_value = value
                return

    @staticmethod
    def _link_principled_input(
        links: "bpy.types.NodeLinks",
        output_socket,
        bsdf: "bpy.types.Node",
        socket_name: str,
    ) -> None:
        input_socket = bsdf.inputs.get(socket_name)
        if output_socket is not None and input_socket is not None:
            links.new(output_socket, input_socket)

    @staticmethod
    def _link_texture_alpha(
        nodes: "bpy.types.Nodes",
        links: "bpy.types.NodeLinks",
        alpha_output,
        bsdf: "bpy.types.Node",
        alpha_factor: float,
    ) -> None:
        alpha_input = bsdf.inputs.get("Alpha")
        if alpha_output is None or alpha_input is None:
            return

        if alpha_factor < 1.0:
            multiply = nodes.new("ShaderNodeMath")
            multiply.operation = "MULTIPLY"
            multiply.location = (-40, -120)
            multiply.inputs[1].default_value = alpha_factor
            links.new(alpha_output, multiply.inputs[0])
            links.new(multiply.outputs["Value"], alpha_input)
            return

        links.new(alpha_output, alpha_input)

    @staticmethod
    def _image_uses_alpha(image: "bpy.types.Image") -> bool:
        """Return True when the image alpha channel contains transparency."""
        channels = getattr(image, "channels", 0)
        if channels < 4:
            return False

        pixels = getattr(image, "pixels", None)
        if pixels is None:
            return True

        pixel_count = len(pixels)
        values_np = np.empty(pixel_count, dtype=np.float32)
        pixels.foreach_get(values_np)
        return bool(np.any(values_np[3::channels] < 0.999))

    @staticmethod
    def _set_transparency_method(bl_mat: "bpy.types.Material") -> None:
        # Blender 4.2+ (EEVEE Next) uses surface_render_method and supports
        # DITHERED. Older versions use blend_method, where HASHED is the
        # closest dithered transparency equivalent.
        if hasattr(bl_mat, "surface_render_method"):
            try:
                bl_mat.surface_render_method = "DITHERED"
                return
            except (TypeError, ValueError):
                bl_mat.surface_render_method = "BLENDED"
                return

        try:
            bl_mat.blend_method = "HASHED"
        except (TypeError, ValueError):
            bl_mat.blend_method = "BLEND"
