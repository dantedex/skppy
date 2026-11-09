# SPDX-License-Identifier: MIT
"""V-Ray PBR material graph decoding tests."""

import io
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest

import skppy
from skppy.parser.material_parser import _parse_material_xml
from skppy.parser_legacy.parser import parse_legacy_bytes
from skppy.parser.vray_materials import (
    _list_references,
    apply_vray_attribute_dictionaries,
    apply_vray_materials,
    apply_vray_xml,
)
from tests.blender.fixture_data import legacy_v8_bytes


def _plugin(name: str, class_name: str, params: object, user_data: object = None) -> tuple[str, str]:
    return name, json.dumps(
        {
            "name": name,
            "class": class_name,
            "params": params,
            "userData": user_data if user_data is not None else {},
        },
    )


def _dictionaries(main: str, plugins: list[tuple[str, str]]) -> list[skppy.AttributeDictionary]:
    return [
        skppy.AttributeDictionary(
            name="VRayInfo",
            entries=[skppy.AttributeDictionaryEntry(key="main_plugin", value_type=3, string_value=main)],
        ),
        skppy.AttributeDictionary(
            name="VRayPlugins",
            entries=[
                skppy.AttributeDictionaryEntry(key=key, value_type=3, string_value=value) for key, value in plugins
            ],
        ),
    ]


def test_applies_single_vray_brdf_scalars_and_linear_diffuse_color() -> None:
    plugins = [
        ("invalid", "not json"),
        _plugin("/Material", "MtlSingleBRDF", {"brdf": "/Material/BRDF"}),
        _plugin(
            "/Material/BRDF",
            "BRDFVRayMtl",
            {
                "diffuse": "Color(0.215861,0.215861,0.215861)",
                "metalness": "0.51",
                "option_use_roughness": "1",
                "reflect_glossiness": "0.43",
            },
        ),
    ]
    material = skppy.Material(color=skppy.Color(1, 2, 3))

    assert apply_vray_attribute_dictionaries(material, _dictionaries("/Material", plugins))
    assert material.metallic == pytest.approx(0.51)
    assert material.roughness == pytest.approx(0.43)
    assert material.color == skppy.Color(128, 128, 128)


def test_converts_vray_reflection_glossiness_to_roughness() -> None:
    plugins = [
        _plugin("/Material", "MtlSingleBRDF", {"brdf": "/Material/BRDF"}),
        _plugin(
            "/Material/BRDF",
            "BRDFVRayMtl",
            {"metalness": "0", "option_use_roughness": "0", "reflect_glossiness": "0.640823"},
        ),
    ]
    material = skppy.Material()

    assert apply_vray_attribute_dictionaries(material, _dictionaries("/Material", plugins))
    assert material.roughness == pytest.approx(0.359177)


@pytest.mark.parametrize("use_roughness", ["0", "1"])
@pytest.mark.parametrize("value", [None, "missing_texture", "nan"])
def test_missing_vray_roughness_preserves_existing_value(use_roughness: str, value: str | None) -> None:
    params = {"option_use_roughness": use_roughness}
    if value is not None:
        params["reflect_glossiness"] = value
    material = skppy.Material(roughness=0.2)
    plugins = [_plugin("/Material/BRDF", "BRDFVRayMtl", params)]

    assert apply_vray_attribute_dictionaries(material, _dictionaries("/Material/BRDF", plugins))
    assert material.roughness == pytest.approx(0.2)


def test_uses_scalar_fallbacks_when_vray_parameters_reference_textures() -> None:
    plugins = [
        _plugin("/Material", "MtlSingleBRDF", {"brdf": "/Material/BRDF"}),
        _plugin(
            "/Material/BRDF",
            "BRDFVRayMtl",
            {
                "diffuse": "/Material/Diffuse",
                "metalness": "/Material/Metalness",
                "option_use_roughness": "yes",
                "reflect_glossiness": "/Material/Roughness",
            },
            {"metalness_float": "1.2", "reflect_glossiness_float": "-0.2"},
        ),
    ]
    material = skppy.Material(color=skppy.Color(10, 20, 30))

    assert apply_vray_attribute_dictionaries(material, _dictionaries("/Material", plugins))
    assert material.metallic == 1.0
    assert material.roughness == 0.0
    assert material.color == skppy.Color(10, 20, 30)


def test_preserves_enscape_roughness_when_vray_parameter_references_its_texture() -> None:
    plugins = [
        _plugin(
            "/Material",
            "BRDFVRayMtl",
            {"option_use_roughness": "1", "reflect_glossiness": "/Roughness"},
            {"reflect_glossiness_float": "0"},
        ),
    ]
    material = skppy.Material(roughness=0.72, roughness_texture=skppy.Texture(filename="roughness.jpg"))

    assert apply_vray_attribute_dictionaries(material, _dictionaries("/Material", plugins))
    assert material.roughness == pytest.approx(0.72)


def test_resolves_wrapped_and_layered_vray_material_graph() -> None:
    plugins = [
        _plugin("/Material", "MtlSingleBRDF", {"brdf": "/Stats"}),
        _plugin("/Stats", "MtlRenderStats", {"base_mtl": "/ID"}),
        _plugin("/ID", "MtlMaterialID", {"base_mtl": "/Bump"}),
        _plugin("/Bump", "BRDFBump", {"base_brdf": "/Layered"}),
        _plugin("/Layered", "BRDFLayered", {"brdfs": "List(/Missing,/PBR)"}),
        _plugin(
            "/PBR",
            "BRDFVRayMtl",
            {"metalness": "1", "option_use_roughness": "true", "reflect_glossiness": "0.15"},
        ),
    ]
    model = skppy.Model.new()
    material = model.add_material("Layered")
    model.attribute_dictionaries_by_object_id[material.id] = _dictionaries("/Material", plugins)

    apply_vray_materials(model)

    assert (material.metallic, material.roughness) == pytest.approx((1.0, 0.15))


