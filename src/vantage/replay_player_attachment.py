"""Build54800 eleven complete attachment bodies,1563B/440 instructions.

Source: player-derived-attachment-source-v1. Actual allocation/free and current
Watson imports remain mandatory. Explicit pointer-fill/node budgets bound the
logical normal-effect profile. Native stack/register/EH/fault/concurrency parity,
the subsequent14134b780 reader and full Player/World/playback are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local

_U64 = (1 << 64) - 1
_MALLOC, _FREE, _WATSON = 0x142D6BA78, 0x142D6BAB4, 0x14319A060


@dataclass(frozen=True, slots=True)
class ReplayPlayerAttachmentScratch:
    """Explicit logical postRSP28 factory,20..2f constructor and20 error seeds."""

    factory: bytes
    constructor: bytes
    error: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in ((self.factory, 8), (self.constructor, 16), (self.error, 8))
        ):
            raise ValueError("explicit8/16/8-byte attachment scratch required")


@dataclass(frozen=True, slots=True)
class ReplayPlayerAttachmentProfile:
    """Per-fill pointer limit and cumulative outer+inner nodes per cleanup."""

    maximum_pointer_words: int
    maximum_node_visits: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (self.maximum_pointer_words, self.maximum_node_visits)
        ):
            raise ValueError("explicit nonnegative integer attachment budgets required")


def _environment(
    bind_local: LocalBinding,
    scratch: ReplayPlayerAttachmentScratch,
    profile: ReplayPlayerAttachmentProfile,
) -> None:
    if not callable(bind_local):
        raise ValueError("actual attachment local binding required")
    if not isinstance(scratch, ReplayPlayerAttachmentScratch):
        raise ValueError("explicit attachment scratch required")
    if not isinstance(profile, ReplayPlayerAttachmentProfile):
        raise ValueError("explicit attachment finite profile required")


def _fill(
    context: ReplayTaskRebuildStorage,
    begin: int,
    count: int,
    value: int,
    profile: ReplayPlayerAttachmentProfile,
) -> None:
    if count > profile.maximum_pointer_words:
        raise UnresolvedReplayTaskRebuild("attachment pointer-fill budget exhausted")
    for _ in range(count):
        _write(context, begin, 8, value)
        begin = (begin + 8) & _U64


def _half(context: ReplayTaskRebuildStorage, address: int, calls: ReplayTaskRebuildCalls) -> None:
    _write(context, address, 4, 0)
    _write(context, address + 8, 8, 0)
    _write(context, address + 16, 8, 0)
    sentinel = _call(calls, _MALLOC, (0x68,), width=8)
    # The source has no sentinel-null guard; even address0 reaches real storage.
    _write(context, sentinel, 8, sentinel)
    _write(context, sentinel + 8, 8, sentinel)
    _write(context, address + 8, 8, sentinel)
    for offset in (0x18, 0x20, 0x28):
        _write(context, address + offset, 8, 0)
    _write(context, address + 0x30, 8, 7)
    _write(context, address + 0x38, 8, 8)
    _write(context, address, 4, 0x3F800000)


def construct_replay_player_attachment(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAttachmentScratch,
    profile: ReplayPlayerAttachmentProfile,
) -> int:
    """Whole462B1416c2270, held object/sentinels and current post-child ranges.

    First-table alternate233e is unreachable with source-held callee-saved EBP0.
    Padding4..7 of each half remains untouched. Fill admission follows header
    publication, and callbacks cannot redirect held owner/return/local registers.
    """
    _validate(context, calls, address)
    _environment(bind_local, scratch, profile)
    with _local(memoryview(bytearray(scratch.constructor)), bind_local) as frame:
        _write(context, frame + 8, 8, address)
        _write(context, frame, 8, address)
        _half(context, address, calls)
        sentinel = _read(context, address + 8, 8)
        replacement = _call(calls, _MALLOC, (0x80,), width=8)
        begin = _read(context, address + 0x18, 8)
        count = (_signed((_read(context, address + 0x28, 8) - begin) & _U64, 8) >> 3) & _U64
        if count:
            _call(calls, 0x1416E8D10, ((address + 0x18) & _U64, begin, count))
        end = (replacement + 0x80) & _U64
        _write(context, address + 0x18, 8, replacement)
        _write(context, address + 0x20, 8, end)
        _write(context, address + 0x28, 8, end)
        _fill(context, replacement, 16, sentinel, profile)
        half = (address + 0x40) & _U64
        _write(context, frame, 8, half)
        _half(context, half, calls)
        sentinel = _read(context, half + 8, 8)
        header = (half + 0x18) & _U64
        begin = _read(context, header, 8)
        end = _read(context, header + 8, 8)
        difference = (end - begin) & _U64
        count = (_signed(difference, 8) >> 3) & _U64
        if count < 16:
            replacement = _call(calls, _MALLOC, (0x80,), width=8)
            current_begin = _read(context, header, 8)
            count = (
                _signed((_read(context, header + 16, 8) - current_begin) & _U64, 8) >> 3
            ) & _U64
            if count:
                _call(calls, 0x1416E8C50, (header, current_begin, count))
            end = (replacement + 0x80) & _U64
            _write(context, header, 8, replacement)
            _write(context, header + 8, 8, end)
            _write(context, header + 16, 8, end)
            _fill(context, replacement, 16, sentinel, profile)
        else:
            count = ((difference + 7) & _U64) >> 3
            if begin > end:
                count = 0
            _fill(context, begin, count, sentinel, profile)
        return address


def create_replay_player_attachment(
    context: ReplayTaskRebuildStorage,
    output: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAttachmentScratch,
) -> int:
    """Whole102B1416c2180; null malloc publishes0, actual child RAX publishes."""
    _validate(context, calls, output)
    if not callable(bind_local) or not isinstance(scratch, ReplayPlayerAttachmentScratch):
        raise ValueError("explicit attachment scratch/local binding required")
    with _local(memoryview(bytearray(scratch.factory)), bind_local) as frame:
        _write(context, frame, 8, output)
        allocation = _call(calls, _MALLOC, (0x80,), width=8)
        _write(context, frame, 8, allocation)
        result = 0
        if allocation:
            for offset in range(0, 128, 16):
                _write(context, allocation + offset, 16, 0)
            result = _call(calls, 0x1416C2270, (allocation,), width=8)
        _write(context, output, 8, result)
        return output


def _destroy(context: ReplayTaskRebuildStorage, old: int, calls: ReplayTaskRebuildCalls) -> None:
    for target, offset in (
        (0x1416C6580, 0x58),
        (0x1416C6730, 0x48),
        (0x1416C6660, 0x18),
        (0x1416C6850, 8),
    ):
        _call(calls, target, ((old + offset) & _U64,))
    _call(calls, _FREE, (old, 0x80))


def move_replay_player_attachment(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Whole97B1416bfe70; source zero then current old read, even for aliases."""
    _validate(context, calls, destination, source)
    replacement = _read(context, source, 8)
    _write(context, source, 8, 0)
    old = _read(context, destination, 8)
    _write(context, destination, 8, replacement)
    if old:
        _destroy(context, old, calls)
    return destination


