"""Source-led whole-record grammar and actual leaf-table lookup controls."""

from __future__ import annotations

import hashlib

import pytest

from vantage.replay_localization_catalog_data import (
    ReplayCatalogData,
    ReplayCatalogEntry,
    ReplayCatalogRecord,
    ReplayLocalizationCatalogError,
    create_replay_localization_catalog_table,
    read_replay_localization_catalog,
)
from vantage.replay_localization_runtime import (
    ReplayLocalizationRuntime,
    ReplayLocalizationTargets,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_localization_catalog import (
    ReplayLocalizationCatalogProfile,
    bind_replay_player_localization_catalog,
)
from vantage.replay_task_rebuild import ReplayTaskRebuildCalls, ReplayTaskRebuildStorage


def test_all_five_escapes_decode_once_and_raw_occurrence_spans_remain_original():
    raw = b'\xef\xbb\xbf\t_Ab09 "a\\nb\\tc\\\\d\\\'e\\"f" // tail\r\n'
    data = read_replay_localization_catalog(raw)
    assert data.entries == (ReplayCatalogEntry(b"_Ab09", b"a\nb\tc\\d'e\"f"),)
    assert data.source_sha256 == hashlib.sha256(raw).hexdigest()
    (record,) = data.records
    assert (record.line_number, record.record_offset, record.key_offset) == (1, 3, 4)
    assert (record.value_offset, record.value_end) == (11, 27)
    assert record.comment_offset == 29 and record.record_end == len(raw)
    assert raw[record.value_offset : record.value_end] == b"a\\nb\\tc\\\\d\\'e\\\"f"


def test_duplicate_values_replace_case_sensitively_without_moving_the_first_key():
    raw = b'7 "first"\n07 "different"\nName "upper"\nname "lower"\n7 "last"'
    data = read_replay_localization_catalog(raw)
    assert data.entries == (
        ReplayCatalogEntry(b"7", b"last"),
        ReplayCatalogEntry(b"07", b"different"),
        ReplayCatalogEntry(b"Name", b"upper"),
        ReplayCatalogEntry(b"name", b"lower"),
    )
    assert [record.entry.key for record in data.records] == [b"7", b"07", b"Name", b"name", b"7"]
    assert [record.line_number for record in data.records] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("boundary", [b"\r\n", b"\r", b"\n", b"\0"])
def test_all_native_line_boundaries_preserve_absolute_spans_and_one_line_increment(boundary):
    first = b'A "one"' + boundary
    raw = first + b'B "two"'
    data = read_replay_localization_catalog(raw)
    assert [(r.line_number, r.record_offset, r.record_end) for r in data.records] == [
        (1, 0, len(first)),
        (2, len(first), len(raw)),
    ]


def test_blank_comment_bom_and_final_eof_lines_do_not_create_fake_entries():
    raw = b'\xef\xbb\xbf\r\n\t // opaque \\q \xff\r\n \t\nA ""\t// \\q\xff\0// final'
    data = read_replay_localization_catalog(raw)
    assert data.entries == (ReplayCatalogEntry(b"A", b""),)
    (record,) = data.records
    assert record.line_number == 4
    assert record.entry.text == b""
    assert record.comment_offset is not None
    assert raw[record.comment_offset : record.comment_offset + 2] == b"//"


@pytest.mark.parametrize("raw", [b"", b"\xef\xbb\xbf", b"\r\n\0", b" // comment", b"\t "])
def test_complete_empty_catalogs_retain_their_digest_without_inventing_records(raw):
    data = read_replay_localization_catalog(raw)
    assert data.entries == data.records == ()
    assert data.source_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "text",
    [
        "Caf\u00e9".encode(),
        "\u4e2d\u6587".encode(),
        "\U0001f600".encode(),
        b"\xff\x80",
        b"<tag x=1>text</tag>",
        b" a\tb ",
        b"\x01\x7f",
    ],
)
def test_value_bytes_and_tags_survive_without_unicode_replacement_or_validation_rewrites(text):
    data = read_replay_localization_catalog(b'K "' + text + b'"')
    assert data.entries == (ReplayCatalogEntry(b"K", text),)


def test_escaped_backslash_is_not_reinterpreted_as_another_escape():
    assert read_replay_localization_catalog(b'K "\\\\n"').entries == (
        ReplayCatalogEntry(b"K", b"\\n"),
    )


