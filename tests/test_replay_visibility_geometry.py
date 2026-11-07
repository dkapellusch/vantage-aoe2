"""Dual-image static mask expectations and original signed row clipping rules."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from functools import cache
from pathlib import Path

import pytest

from vantage.replay_visibility_geometry import (
    UnsupportedReplayVisibilityGeometry,
    replay_visibility_rows,
)

FIXTURE = Path(__file__).parent / "fixtures/native_visibility_circle_rows_42.json.gz"
MAX_I32 = 0x7FFFFFFF
MIN_I32 = -0x80000000


@cache
def _fixture():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


@pytest.mark.parametrize(
    "mode,radius", [(mode, radius) for mode in range(2) for radius in range(21)]
)
def test_all_42_original_row_tables(mode: int, radius: int) -> None:
    fixture = _fixture()
    assert fixture["scope"] == "Original static table data, no Game/native fixture execution"
    case = fixture["cases"][mode * 21 + radius]
    raw = bytes.fromhex(case["raw_hex"])
    assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
    records = list(struct.iter_unpack("<iii", raw))
    assert records[-1] == (999, 0, 0)
    assert records[:-1] == [tuple(row) for row in case["rows"]]
    actual = replay_visibility_rows(50, 50, radius, mode, width=101, height=101)
    expected = tuple((dy + 50, low + 50, high + 50) for dy, low, high in case["rows"])
    assert actual == expected
    assert sum(high - low + 1 for _, low, high in actual) == case["count"]


def test_fixture_packed_data_and_both_static_pointer_tables() -> None:
    fixture = _fixture()
    assert len(fixture["cases"]) == 42
    packed = bytearray()
    for case in fixture["cases"]:
        packed.append(len(case["rows"]) + 1)
        packed.extend(bytes.fromhex(case["raw_hex"]))
    assert (
        hashlib.sha256(packed).hexdigest()
        == ("6e12cd3f9e6ed880fa4f2f41fd59838a9db839a9fdc6cd5f729d246c357c20f8")
        == fixture["packed_sha256"]
    )
    assert [p["address"] for p in fixture["pointer_tables"]] == ["0x14408d1a0", "0x14408d250"]
    for table in fixture["pointer_tables"]:
        raw = bytes.fromhex(table["raw_hex"])
        assert len(raw) == 21 * 8
        assert hashlib.sha256(raw).hexdigest() == table["sha256"]
    assert (fixture["native_code_bytes"], fixture["native_instructions"]) == (2178, 534)


def test_radius_one_masks_are_not_a_euclidean_circle_approximation() -> None:
    assert replay_visibility_rows(3, 3, 1, 0, width=7, height=7) == (
        (2, 2, 4),
        (3, 2, 4),
        (4, 2, 4),
    )
    assert replay_visibility_rows(3, 3, 1, 1, width=7, height=7) == ((2, 2, 3), (3, 2, 3))


@pytest.mark.parametrize("mode,count", [(0, 1313), (1, 1256)])
def test_maximum_radius_and_cap(mode: int, count: int) -> None:
    rows = replay_visibility_rows(30, 30, 20, mode, width=61, height=61)
    assert len(rows) <= 41
    assert sum(high - low + 1 for _, low, high in rows) == count
    assert replay_visibility_rows(30, 30, MAX_I32, mode, width=61, height=61) == rows
    assert replay_visibility_rows(30, 30, 21, mode, width=61, height=61) == rows


@pytest.mark.parametrize("mode", [0, 1, -1, MIN_I32, MAX_I32])
def test_zero_radius_and_nonzero_flag(mode: int) -> None:
    assert replay_visibility_rows(0, 0, 0, mode, width=1, height=1) == ((0, 0, 0),)
    assert replay_visibility_rows(1, 0, 0, mode, width=1, height=1) == ()
    if mode:
        assert replay_visibility_rows(3, 3, 1, mode, width=7, height=7) == (
            (2, 2, 3),
            (3, 2, 3),
        )


@pytest.mark.parametrize(
    "center,mode,expected",
    [
        ((0, 0), 0, ((0, 0, 1), (1, 0, 1))),
        ((0, 0), 1, ((0, 0, 0),)),
        ((1, 1), 0, ((0, 0, 1), (1, 0, 1))),
        ((1, 1), 1, ((0, 0, 1), (1, 0, 1))),
        ((-1, -1), 0, ((0, 0, 0),)),
        ((-1, -1), 1, ()),
        ((3, 3), 0, ()),
    ],
)
def test_inclusive_clipping_at_edges_and_outside(center, mode, expected) -> None:
    assert replay_visibility_rows(*center, 1, mode, width=2, height=2) == expected


def test_wrapping_y_addition_can_reenter_a_valid_large_grid() -> None:
    # ADD ofMIN_I32 and the original row dY-2 yieldsMAX_I32-1; dY-1 yieldsMAX_I32
    # and is clipped. Ordinary unbounded Python addition would wrongly omit this row.
    assert replay_visibility_rows(0, MIN_I32, 2, 0, width=1, height=MAX_I32) == (
        (MAX_I32 - 1, 0, 0),
    )
    rows = replay_visibility_rows(0, MIN_I32, 20, 0, width=1, height=MAX_I32)
    assert rows == tuple((y, 0, 0) for y in range(MAX_I32 - 19, MAX_I32))


def test_wrapping_x_endpoints_and_signed_upper_clip() -> None:
    assert replay_visibility_rows(MAX_I32, 0, 1, 0, width=MAX_I32, height=1) == ()
    assert replay_visibility_rows(MAX_I32, 0, 1, 1, width=MAX_I32, height=1) == (
        (0, MAX_I32 - 1, MAX_I32 - 1),
    )
    assert replay_visibility_rows(MIN_I32, 0, 1, 1, width=MAX_I32, height=1) == ()


def test_storage_domain_accepts_large_maps_without_allocating_a_grid() -> None:
    assert replay_visibility_rows(100, 100, 1, 0, width=46340, height=46340) == (
        (99, 99, 101),
        (100, 99, 101),
        (101, 99, 101),
    )


@pytest.mark.parametrize(
    "width,height", [(0, 10), (10, 0), (-1, 1), (1, -1), (MAX_I32, 2), (46341, 46341)]
)
def test_invalid_storage_domain_is_explicit(width: int, height: int) -> None:
    with pytest.raises(UnsupportedReplayVisibilityGeometry, match="storage premises"):
        replay_visibility_rows(0, 0, 1, 0, width=width, height=height)


@pytest.mark.parametrize("radius", [-1, MIN_I32])
def test_negative_radius_rejects_unsafe_native_index(radius: int) -> None:
    with pytest.raises(UnsupportedReplayVisibilityGeometry, match="unsafe native table index"):
        replay_visibility_rows(0, 0, radius, 0, width=10, height=10)


@pytest.mark.parametrize("name", ["center_x", "center_y", "radius", "mode_flag", "width", "height"])
@pytest.mark.parametrize("invalid", [True, 1.0, "1", None, MAX_I32 + 1, MIN_I32 - 1])
def test_exact_i32_inputs(name, invalid) -> None:
    values = dict(center_x=0, center_y=0, radius=1, mode_flag=0, width=10, height=10)
    values[name] = invalid
    with pytest.raises(UnsupportedReplayVisibilityGeometry, match=name):
        replay_visibility_rows(**values)
