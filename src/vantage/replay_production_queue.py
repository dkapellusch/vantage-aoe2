"""Native unit queue merge and append preparation, before RTTI/allocation.

The caller supplies accepted quantity and current unit-cost cache after charging
and tracking. A merged transition completes the original queue mutation.
Other transitions stop before the native allocator or unit dynamic cast, with
their precise partial state retained. Neither is a completed new queue entry.
Evidence: world-envelope/production-queue-commit/README.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import Literal, Self

from vantage.replay_movement_geometry import _float
from vantage.replay_production_cache import ProductionCache, ReplayProductionCacheSlot
from vantage.replay_production_resources import _integer


def _cache(cache: ProductionCache) -> None:
    if (
        not isinstance(cache, tuple)
        or len(cache) != 3
        or any(not isinstance(slot, ReplayProductionCacheSlot) for slot in cache)
    ):
        raise ValueError("production cache must contain three native cache slots")


def _short(value: int) -> int:
    return ((value + 32768) & 0xFFFF) - 32768


@dataclass(frozen=True, slots=True)
class ReplayProductionQueueSlot:
    """All48 runtime bytes; the saved36B representation has no UID or padding.

    field_2c_bits has no asserted gameplay interpretation. Preserve both native
    padding words even for unused capacity slots. Unit/research/quantity fields
    retain signed16 bits independently; no mutual-exclusion rule is invented.
    """

    unit_id: int
    quantity: int
    research_id: int
    costs: ProductionCache
    uid: int
    flags: int
    field_2c_bits: int = 0
    padding_06: bytes = b"\0\0"
    padding_2e: bytes = b"\0\0"

    def __post_init__(self) -> None:
        for value, label in (
            (self.unit_id, "unit ID"),
            (self.quantity, "slot quantity"),
            (self.research_id, "research ID"),
        ):
            _integer(value, -32768, 32767, label)
        _cache(self.costs)
        _integer(self.uid, 0, 0xFFFFFFFFFFFFFFFF, "queue UID")
        _integer(self.flags, 0, 0xFFFFFFFF, "queue flags")
        _integer(self.field_2c_bits, 0, 0xFFFF, "queue field2c bits")
        for padding in (self.padding_06, self.padding_2e):
            if not isinstance(padding, bytes) or len(padding) != 2:
                raise ValueError("queue padding must preserve exactly two raw bytes")

    def to_raw(self) -> bytes:
        raw = bytearray(48)
        struct.pack_into("<hhh", raw, 0, self.unit_id, self.quantity, self.research_id)
        raw[6:8] = self.padding_06
        for offset, slot in zip((8, 16, 24), self.costs, strict=True):
            struct.pack_into("<iI", raw, offset, slot.resource_id, slot.amount_bits)
        struct.pack_into("<QIH", raw, 32, self.uid, self.flags, self.field_2c_bits)
        raw[46:48] = self.padding_2e
        return bytes(raw)

    @classmethod
    def from_raw(cls, raw: bytes) -> Self:
        if not isinstance(raw, bytes) or len(raw) != 48:
            raise ValueError("runtime production slot requires exactly48 bytes")
        unit_id, quantity, research_id = struct.unpack_from("<hhh", raw)
        costs = [
            ReplayProductionCacheSlot(*struct.unpack_from("<iI", raw, offset))
            for offset in (8, 16, 24)
        ]
        uid, flags, field_2c_bits = struct.unpack_from("<QIH", raw, 32)
        return cls(
            unit_id,
            quantity,
            research_id,
            (costs[0], costs[1], costs[2]),
            uid,
            flags,
            field_2c_bits,
            raw[6:8],
            raw[46:48],
        )


@dataclass(frozen=True, slots=True)
class ReplayProductionQueueState:
    """Distinct capacity+8a0, used+8a2, units+8a4, revision+8b0 and UID+988.

    slots contains every allocated capacity entry, including unused ones.
    Counts are not recomputed from slot quantities. The next UID is supplied
    explicitly; this type does not restore or infer its saved-reader value.
    """

    capacity: int
    used: int
    units: int
    revision: int
    next_uid: int
    slots: tuple[ReplayProductionQueueSlot, ...]
    cache: ProductionCache

    def __post_init__(self) -> None:
        _integer(self.capacity, 0, 32767, "queue capacity")
        _integer(self.used, 0, self.capacity, "used queue entries")
        _integer(self.units, -32768, 32767, "queued unit count")
        _integer(self.revision, 0, 255, "queue revision")
        _integer(self.next_uid, 0, 0xFFFFFFFFFFFFFFFF, "next queue UID")
        if (
            not isinstance(self.slots, tuple)
            or len(self.slots) != self.capacity
            or any(not isinstance(slot, ReplayProductionQueueSlot) for slot in self.slots)
        ):
            raise ValueError("queue slots must retain every allocated capacity entry")
        _cache(self.cache)


@dataclass(frozen=True, slots=True)
class ReplayProductionQueueTransition:
    stage: Literal["merged", "needs_allocation", "needs_unit_cast"]
    state: ReplayProductionQueueState


def stage_replay_unit_queue(
    state: ReplayProductionQueueState,
    unit_id: int,
    accepted_quantity: int,
    flags: int,
    cache: ProductionCache,
) -> ReplayProductionQueueTransition:
    """Native1412846b0 after accepted charge/cache/tracker callbacks.

    Quantity must be a positive already accepted count within the15-unit bound.
    Variant/RNG selection, charging, population and tracker mutation happen
    before this transition and are not performed here. cache must be the exact
    current unit output from cache_replay_building_unit_costs with research=-1;
    master/resource inputs must remain unchanged through the native second
    cache call. No intervening optional telemetry effect is modeled.

    Merge checks only the last used slot: unit ID, exact u32 flags, exact i32
    cost IDs and ordered f32 equality. Signed zeros compare equal; every NaN
    prevents merge. Research ID and field2c are not part of this unit predicate.
    Merge wraps signed16 quantities/counts and byte revision, retaining used,
    capacity, UID, padding and every other slot byte.

    If capacity is full, retain the cache update and stop before allocation.
    Otherwise fill the existing unused slot, assign/increment UID with u64
    wrapping and stop before the real native dynamic cast. At that checkpoint
    used/units/revision/field2c have not changed. A later successful cast or
    allocator must be modeled separately; no fallback success is invented.
    """
    _integer(unit_id, 0, 32767, "selected unit ID")
    _integer(accepted_quantity, 1, 32767, "accepted unit quantity")
    _integer(flags, 0, 0xFFFFFFFF, "requested unit flags")
    if not 0 <= state.units < 15 or accepted_quantity > 15 - state.units:
        raise ValueError("accepted quantity is outside the native15-unit queue bound")
    _cache(cache)
    updated = replace(state, cache=cache)
    if state.used > 0:
        last = state.slots[state.used - 1]
        same = (
            last.unit_id == unit_id
            and last.flags == flags
            and all(
                a.resource_id == b.resource_id and _float(a.amount_bits) == _float(b.amount_bits)
                for a, b in zip(cache, last.costs, strict=True)
            )
        )
        if same:
            slots = list(state.slots)
            slots[state.used - 1] = replace(
                last, quantity=_short(last.quantity + accepted_quantity)
            )
            return ReplayProductionQueueTransition(
                "merged",
                replace(
                    updated,
                    units=_short(state.units + accepted_quantity),
                    revision=(state.revision + 1) & 255,
                    slots=tuple(slots),
                ),
            )
    if state.capacity <= state.used:
        return ReplayProductionQueueTransition("needs_allocation", updated)
    slots = list(state.slots)
    slots[state.used] = replace(
        slots[state.used],
        unit_id=unit_id,
        quantity=accepted_quantity,
        research_id=-1,
        costs=cache,
        uid=state.next_uid,
        flags=flags,
    )
    return ReplayProductionQueueTransition(
        "needs_unit_cast",
        replace(updated, next_uid=(state.next_uid + 1) & 0xFFFFFFFFFFFFFFFF, slots=tuple(slots)),
    )
