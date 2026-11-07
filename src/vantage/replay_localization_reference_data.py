"""Explicit ASCII reference JSON and sparse owned numeric-alias backing.

Source: player-localization-startup-static-v1, especially1408f2f00,
140965d62..5d91,140962270 and1409626e0. This finite data projection does
not select an asset, activate localization, create catalogs or simulate native
startup/JSON parsing. Actual insertion/string cleanup remain caller services.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .replay_localization_runtime import ReplayLocalizationRuntime
from .replay_memory import ReplayMemory
from .replay_task_rebuild import ReplayTaskRebuildCalls, ReplayTaskRebuildStorage, _call

_INSERT_VALUE, _DESTROY_STRING = 0x140962270, 0x1402A88A0
_WHITESPACE = b" \t\r\n"
_U32 = (1 << 32) - 1


def _plain_key(key: bytes) -> bool:
    return (
        type(key) is bytes
        and bool(key)
        and all(0x20 <= byte <= 0x7E and byte not in (0x22, 0x5C) for byte in key)
    )


@dataclass(frozen=True, slots=True)
class ReplayLocalizationReferenceEntry:
    """An unescaped printable ASCII symbolic key and exact signed32 value."""

    key: bytes
    value: int

    def __post_init__(self) -> None:
        if not _plain_key(self.key):
            raise ValueError("nonempty plain printable ASCII reference key bytes required")
        if type(self.value) is not int or not -(1 << 31) <= self.value < 1 << 31:
            raise ValueError("exact signed32 reference integer required")


@dataclass(frozen=True, slots=True)
class ReplayLocalizationReferenceRecord:
    """An admitted source occurrence; byte offsets exclude trailing whitespace.

    record_offset points at the opening key quote, key_offset at its contents,
    value_offset at the optional minus/digits, and record_end immediately after
    the integer. All offsets are zero-based; record_end is exclusive. Records
    retain every duplicate occurrence even though the last value wins.
    """

    entry: ReplayLocalizationReferenceEntry
    record_offset: int
    key_offset: int
    value_offset: int
    record_end: int

    def __post_init__(self) -> None:
        offsets = (self.record_offset, self.key_offset, self.value_offset, self.record_end)
        if not isinstance(self.entry, ReplayLocalizationReferenceEntry) or any(
            type(value) is not int or value < 0 for value in offsets
        ):
            raise ValueError("explicit reference occurrence and nonnegative offsets required")
        if not (
            self.record_offset + 1 == self.key_offset
            and self.key_offset + len(self.entry.key) + 1 < self.value_offset < self.record_end
        ):
            raise ValueError("reference key/value spans must fit the original record")


@dataclass(frozen=True, slots=True)
class ReplayLocalizationReferenceData:
    """Unique byte-lexicographic entries and explicit source SHA256.

    Direct construction supplies caller-owned semantic data, not proof of asset
    selection or digest provenance. The reader computes its digest from raw
    bytes and retains all source-ordered occurrences. An explicitly empty root
    object is admitted; it never implies active or empty localization catalogs.
    """

    entries: tuple[ReplayLocalizationReferenceEntry, ...]
    source_sha256: str
    records: tuple[ReplayLocalizationReferenceRecord, ...] = ()

    def __post_init__(self) -> None:
        if type(self.entries) is not tuple or any(
            not isinstance(entry, ReplayLocalizationReferenceEntry) for entry in self.entries
        ):
            raise ValueError("explicit reference entry tuple required")
        keys = tuple(entry.key for entry in self.entries)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("reference entries must be unique and byte-lexicographically sorted")
        if (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(byte not in "0123456789abcdef" for byte in self.source_sha256)
        ):
            raise ValueError("explicit lowercase reference source SHA256 required")
        if type(self.records) is not tuple or any(
            not isinstance(record, ReplayLocalizationReferenceRecord) for record in self.records
        ):
            raise ValueError("explicit source-ordered reference records required")
        if self.records:
            latest: dict[bytes, ReplayLocalizationReferenceEntry] = {}
            previous_end = 0
            for record in self.records:
                if record.record_offset < previous_end:
                    raise ValueError("reference records must retain nonoverlapping source order")
                latest[record.entry.key] = record.entry
                previous_end = record.record_end
            if tuple(latest[key] for key in sorted(latest)) != self.entries:
                raise ValueError("reference entries must equal the last occurrence of every key")


@dataclass(slots=True)
class _Reader:
    raw: bytes
    position: int = 0

    def whitespace(self) -> None:
        while self.position < len(self.raw) and self.raw[self.position] in _WHITESPACE:
            self.position += 1

    def take(self, byte: int) -> bool:
        if self.position < len(self.raw) and self.raw[self.position] == byte:
            self.position += 1
            return True
        return False

    def require(self, byte: int) -> None:
        if not self.take(byte):
            raise ValueError(f"unadmitted reference JSON at byte {self.position}")

    def key(self) -> bytes:
        self.require(0x22)
        start = self.position
        while self.position < len(self.raw) and self.raw[self.position] != 0x22:
            byte = self.raw[self.position]
            if not 0x20 <= byte <= 0x7E or byte == 0x5C:
                raise ValueError(f"unadmitted reference key at byte {self.position}")
            self.position += 1
        key = self.raw[start : self.position]
        self.require(0x22)
        if not key:
            raise ValueError("empty reference JSON keys are outside the admitted data profile")
        return key

    def integer(self) -> int:
        negative = self.take(0x2D)
        start = self.position
        while self.position < len(self.raw) and 0x30 <= self.raw[self.position] <= 0x39:
            self.position += 1
        digits = self.raw[start : self.position]
        if not digits or len(digits) > 10 or (len(digits) > 1 and digits[0] == 0x30):
            raise ValueError(f"admitted JSON signed32 integer required at byte {start}")
        value = int(digits)
        value = -value if negative else value
        if not -(1 << 31) <= value < 1 << 31:
            raise ValueError(f"reference integer exceeds signed32 at byte {start}")
        return value


def read_replay_localization_references_ascii(raw: bytes) -> ReplayLocalizationReferenceData:
    """Read one complete finite JSON object; last duplicate wins.

    Only JSON SP/HT/CR/LF whitespace, nonempty unescaped printable ASCII keys
    and signed32 integer tokens are admitted. No BOM, comments, trailing comma,
    nested/array/float/bool/null value, escaped key or extra root is accepted.
    JSON -0 is accepted as integer0. Every input byte is validated. Native
    generic JSON grammar, invalid-input conversion, Unicode and recursive
    effects are deliberately outside this explicit data reader.
    """
    if type(raw) is not bytes:
        raise ValueError("explicit raw reference JSON bytes required")
    reader = _Reader(raw)
    records = []
    latest: dict[bytes, ReplayLocalizationReferenceEntry] = {}
    reader.whitespace()
    reader.require(0x7B)
    reader.whitespace()
    if not reader.take(0x7D):
        while True:
            record_offset = reader.position
            key = reader.key()
            reader.whitespace()
            reader.require(0x3A)
            reader.whitespace()
            value_offset = reader.position
            entry = ReplayLocalizationReferenceEntry(key, reader.integer())
            records.append(
                ReplayLocalizationReferenceRecord(
                    entry,
                    record_offset,
                    record_offset + 1,
                    value_offset,
                    reader.position,
                )
            )
            latest[key] = entry
            reader.whitespace()
            if reader.take(0x7D):
                break
            reader.require(0x2C)
            reader.whitespace()
    reader.whitespace()
    if reader.position != len(raw):
        raise ValueError(f"unadmitted bytes after reference JSON at byte {reader.position}")
    return ReplayLocalizationReferenceData(
        tuple(latest[key] for key in sorted(latest)),
        hashlib.sha256(raw).hexdigest(),
        tuple(records),
    )


def create_replay_localization_reference_context(
    memory: ReplayMemory,
    *,
    runtime: ReplayLocalizationRuntime,
) -> ReplayTaskRebuildStorage:
    """Define only a fresh alias map and registered mutex in a2d0 manager.

    Source1409626e0 establishes max load1, empty self-linked56B sentinel,
    eight16B buckets, mask7 and bucket count8. This sparse owned projection
    defines those consumed header fields plus mutex count2cc=0. All manager
    catalogs, active239, fixed global, vtable and other mutex/sentinel/padding
    bytes remain undefined. It is not the native constructor/startup or an
    active empty-catalog state. Runtime must own this exact memory before any
    allocation; earlier effects survive later allocation/register failures.
    """
    if (
        not isinstance(memory, ReplayMemory)
        or not isinstance(runtime, ReplayLocalizationRuntime)
        or runtime.memory is not memory
    ):
        raise ValueError("same owned memory and localization runtime required")
    manager = memory.allocate(0x2D0)
    sentinel = memory.allocate(0x38)
    buckets = memory.allocate(8 * 16)
    table = manager + 0x240
    memory.write(sentinel, 8, sentinel)
    memory.write(sentinel + 8, 8, sentinel)
    for index in range(8):
        memory.write(buckets + index * 16, 8, sentinel)
        memory.write(buckets + index * 16 + 8, 8, sentinel)
    memory.write(table, 4, 0x3F800000)
    memory.write(table + 8, 8, sentinel)
    memory.write(table + 0x10, 8, 0)
    memory.write(table + 0x18, 8, buckets)
    memory.write(table + 0x20, 8, buckets + 128)
    memory.write(table + 0x28, 8, buckets + 128)
    memory.write(table + 0x30, 8, 7)
    memory.write(table + 0x38, 8, 8)
    memory.write(manager + 0x2CC, 4, 0)
    runtime.register_mutex(manager + 0x280)
    return ReplayTaskRebuildStorage(manager, memory.read, memory.write)


def populate_replay_localization_references(
    memory: ReplayMemory,
    context: ReplayTaskRebuildStorage,
    data: ReplayLocalizationReferenceData,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Call actual value insertion and actual string cleanup for sorted data.

    Context must bind the same memory's direct read/write methods. Each entry
    gets coherent36B key-string+DWORD and16B output borrowed logical locals,
    explicitly zero-seeded owned caller temporaries (not a native frame).
    Heap keys use aligned length+1 backing with capacity=length; SSO capacity
    is15. Value insertion140962270 moves the key or retains it on an existing
    hit;1402a88a0 then owns cleanup. Both child RAX values are ignored.

    No insertion/free/helper success, locking, rollback or exception cleanup
    is supplied here. On a reached missing child or failure, preceding map,
    node and heap effects remain; borrowed local mappings expire. Source
    startup's final temporary-map copy, lock sequence and native EH/stack
    effects are outside this explicit serialized data-population operation.
    """
    if (
        not isinstance(memory, ReplayMemory)
        or not isinstance(context, ReplayTaskRebuildStorage)
        or not isinstance(data, ReplayLocalizationReferenceData)
        or not isinstance(calls, ReplayTaskRebuildCalls)
        or getattr(context.read, "__self__", None) is not memory
        or getattr(context.read, "__func__", None) is not ReplayMemory.read
        or getattr(context.write, "__self__", None) is not memory
        or getattr(context.write, "__func__", None) is not ReplayMemory.write
    ):
        raise ValueError("reference data, calls and direct context methods on same memory required")
    for entry in data.entries:
        with (
            memory.bind_local(memoryview(bytearray(36))) as source,
            memory.bind_local(memoryview(bytearray(16))) as output,
        ):
            length = len(entry.key)
            if length > 15:
                pointer = memory.allocate_aligned(length + 1)
                memory.write_bytes(pointer, entry.key + b"\0")
                memory.write(source, 8, pointer)
                capacity = length
            else:
                memory.write_bytes(source, entry.key + b"\0")
                capacity = 15
            memory.write(source + 0x10, 8, length)
            memory.write(source + 0x18, 8, capacity)
            memory.write(source + 0x20, 4, entry.value & _U32)
            _call(calls, _INSERT_VALUE, (context.subject + 0x240, output, source))
            _call(calls, _DESTROY_STRING, (source,))
