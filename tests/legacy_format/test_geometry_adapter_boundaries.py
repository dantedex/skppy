# SPDX-License-Identifier: MIT
"""Legacy geometry adapter and archive-reference boundary fixtures."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any, cast

import pytest

from skppy.data_structure.entities import (
    Edge,
    EdgeUse,
    Face,
    FaceUVProjection,
    Loop,
    Vertex,
)
from skppy.data_structure.primitives import Vector3D
from skppy.parser_legacy.binary import (
    ArchiveObjectHandle,
    ArchiveObjectTag,
    LegacyArchiveReader,
)
from skppy.parser_legacy.geometry_readers import (
    _apply_face_texture_coords,
    _resolve_face_texture_payload,
    read_construction_geometry_body,
    read_curve,
    read_edge_body,
    read_edge_preview_from_session,
    read_edge_use,
    read_edge_use_body,
)
from skppy.parser_legacy.parser_types import (
    DrawingElementState,
    EdgeState,
    EntityHeaderState,
)
from skppy.parser_legacy.session import LegacyArchiveSession

from ._fixtures import (
    _class_ref_tag,
    _edge_preview_bytes,
    _new_class_tag,
    _object_ref_tag,
    _read_object_tags,
)


def _tag(kind: str = "null", index: int | None = 0) -> ArchiveObjectTag:
    return ArchiveObjectTag(cast(Any, kind), index or 0, index=index)


def _entity_header(
    *,
    container_tag: ArchiveObjectTag | None = None,
    container_index: int | None = None,
) -> EntityHeaderState:
    return EntityHeaderState(
        3,
        0,
        None,
        container_tag,
        None,
        0,
        attribute_container_object_index=container_index,
    )


def _drawing(header: EntityHeaderState | None = None) -> DrawingElementState:
    return DrawingElementState(
        0,
        header or _entity_header(),
        _tag(),
        False,
        True,
        True,
        False,
        False,
        False,
        None,
        0,
    )


def _vertex(x: float) -> Vertex:
    return Vertex(id=0, position=Vector3D(x, 0.0, 0.0))


def _edge_state(end: Vertex) -> EdgeState:
    return EdgeState(
        _tag(),
        1,
        0,
        _drawing(),
        Edge(id=0, start_vertex_id=0, end_vertex_id=0),
        _vertex(0.0),
        end,
        None,
        0,
    )


def test_tagged_curve_adapter_delegates_after_consuming_tag(monkeypatch) -> None:
    expected = object()
    calls: list[dict[str, object]] = []

    def fake_body(reader: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return expected

    monkeypatch.setattr("skppy.parser_legacy.geometry_readers.read_curve_body", fake_body)
    result = read_curve(
        io.BytesIO(_new_class_tag("CCurve", schema=4)),
        entity_class_version=3,
        class_version=4,
    )

    assert result is expected
    assert calls[0]["class_version"] == 4


def test_edge_body_supports_su3_chains_and_rejects_unresolved_vertices() -> None:
    previous_end = _vertex(1.0)
    previous = _edge_state(previous_end)
    chained_handle = ArchiveObjectHandle("object_ref", _tag("object_ref", 4), 4, None, "CEdge", 2)
    values = iter((chained_handle, _vertex(2.0)))

    edge = read_edge_body(
        cast(Any, SimpleNamespace(tell=lambda: 0)),
        object_tag=_tag(),
        object_index=2,
        class_version=1,
        read_drawing_element=_drawing,
        read_vertex_object=lambda: next(values),
        previous_edge=previous,
    )

    assert edge.start_vertex is previous_end
    with pytest.raises(ValueError, match="did not resolve"):
        read_edge_body(
            cast(Any, SimpleNamespace(tell=lambda: 0)),
            object_tag=_tag(),
            object_index=2,
            class_version=1,
            read_drawing_element=_drawing,
            read_vertex_object=lambda: object(),
        )


def test_edge_use_v0_and_unresolved_reference_fallback() -> None:
    references: list[ArchiveObjectTag] = []
    edge_use = read_edge_use_body(
        LegacyArchiveReader(io.BytesIO(b"\x01")),
        class_version=0,
        read_entity=lambda: None,
        read_edge=lambda: 5,
        read_reference=lambda: references.append(_tag()) or _tag(),
    )
    assert edge_use == EdgeUse(edge_id=5, reversed=True)
    assert len(references) == 3

    objects = iter(((_tag("object_ref", 17), object()), _tag()))
    context = SimpleNamespace(
        session=SimpleNamespace(reader=LegacyArchiveReader(io.BytesIO(b"\x00"))),
        read_entity=lambda: None,
        read_object=lambda: next(objects),
        read_reference=lambda: next(objects),
    )
    assert read_edge_use(cast(Any, context), class_version=1).edge_id == 17


def test_face_texture_resolution_covers_fallback_and_malformed_entries() -> None:
    uv = FaceUVProjection()
    texture_tag = _tag("object_ref", 8)
    container = (_tag(), (texture_tag,), (), 0, 0)
    entry = SimpleNamespace(class_name="CFaceTextureCoords")
    session = SimpleNamespace(
        objects={7: container, 8: (0, uv, uv, 1, 1)},
        index_table=SimpleNamespace(resolve_object=lambda index: entry),
    )
    context = SimpleNamespace(session=session)
    drawing = _drawing(_entity_header(container_tag=_tag("object_ref", 7), container_index=None))
    face = Face(
        id=1,
        plane=(0.0, 0.0, 1.0, 0.0),
        outer_loop=Loop(),
        inner_loops=[],
    )

    _apply_face_texture_coords(cast(Any, context), face, drawing)
    assert face.front_uv is uv
    assert face.back_uv is uv

    assert _resolve_face_texture_payload(cast(Any, context), _drawing(_entity_header())) is None

    session.objects[7] = (_tag(), (_tag(index=None),), (), 0, 0)
    assert _resolve_face_texture_payload(cast(Any, context), drawing) is None

    session.objects[7] = container
    session.index_table.resolve_object = lambda index: None
    assert _resolve_face_texture_payload(cast(Any, context), drawing) is None

    session.index_table.resolve_object = lambda index: entry
    session.objects[8] = object()
    assert _resolve_face_texture_payload(cast(Any, context), drawing) is None


def test_construction_geometry_version_guard() -> None:
    with pytest.raises(NotImplementedError, match="CConstructionGeometry"):
        read_construction_geometry_body(class_version=1, read_drawing_element=_drawing)


def test_session_edge_adapter_resolves_an_existing_vertex_reference() -> None:
    original = _edge_preview_bytes()
    second_vertex = _class_ref_tag(13) + b"\x00\x00" + original[-26:-2]
    data = original.replace(second_vertex, _object_ref_tag(14), 1)
    session = LegacyArchiveSession(io.BytesIO(data))
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

    assert edge.start_vertex is edge.end_vertex
