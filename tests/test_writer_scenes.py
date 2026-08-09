# SPDX-License-Identifier: MIT
"""Raw-byte checks for modern named-scene serialization."""

from __future__ import annotations

import struct

import pytest

from skppy.data_structure.construction import Camera
from skppy.data_structure.model import Model
from skppy.data_structure.primitives import Vector3D
from skppy.data_structure.scene_data import PageBackgroundImage, Scene
from skppy.writer.model_data import encode_model_data
from skppy.writer.scenes import encode_scenes


def _raw_record(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HI", tag, len(payload)) + payload


def test_scene_matches_raw_sdk_record_shape() -> None:
    scene = Scene(id=1, name="TestScene")
    base = b"".join(
        (
            _raw_record(0x05DC, _raw_record(0x05DE, b"\x12")),
            _raw_record(0x6F55, b"TestScene"),
            _raw_record(0x6F56),
        )
    )
    record = b"".join(
        (
            _raw_record(0x6F54, base),
            _raw_record(0x7149, struct.pack("<I", 0)),
            _raw_record(0x7152, b"\x01"),
            _raw_record(0x7153),
            _raw_record(0x7154, struct.pack("<d", -1.0)),
            _raw_record(0x7155, struct.pack("<d", -1.0)),
            _raw_record(0x715C),
            _raw_record(0x7157, b"\x01"),
        )
    )
    expected = _raw_record(
        0x6D60,
        _raw_record(0x6D61, _raw_record(0x7148, record)),
    )

    assert (
        encode_scenes(
            [scene],
            scene_id_map={1: 18},
            entity_id_map={},
            layer_id_map={},
        )
        == expected
    )


def test_model_root_contains_raw_unicode_scene_fields() -> None:
    model = Model.new()
    model.scenes.append(Scene(id=1, name="Cena São Paulo", description="Visão principal"))

    encoded = encode_model_data(model)

    assert _raw_record(0x6F55, "Cena São Paulo".encode()) in encoded
    assert _raw_record(0x6F56, "Visão principal".encode()) in encoded


def test_scene_camera_snapshot_contains_raw_camera_record() -> None:
    camera = Camera(
        eye=Vector3D(10, 20, 30),
        target=Vector3D(1, 2, 3),
        up=Vector3D(0, 0, 1),
    )
    scene = Scene(id=1, name="Camera scene", flags=1, camera=camera)

    encoded = encode_scenes(
        [scene],
        scene_id_map={1: 18},
        entity_id_map={},
        layer_id_map={},
    )

    camera_payload = b"".join(
        (
            _raw_record(0x34BD, struct.pack("<3d", 10, 20, 30)),
            _raw_record(0x34BE, struct.pack("<3d", 1, 2, 3)),
            _raw_record(0x34BF, struct.pack("<3d", 0, 0, 1)),
            _raw_record(0x34C0, struct.pack("<d", 1.0)),
            _raw_record(0x34C1, struct.pack("<d", 10000.0)),
            _raw_record(0x34C2, b"\x01"),
            _raw_record(0x34C4, struct.pack("<d", 35.0)),
            _raw_record(0x34C3, struct.pack("<d", 1.0)),
            _raw_record(0x34C5, struct.pack("<d", 0.0)),
            _raw_record(0x34C6, b"\x01"),
            _raw_record(0x34C7, b"\x00"),
            _raw_record(0x34C8),
            _raw_record(0x34C9, struct.pack("<d", 0.0)),
            _raw_record(0x34CA, b"\x00"),
            _raw_record(0x34CB, struct.pack("<d", 1.0)),
            _raw_record(0x34CC, struct.pack("<d", 0.0)),
            _raw_record(0x34CD, struct.pack("<d", 0.0)),
            _raw_record(0x34CE, b"\x01"),
        )
    )
    assert _raw_record(0x714A, _raw_record(0x34BC, camera_payload)) in encoded


def test_scene_replaces_known_raw_fields_and_preserves_unknown_snapshot() -> None:
    unknown_snapshot = _raw_record(0x714D, b"rendering snapshot")
    stale_base = _raw_record(
        0x6F54,
        _raw_record(0x05DC, _raw_record(0x05DE, b"\x01"))
        + _raw_record(0x6F55, b"Old name")
        + _raw_record(0x6F56, b"Old description"),
    )
    scene = Scene(
        id=1,
        name="New name",
        description="New description",
        raw_payload=stale_base + unknown_snapshot,
    )

    encoded = encode_scenes(
        [scene],
        scene_id_map={1: 18},
        entity_id_map={},
        layer_id_map={},
    )

    expected_base = _raw_record(
        0x6F54,
        _raw_record(0x05DC, _raw_record(0x05DE, b"\x12"))
        + _raw_record(0x6F55, b"New name")
        + _raw_record(0x6F56, b"New description"),
    )
    assert expected_base in encoded
    assert unknown_snapshot in encoded
    assert b"Old name" not in encoded


def _encode_one_scene(
    scene: Scene,
    *,
    entity_id_map: dict[int, int] | None = None,
    layer_id_map: dict[int, int] | None = None,
    background_image_object_ids: dict[int, int] | None = None,
    background_image_reference_ids: dict[int, int] | None = None,
) -> bytes:
    return encode_scenes(
        [scene],
        scene_id_map={scene.id: 18},
        entity_id_map=entity_id_map or {},
        layer_id_map=layer_id_map or {},
        background_image_object_ids=background_image_object_ids,
        background_image_reference_ids=background_image_reference_ids,
    )


def test_scene_optional_references_match_raw_serialized_ids() -> None:
    image = PageBackgroundImage(path="photo.png", image_data=b"raw")
    scene = Scene(
        id=1,
        name="References",
        hidden_entity_ids=[10],
        hidden_layer_ids=[20],
        active_section_plane_ids=[30],
        style_reference=7,
        background_image=image,
        display_background_image=True,
    )
    encoded = _encode_one_scene(
        scene,
        entity_id_map={10: 19, 30: 21},
        layer_id_map={20: 20},
        background_image_object_ids={id(image): 22},
    )

    assert _raw_record(0x714B, b"\x13") in encoded
    assert _raw_record(0x7150, b"\x14") in encoded
    assert _raw_record(0x7151, b"\x15") in encoded
    assert _raw_record(0x714C, b"\x07") in encoded
    assert _raw_record(0x7156, b"\x16") in encoded

    referenced = Scene(id=2, name="Referenced", background_image_ref=99)
    assert _raw_record(0x7156, b"\x17") in encode_scenes(
        [referenced],
        scene_id_map={2: 18},
        entity_id_map={},
        layer_id_map={},
        background_image_reference_ids={99: 23},
    )


@pytest.mark.parametrize(
    ("scene", "message"),
    [
        (Scene(id=1, name="Bad", flags=1), "requires a camera snapshot"),
        (Scene(id=1, name="Bad", camera=Camera()), "requires the use-camera flag"),
        (
            Scene(id=1, name="Bad", display_background_image=True),
            "requires an image",
        ),
        (Scene(id=0, name="Bad"), "IDs must be positive and unique"),
        (Scene(id=1, name=""), "names must be non-empty and unique"),
    ],
)
def test_scenes_reject_invalid_state(scene: Scene, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _encode_one_scene(scene)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("hidden_entity_ids", "unknown hidden entity"),
        ("hidden_layer_ids", "unknown hidden layer"),
        ("active_section_plane_ids", "unknown section plane"),
    ],
)
def test_scene_rejects_unknown_model_references(field: str, message: str) -> None:
    scene = Scene(id=1, name="Bad")
    setattr(scene, field, [99])
    with pytest.raises(ValueError, match=message):
        _encode_one_scene(scene)


def test_scene_rejects_unknown_background_and_invalid_raw_payload() -> None:
    with pytest.raises(ValueError, match="unknown background image"):
        _encode_one_scene(Scene(id=1, name="Bad", background_image_ref=99))
    with pytest.raises(ValueError, match="not a valid TLV"):
        _encode_one_scene(Scene(id=1, name="Bad", raw_payload=b"truncated"))


def test_scene_raw_payload_ignores_duplicate_modeled_records() -> None:
    stale = _raw_record(0x7149, struct.pack("<I", 1))
    scene = Scene(id=1, name="Merged", raw_payload=stale + stale)
    encoded = _encode_one_scene(scene)

    assert encoded.count(_raw_record(0x7149, struct.pack("<I", 0))) == 1
    assert _raw_record(0x7149, struct.pack("<I", 1)) not in encoded
