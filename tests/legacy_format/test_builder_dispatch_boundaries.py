# SPDX-License-Identifier: MIT
"""Legacy builder, component adapter, and object-dispatch boundaries."""

from __future__ import annotations

import io
import struct
from types import SimpleNamespace
from typing import Any, cast

import pytest

from skppy.data_structure.entities import (
    ArcCurve,
    ComponentDefinition,
    ComponentInstance,
    Edge,
    Entities,
    Group,
)
from skppy.data_structure.layers import Layer, LayerFolder
from skppy.data_structure.materials import Material
from skppy.data_structure.model import Model
from skppy.data_structure.model_metadata import LineStyle
from skppy.parser_legacy.annotation_readers import (
    read_dimension,
    read_dimension_linear,
    read_text,
)
from skppy.parser_legacy.attribute_readers import read_attribute
from skppy.parser_legacy.binary import (
    ArchiveIndexEntry,
    ArchiveObjectHandle,
    ArchiveObjectTag,
    LegacyArchiveReader,
)
from skppy.parser_legacy.component_builder import populate_definitions
from skppy.parser_legacy.component_body import _is_relationship
from skppy.parser_legacy.component_payloads import read_definition_list_payload
from skppy.parser_legacy.component_readers import read_component_definition
from skppy.parser_legacy.entity_builder import (
    _add_curves,
    _add_instance,
    _entity_ids_by_archive_index,
)
from skppy.parser_legacy.errors import UnsupportedLegacyObjectError
from skppy.parser_legacy.material_builder import (
    collect_materials,
    material_ids_by_archive_index,
    populate_layers,
    populate_materials,
)
from skppy.parser_legacy.model_builder import ModelBuilder
from skppy.parser_legacy.object_dispatch import (
    _read_supported_object_from_handle,
    resolve_supported_object,
)
from skppy.parser_legacy.object_readers import ObjectReaderBinding, ReaderCall
from skppy.parser_legacy.parser_types import (
    ComponentDefinitionState,
    LayerState,
    MaterialState,
)
from skppy.parser_legacy.provenance import ArchiveProvenance


def _tag(kind: str = "object_ref", index: int | None = 1) -> ArchiveObjectTag:
    return ArchiveObjectTag(cast(Any, kind), index or 0, index=index)


def _handle(
    kind: str,
    *,
    index: int | None = None,
    class_name: str | None = None,
) -> ArchiveObjectHandle:
    return ArchiveObjectHandle(
        cast(Any, kind),
        _tag("object_ref" if kind == "object_ref" else "null", index),
        index,
        None,
        class_name,
        None,
    )


def _definition_state(index: int, guid: bytes) -> ComponentDefinitionState:
    return ComponentDefinitionState(
        object_tag=_tag("new_class"),
        object_index=index,
        definition=ComponentDefinition(guid=guid),
        entity_payloads=(),
    )


def _material_state(name: str) -> MaterialState:
    return MaterialState(
        class_version=4,
        payload_start_offset=0,
        entity_header=cast(Any, None),
        material=Material(name=name),
        used_by_layer=None,
        color=None,
        string_90=None,
        material_type=None,
        colorize_type=None,
        transparency=None,
        use_transparency=None,
        payload_end_offset=0,
    )


def test_component_builder_reuses_duplicate_indices_and_guids() -> None:
    first = _definition_state(7, b"a" * 16)
    duplicate_index = _definition_state(7, b"b" * 16)
    duplicate_guid = _definition_state(8, b"a" * 16)
    provenance = ArchiveProvenance(
        archive_objects=((7, first),),
        root_objects=(first, duplicate_index, duplicate_guid),
    )
    model = Model(legacy_archive=provenance)

    definitions = populate_definitions(
        model,
        provenance,
        material_id_by_object_index={},
        archive_indices_by_identity={},
        objects_by_archive_index={},
    )

    assert model.definitions == [first.definition]
    assert definitions == {7: first.definition, 8: first.definition}


