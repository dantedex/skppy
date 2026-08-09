# SPDX-License-Identifier: MIT
"""Raw SU2017 compatibility-extension fixtures for view metadata."""

import pytest

import skppy
from skppy.legacy_writter import build_legacy_2017_model
from skppy.legacy_writter.extensions import EXTENSION_DICTIONARY_NAME


def test_view_metadata_matches_raw_legacy_extension_payload() -> None:
    model = skppy.Model.new()
    model.model_view_axes = skppy.ModelViewAxes(flags=9)
    model.cameras = [skppy.Camera(allow_clipping=False)]
    model.rendering_options = skppy.RenderingOptions(draw_hidden_objects=True)
    model.styles_registry = skppy.StylesRegistry(
        styles=[
            skppy.StyleDescriptor(
                file_name="Style",
                display_name="Display",
                xml_data=b"<x/>",
            ),
        ],
        active_style_ref=1,
    )
    model.scenes = [
        skppy.Scene(
            1,
            "S",
            flags=1,
            camera=skppy.Camera(allow_clipping=False),
            raw_payload=b"raw",
        ),
    ]
    expected = (
        '{"axes_flags":9,"camera_allow_clipping":false,"rendering":{"ambient_occlusion":false,'
        '"ao_color":4294967295,"ao_color_enabled":false,"ao_distance":0,"ao_intensity":0,"ao_multiplier":0,'
        '"draw_hidden_objects":true,"hide_custom_control_points":false,"line_style_edges":false,'
        '"section_cut_filled":false,"section_default_fill_color":0},"scenes":{"S":{"allow_clipping":false,'
        '"raw_payload":"cmF3"}},"styles":{"1":{"display_name":"Display","xml_data":"PHgvPg=="}}}'
    ).encode("utf-16le")

    assert expected in build_legacy_2017_model(model)


def test_reserved_extension_dictionary_name_is_rejected() -> None:
    model = skppy.Model.new()
    model.attribute_dictionaries = [skppy.AttributeDictionary(name=EXTENSION_DICTIONARY_NAME)]

    with pytest.raises(ValueError, match="reserved by the legacy writer"):
        build_legacy_2017_model(model)
