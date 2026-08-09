# SPDX-License-Identifier: MIT
"""
Document metadata data classes.

.. module:: skppy.data_structure.document
   :synopsis: Document, header, and ZIP entry data structures

These classes hold the non-geometric metadata extracted from a .skp file:
the binary header, the ZIP container, and individual ZIP entries.

Example
-------
::

    doc = SkpDocument(filepath="model.skp", header=header,
                      zip_entries=entries, model_entry=model_entry)
    doc.dump_zip("extracted/")
"""

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .header import SkpHeader


@dataclass(slots=True)
class SkpZipEntry:
    """
    Metadata for a single ZIP entry in a .skp file.

    Parameters
    ----------
    name : str
        Entry name (path inside the ZIP).
    file_size : int
        Uncompressed file size in bytes.
    compress_size : int
        Compressed file size in bytes.
    crc : int
        CRC-32 checksum.
    is_dir : bool
        Whether this entry is a directory.

    Examples
    --------
    >>> entry = SkpZipEntry(name="model.dat", file_size=1024,
    ...                     compress_size=512, crc=12345, is_dir=False)
    >>> entry.name
    'model.dat'
    >>> entry.is_dir
    False
    """

    name: str
    file_size: int
    compress_size: int
    crc: int
    is_dir: bool


@dataclass(slots=True)
class SkpDocument:
    """
    ZIP container metadata for a .skp file.

    Parameters
    ----------
    filepath : str
        Path to the original .skp file.
    header : SkpHeader
        Parsed binary header.
    zip_entries : list of SkpZipEntry
        All entries in the embedded ZIP archive.
    model_entry : SkpZipEntry or None
        The ``model.dat`` entry, or ``None`` if missing.

    Examples
    --------
    >>> doc = SkpDocument(filepath="model.skp", header=header,
    ...                   zip_entries=entries, model_entry=model_entry)
    >>> doc.dump_zip("extracted/")
    PosixPath('extracted')
    """

    filepath: str
    header: SkpHeader
    zip_entries: List[SkpZipEntry]
    model_entry: Optional[SkpZipEntry]

    def dump_zip(self, output_dir: str) -> Path:
        """
        Extract the ZIP contents to *output_dir*.

        The output preserves the internal SKP folder structure.

        Parameters
        ----------
        output_dir : str
            Destination directory. Created if it does not exist.

        Returns
        -------
        Path
            The resolved output directory path.

        Raises
        ------
        ValueError
            If an entry attempts to write outside *output_dir* (zip-slip guard).

        Examples
        --------
        >>> doc.dump_zip("extracted/")
        PosixPath('extracted')
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(self.filepath, "r") as zf:
            for entry in self.zip_entries:
                target = output_path / Path(entry.name)
                if not self._is_within_directory(output_path, target):
                    raise ValueError(f"Refusing to write outside output directory: {entry.name}")

                if entry.is_dir or entry.name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(entry.name, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

        return output_path

    @staticmethod
    def _is_within_directory(root: Path, target: Path) -> bool:
        """Check that *target* resolves inside *root* (zip-slip guard)."""
        root_resolved = root.resolve()
        target_resolved = target.resolve()
        return root_resolved == target_resolved or root_resolved in target_resolved.parents
