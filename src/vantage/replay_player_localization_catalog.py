"""Complete catalog search bodies and four current-import CRT thunks.

Source: player-derived-string-independent-source-v1/catalog-source-first.json.
The three vector layers and final virtual chain use actual lock/lookup children.
No language, empty fallback catalog, mutex success or native identity is chosen.
Physical stack, native fault/unwind and concurrency behavior are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

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

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_FIND, _CATALOG = 0x14095F0B0, 0x140964B80
_LOCK, _UNLOCK, _THROW, _COMPARE = 0x142D6AA5B, 0x142D6AA61, 0x142D6AA67, 0x142D6E4B3
_IMPORTS = {
    _LOCK: (0x143199288, 1),
    _UNLOCK: (0x143199280, 1),
    _THROW: (0x143199278, 1),
    _COMPARE: (0x14319A300, 2),
}


@dataclass(frozen=True, slots=True)
class ReplayLocalizationCatalogProfile:
    """Explicit per-outer-call bounds for mutable scans and linked structures.

    Budgets refuse at the reached next iteration after prior effects; native
    code has no such cycle guard. Held cursors and current end/next/header reads
    remain source-shaped, with wrapped arithmetic and no invented alignment or
    range clamps. Native synchronization/provider internals are not supplied.
    """

    maximum_key_bytes: int
    maximum_nodes: int
    maximum_rows: int
    maximum_virtuals: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.maximum_key_bytes,
                self.maximum_nodes,
                self.maximum_rows,
                self.maximum_virtuals,
            )
        ):
            raise ValueError("explicit nonnegative catalog traversal budgets required")


@dataclass(slots=True)
class _State:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    profile: ReplayLocalizationCatalogProfile
    key_bytes: int = 0
    nodes: int = 0
    rows: int = 0
    virtuals: int = 0

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def call(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def visit(self, counter: str, maximum: int) -> None:
        value = getattr(self, counter)
        if value >= maximum:
            raise UnresolvedReplayTaskRebuild(f"localization {counter} budget exhausted")
        setattr(self, counter, value + 1)

    def find(self, table: int, key: int) -> int:
        cursor, hashed = key, 5381
        byte = self.read(cursor, 1) if key else 0
        while byte:
            self.visit("key_bytes", self.profile.maximum_key_bytes)
            hashed = (hashed * 33 ^ _signed(byte, 1)) & _U32
            cursor = (cursor + 1) & _U64
            byte = self.read(cursor, 1)
        bucket = self.read(table + 0x30) & hashed
        buckets = self.read(table + 0x18)
        sentinel = self.read(table + 8)
        node = self.read(buckets + 16 * bucket + 8)
        if node == sentinel:
            return 0
        node_key = self.read(node + 0x10)
        first = self.read(buckets + 16 * bucket)
        while True:
            self.visit("nodes", self.profile.maximum_nodes)
            equal = not self.call(_COMPARE, key, node_key, result=True) & _U32
            if equal:
                break
            if node == first:
                return 0
            node = self.read(node + 8)
            node_key = self.read(node + 0x10)
        # Native cmove also turns an otherwise matched null node into sentinel.
        return self.read(node + 0x18) if node and node != sentinel else 0

    def error(self, code: int) -> None:
        self.call(_THROW, code)
        trap = 0x140964D92 if code == 6 else 0x140964D9D
        raise UnresolvedReplayTaskRebuild(f"catalog error returned before INT3 {trap:x}")

    def lock(self, mutex: int) -> None:
        if self.call(_LOCK, mutex, result=True) & _U32:
            self.error(5)
        if self.read(mutex + 0x4C, 4) == 0x7FFFFFFF:
            _write(self.context, mutex + 0x4C, 4, 0x7FFFFFFE)
            self.error(6)

    def catalog(self, manager: int, key: int, output: int) -> int:
        for mutex_offset, begin_offset, end_offset in (
            (0xB8, 0x70, 0x78),
            (0x158, 0xA0, 0xA8),
            (0x108, 0x88, 0x90),
        ):
            mutex = (manager + mutex_offset) & _U64
            self.lock(mutex)
            row = self.read(manager + begin_offset)
            end = self.read(manager + end_offset)
            while row != end:
                self.visit("rows", self.profile.maximum_rows)
                table = self.read(row)
                found = self.call(_FIND, table, key, result=True)
                if found:
                    if output:
                        _write(self.context, output, 8, found)
                    self.call(_UNLOCK, mutex)
                    return 1  # Only AL is part of the source return contract.
                row = (row + 16) & _U64
                end = self.read(manager + end_offset)
            self.call(_UNLOCK, mutex)
        mutex = (manager + 0x1D0) & _U64
        self.lock(mutex)
        current = self.read(manager + 0x1C0)
        while current:
            self.visit("virtuals", self.profile.maximum_virtuals)
            vtable = self.read(current)
            target = self.read(vtable + 0x28)
            found = self.call(target, current, key, result=True)
            if found:
                # Unlike the three fixed-table hits, this path has no null guard.
                _write(self.context, output, 8, found)
                self.call(_UNLOCK, mutex)
                return 1
            current = self.read(current + 0x10)
        self.call(_UNLOCK, mutex)
        return 0


def bind_replay_player_localization_catalog(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    profile: ReplayLocalizationCatalogProfile,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind two searches and four actual six-byte import tail transfers.

    Actual lower routing must reenter these owned bodies for reached searches.
    All current IATs dispatch through imports without interpreting owned tokens.
    Native catalog's boolean result guarantees AL only; source callers must
    continue to use their actual low-register tests/current output reads.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(profile, ReplayLocalizationCatalogProfile):
        raise ValueError("explicit localization catalog profile required")
    active: _State | None = None

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        nonlocal active
        if target in _IMPORTS:
            slot, arity = _IMPORTS[target]
            if len(args) != arity or data is not None:
                raise ValueError("malformed localization import call")
            _validate(context, calls, *args)
            imported = _read(context, slot, 8)
            if terminal.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{imported:x} is unavailable")
            return terminal.call(imported, args, None)
        if target not in (_FIND, _CATALOG):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (2 if target == _FIND else 3) or data is not None:
            raise ValueError("malformed localization catalog call")
        _validate(context, calls, *args)
        outer = active is None
        if outer:
            active = _State(context, calls, profile)
        state = active
        assert state is not None
        try:
            return state.find(*args) if target == _FIND else state.catalog(*args)
        finally:
            if outer:
                active = None

    return ReplayTaskRebuildCalls(dispatch)
