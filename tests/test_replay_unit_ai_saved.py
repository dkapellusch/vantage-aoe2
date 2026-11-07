"""Complete actual TC savedAI composition and current positive-group caller effects."""

from __future__ import annotations

import hashlib

import pytest

from vantage.replay_binary import SaveReader
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
from vantage.replay_unit_ai import read_unit_ai
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_ai_saved import (
    ReplaySavedAIScratch,
    bind_replay_saved_unit_ai,
)

# Actual TC5595/owner1/master109, frozen wire hash0e5031b3; constructor inputs
# below remain explicitly authored rather than a claim of whole World restore.
RAW = bytes.fromhex(
    "ffffffffffffffffffffffffffffffffffffffffffffffff000080bf000080bf000080bf00000040ffffffffffffffff"
    "ffffffffffffffff0000000000000000e803000067040000ee02000000000000e8030000ffffffff00000041000080bf"
    "000080bf000080bf000000000000000000000000000000000000000034420000e8410000000000ffffffff0000000000"
    "00000000000000c10100000e04000000000000ffffffff00000000000001000034420000e84100000000000000000000"
)
SCRATCH = ReplaySavedAIScratch(b"\xac" * 0xD70, b"\xbd" * 0xD0)


def setup(raw=RAW, *, lower=None, after_effect=None, after_write=None):
    memory = ReplayMemory()
    ai, output, stream, table, position = (memory.allocate(n) for n in (528, 48, 8, 32, 16))
    memory.write_bytes(ai, b"Z" * 528)
    memory.write_bytes(output, b"O" * 48)
    memory.write_bytes(position, b"P" * 16)
    for pointer, value in (
        (ai + 0xA8, ai + 0x78),
        (ai + 0xB0, ai + 0x78),
        (ai + 0xC0, position),
        (stream, table),
        (table + 24, 0xA110),
    ):
        memory.write(pointer, 8, value)
    memory.write(ai + 0xB8, 4, 0)
    for offset in (0x1F8, 0x200, 0x208):
        memory.write(ai + offset, 8, 0)
    for pointer, value in ((0x143199DD0, 0x142D6BAB4), (0x143199938, 0x142D6E3B7)):
        memory.map_bytes(pointer, value.to_bytes(8, "little"))
    memory.map_bytes(0x1440A0D94, (0x44E666).to_bytes(4, "little"))

    def write(pointer, width, value):
        memory.write(pointer, width, value)
        if after_write:
            after_write(memory, pointer, width, value)

    context = ReplayTaskRebuildStorage(ai, memory.read, write)
    atomic = ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)
    source = ReplaySavedInput(raw)
    runtime = memory.runtime_calls(ReplayTaskRebuildCalls(lower) if lower else None)
    io = bind_replay_saved_input(
        context, runtime, source, stream=stream, target=0xA110, result_bytes=bytes(48)
    )
    reads = []

    def watch(target, args, data):
        if target == 0xA110:
            reads.append((source.position, args))
        assert io.call is not None
        return io.call(target, args, data)

    strings = bind_replay_saved_string(context, ReplayTaskRebuildCalls(watch), imports=runtime)
    result = bind_replay_saved_result(context, strings, atomics=atomic, imports=runtime)
    apply = bind_replay_saved_apply(context, result, atomics=atomic, imports=runtime)
    positions = bind_replay_saved_position(
        context, apply, atomics=atomic, bind_local=memory.bind_local
    )

    def effect(target, args, data):
        assert positions.call is not None
        answer = positions.call(target, args, data)
        if after_effect:
            after_effect(memory, target, args, answer)
        return answer

    calls = bind_replay_saved_unit_ai(
        context,
        ReplayTaskRebuildCalls(effect),
        atomics=atomic,
        bind_local=memory.bind_local,
        scratch=SCRATCH,
        imports=runtime,
    )
    return memory, ai, output, stream, position, context, atomic, source, reads, calls


