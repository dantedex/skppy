# SPDX-License-Identifier: MIT
"""Build the shared public model from a pre-ZIP SketchUp object graph.

The pipeline reads the envelope, seeds one archive identity table, decodes the
root component and model tail, then resolves archive references into the same
:class:`~skppy.data_structure.model.Model` classes used by the modern parser.
Call :func:`skppy.load` for automatic modern/legacy dispatch; the functions in
this module are useful when a caller already knows that a stream is pre-ZIP.
"""

from __future__ import annotations

from typing import BinaryIO, TypeVar, cast

from ..load_limits import LoadLimits
from ..data_structure.construction import ShadowInfo
from ..data_structure.entities import Face
from ..data_structure.model import Model
from ..data_structure.model_metadata import (
    DimensionStyle,
    Font,
    ModelViewAxes,
    OptionsManager,
    StyleDescriptor,
    StylesRegistry,
    TextStyle,
    WatermarkManager,
)

from .attribute_readers import (
    read_attribute_container_preview as read_attribute_container,
)
from .attribute_builder import attribute_dictionaries_by_owner_id, attribute_dictionaries_for_container_index
from .camera_payloads import read_root_camera_section
from .base_payloads import (
    read_model_payload_preamble,
    read_rendering_options,
    read_root_model_prefix,
)
from .parser_types import DibState, EdgeState, RootModelPrefixState, SceneState
from .binary import (
    ArchiveObjectTag,
    LegacyArchiveBuffer,
)
from .options_payloads import read_options_manager
from .root_payloads import read_post_rendering_model_data
from .session import LegacyArchiveSession

from .object_dispatch import create_object_read_context
from .model_tail import ModelTailState, read_model_tail
from .recovery import (
    POST_LAYER_HEURISTIC_SCAN_BYTES,
    scan_font_previews,
    scan_post_layer_previews,
    scan_style_previews,
)
from .envelope import ParsedLegacyEnvelope, VersionMapEntry, read_legacy_envelope
from .schema import ArchiveSchema
from .model_builder import ModelBuilder
from .entity_builder import index_archive_object_identities, populate_root_entities
from .extensions import apply_legacy_extensions
from .scene_builder import populate_scenes
from .scene_pages import RecoveredSceneState
from .provenance import ArchiveProvenance
from .material_builder import (
    apply_renderer_materials,
    collect_materials,
    material_ids_by_archive_index,
    populate_layers,
    populate_materials,
)
from .component_builder import populate_definitions
from .component_body import ComponentBodyState
from .root_component import read_root_component

_T = TypeVar("_T")


def _first_archive_object(provenance: ArchiveProvenance, object_type: type[_T]) -> _T | None:
    """Return the first directly decoded archive object of one public type."""
    return next(
        (value for _, value in provenance.archive_objects if isinstance(value, object_type)),
        None,
    )


