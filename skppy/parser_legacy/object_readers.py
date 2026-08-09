# SPDX-License-Identifier: MIT
"""Runtime-class reader registry for legacy CArchive objects.

The archive stores a runtime class name before each new object, but the domain
readers intentionally expose signatures that match their actual wire layout.
For example, a vertex needs the raw object tag, a curve needs a recursive
reference callback, and a page needs both page and view-page schema versions.
Changing every domain reader to accept a generic ``handle`` would hide those
requirements and couple otherwise focused binary readers to dispatch state.

This module therefore normalizes invocation at one boundary. A mapping-like
registry selects an immutable callable binding; the binding supplies only the
context values required by its declared :class:`ReaderCall`. This avoids the
old linear class-name chain and avoids allocating one adapter closure for every
runtime class.
"""

from __future__ import annotations

from collections.abc import Callable, KeysView, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from .annotation_readers import (
    read_dimension,
    read_dimension_linear,
    read_dimension_radial,
    read_text,
)
from .attribute_readers import (
    read_attribute,
    read_attribute_container,
    read_named_attribute,
)
from .base_payloads import read_component_behavior
from .binary import ArchiveObjectHandle
from .camera_payloads import read_camera_body
from .component_payloads import read_definition_list_payload
from .component_readers import (
    read_component_definition,
    read_component_instance,
    read_group,
    read_image,
)
from .geometry_readers import (
    read_arc_curve_body,
    read_construction_geometry_body,
    read_curve_body,
    read_edge,
    read_edge_use,
    read_face,
    read_guide_line_body,
    read_guide_point_body,
    read_loop,
    read_polyline_body,
    read_section_plane_body,
    read_vertex_body,
)
from .image_payloads import read_dib_payload, read_thumbnail, read_texture
from .layer_payloads import read_layer, read_layer_group, read_layer_manager
from .line_style_payloads import read_custom_line_style
from .material_payloads import read_material, read_material_manager
from .metadata_readers import (
    read_dimension_style,
    read_font,
    read_font_manager,
    read_style,
    read_style_manager,
    read_text_style,
    read_watermark,
    read_watermark_manager,
)
from .parser_types import SupportedObjectPayload
from .read_context import ObjectReadContext
from .relationship_payloads import read_relationship, read_relationship_map
from .rendering_options import read_rendering_options_payload
from .scene_pages import (
    read_axes,
    read_page,
    read_page_list,
    read_shadow_info,
    read_view_page,
)
from .uv_payloads import read_face_texture_coords
from .visual_payloads import read_background_image

GenericReader = Callable[..., SupportedObjectPayload]


class ReaderCall(Enum):
    """Argument layout used to invoke one domain reader.

    These values describe calling conventions, not SketchUp wire values. A new
    member is warranted only when a reader has a genuinely different binary
    dependency, such as the archive stream, recursive resolver, object index,
    or a second class version. Keeping that distinction explicit prevents a
    future reader from accidentally receiving the wrong schema or consuming
    bytes from the wrong level of the archive.
    """

    CONTEXT = auto()
    VERSIONED_CONTEXT = auto()
    TAGGED_VERSIONED_CONTEXT = auto()
    VERTEX = auto()
    TAGGED_CONTEXT = auto()
    STREAM_TAGGED_VERSION = auto()
    ENTITY_THEN_READER = auto()
    INDEXED_TAGGED_CONTEXT = auto()
    CURVE = auto()
    ARC_CURVE = auto()
    DRAWING_ELEMENT = auto()
    FILE_VERSION_DRAWING_ELEMENT = auto()
    CONSTRUCTION_GEOMETRY = auto()
    COMPONENT_DEFINITION = auto()
    COMPONENT_PLACEMENT = auto()
    VIEW_PAGE = auto()
    DEFINITION_LIST = auto()


