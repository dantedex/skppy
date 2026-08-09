# SPDX-License-Identifier: MIT
"""Vector and transformation primitives used throughout the public model.

Coordinates and translations use SketchUp's native inch unit. :class:`Transform`
accepts either the 13-value SketchUp representation or a NumPy ``4 x 4`` matrix
and provides composition and point/vector conversion helpers.

Example
-------
::

    import skppy

    move = skppy.Transform.from_translation(24, 36, 0)
    print(move.translation().to_tuple())  # (24.0, 36.0, 0.0)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np


@dataclass(slots=True)
class Vector2D:
    """2-D point or vector.

    Attributes
    ----------
    x : float
        X component.
    y : float
        Y component.
    """

    x: float
    y: float

    def __add__(self, other: Vector2D) -> Vector2D:
        """Return the component-wise sum of two vectors.

        Parameters
        ----------
        other : Vector2D
            Vector to add.

        Returns
        -------
        Vector2D
            ``self + other``.
        """
        return Vector2D(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vector2D) -> Vector2D:
        """Return the component-wise difference of two vectors.

        Parameters
        ----------
        other : Vector2D
            Vector to subtract.

        Returns
        -------
        Vector2D
            ``self - other``.
        """
        return Vector2D(self.x - other.x, self.y - other.y)

    def to_array(self) -> np.ndarray:
        """Return ``[x, y]`` as a NumPy array.

        Returns
        -------
        numpy.ndarray
            Two-element floating-point array.
        """
        return np.array([self.x, self.y], dtype=float)


@dataclass(slots=True)
class Vector3D:
    """3-D point or vector (SketchUp internal units = inches).

    All geometric positions and directions in skppy are expressed in
    SketchUp's internal unit -- inches -- unless otherwise noted.

    Attributes
    ----------
    x : float
        X component.
    y : float
        Y component.
    z : float
        Z component.
    """

    x: float
    y: float
    z: float

    def __add__(self, other: Vector3D) -> Vector3D:
        """Return the component-wise sum of two vectors.

        Parameters
        ----------
        other : Vector3D
            Vector to add.

        Returns
        -------
        Vector3D
            ``self + other``.
        """
        return Vector3D(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vector3D) -> Vector3D:
        """Return the component-wise difference of two vectors.

        Parameters
        ----------
        other : Vector3D
            Vector to subtract.

        Returns
        -------
        Vector3D
            ``self - other``.
        """
        return Vector3D(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vector3D:
        """Return this vector scaled by *scalar*."""
        return Vector3D(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> Vector3D:
        """Return this vector scaled by *scalar*."""
        return self * scalar

    def dot(self, other: Vector3D) -> float:
        """Return the dot product with *other*.

        Parameters
        ----------
        other : Vector3D
            The other vector.

        Returns
        -------
        float
            ``self . other``.
        """
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vector3D) -> Vector3D:
        """Return the cross product with *other*.

        Parameters
        ----------
        other : Vector3D
            The other vector.

        Returns
        -------
        Vector3D
            ``self x other``.
        """
        return Vector3D(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def length(self) -> float:
        """Return the Euclidean length (magnitude) of the vector.

        Returns
        -------
        float
            ``sqrt(x^2 + y^2 + z^2)``.
        """
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalized(self) -> Vector3D:
        """Return a unit-length copy of this vector.

        Returns
        -------
        Vector3D
            Unit vector.  Falls back to ``(0, 0, 1)`` when the length is
            near zero (below ``1e-12``).
        """
        n = self.length()
        return Vector3D(self.x / n, self.y / n, self.z / n) if n > 1e-12 else Vector3D(0, 0, 1)

    def to_tuple(self) -> Tuple[float, float, float]:
        """Return ``(x, y, z)`` as a plain tuple.

        Returns
        -------
        tuple of float
            ``(x, y, z)``.
        """
        return (self.x, self.y, self.z)

    def to_array(self) -> np.ndarray:
        """Return ``[x, y, z]`` as a NumPy array.

        Returns
        -------
        numpy.ndarray
            Three-element floating-point array.
        """
        return np.array([self.x, self.y, self.z], dtype=float)


# -
# Transform  (SUTransformation - 13 floats, row-major 3x3 + translation + w)
# -

_IDENTITY_MATRIX = np.eye(4, dtype=float)


@dataclass(slots=True, init=False, eq=False)
class Transform:
    """
    Wraps the 13-float SUTransformation used by SketchUp.

    Layout (row-major, 3x3 rotation + translation + scale):

    - Indices 0-2 : first row of the rotation/scale matrix
    - Indices 3-5 : second row
    - Indices 6-8 : third row
    - Indices 9-11: translation (tx, ty, tz) in SketchUp inches
    - Index 12    : uniform scale factor (normally 1.0)

    All spatial values are in SketchUp inches.

    Parameters
    ----------
    values : sequence of float, numpy.ndarray, optional
        Optional 13-float SketchUp transformation or ``(4, 4)`` matrix.
    """

    _matrix: np.ndarray

    def __init__(
        self,
        values: Optional[Union[Sequence[float], np.ndarray]] = None,
    ) -> None:
        """
        Create a transform from SketchUp's 13-float layout or a 4x4 matrix.

        Parameters
        ----------
        values : sequence of float, numpy.ndarray, optional
            ``None`` creates the identity transform.  A flat sequence is
            interpreted as SketchUp's 13-float row-major transform layout
            (3x3 basis, translation, homogeneous scale).  A ``(4, 4)`` NumPy
            array is copied directly.
        """
        self._matrix = _coerce_transform_matrix(values)

    @classmethod
    def identity(cls) -> Transform:
        """
        Return the identity transform (no rotation, no translation, scale=1).

        Returns
        -------
        Transform
        """
        return cls(_IDENTITY_MATRIX)

    @classmethod
    def from_translation(cls, tx: float, ty: float, tz: float) -> Transform:
        """
        Build a pure translation transform.

        Parameters
        ----------
        tx, ty, tz : float
            Translation offsets in SketchUp inches.

        Returns
        -------
        Transform
        """
        matrix = np.eye(4, dtype=float)
        matrix[:3, 3] = [tx, ty, tz]
        return cls(matrix)

    @classmethod
    def from_uniform_scale(cls, s: float) -> Transform:
        """
        Build a uniform scale transform around the origin.

        Parameters
        ----------
        s : float
            Scale factor applied to all three axes.

        Returns
        -------
        Transform
        """
        matrix = np.eye(4, dtype=float)
        matrix[0, 0] = matrix[1, 1] = matrix[2, 2] = s
        return cls(matrix)

    @classmethod
    def from_scale(cls, sx: float, sy: float, sz: float) -> Transform:
        """
        Build a non-uniform scale transform around the origin.

        Parameters
        ----------
        sx, sy, sz : float
            Per-axis scale factors.

        Returns
        -------
        Transform
        """
        matrix = np.eye(4, dtype=float)
        matrix[0, 0], matrix[1, 1], matrix[2, 2] = sx, sy, sz
        return cls(matrix)

    @classmethod
    def from_rotation_z(cls, radians: float) -> Transform:
        """
        Build a rotation around the Z axis.

        Parameters
        ----------
        radians : float
            Rotation angle in radians.

        Returns
        -------
        Transform
        """
        c, s = math.cos(radians), math.sin(radians)
        matrix = np.eye(4, dtype=float)
        matrix[:3, :3] = np.array(
            [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]],
            dtype=float,
        )
        return cls(matrix)

    @classmethod
    def from_rotation_x(cls, radians: float) -> Transform:
        """
        Build a rotation around the X axis.

        Parameters
        ----------
        radians : float
            Rotation angle in radians.

        Returns
        -------
        Transform
        """
        c, s = math.cos(radians), math.sin(radians)
        matrix = np.eye(4, dtype=float)
        matrix[:3, :3] = np.array(
            [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]],
            dtype=float,
        )
        return cls(matrix)

    @classmethod
    def from_rotation_y(cls, radians: float) -> Transform:
        """
        Build a rotation around the Y axis.

        Parameters
        ----------
        radians : float
            Rotation angle in radians.

        Returns
        -------
        Transform
        """
        c, s = math.cos(radians), math.sin(radians)
        matrix = np.eye(4, dtype=float)
        matrix[:3, :3] = np.array(
            [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]],
            dtype=float,
        )
        return cls(matrix)

    @property
    def matrix(self) -> np.ndarray:
        """Return a copy of the internal 4x4 matrix.

        Returns
        -------
        numpy.ndarray
            Matrix in row-major order.
        """
        return self._matrix.copy()

    def to_list(self) -> List[float]:
        """
        Return the raw 13-float list.

        Returns
        -------
        list of float
            Copy of the internal 13-element values list.
        """
        return _matrix_to_transform13(self._matrix)

    def translation(self) -> Vector3D:
        """
        Extract the translation component of the transform.

        Returns
        -------
        Vector3D
            The (tx, ty, tz) translation in SketchUp inches.
        """
        tx, ty, tz = self._matrix[:3, 3]
        return Vector3D(float(tx), float(ty), float(tz))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Transform):
            return NotImplemented
        return bool(np.allclose(self._matrix, other._matrix))


def _coerce_transform_matrix(
    values: Optional[Union[Sequence[float], np.ndarray]],
) -> np.ndarray:
    """Normalize a 13-float SUTransformation or 4x4 matrix to ndarray form."""
    if values is None:
        return np.eye(4, dtype=float)

    array = np.asarray(values, dtype=float)
    if array.shape == (4, 4):
        return array.copy()

    flat = array.ravel()
    value_count = len(flat)
    if value_count < 13:
        flat = np.pad(flat, (0, 13 - value_count))
    matrix = np.eye(4, dtype=float)
    matrix[:3, :3] = flat[:9].reshape((3, 3))
    matrix[:3, 3] = flat[9:12]
    matrix[3, 3] = flat[12] if value_count >= 13 else 1.0
    return matrix


def _matrix_to_transform13(matrix: np.ndarray) -> List[float]:
    """Convert a 4x4 transform matrix to SketchUp's 13-float layout."""
    m = np.asarray(matrix, dtype=float)
    return [
        float(m[0, 0]),
        float(m[0, 1]),
        float(m[0, 2]),
        float(m[1, 0]),
        float(m[1, 1]),
        float(m[1, 2]),
        float(m[2, 0]),
        float(m[2, 1]),
        float(m[2, 2]),
        float(m[0, 3]),
        float(m[1, 3]),
        float(m[2, 3]),
        float(m[3, 3]),
    ]
