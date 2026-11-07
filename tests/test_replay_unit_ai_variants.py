"""Initial AI constructor ownership, dynamic branches and derived reader effects."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_task_rows import bind_replay_task_rows
from vantage.replay_unit_ai_base import bind_replay_unit_ai_base
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_ai_support import bind_replay_unit_ai_support
from vantage.replay_unit_ai_variants import (
    ReplayUnitAIVariantScratch,
    bind_replay_unit_ai_variants,
)
from vantage.replay_unit_ai_vector_growth import bind_replay_unit_ai_vector_growth

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/native_unit_ai_variants_54800.json").read_bytes()
)
PLANS = {row["tag"]: row for row in FIXTURE["variants"]}
SEED = ReplayUnitAIVariantScratch(b"\xa3" * 0x140, b"\xb4" * 0xC0, b"\xc5" * 0xD0)
MASK = (1 << 64) - 1
MASTER_ADD = 0x6A586EB28AC201FC + 0xCF19788B2554E70
CLASS_SUB = 0x50A06BCECEBEF905 - 0x5B32AA7995D95916


def static(memory):
    rows = {}
    for plan in PLANS.values():
        for row in plan["class_current_static_read_order"]:
            rows[int(row["address"], 16)] = bytes.fromhex(row["raw_hex"])
    for row in FIXTURE["AI17_row_defaults"]:
        rows[int(row["address"], 16)] = bytes.fromhex(row["raw_hex"])
    for address, raw in rows.items():
        memory.map_bytes(address, raw)
    memory.map_bytes(0x1431999A0, (0x142D6E3DB).to_bytes(8, "little"))
    memory.map_bytes(0x143199DD0, (0x142D6BAB4).to_bytes(8, "little"))


def constructor_setup(
    *,
    kind=0,
    master_id=0,
    master_flag=0,
    player_mode=0,
    world_mode=0,
    extra=None,
    after_read=None,
    after_write=None,
    real_vectors=False,
):
    memory = ReplayMemory()
    static(memory)
    ai, unit, master, player, unit_table, player_table, game, world = (
        memory.allocate(n) for n in (0x210, 0x900, 0x500, 0x100, 0x868, 0x98, 0x600, 0x700)
    )
    for pointer, size in (
        (ai, 0x210),
        (unit, 0x900),
        (master, 0x500),
        (player, 0x100),
        (unit_table, 0x868),
        (player_table, 0x98),
        (game, 0x600),
        (world, 0x700),
    ):
        memory.write_bytes(pointer, b"\x6d" * size)
    memory.write(unit, 8, unit_table)
    memory.write(unit + 16, 8, master + MASTER_ADD)
    memory.write(unit + 24, 8, player)
    memory.write(master + 0x38, 8, (kind + CLASS_SUB) & MASK)
    memory.write(master + 24, 8, ((master_id + 0x47E37DFF0616CE4F) & MASK) ^ 0x349E37847AD69F19)
    memory.write(master + 0x379, 1, master_flag)
    memory.write(player, 8, player_table)
    memory.write(player + 16, 4, player_mode)
    memory.write(unit_table + 0x860, 8, 0xFA860)
    memory.write(player_table + 0x90, 8, 0xFA090)
    memory.map_bytes(0x144353698, game.to_bytes(8, "little"))
    memory.write(game + 0x5C0, 8, world)
    memory.write(world + 0x6B4, 4, world_mode)
    coordinates = (0x3F800000, 0x40000000, 0x40400000)
    for offset, value, adjustment in (
        (0x170, coordinates[0], 0x183CAC30D2441D0E - 0x4C3FBA69E4EA7FD1),
        (0x178, coordinates[1], 0x61501AA6ECFD980A - 0x6C5EAB60B426DD28),
        (0x180, coordinates[2], -0x2B3719EF44DE99FF - 0x21D14A25ED7C802C),
    ):
        memory.write(unit + offset, 8, (value + adjustment) & MASK)
    reads, effects, locals_seen = [], [], []
    state = dict(
        memory=memory,
        ai=ai,
        unit=unit,
        master=master,
        player=player,
        world=world,
        game=game,
        reads=reads,
        effects=effects,
        locals=locals_seen,
    )

    def read(address, width):
        value = memory.read(address, width)
        reads.append((address, width, value))
        if after_read:
            after_read(state, address, width, value)
        return value

    def write(address, width, value):
        memory.write(address, width, value)
        if after_write:
            after_write(state, address, width, value)

    context = ReplayTaskRebuildStorage(unit, read, write)
    runtime = memory.runtime_calls()
    support = bind_replay_unit_ai_support(context, runtime)
    class_calls = bind_replay_unit_ai_base(context, support, imports=runtime)
    rows = bind_replay_task_rows(context, class_calls, bind_local=memory.bind_local)
    vectors = bind_replay_unit_ai_vector_growth(context, rows, imports=runtime)

    def call(target, args, data):
        effects.append((target, args, data))
        if extra and extra(state, target, args, data):
            return state.get("return_value")
        if target == 0x140D094C0:
            # Explicit predecessor fixture, not a claim of complete base construction.
            memory.write(args[0] + 8, 8, args[1])
            memory.write(args[0] + 0x1B1, 1, 9)
            for offset in (0x198, 0x1A0, 0x1A8):
                memory.write(args[0] + offset, 8, 0)
            return 0xBAD  # Constructor caller must ignore this RAX.
        if target == 0x140CEFB30:
            begin, end = (memory.read(args[1] + offset, 8) for offset in (0, 8))
            locals_seen.append((args[1], begin, end, memory.read_bytes(begin, end - begin)))
            assert begin == args[1] + 16  # Original coherent relative stack layout.
            assert class_calls.call is not None
            return class_calls.call(target, args, data)
        if target == 0x140D19DD0:
            memory.write(args[0] + 0x170, 4, args[1])
            return 0x123
        if target == 0xFA860:
            return 0x7FC01234
        if target == 0xFA090:
            return 0x123456789ABCDE6B
        delegate = vectors if real_vectors else runtime
        assert delegate.call is not None
        return delegate.call(target, args, data)

    atomics = ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)
    bound = bind_replay_unit_ai_variants(
        context,
        ReplayTaskRebuildCalls(call),
        atomics=atomics,
        bind_local=memory.bind_local,
        scratch=SEED,
    )
    state.update(calls=bound, context=context)
    return state


def construct(state, tag):
    bound = state["calls"]
    assert bound.call is not None
    plan = PLANS[tag]
    return bound.call(
        int(plan["constructor"], 16), (state["ai"], state["unit"], 0xF12345670000000A), None
    )


@pytest.mark.parametrize("tag", [2, 4, 5, 8, 13, 17, 19])
def test_all_seven_callers_use_actual_current_class_backing_and_preserve_other_bytes(tag):
    state = constructor_setup()
    memory, ai, unit = state["memory"], state["ai"], state["unit"]
    assert construct(state, tag) == ai
    plan = PLANS[tag]
    assert state["effects"][0] == (
        0x140D094C0,
        (ai, unit, 0xF12345670000000A, plan["common_R9D"]),
        None,
    )
    assert memory.read(ai, 8) == int(plan["vtable"], 16)
    if plan["class_bytes"]:
        begin, end = memory.read(ai + 0x198, 8), memory.read(ai + 0x1A0, 8)
        assert end - begin == plan["class_bytes"]
        assert memory.read_bytes(begin, end - begin) == bytes.fromhex(plan["original_class_hex"])
        descriptor, first, last, raw = state["locals"][0]
        assert raw == bytes.fromhex(plan["original_class_hex"]) and last - first == len(raw)
        for pointer in (descriptor, first):
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                memory.read(pointer, 1)
    assert memory.read_bytes(ai + 0x1DF, 0x19) == b"\x6d" * 0x19
    if tag in (2, 4):
        assert [memory.read(ai + offset, 4) for offset in (0x1F8, 0x1FC, 0x200)] == [
            0x3F800000,
            0x40000000,
            0x40400000,
        ]
    if tag == 2:
        assert memory.read(ai + 0x204, 4) == 0x7FC01234
    elif tag == 4:
        assert memory.read_bytes(ai + 0x204, 4) == b"\0\0mm"
    elif tag == 8:
        assert memory.read_bytes(ai + 0x1F8, 8) == (4500).to_bytes(4, "little") + b"m" * 4
    elif tag == 17:
        assert memory.read_bytes(ai + 0x1F8, 24) == bytes(24)
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()


@pytest.mark.parametrize("kind, expected", [(58, 9), (59, 0), (0x1003B, 0)])
def test_type2_kind_only_clears_flag_on_low_word59_and_current_owner_virtual(kind, expected):
    state = constructor_setup(kind=kind)
    construct(state, 2)
    memory, ai = state["memory"], state["ai"]
    assert memory.read(ai + 0x1B1, 1) == expected
    assert state["effects"][-1] == (0xFA860, (state["unit"],), None)


@pytest.mark.parametrize("world_mode", [0, 1, 2, 0xFFFFFFFF])
def test_type5_exact_world_one_branch_requires_reused_live_class_argument(world_mode):
    seen = []

    def extra(state, target, args, data):
        if target != 0x1402B89C0:
            return False
        assert args[0] == state["ai"] + 0x198 and data is None
        seen.append((args[1], state["memory"].read(args[1], 4)))
        state["return_value"] = None
        return True

    state = constructor_setup(world_mode=world_mode, extra=extra)
    construct(state, 5)
    assert [value for _, value in seen] == ([47, 18, 13, 55] if world_mode == 1 else [])
    if seen:
        assert len({pointer for pointer, _ in seen}) == 1
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            state["memory"].read(seen[0][0], 1)
    assert state["effects"][-1][0:2] == (0x140D19DD0, (state["ai"], 6000))


def test_missing_positive_type5_child_stops_before_flag_and_timer_with_prior_classes_intact():
    state = constructor_setup(world_mode=1)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402b89c0"):
        construct(state, 5)
    memory, ai = state["memory"], state["ai"]
    assert memory.read(ai + 0x1B1, 1) == 9
    assert memory.read_bytes(memory.read(ai + 0x198, 8), 72) == bytes.fromhex(
        PLANS[5]["original_class_hex"]
    )
    assert not any(target == 0x140D19DD0 for target, _, _ in state["effects"])


@pytest.mark.parametrize(
    "kind,master_id,flag,expected",
    [
        (0, 0x20F, 0, 1),
        (0, 0x210, 0, 1),
        (0, 0x450, 0, 1),
        (35, 0, 0, 3),
        (64, 0, 0, 3),
        (61, 0, 0, 3),
        (0, 0, 1, 1),
        (0, 0, 8, 1),
        (0, 0, 0x81, 1),
        (0, 0, 0x88, 0x6B),
        (0, 0, 0, 0x6B),
    ],
)
def test_type13_id_group_signed_flags_and_current_player_fallback(kind, master_id, flag, expected):
    state = constructor_setup(kind=kind, master_id=master_id, master_flag=flag)
    construct(state, 13)
    assert state["memory"].read(state["ai"] + 0x1B1, 1) == expected
    timers = [args for target, args, _ in state["effects"] if target == 0x140D19DD0]
    assert timers == [(state["ai"], 500)]


def test_type13_holds_first_group_but_reloads_player_mode_after_timer():
    def extra(state, target, args, data):
        if target != 0x140D19DD0:
            return False
        state["memory"].write(state["master"] + 0x38, 8, CLASS_SUB & MASK)
        state["return_value"] = None
        return True

    state = constructor_setup(kind=35, extra=extra)
    construct(state, 13)
    assert state["memory"].read(state["ai"] + 0x1B1, 1) == 3
    mode_reads = [r for r in state["reads"] if r[0] == state["player"] + 16]
    assert len(mode_reads) == 4


def test_type13_current_player_mode_three_adds_ten_and_selects1500():
    seen = []

    def extra(state, target, args, data):
        if target != 0x1402B89C0:
            return False
        seen.append(state["memory"].read(args[1], 4))
        state["return_value"] = None
        return True

    state = constructor_setup(player_mode=3, kind=35, extra=extra)
    construct(state, 13)
    assert seen == [10]
    assert (0x140D19DD0, (state["ai"], 1500), None) in state["effects"]
    assert state["memory"].read(state["ai"] + 0x1B1, 1) == 0x6B


def reader_setup(
    raw,
    *,
    entry=0x140CF9460,
    version=0x44E666,
    common_status=0,
    after_effect=None,
    after_write=None,
    real_vectors=False,
):
    memory = ReplayMemory()
    static(memory)
    ai, out, stream, table = (memory.allocate(n) for n in (0x210, 48, 8, 32))
    memory.write_bytes(ai, b"I" * 0x210)
    memory.write_bytes(out, b"O" * 48)
    memory.write(stream, 8, table)
    memory.write(table + 24, 8, 0xAF100)
    memory.map_bytes(0x1440A0D94, version.to_bytes(4, "little"))
    for offset in (0x1F8, 0x200, 0x208):
        memory.write(ai + offset, 8, 0)

    def write(address, width, value):
        memory.write(address, width, value)
        if after_write:
            after_write(memory, ai, address, width, value)

    context = ReplayTaskRebuildStorage(ai, memory.read, write)
    atomics = ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)
    source = ReplaySavedInput(raw)
    runtime = memory.runtime_calls()
    strings = bind_replay_saved_string(context, runtime, imports=runtime)
    results = bind_replay_saved_result(context, strings, atomics=atomics, imports=runtime)
    io = bind_replay_saved_input(
        context, results, source, stream=stream, target=0xAF100, result_bytes=bytes(48)
    )
    rows = bind_replay_task_rows(context, io, bind_local=memory.bind_local)
    vectors = bind_replay_unit_ai_vector_growth(context, rows, imports=runtime)
    events = []

    def call(target, args, data):
        events.append((target, args, data))
        if target == 0x140D267D0:
            assert args[0] == ai and args[2] == stream
            expected = b"\xb4" if entry == 0x140CF9460 else b"\xc5"
            assert memory.read_bytes(args[1], 48) == expected * 48
            memory.write_bytes(args[1], bytes(48))
            memory.write(args[1] + 24, 8, common_status)
            answer = args[1]
        else:
            delegate = vectors if real_vectors else io
            assert delegate.call is not None
            answer = delegate.call(target, args, data)
        if after_effect:
            after_effect(memory, ai, target, args)
        return answer

    bound = bind_replay_unit_ai_variants(
        context,
        ReplayTaskRebuildCalls(call),
        atomics=atomics,
        bind_local=memory.bind_local,
        scratch=SEED,
    )
    return memory, ai, out, stream, source, events, bound


def invoke_reader(parts, entry=0x140CF9460):
    _, ai, out, stream, _, _, bound = parts
    assert bound.call is not None
    return bound.call(entry, (ai, out, stream), None)


def test_ai4_four_reads_preserve_untouched_constructor_bytes_and_output_padding():
    raw = bytes.fromhex("010000000200000003000000a7")
    parts = reader_setup(raw)
    memory, ai, out, _, source, events, _ = parts
    before = memory.read_bytes(ai, 0x210)
    assert invoke_reader(parts) == out
    assert source.remaining == 0 and memory.read_bytes(ai + 0x1F8, 13) == raw
    assert memory.read_bytes(ai + 0x205, 11) == before[0x205:]
    assert memory.read_bytes(out, 48) == bytes(41) + b"O" * 7
    assert [args[3] for target, args, _ in events if target == 0xAF100] == [4, 4, 4, 1]


@pytest.mark.parametrize("version", [0, 0xD0F5B, 0x80000000, 0xFFFFFFFF])
def test_ai4_old_signed_gate_preserves_derived_fields_after_unconditional_common_cleanup(version):
    parts = reader_setup(b"", version=version, common_status=0xC0FFEE)
    memory, ai, _, _, source, events, _ = parts
    before = memory.read_bytes(ai, 0x210)
    invoke_reader(parts)
    assert memory.read_bytes(ai, 0x210) == before and source.position == 0
    assert [target for target, _, _ in events] == [0x140D267D0, 0x1402BD7F0]


def test_ai4_version_changes_during_common_cleanup_and_current_stream_is_reloaded():
    def after(memory, ai, target, args):
        if target == 0x1402BD7F0:
            memory.write(0x1440A0D94, 4, 0xD0F5C)

    parts = reader_setup(bytes(13), version=0, common_status=23, after_effect=after)
    invoke_reader(parts)
    assert parts[4].position == 13


@pytest.mark.parametrize("count", [0, 0xFFFFFFFF, 0x80000000])
def test_ai17_nonpositive_count_preserves_vector_and_uses_four_bytes(count):
    parts = reader_setup(count.to_bytes(4, "little"), entry=0x140CF8F00)
    memory, ai, _, _, source, events, _ = parts
    before = memory.read_bytes(ai + 0x1F8, 24)
    invoke_reader(parts, 0x140CF8F00)
    assert source.position == 4 and memory.read_bytes(ai + 0x1F8, 24) == before
    assert [args[3] for target, args, _ in events if target == 0xAF100] == [4]


def test_ai17_positive_record_copies_all52_bytes_and_increments_current_end_after_copy():
    raw_record = bytes(range(52))
    pointers = {}

    def after_write(memory, ai, address, width, value):
        if "end" in pointers and address == pointers["end"] + 48:
            memory.write(ai + 0x200, 8, pointers["end"] + 52)

    parts = reader_setup(
        (1).to_bytes(4, "little") + raw_record, entry=0x140CF8F00, after_write=after_write
    )
    memory, ai, _, _, source, _, _ = parts
    end = memory.allocate(156)
    pointers["end"] = end
    for offset, value in ((0x1F8, end), (0x200, end), (0x208, end + 156)):
        memory.write(ai + offset, 8, value)
    invoke_reader(parts, 0x140CF8F00)
    assert source.position == 56 and memory.read_bytes(end, 52) == raw_record
    assert memory.read(ai + 0x200, 8) == end + 104


def test_ai17_full_capacity_growth_is_required_after_record_was_consumed():
    parts = reader_setup((1).to_bytes(4, "little") + bytes(52), entry=0x140CF8F00)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140cedd60"):
        invoke_reader(parts, 0x140CF8F00)
    assert parts[4].position == 56


@pytest.mark.parametrize(
    "entry, args",
    [
        (0x140CEE930, (1,)),
        (0x140CF9460, (1, 2)),
        (0x140CF8F00, (1, 2, -1)),
        (0x140D6ACC0, ()),
        (0x14172AC80, (1, 2)),
    ],
)
def test_known_entries_reject_bad_shape_without_any_effect(entry, args):
    state = constructor_setup()
    before = state["memory"].snapshot()
    with pytest.raises(ValueError):
        state["calls"].call(entry, args, None)
    assert state["memory"].snapshot() == before and state["effects"] == []


@pytest.mark.parametrize(
    "tag, world_mode, player_mode, appended",
    [
        (5, 1, 0, [47, 18, 13, 55]),
        (13, 0, 3, [10]),
    ],
)
def test_positive_constructor_classes_compose_real_append_allocate_move_commit_and_free(
    tag,
    world_mode,
    player_mode,
    appended,
):
    state = constructor_setup(world_mode=world_mode, player_mode=player_mode, real_vectors=True)
    assert construct(state, tag) == state["ai"]
    memory, ai = state["memory"], state["ai"]
    begin, end = memory.read(ai + 0x198, 8), memory.read(ai + 0x1A0, 8)
    expected = PLANS[tag]["original_class_words"] + appended
    assert [memory.read(begin + index * 4, 4) for index in range(len(expected))] == expected
    assert end == begin + 4 * len(expected)
    assert memory.read(ai + 0x1A8, 8) > end


def test_ai17_positive_record_composes_actual_growth_commit_and_native_padding_copy():
    record = bytes(range(52))
    parts = reader_setup((1).to_bytes(4, "little") + record, entry=0x140CF8F00, real_vectors=True)
    memory, ai, out, _, source, _, _ = parts
    assert invoke_reader(parts, 0x140CF8F00) == out
    begin = memory.read(ai + 0x1F8, 8)
    assert memory.read_bytes(begin, 52) == record and source.position == 56
    assert memory.read(ai + 0x200, 8) == memory.read(ai + 0x208, 8) == begin + 52
