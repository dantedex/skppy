# SPDX-License-Identifier: MIT
"""Tests for modern model root and required default records."""

from __future__ import annotations

import struct
import math

import pytest

from skppy import (
    Camera,
    Color,
    LinearDimension,
    PageBackgroundImage,
    PointReference,
    Scene,
    Text,
)
from skppy.data_structure.entities import (
    ComponentInstance,
    Edge,
    EdgeUse,
    Face,
    Loop,
    Vertex,
)
from skppy.data_structure.model import Model
from skppy.data_structure.model_metadata import (
    AttributeDictionary,
    DimensionStyle,
    EnvironmentData,
    EnvironmentEntry,
    Font,
    LineStyle,
    OptionsManager,
    StyleDescriptor,
    StylesRegistry,
    TextStyle,
    Watermark,
    WatermarkManager,
)
from skppy.data_structure.primitives import Vector3D
from skppy.writer.fonts import encode_fonts
from skppy.writer.model_data import (
    _create_id_plan,
    _merge_entries,
    _point_reference_id_resolver,
    build_model_container,
    encode_model_data,
)


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    """Construct expected wire bytes without using writer primitives."""
    return struct.pack("<HI", tag, len(payload)) + payload


def _triangle_model() -> Model:
    model = Model.new()
    model.entities.vertices = [
        Vertex(1, Vector3D(0.0, 0.0, 0.0)),
        Vertex(2, Vector3D(1.0, 0.0, 0.0)),
        Vertex(3, Vector3D(0.0, 1.0, 0.0)),
    ]
    model.entities.edges = [Edge(4, 1, 2), Edge(5, 2, 3), Edge(6, 3, 1)]
    model.entities.faces = [
        Face(
            id=7,
            plane=(0.0, 0.0, 1.0, 0.0),
            outer_loop=Loop(
                [EdgeUse(4, False), EdgeUse(5, False), EdgeUse(6, False)],
                is_outer=True,
            ),
            inner_loops=[],
        )
    ]
    return model


def test_font_block_matches_independent_wire_representation() -> None:
    """Encode every scalar in a font record with its documented width."""
    identity = _raw_record(0x05DC, _raw_record(0x05DE, b"\x02"))
    font_payload = b"".join(
        (
            identity,
            _raw_record(0x5015, b"Arial"),  # Face name.
            _raw_record(0x5016, b"\x00"),  # Bold flag.
            _raw_record(0x5017, b"\x00"),  # Italic flag.
            _raw_record(0x5018, struct.pack("<I", 12)),  # Point size.
            _raw_record(0x5019, b"\x00"),  # Use-world-size flag.
            _raw_record(0x501A, struct.pack("<d", 1.0)),  # World size.
        )
    )
    font_list = _raw_record(0x4E21, _raw_record(0x5014, font_payload))
    expected = _raw_record(0x4E20, font_list)

    assert encode_fonts([Font("Arial", point_size=12, world_size=1.0)]) == expected


