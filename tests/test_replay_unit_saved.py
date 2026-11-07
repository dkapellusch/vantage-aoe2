"""Source-derived complete Unit caller controls over owned current storage.

Component controls isolate Combat explicitly. Positive stingers execute actual
Input/Result/wrappers/graphic fixup; unported map/vector/ownership descendants
refuse unless a test names its component effect. No native execution is claimed.
"""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from vantage.replay_base_saved_leaves import release_replay_base_saved_pair_control
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_position import bind_replay_saved_position
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_construction import bind_replay_unit_ai_construction
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_ai_variants import (
    ReplayUnitAIVariantScratch,
    bind_replay_unit_ai_variants,
)
from vantage.replay_unit_saved import (
    ReplayUnitSavedReaderScratch,
    bind_replay_unit_saved,
    read_replay_saved_unit,
)
from vantage.replay_unit_saved_components import (
    ReplayUnitSavedScratch,
    bind_replay_unit_saved_components,
)

ENTRY, COMBAT, VERSION = 0x1412D4F50, 0x1411587A0, 0x1440A0D94
IO, IO2, AI_READER = 0xDB01, 0xDB02, 0xDB03
MODERN, U64 = 0x44E666, (1 << 64) - 1
SCRATCH = ReplayUnitSavedReaderScratch(bytes(i & 255 for i in range(0xF18)))


def wire_plan(
    version=MODERN,
    *,
    tag=0,
    legacy_flag=0,
    legacy_tag=70,
    discarded=0,
    stingers=0,
    pairs=(),
    optional=0,
):
    """Independent stable-version recipe from the frozen original source."""
    v = version if version < 0x80000000 else version - (1 << 32)
    rows = []

    def add(label, kind, offset, width, value):
        mask = (1 << (8 * width)) - 1
        rows.append(
            dict(
                label=label,
                kind=kind,
                offset=offset,
                width=width,
                raw=(value & mask).to_bytes(width, "little"),
            )
        )

    def field(offset, width=4):
        add(f"{offset:x}", "object", offset, width, 0x80000000 + offset)

    if v >= 0x911EB:
        field(0x68C, 1)
    if v >= 0x94000:
        field(0x68D, 1)
    if v < 0xCCF5C:
        add("legacy_flag", "unit", 1, 1, legacy_flag)
        if legacy_flag:
            add("legacy_tag", "unit", 2, 1, legacy_tag)
    if v >= 0x9428F:
        for offset in range(0x618, 0x624, 2):
            field(offset, 2)
    elif v >= 0x90F5C:
        for offset in range(0x618, 0x622, 2):
            field(offset, 2)
    if v >= 0x928F5:
        field(0x624, 2)
    for gate, offset, width in ((0x99C28, 0x628, 4), (0x9A666, 0x690, 4), (0xB8F5C, 0x630, 1)):
        if v >= gate:
            field(offset, width)
    add("ai_tag", "unit", 0x18, 4, tag)
    if v >= 0x323333:
        for offset, width in (
            (0x664, 1),
            (0x634, 4),
            (0x644, 4),
            (0x648, 4),
            (0x640, 4),
            (0x638, 4),
            (0x63C, 4),
            (0x64C, 4),
            (0x65C, 4),
            (0x660, 4),
            (0x658, 4),
            (0x650, 4),
            (0x654, 4),
        ):
            field(offset, width)
    else:
        if v >= 0xA4CCC:
            for offset, width in ((0x664, 1), (0x634, 4), (0x644, 4), (0x648, 4)):
                field(offset, width)
        if v >= 0xBB5C2:
            field(0x640)
            field(0x638)
        if v >= 0xBBD70:
            field(0x63C)
    for gate, offset, width in (
        (0xA6B85, 0x698, 4),
        (0xA75C2, 0x670, 1),
        (0xBB0A3, 0x671, 1),
        (0x14028F, 0x668, 4),
    ):
        if v >= gate:
            field(offset, width)
    if v >= 0x190000:
        field(0x66C, 2)
        field(0x66E, 2)
    if v >= 0x1A051E:
        field(0x62C)
    if (version + 0xFFE5F334) & 0xFFFFFFFF <= 0x2147:
        add("discard_byte", "unit", 8, 1, 0xEA)
    if 0x281999 <= v < 0x320000:
        field(0x6AC)
        field(0x6B0)
        field(0x6DC)
        add("discard_count", "unit", 0x20, 8, discarded)
        for index in range(discarded):
            add(f"discard{index}", "unit", 0x88, 4, index + 10)
        field(0x6B4)
    elif v >= 0x320000:
        for offset in (0x6AC, 0x6B0, 0x6DC, 0x6B4, 0x6B8, 0x6BC):
            field(offset)
    if v >= 0x3D051E:
        for offset in (0x7C0, 0x7C4, 0x7C8):
            field(offset)
        add("stinger_count", "unit", 0xC, 4, stingers)
        for index in range(stingers if stingers < 0x80000000 else 0):
            for offset in (0, 4, 0xC, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24):
                add(f"s{index}_{offset:x}", "stinger", offset, 4, 100 + index + offset)
            add(f"s{index}_sprite", "child", 0, 2, 0xFFFF)
            if v >= 0x433333:
                add(f"s{index}_time", "stinger", 8, 4, 0x80000000)
    if v >= 0x3D1999:
        for offset in (0x6C0, 0x6C4, 0x6C8, 0x6D0, 0x6D4):
            field(offset)
    if v >= 0x3D3333:
        add("map_count", "unit", 0x10, 4, len(pairs))
        for index, (key, value) in enumerate(pairs):
            add(f"mapkey{index}", "unit", 4, 2, key)
            add(f"mapvalue{index}", "unit", 0x14, 4, value)
    if v >= 0x3D6666:
        field(0x6D8)
    if v >= 0x404CCD:
        field(0x808, 1)
    if v >= 0x43B333:
        add("optional", "unit", 0, 1, optional)
        if optional:
            add("timer_word", "timer", 0, 2, 0x1234)
            add("timer_dword", "timer", 4, 4, 0x7FC01234)
    return rows