def test_uses_one_unambiguous_direct_brdf_and_ignores_ambiguous_graphs() -> None:
    direct = _plugin(
        "/Only",
        "BRDFVRayMtl",
        {"metalness": "nan", "option_use_roughness": "0", "reflect_glossiness": "bad"},
        {"metalness_float": "bad", "reflect_glossiness_float": "bad"},
    )
    material = skppy.Material(metallic=0.25, roughness=0.4)

    assert apply_vray_attribute_dictionaries(material, _dictionaries("/Missing", [direct]))
    assert (material.metallic, material.roughness) == pytest.approx((0.25, 0.4))

    ambiguous = [direct, _plugin("/Other", "BRDFVRayMtl", {})]
    assert not apply_vray_attribute_dictionaries(material, _dictionaries("/Missing", ambiguous))
    assert not apply_vray_attribute_dictionaries(material, [])


def test_ignores_cyclic_unknown_and_malformed_vray_values() -> None:
    cyclic = [_plugin("/Cycle", "MtlSingleBRDF", {"brdf": "/Cycle"})]
    unknown = [_plugin("/Unknown", "Unsupported", {})]
    malformed_color = [
        _plugin(
            "/BRDF",
            "BRDFVRayMtl",
            {"diffuse": "Color(red,0,0)", "metalness": "0", "reflect_glossiness": "1"},
        ),
    ]
    material = skppy.Material(color=skppy.Color(1, 2, 3))

    assert not apply_vray_attribute_dictionaries(material, _dictionaries("/Cycle", cyclic))
    assert not apply_vray_attribute_dictionaries(material, _dictionaries("/Unknown", unknown))
    assert apply_vray_attribute_dictionaries(material, _dictionaries("", malformed_color))
    assert material.color == skppy.Color(1, 2, 3)


def test_applies_namespaced_vray_material_xml() -> None:
    root = ET.fromstring(
        """
        <material xmlns:n0="http://sketchup.google.com/schemas/1.0/types">
          <n0:AttributeDictionaries>
            <n0:AttributeDictionary name="Ignored"><n0:Attribute key="x">1</n0:Attribute></n0:AttributeDictionary>
            <n0:AttributeDictionary name="VRayInfo">
              <n0:Attribute key="main_plugin">/M</n0:Attribute>
            </n0:AttributeDictionary>
            <n0:AttributeDictionary name="VRayPlugins">
              <n0:Attribute key="/M">\ufeff{"name":"/M","class":"MtlSingleBRDF","params":{"brdf":"/B"}}</n0:Attribute>
              <n0:Attribute key="/B">{"name":"/B","class":"BRDFVRayMtl","params":{"metalness":"0.8","option_use_roughness":"1","reflect_glossiness":"0.25"}}</n0:Attribute>
            </n0:AttributeDictionary>
          </n0:AttributeDictionaries>
        </material>
        """,
    )
    material = skppy.Material()

    assert apply_vray_xml(material, root)
    assert (material.metallic, material.roughness) == pytest.approx((0.8, 0.25))


def test_modern_material_import_prefers_sketchup_unless_vray_is_enabled() -> None:
    xml = b"""<materialDocument>
      <material colorRed="10" colorGreen="20" colorBlue="30" hasTexture="0">
        <pbrMR metallicFactor="0.2" roughnessFactor="0.7" />
        <AttributeDictionaries>
          <AttributeDictionary name="VRayInfo">
            <Attribute key="main_plugin">/M</Attribute>
          </AttributeDictionary>
          <AttributeDictionary name="VRayPlugins">
            <Attribute key="/M">
              {"name":"/M","class":"MtlSingleBRDF","params":{"brdf":"/B"}}
            </Attribute>
            <Attribute key="/B">
              {"name":"/B","class":"BRDFVRayMtl","params":{
                "metalness":"0.8","option_use_roughness":"1","reflect_glossiness":"0.25"
              }}
            </Attribute>
          </AttributeDictionary>
        </AttributeDictionaries>
      </material>
    </materialDocument>"""
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w"):
        pass
    archive_bytes.seek(0)

    with zipfile.ZipFile(archive_bytes) as archive:
        sketchup = _parse_material_xml(xml, "Paint", archive)
        vray = _parse_material_xml(xml, "Paint", archive, import_vray_materials=True)

    assert (sketchup.metallic, sketchup.roughness) == pytest.approx((0.2, 0.7))
    assert sketchup.color == skppy.Color(10, 20, 30)
    assert (vray.metallic, vray.roughness) == pytest.approx((0.8, 0.25))


def test_legacy_material_import_applies_vray_only_when_enabled(monkeypatch) -> None:
    applied_to = []
    monkeypatch.setattr(
        "skppy.parser_legacy.parser.apply_renderer_materials", lambda model, **kwargs: applied_to.append(model)
    )

    sketchup = parse_legacy_bytes(legacy_v8_bytes())
    vray = parse_legacy_bytes(legacy_v8_bytes(), import_vray_materials=True)

    assert applied_to == [vray]
    assert sketchup is not vray


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("List(/A, /B)", ["/A", "/B"]),
        ("List()", []),
        ("not a list", []),
        (None, []),
    ],
)
def test_parses_vray_reference_lists(value: object, expected: list[str]) -> None:
    assert _list_references(value) == expected
