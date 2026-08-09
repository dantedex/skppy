# SPDX-License-Identifier: MIT
"""Modern SKP writing and independently testable encoding primitives."""

from .container import build_modern_container, write_modern_container
from .attributes import encode_attribute_dictionaries
from .entities import encode_entities
from .fonts import default_fonts, encode_fonts
from .model_data import (
    build_model_container,
    default_modern_header,
    encode_model_data,
    write_model as write_modern_model,
)
from .model_metadata import (
    encode_model_view_axes,
    encode_rendering_options,
    encode_shadow_info,
)
from .scenes import encode_scenes
from .tlv import encode_bool, encode_compact_int, encode_record

__all__ = [
    "build_model_container",
    "build_modern_container",
    "default_fonts",
    "default_modern_header",
    "encode_attribute_dictionaries",
    "encode_bool",
    "encode_compact_int",
    "encode_entities",
    "encode_fonts",
    "encode_model_data",
    "encode_model_view_axes",
    "encode_record",
    "encode_rendering_options",
    "encode_scenes",
    "encode_shadow_info",
    "write_modern_container",
    "write_modern_model",
]
