# SPDX-License-Identifier: MIT
"""Run Blender addon integration assertions inside Blender's Python process."""

from __future__ import annotations

import argparse
import importlib
import io
import math
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_data import legacy_v8_bytes, modern_zip_bytes


def _arguments() -> argparse.Namespace:
    """Parse arguments following Blender's ``--`` separator."""
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--export-output", type=Path)
    return parser.parse_args(arguments)


def _png_rgba(alpha: int) -> bytes:
    """Return a valid one-pixel RGBA PNG without external image dependencies."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(bytes((0, 220, 120, 40, alpha)))
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def _material_package_bytes(name: str) -> bytes:
    """Return a standalone textured SketchUp material package."""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<materialDocument xmlns="http://sketchup.google.com/schemas/sketchup/1.0/material"
                  xmlns:mat="http://sketchup.google.com/schemas/sketchup/1.0/material">
  <mat:material name="{name}" colorRed="10" colorGreen="20" colorBlue="30"
                useTrans="1" trans="0.25" hasTexture="1">
    <mat:texture textureFilename="standalone.png" xScale="12.5" yScale="25">
      <mat:images><mat:image path="texture.png" file_name="standalone.png" /></mat:images>
    </mat:texture>
  </mat:material>
</materialDocument>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("document.xml", xml)
        archive.writestr("ref/texture.png", _png_rgba(255))
    return buffer.getvalue()


def _classification_package_bytes() -> bytes:
    """Return the unrelated ZIP payload found after some legacy models."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("document.xml", "<classificationDocument/>")
    return buffer.getvalue()


def _install_extension(addon: Path) -> str:
    """Install the packaged extension and return its importable module name."""
    if not addon.is_file():
        raise AssertionError(f"addon archive does not exist: {addon}")

    result = bpy.ops.extensions.package_install_files(
        filepath=str(addon.resolve()),
        repo="user_default",
        enable_on_install=True,
        overwrite=True,
    )
    if "FINISHED" not in result:
        raise AssertionError(f"Blender could not install the extension: {result}")

    module_name = "bl_ext.user_default.blender_skp_io"
    if module_name not in bpy.context.preferences.addons:
        raise AssertionError(f"extension was not enabled as {module_name}")
    return module_name


