"""Complete native Master70 append, including its actual original runtime import."""

from __future__ import annotations

import gzip
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_population import ReplayPopulationAttribute, ReplayPopulationMaster
from vantage.replay_production import charge_replay_production_selection
from vantage.replay_production_append import finish_replay_master70_queue_append
from vantage.replay_production_cache import (
    ReplayProductionCacheSlot,
    cache_replay_building_unit_costs,
)
from vantage.replay_production_queue import (
    ReplayProductionQueueSlot,
    ReplayProductionQueueState,
    ReplayProductionQueueTransition,
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


def test_original_complete_caller_with_genuine_runtime_all4404_cases() -> None:
    path = Path(__file__).parent / "fixtures/native_replay_production_append_54800.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    stages: dict[str, int] = {}
    for row, native in data["rows"]:
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
        after = previous
        stage = "rejected"
        if charge.accepted_quantity:
            cache = cache_replay_building_unit_costs([master] * 4, 1, charge.resources)
            transition = stage_replay_unit_queue(
                previous, 1, charge.accepted_quantity, row[8] & 0xFFFFFFFF, cache
            )
            stage, after = transition.stage, transition.state
            if stage == "needs_unit_cast":
                # Synthetic native entries were zero except first entry+2.
                short = ((row[21] + 32768) & 0xFFFF) - 32768
                locations = ((0, short, 0, 0),) + ((0, 0, 0, 0),) * (row[20] - 1)
                if row[20] == 0:
                    locations = ()
                after = finish_replay_master70_queue_append(
                    transition, training_locations=locations
                )
                stage = "appended"
                assert native[72:77] == [1, 1, 0, 0, 1]  # Actual RAX, not a cast stub.
            else:
                assert native[72:77] == [0, 0, 0xFFFFFFFF, 0xFFFFFFFF, 0]
            assert native[12] == (row[17] + charge.accepted_quantity) & 0xFFFFFFFF
            assert native[13] == row[18] + charge.accepted_quantity
            assert native[14] == row[19] + (charge.accepted_quantity if row[13] != -1 else 0)
        else:
            assert native[:4] == [0, 1, 0, 0]
        if stage in {"merged", "appended"}:
            assert native[:3] == [0, 1, 1]
        elif stage == "needs_allocation":
            assert native[:4] == [2, 0, 0, 2]
        assert [
            after.capacity,
            after.used,
            after.units & 0xFFFFFFFF,
            after.revision,
            after.next_uid & 0xFFFFFFFF,
            after.next_uid >> 32,
        ] == native[4:10], row
        assert [v for c in after.cache for v in (c.resource_id & 0xFFFFFFFF, c.amount_bits)] == (
            native[18:24]
        )
        slots = b"".join(slot.to_raw() for slot in after.slots)
        slots += initial.to_raw() * (4 - after.capacity)
        assert list(struct.unpack("<48I", slots)) == native[24:72], row
        assert native[15] == 1 and native[17] == 0xABCDEF12
        assert previous.slots == (initial,) * row[3] and resources[0] == row[14]
        stages[stage] = stages.get(stage, 0) + 1
    assert stages == {"appended": 3396, "merged": 792, "rejected": 192, "needs_allocation": 24}


def _pending() -> ReplayProductionQueueTransition:
    slot = ReplayProductionQueueSlot(3, 7, 9, _CACHE, 22, 0, 0xABCD, b"pq", b"rs")
    state = ReplayProductionQueueState(2, 0, 3, 255, 0xFFFFFFFFFFFFFFFF, (slot,) * 2, _CACHE)
    return stage_replay_unit_queue(state, 1, 2, 0xFFFFFFFF, _CACHE)


@pytest.mark.parametrize("value", (0, 32767, -32768, -1))
def test_first_entry_bits_and_only_final_fields_change(value: int) -> None:
    pending = _pending()
    before = pending.state
    after = finish_replay_master70_queue_append(
        pending, training_locations=((-32768, value, 255, 0xFFFFFFFF), (1, 99, 0, 0))
    )
    assert after == replace(
        before,
        used=1,
        units=5,
        revision=0,
        slots=(replace(before.slots[0], field_2c_bits=value & 0xFFFF), before.slots[1]),
    )
    assert after.next_uid == 0 and after.slots[0].uid == 0xFFFFFFFFFFFFFFFF
    assert after.slots[1] is before.slots[1]
    assert after.slots[0].padding_06 == b"pq" and after.slots[0].padding_2e == b"rs"
    assert pending.state is before


def test_empty_vector_writes_zero_instead_of_retaining_old_bits() -> None:
    pending = _pending()
    after = finish_replay_master70_queue_append(pending, training_locations=())
    assert pending.state.slots[0].field_2c_bits == 0xABCD
    assert after.slots[0].field_2c_bits == 0


@pytest.mark.parametrize("stage", ("merged", "needs_allocation"))
def test_other_checkpoints_are_not_completed(stage: str) -> None:
    pending = _pending()
    with pytest.raises(ValueError, match="needs_unit_cast"):
        finish_replay_master70_queue_append(
            # Deliberately test runtime rejection of another Literal stage.
            replace(pending, stage=stage),
            training_locations=(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "changes,match",
    (
        ({"flags": 0}, "flags"),
        ({"research_id": 1}, "research"),
        ({"unit_id": -1}, "unit/count"),
        ({"quantity": 0}, "quantity"),
        ({"quantity": 13}, "quantity"),
        ({"uid": 0}, "UID"),
        ({"costs": (_CACHE[2],) * 3}, "cost cache"),
    ),
)
def test_nonpending_slot_context_is_explicit(changes: dict[str, object], match: str) -> None:
    pending = _pending()
    slot = replace(pending.state.slots[0], **changes)
    bad = replace(pending, state=replace(pending.state, slots=(slot, pending.state.slots[1])))
    with pytest.raises(ValueError, match=match):
        finish_replay_master70_queue_append(bad, training_locations=())


def test_full_capacity_and_bad_count_do_not_complete() -> None:
    pending = _pending()
    for bad in (replace(pending.state, used=2), replace(pending.state, units=-1)):
        with pytest.raises(ValueError):
            finish_replay_master70_queue_append(replace(pending, state=bad), training_locations=())


@pytest.mark.parametrize(
    "entries",
    (
        ((0, 0, 0),),
        ((32768, 0, 0, 0),),
        ((0, 32768, 0, 0),),
        ((0, 0, 256, 0),),
        ((0, 0, 0, -1),),
        ([0, 0, 0, 0],),
        [(0, 0, 0, 0)],
    ),
)
def test_locations_require_actual_decoded_native_field_ranges(entries: object) -> None:
    with pytest.raises(ValueError):
        # Deliberately pass malformed runtime input outside the declared tuple type.
        finish_replay_master70_queue_append(_pending(), training_locations=entries)  # type: ignore[arg-type]
