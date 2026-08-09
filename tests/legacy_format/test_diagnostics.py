# SPDX-License-Identifier: MIT
"""Non-raising V8 diagnostics and class coverage reports."""

# ruff: noqa: F403, F405

from ._fixtures import *


def test_diagnose_legacy_bytes_reports_unsupported_class() -> None:
    """Return structured diagnostics when V8 parsing finds an unsupported class."""
    data = _legacy_file_bytes(
        saved_path="C:/models/space.skp",
        root_entity_count=1,
        root_entity_payload=_new_class_tag("CSpace", schema=0),
    )

    report = diagnose_legacy_bytes(data)

    assert not report.ok
    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue.kind == "unsupported_object"
    assert issue.class_name == "CSpace"
    assert issue.schema == 0
    assert issue.class_index is not None
    assert issue.object_index is not None
    assert issue.offset is not None
    assert issue.tag_kind == "new_class"


def test_diagnose_legacy_bytes_returns_ok_report() -> None:
    """Return an OK report when the V8 stream parses without diagnostics."""
    report = diagnose_legacy_bytes(_legacy_file_bytes(saved_path="C:/models/empty.skp"))

    assert report.ok
    assert report.issues == ()


def test_diagnose_legacy_bytes_reports_invalid_envelope() -> None:
    """Return a structured issue for bytes that are not a V8 envelope."""
    report = diagnose_legacy_bytes(b"PK\x03\x04not-a-legacy-archive-file")

    assert not report.ok
    assert report.issues[0].kind == "invalid_legacy_envelope"


def test_parse_legacy_loads_dimension_linear_preview() -> None:
    """Load structured V8 linear-dimension anchors and geometry."""
    data = _legacy_file_bytes(
        saved_path="C:/models/dimension.skp",
        root_entity_count=1,
        root_entity_payload=_dimension_linear_preview_bytes(),
        extra_version_entries=[
            ("CDimension", 1),
            ("CDimensionLinear", 6),
        ],
    )

    model = parse_legacy_bytes(data)

    assert model.legacy_archive is not None
    payload = model.legacy_archive.root_objects[0]
    assert payload.dimension.text == ""
    assert payload.dimension.font_tag.kind == "null"
    assert payload.dimension.is_3d_text is False
    assert payload.dimension.arrow_type == 0
    assert payload.start_ref.position == (0.0, 0.0, 0.0)
    assert payload.end_ref.position == (100.0, 0.0, 0.0)
    assert payload.normal == (0.0, 0.0, 1.0)
    assert payload.x_axis == (1.0, 0.0, 0.0)
    assert payload.dimension_type == 0
    assert payload.y_position == 0.0
    assert payload.x_position == 0.0
    assert payload.text_position == 1
    assert len(model.entities.linear_dimensions) == 1
    dimension = model.entities.linear_dimensions[0]
    assert dimension.start.position.to_tuple() == (0.0, 0.0, 0.0)
    assert dimension.end.position.to_tuple() == (100.0, 0.0, 0.0)
    assert dimension.direction.to_tuple() == (0.0, 0.0, 1.0)
    assert dimension.render_direction.to_tuple() == (1.0, 0.0, 0.0)
    assert dimension.alignment == 1


def test_parse_legacy_maps_text_to_shared_entity() -> None:
    """Publish decoded legacy text instead of leaving it in archive provenance."""
    text_payload = b"".join(
        [
            _new_class_tag("CText", schema=9),
            _drawing_element_payload_bytes(),
            _new_class_tag("CSkFont", schema=1),
            b"\x00\x00",
            _font_preview_payload_bytes("Arial"),
            struct.pack("<2d", 0.25, 0.5),
            _point_ref_preview_bytes(),
            struct.pack("<3d", 1.0, 2.0, 3.0),
            struct.pack("<3d", 0.0, 0.0, 1.0),
            struct.pack("<II", 2, 3),
            b"\x01\x00",
            struct.pack("<I", 4),
            b"\x01",
            _legacy_string("Label"),
            b"\x00",
            struct.pack("<I", 5),
        ]
    )
    model = parse_legacy_bytes(
        _legacy_file_bytes(
            saved_path="text.skp",
            root_entity_count=1,
            root_entity_payload=text_payload,
            extra_version_entries=[("CText", 9), ("CSkFont", 1)],
        )
    )

    assert len(model.entities.texts) == 1
    text = model.entities.texts[0]
    assert text.text == "Label"
    assert text.font is not None and text.font.face_name == "Arial"
    assert (text.screen_position.x, text.screen_position.y) == (0.25, 0.5)
    assert text.anchor.position.to_tuple() == (1.0, 2.0, 3.0)
    assert text.leader_vector.to_tuple() == (1.0, 2.0, 3.0)
    assert text.view_direction.to_tuple() == (0.0, 0.0, 1.0)