def setup(*, version=MODERN, plan=None, before=None, after=None, on_read=None, on_write=None):
    h = SimpleNamespace()
    h.m = m = ReplayMemory()
    h.obj, h.out, h.stream, h.table, h.table2, h.master, h.owner, h.owner_state, h.game = (
        m.allocate(size) for size in (0xA00, 48, 8, 0x1000, 0x1000, 0x400, 0x100, 0x210, 0x600)
    )
    m.write_bytes(h.obj, b"Z" * 0xA00)
    m.write_bytes(h.out, b"O" * 48)
    m.write(h.obj, 8, h.table)
    m.write(h.obj + 16, 8, h.master + 0x774A063B3D17506C)
    m.write(h.obj + 24, 8, h.owner)
    m.write(h.master + 0x360, 4, 0x7FC01234)
    m.write(h.owner + 0x98, 8, h.owner_state)
    m.write(h.owner + 8, 8, 0xEE000000)
    encoded = ((0x3FC00000 ^ 0xA9834B738A7DD167) + 0x042AC42976FCCEF5) & U64
    m.write(h.owner_state + 0x208, 8, encoded ^ 0xC22D6B496D833977 ^ 0x6AE24D3352F04511)
    m.write(h.stream, 8, h.table)
    m.write(h.table + 24, 8, IO)
    m.write(h.table2 + 24, 8, IO2)
    m.write(h.game + 0x5C0, 8, 0)  # Explicit known-null world, negative graphicID skips it.
    h.vector = m.allocate(56 * 3)
    m.write(h.obj + 0x7F0, 8, h.vector)
    m.write(h.obj + 0x7F8, 8, h.vector)
    m.write(h.obj + 0x800, 8, h.vector + 56 * 3)
    for pointer, width, value in (
        (VERSION, 4, version & 0xFFFFFFFF),
        (0x143199DD0, 8, 0x142D6BAB4),
        (0x143199938, 8, 0x142D6E3B7),
        (0x144353698, 8, h.game),
        (0x1436A02F8, 4, 0x447A0000),
    ):
        m.map_bytes(pointer, value.to_bytes(width, "little"))
    m.map_bytes(0x1436A0A30, b"\xff" * 16, writable=False)
    h.frames, h.finished, h.ops, h.calls, h.reads = [], [], [], [], []
    h.missing, h.handlers, h.effects = set(), {}, {}
    h.opaque = 0xFEDCBA9876543210
    h.plan = wire_plan(version) if plan is None else plan
    h.source = ReplaySavedInput(b"".join(row["raw"] for row in h.plan))

    def read(pointer, width):
        value = m.read(pointer, width)
        h.ops.append(("read", pointer, width, value))
        if on_read:
            on_read(h, pointer, width, value)
        return value

    def write(pointer, width, value):
        m.write(pointer, width, value)
        h.ops.append(("write", pointer, width, value))
        if on_write:
            on_write(h, pointer, width, value)

    h.context = ReplayTaskRebuildStorage(h.obj, read, write)
    h.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)

    @contextmanager
    def local(view):
        with m.bind_local(view) as pointer:
            h.frames.append((pointer, view))
            try:
                yield pointer
            finally:
                h.finished.append((pointer, bytes(view)))
                h.frames.pop()

    h.local = local
    runtime = m.runtime_calls()

    def dispatch(target, args, data):
        h.calls.append((target, args))
        if target in h.missing:
            raise UnresolvedReplayTaskRebuild(f"missing actual child{target:x}")
        if before:
            before(h, target, args)
        if target in (IO, IO2):
            row = h.plan[len(h.reads)]
            assert args[3] == row["width"]
            if row["kind"] in ("unit", "object", "stinger", "timer"):
                base = {
                    "unit": h.frames[0][0] + 0x100,
                    "object": h.obj,
                    "stinger": getattr(h, "stinger", 0),
                    "timer": getattr(h, "timer", 0),
                }
                assert args[2] == base[row["kind"]] + row["offset"]
            h.reads.append((row["label"], args))
        if target in h.effects:
            answer = h.effects[target](target, args, data)
        elif target == COMBAT:
            assert args == (h.obj, h.frames[0][0] + 0x190, h.stream, h.opaque)
            answer = 0xDEADBEEF  # Explicit isolated Combat predecessor fixture.
        elif target == 0x1408EE150:
            release_replay_base_saved_pair_control(
                h.context, args[0], calls=h.graph, atomics=h.atomics
            )
            answer = None
        elif target in h.handlers:
            if target == 0x1411281D0:
                h.stinger = args[0]
            elif target == 0x1410B1A40:
                h.timer = args[0]
            answer = h.handlers[target](target, args, data)
        else:
            assert runtime.call
            answer = runtime.call(target, args, data)
        if after:
            changed = after(h, target, args, answer)
            if changed is not None:
                answer = changed
        return answer

    h.graph = ReplayTaskRebuildCalls(dispatch)

    def register(bound, targets):
        assert bound.call
        for target in targets:
            h.handlers[target] = bound.call

    register(
        bind_replay_saved_result(h.context, h.graph, atomics=h.atomics, imports=runtime),
        (0x1402BD7F0, 0x1402BD890, 0x140900620),
    )
    register(
        bind_replay_saved_apply(h.context, h.graph, atomics=h.atomics, imports=runtime),
        (0x1409076B0, 0x1402B9080),
    )
    for io in (IO, IO2):
        register(
            bind_replay_saved_input(
                h.context, h.graph, h.source, stream=h.stream, target=io, result_bytes=bytes(48)
            ),
            (io,),
        )
    register(
        bind_replay_saved_position(h.context, h.graph, atomics=h.atomics, bind_local=local),
        (0x140B81D60, 0x140B81E60, 0x140D94310, 0x140D07EE0),
    )
    register(
        bind_replay_unit_ai_construction(h.context, h.graph, bind_local=local, imports=runtime),
        (0x1412CA880, 0x140CEF620, 0x142D6E3B7),
    )
    register(
        bind_replay_unit_ai_variants(
            h.context,
            h.graph,
            atomics=h.atomics,
            bind_local=local,
            scratch=ReplayUnitAIVariantScratch(bytes(0x140), bytes(0xC0), bytes(0xD0)),
        ),
        (0x140D6ACC0, 0x14172AC80),
    )
    register(
        bind_replay_unit_saved_components(
            h.context,
            h.graph,
            atomics=h.atomics,
            bind_local=local,
            scratch=ReplayUnitSavedScratch(bytes(0x90), bytes(0x80)),
        ),
        (0x1411281D0, 0x1410B1A40, 0x1416028D0),
    )
    h.bound = bind_replay_unit_saved(
        h.context, h.graph, atomics=h.atomics, bind_local=local, scratch=SCRATCH, mxcsr=0x1F80
    )
    return h


