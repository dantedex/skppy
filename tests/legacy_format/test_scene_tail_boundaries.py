# SPDX-License-Identifier: MIT
"""Legacy scene adapters, model-tail gates, and reference boundaries."""

from __future__ import annotations

import io
import struct
from types import SimpleNamespace
from typing import Any, cast

import pytest

from skppy.data_structure.construction import ShadowInfo
from skppy.data_structure.model import Model
from skppy.data_structure.model_metadata import (
    DimensionStyle,
    LineStyle,
    ModelViewAxes,
    StylesRegistry,
    TextStyle,
    WatermarkManager,
)
from skppy.data_structure.scene_data import PageBackgroundImage, Scene
from skppy.parser_legacy.binary import (
    ArchiveObjectHandle,
    ArchiveObjectTag,
    LegacyArchiveReader,
)
from skppy.parser_legacy.model_tail import _read_legacy_page_array, read_model_tail
from skppy.parser_legacy.parser_types import SceneState
from skppy.parser_legacy.read_context import ObjectReadContext
from skppy.parser_legacy.scene_builder import populate_scenes
from skppy.parser_legacy.scene_pages import (
    RecoveredSceneState,
    SCENE_FLAG_USE_CAMERA,
    _flag_enabled,
    _read_scene_snapshots,
    looks_like_scene_page_tail,
    read_image_rep_payload,
    read_page_list_body,
    read_scene_identity,
    read_scene_page_timing,
    read_view_page,
    read_view_page_preview_from_span,
)

from ._fixtures import _new_class_tag


def _tag(kind: str = "null", index: int | None = 0) -> ArchiveObjectTag:
    return ArchiveObjectTag(cast(Any, kind), index or 0, index=index)


def _scene_state(offset: int, name: str = "Scene") -> SceneState:
    return SceneState(
        object_tag=_tag("new_class", None),
        class_version=12,
        scene=Scene(id=0, name=name),
        payload_start_offset=offset,
    )


def _recovered(offset: int, name: str = "Recovered") -> RecoveredSceneState:
    return RecoveredSceneState(
        object_tag=_tag("new_class", None),
        payload_start_offset=offset,
        name=name,
        description="Description",
        flags_u32=0,
        include_in_animation=True,
        transition_time=-1.0,
        delay_time=-1.0,
        timing_offset=4,
        use_camera=False,
        use_rendering_options=False,
        use_shadow_info=False,
        use_axes=False,
        use_hidden=False,
        use_layer_visibility=False,
        use_section_planes=False,
        raw_tail_payload=b"raw",
        payload_end_offset=offset + 3,
    )


def test_scene_identity_image_rep_and_page_list_boundaries() -> None:
    with pytest.raises(NotImplementedError, match="CSketchUpPage"):
        read_scene_identity(LegacyArchiveReader(io.BytesIO()), class_version=2)
    assert read_image_rep_payload(io.BytesIO(b"\x00")) == b""
    with pytest.raises(NotImplementedError, match="CPageList"):
        read_page_list_body(LegacyArchiveReader(io.BytesIO()), class_version=2, read_object=lambda: None)

    scene = Scene(id=0, name="Direct")
    state = _scene_state(1, "Wrapped")
    objects = iter((scene, state, object()))
    pages = read_page_list_body(
        LegacyArchiveReader(io.BytesIO(struct.pack("<I", 2))),
        class_version=1,
        read_object=lambda: next(objects),
    )
    assert pages == (scene, state.scene)


def test_old_view_page_camera_snapshot_and_version_guard() -> None:
    old_camera = (
        struct.pack("<9d", *range(9))
        + struct.pack("<2d", 0.1, 100.0)
        + b"\x01"
        + struct.pack("<2d", 35.0, 20.0)
        + struct.pack("<3d", 0.0, 0.0, 0.0)
    )
    context = SimpleNamespace(
        session=SimpleNamespace(reader=LegacyArchiveReader(io.BytesIO(old_camera))),
        class_versions={},
    )
    state = _scene_state(0)
    state.use_camera = True
    _read_scene_snapshots(cast(Any, context), state, class_version=6)
    assert state.camera_tag is not None
    assert state.camera_tag.class_name == "CCamera"
    assert state.scene.camera is not None

    with pytest.raises(NotImplementedError, match="CViewPage"):
        read_view_page(
            cast(Any, context),
            object_tag=_tag(),
            class_version=10,
            page_class_version=1,
        )


