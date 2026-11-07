"""Native movement speed caps from explicitly resolved object inputs.

The caller supplies current master/sprite values, the optional object+820
bonus and the category5 modifier vector. This module does not restore those
runtime structures or resolve targets for the additional Unit70 boost branch.
Raw binary32 words preserve native SSE operation order and NaN payloads.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_movement_geometry import _float, _op, _word


class UnsupportedReplaySpeedCap(ValueError):
    """The native target-dependent boost requires more simulation context."""


@dataclass(frozen=True, slots=True)
class ReplayStatModifier:
    """One native12-byte record; all three members retain their original words.

    ``operation``1 adds,2 multiplies,3 takes MINSS(amount,current),4 takes
    MAXSS(amount,current). Other operation words preserve the input.
    ``unknown_bits`` is the record's unused middle word.
    """

    operation: int
    amount_bits: int
    unknown_bits: int = 0


def _signed(value: int, name: str) -> None:
    if not isinstance(value, int) or not -0x80000000 <= value <= 0x7FFFFFFF:
        raise ValueError(f"{name} must be a signed32-bit integer")


def _modifiers(modifiers: tuple[ReplayStatModifier, ...]) -> None:
    if not isinstance(modifiers, tuple):
        raise ValueError("modifiers must be an ordered tuple of ReplayStatModifier records")
    for modifier in modifiers:
        if not isinstance(modifier, ReplayStatModifier):
            raise ValueError("modifiers must contain ReplayStatModifier records")
        for word in (modifier.operation, modifier.amount_bits, modifier.unknown_bits):
            _word(word)


def apply_replay_stat_modifiers(value_bits: int, modifiers: tuple[ReplayStatModifier, ...]) -> int:
    """Apply one resolved modifier vector in stored order, without a map lookup.

    Native1414c47e0 selects the exact current word for equal or unordered
    MINSS/MAXSS operands. This includes signaling NaNs and signed zero.
    The input vector is already selected for the caller's category.
    """
    _word(value_bits)
    _modifiers(modifiers)
    for modifier in modifiers:
        operation, amount = modifier.operation, modifier.amount_bits
        if operation == 1:
            value_bits = _op(value_bits, amount, "+")
        elif operation == 2:
            value_bits = _op(value_bits, amount, "*")
        elif operation == 3:
            value_bits = amount if _float(amount) < _float(value_bits) else value_bits
        elif operation == 4:
            value_bits = amount if _float(amount) > _float(value_bits) else value_bits
    return value_bits


def replay_movement_base_speed(
    master_speed_bits: int,
    *,
    sprite_speed_bits: int | None = None,
    reference_id: int = -1,
    reference_factor_bits: int = 0,
) -> int:
    """Native14120db90 with an explicit master virtual+e8 result.

    A present sprite multiplies the master speed only when its+c value
    compares ordered>0. The reference bonus uses the original master speed,
    separately from that sprite product. ``None`` means no current sprite.
    """
    _word(master_speed_bits)
    _word(reference_factor_bits)
    _signed(reference_id, "reference_id")
    if sprite_speed_bits is not None:
        _word(sprite_speed_bits)
    speed = master_speed_bits
    if sprite_speed_bits is not None and _float(sprite_speed_bits) > 0:
        speed = _op(speed, sprite_speed_bits, "*")
    if reference_id != -1:
        speed = _op(speed, _op(master_speed_bits, reference_factor_bits, "*"), "+")
    return speed


def replay_unit_speed_cap(
    master_speed_bits: int,
    *,
    master_target_boost_bits: int,
    sprite_speed_bits: int | None = None,
    reference_id: int = -1,
    reference_factor_bits: int = 0,
    stop_count: int = 0,
    unit_addend_bits: int = 0,
    secondary_addend_bits: int = 0,
    bonus_bits: int | None = None,
    modifiers: tuple[ReplayStatModifier, ...] = (),
) -> int:
    """Bounded native1412b6650 Unit70 cap, including category5 modifiers.

    ``master_target_boost_bits`` is the current master+3b8 word. A positive
    value and nonzero/unordered accumulated speed would require native
    target/AI/formation queries, so that branch raises explicitly.

    ``unit_addend_bits`` and ``secondary_addend_bits`` are object+6b4/+7c0.
    ``bonus_bits`` is None for null820, otherwise its pointed-to+4 word.
    ``modifiers`` is the already resolved category5 vector. These values
    must come from current simulation state; saved defaults are insufficient.
    """
    for value in (
        master_speed_bits,
        master_target_boost_bits,
        reference_factor_bits,
        unit_addend_bits,
        secondary_addend_bits,
    ):
        _word(value)
    if sprite_speed_bits is not None:
        _word(sprite_speed_bits)
    if bonus_bits is not None:
        _word(bonus_bits)
    _signed(stop_count, "stop_count")
    _signed(reference_id, "reference_id")
    _modifiers(modifiers)
    # Native returns exact+0 before the base/additive fields, boost or modifiers.
    if stop_count > 0:
        return 0
    speed = replay_movement_base_speed(
        master_speed_bits,
        sprite_speed_bits=sprite_speed_bits,
        reference_id=reference_id,
        reference_factor_bits=reference_factor_bits,
    )
    speed = _op(_op(speed, unit_addend_bits, "+"), secondary_addend_bits, "+")
    if bonus_bits is not None:
        speed = _op(speed, bonus_bits, "+")
    if _float(speed) != 0.0 and _float(master_target_boost_bits) > 0:
        raise UnsupportedReplaySpeedCap(
            "native Unit70 target-dependent speed boost is unimplemented"
        )
    return apply_replay_stat_modifiers(speed, modifiers)
