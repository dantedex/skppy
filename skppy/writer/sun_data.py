# SPDX-License-Identifier: MIT
"""Modern opaque sun-data serialization."""

from __future__ import annotations

from ..data_structure.model_metadata import SunData
from ..parser.tlv import TlvTag, iter_records
from .tlv import encode_record


def encode_sun_data(sun: SunData) -> bytes:
    """Encode the root sun-data payload while preserving its mapped TLV body."""
    payload = sun.raw_payload
    if payload is None:
        payload = encode_record(TlvTag.SUN_DATA_EXTRA)
    else:
        # Validate framing before embedding caller- or parser-provided bytes.
        list(iter_records(payload))
    return encode_record(TlvTag.SUN_DATA_RECORD, payload)