def invoke(parts, entry=0x140CF9DC0):
    _memory, ai, output, stream, *_rest, calls = parts
    assert calls.call is not None
    return calls.call(entry, (ai, output, stream), None)


def test_complete_actual192B_TC_uses50_reads_real_forward_copy_cleanup_and_position():
    parts = setup()
    memory, ai, output, _stream, position, _, _, source, reads, _ = parts
    assert hashlib.sha256(RAW).hexdigest() == (
        "0e5031b3f84d28093d1d0318c0289522fa7a98cc2aa61f878af91d796c8e79d1"
    )
    before = memory.read_bytes(ai, 528)
    parsed = read_unit_ai(SaveReader(RAW, version=0x44E666), 15)
    assert invoke(parts) == output
    assert source.position == 192 and source.remaining == 0 and len(reads) == 50
    assert [args[3] for _, args in reads[:24]] == [4] * 23 + [16]
    assert [args[3] for _, args in reads[-6:]] == [1, 4, 4, 4, 2, 4]
    for offset, word in parsed.fields.items():
        assert (
            memory.read(ai + offset, 1 if offset in (0x1B0, 0x1B1, 0x1C0, 0x1DC, 0x1DE) else 4)
            == word
        )
    assert memory.read_bytes(ai + 0x18, 0x24) == before[0x18:0x3C]
    assert memory.read_bytes(ai + 0x1F8, 24) == before[0x1F8:0x210]
    assert memory.read_bytes(position, 14) == RAW[174:188]
    assert memory.read_bytes(position + 14, 2) == b"PP"
    assert memory.read_bytes(output, 41) == bytes(41)
    assert memory.read_bytes(output + 41, 7) == b"O" * 7
    assert memory.read(ai + 0xA8, 8) == memory.read(ai + 0xB0, 8) == ai + 0x78
    assert memory.read(ai + 0xB8, 4) == 0
    assert ReplayMemory.from_snapshot(memory.snapshot()).snapshot() == memory.snapshot()


@pytest.mark.parametrize("count", [0xFFFFFFFF, 0x80000000])
def test_negative_counts_skip_groups_without_erasing_constructor_fields(count):
    raw = bytearray(RAW)
    for offset in (108, 112, 116, 147, 159, 188):
        raw[offset : offset + 4] = count.to_bytes(4, "little")
    parts = setup(bytes(raw))
    memory, ai, output, _, _, _, _, source, reads, _ = parts
    before = memory.read_bytes(ai + 0x18, 0x24)
    assert invoke(parts) == output and source.remaining == 0 and len(reads) == 50
    assert memory.read_bytes(ai + 0x18, 0x24) == before


def test_zero_spawn_flag_leaves_current_constructor_position_untouched():
    raw = RAW[:173] + b"\0" + RAW[188:]
    parts = setup(raw)
    memory, _, _, _, position, _, _, source, reads, _ = parts
    invoke(parts)
    assert source.remaining == 0 and len(reads) == 46
    assert memory.read_bytes(position, 16) == b"P" * 16


def test_unconditional_clear_frees_real_old_nodes_before_zero_saved_list_count():
    parts = setup()
    memory, ai, *_ = parts
    old = memory.allocate(64)
    memory.write(ai + 0xA8, 8, old)
    memory.write(ai + 0xB0, 8, old)
    memory.write(ai + 0xB8, 4, 1)
    memory.write(old + 48, 8, ai + 0x78)
    invoke(parts)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(old, 1)
    assert memory.read(ai + 0xB8, 4) == 0


def test_positive_first_group_requires_actual_state_helper_after_record_and_cleanup():
    raw = RAW[:108] + (1).to_bytes(4, "little") + bytes(range(52)) + RAW[112:]
    parts = setup(raw)
    memory, ai, _, _, _, _, _, source, _, _ = parts
    for pointer in (0x14324ABA0, 0x14324B1D0):
        memory.map_bytes(pointer, bytes(16))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140d1adf0"):
        invoke(parts)
    assert source.position == 164
    assert memory.read(ai + 0x170, 4) == 1000


