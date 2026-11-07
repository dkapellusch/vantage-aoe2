"""Six source bodies for localization alias bucket growth and rehash.

Originals: player-localization-alias-descendants-static-v1; source-first.json
in this stage pins all1268 bytes. Scalar FP uses masked nearest-even, DAZ/FTZ
off; ceil is an actual current-import raw-word call. Physical stack/registers,
FPstatus, fault/EH and threads are excluded. No native catalog is initialized.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary32 import divide_binary32, unsigned64_binary32
from vantage.replay_task_containers import _growth
from vantage.replay_task_group_storage import LocalBinding
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _unsigned,
    _write,
)
from vantage.replay_unit_ai_base import _validate
from vantage.replay_unit_ai_construction import _local

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_COUNT, _REHASH, _VECTOR = 0x140969420, 0x140969930, 0x1409691F0
_FILL, _RELEASE, _CEIL = 0x1409624E0, 0x140969EE0, 0x142D6E453
_ARITIES = {_COUNT: 2, _REHASH: 2, _VECTOR: 3, _FILL: 3, _RELEASE: 3, _CEIL: 1}


@dataclass(frozen=True, slots=True)
class ReplayLocalizationAliasGrowthScratch:
    """Seeds for vector post50, rehash post20..3f, and Watson post20.

    Each invocation maps fresh mutable backing. Rehash cap20/bucket28/map30/
    vector38 remain coherent through actual children and branch-specific reads.
    Vector fill-value home remains live throughout allocation/reuse children.
    """

    vector: bytes
    rehash: bytes
    release: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.vector, 8),
                (self.rehash, 32),
                (self.release, 8),
            )
        ):
            raise ValueError("explicit eight/thirty-two/eight-byte growth seeds required")


@dataclass(frozen=True, slots=True)
class ReplayLocalizationAliasGrowthProfile:
    """Shared reached-work limits and the explicit scalar SSE profile.

    Counters cover bucket fill stores, traversed list nodes, hashed bytes and
    compared candidates across synchronous owned reentry. A refused next store
    retains its preceding source read. Reversed or unreachable scalar fill
    ranges are bounded prefixes, never clamped to successful zero stores.
    Every actual backing access still requires its admitted nonwrapping span.
    """

    maximum_fill_stores: int
    maximum_nodes: int
    maximum_key_bytes: int
    maximum_candidates: int
    mxcsr: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.maximum_fill_stores,
                self.maximum_nodes,
                self.maximum_key_bytes,
                self.maximum_candidates,
            )
        ):
            raise ValueError("explicit nonnegative alias-growth work bounds required")
        _unsigned(self.mxcsr, 4, "alias-growth MXCSR")
        if self.mxcsr & ~0x3F != 0x1F80:
            raise ValueError("masked nearest-even MXCSR with DAZ/FTZ off required")


@dataclass(slots=True)
class _State:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    imports: ReplayTaskRebuildCalls
    bind_local: LocalBinding
    scratch: ReplayLocalizationAliasGrowthScratch
    profile: ReplayLocalizationAliasGrowthProfile
    stores: int = 0
    nodes: int = 0
    key_bytes: int = 0
    candidates: int = 0

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, value: int) -> None:
        _write(self.context, address, 8, value)

    def call(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def visit(self, counter: str, maximum: int) -> None:
        current = getattr(self, counter)
        if current >= maximum:
            raise UnresolvedReplayTaskRebuild(f"alias growth {counter} budget exhausted")
        setattr(self, counter, current + 1)

    def store(self, address: int, value: int) -> None:
        self.visit("stores", self.profile.maximum_fill_stores)
        self.write(address, value)

    def count(self, table: int, requested: int) -> int:
        previous = self.read(table + 0x38)
        ratio = divide_binary32(unsigned64_binary32(requested), self.read(table, 4))
        rounded = _call(self.calls, _CEIL, (ratio,), width=4)
        calculated = _growth(rounded, self.read(0x1436A0308, 4))
        if previous >= calculated:
            return previous
        return max((previous * 8) & _U64, calculated) if previous < 512 else calculated

    def fill(self, begin: int, end: int, source: int) -> None:
        count = (((end - begin + 7) & _U64) >> 3) if begin <= end else 0
        current = begin
        if count >= 2:
            value = self.read(source)  # Mandatory BEFORE the overlap decision.
            last = (begin - 8 + count * 8) & _U64
            if begin > source or last < source:
                for _ in range(count & ~1):
                    self.store(current, value)
                    current = (current + 8) & _U64
        while current != end:
            value = self.read(source)
            self.store(current, value)
            current = (current + 8) & _U64

    def vector(self, header: int, requested: int, value: int) -> None:
        with _local(memoryview(bytearray(self.scratch.vector)), self.bind_local) as home:
            self.write(home, value)
            begin = self.read(header)
            end = self.read(header + 8)
            size = (_signed((end - begin) & _U64, 8) >> 3) & _U64
            if size >= requested:
                self.call(_FILL, begin, end, home)
                return
            if requested > 0x1FFFFFFFFFFFFFFF:
                self.call(0x1402A9460)
                raise UnresolvedReplayTaskRebuild("vector error returned before INT3 1409692b1")
            byte_count = (requested * 8) & _U64
            allocated = self.call(0x1402A94D0, byte_count, result=True)
            previous = self.read(header)
            capacity = self.read(header + 0x10)
            count = (_signed((capacity - previous) & _U64, 8) >> 3) & _U64
            if count:
                self.call(_RELEASE, header, previous, count)
            end = (allocated + byte_count) & _U64
            self.write(header, allocated)
            self.write(header + 8, end)
            self.write(header + 0x10, end)
            while allocated != end:
                self.store(allocated, value)  # Held R8/RBX, not current home.
                allocated = (allocated + 8) & _U64

    def release(self, ignored: int, begin: int, capacity: int) -> int | None:
        size = (capacity * 8) & _U64
        pointer = begin
        if size >= 0x1000:
            base = self.read(begin - 8)
            size = (size + 0x27) & _U64
            if (begin - base - 8) & _U64 > 0x1F:
                with _local(memoryview(bytearray(self.scratch.release)), self.bind_local) as fifth:
                    self.write(fifth, 0)
                    target = self.read(0x14319A060)
                    _call(self.imports, target, (0, 0, 0, 0, self.read(fifth)))
                    raise UnresolvedReplayTaskRebuild("Watson returned before INT3 140969f35")
            pointer = base
        if self.calls.call is None:
            raise UnresolvedReplayTaskRebuild("reached142d6bab4 is unavailable")
        return self.calls.call(0x142D6BAB4, (pointer, size), None)

    def rehash(self, table: int, requested: int) -> None:
        with _local(memoryview(bytearray(self.scratch.rehash)), self.bind_local) as home:
            self.write(home + 16, table)
            if requested > 1 << 59:
                self.call(0x142D66698, 0x143682938)
                raise UnresolvedReplayTaskRebuild("rehash error returned before INT3 140969be5")
            sentinel = self.read(table + 8)
            bucket_count = 1 << (((((requested - 1) & _U64) | 1).bit_length()) & 63)
            vector = (table + 0x18) & _U64
            self.write(home + 24, vector)
            self.call(_VECTOR, vector, (2 * bucket_count) & _U64, sentinel)
            self.write(table + 0x38, bucket_count)
            self.write(table + 0x30, bucket_count - 1)
            current = self.read(self.read(table + 8))
            owner = table
            while current != sentinel:
                self.visit("nodes", self.profile.maximum_nodes)
                capacity = self.read(current + 0x28)
                following = self.read(current)  # Held before all hash/compare effects.
                length = self.read(current + 0x20)
                self.write(home, capacity)
                key = self.read(current + 0x10) if capacity > 15 else (current + 0x10) & _U64
                hashed = 0xCBF29CE484222325
                for offset in range(length):
                    self.visit("key_bytes", self.profile.maximum_key_bytes)
                    hashed = ((hashed ^ self.read(key + offset, 1)) * 0x100000001B3) & _U64
                if length:
                    self.write(home, capacity)
                mask = self.read(owner + 0x30)
                bucket = ((hashed & mask) * 16 + self.read(vector)) & _U64
                self.write(home + 8, bucket)
                if self.read(bucket) == sentinel:
                    self.write(bucket, current)
                    self.write(bucket + 8, current)
                else:
                    candidate = self.read(bucket + 8)
                    self.visit("candidates", self.profile.maximum_candidates)
                    candidate_capacity = self.read(candidate + 0x28)
                    candidate_length = self.read(candidate + 0x20)
                    other = (
                        self.read(candidate + 0x10)
                        if candidate_capacity > 15
                        else (candidate + 0x10) & _U64
                    )
                    query = self.read(current + 0x10) if capacity > 15 else (current + 0x10) & _U64
                    equal = length == candidate_length
                    if equal and length:
                        equal = not self.call(0x142D6E3BD, query, other, length, result=True) & _U32
                        bucket = self.read(home + 8)
                        self.write(home, capacity)
                    if equal:
                        next_match = self.read(candidate)
                        if next_match != current:
                            self.splice(current, following, next_match)
                        owner = self.read(home + 16)
                        vector = self.read(home + 24)
                        self.write(bucket + 8, current)
                    else:
                        boundary = self.read(bucket)
                        matched = False
                        later = False
                        while candidate != boundary:
                            later = True
                            candidate = self.read(candidate + 8)
                            self.visit("candidates", self.profile.maximum_candidates)
                            candidate_capacity = self.read(candidate + 0x28)
                            other = (
                                self.read(candidate + 0x10)
                                if candidate_capacity > 15
                                else (candidate + 0x10) & _U64
                            )
                            query = (
                                self.read(current + 0x10)
                                if capacity > 15
                                else (current + 0x10) & _U64
                            )
                            candidate_length = self.read(candidate + 0x20)
                            if length == candidate_length:
                                if (
                                    not length
                                    or not self.call(
                                        0x142D6E3BD,
                                        query,
                                        other,
                                        length,
                                        result=True,
                                    )
                                    & _U32
                                ):
                                    matched = True
                                    break
                                capacity = self.read(home)
                        if matched:
                            next_match = self.read(candidate)
                            previous = self.read(current + 8)
                            owner = self.read(home + 16)
                            vector = self.read(home + 24)
                            self.splice(current, following, next_match, previous=previous)
                        else:
                            # Only exhaustion of a nonempty later-candidate loop reloads28.
                            if later:
                                bucket = self.read(home + 8)
                            previous = self.read(current + 8)
                            owner = self.read(home + 16)
                            vector = self.read(home + 24)
                            self.splice(current, following, candidate, previous=previous)
                            self.write(bucket, current)
                current = following

    def splice(
        self,
        node: int,
        following: int,
        target: int,
        *,
        previous: int | None = None,
    ) -> None:
        if previous is None:
            previous = self.read(node + 8)
        self.write(previous, following)
        before_following = self.read(following + 8)
        self.write(before_following, target)
        before_target = self.read(target + 8)
        self.write(before_target, node)
        self.write(target + 8, before_following)
        self.write(following + 8, previous)
        self.write(node + 8, before_target)


def bind_replay_localization_alias_growth(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: ReplayLocalizationAliasGrowthScratch,
    profile: ReplayLocalizationAliasGrowthProfile,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind only six bodies; actual lower routing must reenter owned children.

    Ceil receives/returns its raw XMM0 DWORD, unlike integer raw RAX children.
    Its current143199ef0 target goes directly to terminal imports. Memcmp is
    deliberately not owned here. Cleanup's normal tail-free retains raw return.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if (
        not callable(bind_local)
        or not isinstance(scratch, ReplayLocalizationAliasGrowthScratch)
        or not isinstance(profile, ReplayLocalizationAliasGrowthProfile)
    ):
        raise ValueError("actual local binding, explicit alias-growth seeds/profile required")
    active: _State | None = None

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        nonlocal active
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed localization alias-growth call")
        _validate(context, calls, *args)
        if target == _CEIL:
            _unsigned(args[0], 4, "ceil low XMM0 word")
            return _call(terminal, _read(context, 0x143199EF0, 8), args, width=4)
        outer = active is None
        if outer:
            active = _State(context, calls, terminal, bind_local, scratch, profile)
        state = active
        assert state is not None
        try:
            if target == _COUNT:
                return state.count(*args)
            if target == _REHASH:
                state.rehash(*args)
            elif target == _VECTOR:
                state.vector(*args)
            elif target == _FILL:
                state.fill(*args)
            else:
                return state.release(*args)
            return None
        finally:
            if outer:
                active = None

    return ReplayTaskRebuildCalls(dispatch)
