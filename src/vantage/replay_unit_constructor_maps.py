"""Build54800 Action/Unit/Base map construction and actual bucket descendants.

Sources: unit-constructor-map-families-source-v1 and the complete original
Base bodies in unit-constructor-support-source-v1. Full original byte/operand
comparisons admit the existing scalar resize/release/fill algorithms. Each
entry keeps its own actual child targets and sentinel size. Current backing,
runtime effects and finite nonwrapping DF0 fills are explicit prerequisites;
physical stack, CPU faults/EH and complete World restoration are excluded.
"""

from __future__ import annotations

from .replay_task_buckets import fill_replay_task_buckets
from .replay_task_group_storage import LocalBinding, _release, _resize
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local

# Constructor: sentinel bytes, initializer, fill, release. These are distinct
# actual entries; equivalence does not replace their source-specific calls.
_FAMILIES = {
    0x141136CA0: (24, 0x14113A360, 0x141136C10, 0x14113B410),
    0x1412A5C60: (24, 0x1412BF190, 0x14126D9A0, 0x1412C6370),
    0x14122DC70: (32, 0x14124AF90, 0x14122DAD0, 0x14124E0B0),
    0x14122DBF0: (48, 0x14124B060, 0x14122DB60, 0x14124E110),
}
_INITIALIZERS = {row[1]: (row[2], row[3]) for row in _FAMILIES.values()}
_FILLS = frozenset(row[2] for row in _FAMILIES.values())
_RELEASES = frozenset(row[3] for row in _FAMILIES.values())


def construct_replay_unit_map(
    context: ReplayTaskRebuildStorage,
    entry: int,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """One complete117B constructor, including real allocation and initializer.

    Only the sentinel's first two links are initialized. Padding and payload
    keep their prior definedness. The initializer receives the current header
    sentinel after publication, and its return never replaces the held map.
    """
    _validate(context, calls, entry, address)
    if entry not in _FAMILIES:
        raise ValueError("unsupported Unit map constructor entry")
    size, initializer, _, _ = _FAMILIES[entry]
    _write(context, address, 4, 0)
    _write(context, address + 8, 8, 0)
    _write(context, address + 16, 8, 0)
    sentinel = _call(calls, 0x142D6BA78, (size,), width=8)
    _write(context, sentinel, 8, sentinel)
    _write(context, sentinel + 8, 8, sentinel)
    _write(context, address + 8, 8, sentinel)
    for offset in (0x18, 0x20, 0x28):
        _write(context, address + offset, 8, 0)
    _write(context, address + 0x30, 8, 7)
    _write(context, address + 0x38, 8, 8)
    _write(context, address, 4, 0x3F800000)
    _call(calls, initializer, (address + 0x18, 16, _read(context, address + 8, 8)))
    return address


def resize_replay_unit_map_buckets(
    context: ReplayTaskRebuildStorage,
    entry: int,
    header: int,
    requested: int,
    value: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full193B initializer; held VALUE and actual current post-allocation headers.

    Reuse fills the held whole range using a real live8B local. Growth calls
    the distinct three-argument release before committing/filling the held new
    allocation. Actual overflow/runtime/import effects remain mandatory.
    """
    _validate(context, calls, entry, header, requested, value)
    if entry not in _INITIALIZERS:
        raise ValueError("unsupported Unit bucket initializer entry")
    fill, release = _INITIALIZERS[entry]
    _resize(context, header, requested, value, calls, fill, release)


def release_replay_unit_map_buckets(
    context: ReplayTaskRebuildStorage,
    entry: int,
    header: int,
    begin: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full85B release: ignored header, actual pointer/capacity and tail free.

    Large backing reads the saved allocation pointer and current Watson IAT.
    No null guard, pointer/header reset or swallowed child failure is invented.
    """
    _validate(context, calls, entry, header, begin, capacity)
    if entry not in _RELEASES:
        raise ValueError("unsupported Unit bucket release entry")
    _release(context, begin, capacity, calls)


def bind_replay_unit_constructor_maps(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
) -> ReplayTaskRebuildCalls:
    """Bind four full map families; unknown reached entries still delegate/refuse.

    Fills accept the native three-scalar ABI or the existing two-scalar plus
    writable8B local-view adapter. Enter does not pre-read that local, preserving
    the original empty and count>=2 early-preload paths. Scalar range semantics
    retain their documented finite nonwrapping DF0 profile.
    """
    _validate(context, calls)
    if not callable(bind_local):
        raise ValueError("actual Unit map local binding required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target in _FAMILIES or target in _INITIALIZERS or target in _RELEASES:
            arity = 1 if target in _FAMILIES else 3
            if len(args) != arity or data is not None:
                raise ValueError("malformed Unit map scalar call")
            if target in _FAMILIES:
                return construct_replay_unit_map(context, target, *args, calls=bound)
            if target in _INITIALIZERS:
                resize_replay_unit_map_buckets(context, target, *args, calls=bound)
            else:
                release_replay_unit_map_buckets(context, target, *args, calls=bound)
            return None
        if target in _FILLS:
            if len(args) == 3 and data is None:
                fill_replay_task_buckets(context, *args)
                return None
            if (
                len(args) != 2
                or data is None
                or data.ndim != 1
                or data.format != "B"
                or not data.c_contiguous
                or data.readonly
                or len(data) != 8
            ):
                raise ValueError("Unit map fill requires native pointers or writable8B local")
            for value in args:
                _unsigned(value, 8, "Unit map fill argument")
            with _local(data, bind_local) as address:
                fill_replay_task_buckets(context, args[0], args[1], address)
            return None
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, args, data)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
