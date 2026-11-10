"""Game audio for the spectator: Wwise event ids to browser-playable files.

The game streams ``SoundEvent.eventId`` -- a Wwise ID, i.e. the 32-bit FNV-1
hash of a lowercase event name. Resolving one to sound means walking the
SoundBank hierarchy (HIRC) inside the installed ``wwise/*.pck`` packages:

    Event -> its Play actions -> target node -> Sound (media id) or a container
    (Random/Sequence, Switch, Layer) whose children are recursed into.

Containers are resolved by inverting each node's ``DirectParentID`` rather
than parsing every container's child list, which keeps the parser to a short
prefix of each object. A switch container (e.g. per-civ unit voices) is
flattened, so callers choose among all variants with ``variant``.

The media itself (Wwise Vorbis/Opus inside RIFF ``.wem``) is decoded by the
external ``vgmstream-cli`` and, when ``ffmpeg`` exists, re-encoded to Ogg Opus.
Without vgmstream the library still resolves ids but yields no audio.

Layouts verified against the DE install (AKPK v1, BKHD bank version 172).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

#: Bumped whenever the on-disk index layout or parsing rules change.
INDEX_VERSION = 1

#: Codec-plugin type nibble of a Sound's ``ulPluginID`` (vs. 2 = source plugin,
#: whose parameter block precedes the node params).
_PLUGIN_SOURCE = 2
#: ``AkActionType`` of a Play action.
_ACTION_PLAY = 0x0403
#: HIRC object types.
_HIRC_SOUND, _HIRC_ACTION, _HIRC_EVENT = 2, 3, 4
_CONTAINERS = frozenset({5, 6, 9})  # random/sequence, switch, layer
_NODES = frozenset({_HIRC_SOUND, 5, 6, 7, 9})

#: Transcoder: raw ``.wem`` bytes -> (audio bytes, mime type), or None on failure.
Transcoder = Callable[[bytes], tuple[bytes, str] | None]


def fnv1_32(name: str) -> int:
    """Wwise short ID of ``name``: FNV-1 32-bit over its lowercase bytes."""
    h = 2166136261
    for c in name.lower().encode():
        h = ((h * 16777619) & 0xFFFFFFFF) ^ c
    return h


#: Chat taunts 1-105. The game formats ``Play_%sTaunt_%02d`` (empty prefix for
#: the standard set); all 105 live in ``wwise/en/Base.pck``.
TAUNT_EVENTS: dict[int, int] = {n: fnv1_32(f"Play_Taunt_{n:02d}") for n in range(1, 106)}

#: Gameplay notifications, keyed as in ``resources/_common/dat/sounds.json``
#: (whose ``name`` fields are the event names). There is no generic "unit
#: trained" event: each unit's own "created" event arrives as a SoundEvent.
NOTIFICATION_EVENTS: dict[str, int] = {
    key: fnv1_32(name)
    for key, name in {
        "age_up": "Play_Age_Up",
        "tech_researched": "Play_Technology_Researched",
        "townbell_start": "Play_Townbell_Start",
        "under_attack": "Play_Under_Attack",
        "under_attack_town": "Play_Town_Under_Attack",
        "under_attack_conversion": "Play_Monk_Attacking",
        "under_attack_animals": "Play_Animal_Attack",
        "victory": "Play_Victory",
        "defeat": "Play_Defeat",
        "player_eliminated": "Play_Player_Eliminated",
        "wonder_started": "Play_Wonder_Started",
        "wonder_completed": "Play_Wonder_Completed",
        "wonder_destroyed": "Play_Wonder_Destroyed",
        "tribute": "Play_Tribute",
        "chat": "Play_Chat_Received",
        "flare": "Play_Flare",
        "pop_capped": "Play_Population_Capped",
        "pop_warning": "Play_Population_Warning",
        "treasure_pickup": "Play_Relic_Pickup",
        "capture_complete": "Play_Capture_Everything",
        "got_converted": "Play_Monk_Convert_Complete",
        "market_buy": "Play_Market_Buy",
        "market_sell": "Play_Market_Sell",
        "farm_depleted": "Play_Farm_Depleted",
        "civ_jingle": "Play_Civilization_Jingle",
    }.items()
}

#: World sounds the spectator plays on its own (no stream event carries them).
#: Their names were found by hashing candidate names against the installed
#: banks' event table (every one resolves to media in the DE install).
#:
#: * ``ambience_<biome>``: the outdoor ambience beds, one event per biome name
#:   (``Forest``, ``Plains``...); each is a container of many short layers.
#: * ``villager_<work>``: villager work loops (chopping, mining, building...).
#: * ``weapon_<kind>``: attack swings/shots and impacts, for fights on screen
#:   when the stream does not say which attack sprite frame fired.
WORLD_EVENTS: dict[str, int] = {
    key: fnv1_32(name)
    for key, name in {
        "ambience_forest": "Forest",
        "ambience_plains": "Plains",
        "ambience_desert": "Desert",
        "ambience_snow": "Snow",
        "ambience_jungle": "Jungle",
        "ambience_lake": "Lake",
        "ambience_ocean": "Ocean",
        "seagulls": "Play_Seagulls",
        "hawk": "Play_Hawk_Idle",
        "villager_wood": "Play_Villager_Wood_Chop",
        "villager_mining": "Play_Villager_Mining",
        "villager_build": "Play_Villager_Build",
        "villager_farm": "Play_Villager_Farm",
        "villager_forage": "Play_Villager_Forage",
        "villager_fishing": "Play_Villager_Fishing",
        "weapon_swing_club": "Play_Swing_Club",
        "weapon_swing_mace": "Play_Swing_Mace",
        "weapon_swing_spear": "Play_Swing_Spear",
        "weapon_swing_dagger": "Play_Swing_Dagger",
        "weapon_hit_club": "Play_Hit_Club",
        "weapon_shoot_bow": "Play_Shoot_Bow",
        "weapon_shoot_crossbow": "Play_Shoot_Crossbow",
        "weapon_shoot_hand_cannon": "Play_Shoot_Hand_Cannon",
        "weapon_impact_bullet": "Play_Impact_Bullet",
        "weapon_mangonel": "Play_Attack_Mangonel",
        "weapon_scorpion": "Play_Attack_Scorpion",
        "weapon_trebuchet": "Play_Attack_Trebuchet",
        "weapon_bombard": "Play_Attack_Bombard_Cannon",
    }.items()
}
#: The burning-building loop: the main sound event of the flame sprites that a
#: building's damage graphics place (``FLM*``); its event name is not known.
WORLD_EVENTS["building_fire"] = 3992053517
#: ``/audio/notify/<key>`` serves every named event, notifications and world sounds.
NOTIFICATION_EVENTS.update(WORLD_EVENTS)


def taunt_event(n: int) -> int | None:
    """Event id of chat taunt ``n`` (1-105), else None."""
    return TAUNT_EVENTS.get(n)


# --------------------------------------------------------------------------- #
# Container parsing (pure functions over bytes / file handles)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PckEntry:
    id: int
    offset: int  # absolute byte offset in the .pck
    size: int


def read_akpk(f: BinaryIO) -> tuple[list[PckEntry], list[PckEntry]]:
    """(soundbanks, streamed files) from an AKPK package header."""
    head = f.read(28)
    if len(head) < 28 or head[:4] != b"AKPK":
        raise ValueError("not an AKPK package")
    _hsize, _ver, lang_size, bank_size, stream_size, _ext = struct.unpack_from("<6I", head, 4)
    f.seek(28 + lang_size)
    banks = _lut(f.read(bank_size))
    streams = _lut(f.read(stream_size))
    return banks, streams


def _lut(data: bytes) -> list[PckEntry]:
    if len(data) < 4:
        return []
    (count,) = struct.unpack_from("<I", data)
    if count == 0:
        return []
    width = (len(data) - 4) // count
    # 20 bytes: u32 id; 24 bytes: u64 id (newer externals tables). Then
    # block size, file size, start block, language id.
    idfmt = {20: "<I", 24: "<Q"}.get(width)
    if idfmt is None:
        raise ValueError(f"unsupported AKPK entry size {width}")
    idlen = struct.calcsize(idfmt)
    out = []
    for i in range(count):
        o = 4 + i * width
        (eid,) = struct.unpack_from(idfmt, data, o)
        block, size, start, _lang = struct.unpack_from("<4I", data, o + idlen)
        out.append(PckEntry(eid, start * max(block, 1), size))
    return out


@dataclass(slots=True)
class BankContents:
    version: int
    media: list[PckEntry]  # embedded (DIDX/DATA) media, absolute offsets
    hirc: bytes


def read_bank(f: BinaryIO, offset: int, size: int) -> BankContents:
    """Seek through one bank's chunks, reading only BKHD, DIDX and HIRC."""
    version = 0
    didx: list[tuple[int, int, int]] = []
    data_at: int | None = None
    hirc = b""
    pos = 0
    while pos + 8 <= size:
        f.seek(offset + pos)
        tag, length = struct.unpack("<4sI", f.read(8))
        if tag == b"BKHD":
            (version,) = struct.unpack("<I", f.read(4))
        elif tag == b"DIDX":
            raw = f.read(length)
            didx = [struct.unpack_from("<3I", raw, i) for i in range(0, length - 11, 12)]
        elif tag == b"DATA":
            data_at = offset + pos + 8
        elif tag == b"HIRC":
            hirc = f.read(length)
        pos += 8 + length
    media = (
        [PckEntry(mid, data_at + off, sz) for mid, off, sz in didx] if data_at is not None else []
    )
    return BankContents(version, media, hirc)


