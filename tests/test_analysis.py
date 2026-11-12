from pathlib import Path

import pytest

from vantage.analysis import analysis_provenance, source_revision
from vantage.gamedata import GameData


def test_source_revision_tracks_code_and_schema_not_filesystem_location(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    for root in (a, b):
        root.mkdir()
        (root / "world.py").write_text("idle = 1\n")
        (root / "cade_schema.json").write_text('{"fields": []}')
    assert source_revision(a) == source_revision(b)
    (b / "world.py").write_text("idle = 2\n")
    assert source_revision(a) != source_revision(b)
    (b / "world.py").write_text("idle = 1\n")
    (b / "cade_schema.json").write_text('{"fields": [1]}')
    assert source_revision(a) != source_revision(b)


def test_provenance_tracks_config_and_installed_data_without_personal_paths(tmp_path: Path) -> None:
    folder = tmp_path / "resources" / "_common" / "dat"
    folder.mkdir(parents=True)
    dat = folder / "empires2_x2_p1.dat"
    dat.write_bytes(b"build one")
    data = GameData(tmp_path)
    first = analysis_provenance(data)
    assert first["game_data"][dat.name]
    assert str(tmp_path) not in str(first)
    assert analysis_provenance(data, tc_idle_villagers=100) != first
    dat.write_bytes(b"build two with changed effects")
    assert analysis_provenance(data) != first


def test_no_game_art_preserves_metadata_and_never_reads_game_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import threading
    import urllib.error
    import urllib.request

    from vantage.server import Session, serve

    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "viewer"))
    data = GameData(tmp_path)
    monkeypatch.setattr(data, "tech_tree", lambda *_: {"relevant_upgrades": {"125": [45, 46]}})
    monkeypatch.setattr(data, "icon_png", lambda *_: pytest.fail("game art was read"))
    session = Session(data, tmp_path / "recordings")
    server = serve("127.0.0.1", 0, session, [], game_art=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:

        def get(path: str) -> bytes:
            with urllib.request.urlopen(base + path) as response:
                return response.read()

        assert json.loads(get("/api/config"))["game_art"] is False
        assert json.loads(get("/api/techtree/1"))["relevant_upgrades"]["125"] == [45, 46]
        assert json.loads(get("/api/session"))["game_data"] is True
        assert b"<svg" in get("/icon/unit/1.png")
        assert json.loads(get("/api/particles")) == {}
        with pytest.raises(urllib.error.HTTPError) as error:
            get("/sprite/1/0/0.png")
        assert error.value.code == 404
    finally:
        session.stop()
        server.shutdown()
        server.server_close()
