# SPDX-License-Identifier: MIT
"""Reject material loss before touching an export destination."""

import pytest

import skppy
from skppy.writer.materials import material_entries


@pytest.mark.parametrize("format", ["modern", "sketchup_2017"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tint_color", skppy.Color(128, 128, 128)),
        ("texture_fade", 0.25),
        ("transmission", 0.75),
        ("ior", 2.2),
        ("specular", 0.1),
        ("emission_color", skppy.Color(1, 2, 3)),
        ("emission_strength", 3.0),
        ("bump_map_type", "NORMAL"),
        ("bump_strength", 0.5),
        ("normal_scale", 0.2),
        ("displacement_scale", 0.1),
        *[
            (slot, skppy.Texture(filename="map.png", data=b"pixels"))
            for slot in (
                "metallic_texture",
                "roughness_texture",
                "normal_texture",
                "bump_texture",
                "displacement_texture",
            )
        ],
    ],
)
def test_save_rejects_unsupported_renderer_properties(format, field, value, tmp_path) -> None:
    model = skppy.Model.new()
    material = model.add_material("PBR")
    setattr(material, field, value)
    destination = tmp_path / "model.skp"
    destination.write_bytes(b"previous model")

    with pytest.raises(ValueError, match=f"unsupported export properties: {field}"):
        model.save(destination, format=format, export_vray_materials=True)

    assert destination.read_bytes() == b"previous model"


@pytest.mark.parametrize("format", ["modern", "sketchup_2017"])
def test_save_rejects_duplicate_material_names(format, tmp_path) -> None:
    model = skppy.Model.new()
    model.add_material("Same")
    model.add_material("Same")
    with pytest.raises(ValueError, match="Duplicate material name"):
        model.save(tmp_path / "model.skp", format=format)


def test_material_resources_reject_duplicate_names_and_reserved_image_name() -> None:
    with pytest.raises(ValueError, match="Duplicate material name"):
        material_entries([skppy.Material(name="Same"), skppy.Material(name="Same")])
    material = skppy.Material(name="A", has_texture=True, texture=skppy.Texture(filename="material.xml", data=b"x"))
    with pytest.raises(ValueError, match="safe basename"):
        material_entries([material])


@pytest.mark.parametrize(("field", "value"), [("brightness", 0.5), ("inverted", True)])
def test_export_rejects_unrepresented_base_image_adjustments(field, value) -> None:
    material = skppy.Material(name="Adjusted", has_texture=True, texture=skppy.Texture(filename="a.png", data=b"x"))
    setattr(material.texture, field, value)
    with pytest.raises(ValueError, match=f"texture.{field}"):
        material_entries([material])
