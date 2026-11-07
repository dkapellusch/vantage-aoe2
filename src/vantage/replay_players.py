"""Native DE save-68.9 base-player headers, before derived player/object data.

The sequential layout comes from WorldPlayerBase's stream constructor
0x141713f70 and its string/scalar helpers. See the player-base native evidence
under artifacts/game-internals/2026-10-18-world-restore. This reader never scans
for the next player: the caller must supply a structural factory boundary.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_xs import SavedXS, read_xs


@dataclass(frozen=True, slots=True)
class SavedPlayer:
    """A base header with exact resource bits and every consumed wire section.

    The second resource-sized array has not been assigned a gameplay meaning.
    ``fields`` keeps other members under their native runtime offsets, without
    treating those memory offsets as serialized offsets. ``end_offset`` points
    to the derived constructor's first marker, not the next player's header.
    """

    offset: int
    end_offset: int
    player_id: int | None
    factory_type: int
    name: str
    name_bytes: bytes
    civilization: str
    civilization_bytes: bytes
    relations: tuple[int, ...]
    diplomacy: tuple[int, ...]
    status: int
    allied_victory: int
    color_table_id: int
    resources: tuple[float, ...]
    resource_words: tuple[int, ...]
    secondary_resource_words: tuple[int, ...]
    equipped_skins_words: tuple[int, ...]
    id_set: tuple[int, ...]
    selected_object_ids: tuple[int, ...]
    fields: dict[int, int | tuple[int, ...]]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedResearch:
    """One native research record; unknown members keep their runtime offsets.

    The raw research state, progress, three cost adjustments, and multiple-use
    flag match all 16,610 records in the paired native snapshots. The snapshot's
    civ-dependent researchAdjustment is not the saved times-researched short;
    this reader preserves those distinct facts instead of synthesizing it.
    """

    offset: int
    end_offset: int
    research_id: int
    research_done: float
    state: int
    cost_adjustments: tuple[int, int, int]
    times_researched: int
    allow_multiple_research: bool
    strings: tuple[str, str, str]
    fields: dict[int, int]
    entries: tuple[bytes, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedPlayerHistory:
    """Exact modern history rows, death records, totals, and per-player arrays."""

    offset: int
    end_offset: int
    header_words: tuple[int, int, int]
    rows: tuple[tuple[int, int], ...]
    death_records: tuple[bytes, ...]
    fixed_words: tuple[int, ...]
    player_slots: int
    player_arrays: tuple[tuple[int, ...], tuple[int, ...]]
    tail: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedPlayerConfiguration:
    """Four native configuration groups, preserving every complete record."""

    offset: int
    end_offset: int
    counts: tuple[int, int, int, int]
    extra_word: int
    groups: tuple[tuple[bytes, ...], ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedPlayerPrefix:
    """Verified WorldPlayer data following a base header, with an explicit stop.

    ``saved_ai`` stops before the AI payload; its enclosing WorldPlayer tail
    remains unread. ``outer_player`` stops after WorldPlayer's relic modifier.
    Gaia has an additional outer payload, so neither value claims the next
    master vector or the whole player has been decoded. No boundary scan runs.
    """

    offset: int
    end_offset: int
    saved_type: int
    research: tuple[SavedResearch, ...]
    history: SavedPlayerHistory
    configuration: SavedPlayerConfiguration
    next_section: Literal["saved_ai", "outer_player"]
    fields: dict[int, int]
    sections: dict[str, bytes]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedPlayerAIContinuation:
    """WorldPlayer state after its complete saved-AI wrapper.

    The next master-table marker remains unread. The XS presence byte is part
    of this continuation only when an AI wrapper was actually loaded; it is
    absent from the common Gaia/human tail already handled by the prefix API.
    """

    offset: int
    end_offset: int
    xs_flag: int
    task_accumulator_count: int
    task_group_count: int
    saved_relic_time_modifier_bits: int
    sections: dict[str, bytes]
    raw: bytes
    xs: SavedXS | None = None


def read_player_ai_continuation(reader: SaveReader) -> SavedPlayerAIContinuation:
    """Read the save68.9 WorldPlayer tail after a present full AI wrapper.

    Native 0x1416c2440 reads an XS byte here, then ResourceGeneration's two
    counted groups, marker11 and the relic modifier. Unverified nested bodies
    fail explicitly and restore the entire continuation's starting cursor.
    """
    start = reader.pos
    try:
        if reader.version != 0x44E666:
            raise SaveDecodeError(
                f"unsupported player AI continuation save version {reader.version:#x}", start
            )
        sections: dict[str, bytes] = {}
        xs_flag = reader.u8()
        sections["xs_flag"] = reader.data[start : reader.pos]
        xs = read_xs(reader) if xs_flag else None
        if xs is not None:
            sections["xs"] = xs.raw
        at = reader.pos
        accumulators = reader.i32()
        if accumulators != 0:
            raise SaveDecodeError("unsupported resource-generation accumulators", at)
        groups = reader.i32()
        if groups != 0:
            raise SaveDecodeError("unsupported resource-generation task groups", reader.pos - 4)
        sections["resource_generation"] = reader.data[at : reader.pos]
        at = reader.pos
        reader.marker(11)
        sections["marker1.before_relic"] = reader.data[at : reader.pos]
        at = reader.pos
        relic = reader.u32()
        sections["saved_relic_time_modifier"] = reader.data[at : reader.pos]
        return SavedPlayerAIContinuation(
            start,
            reader.pos,
            xs_flag,
            accumulators,
            groups,
            relic,
            sections,
            reader.data[start : reader.pos],
            xs,
        )
    except SaveDecodeError:
        reader.pos = start
        raise


@dataclass(frozen=True, slots=True)
class SavedGaiaExtension:
    """Gaia's fixed native fields after WorldPlayer and before the master marker.

    Members are labeled by native runtime offsets and preserve their saved bits.
    Their gameplay meanings are not inferred from default values. The following
    master marker/count belong to the caller and remain unread.
    """

    offset: int
    end_offset: int
    fields: dict[int, int | tuple[int, ...]]
    sections: dict[int, bytes]
    raw: bytes


def read_gaia_extension(reader: SaveReader) -> SavedGaiaExtension:
    """Read the exact 68.9 Gaia constructor tail, rolling back on any error.

    Native 0x14174fa70 reads two words, five triples, four words, two 9-word arrays,
    and the remaining fixed members. The resulting 452 bytes are derived from
    these reads; no measured gap or resynchronization is used.
    """
    start = reader.pos
    try:
        if reader.version != 0x44E666:
            raise SaveDecodeError(f"unsupported Gaia save version {reader.version:#x}", start)
        fields: dict[int, int | tuple[int, ...]] = {}
        sections: dict[int, bytes] = {}

        def member(offset: int, count: int = 1) -> None:
            raw = reader.take(count * 4)
            sections[offset] = raw
            values = struct.unpack("<" + str(count) + "I", raw)
            fields[offset] = values[0] if count == 1 else values

        member(0x13F0)
        member(0x13F4)
        # Legacy save<=0x911eb reads two additional words here; 68.9 omits them.
        for index in range(5):
            for offset in (0x1400, 0x1404, 0x1408):
                member(offset + index * 24)
        # Enabled since save>=0x9f851.
        for offset in (0x1474, 0x1478, 0x147C, 0x1480):
            member(offset)
        member(0x1484, 9)
        member(0x14A8, 9)
        # Enabled for save>0x9fae1.
        for offset, count in (
            (0x14CC, 1),
            (0x14D0, 10),
            (0x14F8, 1),
            (0x14FC, 1),
            (0x1500, 50),
            (0x1690, 1),
            (0x1694, 10),
        ):
            member(offset, count)
        return SavedGaiaExtension(
            start, reader.pos, fields, sections, reader.data[start : reader.pos]
        )
    except SaveDecodeError:
        reader.pos = start
        raise


def read_player_prefix(
    reader: SaveReader, header: SavedPlayer, num_players: int
) -> SavedPlayerPrefix:
    """Read verified derived data at ``header.end_offset``, with rollback on error.

    Coverage is exact save 68.9. Nonzero scout-map and resource-generation
    payloads are unsupported and reported explicitly. AI data is an explicit
    returned continuation boundary, without consuming any of that payload.
    """
    start = reader.pos
    try:
        return _read_player_prefix(reader, header, num_players)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_research(r: SaveReader) -> tuple[SavedResearch, ...]:
    count_at = r.pos
    count = r.i16()
    if not 0 <= count <= r.remaining // 63:
        raise SaveDecodeError(f"invalid research count {count}", count_at)
    result = []
    for index in range(count):
        start = r.pos
        done, state = r.f32(), r.i16()
        costs = (r.i16(), r.i16(), r.i16())
        times, multiple = r.i16(), r.u8()
        strings = (r.de_string(), r.de_string(), r.de_string())
        fields = {0xE: multiple, 0x58: r.u8(), 0x6E: r.i16(), 0x70: r.i16()}
        for slot in range(3):
            for base in (0x5A, 0x60, 0x66):
                fields[base + slot * 2] = r.i16()
        fields[0x6C], fields[0x74] = r.i16(), r.u32()
        fields[0x78], fields[0x7A] = r.u8(), r.i16()
        entries_at = r.pos
        entry_count = r.i16()
        if not 0 <= entry_count <= r.remaining // 13:
            raise SaveDecodeError(f"invalid research entry count {entry_count}", entries_at)
        entries = tuple(r.take(13) for _ in range(entry_count))
        fields[0x7C] = r.i16()
        result.append(
            SavedResearch(
                start,
                r.pos,
                index,
                done,
                state,
                costs,
                times,
                bool(multiple),
                strings,
                fields,
                entries,
                r.data[start : r.pos],
            )
        )
    return tuple(result)


def _read_history(r: SaveReader) -> SavedPlayerHistory:
    start = r.pos
    r.marker(11)
    rows_at = r.pos
    row_count, word18, word20 = r.i32(), r.i32(), r.i32()
    r.marker(22)
    if not 0 <= row_count <= r.remaining // 4:
        raise SaveDecodeError(f"invalid history row count {row_count}", rows_at)
    rows = tuple((r.u16(), r.u16()) for _ in range(row_count))
    deaths = tuple(r.take(21) for _ in range(r.count(item_size=21)))
    fixed = tuple(r.u32() for _ in range(17))
    players = r.count(item_size=8)
    arrays = (
        tuple(r.u32() for _ in range(players)),
        tuple(r.u32() for _ in range(players)),
    )
    tail = r.take(16)
    r.marker(33)
    return SavedPlayerHistory(
        start,
        r.pos,
        (row_count, word18, word20),
        rows,
        deaths,
        fixed,
        players,
        arrays,
        tail,
        r.data[start : r.pos],
    )


def _read_configuration(r: SaveReader) -> SavedPlayerConfiguration:
    start = r.pos
    counts = (r.u8(), r.u8(), r.u16(), r.u8())
    extra = r.u32()
    groups = []
    # 1414aea70 modern branches: old fixed-capacity arrays are absent.
    for group, count in enumerate(counts):
        records = []
        for _ in range(count):
            at = r.pos
            if group == 2:
                r.skip(97)  # id4,flag1,word4,84-byte block,word4
                r.skip(r.u8() * 4)
                r.skip(16)
            else:
                r.skip(9 if group == 3 else 5)
                for _ in range(3):
                    r.skip(r.u8() * 4)
                r.skip((110, 103, 0, 96)[group])
            records.append(r.data[at : r.pos])
        groups.append(tuple(records))
    return SavedPlayerConfiguration(
        start, r.pos, counts, extra, tuple(groups), r.data[start : r.pos]
    )


def _read_player_prefix(r: SaveReader, header: SavedPlayer, num_players: int) -> SavedPlayerPrefix:
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError(f"unsupported player save version {r.version:#x}", start)
    if start != header.end_offset:
        raise SaveDecodeError("derived player does not follow its base header", start)
    if num_players != len(header.relations):
        raise SaveDecodeError("derived world player count differs from base header", start)
    sections: dict[str, bytes] = {}
    fields: dict[int, int] = {}

    def section(name: str, at: int) -> None:
        sections[name] = r.data[at : r.pos]

    r.marker(11)
    saved_type = r.u8()  # 1415e5830 ->140daf040
    if saved_type != header.factory_type:
        raise SaveDecodeError("derived saved type differs from factory tag", start + 1)
    for member, size in (
        (0x6DC, 4),
        (0x710, 4),
        (0x6E0, 4),
        (0x6E4, 4),
        (0x6E8, 1),
        (0x6EC, 4),
        (0x6F0, 4),
        (0x6F4, 4),
        (0x6F8, 1),
        (0x6FC, 4),
        (0x700, 4),
        (0x6D8, 4),
        (0x714, 4),
    ):
        fields[member] = r.u8() if size == 1 else r.u32()
    section("fixed_prefix", start)
    at = r.pos
    research = _read_research(r)
    section("research", at)
    at = r.pos
    fields[0xD30] = r.u32()
    section("runtime_d30", at)
    history = _read_history(r)
    sections["history"] = history.raw
    at = r.pos
    fields[0xD20], fields[0xD24] = r.u32(), r.u32()
    r.marker(11)
    section("after_history", at)
    at = r.pos
    for _ in range(9):
        r.skip(21)
        r.skip(r.u8())
        r.skip(2)  # final byte and extra save>=67.3 byte
    r.skip(2)
    r.marker(11)
    section("nine_groups", at)
    at = r.pos
    r.skip(40)
    r.marker(11)
    section("two_fixed_arrays", at)
    at = r.pos
    for member in range(0x1378, 0x13A4, 4):
        fields[member] = r.u32()
    for member, size in (
        (0x12D0, 1),
        (0xD80, 1),
        (0xD81, 1),
        (0x1308, 4),
        (0x13A4, 4),
        (0x13AC, 1),
        (0x13A8, 4),
        (0x13AD, 1),
        (0x1300, 4),
    ):
        fields[member] = r.u8() if size == 1 else r.u32()
    r.marker(11)
    fields[0x1304] = r.u8()
    r.skip(num_players)
    for member in (0xD34, 0xD3C, 0xD40, 0xD44, 0xD48, 0xD50, 0xD38, 0xD4C):
        fields[member] = r.u32()
    r.skip(36)  # old_player_kills[9]
    section("fixed_after_groups", at)
    configuration = _read_configuration(r)
    sections["configuration"] = configuration.raw
    at = r.pos
    if saved_type == 1:
        fields[0x12E8] = r.u32()
        if fields[0x12E8]:
            raise SaveDecodeError("unsupported saved scout-map payload", r.pos)
    fields[0x1330] = r.u32()
    for member in (0x13AE, 0x13AF, 0x12F8):
        fields[member] = r.u8()
    r.marker(11)
    if saved_type == 3:
        saved_ai = r.i32()
        if saved_ai == 1:
            section("before_saved_ai", at)
            return SavedPlayerPrefix(
                start,
                r.pos,
                saved_type,
                research,
                history,
                configuration,
                "saved_ai",
                fields,
                sections,
                r.data[start : r.pos],
            )
    # Empty generation accumulators are present in every verified Gaia/human.
    # Nonempty bodies have a known entry point but are not silently skipped.
    accumulator_count = r.i32()
    if accumulator_count != 0:
        raise SaveDecodeError("unsupported resource-generation accumulators", r.pos - 4)
    task_group_count = r.i32()
    if task_group_count != 0:
        raise SaveDecodeError("unsupported resource-generation task groups", r.pos - 4)
    r.marker(11)
    fields[0x12FC] = r.u32()  # savedRelicTimeModifier bits; save>68.8
    section("world_player_tail", at)
    return SavedPlayerPrefix(
        start,
        r.pos,
        saved_type,
        research,
        history,
        configuration,
        "outer_player",
        fields,
        sections,
        r.data[start : r.pos],
    )


def read_player_header(
    reader: SaveReader,
    num_players: int,
    *,
    player_id: int | None = None,
    factory_type: int | None = None,
) -> SavedPlayer:
    """Read one base header transactionally, including its factory byte by default.

    ``num_players`` includes Gaia and comes from the surrounding saved world.
    A caller which already consumed the factory byte may pass ``factory_type``;
    in that case ``offset`` and ``raw`` begin at the base constructor's marker.
    Current evidence covers factory types 1 (human), 2 (Gaia), and 3 (AI). Other save
    versions/variants fail at an explicit offset with the input cursor restored.
    """
    start = reader.pos
    try:
        return _read_player_header(reader, num_players, player_id, factory_type)
    except SaveDecodeError:
        reader.pos = start
        raise


def _read_player_header(
    r: SaveReader, num_players: int, player_id: int | None, factory_type: int | None
) -> SavedPlayer:
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError(f"unsupported player save version {r.version:#x}", start)
    if not 1 <= num_players <= r.remaining // 5:
        raise SaveDecodeError(f"invalid world player count {num_players}", start)
    sections: dict[str, bytes] = {}

    def take(label: str, size: int) -> bytes:
        value = r.take(size)
        sections[label] = value
        return value

    def scalar(label: str, fmt: str) -> int:
        return int(struct.unpack("<" + fmt, take(label, struct.calcsize(fmt)))[0])

    def words(label: str, count: int) -> tuple[int, ...]:
        return struct.unpack("<" + str(count) + "I", take(label, count * 4))

    def count(label: str, item_size: int, *, signed: bool = True) -> int:
        at = r.pos
        value = scalar(label, "i" if signed else "I")
        if not 0 <= value <= r.remaining // item_size:
            raise SaveDecodeError(f"invalid {label} {value}", at)
        return value

    def marker(label: str, expected: int) -> None:
        at = r.pos
        actual = scalar(label, "B")
        if actual != expected:
            raise SaveDecodeError(f"expected player marker {expected}, found {actual}", at)

    def nul_string(label: str, *, wide_count: bool) -> bytes:
        at = r.pos
        if wide_count:
            size = count(label + ".length", 1, signed=False)
        else:
            size = scalar(label + ".length", "h")
        if size < 0 or (not wide_count and size == 0):
            raise SaveDecodeError(f"invalid {label} string length {size}", at)
        payload = take(label, size)
        if payload and payload[-1] != 0:
            raise SaveDecodeError(f"unterminated {label} string", at)
        return payload

    if factory_type is None:
        factory_type = scalar("factory_type", "B")
    if factory_type not in {1, 2, 3}:
        raise SaveDecodeError(f"unsupported player factory type {factory_type}", start)
    marker("marker1.initial", 11)
    relations = tuple(take("relations", num_players))
    diplomacy = struct.unpack("<" + str(num_players) + "i", take("diplomacy", num_players * 4))
    status, allied_victory = scalar("status", "i"), scalar("allied_victory", "B")
    name_bytes = nul_string("name", wide_count=False)
    marker("marker2", 22)
    resource_count = count("resource_count", 8)
    marker("marker3", 33)
    resource_words = words("resources", resource_count)
    resources = struct.unpack("<" + str(resource_count) + "f", sections["resources"])
    secondary = words("secondary_resource_words", resource_count)
    marker("marker1.after_resources", 11)
    fields: dict[int, int | tuple[int, ...]] = {
        0x228: scalar("runtime_228", "I"),
        0x22C: scalar("runtime_22c", "I"),
    }
    view_count = scalar("saved_view_count", "i")
    fields[0x240] = view_count
    # Native consumes view entries only for unsigned(count - 1) < 10.
    fields[0x238] = words("saved_views", view_count * 2 if 1 <= view_count <= 10 else 0)
    for member, fmt in ((0x230, "h"), (0x232, "h"), (0x88, "B")):
        fields[member] = scalar(f"runtime_{member:x}", fmt)
    at = r.pos
    civilization_bytes = r.de_bytes()
    sections["civilization"] = r.data[at : r.pos]
    skin_count = count("equipped_skins.count", 8, signed=False)
    skins = words("equipped_skins.words", skin_count * 2)
    for member in (0x89, 0x8B):
        fields[member] = scalar(f"runtime_{member:x}", "B")
    marker("marker1.before_color", 11)
    color = scalar("color_table_id", "B")
    marker("marker1.after_color", 11)
    for member in (0x5A4, 0x5A8):
        fields[member] = scalar(f"runtime_{member:x}", "I")
    id_count = scalar("id_set.count", "i")
    if id_count > r.remaining // 4:
        raise SaveDecodeError(f"invalid ID set count {id_count}", r.pos - 4)
    id_set = struct.unpack("<" + str(max(0, id_count)) + "i", take("id_set", max(0, id_count) * 4))
    # Save 68.9 skips both old counted lists, migration arrays, and old u16s
    # above LAB_141716a00: those gates end at save word 0x1a30a2.
    for member in range(0x5E0, 0x5FC, 4):
        fields[member] = scalar(f"runtime_{member:x}", "I")
    for member in (0x5FC, 0x60C, 0x61C):
        fields[member] = words(f"runtime_{member:x}", 4)
    for member in range(0x24C, 0x270, 4):
        fields[member] = scalar(f"runtime_{member:x}", "I")
    for member, fmt in (
        (0x538, "I"),
        (0x53C, "I"),
        (0x540, "B"),
        (0x541, "B"),
        (0x542, "B"),
        (0x543, "B"),
        (0x544, "I"),
        (0x548, "I"),
        (0x551, "B"),
        (0x552, "B"),
        (0x553, "B"),
        (0x554, "I"),
        (0x55C, "I"),
    ):
        fields[member] = scalar(f"runtime_{member:x}", fmt)
    nul_string("localized_name", wide_count=True)
    fields[0x14] = scalar("name_mode", "I")
    selection_count = scalar("selected_object_count", "i")
    fields[0x48C] = selection_count
    if selection_count > 0:
        fields[0x2A0] = scalar("selected_lead_object_id", "i")
        fields[0x488] = scalar("runtime_488", "I")
        if selection_count > r.remaining // 4:
            raise SaveDecodeError(f"invalid selected object count {selection_count}", r.pos)
        selected = struct.unpack(
            "<" + str(selection_count) + "i", take("selected_object_ids", selection_count * 4)
        )
    else:
        selected = ()
    for member, fmt in (
        (0x54C, "I"),
        (0x550, "B"),
        (0x578, "B"),
        (0x57C, "I"),
        (0x580, "I"),
        (0x590, "B"),
        (0x5A0, "B"),
    ):
        fields[member] = scalar(f"runtime_{member:x}", fmt)
    marker("marker1.final", 11)
    return SavedPlayer(
        start,
        r.pos,
        player_id,
        factory_type,
        name_bytes.removesuffix(b"\0").decode("utf-8", "replace"),
        name_bytes,
        civilization_bytes.decode("utf-8", "replace"),
        civilization_bytes,
        relations,
        diplomacy,
        status,
        allied_victory,
        color,
        resources,
        resource_words,
        secondary,
        skins,
        id_set,
        selected,
        fields,
        sections,
        r.data[start : r.pos],
    )
