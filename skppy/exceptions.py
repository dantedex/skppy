# SPDX-License-Identifier: MIT
"""
Custom exceptions for skppy.

.. module:: skppy.exceptions
   :synopsis: Exception classes for skppy

OldFormatError
    Raised when the ZIP-specific header parser receives a legacy pre-ZIP file.
    The public :func:`skppy.load` entry point detects that format first and
    routes supported pre-ZIP files to the CArchive parser.

Example
-------
::

    with open("model.skp", "rb") as stream:
        try:
            header = parse_header(stream)
        except skppy.OldFormatError:
            model = skppy.load("model.skp")

InvalidSkpError
    Raised by :func:`skppy.load` when an existing file cannot be decoded as a
    supported SketchUp model.
"""

from __future__ import annotations


class InvalidSkpError(Exception):
    """An existing file cannot be decoded as a valid supported SKP model.

    The public loader translates malformed container and binary-payload
    failures into this exception while retaining the original exception as
    ``__cause__``. Filesystem errors such as :class:`FileNotFoundError` and
    :class:`PermissionError` deliberately remain standard Python errors.
    """


class ComponentCycleError(ValueError):
    """A component definition recursively references its active ancestry."""


class LoadCancelledError(Exception):
    """A caller cooperatively cancelled an in-progress SKP load."""


class OldFormatError(Exception):
    """
    Signal that a file belongs to the legacy pre-ZIP parser.

    This exception belongs to the modern ZIP header parser. Normal callers
    should use :func:`skppy.load`, which detects pre-ZIP CArchive files and
    dispatches them to :mod:`skppy.parser_legacy` before this exception is raised.

    Parameters
    ----------
    message : str
        Human-readable error description.
    filepath : str or None, optional
        Path to the file that triggered the error.

    Attributes
    ----------
    filepath : str or None
        Path to the file that triggered the error, if available.
    message : str
        Human-readable error description.

    Example
    -------
    ::

        with open("old_file.skp", "rb") as stream:
            try:
                header = parse_header(stream)
            except skppy.OldFormatError:
                model = skppy.load("old_file.skp")
    """

    def __init__(self, message: str, filepath: str | None = None):
        """
        Store the message and optional file path for a legacy-format failure.

        Parameters
        ----------
        message : str
            Human-readable error description.
        filepath : str or None, optional
            Path to the legacy file, when available.
        """
        self.filepath = filepath
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        if self.filepath:
            return f"{self.message} (file: {self.filepath})"
        return self.message
