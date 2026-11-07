"""Modern saved36B queues against the unchanged original controlled reader block."""

from __future__ import annotations

import gzip
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_objects import SavedBuilding
from vantage.replay_production_cache import ReplayProductionCacheSlot
from vantage.replay_production_queue import ReplayProductionQueueState
from vantage.replay_production_restore import (
    ReplayRestoredBuildingQueue,
    restore_replay_fresh_building_queue,
)

_CACHE = (ReplayProductionCacheSlot(-1, 0),) * 3
_FRESH = ReplayProductionQueueState(0, 0, 0, 0, 0, (), _CACHE)


def _saved(raw: bytes, capacity: int) -> SavedBuilding:
    used, units, byte = struct.unpack_from("<HHB", raw, capacity * 36)
    return SavedBuilding(
        {0x8A2: used, 0x8A4: units, 0x8A6: byte},
        (),
        tuple(raw[36 * i : 36 * (i + 1)] for i in range(capacity)),
        (b"", b""),
        (0, 0),
        {},
        raw,
    )


def _restore(
    saved: SavedBuilding, constructor: ReplayProductionQueueState = _FRESH
) -> ReplayRestoredBuildingQueue:
    return restore_replay_fresh_building_queue(
        saved, save_version=0x44E666, preceding_slot_offset=0, constructor_state=constructor
    )


def test_original918_block_cases_and_explicit_fresh_supported_subset() -> None:
    path = Path(__file__).parent / "fixtures/native_replay_production_restore_54800.json.gz"
    cases = json.loads(gzip.decompress(path.read_bytes()))["cases"]
    counts = {"restored": 0, "incoherent_used": 0, "nonfresh_UID": 0, "short_IO": 0}
    for case in cases:
        row, native = case["input"], case["header"]
        raw, capacity = bytes.fromhex(row["wire_hex"]), row["capacity"]
        assert native[9] == 1  # Original DRs restored/read back before reaping.
        if not native[0]:
            # No SavedBuilding exists for these deliberately incomplete IO
            # outcomes. They do not test or imply the native error handler.
            assert len(raw) < 36 * capacity + 5 and native[10] == 1
            counts["short_IO"] += 1
            continue
        saved = _saved(raw, capacity)
        fields_before = dict(saved.fields)
        if row["initial_uid"]:
            # Native block accepts this explicit checkpoint input; the narrow
            # fresh-constructor restorer intentionally has no such profile.
            with pytest.raises(ValueError, match="fresh constructor"):
                _restore(saved, replace(_FRESH, next_uid=row["initial_uid"]))
            counts["nonfresh_UID"] += 1
        elif saved.fields[0x8A2] >= 0x8000:
            with pytest.raises(ValueError, match="used count"):
                _restore(saved)
            counts["incoherent_used"] += 1
        else:
            restored = _restore(saved)
            queue = restored.queue
            assert [
                queue.capacity,
                queue.used,
                queue.units & 0xFFFFFFFF,
                restored.raw_field_8a6,
                queue.next_uid & 0xFFFFFFFF,
                queue.next_uid >> 32,
            ] == native[1:7]
            assert b"".join(slot.to_raw() for slot in queue.slots).hex() == case["slots_hex"]
            assert [slot.uid for slot in queue.slots] == list(range(capacity))
            assert all(slot.padding_06 == slot.padding_2e == bytes(2) for slot in queue.slots)
            # Separately proven constructor defaults; the native block canary
            # verifies that the block leaves these unmodified.
            assert queue.revision == 0 and queue.cache == _CACHE
            assert native[7] == 36 * capacity + 5
            assert native[8] == 6 * capacity + 3
            counts["restored"] += 1
        assert saved.fields == fields_before
        assert saved.production_queue == tuple(raw[36 * i : 36 * (i + 1)] for i in range(capacity))
    assert counts == {"restored": 192, "incoherent_used": 192, "nonfresh_UID": 384, "short_IO": 150}


