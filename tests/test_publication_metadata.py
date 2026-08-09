# SPDX-License-Identifier: MIT
"""Checks for the public project identity distributed with skppy."""

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
AUTHOR = {"name": "Dante Dex", "email": "dante.dex.arch@gmail.com"}


def test_python_package_identifies_public_author_and_repositories() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert project["authors"] == [AUTHOR]
    assert project["maintainers"] == [AUTHOR]
    assert project["urls"] == {
        "Homepage": "https://github.com/dantedex/skppy",
        "Documentation": "https://dantedex.github.io/skppy/",
        "Repository": "https://github.com/dantedex/skppy.git",
        "Issues": "https://github.com/dantedex/skppy/issues",
    }


def test_license_and_public_readme_identify_dante_dex() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Copyright (c) 2026 Dante Dex" in license_text
    assert "dante.dex.arch@gmail.com" in readme
    assert "https://github.com/dantedex/skppy" in readme
    assert "https://github.com/dantedex/skppy-tests" in readme


def test_blender_source_manifest_identifies_public_maintainer() -> None:
    manifest = tomllib.loads((ROOT / "blender_skp_io" / "blender_manifest.toml").read_text(encoding="utf-8"))
    entrypoint = (ROOT / "blender_skp_io" / "__init__.py").read_text(encoding="utf-8")

    assert manifest["maintainer"] == "Dante Dex <dante.dex.arch@gmail.com>"
    assert '"author": "Dante Dex"' in entrypoint
    assert "https://dantedex.github.io/skppy/" in entrypoint
    assert "https://github.com/dantedex/skppy/issues" in entrypoint
