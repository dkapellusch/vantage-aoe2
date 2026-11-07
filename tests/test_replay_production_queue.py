"""Original full-return merge and exact pre-cast/pre-allocation queue state."""

from __future__ import annotations

import gzip
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_population import ReplayPopulationAttribute, ReplayPopulationMaster
from vantage.replay_production import charge_replay_production_selection
from vantage.replay_production_cache import (
    ReplayProductionCacheSlot,
    cache_replay_building_unit_costs,
)
from vantage.replay_production_queue import (
    ReplayProductionQueueSlot,
    ReplayProductionQueueState,
    stage_replay_unit_queue,
)
from vantage.replay_production_resources import ReplayProductionMaster, ReplayUnitCost

_CACHE = (
    ReplayProductionCacheSlot(0, 0x42480000),
    ReplayProductionCacheSlot(-1, 0),
    ReplayProductionCacheSlot(-1, 0),
)


def _initial_slot(row: list[int]) -> ReplayProductionQueueSlot:
    raw = bytearray(b"\xa5" * 48)
    struct.pack_into("<hhh", raw, 0, row[4], row[5], row[6])
    struct.pack_into("<Q", raw, 32, 0x123456789ABCDEF0)
    struct.pack_into("<I", raw, 40, row[7] & 0xFFFFFFFF)
    values = [0, 0x42480000, 0xFFFFFFFF, 0x80000000 if row[9] == 1 else 0, 0xFFFFFFFF, 0]
    change = {
        2: (0, 1),
        3: (1, 0x42480001),
        4: (1, 0x7FC01234),
        5: (3, 0x7FC01234),
        6: (5, 0x7F801234),
    }.get(row[9])
    if change is not None:
        values[change[0]] = change[1]
    struct.pack_into("<6I", raw, 8, *values)
    return ReplayProductionQueueSlot.from_raw(bytes(raw))


def test_original_whole_caller_positive_quantity_queue_states() -> None:
    path = Path(__file__).parent / "fixtures/native_replay_production_queue_54800.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    checked = rejected = unported_nonpositive = 0
    stages: dict[str, int] = {}
    for row, native in data["rows"]:
        if row[0] <= 0:
            unported_nonpositive += 1
            continue
        master = ReplayProductionMaster(
            70, (ReplayUnitCost(0, 50, 1), ReplayUnitCost(-1, 0, 0), ReplayUnitCost(-1, 0, 0))
        )
        attrs = (
            ReplayPopulationAttribute(4, row[16]),
            ReplayPopulationAttribute(-1, 0),
            ReplayPopulationAttribute(-1, 0),
        )
        resources = [0x42550000 + i for i in range(576)]
        resources[0], resources[80] = row[14], row[15]
        charge = charge_replay_production_selection(
            [master] * 4, [ReplayPopulationMaster(70, attrs)] * 4, 1, row[0], row[1], resources
        )
        assert [charge.resources[0], charge.resources[80]] == native[10:12], row
        initial = _initial_slot(row)
        previous = ReplayProductionQueueState(
            row[3],
            row[2],
            row[1],
            row[12],
            row[10] | (row[11] << 32),
            (initial,) * row[3],
            (ReplayProductionCacheSlot(-1515870811, 0xA5A5A5A5),) * 3,
        )
        if not charge.accepted_quantity:
            assert native[:4] == [0, 1, 0, 0]
            assert native[4:10] == [row[3], row[2], row[1], row[12], row[10], row[11]]
            rejected += 1
            continue
        cache = cache_replay_building_unit_costs([master] * 4, 1, charge.resources)
        transition = stage_replay_unit_queue(
            previous, 1, charge.accepted_quantity, row[8] & 0xFFFFFFFF, cache
        )
        stage = {0: "merged", 1: "needs_unit_cast", 2: "needs_allocation"}[native[0]]
        assert transition.stage == stage, row
        stages[stage] = stages.get(stage, 0) + 1
        after = transition.state
        header = [
            after.capacity,
            after.used,
            after.units & 0xFFFFFFFF,
            after.revision,
            after.next_uid & 0xFFFFFFFF,
            after.next_uid >> 32,
        ]
        assert header == native[4:10], row
        assert [v for c in after.cache for v in (c.resource_id & 0xFFFFFFFF, c.amount_bits)] == (
            native[18:24]
        )
        # Every runtime byte, including unused capacity, UID, field2c and both
        # padding words. Physically backed outside-capacity fixture tails stay
        # unchanged at the allocation checkpoint.
        slots = b"".join(slot.to_raw() for slot in after.slots)
        slots += initial.to_raw() * (4 - after.capacity)
        assert list(struct.unpack("<48I", slots)) == native[24:], row
        assert native[12] == (row[17] + charge.accepted_quantity) & 0xFFFFFFFF
        assert native[13] == row[18] + charge.accepted_quantity
        assert native[14] == row[19] + (charge.accepted_quantity if row[13] != -1 else 0)
        assert native[15] == 1 and native[17] == 0xABCDEF12
        assert previous.slots == (initial,) * row[3]
        assert resources[0] == row[14] and resources[80] == row[15]
        checked += 1
    assert checked == 1157 and rejected == 96 and unported_nonpositive == 378
    assert stages == {"needs_unit_cast": 933, "merged": 218, "needs_allocation": 6}


