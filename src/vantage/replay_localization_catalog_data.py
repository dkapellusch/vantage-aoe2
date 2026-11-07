"""Complete supplied catalog records and persistent owned leaf lookup backing.

Data grammar: complete14095cae0/14095f180 and14095da40, documented in
player-localization-catalog-grammar-static-v1. Stored text remains bytes after
the five source escapes; character conversion only diagnoses it. This is no
native file/stream/parser binder: diagnostics, allocation/unwind effects and
resource/language selection are separate from the admitted data projection.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass

from .replay_localization_data import _hash_key
from .replay_memory import ReplayMemory


def _key(key: bytes) -> bool:
    return (
        type(key) is bytes
        and bool(key)
        and all(
            0x30 <= byte <= 0x39 or 0x41 <= byte <= 0x5A or 0x61 <= byte <= 0x7A or byte == 0x5F
            for byte in key
        )
    )


class ReplayLocalizationCatalogError(ValueError):
    """A complete supplied record fails the source's strict data grammar."""

    def __init__(self, code: str, offset: int, line_number: int) -> None:
        self.code, self.offset, self.line_number = code, offset, line_number
        super().__init__(f"{code} at byte {offset}, line {line_number}")


@dataclass(frozen=True, slots=True)
class ReplayCatalogEntry:
    """Exact key CString bytes and escape-decoded value CString bytes."""

    key: bytes
    text: bytes

    def __post_init__(self) -> None:
        if not _key(self.key):
            raise ValueError("nonempty ASCII alphanumeric/underscore catalog key required")
        if type(self.text) is not bytes or b"\0" in self.text:
            raise ValueError("explicit catalog text bytes without CString NUL required")


@dataclass(frozen=True, slots=True)
class ReplayCatalogRecord:
    """Every key occurrence, including overwritten values, in original bytes.

    Line numbers start at one; offsets are absolute zero-based byte positions,
    including a skipped initial UTF8 BOM. value_end names the closing quote;
    record_end includes a supplied CR/LF/NUL boundary and excludes the synthetic
    EOF NUL. comment_offset, when present, names the first slash of trailing //.
    Escape decoding means text length need not equal its raw source span.
    """

    entry: ReplayCatalogEntry
    line_number: int
    record_offset: int
    record_end: int
    key_offset: int
    value_offset: int
    value_end: int
    comment_offset: int | None = None

    def __post_init__(self) -> None:
        positions = (
            self.record_offset,
            self.record_end,
            self.key_offset,
            self.value_offset,
            self.value_end,
        )
        if (
            not isinstance(self.entry, ReplayCatalogEntry)
            or type(self.line_number) is not int
            or self.line_number < 1
            or any(type(value) is not int or value < 0 for value in positions)
        ):
            raise ValueError("explicit catalog record and original offsets required")
        if not (
            self.record_offset <= self.key_offset
            and self.key_offset + len(self.entry.key) + 2 <= self.value_offset
            and self.value_offset + len(self.entry.text) <= self.value_end < self.record_end
        ):
            raise ValueError("catalog key/value spans must fit the original record")
        if self.comment_offset is not None and (
            type(self.comment_offset) is not int
            or not self.value_end < self.comment_offset < self.record_end - 1
        ):
            raise ValueError("catalog comment must follow the closing quote")


@dataclass(frozen=True, slots=True)
class ReplayCatalogData:
    """All keys, retaining first-insertion order and last duplicate value.

    Empty supplied catalogs are meaningful data. They do not establish an empty
    native layer or an active manager. Direct construction supplies explicit
    owned entries; only the reader computes provenance from complete raw bytes.
    """

    entries: tuple[ReplayCatalogEntry, ...]
    source_sha256: str
    records: tuple[ReplayCatalogRecord, ...] = ()

    def __post_init__(self) -> None:
        if type(self.entries) is not tuple or any(
            not isinstance(entry, ReplayCatalogEntry) for entry in self.entries
        ):
            raise ValueError("ordered explicit catalog entries required")
        if len({entry.key for entry in self.entries}) != len(self.entries):
            raise ValueError("catalog entries require unique keys")
        if (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(byte not in "0123456789abcdef" for byte in self.source_sha256)
        ):
            raise ValueError("explicit lowercase catalog source SHA256 required")
        if type(self.records) is not tuple or any(
            not isinstance(record, ReplayCatalogRecord) for record in self.records
        ):
            raise ValueError("ordered catalog occurrence records required")
        if self.records:
            latest: dict[bytes, ReplayCatalogEntry] = {}
            end, line = 0, 0
            for record in self.records:
                if record.record_offset < end or record.line_number <= line:
                    raise ValueError("catalog records must retain original source order")
                latest[record.entry.key] = record.entry
                end, line = record.record_end, record.line_number
            if tuple(latest.values()) != self.entries:
                raise ValueError("catalog entries must retain first order and last values")


def _lines(raw: bytes) -> Iterator[tuple[int, int, int, int]]:
    """Mirror CR/LF/NUL line boundaries, including the appended EOF NUL."""
    start = 3 if raw.startswith(b"\xef\xbb\xbf") else 0
    number = 1
    while start <= len(raw):
        end = start
        while end < len(raw) and raw[end] not in (0, 0x0D, 0x0A):
            end += 1
        after = end + 1
        if end < len(raw) and raw[end] == 0x0D and raw[end + 1 : end + 2] == b"\n":
            after += 1
        yield number, start, end, min(after, len(raw))
        start, number = after, number + 1