def clear_replay_player_attachment(
    context: ReplayTaskRebuildStorage, holder: int, *, calls: ReplayTaskRebuildCalls
) -> None:
    """Whole74B1416c6a40; held pointee, holder never cleared or reread."""
    _validate(context, calls, holder)
    old = _read(context, holder, 8)
    if old:
        _destroy(context, old, calls)


def _watson(
    context: ReplayTaskRebuildStorage,
    terminal: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAttachmentScratch,
) -> None:
    with _local(memoryview(bytearray(scratch.error)), bind_local) as frame:
        _write(context, frame, 8, 0)
        target = _read(context, _WATSON, 8)
        _call(terminal, target, (0, 0, 0, 0, _read(context, frame, 8)))
        raise UnresolvedReplayTaskRebuild("attachment Watson returned before outside INT3")


def free_replay_player_attachment_range(
    context: ReplayTaskRebuildStorage,
    ignored_header: int,
    pointer: int,
    count: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAttachmentScratch,
) -> None:
    """Both complete85B1416e8d10/e8c50; RCX is real but unread, R8 wraps."""
    _validate(context, calls, ignored_header, pointer, count)
    _validate(context, imports)
    size = (count * 8) & _U64
    if size >= 0x1000:
        base = _read(context, pointer - 8, 8)
        size = (size + 0x27) & _U64
        if (pointer - base - 8) & _U64 > 31:
            _watson(context, imports, bind_local, scratch)
        pointer = base
    _call(calls, _FREE, (pointer, size))


