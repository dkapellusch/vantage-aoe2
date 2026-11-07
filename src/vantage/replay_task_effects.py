"""Build54800 TaskList marker/default-record effects and group-clear controller.

Sources: world-envelope/task-rebuild-remaining-dependencies-v1,
task-default-effect-source-v1 and task-default-growth-source-v1. Current
backing/dispatch and actual reached external effects remain required. Native
stack aliases, faults, traps and C++ unwinding are outside this interface.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from .replay_task_bucket_storage import bind_replay_task_bucket_leaves
from .replay_task_containers import ReplayTaskContainerCalls, bind_replay_task_prefix_containers
from .replay_task_group_cleanup import bind_replay_task_group_cleanup
from .replay_task_group_maps import bind_replay_task_group_maps
from .replay_task_prefix import ReplayTaskPrefixScratch, run_replay_task_prefix
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_task_rows import bind_replay_task_rows

_U64 = (1 << 64) - 1
_MAX = (1 << 60) - 1
LocalBinding = Callable[[memoryview], AbstractContextManager[int]]


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *addresses: int,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit task effect calls required")
    for address in addresses:
        _unsigned(address, 8, "task effect address")


def _error(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...] = ()) -> None:
    _call(calls, target, args)
    raise RuntimeError(f"nonreturning helper{target:x} unexpectedly returned")


def set_replay_task_marker(context: ReplayTaskRebuildStorage, value: int) -> None:
    """Full1412483f0: store DL into subject2ca, discarding upper argument bits."""
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task storage required")
    _unsigned(value, 8, "marker register")
    _write(context, context.subject + 0x2CA, 1, value)


def grow_replay_task_vector16(
    context: ReplayTaskRebuildStorage,
    vector: int,
    position: int,
    source_address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full141136840; source_address names the actual current16B descriptor.

    Descriptor snapshot occurs after allocation. Current end is read before
    current begin after the snapshot store; the split suffix rereads end after
    prefix move. Free precedes all three header commits. Valid finite backing
    and successful actual allocation/move/free effects are explicit premises.
    Returned nonreturning helpers raise before verified993/999/99f trap bytes.
    """
    _validate(context, calls, vector, position, source_address)
    begin = _read(context, vector, 8)
    end = _read(context, vector + 8, 8)
    count = (_signed((end - begin) & _U64, 8) >> 4) & _U64
    displacement = (position - begin) & _U64
    # Exact source guard; signed SAR's full-entry range cannot equal _MAX.
    if count == _MAX:
        _error(calls, 0x14113A7A0)
    capacity_end = _read(context, vector + 0x10, 8)
    count = (count + 1) & _U64
    capacity = (_signed((capacity_end - begin) & _U64, 8) >> 4) & _U64
    half = capacity >> 1
    if capacity > (_MAX - half) & _U64:
        grown = _MAX
    else:
        grown = max(count, (capacity + half) & _U64)
        if grown > _MAX:
            _error(calls, 0x1402A9460)
    byte_count = (grown << 4) & _U64
    allocation = _call(calls, 0x1402A94D0, (byte_count,), width=8)
    descriptor = _read(context, source_address, 16)
    inserted = (allocation + (displacement & ~15)) & _U64
    _write(context, inserted, 16, descriptor)
    current_end = _read(context, vector + 8, 8)
    current_begin = _read(context, vector, 8)
    if position == current_end:
        _call(calls, 0x142D6E3DB, (allocation, current_begin, current_end - current_begin))
    else:
        _call(calls, 0x142D6E3DB, (allocation, current_begin, position - current_begin))
        current_end = _read(context, vector + 8, 8)
        _call(calls, 0x142D6E3DB, (inserted + 16, position, current_end - position))
    current_begin = _read(context, vector, 8)
    if current_begin:
        old_size = (_read(context, vector + 0x10, 8) - current_begin) & _U64 & ~15
        pointer = current_begin
        if old_size >= 0x1000:
            pointer = _read(context, current_begin - 8, 8)
            old_size = (old_size + 0x27) & _U64
            if (current_begin - pointer - 8) & _U64 > 31:
                watson = _read(context, 0x14319A060, 8)
                _error(calls, watson, (0, 0, 0, 0, 0))
        _call(calls, 0x142D6BAB4, (pointer, old_size))
    _write(context, vector, 8, allocation)
    _write(context, vector + 8, 8, allocation + (count << 4))
    _write(context, vector + 0x10, 8, allocation + byte_count)
    return inserted