@dataclass(frozen=True, slots=True)
class ObjectReaderBinding:
    """Callable binding between a runtime class and a domain reader.

    The binding is immutable because registry entries are process-wide parser
    configuration. Making it callable lets dispatch use the normal mapping
    expression ``OBJECT_READERS[class_name](context, handle)`` without wrapper
    functions. ``schema_first`` exists for the few old construction classes
    whose runtime handle is more authoritative than the version-map fallback;
    all other classes prefer the version map selected for the file.
    """

    reader: GenericReader
    call: ReaderCall = ReaderCall.VERSIONED_CONTEXT
    version_keyword: str = "class_version"
    schema_first: bool = False

    def __call__(  # noqa: C901, PLR0912
        self,
        context: ObjectReadContext,
        handle: ArchiveObjectHandle,
    ) -> SupportedObjectPayload:
        """Invoke the bound reader with values supplied by the read context."""
        class_name = handle.class_name or ""
        mapped_version = context.class_versions.get(class_name, 0)
        # Most bodies follow CVersionMap. A small set of construction objects
        # was historically emitted with the effective schema on the object
        # handle, so their bindings opt into the inverse precedence.
        version = (
            (handle.schema or mapped_version)
            if self.schema_first
            else context.class_versions.get(class_name, handle.schema or 0)
        )
        session = context.session

        if self.call is ReaderCall.CONTEXT:
            return self.reader(context)
        if self.call is ReaderCall.VERSIONED_CONTEXT:
            return self.reader(context, class_version=version)
        if self.call is ReaderCall.TAGGED_VERSIONED_CONTEXT:
            return self.reader(
                context,
                object_tag=handle.tag,
                class_version=version,
            )
        if self.call is ReaderCall.VERTEX:
            return self.reader(
                session.reader,
                object_tag=handle.tag,
                read_entity=context.read_entity,
            )
        if self.call is ReaderCall.TAGGED_CONTEXT:
            return self.reader(context, object_tag=handle.tag)
        if self.call is ReaderCall.STREAM_TAGGED_VERSION:
            return self.reader(
                session.stream,
                object_tag=handle.tag,
                **{self.version_keyword: version},
            )
        if self.call is ReaderCall.ENTITY_THEN_READER:
            context.read_entity()
            return self.reader(session.reader, version)
        if self.call is ReaderCall.INDEXED_TAGGED_CONTEXT:
            return self.reader(
                context,
                object_tag=handle.tag,
                object_index=handle.object_index,
                class_version=version,
            )
        if self.call is ReaderCall.CURVE:
            return self.reader(
                session.reader,
                class_version=version,
                read_entity=context.read_entity,
                read_reference=lambda: context.read_reference(resolve_new=True),
            )
        if self.call is ReaderCall.ARC_CURVE:
            return self.reader(
                session.reader,
                curve_class_version=context.class_versions.get("CCurve", 4),
                arc_class_version=version,
                read_entity=context.read_entity,
                read_reference=lambda: context.read_reference(resolve_new=True),
            )
        if self.call is ReaderCall.DRAWING_ELEMENT:
            return self.reader(
                session.reader,
                class_version=version,
                read_drawing_element=context.read_drawing_element,
            )
        if self.call is ReaderCall.FILE_VERSION_DRAWING_ELEMENT:
            return self.reader(
                session.reader,
                class_version=version,
                file_version=session.file_version,
                read_drawing_element=context.read_drawing_element,
            )
        if self.call is ReaderCall.CONSTRUCTION_GEOMETRY:
            return self.reader(
                class_version=version,
                read_drawing_element=context.read_drawing_element,
            )
        if self.call is ReaderCall.COMPONENT_DEFINITION:
            return self.reader(
                context,
                object_tag=handle.tag,
                object_index=handle.object_index,
                component_class_version=context.class_versions.get("CComponent", 11),
                class_version=version,
            )
        if self.call is ReaderCall.COMPONENT_PLACEMENT:
            return self.reader(
                context,
                class_version=version,
                component_instance_version=context.class_versions.get("CComponentInstance", 4),
            )
        if self.call is ReaderCall.VIEW_PAGE:
            return self.reader(
                context,
                object_tag=handle.tag,
                class_version=version,
                page_class_version=context.class_versions.get("CSketchUpPage", 1),
            )
        if self.call is ReaderCall.DEFINITION_LIST:
            return self.reader(
                session,
                class_version=version,
                resolve=context.resolve,
            )
        raise AssertionError(f"Unhandled reader call layout: {self.call}")


class LegacyObjectReaderRegistry:
    """Read-only mapping-style access to legacy object reader bindings.

    Only ``keys`` and ``__getitem__`` are exposed because dispatch needs class
    discovery and exact lookup, not mutation. Central ownership also makes the
    supported runtime-class surface inspectable by diagnostics and tests while
    preventing call sites from depending on the registry's internal ``dict``.
    """

    def __init__(self, readers: Mapping[str, ObjectReaderBinding]) -> None:
        self._readers = dict(readers)

    def __getitem__(self, class_name: str) -> ObjectReaderBinding:
        """Return the binding for *class_name* or raise ``KeyError``."""
        return self._readers[class_name]

    def keys(self) -> KeysView[str]:
        """Return the runtime class names supported by this registry."""
        return self._readers.keys()


