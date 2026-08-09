# SPDX-License-Identifier: MIT
"""Definition and root-instance assembly into shared model classes."""

# ruff: noqa: F403, F405

from dataclasses import replace

from skppy.parser_legacy.entity_builder import index_archive_object_identities

from ._fixtures import *


def test_archive_provenance_supports_incremental_population() -> None:
    """Allow the once-per-file provenance record to follow parser progress."""
    provenance = ArchiveProvenance()

    provenance.product_name = "SketchUp Model"
    provenance.archive_offset = 128

    assert provenance.product_name == "SketchUp Model"
    assert provenance.archive_offset == 128
    assert provenance.root_objects == ()


def test_archive_identity_index_preserves_alias_indices() -> None:
    """Resolve every archive alias without rescanning the global object table."""
    shared = SectionPlane(id=4)

    assert index_archive_object_identities(((7, shared), (12, shared))) == {id(shared): (7, 12)}


def test_model_builder_normalizes_raw_style_archive_indices() -> None:
    style = StyleDescriptor(guid=bytes(16), file_name="Style")
    registry = StylesRegistry(styles=[style], active_style_ref=41)
    model = Model(
        scenes=[Scene(1, "View", flags=2, style_reference=41)],
        styles_registry=registry,
    )
    builder = ModelBuilder(model.header, ArchiveProvenance())
    builder.model = model

    builder.normalize_style_references(((41, style),))

    assert registry.active_style_ref == 1
    assert model.scenes[0].style_reference == 1

    builder.model.styles_registry = None
    builder.normalize_style_references(((41, style),))


def test_populate_supported_definitions_maps_geometry_and_instances() -> None:
    """Map component-definition previews into shared definitions and instances."""
    edge_preview = read_edge_preview(
        io.BytesIO(_edge_preview_bytes()),
        entity_class_version=3,
        edge_class_version=2,
    )
    target_definition = _component_definition_preview(
        object_index=7,
        guid=b"\x07" * 16,
        name="Target",
        entity_payloads=(edge_preview,),
    )
    instance_preview = ComponentInstance(
        id=0,
        guid=b"\x00" * 16,
        definition_id=7,
        transform=list(_component_instance_transform_values()),
        name="Placed",
    )
    placed_definition = _component_definition_preview(
        object_index=9,
        guid=b"\x09" * 16,
        name="PlacedDef",
        entity_payloads=(instance_preview,),
    )
    model = Model(
        legacy_archive=ArchiveProvenance(
            product_name="SketchUp Model",
            version_string="{8.0.1}",
            model_guid=bytes(range(16)),
            saved_path="",
            timestamp=0,
            version_map=(),
            archive_offset=0,
            root_objects=(target_definition, placed_definition),
        )
    )

    definitions = populate_definitions(model, model.legacy_archive)

    assert len(model.definitions) == 2
    assert model.definitions[0] is target_definition.definition
    assert model.definitions[1] is placed_definition.definition
    assert model.definitions[0].name == "Target"
    assert len(model.definitions[0].entities.edges) == 1
    assert model.definitions[0].behavior_always_face_camera is True
    assert model.definitions[0].behavior_cuts_opening is True
    assert model.definitions[0].behavior_snap_enabled is True
    assert model.definitions[0].behavior_snap_mode == 2
    instance = model.definitions[1].entities.component_instances[0]
    assert instance is instance_preview
    assert instance.name == "Placed"
    assert instance.definition_id == model.definitions[0].id
    assert definitions == {
        7: model.definitions[0],
        9: model.definitions[1],
    }
    assert not model.entities.component_instances


def test_root_builder_does_not_leak_component_definition_geometry() -> None:
    """Keep cached definition edges out of the model root entity collection."""
    edge = read_edge_preview(
        io.BytesIO(_edge_preview_bytes()),
        entity_class_version=3,
        edge_class_version=2,
    )
    definition = _component_definition_preview(
        object_index=7,
        guid=b"\x07" * 16,
        name="Nested",
        entity_payloads=(edge,),
    )
    provenance = ArchiveProvenance(
        product_name="SketchUp Model",
        version_string="{8.0.1}",
        model_guid=bytes(range(16)),
        saved_path="",
        timestamp=0,
        version_map=(),
        archive_offset=0,
        root_objects=(definition,),
        archive_objects=((8, edge),),
    )
    model = Model(legacy_archive=provenance)

    populate_root_entities(model, provenance)

    assert model.entities.vertices == []
    assert model.entities.edges == []


