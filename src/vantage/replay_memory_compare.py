"""Explicit owned byte comparison and build54800's current-import memcmp thunk.

The six-byte thunk is original source behavior. The comparison provider is an
owned-engine capability: both complete spans must have defined nonwrapping
backing. It returns raw EAX with normalized signed32 -1/0/+1 semantics, not an
exact native nonzero magnitude or optimized CRT access/fault/EH/concurrency or
DLL identity claim. No capability or IAT value is chosen by default.
"""

from __future__ import annotations

from vantage.replay_memory import ReplayMemory
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
)
from vantage.replay_unit_ai_base import _validate

_THUNK = 0x142D6E3BD
_IAT = 0x143199940
_OWNED_TARGETS = frozenset(
    (
        0x142D6BA78,
        0x1402A94D0,
        0x142D6BAB4,
        0x142D6E3DB,
        0x142D6E3B7,
        0x142D6E453,
        0x1402A9460,
        0x14113A7A0,
        0x14114DD60,
        0x142D66698,
    )
)


def compare_replay_memory_bytes(
    memory: ReplayMemory,
    left: int,
    right: int,
    count: int,
) -> int:
    """Compare unsigned bytes; raw EAX is FFFFFFFF, zero or one.

    Scalar validation precedes backing reads. Zero count has no backing access.
    Otherwise the entire left span is read before the entire right span. Both
    must be fully defined, including bytes after the first unequal byte. This
    explicit engine admission does not emulate native vector/fault read order.
    No memory writes or delegate fallback occur on a backing error.
    """
    if not isinstance(memory, ReplayMemory):
        raise ValueError("explicit owned replay memory required")
    for value in (left, right, count):
        _unsigned(value, 8, "comparison argument")
    if not count:
        return 0
    lhs = memory.read_bytes(left, count)
    rhs = memory.read_bytes(right, count)
    return ((lhs > rhs) - (lhs < rhs)) & 0xFFFFFFFF


def replay_memory_comparison_calls(
    memory: ReplayMemory,
    delegate: ReplayTaskRebuildCalls | None = None,
    *,
    comparison_target: int,
    calloc_target: int | None = None,
    strlen_target: int | None = None,
) -> ReplayTaskRebuildCalls:
    """Compose a fresh explicit comparison capability under real runtime calls.

    This factory owns the complete calloc/strlen/runtime configuration, so its
    comparison identity cannot be shadowed by those selected operations. The
    caller reserves the fresh token against any additional delegate identities;
    unknown delegate namespaces cannot be inferred from a callable. The native
    thunk token is reserved separately. No source global/current IAT is written.
    """
    if not isinstance(memory, ReplayMemory):
        raise ValueError("explicit owned replay memory required")
    if delegate is not None and not isinstance(delegate, ReplayTaskRebuildCalls):
        raise ValueError("explicit helper delegate required")
    _unsigned(comparison_target, 8, "comparison target")
    for optional, label in ((calloc_target, "calloc target"), (strlen_target, "strlen target")):
        if optional is not None:
            _unsigned(optional, 8, label)
    if (
        not comparison_target
        or comparison_target in _OWNED_TARGETS
        or comparison_target in (_THUNK, calloc_target, strlen_target)
    ):
        raise ValueError("nonnull distinct engine comparison target required")

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target == comparison_target:
            if len(args) != 3 or data is not None:
                raise ValueError("malformed owned memory comparison call")
            return compare_replay_memory_bytes(memory, *args)
        if delegate is None or delegate.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return delegate.call(target, args, data)

    return memory.runtime_calls(
        ReplayTaskRebuildCalls(call), calloc_target=calloc_target, strlen_target=strlen_target
    )


def call_replay_memcmp_thunk(
    context: ReplayTaskRebuildStorage,
    left: int,
    right: int,
    count: int,
    *,
    imports: ReplayTaskRebuildCalls,
) -> int:
    """Full6B142d6e3bd: read current143199940, tail-dispatch unchanged three args.

    The logical result is consumed raw EAX only. imports is the actual terminal
    dispatcher, so a selected token equal to a body/thunk address is dispatched
    once rather than recursively reinterpreted by this binder. Missing imports
    still refuse after the reached current slot read. No native RAX is implied.
    """
    _validate(context, imports, left, right, count)
    target = _read(context, _IAT, 8)
    return _call(imports, target, (left, right, count), width=4)


def bind_replay_memcmp_thunk(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind only the actual thunk; unknown bodies retain the supplied delegate.

    By default the pre-binding lower calls dispatcher is terminal for imported
    targets. A separately supplied imports dispatcher must satisfy that same
    contract. This function supplies no comparison provider or default identity.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target == _THUNK:
            if len(args) != 3 or data is not None:
                raise ValueError("malformed replay memcmp thunk call")
            return call_replay_memcmp_thunk(context, *args, imports=terminal)
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, args, data)

    return ReplayTaskRebuildCalls(call)