def iter_hirc(hirc: bytes) -> Iterator[tuple[int, int, bytes]]:
    """(type, object id, body including the id) for every HIRC object."""
    if len(hirc) < 4:
        return
    (count,) = struct.unpack_from("<I", hirc)
    o = 4
    for _ in range(count):
        if o + 9 > len(hirc):
            return
        kind = hirc[o]
        (length,) = struct.unpack_from("<I", hirc, o + 1)
        body = hirc[o + 5 : o + 5 + length]
        if len(body) >= 4:
            yield kind, struct.unpack_from("<I", body)[0], body
        o += 5 + length


def event_actions(body: bytes) -> list[int]:
    """Action ids of an Event body.

    v172 has 7 bytes between the id and a u8 action count; older banks put a
    u32 (or var-length u8) count straight after the id. Pick whichever layout
    accounts for the body length exactly.
    """
    # v172's 7 bytes are zero, so the u32 layout can only match a legacy body.
    for count_at, count_fmt in ((4, "<I"), (11, "<B"), (4, "<B")):
        if len(body) <= count_at:
            continue
        (n,) = struct.unpack_from(count_fmt, body, count_at)
        start = count_at + struct.calcsize(count_fmt)
        if start + 4 * n == len(body):
            return list(struct.unpack_from(f"<{n}I", body, start))
    return []