def test_view_page_preview_rejects_wrong_tags_and_entity_references() -> None:
    wrong_class = _new_class_tag("COther", schema=1)
    with pytest.raises(ValueError, match="Expected CViewPage"):
        read_view_page_preview_from_span(
            wrong_class,
            tag_offset=0,
            payload_end_offset=len(wrong_class),
            absolute_start=0,
        )

    with pytest.raises(ValueError, match="object tag"):
        read_view_page_preview_from_span(b"\x00\x00", tag_offset=0, payload_end_offset=2, absolute_start=0)

    wrong_entity = struct.pack("<H", 0x8001) + b"\x01\x00"
    with pytest.raises(ValueError, match="null CEntity"):
        read_view_page_preview_from_span(
            wrong_entity,
            tag_offset=0,
            payload_end_offset=len(wrong_entity),
            absolute_start=0,
        )


def test_scene_timing_short_invalid_and_missing_candidates() -> None:
    assert read_scene_page_timing(b"123") == (None, None, None, None, None)
    assert read_scene_page_timing(struct.pack("<I", 0x1_0000)) == (
        None,
        None,
        None,
        None,
        None,
    )
    assert read_scene_page_timing(struct.pack("<I", 0) + b"\x02" * 20) == (
        0,
        None,
        None,
        None,
        None,
    )
    assert looks_like_scene_page_tail(b"123") is False
    assert _flag_enabled(None, SCENE_FLAG_USE_CAMERA) is None


def test_scene_builder_merges_matching_recovery_and_direct_payloads() -> None:
    matching = _scene_state(10, "Direct")
    unmatched = _scene_state(20, "Only direct")
    model = Model()

    populate_scenes(model, (matching, unmatched), (_recovered(10),))

    assert [scene.name for scene in model.scenes] == ["Direct", "Only direct"]
    assert model.scenes[0].raw_payload == b"raw"
    assert [scene.id for scene in model.scenes] == [1, 2]


def test_legacy_page_array_filters_non_scene_objects() -> None:
    scene = Scene(id=0, name="Page")
    objects = iter(((None, scene), (None, object())))
    context = SimpleNamespace(
        session=SimpleNamespace(reader=LegacyArchiveReader(io.BytesIO(struct.pack("<I", 2)))),
        read_object=lambda: next(objects),
    )
    assert _read_legacy_page_array(cast(Any, context)) == (scene,)


def test_model_tail_reads_late_line_styles_and_background(monkeypatch) -> None:
    background = PageBackgroundImage(path="background.png")
    integers = iter((*([0] * 16), 99))
    reader = SimpleNamespace(
        stream=io.BytesIO(),
        tell=lambda: 7,
        read_u32=lambda: next(integers),
        read_bool=lambda: True,
    )
    context = SimpleNamespace(
        session=SimpleNamespace(reader=reader),
        class_versions={},
        read_drawing_element=lambda: None,
        read_object=lambda: (_tag(), background),
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.model_tail.read_shadow_info",
        lambda *args, **kwargs: ShadowInfo(),
    )
    monkeypatch.setattr("skppy.parser_legacy.model_tail.read_page_list", lambda *args, **kwargs: ())
    monkeypatch.setattr(
        "skppy.parser_legacy.model_tail.read_axes_payload",
        lambda *args, **kwargs: ModelViewAxes(),
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.model_tail.read_dimension_style",
        lambda *args, **kwargs: DimensionStyle(),
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.model_tail.read_text_style",
        lambda *args, **kwargs: TextStyle(),
    )
    monkeypatch.setattr("skppy.parser_legacy.model_tail.read_font_manager", lambda *args, **kwargs: ())
    monkeypatch.setattr(
        "skppy.parser_legacy.model_tail.read_line_style_manager",
        lambda *args, **kwargs: (LineStyle(name="Dash"),),
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.model_tail.read_style_manager",
        lambda *args, **kwargs: StylesRegistry(),
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.model_tail.read_watermark_manager",
        lambda *args, **kwargs: WatermarkManager(),
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.model_tail.read_options_manager",
        lambda *args, **kwargs: None,
    )

    tail = read_model_tail(cast(Any, context), model_class_version=29)

    assert [style.name for style in tail.line_styles] == ["Dash"]
    assert tail.background_image is background
    assert (tail.final_u32, tail.final_bool) == (99, True)

    old_integers = iter([0] * 17)
    old_context = SimpleNamespace(
        session=SimpleNamespace(
            reader=SimpleNamespace(
                stream=io.BytesIO(),
                tell=lambda: 0,
                read_u32=lambda: next(old_integers),
            )
        ),
        class_versions={},
        read_drawing_element=lambda: None,
        read_object=lambda: (_tag(), object()),
    )
    old_tail = read_model_tail(cast(Any, old_context), model_class_version=11)
    assert old_tail.scenes == ()


def test_read_context_resolves_opted_in_inline_reference() -> None:
    handle = ArchiveObjectHandle("new_object", _tag("new_class", None), 4, 3, "CTest", 1)
    resolved = []
    session = SimpleNamespace(read_object_handle=lambda: handle)
    context = ObjectReadContext(cast(Any, session), {}, resolved.append)

    assert context.read_reference(resolve_new=True) is handle.tag
    assert resolved == [handle]
