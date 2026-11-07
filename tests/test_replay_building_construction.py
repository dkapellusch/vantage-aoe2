"""Whole Building caller phases with real Result/pair/cleanup composition.

The named Unit, saved-reader and engine callbacks are explicit isolated fixture
boundaries. They are never installed by the shipping binder or called native
success. Decoded coordinate expectations are independent raw binary32 inputs.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_building_construction import (
    ReplayBuildingConstructionScratch,
    bind_replay_building_construction,
    construct_replay_building_object,
)
from vantage.replay_memory import ReplayMemory
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

ENTRY, UNIT, READER = 0x14126DAA0, 0x1412A5D60, 0x141297F00
U64 = (1 << 64) - 1
SCRATCH = ReplayBuildingConstructionScratch(bytes((i * 11 + 1) & 255 for i in range(0xD4)))


def setup(*, status=0, reader_status=0, positive=False, before=None, after=None, on_write=None):
    h = SimpleNamespace()
    h.m = m = ReplayMemory()
    h.obj, h.out, h.stream, h.owner = (m.allocate(n) for n in (0xA00, 48, 8, 0x100))
    m.write_bytes(h.obj, b"\xa5" * 0xA00)
    m.write_bytes(h.out, bytes(41) + b"padding")
    m.write(h.out + 24, 8, status)
    m.write(h.obj + 24, 8, h.owner)
    m.write(h.owner + 0x78, 8, 0xABCD)
    h.opaque = 0xFEDCBA9876543210
    h.x, h.y = 0xC0200000, 0x40600000  # -2.5, 3.5 -> truncation -2,3.
    m.write(h.obj + 0x170, 8, (h.x + 0x183CAC30D2441D0E - 0x4C3FBA69E4EA7FD1) & U64)
    m.write(h.obj + 0x178, 8, (h.y + 0x61501AA6ECFD980A - 0x6C5EAB60B426DD28) & U64)
    h.frames, h.finished, h.events, h.ops = [], [], [], []
    h.handlers, h.missing = {}, set()

    def write(address, width, value):
        m.write(address, width, value)
        h.ops.append(("write", address, width, value))
        if on_write:
            on_write(h, address, width, value)

    def read(address, width):
        value = m.read(address, width)
        h.ops.append(("read", address, width, value))
        return value

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

    def call(target, args, data):
        h.events.append((target, args))
        if target in h.missing:
            raise UnresolvedReplayTaskRebuild(f"missing actual child {target:x}")
        if before:
            before(h, target, args)
        if target == UNIT:
            assert args == (h.obj, h.out, h.stream, h.opaque, 0)
            answer = 0xDEADBEEF  # Explicit isolated predecessor, RAX ignored.
        elif target == READER:
            assert args == (h.obj, h.frames[0][0] + 0x38, h.stream, h.opaque)
            m.write_bytes(args[1], bytes(48))
            m.write(args[1] + 24, 8, reader_status)
            answer = args[1]  # Explicit isolated reader Result identity.
        elif target == 0x141285450:
            answer = int(positive)  # Provider supplies the admitted raw AL result.
        elif target == 0x14115F0A0:
            answer = 0xFEDCBA98
        elif target in h.handlers:
            answer = h.handlers[target](target, args, data)
        else:
            assert runtime.call
            answer = runtime.call(target, args, data)
        if after:
            changed = after(h, target, args, answer)
            if changed is not None:
                answer = changed
        return answer

    h.graph = ReplayTaskRebuildCalls(call)
    for bound, targets in (
        (
            bind_replay_saved_result(h.context, h.graph, atomics=h.atomics, imports=runtime),
            (0x1402BD7F0, 0x1402BD890, 0x140900620),
        ),
        (
            bind_replay_saved_apply(h.context, h.graph, atomics=h.atomics, imports=runtime),
            (0x1409076B0, 0x1402B9080),
        ),
        (bind_replay_saved_pair(h.context, h.graph, atomics=h.atomics), (0x14090D270,)),
    ):
        assert bound.call
        for target in targets:
            h.handlers[target] = bound.call
    h.bound = bind_replay_building_construction(
        h.context, h.graph, atomics=h.atomics, bind_local=local, scratch=SCRATCH, mxcsr=0x1F80
    )
    return h


def invoke(h, flag=0, *, direct=False):
    if direct:
        return construct_replay_building_object(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            flag,
            calls=h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
            mxcsr=0x1F80,
        )
    assert h.bound.call
    return h.bound.call(ENTRY, (h.obj, h.out, h.stream, h.opaque, flag), None)


@pytest.mark.parametrize("direct", (False, True))
@pytest.mark.parametrize("flag", (0, 1, 0xFFFFFFFF, 1 << 32))
def test_whole_constructor_actual_results_and_flag_width(direct, flag):
    h = setup()
    assert invoke(h, flag, direct=direct) == h.obj
    assert h.m.read(h.obj, 8) == 0x1432B5FC8
    assert h.m.read(h.obj + 0x8B0, 8) == 0xFFFFFFFFFFFF0000
    assert h.m.read(h.obj + 0x930, 8) == 1
    assert h.m.read(h.obj + 0x9A8, 8) == 32
    assert h.m.read(h.obj + 0x8F0, 4) == 0xFFFFFFFF
    assert h.m.read(h.obj + 0x8F4, 2) == 0xFFFF
    assert h.m.read_bytes(h.obj + 0x84C, 4) == b"\0\0\xa5\xa5"
    assert h.m.read_bytes(h.obj + 0x938, 8) == b"\xff" + b"\xa5" * 7
    assert h.m.read(h.obj + 0x951, 1) == 0xA5  # No invented initialization.
    assert h.m.read(h.obj + 0x1C4, 1) == 1
    assert h.m.read(h.out + 24, 8) == 0
    assert h.m.read_bytes(h.out + 41, 7) == b"padding"
    assert sum(t == READER for t, _ in h.events) == bool(flag & 0xFFFFFFFF)
    assert h.finished[-1][1][0xD0:] == (flag & 0xFFFFFFFF).to_bytes(4, "little")


def test_parent_error_keeps_initial_stores_but_skips_success_reset_and_reader():
    h = setup(status=5)
    assert invoke(h, 1) == h.obj
    assert h.m.read(h.obj + 0x828, 8) == 0
    assert h.m.read(h.obj + 0x870, 8) == 0xA5A5A5A5A5A5A5A5
    assert h.m.read(h.out + 24, 8) == 5
    assert not any(t in (READER, 0x141285450) for t, _ in h.events)


def test_reader_error_propagates_and_skips_post_read_callbacks():
    h = setup(reader_status=13)
    invoke(h, 1)
    assert h.m.read(h.out + 24, 8) == 13
    assert not any(t == 0x141285450 for t, _ in h.events)


def test_late_fifth_slot_and_current_vector_begin_are_live():
    def after(h, target, args, answer):
        if target == 0x1409076B0:
            frame = h.frames[0][0]
            h.m.write(frame + 0xD0, 4, 1)
            h.m.write(h.obj + 0x828, 8, 0x12345678)
            h.m.write(h.obj + 0x830, 8, 0x99999999)

    h = setup(after=after)
    invoke(h, 0)
    assert any(t == READER for t, _ in h.events)
    assert h.m.read(h.obj + 0x830, 8) == 0x12345678


@pytest.mark.parametrize(
    "raw,active",
    (
        (0, 0),
        (0x80000000, 0),
        (0x1, 1),
        (0x80000001, 1),
        (0x7FC01234, 1),
        (0xFFC01234, 1),
        (0x7F800000, 1),
    ),
)
def test_post_read_active_gate_signed_zero_subnormals_nan(raw, active):
    def after(h, target, args, answer):
        if target == READER:
            h.m.write(h.obj + 0x951, 1, 0)
            h.m.write(h.obj + 0x900, 4, raw)

    h = setup(after=after)
    invoke(h, 1)
    assert h.m.read(h.obj + 0x1C4, 1) == active


@pytest.mark.parametrize(
    "x,y,expected",
    (
        (0xC0200000, 0x40600000, (0xFFFFFFFE, 3)),
        (0x80000000, 0x3F7FFFFF, (0, 0)),
        (0x7FC01234, 0x7F800000, (0x80000000, 0x80000000)),
        (0x4F000000, 0xCF000000, (0x80000000, 0x80000000)),
    ),
)
def test_protected_coordinate_stages_and_real_selected_return(x, y, expected):
    h = setup(positive=True)
    h.m.write(h.obj + 0x170, 8, (x + 0x183CAC30D2441D0E - 0x4C3FBA69E4EA7FD1) & U64)
    h.m.write(h.obj + 0x178, 8, (y + 0x61501AA6ECFD980A - 0x6C5EAB60B426DD28) & U64)
    invoke(h)
    args = next(args for target, args in h.events if target == 0x14115F0A0)
    assert args == (0xABCD, h.obj, *expected)
    assert h.m.read(h.obj + 0x954, 4) == 0xFEDCBA98


def test_held_recipient_survives_later_decode_backing_mutation():
    def write(h, address, width, value):
        if h.frames and address == h.frames[0][0] + 0xB8:
            h.m.write(h.owner + 0x78, 8, 0xF00D)

    h = setup(positive=True, on_write=write)
    invoke(h)
    args = next(args for target, args in h.events if target == 0x14115F0A0)
    assert args[0] == 0xABCD


@pytest.mark.parametrize(
    "target", (UNIT, 0x1409076B0, 0x14090D270, 0x1402BD890, READER, 0x141285450, 0x14115F0A0)
)
def test_required_children_refuse_and_keep_prior_effects(target):
    h = setup(positive=True)
    h.missing.add(target)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="missing actual child"):
        invoke(h, 1)
    assert not h.frames
    if target != UNIT:
        assert h.m.read(h.obj, 8) == 0x1432B5FC8


@pytest.mark.parametrize("size", (0, 0xD3, 0xD5))
def test_constructor_seed_exact_size(size):
    with pytest.raises(ValueError):
        ReplayBuildingConstructionScratch(bytes(size))


@pytest.mark.parametrize("mxcsr", (0, 0x9FC0, True, 0x1F81))
def test_constructor_invalid_profile_before_any_mutation(mxcsr):
    h = setup()
    with pytest.raises(ValueError):
        construct_replay_building_object(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            0,
            calls=h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
            mxcsr=mxcsr,
        )
    assert not h.events and not h.ops


def test_constructor_binder_strict_arity_data_and_unknown():
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError):
        h.bound.call(ENTRY, (h.obj,), None)
    with pytest.raises(ValueError):
        h.bound.call(ENTRY, (h.obj, h.out, h.stream, h.opaque, 0), memoryview(b"x"))
    unavailable = bind_replay_building_construction(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.local,
        scratch=SCRATCH,
        mxcsr=0x1F80,
    )
    assert unavailable.call
    with pytest.raises(UnresolvedReplayTaskRebuild):
        unavailable.call(0xBADBAD, (), None)
