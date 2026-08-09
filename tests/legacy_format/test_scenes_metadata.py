# SPDX-License-Identifier: MIT
"""Scene recovery and model metadata object decoding."""

# ruff: noqa: F403, F405

from ._fixtures import *


def test_model_tail_state_supports_incremental_population() -> None:
    """Keep mutable defaults isolated while the model tail is being decoded."""
    first = ModelTailState()
    second = ModelTailState()

    first.payload_start_offset = 128

    assert first.payload_start_offset == 128
    assert second.payload_start_offset == 0
    assert first.shadow_info is not second.shadow_info
    assert first.styles_registry is not second.styles_registry


def test_scan_scene_previews_extracts_view_page_strings() -> None:
    """Extract the confirmed leading strings from inline CViewPage payloads."""
    raw_tail = _scene_page_tail_bytes(
        flags=0,
        include_in_animation=True,
        transition_time=-1.0,
        delay_time=-1.0,
        trailing_payload=b"\x01\x02\x03\x04",
    )
    data = b"\x00\x00\x00" + b"".join(
        [
            _new_class_tag("CViewPage", schema=15),
            b"\x00\x00",
            _legacy_string("TestScene"),
            _legacy_string("Description"),
            raw_tail,
            _new_class_tag("CSkFont", schema=1),
        ]
    )

    previews = _scan_scene_previews(data, absolute_start=100)

    assert len(previews) == 1
    assert previews[0].object_tag.class_name == "CViewPage"
    assert previews[0].name == "TestScene"
    assert previews[0].description == "Description"
    assert previews[0].raw_tail_payload == raw_tail
    assert previews[0].flags_u32 == 0
    assert previews[0].include_in_animation is True
    assert previews[0].transition_time == -1.0
    assert previews[0].delay_time == -1.0
    assert previews[0].timing_offset == 4
    assert previews[0].use_camera is False
    assert previews[0].use_layer_visibility is False
    assert previews[0].payload_start_offset == 100 + 3 + len(_new_class_tag("CViewPage", schema=15))
    assert previews[0].payload_end_offset == 100 + len(data) - len(_new_class_tag("CSkFont", schema=1))


def test_read_view_page_preview_from_span_extracts_confirmed_prefix() -> None:
    """Read a bounded CViewPage span without depending on post-layer scanning."""
    raw_tail = _scene_page_tail_bytes(
        flags=0x20,
        include_in_animation=False,
        transition_time=1.25,
        delay_time=2.5,
        trailing_payload=b"\xaa\xbb",
    )
    data = b"\x99\x88" + b"".join(
        [
            _new_class_tag("CViewPage", schema=12),
            b"\x00\x00",
            _legacy_string("SpanScene"),
            _legacy_string("From span"),
            raw_tail,
            b"\x77\x66",
        ]
    )
    tag_offset = 2
    payload_end_offset = len(data) - 2

    preview = read_view_page_preview_from_span(
        data,
        tag_offset=tag_offset,
        payload_end_offset=payload_end_offset,
        absolute_start=500,
    )

    assert preview.object_tag.class_name == "CViewPage"
    assert preview.payload_start_offset == 500 + tag_offset + len(_new_class_tag("CViewPage", schema=12))
    assert preview.name == "SpanScene"
    assert preview.description == "From span"
    assert preview.flags_u32 == 0x20
    assert preview.include_in_animation is False
    assert preview.transition_time == 1.25
    assert preview.delay_time == 2.5
    assert preview.timing_offset == 4
    assert preview.use_camera is False
    assert preview.use_layer_visibility is True
    assert preview.use_section_planes is False
    assert preview.raw_tail_payload == raw_tail
    assert preview.payload_end_offset == 500 + payload_end_offset


