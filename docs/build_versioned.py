# SPDX-License-Identifier: MIT
"""Build main and tagged documentation into stable GitHub Pages paths."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")
ROOT_REDIRECT = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="0; url=./latest/">
    <link rel="canonical" href="./latest/">
    <title>skppy documentation</title>
  </head>
  <body><p>Continue to the <a href="./latest/">latest skppy documentation</a>.</p></body>
</html>
"""


def _run_git(repo_root: Path, *args: str) -> str:
    """Run Git in the repository and return decoded standard output."""
    result = subprocess.run(
        ("git", *args),
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def _document_names(source_directory: Path) -> list[str]:
    """Return Sphinx document names available in a source tree."""
    documents = []
    for suffix in ("*.rst", "*.md"):
        for source in source_directory.rglob(suffix):
            relative = source.relative_to(source_directory)
            if "_build" in relative.parts or relative.name == "README.md":
                continue
            documents.append(relative.with_suffix("").as_posix())
    return sorted(set(documents))


def _tag_documents(repo_root: Path, tag: str) -> list[str]:
    """Read documentation names from one Git tag without a checkout."""
    archive = subprocess.run(
        ("git", "archive", "--format=tar", tag, "--", "docs"),
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    with tempfile.TemporaryDirectory() as temporary_directory:
        with tarfile.open(fileobj=BytesIO(archive)) as archive_file:
            archive_file.extractall(temporary_directory)
        return _document_names(Path(temporary_directory) / "docs")


def discover_versions(repo_root: Path) -> list[dict[str, object]]:
    """Describe the development docs and all semantic release tags."""
    versions: list[dict[str, object]] = [
        {
            "label": "latest",
            "path": "latest",
            "ref": "main",
            "documents": _document_names(repo_root / "docs"),
        }
    ]
    tags = []
    for tag in _run_git(repo_root, "tag", "--list").splitlines():
        match = TAG_PATTERN.fullmatch(tag)
        if match:
            public_version = match.group("version")
            numeric_version = tuple(int(part) for part in public_version.split("."))
            tags.append((numeric_version, tag, public_version))

    for _, tag, public_version in sorted(tags, reverse=True):
        versions.append(
            {
                "label": public_version,
                "path": public_version,
                "ref": tag,
                "documents": _tag_documents(repo_root, tag),
            }
        )
    return versions


def _extract_source(repo_root: Path, ref: str, destination: Path) -> None:
    """Extract a trusted Git revision and add its generated version module."""
    archive = subprocess.run(
        ("git", "archive", "--format=tar", ref),
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    with tarfile.open(fileobj=BytesIO(archive)) as archive_file:
        archive_file.extractall(destination)


def _write_version_module(source_root: Path, release: str) -> None:
    """Provide the generated setuptools-scm module absent from Git archives."""
    parts = tuple(int(part) for part in release.split("."))
    module = (
        "# SPDX-License-Identifier: MIT\n"
        f"__version__ = version = {release!r}\n"
        f"__version_tuple__ = version_tuple = {parts!r}\n"
        "__commit_id__ = commit_id = None\n"
    )
    (source_root / "skppy" / "_version.py").write_text(module, encoding="utf-8")


def build_versioned_docs(repo_root: Path, output_directory: Path) -> None:
    """Build current and released documentation with the installed Sphinx."""
    versions = discover_versions(repo_root)
    shutil.rmtree(output_directory, ignore_errors=True)
    output_directory.mkdir(parents=True)
    serialized_versions = json.dumps(versions, separators=(",", ":"))

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        for item in versions:
            public_path = str(item["path"])
            if public_path == "latest":
                source_root = repo_root
                release = "latest"
            else:
                source_root = temporary_root / public_path
                _extract_source(repo_root, str(item["ref"]), source_root)
                release = public_path
                _write_version_module(source_root, release)

            environment = os.environ.copy()
            environment.update(
                {
                    "SKPPY_DOC_CURRENT": public_path,
                    "SKPPY_DOC_PACKAGE_ROOT": str(source_root),
                    "SKPPY_DOC_RELEASE": release,
                    "SKPPY_DOC_VERSIONS": serialized_versions,
                }
            )
            subprocess.run(
                (
                    sys.executable,
                    "-m",
                    "sphinx",
                    "-b",
                    "html",
                    "-W",
                    "--keep-going",
                    "-c",
                    str(repo_root / "docs"),
                    str(source_root / "docs"),
                    str(output_directory / public_path),
                ),
                cwd=source_root,
                env=environment,
                check=True,
            )

    (output_directory / ".nojekyll").touch()
    (output_directory / "index.html").write_text(ROOT_REDIRECT, encoding="utf-8")


def main() -> None:
    """Build versioned documentation from command-line paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    build_versioned_docs(repo_root, args.output_directory.resolve())


if __name__ == "__main__":
    main()
