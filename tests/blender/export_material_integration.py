# SPDX-License-Identifier: MIT
"""Isolated live builder/operator material-export regressions for the parent runner."""

from __future__ import annotations

import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import bpy
import numpy as np

if __package__:
    from .export_material_baking import _decode_png, _snapshot
else:
    from export_material_baking import _decode_png, _snapshot


_KINDS = ("scenes", "objects", "collections", "meshes", "materials", "images", "node_groups")
_BAKE = {"bake_materials": True, "bake_resolution": 32, "bake_margin": 0}
_EXPORT = {"export_scope": "SCENE", "apply_modifiers": False, "merge_coplanar_faces": False}


def _data() -> dict[str, set[Any]]:
    return {kind: set(getattr(bpy.data, kind)) for kind in _KINDS}


def _material(name: str) -> tuple[Any, Any]:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    shader = tree.nodes.get("Principled BSDF")
    shader.name = "Actual renamed surface"
    # A name-based lookup must not export this disconnected closure instead.
    decoy = tree.nodes.new("ShaderNodeBsdfPrincipled")
    decoy.name = "Principled BSDF"
    decoy.inputs["Base Color"].default_value = (1, 0, 1, 1)
    decoy.inputs["Metallic"].default_value = 1
    decoy.inputs["Roughness"].default_value = 1
    decoy.inputs["Alpha"].default_value = 0
    tree.nodes.active = decoy
    shader.select = False
    return material, shader


def _fixture(scene: Any) -> tuple[tuple[Any, Any], tuple[Any, ...], Any]:
    procedural, shader = _material("Integration procedural")
    shader.inputs["Base Color"].default_value = (0.2, 0.4, 0.6, 1)
    shader.inputs["Alpha"].default_value = 0.35
    shader.inputs["Metallic"].default_value = 0.27
    shader.inputs["Roughness"].default_value = 0.63
    tree = procedural.node_tree
    coordinates = tree.nodes.new("ShaderNodeTexCoord")
    separate = tree.nodes.new("ShaderNodeSeparateXYZ")
    combine = tree.nodes.new("ShaderNodeCombineXYZ")
    checker = tree.nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = 2
    checker.inputs["Color1"].default_value = (0.25, 0.5, 1, 1)
    checker.inputs["Color2"].default_value = (1, 0.25, 0, 1)
    tree.links.new(coordinates.outputs["Generated"], separate.inputs[0])
    tree.links.new(separate.outputs["X"], combine.inputs["X"])
    tree.links.new(separate.outputs["Y"], combine.inputs["Y"])
    tree.links.new(combine.outputs[0], checker.inputs["Vector"])
    tree.links.new(checker.outputs["Color"], shader.inputs["Base Color"])
    tree.links.new(separate.outputs["X"], shader.inputs["Alpha"])
    # Color/alpha baking must not silently promise a roughness map as well.
    tree.links.new(checker.outputs["Fac"], shader.inputs["Roughness"])

    constant, constant_shader = _material("Integration constant")
    constant_shader.inputs["Base Color"].default_value = (0.2, 0.4, 0.6, 1)
    constant_shader.inputs["Alpha"].default_value = 0.7
    constant_shader.inputs["Metallic"].default_value = 0.4
    constant_shader.inputs["Roughness"].default_value = 0.3

    unused, unused_shader = _material("Integration UNUSED unsafe material")
    unsafe = unused.node_tree.nodes.new("ShaderNodeObjectInfo")
    unused.node_tree.links.new(unsafe.outputs["Color"], unused_shader.inputs["Base Color"])

    mesh = bpy.data.meshes.new("Integration shared mesh")
    mesh.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (3, 0, 0), (4, 0, 0), (4, 1, 0), (3, 1, 0)],
        [],
        [(0, 1, 2, 3), (4, 5, 6, 7)],
    )
    uv = mesh.uv_layers.new(name="Existing destination UV")
    for index, point in enumerate(((0, 0), (1, 0), (1, 1), (0, 1)) * 2):
        uv.data[index].uv = point
    # Duplicate slots and overlapping UVs on a different material are valid.
    for material in (unused, constant, procedural, procedural):
        mesh.materials.append(material)
    mesh.polygons[0].material_index = 3
    mesh.polygons[1].material_index = 1
    first = bpy.data.objects.new("Integration first", mesh)
    second = bpy.data.objects.new("Integration second", mesh)
    for obj in (first, second):
        scene.collection.objects.link(obj)
    first.location = (7, -3, 2)
    second.location = (-4, 11, -3)
    second.rotation_euler = (0.2, 0.3, 0.4)
    second.scale = (3, 1, 2)
    first.select_set(True)
    bpy.context.view_layer.objects.active = first
    bpy.context.view_layer.update()
    return (first, second), (procedural, constant, unused), shader