def invoke(h, *, direct=False):
    if direct:
        return read_replay_saved_unit(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            calls=h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
            mxcsr=0x1F80,
        )
    assert h.bound.call
    return h.bound.call(ENTRY, (h.obj, h.out, h.stream, h.opaque), None)


def replace_input(h, plan):
    """Create a new immutable source and bind its actual capabilities."""
    h.plan = plan
    h.source = ReplaySavedInput(b"".join(row["raw"] for row in plan))
    for io in (IO, IO2):
        bound = bind_replay_saved_input(
            h.context, h.graph, h.source, stream=h.stream, target=io, result_bytes=bytes(48)
        )
        assert bound.call
        h.handlers[io] = bound.call


@pytest.mark.parametrize(
    "version",
    [
        0,
        0x90F5B,
        0x90F5C,
        0x911EA,
        0x911EB,
        0x928F4,
        0x928F5,
        0x93FFF,
        0x94000,
        0x9428E,
        0x9428F,
        0x99C27,
        0x99C28,
        0x9A665,
        0x9A666,
        0xA4CCB,
        0xA4CCC,
        0xA6B84,
        0xA6B85,
        0xA75C1,
        0xA75C2,
        0xBB0A2,
        0xBB0A3,
        0xBB5C1,
        0xBB5C2,
        0xBBD6F,
        0xBBD70,
        0xB8F5B,
        0xB8F5C,
        0xCCF5B,
        0xCCF5C,
        0x14028E,
        0x14028F,
        0x18FFFF,
        0x190000,
        0x1A051D,
        0x1A051E,
        0x1A0CCB,
        0x1A0CCC,
        0x1A2E13,
        0x1A2E14,
        0x281998,
        0x281999,
        0x31FFFF,
        0x320000,
        0x323332,
        0x323333,
        0x3D051D,
        0x3D051E,
        0x3D1998,
        0x3D1999,
        0x3D3332,
        0x3D3333,
        0x3D6665,
        0x3D6666,
        0x404CCC,
        0x404CCD,
        0x43B332,
        0x43B333,
        MODERN,
        0x80000000,
        0xFFFFFFFF,
    ],
)
@pytest.mark.parametrize("direct", [False, True])
def test_complete_stable_version_wire_order_and_explicit_defaults(version, direct):
    h = setup(version=version)
    assert invoke(h, direct=direct) == h.out
    assert len(h.reads) == len(h.plan)
    assert h.source.position == sum(row["width"] for row in h.plan)
    assert h.m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    assert h.m.read(h.obj + 15, 1) == 70
    assert h.m.read(h.obj + 0x688, 4) == 0x7FC01234
    assert h.m.read(h.obj + 0x694, 1) == 0
    assert h.m.read(h.obj + 0x1F0, 8) == 0
    assert h.m.read(h.obj + 0x7F8, 8) == h.vector
    selected = {row["offset"] for row in h.plan if row["kind"] == "object"}
    for offset in (0x6AC, 0x6B8, 0x6D8, 0x808):
        if offset not in selected:
            assert h.m.read(h.obj + offset, 1) == 0x5A
    signed_version = version if version < 0x80000000 else version - (1 << 32)
    if signed_version < 0x928F5:
        assert h.m.read(h.obj + 0x624, 2) == 1500


