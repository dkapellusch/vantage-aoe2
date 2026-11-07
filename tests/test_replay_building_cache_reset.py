"""Whole actual cache-reset buffers and explicit profile admission boundaries."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from vantage.replay_building_cache_reset import (
    ReplayBuildingCacheResetContext,
    reset_replay_building_cache,
)

FIXTURE = Path(__file__).parent / "fixtures/native_building_cache_reset_54800.json.gz"
FIXTURE_SHA = "82700b270e08fac7cc355bb8139a4b67c962c7d904647e1580e959777156a87b"


def _cases() -> list[dict[str, Any]]:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA
    value = json.loads(gzip.decompress(raw))
    assert value["format"] == "native-building-cache-reset-v1"
    return cast(list[dict[str, Any]], value["cases"])


def _context() -> ReplayBuildingCacheResetContext:
    return ReplayBuildingCacheResetContext(1, True, True, True, 0x1F80)


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["id"]))
def test_actual_complete_native_storage(case: dict[str, Any]) -> None:
    before, after = case["before"], case["after"]
    original = bytes.fromhex(before["snapshot_raw_hex"])
    context = ReplayBuildingCacheResetContext(
        before["nil_marker"], True, True, True, before["mxcsr"]
    )
    patch = reset_replay_building_cache(
        context, field760=before["getter760_i32"], field75c_bits=before["sight75c_bits"]
    )
    actual = bytearray(original)
    # Five source-verified identity words are zero-normalized in both native
    # endpoints. Sentinel writes denote the same identity, so remain zero here.
    for at, width, value in patch.object_writes:
        actual[16 + at : 16 + at + width] = value.to_bytes(width, "little")
    for at in patch.sentinel_self_links:
        actual[1968 + at : 1968 + at + 8] = bytes(8)
    assert len(actual) == 2024
    assert bytes(actual) == bytes.fromhex(after["snapshot_raw_hex"])
    assert original == bytes.fromhex(before["snapshot_raw_hex"])
    assert before["sight75c_bits"] == after["sight75c_bits"]


def test_fixture_retains_every_native_endpoint_and_status() -> None:
    cases = _cases()
    assert len(cases) == 220
    assert {c["before"]["nil_marker"] for c in cases} == {1, 255}
    assert {c["after"]["mxcsr"] for c in cases} == {0x1F80, 0x1F81, 0x1F82, 0x1FA0, 0x1FA1, 0x1FA2}
    assert {c["before"]["counter728_raw_hex"] for c in cases} == {
        "0000000000000000",
        "5a5a5a5a5a5a5a5a",
    }


@pytest.mark.parametrize(
    "field", ["sentinel_links_self", "disjoint_backing", "building_getter_bound"]
)
def test_unresolved_storage_or_dispatch_rejects_before_returning_patch(field: str) -> None:
    with pytest.raises(ValueError):
        reset_replay_building_cache(
            replace(_context(), **{field: False}), field760=0, field75c_bits=0
        )


def test_zero_marker_requires_unimplemented_tree_destruction() -> None:
    with pytest.raises(ValueError, match="tree destruction"):
        reset_replay_building_cache(
            replace(_context(), sentinel_marker=0), field760=0, field75c_bits=0
        )


@pytest.mark.parametrize("mxcsr", [0, 0x1F00, 0x3F80, 0x5F80, 0x7F80, 0x1FC0, 0x9F80, 0x11F80])
def test_native_fp_control_changes_are_explicitly_unsupported(mxcsr: int) -> None:
    with pytest.raises(ValueError, match="MXCSR"):
        reset_replay_building_cache(
            replace(_context(), mxcsr=mxcsr), field760=-1, field75c_bits=0x7FC12345
        )


@pytest.mark.parametrize("mxcsr", [0x1F81, 0x1FA0, 0x1FBF])
def test_source_derived_sticky_status_does_not_change_scalar_results(mxcsr: int) -> None:
    # The actual native matrix began with1f80; these sticky-bit admissions
    # follow the complete source, which never reads the status bits.
    expected = reset_replay_building_cache(_context(), field760=-1, field75c_bits=0x7FC12345)
    assert (
        reset_replay_building_cache(
            replace(_context(), mxcsr=mxcsr), field760=-1, field75c_bits=0x7FC12345
        )
        == expected
    )


@pytest.mark.parametrize("word", [0x33D6BF96, 0x3F800000, 0x7F7FFFFF, 0x7F800000])
def test_ordered_greater_sight_requires_visibility_callbacks(word: int) -> None:
    with pytest.raises(ValueError, match="visibility"):
        reset_replay_building_cache(_context(), field760=0, field75c_bits=word)


@pytest.mark.parametrize("value", [True, 1.5, -2147483649, 2147483648])
def test_getter_input_requires_signed32(value: Any) -> None:
    with pytest.raises(ValueError):
        reset_replay_building_cache(_context(), field760=value, field75c_bits=0)


@pytest.mark.parametrize("value", [True, 1.5, -1, 0x100000000])
def test_sight_requires_raw_binary32_bits(value: Any) -> None:
    with pytest.raises(ValueError):
        reset_replay_building_cache(_context(), field760=0, field75c_bits=value)


@pytest.mark.parametrize(
    "field", ["sentinel_links_self", "disjoint_backing", "building_getter_bound"]
)
@pytest.mark.parametrize("value", [None, 0, 1])
def test_context_requires_explicit_bool_premises(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(_context(), **{field: value})


@pytest.mark.parametrize("value", [True, -1, 256, 1.5])
def test_marker_is_an_explicit_raw_byte(value: Any) -> None:
    with pytest.raises(ValueError):
        replace(_context(), sentinel_marker=value)


@pytest.mark.parametrize("value", [True, -1, 0x100000000, 1.5])
def test_mxcsr_is_an_explicit_raw_word(value: Any) -> None:
    with pytest.raises(ValueError):
        replace(_context(), mxcsr=value)


def test_missing_context_is_not_assigned_constructor_defaults() -> None:
    with pytest.raises(ValueError, match="context"):
        reset_replay_building_cache(None, field760=0, field75c_bits=0)
