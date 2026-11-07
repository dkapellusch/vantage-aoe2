"""Build54800 TaskList prefix map/clear/vector helper bodies.

Ports1411434c0/143260/1510f0/151180/143090 over current scalar storage.
Allocation, rehash, bucket fill, ceilf, memmove and error leaves require actual
bindings. This closes the five bodies, not a heap implementation or World tick.
Sources: world-envelope/task-prefix-helper-source-v1/native and
transform-command-gates/native-reader-reset. All addresses are build specific.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .replay_binary32 import (
    compare_binary32,
    divide_binary32,
    subtract_binary32,
    unsigned64_binary32,
)
from .replay_task_prefix import ReplayTaskPrefixCalls
from .replay_task_rebuild import ReplayTaskRebuildStorage, _read, _signed, _unsigned, _write

_U64 = (1 << 64) - 1
_FNV = 0xCBF29CE484222325
_PRIME = 0x100000001B3


class UnresolvedReplayTaskContainer(ValueError):
    """A reached container leaf has no actual implementation binding."""


@dataclass(frozen=True, slots=True)
class ReplayTaskContainerCalls:
    """Actual leaf dispatcher and the admitted scalar floating-point profile.

    call(target,args,data) receives native effective scalar arguments. Allocators
    142d6ba78/1402a94d0 take(byte_size,) and return a raw u64 pointer. Sized free
    142d6bab4 takes(pointer,size); memmove142d6e3db takes(dest,src,size). Rehash
    14114d760/14114d970 takes(map,bucket_count). Fill141143790/141143820 takes
    (begin,end) and a mutable8B source local. Ceilf142d6e453 takes(rawXMM0word,)
    and returns a raw u32 word; no guessed ceil implementation is supplied.

    Length error142d66698 takes its static string pointer; vector errors
    14114dd60/1402a9460 take no arguments. The current Watson target read from
    14319a060 receives five zero arguments. Errors must actually not return.
    An unexpected return is surfaced as RuntimeError, not native INT3 parity.

    None marks the dispatcher unavailable. No default success/allocation exists.
    Masked nearest-even MXCSR with DAZ/FTZoff is required. Successful coherent
    backing and valid containers are premises. Callback exceptions preserve
    preceding body effects; C++ EH node-guard cleanup and native fault ordering,
    upper lanes/FPstatus/traps, stack aliases and escaped locals are excluded.
    """

    call: Callable[[int, tuple[int, ...], memoryview | None], int | None] | None
    mxcsr: int

    def __post_init__(self) -> None:
        if self.call is not None and not callable(self.call):
            raise ValueError("actual container leaf dispatcher or unavailable binding required")
        _unsigned(self.mxcsr, 4, "MXCSR")
        if self.mxcsr & ~0x3F != 0x1F80:
            raise ValueError("masked nearest-even MXCSR, DAZ/FTZoff required")


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskContainerCalls,
    *addresses: int,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current scalar container storage required")
    if not isinstance(calls, ReplayTaskContainerCalls):
        raise ValueError("explicit actual container leaf bindings required")
    for address in addresses:
        _unsigned(address, 8, "container address")


def _view(value: memoryview, width: int) -> None:
    if (
        not isinstance(value, memoryview)
        or value.ndim != 1
        or value.format != "B"
        or not value.c_contiguous
        or value.readonly
        or len(value) != width
    ):
        raise ValueError(f"explicit writable contiguous{width}B view required")


def _get(value: memoryview, offset: int, width: int) -> int:
    return int.from_bytes(value[offset : offset + width], "little")


def _call(
    calls: ReplayTaskContainerCalls,
    target: int,
    args: tuple[int, ...],
    data: memoryview | None = None,
    *,
    width: int | None = None,
) -> int:
    if calls.call is None:
        raise UnresolvedReplayTaskContainer(f"reached{target:x} is unavailable")
    value = calls.call(target, tuple(arg & _U64 for arg in args), data)
    if width is None:
        return 0
    if value is None:
        raise ValueError(f"helper{target:x} must return its raw scalar result")
    _unsigned(value, width, f"helper{target:x} return")
    return value


def _error(calls: ReplayTaskContainerCalls, target: int, args: tuple[int, ...] = ()) -> None:
    _call(calls, target, args)
    raise RuntimeError(f"nonreturning helper{target:x} unexpectedly returned")


def _hash_pair(key: memoryview) -> int:
    high = _FNV
    for i in range(4, 8):
        high = ((high ^ key[i]) * _PRIME) & _U64
    low = _FNV
    for i in range(4):
        low = ((low ^ key[i]) * _PRIME) & _U64
    return ((2 * high) ^ low) & _U64


def _hash_byte(key: int) -> int:
    return ((key ^ _FNV) * _PRIME) & _U64


def _search(
    context: ReplayTaskRebuildStorage,
    tail: int,
    boundary: int,
    first: int,
    second: Callable[[], int] | None,
) -> tuple[int, bool]:
    node = tail
    while True:
        if _read(context, node + 0x10, 4 if second else 1) == first:
            if second is None:
                return node, True
            word = _read(context, node + 0x14, 4)
            if second() == word:
                return node, True
        if node == boundary:
            return node, False
        node = _read(context, node + 8, 8)


def _cvtt64(word: int) -> int:
    exponent = word >> 23 & 255
    if exponent == 255:
        return 1 << 63
    magnitude = word & 0x7FFFFF
    if exponent:
        magnitude |= 0x800000
    shift = exponent - 150 if exponent else -149
    magnitude = magnitude << shift if shift >= 0 else magnitude >> -shift
    result = -magnitude if word & 0x80000000 else magnitude
    return result & _U64 if -(1 << 63) <= result < 1 << 63 else 1 << 63


def _growth(word: int, threshold: int) -> int:
    addend = 0
    order = compare_binary32(word, threshold)
    if order is not None and order >= 0:
        word = subtract_binary32(word, threshold)
        order = compare_binary32(word, threshold)
        if order is None or order < 0:
            addend = 1 << 63
    return max(8, (_cvtt64(word) + addend) & _U64)


def _lookup(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    out: int,
    key: memoryview,
    value: memoryview,
    calls: ReplayTaskContainerCalls,
    *,
    pair: bool,
) -> int:
    # The byte key used by the first search is held in CL across hashing.
    byte_key = 0 if pair else key[0]
    hashed = _hash_pair(key) if pair else _hash_byte(byte_key)
    mask = _read(context, map_address + 0x30, 8)
    index = ((hashed & mask) * 16) & _U64
    buckets = _read(context, map_address + 0x18, 8)
    tail = _read(context, buckets + index + 8, 8)
    predecessor = _read(context, map_address + 8, 8)
    if tail != predecessor:
        boundary = _read(context, buckets + index, 8)
        first = _get(key, 0, 4) if pair else byte_key
        predecessor, found = _search(
            context,
            tail,
            boundary,
            first,
            (lambda: _get(key, 4, 4)) if pair else None,
        )
        if found:
            _write(context, out, 8, predecessor)
            _write(context, out + 8, 1, 0)
            return out
    if _read(context, map_address + 0x10, 8) == 0x07FFFFFFFFFFFFFF:
        _error(calls, 0x142D66698, (0x143682918,))
    node = _call(calls, 0x142D6BA78, (32,), width=8)
    # Allocation may mutate the caller's current key/value views.
    _write(context, node + 0x10, 8 if pair else 1, _get(key, 0, 8 if pair else 1))
    _write(context, node + 0x18, 4 if pair else 8, _get(value, 0, 4 if pair else 8))
    load = _read(context, map_address, 4)
    bucket_count = _read(context, map_address + 0x38, 8)
    total = unsigned64_binary32((_read(context, map_address + 0x10, 8) + 1) & _U64)
    ratio = divide_binary32(total, unsigned64_binary32(bucket_count))
    if compare_binary32(ratio, load) == 1:
        ceiling = _call(calls, 0x142D6E453, (divide_binary32(total, load),), width=4)
        requested = _growth(ceiling, _read(context, 0x1436A0308, 4))
        if bucket_count < requested:
            bucket_count = max(bucket_count * 8, requested) if bucket_count < 512 else requested
        _call(calls, 0x14114D760 if pair else 0x14114D970, (map_address, bucket_count))
        mask = _read(context, map_address + 0x30, 8)
        index = ((hashed & mask) * 16) & _U64
        buckets = _read(context, map_address + 0x18, 8)
        tail = _read(context, buckets + index + 8, 8)
        predecessor = _read(context, map_address + 8, 8)
        if tail != predecessor:
            boundary = _read(context, buckets + index, 8)
            first = _read(context, node + 0x10, 4 if pair else 1)
            predecessor, found = _search(
                context,
                tail,
                boundary,
                first,
                (lambda: _read(context, node + 0x14, 4)) if pair else None,
            )
            if found:
                predecessor = _read(context, predecessor, 8)
    following = _read(context, predecessor + 8, 8)
    _write(context, map_address + 0x10, 8, _read(context, map_address + 0x10, 8) + 1)
    _write(context, node, 8, predecessor)
    _write(context, node + 8, 8, following)
    _write(context, following, 8, node)
    _write(context, predecessor + 8, 8, node)
    mask = _read(context, map_address + 0x30, 8)
    index = ((hashed & mask) * 16) & _U64
    buckets = _read(context, map_address + 0x18, 8)
    boundary = _read(context, buckets + index, 8)
    if boundary == _read(context, map_address + 8, 8):
        _write(context, buckets + index, 8, node)
        _write(context, buckets + index + 8, 8, node)
    elif boundary == predecessor:
        _write(context, buckets + index, 8, node)
    elif _read(context, buckets + index + 8, 8) == following:
        _write(context, buckets + index + 8, 8, node)
    _write(context, out, 8, node)
    _write(context, out + 8, 1, 1)
    return out


def lookup_replay_task_pair(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    out: int,
    key: memoryview,
    value: memoryview,
    *,
    calls: ReplayTaskContainerCalls,
) -> int:
    """Full1411434c0: pair-u32 lookup/insert, valueu32, qword/byte OUT stores."""
    _validate(context, calls, map_address, out)
    _view(key, 8)
    _view(value, 4)
    return _lookup(context, map_address, out, key, value, calls, pair=True)


def lookup_replay_task_byte(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    out: int,
    key: memoryview,
    value: memoryview,
    *,
    calls: ReplayTaskContainerCalls,
) -> int:
    """Full141143260: byte-key lookup/insert, valueu64, qword/byte OUT stores."""
    _validate(context, calls, map_address, out)
    _view(key, 1)
    _view(value, 8)
    return _lookup(context, map_address, out, key, value, calls, pair=False)


def _dense_clear(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    head: int,
    calls: ReplayTaskContainerCalls,
    fill: int,
) -> None:
    following = _read(context, head + 8, 8)
    _write(context, following, 8, 0)
    node = _read(context, head, 8)
    while node:
        previous = _read(context, node, 8)
        _call(calls, 0x142D6BAB4, (node, 32))
        node = previous
    current_head = _read(context, map_address + 8, 8)
    _write(context, current_head, 8, current_head)
    current_head = _read(context, map_address + 8, 8)
    _write(context, current_head + 8, 8, current_head)
    _write(context, map_address + 0x10, 8, 0)
    current_head = _read(context, map_address + 8, 8)
    end = _read(context, map_address + 0x20, 8)
    begin = _read(context, map_address + 0x18, 8)
    local = bytearray(current_head.to_bytes(8, "little"))
    _call(calls, fill, (begin, end), memoryview(local))


def clear_replay_task_pair(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full1411510f0, including current head rereads after all sized frees."""
    _validate(context, calls, map_address)
    if _read(context, map_address + 0x10, 8):
        _dense_clear(context, map_address, _read(context, map_address + 8, 8), calls, 0x141143790)


