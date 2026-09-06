# SPDX-License-Identifier: MIT
"""Tests for versioned documentation publication."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import runpy
import sys

import pytest
from jinja2 import Environment, FileSystemLoader


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

    assert versions[0]["label"] == "stable"
    assert versions[0]["path"] == "stable"
    assert versions[0]["ref"] == versions[2]["ref"]
    assert versions[0]["version"] == versions[2]["label"]
    assert versions[1]["path"] == "latest"
    assert "index" in versions[0]["documents"]
    assert any(item["label"] == "0.9.0" and item["path"] == "0.9.0" for item in versions)


def test_documentation_workflow_deploys_without_an_opt_in_variable() -> None:
    workflow = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")

    assert "make docs-versioned" in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/deploy-pages@v5" in workflow
    assert "ENABLE_GITHUB_PAGES" not in workflow


def test_documentation_workflow_does_not_deploy_duplicate_tag_builds() -> None:
    workflow = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")

    assert workflow.count("github.ref_type != 'tag'") == 2


def test_documentation_uses_current_sphinx_without_multiversion_dependency() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"sphinx>=7.2"' in metadata
    assert "sphinx-multiversion" not in metadata


def test_readme_links_current_and_release_documentation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "https://dantedex.github.io/skppy/latest/" in readme
    assert "https://dantedex.github.io/skppy/0.10.0/" in readme
    assert "https://dantedex.github.io/skppy/stable/" in readme


def test_versions_sort_numerically_and_ignore_nonrelease_tags(tmp_path, monkeypatch) -> None:
    builder = _load_version_builder()
    monkeypatch.setattr(builder, "_run_git", lambda *args: "v0.9.1\nv0.10.0\nv0.11.0rc1\nbackup\n")
    monkeypatch.setattr(builder, "_tag_documents", lambda *args: ["index"])

    versions = builder.discover_versions(tmp_path)

    assert [item["path"] for item in versions] == ["stable", "latest", "0.10.0", "0.9.1"]
    assert versions[0]["ref"] == "v0.10.0"
    assert versions[0]["version"] == "0.10.0"


def test_document_inventory_includes_generated_api_pages_before_build(tmp_path) -> None:
    builder = _load_version_builder()
    source = tmp_path / "api"
    source.mkdir()
    (source / "index.rst").write_text(
        "API\n===\n\n.. autosummary::\n   :toctree: generated\n\n   skppy.loader\n   skppy.utils\n",
        encoding="utf-8",
    )
    assert builder._document_names(tmp_path) == ["api/generated/skppy.loader", "api/generated/skppy.utils", "api/index"]


@pytest.mark.parametrize("has_release", [False, True])
def test_versioned_build_uses_release_source_for_stable(tmp_path, monkeypatch, has_release) -> None:
    builder = _load_version_builder()
    monkeypatch.setattr(builder, "_run_git", lambda *args: "v1.0.0" if has_release else "")
    monkeypatch.setattr(builder, "_tag_documents", lambda *args: ["index"])
    builds = []
    extracts = []

    def extract(root, ref, destination):
        extracts.append(ref)
        (destination / "skppy").mkdir(parents=True)

    def build(command, *, cwd, env, check):
        builds.append((env["SKPPY_DOC_CURRENT"], env["SKPPY_DOC_RELEASE"]))
        if env["SKPPY_DOC_CURRENT"] != "latest":
            assert "version = '1.0.0'" in (cwd / "skppy/_version.py").read_text()

    monkeypatch.setattr(builder, "_extract_source", extract)
    monkeypatch.setattr(builder.subprocess, "run", build)
    output = tmp_path / "output"
    builder.build_versioned_docs(tmp_path, output)

    assert builds == (
        [("stable", "1.0.0"), ("latest", "latest"), ("1.0.0", "1.0.0")] if has_release else [("latest", "latest")]
    )
    assert extracts == (["v1.0.0", "v1.0.0"] if has_release else [])
    default_path = "stable" if has_release else "latest"
    assert f"url=./{default_path}/" in (output / "index.html").read_text()
    assert (output / ".nojekyll").is_file()


@pytest.fixture
def version_context(monkeypatch):
    monkeypatch.setattr(sys, "path", sys.path.copy())
    config = runpy.run_path(str(ROOT / "docs/conf.py"))
    versions = [
        {"path": "stable", "label": "stable", "version": "0.10.0", "documents": ["index", "guides/reading"]},
        {"path": "latest", "label": "latest", "documents": ["index", "guides/reading", "new-page"]},
        {"path": "0.10.0", "label": "0.10.0", "documents": ["index", "guides/reading"]},
        {"path": "0.9.1", "label": "0.9.1", "documents": ["index"]},
    ]
    monkeypatch.setenv("SKPPY_DOC_VERSIONS", json.dumps(versions))
    return config["_add_version_context"]


@pytest.mark.parametrize(
    ("current", "outdated"), [("stable", False), ("latest", False), ("0.10.0", False), ("0.9.1", True)]
)
def test_version_links_preserve_nested_pages_and_warn_only_for_old_releases(
    version_context, monkeypatch, current, outdated
):
    monkeypatch.setenv("SKPPY_DOC_CURRENT", current)
    context = {}
    version_context(None, "guides/reading", None, context, None)

    assert context["documentation_current"]["path"] == current
    assert context["documentation_outdated"] is outdated
    stable_url = "reading.html" if current == "stable" else "../../stable/guides/reading.html"
    older_url = "../index.html" if current == "0.9.1" else "../../0.9.1/index.html"
    assert context["documentation_stable"]["url"] == stable_url
    assert context["documentation_versions"][-1]["url"] == older_url
    assert context["documentation_versions"][-1]["same_page"] is False
    assert sum(item["current"] for item in context["documentation_versions"]) == 1


def test_new_page_falls_back_to_release_index(version_context, monkeypatch) -> None:
    monkeypatch.setenv("SKPPY_DOC_CURRENT", "latest")
    context = {}
    version_context(None, "new-page", None, context, None)
    assert context["documentation_stable"]["url"] == "../stable/index.html"
    assert context["documentation_stable"]["same_page"] is False


def test_local_unversioned_build_has_no_menu(version_context, monkeypatch) -> None:
    monkeypatch.delenv("SKPPY_DOC_CURRENT", raising=False)
    context = {}
    version_context(None, "index", None, context, None)
    assert context == {}


def test_version_panel_renders_accessible_plain_links(version_context, monkeypatch) -> None:
    monkeypatch.setenv("SKPPY_DOC_CURRENT", "stable")
    context = {}
    version_context(None, "index", None, context, None)
    environment = Environment(loader=FileSystemLoader(ROOT / "docs/_templates"), autoescape=True)
    rendered = environment.get_template("versioning.jinja").render(context)

    assert '<details class="version-switcher">' in rendered
    assert 'aria-label="Documentation versions"' in rendered
    assert rendered.count('aria-current="page"') == 1
    assert 'href="index.html" aria-current="page"' in rendered
    assert "Development" in rendered and "Releases" in rendered
    assert "onchange=" not in rendered and "<select" not in rendered
