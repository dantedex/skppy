# SPDX-License-Identifier: MIT
"""Modern model options-manager serialization."""

from __future__ import annotations

import struct

from ..data_structure.model_metadata import OptionsManager
from ..parser.tlv import TlvTag
from .tlv import encode_bool, encode_record, encode_records


def encode_options_manager(manager: OptionsManager) -> bytes:
    """Encode the payload of the root options-manager block."""
    names = [provider.name for provider in manager.providers]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Option-provider names must be non-empty and unique")
    providers: list[tuple[int, bytes]] = []
    for provider in manager.providers:
        key_records: list[tuple[int, bytes]] = []
        for key, value in provider.keys.items():
            if not key:
                raise ValueError("Option keys must be non-empty")
            key_records.extend(
                (
                    (TlvTag.OPTIONS_KEY_NAME, key.encode("utf-8")),
                    (TlvTag.ATTR_TYPED_VALUE, _encode_option_value(value)),
                )
            )
        providers.append(
            (
                TlvTag.OPTIONS_PROVIDER_RECORD,
                encode_records(
                    (
                        (TlvTag.OPTIONS_PROVIDER_NAME, provider.name.encode("utf-8")),
                        (TlvTag.OPTIONS_KEY_TABLE, encode_records(key_records)),
                    )
                ),
            )
        )
    return encode_record(
        TlvTag.OPTIONS_MANAGER_RECORD,
        encode_record(TlvTag.OPTIONS_PROVIDER_LIST, encode_records(providers)),
    )


def _encode_option_value(value: bool | int | float | str) -> bytes:
    if isinstance(value, bool):
        return encode_record(TlvTag.ATTR_TYPED_VALUE_BOOL, encode_bool(value))
    if isinstance(value, int):
        if not -(2**31) <= value < 2**31:
            raise ValueError("Integer option values must fit in i32")
        return encode_record(TlvTag.ATTR_TYPED_VALUE_TYPE, struct.pack("<i", value))
    if isinstance(value, float):
        return encode_record(TlvTag.ATTR_TYPED_VALUE_F64, struct.pack("<d", value))
    if isinstance(value, str):
        return encode_record(TlvTag.ATTR_TYPED_VALUE_STRING, value.encode("utf-8"))
    raise TypeError(f"Unsupported option value type: {type(value).__name__}")