def play_target(body: bytes) -> int | None:
    """Target node of an Action body if it is a Play action."""
    if len(body) < 10:
        return None
    kind, target = struct.unpack_from("<HI", body, 4)
    return target if kind == _ACTION_PLAY else None


def sound_source(body: bytes) -> int | None:
    """Media (source) id of a Sound body: AkBankSourceData's sourceID."""
    if len(body) < 13:
        return None
    return int(struct.unpack_from("<I", body, 9)[0])


def node_parent(kind: int, body: bytes) -> int | None:
    """``DirectParentID`` from a node's NodeBaseParams (v172 layout).

    NodeBaseParams opens with: override-FX u8, FX count u8 (+ bypass u8 and
    6 bytes per FX), override-metadata u8, metadata count u8 (+ 6 bytes each),
    override bus u32, direct parent u32. A Sound prefixes it with 18 bytes of
    AkBankSourceData (plus a sized parameter block for source plugins).
    """
    try:
        p = 4
        if kind == _HIRC_SOUND:
            (plugin,) = struct.unpack_from("<I", body, 4)
            p = 22
            if plugin & 0xF == _PLUGIN_SOURCE:
                (psize,) = struct.unpack_from("<I", body, p)
                p += 4 + psize
        p += 1
        nfx = body[p]
        p += 1
        if nfx:
            p += 1 + 6 * nfx
        p += 1
        nmeta = body[p]
        p += 1 + 6 * nmeta
        return int(struct.unpack_from("<I", body, p + 4)[0])
    except (IndexError, struct.error):
        return None


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _Index:
    media: dict[int, tuple[str, int, int, bool]]  # id -> (pck relpath, offset, size, streamed)
    events: dict[int, list[int]]  # event id -> play targets
    sounds: dict[int, int]  # sound id -> media id
    containers: dict[int, list[int]]  # container id -> child node ids


