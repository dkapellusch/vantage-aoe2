"""Preallocated kind3/5 legacy index mutation, independent of modern occupancy.

The admitted profile is an explicitly initialized six-level index, modern roots
disabled, finite binary32 inputs and available record/bucket capacity. Native
141122240/141121960/141121110 are independently checked by2,120 original-code
operations in world-envelope/legacy-contact-mutation/. This does not invoke
the entity setter, execute virtual610, allocate memory or initialize a world.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from .replay_legacy_contacts import _finite
from .replay_legacy_query import (
    LegacyQueryIndex,
    LegacyQueryLevel,
    LegacyQueryRecord,
    UnsupportedLegacyQuery,
)
from .replay_movement_geometry import _float, _op


class UnsupportedLegacyMutation(ValueError):
    """The state or operation requires a native branch outside this profile."""


def _integer(value: int, low: int, high: int, label: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in[{low},{high}]")


def _kind(value: int) -> None:
    if type(value) is not int or value not in (3, 5):
        raise UnsupportedLegacyMutation("legacy mutation requires current master kind3 or5")


@dataclass(frozen=True, slots=True)
class LegacyMutationRecord:
    """A stable nonzero token and all64 native bytes, including stale payload.

    Raw qwords+8/+10 contain explicit object/free-record tokens, never inferred
    process pointers. Free records may retain arbitrary old headers/payload.
    """

    token: int
    raw: bytes

    def __post_init__(self) -> None:
        _integer(self.token, 1, 0xFFFFFFFFFFFFFFFF, "legacy record token")
        if not isinstance(self.raw, bytes) or len(self.raw) != 64:
            raise ValueError("legacy record must preserve exactly64 immutable bytes")


@dataclass(frozen=True, slots=True)
class LegacyMutationBucket:
    """Used count and every preallocated slot, preserving stale tail tokens."""

    used: int
    slots: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.slots, tuple) or len(self.slots) > 8192:
            raise ValueError("legacy bucket requires at most8192 immutable capacity slots")
        _integer(self.used, 0, len(self.slots), "legacy used bucket count")
        for token in self.slots:
            _integer(token, 0, 0xFFFFFFFFFFFFFFFF, "legacy bucket slot token")


@dataclass(frozen=True, slots=True)
class LegacyMutationObject:
    token: int
    object_id: int
    record_token: int

    def __post_init__(self) -> None:
        _integer(self.token, 1, 0xFFFFFFFFFFFFFFFF, "legacy object token")
        _integer(self.object_id, -(1 << 31), (1 << 31) - 1, "legacy object ID")
        _integer(self.record_token, 0, 0xFFFFFFFFFFFFFFFF, "legacy object record link")


@dataclass(frozen=True, slots=True)
class LegacyMutationState:
    """Explicit initialized state; no capacity, free chain or links are inferred.

    Every record belongs either to one object's active bucket row or to the
    declared free chain. Stale bucket tails and free-record payload remain raw.
    Construction validates the whole state; per-operation registry work does
    not copy or revalidate all buckets. snapshot() pays that explicit cost.
    """

    width: int
    height: int
    lookup_words: tuple[int, ...]
    levels: tuple[LegacyQueryLevel, ...]
    buckets: tuple[LegacyMutationBucket, ...]
    records: tuple[LegacyMutationRecord, ...]
    objects: tuple[LegacyMutationObject, ...]
    free_head: int
    free_count: int
    modern_enabled: bool

    def __post_init__(self) -> None:
        if type(self.modern_enabled) is not bool:
            raise ValueError("legacy modern-enabled profile must be an explicit boolean")
        if self.modern_enabled:
            raise UnsupportedLegacyMutation("combined modern index mutation is not implemented")
        # Reuse the collector's initialized lookup/descriptor contract unchanged.
        try:
            LegacyQueryIndex(
                self.width, self.height, self.lookup_words, self.levels, ((),) * 1365, ()
            )
        except UnsupportedLegacyQuery as error:
            raise UnsupportedLegacyMutation(str(error)) from error
        if (
            not isinstance(self.buckets, tuple)
            or len(self.buckets) != 1365
            or any(not isinstance(bucket, LegacyMutationBucket) for bucket in self.buckets)
            or sum(len(bucket.slots) for bucket in self.buckets) > 65536
        ):
            raise ValueError("legacy mutation requires1365 buckets and at most65536 slots")
        for values, kind in (
            (self.records, LegacyMutationRecord),
            (self.objects, LegacyMutationObject),
        ):
            if (
                not isinstance(values, tuple)
                or len(values) > 8192
                or any(not isinstance(value, kind) for value in values)
            ):
                raise ValueError("legacy mutation requires at most8192 typed immutable entries")
        records = {record.token: record.raw for record in self.records}
        objects = {obj.token: obj for obj in self.objects}
        if len(records) != len(self.records) or len(objects) != len(self.objects):
            raise ValueError("legacy record/object tokens must each be distinct")
        if records.keys() & objects.keys():
            raise ValueError("legacy object and record token domains must not overlap")
        _integer(self.free_head, 0, 0xFFFFFFFFFFFFFFFF, "legacy free-record head")
        _integer(self.free_count, 0, len(records), "legacy free-record count")
        free: set[int] = set()
        head = self.free_head
        while head:
            if head not in records or head in free:
                raise ValueError("legacy free chain contains an unknown token or cycle")
            free.add(head)
            head = struct.unpack_from("<Q", records[head], 0x10)[0]
        if len(free) != self.free_count:
            raise ValueError("legacy free-chain length disagrees with its native count")
        active: set[int] = set()
        for bucket_index, bucket in enumerate(self.buckets):
            for row, token in enumerate(bucket.slots[: bucket.used]):
                if token not in records or token in active or token in free:
                    raise ValueError("legacy used bucket row is unknown, duplicated or free")
                active.add(token)
                raw = records[token]
                if raw[1] not in (2, 3, 5, 11, 13):
                    raise UnsupportedLegacyMutation("legacy external record kind is unproved")
                geometry = 2 if raw[1] in (3, 5) else 3
                if (
                    raw[0] != geometry
                    or struct.unpack_from("<i", raw, 4)[0] != bucket_index
                    or (struct.unpack_from("<i", raw, 0x1C)[0] != row)
                ):
                    raise ValueError("legacy record geometry/bucket/row disagrees with its link")
                object_token = struct.unpack_from("<Q", raw, 8)[0]
                if object_token not in objects or objects[object_token].record_token != token:
                    raise ValueError("legacy active record disagrees with its object link")
                if objects[object_token].object_id != struct.unpack_from("<i", raw, 0x18)[0]:
                    raise ValueError("legacy record ID disagrees with its object")
                LegacyQueryRecord(
                    token,
                    raw[1],
                    raw[3],
                    objects[object_token].object_id,
                    struct.unpack_from("<4I", raw, 0x20),
                )
        linked = [obj.record_token for obj in self.objects if obj.record_token]
        if len(linked) != len(set(linked)) or set(linked) != active:
            raise ValueError("legacy object links must identify every active record once")
        if active | free != records.keys():
            raise ValueError("legacy records must all be active or on the explicit free chain")


class LegacyContactRegistry:
    """Mutable, single-threaded legacy index with explicit immutable checkpoints.

    Tokens are stable identities. This registry does not own entity positions
    or masters: refresh receives the already committed position and current
    admitted master fields. Unsupported branch guards run before mutation;
    their rejection does not claim the native allocator path is transactional.
    """

    def __init__(self, state: LegacyMutationState) -> None:
        if not isinstance(state, LegacyMutationState):
            raise ValueError("legacy registry requires a validated explicit state")
        self._initial = state
        self._records = {record.token: bytearray(record.raw) for record in state.records}
        self._objects = {obj.token: obj for obj in state.objects}
        self._links = {obj.token: obj.record_token for obj in state.objects}
        self._slots = [list(bucket.slots) for bucket in state.buckets]
        self._used = [bucket.used for bucket in state.buckets]
        self._free_head, self._free_count = state.free_head, state.free_count

    def _object(self, token: int) -> LegacyMutationObject:
        _integer(token, 1, 0xFFFFFFFFFFFFFFFF, "legacy object token")
        if token not in self._objects:
            raise ValueError("legacy mutation requires an explicitly registered object")
        return self._objects[token]

    def _unlink(self, token: int) -> None:
        raw = self._records[token]
        bucket, row = struct.unpack_from("<i", raw, 4)[0], struct.unpack_from("<i", raw, 0x1C)[0]
        count, slots = self._used[bucket], self._slots[bucket]
        if row + 1 < count:
            slots[row] = slots[count - 1]
            struct.pack_into("<i", self._records[slots[row]], 0x1C, row)
        self._used[bucket] -= 1

    def refresh(
        self,
        object_token: int,
        *,
        kind: int,
        enabled: bool,
        position_bits: tuple[int, int],
        radius_bits: tuple[int, int],
    ) -> bool:
        """Native141122240 admitted kind3/5 legacy branch; return its defined AL.

        Coordinates/radii are bounded finite binary32 words with absolute
        value<=4096 and nonnegative radii, under default nearest-even MXCSR.
        Native truncation/clipping affects bucket selection only; raw bounds
        retain their exact words. Available record/bucket capacity is required.
        Existing flags, unused fields and stale bucket tails survive.
        """
        obj = self._object(object_token)
        _kind(kind)
        if type(enabled) is not bool or not enabled:
            raise UnsupportedLegacyMutation("legacy refresh requires explicit enabled=True")
        for pair in (position_bits, radius_bits):
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("legacy position/radius requires two immutable binary32 words")
            for word in pair:
                _finite(word, 4096)
        if any(_float(word) < 0 for word in radius_bits):
            raise ValueError("legacy master radii must be nonnegative")
        x, y = position_bits
        rx, ry = radius_bits
        bounds = _op(x, rx, "-"), _op(y, ry, "-"), _op(rx, x, "+"), _op(ry, y, "+")
        # These admitted finite bounds fit CVTTSS2SI32; no overflow normalization.
        low_x, low_y, high_x, high_y = (
            max(0, min(extent - 1, int(_float(word))))
            for word, extent in zip(
                bounds, (self._initial.width, self._initial.height) * 2, strict=True
            )
        )
        level_index = min(
            self._initial.lookup_words[(low_x ^ high_x) >> 3],
            self._initial.lookup_words[(low_y ^ high_y) >> 3],
        )
        level = self._initial.levels[level_index]
        bucket = (
            ((low_y >> level.coordinate_shift) << level.ordinal)
            + level.base_index
            + (low_x >> level.coordinate_shift)
        )
        token = self._links[object_token]
        old_bucket = struct.unpack_from("<i", self._records[token], 4)[0] if token else -1
        if bucket != old_bucket and self._used[bucket] >= len(self._slots[bucket]):
            raise UnsupportedLegacyMutation("legacy destination bucket needs unported growth")
        if not token and not self._free_count:
            raise UnsupportedLegacyMutation("legacy record pool needs unported allocation")
        if not token:
            token = self._free_head
            raw = self._records[token]
            self._free_head = struct.unpack_from("<Q", raw, 0x10)[0]
            self._free_count -= 1
            self._links[object_token] = token
            struct.pack_into("<H", raw, 2, 0x100)
            struct.pack_into("<QQi", raw, 8, object_token, 0, obj.object_id)
            raw[1] = 0
        else:
            raw = self._records[token]
        if bucket != old_bucket:
            if old_bucket >= 0:
                self._unlink(token)
            row = self._used[bucket]
            self._slots[bucket][row] = token
            self._used[bucket] += 1
        else:
            row = struct.unpack_from("<i", raw, 0x1C)[0]
        raw[0], raw[1] = 2, kind
        struct.pack_into("<i", raw, 4, bucket)
        struct.pack_into("<i", raw, 0x1C, row)
        struct.pack_into("<4I", raw, 0x20, *bounds)
        if kind == 5:
            struct.pack_into("<4I", raw, 0x30, x, y, rx, _op(rx, rx, "*"))
        return True

    def remove(self, object_token: int, *, kind: int) -> bool:
        """Native141121960 ordinary kind3/5 removal; F2 is not an admission test.

        Null record links returnFalse. Removal preserves the record payload,
        repairs a swapped last row, leaves the stale bucket tail and pushes
        the record onto the free chain before clearing the object's link.
        """
        self._object(object_token)
        _kind(kind)
        token = self._links[object_token]
        if not token:
            return False
        self._unlink(token)
        struct.pack_into("<Q", self._records[token], 0x10, self._free_head)
        self._free_head = token
        self._free_count += 1
        self._links[object_token] = 0
        return True

    def action_end_flags(self, object_token: int, *, mode: Literal[0, 16]) -> None:
        """Native141121110 with explicit mode0/10 and modern index disabled.

        The caller must obtain mode from the separate actual virtual610 phase.
        This helper does not infer it from motion or invoke the action wrapper.
        The original entry is void; no RAX result is invented.
        """
        self._object(object_token)
        if type(mode) is not int or mode not in (0, 16):
            raise UnsupportedLegacyMutation("legacy action-end mode must be explicit0 or0x10")
        token = self._links[object_token]
        if token:
            raw = self._records[token]
            raw[3] = (raw[3] & 15) | mode

    def snapshot(self) -> LegacyMutationState:
        """Copy and validate all record/bucket capacity bytes for seek/oracle use."""
        initial = self._initial
        return LegacyMutationState(
            initial.width,
            initial.height,
            initial.lookup_words,
            initial.levels,
            tuple(
                LegacyMutationBucket(used, tuple(slots))
                for used, slots in zip(self._used, self._slots, strict=True)
            ),
            tuple(
                LegacyMutationRecord(record.token, bytes(self._records[record.token]))
                for record in initial.records
            ),
            tuple(
                LegacyMutationObject(obj.token, obj.object_id, self._links[obj.token])
                for obj in initial.objects
            ),
            self._free_head,
            self._free_count,
            initial.modern_enabled,
        )

    def query_index_snapshot(self, *, callback_outputs_independent: bool) -> LegacyQueryIndex:
        """Explicit full projection cost; never required by a position refresh.

        The caller separately proves the collector's native callback outputs
        independent before using a numeric-only projection. True records that
        precondition; this method does not establish it or invoke callbacks.
        Only used ordered links survive into the existing query representation.
        """
        if type(callback_outputs_independent) is not bool or not callback_outputs_independent:
            raise UnsupportedLegacyMutation("legacy query requires callback output independence")
        state = self.snapshot()
        active = {obj.record_token for obj in state.objects if obj.record_token}
        records = tuple(
            LegacyQueryRecord(
                record.token,
                record.raw[1],
                record.raw[3],
                struct.unpack_from("<i", record.raw, 0x18)[0],
                struct.unpack_from("<4I", record.raw, 0x20),
            )
            for record in state.records
            if record.token in active
        )
        ordinals = {record.token: ordinal for ordinal, record in enumerate(records)}
        return LegacyQueryIndex(
            state.width,
            state.height,
            state.lookup_words,
            state.levels,
            tuple(
                tuple(ordinals[token] for token in bucket.slots[: bucket.used])
                for bucket in state.buckets
            ),
            records,
        )
