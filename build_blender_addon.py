#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Package the blender_skp_io Blender addon as a distributable zip.

The zip is self-contained: the skppy library source is bundled inside it
under skppy/ so no separate installation is required in Blender's Python.

Repository layout
-----------------
    skppy/                  <- Python package (library + parser)
        pyproject.toml
        __init__.py
        ...
    blender_skp_io/         <- Blender addon
        __init__.py
        blender_manifest.toml
        annotation_builder.py
        export_builder.py
        scene_builder.py
        operators/
            __init__.py
            export_skp.py
            import_skp.py
    build_blender_addon.py  <- this script

Zip layout (output)
-------------------
    __init__.py
    blender_manifest.toml
    annotation_builder.py
    export_builder.py
    scene_builder.py
    operators/
        __init__.py
        export_skp.py
        import_skp.py
    skppy/                  <- bundled skppy library (copied from repo root at build time)
        __init__.py
        loader.py
        ...

Usage
-----
    python build_blender_addon.py            # creates dist/blender_skp_io-<ver>.zip
    python build_blender_addon.py --clean    # remove dist/ before building

The package version is the same one skppy gets from setuptools-scm, including
development versions such as ``0.9.1.dev12``. Blender extension manifests
require SemVer-compatible versions, so packaged manifests convert development
versions to prerelease form, such as ``0.9.1-dev.12``. For CI/release builds,
use a tag like ``v0.9.0``. Untagged checkouts fall back to ``0.0.0`` unless
``SKPPY_VERSION`` or ``SETUPTOOLS_SCM_PRETEND_VERSION`` is set.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ADDON_DIR = REPO_ROOT / "blender_skp_io"
SKPPY_SRC = REPO_ROOT / "skppy"
DIST_DIR = REPO_ROOT / "dist"

# Patterns to exclude from the zip
_EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "egg-info",
    "tests",
}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _normalise_version(raw_version: str) -> str:
    """
    Return a tag/env version in the same public form used by skppy.

    Tags may be written as ``vMAJOR.MINOR.PATCH``.  Development versions such
    as ``0.9.1.dev12`` are preserved.  Local version metadata (``+...``) is
    dropped to match the project's ``setuptools-scm`` ``no-local-version``
    setting.
    """
    version = raw_version.strip()
    if version.startswith("refs/tags/"):
        version = version.removeprefix("refs/tags/")
    if version.startswith("v"):
        version = version[1:]
    version = version.split("+", 1)[0]
    if not re.match(r"^\d+(?:\.\d+)*(?:(?:a|b|rc|\.post|\.dev)\d+)?$", version):
        raise RuntimeError(
            f"Cannot derive Blender addon version from {raw_version!r}; expected a version like v0.9.0 or 0.9.1.dev12"
        )
    return version


def _version_from_setuptools_scm() -> str | None:
    try:
        from setuptools_scm import get_version
    except ImportError:
        return None

    try:
        return get_version(
            root=REPO_ROOT,
            version_scheme="guess-next-dev",
            local_scheme="no-local-version",
        )
    except Exception:
        return None


def _bump_version_for_dev(tag_version: str) -> str:
    parts = tag_version.split(".")
    if not parts or not parts[-1].isdigit():
        return f"{tag_version}.dev"
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def _version_from_git_describe() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "describe", "--tags", "--long", "--dirty"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    described = completed.stdout.strip()
    match = re.match(r"^(?P<tag>.+)-(?P<distance>\d+)-g[0-9a-f]+(?:-dirty)?$", described)
    if not match:
        return described or None

    tag_version = _normalise_version(match.group("tag"))
    distance = int(match.group("distance"))
    dirty = described.endswith("-dirty")
    if distance == 0 and not dirty:
        return tag_version
    dev_distance = distance if distance > 0 else 0
    return f"{_bump_version_for_dev(tag_version)}.dev{dev_distance}"


