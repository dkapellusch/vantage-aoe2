"""vantage.audio: AKPK/BNK parsing, event resolution, caching, transcoding."""

from __future__ import annotations

import io
import json
import struct
import sys
from pathlib import Path

import pytest

from vantage import audio
from vantage.audio import (
    NOTIFICATION_EVENTS,
    TAUNT_EVENTS,
    AudioLibrary,
    event_actions,
    fnv1_32,
    iter_hirc,
    node_parent,
    play_target,
    read_akpk,
    read_bank,
    sound_source,
    taunt_event,
)

# Object ids used by the synthetic bank.
EV_RANDOM, EV_SINGLE, EV_EMPTY, EV_STOP = 1001, 1002, 1003, 1004
ACT_RANDOM, ACT_SINGLE, ACT_STOP = 2001, 2002, 2004
RANDOM, MIXER = 3001, 3500
SND_A, SND_B, SND_C = 4001, 4002, 4003
MEDIA_A, MEDIA_B, MEDIA_C = 5001, 5002, 5003  # embedded, streamed, prefetch+streamed

WEM_A = b"RIFF-embedded-A"
WEM_B = b"RIFF-streamed-B!"
WEM_C_PREFIX = b"RIFF-pre"
WEM_C_FULL = b"RIFF-prefetch-full-C"


def _obj(kind: int, oid: int, rest: bytes) -> bytes:
    body = struct.pack("<I", oid) + rest
    return struct.pack("<BI", kind, len(body)) + body


def _node_params(parent: int) -> bytes:
    # override-FX, #FX, override-metadata, #metadata, override bus, direct parent
    return bytes(4) + struct.pack("<II", 0, parent)


def _sound(oid: int, media: int, stream_type: int, parent: int) -> bytes:
    source = struct.pack("<IBIIIB", 0x00040001, stream_type, media, 0xDEADBEEF, 99, 0)
    return _obj(2, oid, source + _node_params(parent) + b"\x00" * 6)


def _event(oid: int, actions: list[int]) -> bytes:
    return _obj(4, oid, bytes(7) + struct.pack(f"<B{len(actions)}I", len(actions), *actions))


def _action(oid: int, kind: int, target: int) -> bytes:
    return _obj(3, oid, struct.pack("<HIB", kind, target, 0) + bytes(5))


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack("<I", len(payload)) + payload


def _bank() -> bytes:
    objs = [
        _event(EV_RANDOM, [ACT_RANDOM]),
        _event(EV_SINGLE, [ACT_SINGLE]),
        _event(EV_EMPTY, []),
        _event(EV_STOP, [ACT_STOP]),
        _action(ACT_RANDOM, 0x0403, RANDOM),
        _action(ACT_SINGLE, 0x0403, SND_C),
        _action(ACT_STOP, 0x0103, RANDOM),
        _obj(7, MIXER, _node_params(0) + bytes(8)),
        _obj(5, RANDOM, _node_params(MIXER) + bytes(8)),
        _sound(SND_B, MEDIA_B, 2, RANDOM),  # listed first: order must still be by id
        _sound(SND_A, MEDIA_A, 0, RANDOM),
        _sound(SND_C, MEDIA_C, 1, MIXER),
    ]
    hirc = struct.pack("<I", len(objs)) + b"".join(objs)
    data = WEM_A + WEM_C_PREFIX
    didx = struct.pack("<3I", MEDIA_A, 0, len(WEM_A)) + struct.pack(
        "<3I", MEDIA_C, len(WEM_A), len(WEM_C_PREFIX)
    )
    return b"".join(
        [
            _chunk(b"BKHD", struct.pack("<II", 172, 77) + bytes(8)),
            _chunk(b"DIDX", didx),
            _chunk(b"DATA", data),
            _chunk(b"HIRC", hirc),
        ]
    )


