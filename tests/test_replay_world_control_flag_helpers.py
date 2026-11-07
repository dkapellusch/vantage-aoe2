"""Source-led controls for the complete322B/4B control-flag helpers."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_control_flag_helpers import (
    bind_replay_world_control_flag_helpers,
    read_replay_control_flag_dword,
)

ROW, GETTER, SETTER, VIRTUAL = 0x1416DFB20, 0x1413F7A00, 0x1412473E0, 0xA2F8
K1, K2 = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
SUB, ADD = 0x50A06BCECEBEF905, 0x5B32AA7995D95916
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
Handler = Callable[[tuple[int, ...]], int | None]


class Rig:
    def __init__(self) -> None:
        self.memory = ReplayMemory()
        self.events: list[tuple] = []
        self.after_read: Callable[[int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.virtual_handler: Handler | None = None
        self.setter_handler: Handler | None = None
        self.al: int | None = 1
        self.home = self.alloc(8, 0xA5)
        self.context = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.normal = ReplayTaskRebuildCalls(self.normal_call)
        self.virtual = ReplayTaskRebuildCalls(self.virtual_call)
        self.setter = ReplayTaskRebuildCalls(self.setter_call)
        self.bound = self.bind()

    def alloc(self, size: int, fill: int = 0) -> int:
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([fill]) * size)
        return address

    def put(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value & ((1 << (width * 8)) - 1))

    def get(self, address: int, width: int = 8) -> int:
        return self.memory.read(address, width)

    def read(self, address: int, width: int) -> int:
        self.events.append(("read", address, width))
        value = self.get(address, width)
        if self.after_read:
            self.after_read(address, width)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("write", address, width, value))
        self.put(address, width, value)
        if self.after_write:
            self.after_write(address, width, value)

    def normal_call(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        self.events.append(("normal", target, args, data))
        raise UnresolvedReplayTaskRebuild(f"authored normal child {target:x} unavailable")

    def virtual_call(
        self,
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
    ) -> int | None:
        assert data is None
        self.events.append(("virtual", target, args))
        return self.virtual_handler(args) if self.virtual_handler else self.al

    def setter_call(
        self,
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
    ) -> int | None:
        assert target == SETTER and data is None
        self.events.append(("setter", target, args))
        return self.setter_handler(args) if self.setter_handler else None

    def bind(
        self,
        *,
        home: int | None = None,
        virtual: ReplayTaskRebuildCalls | None = None,
        setter: ReplayTaskRebuildCalls | None = None,
    ) -> ReplayTaskRebuildCalls:
        return bind_replay_world_control_flag_helpers(
            self.context,
            self.normal,
            decode_home=self.home if home is None else home,
            virtual_calls=self.virtual if virtual is None else virtual,
            setter_calls=self.setter if setter is None else setter,
        )

    def invoke(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def calls(self, channel: str) -> list[tuple[int, tuple[int, ...]]]:
        return [(e[1], e[2]) for e in self.events if e[0] == channel]

    def unit(self, kind: int = 2) -> tuple[int, int, int]:
        unit, master, vptr = self.alloc(0x20), self.alloc(0x40), self.alloc(0x300)
        self.put(unit, 8, vptr)
        self.put(unit + 0x10, 8, master + K1 + K2)
        self.put(master + 0x38, 8, kind - ADD + SUB)
        self.put(vptr + 0x2F8, 8, VIRTUAL)
        return unit, master, vptr

    def members(self, units: tuple[int, ...], count: int | None = None) -> tuple[int, int, int]:
        receiver, header = self.alloc(0x40), self.alloc(0x18)
        array = self.alloc(max(1, len(units)) * 8)
        self.put(receiver + 0x30, 8, header)
        self.put(header + 8, 8, array)
        self.put(header + 0x10, 4, len(units) if count is None else count)
        for i, unit in enumerate(units):
            self.put(array + i * 8, 8, unit)
        return receiver, header, array


@pytest.mark.parametrize("word", [0, 1, 0x80000000, U32])
def test_getter_returns_full_current_zeroextended_dword_without_services(word: int) -> None:
    r = Rig()
    receiver = r.alloc(0x80)
    r.put(receiver + 0x7C, 4, word)
    r.bound = r.bind(
        home=0xDEAD0000, virtual=ReplayTaskRebuildCalls(None), setter=ReplayTaskRebuildCalls(None)
    )
    assert read_replay_control_flag_dword(r.context, receiver) == word
    assert r.invoke(GETTER, receiver) == word
    assert r.events == [("read", receiver + 0x7C, 4)] * 2


def test_getter_holds_read_value_and_wraps_receiver_address() -> None:
    r = Rig()
    r.memory.map_bytes(0xB, (0x80000001).to_bytes(4, "little"))

    def after(a: int, _n: int) -> None:
        if a == 0xB:
            r.put(a, 4, 2)

    r.after_read = after
    assert r.invoke(GETTER, U64 - 0x70) == 0x80000001
    assert r.events == [("read", 0xB, 4)]


def test_unknown_dispatch_preserves_target_tuple_data_and_result_identity() -> None:
    r = Rig()
    args, data, result = (-1, True, 1 << 90), memoryview(bytearray(b"x")), int("8" * 90)

    def normal(target: int, values: tuple[int, ...], view: memoryview | None) -> int:
        assert target == 0xDEAD and values is args and view is data
        return result

    bound = bind_replay_world_control_flag_helpers(
        r.context,
        ReplayTaskRebuildCalls(normal),
        decode_home=r.home,
        virtual_calls=r.virtual,
        setter_calls=r.setter,
    )
    assert bound.call is not None and bound.call(0xDEAD, args, data) is result
    assert r.events == []


@pytest.mark.parametrize("count", [0, U32, 0x80000000])
def test_nonpositive_count_returns_held_initial_header_without_home_or_children(count: int) -> None:
    r = Rig()
    receiver, header, _array = r.members((), count)
    changed = r.alloc(0x18)

    def after(a: int, _n: int) -> None:
        if a == header + 0x10:
            r.put(receiver + 0x30, 8, changed)
            r.put(header + 0x10, 4, 1)

    r.after_read = after
    r.bound = r.bind(
        home=0xDEAD0000, virtual=ReplayTaskRebuildCalls(None), setter=ReplayTaskRebuildCalls(None)
    )
    assert r.invoke(ROW, receiver, U64) == header
    assert r.events == [("read", receiver + 0x30, 8), ("read", header + 0x10, 4)]
    assert r.get(r.home) == 0xA5A5A5A5A5A5A5A5


@pytest.mark.parametrize("null_receiver", [True, False])
def test_null_receiver_or_member_keeps_actual_access_before_decode_home(
    null_receiver: bool,
) -> None:
    r = Rig()
    receiver, _header, _array = r.members((0,))
    with pytest.raises(ReplayMemoryError):
        r.invoke(ROW, 0 if null_receiver else receiver, 1)
    assert r.events[-1] == ("read", 0x30 if null_receiver else 0x10, 8)
    assert not any(e[0] == "write" for e in r.events)
    assert not r.calls("virtual") and not r.calls("setter")


@pytest.mark.parametrize("kind", [0, 1, 2, 3, 4, 19, 21, 22, 0x10002, 0xFFFFFFFF00000004])
def test_unsigned_low_word_mask_and_mandatory_fullzero_setter(kind: int) -> None:
    r = Rig()
    unit, _master, _vptr = r.unit(kind)
    receiver, header, _array = r.members((unit,))
    assert r.invoke(ROW, receiver, 0) == header
    admitted = kind & 0xFFFF in (2, 4, 19, 21)
    assert r.calls("setter") == ([(SETTER, (unit, 0, U64))] if admitted else [])
    assert not r.calls("virtual")
    assert r.get(r.home) == kind & U64


def test_all_six_decode_store_readbacks_and_bound_order_are_source_exact() -> None:
    r = Rig()
    unit, master, _vptr = r.unit()
    receiver, header, array = r.members((unit,))
    encoded_master = (master + K1 + K2) & U64
    encoded_word = (2 - ADD + SUB) & U64
    assert r.invoke(ROW, receiver, 0) == header
    expected = [
        ("read", receiver + 0x30, 8),
        ("read", header + 0x10, 4),
        ("read", header + 8, 8),
        ("read", array, 8),
        ("read", unit + 0x10, 8),
    ]
    for value in (encoded_master, (encoded_master - K1) & U64, master):
        expected += [("write", r.home, 8, value), ("read", r.home, 8)]
    expected += [("read", master + 0x38, 8)]
    for value in (encoded_word, (encoded_word - SUB) & U64, 2):
        expected += [("write", r.home, 8, value), ("read", r.home, 8)]
    expected += [
        ("setter", SETTER, (unit, 0, U64)),
        ("read", receiver + 0x30, 8),
        ("read", header + 0x10, 4),
    ]
    assert r.events == expected


@pytest.mark.parametrize("stage", [1, 6])
def test_decode_uses_current_home_after_stage_write_callbacks(stage: int) -> None:
    r = Rig()
    unit, _master, _vptr = r.unit(0)
    _other, other_master, _other_vptr = r.unit(2)
    receiver, header, _array = r.members((unit,))
    writes = 0

    def after(a: int, _n: int, _value: int) -> None:
        nonlocal writes
        if a == r.home:
            writes += 1
            if writes == stage:
                r.put(a, 8, other_master + K1 + K2 if stage == 1 else 4)

    r.after_write = after
    assert r.invoke(ROW, receiver, 0) == header
    assert r.calls("setter") == [(SETTER, (unit, 0, U64))]
    assert writes == 6 and r.get(r.home) == (2 if stage == 1 else 4)


@pytest.mark.parametrize("value", [0, 1, 0x100, 0x101, 255, U64, 0xAA00000000000000])
def test_input_only_dl_and_virtual_full_known_rdx_preparation(value: int) -> None:
    r = Rig()
    unit, _master, _vptr = r.unit()
    receiver, header, _array = r.members((unit,))
    assert r.invoke(ROW, receiver, value) == header
    active = bool(value & 255)
    assert r.calls("virtual") == ([(VIRTUAL, (unit, 0x50A06BCECEBEF901, U64))] if active else [])
    assert r.calls("setter") == [(SETTER, (unit, 1, 255) if active else (unit, 0, U64))]


@pytest.mark.parametrize("al", [0, 1, 2, 128, 255])
def test_virtual_entire_al_nonzero_and_setter_known_mask(al: int) -> None:
    r = Rig()
    unit, _master, _vptr = r.unit()
    receiver, header, _array = r.members((unit,))
    r.al = al
    assert r.invoke(ROW, receiver, 1) == header
    assert r.calls("setter") == [(SETTER, (unit, 1, 255) if al else (unit, 0, U64))]


def test_virtual_holds_vptr_but_reads_its_slot_at_call_point() -> None:
    r = Rig()
    unit, _master, vptr = r.unit()
    receiver, header, _array = r.members((unit,))
    other_vptr = r.alloc(0x300)
    r.put(other_vptr + 0x2F8, 8, 0xE2F8)

    def after(a: int, _n: int) -> None:
        if a == unit:
            r.put(unit, 8, other_vptr)
            r.put(vptr + 0x2F8, 8, 0xD2F8)

    r.after_read = after
    assert r.invoke(ROW, receiver, 1) == header
    assert r.calls("virtual") == [(0xD2F8, (unit, 0x50A06BCECEBEF901, U64))]


@pytest.mark.parametrize("ignored", [None, -1, 1 << 100, True])
def test_setter_result_is_opaque_and_actual_list_return_replaces_it(ignored: int | None) -> None:
    r = Rig()
    unit, _master, _vptr = r.unit()
    receiver, header, _array = r.members((unit,))
    r.setter_handler = lambda _a: ignored
    assert r.invoke(ROW, receiver, 0) == header


def test_current_headers_arrays_and_count_but_held_header_across_bound_callback() -> None:
    r = Rig()
    first, _m1, _v1 = r.unit()
    unused, _m2, _v2 = r.unit()
    last, _m3, _v3 = r.unit()
    receiver, initial, _a1 = r.members((first,))
    _r2, second, _a2 = r.members((0, unused), 2)
    _r3, final, _a3 = r.members((), 0)
    replacement = r.alloc(16)
    r.put(replacement + 8, 8, last)

    def setter(a: tuple[int, ...]) -> None:
        r.put(receiver + 0x30, 8, second if a[0] == first else final)

    r.setter_handler = setter

    def after(a: int, _n: int) -> None:
        if a == second + 0x10:
            r.put(receiver + 0x30, 8, final)
            r.put(second + 8, 8, replacement)
        elif a == final + 0x10:
            r.put(receiver + 0x30, 8, initial)

    r.after_read = after
    assert r.invoke(ROW, receiver, 0) == final
    assert r.get(receiver + 0x30) == initial
    assert r.calls("setter") == [(SETTER, (first, 0, U64)), (SETTER, (last, 0, U64))]
    assert ("read", second + 8, 8) in r.events and ("read", final + 8, 8) not in r.events
    assert r.events.count(("read", receiver + 0x30, 8)) == 3


def test_decode_home_is_callers_actual_shared_storage_address() -> None:
    r = Rig()
    caller_frame = r.alloc(0x80, 0xD5)
    unit, _master, _vptr = r.unit(4)
    receiver, header, _array = r.members((unit,))
    r.bound = r.bind(home=caller_frame)
    assert r.invoke(ROW, receiver, 0) == header
    assert r.get(caller_frame) == 4 and r.get(r.home) == 0xA5A5A5A5A5A5A5A5
    assert sum(e[0] == "write" and e[1] == caller_frame for e in r.events) == 6


def test_missing_decode_backing_refuses_after_member_load_at_first_source_store() -> None:
    r = Rig()
    unit, _master, _vptr = r.unit()
    receiver, _header, _array = r.members((unit,))
    r.bound = r.bind(home=0xDEAD0000)
    with pytest.raises(ReplayMemoryError):
        r.invoke(ROW, receiver, 0)
    assert r.events[-2] == ("read", unit + 0x10, 8)
    assert r.events[-1][0:3] == ("write", 0xDEAD0000, 8)
    assert not r.calls("setter") and not r.calls("virtual")


@pytest.mark.parametrize("missing,value", [("virtual", 1), ("setter", 0), ("setter", 1)])
def test_missing_reached_register_service_keeps_prior_decode_prefix(
    missing: str,
    value: int,
) -> None:
    r = Rig()
    unit, _master, _vptr = r.unit()
    receiver, _header, _array = r.members((unit,))
    r.bound = r.bind(**{missing: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.invoke(ROW, receiver, value)
    assert r.get(r.home) == 2
    assert r.events.count(("read", receiver + 0x30, 8)) == 1
    assert len(r.calls("virtual")) == int(missing == "setter" and bool(value))
    assert not r.calls("setter")


@pytest.mark.parametrize("al", [None, -1, 256, True])
def test_consumed_virtual_channel_returns_an_actual_al_byte_only(al: int | None) -> None:
    r = Rig()
    unit, _master, _vptr = r.unit()
    receiver, _header, _array = r.members((unit,))
    r.al = al
    with pytest.raises(ValueError):
        r.invoke(ROW, receiver, 1)
    assert len(r.calls("virtual")) == 1 and not r.calls("setter")
    assert r.events.count(("read", receiver + 0x30, 8)) == 1