def _source_state(objects: tuple[Any, ...], materials: tuple[Any, ...]) -> tuple[Any, ...]:
    scene = bpy.context.scene
    return (
        _data(),
        tuple(_snapshot(obj, material) for obj in objects for material in materials),
        tuple(
            (
                material.diffuse_color[:],
                tuple(
                    (
                        node.name,
                        tuple(
                            tuple(socket.default_value)
                            if hasattr(socket.default_value, "__len__")
                            else socket.default_value
                            for socket in node.inputs
                            if hasattr(socket, "default_value")
                        ),
                    )
                    for node in material.node_tree.nodes
                ),
            )
            for material in materials
        ),
        scene.render.engine,
        scene.cycles.device,
        scene.cycles.samples,
        scene.render.resolution_x,
        scene.render.resolution_y,
        scene.render.resolution_percentage,
        scene.render.bake.margin,
        scene.render.image_settings.file_format,
        scene.render.image_settings.color_mode,
        scene.view_settings.view_transform,
    )


def _rgb(material: Any) -> tuple[int, int, int]:
    return material.color.r, material.color.g, material.color.b


def _near(actual: float, expected: float) -> None:
    assert abs(actual - expected) < 1e-6, (actual, expected)


def _pixels(material: Any) -> None:
    assert material.has_texture and material.texture is not None
    assert material.texture.filename.endswith(".png")
    pixels = _decode_png(material.texture.data)
    assert pixels.shape == (32, 32, 4), pixels.shape
    # Independent expected values, not a comparison against another export/bake.
    # The other quad extends Generated bounds to x=4. Alpha is Generated X,
    # i.e. (x + 0.5) / 128, and the checker changes color halfway up the UVs.
    for x, y, rgb in (
        (8, 8, (137, 188, 255)),
        (24, 8, (137, 188, 255)),
        (8, 24, (255, 137, 0)),
        (24, 24, (255, 137, 0)),
    ):
        expected = (*rgb, round((x + 0.5) / 128 * 255))
        actual = pixels[y, x].astype(int)
        assert np.max(np.abs(actual - expected)) <= 2, (material.name, x, y, actual, expected)


def _assert_model(model: Any, objects: tuple[Any, ...]) -> None:
    instances = {instance.name: instance for instance in model.entities.component_instances}
    assert set(instances) == {obj.name for obj in objects}
    definitions = {definition.id: definition for definition in model.definitions}
    assert len(definitions) == 2, "Procedural shared mesh needs per-object definitions"
    assert len({instance.definition_id for instance in instances.values()}) == 2
    materials = {material.id: material for material in model.materials}
    assert len(materials) == 3, "Only two baked variants and the shared constant should be emitted"
    assert not any("UNUSED" in material.name for material in materials.values())
    baked_ids = set()
    constant_ids = set()
    for obj in objects:
        definition = definitions[instances[obj.name].definition_id]
        assert len(definition.entities.faces) == 2
        procedural_face, constant_face = definition.entities.faces
        assert procedural_face.front_material_id != constant_face.front_material_id
        assert procedural_face.front_uv is not None and constant_face.front_uv is not None
        baked = materials[procedural_face.front_material_id]
        constant = materials[constant_face.front_material_id]
        assert baked.name.startswith("Integration procedural"), baked.name
        assert constant.name == "Integration constant", constant.name
        baked_ids.add(baked.id)
        constant_ids.add(constant.id)
        assert _rgb(baked) == (255, 255, 255)
        _near(baked.alpha, 1)
        _near(baked.metallic, 0.27)
        _near(baked.roughness, 0.63)
        assert baked.roughness_texture is None
        assert baked.opacity_texture is None, "Baked alpha belongs in the base-color PNG"
        _pixels(baked)
        assert not constant.has_texture and constant.texture is None
        assert _rgb(constant) == (124, 170, 203)
        _near(constant.alpha, 0.7)
        _near(constant.metallic, 0.4)
        _near(constant.roughness, 0.3)
    assert len(baked_ids) == 2 and len(constant_ids) == 1
    assert baked_ids | constant_ids == set(materials)


