"""Original-source batch controls with explicit authored serializer/clock children."""

import struct
from contextlib import contextmanager

import pytest

from vantage.replay_command_batch import ReplayCommandBatchProfile, bind_replay_command_batch
from vantage.replay_memory import ReplayMemory
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

ROW, VECTOR, LENGTH = 0x1402A8630, 0x140E0B2A0, 0x140E0B920
GETTER, SELECTOR, RESULT, CLOCK = 0x14098F250, 0x140942110, 0x14096B890, 0x140A71140
BEGIN, END, FREE, ALLOC = 0x140E08860, 0x140E07CC0, 0x142D6BAB4, 0x1402A94D0
COUNTER, MESSAGE, OUTPUT, COMPARE = 0x140973210, 0x140A08AE0, 0x1408FCD50, 0x142D6E3E7
WATSON, KEY, SERIALIZE, SEND = 0x765430, 0x765440, 0x765450, 0x765460
U64 = (1 << 64) - 1


def double(value):
    return int.from_bytes(struct.pack("<d", value), "little")


class Rig:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events, self.locals, self.active = [], [], []
        self.handlers, self.home_handlers = {}, {}
        self.after_read, self.after_write = None, None
        self.memory.map_bytes(0x14319A060, WATSON.to_bytes(8, "little"))
        self.memory.map_bytes(0x144287608, b"\0" * 8)
        self.memory.map_bytes(0x14428FA88, double(1).to_bytes(8, "little"))
        self.memory.map_bytes(0x1431FED08, double(1).to_bytes(8, "little"))

        def read(address, width):
            self.events.append(("read", address, width))
            value = self.memory.read(address, width)
            if self.after_read:
                self.after_read(address, width)
            return value

        def write(address, width, value):
            self.events.append(("write", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write:
                self.after_write(address, width, value)

        runtime = self.memory.runtime_calls()

        def call(target, args, data):
            self.events.append(("call", target, args))
            assert data is None
            if target in self.handlers:
                return self.handlers[target](args)
            if target == 0x1402BD7F0:
                return self.results.call(target, args, data)
            return runtime.call(target, args, data)

        def home(target, args, data):
            self.events.append(("home", target, args))
            assert data is None
            if target not in self.home_handlers:
                raise UnresolvedReplayTaskRebuild(f"authored HOME child {target:x} unavailable")
            return self.home_handlers[target](args)

        def atomic(address, delta):
            self.events.append(("atomic", address, delta))
            return self.memory.fetch_add_u32(address, delta)

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.calls, self.homes = ReplayTaskRebuildCalls(call), ReplayTaskRebuildCalls(home)
        self.atomics = ReplayUnitAIMapAtomics(None, atomic)
        self.results = bind_replay_saved_result(
            self.storage,
            self.calls,
            imports=self.calls,
            atomics=self.atomics,
        )
        self.profile = ReplayCommandBatchProfile(
            b"\xa5" * 0x28,
            b"\xb6" * 0x28,
            b"\xc7" * 0x50,
            b"\xd8" * 0xB0,
        )
        self.bound = bind_replay_command_batch(
            self.storage,
            self.calls,
            watson_home_calls=self.homes,
            error_home_calls=self.homes,
            atomics=self.atomics,
            bind_local=self.local,
            profile=self.profile,
            mxcsr=0x1F80,
        )

    def alloc(self, size, byte=0):
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([byte]) * size)
        return address

    def put(self, address, width, value):
        self.memory.write(address, width, value & ((1 << (width * 8)) - 1))

    def get(self, address, width=8):
        return self.memory.read(address, width)

    @contextmanager
    def local(self, view):
        with self.memory.bind_local(view) as address:
            self.locals.append((address, len(view), view))
            self.active.append(address)
            try:
                yield address
            finally:
                self.active.remove(address)

    def invoke(self, target, *args):
        return self.bound.call(target, args, None)

    def header(self, begin, end, cap, *, size=0x20):
        address = self.alloc(size, 0xE9)
        for offset, value in ((0, begin), (8, end), (16, cap)):
            self.put(address + offset, 8, value)
        return address

    def provider(self):
        tree, provider, vptr, descriptor = (self.alloc(n) for n in (0x50, 0x58, 0xF0, 0x20))
        node, sentinel = provider + 0x28, tree + 0x20
        self.put(tree + 8, 8, node)
        for offset, value in ((8, sentinel), (16, sentinel), (24, tree)):
            self.put(node + offset, 8, value)
        self.put(provider, 8, vptr)
        self.put(vptr + 8, 8, KEY)
        self.put(vptr + 0x18, 8, SERIALIZE)
        self.put(0x144287608, 8, tree)
        self.handlers[KEY] = lambda args: descriptor
        self.handlers[COMPARE] = lambda args: 0
        return tree, provider


@pytest.mark.parametrize("target", [ROW, VECTOR])
def test_null_vector_preserves_other_fields_and_skips_capacity(target):
    rig = Rig()
    header = rig.header(0, 0x12345678, 0x98765432)
    before = rig.memory.read_bytes(header, 32)
    assert rig.invoke(target, header) is None
    assert rig.memory.read_bytes(header, 32) == before
    assert rig.events == [("read", header, 8)]


def test_row_sized_free_and_clear_order_preserves_payload_and_padding():
    rig = Rig()
    data = rig.alloc(0x40, 0xFA)
    header = rig.header(data, data + 5, data + 0x40)
    assert rig.invoke(ROW, header) is None
    assert ("call", FREE, (data, 0x40)) in rig.events
    assert rig.memory.read_bytes(header, 32) == bytes(24) + b"\xe9" * 8
    assert rig.events[-3:] == [("write", header + i, 8, 0) for i in (0, 8, 16)]


@pytest.mark.parametrize("gap,valid", [(0, True), (31, True), (32, False), (-1, False)])
def test_row_aligned_backpointer_bounds_use_live_watson_home(gap, valid):
    rig = Rig()
    storage = rig.alloc(0x1100)
    data = storage + 64
    allocation = data - 8 - gap
    rig.put(data - 8, 8, allocation)
    header = rig.header(data, data + 5, data + 0x1000)
    rig.handlers[FREE] = lambda args: None

    def watson(args):
        assert args[:4] == (0, 0, 0, 0)
        assert rig.get(args[4]) == 0
        assert args[4] - 0x20 in rig.active

    rig.home_handlers[WATSON] = watson
    if valid:
        rig.invoke(ROW, header)
        assert ("call", FREE, (allocation, 0x1027)) in rig.events
        assert rig.get(header) == 0
    else:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="INT3"):
            rig.invoke(ROW, header)
        assert rig.get(header) == data
        assert not any(x[:2] == ("call", FREE) for x in rig.events)