@pytest.mark.parametrize(
    "raw,code,offset",
    [
        (b'-1 "x"', "invalid_key", 0),
        (b'a-b "x"', "invalid_key", 1),
        (b'\xef\xbb\xbfA "x"', "invalid_key", 0),
        (b'\xff "x"', "invalid_key", 0),
        (b'A"x"', "invalid_key", 1),
        (b"A", "missing_open_quote", 1),
        (b'A\v"x"', "invalid_key", 1),
        (b"A x", "missing_open_quote", 2),
        (b'A "x', "missing_close_quote", 4),
        (b'A "x\\q"', "unknown_escape", 5),
        (b'A "x\\', "unknown_escape", 5),
        (b'A "x" / comment', "trailing_data", 6),
        (b'A "x" y', "trailing_data", 6),
        (b'A "x""', "trailing_data", 5),
        (b'A "x\r\ny"', "missing_close_quote", 4),
        (b'A "x\0y"', "missing_close_quote", 4),
    ],
)
def test_malformed_complete_records_report_the_original_byte_and_line(raw, code, offset):
    with pytest.raises(ReplayLocalizationCatalogError) as caught:
        read_replay_localization_catalog(b"// first\n" + raw)
    assert (caught.value.code, caught.value.offset, caught.value.line_number) == (
        code,
        9 + offset,
        2,
    )


def test_every_occurrence_is_validated_even_if_a_later_duplicate_would_replace_it():
    with pytest.raises(ReplayLocalizationCatalogError, match="unknown_escape"):
        read_replay_localization_catalog(b'A "old"\nA "\\q"\nA "new"\n')


def test_only_one_absolute_initial_bom_is_skipped():
    with pytest.raises(ReplayLocalizationCatalogError) as caught:
        read_replay_localization_catalog(b'\xef\xbb\xbf\xef\xbb\xbfA "x"')
    assert (caught.value.code, caught.value.offset, caught.value.line_number) == (
        "invalid_key",
        3,
        1,
    )


@pytest.mark.parametrize("raw", ["", bytearray(), None, memoryview(b"")])
def test_complete_input_requires_immutable_bytes(raw):
    with pytest.raises(ValueError, match="immutable"):
        read_replay_localization_catalog(raw)


def test_direct_data_and_record_invariants_cannot_discard_duplicate_or_order_provenance():
    data = read_replay_localization_catalog(b'A "old"\nB "two"\nA "new"')
    with pytest.raises(ValueError, match="source order"):
        ReplayCatalogData(data.entries, data.source_sha256, data.records[::-1])
    with pytest.raises(ValueError, match="first order and last values"):
        ReplayCatalogData(data.entries[::-1], data.source_sha256, data.records)
    with pytest.raises(ValueError, match="unique"):
        ReplayCatalogData(data.entries + data.entries, data.source_sha256)
    with pytest.raises(ValueError, match="SHA256"):
        ReplayCatalogData(data.entries, "F" * 64)
    with pytest.raises(ValueError, match="spans"):
        ReplayCatalogRecord(data.entries[0], 1, 0, 10, 0, 3, 3)
    with pytest.raises(ValueError, match="comment"):
        ReplayCatalogRecord(ReplayCatalogEntry(b"A", b"x"), 1, 0, 10, 0, 3, 4, 4)
    with pytest.raises(ValueError, match="offsets"):
        ReplayCatalogRecord(data.entries[0], True, 0, 10, 0, 3, 8)


@pytest.mark.parametrize(
    "key,text",
    [(b"", b"x"), (b"-1", b"x"), (b"a-b", b"x"), ("A", b"x"), (b"A", "x"), (b"A", b"x\0")],
)
def test_direct_entries_keep_the_native_cstring_key_and_value_domain(key, text):
    with pytest.raises(ValueError):
        ReplayCatalogEntry(key, text)


