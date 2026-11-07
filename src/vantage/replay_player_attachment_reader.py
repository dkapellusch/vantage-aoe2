"""Finite normal14134b780 and seventeen exact container/scalar entry bodies.

Source: player-attachment-reader-source-v1, accepted6ca13148. Current addressed
storage, real children and coherent logical homes retain source ordering. No
native stack/cookie/EH/fault/concurrency parity or diagnostic-string restoration
is supplied. Raw replay float words are copied unchanged; container arithmetic
requires masked nearest-even MXCSR with DAZ/FTZ off and the stated finite domain.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import compare_binary32, divide_binary32, unsigned64_binary32
from .replay_task_containers import _growth
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_MALLOC, _FREE, _ALIGNED = 0x142D6BA78, 0x142D6BAB4, 0x1402A94D0
_FNV, _PRIME = 0xCBF29CE484222325, 0x100000001B3


class UnimplementedReplayPlayerAttachmentDiagnostic(UnresolvedReplayTaskRebuild):
    """An original nonzero fixed Result reached its unprovided diagnostic."""

    def __init__(self, entry: int, site: int, status: int) -> None:
        self.source_entry, self.input_site, self.status = entry, site, status
        super().__init__(f"attachment diagnostic{entry:x} after{site:x}, status{status:x}")


@dataclass(frozen=True, slots=True)
class ReplayPlayerAttachmentReaderScratch:
    """Explicit source windows, with all uninitialized holes seeded by caller.

    reader: postRSP20..140 (288B); scalar:28..60 (56B); reserve:50..58 (8B);
    insert:20..30 (16B); copy:20..58 (56B); rehash:20..38 (24B);
    constructor:20..28 (8B); error:20..28 (8B). Windows belong to separate
    live invocations. Passed local pointers retain relative identity/backing.
    Native register-save/EH/cookie/outside-window identities are excluded.
    """

    reader: bytes
    scalar: bytes
    reserve: bytes
    insert: bytes
    copy: bytes
    rehash: bytes
    constructor: bytes
    error: bytes

    def __post_init__(self) -> None:
        values = (
            (self.reader, 288),
            (self.scalar, 56),
            (self.reserve, 8),
            (self.insert, 16),
            (self.copy, 56),
            (self.rehash, 24),
            (self.constructor, 8),
            (self.error, 8),
        )
        if any(type(value) is not bytes or len(value) != size for value, size in values):
            raise ValueError("explicit288/56/8/16/56/24/8/8-byte attachment seeds required")


@dataclass(frozen=True, slots=True)
class ReplayPlayerAttachmentReaderProfile:
    """Reached per-entry budgets; counters remain source-width/current-bound.

    Records count outer reader records; node visits also bound inner WORD reads
    and list traversals. Pointer stores bound fill loops per invoked entry. Each
    real nested body has its own budgets. No positive count or successful child
    is inferred. Arithmetic admits finite positive load factors and finite ceil
    conversions, with aligned nonwrapping ranges at reached fills/rehashes.
    """

    maximum_records: int
    maximum_node_visits: int
    maximum_pointer_stores: int
    mxcsr: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.maximum_records,
                self.maximum_node_visits,
                self.maximum_pointer_stores,
            )
        ):
            raise ValueError("explicit nonnegative attachment reader budgets required")
        if type(self.mxcsr) is not int or self.mxcsr & ~0x3F != 0x1F80:
            raise ValueError("masked nearest-even MXCSR with DAZ/FTZ off required")


@dataclass(slots=True)
class _State:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    imports: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics
    bind_local: LocalBinding
    scratch: ReplayPlayerAttachmentReaderScratch
    profile: ReplayPlayerAttachmentReaderProfile
    visits: int = 0
    stores: int = 0
    records: int = 0

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def call(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def visit(self) -> None:
        if self.visits >= self.profile.maximum_node_visits:
            raise UnresolvedReplayTaskRebuild("attachment node/inner-read budget exhausted")
        self.visits += 1

    def pointer(self, address: int, value: int) -> None:
        if self.stores >= self.profile.maximum_pointer_stores:
            raise UnresolvedReplayTaskRebuild("attachment pointer-fill budget exhausted")
        self.stores += 1
        self.write(address, 8, value)

    def record(self) -> None:
        if self.records >= self.profile.maximum_records:
            raise UnresolvedReplayTaskRebuild("attachment reader record budget exhausted")
        self.records += 1

    def zero(self, result: int) -> None:
        for offset in (0, 16, 32):
            self.write(result + offset, 16, 0)

    def release(self, result: int) -> None:
        control = self.read(result + 0x20)
        if control:
            _release(self.context, control, self.calls, self.atomics)

    def error(self, target: int, *args: int) -> None:
        self.call(target, *args)
        raise UnresolvedReplayTaskRebuild(f"nonreturning{target:x} returned before source trap")

    def watson(self, fifth: int) -> None:
        self.write(fifth, 8, 0)
        target = self.read(0x14319A060)
        current_fifth = self.read(fifth)
        _call(self.imports, target, (0, 0, 0, 0, current_fifth))
        raise UnresolvedReplayTaskRebuild("attachment Watson returned before source INT3")

    def factor(self, value: int) -> int:
        if value & 0x80000000 or not value & 0x7FFFFFFF or value & 0x7F800000 == 0x7F800000:
            raise UnresolvedReplayTaskRebuild(
                "attachment load factor outside positive finite domain"
            )
        return value

    def ceiling(self, quotient: int) -> int:
        if quotient & 0x7F800000 == 0x7F800000:
            raise UnresolvedReplayTaskRebuild("attachment growth quotient outside finite domain")
        word = _call(self.calls, 0x142D6E453, (quotient,), width=4)
        threshold = self.read(0x1436A0308, 4)
        if word & 0x80000000 or word & 0x7F800000 == 0x7F800000:
            raise UnresolvedReplayTaskRebuild("attachment ceil result outside finite domain")
        return _growth(word, threshold)


def _increment(value: int) -> int:
    if value >= 0x7FFFFFFF:
        raise UnresolvedReplayTaskRebuild(
            "attachment loop increment outside signedDWORD nonwrap domain"
        )
    return value + 1


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 3) & _U64


def _hash(word: int, width: int) -> int:
    hashed = _FNV
    for offset in range(width):
        hashed = ((hashed ^ (word >> (offset * 8) & 255)) * _PRIME) & _U64
    return hashed


def _fill(state: _State, begin: int, end: int, source: int) -> None:
    """132B three-entry source prefetch, overlap branch and current scalar tail."""
    count = ((end - begin + 7) & _U64) >> 3
    if begin > end:
        count = 0
    current = begin
    if count >= 2:
        prefetched = state.read(source)
        last = (begin - 8 + count * 8) & _U64
        if begin > source or last < source:
            if end < begin or (end - begin) & 7 or end > _U64:
                raise UnresolvedReplayTaskRebuild(
                    "attachment fill range outside aligned finite domain"
                )
            for _ in range(count & ~1):
                state.pointer(current, prefetched)
                current += 8
    if current != end:
        if end < current or (end - current) & 7:
            raise UnresolvedReplayTaskRebuild("attachment scalar fill range outside finite domain")
        while current != end:
            state.pointer(current, state.read(source))
            current += 8


def _range_free(state: _State, pointer: int, count: int) -> None:
    size = count * 8 & _U64
    if size >= 0x1000:
        base = state.read(pointer - 8)
        size = size + 0x27 & _U64
        if (pointer - base - 8) & _U64 > 31:
            with _local(memoryview(bytearray(state.scratch.error)), state.bind_local) as local:
                state.watson(local)
        pointer = base
    state.call(_FREE, pointer, size)


def _reserve(state: _State, header: int, requested: int, value: int) -> None:
    with _local(memoryview(bytearray(state.scratch.reserve)), state.bind_local) as home:
        state.write(home, 8, value)
        begin = state.read(header)
        end = state.read(header + 8)
        if _count(end, begin) >= requested:
            state.call(0x14126D910, begin, end, home)
            return
        if requested > 0x1FFFFFFFFFFFFFFF:
            state.error(0x1402A9460)
        size = requested * 8 & _U64
        replacement = state.call(_ALIGNED, size, result=True)
        current_begin = state.read(header)
        capacity = _count(state.read(header + 16), current_begin)
        if capacity:
            state.call(0x1412879B0, header, current_begin, capacity)
        new_end = replacement + size & _U64
        state.write(header, 8, replacement)
        state.write(header + 8, 8, new_end)
        state.write(header + 16, 8, new_end)
        if new_end < replacement or size & 7:
            raise UnresolvedReplayTaskRebuild("attachment reserve fill outside nonwrap domain")
        while replacement != new_end:
            state.pointer(replacement, value)
            replacement += 8


def _initialize(state: _State, container: int, *, reader: bool) -> int:
    state.write(container, 4, 0)
    state.write(container + 8, 8, 0)
    state.write(container + 16, 8, 0)
    sentinel = state.call(_MALLOC, 24, result=True)
    state.write(sentinel, 8, sentinel)
    state.write(sentinel + 8, 8, sentinel)
    state.write(container + 8, 8, sentinel)
    state.write(container + 0x18, 8, 0)
    if reader:
        state.write(container + 0x20, 16, 0)
    else:
        state.write(container + 0x20, 8, 0)
        state.write(container + 0x28, 8, 0)
    state.write(container + 0x30, 8, 7)
    state.write(container + 0x38, 8, 8)
    state.write(container, 4, 0x3F800000)
    return sentinel


def _value_constructor(state: _State, address: int) -> int:
    with _local(memoryview(bytearray(state.scratch.constructor)), state.bind_local) as home:
        state.write(home, 8, address)
        state.write(address, 4, 0xBF800000)
        state.write(address + 4, 4, 0)
        state.write(address + 8, 2, 0)
        container = address + 0x10 & _U64
        state.write(home, 8, container)
        _initialize(state, container, reader=False)
        state.call(0x141283BD0, container + 0x18, 16, state.read(container + 8))
        return address


def _cleanup(state: _State, container: int) -> None:
    state.call(0x14126E8A0, container + 0x18)
    sentinel = state.read(container + 8)
    tail = state.read(sentinel + 8)
    state.write(tail, 8, 0)
    node = state.read(sentinel)
    while node:
        state.visit()
        following = state.read(node)
        state.call(_FREE, node, 24)
        node = following
    state.call(_FREE, state.read(container + 8), 24)


def _growth_count(state: _State, address: int, requested: int) -> int:
    old = state.read(address + 0x38)
    quotient = divide_binary32(unsigned64_binary32(requested), state.factor(state.read(address, 4)))
    amount = state.ceiling(quotient)
    if old < amount and old < 512:
        amount = max(amount, old * 8 & _U64)
    return old if old >= amount else amount


def _grow_outer_word(state: _State, address: int) -> None:
    count = state.read(address + 0x10) + 1 & _U64
    old = state.read(address + 0x38)
    quotient = divide_binary32(unsigned64_binary32(count), state.factor(state.read(address, 4)))
    amount = state.ceiling(quotient)
    if old < amount:
        old = max(old * 8 & _U64, amount) if old < 512 else amount
    state.call(0x14134AF70, address, old)


def _node_equal(state: _State, node: int, first: int, second: int | None) -> bool:
    if state.read(node + 0x10, 2) != first:
        return False
    return second is None or state.read(node + 0x12, 2) == second


def _splice_rehash(state: _State, node: int, following: int, candidate: int) -> None:
    next_candidate = state.read(candidate)
    old_previous = state.read(node + 8)
    state.write(old_previous, 8, following)
    following_previous = state.read(following + 8)
    state.write(following_previous, 8, next_candidate)
    candidate_previous = state.read(next_candidate + 8)
    state.write(candidate_previous, 8, node)
    state.write(next_candidate + 8, 8, following_previous)
    state.write(following + 8, 8, old_previous)
    state.write(node + 8, 8, candidate_previous)


def _rehash_nodes(state: _State, address: int, sentinel: int, *, pair: bool) -> None:
    current_sentinel = state.read(address + 8)
    node = state.read(current_sentinel)
    following = node
    while node != sentinel:
        state.visit()
        if pair:
            first = state.read(node + 0x10, 2)
            second_word = state.read(node + 0x12, 2)
            second: int | None = second_word
            following = state.read(following)
            hashed = _hash((first << 16) | second_word, 4)
        else:
            low = state.read(node + 0x10, 1)
            high = state.read(node + 0x11, 1)
            following = state.read(following)
            hashed = _hash(low | high << 8, 2)
            first, second = 0, None
        bucket = (hashed & state.read(address + 0x30)) * 16 + state.read(address + 0x18)
        boundary = state.read(bucket)
        if boundary == sentinel:
            state.write(bucket, 8, node)
            state.write(bucket + 8, 8, node)
        else:
            candidate = state.read(bucket + 8)
            if not pair:
                first = state.read(node + 0x10, 2)
            if _node_equal(state, candidate, first, second):
                next_candidate = state.read(candidate)
                if next_candidate != node:
                    # Source already holds next_candidate before the other reads.
                    previous = state.read(node + 8)
                    state.write(previous, 8, following)
                    following_previous = state.read(following + 8)
                    state.write(following_previous, 8, next_candidate)
                    candidate_previous = state.read(next_candidate + 8)
                    state.write(candidate_previous, 8, node)
                    state.write(next_candidate + 8, 8, following_previous)
                    state.write(following + 8, 8, previous)
                    state.write(node + 8, 8, candidate_previous)
                state.write(bucket + 8, 8, node)
            else:
                found = False
                while boundary != candidate:
                    state.visit()
                    candidate = state.read(candidate + 8)
                    if _node_equal(state, candidate, first, second):
                        found = True
                        break
                if found:
                    _splice_rehash(state, node, following, candidate)
                else:
                    previous = state.read(node + 8)
                    state.write(previous, 8, following)
                    following_previous = state.read(following + 8)
                    state.write(following_previous, 8, candidate)
                    candidate_previous = state.read(candidate + 8)
                    state.write(candidate_previous, 8, node)
                    state.write(candidate + 8, 8, following_previous)
                    state.write(following + 8, 8, previous)
                    state.write(node + 8, 8, candidate_previous)
                    state.write(bucket, 8, node)
        node = following


def _buckets(state: _State, requested: int) -> int:
    if requested > 1 << 59:
        state.error(0x142D66698, 0x143682938)
    source = ((requested - 1) & _U64) | 1
    return 1 << (source.bit_length() & 63)


def _rehash(state: _State, address: int, requested: int, *, pair: bool, inner: bool) -> None:
    buckets = _buckets(state, requested)
    if inner:
        sentinel = state.read(address + 8)
        state.call(0x141283BD0, address + 0x18, buckets * 2, sentinel)
        state.write(address + 0x38, 8, buckets)
        state.write(address + 0x30, 8, buckets - 1)
        _rehash_nodes(state, address, sentinel, pair=False)
        return
    with _local(memoryview(bytearray(state.scratch.rehash)), state.bind_local) as frame:
        begin = state.read(address + 0x18)
        end = state.read(address + 0x20)
        sentinel = state.read(address + 8)
        state.write(frame + 0x10, 8, sentinel)
        requested_words = buckets * 2
        if _count(end, begin) < requested_words:
            if requested_words > 0x1FFFFFFFFFFFFFFF:
                state.error(0x1402A9460)
            size = requested_words * 8 & _U64
            replacement = state.call(_ALIGNED, size, result=True)
            current_begin = state.read(address + 0x18)
            capacity = state.read(address + 0x28)
            count = _count(capacity, current_begin)
            if count:
                free_size = count * 8 & _U64
                free_pointer = current_begin
                if free_size >= 0x1000:
                    base = state.read(current_begin - 8)
                    free_size = free_size + 0x27 & _U64
                    if (current_begin - base - 8) & _U64 > 31:
                        state.watson(frame)
                    free_pointer = base
                state.call(_FREE, free_pointer, free_size)
            new_end = replacement + size & _U64
            state.write(address + 0x18, 8, replacement)
            state.write(address + 0x20, 8, new_end)
            state.write(address + 0x28, 8, new_end)
            if new_end < replacement:
                raise UnresolvedReplayTaskRebuild("attachment rehash fill wraps")
            while replacement != new_end:
                state.pointer(replacement, sentinel)
                replacement += 8
        else:
            state.call(0x141345BA0 if pair else 0x141345B10, begin, end, frame + 0x10)
        state.write(address + 0x38, 8, buckets)
        state.write(address + 0x30, 8, buckets - 1)
        _rehash_nodes(state, address, sentinel, pair=pair)


def _search(
    state: _State, tail: int, boundary: int, first: int, second: int | None, *, new_node: int = 0
) -> tuple[int, bool]:
    node = tail
    while True:
        state.visit()
        equal = state.read(node + 0x10, 2) == first
        if equal and second is not None:
            candidate_second = state.read(node + 0x12, 2)
            expected_second = state.read(new_node + 0x12, 2) if new_node else second
            equal = candidate_second == expected_second
        if equal:
            return node, True
        if node == boundary:
            return node, False
        node = state.read(node + 8)


def _insert(state: _State, address: int, output: int, key: int, *, pair: bool, inner: bool) -> int:
    if pair:
        second_word = state.read(key + 2, 2)
        second: int | None = second_word
        first = state.read(key, 2)
        hashed = _hash((first << 16) | second_word, 4)
    else:
        low = state.read(key, 1)
        high = state.read(key + 1, 1)
        hashed = _hash(low | high << 8, 2)
        first, second = 0, None
    index = (hashed & state.read(address + 0x30)) * 16
    table = state.read(address + 0x18)
    tail = state.read(table + index + 8)
    head_cell = address + 8 & _U64
    predecessor = state.read(head_cell)
    if tail != predecessor:
        boundary = state.read(table + index)
        if not pair:
            first = state.read(key, 2)
        predecessor, found = _search(state, tail, boundary, first, second)
        if found:
            state.write(output, 8, predecessor)
            state.write(output + 8, 1, 0)
            return output
    maximum = 0xAAAAAAAAAAAAAAA if inner else 0x276276276276276
    if state.read(address + 0x10) == maximum:
        state.error(0x142D66698, 0x143682918)
    with _local(memoryview(bytearray(state.scratch.insert)), state.bind_local) as frame:
        state.write(frame, 8, head_cell)
        state.write(frame + 8, 8, 0)
        node = state.call(_MALLOC, 24 if inner else 104, result=True)
        state.write(frame + 8, 8, node)
        state.write(node + 0x10, 4 if pair else 2, state.read(key, 4 if pair else 2))
        if not inner:
            for offset in range(0x18, 0x68, 16):
                state.write(node + offset, 16, 0)
            state.call(0x141345C30, node + 0x18)
        if pair:
            factor = state.factor(state.read(address, 4))
            old_buckets = state.read(address + 0x38)
            count = state.read(address + 0x10) + 1 & _U64
            total = unsigned64_binary32(count)
            ratio = divide_binary32(total, unsigned64_binary32(old_buckets))
        else:
            count = state.read(address + 0x10) + 1 & _U64
            total = unsigned64_binary32(count)
            old_buckets = state.read(address + 0x38)
            ratio = divide_binary32(total, unsigned64_binary32(old_buckets))
            factor = state.factor(state.read(address, 4))
        order = compare_binary32(ratio, factor)
        if order is None:
            raise UnresolvedReplayTaskRebuild("attachment load ratio outside ordered finite domain")
        if order > 0:
            if pair:
                requested = state.ceiling(divide_binary32(total, factor))
                if old_buckets < requested:
                    old_buckets = (
                        max(old_buckets * 8 & _U64, requested) if old_buckets < 512 else requested
                    )
                state.call(0x14134B200, address, old_buckets)
            elif inner:
                requested = state.call(0x14134AED0, address, count, result=True)
                state.call(0x1412840B0, address, requested)
            else:
                state.call(0x14134B4B0, address)
            index = (hashed & state.read(address + 0x30)) * 16
            table = state.read(address + 0x18)
            tail = state.read(table + index + 8)
            predecessor = state.read(head_cell)
            if tail != predecessor:
                boundary = state.read(table + index)
                current_first = state.read(node + 0x10, 2)
                predecessor, found = _search(
                    state,
                    tail,
                    boundary,
                    current_first,
                    0 if pair else None,
                    new_node=node if pair else 0,
                )
                if found:
                    predecessor = state.read(predecessor)
        following = state.read(predecessor + 8)
        state.write(address + 0x10, 8, state.read(address + 0x10) + 1)
        state.write(node, 8, predecessor)
        state.write(node + 8, 8, following)
        state.write(following, 8, node)
        state.write(predecessor + 8, 8, node)
        index = (hashed & state.read(address + 0x30)) * 16
        table = state.read(address + 0x18)
        beginning = state.read(table + index)
        if beginning == state.read(head_cell):
            state.write(table + index, 8, node)
            state.write(table + index + 8, 8, node)
        elif beginning == predecessor:
            state.write(table + index, 8, node)
        elif state.read(table + index + 8) == following:
            state.write(table + index + 8, 8, node)
        state.write(output, 8, node)
        state.write(output + 8, 1, 1)
        return output


def _copy(state: _State, destination: int, source: int) -> int:
    if destination == source:
        return destination
    with _local(memoryview(bytearray(state.scratch.copy)), state.bind_local) as frame:
        state.write(frame + 0x30, 8, destination)
        state.write(destination, 4, state.read(source, 4))
        head_cell = destination + 8 & _U64
        source_head = state.read(source + 8)
        source_node = state.read(source_head)
        destination_head = state.read(head_cell)
        current = state.read(destination_head)
        while current != destination_head:
            state.visit()
            if source_node == source_head:
                previous = state.read(current + 8)
                state.write(previous, 8, destination_head)
                state.write(destination_head + 8, 8, previous)
                count = 0
                while current != destination_head:
                    state.visit()
                    following = state.read(current)
                    state.call(_FREE, current, 24)
                    current = following
                    count += 1
                state.write(head_cell + 8, 8, state.read(head_cell + 8) - count)
                break
            state.write(current + 0x10, 2, state.read(source_node + 0x10, 2))
            current = state.read(current)
            source_node = state.read(source_node)
        else:
            state.write(frame + 0x10, 8, head_cell)
            count = 0
            state.write(frame + 0x18, 8, 0)
            state.write(frame + 0x20, 16, 0)
            first = last = 0
            if source_node != source_head:
                state.visit()
                state.write(frame, 8, head_cell)
                state.write(frame + 8, 8, 0)
                first = state.call(_MALLOC, 24, result=True)
                state.write(first + 0x10, 2, state.read(source_node + 0x10, 2))
                state.write(frame + 8, 8, 0)
                state.write(frame + 0x28, 8, first)
                last = first
                state.write(frame + 0x20, 8, first)
                count = 1
                state.write(frame + 0x18, 8, count)
                source_node = state.read(source_node)
                while source_node != source_head:
                    state.visit()
                    state.write(frame + 8, 8, 0)
                    node = state.call(_MALLOC, 24, result=True)
                    state.write(node + 0x10, 2, state.read(source_node + 0x10, 2))
                    state.write(last, 8, node)
                    state.write(node + 8, 8, last)
                    state.write(frame + 8, 8, 0)
                    last = node
                    state.write(frame + 0x20, 8, node)
                    count += 1
                    state.write(frame + 0x18, 8, count)
                    source_node = state.read(source_node)
            else:
                first = state.read(frame + 0x28)
                last = state.read(frame + 0x20)
            current_head = state.read(head_cell)
            if count:
                previous = state.read(current_head + 8)
                state.write(first + 8, 8, previous)
                state.write(previous, 8, first)
                state.write(last, 8, current_head)
                state.write(current_head + 8, 8, last)
                state.write(head_cell + 8, 8, state.read(head_cell + 8) + count)
        count = state.read(destination + 0x10)
        buckets = state.call(0x14134AED0, destination, count, result=True)
        state.call(0x1412840B0, destination, buckets)
        return destination


# Literal original reader sites: dest postRSP, width, typed target, line/detail,
# raw error entry, forwarded error entry, pair-helper versus inline A cleanup.
_SITES = {
    0x14134B7F2: (0x130, 4, 0, 0, 0, 0x14134B811, 0x14134B889, True),
    0x14134BA31: (0xCC, 2, 0, 0, 0, 0x14134BA51, 0x14134C85E, False),
    0x14134BB35: (0xCE, 2, 0, 0, 0, 0x14134BB55, 0x14134C723, False),
    0x14134BCAE: (0xE0, 4, 0, 0, 0, 0x14134BCCD, 0x14134C613, True),
    0x14134BD8F: (0xE4, 4, 0x140B81E60, 0x99, 0x1432BF988, 0, 0x14134C4E3, True),
    0x14134BDEF: (0xE8, 2, 0x140B81C60, 0x9A, 0x1432BF9A8, 0, 0x14134C3A3, True),
    0x14134BE4F: (0xD0, 4, 0x140B81D60, 0x9D, 0x1432BF9C0, 0, 0x14134C267, True),
    0x14134BEB8: (0xC8, 2, 0x140B81C60, 0xA2, 0x1432BF9D8, 0, 0x14134C133, True),
    0x14134BF7F: (0x138, 4, 0, 0, 0, 0x14134BF9F, 0x14134C012, False),
    0x14134CA02: (0xD0, 2, 0, 0, 0, 0x14134CA22, 0x14134D788, False),
    0x14134CB7D: (0xE0, 4, 0, 0, 0, 0x14134CB9D, 0x14134D5E8, False),
    0x14134CC84: (0xE4, 4, 0, 0, 0, 0x14134CCA4, 0x14134D443, False),
    0x14134CD88: (0xE8, 2, 0, 0, 0, 0x14134CDA8, 0x14134D307, True),
    0x14134CE6A: (0xCC, 4, 0x140B81D60, 0xB6, 0x1432BF9C0, 0, 0x14134D1B1, True),
    0x14134CED1: (0xC8, 2, 0, 0, 0, 0x14134CEF1, 0x14134D072, True),
}


def _input(state: _State, frame: int, stream: int, site: int) -> None:
    destination, width, target, line, detail, raw_error, error, pair = _SITES[site]
    forwarded, raw = frame + 0x48, frame + 0x78
    state.zero(forwarded)
    if target:
        state.write(frame + 8, 8, frame + destination - 0x20)
        state.write(frame, 8, stream)
        state.call(
            target, forwarded, 0x1432BF8C0, line, detail, state.read(frame), state.read(frame + 8)
        )
    else:
        state.zero(raw)
        table = state.read(stream)
        destination_address = frame + destination - 0x20
        state.call(state.read(table + 0x18), stream, raw, destination_address, width)
        state.zero(forwarded)
        state.write(raw + 0x28, 1, 1)
        status = state.read(raw + 0x18)
        if status:
            raise UnimplementedReplayPlayerAttachmentDiagnostic(raw_error, site, status)
        state.call(0x1409076B0, forwarded, raw)
        state.release(raw)
        state.call(0x1402BD890, raw)
    status = state.read(forwarded + 0x18)
    if status:
        raise UnimplementedReplayPlayerAttachmentDiagnostic(error, site, status)
    state.write(forwarded + 0x28, 1, 1)
    if pair:
        state.call(0x1408EE150, forwarded + 0x18)
    else:
        state.release(forwarded)
    state.call(0x1402BD890, forwarded)


def _reader(state: _State, address: int, output: int, stream: int) -> int:
    with _local(memoryview(bytearray(state.scratch.reader)), state.bind_local) as frame:
        state.write(frame + 0x18, 8, address)
        state.write(frame + 0x118, 8, output)
        _input(state, frame, stream, 0x14134B7F2)
        first_index = 0
        if _signed(state.read(frame + 0x110, 4), 4) > 0:
            while True:
                state.record()
                _input(state, frame, stream, 0x14134BA31)
                _input(state, frame, stream, 0x14134BB35)
                state.write(frame + 0xC0, 4, 0xBF800000)
                state.write(frame + 0xC4, 4, 0)
                state.write(frame + 0xC8, 2, 0)
                local = frame + 0xD0
                state.write(frame + 0x20, 8, local)
                sentinel = _initialize(state, local, reader=True)
                state.call(0x141283BD0, local + 0x18, 16, sentinel)
                for site in (0x14134BCAE, 0x14134BD8F, 0x14134BDEF, 0x14134BE4F):
                    _input(state, frame, stream, site)
                inner_index = 0
                if _signed(state.read(frame + 0xB0, 4), 4) > 0:
                    while True:
                        state.visit()
                        _input(state, frame, stream, 0x14134BEB8)
                        state.call(0x141345920, local, frame + 0x28, frame + 0xA8)
                        inner_index = _increment(inner_index)
                        if inner_index >= _signed(state.read(frame + 0xB0, 4), 4):
                            break
                iterator = state.call(0x141345460, address, frame + 0x38, frame + 0xAC, result=True)
                record = state.read(iterator)
                for offset, source, width in ((0x18, 0xC0, 4), (0x1C, 0xC4, 4), (0x20, 0xC8, 2)):
                    state.write(record + offset, width, state.read(frame + source, width))
                state.call(0x141345F50, record + 0x28, local)
                state.call(0x141345E80, local)
                first_index = _increment(first_index)
                if first_index >= _signed(state.read(frame + 0x110, 4), 4):
                    break
        _input(state, frame, stream, 0x14134BF7F)
        second_index = 0
        if _signed(state.read(frame + 0x118, 4), 4) > 0:
            while True:
                state.record()
                _input(state, frame, stream, 0x14134CA02)
                state.write(frame + 0xC0, 4, 0xBF800000)
                state.write(frame + 0xC4, 4, 0)
                state.write(frame + 0xC8, 2, 0)
                local = frame + 0xD0
                state.write(frame + 0x20, 8, local)
                sentinel = _initialize(state, local, reader=True)
                state.call(0x141283BD0, local + 0x18, 16, sentinel)
                for site in (0x14134CB7D, 0x14134CC84, 0x14134CD88, 0x14134CE6A):
                    _input(state, frame, stream, site)
                inner_index = 0
                if _signed(state.read(frame + 0xAC, 4), 4) > 0:
                    while True:
                        state.visit()
                        _input(state, frame, stream, 0x14134CED1)
                        state.call(0x141345920, local, frame + 0x38, frame + 0xA8)
                        inner_index = _increment(inner_index)
                        if inner_index >= _signed(state.read(frame + 0xAC, 4), 4):
                            break
                current = state.read(frame + 0x18)
                iterator = state.call(
                    0x141345250, current + 0x40, frame + 0x28, frame + 0xB0, result=True
                )
                record = state.read(iterator)
                for offset, source, width in ((0x18, 0xC0, 4), (0x1C, 0xC4, 4), (0x20, 0xC8, 2)):
                    state.write(record + offset, width, state.read(frame + source, width))
                state.call(0x141345F50, record + 0x28, local)
                _cleanup(state, local)
                second_index = _increment(second_index)
                if second_index >= _signed(state.read(frame + 0x118, 4), 4):
                    break
        for offset in (0, 8, 16, 24, 32):
            state.write(output + offset, 8, 0)
        state.write(output + 40, 1, 0)
        return output


def _word_reader(
    state: _State, output: int, metadata: int, line: int, detail: int, stream: int, destination: int
) -> int:
    with _local(memoryview(bytearray(state.scratch.scalar)), state.bind_local) as frame:
        state.write(frame, 8, output)
        raw = frame + 8
        state.zero(raw)
        table = state.read(stream)
        state.call(state.read(table + 0x18), stream, raw, destination, 2)
        state.zero(output)
        state.write(raw + 0x28, 1, 1)
        if state.read(raw + 0x18):
            state.call(0x140900ED0, raw, metadata, line & _U32, detail)
        state.call(0x1409076B0, output, raw)
        state.release(raw)
        state.call(0x1402BD890, raw)
        return output


_ARITIES = {
    0x14134B780: 3,
    0x140B81C60: 6,
    0x141283BD0: 3,
    0x14126D910: 3,
    0x141345BA0: 3,
    0x141345B10: 3,
    0x1412879B0: 3,
    0x141345250: 3,
    0x141345460: 3,
    0x141345920: 3,
    0x141345C30: 1,
    0x141345F50: 2,
    0x141345E80: 1,
    0x14134AED0: 2,
    0x14134B4B0: 1,
    0x1412840B0: 2,
    0x14134AF70: 2,
    0x14134B200: 2,
}


def bind_replay_player_attachment_reader(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAttachmentReaderScratch,
    profile: ReplayPlayerAttachmentReaderProfile,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind only the eighteen accepted normal entries; actual children delegate.

    Supplying a dispatcher does not establish restored class, native image or
    live stream identity. These effective scalar calls expose only the explicit
    logical windows above. Unknown targets remain mandatory through calls.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual atomic/local attachment bindings required")
    if not isinstance(scratch, ReplayPlayerAttachmentReaderScratch) or not isinstance(
        profile, ReplayPlayerAttachmentReaderProfile
    ):
        raise ValueError("explicit attachment reader scratch/profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed attachment reader call")
        _validate(context, calls, *args)
        state = _State(context, calls, terminal, atomics, bind_local, scratch, profile)
        if target == 0x14134B780:
            return _reader(state, *args)
        if target == 0x140B81C60:
            return _word_reader(state, *args)
        if target == 0x141283BD0:
            _reserve(state, *args)
        elif target in (0x14126D910, 0x141345BA0, 0x141345B10):
            _fill(state, *args)
        elif target == 0x1412879B0:
            _range_free(state, args[1], args[2])
        elif target in (0x141345250, 0x141345460, 0x141345920):
            return _insert(state, *args, pair=target == 0x141345460, inner=target == 0x141345920)
        elif target == 0x141345C30:
            return _value_constructor(state, *args)
        elif target == 0x141345F50:
            return _copy(state, *args)
        elif target == 0x141345E80:
            _cleanup(state, *args)
        elif target == 0x14134AED0:
            return _growth_count(state, *args)
        elif target == 0x14134B4B0:
            _grow_outer_word(state, *args)
        else:
            _rehash(state, *args, pair=target == 0x14134B200, inner=target == 0x1412840B0)
        return None

    return ReplayTaskRebuildCalls(dispatch)
