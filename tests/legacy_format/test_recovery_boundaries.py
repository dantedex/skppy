# SPDX-License-Identifier: MIT
"""Legacy heuristic-recovery rejection and fallback boundaries."""

from __future__ import annotations

import struct

from skppy.data_structure.construction import ShadowInfo
from skppy.parser_legacy.recovery import (
    DEFAULT_MODEL_VIEW_AXES_BYTES,
    RecoveredShadowInfo,
    _looks_like_legacy_class_name,
    _next_runtime_class_candidate,
    _next_runtime_class_tag_offset,
    _scan_model_view_axes,
    _scan_scene_previews,
    scan_font_previews,
    scan_style_previews,
)

from ._fixtures import _legacy_string, _new_class_tag, _style_preview_payload_bytes


def test_scene_scanner_rejects_bad_entity_and_truncated_candidates() -> None:
    wrong_entity = b"".join(
        [
            _new_class_tag("CViewPage", schema=12),
            b"\x01\x00",
            _legacy_string("Scene"),
            _legacy_string(""),
        ]
    )
    assert _scan_scene_previews(wrong_entity, absolute_start=0) == ()
    assert _scan_scene_previews(_new_class_tag("CViewPage", schema=12), absolute_start=0) == ()


def test_scene_scanner_skips_preview_decode_errors(monkeypatch) -> None:
    data = b"".join(
        [
            _new_class_tag("CViewPage", schema=12),
            b"\x00\x00",
            _legacy_string("Scene"),
            _legacy_string("Description"),
            b"tail",
        ]
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.recovery.read_view_page_preview_from_span",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad preview")),
    )
    assert _scan_scene_previews(data, absolute_start=0) == ()


def test_runtime_class_candidate_skips_false_headers_and_name_shapes() -> None:
    class_name = b"CViewPage"
    false_header = b"xxxx" + struct.pack("<H", len(class_name)) + class_name
    valid_offset = len(false_header)
    data = false_header + _new_class_tag("CViewPage", schema=12)

    assert _next_runtime_class_candidate(data, class_name, 0) == valid_offset
    invalid_tag = b"\xff\xff\x00\x00\x01\x00C"
    assert _next_runtime_class_tag_offset(invalid_tag + data[valid_offset:], 0) == len(invalid_tag)
    assert _looks_like_legacy_class_name(b"C_Name9") is True
    assert _looks_like_legacy_class_name(b"C-name") is False


def test_axes_scanner_uses_shadow_offset_and_retries_identity_candidates() -> None:
    invalid = struct.pack("<3d", float("nan"), 0.0, 0.0) + DEFAULT_MODEL_VIEW_AXES_BYTES
    valid = struct.pack("<3d", 4.0, 5.0, 6.0) + DEFAULT_MODEL_VIEW_AXES_BYTES
    prefix = b"ignored!"
    data = prefix + invalid + valid
    absolute_start = 100
    shadow = RecoveredShadowInfo(
        payload_start_offset=absolute_start,
        value=ShadowInfo(),
        payload_end_offset=absolute_start + len(prefix),
    )

    recovered = _scan_model_view_axes(data, absolute_start=absolute_start, shadow_info=shadow)

    assert recovered is not None
    assert recovered.payload_start_offset == absolute_start + len(prefix) + len(invalid)
    assert recovered.value.origin == (4.0, 5.0, 6.0)


def test_font_and_style_scanners_skip_malformed_and_invalid_records() -> None:
    malformed_font = b"\xff\xfe\xff\x20" + b"x" * 20
    assert scan_font_previews(malformed_font, absolute_start=0) == ()

    truncated_style = _new_class_tag("CSkpStyle", schema=2) + b"\x00"
    assert scan_style_previews(truncated_style, absolute_start=0) == ()

    invalid_style = _style_preview_payload_bytes(
        guid=b"g" * 16,
        display_name="Style",
        file_name="style.style",
        option_count=10_001,
    )
    assert scan_style_previews(invalid_style, absolute_start=0) == ()
