"""Source-derived finite attachment controls; authored seams are explicit.

Normal cases compose the eleven actual staged bodies and owned Memory runtime.
Callback seams isolate held/current/alias ordering and mandatory refusal paths;
they do not supply a successful implementation of any unclosed game reader.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_attachment as attachment
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

FACTORY, CTOR, MOVE, HOLDER = 0x1416C2180, 0x1416C2270, 0x1416BFE70, 0x1416C6A40
RANGES = (0x1416E8D10, 0x1416E8C50)
VECTORS = (0x1416C6580, 0x1416C6660, 0x14126E8A0)
NODES = (0x1416C6730, 0x1416C6850)
MALLOC, FREE, WATSON_IAT, WATSON = 0x142D6BA78, 0x142D6BAB4, 0x14319A060, 0xBACE50
U64 = (1 << 64) - 1


class Fixture:
    def __init__(self, *, words=1024, nodes=1024):
        self.memory = ReplayMemory(max_bytes=2 << 20)
        self.subject = self.alloc(128, 0xA5)
        self.output = self.alloc(16, 0)
        self.events, self.effects, self.active, self.closed = [], {}, {}, []
        self.on_read = self.on_write = None
        self.context = ReplayTaskRebuildStorage(self.subject, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.imports = ReplayTaskRebuildCalls(self.terminal)
        self.primitive = self.memory.runtime_calls()
        self.scratch = attachment.ReplayPlayerAttachmentScratch(
            b"\xa5" * 8, b"\xc7" * 16, b"\xe9" * 8
        )
        self.profile = attachment.ReplayPlayerAttachmentProfile(words, nodes)
        self.bound = attachment.bind_replay_player_attachment(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            scratch=self.scratch,
            profile=self.profile,
            imports=self.imports,
        )
        self.memory.map_bytes(WATSON_IAT, WATSON.to_bytes(8, "little"))

    def alloc(self, size, byte=None):
        address = self.memory.allocate(size)
        if byte is not None:
            self.memory.fill(address, byte, size)
        return address

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.on_read:
            self.on_read(address, width, value)
        return value

    def write(self, address, width, value):
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.on_write:
            self.on_write(address, width, value)

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.active[address] = view
            self.events.append(("local", address, bytes(view)))
            try:
                yield address
            finally:
                self.closed.append((address, bytes(view)))
                del self.active[address]

    def actual(self, target, args):
        assert self.primitive.call is not None
        return self.primitive.call(target, args, None)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.effects:
            return self.effects[target](args)
        if target in (FACTORY, CTOR, MOVE, HOLDER, *RANGES, *VECTORS, *NODES):
            return self.run(target, *args)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def run(self, target, *args):
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def ctor(self):
        return attachment.construct_replay_player_attachment(
            self.context,
            self.subject,
            calls=self.calls,
            bind_local=self.bind_local,
            scratch=self.scratch,
            profile=self.profile,
        )

    def factory(self):
        return attachment.create_replay_player_attachment(
            self.context,
            self.output,
            calls=self.calls,
            bind_local=self.bind_local,
            scratch=self.scratch,
        )

    def vector(self, begin=0, end=0, capacity=0):
        header = self.alloc(24, 0)
        for offset, value in ((0, begin), (8, end), (16, capacity)):
            self.memory.write(header + offset, 8, value)
        return header

    def sentinel(self, size=0x68):
        value = self.alloc(size, 0)
        self.memory.write(value, 8, value)
        self.memory.write(value + 8, 8, value)
        return value

    def chain(self, outer=1, inner=1):
        sentinel = self.sentinel()
        nodes = [self.alloc(0x68, 0) for _ in range(outer)]
        nested_sets = []
        for index, node in enumerate(nodes):
            self.memory.write(node, 8, nodes[index + 1] if index + 1 < outer else sentinel)
            nested = self.sentinel(0x18)
            entries = [self.alloc(0x18, 0) for _ in range(inner)]
            if entries:
                self.memory.write(nested, 8, entries[0])
                self.memory.write(nested + 8, 8, entries[-1])
                for j, entry in enumerate(entries):
                    self.memory.write(entry, 8, entries[j + 1] if j + 1 < inner else nested)
            self.memory.write(node + 0x30, 8, nested)
            nested_sets.append((nested, entries))
        if nodes:
            self.memory.write(sentinel, 8, nodes[0])
            self.memory.write(sentinel + 8, 8, nodes[-1])
        header = self.alloc(8, 0)
        self.memory.write(header, 8, sentinel)
        return header, sentinel, nodes, nested_sets

    def calls_to(self, target):
        return [event[2] for event in self.events if event[:2] == ("c", target)]


def fail(args):
    raise UnresolvedReplayTaskRebuild("authored mandatory provider refusal")


def test_factory_null_alloc_live_home_and_delayed_zero_publication():
    f = Fixture()
    f.memory.write(f.output, 8, 0xDEAD)

    def allocation(args):
        assert args == (128,)
        assert len(f.active) == 1
        frame = next(iter(f.active))
        assert f.memory.read(frame, 8) == f.output
        assert f.memory.read(f.output, 8) == 0xDEAD
        f.memory.write(frame, 8, 0xBAD)
        return 0

    f.effects[MALLOC] = allocation
    assert f.factory() == f.output
    assert f.memory.read(f.output, 8) == 0
    assert not f.calls_to(CTOR)
    assert f.closed[-1][1] == bytes(8)
    assert not f.active


def test_factory_eight_ordered_zeroes_and_actual_ctor_return_held_output():
    f = Fixture()
    allocated = f.alloc(128, 0xDC)
    f.effects[MALLOC] = lambda args: allocated

    def child(args):
        assert args == (allocated,)
        assert f.memory.read_bytes(allocated, 128) == bytes(128)
        frame = next(iter(f.active))
        assert f.memory.read(frame, 8) == allocated
        f.memory.write(frame, 8, f.subject)
        return 0x12345678

    f.effects[CTOR] = child
    assert f.factory() == f.output
    stores = [e[1:] for e in f.events if e[0] == "w" and allocated <= e[1] < allocated + 128]
    assert stores == [(allocated + offset, 16, 0) for offset in range(0, 128, 16)]
    assert f.memory.read(f.output, 8) == 0x12345678


@pytest.mark.parametrize("missing", [MALLOC, CTOR])
def test_factory_missing_provider_keeps_old_output_and_prior_effects(missing):
    f = Fixture()
    f.memory.write(f.output, 8, 0xABC)
    f.effects[missing] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mandatory"):
        f.factory()
    assert f.memory.read(f.output, 8) == 0xABC
    assert not f.active and len(f.closed) == 1
    zeroes = [e for e in f.events if e[0] == "w" and e[2] == 16]
    assert len(zeroes) == (8 if missing == CTOR else 0)


def test_factory_full_composition_five_allocations_592bytes_two_tables():
    f = Fixture()
    assert f.run(FACTORY, f.output) == f.output
    obj = f.memory.read(f.output, 8)
    assert f.calls_to(MALLOC) == [(128,), (104,), (128,), (104,), (128,)]
    assert sum(args[0] for args in f.calls_to(MALLOC)) == 592
    for half in (obj, obj + 64):
        sentinel = f.memory.read(half + 8, 8)
        begin = f.memory.read(half + 24, 8)
        assert f.memory.read(sentinel, 8) == f.memory.read(sentinel + 8, 8) == sentinel
        assert f.memory.read_bytes(begin, 128) == sentinel.to_bytes(8, "little") * 16
        assert f.memory.read(half + 32, 8) == f.memory.read(half + 40, 8) == begin + 128
        assert f.memory.read(half, 4) == 0x3F800000
        assert f.memory.read(half + 48, 8) == 7 and f.memory.read(half + 56, 8) == 8
        assert f.memory.read(half + 4, 4) == 0
    assert [len(raw) for _, raw in f.closed] == [16, 8]


def test_direct_ctor_keeps_padding_and_coherent_live_home_return():
    f = Fixture()

    def allocation(args):
        frame = next(iter(f.active))
        assert f.memory.read(frame + 8, 8) == f.subject
        held = f.memory.read(frame, 8)
        assert held == (f.subject if len(f.calls_to(MALLOC)) <= 2 else f.subject + 64)
        result = f.actual(MALLOC, args)
        f.memory.write(frame + 8, 8, 0xBAD)
        return result

    # Mutate homes only at the last call; early mutation must also remain visible.
    count = 0

    def last_allocation(args):
        nonlocal count
        count += 1
        if count == 4:
            return allocation(args)
        return f.actual(MALLOC, args)

    f.effects[MALLOC] = last_allocation
    assert f.ctor() == f.subject
    assert f.memory.read(f.subject + 4, 4) == f.memory.read(f.subject + 68, 4) == 0xA5A5A5A5
    assert len(f.closed) == 1
    frame = f.closed[0][1]
    assert frame[:8] == (f.subject + 64).to_bytes(8, "little")
    assert frame[8:] == (0xBAD).to_bytes(8, "little")


def test_constructor_sentinel_null_has_real_storage_failure_no_guard():
    f = Fixture()
    f.effects[MALLOC] = lambda args: 0
    with pytest.raises(ReplayMemoryError):
        f.ctor()
    assert f.memory.read(f.subject, 4) == 0
    assert f.memory.read(f.subject + 8, 8) == f.memory.read(f.subject + 16, 8) == 0
    assert f.calls_to(MALLOC) == [(104,)]
    assert not f.active


def test_constructor_null_table_publishes_headers_before_real_fill_failure():
    f = Fixture()
    n = 0

    def allocation(args):
        nonlocal n
        n += 1
        return 0 if n == 2 else f.actual(MALLOC, args)

    f.effects[MALLOC] = allocation
    with pytest.raises(ReplayMemoryError):
        f.ctor()
    assert f.memory.read(f.subject + 24, 8) == 0
    assert f.memory.read(f.subject + 32, 8) == f.memory.read(f.subject + 40, 8) == 128


@pytest.mark.parametrize("words", [0, 15])
def test_literal_fill_budget_refuses_after_three_header_publications(words):
    f = Fixture(words=words)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="pointer-fill"):
        f.ctor()
    begin = f.memory.read(f.subject + 24, 8)
    assert f.memory.read(f.subject + 32, 8) == f.memory.read(f.subject + 40, 8) == begin + 128
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.memory.read(begin, 8)
    assert len(f.calls_to(MALLOC)) == 2
    assert f.memory.read(f.subject + 64, 4) == 0xA5A5A5A5


@pytest.mark.parametrize("half,range_target", [(0, RANGES[0]), (64, RANGES[1])])
def test_constructor_current_post_alloc_range_free_then_publish_held_sentinel(half, range_target):
    f = Fixture()
    old = f.alloc(16, 0)
    substitute = f.alloc(8, 0)
    count = 0
    expected_call = 2 if half == 0 else 4

    def allocation(args):
        nonlocal count
        count += 1
        result = f.actual(MALLOC, args)
        if count == expected_call:
            f.memory.write(f.subject + half + 24, 8, old)
            f.memory.write(f.subject + half + 40, 8, old + 16)
        return result

    def free(args):
        assert f.memory.read(f.subject + half + 24, 8) == old
        f.memory.write(f.subject + half + 8, 8, substitute)
        return f.actual(FREE, args)

    f.effects[MALLOC], f.effects[FREE] = allocation, free
    assert f.ctor() == f.subject
    assert f.calls_to(range_target) == [(f.subject + half + 24, old, 2)]
    begin = f.memory.read(f.subject + half + 24, 8)
    stored_sentinel = f.memory.read(begin, 8)
    assert stored_sentinel != substitute
    assert f.memory.read(f.subject + half + 8, 8) == substitute
    assert f.memory.read_bytes(begin, 128) == stored_sentinel.to_bytes(8, "little") * 16


@pytest.mark.parametrize("difference,expected_count", [(128, 16), (129, 17), (135, 17)])
def test_second_reuse_unsigned_sar_roundup_and_held_range(difference, expected_count):
    f = Fixture()
    begin = f.alloc(256, 0xDC)
    triggered = False

    def change(address, width, value):
        nonlocal triggered
        if address == f.subject + 64 and width == 4 and value == 0x3F800000:
            triggered = True
            f.memory.write(f.subject + 88, 8, begin)
            f.memory.write(f.subject + 96, 8, begin + difference)
            f.memory.write(f.subject + 104, 8, 0xBAD)

    f.on_write = change
    assert f.ctor() == f.subject and triggered
    assert len(f.calls_to(MALLOC)) == 3
    sentinel = f.memory.read(f.subject + 72, 8)
    assert (
        f.memory.read_bytes(begin, expected_count * 8)
        == sentinel.to_bytes(8, "little") * expected_count
    )
    assert f.memory.read(begin + expected_count * 8, 8) == 0xDCDCDCDCDCDCDCDC
    assert f.memory.read(f.subject + 96, 8) == begin + difference
    assert f.memory.read(f.subject + 104, 8) == 0xBAD


@pytest.mark.parametrize("begin,end", [(0x3000, 0x2FF8), (U64 - 7, 120)])
def test_second_reuse_begin_above_end_zero_fill_no_backing_required(begin, end):
    f = Fixture()

    def change(address, width, value):
        if address == f.subject + 64 and width == 4 and value == 0x3F800000:
            f.memory.write(f.subject + 88, 8, begin)
            f.memory.write(f.subject + 96, 8, end)

    f.on_write = change
    assert f.ctor() == f.subject
    assert len(f.calls_to(MALLOC)) == 3
    assert f.memory.read(f.subject + 88, 8) == begin


def test_dynamic_fill_budget_uses_rounded_source_count_after_metadata_no_republish():
    f = Fixture(words=16)
    begin = f.alloc(256, 0xDC)

    def change(address, width, value):
        if address == f.subject + 64 and width == 4 and value == 0x3F800000:
            f.memory.write(f.subject + 88, 8, begin)
            f.memory.write(f.subject + 96, 8, begin + 129)

    f.on_write = change
    with pytest.raises(UnresolvedReplayTaskRebuild, match="pointer-fill"):
        f.ctor()
    assert f.memory.read_bytes(begin, 256) == b"\xdc" * 256
    assert f.memory.read(f.subject + 96, 8) == begin + 129


@pytest.mark.parametrize("target", [MALLOC, RANGES[0], RANGES[1]])
def test_constructor_mandatory_failure_retains_earlier_stores(target):
    f = Fixture()
    if target == MALLOC:
        f.effects[MALLOC] = fail
    else:
        old = f.alloc(8, 0)
        n = 0

        def allocation(args):
            nonlocal n
            n += 1
            result = f.actual(MALLOC, args)
            if n == (2 if target == RANGES[0] else 4):
                half = 0 if target == RANGES[0] else 64
                f.memory.write(f.subject + half + 24, 8, old)
                f.memory.write(f.subject + half + 40, 8, old + 8)
            return result

        f.effects[MALLOC], f.effects[target] = allocation, fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mandatory"):
        f.ctor()
    assert f.memory.read(f.subject, 4) == (0 if target == MALLOC else 0x3F800000)
    if target == MALLOC:
        assert f.memory.read(f.subject + 8, 8) == 0
    else:
        assert f.memory.read(f.subject + (24 if target == RANGES[0] else 88), 8) == old
    assert not f.active


def test_move_same_cell_restores_pointer_and_skips_all_destruction():
    f = Fixture()
    f.memory.write(f.output, 8, 0x1234)
    assert f.run(MOVE, f.output, f.output) == f.output
    assert f.memory.read(f.output, 8) == 0x1234
    assert [e for e in f.events if e[0] != "local"] == [
        ("r", f.output, 8, 0x1234),
        ("w", f.output, 8, 0),
        ("r", f.output, 8, 0),
        ("w", f.output, 8, 0x1234),
    ]


def test_move_partial_overlap_observes_zero_before_old_read_and_held_replacement():
    f = Fixture()
    f.memory.write(f.output, 8, 0x1122334455667788)
    # Destination at source+4 reads its low4 after source zero; high4 already0.
    assert f.run(MOVE, f.output + 4, f.output) == f.output + 4
    assert f.memory.read(f.output + 4, 8) == 0x1122334455667788
    assert f.memory.read(f.output, 4) == 0
    assert not f.calls_to(FREE)


@pytest.mark.parametrize("target", [VECTORS[0], NODES[0], VECTORS[1], NODES[1], FREE])
def test_move_publishes_before_each_mandatory_cleanup_failure(target):
    f = Fixture()
    old, replacement = f.alloc(128, 0), f.alloc(128, 0)
    f.memory.write(f.subject, 8, old)
    f.memory.write(f.output, 8, replacement)
    order = [(VECTORS[0], 88), (NODES[0], 72), (VECTORS[1], 24), (NODES[1], 8)]
    for child, _ in order:
        f.effects[child] = lambda args: None  # Explicit trace-only authored seam.
    f.effects[FREE] = lambda args: None
    f.effects[target] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mandatory"):
        attachment.move_replay_player_attachment(f.context, f.subject, f.output, calls=f.calls)
    assert f.memory.read(f.output, 8) == 0 and f.memory.read(f.subject, 8) == replacement
    reached = [(e[1], e[2]) for e in f.events if e[0] == "c"]
    expected = [(child, (old + offset,)) for child, offset in order] + [(FREE, (old, 128))]
    stop = [entry[0] for entry in expected].index(target) + 1
    assert reached == expected[:stop]


def test_holder_null_only_one_read_no_reset():
    f = Fixture()
    assert f.run(HOLDER, f.output) is None
    assert f.events == [("r", f.output, 8, 0)]


def test_holder_held_old_survives_cell_mutation_and_never_resets_holder():
    f = Fixture()
    old = f.alloc(128, 0)
    f.memory.write(f.output, 8, old)
    order = [(VECTORS[0], 88), (NODES[0], 72), (VECTORS[1], 24), (NODES[1], 8)]

    def child(args):
        f.memory.write(f.output, 8, 0xBAD)

    for target, _ in order:
        f.effects[target] = child
    attachment.clear_replay_player_attachment(f.context, f.output, calls=f.calls)
    assert f.memory.read(f.output, 8) == 0xBAD
    assert [(e[1], e[2]) for e in f.events if e[0] == "c"] == [
        *((target, (old + offset,)) for target, offset in order),
        (FREE, (old, 128)),
    ]


def test_whole_factory_move_cleanup_actual_ownership_and_unchanged_holder_cell():
    f = Fixture()
    holder = f.alloc(8, 0)
    f.run(FACTORY, f.output)
    old = f.memory.read(f.output, 8)
    old_fields = {offset: f.memory.read(old + offset, 8) for offset in (8, 24, 72, 88)}
    f.run(MOVE, holder, f.output)
    f.run(FACTORY, f.output)
    new = f.memory.read(f.output, 8)
    f.run(MOVE, holder, f.output)
    assert f.memory.read(holder, 8) == new and f.memory.read(f.output, 8) == 0
    assert f.calls_to(FREE) == [
        (old_fields[88], 128),
        (old_fields[72], 104),
        (old_fields[24], 128),
        (old_fields[8], 104),
        (old, 128),
    ]
    assert f.run(HOLDER, holder) is None
    assert f.memory.read(holder, 8) == new
    assert f.calls_to(FREE)[-1] == (new, 128)


@pytest.mark.parametrize("target", VECTORS)
def test_vector_null_skips_unbacked_capacity_and_all_resets(target):
    f = Fixture()
    header = f.alloc(8, 0)
    assert f.run(target, header) is None
    assert f.events == [("r", header, 8, 0)]


@pytest.mark.parametrize("target", VECTORS)
@pytest.mark.parametrize("extra", [0, 7, 15])
def test_vector_nonnull_masks_capacity_and_resets_after_actual_free(target, extra):
    f = Fixture()
    begin = f.alloc(16, 0)
    header = f.vector(begin, 0xBAD, begin + extra)

    def free(args):
        assert args == (begin, extra & ~7)
        assert f.memory.read(header, 8) == begin
        f.memory.write(header + 8, 8, 0xFFFF)
        return f.actual(FREE, args)

    f.effects[FREE] = free
    assert f.run(target, header) is None
    assert f.calls_to(FREE) == [(begin, extra & ~7)]
    assert f.memory.read_bytes(header, 24) == bytes(24)
    assert not [e for e in f.events if e[:3] == ("r", header + 8, 8)]
    assert [e for e in f.events if e[0] == "w"][-3:] == [
        ("w", header + offset, 8, 0) for offset in (0, 8, 16)
    ]


@pytest.mark.parametrize("target", VECTORS)
def test_vector_missing_free_preserves_all_header_words(target):
    f = Fixture()
    begin = f.alloc(8, 0)
    header = f.vector(begin, 0xABC, begin + 8)
    before = f.memory.read_bytes(header, 24)
    f.effects[FREE] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mandatory"):
        f.run(target, header)
    assert f.memory.read_bytes(header, 24) == before


@pytest.mark.parametrize("target", RANGES)
@pytest.mark.parametrize("count,size", [(0, 0), (1, 8), (511, 4088), (1 << 61, 0), (U64, U64 - 7)])
def test_range_three_arg_abi_zero_and_wrapped_bytecounts(target, count, size):
    f = Fixture()
    pointer = f.alloc(32, 0)
    if size >= 4096:
        # Explicit large-allocation representation withvalid delta8.
        pointer += 16
        f.memory.write(pointer - 8, 8, pointer - 16)
        expected = (pointer - 16, (size + 39) & U64)
    else:
        expected = (pointer, size)
    f.effects[FREE] = lambda args: None  # Trace raw arithmetic without size/backing inference.
    assert f.run(target, U64, pointer, count) is None
    assert f.calls_to(FREE) == [expected]
    assert not any(e[0] == "r" and e[1] == U64 for e in f.events)


@pytest.mark.parametrize("target", (*RANGES, *VECTORS))
@pytest.mark.parametrize("delta", [0, 31])
def test_large_valid_backpointer_current_read_and_adjusted_actual_free(target, delta):
    f = Fixture()
    base = f.alloc(64, 0)
    pointer = base + 8 + delta
    f.memory.write(pointer - 8, 8, base)
    header = f.vector(pointer, 0, pointer + 4096)
    args = (header, pointer, 512) if target in RANGES else (header,)
    f.run(target, *args)
    assert f.calls_to(FREE) == [(base, 4135)]
    assert not [e for e in f.events if e[0] == "i"]


@pytest.mark.parametrize("target", (*RANGES, *VECTORS))
@pytest.mark.parametrize("returns", [False, True])
def test_large_invalid_delta_current_watson_five_zeros_live_errorword(target, returns):
    f = Fixture()
    base = f.alloc(80, 0)
    pointer = base + 48
    f.memory.write(pointer - 8, 8, base)
    header = f.vector(pointer, 0, pointer + 4096)
    before = f.memory.read_bytes(header, 24)

    def watson(args):
        assert args == (0, 0, 0, 0, 0)
        assert len(f.active) == 1
        frame = next(iter(f.active))
        assert f.memory.read(frame, 8) == 0
        assert f.events[-2] == ("r", frame, 8, 0)
        if not returns:
            fail(args)

    f.effects[WATSON] = watson
    args = (header, pointer, 512) if target in RANGES else (header,)
    message = "outside INT3" if returns else "mandatory"
    with pytest.raises(UnresolvedReplayTaskRebuild, match=message):
        f.run(target, *args)
    assert f.memory.read_bytes(header, 24) == before
    assert not f.calls_to(FREE)
    assert f.closed[-1][1] == bytes(8) and not f.active


def test_watson_current_iat_and_current_fifth_word_after_local_write_and_iat_read():
    f = Fixture()
    base = f.alloc(80, 0)
    pointer = base + 48
    f.memory.write(pointer - 8, 8, base)
    new_target = 0xBACE51

    def change_write(address, width, value):
        if address in f.active:
            f.memory.write(WATSON_IAT, 8, new_target)
            f.memory.write(address, 8, 17)

    def change_read(address, width, value):
        if address == WATSON_IAT:
            f.memory.write(next(iter(f.active)), 8, 23)

    f.on_write, f.on_read = change_write, change_read

    def terminal(args):
        assert args == (0, 0, 0, 0, 23)
        fail(args)

    f.effects[new_target] = terminal
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mandatory"):
        f.run(RANGES[0], 0, pointer, 512)
    assert f.closed[-1][1] == (23).to_bytes(8, "little")


@pytest.mark.parametrize("target", NODES)
def test_empty_selflinked_node_sentinel_break_then_actual_free_no_header_reset(target):
    f = Fixture(nodes=0)
    header, sentinel, _, _ = f.chain(0, 0)
    assert f.run(target, header) is None
    assert f.calls_to(FREE) == [(sentinel, 104)]
    assert f.memory.read(header, 8) == sentinel
    assert ("w", sentinel, 8, 0) in f.events


@pytest.mark.parametrize("target", NODES)
def test_node_chain_actual_nested_and_outer_frees_in_source_order(target):
    f = Fixture(nodes=6)
    header, sentinel, nodes, nested = f.chain(2, 2)
    f.run(target, header)
    expected = []
    for node, (inner_sentinel, entries) in zip(nodes, nested, strict=True):
        expected.extend((entry, 24) for entry in entries)
        expected.extend([(inner_sentinel, 24), (node, 104)])
    expected.append((sentinel, 104))
    assert f.calls_to(FREE) == expected
    assert f.memory.read(header, 8) == sentinel


@pytest.mark.parametrize("budget", [0, 1, 2, 3])
def test_cumulative_node_budget_retains_tail_breaks_and_previous_iterations(budget):
    f = Fixture(nodes=budget)
    header, sentinel, nodes, nested = f.chain(2, 1)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="node-visit"):
        f.run(NODES[0], header)
    assert f.memory.read(nodes[-1], 8) == 0  # Source outer prelude always executed.
    expected = []
    if budget >= 2:
        expected = [(nested[0][1][0], 24), (nested[0][0], 24), (nodes[0], 104)]
    assert f.calls_to(FREE) == expected
    if budget in (1, 3):
        index = 0 if budget == 1 else 1
        assert f.memory.read(nested[index][1][-1], 8) == 0  # Inner prelude before refusal.
    assert not any(args == (sentinel, 104) for args in f.calls_to(FREE))


def test_nodes_hold_nexts_reload_nested_and_final_sentinels_after_callbacks():
    f = Fixture()
    header, sentinel, nodes, nested = f.chain(2, 1)
    final_sentinel, replacement_nested = f.sentinel(), f.sentinel(24)
    first, second = nodes
    old_nested, entries = nested[0]
    inner = entries[0]

    def free(args):
        pointer, _ = args
        if pointer == inner:
            f.memory.write(inner, 8, 0xBAD)  # Held next was0 after source tail break.
            f.memory.write(first + 0x30, 8, replacement_nested)
        if pointer == first:
            f.memory.write(first, 8, 0xBAD)  # Held next remains second.
            f.memory.write(header, 8, final_sentinel)
        return f.actual(FREE, args)

    f.effects[FREE] = free
    f.run(NODES[0], header)
    expected = [
        (inner, 24),
        (replacement_nested, 24),
        (first, 104),
        (nested[1][1][0], 24),
        (nested[1][0], 24),
        (second, 104),
        (final_sentinel, 104),
    ]
    assert f.calls_to(FREE) == expected
    assert (old_nested, 24) not in f.calls_to(FREE) and (sentinel, 104) not in f.calls_to(FREE)
    assert f.memory.read(old_nested, 8) == inner


def test_nodes_current_nested_header_read_occurs_after_real_vector_child():
    f = Fixture()
    header, _, nodes, old_nested = f.chain(1, 0)
    replacement = f.sentinel(24)
    payload = f.alloc(8, 0)
    f.memory.write(nodes[0] + 0x40, 8, payload)
    f.memory.write(nodes[0] + 0x50, 8, payload + 8)

    def free(args):
        if args[0] == payload:
            f.memory.write(nodes[0] + 0x30, 8, replacement)
        return f.actual(FREE, args)

    f.effects[FREE] = free
    f.run(NODES[0], header)
    assert f.calls_to(FREE)[:2] == [(payload, 8), (replacement, 24)]
    assert not any(args[0] == old_nested[0][0] for args in f.calls_to(FREE))


def test_node_cycle_refuses_at_budget_after_preceding_real_effects():
    f = Fixture(nodes=1)
    header, sentinel, nodes, nested = f.chain(1, 0)
    # An independent backed tail stub preserves sentinel.first through the break.
    tail_stub = f.alloc(8, 0)
    f.memory.write(sentinel + 8, 8, tail_stub)
    f.memory.write(nodes[0], 8, nodes[0])
    f.effects[FREE] = lambda args: None  # Keep backing live to isolate finite-cycle policy.
    with pytest.raises(UnresolvedReplayTaskRebuild, match="node-visit"):
        f.run(NODES[0], header)
    assert f.calls_to(FREE) == [(nested[0][0], 24), (nodes[0], 104)]
    assert not any(args[0] == sentinel for args in f.calls_to(FREE))


@pytest.mark.parametrize("missing", [VECTORS[2], FREE])
def test_node_mandatory_failure_preserves_prelude_and_stops_before_following_effects(missing):
    f = Fixture()
    header, _, nodes, nested = f.chain(1, 1)
    f.effects[missing] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mandatory"):
        attachment.clear_replay_player_attachment_nodes(
            f.context, header, calls=f.calls, profile=f.profile
        )
    assert f.memory.read(nodes[-1], 8) == 0
    assert f.calls_to(VECTORS[2]) == [(nodes[0] + 64,)]
    assert f.calls_to(FREE) == ([] if missing == VECTORS[2] else [(nested[0][1][0], 24)])


def test_projected_caller_uses_actual_factory_cell_move_cleanup_then_reader_refusal():
    f = Fixture()
    player = f.alloc(0x1400, 0)
    f.run(FACTORY, f.output)
    obj = f.memory.read(f.output, 8)
    f.run(MOVE, player + 0x12E0, f.output)
    assert f.run(HOLDER, f.output) is None
    assert f.memory.read(player + 0x12E0, 8) == obj
    assert f.memory.read(f.output, 8) == 0
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14134b780"):
        f.run(0x14134B780, f.memory.read(player + 0x12E0, 8), 0xDEAD, 0xFEED)
    assert f.calls_to(0x14134B780) == [(obj, 0xDEAD, 0xFEED)]


@pytest.mark.parametrize("values", [(-1, 0), (0, -1), (True, 1), (1, 1.5)])
def test_profile_requires_explicit_nonnegative_integer_budgets(values):
    with pytest.raises(ValueError, match="nonnegative integer"):
        attachment.ReplayPlayerAttachmentProfile(*values)


@pytest.mark.parametrize(
    "values",
    [
        (b"", bytes(16), bytes(8)),
        (bytes(8), bytes(8), bytes(8)),
        (bytes(8), bytes(16), bytearray(8)),
    ],
)
def test_scratch_requires_all_explicit_seed_widths(values):
    with pytest.raises(ValueError, match="8/16/8"):
        attachment.ReplayPlayerAttachmentScratch(*values)


@pytest.mark.parametrize(
    "target,arity",
    [
        (FACTORY, 1),
        (CTOR, 1),
        (MOVE, 2),
        (HOLDER, 1),
        *((x, 3) for x in RANGES),
        *((x, 1) for x in VECTORS),
        *((x, 1) for x in NODES),
    ],
)
def test_all_eleven_binding_arities_and_data_refused_before_effects(target, arity):
    f = Fixture()
    assert f.bound.call is not None
    with pytest.raises(ValueError, match="malformed"):
        f.bound.call(target, (f.subject,) * (arity + 1), None)
    with pytest.raises(ValueError, match="malformed"):
        f.bound.call(target, (f.subject,) * arity, memoryview(b""))
    assert not f.events


def test_unbound_external_is_not_a_success_default():
    f = Fixture()
    bound = attachment.bind_replay_player_attachment(
        f.context,
        ReplayTaskRebuildCalls(None),
        bind_local=f.bind_local,
        scratch=f.scratch,
        profile=f.profile,
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="142d6ba78"):
        bound.call(FACTORY, (f.output,), None)
    assert f.memory.read(f.output, 8) == 0 and not f.active
