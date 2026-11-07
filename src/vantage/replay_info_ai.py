"""Native saved InfoAI state, derived from reader 0x140c32020 for save 68.9.

Counts and markers determine every boundary. Native runtime member offsets
identify scalar words and arrays; opaque records retain exact wire bytes.
This decodes stored state without applying constructor filtering or AI updates.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader


@dataclass(frozen=True, slots=True)
class SavedInfoObject:
    object_id: int
    fields: dict[int, int]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedInfoGrid:
    fields: dict[int, int]
    cells: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedInfoSearch:
    """The nested AISearch record, including its three SearchData bodies.

    SearchData's fifteen words include one discarded native local. Preserve
    that word in wire order instead of assigning it an invented member offset.
    """

    data_words: tuple[tuple[int, ...], ...]
    subgroup_ids: tuple[tuple[int, ...], ...]
    subgroup_words: tuple[tuple[int, ...], ...]
    group_ids: tuple[tuple[int, ...], ...]
    state_word: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedInfoAI:
    offset: int
    end_offset: int
    num_players: int
    fields: dict[int, int]
    sections: dict[str, bytes]
    arrays: dict[int, tuple[bytes, ...]]
    player_words: tuple[tuple[int, ...], ...]
    shared_id_lists: tuple[tuple[int, ...], ...]
    objects: tuple[SavedInfoObject, ...]
    grid: SavedInfoGrid
    profile_bytes: bytes
    grouped_records: tuple[tuple[bytes, ...], ...]
    technology_count: int
    player_technology_words: tuple[tuple[int, ...], ...]
    short_map: tuple[tuple[int, int], ...]
    search: SavedInfoSearch
    triples: tuple[tuple[int, int, int], ...]
    raw: bytes


def read_info_ai(reader: SaveReader, num_players: int) -> SavedInfoAI:
    """Read one complete InfoAI module, with world player count including Gaia.

    Native 0x141603ef0 obtains this count from the world's player vector; it
    cannot be inferred from InfoAI's own bytes. A failure restores the cursor.
    """
    start = reader.pos
    try:
        return _read_info_ai(reader, num_players)
    except SaveDecodeError:
        reader.pos = start
        raise


def _marker(r: SaveReader, value: int) -> None:
    at = r.pos
    actual = r.u16()
    if actual != value:
        raise SaveDecodeError(f"expected AI marker {value:#x}, found {actual:#x}", at)


def _words(r: SaveReader, count: int) -> tuple[int, ...]:
    # Prove the entire fixed-width payload fits before allocating its tuple.
    if not 0 <= count <= r.remaining // 4:
        raise SaveDecodeError(f"invalid word count {count}", r.pos)
    return tuple(r.u32() for _ in range(count))


def _ids(r: SaveReader) -> tuple[int, ...]:
    return _words(r, r.count(item_size=4))


def _records(r: SaveReader, width: int, *, signed: bool = True) -> tuple[bytes, ...]:
    return tuple(r.take(width) for _ in range(r.count(item_size=width, signed=signed)))


def _object(r: SaveReader) -> SavedInfoObject:
    start = r.pos
    object_id = r.u32()
    fields = {0: r.u16(), 2: r.u16()}
    for offset in (4, 8, 0xC):
        fields[offset] = r.u32()
    fields[0x10], fields[0x12], fields[0x14], fields[0x11] = (r.u8(), r.u16(), r.u32(), r.u8())
    for offset in (0x18, 0x1C, 0x20, 0x24, 0x28):
        fields[offset] = r.u32()
    fields[0x30], fields[0x2C] = r.u16(), r.u32()
    return SavedInfoObject(object_id, fields, r.data[start : r.pos])


def _grid(r: SaveReader) -> SavedInfoGrid:
    # Native 0x141028560: four words, one byte, then height rows of width bytes.
    start = r.pos
    fields = {offset: r.u32() for offset in (8, 0xC, 0x10, 0x14)}
    fields[0x30] = r.u8()
    width, height = fields[8], fields[0xC]
    if width >= 0x80000000 or height >= 0x80000000:
        raise SaveDecodeError("negative InfoAI grid dimensions", start)
    cells = r.take(width * height)
    return SavedInfoGrid(fields, cells, r.data[start : r.pos])


def _search_data(r: SaveReader) -> tuple[int, ...]:
    # Native 0x140d48e20: member8, discarded word, then members c through3c.
    _marker(r, 0xA10)
    words = _words(r, 15)
    _marker(r, 0xA20)
    return words


def _search(r: SaveReader) -> SavedInfoSearch:
    # Native 0x140d43410 -> SearchData, two 0x140d46da0 subgroups, twenty ID lists.
    start = r.pos
    _marker(r, 0xA10)
    data = [_search_data(r)]
    subgroup_ids = []
    subgroup_words = []
    for _ in range(2):
        _marker(r, 0xA10)
        subgroup_ids.append(_ids(r))
        subgroup_words.append(_words(r, 4))
        data.append(_search_data(r))
        _marker(r, 0xA20)
    groups = tuple(_ids(r) for _ in range(20))
    state = r.u32()
    _marker(r, 0xA20)
    return SavedInfoSearch(
        tuple(data),
        tuple(subgroup_ids),
        tuple(subgroup_words),
        groups,
        state,
        r.data[start : r.pos],
    )


def _read_info_ai(r: SaveReader, num_players: int) -> SavedInfoAI:
    start = r.pos
    if r.version != 0x44E666:
        raise SaveDecodeError(f"unsupported InfoAI save version {r.version:#x}", start)
    if not 0 <= num_players <= r.remaining // 32:
        raise SaveDecodeError(f"invalid InfoAI world player count {num_players}", start)
    fields: dict[int, int] = {}
    arrays: dict[int, tuple[bytes, ...]] = {}
    sections: dict[str, bytes] = {}
    _marker(r, 0xA10)
    fields[0x4E0], fields[0x104E4] = r.u32(), r.u32()
    arrays[0x4E4] = _records(r, 4, signed=False)
    # Two vectors, four words per player each, interleaved A0,B0,A1,B1,...
    player_words = tuple(_words(r, 8) for _ in range(num_players))
    _marker(r, 0xAA0)
    shared_ids = tuple(_ids(r) for _ in range(4))
    for offset in (0x10518, 0x1051C, 0x10520):
        fields[offset] = r.u32()
    object_count = r.count(item_size=54)
    _marker(r, 0xAA0)
    objects = tuple(_object(r) for _ in range(object_count))
    _marker(r, 0xAA0)
    arrays[0x19300] = _records(r, 16)
    _marker(r, 0xAA0)
    # Two compound blocks have nine header words (including their record
    # count) and40-byte records. Member+0xc is derived, never read.
    for base in (0x19310, 0x19340):
        fields[base] = r.u32()
        count_at = r.pos
        count = r.count(item_size=40)
        fields[base + 4] = count
        for offset in (8, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24):
            fields[base + offset] = r.u32()
        if count > r.remaining // 40:
            raise SaveDecodeError(f"truncated InfoAI block count {count}", count_at)
        arrays[base + 0x28] = tuple(r.take(40) for _ in range(count))
    _marker(r, 0xAA0)
    arrays[0x19378] = _records(r, 40)
    for offset in (0x10568, 0x10580, 0x10598, 0x105B0, 0x10618, 0x10600):
        arrays[offset] = _records(r, 4)
    _marker(r, 0xAA0)
    sections["words_10648"] = r.take(9000 * 4)
    _marker(r, 0xAA0)
    fields[0x192E8] = r.u32()
    grid = _grid(r)
    for offset in (0x192EC, 0x192F4):
        fields[offset] = int.from_bytes(r.take(8), "little")
    fields[0x19380] = r.u32()
    profile = r.take(r.count(item_size=1))
    sections["bytes_19484"] = r.take(0xC0)
    _marker(r, 0xAA0)
    group_counts = _words(r, 4)
    for i, value in enumerate(group_counts):
        fields[0x19578 + i * 4] = value
    for i, value in enumerate(_words(r, 4)):
        fields[0x19568 + i * 4] = value
    grouped = []
    for count in group_counts:
        if count >= 0x80000000 or count > r.remaining // 29:
            raise SaveDecodeError(f"invalid InfoAI group count {count}", r.pos)
        grouped.append(tuple(r.take(29) for _ in range(count)))
    _marker(r, 0xAA0)
    sections["discarded_64"] = r.take(64)
    sections["bytes_19588"] = r.take(32)
    sections["bytes_195a8"] = r.take(32)
    fields[0x195C8] = r.u32()
    sections["player_bytes_19700"] = r.take(num_players)
    sections["player_bytes_19718"] = r.take(num_players)
    for offset in (0x19730, 0x19734, 0x19738, 0x1973C, 0x19740):
        fields[offset] = r.u32()
    _marker(r, 0xAA0)
    fields[0x19744] = r.u32()
    count_at = r.pos
    technology_count = r.i32()
    if not 0 <= technology_count <= 1024:
        raise SaveDecodeError(f"invalid InfoAI technology count {technology_count}", count_at)
    # Native explicitly rejects count>1024; each runtime row allocates4096
    # bytes, but only count*4 bytes per player are serialized.
    technology_words = tuple(_words(r, technology_count) for _ in range(num_players))
    for offset in (0x19760, 0x19778, 0x19790):
        arrays[offset] = tuple(r.take(4) for _ in range(num_players))
    fields[0x197A8], fields[0x197AC] = r.u32(), r.u32()
    _marker(r, 0xAA0)
    arrays[0x19808] = _records(r, 44)
    count_at = r.pos
    map_count = r.i16()
    if not 0 <= map_count <= r.remaining // 6:
        raise SaveDecodeError(f"invalid InfoAI short map count {map_count}", count_at)
    short_map = tuple((r.i16(), r.u32()) for _ in range(map_count))
    search = _search(r)
    arrays[0xD8] = tuple(r.take(4) for _ in range(num_players))
    triples = tuple((r.u32(), r.u32(), r.u32()) for _ in range(r.count(item_size=12)))
    _marker(r, 0xA20)
    return SavedInfoAI(
        start,
        r.pos,
        num_players,
        fields,
        sections,
        arrays,
        player_words,
        shared_ids,
        objects,
        grid,
        profile,
        tuple(grouped),
        technology_count,
        technology_words,
        short_map,
        search,
        triples,
        r.data[start : r.pos],
    )
