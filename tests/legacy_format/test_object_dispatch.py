# SPDX-License-Identifier: MIT
"""Dispatch for geometry, material, layer, and metadata objects."""

# ruff: noqa: F403, F405

from ._fixtures import *


def test_read_supported_object_dispatches_edge_curve() -> None:
    """Dispatch CEdge with an inline CCurve payload."""
    data = _edge_preview_with_curve_bytes()
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(session, {"CEntity": 3, "CEdge": 2, "CVertex": 0, "CCurve": 4})

    assert isinstance(preview, EdgeState)
    assert preview.curve_tag is not None
    assert preview.curve_tag.class_name == "CCurve"
    assert isinstance(preview.curve, Curve)
    assert preview.curve.is_polygon is True
    assert len(preview.curve.edge_ids) == 3
    assert session.tell() == len(data)


def test_read_supported_object_resolves_edge_vertex_refs() -> None:
    """Resolve CEdge vertex object refs without consuming new vertex payloads."""
    data = b"".join(
        [
            _new_class_tag("CEdge", schema=2),
            _drawing_element_payload_bytes(),
            _new_class_tag("CVertex", schema=0),
            b"\x00\x00",
            struct.pack("<3d", 0.0, 0.0, 0.0),
            _class_ref_tag(3),
            b"\x00\x00",
            struct.pack("<3d", 10.0, 0.0, 0.0),
            b"\x00\x00",
            _class_ref_tag(1),
            _drawing_element_payload_bytes(),
            _object_ref_tag(5),
            _class_ref_tag(3),
            b"\x00\x00",
            struct.pack("<3d", 20.0, 0.0, 0.0),
            b"\x00\x00",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    first = read_supported_object(session, {"CEntity": 3, "CEdge": 2, "CVertex": 0})
    second = read_supported_object(session, {"CEntity": 3, "CEdge": 2, "CVertex": 0})

    assert isinstance(first, EdgeState)
    assert isinstance(second, EdgeState)
    assert second.start_vertex is first.end_vertex
    assert second.end_vertex.position.to_tuple() == (20.0, 0.0, 0.0)
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_arc_curve() -> None:
    """Dispatch CArcCurve v1 with its CCurve base and CArc3d payload."""
    data = b"".join(
        [
            _new_class_tag("CArcCurve", schema=1),
            b"\x00\x00",
            b"\x00",
            struct.pack("<I", 4),
            _arc3d_preview_payload_bytes(),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(session, {"CEntity": 3, "CCurve": 4, "CArcCurve": 1})

    assert isinstance(preview, ArcCurve)
    assert len(preview.edge_ids) == 4
    assert preview.center == (1.0, 2.0, 3.0)
    assert preview.normal == (0.0, 0.0, 1.0)
    assert preview.radius == 1.0
    assert preview.start_angle == 0.25
    assert preview.end_angle == 1.25
    assert session.tell() == len(data)


def test_read_supported_object_returns_refs() -> None:
    """Return object-reference handles without trying to read payload bytes."""
    session = LegacyArchiveSession(io.BytesIO(_object_ref_tag(2)))
    session.register_implicit_object("CSketchUpModel", 22)

    preview = read_supported_object(session, {"CEntity": 3})

    assert isinstance(preview, ArchiveObjectHandle)
    assert preview.kind == "object_ref"
    assert preview.class_name == "CSketchUpModel"


def test_read_supported_object_dispatches_nested_face_graph() -> None:
    """Dispatch CFace with inline CLoop, CEdgeUse, CEdge, and CVertex objects."""
    data = _nested_face_preview_bytes()
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CFace": 3,
            "CLoop": 1,
            "CEdgeUse": 1,
            "CEdge": 2,
            "CVertex": 0,
        },
    )

    assert isinstance(preview, Face)
    assert preview.plane == (0.0, 0.0, 1.0, 0.0)
    assert len(preview.outer_loop.edge_uses) == 1
    assert preview.outer_loop.edge_uses[0].reversed is False
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_material() -> None:
    """Dispatch a non-textured CMaterial object through the archive session."""
    data = b"".join(
        [
            _new_class_tag("CMaterial", schema=12),
            _material_preview_bytes(name="Red"),
            _class_ref_tag(1),
            _material_preview_bytes(name="Green"),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    first = read_supported_object(session, {"CEntity": 3, "CMaterial": 12})
    second = read_supported_object(session, {"CEntity": 3, "CMaterial": 12})

    assert isinstance(first, MaterialState)
    assert first.material.name == "Red"
    assert first.material.color == Color(255, 84, 84, 255)
    assert first.material.has_texture is False
    assert isinstance(second, MaterialState)
    assert second.material.name == "Green"
    assert second.material.alpha == 1.0
    assert second.transparency == 0.5
    assert second.use_transparency is False
    assert session.tell() == len(data)


def test_material_applies_enabled_transparency_as_opacity() -> None:
    """Convert CMaterial transparency to public opacity only when enabled."""
    data = b"".join(
        [
            _new_class_tag("CMaterial", schema=12),
            _material_preview_bytes(
                name="Glass",
                transparency=0.4,
                use_transparency=True,
            ),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    material = read_supported_object(session, {"CEntity": 3, "CMaterial": 12})

    assert isinstance(material, MaterialState)
    assert material.material.alpha == pytest.approx(0.6)
    assert material.transparency == 0.4
    assert material.use_transparency is True


def test_read_supported_object_dispatches_texture_with_dib() -> None:
    """Dispatch CTexture v6 and its referenced CDib image payload."""
    data = b"".join(
        [
            _new_class_tag("CTexture", schema=6),
            _texture_preview_payload_bytes(),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(session, {"CEntity": 3, "CTexture": 6, "CDib": 3})

    assert isinstance(preview, Texture)
    assert preview.x_scale == 12.0
    assert preview.y_scale == 24.0
    assert preview.filename == "texture.png"
    assert preview.data == b"PNG"
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_textured_material() -> None:
    """Dispatch CMaterial v12 with an inline CTexture payload."""
    data = b"".join(
        [
            _new_class_tag("CMaterial", schema=12),
            _material_preview_bytes(
                name="Textured",
                texture_payload=_texture_preview_payload_bytes(),
            ),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(session, {"CEntity": 3, "CMaterial": 12, "CTexture": 6, "CDib": 3})

    assert isinstance(preview, MaterialState)
    assert preview.material.name == "Textured"
    assert preview.material.has_texture is True
    assert isinstance(preview.material.texture, Texture)
    assert preview.material.texture.filename == "texture.png"
    assert preview.material.texture.data == b"PNG"
    assert preview.used_by_layer is True
    assert preview.material_type == 0
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_material_manager() -> None:
    """Dispatch CMaterialManager v4 with material objects and current ref."""
    data = b"".join(
        [
            _new_class_tag("CMaterialManager", schema=4),
            b"\x00\x00",
            struct.pack("<I", 2),
            _new_class_tag("CMaterial", schema=12),
            _material_preview_bytes(name="Red"),
            _class_ref_tag(3),
            _material_preview_bytes(name="Green"),
            _object_ref_tag(4),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CMaterialManager": 4,
            "CMaterial": 12,
            "CTexture": 6,
            "CDib": 3,
        },
    )

    assert isinstance(preview, tuple)
    assert [record.material.name for record in preview] == [
        "Red",
        "Green",
    ]
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_layer() -> None:
    """Dispatch CLayer v2 with its inline material payload."""
    data = b"".join(
        [
            _new_class_tag("CLayer", schema=2),
            b"\x00\x00",
            _legacy_string("Layer 1"),
            b"\x01",
            _material_preview_bytes(name="Layer Material"),
            struct.pack("<I", 42),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CLayer": 2,
            "CMaterial": 12,
            "CTexture": 6,
            "CDib": 3,
        },
    )

    assert isinstance(preview, LayerState)
    assert preview.layer.name == "Layer 1"
    assert preview.layer.visible is False
    assert preview.material is not None
    assert preview.material.material.name == "Layer Material"
    assert preview.layer.page_behavior == 42
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_layer_with_line_style() -> None:
    """CLayer v3 appends a custom-line-style archive reference."""
    data = b"".join(
        [
            _new_class_tag("CLayer", schema=3),
            b"\x00\x00",
            _legacy_string("Layer 1"),
            b"\x00",
            _material_preview_bytes(name="Layer Material"),
            struct.pack("<I", 42),
            b"\x00\x00",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CLayer": 3,
            "CMaterial": 12,
            "CTexture": 6,
            "CDib": 3,
        },
    )

    assert isinstance(preview, LayerState)
    assert preview.layer.page_behavior == 42
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_layer_manager() -> None:
    """Dispatch CLayerManager v4 with layer objects and current-layer ref."""
    data = b"".join(
        [
            _new_class_tag("CLayerManager", schema=4),
            b"\x00\x00",
            struct.pack("<I", 2),
            _new_class_tag("CLayer", schema=2),
            _layer_preview_payload_bytes("Layer 1", hidden=False, flags=10),
            _class_ref_tag(3),
            _layer_preview_payload_bytes("Layer 2", hidden=True, flags=20),
            _object_ref_tag(4),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CLayerManager": 4,
            "CLayer": 2,
            "CMaterial": 12,
            "CTexture": 6,
            "CDib": 3,
        },
    )

    assert isinstance(preview, tuple)
    layers, active_layer_tag, folders, _, _ = preview
    assert len(layers) == 2
    assert layers[0].layer.name == "Layer 1"
    assert [record.layer.name for record in layers] == [
        "Layer 1",
        "Layer 2",
    ]
    assert layers[1].layer.visible is False
    assert active_layer_tag is not None
    assert active_layer_tag.kind == "object_ref"
    assert active_layer_tag.index == 4
    assert folders == ()
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_su2020_layer_group() -> None:
    """Decode a tagged layer folder directly into the shared data class."""
    data = b"".join(
        [
            _new_class_tag("CLayerGroup", schema=3),
            b"\x00\x00\x01\x01",
            _legacy_string("Architecture"),
            struct.pack("<II", 0, 0),
            b"\x01\x00",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data), file_version="20.0.1")

    folder = read_supported_object(
        session,
        {"CEntity": 6, "CLayerGroup": 3},
    )

    assert isinstance(folder, LayerFolder)
    assert folder.name == "Architecture"
    assert folder.visible is True
    assert folder.child_folders == []
    assert folder.child_layer_ids == []
    assert session.tell() == len(data)


def test_layer_manager_v7_reads_implicit_root_group() -> None:
    """Expose children of SU2020's implicit root group as public folders."""
    child = b"".join(
        [
            _new_class_tag("CLayerGroup", schema=3),
            b"\x00\x00\x01\x03",
            _legacy_string("Architecture"),
            struct.pack("<II", 0, 0),
            b"\x01\x00",
        ]
    )
    data = b"".join(
        [
            _new_class_tag("CLayerManager", schema=7),
            b"\x00\x00\x01\x01",
            struct.pack("<I", 0),
            b"\x00\x00\x01\x02",
            _legacy_string("Root"),
            struct.pack("<I", 1),
            child,
            struct.pack("<I", 0),
            b"\x01\x01",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data), file_version="20.0.1")

    layers, active, folders, _, _ = read_supported_object(
        session,
        {"CEntity": 6, "CLayerManager": 7, "CLayerGroup": 3},
    )

    assert layers == ()
    assert active is None
    assert [folder.name for folder in folders] == ["Architecture"]
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_su2019_line_style() -> None:
    """Consume SU2019's duplicate entity body and schema-2 style fields."""
    data = b"".join(
        [
            _new_class_tag("CCustomLineStyle", schema=4),
            b"\x00\x00\x01\x06",
            b"\x00\x00\x01\x06",
            _legacy_string("Dash"),
            _legacy_string("12.0, -6.0"),
            struct.pack("<3d", 1.0, 2.0, 1.0),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data), file_version="19.0.1")

    style = read_supported_object(
        session,
        {"CEntity": 6, "CCustomLineStyle": 2},
    )

    assert isinstance(style, LineStyle)
    assert style.name == "Dash"
    assert style.dash_pattern == "12.0, -6.0"
    assert style.line_width_points == 1.0
    assert style.stipple_scale == 2.0
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_attribute_container() -> None:
    """Dispatch CAttributeContainer with a nested CAttributeNamed dictionary."""
    data = b"".join(
        [
            _new_class_tag("CAttributeContainer", schema=0),
            b"\x00\x00",
            _new_class_tag("CAttributeNamed", schema=1),
            _named_attribute_payload_bytes("ModelProperties", "IsClassified"),
            b"\x00\x00",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CAttributeContainer": 0,
            "CAttributeNamed": 1,
        },
    )

    assert isinstance(preview, tuple)
    assert len(preview) == 5
    assert preview[0].class_name == "CAttributeContainer"
    assert preview[1][0].class_name == "CAttributeNamed"
    assert len(preview[2]) == 1
    attribute = preview[2][0]
    assert isinstance(attribute, AttributeDictionary)
    assert attribute.name == "ModelProperties"
    assert attribute.entries[0].key == "IsClassified"
    assert attribute.entries[0].bool_value is True
    assert session.tell() == len(data)


def test_entity_header_records_its_attribute_container_owner() -> None:
    """Retain ownership while recursively decoding an inline container."""
    data = b"".join(
        [
            _new_class_tag("CVertex", schema=0),
            _new_class_tag("CAttributeContainer", schema=0),
            b"\x00\x00",
            _new_class_tag("CAttributeNamed", schema=1),
            _named_attribute_payload_bytes("VertexProperties", "Enabled"),
            b"\x00\x00",
            struct.pack("<3d", 1.0, 2.0, 3.0),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    vertex = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CVertex": 0,
            "CAttributeContainer": 0,
            "CAttributeNamed": 1,
        },
    )

    owner_index = next(index for index, payload in session.objects.items() if payload is vertex)
    container_index = next(
        index
        for index, payload in session.objects.items()
        if isinstance(payload, tuple) and len(payload) == 5 and payload[0].class_name == "CAttributeContainer"
    )
    assert session.attribute_container_indices_by_owner == {owner_index: container_index}


def test_attribute_container_preserves_face_texture_coordinate_entry() -> None:
    """Keep technical UV entries addressable even though they are not dictionaries."""
    data = b"".join(
        [
            _new_class_tag("CAttributeContainer", schema=0),
            b"\x00\x00",
            _new_class_tag("CFaceTextureCoords", schema=4),
            _face_texture_coords_payload_bytes(),
            b"\x00\x00",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    container = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CAttributeContainer": 0,
            "CFaceTextureCoords": 4,
        },
    )

    assert len(container[1]) == 1
    texture_tag = container[1][0]
    assert texture_tag.kind == "object_ref"
    assert texture_tag.class_name == "CFaceTextureCoords"
    assert session.index_table.resolve_object(texture_tag.index).class_name == ("CFaceTextureCoords")
    assert len(container[2]) == 0
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_attribute() -> None:
    """Dispatch the standalone CAttribute v0 base payload."""
    data = b"".join(
        [
            _new_class_tag("CAttribute", schema=0),
            b"\x00\x00",
            struct.pack("<I", 7),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CAttribute": 0,
        },
    )

    assert preview == 7
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_component_behavior() -> None:
    """Dispatch CComponentBehavior v5 through the shared object path."""
    data = b"".join(
        [
            _new_class_tag("CComponentBehavior", schema=5),
            _component_behavior_bytes(
                is_2d=True,
                cuts_opening=True,
                snap_to=2,
                always_face_camera=True,
                shadows_face_sun=True,
                no_scale_mask=0x15,
            ),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CComponentBehavior": 5,
        },
    )

    assert isinstance(preview, ComponentBehaviorState)
    assert preview.object_tag is not None
    assert preview.object_tag.class_name == "CComponentBehavior"
    assert preview.is_2d is True
    assert preview.cuts_opening is True
    assert preview.snap_to == 2
    assert preview.always_face_camera is True
    assert preview.shadows_face_sun is True
    assert preview.no_scale_mask == 0x15
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_camera() -> None:
    """Dispatch CCamera v5 through the shared object path."""
    data = b"".join(
        [
            _new_class_tag("CCamera", schema=5),
            _camera_payload_bytes(),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(session, {"CCamera": 5})

    assert isinstance(preview, Camera)
    assert preview.eye.to_tuple() == (10.0, 20.0, 30.0)
    assert preview.target.to_tuple() == (0.0, 0.0, 0.0)
    assert preview.name == ""
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_rendering_options() -> None:
    """Dispatch CRenderingOptions v36 through the shared object path."""
    data = b"".join(
        [
            _new_class_tag("CRenderingOptions", schema=36),
            _rendering_options_bytes(),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(session, {"CEntity": 3, "CRenderingOptions": 36})

    assert isinstance(preview, RenderingOptions)
    assert preview.render_mode == 2
    assert preview.edge_display_mode == 1
    assert preview.draw_ground is True
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_page_list() -> None:
    """Dispatch CPageList v1 page-reference arrays."""
    data = b"".join(
        [
            _new_class_tag("CPageList", schema=1),
            b"\x00\x00",
            struct.pack("<I", 2),
            b"\x00\x00",
            b"\x00\x00",
            b"\x00\x00",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CPageList": 1,
        },
    )

    assert preview == ()
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_sketchup_page() -> None:
    """Dispatch CSketchUpPage v1 scene identity metadata."""
    data = b"".join(
        [
            _new_class_tag("CSketchUpPage", schema=1),
            b"\x00\x00",
            _legacy_string("Scene 1"),
            _legacy_string("Base page"),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CSketchUpPage": 1,
        },
    )

    assert isinstance(preview, Scene)
    assert preview.name == "Scene 1"
    assert preview.description == "Base page"
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_view_page() -> None:
    """Dispatch CViewPage v12 scene flags and finite metadata tail."""
    data = b"".join(
        [
            _new_class_tag("CViewPage", schema=12),
            b"\x00\x00",
            _legacy_string("Scene 1"),
            _legacy_string("View page"),
            struct.pack("<I", 0x7F),
            _new_class_tag("CCamera", schema=5),
            _camera_payload_bytes(),
            _rendering_options_bytes(),
            _style_preview_payload_bytes(
                guid=bytes(range(16)),
                display_name="Scene Style",
                file_name="scene.style",
                option_count=0,
            ),
            _shadow_info_payload_bytes(),
            b"\x01",
            _drawing_element_payload_bytes(),
            _sketch_cs_payload_bytes(),
            b"\x00",
            struct.pack("<I", 2),
            _object_ref_tag(21),
            _object_ref_tag(22),
            struct.pack("<I", 1),
            _object_ref_tag(31),
            struct.pack("<I", 1),
            _object_ref_tag(41),
            b"\x01",
            struct.pack("<d", 1.5),
            struct.pack("<d", 2.5),
            b"\x00\x00",
            b"\x01",
            b"\x01",
            b"\x01",
            struct.pack("<I", 4),
            b"PNG!",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CDrawingElement": 9,
            "CCamera": 5,
            "CSketchUpPage": 1,
            "CViewPage": 12,
        },
    )

    assert isinstance(preview, SceneState)
    assert preview.object_tag.class_name == "CViewPage"
    assert preview.scene.name == "Scene 1"
    assert preview.scene.description == "View page"
    assert preview.scene.flags == 0x7F
    assert preview.camera_tag is not None
    assert preview.camera_tag.class_name == "CCamera"
    assert preview.scene.camera is not None
    assert preview.scene.camera.eye.to_tuple() == (10.0, 20.0, 30.0)
    assert preview.rendering_options is not None
    assert preview.rendering_options.render_mode == 2
    assert preview.rendering_options.edge_display_mode == 1
    assert preview.style_tag is not None
    assert preview.style_tag.class_name == "CSkpStyle"
    assert preview.style_tag.index is not None
    assert preview.shadow_info is not None
    assert preview.shadow_info.city == b"Boulder (CO)"
    assert preview.shadow_info_display_shadows is True
    assert preview.axes is not None
    assert preview.axes.z_axis == (0.0, 0.0, 1.0)
    assert preview.axes_display is False
    assert [tag.index for tag in preview.hidden_entity_tags] == [21, 22]
    assert [tag.index for tag in preview.hidden_layer_tags] == [31]
    assert [tag.index for tag in preview.active_section_plane_tags] == [41]
    assert preview.scene.show_in_slideshow is True
    assert preview.transition_time == 1.5
    assert preview.delay_time == 2.5
    assert preview.background_image_tag is not None
    assert preview.background_image_tag.kind == "null"
    assert preview.scene.display_background_image is True
    assert preview.image_rep_present is True
    assert preview.image_rep is not None
    assert preview.image_rep == b"PNG!"
    assert preview.use_camera is True
    assert preview.use_rendering_options is True
    assert preview.use_shadow_info is True
    assert preview.use_axes is True
    assert preview.use_hidden is True
    assert preview.use_layer_visibility is True
    assert preview.use_section_planes is True
    assert session.tell() == len(data)


@pytest.mark.parametrize("class_version", [6, 9, 11, 12, 13])
def test_view_page_tail_is_selected_by_class_version(class_version: int) -> None:
    """Consume only the scene fields introduced by each observed schema."""
    tail = [b"\x01"]
    if 6 <= class_version <= 10:
        tail.append(b"\x00")
    if class_version >= 8:
        tail.append(struct.pack("<d", 1.5))
    if class_version >= 9:
        tail.append(struct.pack("<d", 2.5))
    if class_version > 9:
        tail.append(b"\x00\x00")
    if class_version >= 12:
        tail.extend((b"\x00", b"\x00"))
    data = b"".join(
        [
            _new_class_tag("CViewPage", schema=class_version),
            b"\x00\x00",
            _legacy_string("Scene"),
            _legacy_string("Versioned"),
            struct.pack("<I", 0),
            *tail,
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    scene = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CSketchUpPage": 1,
            "CViewPage": class_version,
        },
    )

    assert isinstance(scene, SceneState)
    assert scene.scene.show_in_slideshow is True
    assert scene.transition_time == (1.5 if class_version >= 8 else -1.0)
    assert scene.delay_time == (2.5 if class_version >= 9 else -1.0)
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_sketch_cs() -> None:
    """Dispatch CSketchCS v0 coordinate-system vectors."""
    data = b"".join(
        [
            _new_class_tag("CSketchCS", schema=0),
            _drawing_element_payload_bytes(),
            struct.pack(
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
            ),
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {"CEntity": 3, "CDrawingElement": 9, "CSketchCS": 0},
    )

    assert isinstance(preview, ModelViewAxes)
    assert preview.origin == (10.0, 10.0, 10.0)
    assert preview.x_axis == (2**-0.5, 2**-0.5, 0.0)
    assert preview.y_axis == (-(2**-0.5), 2**-0.5, 0.0)
    assert preview.z_axis == (0.0, 0.0, 1.0)
    assert session.tell() == len(data)


def test_read_supported_object_dispatches_shadow_info() -> None:
    """Dispatch CShadowInfo v7 shadow/geolocation metadata."""
    data = b"".join(
        [
            _new_class_tag("CShadowInfo", schema=7),
            b"\x00\x00",
            struct.pack("<I", 1_700_000_000),
            b"\x01",
            _legacy_string("USA"),
            _legacy_string("Boulder (CO)"),
            struct.pack("<d", -120.0),
            struct.pack("<d", 45.0),
            struct.pack("<d", -7.0),
            struct.pack("<3d", 0.0, 1.0, 0.0),
            b"\x01\x00\x01\x00",
            struct.pack("<i", 80),
            struct.pack("<i", 20),
            b"\x01",
        ]
    )
    session = LegacyArchiveSession(io.BytesIO(data))

    preview = read_supported_object(
        session,
        {
            "CEntity": 3,
            "CShadowInfo": 7,
        },
    )

    assert isinstance(preview, ShadowInfo)
    assert preview.time == 1_700_000_000
    assert preview.daylight_savings is True
    assert preview.city == b"Boulder (CO)"
    assert preview.longitude == -120.0
    assert preview.latitude == 45.0
    assert preview.timezone_offset == -7.0
    assert preview.north_direction == (0.0, 1.0, 0.0)
    assert (
        preview.display_shadows,
        preview.display_north,
        preview.display_on_all_faces,
        preview.display_on_ground_plane,
    ) == (
        True,
        False,
        True,
        False,
    )
    assert preview.light == 80
    assert preview.dark == 20
    assert preview.use_sun_for_all_shading is True
    assert session.tell() == len(data)
