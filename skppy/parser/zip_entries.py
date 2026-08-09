# SPDX-License-Identifier: MIT
"""
ZIP entry reader.

.. module:: skppy.parser.zip_entries
   :synopsis: ZIP entry reading utilities

Provides a function to read metadata for all entries from the embedded ZIP
archive of a .skp file.

Example
-------

    >>> entries, model_entry = read_zip_entries("model.skp")
"""

from __future__ import annotations

import logging
import zipfile
from typing import List, Optional, Tuple

from ..data_structure.document import SkpZipEntry

logger = logging.getLogger(__name__)


def read_zip_entries(filepath: str) -> Tuple[List[SkpZipEntry], Optional[SkpZipEntry]]:
    """
    Read all ZIP entries from a .skp file.

    Parameters
    ----------
    filepath : str
        Path to the .skp file.

    Returns
    -------
    tuple of (list of SkpZipEntry, SkpZipEntry or None)
        All entries and the ``model.dat`` entry (or ``None`` if missing).

    Examples
    --------
    >>> entries, model_entry = read_zip_entries("model.skp")
    >>> model_entry.name
    'model.dat'
    """
    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            entries = [
                SkpZipEntry(
                    name=info.filename,
                    file_size=info.file_size,
                    compress_size=info.compress_size,
                    crc=info.CRC,
                    is_dir=info.is_dir(),
                )
                for info in zf.infolist()
            ]
    except zipfile.BadZipFile:
        logger.warning("File is not a valid ZIP container: %s", filepath)
        return [], None

    model_entry = next((entry for entry in entries if entry.name == "model.dat"), None)
    return entries, model_entry