def test_positive52record_argument_order_and_current_count_recheck():
    record = bytes(range(52))
    raw = RAW[:108] + (1).to_bytes(4, "little") + record + RAW[112:]
    seen = []

    def lower(target, args, data):
        assert target == 0x140D1ADF0 and data is None
        seen.append(args)

    parts = setup(raw, lower=lower)
    memory, ai, *_ = parts
    for pointer in (0x14324ABA0, 0x14324B1D0):
        memory.map_bytes(pointer, bytes(16))
    invoke(parts)
    words = [int.from_bytes(record[i : i + 4], "little") for i in range(0, 52, 4)]
    assert seen == [
        (
            ai,
            words[0],
            words[1],
            words[3],
            words[12],
            words[4],
            words[5],
            words[6],
            words[7],
            words[8],
            0,
            words[2],
            words[9],
            words[10],
            record[44],
        )
    ]


def test_positive24record_does_not_copy_raw_bytes_into_constructor_array():
    record = bytes(range(24))
    raw = RAW[:112] + (1).to_bytes(4, "little") + record + RAW[116:]
    seen = []

    def lower(target, args, data):
        assert target == 0x140D1AC10 and data is None
        seen.append(args)

    parts = setup(raw, lower=lower)
    memory, ai, *_ = parts
    before = memory.read_bytes(ai + 0x28, 16)
    invoke(parts)
    assert seen == [(ai, *(int.from_bytes(record[i : i + 4], "little") for i in range(0, 24, 4)))]
    assert memory.read_bytes(ai + 0x28, 16) == before


def test_positive_id_read_has_distinct_mandatory_status_cleanup_before_append():
    raw = RAW[:116] + (1).to_bytes(4, "little") + (99).to_bytes(4, "little") + RAW[120:]
    parts = setup(raw)
    source = parts[7]
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1408ee150"):
        invoke(parts)
    assert source.position == 124


def test_positive44record_allocates_links_real_node_and_consumes44wire_bytes():
    record = bytes(range(44))
    raw = RAW[:147] + (1).to_bytes(4, "little") + record + RAW[151:]
    parts = setup(raw)
    memory, ai, *_ = parts
    invoke(parts)
    node = memory.read(ai + 0xA8, 8)
    assert node != ai + 0x78 and memory.read(ai + 0xB0, 8) == node
    assert memory.read_bytes(node, 44) == record
    assert memory.read(node + 48, 8) == memory.read(node + 56, 8) == ai + 0x78
    assert memory.read(ai + 0xB8, 4) == 1


def test_positive_pairs_call_actual_helper_in_wire_order():
    raw = RAW[:159] + (1).to_bytes(4, "little") + bytes.fromhex("0700000009000000") + RAW[163:]
    seen = []

    def lower(target, args, data):
        assert target == 0x140D1AAC0 and data is None
        seen.append(args)

    parts = setup(raw, lower=lower)
    invoke(parts)
    assert seen == [(parts[1], 7, 9)]


def test_positive_derived_record_reuses_capacity_and_increments_current_end():
    record = bytes(range(52))
    raw = RAW[:188] + (1).to_bytes(4, "little") + record
    parts = setup(raw)
    memory, ai, *_ = parts
    array = memory.allocate(104)
    memory.write(ai + 0x1F8, 8, array)
    memory.write(ai + 0x200, 8, array)
    memory.write(ai + 0x208, 8, array + 104)
    for pointer in (0x14324ABA0, 0x14324B1D0):
        memory.map_bytes(pointer, bytes(16))
    invoke(parts)
    assert memory.read_bytes(array, 52) == record
    assert memory.read(ai + 0x200, 8) == array + 52


def test_derived_growth_requires_real_child_with_descriptor_address():
    raw = RAW[:188] + (1).to_bytes(4, "little") + bytes(range(52))
    parts = setup(raw)
    memory, _, _, _, _, _, _, source, _, _ = parts
    for pointer in (0x14324ABA0, 0x14324B1D0):
        memory.map_bytes(pointer, bytes(16))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140cedd60"):
        invoke(parts)
    assert source.remaining == 0


