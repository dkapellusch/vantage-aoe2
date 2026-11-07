"""Normal DE string source phases with actual owned Input/Result composition."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_de_string_saved import (
    ReplayDEStringSavedScratch,
    bind_replay_de_string_saved,
    read_replay_de_string_saved,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

ENTRY, READ1, READ2, FREE = 0x140A1BDF0, 0x701, 0x702, 0x703
FORWARD, CLEAR, GROW = 0x1409076B0, 0x1402BD890, 0x140A1A5E0
MAGIC, U64 = 0xA60, (1 << 64) - 1
SEEDS = ReplayDEStringSavedScratch(b"\x55\xaa", b"\xbb\xcc")


def wire(payload=b"abc", *, swapped=False):
    first, second = (len(payload), MAGIC) if swapped else (MAGIC, len(payload))
    return first.to_bytes(2, "little") + second.to_bytes(2, "little") + payload


class Harness:
    def __init__(self, raw, *, pointer=0, length=7, capacity=0):
        self.memory = ReplayMemory()
        self.events = []
        self.locals = []
        self.final_locals = {}
        self.active = 0
        self.before_call = lambda target, args, data: None
        self.after_call = lambda target, args, data, result: None
        self.after_read = lambda address, width, value: None
        self.before_write = lambda address, width, value: None
        self.child = lambda target, args, data: None
        self.context = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.source = ReplaySavedInput(raw)
        self.atomics = ReplayUnitAIMapAtomics(None, self.fetch_add)
        self.runtime = self.memory.runtime_calls(ReplayTaskRebuildCalls(self.terminal))
        self.memory.map_bytes(0x143199DD0, FREE.to_bytes(8, "little"))
        self.address = self.memory.allocate(40)
        self.memory.write_bytes(self.address, b"\xa5" * 40)
        for offset, value in ((0, pointer), (8, length), (16, capacity)):
            self.memory.write(self.address + offset, 8, value)
        self.output = self.memory.allocate(48)
        self.memory.write_bytes(self.output, b"\xd7" * 48)
        self.stream, self.table, self.table2 = (
            self.memory.allocate(8),
            self.memory.allocate(32),
            self.memory.allocate(32),
        )
        self.memory.write(self.stream, 8, self.table)
        self.memory.write(self.table + 24, 8, READ1)
        self.memory.write(self.table2 + 24, 8, READ2)
        support = bind_replay_unit_constructor_support(
            self.context,
            self.runtime,
            bind_local=self.bind_local,
            imports=ReplayTaskRebuildCalls(self.terminal),
        )
        result = bind_replay_saved_result(
            self.context,
            support,
            atomics=self.atomics,
            imports=ReplayTaskRebuildCalls(self.terminal),
        )
        apply = bind_replay_saved_apply(
            self.context,
            result,
            atomics=self.atomics,
            imports=ReplayTaskRebuildCalls(self.terminal),
        )
        input1 = bind_replay_saved_input(
            self.context,
            apply,
            self.source,
            stream=self.stream,
            target=READ1,
            result_bytes=bytes(48),
        )
        self.lower = bind_replay_saved_input(
            self.context,
            input1,
            self.source,
            stream=self.stream,
            target=READ2,
            result_bytes=bytes(48),
        )
        self.calls = ReplayTaskRebuildCalls(self.call)

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("read", address, width, value))
        self.after_read(address, width, value)
        return value

    def write(self, address, width, value):
        self.events.append(("write", address, width, value))
        self.before_write(address, width, value)
        self.memory.write(address, width, value)

    def fetch_add(self, address, addend):
        previous = self.memory.fetch_add_u32(address, addend)
        self.events.append(("atomic", address, addend, previous))
        return previous

    def terminal(self, target, args, data):
        if target == FREE:
            self.memory.free(args[0])
            return None
        return self.child(target, args, data)

    def call(self, target, args, data):
        self.events.append(("call", target, args, data))
        self.before_call(target, args, data)
        assert self.lower.call is not None
        result = self.lower.call(target, args, data)
        self.after_call(target, args, data, result)
        return result

    @contextmanager
    def bind_local(self, view):
        self.active += 1
        try:
            with self.memory.bind_local(view) as address:
                self.locals.append((address, len(view), view.tobytes()))
                try:
                    yield address
                finally:
                    self.final_locals[address] = view.tobytes()
        finally:
            self.active -= 1

    def run(self, *, bound=False, scratch=SEEDS, calls=None):
        calls = self.calls if calls is None else calls
        if bound:
            actual = bind_replay_de_string_saved(
                self.context,
                calls,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=scratch,
            )
            assert actual.call is not None
            return actual.call(ENTRY, (self.address, self.output, self.stream), None)
        return read_replay_de_string_saved(
            self.context,
            self.address,
            self.output,
            self.stream,
            calls=calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=scratch,
        )


@pytest.mark.parametrize("payload", [b"", b"a", b"ab\0\xffZ", b"x" * 16])
@pytest.mark.parametrize("swapped", [False, True])
@pytest.mark.parametrize("bound", [False, True])
def test_real_bytes_results_cleanup_growth_and_output_padding(payload, swapped, bound) -> None:
    h = Harness(wire(payload, swapped=swapped))
    assert h.run(bound=bound) == h.output
    assert h.source.position == 4 + len(payload) and h.source.remaining == 0
    assert h.active == 0
    assert h.memory.read_bytes(h.output, 48) == bytes(41) + b"\xd7" * 7
    assert h.memory.read_bytes(h.address + 24, 16) == b"\xa5" * 16
    calls = [e for e in h.events if e[0] == "call"]
    assert [e[3] for e in calls if e[1] == READ1] == [None] * (3 if payload else 2)
    assert [e[2][3] for e in calls if e[1] == READ1] == (
        [2, 2, len(payload)] if payload else [2, 2]
    )
    assert len([e for e in calls if e[1] == FORWARD]) == 2
    assert len([e for e in calls if e[1] == CLEAR]) == (5 if payload else 4)
    if payload:
        pointer = h.memory.read(h.address, 8)
        assert h.memory.read_bytes(pointer, len(payload) + 1) == payload + b"\0"
        assert h.memory.read(h.address + 8, 8) == len(payload)
        region = next(r for r in h.memory.snapshot().regions if r.address == pointer)
        assert region.defined[: len(payload) + 1] == b"\x01" * (len(payload) + 1)
        assert not any(region.defined[len(payload) + 1 :])
    else:
        assert h.memory.read(h.address, 8) == 0
        assert h.memory.read(h.address + 8, 8) == 7
        assert not any(e[1] == GROW for e in calls)


def test_both_header_words_magic_is_real_nonzero_length_not_empty_or_error() -> None:
    h = Harness(wire(b"x" * MAGIC))
    h.run()
    assert h.memory.read(h.address + 8, 8) == MAGIC
    assert h.source.position == MAGIC + 4


@pytest.mark.parametrize("capacity,pointer,reads_pointer", [(0, 0xBAD, False), (8, 0, True)])
def test_entry_capacity_first_and_reset_only_if_capacity_and_pointer_nonzero(
    capacity,
    pointer,
    reads_pointer,
) -> None:
    h = Harness(wire(b""), pointer=pointer, capacity=capacity)
    before = h.memory.read_bytes(h.address, 24)
    h.run()
    assert h.events[0] == ("read", h.address + 16, 8, capacity)
    if reads_pointer:
        assert h.events[1] == ("read", h.address, 8, pointer)
    else:
        assert h.events[1][0] == "write"
    assert h.memory.read_bytes(h.address, 24) == before


def test_real_old_free_and_reset_happen_before_first_read_and_empty_does_no_more() -> None:
    h = Harness(wire(b""))
    old = h.memory.allocate(8)
    h.memory.write_bytes(old, b"old\0xxxx")
    h.memory.write(h.address, 8, old)
    h.memory.write(h.address + 16, 8, 8)
    h.run()
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(old, 1)
    assert h.memory.read(h.address, 8) == 0x14428BB30
    assert h.memory.read(h.address + 8, 8) == h.memory.read(h.address + 16, 8) == 0
    assert h.events[:7] == [
        ("read", h.address + 16, 8, 8),
        ("read", h.address, 8, old),
        ("call", 0x142D6C270, (old,), None),
        ("read", 0x143199DD0, 8, FREE),
        ("write", h.address, 8, 0x14428BB30),
        ("write", h.address + 16, 8, 0),
        ("write", h.address + 8, 8, 0),
    ]


def test_old_free_failure_precedes_all_locals_and_input() -> None:
    h = Harness(wire())
    h.memory.write(h.address, 8, 0xBAD)
    h.memory.write(h.address + 16, 8, 8)
    with pytest.raises(ReplayMemoryError, match="owned allocation"):
        h.run()
    assert h.locals == [] and h.source.position == 0
    assert h.memory.read(h.address, 8) == 0xBAD


def test_current_stream_vptr_is_reloaded_for_each_header_and_payload() -> None:
    h = Harness(wire())
    reads = 0

    def after(target, args, data, result):
        nonlocal reads
        if target in (READ1, READ2):
            reads += 1
            h.memory.write(h.stream, 8, h.table2 if reads == 1 else h.table)

    h.after_call = after
    h.run()
    assert [e[1] for e in h.events if e[0] == "call" and e[1] in (READ1, READ2)] == [
        READ1,
        READ2,
        READ1,
    ]


def test_payload_reads_vptr_then_current_destination_then_current_slot() -> None:
    h = Harness(wire())
    seen = []

    def after(target, args, data, result):
        if target == GROW:
            h.memory.write(h.table + 24, 8, READ1)
            seen.append(True)

    def mutate(address, width, value):
        if seen and address == h.address:
            h.memory.write(h.table + 24, 8, READ2)

    h.after_call, h.after_read = after, mutate
    h.run()
    payload = next(i for i, e in enumerate(h.events) if e[0] == "call" and e[1] == READ2)
    assert h.events[payload - 3 : payload] == [
        ("read", h.stream, 8, h.table),
        ("read", h.address, 8, h.events[payload][2][2]),
        ("read", h.table + 24, 8, READ2),
    ]


def test_terminator_rereads_pointer_after_actual_payload_cleanup() -> None:
    h = Harness(wire())
    replacement = h.memory.allocate(8)
    h.memory.write_bytes(replacement, b"X" * 8)
    payload_result = []

    def after(target, args, data, result):
        if target in (READ1, READ2) and args[3] == 3:
            payload_result.append(args[1])
        if target == CLEAR and payload_result and args[0] == payload_result[0]:
            h.memory.write(h.address, 8, replacement)

    h.after_call = after
    h.run()
    assert h.memory.read_bytes(replacement, 8) == b"XXX\0XXXX"
    assert h.memory.read(h.address + 8, 8) == 3


def test_explicit_word_seeds_preserve_unwritten_bytes_from_declared_partial_provider() -> None:
    h = Harness(b"")
    reads = 0

    def call(target, args, data):
        nonlocal reads
        if target == READ1:
            reads += 1
            h.memory.write(args[2], 1, 0x60 if reads == 1 else 3)
            h.memory.write_bytes(args[1], bytes(48))
            if reads == 3:
                h.memory.write_bytes(args[2], b"abc")
            return 0xBAD
        assert h.lower.call is not None
        return h.lower.call(target, args, data)

    seeds = ReplayDEStringSavedScratch(b"\0\x0a", b"\0\0")
    h.run(scratch=seeds, calls=ReplayTaskRebuildCalls(call))
    assert h.memory.read_bytes(h.memory.read(h.address, 8), 4) == b"abc\0"
    assert h.locals[:2] == [(h.locals[0][0], 2, seeds.signature), (h.locals[1][0], 2, seeds.length)]


def test_header_control_acquire_release_and_payload_release_use_real_atomic_paths() -> None:
    h = Harness(wire())
    controls = []
    virtuals = []

    def after(target, args, data, result):
        if target not in (READ1, READ2):
            return
        control, table = h.memory.allocate(16), h.memory.allocate(16)
        for at, width, value in (
            (control, 8, table),
            (control + 8, 4, 1),
            (control + 12, 4, 1),
            (table, 8, 0xD1),
            (table + 8, 8, 0xD2),
        ):
            h.memory.write(at, width, value)
        controls.append(control)
        h.memory.write(args[1] + 32, 8, control)

    def child(target, args, data):
        assert target in (0xD1, 0xD2) and args[0] in controls
        virtuals.append((target, args[0]))

    h.after_call, h.child = after, child
    h.run()
    assert virtuals == [(target, control) for control in controls for target in (0xD1, 0xD2)]
    assert len([e for e in h.events if e[0] == "atomic"]) == 10
    assert all(
        h.memory.read(control + 8, 4) == h.memory.read(control + 12, 4) == 0 for control in controls
    )


@pytest.mark.parametrize("read_index", [1, 2, 3])
def test_raw_result_error_frontiers_preserve_reads_and_exact_processed_phase(read_index) -> None:
    h = Harness(wire())
    count, failed = 0, []

    def after(target, args, data, result):
        nonlocal count
        if target in (READ1, READ2):
            count += 1
            if count == read_index:
                h.memory.write(args[1] + 24, 8, 99)
                failed.append(args[1])

    h.after_call = after
    with pytest.raises(UnresolvedReplayTaskRebuild, match="frontier"):
        h.run()
    assert h.source.position == (2 * read_index if read_index < 3 else 7)
    assert h.memory.read_bytes(h.output, 48) == b"\xd7" * 48
    assert h.final_locals[failed[0]][40] == (1 if read_index < 3 else 0)
    assert h.active == 0


def test_forwarded_status_checked_only_after_b_result_cleanup() -> None:
    h = Harness(wire())
    result_a, result_b = [], []

    def before(target, args, data):
        if target == FORWARD:
            result_a.append(args[0])
            result_b.append(args[1])
        if target == CLEAR and result_b and args[0] == result_b[0]:
            h.memory.write(result_a[0] + 24, 8, 9)

    h.before_call = before
    with pytest.raises(UnresolvedReplayTaskRebuild, match="forwarded-error"):
        h.run()
    assert h.source.position == 2
    assert h.final_locals[result_a[0]][40] == 0
    assert any(e[0] == "call" and e[1] == CLEAR for e in h.events)


def test_missing_sentinel_refuses_after_both_real_header_cleanups_before_tls() -> None:
    h = Harness(b"\x01\0\x02\0")
    with pytest.raises(UnresolvedReplayTaskRebuild, match="signature TLS"):
        h.run()
    assert h.source.position == 4 and h.active == 0
    assert len([e for e in h.events if e[0] == "call" and e[1] == CLEAR]) == 4
    assert h.memory.read_bytes(h.output, 48) == b"\xd7" * 48


def test_actual_truncation_preserves_prior_free_headers_allocation_and_cursor() -> None:
    h = Harness(MAGIC.to_bytes(2, "little") + b"\x04\0" + b"ab")
    with pytest.raises(UnresolvedReplayTaskRebuild, match="remaining"):
        h.run()
    assert h.source.position == 4
    assert h.memory.read(h.address + 16, 8) == 32
    assert h.memory.read(h.address + 8, 8) == 7
    allocated = h.memory.read(h.address, 8)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.memory.read(allocated, 1)


def test_required_forward_failure_is_not_replaced_by_zero_success() -> None:
    h = Harness(wire())

    def call(target, args, data):
        if target == FORWARD:
            raise UnresolvedReplayTaskRebuild("missing actual forward")
        assert h.lower.call is not None
        return h.lower.call(target, args, data)

    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual forward"):
        h.run(calls=ReplayTaskRebuildCalls(call))
    assert h.source.position == 2 and h.active == 0


def test_missing_actual_input_refuses_despite_zero_initialized_result_storage() -> None:
    h = Harness(wire(b""))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.run(calls=ReplayTaskRebuildCalls(None))
    assert h.source.position == 0 and h.active == 0
    assert h.memory.read_bytes(h.output, 48) == b"\xd7" * 48
    assert h.final_locals[h.locals[2][0]] == bytes(48)
    assert h.final_locals[h.locals[3][0]] == bytes(48)


def test_final_result_store_failure_keeps_string_and_prior_output_words() -> None:
    h = Harness(wire())

    def fail(address, width, value):
        if address == h.output + 16:
            raise RuntimeError("output store")

    h.before_write = fail
    with pytest.raises(RuntimeError, match="output store"):
        h.run()
    assert h.memory.read_bytes(h.output, 24) == bytes(16) + b"\xd7" * 8
    assert h.memory.read_bytes(h.memory.read(h.address, 8), 4) == b"abc\0"


@pytest.mark.parametrize(
    "signature,length", [(b"", b"12"), (b"123", b"12"), (b"12", bytearray(b"12")), (b"12", b"")]
)
def test_raw_word_scratch_width_and_type_admission(signature, length) -> None:
    with pytest.raises(ValueError):
        ReplayDEStringSavedScratch(signature, length)


@pytest.mark.parametrize(
    "args,data",
    [
        ((), None),
        ((1, 2), None),
        ((1, 2, 3, 4), None),
        ((True, 2, 3), None),
        ((1, -1, 3), None),
        ((1, 2, U64 + 1), None),
        ((1, 2, 3), memoryview(bytearray())),
    ],
)
def test_known_binding_refusal_before_access(args, data) -> None:
    h = Harness(wire())
    bound = bind_replay_de_string_saved(
        h.context, h.calls, atomics=h.atomics, bind_local=h.bind_local, scratch=SEEDS
    )
    assert bound.call is not None
    with pytest.raises(ValueError):
        bound.call(ENTRY, args, data)
    assert h.events == [] and h.locals == []


def test_unknown_delegate_keeps_live_view_and_raw_return_and_missing_refuses() -> None:
    h = Harness(wire())
    view = memoryview(bytearray(b"abc"))

    def child(target, args, data):
        assert target == 0xABC and args == (U64,) and data is view
        data[0] = 0xEE
        return U64

    bound = bind_replay_de_string_saved(
        h.context,
        ReplayTaskRebuildCalls(child),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SEEDS,
    )
    assert bound.call is not None
    assert bound.call(0xABC, (U64,), view) == U64
    assert view.tobytes() == b"\xeebc"
    missing = bind_replay_de_string_saved(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SEEDS,
    )
    assert missing.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        missing.call(0xABC, (), None)
