# SPDX-License-Identifier: MIT
"""
Parser for the materials section (tag 0x01F7) of model.dat.

Combines:
  - Binary TLV records (identity, name, and record context)
  - material.xml files from the ZIP archive (color, texture, PBR fields)

Edge Cases and Known Strategies
--------------------------------
Windows-encoded ZIP filenames (CP437 mojibake)
    SKP files saved on Windows may store non-ASCII material folder names with
    their raw UTF-8 bytes un-flagged.  Python's ``zipfile`` module falls back to
    CP437 when the UTF-8 flag is absent, producing mojibake filenames.
    ``build_zip_name_map`` builds a {utf8-corrected -> stored} lookup so that
    ``_zip_read`` can find entries by their intended Unicode name regardless of
    how they were stored.

Missing material.xml
    Not all materials have an accompanying material.xml (e.g. default colours
    created programmatically, or very old SKP files). When the XML entry is
    absent, appearance remains at neutral public defaults; colour uses neutral
    grey and texture image data remains absent. A DEBUG log message is emitted
    and parsing continues.

XML namespace variance
    SketchUp's material.xml uses a Google namespace
    (``http://sketchup.google.com/schemas/sketchup/1.0/material``).  Some files
    produced by third-party tools omit the namespace prefix.  All
    ``root.find()`` calls therefore try the namespaced path first and fall back
    to the bare element name.

Absolute Windows texture paths
    The ``textureFilename`` XML attribute often stores an absolute Windows path
    (e.g. ``C:\\Users\\...\\texture.png``).  Only the ``os.path.basename`` is
    used to locate the file inside the ZIP archive under
    ``materials/<name>/<basename>``.

ZIP-relative image paths (preferred)
    When the ``<images>`` child element is present its ``<image path="...">``
    attribute is tried first.  Paths starting with ``./`` are resolved relative
    to ``materials/<name>/``; paths starting with ``materials/`` are treated as
    ZIP-root-relative; all other paths are assumed to be material-folder-local.

Missing texture data
    If the texture image file cannot be found in the ZIP a ``Texture`` object is
    still created with ``data=None`` so that downstream code knows a texture was
    intended (useful for UV generation) without crashing.  A DEBUG log message
    records the missing path.

PBR fields
    ``pbrMR`` (metallic-roughness) elements are parsed when present.  SketchUp
    stores factors as child elements in observed files, with ``enable_*`` flags
    deciding whether the factors are active.  Models from SketchUp versions
    prior to 2021 typically omit this block, in which case metallic=0.0 and
    roughness=1.0 are used.

Opacity encoding
    SketchUp stores opacity as ``trans`` (0=opaque, 1=fully transparent)
    gated by ``useTrans``.  The parsed ``alpha`` field is always in the
    conventional range 0.0 (transparent) ... 1.0 (opaque).
"""

from __future__ import annotations

import copy
import logging
import os
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import fields
from typing import Dict, List, Mapping, Optional
from xml.parsers import expat

from ..data_structure.images import Texture, normalize_texture_scale
from ..data_structure.materials import Color, Material
from ..data_structure.model_metadata import AttributeDictionary
from .attributes import parse_entity_attribute_dictionaries
from .tlv import (
    TlvTag,
    find_child,
    iter_records,
    read_id_from_wrapper,
    read_utf8,
)
from .vray_materials import apply_vray_xml

logger = logging.getLogger(__name__)

_MAT_NS = "http://sketchup.google.com/schemas/sketchup/1.0/material"
_MAX_MATERIAL_XML_BYTES = 8 * 1024 * 1024