def test_nonempty_path_requires_constructor_after_allocation_and_real_memset():
    raw = RAW[:139] + (1).to_bytes(4, "little") + RAW[143:]
    parts = setup(raw)
    memory, _, _, _, _, _, _, source, _, _ = parts
    before = memory.mapped_bytes
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14106a110"):
        invoke(parts)
    assert source.position == 143 and memory.mapped_bytes == before + 0x548


def test_version_changes_after_unconditional_clear_reach_all_old_fallbacks():
    seen = []

    def effect(memory, target, args, answer):
        if target == 0x140D36FE0:
            memory.write(0x1440A0D94, 4, 0)

    def lower(target, args, data):
        assert target == 0x140D3ECE0 and data is None
        seen.append(args)
        memory.write(args[0] + 0x1D4, 4, 1000)

    parts = setup(RAW[:147], lower=lower, after_effect=effect)
    memory, ai, output, _, position, _, _, source, reads, _ = parts
    invoke(parts)
    assert source.position == 147 and source.remaining == 0 and len(reads) == 36
    assert seen == [(ai, 1000, 0x14324B4F0, 0x3B7)]
    assert memory.read(ai + 0xBC, 4) == 0 and memory.read(ai + 0x1D4, 4) == 1000
    assert memory.read(ai + 0x1D8, 4) == 0xFFFFFFFF
    assert memory.read(ai + 0x1DC, 1) == memory.read(ai + 0x180, 4) == 0
    assert memory.read(ai + 0x1DE, 1) == ord("Z")
    assert memory.read_bytes(position, 16) == b"P" * 16
    assert memory.read_bytes(output, 41) == bytes(41)


def test_first_group_loop_observes_changed_count_after_actual_helper_effect():
    raw = RAW[:108] + (1).to_bytes(4, "little") + bytes(range(52)) * 2 + RAW[112:]
    seen = []

    def lower(target, args, data):
        assert target == 0x140D1ADF0 and data is None
        seen.append(args)
        # The count originally read1. Current source local is changed to2 by
        # the explicit child effect; the caller must read the second record.
        memory.write(reads[24][1][2], 4, 2)

    parts = setup(raw, lower=lower)
    memory, _, _, _, _, _, _, source, reads, _ = parts
    for pointer in (0x14324ABA0, 0x14324B1D0):
        memory.map_bytes(pointer, bytes(16))
    invoke(parts)
    assert len(seen) == 2 and source.remaining == 0


def test_derived_record_end_increment_uses_current_header_after_last_copy_store():
    record = bytes(range(52))
    raw = RAW[:188] + (1).to_bytes(4, "little") + record
    state = {}

    def write(memory, pointer, width, value):
        if pointer == state.get("last") and width == 4:
            memory.write(state["end"], 8, state["array"] + 52)

    parts = setup(raw, after_write=write)
    memory, ai, *_ = parts
    array = memory.allocate(156)
    state.update(last=array + 48, end=ai + 0x200, array=array)
    for offset, value in ((0x1F8, array), (0x200, array), (0x208, array + 156)):
        memory.write(ai + offset, 8, value)
    for pointer in (0x14324ABA0, 0x14324B1D0):
        memory.map_bytes(pointer, bytes(16))
    invoke(parts)
    assert memory.read_bytes(array, 52) == record
    assert memory.read(ai + 0x200, 8) == array + 104


def test_common_does_not_invent_status_check_after_position_child_returns():
    def effect(memory, target, args, answer):
        if target == 0x140C29890:
            memory.write(args[1] + 24, 8, 1)

    parts = setup(after_effect=effect)
    memory, _, output, _, position, _, _, source, _, _ = parts
    invoke(parts)
    assert source.position == 192 and memory.read_bytes(position, 14) == RAW[174:188]
    assert memory.read_bytes(output, 41) == bytes(41)
