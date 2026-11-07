"""An install change must survive an older native replay's completion."""

import threading
from types import SimpleNamespace as NS

import pytest
from test_native_session import Converter, Executor

from vantage import server
from vantage.gamedata import GameData
from vantage.native_session import NativeSession


@pytest.mark.parametrize("when", ("queued", "conversion", "loading"))
def test_new_game_directory_cancels_stale_native_load(tmp_path, when):
    replay = tmp_path / "match.aoe2record"
    replay.write_bytes(b"fake replay, never parsed")
    install = tmp_path / "new-install"
    install.mkdir()
    (install / "AoE2DE_s.exe").write_bytes(b"fake install, never executed")
    original = GameData(None, cache_dir=tmp_path / "assets")
    session = NativeSession(original, tmp_path / "recordings")
    executor = Executor()
    prepared = []

    def change_install():
        assert session.set_game_dir(str(install)) == {"ok": True, "game_dir": str(install)}

    converter = Converter(change_install if when == "conversion" else None)

    def load(*_):
        prepared.append(True)
        if when == "loading":
            change_install()
        return original, object(), {}

    session.configure_native(
        NS(converter=lambda: converter, cache_dir=tmp_path / "cache"),
        executor=executor,
        loader=load,
    )
    generation = session.open_native_replay(replay)["generation"]
    if when == "queued":
        change_install()
    executor.run()
    assert session.data is not original and session.data.game_dir == install
    assert session.generation == generation and session.mode == "native_replay"
    assert session.source["status"] == "cancelled" and session.ended.is_set()
    assert session.error is None and session.native.current.state == "cancelled"
    assert converter.calls == (when != "queued")
    assert bool(prepared) == (when == "loading")
    session.close_native()


def test_selecting_same_game_directory_keeps_normal_native_adoption(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    (install / "AoE2DE_s.exe").write_bytes(b"fake install, never executed")
    replay = tmp_path / "match.aoe2record"
    replay.write_bytes(b"fake replay, never parsed")
    original = GameData(install, cache_dir=tmp_path / "assets")
    session = NativeSession(original, tmp_path / "recordings")
    executor, timeline = Executor(), object()
    session.configure_native(
        NS(converter=Converter, cache_dir=tmp_path / "cache"),
        executor=executor,
        loader=lambda *_: (original, timeline, {}),
    )
    generation = session.open_native_replay(replay)["generation"]
    assert session.set_game_dir(str(install))["ok"]
    executor.run()
    assert session.data is original and session.timeline is timeline
    assert session.generation == generation + 1
    assert session.mode == "recording" and session.source["status"] == "ready"
    session.close_native()


def test_game_directory_replacement_holds_selection_lock(tmp_path, monkeypatch):
    install = tmp_path / "install"
    install.mkdir()
    (install / "AoE2DE_s.exe").write_bytes(b"fake install, never executed")
    session = NativeSession(GameData(None, cache_dir=tmp_path), tmp_path)
    entered, release = threading.Event(), threading.Event()
    replacement = GameData(install, cache_dir=tmp_path)

    def construct(*_):
        entered.set()
        assert release.wait(2)
        return replacement

    monkeypatch.setattr(server, "GameData", construct)
    worker = threading.Thread(target=session.set_game_dir, args=(str(install),))
    worker.start()
    try:
        assert entered.wait(2)
        acquired = session.lock.acquire(blocking=False)
        if acquired:
            session.lock.release()
        assert not acquired  # Adoption cannot pass its identity check mid-replacement.
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive() and session.data is replacement
