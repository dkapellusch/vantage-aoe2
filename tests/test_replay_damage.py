"""Damage field order, protected HP writes and reached lifecycle behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from vantage.replay_damage import (
    ReplayDamageCallbacks,
    ReplayDamageStorage,
    UnresolvedReplayDamageContext,
    apply_replay_common_damage,
    apply_replay_unit_damage,
    replay_unit_hp_floor,
)

_MASK = (1 << 64) - 1
_BASE_XOR = 0xD978539418047C54 ^ 0xABAA7F7397F61E6C
_NO_CALLBACKS = ReplayDamageCallbacks(None, None)


def _encode(hp: int, high: int = 0x89ABCDEF) -> int:
    return ((((high << 32) | hp) + 0x147B5E081EC087D9) & _MASK) ^ 0x0F2A55F7A61DD00E


def _decoded(raw: int) -> int:
    return ((raw ^ 0x0F2A55F7A61DD00E) - 0x147B5E081EC087D9) & _MASK


@dataclass
class _Store:
    fields: dict[int, int]
    master: dict[int, int] = field(default_factory=dict)
    events: list[tuple[str, int, int, int | None]] = field(default_factory=list)

    def read(self, offset: int, width: int) -> int:
        self.events.append(("read", offset, width, None))
        return self.fields[offset]

    def write(self, offset: int, width: int, value: int) -> None:
        self.events.append(("write", offset, width, value))
        self.fields[offset] = value

    def read_master(self, offset: int, width: int) -> int:
        self.events.append(("master", offset, width, None))
        return self.master[offset]

    def binding(self, *, master: bool = True) -> ReplayDamageStorage:
        return ReplayDamageStorage(self.read, self.write, self.read_master if master else None)


def _unit(hp: int = 0x41200000) -> _Store:
    return _Store(
        {0x130: _encode(hp), 0x6C4: 0, 0x6C0: 0, 0x7E0: 0, 0x7F8: 0, 0x7F0: 0, 0x594: 0}, {0x3D0: 0}
    )


def _healthy(store: _Store) -> Callable[[], None]:
    def callback() -> None:
        store.events.append(("healthy", 0, 0, None))

    return callback


@pytest.mark.parametrize(
    ("hp", "damage", "expected"),
    [
        (0x41200000, 0x40400000, 0x40E00000),
        (0x3F800000, 0x40000000, 0xBF800000),
        (0x3F800000, 0xC0000000, 0x40400000),
        (0x80000000, 0, 0x80000000),
        (0, 0x80000000, 0),
        (0x7F800000, 0x7F800000, 0xFFC00000),
        (0xFF800123, 0x7FC00456, 0xFFC00123),
        (0x3F800000, 0xFF800123, 0xFFC00123),
        (0x7F7FFFFF, 0xFF7FFFFF, 0x7F800000),
    ],
)
@pytest.mark.parametrize("high", [0, 0x89ABCDEF, 0xFFFFFFFF])
def test_common_full_protected_word(hp: int, damage: int, expected: int, high: int) -> None:
    store = _Store({0x130: _encode(hp, high)})
    apply_replay_common_damage(store.binding(master=False), damage, mxcsr=0x1F80)
    assert store.fields[0x130] == _encode(expected, high)
    assert _decoded(store.fields[0x130]) >> 32 == high
    assert store.events == [("read", 0x130, 8, None), ("write", 0x130, 8, _encode(expected, high))]


@pytest.mark.parametrize(
    ("factor", "fallback", "base", "expected", "master_reads"),
    [
        (0, 0, None, 0, [(0x3D0, 4)]),
        (0x80000000, 0x80000000, None, 0, [(0x3D0, 4)]),
        (0xBF800000, None, None, 0x3F800000, []),
        (0xFF800123, None, None, 0x7F800123, []),
        (0x7FC00456, None, None, 0x7FC00456, []),
        (0, 0xFF800123, None, 0x7F800123, [(0x3D0, 4)]),
        (0x3F000000, None, 101, 0x424A0000, [(0x68, 8)]),
        (0x3F800000, None, -32768, 0xC7000000, [(0x68, 8)]),
        (0, 0x3F000000, -101, 0xC24A0000, [(0x3D0, 4), (0x68, 8)]),
        (0x7F800000, None, 0, 0xFFC00000, [(0x68, 8)]),
    ],
)
def test_floor_reached_reads(
    factor: int,
    fallback: int | None,
    base: int | None,
    expected: int,
    master_reads: list[tuple[int, int]],
) -> None:
    store = _Store({0x7E0: factor})
    if fallback is not None:
        store.master[0x3D0] = fallback
    if base is not None:
        store.master[0x68] = (0xFEDCBA9876540000 | (base & 0xFFFF)) ^ _BASE_XOR
    assert replay_unit_hp_floor(store.binding(), mxcsr=0x1F80) == expected
    assert store.events == [
        ("read", 0x7E0, 4, None),
        *(("master", at, size, None) for at, size in master_reads),
    ]


def test_floor_resolves_master_again_for_base_hp() -> None:
    store = _Store({0x7E0: 0})
    reads: list[tuple[int, int]] = []

    def current_master(offset: int, width: int) -> int:
        reads.append((offset, width))
        return 0x3F800000 if len(reads) == 1 else (37 ^ _BASE_XOR)

    bound = ReplayDamageStorage(store.read, store.write, current_master)
    assert replay_unit_hp_floor(bound, mxcsr=0x1F80) == 0x42140000
    assert reads == [(0x3D0, 4), (0x68, 8)]


@pytest.mark.parametrize(
    ("absorbed", "damage", "expected"),
    [
        (0x40000000, 0x40400000, 0x40A00000),
        (0x40000000, 0x41000000, 0x41200000),
        (0x40000000, 0xBF800000, 0x3F800000),
        (0x80000000, 0x80000000, 0x80000000),
    ],
)
def test_fully_absorbed_skips_all_hp_master_and_lifecycle(
    absorbed: int,
    damage: int,
    expected: int,
) -> None:
    store = _Store({0x6C4: 0x41200000, 0x6C0: absorbed})
    apply_replay_unit_damage(
        store.binding(master=False), damage, mxcsr=0x1F80, callbacks=_NO_CALLBACKS
    )
    assert store.events == [
        ("read", 0x6C4, 4, None),
        ("read", 0x6C0, 4, None),
        ("write", 0x6C0, 4, expected),
    ]


def test_overshoot_stores_absorption_before_hp_floor_and_healthy_callback() -> None:
    store = _unit()
    store.fields.update({0x6C4: 0x40A00000, 0x6C0: 0x40000000})
    apply_replay_unit_damage(
        store.binding(),
        0x41000000,
        mxcsr=0x1F80,
        callbacks=ReplayDamageCallbacks(_healthy(store), None),
    )
    assert store.fields[0x6C0] == 0x40A00000
    assert store.fields[0x130] == _encode(0x40A00000)
    assert [(k, at, width) for k, at, width, _ in store.events] == [
        ("read", 0x6C4, 4),
        ("read", 0x6C0, 4),
        ("write", 0x6C0, 4),
        ("read", 0x130, 8),
        ("read", 0x7E0, 4),
        ("master", 0x3D0, 4),
        ("write", 0x130, 8),
        ("read", 0x130, 8),
        ("healthy", 0, 0),
    ]


def test_absorption_rounded_add_is_not_replaced_by_cap() -> None:
    # cap=1, absorbed=-2**25: rounded gap=2**25, rounded absorbed+gap=+0.
    store = _unit()
    store.fields.update({0x6C4: 0x3F800000, 0x6C0: 0xCC000000})
    apply_replay_unit_damage(
        store.binding(),
        0x4C000001,
        mxcsr=0x1F80,
        callbacks=ReplayDamageCallbacks(_healthy(store), None),
    )
    assert store.fields[0x6C0] == 0
    assert _decoded(store.fields[0x130]) & 0xFFFFFFFF == 0x40C00000


@pytest.mark.parametrize(
    "cap,absorbed",
    [
        (0, 0),
        (0xBF800000, 0),
        (0x7FC00123, 0),
        (0x41200000, 0xFF800123),
    ],
)
def test_ineligible_absorption_is_not_written(cap: int, absorbed: int) -> None:
    store = _unit()
    store.fields.update({0x6C4: cap, 0x6C0: absorbed})
    apply_replay_unit_damage(
        store.binding(),
        0x3F800000,
        mxcsr=0x1F80,
        callbacks=ReplayDamageCallbacks(_healthy(store), None),
    )
    assert store.fields[0x6C0] == absorbed
    assert not any(k == "write" and at == 0x6C0 for k, at, _, _ in store.events)
    assert store.fields[0x130] == _encode(0x41100000)


@pytest.mark.parametrize(
    ("hp", "factor", "expected", "healthy"),
    [
        (0x3F800000, 0xC0000000, 0x40000000, True),  # Absolute floor2.
        (0x7FC00123, 0xBF800000, 0x3F800000, True),  # Unordered candidate keeps floor.
        (0x41200000, 0xFF800123, 0x7F800123, False),  # Preserve sNaN floor/raw store.
        (0x80000000, 0, 0x80000000, False),
    ],
)
def test_floor_selection_and_post_write_unordered_route(
    hp: int,
    factor: int,
    expected: int,
    healthy: bool,
) -> None:
    store = _unit(hp)
    store.fields[0x7E0] = factor
    apply_replay_unit_damage(
        store.binding(), 0, mxcsr=0x1F80, callbacks=ReplayDamageCallbacks(_healthy(store), None)
    )
    assert store.fields[0x130] == _encode(expected)
    assert any(event[0] == "healthy" for event in store.events) is healthy
    assert any(event[:3] == ("read", 0x7F8, 8) for event in store.events) is not healthy


@pytest.mark.parametrize(
    ("begin", "end", "flag", "reached", "flag_read"),
    [
        (0, 0, 0, False, False),
        (100, 155, 0, False, False),
        (100, 156, 0, True, True),
        (100, 156, 255, False, True),
        (156, 100, 0, True, True),
        (0xFFFFFFFFFFFFFFF0, 40, 0, True, True),
    ],
)
def test_low_hp_credit_count_and_notified_gate(
    begin: int,
    end: int,
    flag: int,
    reached: bool,
    flag_read: bool,
) -> None:
    store = _unit(0)
    store.fields.update({0x7F0: begin, 0x7F8: end, 0x594: flag})
    called: list[str] = []
    apply_replay_unit_damage(
        store.binding(),
        0,
        mxcsr=0x1F80,
        callbacks=ReplayDamageCallbacks(None, lambda: called.append("low")),
    )
    assert called == (["low"] if reached else [])
    assert any(event[:3] == ("read", 0x594, 1) for event in store.events) is flag_read
    # Only the scalar gate is implemented. A successful callback owns any594 write.
    assert store.fields[0x594] == flag


def test_unknown_master_after_absorption_keeps_earlier_write() -> None:
    store = _unit()
    store.fields.update({0x6C4: 0x40A00000, 0x6C0: 0x40000000})
    original_hp = store.fields[0x130]
    with pytest.raises(UnresolvedReplayDamageContext, match="master"):
        apply_replay_unit_damage(
            store.binding(master=False), 0x41000000, mxcsr=0x1F80, callbacks=_NO_CALLBACKS
        )
    assert store.fields[0x6C0] == 0x40A00000
    assert store.fields[0x130] == original_hp


@pytest.mark.parametrize("low", [False, True])
def test_missing_reached_continuation_raises_after_hp_store(low: bool) -> None:
    store = _unit(0x3F800000 if low else 0x41200000)
    if low:
        store.fields[0x7F8] = 56
    with pytest.raises(UnresolvedReplayDamageContext, match="bookkeeping" if low else "lifecycle"):
        apply_replay_unit_damage(store.binding(), 0x3F800000, mxcsr=0x1F80, callbacks=_NO_CALLBACKS)
    assert store.fields[0x130] == _encode(0 if low else 0x41100000)


@pytest.mark.parametrize("low", [False, True])
def test_callback_exception_retains_damage_and_callback_mutations(low: bool) -> None:
    store = _unit(0x3F800000 if low else 0x41200000)
    store.fields[0x7F8] = 56

    def callback() -> None:
        assert store.fields[0x130] == _encode(0 if low else 0x41100000)
        store.fields[0x594] = 17
        raise RuntimeError("lifecycle stopped")

    callbacks = ReplayDamageCallbacks(None if low else callback, callback if low else None)
    with pytest.raises(RuntimeError, match="lifecycle stopped"):
        apply_replay_unit_damage(store.binding(), 0x3F800000, mxcsr=0x1F80, callbacks=callbacks)
    assert store.fields[0x594] == 17
    assert store.fields[0x130] == _encode(0 if low else 0x41100000)


@pytest.mark.parametrize("operation", [apply_replay_common_damage, apply_replay_unit_damage])
@pytest.mark.parametrize("mxcsr", [0, 0x1FC0, 0x9F80, 0x3F80, True, -1, 1 << 32])
def test_unsupported_controls_refused_before_storage_access(
    operation: Callable[..., None],
    mxcsr: int,
) -> None:
    store = _unit()
    extra = {"callbacks": _NO_CALLBACKS} if operation is apply_replay_unit_damage else {}
    with pytest.raises(ValueError):
        operation(store.binding(), 0, mxcsr=mxcsr, **extra)
    assert store.events == []


def test_masked_sticky_flags_do_not_change_scalar_results() -> None:
    store = _Store({0x130: _encode(0x41200000)})
    apply_replay_common_damage(store.binding(master=False), 0x3F800000, mxcsr=0x1FBF)
    assert store.fields[0x130] == _encode(0x41100000)


def test_bad_reached_read_is_refused() -> None:
    store = _unit()
    store.fields[0x6C4] = 1 << 32
    with pytest.raises(ValueError, match="storage read"):
        apply_replay_unit_damage(store.binding(), 0, mxcsr=0x1F80, callbacks=_NO_CALLBACKS)
    assert not any(event[0] == "write" for event in store.events)