def parse_legacy_model(
    stream: BinaryIO, *, import_vray_materials: bool = False, limits: LoadLimits | None = None
) -> Model:
    """
    Parse a pre-ZIP SketchUp stream into the shared :class:`Model`.

    Class layouts are selected from the file's product version and
    ``CVersionMap``. Archive provenance remains available through
    ``model.legacy_archive`` while semantic data is returned in the shared
    model classes used by the modern parser.
    """
    # First preserve the archive-level view (offsets, handles, and unresolved
    # ownership); the builders below normalize that view into the same Model
    # graph returned by the modern ZIP parser.
    legacy_header = parse_legacy_header(stream)
    builder = ModelBuilder(
        legacy_header.to_skp_header(),
        legacy_header,
        archive_objects=legacy_header.archive_objects,
    )
    model = builder.model
    # A metadata object decoded through the archive table is authoritative.
    # Header/tail copies are fallbacks for versions that serialized it inline.
    direct_shadow_info = _first_archive_object(legacy_header, ShadowInfo)
    direct_model_view_axes = _first_archive_object(legacy_header, ModelViewAxes)
    builder.apply_metadata(
        camera=(legacy_header.root_camera),
        rendering_options=legacy_header.rendering_options,
        shadow_info=direct_shadow_info or legacy_header.shadow_info,
        model_view_axes=direct_model_view_axes or legacy_header.model_view_axes,
    )
    builder.apply_options_manager(legacy_header.options_manager)
    builder.add_attribute_dictionaries(legacy_header.model_properties)
    populate_layers(model, legacy_header)
    # MaterialState retains archive identity while Material is the public
    # object. Registering the replacement lets later object references resolve
    # to the exact Material instance installed on the model.
    material_states = collect_materials(legacy_header)
    populate_materials(model, material_states)
    materials_by_name = {material.name: material for material in model.materials}
    for state in material_states:
        material = materials_by_name.get(state.material.name)
        if material is not None:
            builder.register_archive_value(state, material)
    material_id_by_object_index = material_ids_by_archive_index(model, legacy_header, material_states=material_states)
    objects_by_archive_index = dict(legacy_header.archive_objects)
    populate_scenes(
        model,
        legacy_header.archived_scenes,
        legacy_header.scene_previews,
    )
    builder.add_fonts(
        (
            *legacy_header.font_previews,
            *(value for _, value in legacy_header.archive_objects if isinstance(value, Font)),
        )
    )
    builder.apply_styles_registry(legacy_header.styles_registry or _first_archive_object(legacy_header, StylesRegistry))
    builder.normalize_style_references(legacy_header.archive_objects)
    builder.apply_watermark_manager(
        legacy_header.watermark_manager or _first_archive_object(legacy_header, WatermarkManager)
    )
    builder.apply_annotation_styles(
        text_style=legacy_header.text_style or _first_archive_object(legacy_header, TextStyle),
        dimension_style=legacy_header.dimension_style or _first_archive_object(legacy_header, DimensionStyle),
    )
    builder.apply_background_image(legacy_header.background_image)
    builder.add_styles(
        (
            *legacy_header.style_previews,
            *(value for _, value in legacy_header.archive_objects if isinstance(value, StyleDescriptor)),
        )
    )
    builder.add_line_styles(legacy_header.line_styles)
    builder.apply_legacy_defaults(
        has_post_rendering_data=(legacy_header.post_rendering_payload_start_offset is not None)
    )
    # Definitions must receive final model IDs before instances are translated
    # from CArchive object indices into those IDs.
    archive_indices_by_identity = index_archive_object_identities(legacy_header.archive_objects)
    definitions_by_archive_index = populate_definitions(
        model,
        legacy_header,
        material_id_by_object_index=material_id_by_object_index,
        archive_indices_by_identity=archive_indices_by_identity,
        objects_by_archive_index=objects_by_archive_index,
    )
    model_owner_ids = {
        **material_id_by_object_index,
        **{
            state.object_tag.index: state.layer.id
            for state in legacy_header.archived_layers
            if state.object_tag.index is not None
        },
        **{archive_index: definition.id for archive_index, definition in definitions_by_archive_index.items()},
    }
    model.attribute_dictionaries_by_object_id.update(
        attribute_dictionaries_by_owner_id(
            legacy_header.attribute_container_indices_by_owner,
            legacy_header.archive_objects,
            model_owner_ids,
            objects_by_archive_index=objects_by_archive_index,
        )
    )
    populate_root_entities(
        model,
        legacy_header,
        definition_by_object_index=definitions_by_archive_index,
        material_id_by_object_index=material_id_by_object_index,
        archive_indices_by_identity=archive_indices_by_identity,
        objects_by_archive_index=objects_by_archive_index,
    )
    model.attribute_dictionaries.extend(
        attribute_dictionaries_for_container_index(
            legacy_header.root_attribute_container_index,
            objects_by_archive_index,
        )
    )
    apply_legacy_extensions(model)
    if import_vray_materials:
        apply_renderer_materials(model, max_xml_bytes=(limits or LoadLimits()).max_xml_bytes)
    return builder.finalize()


