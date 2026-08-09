# SPDX-License-Identifier: MIT
import subprocess
import sys
import tomllib
import zipfile

import build_blender_addon
from build_blender_addon import _blender_manifest_version, _manifest_with_version


def test_blender_manifest_version_converts_pep440_dev_to_semver_prerelease():
    assert _blender_manifest_version("0.5.1.dev12") == "0.5.1-dev.12"
    assert _blender_manifest_version("0.1.dev2") == "0.1.0-dev.2"


def test_blender_manifest_version_leaves_release_version_unchanged():
    assert _blender_manifest_version("0.5.1") == "0.5.1"
    assert _blender_manifest_version("0.1") == "0.1.0"


def test_manifest_with_version_uses_blender_compatible_dev_version():
    text = _manifest_with_version("0.5.1.dev12")

    assert 'version = "0.5.1-dev.12"' in text
    assert 'version = "0.5.1.dev12"' not in text


def test_built_addon_normalizes_untagged_root_dev_version(tmp_path, monkeypatch):
    """Keep untagged root histories installable as Blender extensions."""
    monkeypatch.setattr(build_blender_addon, "DIST_DIR", tmp_path)
    archive = build_blender_addon.build(version_override="0.1.dev2")

    with zipfile.ZipFile(archive) as addon_zip:
        manifest = tomllib.loads(addon_zip.read("blender_manifest.toml").decode("utf-8"))

    assert manifest["version"] == "0.1.0-dev.2"


def test_built_addon_bundles_complete_legacy_parser(tmp_path, monkeypatch):
    """Keep legacy format support in the self-contained Blender package."""
    monkeypatch.setattr(build_blender_addon, "DIST_DIR", tmp_path)

    archive = build_blender_addon.build(version_override="0.8.0.dev1")

    expected_parser_files = {
        f"skppy/{path.relative_to(build_blender_addon.SKPPY_SRC)}"
        for path in (build_blender_addon.SKPPY_SRC / "parser_legacy").glob("*.py")
    }
    with zipfile.ZipFile(archive) as addon_zip:
        bundled_files = set(addon_zip.namelist())
        absolute_internal_imports = {name for name in expected_parser_files if b"from skppy." in addon_zip.read(name)}
        addon_entrypoint = addon_zip.read("__init__.py")
        addon_manifest = tomllib.loads(addon_zip.read("blender_manifest.toml").decode("utf-8"))
        bundled_version = addon_zip.read("skppy/_version.py")

    assert expected_parser_files <= bundled_files
    assert absolute_internal_imports == set()
    assert "skppy/loader.py" in bundled_files
    assert "export_builder.py" in bundled_files
    assert "operators/export_skp.py" in bundled_files
    assert b"skppy.__version__ = _bundled_skppy_version" in addon_entrypoint
    assert b"TOPBAR_MT_file_export.append" in addon_entrypoint
    assert b'"author": "Dante Dex"' in addon_entrypoint
    assert b"https://github.com/dantedex/skppy/issues" in addon_entrypoint
    assert addon_manifest["maintainer"] == "Dante Dex <dante.dex.arch@gmail.com>"
    assert addon_manifest["version"] == "0.8.0-dev.1"
    assert b'__version__ = version = "0.8.0.dev1"' in bundled_version


def test_bundled_skppy_prefers_its_generated_version(tmp_path, monkeypatch):
    """The add-on must not inherit version metadata from another installation."""
    monkeypatch.setattr(build_blender_addon, "DIST_DIR", tmp_path)
    archive = build_blender_addon.build(version_override="0.8.0.dev1")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (f"import sys; sys.path.insert(0, {str(archive)!r}); import skppy; print(skppy.__version__)"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "0.8.0.dev1"
