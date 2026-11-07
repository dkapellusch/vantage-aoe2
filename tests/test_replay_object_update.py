"""Retained native traces and source-led current-storage/virtual-call controls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_object_update import ReplayObjectUpdateProfile, bind_replay_object_update
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

ENTRY = 0x141229A20
ORACLE = json.loads(
    (Path(__file__).parent / "fixtures/native_object_update_dispatch_54800.json").read_bytes()
)


class Rig:
    def __init__(self, *, count=3, maximum=32):
        self.memory = ReplayMemory()
        self.address = self.memory.allocate(0x18)
        self.buffer = self.memory.allocate(5 * 8)
        self.objects = [self.memory.allocate(8) for _ in range(5)]
        self.vtables = [self.memory.allocate(0x38) for _ in range(5)]
        self.handlers = {}
        self.events = []
        self.on_read = None
        self.memory.write(self.address + 8, 8, self.buffer)
        self.set_count(count)
        self.replace_items([1, 2, 3, 0, 0])
        for index, (obj, table) in enumerate(zip(self.objects, self.vtables, strict=True)):
            self.memory.write(obj, 8, table)
            self.memory.write(table + 0x30, 8, 0xA000 + index)
            self.memory.write(table + 0x18, 8, 0xB000 + index)
            self.handlers[0xA000 + index] = lambda args, data: 0
            self.handlers[0xB000 + index] = lambda args, data: None

        def read(address, width):
            self.events.append(("read", address, width))
            value = self.memory.read(address, width)
            if self.on_read is not None:
                self.on_read(address, width)
            return value

        def dispatch(target, args, data):
            self.events.append(("call", target, args, data))
            if target == ENTRY:
                return self.binding.call(target, args, data)
            if target not in self.handlers:
                raise UnresolvedReplayTaskRebuild(f"owned test provider {target:x} unavailable")
            return self.handlers[target](args, data)

        self.calls = ReplayTaskRebuildCalls(dispatch)
        self.binding = bind_replay_object_update(
            ReplayTaskRebuildStorage(0x123456, read, self.memory.write),
            self.calls,
            profile=ReplayObjectUpdateProfile(maximum),
        )

    def set_count(self, value):
        self.memory.write(self.address + 0x10, 4, value & 0xFFFFFFFF)

    def count(self):
        raw = self.memory.read(self.address + 0x10, 4)
        return raw if raw < 0x80000000 else raw - (1 << 32)

    def replace_items(self, identifiers, *, reallocate=False):
        if reallocate:
            self.buffer = self.memory.allocate(max(1, len(identifiers)) * 8)
            self.memory.write(self.address + 8, 8, self.buffer)
        for index, identifier in enumerate(identifiers):
            self.memory.write(self.buffer + 8 * index, 8, self.objects[identifier])

    def active_ids(self):
        return [
            self.objects.index(self.memory.read(self.buffer + 8 * index, 8))
            for index in range(max(0, self.count()))
        ]

    def run(self, address=None):
        return self.binding.call(ENTRY, (self.address if address is None else address,), None)


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda case: case["name"])
def test_addressed_dispatch_reproduces_all_retained_original_native_traces(case):
    name = case["name"]
    count = 0 if name == "empty" else -1 if name == "negative_count" else 3
    if name in ("append_reallocate", "post_without_removal"):
        count = 2
    rig = Rig(count=count)
    trace, updates = [], [0] * 5

    def update(args, data):
        assert data is None
        identifier = rig.objects.index(args[0])
        trace.append(f"U{identifier}")
        updates[identifier] += 1
        if identifier == 1 and updates[identifier] == 1:
            if name == "update_removes_itself":
                rig.replace_items(rig.active_ids()[1:])
                rig.set_count(rig.count() - 1)
                return 1
            if name in ("post_swap_remove", "post_shift_remove", "post_without_removal"):
                return 1
            if name == "append_reallocate":
                rig.replace_items([*rig.active_ids(), 3, *([0] * 5)], reallocate=True)
                rig.set_count(rig.count() + 1)
            if name == "shrink_count":
                rig.set_count(1)
            if name == "replace_later":
                rig.memory.write(rig.buffer + 8, 8, rig.objects[4])
            if name == "negative_during_update":
                rig.set_count(-1)
        return 0

    def remove(args, data):
        assert data is None
        identifier = rig.objects.index(args[0])
        trace.append(f"P{identifier}")
        if name == "update_removes_itself":
            return None
        active = rig.active_ids()
        at = active.index(identifier)
        if name == "post_swap_remove":
            active[at] = active[-1]
            rig.replace_items(active[:-1])
            rig.set_count(rig.count() - 1)
        elif name == "post_shift_remove":
            rig.replace_items(active[:at] + active[at + 1 :])
            rig.set_count(rig.count() - 1)
        return None

    for identifier in range(5):
        rig.handlers[0xA000 + identifier] = update
        rig.handlers[0xB000 + identifier] = remove
    assert rig.run() is None
    assert ",".join(trace) == case["trace"]
    assert rig.count() == case["final_count"]
    assert rig.active_ids() == case["active_ids"]
    assert updates[1:] == case["updates"]


@pytest.mark.parametrize("raw_count", [0, 0x80000000, 0xFFFFFFFF])
def test_nonpositive_count_returns_after_one_read_even_with_no_callbacks_or_buffer(raw_count):
    events = []

    def read(address, width):
        events.append((address, width))
        assert (address, width) == (0x1010, 4)
        return raw_count

    calls = bind_replay_object_update(
        ReplayTaskRebuildStorage(1, read, lambda *args: pytest.fail("no body stores")),
        ReplayTaskRebuildCalls(None),
        profile=ReplayObjectUpdateProfile(0),
    )
    assert calls.call(ENTRY, (0x1000,), None) is None
    assert events == [(0x1010, 4)]


def test_exact_read_call_order_has_no_second_count_read_before_first_callback():
    rig = Rig(count=1)

    def after_read(address, width):
        if address == rig.address + 8:
            rig.set_count(0)

    rig.on_read = after_read
    assert rig.run() is None
    obj, table = rig.objects[1], rig.vtables[1]
    assert rig.events == [
        ("read", rig.address + 0x10, 4),
        ("read", rig.address + 8, 8),
        ("read", rig.buffer, 8),
        ("read", obj, 8),
        ("read", table + 0x30, 8),
        ("call", 0xA001, (obj,), None),
        ("read", rig.address + 0x10, 4),
    ]


def test_removal_uses_held_object_and_its_current_vtable_after_slot_replacement():
    rig = Rig(count=1)
    obj = rig.objects[1]
    new_table = rig.memory.allocate(0x38)
    rig.memory.write(new_table + 0x18, 8, 0xD001)

    def update(args, data):
        rig.memory.write(rig.buffer, 8, rig.objects[2])
        rig.memory.write(obj, 8, new_table)
        return 0x10001

    def remove(args, data):
        assert args == (obj,) and data is None
        rig.set_count(0)
        return 0xBAD0

    rig.handlers.update({0xA001: update, 0xD001: remove})
    assert rig.run() is None
    assert [event for event in rig.events if event[0] == "call"] == [
        ("call", 0xA001, (obj,), None),
        ("call", 0xD001, (obj,), None),
    ]
    assert ("read", new_table + 0x18, 8) in rig.events


@pytest.mark.parametrize(
    "raw_result,removes", [(0x100, False), (0xFF00, False), (0xFF, True), (0x100000000000001, True)]
)
def test_only_low_al_controls_removal_and_removal_rax_is_ignored(raw_result, removes):
    rig = Rig(count=1)

    def update(args, data):
        rig.set_count(0)
        return raw_result

    rig.handlers[0xA001] = update
    rig.handlers[0xB001] = lambda args, data: None
    assert rig.run() is None
    targets = [event[1] for event in rig.events if event[0] == "call"]
    assert targets == ([0xA001, 0xB001] if removes else [0xA001])


def test_low_al_zero_does_not_dereference_object_or_vtable_after_callback_frees_them():
    rig = Rig(count=1)

    def update(args, data):
        rig.set_count(0)
        rig.memory.free(rig.vtables[1])
        rig.memory.free(rig.objects[1])
        return 0x100

    rig.handlers[0xA001] = update
    assert rig.run() is None


def test_zero_work_budget_refuses_after_entry_count_before_buffer_or_callback():
    rig = Rig(count=1, maximum=0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="work limit"):
        rig.run()
    assert rig.events == [("read", rig.address + 0x10, 4)]


def test_nonprogressing_removal_is_not_faked_and_work_limit_retains_prior_effects():
    rig = Rig(count=1, maximum=3)
    effects = []
    rig.handlers[0xA001] = lambda args, data: 1
    rig.handlers[0xB001] = lambda args, data: effects.append(args[0])
    with pytest.raises(UnresolvedReplayTaskRebuild, match="work limit"):
        rig.run()
    assert effects == [rig.objects[1]] * 3
    assert rig.count() == 1 and rig.active_ids() == [1]
    assert [event[1] for event in rig.events if event[0] == "call"] == [0xA001, 0xB001] * 3


def test_reentrant_owned_calls_share_work_and_outer_finally_resets_after_failure():
    rig = Rig(count=2, maximum=2)
    inner = rig.memory.allocate(0x18)
    inner_buffer = rig.memory.allocate(8)
    rig.memory.write(inner + 8, 8, inner_buffer)
    rig.memory.write(inner + 0x10, 4, 1)
    rig.memory.write(inner_buffer, 8, rig.objects[2])

    def update(args, data):
        rig.calls.call(ENTRY, (inner,), None)
        return 0

    rig.handlers[0xA001] = update
    with pytest.raises(UnresolvedReplayTaskRebuild, match="work limit"):
        rig.run()
    assert [event[1] for event in rig.events if event[0] == "call"] == [0xA001, ENTRY, 0xA002]
    # After failure a fresh outer invocation gets its full budget again.
    rig.set_count(1)
    assert rig.run() is None


def test_each_successful_outer_call_starts_with_a_fresh_work_limit():
    rig = Rig(count=1, maximum=1)
    for _ in range(3):
        assert rig.run() is None
    assert sum(event[0] == "call" for event in rig.events) == 3


def test_missing_update_and_removal_providers_refuse_in_source_order():
    rig = Rig(count=1)
    del rig.handlers[0xA001]
    with pytest.raises(UnresolvedReplayTaskRebuild, match="a001 unavailable"):
        rig.run()
    assert rig.events[-1] == ("call", 0xA001, (rig.objects[1],), None)
    rig.handlers[0xA001] = lambda args, data: 1
    del rig.handlers[0xB001]
    with pytest.raises(UnresolvedReplayTaskRebuild, match="b001 unavailable"):
        rig.run()
    assert rig.events[-1] == ("call", 0xB001, (rig.objects[1],), None)


def test_null_object_is_read_and_refuses_missing_backing_instead_of_being_skipped():
    rig = Rig(count=1)
    rig.memory.write(rig.buffer, 8, 0)
    with pytest.raises(ReplayMemoryError):
        rig.run()
    assert rig.events[-1] == ("read", 0, 8)


@pytest.mark.parametrize("result", [None, True, -1, 1 << 64])
def test_update_provider_must_supply_an_actual_raw_result(result):
    rig = Rig(count=1)
    rig.handlers[0xA001] = lambda args, data: result
    with pytest.raises(ValueError, match=r"raw|unsigned"):
        rig.run()


def test_child_exception_preserves_effects_and_does_not_force_a_bottom_count_read():
    rig = Rig(count=1)

    def update(args, data):
        rig.set_count(-1)
        raise RuntimeError("actual update failed")

    rig.handlers[0xA001] = update
    with pytest.raises(RuntimeError, match="actual update failed"):
        rig.run()
    assert rig.count() == -1
    assert rig.events[-1][0] == "call"


def test_held_list_and_vtable_slot_address_arithmetic_wraps_u64():
    memory = ReplayMemory(start=0x1000)
    obj, buffer = memory.allocate(8), memory.allocate(8)
    memory.write(obj, 8, (1 << 64) - 0x20)
    memory.write(buffer, 8, obj)
    memory.map_bytes(
        0, buffer.to_bytes(8, "little") + (1).to_bytes(8, "little") + (0xC001).to_bytes(8, "little")
    )
    events = []

    def dispatch(target, args, data):
        events.append((target, args, data))
        return 0

    calls = bind_replay_object_update(
        ReplayTaskRebuildStorage(1, memory.read, memory.write),
        ReplayTaskRebuildCalls(dispatch),
        profile=ReplayObjectUpdateProfile(1),
    )
    assert calls.call(ENTRY, ((1 << 64) - 8,), None) is None
    assert events == [(0xC001, (obj,), None)]


def test_unknown_delegation_preserves_argument_payload_and_result_identity():
    raw = memoryview(bytearray(b"raw"))
    args = (3, 4)
    seen = []

    def dispatch(target, received, data):
        seen.append((target, received is args, data is raw))
        return 0xABCD

    calls = bind_replay_object_update(
        ReplayTaskRebuildStorage(
            1,
            lambda *args: pytest.fail("unexpected read"),
            lambda *args: pytest.fail("unexpected store"),
        ),
        ReplayTaskRebuildCalls(dispatch),
        profile=ReplayObjectUpdateProfile(0),
    )
    assert calls.call(0x99, args, raw) == 0xABCD
    assert seen == [(0x99, True, True)]


@pytest.mark.parametrize(
    "args,data",
    [
        ((), None),
        ((1, 2), None),
        ((1,), memoryview(b"x")),
        ((True,), None),
        ((-1,), None),
        ((1 << 64,), None),
    ],
)
def test_bad_known_abi_refuses_before_any_source_read(args, data):
    rig = Rig()
    with pytest.raises(ValueError):
        rig.binding.call(ENTRY, args, data)
    assert rig.events == []


@pytest.mark.parametrize("maximum", [-1, True, 1.0, None])
def test_work_profile_requires_an_actual_nonnegative_integer(maximum):
    with pytest.raises(ValueError, match="nonnegative"):
        ReplayObjectUpdateProfile(maximum)