def _provenance_from_envelope(envelope: ParsedLegacyEnvelope) -> ArchiveProvenance:
    """Copy immutable envelope fields into the mutable parse accumulator."""
    provenance = ArchiveProvenance()
    provenance.product_name = envelope.product_name
    provenance.version_string = envelope.version_string
    provenance.format_version = envelope.format_version
    provenance.model_guid = envelope.model_guid
    provenance.saved_path = envelope.saved_path
    provenance.timestamp = envelope.timestamp
    provenance.version_map = envelope.version_map
    provenance.archive_schema = envelope.archive_schema
    provenance.archive_offset = envelope.archive_offset
    return provenance


def _read_inline_model_prefix(
    stream: BinaryIO,
    provenance: ArchiveProvenance,
    model_class_version: int,
) -> RootModelPrefixState:
    """Read root-only inline sections before archive object indexing begins."""
    archive_schema = provenance.archive_schema
    root_prefix = read_root_model_prefix(stream, model_class_version)
    provenance.root_prefix = root_prefix
    model_preamble_payload = read_model_payload_preamble(
        stream,
        entity_class_version=_version_for_class(archive_schema, "CEntity"),
        component_behavior_class_version=_version_for_class(archive_schema, "CComponentBehavior"),
    )
    (
        provenance.model_preamble_payload_start_offset,
        provenance.root_component_behavior,
        provenance.model_description,
        provenance.model_preamble_payload_end_offset,
    ) = model_preamble_payload
    # Options and model attributes moved into this prefix at model schema 21.
    # Older schemas serialize options again in the model tail.
    if model_class_version >= 21:
        provenance.options_manager = read_options_manager(stream)
        provenance.options_manager_payload_end_offset = stream.tell()
        model_properties_payload = read_attribute_container(
            stream,
            entity_class_version=_version_for_class(archive_schema, "CEntity"),
            attribute_named_class_version=_version_for_class(archive_schema, "CAttributeNamed"),
        )
    else:
        provenance.options_manager = OptionsManager()
        provenance.options_manager_payload_end_offset = stream.tell()
        empty_offset = stream.tell()
        model_properties_payload = (
            ArchiveObjectTag("null", 0, 0),
            (),
            (),
            empty_offset,
            empty_offset,
        )
    (
        provenance.model_properties_object_tag,
        provenance.model_property_tags,
        provenance.model_properties,
        provenance.model_properties_payload_start_offset,
        provenance.model_properties_payload_end_offset,
    ) = model_properties_payload
    camera_section_payload = read_root_camera_section(
        stream,
        model_class_version=model_class_version,
        camera_class_version=archive_schema.versions.get("CCamera"),
    )
    (
        provenance.camera_section_leading_tag,
        provenance.root_camera_tag,
        provenance.root_camera,
        provenance.root_camera_payload_end_offset,
        provenance.camera_section_leading_dib,
    ) = camera_section_payload
    provenance.rendering_options = read_rendering_options(
        stream,
        entity_class_version=_version_for_class(archive_schema, "CEntity"),
        rendering_options_class_version=_version_for_class(archive_schema, "CRenderingOptions"),
    )
    provenance.rendering_options_payload_end_offset = stream.tell()
    (
        provenance.post_rendering_payload_start_offset,
        provenance.obsolete_vertex_count,
        provenance.validity_check_performed,
        provenance.root_component_payload_start_offset,
    ) = read_post_rendering_model_data(
        stream,
        model_class_version=model_class_version,
    )
    return root_prefix


