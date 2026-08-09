# SPDX-License-Identifier: MIT
"""Sphinx configuration for skppy documentation."""

import doctest
import os
import sys

# Make skppy importable for autodoc (docs/ is one level below the repo root)
sys.path.insert(0, os.path.abspath(".."))

# -
# Project metadata
# -
project = "skppy"
copyright = "2026, Dante Dex"
author = "Dante Dex"
try:
    import skppy

    release = skppy.__version__
except Exception:
    release = "0+unknown"

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
html_title = "skppy"