def _builder(builder_type: Any, objects: tuple[Any, ...], materials: tuple[Any, ...]) -> None:
    before = _source_state(objects, materials)
    builder = builder_type(bpy.context, **_EXPORT, **_BAKE)
    model = builder.build()
    assert _source_state(objects, materials) == before, "Builder mutated source data/context or leaked bake data"
    _assert_model(model, objects)
    assert any("Roughness map" in warning for warning in builder.warnings), builder.warnings
    assert not any("requires baking" in warning for warning in builder.warnings), builder.warnings
    assert not any("UNUSED" in warning for warning in builder.warnings), builder.warnings
    first, second = objects
    assert (
        builder._material_for(materials[0], first, first.data).id
        != builder._material_for(materials[0], second, second.data).id
    )
    assert len(model.materials) == 3, "Repeated lookup must reuse each object's baked material"
    assert _source_state(objects, materials) == before
    _baked_uv_projection(builder, first, model.materials[0].id)
    assert _source_state(objects, materials) == before


def _baked_uv_projection(builder: Any, obj: Any, material_id: int) -> None:
    """Reuse an already baked material to check projection guards without more Cycles passes."""
    assert material_id in builder._baked_material_ids
    mesh = obj.data.copy()
    try:
        uv = mesh.uv_layers.active.data
        polygon = mesh.polygons[0]
        original = uv[2].uv[:]
        uv[2].uv.x -= 1e-6
        builder._face_uv_projection(mesh, polygon, uv, polygon.normal, material_id)
        uv[2].uv.x = original[0] - 1e-3
        try:
            builder._face_uv_projection(mesh, polygon, uv, polygon.normal, material_id)
        except ValueError as error:
            assert "Non-affine baked" in str(error), str(error)
        else:
            raise AssertionError("Baked UV residual above 1e-5 was approximated")
        uv[2].uv = original
        for index in polygon.loop_indices:
            uv[index].uv.y = 0
        try:
            builder._face_uv_projection(mesh, polygon, uv, polygon.normal, material_id)
        except ValueError as error:
            assert "nonsingular" in str(error), str(error)
        else:
            raise AssertionError("Singular baked UV projection was replaced by identity")
    finally:
        bpy.data.meshes.remove(mesh)


def _incompatible_flags(builder_type: Any, objects: tuple[Any, ...], materials: tuple[Any, ...]) -> None:
    for flag in ("export_uvs", "export_textures"):
        before = _source_state(objects, materials)
        builder = builder_type(bpy.context, **_EXPORT, **_BAKE, **{flag: False})
        try:
            builder.build()
        except ValueError as error:
            assert "Embedded Textures and UV Coordinates" in str(error), str(error)
        else:
            raise AssertionError(f"Material baking unexpectedly allowed {flag}=False")
        assert _source_state(objects, materials) == before, f"Failed {flag}=False build mutated source/context"


