"""Retained native RNG outputs and source-led addressed mutation/log controls."""

from __future__ import annotations

import gzip
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_random_registry_storage import (
    ReplayRandomRegistryStorageProfile,
    bind_replay_random_registry_storage,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

REGISTRY, SEED, DRAW = 0x140FDDBF0, 0x140903F20, 0x140903AF0
ENGINE, LOGGER, FORMAT = 0x140904060, 0x140902830, 0x14101ADB0
BASE, COUNT = 0x143DB0AB0, 0x143DB0AC0
ENABLE, SECONDARY, LOG = 0x14435505E, 0x14427C9B0, 0x144355068
HEADER, SEED_FORMAT, DRAW_FORMAT = 0x1431F50C0, 0x1431F50D8, 0x1431F5100
YES, NO = 0x1431F50BC, 0x14368B9D4
SCRATCH = bytes((13 * i + 7) & 255 for i in range(0x90))
FIXTURES = Path(__file__).parent / "fixtures"


def native_rows(operation):
    raw = (FIXTURES / "native_replay_random_54800.json.gz").read_bytes()
    return [
        (inputs, expected)
        for inputs, expected in json.loads(gzip.decompress(raw))
        if inputs[0] == operation
    ]


class Rig:
    def __init__(self, *, maximum=64):
        self.memory = ReplayMemory()
        self.events, self.read_values, self.frames, self.exit_bytes = [], [], [], []
        self.on_read, self.on_write, self.formatter = None, None, None
        self.globals = set()
        self.set_global(BASE, 8, 0)
        self.set_global(COUNT, 8, 0)
        self.stream = self.new_stream()

        def read(address, width):
            self.events.append(("read", address, width))
            value = self.memory.read(address, width)
            self.read_values.append((address, width, value))
            if self.on_read is not None:
                self.on_read(address, width, value)
            return value

        def write(address, width, value):
            self.events.append(("write", address, width, value))
            self.memory.write(address, width, value)
            if self.on_write is not None:
                self.on_write(address, width, value)

        def call(target, args, data):
            self.events.append(("call", target, args, data))
            if target != FORMAT or self.formatter is None:
                raise UnresolvedReplayTaskRebuild(f"actual test provider{target:x} unavailable")
            return self.formatter(args, data)

        @contextmanager
        def local(view):
            with self.memory.bind_local(view) as address:
                self.frames.append(address)
                self.events.append(("local-enter", address))
                try:
                    yield address
                finally:
                    self.exit_bytes.append((address, bytes(view)))
                    self.events.append(("local-exit", address))

        self.binding = bind_replay_random_registry_storage(
            ReplayTaskRebuildStorage(0xABCDEF, read, write),
            ReplayTaskRebuildCalls(call),
            profile=ReplayRandomRegistryStorageProfile(maximum, SCRATCH),
            bind_local=local,
        )

    def set_global(self, address, width, value):
        if address in self.globals:
            self.memory.write(address, width, value)
        else:
            self.memory.map_bytes(address, value.to_bytes(width, "little"))
            self.globals.add(address)

    def new_stream(self, *, words=None, index=0, calls=0, last=0xAABBCCDD):
        stream = self.memory.allocate(0x90)
        self.memory.write(stream + 0x20, 1, 0)
        self.set_state(stream, list(range(16)) if words is None else words, index, calls, last)
        return stream

    def set_state(self, stream, words, index, calls, last):
        for offset, value in [(0x18, calls), (0x88, last), (0x64, index)]:
            self.memory.write(stream + offset, 4, value)
        for i, word in enumerate(words):
            self.memory.write(stream + 0x24 + 4 * i, 4, word)

    def state(self, stream):
        return [
            self.memory.read(stream + offset, 4)
            for offset in (0x18, 0x88, 0x64, *range(0x24, 0x64, 4))
        ]

    def registry(self, streams):
        base = self.memory.allocate(max(1, len(streams)) * 8)
        for i, stream in enumerate(streams):
            self.memory.write(base + i * 8, 8, stream)
        self.set_global(BASE, 8, base)
        self.set_global(COUNT, 8, len(streams))
        return base

    def logging(self, *, secondary=1, enabled=1, name=0x1111222233334444):
        self.memory.write(self.stream, 8, name)
        self.memory.write(self.stream + 0x20, 1, 1)
        self.set_global(ENABLE, 1, enabled)
        self.set_global(SECONDARY, 1, secondary)
        self.set_global(LOG, 8, 0xCC00)

    def run(self, target, *args):
        return self.binding.call(target, args, None)

    def source_events(self):
        return [e for e in self.events if e[0] in ("read", "write", "call")]


@pytest.mark.parametrize("target", [ENGINE, SEED])
def test_all_256_retained_native_seed_outputs_through_both_owned_entries(target):
    rows = native_rows(0)
    assert len(rows) == 256
    for inputs, expected in rows:
        _, value, calls, last, index, *words = inputs
        rig = Rig()
        rig.set_state(rig.stream, words, index, calls, last)
        args = (rig.stream + 0x24, value) if target == ENGINE else (rig.stream, value, 0, 0)
        assert rig.run(target, *args) is None
        assert [0, *rig.state(rig.stream)] == expected
        assert not rig.frames


def test_all_3712_retained_native_full_word_draw_outputs():
    rows = native_rows(2)
    assert len(rows) == 3712
    for inputs, expected in rows:
        _, _, calls, last, index, *words = inputs
        rig = Rig()
        rig.set_state(rig.stream, words, index, calls, last)
        value = rig.run(DRAW, rig.stream, 0, 0)
        assert [value, *rig.state(rig.stream)] == expected
        assert not any(e[0] == "write" and e[1] == rig.stream + 0x88 for e in rig.events)


def decode_registry(words):
    cursor, result = 1, []
    for _ in range(words[0]):
        present = words[cursor]
        cursor += 1
        if not present:
            result.append(None)
            continue
        state, depth = words[cursor : cursor + 19], words[cursor + 19]
        cursor += 20
        stack = words[cursor : cursor + 17 * depth]
        cursor += len(stack)
        result.append((state, stack))
    assert cursor == len(words)
    return result


def test_all_33_retained_native_registry_seed_operations_preserve_checkpoint_backing():
    raw = (FIXTURES / "native_replay_random_registry_54800.json.gz").read_bytes()
    cases = [case for case in json.loads(gzip.decompress(raw))["cases"] if case["op"] == 0]
    assert len(cases) == 33
    for case in cases:
        before, after = decode_registry(case["before"]), decode_registry(case["after"])
        rig, streams, collateral = Rig(), [], []
        for item in before:
            if item is None:
                streams.append(0)
                collateral.append(None)
                continue
            state, stack = item
            calls, last, index, *words = state
            stream = rig.new_stream(words=words, calls=calls, last=last, index=index)
            # This five-body family never accesses the checkpoint area.
            marker = bytes(range(0x68, 0x88))
            for i, value in enumerate(marker):
                rig.memory.write(stream + 0x68 + i, 1, value)
            stack_bytes = b"".join(v.to_bytes(4, "little") for v in stack)
            address = rig.memory.allocate(len(stack_bytes)) if stack_bytes else None
            if address is not None:
                for i, value in enumerate(stack_bytes):
                    rig.memory.write(address + i, 1, value)
            streams.append(stream)
            collateral.append((marker, address, stack_bytes))
        rig.registry(streams)
        assert rig.run(REGISTRY, case["seed"]) is None
        for i, (stream, expected) in enumerate(zip(streams, after, strict=True)):
            if not stream:
                assert expected is None
                continue
            state, stack = expected
            assert rig.state(stream) == state
            assert stack == before[i][1]
            marker, address, stack_bytes = collateral[i]
            assert bytes(rig.memory.read(stream + 0x68 + j, 1) for j in range(32)) == marker
            if address is not None:
                assert bytes(rig.memory.read(address + j, 1) for j in range(len(stack_bytes))) == (
                    stack_bytes
                )


def test_engine_reads_no_old_storage_and_publishes_sixteen_scalars_then_index_last():
    memory, events = ReplayMemory(), []
    address = memory.allocate(0x44)
    expected = native_rows(0)[0][1][4:]

    def read(at, width):
        pytest.fail("engine seed must not read old storage")

    def write(at, width, value):
        events.append((at, width, value))
        memory.write(at, width, value)

    binding = bind_replay_random_registry_storage(
        ReplayTaskRebuildStorage(1, read, write),
        ReplayTaskRebuildCalls(None),
        profile=ReplayRandomRegistryStorageProfile(0, SCRATCH),
        bind_local=memory.bind_local,
    )
    assert binding.call(ENGINE, (address, 0xAABBCCDD00000000), None) is None
    assert events == [(address + 4 * i, 4, word) for i, word in enumerate(expected)] + [
        (address + 0x40, 4, 0)
    ]


def test_engine_failure_retains_exact_published_prefix_without_touching_old_index():
    rig = Rig()
    engine = rig.memory.allocate(0x44)
    rig.memory.write(engine + 0x40, 4, 123)
    expected = native_rows(0)[0][1][4:]

    def write(at, width, value):
        if at == engine + 8:
            raise RuntimeError("actual third store failed after effect")

    rig.on_write = write
    with pytest.raises(RuntimeError, match="third store"):
        rig.run(ENGINE, engine, 0)
    assert [rig.memory.read(engine + 4 * i, 4) for i in range(3)] == expected[:3]
    assert rig.memory.read(engine + 0x40, 4) == 123
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(engine + 12, 4)


@pytest.mark.parametrize("target", [SEED, LOGGER])
def test_disabled_stream_reads_no_globals_name_or_logical_frame(target):
    rig = Rig()
    args = (rig.stream, 0, 0, 0)
    rig.run(target, *args)
    reads = [e for e in rig.events if e[0] == "read"]
    assert reads == [("read", rig.stream + 0x20, 1)]
    assert not rig.frames


@pytest.mark.parametrize("target", [SEED, LOGGER])
def test_enable_zero_has_distinct_seed_and_full_logger_gate_read_order(target):
    rig = Rig()
    rig.logging(enabled=0)
    rig.run(target, rig.stream, 0, 0, 0)
    expected = [("read", rig.stream + 0x20, 1), ("read", ENABLE, 1)]
    if target == LOGGER:
        expected.append(("read", SECONDARY, 1))
    assert [e for e in rig.events if e[0] == "read"] == expected
    assert not rig.frames


def expected_frame(frame, *, name, label, line, secondary):
    raw = bytearray(SCRATCH)
    words = [
        (0x20, 8, frame + 0x70),
        (0x30, 4, line),
        (0x38, 4, 2),
        (0x40, 8, name),
        (0x48, 4, 15),
        (0x50, 8, label),
        (0x58, 4, 15),
        (0x60, 8, YES if secondary else NO),
        (0x68, 4, 15),
        (0x70, 8, frame + 0x60),
        (0x78, 8, frame + 0x40),
        (0x80, 8, frame + 0x50),
        (0x88, 8, frame + 0x30),
    ]
    for offset, width, value in words:
        raw[offset : offset + width] = value.to_bytes(width, "little")
    return raw


@pytest.mark.parametrize("target", [SEED, LOGGER])
@pytest.mark.parametrize("secondary", [0, 255])
def test_enabled_logging_exact_aliased_descriptors_and_partial_padding(target, secondary):
    rig = Rig()
    rig.logging(secondary=secondary)
    label, line, captured = 0x1234567890, 0x23, []
    value = 0 if target == SEED else 0xFEDCBA98

    def formatter(args, data):
        frame = rig.frames[-1]
        assert data is None
        captured.append((args, bytes(rig.memory.read(frame + i, 1) for i in range(0x90))))

    rig.formatter = formatter
    assert (
        rig.run(target, rig.stream, (0xAABBCCDD << 32) | value, label, (0xAABBCCDD << 32) | line)
        is None
    )
    frame = rig.frames[0]
    first = expected_frame(
        frame, name=0x1111222233334444, label=label, line=line, secondary=secondary
    )
    assert captured[0] == ((0xCC00, 0x26, HEADER, 4, frame + 0x70), bytes(first))
    second = bytearray(first)
    for offset, width, word in [
        (0x60, 8, frame + 0x30),
        (0x38, 4, 7),
        (0x20, 8, frame + 0x60),
        (0x30, 4, value),
    ]:
        second[offset : offset + width] = word.to_bytes(width, "little")
    fmt = SEED_FORMAT if target == SEED else DRAW_FORMAT
    assert captured[1] == ((0xCC00, 0x26, fmt, 1, frame + 0x60), bytes(second))
    assert len(captured) == 2
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(frame, 1)


@pytest.mark.parametrize("target", [SEED, LOGGER])
def test_header_store_read_order_matches_native_seed_vs_logger_difference(target):
    rig = Rig()
    rig.logging()
    rig.formatter = lambda args, data: None
    rig.run(target, rig.stream, 0, 0xABCD, 0x23)
    f = rig.frames[0]
    prefix = [("read", rig.stream + 0x20, 1), ("read", ENABLE, 1)]
    prefix += (
        [("read", rig.stream, 8), ("read", SECONDARY, 1)]
        if target == SEED
        else [("read", SECONDARY, 1), ("read", rig.stream, 8)]
    )
    prefix += [
        ("write", f + 0x48, 4, 15),
        ("write", f + 0x40, 8, 0x1111222233334444),
        ("write", f + 0x68, 4, 15),
    ]
    if target == LOGGER:
        prefix.append(("write", f + 0x38, 4, 2))
    prefix += [
        ("read", LOG, 8),
        ("write", f + 0x60, 8, YES),
        ("write", f + 0x70, 8, f + 0x60),
        ("write", f + 0x78, 8, f + 0x40),
        ("write", f + 0x80, 8, f + 0x50),
        ("write", f + 0x88, 8, f + 0x30),
    ]
    if target == SEED:
        prefix.append(("write", f + 0x38, 4, 2))
    prefix += [
        ("write", f + 0x58, 4, 15),
        ("write", f + 0x30, 4, 0x23),
        ("write", f + 0x50, 8, 0xABCD),
        ("write", f + 0x20, 8, f + 0x70),
        ("call", FORMAT, (0xCC00, 0x26, HEADER, 4, f + 0x70), None),
    ]
    assert rig.source_events()[: len(prefix)] == prefix


@pytest.mark.parametrize(("target", "expected_logger"), [(SEED, 0xCC00), (LOGGER, 0xDD00)])
def test_type38_store_changes_only_the_native_current_logger_read(target, expected_logger):
    rig = Rig()
    rig.logging()
    seen = []

    def write(at, width, value):
        if rig.frames and at == rig.frames[-1] + 0x38 and value == 2:
            rig.memory.write(LOG, 8, 0xDD00)

    rig.on_write = write
    rig.formatter = lambda args, data: seen.append(args)
    rig.run(target, rig.stream, 0, 0, 0)
    assert [args[0] for args in seen] == [expected_logger, 0xDD00]


@pytest.mark.parametrize("target", [SEED, LOGGER])
def test_formatter_mutations_persist_in_shared_frame_and_second_gate_and_logger_are_fresh(target):
    rig = Rig()
    rig.logging()
    seen = []

    def formatter(args, data):
        frame = rig.frames[-1]
        seen.append(args)
        if len(seen) == 1:
            rig.memory.write(LOG, 8, 0xEE00)
            rig.memory.write(frame + 0x3C, 4, 0xDEADBEEF)
            rig.memory.write(frame + 0x30, 4, 1234)
            rig.memory.write(rig.stream, 8, 0x9999)
            rig.memory.write(SECONDARY, 1, 0)
        else:
            assert args[0] == 0xEE00
            assert rig.memory.read(frame + 0x30, 4) == 7
            assert rig.memory.read(frame + 0x3C, 4) == 0xDEADBEEF
            assert rig.memory.read(frame + 0x40, 8) == 0x1111222233334444
            assert rig.memory.read(frame + 0x70, 8) == frame + 0x60
            assert rig.memory.read(frame + 0x60, 8) == frame + 0x30

    rig.formatter = formatter
    rig.run(target, rig.stream, 7, 0, 0)
    assert len(seen) == 2


@pytest.mark.parametrize("target", [SEED, LOGGER])
def test_formatter_can_disable_only_the_second_call_without_skipping_seed_engine(target):
    rig = Rig()
    rig.logging()
    seen = []

    def formatter(args, data):
        seen.append(args)
        rig.memory.write(ENABLE, 1, 0)

    rig.formatter = formatter
    old = rig.state(rig.stream)
    rig.run(target, rig.stream, 0, 0, 0)
    assert len(seen) == 1
    if target == SEED:
        assert rig.state(rig.stream)[3:] == native_rows(0)[0][1][4:]
    else:
        assert rig.state(rig.stream) == old


def test_seed_logging_frame_remains_live_during_engine_stores_then_expires():
    rig = Rig()
    rig.logging()
    checked = []
    rig.formatter = lambda args, data: None

    def write(at, width, value):
        if rig.stream + 0x24 <= at <= rig.stream + 0x64:
            frame = rig.frames[-1]
            assert rig.memory.read(frame + 0x30, 4) == 42
            checked.append(at)

    rig.on_write = write
    rig.run(SEED, rig.stream, 42, 0, 0)
    assert checked == [rig.stream + i for i in range(0x24, 0x68, 4)]
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(rig.frames[0] + 0x30, 4)


def test_full_draw_holds_native_return_across_logger_mutation_without_overwriting88():
    inputs, expected = native_rows(2)[0]
    _, _, calls, last, index, *words = inputs
    rig = Rig()
    rig.set_state(rig.stream, words, index, calls, last)
    rig.logging()

    def formatter(args, data):
        rig.memory.write(rig.stream + 0x88, 4, 0x12345678)
        rig.memory.write(rig.stream + 0x18, 4, 999)
        rig.memory.write(rig.stream + 0x64, 4, 2)
        rig.memory.write(rig.stream + 0x2C, 4, 123)

    rig.formatter = formatter
    assert rig.run(DRAW, rig.stream, 0, 0) == expected[0]
    assert rig.memory.read(rig.stream + 0x88, 4) == 0x12345678
    assert rig.memory.read(rig.stream + 0x18, 4) == 999
    assert not any(e[0] == "write" and e[1] == rig.stream + 0x88 for e in rig.events)


def test_draw_repeats_operand_reads_and_rereads_index_after_each_publication():
    rig = Rig()
    rig.set_state(rig.stream, list(range(1, 17)), 0, 0, 123)
    s, seen = rig.stream, {}

    def read(at, width, value):
        seen[at] = seen.get(at, 0) + 1
        if at == s + 0x58 and seen[at] == 1:
            rig.memory.write(at, 4, 101)
        if at == s + 0x48 and seen[at] == 1:
            rig.memory.write(at, 4, 500)
        if at == s + 0x34 and seen[at] == 1:
            rig.memory.write(at, 4, 99)

    def write(at, width, value):
        if at == s + 0x24:
            rig.memory.write(s + 0x64, 4, 5)
        if at == s + 0x64:
            rig.memory.write(s + 0x64, 4, 7)
            rig.memory.write(s + 0x34, 4, 500)

    rig.on_read, rig.on_write = read, write
    assert rig.run(DRAW, s, 0, 0) == 8
    for at, expected in [
        (s + 0x58, [14, 101]),
        (s + 0x48, [10, 500]),
        (s + 0x34, [500, 99]),
        (s + 0x64, [0, 5, 7]),
    ]:
        assert [v for address, _, v in rig.read_values if address == at] == expected
    assert ("write", s + 0x24, 4, 0x60190) in rig.events
    assert ("write", s + 0x64, 4, 4) in rig.events


def test_initial_draw_index_is_not_silently_masked_before_its_first_access():
    rig = Rig()
    rig.memory.write(rig.stream + 0x64, 4, 0x10000000)
    with pytest.raises(ReplayMemoryError):
        rig.run(DRAW, rig.stream, 0, 0)
    assert rig.memory.read(rig.stream + 0x18, 4) == 1
    assert rig.events[-1] == ("read", rig.stream + 0x40000024, 4)


def test_zero_registry_count_requires_only_count_backing_and_ignores_zero_budget():
    memory, events = ReplayMemory(), []
    memory.map_bytes(COUNT, bytes(8))

    def read(at, width):
        events.append((at, width))
        return memory.read(at, width)

    binding = bind_replay_random_registry_storage(
        ReplayTaskRebuildStorage(1, read, memory.write),
        ReplayTaskRebuildCalls(None),
        profile=ReplayRandomRegistryStorageProfile(0, SCRATCH),
        bind_local=memory.bind_local,
    )
    assert binding.call(REGISTRY, (0xFFFFFFFFFFFFFFFF,), None) is None
    assert events == [(COUNT, 8)]


def test_null_slots_hold_count_but_reload_current_base_on_each_iteration():
    rig = Rig()
    first = rig.registry([0, 0])
    replacement = rig.memory.allocate(16)
    rig.memory.write(replacement + 8, 8, rig.stream)

    def read(at, width, value):
        if at == first:
            rig.memory.write(COUNT, 8, 0)
            rig.memory.write(BASE, 8, replacement)

    rig.on_read = read
    rig.run(REGISTRY, 0)
    assert rig.memory.read(rig.stream + 0x18, 4) == 1
    reads = [e for e in rig.events if e[0] == "read" and e[1] in (BASE, COUNT)]
    assert reads == [("read", COUNT, 8), ("read", BASE, 8), ("read", BASE, 8), ("read", COUNT, 8)]


def test_registry_holds_stream_across_seed_formatter_replacing_its_slot():
    rig = Rig()
    base = rig.registry([rig.stream])
    replacement = rig.new_stream(calls=55)
    rig.logging()

    def formatter(args, data):
        rig.memory.write(base, 8, replacement)
        rig.memory.write(ENABLE, 1, 0)

    rig.formatter = formatter
    rig.run(REGISTRY, 0)
    assert rig.memory.read(rig.stream + 0x18, 4) == 1
    assert rig.memory.read(replacement + 0x18, 4) == 55


@pytest.mark.parametrize("grow", [False, True])
def test_registry_count_is_refreshed_only_after_nonnull_seed_and_draw(grow):
    rig = Rig()
    other = rig.new_stream()
    base = rig.registry([rig.stream, other])
    rig.memory.write(COUNT, 8, 1 if grow else 2)

    def write(at, width, value):
        if at == rig.stream + 0x18:
            rig.memory.write(COUNT, 8, 2 if grow else 0)

    rig.on_write = write
    rig.run(REGISTRY, 0)
    assert rig.memory.read(rig.stream + 0x18, 4) == 1
    assert rig.memory.read(other + 0x18, 4) == int(grow)
    assert sum(e == ("read", base + 8, 8) for e in rig.events) == int(grow)


def test_registry_chains_full_word_instead_of_masked_seed_between_streams():
    raw = (FIXTURES / "native_replay_random_registry_54800.json.gz").read_bytes()
    case = next(
        c
        for c in json.loads(gzip.decompress(raw))["cases"]
        if c["op"] == 0 and c["seed"] == 21976 and c["before"][0] == 3
    )
    before, after = decode_registry(case["before"]), decode_registry(case["after"])
    rig = Rig()
    streams = []
    for state, _ in before:
        calls, last, index, *words = state
        streams.append(rig.new_stream(words=words, index=index, calls=calls, last=last))
    rig.registry(streams)
    assert after[0][0][2] == 15
    assert after[0][0][18] > 32767  # Native first full-word result feeding second seed.
    rig.run(REGISTRY, (0xAABBCCDD << 32) | case["seed"])
    assert [rig.state(stream) for stream in streams] == [state for state, _ in after]


def test_engine_and_stream_field_address_arithmetic_wraps_at_u64():
    raw = (FIXTURES / "native_replay_random_registry_54800.json.gz").read_bytes()
    case = next(
        c
        for c in json.loads(gzip.decompress(raw))["cases"]
        if c["op"] == 0 and c["seed"] == 0 and c["before"][0] == 1
    )
    before = decode_registry(case["before"])[0][0]
    expected = decode_registry(case["after"])[0][0]
    memory, stream = ReplayMemory(), (1 << 64) - 0x24
    memory.map_bytes(stream, bytes(0x24))
    memory.map_bytes(0, bytes(0x6C))
    memory.write(stream + 0x18, 4, before[0])
    memory.write(0x64, 4, before[1])  # Wrapped stream88.
    binding = bind_replay_random_registry_storage(
        ReplayTaskRebuildStorage(1, memory.read, memory.write),
        ReplayTaskRebuildCalls(None),
        profile=ReplayRandomRegistryStorageProfile(0, SCRATCH),
        bind_local=memory.bind_local,
    )
    assert binding.call(SEED, (stream, 0, 0, 0), None) is None
    result = binding.call(DRAW, (stream, 0, 0), None)
    actual = [
        memory.read((stream + offset) & ((1 << 64) - 1), 4)
        for offset in (0x18, 0x88, 0x64, *range(0x24, 0x64, 4))
    ]
    assert actual == expected
    assert result == expected[3 + expected[2]]


@pytest.mark.parametrize("count", [1, (1 << 64) - 1])
def test_zero_budget_refuses_nonzero_unsigned_count_before_base_read(count):
    rig = Rig(maximum=0)
    rig.memory.write(COUNT, 8, count)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="work limit"):
        rig.run(REGISTRY, 0)
    assert rig.events == [("read", COUNT, 8)]


