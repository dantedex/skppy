# SPDX-License-Identifier: MIT
"""MFC CArchive tags, indexes, sessions, and schema guards."""

# ruff: noqa: F403, F405

from ._fixtures import *
from skppy.parser_legacy.binary import LegacyArchiveBuffer


def test_legacy_archive_reader_decodes_object_tags() -> None:
    """Decode the observed CArchive object and class tag forms."""
    data = b"".join(
        [
            b"\x00\x00",
            b"\xff\xff\x16\x00\x0e\x00CSketchUpModel",
            b"\x03\x80",
            b"\xff\x7f\x05\x00\x00\x00",
            b"\xff\x7f\x06\x00\x00\x80",
        ]
    )
    reader = LegacyArchiveReader(io.BytesIO(data))

    assert reader.read_object_tag().kind == "null"

    new_class = reader.read_object_tag()
    assert new_class.kind == "new_class"
    assert new_class.schema == 22
    assert new_class.class_name == "CSketchUpModel"

    class_ref = reader.read_object_tag()
    assert class_ref.kind == "class_ref"
    assert class_ref.index == 3

    object_ref = reader.read_object_tag()
    assert object_ref.kind == "object_ref"
    assert object_ref.index == 5

    extended_class_ref = reader.read_object_tag()
    assert extended_class_ref.kind == "class_ref"
    assert extended_class_ref.index == 6


def test_local_archive_tag_builders_emit_independent_wire_bytes() -> None:
    """Keep class and reference fixtures independent from parser tag objects."""
    assert _new_class_tag("CEdge", schema=2) == (b"\xff\xff\x02\x00\x05\x00CEdge")
    assert _class_ref_tag(3) == b"\x03\x80"
    assert _object_ref_tag(5) == b"\x05\x00"


def test_legacy_archive_buffer_reads_and_seeks_without_scalar_slices() -> None:
    """Decode scalars directly from the in-memory legacy archive cursor."""
    stream = LegacyArchiveBuffer(struct.pack("<HI", 17, 42) + b"tail")
    reader = LegacyArchiveReader(stream)

    assert reader.read_u16() == 17
    checkpoint = stream.tell()
    assert reader.read_u32() == 42
    assert stream.read() == b"tail"
    assert stream.seek(checkpoint) == checkpoint
    assert reader.read_u32() == 42


def test_archive_index_table_tracks_shared_class_and_object_indices() -> None:
    """Track the shared CArchive index sequence seen before simple V8 geometry."""
    table = ArchiveIndexTable()
    table.register_implicit_object("CSketchUpModel", 22)

    tags = _read_object_tags(
        b"".join(
            [
                _new_class_tag("CAttributeContainer", schema=0),
                _new_class_tag("CAttributeNamed", schema=1),
                _new_class_tag("CCamera", schema=5),
                _new_class_tag("CLayer", schema=3),
                _new_class_tag("CEdge", schema=2),
                _new_class_tag("CVertex", schema=0),
            ]
        )
    )
    for tag in tags:
        table.register_new_object_tag(tag)

    class_entry = table.resolve_class(13)
    object_entry = table.resolve_object(14)

    assert class_entry is not None
    assert class_entry.class_name == "CVertex"
    assert object_entry is not None
    assert object_entry.class_name == "CVertex"


def test_archive_index_table_resolves_object_handles() -> None:
    """Resolve object tags while registering new objects in archive order."""
    table = ArchiveIndexTable()
    null_handle = table.resolve_or_register_object_tag(_read_object_tags(b"\x00\x00")[0])
    assert null_handle.kind == "null"
    assert null_handle.object_index == 0

    edge_handle = table.resolve_or_register_object_tag(_read_object_tags(_new_class_tag("CEdge", schema=2))[0])
    assert edge_handle.kind == "new_object"
    assert edge_handle.class_index == 1
    assert edge_handle.object_index == 2
    assert edge_handle.class_name == "CEdge"

    next_edge_handle = table.resolve_or_register_object_tag(_read_object_tags(_class_ref_tag(1))[0])
    assert next_edge_handle.kind == "new_object"
    assert next_edge_handle.class_index == 1
    assert next_edge_handle.object_index == 3
    assert next_edge_handle.class_name == "CEdge"

    ref_handle = table.resolve_or_register_object_tag(_read_object_tags(b"\x02\x00")[0])
    assert ref_handle.kind == "object_ref"
    assert ref_handle.object_index == 2
    assert ref_handle.class_name == "CEdge"


