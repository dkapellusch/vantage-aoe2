"""Build54800's complete numeric alias lookup, map find and insertion bodies.

Source: player-localization-static-source-v1/140964460,140961de0,
player-localization-alias-descendants-static-v1/140961d10 and
player-localization-startup-static-v1/140962270. Actual descendants,
current storage and coherent explicit locals remain required. Owned limits
exclude physical stack/EH/fault/concurrency and private native CRT behavior.
Scalar binary32 uses masked nearest-even arithmetic with DAZ/FTZ off; native
FP status, traps and other MXCSR profiles are outside this engine profile.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import compare_binary32, divide_binary32, unsigned64_binary32
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
_LOOKUP, _FIND, _INSERT, _INSERT_VALUE = 0x140964460, 0x140961D10, 0x140961DE0, 0x140962270
_COMPARE = 0x142D6E3BD
_STRLEN, _COPY = 0x142D6E44D, 0x142D6E3B1
_LOCK, _UNLOCK, _THROW = 0x142D6AA5B, 0x142D6AA61, 0x142D6AA67


@dataclass(frozen=True, slots=True)
class ReplayLocalizationAliasScratch:
    """Explicit A0 lookup and40 insertion logical frame seeds."""

    lookup: bytes
    insertion: bytes

    def __post_init__(self) -> None:
        if type(self.lookup) is not bytes or len(self.lookup) != 0xA0:
            raise ValueError("explicit A0-byte alias lookup frame required")
        if type(self.insertion) is not bytes or len(self.insertion) != 0x40:
            raise ValueError("explicit40-byte alias insertion frame required")


@dataclass(frozen=True, slots=True)
class ReplayLocalizationAliasProfile:
    """Shared per-outer-call limits, refusing after earlier source effects."""

    maximum_key_bytes: int
    maximum_nodes: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.maximum_key_bytes,
                self.maximum_nodes,
            )
        ):
            raise ValueError("explicit nonnegative alias traversal budgets required")


@dataclass(slots=True)
class _State:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    imports: ReplayTaskRebuildCalls
    bind_local: LocalBinding
    scratch: ReplayLocalizationAliasScratch
    profile: ReplayLocalizationAliasProfile
    key_bytes: int = 0
    nodes: int = 0

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, value: int, width: int = 8) -> None:
        _write(self.context, address, width, value)

    def call(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def visit(self, counter: str, limit: int) -> None:
        value = getattr(self, counter)
        if value >= limit:
            raise UnresolvedReplayTaskRebuild(f"localization alias {counter} budget exhausted")
        setattr(self, counter, value + 1)

    def hash(self, pointer: int, length: int) -> int:
        value = 0xCBF29CE484222325
        for offset in range(length):
            self.visit("key_bytes", self.profile.maximum_key_bytes)
            value = ((value ^ self.read(pointer + offset, 1)) * 0x100000001B3) & _U64
        return value

    def node_key(self, node: int) -> int:
        heap = self.read(node + 0x28) > 15
        return self.read(node + 0x10) if heap else (node + 0x10) & _U64

    def same(self, left: int, right: int, length: int) -> bool:
        return not self.call(_COMPARE, left, right, length, result=True) & _U32

    def find(self, table: int, output: int, source: int, hashed: int) -> int:
        mask = self.read(table + 0x30)
        sentinel = self.read(table + 8)
        bucket = (self.read(table + 0x18) + ((mask & hashed) << 4)) & _U64
        node = self.read(bucket + 8)
        if node == sentinel:
            self.write(output, sentinel)
            self.write(output + 8, 0)
            return output
        first = self.read(bucket)
        length = self.read(source + 0x10)
        capacity = self.read(source + 0x18)
        while True:
            self.visit("nodes", self.profile.maximum_nodes)
            right = self.node_key(node)
            left = self.read(source) if capacity > 15 else source
            if length == self.read(node + 0x20) and (not length or self.same(left, right, length)):
                self.write(output, self.read(node))
                self.write(output + 8, node)
                return output
            if node == first:
                self.write(output, node)
                self.write(output + 8, 0)
                return output
            node = self.read(node + 8)

    def insertion(self, table: int, output: int, source: int, *, with_value: bool = False) -> int:
        with _local(memoryview(bytearray(self.scratch.insertion)), self.bind_local) as frame:
            length = self.read(source + 0x10)
            pointer = self.read(source) if self.read(source + 0x18) > 15 else source
            hashed = self.hash(pointer, length)
            self.call(_FIND, table, frame + 0x30, source, hashed)
            node = self.read(frame + 0x38)
            if node:
                self.write(output, node)
                self.write(output + 8, 0, 1)
                return output
            sentinel_address = (table + 8) & _U64
            if self.read(table + 0x10) == 0x0492492492492492:
                self.call(0x142D66698, 0x143682918)
                trap = "1409624d1" if with_value else "140962041"
                raise UnresolvedReplayTaskRebuild(f"length error returned before INT3 {trap}")
            self.write(frame + 0x20, sentinel_address)
            self.write(frame + 0x28, 0)
            allocated = self.call(0x142D6BA78, 0x38, result=True)
            self.write(frame + 0x28, allocated)
            self.write(allocated + 0x10, 0, 16)
            self.write(allocated + 0x20, 0)
            self.write(allocated + 0x28, 0)
            self.write(allocated + 0x10, self.read(source, 16), 16)
            self.write(allocated + 0x20, self.read(source + 0x10, 16), 16)
            self.write(source + 0x10, 0)
            self.write(source + 0x18, 15)
            self.write(source, 0, 1)
            self.write(allocated + 0x30, self.read(source + 0x20, 4) if with_value else 0, 4)
            count = (self.read(table + 0x10) + 1) & _U64
            numerator = unsigned64_binary32(count)
            denominator = unsigned64_binary32(self.read(table + 0x38))
            factor = divide_binary32(numerator, denominator)
            if compare_binary32(factor, self.read(table, 4)) == 1:
                requested = self.call(0x140969420, table, count, result=True)
                self.call(0x140969930, table, requested)
                mask = self.read(table + 0x30)
                buckets = self.read(table + 0x18)
                bucket = (buckets + ((mask & hashed) << 4)) & _U64
                node = self.read(bucket + 8)
                before = self.read(sentinel_address)
                if node != before:
                    first = self.read(bucket)
                    length = self.read(allocated + 0x20)
                    while True:
                        self.visit("nodes", self.profile.maximum_nodes)
                        right = self.node_key(node)
                        left = (
                            self.read(allocated + 0x10)
                            if self.read(allocated + 0x28) > 15
                            else (allocated + 0x10) & _U64
                        )
                        if length == self.read(node + 0x20) and (
                            not length or self.same(left, right, length)
                        ):
                            before = self.read(node)
                            break
                        if node == first:
                            before = node
                            break
                        node = self.read(node + 8)
            else:
                before = self.read(frame + 0x30)
            previous = self.read(before + 8)
            self.write(table + 0x10, self.read(table + 0x10) + 1)
            self.write(allocated, before)
            self.write(allocated + 8, previous)
            self.write(previous, allocated)
            self.write(before + 8, allocated)
            mask = self.read(table + 0x30)
            bucket = (self.read(table + 0x18) + ((mask & hashed) << 4)) & _U64
            first = self.read(bucket)
            if first == self.read(sentinel_address):
                self.write(bucket, allocated)
                self.write(bucket + 8, allocated)
            elif first == before:
                self.write(bucket, allocated)
            elif self.read(bucket + 8) == previous:
                self.write(bucket + 8, allocated)
            self.write(output, allocated)
            self.write(output + 8, 1, 1)
            return output

    def lock(self, mutex: int) -> None:
        if self.call(_LOCK, mutex, result=True) & _U32:
            self.call(_THROW, 5)
            raise UnresolvedReplayTaskRebuild("alias lock error returned before INT3 1409647a4")
        if self.read(mutex + 0x4C, 4) == 0x7FFFFFFF:
            self.write(mutex + 0x4C, 0x7FFFFFFE, 4)
            self.call(_THROW, 6)
            raise UnresolvedReplayTaskRebuild("alias count error returned before INT3 1409647b8")

    def make_string(
        self, frame: int, temporary: int, source: int, *, first: bool
    ) -> tuple[
        int,
        int,
        int,
    ]:
        self.write(temporary, 0, 16)
        if not first:
            self.write(temporary + 0x10, 0, 16)
        length = self.call(_STRLEN, source, result=True)
        if length > 0x7FFFFFFFFFFFFFFF:
            self.call(0x1402A91E0)
            trap = "1409647be" if first else "140964799"
            raise UnresolvedReplayTaskRebuild(
                f"alias string length error returned before INT3 {trap}"
            )
        if length <= 15:
            self.write(temporary + 0x10, length)
            self.write(temporary + 0x18, 15)
            self.call(_COPY, temporary, source, length)
            self.write(temporary + length, 0, 1)
            if first:
                capacity = self.read(temporary + 0x18)
                length = self.read(temporary + 0x10)
                pointer = self.read(temporary)
                return length, capacity, pointer
            return length, 15, temporary
        capacity = min(max(length | 15, 22), 0x7FFFFFFFFFFFFFFF)
        pointer = self.call(0x1402A94D0, capacity + 1, result=True)
        self.write(temporary, pointer)
        self.write(temporary + 0x10, length)
        self.write(temporary + 0x18, capacity)
        self.call(_COPY, pointer, source, length)
        self.write(pointer + length, 0, 1)
        return length, capacity, pointer

    def free_string(self, frame: int, pointer: int, capacity: int, trap: str) -> None:
        if capacity <= 15:
            return
        size = (capacity + 1) & _U64
        if size >= 0x1000:
            base = self.read(pointer - 8)
            size = (size + 0x27) & _U64
            if (pointer - base - 8) & _U64 > 0x1F:
                self.write(frame + 0x20, 0)
                target = self.read(0x14319A060)
                _call(self.imports, target, (0, 0, 0, 0, self.read(frame + 0x20)))
                raise UnresolvedReplayTaskRebuild(
                    f"alias invalid parameter returned before INT3 {trap}"
                )
            pointer = base
        self.call(0x142D6BAB4, pointer, size)

    def lookup(self, manager: int, key: int) -> int:
        with _local(memoryview(bytearray(self.scratch.lookup)), self.bind_local) as frame:
            self.write(frame + 0x60, manager)
            self.write(frame + 0x30, 0, 4)
            mutex = (manager + 0x280) & _U64
            self.write(frame + 0x58, mutex)
            self.lock(mutex)
            temporary = (frame + 0x38) & _U64
            length, capacity, pointer = self.make_string(frame, temporary, key, first=True)
            left = pointer if capacity > 15 else temporary
            hashed = self.hash(left, length)
            mask = self.read(manager + 0x270)
            buckets = self.read(manager + 0x258)
            bucket = (buckets + ((mask & hashed) << 4)) & _U64
            node = self.read(bucket + 8)
            sentinel = self.read(self.read(frame + 0x60) + 0x248)
            self.write(frame + 0x88, sentinel)
            if node != sentinel:
                first = self.read(bucket)
                while True:
                    self.visit("nodes", self.profile.maximum_nodes)
                    right = self.node_key(node)
                    if length == self.read(node + 0x20) and (
                        not length or self.same(left, right, length)
                    ):
                        break
                    if node == first:
                        node = 0
                        break
                    node = self.read(node + 8)
                mutex = self.read(frame + 0x58)
            else:
                node = 0  # Native60b XOR EBX before reloading the current sentinel home.
            sentinel = self.read(frame + 0x88)
            if not node:
                node = sentinel
            self.free_string(frame, pointer, capacity, "14096465c")
            if node != sentinel:
                current_manager = self.read(frame + 0x60)
                temporary = (frame + 0x68) & _U64
                self.make_string(frame, temporary, key, first=False)
                returned = self.call(
                    _INSERT, current_manager + 0x240, frame + 0x88, temporary, result=True
                )
                self.write(frame + 0x30, self.read(self.read(returned) + 0x30, 4), 4)
                capacity = self.read(temporary + 0x18)
                # Native reads a heap pointer only on the non-SSO cleanup path.
                if capacity > 15:
                    self.free_string(frame, self.read(temporary), capacity, "140964768")
            self.call(_UNLOCK, mutex)
            return self.read(frame + 0x30, 4)


def bind_replay_localization_alias(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: ReplayLocalizationAliasScratch,
    profile: ReplayLocalizationAliasProfile,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind complete140964460/140961d10/140961de0/140962270 with shared scan admission.

    Real lower dispatch must reenter owned descendants; imported services use
    the separate terminal namespace. No map, mutex, locale, aliases or child
    success is supplied here. Missing children retain preceding writes/locks.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if (
        not callable(bind_local)
        or not isinstance(scratch, ReplayLocalizationAliasScratch)
        or not isinstance(profile, ReplayLocalizationAliasProfile)
    ):
        raise ValueError("explicit alias locals, scratch and profile required")
    active: _State | None = None
    arities = {_LOOKUP: 2, _FIND: 4, _INSERT: 3, _INSERT_VALUE: 3}

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        nonlocal active
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed localization alias call")
        _validate(context, calls, *args)
        outer = active is None
        if outer:
            active = _State(context, calls, terminal, bind_local, scratch, profile)
        assert active is not None
        try:
            if target == _LOOKUP:
                return active.lookup(*args)
            if target == _FIND:
                return active.find(*args)
            return active.insertion(*args, with_value=target == _INSERT_VALUE)
        finally:
            if outer:
                active = None

    return ReplayTaskRebuildCalls(dispatch)