def _uv_cache_variants(builder_type: Any) -> None:
    """One material must retain direct-image and mismatched-UV variants in either order."""
    baseline = _data()
    try:
        material, shader = _material("Integration UV cache variants")
        shader.inputs["Base Color"].default_value = (0.2, 0.4, 0.6, 1)
        generated = bpy.data.images.new("Integration UV cache pixels", width=2, height=2, alpha=True)
        generated.alpha_mode = "STRAIGHT"
        generated.colorspace_settings.name = "sRGB"
        generated.pixels[:] = (1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 1, 0.25, 0.5, 0.75, 1)
        generated.update()
        with TemporaryDirectory(prefix="skppy-export-uv-cache-") as directory:
            generated.filepath_raw = str(Path(directory) / "shared.png")
            generated.file_format = "PNG"
            generated.save()
            image = bpy.data.images.load(generated.filepath_raw, check_existing=False)
            image.alpha_mode = "STRAIGHT"
            image.colorspace_settings.name = "sRGB"
            image.pack()
        assert image.source == "FILE" and not image.is_dirty and image.packed_file is not None
        packed = bytes(image.packed_file.data)
        pixels = tuple(image.pixels[:])
        tree = material.node_tree
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        source = tree.nodes.new("ShaderNodeUVMap")
        source.uv_map = "Shared source UV"
        tree.links.new(source.outputs["UV"], texture.inputs["Vector"])
        tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        objects = []
        for name, active_index in (("UV compatible A", 0), ("UV mismatch B", 1)):
            mesh = bpy.data.meshes.new(name)
            mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
            source_uv = mesh.uv_layers.new(name=source.uv_map)
            destination_uv = mesh.uv_layers.new(name="Different destination UV")
            for index, point in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
                source_uv.data[index].uv = point
                destination_uv.data[index].uv = (1 - point[0], point[1])
            source_uv.active_render = True
            mesh.uv_layers.active_index = active_index
            mesh.materials.append(material)
            obj = bpy.data.objects.new(name, mesh)
            bpy.context.scene.collection.objects.link(obj)
            objects.append(obj)
        bpy.context.view_layer.update()
        compatible, mismatch = objects
        before = _source_state(tuple(objects), (material,))
        for order in (objects, list(reversed(objects))):
            builder = builder_type(bpy.context, **_EXPORT, bake_materials=False)
            # Override only enumeration so the real build sees each exact traversal order.
            with patch.object(builder, "_objects_to_export", return_value=order):
                model = builder.build()
            assert len(model.materials) == 2 and len(model.definitions) == 2
            direct = builder._material_for(material, compatible, compatible.data)
            fallback = builder._material_for(material, mismatch, mismatch.data)
            assert direct.id != fallback.id, "UV compatibility was lost in the material cache"
            assert direct.has_texture and direct.texture is not None
            assert direct.texture.data == packed
            assert not fallback.has_texture and fallback.texture is None
            assert _rgb(fallback) == (124, 170, 203)
            assert set(builder._material_map) == {
                (material.as_pointer(), 0, True, False, False),
                (material.as_pointer(), 0, False, True, False),
            }
            warnings = [warning for warning in builder.warnings if "requires baking" in warning]
            assert len(warnings) == 1 and material.name in warnings[0], builder.warnings
            definitions = {definition.id: definition for definition in model.definitions}
            expected_ids = {compatible.name: direct.id, mismatch.name: fallback.id}
            for instance in model.entities.component_instances:
                face = definitions[instance.definition_id].entities.faces[0]
                assert face.front_material_id == expected_ids[instance.name]
            assert len(model.materials) == 2, "Repeated material lookup duplicated a UV variant"
            assert _source_state(tuple(objects), (material,)) == before
            assert bytes(image.packed_file.data) == packed and tuple(image.pixels[:]) == pixels
    finally:
        for kind in _KINDS:
            collection = getattr(bpy.data, kind)
            for item in set(collection) - baseline[kind]:
                collection.remove(item, do_unlink=True)
    assert _data() == baseline, "UV cache regression leaked fixture data"


