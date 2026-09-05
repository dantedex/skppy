# SPDX-License-Identifier: MIT
"""
Load a SketchUp .skp file and return a fully parsed Model.

.. module:: skppy.loader
   :synopsis: File loading and parsing pipeline

The :func:`load` function is the primary entry point for reading .skp files.
It handles header parsing, ZIP extraction, and delegates to the model parser
to produce a fully-populated :class:`~skppy.data_structure.model.Model`.

Example
-------
::

    import skppy

    model = skppy.load("architecture.skp")
    print(model.header.version_string)   # e.g. "{23.1.340}"
    print(len(model.materials))
    print(len(model.definitions))
"""

import logging
import os
import struct
import zipfile
from collections.abc import Callable

from ._cancellation import cancellation_scope, check_cancelled
from ._bounded_io import BoundedZipFile, InputLimitError, read_bounded
from .load_limits import LoadLimits
from .data_structure import SkpDocument
from .data_structure.model import Model
from .exceptions import InvalidSkpError, OldFormatError
from .parser.header_parser import parse_header
from .parser.model_parser import parse_model
from .parser.zip_entries import read_zip_entries
from .parser_legacy.parser import parse_legacy_bytes

logger = logging.getLogger(__name__)


def load(
    filepath: str | os.PathLike[str],
    *,
    cancellation_check: Callable[[], bool] | None = None,
    import_vray_materials: bool = False,
    limits: LoadLimits | None = None,
) -> Model:
    """
    Load a SketchUp .skp file and return a fully parsed Model.

    Modern versionless ZIP-based files (SketchUp 2021+) are parsed through the
    TLV parser. Earlier binary files are parsed through the version-aware
    CArchive parser. Container detection is automatic.

    Parameters
    ----------
    filepath : str or os.PathLike
        Path to the .skp file (absolute or relative to the current directory).
    cancellation_check : callable, optional
        Zero-argument callback returning ``True`` when parsing should stop.
        Cancellation raises :class:`~skppy.LoadCancelledError` and is never
        converted to :class:`~skppy.InvalidSkpError`.
    import_vray_materials : bool, optional
        Prefer V-Ray PBR attributes over SketchUp material appearance. The
        default is ``False`` so normal SketchUp materials remain authoritative.
    limits : LoadLimits, optional
        Configurable uncompressed input byte budgets. Defaults to 1 GiB per
        resource and 4 GiB cumulative ZIP reads, with 8 MiB XML resources.

    Returns
    -------
    Model
        Fully populated model containing:

        - ``header``              -- :class:`~skppy.data_structure.header.SkpHeader`
          with product name, version, and zip offset.
        - ``document``            -- :class:`~skppy.data_structure.document.SkpDocument`
          for raw ZIP entry access.
        - ``entities``            -- Root-level geometry
          (vertices, edges, faces, component instances, groups, images,
          curves, arc curves, guide points/lines, section planes).
        - ``definitions``         -- List of
          :class:`~skppy.data_structure.entities.ComponentDefinition`, each with
          their own nested entities and behavior flags.
        - ``materials``           -- List of
          :class:`~skppy.data_structure.materials.Material` (colour, optional
          texture, PBR metallic/roughness).
        - ``layers``              -- List of
          :class:`~skppy.data_structure.layers.Layer`.
        - ``layer_folders``       -- List of
          :class:`~skppy.data_structure.layers.LayerFolder`.
        - ``cameras``             -- List of
          :class:`~skppy.data_structure.construction.Camera` (saved views).
        - ``scenes``              -- List of
          :class:`~skppy.data_structure.scene_data.Scene` (named pages).
        - ``active_layer_id``     -- ID of the layer active when the file was saved.
        - ``rendering_options``   -- :class:`~skppy.data_structure.model_metadata.RenderingOptions`
          (edge display, fog, ground, shadows, AO, etc.).
        - ``shadow_info``         -- :class:`~skppy.data_structure.construction.ShadowInfo`
          (geo-referenced shadows).
        - ``model_view_axes``     -- :class:`~skppy.data_structure.model_metadata.ModelViewAxes`
          (sketch axes).
        - ``line_styles``         -- List of
          :class:`~skppy.data_structure.model_metadata.LineStyle`.
        - ``options_manager``     -- :class:`~skppy.data_structure.model_metadata.OptionsManager`
          (app-level settings).
        - ``environment_data``    -- :class:`~skppy.data_structure.model_metadata.EnvironmentData`
          (sky/IBL presets).
        - ``attribute_dictionaries`` -- List of
          :class:`~skppy.data_structure.model_metadata.AttributeDictionary`.

    Raises
    ------
    FileNotFoundError
        If *filepath* does not exist.
    InvalidSkpError
        If an existing file cannot be decoded as a supported SKP model.

    Examples
    --------
    Basic usage::

        import skppy

        model = skppy.load("architecture.skp")
        print(model.header.version_string)   # e.g. "{23.1.340}"
        print(len(model.materials))
        print(len(model.definitions))

    Traversing geometry::

        for face in model.entities.faces:
            print(face.id, face.plane)
            triangles = face.triangulate(model.entities)

    Inspecting legacy archive provenance::

        model = skppy.load("legacy.skp")
        if model.legacy_archive is not None:
            print(model.legacy_archive.archive_offset)
    """
    path = os.fspath(filepath)
    with cancellation_scope(cancellation_check):
        return _load(path, import_vray_materials=import_vray_materials, limits=limits or LoadLimits())


def _load(path: str, *, import_vray_materials: bool, limits: LoadLimits) -> Model:
    """Load one path inside an already installed cancellation scope."""
    try:
        with open(path, "rb") as fh:
            if not zipfile.is_zipfile(fh):
                fh.seek(0)
                logger.info("Starting to parse pre-ZIP CArchive file: %s", path)
                data = read_bounded(fh, limits.max_entry_bytes, path)
                check_cancelled()
                return parse_legacy_bytes(data, import_vray_materials=import_vray_materials)

            fh.seek(0)
            logger.info("Starting to parse file: %s", path)
            try:
                header = parse_header(fh, locate_zip=True)
            except OldFormatError:
                # Some legacy SKP files carry an unrelated ZIP payload after
                # the CArchive.  ``is_zipfile`` detects that trailing archive,
                # so the authoritative SketchUp header must win dispatch.
                fh.seek(0)
                logger.info("Starting to parse legacy CArchive with appended ZIP: %s", path)
                data = read_bounded(fh, limits.max_entry_bytes, path)
                check_cancelled()
                return parse_legacy_bytes(data, import_vray_materials=import_vray_materials)
            logger.info(
                "Header parsed: product=%r, version=%r, zip_offset=%s",
                header.product_name,
                header.version_string,
                header.zip_offset,
            )

        zip_entries, model_entry = read_zip_entries(path)
        check_cancelled()
        document = SkpDocument(
            filepath=path,
            header=header,
            zip_entries=zip_entries,
            model_entry=model_entry,
        )
        if model_entry is None:
            raise ValueError("SKP ZIP container does not contain model.dat")

        with BoundedZipFile(path, limits=limits) as zf:
            model_data = zf.read("model.dat")
            check_cancelled()
            return parse_model(
                model_data,
                zf,
                header,
                document,
                import_vray_materials=import_vray_materials,
            )
    except (EOFError, KeyError, struct.error, ValueError, zipfile.BadZipFile, InputLimitError) as exc:
        raise InvalidSkpError(f"Could not decode a valid SKP file: {path}") from exc
