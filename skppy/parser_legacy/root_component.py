# SPDX-License-Identifier: MIT
"""Structured reader for the model's untagged root ``CComponent``."""

from __future__ import annotations

from .component_body import ComponentBodyState, read_component_body
from .object_dispatch import create_object_read_context
from .session import LegacyArchiveSession


def read_root_component(session: LegacyArchiveSession, class_versions: dict[str, int]) -> ComponentBodyState:
    """Read the verified SketchUp 8 ``CComponent::Serialize`` prefix."""
    context = create_object_read_context(session, class_versions)
    return read_component_body(context)
