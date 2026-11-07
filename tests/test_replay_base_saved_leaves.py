"""Source-led owned controls; declared factories are explicit fixture effects."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_base_saved_leaves import (
    bind_replay_base_saved_leaves,
    classify_replay_base_saved_type,
    get_replay_base_saved_service,
    record_replay_base_saved_notification,
    release_replay_base_saved_pair_control,
    resize_replay_base_saved_name,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

GLOBAL, FACTORY, DELETE, GROW = 0x1444585E8, 0x141856260, 0x1418535F0, 0x1402BB420
TABLE, SELECTORS = 0x1410B94C4, 0x1410B94D0
U64 = (1 << 64) - 1
SELECTOR_RAW = bytes.fromhex(
    "0000000002020202020002020202020101010202020202020202020202020202"
    "02020202020202020202020202020202020202020202020200"
)


class Harness:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events, self.frames, self.finished = [], [], []
        self.providers = {}
        self.on_write = lambda address, width, value: None
        self.context = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.call)
        self.atomics = ReplayUnitAIMapAtomics(
            self.memory.compare_exchange_u32, self.memory.fetch_add_u32
        )
        self.bound = bind_replay_base_saved_leaves(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=b"\xa3" * 8,
        )

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("read", address, width, value))
        return value

    def write(self, address, width, value):
        self.events.append(("write", address, width, value))
        self.memory.write(address, width, value)
        self.on_write(address, width, value)

    def call(self, target, args, data):
        self.events.append(("call", target, args, data))
        if target not in self.providers:
            raise UnresolvedReplayTaskRebuild(f"unknown test child{target:x}")
        return self.providers[target](args, data)

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.frames.append((address, view))
            try:
                yield address
            finally:
                self.finished.append(view.tobytes())

    def block(self, size, fill=None):
        at = self.memory.allocate(size)
        if fill is not None:
            self.memory.write_bytes(at, bytes([fill]) * size)
        return at

    def invoke(self, target, *args):
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def service(self, value):
        self.memory.map_bytes(GLOBAL, value.to_bytes(8, "little"))


@pytest.mark.parametrize("requested", [0, 3, 7])
@pytest.mark.parametrize("heap", [False, True])
def test_name_shrink_equal_length_terminator_and_guard_bytes(requested, heap):
    h = Harness()
    name, buffer = h.block(40, 0xA3), h.block(16, 0xD4)
    h.memory.write(name + 16, 8, 7)
    h.memory.write(name + 24, 8, 16 if heap else 15)
    if heap:
        h.memory.write(name, 8, buffer)
    before = h.memory.read_bytes(name, 40)
    h.invoke(0x1402BB570, name, requested, U64)
    expected = bytearray(before)
    expected[16:24] = requested.to_bytes(8, "little")
    if not heap:
        expected[requested] = 0
    assert h.memory.read_bytes(name, 40) == bytes(expected)
    assert h.memory.read_bytes(buffer, 16) == (
        b"\xd4" * requested + b"\0" + b"\xd4" * (15 - requested) if heap else b"\xd4" * 16
    )
    assert not any(event[0] == "call" for event in h.events)


def test_name_buffer_choice_uses_current_capacity_after_length_store():
    h = Harness()
    name, buffer = h.block(32, 0xA3), h.block(8, 0xD4)
    h.memory.write(name + 16, 8, 9)
    h.memory.write(name + 24, 8, 15)

    def change(address, width, value):
        if address == name + 16:
            h.memory.write(name, 8, buffer)
            h.memory.write(name + 24, 8, 16)

    h.on_write = change
    resize_replay_base_saved_name(h.context, name, 3, 0, calls=h.calls)
    assert h.memory.read_bytes(buffer, 8) == b"\xd4\xd4\xd4\0" + b"\xd4" * 4


def test_name_growth_requires_actual_child_before_length_or_capacity_reads():
    h = Harness()
    name = h.block(24)  # capacity unmapped; only held old length is read.
    h.memory.write(name + 16, 8, 5)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402bb420"):
        h.invoke(0x1402BB570, name, 12, U64)
    assert h.memory.read(name + 16, 8) == 5
    assert h.events == [("read", name + 16, 8, 5), ("call", GROW, (name, 7, U64), None)]


def test_name_terminator_failure_retains_new_length():
    h = Harness()
    name = h.block(32)
    for offset, value in ((0, 0), (16, 5), (24, 16)):
        h.memory.write(name + offset, 8, value)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.invoke(0x1402BB570, name, 2, 0)
    assert h.memory.read(name + 16, 8) == 2


@pytest.mark.parametrize(
    "category,expected",
    [
        (0, 0),
        (3, 3),
        (4, 0xFFFFFFFF),
        (9, 9),
        (14, 0xFFFFFFFF),
        (15, 0),
        (16, 0),
        (17, 0),
        (18, 0xFFFFFFFF),
        (56, 56),
        (57, 0xFFFFFFFF),
        (0x80000000, 0xFFFFFFFF),
        (U64, 0xFFFFFFFF),
        (0x100000038, 56),
    ],
)
def test_classifier_real_static_tables_unsigned_low_word(category, expected):
    h = Harness()
    assert len(SELECTOR_RAW) == 57
    h.memory.map_bytes(TABLE, bytes.fromhex("b8940b01b5940b01bb940b01"))
    h.memory.map_bytes(SELECTORS, SELECTOR_RAW)
    assert h.invoke(0x1410B9490, category) == expected
    assert len(h.events) == (0 if category & 0xFFFFFFFF > 56 else 2)


def test_classifier_reload_current_selector_and_unknown_case_refusal():
    h = Harness()
    h.memory.map_bytes(SELECTORS, b"\x01")
    h.memory.map_bytes(TABLE + 4, (0x10B94B8).to_bytes(4, "little"))
    assert classify_replay_base_saved_type(h.context, 0) == 0
    h.memory.write(TABLE + 4, 4, 0xABCDE)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unadmitted"):
        classify_replay_base_saved_type(h.context, 0)


def test_pair_null_control_does_not_read_status_or_require_atomic_effect():
    h = Harness()
    pair = h.block(16)
    h.memory.write(pair + 8, 8, 0)
    release_replay_base_saved_pair_control(
        h.context,
        pair,
        calls=ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
    )
    assert h.events == [("read", pair + 8, 8, 0)]


@pytest.mark.parametrize(
    "strong,weak,calls", [(1, 1, [0xCA1, 0xCA3]), (2, 1, []), (0, 1, []), (1, 2, [0xCA1])]
)
def test_pair_real_atomics_and_refreshed_dispose_target(strong, weak, calls):
    h = Harness()
    pair, control, table, replacement = (h.block(16) for _ in range(4))
    for address, width, value in (
        (pair + 8, 8, control),
        (control, 8, table),
        (control + 8, 4, strong),
        (control + 12, 4, weak),
        (table, 8, 0xCA1),
        (table + 8, 8, 0xCA2),
        (replacement + 8, 8, 0xCA3),
    ):
        h.memory.write(address, width, value)

    def destroy(args, data):
        assert args == (control,) and data is None
        h.memory.write(control, 8, replacement)
        h.memory.write(pair + 8, 8, 0)

    h.providers[0xCA1] = destroy
    h.providers[0xCA3] = lambda args, data: None
    h.invoke(0x1408EE150, pair)
    assert [e[1] for e in h.events if e[0] == "call"] == calls
    assert h.memory.read(control + 8, 4) == (strong - 1) & 0xFFFFFFFF
    assert h.memory.read(control + 12, 4) == (weak - 1 if strong == 1 else weak)


@pytest.mark.parametrize("value", [1, 0x8000000000000000, U64])
def test_service_fast_path_reads_only_current_global(value):
    h = Harness()
    h.service(value)
    assert h.invoke(0x14185B6D0) == value
    assert h.frames == [] and h.events == [("read", GLOBAL, 8, value)]


def test_service_null_requires_factory_without_inventing_current_singleton():
    h = Harness()
    h.service(0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141856260"):
        h.invoke(0x14185B6D0)
    assert h.memory.read(GLOBAL, 8) == 0
    assert h.finished == [b"\xa3" * 8]


def test_service_factory_return_carrier_and_two_current_cleanup_reloads():
    h = Harness()
    h.service(0)
    carrier = h.block(8)
    seen = []

    def factory(args, data):
        local = args[0]
        assert data is None and h.memory.read(local, 8) == 0xA3A3A3A3A3A3A3A3
        h.memory.write(local, 8, 0x111)
        h.memory.write(carrier, 8, 0x222)
        h.memory.write(GLOBAL, 8, 0x333)
        return carrier

    def delete(args, data):
        seen.append(args)
        assert data is None
        h.memory.write(GLOBAL, 8, 0x444 if args[0] == GLOBAL else 0x555)

    h.providers.update({FACTORY: factory, DELETE: delete})
    assert h.invoke(0x14185B6D0) == 0x555
    assert seen == [(GLOBAL, 0x333), (h.frames[0][0], 0x111)]
    assert h.memory.read(carrier, 8) == 0
    assert h.finished == [(0x111).to_bytes(8, "little")]


def test_service_held_return_not_reloaded_after_plain_global_store():
    h = Harness()
    h.service(0)

    def factory(args, data):
        h.memory.write(args[0], 8, 0x222)
        return args[0]

    def mutate(address, width, value):
        if address == GLOBAL:
            h.memory.write(GLOBAL, 8, 0x333)

    h.providers[FACTORY] = factory
    h.on_write = mutate
    assert h.invoke(0x14185B6D0) == 0x222
    assert h.memory.read(GLOBAL, 8) == 0x333
    assert h.finished == [bytes(8)]


def test_service_global_cleanup_can_clear_local_before_its_current_gate():
    h = Harness()
    h.service(0)
    carrier = h.block(8)

    def factory(args, data):
        h.memory.write(GLOBAL, 8, 0x111)
        h.memory.write(args[0], 8, 0x222)
        h.memory.write(carrier, 8, 0x333)
        return carrier

    def delete(args, data):
        h.memory.write(h.frames[0][0], 8, 0)

    h.providers.update({FACTORY: factory, DELETE: delete})
    assert h.invoke(0x14185B6D0) == 0x333
    assert len([e for e in h.events if e[0] == "call" and e[1] == DELETE]) == 1


def test_service_missing_destructor_keeps_published_value_and_cleared_carrier():
    h = Harness()
    h.service(0)

    def factory(args, data):
        h.memory.write(args[0], 8, 0x222)
        h.memory.write(GLOBAL, 8, 0x111)
        return args[0]

    h.providers[FACTORY] = factory
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1418535f0"):
        h.invoke(0x14185B6D0)
    assert h.memory.read(GLOBAL, 8) == 0x222 and h.finished == [bytes(8)]


@pytest.mark.parametrize(
    "identifier,counter,expected",
    [
        (7, None, 7),
        (0x7FFFFFFF, None, 0x7FFFFFFF),
        (0, 0, 0xFFFFFFFF),
        (0x80000000, 0x80000000, 0x7FFFFFFF),
        (0xFFFFFFFF, 3, 2),
    ],
)
def test_notification_signed_id_and_wrapping_current_counter(identifier, counter, expected):
    h = Harness()
    service, subject = h.block(0x2D0), h.block(0x300, 0xA3)
    h.memory.write(service + 0x1A1, 1, 0)
    h.memory.write(subject + 8, 4, identifier)
    if counter is not None:
        h.memory.write(service + 0x2CC, 4, counter)
    h.invoke(0x14185CE10, service, subject)
    assert h.memory.read(subject + 0x2F0, 4) == expected
    assert h.memory.read_bytes(subject + 0x2F4, 12) == b"\xa3" * 12


def test_notification_active_gate_skips_all_subject_and_counter_accesses():
    h = Harness()
    service = h.block(0x1A2)
    h.memory.write(service + 0x1A1, 1, 255)
    record_replay_base_saved_notification(h.context, service, U64)
    assert h.events == [("read", service + 0x1A1, 1, 255)]


def test_notification_rereads_counter_after_decrement():
    h = Harness()
    service, subject = h.block(0x2D0), h.block(0x300)
    for at, width, value in ((service + 0x1A1, 1, 0), (subject + 8, 4, 0), (service + 0x2CC, 4, 8)):
        h.memory.write(at, width, value)

    def mutate(address, width, value):
        if address == service + 0x2CC:
            h.memory.write(address, 4, 99)

    h.on_write = mutate
    record_replay_base_saved_notification(h.context, service, subject)
    assert h.memory.read(subject + 0x2F0, 4) == 99


def test_notification_output_failure_retains_counter_decrement():
    h = Harness()
    service, subject = h.block(0x2D0), h.block(12)
    for at, width, value in ((service + 0x1A1, 1, 0), (subject + 8, 4, 0), (service + 0x2CC, 4, 8)):
        h.memory.write(at, width, value)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        record_replay_base_saved_notification(h.context, service, subject)
    assert h.memory.read(service + 0x2CC, 4) == 7


@pytest.mark.parametrize(
    "entry,args",
    [
        (0x1402BB570, (1, 2)),
        (0x1408EE150, ()),
        (0x1410B9490, (1, 2)),
        (0x14185B6D0, (1,)),
        (0x14185CE10, (1,)),
    ],
)
def test_bound_entry_arity_refuses_before_effects(entry, args):
    h = Harness()
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(entry, args, None)
    assert h.events == []


def test_service_invalid_seed_refuses_before_read_and_unknown_binder_preserves_view():
    h = Harness()
    with pytest.raises(ValueError, match="explicit8-byte"):
        get_replay_base_saved_service(
            h.context, calls=h.calls, bind_local=h.bind_local, scratch=bytes(7)
        )
    assert h.events == []
    view = memoryview(bytearray(b"input"))
    h.providers[0xABC] = lambda args, data: U64 if data is view and args == (3,) else 0
    assert h.bound.call(0xABC, (3,), view) == U64
