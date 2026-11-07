"""Build54800 tracker224B, insertion603B and length-error17B source ports.

These are current-address red/black tree operations, with real allocation and
an explicit40-byte caller frame seed. Coherent finite tree backing is required;
native stack/register, fault/EH/concurrency and complete World claims are excluded.
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
_LOOKUP, _INSERT, _LENGTH = 0x1411445A0, 0x14114DB00, 0x1402AB280


@dataclass(frozen=True, slots=True)
class ReplayCombatTrackerScratch:
    """Explicit40-byte working-RSP frame; descriptor padding3c..3f is unassigned.

    ParentQWORD30 and sideDWORD38 are written before search. After allocation,
    the actual16B at30 (including seed/current padding) is copied to20, replacing
    header20 and zero28. It remains live during the full insertion child.
    """

    lookup: bytes

    def __post_init__(self) -> None:
        if type(self.lookup) is not bytes or len(self.lookup) != 0x40:
            raise ValueError("explicit40-byte Combat tracker frame required")


def fail_replay_combat_tracker_length(
    context: ReplayTaskRebuildStorage,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full17B helper: current length-error IAT target, fixed literal RCX.

    Selected imported target is terminal: no recursive interpretation as an
    owned thunk. A returned nonreturning helper refuses before verified INT3.
    """
    _validate(context, calls)
    target = _read(context, 0x1431992A0, 8)
    _call(calls, target, (0x143677420,))
    raise RuntimeError("nonreturning Combat tracker length helper returned")


