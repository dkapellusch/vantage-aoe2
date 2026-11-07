"""Independent original-game angle oracles and explicit supported-domain checks."""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from vantage.replay_trigonometry import (
    native_acos_bits,
    native_cos_small_bits,
    native_cos_turn_bits,
    native_sin_small_bits,
    native_sin_turn_bits,
)

FUNCTIONS = (native_acos_bits, native_sin_small_bits, native_cos_small_bits)
TURN_FUNCTIONS = (native_sin_turn_bits, native_cos_turn_bits)


@pytest.fixture(scope="module")
def native_rows() -> list[list[int]]:
    path = Path(__file__).parent / "fixtures/native_replay_trigonometry_54800.json.gz"
    result = json.loads(gzip.decompress(path.read_bytes()))
    rows: list[list[int]] = result["rows"]
    return rows


@pytest.mark.parametrize("kind,count", ((0, 41194), (1, 81962), (2, 81962)))
def test_original_native_outputs(kind: int, count: int, native_rows: list[list[int]]) -> None:
    rows = [row for row in native_rows if row[0] == kind]
    assert len(rows) == count
    for _, value, expected in rows:
        assert FUNCTIONS[kind](value) == expected, (kind, hex(value), hex(expected))


@pytest.mark.parametrize("function", FUNCTIONS + TURN_FUNCTIONS)
@pytest.mark.parametrize("value", (-1, 0x100000000, 0.0, None))
def test_invalid_scalar_words(function: Callable[[int], int], value: object) -> None:
    # The object-typed call exercises public input validation without bypassing types.
    with pytest.raises(ValueError):
        function(value)  # type: ignore[arg-type]  # Deliberately invalid public input.


@pytest.mark.parametrize("function", (native_sin_small_bits, native_cos_small_bits))
@pytest.mark.parametrize("value", (0x3F490FDB, 0xBF490FDB, 0x3F800000, 0x7F800000, 0x7FC00001))
def test_small_angle_rejects_unimplemented_range_reduction(
    function: Callable[[int], int], value: int
) -> None:
    with pytest.raises(ValueError, match="small-angle branch"):
        function(value)


def test_native_truncated_endpoints_and_signed_tiny_sine() -> None:
    assert native_acos_bits(0x3F800000) == 0
    assert native_acos_bits(0xBF800000) == 0x40490FDA
    assert native_acos_bits(0) == 0x3FC90FDA
    assert native_sin_small_bits(0x80000000) == 0x80000000
    assert native_sin_small_bits(1) == 1
    assert native_cos_small_bits(0x80000001) == 0x3F800000


@pytest.mark.parametrize("kind", (0, 1))
def test_original_turn_range_outputs(kind: int) -> None:
    path = Path(__file__).parent / "fixtures/native_replay_turn_trigonometry_54800.json.gz"
    rows = [row for row in json.loads(gzip.decompress(path.read_bytes()))["rows"] if row[0] == kind]
    assert len(rows) == 82044
    for _, value, expected in rows:
        assert TURN_FUNCTIONS[kind](value) == expected, (kind, hex(value), hex(expected))


@pytest.mark.parametrize("function", TURN_FUNCTIONS)
@pytest.mark.parametrize("value", (0x40490FDC, 0xC0490FDC, 0x7F800000, 0x7FC00001))
def test_turn_functions_reject_unimplemented_range_reduction(
    function: Callable[[int], int], value: int
) -> None:
    with pytest.raises(ValueError, match="turn range"):
        function(value)