def test_archive_index_table_class_ref_can_target_object_entry() -> None:
    """Resolve old class refs that point at an object-table entry."""
    table = ArchiveIndexTable()
    vertex_tag = _read_object_tags(_new_class_tag("CVertex", schema=0))[0]
    table.register_new_object_tag(vertex_tag)

    next_vertex_tag = _read_object_tags(_class_ref_tag(2))[0]
    registration = table.register_new_object_tag(next_vertex_tag)

    assert registration is not None
    assert registration.class_index == 2
    assert registration.class_name == "CVertex"
    assert registration.schema == 0


def test_legacy_archive_session_reads_handles_and_tracks_offsets() -> None:
    """Use the stateful archive session as the reader/table entry point."""
    data = b"".join(
        [
            _new_class_tag("CEdge", schema=2),
            _class_ref_tag(3),
            _object_ref_tag(4),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))
    root = session.register_implicit_object("CSketchUpModel", 22)
    assert root.class_index == 1
    assert root.object_index == 2

    first_edge = session.read_object_handle()
    assert first_edge.kind == "new_object"
    assert first_edge.class_index == 3
    assert first_edge.object_index == 4
    assert first_edge.class_name == "CEdge"

    second_edge = session.read_object_handle()
    assert second_edge.kind == "new_object"
    assert second_edge.class_index == 3
    assert second_edge.object_index == 5
    assert second_edge.class_name == "CEdge"

    edge_ref = session.read_object_handle()
    assert edge_ref.kind == "object_ref"
    assert edge_ref.object_index == 4
    assert edge_ref.class_name == "CEdge"
    assert session.tell() == len(data)


def test_seed_known_archive_entries_stops_before_root_component() -> None:
    """Leave root-component classes to the stateful reader."""
    session = LegacyArchiveSession(io.BytesIO(b""))
    _seed_known_archive_entries(
        session,
        model_class_version=22,
        root_prefix=SimpleNamespace(thumbnail=None),
        model_properties_object_tag=_read_object_tags(_new_class_tag("CAttributeContainer", schema=0))[0],
        model_property_tags=(),
        camera_section_leading_dib=None,
        root_camera_tag=_read_object_tags(_new_class_tag("CCamera", schema=5))[0],
    )
    assert not any(entry.class_name == "CLayer" for entry in session.index_table.entries)


def test_read_edge_preview_decodes_simple_edge_payload() -> None:
    """Decode the simple V8 edge shape emitted by generated edge fixtures."""
    data = _edge_preview_bytes()

    edge = read_edge_preview(io.BytesIO(data), entity_class_version=3, edge_class_version=2)

    assert edge.object_tag.kind == "new_class"
    assert edge.object_tag.class_name == "CEdge"
    assert edge.drawing_element.material_tag.kind == "null"
    assert edge.drawing_element.hidden is False
    assert edge.drawing_element.casts_shadows is True
    assert edge.drawing_element.receives_shadows is True
    assert edge.drawing_element.soft is False
    assert edge.drawing_element.smooth is False
    assert edge.drawing_element.locked is False
    assert edge.drawing_element.layer_tag is not None
    assert edge.drawing_element.layer_tag.kind == "null"
    assert edge.start_vertex.position.to_tuple() == (0.0, 0.0, 0.0)
    assert edge.end_vertex.position.to_tuple() == (10.0, 10.0, 10.0)
    assert edge.curve_tag is not None
    assert edge.curve_tag.kind == "null"
    assert edge.payload_end_offset == len(data)


def test_read_edge_preview_maps_drawing_flags_to_shared_edge() -> None:
    """Expose legacy hidden/soft/smooth state through the common Edge API."""
    data = _edge_preview_bytes(hidden=True, soft=True, smooth=True)

    edge = read_edge_preview(io.BytesIO(data), entity_class_version=3, edge_class_version=2)

    assert edge.edge.is_hidden is True
    assert edge.edge.is_soft is True
    assert edge.edge.is_smooth is True


def test_read_edge_preview_from_session_tracks_vertex_class_ref() -> None:
    """Decode CEdge while registering inline vertex class refs in the session."""
    session = LegacyArchiveSession(io.BytesIO(_edge_preview_bytes()))
    session.register_implicit_object("CSketchUpModel", 22)
    for tag in _read_object_tags(
        b"".join(
            [
                _new_class_tag("CAttributeContainer", schema=0),
                _new_class_tag("CAttributeNamed", schema=1),
                _new_class_tag("CCamera", schema=5),
                _new_class_tag("CLayer", schema=3),
            ]
        )
    ):
        session.index_table.register_new_object_tag(tag)

    edge = read_edge_preview_from_session(session, entity_class_version=3, edge_class_version=2)
    vertex_class = session.index_table.resolve_class(13)
    vertex_object = session.index_table.resolve_object(14)

    assert vertex_class is not None
    assert vertex_class.class_name == "CVertex"
    assert vertex_object is not None
    assert session.objects[14] is edge.start_vertex
    assert vertex_class is not None
    assert vertex_class.class_name == "CVertex"
    assert vertex_object is not None
    assert vertex_object.class_name == "CVertex"
    assert session.tell() == len(_edge_preview_bytes())