def _noise_ramp_shaders(builder_type: Any) -> None:
    """Bake a real multi-node color expression on three supported surface closures."""
    baseline = _data()
    try:
        mesh = bpy.data.meshes.new("Integration Noise ramp plane")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        uv = mesh.uv_layers.new(name="Noise ramp destination UV")
        for index, point in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
            uv.data[index].uv = point
        obj = bpy.data.objects.new("Integration Noise ramp object", mesh)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.update()
        for kind, expected_alpha in (
            ("ShaderNodeBsdfPrincipled", 89),
            ("ShaderNodeBsdfDiffuse", 255),
            ("ShaderNodeBsdfTranslucent", 255),
        ):
            material = bpy.data.materials.new(f"Integration Noise ramp {kind}")
            material.use_nodes = True
            tree = material.node_tree
            tree.nodes.clear()
            output = tree.nodes.new("ShaderNodeOutputMaterial")
            output.target = "CYCLES"
            output.is_active_output = True
            shader = tree.nodes.new(kind)
            shader.name = "Renamed Noise ramp surface"
            if kind == "ShaderNodeBsdfPrincipled":
                shader.inputs["Alpha"].default_value = 0.35
            coordinates = tree.nodes.new("ShaderNodeTexCoord")
            noise = tree.nodes.new("ShaderNodeTexNoise")
            noise.noise_dimensions = "3D"
            noise.inputs["Scale"].default_value = 4
            noise.inputs["Detail"].default_value = 2
            ramp = tree.nodes.new("ShaderNodeValToRGB")
            ramp.color_ramp.interpolation = "LINEAR"
            ramp.color_ramp.elements[0].position = 0.25
            ramp.color_ramp.elements[0].color = (1, 0, 0, 1)
            ramp.color_ramp.elements[1].position = 0.75
            ramp.color_ramp.elements[1].color = (0, 0, 1, 1)
            color_input = "Base Color" if kind == "ShaderNodeBsdfPrincipled" else "Color"
            tree.links.new(coordinates.outputs["Generated"], noise.inputs["Vector"])
            tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
            tree.links.new(ramp.outputs["Color"], shader.inputs[color_input])
            tree.links.new(shader.outputs[0], output.inputs["Surface"])
            tree.nodes.active = ramp
            mesh.materials.clear()
            mesh.materials.append(material)
            before = _source_state((obj,), (material,))
            ramp_before = tuple((element.position, tuple(element.color)) for element in ramp.color_ramp.elements)
            builder = builder_type(bpy.context, **_EXPORT, **_BAKE)
            with patch.object(builder, "_objects_to_export", return_value=[obj]):
                model = builder.build()
            assert _source_state((obj,), (material,)) == before, f"{kind} bake mutated source/context"
            assert (
                tuple((element.position, tuple(element.color)) for element in ramp.color_ramp.elements) == ramp_before
            )
            assert ramp.color_ramp.interpolation == "LINEAR" and noise.noise_dimensions == "3D"
            assert output.is_active_output and output.target == "CYCLES"
            assert len(model.materials) == 1 and len(model.definitions) == 1
            exported = model.materials[0]
            assert model.definitions[0].entities.faces[0].front_material_id == exported.id
            assert exported.id in builder._baked_material_ids
            assert _rgb(exported) == (255, 255, 255)
            _near(exported.alpha, 1)
            assert exported.has_texture and exported.texture is not None
            pixels = _decode_png(exported.texture.data)
            assert pixels.shape == (32, 32, 4), pixels.shape
            interior = pixels[2:-2, 2:-2].astype(int)
            # Noise is not a cross-version exact-pixel oracle. The red-to-blue
            # ramp independently constrains channels, variation, and scalar alpha.
            assert np.max(interior[:, :, 1]) == 0, (kind, "unexpected green")
            for channel in (0, 2):
                values = interior[:, :, channel]
                assert np.max(values) - np.min(values) > 40, (kind, channel, "lost procedural variation")
                assert np.max(values) > 180, (kind, channel, "lost ramp endpoint range")
            encoded = interior[:, :, (0, 2)] / 255.0
            linear = np.where(encoded <= 0.04045, encoded / 12.92, ((encoded + 0.055) / 1.055) ** 2.4)
            assert np.max(np.abs(linear.sum(axis=2) - 1)) < 0.02, (kind, "not a red/blue linear ramp")
            assert np.max(np.abs(interior[:, :, 3] - expected_alpha)) <= 1, (kind, "incorrect scalar alpha")
            if kind == "ShaderNodeBsdfTranslucent":
                assert any("Transmission" in warning and "opaque" in warning for warning in builder.warnings), (
                    builder.warnings
                )
            else:
                assert not builder.warnings, builder.warnings
    finally:
        for kind in _KINDS:
            collection = getattr(bpy.data, kind)
            for item in set(collection) - baseline[kind]:
                collection.remove(item, do_unlink=True)
    assert _data() == baseline, "Noise ramp shader regressions leaked fixture data"


def _bake_off(builder_type: Any, objects: tuple[Any, ...], materials: tuple[Any, ...], shader: Any) -> None:
    material = materials[0]
    tree = material.node_tree
    original = shader.inputs["Base Color"].links[0].from_socket
    image = bpy.data.images.new("Integration upstream image", width=2, height=2)
    loaded = None
    texture = tree.nodes.new("ShaderNodeTexImage")
    invert = tree.nodes.new("ShaderNodeInvert")
    try:
        with TemporaryDirectory(prefix="skppy-export-upstream-") as directory:
            image.filepath_raw = str(Path(directory) / "upstream.png")
            image.file_format = "PNG"
            image.save()
            loaded = bpy.data.images.load(image.filepath_raw, check_existing=False)
            loaded.pack()
        texture.image = loaded
        tree.links.new(texture.outputs["Color"], invert.inputs["Color"])
        tree.links.new(invert.outputs["Color"], shader.inputs["Base Color"])
        before = _source_state(objects, materials)
        builder = builder_type(bpy.context, **_EXPORT, bake_materials=False)
        model = builder.build()
        assert _source_state(objects, materials) == before
        assert len(model.materials) == 2 and len(model.definitions) == 1
        exported = next(value for value in model.materials if value.name == material.name)
        assert not exported.has_texture and exported.texture is None, "Do not select an arbitrary upstream image"
        assert _rgb(exported) == (124, 170, 203)
        _near(exported.alpha, 0.35)
        _near(exported.metallic, 0.27)
        _near(exported.roughness, 0.63)
        assert exported.roughness_texture is None
        assert any("requires baking" in warning for warning in builder.warnings), builder.warnings
        assert any("Roughness map" in warning for warning in builder.warnings), builder.warnings
        assert not any("UNUSED" in warning for warning in builder.warnings)
    finally:
        tree.nodes.remove(invert)
        tree.nodes.remove(texture)
        tree.links.new(original, shader.inputs["Base Color"])
        if loaded is not None:
            bpy.data.images.remove(loaded)
        bpy.data.images.remove(image)


