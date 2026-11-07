"""Complete empty-occupancy request outputs from unchanged original code."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from vantage.replay_clear_path import EmptyPathContext, find_empty_replay_path

FIXTURES = Path(__file__).parent / "fixtures"
Q = 1 << 22
CONTEXT = EmptyPathContext(32, (0,) * 1024)


@pytest.mark.parametrize(
    ("name", "digest", "cases", "header"),
    [
        (
            "native_clear_paths_54800.json.gz",
            "fd0fc017d8c3540943d130d03ae79c544331ffb8a8b4ebacb6a4f24042375cb7",
            21100,
            7,
        ),
        (
            "native_clear_path_precision_54800.json.gz",
            "7fa9ab65d6d08c9168232d56109408ad5a4049c03455b33369d532c937dadd57",
            150,
            8,
        ),
    ],
)
def test_complete_requests_match_original_native_code(
    name: str, digest: str, cases: int, header: int
) -> None:
    blob = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(blob).hexdigest() == digest
    oracle = json.loads(gzip.decompress(blob))
    assert not oracle["original_instructions_changed"]
    assert not oracle["game_launched"]
    assert not oracle["original_imports_executed"]
    assert not oracle["original_heap_allocation_executed"]
    contexts = {CONTEXT.stride: CONTEXT}
    for row, expected in oracle["cases"]:
        sx, sy, gx, gy, radius, tx, ty, reach, mode = row[:9]
        stride = row[9] if len(row) == 10 else 32
        if stride not in contexts:
            contexts[stride] = EmptyPathContext(stride, (0,) * stride**2)
        result = find_empty_replay_path(
            contexts[stride],
            (sx, sy),
            (gx, gy),
            radius,
            target_extents=(tx, ty),
            range_q22=reach,
            heuristic_mode=bool(mode),
            length_bits=0xA5A5A5A5,
            clock_bits=0xA5A5A5A5,
        )
        assert [result.status, len(result.points), result.length_bits, result.clock_bits] == (
            expected[:4]
        ), row
        assert result.heuristic_bits == (expected[6] if expected[5] else None), row
        assert [word for point in result.points for word in point] == expected[header:], row
    assert len(oracle["cases"]) == cases


def test_clear_route_preserves_raw_length_and_clock_words() -> None:
    result = find_empty_replay_path(
        CONTEXT,
        (8 * Q, 8 * Q),
        (10 * Q, 9 * Q),
        Q // 4,
        length_bits=0x7F800001,
        clock_bits=0xFFFFFFFF,
    )
    assert result.status == 1
    assert result.points == ((0x41000000, 0, 0x41000000), (0x41200000, 0, 0x41100000))
    assert result.length_bits == 0x7F800001
    assert result.clock_bits == 0xFFFFFFFF


def test_target_extent_clipping_is_part_of_the_original_route() -> None:
    result = find_empty_replay_path(
        CONTEXT,
        (8 * Q, 8 * Q),
        (10 * Q, 9 * Q),
        Q // 4,
        target_extents=(Q // 2, Q // 2),
    )
    assert result.status == 1
    assert result.points[-1] == (0x41180000, 0, 0x410C0000)  # 9.5,0,8.75


def test_integer_range_endpoint_adjustment_matches_native_rounding() -> None:
    result = find_empty_replay_path(
        CONTEXT, (8 * Q, 8 * Q), (10 * Q, 9 * Q), Q // 4, range_q22=Q // 2
    )
    assert result.status == 1
    assert result.points[-1] == (0x4118D836, 0, 0x410C6C1B)


def test_outside_goal_is_clipped_by_the_core_window() -> None:
    # The outer1410779a0 wrapper has its own bounds validation. This calls the
    # modern core contract directly, as in the original native oracle.
    result = find_empty_replay_path(CONTEXT, (8 * Q, 8 * Q), (34 * Q, 8 * Q), Q // 4)
    assert result.status == 1
    assert result.points[-1] == (0x41FE0000, 0, 0x41000000)


def test_invalid_start_returns_raw_status5_without_points() -> None:
    result = find_empty_replay_path(CONTEXT, (0, 0), (8 * Q, 8 * Q), Q // 4)
    assert result.status == 5
    assert result.points == ()
    assert result.heuristic_bits is None


def test_already_in_range_includes_native_squared_distance_quantization() -> None:
    result = find_empty_replay_path(CONTEXT, (8 * Q, 8 * Q), (8 * Q + 3, 8 * Q - 3), Q // 4)
    assert result.status == 0
    assert result.points == ()
    assert result.heuristic_bits is None


def test_floating_heuristic_can_accept_only_the_initial_node() -> None:
    start, goal = (Q // 4, 8 * Q), (Q // 4 + 31 * Q + 2, 8 * Q)
    floating = find_empty_replay_path(CONTEXT, start, goal, Q // 4, range_q22=31 * Q + 1)
    integer = find_empty_replay_path(
        CONTEXT, start, goal, Q // 4, range_q22=31 * Q + 1, heuristic_mode=True
    )
    assert floating.status == integer.status == 1
    assert floating.points == ((0x3E800000, 0, 0x41000000),)
    assert integer.points[-1] == (0x3E800008, 0, 0x41000000)


@pytest.mark.parametrize("mode", (False, True))
def test_large_map_heuristic_wrap_can_accept_only_start(mode: bool) -> None:
    context = EmptyPathContext(480, (0,) * 480**2)
    result = find_empty_replay_path(
        context, (8 * Q, 8 * Q), (472 * Q, 472 * Q), Q // 4, heuristic_mode=mode
    )
    assert result.status == 1
    assert result.points == ((0x41000000, 0, 0x41000000),)
    assert result.heuristic_bits is not None and result.heuristic_bits & 0x80000000


def test_blocked_occupancy_is_rejected_explicitly() -> None:
    with pytest.raises(ValueError, match="empty occupancy"):
        EmptyPathContext(1, (1,))
    with pytest.raises(ValueError, match="empty occupancy"):
        EmptyPathContext(1, (0,), ((0, 0, Q, Q),))


def test_native_unsafe_grid_line_cell_access_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid cell"):
        find_empty_replay_path(CONTEXT, (1, 0), (0, Q), 0)


@pytest.mark.parametrize("stride", (0, 513))
def test_unsupported_context_stride_is_rejected(stride: int) -> None:
    with pytest.raises(ValueError, match="stride"):
        EmptyPathContext(stride, ())


def test_context_shape_and_immutable_occupancy_are_required() -> None:
    with pytest.raises(ValueError, match="one qword"):
        EmptyPathContext(2, (0,))
    with pytest.raises(ValueError, match="immutable tuple"):
        EmptyPathContext(1, (0,), [])
    with pytest.raises(ValueError, match="integer"):
        EmptyPathContext(1, (0.0,))


@pytest.mark.parametrize("radius", (-1, Q // 2 + 1))
def test_radius_outside_modern_branch_is_rejected(radius: int) -> None:
    with pytest.raises(ValueError, match="radius"):
        find_empty_replay_path(CONTEXT, (8 * Q, 8 * Q), (10 * Q, 9 * Q), radius)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(range_q22=-1),
        dict(target_extents=(-1, 0)),
        dict(target_extents=((1 << 31) - 1, 0)),
        dict(heuristic_mode=1),
        dict(length_bits=1 << 32),
        dict(clock_bits=-1),
    ],
)
def test_invalid_scalar_domains_are_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        find_empty_replay_path(CONTEXT, (8 * Q, 8 * Q), (10 * Q, 9 * Q), Q // 4, **kwargs)
