# SPDX-License-Identifier: MIT
"""Legacy diagnostic wrappers and top-level parser orchestration boundaries."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any, cast

from skppy.data_structure.construction import Camera
from skppy.data_structure.model_metadata import OptionsManager, RenderingOptions
from skppy.parser_legacy.binary import ArchiveObjectTag
from skppy.parser_legacy.diagnostics import (
    LegacyClassCoverageEntry,
    LegacyClassCoverageReport,
    _class_support_status,
    diagnose_legacy_class_coverage_file,
    diagnose_legacy_file,
    diagnose_legacy_runtime_classes_file,
    diagnose_legacy_stream,
)
from skppy.parser_legacy.parser import (
    _read_inline_model_prefix,
    _seed_known_archive_entries,
)
from skppy.parser_legacy.parser_types import DibState, RootModelPrefixState
from skppy.parser_legacy.provenance import ArchiveProvenance


def _tag(class_name: str = "CTest") -> ArchiveObjectTag:
    return ArchiveObjectTag("new_class", 0xFFFF, schema=1, class_name=class_name)


def test_diagnostic_supported_entries_and_not_implemented_issue(monkeypatch) -> None:
    supported = LegacyClassCoverageEntry("CEdge", 2, "supported")
    missing = LegacyClassCoverageEntry("CUnknown", 1, "missing")
    report = LegacyClassCoverageReport((supported, missing))
    assert report.supported_entries == (supported,)

    monkeypatch.setattr(
        "skppy.parser_legacy.diagnostics.parse_legacy_model",
        lambda stream: (_ for _ in ()).throw(NotImplementedError("future schema")),
    )
    issue_report = diagnose_legacy_stream(io.BytesIO())
    assert issue_report.issues[0].kind == "not_implemented"


def test_diagnostic_file_wrappers_and_heuristic_status(tmp_path, monkeypatch) -> None:
    path = tmp_path / "invalid.skp"
    path.write_bytes(b"not a legacy archive")

    assert diagnose_legacy_file(path).issues
    assert diagnose_legacy_class_coverage_file(path).issues
    assert diagnose_legacy_runtime_classes_file(path).issues

    monkeypatch.setattr(
        "skppy.parser_legacy.diagnostics.HEURISTIC_LEGACY_OBJECT_CLASSES",
        frozenset({"CHeuristic"}),
    )
    assert _class_support_status("CHeuristic") == "heuristic"


def test_old_model_prefix_synthesizes_empty_options_and_properties(monkeypatch) -> None:
    root_prefix = RootModelPrefixState(class_version=20)
    camera_tag = _tag("CCamera")
    monkeypatch.setattr(
        "skppy.parser_legacy.parser.read_root_model_prefix",
        lambda stream, version: root_prefix,
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.parser._version_for_class",
        lambda schema, class_name: 0,
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.parser.read_model_payload_preamble",
        lambda *args, **kwargs: (1, None, "Description", 2),
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.parser.read_root_camera_section",
        lambda *args, **kwargs: (_tag("CDib"), camera_tag, Camera(), 3, None),
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.parser.read_rendering_options",
        lambda *args, **kwargs: RenderingOptions(),
    )
    monkeypatch.setattr(
        "skppy.parser_legacy.parser.read_post_rendering_model_data",
        lambda *args, **kwargs: (4, 0, 1, 5),
    )
    provenance = ArchiveProvenance()
    stream = io.BytesIO()

    result = _read_inline_model_prefix(stream, provenance, 20)

    assert result is root_prefix
    assert isinstance(provenance.options_manager, OptionsManager)
    assert provenance.model_properties_object_tag == ArchiveObjectTag("null", 0, 0)
    assert provenance.model_properties == ()


def test_archive_seed_registers_thumbnail_and_leading_dib() -> None:
    thumbnail_tag = _tag("CDib")
    leading_tag = _tag("CDib")
    root_prefix = RootModelPrefixState(thumbnail=DibState(thumbnail_tag, 3, 0, 4, b"PNG", None, 3))
    registered: list[ArchiveObjectTag] = []
    implicit: list[tuple[str, int]] = []
    session = SimpleNamespace(
        register_implicit_object=lambda name, version: implicit.append((name, version)),
        index_table=SimpleNamespace(register_new_object_tag=lambda tag: registered.append(tag)),
    )

    _seed_known_archive_entries(
        cast(Any, session),
        model_class_version=22,
        root_prefix=root_prefix,
        model_properties_object_tag=_tag("CAttributeContainer"),
        model_property_tags=(_tag("CAttributeNamed"),),
        root_camera_tag=_tag("CCamera"),
        camera_section_leading_dib=DibState(leading_tag, 3, 0, 4, b"PNG", None, 3),
    )

    assert implicit == [("CSketchUpModel", 22)]
    assert registered[0] is thumbnail_tag
    assert leading_tag in registered
    assert registered[-1].class_name == "CCamera"