def test_parse_legacy_maps_radial_dimension_to_shared_entity() -> None:
    """Publish radial placement and embedded arc geometry."""
    radial_payload = b"".join(
        [
            _new_class_tag("CDimensionRadial", schema=2),
            _dimension_base_payload_bytes(text="Radius"),
            b"\x00\x00",
            struct.pack("<2d", 1.5, 2.5),
            b"\x01",
            _arc3d_preview_payload_bytes(),
        ]
    )
    model = parse_legacy_bytes(
        _legacy_file_bytes(
            saved_path="radial.skp",
            root_entity_count=1,
            root_entity_payload=radial_payload,
            extra_version_entries=[("CDimension", 1), ("CDimensionRadial", 2)],
        )
    )

    assert len(model.entities.radial_dimensions) == 1
    dimension = model.entities.radial_dimensions[0]
    assert dimension.text == "Radius"
    assert dimension.parameter == 1.5
    assert dimension.radius_ratio == 2.5
    assert dimension.is_diameter is True
    assert dimension.arc is not None
    assert dimension.arc.center.to_tuple() == (1.0, 2.0, 3.0)
    assert dimension.arc.y_axis is not None
    assert dimension.arc.y_axis.to_tuple() == (0.0, 1.0, 0.0)


def test_parse_legacy_maps_font_previews() -> None:
    """Map observed post-layer CSkFont previews into public model fonts."""
    data = _legacy_file_bytes(
        saved_path="C:/models/fonts.skp",
        root_entity_count=1,
        root_entity_payload=_edge_preview_bytes(),
        trailing_archive_payload=b"".join(
            [
                _font_preview_payload_bytes("Arial"),
                _font_preview_payload_bytes("Tahoma", bold=True),
            ]
        ),
    )

    model = parse_legacy_bytes(data)

    assert [font.face_name for font in model.fonts] == ["Arial", "Tahoma"]
    assert [font.point_size for font in model.fonts] == [12, 12]
    assert model.fonts[1].bold is True


def test_parse_legacy_maps_style_previews() -> None:
    """Map observed post-layer CSkpStyle previews into the public style registry."""
    guid = bytes(range(16))
    data = _legacy_file_bytes(
        saved_path="C:/models/styles.skp",
        root_entity_count=1,
        root_entity_payload=_edge_preview_bytes(),
        trailing_archive_payload=_style_preview_payload_bytes(
            guid=guid,
            display_name="Style",
            file_name="",
        ),
    )

    model = parse_legacy_bytes(data)

    assert model.styles_registry is not None
    assert len(model.styles_registry.styles) == 1
    style = model.styles_registry.styles[0]
    assert style.guid == guid
    assert style.display_name == "Style"
    assert style.file_name == ""


