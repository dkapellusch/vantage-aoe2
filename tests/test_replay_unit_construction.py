"""Source-led caller phases using owned bytes and named lower-child fixtures.

The fixture parent/map/reader/Result implementations below are explicitly
controlled child effects for isolated caller tests, not a successful native
constructor, saved restore or World. A separate recursive test keeps unknown
children unavailable and checks the real first refusal through all six bodies.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_memory import ReplayMemory
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_construction import (
    ReplayUnitConstructionFloatingCalls,
    ReplayUnitConstructionScratch,
    bind_replay_unit_construction,
    construct_replay_unit_object,
)

BASE, ANIMATED, MOVING = 0x14122E1B0, 0x141141760, 0x141206510
ACTION, COMBAT, UNIT = 0x141136EC0, 0x141143C30, 0x1412A5D60
ENTRIES = (BASE, ANIMATED, MOVING, ACTION, COMBAT, UNIT)
PARENTS = dict(zip(ENTRIES[1:], ENTRIES[:-1], strict=True))
FLAGS = {BASE: 0xC0, ANIMATED: 0xB0, MOVING: 0xB0, ACTION: 0xB0, COMBAT: 0xD0, UNIT: 0xD0}
READERS = dict(
    zip(
        ENTRIES,
        (0x14125D730, 0x141142A70, 0x14121F910, 0x14113E920, 0x1411587A0, 0x1412D4F50),
        strict=True,
    )
)
TABLES = dict(
    zip(
        ENTRIES,
        (0x1432B4078, 0x1432A6748, 0x1432B2838, 0x1432A5708, 0x1432A70D0, 0x1432B8270),
        strict=True,
    )
)
FORWARD, PAIR, COPY = 0x1409076B0, 0x14090D270, 0x1402B9080
CLEANUP, DIRECT_CLEANUP = 0x1402BD890, 0x1402BD7F0
SELECTED, OTHER_SELECTED = 0x141219F20, 0xA490
FREE, ALLOCATE = 0x142D6BAB4, 0x142D6BA78
U64, U32 = (1 << 64) - 1, (1 << 32) - 1
MASTER_ADD = 0x6A586EB28AC201FC + 0xCF19788B2554E70
SCRATCH = ReplayUnitConstructionScratch(
    *(bytes((i * 7 + j) & 255 for j in range(FLAGS[entry] + 4)) for i, entry in enumerate(ENTRIES))
)


def setup(entry, *, status=0, before=None, after=None, on_read=None, floating=None):
    h = SimpleNamespace()
    h.memory = m = ReplayMemory()
    h.obj, h.out, h.stream = (m.allocate(n) for n in (0x828, 48, 8))
    m.write_bytes(h.obj, b"\xa5" * 0x828)
    m.write(h.obj + 0x200, 8, 0)  # Explicit isolated Unit post-success premise.
    m.write_bytes(h.out, bytes(48))
    m.write(h.out + 24, 8, status)
    m.write(h.out + 40, 1, 0x99)
    m.write_bytes(h.out + 41, b"padding")
    m.map_bytes(TABLES[MOVING] + 0x490, SELECTED.to_bytes(8, "little"))
    m.map_bytes(0x14435505B, b"\0")
    h.entry, h.opaque = entry, 0xABCDEF1234567890
    h.calls_seen, h.accesses, h.frames, h.finished, h.float_seen = [], [], [], [], []
    h.allocations = []

    def read(address, width):
        value = m.read(address, width)
        h.accesses.append(("read", address, width, value))
        if on_read:
            replacement = on_read(h, address, width, value)
            if replacement is not None:
                return replacement
        return value

    def write(address, width, value):
        h.accesses.append(("write", address, width, value))
        m.write(address, width, value)

    h.context = ReplayTaskRebuildStorage(h.obj, read, write)
    h.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)

    @contextmanager
    def local(view):
        with m.bind_local(view) as address:
            h.frames.append((address, view))
            try:
                yield address
            finally:
                h.finished.append((address, view.tobytes()))
                h.frames.pop()

    h.bind_local = local

    def call(target, args, data):
        h.calls_seen.append((target, args, data))
        assert data is None
        if before:
            before(h, target, args)
        if target == PARENTS.get(entry):
            # A declared isolated predecessor effect; it is not the real
            # parent body or a composition-success claim.
            assert args == (h.obj, h.out, h.stream, h.opaque, 0)
            answer = 0xDEADBEEF  # Caller must ignore parent RAX.
        elif target == ALLOCATE:
            assert args == (40,)
            answer = m.allocate(40)
            m.write_bytes(answer, b"\xd3" * 40)
            h.allocations.append(answer)
        elif target == FORWARD:
            destination, source = args
            # Controlled Result provider: populate all defined Result fields,
            # keep local padding seeded, and return the destination identity.
            for offset in (0, 8, 16, 24, 32):
                m.write(destination + offset, 8, m.read(source + offset, 8))
            m.write(destination + 40, 1, 0)
            answer = destination
        elif target == PAIR:
            destination, source = args
            m.write_bytes(destination, m.read_bytes(source, 16))
            answer = destination
        elif target in (COPY, CLEANUP, DIRECT_CLEANUP):
            # Named caller-boundary fixtures; real copy/release implementations
            # are mandatory in production and are tested separately.
            answer = None
        elif target in READERS.values():
            obj, result, stream, opaque = args
            assert (obj, stream, opaque) == (h.obj, h.stream, h.opaque)
            m.write_bytes(result, bytes(41))
            answer = result
        elif target in (SELECTED, OTHER_SELECTED):
            assert args == (h.obj,)
            answer = None
        elif target in (
            0x14122DC70,
            0x1410B2A40,
            0x140A1A660,
            0x14122DBF0,
            0x141136CA0,
            0x1411438B0,
            0x141143930,
            0x1412A5CE0,
            0x1412A5C60,
            0x14106A330,
            0x140B2CFC0,
            FREE,
            0x14101ADB0,
        ):
            answer = None  # Declared isolated subobject/destructor/log fixture.
        else:
            raise UnresolvedReplayTaskRebuild(f"fixture has no actual child{target:x}")
        if after:
            replacement = after(h, target, args, answer)
            if replacement is not None:
                answer = replacement
        return answer

    h.calls = ReplayTaskRebuildCalls(call)

    def fp_call(target, args, xmm1):
        h.float_seen.append((target, args, xmm1))
        if floating:
            return floating(h, target, args, xmm1)
        raise UnresolvedReplayTaskRebuild("fixture floating child unavailable")

    h.floating = ReplayUnitConstructionFloatingCalls(fp_call)
    h.bound = bind_replay_unit_construction(
        h.context,
        h.calls,
        atomics=h.atomics,
        bind_local=local,
        scratch=SCRATCH,
        floating=h.floating,
    )
    return h


def invoke(h, flag=0, *, direct=True):
    args = (h.obj, h.out, h.stream, h.opaque, flag)
    if direct:
        return construct_replay_unit_object(
            h.context,
            *args,
            entry=h.entry,
            calls=h.calls,
            atomics=h.atomics,
            bind_local=h.bind_local,
            scratch=SCRATCH,
            floating=h.floating,
        )
    assert h.bound.call is not None
    return h.bound.call(h.entry, args, None)


def targets(h):
    return [target for target, _args, _data in h.calls_seen]


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("direct", [False, True])
def test_six_whole_caller_phases_over_owned_poisoned_storage(entry, direct):
    h = setup(entry)
    before = h.memory.read_bytes(h.out, 48)
    assert invoke(h, direct=direct) == h.obj
    assert h.memory.read(h.obj, 8) == TABLES[entry]
    assert not h.frames and len(h.finished) == (1 if direct else ENTRIES.index(entry) + 1)
    assert not set(READERS.values()).intersection(targets(h))
    assert h.memory.read_bytes(h.out + 41, 7) == b"padding"
    if entry == BASE:
        assert h.memory.read_bytes(h.out, 48) == before
        assert h.memory.read(h.obj + 0x10, 8) == MASTER_ADD & U64
        assert h.memory.read_bytes(h.obj + 0x140, 2) == b"\xa5\0"
        assert h.memory.read_bytes(h.obj + 0x208, 8) == b"\xa5" * 8
        assert h.memory.read(h.obj + 0x1C4, 4) == 0x1000001
        assert h.memory.read(h.obj + 0x1C8, 4) == 0x1010100
        assert targets(h) == [
            0x14122DC70,
            0x1410B2A40,
            0x140A1A660,
            0x140A1A660,
            ALLOCATE,
            0x14122DBF0,
        ]
    elif entry == ANIMATED:
        if direct:
            assert targets(h) == [BASE, FORWARD, PAIR, COPY, DIRECT_CLEANUP]
        else:
            assert targets(h)[-4:] == [FORWARD, PAIR, COPY, DIRECT_CLEANUP]
    elif entry == MOVING:
        assert h.memory.read(h.obj + 0x3C8, 8) == 0x3F800000
        assert h.memory.read(h.obj + 0x3DC, 4) == 0xBF800000
        assert h.memory.read_bytes(h.obj + 0x3B8, 4) == b"\0\0\xa5\xa5"
    elif entry == ACTION:
        assert h.memory.read(h.obj + 0x430, 4) == U32
        assert h.memory.read(h.obj + 0x438, 8) == 0
        assert h.memory.read(h.out + 40, 1) == 1
    elif entry == COMBAT:
        assert h.memory.read_bytes(h.obj + 0x58C, 4) == b"\0\xa5\xa5\xa5"
        assert h.memory.read(h.obj + 0x59C, 4) == U32
        assert h.memory.read(h.out + 40, 1) == 1
    else:
        assert h.memory.read(h.obj + 0x648, 8) == 0xFFFFFFFFBF800000
        assert h.memory.read(h.obj + 0x650, 8) == U64
        assert h.memory.read_bytes(h.obj + 0x808, 16) == b"\0\0\xa5\xa5" + bytes(8) + b"\xa5" * 4
        assert h.memory.read(h.obj + 0x6DC, 4) == 0
    for pointer in h.allocations:
        assert tuple(h.memory.read(pointer + i, 8) for i in (0, 8, 16)) == (pointer,) * 3
        assert h.memory.read_bytes(pointer + 24, 16) == b"\1\1" + b"\xd3" * 14


@pytest.mark.parametrize("entry", ENTRIES)
def test_failed_incoming_status_does_not_skip_initialization_or_unconditional_forward(entry):
    h = setup(entry, status=0xBAD)
    assert invoke(h) == h.obj
    assert h.memory.read(h.obj, 8) == TABLES[entry]
    if entry in (ANIMATED, MOVING, UNIT):
        assert FORWARD in targets(h) and COPY in targets(h)
    assert SELECTED not in targets(h)
    assert not set(READERS.values()).intersection(targets(h))
    if entry == ACTION:
        assert h.memory.read_bytes(h.obj + 0x438, 12) == b"\xa5" * 12
    if entry != BASE:
        assert any(a[:3] == ("read", h.out + 24, 8) for a in h.accesses)


@pytest.mark.parametrize("entry", ENTRIES)
def test_fifth_is_low_dword_and_reader_is_called_with_opaque_r9(entry):
    h = setup(entry)
    invoke(h, 1 << 32)
    assert READERS[entry] not in targets(h)
    h = setup(entry)
    invoke(h, 0xAB0000000100)
    assert READERS[entry] in targets(h)
    args = next(args for target, args, _data in h.calls_seen if target == READERS[entry])
    assert args == (
        h.obj,
        h.finished[0][0] + (0x40 if entry in (COMBAT, UNIT) else 0x30),
        h.stream,
        h.opaque,
    )


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("initial,changed", [(0, 0x100), (1, 0)])
def test_fifth_flag_is_reloaded_from_coherent_local_after_children(entry, initial, changed):
    gate_predecessor = {
        BASE: 0x14122DBF0,
        ANIMATED: DIRECT_CLEANUP,
        MOVING: SELECTED,
        ACTION: 0x141136CA0,
        COMBAT: 0x141143930,
        UNIT: CLEANUP,
    }[entry]

    def before(h, target, _args):
        if target == gate_predecessor:
            frame = h.frames[-1][0]
            h.memory.write(frame + FLAGS[entry], 4, changed)

    h = setup(entry, before=before)
    invoke(h, initial)
    assert (READERS[entry] in targets(h)) == bool(changed)


def test_base_has_no_incoming_result_status_guard_before_its_own_reader():
    h = setup(BASE, status=99)
    invoke(h, 1)
    assert READERS[BASE] in targets(h)


def test_base_reused_qword_temp_preserves_current_upper_word_after_dword_zero():
    def before(h, target, _args):
        if target == 0x1410B2A40:
            frame = h.frames[-1][0]
            h.memory.write(frame + 0x20, 8, 0xDEADBEEF11223344)

    h = setup(BASE, before=before)
    invoke(h)
    first = ((0xDEADBEEF00000000 + 0x147B5E081EC087D9) & U64) ^ 0xF2A55F7A61DD00E
    second = ((first & 0xFFFFFFFF00000000) - 0x4C3FBA69E4EA7FD1 + 0x183CAC30D2441D0E) & U64
    third = ((second & 0xFFFFFFFF00000000) - 0x6C5EAB60B426DD28 + 0x61501AA6ECFD980A) & U64
    fourth = ((third & 0xFFFFFFFF00000000) - 0x21D14A25ED7C802C - 0x2B3719EF44DE99FF) & U64
    assert [h.memory.read(h.obj + offset, 8) for offset in (0x130, 0x170, 0x178, 0x180)] == [
        first,
        second,
        third,
        fourth,
    ]
    frame = h.finished[0][0]
    assert sum(a[:3] == ("write", frame + 0x20, 4) for a in h.accesses) == 4


@pytest.mark.parametrize("failure", [FORWARD, PAIR, COPY, DIRECT_CLEANUP])
def test_result_child_failures_do_not_invent_remaining_cleanup(failure):
    def before(_h, target, _args):
        if target == failure:
            raise UnresolvedReplayTaskRebuild("declared Result child failure")

    h = setup(ANIMATED, before=before)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Result child failure"):
        invoke(h)
    assert h.memory.read(h.obj, 8) == TABLES[ANIMATED]
    assert targets(h)[-1] == failure and not h.frames
    expected_processed = {FORWARD: 0x99, PAIR: 0x99, COPY: 0x99, DIRECT_CLEANUP: 0}
    assert h.memory.read(h.out + 40, 1) == expected_processed[failure]


def test_action_map_failure_does_not_preemptively_mark_output_processed():
    def before(_h, target, _args):
        if target == 0x141136CA0:
            raise UnresolvedReplayTaskRebuild("actual map unavailable")

    h = setup(ACTION, before=before)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual map"):
        invoke(h)
    assert h.memory.read(h.out + 40, 1) == 0x99
    assert h.memory.read(h.obj + 0x448, 8) == 0
    assert h.memory.read(h.obj + 0x438, 8) == int.from_bytes(b"\xa5" * 8, "little")


def test_pair_child_precedes_identity_and_current_vector_reads_with_signed_count():
    returned = None

    def after(h, target, args, answer):
        nonlocal returned
        if target == FORWARD:
            returned = answer
        if target == PAIR:
            assert returned is not None
            h.memory.write(returned, 8, 0x1000)
            h.memory.write(returned + 8, 8, 0xFE0)
        return None

    h = setup(ANIMATED, after=after)
    invoke(h)
    copy = next(args for target, args, _ in h.calls_seen if target == COPY)
    assert copy == (h.out, 0x1000, U64)
    assert targets(h).index(PAIR) < targets(h).index(COPY)


def test_returned_output_identity_skips_copy_but_cleanup_uses_actual_local_control():
    def after(h, target, _args, _answer):
        if target == FORWARD:
            return h.out
        return None

    h = setup(ANIMATED, after=after)
    invoke(h)
    assert COPY not in targets(h)
    assert DIRECT_CLEANUP in targets(h)
    assert h.memory.read(h.out + 40, 1) == 0


def test_result_release_reads_current_local_control_then_holds_it_across_virtuals():
    def before(h, target, args):
        if target == PAIR:
            h.memory.write(h.frames[-1][0] + 0x50, 8, h.control)
        if target == 0xA001:
            h.memory.write(h.control, 8, h.second_vtable)
            h.memory.write(h.frames[-1][0] + 0x50, 8, h.other_control)

    h = setup(ANIMATED, before=before)
    h.control, h.other_control = (h.memory.allocate(16) for _ in range(2))
    h.memory.write_bytes(h.other_control, bytes(16))
    first = h.memory.allocate(16)
    h.second_vtable = h.memory.allocate(16)
    h.memory.write(first, 8, 0xA001)
    h.memory.write(first + 8, 8, 0xBAD)
    h.memory.write(h.second_vtable + 8, 8, 0xA002)
    h.memory.write(h.control, 8, first)
    h.memory.write(h.control + 8, 4, 1)
    h.memory.write(h.control + 12, 4, 1)
    lower = h.calls

    def callbacks(target, args, data):
        if target in (0xA001, 0xA002):
            h.calls_seen.append((target, args, data))
            before(h, target, args)
            assert args == (h.control,)
            return None
        assert lower.call
        return lower.call(target, args, data)

    h.calls = ReplayTaskRebuildCalls(callbacks)
    invoke(h, direct=True)
    assert [t for t in targets(h) if t in (0xA001, 0xA002)] == [0xA001, 0xA002]
    assert h.memory.read(h.control + 8, 4) == h.memory.read(h.control + 12, 4) == 0
    assert h.memory.read(h.other_control + 8, 8) == 0


@pytest.mark.parametrize("old_strong", [0, 2, U32])
def test_nonterminal_local_strong_release_does_not_touch_weak(old_strong):
    def before(h, target, _args):
        if target == PAIR:
            h.memory.write(h.frames[-1][0] + 0x50, 8, h.control)

    h = setup(ANIMATED, before=before)
    h.control = h.memory.allocate(16)
    h.memory.write(h.control + 8, 4, old_strong)
    h.memory.write(h.control + 12, 4, 123)
    invoke(h)
    assert h.memory.read(h.control + 8, 4) == (old_strong - 1) & U32
    assert h.memory.read(h.control + 12, 4) == 123


@pytest.mark.parametrize("selected", [SELECTED, OTHER_SELECTED])
def test_moving_current_dispatch_held_frees_and_later_slot_reloads(selected):
    def before(h, target, args):
        if target == CLEANUP:
            table = h.memory.allocate(0x498)
            h.memory.write(h.obj, 8, table)
            h.memory.write(table + 0x490, 8, selected)
        if target == selected:
            for offset, pointer in zip((0x3F0, 0x3F8, 0x400, 0x3B0), h.pointers, strict=True):
                h.memory.write(h.obj + offset, 8, pointer)
            h.memory.write(h.obj + 0x408, 8, U64)
            h.memory.write(h.obj + 0x410, 4, U32)
        if target == 0x14106A330 and args[0] == h.pointers[0]:
            h.memory.write(h.obj + 0x3F0, 8, 0x9999)
            h.memory.write(h.obj + 0x3F8, 8, h.changed)

    h = setup(MOVING, before=before)
    h.pointers = [h.memory.allocate(72) for _ in range(4)]
    h.changed = h.memory.allocate(72)
    invoke(h)
    frees = [args for target, args, _ in h.calls_seen if target == FREE]
    assert frees == [(h.pointers[0], 72), (h.changed, 72), (h.pointers[2], 24), (h.pointers[3], 8)]
    assert all(
        h.memory.read(h.obj + offset, 8) == 0 for offset in (0x3F0, 0x3F8, 0x400, 0x408, 0x3B0)
    )
    assert targets(h).count(selected) == 1


def test_moving_failure_retains_prior_destroy_and_does_not_clear_after_failed_free():
    def before(h, target, _args):
        if target == SELECTED:
            h.memory.write(h.obj + 0x3F0, 8, h.pointer)
        if target == FREE:
            raise UnresolvedReplayTaskRebuild("explicit unavailable free")

    h = setup(MOVING, before=before)
    h.pointer = h.memory.allocate(72)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable free"):
        invoke(h)
    assert h.memory.read(h.obj + 0x3F0, 8) == h.pointer
    assert 0x14106A330 in targets(h)
    assert not h.frames


@pytest.mark.parametrize("enable", [0, 1, 255])
def test_moving_logger_has_current_unsigned_byte_gate_and_exact_five_args(enable):
    h = setup(MOVING)
    h.memory.write(0x14435505B, 1, enable)
    h.memory.map_bytes(0x144355068, (0x1234).to_bytes(8, "little"))
    invoke(h)
    logs = [args for target, args, _ in h.calls_seen if target == 0x14101ADB0]
    assert logs == ([(0x1234, 0x23, 0x1432B3158, 0, 0)] if enable else [])
    reads = [a for a in h.accesses if a[:3] == ("read", 0x144355068, 8)]
    assert bool(reads) == bool(enable)


def test_moving_does_not_add_status_recheck_after_selected_callback():
    def before(h, target, _args):
        if target == SELECTED:
            h.memory.write(h.out + 24, 8, 5)

    h = setup(MOVING, before=before)
    h.memory.write(0x14435505B, 1, 1)
    h.memory.map_bytes(0x144355068, bytes(8))
    invoke(h)
    assert 0x14101ADB0 in targets(h)


@pytest.mark.parametrize("entry", [MOVING, UNIT])
def test_failed_reader_status_is_checked_only_after_real_cleanup(entry):
    def after(h, target, args, _answer):
        if target == READERS[entry]:
            h.memory.write(args[1] + 24, 8, 7)
        return None

    h = setup(entry, after=after)
    invoke(h, 1)
    assert targets(h).count(CLEANUP) == 2
    assert 0x14101ADB0 not in targets(h) and not h.float_seen


def install_fp_context(h, *, group=13, identifier=-1):
    m = h.memory
    h.masters = [m.allocate(0x100) for _ in range(3)]
    h.owner, h.array, h.owner_entry = (m.allocate(n) for n in (0x30, 16, 8))
    h.array += 8  # Signed ID -1 must access the preceding backed slot.
    h.master_table, h.entry_table = (m.allocate(0x100) for _ in range(2))
    m.write(h.masters[0] + 0x38, 8, (group - 0x5B32AA7995D95916 + 0x50A06BCECEBEF905) & U64)
    m.write(h.masters[1], 8, h.master_table)
    m.write(h.master_table + 0xF0, 8, 0xF000)
    m.write(
        h.masters[2] + 0x18, 8, ((identifier & 0xFFFF) + 0x47E37DFF0616CE4F) ^ 0x349E37847AD69F19
    )
    m.write(h.obj + 0x10, 8, (h.masters[0] + MASTER_ADD) & U64)
    m.write(h.obj + 0x18, 8, h.owner)
    m.write(h.obj + 0x200, 8, 1)
    m.write(h.owner + 0x28, 8, h.array)
    m.write(h.array + identifier * 8, 8, h.owner_entry)
    m.write(h.owner_entry, 8, h.entry_table)
    m.write(h.entry_table + 0xE8, 8, 0xE800)


def master_reads(h, address, width, value):
    if (address, width) == (h.obj + 0x10, 8):
        h.master_read_count += 1
        if h.master_read_count < 3:
            h.memory.write(h.obj + 0x10, 8, (h.masters[h.master_read_count] + MASTER_ADD) & U64)
    return value


def test_unit_current_three_master_decodes_signed_id_and_held_fp_target_full128():
    pattern = 0xFEDCBA9876543210000000007FC01234

    def floating(h, target, args, xmm1):
        if target == 0xE800:
            assert args == (h.owner_entry,) and xmm1 is None
            h.memory.write(h.master_table + 0xF0, 8, 0xBAD)
            h.memory.write(h.obj + 0x10, 8, 0)
            h.memory.write(h.obj + 0x18, 8, 0)
            return pattern
        assert (target, args, xmm1) == (0xF000, (h.masters[1],), pattern)
        return None

    h = setup(UNIT, on_read=master_reads, floating=floating)
    install_fp_context(h)
    h.master_read_count = 0
    invoke(h)
    assert h.master_read_count == 3
    assert h.float_seen == [(0xE800, (h.owner_entry,), None), (0xF000, (h.masters[1],), pattern)]


@pytest.mark.parametrize("returned", [None, -1, 1 << 128, True])
def test_unit_fp_first_return_unavailable_or_nonraw128_refuses_without_second_call(returned):
    h = setup(UNIT, on_read=master_reads, floating=lambda *_args: returned)
    install_fp_context(h)
    h.master_read_count = 0
    with pytest.raises((ValueError, UnresolvedReplayTaskRebuild)):
        invoke(h)
    assert len(h.float_seen) == 1 and not h.frames


def test_unit_group_other_than13_skips_owner_and_floating_reads():
    h = setup(UNIT, on_read=master_reads)
    install_fp_context(h, group=12)
    h.master_read_count = 0
    invoke(h)
    assert h.master_read_count == 1 and not h.float_seen
    assert not any(a[:3] == ("read", h.obj + 0x18, 8) for a in h.accesses)


def test_recursive_real_six_body_prefix_refuses_at_first_base_child_without_fake_success():
    h = setup(UNIT)
    h.bound = bind_replay_unit_construction(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SCRATCH,
    )
    original_result = h.memory.read_bytes(h.out, 48)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14122dc70"):
        invoke(h, 1, direct=False)
    assert h.memory.read(h.obj, 8) == TABLES[BASE]
    assert h.memory.read(h.obj + 0x10, 8) == MASTER_ADD & U64
    assert h.memory.read_bytes(h.obj + 0x100, 4) == b"\xa5" * 4
    assert h.memory.read_bytes(h.out, 48) == original_result
    assert len(h.finished) == 6 and not h.frames


@pytest.mark.parametrize(
    "entry,missing",
    [(BASE, 0x14122DC70), (ACTION, 0x141136CA0), (COMBAT, 0x1411438B0), (UNIT, 0x1412A5C60)],
)
def test_missing_mandatory_child_keeps_actual_prior_writes(entry, missing):
    def before(_h, target, _args):
        if target == missing:
            raise UnresolvedReplayTaskRebuild(f"actual child{missing:x} unavailable")

    h = setup(entry, before=before)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual child"):
        invoke(h)
    assert h.memory.read(h.obj, 8) == TABLES[entry]
    assert not h.frames
    if entry == COMBAT:
        assert h.memory.read(h.obj + 0x520, 8) == h.allocations[0]
        assert h.memory.read(h.obj + 0x58C, 1) == 0xA5
    if entry == UNIT:
        assert h.memory.read(h.obj + 0x75C, 8) == 0
        assert h.memory.read_bytes(h.obj + 0x80C, 8) == b"\xa5" * 8


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("arity", [0, 4, 6])
def test_binder_rejects_wrong_constructor_arity_before_effects(entry, arity):
    h = setup(entry)
    assert h.bound.call
    with pytest.raises(ValueError, match="five-argument"):
        h.bound.call(entry, (1,) * arity, None)
    assert not h.accesses and not h.frames and not h.calls_seen


def test_binder_unknown_targets_delegate_and_missing_targets_refuse():
    h = setup(BASE)
    assert h.bound.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="fixture has no actual child"):
        h.bound.call(0x12345, (1,), None)
    assert targets(h) == [0x12345]


def test_explicit_scratch_and_float_provider_validation():
    with pytest.raises(ValueError, match="base construction frame"):
        ReplayUnitConstructionScratch(
            bytes(1), SCRATCH.animated, SCRATCH.moving, SCRATCH.action, SCRATCH.combat, SCRATCH.unit
        )
    with pytest.raises(ValueError, match="floating-call"):
        ReplayUnitConstructionFloatingCalls(123)