def test_archive_session_tracks_only_objects_stored_after_checkpoint() -> None:
    """Collect inline objects without rescanning the complete archive table."""
    session = LegacyArchiveSession(io.BytesIO())
    first = ArchiveObjectHandle("null", ArchiveObjectTag("null", 0, 0), 0, None, None, None)
    second = ArchiveObjectHandle("null", ArchiveObjectTag("null", 0, 0), 0, None, None, None)

    session.store_object(1, first)
    checkpoint = session.object_checkpoint()
    session.store_object(2, second)
    session.store_object(2, second)

    assert session.objects_since(checkpoint) == [second]


def test_read_supported_object_dispatches_edge() -> None:
    """Dispatch a supported new object by runtime class name."""
    session = LegacyArchiveSession(io.BytesIO(_edge_preview_bytes()))
    session.register_implicit_object("CSketchUpModel", 22)
    for tag in _read_object_tags(
        b"".join(
            [
                _new_class_tag("CAttributeContainer", schema=0),
                _new_class_tag("CAttributeNamed", schema=1),
                _new_class_tag("CCamera", schema=5),
                _new_class_tag("CLayer", schema=3),
            ]
        )
    ):
        session.index_table.register_new_object_tag(tag)

    preview = read_supported_object(session, {"CEntity": 3, "CEdge": 2, "CVertex": 0})

    assert isinstance(preview, EdgeState)
    assert preview.payload_end_offset == len(_edge_preview_bytes())


def test_read_supported_object_reports_unsupported_context() -> None:
    """Report archive context when a V8 runtime class has no dispatch path."""
    data = _new_class_tag("CSpace", schema=0)
    session = LegacyArchiveSession(io.BytesIO(data))
    error = None

    try:
        read_supported_object(session, {"CEntity": 3, "CSpace": 0})
    except UnsupportedLegacyObjectError as exc:
        error = exc
        message = str(exc)
    else:
        raise AssertionError("Unsupported legacy object did not raise.")

    assert error is not None
    assert error.class_name == "CSpace"
    assert error.offset == 12
    assert error.schema == 0
    assert error.class_index == 1
    assert error.object_index == 2
    assert error.tag_kind == "new_class"
    assert "Unsupported legacy object class 'CSpace'" in message
    assert "offset 12" in message
    assert "schema=0" in message
    assert "class_index=1" in message
    assert "object_index=2" in message
    assert "tag_kind='new_class'" in message


def test_strict_schema_rejected_before_payload_is_consumed() -> None:
    """Reject an unverified changed layout at the object payload boundary."""
    object_tag = _new_class_tag("CComponentInstance", schema=3)
    session = LegacyArchiveSession(io.BytesIO(object_tag + b"PAYLOAD"), file_version="4.0.0")

    with pytest.raises(UnsupportedLegacySchemaError) as caught:
        read_supported_object(
            session,
            {"CEntity": 3, "CComponentInstance": 3},
        )

    assert session.tell() == len(object_tag)
    assert caught.value.class_name == "CComponentInstance"
    assert caught.value.schema == 3
    assert caught.value.file_version == "4.0.0"
    assert caught.value.object_index == 2


def test_every_strict_schema_class_rejects_unknown_layout_before_body() -> None:
    """Keep every enumerated runtime-layout guard at the object boundary."""
    from skppy.parser_legacy.schema import VERIFIED_CLASS_SCHEMAS

    for class_name, supported_schemas in VERIFIED_CLASS_SCHEMAS.items():
        unsupported_schema = max(supported_schemas) + 1
        object_tag = _new_class_tag(class_name, schema=unsupported_schema)
        session = LegacyArchiveSession(io.BytesIO(object_tag + b"UNREAD"), file_version="8.0.1")

        with pytest.raises(UnsupportedLegacySchemaError):
            read_supported_object(session, {class_name: unsupported_schema})

        assert session.tell() == len(object_tag)


def test_current_sdk_component_definition_tag_accepts_su8_payload() -> None:
    """Accept runtime schema 11 when the SU8 version map selects payload v10."""
    from skppy.parser_legacy.schema import require_verified_schema

    require_verified_schema(
        "CComponentDefinition",
        11,
        file_version="8.0.1",
        offset=0,
        object_index=12,
    )
    require_verified_schema(
        "CComponentInstance",
        6,
        file_version="8.0.1",
        offset=0,
        object_index=13,
    )
