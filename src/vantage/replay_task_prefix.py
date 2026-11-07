"""Build54800 TaskList prefix14114bf70 with concrete task getter/selector leaves.

Ports complete157/162 caller flow over current scalar backing. Reached map
clear/lookup and vector growth effects require real implementations. Native
scratch seeds are explicit; no restored state or completed World is inferred.
Source: world-envelope/first-building-transform-postreader-frontier/
native-second-three-20261018/14114bf70.asm.tsv and task-prefix-helper-source-v1.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .replay_binary32 import compare_binary32, multiply_binary32, signed32_binary32
from .replay_task_rebuild import (
    ReplayTaskRebuildStorage,
    _cvtt,
    _get,
    _put,
    _read,
    _signed,
    _unsigned,
    _write,
)

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1


class UnresolvedReplayTaskPrefix(ValueError):
    """A reached prefix container implementation has no current binding."""


@dataclass(frozen=True, slots=True)
class ReplayTaskPrefixScratch:
    """Initial64B descriptor and two distinct3B metadata-padding locals.

    Descriptor offsets15..17 and39..3f (hex) are unwritten by157. The full64B
    record persists across tasks and is exposed to append growth as a mutable
    view. first_padding is nativeRSP95..97; max_padding isRSP8d..8f. Both metadata
    paths write lowf32 plus byte4=1 and these three high bytes to subject588.
    Seeds specify actual current scratch, with no default zero initialization.
    """

    descriptor: bytes
    first_padding: bytes
    max_padding: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != width
            for value, width in (
                (self.descriptor, 64),
                (self.first_padding, 3),
                (self.max_padding, 3),
            )
        ):
            raise ValueError("explicit64/3/3-byte task prefix scratch seeds required")


@dataclass(frozen=True, slots=True)
class ReplayTaskPrefixCalls:
    """Actual container dispatcher: call(target,args,key,value)->optional token.

    Clears1510f0/151180 receive args=(map,). Lookup1434c0 receives args=(map,),
    key8B and a DIRECT mutable4B view of descriptor30. Lookup143260 receives
    args=(map,), key1B and current local task pointer8B. Both return the bound
    caller hidden-OUT-storage address token, whose byte8 is inserted and qword0
    is the node. This effective OUT token abstracts RDX stack storage; it is not
    an observation or premise about native RAX. Lookup callbacks must perform
    actual result writes. Append143090 receives args=(vector,currentEnd), key
    as the shared64B descriptor view and no value. Void returns are ignored.

    None marks an unavailable dispatcher. A supplied dispatcher must raise for
    any unavailable reached target. Exceptions retain prior writes and helper
    effects. Copied keys and shared value views preserve their source aliases;
    literal stack addresses, escaped locals and accesses beyond views are
    excluded. Observer callbacks do not establish real container effects.
    """

    call: Callable[[int, tuple[int, ...], memoryview | None, memoryview | None], int | None] | None

    def __post_init__(self) -> None:
        if self.call is not None and not callable(self.call):
            raise ValueError("actual prefix helper dispatcher or unavailable binding required")


def _call(
    calls: ReplayTaskPrefixCalls,
    target: int,
    args: tuple[int, ...],
    key: memoryview | None = None,
    value: memoryview | None = None,
    *,
    out: bool = False,
) -> int:
    if calls.call is None:
        raise UnresolvedReplayTaskPrefix(f"reached{target:x} is unavailable")
    result = calls.call(target, tuple(arg & _U64 for arg in args), key, value)
    if not out:
        return 0
    if result is None:
        raise ValueError(f"helper{target:x} requires bound caller OUT storage")
    _unsigned(result, 8, "prefix hidden OUT storage")
    return result


def _score(context: ReplayTaskRebuildStorage, task: int) -> int:
    # 1410b1a20 returns raw XMM0, including a fixed -1.0 for null.
    return _read(context, task + 0x28, 4) if task else 0xBF800000


def _flags(context: ReplayTaskRebuildStorage, task: int) -> int:
    # 1410b1a10 promises AL0 for null; unused upper RAX bits are irrelevant.
    return _read(context, task + 0x15, 1) if task else 0


def _maxss(destination: int, source: int) -> int:
    # Legacy MAXSS returns the raw source on equality OR unordered, even sNaN.
    return destination if compare_binary32(destination, source) == 1 else source


def _task162(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskPrefixCalls,
    task: int,
) -> None:
    for index in range(4):
        key = bytearray([_read(context, 0x1432A70C0 + index, 1)])
        current_task = bytearray(task.to_bytes(8, "little"))
        flags = _flags(context, task)
        score = _score(context, _get(current_task, 0, 8))
        # COMISS(+0,score)/JA rejects ordered negative only. NaNs proceed.
        if compare_binary32(0, score) == 1:
            continue
        if flags and not key[0] & flags:
            continue
        output = _call(
            calls,
            0x141143260,
            ((context.subject + 0x5D8) & _U64,),
            memoryview(key),
            memoryview(current_task),
            out=True,
        )
        if _read(context, output + 8, 1):
            continue
        node = _read(context, output, 8)
        old_task = _read(context, node + 0x18, 8)
        old_score = _score(context, old_task)
        if compare_binary32(old_score, score) == 1:
            _write(context, node + 0x18, 8, _get(current_task, 0, 8))


def _metadata(
    context: ReplayTaskRebuildStorage,
    scratch: ReplayTaskPrefixScratch,
    descriptor: bytearray,
    count: int,
) -> None:
    has_value = _read(context, context.subject + 0x58C, 1)
    product = multiply_binary32(signed32_binary32(_signed(count, 4)), _get(descriptor, 0xC, 4))
    padding = scratch.first_padding
    if has_value:
        product = _maxss(product, _read(context, context.subject + 0x588, 4))
        padding = scratch.max_padding
    raw = product | 1 << 32 | int.from_bytes(padding, "little") << 40
    _write(context, context.subject + 0x588, 8, raw)


def _task157(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskPrefixCalls,
    scratch: ReplayTaskPrefixScratch,
    descriptor: bytearray,
    task: int,
) -> None:
    selected = _signed(_read(context, task + 0x10, 2), 2)
    class_mode = ((selected + 999) & 0xFFFF) > 1998
    if class_mode:
        selector = selected
    elif selected < 0:
        alternate = _signed(_read(context, task + 0x12, 2), 2)
        selector = alternate if alternate >= 0 else -1
    else:
        selector = (selected + 900) & _U32  # Actual ECX-only1410b9f00 leaf.
    zero_test = _read(context, task + 0x30, 4)
    linked = _read(context, task + 0x48, 8)
    kind = _read(context, task + 0x19, 1)
    count = _signed(_read(context, task + 0x36, 2), 2)
    extra = _signed(_read(context, task + 0x34, 2), 2)
    tail = _read(context, task + 0x78, 4)
    head = _read(context, task + 0x60, 4)
    flags = _read(context, task + 0x15, 1)
    is_zero = int(compare_binary32(zero_test, 0) == 0)
    amount = _read(context, task + 0x28, 4)
    _put(descriptor, 0, 4, selector)
    _put(descriptor, 4, 4, _signed(_read(context, task + 0x22, 2), 2))
    _put(descriptor, 0xC, 4, amount)
    descriptor[0x14] = is_zero
    _put(descriptor, 0x18, 4, flags)
    _put(descriptor, 0x1C, 4, head)
    _put(descriptor, 0x20, 4, tail)
    _put(descriptor, 0x24, 4, extra)
    _put(descriptor, 0x28, 8, linked)
    _put(descriptor, 0x30, 4, count)
    _put(descriptor, 0x34, 4, kind)
    descriptor[0x38] = int(class_mode)
    _put(descriptor, 0x10, 4, _cvtt(_read(context, task + 0x2C, 4)))
    _put(descriptor, 8, 4, _cvtt(_read(context, task + 0x1C, 4)))
    if count > 0:
        key = bytearray(descriptor[0x34:0x38] + descriptor[8:12])
        output = _call(
            calls,
            0x1411434C0,
            ((context.subject + 0x548) & _U64,),
            memoryview(key),
            memoryview(descriptor)[0x30:0x34],
            out=True,
        )
        inserted = _read(context, output + 8, 1)
        current_count = _get(descriptor, 0x30, 4)
        if not inserted:
            node = _read(context, output, 8)
            old_count = _signed(_read(context, node + 0x18, 4), 4)
            if _signed(current_count, 4) > old_count:
                _write(context, node + 0x18, 4, current_count)
                current_count = _get(descriptor, 0x30, 4)
        if _get(descriptor, 8, 4) == 10:
            _metadata(context, scratch, descriptor, current_count)
    vector = (context.subject + 0x530) & _U64
    end = _read(context, vector + 8, 8)
    if end == _read(context, vector + 0x10, 8):
        _call(calls, 0x141143090, (vector, end), memoryview(descriptor))
    else:
        for offset in range(0, 64, 16):
            _write(context, end + offset, 16, _get(descriptor, offset, 16))
        _write(context, vector + 8, 8, _read(context, vector + 8, 8) + 64)


def run_replay_task_prefix(
    context: ReplayTaskRebuildStorage,
    task_list: int,
    *,
    mxcsr: int,
    scratch: ReplayTaskPrefixScratch,
    calls: ReplayTaskPrefixCalls,
) -> None:
    """Run full14114bf70 before the outer master-rule rebuild.

    Always clears530 vector, invokes both map clears and writes58c=0 before
    checking the original held TaskList. Type157 appends64B descriptors and
    conditionally updates map/metadata;162 examines four current literal keys
    with concrete current task getters. Other/null tasks skip. Both entry and
    tail use current TaskList fields; the signed32 counter and separateu64 byte
    offset wrap independently. Source order and prior effects on failure hold.

    Coherent current backing, valid vectors and real reached containers are
    required. Default masked nearest-even MXCSR with DAZ/FTZoff is admitted;
    FPstatus/traps/upper lanes and literal native stack/fault parity are excluded.
    No initial World pending flag or tick integration is changed automatically.
    """
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task prefix scalar storage required")
    if not isinstance(scratch, ReplayTaskPrefixScratch):
        raise ValueError("explicit task prefix scratch seeds required")
    if not isinstance(calls, ReplayTaskPrefixCalls):
        raise ValueError("explicit actual prefix helper bindings required")
    _unsigned(task_list, 8, "TaskList")
    _unsigned(mxcsr, 4, "MXCSR")
    if mxcsr & ~0x3F != 0x1F80:
        raise ValueError("masked nearest-even MXCSR, DAZ/FTZoff required")
    descriptor = bytearray(scratch.descriptor)
    vector = (context.subject + 0x530) & _U64
    begin = _read(context, vector, 8)
    if begin != _read(context, vector + 8, 8):
        _write(context, vector + 8, 8, begin)
    _call(calls, 0x1411510F0, ((context.subject + 0x548) & _U64,))
    _call(calls, 0x141151180, ((context.subject + 0x5D8) & _U64,))
    _write(context, context.subject + 0x58C, 1, 0)
    if not task_list:
        return
    end = _read(context, task_list + 0x10, 8)
    begin = _read(context, task_list + 8, 8)
    if end == begin or not (_signed((end - begin) & _U64, 8) >> 3):
        return
    ordinal = offset = 0
    while True:
        task = _read(context, begin + offset, 8)
        if task:
            kind = _signed(_read(context, task + 0xE, 2), 2)
            if kind == 157:
                _task157(context, calls, scratch, descriptor, task)
            elif kind == 162:
                _task162(context, calls, task)
        ordinal = (ordinal + 1) & _U32
        offset = (offset + 8) & _U64
        begin = _read(context, task_list + 8, 8)
        end = _read(context, task_list + 0x10, 8)
        count = (_signed((end - begin) & _U64, 8) >> 3) & _U64
        if (_signed(ordinal, 4) & _U64) >= count:
            return
