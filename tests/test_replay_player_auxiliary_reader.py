"""Authored normal-reader controls over actual engine backing and reused bodies.

The stream Input effect is an explicit authored service seam. These tests do
not run native code or implement the original diagnostic/TLS/error descendants.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_auxiliary_reader as reader
from vantage.replay_base_saved_leaves import bind_replay_base_saved_leaves
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

U64 = (1 << 64) - 1
ENTRY, INPUT, INPUT2, CALLOC, CALLOC2 = 0x1414AEA70, 0xAA10, 0xAA20, 0xCC10, 0xCC20
VERSION, IAT = 0x1440A0D94, 0x143199DC0
PAIR, VECTOR, FINAL, FREE = 0x1408EE150, 0x1402BD890, 0x140900620, 0x142D6BAB4


SOURCE_SITES = {
    0x1414AEAEA: (120, 0x1414AEAF8),
    0x1414AEC82: (1272, 0x1414AEC94),
    0x1414AEE1D: (1320, 0x1414AEE2F),
    0x1414AEF93: (1368, 0x1414AEFA5),
    0x1414AF12C: (1416, 0x1414AF13E),
    0x1414AF2DC: (1464, 0x1414AF2EE),
    0x1414AF4FD: (648, 0x1414B13D6),
    0x1414AF568: (2376, 0x1414B1273),
    0x1414AF5D7: (1752, 0x1414B05C3),
    0x1414AF658: (1512, 0x1414B0102),
    0x1414AF6B7: (1704, 0x1414B04B9),
    0x1414AF738: (1560, 0x1414B0223),
    0x1414AF797: (1656, 0x1414B0453),
    0x1414AF81C: (1608, 0x1414B0343),
    0x1414AF8C2: (2328, 0x1414B1143),
    0x1414AF925: (2280, 0x1414B1013),
    0x1414AF984: (2232, 0x1414B0F13),
    0x1414AF9E7: (2184, 0x1414B0DF3),
    0x1414AFA46: (2136, 0x1414B0CE9),
    0x1414AFAA9: (2088, 0x1414B0C23),
    0x1414AFB08: (2040, 0x1414B0B0B),
    0x1414AFB7B: (1944, 0x1414B0998),
    0x1414AFBDC: (1896, 0x1414B08C8),
    0x1414AFC3D: (1848, 0x1414B07F8),
    0x1414AFC9F: (1800, 0x1414B06E4),
    0x1414AFD08: (1992, 0x1414B09F8),
    0x1414AFDB2: (168, 0x1414B3353),
    0x1414AFE11: (792, 0x1414B3236),
    0x1414AFE8C: (696, 0x1414B23A3),
    0x1414AFF19: (2424, 0x1414B1DF1),
    0x1414AFF78: (2616, 0x1414B2283),
    0x1414AFFF9: (2472, 0x1414B1F23),
    0x1414B0058: (2568, 0x1414B2163),
    0x1414B00DD: (2520, 0x1414B2043),
    0x1414B15C6: (744, 0x1414B3123),
    0x1414B1635: (3144, 0x1414B2FF3),
    0x1414B1694: (3096, 0x1414B2ED3),
    0x1414B16F7: (3048, 0x1414B2DB3),
    0x1414B1756: (3000, 0x1414B2CB3),
    0x1414B17B9: (2952, 0x1414B2B93),
    0x1414B1818: (2904, 0x1414B2A68),
    0x1414B188B: (2712, 0x1414B25E3),
    0x1414B18EA: (2664, 0x1414B24C4),
    0x1414B1956: (2760, 0x1414B2753),
    0x1414B19BF: (2808, 0x1414B2884),
    0x1414B1A28: (2856, 0x1414B29A3),
    0x1414B1AD4: (312, 0x1414B4B73),
    0x1414B1B64: (264, 0x1414B49D3),
    0x1414B1BEB: (216, 0x1414B4863),
    0x1414B1C4A: (888, 0x1414B4753),
    0x1414B1CC2: (840, 0x1414B40A6),
    0x1414B1D3D: (3240, 0x1414B3D86),
    0x1414B1DC7: (3192, 0x1414B3C86),
    0x1414B3509: (3336, 0x1414B3FA3),
    0x1414B356B: (3288, 0x1414B3E83),
    0x1414B35DA: (3384, 0x1414B4213),
    0x1414B3642: (3432, 0x1414B4367),
    0x1414B36AA: (3480, 0x1414B44D6),
    0x1414B3712: (3528, 0x1414B4642),
    0x1414B37BE: (600, 0x1414B6802),
    0x1414B385E: (552, 0x1414B665F),
    0x1414B38FB: (504, 0x1414B64AF),
    0x1414B39AB: (360, 0x1414B5755),
    0x1414B3A6D: (936, 0x1414B5211),
    0x1414B3AD8: (1080, 0x1414B5666),
    0x1414B3B65: (984, 0x1414B5333),
    0x1414B3BD0: (1032, 0x1414B5563),
    0x1414B3C61: (3576, 0x1414B5443),
    0x1414B4D7B: (456, 0x1414B636F),
    0x1414B4E1F: (408, 0x1414B6233),
    0x1414B4E8A: (1224, 0x1414B6133),
    0x1414B4EF9: (1176, 0x1414B6003),
    0x1414B4F64: (3816, 0x1414B5F03),
    0x1414B4FC7: (3768, 0x1414B5DE6),
    0x1414B5026: (1128, 0x1414B5CD6),
    0x1414B509E: (3624, 0x1414B589F),
    0x1414B510A: (3672, 0x1414B5A13),
    0x1414B5173: (3720, 0x1414B5B67),
}


def chunks(version, counts=(1, 1, 1, 1), subcounts=(1, 1, 1)):
    """Independent source field order, raw byte widths and threshold gates."""
    result = []

    def add(site, size, value=None):
        if value is None:
            raw = bytes([(len(result) % 239) + 1]) * size
        else:
            raw = value.to_bytes(size, "little", signed=value < 0)
        result.append((site, raw))

    for site, value in ((0x1414AEAEA, counts[0]), (0x1414AEC82, counts[1])):
        add(site, 1, value)
    add(
        0x1414AEE1D if version >= 0x43E666 else 0x1414AEF93,
        2 if version >= 0x43E666 else 1,
        counts[2],
    )
    add(0x1414AF12C, 1, counts[3])
    if version >= 0x963D7:
        add(0x1414AF2DC, 4)
    old, text = (40, 3) if version < 0xA6147 else (100, 10)
    modern = version >= 0xAD70A
    for _ in range(max(0, counts[0])):
        add(0x1414AF4FD, 4)
        add(0x1414AF568, 1)
        if modern:
            sites = (
                (0x1414AF5D7, 0x1414AF658),
                (0x1414AF6B7, 0x1414AF738),
                (0x1414AF797, 0x1414AF81C),
            )
        else:
            sites = (
                (0x1414AF8C2, 0x1414AF925),
                (0x1414AF984, 0x1414AF9E7),
                (0x1414AFA46, 0x1414AFAA9),
            )
        for number, (count_site, data_site) in enumerate(sites):
            add(count_site, 1, subcounts[number])
            if not modern or subcounts[number]:
                add(data_site, 4 * (subcounts[number] if modern else old))
        add(0x1414AFB08, 0x54)
        if version >= 0x963D7:
            for site, size in (
                (0x1414AFB7B, 1),
                (0x1414AFBDC, text),
                (0x1414AFC3D, text),
                (0x1414AFC9F, 1),
            ):
                add(site, size)
        if version >= 0x9828F:
            add(0x1414AFD08, 4)
    for _ in range(max(0, counts[1])):
        add(0x1414AFDB2, 4)
        add(0x1414AFE11, 1)
        sites = (
            ((0x1414AFE8C, 0x1414AFF19), (0x1414AFF78, 0x1414AFFF9), (0x1414B0058, 0x1414B00DD))
            if modern
            else (
                (0x1414B15C6, 0x1414B1635),
                (0x1414B1694, 0x1414B16F7),
                (0x1414B1756, 0x1414B17B9),
            )
        )
        for number, (count_site, data_site) in enumerate(sites):
            add(count_site, 1, subcounts[number])
            if not modern or subcounts[number]:
                add(data_site, 4 * (subcounts[number] if modern else old))
        add(0x1414B1818, 0x54)
        if version >= 0x963D7:
            add(0x1414B188B, 1)
            add(0x1414B18EA, 5)
        for threshold, site, size in (
            (0x96B85, 0x1414B1956, 5),
            (0x9828F, 0x1414B19BF, 4),
            (0x9E8F5, 0x1414B1A28, 4),
        ):
            if version >= threshold:
                add(site, size)
    for _ in range(max(0, counts[2])):
        for site, size in (
            (0x1414B1AD4, 4),
            (0x1414B1B64, 1),
            (0x1414B1BEB, 4),
            (0x1414B1C4A, 0x54),
        ):
            add(site, size)
        if version >= 0x963D7:
            add(0x1414B1CC2, 4)
            add(0x1414B1D3D if modern else 0x1414B3509, 1, subcounts[0])
            if not modern or subcounts[0]:
                add(0x1414B1DC7 if modern else 0x1414B356B, 4 * (subcounts[0] if modern else old))
        for threshold, site in (
            (0x975C2, 0x1414B35DA),
            (0x98000, 0x1414B3642),
            (0x9828F, 0x1414B36AA),
            (0x9E8F5, 0x1414B3712),
        ):
            if version >= threshold:
                add(site, 4)
    for _ in range(max(0, counts[3])):
        for site, size in ((0x1414B37BE, 4), (0x1414B385E, 1), (0x1414B38FB, 4)):
            add(site, size)
        sites = (
            ((0x1414B39AB, 0x1414B3A6D), (0x1414B3AD8, 0x1414B3B65), (0x1414B3BD0, 0x1414B3C61))
            if modern
            else (
                (0x1414B4D7B, 0x1414B4E1F),
                (0x1414B4E8A, 0x1414B4EF9),
                (0x1414B4F64, 0x1414B4FC7),
            )
        )
        for number, (count_site, data_site) in enumerate(sites):
            add(count_site, 1, subcounts[number])
            if not modern or subcounts[number]:
                add(data_site, 4 * (subcounts[number] if modern else old))
        add(0x1414B5026, 0x54)
        for threshold, site in (
            (0x963D7, 0x1414B509E),
            (0x975C2, 0x1414B510A),
            (0x9828F, 0x1414B5173),
        ):
            if version >= threshold:
                add(site, 4)
    return result


class Fixture:
    def __init__(self, version=0x44E666, counts=(1, 1, 1, 1), subcounts=(1, 1, 1), *, budget=33532):
        self.memory = ReplayMemory(max_bytes=8 << 20)
        self.address, self.output, self.stream, self.table = (
            self.memory.allocate(72),
            self.memory.allocate(48),
            self.memory.allocate(8),
            self.memory.allocate(32),
        )
        self.primitive = self.memory.runtime_calls(calloc_target=CALLOC)
        assert self.primitive.call is not None
        self.primitive.call(0x142D6E3B7, (self.address, 0, 72), None)
        self.memory.fill(self.output, 0xC7, 48)
        self.memory.write(self.stream, 8, self.table)
        self.memory.write(self.table + 24, 8, INPUT)
        self.memory.map_bytes(VERSION, version.to_bytes(4, "little"))
        self.memory.map_bytes(IAT, CALLOC.to_bytes(8, "little"))
        self.memory.map_bytes(0x143199DD0, FREE.to_bytes(8, "little"))
        self.pending = chunks(version, counts, subcounts)
        self.expected = list(self.pending)
        self.events, self.inputs, self.allocations, self.closed = [], [], [], []
        self.frame, self.active = 0, False
        self.on_read = self.on_write = self.on_input = self.on_calloc = None
        self.effects = {}
        self.failure_site = None
        self.input_return = None
        self.context = ReplayTaskRebuildStorage(self.address, self.read, self.write)
        self.calls, self.imports = (
            ReplayTaskRebuildCalls(self.dispatch),
            ReplayTaskRebuildCalls(self.terminal),
        )
        self.atomics = ReplayUnitAIMapAtomics(None, self.atomic)
        self.routes = {}
        # The pair-release leaf and full/vector Result bodies are actual reused ports.
        self.routes[PAIR] = bind_replay_base_saved_leaves(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=bytes(8),
        )
        self.routes[0x14090D270] = bind_replay_saved_pair(
            self.context, self.calls, atomics=self.atomics
        )
        self.routes[0x1402B9080] = bind_replay_saved_apply(
            self.context, self.calls, atomics=self.atomics, imports=self.imports
        )
        finalized = bind_replay_saved_result(
            self.context, self.calls, atomics=self.atomics, imports=self.imports
        )
        for target in (VECTOR, 0x1402BD7F0, FINAL):
            self.routes[target] = finalized
        string = bind_replay_saved_string(self.context, self.calls, imports=self.imports)
        for target in (0x1402A88A0, 0x1402A8920):
            self.routes[target] = string
        self.scratch = reader.ReplayPlayerAuxiliaryReaderScratch(b"\xa5" * 3864)
        self.profile = reader.ReplayPlayerAuxiliaryReaderProfile(budget)
        self.bound = reader.bind_replay_player_auxiliary_reader(
            self.context,
            self.calls,
            imports=self.imports,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=self.scratch,
            profile=self.profile,
        )

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

    def atomic(self, address, value):
        prior = self.memory.fetch_add_u32(address, value)
        self.events.append(("a", address, value, prior))
        return prior

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.frame, self.active = address, True
            try:
                yield address
            finally:
                self.closed.append(bytes(view))
                self.active = False

    def result(self, address, *, status=0, control=0, vector=0, count=0, capacity=0):
        for offset, value in (
            (0, vector),
            (8, vector + 32 * count),
            (16, vector + 32 * capacity),
            (24, status),
            (32, control),
        ):
            self.memory.write(address + offset, 8, value)
        self.memory.write(address + 40, 1, 0)

    def control(self, *, strong=1, weak=1, destroy=0xD0, dispose=0xD8):
        address, table = self.memory.allocate(16), self.memory.allocate(16)
        for offset, value, width in ((0, table, 8), (8, strong, 4), (12, weak, 4)):
            self.memory.write(address + offset, width, value)
        self.memory.write(table, 8, destroy)
        self.memory.write(table + 8, 8, dispose)
        return address, table

    def terminal(self, target, args, data):
        self.events.append(("i", target, args))
        if target in self.effects:
            return self.effects[target](args)
        if target in (CALLOC, CALLOC2):
            self.allocations.append((target, args))
            assert self.primitive.call is not None
            allocation = self.primitive.call(CALLOC, args, data)
            if self.on_calloc:
                self.on_calloc(args, allocation)
            return allocation
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def dispatch(self, target, args, data):
        self.events.append(("c", target, args))
        if target in self.effects:
            return self.effects[target](args)
        if target in (INPUT, INPUT2):
            assert self.active and data is None
            stream, result, destination, size = args
            assert stream == self.stream
            site, payload = self.pending.pop(0)
            assert SOURCE_SITES[site][0] == result - self.frame
            assert self.memory.read_bytes(result, 48) == bytes(48)
            assert size == len(payload), (hex(site), size, len(payload))
            self.memory.write_bytes(destination, payload)
            self.result(result, status=0xBAD if site == self.failure_site else 0)
            self.inputs.append((site, target, result, destination, size, payload))
            if self.on_input:
                self.on_input(site, result, destination, size)
            return self.input_return
        if target in self.routes:
            bound = self.routes[target]
            assert bound is not None and bound.call is not None
            return bound.call(target, args, data)
        assert self.primitive.call is not None
        return self.primitive.call(target, args, data)

    def run(self):
        assert self.bound.call is not None
        return self.bound.call(ENTRY, (self.address, self.output, self.stream), None)


def test_four_empty_families_keep_actual_zero_count_allocations_and_output_padding():
    f = Fixture(counts=(0, 0, 0, 0), budget=0)
    assert f.run() == f.output
    assert not f.pending
    assert [args for target, args in f.allocations] == [(0, 0xA8), (0, 0xA0), (0, 0x88), (0, 0xA0)]
    assert all(f.memory.read(f.address + off, 8) for off in (8, 24, 40, 56))
    assert f.memory.read_bytes(f.output, 41) == bytes(41)
    assert f.memory.read_bytes(f.output + 41, 7) == b"\xc7" * 7
    assert not f.active
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.frame, 1)


@pytest.mark.parametrize(
    "version",
    [
        0x90000,
        0x963D6,
        0x963D7,
        0x96B84,
        0x96B85,
        0x975C1,
        0x975C2,
        0x97FFF,
        0x98000,
        0x9828E,
        0x9828F,
        0x9E8F4,
        0x9E8F5,
        0xA6146,
        0xA6147,
        0xAD709,
        0xAD70A,
        0x43E665,
        0x43E666,
        0x44E666,
    ],
)
def test_all_four_families_actual_bytes_and_every_version_boundary(version):
    f = Fixture(version)
    assert f.run() == f.output and not f.pending
    assert [(row[0], row[5]) for row in f.inputs] == f.expected
    assert [args for target, args in f.allocations if args[1] != 4] == [
        (1, 0xA8),
        (1, 0xA0),
        (1, 0x88),
        (1, 0xA0),
    ]
    for _site, _target, _result, destination, size, payload in f.inputs[5:]:
        assert f.memory.read_bytes(destination, size) == payload


@pytest.mark.parametrize("version", [0x90000, 0xA6147, 0x44E666])
def test_zero_subcounts_legacy_still_reads_fixed_arrays_modern_skips(version):
    f = Fixture(version, subcounts=(0, 0, 0))
    f.run()
    assert not f.pending
    pointed = [args for target, args in f.allocations if args[1] == 4]
    assert pointed == (
        []
        if version >= 0xAD70A
        else [(40 if version < 0xA6147 else 100, 4)] * (9 if version < 0x963D7 else 10)
    )


@pytest.mark.parametrize("returned", [None, -7, True, 1 << 80])
def test_Input_RAX_is_ignored_and_fixed_local_status_controls(returned):
    f = Fixture(counts=(0, 0, 0, 0), budget=0)
    f.input_return = returned
    assert f.run() == f.output and not f.pending


@pytest.mark.parametrize("site", sorted(SOURCE_SITES))
def test_every_nonzero_status_stops_at_exact_original_entry_without_mark_or_cleanup(site):
    version = 0x44E666 if site in {value[0] for value in chunks(0x44E666)} else 0xA6147
    f = Fixture(version)
    f.failure_site = site
    before_output = f.memory.read_bytes(f.output, 48)
    with pytest.raises(reader.UnimplementedReplayPlayerAuxiliaryDiagnostic) as error:
        f.run()
    assert error.value.source_entry == SOURCE_SITES[site][1]
    assert error.value.input_site == site and error.value.status == 0xBAD
    offset = SOURCE_SITES[site][0]
    assert f.closed[-1][offset + 40] == 0
    assert f.memory.read_bytes(f.output, 48) == before_output
    assert f.events[-1][:3] == ("r", f.frame + offset + 24, 8)
    assert not f.active
    with pytest.raises(ReplayMemoryError):
        f.memory.read(f.frame + offset, 1)


def test_unreached_results_and_logical_holes_are_seeded_not_blanket_zeroed():
    f = Fixture()
    f.failure_site = 0x1414AEAEA
    with pytest.raises(reader.UnimplementedReplayPlayerAuxiliaryDiagnostic):
        f.run()
    closed = f.closed[-1]
    assert closed[8:120] == b"\xa5" * 112
    assert closed[168:] == b"\xa5" * (3864 - 168)
    assert [(row[1] - f.frame, row[2]) for row in f.events if row[0] == "w"] == [
        (0, 8),
        (120, 16),
        (136, 16),
        (152, 16),
    ]


def test_signed_negative_third_count_allocates_raw_u64_before_current_signed_gate():
    f = Fixture(counts=(0, 0, -1, 0), budget=0)
    f.run()
    assert [args for target, args in f.allocations] == [
        (0, 0xA8),
        (0, 0xA0),
        (U64, 0x88),
        (0, 0xA0),
    ]
    assert f.memory.read(f.address + 0x28, 8) == 0  # Actual engine calloc overflow null.


def test_current_IAT_is_reloaded_and_terminal_token_can_equal_owned_reader():
    f = Fixture(counts=(0, 0, 0, 0), budget=0)

    def first(args, allocation):
        if args[1] == 0xA8:
            f.memory.write(IAT, 8, CALLOC2)

    f.on_calloc = first
    f.run()
    assert [target for target, args in f.allocations] == [CALLOC, CALLOC2, CALLOC2, CALLOC2]
    g = Fixture(counts=(0, 0, 0, 0), budget=0)
    g.memory.write(IAT, 8, ENTRY)

    def current(args):
        assert len(args) == 2
        return g.memory.calloc(*args)

    g.effects[ENTRY] = current
    assert g.run() == g.output


def test_pointed_allocation_publishes_to_current_header_after_actual_calloc():
    f = Fixture(counts=(1, 0, 0, 0), subcounts=(1, 0, 0))
    record = {}

    def allocated(args, allocation):
        if args[1] == 4 and not record:
            old = f.memory.read(f.address + 8, 8)
            replacement = f.memory.calloc(1, 0xA8)
            f.memory.move(replacement, old, 0xA8)
            f.memory.write(f.address + 8, 8, replacement)
            record.update(old=old, replacement=replacement, allocation=allocation)

    f.on_calloc = allocated
    f.run()
    assert f.memory.read(record["old"] + 0x10, 8) == 0
    assert f.memory.read(record["replacement"] + 0x10, 8) == record["allocation"]
    assert next(row[3] for row in f.inputs if row[0] == 0x1414AF658) == record["allocation"]


def test_Input_target_is_captured_before_pointer_read_and_uses_held_header_base():
    f = Fixture(counts=(1, 0, 0, 0), subcounts=(1, 0, 0))
    replacement_table = f.memory.allocate(32)
    f.memory.write(replacement_table + 24, 8, INPUT2)
    changes = {}

    def capture(address, width, value):
        if address == f.table + 24 and f.pending[0][0] == 0x1414AF658 and not changes:
            old = f.memory.read(f.address + 8, 8)
            replacement = f.memory.calloc(1, 0xA8)
            f.memory.move(replacement, old, 0xA8)
            pointed = f.memory.calloc(1, 4)
            f.memory.write(old + 0x10, 8, pointed)
            f.memory.write(f.address + 8, 8, replacement)
            f.memory.write(f.stream, 8, replacement_table)
            changes.update(pointed=pointed)

    f.on_read = capture
    f.run()
    row = next(row for row in f.inputs if row[0] == 0x1414AF658)
    assert (row[1], row[3]) == (INPUT, changes["pointed"])
    assert next(row[1] for row in f.inputs if row[0] == 0x1414AF6B7) == INPUT2


def test_current_loop_home_and_count_keep_field_offset_separate_from_held_stride():
    f = Fixture(counts=(3, 0, 0, 0), subcounts=(0, 0, 0))
    header = f.pending[:5]
    rows = f.pending[5:]
    length = len(rows) // 3
    f.pending = header + rows[:length] + rows[length * 2 :]

    def mutate(site, result, destination, size):
        if site == 0x1414AFD08 and sum(row[0] == site for row in f.inputs) == 1:
            f.memory.write(f.frame + 8, 4, 1)

    f.on_input = mutate
    f.run()
    base = f.memory.read(f.address + 8, 8)
    destinations = [row[3] for row in f.inputs if row[0] == 0x1414AF4FD]
    assert destinations == [base, base + 2 * 0xA8]
    assert f.memory.read_bytes(base + 0xA8, 0xA8) == bytes(0xA8)


def test_current_count_can_extend_loop_with_new_actual_backing():
    f = Fixture(counts=(2, 0, 0, 0), subcounts=(0, 0, 0))
    f.pending[0] = (0x1414AEAEA, b"\x01")
    changes = {}

    def mutate(site, result, destination, size):
        if site == 0x1414AFD08 and not changes:
            old = f.memory.read(f.address + 8, 8)
            new = f.memory.calloc(2, 0xA8)
            f.memory.move(new, old, 0xA8)
            f.memory.write(f.address + 8, 8, new)
            f.memory.write(f.address, 1, 2)
            changes["new"] = new

    f.on_input = mutate
    f.run()
    assert len([row for row in f.inputs if row[0] == 0x1414AF4FD]) == 2
    assert [args for target, args in f.allocations if args[1] == 0xA8] == [(1, 0xA8)]


def test_saved_legacy_count_home_is_current_for_later_allocations_and_fixed_reads():
    f = Fixture(0x90000, counts=(1, 0, 0, 0))
    data_sites = {0x1414AF925, 0x1414AF9E7, 0x1414AFAA9}
    f.pending = [(site, b"" if site in data_sites else raw) for site, raw in f.pending]
    number = []

    def mutate(args, allocation):
        if args[1] == 4:
            number.append(args)
            if len(number) == 2:
                f.memory.write(f.frame + 0x68, 8, 0)

    f.on_calloc = mutate
    f.run()
    assert number == [(40, 4), (40, 4), (0, 4)]
    assert all(row[4] == 0 for row in f.inputs if row[0] in data_sites)


def test_skipped_version_branches_retain_held_value_after_global_read_mutation():
    f = Fixture(0x90000, counts=(0, 1, 0, 0))
    changed = []

    def mutate(address, width, value):
        if address == VERSION and f.inputs and f.inputs[-1][0] == 0x1414B1818 and not changed:
            f.memory.write(VERSION, 4, 0x44E666)
            changed.append(True)

    f.on_read = mutate
    f.run()
    assert changed and not f.pending
    assert not any(
        row[0] in (0x1414B188B, 0x1414B1956, 0x1414B19BF, 0x1414B1A28) for row in f.inputs
    )


@pytest.mark.parametrize("site", [0x1414AEAEA, 0x1414AEC82, 0x1414B1AD4, 0x1414B37BE])
def test_actual_cleanup_variants_release_control_and_use_current_weak_vptr(site):
    f = Fixture()
    control, _ = f.control()
    _replacement, new_table = f.control(destroy=0xE0, dispose=0xE8)

    def destroy(args):
        assert args == (control,) and f.active
        f.memory.write(control, 8, new_table)

    f.effects[0xD0], f.effects[0xE8] = destroy, lambda args: None

    def supply(chosen, result, destination, size):
        if chosen == site:
            f.memory.write(result + 32, 8, control)

    f.on_input = supply
    f.run()
    assert f.memory.read(control + 8, 4) == f.memory.read(control + 12, 4) == 0
    assert ("c", 0xE8, (control,)) in f.events


@pytest.mark.parametrize("site,same_control", [(0x1414B37BE, False), (0x1414B1AD4, True)])
def test_family4_weak_cleanup_reloads_mutable_home_but_family3_holds_R12(site, same_control):
    f = Fixture()
    original, _ = f.control()
    replacement, _ = f.control(destroy=0xE0, dispose=0xE8)

    def destroy(args):
        assert args == (original,)
        f.memory.write(f.frame, 8, replacement)

    f.effects[0xD0] = destroy
    f.effects[0xD8] = f.effects[0xE8] = lambda args: None

    def supply(chosen, result, destination, size):
        if chosen == site:
            f.memory.write(result + 32, 8, original)

    f.on_input = supply
    if same_control:
        # Restore source stride home before the later current stride read.
        def restore(address, width, value):
            if address == VERSION and f.inputs[-1][0] == 0x1414B1CC2:
                f.memory.write(f.frame, 8, 0)

        f.on_read = restore
    f.run()
    assert f.memory.read(original + 12, 4) == (0 if same_control else 1)
    assert f.memory.read(replacement + 12, 4) == (1 if same_control else 0)


def test_real_full_Result_cleanup_destroys_SSO_and_frees_while_window_is_live():
    f = Fixture(counts=(0, 0, 0, 0), budget=0)
    vector = f.memory.allocate(32)
    f.memory.fill(vector, 0xA5, 32)
    f.memory.write_bytes(vector, b"abc\0")
    f.memory.write(vector + 16, 8, 3)
    f.memory.write(vector + 24, 8, 15)

    def supply(site, result, destination, size):
        if site == 0x1414AEC82:
            f.result(result, vector=vector, count=1, capacity=1)

    def free(args):
        assert f.active and args == (vector, 32)
        assert f.memory.read(vector, 1) == 0 and f.memory.read(vector + 16, 8) == 0
        f.memory.free(vector)

    f.on_input, f.effects[FREE] = supply, free
    f.run()
    assert ("c", 0x1402A8920, (vector,)) in f.events
    with pytest.raises(ReplayMemoryError):
        f.memory.read(vector, 1)


@pytest.mark.parametrize("target", [INPUT, PAIR, VECTOR, FINAL, CALLOC])
def test_missing_reached_effects_refuse_without_synthesizing_completion(target):
    f = Fixture(counts=(0, 0, 0, 0), budget=0)

    def missing(args):
        raise UnresolvedReplayTaskRebuild(f"actual{target:x} unavailable")

    f.effects[target] = missing
    before = f.memory.read_bytes(f.output, 48)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"actual{target:x}"):
        f.run()
    assert f.memory.read_bytes(f.output, 48) == before
    assert not f.active


def test_budget_and_mutated_counter_nonwrap_domain_refuse_at_declared_boundary():
    f = Fixture(counts=(1, 0, 0, 0), budget=0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="budget"):
        f.run()
    assert f.memory.read(f.address + 8, 8)
    g = Fixture(counts=(1, 0, 0, 0), subcounts=(0, 0, 0))

    def mutate(site, result, destination, size):
        if site == 0x1414AFD08:
            g.memory.write(g.frame + 8, 4, 0xFFFFFFFF)

    g.on_input = mutate
    with pytest.raises(UnresolvedReplayTaskRebuild, match="nonwrap"):
        g.run()
    assert g.memory.read(g.address + 8, 8)


def test_unknown_delegation_retains_data_and_owned_arity_refuses_before_local_binding():
    f = Fixture(counts=(0, 0, 0, 0))
    view = memoryview(bytearray(3))
    seen = []

    def delegate(target, args, data):
        seen.append((target, args, data))
        return 19

    bound = reader.bind_replay_player_auxiliary_reader(
        f.context,
        ReplayTaskRebuildCalls(delegate),
        imports=f.imports,
        atomics=f.atomics,
        bind_local=f.bind_local,
        scratch=f.scratch,
        profile=f.profile,
    )
    assert bound.call is not None
    assert bound.call(0xABC, (7, 8), view) == 19
    assert seen == [(0xABC, (7, 8), view)] and seen[0][2] is view
    with pytest.raises(ValueError, match="malformed"):
        bound.call(ENTRY, (1, 2), None)
    assert not f.events and not f.active


@pytest.mark.parametrize("seed", [b"", bytes(3863), bytes(3865), bytearray(3864)])
def test_explicit_window_seed_required(seed):
    with pytest.raises(ValueError, match="3864"):
        reader.ReplayPlayerAuxiliaryReaderScratch(seed)


@pytest.mark.parametrize("budget", [-1, 33533, True])
def test_explicit_finite_profile_required(budget):
    with pytest.raises(ValueError, match="budget"):
        reader.ReplayPlayerAuxiliaryReaderProfile(budget)


def test_missing_inline_atomic_provider_has_no_scalar_fallback():
    f = Fixture()
    control, _ = f.control()

    def supply(site, result, destination, size):
        if site == 0x1414B1AD4:
            f.memory.write(result + 32, 8, control)

    f.on_input = supply
    f.bound = reader.bind_replay_player_auxiliary_reader(
        f.context,
        f.calls,
        imports=f.imports,
        atomics=ReplayUnitAIMapAtomics(None, None),
        bind_local=f.bind_local,
        scratch=f.scratch,
        profile=f.profile,
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        f.run()
    assert f.memory.read(control + 8, 4) == 1
    assert f.memory.read(control + 12, 4) == 1
    assert f.closed[-1][SOURCE_SITES[0x1414B1AD4][0] + 40] == 1
    assert f.memory.read_bytes(f.output, 48) == b"\xc7" * 48


def test_missing_current_free_import_leaves_vector_uncommitted_after_prior_success():
    f = Fixture(counts=(0, 0, 0, 0), budget=0)
    vector = f.memory.calloc(1, 32)

    def supply(site, result, destination, size):
        if site == 0x1414AEC82:
            f.result(result, vector=vector, capacity=1)

    f.on_input = supply
    f.memory.write(0x143199DD0, 8, 0xEEFF)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="eeff"):
        f.run()
    offset = SOURCE_SITES[0x1414AEC82][0]
    assert int.from_bytes(f.closed[-1][offset : offset + 8], "little") == vector
    assert f.closed[-1][offset + 40] == 1
    assert f.memory.read_bytes(f.output, 48) == b"\xc7" * 48


def literal_third_threshold_protocol(version):
    """Literal source protocol independent of the general chunks() oracle.

    B1C7B/JL3592: below963D7 no7c/count18/array20 reads or pointedcalloc.
    At/above: DWORD7c then freshAD70A selects legacyBYTE18/fixed40DWORDs.
    """
    protocol = [
        (0x1414AEAEA, b"\0"),
        (0x1414AEC82, b"\0"),
        (0x1414AEF93, b"\1"),
        (0x1414AF12C, b"\0"),
    ]
    if version >= 0x963D7:
        protocol.append((0x1414AF2DC, b"\x44" * 4))
    protocol.extend(
        [
            (0x1414B1AD4, b"\x11" * 4),
            (0x1414B1B64, b"\x22"),
            (0x1414B1BEB, b"\x33" * 4),
            (0x1414B1C4A, b"\x55" * 0x54),
        ]
    )
    if version >= 0x963D7:
        protocol.extend(
            [(0x1414B1CC2, b"\x66" * 4), (0x1414B3509, b"\1"), (0x1414B356B, b"\x77" * 160)]
        )
    return protocol


@pytest.mark.parametrize("version,byte_count", [(0x963D6, 97), (0x963D7, 266), (0x963D8, 266)])
def test_third_threshold_literal_source_trace_and_actual_allocations(version, byte_count):
    f = Fixture(version, counts=(0, 0, 1, 0))
    f.pending = literal_third_threshold_protocol(version)
    expected = list(f.pending)
    assert f.run() == f.output and not f.pending
    assert [(item[0], item[5]) for item in f.inputs] == expected
    assert sum(item[4] for item in f.inputs) == byte_count
    allocations = [(0, 0xA8), (0, 0xA0), (1, 0x88)]
    if version >= 0x963D7:
        allocations.append((40, 4))
    allocations.append((0, 0xA0))
    assert [args for target, args in f.allocations] == allocations
    base = f.memory.read(f.address + 0x28, 8)
    if version < 0x963D7:
        assert f.memory.read(base + 0x18, 1) == f.memory.read(base + 0x20, 8) == 0


@pytest.mark.parametrize(
    "version,pointed,total_bytes",
    [
        (0x963D6, 9, 1817),
        (0x963D7, 10, 2004),
        (0x963D8, 10, 2004),
    ],
)
def test_all_four_families_threshold_totals_are_source_derived(version, pointed, total_bytes):
    f = Fixture(version)
    f.run()
    assert not f.pending
    assert len(f.allocations) == pointed + 4
    assert len([args for target, args in f.allocations if args[1] == 4]) == pointed
    assert sum(item[4] for item in f.inputs) == total_bytes


def test_skipped_third_gate_reloads_CURRENT_stride_home_into_R12_before_join():
    f = Fixture(0x963D6, counts=(0, 0, 1, 0))
    f.pending = literal_third_threshold_protocol(0x963D6)
    control, _ = f.control(strong=2)

    def supplied(site, result, destination, size):
        if site == 0x1414B1B64:
            f.memory.write(result + 32, 8, control)
            f.memory.write(f.frame, 8, 0x88)

    f.on_input = supplied
    f.run()
    assert not f.pending and f.memory.read(control + 8, 4) == 1
    # R12 was clobbered by register-held control cleanup, then b3592 reloads88h.
    assert int.from_bytes(f.closed[-1][:8], "little") == 0x110
    assert len(f.allocations) == 4


def test_entered_third_gate_does_not_skip_legacy_pair_when_version_drops_after7c():
    f = Fixture(0x963D7, counts=(0, 0, 1, 0))
    f.pending = literal_third_threshold_protocol(0x963D7)

    def drop(site, result, destination, size):
        if site == 0x1414B1CC2:
            f.memory.write(VERSION, 4, 0x90000)

    f.on_input = drop
    f.run()
    assert not f.pending
    assert [item[0] for item in f.inputs][-3:] == [0x1414B1CC2, 0x1414B3509, 0x1414B356B]
    assert (CALLOC, (40, 4)) in f.allocations


def test_skipped_third_gate_cannot_enter_pair_after_global_changes_but_tail_is_current():
    f = Fixture(0x963D6, counts=(0, 0, 1, 0))
    f.pending = literal_third_threshold_protocol(0x963D6)
    tail = [
        (0x1414B35DA, b"\x81" * 4),
        (0x1414B3642, b"\x82" * 4),
        (0x1414B36AA, b"\x83" * 4),
        (0x1414B3712, b"\x84" * 4),
    ]
    f.pending.extend(tail)
    changed = []

    def change(address, width, value):
        if address == VERSION and f.inputs and f.inputs[-1][0] == 0x1414B1C4A and not changed:
            f.memory.write(VERSION, 4, 0x44E666)
            changed.append(True)

    f.on_read = change
    f.run()
    assert changed and not f.pending
    assert [(item[0], item[5]) for item in f.inputs][-4:] == tail
    assert not any(
        item[0] in (0x1414B1CC2, 0x1414B1D3D, 0x1414B3509, 0x1414B356B) for item in f.inputs
    )
    assert len(f.allocations) == 4 and sum(item[4] for item in f.inputs) == 113