def test_root_builder_resolves_recursive_su3_curve_edge_reference() -> None:
    """Recover an edge that refers to a curve still being deserialized."""
    archived_edge = read_edge_preview(
        io.BytesIO(_edge_preview_bytes()),
        entity_class_version=3,
        edge_class_version=2,
    )
    archived_edge = replace(
        archived_edge,
        curve_tag=ArchiveObjectTag(kind="object_ref", raw_tag=11, index=11),
    )
    curve = Curve(id=0, edge_ids=[], is_polygon=False)
    provenance = ArchiveProvenance(
        product_name="SketchUp Model",
        version_string="{3.0.1}",
        model_guid=bytes(range(16)),
        saved_path="",
        timestamp=0,
        version_map=(),
        archive_offset=0,
        root_objects=(archived_edge,),
        archive_objects=((11, curve),),
    )
    model = Model(legacy_archive=provenance)

    populate_root_entities(model, provenance)

    assert len(model.entities.edges) == 1
    assert len(model.entities.curves) == 1
    assert model.entities.curves[0] is curve
    assert curve.edge_ids == [model.entities.edges[0].id]


def test_root_builder_maps_relationships_to_public_entity_ids() -> None:
    """Translate relationship archive tags after allocating entity IDs."""
    first_edge = read_edge_preview(
        io.BytesIO(_edge_preview_bytes()),
        entity_class_version=3,
        edge_class_version=2,
    )
    second_edge = read_edge_preview(
        io.BytesIO(_edge_preview_bytes()),
        entity_class_version=3,
        edge_class_version=2,
    )
    relationship = (
        ArchiveObjectTag("object_ref", 11, 11),
        ArchiveObjectTag("object_ref", 12, 12),
    )
    provenance = ArchiveProvenance(
        root_objects=(first_edge, second_edge),
        root_relationships=(relationship,),
        archive_objects=((11, first_edge), (12, second_edge)),
    )
    model = Model(legacy_archive=provenance)

    populate_root_entities(model, provenance)

    assert len(model.entities.relationships) == 1
    assert model.entities.relationships[0].source_id == model.entities.edges[0].id
    assert model.entities.relationships[0].target_id == model.entities.edges[1].id


def test_root_builder_preserves_unresolved_relationship_endpoint() -> None:
    """Represent dangling archive references without leaking archive indices."""
    edge = read_edge_preview(
        io.BytesIO(_edge_preview_bytes()),
        entity_class_version=3,
        edge_class_version=2,
    )
    relationship = (
        ArchiveObjectTag("object_ref", 11, 11),
        ArchiveObjectTag("object_ref", 99, 99),
    )
    provenance = ArchiveProvenance(
        root_objects=(edge,),
        root_relationships=(relationship,),
        archive_objects=((11, edge),),
    )
    model = Model(legacy_archive=provenance)

    populate_root_entities(model, provenance)

    public_relationship = model.entities.relationships[0]
    assert public_relationship.source_id == model.entities.edges[0].id
    assert public_relationship.target_id is None


def test_root_builder_attaches_entity_attribute_dictionaries() -> None:
    """Expose named dictionaries under their final owner ID."""
    edge = read_edge_preview(
        io.BytesIO(_edge_preview_bytes()),
        entity_class_version=3,
        edge_class_version=2,
    )
    dictionary = AttributeDictionary(name="EntityProperties")
    container = (
        ArchiveObjectTag("object_ref", 12, 12),
        (),
        (dictionary,),
        0,
        0,
    )
    provenance = ArchiveProvenance(
        root_objects=(edge,),
        archive_objects=((11, edge), (12, container)),
        attribute_container_indices_by_owner=((11, 12),),
    )
    model = Model(legacy_archive=provenance)

    populate_root_entities(model, provenance)

    edge_id = model.entities.edges[0].id
    assert model.entities.attribute_dictionaries_by_entity_id == {edge_id: [dictionary]}


def test_populate_supported_definitions_maps_images() -> None:
    """Map CImage previews into shared image entities."""
    target_definition = _component_definition_preview(
        object_index=7,
        guid=b"\x07" * 16,
        name="ImagePlane",
        entity_payloads=(),
    )
    image_preview = Image(
        id=0,
        guid=b"\x00" * 16,
        definition_id=7,
        transform=list(_component_instance_transform_values()),
        name="Placed Image",
    )
    placed_definition = _component_definition_preview(
        object_index=9,
        guid=b"\x09" * 16,
        name="ImageHolder",
        entity_payloads=(image_preview,),
    )
    model = Model(
        legacy_archive=ArchiveProvenance(
            product_name="SketchUp Model",
            version_string="{8.0.1}",
            model_guid=bytes(range(16)),
            saved_path="",
            timestamp=0,
            version_map=(),
            archive_offset=0,
            root_objects=(target_definition, placed_definition),
        )
    )

    populate_definitions(model, model.legacy_archive)

    assert len(model.definitions) == 2
    assert len(model.definitions[1].entities.images) == 1
    image = model.definitions[1].entities.images[0]
    assert image is image_preview
    assert image.name == "Placed Image"
    assert image.definition_id == model.definitions[0].id
    assert image.transform == list(_component_instance_transform_values())


