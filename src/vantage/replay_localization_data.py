"""Selected ASCII localization records and sparse owned first-catalog backing.

Sources: player-localization-static-source-v1, complete140964b80/14095f0b0
and selected-record paths in14095cae0/14095f180. Callers explicitly supply
raw asset bytes and keys. This projection proves no native locale/resource
selection, complete loader/parser behavior, manager identity or later layers.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass

from vantage.replay_localization_runtime import ReplayLocalizationRuntime
from vantage.replay_memory import ReplayMemory
from vantage.replay_task_rebuild import ReplayTaskRebuildStorage

_GLOBAL = 0x1442842E8
_MAX_KEY = b"2147483647"


def _canonical_key(key: bytes) -> bool:
    return (
        type(key) is bytes
        and bool(key)
        and key.isdigit()
        and (key == b"0" or key[:1] != b"0")
        and (len(key) < 10 or (len(key) == 10 and key <= _MAX_KEY))
    )


def _plain_text(text: bytes) -> bool:
    return type(text) is bytes and all(
        0x20 <= value <= 0x7E and value not in (0x22, 0x5C) for value in text
    )


@dataclass(frozen=True, slots=True)
class ReplayLocalizationEntry:
    """Canonical decimal CString key and unchanged admitted ASCII text bytes."""

    key: bytes
    text: bytes

    def __post_init__(self) -> None:
        if not _canonical_key(self.key):
            raise ValueError("canonical nonnegative signed32 decimal key bytes required")
        if not _plain_text(self.text):
            raise ValueError("quoted printable ASCII without quote/backslash required")


@dataclass(frozen=True, slots=True)
class ReplayLocalizationRecord:
    """One admitted selected occurrence, with absolute original byte offsets.

    line_number is one-based; record_offset/key_offset/text_offset are zero-based.
    record_end is exclusive and includes its CRLF/CR/LF when present. Key/text
    lengths come from entry and exclude delimiters and quotes. Every selected
    duplicate is retained, even when a later occurrence supplies the final text.
    """

    entry: ReplayLocalizationEntry
    line_number: int
    record_offset: int
    record_end: int
    key_offset: int
    text_offset: int

    def __post_init__(self) -> None:
        offsets = (self.record_offset, self.record_end, self.key_offset, self.text_offset)
        if (
            not isinstance(self.entry, ReplayLocalizationEntry)
            or type(self.line_number) is not int
            or self.line_number < 1
            or any(type(value) is not int or value < 0 for value in offsets)
        ):
            raise ValueError("explicit localization occurrence and original byte offsets required")
        if not (
            self.record_offset <= self.key_offset
            and self.key_offset + len(self.entry.key) + 2 <= self.text_offset
            and self.text_offset + len(self.entry.text) < self.record_end
        ):
            raise ValueError("localization key/text spans must fit their original record")


@dataclass(frozen=True, slots=True)
class ReplayLocalizationData:
    """Unique selected entries in caller key order and an explicit asset digest.

    records, when supplied, retain all source-ordered selected occurrences.
    Direct construction supplies explicit owned data; a digest alone is not
    proof of any native asset selection. The reader computes it from raw bytes.
    """

    entries: tuple[ReplayLocalizationEntry, ...]
    source_sha256: str
    records: tuple[ReplayLocalizationRecord, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.entries) is not tuple
            or not self.entries
            or any(not isinstance(entry, ReplayLocalizationEntry) for entry in self.entries)
        ):
            raise ValueError("nonempty ordered localization entries required")
        keys = tuple(entry.key for entry in self.entries)
        if len(set(keys)) != len(keys):
            raise ValueError("localization table entries require unique keys")
        if (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(value not in "0123456789abcdef" for value in self.source_sha256)
        ):
            raise ValueError("explicit lowercase localization source SHA256 required")
        if type(self.records) is not tuple or any(
            not isinstance(record, ReplayLocalizationRecord) for record in self.records
        ):
            raise ValueError("ordered selected localization occurrences required")
        if self.records:
            latest = {}
            end, line = 0, 0
            for record in self.records:
                if record.record_offset < end or record.line_number <= line:
                    raise ValueError("selected localization records must retain source order")
                latest[record.entry.key] = record.entry
                end, line = record.record_end, record.line_number
            if latest != {entry.key: entry for entry in self.entries}:
                raise ValueError("entries must equal the last selected occurrence of each key")


def _lines(raw: bytes) -> Iterator[tuple[int, int, bytes, int]]:
    """Split only native CR/LF boundaries, retaining absolute byte positions."""
    start, number = 0, 1
    while start < len(raw):
        end = start
        while end < len(raw) and raw[end] not in (0x0D, 0x0A):
            end += 1
        after = end
        if after < len(raw):
            after += 1
            if raw[end] == 0x0D and after < len(raw) and raw[after] == 0x0A:
                after += 1
        yield number, start, raw[start:end], after
        start, number = after, number + 1


def _key_byte(value: int) -> bool:
    return 0x30 <= value <= 0x39 or 0x41 <= value <= 0x5A or 0x61 <= value <= 0x7A or value == 0x5F


def read_replay_localization_ascii_subset(
    raw: bytes,
    *,
    keys: tuple[int, ...],
) -> ReplayLocalizationData:
    """Admit complete selected plain records; do not validate unselected records.

    Selected keys are explicit unique int32 nonnegative values. An exact native
    alnum/underscore key token identifies a selected record; malformed selected
    separators/quotes/text/trailing data refuse even if a valid duplicate exists.
    Keys use canonical decimal spelling. Values retain spaces and punctuation,
    with no quote/backslash/control/Unicode decoding or escape interpretation.
    Last selected duplicate wins, while every occurrence retains raw offsets.
    EOF is an admitted record boundary for this data projection; full native
    stream initialization, EOF diagnostics and all loader effects are excluded.
    """
    if (
        type(raw) is not bytes
        or type(keys) is not tuple
        or not keys
        or any(type(key) is not int or not 0 <= key <= 0x7FFFFFFF for key in keys)
    ):
        raise ValueError("explicit raw bytes and nonempty nonnegative signed32 keys required")
    if len(set(keys)) != len(keys):
        raise ValueError("selected localization keys must be unique")
    selected = tuple(str(key).encode("ascii") for key in keys)
    selected_set = set(selected)
    latest: dict[bytes, ReplayLocalizationEntry] = {}
    records = []
    for number, offset, line, after in _lines(raw):
        begin = len(line) - len(line.lstrip(b" \t"))
        end = begin
        while end < len(line) and _key_byte(line[end]):
            end += 1
        token = line[begin:end]
        if token not in selected_set:
            continue
        value = end
        while value < len(line) and line[value] in (0x20, 0x09):
            value += 1
        if value == end or value >= len(line) or line[value] != 0x22:
            raise ValueError(f"unadmitted selected localization record at byte {offset}")
        text_begin = value + 1
        close = line.find(b'"', text_begin)
        if close < 0 or line[close + 1 :].strip(b" \t"):
            raise ValueError(f"unadmitted selected localization record at byte {offset}")
        text = line[text_begin:close]
        if not _plain_text(text):
            raise ValueError(f"unadmitted selected localization record at byte {offset}")
        entry = ReplayLocalizationEntry(token, text)
        latest[token] = entry
        records.append(
            ReplayLocalizationRecord(
                entry,
                number,
                offset,
                after,
                offset + begin,
                offset + text_begin,
            )
        )
    if any(key not in latest for key in selected):
        raise ValueError("every selected localization key requires an admitted record")
    return ReplayLocalizationData(
        tuple(latest[key] for key in selected),
        hashlib.sha256(raw).hexdigest(),
        tuple(records),
    )


def _hash_key(key: bytes) -> int:
    """Original14095f0b0 wraps DWORD hash*33 XOR sign-extended BYTE."""
    value = 0x1505
    for byte in key:
        signed = byte if byte < 0x80 else byte - 0x100
        value = ((value * 33) ^ signed) & 0xFFFFFFFF
    return value


def create_replay_localization_context(
    memory: ReplayMemory,
    data: ReplayLocalizationData,
    *,
    runtime: ReplayLocalizationRuntime,
    bucket_count: int,
) -> ReplayTaskRebuildStorage:
    """Create a fresh explicit first layer; all unread fields remain undefined.

    table+8 sentinel, +18 bucket pointer and +30 mask match14095f0b0. Each
    bucket+8 selects its last node and bucket+0 its first boundary; node+8
    follows the preceding node within that bucket, ending at the sentinel.
    Nodes and all key/text Cstrings have separate fresh owned allocations.

    Only manager70/78, its16-byte row's first QWORD, mutexB8+4C and active239
    are defined. Register the explicitly zeroed mutex, then publish the fresh
    fixed global. Later catalog layers, virtual lists, aliases, static empty
    buffers, IATs and other manager/table/node bytes are not fabricated.
    A reached lookup miss therefore requires real missing backing/providers.
    This is owned data initialization, not the native manager/table constructor
    or insertion binder. Earlier allocations/writes survive a later failure.
    """
    if (
        not isinstance(memory, ReplayMemory)
        or not isinstance(data, ReplayLocalizationData)
        or not isinstance(runtime, ReplayLocalizationRuntime)
        or runtime.memory is not memory
        or type(bucket_count) is not int
        or bucket_count <= 0
        or bucket_count & (bucket_count - 1)
        or bucket_count > ((1 << 64) - 1) // 16
    ):
        raise ValueError(
            "same owned memory/runtime, localization data and power-of-two buckets required",
        )
    manager = memory.allocate(0x240)
    table = memory.allocate(0x38)
    sentinel = memory.allocate(0x20)
    buckets = memory.allocate(bucket_count * 16)
    row = memory.allocate(16)
    grouped: list[list[int]] = [[] for _ in range(bucket_count)]
    for entry in data.entries:
        node = memory.allocate(0x20)
        key = memory.allocate(len(entry.key) + 1)
        text = memory.allocate(len(entry.text) + 1)
        memory.write_bytes(key, entry.key + b"\0")
        memory.write_bytes(text, entry.text + b"\0")
        chain = grouped[_hash_key(entry.key) & (bucket_count - 1)]
        memory.write(node + 8, 8, chain[-1] if chain else sentinel)
        memory.write(node + 0x10, 8, key)
        memory.write(node + 0x18, 8, text)
        chain.append(node)
    for index, chain in enumerate(grouped):
        memory.write(buckets + index * 16, 8, chain[0] if chain else sentinel)
        memory.write(buckets + index * 16 + 8, 8, chain[-1] if chain else sentinel)
    memory.write(table + 8, 8, sentinel)
    memory.write(table + 0x18, 8, buckets)
    memory.write(table + 0x30, 8, bucket_count - 1)
    memory.write(row, 8, table)
    memory.write(manager + 0x70, 8, row)
    memory.write(manager + 0x78, 8, row + 16)
    memory.write(manager + 0xB8 + 0x4C, 4, 0)
    memory.write(manager + 0x239, 1, 1)
    runtime.register_mutex(manager + 0xB8)
    memory.map_bytes(_GLOBAL, manager.to_bytes(8, "little"))
    return ReplayTaskRebuildStorage(manager, memory.read, memory.write)
