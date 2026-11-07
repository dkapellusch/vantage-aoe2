"""Build54800 task group/criterion lookup, hash, rehash and reached import thunks.

Sources: task-rebuild-helper-source-v1/{native,hash-native} and
task-group-lookup-leaves-source-v1/native. Full seven bodies plus two six-byte
thunks, with concrete bucket storage. Current backing/runtime effects and the
masked nearest-even FP profile remain explicit; this does not restore a World.
"""

from __future__ import annotations

from .replay_binary32 import compare_binary32, divide_binary32, unsigned64_binary32
from .replay_task_containers import (
    ReplayTaskContainerCalls,
    _call,
    _error,
    _growth,
    _validate,
    _view,
)
from .replay_task_group_storage import LocalBinding, bind_replay_task_group_storage
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
_STORAGE = frozenset(
    (
        0x1412BF260,
        0x1412BF330,
        0x1412BF400,
        0x1412C63D0,
        0x1412C6430,
        0x1412C6490,
        0x1412A5AB0,
        0x1412A5B40,
        0x1412A5BD0,
    )
)


def _fnv(values: tuple[int, ...]) -> int:
    result = _FNV
    for value in values:
        result = ((result ^ value) * _PRIME) & _U64
    return result


def _combine(seed: int, value: int) -> int:
    return ((value + (seed << 6) + 0x9E3779B9 + (seed >> 2)) & _U64) ^ seed


def hash_replay_task_group_float(word: int) -> int:
    """Full1412b3370 in the fixed masked FP profile; normalize signed zeros only.

    Subnormals and NaN payloads retain their raw bits. UCOMISS changes no input
    bits; flags, unmasked traps and FPstatus are outside this scalar interface.
    """
    _unsigned(word, 4, "group float hash word")
    if word & 0x7FFFFFFF == 0:
        word = 0
    return _fnv(tuple(word.to_bytes(4, "little")))


