"""Build54800 Common and Unit/Building HP damage execution over bound storage.

Exact Common leaf141247540 and Unit1412ba130 prelude, floor1412b6430 and
post-write dispatch. Scalar storage accesses preserve native widths/order;
the HP qword's decoded high word is retained. Read bindings represent current
subject/master storage, not saved defaults. Unit lifecycle tails require real
implementations when reached; no callback effects or World state are invented.
See terrain-effect-hp-dispatch-review-v1 for original byte/source evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    multiply_binary32,
    signed16_binary32,
    subtract_binary32,
)

_QWORD = (1 << 64) - 1
_HP_XOR = 0x0F2A55F7A61DD00E
_HP_ADD = 0x147B5E081EC087D9
_BASE_XOR = 0xD978539418047C54 ^ 0xABAA7F7397F61E6C


class UnresolvedReplayDamageContext(ValueError):
    """A reached current master read or lifecycle implementation is missing."""


def _unsigned(value: int, maximum: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an unsigned word no greater than {maximum}")


def _controls(mxcsr: int) -> None:
    _unsigned(mxcsr, 0xFFFFFFFF, "MXCSR")
    if mxcsr & ~0x3F != 0x1F80:
        raise ValueError("damage requires masked nearest-even MXCSR, DAZ/FTZ off")


@dataclass(frozen=True, slots=True)
class ReplayDamageStorage:
    """Actual current object scalar storage and optional current master reader.

    Callables take byte offset and width; writes also take the raw unsigned
    value. They must implement coherent, successfully backed scalar accesses
    for this subject. read_current_master resolves the then-current master
    independently on EACH call, including the separate fallback and base-HP
    reads. The known floor getter has no calls or subject/master writes.

    This does not bind or infer a native vptr. The caller must select the
    correct Common or Unit/Building target. Aliased, concurrent, faulting or
    incoherent storage and native FPstatus/traps are outside the contract.
    Callback exceptions propagate; completed subject writes are retained.
    """

    read_subject: Callable[[int, int], int]
    write_subject: Callable[[int, int, int], None]
    read_current_master: Callable[[int, int], int] | None

    def __post_init__(self) -> None:
        if not callable(self.read_subject) or not callable(self.write_subject):
            raise ValueError("actual subject scalar read/write bindings are required")
        if self.read_current_master is not None and not callable(self.read_current_master):
            raise ValueError("current master reader must be callable or unavailable")


@dataclass(frozen=True, slots=True)
class ReplayDamageCallbacks:
    """Actual Unit lifecycle helper and low-HP bookkeeping continuation.

    healthy binds1412b7f00 with the current subject. low_hp binds the complete
    1412ba2e5 continuation after nonzero credit count and byte594==0 gates.
    They may change object/master/World state; no later scalar reads are made
    here after either returns. None explicitly marks an unavailable binding
    and raises if that continuation is reached, after prior native writes.
    """

    healthy: Callable[[], None] | None
    low_hp: Callable[[], None] | None

    def __post_init__(self) -> None:
        if any(value is not None and not callable(value) for value in (self.healthy, self.low_hp)):
            raise ValueError("damage continuations must be callable or unavailable")


def _read(storage: ReplayDamageStorage, offset: int, width: int, *, master: bool = False) -> int:
    reader = storage.read_current_master if master else storage.read_subject
    if reader is None:
        raise UnresolvedReplayDamageContext("reached current master read is unavailable")
    value = reader(offset, width)
    _unsigned(value, (1 << (width * 8)) - 1, "current damage storage read")
    return value


def _decoded_hp(raw: int) -> int:
    return ((raw ^ _HP_XOR) - _HP_ADD) & _QWORD


def _encoded_hp(decoded: int, low_word: int) -> int:
    updated = (decoded & 0xFFFFFFFF00000000) | low_word
    return ((updated + _HP_ADD) & _QWORD) ^ _HP_XOR


def replay_unit_hp_floor(storage: ReplayDamageStorage, *, mxcsr: int) -> int:
    """1412b6430: current factor/fallback and conditional signed16 base HP.

    Either zero sign falls back to current master3d0. A selected ordered zero
    returns +0. A negative OR unordered factor takes raw sign-clear ABS,
    retaining signaling bits/payload. Only ordered positive factors read and
    decode master68, then multiply signed16 baseHP by the factor.
    """
    if not isinstance(storage, ReplayDamageStorage):
        raise ValueError("explicit current damage storage bindings required")
    _controls(mxcsr)
    factor = _read(storage, 0x7E0, 4)
    if compare_binary32(factor, 0) == 0:
        factor = _read(storage, 0x3D0, 4, master=True)
    order = compare_binary32(factor, 0)
    if order == 0:
        return 0
    if order != 1:
        return factor & 0x7FFFFFFF
    raw = _read(storage, 0x68, 8, master=True)
    base = (raw ^ _BASE_XOR) & 0xFFFF
    signed = base if base < 0x8000 else base - 0x10000
    return multiply_binary32(signed16_binary32(signed), factor)


def apply_replay_common_damage(
    storage: ReplayDamageStorage, damage_bits: int, *, mxcsr: int
) -> None:
    """Complete133-byte Common target: subtract once and write full protected HP.

    No clamping, floor/master read, sign restriction or lifecycle notification
    occurs. Families10/20/25/30/40/50/60 have this constructor-installed b8 slot;
    selection of an actual current target remains the caller's responsibility.
    """
    if not isinstance(storage, ReplayDamageStorage):
        raise ValueError("explicit current damage storage bindings required")
    _controls(mxcsr)
    _unsigned(damage_bits, 0xFFFFFFFF, "damage binary32")
    decoded = _decoded_hp(_read(storage, 0x130, 8))
    result = subtract_binary32(decoded & 0xFFFFFFFF, damage_bits)
    storage.write_subject(0x130, 8, _encoded_hp(decoded, result))


def apply_replay_unit_damage(
    storage: ReplayDamageStorage,
    damage_bits: int,
    *,
    mxcsr: int,
    callbacks: ReplayDamageCallbacks,
) -> None:
    """1412ba130: absorption, HP/floor write and actual reached continuation.

    Unit70 and Building80 share this constructor-installed b8 target. A fully
    absorbed hit returns before HP/master/lifecycle reads. Otherwise preserve
    the rounded absorbed+gap store, residual subtraction, current HP decode,
    floor getter and protected-qword write in order. Reload HP after that write.
    Unordered comparisons retain source JC/JBE behavior, including low-HP NaNs.

    Low-HP count uses signed64(end-begin) modulo2**64, truncating /56 toward0.
    A nonzero count and zero594 require the full bookkeeping continuation.
    Native vector backing/order remains a caller premise, not inferred from
    these scalars. Unknown reached work raises after completed writes; it is
    never treated as successful damage/lifecycle execution.
    """
    if not isinstance(storage, ReplayDamageStorage):
        raise ValueError("explicit current damage storage bindings required")
    if not isinstance(callbacks, ReplayDamageCallbacks):
        raise ValueError("explicit current damage continuation bindings required")
    _controls(mxcsr)
    _unsigned(damage_bits, 0xFFFFFFFF, "damage binary32")
    cap = _read(storage, 0x6C4, 4)
    absorbed = _read(storage, 0x6C0, 4)
    if compare_binary32(cap, absorbed) == 1:
        gap = subtract_binary32(cap, absorbed)
        if compare_binary32(gap, damage_bits) in (0, 1):
            storage.write_subject(0x6C0, 4, add_binary32(absorbed, damage_bits))
            return
        storage.write_subject(0x6C0, 4, add_binary32(absorbed, gap))
        damage_bits = subtract_binary32(damage_bits, gap)
    decoded = _decoded_hp(_read(storage, 0x130, 8))
    candidate = subtract_binary32(decoded & 0xFFFFFFFF, damage_bits)
    floor = replay_unit_hp_floor(storage, mxcsr=mxcsr)
    result = (
        floor
        if compare_binary32(floor, 0) != 0 and compare_binary32(candidate, floor) in (None, -1)
        else candidate
    )
    storage.write_subject(0x130, 8, _encoded_hp(decoded, result))
    hp = _decoded_hp(_read(storage, 0x130, 8)) & 0xFFFFFFFF
    if compare_binary32(hp, 0x3F800000) in (0, 1):
        if callbacks.healthy is None:
            raise UnresolvedReplayDamageContext("reached Unit lifecycle1412b7f00 is unavailable")
        callbacks.healthy()
        return
    end = _read(storage, 0x7F8, 8)
    begin = _read(storage, 0x7F0, 8)
    difference = (end - begin) & _QWORD
    signed_difference = difference if difference < 1 << 63 else difference - (1 << 64)
    if abs(signed_difference) // 56 == 0:
        return
    if _read(storage, 0x594, 1):
        return
    if callbacks.low_hp is None:
        raise UnresolvedReplayDamageContext("reached low-HP bookkeeping is unavailable")
    callbacks.low_hp()
