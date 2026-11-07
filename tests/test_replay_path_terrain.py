"""Original native classification oracle and selector/grid scalar boundaries."""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

import pytest

from vantage.replay_path_terrain import (
    build_path_terrain_selector,
    path_terrain_class,
    path_terrain_query_mask,
    replace_path_terrain_class,
)


def test_classification_matches_every_retained_original_native_leaf_result() -> None:
    fixture = Path(__file__).parent / "fixtures/native_path_terrain_classes_54800.bin.gz"
    raw = gzip.decompress(fixture.read_bytes())
    assert len(raw) == (65536 + 4096) * 8
    for flags, expected in struct.iter_unpack("<II", raw):
        assert path_terrain_class(flags) == expected


def test_native_class_precedence_and_unselected_high_bits() -> None:
    assert [path_terrain_class(f) for f in (0, 1, 8, 32, 63, 0x80000020, 0xFFFFFFFF)] == [
        0,
        1,
        2,
        4,
        1,
        4,
        1,
    ]


def test_build_matched_recording_selector_7_from_explicit_initialized_values() -> None:
    path = Path(__file__).parent / "fixtures/native_path_terrain_selector_54800.json"
    fixture = json.loads(path.read_text())
    words = fixture["terrain_speed_words"]
    for unused in (0, 0xFFFFFFFF):
        flags = [unused] * len(words)
        for terrain_id, value in fixture["initialized_class_flags"].items():
            flags[int(terrain_id)] = value
        selector = build_path_terrain_selector(words, flags)
        assert selector == fixture["effective_selector"] == 6
        assert path_terrain_query_mask(selector) == fixture["query_mask"] == 249


def test_selector_uses_positive_binary32_words_and_explicit_initialized_classes() -> None:
    words = (0x3F800000, 0x7F800000, 0xBF800000, 0, 0x80000000, 0x7FC01234, 0xFFC01234, 1)
    flags = (8, 32, 1, 1, 1, 1, 1, 32)
    assert build_path_terrain_selector(words, flags) == 6
    assert words[-1] == 1 and flags[-1] == 32
    assert build_path_terrain_selector((), ()) == 0
    assert build_path_terrain_selector((0x3F800000,), (0,)) == 0
    assert build_path_terrain_selector((0x3F800000,), (1,)) == 1


def test_cell_replacement_retains_every_high_occupancy_bit() -> None:
    for high in (0, 0x123456789ABCDE00, 0xFFFFFFFFFFFFFF00, 0x8000000000000000):
        for low in (0, 4, 255):
            assert replace_path_terrain_class(high | low, 32) == high | 4
            assert replace_path_terrain_class(high | low, 0) == high


def test_query_mask_preserves_native_xor_and_signed_extension() -> None:
    assert path_terrain_query_mask(6) == 249
    assert path_terrain_query_mask(0) == 255
    assert path_terrain_query_mask(255) == 0
    assert path_terrain_query_mask(0x80000006) == -2147483399


@pytest.mark.parametrize("bad", (-1, 1 << 32, 1.25, "1"))
def test_reject_invalid_flag_and_selector_words(bad: int) -> None:
    with pytest.raises(ValueError):
        path_terrain_class(bad)
    with pytest.raises(ValueError):
        path_terrain_query_mask(bad)


@pytest.mark.parametrize("bad", (-1, 1 << 64))
def test_reject_invalid_cell_words(bad: int) -> None:
    with pytest.raises(ValueError):
        replace_path_terrain_class(bad, 0)


def test_reject_mismatched_oversized_or_invalid_selector_inputs() -> None:
    for words, flags in (((0,), ()), ((0,) * 257, (0,) * 257), ((-1,), (0,)), ((0,), (-1,))):
        with pytest.raises(ValueError):
            build_path_terrain_selector(words, flags)
