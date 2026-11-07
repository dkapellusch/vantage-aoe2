"""Base Player caller controls with explicit test-only descendant effects.

These tests import the ordinary production module. Their small byte carrier
and opaque child fixtures exercise the authored caller; they establish no
native, production Memory, current Player/World or complete replay parity.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage import replay_player_base_construction as PORT
from vantage.replay_player_construction_support import (
    ReplayPlayerSupportFloatingCalls,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

U64 = (1 << 64) - 1


class Carrier:
    """Finite test-only byte storage with live local views and reached hooks."""

    def __init__(self):
        self.cells = {}
        self.locals = {}
        self.events = []
        self.hook = None
        self.next_allocation = 0x500000
        self.calls = []
        self.inputs = []
        self.markers = []
        self.input_values = {}
        self.extra = {}
        self.world_count = 0
        self.next_status = 0
        self.refuse = None
        self.s = 0x10000
        self.out = 0x20000
        self.stream = 0x30000
        self.frame = 0x900000
        self.map(self.s, 0x700, 0xA3)
        self.map(self.out, 48)
        self.map(self.stream, 8)
        self.map(0x31000, 32)
        self.map(0x40000, 4)
        self.put(self.stream, 8, 0x31000)
        self.put(0x31018, 8, 0xABC0)
        for address, width, value in (
            (0x1440A0D94, 4, 0x44E666),
            (0x143DAE278, 4, 6),
            (0x1436A02F8, 4, 0x3F800000),
            (0x1436A02E4, 4, 0x40000000),
            (0x1432ED700, 4, 0x41147AE1),
            (0x1440A0EE0, 1, 11),
            (0x1440A0EE1, 1, 22),
            (0x1440A0EE2, 1, 33),
            (0x143199DC0, 8, 0xCCC0),
            (0x143199DD0, 8, 0xDDD0),
        ):
            self.map(address, width)
            self.put(address, width, value)
        self.context = ReplayTaskRebuildStorage(self.s, self.read, self.write)
        self.effects = ReplayTaskRebuildCalls(self.effect)
        self.terminal = ReplayTaskRebuildCalls(self.imported)
        self.atomics = ReplayUnitAIMapAtomics(None, self.fetch_add)
        self.floating = ReplayPlayerSupportFloatingCalls(self.marker)

    def map(self, address, width, byte=0):
        for index in range(width):
            self.cells[(address + index) & U64] = byte

    def put(self, address, width, value):
        raw = (value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")
        for index, byte in enumerate(raw):
            target = address + index & U64
            for begin, view in self.locals.items():
                if begin <= target < begin + len(view):
                    view[target - begin] = byte
                    break
            else:
                assert target in self.cells, f"unmapped write{target:x}"
                self.cells[target] = byte

    def get(self, address, width):
        result = bytearray()
        for index in range(width):
            target = address + index & U64
            for begin, view in self.locals.items():
                if begin <= target < begin + len(view):
                    result.append(view[target - begin])
                    break
            else:
                if target not in self.cells:
                    raise UnresolvedReplayTaskRebuild(f"unbacked fixture byte{target:x}")
                result.append(self.cells[target])
        return int.from_bytes(result, "little")

    def read(self, address, width):
        value = self.get(address, width)
        self.events.append(["read", address, width, value])
        if self.hook:
            self.hook("read", address, width, value)
        return value

    def write(self, address, width, value):
        self.put(address, width, value)
        self.events.append(["write", address, width, value])
        if self.hook:
            self.hook("write", address, width, value)

    def allocate(self, size):
        result = self.next_allocation
        self.next_allocation += max(size, 1) + 64
        self.map(result, max(size, 1), 0xC7)
        return result

    def zero_result(self, result):
        self.put(result, 48, 0)
        if self.next_status:
            self.put(result + 24, 8, self.next_status)
            self.next_status = 0

    def imported(self, target, args, data):
        assert data is None
        self.calls.append([target, list(args)])
        if self.refuse == target:
            raise UnresolvedReplayTaskRebuild(f"explicit refused import{target:x}")
        if target in self.extra:
            return self.extra[target](args)
        if target == 0xCCC0:
            count, width = args
            result = self.allocate(count * width)
            self.put(result, count * width, 0)
            return result
        if target == 0xDDD0:
            return None
        raise UnresolvedReplayTaskRebuild(f"unbound test import{target:x}")

    def effect(self, target, args, data):
        assert data is None
        self.calls.append([target, list(args)])
        if self.refuse == target:
            raise UnresolvedReplayTaskRebuild(f"explicit refused child{target:x}")
        if target in self.extra:
            return self.extra[target](args)
        if target in (0x142D6BA78, 0x142D6C268, 0x1402A94D0):
            return self.allocate(args[0])
        if target == 0xABC0:
            _, result, destination, width = args
            self.inputs.append([destination, width])
            self.write(destination, width, self.input_values.get(destination, 0))
            self.zero_result(result)
            return result
        if target == 0x140991CE0:
            destination, source = args
            self.put(source + 40, 1, 1)
            self.put(destination + 24, 16, self.get(source + 24, 16))
            self.put(destination + 40, 1, 0)
            return destination
        if target == 0x14090D270:
            self.put(args[0], 16, self.get(args[1], 16))
            return args[0]
        if target == 0x1402B9080:
            assert args[2] == 0, "fixture Result vector has no concrete nonempty policy"
            return args[0]
        if target == 0x142D6E3B7:
            self.put(args[0], args[2], int.from_bytes(bytes([args[1] & 255]) * args[2], "little"))
            return args[0]
        if target in (0x142D6E3B1, 0x142D6E3DB):
            self.put(args[0], args[2], self.get(args[1], args[2]))
            return args[0]
        if target == 0x1402DBEF0:
            header, pointer, size, capacity = args
            self.put(header, 8, pointer)
            self.put(header + 8, 8, pointer + size)
            self.put(header + 16, 8, pointer + capacity)
            return None
        if target == 0x141603EF0:
            return self.world_count
        if target == 0x140C4DDE0:
            header, count, source = args
            pointer = self.allocate(count * 4)
            for index in range(count):
                self.put(pointer + index * 4, 4, self.get(source, 4))
            for offset, value in (
                (0, pointer),
                (8, pointer + count * 4),
                (16, pointer + count * 4),
            ):
                self.put(header + offset, 8, value)
            return None
        if target in (
            0x140D07EE0,
            0x140DAF040,
            0x140B81E60,
            0x140B81D60,
            0x141711C20,
            0x141712290,
            0x141712390,
        ):
            output, _, _, _, _, destination = args
            width = 1 if target in (0x140D07EE0, 0x140DAF040) else 4
            self.write(destination, width, self.input_values.get(destination, 0))
            self.zero_result(output)
            return output
        if target in (0x140A1BDF0, 0x140A1CF00, 0x140A1D990):
            self.zero_result(args[1])
            return args[1]
        if target == 0x140E33410:
            self.zero_result(args[0])
            return args[0]
        if target == 0x1409076B0:
            self.put(args[0], 48, self.get(args[1], 48))
            return args[0]
        if target == 0x141712AE0:
            self.put(args[0], 8, 0)
            return args[0]
        if target in (0x141712B50, 0x140C2AE90, 0x14115D200, 0x141143DF0):
            return args[0]
        if target in (0x140F6A4B0, 0x140F6BCE0):
            return 0
        if target in (
            0x1408EE150,
            0x1402BD7F0,
            0x140900620,
            0x140900ED0,
            0x1417394D0,
            0x14174A0C0,
            0x14174A2C0,
            0x140A1B220,
            0x140A1A7E0,
            0x140A15B60,
            0x1416607B0,
            0x140B53800,
            0x141711BF0,
            0x141727C80,
            0x140FDDCE0,
        ):
            return None
        raise UnresolvedReplayTaskRebuild(f"unbound test child{target:x}")

    def fetch_add(self, address, add):
        old = self.read(address, 4)
        self.write(address, 4, old + add & 0xFFFFFFFF)
        return old

    def marker(self, target, invocation):
        assert target == 0x14162CD70
        self.markers.append(
            [invocation.output, invocation.label, invocation.xmm3_u32, invocation.expected_u8]
        )
        self.zero_result(invocation.output)
        return invocation.output

    @contextmanager
    def binding(self, view):
        assert self.frame not in self.locals
        self.locals[self.frame] = view
        try:
            yield self.frame
        finally:
            del self.locals[self.frame]

    @contextmanager
    def phase(self, seed=0):
        with self.binding(memoryview(bytearray([seed] * 0x4770))):
            yield PORT._PlayerConstruction(
                self.context,
                self.effects,
                self.terminal,
                self.atomics,
                self.floating,
                self.s,
                self.out,
                self.stream,
                self.frame,
                0x41147AE1,
            )

    def whole(self, bound=False, seed=0):
        kwargs = dict(
            calls=self.effects,
            atomics=self.atomics,
            bind_local=self.binding,
            scratch=bytes([seed] * 0x4770),
            floating=self.floating,
            imports=self.terminal,
        )
        args = (self.s, self.out, self.stream, 0x60000, 0x40000)
        if bound:
            calls = PORT.bind_replay_saved_base_player(self.context, **kwargs)
            return calls.call(0x141713F70, args, None)
        return PORT.construct_replay_saved_base_player(self.context, *args, **kwargs)


def require_refusal(operation, text):
    try:
        operation()
    except (UnresolvedReplayTaskRebuild, ValueError) as error:
        assert text in str(error), str(error)
        return
    raise AssertionError("expected reached refusal")


@pytest.mark.parametrize(
    "version,bound",
    [
        pytest.param(0xA0000, False, id="whole-a0000-direct"),
        pytest.param(0xA0000, True, id="whole-a0000-bound"),
        pytest.param(0xB828F, False, id="whole-b828f-direct"),
        pytest.param(0xB828F, True, id="whole-b828f-bound"),
        pytest.param(0xBA666, False, id="whole-ba666-direct"),
        pytest.param(0xBA666, True, id="whole-ba666-bound"),
        pytest.param(0xBF333, False, id="whole-bf333-direct"),
        pytest.param(0xBF333, True, id="whole-bf333-bound"),
        pytest.param(0xC51EB, False, id="whole-c51eb-direct"),
        pytest.param(0xC51EB, True, id="whole-c51eb-bound"),
        pytest.param(0xC8000, False, id="whole-c8000-direct"),
        pytest.param(0xC8000, True, id="whole-c8000-bound"),
        pytest.param(0xCA666, False, id="whole-ca666-direct"),
        pytest.param(0xCA666, True, id="whole-ca666-bound"),
        pytest.param(0xCC28F, False, id="whole-cc28f-direct"),
        pytest.param(0xCC28F, True, id="whole-cc28f-bound"),
        pytest.param(0xD0000, False, id="whole-d0000-direct"),
        pytest.param(0xD0000, True, id="whole-d0000-bound"),
        pytest.param(0x140F5C, False, id="whole-140f5c-direct"),
        pytest.param(0x140F5C, True, id="whole-140f5c-bound"),
        pytest.param(0x190A3D, False, id="whole-190a3d-direct"),
        pytest.param(0x190A3D, True, id="whole-190a3d-bound"),
        pytest.param(0x1A30A3, False, id="whole-1a30a3-direct"),
        pytest.param(0x1A30A3, True, id="whole-1a30a3-bound"),
        pytest.param(0x3D0000, False, id="whole-3d0000-direct"),
        pytest.param(0x3D0000, True, id="whole-3d0000-bound"),
        pytest.param(0x42B333, False, id="whole-42b333-direct"),
        pytest.param(0x42B333, True, id="whole-42b333-bound"),
        pytest.param(0x44E666, False, id="whole-44e666-direct"),
        pytest.param(0x44E666, True, id="whole-44e666-bound"),
    ],
)
def test_saved_player_zero_count_versions(version, bound):
    c = Carrier()
    c.put(0x1440A0D94, 4, version)
    returned = c.whole(bound=bound, seed=0xA3)
    assert returned == c.s and not c.locals
    assert c.get(c.s + 0x5DC, 1) == 0
    assert c.get(c.s + 0x5B0, 44) == 0
    assert len(c.markers) == 7
    assert all(row[2] == 0x41147AE1 for row in c.markers)


def test_first_marker_returned_status_cleaned():
    c = Carrier()
    c.next_status = 0x77
    assert c.whole() == c.s
    assert len(c.markers) == 1 and not c.locals
    assert c.get(c.out + 24, 8) == 0x77
    assert c.calls[-1][0] == 0x1402BD7F0


def test_first_array_refusal_preserves_prefix():
    c = Carrier()
    c.refuse = 0x141712B50
    require_refusal(c.whole, "explicit refused child141712b50")
    assert c.get(c.s, 8) == 0x1432F47D0 and not c.locals
    assert c.get(c.s + 0x648, 4) == 0xA3A3A3A3


def test_current_index_after_prefix():
    c = Carrier()
    c.put(0x40000, 4, 1)

    def late_index(kind, address, width, value):
        if kind == "write" and address == c.s + 0x6CC:
            c.put(0x40000, 4, 99)

    c.hook = late_index
    assert c.whole() == c.s and c.get(c.s + 0x648, 4) == 99


def test_held_marker_xmm6_current_byte_and_partial_home():
    c = Carrier()
    with c.phase(0xA3) as p:
        p.marker(first=True)
        c.put(0x1432ED700, 4, 0x7F800001)
        c.put(0x1440A0EE0, 1, 77)
        p.marker()
        assert [row[2:] for row in c.markers] == [[0x41147AE1, 11], [0x41147AE1, 77]]
        assert c.get(c.frame + 0x21, 7) == int.from_bytes(bytes([0xA3]) * 7, "little")


def test_legacy_refresh_only_after_entered_group():
    c = Carrier()
    c.put(0x1440A0D94, 4, 0xCC28F)
    with c.phase() as p:

        def change_legacy_version(kind, address, width, value):
            if kind == "write" and address == c.frame + 0xB8 and width == 4:
                c.put(0x1440A0D94, 4, 0x1A30A3)

        c.hook = change_legacy_version
        p.legacy_groups()
        assert c.inputs == [[c.frame + 0xB8, 4], [c.frame + 0xB8, 4]]


def test_relation_iterator_held_current_frame_end():
    c = Carrier()
    c.world_count = 2
    c.map(0x64000, 2)
    c.put(c.s + 0x180, 8, 0x64000)
    c.put(c.s + 0x188, 8, 0x64002)
    c.put(c.s + 0x190, 8, 0x64002)
    with c.phase() as p:

        def shorten_relation_end(kind, address, width, value):
            if kind == "write" and address == 0x64000 and width == 1:
                c.put(c.frame + 0xC0, 8, 0x64001)

        c.hook = shorten_relation_end
        p.relations()
        assert [item for item in c.inputs if 0x64000 <= item[0] < 0x64002] == [[0x64000, 1]]


def test_relation_selected_target_held_before_version():
    c = Carrier()
    for offset in (0x180, 0x188, 0x190):
        c.put(c.s + offset, 8, 0)
    c.put(0x1440A0D94, 4, 0x3D0000)
    with c.phase() as p:

        def change_selected_after_gate(kind, address, width, value):
            if kind == "read" and address == 0x1440A0D94:
                c.put(0x31018, 8, 0xFED0)

        c.hook = change_selected_after_gate
        require_refusal(p.relations, "unbound test childfed0")
        assert len(c.inputs) == 1 and c.inputs[0][1] == 0
        assert c.calls[-1][0] == 0xFED0


def test_default_held_table_partial_highword_ordered_cipher():
    c = Carrier()
    c.map(0x65000, 32, 0x55)
    c.map(0x66000, 32, 0x66)
    c.put(c.s + 0x90, 4, 0)
    c.put(c.s + 0x98, 8, 0x65000)
    with c.phase(0xA3) as p:

        def change_default_table(kind, address, width, value):
            if kind == "write" and address == c.frame + 0x38 and width == 4:
                c.put(c.s + 0x98, 8, 0x66000)

        c.hook = change_default_table
        p.encoded_default(0, 0, 0x3F800000)
        raw = 0xA3A3A3A33F800000
        a, b, d, e = PORT._CIPHER
        expected = (((raw ^ a) + b) & U64) ^ d ^ e
        assert c.get(0x65000, 8) == expected and c.get(0x66000, 8) == 0x6666666666666666


def test_legacy_held_ax_before_current_local_word():
    c = Carrier()
    c.map(0x67000, 0x1000)
    c.put(c.s + 0x90, 4, 0xDA)
    c.put(c.s + 0x98, 8, 0x67000)
    a, b, d, e = PORT._CIPHER
    raw = 0x1122334455667788
    c.put(0x676C8, 8, (((raw ^ a) + b) & U64) ^ d ^ e)
    with c.phase() as p:
        changed = False

        def mutate_decoded_local(kind, address, width, value):
            nonlocal changed
            if not changed and kind == "write" and address == c.frame + 0x38 and width == 8:
                changed = True
                c.put(address, 8, 0x9999)

        c.hook = mutate_decoded_local
        p.legacy_resources()
        writes = [row for row in c.events if row[:3] == ["write", c.frame + 0x38, 4]]
        assert writes[0][3] == 0x7788


@pytest.mark.parametrize(
    "version",
    [
        pytest.param(0x3C0000, id="positive-601-resource-full-phase-3c0000"),
        pytest.param(0x44E666, id="positive-601-resource-full-phase-44e666"),
    ],
)
def test_positive_resource_storage_raw_words(version):
    a, b, d, e = PORT._CIPHER
    c = Carrier()
    c.map(0x60000, 0x118)
    c.map(0x61000, 8)
    c.map(0x62000, 0x32)
    c.put(c.s + 8, 8, 0x60000)
    c.put(0x60110, 8, 0x61000)
    c.put(0x61000, 8, 0x62000)
    c.put(c.s + 0x90, 4, 2)
    c.put(0x1440A0D94, 4, version)
    first_word = 0
    if version == 0x44E666:
        first_word = 0x7FA00001
        c.input_values[c.next_allocation] = (0x80000000 << 32) | first_word
    with c.phase(0xA3) as p:
        p.resources()
        assert c.get(c.s + 0x90, 4) == 601
        reindex = [row for row in c.calls if row[0] == 0x140FDDCE0]
        assert len(reindex) == int(version < 0x3D0000)
        table = c.get(c.s + 0x98, 8)
        raw = 0xA3A3A3A300000000 | first_word
        assert c.get(table, 8) == ((((raw ^ a) + b) & U64) ^ d ^ e)
        if first_word:
            raw = 0xA3A3A3A380000000
            assert c.get(table + 8, 8) == ((((raw ^ a) + b) & U64) ^ d ^ e)


def test_auxiliary_alias_manual_current_destination_each_word():
    c = Carrier()
    c.map(0x68000, 32, 0x88)
    c.put(c.s + 0x588, 8, c.s + 0x588)
    c.put(c.s + 0x90, 4, 4)
    source = c.next_allocation
    words = [11, 22, 33, 44]
    c.input_values[source] = int.from_bytes(
        b"".join(v.to_bytes(4, "little") for v in words), "little"
    )
    with c.phase() as p:
        c.put(c.frame + 0xB8, 4, 4)
        changed = False

        def change_auxiliary_destination(kind, address, width, value):
            nonlocal changed
            if not changed and kind == "write" and address == c.s + 0x588 and width == 4:
                changed = True
                c.put(c.s + 0x588, 8, 0x68000)

        c.hook = change_auxiliary_destination
        p.copy_auxiliary(4)
        assert c.get(0x68004, 12) == int.from_bytes(
            b"".join(v.to_bytes(4, "little") for v in words[1:]), "little"
        )
        assert c.get(0x68000, 4) == 0x88888888


def test_secondary_metadata_refusal_after_outputzero_and_processed():
    c = Carrier()
    c.refuse = 0x140900ED0
    with c.phase(0xA3) as p:
        c.put(c.frame + 0xE8, 48, 0)
        c.put(c.frame + 0x100, 8, 77)
        require_refusal(lambda: p.secondary(0x20C, 0x1432F4BA0), "explicit refused child140900ed0")
        assert c.get(c.frame + 0x40, 48) == 0
        assert c.get(c.frame + 0x110, 1) == 1
        assert not any(row[0] == 0x1409076B0 for row in c.calls)


def test_inline_control_current_second_vptr_and_real_atomics():
    c = Carrier()
    for address, width in ((0x69000, 16), (0x6A000, 16), (0x6B000, 16)):
        c.map(address, width)
    c.put(0x69000, 8, 0x6A000)
    c.put(0x69008, 4, 1)
    c.put(0x6900C, 4, 1)
    c.put(0x6A000, 8, 0x1111)
    c.put(0x6B008, 8, 0x2222)
    c.extra[0x1111] = lambda args: c.put(args[0], 8, 0x6B000)
    c.extra[0x2222] = lambda args: None
    with c.phase() as p:
        c.put(c.frame + 0x60, 8, 0x69000)
        p.inline_cleanup(0x40)
        assert [row[0] for row in c.calls] == [0x1111, 0x2222, 0x1402BD7F0]
        assert c.get(0x69008, 8) == 0


@pytest.mark.parametrize(
    "version",
    [
        pytest.param(0x190A3D, id="whole-positive-all-counted-normal-190a3d"),
        pytest.param(0x44E666, id="whole-positive-all-counted-normal-44e666"),
    ],
)
def test_whole_positive_saved_player_counts(version):
    c = Carrier()
    c.world_count = 2
    c.map(0x60000, 0x118)
    c.map(0x61000, 8)
    c.map(0x62000, 0x32)
    c.put(0x60110, 8, 0x61000)
    c.put(0x61000, 8, 0x62000)
    c.put(0x1440A0D94, 4, version)
    c.input_values.update(
        {
            c.s + 0x90: 2,
            c.s + 0x240: 2,
            c.s + 0x48C: 2,
            c.frame + 0xB8: 2,
            c.frame + 0xC0: 0xFFFFFFFE,
        }
    )
    assert c.whole(bound=True, seed=0xA3) == c.s
    assert c.get(c.s + 0x90, 4) == 601
    assert c.get(c.s + 0x2A0, 8) == 2 and c.get(c.s + 0x2A8, 16) == (2 << 64) | 2
    assert len([row for row in c.calls if row[0] == 0x140B53800]) == 2
    assert len([row for row in c.inputs if row[0] == c.frame + 0xB8]) == (
        6 if version == 0x190A3D else 4
    )


def test_actual_marker_rax_fixed_raw_cleanup():
    c = Carrier()
    c.map(0x70000, 48)
    c.put(0x70018, 8, 0x77)
    with c.phase() as p:

        def alternative_marker(target, invocation):
            c.zero_result(invocation.output)
            return 0x70000

        p.floating = ReplayPlayerSupportFloatingCalls(alternative_marker)
        try:
            p.marker(first=True, manual=True, cleanup="inline")
        except PORT._ReturnedStatus:
            pass
        else:
            raise AssertionError("actual alternative marker RAX status was dropped")
        assert c.get(c.out + 24, 8) == 0x77
        assert c.calls[-1] == [0x1402BD7F0, [c.frame + 0x40]]


def test_actual_typed_rax_fixed_local_cleanup_stack5_stack6():
    c = Carrier()
    c.map(0x70000, 48)
    c.put(0x70018, 8, 0x66)
    with c.phase() as p:

        def alternative_typed(args):
            c.zero_result(args[0])
            c.put(args[5], 4, 0xAABBCCDD)
            return 0x70000

        c.extra[0x141711C20] = alternative_typed
        try:
            p.typed(0x141711C20, 0x212, 0x1432F4BB4, c.frame + 0xC0)
        except PORT._ReturnedStatus:
            pass
        else:
            raise AssertionError("actual alternative typed RAX status was dropped")
        assert c.get(c.out + 24, 8) == 0x66
        assert c.calls[-1] == [0x140900620, [c.frame + 0x40]]
        assert c.get(c.frame + 0x28, 8) == c.frame + 0xC0
        assert c.get(c.frame + 0x20, 8) == c.stream


def test_secondary_forward_rax_ignored_fixed_local_consumed():
    c = Carrier()
    c.map(0x70000, 48)
    c.put(0x70018, 8, 0x77)
    with c.phase() as p:
        p.zero_result(0xE8)

        def alternative_forward(args):
            c.put(args[0], 48, 0)
            return 0x70000

        c.extra[0x1409076B0] = alternative_forward
        p.secondary(0x21B, 0x1432F4BC0)
        assert c.get(c.out + 24, 8) == 0
        assert [row for row in c.calls if row[0] == 0x140991CE0][-1][1][1] == c.frame + 0x40


def test_current_iat_target_alias_routed_terminally():
    c = Carrier()
    c.put(0x143199DC0, 8, 0x141712B50)
    c.extra[0x141712B50] = lambda args: 0x1234
    with c.phase() as p:
        assert p.imported(0x143199DC0, 3, 4, result=True) == 0x1234
        assert c.calls == [[0x141712B50, [3, 4]]]


def test_last_marker_error_skips_final_success_reset():
    c = Carrier()
    original_marker = c.marker

    def last_marker_error(target, invocation):
        if len(c.markers) == 6:
            c.next_status = 0x55
        return original_marker(target, invocation)

    c.floating = ReplayPlayerSupportFloatingCalls(last_marker_error)
    assert c.whole() == c.s and c.get(c.s + 0x5DC, 1) == 0xA3
    assert c.get(c.out + 24, 8) == 0x55 and not c.locals


def test_binder_arity_data_pre_effect_refusals():
    c = Carrier()
    bound = PORT.bind_replay_saved_base_player(
        c.context,
        c.effects,
        atomics=c.atomics,
        bind_local=c.binding,
        scratch=bytes(0x4770),
        floating=c.floating,
        imports=c.terminal,
    )
    require_refusal(lambda: bound.call(0x141713F70, (c.s,), None), "malformed")
    require_refusal(lambda: bound.call(0x141713F70, (c.s,) * 5, memoryview(b"x")), "malformed")
    assert not c.events and not c.calls


def test_current_civ_destring_returned_status_cleanup_before_exit():
    c = Carrier()

    def string_error(args):
        c.zero_result(args[1])
        c.put(args[1] + 24, 8, 0x77)

    c.extra[0x140A1BDF0] = string_error
    assert c.whole() == c.s
    assert c.get(c.out + 24, 8) == 0x77 and not c.locals
    assert c.calls[-1] == [0x140A1B220, [c.frame + 0xD0]]
    assert c.get(c.s + 0x5DC, 1) == 0xA3


@pytest.mark.parametrize(
    "returned",
    [
        pytest.param(False, id="negative-world-count-length-frontier-returned-False"),
        pytest.param(True, id="negative-world-count-length-frontier-returned-True"),
    ],
)
def test_negative_world_count_refuses_at_length_boundary(returned):
    c = Carrier()
    c.world_count = 0xFFFFFFFF
    for offset in (0x180, 0x188, 0x190):
        c.put(c.s + offset, 8, 0)
    if returned:
        c.extra[0x1402DBEA0] = lambda args: None
    with c.phase() as p:
        require_refusal(
            p.relations, "length error returned" if returned else "unbound test child1402dbea0"
        )
        assert c.get(c.frame + 0x30, 8) == U64
        assert c.get(c.frame + 0xC0, 8) == (1 << 63) - 1
        assert not c.inputs
