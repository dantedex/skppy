# SPDX-License-Identifier: MIT
"""Modern page-background-image parser fixtures."""

from __future__ import annotations

import struct
import zipfile

from skppy.parser.background_images import (
    _bool,
    _f64,
    _i32,
    _image_data,
    _points,
    _vector,
    parse_background_images,
)
from skppy.writer.tlv import encode_record


class TlvTag:
    """Literal observed wire tags; intentionally independent of production."""

    MODEL_EMPTY_MARKER = 0x0201
    ID_WRAPPER = 0x05DC
    ID_VALUE = 0x05DE
    DIB_RECORD = 0x2328
    DIB_EXTERNAL_PATH = 0x232A
    DIB_BINARY = 0x232B
    BACKGROUND_IMAGE_RECORD = 0x2904
    BACKGROUND_IMAGE_REFERENCE = 0x2905
    BACKGROUND_IMAGE_VISIBLE = 0x2906
    BACKGROUND_IMAGE_OPACITY = 0x2907
    BACKGROUND_IMAGE_GRIP_POINTS = 0x2908
    BACKGROUND_IMAGE_PRINCIPAL_DELTA = 0x2909
    BACKGROUND_IMAGE_RADIAL_DISTORTION = 0x290A
    BACKGROUND_IMAGE_SOURCE = 0x290B
    IMAGE_REFERENCE_RECORD = 0x2AF8
    IMAGE_REFERENCE_PATH = 0x2AF9
    IMAGE_REFERENCE_STATE = 0x2AFA
    IMAGE_REFERENCE_DIB = 0x2AFB
    IMAGE_REFERENCE_WIDTH = 0x2AFC
    IMAGE_REFERENCE_HEIGHT = 0x2AFD
    IMAGE_REFERENCE_FILE_SIZE = 0x2AFE
    IMAGE_REFERENCE_TIMESTAMP = 0x2AFF


def _record(tag: TlvTag, payload: bytes = b"") -> bytes:
    return encode_record(tag, payload)


def test_background_image_decodes_complete_embedded_reference(tmp_path):
    archive_path = tmp_path / "model.skp"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("unused", b"")

    identity = _record(TlvTag.ID_WRAPPER, _record(TlvTag.ID_VALUE, b"\x2a"))
    dib = _record(TlvTag.DIB_RECORD, _record(TlvTag.DIB_BINARY, b"image-bytes"))
    reference = _record(
        TlvTag.IMAGE_REFERENCE_RECORD,
        b"".join(
            (
                _record(TlvTag.IMAGE_REFERENCE_PATH, b"background.png"),
                _record(TlvTag.IMAGE_REFERENCE_STATE, struct.pack("<i", 3)),
                _record(TlvTag.IMAGE_REFERENCE_DIB, dib),
                _record(TlvTag.IMAGE_REFERENCE_WIDTH, struct.pack("<i", 640)),
                _record(TlvTag.IMAGE_REFERENCE_HEIGHT, struct.pack("<i", 480)),
                _record(TlvTag.IMAGE_REFERENCE_FILE_SIZE, struct.pack("<i", 11)),
                _record(TlvTag.IMAGE_REFERENCE_TIMESTAMP, struct.pack("<i", 1234)),
            )
        ),
    )
    grip_points = struct.pack("<dddddd", 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    image = _record(
        TlvTag.BACKGROUND_IMAGE_RECORD,
        b"".join(
            (
                identity,
                _record(TlvTag.BACKGROUND_IMAGE_REFERENCE, reference),
                _record(TlvTag.BACKGROUND_IMAGE_VISIBLE, b"\x01"),
                _record(TlvTag.BACKGROUND_IMAGE_OPACITY, struct.pack("<d", 0.75)),
                _record(TlvTag.BACKGROUND_IMAGE_GRIP_POINTS, grip_points),
                _record(
                    TlvTag.BACKGROUND_IMAGE_PRINCIPAL_DELTA,
                    struct.pack("<ddd", 7.0, 8.0, 9.0),
                ),
                _record(
                    TlvTag.BACKGROUND_IMAGE_RADIAL_DISTORTION,
                    struct.pack("<d", 0.125),
                ),
                _record(TlvTag.BACKGROUND_IMAGE_SOURCE, struct.pack("<i", 2)),
            )
        ),
    )
    payload = _record(TlvTag.MODEL_EMPTY_MARKER, b"ignored") + image

    with zipfile.ZipFile(archive_path) as archive:
        parsed = parse_background_images(payload, archive)

    assert list(parsed) == [42]
    background = parsed[42]
    assert background.path == "background.png"
    assert background.reference_state == 3
    assert background.image_data == b"image-bytes"
    assert (background.width, background.height, background.file_size) == (640, 480, 11)
    assert background.timestamp == 1234
    assert background.visible is True
    assert background.opacity == 0.75
    assert [point.to_tuple() for point in background.grip_points] == [
        (1.0, 2.0, 3.0),
        (4.0, 5.0, 6.0),
    ]
    assert background.principal_point_delta.to_tuple() == (7.0, 8.0, 9.0)
    assert background.radial_distortion_k1 == 0.125
    assert background.image_source == 2


def test_background_image_helpers_cover_defaults_and_external_resources(tmp_path):
    archive_path = tmp_path / "model.skp"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("images/external.png", b"external")

    assert _i32(None) == 0
    assert _f64(b"short", 2.5) == 2.5
    assert _bool(None) is False
    assert _points(None) == []
    assert _vector(None).to_tuple() == (0.0, 0.0, 0.0)
    assert _image_data(None, None) is None  # type: ignore[arg-type]

    with zipfile.ZipFile(archive_path) as archive:
        external = _record(TlvTag.DIB_EXTERNAL_PATH, b"images/external.png")
        missing = _record(TlvTag.DIB_EXTERNAL_PATH, b"images/missing.png")
        assert _image_data(external, archive) == b"external"
        assert _image_data(missing, archive) is None


def test_background_image_ignores_records_without_persistent_id(tmp_path):
    archive_path = tmp_path / "model.skp"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("unused", b"")
    payload = _record(TlvTag.BACKGROUND_IMAGE_RECORD)
    with zipfile.ZipFile(archive_path) as archive:
        assert parse_background_images(payload, archive) == {}
