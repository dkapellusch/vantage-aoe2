"""Authored selected-record/data-layout controls; no native asset is selected."""

from __future__ import annotations

import hashlib

import pytest

from vantage.replay_localization_data import (
    ReplayLocalizationData,
    ReplayLocalizationEntry,
    ReplayLocalizationRecord,
    create_replay_localization_context,
    read_replay_localization_ascii_subset,
)
from vantage.replay_localization_runtime import (
    ReplayLocalizationRuntime,
    ReplayLocalizationTargets,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_construction_support import ReplayPlayerSupportFloatingCalls
from vantage.replay_player_derived_construction import _DerivedConstruction
from vantage.replay_player_localization_catalog import (
    ReplayLocalizationCatalogProfile,
    bind_replay_player_localization_catalog,
)
from vantage.replay_player_research_rows import bind_replay_player_research_rows
from vantage.replay_player_research_strings import (
    ReplayPlayerResearchStringsProfile,
    ReplayPlayerResearchStringsScratch,
    bind_replay_player_research_strings,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

GLOBAL = 0x1442842E8
TARGETS = ReplayLocalizationTargets(0xC00010, 0xC00020, 0xC00030, 0xC00040, 0xC00050)


def runtime_for(memory):
    return ReplayLocalizationRuntime(memory, TARGETS, delegate=memory.runtime_calls())


def build(raw=b'1 "One"\n5 "Five"\n2 ""\n', keys=(1, 5, 2), buckets=4):
    memory = ReplayMemory()
    runtime = runtime_for(memory)
    data = read_replay_localization_ascii_subset(raw, keys=keys)
    context = create_replay_localization_context(
        memory,
        data,
        runtime=runtime,
        bucket_count=buckets,
    )
    return memory, runtime, data, context


def table_parts(memory, manager):
    row = memory.read(manager + 0x70, 8)
    table = memory.read(row, 8)
    return row, table, memory.read(table + 8, 8), memory.read(table + 0x18, 8)


def test_selected_source_offsets_digest_and_last_duplicate_value_are_exact():
    raw = b'junk\r\n7 "Old"\n5\t"Five"\r7 "New"\r\n'
    data = read_replay_localization_ascii_subset(raw, keys=(5, 7))
    assert data.entries == (
        ReplayLocalizationEntry(b"5", b"Five"),
        ReplayLocalizationEntry(b"7", b"New"),
    )
    assert data.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert [
        (
            record.entry.key,
            record.entry.text,
            record.line_number,
            record.record_offset,
            record.record_end,
            record.key_offset,
            record.text_offset,
        )
        for record in data.records
    ] == [
        (b"7", b"Old", 2, 6, 14, 6, 9),
        (b"5", b"Five", 3, 14, 23, 14, 17),
        (b"7", b"New", 4, 23, 32, 23, 26),
    ]
    for record in data.records:
        assert (
            raw[record.key_offset : record.key_offset + len(record.entry.key)] == record.entry.key
        )
        assert raw[record.text_offset : record.text_offset + len(record.entry.text)] == (
            record.entry.text
        )


def test_authored_exact_paphos_records_keep_real_ids_text_and_lexical_offsets():
    # Exact selected raw records from the source-pinned asset's lines766/767;
    # this authored fragment supplies no automatic file/language selection.
    raw = b'407089 "Archaic Age"\r\n407090 "Civic Age"\r\n'
    data = read_replay_localization_ascii_subset(raw, keys=(407089, 407090))
    assert data.entries == (
        ReplayLocalizationEntry(b"407089", b"Archaic Age"),
        ReplayLocalizationEntry(b"407090", b"Civic Age"),
    )
    assert [
        (record.record_offset, record.record_end, record.key_offset, record.text_offset)
        for record in data.records
    ] == [(0, 22, 0, 8), (22, 42, 22, 30)]
    assert data.source_sha256 == hashlib.sha256(raw).hexdigest()


def test_plain_text_preserves_internal_and_edge_spaces_and_printable_punctuation():
    data = read_replay_localization_ascii_subset(b'\t 0\t " !#[]~ " \t\r\n', keys=(0,))
    assert data.entries == (ReplayLocalizationEntry(b"0", b" !#[]~ "),)
    record = data.records[0]
    assert (record.record_offset, record.record_end, record.key_offset, record.text_offset) == (
        0,
        18,
        2,
        6,
    )


def test_zero_maximum_signed32_and_empty_text_are_admitted_without_invented_defaults():
    data = read_replay_localization_ascii_subset(b'2147483647 "Limit"\n0 ""', keys=(0, 0x7FFFFFFF))
    assert data.entries == (
        ReplayLocalizationEntry(b"0", b""),
        ReplayLocalizationEntry(b"2147483647", b"Limit"),
    )
    assert data.records[-1].record_end == 23


def test_unselected_records_are_explicitly_not_validated_or_unicode_decoded():
    raw = b'\xffnot a selected record\0\n07 "separate raw key"\n7x invalid\n7 "Chosen"\n'
    data = read_replay_localization_ascii_subset(raw, keys=(7,))
    assert data.entries == (ReplayLocalizationEntry(b"7", b"Chosen"),)
    assert len(data.records) == 1
    assert data.source_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "bad",
    [
        b"7\n",
        b'7"Text"\n',
        b"7 \n",
        b"7 Text\n",
        b'7 "\n',
        b'7 "Text" junk\n',
        b'7 "Text" // comment\n',
        b'7 "a\\n"\n',
        b'7 "a\\t"\n',
        b'7 "a\\b"\n',
        b'7 "a\tb"\n',
        b'7 "a\0b"\n',
        b'7 "\x7f"\n',
        b'7 "\xc3\xa9"\n',
        b'7\v"Text"\n',
        b'7 "a"b"\n',
    ],
)
def test_any_unadmitted_selected_occurrence_refuses_even_between_valid_duplicates(bad):
    with pytest.raises(ValueError, match="unadmitted selected"):
        read_replay_localization_ascii_subset(b'7 "Earlier"\n' + bad + b'7 "Later"\n', keys=(7,))


@pytest.mark.parametrize("raw", [b"", b'8 "Other"\n', b'07 "Noncanonical"\n'])
def test_missing_selected_key_refuses_instead_of_synthesizing_empty_text(raw):
    with pytest.raises(ValueError, match="every selected"):
        read_replay_localization_ascii_subset(raw, keys=(7,))


@pytest.mark.parametrize(
    "keys",
    [
        (),
        [],
        (True,),
        (-1,),
        (0x80000000,),
        (7, 7),
        ("7",),
        (7.0,),
    ],
)
def test_selected_key_input_requires_nonempty_unique_actual_signed32_nonnegative_integers(keys):
    with pytest.raises(ValueError):
        read_replay_localization_ascii_subset(b'7 "Seven"\n', keys=keys)


@pytest.mark.parametrize("raw", [bytearray(b'7 "Seven"'), '7 "Seven"', None])
def test_raw_asset_requires_immutable_explicit_bytes(raw):
    with pytest.raises(ValueError):
        read_replay_localization_ascii_subset(raw, keys=(7,))


@pytest.mark.parametrize("key", [b"", b"07", b"-1", b"2147483648", b"x", "7", bytearray(b"7")])
def test_direct_entry_keys_cannot_bypass_canonical_decimal_domain(key):
    with pytest.raises(ValueError, match="canonical"):
        ReplayLocalizationEntry(key, b"Text")


@pytest.mark.parametrize("text", [b'"', b"\\", b"\0", b"\n", b"\x80", "Text", bytearray(b"Text")])
def test_direct_entry_text_cannot_bypass_plain_ascii_domain(text):
    with pytest.raises(ValueError, match="printable ASCII"):
        ReplayLocalizationEntry(b"7", text)


def test_direct_data_requires_positive_unique_entries_and_a_lowercase_digest():
    entry = ReplayLocalizationEntry(b"7", b"Text")
    for entries in ((), [], (entry, entry)):
        with pytest.raises(ValueError):
            ReplayLocalizationData(entries, "0" * 64)
    for digest in ("bad", "A" * 64, None):
        with pytest.raises(ValueError, match="SHA256"):
            ReplayLocalizationData((entry,), digest)


def test_supplied_record_metadata_must_fit_be_ordered_and_match_last_values():
    data = read_replay_localization_ascii_subset(b'7 "Old"\n7 "New"\n', keys=(7,))
    with pytest.raises(ValueError, match="last selected"):
        ReplayLocalizationData(
            (ReplayLocalizationEntry(b"7", b"Old"),), data.source_sha256, data.records
        )
    with pytest.raises(ValueError, match="source order"):
        ReplayLocalizationData(data.entries, data.source_sha256, data.records[::-1])
    with pytest.raises(ValueError, match="spans"):
        ReplayLocalizationRecord(data.entries[0], 1, 0, 4, 0, 3)
    with pytest.raises(ValueError, match="offsets"):
        ReplayLocalizationRecord(data.entries[0], 1, -1, 10, 0, 3)


def test_sparse_source_table_has_literal_collision_boundaries_backlinks_and_cstrings():
    memory, _, _, context = build()
    manager = context.subject
    row, table, sentinel, buckets = table_parts(memory, manager)
    assert memory.read(GLOBAL, 8) == manager
    assert context.read(manager + 0x78, 8) == row + 16
    assert memory.read(table + 0x30, 8) == 3
    # Independent low-two-bit literals: hash('1')=177556, hash('5')=177552,
    # hash('2')=177559. Therefore '1'/'5' collide in bucket0 and '2' uses3.
    first = memory.read(buckets, 8)
    last = memory.read(buckets + 8, 8)
    third = memory.read(buckets + 3 * 16, 8)
    assert first != last and third not in (first, last, sentinel)
    assert memory.read(last + 8, 8) == first
    assert memory.read(first + 8, 8) == sentinel
    assert memory.read(third + 8, 8) == sentinel
    assert memory.read(buckets + 3 * 16 + 8, 8) == third
    for index in (1, 2):
        assert memory.read(buckets + index * 16, 8) == sentinel
        assert memory.read(buckets + index * 16 + 8, 8) == sentinel
    for node, key, text in (
        (first, b"1\0", b"One\0"),
        (last, b"5\0", b"Five\0"),
        (third, b"2\0", b"\0"),
    ):
        assert memory.read_bytes(memory.read(node + 0x10, 8), len(key)) == key
        assert memory.read_bytes(memory.read(node + 0x18, 8), len(text)) == text
    assert memory.read(manager + 0x239, 1) == 1
    assert memory.read(manager + 0x104, 4) == 0


def test_unread_fields_later_layers_static_defaults_and_imports_remain_undefined():
    memory, _, _, context = build()
    manager = context.subject
    row, table, sentinel, buckets = table_parts(memory, manager)
    node = memory.read(buckets, 8)
    for address, width in (
        (manager, 8),
        (manager + 0x80, 8),
        (manager + 0x88, 8),
        (manager + 0x90, 8),
        (manager + 0xA0, 8),
        (manager + 0xA8, 8),
        (manager + 0xB8, 8),
        (manager + 0x1C0, 8),
        (row + 8, 8),
        (table, 8),
        (table + 0x10, 8),
        (table + 0x20, 8),
        (table + 0x28, 8),
        (sentinel, 1),
        (node, 8),
        (0x143676DC8, 1),
        (0x14428BB30, 1),
        (0x143199CA0, 8),
        (0x14319A300, 8),
        (0x143199288, 8),
        (0x143199280, 8),
        (0x143199278, 8),
    ):
        with pytest.raises(ReplayMemoryError):
            memory.read(address, width)


def test_equal_key_and_text_bytes_use_separate_persistent_owned_copies():
    memory, _, data, context = build(b'1 "1"\n2 "1"\n', (1, 2), buckets=1)
    _, _, sentinel, buckets = table_parts(memory, context.subject)
    first, last = memory.read(buckets, 8), memory.read(buckets + 8, 8)
    assert first != last and memory.read(first + 8, 8) == sentinel
    key1, text1 = memory.read(first + 0x10, 8), memory.read(first + 0x18, 8)
    key2, text2 = memory.read(last + 0x10, 8), memory.read(last + 0x18, 8)
    assert len({key1, text1, key2, text2}) == 4
    memory.write_bytes(text1, b"X\0")
    assert memory.read_bytes(key1, 2) == b"1\0"
    assert memory.read_bytes(text2, 2) == b"1\0"
    assert data.entries[0].text == data.entries[1].text == b"1"


def test_builder_registers_real_zero_count_mutex_and_services_need_explicit_current_slots():
    memory, runtime, _, context = build()
    slots = (
        (0x143199CA0, TARGETS.conversion),
        (0x14319A300, TARGETS.comparison),
        (0x143199288, TARGETS.lock),
        (0x143199280, TARGETS.unlock),
        (0x143199278, TARGETS.error),
    )
    for slot, target in slots:
        memory.map_bytes(slot, target.to_bytes(8, "little"))
    calls = runtime.calls()
    assert calls.call is not None
    mutex = context.subject + 0xB8
    assert calls.call(memory.read(0x143199288, 8), (mutex,), None) == 0
    assert memory.read(mutex + 0x4C, 4) == 1
    assert calls.call(memory.read(0x143199280, 8), (mutex,), None) == 0
    assert memory.read(mutex + 0x4C, 4) == 0
    _, _, _, buckets = table_parts(memory, context.subject)
    node = memory.read(buckets, 8)
    key = memory.read(node + 0x10, 8)
    output = memory.allocate(16)
    assert calls.call(memory.read(0x143199CA0, 8), (1, output, 16, 10), None) == 0
    assert memory.read_bytes(output, 2) == b"1\0"
    assert calls.call(memory.read(0x14319A300, 8), (key, output), None) == 0


@pytest.mark.parametrize("bucket_count", [0, -1, 3, True, 1.0, 1 << 64])
def test_bucket_domain_refuses_before_any_allocations(bucket_count):
    memory = ReplayMemory()
    runtime = runtime_for(memory)
    data = read_replay_localization_ascii_subset(b'1 "One"\n', keys=(1,))
    with pytest.raises(ValueError, match="power-of-two"):
        create_replay_localization_context(memory, data, runtime=runtime, bucket_count=bucket_count)
    assert memory.mapped_bytes == 0


def test_runtime_from_other_memory_refuses_before_either_memory_changes():
    memory, other = ReplayMemory(), ReplayMemory()
    data = read_replay_localization_ascii_subset(b'1 "One"\n', keys=(1,))
    with pytest.raises(ValueError, match="same owned memory"):
        create_replay_localization_context(memory, data, runtime=runtime_for(other), bucket_count=1)
    assert memory.mapped_bytes == other.mapped_bytes == 0


def test_existing_global_is_not_overwritten_when_fresh_publication_fails():
    memory = ReplayMemory()
    memory.map_bytes(GLOBAL, (0x12345678).to_bytes(8, "little"))
    data = read_replay_localization_ascii_subset(b'1 "One"\n', keys=(1,))
    with pytest.raises(ReplayMemoryError, match="overlap"):
        create_replay_localization_context(
            memory,
            data,
            runtime=runtime_for(memory),
            bucket_count=1,
        )
    assert memory.read(GLOBAL, 8) == 0x12345678


def source_localization_services(raw, keys):
    """Authored explicit profile; every reached source helper is real."""
    memory = ReplayMemory()
    terminal = ReplayLocalizationRuntime(
        memory,
        TARGETS,
        delegate=memory.runtime_calls(strlen_target=0xD00100),
    )
    data = read_replay_localization_ascii_subset(raw, keys=keys)
    context = create_replay_localization_context(
        memory,
        data,
        runtime=terminal,
        bucket_count=1,
    )
    for slot, target in (
        (0x143199CA0, TARGETS.conversion),
        (0x14319A300, TARGETS.comparison),
        (0x143199288, TARGETS.lock),
        (0x143199280, TARGETS.unlock),
        (0x143199278, TARGETS.error),
        (0x14319A290, 0xD00100),
        (0x143199930, 0x142D6E3DB),
        (0x143199DD0, 0x142D6BAB4),
    ):
        memory.map_bytes(slot, target.to_bytes(8, "little"))
    services = terminal.calls()
    events, routes = [], {}

    def dispatch(target, args, payload):
        events.append((target, args))
        selected = routes.get(target, services)
        assert selected.call is not None
        return selected.call(target, args, payload)

    calls = ReplayTaskRebuildCalls(dispatch)
    strings = bind_replay_player_research_strings(
        context,
        calls,
        bind_local=memory.bind_local,
        scratch=ReplayPlayerResearchStringsScratch(b"\xa5" * 16, b"\xb6" * 16, b"\xc7" * 8),
        profile=ReplayPlayerResearchStringsProfile(2),
        imports=services,
    )
    catalog = bind_replay_player_localization_catalog(
        context,
        calls,
        profile=ReplayLocalizationCatalogProfile(64, 8, 4, 0),
        imports=services,
    )
    support = bind_replay_unit_constructor_support(
        context,
        calls,
        bind_local=memory.bind_local,
        imports=services,
    )
    rows = bind_replay_player_research_rows(
        context,
        calls,
        bind_local=memory.bind_local,
        error_seed=b"\xd8" * 8,
        imports=services,
    )
    for targets, binding in (
        ((0x140803E30, 0x140803EA0, 0x140A15BF0, 0x140967520, 0x140963BE0, 0x140964A30), strings),
        ((0x14095F0B0, 0x140964B80, 0x142D6AA5B, 0x142D6AA61, 0x142D6AA67, 0x142D6E4B3), catalog),
        ((0x142D6E44D, 0x140A13780, 0x140A1A5E0, 0x142D6E3B1, 0x142D6C270, 0x142D6C268), support),
        ((0x140F92850, 0x140F92070, 0x1402A8790, 0x140F6BBF0), rows),
    ):
        routes.update(dict.fromkeys(targets, binding))
    return memory, context, calls, events


@pytest.mark.parametrize(
    "identifier,expected",
    [
        (407089, b"Archaic Age"),
        (407090, b"Civic Age"),
    ],
)
def test_plain_records_flow_through_real_lookup_and_string_assignment(identifier, expected):
    memory, context, calls, events = source_localization_services(
        b'407089 "Archaic Age"\r\n407090 "Civic Age"\r\n',
        (407089, 407090),
    )
    assert calls.call is not None
    pointer = calls.call(0x140803E30, (identifier,), None)
    assert memory.read_bytes(pointer, len(expected) + 1) == expected + b"\0"
    destination = memory.allocate(24)
    memory.write(destination, 8, 0)  # Capacity/length deliberately undefined.
    assert calls.call(0x140A15BF0, (destination, pointer), None) == destination
    result = memory.read(destination, 8)
    assert memory.read_bytes(result, len(expected) + 1) == expected + b"\0"
    assert memory.read(destination + 8, 8) == len(expected)
    assert memory.read(destination + 16, 8) == 32
    assert result != pointer
    assert memory.read(context.subject + 0x104, 4) == 0
    assert {
        0x140803EA0,
        0x140964A30,
        0x140964B80,
        0x14095F0B0,
        0x142D6AA5B,
        0x142D6AA61,
        0x142D6E4B3,
        0x140A13780,
        0x140A1A5E0,
    } <= {target for target, _ in events}
    with pytest.raises(ReplayMemoryError):
        memory.read(context.subject + 0xA0, 8)


def test_sparse_catalog_miss_releases_first_lock_then_requires_next_real_mutex():
    memory, context, calls, events = source_localization_services(b'7 "Seven"\n', (7,))
    assert calls.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unregistered owned localization mutex"):
        calls.call(0x140803E30, (8,), None)
    assert memory.read(context.subject + 0x104, 4) == 0
    assert (0x142D6AA61, (context.subject + 0xB8,)) in events
    assert events[-1] == (0x142D6AA5B, (context.subject + 0x158,))
    assert not any(target == 0x140964460 for target, _ in events)


def test_derived_final_records_use_real_row_copy_catalog_assignment_and_release():
    memory, context, calls, events = source_localization_services(
        b'407089 "Archaic Age"\r\n407090 "Civic Age"\r\n',
        (407089, 407090),
    )
    player, civilization = memory.allocate(0x12FD), memory.allocate(0x150)
    master, research = memory.allocate(8), memory.allocate(2 * 0x98)
    source = memory.allocate(40)
    for index, (name, icon) in enumerate(((407089, 33), (407090, 44))):
        row = b"".join(
            value.to_bytes(4, "little", signed=True) for value in (index, name, icon, -2, -2)
        )
        memory.write_bytes(source + index * 20, row)
        record = research + index * 0x98
        memory.write(record + 0x10, 8, 0)
        memory.write(record + 0x18, 8, 0)
        memory.write(record + 0x6C, 2, 0xFFFF)
    for offset, value in ((0x138, source), (0x140, source + 40), (0x148, source + 40)):
        memory.write(civilization + offset, 8, value)
    memory.write(player + 0x6A8, 8, civilization)
    memory.write(player + 0x6D0, 8, master)
    memory.write(master, 8, research)
    # Explicit pre-typed-field version isolates this already source-ported phase.
    memory.map_bytes(0x1440A0D94, (0x44CCCC).to_bytes(4, "little"))
    with memory.bind_local(memoryview(bytearray(b"\xe9" * 0xD8))) as frame:
        state = _DerivedConstruction(
            context,
            calls,
            ReplayUnitAIMapAtomics(None, None),
            ReplayPlayerSupportFloatingCalls(None),
            player,
            0,
            0,
            frame,
        )
        state.final_records()
        copied = memory.read(frame + 0xC0, 8)
        assert memory.read(frame + 0xC8, 8) == copied + 40
        assert memory.read(frame + 0xD0, 8) == copied + 40
    for index, expected in enumerate((b"Archaic Age", b"Civic Age")):
        record = research + index * 0x98
        pointer = memory.read(record + 0x10, 8)
        assert memory.read_bytes(pointer, len(expected) + 1) == expected + b"\0"
        assert memory.read(record + 0x18, 8) == len(expected)
        assert memory.read(record + 0x20, 8) == 32
        assert memory.read(record + 0x6C, 2) == (33, 44)[index]
    assert memory.read_bytes(source, 4) == b"\0" * 4
    assert memory.read(context.subject + 0x104, 4) == 0
    with pytest.raises(ReplayMemoryError):
        memory.read(copied, 1)
    assert events[-2:] == [(0x1402A8790, (copied, 40)), (0x142D6BAB4, (copied, 40))]
