"""Bounded native legacy segment bucket collection from explicit initialized state.

The numeric profile is flags0x90, selector-2, owner1, factor1, no temporary
terrain, and an interior query. Entity callbacks are not executed. Callers must
establish their output independence before projecting entity-linked records
into this geometry-only index. This does not rebuild a spatial index from saves.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .replay_legacy_contacts import LegacySegment, _finite, _segment, legacy_segment_contacts
from .replay_movement_geometry import _float, _op

_COLLISION_CAPACITY = 25


class UnsupportedLegacyQuery(ValueError):
    """The supplied query needs an unported native branch or initialization profile."""


@dataclass(frozen=True, slots=True)
class LegacyQueryLevel:
    ordinal: int
    coordinate_shift: int
    dimension: int
    base_index: int


@dataclass(frozen=True, slots=True)
class LegacyQueryRecord:
    token: int
    kind: int
    flags: int
    id_or_terrain: int
    bounds: LegacySegment

    def __post_init__(self) -> None:
        if type(self.token) is not int or not 0 < self.token <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("legacy record token must be a nonzero u64")
        if any(
            type(value) is not int or not 0 <= value <= 255 for value in (self.kind, self.flags)
        ):
            raise ValueError("legacy record kind/flags must be u8")
        if type(self.id_or_terrain) is not int or not -(1 << 31) <= self.id_or_terrain < (1 << 31):
            raise ValueError("legacy record ID/terrain must be signed i32")
        _segment(self.bounds)


@dataclass(frozen=True, slots=True)
class LegacyQueryIndex:
    width: int
    height: int
    lookup_words: tuple[int, ...]
    levels: tuple[LegacyQueryLevel, ...]
    buckets: tuple[tuple[int, ...], ...]
    records: tuple[LegacyQueryRecord, ...]

    def __post_init__(self) -> None:
        # The original initializer's six-level layout is independently observed
        # at200x200. All tables/order are still required caller inputs.
        if (
            any(
                type(value) is not int or not 1 <= value <= 255
                for value in (self.width, self.height)
            )
            or max(self.width, self.height) < 128
        ):
            raise UnsupportedLegacyQuery("legacy query requires the proven six-level map extent")
        if not isinstance(self.lookup_words, tuple) or len(self.lookup_words) != 64:
            raise UnsupportedLegacyQuery("legacy query requires the initialized64-word lookup")
        expected = tuple(max(-1, 5 - value.bit_length()) for value in range(64))
        if (
            any(type(value) is not int for value in self.lookup_words)
            or self.lookup_words != expected
        ):
            raise UnsupportedLegacyQuery("legacy lookup differs from the proven initialized layout")
        if not isinstance(self.levels, tuple) or len(self.levels) != 6:
            raise UnsupportedLegacyQuery("legacy query requires six initialized levels")
        offset = 0
        for ordinal, level in enumerate(self.levels):
            if not isinstance(level, LegacyQueryLevel):
                raise ValueError("legacy levels must be immutable LegacyQueryLevel values")
            fields = level.ordinal, level.coordinate_shift, level.dimension, level.base_index
            if any(type(value) is not int for value in fields) or fields != (
                ordinal,
                8 - ordinal,
                256 >> ordinal,
                offset,
            ):
                raise UnsupportedLegacyQuery("legacy level descriptor differs from initialization")
            offset += 4**ordinal
        if not isinstance(self.buckets, tuple) or len(self.buckets) != offset:
            raise ValueError("legacy index requires every ordered initialized bucket")
        if not isinstance(self.records, tuple) or len(self.records) > 8192:
            raise ValueError("legacy query requires at most8192 immutable records")
        if any(not isinstance(record, LegacyQueryRecord) for record in self.records):
            raise ValueError("legacy records must be immutable LegacyQueryRecord values")
        if len({record.token for record in self.records}) != len(self.records):
            raise ValueError("legacy record tokens must identify distinct records")
        links = 0
        for bucket in self.buckets:
            if not isinstance(bucket, tuple):
                raise ValueError("legacy bucket order must be immutable")
            links += len(bucket)
            if links > 65536 or any(
                type(index) is not int or not 0 <= index < len(self.records) for index in bucket
            ):
                raise ValueError("legacy ordered bucket references exceed the bounded record set")


@dataclass(frozen=True, slots=True)
class LegacyQueryResult:
    exhausted: bool
    collision_count: int
    collision_buffer: bytes
    contact_count: int
    contact_buffer: bytes
    manager_flag_bytes: bytes
    manager_parameter_bytes: bytes

    @property
    def collision_tokens(self) -> tuple[int, ...]:
        return tuple(
            struct.unpack_from("<Q", self.collision_buffer, i * 8)[0]
            for i in range(self.collision_count)
        )


def _query_buckets(
    index: LegacyQueryIndex, segment: LegacySegment, expand: bool, radius: int
) -> tuple[tuple[int, ...], LegacySegment]:
    x0, y0, x1, y1 = segment
    # MINSS/MAXSS both select their second operand for equality.
    left, right = (x0 if _float(x0) < _float(x1) else x1, x0 if _float(x0) > _float(x1) else x1)
    bottom, top = (y0 if _float(y0) < _float(y1) else y1, y0 if _float(y0) > _float(y1) else y1)
    bounds = left, bottom, right, top
    if expand:
        left, bottom = _op(left, radius, "-"), _op(bottom, radius, "-")
        right, top = _op(radius, right, "+"), _op(radius, top, "+")
    if not (
        0 < _float(left) <= _float(right) < index.width
        and 0 < _float(bottom) <= _float(top) < index.height
    ):
        raise UnsupportedLegacyQuery(
            "legacy border/clipped queries require the unported border helper"
        )
    low_x, low_y, high_x, high_y = (int(_float(value)) for value in (left, bottom, right, top))
    common = min(
        index.lookup_words[(low_x ^ high_x) >> 3], index.lookup_words[(low_y ^ high_y) >> 3]
    )
    selected = []
    for ordinal in range(common, -1, -1):
        level = index.levels[ordinal]
        selected.append(
            ((low_y >> level.coordinate_shift) << ordinal)
            + level.base_index
            + (low_x >> level.coordinate_shift)
        )
    for ordinal in range(common + 1, len(index.levels)):
        level = index.levels[ordinal]
        for y in range(low_y >> level.coordinate_shift, (high_y >> level.coordinate_shift) + 1):
            for x in range(low_x >> level.coordinate_shift, (high_x >> level.coordinate_shift) + 1):
                selected.append((y << ordinal) + level.base_index + x)
    return tuple(selected), bounds


def legacy_query_segment(
    index: LegacyQueryIndex,
    segment: LegacySegment,
    *,
    radius_bits: int,
    expand: bool = True,
    ignore_ids: tuple[int, ...] = (),
    ignore_enabled: bool = True,
    emit_contacts: bool = False,
    collision_buffer: bytes = bytes(_COLLISION_CAPACITY * 8),
    contact_buffer: bytes = b"",
    contact_count: int = 0,
    flags: int = 0x90,
    selector: int = -2,
    owner_id: int = 1,
    factor_bits: int = 0x3F800000,
    terrain_insertion: bool = False,
) -> LegacyQueryResult:
    """Original14111d3d0/14111d8f0 bounded numeric output and manager mutations.

    Bucket order and duplicate records survive. AL1 is exhaustion after a bucket
    reaches the fixed25-entry collision capacity. Contacts reset to zero only
    when emission is enabled and a nonempty24-byte-record buffer is supplied.
    Existing output tails and unused contact-record bytes survive unchanged.
    Returned manager bytes correspond to native+54..5b and+7c..88.
    """
    if not isinstance(index, LegacyQueryIndex):
        raise ValueError("legacy query requires an explicit validated bucket index")
    if (
        type(flags) is not int
        or flags != 0x90
        or type(selector) is not int
        or selector != -2
        or type(owner_id) is not int
        or owner_id != 1
        or type(factor_bits) is not int
        or factor_bits != 0x3F800000
        or type(terrain_insertion) is not bool
        or terrain_insertion
    ):
        raise UnsupportedLegacyQuery(
            "legacy query requires flags90/selector-2/owner1/factor1/no terrain"
        )
    if any(type(value) is not bool for value in (expand, ignore_enabled, emit_contacts)):
        raise ValueError("legacy query mode values must be booleans")
    _segment(segment)
    _finite(radius_bits, 4096)
    if _float(radius_bits) < 0:
        raise ValueError("legacy query radius must be nonnegative")
    if (
        not isinstance(ignore_ids, tuple)
        or len(ignore_ids) > 64
        or any(
            type(value) is not int or not -(1 << 31) <= value < (1 << 31) for value in ignore_ids
        )
    ):
        raise ValueError("legacy ignore IDs require at most64 immutable signed i32 values")
    if not isinstance(collision_buffer, bytes) or len(collision_buffer) != _COLLISION_CAPACITY * 8:
        raise ValueError("legacy collision buffer requires exactly25 eight-byte token slots")
    if (
        not isinstance(contact_buffer, bytes)
        or len(contact_buffer) % 24
        or len(contact_buffer) > 64 * 24
    ):
        raise ValueError("legacy contacts require at most64 complete24-byte records")
    if type(contact_count) is not int or not 0 <= contact_count <= len(contact_buffer) // 24:
        raise ValueError("legacy contact count must be inside supplied capacity")
    selected, bounds = _query_buckets(index, segment, expand, radius_bits)
    emitting = emit_contacts and bool(contact_buffer)
    count = 0 if emitting else contact_count
    contacts = contact_buffer
    collisions = bytearray(collision_buffer)
    hits = 0
    for bucket in selected:
        for ordinal in index.buckets[bucket]:
            record = index.records[ordinal]
            if not record.flags & 1:
                continue
            left, bottom, right, top = record.bounds
            if expand:
                left, bottom = _op(left, radius_bits, "-"), _op(bottom, radius_bits, "-")
                right, top = _op(radius_bits, right, "+"), _op(radius_bits, top, "+")
            if not (
                _float(bounds[0]) <= _float(right)
                and _float(left) <= _float(bounds[2])
                and _float(bounds[1]) <= _float(top)
                and _float(bottom) <= _float(bounds[3])
            ):
                continue
            if ignore_enabled and record.id_or_terrain in ignore_ids:
                continue
            if record.kind not in (2, 3, 5, 11, 13):
                continue
            result = legacy_segment_contacts(
                record.bounds,
                segment,
                shape="type5" if record.kind == 5 else "rectangle",
                expand=expand,
                expansion_bits=radius_bits,
                emit_contacts=emitting,
                entry_token=record.token,
                object_id=record.id_or_terrain,
                contact_buffer=contacts,
                contact_count=count,
            )
            count, contacts = result.contact_count, result.contact_buffer
            if result.hit:
                struct.pack_into("<Q", collisions, hits * 8, record.token)
                hits += 1
                if hits == _COLLISION_CAPACITY:
                    break
        if hits == _COLLISION_CAPACITY:
            break
    return LegacyQueryResult(
        hits == _COLLISION_CAPACITY,
        hits,
        bytes(collisions),
        count,
        contacts,
        bytes((int(emitting), 0, 1, int(expand))) + struct.pack("<I", radius_bits),
        struct.pack("<iII", -2, 1, 0x3F800000) + b"\0",
    )