def clear_replay_player_attachment_vector(
    context: ReplayTaskRebuildStorage,
    header: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAttachmentScratch,
) -> None:
    """Three complete108B bodies; no capacity read/reset on null begin."""
    _validate(context, calls, header)
    _validate(context, imports)
    begin = _read(context, header, 8)
    if not begin:
        return
    size = (_read(context, header + 16, 8) - begin) & (_U64 - 7)
    pointer = begin
    if size >= 0x1000:
        base = _read(context, begin - 8, 8)
        size = (size + 0x27) & _U64
        if (begin - base - 8) & _U64 > 31:
            _watson(context, imports, bind_local, scratch)
        pointer = base
    _call(calls, _FREE, (pointer, size))
    for offset in (0, 8, 16):
        _write(context, header + offset, 8, 0)


def clear_replay_player_attachment_nodes(
    context: ReplayTaskRebuildStorage,
    header: int,
    *,
    calls: ReplayTaskRebuildCalls,
    profile: ReplayPlayerAttachmentProfile,
) -> None:
    """Both complete167B bodies; held nexts and current nested/final sentinels.

    Budget exhaustion occurs before next iteration's first effect. Tail-link
    breaks, earlier children and frees remain; no cycle recovery is invented.
    """
    _validate(context, calls, header)
    if not isinstance(profile, ReplayPlayerAttachmentProfile):
        raise ValueError("explicit attachment finite profile required")
    sentinel = _read(context, header, 8)
    _write(context, _read(context, sentinel + 8, 8), 8, 0)
    node = _read(context, sentinel, 8)
    visits = 0
    while node:
        if visits == profile.maximum_node_visits:
            raise UnresolvedReplayTaskRebuild("attachment node-visit budget exhausted")
        visits += 1
        next_node = _read(context, node, 8)
        _call(calls, 0x14126E8A0, ((node + 0x40) & _U64,))
        nested = _read(context, node + 0x30, 8)
        _write(context, _read(context, nested + 8, 8), 8, 0)
        inner = _read(context, nested, 8)
        while inner:
            if visits == profile.maximum_node_visits:
                raise UnresolvedReplayTaskRebuild("attachment node-visit budget exhausted")
            visits += 1
            next_inner = _read(context, inner, 8)
            _call(calls, _FREE, (inner, 0x18))
            inner = next_inner
        _call(calls, _FREE, (_read(context, node + 0x30, 8), 0x18))
        _call(calls, _FREE, (node, 0x68))
        node = next_node
    _call(calls, _FREE, (_read(context, header, 8), 0x68))


def bind_replay_player_attachment(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAttachmentScratch,
    profile: ReplayPlayerAttachmentProfile,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind exactly eleven source bodies; external calls remain mandatory."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    _environment(bind_local, scratch, profile)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x1416C2180: 1,
            0x1416C2270: 1,
            0x1416BFE70: 2,
            0x1416C6A40: 1,
            0x1416E8D10: 3,
            0x1416E8C50: 3,
            0x1416C6580: 1,
            0x1416C6660: 1,
            0x14126E8A0: 1,
            0x1416C6730: 1,
            0x1416C6850: 1,
        }
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed attachment helper call")
        _validate(context, calls, *args)
        if target == 0x1416C2180:
            return create_replay_player_attachment(
                context, *args, calls=bound, bind_local=bind_local, scratch=scratch
            )
        if target == 0x1416C2270:
            return construct_replay_player_attachment(
                context,
                *args,
                calls=bound,
                bind_local=bind_local,
                scratch=scratch,
                profile=profile,
            )
        if target == 0x1416BFE70:
            return move_replay_player_attachment(context, *args, calls=bound)
        if target == 0x1416C6A40:
            clear_replay_player_attachment(context, *args, calls=bound)
        elif target in (0x1416E8D10, 0x1416E8C50):
            free_replay_player_attachment_range(
                context,
                *args,
                calls=bound,
                imports=terminal,
                bind_local=bind_local,
                scratch=scratch,
            )
        elif target in (0x1416C6580, 0x1416C6660, 0x14126E8A0):
            clear_replay_player_attachment_vector(
                context,
                *args,
                calls=bound,
                imports=terminal,
                bind_local=bind_local,
                scratch=scratch,
            )
        else:
            clear_replay_player_attachment_nodes(context, *args, calls=bound, profile=profile)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
