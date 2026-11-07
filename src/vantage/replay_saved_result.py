"""Build54800 saved-reader Result vector destruction and shared finalization.

Complete159B1402bd7f0,5B1402bd890 and209B140900620, from the retained
tc-unit-ai-saved-result-{cleanup,finalize}-source-v1 packages. Element
destruction, current control virtuals, atomics and CRT effects are required.
This does not infer stream success or initialize Result status/processed bits.
Native fences, faults, stack/cookies, threading and C++ unwinding are excluded.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1


def _vector(
    context: ReplayTaskRebuildStorage,
    address: int,
    element: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
) -> None:
    begin = _read(context, address, 8)
    if not begin:
        return
    end = _read(context, address + 8, 8)
    while begin != end:
        _call(calls, element, (begin,))
        begin = begin + 32 & _U64
    # Element cleanup may replace the vector. Native code holds the iteration
    # end but reloads both allocation pointers only after destroying entries.
    begin = _read(context, address, 8)
    capacity = _read(context, address + 16, 8)
    size = (capacity - begin) & (_U64 - 31)
    pointer = begin
    if size >= 0x1000:
        pointer = _read(context, begin - 8, 8)
        size = size + 0x27 & _U64
        if (begin - pointer - 8) & _U64 > 31:
            _call(imports, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
            raise UnresolvedReplayTaskRebuild("nonreturning Result Watson returned before INT3")
    _call(calls, 0x142D6BAB4, (pointer, size))
    for offset in (0, 8, 16):
        _write(context, address + offset, 8, 0)


def clear_replay_saved_result_vector(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Full159B1402bd7f0 and genuine5B1402bd890 alias; vector fields only.

    A null begin skips end/capacity reads and all stores. Nonnull empty vectors
    are freed. The held iteration range uses mandatory32B element cleanup;
    later allocation-pointer reads and the three header resets follow source.
    """
    _validate(context, calls, address)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    _vector(context, address, 0x1402A88A0, calls=calls, imports=terminal)


def finalize_replay_saved_result(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Full209B140900620: held control release BEFORE current vector cleanup.

    The control token remains stored. Status+18 and processedBYTE+28 are not
    touched; callers own those effects. Destroy/dispose callbacks use current
    vtables of the held control, even if callbacks replace Result+20.
    """
    _validate(context, calls, address)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual saved Result shared-count bindings required")
    control = _read(context, address + 0x20, 8)
    if control:
        _release(context, control, calls, atomics)
    _vector(context, address, 0x1402A8920, calls=calls, imports=terminal)


def bind_replay_saved_result(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind complete cleanup callers and current sized-free import transfer."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual saved Result shared-count bindings required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x1402BD7F0: 1, 0x1402BD890: 1, 0x140900620: 1, 0x142D6BAB4: 2}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed saved Result cleanup call")
        _validate(context, calls, *args)
        if target in (0x1402BD7F0, 0x1402BD890):
            clear_replay_saved_result_vector(context, *args, calls=bound, imports=terminal)
        elif target == 0x140900620:
            finalize_replay_saved_result(
                context, *args, calls=bound, atomics=atomics, imports=terminal
            )
        else:
            imported = _read(context, 0x143199DD0, 8)
            if terminal.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{imported:x} is unavailable")
            return terminal.call(imported, args, None)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