def source_catalog_services(raw, *, buckets=1):
    memory = ReplayMemory()
    data = read_replay_localization_catalog(raw)
    table = create_replay_localization_catalog_table(memory, data, bucket_count=buckets)
    targets = ReplayLocalizationTargets(0xCA0010, 0xCA0020, 0xCA0030, 0xCA0040, 0xCA0050)
    runtime = ReplayLocalizationRuntime(memory, targets, delegate=memory.runtime_calls())
    memory.map_bytes(0x14319A300, targets.comparison.to_bytes(8, "little"))
    services = runtime.calls()
    events, routes = [], {}

    def dispatch(target, args, payload):
        events.append((target, args))
        selected = routes.get(target, services)
        assert selected.call is not None
        return selected.call(target, args, payload)

    calls = ReplayTaskRebuildCalls(dispatch)
    catalog = bind_replay_player_localization_catalog(
        ReplayTaskRebuildStorage(table, memory.read, memory.write),
        calls,
        profile=ReplayLocalizationCatalogProfile(1 << 20, 1 << 20, 0, 0),
        imports=services,
    )
    routes.update(dict.fromkeys((0x14095F0B0, 0x142D6E4B3), catalog))
    return memory, data, table, calls, events


def lookup_catalog(memory, table, calls, key):
    pointer = memory.allocate(len(key) + 1)
    memory.write_bytes(pointer, key + b"\0")
    try:
        assert calls.call is not None
        return calls.call(0x14095F0B0, (table, pointer), None)
    finally:
        memory.free(pointer)


@pytest.mark.parametrize("buckets", [1, 2, 8])
def test_whole_records_flow_through_actual_leaf_and_current_import_comparison(buckets):
    raw = b'A "old"\n7 "Caf\xc3\xa9\\n<tag>"\n_ ""\nA "last"\n07 "seven"'
    memory, data, table, calls, events = source_catalog_services(raw, buckets=buckets)
    for entry in data.entries:
        result = lookup_catalog(memory, table, calls, entry.key)
        assert result and memory.read_bytes(result, len(entry.text) + 1) == entry.text + b"\0"
    assert lookup_catalog(memory, table, calls, b"a") == 0
    assert {0x14095F0B0, 0x142D6E4B3} <= {target for target, _ in events}
    with pytest.raises(ReplayMemoryError):
        memory.read(0x1442842E8, 8)


def test_empty_table_misses_without_reading_undefined_sentinel_or_compare_provider():
    memory, data, table, calls, events = source_catalog_services(b"// genuinely supplied empty\n")
    assert data.entries == () and lookup_catalog(memory, table, calls, b"Anything") == 0
    assert [target for target, _ in events] == [0x14095F0B0]
    with pytest.raises(ReplayMemoryError):
        memory.read(memory.read(table + 8, 8), 1)


def test_lookup_only_backing_leaves_unread_headers_padding_and_native_list_links_undefined():
    memory, _, table, _, _ = source_catalog_services(b'A "A"\nB "A"')
    buckets, sentinel = memory.read(table + 0x18, 8), memory.read(table + 8, 8)
    first, last = memory.read(buckets, 8), memory.read(buckets + 8, 8)
    assert memory.read(last + 8, 8) == first and memory.read(first + 8, 8) == sentinel
    pointers = [memory.read(node + offset, 8) for node in (first, last) for offset in (0x10, 0x18)]
    assert len(set(pointers)) == 4
    for address, width in [
        (table, 8),
        (table + 0x10, 8),
        (table + 0x20, 8),
        (table + 0x28, 8),
        (first, 8),
        (last, 8),
        (sentinel, 8),
        (0x1442842E8, 8),
        (0x143199288, 8),
    ]:
        with pytest.raises(ReplayMemoryError):
            memory.read(address, width)


@pytest.mark.parametrize("buckets", [0, -1, True, 1.0, 3, 1 << 64])
def test_bad_bucket_counts_refuse_before_storage_effects(buckets):
    memory = ReplayMemory()
    data = read_replay_localization_catalog(b'A "x"')
    with pytest.raises(ValueError, match="power-of-two"):
        create_replay_localization_catalog_table(memory, data, bucket_count=buckets)
    assert memory.mapped_bytes == 0


def test_later_storage_failure_retains_prior_allocations_without_publishing_global_state():
    memory = ReplayMemory(max_bytes=0x38 + 0x20)
    data = read_replay_localization_catalog(b'A "x"')
    with pytest.raises(MemoryError):
        create_replay_localization_catalog_table(memory, data, bucket_count=1)
    assert memory.mapped_bytes == 0x38 + 0x20
    with pytest.raises(ReplayMemoryError):
        memory.read(0x1442842E8, 8)
