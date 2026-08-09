# SPDX-License-Identifier: MIT
"""
Binary file header data class.

.. module:: skppy.data_structure.header
   :synopsis: SKP file header data structure

The header precedes the embedded ZIP archive and encodes product name,
version string, and VFF fields.

Example
-------
::

    header = SkpHeader(
        product_name="SketchUp",
        version_string="{26.1.103}",
        version_tuple=(26, 1, 103),
        vff_magic="...",
        vff_field_1=0, vff_field_2=0, vff_field_3=0, vff_field_4=0,
        zip_offset=12345,
    )
"""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(slots=True)
class SkpHeader:
    """
    Binary header of a .skp file.

    The header is located at the start of the file, before the embedded
    ZIP archive. It contains the product name, version string, and
    VFF (Version File Format) fields.

    Parameters
    ----------
    product_name : str
        Product name (e.g., ``"SketchUp"``).
    version_string : str
        Version string (e.g., ``"{26.1.103}"``).
    version_tuple : tuple of int or None
        Parsed version as a tuple (e.g., ``(26, 1, 103)``).
    vff_magic : str
        VFF magic bytes.
    vff_field_1 : int
        VFF field 1.
    vff_field_2 : int
        VFF field 2.
    vff_field_3 : int
        VFF field 3.
    vff_field_4 : int
        VFF field 4.
    zip_offset : int or None
        Byte offset to the ZIP archive start.
    model_guid : bytes or None, optional
        16-byte model GUID (available via meta/meta.dat).

    Examples
    --------
    >>> h = SkpHeader(product_name="SketchUp", version_string="{26.1.103}",
    ...               version_tuple=(26, 1, 103),
    ...               vff_magic="SU", vff_field_1=0, vff_field_2=0,
    ...               vff_field_3=0, vff_field_4=0, zip_offset=12345)
    >>> h.version_string
    '{26.1.103}'
    """

    product_name: str
    version_string: str
    version_tuple: Optional[Tuple[int, ...]]
    vff_magic: str
    vff_field_1: int
    vff_field_2: int
    vff_field_3: int
    vff_field_4: int
    zip_offset: Optional[int]
    model_guid: Optional[bytes] = None
