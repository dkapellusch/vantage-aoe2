"""Restore current saved queue slots in an explicit fresh-building context.

This is the state before the saved reader's later tracking reconstruction.
The original slot block and constructor stores are documented in
world-envelope/production-queue-restore/README.md; no allocator, preceding
behavior state or unknown parent callback is approximated here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace

from vantage.replay_objects import SavedBuilding
from vantage.replay_production_cache import ReplayProductionCacheSlot
from vantage.replay_production_queue import (
    ReplayProductionQueueSlot,
    ReplayProductionQueueState,
)
from vantage.replay_production_resources import _integer


@dataclass(frozen=True, slots=True)
class ReplayRestoredBuildingQueue:
    """All capacity slots plus the independent saved byte at building8a6."""

    queue: ReplayProductionQueueState
    raw_field_8a6: int


def restore_replay_fresh_building_queue(
    saved: SavedBuilding,
    *,
    save_version: int,
    preceding_slot_offset: int,
    constructor_state: ReplayProductionQueueState,
) -> ReplayRestoredBuildingQueue:
    """Map current36B saved capacity entries to48B slots before tracking.

    All three keyword preconditions are explicit, without defaults or an
    automatic world invocation. constructor_state is the known fresh queue at
    the boundary before this slot reader: capacity/used/units/revision/nextUID0,
    no slots, cache(-1,+0) three times. The caller must establish that preceding
    callbacks retained it. Only save68.9 and preceding slot offset0 are proved.

    SavedBuilding's supported parser already rejects nonempty behavior state.
    Its production_queue length is capacity8a0, independent of saved used8a2
    and total-unit8a4 words. Reinterpret those u16 words as signed16, retaining
    negative total-unit counts and all slot IDs/quantities/research/IEEE bits.
    Reject used/capacity values incompatible with the coherent queue state;
    no counts are inferred or repaired from slot contents.

    Assign UID0..capacity-1 to every capacity slot, even when used=0; nextUID
    becomes capacity. Native calloc padding remains zero. Revision and building
    cache retain the explicit fresh constructor state, while raw byte8a6 is
    returned separately. Later tracker reconstruction, partial native failures,
    allocation and other constructor/behavior/version contexts are not applied.
    """
    if save_version != 0x44E666:
        raise ValueError("unsupported saved production queue version")
    if preceding_slot_offset != 0:
        raise ValueError("saved queue requires empty prior behavior with slot offset0")
    fresh = ReplayProductionQueueState(0, 0, 0, 0, 0, (), (ReplayProductionCacheSlot(-1, 0),) * 3)
    if constructor_state != fresh:
        raise ValueError("saved queue requires the known fresh constructor state")
    if not isinstance(saved.production_queue, tuple):
        raise ValueError("saved production queue must retain every capacity entry")
    capacity = len(saved.production_queue)
    _integer(capacity, 0, 32767, "saved queue capacity")
    fields: list[int] = []
    for member, high, label in (
        (0x8A2, 0xFFFF, "used word"),
        (0x8A4, 0xFFFF, "unit-count word"),
        (0x8A6, 0xFF, "byte8a6"),
    ):
        value = saved.fields.get(member)
        if value is None:
            raise ValueError(f"missing saved queue {label}")
        _integer(value, 0, high, f"saved queue {label}")
        fields.append(value)
    used = ((fields[0] + 32768) & 0xFFFF) - 32768
    units = ((fields[1] + 32768) & 0xFFFF) - 32768
    if not 0 <= used <= capacity:
        raise ValueError("saved used count is incompatible with the coherent queue capacity")
    slots = []
    for uid, wire in enumerate(saved.production_queue):
        if not isinstance(wire, bytes) or len(wire) != 36:
            raise ValueError("saved production capacity entry requires exactly36 raw bytes")
        raw = bytearray(48)
        raw[:6] = wire[:6]
        raw[44:46] = wire[6:8]
        raw[40:44] = wire[8:12]
        raw[8:32] = wire[12:36]
        struct.pack_into("<Q", raw, 32, uid)
        slots.append(ReplayProductionQueueSlot.from_raw(bytes(raw)))
    return ReplayRestoredBuildingQueue(
        replace(
            constructor_state,
            capacity=capacity,
            used=used,
            units=units,
            slots=tuple(slots),
            next_uid=capacity,
        ),
        fields[2],
    )