def test_component_definition_reader_guards_and_complete_adapter(monkeypatch) -> None:
    context = SimpleNamespace()
    with pytest.raises(NotImplementedError, match="CComponent version 11"):
        read_component_definition(
            cast(Any, context),
            object_tag=_tag(),
            object_index=1,
            component_class_version=10,
            class_version=10,
        )
    with pytest.raises(NotImplementedError, match="CComponentDefinition"):
        read_component_definition(
            cast(Any, context),
            object_tag=_tag(),
            object_index=1,
            component_class_version=11,
            class_version=9,
        )

    strings = iter(("Definition", "Description", "component.skp"))
    integers = iter((123, 2))
    reader = SimpleNamespace(
        read_exact=lambda size, label: b"g" * size,
        read_legacy_utf16_string=lambda label: next(strings),
        read_u32=lambda: next(integers),
        read_bool=lambda: True,
        read_vec3_f64=lambda: (0.0, 0.0, 0.0),
        tell=lambda: 17,
    )
    context = SimpleNamespace(
        session=SimpleNamespace(reader=reader),
        class_versions={"CComponentBehavior": 5},
        read_entity=lambda: object(),
        read_object=lambda: (_tag("null", 0), b"thumbnail"),
    )
    component = SimpleNamespace(entities=(object(),), materials=None, relationships=())
    behavior = SimpleNamespace(
        snap_to=2,
        no_scale_mask=3,
        is_2d=False,
        cuts_opening=True,
        always_face_camera=True,
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.component_readers.read_component_body",
        lambda unused: component,
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.component_readers.read_component_behavior_body",
        lambda *args, **kwargs: behavior,
    )

    state = read_component_definition(
        cast(Any, context),
        object_tag=_tag("new_class"),
        object_index=9,
        component_class_version=11,
        class_version=10,
    )

    assert state.object_index == 9
    assert state.entity_payloads == component.entities
    assert state.definition.name == "Definition"
    assert state.definition.description == "Description"
    assert state.definition.loaded_from == "component.skp"
    assert state.definition.timestamp == 123
    assert state.definition.modified is True
    assert state.definition.definition_type == 2
    assert state.definition.packed_payload == b"thumbnail"
    assert state.definition.behavior_snap_enabled is True
    assert state.definition.behavior_no_scale_mask == 3


def test_definition_list_resolves_inline_objects() -> None:
    handles = iter(
        (
            _handle("new_object", index=2, class_name="CComponentDefinition"),
            _handle("object_ref", index=2),
        )
    )
    resolved: list[ArchiveObjectHandle] = []
    session = SimpleNamespace(
        tell=lambda: 4,
        reader=LegacyArchiveReader(io.BytesIO(struct.pack("<I", 2))),
        read_object_handle=lambda: next(handles),
    )

    tags, start, end = read_definition_list_payload(cast(Any, session), class_version=0, resolve=resolved.append)

    assert len(tags) == 2
    assert (start, end) == (4, 4)
    assert len(resolved) == 1
    assert resolved[0].kind == "new_object"


def test_annotation_and_attribute_readers_reject_unknown_versions() -> None:
    context = cast(Any, SimpleNamespace())
    for reader, version in (
        (read_dimension, 2),
        (read_dimension_linear, 5),
        (read_text, 8),
        (read_attribute, 1),
    ):
        with pytest.raises(NotImplementedError):
            reader(context, class_version=version)

    dimension = read_dimension(
        cast(
            Any,
            SimpleNamespace(
                session=SimpleNamespace(reader=SimpleNamespace(read_legacy_utf16_string=lambda label: "Distance")),
                read_drawing_element=lambda: object(),
            ),
        ),
        class_version=0,
    )
    assert dimension.text == "Distance"
    assert dimension.font is None


def test_relationship_shape_and_reader_binding_terminal_layouts() -> None:
    relationship = (_tag(index=1), _tag(index=2))
    assert _is_relationship(relationship) is True
    assert _is_relationship((relationship[0], object())) is False

    calls: list[tuple[object, dict[str, object]]] = []

    def reader(context: object, **kwargs: object) -> object:
        calls.append((context, kwargs))
        return object()

    context = SimpleNamespace(
        class_versions={"CComponentDefinition": 10, "CComponent": 11},
        session=SimpleNamespace(),
    )
    handle = _handle("new_object", index=5, class_name="CComponentDefinition")
    binding = ObjectReaderBinding(reader, ReaderCall.COMPONENT_DEFINITION)
    assert binding(cast(Any, context), handle) is not None
    assert calls[0][1] == {
        "object_tag": handle.tag,
        "object_index": 5,
        "component_class_version": 11,
        "class_version": 10,
    }

    invalid = ObjectReaderBinding(reader, cast(Any, object()))
    with pytest.raises(AssertionError, match="Unhandled reader call layout"):
        invalid(cast(Any, context), handle)


def test_model_builder_resolves_pending_references_and_boundary_paths() -> None:
    builder = ModelBuilder(cast(Any, None), None)
    assigned: list[object] = []
    builder.reference(7, assigned.append)
    builder.reference(8, assigned.append)
    value = object()
    builder.register(7, value)
    builder.reference(7, assigned.append)

    assert assigned == [value, value]
    assert builder.register_archive_value(object(), object()) is None
    with pytest.raises(ValueError, match=r"\[8\]"):
        builder.finalize()


def test_model_builder_collection_defaults_and_deduplication() -> None:
    builder = ModelBuilder(cast(Any, None), None)
    builder.add_styles(())
    assert builder.model.styles_registry is None

    from skppy.data_structure.model_metadata import StyleDescriptor

    style = StyleDescriptor(display_name="Default")
    builder.add_styles((style, style))
    assert builder.model.styles_registry is not None
    assert builder.model.styles_registry.styles == [style]

    line = LineStyle(name="Custom")
    builder.add_line_styles((line, line))
    assert builder.model.line_styles == [line]

    builder.apply_legacy_defaults(has_post_rendering_data=False)
    assert builder.model.environment_data is None
    builder.apply_legacy_defaults(has_post_rendering_data=True)
    assert builder.model.environment_data is not None
    assert builder.model.line_styles == [line]