def append_replay_task_default(
    context: ReplayTaskRebuildStorage,
    source_address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full141138ef0; concrete growth, or one16B copy then current-end RMW."""
    _validate(context, calls, source_address)
    vector = (context.subject + 0x448) & _U64
    end = _read(context, vector + 8, 8)
    capacity_end = _read(context, vector + 0x10, 8)
    if end == capacity_end:
        grow_replay_task_vector16(context, vector, end, source_address, calls=calls)
    else:
        descriptor = _read(context, source_address, 16)
        _write(context, end, 16, descriptor)
        _write(context, vector + 8, 8, _read(context, vector + 8, 8) + 16)


def build_replay_task_default(
    context: ReplayTaskRebuildStorage,
    task: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412b7850: fully assigned16B record and actual current virtual820.

    The protected current owner98 resource qword supplies raw lowDWORD bytes;
    no numeric conversion, clamp or owner8 World read occurs. Current virtual
    target dispatch receives(subject,) and its mutable16B local input view.
    """
    _validate(context, calls, task)
    selector = _signed(_read(context, task + 0x10, 2), 2)
    kind = _signed(_read(context, task + 0x24, 2), 2)
    value = selector + 900
    if selector == -1:
        value = _signed(_read(context, task + 0x12, 2), 2)
    owner = _read(context, context.subject + 0x18, 8)
    resource = _signed(_read(context, task + 0x22, 2), 2)
    descriptor = bytearray(
        (kind & 0xFFFFFFFF).to_bytes(4, "little")
        + (value & 0xFFFFFFFF).to_bytes(4, "little")
        + bytes(8)
    )
    table = _read(context, owner + 0x98, 8)
    raw = _read(context, table + resource * 8, 8)
    decoded = (
        ((raw ^ 0x6AE24D3352F04511 ^ 0xC22D6B496D833977) - 0x042AC42976FCCEF5) & _U64
    ) ^ 0xA9834B738A7DD167
    amount = _read(context, task + 0x28, 4)
    vptr = _read(context, context.subject, 8)
    descriptor[8:12] = amount.to_bytes(4, "little")
    descriptor[12:16] = (decoded & 0xFFFFFFFF).to_bytes(4, "little")
    target = _read(context, vptr + 0x820, 8)
    _call(calls, target, (context.subject,), memoryview(descriptor))


def clear_replay_task_groups(
    context: ReplayTaskRebuildStorage,
    map_address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412c5270; actual three subobject destructors/free/fill remain required."""
    _validate(context, calls, map_address)
    if not _read(context, map_address + 0x10, 8):
        return
    head = _read(context, map_address + 8, 8)
    last = _read(context, head + 8, 8)
    _write(context, last, 8, 0)
    node = _read(context, head, 8)
    while node:
        following = _read(context, node, 8)
        _call(calls, 0x1402BD6F0, (node + 0x60,))
        _call(calls, 0x1412A6710, (node + 0x38,))
        _call(calls, 0x1412A6BE0, (node + 0x28,))
        _call(calls, 0x142D6BAB4, (node, 0x78))
        node = following
    head = _read(context, map_address + 8, 8)
    _write(context, head, 8, head)
    head = _read(context, map_address + 8, 8)
    _write(context, head + 8, 8, head)
    _write(context, map_address + 0x10, 8, 0)
    head = _read(context, map_address + 8, 8)
    end = _read(context, map_address + 0x20, 8)
    begin = _read(context, map_address + 0x18, 8)
    local = bytearray(head.to_bytes(8, "little"))
    _call(calls, 0x1412A5BD0, (begin, end), memoryview(local))


def bind_replay_task_effects(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
) -> ReplayTaskRebuildCalls:
    """Bind known bodies; preserve actual current dispatch and live-local identity.

    bind_local must expose the LIVE supplied view in this same backing for the
    full scope, preserving unrelated bytes and prior nested mappings. Entering
    must not probe its bytes. Exit cannot suppress a body error. Unknown effects
    delegate, or fail at reach; neither saved family nor installed vtable is a
    substitute for the builder's current target read.
    """
    _validate(context, calls)
    if not callable(bind_local):
        raise ValueError("actual scoped live-local binding required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        counts = {0x1412483F0: 2, 0x1412B7850: 2, 0x141138EF0: 1, 0x141136840: 3, 0x1412C5270: 1}
        if target not in counts:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != counts[target] or (data is not None) != (target == 0x141138EF0):
            raise ValueError("malformed task effect call")
        if target == 0x141136840:
            return grow_replay_task_vector16(context, *args, calls=bound)
        if target == 0x1412C5270:
            clear_replay_task_groups(context, args[0], calls=bound)
            return None
        subject = ReplayTaskRebuildStorage(args[0], context.read, context.write)
        if target == 0x1412483F0:
            set_replay_task_marker(subject, args[1])
        elif target == 0x1412B7850:
            build_replay_task_default(subject, args[1], calls=bound)
        else:
            if (
                data is None
                or data.ndim != 1
                or data.format != "B"
                or not data.c_contiguous
                or data.readonly
                or len(data) != 16
            ):
                raise ValueError("explicit writable contiguous16B descriptor view required")
            manager = bind_local(data)
            address = manager.__enter__()
            try:
                _unsigned(address, 8, "bound descriptor address")
                append_replay_task_default(subject, address, calls=bound)
            except BaseException as error:
                manager.__exit__(type(error), error, error.__traceback__)
                raise
            else:
                manager.__exit__(None, None, None)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound


def bind_replay_task_execution(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    pair_out: int,
    byte_out: int,
    mxcsr: int,
    prefix_scratch: ReplayTaskPrefixScratch,
) -> ReplayTaskRebuildCalls:
    """Compose actual prefix/container/bucket/default bodies for the outer rebuild.

    OUT tokens require backed9B each; all headers and current identities remain
    explicit inputs. The caller still supplies outer rebuild scratch. Other
    reached containers/clones/virtuals remain mandatory; group cleanup uses the
    six verified bodies through the supplied current backing/runtime bindings.
    Group/criterion maps, row/class append/grow, selector and search entries
    have concrete bindings too. Their sequential lookup OUT tokens reuse
    pair_out/byte_out after prefix return; callers own their actual backing.
    This factory does not construct a restored World or clear its pending flags.
    """
    _validate(context, calls, pair_out, byte_out)
    if not isinstance(prefix_scratch, ReplayTaskPrefixScratch):
        raise ValueError("explicit prefix scratch required")
    container = ReplayTaskContainerCalls(calls.call, mxcsr)
    buckets = bind_replay_task_bucket_leaves(context, container, bind_local=bind_local)
    prefix = bind_replay_task_prefix_containers(
        context, pair_out=pair_out, byte_out=byte_out, calls=buckets
    )
    rows = bind_replay_task_rows(context, calls, bind_local=bind_local)
    groups = bind_replay_task_group_maps(
        context,
        rows,
        bind_local=bind_local,
        group_out=pair_out,
        criterion_out=byte_out,
        mxcsr=mxcsr,
    )
    cleanup = bind_replay_task_group_cleanup(context, groups, bind_local=bind_local)
    effects = bind_replay_task_effects(context, cleanup, bind_local=bind_local)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target == 0x14114BF70:
            if len(args) != 2 or data is not None:
                raise ValueError("malformed task prefix call")
            subject = ReplayTaskRebuildStorage(args[0], context.read, context.write)
            run_replay_task_prefix(
                subject, args[1], mxcsr=mxcsr, scratch=prefix_scratch, calls=prefix
            )
            return None
        assert effects.call is not None
        return effects.call(target, args, data)

    return ReplayTaskRebuildCalls(dispatch)
