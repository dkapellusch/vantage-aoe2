"""Source-derived current-state controls; unknown child programs stay explicit."""

from __future__ import annotations

import pytest

from vantage.replay_base_saved_support import (
    bind_replay_base_saved_support,
    create_replay_base_saved_sprite,
    notify_replay_base_saved_object,
    set_replay_base_saved_attachment,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

SET, SPRITE, NOTIFY = 0x141248810, 0x14124DD00, 0x141868CB0
REFRESH, ALLOCATE, CONSTRUCT = 0x1412475D0, 0x142D6BA78, 0x141480D30
GET, SEND = 0x14185B6D0, 0x14185CE10
U64 = (1 << 64) - 1


class Harness:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events = []
        self.after_read = lambda address, width, value: None
        self.before_write = lambda address, width, value: None
        self.on_call = lambda target, args, data: None
        self.runtime = self.memory.runtime_calls()
        self.context = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.call)
        self.bound = bind_replay_base_saved_support(self.context, self.calls)

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("read", address, width, value))
        self.after_read(address, width, value)
        return value

    def write(self, address, width, value):
        self.events.append(("write", address, width, value))
        self.before_write(address, width, value)
        self.memory.write(address, width, value)

    def call(self, target, args, data):
        self.events.append(("call", target, args, data))
        if target == ALLOCATE:
            assert self.runtime.call is not None
            return self.runtime.call(target, args, data)
        return self.on_call(target, args, data)

    def invoke(self, target, *args):
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def subject(self, previous=0, active=0, kind=0):
        address = self.memory.allocate(0x160)
        self.memory.write_bytes(address, b"\xa5" * 0x160)
        self.memory.write(address + 0x138, 8, previous)
        self.memory.write(address + 0x140, 1, kind)
        self.memory.write(address + 0x141, 1, active)
        return address

    def attachment(self, kind):
        address = self.memory.allocate(16)
        self.memory.write_bytes(address, b"\xcc" * 16)
        self.memory.write(address + 9, 1, kind)
        return address


@pytest.mark.parametrize("target", [0, 0xBAD, U64])
@pytest.mark.parametrize("bound", [False, True])
def test_same_pointer_skips_unavailable_later_fields_and_all_effects(target, bound) -> None:
    h = Harness()
    subject = h.memory.allocate(0x150)
    h.memory.write(subject + 0x138, 8, target)
    before = h.memory.snapshot()
    if bound:
        h.invoke(SET, subject, target)
    else:
        set_replay_base_saved_attachment(
            h.context, subject, target, calls=ReplayTaskRebuildCalls(None)
        )
    assert h.events == [("read", subject + 0x138, 8, target)]
    assert h.memory.snapshot() == before


@pytest.mark.parametrize("active", [0, 1, 0x80, 0xFF])
def test_null_attachment_publishes_then_only_clears_active_byte(active) -> None:
    h = Harness()
    subject = h.subject(0xBAD, active, 0x7F)
    h.invoke(SET, subject, 0)
    expected = [
        ("read", subject + 0x138, 8, 0xBAD),
        ("write", subject + 0x138, 8, 0),
        ("read", subject + 0x141, 1, active),
    ]
    if active:
        expected += [("write", subject + 0x141, 1, 0), ("call", REFRESH, (subject,), None)]
    assert h.events == expected
    assert h.memory.read(subject + 0x140, 1) == 0x7F
    assert h.memory.read_bytes(subject + 0x142, 30) == b"\xa5" * 30


@pytest.mark.parametrize(
    "active,old_kind,new_kind,refresh",
    [
        (0, 1, 1, True),
        (0, 1, 255, True),
        (1, 7, 7, False),
        (128, 7, 7, False),
        (255, 7, 8, True),
        (1, 255, 0, True),
    ],
)
@pytest.mark.parametrize("bound", [False, True])
def test_nonnull_exact_read_order_and_widths(active, old_kind, new_kind, refresh, bound) -> None:
    h = Harness()
    target = h.attachment(new_kind)
    subject = h.subject(0, active, old_kind)
    if bound:
        h.invoke(SET, subject, target)
    else:
        set_replay_base_saved_attachment(h.context, subject, target, calls=h.calls)
    expected = [
        ("read", subject + 0x138, 8, 0),
        ("write", subject + 0x138, 8, target),
        ("read", subject + 0x141, 1, active),
        ("read", target + 9, 1, new_kind),
    ]
    if active:
        expected.append(("read", subject + 0x140, 1, old_kind))
    if refresh:
        expected += [
            ("write", subject + 0x140, 1, new_kind),
            ("write", subject + 0x141, 1, 1),
            ("call", REFRESH, (subject,), None),
        ]
    assert h.events == expected
    assert h.memory.read(subject + 0x138, 8) == target
    assert h.memory.read_bytes(subject + 0x142, 30) == b"\xa5" * 30


