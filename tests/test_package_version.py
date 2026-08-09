# SPDX-License-Identifier: MIT
"""Package-version fallbacks used by source trees and bundled add-ons."""

from __future__ import annotations

import importlib
import importlib.metadata
import sys

import skppy


def test_package_version_falls_back_to_metadata_and_unknown(monkeypatch):
    generated_module = sys.modules.get("skppy._version")
    original_version = skppy.__version__
    sys.modules["skppy._version"] = None
    try:
        monkeypatch.setattr(importlib.metadata, "version", lambda _name: "9.8.7")
        importlib.reload(skppy)
        assert skppy.__version__ == "9.8.7"

        def missing(_name):
            raise importlib.metadata.PackageNotFoundError

        monkeypatch.setattr(importlib.metadata, "version", missing)
        importlib.reload(skppy)
        assert skppy.__version__ == "0+unknown"
    finally:
        if generated_module is None:
            sys.modules.pop("skppy._version", None)
        else:
            sys.modules["skppy._version"] = generated_module
        importlib.reload(skppy)
        assert skppy.__version__ == original_version