def test_null_slots_spend_work_and_next_outer_call_resets_after_failure():
    rig = Rig(maximum=1)
    rig.registry([0, rig.stream])
    with pytest.raises(UnresolvedReplayTaskRebuild, match="work limit"):
        rig.run(REGISTRY, 0)
    assert rig.memory.read(rig.stream + 0x18, 4) == 0
    assert sum(e == ("read", BASE, 8) for e in rig.events) == 1
    rig.registry([rig.stream])
    rig.run(REGISTRY, 0)
    assert rig.memory.read(rig.stream + 0x18, 4) == 1


def test_formatter_registry_reentry_shares_budget_and_failure_resets_outer_state_only():
    rig = Rig(maximum=1)
    rig.registry([rig.stream])
    rig.logging()
    nested = []

    def formatter(args, data):
        start = len(rig.events)
        with pytest.raises(UnresolvedReplayTaskRebuild, match="work limit"):
            rig.run(REGISTRY, 99)
        nested.append(rig.events[start:])
        # Catching an inner refusal must not refresh the outer active budget.
        with pytest.raises(UnresolvedReplayTaskRebuild, match="work limit"):
            rig.run(REGISTRY, 100)
        raise RuntimeError("actual formatter stops outer call")

    rig.formatter = formatter
    with pytest.raises(RuntimeError, match="stops outer"):
        rig.run(REGISTRY, 0)
    assert nested == [[("read", COUNT, 8)]]
    rig.memory.write(rig.stream + 0x20, 1, 0)
    rig.run(REGISTRY, 0)
    assert rig.memory.read(rig.stream + 0x18, 4) == 1