def test_real_positive_stingers_use_actual_reader_wrappers_and_inline_append():
    h = setup(plan=wire_plan(stingers=2))
    invoke(h)
    assert h.m.read(h.obj + 0x7F8, 8) == h.vector + 112
    for index in range(2):
        pointer = h.vector + index * 56
        for offset in (0, 4, 0xC, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24):
            assert h.m.read(pointer + offset, 4) == 100 + index + offset
        assert h.m.read(pointer + 8, 4) == 0x80000000
        assert h.m.read_bytes(pointer + 40, 16) == bytes(16)
    assert h.source.position == sum(row["width"] for row in h.plan)
    assert len([e for e in h.ops if e[:3] == ("read", 0x1436A0A30, 16)]) == 1


def test_missing_positive_vector_growth_refuses_after_real_stinger_effects():
    h = setup(plan=wire_plan(stingers=1))
    h.m.write(h.obj + 0x800, 8, h.vector)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1412a38c0"):
        invoke(h)
    assert h.calls[-1][0] == 0x1412A38C0
    assert h.m.read(h.obj + 0x7F8, 8) == h.vector
    assert h.m.read(h.obj + 0x7C8, 4) == 0x800007C8
    assert h.m.read_bytes(h.out, 48) == b"O" * 48


def test_positive_map_helper_remains_mandatory_after_real_pair_input():
    h = setup(plan=wire_plan(pairs=[(0xFFFF, 0x7FC01234)]))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1412a48d0"):
        invoke(h)
    target, args = h.calls[-1]
    assert target == 0x1412A48D0 and args[0] == h.obj + 0x768
    frame = h.finished[-1][1]
    assert frame[0x104:0x106] == b"\xff\xff"
    assert frame[0x114:0x118] == bytes.fromhex("3412c07f")


