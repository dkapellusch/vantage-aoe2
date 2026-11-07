"""Structural native XS runtime restoration for the verified DE save68.9 profile.

Native stream readers expose separate internal XS component versions. They are
preserved and checked independently of the outer game's save-version word.
No bytecode, source or serialized value is executed by these readers.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader


class UnsupportedSavedXS(SaveDecodeError):
    """An XS saved component whose complete wire variant is not verified."""


@dataclass(frozen=True, slots=True)
class SavedXSVariable:
    offset: int
    end_offset: int
    symbol_id: int
    type_bits: int
    modifiers: int
    data: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSSyscall:
    offset: int
    end_offset: int
    fields: dict[int, int]
    parameters: tuple[SavedXSVariable, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSSymbol:
    offset: int
    end_offset: int
    name_bytes: bytes
    type_tag: int
    value_bits: int
    symbol_id: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSSymbolTable:
    offset: int
    end_offset: int
    hash_size: int
    number_symbols: int
    case_sensitive: int
    invalid_value_bits: int
    invalid_type: int
    buckets: tuple[tuple[SavedXSSymbol, ...], ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSSyscalls:
    offset: int
    end_offset: int
    version: int
    static_words: tuple[int, ...]
    entries: tuple[SavedXSSyscall, ...]
    symbols: SavedXSSymbolTable
    flags: tuple[int, int, int]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSFile:
    offset: int
    end_offset: int
    file_id: int
    filename_bytes: bytes
    source_bytes: bytes
    source_line_offsets: tuple[int, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSSource:
    offset: int
    end_offset: int
    version: int
    files: tuple[SavedXSFile, ...]
    symbols: SavedXSSymbolTable
    code: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSRuleModule:
    version: int
    entry_version: int
    group_entry_version: int
    counts: tuple[int, int, int]
    next_sorted_rule_index_bits: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSFunction:
    offset: int
    end_offset: int
    fields: dict[int, int]
    variables: tuple[SavedXSVariable, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSHeapValue:
    offset: int
    end_offset: int
    type_bits: int
    allocation_size: int
    reference_count: int
    data: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXSData:
    offset: int
    end_offset: int
    version: int
    rules: SavedXSRuleModule
    name_bytes: bytes
    functions: tuple[SavedXSFunction, ...]
    variables: tuple[SavedXSVariable, ...]
    exported_variables: tuple[int, ...]
    stack_words: tuple[int, ...]
    heap: bytes
    fields: dict[int, int]
    empty_counts: dict[str, int]
    has_output: int
    array_counts: tuple[int, ...]
    user_heap: tuple[SavedXSHeapValue, ...]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedXS:
    offset: int
    end_offset: int
    version: int
    player_id: int
    name_bytes: bytes
    syscalls: SavedXSSyscalls
    source: SavedXSSource
    data_flags: bytes
    data_slots: tuple[SavedXSData | None, ...]
    fields: dict[int, int]
    sections: dict[str, bytes]
    raw: bytes


def _empty_count(reader: SaveReader, what: str) -> int:
    at = reader.pos
    count = reader.i32()
    if count != 0:
        raise UnsupportedSavedXS(f"unsupported nonempty XS {what} count {count}", at)
    return count


def _rules(reader: SaveReader) -> SavedXSRuleModule:
    # Native 0x1417fb770 always reads the two four-byte static reader
    # versions through 0x1417f6510/0x1417f6860, including module version0.
    start = reader.pos
    version, entry_version, group_version = reader.u32(), reader.u32(), reader.u32()
    if (version, entry_version, group_version) != (0, 1, 0):
        raise UnsupportedSavedXS("unsupported XS rule-module versions", start)
    counts = (
        _empty_count(reader, "rules"),
        _empty_count(reader, "sorted rules"),
        _empty_count(reader, "rule groups"),
    )
    next_index = reader.u32()
    return SavedXSRuleModule(
        version, entry_version, group_version, counts, next_index, reader.data[start : reader.pos]
    )


def _function(reader: SaveReader) -> SavedXSFunction:
    # Native 0x1417e6260, static function-entry version2.
    start = reader.pos
    fields = {offset: reader.u32() for offset in (0, 4, 8, 0xC)}
    fields[0x29], fields[0x10], fields[0x2A] = reader.u8(), reader.u32(), reader.u8()
    variables = tuple(_variable(reader) for _ in range(reader.count(item_size=13)))
    fields[0x28] = reader.u8()
    return SavedXSFunction(start, reader.pos, fields, variables, reader.data[start : reader.pos])


def _heap_value(reader: SaveReader) -> SavedXSHeapValue:
    # Native 0x1417bc090, xsdata.cpp lines0xa8f..0xa99. Allocation size is
    # metadata, not a byte count: the separately saved length controls reading.
    start = reader.pos
    kind, size = reader.u32(), reader.u32()
    length = reader.count(item_size=1)
    references = reader.u32()
    data = reader.take(length)
    return SavedXSHeapValue(
        start, reader.pos, kind, size, references, data, reader.data[start : reader.pos]
    )


def _data(reader: SaveReader) -> SavedXSData:
    # Native 0x1417bc090. Only the complete, paired version4 profile below
    # is accepted; optional factories stop explicitly rather than losing bytes.
    start = reader.pos
    sections: dict[str, bytes] = {}

    def section(name: str, at: int) -> None:
        sections[name] = reader.data[at : reader.pos]

    version = reader.u32()
    if version != 4:
        raise UnsupportedSavedXS(f"unsupported XS data version {version}", start)
    section("version", start)
    at = reader.pos
    rules = _rules(reader)
    section("rules", at)
    at = reader.pos
    fields = {0x40: reader.u32()}
    name = reader.de_bytes()  # Native 0x140fb9f60 delegates to the DE string reader.
    section("identity", at)
    at = reader.pos
    functions = tuple(_function(reader) for _ in range(reader.count(item_size=27)))
    section("functions", at)
    at = reader.pos
    variables = tuple(_variable(reader) for _ in range(reader.count(item_size=13)))
    section("variables", at)
    at = reader.pos
    exported = tuple(reader.u32() for _ in range(reader.count(item_size=4)))
    section("exported_variables", at)
    at = reader.pos
    empty_counts = {
        "user_classes": _empty_count(reader, "user classes"),
        "events": _empty_count(reader, "events"),
    }
    section("empty_factories", at)
    at = reader.pos
    stack = tuple(reader.u32() for _ in range(reader.count(item_size=4)))
    section("stack", at)
    at = reader.pos
    heap = reader.take(reader.count(item_size=1))
    section("heap", at)
    at = reader.pos
    fields.update({offset: reader.u32() for offset in (0x138, 0x13C)})
    empty_counts["call_stack"] = _empty_count(reader, "call stack")
    fields.update({offset: reader.u32() for offset in (0x150, 0x154, 0x158, 0x15C, 0x160)})
    empty_counts["breakpoints"] = _empty_count(reader, "breakpoints")
    fields[0x178], fields[0x3DA], fields[0x37C], fields[0x3D8] = (
        reader.u32(),
        reader.u8(),
        reader.u32(),
        reader.u8(),
    )
    output_at = reader.pos
    has_output = reader.u8()
    if has_output:
        raise UnsupportedSavedXS("unsupported XS output log", output_at)
    section("interpreter", at)
    at = reader.pos
    # Save-data version>1 carries these six containers in native member
    # order. Their nonempty element grammars require further native coverage.
    arrays = tuple(
        _empty_count(reader, f"array container+{offset:#x}")
        for offset in (0xB8, 0xC8, 0xD8, 0xE8, 0xF8, 0x108)
    )
    section("array_containers", at)
    at = reader.pos
    # Version>3 adds the user heap; version>=3 adds mUnitID afterward.
    user_heap = tuple(_heap_value(reader) for _ in range(reader.count(item_size=16)))
    section("user_heap", at)
    at = reader.pos
    fields[0x3A0] = reader.u32()
    section("unit_id", at)
    return SavedXSData(
        start,
        reader.pos,
        version,
        rules,
        name,
        functions,
        variables,
        exported,
        stack,
        heap,
        fields,
        empty_counts,
        has_output,
        arrays,
        user_heap,
        sections,
        reader.data[start : reader.pos],
    )


def read_xs(reader: SaveReader) -> SavedXS:
    """Read one complete XS runtime from its version; restore cursor on error.

    The verified outer save68.9 profile uses runtime3, syscall module2 and the
    explicitly checked child versions. Present data slots use data version4.
    Nonempty rules, classes, events, call stacks, breakpoints, output logs and
    typed array containers remain explicit unsupported variants. Their bytes
    are never guessed from a following marker or a known sample's length.
    """
    start = reader.pos
    try:
        if reader.version != 0x44E666:
            raise UnsupportedSavedXS(f"unsupported XS save version {reader.version:#x}", start)
        sections: dict[str, bytes] = {}
        version = reader.u32()
        if version != 3:
            raise UnsupportedSavedXS(f"unsupported XS runtime version {version}", start)
        player_id, name = reader.i32(), reader.de_bytes()
        sections["header"] = reader.data[start : reader.pos]
        syscalls = _syscalls(reader)
        sections["syscalls"] = syscalls.raw
        source = _source(reader)
        sections["source"] = source.raw
        at = reader.pos
        flags = bytearray()
        slots = []
        for _ in range(reader.count(item_size=1, signed=False)):
            present = reader.u8()
            flags.append(present)
            # The native loader tests equality to1, not general truthiness.
            slots.append(_data(reader) if present == 1 else None)
        sections["data_slots"] = reader.data[at : reader.pos]
        at = reader.pos
        fields = {0x70: reader.u32()}
        fields.update({offset: reader.u8() for offset in range(0x74, 0x7D)})
        sections["configuration"] = reader.data[at : reader.pos]
        return SavedXS(
            start,
            reader.pos,
            version,
            player_id,
            name,
            syscalls,
            source,
            bytes(flags),
            tuple(slots),
            fields,
            sections,
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def _string(reader: SaveReader) -> bytes:
    # Native 0x141825640/0x1417d7060 pass N+1 to Serialize<char> only if
    # N>0. The additional byte is on the wire, unlike Build AI's strings.
    length = reader.count(item_size=1)
    return reader.take(length + 1) if length else b""


def _variable(reader: SaveReader) -> SavedXSVariable:
    # Native 0x14183d560; string/array types 0x10/0x40 add four bytes only
    # to the runtime allocation. Both branches read exactly dataLength bytes.
    start = reader.pos
    symbol, kind, modifiers = reader.i32(), reader.u32(), reader.u8()
    data = reader.take(reader.count(item_size=1))
    return SavedXSVariable(
        start, reader.pos, symbol, kind, modifiers, data, reader.data[start : reader.pos]
    )


def _syscall(reader: SaveReader) -> SavedXSSyscall:
    # Native 0x14182c4f0, current static syscall-entry version2.
    start = reader.pos
    fields = {0: reader.u32(), 4: reader.u32(), 0x28: reader.u8(), 0x29: reader.u8()}
    fields[0x2C] = reader.u32()
    parameters = tuple(_variable(reader) for _ in range(reader.count(item_size=13)))
    return SavedXSSyscall(start, reader.pos, fields, parameters, reader.data[start : reader.pos])


def _symbols(reader: SaveReader) -> SavedXSSymbolTable:
    # Native 0x141826310/0x141825640, static versions1/1. numberSymbols
    # is an ID-slot bound; the native reader permits holes in those slots.
    start = reader.pos
    hash_size = reader.count(item_size=4)
    at = reader.pos
    number = reader.i32()
    if number < 0:
        raise SaveDecodeError(f"invalid XS symbol-slot count {number}", at)
    case, invalid, invalid_type = reader.u8(), reader.u32(), reader.u8()
    seen: set[int] = set()
    buckets = []
    for _ in range(hash_size):
        entries = []
        for _ in range(reader.count(item_size=13)):
            entry_start = reader.pos
            name = _string(reader)
            kind, value, symbol = reader.u8(), reader.u32(), reader.i32()
            if not 0 <= symbol < number or symbol in seen:
                raise SaveDecodeError(f"invalid or duplicate XS symbol ID {symbol}", reader.pos - 4)
            seen.add(symbol)
            entries.append(
                SavedXSSymbol(
                    entry_start,
                    reader.pos,
                    name,
                    kind,
                    value,
                    symbol,
                    reader.data[entry_start : reader.pos],
                )
            )
        buckets.append(tuple(entries))
    return SavedXSSymbolTable(
        start,
        reader.pos,
        hash_size,
        number,
        case,
        invalid,
        invalid_type,
        tuple(buckets),
        reader.data[start : reader.pos],
    )


def _syscalls(reader: SaveReader) -> SavedXSSyscalls:
    start = reader.pos
    version = reader.u32()
    if version != 2:
        raise UnsupportedSavedXS(f"unsupported XS syscall-module version {version}", start)
    # Nine native fixed scalar readers, in call order. The values control
    # child variants; retain them per record rather than mutating globals.
    words = tuple(reader.u32() for _ in range(9))
    if words != (0, 0, 0, 2, 0, 2, 1, 1, 2):
        raise UnsupportedSavedXS(f"unsupported XS static component versions {words}", start + 4)
    entries = tuple(_syscall(reader) for _ in range(reader.count(item_size=18)))
    symbols = _symbols(reader)
    flags = (reader.u8(), reader.u8(), reader.u8())
    return SavedXSSyscalls(
        start, reader.pos, version, words, entries, symbols, flags, reader.data[start : reader.pos]
    )


def _file(reader: SaveReader) -> SavedXSFile:
    # Native 0x1417d7060: ID, two counted N+1 byte strings, then i32 line
    # count and that many four-byte source offsets via Serialize<int32_t>.
    start = reader.pos
    file_id = reader.u32()
    name, source = _string(reader), _string(reader)
    lines = tuple(reader.u32() for _ in range(reader.count(item_size=4)))
    return SavedXSFile(
        start, reader.pos, file_id, name, source, lines, reader.data[start : reader.pos]
    )


def _source(reader: SaveReader) -> SavedXSSource:
    # Native 0x14181f3c0; the current reader does not branch on its saved
    # source version. Preserve it without applying that word to child formats.
    start = reader.pos
    version = reader.u32()
    files = tuple(_file(reader) for _ in range(reader.count(item_size=16)))
    symbols = _symbols(reader)
    code = reader.take(reader.count(item_size=1))
    return SavedXSSource(
        start, reader.pos, version, files, symbols, code, reader.data[start : reader.pos]
    )