@pytest.mark.parametrize(
    ("font", "message"),
    [
        (Font("", point_size=12, world_size=1.0), "cannot be empty"),
        (Font("Arial", point_size=-1, world_size=1.0), "fit in u32"),
        (Font("Arial", point_size=12, world_size=-1.0), "non-negative"),
    ],
)
def test_font_block_rejects_unrepresentable_values(font: Font, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        encode_fonts([font])


def test_generated_triangle_root_matches_raw_remapped_records() -> None:
    """Check the generated root without using the modern parser as an oracle."""
    encoded = encode_model_data(_triangle_model())
    first_vertex = _raw_record(
        0x09C4,
        _raw_record(0x05DC, _raw_record(0x05DE, b"\x12")) + _raw_record(0x09C5, struct.pack("<3d", 0.0, 0.0, 0.0)),
    )
    first_edge = _raw_record(
        0x0BB8,
        _raw_record(
            0x07D0,
            _raw_record(0x05DC, _raw_record(0x05DE, b"\x15")) + _raw_record(0x07D3, b"\x06"),
        )
        + _raw_record(0x0BB9, b"\x12")
        + _raw_record(0x0BBA, b"\x13"),
    )
    assert _raw_record(0x5015, b"Arial") in encoded
    assert _raw_record(0x5015, b"Tahoma") in encoded
    assert first_vertex in encoded
    assert first_edge in encoded
    assert _raw_record(0x0DAD, struct.pack("<4d", 0.0, 0.0, 1.0, 0.0)) in encoded


def test_model_id_plan_groups_interleaved_curve_edges() -> None:
    """Give every curve a contiguous serialized edge range for the SDK."""
    model = Model.new()
    model.entities.add_arc_curve((0, 0, 0), (0, 0, 1), 2.0, 0.0, math.pi, 3)
    model.entities.add_arc_curve((10, 0, 0), (0, 0, 1), 3.0, 0.0, math.pi, 3)
    first = model.entities.edges[:3]
    second = model.entities.edges[3:]
    model.entities.edges = [edge for pair in zip(first, second) for edge in pair]
    encoded = encode_model_data(model)

    first_curve = _raw_record(
        0x4A38,
        _raw_record(0x05DC, _raw_record(0x05DE, b"\x20"))
        + _raw_record(0x4A39, struct.pack("<I", 3))
        + _raw_record(0x4A3A, b"\x00")
        + _raw_record(0x4A3B, b"\x1a")
        + _raw_record(0x4A3C, b"\x1c"),
    )
    second_curve = _raw_record(
        0x4A38,
        _raw_record(0x05DC, _raw_record(0x05DE, b"\x21"))
        + _raw_record(0x4A39, struct.pack("<I", 3))
        + _raw_record(0x4A3A, b"\x00")
        + _raw_record(0x4A3B, b"\x1d")
        + _raw_record(0x4A3C, b"\x1f"),
    )

    assert first_curve in encoded
    assert second_curve in encoded


def test_model_id_plan_maps_nested_point_reference_paths_to_raw_ids() -> None:
    model = Model.new()
    definition = model.add_definition("Dimension reference")
    start = definition.entities.add_vertex(0.0, 0.0, 0.0)
    end = definition.entities.add_vertex(4.0, 0.0, 0.0)
    edge = definition.entities.add_edge(start, end)
    instance = model.entities.add_instance(definition)
    model.entities.linear_dimensions.append(
        LinearDimension(
            id=instance.id + 1,
            start=PointReference(
                kind=5,
                position=Vector3D(0.25, 0.0, 0.0),
                entity_id=edge.id,
                instance_path_ids=[instance.id],
            ),
        )
    )

    encoded = encode_model_data(model)
    expected_style = _raw_record(
        0x53FC,
        _raw_record(0x53FD, b"\x15") + _raw_record(0x53FE, b"\x01\x16"),
    )

    assert _raw_record(0x520B, expected_style) in encoded


def test_model_annotation_font_object_maps_to_raw_font_reference() -> None:
    model = Model.new()
    model.fonts = [Font("Arial"), Font("Courier New")]
    model.entities.texts.append(Text(id=1, text="Font object", font=model.fonts[1]))

    encoded = encode_model_data(model)

    assert _raw_record(0x55F9, b"\x03") in encoded


def test_model_rejects_unregistered_annotation_font() -> None:
    model = Model.new()
    model.entities.texts.append(Text(id=1, font=Font("Unregistered")))

    with pytest.raises(ValueError, match="not registered"):
        encode_model_data(model)


def test_model_rejects_ambiguous_global_object_ids() -> None:
    model = Model.new()
    material = model.add_material("Shared ID")
    layer = model.add_layer("Shared ID")
    layer.id = material.id

    with pytest.raises(ValueError, match="globally unique"):
        encode_model_data(model)


def test_model_rejects_dangling_active_layer_and_scene_style() -> None:
    model = Model.new()
    model.active_layer_id = 99
    with pytest.raises(ValueError, match="Active layer"):
        encode_model_data(model)

    model.active_layer_id = None
    model.scenes.append(Scene(id=1, name="Dangling style", style_reference=1))
    with pytest.raises(ValueError, match="style reference"):
        encode_model_data(model)


def test_model_rejects_conflicting_scene_background_visibility() -> None:
    model = Model.new()
    image = PageBackgroundImage(
        id=1,
        path="writer.png",
        image_data=b"\x89PNG\r\n\x1a\nraw",
        width=1,
        height=1,
        visible=False,
    )
    model.scenes.append(
        Scene(
            id=1,
            name="Conflicting image",
            background_image=image,
            display_background_image=True,
        )
    )

    with pytest.raises(ValueError, match="display state"):
        encode_model_data(model)


def test_model_data_rejects_unsupported_top_level_data() -> None:
    """Do not silently omit model resources that lack an encoder."""
    model = Model.new()
    model.scenes.append(Scene(id=1, name="Opaque", raw_payload=b"opaque"))
    with pytest.raises(ValueError, match="not a valid TLV"):
        encode_model_data(model)


def test_extra_entries_cannot_replace_generated_model_data() -> None:
    """Keep the graph serializer authoritative over the core ZIP entry."""
    with pytest.raises(ValueError, match="cannot replace"):
        build_model_container(Model.new(), extra_entries={"model.dat": b"opaque"})


def test_model_root_emits_all_supported_optional_blocks() -> None:
    model = Model.new()
    model.cameras = [Camera(name="Current")]
    model.line_styles = [LineStyle(name="Writer", dash_pattern="1.0, -1.0", mutability=True)]
    model.text_style = TextStyle(font_ref=2, screen_font_ref=2)
    model.dimension_style = DimensionStyle(font_ref=2)
    model.options_manager = OptionsManager()
    environment = EnvironmentEntry(
        id=1,
        name="Studio",
        image_filename="studio.exr",
        image_data=b"environment",
    )
    model.environment_data = EnvironmentData(selected=environment)
    model.watermark_manager = WatermarkManager(
        watermarks=[Watermark(id=1, name="Overlay", image_data=b"\x89PNG\r\n\x1a\nraw")]
    )
    model.styles_registry = StylesRegistry(styles=[StyleDescriptor(file_name="Writer")], active_style_ref=1)
    model.background_image = PageBackgroundImage(
        id=1,
        path="photo.png",
        image_data=b"\x89PNG\r\n\x1a\nraw",
    )

    encoded = encode_model_data(model)

    for tag in (
        0x01FA,
        0x01FE,
        0x01FF,
        0x0200,
        0x0201,
        0x0202,
        0x0203,
        0x0206,
        0x0208,
        0x0210,
    ):
        assert struct.pack("<H", tag) in encoded
    assert _raw_record(0x4077, b"Writer") in encoded
    assert _raw_record(0x7B0D, b"Studio") in encoded
    assert _raw_record(0x2EE4, b"Overlay") in encoded


def test_generated_material_entries_reject_extra_entry_conflicts() -> None:
    model = Model.new()
    model.add_material("Paint", color=Color(1, 2, 3))
    with pytest.raises(ValueError, match="conflicts with generated entry"):
        build_model_container(
            model,
            extra_entries={"materials/Paint/material.xml": b"conflict"},
        )

    model = Model.new()
    model.add_layer("Walls")
    with pytest.raises(ValueError, match="Generated ZIP entries conflict"):
        build_model_container(
            model,
            extra_entries={"materials/Layer_Walls/material.xml": b"conflict"},
        )

    with pytest.raises(ValueError, match="Generated ZIP entries conflict"):
        _merge_entries({"same": b"first"}, {"same": b"second"})

    merged: dict[str, bytes] = {}
    _merge_entries(merged, {"new": b"payload"})
    assert merged == {"new": b"payload"}


def test_layer_resources_are_added_to_raw_model_container() -> None:
    model = Model.new()
    model.add_layer("Walls")
    encoded = build_model_container(model)

    assert encoded.startswith(b"\xff\xfe\xff")
    assert b"materials/Layer_Walls/material.xml" in encoded


def test_model_rejects_invalid_object_and_attribute_owner_ids() -> None:
    model = Model.new()
    material = model.add_material("Bad")
    material.id = 0
    with pytest.raises(ValueError, match="object IDs must be positive"):
        encode_model_data(model)

    model = Model.new()
    model.attribute_dictionaries_by_object_id[99] = [AttributeDictionary(name="Unsupported")]
    with pytest.raises(NotImplementedError, match="object IDs"):
        encode_model_data(model)


def test_model_rejects_invalid_annotation_font_ids_and_mismatches() -> None:
    model = Model.new()
    model.entities.texts.append(Text(id=1, font_id=99))
    with pytest.raises(ValueError, match="font_id does not identify"):
        encode_model_data(model)

    model = Model.new()
    model.fonts = [Font("Arial"), Font("Courier")]
    model.entities.texts.append(Text(id=1, font=model.fonts[0], font_id=3))
    with pytest.raises(ValueError, match="identify different fonts"):
        encode_model_data(model)


def test_scene_background_reference_resolves_before_visibility_validation() -> None:
    model = Model.new()
    model.background_image = PageBackgroundImage(
        id=7,
        path="photo.png",
        image_data=b"\x89PNG\r\n\x1a\nraw",
        visible=False,
    )
    model.scenes.append(
        Scene(
            id=1,
            name="Referenced",
            background_image_ref=7,
            display_background_image=True,
        )
    )
    with pytest.raises(ValueError, match="display state"):
        encode_model_data(model)


def test_point_reference_resolver_rejects_invalid_paths_and_leaf_ids() -> None:
    model = Model.new()
    vertex = model.entities.add_vertex(0.0, 0.0, 0.0)
    plan = _create_id_plan(model)

    with pytest.raises(ValueError, match="Unknown point-reference definition"):
        _point_reference_id_resolver(model, plan, definition_id=99)(vertex.id, ())

    resolver = _point_reference_id_resolver(model, plan)
    with pytest.raises(ValueError, match="path contains unknown entity"):
        resolver(vertex.id, (99,))
    with pytest.raises(ValueError, match="is not an instance"):
        resolver(vertex.id, (vertex.id,))
    with pytest.raises(ValueError, match="unknown leaf entity"):
        resolver(99, ())

    instance_model = Model.new()
    instance_model.entities.component_instances.append(ComponentInstance(id=1, definition_id=99))
    instance_plan = _create_id_plan(instance_model)
    with pytest.raises(ValueError, match="references unknown definition"):
        _point_reference_id_resolver(instance_model, instance_plan)(1, (1,))


def test_point_reference_resolver_maps_a_definition_leaf() -> None:
    model = Model.new()
    definition = model.add_definition("Leaf")
    vertex = definition.entities.add_vertex(0.0, 0.0, 0.0)
    plan = _create_id_plan(model)

    assert _point_reference_id_resolver(model, plan, definition_id=definition.id)(vertex.id, ()) == (
        plan.definition_entity_ids[definition.id][vertex.id],
        (),
    )
