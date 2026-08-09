# SPDX-License-Identifier: MIT
"""Readers for legacy typed values and model option providers."""

from __future__ import annotations

from typing import Any, BinaryIO

from ..data_structure.model_metadata import OptionsManager, OptionsProvider

from .binary import LegacyArchiveReader

_SCALAR_TYPED_VALUE_READERS = {
    2: LegacyArchiveReader.read_u8,
    3: LegacyArchiveReader.read_u16,
    4: LegacyArchiveReader.read_u32,
    5: LegacyArchiveReader.read_f32,
    6: LegacyArchiveReader.read_f64,
    7: LegacyArchiveReader.read_bool,
    8: LegacyArchiveReader.read_u32,
    9: LegacyArchiveReader.read_u32,
    12: LegacyArchiveReader.read_f64,
    13: LegacyArchiveReader.read_f64,
    14: LegacyArchiveReader.read_f64,
    15: LegacyArchiveReader.read_f64,
    16: LegacyArchiveReader.read_f64,
}


def read_typed_value(stream: BinaryIO) -> Any:
    """Read one old-format ``CTypedValue`` record as a native Python value."""
    reader = LegacyArchiveReader(stream)
    start = reader.tell()
    type_code = reader.read_u8()

    # These codes mirror the observed legacy typed-value encoding. Several semantic
    # types share one primitive wire representation, so preserve the native
    # value here and let the owning option provide its meaning.
    scalar_reader = _SCALAR_TYPED_VALUE_READERS.get(type_code)
    if scalar_reader is not None:
        return scalar_reader(reader)
    if type_code == 0:
        return None
    value: Any
    if type_code == 10:
        value = reader.read_legacy_utf16_string("typed string")
    elif type_code == 11:
        # Arrays contain complete nested CTypedValue records, including their
        # own type byte; they are not a homogeneous primitive array.
        value = tuple(read_typed_value(stream) for _ in range(reader.read_u32()))
    elif type_code in {17, 18, 19}:
        value = tuple(reader.read_f64() for _ in range(3))
    elif type_code == 20:
        value = tuple(reader.read_f64() for _ in range(16))
    else:
        raise ValueError(f"Unsupported CTypedValue type {type_code} at offset {start}.")

    return value


def read_options_manager(stream: BinaryIO) -> OptionsManager:
    """Read ``COptionsManager::Serialize`` into the shared options model."""
    reader = LegacyArchiveReader(stream)
    reader.read_u32()  # Options-manager serialization version.
    option_set_count = reader.read_u32()
    manager = OptionsManager()

    for _ in range(option_set_count):
        option_set_name = reader.read_legacy_utf16_string("option set name")
        options: dict[str, bool | int | float | str] = {}
        # Providers do not serialize an entry count. An empty UTF-16 key is the
        # terminator, so consuming it is part of reaching the next provider.
        while True:
            option_name = reader.read_legacy_utf16_string("option name")
            if not option_name:
                break
            # The shared modern/legacy API stores provider values as strings;
            # typed decoding still happens first to normalize booleans cleanly.
            options[option_name] = _option_value_to_string(read_typed_value(stream))
        manager.providers.append(OptionsProvider(name=option_set_name, keys=options))

    return manager


def _option_value_to_string(value: Any) -> str:
    """Convert a typed legacy option to the public provider representation."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