def clear_replay_task_byte(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full141151180, with dense reset or sparse bucket-by-bucket unlinking."""
    _validate(context, calls, map_address)
    count = _read(context, map_address + 0x10, 8)
    if not count:
        return
    bucket_count = _read(context, map_address + 0x38, 8)
    head = _read(context, map_address + 8, 8)
    if count >= bucket_count >> 3:
        _dense_clear(context, map_address, head, calls, 0x141143820)
        return
    node = _read(context, head, 8)
    if node == head:
        return
    buckets = _read(context, map_address + 0x18, 8)
    first = node
    following = _read(context, node + 8, 8)
    hashed = _hash_byte(_read(context, node + 0x10, 1))
    bucket = buckets + ((hashed & _read(context, map_address + 0x30, 8)) * 16)
    boundary = _read(context, bucket, 8)
    last = _read(context, bucket + 8, 8)
    while True:
        freed = node
        node = _read(context, node, 8)
        _call(calls, 0x142D6BAB4, (freed, 32))
        _write(context, map_address + 0x10, 8, _read(context, map_address + 0x10, 8) - 1)
        if freed == last:
            if boundary == first:
                _write(context, bucket, 8, head)
                replacement = head
            else:
                replacement = following
            _write(context, bucket + 8, 8, replacement)
            break
        if node == head:
            if boundary == first:
                _write(context, bucket, 8, node)
            _write(context, following, 8, node)
            _write(context, node + 8, 8, following)
            return
    while node != head:
        hashed = _hash_byte(_read(context, node + 0x10, 1))
        bucket = buckets + ((hashed & _read(context, map_address + 0x30, 8)) * 16)
        last = _read(context, bucket + 8, 8)
        while True:
            freed = node
            node = _read(context, node, 8)
            _call(calls, 0x142D6BAB4, (freed, 32))
            _write(context, map_address + 0x10, 8, _read(context, map_address + 0x10, 8) - 1)
            if freed == last:
                _write(context, bucket, 8, head)
                _write(context, bucket + 8, 8, head)
                break
            if node == head:
                _write(context, bucket, 8, node)
                _write(context, following, 8, node)
                _write(context, node + 8, 8, following)
                return
    _write(context, following, 8, node)
    _write(context, node + 8, 8, following)


def grow_replay_task_vector64(
    context: ReplayTaskRebuildStorage,
    vector: int,
    position: int,
    descriptor: memoryview,
    *,
    calls: ReplayTaskContainerCalls,
) -> int:
    """Full141143090 insertion/growth, with copy-before-move and sized free."""
    _validate(context, calls, vector, position)
    _view(descriptor, 64)
    begin = _read(context, vector, 8)
    end = _read(context, vector + 8, 8)
    count = _signed((end - begin) & _U64, 8) >> 6
    offset = (position - begin) & _U64
    maximum = 0x03FFFFFFFFFFFFFF
    if count & _U64 == maximum:
        _error(calls, 0x14114DD60)
    capacity = _signed((_read(context, vector + 0x10, 8) - begin) & _U64, 8) >> 6 & _U64
    count = (count + 1) & _U64
    half = capacity >> 1
    if capacity > (maximum - half) & _U64:
        growth = maximum
    else:
        growth = max((capacity + half) & _U64, count)
        if growth > maximum:
            _error(calls, 0x1402A9460)
    allocation = _call(calls, 0x1402A94D0, ((growth * 64) & _U64,), width=8)
    inserted = (allocation + (offset & ~63)) & _U64
    for index in range(0, 64, 16):
        _write(context, inserted + index, 16, _get(descriptor, index, 16))
    end = _read(context, vector + 8, 8)
    begin = _read(context, vector, 8)
    if position == end:
        _call(calls, 0x142D6E3DB, (allocation, begin, (end - begin) & _U64))
    else:
        _call(calls, 0x142D6E3DB, (allocation, begin, (position - begin) & _U64))
        end = _read(context, vector + 8, 8)
        _call(calls, 0x142D6E3DB, (inserted + 64, position, (end - position) & _U64))
    begin = _read(context, vector, 8)
    if begin:
        size = (_read(context, vector + 0x10, 8) - begin) & _U64 & ~63
        pointer = begin
        if size >= 0x1000:
            pointer = _read(context, begin - 8, 8)
            size = (size + 0x27) & _U64
            if (begin - pointer - 8) & _U64 > 31:
                target = _read(context, 0x14319A060, 8)
                _error(calls, target, (0, 0, 0, 0, 0))
        _call(calls, 0x142D6BAB4, (pointer, size))
    _write(context, vector, 8, allocation)
    _write(context, vector + 8, 8, allocation + count * 64)
    _write(context, vector + 0x10, 8, allocation + growth * 64)
    return inserted


def bind_replay_task_prefix_containers(
    context: ReplayTaskRebuildStorage,
    *,
    pair_out: int,
    byte_out: int,
    calls: ReplayTaskContainerCalls,
) -> ReplayTaskPrefixCalls:
    """Bind the five real bodies and caller-owned OUT tokens to14114bf70.

    OUT storage must be current readable/writable9B backing. Real reached leaf
    implementations remain mandatory; this adapter never substitutes observers.
    """
    _validate(context, calls, pair_out, byte_out)

    def dispatch(
        target: int,
        args: tuple[int, ...],
        key: memoryview | None,
        value: memoryview | None,
    ) -> int | None:
        if target == 0x1411510F0 and len(args) == 1 and key is value is None:
            clear_replay_task_pair(context, args[0], calls=calls)
        elif target == 0x141151180 and len(args) == 1 and key is value is None:
            clear_replay_task_byte(context, args[0], calls=calls)
        elif target in (0x1411434C0, 0x141143260) and len(args) == 1:
            if key is None or value is None:
                raise ValueError("lookup requires current key/value views")
            if target == 0x1411434C0:
                return lookup_replay_task_pair(context, args[0], pair_out, key, value, calls=calls)
            return lookup_replay_task_byte(context, args[0], byte_out, key, value, calls=calls)
        elif target == 0x141143090 and len(args) == 2 and value is None:
            if key is None:
                raise ValueError("growth requires the current64B descriptor view")
            return grow_replay_task_vector64(context, args[0], args[1], key, calls=calls)
        else:
            raise UnresolvedReplayTaskContainer(f"unbound/malformed prefix target{target:x}")
        return None

    return ReplayTaskPrefixCalls(dispatch)
