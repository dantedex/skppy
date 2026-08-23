# SPDX-License-Identifier: MIT
"""Load standalone SketchUp material packages."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
import zipfile

from .data_structure.materials import Material
from .exceptions import InvalidSkmError
from .parser.material_parser import _parse_material_xml, build_zip_name_map


def load_material(
    filepath: str | os.PathLike[str],
    *,
    import_vray_materials: bool = False,
) -> Material:
    """Load one standalone SketchUp material package.

    Package detection uses the ZIP contents rather than the filename suffix,
    so incorrectly named ``.skp`` downloads containing an SKM material are
    accepted as well as conventional ``.skm`` files.

    Parameters
    ----------
    filepath : str or os.PathLike
        Path to a SketchUp material ZIP containing ``document.xml``.
    import_vray_materials : bool, optional
        Prefer supported V-Ray and Enscape PBR values embedded in the material XML.

    Returns
    -------
    Material
        Material appearance, renderer parameters, and embedded textures.

    Raises
    ------
    InvalidSkmError
        If the file is not a supported material package.
    """
    path = os.fspath(filepath)
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("document.xml")
            material = _parse_material_xml(
                xml_bytes,
                os.path.splitext(os.path.basename(path))[0],
                archive,
                build_zip_name_map(archive),
                import_vray_materials=import_vray_materials,
                image_directory="ref",
                require_material=True,
            )
            return material
    except (ET.ParseError, KeyError, TypeError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        raise InvalidSkmError(f"Could not decode a valid SKM file: {path}") from exc
