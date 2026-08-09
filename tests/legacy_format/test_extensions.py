# SPDX-License-Identifier: MIT
"""Direct decoding tests for skppy metadata stored in legacy attributes."""

import json

import pytest

import skppy
from skppy.data_structure.model_metadata import SunData
from skppy.parser_legacy.attribute_builder import attribute_dictionaries_for_container_index
from skppy.parser_legacy.extensions import apply_legacy_extensions


def _install(model: skppy.Model, payload: object) -> None:
    model.attribute_dictionaries.append(
        skppy.AttributeDictionary(
            name="SkppyLegacyExtensions",
            entries=[
                skppy.AttributeDictionaryEntry(
                    key="PayloadV1",
                    value_type=3,
                    string_value=json.dumps(payload, separators=(",", ":")),
                ),
            ],
        ),
    )


def test_applies_all_supported_extension_sections() -> None:
    model = skppy.Model.new()
    material = model.add_material("Steel")
    layer = model.add_layer("Walls")
    layer.material = skppy.Material(name="Display")
    model.model_view_axes = skppy.ModelViewAxes()
    model.cameras = [skppy.Camera()]
    model.rendering_options = skppy.RenderingOptions()
    model.scenes = [skppy.Scene(1, "View", flags=1, camera=skppy.Camera())]
    model.styles_registry = skppy.StylesRegistry(
        styles=[skppy.StyleDescriptor(file_name="Style")],
        active_style_ref=1,
    )
    _install(
        model,
        {
            "line_styles": [
                {
                    "name": "Custom",
                    "dash_pattern": "3,-2",
                    "stipple_scale": 2.0,
                    "line_width_points": 1.5,
                    "color": 0x11223344,
                    "mutability": False,
                },
            ],
            "layer_folders": [
                {
                    "name": "Parent",
                    "visible": False,
                    "layers": ["Walls"],
                    "children": [{"name": "Child", "layers": [], "children": []}],
                },
            ],
            "material_pbr": {"Steel": [0.8, 0.2]},
            "layer_material_pbr": {"Walls": [0.3, 0.4]},
            "environment": {
                "selected": 7,
                "entries": [
                    {
                        "id": 7,
                        "name": "Studio",
                        "thumbnail_path": "thumb.jpg",
                        "image_filename": "studio.hdr",
                        "image_data": "SERS",
                        "thumbnail_data": "VEhVTUI=",
                        "description": "Test",
                        "use_as_skydome": True,
                        "use_for_reflections": True,
                        "rotation": 45.0,
                        "skydome_exposure": 2.0,
                        "reflection_exposure": 3.0,
                    },
                ],
            },
            "sun": "cmF3",
            "axes_flags": 9,
            "camera_allow_clipping": False,
            "scenes": {"View": {"allow_clipping": False, "raw_payload": "c2NlbmU="}},
            "rendering": {"ambient_occlusion": True, "ao_distance": 4},
            "styles": {"1": {"display_name": "Display", "xml_data": "PHgvPg=="}},
        },
    )

    apply_legacy_extensions(model)

    assert model.line_styles == [
        skppy.LineStyle("Custom", "3,-2", 2.0, 1.5, 0x11223344, False),
    ]
    assert model.layer_folders[0].child_layer_ids == [layer.id]
    assert model.layer_folders[0].child_folders[0].name == "Child"
    assert (material.metallic, material.roughness) == (0.8, 0.2)
    assert layer.material is not None
    assert (layer.material.metallic, layer.material.roughness) == (0.3, 0.4)
    assert model.environment_data is not None
    assert model.environment_data.selected is model.environment_data.entries[0]
    assert model.environment_data.selected.image_data == b"HDR"
    assert model.environment_data.selected.thumbnail_data == b"THUMB"
    assert model.sun_data == SunData(b"raw")
    assert model.model_view_axes.flags == 9
    assert model.cameras[0].allow_clipping is False
    assert model.scenes[0].camera is not None
    assert model.scenes[0].camera.allow_clipping is False
    assert model.scenes[0].raw_payload == b"scene"
    assert model.rendering_options.ambient_occlusion is True
    assert model.rendering_options.ao_distance == 4
    assert model.styles_registry.styles[0].display_name == "Display"
    assert model.styles_registry.styles[0].xml_data == b"<x/>"
    assert all(dictionary.name != "SkppyLegacyExtensions" for dictionary in model.attribute_dictionaries)


