"""Native save68.9 world fields after TribeScenario's virtual reader.

The current load_flag0 grammar follows BaseWorld14160d710 and World14169bd10.
Member keys refer to native storage offsets; scalar words retain wire bits.
Nonempty saved groups stop explicitly until their complete reader is
supported. Script state is read without executing the script.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_unit_ai import SavedUnitAIPath, _read_path
from vantage.replay_xs import SavedXS, read_xs


@dataclass(frozen=True, slots=True)
class SavedTailSlot:
    player_array_index: int
    humanity: int
    name_bytes: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedTailCommandCache:
    member118: int
    command_units: tuple[int, ...]
    selected_units: tuple[tuple[int, ...], ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedBaseWorldTail:
    offset: int
    end_offset: int
    local_d84: int
    fields: dict[int, int]
    slots: tuple[SavedTailSlot, ...]
    player_flags: tuple[int, ...]
    saved_player_count: int
    words_at238: tuple[int, ...]
    command_cache: SavedTailCommandCache
    paths: tuple[SavedUnitAIPath, ...]
    group_header: tuple[int, int]
    color_correction: bytes
    global_flag: int
    trigger_ids: tuple[int, ...]
    values_at270: tuple[int, ...]
    color_words: tuple[int, int, int]
    raw: bytes


def _words(r: SaveReader, count: int) -> tuple[int, ...]:
    if not 0 <= count <= r.remaining // 4:
        raise SaveDecodeError(f"invalid world-tail word count {count}", r.pos)
    return tuple(r.u32() for _ in range(count))


def _command_cache(r: SaveReader) -> SavedTailCommandCache:
    # Native140f52c80, modern branch: the count helper140f3ef10 reads2
    # bytes then zero-extends into the native int, despite its wider storage.
    start = r.pos
    count = r.u16()
    member118 = r.u32()
    command_units = _words(r, count)
    selected = tuple(_words(r, r.u16()) for _ in range(9))
    return SavedTailCommandCache(member118, command_units, selected, r.data[start : r.pos])


def read_base_world_tail(r: SaveReader, *, load_flag: int = 0) -> SavedBaseWorldTail:
    start = r.pos
    try:
        return _base_world_tail(r, load_flag)
    except SaveDecodeError:
        r.pos = start
        raise


def _base_world_tail(r: SaveReader, load_flag: int) -> SavedBaseWorldTail:
    start = r.pos
    if r.version != 0x44E666 or load_flag != 0:
        raise SaveDecodeError("unsupported BaseWorld-tail version/load flag", start)
    local_d84 = r.u32()
    fields = {0xC: r.u32()}
    slots = []
    for _ in range(9):
        begin = r.pos
        index, humanity = r.u32(), r.u32()
        name = r.take(r.count(item_size=1))
        slots.append(SavedTailSlot(index, humanity, name, r.data[begin : r.pos]))
    player_flags = _words(r, 9)
    saved_player_count = r.u32()
    for member in (0x224, 0x230, 0x234):
        fields[member] = r.u32()
    words = _words(r, r.count(item_size=4))
    cache = _command_cache(r)
    paths = tuple(_read_path(r) for _ in range(r.count(item_size=28)))
    # Native14160c450: two direct u32 reads, then count58 objects with
    # vtable1432a0478/slot18 ->1410e45a0 (group.cpp).
    at = r.pos
    groups = r.u32(), r.u32()
    if groups[0] != 0:
        raise SaveDecodeError(f"unresolved saved group objects count {groups[0]}", at)
    color = r.de_bytes()  # 1415e6cc0 ->140a1bdf0.
    flag = r.u8()
    triggers = _words(r, r.count(item_size=4))
    values = _words(r, r.count(item_size=4))
    color_words = r.u32(), r.u32(), r.u32()
    return SavedBaseWorldTail(
        start,
        r.pos,
        local_d84,
        fields,
        tuple(slots),
        player_flags,
        saved_player_count,
        words,
        cache,
        paths,
        groups,
        color,
        flag,
        triggers,
        values,
        color_words,
        r.data[start : r.pos],
    )


def _read_outer_scalar_prefix(r: SaveReader) -> dict[int | str, int]:
    """Exact129 bytes before TriggerSystem constructor141644f40."""
    start = r.pos
    fields: dict[int | str, int] = {}
    for member, width in (
        (0x840, 4),
        (0x844, 4),
        (0x848, 4),
        (0x84C, 1),
        (0x850, 4),
        (0x854, 1),
        (0x855, 1),
        (0x856, 1),
        (0x860, 1),
    ):
        fields[member] = int.from_bytes(r.take(width), "little")
    for member in range(0x864, 0x8B8, 4):
        fields[member] = r.u32()
    fields["option_flag1"], fields["option_flag2"] = r.u8(), r.u8()
    for member in (0x8D4, 0x8D5, 0x8D6, 0x8D8, 0x8D9, 0x8DA, 0x8DB):
        fields[member] = r.u8()
    fields[0x8DC], fields[0x8E0] = r.u32(), r.u8()
    fields[0x8E2], fields[0x8E4], fields[0x8E8], fields[0x8EC] = (
        r.u16(),
        r.u16(),
        r.u32(),
        r.u16(),
    )
    assert r.pos - start == 129
    return fields


@dataclass(frozen=True, slots=True)
class SavedTriggerEffect:
    kind: int
    words: tuple[int, ...]
    text: bytes
    sound: bytes
    selected_units: tuple[int, ...]
    extra_strings: tuple[bytes, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedTriggerCondition:
    kind: int
    words: tuple[int, ...]
    text: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedTriggerBody:
    fields: dict[int, int]
    strings: tuple[bytes, bytes, bytes]
    effects: tuple[SavedTriggerEffect, ...]
    effect_order: tuple[int, ...]
    conditions: tuple[SavedTriggerCondition, ...]
    condition_order: tuple[int, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedTriggerSystem:
    offset: int
    end_offset: int
    version_bits: int
    fields: dict[int, int]
    triggers: tuple[SavedTriggerBody, ...]
    trigger_order: tuple[int, ...]
    words_atc: tuple[int, ...]
    words_at410: tuple[int, ...]
    indexed_strings: tuple[tuple[int, bytes], ...]
    pairs_atce0: tuple[tuple[int, int], ...]
    pairs_atcf8: tuple[tuple[int, int], ...]
    records_atd40: tuple[tuple[int, tuple[tuple[int, ...], ...]], ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedWorldTailMessage:
    present: int
    fields: dict[int, int]
    text: bytes | None
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedOuterWorldTail:
    offset: int
    end_offset: int
    fields: dict[int | str, int]
    triggers: SavedTriggerSystem
    xs_flag1: int
    xs1: SavedXS | None
    strings64: tuple[bytes, ...]
    xs_flag2: int
    xs2: SavedXS | None
    player_teams: tuple[int, ...]
    game_values: tuple[int, ...]
    game_flags: tuple[int, ...]
    strings32: tuple[bytes, ...]
    messages: tuple[SavedWorldTailMessage, ...]
    words_at938: tuple[int, ...]
    records: tuple[tuple[int, ...], ...]
    terrain_present: int
    terrain_effects: tuple[tuple[int, bytes, int], ...] | None
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedWorldTail:
    offset: int
    end_offset: int
    base: SavedBaseWorldTail
    outer: SavedOuterWorldTail
    raw: bytes


def read_world_tail(reader: SaveReader, *, load_flag: int = 0) -> SavedWorldTail:
    """Read after the complete scenario; leave any following caller bytes unread.

    All failures restore the initial cursor. Nonempty saved groups are an
    explicit unsupported boundary.
    """
    start = reader.pos
    try:
        base = read_base_world_tail(reader, load_flag=load_flag)
        outer = read_outer_world_tail(reader)
        return SavedWorldTail(start, reader.pos, base, outer, reader.data[start : reader.pos])
    except SaveDecodeError:
        reader.pos = start
        raise


def _count64(r: SaveReader, minimum: int) -> int:
    at = r.pos
    count = int.from_bytes(r.take(8), "little")
    if count > r.remaining // minimum:
        raise SaveDecodeError(f"invalid world-tail u64 count {count}", at)
    return count


def read_outer_world_tail(reader: SaveReader) -> SavedOuterWorldTail:
    """Read World14169bd10's continuation after the BaseWorld reader returns."""
    start = reader.pos
    try:
        if reader.version != 0x44E666:
            raise SaveDecodeError("unsupported outer-world tail version", start)
        return _read_outer_world_tail(reader)
    except SaveDecodeError:
        reader.pos = start
        raise


