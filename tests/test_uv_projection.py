# SPDX-License-Identifier: MIT
import numpy as np
import pytest

from skppy.data_structure.entities import FaceUVProjection, UVPin
from skppy.data_structure.primitives import Vector2D


def test_face_uv_projection_inverts_affine_texture_matrix_on_xy_face():
    projection = FaceUVProjection(
        transform=[
            0.770250794234163,
            -1.7255866867311467,
            0.0,
            1.7720328480168945,
            0.6798725794905275,
            0.0,
            -83.78023515256854,
            26.48000499957223,
            1.0,
        ],
        origin=(0.0, 0.0, 0.0),
    )

    uv = projection.compute_uv(
        0.344131447886614,
        0.344131447886892,
        59.62670001958214,
        39.37007874015748,
        39.37007874015748,
        normal=(0.0, 0.0, 1.0),
    )

    assert uv == pytest.approx((0.7340815, 0.8867398))


def test_face_uv_projection_batch_matches_single_point_results():
    projection = FaceUVProjection(
        transform=[
            0.770250794234163,
            -1.7255866867311467,
            0.0,
            1.7720328480168945,
            0.6798725794905275,
            0.0,
            -83.78023515256854,
            26.48000499957223,
            1.0,
        ],
        origin=(0.0, 0.0, 0.0),
    )
    positions = [
        (0.344131447886614, 0.344131447886892, 59.62670001958214),
        (20.0, 10.0, 59.62670001958214),
        (10.0, 30.0, 59.62670001958214),
    ]

    batched = projection.compute_uvs(
        positions,
        39.37007874015748,
        39.37007874015748,
        normal=(0.0, 0.0, 1.0),
    )
    individual = [
        projection.compute_uv(
            x,
            y,
            z,
            39.37007874015748,
            39.37007874015748,
            normal=(0.0, 0.0, 1.0),
        )
        for x, y, z in positions
    ]

    assert len(batched) == len(individual)
    for batch_uv, point_uv in zip(batched, individual):
        assert batch_uv == pytest.approx(point_uv)


def test_face_uv_projection_uses_xz_coordinates_on_y_dominant_face():
    projection = FaceUVProjection(
        transform=[
            0.0,
            1.8915006778569368,
            0.0,
            -1.9133640651151103,
            -0.12853023338275135,
            -1.0604875662695546e-16,
            58.996392925868335,
            -57.03150834815965,
            1.0,
        ],
        origin=(0.0, 0.0, 0.0),
    )

    uv = projection.compute_uv(
        -4.65740279238153,
        2.6889527559041166,
        3.4454299212598585,
        39.37007874015748,
        39.37007874015748,
        normal=(0.0, -1.0, 0.0),
    )

    assert uv == pytest.approx((0.8695335, 0.8450072))


def test_face_uv_projection_uses_face_local_basis_on_oblique_face():
    projection = FaceUVProjection(
        transform=[
            0.5985876067137393,
            4.194192529109986e-05,
            0.0,
            0.05968492156249227,
            0.6040105430845886,
            1.3238786152405813e-16,
            -20.020471122228216,
            2.327628335351107,
            0.9999999999999396,
        ],
        origin=(0.0, 0.0, 0.0),
    )

    uv = projection.compute_uv(
        6.534454496563861,
        6.534454496563854,
        12.91338582677165,
        39.37007874015748,
        39.37007874015748,
        normal=(0.7213099905642555, 0.4819639270128061, -0.4974159934808975),
    )

    assert uv == pytest.approx((0.8699238, 0.5627351))


def test_face_uv_projection_uses_legacy_direction_and_homogeneous_q():
    projection = FaceUVProjection(
        transform=[
            1.0,
            0.0,
            0.1,
            0.0,
            1.0,
            0.2,
            0.0,
            0.0,
            1.0,
        ],
        origin=(1.0, 0.0, 0.0),
        projection_direction=(1.0, 0.0, 0.0),
    )

    uv = projection.compute_uv(
        7.0,
        2.0,
        3.0,
        1.0,
        1.0,
        normal=(0.0, 0.0, 1.0),
    )

    # Projection along X uses (Y, Z) = (2, 3). Applying inverse(M)
    # produces UVQ=(2, 3, 0.2), hence UV=(10, 15).
    assert uv == pytest.approx((10.0, 15.0))


def test_face_uv_projection_reports_singular_matrix_without_crashing():
    """Return neutral UVs when a stored projection cannot be inverted."""
    projection = FaceUVProjection(
        transform=[0.0] * 9,
        origin=(0.0, 0.0, 0.0),
    )

    assert projection.is_singular()
    assert projection.compute_uvs(
        [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)],
        1.0,
        1.0,
        normal=(0.0, 0.0, 1.0),
    ) == [(0.0, 0.0), (0.0, 0.0)]


def test_face_uv_projection_rejects_non_finite_matrix_without_warning():
    projection = FaceUVProjection(transform=[float("nan"), 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0])

    assert projection.is_singular()


@pytest.mark.parametrize("scale", [0.0, -0.0, float("nan"), float("inf")])
def test_face_uv_projection_normalizes_invalid_texture_scales(scale):
    """Never expose non-finite UVs for malformed texture dimensions."""
    projection = FaceUVProjection()

    uvs = projection.compute_uvs([(1.0, 2.0, 0.0)], scale, scale, normal=(0.0, 0.0, 1.0))

    assert np.isfinite(uvs).all()
    assert uvs == [(1.0, 2.0)]


def test_face_uv_projection_uses_exact_control_point_uvs():
    projection = FaceUVProjection(
        pins=[
            UVPin(
                texture_position=Vector2D(8.0, 6.0),
                model_position=Vector2D(1.0, 0.0),
            )
        ]
    )

    assert projection.compute_uvs(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        4.0,
        3.0,
        normal=(0.0, 0.0, 1.0),
    ) == [(0.0, 0.0), (2.0, 2.0)]