def _create_seeded_archive_session(
    stream: BinaryIO,
    provenance: ArchiveProvenance,
    model_class_version: int,
    root_prefix: RootModelPrefixState,
) -> LegacyArchiveSession:
    """Start object indexing at the exact root-component boundary."""
    archive_session = LegacyArchiveSession(stream, file_version=str(provenance.format_version))
    _seed_known_archive_entries(
        archive_session,
        model_class_version=model_class_version,
        root_prefix=root_prefix,
        model_properties_object_tag=cast(ArchiveObjectTag, provenance.model_properties_object_tag),
        model_property_tags=provenance.model_property_tags,
        root_camera_tag=cast(ArchiveObjectTag, provenance.root_camera_tag),
        camera_section_leading_dib=provenance.camera_section_leading_dib,
    )
    return archive_session


def _apply_root_component_provenance(
    provenance: ArchiveProvenance,
    root_component: ComponentBodyState,
) -> None:
    """Install normalized root-component ownership and geometry metadata."""
    root_objects = root_component.entities
    root_face_edges = tuple(value for value in root_component.entity_children if isinstance(value, EdgeState))
    provenance.definition_tags = root_component.definition_tags
    provenance.definition_list_start_offset = root_component.definition_list_start_offset
    provenance.definition_list_end_offset = root_component.definition_list_end_offset
    provenance.root_component_materials = root_component.materials
    provenance.root_attribute_container_index = (
        root_component.drawing_element.entity_header.attribute_container_object_index
    )
    provenance.archived_layers = root_component.layers
    provenance.layer_folders = root_component.layer_folders
    provenance.active_layer_tag = root_component.active_layer_tag
    provenance.layer_manager_start_offset = root_component.layer_manager_start_offset
    provenance.layer_manager_payload_start_offset = root_component.layer_manager_start_offset
    provenance.layer_manager_payload_end_offset = root_component.layer_manager_end_offset
    provenance.root_entity_count = root_component.entity_count
    provenance.root_component_payload_end_offset = root_component.payload_end_offset
    provenance.root_objects = root_objects
    provenance.root_relationships = root_component.relationships
    provenance.root_edge_previews = (
        *(value for value in root_objects if isinstance(value, EdgeState)),
        *root_face_edges,
    )
    provenance.root_faces = tuple(value for value in root_objects if isinstance(value, Face))


def _recover_trailing_metadata(
    stream: BinaryIO,
) -> tuple[
    tuple[RecoveredSceneState, ...],
    tuple[Font, ...],
    tuple[StyleDescriptor, ...],
]:
    """Scan only the bounded suffix left after structural model-tail decoding."""
    trailing_offset = stream.tell()
    trailing_data = stream.read(POST_LAYER_HEURISTIC_SCAN_BYTES)
    scene_previews, _, _ = scan_post_layer_previews(trailing_data, absolute_start=trailing_offset)
    recovered_fonts = scan_font_previews(trailing_data, absolute_start=trailing_offset)
    recovered_styles = scan_style_previews(trailing_data, absolute_start=trailing_offset)
    stream.seek(trailing_offset)
    return scene_previews, recovered_fonts, recovered_styles


def _apply_tail_provenance(
    provenance: ArchiveProvenance,
    model_tail: ModelTailState,
    archive_session: LegacyArchiveSession,
    scene_previews: tuple[RecoveredSceneState, ...],
    recovered_fonts: tuple[Font, ...],
    recovered_styles: tuple[StyleDescriptor, ...],
) -> None:
    """Install model-tail metadata and final archive ownership snapshots."""
    provenance.archived_scenes = tuple(
        value for value in archive_session.objects.values() if isinstance(value, SceneState)
    )
    provenance.scene_previews = scene_previews
    provenance.shadow_info = model_tail.shadow_info
    provenance.model_view_axes = model_tail.model_view_axes
    provenance.font_previews = (*model_tail.fonts, *recovered_fonts)
    provenance.style_previews = (*model_tail.styles_registry.styles, *recovered_styles)
    provenance.line_styles = model_tail.line_styles
    provenance.styles_registry = model_tail.styles_registry
    provenance.watermark_manager = model_tail.watermark_manager
    provenance.text_style = model_tail.text_style
    provenance.dimension_style = model_tail.dimension_style
    provenance.background_image = model_tail.background_image
    provenance.model_tail_state_u32 = model_tail.state_u32
    provenance.model_tail_final_u32 = model_tail.final_u32
    provenance.model_tail_final_bool = model_tail.final_bool
    provenance.model_tail_payload_end_offset = model_tail.payload_end_offset
    provenance.archive_index_entries = archive_session.index_table.entries
    provenance.archive_objects = tuple(archive_session.objects.items())
    provenance.attribute_container_indices_by_owner = tuple(
        archive_session.attribute_container_indices_by_owner.items()
    )


