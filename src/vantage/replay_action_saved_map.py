"""Build54800 Action saved-map lookup619B and rehash429B, plus actual thunks.

Source: action-saved-map-source-v1; complete instruction bytes match both
regular-file originals. Four-byte FNV keys and ordered linked-list/bucket
effects retain current reads. Real allocation, storage and selected IAT
effects remain required. Scalar FP uses masked nearest-even, DAZ/FTZ off;
native stack/register, node-guard EH, faults and concurrency are excluded.
"""

from __future__ import annotations

from .replay_binary32 import compare_binary32, divide_binary32, unsigned64_binary32
from .replay_task_containers import (
    ReplayTaskContainerCalls,
    _call,
    _error,
    _growth,
    _validate,
)
from .replay_task_group_maps import (
    _splice,
    call_replay_task_group_ceil,
    call_replay_task_group_length,
)
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _unsigned,
    _write,
)

_U64 = (1 << 64) - 1
_FNV = 0xCBF29CE484222325
_PRIME = 0x100000001B3


def _hash(context: ReplayTaskRebuildStorage, key: int) -> int:
    result = _FNV
    for offset in range(4):
        result = ((result ^ _read(context, key + offset, 1)) * _PRIME) & _U64
    return result


def _search(
    context: ReplayTaskRebuildStorage,
    header: int,
    hashed: int,
    key: int,
    *,
    post: bool,
) -> tuple[bool, int]:
    mask = _read(context, header + 0x30, 8)
    buckets = _read(context, header + 0x18, 8)
    slot = (buckets + (hashed & mask) * 16) & _U64
    node = _read(context, slot + 8, 8)
    sentinel = _read(context, header + 8, 8)
    if node == sentinel:
        return False, sentinel
    boundary = _read(context, slot, 8)
    held = _read(context, key, 4)
    while True:
        if held == _read(context, node + 0x10, 4):
            return True, _read(context, node, 8) if post else node
        if node == boundary:
            return False, node
        node = _read(context, node + 8, 8)


