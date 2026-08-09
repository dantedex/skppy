# SPDX-License-Identifier: MIT
import pytest

import skppy
from skppy.data_structure.construction import GuideLine, GuidePoint, SectionPlane
from skppy.data_structure.entities import (
    ArcCurve,
    Curve,
    Edge,
    EdgeUse,
    Entities,
    Face,
    Loop,
    Vertex,
)
from skppy.data_structure.primitives import Vector3D


def test_model_builders_create_layers_materials_definitions_groups_and_scene():
    model = skppy.new_model()

    layer = model.add_layer("Walls", visible=False)
    material = model.add_material(
        "Brick",
        color=skppy.Color(180, 80, 60),
        alpha=0.75,
        metallic=0.1,
        roughness=0.8,
    )
    definition = model.add_definition("Panel", description="A test panel")
    face = definition.entities.add_face(
        [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)],
        material_id=material.id,
    )
    instance = model.entities.add_instance(
        definition,
        transform=skppy.Transform.from_translation(10.0, 0.0, 0.0),
        name="Panel A",
    )
    group_definition, group = model.add_group("Standalone")

    assert model.get_layer("Walls") is layer
    assert model.get_layer("Missing") is None
    assert model.get_material("Brick") is material
    assert model.get_material("Missing") is None
    assert model.get_definition("Panel") is definition
    assert model.get_definition("Missing") is None
    assert face.front_material_id == material.id
    assert instance.definition_id == definition.id
    assert group.definition_id == group_definition.id

    scene = model.to_scene()

    assert scene.name == "Scene"
    assert [child.name for child in scene.children] == ["Panel A", "Standalone"]
    assert scene.children[0].mesh is not None
    assert scene.children[0].mesh.faces[0].material_name == "Brick"


def test_model_to_scene_rejects_recursive_component_definitions() -> None:
    """Report malformed definition cycles instead of exhausting recursion."""
    model = skppy.new_model()
    first = model.add_definition("First")
    second = model.add_definition("Second")
    first.entities.add_instance(second)
    second.entities.add_instance(first)
    model.entities.add_instance(first)

    with pytest.raises(skppy.ComponentCycleError, match=r"1 -> 2 -> 1"):
        model.to_scene()


def test_model_to_scene_allows_repeated_non_recursive_instances() -> None:
    """Cycle detection is path-local and does not deduplicate valid instances."""
    model = skppy.new_model()
    definition = model.add_definition("Repeated")
    model.entities.add_instance(definition, name="One")
    model.entities.add_instance(definition, name="Two")

    assert [node.name for node in model.to_scene().children] == ["One", "Two"]


def test_model_root_geometry_and_persistence(tmp_path):
    model = skppy.new_model()
    model.entities.vertices = [
        Vertex(1, Vector3D(0.0, 0.0, 0.0)),
        Vertex(2, Vector3D(1.0, 0.0, 0.0)),
        Vertex(3, Vector3D(0.0, 1.0, 0.0)),
    ]
    model.entities.edges = [Edge(10, 1, 2), Edge(11, 2, 3), Edge(12, 3, 1)]
    model.entities.faces = [
        Face(
            id=100,
            plane=(0.0, 0.0, 1.0, 0.0),
            outer_loop=Loop([EdgeUse(10, False), EdgeUse(11, False), EdgeUse(12, False)]),
            inner_loops=[],
        )
    ]

    scene = model.to_scene()
    assert scene.children[0].name == "RootGeometry"
    assert scene.children[0].mesh is not None

    with pytest.raises(RuntimeError, match=r"loaded from a \.skp"):
        model.dump_zip("unused")

    output = tmp_path / "output.skp"
    assert model.save(output) == output
    assert len(skppy.load(output).entities.faces) == 1


def test_entities_sync_id_counter_includes_all_id_bearing_entities():
    """Allocate after curves and construction geometry without ID collisions."""
    entities = Entities(
        curves=[Curve(id=40, edge_ids=[])],
        arc_curves=[ArcCurve(id=50, edge_ids=[])],
        guide_points=[GuidePoint(id=60, position=(0.0, 0.0, 0.0))],
        guide_lines=[
            GuideLine(
                id=70,
                point=(0.0, 0.0, 0.0),
                direction=(1.0, 0.0, 0.0),
            )
        ],
        section_planes=[SectionPlane(id=80, plane=(0.0, 0.0, 1.0, 0.0))],
    )

    entities._sync_id_counter()

    assert entities.add_vertex(0.0, 0.0, 0.0).id == 81


def test_public_package_exports_parsed_entity_types():
    """Expose types returned by load() for normal isinstance checks."""
    for name in (
        "ArcCurve",
        "Curve",
        "FaceUVProjection",
        "GuideLine",
        "GuidePoint",
        "Scene",
        "SectionPlane",
        "ShadowInfo",
    ):
        assert name in skppy.__all__
        assert getattr(skppy, name) is not None


def test_camera_defaults_use_independent_vectors():
    """Allow incremental readers to populate cameras without shared state."""
    first = skppy.Camera()
    second = skppy.Camera()

    first.eye.x = 10.0

    assert first.eye.to_tuple() == (10.0, 0.0, 0.0)
    assert second.eye.to_tuple() == (0.0, 0.0, 0.0)


def test_incremental_data_structure_defaults_are_independent():
    """Keep mutable defaults isolated for version-aware legacy readers."""
    first_instance = skppy.ComponentInstance()
    second_instance = skppy.ComponentInstance()
    first_instance.transform[9] = 5.0

    first_definition = skppy.ComponentDefinition()
    second_definition = skppy.ComponentDefinition()
    first_definition.entities.add_vertex(1.0, 2.0, 3.0)

    first_uv = skppy.FaceUVProjection()
    second_uv = skppy.FaceUVProjection()
    first_uv.transform[0] = 2.0

    assert second_instance.transform[9] == 0.0
    assert not second_definition.entities.vertices
    assert second_uv.transform[0] == 1.0


def test_add_face_rejects_incomplete_polygon():
    """Reject a face before allocating partial vertices or edges."""
    entities = Entities()

    with pytest.raises(ValueError, match="at least 3"):
        entities.add_face([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])

    assert not entities.vertices
    assert not entities.edges
