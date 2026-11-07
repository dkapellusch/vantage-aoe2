"""Native BaseScenario 1.59 reader for the save68.9 profile.

The grammar comes from 140d86730 and its stream helpers, retained under the
world-envelope/scenario-base artifacts. It leaves TribeScenario data unread.
Native localization, string cleanup, and external file loads are separate;
all saved values and bytes remain available here.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_binary import SaveDecodeError, SaveReader


@dataclass(frozen=True, slots=True)
class SavedScenarioField:
    name: str
    offset: int
    end_offset: int
    value: int | bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedScenarioBitmap:
    offset: int
    end_offset: int
    version_word: int
    width: int
    height: int
    orientation_word: int
    payload: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class SavedScenarioPlayer:
    name_256: bytes
    name_string_id_word: int
    active_word: int
    type_word: int
    civilization: bytes
    architecture: bytes
    posture_word: int
    civilization_lock_word: int
    personality_lock_word: int
    build_list_filename: bytes
    city_plan_filename: bytes
    ai_rules_filename: bytes
    build_list_data: bytes
    city_plan_data: bytes
    ai_rules_data: bytes
    ai_rules_type_byte: int


@dataclass(frozen=True, slots=True)
class SavedScenarioBase:
    offset: int
    end_offset: int
    version_bits: int
    max_players: int
    gaia_player_index: int
    players: tuple[SavedScenarioPlayer, ...]
    victory_conquest_byte: int
    list_num: int
    avail_id_word: int
    old_time_bits: int
    member_248: bytes
    resource_string_id_words: tuple[int, ...]
    resource_texts: tuple[bytes, ...]
    member_290: bytes
    member_260: bytes
    member_278: bytes
    member_2a8: bytes
    bitmap: SavedScenarioBitmap
    tail_word: int
    fields: tuple[SavedScenarioField, ...]
    raw: bytes


class _ScenarioReader:
    def __init__(self, reader: SaveReader) -> None:
        self.reader = reader
        self.fields: list[SavedScenarioField] = []

    def word(self, name: str, size: int = 4, *, signed: bool = False) -> int:
        start = self.reader.pos
        raw = self.reader.take(size)
        value = int.from_bytes(raw, "little", signed=signed)
        self.fields.append(SavedScenarioField(name, start, self.reader.pos, value, raw))
        return value

    def blob(self, name: str, count: int) -> bytes:
        start = self.reader.pos
        raw = self.reader.take(count)
        self.fields.append(SavedScenarioField(name, start, self.reader.pos, raw, raw))
        return raw

    def short_bytes(self, name: str) -> bytes:
        start = self.reader.pos
        count = self.word(name + ".length", 2, signed=True)
        if count < 0:
            raise SaveDecodeError("negative scenario short-string length", start)
        return self.blob(name, count)

    def de_bytes(self, name: str) -> bytes:
        start = self.reader.pos
        value = self.reader.de_bytes()
        raw = self.reader.data[start : self.reader.pos]
        self.fields.append(SavedScenarioField(name, start, self.reader.pos, value, raw))
        return value

    def bitmap(self) -> SavedScenarioBitmap:
        # Picture1409c3530 -> size1409c2a80; positive dimensions cause a native
        # stream skip of height * aligned(width, 4) + 0x428 bytes. Retain them.
        start = self.reader.pos
        version = self.word("bitmap.version")
        width = self.word("bitmap.width", signed=True)
        height = self.word("bitmap.height", signed=True)
        orientation = self.word("bitmap.orientation", 2)
        payload = b""
        if width > 0 and height > 0:
            size = height * ((width + 3) & ~3) + 0x428
            if size > 0x7FFFFFFF:
                raise SaveDecodeError("scenario bitmap byte count overflows native i32", start + 4)
            payload = self.blob("bitmap.payload", size)
        return SavedScenarioBitmap(
            start,
            self.reader.pos,
            version,
            width,
            height,
            orientation,
            payload,
            self.reader.data[start : self.reader.pos],
        )


def read_scenario_base(reader: SaveReader) -> SavedScenarioBase:
    """Read BaseScenario 1.59, restoring the entire cursor on decode failure.

    Saved ``MaxPlayers`` controls the arrays (16 in the captured recordings),
    independently of the number of match participants. Nonempty native strings,
    bitmap payloads, and embedded AI files use their serialized lengths. Native
    list_num >= 1 is rejected by the source reader and is rejected here as well.
    """
    start = reader.pos
    try:
        if reader.version != 0x44E666:
            raise SaveDecodeError("BaseScenario requires save68.9", start)
        stream = _ScenarioReader(reader)
        version = stream.word("version_bits")
        if version != 0x3FCB851F:
            raise SaveDecodeError("unsupported BaseScenario version (expected 1.59)", start)
        count_at = reader.pos
        count = stream.word("MaxPlayers")
        # Every entry has at least a 256-byte fixed name. Prove a lower bound
        # before allocating or iterating; all subsequent reads remain checked.
        if count > 0xA00000 or count > reader.remaining // 256:
            raise SaveDecodeError("invalid scenario player count", count_at)
        gaia = stream.word("GaiaPlayerIndex")
        names = [stream.blob(f"player_name[{i}]", 256) for i in range(count)]
        name_ids = [stream.word(f"player_name_string_id[{i}]") for i in range(count)]
        rows: list[tuple[int, int, bytes, bytes, int]] = []
        seen_inactive = False
        active_count = 0
        for i in range(count):
            active_at = reader.pos
            active = stream.word(f"active[{i}]")
            if active:
                active_count += 1
                if seen_inactive or active_count > 8:
                    raise SaveDecodeError("invalid scenario active-player prefix", active_at)
            else:
                seen_inactive = True
            player_type = stream.word(f"player_type[{i}]")
            civilization = stream.de_bytes(f"civilization[{i}]")
            architecture = stream.de_bytes(f"architecture[{i}]")
            posture = stream.word(f"posture[{i}]")
            rows.append((active, player_type, civilization, architecture, posture))
        civ_locks = [stream.word(f"civilization_lock[{i}]") for i in range(count)]
        personality_locks = [stream.word(f"personality_lock[{i}]") for i in range(count)]
        victory = stream.word("victory_conquest", 1)
        list_at = reader.pos
        list_num = stream.word("list_num", 2, signed=True)
        avail_id = stream.word("avail_id", 2)
        old_time = stream.word("old_time_bits")
        if list_num >= 1:
            raise SaveDecodeError("native BaseScenario rejects list_num >= 1", list_at)
        member_248 = stream.short_bytes("member_248")
        ids = tuple(
            stream.word(f"resource_string_{member}")
            for member in ("188", "1a8", "1c8", "1e8", "208", "228")
        )
        texts = tuple(
            stream.short_bytes(f"resource_text_{member}")
            for member in ("188", "1a8", "1c8", "1e8", "208", "228")
        )
        strings = [
            stream.short_bytes(f"member_{member}") for member in ("290", "260", "278", "2a8")
        ]
        bitmap = stream.bitmap()
        file_names = [
            [stream.short_bytes(f"{name}_filename[{i}]") for i in range(count)]
            for name in ("build_list", "city_plan", "ai_rules")
        ]
        files: list[tuple[bytes, ...]] = []
        for i in range(count):
            sizes = []
            for name in ("build_list", "city_plan", "ai_rules"):
                size_at = reader.pos
                size = stream.word(f"{name}_size[{i}]", signed=True)
                # 140d83a60 resizes to signed size then 140d76d30 enforces this
                # byte-array bound. Negative sizes cannot form a valid vector.
                if not 0 <= size <= 0xA00000:
                    raise SaveDecodeError("invalid embedded scenario file size", size_at)
                sizes.append(size)
            files.append(
                tuple(
                    stream.blob(f"{name}_data[{i}]", size)
                    for name, size in zip(
                        ("build_list", "city_plan", "ai_rules"), sizes, strict=True
                    )
                )
            )
        ai_types = [stream.word(f"ai_rules_type[{i}]", 1) for i in range(count)]
        tail = stream.word("tail_word")
        players = tuple(
            SavedScenarioPlayer(
                names[i],
                name_ids[i],
                *rows[i],
                civ_locks[i],
                personality_locks[i],
                file_names[0][i],
                file_names[1][i],
                file_names[2][i],
                files[i][0],
                files[i][1],
                files[i][2],
                ai_types[i],
            )
            for i in range(count)
        )
        return SavedScenarioBase(
            start,
            reader.pos,
            version,
            count,
            gaia,
            players,
            victory,
            list_num,
            avail_id,
            old_time,
            member_248,
            ids,
            texts,
            strings[0],
            strings[1],
            strings[2],
            strings[3],
            bitmap,
            tail,
            tuple(stream.fields),
            reader.data[start : reader.pos],
        )
    except SaveDecodeError:
        reader.pos = start
        raise
