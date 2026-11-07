"""Original saved lobby mappings and explicit native resolver branch contexts."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_command_players import (
    ReplayCommandPlayerBinding,
    ReplayCommandPlayerError,
    ReplayCommandPlayerSlot,
    ReplayCommandPlayerTable,
    initial_replay_command_players,
)
from vantage.replay_file_header import read_file_header


@pytest.fixture(scope="module")
def saved_options():
    fixture = Path(__file__).parent / "fixtures/native_saved_file_headers_54800.json.gz"
    return {
        c["sample"]: read_file_header(SaveReader(bytes.fromhex(c["raw_hex"]))).options
        for c in json.loads(gzip.decompress(fixture.read_bytes()))["cases"]
    }


@pytest.mark.parametrize(("sample", "active"), [("3p", 3), ("6p", 6)])
def test_original_headers_bind_active_slots_and_retain_inactive_invalid_indices(
    saved_options, sample, active
):
    options = saved_options[sample]
    table = initial_replay_command_players(options, active + 1)
    assert table.descriptor_slots == tuple(range(8))
    for wire in range(1, active + 1):
        assert table.resolve_non_gaia(wire) == ReplayCommandPlayerBinding(wire, wire - 1, wire)
    assert table.players[0].humanity == 2
    assert [p.humanity for p in table.players[1:active]] == [4] * (active - 1)
    for wire in range(active + 1, 9):
        assert table.players[wire - 1] == ReplayCommandPlayerSlot(1, 0xFFFFFFFF)
        assert table.resolve_non_gaia(wire) is None


def test_descriptor_slot_and_world_index_are_independent_and_duplicates_are_allowed():
    players = (ReplayCommandPlayerSlot(2, 0xFFFFFFFF),) * 7 + (ReplayCommandPlayerSlot(3, 2),)
    table = ReplayCommandPlayerTable(players, (True, False, True), (7, 7, 0, 1, 2, 3, 4, 5))
    assert table.resolve_non_gaia(1) == ReplayCommandPlayerBinding(1, 7, 2)
    assert table.resolve_non_gaia(2) == ReplayCommandPlayerBinding(2, 7, 2)
    assert table.resolve_non_gaia(3) is None
    assert replace(table, world_player_present=(True, True, False)).resolve_non_gaia(1) is None


@pytest.mark.parametrize("humanity", [0, 1, 5, 0xFFFFFFFF])
def test_inactive_humanity_has_no_binding(humanity):
    table = ReplayCommandPlayerTable((ReplayCommandPlayerSlot(humanity, 0),) * 8, (True,))
    assert table.resolve_non_gaia(1) is None


@pytest.mark.parametrize("humanity", [2, 3, 4])
def test_single_complete_vector_entry_is_sufficient_and_active_slot_can_reference_zero(humanity):
    table = ReplayCommandPlayerTable((ReplayCommandPlayerSlot(humanity, 0),) * 8, (True,))
    assert table.resolve_non_gaia(8) == ReplayCommandPlayerBinding(8, 7, 0)


@pytest.mark.parametrize("world", [None, (), (False,)])
def test_null_world_empty_vector_and_null_player_each_have_no_binding(world):
    table = ReplayCommandPlayerTable((ReplayCommandPlayerSlot(2, 0),) * 8, world)
    assert table.resolve_non_gaia(1) is None


@pytest.mark.parametrize("index", [1, 8, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFE, 0xFFFFFFFF])
def test_unsigned_world_index_guard_does_not_wrap_or_use_negative_python_indexing(index):
    table = ReplayCommandPlayerTable((ReplayCommandPlayerSlot(2, index),) * 8, (True,))
    assert table.resolve_non_gaia(1) is None


@pytest.mark.parametrize("selector", [False, True, -1, 0, 9, 255, 256, 1.0, "1", None])
def test_gaia_and_unsafe_or_nonwire_selectors_are_explicitly_unsupported(selector):
    table = ReplayCommandPlayerTable((ReplayCommandPlayerSlot(2, 0),) * 8, (True,))
    with pytest.raises(ReplayCommandPlayerError) as caught:
        table.resolve_non_gaia(selector)
    assert caught.value.code == "selector"


@pytest.mark.parametrize("word", [False, -1, 0x100000000, 1.0])
def test_native_metadata_requires_exact_unsigned_words(word):
    with pytest.raises(ReplayCommandPlayerError, match="humanity"):
        ReplayCommandPlayerSlot(word, 0)
    with pytest.raises(ReplayCommandPlayerError, match="world player index"):
        ReplayCommandPlayerSlot(2, word)


def test_unrestored_lobby_slot_is_unknown_even_if_world_is_absent(saved_options):
    options = saved_options["3p"]
    partial = replace(options, max_players_for_lobby=1, players=options.players[:1])
    table = initial_replay_command_players(partial, 0)
    assert table.resolve_non_gaia(1) is None
    assert table.players[1:] == (None,) * 7
    with pytest.raises(ReplayCommandPlayerError) as caught:
        table.resolve_non_gaia(2)
    assert caught.value.code == "unrestored_slot"


@pytest.mark.parametrize(
    "changes",
    [
        {"players": ()},
        {"players": [None] * 8},
        {"players": (0,) * 8},
        {"descriptor_slots": tuple(range(7))},
        {"descriptor_slots": (True,) * 8},
        {"descriptor_slots": (8,) * 8},
        {"world_player_present": [True]},
        {"world_player_present": (1,)},
    ],
)
def test_malformed_explicit_contexts_fail_before_lookup(changes):
    table = ReplayCommandPlayerTable((ReplayCommandPlayerSlot(2, 0),) * 8, (True,))
    with pytest.raises(ReplayCommandPlayerError):
        replace(table, **changes)


def test_saved_factory_checks_slot_order_capacity_profile_signed_width_and_count(saved_options):
    options = saved_options["3p"]
    for value in (
        replace(options, version_word=0),
        replace(options, max_players_for_lobby=7),
        replace(options, players=tuple(reversed(options.players))),
        replace(options, players=(replace(options.players[0], version=14), *options.players[1:])),
        replace(
            options,
            players=(
                replace(options.players[0], world_player_index=0xFFFFFFFF),
                *options.players[1:],
            ),
        ),
    ):
        with pytest.raises(ReplayCommandPlayerError):
            initial_replay_command_players(value, 4)
    for count in (True, -1, 0x10000, 4.0):
        with pytest.raises(ReplayCommandPlayerError):
            initial_replay_command_players(options, count)
    # Signed wire bits other than -1 remain unsigned out-of-range metadata.
    changed = replace(
        options, players=(replace(options.players[0], world_player_index=-2), *options.players[1:])
    )
    table = initial_replay_command_players(changed, 4)
    assert table.players[0].world_player_index == 0xFFFFFFFE
    assert table.resolve_non_gaia(1) is None