@pytest.mark.parametrize("target", [SEED, DRAW, LOGGER])
def test_missing_formatter_refuses_after_prior_effects_and_closes_logical_frame(target):
    rig = Rig()
    rig.logging()
    before = rig.state(rig.stream)
    args = (rig.stream, 0, 0) if target == DRAW else (rig.stream, 0, 0, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14101adb0"):
        rig.run(target, *args)
    assert len(rig.exit_bytes) == 1
    with pytest.raises(ReplayMemoryError):
        rig.memory.read(rig.frames[0], 1)
    if target == DRAW:
        assert rig.memory.read(rig.stream + 0x18, 4) == before[0] + 1
    else:
        assert rig.state(rig.stream) == before


@pytest.mark.parametrize("target", [REGISTRY, SEED, ENGINE, DRAW, LOGGER])
def test_malformed_known_abi_refuses_before_storage_or_local_effects(target):
    rig = Rig()
    args = {
        REGISTRY: (0,),
        SEED: (rig.stream, 0, 0, 0),
        ENGINE: (rig.stream + 0x24, 0),
        DRAW: (rig.stream, 0, 0),
        LOGGER: (rig.stream, 0, 0, 0),
    }[target]
    for bad, data in [
        ((), None),
        ((*args, 0), None),
        ((True, *args[1:]), None),
        (args, memoryview(b"x")),
    ]:
        with pytest.raises(ValueError):
            rig.binding.call(target, bad, data)
    assert not rig.events


@pytest.mark.parametrize(
    ("maximum", "scratch"),
    [
        (-1, SCRATCH),
        (True, SCRATCH),
        (None, SCRATCH),
        (1.5, SCRATCH),
        (1, b""),
        (1, bytes(143)),
        (1, bytes(145)),
        (1, bytearray(144)),
    ],
)
def test_explicit_work_and_scratch_profile_is_required(maximum, scratch):
    with pytest.raises(ValueError):
        ReplayRandomRegistryStorageProfile(maximum, scratch)


def test_unknown_target_preserves_argument_payload_and_result_identity():
    memory, seen = ReplayMemory(), []
    marker, args, payload = object(), (1, 2), memoryview(b"payload")

    def call(target, incoming, data):
        seen.append((target, incoming, data))
        return marker

    binding = bind_replay_random_registry_storage(
        ReplayTaskRebuildStorage(1, memory.read, memory.write),
        ReplayTaskRebuildCalls(call),
        profile=ReplayRandomRegistryStorageProfile(0, SCRATCH),
        bind_local=memory.bind_local,
    )
    assert binding.call(0x1234, args, payload) is marker
    assert seen[0][1] is args and seen[0][2] is payload
