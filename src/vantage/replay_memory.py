"""Owned virtual memory for the replay simulator's address-based body ports.

Addresses belong to this Python runtime, not a live process. Allocations start
undefined: copying preserves definedness, while interpreting an unwritten word
fails explicitly. The successful allocator layout follows build54800's
1402a94d0; malloc/new-handler, C++ unwinding and native fault parity are excluded.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right, insort
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from .replay_task_rebuild import ReplayTaskRebuildCalls, UnresolvedReplayTaskRebuild

_U64 = (1 << 64) - 1


class ReplayMemoryError(ValueError):
    """The engine has no admitted current backing for an operation."""


class ReplayMemoryRuntimeError(RuntimeError):
    """A reached nonreturning runtime error terminates the simulated operation."""

    def __init__(self, target: int, args: tuple[int, ...]) -> None:
        self.target, self.args_words = target, args
        super().__init__(f"replay runtime error{target:x}: {args}")


@dataclass(frozen=True, slots=True)
class ReplayMemoryRegionSnapshot:
    address: int
    data: bytes
    defined: bytes
    writable: bool
    owned: bool


@dataclass(frozen=True, slots=True)
class ReplayMemorySnapshot:
    """Memory state only; a complete World/seek checkpoint needs its other state."""

    next_address: int
    max_bytes: int
    regions: tuple[ReplayMemoryRegionSnapshot, ...]


@dataclass(slots=True)
class _Region:
    address: int
    data: memoryview
    defined: bytearray
    writable: bool
    owned: bool
    borrowed: bool = False


def _u64(value: int, label: str) -> None:
    if type(value) is not int or not 0 <= value <= _U64:
        raise ValueError(f"{label} must be a raw u64")


def _ceil_word(word: int) -> int:
    if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
        raise ValueError("ceil input must be a raw binary32 word")
    exponent = word >> 23 & 255
    if exponent == 255:
        if word & 0x7FFFFF:
            raise UnresolvedReplayTaskRebuild("ceil NaN payload binding is unavailable")
        return word
    if exponent >= 150 or not word & 0x7FFFFFFF:
        return word
    if exponent < 127:
        return 0x80000000 if word >> 31 else 0x3F800000
    mask = (1 << (150 - exponent)) - 1
    return (word if word >> 31 else word + mask) & ~mask


class ReplayMemory:
    """Finite, deterministic little-endian storage with live scoped local views.

    Imported bytes are explicit; allocations contain undefined bytes until
    written. Reads/writes may cross adjacent regions and are checked before
    effects. No partial native fault behavior is promised. Allocation addresses
    are fresh, engine-owned tokens; they do not establish restored object or
    vtable identities. The byte limit is an engine resource limit.
    """

    def __init__(self, *, start: int = 0x10000000000, max_bytes: int = 256 << 20) -> None:
        _u64(start, "allocation start")
        if not start or type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("nonnull start and nonnegative byte limit required")
        self._next = start
        self._limit = max_bytes
        self._bytes = 0
        self._starts: list[int] = []
        self._regions: dict[int, _Region] = {}
        self._locals: set[int] = set()

    @property
    def mapped_bytes(self) -> int:
        return self._bytes

    def _check_region(self, address: int, size: int) -> None:
        _u64(address, "mapped address")
        if not size or address + size > 1 << 64:
            raise ValueError("nonempty, nonwrapping memory region required")
        index = bisect_left(self._starts, address)
        if index and self._starts[index - 1] + len(self._regions[self._starts[index - 1]].data) > (
            address
        ):
            raise ReplayMemoryError("memory regions overlap")
        if index < len(self._starts) and address + size > self._starts[index]:
            raise ReplayMemoryError("memory regions overlap")
        if size > self._limit - self._bytes:
            raise MemoryError("replay memory byte limit exceeded")

    def _insert(self, region: _Region) -> None:
        size = len(region.data)
        self._check_region(region.address, size)
        insort(self._starts, region.address)
        self._regions[region.address] = region
        self._bytes += size

    def _fresh(self, size: int) -> int:
        cursor = (self._next + 15) & ~15
        while cursor + size <= 1 << 64:
            index = bisect_right(self._starts, cursor)
            if index:
                previous = self._regions[self._starts[index - 1]]
                end = previous.address + len(previous.data)
                if cursor < end:
                    cursor = (end + 15) & ~15
                    continue
            if index < len(self._starts) and cursor + size > self._starts[index]:
                region = self._regions[self._starts[index]]
                cursor = (region.address + len(region.data) + 15) & ~15
                continue
            return cursor
        raise MemoryError("replay address space exhausted")

    def map_bytes(self, address: int, data: bytes, *, writable: bool = True) -> None:
        """Copy explicit input bytes into a disjoint current memory region."""
        if type(data) is not bytes or type(writable) is not bool:
            raise ValueError("explicit bytes and boolean writable flag required")
        self._check_region(address, len(data))
        self._insert(
            _Region(
                address,
                memoryview(bytearray(data)),
                bytearray(b"\x01") * len(data),
                writable,
                False,
            )
        )

    def allocate(self, size: int) -> int:
        """Allocate fresh undefined storage; raw zero-size allocation is nonnull."""
        _u64(size, "allocation size")
        extent = max(1, size)
        if extent > self._limit - self._bytes:
            raise MemoryError("replay memory byte limit exceeded")
        address = self._fresh(extent)
        self._insert(_Region(address, memoryview(bytearray(extent)), bytearray(extent), True, True))
        self._next = address + extent
        return address

    def allocate_aligned(self, size: int) -> int:
        """Successful1402a94d0 layout, including the large allocation backpointer."""
        _u64(size, "aligned allocation size")
        if not size:
            return 0
        if size < 0x1000:
            return self.allocate(size)
        if (size + 0x27) & _U64 <= size:
            raise ReplayMemoryRuntimeError(0x1402A9460, ())
        base = self.allocate(size + 0x27)
        address = (base + 0x27) & ~31
        self.write(address - 8, 8, base)
        return address

    def calloc(self, count: int, element_size: int) -> int:
        """Successful zero allocation or unsigned product-overflow null result.

        Zero product uses the existing nonnull zero-size allocation profile;
        its one-byte backing extent remains undefined. Engine resource limits
        still raise MemoryError. No native errno or allocation-failure callback
        behavior is claimed.
        """
        _u64(count, "calloc count")
        _u64(element_size, "calloc element size")
        if count and element_size > _U64 // count:
            return 0
        size = count * element_size
        address = self.allocate(size)
        self.fill(address, 0, size)
        return address

    def free(self, address: int) -> None:
        """CRT-style null no-op, otherwise release an owned allocation base."""
        _u64(address, "free pointer")
        if not address:
            return
        region = self._regions.get(address)
        if region is None or not region.owned:
            raise ReplayMemoryError("free requires an owned allocation base")
        self._remove(address)

    def _remove(self, address: int) -> None:
        size = len(self._regions[address].data)
        self._regions.pop(address)
        self._starts.remove(address)
        self._bytes -= size

    def _parts(
        self, address: int, size: int, *, write: bool = False
    ) -> list[tuple[_Region, int, int]]:
        _u64(address, "memory address")
        _u64(size, "memory size")
        if address + size > 1 << 64:
            raise ReplayMemoryError("memory access wraps the address space")
        parts = []
        cursor, remaining = address, size
        while remaining:
            index = bisect_right(self._starts, cursor) - 1
            if index < 0:
                raise ReplayMemoryError(f"unmapped replay address{cursor:x}")
            region = self._regions[self._starts[index]]
            offset = cursor - region.address
            if offset >= len(region.data):
                raise ReplayMemoryError(f"unmapped replay address{cursor:x}")
            if write and not region.writable:
                raise ReplayMemoryError(f"readonly replay address{cursor:x}")
            take = min(remaining, len(region.data) - offset)
            parts.append((region, offset, take))
            cursor, remaining = cursor + take, remaining - take
        return parts

    def read_bytes(self, address: int, size: int) -> bytes:
        parts = self._parts(address, size)
        if any(0 in region.defined[offset : offset + count] for region, offset, count in parts):
            raise ReplayMemoryError(f"undefined replay bytes at{address:x}/{size}")
        return b"".join(region.data[offset : offset + count] for region, offset, count in parts)

    def read(self, address: int, width: int) -> int:
        if type(width) is not int or width <= 0:
            raise ValueError("positive scalar width required")
        return int.from_bytes(self.read_bytes(address, width), "little")

    def c_string_length(self, address: int) -> int:
        """Count defined bytes before the first NUL in current engine backing.

        Adjacent mappings and live locals are readable. Bytes after the first
        NUL need no backing or definedness. Missing, undefined or wrapping
        backing raises ReplayMemoryError; no decoding or memory writes occur.
        This is a CRT semantic provider, without optimized native instruction,
        fault, exception or concurrent-writer parity.
        """
        _u64(address, "C-string address")
        cursor = address
        while self.read(cursor, 1):
            if cursor == _U64:
                raise ReplayMemoryError("memory access wraps the address space")
            cursor += 1
        return cursor - address

    def write_bytes(self, address: int, data: bytes) -> None:
        if type(data) is not bytes:
            raise ValueError("explicit bytes required")
        parts = self._parts(address, len(data), write=True)
        cursor = 0
        for region, offset, count in parts:
            region.data[offset : offset + count] = data[cursor : cursor + count]
            region.defined[offset : offset + count] = b"\x01" * count
            cursor += count

    def write(self, address: int, width: int, value: int) -> None:
        if (
            type(width) is not int
            or width <= 0
            or type(value) is not int
            or value < 0
            or value.bit_length() > width * 8
        ):
            raise ValueError("positive width and unsigned scalar value required")
        self._parts(address, width, write=True)
        self.write_bytes(address, value.to_bytes(width, "little"))

    def compare_exchange_u32(self, address: int, expected: int, desired: int) -> int:
        """Single-threaded engine CMPXCHG effect; return the prior DWORD.

        This runtime has no concurrent memory writers. This method is one
        indivisible engine operation, not a host/native CPU atomic primitive.
        Whole-span writable/defined backing is required even for a mismatch;
        native alignment, fault ordering and memory fences are excluded.
        """
        for value in (expected, desired):
            if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
                raise ValueError("compare exchange requires raw u32 values")
        self._parts(address, 4, write=True)
        previous = self.read(address, 4)
        if previous == expected:
            self.write(address, 4, desired)
        return previous

    def fetch_add_u32(self, address: int, addend: int) -> int:
        """Single-threaded engine XADD/INC effect, with wrapped DWORD sum.

        Return the prior word. The same owned-memory, whole-span preflight
        and concurrency/fault exclusions as compare_exchange_u32 apply.
        """
        if type(addend) is not int or not 0 <= addend <= 0xFFFFFFFF:
            raise ValueError("fetch add requires a raw u32 addend")
        self._parts(address, 4, write=True)
        previous = self.read(address, 4)
        self.write(address, 4, (previous + addend) & 0xFFFFFFFF)
        return previous

    def move(self, destination: int, source: int, size: int) -> int:
        """Snapshot bytes/definedness; undefined transfers into borrowed locals refuse.

        Borrowed Python views have external writers without metadata callbacks.
        They must remain fully initialized; otherwise aliases could silently
        interpret undefined bytes or reject subsequent external initialized
        writes. Owned/private backing preserves undefined bytes exactly.
        """
        source_parts = self._parts(source, size)
        destination_parts = self._parts(destination, size, write=True)
        data = b"".join(r.data[o : o + n] for r, o, n in source_parts)
        defined = b"".join(r.defined[o : o + n] for r, o, n in source_parts)
        cursor = 0
        for region, _offset, count in destination_parts:
            if region.borrowed and 0 in defined[cursor : cursor + count]:
                raise ReplayMemoryError("undefined transfer into borrowed local")
            cursor += count
        cursor = 0
        for region, offset, count in destination_parts:
            region.data[offset : offset + count] = data[cursor : cursor + count]
            region.defined[offset : offset + count] = defined[cursor : cursor + count]
            cursor += count
        return destination

    def fill(self, destination: int, value: int, size: int) -> int:
        """Memset byte effects after whole-span writable preflight.

        Zero size performs no data access. Undefined destination bytes become
        defined, including live borrowed views. This is an engine primitive,
        with no CRT instruction or native fault-atomicity claim.
        """
        _u64(value, "fill value")
        parts = self._parts(destination, size, write=True)
        byte = bytes((value & 255,))
        for region, offset, count in parts:
            region.data[offset : offset + count] = byte * count
            region.defined[offset : offset + count] = b"\x01" * count
        return destination

    @contextmanager
    def bind_local(self, view: memoryview) -> Iterator[int]:
        """Expose a fully initialized live view without reading its bytes on entry.

        A retained independent view keeps the binding valid if the caller
        releases its view. Nested aliases remain live. Undefined raw transfers
        into borrowed locals are refused before effects; external writes need
        no metadata notification because these local bytes stay defined.
        """
        if (
            not isinstance(view, memoryview)
            or view.ndim != 1
            or view.format != "B"
            or not view.c_contiguous
            or view.readonly
            or not len(view)
        ):
            raise ValueError("nonempty writable contiguous byte view required")
        address = self._fresh(len(view))
        self._check_region(address, len(view))
        retained = memoryview(view)
        self._insert(_Region(address, retained, bytearray(b"\x01") * len(view), True, False, True))
        self._locals.add(address)
        self._next = address + len(view)
        try:
            yield address
        finally:
            self._remove(address)
            self._locals.remove(address)
            retained.release()

    def snapshot(self) -> ReplayMemorySnapshot:
        if self._locals:
            raise ReplayMemoryError("cannot snapshot borrowed local bindings")
        return ReplayMemorySnapshot(
            self._next,
            self._limit,
            tuple(
                ReplayMemoryRegionSnapshot(
                    r.address, bytes(r.data), bytes(r.defined), r.writable, r.owned
                )
                for r in (self._regions[address] for address in self._starts)
            ),
        )

    @classmethod
    def from_snapshot(cls, snapshot: ReplayMemorySnapshot) -> ReplayMemory:
        if not isinstance(snapshot, ReplayMemorySnapshot):
            raise ValueError("explicit replay memory snapshot required")
        if type(snapshot.next_address) is not int or not 0 < snapshot.next_address <= 1 << 64:
            raise ValueError("invalid replay allocation cursor")
        result = cls(start=min(snapshot.next_address, _U64), max_bytes=snapshot.max_bytes)
        result._next = snapshot.next_address
        for region in snapshot.regions:
            if (
                not isinstance(region, ReplayMemoryRegionSnapshot)
                or type(region.data) is not bytes
                or type(region.defined) is not bytes
                or len(region.data) != len(region.defined)
                or any(value not in (0, 1) for value in region.defined)
                or type(region.writable) is not bool
                or type(region.owned) is not bool
            ):
                raise ValueError("invalid replay memory snapshot region")
            if len(region.data) > result._limit - result._bytes:
                raise MemoryError("replay memory byte limit exceeded")
            result._insert(
                _Region(
                    region.address,
                    memoryview(bytearray(region.data)),
                    bytearray(region.defined),
                    region.writable,
                    region.owned,
                )
            )
        return result

    def runtime_calls(
        self,
        delegate: ReplayTaskRebuildCalls | None = None,
        *,
        calloc_target: int | None = None,
        strlen_target: int | None = None,
    ) -> ReplayTaskRebuildCalls:
        """Concrete successful owned-memory runtime effects for body execution.

        Error leaves terminate with an engine exception; C++ exception objects,
        allocation-failure new-handlers and native FPstatus are not simulated.
        NaN ceil payload behavior and unknown effective targets require a real
        delegate. Free accepts RCX alone or the caller's ignored size in RDX.
        calloc_target and strlen_target are optional explicit engine capability
        identities, not observed DLL addresses. A body must still read its
        current IAT before dispatching. No strlen target is bound by default.
        """
        if delegate is not None and not isinstance(delegate, ReplayTaskRebuildCalls):
            raise ValueError("explicit helper delegate required")
        if calloc_target is not None:
            _u64(calloc_target, "calloc target")
            if not calloc_target or calloc_target in (
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
            ):
                raise ValueError("nonnull distinct engine calloc target required")
        if strlen_target is not None:
            _u64(strlen_target, "strlen target")
            if (
                not strlen_target
                or strlen_target == calloc_target
                or strlen_target
                in (
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
            ):
                raise ValueError("nonnull distinct engine strlen target required")

        def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            arities = {
                0x142D6BA78: 1,
                0x1402A94D0: 1,
                0x142D6BAB4: 2,
                0x142D6E3DB: 3,
                0x142D6E3B7: 3,
                0x142D6E453: 1,
            }
            if calloc_target is not None:
                arities[calloc_target] = 2
            if strlen_target is not None:
                arities[strlen_target] = 1
            if target in arities:
                valid_arity = len(args) == arities[target] or (
                    target == 0x142D6BAB4 and len(args) == 1
                )
                if not valid_arity or data is not None:
                    raise ValueError("malformed replay memory runtime call")
                for value in args:
                    _u64(value, "runtime argument")
                if target == calloc_target:
                    return self.calloc(*args)
                if target == strlen_target:
                    return self.c_string_length(args[0])
                if target == 0x142D6BA78:
                    return self.allocate(args[0])
                if target == 0x1402A94D0:
                    return self.allocate_aligned(args[0])
                if target == 0x142D6BAB4:
                    self.free(args[0])
                    return None
                if target == 0x142D6E3DB:
                    return self.move(*args)
                if target == 0x142D6E3B7:
                    return self.fill(*args)
                try:
                    return _ceil_word(args[0])
                except UnresolvedReplayTaskRebuild:
                    pass
            if target in (0x1402A9460, 0x14113A7A0, 0x14114DD60, 0x142D66698):
                raise ReplayMemoryRuntimeError(target, args)
            if delegate is None or delegate.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return delegate.call(target, args, data)

        return ReplayTaskRebuildCalls(call)
