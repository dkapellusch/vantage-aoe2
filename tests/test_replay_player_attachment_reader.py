"""Authored source-ordered controls; owned Memory and actual reused providers.

The Input service, finite replay bytes and callback mutations are authored seams.
No original game, carrier, probe or native execution is part of these controls.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_attachment as attachment
from vantage import replay_player_attachment_reader as reader
from vantage.replay_base_saved_leaves import bind_replay_base_saved_leaves
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_position import bind_replay_saved_position
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

ENTRY, INPUT, MALLOC, ALIGNED, FREE = 0x14134B780, 0xBB10, 0x142D6BA78, 0x1402A94D0, 0x142D6BAB4
FORWARD, VECTOR, PAIR, CEIL = 0x1409076B0, 0x1402BD890, 0x1408EE150, 0x142D6E453
WATSON_IAT, WATSON, IMPORT_FREE = 0x14319A060, 0xBA70, 0xBAF0
FILL_ENTRIES = (0x14126D910, 0x141345B10, 0x141345BA0)
INSERT_ENTRIES = (0x141345460, 0x141345250, 0x141345920)
U64 = (1 << 64) - 1
# Separate literal original-site/error oracle. B is raw, A is fixed forwarded.
SITES = (
    (0x14134B7F2, 0x14134B811, 0x14134B889),
    (0x14134BA31, 0x14134BA51, 0x14134C85E),
    (0x14134BB35, 0x14134BB55, 0x14134C723),
    (0x14134BCAE, 0x14134BCCD, 0x14134C613),
    (0x14134BD8F, 0, 0x14134C4E3),
    (0x14134BDEF, 0, 0x14134C3A3),
    (0x14134BE4F, 0, 0x14134C267),
    (0x14134BEB8, 0, 0x14134C133),
    (0x14134BF7F, 0x14134BF9F, 0x14134C012),
    (0x14134CA02, 0x14134CA22, 0x14134D788),
    (0x14134CB7D, 0x14134CB9D, 0x14134D5E8),
    (0x14134CC84, 0x14134CCA4, 0x14134D443),
    (0x14134CD88, 0x14134CDA8, 0x14134D307),
    (0x14134CE6A, 0, 0x14134D1B1),
    (0x14134CED1, 0x14134CEF1, 0x14134D072),
)


def payload(
    first=((3, 7, 0x7FC01234, 0x80000000, 19, (4,)),),
    second=((5, 0x3F000000, 0xBF000000, 23, (8,)),),
    *,
    counts=None,
):
    result = []

    def put(site, value, width):
        result.append((site, (value & ((1 << (8 * width)) - 1)).to_bytes(width, "little")))

    first_count, second_count = counts if counts is not None else (len(first), len(second))
    put(0x14134B7F2, first_count, 4)
    for a, b, x, y, word, elements in first:
        for site, value, width in (
            (0x14134BA31, a, 2),
            (0x14134BB35, b, 2),
            (0x14134BCAE, x, 4),
            (0x14134BD8F, y, 4),
            (0x14134BDEF, word, 2),
            (0x14134BE4F, len(elements), 4),
        ):
            put(site, value, width)
        for element in elements:
            put(0x14134BEB8, element, 2)
    put(0x14134BF7F, second_count, 4)
    for a, x, y, word, elements in second:
        for site, value, width in (
            (0x14134CA02, a, 2),
            (0x14134CB7D, x, 4),
            (0x14134CC84, y, 4),
            (0x14134CD88, word, 2),
            (0x14134CE6A, len(elements), 4),
        ):
            put(site, value, width)
        for element in elements:
            put(0x14134CED1, element, 2)
    return result


class Fixture:
    def __init__(self, chunks=(), *, records=1000, visits=10000, stores=10000):
        self.memory = ReplayMemory(max_bytes=8 << 20)
        self.subject = self.alloc(128, 0)
        self.output = self.alloc(48, 0xD7)
        self.stream = self.alloc(8, 0)
        self.table = self.alloc(32, 0)
        self.memory.write(self.stream, 8, self.table)
        self.memory.write(self.table + 24, 8, INPUT)
        self.memory.map_bytes(0x1436A0308, bytes.fromhex("0000005f"))
        self.memory.map_bytes(WATSON_IAT, WATSON.to_bytes(8, "little"))
        self.memory.map_bytes(0x143199DD0, IMPORT_FREE.to_bytes(8, "little"))
        self.context = ReplayTaskRebuildStorage(self.subject, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.imports = ReplayTaskRebuildCalls(self.terminal)
        self.primitive = self.memory.runtime_calls()
        self.atomics = ReplayUnitAIMapAtomics(None, self.xadd)
        self.events, self.active, self.closed, self.effects = [], {}, [], {}
        self.on_read = self.on_write = self.on_input = self.after_forward = None
        self.chunks, self.cursor, self.current_site, self.consumed = list(chunks), 0, 0, 0
        self.failure = None
        self.raw_results, self.destinations, self.input_events = [], [], []
        self.scratch = reader.ReplayPlayerAttachmentReaderScratch(
            b"\xa5" * 288,
            b"\xb6" * 56,
            b"\xc7" * 8,
            b"\xd8" * 16,
            b"\xe9" * 56,
            b"\xfa" * 24,
            b"\x9b" * 8,
            b"\xac" * 8,
        )
        self.profile = reader.ReplayPlayerAttachmentReaderProfile(records, visits, stores, 0x1F80)
        self.bound = reader.bind_replay_player_attachment_reader(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
            profile=self.profile,
            imports=self.imports,
        )
        self.attachment = attachment.bind_replay_player_attachment(
            self.context,
            self.calls,
            bind_local=self.bind_local,
            scratch=attachment.ReplayPlayerAttachmentScratch(
                b"\xa1" * 8, b"\xb2" * 16, b"\xc3" * 8
            ),
            profile=attachment.ReplayPlayerAttachmentProfile(10000, 10000),
            imports=self.imports,
        )
        self.saved = (
            bind_replay_saved_apply(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
            bind_replay_base_saved_leaves(
                self.context,
                self.calls,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=b"\x11" * 8,
            ),
            bind_replay_saved_result(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
            bind_replay_saved_position(
                self.context, self.calls, atomics=self.atomics, bind_local=self.bind_local
            ),
        )

    def alloc(self, size, byte=None):
        pointer = self.memory.allocate(size)
        if byte is not None:
            self.memory.fill(pointer, byte, size)
        return pointer

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

    def xadd(self, address, value):
        old = self.memory.fetch_add_u32(address, value)
        self.events.append(("atomic", address, value, old))
        return old

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

    def actual(self, target, *args):
        assert self.primitive.call is not None
        return self.primitive.call(target, args, None)

    def run(self, target, *args):
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        return self.actual(FREE if target == IMPORT_FREE else target, *args)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.effects:
            return self.effects[target](args)
        if target in reader._ARITIES:
            return self.run(target, *args)
        if target == INPUT:
            stream, result, destination, width = args
            assert stream == self.stream
            assert self.cursor < len(self.chunks), (self.cursor, width)
            site, raw = self.chunks[self.cursor]
            self.current_site = site
            self.input_events.append(len(self.events) - 1)
            assert width == len(raw)
            assert self.memory.read_bytes(result, 48) == bytes(48)
            self.raw_results.append(result)
            self.destinations.append(destination)
            self.memory.write_bytes(destination, raw)
            self.cursor += 1
            self.consumed += width
            if self.on_input:
                self.on_input(site, result, destination)
            if self.failure == (site, "B"):
                self.memory.write(result + 24, 8, 0xBAD)
            return 0xDEADBEEF  # Every source Input RAX is ignored.
        if target in (0x1416C2270, 0x14126E8A0):
            assert self.attachment.call is not None
            return self.attachment.call(target, args, data)
        if target in (FORWARD, 0x1402B9080):
            assert self.saved[0].call is not None
            value = self.saved[0].call(target, args, data)
            if target == FORWARD:
                if self.failure == (self.current_site, "A"):
                    self.memory.write(args[0] + 24, 8, 0xBAD)
                if self.after_forward:
                    self.after_forward(args)
            return value
        if target == PAIR:
            assert self.saved[1].call is not None
            return self.saved[1].call(target, args, data)
        if target in (VECTOR, 0x140900620):
            assert self.saved[2].call is not None
            return self.saved[2].call(target, args, data)
        if target in (0x140B81D60, 0x140B81E60):
            assert self.saved[3].call is not None
            return self.saved[3].call(target, args, data)
        return self.actual(target, *args)

    def initialize(self, address=None):
        assert self.attachment.call is not None
        return self.attachment.call(
            0x1416C2270, (self.subject if address is None else address,), None
        )

    def read_all(self):
        return self.run(ENTRY, self.subject, self.output, self.stream)

    def frame(self):
        return next(address for address, view in self.active.items() if len(view) == 288)

    def value(self):
        value = self.alloc(80, 0xD1)
        self.run(0x141345C30, value)
        return value + 16

    def insert(self, target, address, key):
        key_address = self.alloc(4, 0)
        self.memory.write(key_address, 4, key)
        output = self.alloc(16, 0xD7)
        assert self.run(target, address, output, key_address) == output
        return self.memory.read(output, 8), self.memory.read(output + 8, 1), output

    def keys(self, container, pair=False):
        sentinel = self.memory.read(container + 8, 8)
        node = self.memory.read(sentinel, 8)
        result = []
        while node != sentinel:
            assert len(result) < 1000
            result.append(self.memory.read(node + 16, 4 if pair else 2))
            node = self.memory.read(node, 8)
        return result

    def calls_to(self, target):
        return [event[2] for event in self.events if event[:2] == ("c", target)]


def unavailable(args):
    raise UnresolvedReplayTaskRebuild("authored missing mandatory provider")


def fnv(value, width):
    hashed = 0xCBF29CE484222325
    for byte in value.to_bytes(width, "little"):
        hashed = ((hashed ^ byte) * 0x100000001B3) & U64
    return hashed


def test_positive_two_families_use_real_containers_all15reads_and_raw_float_bits():
    chunks = payload()
    f = Fixture(chunks)
    f.initialize()
    assert f.read_all() == f.output
    assert f.cursor == 15 and f.consumed == 46
    assert f.memory.read_bytes(f.output, 48) == bytes(41) + b"\xd7" * 7
    assert f.keys(f.subject, pair=True) == [3 | 7 << 16]
    assert f.keys(f.subject + 64) == [5]
    first_head = f.memory.read(f.subject + 8, 8)
    first = f.memory.read(first_head, 8)
    assert f.memory.read(first + 24, 4) == 0x7FC01234
    assert f.memory.read(first + 28, 4) == 0x80000000
    assert f.memory.read(first + 32, 2) == 19
    assert f.keys(first + 40) == [4]
    assert set(site for site, _ in chunks) == {row[0] for row in SITES}
    frame, closed = next((address, raw) for address, raw in f.closed if len(raw) == 288)
    assert int.from_bytes(closed[0x118:0x11C], "little") == 1
    assert closed[0x11C:0x120] == (f.output >> 32).to_bytes(4, "little")
    direct_sites = {site for site, raw_error, _ in SITES if raw_error}
    for (site, _), raw_result in zip(chunks, f.raw_results, strict=True):
        if site in direct_sites:
            assert raw_result == frame + 0x78
        else:
            assert not frame <= raw_result < frame + 288
    assert all(args[0] == frame + 0x48 for args in f.calls_to(FORWARD))
    assert not f.active
    with pytest.raises(ReplayMemoryError):
        f.memory.read(frame, 1)


@pytest.mark.parametrize("counts", [(0, 0), (-1, -1), (-0x80000000, 0)])
def test_nonpositive_signed_counts_consume_only_two_headers(counts):
    f = Fixture(payload((), (), counts=counts), records=0)
    assert f.read_all() == f.output
    assert f.cursor == 2 and f.consumed == 8
    assert not f.calls_to(MALLOC)


@pytest.mark.parametrize(
    "site,branch,error",
    [
        (site, branch, raw_error if branch == "B" else error)
        for site, raw_error, error in SITES
        for branch in ("B", "A")
        if branch == "A" or raw_error
    ],
)
def test_all25_current_fixed_status_frontiers_preserve_prior_effects(site, branch, error):
    f = Fixture(payload())
    f.initialize()
    f.failure = (site, branch)
    with pytest.raises(reader.UnimplementedReplayPlayerAttachmentDiagnostic) as caught:
        f.read_all()
    assert (caught.value.source_entry, caught.value.input_site, caught.value.status) == (
        error,
        site,
        0xBAD,
    )
    assert f.current_site == site and not f.active
    assert f.memory.read_bytes(f.output, 48) == b"\xd7" * 48
    if branch == "B":
        assert not any(
            event[:2] == ("c", FORWARD) and event[2][1] == f.raw_results[-1]
            for event in f.events[f.input_events[-1] :]
        )
    else:
        current = f.events[f.input_events[-1] :]
        forwarded = [
            i
            for i, event in enumerate(current)
            if event[:2] == ("c", FORWARD) and event[2][1] == f.raw_results[-1]
        ]
        cleaned = [
            i
            for i, event in enumerate(current)
            if event[:2] == ("c", VECTOR) and event[2] == (f.raw_results[-1],)
        ]
        assert len(forwarded) == len(cleaned) == 1
        assert forwarded[0] < cleaned[0]


@pytest.mark.parametrize("target", INSERT_ENTRIES)
def test_duplicate_key_returns_existing_slot_preserving_padding_and_allocation_count(target):
    f = Fixture()
    f.initialize()
    address = (
        f.value() if target == 0x141345920 else f.subject + (64 if target == 0x141345250 else 0)
    )
    first, inserted, out = f.insert(target, address, 0x12345678)
    before = len(f.calls_to(MALLOC))
    second, duplicate, out2 = f.insert(target, address, 0x12345678)
    assert inserted == 1 and duplicate == 0 and second == first
    assert len(f.calls_to(MALLOC)) == before
    assert f.memory.read(address + 16, 8) == 1
    assert f.memory.read_bytes(out + 9, 7) == f.memory.read_bytes(out2 + 9, 7) == b"\xd7" * 7


@pytest.mark.parametrize(
    "target,pair", [(0x141345460, True), (0x141345250, False), (0x141345920, False)]
)
def test_collision_and_growth_rehash_preserve_all_keys_and_real_ceil(target, pair):
    f = Fixture()
    f.initialize()
    address = f.value() if target == 0x141345920 else f.subject + (64 if not pair else 0)
    values = []
    for value in range(500):
        hashed = fnv(((value & 0xFFFF) << 16) | (value >> 16), 4) if pair else fnv(value, 2)
        if hashed & 7 == 0:
            values.append(value)
        if len(values) == 10:
            break
    assert len(values) == 10
    for value in values:
        f.insert(target, address, value)
    assert sorted(f.keys(address, pair)) == values
    assert f.memory.read(address + 16, 8) == 10
    assert f.memory.read(address + 56, 8) >= 16
    assert f.calls_to(CEIL)
    assert f.calls_to(ALIGNED)


@pytest.mark.parametrize(
    "destination_keys,source_keys", [((1, 2, 3), (9,)), ((1,), (7, 8, 9)), ((), ())]
)
def test_copy_reuses_prefix_grows_or_frees_tail_then_rehashes(destination_keys, source_keys):
    f = Fixture()
    destination, source = f.value(), f.value()
    for value in destination_keys:
        f.insert(0x141345920, destination, value)
    for value in source_keys:
        f.insert(0x141345920, source, value)
    old_nodes = []
    head = f.memory.read(destination + 8, 8)
    node = f.memory.read(head, 8)
    while node != head:
        old_nodes.append(node)
        node = f.memory.read(node, 8)
    assert f.run(0x141345F50, destination, source) == destination
    assert sorted(f.keys(destination)) == sorted(source_keys)
    assert f.memory.read(destination + 16, 8) == len(source_keys)
    assert f.calls_to(CEIL) and f.calls_to(0x1412840B0)
    if len(destination_keys) > len(source_keys):
        assert len(f.calls_to(FREE)) >= len(destination_keys) - len(source_keys)


def test_copy_same_address_has_no_body_reads_or_local_binding():
    f = Fixture()
    address = f.value()
    f.events.clear()
    assert f.run(0x141345F50, address, address) == address
    assert f.events == []


@pytest.mark.parametrize("target", FILL_ENTRIES)
@pytest.mark.parametrize("overlap", [False, True])
def test_fill_prefetch_precedes_overlap_and_scalar_tail_reloads_current_source(target, overlap):
    f = Fixture()
    begin = f.alloc(32, 0)
    source = begin + 8 if overlap else f.alloc(8, 0)
    f.memory.write(source, 8, 11)
    reads = []

    def change_after_prefetch(address, width, value):
        if address == source and width == 8:
            reads.append(value)
            if len(reads) == 1:
                f.memory.write(source, 8, 22)

    f.on_read = change_after_prefetch
    f.run(target, begin, begin + 32, source)
    assert reads == ([11, 22, 22, 22, 22] if overlap else [11])
    assert f.memory.read_bytes(begin, 32) == (22 if overlap else 11).to_bytes(8, "little") * 4


@pytest.mark.parametrize("target", FILL_ENTRIES)
def test_reversed_fill_refuses_before_scalar_store_instead_of_succeeding(target):
    f = Fixture()
    begin = f.alloc(32, 0)
    source = f.alloc(8, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="finite"):
        f.run(target, begin + 16, begin, source)
    assert f.memory.read_bytes(begin, 32) == bytes(32)


def test_reserve_reloads_current_old_header_after_allocator_and_frees_before_publish():
    f = Fixture()
    header = f.alloc(24, 0)
    old = f.alloc(16, 0)
    replacement = f.alloc(32, 0)

    def allocate(args):
        assert args == (32,)
        f.memory.write(header, 8, old)
        f.memory.write(header + 16, 8, old + 16)
        return replacement

    f.effects[ALIGNED] = allocate
    f.run(0x141283BD0, header, 4, 0x1234)
    assert f.calls_to(0x1412879B0) == [(header, old, 2)]
    free = next(i for i, event in enumerate(f.events) if event[:2] == ("c", FREE))
    commit = next(i for i, event in enumerate(f.events) if event[:3] == ("w", header, 8))
    assert free < commit
    assert f.memory.read_bytes(replacement, 32) == (0x1234).to_bytes(8, "little") * 4
    with pytest.raises(ReplayMemoryError):
        f.memory.read(old, 1)


def test_reserve_existing_range_passes_live_source_home_to_real_fill():
    f = Fixture()
    header, words = f.alloc(24, 0), f.alloc(32, 0)
    for offset, value in ((0, words), (8, words + 32), (16, words + 32)):
        f.memory.write(header + offset, 8, value)

    def fill(args):
        assert args[:2] == (words, words + 32)
        assert f.memory.read(args[2], 8) == 17
        f.memory.write(args[2], 8, 23)
        return f.run(0x14126D910, *args)

    f.effects[0x14126D910] = fill
    f.run(0x141283BD0, header, 4, 17)
    assert f.memory.read_bytes(words, 32) == (23).to_bytes(8, "little") * 4
    assert not f.calls_to(ALIGNED)


def test_pair_insert_reads_second_then_first_and_holds_hash_while_malloc_rereads_payload():
    f = Fixture()
    f.initialize()
    key, output = f.alloc(4, 0), f.alloc(16, 0)
    original, changed = 0x00070003, 0x00090005
    f.memory.write(key, 4, original)
    key_reads = []
    f.on_read = lambda address, width, value: (
        key_reads.append((address, width)) if key <= address < key + 4 else None
    )

    def allocate(args):
        f.memory.write(key, 4, changed)
        return f.actual(MALLOC, *args)

    f.effects[MALLOC] = allocate
    assert f.run(0x141345460, f.subject, output, key) == output
    assert key_reads[:2] == [(key + 2, 2), (key, 2)]
    assert (key, 4) in key_reads
    node = f.memory.read(output, 8)
    assert f.memory.read(node + 16, 4) == changed
    table = f.memory.read(f.subject + 24, 8)
    bucket = table + (fnv(3 << 16 | 7, 4) & 7) * 16
    assert f.memory.read(bucket, 8) == node


def test_pair_rehash_reads_first_then_second_and_retains_live_fill_home():
    f = Fixture()
    f.initialize()
    node, _, _ = f.insert(0x141345460, f.subject, 0x00070003)
    reads = []
    f.on_read = lambda address, width, value: (
        reads.append((address, width)) if address in (node + 16, node + 18) else None
    )
    f.run(0x14134B200, f.subject, 8)
    assert reads[:2] == [(node + 16, 2), (node + 18, 2)]
    assert f.calls_to(0x141345BA0)


def test_watson_uses_current_fifth_home_after_current_import_read_and_retains_it():
    f = Fixture()
    base = f.alloc(5000, 0)
    pointer = base + 80
    f.memory.write(pointer - 8, 8, base)

    def mutate_fifth(address, width, value):
        if address == WATSON_IAT:
            home = next(address for address, view in f.active.items() if len(view) == 8)
            assert f.memory.read(home, 8) == 0
            f.memory.write(home, 8, 0xBEEF)

    f.on_read = mutate_fifth
    f.effects[WATSON] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson"):
        f.run(0x1412879B0, 0, pointer, 512)
    assert ("i", WATSON, (0, 0, 0, 0, 0xBEEF)) in f.events
    assert not f.calls_to(FREE)
    assert not f.active


def test_current_self_home_redirects_second_family_but_first_family_holds_initial_subject():
    f = Fixture(payload(first=((3, 7, 1, 2, 3, ()),), second=((5, 4, 5, 6, ()),)))
    f.initialize()
    other = f.alloc(128, 0)
    f.initialize(other)

    def redirect(site, result, destination):
        if site == 0x14134BCAE:
            f.memory.write(f.frame() + 0x18, 8, other)

    f.on_input = redirect
    f.read_all()
    assert f.keys(f.subject, pair=True) == [0x00070003]
    assert f.keys(f.subject + 64) == []
    assert f.keys(other + 64) == [5]


def test_current_first_count_can_shrink_after_real_cleanup_with_prior_record_retained():
    first = ((3, 7, 1, 2, 3, ()),)
    f = Fixture(payload(first, (), counts=(2, 0)))
    f.initialize()

    def cleanup(args):
        f.memory.write(f.frame() + 0x110, 4, 1)
        return f.run(0x141345E80, *args)

    f.effects[0x141345E80] = cleanup
    assert f.read_all() == f.output
    assert f.consumed == 26
    assert f.memory.read(f.subject + 16, 8) == 1


@pytest.mark.parametrize(
    "target",
    [
        FORWARD,
        VECTOR,
        PAIR,
        0x141283BD0,
        0x140B81C60,
        0x141345920,
        0x141345460,
        0x141345250,
        0x141345F50,
        0x141345E80,
        0x14126E8A0,
        CEIL,
    ],
)
def test_missing_reached_provider_refuses_without_output_success_or_faked_children(target):
    f = Fixture(payload())
    f.initialize()
    f.effects[target] = unavailable
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mandatory"):
        f.read_all()
    assert f.calls_to(target)
    assert not f.active
    assert f.memory.read_bytes(f.output, 48) == b"\xd7" * 48


def test_reached_reader_and_pointer_budgets_keep_preceding_effects():
    f = Fixture(payload(), records=0)
    f.initialize()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="record budget"):
        f.read_all()
    assert f.cursor == 1 and f.consumed == 4
    g = Fixture(stores=2)
    header = g.alloc(24, 0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="pointer-fill budget"):
        g.run(0x141283BD0, header, 4, 0xAB)
    begin = g.memory.read(header, 8)
    assert g.memory.read_bytes(begin, 16) == (0xAB).to_bytes(8, "little") * 2
    assert g.memory.read(header + 8, 8) == begin + 32


def test_zero_rehash_request_preserves_native_masked_shift_rounding():
    f = Fixture()
    f.initialize()
    f.run(0x14134B200, f.subject, 0)
    assert f.memory.read(f.subject + 56, 8) == 1
    assert f.memory.read(f.subject + 48, 8) == 0


@pytest.mark.parametrize("target", [0x141345EE0, 0x123456])
def test_diagnostic_only_and_unknown_entries_delegate_instead_of_default_success(target):
    f = Fixture()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run(target, f.subject)


def test_nonzero_shared_control_uses_actual_atomic_release_and_current_weak_vptr():
    f = Fixture(payload((), ()))
    control, first_table, second_table = f.alloc(16, 0), f.alloc(16, 0), f.alloc(16, 0)
    destroy, weak = 0xBD10, 0xBD20
    f.memory.write(control, 8, first_table)
    f.memory.write(control + 8, 4, 1)
    f.memory.write(control + 12, 4, 1)
    f.memory.write(first_table, 8, destroy)
    f.memory.write(first_table + 8, 8, 0xBAD)
    f.memory.write(second_table + 8, 8, weak)

    def shared(site, result, destination):
        if site == 0x14134B7F2:
            f.memory.write(result + 32, 8, control)

    def destroyed(args):
        assert args == (control,)
        f.memory.write(control, 8, second_table)

    f.on_input = shared
    f.effects[destroy] = destroyed
    f.effects[weak] = lambda args: None
    assert f.read_all() == f.output
    operations = [event[2:] for event in f.events if event[0] == "atomic"]
    assert operations == [(1, 1), (0xFFFFFFFF, 2), (0xFFFFFFFF, 1), (0xFFFFFFFF, 1)]
    assert f.calls_to(destroy) == f.calls_to(weak) == [(control,)]
    assert f.memory.read(control + 8, 4) == f.memory.read(control + 12, 4) == 0


def test_word_wrapper_nonzero_raw_requires_real_diagnostic_before_forwarding():
    f = Fixture(((0x1234, b"\x23\x01"),))
    destination = f.alloc(2, 0)
    f.failure = (0x1234, "B")
    f.effects[0x140900ED0] = unavailable
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mandatory"):
        f.run(0x140B81C60, f.output, 0xFEED, 0x123456789, 0xBEEF, f.stream, destination)
    assert f.memory.read_bytes(f.output, 48) == bytes(48)
    assert f.memory.read(destination, 2) == 0x123
    assert f.calls_to(0x140900ED0)[0][1:] == (0xFEED, 0x23456789, 0xBEEF)
    assert not f.calls_to(FORWARD)
    assert not f.active


def test_word_wrapper_returns_held_output_after_home_mutation_and_ignores_Input_RAX():
    f = Fixture(((0x1234, b"\x23\x01"),))
    destination = f.alloc(2, 0)

    def mutate_home(site, result, target):
        assert f.memory.read(result - 8, 8) == f.output
        f.memory.write(result - 8, 8, 0xBAD)

    f.on_input = mutate_home
    assert f.run(0x140B81C60, f.output, 0xFEED, 7, 0xBEEF, f.stream, destination) == f.output
    assert f.memory.read(destination, 2) == 0x123
    assert f.memory.read_bytes(f.output, 48) == bytes(48)
    assert len(f.calls_to(VECTOR)) == 1


def test_second_WORD_key_preserves_high_half_of_reused_first_inner_count():
    f = Fixture(payload(first=((3, 7, 1, 2, 3, ()),), second=((5, 4, 5, 6, ()),)))
    f.initialize()
    observed = []

    def mutate_count(site, result, destination):
        if site == 0x14134BE4F:
            f.memory.write(destination, 4, 0xFEED0000)
        elif site == 0x14134CA02:
            observed.append(f.memory.read(destination, 4))

    f.on_input = mutate_count
    f.read_all()
    assert observed == [0xFEED0005]
    assert f.keys(f.subject + 64) == [5]


def test_pair_insert_holds_factor_read_before_current_bucket_and_count_reads():
    f = Fixture()
    f.initialize()
    changed = False

    def factor_callback(address, width, value):
        nonlocal changed
        if address == f.subject and width == 4 and not changed:
            changed = True
            assert value == 0x3F800000
            f.memory.write(f.subject, 4, 0x3C23D70A)

    f.on_read = factor_callback
    f.insert(0x141345460, f.subject, 0x00070003)
    assert changed
    factor_at = next(i for i, e in enumerate(f.events) if e[:3] == ("r", f.subject, 4))
    next_reads = [e[1] for e in f.events[factor_at + 1 :] if e[0] == "r"]
    assert next_reads[:2] == [f.subject + 56, f.subject + 16]
    assert not f.calls_to(0x14134B200)
    assert f.memory.read(f.subject, 4) == 0x3C23D70A