def test_ignores_absent_extension_dictionary() -> None:
    model = skppy.Model.new()

    apply_legacy_extensions(model)

    assert model.attribute_dictionaries == []
    assert attribute_dictionaries_for_container_index(None, {}) == []


def test_ignores_optional_extension_targets_that_are_not_in_the_model() -> None:
    model = skppy.Model.new()
    _install(
        model,
        {
            "material_pbr": {"Missing": [0.1, 0.2]},
            "layer_material_pbr": {"Missing": [0.3, 0.4]},
            "scenes": {"Missing": {"raw_payload": "cmF3"}},
            "rendering": {},
            "styles": {},
        },
    )

    apply_legacy_extensions(model)

    assert model.materials == []
    assert model.scenes == []


def test_applies_inline_style_extension() -> None:
    inline = skppy.StyleDescriptor(file_name="Inline")
    model = skppy.Model.new()
    model.styles_registry = skppy.StylesRegistry(
        styles=[skppy.StyleDescriptor(file_name="Main")],
        active_style_ref=1,
        inline_style_override=inline,
    )
    _install(model, {"styles": {"2": {"display_name": "Override", "xml_data": None}}})

    apply_legacy_extensions(model)

    assert inline.display_name == "Override"
    assert inline.xml_data is None


def test_applies_definition_entity_and_shadow_extensions() -> None:
    model = skppy.Model.new()
    start = model.entities.add_vertex(0, 0, 0)
    end = model.entities.add_vertex(1, 0, 0)
    edge = model.entities.add_edge(start, end)
    edge.curve_id = 10
    model.entities.curves = [skppy.Curve(id=10, edge_ids=[edge.id])]
    model.entities.section_planes = [skppy.SectionPlane(id=20)]
    definition = model.add_definition("Packed")
    model.shadow_info = skppy.ShadowInfo()
    _install(
        model,
        {
            "definitions": {"Packed": {"packed_payload": "YmxvYg=="}, "Missing": {}},
            "entity_scopes": {
                "root": {
                    "raw_arcs": [{"edges": [0], "payload": ""}],
                    "sections": {"0": {"name": "Cut", "symbol": "A"}},
                },
                "definitions": {"Packed": {}, "Missing": {}},
            },
            "shadow_edges_cast_shadows": True,
        },
    )

    apply_legacy_extensions(model)

    assert definition.packed_payload == b"blob"
    assert model.entities.curves == []
    assert model.entities.arc_curves == [skppy.ArcCurve(id=10, edge_ids=[edge.id], raw_arc_payload=b"")]
    assert (model.entities.section_planes[0].name, model.entities.section_planes[0].symbol) == ("Cut", "A")
    assert model.shadow_info.edges_cast_shadows is True