def insert_replay_combat_tracker(
    context: ReplayTaskRebuildStorage,
    header: int,
    descriptor: int,
    node: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full603B insertion/fixup, returning held new-node RAX.

    Link0/parent8/link10, color18 and nil19 retain exact source read/store
    phases. Held sentinel and current header-root reads are distinct; this
    function does not inspect key/value/padding or call a runtime helper.
    """
    _validate(context, calls, header, descriptor, node)
    _write(context, header + 8, 8, _read(context, header + 8, 8) + 1)
    sentinel = _read(context, header, 8)
    parent = _read(context, descriptor, 8)
    _write(context, node + 8, 8, parent)
    if parent == sentinel:
        _write(context, sentinel, 8, node)
        _write(context, sentinel + 8, 8, node)
        _write(context, sentinel + 16, 8, node)
        _write(context, node + 24, 1, 1)
        return node
    if _read(context, descriptor + 8, 4) == 0:
        _write(context, parent + 16, 8, node)
        if parent == _read(context, sentinel + 16, 8):
            _write(context, sentinel + 16, 8, node)
    else:
        _write(context, parent, 8, node)
        if parent == _read(context, sentinel, 8):
            _write(context, sentinel, 8, node)
    cursor = node
    parent = _read(context, node + 8, 8)
    while _read(context, parent + 24, 1) == 0:
        parent = _read(context, cursor + 8, 8)
        grandparent = _read(context, parent + 8, 8)
        other = _read(context, grandparent, 8)
        if parent == other:
            other = _read(context, grandparent + 16, 8)
            if _read(context, other + 24, 1) == 0:
                _write(context, parent + 24, 1, 1)
                _write(context, other + 24, 1, 1)
                parent = _read(context, cursor + 8, 8)
                ancestor = _read(context, parent + 8, 8)
                _write(context, ancestor + 24, 1, 0)
                parent = _read(context, cursor + 8, 8)
                cursor = _read(context, parent + 8, 8)
            else:
                pivot = _read(context, parent + 16, 8)
                if cursor == pivot:
                    child = _read(context, pivot, 8)
                    cursor = parent
                    _write(context, parent + 16, 8, child)
                    child = _read(context, pivot, 8)
                    if _read(context, child + 25, 1) == 0:
                        _write(context, child + 8, 8, parent)
                    ancestor = _read(context, parent + 8, 8)
                    _write(context, pivot + 8, 8, ancestor)
                    current_head = _read(context, header, 8)
                    if parent == _read(context, current_head + 8, 8):
                        _write(context, current_head + 8, 8, pivot)
                    else:
                        ancestor = _read(context, parent + 8, 8)
                        if parent == _read(context, ancestor, 8):
                            _write(context, ancestor, 8, pivot)
                        else:
                            _write(context, ancestor + 16, 8, pivot)
                    _write(context, pivot, 8, parent)
                    _write(context, parent + 8, 8, pivot)
                parent = _read(context, cursor + 8, 8)
                _write(context, parent + 24, 1, 1)
                parent = _read(context, cursor + 8, 8)
                ancestor = _read(context, parent + 8, 8)
                _write(context, ancestor + 24, 1, 0)
                parent = _read(context, cursor + 8, 8)
                ancestor = _read(context, parent + 8, 8)
                pivot = _read(context, ancestor, 8)
                child = _read(context, pivot + 16, 8)
                _write(context, ancestor, 8, child)
                child = _read(context, pivot + 16, 8)
                if _read(context, child + 25, 1) == 0:
                    _write(context, child + 8, 8, ancestor)
                upper = _read(context, ancestor + 8, 8)
                _write(context, pivot + 8, 8, upper)
                current_head = _read(context, header, 8)
                if ancestor == _read(context, current_head + 8, 8):
                    _write(context, current_head + 8, 8, pivot)
                else:
                    upper = _read(context, ancestor + 8, 8)
                    if ancestor == _read(context, upper + 16, 8):
                        _write(context, upper + 16, 8, pivot)
                    else:
                        _write(context, upper, 8, pivot)
                _write(context, pivot + 16, 8, ancestor)
                _write(context, ancestor + 8, 8, pivot)
        elif _read(context, other + 24, 1) == 0:
            _write(context, parent + 24, 1, 1)
            _write(context, other + 24, 1, 1)
            parent = _read(context, cursor + 8, 8)
            ancestor = _read(context, parent + 8, 8)
            _write(context, ancestor + 24, 1, 0)
            parent = _read(context, cursor + 8, 8)
            cursor = _read(context, parent + 8, 8)
        else:
            pivot = _read(context, parent, 8)
            if cursor == pivot:
                child = _read(context, pivot + 16, 8)
                cursor = parent
                _write(context, parent, 8, child)
                child = _read(context, pivot + 16, 8)
                if _read(context, child + 25, 1) == 0:
                    _write(context, child + 8, 8, parent)
                ancestor = _read(context, parent + 8, 8)
                _write(context, pivot + 8, 8, ancestor)
                current_head = _read(context, header, 8)
                if parent == _read(context, current_head + 8, 8):
                    _write(context, current_head + 8, 8, pivot)
                else:
                    ancestor = _read(context, parent + 8, 8)
                    if parent == _read(context, ancestor + 16, 8):
                        _write(context, ancestor + 16, 8, pivot)
                    else:
                        _write(context, ancestor, 8, pivot)
                _write(context, pivot + 16, 8, parent)
                _write(context, parent + 8, 8, pivot)
            parent = _read(context, cursor + 8, 8)
            _write(context, parent + 24, 1, 1)
            parent = _read(context, cursor + 8, 8)
            ancestor = _read(context, parent + 8, 8)
            _write(context, ancestor + 24, 1, 0)
            parent = _read(context, cursor + 8, 8)
            ancestor = _read(context, parent + 8, 8)
            pivot = _read(context, ancestor + 16, 8)
            child = _read(context, pivot, 8)
            _write(context, ancestor + 16, 8, child)
            child = _read(context, pivot, 8)
            if _read(context, child + 25, 1) == 0:
                _write(context, child + 8, 8, ancestor)
            upper = _read(context, ancestor + 8, 8)
            _write(context, pivot + 8, 8, upper)
            current_head = _read(context, header, 8)
            if ancestor == _read(context, current_head + 8, 8):
                _write(context, current_head + 8, 8, pivot)
            else:
                upper = _read(context, ancestor + 8, 8)
                if ancestor == _read(context, upper, 8):
                    _write(context, upper, 8, pivot)
                else:
                    _write(context, upper + 16, 8, pivot)
            _write(context, pivot, 8, ancestor)
            _write(context, ancestor + 8, 8, pivot)
        parent = _read(context, cursor + 8, 8)
    root = _read(context, sentinel + 8, 8)
    _write(context, root + 24, 1, 1)
    return node


def lookup_replay_combat_tracker(
    context: ReplayTaskRebuildStorage,
    header: int,
    key: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayCombatTrackerScratch,
) -> int:
    """Full224B signed-i32 lookup/insert, returning the direct qword value slot."""
    _validate(context, calls, header, key)
    if not callable(bind_local) or not isinstance(scratch, ReplayCombatTrackerScratch):
        raise ValueError("actual tracker local binding and40-byte seed required")
    with _local(memoryview(bytearray(scratch.lookup)), bind_local) as frame:
        sentinel = _read(context, header, 8)
        cursor = _read(context, sentinel + 8, 8)
        _write(context, frame + 0x30, 8, cursor)
        _write(context, frame + 0x38, 4, 0)
        candidate = sentinel
        if _read(context, cursor + 25, 1) == 0:
            held_key = _signed(_read(context, key, 4), 4)
            while True:
                _write(context, frame + 0x30, 8, cursor)
                if _signed(_read(context, cursor + 28, 4), 4) < held_key:
                    _write(context, frame + 0x38, 4, 0)
                    cursor = (cursor + 16) & _U64
                else:
                    _write(context, frame + 0x38, 4, 1)
                    candidate = cursor
                cursor = _read(context, cursor, 8)
                if _read(context, cursor + 25, 1):
                    break
        if _read(context, candidate + 25, 1) == 0:
            found = _signed(_read(context, candidate + 28, 4), 4)
            if _signed(_read(context, key, 4), 4) >= found:
                return (candidate + 32) & _U64
        if _read(context, header + 8, 8) == 0x0666666666666666:
            _call(calls, _LENGTH, ())
            raise RuntimeError("nonreturning Combat tracker length helper returned")
        _write(context, frame + 0x20, 8, header)
        _write(context, frame + 0x28, 8, 0)
        node = _call(calls, 0x142D6BA78, (40,), width=8)
        _write(context, node + 28, 4, _read(context, key, 4))
        _write(context, node + 32, 8, 0)
        for offset in (0, 8, 16):
            _write(context, node + offset, 8, sentinel)
        _write(context, node + 24, 2, 0)
        descriptor = _read(context, frame + 0x30, 16)
        _write(context, frame + 0x20, 16, descriptor)
        inserted = _call(calls, _INSERT, (header, frame + 0x20, node), width=8)
        return (inserted + 32) & _U64


def bind_replay_combat_saved_tracker(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: ReplayCombatTrackerScratch,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind three actual entries; current-IAT selected target uses terminal imports."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not callable(bind_local) or not isinstance(scratch, ReplayCombatTrackerScratch):
        raise ValueError("actual tracker local binding and40-byte seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (_LOOKUP, _INSERT, _LENGTH):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        arity = 2 if target == _LOOKUP else 3 if target == _INSERT else 0
        if len(args) != arity or data is not None:
            raise ValueError("malformed Combat tracker call")
        if target == _LENGTH:
            fail_replay_combat_tracker_length(context, calls=terminal)
            return None
        if target == _INSERT:
            return insert_replay_combat_tracker(context, *args, calls=bound)
        return lookup_replay_combat_tracker(
            context,
            *args,
            calls=bound,
            bind_local=bind_local,
            scratch=scratch,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