def test_scan_scene_previews_extracts_class_ref_view_pages() -> None:
    """Extract later CViewPage records serialized through CArchive class refs."""
    first_tail = _scene_page_tail_bytes(
        flags=0,
        include_in_animation=True,
        transition_time=-1.0,
        delay_time=-1.0,
    )
    second_tail = _scene_page_tail_bytes(
        flags=0x20,
        include_in_animation=False,
        transition_time=1.0,
        delay_time=2.0,
    )
    data = b"".join(
        [
            _new_class_tag("CViewPage", schema=12),
            b"\x00\x00",
            _legacy_string("FirstScene"),
            _legacy_string(""),
            first_tail,
            struct.pack("<H", 0x800B),
            b"\x00\x00",
            _legacy_string("SecondScene"),
            _legacy_string("Description"),
            second_tail,
            _new_class_tag("CSkFont", schema=1),
        ]
    )

    previews = _scan_scene_previews(data, absolute_start=1000)

    assert [preview.name for preview in previews] == ["FirstScene", "SecondScene"]
    assert [preview.raw_tail_payload for preview in previews] == [
        first_tail,
        second_tail,
    ]
    assert previews[1].object_tag.kind == "class_ref"
    assert previews[1].flags_u32 == 0x20
    assert previews[1].include_in_animation is False


def test_scan_scene_previews_finds_timing_after_optional_payload() -> None:
    """Extract CViewPage timing after flag-dependent camera/page payload bytes."""
    raw_tail = b"".join(
        [
            struct.pack("<I", 0x01),
            b"\x07\x80",
            b"\x00" * 32,
            _scene_timing_bytes(
                include_in_animation=True,
                transition_time=-1.0,
                delay_time=-1.0,
            ),
        ]
    )
    data = b"".join(
        [
            _new_class_tag("CViewPage", schema=12),
            b"\x00\x00",
            _legacy_string("CameraScene"),
            _legacy_string(""),
            raw_tail,
            _new_class_tag("CSkFont", schema=1),
        ]
    )

    previews = _scan_scene_previews(data, absolute_start=0)

    assert len(previews) == 1
    assert previews[0].flags_u32 == 0x01
    assert previews[0].include_in_animation is True
    assert previews[0].transition_time == -1.0
    assert previews[0].delay_time == -1.0
    assert previews[0].timing_offset == 38
    assert previews[0].use_camera is True
    assert previews[0].use_layer_visibility is False
    assert previews[0].raw_tail_payload == raw_tail


def test_parse_legacy_maps_scene_page_flags_and_raw_payload() -> None:
    """Map confirmed CViewPage page fields while preserving the opaque tail."""
    raw_tail = _scene_page_tail_bytes(
        flags=0x20,
        include_in_animation=False,
        transition_time=1.5,
        delay_time=2.5,
        trailing_payload=b"\xaa\xbb",
    )
    second_tail = _scene_page_tail_bytes(
        flags=0x40,
        include_in_animation=True,
        transition_time=3.5,
        delay_time=4.5,
    )
    data = _legacy_file_bytes(
        saved_path="C:/models/scenes.skp",
        root_entity_count=1,
        root_entity_payload=_edge_preview_bytes(),
        trailing_archive_payload=b"".join(
            [
                _new_class_tag("CViewPage", schema=12),
                b"\x00\x00",
                _legacy_string("TestScene"),
                _legacy_string("Description"),
                raw_tail,
                struct.pack("<H", 0x800B),
                b"\x00\x00",
                _legacy_string("SecondScene"),
                _legacy_string(""),
                second_tail,
                _new_class_tag("CSkFont", schema=1),
            ]
        ),
    )

    model = parse_legacy_bytes(data)

    assert len(model.scenes) == 2
    assert model.scenes[0].name == "TestScene"
    assert model.scenes[0].description == "Description"
    assert model.scenes[0].flags == 0x20
    assert model.scenes[0].show_in_slideshow is False
    assert model.scenes[0].raw_payload == raw_tail
    assert model.scenes[1].name == "SecondScene"
    assert model.scenes[1].flags == 0x40
    assert model.scenes[1].show_in_slideshow is True
    assert model.scenes[1].raw_payload == second_tail
    assert model.legacy_archive is not None
    assert model.legacy_archive.scene_previews[0].transition_time == 1.5
    assert model.legacy_archive.scene_previews[0].delay_time == 2.5
    assert model.legacy_archive.scene_previews[0].timing_offset == 4
    assert model.legacy_archive.scene_previews[1].transition_time == 3.5
    assert model.legacy_archive.scene_previews[1].delay_time == 4.5
    assert model.legacy_archive.scene_previews[1].timing_offset == 4


