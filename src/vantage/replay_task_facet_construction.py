"""Build54800 fresh task maps and an explicit partial-object bootstrap profile.

Sources: task-facet-constructor-source-v1 (1411438b0/141143930), retained
1412a5ce0, and task-object-materialization-frontier-v1. The three map bodies
are complete. The facet initializer selects only documented constructor fields;
it does not execute whole object constructors, saved readers or World updates.
"""

from __future__ import annotations

from .replay_task_bucket_storage import bind_replay_task_bucket_leaves
from .replay_task_containers import ReplayTaskContainerCalls
from .replay_task_group_storage import LocalBinding, bind_replay_task_group_storage
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)


def _validate(context: ReplayTaskRebuildStorage, calls: ReplayTaskRebuildCalls) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit actual task construction effects required")


def _construct_map(
    context: ReplayTaskRebuildStorage,
    address: int,
    sentinel_size: int,
    initializer: int,
    calls: ReplayTaskRebuildCalls,
) -> int:
    _validate(context, calls)
    _unsigned(address, 8, "task map address")
    _write(context, address, 4, 0)
    _write(context, address + 8, 8, 0)
    _write(context, address + 0x10, 8, 0)
    sentinel = _call(calls, 0x142D6BA78, (sentinel_size,), width=8)
    _write(context, sentinel, 8, sentinel)
    _write(context, sentinel + 8, 8, sentinel)
    _write(context, address + 8, 8, sentinel)
    for offset in (0x18, 0x20, 0x28):
        _write(context, address + offset, 8, 0)
    _write(context, address + 0x30, 8, 7)
    _write(context, address + 0x38, 8, 8)
    _write(context, address, 4, 0x3F800000)
    value = _read(context, address + 8, 8)
    _call(calls, initializer, (address + 0x18, 16, value))
    return address


def construct_replay_task_pair_map(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full1411438b0:32B sentinel, then actual14114d5c0(header,16,current VALUE).

    Header4..7 and sentinel16..31 are untouched. There is no null allocation
    guard. Prior writes/allocations survive errors; native C++ EH and faults
    are outside the effective storage interface. Return the held map address.
    """
    return _construct_map(context, address, 32, 0x14114D5C0, calls)


def construct_replay_task_byte_map(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full141143930: distinct14114d690 initializer, otherwise the pair phases."""
    return _construct_map(context, address, 32, 0x14114D690, calls)


def construct_replay_task_group_map(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full1412a5ce0:120B sentinel;1412bf400; sentinel16..119 untouched."""
    return _construct_map(context, address, 120, 0x1412BF400, calls)


def initialize_fresh_replay_task_facets(
    context: ReplayTaskRebuildStorage,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Select the fresh Action/Combat/Unit task-facet preservation profile.

    The caller provides fresh owned backing through subject+7bf and admits
    that omitted constructor/reader callbacks have not changed these fields
    before virtual960. This is an adapter over source-defined fields, not any
    complete native object constructor or a serialized post-reader state.
    Other bytes stay untouched, including588's float and header padding.
    Maps invoke their real constructors/children; a reached error stops with
    earlier effects retained. Reusing this on an initialized object is outside
    this fresh profile and would abandon its existing container ownership.
    """
    _validate(context, calls)
    subject = context.subject
    for offset in (0x448, 0x450, 0x458, 0x530, 0x538, 0x540):
        _write(context, subject + offset, 8, 0)
    _call(calls, 0x1411438B0, (subject + 0x548,))
    _write(context, subject + 0x58C, 1, 0)
    _call(calls, 0x141143930, (subject + 0x5D8,))
    for offset in range(0x6AC, 0x6DC, 8):
        _write(context, subject + offset, 8, 0)
    _write(context, subject + 0x6DC, 4, 0)
    _call(calls, 0x1412A5CE0, (subject + 0x6E0,))
    for offset in (0x730, 0x738, 0x740, 0x748, 0x750, 0x7A8, 0x7B0, 0x7B8):
        _write(context, subject + offset, 8, 0)


def bind_replay_task_facet_construction(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind all three constructors with real pair/byte/group bucket children.

    Allocation/free/error effects still come from calls. The explicit bucket
    bridge uses current backing and live scoped locals; unknown targets delegate
    or refuse. MXCSR admits the existing prefix bucket container interface.
    """
    _validate(context, calls)

    def runtime(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, args, data)

    buckets = bind_replay_task_bucket_leaves(
        context, ReplayTaskContainerCalls(runtime, mxcsr), bind_local=bind_local
    )
    children = bind_replay_task_group_storage(
        context, ReplayTaskRebuildCalls(buckets.call), bind_local=bind_local
    )
    constructors = {
        0x1411438B0: construct_replay_task_pair_map,
        0x141143930: construct_replay_task_byte_map,
        0x1412A5CE0: construct_replay_task_group_map,
    }

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in constructors:
            assert children.call is not None
            return children.call(target, args, data)
        if len(args) != 1 or data is not None:
            raise ValueError("map constructor requires one scalar address")
        return constructors[target](context, args[0], calls=bound)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
