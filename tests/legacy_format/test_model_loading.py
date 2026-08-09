# SPDX-License-Identifier: MIT
"""End-to-end V8 loading and shared model construction."""

# ruff: noqa: F403, F405

from skppy import Vector3D

from ._fixtures import *


def test_parser_legacy_does_not_reintroduce_legacy_preview_types() -> None:
    """Keep the parser free of the removed parallel ``LegacyV8`` type graph."""
    modules = (parser_types, scene_pages)
    legacy_names = [name for module in modules for name in vars(module) if name.startswith("LegacyV8")]
    assert legacy_names == []


def test_supported_class_catalog_covers_complete_legacy_map() -> None:
    """Keep dispatch coverage synchronized with the observed V8 class map."""
    assert len(LEGACY_CLASS_SCHEMAS) == 55
    assert SUPPORTED_LEGACY_OBJECT_CLASSES == frozenset(LEGACY_CLASS_SCHEMAS)
    assert {"CCustomLineStyle", "CLayerGroup"} <= SUPPORTED_PRE_ZIP_OBJECT_CLASSES


def test_parse_legacy_header_and_version_map() -> None:
    """Parse the V8 envelope, version map, and archive offset."""
    data = _legacy_file_bytes(saved_path="C:/models/empty.skp")

    model = parse_legacy_bytes(data)
    legacy = model.legacy_archive

    assert model.header is not None
    assert legacy is not None
    assert model.header.product_name == "SketchUp Model"
    assert model.header.version_string == "{8.0.1}"
    assert model.header.version_tuple == (8, 0, 1)
    assert model.header.model_guid == bytes(range(16))
    assert legacy.saved_path == "C:/models/empty.skp"
    assert legacy.timestamp == 1_700_000_000
    assert legacy.format_version == SketchUpFormatVersion(8, 0, 1)
    assert legacy.archive_schema.version_for("CSketchUpModel") == 22
    assert legacy.saved_at.year == 2023
    assert [entry.class_name for entry in legacy.version_map] == [
        "CAttributeContainer",
        "CAttributeNamed",
        "CCamera",
        "CEntity",
        "CComponentBehavior",
        "CComponent",
        "CDrawingElement",
        "CMaterialManager",
        "CDefinitionList",
        "CRenderingOptions",
        "CShadowInfo",
        "CPageList",
        "CSketchCS",
        "CDimensionStyle",
        "CTextStyle",
        "CFontManager",
        "CSkpStyleManager",
        "CWatermarkManager",
        "CLayer",
        "CLayerManager",
        "CMaterial",
        "CEdge",
        "CVertex",
        "CSketchUpModel",
        "End-Of-Version-Map",
    ]
    assert [entry.version for entry in legacy.version_map] == [
        0,
        1,
        5,
        3,
        5,
        11,
        9,
        4,
        0,
        36,
        7,
        1,
        0,
        4,
        5,
        0,
        2,
        2,
        2,
        4,
        12,
        2,
        0,
        22,
        0,
    ]
    assert legacy.root_prefix is not None
    assert legacy.root_prefix.class_version == 22
    assert legacy.root_prefix.unknown_u32_a == 1
    assert legacy.root_prefix.unknown_u32_b == 0x4B0
    assert legacy.root_prefix.license_product_family == 0
    assert legacy.root_prefix.next_persistent_id is None
    assert legacy.root_prefix.thumbnail_object_tag is not None
    assert legacy.root_prefix.thumbnail_object_tag.kind == "null"
    assert legacy.root_prefix.redefine_thumbnail_on_save is True
    assert legacy.model_preamble_payload_start_offset is not None
    assert legacy.model_preamble_payload_start_offset == legacy.root_prefix.prefix_end_offset
    assert legacy.model_description == ""
    assert legacy.root_component_behavior is not None
    behavior = legacy.root_component_behavior
    assert behavior.class_version == 5
    assert behavior.entity_header.class_version == 3
    assert behavior.entity_header.attribute_container_tag is not None
    assert behavior.entity_header.attribute_container_tag.kind == "null"
    assert behavior.is_2d is False
    assert behavior.cuts_opening is False
    assert behavior.snap_to == 0
    assert behavior.always_face_camera is False
    assert behavior.shadows_face_sun is False
    assert behavior.no_scale_mask == 0
    assert legacy.options_manager is not None
    options_manager = legacy.options_manager
    assert len(options_manager.providers) == 1
    assert options_manager.providers[0].name == "PageOptions"
    assert options_manager.providers[0].keys == {
        "ShowTransition": "true",
        "TransitionTime": "1.5",
    }
    assert model.options_manager is options_manager
    assert legacy.options_manager_payload_end_offset is not None
    assert legacy.model_preamble_payload_end_offset is not None
    assert legacy.options_manager_payload_end_offset > legacy.model_preamble_payload_end_offset
    assert legacy.model_properties is not None
    model_properties = legacy.model_properties
    assert legacy.model_properties_payload_start_offset is not None
    assert legacy.model_properties_payload_start_offset > legacy.options_manager_payload_end_offset
    assert legacy.model_properties_object_tag is not None
    assert legacy.model_properties_object_tag.class_name == "CAttributeContainer"
    assert len(model_properties) == 1
    assert legacy.model_property_tags[0].class_name == "CAttributeNamed"
    attribute = model_properties[0]
    assert attribute.name == "ModelProperties"
    assert attribute.entries[0].key == "IsClassified"
    assert attribute.entries[0].bool_value is False
    assert legacy.camera_section_leading_tag is not None
    assert legacy.camera_section_leading_tag.kind == "null"
    assert legacy.root_camera is not None
    camera = legacy.root_camera
    assert legacy.root_camera_tag is not None
    assert legacy.root_camera_tag.kind == "new_class"
    assert legacy.root_camera_tag.class_name == "CCamera"
    assert camera.eye.to_tuple() == (10.0, 20.0, 30.0)
    assert camera.target.to_tuple() == (0.0, 0.0, 0.0)
    assert camera.up.to_tuple() == (0.0, 0.0, 1.0)
    assert camera.is_perspective is True
    assert camera.fov_is_height is False
    assert camera.legacy_flag is True
    assert camera.name == ""
    assert camera.is_2d is False
    assert legacy.rendering_options is not None
    rendering_options = legacy.rendering_options
    assert rendering_options.render_mode == 2
    assert rendering_options.edge_display_mode == 1
    assert rendering_options.draw_ground is True
    assert legacy.post_rendering_payload_start_offset is not None
    assert legacy.post_rendering_payload_start_offset == legacy.rendering_options_payload_end_offset
    assert legacy.obsolete_vertex_count == 0
    assert legacy.validity_check_performed == 1
    assert legacy.definition_tags == ()
    assert legacy.root_component_materials == ()
    assert legacy.layer_manager_payload_start_offset is not None
    assert legacy.layer_manager_payload_start_offset == legacy.layer_manager_start_offset
    assert len(legacy.archived_layers) == 1
    first_layer = legacy.archived_layers[0]
    assert first_layer.object_tag.kind == "new_class"
    assert first_layer.object_tag.class_name == "CLayer"
    assert first_layer.layer.name == "Layer0"
    assert first_layer.layer.visible is True
    assert first_layer.material is not None
    material = first_layer.material
    assert material.material.name == "Layer_Layer0"
    assert material.material.has_texture is False
    assert material.material.color == Color(255, 84, 84, 255)
    assert material.material_type == 0
    assert material.colorize_type == 0
    assert material.material.alpha == 1.0
    assert material.transparency == 0.5
    assert material.use_transparency is False
    assert first_layer.layer.page_behavior == 0
    assert legacy.active_layer_tag is not None
    assert legacy.active_layer_tag.kind == "object_ref"
    assert legacy.active_layer_tag.index == 10
    assert legacy.root_component_payload_start_offset is not None
    assert legacy.layer_manager_payload_start_offset is not None
    assert legacy.layer_manager_payload_end_offset is not None
    assert (
        legacy.root_component_payload_start_offset
        < legacy.layer_manager_payload_start_offset
        < legacy.layer_manager_payload_end_offset
    )
    assert legacy.root_entity_count == 0
    assert legacy.root_component_payload_end_offset is not None
    assert legacy.model_tail_payload_end_offset is not None
    assert data[legacy.model_tail_payload_end_offset :] == b"ARCHIVE"
    assert len(model.layers) == 1
    assert model.layers[0].name == "Layer0"
    assert model.layers[0].visible is True
    assert len(model.cameras) == 1
    assert model.cameras[0].eye.to_tuple() == (10.0, 20.0, 30.0)
    assert model.cameras[0].target.to_tuple() == (0.0, 0.0, 0.0)
    assert model.cameras[0].up.to_tuple() == (0.0, 0.0, 1.0)
    assert len(model.attribute_dictionaries) == 1
    assert model.attribute_dictionaries[0].name == "ModelProperties"
    assert model.attribute_dictionaries[0].entries[0].key == "IsClassified"
    assert model.attribute_dictionaries[0].entries[0].bool_value is False
    assert len(model.materials) == 0