def hash_replay_task_group(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    key: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> int:
    """Full1412a36c0: original source load order, no padding reads."""
    _validate(context, calls, map_address, key)
    first = _call(calls, 0x1412B3370, (_read(context, key, 4),), width=8)
    byte4 = _read(context, key + 4, 1)
    byte8 = _read(context, key + 8, 1)
    rest = tuple(_read(context, key + offset, 1) for offset in (5, 6, 7))
    seed = _combine((first + 0x9E3779B9) & _U64, _fnv((byte4, *rest)))
    return _combine(seed, _fnv((byte8,)))


def hash_replay_task_criterion(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    key: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> int:
    """Full1412a3560; byte5/4/0 and float8 precede byte6/7 and float calls."""
    _validate(context, calls, map_address, key)
    byte5 = _read(context, key + 5, 1)
    byte4 = _read(context, key + 4, 1)
    byte0 = _read(context, key, 1)
    float8 = _read(context, key + 8, 4)
    byte6 = _read(context, key + 6, 1)
    byte7 = _read(context, key + 7, 1)
    seed = _combine((_fnv((byte0,)) + 0x9E3779B9) & _U64, _fnv((byte4, byte5, byte6, byte7)))
    hash8 = _call(calls, 0x1412B3370, (float8,), width=8)
    floatc = _read(context, key + 12, 4)
    seed = _combine(seed, hash8)
    hashc = _call(calls, 0x1412B3370, (floatc,), width=8)
    last = tuple(_read(context, key + offset, 1) for offset in range(16, 24))
    return _combine(_combine(seed, hashc), _fnv(last))


def call_replay_task_group_ceil(
    context: ReplayTaskRebuildStorage,
    word: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> int:
    """Full142d6e453: current143199ef0 target; raw XMM0 low32 argument/result.

    The supplied selected-target binding implements actual ceil effects. A
    binding at the thunk entry alone does not substitute for this current read.
    """
    _validate(context, calls)
    _unsigned(word, 4, "ceil XMM0 low word")
    return _call(calls, _read(context, 0x143199EF0, 8), (word,), width=4)


def call_replay_task_group_length(
    context: ReplayTaskRebuildStorage,
    message: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full142d66698: tail-route RCX through current1431992a0.

    No normal result is promised. If a supplied target returns, the caller's
    separate nonreturning-helper guard stops before its verified adjacent CC.
    """
    _validate(context, calls, message)
    _call(calls, _read(context, 0x1431992A0, 8), (message,))


def _equal(
    context: ReplayTaskRebuildStorage,
    left: int,
    right: int,
    byte: int,
    *,
    group: bool,
) -> bool:
    if byte != _read(context, right + (8 if group else 0), 1):
        return False
    right4 = _read(context, right + 4, 4)
    if _read(context, left + 4, 4) != right4:
        return False
    for offset in (0,) if group else (8, 12):
        a = _read(context, left + offset, 4)
        b = _read(context, right + offset, 4)
        if compare_binary32(a, b) != 0:
            return False
    if group:
        return True
    right10 = _read(context, right + 16, 8)
    return _read(context, left + 16, 8) == right10


def _search(
    context: ReplayTaskRebuildStorage,
    header: int,
    hashed: int,
    key: int,
    *,
    group: bool,
    post: bool,
) -> tuple[bool, int]:
    mask = _read(context, header + 0x30, 8)
    buckets = _read(context, header + 0x18, 8)
    slot = (buckets + (hashed & mask) * 16) & _U64
    node = _read(context, slot + 8, 8)
    sentinel = _read(context, header + 8, 8)
    if node == sentinel:
        return False, sentinel
    first = _read(context, slot, 8)
    byte = _read(context, key + (8 if group else 0), 1)
    while True:
        if _equal(context, key, node + 0x10, byte, group=group):
            return True, _read(context, node, 8) if post else node
        if node == first:
            return False, node
        node = _read(context, node + 8, 8)


def _node(
    context: ReplayTaskRebuildStorage,
    key: int,
    calls: ReplayTaskContainerCalls,
    *,
    group: bool,
) -> int:
    node = _call(calls, 0x142D6BA78, (0x78 if group else 0xA0,), width=8)
    # Each store can change the later source read through a declared public alias.
    _write(context, node + 0x10, 8 if group else 16, _read(context, key, 8 if group else 16))
    _write(
        context,
        node + (0x18 if group else 0x20),
        4 if group else 8,
        _read(context, key + (8 if group else 16), 4 if group else 8),
    )
    payload = node + (0x20 if group else 0x28)
    for offset in range(0, 80 if group else 112, 16):
        _write(context, payload + offset, 16, 0)
    _write(context, payload + (80 if group else 112), 8, 0)
    inner = payload if group else payload + 0x30
    _write(context, inner, 4, 0)
    sentinel = _call(calls, 0x142D6BA78, (0xA0 if group else 0x18,), width=8)
    _write(context, sentinel, 8, sentinel)
    _write(context, sentinel + 8, 8, sentinel)
    _write(context, inner + 8, 8, sentinel)
    for offset in (0x18, 0x20, 0x28):
        _write(context, inner + offset, 8, 0)
    _write(context, inner + 0x30, 8, 7)
    _write(context, inner + 0x38, 8, 8)
    _write(context, inner, 4, 0x3F800000)
    _call(
        calls,
        0x1412BF330 if group else 0x1412BF260,
        (inner + 0x18, 16, _read(context, inner + 8, 8)),
    )
    if group:
        for offset in (0x40, 0x48, 0x50):
            _write(context, inner + offset, 8, 0)
    else:
        _write(context, payload + 0x70, 4, 0)
    return node


def _grow(
    context: ReplayTaskRebuildStorage,
    header: int,
    calls: ReplayTaskContainerCalls,
    *,
    group: bool,
) -> bool:
    load = _read(context, header, 4)
    count = _read(context, header + 0x38, 8)
    numerator = unsigned64_binary32((_read(context, header + 0x10, 8) + 1) & _U64)
    ratio = divide_binary32(numerator, unsigned64_binary32(count))
    if compare_binary32(ratio, load) != 1:
        return False
    ceiling = _call(calls, 0x142D6E453, (divide_binary32(numerator, load),), width=4)
    required = _growth(ceiling, _read(context, 0x1436A0308, 4))
    if count < required:
        count = max((count * 8) & _U64, required) if count < 0x200 else required
    _call(calls, 0x1412BFB10 if group else 0x1412BF920, (header, count))
    return True


def _lookup(
    context: ReplayTaskRebuildStorage,
    header: int,
    output: int,
    key: int,
    calls: ReplayTaskContainerCalls,
    *,
    group: bool,
) -> int:
    hashed = _call(calls, 0x1412A36C0 if group else 0x1412A3560, (header, key), width=8)
    hit, predecessor = _search(context, header, hashed, key, group=group, post=False)
    if hit:
        _write(context, output, 8, predecessor)
        _write(context, output + 8, 1, 0)
        return output
    if _read(context, header + 0x10, 8) == (0x222222222222222 if group else 0x199999999999999):
        _error(calls, 0x142D66698, (0x143682918,))
    node = _node(context, key, calls, group=group)
    if _grow(context, header, calls, group=group):
        _, predecessor = _search(context, header, hashed, node + 0x10, group=group, post=True)
    successor = _read(context, predecessor + 8, 8)
    _write(context, header + 0x10, 8, _read(context, header + 0x10, 8) + 1)
    _write(context, node, 8, predecessor)
    _write(context, node + 8, 8, successor)
    _write(context, successor, 8, node)
    _write(context, predecessor + 8, 8, node)
    mask = _read(context, header + 0x30, 8)
    buckets = _read(context, header + 0x18, 8)
    slot = (buckets + (hashed & mask) * 16) & _U64
    first = _read(context, slot, 8)
    if first == _read(context, header + 8, 8):
        _write(context, slot, 8, node)
        _write(context, slot + 8, 8, node)
    elif first == predecessor:
        _write(context, slot, 8, node)
    elif _read(context, slot + 8, 8) == successor:
        _write(context, slot + 8, 8, node)
    _write(context, output, 8, node)
    _write(context, output + 8, 1, 1)
    return output


def lookup_replay_task_group(
    context: ReplayTaskRebuildStorage,
    header: int,
    output: int,
    key: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> int:
    """Full1412a4560 over current raw addresses; returns the nine-byte OUT slot.

    The key is hashed before allocation but copied after it. Exact integer4,
    byte8 and ordered float0 equality ignore padding. Current map changes,
    partial OUT stores and explicit public aliases retain their source phases.
    Native stack/heap/fault/trap/C++ EH equivalence is excluded.
    """
    _validate(context, calls, header, output, key)
    return _lookup(context, header, output, key, calls, group=True)


def lookup_replay_task_criterion(
    context: ReplayTaskRebuildStorage,
    header: int,
    output: int,
    key: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> int:
    """Full1412a4220 with byte0/integer4/ordered floats8,c/qword10 equality."""
    _validate(context, calls, header, output, key)
    return _lookup(context, header, output, key, calls, group=False)


def _splice(context: ReplayTaskRebuildStorage, node: int, following: int, target: int) -> None:
    previous = _read(context, node + 8, 8)
    _write(context, previous, 8, following)
    next_previous = _read(context, following + 8, 8)
    _write(context, next_previous, 8, target)
    target_previous = _read(context, target + 8, 8)
    _write(context, target_previous, 8, node)
    _write(context, target + 8, 8, next_previous)
    _write(context, following + 8, 8, previous)
    _write(context, node + 8, 8, target_previous)


def _rehash(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    calls: ReplayTaskContainerCalls,
    *,
    group: bool,
) -> None:
    if requested > 1 << 59:
        _error(calls, 0x142D66698, (0x143682938,))
    sentinel = _read(context, header + 8, 8)
    count = 1 << (((((requested - 1) & _U64) | 1).bit_length()) & 63)
    _call(calls, 0x1412BF400 if group else 0x1412BF330, (header + 0x18, count * 2, sentinel))
    _write(context, header + 0x38, 8, count)
    _write(context, header + 0x30, 8, count - 1)
    node = _read(context, _read(context, header + 8, 8), 8)
    while node != sentinel:
        following = _read(context, node, 8)
        hashed = _call(
            calls, 0x1412A36C0 if group else 0x1412A3560, (header, (node + 0x10) & _U64), width=8
        )
        if group:
            mask, buckets = _read(context, header + 0x30, 8), _read(context, header + 0x18, 8)
        else:
            buckets, mask = _read(context, header + 0x18, 8), _read(context, header + 0x30, 8)
        slot = (buckets + (hashed & mask) * 16) & _U64
        first = _read(context, slot, 8)
        if first == sentinel:
            _write(context, slot, 8, node)
            _write(context, slot + 8, 8, node)
        else:
            tail = _read(context, slot + 8, 8)
            byte = _read(context, node + (0x18 if group else 0x10), 1)
            if _equal(context, node + 0x10, tail + 0x10, byte, group=group):
                target = _read(context, tail, 8)
                if target != node:
                    _splice(context, node, following, target)
                _write(context, slot + 8, 8, node)
            else:
                matched = False
                while tail != first:
                    tail = _read(context, tail + 8, 8)
                    if _equal(context, node + 0x10, tail + 0x10, byte, group=group):
                        matched = True
                        break
                if matched:
                    _splice(context, node, following, _read(context, tail, 8))
                else:
                    _splice(context, node, following, tail)
                    _write(context, slot, 8, node)
        node = following


def rehash_replay_task_group(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full1412bfb10; real storage, held sentinel/next and ordered current links.

    Request0 rounds to one bucket and request1 to two, with actual x64 masked
    shift semantics. Finite coherent traversal and source scalar backing are
    premises; malformed cycles have no termination guarantee.
    """
    _validate(context, calls, header)
    _unsigned(requested, 8, "requested group bucket count")
    _rehash(context, header, requested, calls, group=True)


def rehash_replay_task_criterion(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    *,
    calls: ReplayTaskContainerCalls,
) -> None:
    """Full1412bf920, including distinct storage330 and bucket-before-mask read."""
    _validate(context, calls, header)
    _unsigned(requested, 8, "requested criterion bucket count")
    _rehash(context, header, requested, calls, group=False)


def bind_replay_task_group_maps(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    group_out: int,
    criterion_out: int,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind nine map/hash/thunk entries and actual bucket storage recursively.

    Lookups accept native three-address arguments, or effective(map,) plus a
    live writable12/24B key view and caller-owned9B OUT storage. Only that view
    form requires fully known key bytes; direct-address hashing/hits may leave
    padding undefined. Scoped binding does not read bytes at entry and cannot
    suppress body errors. OUT/current pointers are never inferred identities.

    Ceil uses raw XMM0.low32 words in the scalar carrier. Reached current IAT
    reads are mandatory; selected runtime leaf effects must be supplied. This
    creates no saved object, initial World or implicit successful callback.
    """
    if not isinstance(calls, ReplayTaskRebuildCalls) or not callable(bind_local):
        raise ValueError("actual runtime calls and scoped live-local provider required")
    _validate(context, ReplayTaskContainerCalls(calls.call, mxcsr), group_out, criterion_out)
    lookups = {0x1412A4560: lookup_replay_task_group, 0x1412A4220: lookup_replay_task_criterion}
    pairs = {
        0x1412A36C0: hash_replay_task_group,
        0x1412A3560: hash_replay_task_criterion,
        0x1412BFB10: rehash_replay_task_group,
        0x1412BF920: rehash_replay_task_criterion,
    }

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target in lookups:
            if len(args) == 3 and data is None:
                return lookups[target](context, *args, calls=bound)
            if len(args) != 1 or data is None:
                raise ValueError("lookup requires three addresses or map and current key view")
            _view(data, 12 if target == 0x1412A4560 else 24)
            manager = bind_local(data)
            address = manager.__enter__()
            try:
                _unsigned(address, 8, "bound task group key address")
                result = lookups[target](
                    context,
                    args[0],
                    group_out if target == 0x1412A4560 else criterion_out,
                    address,
                    calls=bound,
                )
            except BaseException as error:
                manager.__exit__(type(error), error, error.__traceback__)
                raise
            else:
                manager.__exit__(None, None, None)
            return result
        if target in pairs:
            if len(args) != 2 or data is not None:
                raise ValueError("map hash/rehash requires two scalar arguments")
            return pairs[target](context, *args, calls=bound)
        if target in (0x1412B3370, 0x142D6E453, 0x142D66698):
            if len(args) != 1 or data is not None:
                raise ValueError("float hash or runtime thunk requires one scalar carrier")
            if target == 0x1412B3370:
                return hash_replay_task_group_float(args[0])
            if target == 0x142D6E453:
                return call_replay_task_group_ceil(context, args[0], calls=bound)
            call_replay_task_group_length(context, args[0], calls=bound)
            return None
        if target in _STORAGE:
            assert storage.call is not None
            return storage.call(target, args, data)
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, args, data)

    bound = ReplayTaskContainerCalls(dispatch, mxcsr)
    storage = bind_replay_task_group_storage(
        context, ReplayTaskRebuildCalls(dispatch), bind_local=bind_local
    )
    return ReplayTaskRebuildCalls(dispatch)
