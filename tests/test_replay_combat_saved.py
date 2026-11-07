"""Source-derived normal Combat controls with real Input/Result/tree children.

The component fixture isolates Action explicitly; the final composition runs
real Action/map/behavior/factory and isolates only Moving plus virtual960's
engine effect. Owned initialized tracker backing is an explicit input profile,
not inferred from saved tuples or a claim of native recording identity.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_action_saved import ReplayActionSavedScratch, bind_replay_action_saved
from vantage.replay_action_saved_map import bind_replay_action_saved_map
from vantage.replay_base_saved_leaves import release_replay_base_saved_pair_control
from vantage.replay_behavior_factory import bind_replay_behavior_factory
from vantage.replay_behavior_saved import (
    ReplayBehaviorSavedScratch,
    bind_replay_behavior_saved,
)
from vantage.replay_combat_saved import (
    ReplayCombatSavedScratch,
    bind_replay_combat_saved,
    read_replay_saved_combat,
)
from vantage.replay_combat_saved_tracker import (
    ReplayCombatTrackerScratch,
    bind_replay_combat_saved_tracker,
)
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
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_constructor_maps import bind_replay_unit_constructor_maps

ENTRY, ACTION, MOVING = 0x1411587A0, 0x14113E920, 0x14121F910
VERSION, IO, IO2, TASK, CEIL = 0x1440A0D94, 0xDA01, 0xDA02, 0xDA03, 0xDA04
MODERN, U64 = 0x44E666, (1 << 64) - 1
SCRATCH = ReplayCombatSavedScratch(bytes(range(0xC8)))


def wire_plan(version=MODERN, *, count=0, rows=(), previous=-1):
    """Hand-derived constant-version recipe, with no parent bytes inferred."""
    v = version if version < 0x80000000 else version - (1 << 32)
    plan = []

    def add(label, kind, offset, width, value):
        mask = (1 << (8 * width)) - 1
        plan.append(
            dict(
                label=label,
                kind=kind,
                offset=offset,
                width=width,
                raw=(value & mask).to_bytes(width, "little"),
            )
        )

    if v >= 0x90CCC:
        for offset in (0x51D, 0x51E, 0x51F):
            add(f"{offset:x}", "object", offset, 1, offset)
    add("514", "object", 0x514, 4, 0x7FC01234)
    for offset, width, gate, value in (
        (0x518, 4, 0x423333, 0xFFFFFFFF),
        (0x51C, 1, 0x2028F, 0xC7),
        (0x4FC, 1, 0x9170A, 0x12),
        (0x4FD, 1, 0x9170A, 0xFE),
        (0x4F8, 4, 0xA051E, 0x80000000),
        (0x4A0, 1, 0x1A2E14, 0x87),
    ):
        if v >= gate:
            add(f"{offset:x}", "object", offset, width, value)
    if v >= 0x3D0A3D:
        add("count", "combat", 0xC0, 4, count)
        for i, (key, first, second) in enumerate(rows):
            add(f"first{i}", "combat", 0xC4, 4, first)
            add(f"second{i}", "combat", 0xB8, 4, second)
            if v >= 0x3EE666 and v != 0x3F0000:
                add(f"key{i}", "combat", 0xB0, 4, key)
    if v >= 0x3F8000:
        add("590", "object", 0x590, 4, 0x7F800001)
    if v >= 0x3F9999:
        add("prior", "combat", 0xB0, 2, previous)
        for offset in (0x508, 0x50C, 0x510):
            add(f"{offset:x}", "object", offset, 4, 0x80000000 + offset)
    if v >= 0x403333:
        add("594", "object", 0x594, 1, 0xFF)
    if v >= 0x44B333:
        add("59c", "object", 0x59C, 4, 0xFFC01234)
        add("5a0", "object", 0x5A0, 4, 0xDEADBEEF)
    return plan


def setup(
    *,
    version=MODERN,
    plan=None,
    before=None,
    after=None,
    after_read=None,
    after_write=None,
    real_action=False,
    truncate=None,
):
    h = SimpleNamespace()
    h.m = m = ReplayMemory()
    h.obj, h.out, h.stream, h.vtable, h.vtable2, h.master, h.owner, h.master_table, h.nil = (
        m.allocate(size) for size in (0xA00, 48, 8, 0x1000, 0x1000, 0x300, 0x40, 0x40, 40)
    )
    m.write_bytes(h.obj, b"\xa5" * 0xA00)
    m.write_bytes(h.out, b"O" * 48)
    m.write(h.obj, 8, h.vtable)
    m.write(h.obj + 16, 8, (h.master + 0x774A063B3D17506C) & U64)
    m.write(h.obj + 24, 8, h.owner)
    m.write(h.owner + 40, 8, h.master_table + 16)
    m.write(h.master_table, 8, 0xFEED0002)  # Signed -2 is backed explicitly.
    m.write(h.master_table + 16, 8, 0xFEED0000)
    m.write(h.master + 0x228, 8, 0)
    m.write(h.stream, 8, h.vtable)
    m.write(h.vtable + 24, 8, IO)
    m.write(h.vtable2 + 24, 8, IO2)
    m.write(h.vtable + 0x960, 8, TASK)
    m.write(h.vtable2 + 0x960, 8, TASK)
    m.write(h.vtable + 0x8F8, 8, 0x14113B370)
    # Explicit initialized current tracker profile (not a saved-count inference).
    m.write_bytes(h.nil, b"N" * 40)
    for offset in (0, 8, 16):
        m.write(h.nil + offset, 8, h.nil)
    m.write(h.nil + 24, 2, 0x101)
    m.write(h.obj + 0x520, 8, h.nil)
    m.write(h.obj + 0x528, 8, 0)
    for address, width, value in (
        (VERSION, 4, version & 0xFFFFFFFF),
        (0x143199DD0, 8, 0x142D6BAB4),
        (0x143199EF0, 8, CEIL),
        (0x1436A0308, 4, 0x5F000000),
    ):
        m.map_bytes(address, value.to_bytes(width, "little"))
    h.frames, h.finished, h.events, h.ops, h.reads = [], [], [], [], []
    h.missing, h.handlers = set(), {}
    h.opaque = 0xFEDCBA9876543210
    h.plan = wire_plan(version) if plan is None else plan
    if real_action:
        h.plan = [
            dict(label="a428", kind="object", offset=0x428, width=1, raw=b"\x17"),
            dict(label="a42c", kind="object", offset=0x42C, width=4, raw=bytes(4)),
            dict(label="a430", kind="object", offset=0x430, width=4, raw=bytes(4)),
            dict(label="a434", kind="object", offset=0x434, width=4, raw=bytes(4)),
            dict(
                label="acount", kind="action", offset=0xA8, width=8, raw=(1).to_bytes(8, "little")
            ),
            dict(label="akey", kind="action", offset=0xA0, width=4, raw=(99).to_bytes(4, "little")),
            dict(
                label="avalue",
                kind="action",
                offset=0x9C,
                width=4,
                raw=(0x7FC01234).to_bytes(4, "little"),
            ),
            dict(label="tag", kind="behavior", offset=0x68, width=2, raw=bytes(2)),
            *h.plan,
        ]
    wire = b"".join(r["raw"] for r in h.plan)
    h.source = ReplaySavedInput(wire if truncate is None else wire[:truncate])

    def read(address, width):
        value = m.read(address, width)
        h.ops.append(("read", address, width, value))
        if after_read:
            after_read(h, address, width, value)
        return value

    def write(address, width, value):
        m.write(address, width, value)
        h.ops.append(("write", address, width, value))
        if after_write:
            after_write(h, address, width, value)

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

    def terminal(target, args, data):
        assert runtime.call
        return runtime.call(0x142D6E453 if target == CEIL else target, args, data)

    h.imports = ReplayTaskRebuildCalls(terminal)

    def dispatch(target, args, data):
        h.events.append((target, args))
        if target in h.missing:
            raise UnresolvedReplayTaskRebuild(f"missing actual child{target:x}")
        if before:
            before(h, target, args)
        if target in (IO, IO2):
            row = h.plan[len(h.reads)]
            if row["kind"] == "object":
                base = h.obj
            else:
                size = {"combat": 0xC8, "action": 0xB0, "behavior": 0xD0}[row["kind"]]
                base = next(p for p, view in h.frames if len(view) == size)
            assert args[2:] == (base + row["offset"], row["width"])
            h.reads.append((row["label"], args))
        if target == ACTION and not real_action:
            assert args == (h.obj, h.frames[0][0] + 0x48, h.stream, h.opaque)
            answer = 0xDEADBEEF  # Explicit isolated Action predecessor fixture.
        elif target == MOVING:
            assert real_action and args[0] == h.obj and args[3] == h.opaque
            answer = 0xDEADBEEF  # Explicit isolated Moving predecessor fixture.
        elif target == TASK:
            assert args[0] == h.obj
            answer = None  # Required engine virtual960 fixture, not task rebuild proof.
        elif target == 0x1408EE150:
            release_replay_base_saved_pair_control(
                h.context,
                args[0],
                calls=h.graph,
                atomics=h.atomics,
            )
            answer = None
        elif target in h.handlers:
            answer = h.handlers[target](target, args, data)
        else:
            answer = terminal(target, args, data)
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
        bind_replay_saved_result(h.context, h.graph, atomics=h.atomics, imports=h.imports),
        (0x1402BD7F0, 0x1402BD890, 0x140900620),
    )
    register(
        bind_replay_saved_apply(h.context, h.graph, atomics=h.atomics, imports=h.imports),
        (0x1409076B0, 0x1402B9080),
    )
    for io in (IO, IO2):
        register(
            bind_replay_saved_input(
                h.context,
                h.graph,
                h.source,
                stream=h.stream,
                target=io,
                result_bytes=bytes(48),
            ),
            (io,),
        )
    register(
        bind_replay_saved_position(h.context, h.graph, atomics=h.atomics, bind_local=local),
        (0x140D94310, 0x140D07EE0),
    )
    register(
        bind_replay_combat_saved_tracker(
            h.context,
            h.graph,
            bind_local=local,
            scratch=ReplayCombatTrackerScratch(bytes(range(64))),
            imports=h.imports,
        ),
        (0x1411445A0, 0x14114DB00, 0x1402AB280),
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
            bind_local=local,
            scratch=ReplayBehaviorSavedScratch(bytes(range(0xD0))),
        ),
        (0x140B88C50,),
    )
    register(
        bind_replay_unit_constructor_maps(h.context, h.graph, bind_local=local),
        (0x141136CA0, 0x14113A360, 0x141136C10, 0x14113B410),
    )
    register(
        bind_replay_action_saved_map(h.context, h.graph, mxcsr=0x1F80),
        (0x1411369A0, 0x14113A430, 0x142D6E453, 0x142D66698),
    )
    register(
        bind_replay_action_saved(
            h.context,
            h.graph,
            atomics=h.atomics,
            bind_local=local,
            scratch=ReplayActionSavedScratch(bytes(range(0xB0))),
        ),
        (ACTION,),
    )
    h.bound = bind_replay_combat_saved(
        h.context,
        h.graph,
        atomics=h.atomics,
        bind_local=local,
        scratch=SCRATCH,
    )
    if real_action:
        assert h.graph.call
        h.graph.call(0x141136CA0, (h.obj + 0x460,), None)
        h.events.clear()
        h.ops.clear()
    return h


def invoke(h, *, direct=False):
    if direct:
        return read_replay_saved_combat(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            calls=h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
        )
    assert h.bound.call
    return h.bound.call(ENTRY, (h.obj, h.out, h.stream, h.opaque), None)


def tracker_items(h):
    def walk(node):
        if node == h.nil:
            return []
        return [
            *walk(h.m.read(node, 8)),
            (h.m.read(node + 28, 4), h.m.read(node + 32, 8)),
            *walk(h.m.read(node + 16, 8)),
        ]

    return dict(walk(h.m.read(h.nil + 8, 8)))


@pytest.mark.parametrize(
    "version",
    [
        0,
        0x2028E,
        0x2028F,
        0x90CCB,
        0x90CCC,
        0x91709,
        0x9170A,
        0xA051D,
        0xA051E,
        0x1A2E13,
        0x1A2E14,
        0x3D0A3C,
        0x3D0A3D,
        0x3F7FFF,
        0x3F8000,
        0x3F9998,
        0x3F9999,
        0x403332,
        0x403333,
        0x423332,
        0x423333,
        0x44B332,
        0x44B333,
        0x80000000,
        0xFFFFFFFF,
    ],
)
@pytest.mark.parametrize("direct", [False, True])
def test_all_signed_version_edges_and_constructor_preservation(version, direct):
    h = setup(version=version)
    before = h.m.read_bytes(h.obj, 0xA00)
    assert invoke(h, direct=direct) == h.out
    assert len(h.reads) == len(h.plan) and h.source.position == sum(r["width"] for r in h.plan)
    assert h.m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    selected = {r["offset"] for r in h.plan if r["kind"] == "object"}
    for offset, width in (
        (0x518, 4),
        (0x51C, 1),
        (0x4F8, 4),
        (0x590, 4),
        (0x594, 1),
        (0x59C, 4),
        (0x5A0, 4),
    ):
        if offset not in selected:
            assert h.m.read_bytes(h.obj + offset, width) == before[offset : offset + width]
    assert h.m.read(h.obj + 15, 1) == 0x32
    assert h.events[-1] == (TASK, (h.obj, 0))
    assert all(h.m.read(h.obj + offset, 8) == 0 for offset in range(0x4A8, 0x4F8, 8))


@pytest.mark.parametrize(
    "version,expected_key",
    [(MODERN, 7), (0x3F0000, 0xFFFFFFFF), (0x3EE665, 0xFFFFFFFF), (0x3EE666, 7)],
)
def test_real_tracker_positive_and_duplicate_current_values(version, expected_key):
    rows = [(7, 0x7FC00001, 0x80000000), (7, 0xFFFFFFFF, 0x12345678)]
    h = setup(version=version, plan=wire_plan(version, count=2, rows=rows))
    invoke(h)
    assert tracker_items(h) == {expected_key: 0x12345678FFFFFFFF}
    assert h.m.read(h.obj + 0x528, 8) == 1


@pytest.mark.parametrize("count", [0x80000000, 0xFFFFFFFF])
def test_negative_signed_count_does_not_clear_existing_tracker(count):
    h = setup(plan=wire_plan(count=count))
    key = h.m.allocate(4)
    h.m.write(key, 4, 9)
    assert h.graph.call
    slot = h.graph.call(0x1411445A0, (h.obj + 0x520, key), None)
    h.m.write(slot, 8, 123)
    invoke(h)
    assert tracker_items(h) == {9: 123}


@pytest.mark.parametrize("previous,expected", [(-1, 0), (0, 0xFEED0000), (-2, 0xFEED0002)])
def test_previous_master_is_current_signed16_with_only_minus_one_sentinel(previous, expected):
    h = setup(plan=wire_plan(previous=previous))
    invoke(h)
    assert h.m.read(h.obj + 0x500, 8) == expected


def test_tracker_child_mutates_live_tuple_and_count_before_caller_rereads():
    def after(h, target, args, answer):
        if target == 0x1411445A0:
            frame = h.frames[0][0]
            h.m.write(frame + 0x38, 8, 0xDEADBEEF01020304)
            h.m.write(frame + 0xC0, 4, 1)

    h = setup(plan=wire_plan(count=3, rows=[(8, 10, 20)]), after=after)
    invoke(h)
    assert tracker_items(h) == {8: 0xDEADBEEF01020304}


def test_current_version_skip_reload_and_current_stream_vptr():
    # The514 completion lowers the next current gate; skipping518 must not
    # perform an extra global read that could restore later groups.
    plan = wire_plan(0)

    def after(h, target, args, answer):
        if target == IO and args[2] == h.obj + 0x514:
            h.m.write(h.stream, 8, h.vtable2)

    h = setup(version=0, plan=plan, after=after)
    invoke(h)
    versions = [e for e in h.ops if e[:3] == ("read", VERSION, 4)]
    assert len(versions) == 2  # first direct CMP, then held chain after514.


def test_stream_virtual_is_reloaded_between_raw_calls():
    def after(h, target, args, answer):
        if target == IO and h.reads[-1][0] == "51d":
            h.m.write(h.stream, 8, h.vtable2)

    h = setup(after=after)
    invoke(h)
    inputs = [target for target, _ in h.events if target in (IO, IO2)]
    assert inputs[0] == IO and all(target == IO2 for target in inputs[1:])


def test_shared_release_holds_control_but_refreshes_vptr_after_destroy():
    control = replacement = table = table2 = None

    def after(h, target, args, answer):
        if target == IO and h.reads[-1][0] == "514":
            h.m.write(args[1] + 32, 8, control)

    h = setup(after=after)
    control, replacement, table, table2 = (h.m.allocate(n) for n in (16, 16, 16, 16))
    h.m.write(control, 8, table)
    h.m.write(control + 8, 4, 1)
    h.m.write(control + 12, 4, 1)
    h.m.write(table, 8, 0xD111)
    h.m.write(table + 8, 8, 0xD112)
    h.m.write(table2 + 8, 8, 0xD113)
    calls = []

    def destroy(target, args, data):
        calls.append((target, args))
        h.m.write(control, 8, table2)
        h.m.write(h.frames[0][0] + 0x68, 8, replacement)

    def dispose(target, args, data):
        calls.append((target, args))

    h.handlers[0xD111] = destroy
    h.handlers[0xD113] = dispose
    invoke(h)
    assert calls == [(0xD111, (control,)), (0xD113, (control,))]
    assert h.m.read(control + 8, 4) == h.m.read(control + 12, 4) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        h.m.read(replacement + 8, 4)


def test_current_secondary_status_is_checked_after_raw_cleanup():
    def after(h, target, args, answer):
        if target == 0x1402BD7F0 and h.reads and h.reads[-1][0] == "prior":
            h.m.write(h.frames[0][0] + 0x90, 8, 0xBAD)

    h = setup(after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="decoration/TLS"):
        invoke(h)
    frame = h.finished[-1][1]
    assert frame[0x70] == 1 and frame[0xA0] == 0
    assert h.m.read(h.obj + 0x500, 8) == 0xA5A5A5A5A5A5A5A5


def test_count_cleanup_can_change_current_signed_count_before_loop():
    def after(h, target, args, answer):
        if target == 0x140900620 and h.reads and h.reads[-1][0] == "count":
            h.m.write(h.frames[0][0] + 0xC0, 4, 0xFFFFFFFF)

    h = setup(plan=wire_plan(count=123), after=after)
    invoke(h)
    assert tracker_items(h) == {} and h.m.read(h.obj + 0x528, 8) == 0


def test_current_master_local_decode_rereads_after_each_store():
    changed = False

    def mutate(h, address, width, value):
        nonlocal changed
        if h.frames and address == h.frames[0][0] + 0xB8 and width == 8 and not changed:
            changed = True
            h.m.write(address, 8, h.master + 0x774A063B3D17506C)

    h = setup(version=0, after_write=mutate)
    h.m.write(h.obj + 16, 8, 0)
    invoke(h)
    assert h.events[-1] == (TASK, (h.obj, 0))


def test_wrapper_return_is_ignored_and_fixed_result_status_used():
    def after(h, target, args, answer):
        if target in (0x140D94310, 0x140D07EE0):
            return 0xFFFFFFFFFFFFFFFF

    h = setup(after=after)
    assert invoke(h) == h.out
    assert h.m.read(h.obj + 0x5A0, 4) == 0xDEADBEEF


@pytest.mark.parametrize("label,processed", [("514", 0), ("prior", 1), ("59c", 1)])
def test_error_frontier_preserves_phase_specific_processed_and_prior_writes(label, processed):
    def after(h, target, args, answer):
        if target in (IO, IO2) and h.reads[-1][0] == label:
            h.m.write(args[1] + 24, 8, 0xBAD)

    h = setup(after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="decoration/TLS"):
        invoke(h)
    result = h.finished[-1][1]
    assert result[0x70] == processed
    assert h.m.read(h.obj + 15, 1) == 0x32
    assert h.m.read_bytes(h.out, 48) == b"O" * 48
    assert not any(target == TASK for target, _ in h.events)


@pytest.mark.parametrize(
    "child", [ACTION, 0x1402BD7F0, 0x140900620, 0x1409076B0, 0x140D94310, TASK]
)
def test_mandatory_child_failure_keeps_prior_state_and_output_unpublished(child):
    h = setup()
    h.missing.add(child)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="missing actual child"):
        invoke(h)
    assert h.m.read(h.obj + 0x4F0, 8) == 0
    assert h.m.read_bytes(h.out, 48) == b"O" * 48


def test_truncated_real_input_retains_prior_restored_scalars():
    h = setup(truncate=4)
    with pytest.raises((ValueError, ReplayMemoryError)):
        invoke(h)
    assert h.source.position == 3
    assert h.m.read(h.obj + 0x51F, 1) == 0x1F
    assert h.m.read(h.obj + 0x514, 4) == 0xA5A5A5A5


def test_complete_real_action_map_behavior_factory_tracker_and_input_composition():
    rows = [(5, 0x01020304, 0x80000000), (-2, 1, 2), (5, 9, 10)]
    h = setup(real_action=True, plan=wire_plan(count=3, rows=rows))
    assert invoke(h) == h.out
    assert h.source.position == sum(r["width"] for r in h.plan)
    assert tracker_items(h) == {5: 0xA00000009, 0xFFFFFFFE: 0x200000001}
    manager = h.m.read(h.obj + 0x420, 8)
    assert h.m.read_bytes(manager, 24) == (
        (0x143226988).to_bytes(8, "little") + h.obj.to_bytes(8, "little") + bytes(8)
    )
    sentinel = h.m.read(h.obj + 0x468, 8)
    node = h.m.read(sentinel + 8, 8)
    assert h.m.read(node + 16, 4) == 99 and h.m.read(node + 20, 4) == 0x7FC01234
    assert any(target == MOVING for target, _ in h.events)
    assert any(target == 0x14113B370 for target, _ in h.events)
    assert h.m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7


@pytest.mark.parametrize("args", [(), (1,), (1, 2, 3), (1, 2, 3, 4, 5)])
def test_bound_arity_rejects_before_body_effects(args):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(ENTRY, args, None)
    assert h.events == [] and h.ops == []


def test_scratch_admission_and_unknown_entry_delegation():
    with pytest.raises(ValueError):
        ReplayCombatSavedScratch(bytes(0xC7))
    h = setup()
    assert h.bound.call
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.bound.call(0xDEAD, (), None)
    assert h.events == [(0xDEAD, ())]