def read_replay_localization_catalog(raw: bytes) -> ReplayCatalogData:
    """Read every record, with the loader's BOM skip and strict quote rule.

    Only SP/HT are separators. Blank lines and // comments have no entry. Keys
    use the source's full alphanumeric/underscore domain; exact key bytes keep
    distinct spellings such as 7 and 07. Values preserve bytes and decode only
    backslash n/t/backslash/apostrophe/quote. Trailing data must be SP/HT or //.
    Unknown escapes and malformed records refuse with their original position.

    CRLF counts as one boundary; lone CR/LF and embedded NUL also end a line.
    The opener's appended NUL admits a closed record at EOF. Source EOF and
    character warnings do not change stored values; their callbacks/formatting,
    malformed-byte conversion reads and partial native loader effects are not
    modeled by this data reader. No UTF8 replacement or normalization occurs.
    """
    if type(raw) is not bytes:
        raise ValueError("complete immutable catalog bytes required")
    latest: dict[bytes, ReplayCatalogEntry] = {}
    records = []
    escapes = {0x6E: 0x0A, 0x74: 0x09, 0x5C: 0x5C, 0x27: 0x27, 0x22: 0x22}
    for number, start, end, after in _lines(raw):
        begin, limit = start, end
        while begin < limit and raw[begin] in (0x20, 0x09):
            begin += 1
        while limit > begin and raw[limit - 1] in (0x20, 0x09):
            limit -= 1
        if begin == limit or raw[begin : begin + 2] == b"//":
            continue
        cursor = begin
        while cursor < limit and raw[cursor] not in (0x20, 0x09):
            byte = raw[cursor]
            if not (
                0x30 <= byte <= 0x39 or 0x41 <= byte <= 0x5A or 0x61 <= byte <= 0x7A or byte == 0x5F
            ):
                raise ReplayLocalizationCatalogError("invalid_key", cursor, number)
            cursor += 1
        key = raw[begin:cursor]
        while cursor < limit and raw[cursor] in (0x20, 0x09):
            cursor += 1
        if cursor == limit or raw[cursor] != 0x22:
            raise ReplayLocalizationCatalogError("missing_open_quote", cursor, number)
        cursor += 1
        value_offset = cursor
        text = bytearray()
        while cursor < limit and raw[cursor] != 0x22:
            byte = raw[cursor]
            if byte == 0x5C:
                cursor += 1
                if cursor == limit or raw[cursor] not in escapes:
                    raise ReplayLocalizationCatalogError("unknown_escape", cursor, number)
                byte = escapes[raw[cursor]]
            text.append(byte)
            cursor += 1
        if cursor == limit:
            raise ReplayLocalizationCatalogError("missing_close_quote", cursor, number)
        value_end = cursor
        cursor += 1
        while cursor < limit and raw[cursor] in (0x20, 0x09):
            cursor += 1
        comment = None
        if cursor != limit:
            if raw[cursor : cursor + 2] != b"//":
                raise ReplayLocalizationCatalogError("trailing_data", cursor, number)
            comment = cursor
        entry = ReplayCatalogEntry(key, bytes(text))
        latest[key] = entry
        records.append(
            ReplayCatalogRecord(
                entry,
                number,
                start,
                after,
                begin,
                value_offset,
                value_end,
                comment,
            )
        )
    return ReplayCatalogData(
        tuple(latest.values()),
        hashlib.sha256(raw).hexdigest(),
        tuple(records),
    )


def create_replay_localization_catalog_table(
    memory: ReplayMemory,
    data: ReplayCatalogData,
    *,
    bucket_count: int,
) -> int:
    """Back all supplied entries for actual14095f0b0's leaf lookup.

    This persistent owned table defines only the leaf's consumed fields. Key
    and value Cstrings have separate allocations, even for equal/empty values.
    Bucket boundaries and preceding-node links preserve first insertion order.
    Other headers, forward list, native constructors/insertion/growth and frees
    remain unprovided; this is not a mutable native container implementation.
    No manager, layer, mutex, active flag, global, IAT or locale is supplied.
    Earlier allocations/writes survive a later owned storage failure.
    """
    if (
        not isinstance(memory, ReplayMemory)
        or not isinstance(data, ReplayCatalogData)
        or type(bucket_count) is not int
        or bucket_count <= 0
        or bucket_count & (bucket_count - 1)
        or bucket_count > ((1 << 64) - 1) // 16
    ):
        raise ValueError("owned memory, catalog data and positive power-of-two buckets required")
    table, sentinel = memory.allocate(0x38), memory.allocate(0x20)
    buckets = memory.allocate(bucket_count * 16)
    first = [sentinel] * bucket_count
    last = [sentinel] * bucket_count
    for entry in data.entries:
        node = memory.allocate(0x20)
        key, text = memory.allocate(len(entry.key) + 1), memory.allocate(len(entry.text) + 1)
        memory.write_bytes(key, entry.key + b"\0")
        memory.write_bytes(text, entry.text + b"\0")
        bucket = _hash_key(entry.key) & (bucket_count - 1)
        memory.write(node + 8, 8, last[bucket])
        memory.write(node + 0x10, 8, key)
        memory.write(node + 0x18, 8, text)
        if first[bucket] == sentinel:
            first[bucket] = node
        last[bucket] = node
    for index, (begin, end) in enumerate(zip(first, last, strict=True)):
        memory.write(buckets + 16 * index, 8, begin)
        memory.write(buckets + 16 * index + 8, 8, end)
    memory.write(table + 8, 8, sentinel)
    memory.write(table + 0x18, 8, buckets)
    memory.write(table + 0x30, 8, bucket_count - 1)
    return table
