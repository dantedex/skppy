# SPDX-License-Identifier: MIT
"""Read model input in cancellable chunks with pre-allocation limits."""

import os
import zipfile
from typing import BinaryIO, IO

from ._cancellation import check_cancelled
from .load_limits import LoadLimits


class InputLimitError(Exception):
    """An input budget was exceeded; optional resource fallbacks must not hide it."""


def read_bounded(stream: IO[bytes], limit: int, label: str) -> bytes:
    """Read at most *limit* bytes, checking cancellation between chunks."""
    data = bytearray()
    while True:
        check_cancelled()
        chunk = stream.read(min(65536, limit - len(data) + 1))
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > limit:
            raise InputLimitError(f"{label!r} exceeds its input byte limit ({limit})")


class BoundedZipFile(zipfile.ZipFile):
    """A parsing archive that rejects oversized resources before extraction."""

    def __init__(self, file: str | os.PathLike[str] | BinaryIO, *, limits: LoadLimits) -> None:
        super().__init__(file, "r")
        self.limits = limits
        self._bytes_read = 0

    def read(self, name: str | zipfile.ZipInfo, pwd: bytes | None = None) -> bytes:
        """Enforce declared and actual resource sizes and the cumulative budget."""
        check_cancelled()
        info = name if isinstance(name, zipfile.ZipInfo) else self.getinfo(name)
        limit = min(self.limits.max_entry_bytes, self.limits.max_total_bytes - self._bytes_read)
        if info.filename.lower().endswith(".xml"):
            limit = min(limit, self.limits.max_xml_bytes)
        if info.file_size > limit:
            raise InputLimitError(f"{info.filename!r} exceeds its input byte limit ({limit})")
        with self.open(info, pwd=pwd) as stream:
            data = read_bounded(stream, limit, info.filename)
        self._bytes_read += len(data)
        return data
