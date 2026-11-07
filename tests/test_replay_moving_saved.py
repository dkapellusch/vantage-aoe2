"""Owned direct I/O and real Result effects for two complete Moving callers.

Animated/selected virtuals and optional unported children are named explicit
fixture boundaries. Scripted optional-child cases audit caller continuation;
they do not claim full native path/point implementations or restore success.
Default optional path/point providers refuse when actually reached.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_memory import ReplayMemory
from vantage.replay_moving_saved import (
    ReplayMovingSavedScratch,
    bind_replay_moving_saved,
    read_replay_saved_moving,
    reset_replay_saved_moving,
)
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

READER, RESET, PARENT = 0x14121F910, 0x141218E80, 0x141142A70
IO, IO2 = 0xBA01, 0xBA02
SELECTED, SELECTED2, SELECTED3 = 0xCA01, 0xCA02, 0xCA03
ALLOCATE, FREE = 0x142D6BA78, 0x142D6BAB4
NODE, PATH, MOTION, FIRST, SECOND, POINTS = (
    0x14106A180,
    0x14106FC40,
    0x14106A0F0,
    0x141075100,
    0x141074E50,
    0x14121A010,
)
CLEANUP, FINALIZE, VERSION = 0x1402BD890, 0x140900620, 0x1440A0D94
MODERN, U32, U64 = 0x44E666, (1 << 32) - 1, (1 << 64) - 1
SCRATCH = ReplayMovingSavedScratch(bytes(range(0xD8)))


def wire_plan(version=MODERN, *, primary=0, secondary=0, motion=0, points=0):
    """Hand-led fixed-version caller read sequence; no parent/path wire implied."""
    plan = []

    def add(label, kind, offset, width, value=None):
        if value is None:
            value = int.from_bytes(
                bytes((len(plan) * 7 + i + 1) & 255 for i in range(width)), "little"
            )
        plan.append(
            dict(
                label=label,
                kind=kind,
                offset=offset,
                width=width,
                raw=(value & ((1 << (width * 8)) - 1)).to_bytes(width, "little"),
            )
        )

    for offset in (0x370, 0x374, 0x378, 0x37C, 0x380, 0x384):
        add(f"{offset:x}", "object", offset, 4)
    if version < 0x240000:
        for i, offset in enumerate((0xB0, 0xC8, 0xC8, 0xC8)):
            add(f"discard{i}", "frame", offset, 4)
    add("391", "object", 0x391, 1)
    add("392", "object", 0x392, 1)
    if 0xCE3D7 <= version < 0xD3333:
        add("legacy75first", "frame", 0x75, 1, 0xFF)
        add("legacy75second", "frame", 0x75, 1, 0x80)
    if version >= 0x9947A:
        add("390", "object", 0x390, 1)
    if version >= 0xD3333:
        add("393", "object", 0x393, 1)
    add("primary", "frame", 0xD0, 4, primary)
    if version >= 0xA1999:
        add("secondary", "frame", 0xC8, 4, secondary)
    add("motion", "frame", 0xD4, 4, motion)
    if motion == 1:
        add("motion_first", "frame", 0xB8, 12)
        add("motion_second", "frame", 0xB8, 12)
    for offset in (0x3BC, 0x3C8, 0x3D4):
        add(f"{offset:x}", "object", offset, 12)
    add("408", "object", 0x408, 4)
    if version >= 0x446666:
        add("40c", "object", 0x40C, 4)
    add("points", "frame", 0xA8, 4, points)
    for i in range(max(points, 0)):
        add(f"point{i}", "frame", 0xB8, 12)
    if version >= 0xA0CCC:
        add("3b9", "object", 0x3B9, 1 if version >= 0x250000 else 4)
        add("3e0", "object", 0x3E0, 12)
        if version >= 0xA0F5C:
            add("410", "object", 0x410, 4)
    if version == 0xAA3D7:
        add("aa_discard", "frame", 0xB0, 4)
    if 0xC1999 <= version < 0xD3333:
        add("legacy74", "frame", 0x74, 1)
    if version >= 0xC9EB8:
        for offset in (0x358, 0x35C, 0x360, 0x364):
            add(f"{offset:x}", "object", offset, 4)
    if version >= 0x1A0A3D:
        add("3a0", "object", 0x3A0, 4)
        add("3a4", "object", 0x3A4, 4)
    return plan


def setup(
    plan=None,
    *,
    version=MODERN,
    before=None,
    after=None,
    on_read=None,
    on_write=None,
    optional=None,
):
    h = SimpleNamespace()
    h.memory = m = ReplayMemory()
    h.obj, h.out, h.stream, h.table, h.table2 = (
        m.allocate(n) for n in (0x420, 48, 8, 0x498, 0x498)
    )
    m.write_bytes(h.obj, b"\xa5" * 0x420)
    m.write_bytes(h.out, b"O" * 48)
    m.write(h.obj, 8, h.table)
    for offset in (0x3F0, 0x3F8, 0x400, 0x3B0):
        m.write(h.obj + offset, 8, 0)
    m.write(h.table + 0x490, 8, SELECTED)
    m.write(h.table + 24, 8, IO)
    m.write(h.table2 + 0x490, 8, SELECTED3)
    m.write(h.table2 + 24, 8, IO2)
    m.write(h.stream, 8, h.table)
    m.map_bytes(VERSION, (version & U32).to_bytes(4, "little"))
    m.map_bytes(0x14435505B, b"\0")
    m.map_bytes(0x143199DD0, FREE.to_bytes(8, "little"))
    h.opaque = 0x1234567890ABCDEF
    h.frames, h.finished, h.events, h.operations, h.reads, h.versions, h.allocations = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    h.plan = wire_plan(version) if plan is None else plan
    h.source = ReplaySavedInput(b"".join(row["raw"] for row in h.plan))
    h.parent_done = False

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
    runtime = m.runtime_calls()
    result = bind_replay_saved_result(h.context, runtime, atomics=h.atomics, imports=runtime)
    first = bind_replay_saved_input(
        h.context, result, h.source, stream=h.stream, target=IO, result_bytes=bytes(48)
    )
    input_calls = bind_replay_saved_input(
        h.context, first, h.source, stream=h.stream, target=IO2, result_bytes=bytes(48)
    )

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

    def call(target, args, data):
        h.events.append((target, args, data))
        assert data is None
        if before:
            before(h, target, args)
        if target == PARENT:
            assert args == (h.obj, h.frames[-1][0] + 0x78, h.stream, h.opaque)
            assert m.read_bytes(args[1], 48) == bytes(48)
            # Named predecessor fixture; no implicit native stream or owner.
            h.parent_done = True
            answer = 0xDEADBEEF  # Parent RAX is not the selected Result.
        elif target in (SELECTED, SELECTED2, SELECTED3):
            assert args == (h.obj,)
            answer = None  # Named selected-virtual effect supplied by fixture.
        elif target in (IO, IO2):
            row = h.plan[len(h.reads)]
            expected = (h.obj if row["kind"] == "object" else h.frames[-1][0]) + row["offset"]
            assert args == (h.stream, h.frames[-1][0] + 0x78, expected, row["width"])
            h.reads.append((target, row["label"], args))
            assert input_calls.call
            answer = input_calls.call(target, args, None)
        elif target == ALLOCATE:
            answer = m.allocate(args[0])
            m.write_bytes(answer, b"\xd3" * args[0])
            h.allocations.append(answer)
        elif target in (NODE, PATH, MOTION, FIRST, SECOND, POINTS):
            if optional is None:
                raise UnresolvedReplayTaskRebuild(f"unprovided actual optional child{target:x}")
            answer = optional(h, target, args)
        elif target in (0x14106A330, 0x140B2CFC0):
            answer = None  # Explicit isolated destruction fixture.
        elif target == 0x14101ADB0:
            raise UnresolvedReplayTaskRebuild("unprovided actual lowDL logger ABI")
        else:
            assert input_calls.call
            answer = input_calls.call(target, args, data)
        if after:
            changed = after(h, target, args, answer)
            if changed is not None:
                answer = changed
        return answer

    h.calls = ReplayTaskRebuildCalls(call)
    h.bound = bind_replay_moving_saved(
        h.context,
        h.calls,
        atomics=h.atomics,
        bind_local=local,
        scratch=SCRATCH,
    )
    return h


def invoke(h, *, direct=False):
    if direct:
        return read_replay_saved_moving(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            calls=h.bound,
            atomics=h.atomics,
            bind_local=h.bind_local,
            scratch=SCRATCH,
        )
    assert h.bound.call
    return h.bound.call(READER, (h.obj, h.out, h.stream, h.opaque), None)


def targets(h):
    return [target for target, _args, _data in h.events]


VERSIONS = (
    -1,
    0x99479,
    0x9947A,
    0xA0CCB,
    0xA0CCC,
    0xA0F5B,
    0xA0F5C,
    0xA1998,
    0xA1999,
    0xAA3D7,
    0xC1998,
    0xC1999,
    0xC9EB7,
    0xC9EB8,
    0xCE3D6,
    0xCE3D7,
    0xD3332,
    0xD3333,
    0x1A0A3C,
    0x1A0A3D,
    0x23FFFF,
    0x240000,
    0x24FFFF,
    0x250000,
    0x446665,
    0x446666,
    MODERN,
)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("direct", [False, True])
def test_all_historical_boundaries_real_exact_input_and_result_cleanup(version, direct):
    h = setup(version=version)
    assert invoke(h, direct=direct) == h.out
    assert h.source.remaining == 0 and len(h.reads) == len(h.plan)
    assert h.memory.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    assert h.memory.read(h.obj + 15, 1) == 30
    assert h.memory.read(h.obj + 0x39C, 4) == 0xBF800000
    assert h.memory.read(h.obj + 0x394, 4) == 0
    assert not h.frames and len(h.finished) == 1
    assert targets(h)[:2] == [SELECTED, PARENT]
    assert PATH not in targets(h) and POINTS not in targets(h)
    expected = bytearray(b"\xa5" * 0x420)
    for row in h.plan:
        if row["kind"] == "object":
            expected[row["offset"] : row["offset"] + row["width"]] = row["raw"]
    for offset, width in ((0x370, 24), (0x358, 16), (0x3A0, 8), (0x3BC, 12)):
        if any(row["kind"] == "object" and row["offset"] == offset for row in h.plan):
            assert h.memory.read_bytes(h.obj + offset, width) == expected[offset : offset + width]
    if 0xCE3D7 <= version < 0xD3333:
        assert h.memory.read(h.obj + 0x393, 1) == 1
    if version < 0x9947A:
        assert h.memory.read(h.obj + 0x390, 1) == 0xA5
    if version < 0xD3333 and not 0xCE3D7 <= version < 0xD3333:
        assert h.memory.read(h.obj + 0x393, 1) == 0xA5
    if version < 0x446666:
        assert h.memory.read(h.obj + 0x40C, 4) == 0  # Actual reset408 QWORD covers40c.


def test_modern_hand_count_and_caller_parent_result_is_not_output_initialization():
    h = setup()
    assert sum(row["width"] for row in h.plan) == 129 and len(h.plan) == 28
    invoke(h)
    assert h.source.position == 129
    # One initial parent and9 direct modern reads use inline cleanup; other
    # 19 reads use the real209-byte Result finalizer.
    assert targets(h).count(CLEANUP) == 10
    assert targets(h).count(FINALIZE) == 19


def test_old_unaligned_3b9_dword_really_overwrites_first_saved_vector_byte():
    h = setup(version=0x24FFFF)
    vector = next(row["raw"] for row in h.plan if row["label"] == "3bc")
    old_flag = next(row["raw"] for row in h.plan if row["label"] == "3b9")
    invoke(h)
    assert h.memory.read_bytes(h.obj + 0x3BC, 12) == old_flag[3:] + vector[1:]


def test_parent_error_refuses_after_real_reset_before_family_or_output_defaults():
    def after(h, target, args, _answer):
        if target == PARENT:
            h.memory.write(args[1] + 24, 8, 9)

    h = setup(after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="decoration/TLS"):
        invoke(h)
    assert not h.reads and h.source.position == 0
    assert h.memory.read(h.obj + 0x370, 8) == 0
    assert h.memory.read(h.obj + 15, 1) == 0xA5
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48
    assert CLEANUP not in targets(h) and FINALIZE not in targets(h)


def test_first_raw_error_keeps_actual_bytes_and_does_not_release_control_or_forward():
    def after(h, target, args, _answer):
        if target == IO:
            h.memory.write(args[1] + 24, 8, 7)
            h.memory.write(args[1] + 32, 8, h.control)

    h = setup(after=after)
    h.control = h.memory.allocate(16)
    h.memory.write(h.control + 8, 4, 3)
    h.memory.write(h.control + 12, 4, 8)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="decoration/TLS"):
        invoke(h)
    assert h.source.position == 4 and len(h.reads) == 1
    assert h.memory.read_bytes(h.obj + 0x370, 4) == h.plan[0]["raw"]
    assert h.memory.read(h.control + 8, 4) == 3 and h.memory.read(h.control + 12, 4) == 8
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48
    assert targets(h).count(CLEANUP) == 1  # Parent cleanup only.


@pytest.mark.parametrize("target", [CLEANUP, FINALIZE])
def test_cleanup_refusal_preserves_processed_store_and_stops_without_output_defaults(target):
    def before(h, current, _args):
        if current == target and h.reads:
            raise UnresolvedReplayTaskRebuild("actual cleanup unavailable")

    h = setup(before=before)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="cleanup unavailable"):
        invoke(h)
    assert h.finished[0][1][0xA0] == 1
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48
    assert not h.frames


def test_reset_holds_old_vptr_but_reads_its_current_slot_after_stores():
    def on_write(h, pointer, width, _value):
        if (pointer, width) == (h.obj + 0x370, 8):
            h.memory.write(h.obj, 8, h.table2)
            h.memory.write(h.table + 0x490, 8, SELECTED2)

    h = setup(on_write=on_write)
    reset_replay_saved_moving(h.context, h.obj, calls=h.calls)
    assert targets(h) == [SELECTED2]
    assert h.memory.read(h.obj, 8) == h.table2


def test_reset_holds_3b0_before_scalar_resets_but_later_path_pointers_are_current():
    def before(h, target, args):
        if target == 0x14106A330 and args == (h.paths[0],):
            h.memory.write(h.obj + 0x3F8, 8, h.changed_path)

    def on_write(h, pointer, width, _value):
        if (pointer, width) == (h.obj + 0x408, 8):
            h.memory.write(h.obj + 0x3B0, 8, h.changed_scalar)

    h = setup(before=before, on_write=on_write)
    h.paths = [h.memory.allocate(72) for _ in range(2)]
    h.changed_path = h.memory.allocate(72)
    h.scalar, h.changed_scalar = h.memory.allocate(8), h.memory.allocate(8)
    h.motion = h.memory.allocate(24)
    for offset, pointer in zip(
        (0x3F0, 0x3F8, 0x400, 0x3B0), (*h.paths, h.motion, h.scalar), strict=True
    ):
        h.memory.write(h.obj + offset, 8, pointer)
    reset_replay_saved_moving(h.context, h.obj, calls=h.calls)
    frees = [args for target, args, _ in h.events if target == FREE]
    assert frees == [(h.paths[0], 72), (h.changed_path, 72), (h.motion, 24), (h.scalar, 8)]
    assert h.memory.read(h.obj + 0x3B0, 8) == 0


def test_reset_free_failure_does_not_clear_held_path_slot_or_later_fields():
    def before(_h, target, _args):
        if target == FREE:
            raise UnresolvedReplayTaskRebuild("actual free refused")

    h = setup(before=before)
    path = h.memory.allocate(72)
    h.memory.write(h.obj + 0x3F0, 8, path)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="free refused"):
        reset_replay_saved_moving(h.context, h.obj, calls=h.calls)
    assert h.memory.read(h.obj + 0x3F0, 8) == path
    assert 0x14106A330 in targets(h)
    assert h.memory.read(h.obj + 0x410, 4) == 0xA5A5A5A5


@pytest.mark.parametrize("label", ["370", "3b9"])
def test_current_io_selection_and_special_preclear_held_r10_are_distinct(label):
    def on_write(h, pointer, width, _value):
        if (
            h.parent_done
            and h.frames
            and (pointer, width) == (h.frames[-1][0] + 0x78, 16)
            and h.plan[len(h.reads)]["label"] == label
        ):
            h.memory.write(h.stream, 8, h.table2)

    h = setup(on_write=on_write)
    invoke(h)
    selected = next(target for target, current, _args in h.reads if current == label)
    assert selected == (IO2 if label == "370" else IO)
    if label == "3b9":
        assert next(target for target, current, _args in h.reads if current == "3e0") == IO2


def test_held_version_skip_bypasses_390_393_reload_even_when_global_already_changed():
    def on_read(h, pointer, _width, value):
        if pointer == VERSION and len(h.versions) == 2:
            h.memory.write(VERSION, 4, MODERN)
            return 0x99479
        return value

    plan = [row for row in wire_plan() if row["label"] not in ("390", "393")]
    h = setup(plan, on_read=on_read)
    invoke(h)
    assert h.source.remaining == 0
    assert h.memory.read(h.obj + 0x390, 1) == h.memory.read(h.obj + 0x393, 1) == 0xA5


def test_late_aa_skip_retains_version_through_two_more_gates():
    def on_read(h, pointer, _width, value):
        if pointer == VERSION and h.reads and h.reads[-1][1] == "410":
            h.memory.write(VERSION, 4, MODERN)
            return 0xAA3D6
        return value

    plan = [
        row for row in wire_plan() if row["label"] not in ("358", "35c", "360", "364", "3a0", "3a4")
    ]
    h = setup(plan, on_read=on_read)
    invoke(h)
    assert h.source.remaining == 0
    assert h.memory.read_bytes(h.obj + 0x358, 16) == b"\xa5" * 16


def test_parent_mutations_survive_unselected_optional_fields_without_defaults():
    def after(h, target, _args, _answer):
        if target == PARENT:
            h.memory.write(h.obj + 0x3F8, 8, 0x123400)
            h.memory.write(h.obj + 0x400, 8, 0x567800)
            h.memory.write(h.obj + 0x40C, 4, 0x11223344)

    h = setup(version=0x446665, after=after)
    invoke(h)
    assert h.memory.read(h.obj + 0x3F8, 8) == 0x123400
    assert h.memory.read(h.obj + 0x400, 8) == 0x567800
    assert h.memory.read(h.obj + 0x40C, 4) == 0x11223344


@pytest.mark.parametrize("count", [-1, -(1 << 31)])
def test_signed_nonpositive_point_count_is_published_raw_without_helper(count):
    h = setup(wire_plan(points=count))
    invoke(h)
    assert POINTS not in targets(h)
    assert h.memory.read(h.obj + 0x394, 4) == count & U32


def test_3e0_remains_selected_but_410_reloads_current_version_after_callbacks():
    def after(h, target, _args, _answer):
        if target == IO and h.reads[-1][1] == "3b9":
            h.memory.write(VERSION, 4, 0)

    # After changing the global at3b9,3e0 is still part of the already-selected
    # outer branch. The current410 gate refuses its read; the tail gates skip.
    skip = {"410", "358", "35c", "360", "364", "3a0", "3a4"}
    plan = [row for row in wire_plan() if row["label"] not in skip]
    h = setup(plan, after=after)
    invoke(h)
    assert h.source.remaining == 0
    assert any(label == "3e0" for _target, label, _args in h.reads)
    assert h.memory.read(h.obj + 0x410, 4) == 0


def test_legacy_boolean_uses_current_second_byte_after_finalize_not_cached_io():
    def after(h, target, _args, _answer):
        if target == FINALIZE and h.reads[-1][1] == "legacy75second":
            h.memory.write(h.frames[-1][0] + 0x75, 1, 0)

    h = setup(version=0xCE3D7, after=after)
    invoke(h)
    assert h.memory.read(h.obj + 0x393, 1) == 0


def test_raw_io_return_rax_is_not_result_identity_or_status():
    h = setup(after=lambda _h, target, _args, _answer: U64 if target == IO else None)
    assert invoke(h) == h.out
    assert h.source.remaining == 0


@pytest.mark.parametrize("which", ["primary", "secondary", "points"])
def test_positive_optional_branches_refuse_at_actual_children_without_fake_success(which):
    def optional(h, target, args):
        if target == NODE:
            assert h.memory.read_bytes(args[0], 72) == bytes(72)
            return args[0]  # Declared constructor RAX fixture, no source closure claim.
        raise UnresolvedReplayTaskRebuild(f"actual optional child{target:x} unavailable")

    kwargs = {which: 1}
    h = setup(wire_plan(**kwargs), optional=optional)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual optional child"):
        invoke(h)
    assert targets(h)[-1] == (POINTS if which == "points" else PATH)
    if which == "secondary":
        assert h.memory.read(h.obj + 0x3F8, 8) == h.allocations[-1]
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48


def test_primary_current_head_and_count_after_scripted_reader_cleanup():
    def optional(h, target, args):
        if target == NODE:
            return args[0]
        assert target == PATH
        h.memory.write(h.frames[-1][0] + 0xB0, 8, h.previous)
        h.memory.write(h.frames[-1][0] + 0xD0, 4, 1)
        return 0xDEADBEEF  # The child RAX is ignored; supplied Result stays zero.

    h = setup(wire_plan(primary=2), optional=optional)
    h.previous = h.memory.allocate(72)
    invoke(h)
    assert targets(h).count(PATH) == 1
    assert h.memory.read(h.obj + 0x3F0, 8) == h.allocations[0]
    assert h.memory.read(h.allocations[0] + 8, 8) == h.previous


def test_primary_error_keeps_parent_pointer_without_publishing_new_head():
    def after(h, target, _args, _answer):
        if target == PARENT:
            h.memory.write(h.obj + 0x3F0, 8, h.existing)

    def optional(h, target, args):
        if target == NODE:
            return args[0]
        assert target == PATH
        h.memory.write(args[1] + 24, 8, 6)

    h = setup(wire_plan(primary=1), optional=optional, after=after)
    h.existing = h.memory.allocate(72)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="decoration/TLS"):
        invoke(h)
    assert h.memory.read(h.obj + 0x3F0, 8) == h.existing
    assert h.memory.read(h.allocations[0] + 8, 8) == 0
    assert FREE not in targets(h)


def test_controller_two_real_tuple_inputs_current_pointer_after_finalize_and_passed_four_args():
    def optional(h, target, args):
        if target == MOTION:
            h.memory.write_bytes(args[0], bytes(24))
            return args[0]
        assert target in (FIRST, SECOND)
        assert args[2:] == (0x1432B30E0, 0x327 if target == FIRST else 0x329)
        assert args[0] == h.replacement
        offset = 0 if target == FIRST else 12
        h.memory.write_bytes(args[0] + offset, h.memory.read_bytes(args[1], 12))

    def after(h, target, _args, _answer):
        if target == FINALIZE and h.reads[-1][1] in ("motion_first", "motion_second"):
            h.memory.write(h.obj + 0x400, 8, h.replacement)

    h = setup(wire_plan(motion=1), optional=optional, after=after)
    h.replacement = h.memory.allocate(24)
    h.memory.write_bytes(h.replacement, b"R" * 24)
    invoke(h)
    expected = b"".join(row["raw"] for row in h.plan if row["label"].startswith("motion_"))
    assert h.memory.read_bytes(h.replacement, 24) == expected


def test_points_scripted_reserve_current_count_pointer_and_tuple_after_cleanup():
    def optional(h, target, args):
        assert target == POINTS and args == (h.obj, 3)
        h.memory.write(h.obj + 0x388, 8, h.first_points)
        h.memory.write(h.frames[-1][0] + 0xA8, 4, 1)
        return 1  # Explicit reserve fixture, not a port of the262-byte body.

    def after(h, target, _args, _answer):
        if target == FINALIZE and h.reads[-1][1] == "point0":
            h.memory.write(h.obj + 0x388, 8, h.second_points)
            h.memory.write(h.frames[-1][0] + 0xB8, 8, 0x1122334455667788)
            h.memory.write(h.frames[-1][0] + 0xC0, 4, 0xAABBCCDD)

    plan = [row for row in wire_plan(points=3) if row["label"] not in ("point1", "point2")]
    h = setup(plan, optional=optional, after=after)
    h.first_points, h.second_points = h.memory.allocate(36), h.memory.allocate(36)
    h.memory.write_bytes(h.first_points, b"F" * 36)
    h.memory.write_bytes(h.second_points, b"S" * 36)
    invoke(h)
    assert h.memory.read_bytes(h.first_points, 36) == b"F" * 36
    assert h.memory.read_bytes(h.second_points, 12) == bytes.fromhex("8877665544332211ddccbbaa")
    assert h.memory.read(h.obj + 0x394, 4) == 1


def test_point_destination_is_held_across_qword_store_then_tail_read():
    def optional(h, target, _args):
        assert target == POINTS
        h.memory.write(h.obj + 0x388, 8, h.first_points)
        return U32  # Every nonzero rawEAX selects success, not a signed >0 test.

    def on_write(h, pointer, width, _value):
        if hasattr(h, "first_points") and (pointer, width) == (h.first_points, 8):
            h.memory.write(h.obj + 0x388, 8, h.second_points)
            h.memory.write(h.frames[-1][0] + 0xC0, 4, 0xAABBCCDD)

    h = setup(wire_plan(points=1), optional=optional, on_write=on_write)
    h.first_points, h.second_points = h.memory.allocate(12), h.memory.allocate(12)
    h.memory.write_bytes(h.first_points, b"F" * 12)
    h.memory.write_bytes(h.second_points, b"S" * 12)
    invoke(h)
    row = next(row for row in h.plan if row["label"] == "point0")
    assert h.memory.read_bytes(h.first_points, 12) == row["raw"][:8] + bytes.fromhex("ddccbbaa")
    assert h.memory.read_bytes(h.second_points, 12) == b"S" * 12


def test_point_helper_zero_return_refuses_before_later_reads_or_count_publication():
    h = setup(
        wire_plan(points=1), optional=lambda _h, target, _args: 0 if target == POINTS else None
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="failure decoration/TLS"):
        invoke(h)
    assert h.reads[-1][1] == "points"
    assert h.memory.read(h.obj + 0x394, 4) == 0xA5A5A5A5


def test_null_primary_allocation_still_reaches_required_path_reader_with_null():
    def after(_h, target, _args, _answer):
        return 0 if target == ALLOCATE else None

    h = setup(wire_plan(primary=1), after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="optional child"):
        invoke(h)
    assert NODE not in targets(h)
    assert next(args for target, args, _ in h.events if target == PATH)[0] == 0


def test_logger_enabled_is_mandatory_low_dl_frontier_before_output_success_defaults():
    h = setup()
    h.memory.write(0x14435505B, 1, 255)
    h.memory.map_bytes(0x144355068, (0x1234).to_bytes(8, "little"))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="lowDL logger"):
        invoke(h)
    assert h.source.remaining == 0
    assert h.events[-1][1] == (0x1234, 0x23, 0x1432B31F8, 0, 0)
    assert h.memory.read_bytes(h.out, 48) == b"O" * 48


@pytest.mark.parametrize(
    "entry,arity", [(READER, 0), (READER, 3), (READER, 5), (RESET, 0), (RESET, 2)]
)
def test_binder_strict_effective_arity_before_body(entry, arity):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed Moving"):
        h.bound.call(entry, (1,) * arity, None)
    assert not h.operations and not h.events


def test_missing_actual_selected_virtual_stops_reset_before_parent_or_stream():
    h = setup()
    bound = bind_replay_moving_saved(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SCRATCH,
    )
    assert bound.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{SELECTED:x}"):
        bound.call(READER, (h.obj, h.out, h.stream, h.opaque), None)
    assert h.source.position == 0 and not h.events
    assert h.memory.read(h.obj + 0x370, 8) == 0
    assert h.memory.read(h.obj + 0x3BC, 8) == 0xA5A5A5A5A5A5A5A5


def test_scratch_is_explicit_and_unknown_target_delegates_or_refuses():
    with pytest.raises(ValueError, match="D8-byte"):
        ReplayMovingSavedScratch(bytes(0xD7))
    h = setup()
    assert h.bound.call
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.bound.call(0x123456, (), None)
    assert targets(h) == [0x123456]
