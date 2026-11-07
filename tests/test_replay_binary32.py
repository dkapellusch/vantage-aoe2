"""Exact scalar endpoints used by damage and later simulation arithmetic."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_binary32 import (
    add_binary32,
    compare_binary32,
    divide_binary32,
    multiply_binary32,
    signed16_binary32,
    signed32_binary32,
    subtract_binary32,
    unsigned64_binary32,
)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (0x3F800000, 0x33800000, 0x3F800000),  # Half an ULP: even lower result.
        (0x3F800001, 0x33800000, 0x3F800002),  # Half an ULP: even upper result.
        (0x3F800000, 0x33800001, 0x3F800001),
        (0x3FFFFFFF, 0x33800000, 0x40000000),  # Rounding carry.
        (0x007FFFFF, 1, 0x00800000),
        (0x00800000, 0x80000001, 0x007FFFFF),
        (1, 0x80000001, 0),
        (0x80000000, 0x80000000, 0x80000000),
        (0, 0x80000000, 0),
        (0x7F7FFFFF, 0x7F7FFFFF, 0x7F800000),
        (0xFF7FFFFF, 0xFF7FFFFF, 0xFF800000),
        (0x7F800000, 0xFF800000, 0xFFC00000),
        (0x7F800000, 1, 0x7F800000),
        (0xFF800000, 0xFF800000, 0xFF800000),
        (0x7F800123, 0xFFC00456, 0x7FC00123),
        (0xFFC00456, 0x7F800123, 0xFFC00456),
        (0x3F800000, 0xFF800123, 0xFFC00123),
    ],
)
def test_add_exact_words(left: int, right: int, expected: int) -> None:
    assert add_binary32(left, right) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (0x41200000, 0x40400000, 0x40E00000),
        (0x3F800000, 0x40000000, 0xBF800000),
        (0x3F800000, 0xBF800000, 0x40000000),
        (0x3F800000, 0x33000000, 0x3F800000),
        (0x3F800000, 0x33000001, 0x3F7FFFFF),
        (0x00800000, 0x007FFFFF, 1),
        (0x80000001, 0x80000001, 0),
        (0x80000000, 0, 0x80000000),
        (0x80000000, 0x80000000, 0),
        (0, 0x80000000, 0),
        (0x7F800000, 0x7F800000, 0xFFC00000),
        (0xFF800000, 0x7F800000, 0xFF800000),
        (0x3F800000, 0xFF800123, 0xFFC00123),  # NaN sign is not flipped by SUBSS.
        (0xFF800123, 0x7FC00456, 0xFFC00123),
    ],
)
def test_subtract_exact_words(left: int, right: int, expected: int) -> None:
    assert subtract_binary32(left, right) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (0x3FC00000, 0x40000000, 0x40400000),
        (0x3F800001, 0x3F800001, 0x3F800002),
        (1, 0x3F000000, 0),
        (3, 0x3F000000, 2),
        (0x80000001, 0x3F000000, 0x80000000),
        (0x00800000, 0x3F000000, 0x00400000),
        (0x007FFFFF, 0x40000000, 0x00FFFFFE),
        (0x7F7FFFFF, 0x40000000, 0x7F800000),
        (0xFF7FFFFF, 0x40000000, 0xFF800000),
        (0, 0xBF800000, 0x80000000),
        (0x80000000, 0xBF800000, 0),
        (0x7F800000, 0, 0xFFC00000),
        (0x80000000, 0xFF800000, 0xFFC00000),
        (0x7F800000, 0xBF800000, 0xFF800000),
        (0xFF800123, 0, 0xFFC00123),
        (0xFFC00456, 0x7F800123, 0xFFC00456),
    ],
)
def test_multiply_exact_words(left: int, right: int, expected: int) -> None:
    assert multiply_binary32(left, right) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (0, 0x80000000, 0),
        (0xFF800000, 0x7F800000, -1),
        (0x80000001, 0x80000000, -1),
        (0xBF800001, 0xBF800000, -1),
        (0x7F7FFFFF, 0x7F800000, -1),
        (0x00800000, 0x007FFFFF, 1),
        (1, 1, 0),
        (0x80000000, 1, -1),
        (0xBF800000, 0xBF800001, 1),
        (0x7F800123, 0, None),
        (0, 0xFFC00456, None),
        (0xFF800123, 0x7FC00456, None),
    ],
)
def test_compare(left: int, right: int, expected: int | None) -> None:
    assert compare_binary32(left, right) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-32768, 0xC7000000),
        (-1, 0xBF800000),
        (0, 0),
        (1, 0x3F800000),
        (32767, 0x46FFFE00),
    ],
)
def test_signed16_conversion(value: int, expected: int) -> None:
    assert signed16_binary32(value) == expected


@pytest.mark.parametrize(
    "operation",
    [
        add_binary32,
        subtract_binary32,
        multiply_binary32,
        compare_binary32,
    ],
)
@pytest.mark.parametrize("bad", [-1, 1 << 32, True, 1.0, None])
def test_invalid_words(operation: Callable[[int, int], int | None], bad: int) -> None:
    with pytest.raises(ValueError):
        operation(bad, 0)
    with pytest.raises(ValueError):
        operation(0, bad)


@pytest.mark.parametrize("bad", [-32769, 32768, True, 1.0, None])
def test_invalid_signed16(bad: int) -> None:
    with pytest.raises(ValueError):
        signed16_binary32(bad)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-(1 << 31), 0xCF000000),
        ((1 << 31) - 1, 0x4F000000),
        (-1, 0xBF800000),
        (0, 0),
        (1, 0x3F800000),
        (16777216, 0x4B800000),
        (16777217, 0x4B800000),
        (16777218, 0x4B800001),
        (16777219, 0x4B800002),
        (-16777217, 0xCB800000),
        (-16777219, 0xCB800002),
        (33554431, 0x4C000000),
        (1073741888, 0x4E800000),
        (1073742016, 0x4E800002),
        (-1073742016, 0xCE800002),
        (2147483520, 0x4EFFFFFF),
        (2147483583, 0x4EFFFFFF),
        (2147483584, 0x4F000000),
    ],
)
def test_signed32_conversion_rounding(value: int, expected: int) -> None:
    assert signed32_binary32(value) == expected


@pytest.mark.parametrize("bad", [-(1 << 31) - 1, 1 << 31, True, 1.0, None])
def test_invalid_signed32(bad: int) -> None:
    with pytest.raises(ValueError):
        signed32_binary32(bad)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (0x3F800000, 0x40400000, 0x3EAAAAAB),
        (0x41200000, 0x40400000, 0x40555555),
        (0x7F7FFFFF, 0x40000000, 0x7EFFFFFF),
        (0x7F7FFFFF, 0x3F000000, 0x7F800000),
        (1, 0x40000000, 0),
        (3, 0x40000000, 2),
        (0x80000001, 0x40000000, 0x80000000),
        (0x00800000, 0x40000000, 0x00400000),
        (0x00800000, 0x3F800001, 0x007FFFFF),
        (0x007FFFFF, 0x3F000000, 0x00FFFFFE),
        (0, 0xBF800000, 0x80000000),
        (0x80000000, 0xBF800000, 0),
        (0xBF800000, 0, 0xFF800000),
        (0x3F800000, 0x80000000, 0xFF800000),
        (0, 0, 0xFFC00000),
        (0x80000000, 0, 0xFFC00000),
        (0x7F800000, 0x7F800000, 0xFFC00000),
        (0xFF800000, 0x3F800000, 0xFF800000),
        (0x3F800000, 0xFF800000, 0x80000000),
        (0x7F800123, 0xFFC00456, 0x7FC00123),
        (0xFFC00456, 0x7F800123, 0xFFC00456),
        (0x3F800000, 0xFF800123, 0xFFC00123),
    ],
)
def test_divide_exact_words(left: int, right: int, expected: int) -> None:
    assert divide_binary32(left, right) == expected


@pytest.mark.parametrize("bad", [-1, 1 << 32, True, 1.0, None])
def test_invalid_division_words(bad: int) -> None:
    with pytest.raises(ValueError):
        divide_binary32(bad, 0)
    with pytest.raises(ValueError):
        divide_binary32(0, bad)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0),
        (1, 0x3F800000),
        ((1 << 24) + 1, 0x4B800000),
        ((1 << 24) + 3, 0x4B800002),
        ((1 << 63) - 1, 0x5F000000),
        (1 << 63, 0x5F000000),
        ((1 << 63) + (1 << 39), 0x5F000000),
        ((1 << 63) + (1 << 39) + 1, 0x5F000001),
        ((1 << 64) - (1 << 39) - 1, 0x5F7FFFFF),
        ((1 << 64) - (1 << 39), 0x5F800000),
        ((1 << 64) - 1, 0x5F800000),
    ],
)
def test_unsigned64_sticky_half_conversion(value: int, expected: int) -> None:
    assert unsigned64_binary32(value) == expected


@pytest.mark.parametrize("bad", [-1, 1 << 64, True, 1.0, None])
def test_invalid_unsigned64(bad: int) -> None:
    with pytest.raises(ValueError):
        unsigned64_binary32(bad)
