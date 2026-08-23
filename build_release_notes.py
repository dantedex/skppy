# SPDX-License-Identifier: MIT
"""Extract one tagged release section from the project changelog."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


_RELEASE_HEADING = re.compile(r"^##\s+(?P<version>\S+)(?:\s+-\s+.*)?$")


def extract_release_notes(changelog: str, tag: str) -> str:
    """Return only the changelog body matching a version tag."""
    version = tag.removeprefix("v")
    lines = changelog.splitlines()
    start_index: int | None = None

    for index, line in enumerate(lines):
        match = _RELEASE_HEADING.fullmatch(line)
        if match is not None and match.group("version") == version:
            start_index = index + 1
            break

    if start_index is None:
        raise ValueError(f"CHANGELOG.md has no release section for tag {tag!r}")

    end_index = len(lines)
    for index in range(start_index, len(lines)):
        if lines[index].startswith("## "):
            end_index = index
            break

    notes = "\n".join(lines[start_index:end_index]).strip()
    if not notes:
        raise ValueError(f"CHANGELOG.md release section for tag {tag!r} is empty")
    return f"{notes}\n"


def main() -> None:
    """Write release notes for one tag to a file consumed by GitHub Actions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Git tag to extract, normally vX.Y.Z")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--output", type=Path, default=Path("release-notes.md"))
    args = parser.parse_args()

    changelog = args.changelog.read_text(encoding="utf-8")
    args.output.write_text(extract_release_notes(changelog, args.tag), encoding="utf-8")


if __name__ == "__main__":
    main()