def _state(*, capacity: int = 2, used: int = 1) -> ReplayProductionQueueState:
    slot = ReplayProductionQueueSlot(1, 32767, 17, _CACHE, 99, 0xFFFFFFFF, 0xABCD, b"pq", b"rs")
    return ReplayProductionQueueState(
        capacity, used, 0, 255, 0xFFFFFFFFFFFFFFFF, (slot,) * capacity, _CACHE
    )


def test_merge_wraps_only_quantity_units_revision_and_ignores_research_field() -> None:
    before = _state(capacity=1)
    result = stage_replay_unit_queue(before, 1, 2, 0xFFFFFFFF, _CACHE)
    assert result.stage == "merged"
    assert result.state == replace(
        before, units=2, revision=0, slots=(replace(before.slots[0], quantity=-32767),)
    )
    assert result.state.used == result.state.capacity == 1


@pytest.mark.parametrize("nan", (0x7FC01234, 0x7F801234, 0xFFC05678))
def test_nan_cost_never_merges(nan: int) -> None:
    before = _state()
    cache = (ReplayProductionCacheSlot(0, nan), _CACHE[1], _CACHE[2])
    old = replace(before.slots[0], costs=cache)
    before = replace(before, slots=(old, before.slots[1]))
    assert stage_replay_unit_queue(before, 1, 1, 0xFFFFFFFF, _CACHE).stage == "needs_unit_cast"


def test_signed_zero_costs_compare_equal() -> None:
    before = _state()
    old_costs = (_CACHE[0], ReplayProductionCacheSlot(-1, 0x80000000), _CACHE[2])
    before = replace(before, slots=(replace(before.slots[0], costs=old_costs), before.slots[1]))
    after = stage_replay_unit_queue(before, 1, 1, 0xFFFFFFFF, _CACHE)
    assert after.stage == "merged"
    assert after.state.slots[0].costs == old_costs  # Preserve old -0 bits on merge.


def test_append_stops_before_cast_and_preserves_unwritten_bits() -> None:
    before = _state()
    result = stage_replay_unit_queue(before, 2, 3, 0x80000000, _CACHE)
    assert result.stage == "needs_unit_cast"
    after = result.state
    assert (after.used, after.units, after.revision, after.next_uid) == (1, 0, 255, 0)
    assert after.slots[0] is before.slots[0]
    assert after.slots[1] == replace(
        before.slots[1],
        unit_id=2,
        quantity=3,
        research_id=-1,
        costs=_CACHE,
        uid=0xFFFFFFFFFFFFFFFF,
        flags=0x80000000,
    )
    assert after.slots[1].field_2c_bits == 0xABCD
    assert after.slots[1].padding_06 == b"pq" and after.slots[1].padding_2e == b"rs"


def test_allocation_checkpoint_keeps_queue_and_uid_unchanged() -> None:
    before = _state(capacity=1)
    after = stage_replay_unit_queue(before, 2, 3, 0xFFFFFFFF, _CACHE)
    assert after.stage == "needs_allocation" and after.state == before


@pytest.mark.parametrize("raw", (bytes(48), bytes([255]) * 48, bytes(range(48))))
def test_runtime_slot_preserves_all48_bytes(raw: bytes) -> None:
    assert ReplayProductionQueueSlot.from_raw(raw).to_raw() == raw


@pytest.mark.parametrize("quantity,units", ((-1, 0), (0, 0), (1, -1), (1, 15), (2, 14)))
def test_unaccepted_quantity_or_count_is_explicitly_unsupported(quantity: int, units: int) -> None:
    with pytest.raises(ValueError):
        stage_replay_unit_queue(replace(_state(), units=units), 1, quantity, 0, _CACHE)


def test_capacity_is_distinct_from_used_and_units() -> None:
    before = _state(capacity=3, used=0)
    assert len(before.slots) == 3 and before.used == before.units == 0
    with pytest.raises(ValueError, match="capacity entry"):
        replace(before, slots=before.slots[:1])
    with pytest.raises(ValueError, match="used"):
        replace(before, used=4)
    with pytest.raises(ValueError, match="exactly48"):
        ReplayProductionQueueSlot.from_raw(bytes(36))
    with pytest.raises(ValueError, match="padding"):
        replace(before.slots[0], padding_06=b"x")