def _akpk(banks: list[tuple[int, bytes]], streams: list[tuple[int, bytes]]) -> bytes:
    name = "sfx".encode("utf-16le") + b"\x00\x00"
    lang = struct.pack("<III", 1, 12, 0) + name
    lang += bytes(-len(lang) % 4)
    bank_lut_size = 4 + 20 * len(banks)
    stream_lut_size = 4 + 20 * len(streams)
    ext_lut = struct.pack("<I", 0)
    header_end = 28 + len(lang) + bank_lut_size + stream_lut_size + len(ext_lut)
    payload = b""
    luts: list[bytes] = []
    for table in (banks, streams):
        lut = struct.pack("<I", len(table))
        for eid, blob in table:
            lut += struct.pack("<5I", eid, 1, len(blob), header_end + len(payload), 0)
            payload += blob
        luts.append(lut)
    head = b"AKPK" + struct.pack(
        "<6I", header_end - 8, 1, len(lang), bank_lut_size, stream_lut_size, len(ext_lut)
    )
    return head + lang + luts[0] + luts[1] + ext_lut + payload


def _install(tmp_path: Path) -> Path:
    game = tmp_path / "game"
    (game / "wwise" / "en").mkdir(parents=True)
    pck = _akpk([(77, _bank())], [(MEDIA_B, WEM_B), (MEDIA_C, WEM_C_FULL)])
    (game / "wwise" / "Base.pck").write_bytes(pck)
    (game / "wwise" / "en" / "Base.pck").write_bytes(_akpk([], []))
    return game


def _echo(calls: list[bytes]) -> audio.Transcoder:
    def run(wem: bytes) -> tuple[bytes, str] | None:
        calls.append(wem)
        return b"OGG:" + wem, "audio/ogg"

    return run


# --------------------------------------------------------------------------- #


def test_fnv1_32_matches_wwise_ids() -> None:
    assert fnv1_32("") == 2166136261
    # Real DE ids: the first taunt and the age-up fanfare.
    assert fnv1_32("Play_Taunt_01") == fnv1_32("play_taunt_01") == 3521982396
    assert NOTIFICATION_EVENTS["age_up"] == 4272164677
    assert NOTIFICATION_EVENTS["victory"] == 2453267296


def test_taunt_table() -> None:
    assert len(TAUNT_EVENTS) == 105
    assert taunt_event(1) == 3521982396
    assert taunt_event(105) == fnv1_32("Play_Taunt_105")
    assert taunt_event(0) is None and taunt_event(106) is None


def test_read_akpk_and_bank(tmp_path: Path) -> None:
    pck = _akpk([(77, _bank())], [(MEDIA_B, WEM_B)])
    f = io.BytesIO(pck)
    banks, streams = read_akpk(f)
    assert [b.id for b in banks] == [77]
    assert streams[0].id == MEDIA_B
    assert pck[streams[0].offset : streams[0].offset + streams[0].size] == WEM_B
    bank = read_bank(f, banks[0].offset, banks[0].size)
    assert bank.version == 172
    a = next(m for m in bank.media if m.id == MEDIA_A)
    assert pck[a.offset : a.offset + a.size] == WEM_A
    kinds = {oid: kind for kind, oid, _ in iter_hirc(bank.hirc)}
    assert kinds[EV_RANDOM] == 4 and kinds[RANDOM] == 5 and kinds[SND_A] == 2
    with pytest.raises(ValueError):
        read_akpk(io.BytesIO(b"RIFF" + bytes(40)))


def test_object_field_parsers() -> None:
    body = _event(9, [10, 11])[5:]
    assert event_actions(body) == [10, 11]
    # Older layout: u32 count straight after the id.
    assert event_actions(struct.pack("<III", 9, 1, 10)) == [10]
    assert event_actions(b"\x01\x02") == []
    assert play_target(_action(1, 0x0403, 55)[5:]) == 55
    assert play_target(_action(1, 0x0103, 55)[5:]) is None
    snd = _sound(1, 777, 0, 888)[5:]
    assert sound_source(snd) == 777
    assert node_parent(2, snd) == 888
    assert node_parent(5, _obj(5, 1, _node_params(42))[5:]) == 42
    # One FX slot shifts the parent by bypass byte + 6.
    fx = bytes([0, 1, 0]) + bytes(6) + bytes(2) + struct.pack("<II", 0, 43)
    assert node_parent(5, struct.pack("<I", 1) + fx) == 43
    assert node_parent(5, b"\x00\x00\x00\x00\x00") is None