def test_diagnose_legacy_class_coverage_reports_version_map_statuses() -> None:
    """Class coverage diagnostics classify version-map entries by support state."""
    report = diagnose_legacy_class_coverage_bytes(
        _legacy_file_bytes(
            saved_path="C:/models/coverage.skp",
            extra_version_entries=[
                ("CText", 9),
                ("CPolyline3d", 1),
                ("CRelationshipMap", 0),
                ("CAttribute", 0),
                ("CSkpStyleManager", 2),
                ("CWatermark", 1),
                ("CWatermarkManager", 2),
                ("CSketchUpPage", 1),
                ("CSketchCS", 0),
                ("CViewPage", 12),
                ("CSpace", 0),
                ("CDimension", 1),
                ("CDimensionLinear", 6),
                ("CDimensionRadial", 2),
                ("CShadowInfo", 7),
                ("CSkFont", 1),
                ("CFontManager", 0),
                ("CTextStyle", 5),
                ("CDimensionStyle", 4),
                ("CSkpStyle", 1),
            ],
        )
    )

    status_by_name = {entry.class_name: entry.status for entry in report.entries}

    assert status_by_name["CEdge"] == "supported"
    assert status_by_name["CDimension"] == "supported"
    assert status_by_name["CDimensionLinear"] == "supported"
    assert status_by_name["CDimensionRadial"] == "supported"
    assert status_by_name["CSkFont"] == "supported"
    assert status_by_name["CFontManager"] == "supported"
    assert status_by_name["CTextStyle"] == "supported"
    assert status_by_name["CDimensionStyle"] == "supported"
    assert status_by_name["CSkpStyle"] == "supported"
    assert status_by_name["CText"] == "supported"
    assert status_by_name["CPolyline3d"] == "supported"
    assert status_by_name["CRelationshipMap"] == "supported"
    assert status_by_name["CAttribute"] == "supported"
    assert status_by_name["CSkpStyleManager"] == "supported"
    assert status_by_name["CWatermark"] == "supported"
    assert status_by_name["CWatermarkManager"] == "supported"
    assert status_by_name["CSketchUpPage"] == "supported"
    assert status_by_name["CSketchCS"] == "supported"
    assert status_by_name["CViewPage"] == "supported"
    assert status_by_name["CSpace"] == "missing"
    assert status_by_name["CShadowInfo"] == "supported"
    assert "End-Of-Version-Map" not in status_by_name
    assert any(entry.class_name == "CSpace" for entry in report.missing_entries)
    assert report.heuristic_entries == ()


def test_diagnose_legacy_class_coverage_reports_invalid_envelope() -> None:
    """Do not raise when class coverage is asked to inspect a non-V8 stream."""
    report = diagnose_legacy_class_coverage_bytes(b"PK\x03\x04not-a-legacy-archive-file")

    assert not report.ok
    assert report.entries == ()
    assert report.issues[0].kind == "invalid_legacy_envelope"


def test_diagnose_legacy_runtime_classes_reports_observed_tags() -> None:
    """Distinguish version-map entries from runtime classes observed in bytes."""
    report = diagnose_legacy_runtime_classes_bytes(
        _legacy_file_bytes(
            saved_path="C:/models/runtime-classes.skp",
            root_entity_count=1,
            root_entity_payload=_edge_preview_bytes(),
            extra_version_entries=[
                ("CText", 9),
                ("CPolyline3d", 1),
                ("CRelationshipMap", 0),
                ("CAttribute", 0),
                ("CSkpStyleManager", 2),
                ("CWatermark", 1),
                ("CWatermarkManager", 2),
                ("CSketchUpPage", 1),
                ("CSketchCS", 0),
                ("CViewPage", 12),
                ("CSpace", 0),
                ("CShadowInfo", 7),
            ],
            trailing_archive_payload=b"".join(
                [
                    _new_class_tag("CWatermark", schema=1),
                    _new_class_tag("CSketchCS", schema=0),
                    _new_class_tag("CViewPage", schema=12),
                    _new_class_tag("CSpace", schema=0),
                    _new_class_tag("CShadowInfo", schema=7),
                ]
            ),
        )
    )

    observed_by_name = {entry.class_name: entry for entry in report.observed_entries}

    assert observed_by_name["CEdge"].status == "supported"
    assert observed_by_name["CWatermark"].status == "supported"
    assert observed_by_name["CWatermark"].count == 1
    assert observed_by_name["CSketchCS"].status == "supported"
    assert observed_by_name["CSketchCS"].count == 1
    assert observed_by_name["CViewPage"].status == "supported"
    assert observed_by_name["CViewPage"].count == 1
    assert observed_by_name["CSpace"].status == "missing"
    assert observed_by_name["CSpace"].count == 1
    assert observed_by_name["CShadowInfo"].status == "supported"
    assert observed_by_name["CShadowInfo"].first_offset is not None
    assert [entry.class_name for entry in report.missing_observed_entries] == ["CSpace"]
    assert report.heuristic_observed_entries == ()


def test_diagnose_legacy_runtime_classes_reports_invalid_envelope() -> None:
    """Do not raise when runtime observation is asked to inspect a non-V8 stream."""
    report = diagnose_legacy_runtime_classes_bytes(b"PK\x03\x04not-a-legacy-archive-file")

    assert not report.ok
    assert report.entries == ()
    assert report.issues[0].kind == "invalid_legacy_envelope"
