"""Source-derived direct-read fixtures with actual owned Input/Result implementations.

Other descendants have explicit finite test effects; these tests establish the
caller contract, not the original implementation or wire grammar of a child.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_base_saved import (
    bind_replay_saved_base,
    read_replay_saved_base,
    resolve_replay_saved_base_owner,
)
from vantage.replay_base_saved_support import bind_replay_base_saved_support
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

U64, U32 = (1 << 64) - 1, (1 << 32) - 1
VERSION, INPUT, INPUT2 = 0x1440A0D94, 0xC01, 0xC02
KEY = 0x774A063B3D17506C
# Independent frozen source fixtures: result-slot offset, destination kind and
# offset, width. Only the final payload is dynamically selected by the caller.
SITES = (
    (0xE0, False, -0x78, 1),  # 1
    (0x110, False, -0x7C, 2),  # 2
    (0x140, False, -0x7C, 2),  # 3
    (0x170, False, -0x74, 4),  # 4
    (0x1A0, False, -0x38, 4),  # 5
    (0x1D0, True, 0x188, 1),  # 6
    (0x230, True, 0x189, 1),  # 7
    (0x260, True, 0x18A, 1),  # 8
    (0x290, True, 0x18B, 1),  # 9
    (0x2C0, True, 0x8, 4),  # 10
    (0x2F0, True, 0xE, 1),  # 11
    (0x320, False, -0x34, 4),  # 12
    (0x350, False, -0x30, 4),  # 13
    (0x380, False, -0x2C, 4),  # 14
    (0x3B0, True, 0x158, 2),  # 15
    (0x3E0, True, 0x15A, 2),  # 16
    (0x410, True, 0x15C, 2),  # 17
    (0x440, True, 0x15E, 2),  # 18
    (0x470, False, -0x4C, 1),  # 19
    (0x4A0, True, 0x160, 2),  # 20
    (0x4D0, True, 0x168, 4),  # 21
    (0xFB0, False, -0x58, 2),  # 22
    (0x500, False, -0x54, 2),  # 23
    (0xFE0, False, -0x44, 4),  # 24
    (0x530, True, 0x18C, 4),  # 25
    (0x560, False, 0xDC, 4),  # 26
    (0x590, True, 0xD, 1),  # 27
    (0x5C0, True, 0x165, 1),  # 28
    (0x5F0, False, -0x7C, 2),  # 29
    (0x620, True, 0x190, 4),  # 30
    (0x650, True, 0x1C5, 1),  # 31
    (0x680, False, -0x28, 4),  # 32
    (0x6B0, False, -0x28, 4),  # 33
    (0x6E0, False, -0x40, 4),  # 34
    (0x710, False, -0x40, 4),  # 35
    (0x740, False, -0x40, 4),  # 36
    (0x770, False, 0xD0, 4),  # 37
    (0x7A0, False, -0x24, 4),  # 38
    (0x7D0, False, -0x24, 4),  # 39
    (0x800, False, -0x50, 4),  # 40
    (0x830, False, 0xD4, 4),  # 41
    (0x860, False, -0x50, 4),  # 42
    (0x890, False, -0x3C, 4),  # 43
    (0x8C0, False, 0xD8, 4),  # 44
    (0x8F0, True, 0x210, 4),  # 45
    (0x920, True, 0x214, 4),  # 46
    (0x950, True, 0x1C7, 1),  # 47
    (0x980, True, 0x1C6, 1),  # 48
    (0x9B0, False, -0x60, 1),  # 49
    (0x9E0, False, -0x5E, 1),  # 50
    (0xA10, False, -0x5F, 1),  # 51
    (0xA70, False, -0x5D, 1),  # 52
    (0xAD0, False, -0x5C, 1),  # 53
    (0xB60, False, -0x7C, 2),  # 54
    (0xBC0, False, -0x7C, 2),  # 55
    (0xC20, False, -0x7C, 2),  # 56
    (0xC80, True, 0x198, 4),  # 57
    (0xCB0, True, 0x294, 1),  # 58
    (0xCE0, True, 0x290, 4),  # 59
    (0xD10, True, 0x2C8, 2),  # 60
    (0xD40, True, 0x1E8, 2),  # 61
    (0xDD0, True, 0x1C9, 1),  # 62
    (0xE00, True, 0x1CA, 1),  # 63
    (0xE30, True, 0x1CB, 1),  # 64
    (0xE60, True, 0x295, 1),  # 65
    (0xE90, True, 0x2D0, 4),  # 66
    (0xEC0, True, 0x2D4, 4),  # 67
    (0xEF0, True, 0x162, 2),  # 68
    (0xF20, True, 0x16C, 4),  # 69
    (0xF50, True, 0x30, 4),  # 70
    (0xF80, False, -0x48, 4),  # 71
    (0x200, 0, 0x0, 0),  # 72
)


def plan(version, *, maps=0, old_count=0, elements=0, masters=(0, 0), dynamic=(0, 0)):
    signed = version if version < 1 << 31 else version - (1 << 32)
    present = set(range(1, 73))

    def remove(condition, *sites):
        if not condition:
            present.difference_update(sites)

    remove(signed >= 0x7170A, 8)
    remove(signed < 0xB947A, 19)
    remove(signed >= 0x420000, 22, 23, 24)
    remove((version - 0xCEB85) & U32 <= 0x15147B, 26)
    remove(signed >= 0x9D999, 28)
    remove(signed >= 0xC8CCC, 29)
    remove(signed >= 0xC6B85, 30)
    remove(signed < 0xAD999, 32, 33, 40, 41)
    remove(version == 0x6FDB2, *range(34, 40))
    remove((version - 0x91C28) & U32 <= 0x8290, 44)
    remove(signed >= 0x9A8F5, 45)
    remove(signed >= 0xCB0A3, 46)
    remove(signed >= 0x19428F, 47)
    remove(signed >= 0xB547A, 48)
    remove(signed >= 0xCCF5C, 49, 50, 51, 52)
    remove(bool(masters[0]), 51)
    remove(bool(masters[1]), 52)
    remove(signed >= 0xB1C28, 53)
    remove(signed >= 0xCB333, 54, 55, 56)
    for threshold, sites in (
        (0xCE8F5, (57,)),
        (0xD2666, (58, 59)),
        (0xD28F5, (60,)),
        (0xD3AE1, (61,)),
        (0xD428F, (62,)),
        (0x3F1999, (63,)),
        (0xD51EB, (64,)),
        (0x141999, (65,)),
        (0x3D07AE, (66, 67)),
        (0x3D3333, (68, 69)),
        (0x3DB333, (70,)),
        (0x416666, (71, 72)),
    ):
        remove(signed >= threshold, *sites)
    result = []
    for site in sorted(present):
        if site == 23:
            result.extend([23, 24] * maps)
        elif site == 24:
            continue
        elif site in (41, 43):
            result.extend([site] * max(0, old_count if site == 41 else elements))
        else:
            result.append(site)
    return result


class Case:
    def __init__(
        self,
        version=0x44E666,
        *,
        maps=0,
        old_count=0,
        elements=0,
        masters=(0, 0),
        types=(10, 10),
        dynamic=(0, 0),
        primary=0,
        payload=b"",
        sprite=0,
        ordinals=None,
        values=None,
        owner_state=0,
    ):
        m = self.memory = ReplayMemory()
        self.subject, self.output, self.stream, self.table, self.world, self.owner, self.master = (
            m.allocate(size) for size in (0x400, 48, 8, 32, 0x800, 0x700, 0x500)
        )
        for address, size in (
            (self.subject, 0x400),
            (self.world, 0x800),
            (self.owner, 0x700),
            (self.master, 0x500),
        ):
            m.write_bytes(address, bytes(size))
        m.write_bytes(self.output, bytes([0xA5]) * 48)
        m.write(self.stream, 8, self.table)
        m.write(self.table + 24, 8, INPUT)
        m.map_bytes(VERSION, version.to_bytes(4, "little"))
        m.map_bytes(0x144289738, (0xABCD).to_bytes(8, "little"))
        players, masters_table, graphics, owner_table, world_table = (
            m.allocate(size) for size in (16, 16, 16, 0x300, 0x90)
        )
        m.write(players, 8, self.owner)
        m.write(self.world + 0x768, 8, players)
        m.write(self.world + 0x770, 8, players + 16)
        m.write(self.world + 0xC0, 8, graphics)
        m.write(graphics, 8, 0xFACE)
        m.write(masters_table, 8, self.master)
        m.write(self.owner + 0x28, 8, masters_table)
        m.write(self.owner + 8, 8, self.world)
        m.write(self.owner + 0x648, 4, owner_state)
        m.write(self.owner, 8, owner_table)
        m.write(owner_table + 0x2D8, 8, 0xD01)
        m.write(self.world, 8, world_table)
        m.write(world_table + 0x88, 8, 0xD02)
        m.write(self.subject + 0x50, 8, 15)
        for offset in (0x30, 0x38, 0x40, 0x78):
            m.write(self.owner + offset, 8, 0xA000 + offset)
        self.ordinals = (
            plan(
                version,
                maps=maps,
                old_count=old_count,
                elements=elements,
                masters=masters,
                dynamic=dynamic,
            )
            if ordinals is None
            else ordinals
        )
        self.values = {
            1: 0,
            2: 0,
            3: 0xFFFF,
            4: U32,
            5: 0x3F800000,
            6: 3,
            7: 0,
            8: 0,
            9: 0,
            12: 0x3FC00000,
            13: 0xC0100000,
            14: 0x3F000000,
            22: maps,
            23: 7,
            24: 0x7FC12345,
            40: old_count & U32,
            42: elements & U32,
            49: masters[0],
            50: masters[1],
            51: types[0],
            52: types[1],
            53: sprite,
            54: primary,
            55: dynamic[0],
            56: dynamic[1],
            71: len(payload),
        }
        self.values.update(values or {})
        wire = bytearray()
        for ordinal in self.ordinals:
            width = SITES[ordinal - 1][3]
            wire.extend(
                payload
                if ordinal == 72
                else (self.values.get(ordinal, ordinal) & ((1 << (width * 8)) - 1)).to_bytes(
                    width, "little"
                )
            )
        self.source = ReplaySavedInput(bytes(wire))
        self.events, self.reads, self.map_records, self.elements, self.objects = [], [], [], [], []
        self.hooks, self.missing, self.status, self.result_controls = {}, set(), {}, {}
        self.null_allocation = False
        self.classification = U32
        if any(masters):
            self.map_master_tables()
        self.frame = None
        self.last_frame = b""
        self.context = ReplayTaskRebuildStorage(self.subject, self.read, m.write)
        self.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)
        actual_runtime = m.runtime_calls(ReplayTaskRebuildCalls(self.effect))

        def runtime_dispatch(target, args, data):
            if target == 0x142D6BA78 and self.null_allocation:
                return 0
            return actual_runtime.call(target, args, data)

        runtime = ReplayTaskRebuildCalls(runtime_dispatch)
        apply = bind_replay_saved_apply(
            self.context, runtime, atomics=self.atomics, imports=runtime
        )
        cleanup = bind_replay_saved_result(
            self.context, apply, atomics=self.atomics, imports=runtime
        )
        support = bind_replay_base_saved_support(self.context, cleanup)
        self.calls = bind_replay_saved_base(
            self.context,
            support,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=b"w" * 0x1168,
        )

    def map_master_tables(self):
        for address, data in (
            (0x1412651A8, "53242601b22426011125260170252601cf2526012e2626018a262601ab282601"),
            (0x141265210, "5b292601ba292601192a2601782a2601d72a2601362b2601922b26018e2d2601"),
        ):
            self.memory.map_bytes(address, bytes.fromhex(data))
        selectors = bytes(
            [0]
            + [7] * 9
            + [1]
            + [7] * 9
            + [2]
            + [7] * 9
            + [3]
            + [7] * 19
            + [4]
            + [7] * 9
            + [5]
            + [7] * 9
            + [6]
        )
        assert len(selectors) == 71
        self.memory.map_bytes(0x1412651C8, selectors)
        self.memory.map_bytes(0x141265230, selectors)

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.frame = address
            try:
                yield address
            finally:
                self.last_frame = self.memory.read_bytes(address, len(view))

    def read(self, address, width):
        value = self.memory.read(address, width)
        hook = self.hooks.get(("read", address, width))
        if hook:
            hook(value)
        return value

    def effect(self, target, args, data):
        assert data is None
        self.events.append((target, args))
        if target in self.missing:
            raise UnresolvedReplayTaskRebuild(f"test child unavailable{target:x}")
        hook = self.hooks.get(target)
        if hook:
            return hook(args)
        m = self.memory
        if target in (INPUT, INPUT2):
            ordinal = self.ordinals[len(self.reads)]
            slot, object_field, offset, width = SITES[ordinal - 1]
            assert args[:2] == (self.stream, self.frame + 0x100 + slot)
            if ordinal != 72:
                assert args[2:] == (
                    (self.subject if object_field else self.frame + 0x100) + offset,
                    width,
                )
            self.source.read_into(self.context, args[2], args[3])
            profile = bytearray(48)
            profile[24:32] = self.status.get(ordinal, 0).to_bytes(8, "little")
            profile[32:40] = self.result_controls.get(ordinal, 0).to_bytes(8, "little")
            m.write_bytes(args[1], bytes(profile))
            self.reads.append(ordinal)
            callback = self.hooks.get(("input", ordinal))
            if callback:
                callback(args)
            return args[1]
        if target == 0x1408EE150:
            assert m.read(args[0] + 8, 8) == 0
            return None
        if target == 0x14122F320:
            value = m.allocate(4)
            self.map_records.append((m.read(args[1], 2), value))
            return value
        if target == 0x14124B760:
            self.elements.append(args)
            return None
        if target in (
            0x1411B2820,
            0x1411745B0,
            0x1411A10A0,
            0x1411639B0,
            0x141199960,
            0x14130AF90,
            0x1412E1CA0,
        ):
            assert args[2:] == (self.stream, self.world + 0xC0, self.world + 0xA0, 1)
            m.write(args[0] + 0x122, 1, 0)
            m.write(args[0] + 0xCD, 1, 0)
            m.write_bytes(args[1], bytes(48))
            return args[0]
        if target == 0x1412429D0:
            m.write(args[0], 8, args[1])
            return None
        if target == 0x1411DF830:
            m.write(self.subject + 0x208, 8, args[0])
            return None
        if target == 0x141480D30:
            m.write(args[0], 8, args[1])
            return args[0]
        if target == 0x141483140:
            m.write(args[0] + 8, 8, args[3])
            m.write_bytes(args[1], bytes(48))
            return args[1]
        if target == 0x1409BDA80:
            pointer = m.allocate(8)
            m.write(pointer, 8, len(self.objects) + 1)
            self.objects.append(pointer)
            m.write(args[2], 8, pointer)
            m.write_bytes(args[1], bytes(48))
            return args[1]
        if target == 0x141255B00:
            self.objects.append((args[0], m.read(args[1], 8)))
            return None
        if target in (0x141248070, 0x1412480D0):
            m.write(self.subject + (0x298 if target == 0x141248070 else 0x2B0), 8, 0x111)
            return None
        if target == 0x140A1BDF0:
            m.write(args[0], 8, 0x222)
            m.write_bytes(args[1], bytes(48))
            return args[1]
        if target == 0x1402BB570:
            m.write(args[0] + 16, 8, args[1])
            return args[0]
        if target == 0x14185B6D0:
            assert args == ()
            return self.world
        if target == 0x14185CE10:
            m.write(self.subject + 0x338, 8, m.read(self.subject + 0x338, 8) + 1)
            return None
        if target == 0xD01:
            m.write(self.subject + 0x340, 8, args[0])
            return None
        if target == 0x1410B9490:
            return self.classification
        if target in (0x141727E10, 0x141228090, 0xD02, 0x14111A250, 0x14115F0A0):
            m.write(self.subject + 0x348, 8, m.read(self.subject + 0x348, 8) + 1)
            return None
        if target == 0x141729140:
            m.write(args[1], 4, args[2])
            m.write(args[1] + 4, 4, U32)
            m.write(args[1] + 8, 1, 0)
            return None
        if target == 0x1412488E0:
            m.write(self.subject + 0x33C, 4, 0xF00D)
            return None
        raise UnresolvedReplayTaskRebuild(f"test unknown child{target:x}")

    def invoke(self, direct=False):
        args = (self.subject, self.output, self.stream, self.world)
        if direct:
            return read_replay_saved_base(
                self.context,
                *args,
                calls=self.calls,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=b"w" * 0x1168,
            )
        assert self.calls.call is not None
        return self.calls.call(0x14125D730, args, None)


@pytest.mark.parametrize("direct", [False, True])
def test_modern_actual_input_result_chain_encoded_words_and_padding(direct):
    case = Case(payload=b"abc")
    assert case.invoke(direct) == case.output
    m, s = case.memory, case.subject
    assert case.reads == case.ordinals and case.source.remaining == 0
    assert m.read_bytes(case.output, 48) == bytes(41) + b"\xa5" * 7
    assert m.read(s + 24, 8) == case.owner
    assert m.read(s + 16, 8) == (case.master + KEY) & U64
    q = ((case.master + KEY) & U64 & ~U32) | 0x3F800000
    q = (q + 0x147B5E081EC087D9 & U64) ^ 0x0F2A55F7A61DD00E
    assert m.read(s + 0x130, 8) == q
    for field, word, constant in (
        (0x170, 0x3FC00000, -0x34030E3912A662C3),
        (0x178, 0xC0100000, -0x0B0E90B9C729451E),
        (0x180, 0x3F000000, -0x4D086415325B1A2B),
    ):
        q = ((q & ~U32 | word) + constant) & U64
        assert m.read(s + field, 8) == q
    assert m.read_bytes(s + 0x38, 3) == b"abc"
    assert m.read(s + 0x340, 8) == case.owner
    assert m.read(s + 0x33C, 4) == 0xF00D
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        m.read(case.frame, 1)


THRESHOLDS = (
    0x7170A,
    0xB947A,
    0x420000,
    0xCEB85,
    0x220001,
    0x9D999,
    0xC8CCC,
    0xC6B85,
    0xAD999,
    0x6FDB2,
    0x91C28,
    0x99EB9,
    0x9A8F5,
    0xCB0A3,
    0x19428F,
    0xB547A,
    0xCCF5C,
    0xB1C28,
    0xCB333,
    0xCE8F5,
    0xD2666,
    0xD28F5,
    0xD3AE1,
    0xD3D70,
    0xD4000,
    0xD428F,
    0x3F1999,
    0xD51EB,
    0x141999,
    0x3D07AE,
    0x3D3333,
    0x3DB333,
    0x416666,
)


@pytest.mark.parametrize(
    "version", sorted({0, 0x80000000, U32, *(t + d for t in THRESHOLDS for d in (-1, 0, 1))})
)
def test_every_version_gate_both_sides_and_historical_positive_loops(version):
    case = Case(version, maps=1, old_count=1, elements=1)
    case.invoke()
    assert case.reads == case.ordinals and case.source.remaining == 0
    assert len(case.elements) == 1
    assert case.memory.read(case.subject + 0x1C0, 2) == 0xFF


def test_positive_map_value_held_before_lookup_and_all_dynamic_groups():
    case = Case(maps=2, elements=2, primary=1, dynamic=(2, 1))
    case.invoke()
    assert case.reads == case.ordinals and case.source.remaining == 0
    assert len(case.map_records) == len(case.elements) == 2
    assert all(case.memory.read(address, 4) == 0x7FC12345 for _, address in case.map_records)
    calls = [args for target, args in case.events if target == 0x141255B00]
    assert [args[0] for args in calls] == [case.subject + 0x78] * 2 + [case.subject + 0x60]
    assert len([target for target, _ in case.events if target == 0x1409BDA80]) == 4


@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize(
    ("kind", "target", "size"),
    [
        (10, 0x1411B2820, 480),
        (20, 0x1411745B0, 488),
        (30, 0x1411A10A0, 552),
        (40, 0x1411639B0, 664),
        (60, 0x141199960, 816),
        (70, 0x14130AF90, 1000),
        (80, 0x1412E1CA0, 1184),
    ],
)
def test_both_nested_master_dispatch_tables_actual_allocation_and_return(which, kind, target, size):
    case = Case(masters=(int(which == 0), int(which == 1)), types=(kind, kind))
    case.invoke()
    args = next(args for entry, args in case.events if entry == target)
    assert case.memory.read_bytes(args[0], size) == bytes(size)
    pointer = (
        (case.memory.read(case.subject + 16, 8) - KEY) & U64
        if which == 0
        else (case.memory.read(case.subject + 0x1F8, 8))
    )
    assert pointer == args[0]
    field = 0x200 if which == 0 else 0x208
    assert case.memory.read(case.subject + field, 8) == (case.subject if which == 0 else pointer)


@pytest.mark.parametrize("which", [0, 1])
def test_null_master_allocation_still_publishes_and_reconciles_before_status(which):
    case = Case(masters=(int(which == 0), int(which == 1)))
    case.null_allocation = True
    observed = []
    target = 0x1412429D0 if which == 0 else 0x1411DF830

    def stop(args):
        observed.append(args)
        raise UnresolvedReplayTaskRebuild("bounded null reconciliation")

    case.hooks[target] = stop
    with pytest.raises(UnresolvedReplayTaskRebuild, match="null reconciliation"):
        case.invoke()
    assert case.memory.read(case.subject + (16 if which == 0 else 0x1F8), 8) == (
        KEY if which == 0 else 0
    )
    assert observed and case.memory.read_bytes(case.output, 48) == b"\xa5" * 48


@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize("kind", [0, 9, 11, 50, 81, 255])
def test_unknown_master_type_refuses_before_allocation(which, kind):
    case = Case(masters=(int(which == 0), int(which == 1)), types=(kind, kind))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="metadata frontier"):
        case.invoke()
    assert case.reads[-1] == 51 + which
    assert not any(target in (0x1412429D0, 0x1411DF830) for target, _ in case.events)


def test_current_master_selector_can_route_to_another_known_body():
    case = Case(masters=(1, 0), types=(10, 10))
    case.memory.write(0x1412651C8, 1, 1)
    case.invoke()
    assert any(target == 0x1411745B0 for target, _ in case.events)
    assert not any(target == 0x1411B2820 for target, _ in case.events)


def test_first_master_reconciliation_mutates_current_second_presence():
    ordinals = plan(0x44E666, masters=(1, 0))
    case = Case(masters=(1, 1), ordinals=ordinals)

    def reconcile(args):
        case.memory.write(args[0], 8, args[1])
        case.memory.write(case.frame + 0x100 - 0x5E, 1, 0)

    case.hooks[0x1412429D0] = reconcile
    case.invoke()
    assert 51 in case.reads and 52 not in case.reads and case.source.remaining == 0


def test_master_constructor_error_keeps_publication_and_reconciliation_before_check():
    case = Case(masters=(1, 0))

    def failed(args):
        case.memory.write(args[1] + 24, 8, 1)
        return args[0]

    case.hooks[0x1411B2820] = failed
    with pytest.raises(UnresolvedReplayTaskRebuild, match="metadata frontier"):
        case.invoke()
    assert case.memory.read(case.subject + 0x200, 8) == case.subject
    assert case.memory.read_bytes(case.output, 48) == b"\xa5" * 48


@pytest.mark.parametrize("ordinal", range(1, 73))
def test_each_raw_result_error_refuses_after_its_own_direct_bytes(ordinal):
    version = (
        0x6FDB2
        if ordinal in (19, 32, 33, 40, 41, *range(34, 40))
        else 0x95000
        if ordinal == 44
        else 0xD0000
        if ordinal == 26
        else 0x44E666
    )
    case = Case(
        version,
        maps=1,
        elements=1,
        old_count=1,
        masters=(1, 1),
        dynamic=(1, 1),
        primary=1,
        sprite=1,
        payload=b"ab",
    )
    case.status[ordinal] = 1
    with pytest.raises(UnresolvedReplayTaskRebuild, match="metadata frontier"):
        case.invoke()
    assert case.reads[-1] == ordinal
    result = 0x100 + SITES[ordinal - 1][0]
    assert case.last_frame[result + 40] == (1 if ordinal in (22, 23, 24) else 0)
    assert case.memory.read_bytes(case.output, 48) == b"\xa5" * 48


def test_map_value_held_and_count_reloaded_after_current_lookup():
    case = Case(maps=2, ordinals=plan(0x44E666, maps=1))

    def lookup(args):
        slot = case.memory.allocate(4)
        case.map_records.append((case.memory.read(args[1], 2), slot))
        case.memory.write(case.frame + 0x100 - 0x44, 4, 0xBAD)
        case.memory.write(case.frame + 0x100 - 0x58, 2, 0)
        return slot

    case.hooks[0x14122F320] = lookup
    case.invoke()
    assert len(case.map_records) == 1
    assert case.memory.read(case.map_records[0][1], 4) == 0x7FC12345


def test_child_count_is_decremented_before_call_and_reloaded_after_append():
    case = Case(dynamic=(2, 0), ordinals=plan(0x44E666, dynamic=(1, 0)))
    observed = []

    def append(args):
        observed.append(case.memory.read(case.frame + 0x100 - 0x7C, 2))
        case.memory.write(case.frame + 0x100 - 0x7C, 2, 0)

    case.hooks[0x141255B00] = append
    case.invoke()
    assert observed == [1] and case.source.remaining == 0


def test_held_version_skip_edge_does_not_invent_reload_for_next_threshold():
    ordinals = [ordinal for ordinal in plan(0xAD999) if ordinal != 45]
    case = Case(0xAD999, ordinals=ordinals)
    enabled = False

    def after31(_):
        nonlocal enabled
        enabled = True

    def version_read(_):
        nonlocal enabled
        if enabled:
            case.memory.write(VERSION, 4, 0x6FDB2)
            enabled = False

    case.hooks[("input", 31)] = after31
    case.hooks[("read", VERSION, 4)] = version_read
    case.invoke()
    assert all(ordinal not in case.reads for ordinal in range(32, 42))
    assert case.source.remaining == 0


def test_first_result_atomics_reload_control_vptr_and_stream_after_callbacks():
    case = Case()
    m = case.memory
    control, table, next_table, stream_table = (m.allocate(size) for size in (16, 16, 16, 32))
    for address, width, value in (
        (control, 8, table),
        (control + 8, 4, 1),
        (control + 12, 4, 1),
        (table, 8, 0xD10),
        (next_table + 8, 8, 0xD11),
        (stream_table + 24, 8, INPUT2),
    ):
        m.write(address, width, value)
    case.result_controls[1] = control
    observed = []

    def destroy(_):
        m.write(control, 8, next_table)
        m.write(case.stream, 8, stream_table)
        observed.append("destroy")

    def dispose(_):
        observed.append("dispose")

    case.hooks.update({0xD10: destroy, 0xD11: dispose})
    case.invoke()
    assert observed == ["destroy", "dispose"]
    assert m.read(control + 8, 4) == m.read(control + 12, 4) == 0
    io = [target for target, _ in case.events if target in (INPUT, INPUT2)]
    assert io[0] == INPUT and set(io[1:]) == {INPUT2}


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        (0x7F800000, 0x80000000),
        (0x7FC12345, 0x80000000),
        (0x80000000, 0),
        (0xBFC00000, 0xFFFFFFFF),
        (0x4F000000, 0x80000000),
    ],
)
def test_current_encoded_contact_coordinates_use_masked_integer_cvtt(word, expected):
    case = Case(values={12: word})
    case.memory.write(case.master + 0x122, 1, 2)
    case.invoke()
    contact = next(args for target, args in case.events if target == 0x14115F0A0)
    assert contact == (0xA078, case.subject, expected, 0xFFFFFFFE)


@pytest.mark.parametrize("flags", [(1, 0, 0xA038), (0, 1, 0xA040), (0, 0, 0xA030)])
def test_nonzero_owner_branch_actual_record_and_virtual_calls(flags):
    first, second, selected = flags
    case = Case(owner_state=1, values={7: first, 8: second})
    case.invoke()
    assert next(args for target, args in case.events if target == 0x141228090) == (
        selected,
        case.subject,
    )
    assert any(target == 0xD02 for target, _ in case.events)
    assert any(target == 0x141729140 for target, _ in case.events)
    assert any(target == 0x14111A250 for target, _ in case.events)


def test_classification_reads_current_second_field_after_registration_callback():
    case = Case()
    seen = []

    def classify(args):
        seen.append(args[0])
        return 2 if len(seen) == 1 else U32

    def register(_):
        case.memory.write(case.subject + 0x162, 2, 0xFFFE)

    case.hooks.update({0x1410B9490: classify, 0x141727E10: register})
    case.invoke()
    assert seen == [20, 0xFFFFFFFE]


@pytest.mark.parametrize(
    "missing",
    [
        0x14122F320,
        0x14124B760,
        0x1411B2820,
        0x141483140,
        0x1409BDA80,
        0x140A1BDF0,
        0x14185B6D0,
        0xD01,
        0x1412488E0,
    ],
)
def test_missing_semantic_children_refuse_with_prior_bytes_and_effects(missing):
    case = Case(maps=1, elements=1, masters=(1, 0), sprite=1, primary=1)
    case.missing.add(missing)
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"unavailable{missing:x}"):
        case.invoke()
    assert case.reads and case.memory.read(case.subject + 15, 1) == 10
    assert case.memory.read_bytes(case.output, 48) == b"\xa5" * 48


def test_reset_child_required_when_current_attachment_was_changed():
    case = Case()
    case.memory.write(case.subject + 0x138, 8, 0x1234)
    case.memory.write(case.subject + 0x141, 1, 1)
    case.missing.add(0x1412475D0)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable1412475d0"):
        case.invoke()
    assert case.memory.read(case.subject + 0x138, 8) == 0
    assert case.memory.read(case.subject + 0x141, 1) == 0


@pytest.mark.parametrize("index", [U32, 0x80000000, 1, 0x100000001])
def test_resolver_signed_low32_and_out_of_range(index):
    case = Case()
    assert resolve_replay_saved_base_owner(case.context, case.world, index) == 0


def test_resolver_current_begin_then_end_and_16byte_entry():
    case = Case()
    begin = case.memory.read(case.world + 0x768, 8)
    seen = []

    def on_begin(_):
        seen.append("begin")
        case.memory.write(case.world + 0x770, 8, begin)

    case.hooks[("read", case.world + 0x768, 8)] = on_begin
    assert resolve_replay_saved_base_owner(case.context, case.world, 0) == 0
    assert seen == ["begin"]


@pytest.mark.parametrize("args", [(), (1,), (1, 2, 3), (1, 2, 3, 4, 5)])
def test_binder_validates_full_base_arity_before_effects(args):
    case = Case()
    with pytest.raises(ValueError, match="malformed Base saved call"):
        case.calls.call(0x14125D730, args, None)
    assert case.source.position == 0


def test_unknown_helper_and_scratch_validation():
    case = Case()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unknown child1234"):
        case.calls.call(0x1234, (), None)
    with pytest.raises(ValueError, match="0x1168"):
        read_replay_saved_base(
            case.context,
            case.subject,
            case.output,
            case.stream,
            case.world,
            calls=case.calls,
            atomics=case.atomics,
            bind_local=case.bind_local,
            scratch=b"",
        )
    assert case.source.position == 0


def test_first_master_original_control_cleanup_is_mandatory_after_forwarded_cleanup():
    case = Case(masters=(1, 0))
    control = case.memory.allocate(16)
    case.memory.write(control, 8, 0)
    case.memory.write(control + 8, 4, 1)
    case.memory.write(control + 12, 4, 1)

    def construct(args):
        case.memory.write(args[1] + 32, 8, control)
        return args[0]

    case.hooks[0x1411B2820] = construct
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unknown child1402aaa80"):
        case.invoke()
    assert case.memory.read(control + 8, 4) == 1
    assert case.memory.read(case.subject + 0x200, 8) == case.subject
    assert case.memory.read_bytes(case.output, 48) == b"\xa5" * 48


def test_graphic_lookup_and_handle_retain_master_scratch_highword():
    case = Case(values={3: 0, 4: 0xFFFFFFFE})
    case.invoke()
    assert case.memory.read(case.subject + 32, 8) == 0xFACE
    expected = ((case.master + KEY) & U64 & ~U32) | U32
    assert case.memory.read(case.subject + 0x148, 8) == expected


def test_final_flag_uses_current_master_after_last_mandatory_callback():
    case = Case()
    replacement = case.memory.allocate(0x500)
    case.memory.write_bytes(replacement, bytes(0x500))
    case.memory.write(replacement + 0xCD, 1, 10)

    def replace(_):
        case.memory.write(case.subject + 16, 8, (replacement + KEY) & U64)

    case.hooks[0x1412488E0] = replace
    case.invoke()
    assert case.memory.read(case.subject + 0x1C9, 1) == 0


def test_output_can_alias_subject_and_is_cleared_only_after_callbacks():
    case = Case()
    case.output = case.subject + 0x338
    case.memory.write_bytes(case.output, b"\xa5" * 48)
    observed = []

    def before_output(_):
        observed.append(case.memory.read(case.subject + 0x340, 8))

    case.hooks[0x1412488E0] = before_output
    assert case.invoke() == case.output
    assert observed == [case.owner]
    assert case.memory.read_bytes(case.output, 48) == bytes(41) + b"\xa5" * 7
