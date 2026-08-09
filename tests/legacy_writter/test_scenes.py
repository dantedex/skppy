# SPDX-License-Identifier: MIT
"""Raw SU2017 scene, page-list, and camera writer fixtures."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.model import _LegacyModelEncoder


def test_scene_camera_matches_raw_carchive_payload() -> None:
    model = skppy.Model.new()
    model.scenes = [
        skppy.Scene(
            id=1,
            name="View",
            description="Test",
            flags=1,
            camera=skppy.Camera(
                eye=skppy.Vector3D(1, 2, 3),
                target=skppy.Vector3D(0, 0, 0),
                up=skppy.Vector3D(0, 0, 1),
                name="Camera",
            ),
        )
    ]
    encoder = _LegacyModelEncoder(model, model.entities)
    encoder.data.clear()
    encoder._write_page_list()
    expected = bytes.fromhex(
        "00000001000000ffff0d00090043566965775061676500000101fffeff045600690065007700fffeff04540065007300740001000000078000000000"
        "0000f03f0000000000000040000000000000084000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        "000000000000f03f000000000000f03f000000000088c340010000000000804140000000000000f03f00000000000000000000000000000000000000"
        "000000000000000000000000000100fffeff06430061006d00650072006100000000000000000000000000000000f03f000000000000000000000000"
        "0000000001000000000000f0bf000000000000f0bf000000000a00"
    )

    assert encoder.data == expected


def test_writes_scene_shadow_axes_and_reference_sets() -> None:
    model = skppy.Model.new()
    layer = model.add_layer("Hidden")
    edge = model.entities.add_edge(model.entities.add_vertex(0, 0, 0), model.entities.add_vertex(1, 0, 0))
    section = skppy.SectionPlane(id=4, plane=(0, 0, 1, 0), layer_id=layer.id)
    model.entities.section_planes.append(section)
    model.shadow_info = skppy.ShadowInfo(display_shadows=True)
    model.scenes = [
        skppy.Scene(
            id=1,
            name="State",
            flags=0x7C,
            hidden_entity_ids=[edge.id],
            hidden_layer_ids=[layer.id],
            active_section_plane_ids=[section.id],
        )
    ]

    encoded = build_legacy_2017_model(model)

    assert b"CViewPage" in encoded
    assert "State".encode("utf-16le") in encoded


def test_scene_rendering_snapshot_matches_raw_carchive_payload() -> None:
    model = skppy.Model.new()
    model.rendering_options = skppy.RenderingOptions(render_mode=3, draw_ground=True)
    model.scenes = [skppy.Scene(1, "Render", flags=2)]
    encoder = _LegacyModelEncoder(model, model.entities)
    encoder.data.clear()
    encoder._write_page_list()
    expected = bytes.fromhex(
        "00000001000000ffff0d00090043566965775061676500000101fffeff06520065006e00640065007200fffeff000200"
        "00000000000300000000000000000000ffffffff000000ff00ff00ff808080ff00000001000000000000000000000000"
        "000000000000000000000000000000000000ffffffffccccccff00000000000000000000000000000000000000cccccc"
        "ff000000000000000000000000000000000000000000000000000001010087ceebffc0d8e8ff8b4513ff000100000000"
        "00000000ff808080ff000000ff00000000000000000000000000000000000000000000808080ff000000000000000000"
        "00000000000000000000000000000000000000000001000000000000f0bf000000000000f0bf000000000a00"
    )

    assert encoder.data == expected


def test_scene_style_is_declared_inline_and_reused_by_registry() -> None:
    style = skppy.StyleDescriptor(guid=bytes(range(16)), display_name="Draft", file_name="Style")
    registry = skppy.StylesRegistry(styles=[style], active_style_ref=1)
    model = skppy.Model.new()
    model.styles_registry = registry
    model.scenes = [skppy.Scene(1, "Style", flags=2, style_reference=1)]
    encoder = _LegacyModelEncoder(model, model.entities)
    encoder.data.clear()

    encoder._write_page_list()
    assert encoder.data.count(b"CSkpStyle") == 1
    encoder.data.clear()
    encoder._write_styles_registry(registry, skppy.WatermarkManager())

    assert encoder.data == bytes.fromhex("000000010000000c000c00000000")


@pytest.mark.parametrize(
    ("scene", "message"),
    [
        (skppy.Scene(1, "Style", style_reference=1), "use-rendering-options flag"),
        (skppy.Scene(1, "Style", flags=2, style_reference=2), "registered style"),
        (skppy.Scene(1, "Background", background_image_ref=1), "unknown background image reference"),
        (skppy.Scene(1, "Display", display_background_image=True), "requires an image"),
        (skppy.Scene(1, "Missing Camera", flags=1), "requires a camera snapshot"),
        (skppy.Scene(1, "Extra Camera", camera=skppy.Camera()), "requires the use-camera flag"),
        (skppy.Scene(1, "Hidden", hidden_entity_ids=[1]), "hidden entities require"),
    ],
)
def test_rejects_unsupported_or_inconsistent_scene_state(scene: skppy.Scene, message: str) -> None:
    model = skppy.Model.new()
    model.scenes = [scene]

    with pytest.raises((ValueError, NotImplementedError), match=message):
        build_legacy_2017_model(model)


@pytest.mark.parametrize(
    "scenes, message",
    [
        ([skppy.Scene(0, "Zero")], "IDs must be positive"),
        ([skppy.Scene(1, "One"), skppy.Scene(1, "Two")], "IDs must be positive"),
        ([skppy.Scene(1, "")], "names must be non-empty"),
        ([skppy.Scene(1, "Same"), skppy.Scene(2, "Same")], "names must be non-empty"),
    ],
)
def test_rejects_invalid_scene_identity(scenes: list[skppy.Scene], message: str) -> None:
    model = skppy.Model.new()
    model.scenes = scenes

    with pytest.raises(ValueError, match=message):
        build_legacy_2017_model(model)


def test_rejects_unknown_scene_references() -> None:
    model = skppy.Model.new()
    model.scenes = [skppy.Scene(1, "Missing", flags=0x70, hidden_entity_ids=[1])]

    with pytest.raises(ValueError, match="unknown entity reference 1"):
        build_legacy_2017_model(model)
