"""Source-derived Action caller controls over owned storage and real children.

Moving is a named isolated predecessor fixture, and manager selection is an
explicit engine virtual fixture. Neither claims native parent/factory closure.
Input bytes, Result cleanup, behavior reader, map constructors/lookup/rehash and
allocation effects execute their actual Python bodies. Unprovided children
refuse; no map/behavior semantic-success leaf substitutes for those bodies.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_action_saved import (
    ReplayActionSavedScratch,
    bind_replay_action_saved,
    read_replay_saved_action,
)
from vantage.replay_action_saved_map import bind_replay_action_saved_map
from vantage.replay_behavior_saved import (
    ReplayBehaviorSavedScratch,
    bind_replay_behavior_saved,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_constructor_maps import bind_replay_unit_constructor_maps

ENTRY, PARENT, LOOKUP, BEHAVIOR = 0x14113E920, 0x14121F910, 0x1411369A0, 0x140B88C50
CLEANUP, VERSION = 0x1402BD890, 0x1440A0D94
IO, IO2, FACTORY, FACTORY2, CEIL = 0xDA01, 0xDA02, 0xDB01, 0xDB02, 0xDC01
DESTROY, DISPOSE, DISPOSE2 = 0xDD01, 0xDD02, 0xDD03
MODERN, U32, U64 = 0x44E666, (1 << 32) - 1, (1 << 64) - 1
SCRATCH = ReplayActionSavedScratch(bytes(range(0xB0)))


def wire_plan(version=MODERN, *, count=0, pairs=()):
    """Hand-led stable-version wire recipe; parent payload excluded explicitly."""
    version = version if version < 0x80000000 else version - (1 << 32)
    rows = []

    def add(label, kind, offset, width, value):
        rows.append(
            dict(
                label=label,
                kind=kind,
                offset=offset,
                width=width,
                raw=(value & ((1 << (8 * width)) - 1)).to_bytes(width, "little"),
            )
        )

    if version < 0x250000:
        add("discard", "action", 0x98, 1, 0x91)
    if version >= 0x68000:
        add("428", "object", 0x428, 1, 0xD3)
    if version >= 0xBE666:
        add("42c", "object", 0x42C, 4, 0x7F800001)
    elif version >= 0xB947A:
        add("42c", "object", 0x42C, 2, 0xBEEF)
    if version >= 0x1A170A:
        add("430", "object", 0x430, 4, 0xDEADBEEF)
        add("434", "object", 0x434, 4, 0xFFFFFFFF)
    if version >= 0x43CCCD:
        add("count", "action", 0xA8, 8, count)
        for i, (key, value) in enumerate(pairs):
            add(f"key{i}", "action", 0xA0, 4, key)
            add(f"value{i}", "action", 0x9C, 4, value)
    add("tag", "behavior", 0x68, 2, 0)
    return rows


def setup(
    plan=None,
    *,
    version=MODERN,
    before=None,
    after=None,
    on_read=None,
    on_write=None,
    truncate=None,
):
    h = SimpleNamespace()
    h.memory = m = ReplayMemory()
    h.obj, h.out, h.stream, h.table, h.table2, h.manager = (
        m.allocate(size) for size in (0x4A0, 48, 8, 0x900, 0x900, 24)
    )
    m.write_bytes(h.obj, b"\xa5" * 0x4A0)
    m.write_bytes(h.out, b"O" * 48)
    m.write_bytes(h.manager, bytes(24))  # Explicit empty existing owned list profile.
    m.write(h.obj, 8, h.table)
    m.write(h.stream, 8, h.table)
    m.write(h.table + 24, 8, IO)
    m.write(h.table2 + 24, 8, IO2)
    m.write(h.table + 0x8F8, 8, FACTORY)
    m.write(h.table2 + 0x8F8, 8, FACTORY2)
    for pointer, value in (
        (VERSION, version & U32),
        (0x143199DD0, 0x142D6BAB4),
        (0x143199EF0, CEIL),
    ):
        m.map_bytes(pointer, value.to_bytes(4 if pointer == VERSION else 8, "little"))
    # Current original static threshold, independently checked in both images.
    m.map_bytes(0x1436A0308, bytes.fromhex("0000005f"), writable=False)
    h.opaque = 0x1234567890ABCDEF
    h.frames, h.finished, h.events, h.operations, h.reads, h.versions = [], [], [], [], [], []
    h.missing = set()
    h.plan = wire_plan(version) if plan is None else plan
    wire = b"".join(row["raw"] for row in h.plan)
    h.source = ReplaySavedInput(wire if truncate is None else wire[:truncate])

    def read(pointer, width):
        value = m.read(pointer, width)
        h.operations.append(("read", pointer, width, value))
        if pointer == VERSION:
            h.versions.append(value)
        if on_read:
            changed = on_read(h, pointer, width, value)
            if changed is not None:
                return changed
        return value

    def write(pointer, width, value):
        h.operations.append(("write", pointer, width, value))
        m.write(pointer, width, value)
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
                h.finished.append((pointer, view.tobytes()))
                h.frames.pop()

    h.bind_local = local
    runtime = m.runtime_calls()

    def terminal(target, args, data):
        if target == CEIL:
            assert runtime.call
            return runtime.call(0x142D6E453, args, data)
        assert runtime.call
        return runtime.call(target, args, data)

    imports = ReplayTaskRebuildCalls(terminal)
    result = bind_replay_saved_result(h.context, imports, atomics=h.atomics, imports=imports)
    first = bind_replay_saved_input(
        h.context, result, h.source, stream=h.stream, target=IO, result_bytes=bytes(48)
    )
    second = bind_replay_saved_input(
        h.context, first, h.source, stream=h.stream, target=IO2, result_bytes=bytes(48)
    )

    def input_call(target, args, data):
        if target in (IO, IO2):
            row = h.plan[len(h.reads)]
            base = (
                h.obj
                if row["kind"] == "object"
                else (h.frames[0][0] if row["kind"] == "action" else h.frames[-1][0])
            )
            assert args[2:] == (base + row["offset"], row["width"])
            h.reads.append((target, row["label"], args))
        assert second.call
        return second.call(target, args, data)

    behavior = bind_replay_behavior_saved(
        h.context,
        ReplayTaskRebuildCalls(input_call),
        atomics=h.atomics,
        bind_local=local,
        scratch=ReplayBehaviorSavedScratch(bytes(range(0xD0))),
    )
    constructors = bind_replay_unit_constructor_maps(h.context, behavior, bind_local=local)
    lower = bind_replay_action_saved_map(h.context, constructors, mxcsr=0x1F80)
    assert constructors.call
    constructors.call(0x141136CA0, (h.obj + 0x460,), None)
    # Construction is a real earlier phase, excluded from Action event assertions.
    h.operations.clear()
    h.finished.clear()

    def call(target, args, data):
        h.events.append((target, args, data))
        if target in h.missing:
            raise UnresolvedReplayTaskRebuild(f"unprovided actual child{target:x}")
        if before:
            before(h, target, args)
        if target == PARENT:
            assert args == (h.obj, h.frames[0][0] + 0x68, h.stream, h.opaque)
            assert m.read_bytes(args[1], 48) == bytes(48)
            # Explicit isolated predecessor fixture, not a native parent port.
            answer = 0xDEADBEEF
        elif target in (FACTORY, FACTORY2):
            assert args == (h.obj,)
            answer = h.manager  # Explicit engine virtual-selection fixture.
        elif target in (DESTROY, DISPOSE, DISPOSE2):
            answer = None  # Explicit engine shared-control destructor fixtures.
        else:
            assert lower.call
            answer = lower.call(target, args, data)
        if after:
            changed = after(h, target, args, answer)
            if changed is not None:
                answer = changed
        return answer

    h.calls = ReplayTaskRebuildCalls(call)
    h.bound = bind_replay_action_saved(
        h.context,
        h.calls,
        atomics=h.atomics,
        bind_local=local,
        scratch=SCRATCH,
    )
    return h


def invoke(h, *, direct=False):
    if direct:
        return read_replay_saved_action(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            calls=h.calls,
            atomics=h.atomics,
            bind_local=h.bind_local,
            scratch=SCRATCH,
        )
    assert h.bound.call
    return h.bound.call(ENTRY, (h.obj, h.out, h.stream, h.opaque), None)


def map_items(h):
    m, header = h.memory, h.obj + 0x460
    sentinel = m.read(header + 8, 8)
    node, items = m.read(sentinel, 8), {}
    while node != sentinel:
        items[m.read(node + 0x10, 4)] = m.read(node + 0x14, 4)
        node = m.read(node, 8)
    return items


@pytest.mark.parametrize(
    "version",
    [
        0,
        0x67FFF,
        0x68000,
        0xB9479,
        0xB947A,
        0xBE665,
        0xBE666,
        0x1A1709,
        0x1A170A,
        0x24FFFF,
        0x250000,
        0x43CCCC,
        0x43CCCD,
        MODERN,
        0x7FFFFFFF,
        0x80000000,
        0xFFFFFFFF,
    ],
)
@pytest.mark.parametrize("direct", [False, True])
def test_all_signed_version_edges_and_exact_owned_input(version, direct):
    h = setup(version=version)
    assert invoke(h, direct=direct) == h.out
    assert h.source.remaining == 0
    assert [row[1] for row in h.reads] == [row["label"] for row in h.plan]
    m = h.memory
    assert m.read(h.obj + 15, 1) == 0x28
    assert m.read(h.obj + 0x420, 8) == h.manager
    assert m.read(h.obj + 0x42A, 2) == 0
    raw = version if version < 0x80000000 else version - (1 << 32)
    assert m.read(h.obj + 0x428, 1) == (0xD3 if raw >= 0x68000 else 0)
    assert m.read(h.obj + 0x42C, 4) == (
        0x7F800001 if raw >= 0xBE666 else 0xA5A5BEEF if raw >= 0xB947A else 0
    )
    assert m.read(h.obj + 0x430, 4) == (0xDEADBEEF if raw >= 0x1A170A else U32)
    assert m.read(h.obj + 0x434, 4) == (U32 if raw >= 0x1A170A else 0)
    assert m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    frame = next(raw for _, raw in h.finished if len(raw) == 0xB0)
    assert frame[0xA4:0xA8] == SCRATCH.reader[0xA4:0xA8]
    assert frame[:0x28] == SCRATCH.reader[:0x28]


def test_real_map_duplicate_and_raw_nan_words_without_clear():
    pairs = ((7, 0x7FC01234), (0xFFFFFFFF, 0x80000000), (7, 0x7F800001))
    h = setup(wire_plan(count=3, pairs=pairs))
    assert invoke(h) == h.out
    assert map_items(h) == {7: 0x7F800001, U32: 0x80000000}
    assert h.memory.read(h.obj + 0x470, 8) == 2
    assert h.source.remaining == 0


def test_real_map_growth_and_held_value_after_source_mutation():
    pairs = tuple((i, 0x7F800001 + i) for i in range(10))

    def before(h, target, args):
        if target == LOOKUP:
            h.memory.write(h.frames[0][0] + 0x9C, 4, 0x11223344)

    h = setup(wire_plan(count=10, pairs=pairs), before=before)
    assert invoke(h) == h.out
    assert map_items(h) == dict(pairs)
    assert h.memory.read(h.obj + 0x498, 8) > 8


def test_unsigned_qword_count_and_current_post_lookup_reload():
    def after(h, target, args, answer):
        if target == LOOKUP:
            h.memory.write(h.frames[0][0] + 0xA8, 8, 0)

    h = setup(wire_plan(count=U64, pairs=((5, 0xFFFFFFFF),)), after=after)
    assert invoke(h) == h.out
    assert map_items(h) == {5: U32}
    assert sum(target == LOOKUP for target, _, _ in h.events) == 1


def test_count_can_grow_after_first_real_insertion():
    pairs = ((1, 11), (2, 22), (3, 33))

    def after(h, target, args, answer):
        if target == LOOKUP:
            h.memory.write(h.frames[0][0] + 0xA8, 8, 3)

    h = setup(wire_plan(count=1, pairs=pairs), after=after)
    assert invoke(h) == h.out
    assert map_items(h) == dict(pairs)


def test_current_count_after_real_cleanup_can_skip_positive_wire_count():
    def after(h, target, args, answer):
        if target == CLEANUP and h.reads and h.reads[-1][1] == "count":
            h.memory.write(h.frames[0][0] + 0xA8, 8, 0)

    h = setup(wire_plan(count=4), after=after)
    assert invoke(h) == h.out
    assert map_items(h) == {}
    assert not any(target == LOOKUP for target, _, _ in h.events)


def test_existing_map_survives_zero_count():
    h = setup()
    key, output = h.memory.allocate(4), h.memory.allocate(16)
    h.memory.write(key, 4, 77)
    assert h.calls.call
    carrier = h.calls.call(LOOKUP, (h.obj + 0x460, output, key), None)
    assert carrier == output
    h.memory.write(h.memory.read(output, 8) + 0x14, 4, 88)
    h.events.clear()
    assert invoke(h) == h.out
    assert map_items(h) == {77: 88}


def test_held_version_skips_reload_and_current_versions_resume():
    def on_read(h, pointer, width, value):
        if pointer == VERSION and len(h.versions) == 1:
            h.memory.write(VERSION, 4, 0)

    plan = [row for row in wire_plan(0x250000) if row["label"] in ("428", "tag")]
    h = setup(plan, version=0x250000, on_read=on_read)
    assert invoke(h) == h.out
    assert h.versions == [0x250000, 0, 0, 0]
    assert [row[1] for row in h.reads] == ["428", "tag"]


def test_version_reload_after_legacy_read_uses_cleanup_mutation():
    def after(h, target, args, answer):
        if target == CLEANUP and h.reads and h.reads[-1][1] == "discard":
            h.memory.write(VERSION, 4, 0x250000)

    plan = wire_plan(0)[:-1] + wire_plan(0x250000)
    h = setup(plan, version=0, after=after)
    assert invoke(h) == h.out
    assert h.versions == [0, 0x250000, 0x250000, 0x250000, 0x250000]


def test_paired_430_434_keeps_selected_gate_after_version_change():
    def after(h, target, args, answer):
        if target in (IO, IO2) and h.reads[-1][1] == "430":
            h.memory.write(VERSION, 4, 0)

    h = setup(wire_plan(0x250000), version=0x250000, after=after)
    assert invoke(h) == h.out
    assert h.memory.read(h.obj + 0x434, 4) == U32


def test_narrow_42c_uses_same_held_version_for_lower_bound():
    def on_read(h, pointer, width, value):
        if pointer == VERSION and len(h.versions) == 3:
            h.memory.write(VERSION, 4, 0xBE666)

    h = setup(wire_plan(0xBE665), version=0xBE665, on_read=on_read)
    assert invoke(h) == h.out
    assert h.memory.read(h.obj + 0x42C, 4) == 0xA5A5BEEF
    assert h.versions == [0xBE665, 0xBE665, 0xBE665, 0xBE666, 0xBE666]


def test_each_input_uses_current_stream_table():
    def after(h, target, args, answer):
        if target == IO and h.reads[-1][1] == "428":
            h.memory.write(h.stream, 8, h.table2)

    h = setup(after=after)
    assert invoke(h) == h.out
    assert [target for target, _, _ in h.reads] == [IO] + [IO2] * 5


def test_factory_current_table_and_held_return_survive_publication_mutation():
    other = []

    def after(h, target, args, answer):
        if target == IO and h.reads[-1][1] == "count":
            h.memory.write(h.obj, 8, h.table2)

    def on_write(h, pointer, width, value):
        if pointer == h.obj + 0x420:
            h.memory.write(pointer, 8, 0xDEADBEEF)
            other.append(value)

    h = setup(after=after, on_write=on_write)
    assert invoke(h) == h.out
    assert other == [h.manager]
    assert any(target == FACTORY2 for target, _, _ in h.events)
    assert next(args[0] for target, args, _ in h.events if target == BEHAVIOR) == h.manager
    assert h.memory.read(h.obj + 0x420, 8) == 0xDEADBEEF


@pytest.mark.parametrize("target", [PARENT, LOOKUP, FACTORY, BEHAVIOR])
def test_missing_actual_children_refuse_at_reached_call(target):
    h = setup(wire_plan(count=1, pairs=((1, 2),)) if target == LOOKUP else None)
    h.missing.add(target)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unprovided actual child"):
        invoke(h)
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48
    assert not h.frames
    if target == PARENT:
        assert h.versions == [] and h.memory.read(h.obj + 15, 1) == 0xA5
    elif target == LOOKUP:
        assert h.source.position == 29 and not map_items(h)
    elif target == FACTORY:
        assert h.memory.read(h.obj + 0x420, 8) == 0xA5A5A5A5A5A5A5A5
    else:
        assert h.memory.read(h.obj + 0x420, 8) == h.manager


@pytest.mark.parametrize(
    "label,version",
    [
        ("discard", 0),
        ("428", MODERN),
        ("42c", MODERN),
        ("42c", 0xB947A),
        ("430", MODERN),
        ("434", MODERN),
        ("count", MODERN),
        ("key0", MODERN),
        ("value0", MODERN),
    ],
)
def test_all_nine_input_sites_stop_at_returned_error_frontier(label, version):
    def after(h, target, args, answer):
        if target in (IO, IO2) and h.reads[-1][1] == label:
            h.memory.write(args[1] + 24, 8, 123)

    pairs = ((9, 10),) if label in ("key0", "value0") else ()
    h = setup(wire_plan(version, count=int(bool(pairs)), pairs=pairs), version=version, after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="decoration/TLS"):
        invoke(h)
    assert h.reads[-1][1] == label
    result = next(raw for _, raw in h.finished if len(raw) == 0xB0)[0x68:0x98]
    assert int.from_bytes(result[24:32], "little") == 123 and result[40] == 0
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48
    assert not any(target == FACTORY for target, _, _ in h.events)


def test_parent_error_does_not_set_action_kind_or_process_result():
    def after(h, target, args, answer):
        if target == PARENT:
            h.memory.write(args[1] + 24, 8, 9)

    h = setup(after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="decoration/TLS"):
        invoke(h)
    assert h.memory.read(h.obj + 15, 1) == 0xA5
    assert len(h.events) == 1 and not h.versions


def test_behavior_error_preserves_publication_and_prior_scalar_effects():
    def after(h, target, args, answer):
        if target == BEHAVIOR:
            h.memory.write(args[1] + 24, 8, 7)

    h = setup(after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="decoration/TLS"):
        invoke(h)
    assert h.memory.read(h.obj + 0x420, 8) == h.manager
    assert h.memory.read(h.obj + 0x430, 4) == 0xDEADBEEF
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48


def test_exact_input_truncation_preserves_prior_field_and_cursor():
    h = setup(truncate=3)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="exceeds remaining"):
        invoke(h)
    assert h.source.position == 1
    assert h.memory.read(h.obj + 0x428, 1) == 0xD3
    assert h.memory.read(h.obj + 0x42C, 4) == 0xA5A5A5A5


def test_actual_shared_control_release_holds_identity_and_reloads_virtual():
    controls = []

    def after(h, target, args, answer):
        if target == PARENT:
            control = h.memory.allocate(16)
            table, table2 = h.memory.allocate(16), h.memory.allocate(16)
            h.memory.write(control, 8, table)
            h.memory.write(control + 8, 4, 1)
            h.memory.write(control + 12, 4, 1)
            h.memory.write(table, 8, DESTROY)
            h.memory.write(table2 + 8, 8, DISPOSE2)
            h.memory.write(args[1] + 32, 8, control)
            controls.append((control, table2, args[1]))
        elif target == DESTROY:
            control, table2, result = controls[0]
            assert args == (control,)
            h.memory.write(control, 8, table2)
            h.memory.write(result + 32, 8, 0)

    h = setup(after=after)
    assert invoke(h) == h.out
    control = controls[0][0]
    assert h.memory.read(control + 8, 4) == h.memory.read(control + 12, 4) == 0
    assert next(args for target, args, _ in h.events if target == DISPOSE2) == (control,)


def test_missing_atomic_refuses_after_processed_write_before_kind_store():
    def after(h, target, args, answer):
        if target == PARENT:
            h.memory.write(args[1] + 32, 8, 0x1234)

    h = setup(after=after)
    h.atomics = ReplayUnitAIMapAtomics(None, None)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        invoke(h, direct=True)
    frame = next(raw for _, raw in h.finished if len(raw) == 0xB0)
    assert frame[0x90] == 1
    assert h.memory.read(h.obj + 15, 1) == 0xA5


@pytest.mark.parametrize("prior", [0, 2])
def test_strong_nonlast_wrap_or_decrement_never_reads_undefined_vptr_or_weak(prior):
    controls = []

    def after(h, target, args, answer):
        if target == PARENT:
            control = h.memory.allocate(16)
            h.memory.write(control + 8, 4, prior)
            h.memory.write(args[1] + 32, 8, control)
            controls.append(control)

    h = setup(after=after)
    assert invoke(h) == h.out
    assert h.memory.read(controls[0] + 8, 4) == (prior - 1) & U32
    assert not any(target in (DESTROY, DISPOSE, DISPOSE2) for target, _, _ in h.events)


def test_destroy_failure_preserves_processed_and_strong_decrement_before_weak():
    controls = []

    def after(h, target, args, answer):
        if target == PARENT:
            control, table = h.memory.allocate(16), h.memory.allocate(8)
            h.memory.write(control, 8, table)
            h.memory.write(control + 8, 4, 1)
            h.memory.write(control + 12, 4, 1)
            h.memory.write(table, 8, DESTROY)
            h.memory.write(args[1] + 32, 8, control)
            controls.append(control)

    h = setup(after=after)
    h.missing.add(DESTROY)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unprovided actual child"):
        invoke(h)
    assert h.memory.read(controls[0] + 8, 4) == 0
    assert h.memory.read(controls[0] + 12, 4) == 1
    assert next(raw for _, raw in h.finished if len(raw) == 0xB0)[0x90] == 1
    assert h.memory.read(h.obj + 15, 1) == 0xA5


def test_missing_real_cleanup_keeps_processed_before_kind_store():
    h = setup()
    h.missing.add(CLEANUP)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unprovided actual child"):
        invoke(h)
    assert next(raw for _, raw in h.finished if len(raw) == 0xB0)[0x90] == 1
    assert h.memory.read(h.obj + 15, 1) == 0xA5
    assert not h.versions


def test_failure_during_final_output_writes_retains_only_reached_stores():
    def on_write(h, pointer, width, value):
        if pointer == h.out + 16:
            raise RuntimeError("owned writer failed after its reached store")

    h = setup(on_write=on_write)
    with pytest.raises(RuntimeError, match="owned writer failed"):
        invoke(h)
    assert h.memory.read_bytes(h.out, 48) == bytes(24) + b"O" * 24
    assert h.memory.read(h.obj + 0x420, 8) == h.manager
    assert not h.frames


def test_current_factory_null_is_published_before_real_reader_refuses():
    def after(h, target, args, answer):
        if target == FACTORY:
            return 0

    h = setup(after=after)
    with pytest.raises(ReplayMemoryError):
        invoke(h)
    assert h.memory.read(h.obj + 0x420, 8) == 0
    assert next(args[0] for target, args, _ in h.events if target == BEHAVIOR) == 0


@pytest.mark.parametrize(
    "args,data",
    [
        ((), None),
        ((1, 2, 3), None),
        ((1, 2, 3, 4, 5), None),
        ((1, 2, 3, 4), memoryview(bytearray(1))),
    ],
)
def test_binder_rejects_malformed_entry_before_effects(args, data):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed Action"):
        h.bound.call(ENTRY, args, data)
    assert not h.events and not h.operations


@pytest.mark.parametrize("seed", [bytes(0xAF), bytes(0xB1), bytearray(0xB0), None])
def test_explicit_frame_seed_is_required(seed):
    with pytest.raises(ValueError, match="B0-byte"):
        ReplayActionSavedScratch(seed)


def test_unknown_entry_delegates_exactly_and_unavailable_refuses():
    h = setup()
    assert h.bound.call
    h.missing.add(0x11223344)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unprovided actual child"):
        h.bound.call(0x11223344, (7, 8), memoryview(bytearray(3)))
    assert h.events[-1][0:2] == (0x11223344, (7, 8))
    empty = bind_replay_action_saved(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SCRATCH,
    )
    assert empty.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        empty.call(0x11223344, (), None)