def lookup_replay_action_saved_map(
    context: ReplayTaskRebuildStorage,
    header: int,
    output: int,
    key: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> int:
    """Complete normal1411369a0; native three-address ABI, nine-byte output.

    The key is hashed before allocation but copied afterward. A duplicate
    writes its held node and false without reading the count/load factor.
    Rehash may mutate current backing; the post-rehash search keeps the old
    hash and compares the newly allocated node's current DWORD key. Failed
    child effects retain earlier writes; no unwind cleanup is invented.
    """
    _validate(context, calls, header, output, key)
    hashed = _hash(context, key)
    found, predecessor = _search(context, header, hashed, key, post=False)
    if found:
        _write(context, output, 8, predecessor)
        _write(context, output + 8, 1, 0)
        return output
    if _read(context, header + 0x10, 8) == 0x0AAAAAAAAAAAAAAA:
        _error(calls, 0x142D66698, (0x143682918,))
    node = _call(calls, 0x142D6BA78, (24,), width=8)
    _write(context, node + 0x10, 4, _read(context, key, 4))
    _write(context, node + 0x14, 4, 0)
    load = _read(context, header, 4)
    capacity = _read(context, header + 0x38, 8)
    total = unsigned64_binary32((_read(context, header + 0x10, 8) + 1) & _U64)
    ratio = divide_binary32(total, unsigned64_binary32(capacity))
    if compare_binary32(ratio, load) == 1:
        ceiling = _call(calls, 0x142D6E453, (divide_binary32(total, load),), width=4)
        requested = _growth(ceiling, _read(context, 0x1436A0308, 4))
        if capacity < requested:
            capacity = max(capacity * 8, requested) if capacity < 512 else requested
        _call(calls, 0x14113A430, (header, capacity))
        _, predecessor = _search(context, header, hashed, node + 0x10, post=True)
    following = _read(context, predecessor + 8, 8)
    _write(context, header + 0x10, 8, _read(context, header + 0x10, 8) + 1)
    _write(context, node, 8, predecessor)
    _write(context, node + 8, 8, following)
    _write(context, following, 8, node)
    _write(context, predecessor + 8, 8, node)
    mask = _read(context, header + 0x30, 8)
    buckets = _read(context, header + 0x18, 8)
    slot = (buckets + (hashed & mask) * 16) & _U64
    boundary = _read(context, slot, 8)
    if boundary == _read(context, header + 8, 8):
        _write(context, slot, 8, node)
        _write(context, slot + 8, 8, node)
    elif boundary == predecessor:
        _write(context, slot, 8, node)
    elif _read(context, slot + 8, 8) == following:
        _write(context, slot + 8, 8, node)
    _write(context, output, 8, node)
    _write(context, output + 8, 1, 1)
    return output


def rehash_replay_action_saved_map(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Complete normal14113a430; real current storage and ordered list splice.

    The held sentinel survives the actual initializer. Request0 wraps then
    rounds to one bucket; request1 gives two, following masked x64 shifts.
    Each node reads key byte1, byte0, its next link, then byte2/3 before
    selecting current buckets. Finite coherent traversal is required;
    malformed cycles carry no invented iteration limit or repaired links.
    """
    _validate(context, calls, header, requested)
    if requested > 1 << 59:
        _error(calls, 0x142D66698, (0x143682938,))
    sentinel = _read(context, header + 8, 8)
    count = 1 << (((((requested - 1) & _U64) | 1).bit_length()) & 63)
    _call(calls, 0x14113A360, (header + 0x18, (count * 2) & _U64, sentinel))
    _write(context, header + 0x38, 8, count)
    _write(context, header + 0x30, 8, count - 1)
    node = _read(context, _read(context, header + 8, 8), 8)
    while node != sentinel:
        byte1 = _read(context, node + 0x11, 1)
        byte0 = _read(context, node + 0x10, 1)
        following = _read(context, node, 8)
        hashed = ((byte0 ^ _FNV) * _PRIME) & _U64
        hashed = ((hashed ^ byte1) * _PRIME) & _U64
        hashed = ((hashed ^ _read(context, node + 0x12, 1)) * _PRIME) & _U64
        hashed = ((hashed ^ _read(context, node + 0x13, 1)) * _PRIME) & _U64
        mask = _read(context, header + 0x30, 8)
        buckets = _read(context, header + 0x18, 8)
        slot = (buckets + (hashed & mask) * 16) & _U64
        first = _read(context, slot, 8)
        if first == sentinel:
            _write(context, slot, 8, node)
            _write(context, slot + 8, 8, node)
        else:
            tail = _read(context, slot + 8, 8)
            held = _read(context, node + 0x10, 4)
            if held == _read(context, tail + 0x10, 4):
                target = _read(context, tail, 8)
                if target != node:
                    _splice(context, node, following, target)
                _write(context, slot + 8, 8, node)
            else:
                while tail != first:
                    tail = _read(context, tail + 8, 8)
                    if held == _read(context, tail + 0x10, 4):
                        _splice(context, node, following, _read(context, tail, 8))
                        break
                else:
                    _splice(context, node, following, tail)
                    _write(context, slot, 8, node)
        node = following


def bind_replay_action_saved_map(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind lookup/rehash and reached ceil/length thunks with current IAT reads.

    Bucket initializer14113a360 and all selected runtime targets remain real
    required children. Ceil uses the raw XMM0 low word in a scalar carrier;
    wider registers, FP status/traps and native import identity are excluded.
    """
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("actual Action map runtime bindings required")
    _validate(context, ReplayTaskContainerCalls(calls.call, mxcsr))

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x1411369A0: 3, 0x14113A430: 2, 0x142D6E453: 1, 0x142D66698: 1}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Action saved-map call")
        for value in args:
            _unsigned(value, 8, "Action saved-map argument")
        if target == 0x1411369A0:
            return lookup_replay_action_saved_map(context, *args, calls=bound)
        if target == 0x14113A430:
            rehash_replay_action_saved_map(context, *args, calls=bound)
        elif target == 0x142D6E453:
            return call_replay_task_group_ceil(context, args[0], calls=bound)
        else:
            call_replay_task_group_length(context, args[0], calls=bound)
        return None

    bound = ReplayTaskContainerCalls(dispatch, mxcsr)
    return ReplayTaskRebuildCalls(dispatch)