def test_archive_schema_uses_file_version_map_and_rejects_missing_classes() -> None:
    """Resolve class schemas from the parsed file map, not a V8 constant table."""
    schema = ArchiveSchema.from_pairs(
        SketchUpFormatVersion(7, 1, 0),
        (("CComponentInstance", 4), ("CEdge", 2)),
    )

    assert schema.version_for("CComponentInstance") == 4
    assert schema.versions == {"CComponentInstance": 4, "CEdge": 2}
    with pytest.raises(ValueError, match=r"CViewPage.*7\.1\.0"):
        schema.version_for("CViewPage")


@pytest.mark.parametrize("major", range(3, 21))
def test_pre_zip_versions_cover_every_sdk_carchive_format(major: int) -> None:
    """Classify save formats through SU2020 as CArchive containers."""
    assert SketchUpFormatVersion(major).is_pre_zip is True


@pytest.mark.parametrize("major", [1, 2, 21, 26])
def test_versionless_and_invalid_versions_are_not_pre_zip(major: int) -> None:
    """Keep SketchUp 2021+ on the VFF/ZIP parser path."""
    assert SketchUpFormatVersion(major).is_pre_zip is False


def test_model_builder_replaces_archive_payload_with_shared_object() -> None:
    """Map a temporary archive payload to its final shared object identity."""
    payload = object()
    shared = object()
    builder = ModelBuilder(cast(Any, None), None, archive_objects=((7, payload),))

    assert builder.register_archive_value(payload, shared) == 7
    assert builder.objects[7] is shared
    assert builder.finalize() is builder.model


