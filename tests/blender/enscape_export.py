# SPDX-License-Identifier: MIT
"""Check Enscape export with live Blender state and independent expected values."""

import importlib
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import zipfile

import bpy


def run(module_name: str, pixels: bytes, export_output: Path | None) -> None:
    """Exercise the operator, shader adapter, loss rejection, and raw metadata."""
    builder_type = importlib.import_module(f"{module_name}.export_builder").BlenderModelBuilder
    assert bpy.ops.export_scene.skp.get_rna_type().properties["export_enscape_materials"].default is False
    viewport = bpy.data.materials.new("Enscape viewport fallback")
    viewport.use_nodes = False
    viewport.diffuse_color = (0.25, 0.25, 0.25, 0.5)
    viewport.metallic = 0.25
    viewport.roughness = 0.75
    expected_color = (137, 137, 137)
    expected_factors = (0.5, 0.25, 0.75)
    if viewport.use_nodes:
        # Blender 5.2 ignores use_nodes=False; its active shader remains authoritative.
        viewport_bsdf = viewport.node_tree.nodes["Principled BSDF"]
        viewport_bsdf.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1)
        viewport_bsdf.inputs["Alpha"].default_value = 0.75
        viewport_bsdf.inputs["Metallic"].default_value = 0.5
        viewport_bsdf.inputs["Roughness"].default_value = 0.25
        expected_color = (188, 188, 188)
        expected_factors = (0.75, 0.5, 0.25)
    converted = builder_type(bpy.context, export_enscape_materials=True)._material_for(viewport)
    assert (converted.color.r, converted.color.g, converted.color.b) == expected_color
    assert (converted.alpha, converted.metallic, converted.roughness) == expected_factors
    bpy.data.materials.remove(viewport)
    mesh = bpy.data.meshes.new("Enscape export mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    mesh.uv_layers.new(name="Rendered")
    mesh.uv_layers.new(name="Editing")
    for entry, uv in zip(mesh.uv_layers["Rendered"].data, ((0, 0), (1, 0), (0, 1))):
        entry.uv = uv
    for entry, uv in zip(mesh.uv_layers["Editing"].data, ((10, 10), (11, 10), (10, 11))):
        entry.uv = uv
    mesh.uv_layers["Rendered"].active_render = True
    mesh.uv_layers.active_index = 1
    obj = bpy.data.objects.new("Enscape export", mesh)
    bpy.context.scene.collection.objects.link(obj)
    for existing in bpy.context.selected_objects:
        existing.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    material = bpy.data.materials.new("Enscape Export Paint")
    material.use_nodes = True
    material["skppy_x_scale"] = 5000.0
    material["skppy_y_scale"] = 10000.0
    mesh.materials.append(material)
    tree = material.node_tree
    bsdf = tree.nodes["Principled BSDF"]
    bsdf.name = "Renamed active shader"
    # A disconnected default-named shader must not override the active shader.
    decoy = tree.nodes.new("ShaderNodeBsdfPrincipled")
    decoy.inputs["Metallic"].default_value = 1
    bsdf.inputs["Base Color"].default_value = (0.2158605, 0.05126946, 0, 1)
    bsdf.inputs["Metallic"].default_value = 0.5
    bsdf.inputs["Roughness"].default_value = 0.25
    bsdf.inputs["Specular IOR Level"].default_value = 0.25
    bsdf.inputs["IOR"].default_value = 2
    bsdf.inputs["Alpha"].default_value = 0.75
    with TemporaryDirectory(prefix="skppy-enscape-export-") as directory:
        directory = Path(directory)
        image_path = directory / "paint.png"
        image_path.write_bytes(pixels)
        image = bpy.data.images.load(str(image_path), check_existing=False)
        image.pack()
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        tree.links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
        alpha = tree.nodes.new("ShaderNodeMath")
        alpha.operation = "MULTIPLY"
        alpha.inputs[1].default_value = 0.75
        tree.links.new(texture.outputs["Alpha"], alpha.inputs[0])
        tree.links.new(alpha.outputs[0], bsdf.inputs["Alpha"])
        _add_diffuse_adjustments(tree, texture, bsdf)
        _check_diffuse_variants(builder_type, material, bsdf, texture)
        _check_uv_scale_variants(builder_type, material, texture)
        exporter = builder_type(bpy.context, export_scope="SELECTED", export_enscape_materials=True)
        model = exporter.build()
        converted = model.materials[0]
        pins = model.definitions[0].entities.faces[0].front_uv.pins
        assert [(pin.texture_position.x, pin.texture_position.y) for pin in pins] == [(0, 0), (5000, 0), (0, 10000)]
        assert mesh.uv_layers.active.name == "Editing"
        assert (converted.color.r, converted.color.g, converted.color.b) == (128, 64, 0)
        assert (converted.metallic, converted.roughness, converted.specular, converted.ior) == (0.5, 0.25, 0.25, 2)
        assert converted.alpha == 0.75 and converted.texture.data == pixels
        assert converted.texture.brightness == 0.5 and converted.texture.inverted is True
        assert converted.texture_fade == 0.25
        assert converted.texture.uv_scale == (2, 4)
        assert (converted.texture.x_scale, converted.texture.y_scale) == (5000, 10000)
        assert (converted.tint_color.r, converted.tint_color.g, converted.tint_color.b) == (128, 255, 64)
        assert exporter.warnings == []
        for format in ("modern", "sketchup_2017"):
            path = directory / f"enscape_export_{format}.skp"
            result = bpy.ops.export_scene.skp(
                filepath=str(path),
                export_scope="SELECTED",
                output_format=format,
                export_enscape_materials=True,
            )
            assert result == {"FINISHED"}
            if format == "modern":
                with zipfile.ZipFile(path) as archive:
                    raw = archive.read("model.dat")
                    assert archive.read("materials/Enscape Export Paint/paint.png") == pixels
                encoding = "utf-8"
            else:
                raw = path.read_bytes()
                encoding = "utf-16-le"
                assert pixels in raw
            for expected in (
                "Enscape.Material",
                "<Metallic>0.5</Metallic>",
                "<Roughness>0.25</Roughness>",
                "<IndexOfRefraction>2</IndexOfRefraction>",
                "<Specular>0.25</Specular>",
                "<Opacity>0.75</Opacity>",
                "<Source>SKETCHUP</Source>",
                "<TintColor>#80FF40</TintColor>",
                "<ImageFade>0.25</ImageFade>",
                "<Brightness>0.5</Brightness><IsInverted>true</IsInverted>",
                "<UseExplicitTransformation>true</UseExplicitTransformation><Width>63.5</Width><Height>63.5</Height>",
            ):
                assert expected.encode(encoding) in raw
            if export_output is not None:
                export_output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, export_output.parent / path.name)
        _check_rejections(builder_type, material, bsdf, texture, directory)
        tree.links.remove(bsdf.inputs["Alpha"].links[0])
        bsdf.inputs["Alpha"].default_value = 1
        bsdf.inputs["Transmission Weight"].default_value = 0.5
        converted = builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
        assert converted.transmission == 0.5 and converted.alpha == 1
        bsdf.inputs["Transmission Weight"].default_value = 0
        bsdf.inputs["Emission Color"].default_value = (1, 0.2158605, 0, 1)
        bsdf.inputs["Emission Strength"].default_value = 5000
        converted = builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
        assert converted.emission_strength == 5000
        assert (converted.emission_color.r, converted.emission_color.g, converted.emission_color.b) == (255, 128, 0)
    bpy.data.objects.remove(obj, do_unlink=True)


