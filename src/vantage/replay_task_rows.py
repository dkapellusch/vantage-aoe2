"""Build54800 task row/class vectors, selector leaves and actual find32 body.

Source: world-envelope/task-group-row-source-v1, nine main bodies and the
find32 thunk. Reached allocator/move/free/error effects and current backing are
mandatory. This does not initialize saved objects or execute a World tick.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from .replay_task_containers import _view
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _trunc_div,
    _unsigned,
    _write,
)

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
LocalBinding = Callable[[memoryview], AbstractContextManager[int]]


def _validate(context: ReplayTaskRebuildStorage, *values: int) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task storage required")
    for value in values:
        _unsigned(value, 8, "task row argument")


def _validate_calls(calls: ReplayTaskRebuildCalls) -> None:
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit current task row effects required")


def _error(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...] = ()) -> None:
    _call(calls, target, args)
    raise RuntimeError(f"nonreturning helper{target:x} unexpectedly returned")


def _capacity(used: int, capacity: int, maximum: int, calls: ReplayTaskRebuildCalls) -> int:
    half = capacity >> 1
    if capacity > (maximum - half) & _U64:
        return maximum
    result = max((used + 1) & _U64, (capacity + half) & _U64)
    if result > maximum:
        _error(calls, 0x1402A9460)
    return result


def _release(
    context: ReplayTaskRebuildStorage,
    vector: int,
    stride: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    begin = _read(context, vector, 8)
    if not begin:
        return
    difference = (_read(context, vector + 16, 8) - begin) & _U64
    size = (
        difference & ~3
        if stride == 4
        else (_trunc_div(_signed(difference, 8), stride) * stride) & _U64
    )
    pointer = begin
    if size >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        size = (size + 0x27) & _U64
        if (begin - pointer - 8) & _U64 > 31:
            _error(calls, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
    _call(calls, 0x142D6BAB4, (pointer, size))


def _move(
    context: ReplayTaskRebuildStorage,
    vector: int,
    position: int,
    inserted: int,
    allocation: int,
    stride: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    end = _read(context, vector + 8, 8)
    begin = _read(context, vector, 8)
    if position == end:
        _call(calls, 0x142D6E3DB, (allocation, begin, end - begin))
    else:
        _call(calls, 0x142D6E3DB, (allocation, begin, position - begin))
        end = _read(context, vector + 8, 8)
        _call(calls, 0x142D6E3DB, (inserted + stride, position, end - position))


def commit_replay_task_vector4(
    context: ReplayTaskRebuildStorage,
    vector: int,
    allocation: int,
    count: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1402ba840: release CURRENT allocation before ordered held-value commits."""
    _validate(context, vector, allocation, count, capacity)
    _validate_calls(calls)
    _release(context, vector, 4, calls)
    _write(context, vector, 8, allocation)
    _write(context, vector + 8, 8, allocation + count * 4)
    _write(context, vector + 16, 8, allocation + capacity * 4)


def _append(
    context: ReplayTaskRebuildStorage,
    vector: int,
    source: int,
    width: int,
    calls: ReplayTaskRebuildCalls,
) -> int:
    _validate(context, vector, source)
    _validate_calls(calls)
    capacity_end = _read(context, vector + 16, 8)
    end = _read(context, vector + 8, 8)
    if end != capacity_end:
        value = _read(context, source, width)
        _write(context, end, 4, _signed(value, 2) if width == 2 else value)
        current_end = _read(context, vector + 8, 8)
        _write(context, vector + 8, 8, current_end + 4)
        return current_end
    begin = _read(context, vector, 8)
    count = (_signed((end - begin) & _U64, 8) >> 2) & _U64
    maximum = _U64 >> 2
    if count == maximum:
        _error(calls, 0x1402BA950)
    old_capacity = (_signed((capacity_end - begin) & _U64, 8) >> 2) & _U64
    capacity = _capacity(count, old_capacity, maximum, calls)
    allocation = _call(calls, 0x1402A94D0, (capacity * 4,), width=8)
    inserted = (allocation + count * 4) & _U64
    value = _read(context, source, width)
    _write(context, inserted, 4, _signed(value, 2) if width == 2 else value)
    _move(context, vector, end, inserted, allocation, 4, calls)
    _call(calls, 0x1402BA840, (vector, allocation, (count + 1) & _U64, capacity))
    return inserted


