"""Stdlib-only reader for AoE2 DE ``.aoe2record`` headers (Vantage replay browser).

Layout, as read from the bytes of current replays (``VER 9.4``, builds
48086 / 48987 / 54800; nothing here is taken from another parser)::

    u32 header_end         absolute offset where the compressed header ends
    u32 next_chapter       absolute offset of the first saved chapter (0 = none)
    raw DEFLATE header     "VER 9.4\\0", save version, DE lobby block, then the
                           AI / map / game-state sections (megabytes; not read)
    body                   32-byte meta, then an operation stream

Only the DE lobby block (version, settings, eight player slots, resource
strings) is decoded; it sits in the first few KB of the decompressed header.
Field semantics marked *corroborated* were checked against the settings
summary the game writes into the same header ("Location: Arabia",
"Difficulty Level: Extreme", "Teams Locked: No", ...) or against the live game
stream; the rest are positional and only known to round-trip sensibly. The
eight lobby checkboxes (lock teams, team positions, shared exploration,
handicap, lock speed, cheats, turbo, full tech tree) are *confirmed*: two real
lobbies with every box inverted read back inverted
(``tests/fixtures/replay_ror_*``). ``multiplayer`` and ``ranked`` are
confirmed on public ranked 1v1 replays (``tests/fixtures/replay_mp_ranked_*``).

Ratings: the post-game trailer holds every player's ladders (id, rank,
rating; see ``_leaderboards``) — the ranked ladder in ranked games, the
human's own ladders (rank -1) in single-player games. It carries no outcome: Action ``0x0B``
(5 bytes: type, player number, player id, disconnected, pad) is a resignation;
the winner is the side left once all others resigned.

Body operations (u32 type first): 1 action (u32 len, payload, u32 absolute
game time ms), 2 sync (u32 ms increment; when followed by a u32 0 it carries a
fixed 360-byte checksum block), 3 view lock (12 bytes), 4 chat (i32 marker,
u32 len, JSON), 6 post-game (u32 final game time ms, then a short trailer).
A saved chapter interrupts the stream at ``next_chapter`` as
``u32 resume_offset, u32 next_chapter`` followed by a compressed save.
"""

from __future__ import annotations

import contextlib
import json
import re
import struct
import zlib
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from vantage.gamedata import GameData

_STR_MARK = b"\x60\x0a"
_SEPARATOR = 155555  # a3 5f 02 00, between lobby sub-blocks
_HEADER_PREFIX = 1 << 16  # decompressed bytes needed for the DE lobby block
_HEADER_COMPRESSED_READ = 1 << 18
_BODY_META = 32
_CHECKSUM_BLOCK = 360
_OP_ACTION, _OP_SYNC, _OP_VIEWLOCK, _OP_CHAT, _OP_POSTGAME = 1, 2, 3, 4, 6
_ACTION_RESIGN, _RESIGN_LEN = 0x0B, 5
_PLAYER_SLOTS = 8
_RESOURCE_RE = re.compile(r"^([A-Z]+):([A-Z_]+):(.*):(.*):(true|false)$")
_FILENAME_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+\.\d+)")

#: Corroborated: -1 and 1 against "Difficulty Level:"; the rest follow the
#: classic 0..4 ordering.
DIFFICULTIES = {-1: "Extreme", 0: "Hardest", 1: "Hard", 2: "Moderate", 3: "Standard", 4: "Easiest"}
#: Corroborated: 0 (random-map games) and 3 (a scenario recording).
GAME_TYPES = {0: "Random Map", 1: "Regicide", 2: "Death Match", 3: "Scenario"}
#: Lobby speed multipliers as stored (1.69 is shown as "Normal").
SPEEDS = {1.0: "Slow", 1.5: "Casual", 1.69: "Normal", 2.0: "Fast"}
_PLAYER_HUMAN, _PLAYER_AI = 2, 4


class ReplayError(ValueError):
    """The file is not a DE replay this reader understands, or is corrupt."""


