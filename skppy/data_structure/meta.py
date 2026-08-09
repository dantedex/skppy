# SPDX-License-Identifier: MIT
"""
Parsed model metadata (``model_meta`` section).

The metadata block stores ancillary information about the SketchUp model such
as the version string, thumbnail paths, unit settings, and application name.
Most fields are optional and may be ``None`` when absent from the file.

See :func:`skppy.parser.meta_parser.parse_meta_info` for the parser that
populates this structure.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass(slots=True)
class SkpMetaInfo:
    """Parsed model metadata from the ``model_meta`` section.

    Attributes
    ----------
    version_string : str or None
        SketchUp version that created the file (e.g. ``"{23.1.340}"``).
    model_thumbnail_path : str or None
        Relative path inside the ZIP to the model thumbnail image.
    preview_thumbnail_path : str or None
        Relative path inside the ZIP to the preview thumbnail image.
    unit : str or None
        Display unit string (e.g. ``"Inches"``, ``"Millimeters"``).
    application : str or None
        Application name that created the file.
    temp_skpx_path : str or None
        Temporary SKPX path used during save, if recorded.
    contributors : list of str
        List of contributor names embedded in the file.
    unknown_values : list of str
        Metadata values that could not be decoded.
    raw_strings : list of str
        All raw strings extracted from the metadata block.
    """

    version_string: Optional[str]
    model_thumbnail_path: Optional[str]
    preview_thumbnail_path: Optional[str]
    unit: Optional[str]
    application: Optional[str]
    temp_skpx_path: Optional[str]
    contributors: List[str]
    unknown_values: List[str]
    raw_strings: List[str]
