# SPDX-License-Identifier: MIT
"""Configurable byte budgets for loading untrusted model resources."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoadLimits:
    """Bound uncompressed input bytes, not the resulting Python object graph.

    ``max_entry_bytes`` also bounds a whole legacy file. ``max_total_bytes``
    counts cumulative ZIP reads, including repeated resources. XML has a
    separate, smaller limit. All limits must be positive integers.
    """

    max_entry_bytes: int = 1024 * 1024 * 1024
    max_total_bytes: int = 4 * 1024 * 1024 * 1024
    max_xml_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in ("max_entry_bytes", "max_total_bytes", "max_xml_bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
