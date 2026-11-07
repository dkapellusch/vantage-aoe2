"""Native saved outer World rule systems for save68.9.

World reader0x14169bd10 loads ExpertEngine0x140bddcb0 and global rules0x140bf4d30
before BaseWorld's prefix. These readers preserve stored state and raw bytes;
they do not execute rule planners or apply native load-time pointer fixups.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader

_MAX_NATIVE_PAYLOAD = 0xA00000


@dataclass(frozen=True, slots=True)
class SavedExpertRule:
    """Descriptor byte13 counts elements; debug bytes include the terminator slot."""

    descriptor: bytes
    elements: tuple[bytes, ...]
    debug_string: bytes | None
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedExpertRuleList:
    header: tuple[int, int, int, int, int]
    rules: tuple[SavedExpertRule, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedExpertLinks:
    capacity: int
    count: int
    discarded_word: int
    values: tuple[int, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedExpertEngine:
    offset: int
    end_offset: int
    string_capacity: int
    discarded_word: int
    strings: tuple[bytes, ...]
    member28_capacity: int
    member40_capacity: int
    script_debugging: int
    lists: tuple[SavedExpertRuleList, ...]
    links: tuple[SavedExpertLinks, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedGlobalRuleEngine:
    offset: int
    end_offset: int
    version_bits: int
    second_version_bits: int
    globals: dict[int, int]
    player_words: tuple[tuple[int, ...], ...]
    global_arrays: dict[int, tuple[int, ...]]
    player_byte_arrays: tuple[bytes, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedWorldRules:
    offset: int
    end_offset: int
    present_word: int
    expert: SavedExpertEngine | None
    globals: SavedGlobalRuleEngine | None
    raw: bytes


def read_world_rules(r: SaveReader) -> SavedWorldRules:
    """Read the outer presence word and two records, stopping at BaseWorld.

    Any nonzero presence word enables both records. Unknown versions and
    malformed or truncated payloads restore the entire starting cursor.
    """
    start = r.pos
    try:
        if r.version != 0x44E666:
            raise SaveDecodeError("unsupported outer World save version", start)
        present_word = r.u32()
        expert = read_expert_engine(r) if present_word else None
        globals_ = read_global_rule_engine(r) if present_word else None
        return SavedWorldRules(start, r.pos, present_word, expert, globals_, r.data[start : r.pos])
    except SaveDecodeError:
        r.pos = start
        raise


def _nonnegative_short(r: SaveReader) -> int:
    at = r.pos
    value = r.i16()
    if value < 0:
        raise SaveDecodeError(f"negative ExpertEngine size {value}", at)
    return value


def _words(r: SaveReader, count: int) -> tuple[int, ...]:
    if not 0 <= count <= r.remaining // 4:
        raise SaveDecodeError(f"invalid rule-engine word count {count}", r.pos)
    return tuple(r.u32() for _ in range(count))


def _elements(r: SaveReader, count: int) -> tuple[bytes, ...]:
    # Native Serialize.h helper0x140bdc8f0 limits count*24 to10MiB.
    size = count * 24
    if not 0 <= size <= min(_MAX_NATIVE_PAYLOAD, r.remaining):
        raise SaveDecodeError(f"invalid ExpertEngine element payload size {size}", r.pos)
    return tuple(r.take(24) for _ in range(count))


def read_expert_engine(r: SaveReader) -> SavedExpertEngine:
    start = r.pos
    try:
        return _expert_engine(r)
    except SaveDecodeError:
        r.pos = start
        raise


def _expert_engine(r: SaveReader) -> SavedExpertEngine:
    # Native 140bd51e0 -> 140bddcb0, with no extra derived wire extension.
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError("unsupported ExpertEngine save version", start)
    string_capacity = _nonnegative_short(r)
    count = _nonnegative_short(r)
    discarded_word = r.u32()
    if count > r.remaining // 4:
        raise SaveDecodeError(f"invalid ExpertEngine string count {count}", r.pos)
    strings = tuple(r.take(r.count(item_size=1)) for _ in range(count))
    capacity28, capacity40 = _nonnegative_short(r), _nonnegative_short(r)
    script_debugging = r.u8()
    count = _nonnegative_short(r)
    if count > r.remaining // 24:
        # Each list requires16 header bytes and8 later link-header bytes.
        raise SaveDecodeError(f"invalid ExpertEngine list count {count}", r.pos)
    lists = []
    for _ in range(count):
        begin = r.pos
        active, member4, capacity, used, discarded = r.u32(), r.u32(), r.i16(), r.i16(), r.u32()
        rules = []
        if active:
            if not 0 <= used <= capacity or used > r.remaining // 24:
                raise SaveDecodeError("invalid active ExpertEngine rule-list capacity/count", begin)
            for _ in range(used):
                rule_start = r.pos
                descriptor = r.take(24)
                # Native modern caller passes descriptor byte13 as the
                # element count;140bdc8f0 reads exactly24 bytes per element.
                elements = _elements(r, descriptor[13])
                debug_string = None
                if script_debugging == 1:
                    # 140a150f0 receives byte-length+1 from the caller;
                    # it adds no length prefix of its own.
                    debug_string = r.take(r.u8() + 1)
                rules.append(
                    SavedExpertRule(descriptor, elements, debug_string, r.data[rule_start : r.pos])
                )
        lists.append(
            SavedExpertRuleList(
                (active, member4, capacity, used, discarded), tuple(rules), r.data[begin : r.pos]
            )
        )
    links = []
    for rule_list in lists:
        begin = r.pos
        capacity, count, discarded = r.i16(), r.i16(), r.u32()
        values: tuple[int, ...] = ()
        if rule_list.header[0]:
            if not 0 <= count <= capacity or count > r.remaining // 2:
                raise SaveDecodeError("invalid ExpertEngine rule links", begin)
            values = tuple(r.u16() for _ in range(count))
        links.append(SavedExpertLinks(capacity, count, discarded, values, r.data[begin : r.pos]))
    return SavedExpertEngine(
        start,
        r.pos,
        string_capacity,
        discarded_word,
        strings,
        capacity28,
        capacity40,
        script_debugging,
        tuple(lists),
        tuple(links),
        r.data[start : r.pos],
    )


def read_global_rule_engine(r: SaveReader) -> SavedGlobalRuleEngine:
    start = r.pos
    try:
        return _global_rule_engine(r)
    except SaveDecodeError:
        r.pos = start
        raise


def _global_rule_engine(r: SaveReader) -> SavedGlobalRuleEngine:
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError("unsupported global rule-engine save version", start)
    # Modern native140bf4d30 has a nested format version. Only the paired
    # 0.14 path is established here; it also stores a second version word.
    version_bits = r.u32()
    if version_bits != 0x3E0F5C29:
        raise SaveDecodeError(f"unsupported nested rule version {version_bits:#x}", start)
    second_version_bits = r.u32()
    globals_ = {address: r.u32() for address in range(0x1442A7480, 0x1442A74A4, 4)}
    # 140bf38f0:8 rows,100 words at save68.9; no serialized allocation header.
    player_words = tuple(_words(r, 100) for _ in range(8))
    arrays = {address: _words(r, 256) for address in (0x1442A7080, 0x1442A6080, 0x1442A6480)}
    player_bytes = tuple(r.take(256) for _ in range(8))
    return SavedGlobalRuleEngine(
        start,
        r.pos,
        version_bits,
        second_version_bits,
        globals_,
        player_words,
        arrays,
        player_bytes,
        r.data[start : r.pos],
    )
