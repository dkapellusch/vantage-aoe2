"""vantage.gamedata: strings, palettes, civs and DDS icon decoding."""

from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

import pytest

from vantage.gamedata import GameData, dds_to_png, find_game_dir


def _dds(width: int, height: int, fourcc: bytes, body: bytes, rgb_flags: int = 0) -> bytes:
    head = bytearray(128)
    head[:4] = b"DDS "
    struct.pack_into("<II", head, 12, height, width)
    struct.pack_into("<I4sI", head, 80, rgb_flags, fourcc, 32 if rgb_flags else 0)
    struct.pack_into("<IIII", head, 92, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    return bytes(head) + body


def _png_pixels(png: bytes) -> tuple[int, int, bytes]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", png[16:24])
    idat = png.index(b"IDAT")
    n = struct.unpack(">I", png[idat - 4 : idat])[0]
    raw = zlib.decompress(png[idat + 4 : idat + 4 + n])
    rows = [raw[y * (w * 4 + 1) + 1 : (y + 1) * (w * 4 + 1)] for y in range(h)]
    return w, h, b"".join(rows)


def test_uncompressed_dds() -> None:
    px = struct.pack("<II", 0xFF112233, 0x80445566)  # ARGB
    w, h, rgba = _png_pixels(dds_to_png(_dds(2, 1, b"\x00" * 4, px, rgb_flags=0x41)))
    assert (w, h) == (2, 1)
    assert rgba == bytes([0x11, 0x22, 0x33, 0xFF, 0x44, 0x55, 0x66, 0x80])


def test_dxt1_and_dxt5() -> None:
    # Colour block: c0 = pure red, c1 = pure blue, all indices 0 -> red everywhere.
    red, blue = 0xF800, 0x001F
    block = struct.pack("<HHI", red, blue, 0)
    _, _, rgba = _png_pixels(dds_to_png(_dds(4, 4, b"DXT1", block)))
    assert rgba[:4] == bytes([255, 0, 0, 255])
    alpha = bytes([200, 10]) + b"\x00" * 6  # index 0 -> alpha 200
    _, _, rgba5 = _png_pixels(dds_to_png(_dds(4, 4, b"DXT5", alpha + block)))
    assert rgba5[:4] == bytes([255, 0, 0, 200])
    with pytest.raises(ValueError):
        dds_to_png(b"nope")


def _fake_install(root: Path) -> Path:
    game = root / "AoE2DE"
    kv = game / "resources" / "en" / "strings" / "key-value"
    kv.mkdir(parents=True)
    (kv / "key-value-strings-utf8.txt").write_text('// comment\n5121 "Villager"\n10271 "Britons"\n')
    dat = game / "resources" / "_common" / "dat"
    dat.mkdir(parents=True)
    civs = {
        "civilization_list": [
            {"internal_name": "Gaia", "name_string_id": 10102},
            {
                "internal_name": "Britons",
                "name_string_id": 10271,
                "emblem_image_path": "/resources/civ_emblems/britons.png",
            },
        ]
    }
    (dat / "civilizations.json").write_text(json.dumps(civs))
    pal = game / "resources" / "_common" / "palettes"
    pal.mkdir(parents=True)
    (pal / "original.pal").write_text("JASC-PAL\n0100\n2\n1 2 3\n4 5 6\n")
    (pal / "playercolor_blue.pal").write_text("JASC-PAL\n0100\n1\n0 0 250\n")
    medal = game / "widgetui" / "textures" / "menu" / "civs"
    medal.mkdir(parents=True)
    (medal / "britons.png").write_bytes(b"\x89PNG-medal")
    units = game / "widgetui" / "textures" / "ingame" / "units"
    units.mkdir(parents=True)
    block = struct.pack("<HHI", 0x07E0, 0, 0)
    (units / "015_50730.DDS").write_bytes(_dds(4, 4, b"DXT1", block))
    return game


def test_install_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    game = _fake_install(tmp_path)
    monkeypatch.setenv("VANTAGE_GAME_DIR", str(game))
    assert find_game_dir() == game
    data = GameData(game, cache_dir=tmp_path / "cache")
    assert data.string(5121) == "Villager"
    de = game / "resources" / "de" / "strings" / "key-value"
    de.mkdir(parents=True)
    (de / "key-value-strings-utf8.txt").write_text('5121 "Dorfbewohner"\n')
    assert data.strings_for("de")[5121] == "Dorfbewohner"
    assert data.strings_for("xx") == {}
    assert data.string(-1, "x") == "x"
    assert data.civ_name(1) == "Britons"
    assert data.civ_name(77) == "Civ 77"
    assert data.emblem_png(1) == b"\x89PNG-medal"
    assert data.interface_palette[1] == (4, 5, 6)
    assert data.player_colors[0] == (0, 0, 250)
    assert data.player_colors[1] == (255, 0, 0)  # missing file -> standard colour
    png = data.icon_png("unit", 15)
    assert png is not None and png.startswith(b"\x89PNG")
    assert (tmp_path / "cache" / "icons" / "unit-15.png").read_bytes() == png
    assert data.icon_png("unit", 16) is None
    assert data.icon_png("nonsense", 15) is None


@pytest.mark.skipif(sys.platform == "win32", reason="Proton paths exist only on Linux")
def test_proton_path_hint_and_missing_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = _fake_install(tmp_path)
    monkeypatch.delenv("VANTAGE_GAME_DIR", raising=False)
    hint = "Z:" + str(game).replace("/", "\\")
    assert find_game_dir(hint) == game
    empty = GameData(None, cache_dir=tmp_path)
    assert not empty.available
    assert empty.strings == {} and empty.civ_name(1) == "Civ 1"
    assert empty.icon_png("unit", 1) is None and empty.emblem_png(1) is None
    assert len(empty.interface_palette) == 256


def test_dxt3_explicit_alpha() -> None:
    block = struct.pack("<HHI", 0xF800, 0x001F, 0)
    alpha = bytes([0x0A, 0xFF]) + b"\x00" * 6  # pixel 0 -> 0xA*17, pixel 2 -> 0xF*17
    _, _, rgba = _png_pixels(dds_to_png(_dds(4, 4, b"DXT3", alpha + block)))
    assert rgba[:4] == bytes([255, 0, 0, 170])
    assert rgba[8:12] == bytes([255, 0, 0, 255])


def test_particle_definitions_and_atlas(tmp_path: Path) -> None:
    game = tmp_path / "AoE2DE"
    pdir = game / "resources" / "_common" / "particles"
    (pdir / "textures" / "atlases").mkdir(parents=True)
    (pdir / "smoke.json").write_text(
        json.dumps(
            {
                "AtlasFile": "textures\\atlases\\smoke.dds",
                "ImageFirst": 2,
                "ImageCount": 4,
                "Scale": 0.5,
                "AlphaEnd": 0,
                "Duration1": 2.9,
                "Duration2": 3.1,
                "StartMode": "Fade",
                "StartDuration": 0.75,
                "StopMode": "Cut",
                "StopDuration": 0.5,
            }
        )
    )
    (pdir / "broken.json").write_text("{")
    block = struct.pack("<HHI", 0xF800, 0x001F, 0)
    (pdir / "textures" / "atlases" / "smoke.dds").write_bytes(_dds(4, 4, b"DXT1", block))
    frames = {"frames": [{"frame": {"x": 0, "y": 0, "w": 4, "h": 4}}]}
    (pdir / "textures" / "atlases" / "smoke.json").write_text(json.dumps(frames))
    data = GameData(game, cache_dir=tmp_path / "cache")

    assert data.particle_definitions == ["broken", "smoke"]
    table = data.particle_definitions_table()
    assert table == {
        "smoke": {
            "atlas": "textures/atlases/smoke.dds",
            "first": 2,
            "count": 4,
            "scale": 0.5,
            "alpha_start": 1.0,
            "alpha_end": 0.0,
            "duration": 1.0,
            "type": "",
            "life": [2.9, 3.1],
            "fade_in": 0.75,
            "fade_out": 0.0,  # StopMode Cut: no fade
            "fire": False,
        }
    }
    got = data.particle_atlas("textures/atlases/smoke.dds")
    assert got is not None
    png, mime, meta = got
    assert mime == "image/png" and _png_pixels(png)[:2] == (4, 4)
    assert meta == {"scale": 1.0, "frames": frames["frames"]}
    assert data.particle_atlas("textures/atlases/smoke.dds") == got  # from the cache
    assert data.particle_atlas("../../secret.dds") is None
    assert GameData(None).particle_definitions == []


def test_return_of_rome_mode_shadows_the_base_game(tmp_path: Path) -> None:
    game = _fake_install(tmp_path)
    ror = game / "modes" / "Pompeii"
    kv = ror / "resources" / "en" / "strings" / "key-value"
    kv.mkdir(parents=True)
    (kv / "key-value-pompeii-strings-utf8.txt").write_text('10271 "Egyptians"\n')
    dat = ror / "resources" / "_common" / "dat"
    (dat / "CivTechTrees").mkdir(parents=True)
    civs = {
        "civilization_list": [
            {"internal_name": "Gaia"},
            {"internal_name": "Egyptian", "name_string_id": 10271, "tech_tree_name": "EGYPTIANS"},
        ]
    }
    (dat / "civilizations.json").write_text(json.dumps(civs))
    tree = {
        "civ_techs_buildings": [{"Node ID": 12, "Name": "Barracks", "Age ID": 1}],
        "civ_techs_units": [{"Node ID": 281, "Name": "Clubman", "Use Type": "Unit"}],
    }
    (dat / "CivTechTrees" / "EGYPTIANS.json").write_text(json.dumps(tree))
    units = ror / "widgetui" / "textures" / "ingame" / "units"
    units.mkdir(parents=True)
    block = struct.pack("<HHI", 0x001F, 0, 0)  # blue, unlike the base game's green icon 15
    (units / "015_ror.DDS").write_bytes(_dds(4, 4, b"DXT1", block))

    base = GameData(game, cache_dir=tmp_path / "cache")
    rome = base.with_mode("Pompeii")
    assert base.with_mode(None) is base and rome.with_mode("Pompeii") is rome
    assert (base.game, rome.game) == ("aoe2", "ror")
    assert rome.roots() == [ror, game] and base.roots() == [game]
    assert rome.string(10271) == "Egyptians" and rome.string(5121) == "Villager"
    assert base.string(10271) == "Britons"
    assert rome.civ_name(1) == "Egyptians" and base.civ_name(1) == "Britons"
    assert rome.dat_path("civilizations.json") == dat / "civilizations.json"
    assert rome.dat_path("palettes.json") is None
    t = rome.tech_tree(1)
    assert t is not None and t["buildings"][0]["name"] == "Barracks"
    assert t["nodes"][0]["name"] == "Clubman"
    assert base.tech_tree(1) is None
    ror_icon, base_icon = rome.icon_png("unit", 15), base.icon_png("unit", 15)
    assert ror_icon is not None and base_icon is not None and ror_icon != base_icon
    assert (tmp_path / "cache" / "icons" / "Pompeii-unit-15.png").is_file()
    assert GameData(game, mode="../etc").mode is None


# -- Steam libraries, profiles, mods, installed build ------------------------------

from vantage import gamedata as G  # noqa: E402


def _library(root: Path, name: str) -> Path:
    lib = root / name
    (lib / "steamapps").mkdir(parents=True)
    return lib


@pytest.mark.skipif(sys.platform == "win32", reason="Proton paths exist only on Linux")
def test_steam_libraries_profiles_and_replay_dirs(tmp_path: Path) -> None:
    steam = _library(tmp_path, "Steam")
    other = _library(tmp_path, "Games")
    entries = "".join(f' "{i}" {{ "path" "{p}" }}\n' for i, p in enumerate((steam, other, "/no")))
    vdf = '"libraryfolders"\n{\n' + entries + "}\n"
    (steam / "steamapps" / "libraryfolders.vdf").write_text(vdf)
    libs = G.steam_libraries([steam])
    assert libs == [steam, other]  # deduplicated, missing libraries dropped
    prof_root = other / "steamapps" / "compatdata" / "813780" / G._PROFILE_IN_PREFIX
    profile = prof_root / "76561198000000000"
    for sub in ("savegame/multi", "modes/Pompeii/savegame"):
        (profile / sub).mkdir(parents=True)
    (prof_root / "logs").mkdir()
    assert G.profile_roots(libs) == [prof_root]
    assert G.profile_dirs([prof_root]) == [profile]
    assert G.replay_dirs([profile]) == [
        profile / "modes/Pompeii/savegame",
        profile / "savegame",
        profile / "savegame/multi",
    ]
    assert G.windows_path(profile / "savegame" / "r.aoe2record").startswith("C:\\users\\steamuser")
    assert G.windows_path(Path("/mnt/x/r.aoe2record")) == "Z:\\mnt\\x\\r.aoe2record"
    assert G.host_path("Z:\\mnt\\x\\") == Path("/mnt/x")
    game = other / "steamapps" / "common" / "AoE2DE"
    win = "C:\\users\\steamuser\\Games\\Age of Empires 2 DE\\76561198000000000\\"
    assert G.host_path(win, game) == profile
    assert G.host_path("D:\\x", game) is None and G.host_path("", game) is None


def _pe(version: str) -> bytes:
    """A minimal PE with one ``.rsrc`` section holding a FileVersion string."""
    key = "FileVersion".encode("utf-16-le") + b"\0\0"
    rsrc = bytearray(b"\0" * 6) + key
    while len(rsrc) % 4:
        rsrc += b"\0"
    rsrc += version.encode("utf-16-le") + b"\0\0"
    head = bytearray(0x200)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x40)
    head[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<H", head, 0x46, 1)  # one section
    struct.pack_into("<H", head, 0x54, 0)  # no optional header
    struct.pack_into("<8sIIII", head, 0x58, b".rsrc", len(rsrc), 0, len(rsrc), 0x200)
    return bytes(head) + bytes(rsrc)


def test_installed_build_from_the_exe_file_version(tmp_path: Path) -> None:
    game = tmp_path / "AoE2DE"
    game.mkdir()
    (game / "AoE2DE_s.exe").write_bytes(_pe("101.103.54800.0"))
    assert G.exe_file_version(game / "AoE2DE_s.exe") == "101.103.54800.0"
    assert G.installed_build(game) == 54800
    assert GameData(game, cache_dir=tmp_path / "c").build == 54800
    (game / "AoE2DE_s.exe").write_bytes(b"MZ not a pe")
    assert G.installed_build(game) is None and G.installed_build(None) is None


def test_mod_roots_follow_the_mod_status_priority(tmp_path: Path) -> None:
    profile = tmp_path / "123"
    mods = profile / "mods"
    gfx = Path("resources/_common/drs/graphics")
    for name in ("subscribed/1_A", "subscribed/2_B", "local/C"):
        (mods / name / gfx).mkdir(parents=True)
    (mods / "local" / "C" / "resources/_common/terrain/textures").mkdir(parents=True)
    (mods / "mod-status.json").write_text(
        json.dumps(
            {
                "Mods": [
                    {"Enabled": True, "Path": "subscribed//2_B", "Priority": 2},
                    {"Enabled": False, "Path": "subscribed//1_A", "Priority": 1},
                    {"Enabled": True, "Path": "local\\C", "Priority": 1},
                ]
            }
        )
    )
    data = GameData(None, cache_dir=tmp_path / "c", mods=G.ModConfig(profiles=[profile]))
    assert data.mod_roots("graphics") == []  # off until enabled
    data.mods.enabled.update(graphics=True, terrain=True)
    assert data.mod_roots("graphics") == [mods / "local/C" / gfx, mods / "subscribed/2_B" / gfx]
    assert data.with_mode("Pompeii").mod_roots("terrain") == [
        mods / "local/C/resources/_common/terrain/textures"
    ]
    extra = tmp_path / "more"
    (extra / "D" / gfx).mkdir(parents=True)
    data.mods.extra = [extra]
    data.mods.live_mods = [mods / "subscribed/1_A"]  # the live game's list wins
    assert data.mod_roots("graphics") == [mods / "subscribed/1_A" / gfx, extra / "D" / gfx]
    assert data.mod_roots("nope") == []


def test_terrain_mod_texture_wins(tmp_path: Path) -> None:
    game = tmp_path / "AoE2DE"
    base = game / "resources/_common/terrain/textures/2x"
    base.mkdir(parents=True)
    red = _dds(4, 4, b"", struct.pack("<16I", *([0xFFFF0000] * 16)), rgb_flags=0x41)
    blue = _dds(4, 4, b"", struct.pack("<16I", *([0xFF0000FF] * 16)), rgb_flags=0x41)
    (base / "grass.dds").write_bytes(red)
    mod = tmp_path / "mod"
    (mod / "resources/_common/terrain/textures").mkdir(parents=True)
    (mod / "resources/_common/terrain/textures/grass.dds").write_bytes(blue)
    data = GameData(game, cache_dir=tmp_path / "c", mods=G.ModConfig(extra=[mod], live_mods=[]))
    plain = data.terrain_png("grass")
    data.mods.enabled["terrain"] = True
    modded = data.terrain_png("grass")
    assert plain is not None and modded is not None and plain != modded


def test_tech_tree_links_triggers_and_civ_description(tmp_path: Path) -> None:
    game = tmp_path / "AoE2DE"
    kv = game / "resources" / "en" / "strings" / "key-value"
    kv.mkdir(parents=True)
    (kv / "key-value-strings-utf8.txt").write_text(
        '10271 "Britons"\n120150 "Foot Archer civilization\\n\\n• Shepherds +25%"\n',
        encoding="utf-8",
    )
    dat = game / "resources" / "_common" / "dat"
    (dat / "CivTechTrees").mkdir(parents=True)
    civ = {"name_string_id": 10271, "tech_tree_name": "BRITONS",
           "tech_tree_description_string_id": 120150}  # fmt: skip
    (dat / "civilizations.json").write_text(json.dumps({"civilization_list": [{}, civ]}))
    node = {"Node ID": 24, "Use Type": "Unit", "Link ID": 4, "Trigger Tech ID": 100}
    (dat / "CivTechTrees" / "BRITONS.json").write_text(json.dumps({"civ_techs_units": [node]}))
    tree = GameData(game, cache_dir=tmp_path / "c").tech_tree(1)
    assert tree is not None
    assert tree["description"] == "Foot Archer civilization\n\n• Shepherds +25%"
    assert (tree["nodes"][0]["link"], tree["nodes"][0]["trigger_tech"]) == (4, 100)


def test_particle_atlas_reports_the_scale_it_returns(tmp_path: Path) -> None:
    pdir = tmp_path / "AoE2DE" / "resources" / "_common" / "particles"
    pdir.mkdir(parents=True)
    # 2048 px wide asks for mip 1, but the file has a single level: full size.
    body = struct.pack("<HHI", 0xF800, 0x001F, 0) * (2048 // 4)
    (pdir / "wide.dds").write_bytes(_dds(2048, 4, b"DXT1", body))
    got = GameData(tmp_path / "AoE2DE", cache_dir=tmp_path / "c").particle_atlas("wide.dds")
    assert got is not None
    png, _, meta = got
    assert _png_pixels(png)[0] == 2048 and meta["scale"] == 1.0


# -- tech tree, unit lines, eras -----------------------------------------------------


def _tn(node_id: int, kind: str = "Tech", *, status: str = "ResearchedCompleted",
        building: int = 12, age: int = 1, trigger: int = -1, name_id: int | None = None,
        picture: int = 5) -> dict[str, object]:  # fmt: skip
    return {
        "Node ID": node_id,
        "Use Type": kind,
        "Node Status": status,
        "Building ID": building,
        "Age ID": age,
        "Trigger Tech ID": trigger,
        "Name String ID": name_id if name_id is not None else 100 + node_id,
        "Picture Index": picture,
        "Name": f"n{node_id}",
    }


@pytest.fixture
def tree_game(tmp_path: Path) -> GameData:
    """Gaia + civ 1 (base) + civ 2 (base) + civ 3 (antiquity), small trees."""
    game = tmp_path / "AoE2DE"
    kv = game / "resources" / "en" / "strings" / "key-value"
    kv.mkdir(parents=True)
    (kv / "key-value-strings-utf8.txt").write_text(
        "\n".join(
            [
                '10001 "Alpha"',
                '10002 "Beta"',
                '10003 "Gamma"',
                '120150 "Alpha help"',
                '120152 "Beta help"',
                '1022 "Loom (nine-row name)"',
                '12403 "Pierce"',
                '12404 "Melee"',
                '407084 "Archaic Age"',
                '407085 "Archaic override"',
                '407086 "Archaic desc"',
                '31000 "Unique Unit"',
                '31001 "Unique Unit help"',
            ]
        )
    )
    dat = game / "resources" / "_common" / "dat"
    (dat / "CivTechTrees").mkdir(parents=True)

    def civ(name: str, sid: int, tree: str, **extra: object) -> dict[str, object]:
        return {"internal_name": name, "name_string_id": sid, "tech_tree_name": tree, **extra}

    civs = [
        civ("Gaia", 0, "GAIA"),
        civ("Alpha", 10001, "ALPHA", unique_unit_image_paths=["a/041_longbow.png", "junk"],
            unique_unit_string_ids=[{"name": 31000, "description": 31001}],
            unique_tech_id_2=900, unique_tech_id_1=901, unique_unit_upgrade_id=950),
        civ("Beta", 10002, "BETA", tech_tree_description_string_id=120152),
        civ("Gamma", 10003, "GAMMA", era="antiquity"),
    ]  # fmt: skip
    (dat / "civilizations.json").write_text(json.dumps({"civilization_list": civs}))

    def tree(
        units: list[dict[str, object]], buildings: list[dict[str, object]] | None = None
    ) -> str:
        return json.dumps({"civ_techs_units": units, "civ_techs_buildings": buildings or []})

    shared = [
        _tn(22, name_id=1022),  # Loom: name string is id - 9000
        _tn(213), _tn(249),  # wheelCart
        _tn(14), _tn(13), _tn(12),  # farm line
        _tn(74, "Unit", building=12), _tn(1350, "Unit", trigger=1350),  # champi base
    ]  # fmt: skip
    alpha = [
        *shared,
        _tn(1014, status="NotAvailable"),
        _tn(1012, status="NotAvailable"),
        _tn(900, building=82, age=3), _tn(901, building=82, age=4),
        _tn(7, "Unit"), _tn(98, status="NotAvailable"),
    ]  # fmt: skip
    beta = [*shared, _tn(1014), _tn(1013), _tn(1012), _tn(902, building=82, age=3), _tn(7, "Unit")]
    # Beta lacks the champi base, which nobody strikes (regional) -> hidden for it.
    beta = [n for n in beta if n["Node ID"] != 1350]
    gamma = [n for n in shared if n["Node ID"] in (213, 249, 14, 13, 12)]
    for name, units in (("ALPHA", alpha), ("BETA", beta), ("GAMMA", gamma)):
        (dat / "CivTechTrees" / f"{name}.json").write_text(tree(units))
    (dat / "unitlines.json").write_text(
        json.dumps(
            {
                "UnitLines": [
                    {"Name": "Spear", "Identifier": ["spear", "x"], "LineID": 5,
                     "IDChain": [93, 358]},
                    {"Name": "Tower", "Identifier": "tower", "LineID": -398, "Building": True,
                     "IDChain": [79, 234]},
                ]
            }
        )
    )  # fmt: skip
    (dat / "eras.json").write_text(
        json.dumps(
            [
                {"Name": "base", "Ages": [], "TechDisplayOverrides": []},
                {
                    "Name": "antiquity",
                    "Ages": [
                        {
                            "NameId": 407084,
                            "ShieldMaterialName": "S",
                            "TechTreeIconMaterialName": "T",
                        }
                    ],
                    "TechDisplayOverrides": [
                        {"TechId": 104, "NameId": 407085, "IconId": 150, "DescriptionId": 407086}
                    ],
                },
            ]
        )
    )  # fmt: skip
    return GameData(game, cache_dir=tmp_path / "c")


def test_availability_struck_versus_hidden(tree_game: GameData) -> None:
    na, hidden = tree_game.availability(1)
    assert "tech:1014" in na and "tech:1014" not in hidden  # NotAvailable for Alpha only
    tree = tree_game.tech_tree(1)
    assert tree is not None
    status = {n["key"]: n["status"] for n in tree["nodes"]}
    assert status["tech:1014"] == "struck" and status["tech:22"] == "available"
    # Beta lists no champi base and no civ strikes it: hidden, not struck.
    na2, hidden2 = tree_game.availability(2)
    assert "trigger:1350" in hidden2 and "trigger:1350" in na2
    assert tree_game.pasture_civs() == [2]


def test_unique_techs_from_the_trees_with_civ_fallback(tree_game: GameData) -> None:
    uts = tree_game.unique_tech_ids
    assert uts[1] == {"castle": [900], "imperial": [901]}
    assert uts[2]["castle"] == [902] and uts[2]["imperial"] == []
    ids = tree_game.power_tech_ids()
    assert {900, 901, 902, 950, 101, 102, 103} <= set(ids)


def test_layout_rows_variants_regional_drop_and_stage_status(tree_game: GameData) -> None:
    tree = tree_game.tech_tree(2)
    assert tree is not None and tree["layout"] is not None
    rows = {r["key"]: r for r in tree["layout"]["rows"]}
    groups = {g["key"]: g for r in rows.values() for g in r["groups"]}
    # Beta has the pasture tech available: the farm group swaps to the pasture stages.
    assert [s["id"] for s in groups["farm"]["stages"]] == [1014, 1013, 1012]
    assert "champiLine" not in groups  # regional base hidden for Beta
    assert groups["loom"]["stages"][0]["name"] == "Loom (nine-row name)"
    assert groups["loom"]["stages"][0]["icon_kind"] == "tech"
    assert groups["castleAgeUniqueTech"]["stages"][0]["id"] == 902
    alpha = tree_game.tech_tree(1)
    assert alpha is not None and alpha["layout"] is not None
    agroups = {g["key"]: g for r in alpha["layout"]["rows"] for g in r["groups"]}
    assert [s["id"] for s in agroups["farm"]["stages"]] == [14, 13, 12]
    assert agroups["champiLine"]["stages"][0]["status"] == "available"
    # A later tier whose base tier is unavailable is struck.
    farm = agroups["wheelCart"]["stages"]
    assert farm[1]["base_key"] == farm[0]["key"]


def test_antiquity_civ_shows_only_the_economy_row(tree_game: GameData) -> None:
    tree = tree_game.tech_tree(3)
    assert tree is not None and tree["era"] == "antiquity"
    assert tree["layout"] is not None
    assert [r["key"] for r in tree["layout"]["rows"]] == ["economy"]
    assert tree_game.civ_era(3) == "antiquity" and tree_game.civ_era(1) == "base"


def test_eras_age_names_and_tech_display_overrides(tree_game: GameData) -> None:
    eras = tree_game.eras()
    assert eras["antiquity"]["ages"][0]["name"] == "Archaic Age"
    assert eras["antiquity"]["techs"]["104"] == {
        "name": "Archaic override", "name_id": 407085, "icon": 150, "description": "Archaic desc",
    }  # fmt: skip
    assert eras["base"] == {"ages": [], "techs": {}}


def test_ui_materials_resolve_to_age_icons(tree_game: GameData) -> None:
    """The antiquity age images come from widgetui/materials.json (atlas entry file)."""
    assert tree_game.game_dir is not None
    ui = tree_game.game_dir / "widgetui"
    (ui / "textures" / "menu" / "techtree").mkdir(parents=True)
    (ui / "textures" / "menu" / "techtree" / "techtree_archaic_age.png").write_bytes(b"png")
    (ui / "materials.json").write_text(json.dumps({
        "Materials": [{"MaterialDef": {"Name": "T", "Type": "Atlas",
                                       "TextureRef": "TArchaic", "AtlasRef": "Techtree"}},
                      {"MaterialDef": {"Name": "Missing", "TextureRef": "Nope"}}],
        "AtlasTextures": [{"AtlasDef": {"Name": "Techtree", "Textures": [
            {"RefName": "TArchaic", "FileName": "textures/menu/techtree/techtree_archaic_age.png"},
            {"RefName": "Nope", "FileName": "textures/menu/techtree/none.png"}]}}],
        "GlobalTextures": [],
    }))  # fmt: skip
    data = GameData(tree_game.game_dir, cache_dir=tree_game.cache_dir)
    assert data.material_png("T") is not None and data.material_png("Missing") is None
    assert data.eras()["antiquity"]["ages"][0]["icon"] == "/ui/material/T.png"


def test_unit_lines_and_unique_unit_icons(tree_game: GameData) -> None:
    table = tree_game.unit_line_table()
    assert table["l5"] == {
        "name": "Spear",
        "identifier": "spear",
        "ids": [93, 358],
        "building": False,
    }
    assert table["l-398"]["building"] is True
    assert tree_game.unit_lines[358] == "l5" and tree_game.unit_lines[234] == "l-398"
    tree = tree_game.tech_tree(1)
    assert tree is not None
    assert tree["unique_units"] == [
        {"icon": 41, "name": "Unique Unit", "description": "Unique Unit help"}
    ]
    assert tree["description_string_id"] == 120150 and tree["description"] == "Alpha help"
    beta = tree_game.tech_tree(2)
    assert beta is not None and beta["description_string_id"] == 120152
    gamma = tree_game.tech_tree(3)  # no explicit description id: civ id + 120149
    assert gamma is not None and gamma["description_string_id"] == 120152


def test_return_of_rome_has_no_nine_row_layout(tree_game: GameData) -> None:
    ror = tree_game.with_mode("Pompeii")
    tree = ror.tech_tree(1)
    assert tree is None or tree["layout"] is None


def test_particle_atlas_prefers_sprite_mod_roots(tmp_path: Path) -> None:
    game = tmp_path / "AoE2DE"
    base = game / "resources" / "_common" / "particles"
    mod = tmp_path / "mod" / "resources" / "_common" / "particles"
    for d, color in ((base, 0xF800), (mod, 0x001F)):
        d.mkdir(parents=True)
        (d / "fx.dds").write_bytes(_dds(4, 4, b"DXT1", struct.pack("<HHI", color, color, 0)))
    data = GameData(game, cache_dir=tmp_path / "c")
    data.mods.live_mods = [tmp_path / "mod"]
    first = data.particle_atlas("fx.dds")
    assert first is not None
    data.mods.enabled["sprites"] = True  # sprite mods cover particles too
    second = data.particle_atlas("fx.dds")
    assert second is not None
    assert _png_pixels(first[0])[2][:4] != _png_pixels(second[0])[2][:4]
    assert data.mod_roots("particles") == [mod]


def _dx10(width: int, height: int, dxgi: int, body: bytes, mips: int = 1) -> bytes:
    head = bytearray(_dds(width, height, b"DX10", b""))
    struct.pack_into("<I", head, 28, mips)
    return bytes(head) + struct.pack("<IIIII", dxgi, 3, 0, 1, 0) + body


def test_dx10_bc7_dds() -> None:
    from tests.test_bc7 import CASES

    _, block, expected = CASES[0]
    for dxgi in (98, 99):
        w, h, rgba = _png_pixels(dds_to_png(_dx10(4, 4, dxgi, bytes.fromhex(block))))
        assert (w, h) == (4, 4)
        assert rgba.hex() == expected


def test_dx10_bc7_mip_selection() -> None:
    from tests.test_bc7 import CASES

    big = b"".join(bytes.fromhex(c[1]) for c in CASES[:4])  # 8x8 = 4 blocks
    small = bytes.fromhex(CASES[5][1])  # 4x4 mip 1
    w, h, rgba = _png_pixels(dds_to_png(_dx10(8, 8, 98, big + small, mips=2), mip=1))
    assert (w, h) == (4, 4)
    assert rgba.hex() == CASES[5][2]


def test_dx10_bc1_and_unknown_format() -> None:
    block = struct.pack("<HHI", 0xF800, 0xF800, 0)  # solid red
    _, _, rgba = _png_pixels(dds_to_png(_dx10(4, 4, 71, block)))
    assert rgba[:4] == b"\xff\x00\x00\xff"
    with pytest.raises(ValueError, match="unsupported"):
        dds_to_png(_dx10(4, 4, 2, b"\x00" * 16))


def test_terrain_mask_comes_from_the_game_or_a_terrain_mod(tmp_path: Path) -> None:
    game = tmp_path / "AoE2DE"
    masks = game / "resources/_common/terrain/masks"
    masks.mkdir(parents=True)
    (masks / "grass.png").write_bytes(b"game-mask")
    mod = tmp_path / "mod"
    (mod / "resources/_common/terrain/textures").mkdir(parents=True)
    (mod / "resources/_common/terrain/masks").mkdir(parents=True)
    (mod / "resources/_common/terrain/masks/grass.png").write_bytes(b"mod-mask")
    data = GameData(game, cache_dir=tmp_path / "c", mods=G.ModConfig(extra=[mod], live_mods=[]))
    assert data.terrain_mask_png("grass") == b"game-mask"
    assert data.terrain_mask_png("../grass") is None and data.terrain_mask_png("none") is None
    data.mods.enabled["terrain"] = True
    assert data.terrain_mask_png("grass") == b"mod-mask"


def test_map_color_grade_is_read_from_the_map_script(tmp_path: Path) -> None:
    game = tmp_path / "AoE2DE"
    rms = game / "resources/_common/drs/gamedata_x2"
    rms.mkdir(parents=True)
    (rms / "random_map.def").write_text("#const CC_DEFAULT 0\n#const CC_WINTER 2\n")
    (rms / "Fixed.rms").write_text("/* color_correction CC_MISTY */\ncolor_correction CC_WINTER\n")
    (rms / "Plain.rms").write_text("<TERRAIN_GENERATION>\nbase_terrain GRASS\n")
    (rms / "Random.rms").write_text(
        "start_random\npercent_chance 50 color_correction CC_WINTER\nend_random\n"
    )
    (rms / "Biome.rms").write_text("if WINTER_FLAG\ncolor_correction CC_WINTER\nendif\n")
    (rms / "Mood.rms").write_text("color_correction COLOUR_MOOD\n")
    cc = game / "resources/_common/terrain/colorcorrection_json"
    cc.mkdir(parents=True)
    presets = [{"name": "Default", "saturation": 0.99, "sharpness": 0.75}, {"name": "Autumn"}]
    (cc / "colorcorrection.json").write_text(json.dumps({"correction_types": presets}))
    data = GameData(game, cache_dir=tmp_path / "c")
    assert data.map_color_grade("Fixed.rms") == 2  # the comment is ignored
    assert data.map_color_grade("plain.RMS") == 0  # no command: Default
    for unknown in ("Random.rms", "Biome.rms", "Mood.rms", "Missing.rms", "x.txt"):
        assert data.map_color_grade(unknown) is None
    assert data.color_grades == [{"name": "Default", "saturation": 0.99}, {"name": "Autumn"}]


def test_native_windows_install_profiles_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from tests.helpers import FakeWinreg

    reg = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", reg)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.delenv("VANTAGE_GAME_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # Path.home() on Windows
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert G.steam_roots() == [G._WINDOWS_STEAM]  # Steam's registry key is absent
    steam = _library(tmp_path, "Steam")
    other = _library(tmp_path, "SteamLibrary")
    reg.set(reg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath", str(steam))
    hklm = r"SOFTWARE\WOW6432Node\Valve\Steam"
    reg.set(reg.HKEY_LOCAL_MACHINE, hklm, "InstallPath", str(steam))
    assert G.steam_roots() == [str(steam), str(steam), G._WINDOWS_STEAM]
    escaped = str(other).replace("/", "\\\\")  # the vdf escapes backslashes
    vdf = f'"libraryfolders"\n{{\n "1" {{ "path" "{escaped}" }}\n}}\n'
    (steam / "steamapps" / "libraryfolders.vdf").write_text(vdf)
    assert G.steam_libraries() == [steam, other]  # deduplicated
    game = _fake_install(other / "steamapps" / "common")
    assert G.find_game_dir() == game
    assert G.find_game_dir(str(game)) == game  # the live game's own path, as is
    monkeypatch.setattr(G, "steam_libraries", lambda: [])
    # A Z: drive is a real drive on Windows, not the Proton host root.
    assert G.find_game_dir("Z:" + str(game).replace("/", "\\")) is None
    # Profiles live in %USERPROFILE%\Games, not in a Proton prefix.
    assert G.profile_roots() == []
    root = tmp_path / "home" / "Games" / "Age of Empires 2 DE"
    profile = root / "76561198000000000"
    for sub in ("savegame/multi", "modes/Pompeii/savegame"):
        (profile / sub).mkdir(parents=True)
    assert G.profile_roots([steam]) == [root]
    assert G.replay_dirs(G.profile_dirs()) == [
        profile / "modes/Pompeii/savegame",
        profile / "savegame",
        profile / "savegame/multi",
    ]
    # The game's paths are host paths: no Z:/C: mapping either way.
    win = "C:\\Users\\me\\Games\\Age of Empires 2 DE\\76561198000000000\\"
    assert G.host_path(win, game) == Path(win)
    assert G.host_path("\\\\nas\\share\\r.aoe2record") == Path("\\\\nas\\share\\r.aoe2record")
    assert G.host_path("relative\\x") is None and G.host_path("") is None
    assert G.windows_path(Path("D:\\r.aoe2record")) == "D:\\r.aoe2record"
    assert GameData(None).cache_dir == tmp_path / "Local" / "Vantage" / "cache"
    assert GameData(None, cache_dir=tmp_path / "c").cache_dir == tmp_path / "c"


@pytest.mark.skipif(sys.platform == "win32", reason="checks the behaviour off Windows")
def test_registry_is_not_read_off_windows() -> None:
    assert G.registry_value("HKCU", r"Software\Valve\Steam", "SteamPath") is None
    assert G.steam_roots() == list(G.STEAM_ROOTS)