class _Short(ReplayError):
    """Ran off the end of the available bytes."""


@dataclass(frozen=True)
class ReplayPlayer:
    number: int  # lobby player number (1-based)
    slot: int  # header slot index (0-7)
    name: str  # display name: the human's name, the AI persona, or the custom script
    civ_id: int
    color_id: int  # 0 blue, 1 red, 2 green, 3 yellow, 4 teal, 5 purple, 6 grey, 7 orange
    team: int  # 0 = no team, 1..4 = lobby teams (stored +1)
    is_human: bool
    ai_name: str  # lobby AI persona ("Knut the Great"); "" for humans
    ai_script: str  # AI script name ("PromiDE", "Immortal v0d10f"); "" for humans
    custom_ai: bool  # script is not a built-in AI
    profile_id: int | None  # platform profile id (humans only)
    handicap: int  # percent
    #: Rating on the leaderboard this game belongs to (ranked games), else the
    #: player's 1v1/team random-map ladder rating; from the post-game record.
    elo: int | None = None
    #: Every ladder in the post-game record: (leaderboard id, rank, rating).
    #: Leaderboard ids: 3 = random map 1v1, 4 = random map team.
    ratings: tuple[tuple[int, int, int], ...] = ()


@dataclass(frozen=True)
class ReplayInfo:
    path: str
    file_size: int
    version: str  # "VER 9.4"
    save_version: float  # e.g. 68.9
    build: int | None  # e.g. 54800 (matches the filename's third component)
    game_version: str | None  # from the filename, e.g. "101.103.54800.0"
    started_at: int | None  # unix seconds, written when the match started
    dlc_ids: tuple[int, ...] = ()
    difficulty_id: int | None = None
    difficulty: str | None = None
    map_id: int | None = None
    map_name: str | None = None
    map_size: int | None = None  # tiles per side
    rms_file: str | None = None  # lobby custom RMS (remembered even when unused)
    scenario_file: str | None = None
    custom_map: bool = False
    game_type_id: int | None = None
    game_type: str | None = None
    victory_type_id: int | None = None
    starting_resources_id: int | None = None
    starting_age_id: int | None = None
    ending_age_id: int | None = None
    reveal_map_id: int | None = None
    speed: float | None = None
    speed_name: str | None = None
    population: int | None = None
    treaty_minutes: int | None = None
    num_players: int | None = None
    lock_teams: bool | None = None
    lock_speed: bool | None = None
    multiplayer: bool | None = None
    cheats: bool | None = None
    all_techs: bool | None = None
    random_positions: bool | None = None
    turbo: bool | None = None
    shared_exploration: bool | None = None
    team_positions: bool | None = None
    handicap: bool | None = None
    ranked: bool | None = None
    players: tuple[ReplayPlayer, ...] = ()
    duration_ms: int | None = None  # game clock at the end of the recording
    recorded_ms: int | None = None  # span covered by this file (< duration if resumed)
    has_postgame: bool = False  # the recording ended with a post-game record
    chapters: int = 0
    #: Resign actions in order: (player number, disconnected, game ms).
    resigned: tuple[tuple[int, bool, int], ...] = ()
    #: Player numbers of the side left standing in a finished game; empty when
    #: unknown (the recording stops early, or more than one side remains).
    winners: tuple[int, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def compatible(self) -> str:
        """Short version tag: replays only play back on a matching build."""
        build = self.build if self.build is not None else "?"
        return f"{self.version} / save {self.save_version:g} / build {build}"

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["players"] = [
            {**asdict(p), "ratings": [list(r) for r in p.ratings]} for p in self.players
        ]
        out["dlc_ids"] = list(self.dlc_ids)
        out["warnings"] = list(self.warnings)
        out["resigned"] = [list(r) for r in self.resigned]
        out["winners"] = list(self.winners)
        out["compatible"] = self.compatible
        return out


class _Reader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def _take(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        if self.pos + size > len(self.data):
            raise _Short(f"truncated at {self.pos:#x}")
        value = struct.unpack_from(fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def u8(self) -> int:
        return int(self._take("<B"))

    def u32(self) -> int:
        return int(self._take("<I"))

    def i32(self) -> int:
        return int(self._take("<i"))

    def f32(self) -> float:
        return float(self._take("<f"))

    def skip(self, n: int) -> None:
        if self.pos + n > len(self.data):
            raise _Short(f"truncated at {self.pos:#x}")
        self.pos += n

    def flags(self, n: int) -> list[bool]:
        return [self.u8() != 0 for _ in range(n)]

    def string(self) -> str:
        """DE length-prefixed string: ``60 0a``, u16 length, bytes."""
        if self.data[self.pos : self.pos + 2] != _STR_MARK:
            raise ReplayError(f"expected string marker at {self.pos:#x}")
        self.pos += 2
        n = int(self._take("<H"))
        if self.pos + n > len(self.data):
            raise _Short(f"truncated string at {self.pos:#x}")
        raw = self.data[self.pos : self.pos + n]
        self.pos += n
        return raw.decode("utf-8", "replace")

    def separator(self) -> None:
        at = self.pos
        if self.u32() != _SEPARATOR:
            raise ReplayError(f"lost sync: no separator at {at:#x}")


def _read_header_prefix(path: Path) -> tuple[bytes, int, int, int]:
    """(decompressed header prefix, header_end, next_chapter, file size)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            head = fh.read(8)
            if len(head) < 8:
                raise ReplayError("file too short")
            header_end, next_chapter = struct.unpack("<II", head)
            if not 8 < header_end <= size:
                raise ReplayError(f"bad header length {header_end}")
            compressed = fh.read(min(header_end - 8, _HEADER_COMPRESSED_READ))
    except OSError as exc:
        raise ReplayError(str(exc)) from exc
    try:
        data = zlib.decompressobj(-15).decompress(compressed, _HEADER_PREFIX)
    except zlib.error as exc:
        raise ReplayError(f"header does not inflate: {exc}") from exc
    if not data.startswith(b"VER "):
        raise ReplayError("not a DE recorded game (no VER tag)")
    return data, header_end, next_chapter, size


def _parse_player(r: _Reader, slot: int) -> tuple[int, ReplayPlayer]:
    """One lobby slot; returns (slot type, player). Type 1 = empty/closed."""
    r.u32()  # dlc id
    color_id = r.i32()
    r.u8()  # selected colour
    r.u8()  # selected team
    team = r.u8()  # resolved team, +1 encoded
    r.skip(9)
    civ_id = r.u32()
    r.skip(4 * r.u32())  # random-civ pool
    ai_script = r.string()
    r.u8()  # AI civ-name index
    ai_name = r.string()
    name = r.string()
    r.string()  # second copy of the player name
    kind = r.u32()
    profile_id = r.i32()
    r.i32()
    number = r.i32()
    r.u8()
    custom_ai = r.u8() != 0
    r.i32()
    handicap = r.u32()
    r.i32()
    r.string()
    is_human = kind == _PLAYER_HUMAN
    # A custom script's persona name is a random civ leader; the game shows the
    # script name instead (corroborated against the live stream).
    ai_display = ai_script if custom_ai and ai_script else (ai_name or ai_script)
    display = name if is_human else ai_display
    player = ReplayPlayer(
        number=number,
        slot=slot,
        name=display,
        civ_id=civ_id,
        color_id=color_id,
        team=max(team - 1, 0),
        is_human=is_human,
        ai_name="" if is_human else ai_name,
        ai_script="" if is_human else ai_script,
        custom_ai=custom_ai,
        profile_id=profile_id if is_human and profile_id > 0 else None,
        handicap=handicap,
    )
    return kind, player


def _parse_lobby(data: bytes, out: dict[str, Any], warnings: list[str]) -> None:
    r = _Reader(data)
    out["version"] = data[:8].split(b"\0", 1)[0].decode("ascii", "replace")
    r.pos = 8
    legacy = r.f32()
    if legacy == -1.0:
        out["save_version"] = round(r.u32() / 65536, 2)  # 16.16 fixed point
    else:
        out["save_version"] = round(legacy, 2)
    raw_build = r.u32()
    out["build"] = raw_build & 0x1FFFF  # stored with bit 17 set
    out["started_at"] = r.u32() or None
    r.f32()
    r.u32()
    r.u32()
    out["dlc_ids"] = tuple(r.u32() for _ in range(r.u32()))

    out["difficulty_id"] = difficulty = r.i32()
    out["difficulty"] = DIFFICULTIES.get(difficulty)
    out["map_size"] = r.u32()
    r.u32()  # selected map id
    out["map_id"] = r.i32()  # resolved map id
    out["reveal_map_id"] = r.i32()
    out["victory_type_id"] = r.u32()
    out["starting_resources_id"] = r.i32()
    out["starting_age_id"] = r.i32()
    out["ending_age_id"] = r.i32()
    out["game_type_id"] = game_type = r.u32()
    out["game_type"] = GAME_TYPES.get(game_type)
    r.separator()
    r.separator()
    speed = round(r.f32(), 2)
    out["speed"], out["speed_name"] = speed, SPEEDS.get(speed)
    out["treaty_minutes"] = r.u32()
    out["population"] = r.u32()
    out["num_players"] = r.u32()
    r.u32()  # unused player colour
    r.u32()  # victory amount
    r.u8()
    r.separator()
    (
        _trade,
        _team_bonus,
        out["random_positions"],
        out["all_techs"],
        _starting_units,
        out["lock_teams"],
        out["lock_speed"],
        out["multiplayer"],
        out["cheats"],
        _record_game,
        _animals,
        _predators,
        out["turbo"],
        out["shared_exploration"],
        out["team_positions"],
    ) = r.flags(15)
    r.u32()  # sub-game mode
    r.u32()  # battle-royale time
    out["handicap"] = r.u8() != 0
    r.u8()
    r.separator()

    players: list[ReplayPlayer] = []
    try:
        for slot in range(_PLAYER_SLOTS):
            kind, player = _parse_player(r, slot)
            if kind in (_PLAYER_HUMAN, _PLAYER_AI):
                players.append(player)
    except ReplayError as exc:
        warnings.append(f"players: {exc}")
        out["players"] = tuple(players)
        return
    out["players"] = tuple(players)

    try:
        r.skip(9)
        r.flags(3)  # fog of war, cheat notifications, coloured chat
        r.separator()
        out["ranked"] = r.u8() != 0
    except ReplayError as exc:
        warnings.append(f"lobby tail: {exc}")
        return
    _scan_resources(data, r.pos, out)


def _scan_resources(data: bytes, start: int, out: dict[str, Any]) -> None:
    """Resource strings ("SOURCE:CATEGORY:file:mod:bool") follow the slots with
    irregular binary between them, so they are located by marker, not parsed."""
    end = min(len(data), start + 0x2000)
    pos = data.find(_STR_MARK, start, end)
    while pos >= 0:
        n = int.from_bytes(data[pos + 2 : pos + 4], "little")
        text = data[pos + 4 : pos + 4 + n].decode("utf-8", "replace")
        m = _RESOURCE_RE.match(text)
        if m:
            category, filename = m.group(2), m.group(3)
            if category == "RANDOM_MAPS" and filename and "rms_file" not in out:
                out["rms_file"] = filename
            elif category == "SCENARIOS" and filename and "scenario_file" not in out:
                out["scenario_file"] = filename
            pos = data.find(_STR_MARK, pos + 4 + n, end)
        else:
            pos = data.find(_STR_MARK, pos + 1, end)


def _walk_body(path: Path, header_end: int, next_chapter: int) -> dict[str, Any]:
    """Follow the operation stream for the game clock. Raises on a lost stream
    with whatever was measured attached to the exception."""
    data = path.read_bytes()
    n = len(data)
    unpack = struct.unpack_from
    pos = header_end + _BODY_META
    elapsed = 0
    base: int | None = None
    final: int | None = None
    chapters = 0
    resigns: list[tuple[int, bool, int]] = []
    result: dict[str, Any] = {}
    try:
        while pos + 4 <= n:
            if next_chapter and pos == next_chapter:
                pos, next_chapter = unpack("<II", data, pos)
                chapters += 1
                continue
            op = unpack("<I", data, pos)[0]
            pos += 4
            if op == _OP_SYNC:
                elapsed += unpack("<I", data, pos)[0]
                pos += 4
                if pos + 4 <= n and unpack("<I", data, pos)[0] == 0:
                    pos += _CHECKSUM_BLOCK
            elif op == _OP_ACTION:
                length = unpack("<I", data, pos)[0]
                if length == _RESIGN_LEN and data[pos + 4] == _ACTION_RESIGN:
                    # (player number, player id, disconnected) at the action's game time.
                    resigns.append((data[pos + 5], data[pos + 7] != 0, pos + 4 + length))
                pos += 4 + length
                if base is None:
                    # Actions carry absolute game time; a recording resumed from a
                    # save starts its sync sum at zero, so anchor on the first one.
                    base = unpack("<I", data, pos)[0] - elapsed
                pos += 4
            elif op == _OP_VIEWLOCK:
                pos += 12
            elif op == _OP_CHAT:
                pos += 4
                pos += 4 + unpack("<I", data, pos)[0]
            elif op == _OP_POSTGAME:
                final = unpack("<I", data, pos)[0]
                with contextlib.suppress(struct.error):
                    result["leaderboards"] = _leaderboards(data, pos + 4)
                break
            else:
                raise ReplayError(f"body: unknown operation {op} at {pos - 4:#x}")
        if pos > n and final is None:
            raise ReplayError("body: truncated final operation")
    except (struct.error, ReplayError) as exc:
        result["error"] = str(exc) if isinstance(exc, ReplayError) else f"body: {exc}"
    start = max(base or 0, 0)
    result["recorded_ms"] = elapsed
    result["duration_ms"] = final if final is not None else start + elapsed
    result["has_postgame"] = final is not None
    result["chapters"] = chapters
    result["resigned"] = [
        (num, disconnected, unpack("<I", data, at)[0]) for num, disconnected, at in resigns
    ]
    return result


def _leaderboards(data: bytes, pos: int) -> list[tuple[int, bool, list[tuple[int, int, int]]]]:
    """The post-game ladder block: ``u32 ?, u32 ?, u32 count`` then per ladder
    ``u32 id, u8 ?, u8 counts_for_this_game, u32 n`` and ``n`` x ``(i32 player
    index, i32 rank, i32 rating)``. Decoded from three public ranked 1v1
    replays (ratings and ranks match the public ladder) and the single-player
    corpus, where the human's ladders appear with rank -1."""
    unpack = struct.unpack_from
    pos += 8
    (count,) = unpack("<I", data, pos)
    pos += 4
    if count > 32:
        raise struct.error("implausible ladder count")
    out: list[tuple[int, bool, list[tuple[int, int, int]]]] = []
    for _ in range(count):
        lb_id, _flag, this_game, n = unpack("<IBBI", data, pos)
        pos += 10
        if n > 8:
            raise struct.error("implausible ladder size")
        rows = [unpack("<iii", data, pos + 12 * k) for k in range(n)]
        pos += 12 * n
        out.append((lb_id, bool(this_game), [(int(a), int(b), int(c)) for a, b, c in rows]))
    return out


def _with_ratings(
    players: Sequence[ReplayPlayer], ladders: Sequence[tuple[int, bool, list[tuple[int, int, int]]]]
) -> tuple[ReplayPlayer, ...]:
    """Attach ladder ratings to players (ladder rows name players by index = number - 1)."""
    team_game = len(players) > 2
    out = []
    for p in players:
        mine = [
            (lb, this, rank, rating)
            for lb, this, rows in ladders
            for idx, rank, rating in rows
            if idx == p.number - 1
        ]
        if not mine:
            out.append(p)
            continue
        preferred = (
            [m for m in mine if m[1]]
            or [m for m in mine if m[0] == (4 if team_game else 3)]
            or mine
        )
        out.append(replace(p, elo=preferred[0][3], ratings=tuple((m[0], m[2], m[3]) for m in mine)))
    return tuple(out)


def _version_from_filename(path: Path) -> str | None:
    m = _FILENAME_VERSION_RE.search(path.name)
    return m.group(1) if m else None


def read_replay(
    path: Path,
    with_duration: bool = True,
    *,
    map_names: Mapping[int, str] | None = None,
) -> ReplayInfo:
    """Read a DE ``.aoe2record``'s lobby header (and, optionally, its game clock).

    Raises :class:`ReplayError` only when the file is not a DE replay at all;
    a section that fails to decode is recorded in ``warnings`` and the fields
    read before it are kept. ``map_names`` maps map ids to display names (see
    :func:`load_map_names`).
    """
    path = Path(path)
    data, header_end, next_chapter, size = _read_header_prefix(path)
    warnings: list[str] = []
    out: dict[str, Any] = {"version": "", "save_version": 0.0, "build": None, "started_at": None}
    try:
        _parse_lobby(data, out, warnings)
    except ReplayError as exc:
        warnings.append(f"lobby: {exc}")
    if with_duration:
        body = _walk_body(path, header_end, next_chapter)
        if "error" in body:
            warnings.append(body.pop("error"))
        out.update(body)

    map_id = out.get("map_id")
    if map_names is not None and map_id is not None and map_id in map_names:
        out["map_name"] = map_names[map_id]
    elif map_names is not None and out.get("rms_file"):
        # An id the game's map list doesn't know is a custom RMS.
        out["custom_map"] = True
        out["map_name"] = Path(out["rms_file"]).stem
    ladders = out.pop("leaderboards", None)
    if ladders and out.get("players"):
        out["players"] = _with_ratings(out["players"], ladders)
    if "resigned" in out:
        out["resigned"] = tuple(tuple(r) for r in out["resigned"])
        out["winners"] = _winners(out.get("players", ()), out["resigned"], out.get("has_postgame"))
    return ReplayInfo(
        path=str(path),
        file_size=size,
        game_version=_version_from_filename(path),
        warnings=tuple(warnings),
        **out,
    )


def _winners(
    players: Sequence[ReplayPlayer], resigned: Sequence[tuple[int, bool, int]], finished: Any
) -> tuple[int, ...]:
    """The side left standing once everyone else resigned. A lobby team of 0 is
    "no team": that player is a side of their own."""
    if not finished or not players:
        return ()
    gone = {num for num, _, _ in resigned}
    sides: dict[Any, list[int]] = {}
    for pl in players:
        sides.setdefault(pl.team if pl.team > 0 else ("solo", pl.number), []).append(pl.number)
    standing = [nums for nums in sides.values() if any(n not in gone for n in nums)]
    return tuple(standing[0]) if len(standing) == 1 else ()


def load_map_names(game: GameData) -> dict[int, str]:
    """Map id -> localized name from the install's ``maps.json`` + string table."""
    path = game.dat_path("maps.json")  # Return of Rome has its own map list
    if path is None:
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("map_list", [])
    except (OSError, ValueError):
        return {}
    names: dict[int, str] = {}
    for entry in entries:
        sid, mid = entry.get("name_string_id"), entry.get("storage_id")
        if isinstance(mid, int):
            fallback = str(entry.get("script_filename") or entry.get("const_name") or mid)
            names[mid] = game.string(sid, fallback.removesuffix(".rms"))
    return names