def _sized_bytes(r: SaveReader) -> bytes:
    return r.take(r.count(item_size=1))


def _trigger_string(r: SaveReader) -> bytes:
    # Native140a1cf00 checks requiredBufSize<=0x2800, then reads that
    # complete count, including the writer's terminator slot when nonempty.
    at = r.pos
    size = r.u32()
    if size > 0x2800:
        raise SaveDecodeError(f"invalid trigger string size {size}", at)
    return r.take(size)


def _trigger_words(r: SaveReader, capacity: int) -> tuple[int, ...]:
    at = r.pos
    count = r.count(item_size=4)
    if count > capacity:
        raise SaveDecodeError(f"trigger fields exceed native capacity {capacity}", at)
    return _words(r, count)


def _trigger_effect(r: SaveReader) -> SavedTriggerEffect:
    # Native141647380: serialized parameter words start at+0x10. Its
    # fixed native parameter capacity is83 words, followed by pointer storage.
    start = r.pos
    kind = r.u32()
    words = _trigger_words(r, 83)
    text, sound = _sized_bytes(r), _sized_bytes(r)
    # Saved member+0x20 is parameter4. Omitted parameters default to-1;
    # only a positive signed selection count causes an incoming array read.
    count = words[4] if len(words) > 4 else 0xFFFFFFFF
    selected = _words(r, count) if 0 < count < 0x80000000 else ()
    extra = _sized_bytes(r), _sized_bytes(r)  # nestedversion>3.8.
    return SavedTriggerEffect(kind, words, text, sound, selected, extra, r.data[start : r.pos])


