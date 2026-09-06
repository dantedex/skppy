# SPDX-License-Identifier: MIT
"""Shared semantic checks for material export, independent of wire format."""

from collections.abc import Iterable

from .data_structure.materials import Material


def validate_material_names(materials: Iterable[Material]) -> None:
    """Reject names that would alias another material's resources."""
    names: set[str] = set()
    for material in materials:
        if material.name in names:
            raise ValueError(f"Duplicate material name: {material.name!r}")
        names.add(material.name)


def validate_material_export(material: Material) -> None:
    """Reject renderer properties that neither supported writer can preserve."""
    defaults = Material()
    fields = (
        "tint_color",
        "texture_fade",
        "transmission",
        "opacity_texture",
        "specular",
        "ior",
        "emission_color",
        "emission_strength",
        "bump_map_type",
        "bump_strength",
        "normal_scale",
        "displacement_scale",
        "metallic_texture",
        "roughness_texture",
        "normal_texture",
        "bump_texture",
        "displacement_texture",
    )
    unsupported = [name for name in fields if getattr(material, name) != getattr(defaults, name)]
    if material.texture is not None:
        if material.texture.brightness != 1.0:
            unsupported.append("texture.brightness")
        if material.texture.inverted:
            unsupported.append("texture.inverted")
        if material.texture.uv_scale != (1.0, 1.0):
            unsupported.append("texture.uv_scale")
    if unsupported:
        raise ValueError(f"Material {material.name!r} has unsupported export properties: {', '.join(unsupported)}")