def _clear_scene() -> None:
    """Remove scene objects and unused test data before each scenario."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)


def _assert_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-6):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def _assert_uvs(mesh: bpy.types.Mesh) -> None:
    uv_layer = mesh.uv_layers.get("SKP UV")
    if uv_layer is None:
        raise AssertionError("synthetic mesh has no SKP UV layer")

    expected = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
    polygon = mesh.polygons[0]
    actual = [tuple(uv_layer.data[index].uv) for index in polygon.loop_indices]
    for corner, (actual_uv, expected_uv) in enumerate(zip(actual, expected)):
        _assert_close(actual_uv[0], expected_uv[0], f"UV {corner}.u")
        _assert_close(actual_uv[1], expected_uv[1], f"UV {corner}.v")


def _linked_from(socket, node_type: str, socket_name: str | None = None) -> bool:
    return any(
        link.from_node.bl_idname == node_type and (socket_name is None or link.from_socket.name == socket_name)
        for link in socket.links
    )


def _assert_materials(scene_builder) -> None:
    transparent = bpy.data.materials["Integration Transparent"]
    opaque = bpy.data.materials["Integration Opaque"]

    transparent_bsdf = transparent.node_tree.nodes["Principled BSDF"]
    opaque_bsdf = opaque.node_tree.nodes["Principled BSDF"]
    _assert_close(transparent_bsdf.inputs["Metallic"].default_value, 0.75, "metallic")
    _assert_close(transparent_bsdf.inputs["Roughness"].default_value, 0.2, "roughness")
    _assert_close(opaque_bsdf.inputs["Metallic"].default_value, 0.1, "opaque metallic")
    _assert_close(opaque_bsdf.inputs["Roughness"].default_value, 0.8, "opaque roughness")

    if not _linked_from(transparent_bsdf.inputs["Base Color"], "ShaderNodeTexImage", "Color"):
        raise AssertionError("texture color is not connected to Principled Base Color")
    if not _linked_from(transparent_bsdf.inputs["Alpha"], "ShaderNodeMath"):
        raise AssertionError("material opacity is not multiplied by texture alpha")
    if not _linked_from(opaque_bsdf.inputs["Alpha"], "ShaderNodeTexImage", "Alpha"):
        raise AssertionError("opaque texture alpha is not connected to Principled Alpha")

    if hasattr(transparent, "surface_render_method"):
        if transparent.surface_render_method != "DITHERED":
            raise AssertionError("transparent material is not dithered")
    elif transparent.blend_method != "HASHED":
        raise AssertionError("transparent material is not hashed")

    transparent_image = bpy.data.images["transparent.png"]
    opaque_image = bpy.data.images["opaque.png"]
    if not scene_builder.BlenderSceneBuilder._image_uses_alpha(transparent_image):
        raise AssertionError("transparent image alpha was not detected")
    if scene_builder.BlenderSceneBuilder._image_uses_alpha(opaque_image):
        raise AssertionError("opaque RGBA image was treated as transparent")


def _run_synthetic(module_name: str) -> None:
    """Build a deterministic shared Model and inspect Blender data blocks."""
    addon = importlib.import_module(module_name)
    skppy = addon.skppy
    scene_builder = importlib.import_module(f"{module_name}.scene_builder")

    model = skppy.Model.new()
    transparent = model.add_material(
        "Integration Transparent",
        color=skppy.Color(120, 160, 200),
        alpha=0.5,
        metallic=0.75,
        roughness=0.2,
    )
    transparent.has_texture = True
    transparent.texture = skppy.Texture(
        filename="transparent.png",
        x_scale=2.0,
        y_scale=4.0,
        data=_png_rgba(96),
    )
    opaque = model.add_material(
        "Integration Opaque",
        color=skppy.Color(220, 180, 140),
        metallic=0.1,
        roughness=0.8,
    )
    opaque.has_texture = True
    opaque.texture = skppy.Texture(
        filename="opaque.png",
        x_scale=2.0,
        y_scale=4.0,
        data=_png_rgba(255),
    )

    first = model.entities.add_face(
        ((0, 0, 0), (4, 0, 0), (4, 8, 0), (0, 8, 0)),
        material_id=transparent.id,
    )
    first.front_uv = skppy.FaceUVProjection()
    second = model.entities.add_face(
        ((6, 0, 0), (10, 0, 0), (10, 8, 0), (6, 8, 0)),
        material_id=opaque.id,
    )
    second.front_uv = skppy.FaceUVProjection()

    builder = scene_builder.BlenderSceneBuilder(model, bpy.context)
    builder.build()
    meshes = [obj.data for obj in builder.created_objects if obj.type == "MESH"]
    if len(meshes) != 1 or len(meshes[0].polygons) != 2:
        raise AssertionError("synthetic import did not create one two-face mesh")
    _assert_uvs(meshes[0])
    _assert_materials(scene_builder)


def _run_loose_edges(module_name: str) -> None:
    """Verify root and instanced 2D linework becomes shared Blender meshes."""
    addon = importlib.import_module(module_name)
    skppy = addon.skppy
    scene_builder = importlib.import_module(f"{module_name}.scene_builder")

    model = skppy.Model.new()
    root_start = model.entities.add_vertex(0.0, 0.0, 0.0)
    root_end = model.entities.add_vertex(10.0, 0.0, 0.0)
    hidden_end = model.entities.add_vertex(10.0, 10.0, 0.0)
    model.entities.add_edge(root_start, root_end)
    hidden = model.entities.add_edge(root_end, hidden_end)
    hidden.flags = 0x01

    definition = model.add_definition("Linework")
    line_start = definition.entities.add_vertex(0.0, 0.0, 0.0)
    line_end = definition.entities.add_vertex(0.0, 5.0, 0.0)
    definition.entities.add_edge(line_start, line_end)
    model.entities.add_instance(definition, name="Linework A")
    model.entities.add_instance(definition, name="Linework B")

    builder = scene_builder.BlenderSceneBuilder(model, bpy.context, import_materials=False)
    builder.build()
    root_object = next((obj for obj in builder.created_objects if obj.name == "RootGeometry"), None)
    if root_object is None or len(root_object.data.edges) != 1 or len(root_object.data.polygons) != 0:
        raise AssertionError("root loose or hidden edges were not imported correctly")
    instances = [obj for obj in builder.created_objects if obj.name in {"Linework A", "Linework B"}]
    if len(instances) != 2 or any(len(obj.data.edges) != 1 for obj in instances):
        raise AssertionError("line-only component instances were not imported")
    if instances[0].data is not instances[1].data:
        raise AssertionError("line-only instances did not share cached mesh data")


def _run_layer_collections(module_name: str) -> None:
    """Verify layer grouping links root geometry to the intended collections."""
    addon = importlib.import_module(module_name)
    skppy = addon.skppy
    scene_builder = importlib.import_module(f"{module_name}.scene_builder")

    model = skppy.Model.new()
    visible = model.add_layer("Integration Visible")
    hidden = model.add_layer("Integration Hidden", visible=False)
    first = model.entities.add_face(((0, 0, 0), (2, 0, 0), (0, 2, 0)))
    second = model.entities.add_face(((4, 0, 0), (6, 0, 0), (4, 2, 0)))
    first.layer_id = visible.id
    second.layer_id = hidden.id
    model.entities.guide_points.append(skppy.GuidePoint(id=101, position=(1.0, 1.0, 1.0), layer_id=visible.id))
    model.entities.guide_lines.append(
        skppy.GuideLine(
            id=102,
            point=(0.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0),
            layer_id=visible.id,
        )
    )
    model.entities.section_planes.append(
        skppy.SectionPlane(
            id=103,
            plane=(0.0, 0.0, 1.0, -2.0),
            name="Integration Section",
            layer_id=hidden.id,
        )
    )

    builder = scene_builder.BlenderSceneBuilder(
        model,
        bpy.context,
        import_materials=False,
        import_by_layers=True,
    )
    builder.build()

    visible_collection = builder._layer_collections[visible.id]
    hidden_collection = builder._layer_collections[hidden.id]
    if len(visible_collection.objects) != 3:
        raise AssertionError("visible layer did not receive its mesh and guides")
    if len(hidden_collection.objects) != 2:
        raise AssertionError("hidden layer did not receive its mesh and section plane")
    if visible_collection.hide_viewport:
        raise AssertionError("visible layer collection is hidden")
    if not hidden_collection.hide_viewport:
        raise AssertionError("hidden layer collection remains visible")
    guide_line = bpy.data.objects["GuideLine_102"]
    if guide_line.type != "MESH" or not guide_line.hide_render:
        raise AssertionError("guide line is not a non-rendering mesh edge")
    section = bpy.data.objects["Integration Section"]
    if tuple(section["skppy_section_plane"]) != (0.0, 0.0, 1.0, -2.0):
        raise AssertionError("section plane equation was not preserved")


def _hierarchy_model(skppy):
    """Build nested shared definitions used by both hierarchy modes."""
    model = skppy.Model.new()
    leaf = model.add_definition("Hierarchy Leaf")
    leaf.entities.add_face(((0, 0, 0), (1, 0, 0), (0, 1, 0)))

    container = model.add_definition("Hierarchy Container")
    container.entities.add_face(((0, 0, 0), (2, 0, 0), (0, 2, 0)))
    container.entities.add_instance(
        leaf,
        transform=skppy.Transform.from_translation(2.0, 0.0, 0.0),
        name="Nested Leaf",
    )
    container.entities.guide_points.append(skppy.GuidePoint(id=901, position=(1.0, 0.0, 0.0)))

    model.entities.add_instance(
        leaf,
        transform=skppy.Transform.from_translation(1.0, 0.0, 0.0),
        name="Leaf A",
    )
    model.entities.add_instance(
        leaf,
        transform=skppy.Transform.from_translation(5.0, 0.0, 0.0),
        name="Leaf B",
    )
    model.entities.add_instance(
        container,
        transform=skppy.Transform.from_translation(10.0, 0.0, 0.0),
        name="Container",
    )
    return model


def _run_hierarchy_modes(module_name: str) -> None:
    """Verify optimized hierarchy, flattening, transforms, sharing, and cycles."""
    addon = importlib.import_module(module_name)
    skppy = addon.skppy
    scene_builder = importlib.import_module(f"{module_name}.scene_builder")

    builder = scene_builder.BlenderSceneBuilder(
        _hierarchy_model(skppy),
        bpy.context,
        import_materials=False,
    )
    builder.build()
    bpy.context.view_layer.update()

    leaf_a = bpy.data.objects["Leaf A"]
    leaf_b = bpy.data.objects["Leaf B"]
    container = bpy.data.objects["Container"]
    container_faces = bpy.data.objects["Container:faces"]
    nested = bpy.data.objects["Nested Leaf"]
    guide = bpy.data.objects["GuidePoint_901"]
    if leaf_a.type != "MESH" or leaf_a.parent is not None:
        raise AssertionError("mesh-only leaf gained a redundant Empty parent")
    if leaf_a.data is not leaf_b.data:
        raise AssertionError("instances of one definition do not share mesh data")
    if container.type != "EMPTY" or container.empty_display_type != "PLAIN_AXES":
        raise AssertionError("nested definition did not create a container Empty")
    if container_faces.parent is not container or container_faces.type != "MESH":
        raise AssertionError("container faces were not parented below the Empty")
    if nested.parent is not container or guide.parent is not container:
        raise AssertionError("nested definition contents lost their parent")
    _assert_close(container.matrix_world.translation.x, 10.0 * builder.scale, "container world x")
    _assert_close(nested.matrix_world.translation.x, 12.0 * builder.scale, "nested world x")
    _assert_close(guide.matrix_world.translation.x, 11.0 * builder.scale, "guide world x")

    _clear_scene()
    flat_builder = scene_builder.BlenderSceneBuilder(
        _hierarchy_model(skppy),
        bpy.context,
        import_materials=False,
        flatten_hierarchy=True,
    )
    flat_builder.build()
    bpy.context.view_layer.update()

    flat_a = bpy.data.objects["Leaf A"]
    flat_b = bpy.data.objects["Leaf B"]
    flat_container = bpy.data.objects["Container"]
    flat_nested = bpy.data.objects["Nested Leaf"]
    flat_guide = bpy.data.objects["GuidePoint_901"]
    if any(obj.parent is not None for obj in flat_builder.created_objects):
        raise AssertionError("flattened import retained object parenting")
    if flat_container.type != "MESH":
        raise AssertionError("flattened container did not expose its direct faces")
    if flat_a.data is not flat_b.data or flat_a.data is not flat_nested.data:
        raise AssertionError("flattened instances stopped sharing definition meshes")
    _assert_close(
        flat_container.matrix_world.translation.x,
        10.0 * flat_builder.scale,
        "flat container world x",
    )
    _assert_close(
        flat_nested.matrix_world.translation.x,
        12.0 * flat_builder.scale,
        "flat nested world x",
    )
    _assert_close(
        flat_guide.matrix_world.translation.x,
        11.0 * flat_builder.scale,
        "flat guide world x",
    )

    _clear_scene()
    cyclic = skppy.Model.new()
    first = cyclic.add_definition("Cycle A")
    second = cyclic.add_definition("Cycle B")
    first.entities.add_instance(second)
    second.entities.add_instance(first)
    cyclic.entities.add_instance(first)
    try:
        scene_builder.BlenderSceneBuilder(
            cyclic,
            bpy.context,
            import_materials=False,
        ).build()
    except skppy.ComponentCycleError:
        pass
    else:
        raise AssertionError("recursive component definitions were not rejected")


def _run_collection_instances(module_name: str) -> None:
    """Verify reusable collection hierarchies avoid expanded object copies."""
    addon = importlib.import_module(module_name)
    scene_builder = importlib.import_module(f"{module_name}.scene_builder")
    builder = scene_builder.BlenderSceneBuilder(
        _hierarchy_model(addon.skppy),
        bpy.context,
        import_materials=False,
        use_collection_instances=True,
    )
    builder.build()

    if len(builder.created_objects) != 3:
        raise AssertionError("collection import exposed internal definition objects as scene objects")
    leaf_a = bpy.data.objects["Leaf A"]
    leaf_b = bpy.data.objects["Leaf B"]
    container = bpy.data.objects["Container"]
    if any(obj.instance_type != "COLLECTION" for obj in (leaf_a, leaf_b, container)):
        raise AssertionError("root components were not imported as collection instances")
    if leaf_a.instance_collection is not leaf_b.instance_collection:
        raise AssertionError("repeated components did not share their definition collection")
    nested = container.instance_collection.objects.get("Nested Leaf")
    if nested is None or nested.instance_type != "COLLECTION":
        raise AssertionError("nested component was expanded instead of instanced")
    if nested.instance_collection is not leaf_a.instance_collection:
        raise AssertionError("nested and root components did not reuse one definition collection")
    if any(child is container.instance_collection for child in builder._import_col.children):
        raise AssertionError("definition source collection was linked visibly beside its instances")
    _assert_close(container.matrix_world.translation.x, 10.0 * builder.scale, "collection container x")
    _assert_close(nested.matrix_world.translation.x, 2.0 * builder.scale, "collection nested local x")


def _run_face_modes(module_name: str) -> None:
    """Verify NGON, triangle, and quad topology modes in Blender itself."""
    addon = importlib.import_module(module_name)
    skppy = addon.skppy
    scene_builder = importlib.import_module(f"{module_name}.scene_builder")
    expected_polygon_counts = {"NGONS": 1, "TRIS": 2, "QUADS": 1}

    for mode, expected_count in expected_polygon_counts.items():
        _clear_scene()
        model = skppy.Model.new()
        model.entities.add_face(((0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)))
        builder = scene_builder.BlenderSceneBuilder(
            model,
            bpy.context,
            import_materials=False,
            triangulation_mode=mode,
        )
        builder.build()
        meshes = [obj.data for obj in builder.created_objects if obj.type == "MESH"]
        if len(meshes) != 1 or len(meshes[0].polygons) != expected_count:
            actual = [len(mesh.polygons) for mesh in meshes]
            raise AssertionError(f"{mode} expected {expected_count} polygons, got {actual}")


def _run_annotations(module_name: str) -> None:
    """Verify visible text and dimension representations and component placement."""
    addon = importlib.import_module(module_name)
    skppy = addon.skppy
    scene_builder = importlib.import_module(f"{module_name}.scene_builder")

    model = skppy.Model.new()
    model.entities.texts.append(
        skppy.Text(
            id=201,
            text="Integration Label",
            anchor=skppy.PointReference(position=skppy.Vector3D(1.0, 2.0, 0.0)),
            leader_vector=skppy.Vector3D(2.0, 0.0, 0.0),
        )
    )
    model.entities.linear_dimensions.append(
        skppy.LinearDimension(
            id=202,
            text="4 in",
            start=skppy.PointReference(position=skppy.Vector3D(0.0, 0.0, 0.0)),
            end=skppy.PointReference(position=skppy.Vector3D(4.0, 0.0, 0.0)),
            offset=1.0,
            drawing=skppy.DrawingElementProperties(hidden=True),
        )
    )
    definition = model.add_definition("Annotation Definition")
    definition.entities.radial_dimensions.append(
        skppy.RadialDimension(
            id=203,
            text="R2",
            radius_ratio=2.0,
            arc=skppy.ArcGeometry(),
        )
    )
    model.entities.add_instance(
        definition,
        transform=skppy.Transform.from_translation(10.0, 0.0, 0.0),
        name="Annotation Component",
    )

    builder = scene_builder.BlenderSceneBuilder(
        model,
        bpy.context,
        import_materials=False,
    )
    builder.build()

    text = bpy.data.objects["Text_201"]
    if text.type != "FONT" or text.data.body != "Integration Label":
        raise AssertionError("text annotation did not become a Blender Font object")
    _assert_close(text.location.x, 3.0 * builder.scale, "text leader placement")
    if len(bpy.data.objects["TextLeader_201"].data.edges) != 1:
        raise AssertionError("text leader did not retain its segment")

    linear_lines = bpy.data.objects["LinearDimension_202:lines"]
    linear_text = bpy.data.objects["LinearDimension_202:text"]
    if len(linear_lines.data.edges) != 3:
        raise AssertionError("linear dimension did not retain extension lines")
    if not linear_lines.hide_viewport or not linear_text.hide_render:
        raise AssertionError("dimension hidden state was not preserved")

    radial_text = bpy.data.objects["RadialDimension_203:text"]
    if radial_text.type != "FONT" or radial_text["skppy_radius_ratio"] != 2.0:
        raise AssertionError("radial dimension metadata was not preserved")
    if radial_text.parent is None or radial_text.parent.name != "Annotation Component":
        raise AssertionError("definition annotation did not inherit its component")
    _assert_close(radial_text.location.x, 2.0 * builder.scale, "radial text position")


def _run_cameras_and_scenes(module_name: str) -> None:
    """Verify standalone and scene-owned cameras and saved page metadata."""
    addon = importlib.import_module(module_name)
    skppy = addon.skppy
    scene_builder = importlib.import_module(f"{module_name}.scene_builder")

    model = skppy.Model.new()
    model.cameras.append(
        skppy.Camera(
            name="Standalone Camera",
            eye=skppy.Vector3D(1.0, 2.0, 3.0),
            target=skppy.Vector3D(1.0, 2.0, 0.0),
            fov=50.0,
        )
    )
    scene_camera = skppy.Camera(
        eye=skppy.Vector3D(10.0, 0.0, 5.0),
        target=skppy.Vector3D(0.0, 0.0, 0.0),
        is_perspective=False,
        ortho_height=20.0,
    )
    model.scenes.append(
        skppy.Scene(
            id=7,
            name="Saved Scene",
            description="Integration page",
            camera=scene_camera,
            hidden_entity_ids=[11],
            hidden_layer_ids=[12],
            active_section_plane_ids=[13],
            show_in_slideshow=False,
        )
    )

    builder = scene_builder.BlenderSceneBuilder(
        model,
        bpy.context,
        import_materials=False,
    )
    builder.build()

    standalone = bpy.data.objects["Standalone Camera"]
    saved = bpy.data.objects["Saved Scene"]
    if standalone.type != "CAMERA" or standalone.data.type != "PERSP":
        raise AssertionError("standalone perspective camera was not imported")
    _assert_close(standalone.location.x, builder.scale, "camera eye x")
    _assert_close(standalone.data.angle_y, math.radians(50.0), "camera FOV")
    _assert_close(standalone.data.clip_end, 100_000.0, "camera far clipping plane")
    if saved.data.type != "ORTHO":
        raise AssertionError("saved scene camera did not retain projection")
    _assert_close(saved.data.ortho_scale, 20.0 * builder.scale, "ortho height")
    if saved["skppy_scene_id"] != 7 or list(saved["skppy_hidden_layer_ids"]) != [12]:
        raise AssertionError("saved scene metadata was not preserved")
    if saved["skppy_show_in_slideshow"]:
        raise AssertionError("saved scene slideshow state was not preserved")


def _run_export(module_name: str, export_output: Path | None = None) -> None:
    """Build Blender data, export it, and inspect the public model graph."""
    addon = importlib.import_module(module_name)
    exporter = importlib.import_module(f"{module_name}.export_builder")
    export_operator = bpy.ops.export_scene.skp.get_rna_type()
    if export_operator.properties["export_vray_materials"].default is not False:
        raise AssertionError("V-Ray material export must be opt-in")

    collection = bpy.data.collections.new("Export Tag")
    bpy.context.scene.collection.children.link(collection)
    mesh = bpy.data.meshes.new("Export Shared Mesh")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 4.0, 0.0),
            (0.0, 4.0, 0.0),
            (1.0, 1.0, 0.0),
            (1.0, 3.0, 0.0),
            (3.0, 3.0, 0.0),
            (3.0, 1.0, 0.0),
        ),
        (),
        ((0, 1, 7, 4), (1, 2, 6, 7), (2, 3, 5, 6), (3, 0, 4, 5)),
    )
    uv_layer = mesh.uv_layers.new(name="Export UV")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv_layer.data[loop_index].uv = (vertex.x / 4.0, vertex.y / 4.0)

    material = bpy.data.materials.new("Export Material")
    material["skppy_x_scale"] = 2.5
    material["skppy_y_scale"] = 4.0
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.25, 0.5, 0.75, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.6
    bsdf.inputs["Roughness"].default_value = 0.3
    bsdf.inputs["Alpha"].default_value = 0.8
    with TemporaryDirectory(prefix="skppy-blender-export-texture-") as directory:
        texture_path = Path(directory) / "export.png"
        texture_path.write_bytes(_png_rgba(192))
        image = bpy.data.images.load(str(texture_path))
        image.pack()
    texture_node = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture_node.image = image
    material.node_tree.links.new(texture_node.outputs["Color"], bsdf.inputs["Base Color"])
    mesh.materials.append(material)

    first = bpy.data.objects.new("Export First", mesh)
    first.location = (1.0, 2.0, 3.0)
    first["author"] = "integration"
    collection.objects.link(first)
    second = bpy.data.objects.new("Export Second", mesh)
    second.location = (5.0, 0.0, 0.0)
    collection.objects.link(second)

    instance_source = bpy.data.collections.new("Export Instance Source")
    instance_source.instance_offset = (1.0, 2.0, 3.0)
    member_parent = bpy.data.objects.new("Export Collection Parent", None)
    member_parent.location = (2.0, 0.0, 0.0)
    instance_source.objects.link(member_parent)
    collection_mesh = bpy.data.meshes.new("Export Collection Mesh")
    collection_mesh.from_pydata(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
        (),
        ((0, 1, 2), (0, 3, 1), (0, 4, 3)),
    )
    for polygon in collection_mesh.polygons:
        polygon.use_smooth = True
    sharp_edge = next(edge for edge in collection_mesh.edges if set(edge.vertices) == {0, 3})
    sharp_edge.use_edge_sharp = True
    member = bpy.data.objects.new("Export Collection Member", collection_mesh)
    member.parent = member_parent
    member.location = (0.0, 0.0, 1.0)
    member["skppy_layer_name"] = "Export Instance Source"
    instance_source.objects.link(member)
    instance_child = bpy.data.collections.new("Export Instance Child")
    instance_source.children.link(instance_child)
    instance_child.objects.link(member)
    collection_instance = bpy.data.objects.new("Export Collection Instance", None)
    collection_instance.instance_type = "COLLECTION"
    collection_instance.instance_collection = instance_source
    collection_instance.location = (0.0, 10.0, 0.0)
    collection.objects.link(collection_instance)

    font_data = bpy.data.curves.new("Export Text Data", type="FONT")
    font_data.body = "Export Label"
    label = bpy.data.objects.new("Export Label", font_data)
    label.location = (0.0, 4.0, 0.0)
    collection.objects.link(label)

    camera_data = bpy.data.cameras.new("Export Camera Data")
    camera = bpy.data.objects.new("Export Camera", camera_data)
    camera.location = (8.0, -8.0, 6.0)
    camera.rotation_euler = (math.radians(65.0), 0.0, math.radians(45.0))
    collection.objects.link(camera)
    bpy.context.scene.camera = camera
    marker = bpy.context.scene.timeline_markers.new("Export View", frame=1)
    marker.camera = camera

    builder = exporter.BlenderModelBuilder(
        bpy.context,
        export_scope="SCENE",
        inches_per_unit=10.0,
        apply_modifiers=False,
    )
    model = builder.build()
    if len(model.definitions) != 3 or len(model.entities.component_instances) != 3:
        raise AssertionError("shared Blender mesh was not exported as one definition")
    definition = next(value for value in model.definitions if value.name == "Export Shared Mesh")
    if (
        len(definition.entities.faces) != 1
        or len(definition.entities.faces[0].inner_loops) != 1
        or definition.entities.faces[0].front_uv is None
    ):
        raise AssertionError("coplanar export did not retain UV data and its inner-loop hole")
    if len(model.materials) != 1 or model.materials[0].texture is None:
        raise AssertionError("exported material did not retain its embedded texture")
    _assert_close(model.materials[0].texture.x_scale, 2.5, "export texture x scale")
    _assert_close(model.materials[0].texture.y_scale, 4.0, "export texture y scale")
    _assert_close(model.materials[0].metallic, 0.6, "export metallic")
    _assert_close(model.materials[0].roughness, 0.3, "export roughness")
    if {layer.name for layer in model.layers} != {
        "Export Tag",
        "Export Instance Source",
    }:
        raise AssertionError("Blender collections were not exported as tags")
    collection_definition = next(value for value in model.definitions if value.name == "Export Instance Source")
    if len(collection_definition.entities.component_instances) != 1:
        raise AssertionError("collection instance duplicated a multiply-linked mesh")
    collection_member = collection_definition.entities.component_instances[0]
    collection_member_matrix = addon.skppy.Transform(collection_member.transform).matrix
    expected_member_translation = (10.0, -20.0, -20.0)
    for axis, expected in enumerate(expected_member_translation):
        _assert_close(collection_member_matrix[axis, 3], expected, f"collection member axis {axis}")
    if len(model.entities.texts) != 1 or model.entities.texts[0].text != "Export Label":
        raise AssertionError("Blender Font object was not exported as text")
    if len(model.cameras) != 1 or len(model.scenes) != 1:
        raise AssertionError("camera and timeline marker were not exported")
    instance = model.entities.component_instances[0]
    dictionaries = model.entities.attribute_dictionaries_by_entity_id[instance.id]
    if dictionaries[0].entries[0].string_value != "integration":
        raise AssertionError("object custom property was not exported")

    with TemporaryDirectory(prefix="skppy-blender-export-") as directory:
        output = Path(directory) / "scene.skp"
        result = bpy.ops.export_scene.skp(
            filepath=str(output),
            export_scope="SCENE",
            inches_per_unit=10.0,
            export_vray_materials=True,
        )
        if "FINISHED" not in result or not output.is_file():
            raise AssertionError(f"SKP export did not finish: {result}")
        legacy_output = Path(directory) / "scene_2017.skp"
        legacy_result = bpy.ops.export_scene.skp(
            filepath=str(legacy_output),
            export_scope="SCENE",
            inches_per_unit=10.0,
            output_format="sketchup_2017",
            export_vray_materials=True,
        )
        if "FINISHED" not in legacy_result or not legacy_output.is_file():
            raise AssertionError(f"SketchUp 2017 export did not finish: {legacy_result}")
        loaded = addon.skppy.load(output, import_vray_materials=True)
        if len(loaded.entities.component_instances) != 3:
            raise AssertionError("exported SKP lost root component instances")
        if len(loaded.definitions) != 3 or not any(len(value.entities.faces) == 1 for value in loaded.definitions):
            raise AssertionError("exported SKP lost reusable mesh geometry")
        loaded_material = next(value for value in loaded.materials if value.name == "Export Material")
        _assert_close(loaded_material.metallic, 0.6, "modern V-Ray metallic")
        _assert_close(loaded_material.roughness, 0.3, "modern V-Ray roughness")
        legacy_loaded = addon.skppy.load(legacy_output, import_vray_materials=True)
        legacy_material = next(value for value in legacy_loaded.materials if value.name == "Export Material")
        _assert_close(legacy_material.metallic, 0.6, "legacy V-Ray metallic")
        _assert_close(legacy_material.roughness, 0.3, "legacy V-Ray roughness")
        if export_output is not None:
            export_output.parent.mkdir(parents=True, exist_ok=True)
            export_output.write_bytes(output.read_bytes())
            legacy_destination = export_output.with_name(f"{export_output.stem}_2017{export_output.suffix}")
            legacy_destination.write_bytes(legacy_output.read_bytes())


def _run_fixture(fixture: Path, *, require_mesh: bool = True) -> None:
    """Exercise the public import operator and automatic format detection."""
    if not fixture.is_file():
        raise AssertionError(f"SKP fixture does not exist: {fixture}")
    _clear_scene()
    result = bpy.ops.import_scene.skp(filepath=str(fixture.resolve()))
    if "FINISHED" not in result:
        raise AssertionError(f"SKP import did not finish: {result}")
    if require_mesh and not any(obj.type == "MESH" for obj in bpy.context.scene.objects):
        raise AssertionError("SKP fixture import produced no mesh objects")


def _run_automatic_dispatch(module_name: str) -> None:
    """Load and import models and materials without a format selector."""
    addon = importlib.import_module(module_name)
    with TemporaryDirectory(prefix="skppy-blender-dispatch-") as directory:
        fixtures = Path(directory)
        modern_path = fixtures / "modern.skp"
        legacy_path = fixtures / "legacy.skp"
        hybrid_path = fixtures / "legacy-with-metadata.skp"
        material_path = fixtures / "standalone.skm"
        misnamed_material_path = fixtures / "misnamed-material.skp"
        modern_path.write_bytes(modern_zip_bytes())
        legacy_path.write_bytes(legacy_v8_bytes())
        hybrid_path.write_bytes(legacy_v8_bytes() + _classification_package_bytes())
        material_path.write_bytes(_material_package_bytes("Integration Standalone SKM"))
        misnamed_material_path.write_bytes(_material_package_bytes("Integration Misnamed SKM"))

        modern = addon.skppy.load(modern_path)
        if modern.header is None or modern.header.version_tuple != (26, 0, 0):
            raise AssertionError("modern fixture did not use the ZIP/TLV parser")
        if modern.legacy_archive is not None:
            raise AssertionError("modern fixture leaked legacy provenance")

        legacy = addon.skppy.load(legacy_path)
        if legacy.header is None or legacy.header.version_tuple != (8, 0, 1):
            raise AssertionError("legacy fixture version was not detected")
        if legacy.legacy_archive is None:
            raise AssertionError("legacy fixture did not use the CArchive parser")

        hybrid = addon.skppy.load(hybrid_path)
        if hybrid.header is None or hybrid.header.version_tuple != (8, 0, 1):
            raise AssertionError("legacy fixture with appended ZIP used the wrong parser")
        try:
            addon.skppy.load_material(hybrid_path)
        except addon.skppy.InvalidSkmError:
            pass
        else:
            raise AssertionError("legacy model metadata was mistaken for a material")

        _clear_scene()
        _run_fixture(modern_path, require_mesh=False)
        _clear_scene()
        _run_fixture(legacy_path, require_mesh=False)
        _clear_scene()
        _run_fixture(hybrid_path, require_mesh=False)

        for path, name in (
            (material_path, "Integration Standalone SKM"),
            (misnamed_material_path, "Integration Misnamed SKM"),
        ):
            result = bpy.ops.import_scene.skp(filepath=str(path.resolve()))
            if "FINISHED" not in result:
                raise AssertionError(f"standalone material import did not finish: {result}")
            material = bpy.data.materials.get(name)
            if material is None or not material.use_fake_user:
                raise AssertionError(f"standalone material was not retained: {name}")
            _assert_close(material["skppy_x_scale"], 12.5, "standalone texture x scale")
            _assert_close(material["skppy_y_scale"], 25.0, "standalone texture y scale")
            bsdf = material.node_tree.nodes["Principled BSDF"]
            if not _linked_from(bsdf.inputs["Base Color"], "ShaderNodeTexImage", "Color"):
                raise AssertionError(f"standalone material texture was not linked: {name}")


def main() -> None:
    """Install the addon and execute all requested integration scenarios."""
    args = _arguments()
    module_name = _install_extension(args.addon)
    _clear_scene()
    _run_synthetic(module_name)
    _clear_scene()
    _run_loose_edges(module_name)
    _clear_scene()
    _run_layer_collections(module_name)
    _clear_scene()
    _run_hierarchy_modes(module_name)
    _clear_scene()
    _run_collection_instances(module_name)
    _clear_scene()
    _run_face_modes(module_name)
    _clear_scene()
    _run_annotations(module_name)
    _clear_scene()
    _run_cameras_and_scenes(module_name)
    _clear_scene()
    _run_export(module_name, args.export_output)
    _run_automatic_dispatch(module_name)
    if args.fixture is not None:
        _run_fixture(args.fixture)
    print("Blender integration assertions passed")


if __name__ == "__main__":
    main()