def append_replay_task_index(
    context: ReplayTaskRebuildStorage,
    vector: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full1412a57e0: read a DWORD, after allocation if full; append without dedup."""
    return _append(context, vector, source, 4, calls)


def append_replay_task_class_word(
    context: ReplayTaskRebuildStorage,
    vector: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full1412a56c0: read signed WORD at actual address; store sign-extended DWORD."""
    return _append(context, vector, source, 2, calls)


def _grow(
    context: ReplayTaskRebuildStorage,
    vector: int,
    position: int,
    source: int,
    stride: int,
    calls: ReplayTaskRebuildCalls,
) -> int:
    _validate(context, vector, position, source)
    _validate_calls(calls)
    begin = _read(context, vector, 8)
    end = _read(context, vector + 8, 8)
    displacement = _trunc_div(_signed((position - begin) & _U64, 8), stride)
    used = _trunc_div(_signed((end - begin) & _U64, 8), stride) & _U64
    maximum = _U64 // stride
    if used == maximum:
        _error(calls, 0x1412C0820 if stride == 40 else 0x1412C0800)
    capacity_end = _read(context, vector + 16, 8)
    old_capacity = _trunc_div(_signed((capacity_end - begin) & _U64, 8), stride) & _U64
    capacity = _capacity(used, old_capacity, maximum, calls)
    allocation = _call(calls, 0x1402A94D0, (capacity * stride,), width=8)
    inserted = (allocation + displacement * stride) & _U64
    for offset, width in ((0, 16), (16, 16), (32, stride - 32)):
        _write(context, inserted + offset, width, _read(context, source + offset, width))
    _move(context, vector, position, inserted, allocation, stride, calls)
    _release(context, vector, stride, calls)
    _write(context, vector, 8, allocation)
    _write(context, vector + 8, 8, allocation + ((used + 1) & _U64) * stride)
    _write(context, vector + 16, 8, allocation + capacity * stride)
    return inserted


def grow_replay_task_rule_rows(
    context: ReplayTaskRebuildStorage,
    vector: int,
    position: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full1412a3ca0: unconditional40B grow/insert, copying16+16+8 in native order."""
    return _grow(context, vector, position, source, 40, calls)


def grow_replay_task_health_rows(
    context: ReplayTaskRebuildStorage,
    vector: int,
    position: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full1412a3ab0: unconditional48B grow/insert, copying three ordered16B chunks."""
    return _grow(context, vector, position, source, 48, calls)


def find_replay_task_class(
    context: ReplayTaskRebuildStorage,
    begin: int,
    end: int,
    value: int,
) -> int:
    """Full142d683d0: current feature bits, vector operands and masked AVX tail.

    An ordered, nonwrapping whole-DWORD range is the admitted profile. Every
    admitted call reads featureDWORD144114154, including empty ranges. Full
    SSE/AVX operands use16/32B reads. Tail mask is current32B storage; only lanes
    with their sign bit set read data. Ascending masked-lane access is a coherent
    scalar projection, without hardware fault/concurrency/upper-lane claims.
    """
    _validate(context, begin, end, value)
    if end < begin or (end - begin) % 4:
        raise ValueError("ordered nonwrapping whole-DWORD range required")
    feature = _read(context, 0x144114154, 4)
    size = end - begin
    value &= _U32
    width = 32 if size >= 32 and feature & 0x20 else 16 if size >= 16 and feature & 4 else 0
    if width:
        stop = begin + size // width * width
        while begin != stop:
            block = _read(context, begin, width)
            for offset in range(0, width, 4):
                if (block >> (offset * 8)) & _U32 == value:
                    return begin + offset
            begin += width
    if width == 32:
        tail = size & 28
        if tail:
            mask = _read(context, 0x14365D550 - tail, 32)
            matches = 0
            for lane in range(8):
                lane_mask = (mask >> (lane * 32)) & _U32
                word = _read(context, begin + lane * 4, 4) if lane_mask >> 31 else 0
                if word == value:
                    for byte in range(4):
                        matches |= ((lane_mask >> (byte * 8 + 7)) & 1) << (lane * 4 + byte)
            if matches:
                return (begin + (matches & -matches).bit_length() - 1) & _U64
            begin += tail
        return begin
    while begin != end:
        if _read(context, begin, 4) == value:
            return begin
        begin += 4
    return begin


def bind_replay_task_rows(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
) -> ReplayTaskRebuildCalls:
    """Bind concrete rows/search/selectors with native addresses or live input views.

    57e0 accepts(vector,value_address) or(vector,)+writable4B view. Grow40/48
    accept(vector,position,source_address) or(vector,position)+live40/48B view.
    WORD append always receives its real2B source address. The find thunk routes
    the concrete search body. Selector outputs are raw EAX or predicate AL only;
    encode also accepts the rebuild caller's unused second scalar argument.
    Unknown runtime effects delegate or fail at reach. Scoped views stay live
    until exit and body errors cannot be suppressed by their mapping manager.
    """
    _validate(context)
    if not isinstance(calls, ReplayTaskRebuildCalls) or not callable(bind_local):
        raise ValueError("actual runtime calls and scoped live-local provider required")
    arities = {0x1412A57E0: 2, 0x1412A56C0: 2, 0x1412A3CA0: 3, 0x1412A3AB0: 3}
    views = {0x1412A57E0: 4, 0x1412A3CA0: 40, 0x1412A3AB0: 48}

    def body(target: int, args: tuple[int, ...]) -> int:
        if target == 0x1412A57E0:
            return append_replay_task_index(context, *args, calls=bound)
        if target == 0x1412A56C0:
            return append_replay_task_class_word(context, *args, calls=bound)
        if target == 0x1412A3CA0:
            return grow_replay_task_rule_rows(context, *args, calls=bound)
        return grow_replay_task_health_rows(context, *args, calls=bound)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target in arities:
            count = arities[target]
            if len(args) == count and data is None:
                return body(target, args)
            if target not in views or len(args) != count - 1 or data is None:
                raise ValueError("row helper requires native addresses or its exact live view")
            _view(data, views[target])
            manager = bind_local(data)
            address = manager.__enter__()
            try:
                _unsigned(address, 8, "bound task row input address")
                result = body(target, (*args, address))
            except BaseException as error:
                manager.__exit__(type(error), error, error.__traceback__)
                raise
            else:
                manager.__exit__(None, None, None)
            return result
        if target in (0x142D683D0, 0x142D6A0D0):
            if len(args) != 3 or data is not None:
                raise ValueError("find32 requires three scalar arguments")
            if target == 0x142D6A0D0:
                return _call(bound, 0x142D683D0, args, width=8)
            return find_replay_task_class(context, *args)
        if target == 0x1402BA840:
            if len(args) != 4 or data is not None:
                raise ValueError("vector commit requires four scalar arguments")
            commit_replay_task_vector4(context, *args, calls=bound)
            return None
        if target in (0x1410B9F00, 0x1410BD060, 0x1410BA3D0):
            if len(args) not in ((1, 2) if target == 0x1410B9F00 else (1,)) or data is not None:
                raise ValueError("selector requires its scalar register inputs")
            _validate(context, *args)
            if target == 0x1410BA3D0:
                return int(((args[0] - 900) & _U32) <= 99)
            return (args[0] + (900 if target == 0x1410B9F00 else -900)) & _U32
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, args, data)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