def test_event_media_resolution(tmp_path: Path) -> None:
    lib = AudioLibrary(_install(tmp_path), tmp_path / "cache", transcoder=_echo([]))
    assert lib.available
    assert lib.event_media(EV_RANDOM) == [MEDIA_A, MEDIA_B]  # container children by id
    assert lib.event_media(EV_SINGLE) == [MEDIA_C]
    assert lib.event_media(EV_EMPTY) == []
    assert lib.event_media(EV_STOP) == []  # non-Play actions are ignored
    assert lib.event_media(424242) == []


def test_media_audio_extracts_and_caches(tmp_path: Path) -> None:
    calls: list[bytes] = []
    lib = AudioLibrary(_install(tmp_path), tmp_path / "cache", transcoder=_echo(calls))
    assert lib.media_audio(MEDIA_A) == (b"OGG:" + WEM_A, "audio/ogg")
    assert lib.media_audio(MEDIA_B) == (b"OGG:" + WEM_B, "audio/ogg")
    # Prefetched media: the full streamed copy wins over the bank prefix.
    assert lib.media_audio(MEDIA_C) == (b"OGG:" + WEM_C_FULL, "audio/ogg")
    assert (tmp_path / "cache" / "audio" / f"{MEDIA_A}.ogg").is_file()
    assert lib.media_audio(MEDIA_A) is not None
    assert len(calls) == 3  # second request served from disk
    assert lib.media_audio(99999) is None

    assert lib.event_audio(EV_RANDOM, 0) == (b"OGG:" + WEM_A, "audio/ogg")
    assert lib.event_audio(EV_RANDOM, 3) == (b"OGG:" + WEM_B, "audio/ogg")
    assert lib.event_audio(EV_EMPTY) is None


def test_failed_transcode_is_remembered(tmp_path: Path) -> None:
    calls: list[bytes] = []

    def broken(wem: bytes) -> tuple[bytes, str] | None:
        calls.append(wem)
        return None

    lib = AudioLibrary(_install(tmp_path), tmp_path / "cache", transcoder=broken)
    assert lib.media_audio(MEDIA_A) is None
    assert lib.media_audio(MEDIA_A) is None
    assert len(calls) == 1


def test_index_cached_and_invalidated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    game = _install(tmp_path)
    cache = tmp_path / "cache"
    AudioLibrary(game, cache, transcoder=_echo([])).event_media(EV_RANDOM)
    index_file = cache / "audio" / "index-en.json"
    assert json.loads(index_file.read_text())["version"] == audio.INDEX_VERSION

    def no_scan(*_args: object) -> object:
        raise AssertionError("index should come from the cache")

    monkeypatch.setattr(audio, "build_index", no_scan)
    assert AudioLibrary(game, cache, transcoder=_echo([])).event_media(EV_RANDOM) == [
        MEDIA_A,
        MEDIA_B,
    ]
    monkeypatch.undo()
    # A changed package invalidates the cached index.
    (game / "wwise" / "en" / "Base.pck").write_bytes(_akpk([], [(MEDIA_A, b"x")]))
    called: list[bool] = []
    real = audio.build_index

    def spy(wwise: Path, files: list[Path]) -> audio._Index:
        called.append(True)
        return real(wwise, files)

    monkeypatch.setattr(audio, "build_index", spy)
    AudioLibrary(game, cache, transcoder=_echo([])).event_media(EV_RANDOM)
    assert called


