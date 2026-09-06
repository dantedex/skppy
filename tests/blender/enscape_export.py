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
    obj = bpy.data.objects.new("Enscape export", mesh)
    bpy.context.scene.collection.objects.link(obj)
    for existing in bpy.context.selected_objects:
        existing.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    material = bpy.data.materials.new("Enscape Export Paint")
    material.use_nodes = True
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
        exporter = builder_type(bpy.context, export_scope="SELECTED", export_enscape_materials=True)
        converted = exporter.build().materials[0]
        assert (converted.color.r, converted.color.g, converted.color.b) == (128, 64, 0)
        assert (converted.metallic, converted.roughness, converted.specular, converted.ior) == (0.5, 0.25, 0.25, 2)
        assert converted.alpha == 0.75 and converted.texture.data == pixels
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