def build_index(wwise: Path, files: list[Path]) -> _Index:
    media: dict[int, tuple[str, int, int, bool]] = {}
    actions: dict[int, int | None] = {}
    events: dict[int, list[int]] = {}
    sounds: dict[int, int] = {}
    kinds: dict[int, int] = {}
    parents: dict[int, int] = {}

    def add_media(mid: int, rel: str, entry: PckEntry, streamed: bool) -> None:
        # A full streamed file beats a bank's (possibly prefetch-only) copy.
        old = media.get(mid)
        if old is None or (streamed, entry.size) > (old[3], old[2]):
            media[mid] = (rel, entry.offset, entry.size, streamed)

    for path in files:
        rel = path.relative_to(wwise).as_posix()
        with path.open("rb") as f:
            try:
                banks, streams = read_akpk(f)
            except ValueError:
                continue
            for entry in streams:
                add_media(entry.id, rel, entry, True)
            for bank_entry in banks:
                bank = read_bank(f, bank_entry.offset, bank_entry.size)
                for entry in bank.media:
                    add_media(entry.id, rel, entry, False)
                for kind, oid, body in iter_hirc(bank.hirc):
                    if kind == _HIRC_EVENT:
                        events.setdefault(oid, event_actions(body))
                    elif kind == _HIRC_ACTION:
                        actions.setdefault(oid, play_target(body))
                    elif kind in _NODES:
                        kinds.setdefault(oid, kind)
                        if kind == _HIRC_SOUND:
                            src = sound_source(body)
                            if src is not None:
                                sounds.setdefault(oid, src)
                        parent = node_parent(kind, body)
                        if parent:
                            parents.setdefault(oid, parent)

    containers: dict[int, list[int]] = {}
    for child, parent in sorted(parents.items()):
        if kinds.get(parent) in _CONTAINERS:
            containers.setdefault(parent, []).append(child)
    event_targets = {
        eid: [t for a in acts if (t := actions.get(a)) is not None] for eid, acts in events.items()
    }
    return _Index(media, event_targets, sounds, containers)


def _fingerprint(wwise: Path, files: list[Path]) -> list[list[Any]]:
    out: list[list[Any]] = []
    for p in files:
        st = p.stat()
        out.append([p.relative_to(wwise).as_posix(), st.st_size, st.st_mtime_ns])
    return out


def _dump(index: _Index, fingerprint: list[list[Any]]) -> dict[str, Any]:
    return {
        "version": INDEX_VERSION,
        "sources": fingerprint,
        "media": {str(k): list(v) for k, v in index.media.items()},
        "events": {str(k): v for k, v in index.events.items()},
        "sounds": {str(k): v for k, v in index.sounds.items()},
        "containers": {str(k): v for k, v in index.containers.items()},
    }


def _load(doc: dict[str, Any]) -> _Index:
    return _Index(
        {int(k): (str(v[0]), int(v[1]), int(v[2]), bool(v[3])) for k, v in doc["media"].items()},
        {int(k): [int(x) for x in v] for k, v in doc["events"].items()},
        {int(k): int(v) for k, v in doc["sounds"].items()},
        {int(k): [int(x) for x in v] for k, v in doc["containers"].items()},
    )


# --------------------------------------------------------------------------- #
# Transcoding
# --------------------------------------------------------------------------- #


