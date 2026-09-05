# SPDX-License-Identifier: MIT
"""Exercise Enscape SKM parsing and material construction in live Blender."""

import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

import bpy


def run(module_name: str, pixels: bytes) -> None:
    """Check opt-in appearance, relief routing, packed images, and color adjustments."""
    skppy = importlib.import_module(module_name).skppy
    builder = importlib.import_module(f"{module_name}.scene_builder").BlenderSceneBuilder
    for relief in ("BUMP", "NORMAL", "DISPLACEMENT"):
        xml = f"""<materialDocument><material name="Enscape {relief}" colorRed="10" colorGreen="20" colorBlue="30">
          <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
            <SketchupMaterial Version="4"><DiffuseColor>#405060</DiffuseColor><Opacity>0.4</Opacity>
              <TintColor>#8080FF</TintColor><ImageFade>0.25</ImageFade>
              <Metallic>0.7</Metallic><Roughness>0.2</Roughness><IndexOfRefraction>1.8</IndexOfRefraction>
              <EmissiveColor>#204060</EmissiveColor><EmissiveStrength>2</EmissiveStrength>
              <BumpMapType>{relief}</BumpMapType><BumpAmount>0.3</BumpAmount><NormalMapIntensity>0.6</NormalMapIntensity>
              <DiffuseTexture><Filepath>diffuse.png</Filepath><Brightness>0.7</Brightness><IsInverted>true</IsInverted>
              </DiffuseTexture>
              <RoughnessTexture><Filepath>roughness.png</Filepath><Brightness>0.8</Brightness><IsInverted>true</IsInverted>
              </RoughnessTexture>
              <BumpTexture><Filepath>relief.png</Filepath></BumpTexture>
            </SketchupMaterial>
          ]]></Attribute></AttributeDictionary>
        </material></materialDocument>"""
        with TemporaryDirectory(prefix="skppy-enscape-") as directory:
            path = Path(directory) / "enscape.skm"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("document.xml", xml)
                for name in ("diffuse.png", "roughness.png", "relief.png"):
                    archive.writestr(f"ref/{name}", pixels)
            plain = builder.build_material(skppy.load_material(path))
            plain_bsdf = plain.node_tree.nodes["Principled BSDF"]
            assert not plain_bsdf.inputs["Base Color"].is_linked
            assert plain_bsdf.inputs["Metallic"].default_value == 0
            assert plain_bsdf.inputs["Alpha"].default_value == 1
            bpy.data.materials.remove(plain)
            assert "FINISHED" in bpy.ops.import_scene.skp(filepath=str(path), import_vray_materials=True)

        material = bpy.data.materials[f"Enscape {relief}"]
        nodes = material.node_tree.nodes
        bsdf = nodes["Principled BSDF"]
        assert abs(bsdf.inputs["Metallic"].default_value - 0.7) < 1e-6
        assert abs(bsdf.inputs["IOR"].default_value - 1.8) < 1e-6
        assert abs(bsdf.inputs["Emission Strength"].default_value - 2) < 1e-6
        fade = bsdf.inputs["Base Color"].links[0].from_node
        assert fade.label == "SKP Image Fade" and fade.blend_type == "MIX"
        assert abs(fade.inputs[0].default_value - 0.25) < 1e-6
        tint = fade.inputs[2].links[0].from_node
        assert tint.label == "SKP Texture Tint" and tint.blend_type == "MULTIPLY"
        assert abs(tint.inputs[2].default_value[0] - 0.2158605) < 1e-6
        assert tint.inputs[2].default_value[2] == 1
        brightness = tint.inputs[1].links[0].from_node
        assert brightness.bl_idname == "ShaderNodeMixRGB" and brightness.blend_type == "MULTIPLY"
        assert abs(brightness.inputs[2].default_value[0] - 0.7) < 1e-6
        invert = brightness.inputs[1].links[0].from_node
        assert invert.bl_idname == "ShaderNodeInvert"
        diffuse = invert.inputs["Color"].links[0].from_node
        assert diffuse.image.colorspace_settings.name == "sRGB"
        alpha = bsdf.inputs["Alpha"].links[0].from_node
        assert alpha.bl_idname == "ShaderNodeMath" and alpha.operation == "MULTIPLY"
        assert abs(alpha.inputs[1].default_value - 0.4) < 1e-6
        assert alpha.inputs[0].links[0].from_socket == diffuse.outputs["Alpha"]
        roughness = bsdf.inputs["Roughness"].links[0].from_node
        assert roughness.operation == "MULTIPLY"
        assert abs(roughness.inputs[1].default_value - 0.8) < 1e-6
        assert roughness.inputs[0].links[0].from_node.operation == "SUBTRACT"
        images = [node.image for node in nodes if node.bl_idname == "ShaderNodeTexImage"]
        assert len(images) == 3
        assert all(image.packed_file and bytes(image.packed_file.data) == pixels for image in images)
        assert all(image.colorspace_settings.name == "Non-Color" for image in images if image != diffuse.image)
        if relief == "DISPLACEMENT":
            node = nodes["Material Output"].inputs["Displacement"].links[0].from_node
            assert node.bl_idname == "ShaderNodeDisplacement"
            assert abs(node.inputs["Scale"].default_value - 0.3) < 1e-6
        else:
            node = bsdf.inputs["Normal"].links[0].from_node
            assert node.bl_idname == ("ShaderNodeBump" if relief == "BUMP" else "ShaderNodeNormalMap")
            assert abs(node.inputs["Strength"].default_value - (0.3 if relief == "BUMP" else 0.6)) < 1e-6
        exporter = importlib.import_module(f"{module_name}.export_builder").BlenderModelBuilder(bpy.context)
        exporter._material_for(material)
        assert any("base-color node graph" in warning for warning in exporter.warnings)
    _run_glass(module_name)


def _run_glass(module_name: str) -> None:
    """Version-5 glass keeps its reflective surface instead of disappearing."""
    xml = """<materialDocument><material name="Enscape Glass">
      <AttributeDictionary name="Enscape.Material"><Attribute key="MaterialData"><![CDATA[
        <SketchupMaterial Version="5"><Type>GENERIC</Type><TypeV5>GLASS</TypeV5><Opacity>0.25</Opacity>
          <IndexOfRefraction>2.25606796116505</IndexOfRefraction><Roughness>0.238</Roughness>
        </SketchupMaterial>
      ]]></Attribute></AttributeDictionary>
    </material></materialDocument>"""
    with TemporaryDirectory(prefix="skppy-glass-") as directory:
        path = Path(directory) / "glass.skm"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("document.xml", xml)
        assert "FINISHED" in bpy.ops.import_scene.skp(filepath=str(path), import_vray_materials=True)
    material = bpy.data.materials["Enscape Glass"]
    bsdf = material.node_tree.nodes["Principled BSDF"]
    assert bsdf.inputs["Alpha"].default_value == 1
    assert not bsdf.inputs["Alpha"].is_linked
    assert abs(bsdf.inputs["Transmission Weight"].default_value - 0.75) < 1e-6
    assert abs(bsdf.inputs["IOR"].default_value - 2.25606796116505) < 1e-6
    assert abs(bsdf.inputs["Roughness"].default_value - 0.238) < 1e-6
    exporter = importlib.import_module(f"{module_name}.export_builder").BlenderModelBuilder(bpy.context)
    exporter._material_for(material)
    assert any("Transmission Weight" in warning for warning in exporter.warnings)
