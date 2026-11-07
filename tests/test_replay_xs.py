"""Native XS current-profile bytes, framing and explicit unsupported branches."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from functools import cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_xs import SavedXS, UnsupportedSavedXS, read_xs

FIXTURE = Path(__file__).parent / "fixtures" / "native_saved_xs_54800.json.gz"


@cache
def _fixture():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _raw() -> bytes:
    return bytes.fromhex(_fixture()["xs_raw_hex"])


@cache
def _native() -> SavedXS:
    return read_xs(SaveReader(_raw()))


def _section_at(saved, name: str) -> int:
    at = saved.offset
    for label, raw in saved.sections.items():
        if label == name:
            return at
        at += len(raw)
    raise AssertionError(name)


def _variable_raw(variable) -> bytes:
    return (
        struct.pack(
            "<iIBi", variable.symbol_id, variable.type_bits, variable.modifiers, len(variable.data)
        )
        + variable.data
    )


def test_complete_native_xs_profile_and_every_component_raw_span() -> None:
    raw = _raw()
    expected = _fixture()["xs_summary"]
    reader = SaveReader(b"prefix" + raw + b"WorldPlayer tail", len(b"prefix"))
    saved = read_xs(reader)
    assert reader.data[reader.pos :] == b"WorldPlayer tail"
    assert len(raw) == expected["raw_bytes"] == 262595
    assert hashlib.sha256(raw).hexdigest() == expected["raw_sha256"]
    assert saved.raw == raw == b"".join(saved.sections.values())
    assert (saved.version, saved.player_id, saved.name_bytes) == (3, 0, b"Expert")
    assert saved.syscalls.static_words == (0, 0, 0, 2, 0, 2, 1, 1, 2)
    assert saved.syscalls.version == 2
    assert len(saved.syscalls.entries) == 274
    assert sum(len(e.parameters) for e in saved.syscalls.entries) == 485
    assert saved.syscalls.flags == (1, 1, 1)
    for entry in saved.syscalls.entries:
        fields = entry.fields
        assert entry.raw == (
            struct.pack(
                "<IIBBIi",
                fields[0],
                fields[4],
                fields[0x28],
                fields[0x29],
                fields[0x2C],
                len(entry.parameters),
            )
            + b"".join(v.raw for v in entry.parameters)
        )
        for variable in entry.parameters:
            assert variable.raw == _variable_raw(variable)
    assert saved.syscalls.raw == (
        struct.pack("<I9Ii", 2, *saved.syscalls.static_words, len(saved.syscalls.entries))
        + b"".join(e.raw for e in saved.syscalls.entries)
        + saved.syscalls.symbols.raw
        + bytes(saved.syscalls.flags)
    )
    for table in (saved.syscalls.symbols, saved.source.symbols):
        assert (
            table.hash_size,
            table.number_symbols,
            table.case_sensitive,
            table.invalid_value_bits,
            table.invalid_type,
        ) == (113, 1583, 1, 0xFFFFFFFF, 255)
        # This hash is also independently validated by the read-only native
        # symbol-table probe, outside the shipping XS reader.
        assert hashlib.sha256(table.raw).hexdigest() == (
            "b0014488cac59db4a1aedac51b6a6aeebbe36a03af912706f2f90fb0d80cfbe9"
        )
        symbols = [entry for bucket in table.buckets for entry in bucket]
        assert {entry.symbol_id for entry in symbols} == set(range(1583))
        buckets = []
        for bucket in table.buckets:
            for entry in bucket:
                assert entry.name_bytes.endswith(b"\0")
                assert entry.raw == (
                    struct.pack("<i", len(entry.name_bytes) - 1)
                    + entry.name_bytes
                    + struct.pack("<BIi", entry.type_tag, entry.value_bits, entry.symbol_id)
                )
            buckets.append(struct.pack("<i", len(bucket)) + b"".join(e.raw for e in bucket))
        assert table.raw == struct.pack("<iiBIB", 113, 1583, 1, 0xFFFFFFFF, 255) + b"".join(buckets)
    assert saved.source.version == 0
    assert [f.filename_bytes for f in saved.source.files] == [
        b"Constants.xs\0",
        b"ailib/GoalArrayOps.xs\0",
        b"ailib/Geometry.xs\0",
    ]
    assert [len(f.source_bytes) for f in saved.source.files] == [61370, 2788, 5706]
    assert [len(f.source_line_offsets) for f in saved.source.files] == [1392, 92, 171]
    for file in saved.source.files:
        assert file.raw == (
            struct.pack("<Ii", file.file_id, len(file.filename_bytes) - 1)
            + file.filename_bytes
            + struct.pack("<i", len(file.source_bytes) - 1)
            + file.source_bytes
            + struct.pack("<i", len(file.source_line_offsets))
            + struct.pack(f"<{len(file.source_line_offsets)}I", *file.source_line_offsets)
        )
    assert len(saved.source.code) == 3835
    assert hashlib.sha256(saved.source.code).hexdigest() == expected["code_sha256"]
    assert saved.source.raw == (
        struct.pack("<Ii", 0, 3)
        + b"".join(f.raw for f in saved.source.files)
        + saved.source.symbols.raw
        + struct.pack("<i", len(saved.source.code))
        + saved.source.code
    )
    assert saved.data_flags == b"\1" and len(saved.data_slots) == 1
    data = saved.data_slots[0]
    assert data is not None
    assert data.version == 4 and data.name_bytes == b"Expert"
    assert data.raw == b"".join(data.sections.values())
    assert (data.rules.version, data.rules.entry_version, data.rules.group_entry_version) == (
        0,
        1,
        0,
    )
    assert data.rules.counts == (0, 0, 0)
    assert len(data.rules.raw) == 28
    assert len(data.functions) == 6
    assert sum(len(f.variables) for f in data.functions) == 66
    assert len(data.variables) == len(data.stack_words) == 1182
    assert len(data.heap) == 18928
    assert hashlib.sha256(data.heap).hexdigest() == expected["heap_sha256"]
    assert data.exported_variables == ()
    assert set(data.empty_counts.values()) == {0}
    assert data.has_output == 0 and data.array_counts == (0,) * 6
    for function in data.functions:
        fields = function.fields
        assert function.raw == (
            struct.pack(
                "<4IBIBi",
                *(fields[i] for i in (0, 4, 8, 0xC)),
                fields[0x29],
                fields[0x10],
                fields[0x2A],
                len(function.variables),
            )
            + b"".join(v.raw for v in function.variables)
            + bytes([fields[0x28]])
        )
        for variable in function.variables:
            assert variable.raw == _variable_raw(variable)
    for variable in data.variables:
        assert variable.raw == _variable_raw(variable)
    assert len(data.user_heap) == 10
    assert [v.data for v in data.user_heap] == [
        b"<BLUE>\0",
        b"<RED>\0",
        b"<GREEN>\0",
        b"<YELLOW>\0",
        b"<AQUA>\0",
        b"<PURPLE>\0",
        b"<GRAY>\0",
        b"<ORANGE>\0",
        b"<WHITE>\0",
        b"<BLACK>\0",
    ]
    for value in data.user_heap:
        assert value.type_bits == 16 and value.reference_count == 1
        assert (
            value.raw
            == struct.pack(
                "<IIiI",
                value.type_bits,
                value.allocation_size,
                len(value.data),
                value.reference_count,
            )
            + value.data
        )
    assert data.fields == {int(k): v for k, v in expected["data_fields"].items()}
    assert saved.fields == {int(k): v for k, v in expected["runtime_fields"].items()}


def test_section_boundary_truncations_restore_the_entire_runtime() -> None:
    saved = _native()
    data = saved.data_slots[0]
    assert data is not None
    boundaries = {0, 1, saved.end_offset}
    for record in (saved, data):
        pos = record.offset
        for raw in record.sections.values():
            boundaries.update((pos, pos + len(raw)))
            pos += len(raw)
    for record in (
        saved.syscalls.symbols,
        saved.source.symbols,
        *saved.source.files,
        *data.functions,
        data.user_heap[0],
        data.user_heap[-1],
    ):
        boundaries.update((record.offset, record.end_offset))
    for boundary in sorted(boundaries):
        for cut in (boundary - 1, boundary, boundary + 1):
            if not 0 <= cut < saved.end_offset:
                continue
            reader = SaveReader(b"prefix" + _raw()[:cut], len(b"prefix"))
            with pytest.raises(SaveDecodeError):
                read_xs(reader)
            assert reader.pos == len(b"prefix")


@pytest.mark.parametrize("what", ["runtime", "syscalls", "static", "data", "rules"])
def test_unverified_component_versions_fail_without_advancing(what: str) -> None:
    saved = _native()
    data = saved.data_slots[0]
    assert data is not None
    at = {
        "runtime": 0,
        "syscalls": saved.syscalls.offset,
        "static": saved.syscalls.offset + 4 + 8 * 4,
        "data": data.offset,
        "rules": _section_at(data, "rules"),
    }[what]
    raw = bytearray(_raw())
    struct.pack_into("<I", raw, at, 99)
    reader = SaveReader(b"prefix" + bytes(raw), len(b"prefix"))
    with pytest.raises(UnsupportedSavedXS, match="unsupported"):
        read_xs(reader)
    assert reader.pos == len(b"prefix")


@pytest.mark.parametrize(
    "what",
    [
        "rules",
        "sorted_rules",
        "rule_groups",
        "classes",
        "events",
        "call_stack",
        "breakpoints",
        "output",
        *range(6),
    ],
)
def test_nonempty_unverified_factories_are_never_guessed_or_skipped(what) -> None:
    data = _native().data_slots[0]
    assert data is not None
    interpreter = _section_at(data, "interpreter")
    if isinstance(what, int):
        at = _section_at(data, "array_containers") + what * 4
    else:
        at = {
            "rules": _section_at(data, "rules") + 12,
            "sorted_rules": _section_at(data, "rules") + 16,
            "rule_groups": _section_at(data, "rules") + 20,
            "classes": _section_at(data, "empty_factories"),
            "events": _section_at(data, "empty_factories") + 4,
            "call_stack": interpreter + 8,
            "breakpoints": interpreter + 32,
            "output": interpreter + len(data.sections["interpreter"]) - 1,
        }[what]
    raw = bytearray(_raw())
    if what == "output":
        raw[at] = 1
    else:
        struct.pack_into("<i", raw, at, 1)
    reader = SaveReader(bytes(raw) + _raw())
    with pytest.raises(UnsupportedSavedXS, match="unsupported"):
        read_xs(reader)
    assert reader.pos == 0


@pytest.mark.parametrize("duplicate", [False, True])
def test_symbol_ids_follow_native_slot_bounds_and_uniqueness(duplicate: bool) -> None:
    table = _native().syscalls.symbols
    symbols = [entry for bucket in table.buckets for entry in bucket]
    raw = bytearray(_raw())
    target = symbols[1]
    value = symbols[0].symbol_id if duplicate else table.number_symbols
    struct.pack_into("<i", raw, target.end_offset - 4, value)
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError, match="invalid or duplicate XS symbol ID"):
        read_xs(reader)
    assert reader.pos == 0


def test_symbol_slot_capacity_may_exceed_the_number_of_saved_entries() -> None:
    raw = bytearray(_raw())
    table = _native().syscalls.symbols
    struct.pack_into("<i", raw, table.offset + 4, table.number_symbols + 1)
    saved = read_xs(SaveReader(bytes(raw)))
    assert saved.syscalls.symbols.number_symbols == 1584
    assert sum(map(len, saved.syscalls.symbols.buckets)) == 1583


def test_data_slot_presence_uses_native_equality_to_one() -> None:
    saved = _native()
    data = saved.data_slots[0]
    assert data is not None
    raw = _raw()[: data.offset - 1] + b"\x02" + _raw()[data.end_offset :]
    result = read_xs(SaveReader(raw))
    assert result.data_flags == b"\x02"
    assert result.data_slots == (None,)
    assert result.raw == raw


def test_user_heap_allocation_metadata_does_not_replace_payload_length() -> None:
    data = _native().data_slots[0]
    assert data is not None
    raw = bytearray(_raw())
    struct.pack_into("<I", raw, data.user_heap[0].offset + 4, 0x7FFFFFFF)
    saved = read_xs(SaveReader(bytes(raw))).data_slots[0]
    assert saved is not None
    assert saved.user_heap[0].allocation_size == 0x7FFFFFFF
    assert saved.user_heap[0].data == b"<BLUE>\0"


def test_constructed_sparse_symbols_variables_and_raw_flags() -> None:
    def de(value):
        return struct.pack("<HH", 0xA60, len(value)) + value

    def variable(symbol, kind, modifiers, data):
        return struct.pack("<iIBi", symbol, kind, modifiers, len(data)) + data

    symbol = struct.pack("<i", 2) + b"\xffx\0" + struct.pack("<BIi", 255, 0x7FC01234, 4)
    symbols = struct.pack("<iiBIBi", 2, 6, 255, 0x80000000, 254, 1) + symbol + bytes(4)
    variables = (variable(-1, 0x40, 255, b"\x00\xff\x80"), variable(7, 0x10, 2, b"text\0"))
    syscall = struct.pack("<IIBBIi", 99, 4, 255, 2, 0x80000000, 2) + b"".join(variables)
    syscalls = (
        struct.pack("<I9Ii", 2, 0, 0, 0, 2, 0, 2, 1, 1, 2, 1) + syscall + symbols + b"\x02\0\xff"
    )
    source = struct.pack("<Ii", 42, 0) + symbols + struct.pack("<i", 3) + b"\xff\0\x01"
    raw = (
        struct.pack("<Ii", 3, -7)
        + de(b"\xff\0")
        + syscalls
        + source
        + struct.pack("<I", 2)
        + b"\0\x02"
        + struct.pack("<I", 0x80000000)
        + bytes(range(9))
    )
    saved = read_xs(SaveReader(raw))
    assert saved.raw == raw
    assert (saved.player_id, saved.name_bytes) == (-7, b"\xff\0")
    assert saved.syscalls.flags == (2, 0, 255)
    assert [v.raw for v in saved.syscalls.entries[0].parameters] == list(variables)
    assert saved.syscalls.symbols.buckets[0][0].name_bytes == b"\xffx\0"
    assert saved.syscalls.symbols.buckets[0][0].value_bits == 0x7FC01234
    assert saved.source.version == 42 and saved.source.code == b"\xff\0\x01"
    assert saved.data_flags == b"\0\x02" and saved.data_slots == (None, None)
    assert saved.fields == {0x70: 0x80000000, **dict(zip(range(0x74, 0x7D), range(9), strict=True))}


def test_outer_save_version_is_checked_separately_from_xs_versions() -> None:
    reader = SaveReader(_raw(), version=0x450000)
    with pytest.raises(UnsupportedSavedXS, match="XS save version"):
        read_xs(reader)
    assert reader.pos == 0