def _trigger_condition(r: SaveReader) -> SavedTriggerCondition:
    # Native141644330: modern parameter block at+0x10 has34 words;
    # >=2.3 adds the following signed length and exact byte string.
    start = r.pos
    kind = r.u32()
    words = _trigger_words(r, 34)
    text = _sized_bytes(r)
    return SavedTriggerCondition(kind, words, text, r.data[start : r.pos])


def _trigger_body(r: SaveReader) -> SavedTriggerBody:
    # Native1416430b0, nestedversion5.0: widths from its original ASM,
    # including the hidden count/order read arguments at+0x70 and+0x58.
    start = r.pos
    fields = {}
    for member, width in (
        (0, 4),
        (4, 1),
        (0xB5, 1),
        (0x28, 4),
        (5, 1),
        (8, 4),
        (0x88, 1),
        (0xA8, 4),
        (0xAC, 1),
        (0xAD, 1),
        (0x78, 4),
        (0xAE, 1),
    ):
        fields[member] = int.from_bytes(r.take(width), "little")
    strings = _trigger_string(r), _trigger_string(r), _trigger_string(r)
    effects = tuple(_trigger_effect(r) for _ in range(r.count(item_size=24)))
    effect_order = _words(r, len(effects))
    conditions = tuple(_trigger_condition(r) for _ in range(r.count(item_size=12)))
    condition_order = _words(r, len(conditions))
    return SavedTriggerBody(
        fields, strings, effects, effect_order, conditions, condition_order, r.data[start : r.pos]
    )