def test_material_and_layer_builders_cover_duplicates_and_recovery() -> None:
    direct = _material_state("Direct")
    recovered = _material_state("Recovered")
    provenance = ArchiveProvenance(
        root_component_materials=(direct,),
        root_objects=(direct, (recovered, "ignored")),
        archive_objects=((1, direct),),
        archive_index_entries=(
            ArchiveIndexEntry(1, "object", "CMaterial", 4),
            ArchiveIndexEntry(2, "object", "CMaterial", 4),
        ),
    )
    materials = collect_materials(provenance)
    model = Model()
    populate_materials(model, materials)
    populate_materials(model, materials)

    assert [material.name for material in model.materials] == ["Direct", "Recovered"]
    assert material_ids_by_archive_index(model, provenance, materials) == {
        1: model.materials[0].id,
        2: model.materials[1].id,
    }

    layer = Layer(name="Layer")
    nested = LayerFolder(name="nested", child_layer_ids=[3, 99])
    folder = LayerFolder(name="root", child_layer_ids=[3], child_folders=[nested])
    layer_state = LayerState(
        object_tag=_tag(index=3),
        payload_start_offset=0,
        entity_header=cast(Any, None),
        layer=layer,
        material=None,
        payload_end_offset=0,
    )
    layer_provenance = ArchiveProvenance(
        archived_layers=(layer_state,),
        active_layer_tag=_tag(index=3),
        layer_folders=(folder,),
    )
    populate_layers(model, layer_provenance)

    assert model.active_layer_id == layer.id
    assert folder.child_layer_ids == [layer.id]
    assert nested.child_layer_ids == [layer.id]


def test_entity_builder_private_conversion_boundaries() -> None:
    unresolved = ComponentInstance(id=0)
    assert (
        _entity_ids_by_archive_index(
            Entities(component_instances=[unresolved]),
            (),
            archive_indices_by_identity={id(unresolved): (4,)},
            converted_entity_ids={},
        )
        == {}
    )

    edge = Edge(id=1, start_vertex_id=1, end_vertex_id=2)
    entities = Entities(edges=[edge])
    arc = ArcCurve()
    _add_curves(entities, {7: arc}, {7: [1]})
    assert entities.arc_curves == [arc]
    assert edge.curve_id == arc.id

    _add_instance(entities, ComponentInstance(definition_id=99), {}, {}, {})
    assert entities.component_instances == []

    definition = ComponentDefinition(id=12)
    group = Group(definition_id=5, material_id=6, layer_id=7)
    _add_instance(entities, group, {5: definition}, {6: 16}, {7: 17})
    assert entities.groups == [group]
    assert (group.definition_id, group.material_id, group.layer_id) == (12, 16, 17)


def test_object_dispatch_reference_null_known_and_unknown_paths(monkeypatch) -> None:
    stored = object()
    objects = {3: stored}
    session = SimpleNamespace(
        objects=objects,
        file_version=None,
        reader=SimpleNamespace(tell=lambda: 44),
        tell=lambda: 44,
        store_object=lambda index, value: objects.__setitem__(index, value),
    )
    missing_reference = _handle("object_ref", index=2)
    anonymous_reference = _handle("object_ref", index=None)
    assert resolve_supported_object(cast(Any, session), missing_reference, {}) is missing_reference
    assert resolve_supported_object(cast(Any, session), anonymous_reference, {}) is anonymous_reference

    context = SimpleNamespace(current_object_index=99)
    assert (
        _read_supported_object_from_handle(cast(Any, session), missing_reference, {}, cast(Any, context))
        is missing_reference
    )
    assert (
        _read_supported_object_from_handle(cast(Any, session), anonymous_reference, {}, cast(Any, context))
        is anonymous_reference
    )
    null = _handle("null")
    assert _read_supported_object_from_handle(cast(Any, session), null, {}, cast(Any, context)) is null

    known = _handle("new_object", index=5, class_name="CTest")
    monkeypatch.setattr(
        "skppy.parser_legacy.object_dispatch.OBJECT_READERS",
        {
            "CTest": lambda read_context, handle: (
                read_context.current_object_index,
                handle.class_name,
            )
        },
    )
    assert resolve_supported_object(cast(Any, session), known, {}) == (5, "CTest")
    assert objects[5] == (5, "CTest")

    unknown = _handle("new_object", index=6, class_name="CUnknown")
    with pytest.raises(UnsupportedLegacyObjectError) as error:
        resolve_supported_object(cast(Any, session), unknown, {})
    assert error.value.class_name == "CUnknown"