def _operator(skppy: Any, objects: tuple[Any, ...], materials: tuple[Any, ...]) -> None:
    with TemporaryDirectory(prefix="skppy-export-material-integration-") as directory:
        output = Path(directory) / "baked.skp"
        before = _source_state(objects, materials)
        result = bpy.ops.export_scene.skp(filepath=str(output), output_format="modern", **_EXPORT, **_BAKE)
        assert result == {"FINISHED"} and output.is_file(), result
        assert _source_state(objects, materials) == before, "Operator mutated source data/context or leaked bake data"
        _assert_model(skppy.load(output), objects)

        for flag in ("export_uvs", "export_textures"):
            _operator_failure(output, objects, materials, ("Embedded Textures and UV Coordinates",), **{flag: False})

        mesh = objects[0].data
        uv = mesh.uv_layers.active.data
        original = uv[2].uv[:]
        uv[2].uv = (0.7, 1)
        try:
            _operator_failure(output, objects, materials, ("Non-affine baked", "triangulation"))
        finally:
            uv[2].uv = original
        mesh.uv_layers.remove(mesh.uv_layers.active)
        _operator_failure(output, objects, materials, ("UV", "existing", materials[0].name))
        assert len(mesh.uv_layers) == 0, "Export must not unwrap the source mesh"


def _operator_failure(
    output: Path, objects: tuple[Any, ...], materials: tuple[Any, ...], fragments: tuple[str, ...], **options: Any
) -> None:
    sentinel = b"Existing destination must survive a failed material bake\x00\xff"
    output.write_bytes(sentinel)
    before = _source_state(objects, materials)
    # ERROR reports normally make bpy.ops raise rather than return CANCELLED.
    try:
        result = bpy.ops.export_scene.skp(filepath=str(output), output_format="modern", **_EXPORT, **_BAKE, **options)
    except RuntimeError as error:
        message = str(error)
        assert all(fragment.lower() in message.lower() for fragment in fragments), message
        if "existing" in fragments:
            assert any(obj.name in message for obj in objects), message
    else:
        assert result == {"CANCELLED"}, result
    assert output.read_bytes() == sentinel, "Failed export overwrote an existing destination"
    assert _source_state(objects, materials) == before, "Failed operator mutated source data/context or leaked data"


def run(module_name: str) -> None:
    """Exercise real builder/baking and registered export operator without scene interference."""
    builder_type = importlib.import_module(f"{module_name}.export_builder").BlenderModelBuilder
    skppy = importlib.import_module(module_name).skppy
    baseline = _data()
    window = bpy.context.window
    original_scene = window.scene
    original_layer = window.view_layer
    original_context = (bpy.context.mode, tuple(bpy.context.selected_objects), original_layer.objects.active)
    scene = bpy.data.scenes.new("Material export integration isolated scene")
    try:
        window.scene = scene
        objects, materials, shader = _fixture(scene)
        _uv_cache_variants(builder_type)
        _noise_ramp_shaders(builder_type)
        _incompatible_flags(builder_type, objects, materials)
        _builder(builder_type, objects, materials)
        _bake_off(builder_type, objects, materials, shader)
        _operator(skppy, objects, materials)
    finally:
        window.scene = original_scene
        window.view_layer = original_layer
        # Remove only data created by this helper, including leftovers on failure.
        for kind in _KINDS:
            collection = getattr(bpy.data, kind)
            for item in set(collection) - baseline[kind]:
                collection.remove(item, do_unlink=True)
    assert _data() == baseline, "Material export integration leaked its fixture data"
    assert (bpy.context.mode, tuple(bpy.context.selected_objects), original_layer.objects.active) == original_context, (
        "Material export integration changed the caller's mode, selection or active object"
    )
