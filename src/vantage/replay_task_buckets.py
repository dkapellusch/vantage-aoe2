"""Build54800 pair/byte-map rehash and qword bucket fill bodies.

Real bucket-storage/error calls and coherent current backing remain mandatory.
Sources: world-envelope/task-container-helper-source-v1/native/
{14114d760,14114d970,141143790,141143820}. Generic fill keeps the real source
address; caller-local view addressing must be bound explicitly by its adapter.
This module alone neither initializes a World nor advances replay ticks.
"""

from __future__ import annotations

from vantage.replay_task_containers import ReplayTaskContainerCalls, _call, _error, _validate
from vantage.replay_task_rebuild import ReplayTaskRebuildStorage, _read, _unsigned, _write

_U64 = (1 << 64) - 1
_FNV = 0xCBF29CE484222325
_PRIME = 0x100000001B3


def fill_replay_task_buckets(
    context: ReplayTaskRebuildStorage,
    begin: int,
    end: int,
    source_address: int,
) -> None:
    """Full equivalent143790/143820 bodies within the finite qword-range ABI.

    DF=0, successful coherent backing and a nonwrapping qword-stepped range
    are explicit premises. The real source address preserves partial overlap;
    an outside-interval source is cached only for the even-length bulk prefix.
    Native malformed-range faults/nontermination and stack aliases are excluded.
    """
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current scalar bucket storage required")
    for address in (begin, end, source_address):
        _unsigned(address, 8, "bucket fill address")
    if end < begin or (end - begin) % 8:
        raise ValueError("finite nonwrapping qword-stepped fill range required")
    count = ((end - begin + 7) & _U64) >> 3
    if count >= 2:
        cached = _read(context, source_address, 8)
        last = (begin - 8 + count * 8) & _U64
        if source_address < begin or source_address > last:
            for _ in range(count & ~1):
                _write(context, begin, 8, cached)
                begin = (begin + 8) & _U64
    while begin != end:
        _write(context, begin, 8, _read(context, source_address, 8))
        begin = (begin + 8) & _U64


def _fnv(values: tuple[int, ...]) -> int:
    hashed = _FNV
    for value in values:
        hashed = ((hashed ^ value) * _PRIME) & _U64
    return hashed


def _pair_hash_and_next(context: ReplayTaskRebuildStorage, node: int) -> tuple[int, int]:
    # Preserve the compiler's interleaved scalar read order, not just the hash.
    b15 = _read(context, node + 0x15, 1)
    b14 = _read(context, node + 0x14, 1)
    b10 = _read(context, node + 0x10, 1)
    following = _read(context, node, 8)
    b16 = _read(context, node + 0x16, 1)
    b17 = _read(context, node + 0x17, 1)
    b11 = _read(context, node + 0x11, 1)
    b12 = _read(context, node + 0x12, 1)
    b13 = _read(context, node + 0x13, 1)
    return ((_fnv((b14, b15, b16, b17)) * 2) ^ _fnv((b10, b11, b12, b13))) & _U64, following


def _splice(context: ReplayTaskRebuildStorage, node: int, following: int, target: int) -> None:
    # Offsets define link direction; no _Next/_Prev naming is assumed.
    p = _read(context, node + 8, 8)
    _write(context, p, 8, following)
    q = _read(context, following + 8, 8)
    _write(context, q, 8, target)
    r = _read(context, target + 8, 8)
    _write(context, r, 8, node)
    _write(context, target + 8, 8, q)
    _write(context, following + 8, 8, p)
    _write(context, node + 8, 8, r)


def _equal(
    context: ReplayTaskRebuildStorage,
    candidate: int,
    node: int,
    first: int,
    *,
    pair: bool,
) -> bool:
    if _read(context, candidate + 0x10, 4 if pair else 1) != first:
        return False
    if not pair:
        return True
    second = _read(context, candidate + 0x14, 4)
    return _read(context, node + 0x14, 4) == second


def _rehash(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    requested: int,
    calls: ReplayTaskContainerCalls,
    *,
    pair: bool,
) -> None:
    if requested > 1 << 59:
        _error(calls, 0x142D66698, (0x143682938,))
    held_head = _read(context, map_address + 8, 8)
    count = 1 << (((((requested - 1) & _U64) | 1).bit_length()) & 63)
    _call(calls, 0x14114D5C0 if pair else 0x14114D690, (map_address + 0x18, count * 2, held_head))
    _write(context, map_address + 0x38, 8, count)
    _write(context, map_address + 0x30, 8, count - 1)
    current_head = _read(context, map_address + 8, 8)
    node = _read(context, current_head, 8)
    while node != held_head:
        if pair:
            hashed, following = _pair_hash_and_next(context, node)
            first = 0  # The pair's held first DWORD is loaded after bucket+8.
        else:
            first = _read(context, node + 0x10, 1)
            following = _read(context, node, 8)
            hashed = ((first ^ _FNV) * _PRIME) & _U64
        mask = _read(context, map_address + 0x30, 8)
        table = _read(context, map_address + 0x18, 8)
        bucket = (table + ((hashed & mask) << 4)) & _U64
        endpoint = _read(context, bucket, 8)
        if endpoint == held_head:
            _write(context, bucket, 8, node)
            _write(context, bucket + 8, 8, node)
        else:
            candidate = _read(context, bucket + 8, 8)
            if pair:
                first = _read(context, node + 0x10, 4)
            if _equal(context, candidate, node, first, pair=pair):
                target = _read(context, candidate, 8)
                if target != node:
                    _splice(context, node, following, target)
                _write(context, bucket + 8, 8, node)
            else:
                matched = False
                while candidate != endpoint:
                    candidate = _read(context, candidate + 8, 8)
                    if _equal(context, candidate, node, first, pair=pair):
                        matched = True
                        break
                if matched:
                    _splice(context, node, following, _read(context, candidate, 8))
                else:
                    _splice(context, node, following, candidate)
                    _write(context, bucket, 8, node)
        node = following


def rehash_replay_task_pair(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    requested: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full14114d760; actual bucket-storage/error leaves remain mandatory.

    Actual current headers, nodes and finite coherent link traversal are required.
    Native faults, C++ EH cleanup, stack aliases and returned-error traps excluded.
    This does not allocate nodes, change count10 or inspect values/padding.
    """
    _validate(context, calls, map_address)
    _unsigned(requested, 8, "requested bucket count")
    _rehash(context, map_address, requested, calls, pair=True)


def rehash_replay_task_byte(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    requested: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full14114d970 under the same effective backing/leaf premises as pair."""
    _validate(context, calls, map_address)
    _unsigned(requested, 8, "requested bucket count")
    _rehash(context, map_address, requested, calls, pair=False)