def find_vgmstream() -> Path | None:
    """``$VANTAGE_VGMSTREAM``, ``~/opt/vgmstream/vgmstream-cli[.exe]``, or PATH."""
    env = os.environ.get("VANTAGE_VGMSTREAM")
    candidates = [Path(env)] if env else []
    exe = "vgmstream-cli.exe" if sys.platform == "win32" else "vgmstream-cli"
    candidates.append(Path.home() / "opt" / "vgmstream" / exe)
    found = shutil.which("vgmstream-cli")
    if found:
        candidates.append(Path(found))
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def transcode(wem: bytes, vgmstream: Path, ffmpeg: str | None) -> tuple[bytes, str] | None:
    """Decode a ``.wem`` to WAV with vgmstream, then to Ogg Opus if ffmpeg exists."""
    with tempfile.TemporaryDirectory(prefix="vantage-audio-") as tmp:
        src, wav, ogg = Path(tmp, "in.wem"), Path(tmp, "out.wav"), Path(tmp, "out.ogg")
        src.write_bytes(wem)
        try:
            subprocess.run(
                [str(vgmstream), "-o", str(wav), str(src)],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if not wav.is_file():
            return None
        if ffmpeg:
            try:
                subprocess.run(
                    [ffmpeg, "-v", "error", "-y", "-i", str(wav), *_OPUS_ARGS, str(ogg)],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                if ogg.is_file() and ogg.stat().st_size > 0:
                    return ogg.read_bytes(), "audio/ogg"
            except (OSError, subprocess.SubprocessError):
                pass
        return wav.read_bytes(), "audio/wav"


def _default_transcoder(vgmstream: Path, ffmpeg: str | None) -> Transcoder:
    def run(wem: bytes) -> tuple[bytes, str] | None:
        return transcode(wem, vgmstream, ffmpeg)

    return run


_OPUS_ARGS = ("-c:a", "libopus", "-b:a", "64k")
_EXT = {"audio/ogg": ".ogg", "audio/wav": ".wav"}
_MIME = {v: k for k, v in _EXT.items()}


# --------------------------------------------------------------------------- #
# Library
# --------------------------------------------------------------------------- #


class AudioLibrary:
    """Lazy, cached event -> media -> audio resolution over one game install."""

    def __init__(
        self,
        game_dir: Path | None,
        cache_dir: Path,
        *,
        language: str = "en",
        transcoder: Transcoder | None = None,
    ) -> None:
        self.wwise = game_dir / "wwise" if game_dir is not None else None
        self.language = language
        self.cache = cache_dir / "audio"
        self._game_dir = game_dir
        self._cache_dir = cache_dir
        self._others: dict[str, AudioLibrary] = {}
        if transcoder is None:
            vgm = find_vgmstream()
            if vgm is not None:
                transcoder = _default_transcoder(vgm, shutil.which("ffmpeg"))
        self._transcoder = transcoder
        self._index: _Index | None = None
        self._lock = threading.Lock()
        self._media_locks: dict[int, threading.Lock] = {}
        self._failed: set[int] = set()
        self._resolved: dict[int, list[int]] = {}

    @property
    def available(self) -> bool:
        return self._transcoder is not None and bool(self._files())

    def _files(self) -> list[Path]:
        if self.wwise is None or not self.wwise.is_dir():
            return []
        files = sorted(self.wwise.glob("*.pck"))
        files += sorted((self.wwise / self.language).glob("*.pck"))
        return files

    def languages(self) -> list[str]:
        """Voice languages installed (``wwise/<lang>/`` folders holding packages)."""
        if self.wwise is None or not self.wwise.is_dir():
            return []
        return sorted(d.name for d in self.wwise.iterdir() if d.is_dir() and any(d.glob("*.pck")))

    def resolve_language(self, requested: str | None) -> str:
        """The installed language closest to ``requested`` (e.g. ``pt-BR`` -> ``pt``).

        Falls back to this library's own language when nothing matches.
        """
        if not requested:
            return self.language
        have = {lang.lower(): lang for lang in self.languages()}
        want = requested.lower().replace("_", "-")
        for cand in (want, want.split("-")[0], want.split("-")[-1]):
            if cand in have:
                return have[cand]
        return self.language

    def for_language(self, requested: str | None) -> AudioLibrary:
        """The library for another voice language (taunts, unit voices), cached.

        Its media cache is separate: Wwise reuses media ids across languages.
        """
        lang = self.resolve_language(requested)
        if lang == self.language:
            return self
        with self._lock:
            other = self._others.get(lang)
            if other is None:
                other = AudioLibrary(
                    self._game_dir,
                    self._cache_dir / "audio-lang" / lang,
                    language=lang,
                    transcoder=self._transcoder,
                )
                self._others[lang] = other
            return other

    def _get_index(self) -> _Index | None:
        with self._lock:
            if self._index is not None:
                return self._index
            files = self._files()
            if self.wwise is None or not files:
                return None
            fp = _fingerprint(self.wwise, files)
            path = self.cache / f"index-{self.language}.json"
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if doc.get("version") == INDEX_VERSION and doc.get("sources") == fp:
                    self._index = _load(doc)
                    return self._index
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                pass
            self._index = build_index(self.wwise, files)
            self.cache.mkdir(parents=True, exist_ok=True)
            # Multiple libraries or server processes can build the same cache
            # at once. Give each writer its own file before the atomic replace.
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=self.cache)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(_dump(self._index, fp), stream, separators=(",", ":"))
                os.replace(tmp_name, path)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp_name)
            return self._index

    def event_media(self, event_id: int) -> list[int]:
        """Candidate media ids an event may play, in a stable order."""
        index = self._get_index()
        if index is None:
            return []
        with self._lock:
            cached = self._resolved.get(event_id)
        if cached is not None:
            return list(cached)
        out: list[int] = []
        seen: set[int] = set()

        def walk(node: int, depth: int) -> None:
            if node in seen or depth > 32:
                return
            seen.add(node)
            src = index.sounds.get(node)
            if src is not None:
                if src in index.media and src not in out:
                    out.append(src)
                return
            for child in index.containers.get(node, ()):
                walk(child, depth + 1)

        for target in index.events.get(event_id, ()):
            walk(target, 0)
        with self._lock:
            self._resolved[event_id] = out
        return list(out)

    def _wem(self, media_id: int) -> bytes | None:
        index = self._get_index()
        if index is None or self.wwise is None:
            return None
        loc = index.media.get(media_id)
        if loc is None:
            return None
        rel, offset, size, _streamed = loc
        try:
            with (self.wwise / rel).open("rb") as f:
                f.seek(offset)
                data = f.read(size)
        except OSError:
            return None
        return data if len(data) == size else None

    def media_audio(self, media_id: int) -> tuple[bytes, str] | None:
        """Decoded audio for one media id, cached under ``cache_dir/audio``."""
        for ext, mime in _MIME.items():
            hit = self.cache / f"{media_id}{ext}"
            if hit.is_file():
                return hit.read_bytes(), mime
        if self._transcoder is None:
            return None
        with self._lock:
            if media_id in self._failed:
                return None
            lock = self._media_locks.setdefault(media_id, threading.Lock())
        with lock:
            for ext, mime in _MIME.items():  # another thread may have finished it
                hit = self.cache / f"{media_id}{ext}"
                if hit.is_file():
                    return hit.read_bytes(), mime
            wem = self._wem(media_id)
            got = self._transcoder(wem) if wem is not None else None
            if got is None or got[1] not in _EXT:
                with self._lock:
                    self._failed.add(media_id)
                return None
            audio, mime = got
            self.cache.mkdir(parents=True, exist_ok=True)
            out = self.cache / f"{media_id}{_EXT[mime]}"
            tmp = out.with_suffix(".part")
            tmp.write_bytes(audio)
            tmp.replace(out)
            return audio, mime

    def event_audio(
        self, event_id: int, variant: int = 0, language: str | None = None
    ) -> tuple[bytes, str] | None:
        """Audio for an event, choosing candidate ``variant % n``.

        ``language`` picks another installed voice language (see
        :meth:`for_language`); missing languages fall back to this one.
        """
        if language:
            lib = self.for_language(language)
            if lib is not self:
                return lib.event_audio(event_id, variant)
        cands = self.event_media(event_id)
        if not cands:
            return None
        return self.media_audio(cands[variant % len(cands)])