def test_vector_holds_row_endpoints_then_rereads_current_outer_header():
    rig = Rig()
    rows, replacement = rig.alloc(64), rig.alloc(96)
    buffers = [rig.alloc(8), rig.alloc(16)]
    outer = rig.header(rows, rows + 64, rows + 64)
    for i, buffer in enumerate(buffers):
        for offset, value in ((0, buffer), (8, buffer + 1), (16, buffer + (8 << i))):
            rig.put(rows + i * 32 + offset, 8, value)
    frees = []

    def free(args):
        frees.append(args)
        if len(frees) == 1:
            rig.put(outer, 8, replacement)
            rig.put(outer + 8, 8, replacement)
            rig.put(outer + 16, 8, replacement + 95)

    rig.handlers[FREE] = free
    rig.invoke(VECTOR, outer)
    assert frees == [(buffers[0], 8), (buffers[1], 16), (replacement, 64)]
    assert rig.memory.read_bytes(outer, 24) == bytes(24)


def test_length_error_calls_actual_leaf_and_refuses_if_it_returns():
    rig = Rig()
    rig.handlers[0x142D66698] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="INT3"):
        rig.invoke(LENGTH)
    assert rig.events == [("call", 0x142D66698, (0x1436794B0,))]


def test_getter_is_current_and_argument_free():
    rig = Rig()
    assert rig.invoke(GETTER) == 0
    rig.put(0x144287608, 8, 0x1122334455667788)
    assert rig.invoke(GETTER) == 0x1122334455667788