def test_inactive_branch_still_reads_target_byte_and_keeps_published_pointer_on_failure() -> None:
    h = Harness()
    subject = h.subject()
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.invoke(SET, subject, 0xBAD)
    assert h.memory.read(subject + 0x138, 8) == 0xBAD
    assert h.events == [
        ("read", subject + 0x138, 8, 0),
        ("write", subject + 0x138, 8, 0xBAD),
        ("read", subject + 0x141, 1, 0),
    ]


def test_active_is_held_but_kind_comparison_is_current_after_descriptor_read() -> None:
    h = Harness()
    subject, target = h.subject(0, 1, 8), h.attachment(7)

    def mutate(address, width, value):
        if address == subject + 0x141:
            h.memory.write(address, 1, 0)
        if address == target + 9:
            h.memory.write(address, 1, 99)
            h.memory.write(subject + 0x140, 1, 7)

    h.after_read = mutate
    h.invoke(SET, subject, target)
    assert h.events[-1] == ("read", subject + 0x140, 1, 7)
    assert h.memory.read(subject + 0x141, 1) == 0
    assert not any(event[0] == "call" for event in h.events)


def test_inactive_branch_uses_captured_descriptor_kind_after_backing_mutates() -> None:
    h = Harness()
    subject, target = h.subject(0, 0, 8), h.attachment(7)

    def mutate(address, width, value):
        if address == target + 9:
            h.memory.write(address, 1, 99)

    h.after_read = mutate
    h.invoke(SET, subject, target)
    assert h.memory.read(subject + 0x140, 1) == 7
    assert h.memory.read(subject + 0x141, 1) == 1


def test_attachment_alias_target_byte_reads_after_pointer_publication() -> None:
    h = Harness()
    subject = h.subject(0, 0, 0x77)
    target = subject + 0x12F
    h.invoke(SET, subject, target)
    assert h.memory.read(subject + 0x140, 1) == target & 0xFF


def test_missing_reset_effect_refuses_after_exact_flag_stores() -> None:
    h = Harness()
    subject = h.subject(0xBAD, 255, 7)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        set_replay_base_saved_attachment(h.context, subject, 0, calls=ReplayTaskRebuildCalls(None))
    assert h.memory.read(subject + 0x138, 8) == 0
    assert h.memory.read(subject + 0x141, 1) == 0
    assert h.memory.read(subject + 0x140, 1) == 7


def test_reset_callback_failure_preserves_prior_and_actual_callback_effects() -> None:
    h = Harness()
    subject, target = h.subject(), h.attachment(9)

    def fail(actual, args, data):
        assert actual == REFRESH and args == (subject,)
        assert h.memory.read(subject + 0x141, 1) == 1
        h.memory.write(subject + 0x140, 1, 88)
        raise RuntimeError("reset child")

    h.on_call = fail
    with pytest.raises(RuntimeError, match="reset child"):
        h.invoke(SET, subject, target)
    assert h.memory.read(subject + 0x138, 8) == target
    assert h.memory.read(subject + 0x140, 1) == 88


def test_second_flag_store_failure_preserves_first_byte_and_pointer() -> None:
    h = Harness()
    subject, target = h.subject(), h.attachment(9)

    def fail(address, width, value):
        if address == subject + 0x141:
            raise RuntimeError("active store")

    h.before_write = fail
    with pytest.raises(RuntimeError, match="active store"):
        h.invoke(SET, subject, target)
    assert h.memory.read(subject + 0x138, 8) == target
    assert h.memory.read(subject + 0x140, 1) == 9
    assert not any(event[0] == "call" for event in h.events)


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("result", [0, 0x8000000000000001, U64])
def test_sprite_real_allocation_two16b_stores_and_actual_constructor_return(bound, result) -> None:
    h = Harness()
    subject = h.subject()
    before = h.memory.read_bytes(subject, 0x160)
    allocated = []

    def construct(target, args, data):
        assert target == CONSTRUCT and data is None
        pointer, owner = args
        assert owner == subject
        assert h.memory.read_bytes(pointer, 32) == bytes(32)
        region = next(r for r in h.memory.snapshot().regions if r.address == pointer)
        assert region.defined == b"\x01" * 32
        allocated.append(pointer)
        h.memory.write(pointer + 8, 8, 0xABC)
        return result

    h.on_call = construct
    actual = (
        h.invoke(SPRITE, subject)
        if bound
        else create_replay_base_saved_sprite(h.context, subject, calls=h.calls)
    )
    assert actual == result
    pointer = allocated[0]
    assert h.events == [
        ("call", ALLOCATE, (32,), None),
        ("write", pointer, 16, 0),
        ("write", pointer + 16, 16, 0),
        ("call", CONSTRUCT, (pointer, subject), None),
    ]
    assert h.memory.read_bytes(subject, 0x160) == before


