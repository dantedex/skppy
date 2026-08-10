# SPDX-License-Identifier: MIT
"""Sphinx configuration for skppy documentation."""

import doctest
import json
import os
from pathlib import Path
import posixpath
import sys

# Make the selected source version importable for autodoc. The versioned build
# points this at each extracted Git tag in turn.
package_root = os.environ.get("SKPPY_DOC_PACKAGE_ROOT", str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, package_root)

# -
# Project metadata
# -
project = "skppy"
copyright = "2026, Dante Dex"
author = "Dante Dex"
try:
    import skppy

    release = os.environ.get("SKPPY_DOC_RELEASE", skppy.__version__)
except Exception:
    release = os.environ.get("SKPPY_DOC_RELEASE", "0+unknown")

# -
# Extensions
# -
extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosummary",
    "sphinx.ext.doctest",
]

doctest_default_flags = doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE
# Only explicit ``doctest`` directives are executable documentation. Autodoc
# may display illustrative prompts that depend on user files or surrounding
# imports and therefore are not standalone tests.
doctest_test_doctest_blocks = ""

# Auto-generate summary tables from autodoc
autosummary_generate = True

# Autodoc settings
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
}
autodoc_typehints = "signature"
autodoc_class_signature = "separated"

# Napoleon settings (for Google/NumPy-style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_use_admonition_for_notes = True
napoleon_use_param = True
napoleon_use_rtype = True

# MyST-Parser options: enable common Markdown extensions
myst_enable_extensions = [
    "colon_fence",  # ::: directives
    "deflist",  # definition lists
    "tasklist",  # - [ ] checkboxes
]

# -
# Source files
# -
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
master_doc = "index"
templates_path = ["_templates"]
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "README.md",
]

# -
# HTML output
# -
html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["versioning.css"]
html_title = "skppy"
html_sidebars = {
    "**": [
        "sidebar/brand.html",
        "versioning.jinja",
        "sidebar/search.html",
        "sidebar/scroll-start.html",
        "sidebar/navigation.html",
        "sidebar/scroll-end.html",
        "sidebar/variant-selector.html",
    ],
}


def _add_version_context(app, pagename, templatename, context, doctree):
    """Add the manually built documentation versions to HTML templates."""
    del app, templatename, doctree
    serialized_versions = os.environ.get("SKPPY_DOC_VERSIONS")
    current_path = os.environ.get("SKPPY_DOC_CURRENT")
    if not serialized_versions or not current_path:
        return

    current_directory = posixpath.dirname(posixpath.join(current_path, pagename))
    versions = json.loads(serialized_versions)
    for item in versions:
        target_page = pagename if pagename in item["documents"] else "index"
        target = posixpath.join(item["path"], f"{target_page}.html")
        item["url"] = posixpath.relpath(target, current_directory)
        item["current"] = item["path"] == current_path
    context["documentation_versions"] = versions


def setup(app):
    """Register the version selector context hook."""
    app.connect("html-page-context", _add_version_context)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