def test_populate_supported_definitions_does_not_infer_root_groups() -> None:
    """Do not invent a root group merely because its definition is unused."""
    edge_preview = read_edge_preview(
        io.BytesIO(_edge_preview_bytes()),
        entity_class_version=3,
        edge_class_version=2,
    )
    group_definition = _component_definition_preview(
        object_index=7,
        guid=b"\x07" * 16,
        name="Group",
        entity_payloads=(edge_preview,),
        definition_type=1,
    )
    model = Model(
        legacy_archive=ArchiveProvenance(
            product_name="SketchUp Model",
            version_string="{8.0.1}",
            model_guid=bytes(range(16)),
            saved_path="",
            timestamp=0,
            version_map=(),
            archive_offset=0,
            root_objects=(group_definition,),
        )
    )

    populate_definitions(model, model.legacy_archive)

    assert len(model.definitions) == 1
    assert not model.entities.groups


def test_populate_supported_definitions_does_not_infer_root_images() -> None:
    """Do not invent a root image merely because its definition is unused."""
    edge_preview = read_edge_preview(
        io.BytesIO(_edge_preview_bytes()),
        entity_class_version=3,
        edge_class_version=2,
    )
    image_definition = _component_definition_preview(
        object_index=7,
        guid=b"\x07" * 16,
        name="ImagePlane",
        entity_payloads=(edge_preview,),
        definition_type=2,
    )
    model = Model(
        legacy_archive=ArchiveProvenance(
            product_name="SketchUp Model",
            version_string="{8.0.1}",
            model_guid=bytes(range(16)),
            saved_path="",
            timestamp=0,
            version_map=(),
            archive_offset=0,
            root_objects=(image_definition,),
        )
    )

    populate_definitions(model, model.legacy_archive)

    assert len(model.definitions) == 1
    assert not model.entities.images
    assert len(model.entities.component_instances) == 0


def test_populate_root_entities_preserves_serialized_component_instances() -> None:
    """Resolve every serialized root instance instead of inferring placement."""
    definition = _component_definition_preview(
        object_index=7,
        guid=b"\x07" * 16,
        name="Target",
        entity_payloads=(),
    )
    instances = tuple(
        ComponentInstance(
            id=0,
            guid=bytes([index]) * 16,
            definition_id=7,
            transform=[
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                float(index),
                0.0,
                0.0,
                1.0,
            ],
            name=f"Placed {index}",
        )
        for index in range(1, 4)
    )
    provenance = ArchiveProvenance(
        product_name="SketchUp Model",
        version_string="{8.0.1}",
        model_guid=bytes(range(16)),
        saved_path="",
        timestamp=0,
        version_map=(),
        archive_offset=0,
        root_objects=(*instances, definition),
    )
    model = Model(legacy_archive=provenance)

    definitions = populate_definitions(model, provenance)
    populate_root_entities(
        model,
        provenance,
        definition_by_object_index=definitions,
    )

    assert [instance.name for instance in model.entities.component_instances] == [
        "Placed 1",
        "Placed 2",
        "Placed 3",
    ]
    assert all(instance.definition_id == model.definitions[0].id for instance in model.entities.component_instances)


def test_populate_supported_definitions_keeps_empty_root_definitions_unplaced() -> None:
    """Do not create root instances for empty component definitions."""
    component_definition = _component_definition_preview(
        object_index=7,
        guid=b"\x07" * 16,
        name="Component",
        entity_payloads=(),
    )
    model = Model(
        legacy_archive=ArchiveProvenance(
            product_name="SketchUp Model",
            version_string="{8.0.1}",
            model_guid=bytes(range(16)),
            saved_path="",
            timestamp=0,
            version_map=(),
            archive_offset=0,
            root_objects=(component_definition,),
        )
    )

    populate_definitions(model, model.legacy_archive)

    assert len(model.definitions) == 1
    assert not model.entities.component_instances
    assert not model.entities.groups