OBJECT_READERS = LegacyObjectReaderRegistry(
    {
        # Each entry names the domain reader and only overrides the default
        # VERSIONED_CONTEXT convention when its binary layout requires it.
        "CVertex": ObjectReaderBinding(read_vertex_body, ReaderCall.VERTEX),
        "CAttributeContainer": ObjectReaderBinding(read_attribute_container, ReaderCall.TAGGED_CONTEXT),
        "CAttribute": ObjectReaderBinding(read_attribute),
        "CAttributeNamed": ObjectReaderBinding(read_named_attribute),
        "CComponentBehavior": ObjectReaderBinding(read_component_behavior, ReaderCall.TAGGED_VERSIONED_CONTEXT),
        "CCamera": ObjectReaderBinding(
            read_camera_body,
            ReaderCall.STREAM_TAGGED_VERSION,
            version_keyword="camera_class_version",
        ),
        "CRenderingOptions": ObjectReaderBinding(read_rendering_options_payload, ReaderCall.ENTITY_THEN_READER),
        "CThumbnail": ObjectReaderBinding(read_thumbnail),
        "CEdge": ObjectReaderBinding(read_edge, ReaderCall.INDEXED_TAGGED_CONTEXT),
        "CCurve": ObjectReaderBinding(read_curve_body, ReaderCall.CURVE),
        "CArcCurve": ObjectReaderBinding(read_arc_curve_body, ReaderCall.ARC_CURVE),
        "CEdgeUse": ObjectReaderBinding(read_edge_use),
        "CLoop": ObjectReaderBinding(read_loop, ReaderCall.CONTEXT),
        "CFace": ObjectReaderBinding(read_face, ReaderCall.TAGGED_VERSIONED_CONTEXT),
        "CConstructionPoint": ObjectReaderBinding(
            read_guide_point_body,
            ReaderCall.DRAWING_ELEMENT,
            schema_first=True,
        ),
        "CConstructionLine": ObjectReaderBinding(
            read_guide_line_body,
            ReaderCall.FILE_VERSION_DRAWING_ELEMENT,
            schema_first=True,
        ),
        "CConstructionGeometry": ObjectReaderBinding(read_construction_geometry_body, ReaderCall.CONSTRUCTION_GEOMETRY),
        "CPolyline3d": ObjectReaderBinding(read_polyline_body, ReaderCall.DRAWING_ELEMENT),
        "CSectionPlane": ObjectReaderBinding(
            read_section_plane_body,
            ReaderCall.FILE_VERSION_DRAWING_ELEMENT,
            schema_first=True,
        ),
        "CComponentDefinition": ObjectReaderBinding(read_component_definition, ReaderCall.COMPONENT_DEFINITION),
        "CComponentInstance": ObjectReaderBinding(read_component_instance),
        "CGroup": ObjectReaderBinding(read_group, ReaderCall.COMPONENT_PLACEMENT),
        "CImage": ObjectReaderBinding(read_image, ReaderCall.COMPONENT_PLACEMENT),
        "CBackgroundImage": ObjectReaderBinding(read_background_image),
        "CDimension": ObjectReaderBinding(read_dimension),
        "CDimensionLinear": ObjectReaderBinding(read_dimension_linear),
        "CDimensionRadial": ObjectReaderBinding(read_dimension_radial),
        "CDimensionStyle": ObjectReaderBinding(read_dimension_style),
        "CText": ObjectReaderBinding(read_text),
        "CSkFont": ObjectReaderBinding(read_font),
        "CFontManager": ObjectReaderBinding(read_font_manager),
        "CTextStyle": ObjectReaderBinding(read_text_style),
        "CSkpStyle": ObjectReaderBinding(read_style),
        "CSkpStyleManager": ObjectReaderBinding(read_style_manager),
        "CSketchUpPage": ObjectReaderBinding(read_page),
        "CViewPage": ObjectReaderBinding(read_view_page, ReaderCall.VIEW_PAGE),
        "CSketchCS": ObjectReaderBinding(read_axes),
        "CShadowInfo": ObjectReaderBinding(read_shadow_info),
        "CWatermark": ObjectReaderBinding(read_watermark),
        "CWatermarkManager": ObjectReaderBinding(read_watermark_manager),
        "CFaceTextureCoords": ObjectReaderBinding(read_face_texture_coords),
        "CRelationship": ObjectReaderBinding(read_relationship, ReaderCall.CONTEXT),
        "CRelationshipMap": ObjectReaderBinding(read_relationship_map),
        "CMaterial": ObjectReaderBinding(read_material),
        "CLayer": ObjectReaderBinding(read_layer, ReaderCall.TAGGED_VERSIONED_CONTEXT),
        "CLayerManager": ObjectReaderBinding(read_layer_manager),
        "CLayerGroup": ObjectReaderBinding(read_layer_group),
        "CCustomLineStyle": ObjectReaderBinding(read_custom_line_style),
        "CTexture": ObjectReaderBinding(read_texture),
        "CDib": ObjectReaderBinding(
            read_dib_payload,
            ReaderCall.STREAM_TAGGED_VERSION,
            version_keyword="dib_class_version",
        ),
        "CMaterialManager": ObjectReaderBinding(read_material_manager),
        "CDefinitionList": ObjectReaderBinding(read_definition_list_payload, ReaderCall.DEFINITION_LIST),
        "CPageList": ObjectReaderBinding(read_page_list),
    }
)