def test_isolated_map_component_receives_current_pointers_and_mutates_loop_count():
    h = setup(plan=wire_plan(pairs=[(7, 0xFFFFFFFF), (9, 10)]))
    observed = []

    def component(target, args, data):
        observed.append((h.m.read(args[2], 2), h.m.read(args[3], 4)))
        # This is an explicit helper-isolation effect, not map implementation.
        h.m.write(h.frames[0][0] + 0x110, 4, 1)

    h.effects[0x1412A48D0] = component
    # Remove the now-skipped second entry from the independent wire recipe.
    replace_input(h, [row for row in h.plan if row["label"] not in ("mapkey1", "mapvalue1")])
    invoke(h)
    assert observed == [(7, 0xFFFFFFFF)]


@pytest.mark.parametrize(
    "legacy_tag,entry,size", [(70, 0x14130AF90, 1000), (80, 0x1412E1CA0, 1184)]
)
def test_legacy_master_reaches_actual_constructor_six_argument_boundary(legacy_tag, entry, size):
    h = setup(version=0xA0000, plan=wire_plan(0xA0000, legacy_flag=1, legacy_tag=legacy_tag))
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{entry:x}"):
        invoke(h)
    target, args = h.calls[-1]
    assert target == entry and len(args) == 6
    assert args[2:] == (h.stream, 0xEE0000C0, 0xEE0000A0, 1)
    assert h.m.read_bytes(args[0], size) == bytes(size)
    assert h.m.read(h.obj + 16, 8) == h.master + 0x774A063B3D17506C


@pytest.mark.parametrize("tag", [0, 0xFFFFFFFF, 0x80000000])
def test_signed_nonpositive_ai_tag_skips_factory_and_reader(tag):
    h = setup(plan=wire_plan(tag=tag))
    invoke(h)
    assert not any(target in (0x1412CA880, 0x1412CADB0, AI_READER) for target, _ in h.calls)


def test_type_one_current_helper_existing_pointer_and_current_reader():
    h = setup(plan=wire_plan(tag=1))
    ai, vptr = h.m.allocate(8), h.m.allocate(24)
    h.m.write(ai, 8, vptr)
    h.m.write(vptr + 16, 8, AI_READER)
    seen = []

    def owner_helper(target, args, data):
        assert args == (h.obj,)
        h.m.write(h.obj + 0x1F0, 8, ai)

    def reader(target, args, data):
        seen.append(args)
        assert h.m.read_bytes(args[1], 48) == bytes(48)
        return 0xBAD  # Ignored actual reader RAX; source checks fixed local Result.

    h.effects[0x1412CADB0], h.effects[AI_READER] = owner_helper, reader
    invoke(h)
    assert len(seen) == 1 and seen[0][0] == ai and seen[0][2] == h.stream


def test_type_one_unavailable_owner_helper_refuses_before_allocation():
    h = setup(plan=wire_plan(tag=1))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1412cadb0"):
        invoke(h)
    assert h.calls[-1] == (0x1412CADB0, (h.obj,))
    assert not any(target == 0x142D6BA78 for target, _ in h.calls)


