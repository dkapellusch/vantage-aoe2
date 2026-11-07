"""Native-derived legacy kind2/5 effects over an explicit shared record pool.

The isolated kind2 profile matches97 original calls and full retained buffers.
The kind5 extension matches528 retained native refresh outputs;502 inputs are
actual prior checkpoints and26 are source-defined initial inputs. See the
world-envelope legacy-kind5-old-fixture-validation-v1 evidence qualifications.

Integer binary32 arithmetic preserves AABBs, kind5 circle squares, raw record
bytes, stale bucket slots and block/cursor/LIFO roles. The public kind2 context
remains unchanged. Generic isolated registration is in replay_legacy_registration.
Modern-enabled composition, actual World binding, growth and playback remain
unfinished; semantic output excludes native floating-point status.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from vantage.replay_legacy_mutation import (
    LegacyMutationBucket,
    LegacyMutationObject,
    LegacyMutationRecord,
)
from vantage.replay_legacy_query import LegacyQueryIndex, LegacyQueryLevel

_EPSILON = 0x3A83126F
_HALF_UNITS = 1 << 148


class UnsupportedLegacyKind2(ValueError):
    """A required current state or native branch is outside this profile."""


def _integer(value: int, low: int, high: int, label: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in[{low},{high}]")


def _finite(word: int, *, radius: bool = False) -> None:
    _integer(word, 0, 0xFFFFFFFF, "binary32 word")
    if word & 0x7FFFFFFF > 0x45800000:
        raise UnsupportedLegacyKind2("finite magnitudes no greater than4096 required")
    if radius and word & 0x80000000 and word & 0x7FFFFFFF:
        raise ValueError("radii must be nonnegative")


def _units(word: int) -> int:
    """An exact finite binary32 value in units of2**-149."""
    exponent, fraction = word >> 23 & 255, word & 0x7FFFFF
    value = fraction if not exponent else (fraction | 0x800000) << (exponent - 1)
    return -value if word & 0x80000000 else value


def _rounded_units(value: int, *, negative_zero: bool = False) -> int:
    sign = 0x80000000 if value < 0 or (not value and negative_zero) else 0
    magnitude = abs(value)
    if magnitude < 0x800000:
        return sign | magnitude
    shift = max(0, magnitude.bit_length() - 24)
    rounded, remainder = divmod(magnitude, 1 << shift)
    if shift:
        half = 1 << (shift - 1)
        if remainder > half or (remainder == half and rounded & 1):
            rounded += 1
        if rounded == 1 << 24:
            rounded >>= 1
            shift += 1
    exponent = shift + 1
    if exponent >= 255:
        raise UnsupportedLegacyKind2("binary32 overflow outside the finite profile")
    return sign | exponent << 23 | (rounded & 0x7FFFFF)


def _sum(left: int, right: int, *, subtract: bool = False) -> int:
    if subtract:
        right ^= 0x80000000
    return _rounded_units(
        _units(left) + _units(right),
        negative_zero=bool(left & right & 0x80000000),
    )


def _truncated(word: int) -> int:
    value = _units(word)
    return -(abs(value) >> 149) if value < 0 else value >> 149


def _fmod_half(word: int) -> int:
    # Division by the exact power-of-two0.5 leaves an exactly representable
    # binary32 remainder. fmod retains the dividend sign, including zero.
    remainder = abs(_units(word)) % _HALF_UNITS
    negative = bool(word & 0x80000000)
    return _rounded_units(-remainder if negative else remainder, negative_zero=negative)


@dataclass(frozen=True, slots=True)
class LegacyKind2Context:
    modern_enabled: bool
    genuine_empty_listener_callback: bool
    disjoint_backing: bool
    mxcsr: int

    def __post_init__(self) -> None:
        for name in ("modern_enabled", "genuine_empty_listener_callback", "disjoint_backing"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"explicit bool required for {name}")
        _integer(self.mxcsr, 0, 0xFFFFFFFF, "MXCSR")
        if self.modern_enabled or not self.genuine_empty_listener_callback:
            raise UnsupportedLegacyKind2("isolated legacy and actual empty callback required")
        if not self.disjoint_backing or self.mxcsr & ~0x3F != 0x1F80:
            raise UnsupportedLegacyKind2("disjoint backing and nearest-even controls required")


@dataclass(frozen=True, slots=True)
class LegacyKind2Pool:
    """Explicit native block cursor and returned-record LIFO, without growth.

    Blocks retain logical record identities in physical slot order. The unused
    metadata capacity and growth step are preserved, not exercised. Reserved
    records are accounted separately from active, returned and unissued slots.
    """

    blocks: tuple[tuple[int, ...], ...]
    metadata_capacity: int
    current_block: int
    next_slot: int
    free_head: int
    available: int
    growth_step: int


@dataclass(frozen=True, slots=True)
class LegacyKind2State:
    width: int
    height: int
    lookup_words: tuple[int, ...]
    levels: tuple[LegacyQueryLevel, ...]
    buckets: tuple[LegacyMutationBucket, ...]
    records: tuple[LegacyMutationRecord, ...]
    objects: tuple[LegacyMutationObject, ...]
    pool: LegacyKind2Pool
    reserved_tokens: tuple[int, ...]
    tile_words: tuple[int, ...]

    def __post_init__(self) -> None:
        LegacyQueryIndex(self.width, self.height, self.lookup_words, self.levels, ((),) * 1365, ())
        if (
            type(self.buckets) is not tuple
            or len(self.buckets) != 1365
            or any(type(b) is not LegacyMutationBucket for b in self.buckets)
            or sum(len(b.slots) for b in self.buckets) > 65536
        ):
            raise ValueError("1365 typed preallocated buckets required")
        if (
            type(self.records) is not tuple
            or len(self.records) > 16384
            or any(type(r) is not LegacyMutationRecord for r in self.records)
            or type(self.objects) is not tuple
            or len(self.objects) > 8192
            or any(type(o) is not LegacyMutationObject for o in self.objects)
        ):
            raise ValueError("at most16384 records and8192 objects required")
        records = {r.token: r.raw for r in self.records}
        objects = {o.token: o for o in self.objects}
        if (
            len(records) != len(self.records)
            or len(objects) != len(self.objects)
            or records.keys() & objects.keys()
        ):
            raise ValueError("distinct record and object identities required")
        pool = self.pool
        if (
            type(pool) is not LegacyKind2Pool
            or type(pool.blocks) is not tuple
            or not 1 <= len(pool.blocks) <= 8
            or any(type(b) is not tuple or not b for b in pool.blocks)
        ):
            raise ValueError("one to eight nonempty explicit pool blocks required")
        block_tokens = [token for block in pool.blocks for token in block]
        for token in block_tokens:
            _integer(token, 1, (1 << 64) - 1, "pool record token")
        if len(block_tokens) != len(set(block_tokens)) or set(block_tokens) != records.keys():
            raise ValueError("pool block slots must identify every record once")
        _integer(pool.metadata_capacity, len(pool.blocks), 8, "pool metadata capacity")
        _integer(pool.current_block, -1, len(pool.blocks) - 1, "current pool block")
        _integer(pool.growth_step, 0, (1 << 31) - 1, "pool growth step")
        _integer(pool.available, 0, len(records), "pool available count")
        _integer(pool.free_head, 0, (1 << 64) - 1, "pool free head")
        if pool.current_block == -1:
            _integer(pool.next_slot, 0, 0, "exhausted pool cursor")
            unissued: set[int] = set()
        else:
            _integer(
                pool.next_slot, 0, len(pool.blocks[pool.current_block]) - 1, "next unissued slot"
            )
            unissued = set(pool.blocks[pool.current_block][pool.next_slot :])
            unissued.update(
                token for block in pool.blocks[pool.current_block + 1 :] for token in block
            )
        free: set[int] = set()
        head = pool.free_head
        while head:
            if head not in records or head in free:
                raise ValueError("unknown or cyclic returned-record chain")
            free.add(head)
            head = struct.unpack_from("<Q", records[head], 0x10)[0]
        if len(free) + len(unissued) != pool.available:
            raise ValueError("pool available count differs from returned/unissued slots")
        if type(self.reserved_tokens) is not tuple:
            raise ValueError("explicit reserved record identities required")
        for token in self.reserved_tokens:
            _integer(token, 1, (1 << 64) - 1, "reserved record token")
        reserved = set(self.reserved_tokens)
        if len(reserved) != len(self.reserved_tokens) or not reserved <= records.keys():
            raise ValueError("invalid reserved record identities")
        active: set[int] = set()
        for bucket_index, bucket in enumerate(self.buckets):
            for row, token in enumerate(bucket.slots[: bucket.used]):
                if token not in records or token in active:
                    raise ValueError("unknown or duplicated active record")
                active.add(token)
                raw = records[token]
                if raw[1] not in (2, 3, 5, 11, 13) or raw[0] != (2 if raw[1] in (3, 5) else 3):
                    raise UnsupportedLegacyKind2("unproved existing record geometry")
                if struct.unpack_from("<i", raw, 4)[0] != bucket_index or (
                    struct.unpack_from("<i", raw, 0x1C)[0] != row
                ):
                    raise ValueError("record bucket/row disagrees with its active slot")
                owner = struct.unpack_from("<Q", raw, 8)[0]
                if (
                    owner not in objects
                    or objects[owner].record_token != token
                    or objects[owner].object_id != struct.unpack_from("<i", raw, 0x18)[0]
                ):
                    raise ValueError("active object/record binding disagrees")
        linked = [o.record_token for o in self.objects if o.record_token]
        if len(linked) != len(set(linked)) or set(linked) != active:
            raise ValueError("every active record must have exactly one object binding")
        partitions = (active, reserved, free, unissued)
        seen: set[int] = set()
        for partition in partitions:
            if seen & partition:
                raise ValueError("active/reserved/returned/unissued records overlap")
            seen.update(partition)
        if seen != records.keys():
            raise ValueError("every record must have an explicit pool role")
        if type(self.tile_words) is not tuple or len(self.tile_words) != self.width * self.height:
            raise ValueError("complete initialized tile plane required")
        for word in self.tile_words:
            _integer(word, 0, (1 << 64) - 1, "tile plane word")


@dataclass(frozen=True, slots=True)
class LegacyKind2Refresh:
    defined_al: bool
    callback_bounds: tuple[int, int, int, int]
    fmod_calls: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class LegacyRegistrationRefresh:
    defined_al: bool
    callback_bounds: tuple[int, int, int, int] | None
    fmod_calls: tuple[tuple[int, int], ...]


def _square(word: int) -> int:
    """One exact binary32 RNE square, including subnormal products and underflow."""
    _finite(word, radius=True)
    magnitude = _units(word) ** 2  # Exact units of2**-298, including either zero sign.
    if not magnitude:
        return 0
    shift = max(149, magnitude.bit_length() - 24)
    rounded, remainder = divmod(magnitude, 1 << shift)
    half = 1 << (shift - 1)
    if remainder > half or (remainder == half and rounded & 1):
        rounded += 1
    if rounded >= 1 << 24:
        rounded >>= 1
        shift += 1
    if rounded < 1 << 23:
        return rounded
    exponent = shift - 148
    if exponent >= 255:
        raise UnsupportedLegacyKind2("radius square overflow outside the finite profile")
    return exponent << 23 | (rounded & 0x7FFFFF)


class _LegacyRegistrationPhase:
    """Shared suffix; each public caller establishes its own admission context.

    Unsupported arguments/capacity are rejected before mutation; that policy
    does not reproduce native partial writes on allocation/callback failure.
    No current Game state, fresh allocator payload or modern phase is inferred.
    """

    def __init__(self, state: LegacyKind2State) -> None:
        if type(state) is not LegacyKind2State:
            raise ValueError("explicit typed kind2 state required")
        self._initial = state
        self._records = {r.token: bytearray(r.raw) for r in state.records}
        self._objects = {o.token: o for o in state.objects}
        self._links = {o.token: o.record_token for o in state.objects}
        self._slots = [list(b.slots) for b in state.buckets]
        self._used = [b.used for b in state.buckets]
        self._tiles = list(state.tile_words)
        self._current, self._next = state.pool.current_block, state.pool.next_slot
        self._free, self._available = state.pool.free_head, state.pool.available

    def _refresh(
        self,
        object_token: int,
        *,
        position_bits: tuple[int, int],
        radius_bits: tuple[int, int],
        kind: int,
        mode: int,
        owner: int,
    ) -> LegacyRegistrationRefresh:
        _integer(object_token, 1, (1 << 64) - 1, "object token")
        if object_token not in self._objects:
            raise ValueError("object token is not registered")
        if type(kind) is not int or kind not in (2, 5):
            raise UnsupportedLegacyKind2("current master registration kind2 or5 required")
        _integer(mode, 1, 255, "full current master mode")
        _integer(owner, 0, 6, "current owner")
        for pair in (position_bits, radius_bits):
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("two immutable binary32 words required")
        for word in position_bits:
            _finite(word)
        for word in radius_bits:
            _finite(word, radius=True)
        x, y = position_bits
        rx, ry = radius_bits
        bounds = (_sum(x, rx, subtract=True), _sum(y, ry, subtract=True), _sum(rx, x), _sum(ry, y))
        dimensions = (self._initial.width, self._initial.height) * 2

        def clipped(words: tuple[int, ...]) -> tuple[int, int, int, int]:
            result = tuple(
                max(0, min(extent - 1, _truncated(word)))
                for word, extent in zip(words, dimensions, strict=True)
            )
            return result[0], result[1], result[2], result[3]

        tile_bounds: tuple[int, int, int, int] | None = None
        fmod_calls: list[tuple[int, int]] = []
        upper: tuple[int, ...] = bounds[2:]
        if kind == 2:
            tile_bounds = clipped(
                (*bounds[:2], *(_sum(v, _EPSILON, subtract=True) for v in bounds[2:]))
            )
            fmod_calls = [(x, _fmod_half(x))]
            adjusted = _units(fmod_calls[0][1]) < _units(_EPSILON)
            if adjusted:
                fmod_calls.append((y, _fmod_half(y)))
                adjusted = _units(fmod_calls[1][1]) < _units(_EPSILON)
            if adjusted:
                upper = tuple(_sum(v, _EPSILON, subtract=True) for v in bounds[2:])
        lo_x, lo_y, hi_x, hi_y = clipped((*bounds[:2], *upper))
        level = self._initial.levels[
            min(
                self._initial.lookup_words[(lo_x ^ hi_x) >> 3],
                self._initial.lookup_words[(lo_y ^ hi_y) >> 3],
            )
        ]
        bucket = (
            level.base_index
            + ((lo_y >> level.coordinate_shift) << level.ordinal)
            + (lo_x >> level.coordinate_shift)
        )
        token = self._links[object_token]
        old_bucket = struct.unpack_from("<i", self._records[token], 4)[0] if token else -1
        if bucket != old_bucket and self._used[bucket] >= len(self._slots[bucket]):
            raise UnsupportedLegacyKind2("destination bucket requires unported growth")
        if not token and not self._available:
            raise UnsupportedLegacyKind2("record pool requires unported growth")
        # In this admitted profile the actual empty-list callback has no
        # semantic stores. Its source call point is after row-major grid writes
        # and before record borrow; callback_bounds records its complete input.
        if tile_bounds is not None:
            left, bottom, right, top = tile_bounds
            stamp = (((owner << 8) | (mode & 63) | 0x40) << 8) | (0x800000 << owner)
            if mode == 5:
                stamp |= 0x8000
            for tile_y in range(bottom, top + 1):
                for tile_x in range(left, right + 1):
                    index = tile_y * self._initial.width + tile_x
                    old = self._tiles[index]
                    if old < 0x800000:
                        self._tiles[index] = (old & 0xFFFFFFFFFF0000FF) | stamp
        if not token:
            self._available -= 1
            if self._free:
                token = self._free
                self._free = struct.unpack_from("<Q", self._records[token], 0x10)[0]
            else:
                block = self._initial.pool.blocks[self._current]
                token = block[self._next]
                self._next += 1
                if self._next == len(block):
                    self._next = 0
                    self._current += 1
                    if self._current == len(self._initial.pool.blocks):
                        self._current = -1
            self._links[object_token] = token
            raw = self._records[token]
            struct.pack_into("<H", raw, 2, 0x100)
            struct.pack_into("<QQi", raw, 8, object_token, 0, self._objects[object_token].object_id)
            raw[1] = 0
        else:
            raw = self._records[token]
        if bucket != old_bucket:
            if old_bucket >= 0:
                old_row = struct.unpack_from("<i", raw, 0x1C)[0]
                old_count = self._used[old_bucket]
                if old_row + 1 < old_count:
                    last_token = self._slots[old_bucket][old_count - 1]
                    self._slots[old_bucket][old_row] = last_token
                    struct.pack_into("<i", self._records[last_token], 0x1C, old_row)
                self._used[old_bucket] -= 1
            row = self._used[bucket]
            self._slots[bucket][row] = token
            self._used[bucket] += 1
        else:
            row = struct.unpack_from("<i", raw, 0x1C)[0]
        raw[0], raw[1] = (3, 2) if kind == 2 else (2, 5)
        struct.pack_into("<i", raw, 4, bucket)
        struct.pack_into("<i", raw, 0x1C, row)
        struct.pack_into("<4I", raw, 0x20, *bounds)
        if kind == 5:
            struct.pack_into("<4I", raw, 0x30, x, y, rx, _square(rx))
        return LegacyRegistrationRefresh(True, tile_bounds, tuple(fmod_calls))

    def snapshot(self) -> LegacyKind2State:
        initial = self._initial
        pool = initial.pool
        return LegacyKind2State(
            initial.width,
            initial.height,
            initial.lookup_words,
            initial.levels,
            tuple(
                LegacyMutationBucket(used, tuple(slots))
                for used, slots in zip(self._used, self._slots, strict=True)
            ),
            tuple(
                LegacyMutationRecord(r.token, bytes(self._records[r.token]))
                for r in initial.records
            ),
            tuple(
                LegacyMutationObject(o.token, o.object_id, self._links[o.token])
                for o in initial.objects
            ),
            LegacyKind2Pool(
                pool.blocks,
                pool.metadata_capacity,
                self._current,
                self._next,
                self._free,
                self._available,
                pool.growth_step,
            ),
            initial.reserved_tokens,
            tuple(self._tiles),
        )


class LegacyKind2Registry(_LegacyRegistrationPhase):
    """Isolated successful legacy entry; original public context is unchanged."""

    def __init__(self, state: LegacyKind2State, context: LegacyKind2Context) -> None:
        if type(state) is not LegacyKind2State or type(context) is not LegacyKind2Context:
            raise ValueError("explicit typed kind2 state/context required")
        self._context = context
        super().__init__(state)

    def refresh(
        self,
        object_token: int,
        *,
        position_bits: tuple[int, int],
        radius_bits: tuple[int, int],
        kind: int,
        mode: int,
        owner: int,
    ) -> LegacyKind2Refresh:
        _integer(object_token, 1, (1 << 64) - 1, "object token")
        if object_token not in self._objects:
            raise ValueError("object token is not registered")
        if type(kind) is not int or kind != 2:
            raise UnsupportedLegacyKind2("current master registration kind2 required")
        result = self._refresh(
            object_token,
            position_bits=position_bits,
            radius_bits=radius_bits,
            kind=kind,
            mode=mode,
            owner=owner,
        )
        assert result.callback_bounds is not None
        return LegacyKind2Refresh(result.defined_al, result.callback_bounds, result.fmod_calls)
