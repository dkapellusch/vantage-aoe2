"""Explicit owned capabilities for the localization body's imported services.

PE import identities are retained in player-localization-static-source-v1.
This engine profile supports signed32 decimal _itoa_s into sixteen-byte
buffers, normalized strcmp, registered single-thread mutex counts and engine
error termination. It does not emulate native CRT internals, invalid-parameter
handlers, debug fill, physical access/fault order, threads or DLL identity.
No native import/global value or successful unavailable service is inferred.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .replay_memory import ReplayMemory, ReplayMemoryRuntimeError
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    UnresolvedReplayTaskRebuild,
    _signed,
    _unsigned,
)

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MEMORY_TARGETS = frozenset(
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


@dataclass(frozen=True, slots=True)
class ReplayLocalizationTargets:
    """Five explicit, distinct owned service tokens; none has a default.

    The caller reserves these identities against additional delegate services.
    Body/thunk tokens may coincide in the separate terminal import namespace;
    native-source binders must still perform their current IAT tail transfer.
    """

    conversion: int
    comparison: int
    lock: int
    unlock: int
    error: int

    def __post_init__(self) -> None:
        values = (self.conversion, self.comparison, self.lock, self.unlock, self.error)
        for value in values:
            _unsigned(value, 8, "localization service token")
        if len(set(values)) != 5 or any(not v or v in _MEMORY_TARGETS for v in values):
            raise ValueError("five nonzero distinct reserved localization service tokens required")


@dataclass(slots=True)
class ReplayLocalizationRuntime:
    """Owned service state, separate from native source and its dispatch slots.

    Explicitly registered mutexes require a fresh defined zero DWORD at+4c.
    Locks/unlocks change that current count, including recursive ownership in
    this single-thread engine. Unknown mutexes, underflow and unsupported counts
    refuse rather than return successful lock results. Caller backing changes
    remain visible. Native owner/thread/protection fields are not synthesized.
    """

    memory: ReplayMemory
    targets: ReplayLocalizationTargets
    delegate: ReplayTaskRebuildCalls | None = None
    _mutexes: set[int] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.memory, ReplayMemory) or not isinstance(
            self.targets, ReplayLocalizationTargets
        ):
            raise ValueError("explicit owned memory and localization service targets required")
        if self.delegate is not None and not isinstance(self.delegate, ReplayTaskRebuildCalls):
            raise ValueError("explicit localization service delegate required")

    def register_mutex(self, mutex: int) -> None:
        _unsigned(mutex, 8, "owned localization mutex")
        if mutex in self._mutexes:
            raise ValueError("owned localization mutex is already registered")
        if self.memory.read((mutex + 0x4C) & _U64, 4) != 0:
            raise ValueError("fresh defined zero mutex count required")
        self._mutexes.add(mutex)

    def calls(self) -> ReplayTaskRebuildCalls:
        """Return a terminal service dispatcher; no IAT/global mappings occur."""
        return ReplayTaskRebuildCalls(self._dispatch)

    def _dispatch(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        service = {
            self.targets.conversion: ("conversion", 4),
            self.targets.comparison: ("comparison", 2),
            self.targets.lock: ("lock", 1),
            self.targets.unlock: ("unlock", 1),
            self.targets.error: ("error", 1),
        }.get(target)
        if service is None:
            if self.delegate is None or self.delegate.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return self.delegate.call(target, args, data)
        kind, arity = service
        if len(args) != arity or data is not None:
            raise ValueError("malformed owned localization service call")
        for value in args:
            _unsigned(value, 8, "owned localization service argument")
        if kind == "conversion":
            value, destination, size, radix = args
            if size != 16 or radix != 10:
                raise UnresolvedReplayTaskRebuild(
                    "only explicit sixteen-byte decimal conversion admitted"
                )
            encoded = str(_signed(value & _U32, 4)).encode("ascii") + b"\0"
            self.memory.write_bytes(destination, encoded)
            return 0
        if kind == "comparison":
            left, right = args
            lhs = self.memory.read_bytes(left, self.memory.c_string_length(left))
            rhs = self.memory.read_bytes(right, self.memory.c_string_length(right))
            return ((lhs > rhs) - (lhs < rhs)) & _U32
        if kind == "error":
            raise ReplayMemoryRuntimeError(target, args)
        mutex = args[0]
        if mutex not in self._mutexes:
            raise UnresolvedReplayTaskRebuild("reached unregistered owned localization mutex")
        field_address = (mutex + 0x4C) & _U64
        count = self.memory.read(field_address, 4)
        if kind == "lock":
            if count >= 0x7FFFFFFF:
                raise UnresolvedReplayTaskRebuild("owned localization mutex count exceeds profile")
            self.memory.write(field_address, 4, count + 1)
        else:
            if not 0 < count <= 0x7FFFFFFF:
                raise UnresolvedReplayTaskRebuild("owned localization mutex unlock exceeds profile")
            self.memory.write(field_address, 4, count - 1)
        return 0