def test_empty_selector_has_no_virtual_or_comparator_effect():
    rig = Rig()
    tree = rig.alloc(0x50)
    rig.put(tree + 8, 8, tree + 0x20)
    assert rig.invoke(SELECTOR, tree, 0xDEADBEEF) == 0
    assert rig.events == [("read", tree + 8, 8)]


def test_selector_actual_virtual_and_equality_predecessor_stop():
    rig = Rig()
    tree, provider = rig.provider()
    assert rig.invoke(SELECTOR, tree, 0x144121990) == provider
    assert [x[1] for x in rig.events if x[0] == "call"] == [KEY, COMPARE]


def test_selector_repeated_compare_uses_second_sign():
    rig = Rig()
    tree, provider = rig.provider()
    sentinel = tree + 0x20
    node, leaf = provider + 0x28, rig.alloc(0x58)
    leaf_node = leaf + 0x28
    rig.put(node + 8, 8, sentinel)
    rig.put(node + 16, 8, leaf_node)
    rig.put(leaf, 8, rig.get(provider))
    for offset, value in ((8, sentinel), (16, sentinel), (24, node)):
        rig.put(leaf_node + offset, 8, value)
    results = iter((1, 0xFFFFFFFF, 0, 1, 99))
    rig.handlers[COMPARE] = lambda args: next(results)
    assert rig.invoke(SELECTOR, tree, 0x144121990) == leaf
    assert len([x for x in rig.events if x[:2] == ("call", COMPARE)]) == 5


def test_result_status_zero_marks_processed_without_mapping_string_frame():
    rig = Rig()
    result = rig.alloc(48, 0xE9)
    rig.put(result + 0x18, 8, 0)
    assert rig.invoke(RESULT, result) is None
    assert rig.get(result + 0x28, 1) == 1
    assert rig.events == [("read", result + 0x18, 8), ("write", result + 0x28, 1, 1)]
    assert not rig.locals


@pytest.mark.parametrize("initial_cap,current_cap", [(15, 15), (16, 15), (15, 16), (16, 16)])
def test_result_sso_selection_and_current_cap_after_output(initial_cap, current_cap):
    rig = Rig()
    result, heap = rig.alloc(48, 0xE9), rig.alloc(32)
    rig.put(result + 0x18, 8, 1)
    frames, frees = [], []

    def message(args):
        assert args[0] == result
        frames.append(args[1])
        rig.put(args[1], 8, heap)
        rig.put(args[1] + 24, 8, initial_cap)

    def output(args):
        assert args == (heap if initial_cap > 15 else frames[0],)
        rig.put(frames[0] + 24, 8, current_cap)

    rig.handlers[MESSAGE], rig.handlers[OUTPUT] = message, output
    rig.handlers[FREE] = lambda args: frees.append(args)
    rig.invoke(RESULT, result)
    assert frees == ([(heap, 17)] if current_cap == 16 else [])
    assert rig.get(result + 0x28, 1) == 1
    assert rig.get(result + 0x18) == 1
    # CMOVA always reads its memory source, even for the inline string.
    selected = rig.events.index(("call", OUTPUT, (heap if initial_cap > 15 else frames[0],)))
    assert ("read", frames[0], 8) in rig.events[:selected]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, 0),
        ((1 << 53) + 1, 1 << 53),
        ((1 << 63) + 1, 1 << 63),
        (U64, 1 << 63),
    ],
)
def test_clock_unsigned_conversion_and_signed_indefinite(raw, expected):
    rig = Rig()
    rig.handlers[COUNTER] = lambda args: raw
    assert rig.invoke(CLOCK) == expected
    assert rig.events == [
        ("call", COUNTER, ()),
        ("read", 0x14428FA88, 8),
        ("read", 0x1431FED08, 8),
    ]


@pytest.mark.parametrize("factor", [double(float("inf")), 0x7FF8000000012345, double(-1)])
def test_clock_current_factor_and_nonfinite_truncation(factor):
    rig = Rig()

    def counter(args):
        rig.put(0x14428FA88, 8, factor)
        rig.put(0x1431FED08, 8, double(0.5))
        return 3

    rig.handlers[COUNTER] = counter
    expected = U64 if factor == double(-1) else 1 << 63
    assert rig.invoke(CLOCK) == expected


