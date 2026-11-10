"""The replay farm's pure helpers (tools/farm/farm.py): no game, no processes."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

FARM = Path(__file__).resolve().parents[1] / "tools/farm/farm.py"


@pytest.fixture(scope="module")
def farm():
    spec = importlib.util.spec_from_file_location("farm_tool", FARM)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["farm_tool"] = module
    spec.loader.exec_module(module)
    return module


def test_windows_path_is_the_z_drive(farm):
    path = Path("/home/u/replays/a b.aoe2record")
    assert farm.windows_path(path) == r"Z:\home\u\replays\a b.aoe2record"


def test_low_graphics_rewrites_known_keys_and_adds_missing_ones(farm, tmp_path):
    reg = tmp_path / "pfx/user.reg"
    reg.parent.mkdir()
    reg.write_text(
        '[Software\\\\Other] 1\n"Bloom"=dword:00000001\n\n'
        + farm.REG_SECTION
        + ' 1794077109\n#time=1dd\n"Bloom"=dword:00000001\n"Scroll Speed"=dword:00000018\n'
        '\n[Software\\\\After] 1\n"Bloom"=dword:00000001\n',
        "latin1",
    )
    farm.set_low_graphics(tmp_path)
    text = reg.read_text("latin1")
    before, section = text.split(farm.REG_SECTION)
    section, after = section.split("\n\n", 1)
    assert '"Bloom"=dword:00000000' in section
    assert '"Game Render Scale"=dword:00000032' in section  # added: it was missing
    assert '"Scroll Speed"=dword:00000018' in section  # not a graphics option: kept
    assert '"Bloom"=dword:00000001' in before and '"Bloom"=dword:00000001' in after


def test_low_graphics_leaves_a_prefix_the_game_never_ran_in(farm, tmp_path):
    reg = tmp_path / "pfx/user.reg"
    reg.parent.mkdir()
    reg.write_text("[Software\\\\Other] 1\n", "latin1")
    farm.set_low_graphics(tmp_path)
    assert reg.read_text("latin1") == "[Software\\\\Other] 1\n"


def test_prefix_copy_leaves_out_saves_mods_and_logs(farm, tmp_path):
    source = tmp_path / "compat"
    profile = source / "pfx/drive_c/users/steamuser/Games/Age of Empires 2 DE"
    for sub in ("123/savegame", "123/mods", "123/profile", "logs"):
        (profile / sub).mkdir(parents=True)
        (profile / sub / "file").write_text("x")
    (source / "pfx/drive_c/windows/logs").mkdir(parents=True)  # not the game's: kept
    (source / "pfx/user.reg").write_text("", "latin1")
    os.symlink("../drive_c", source / "pfx/link")
    target = tmp_path / "inst0"
    farm.make_prefix(source, target)
    copied = target / "pfx/drive_c/users/steamuser/Games/Age of Empires 2 DE"
    assert (copied / "123/profile/file").is_file()
    assert not (copied / "123/savegame").exists()
    assert not (copied / "123/mods").exists()
    assert not (copied / "logs").exists()
    assert (target / "pfx/drive_c/windows/logs").is_dir()
    assert (target / "pfx/link").is_symlink()
    farm.make_prefix(source, target)  # a second call keeps the existing copy


def test_replays_under_tmp_are_staged(farm, tmp_path):
    home = tmp_path / "elsewhere.aoe2record"
    home.write_bytes(b"r")
    staged = farm.stage(home, tmp_path / "farm")
    if str(home.resolve()).startswith("/tmp/"):
        assert staged.parent == tmp_path / "farm/staging" and staged.read_bytes() == b"r"
    else:
        assert staged == home.resolve()


def test_marked_finds_only_processes_naming_a_farm_instance(farm, tmp_path):
    # No process on this machine names this made-up farm folder.
    assert farm.marked(None, tmp_path / "no-such-farm") == []
