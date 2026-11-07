"""Native small AI module spans and variable strategy framing."""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

import pytest

from vantage.replay_ai_modules import SimpleAIKind, read_simple_ai
from vantage.replay_binary import SaveDecodeError, SaveReader

FIXTURE = Path(__file__).parent / "fixtures/native_saved_small_ai_54800.json.gz"


def _u32s(*words: int) -> bytes:
    return struct.pack("<" + "I" * len(words), *words)


def _strategy() -> bytes:
    payload = b"name\x00\x10\x0a\x20\x0a"
    return (
        b"\x10\x0a"
        + _u32s(1, 2, 3, 4)
        + bytes(range(32))
        + _u32s(5, 6, 7, 8)
        + b"\xa0\x0a"
        + _u32s(len(payload))
        + payload
        + _u32s(2, 9, 10, 0, 1, 11, 12)
        + b"\x20\x0a"
    )


def test_native_modules_reach_exact_constructor_continuations() -> None:
    cases = json.loads(gzip.decompress(FIXTURE.read_bytes()))["cases"]
    assert len(cases) == 42
    for case in cases:
        raw = bytes.fromhex(case["raw_hex"])
        following = bytes.fromhex(case["next_bytes_hex"])
        reader = SaveReader(raw + following)
        module = read_simple_ai(reader, case["kind"])
        assert module.raw == raw
        assert reader.pos == len(raw) == case["end_offset"] - case["offset"]
        assert reader.data[reader.pos :] == following
        if case["kind"] == "main":
            assert set(module.lists[0xB8]) <= set(case["native_owner_ids"])
            assert len(raw) == 8 + 4 * len(module.lists[0xB8])
        elif case["kind"] == "diplomacy":
            assert len(raw) == 94 and len(module.fields) == 30
        elif case["kind"] == "emotional":
            assert len(raw) == 28 and len(module.fields) == 6
        elif case["kind"] == "resource":
            assert len(raw) == 8 and len(module.fields) == 1
        elif case["kind"] == "strategy":
            assert len(raw) == 90 + len(module.strings[0xC0])
            assert len(module.fields) == 9 and len(module.vectors) == 2
        else:
            assert case["kind"] == "trade" and len(raw) == 4 and not module.fields


def test_strategy_preserves_embedded_markers_in_payload_and_distinct_vectors() -> None:
    raw = _strategy()
    reader = SaveReader(raw + b"next")
    module = read_simple_ai(reader, "strategy")
    assert module.fields == {
        0xB8: 1,
        0xD8: 2,
        0xE0: 3,
        0xE4: 4,
        0x108: 5,
        0x10C: 6,
        0x110: 7,
        0x968: 8,
        0x978: 12,
    }
    assert module.vectors == {0xE8: bytes(range(16)), 0xF8: bytes(range(16, 32))}
    assert module.strings == {0xC0: b"name\x00\x10\x0a\x20\x0a"}
    assert module.lists == {0x118: (9, 10), 0x130: (), 0x148: (11,)}
    assert module.raw == raw and reader.remaining == 4


@pytest.mark.parametrize(
    "kind,body",
    [
        ("main", _u32s(2, 0xFFFFFFFF, 71)),
        ("diplomacy", b"".join(_u32s(i, i + 10) + bytes([i]) for i in range(10))),
        ("emotional", _u32s(0, 1, 2, 0x7FA00000, 4, 0x80000000)),
        ("resource", _u32s(0xFFFFFFFF)),
        ("trade", b""),
    ],
)
def test_fixed_native_grammars_preserve_uninterpreted_scalar_bits(
    kind: SimpleAIKind, body: bytes
) -> None:
    raw = b"\x10\x0a" + body + b"\x20\x0a"
    reader = SaveReader(raw)
    module = read_simple_ai(reader, kind)
    assert module.raw == raw and reader.remaining == 0


@pytest.mark.parametrize(
    "kind,raw",
    [
        ("main", b"\x10\x0a" + _u32s(2, 71, 72) + b"\x20\x0a"),
        ("diplomacy", b"\x10\x0a" + bytes(90) + b"\x20\x0a"),
        ("emotional", b"\x10\x0a" + bytes(24) + b"\x20\x0a"),
        ("resource", b"\x10\x0a" + bytes(4) + b"\x20\x0a"),
        ("strategy", _strategy()),
        ("trade", b"\x10\x0a\x20\x0a"),
    ],
)
def test_every_truncation_rolls_back_the_module(kind: SimpleAIKind, raw: bytes) -> None:
    for length in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:length], 6)
        with pytest.raises(SaveDecodeError):
            read_simple_ai(reader, kind)
        assert reader.pos == 6


@pytest.mark.parametrize("count", [0, -1, -2147483648])
def test_native_nonpositive_main_count_has_no_payload(count: int) -> None:
    raw = b"\x10\x0a" + struct.pack("<i", count) + b"\x20\x0a"
    reader = SaveReader(raw)
    assert read_simple_ai(reader, "main").lists == {0xB8: ()}
    assert reader.remaining == 0


def test_bad_markers_and_impossible_counts_are_not_resynchronized() -> None:
    for raw in (b"\x11\x0a" + _u32s(0) + b"\x20\x0a", b"\x10\x0a" + _u32s(1_000_000)):
        reader = SaveReader(raw)
        with pytest.raises(SaveDecodeError):
            read_simple_ai(reader, "main")
        assert reader.pos == 0


def test_native_strategy_string_limit_and_save_guard() -> None:
    raw = bytearray(_strategy())
    struct.pack_into("<I", raw, 68, 0xA00001)
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError, match="string length"):
        read_simple_ai(reader, "strategy")
    assert reader.pos == 0
    reader = SaveReader(_strategy(), version=0x450000)
    with pytest.raises(SaveDecodeError, match="save version"):
        read_simple_ai(reader, "strategy")
    assert reader.pos == 0
