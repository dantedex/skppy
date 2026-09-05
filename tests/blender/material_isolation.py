# SPDX-License-Identifier: MIT
"""Live Blender regressions for import ownership and renderer-only UVs."""

import importlib

import bpy


def run(module_name: str) -> None:
    """Import conflicting appearances without changing existing scene data."""
    skppy = importlib.import_module(module_name).skppy
    builder_type = importlib.import_module(f"{module_name}.scene_builder").BlenderSceneBuilder
    original = bpy.data.materials.new("Ownership Test")
    original.use_nodes = True
    original_bsdf = original.node_tree.nodes.get("Principled BSDF")
    original_bsdf.inputs["Roughness"].default_value = 0.23
    image_node = original.node_tree.nodes.new("ShaderNodeTexImage")
    original.node_tree.links.new(image_node.outputs["Color"], original_bsdf.inputs["Base Color"])
    original_nodes = len(original.node_tree.nodes)
    unrelated_mesh = bpy.data.meshes.new("Existing mesh")
    unrelated_mesh.materials.append(None)

    material = skppy.Material(name="Ownership Test", roughness=0.71)
    first = builder_type.build_material(material)
    second = builder_type.build_material(material)
    assert first != original and second != first
    assert len(original.node_tree.nodes) == original_nodes
    assert abs(original_bsdf.inputs["Roughness"].default_value - 0.23) < 1e-6
    assert original_bsdf.inputs["Base Color"].is_linked
    assert not second.node_tree.nodes["Principled BSDF"].inputs["Base Color"].is_linked

    model = skppy.Model.new()
    pbr = model.add_material("Renderer only")
    pbr.roughness_texture = skppy.Texture(filename="missing.png", x_scale=2.0, y_scale=4.0)
    model.entities.add_face([(0, 0, 0), (2, 0, 0), (2, 2, 0)], material_id=pbr.id)
    builder = builder_type(model, bpy.context)
    builder.build()
    mesh = next(obj.data for obj in builder.created_objects if obj.type == "MESH")
    assert len(mesh.uv_layers) == 1
    assert tuple(mesh.uv_layers.active.data[2].uv) == (1.0, 0.5)
    assert unrelated_mesh.materials[0] is None

    kinds = ("objects", "collections", "meshes", "curves", "cameras", "materials", "images")
    previous = {kind: set(getattr(bpy.data, kind)) for kind in kinds}

    def fail_after_geometry(fraction, message):
        if fraction >= 0.8:
            raise RuntimeError("injected build failure")

    failing = builder_type(model, bpy.context, progress_callback=fail_after_geometry)
    try:
        failing.build()
    except RuntimeError as error:
        assert str(error) == "injected build failure"
    else:
        raise AssertionError("failure injection was not reached")
    assert previous == {kind: set(getattr(bpy.data, kind)) for kind in kinds}

    broken = skppy.Material(
        name="Broken image", has_texture=True, texture=skppy.Texture(filename="bad.png", data=b"bad")
    )
    try:
        builder_type.build_material(broken)
    except ValueError as error:
        assert "Could not decode texture" in str(error)
        pass
    else:
        raise AssertionError("invalid image unexpectedly loaded")
    assert previous == {kind: set(getattr(bpy.data, kind)) for kind in kinds}
