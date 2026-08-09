# SPDX-License-Identifier: MIT
"""
Parser for the ``meta/meta.dat`` entry inside a SketchUp ZIP archive.

Entry points::

    from skppy.parser.meta_parser import parse_meta_info, parse_meta_info_from_zip
"""

from __future__ import annotations

import logging
import re
import zipfile
from typing import List, Optional

from ..data_structure.meta import SkpMetaInfo

logger = logging.getLogger(__name__)


def parse_meta_info(data: bytes) -> SkpMetaInfo:
    """
    Parse raw ``meta/meta.dat`` bytes into a :class:`SkpMetaInfo` object.

    The meta.dat file contains a mix of binary blobs and ASCII strings.
    All printable ASCII subsequences of four characters or longer are
    extracted and then classified by pattern matching.

    Parameters
    ----------
    data : bytes
        Raw bytes read from the ``meta/meta.dat`` ZIP entry.

    Returns
    -------
    SkpMetaInfo
        Parsed metadata with version string, unit, application name,
        thumbnail paths, and any unrecognised string values.
    """
    raw_strings = _extract_ascii_strings(data)

    version_string = _first_match(raw_strings, r"\d+\.\d+\.\d+")
    model_thumbnail_path = _first_match(raw_strings, r"meta/model_thumbnail\.png")
    preview_thumbnail_path = _first_match(raw_strings, r"meta/preview_thumbnail\.png")
    unit = _first_match(raw_strings, r"\b(Inches|Meters?|Feet|Centimeters?|Millimeters?)\b")
    application = _first_match(raw_strings, r"SketchUp")
    temp_skpx_path = _first_match(raw_strings, r"\S+\.skpx")

    known_values = {
        v
        for v in [
            version_string,
            model_thumbnail_path,
            preview_thumbnail_path,
            unit,
            application,
            temp_skpx_path,
        ]
        if v
    }

    candidates = []
    for value in raw_strings:
        normalized = _strip_type_suffix(value)
        if normalized in known_values:
            continue
        # Some fields are extracted from a larger descriptive string, such as
        # ``SketchUp Pro``. The enclosing string is metadata too, not a person
        # or an unknown value.
        if any(known and known in normalized for known in (version_string, unit, application)):
            continue
        if normalized in {"Model", "ModelProperties"}:
            continue
        if normalized.startswith("meta/"):
            continue
        if _looks_like_path(normalized):
            continue
        candidates.append(normalized)

    contributors = candidates
    unknown_values = candidates

    if unknown_values:
        logger.info("meta/meta.dat: unclassified strings: %s", unknown_values)

    return SkpMetaInfo(
        version_string=version_string,
        model_thumbnail_path=model_thumbnail_path,
        preview_thumbnail_path=preview_thumbnail_path,
        unit=unit,
        application=application,
        temp_skpx_path=temp_skpx_path,
        contributors=contributors,
        unknown_values=unknown_values,
        raw_strings=raw_strings,
    )


def parse_meta_info_from_zip(filepath: str) -> SkpMetaInfo:
    """
    Open a .skp file as a ZIP archive and parse its ``meta/meta.dat`` entry.

    Parameters
    ----------
    filepath : str
        Path to the .skp file.

    Returns
    -------
    SkpMetaInfo
        Parsed metadata extracted from ``meta/meta.dat``.

    Raises
    ------
    KeyError
        If the ZIP archive does not contain a ``meta/meta.dat`` entry.
    zipfile.BadZipFile
        If *filepath* is not a valid ZIP archive.
    """
    with zipfile.ZipFile(filepath, "r") as zf:
        data = zf.read("meta/meta.dat")
    return parse_meta_info(data)


# -
# Internal helpers
# -


def _extract_ascii_strings(data: bytes, min_length: int = 4) -> List[str]:
    """Extract all printable ASCII substrings of *min_length* or more.

    Parameters
    ----------
    data : bytes
        Raw binary data from meta.dat.
    min_length : int
        Minimum substring length (default 4).

    Returns
    -------
    list of str
        All matching ASCII strings.
    """
    pattern = rb"[ -~]{%d,}" % min_length
    return [match.decode("ascii", errors="replace") for match in re.findall(pattern, data)]


def _first_match(values: List[str], pattern: str) -> Optional[str]:
    """Return the first regex match from a list of strings.

    Parameters
    ----------
    values : list of str
        Strings to search.
    pattern : str
        Regular expression pattern.

    Returns
    -------
    str or None
        The first matched substring, or ``None``.
    """
    regex = re.compile(pattern)
    for value in values:
        match = regex.search(value)
        if match:
            return match.group(0)
    return None


def _strip_type_suffix(value: str) -> str:
    """Remove a single trailing type-suffix character from a string.

    SketchUp sometimes appends a type-indicator character (e.g. ``"ModelP"``
    where ``P`` indicates a pointer).  This strips that suffix when the
    remaining core looks like a known path or numeric identifier.

    Parameters
    ----------
    value : str
        Raw string from meta.dat.

    Returns
    -------
    str
        String with trailing suffix removed, or the original string.
    """
    if len(value) < 2:
        return value
    # Serialized type markers are uppercase suffixes (for example the ``P``
    # in ``ModelP``). Requiring that shape prevents ordinary names such as
    # ``Alice`` from being shortened to ``Alic`` during classification.
    if not value[-1].isupper():
        return value
    core = value[:-1]
    if core.endswith(".png") or core.endswith(".skpx"):
        return core
    if any(ch.isdigit() for ch in core):
        return core
    if core.isalpha() and core[-1].islower():
        return core
    return value


def _looks_like_path(value: str) -> bool:
    """Return ``True`` if *value* looks like a filesystem path.

    Parameters
    ----------
    value : str
        String to test.

    Returns
    -------
    bool
        ``True`` if the string contains ``/`` or ``\\``.
    """
    return "/" in value or "\\" in value