def _add_diffuse_adjustments(tree, image, bsdf) -> None:
    """Author the expected graph directly, without the production importer."""
    invert = tree.nodes.new("ShaderNodeInvert")
    invert.name = "Invert check"
    invert.inputs["Fac"].default_value = 1
    tree.links.new(image.outputs["Color"], invert.inputs["Color"])
    brightness = tree.nodes.new("ShaderNodeMixRGB")
    brightness.name = "Brightness check"
    brightness.blend_type = "MULTIPLY"
    brightness.inputs[0].default_value = 1
    brightness.inputs[2].default_value = (0.5, 0.5, 0.5, 1)
    tree.links.new(invert.outputs["Color"], brightness.inputs[1])
    tint = tree.nodes.new("ShaderNodeMixRGB")
    tint.name = "Tint check"
    tint.blend_type = "MULTIPLY"
    tint.inputs[0].default_value = 1
    tint.inputs[2].default_value = (0.2158605, 1, 0.05126946, 1)
    tree.links.new(brightness.outputs["Color"], tint.inputs[1])
    fade = tree.nodes.new("ShaderNodeMixRGB")
    fade.name = "Fade check"
    fade.blend_type = "MIX"
    fade.inputs[0].default_value = 0.25
    fade.inputs[1].default_value = (0.2158605, 0.05126946, 0, 1)
    tree.links.new(tint.outputs["Color"], fade.inputs[2])
    tree.links.new(fade.outputs["Color"], bsdf.inputs["Base Color"])
    for node in (invert, brightness, tint, fade):
        node.label = "Artist renamed this node"