def test_parse_legacy_maps_direct_view_page_camera_to_scene() -> None:
    """Prefer a directly decoded view page over its scanner preview."""
    data = _legacy_file_bytes(
        saved_path="C:/models/direct-scene.skp",
        root_entity_count=1,
        root_entity_payload=b"".join(
            [
                _new_class_tag("CViewPage", schema=12),
                b"\x00\x00",
                _legacy_string("Camera scene"),
                _legacy_string("Directly decoded"),
                struct.pack("<I", 0x01),
                _new_class_tag("CCamera", schema=5),
                _camera_payload_bytes(),
                b"\x01",
                struct.pack("<d", 1.5),
                struct.pack("<d", 2.5),
                b"\x00\x00",
                b"\x00",
                b"\x00",
            ]
        ),
        extra_version_entries=[("CSketchUpPage", 1), ("CViewPage", 12)],
    )

    model = parse_legacy_bytes(data)

    assert len(model.scenes) == 1
    assert model.scenes[0].name == "Camera scene"
    assert model.scenes[0].camera is not None
    assert model.scenes[0].camera.eye.to_tuple() == (10.0, 20.0, 30.0)
    assert model.scenes[0].camera.fov == 0.1
    assert model.scenes[0].camera.near == 35.0
    assert model.scenes[0].camera.far == 45.0
    assert model.legacy_archive is not None
    assert len(model.legacy_archive.archived_scenes) == 1
    assert model.scenes[0] is model.legacy_archive.archived_scenes[0].scene


def test_scan_shadow_info_extracts_location_scalars() -> None:
    """Extract confirmed V8 shadow/geolocation strings and coordinate doubles."""
    data = b"\x00\x00" + b"".join(
        [
            _legacy_string("Boulder (CO)"),
            _legacy_string("USA"),
            struct.pack("<d", -120.0),
            struct.pack("<d", 45.0),
            struct.pack("<d", -7.0),
            b"\x00\x00",
        ]
    )

    preview = _scan_shadow_info(data, absolute_start=200)

    assert preview is not None
    assert preview.value.country == b"USA"
    assert preview.value.city == b"Boulder (CO)"
    assert preview.value.longitude == -120.0
    assert preview.value.latitude == 45.0
    assert preview.value.timezone_offset == -7.0
    assert preview.payload_start_offset == 202


def test_explicit_metadata_takes_precedence_over_recovery() -> None:
    """Attach explicit archive metadata objects by identity before scan fallback."""
    data = _legacy_file_bytes(
        saved_path="C:/models/metadata.skp",
        root_entity_count=2,
        root_entity_payload=b"".join(
            [
                _new_class_tag("CShadowInfo", schema=7),
                _shadow_info_payload_bytes(),
                _new_class_tag("CSketchCS", schema=0),
                _drawing_element_payload_bytes(),
                _sketch_cs_payload_bytes(),
            ]
        ),
        extra_version_entries=[("CShadowInfo", 7), ("CSketchCS", 0)],
    )

    model = parse_legacy_bytes(data)

    assert model.legacy_archive is not None
    explicit_shadow = next(value for _, value in model.legacy_archive.archive_objects if isinstance(value, ShadowInfo))
    explicit_axes = next(value for _, value in model.legacy_archive.archive_objects if isinstance(value, ModelViewAxes))
    assert model.shadow_info is explicit_shadow
    assert model.model_view_axes is explicit_axes