def test_model_builder_attaches_shared_metadata_without_rebuilding() -> None:
    """Attach and deduplicate shared metadata through the builder."""
    builder = ModelBuilder(cast(Any, None), None)
    camera = Camera(
        eye=Vector3D(1.0, 2.0, 3.0),
        target=Vector3D(0.0, 0.0, 0.0),
        up=Vector3D(0.0, 0.0, 1.0),
    )
    rendering = RenderingOptions(render_mode=2)
    shadow = ShadowInfo(latitude=45.0)
    axes = ModelViewAxes(origin=(4.0, 5.0, 6.0))
    font = Font(face_name="Arial", point_size=12)
    style = StyleDescriptor(display_name="Default")
    registry = StylesRegistry(active_style_ref=7, selected_style_dirty=True)
    watermark_manager = WatermarkManager(watermarks=[Watermark(name="Overlay")], serialized_count=1)
    text_style = TextStyle(font_ref=4)
    dimension_style = DimensionStyle(font_ref=4)
    background = PageBackgroundImage(path="background.png", opacity=0.5)
    options_manager = OptionsManager(providers=[OptionsProvider(name="PageOptions", keys={"Show": "true"})])

    builder.apply_metadata(
        camera=camera,
        rendering_options=rendering,
        shadow_info=shadow,
        model_view_axes=axes,
    )
    builder.add_fonts((font, font))
    builder.apply_styles_registry(registry)
    builder.apply_watermark_manager(watermark_manager)
    builder.apply_annotation_styles(text_style=text_style, dimension_style=dimension_style)
    builder.apply_background_image(background)
    builder.apply_options_manager(options_manager)
    builder.add_styles((style, style))

    assert builder.model.cameras == [camera]
    assert builder.model.rendering_options is rendering
    assert builder.model.shadow_info is shadow
    assert builder.model.model_view_axes is axes
    assert builder.model.fonts == [font]
    assert builder.model.styles_registry is not None
    assert builder.model.styles_registry is registry
    assert builder.model.styles_registry.styles == [style]
    assert builder.model.watermark_manager is watermark_manager
    assert builder.model.text_style is text_style
    assert builder.model.dimension_style is dimension_style
    assert builder.model.background_image is background
    assert builder.model.options_manager is options_manager


def test_read_root_model_prefix_consumes_inline_dib_thumbnail() -> None:
    """SketchUp 8 app files can embed a CDib thumbnail in the model prefix."""
    data = b"".join(
        [
            struct.pack("<I", 1),
            struct.pack("<I", 0x4B0),
            struct.pack("<I", 1),
            _new_class_tag("CDib", schema=3),
            _dib_preview_payload_bytes(),
            b"\x01",
        ]
    )

    prefix = read_root_model_prefix(io.BytesIO(data), model_class_version=22)

    assert prefix.thumbnail_object_tag is not None
    assert prefix.thumbnail_object_tag.class_name == "CDib"
    assert prefix.thumbnail is not None
    assert prefix.thumbnail.image_format == 4
    assert prefix.thumbnail.image_bytes == b"PNG"
    assert prefix.redefine_thumbnail_on_save is True
    assert prefix.prefix_end_offset == len(data)