def test_sprite_null_allocation_returns_zero_without_store_or_constructor() -> None:
    h = Harness()
    seen = []

    def allocate(target, args, data):
        seen.append((target, args, data))
        return 0

    assert (
        create_replay_base_saved_sprite(h.context, 0xBAD, calls=ReplayTaskRebuildCalls(allocate))
        == 0
    )
    assert seen == [(ALLOCATE, (32,), None)] and h.events == []


def test_sprite_missing_constructor_leaves_real_allocation_fully_zero_defined() -> None:
    h = Harness()
    calls = h.memory.runtime_calls()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        create_replay_base_saved_sprite(h.context, 0xBAD, calls=calls)
    allocated = h.memory.snapshot().regions[-1]
    assert allocated.data == bytes(32) and allocated.defined == b"\x01" * 32


def test_sprite_second16b_store_failure_keeps_first16_defined_without_constructor() -> None:
    h = Harness()
    address = h.memory.allocate(32)

    def allocate(target, args, data):
        assert target == ALLOCATE
        return address

    def fail(at, width, value):
        if at == address + 16:
            raise RuntimeError("second vector store")

    h.before_write = fail
    with pytest.raises(RuntimeError, match="second vector store"):
        create_replay_base_saved_sprite(h.context, 0xBAD, calls=ReplayTaskRebuildCalls(allocate))
    region = h.memory.snapshot().regions[-1]
    assert region.data[:16] == bytes(16)
    assert region.defined == b"\x01" * 16 + bytes(16)


def test_sprite_constructor_failure_retains_constructor_writes() -> None:
    h = Harness()

    def fail(target, args, data):
        assert target == CONSTRUCT
        h.memory.write(args[0] + 24, 8, 99)
        raise RuntimeError("constructor")

    h.on_call = fail
    with pytest.raises(RuntimeError, match="constructor"):
        h.invoke(SPRITE, 0xBAD)
    region = h.memory.snapshot().regions[-1]
    assert int.from_bytes(region.data[24:], "little") == 99


@pytest.mark.parametrize("service", [0, 0x8000000000000000, U64])
@pytest.mark.parametrize("bound", [False, True])
def test_notification_getter_and_tail_receive_raw_result_and_held_subject(service, bound) -> None:
    h = Harness()
    subject = h.subject()

    def call(target, args, data):
        if target == GET:
            assert args == ()
            h.memory.write(subject, 8, 0xBAD)
            return service
        assert target == SEND and args == (service, subject)
        return U64

    h.on_call = call
    result = (
        h.invoke(NOTIFY, subject)
        if bound
        else notify_replay_base_saved_object(h.context, subject, calls=h.calls)
    )
    assert result is None
    assert h.events == [("call", GET, (), None), ("call", SEND, (service, subject), None)]


@pytest.mark.parametrize("phase", ["getter", "tail"])
def test_notification_failure_retains_actual_prior_callback_writes(phase) -> None:
    h = Harness()
    subject = h.subject()

    def fail(target, args, data):
        h.memory.write(subject + (8 if target == GET else 16), 8, 77)
        if target == (GET if phase == "getter" else SEND):
            raise RuntimeError(phase)
        return 0x123

    h.on_call = fail
    with pytest.raises(RuntimeError, match=phase):
        h.invoke(NOTIFY, subject)
    assert h.memory.read(subject + 8, 8) == 77
    assert len(h.events) == (1 if phase == "getter" else 2)


@pytest.mark.parametrize(
    "target,args,data",
    [
        (SET, (), None),
        (SET, (1,), None),
        (SET, (1, 2, 3), None),
        (SPRITE, (), None),
        (NOTIFY, (1, 2), None),
        (SET, (True, 0), None),
        (SET, (1, -1), None),
        (SPRITE, (U64 + 1,), None),
        (NOTIFY, (1,), memoryview(bytearray())),
    ],
)
def test_known_binding_refuses_bad_shape_before_any_body_access(target, args, data) -> None:
    h = Harness()
    assert h.bound.call is not None
    with pytest.raises(ValueError):
        h.bound.call(target, args, data)
    assert h.events == []


def test_unknown_binding_delegates_original_live_view_and_raw_return() -> None:
    h = Harness()
    view = memoryview(bytearray(b"abc"))

    def call(target, args, data):
        assert target == 0xABC and args == (U64,) and data is view
        data[0] = 0xEE
        return U64

    h.on_call = call
    assert h.bound.call is not None
    assert h.bound.call(0xABC, (U64,), view) == U64
    assert view.tobytes() == b"\xeebc"


def test_unavailable_delegate_is_not_success_for_known_or_unknown_reached_work() -> None:
    h = Harness()
    bound = bind_replay_base_saved_support(h.context, ReplayTaskRebuildCalls(None))
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        bound.call(SPRITE, (0xBAD,), None)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        bound.call(NOTIFY, (0xBAD,), None)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        bound.call(0xABC, (), None)
    assert h.events == []