def test_type_one_constructor_is_mandatory_after_real_allocation_and_memset():
    h = setup(plan=wire_plan(tag=1))
    h.effects[0x1412CADB0] = lambda target, args, data: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140cef230"):
        invoke(h)
    target, args = h.calls[-1]
    assert target == 0x140CEF230 and args[1:] == (h.obj, 10)
    assert h.m.read_bytes(args[0], 0x1F8) == bytes(0x1F8)
    assert h.m.read(h.obj + 0x1F0, 8) == 0


def test_greater_than_one_uses_real_factory_and_stops_at_required_constructor():
    h = setup(plan=wire_plan(tag=2))
    # Actual tag2 slot from the frozen dual-image factory table.
    h.m.map_bytes(0x1412CAD60, (0x12CAA14).to_bytes(4, "little"))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140cee930"):
        invoke(h)
    target, args = h.calls[-1]
    assert target == 0x140CEE930 and args[1:] == (h.obj, 10)
    assert h.m.read_bytes(args[0], 0x208) == bytes(0x208)
    assert h.m.read(h.obj + 0x1F0, 8) == 0


def test_stinger_result_is_finalized_without_added_caller_status_check():
    def after(h, target, args, answer):
        if target == 0x1411281D0:
            h.m.write(args[1] + 24, 8, 0xBAD)

    h = setup(plan=wire_plan(stingers=1), after=after)
    invoke(h)
    assert h.m.read(h.obj + 0x7F8, 8) == h.vector + 56
    assert h.m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7


def test_inline_append_holds_destination_but_increments_current_end():
    def mutate(h, pointer, width, value):
        if pointer == h.vector + 48 and width == 8:
            h.m.write(h.obj + 0x7F8, 8, h.vector + 56)

    h = setup(plan=wire_plan(stingers=1), on_write=mutate)
    invoke(h)
    assert h.m.read(h.obj + 0x7F8, 8) == h.vector + 112
    assert h.m.read(h.vector, 4) == 100
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.m.read(h.vector + 56, 4)


def test_negative_stinger_count_preserves_existing_vector():
    h = setup(plan=wire_plan(stingers=0xFFFFFFFF))
    h.m.write_bytes(h.vector, b"X" * 56)
    h.m.write(h.obj + 0x7F8, 8, h.vector + 56)
    invoke(h)
    assert h.m.read(h.obj + 0x7F8, 8) == h.vector + 56
    assert h.m.read_bytes(h.vector, 56) == b"X" * 56
    assert not any(target == 0x1411281D0 for target, _ in h.calls)


def test_discard_loop_uses_current_unsigned64_count_including_high_bit():
    plan = wire_plan(0x281999, discarded=1)
    next(row for row in plan if row["label"] == "discard_count")["raw"] = (
        0x8000000000000000
    ).to_bytes(8, "little")

    def after(h, target, args, answer):
        if target == IO and h.reads[-1][0] == "discard0":
            h.m.write(h.frames[0][0] + 0x120, 8, 0)

    h = setup(version=0x281999, plan=plan, after=after)
    invoke(h)
    assert len([label for label, _ in h.reads if label == "discard0"]) == 1


@pytest.mark.parametrize(
    "word,expected",
    [
        (0x80000000, 0),
        (0xBF800000, 0xFC18),
        (0x7FC01234, 0),
        (0x7F800000, 0),
        (1, 0),
        (0x40200000, 2500),
    ],
)
def test_legacy_protected_scalar_uses_raw_binary32_cvtt_lowword(word, expected):
    h = setup(version=0)
    decoded = 0xABCDEF0000000000 | word
    encoded = ((decoded ^ 0xA9834B738A7DD167) + 0x042AC42976FCCEF5) & U64
    h.m.write(h.owner_state + 0x208, 8, encoded ^ 0xC22D6B496D833977 ^ 0x6AE24D3352F04511)
    invoke(h)
    assert h.m.read(h.obj + 0x624, 2) == expected


def test_optional_ownership_transfer_refuses_with_initialized_padding_undefined():
    h = setup(plan=wire_plan(optional=1))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1412a3520"):
        invoke(h)
    target, args = h.calls[-1]
    assert target == 0x1412A3520 and args[0] == h.obj + 0x818
    frame = h.finished[-1][1]
    pointer = int.from_bytes(frame[0x90:0x98], "little")
    assert h.m.read(pointer, 2) == 0xFFFF and h.m.read(pointer + 4, 4) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.m.read(pointer + 2, 2)


