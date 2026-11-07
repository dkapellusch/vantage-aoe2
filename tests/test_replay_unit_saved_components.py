"""Owned normal reader phases, real Result effects and explicit child boundaries.

Wrapper/getter/resolver effects below are declared fixture inputs, not native
oracle outputs or an inference that arbitrary callbacks successfully return.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_position import bind_replay_saved_position
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_ai_variants import (
    ReplayUnitAIVariantScratch,
    bind_replay_unit_ai_variants,
)
from vantage.replay_unit_saved_components import (
    ReplayUnitSavedScratch,
    bind_replay_unit_saved_components,
    fixup_replay_saved_graphic,
    read_replay_saved_stinger,
    read_replay_saved_unpack_timer,
)

STINGER, TIMER = 0x1411281D0, 0x1410B1A40
IO, SECOND_IO = 0xA110, 0xA120
FORWARD, CLEANUP = 0x1409076B0, 0x1402BD890
WRAPPER, FLOAT_WRAPPER = 0x140B81D60, 0x140D94310
GET_WORLD, RESOLVE = 0x140D6ACC0, 0x1416028D0
VERSION, GAME = 0x1440A0D94, 0x144353698
U32 = (1 << 32) - 1
SCRATCH = ReplayUnitSavedScratch(bytes(range(0x90)), bytes(range(0x80)))
FIELDS = (0, 4, 12, 16, 20, 24, 28, 32, 36)
WORDS = tuple(0x01234560 + i for i in range(10))


def stinger_wire(sprite=-7, *, modern=True):
    raw = b"".join(word.to_bytes(4, "little") for word in WORDS[:9])
    raw += (sprite & 0xFFFF).to_bytes(2, "little")
    return raw + (WORDS[9].to_bytes(4, "little") if modern else b"")


def setup(raw, *, version=0x44E666, before=None, after=None, absent=(), control=0):
    h = SimpleNamespace()
    h.memory = m = ReplayMemory()
    h.address, h.output, h.stream, h.table, h.game, h.world = (
        m.allocate(n) for n in (56, 48, 8, 32, 8, 8)
    )
    m.write_bytes(h.address, b"D" * 56)
    m.write_bytes(h.output, b"O" * 48)
    m.write(h.stream, 8, h.table)
    m.write(h.table + 24, 8, IO)
    m.map_bytes(VERSION, version.to_bytes(4, "little"))
    m.map_bytes(GAME, h.game.to_bytes(8, "little"))
    m.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))
    h.frames, h.completed_frames, h.events, h.reads, h.storage_events = [], [], [], [], []

    def read(pointer, width):
        h.storage_events.append(("read", pointer, width))
        return m.read(pointer, width)

    def write(pointer, width, value):
        h.storage_events.append(("write", pointer, width, value))
        m.write(pointer, width, value)

    h.context = ReplayTaskRebuildStorage(h.address, read, write)
    h.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)
    h.source = ReplaySavedInput(raw)
    result_bytes = bytearray(48)
    result_bytes[32:40] = control.to_bytes(8, "little")
    runtime = m.runtime_calls()
    h.io = bind_replay_saved_input(
        h.context, runtime, h.source, stream=h.stream, target=IO, result_bytes=bytes(result_bytes)
    )
    strings = bind_replay_saved_string(h.context, h.io, imports=runtime)
    results = bind_replay_saved_result(h.context, strings, atomics=h.atomics, imports=runtime)
    lower = bind_replay_saved_apply(h.context, results, atomics=h.atomics, imports=runtime)

    @contextmanager
    def bind_local(view):
        with m.bind_local(view) as address:
            h.frames.append((address, view))
            try:
                yield address
            finally:
                h.completed_frames.append(view.tobytes())

    h.bind_local = bind_local

    def call(target, args, data):
        h.events.append((target, args, data))
        if before:
            before(h, target, args, data)
        if target in absent:
            raise UnresolvedReplayTaskRebuild(f"declared missing{target:x}")
        if target in (WRAPPER, FLOAT_WRAPPER):
            assert len(args) == 6 and data is None
            result, filename, _line, _field, stream, destination = args
            assert filename == 0x1432A47C0 and stream == h.stream
            assert h.io.call is not None
            # Explicit fixture wrapper effect: real owned4B I/O into its
            # argument, with a declared zero48B Result. Its native body is not
            # part of the two readers being tested.
            answer = h.io.call(IO, (stream, result, destination, 4), None)
        elif target == GET_WORLD:
            assert len(args) == 1 and data is None
            answer = h.world
        elif target == RESOLVE:
            assert len(args) == 3 and data is None
            m.write(args[1], 8, 0x1234567890)
            answer = args[1]
        else:
            if target in (IO, SECOND_IO):
                h.reads.append((h.source.position, target, args))
            assert lower.call is not None
            answer = lower.call(IO if target == SECOND_IO else target, args, data)
        if after:
            changed = after(h, target, args, answer)
            if changed is not None:
                answer = changed
        return answer

    h.calls = ReplayTaskRebuildCalls(call)
    h.bound = bind_replay_unit_saved_components(
        h.context, h.calls, atomics=h.atomics, bind_local=h.bind_local, scratch=SCRATCH
    )
    return h


def invoke(h, entry=STINGER, *, direct=True):
    if direct:
        function = read_replay_saved_stinger if entry == STINGER else read_replay_saved_unpack_timer
        return function(
            h.context,
            h.address,
            h.output,
            h.stream,
            calls=h.calls,
            atomics=h.atomics,
            bind_local=h.bind_local,
            scratch=SCRATCH,
        )
    assert h.bound.call is not None
    return h.bound.call(entry, (h.address, h.output, h.stream), None)


def check_output(h):
    assert h.memory.read_bytes(h.output, 41) == bytes(41)
    assert h.memory.read_bytes(h.output + 41, 7) == b"O" * 7


@pytest.mark.parametrize("direct", [False, True])
def test_timer_exact_width_order_padding_reused_locals_and_real_result_cleanup(direct):
    h = setup(bytes.fromhex("ff7f12345678"))
    assert invoke(h, TIMER, direct=direct) == h.output
    assert h.source.position == 6
    assert h.memory.read_bytes(h.address, 8) == bytes.fromhex("ff7f444412345678")
    assert [(args[2] - h.address, args[3]) for _, _, args in h.reads] == [(0, 2), (4, 4)]
    assert len({args[1] for _, _, args in h.reads}) == 1
    assert len(h.frames) == 1 and len(h.completed_frames) == 1
    frame, _view = h.frames[0]
    assert {args[1] for _, _, args in h.reads} == {frame + 0x47}
    assert h.completed_frames[0][0xF:0x17] == h.output.to_bytes(8, "little")
    assert [t for t, _, _ in h.events] == [IO, FORWARD, CLEANUP, CLEANUP] * 2
    assert h.completed_frames[0][0x3F] == 1  # aggregate processed
    assert h.completed_frames[0][0x6F] == 1  # raw processed
    assert not any(e[1] == VERSION for e in h.storage_events if e[0] == "read")
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.memory.read(frame, 1)
    check_output(h)


@pytest.mark.parametrize("direct", [True])
def test_modern_stinger_42bytes_field_order_wrappers_resolution_and_padding(direct):
    h = setup(stinger_wire())
    assert invoke(h, direct=direct) == h.output and h.source.remaining == 0
    for offset, word in zip(FIELDS, WORDS[:9], strict=True):
        assert h.memory.read(h.address + offset, 4) == word
    assert h.memory.read(h.address + 8, 4) == WORDS[9]
    assert h.memory.read_bytes(h.address + 40, 8) == b"D" * 8
    assert h.memory.read(h.address + 48, 8) == 0x1234567890
    wrappers = [(t, args) for t, args, _ in h.events if t in (WRAPPER, FLOAT_WRAPPER)]
    assert [(t, a[2], a[3], a[5] - h.address) for t, a in wrappers] == [
        (WRAPPER, 17, 0x1432A4820, 12),
        (WRAPPER, 18, 0x1432A482C, 16),
        (WRAPPER, 19, 0x1432A4838, 20),
        (FLOAT_WRAPPER, 20, 0x1432A4848, 24),
        (WRAPPER, 21, 0x1432A4850, 28),
        (WRAPPER, 22, 0x1432A4860, 32),
        (WRAPPER, 23, 0x1432A4870, 36),
        (WRAPPER, 30, 0x1432A488C, 8),
    ]
    assert [(t, a) for t, a, _ in h.events if t in (GET_WORLD, RESOLVE)] == [
        (GET_WORLD, (h.game,)),
        (RESOLVE, (h.world, h.address + 48, 0xFFFFFFF9)),
    ]
    assert len(h.reads) == 3 and [a[3] for _, _, a in h.reads] == [4, 4, 2]
    check_output(h)


@pytest.mark.parametrize(
    "version,modern",
    [
        (0x433332, False),
        (0x433333, True),
        (0x7FFFFFFF, True),
        (0x80000000, False),
        (0xFFFFFFFF, False),
        (0, False),
    ],
)
def test_current_signed_version_threshold_after_resolution(version, modern):
    h = setup(stinger_wire(modern=modern), version=version)
    invoke(h)
    assert h.source.position == (42 if modern else 38)
    assert h.memory.read(h.address + 8, 4) == (WORDS[9] if modern else U32)
    targets = [t for t, _, _ in h.events]
    assert targets.index(RESOLVE) > targets.index(FLOAT_WRAPPER)
    assert targets.count(WRAPPER) == (7 if modern else 6)


@pytest.mark.parametrize("old,new", [(0, 0x433333), (0x44E666, 0x433332)])
def test_resolution_may_change_current_version_before_time_gate(old, new):
    def after(h, target, _args, _answer):
        if target == RESOLVE:
            h.memory.write(VERSION, 4, new)

    modern = new >= 0x433333
    h = setup(stinger_wire(modern=modern), version=old, after=after)
    invoke(h)
    assert h.source.position == (42 if modern else 38)
    assert h.memory.read(h.address + 8, 4) == (WORDS[9] if modern else U32)


@pytest.mark.parametrize("sprite", [-32768, -1, 0, 32767])
def test_sprite_signed16_to_raw_ecx_width_and_lookup_destination(sprite):
    h = setup(stinger_wire(sprite))
    invoke(h)
    assert next(a for t, a, _ in h.events if t == RESOLVE) == (
        h.world,
        h.address + 48,
        sprite & U32,
    )


def test_current_game_and_sprite_reads_occur_after_prior_callbacks():
    replacement_game = 0xCAFE

    def after(h, target, args, _answer):
        if target == CLEANUP and h.source.position == 38:
            h.memory.write(GAME, 8, replacement_game)
        if target == GET_WORLD:
            assert args == (replacement_game,)
            # Getter is before the saved sprite load, so this is current.
            frame = h.frames[0][0]
            h.memory.write(frame + 0x57, 2, 0x8001)

    h = setup(stinger_wire(), after=after)
    invoke(h)
    assert next(a for t, a, _ in h.events if t == RESOLVE)[2] == 0xFFFF8001


def test_raw_reads_reload_current_stream_vtable_slot_and_ignore_raw_return_value():
    def after(h, target, _args, _answer):
        if target == IO:
            h.memory.write(h.table + 24, 8, SECOND_IO)
            return 0xFFFFFFFFFFFFFFFF

    h = setup(bytes(6), after=after)
    invoke(h, TIMER)
    assert [t for _, t, _ in h.reads] == [IO, SECOND_IO]
    check_output(h)


def test_one_live_frame_retains_seeds_gaps_reused_results_and_wrapper_stack_arguments():
    observed = []

    def before(h, target, args, _data):
        frame = h.frames[0][0]
        if target in (WRAPPER, FLOAT_WRAPPER):
            assert h.memory.read(frame + 0xF, 8) == args[5]  # stack6: bp-61
            assert h.memory.read(frame + 7, 8) == h.stream  # stack5: bp-69
            observed.append(h.memory.read_bytes(frame, 7))
        if target == IO:
            assert h.memory.read_bytes(args[1], 48) == bytes(48)
            assert h.memory.read_bytes(frame + 0x27, 48) == bytes(48)

    h = setup(stinger_wire(), before=before)
    invoke(h)
    assert observed == [SCRATCH.stinger[:7]] * 8
    final = h.completed_frames[0]
    assert final[0x17:0x1F] == SCRATCH.stinger[0x17:0x1F]
    assert final[0x1F:0x27] == h.output.to_bytes(8, "little")
    assert final[0x59:0x5F] == SCRATCH.stinger[0x59:0x5F]


@pytest.mark.parametrize("entry,first_width", [(STINGER, 4), (TIMER, 2)])
def test_raw_error_marks_processed_and_clears_aggregate_before_decoration_frontier(
    entry, first_width
):
    def after(h, target, args, _answer):
        if target == IO:
            h.memory.write(args[1] + 24, 8, 77)

    h = setup(bytes(first_width), after=after)
    output_before = h.memory.read_bytes(h.output, 48)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="raw-error/decoration"):
        invoke(h, entry)
    assert h.source.position == first_width and [t for t, _, _ in h.events] == [IO]
    frame = h.completed_frames[0]
    raw = 0x5F if entry == STINGER else 0x47
    aggregate = 0x27 if entry == STINGER else 0x17
    assert frame[raw + 40] == 1
    assert frame[aggregate : aggregate + 48] == bytes(48)
    assert h.memory.read_bytes(h.output, 48) == output_before


def test_forwarded_status_is_read_after_raw_cleanup_and_before_aggregate_processed():
    aggregate = None

    def after(h, target, args, _answer):
        nonlocal aggregate
        if target == FORWARD:
            aggregate = args[0]
        elif target == CLEANUP and aggregate is not None:
            h.memory.write(aggregate + 24, 8, 99)

    h = setup(bytes(2), after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="forwarded-error/logging"):
        invoke(h, TIMER)
    assert [t for t, _, _ in h.events] == [IO, FORWARD, CLEANUP]
    assert h.completed_frames[0][0x3F] == 0
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


def test_wrapper_error_preserves_child_bytes_and_leaves_aggregate_unprocessed():
    def after(h, target, args, _answer):
        if target == WRAPPER:
            h.memory.write(args[0] + 24, 8, 1)

    h = setup(stinger_wire(), after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="forwarded-error/logging"):
        invoke(h)
    assert h.source.position == 12
    assert h.memory.read(h.address + 12, 4) == WORDS[2]
    assert h.completed_frames[0][0x4F] == 0
    assert h.events[-1][0] == WRAPPER


@pytest.mark.parametrize(
    "missing,position",
    [
        (FORWARD, 4),
        (CLEANUP, 4),
        (WRAPPER, 8),
        (FLOAT_WRAPPER, 20),
        (GET_WORLD, 38),
        (RESOLVE, 38),
    ],
)
def test_missing_mandatory_child_never_becomes_success_and_retains_prior_effects(missing, position):
    h = setup(stinger_wire(), absent=(missing,))
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"missing{missing:x}"):
        invoke(h)
    assert h.source.position == position
    assert h.memory.read(h.address, 4) == WORDS[0]
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48
    assert len(h.completed_frames) == 1


def test_late_time_wrapper_failure_does_not_apply_old_version_default():
    def before(h, target, args, _data):
        if target == WRAPPER and args[2] == 30:
            raise UnresolvedReplayTaskRebuild("time wrapper absent")

    h = setup(stinger_wire(), before=before)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="time wrapper absent"):
        invoke(h)
    assert h.source.position == 38
    assert h.memory.read(h.address + 8, 4) == 0x44444444
    assert h.memory.read(h.address + 48, 8) == 0x1234567890


def test_nonempty_forwarded_vector_requires_actual_reserve_before_any_cleanup():
    def after(h, target, args, _answer):
        if target == IO:
            pointer = h.memory.allocate(32)
            h.memory.write_bytes(pointer, b"S" * 32)
            for offset, word in ((0, pointer), (8, pointer + 32), (16, pointer + 32)):
                h.memory.write(args[1] + offset, 8, word)

    h = setup(bytes(2), after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402ba380"):
        invoke(h, TIMER)
    assert [t for t, _, _ in h.events] == [IO, FORWARD]
    assert h.source.position == 2 and h.completed_frames[0][0x6F] == 1
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


def make_control(h, strong=1, weak=1):
    control, table = h.memory.allocate(16), h.memory.allocate(16)
    for offset, width, value in ((0, 8, table), (8, 4, strong), (12, 4, weak)):
        h.memory.write(control + offset, width, value)
    h.memory.write(table, 8, 0xD100)
    h.memory.write(table + 8, 8, 0xD200)
    return control, table


def test_real_forward_acquire_and_two_inline_releases_balance_each_read_control():
    controls = []
    callbacks = []

    def after(h, target, args, _answer):
        if target == IO:
            current, _ = make_control(h)
            controls.append(current)
            h.memory.write(args[1] + 32, 8, current)

    h = setup(bytes(6), after=after)
    # Actual callbacks are explicit lower effects; no unknown success fallback.
    original = h.calls.call

    def call(target, args, data):
        if target in (0xD100, 0xD200):
            callbacks.append((target, args))
            return None
        assert original is not None
        return original(target, args, data)

    calls = ReplayTaskRebuildCalls(call)
    read_replay_saved_unpack_timer(
        h.context,
        h.address,
        h.output,
        h.stream,
        calls=calls,
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SCRATCH,
    )
    assert callbacks == [
        (0xD100, (c,)) if i % 2 == 0 else (0xD200, (c,)) for c in controls for i in range(2)
    ]
    assert all(h.memory.read(c + 8, 4) == h.memory.read(c + 12, 4) == 0 for c in controls)


def test_control_release_holds_control_and_reloads_its_current_dispose_vtable():
    h = setup(bytes(2))
    first, first_table = make_control(h)
    replacement, _ = make_control(h, 7, 7)
    changed_table = h.memory.allocate(16)
    h.memory.write(changed_table + 8, 8, 0xD300)
    seen = []
    original = h.calls.call

    def call(target, args, data):
        if target == IO:
            assert original is not None
            answer = original(target, args, data)
            h.memory.write(args[1] + 32, 8, first)
            return answer
        if target == FORWARD:
            assert original is not None
            answer = original(target, args, data)
            # This removes the extra forwarded hold from the control under
            # test while preserving current aggregate identity separately.
            h.memory.write(args[0] + 32, 8, 0)
            h.memory.write(first + 8, 4, 1)
            return answer
        if target == 0xD100:
            seen.append(target)
            raw = h.frames[0][0] + 0x47
            h.memory.write(raw + 32, 8, replacement)
            h.memory.write(first, 8, changed_table)
            return None
        if target == 0xD300:
            seen.append(target)
            assert args == (first,)
            raise UnresolvedReplayTaskRebuild("after real held dispose")
        assert original is not None
        return original(target, args, data)

    with pytest.raises(UnresolvedReplayTaskRebuild, match="held dispose"):
        read_replay_saved_unpack_timer(
            h.context,
            h.address,
            h.output,
            h.stream,
            calls=ReplayTaskRebuildCalls(call),
            atomics=h.atomics,
            bind_local=h.bind_local,
            scratch=SCRATCH,
        )
    assert seen == [0xD100, 0xD300]
    assert h.memory.read(first + 8, 4) == h.memory.read(first + 12, 4) == 0
    assert h.memory.read(replacement + 8, 4) == h.memory.read(replacement + 12, 4) == 7
    assert h.memory.read(first_table + 8, 8) == 0xD200


def test_missing_actual_atomic_effect_stops_after_forward_with_retained_control():
    h = setup(bytes(2))
    current, _ = make_control(h)
    original = h.calls.call

    def call(target, args, data):
        assert original is not None
        answer = original(target, args, data)
        if target == FORWARD:
            h.memory.write(args[1] + 32, 8, current)
        return answer

    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect unavailable"):
        read_replay_saved_unpack_timer(
            h.context,
            h.address,
            h.output,
            h.stream,
            calls=ReplayTaskRebuildCalls(call),
            atomics=ReplayUnitAIMapAtomics(None, None),
            bind_local=h.bind_local,
            scratch=SCRATCH,
        )
    assert h.memory.read(current + 8, 4) == 1
    assert h.source.position == 2 and h.events[-1][0] == FORWARD


@pytest.mark.parametrize("entry", [STINGER, TIMER, RESOLVE])
@pytest.mark.parametrize(
    "args,data", [((1, 2), None), ((1, 2, 3, 4), None), ((1, 2, 3), memoryview(b"x"))]
)
def test_binder_strict_arity_and_no_payload(entry, args, data):
    h = setup(bytes(6))
    before = h.memory.snapshot()
    with pytest.raises(ValueError, match="malformed"):
        assert h.bound.call is not None
        h.bound.call(entry, args, data)
    assert h.memory.snapshot() == before and h.frames == []


def test_binder_delegates_unknown_target_with_exact_payload_and_refuses_missing():
    h = setup(bytes(6))
    seen = []
    payload = memoryview(b"payload")
    lower = ReplayTaskRebuildCalls(
        lambda target, args, data: seen.append((target, args, data)) or 55
    )
    bound = bind_replay_unit_saved_components(
        h.context, lower, atomics=h.atomics, bind_local=h.bind_local, scratch=SCRATCH
    )
    assert bound.call is not None and bound.call(0xEE, (1, 2), payload) == 55
    assert seen == [(0xEE, (1, 2), payload)]
    missing = bind_replay_unit_saved_components(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SCRATCH,
    )
    with pytest.raises(UnresolvedReplayTaskRebuild, match="reachedee"):
        assert missing.call is not None
        missing.call(0xEE, (), None)


@pytest.mark.parametrize(
    "stinger,timer", [(b"", bytes(128)), (bytes(144), b""), (bytearray(144), bytes(128))]
)
def test_seed_frame_shapes_are_explicit_exact_bytes(stinger, timer):
    with pytest.raises(ValueError, match="local seeds"):
        ReplayUnitSavedScratch(stinger, timer)


@pytest.mark.parametrize("bad", ["atomics", "local", "scratch", "argument"])
def test_invalid_call_profile_is_rejected_before_any_local_or_object_mutation(bad):
    h = setup(bytes(6))
    before = h.memory.snapshot()
    with pytest.raises(ValueError):
        read_replay_saved_unpack_timer(
            h.context,
            (1 << 64) if bad == "argument" else h.address,
            h.output,
            h.stream,
            calls=h.calls,
            atomics=None if bad == "atomics" else h.atomics,
            bind_local=None if bad == "local" else h.bind_local,
            scratch=None if bad == "scratch" else SCRATCH,
        )
    assert h.memory.snapshot() == before and h.frames == []


def graphic_setup(*, old=0, bound=3, entries=(0x100, 0x200, 0x300)):
    m = ReplayMemory()
    world, output, table = (m.allocate(n) for n in (0xD4, 8, len(entries) * 8))
    m.write(output, 8, old)
    m.write(world + 0xD0, 4, bound & U32)
    m.write(world + 0xC0, 8, table)
    for i, word in enumerate(entries):
        m.write(table + i * 8, 8, word)
    events = []

    def read(pointer, width):
        events.append(("read", pointer, width))
        return m.read(pointer, width)

    def write(pointer, width, value):
        events.append(("write", pointer, width, value))
        m.write(pointer, width, value)

    context = ReplayTaskRebuildStorage(world, read, write)
    return SimpleNamespace(
        memory=m, world=world, output=output, table=table, context=context, events=events
    )


@pytest.mark.parametrize(
    "identifier,bound,entries,expected,read_offsets",
    [
        (0xFFFFFFFF, 3, (0x100, 0x200, 0x300), 0, ()),
        (0x80000000, 3, (0x100, 0x200, 0x300), 0, ()),
        (0x12345678FFFFFFFF, 3, (0x100, 0x200, 0x300), 0, ()),
        (3, 3, (0x100, 0x200, 0x300), 0, (0xD0,)),
        (0, 0, (0x100,), 0, (0xD0,)),
        (0, 0xFFFFFFFF, (0x100,), 0, (0xD0,)),
        (0x7FFFFFFF, 0x7FFFFFFF, (0x100,), 0, (0xD0,)),
        (0, 3, (0x100, 0x200, 0x300), 0x100, (0xD0, 0xC0)),
        (2, 3, (0x100, 0x200, 0x300), 0x300, (0xD0, 0xC0)),
        (0xABCD00000001, 3, (0x100, 0, 0x300), 0, (0xD0, 0xC0)),
    ],
)
def test_graphic_fixup_signed_raw32_bounds_and_null_entry_without_extra_reads(
    identifier, bound, entries, expected, read_offsets
):
    h = graphic_setup(bound=bound, entries=entries)
    fixup_replay_saved_graphic(
        h.context, h.world, h.output, identifier, calls=ReplayTaskRebuildCalls(None)
    )
    expected_reads = [("read", h.output, 8)]
    expected_reads += [
        ("read", h.world + offset, 4 if offset == 0xD0 else 8) for offset in read_offsets
    ]
    if 0xC0 in read_offsets:
        expected_reads += [("read", h.table + (identifier & U32) * 8, 8)]
    if expected:
        expected_reads += [("write", h.output, 8, expected)]
    assert h.events == expected_reads and h.memory.read(h.output, 8) == expected


@pytest.mark.parametrize("identifier,entries", [(U32, (5,)), (1, (5,)), (0, (0,))])
def test_invalid_or_null_lookup_does_not_clear_old_output_after_real_child_returns(
    identifier, entries
):
    h = graphic_setup(old=0xCAFE, bound=1, entries=entries)
    seen = []

    def release(target, args, data):
        assert target == 0x1409CCE80 and args == (0xCAFE, 0) and data is None
        seen.append((target, args))
        h.memory.write(h.output, 8, 0xBEEF)

    fixup_replay_saved_graphic(
        h.context, h.world, h.output, identifier, calls=ReplayTaskRebuildCalls(release)
    )
    assert seen == [(0x1409CCE80, (0xCAFE, 0))]
    assert h.memory.read(h.output, 8) == 0xBEEF
    assert not any(e[0] == "write" for e in h.events)


def test_graphic_old_child_precedes_current_bound_and_table_reads_and_preserves_held_id():
    h = graphic_setup(old=0xCAFE, bound=0, entries=(0x100,))
    new_table = h.memory.allocate(16)
    h.memory.write(new_table + 8, 8, 0xAABB)

    def release(target, args, data):
        assert (target, args, data) == (0x1409CCE80, (0xCAFE, 0), None)
        assert h.events == [("read", h.output, 8)]
        h.memory.write(h.world + 0xD0, 4, 2)
        h.memory.write(h.world + 0xC0, 8, new_table)
        h.memory.write(h.output, 8, 0xDEAD)

    fixup_replay_saved_graphic(
        h.context, h.world, h.output, 0x123400000001, calls=ReplayTaskRebuildCalls(release)
    )
    assert h.events == [
        ("read", h.output, 8),
        ("read", h.world + 0xD0, 4),
        ("read", h.world + 0xC0, 8),
        ("read", new_table + 8, 8),
        ("write", h.output, 8, 0xAABB),
    ]


def test_graphic_table_pointer_is_loaded_after_current_bound_read_effect():
    h = graphic_setup(bound=1, entries=(0x100,))
    new_table = h.memory.allocate(8)
    h.memory.write(new_table, 8, 0xD00D)

    def read(pointer, width):
        value = h.memory.read(pointer, width)
        if pointer == h.world + 0xD0:
            h.memory.write(h.world + 0xC0, 8, new_table)
        return value

    context = ReplayTaskRebuildStorage(h.world, read, h.memory.write)
    fixup_replay_saved_graphic(context, h.world, h.output, 0, calls=ReplayTaskRebuildCalls(None))
    assert h.memory.read(h.output, 8) == 0xD00D


def test_missing_old_graphic_child_is_mandatory_even_for_negative_id():
    h = graphic_setup(old=0xCAFE)
    before = h.memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1409cce80"):
        fixup_replay_saved_graphic(
            h.context, h.world, h.output, U32, calls=ReplayTaskRebuildCalls(None)
        )
    assert h.events == [("read", h.output, 8)] and h.memory.snapshot() == before


def test_old_graphic_child_failure_keeps_mutation_without_later_world_reads():
    h = graphic_setup(old=0xCAFE)

    def release(_target, _args, _data):
        h.memory.write(h.output, 8, 0)
        raise UnresolvedReplayTaskRebuild("release failed")

    with pytest.raises(UnresolvedReplayTaskRebuild, match="release failed"):
        fixup_replay_saved_graphic(
            h.context, h.world, h.output, 0, calls=ReplayTaskRebuildCalls(release)
        )
    assert h.events == [("read", h.output, 8)] and h.memory.read(h.output, 8) == 0


def test_negative_graphic_id_skips_even_an_unreadable_world_but_reads_output_first():
    h = graphic_setup()
    fixup_replay_saved_graphic(h.context, 0, h.output, U32, calls=ReplayTaskRebuildCalls(None))
    assert h.events == [("read", h.output, 8)]
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        fixup_replay_saved_graphic(h.context, 0, 0, U32, calls=ReplayTaskRebuildCalls(None))


@pytest.mark.parametrize("bad", [-1, 1 << 64, False])
def test_graphic_invalid_raw_argument_is_rejected_before_any_storage_effect(bad):
    h = graphic_setup()
    with pytest.raises(ValueError):
        fixup_replay_saved_graphic(
            h.context, h.world, h.output, bad, calls=ReplayTaskRebuildCalls(None)
        )
    assert h.events == []


def real_composition(raw, *, sprite_table=(0xAABB,), old_graphic=0):
    """All three new bodies + root wrappers/getter + real owned input/Results."""
    h = setup(raw)
    h.game = h.memory.allocate(0x5C8)
    h.world = h.memory.allocate(0xD4)
    table = h.memory.allocate(len(sprite_table) * 8)
    h.memory.write(GAME, 8, h.game)
    h.memory.write(h.game + 0x5C0, 8, h.world)
    h.memory.write(h.world + 0xD0, 4, len(sprite_table))
    h.memory.write(h.world + 0xC0, 8, table)
    for i, graphic in enumerate(sprite_table):
        h.memory.write(table + i * 8, 8, graphic)
    h.memory.write(h.address + 48, 8, old_graphic)
    runtime = h.memory.runtime_calls()
    reads = []

    def watch(target, args, data):
        if target == IO:
            reads.append(args)
        assert h.io.call is not None
        return h.io.call(target, args, data)

    strings = bind_replay_saved_string(h.context, ReplayTaskRebuildCalls(watch), imports=runtime)
    results = bind_replay_saved_result(h.context, strings, atomics=h.atomics, imports=runtime)
    apply = bind_replay_saved_apply(h.context, results, atomics=h.atomics, imports=runtime)
    variants = bind_replay_unit_ai_variants(
        h.context,
        apply,
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=ReplayUnitAIVariantScratch(bytes(0x140), bytes(0xC0), bytes(0xD0)),
    )
    wrappers = bind_replay_saved_position(
        h.context, variants, atomics=h.atomics, bind_local=h.bind_local
    )
    h.bound = bind_replay_unit_saved_components(
        h.context, wrappers, atomics=h.atomics, bind_local=h.bind_local, scratch=SCRATCH
    )
    h.real_reads = reads
    return h


@pytest.mark.parametrize("sprite,expected", [(-32768, 0), (-1, 0), (0, 0xAABB), (1, 0)])
def test_stinger_composes_real_scalar_aliases_getter_graphic_input_and_result_bodies(
    sprite, expected
):
    h = real_composition(stinger_wire(sprite))
    assert invoke(h, direct=False) == h.output
    assert h.source.position == 42 and len(h.real_reads) == 11
    assert [args[3] for args in h.real_reads] == [4] * 9 + [2, 4]
    assert h.memory.read(h.address + 48, 8) == expected
    for offset, word in zip(FIELDS, WORDS[:9], strict=True):
        assert h.memory.read(h.address + offset, 4) == word
    assert h.memory.read(h.address + 8, 4) == WORDS[9]
    assert len(h.completed_frames) == 9  # whole reader + eight actual wrapper locals
    check_output(h)


def test_full_real_stinger_negative_id_with_old_pointer_stops_at_actual_release_child():
    h = real_composition(stinger_wire(-1), old_graphic=0xCAFE)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1409cce80"):
        invoke(h, direct=False)
    assert h.source.position == 38 and h.memory.read(h.address + 48, 8) == 0xCAFE
    assert h.memory.read(h.address + 8, 4) == 0x44444444
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


def test_graphic_binder_invokes_actual_body_without_local_frames_or_atomic_effects():
    h = setup(bytes(6))
    h.memory.write(h.address + 48, 8, 0)
    assert h.bound.call is not None
    assert h.bound.call(RESOLVE, (0, h.address + 48, U32), None) is None
    assert h.frames == [] and h.events == [] and h.source.position == 0
