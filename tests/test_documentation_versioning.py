# SPDX-License-Identifier: MIT
"""Tests for versioned documentation publication."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_version_builder():
    spec = spec_from_file_location("build_versioned", ROOT / "docs" / "build_versioned.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_builder_discovers_clean_public_paths() -> None:
    version_builder = _load_version_builder()

    versions = version_builder.discover_versions(ROOT)

    assert versions[0]["label"] == "latest"
    assert versions[0]["path"] == "latest"
    assert "index" in versions[0]["documents"]
    assert any(item["label"] == "0.9.0" and item["path"] == "0.9.0" for item in versions)


def test_documentation_workflow_deploys_without_an_opt_in_variable() -> None:
    workflow = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")

    assert "make docs-versioned" in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/deploy-pages@v5" in workflow
    assert "ENABLE_GITHUB_PAGES" not in workflow


def test_documentation_uses_current_sphinx_without_multiversion_dependency() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"sphinx>=7.2"' in metadata
    assert "sphinx-multiversion" not in metadata


def test_readme_links_current_and_release_documentation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "https://dantedex.github.io/skppy/latest/" in readme
    assert "https://dantedex.github.io/skppy/0.9.1/" in readme
