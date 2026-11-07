"""Research-name conversion, lookup and assignment from six complete bodies.

Sources: player-derived-string-independent-source-v1 and the additional
localization originals it pins. Current storage and actual conversion/catalog/
string children are mandatory. Logical windows retain live pointer identity;
native stack/cookie, faults, exception unwind and concurrency are excluded.
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
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_EMPTY, _MANAGER = 0x143676DC8, 0x1442842E8
_ARITIES = {
    0x140803E30: 1,
    0x140803EA0: 1,
    0x140A15BF0: 2,
    0x140967520: -1,
    0x140963BE0: 0,
    0x140964A30: 2,
}


@dataclass(frozen=True, slots=True)
class ReplayPlayerResearchStringsScratch:
    """Explicit seeds: conversion16B, assignment16B and lookup8B.

    These independent invocation windows map the source's postRSP20 buffers
    and postRSP40 output home. Conversion bytes are not initialized by source.
    Assignment stores pointer before strlen and length after it. Lookup zeros
    its entire home. Each reached window stays live through its actual children.
    """

    conversion: bytes
    assignment: bytes
    lookup: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.conversion, 16),
                (self.assignment, 16),
                (self.lookup, 8),
            )
        ):
            raise ValueError("explicit sixteen/sixteen/eight-byte string seeds required")


@dataclass(frozen=True, slots=True)
class ReplayPlayerResearchStringsProfile:
    """Bound actual resolver entries per outer owned call, including reentry.

    Native numeric-ID fallback has no cycle guard. This supplied budget refuses
    before an unsupported next resolver entry, retaining earlier conversion,
    catalog and caller effects. It never turns a missing/cyclic lookup into text.
    """

    maximum_resolutions: int

    def __post_init__(self) -> None:
        if type(self.maximum_resolutions) is not int or self.maximum_resolutions < 0:
            raise ValueError("explicit nonnegative string-resolution budget required")


@dataclass(slots=True)
class _State:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    imports: ReplayTaskRebuildCalls
    bind_local: LocalBinding
    scratch: ReplayPlayerResearchStringsScratch
    remaining: int

    def call(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def identifier(self, value: int) -> int:
        value &= _U32
        if value == 0xFFFFFFFE:
            return _EMPTY
        with _local(memoryview(bytearray(self.scratch.conversion)), self.bind_local) as buffer:
            target = _read(self.context, 0x143199CA0, 8)
            _call(self.imports, target, (value, buffer, 16, 10))
            return self.call(0x140803EA0, buffer, result=True)

    def resolve(self, key: int) -> int:
        if not self.remaining:
            raise UnresolvedReplayTaskRebuild("research string resolution budget exhausted")
        self.remaining -= 1
        # The predicate ignores RCX, but the source caller retains its key there.
        if not self.call(0x140967520, key, result=True) & 0xFF:
            return _EMPTY
        manager = self.call(0x140963BE0, result=True)
        value = self.call(0x140964A30, manager, key, result=True)
        if value:
            return value
        manager = self.call(0x140963BE0, result=True)
        identifier = self.call(0x140964460, manager, key, result=True) & _U32
        if not identifier:
            return _EMPTY
        return self.call(0x140803E30, identifier, result=True)

    def lookup(self, manager: int, key: int) -> int:
        with _local(memoryview(bytearray(self.scratch.lookup)), self.bind_local) as output:
            _write(self.context, output, 8, 0)
            self.call(0x140964B80, manager, key, output)
            return _read(self.context, output, 8)

    def assign(self, address: int, source: int) -> int:
        previous = _read(self.context, address, 8)
        if previous:
            if _read(self.context, address + 16, 8):
                self.call(0x142D6C270, previous)
            _write(self.context, address, 8, 0x14428BB30)
            _write(self.context, address + 16, 8, 0)
            _write(self.context, address + 8, 8, 0)
        if not source or not _read(self.context, source, 1):
            return address
        with _local(memoryview(bytearray(self.scratch.assignment)), self.bind_local) as descriptor:
            _write(self.context, descriptor, 8, source)
            length = self.call(0x142D6E44D, source, result=True)
            _write(self.context, descriptor + 8, 8, length)
            length = self.call(0x140A13780, descriptor, result=True)
            if length:
                self.call(0x140A1A5E0, address, (length + 1) & _U64)
                destination = _read(self.context, address, 8)
                self.call(0x142D6E3B1, destination, source, length)
                destination = _read(self.context, address, 8)
                _write(self.context, destination + length, 1, 0)
                _write(self.context, address + 8, 8, length)
        return address


def bind_replay_player_research_strings(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: ReplayPlayerResearchStringsScratch,
    profile: ReplayPlayerResearchStringsProfile,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind six source entries, delegating every actual reached child.

    140967520 accepts zero arguments or the caller's incidental key annotation;
    its source consumes neither. Manager/global/data backing remains explicit.
    Full raw child results are masked only at source AL/EAX tests. Supplying
    these bodies establishes no current language catalog or full Player restore.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not callable(bind_local) or not isinstance(scratch, ReplayPlayerResearchStringsScratch):
        raise ValueError("actual local binding and explicit research-string seeds required")
    if not isinstance(profile, ReplayPlayerResearchStringsProfile):
        raise ValueError("explicit research-string resolution profile required")
    active: _State | None = None

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        nonlocal active
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        arity = _ARITIES[target]
        valid = len(args) in (0, 1) if arity == -1 else len(args) == arity
        if not valid or data is not None:
            raise ValueError("malformed research-string call")
        _validate(context, calls, *args)
        outer = active is None
        if outer:
            active = _State(
                context, calls, terminal, bind_local, scratch, profile.maximum_resolutions
            )
        state = active
        assert state is not None
        try:
            if target == 0x140803E30:
                return state.identifier(*args)
            if target == 0x140803EA0:
                return state.resolve(*args)
            if target == 0x140A15BF0:
                return state.assign(*args)
            if target == 0x140964A30:
                return state.lookup(*args)
            if target == 0x140963BE0:
                return _read(context, _MANAGER, 8)
            manager = _read(context, _MANAGER, 8)
            return int(manager != 0 and _read(context, manager + 0x239, 1) != 0)
        finally:
            if outer:
                active = None

    return ReplayTaskRebuildCalls(dispatch)