def _check_diffuse_variants(builder_type, material, bsdf, image) -> None:
    """Check every supported prefix and equivalent neutral tint multiplication."""
    tree = material.node_tree
    cases = (
        (image, 1, False, (255, 255, 255), 1),
        (tree.nodes["Invert check"], 1, True, (255, 255, 255), 1),
        (tree.nodes["Brightness check"], 0.5, True, (255, 255, 255), 1),
        (tree.nodes["Tint check"], 0.5, True, (128, 255, 64), 1),
        (tree.nodes["Fade check"], 0.5, True, (128, 255, 64), 0.25),
    )
    for output, brightness, inverted, tint, fade in cases:
        tree.links.new(output.outputs["Color"], bsdf.inputs["Base Color"])
        converted = builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
        assert converted.texture.brightness == brightness and converted.texture.inverted == inverted
        assert (converted.tint_color.r, converted.tint_color.g, converted.tint_color.b) == tint
        assert converted.texture_fade == fade
    tint_node = tree.nodes["Tint check"]
    tint_node.inputs[2].default_value = (0.5, 0.5, 0.5, 1)
    converted = builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
    assert converted.texture.brightness == 0.25
    assert (converted.tint_color.r, converted.tint_color.g, converted.tint_color.b) == (255, 255, 255)
    tint_node.inputs[2].default_value = (0.2158605, 1, 0.05126946, 1)