def _read_trigger_system(r: SaveReader) -> SavedTriggerSystem:
    # Native141644f40 uses its own f64 version. Only observed5.0 is supported;
    # older4.1..4.6 saves square the final outer count, unlike this branch.
    start = r.pos
    version = int.from_bytes(r.take(8), "little")
    if version != 0x4014000000000000:
        raise SaveDecodeError("unsupported trigger-system nested version", start)
    fields = {8: r.u8()}
    count = r.count(item_size=47)
    triggers = tuple(_trigger_body(r) for _ in range(count))
    order = _words(r, count)
    words = _words(r, 256)
    extra_words = _words(r, r.count(item_size=4))
    strings = tuple((r.u32(), r.take(r.count(item_size=1))) for _ in range(r.count(item_size=8)))
    fields[0xCB4] = r.u32()
    fields[0xCD8], fields[0xC68] = r.u32(), r.u8()
    pairs35 = tuple((r.u32(), r.u8()) for _ in range(_count64(r, 5)))
    pairs40 = tuple((r.u32(), r.u8()) for _ in range(_count64(r, 5)))
    records = tuple(
        (r.u32(), tuple(_words(r, 6) for _ in range(_count64(r, 24))))
        for _ in range(_count64(r, 12))
    )
    fields[0xD98] = r.u8()
    return SavedTriggerSystem(
        start,
        r.pos,
        version,
        fields,
        triggers,
        order,
        words,
        extra_words,
        strings,
        pairs35,
        pairs40,
        records,
        r.data[start : r.pos],
    )


def _read_outer_world_tail(r: SaveReader) -> SavedOuterWorldTail:
    # C14169bd10 branches via LAB1416a11a6 and LAB1416a1685 into the
    # lexically older branch. Those jumps still read the modern payload below.
    start = r.pos
    sections = {}
    fields = _read_outer_scalar_prefix(r)
    sections["scalar_prefix"] = r.data[start : r.pos]
    triggers = _read_trigger_system(r)
    sections["triggers"] = triggers.raw
    at = r.pos
    xs_flag1 = r.u8()
    xs1 = read_xs(r) if xs_flag1 else None
    strings64 = tuple(r.de_bytes() for _ in range(_count64(r, 4)))
    xs_flag2 = r.u8()
    xs2 = read_xs(r) if xs_flag2 else None
    sections["scripts_and_strings"] = r.data[at : r.pos]
    at = r.pos
    teams = tuple(r.u8() for _ in range(8))
    game_values = _words(r, 4)
    game_flags = tuple(r.u8() for _ in range(4))
    fields[0x818], fields[0x81C] = r.u32(), r.u32()
    strings32 = tuple(r.take(r.count(item_size=1)) for _ in range(r.count(item_size=4)))
    fields[0x85C], fields[0x857] = r.u32(), r.u8()
    sections["teams_game_options_and_strings"] = r.data[at : r.pos]
    at = r.pos
    messages = []
    for _ in range(10):
        begin = r.pos
        present = r.u8()
        message: dict[int, int] = {}
        text = None
        if present:
            message[0x14], message[0x18] = r.u32(), r.u32()
            message[0x1C], message[0x20] = r.u8(), r.u32()
            message[0x30], message[0x31] = r.u8(), r.u8()
            text = r.take(r.count(item_size=1))
        messages.append(SavedWorldTailMessage(present, message, text, r.data[begin : r.pos]))
    sections["messages"] = r.data[at : r.pos]
    at = r.pos
    words = _words(r, r.count(item_size=4))
    records = tuple((*_words(r, 4), r.u8(), r.u32()) for _ in range(r.count(item_size=21)))
    fields[0x980] = r.u32()
    terrain_present = r.u8()
    terrain_effects = None
    if terrain_present:
        # Native1414d31f0 ->140e969a0 ->140a150f0: u64 length then
        # exact bytes, with the shared serializer's native10MiB limit.
        effects = []
        for _ in range(r.count(item_size=16, signed=False)):
            key = r.u32()
            at_size = r.pos
            size = _count64(r, 1)
            if size > 0xA00000:
                raise SaveDecodeError("terrain effect key exceeds native10MiB limit", at_size)
            effects.append((key, r.take(size), r.u32()))
        terrain_effects = tuple(effects)
    sections["lists_and_terrain_effects"] = r.data[at : r.pos]
    return SavedOuterWorldTail(
        start,
        r.pos,
        fields,
        triggers,
        xs_flag1,
        xs1,
        strings64,
        xs_flag2,
        xs2,
        teams,
        game_values,
        game_flags,
        strings32,
        tuple(messages),
        words,
        records,
        terrain_present,
        terrain_effects,
        sections,
        r.data[start : r.pos],
    )