def test_capacity_slots_survive_unused_with_signed_fields_payloads_and_independent_counts() -> None:
    entry = struct.pack(
        "<hhhHIiIiIiI",
        -32768,
        -1,
        32767,
        0xFFFF,
        0x80000000,
        -2147483648,
        0x7F801234,
        -1,
        0x80000000,
        2147483647,
        0x7FC05678,
    )
    saved = _saved(entry * 2 + struct.pack("<HHB", 0, 0xFFFF, 0x80), 2)
    restored = _restore(saved)
    queue = restored.queue
    assert (queue.capacity, queue.used, queue.units, queue.next_uid) == (2, 0, -1, 2)
    assert restored.raw_field_8a6 == 0x80
    assert len(queue.slots) == 2
    for index, slot in enumerate(queue.slots):
        assert (slot.unit_id, slot.quantity, slot.research_id) == (-32768, -1, 32767)
        assert slot.field_2c_bits == 0xFFFF and slot.flags == 0x80000000
        assert slot.uid == index
        assert [(c.resource_id, c.amount_bits) for c in slot.costs] == [
            (-2147483648, 0x7F801234),
            (-1, 0x80000000),
            (2147483647, 0x7FC05678),
        ]
        assert slot.padding_06 == slot.padding_2e == bytes(2)


def test_zero_capacity_does_not_recompute_units_or_bool_normalize_raw_byte() -> None:
    saved = _saved(struct.pack("<HHB", 0, 0x8000, 0xFF), 0)
    restored = _restore(saved)
    assert restored.queue.capacity == restored.queue.used == restored.queue.next_uid == 0
    assert restored.queue.slots == () and restored.queue.units == -32768
    assert restored.raw_field_8a6 == 255


@pytest.mark.parametrize("version,offset", ((0x44E665, 0), (0x450000, 0), (0x44E666, 1)))
def test_version_and_preceding_behavior_are_required_proven_context(
    version: int, offset: int
) -> None:
    with pytest.raises(ValueError):
        restore_replay_fresh_building_queue(
            _saved(bytes(5), 0),
            save_version=version,
            preceding_slot_offset=offset,
            constructor_state=_FRESH,
        )


@pytest.mark.parametrize(
    "constructor",
    (
        replace(_FRESH, units=1),
        replace(_FRESH, revision=1),
        replace(_FRESH, next_uid=1),
        replace(_FRESH, cache=(ReplayProductionCacheSlot(-1, 0x80000000),) * 3),
        replace(_FRESH, cache=(ReplayProductionCacheSlot(0, 0),) * 3),
    ),
)
def test_unknown_parent_callback_effects_are_not_reset_to_constructor_defaults(
    constructor: ReplayProductionQueueState,
) -> None:
    with pytest.raises(ValueError, match="fresh constructor"):
        _restore(_saved(bytes(5), 0), constructor)


@pytest.mark.parametrize("used", (1, 0xFFFF, 0x8000))
def test_signed_used_count_must_fit_coherent_capacity(used: int) -> None:
    with pytest.raises(ValueError, match="used count"):
        _restore(_saved(struct.pack("<HHB", used, 0, 1), 0))


@pytest.mark.parametrize("size", (0, 35, 37, 48))
def test_each_capacity_slot_requires_exactly36_wire_bytes(size: int) -> None:
    saved = replace(_saved(bytes(5), 0), production_queue=(bytes(size),))
    with pytest.raises(ValueError, match="exactly36"):
        _restore(saved)


@pytest.mark.parametrize(
    "fields",
    (
        {},
        {0x8A2: 0, 0x8A4: 0},
        {0x8A2: -1, 0x8A4: 0, 0x8A6: 0},
        {0x8A2: 0, 0x8A4: 65536, 0x8A6: 0},
        {0x8A2: 0, 0x8A4: 0, 0x8A6: 256},
    ),
)
def test_saved_fields_require_original_u16_u16_u8_bits(fields: dict[int, int]) -> None:
    with pytest.raises(ValueError):
        _restore(replace(_saved(bytes(5), 0), fields=fields))


def test_oversized_capacity_is_explicit_and_no_entry_is_silently_dropped() -> None:
    saved = replace(_saved(bytes(5), 0), production_queue=(bytes(36),) * 32768)
    with pytest.raises(ValueError, match="capacity"):
        _restore(saved)