def test_read_camera_section_consumes_leading_inline_dib() -> None:
    """SketchUp 8 app files can embed another CDib before the root camera."""
    data = b"".join(
        [
            _class_ref_tag(3),
            _dib_preview_payload_bytes(),
            _new_class_tag("CCamera", schema=5),
            _camera_payload_bytes(),
        ]
    )

    leading_tag, camera_tag, camera, _, leading_dib = read_camera_section(io.BytesIO(data), camera_class_version=5)

    assert leading_tag.kind == "class_ref"
    assert leading_dib is not None
    assert leading_dib.image_bytes == b"PNG"
    assert camera_tag.class_name == "CCamera"
    assert camera.eye.to_tuple() == (10.0, 20.0, 30.0)
    assert camera.name == ""


def test_post_rendering_stops_at_root_component_boundary() -> None:
    """Leave the root component bytes to the stateful component reader."""
    data = _post_rendering_model_data_bytes()
    stream = io.BytesIO(data)

    post_rendering = read_post_rendering_model_data(
        stream,
        model_class_version=22,
    )

    assert post_rendering.payload_start_offset == 0
    assert post_rendering.obsolete_vertex_count == 0
    assert post_rendering.validity_check_performed == 1
    assert post_rendering.payload_end_offset == 8
    assert stream.tell() == 8


def test_parse_legacy_maps_textured_root_material() -> None:
    """Map decoded V8 material previews into shared Material/Texture objects."""
    data = _legacy_file_bytes(
        saved_path="textured.skp",
        root_entity_count=1,
        root_entity_payload=b"".join(
            [
                _new_class_tag("CMaterial", schema=12),
                _material_preview_bytes(
                    name="Textured",
                    texture_payload=_texture_preview_payload_bytes(),
                ),
            ]
        ),
    )

    model = parse_legacy_bytes(data)

    assert len(model.layers) == 1
    materials_by_name = {material.name: material for material in model.materials}
    assert set(materials_by_name) == {"Textured"}
    material = materials_by_name["Textured"]
    assert model.legacy_archive is not None
    archived_material = next(
        value for _, value in model.legacy_archive.archive_objects if isinstance(value, MaterialState)
    )
    assert material is archived_material.material
    assert material.has_texture is True
    assert material.texture is not None
    assert material.texture.filename == "texture.png"
    assert material.texture.x_scale == 12.0
    assert material.texture.y_scale == 24.0
    assert material.texture.data == b"PNG"


def test_parse_legacy_extended_utf16_string() -> None:
    """Parse the extended old string length form used by long saved paths."""
    long_path = "C:/" + ("nested/" * 40) + "model.skp"

    model = parse_legacy_bytes(_legacy_file_bytes(saved_path=long_path))

    assert model.legacy_archive is not None
    assert model.legacy_archive.saved_path == long_path


def test_read_legacy_utf16_string_supports_u32_length() -> None:
    """Decode the MFC length form used by very large attribute strings."""
    text = "x" * 65_536
    data = b"\xff\xfe\xff\xff\xff\xff" + struct.pack("<I", len(text))
    data += text.encode("utf-16le")

    assert LegacyArchiveReader(io.BytesIO(data)).read_legacy_utf16_string("large") == text


def test_load_dispatches_non_zip_file_to_legacy_parser(tmp_path: Path) -> None:
    """Load a non-ZIP legacy file through the public ``skppy.load`` entry point."""
    filepath = tmp_path / "legacy_archive.skp"
    filepath.write_bytes(_legacy_file_bytes(saved_path="legacy_archive.skp"))

    model = skppy.load(str(filepath))

    assert model.header is not None
    assert model.header.version_string == "{8.0.1}"
    assert model.legacy_archive is not None
    assert model.legacy_archive.archive_offset < filepath.stat().st_size
    assert model.legacy_archive.root_prefix is not None
    assert model.legacy_archive.model_preamble_payload_start_offset is not None
    assert model.legacy_archive.options_manager is not None
    assert model.legacy_archive.model_properties is not None
    assert model.legacy_archive.root_camera is not None
    assert model.legacy_archive.rendering_options is not None
    assert model.rendering_options is not None
    assert model.rendering_options.render_mode == 2
    assert model.rendering_options.edge_display_mode == 1
    assert model.rendering_options.draw_ground is True
    assert model.legacy_archive.post_rendering_payload_start_offset is not None
    assert model.legacy_archive.archived_layers
    assert model.legacy_archive.root_component_payload_start_offset is not None
