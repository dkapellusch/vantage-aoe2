"""Fresh engine identities, exact saved counts and real null-slot construction."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from vantage import replay_binary
from vantage.replay_binary import SaveReader
from vantage.replay_civilization_providers import bind_replay_civilization_providers
from vantage.replay_engine_session import create_replay_engine_session
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_construction_support import count_replay_player_world_entries
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_world_player_vector import bind_replay_world_player_vector
from vantage.replay_world_prefix import SavedWorldPrefix, read_world_prefix

_GLOBAL = 0x144353698
_ROOT = Path(replay_binary.__file__).resolve().parents[2]


def _prefixes() -> tuple[SavedWorldPrefix, ...]:
    fixture = _ROOT / "tests/fixtures/native_saved_world_prefix_54800.json"
    cases = json.loads(fixture.read_text())["cases"]
    return tuple(read_world_prefix(SaveReader(bytes.fromhex(row["raw_hex"]))) for row in cases)


def _calls(
    memory: ReplayMemory,
) -> tuple[ReplayTaskRebuildCalls, list[tuple[int, tuple[int, ...]]]]:
    events: list[tuple[int, tuple[int, ...]]] = []
    routes: dict[int, ReplayTaskRebuildCalls] = {}
    runtime = memory.runtime_calls()

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        events.append((target, args))
        provider = routes.get(target, runtime)
        assert provider.call is not None
        return provider.call(target, args, data)

    calls = ReplayTaskRebuildCalls(dispatch)
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    atomics = ReplayUnitAIMapAtomics(memory.compare_exchange_u32, memory.fetch_add_u32)
    vector = bind_replay_world_player_vector(context, calls, atomics=atomics, imports=runtime)
    selector = bind_replay_civilization_providers(context, calls)
    routes.update(dict.fromkeys((0x14161DBE0, 0x1415E7D40, 0x1415E7B70, 0x141344F50), vector))
    routes[0x140FA36A0] = selector
    return calls, events


@pytest.mark.parametrize("case", [0, 1])
def test_recording_counts_allocate_real_shared_pending_slots(case: int) -> None:
    prefix = _prefixes()[case]
    memory = ReplayMemory()
    calls, events = _calls(memory)
    session = create_replay_engine_session(
        memory,
        prefix,
        version=0x44E666,
        family_descriptor=(2).to_bytes(8, "little"),
        calls=calls,
    )
    assert memory.read(_GLOBAL, 8) == session.game
    assert memory.read(session.game + 0x5C0, 8) == session.world
    assert session.wire_player_count == prefix.num_players == (4, 7)[case]
    assert memory.read(session.world + 0x6B4, 4) == session.family == 2
    begin = memory.read(session.world + 0x768, 8)
    assert memory.read(session.world + 0x770, 8) == begin + prefix.num_players * 16
    assert memory.read(session.world + 0x778, 8) == begin + prefix.num_players * 16
    assert memory.read_bytes(begin, prefix.num_players * 16) == bytes(prefix.num_players * 16)
    context = ReplayTaskRebuildStorage(session.world, memory.read, memory.write)
    assert count_replay_player_world_entries(context, session.world) == prefix.num_players
    # Construction has not happened: every count includes all still-null slots.
    # The vector binder routes its owned descendants internally.
    assert [target for target, _ in events] == [
        0x140FA36A0,
        0x14161DBE0,
        0x1402A94D0,
    ]
    for address in (
        session.game,
        session.game + 0x560,
        session.world,
        session.world + 0x6B0,
        session.world + 0x6B8,
        session.world + 0x110,
        session.world + 0xE8,
        session.world + 0x828,
    ):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(address, 1)


@pytest.mark.parametrize(("value", "tag", "expected"), [(7, 0, 7), (3, 1, 2), (2, 1, 0)])
def test_family_comes_from_actual_tagged_selector(value: int, tag: int, expected: int) -> None:
    memory = ReplayMemory()
    calls, _ = _calls(memory)
    descriptor = value.to_bytes(4, "little") + bytes([tag, 0xA5, 0xA5, 0xA5])
    session = create_replay_engine_session(
        memory,
        _prefixes()[0],
        version=0x44E666,
        family_descriptor=descriptor,
        calls=calls,
    )
    assert session.family == expected
    assert memory.read_bytes(session.game + 0x680, 8) == descriptor
    assert memory.read(session.world + 0x6B4, 4) == expected


@pytest.mark.parametrize("count", [0, 0x8000, 0xFFFF, -1, True])
def test_unsupported_signed_wire_counts_refuse_before_allocating(count: int) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match="signed WORD count"):
        create_replay_engine_session(
            memory,
            replace(_prefixes()[0], num_players=count),
            version=0x44E666,
            family_descriptor=bytes(8),
            calls=ReplayTaskRebuildCalls(None),
        )
    assert memory.snapshot() == before


@pytest.mark.parametrize("change", ["raw_count", "raw_length", "extent", "player_words"])
def test_inconsistent_prefix_refuses_before_allocating(change: str) -> None:
    prefix = _prefixes()[0]
    if change == "raw_count":
        raw = bytearray(prefix.raw)
        raw[47:49] = (3).to_bytes(2, "little")
        prefix = replace(prefix, raw=bytes(raw))
    elif change == "raw_length":
        prefix = replace(prefix, raw=prefix.raw[:-1])
    elif change == "extent":
        prefix = replace(prefix, end_offset=prefix.end_offset + 1)
    else:
        prefix = replace(prefix, player_words=prefix.player_words[:-1])
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match="coherent raw World prefix"):
        create_replay_engine_session(
            memory,
            prefix,
            version=0x44E666,
            family_descriptor=bytes(8),
            calls=ReplayTaskRebuildCalls(None),
        )
    assert memory.snapshot() == before


@pytest.mark.parametrize("version", [0, 0x44E665, 0x44E667, True])
def test_unsupported_version_refuses_before_allocating(version: int) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match=r"save68\.9"):
        create_replay_engine_session(
            memory,
            _prefixes()[0],
            version=version,
            family_descriptor=bytes(8),
            calls=ReplayTaskRebuildCalls(None),
        )
    assert memory.snapshot() == before


def test_missing_vector_retains_published_context_without_faking_success() -> None:
    memory = ReplayMemory()
    context = ReplayTaskRebuildStorage(1, memory.read, memory.write)
    zero_pairs: list[int] = []

    def missing(target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        assert target == 0x14161DBE0 and data is None
        zero_pairs.append(args[2])
        assert memory.read_bytes(args[2], 16) == bytes(16)
        raise UnresolvedReplayTaskRebuild("reached14161dbe0 is unavailable")

    calls = bind_replay_civilization_providers(context, ReplayTaskRebuildCalls(missing))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14161dbe0"):
        create_replay_engine_session(
            memory,
            _prefixes()[0],
            version=0x44E666,
            family_descriptor=(2).to_bytes(8, "little"),
            calls=calls,
        )
    game = memory.read(_GLOBAL, 8)
    world = memory.read(game + 0x5C0, 8)
    assert memory.read(world + 0x6B4, 4) == 2
    assert memory.read_bytes(world + 0x768, 24) == bytes(24)
    assert len(zero_pairs) == 1
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(zero_pairs[0], 1)
    assert memory.snapshot().regions


def test_invalid_family_reaches_real_fatal_before_publication() -> None:
    memory = ReplayMemory()
    calls, events = _calls(memory)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1408f56b0"):
        create_replay_engine_session(
            memory,
            _prefixes()[0],
            version=0x44E666,
            family_descriptor=b"\x02\0\0\0\xff\0\0\0",
            calls=calls,
        )
    assert [target for target, _ in events] == [0x140FA36A0, 0x1408F56B0]
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        memory.read(_GLOBAL, 8)


def test_fresh_lifecycle_never_replaces_a_current_engine_game() -> None:
    memory = ReplayMemory()
    calls, _ = _calls(memory)
    prefix = _prefixes()[0]
    first = create_replay_engine_session(
        memory,
        prefix,
        version=0x44E666,
        family_descriptor=bytes(8),
        calls=calls,
    )
    with pytest.raises(ReplayMemoryError, match="overlap"):
        create_replay_engine_session(
            memory,
            prefix,
            version=0x44E666,
            family_descriptor=bytes(8),
            calls=calls,
        )
    assert memory.read(_GLOBAL, 8) == first.game
    assert memory.read(first.game + 0x5C0, 8) == first.world