def parse_legacy_header(stream: BinaryIO) -> ArchiveProvenance:
    """Parse a pre-ZIP file envelope, version map, and archive payload."""
    # CVersionMap from this file selects every subsequent class layout.
    envelope = read_legacy_envelope(stream)
    provenance = _provenance_from_envelope(envelope)
    model_class_version = _version_for_class(provenance.archive_schema, "CSketchUpModel")
    root_prefix = _read_inline_model_prefix(stream, provenance, model_class_version)
    # From here, every nested class tag participates in one shared object table.
    session = _create_seeded_archive_session(stream, provenance, model_class_version, root_prefix)
    class_versions = _class_version_lookup(list(provenance.version_map))
    root_component = read_root_component(session, class_versions)
    _apply_root_component_provenance(provenance, root_component)
    context = create_object_read_context(session, class_versions)
    model_tail = read_model_tail(context, model_class_version=model_class_version)
    provenance.options_manager = model_tail.options_manager or provenance.options_manager
    scene_previews, recovered_fonts, recovered_styles = _recover_trailing_metadata(stream)
    _apply_tail_provenance(
        provenance,
        model_tail,
        session,
        scene_previews,
        recovered_fonts,
        recovered_styles,
    )
    return provenance


def _version_for_class(schema: ArchiveSchema, class_name: str) -> int:
    """Return the class schema selected by the current file CVersionMap."""
    return schema.version_for(class_name)


def _class_version_lookup(entries: list[VersionMapEntry]) -> dict[str, int]:
    return {entry.class_name: entry.version for entry in entries}


def _seed_known_archive_entries(
    session: LegacyArchiveSession,
    *,
    model_class_version: int,
    root_prefix: RootModelPrefixState,
    model_properties_object_tag: ArchiveObjectTag,
    model_property_tags: tuple[ArchiveObjectTag, ...],
    root_camera_tag: ArchiveObjectTag,
    camera_section_leading_dib: DibState | None,
) -> None:
    # Several root objects are serialized inline without a leading ReadObject
    # tag. They must still occupy table slots or every later back-reference is
    # shifted and can resolve to the wrong geometry object.
    session.register_implicit_object("CSketchUpModel", model_class_version)
    if root_prefix.thumbnail is not None:
        session.index_table.register_new_object_tag(root_prefix.thumbnail.object_tag)
    session.index_table.register_new_object_tag(model_properties_object_tag)
    for attribute_tag in model_property_tags:
        session.index_table.register_new_object_tag(attribute_tag)
    if camera_section_leading_dib is not None:
        session.index_table.register_new_object_tag(camera_section_leading_dib.object_tag)
    session.index_table.register_new_object_tag(root_camera_tag)


def parse_legacy_bytes(data: bytes, *, import_vray_materials: bool = False, limits: LoadLimits | None = None) -> Model:
    """Parse a pre-ZIP SketchUp byte string into a shared :class:`Model`."""
    return parse_legacy_model(
        cast(BinaryIO, LegacyArchiveBuffer(data)),
        import_vray_materials=import_vray_materials,
        limits=limits,
    )