def test_begin_uses_real_row_cleanup_and_sets_flag_last():
    rig = Rig()
    owner, rows, data = rig.alloc(0x26C0), rig.alloc(32), rig.alloc(16)
    for offset, value in ((0, data), (8, data + 8), (16, data + 16)):
        rig.put(rows + offset, 8, value)
    for offset, value in ((0x26A0, rows), (0x26A8, rows + 32), (0x26B0, rows + 32)):
        rig.put(owner + offset, 8, value)
    rig.invoke(BEGIN, owner)
    assert ("call", FREE, (data, 16)) in rig.events
    assert rig.get(owner + 0x26A8) == rows
    assert rig.get(owner + 0x26B0) == rows + 32
    assert rig.events[-1] == ("write", owner + 0x26B8, 1, 1)


def test_empty_end_clears_flag_without_serializer_or_clock():
    rig = Rig()
    owner, rows = rig.alloc(0x26C0, 0xFA), rig.alloc(32)
    rig.put(owner + 0x26A0, 8, rows)
    rig.put(owner + 0x26A8, 8, rows)
    rig.invoke(END, owner)
    assert rig.get(owner + 0x26B8, 1) == 0
    assert not any(x[0] == "call" for x in rig.events)


def test_positive_batch_composes_selector_result_clock_and_nested_destruction():
    rig = Rig()
    owner, rows, source = rig.alloc(0x26C0), rig.alloc(32), rig.alloc(16)
    output, output_vptr, clock = rig.alloc(8), rig.alloc(0xF0), rig.alloc(0x58)
    _, provider = rig.provider()
    rig.put(output, 8, output_vptr)
    rig.put(output_vptr + 0xE8, 8, SEND)
    for address, value in (
        (owner + 0x2E8, output),
        (owner + 0x358, clock),
        (owner + 0x26A0, rows),
        (owner + 0x26A8, rows + 32),
        (owner + 0x26B0, rows + 32),
        (rows, source),
        (rows + 8, source + 3),
        (rows + 16, source + 16),
    ):
        rig.put(address, 8, value)
    rig.put(owner + 0x26B8, 1, 1)
    payload = rig.alloc(4)
    rig.memory.write_bytes(payload, b"aoe!")
    result_addresses, sent = [], []

    def serialize(args):
        assert args[0] == provider
        result, descriptor, record = args[1:]
        assert rig.get(record, 1) == 0x62
        assert rig.get(record + 8) == rows
        assert rig.get(owner + 0x26A0) == 0
        rig.memory.write_bytes(result, b"\xab" * 48)
        for offset in (0, 8, 16):
            rig.put(result + offset, 8, 0)
        rig.put(result + 0x18, 8, 0)
        rig.put(result + 0x20, 8, 0)
        result_addresses.append(result)
        for offset, value in ((16, payload), (24, payload + 4), (32, payload + 4)):
            rig.put(descriptor + offset, 8, value)

    def send(args):
        assert rig.get(result_addresses[0] + 0x28, 1) == 1
        assert args == (output, payload, 4)
        sent.append(rig.memory.read_bytes(args[1], args[2]))

    rig.handlers[SERIALIZE], rig.handlers[SEND] = serialize, send
    rig.handlers[COUNTER] = lambda args: 123
    rig.invoke(END, owner)
    assert sent == [b"aoe!"]
    assert rig.get(clock + 0x50, 4) == 123
    assert rig.get(owner + 0x26B8, 1) == 0
    assert rig.memory.read_bytes(owner + 0x26A0, 24) == bytes(24)
    assert not rig.active
    assert ("call", FREE, (source, 16)) in rig.events
    assert ("call", FREE, (rows, 32)) in rig.events
    assert ("call", FREE, (payload, 4)) in rig.events


@pytest.mark.parametrize(
    "target,args",
    [
        (ROW, ()),
        (VECTOR, ()),
        (LENGTH, (1,)),
        (GETTER, (1,)),
        (SELECTOR, (1,)),
        (RESULT, ()),
        (CLOCK, (1,)),
        (BEGIN, ()),
        (END, ()),
    ],
)
def test_owned_arities_fail_before_storage(target, args):
    rig = Rig()
    with pytest.raises(ValueError):
        rig.invoke(target, *args)
    assert not rig.events
