"""Native finite turn-angle steering with an existing scalar controller.

This composes original141210010/141226ee0/141211330 numerical branches.
The caller supplies an active waypoint, desired direction, gameplay cap and
master turn scalars. It does not search paths, choose avoidance directions,
allocate controllers, translate/commit positions or update animation state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vantage.replay_movement_geometry import (
    Float32Vector,
    _float,
    _norm,
    _op,
    _subtract,
    _vector,
    _word,
)
from vantage.replay_trigonometry import (
    native_acos_bits,
    native_cos_turn_bits,
    native_sin_turn_bits,
)

_ZERO, _ONE = 0, 0x3F800000
_EPSILON, _HALF_PI, _PI = 0x33D6BF95, 0x3FC90FDB, 0x40490FDB
_MAX, _NEG_MAX = 0x7F7FFFFF, 0xFF7FFFFF


@dataclass(frozen=True, slots=True)
class ReplaySteeringStep:
    direction: Float32Vector
    perpendicular: Float32Vector
    velocity: int
    acceleration: int
    yaw: int
    limited: int


def _finite(value: int) -> None:
    _word(value)
    if not math.isfinite(_float(value)):
        raise ValueError("finite steering input required")


def _normalize(value: Float32Vector) -> Float32Vector:
    # Original1410f1d80 and rotation's two normalizations are y-square first.
    length = _norm(value, y_first=True)
    return (_op(value[0], length, "/"), _op(value[1], length, "/"), _op(value[2], length, "/"))


def _dot_angle(a: Float32Vector, b: Float32Vector) -> int:
    xx, yy, zz = (_op(x, y, "*") for x, y in zip(a, b, strict=True))
    dot = _op(_op(xx, yy, "+"), zz, "+")
    if _float(dot & 0x7FFFFFFF) < _float(_EPSILON):
        return _HALF_PI
    if _float(dot) >= 1.0:
        return _ZERO
    if _float(dot) <= -1.0:
        return _PI
    return native_acos_bits(dot)


def _cross_y(left: Float32Vector, right: Float32Vector) -> int:
    # Original14096d440: right.x*left.z - left.x*right.z.
    return _op(_op(right[0], left[2], "*"), _op(left[0], right[2], "*"), "-")


def _matrix(angle: int) -> tuple[Float32Vector, ...]:
    # Keep all native operations, including signed-zero products on fixed Y axis.
    x, y, z = _ZERO, _ONE, _ZERO
    c, s = native_cos_turn_bits(angle), native_sin_turn_bits(angle)
    k = _op(_ONE, c, "-")
    xxk = _op(_op(x, x, "*"), k, "*")
    yxk = _op(_op(y, x, "*"), k, "*")
    zxk = _op(_op(z, x, "*"), k, "*")
    yyk = _op(_op(y, y, "*"), k, "*")
    zyk = _op(_op(z, y, "*"), k, "*")
    zzk = _op(_op(z, z, "*"), k, "*")
    xs, ys, zs = _op(x, s, "*"), _op(y, s, "*"), _op(z, s, "*")
    return (
        (_op(xxk, c, "+"), _op(yxk, zs, "-"), _op(zxk, ys, "+")),
        (_op(yxk, zs, "+"), _op(yyk, c, "+"), _op(zyk, xs, "-")),
        (_op(zxk, ys, "-"), _op(zyk, xs, "+"), _op(zzk, c, "+")),
    )


def _rotate(value: Float32Vector, matrix: tuple[Float32Vector, ...]) -> Float32Vector:
    def component(row: Float32Vector) -> int:
        return _op(
            _op(_op(value[1], row[1], "*"), _op(value[0], row[0], "*"), "+"),
            _op(value[2], row[2], "*"),
            "+",
        )

    return component(matrix[0]), component(matrix[1]), component(matrix[2])


def advance_replay_steering(
    position: Float32Vector,
    waypoint: Float32Vector,
    desired: Float32Vector,
    direction: Float32Vector,
    perpendicular: Float32Vector,
    velocity: int,
    acceleration: int,
    elapsed: int,
    speed_cap: int,
    turn_rate: int,
    turn_numerator: int,
    turn_denominator: int,
) -> ReplaySteeringStep:
    """Rotate direction/perpendicular and select native velocity/acceleration.

    Vector order is X,height,Y and scalar inputs/outputs are raw binary32.
    The native yaw magnitude must be below0x40490fdc, the proved normal-turn
    trig domain. Finite input scalars and a positive turn denominator are
    required. Radius is `(velocity*master20c)/master210`; turn cap is
    `master214*elapsed`. Supplied desired direction may reflect avoidance.
    A turn-limited step resets velocity and selects-FLT_MAX acceleration;
    other branches preserve the native turn-circle and cap comparisons.
    """
    for vector in (position, waypoint, desired, direction, perpendicular):
        _vector(vector)
        for value in vector:
            _finite(value)
    for value in (
        velocity,
        acceleration,
        elapsed,
        speed_cap,
        turn_rate,
        turn_numerator,
        turn_denominator,
    ):
        _finite(value)
    if _float(turn_denominator) <= 0.0:
        raise ValueError("positive turn denominator required")
    current = _normalize((direction[0], 0, direction[2]))
    angle = _dot_angle(desired, current)
    cap = _op(turn_rate, elapsed, "*")
    limited = 0 if _float(angle) <= _float(cap) else 1
    if limited:
        angle = cap ^ (0x80000000 if _float(angle) < 0.0 else 0)
    if _float(_cross_y(desired, current)) > 0.0:
        angle ^= 0x80000000
    if (angle & 0x7FFFFFFF) > 0x40490FDB:
        raise ValueError("bounded original turn-angle branch exceeded")
    matrix = _matrix(angle)
    direction = _normalize(_rotate(direction, matrix))
    perpendicular = _normalize(_rotate(perpendicular, matrix))
    if limited == 1:
        return ReplaySteeringStep(direction, perpendicular, 0, _NEG_MAX, angle, limited)
    # Original141211330 recomputes its full3D desired direction from waypoint.
    to_goal = _normalize(_subtract(waypoint, position))
    difference = _dot_angle(direction, to_goal)
    radius = _op(_op(velocity, turn_numerator, "*"), turn_denominator, "/")
    if _float(velocity) > 0.0 and _float(difference & 0x7FFFFFFF) > _float(_EPSILON):
        tangent = perpendicular
        if _float(_cross_y(to_goal, direction)) > 0.0:
            tangent = (tangent[0] ^ 0x80000000, tangent[1] ^ 0x80000000, tangent[2] ^ 0x80000000)
        candidate = (
            _op(_op(tangent[0], radius, "*"), position[0], "+"),
            _op(_op(tangent[1], radius, "*"), position[1], "+"),
            _op(_op(tangent[2], radius, "*"), position[2], "+"),
        )
        remaining = _subtract(waypoint, candidate)
        if _float(_norm(remaining, y_first=True)) < _float(radius):
            return ReplaySteeringStep(direction, perpendicular, velocity, _NEG_MAX, angle, limited)
    if _float(velocity) < _float(speed_cap):
        acceleration = _MAX
    return ReplaySteeringStep(direction, perpendicular, velocity, acceleration, angle, limited)
