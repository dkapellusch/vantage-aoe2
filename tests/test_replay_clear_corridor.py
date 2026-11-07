"""Populated controlled native requests and explicit unported search boundaries."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_clear_corridor import (
    ClearCorridorContext,
    UnsupportedClearCorridor,
    find_clear_corridor_path,
)

Q = 1 << 22
FIXTURE = Path(__file__).parent / "fixtures/native_clear_corridor_paths_54800.json.gz"


def oracle() -> dict:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "e706d5e3c5fbe8c9421cd6087566b27e2d3e145cadaccf33fe11b980315cee00"
    )
    return json.loads(gzip.decompress(raw))


def context_of(case: dict) -> ClearCorridorContext:
    stride = case["input"][9]
    masks = [case["base_mask"]] * stride**2
    for index, value in case["overrides"]:
        masks[index] = value
    return ClearCorridorContext(
        stride,
        tuple(masks),
        tuple(tuple(rectangle) for rectangle in case["rectangles"]),
        tuple(case["ignored"]),
        case["selector_mask"],
    )


def pig_case() -> dict:
    return next(
        case for case in oracle()["cases"] if case["label"] == "pig-saved-t0-create_141122240"
    )


def test_all_populated_and_empty_controls_match_unchanged_original_requests() -> None:
    fixture = oracle()
    assert len(fixture["cases"]) == 796
    assert fixture["capture_provenance"]["rea_evidence_id"] == (
        "ev_58854a572ab8aab53c87a9a8e92882426f91538fa79c1c2c050937571dd45eef"
    )
    assert not fixture["original_instructions_changed"]
    assert not fixture["game_launched"]
    assert fixture["all_supplied_original_function_bytes_equal_historical"]
    for case in fixture["cases"]:
        row, expected = case["input"], case["result"]
        result = find_clear_corridor_path(
            context_of(case),
            tuple(row[:2]),
            tuple(row[2:4]),
            row[4],
            target_extents=tuple(row[5:7]),
            range_q22=row[7],
            heuristic_mode=bool(row[8]),
            length_bits=0xA5A5A5A5,
            clock_bits=0xA5A5A5A5,
        )
        assert [result.status, len(result.points), result.length_bits, result.clock_bits] == (
            expected[:4]
        ), case["label"]
        assert result.heuristic_bits == (expected[6] if expected[5] else None), case["label"]
        assert [word for point in result.points for word in point] == expected[8:], case["label"]


def test_actual_local_pig_candidates_clear_without_assuming_no_obstacles() -> None:
    case = pig_case()
    context = context_of(case)
    assert len(context.obstacles) == 10
    assert case["source_entity_ids"][context.ignored.index(1)] == 10449
    assert case["witness"]["nonignored_candidate_visits"] > 0
    result = find_clear_corridor_path(
        context,
        (656408576, 538968064),
        (673229504, 529312416),
        1258291,
        length_bits=0x7F800001,
        clock_bits=0xFFFFFFFF,
    )
    assert result.status == 1
    assert result.points == ((1125941248, 0, 1124106240), (1126204075, 0, 1123837269))
    assert result.length_bits == 0x7F800001 and result.clock_bits == 0xFFFFFFFF
    assert case["context_claim"] == "controlled local candidate superset, not captured query heap"


def test_self_must_be_explicitly_ignored() -> None:
    context = context_of(pig_case())
    with pytest.raises(UnsupportedClearCorridor, match="start relocation"):
        find_clear_corridor_path(
            replace(context, ignored=(0,) * len(context.obstacles)),
            (656408576, 538968064),
            (673229504, 529312416),
            1258291,
        )


def test_selected_terrain_elsewhere_is_allowed_but_window_insertion_is_unsupported() -> None:
    context = context_of(pig_case())
    assert context.cell_masks[0] & context.selector_mask
    masks = list(context.cell_masks)
    masks[128 * context.stride + 156] = 1
    with pytest.raises(UnsupportedClearCorridor, match="terrain rectangle insertion"):
        find_clear_corridor_path(
            replace(context, cell_masks=tuple(masks)),
            (656408576, 538968064),
            (673229504, 529312416),
            1258291,
        )


def test_a_nonignored_rectangle_crossing_the_route_is_unsupported() -> None:
    context = context_of(pig_case())
    blocked = replace(
        context,
        obstacles=(*context.obstacles, (158 * Q, 127 * Q, 159 * Q, 128 * Q)),
        ignored=(*context.ignored, 0),
    )
    with pytest.raises(UnsupportedClearCorridor, match="obstructed route search"):
        find_clear_corridor_path(blocked, (656408576, 538968064), (673229504, 529312416), 1258291)


def test_negative_query_mask_sign_extends_to_high_cell_bits() -> None:
    context = ClearCorridorContext(16, (1 << 50,) * 256, (), (), 249)
    args = ((8 * Q, 8 * Q), (10 * Q, 9 * Q), Q // 4)
    assert find_clear_corridor_path(context, *args).status == 1
    with pytest.raises(UnsupportedClearCorridor, match="terrain rectangle insertion"):
        find_clear_corridor_path(replace(context, selector_mask=-1), *args)


def test_invalid_start_preserves_native_status_before_any_terrain_insertion() -> None:
    context = ClearCorridorContext(16, (0xFFFFFFFFFFFFFFFF,) * 256, (), (), -1)
    result = find_clear_corridor_path(context, (0, 0), (8 * Q, 8 * Q), Q // 4)
    assert result.status == 5 and result.points == () and result.heuristic_bits is None


def test_conservative_whole_rectangle_gate_rejects_a_hidden_crossing() -> None:
    # No cell index lists are trusted or synthesized by this API. The full
    # registered vector supplies a sufficient clearance proof.
    context = ClearCorridorContext(16, (4,) * 256, ((9 * Q, 7 * Q, 10 * Q, 9 * Q),), (0,), 249)
    with pytest.raises(UnsupportedClearCorridor, match="obstructed route search"):
        find_clear_corridor_path(context, (8 * Q, 8 * Q), (12 * Q, 8 * Q), Q // 4)


@pytest.mark.parametrize("stride", (0, 513))
def test_invalid_stride_is_rejected(stride: int) -> None:
    with pytest.raises(ValueError, match="stride"):
        ClearCorridorContext(stride, (), (), (), 0)


@pytest.mark.parametrize("mask", (-1, 1 << 64, 1.25))
def test_invalid_cell_words_are_rejected(mask: int) -> None:
    with pytest.raises(ValueError, match="u64"):
        ClearCorridorContext(1, (mask,), (), (), 0)


def test_immutable_shapes_ignore_bytes_and_scalar_domains_are_required() -> None:
    for kwargs in (
        dict(cell_masks=()),
        dict(cell_masks=[0]),
        dict(obstacles=[]),
        dict(obstacles=((0, 0, Q, Q),)),
        dict(obstacles=((0, 0, Q),), ignored=(0,)),
        dict(obstacles=((Q, 0, 0, Q),), ignored=(0,)),
        dict(obstacles=((0, 0, Q, Q),), ignored=(2,)),
        dict(obstacles=((0, 0, 1 << 31, Q),), ignored=(0,)),
        dict(selector_mask=1 << 31),
    ):
        arguments = dict(stride=1, cell_masks=(0,), obstacles=(), ignored=(), selector_mask=0)
        arguments.update(kwargs)
        with pytest.raises(ValueError):
            ClearCorridorContext(**arguments)