def _derive_version(version_override: str | None = None) -> str:
    raw_version = (
        version_override
        or os.environ.get("SKPPY_VERSION")
        or os.environ.get("SETUPTOOLS_SCM_PRETEND_VERSION")
        or _version_from_setuptools_scm()
        or _version_from_git_describe()
        or "0.0.0"
    )
    return _normalise_version(raw_version)


def _read_manifest_template() -> str:
    return (ADDON_DIR / "blender_manifest.toml").read_text(encoding="utf-8")


def _manifest_with_version(version: str) -> str:
    text = _read_manifest_template()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("version not found in blender_manifest.toml")
    manifest_version = _blender_manifest_version(version)
    return re.sub(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{manifest_version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )


def _blender_manifest_version(version: str) -> str:
    """
    Return a Blender extension manifest-compatible version.

    ``setuptools-scm`` emits PEP 440 development versions such as
    ``0.5.1.dev12`` and, for an untagged root history, ``0.1.dev2``. Blender
    extension manifests require a three-component semantic version. The
    manifest therefore pads omitted minor or patch components and writes the
    PEP 440 prerelease as a SemVer prerelease. The bundled Python package keeps
    the original PEP 440 version.
    """
    match = re.fullmatch(
        r"(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?(?P<suffix>\.dev\d+)?",
        version,
    )
    if not match:
        raise ValueError(f"Cannot convert {version!r} to a Blender manifest version.")

    base = ".".join(
        (
            match.group("major"),
            match.group("minor") or "0",
            match.group("patch") or "0",
        )
    )
    suffix = match.group("suffix")
    if suffix is None:
        return base
    return f"{base}-dev.{suffix.removeprefix('.dev')}"


def _write_bundled_version_file(skppy_dst: Path, version: str) -> None:
    version_file = skppy_dst / "_version.py"
    version_file.write_text(
        f'# Generated by build_blender_addon.py\n__version__ = version = "{version}"\n',
        encoding="utf-8",
    )


def _should_exclude(path: Path) -> bool:
    if any(part in _EXCLUDE_DIRS for part in path.parts):
        return True
    if path.suffix in _EXCLUDE_SUFFIXES:
        return True
    return False


def _display_path(path: Path) -> Path:
    """Return a repository-relative path when both paths share a filesystem root."""
    try:
        return Path(os.path.relpath(path, REPO_ROOT))
    except ValueError:
        # Windows cannot express a relative path between different drive letters.
        return path


def build(clean: bool = False, version_override: str | None = None) -> Path:
    if clean and DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    version = _derive_version(version_override)
    zip_path = DIST_DIR / f"blender_skp_io-{version}.zip"

    display_path = _display_path(zip_path)
    print(f"Building {display_path} ...")
    print(f"  version: {version}")
    manifest_version = _blender_manifest_version(version)
    if manifest_version != version:
        print(f"  manifest version: {manifest_version}")

    # Copy skppy source into the addon directory so the relative import
    # `from .skppy` works in the built addon.
    skppy_dst = ADDON_DIR / "skppy"
    if skppy_dst.exists():
        shutil.rmtree(skppy_dst)
    shutil.copytree(SKPPY_SRC, skppy_dst)
    _write_bundled_version_file(skppy_dst, version)

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(ADDON_DIR.rglob("*")):
                if _should_exclude(path):
                    continue
                if path.is_dir():
                    continue
                arcname = path.relative_to(ADDON_DIR)
                if arcname == Path("blender_manifest.toml"):
                    zf.writestr(str(arcname), _manifest_with_version(version))
                else:
                    zf.write(path, arcname)
                print(f"  + {arcname}")
    finally:
        # Clean up the copied skppy directory
        shutil.rmtree(skppy_dst)

    print(f"\nDone: {zip_path}")
    print(f"  addon files  : {ADDON_DIR}")
    print(f"  bundled skppy: {SKPPY_SRC}")
    return zip_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the blender_skp_io Blender extension zip")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the dist/ directory before building",
    )
    parser.add_argument(
        "--version",
        dest="version",
        help="Override the Git-tag-derived version, e.g. 0.9.0",
    )
    args = parser.parse_args()
    build(clean=args.clean, version_override=args.version)
