"""Health rule gates, dynamic backing and reached transform callback effects."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest

from vantage.replay_damage import (
    ReplayDamageCallbacks,
    ReplayDamageStorage,
    apply_replay_unit_damage,
)
from vantage.replay_health_transforms import (
    ReplayHealthTransformCallbacks,
    ReplayHealthTransformStorage,
    UnresolvedReplayHealthTransform,
    run_replay_health_transforms,
)

_SUBJECT, _OWNER, _MASTER = 0x10000, 0x20000, 0x30000
_ROWS, _TABLE, _TARGET, _RESOURCES = 0x40000, 0x50000, 0x60000, 0x70000
_MASTER_ADD = 0x774A063B3D17506C
_NONE = ReplayHealthTransformCallbacks(None, None, None, None, None, None)


def _hp(bits: int) -> int:
    return (
        ((0x89ABCDEF00000000 | bits) + 0x147B5E081EC087D9) & ((1 << 64) - 1)
    ) ^ 0x0F2A55F7A61DD00E


def _resource(bits: int) -> int:
    return (
        (((bits ^ 0xA9834B738A7DD167) + 0x042AC42976FCCEF5) & ((1 << 64) - 1))
        ^ 0x6AE24D3352F04511
        ^ 0xC22D6B496D833977
    )


def _id(value: int) -> int:
    return ((value & 0xFFFF) + 0x47E37DFF0616CE4F) ^ 0x349E37847AD69F19


@dataclass
class _Memory:
    values: dict[tuple[int, int], int] = field(default_factory=dict)
    reads: list[tuple[int, int]] = field(default_factory=list)
    calls: list[tuple[str, tuple[int | bool, ...]]] = field(default_factory=list)

    def read(self, address: int, width: int) -> int:
        self.reads.append((address, width))
        return self.values[address, width]

    def put(self, address: int, width: int, value: int) -> None:
        self.values[address, width] = value

    def rule(
        self,
        address: int,
        *,
        target: int = 0,
        threshold: int = 0x41200000,
        gate: int = -1,
        extra: int = -1,
        scale: int = 0,
        payload: int = 17,
    ) -> None:
        for offset, width, value in (
            (0, 4, target & 0xFFFFFFFF),
            (4, 4, threshold),
            (8, 2, gate & 0xFFFF),
            (0xA, 2, extra & 0xFFFF),
            (0xC, 1, scale),
            (0x10, 4, payload),
        ):
            self.put(address + offset, width, value)

    def context(self) -> ReplayHealthTransformStorage:
        return ReplayHealthTransformStorage(_SUBJECT, self.read)

    def callbacks(self) -> ReplayHealthTransformCallbacks:
        def index(value: int) -> int:
            self.calls.append(("index", (value,)))
            return 123

        def flag(owner: int, value: int) -> int:
            self.calls.append(("flag", (owner, value)))
            return 0

        def announce(global_token: int, old: int, new: int) -> None:
            self.calls.append(("announce", (global_token, old, new)))

        def transform(master: int, value: bool) -> None:
            self.calls.append(("transform", (master, value)))

        def payload(kind: int, address: int) -> None:
            self.calls.append(("payload", (kind, address)))

        def post(value: int) -> None:
            self.calls.append(("post", (value,)))

        return ReplayHealthTransformCallbacks(index, flag, announce, transform, payload, post)

    def run(self, callbacks: ReplayHealthTransformCallbacks | None = None) -> None:
        run_replay_health_transforms(
            self.context(),
            mxcsr=0x1F80,
            callbacks=self.callbacks() if callbacks is None else callbacks,
        )


def _base(*, rows: int = 1, hp: int = 0x41A00000) -> _Memory:
    memory = _Memory()
    for at, width, value in (
        (_SUBJECT + 0x7A8, 8, _ROWS),
        (_SUBJECT + 0x7B0, 8, _ROWS + rows * 48),
        (_SUBJECT + 0x18, 8, _OWNER),
        (_SUBJECT + 0x10, 8, _MASTER + _MASTER_ADD),
        (_SUBJECT + 0x130, 8, _hp(hp)),
        (_OWNER + 0x20, 4, 1),
        (_OWNER + 0x28, 8, _TABLE),
        (_OWNER + 0x98, 8, _RESOURCES),
        (_TABLE, 8, _TARGET),
        (_MASTER + 0x228, 8, 0x123456789ABCDEF0),
        (0x144297830, 8, 0),
    ):
        memory.put(at, width, value)
    for index in range(rows):
        memory.rule(_ROWS + index * 48)
    return memory


def test_empty_rules_do_not_need_owner_master_global_or_callbacks() -> None:
    memory = _Memory({(_SUBJECT + 0x7A8, 8): 0, (_SUBJECT + 0x7B0, 8): 0})
    memory.run(_NONE)
    assert memory.reads == [(_SUBJECT + 0x7A8, 8), (_SUBJECT + 0x7B0, 8)]


def test_selected_row_calls_real_bound_sequence_once() -> None:
    memory = _base(rows=2)
    memory.run()
    assert memory.calls == [
        ("transform", (_TARGET, True)),
        ("payload", (17, _ROWS + 0x18)),
        ("post", (0x123456789ABCDEF0,)),
    ]
    assert (_ROWS + 48 + 8, 2) not in memory.reads
    # Separate cached gate, threshold, flag and special phases retain their reads.
    assert memory.reads[:11] == [
        (_SUBJECT + 0x7A8, 8),
        (_SUBJECT + 0x7B0, 8),
        (_ROWS + 8, 2),
        (_SUBJECT + 0x7A8, 8),
        (_ROWS + 0xA, 2),
        (_ROWS + 4, 4),
        (_SUBJECT + 0x7A8, 8),
        (_ROWS + 0xC, 1),
        (_SUBJECT + 0x7A8, 8),
        (_SUBJECT + 0x18, 8),
        (_ROWS + 0xA, 2),
    ]


@pytest.mark.parametrize(
    ("threshold", "hp", "selected"),
    [
        (0x41200000, 0x41200000, False),
        (0x41200000, 0x41300000, True),
        (0x41200000, 0x7FC00123, False),
        (0xC1200000, 0x41200000, False),
        (0xC1200000, 0x41100000, True),
        (0xC1200000, 0x80000000, True),
        (0xC1200000, 0xFF800123, False),
        (0, 0x41A00000, False),
        (0x80000000, 0x41A00000, False),
        (0x7F800123, 0x41A00000, False),
        (0xFFC00456, 0x41A00000, False),
        (0x7F800000, 0x7F800000, False),
        (0xFF800000, 0x41A00000, True),
        (0xFF800000, 0x7F800000, False),
    ],
)
def test_strict_ordered_thresholds(threshold: int, hp: int, selected: bool) -> None:
    memory = _base(hp=hp)
    memory.rule(_ROWS, threshold=threshold)
    memory.run()
    assert bool(memory.calls) is selected
    if threshold & 0x7FFFFFFF == 0 or threshold & 0x7FFFFFFF > 0x7F800000:
        assert (_SUBJECT + 0x130, 8) not in memory.reads


@pytest.mark.parametrize(
    ("resource", "selected"),
    [
        (0, False),
        (0x80000000, False),
        (0xBF800000, False),
        (0xFF800000, False),
        (1, True),
        (0x7F800000, True),
        (0x7F800123, True),
        (0xFFC00456, True),
    ],
)
def test_resource_gate_admits_unordered(resource: int, selected: bool) -> None:
    memory = _base()
    memory.rule(_ROWS, gate=2)
    memory.put(_RESOURCES + 16, 8, _resource(resource))
    memory.run()
    assert bool(memory.calls) is selected
    if not selected:
        assert (_ROWS + 0xA, 2) not in memory.reads
        assert (_SUBJECT + 0x130, 8) not in memory.reads


def test_negative_resource_gate_index_is_not_range_checked_or_treated_as_sentinel() -> None:
    memory = _base()
    memory.rule(_ROWS, gate=-2)
    memory.put(_RESOURCES - 16, 8, _resource(0x3F800000))
    memory.run()
    assert (_RESOURCES - 16, 8) in memory.reads
    assert memory.calls[0] == ("transform", (_TARGET, True))


def test_extra_resource_arithmetic_precedes_special_negative_index_calls() -> None:
    memory = _base()
    memory.rule(_ROWS, extra=-2)
    memory.put(_RESOURCES - 16, 8, _resource(0x7F800123))
    memory.run()
    assert memory.calls == [("index", (-2,)), ("flag", (_OWNER, 123))]
    assert (_SUBJECT + 0x130, 8) not in memory.reads  # Resulting NaN threshold.


@pytest.mark.parametrize(
    ("base", "hp", "selected"),
    [
        (100, 0x42480000, False),
        (100, 0x42700000, True),
        (-100, 0x42200000, True),
        (-100, 0x42700000, False),
        (0, 0x41A00000, False),
    ],
)
def test_any_nonzero_scale_uses_signed16_base_hp(base: int, hp: int, selected: bool) -> None:
    memory = _base(hp=hp)
    memory.rule(_ROWS, threshold=0x3F000000, scale=255)
    encoded_base = (base & 0xFFFF) ^ 0xD978539418047C54 ^ 0xABAA7F7397F61E6C
    memory.put(_MASTER + 0x68, 8, encoded_base)
    memory.run()
    assert bool(memory.calls) is selected
    assert (_MASTER + 0x68, 8) in memory.reads


@pytest.mark.parametrize(
    ("index", "count", "slot", "count_read", "table_read"),
    [
        (-1, 1, _TARGET, False, False),
        (1, 1, _TARGET, True, False),
        (0, 0, _TARGET, True, False),
        (0, 0xFFFFFFFF, _TARGET, True, False),
        (0, 1, 0, True, True),
    ],
)
def test_target_availability_is_signed_bounds_and_slot_presence(
    index: int,
    count: int,
    slot: int,
    count_read: bool,
    table_read: bool,
) -> None:
    memory = _base()
    memory.rule(_ROWS, target=index)
    memory.put(_OWNER + 0x20, 4, count)
    memory.put(_TABLE, 8, slot)
    memory.run()
    assert memory.calls == []
    assert ((_OWNER + 0x20, 4) in memory.reads) is count_read
    assert ((_OWNER + 0x28, 8) in memory.reads) is table_read


def test_unavailable_first_target_continues_to_second_rule() -> None:
    memory = _base(rows=2)
    memory.rule(_ROWS, target=-1)
    memory.run()
    assert memory.calls[1] == ("payload", (17, _ROWS + 48 + 0x18))
    assert memory.reads.count((_SUBJECT + 0x7B0, 8)) == 2


def test_special_callback_uses_captured_owner_then_fresh_row_and_owner_for_target() -> None:
    memory = _base()
    memory.rule(_ROWS, extra=-2)
    memory.put(_RESOURCES - 16, 8, _resource(0))
    new_owner, new_table, new_rows, new_target = 0x80000, 0x90000, 0xA0000, 0xB0000
    memory.rule(new_rows, target=1, payload=29)
    for at, width, value in (
        (new_owner + 0x20, 4, 2),
        (new_owner + 0x28, 8, new_table),
        (new_table + 8, 8, new_target),
    ):
        memory.put(at, width, value)
    callbacks = memory.callbacks()

    def translate(index: int) -> int:
        assert index == -2
        memory.put(_SUBJECT + 0x18, 8, new_owner)
        memory.put(_SUBJECT + 0x7A8, 8, new_rows)
        return 456

    memory.run(replace(callbacks, special_index=translate))
    assert memory.calls == [
        ("flag", (_OWNER, 456)),
        ("transform", (new_target, True)),
        ("payload", (29, new_rows + 0x18)),
        ("post", (0x123456789ABCDEF0,)),
    ]


def test_skipped_special_callback_reloads_begin_end_and_can_grow_rule_vector() -> None:
    memory = _base()
    memory.rule(_ROWS, extra=-2)
    memory.put(_RESOURCES - 16, 8, _resource(0))
    new_rows = 0x80000
    memory.rule(new_rows + 48, payload=71)
    callbacks = memory.callbacks()

    def flag(owner: int, translated: int) -> int:
        memory.put(_SUBJECT + 0x7A8, 8, new_rows)
        memory.put(_SUBJECT + 0x7B0, 8, new_rows + 96)
        return 255

    memory.run(replace(callbacks, special_owner_flag=flag))
    assert (new_rows + 48 + 8, 2) in memory.reads
    assert memory.calls[-2] == ("payload", (71, new_rows + 48 + 0x18))


def test_selected_sequence_preserves_held_target_and_refreshes_payload_and_master() -> None:
    memory = _base()
    memory.put(0x144297830, 8, 0xDEADBEEF)
    memory.put(_MASTER + 0x18, 8, _id(-32768))
    memory.put(_TARGET + 0x18, 8, _id(32767))
    new_rows, new_master = 0x80000, 0x90000
    memory.rule(new_rows, payload=0xFFFFFFFF)
    memory.put(new_master + 0x228, 8, 0xFEDCBA9876543210)
    callbacks = memory.callbacks()

    def announce(global_token: int, old: int, new: int) -> None:
        memory.calls.append(("announce", (global_token, old, new)))
        memory.put(_TABLE, 8, 0)  # Does not replace the already held target.

    def transform(target: int, flag: bool) -> None:
        memory.calls.append(("transform", (target, flag)))
        memory.put(_SUBJECT + 0x7A8, 8, new_rows)

    def payload(kind: int, address: int) -> None:
        memory.calls.append(("payload", (kind, address)))
        memory.put(_SUBJECT + 0x10, 8, new_master + _MASTER_ADD)

    memory.run(replace(callbacks, announce=announce, transform=transform, payload=payload))
    assert memory.calls == [
        ("announce", (0xDEADBEEF, -32768, 32767)),
        ("transform", (_TARGET, True)),
        ("payload", (0xFFFFFFFF, new_rows + 0x18)),
        ("post", (0xFEDCBA9876543210,)),
    ]
    assert (_MASTER + 0x228, 8) not in memory.reads


@pytest.mark.parametrize("missing", ["announce", "transform", "payload", "post_transform"])
def test_missing_reached_sequence_stops_after_prior_callback_effects(missing: str) -> None:
    memory = _base()
    memory.put(0x144297830, 8, 1)
    memory.put(_MASTER + 0x18, 8, _id(3))
    memory.put(_TARGET + 0x18, 8, _id(4))
    callbacks = replace(memory.callbacks(), **{missing: None})
    with pytest.raises(UnresolvedReplayHealthTransform):
        memory.run(callbacks)
    names = [call[0] for call in memory.calls]
    expected = ["announce", "transform", "payload", "post"]
    stopped = ["announce", "transform", "payload", "post_transform"].index(missing)
    assert names == expected[:stopped]


@pytest.mark.parametrize("failing", ["announce", "transform", "payload", "post_transform"])
def test_callback_exceptions_and_mutations_propagate(failing: str) -> None:
    memory = _base()
    memory.put(0x144297830, 8, 1)
    memory.put(_MASTER + 0x18, 8, _id(3))
    memory.put(_TARGET + 0x18, 8, _id(4))
    failure = RuntimeError("actual callback failed")

    def callback(*args: int) -> None:
        memory.put(_SUBJECT + 0x594, 1, 19)
        raise failure

    with pytest.raises(RuntimeError) as caught:
        memory.run(replace(memory.callbacks(), **{failing: callback}))
    assert caught.value is failure
    assert memory.values[_SUBJECT + 0x594, 1] == 19


def test_damage_healthy_binding_executes_real_empty_handler() -> None:
    memory = _base(rows=0)
    for offset, width, value in ((0x6C4, 4, 0), (0x6C0, 4, 0), (0x7E0, 4, 0)):
        memory.put(_SUBJECT + offset, width, value)
    memory.put(_MASTER + 0x3D0, 4, 0)

    def read_subject(offset: int, width: int) -> int:
        return memory.read(_SUBJECT + offset, width)

    def write_subject(offset: int, width: int, value: int) -> None:
        memory.put(_SUBJECT + offset, width, value)

    def read_master(offset: int, width: int) -> int:
        token = (read_subject(0x10, 8) - _MASTER_ADD) & ((1 << 64) - 1)
        return memory.read(token + offset, width)

    apply_replay_unit_damage(
        ReplayDamageStorage(read_subject, write_subject, read_master),
        0x3F800000,
        mxcsr=0x1F80,
        callbacks=ReplayDamageCallbacks(lambda: memory.run(_NONE), None),
    )
    assert memory.values[_SUBJECT + 0x130, 8] == _hp(0x41980000)  # 20-1=19.
    assert memory.reads[-2:] == [(_SUBJECT + 0x7A8, 8), (_SUBJECT + 0x7B0, 8)]


@pytest.mark.parametrize("mxcsr", [0, 0x1FC0, 0x9F80, 0x3F80, True, -1, 1 << 32])
def test_unsupported_controls_fail_before_storage(mxcsr: int) -> None:
    memory = _base()
    with pytest.raises(ValueError):
        run_replay_health_transforms(memory.context(), mxcsr=mxcsr, callbacks=_NONE)
    assert memory.reads == []