def _parse_bounded_xml(xml_bytes: bytes) -> ET.Element:
    """Parse small XML without permitting DTD or entity declarations.

    Material metadata is untrusted file input. Expat supplies declaration
    callbacks before expansion, while ``TreeBuilder`` keeps the ElementTree API
    used by the material decoder without relying on its permissive convenience
    parser.
    """
    if len(xml_bytes) > _MAX_MATERIAL_XML_BYTES:
        raise ValueError(f"Material XML exceeds the maximum supported size ({_MAX_MATERIAL_XML_BYTES} bytes)")

    builder = ET.TreeBuilder()
    parser = expat.ParserCreate(namespace_separator="}")

    def expanded_name(name: str) -> str:
        return f"{{{name}" if "}" in name else name

    def reject_declaration(*_args: object) -> None:
        raise ValueError("DTD and entity declarations are not allowed in material XML")

    parser.StartElementHandler = lambda name, attrs: builder.start(
        expanded_name(name),
        {expanded_name(key): value for key, value in attrs.items()},
    )
    parser.EndElementHandler = lambda name: builder.end(expanded_name(name))
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration
    parser.ExternalEntityRefHandler = lambda *_args: 0

    try:
        parser.Parse(xml_bytes, True)
    except expat.ExpatError as exc:
        raise ET.ParseError(str(exc)) from exc
    return builder.close()


def _commit_material(target: Material, source: Material) -> None:
    """Install a completely validated material enrichment atomically."""
    for material_field in fields(Material):
        setattr(target, material_field.name, getattr(source, material_field.name))


def build_zip_name_map(zip_file: zipfile.ZipFile) -> Dict[str, str]:
    """
    SKP files created on Windows sometimes store non-ASCII filenames with their
    UTF-8 bytes un-flagged, so Python's zipfile decodes them as CP437 (mojibake).
    Build a lookup map {utf8_corrected_path -> actual_stored_path} so we can
    find entries by their proper Unicode name.
    """
    name_map: Dict[str, str] = {}
    for info in zip_file.infolist():
        stored = info.filename
        try:
            corrected = stored.encode("cp437").decode("utf-8")
            if corrected != stored:
                name_map[corrected] = stored
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
    return name_map


def _zip_read(zip_file: zipfile.ZipFile, path: str, name_map: Mapping[str, str]) -> bytes:
    """Read a ZIP entry by its UTF-8 path, falling back via the name_map.

    Parameters
    ----------
    zip_file : zipfile.ZipFile
        Open ZIP archive.
    path : str
        Intended UTF-8 path of the entry.
    name_map : dict
        Mapping from corrected UTF-8 paths to actual stored paths
        (see :func:`build_zip_name_map`).

    Returns
    -------
    bytes
        Raw content of the ZIP entry.

    Raises
    ------
    KeyError
        If the entry is not found by either the corrected or stored path.
    """
    try:
        return zip_file.read(path)
    except KeyError:
        alt = name_map.get(path)
        if alt is not None:
            return zip_file.read(alt)
        raise


def parse_materials(
    materials_container_payload: bytes,
    zip_file: Optional[zipfile.ZipFile] = None,
    *,
    zip_name_map: Mapping[str, str] | None = None,
    attribute_dictionaries_by_object_id: dict[int, list[AttributeDictionary]] | None = None,
    import_vray_materials: bool = False,
) -> List[Material]:
    """Parse the materials-container payload and return a list of Material objects.

    Parameters
    ----------
    materials_container_payload : bytes
        Raw payload of the MATERIALS_CONTAINER (0x30D4) TLV record.
    zip_file : zipfile.ZipFile or None
        Open ZIP archive for reading material.xml files.  When ``None``,
        materials are populated from TLV identity and name only.

    Returns
    -------
    list of Material
        Parsed materials with color, texture, and PBR fields when XML is
        available.
    """
    mat_list_p = find_child(materials_container_payload, TlvTag.MATERIALS_LIST)
    if not mat_list_p:
        return []

    if zip_name_map is not None:
        resolved_name_map: Mapping[str, str] = zip_name_map
    elif zip_file is not None:
        resolved_name_map = build_zip_name_map(zip_file)
    else:
        resolved_name_map = {}

    materials: List[Material] = []

    for tag, rec_p in iter_records(mat_list_p):
        if tag != TlvTag.MATERIAL_RECORD:
            continue
        materials.append(
            parse_material_record(
                rec_p,
                fallback_id=len(materials),
                zip_file=zip_file,
                zip_name_map=resolved_name_map,
                attribute_dictionaries_by_object_id=(attribute_dictionaries_by_object_id),
                import_vray_materials=import_vray_materials,
            )
        )

    return materials