def _check_uv_scale_variants(builder_type, material, texture) -> None:
    """Recognize scale-only graphs without relying on importer-created nodes."""
    tree = material.node_tree
    coordinate = tree.nodes.new("ShaderNodeTexCoord")
    multiply = tree.nodes.new("ShaderNodeVectorMath")
    multiply.operation = "MULTIPLY"
    multiply.inputs[1].default_value = (2, 4, 1)
    tree.links.new(coordinate.outputs["UV"], multiply.inputs[0])
    tree.links.new(multiply.outputs["Vector"], texture.inputs["Vector"])
    converted = builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
    assert converted.texture.uv_scale == (2, 4)
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.vector_type = "POINT"
    mapping.inputs["Scale"].default_value = (2, 4, 1)
    tree.links.new(coordinate.outputs["UV"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
    converted = builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
    assert converted.texture.uv_scale == (2, 4)

    def reject(expected):
        try:
            builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
        except ValueError as exc:
            assert expected in str(exc), str(exc)
        else:
            raise AssertionError(f"expected UV scale rejection: {expected}")

    for name in ("Location", "Rotation"):
        mapping.inputs[name].default_value = (1, 0, 0)
        reject("translation or rotation")
        mapping.inputs[name].default_value = (0, 0, 0)
    mapping.vector_type = "TEXTURE"
    reject("Point mapping")
    mapping.vector_type = "POINT"
    for scale in ((-2, 4, 1), (0, 4, 1), (2, 4, 2)):
        mapping.inputs["Scale"].default_value = scale
        reject("finite and positive")
    mapping.inputs["Scale"].default_value = (2, 4, 1)
    link = tree.links.new(coordinate.outputs["Generated"], mapping.inputs["Scale"])
    reject("constant mapping Scale")
    tree.links.remove(link)
    tree.links.new(multiply.outputs["Vector"], texture.inputs["Vector"])
    multiply.mute = True
    reject("unmuted")
    multiply.mute = False
    coordinate.from_instancer = True
    reject("active UV")
    coordinate.from_instancer = False
    uv_map = tree.nodes.new("ShaderNodeUVMap")
    tree.links.new(uv_map.outputs["UV"], multiply.inputs[0])
    converted = builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
    assert converted.texture.uv_scale == (2, 4)
    uv_map.uv_map = "Editing"
    reject("active UV")
    uv_map.uv_map = ""


def _check_rejections(builder_type, material, bsdf, texture, directory: Path) -> None:
    """Reject unsupported state and keep existing files intact on operator failure."""
    tree = material.node_tree

    def expect_rejection(message):
        try:
            builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
        except ValueError as exc:
            assert message in str(exc), str(exc)
        else:
            raise AssertionError(f"expected Enscape export to reject {message}")

    brightness = tree.nodes["Brightness check"]
    fade = tree.nodes["Fade check"]
    invert = tree.nodes["Invert check"]
    for node in (brightness, fade):
        node.use_clamp = True
        expect_rejection("unclamped")
        node.use_clamp = False
    brightness.inputs[0].default_value = 0.5
    expect_rejection("factor 1")
    brightness.inputs[0].default_value = 1
    invert.inputs["Fac"].default_value = 0.5
    expect_rejection("full-strength")
    invert.inputs["Fac"].default_value = 1
    input_link = tree.links.new(texture.outputs["Color"], fade.inputs[1])
    expect_rejection("constant base color")
    tree.links.remove(input_link)
    brightness.inputs[2].default_value = (-0.5, -0.5, -0.5, 1)
    # Blender clamps negative color channels to zero before the adapter sees them.
    assert tuple(brightness.inputs[2].default_value[:3]) == (0, 0, 0)
    black = builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
    assert black.texture.brightness == 0
    brightness.inputs[2].default_value = (0.5, 0.5, 0.5, 1)
    tint = tree.nodes["Tint check"]
    tint.inputs[2].default_value = (2, 1, 0.5, 1)
    expect_rejection("tint multipliers")
    tint.inputs[2].default_value = (0.2158605, 1, 0.05126946, 1)

    link = tree.links.new(texture.outputs["Color"], bsdf.inputs["Roughness"])
    expect_rejection("linked Roughness")
    destination = directory / "existing.skp"
    destination.write_bytes(b"original file")
    try:
        result = bpy.ops.export_scene.skp(
            filepath=str(destination), export_scope="SELECTED", export_enscape_materials=True
        )
    except RuntimeError as exc:
        assert "linked Roughness" in str(exc)
    else:
        assert result == {"CANCELLED"}
    assert destination.read_bytes() == b"original file"
    tree.links.remove(link)
    for name in (
        "Coat Weight",
        "Sheen Weight",
        "Subsurface Weight",
        "Anisotropic",
        "Diffuse Roughness",
        "Thin Film Thickness",
    ):
        bsdf.inputs[name].default_value = 0.5
        expect_rejection(name)
        bsdf.inputs[name].default_value = 0
    coordinate = tree.nodes.new("ShaderNodeTexCoord")
    link = tree.links.new(coordinate.outputs["Generated"], texture.inputs["Vector"])
    expect_rejection("active UV")
    tree.links.remove(link)
    tree.links.new(coordinate.outputs["UV"], texture.inputs["Vector"])
    builder_type(bpy.context, export_enscape_materials=True)._material_for(material)
    texture.extension = "CLIP"
    expect_rejection("repeating")
    texture.extension = "REPEAT"
    texture.interpolation = "Closest"
    expect_rejection("linear image interpolation")
    texture.interpolation = "Linear"
    image = texture.image
    transparent = bpy.data.images.new("Transparent rejection", width=1, height=1, alpha=True)
    transparent.pixels = (1, 1, 1, 0.5)
    texture.image = transparent
    alpha_link = bsdf.inputs["Alpha"].links[0]
    alpha_source = alpha_link.from_socket
    tree.links.remove(alpha_link)
    expect_rejection("pixels are transparent")
    tree.links.new(alpha_source, bsdf.inputs["Alpha"])
    texture.image = image
    bpy.data.images.remove(transparent)
    bsdf.inputs["Emission Color"].default_value = (2, 1, 1, 1)
    expect_rejection("finite RGB")
    bsdf.inputs["Emission Color"].default_value = (0, 0, 0, 1)
    bsdf.mute = True
    expect_rejection("muted")
    bsdf.mute = False
    output = tree.nodes["Material Output"]
    alternate = tree.nodes.new("ShaderNodeBsdfDiffuse")
    tree.links.new(alternate.outputs[0], output.inputs["Surface"])
    expect_rejection("direct Principled")
    tree.links.new(bsdf.outputs[0], output.inputs["Surface"])
    tree.nodes.remove(alternate)
    try:
        result = bpy.ops.export_scene.skp(
            filepath=str(destination),
            export_scope="SELECTED",
            export_enscape_materials=True,
            export_vray_materials=True,
        )
    except RuntimeError as exc:
        assert "either Enscape or V-Ray" in str(exc)
    else:
        assert result == {"CANCELLED"}
    assert destination.read_bytes() == b"original file"