def test_isolated_transfer_then_real_optional_timer_and_cleanup():
    h = setup(plan=wire_plan(optional=1))

    def transfer(target, args, data):
        # Explicit ownership helper fixture; timer reader remains its real body.
        h.m.write(args[0], 8, h.m.read(args[1], 8))
        h.m.write(args[1], 8, 0)

    h.effects[0x1412A3520] = transfer
    invoke(h)
    timer = h.m.read(h.obj + 0x818, 8)
    assert h.m.read(timer, 2) == 0x1234 and h.m.read(timer + 4, 4) == 0x7FC01234


def test_held_modern_group_finishes_after_input_changes_global_version():
    def after(h, target, args, answer):
        if target == IO and h.reads[-1][0] == "634":
            h.m.write(VERSION, 4, 0)

    plan = wire_plan()
    stop = next(i for i, row in enumerate(plan) if row["label"] == "654") + 1
    h = setup(plan=plan[:stop], after=after)
    invoke(h)
    assert [label for label, _ in h.reads][-9:] == [
        "640",
        "638",
        "63c",
        "64c",
        "65c",
        "660",
        "658",
        "650",
        "654",
    ]


def test_complete_real_combat_action_tracker_stinger_input_composition():
    from vantage.replay_action_saved import (
        ReplayActionSavedScratch,
        bind_replay_action_saved,
    )
    from vantage.replay_action_saved_map import bind_replay_action_saved_map
    from vantage.replay_behavior_factory import bind_replay_behavior_factory
    from vantage.replay_behavior_saved import (
        ReplayBehaviorSavedScratch,
        bind_replay_behavior_saved,
    )
    from vantage.replay_combat_saved import (
        ReplayCombatSavedScratch,
        read_replay_saved_combat,
    )
    from vantage.replay_combat_saved_tracker import (
        ReplayCombatTrackerScratch,
        bind_replay_combat_saved_tracker,
    )
    from vantage.replay_unit_constructor_maps import bind_replay_unit_constructor_maps

    def existing_recipe(name):
        path = Path(__file__).with_name(name)
        spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.wire_plan

    h = setup(plan=wire_plan(stingers=1))
    action = existing_recipe("test_replay_action_saved.py")
    combat = existing_recipe("test_replay_combat_saved.py")
    h.plan = [
        *action(count=1, pairs=[(23, 0x7FC00001)]),
        *combat(count=1, rows=[(8, 11, 12)]),
        *h.plan,
    ]
    # Parent recipes contain coherent child-local destinations; the nested
    # bodies and final field/entry assertions verify them independently here.
    for row in h.plan:
        if row["kind"] in ("action", "combat", "behavior"):
            row["kind"] = "child"
    replace_input(h, h.plan)
    m = h.m
    m.write(h.master + 0x228, 8, 0)
    task_effect, ceil_effect = 0xD901, 0xD902
    m.write(h.table + 0x960, 8, task_effect)
    m.write(h.table + 0x8F8, 8, 0x1412C5A30)
    m.map_bytes(0x143199EF0, ceil_effect.to_bytes(8, "little"))
    m.map_bytes(0x1436A0308, bytes.fromhex("0000005f"), writable=False)
    nil = m.allocate(40)
    m.write_bytes(nil, b"N" * 40)
    for offset in (0, 8, 16):
        m.write(nil + offset, 8, nil)
    m.write(nil + 24, 2, 0x101)
    m.write(h.obj + 0x520, 8, nil)
    m.write(h.obj + 0x528, 8, 0)

    def register(bound, targets):
        assert bound.call
        for target in targets:
            h.handlers[target] = bound.call

    register(
        bind_replay_unit_constructor_maps(h.context, h.graph, bind_local=h.local),
        (0x141136CA0, 0x14113A360, 0x141136C10, 0x14113B410),
    )
    register(
        bind_replay_action_saved_map(h.context, h.graph, mxcsr=0x1F80),
        (0x1411369A0, 0x14113A430, 0x142D6E453, 0x142D66698),
    )
    register(
        bind_replay_behavior_factory(h.context, h.graph),
        (0x14113B370, 0x140B875A0, 0x1412C5A30, 0x140BB6EC0),
    )
    register(
        bind_replay_behavior_saved(
            h.context,
            h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=ReplayBehaviorSavedScratch(bytes(0xD0)),
        ),
        (0x140B88C50,),
    )
    register(
        bind_replay_action_saved(
            h.context,
            h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=ReplayActionSavedScratch(bytes(0xB0)),
        ),
        (0x14113E920,),
    )
    register(
        bind_replay_combat_saved_tracker(
            h.context,
            h.graph,
            bind_local=h.local,
            scratch=ReplayCombatTrackerScratch(bytes(64)),
        ),
        (0x1411445A0, 0x14114DB00, 0x1402AB280),
    )

    def parent(target, args, data):
        return read_replay_saved_combat(
            h.context,
            *args,
            calls=h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=ReplayCombatSavedScratch(bytes(0xC8)),
        )

    def moving(target, args, data):
        assert args[0] == h.obj and args[3] == h.opaque
        return 0xDEADBEEF  # Explicit isolated Moving predecessor, unchanged Result0.

    def task(target, args, data):
        assert args == (h.obj, 0)  # Required final Combat virtual960 engine fixture.

    runtime = m.runtime_calls()

    def ceil(target, args, data):
        assert runtime.call
        return runtime.call(0x142D6E453, args, data)

    h.effects.update({COMBAT: parent, 0x14121F910: moving, task_effect: task, ceil_effect: ceil})
    assert h.graph.call
    h.graph.call(0x141136CA0, (h.obj + 0x460,), None)
    invoke(h)
    assert h.source.position == sum(row["width"] for row in h.plan)
    node = m.read(nil + 8, 8)
    assert m.read(node + 28, 4) == 8 and m.read(node + 32, 8) == 0xC0000000B
    action_nil = m.read(h.obj + 0x468, 8)
    action_node = m.read(action_nil + 8, 8)
    assert m.read(action_node + 16, 4) == 23
    assert m.read(action_node + 20, 4) == 0x7FC00001
    assert m.read(h.obj + 0x7F8, 8) == h.vector + 56
    assert m.read(h.obj + 15, 1) == 70
    assert m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7


