"""Two original civilization registry insertions over explicit current backing.

No registry initialization, record construction or writer callback is supplied.
The name603B original is byte-identical to the existing real Combat tree body;
its complete source-equivalence binding is retained in this port's evidence.
Native physical frame/register/fault/EH/FLAGS and concurrent memory parity are
excluded. Reached engine atomic effects are mandatory, with no scalar fallback.
"""

from __future__ import annotations

from vantage.replay_combat_saved_tracker import insert_replay_combat_tracker
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _signed,
    _write,
)
from vantage.replay_unit_ai_base import _validate
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1


def insert_replay_civilization_numeric(
    context: ReplayTaskRebuildStorage,
    header: int,
    record: int,
    *,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    """Full634B140f6ae70. Consumed result is void; final LOCK INC is mandatory.

    Intrusive node=record+1b0, key=node-19c, DWORD color0, links8/10/parent18.
    Sentinel is held header+20; the fake top parent is header itself. Complete
    reached scalar backing, including the header/sentinel colors, is required.
    Wrapped DWORD subtraction is compared signed against one, even for duplicate
    or boundary keys. No duplicate replacement or comparison normalization occurs.
    """
    _validate(context, ReplayTaskRebuildCalls(None), header, record)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("explicit reached atomic bindings required")
    sentinel, node = (header + 0x20) & _U64, (record + 0x1B0) & _U64
    _write(context, node + 0x10, 8, sentinel)
    _write(context, node + 8, 8, sentinel)
    cursor = _read(context, header + 8, 8)
    if cursor != sentinel:
        held_key = _read(context, node - 0x19C, 4)
        while True:
            difference = (_read(context, cursor - 0x19C, 4) - held_key) & _U32
            parent = cursor
            offset = 0x10 if _signed(difference, 4) < 1 else 8
            cursor = _read(context, parent + offset, 8)
            if cursor == sentinel:
                break
        _write(context, node + 0x18, 8, parent)
        if parent != header:
            parent_key = _read(context, parent - 0x19C, 4)
            current_key = _read(context, node - 0x19C, 4)
            if _signed((parent_key - current_key) & _U32, 4) < 1:
                _write(context, parent + 0x10, 8, node)
            else:
                _write(context, parent + 8, 8, node)
        else:
            _write(context, parent + 8, 8, node)
    else:
        _write(context, node + 0x18, 8, header)
        _write(context, header + 8, 8, node)
    _write(context, node, 4, 1)
    cursor = node
    parent = _read(context, cursor + 0x18, 8)
    while _read(context, parent, 4) != 0:
        parent = _read(context, cursor + 0x18, 8)
        ancestor = _read(context, parent + 0x18, 8)
        other = _read(context, ancestor + 8, 8)
        if parent == other:
            other = _read(context, ancestor + 0x10, 8)
            if _read(context, other, 4) != 0:
                _write(context, parent, 4, 0)
                _write(context, other, 4, 0)
                parent = _read(context, cursor + 0x18, 8)
                upper = _read(context, parent + 0x18, 8)
                _write(context, upper, 4, 1)
                parent = _read(context, cursor + 0x18, 8)
                cursor = _read(context, parent + 0x18, 8)
            else:
                pivot = _read(context, parent + 0x10, 8)
                if cursor == pivot:
                    child = _read(context, pivot + 8, 8)
                    cursor = parent
                    _write(context, parent + 0x10, 8, child)
                    child = _read(context, pivot + 8, 8)
                    if child != sentinel:
                        _write(context, child + 0x18, 8, parent)
                    upper = _read(context, parent + 0x18, 8)
                    _write(context, pivot + 0x18, 8, upper)
                    upper = _read(context, parent + 0x18, 8)
                    if parent == _read(context, upper + 8, 8):
                        _write(context, upper + 8, 8, pivot)
                    else:
                        _write(context, upper + 0x10, 8, pivot)
                    _write(context, pivot + 8, 8, parent)
                    _write(context, parent + 0x18, 8, pivot)
                parent = _read(context, cursor + 0x18, 8)
                _write(context, parent, 4, 0)
                parent = _read(context, cursor + 0x18, 8)
                upper = _read(context, parent + 0x18, 8)
                _write(context, upper, 4, 1)
                parent = _read(context, cursor + 0x18, 8)
                upper = _read(context, parent + 0x18, 8)
                pivot = _read(context, upper + 8, 8)
                child = _read(context, pivot + 0x10, 8)
                _write(context, upper + 8, 8, child)
                child = _read(context, pivot + 0x10, 8)
                if child != sentinel:
                    _write(context, child + 0x18, 8, upper)
                above = _read(context, upper + 0x18, 8)
                _write(context, pivot + 0x18, 8, above)
                above = _read(context, upper + 0x18, 8)
                if upper == _read(context, above + 8, 8):
                    _write(context, above + 8, 8, pivot)
                    _write(context, pivot + 0x10, 8, upper)
                else:
                    _write(context, above + 0x10, 8, pivot)
                    _write(context, pivot + 0x10, 8, upper)
                _write(context, upper + 0x18, 8, pivot)
        elif _read(context, other, 4) != 0:
            _write(context, parent, 4, 0)
            _write(context, other, 4, 0)
            parent = _read(context, cursor + 0x18, 8)
            upper = _read(context, parent + 0x18, 8)
            _write(context, upper, 4, 1)
            parent = _read(context, cursor + 0x18, 8)
            cursor = _read(context, parent + 0x18, 8)
        else:
            pivot = _read(context, parent + 8, 8)
            if cursor == pivot:
                child = _read(context, pivot + 0x10, 8)
                cursor = parent
                _write(context, parent + 8, 8, child)
                child = _read(context, pivot + 0x10, 8)
                if child != sentinel:
                    _write(context, child + 0x18, 8, parent)
                upper = _read(context, parent + 0x18, 8)
                _write(context, pivot + 0x18, 8, upper)
                upper = _read(context, parent + 0x18, 8)
                if parent == _read(context, upper + 8, 8):
                    _write(context, upper + 8, 8, pivot)
                else:
                    _write(context, upper + 0x10, 8, pivot)
                _write(context, pivot + 0x10, 8, parent)
                _write(context, parent + 0x18, 8, pivot)
            parent = _read(context, cursor + 0x18, 8)
            _write(context, parent, 4, 0)
            parent = _read(context, cursor + 0x18, 8)
            upper = _read(context, parent + 0x18, 8)
            _write(context, upper, 4, 1)
            parent = _read(context, cursor + 0x18, 8)
            upper = _read(context, parent + 0x18, 8)
            pivot = _read(context, upper + 0x10, 8)
            child = _read(context, pivot + 8, 8)
            _write(context, upper + 0x10, 8, child)
            child = _read(context, pivot + 8, 8)
            if child != sentinel:
                _write(context, child + 0x18, 8, upper)
            above = _read(context, upper + 0x18, 8)
            _write(context, pivot + 0x18, 8, above)
            above = _read(context, upper + 0x18, 8)
            if upper == _read(context, above + 8, 8):
                _write(context, above + 8, 8, pivot)
            else:
                _write(context, above + 0x10, 8, pivot)
            _write(context, pivot + 8, 8, upper)
            _write(context, upper + 0x18, 8, pivot)
        parent = _read(context, cursor + 0x18, 8)
    root = _read(context, header + 8, 8)
    _write(context, root, 4, 0)
    _atomic(atomics, record + 8, 1)


def link_replay_civilization_name(
    context: ReplayTaskRebuildStorage,
    header: int,
    descriptor: int,
    node: int,
) -> int:
    """Full603B140f6b790 through the byte-identical real source body14114db00.

    No keys, strings or payloads are inspected. The descriptor parent/direction
    and current header/sentinel/node backing must actually exist. This is not
    an equivalent-name selection, registry setup or record constructor.
    """
    return insert_replay_combat_tracker(
        context, header, descriptor, node, calls=ReplayTaskRebuildCalls(None)
    )


def bind_replay_civilization_registry_insert(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
) -> ReplayTaskRebuildCalls:
    """Bind only634B numeric/603B name insertion; all other children delegate."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("explicit reached atomic bindings required")

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target == 0x140F6AE70:
            if len(args) != 2 or data is not None:
                raise ValueError("malformed civilization numeric insertion")
            insert_replay_civilization_numeric(context, *args, atomics=atomics)
            return None
        if target == 0x140F6B790:
            if len(args) != 3 or data is not None:
                raise ValueError("malformed civilization name insertion")
            return link_replay_civilization_name(context, *args)
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, args, data)

    return ReplayTaskRebuildCalls(call)