def test_degrades_without_game_or_vgmstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audio, "find_vgmstream", lambda: None)
    lib = AudioLibrary(_install(tmp_path), tmp_path / "cache")
    assert not lib.available
    assert lib.event_media(EV_RANDOM) == [MEDIA_A, MEDIA_B]  # resolution still works
    assert lib.media_audio(MEDIA_A) is None
    assert lib.event_audio(EV_RANDOM) is None

    nogame = AudioLibrary(None, tmp_path / "cache2", transcoder=_echo([]))
    assert not nogame.available
    assert nogame.event_media(EV_RANDOM) == []
    assert nogame.event_audio(EV_RANDOM) is None


def test_find_vgmstream_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = tmp_path / "vgm"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("VANTAGE_VGMSTREAM", str(exe))
    assert audio.find_vgmstream() == exe


@pytest.mark.skipif(sys.platform == "win32", reason="the fake tools are shell scripts")
def test_transcode_with_fake_tools(tmp_path: Path) -> None:
    # Fake vgmstream: `-o OUT IN` copies IN to OUT. Fake ffmpeg writes the last arg.
    vgm = tmp_path / "vgmstream-cli"
    vgm.write_text('#!/bin/sh\ncp "$3" "$2"\n')
    vgm.chmod(0o755)
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text('#!/bin/sh\nfor a; do last="$a"; done\nprintf OGGDATA > "$last"\n')
    ffmpeg.chmod(0o755)
    assert audio.transcode(b"WEM", vgm, None) == (b"WEM", "audio/wav")
    assert audio.transcode(b"WEM", vgm, str(ffmpeg)) == (b"OGGDATA", "audio/ogg")
    bad = tmp_path / "bad"
    bad.write_text("#!/bin/sh\nexit 1\n")
    bad.chmod(0o755)
    assert audio.transcode(b"WEM", bad, None) is None
    # ffmpeg failing falls back to the WAV.
    assert audio.transcode(b"WEM", vgm, str(bad)) == (b"WEM", "audio/wav")


def test_world_events_are_served_by_name() -> None:
    # World sounds are reachable through the same /audio/notify/<key> table.
    assert audio.WORLD_EVENTS["ambience_forest"] == fnv1_32("Forest")
    assert audio.WORLD_EVENTS["villager_wood"] == fnv1_32("Play_Villager_Wood_Chop")
    assert NOTIFICATION_EVENTS["building_fire"] == 3992053517
    assert all(NOTIFICATION_EVENTS[k] == v for k, v in audio.WORLD_EVENTS.items())


def test_taunt_language_selection(tmp_path: Path) -> None:
    game = _install(tmp_path)
    german = b"RIFF-streamed-B-deutsch!"
    (game / "wwise" / "de").mkdir()
    (game / "wwise" / "de" / "Base.pck").write_bytes(_akpk([], [(MEDIA_B, german)]))
    (game / "wwise" / "fr").mkdir()  # empty: not an installed language
    lib = AudioLibrary(game, tmp_path / "cache", transcoder=_echo([]))
    assert lib.languages() == ["de", "en"]
    assert lib.resolve_language("de-AT") == "de"
    assert lib.resolve_language("fr") == "en" and lib.resolve_language(None) == "en"
    assert lib.for_language("en") is lib
    de = lib.for_language("DE")
    assert de is lib.for_language("de") and de.language == "de"
    assert lib.event_audio(EV_RANDOM, 1, language="de") == (b"OGG:" + german, "audio/ogg")
    assert lib.event_audio(EV_RANDOM, 1) == (b"OGG:" + WEM_B, "audio/ogg")
    # Same media id, separate caches per language.
    assert (tmp_path / "cache" / "audio-lang" / "de" / "audio" / f"{MEDIA_B}.ogg").is_file()
    assert lib.event_audio(EV_RANDOM, 1, language="xx") == (b"OGG:" + WEM_B, "audio/ogg")


def test_find_vgmstream_home_exe_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "opt" / "vgmstream" / "vgmstream-cli.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    exe.chmod(0o755)
    monkeypatch.delenv("VANTAGE_VGMSTREAM", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("sys.platform", "linux")
    assert audio.find_vgmstream() is None  # Linux looks for vgmstream-cli
    monkeypatch.setattr("sys.platform", "win32")
    assert audio.find_vgmstream() == exe