def parse_material_record(
    record_payload: bytes,
    *,
    fallback_id: int = 0,
    zip_file: Optional[zipfile.ZipFile] = None,
    zip_name_map: Mapping[str, str] | None = None,
    attribute_dictionaries_by_object_id: dict[int, list[AttributeDictionary]] | None = None,
    import_vray_materials: bool = False,
) -> Material:
    """Parse one ``MATERIAL_RECORD`` payload from any modern model section.

    Layer display colors use the same nested record as entries in the global
    material manager. Keeping one decoder prevents those two representations
    from drifting as material fields are discovered.
    """
    # A material is mutable and every following record enriches the same public
    # object. Construct it first so TLV and optional XML data share one target.
    material = Material()
    id_wrap = find_child(record_payload, TlvTag.ID_WRAPPER)
    material.id = read_id_from_wrapper(id_wrap) if id_wrap else fallback_id
    attributes = parse_entity_attribute_dictionaries(record_payload)
    if attributes and attribute_dictionaries_by_object_id is not None:
        attribute_dictionaries_by_object_id[material.id] = attributes

    name_p = find_child(record_payload, TlvTag.MATERIAL_NAME)
    material.name = read_utf8(name_p) if name_p else f"material_{fallback_id}"

    # Neutral gray is the format fallback for records without material.xml.
    material.color = Color(r=128, g=128, b=128, a=255)
    # 0x32CA distinguishes global records (0) from materials embedded in a
    # layer record (1); it does not indicate whether the material has a texture.
    # 0x32CD is likewise not opacity: SDK output associates it with positioned
    # texture cases while ordinary translucent materials store appearance only
    # in material.xml. Keep neutral fallbacks until the XML enrichment below.
    material.alpha = 1.0
    material.has_texture = False

    if zip_file is None:
        return material

    resolved_name_map: Mapping[str, str] = zip_name_map if zip_name_map is not None else build_zip_name_map(zip_file)
    xml_path = f"materials/{material.name}/material.xml"
    try:
        xml_bytes = _zip_read(zip_file, xml_path, resolved_name_map)
        _parse_material_xml(
            xml_bytes,
            material.name,
            zip_file,
            resolved_name_map,
            material=material,
            import_vray_materials=import_vray_materials,
        )
    except KeyError:
        logger.debug(
            "material.xml not found for %r (path: %s)",
            material.name,
            xml_path,
        )
    # A malformed optional XML entry should not discard the material's TLV
    # identity. Restrict fallback to expected data/archive failures so parser
    # programming errors are not silently converted to neutral gray.
    except (
        ET.ParseError,
        TypeError,
        UnicodeError,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        logger.warning("Failed to parse material.xml for %r: %s", material.name, exc)

    return material


def _parse_material_xml(
    xml_bytes: bytes,
    mat_name: str,
    zip_file: zipfile.ZipFile,
    zip_name_map: Mapping[str, str] | None = None,
    *,
    material: Material | None = None,
    import_vray_materials: bool = False,
    image_directory: str | None = None,
    require_material: bool = False,
) -> Material:
    """
    Apply a material.xml document to a mutable material and return it.

    When called independently, a neutral material is created first. The model
    parser passes its TLV-initialized object so malformed or absent optional XML
    never discards the material identity and binary fallbacks. Standalone SKM
    loading sets ``require_material`` to reject unrelated ZIP documents.
    """
    target = material
    if target is None:
        candidate = Material()
        candidate.name = mat_name
        candidate.color = Color(128, 128, 128)
    else:
        # XML and texture data are optional enrichment. Stage every mutation so
        # malformed XML or a bad ZIP CRC preserves the complete TLV fallback.
        candidate = copy.deepcopy(target)

    root = _parse_bounded_xml(xml_bytes)
    ns = {"mat": _MAT_NS}

    mat_el = root.find("mat:material", ns)
    if mat_el is None:
        # Some files have the element without namespace prefix
        mat_el = root.find("material")
    if mat_el is None:
        if require_material:
            raise ValueError("material document does not contain a material element")
        return target if target is not None else candidate

    if target is None:
        candidate.name = mat_el.get("name", candidate.name)

    candidate.color = Color(
        r=_attr_int(mat_el, "colorRed", candidate.color.r),
        g=_attr_int(mat_el, "colorGreen", candidate.color.g),
        b=_attr_int(mat_el, "colorBlue", candidate.color.b),
        a=255,
    )

    trans_val = _attr_float(mat_el, "trans", 1.0 - candidate.alpha)
    use_trans = mat_el.get("useTrans", "0") == "1"
    candidate.alpha = max(0.0, min(1.0, 1.0 - trans_val)) if use_trans else 1.0

    candidate.has_texture = mat_el.get("hasTexture", "0") == "1"
    candidate.texture = None
    if candidate.has_texture:
        candidate.texture = _parse_texture_xml(
            mat_el,
            ns,
            mat_name,
            zip_file,
            zip_name_map or {},
            image_directory=image_directory,
        )
    _apply_pbr_xml(candidate, mat_el, ns)
    if import_vray_materials:
        apply_vray_xml(candidate, mat_el)

    if target is not None:
        _commit_material(target, candidate)
        return target
    return candidate


def _find_optional_element(
    parent: ET.Element,
    namespaced_path: str,
    bare_path: str,
    ns: Dict[str, str],
) -> ET.Element | None:
    """Find one element across namespaced and third-party bare XML variants."""
    element = parent.find(namespaced_path, ns)
    return element if element is not None else parent.find(bare_path)


def _parse_texture_xml(
    material_element: ET.Element,
    ns: Dict[str, str],
    material_name: str,
    zip_file: zipfile.ZipFile,
    zip_name_map: Mapping[str, str],
    *,
    image_directory: str | None = None,
) -> Texture | None:
    """Decode texture metadata and its first available embedded image."""
    texture_element = _find_optional_element(material_element, "mat:texture", "texture", ns)
    if texture_element is None:
        return None

    texture = Texture()
    texture.filename = texture_element.get("textureFilename", "")
    texture.x_scale = normalize_texture_scale(_attr_float(texture_element, "xScale", texture.x_scale))
    texture.y_scale = normalize_texture_scale(_attr_float(texture_element, "yScale", texture.y_scale))
    _load_declared_texture_image(
        texture,
        texture_element,
        ns,
        material_name,
        zip_file,
        zip_name_map,
        image_directory=image_directory,
    )
    if texture.data is None and texture.filename:
        basename = os.path.basename(texture.filename.replace("\\", "/"))
        fallback_directory = image_directory or f"materials/{material_name}"
        fallback_path = f"{fallback_directory}/{basename}"
        try:
            texture.data = _zip_read(zip_file, fallback_path, zip_name_map)
        except KeyError:
            logger.debug("Texture file not found in ZIP: %s", fallback_path)
    if texture.filename:
        texture.filename = os.path.basename(texture.filename.replace("\\", "/"))
    return texture


def _load_declared_texture_image(
    texture: Texture,
    texture_element: ET.Element,
    ns: Dict[str, str],
    material_name: str,
    zip_file: zipfile.ZipFile,
    zip_name_map: Mapping[str, str],
    *,
    image_directory: str | None = None,
) -> None:
    """Load the first valid ZIP-relative image declared by a texture element."""
    images_element = _find_optional_element(texture_element, "mat:images", "images", ns)
    if images_element is None:
        return
    image_elements = images_element.findall("mat:image", ns) or images_element.findall("image")
    for image_element in image_elements:
        image_path = image_element.get("path", "")
        if not image_path:
            continue
        zip_path = _material_image_zip_path(material_name, image_path, image_directory=image_directory)
        try:
            texture.data = _zip_read(zip_file, zip_path, zip_name_map)
        except KeyError:
            logger.debug("Image path not found in ZIP: %s", zip_path)
            continue
        if not texture.filename:
            texture.filename = image_element.get("file_name", image_path)
        return


def _material_image_zip_path(
    material_name: str,
    image_path: str,
    *,
    image_directory: str | None = None,
) -> str:
    """Resolve a material image path according to SKP ZIP conventions."""
    base_directory = image_directory or f"materials/{material_name}"
    relative_path = image_path[2:] if image_path.startswith("./") else image_path
    parts = relative_path.split("/")
    if image_directory is not None and (relative_path.startswith("/") or ".." in parts):
        raise ValueError(f"Unsafe material image path: {image_path!r}")
    if relative_path.startswith(("materials/", "ref/")):
        return relative_path
    return f"{base_directory}/{relative_path}"


def _apply_pbr_xml(material: Material, material_element: ET.Element, ns: Dict[str, str]) -> None:
    """Apply optional metallic/roughness factors with format defaults."""
    material.metallic = 0.0
    material.roughness = 1.0
    pbr_element = _find_optional_element(material_element, "mat:pbrMR", "pbrMR", ns)
    if pbr_element is None:
        return
    material.metallic = _parse_enabled_pbr_float(
        pbr_element,
        ns,
        factor_name="metallicFactor",
        enable_name="enable_metalness",
        disabled_value=0.0,
        factor_default=0.0,
    )
    material.roughness = _parse_enabled_pbr_float(
        pbr_element,
        ns,
        factor_name="roughnessFactor",
        enable_name="enable_roughness",
        disabled_value=1.0,
        factor_default=1.0,
    )


def _parse_enabled_pbr_float(
    pbr_el: ET.Element,
    ns: Dict[str, str],
    *,
    factor_name: str,
    enable_name: str,
    disabled_value: float,
    factor_default: float,
) -> float:
    """Return an enabled PBR factor from either child text or legacy attributes."""
    has_factor_attr = pbr_el.get(factor_name) is not None
    enabled = _child_bool(pbr_el, ns, enable_name, default=has_factor_attr)
    if not enabled:
        return disabled_value
    return _child_float(
        pbr_el,
        ns,
        factor_name,
        default=_attr_float(pbr_el, factor_name, factor_default),
    )


def _attr_float(parent: ET.Element, name: str, default: float) -> float:
    try:
        return float(parent.get(name, default))
    except (TypeError, ValueError):
        return default


def _attr_int(parent: ET.Element, name: str, default: int) -> int:
    """Read an integer XML attribute without invalidating the full material."""
    try:
        return int(parent.get(name, default))
    except (TypeError, ValueError):
        return default


def _child_float(
    parent: ET.Element,
    ns: Dict[str, str],
    name: str,
    *,
    default: float,
) -> float:
    child = parent.find(f"mat:{name}", ns)
    if child is None:
        child = parent.find(name)
    if child is None or child.text is None:
        return default
    try:
        return float(child.text.strip())
    except ValueError:
        return default


def _child_bool(
    parent: ET.Element,
    ns: Dict[str, str],
    name: str,
    *,
    default: bool,
) -> bool:
    child = parent.find(f"mat:{name}", ns)
    if child is None:
        child = parent.find(name)
    if child is None or child.text is None:
        return default
    return child.text.strip().lower() in {"1", "true", "yes"}
