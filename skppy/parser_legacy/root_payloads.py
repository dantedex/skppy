# SPDX-License-Identifier: MIT
"""Readers for root-model scalar fields surrounding the object graph."""

from __future__ import annotations

from typing import BinaryIO

from .parser_types import PostRenderingPayload
from .binary import LegacyArchiveReader


def read_post_rendering_model_data(stream: BinaryIO, *, model_class_version: int) -> PostRenderingPayload:
    """Read model scalars preceding the serialized root ``CComponent``."""
    reader = LegacyArchiveReader(stream)
    start = reader.tell()
    obsolete_vertex_count = reader.read_u32()
    validity_check_performed = reader.read_u32() if model_class_version >= 18 else None
    return PostRenderingPayload(
        start,
        obsolete_vertex_count,
        validity_check_performed,
        reader.tell(),
    )
