# SPDX-License-Identifier: MIT
"""Tests for tagged GitHub release-note extraction."""

from pathlib import Path

import pytest

from build_release_notes import extract_release_notes


ROOT = Path(__file__).resolve().parents[1]


def test_extracts_only_requested_release_from_full_project_changelog() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    notes = extract_release_notes(changelog, "v0.10.0")

    assert "Load standalone SketchUp material packages" in notes
    assert "## 0.10.0" not in notes
    assert "## Unreleased" not in notes
    assert "## 0.9.1" not in notes
    assert "Preserve door and window openings" not in notes
    assert notes.endswith("\n")


def test_preserves_subheadings_inside_release_section() -> None:
    changelog = """# Changelog

## Unreleased

- Next change.

## 1.2.3-rc.1 - 2026-08-23

### Added

- Candidate feature.

### Fixed

- Candidate fix.

## 1.2.2 - 2026-08-01

- Previous change.
"""

    assert extract_release_notes(changelog, "v1.2.3-rc.1") == (
        "### Added\n\n- Candidate feature.\n\n### Fixed\n\n- Candidate fix.\n"
    )


@pytest.mark.parametrize(
    ("changelog", "message"),
    [
        ("# Changelog\n\n## 1.0.0\n\n- Initial release.\n", "v2.0.0"),
        ("# Changelog\n\n## 1.0.0\n\n## 0.9.0\n\n- Previous.\n", "v1.0.0"),
    ],
)
def test_rejects_missing_or_empty_release_section(changelog: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        extract_release_notes(changelog, message)


def test_publish_workflow_uses_extracted_release_notes() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert 'python build_release_notes.py "${GITHUB_REF_NAME}" --output release-notes.md' in workflow
    assert "body_path: release-notes.md" in workflow
    assert "body_path: CHANGELOG.md" not in workflow