@pytest.mark.parametrize("child", [COMBAT, 0x1402BD890, 0x140900620])
def test_missing_required_work_retains_prefix_writes_and_no_output_success(child):
    h = setup()
    h.missing.add(child)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="missing actual child"):
        invoke(h)
    assert h.m.read(h.obj + 0x1F0, 8) == 0 and h.m.read(h.obj + 0x694, 1) == 0
    assert h.m.read_bytes(h.out, 48) == b"O" * 48


def test_current_stream_vptr_changes_next_input():
    def after(h, target, args, answer):
        if target == IO:
            h.m.write(h.stream, 8, h.table2)

    h = setup(after=after)
    invoke(h)
    inputs = [target for target, _ in h.calls if target in (IO, IO2)]
    assert inputs[0] == IO and all(target == IO2 for target in inputs[1:])


def test_result_error_refuses_before_processed_store():
    def after(h, target, args, answer):
        if target == IO and h.reads[-1][0] == "68c":
            h.m.write(args[1] + 24, 8, 0xBAD)

    h = setup(after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="metadata/TLS"):
        invoke(h)
    frame = h.finished[-1][1]
    assert frame[0x1E8] == 0
    assert h.m.read(h.obj + 0x68C, 1) == 0x8C


@pytest.mark.parametrize("mxcsr", [0, 0x1F00, 0x3F80, 0x9F80, 0x1FC0])
def test_mxcsr_rejects_before_prefix_effects(mxcsr):
    h = setup()
    with pytest.raises(ValueError, match="MXCSR"):
        read_replay_saved_unit(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            calls=h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
            mxcsr=mxcsr,
        )
    assert h.calls == h.ops == []


@pytest.mark.parametrize("args", [(), (1,), (1, 2, 3), (1, 2, 3, 4, 5)])
def test_bound_arity_admission_and_unknown_delegation(args):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(ENTRY, args, None)
    assert h.calls == h.ops == []


def test_explicit_frame_size_and_unknown_entry_refusal():
    with pytest.raises(ValueError):
        ReplayUnitSavedReaderScratch(bytes(0xF17))
    h = setup()
    assert h.bound.call
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.bound.call(0xDEAD, (), None)
    assert h.calls == [(0xDEAD, ())]
