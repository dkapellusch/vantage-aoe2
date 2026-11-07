"""Bounded native velocity and translation setter-input arithmetic.

The velocity caller supplies the gameplay speed cap and a null formation
result. Translation takes the resulting displacement and returns the intended
setter inputs. Position commits, terrain, occupancy and a full tick remain
outside these components.
"""

from __future__ import annotations

from vantage.replay_movement_geometry import Float32Vector, _float, _op, _vector, _word


def advance_unformed_replay_velocity(
    velocity_bits: int, acceleration_bits: int, elapsed_bits: int, speed_cap_bits: int
) -> int:
    """Original14120fcc0's null-formation branch, preserving SSE operand order.

    The upper-cap return precedes the zero clamp: a negative supplied cap
    may therefore be returned directly. Unordered comparisons do not clamp
    a NaN velocity, and signed zero survives an ordered comparison with zero.
    This requires a null formation result, not merely a single selected unit.
    """
    for value in (velocity_bits, acceleration_bits, elapsed_bits, speed_cap_bits):
        _word(value)
    velocity = _op(_op(acceleration_bits, elapsed_bits, "*"), velocity_bits, "+")
    if _float(velocity) > _float(speed_cap_bits):
        return speed_cap_bits
    if _float(velocity) < 0.0:
        return 0
    return velocity


def replay_translation_setter_inputs(
    position: Float32Vector,
    stored_direction: Float32Vector,
    displacement_bits: int,
    multiplier414_bits: int,
) -> Float32Vector | None:
    """Original1412192e0's inputs to the position setter, or no setter call.

    The caller first computes binary32 elapsed*newVelocity, as141075310 does.
    This helper multiplies that displacement by member414, then the stored
    direction, and adds position, preserving each native SSE operand order.
    An unordered threshold comparison reaches the setter; a small ordered
    magnitude returns None. Input and result vectors use x,height,y order;
    the native setter receives those components as x,y,height.

    The returned vector is an intended setter input. The original setter may
    clamp it and updates terrain, indexes and other state. This helper performs
    none of those changes. Native default MXCSR is required, as for geometry.
    """
    _vector(position)
    _vector(stored_direction)
    _word(displacement_bits)
    _word(multiplier414_bits)
    distance = _op(displacement_bits, multiplier414_bits, "*")
    if _float(distance & 0x7FFFFFFF) < _float(0x33D6BF95):
        return None
    return (
        _op(_op(distance, stored_direction[0], "*"), position[0], "+"),
        _op(_op(distance, stored_direction[1], "*"), position[1], "+"),
        _op(_op(distance, stored_direction[2], "*"), position[2], "+"),
    )