@pytest.mark.parametrize(
    ("dictionaries", "message"),
    [
        (
            [
                skppy.AttributeDictionary(name="SkppyLegacyExtensions"),
                skppy.AttributeDictionary(name="SkppyLegacyExtensions"),
            ],
            "duplicate",
        ),
        ([skppy.AttributeDictionary(name="SkppyLegacyExtensions")], "invalid payload entry"),
        (
            [
                skppy.AttributeDictionary(
                    name="SkppyLegacyExtensions",
                    entries=[
                        skppy.AttributeDictionaryEntry(
                            key="PayloadV1",
                            value_type=3,
                            string_value="not json",
                        ),
                    ],
                ),
            ],
            "not valid JSON",
        ),
        (
            [
                skppy.AttributeDictionary(
                    name="SkppyLegacyExtensions",
                    entries=[
                        skppy.AttributeDictionaryEntry(
                            key="PayloadV1",
                            value_type=3,
                            string_value="[]",
                        ),
                    ],
                ),
            ],
            "must be an object",
        ),
    ],
)
def test_rejects_invalid_extension_containers(
    dictionaries: list[skppy.AttributeDictionary],
    message: str,
) -> None:
    model = skppy.Model.new()
    model.attribute_dictionaries = dictionaries

    with pytest.raises(ValueError, match=message):
        apply_legacy_extensions(model)


@pytest.mark.parametrize(
    ("payload", "prepare", "message"),
    [
        ({"line_styles": {}}, lambda model: None, "must be an array"),
        ({"line_styles": [0]}, lambda model: None, "line style must be an object"),
        (
            {"layer_folders": [{"layers": ["Missing"]}]},
            lambda model: None,
            "references missing layer",
        ),
        ({"material_pbr": {"Steel": [1]}}, lambda model: model.add_material("Steel"), "two values"),
        ({"material_pbr": []}, lambda model: None, "PBR map must be an object"),
        ({"environment": {"selected": 1, "entries": []}}, lambda model: None, "missing selected"),
        ({"environment": {"selected": "one", "entries": []}}, lambda model: None, "must be an integer"),
        (
            {"environment": {"selected": 1, "entries": [{"id": 1, "image_data": None}]}},
            lambda model: None,
            "environment image is required",
        ),
        ({"sun": 7}, lambda model: None, "must be base64 text"),
        ({"sun": "***"}, lambda model: None, "not valid base64"),
        (
            {"rendering": {"unknown": True}},
            lambda model: setattr(model, "rendering_options", skppy.RenderingOptions()),
            "Unknown legacy skppy rendering",
        ),
        (
            {"styles": {"2": {}}},
            lambda model: setattr(
                model,
                "styles_registry",
                skppy.StylesRegistry(styles=[skppy.StyleDescriptor(file_name="One")], active_style_ref=1),
            ),
            "index is out of range",
        ),
        ({"definitions": []}, lambda model: None, "definition extensions must be an object"),
        (
            {"definitions": {"Packed": []}},
            lambda model: model.add_definition("Packed"),
            "definition extension must be an object",
        ),
        ({"entity_scopes": []}, lambda model: None, "entity-scope extensions must be an object"),
        (
            {"entity_scopes": {"root": {"raw_arcs": [{"edges": [1], "payload": ""}]}}},
            lambda model: model.entities.edges.append(skppy.Edge(id=1, start_vertex_id=2, end_vertex_id=3)),
            "raw arc edge position is out of range",
        ),
        (
            {"entity_scopes": {"root": {"raw_arcs": [{"edges": [0], "payload": ""}]}}},
            lambda model: model.entities.edges.append(skppy.Edge(id=1, start_vertex_id=2, end_vertex_id=3)),
            "raw arc has no matching curve",
        ),
        (
            {"entity_scopes": {"root": {"raw_arcs": [{"edges": [0]}]}}},
            lambda model: (
                model.entities.edges.append(skppy.Edge(id=1, start_vertex_id=2, end_vertex_id=3)),
                model.entities.curves.append(skppy.Curve(id=2, edge_ids=[1])),
            ),
            "raw arc payload is required",
        ),
        (
            {"entity_scopes": {"root": {"sections": {"0": {}}}}},
            lambda model: None,
            "section extension index is out of range",
        ),
    ],
)
def test_rejects_invalid_extension_sections(payload: object, prepare: object, message: str) -> None:
    model = skppy.Model.new()
    prepare(model)
    _install(model, payload)

    with pytest.raises(ValueError, match=message):
        apply_legacy_extensions(model)
