"""Bounded native direction, candidate prediction and arrival geometry.

Raw binary32 words preserve native operation order and NaN payloads. These
helpers do not commit positions, calculate gameplay speed caps, follow paths,
steer, apply acceleration, resolve collisions or advance a world clock.
The contract assumes native default MXCSR: nearest-even, no DAZ or FTZ.
"""

from __future__ import annotations

import math
import struct

Float32Vector = tuple[int, int, int]
_EPSILON = 0x33D6BF95
_INVALID = 0xFFC00000


def _word(value: int) -> None:
    if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("movement scalar must be a binary32 u32 word")


def _vector(value: Float32Vector) -> None:
    if not isinstance(value, tuple) or len(value) != 3:
        raise ValueError("movement vector must contain three binary32 u32 words")
    for component in value:
        _word(component)


def _float(value: int) -> float:
    return float(struct.unpack("<f", struct.pack("<I", value))[0])


def _bits(value: float) -> int:
    try:
        return int(struct.unpack("<I", struct.pack("<f", value))[0])
    except OverflowError:
        return 0xFF800000 if value < 0 else 0x7F800000


def _nan(value: int) -> bool:
    return value & 0x7F800000 == 0x7F800000 and bool(value & 0x7FFFFF)


def _op(left: int, right: int, operation: str) -> int:
    # Legacy SSE chooses the destination NaN first and quiets signaling NaNs.
    if _nan(left):
        return left | 0x400000
    if _nan(right):
        return right | 0x400000
    a, b = _float(left), _float(right)
    if operation == "+":
        return _bits(a + b)
    if operation == "-":
        return _bits(a - b)
    if operation == "*":
        return _bits(a * b)
    if b == 0.0:
        if a == 0.0:
            return _INVALID
        return ((left ^ right) & 0x80000000) | 0x7F800000
    return _bits(a / b)


def _sqrt(value: int) -> int:
    if _nan(value):
        return value | 0x400000
    real = _float(value)
    if real < 0:
        return _INVALID
    return _bits(math.sqrt(real))


def _norm(vector: Float32Vector, *, y_first: bool = False) -> int:
    x, y, z = (_op(c, c, "*") for c in vector)
    partial = _op(y, x, "+") if y_first else _op(x, y, "+")
    return _sqrt(_op(partial, z, "+"))


def _subtract(a: Float32Vector, b: Float32Vector) -> Float32Vector:
    return _op(a[0], b[0], "-"), _op(a[1], b[1], "-"), _op(a[2], b[2], "-")


def replay_movement_direction(
    position: Float32Vector, waypoint: Float32Vector, current_direction: Float32Vector
) -> Float32Vector:
    """Native14120fbd0: horizontal desired direction, with saved fallback.

    Ordered equal horizontal coordinates or a length below1e-7 copy the
    fallback's exact words. Native COMISS sends unordered lengths through
    normalization, so NaNs are not silently replaced by the fallback.
    """
    for vector in (position, waypoint, current_direction):
        _vector(vector)
    if _float(position[0]) == _float(waypoint[0]) and _float(position[2]) == _float(waypoint[2]):
        return current_direction
    x, z = _op(waypoint[0], position[0], "-"), _op(waypoint[2], position[2], "-")
    length = _norm((x, 0, z))
    if _float(length) < _float(_EPSILON):
        return current_direction
    return _op(x, length, "/"), 0, _op(z, length, "/")


def predict_replay_movement(
    position: Float32Vector,
    direction: Float32Vector,
    velocity_bits: int,
    acceleration_bits: int,
    elapsed_bits: int,
    speed_cap_bits: int,
    *,
    has_controller: bool = True,
) -> Float32Vector:
    """Native1412256a0: predict a candidate without changing the controller.

    The caller supplies its already computed speed cap. A nonpositive
    predicted speed substitutes that cap. This differs from the actual
    controller's zero clamp. Native object+0x414 is absent from this predictor.
    No controller copies position unchanged, including signaling NaN bits.
    """
    _vector(position)
    _vector(direction)
    for value in (velocity_bits, acceleration_bits, elapsed_bits, speed_cap_bits):
        _word(value)
    if not isinstance(has_controller, bool):
        raise ValueError("has_controller must be a bool")
    if not has_controller:
        return position
    speed = _op(_op(elapsed_bits, acceleration_bits, "*"), velocity_bits, "+")
    if _float(speed) > _float(speed_cap_bits) or _float(speed) <= 0.0:
        speed = speed_cap_bits
    distance = _op(elapsed_bits, speed, "*")
    return (
        _op(_op(distance, direction[0], "*"), position[0], "+"),
        _op(_op(distance, direction[1], "*"), position[1], "+"),
        _op(_op(distance, direction[2], "*"), position[2], "+"),
    )


def replay_movement_arrival(
    waypoint: Float32Vector, position: Float32Vector, candidate: Float32Vector
) -> int:
    """Native14120fdf0: preserve the native0/1/2 progress result.

    Original141252da0 query3 always returns true, so the goal distances
    discard the vertical component. Step length retains all three components.
    COMISS/JBE routes unordered step comparisons to result0.
    """
    for vector in (waypoint, position, candidate):
        _vector(vector)
    before = _subtract(waypoint, position)
    after = _subtract(waypoint, candidate)
    remaining = _norm((before[0], 0, before[2]))
    predicted_remaining = _norm((after[0], 0, after[2]))
    step = _norm(_subtract(candidate, position), y_first=True)
    if _float(predicted_remaining) < _float(_EPSILON):
        return 1
    if _nan(step) or _nan(remaining) or _float(step) <= _float(remaining):
        return 0
    return 1 + int(_float(predicted_remaining) > _float(remaining))