def test_scan_model_view_axes_extracts_orthonormal_axes() -> None:
    """Extract confirmed V8 model axes from origin plus basis vectors."""
    data = b"\x00\x00" + struct.pack(
        "<12d",
        10.0,
        10.0,
        10.0,
        2**-0.5,
        2**-0.5,
        0.0,
        -(2**-0.5),
        2**-0.5,
        0.0,
        0.0,
        0.0,
        1.0,
    )

    preview = _scan_model_view_axes(
        data,
        absolute_start=300,
        shadow_info=None,
    )

    assert preview is not None
    assert preview.payload_start_offset == 302
    assert preview.value.origin == (10.0, 10.0, 10.0)
    assert preview.value.z_axis == (0.0, 0.0, 1.0)


def test_scan_font_previews_extracts_font_records() -> None:
    """Extract observed CSkFont face names and point sizes from post-layer bytes."""
    data = b"".join(
        [
            b"\x00\x00",
            _font_preview_payload_bytes("Arial"),
            b"\x12\x34",
            _font_preview_payload_bytes("Tahoma", italic=True),
        ]
    )

    previews = scan_font_previews(data, absolute_start=400)

    assert [preview.face_name for preview in previews] == ["Arial", "Tahoma"]
    assert [preview.point_size for preview in previews] == [12, 12]
    assert previews[0].bold is False
    assert previews[1].italic is True


def test_scan_style_previews_extracts_style_records() -> None:
    """Extract observed CSkpStyle GUID and display-name records."""
    guid = bytes(range(16))
    data = b"\x00\x00" + _style_preview_payload_bytes(
        guid=guid,
        display_name="Style",
        file_name="classic.style",
        option_count=53,
    )

    previews = scan_style_previews(data, absolute_start=500)

    assert len(previews) == 1
    assert previews[0].guid == guid
    assert previews[0].display_name == "Style"
    assert previews[0].file_name == "classic.style"


def test_read_supported_object_dispatches_font() -> None:
    """Dispatch observed CSkFont v1 payloads through the shared object path."""
    data = b"".join(
        [
            _new_class_tag("CSkFont", schema=1),
            b"\x00\x00",
            _font_preview_payload_bytes("Arial", bold=True),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(session, {"CEntity": 3, "CSkFont": 1})

    assert isinstance(preview, Font)
    assert preview.face_name == "Arial"
    assert preview.bold is True
    assert preview.italic is False
    assert preview.point_size == 12
    assert preview.use_world_size is False
    assert preview.world_size == 1.0
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_font_manager() -> None:
    """Dispatch CFontManager v0 and resolve contained CSkFont objects."""
    data = b"".join(
        [
            _new_class_tag("CFontManager", schema=0),
            b"\x00\x00",
            struct.pack("<I", 2),
            _new_class_tag("CSkFont", schema=1),
            b"\x00\x00",
            _font_preview_payload_bytes("Arial", bold=True),
            _object_ref_tag(4),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CFontManager": 0,
            "CSkFont": 1,
        },
    )

    assert isinstance(preview, tuple)
    assert len(preview) == 2
    assert [font.face_name for font in preview] == ["Arial", "Arial"]
    assert preview[0] is preview[1]
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_text_style() -> None:
    """Dispatch CTextStyle v5 and resolve model/screen font references."""
    data = b"".join(
        [
            _new_class_tag("CTextStyle", schema=5),
            b"\x00\x00",
            _new_class_tag("CSkFont", schema=1),
            b"\x00\x00",
            _font_preview_payload_bytes("Arial"),
            struct.pack("<II", 2, 3),
            b"\x01",
            struct.pack("<I", 4),
            b"\x00",
            _rgba(10, 20, 30, 255),
            _rgba(40, 50, 60, 255),
            _object_ref_tag(4),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CTextStyle": 5,
            "CSkFont": 1,
        },
    )

    assert isinstance(preview, TextStyle)
    assert preview.font_ref == 4
    assert preview.screen_font_ref == 4
    assert preview.arrow_type == 2
    assert preview.line_weight == 3
    assert preview.hide_out_of_plane is True
    assert preview.leader_type == 4
    assert preview.display_leader is False
    assert preview.color == 0xFF0A141E
    assert preview.screen_color == 0xFF28323C
    assert session.tell() == len(data)
