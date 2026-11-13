"""Read-only access to the installed game's own assets: strings, palettes, icons.

Nothing here is redistributed. Names, civ data, the minimap palette and the
unit/tech/building icons are loaded from the AoE2 DE install at run time
(``$VANTAGE_GAME_DIR`` or the usual Steam library paths), and icons are converted
from the game's DDS textures to PNG into a local cache on first use.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import struct
import sys
import threading
import time
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, cast

from vantage.assetcache import SingleFlight, atomic_write
from vantage.bc7 import decode_bc7
from vantage.paths import local_data_dir

#: Steam roots whose ``steamapps/libraryfolders.vdf`` lists every library.
STEAM_ROOTS = ("~/.steam/steam", "~/.local/share/Steam", "~/.steam/root")
#: AoE2 DE's Steam app id (its Proton prefix is ``compatdata/<id>``).
STEAM_APP_ID = 813780
_PROFILE_IN_PREFIX = Path("pfx/drive_c/users/steamuser/Games/Age of Empires 2 DE")
_CANDIDATES = (
    "~/.local/share/Steam/steamapps/common/AoE2DE",
    "~/.steam/steam/steamapps/common/AoE2DE",
)
#: Steam's default install folder on Windows (the registry normally says so too).
_WINDOWS_STEAM = "C:\\Program Files (x86)\\Steam"
_WINDOWS_CANDIDATES = (_WINDOWS_STEAM + "\\steamapps\\common\\AoE2DE",)


def registry_value(hive: str, key: str, name: str = "") -> object | None:
    """A Windows registry value (``hive`` is ``"HKCU"`` or ``"HKLM"``), or None
    when it or its key is missing, or this is not Windows."""
    if sys.platform != "win32":
        return None
    import winreg

    root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    try:
        with winreg.OpenKey(root, key) as k:
            value: object = winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None
    return value


def steam_roots() -> list[str]:
    """Where Steam itself is installed: :data:`STEAM_ROOTS`, or on Windows the
    folders the registry names plus the default one."""
    if sys.platform != "win32":
        return list(STEAM_ROOTS)
    found = (
        registry_value("HKCU", r"Software\Valve\Steam", "SteamPath"),
        registry_value("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    )
    return [p for p in found if isinstance(p, str) and p] + [_WINDOWS_STEAM]


def steam_libraries(roots: Iterable[str | Path] | None = None) -> list[Path]:
    """Every Steam library folder: the Steam roots plus the paths their
    ``steamapps/libraryfolders.vdf`` lists (``"path"  "/mnt/x"`` lines)."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        # normcase: Windows' registry and libraryfolders.vdf spell paths differently.
        key = str(p.expanduser().resolve()) if p.expanduser().exists() else str(p)
        key = os.path.normcase(key)
        if key not in seen and (p.expanduser() / "steamapps").is_dir():
            seen.add(key)
            out.append(p.expanduser())

    for root in roots if roots is not None else steam_roots():
        r = Path(root).expanduser()
        add(r)
        vdf = r / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            add(Path(m.group(1).replace("\\\\", "/")))
    return out


def profile_roots(libraries: Iterable[Path] | None = None) -> list[Path]:
    """``…/Games/Age of Empires 2 DE`` inside each library's Proton prefix; on
    Windows the user's own (``%USERPROFILE%\\Games``), whatever the libraries."""
    if sys.platform == "win32":
        own = Path.home() / "Games" / "Age of Empires 2 DE"
        return [own] if own.is_dir() else []
    libs = steam_libraries() if libraries is None else libraries
    out = []
    for lib in libs:
        p = lib / "steamapps" / "compatdata" / str(STEAM_APP_ID) / _PROFILE_IN_PREFIX
        if p.is_dir():
            out.append(p)
    return out


def profile_dirs(roots: Iterable[Path] | None = None) -> list[Path]:
    """Per-account profile folders (``<profile root>/<steam id>``, ``0`` offline)."""
    out: list[Path] = []
    for root in profile_roots() if roots is None else roots:
        for d in sorted(root.iterdir()) if root.is_dir() else ():
            if d.is_dir() and d.name.isdigit():
                out.append(d)
    return out


def replay_dirs(profiles: Iterable[Path]) -> list[Path]:
    """Single- and multiplayer replay folders of the given profiles, for AoE2
    and for each game mode (Return of Rome writes to ``modes/Pompeii/savegame``)."""
    patterns = ("savegame", "savegame/multi", "modes/*/savegame", "modes/*/savegame/multi")
    found = {p for prof in profiles for pat in patterns for p in prof.glob(pat) if p.is_dir()}
    return sorted(found)


def host_path(win_path: str, game_dir: Path | None = None) -> Path | None:
    """A path the game (under Proton) reports -> the same path on this host.

    ``Z:\\`` is the host root. ``C:\\`` is the Proton prefix's ``drive_c``,
    found next to the library holding ``game_dir`` (or any library). On Windows
    the game runs natively and its paths are this host's.
    """
    if sys.platform == "win32":
        native = re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", win_path or "")
        return Path(win_path) if native else None
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", win_path or "")
    if m is None:
        return Path(win_path) if win_path and win_path.startswith("/") else None
    drive, rest = m.group(1).upper(), m.group(2).replace("\\", "/").rstrip("/")
    if drive == "Z":
        return Path("/" + rest)
    if drive != "C":
        return None
    libs: list[Path] = []
    if game_dir is not None and game_dir.parent.name == "common":
        libs.append(game_dir.parent.parent.parent)
    libs += steam_libraries()
    for lib in libs:
        c = lib / "steamapps" / "compatdata" / str(STEAM_APP_ID) / "pfx" / "drive_c"
        if c.is_dir():
            return c / rest
    return None


def windows_path(p: Path) -> str:
    """A host path as the game under Proton sees it (``C:\\…`` inside its
    prefix, else ``Z:\\…``, the host root); unchanged on Windows."""
    if sys.platform == "win32":
        return str(p)
    parts = p.parts
    if "drive_c" in parts:
        return "C:\\" + "\\".join(parts[parts.index("drive_c") + 1 :])
    return "Z:" + str(p).replace("/", "\\")


def exe_file_version(exe: Path) -> str | None:
    """``FileVersion`` from a PE file's version resource (e.g. ``101.103.54800.0``).

    Reads only the PE headers and the ``.rsrc`` section, then finds the
    UTF-16 ``FileVersion`` key of the ``VS_VERSIONINFO`` string table; its value
    follows, 32-bit aligned.
    """
    try:
        with exe.open("rb") as fh:
            head = fh.read(4096)
            if head[:2] != b"MZ":
                return None
            pe = struct.unpack_from("<I", head, 0x3C)[0]
            if head[pe : pe + 4] != b"PE\0\0":
                return None
            nsec, opt = (
                struct.unpack_from("<H", head, pe + 6)[0],
                struct.unpack_from("<H", head, pe + 20)[0],
            )
            table = pe + 24 + opt
            for i in range(nsec):
                name, _vsize, _va, raw_size, raw_ptr = struct.unpack_from(
                    "<8sIIII", head, table + 40 * i
                )
                if name.rstrip(b"\0") == b".rsrc":
                    fh.seek(raw_ptr)
                    return _version_value(fh.read(raw_size), "FileVersion")
    except (OSError, struct.error):
        return None
    return None


def _version_value(rsrc: bytes, key: str) -> str | None:
    needle = key.encode("utf-16-le") + b"\0\0"
    i = rsrc.find(needle)
    if i < 0:
        return None
    j = (i + len(needle) + 3) & ~3
    k = j
    while k + 1 < len(rsrc) and rsrc[k : k + 2] != b"\0\0":
        k += 2
    value = rsrc[j:k].decode("utf-16-le", errors="replace").strip()
    return value or None


def installed_build(game_dir: Path | None) -> int | None:
    """The installed game's build (third FileVersion component of
    ``AoE2DE_s.exe``; replays name the same number)."""
    if game_dir is None:
        return None
    version = exe_file_version(game_dir / "AoE2DE_s.exe")
    parts = (version or "").split(".")
    return int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else None


#: Where each kind of mod content lives inside a mod folder.
MOD_SUBDIRS = {
    "graphics": Path("resources/_common/drs/graphics"),
    "sprites": Path("resources/_common/drs/graphics"),
    "terrain": Path("resources/_common/terrain/textures"),
    "particles": Path("resources/_common/particles"),
}
#: Which setting turns each kind on. Sprite mods cover particles too (mod
#: folders are searched for SPRITES and PARTICLES under enableSpriteMods);
#: ``graphics`` is the legacy switch, honoured for both.
_MOD_SWITCHES = {
    "graphics": ("graphics",),
    "sprites": ("sprites",),
    "terrain": ("terrain",),
    "particles": ("sprites", "graphics"),
}


#: Seconds a scan of the mod folders is reused (:meth:`ModConfig._cached`).
MOD_RESCAN_S = 5.0


@dataclass
class ModConfig:
    """Which mods the spectator reads, shared by every :class:`GameData` view
    of one install. Nothing is read from mods unless a kind is enabled."""

    enabled: dict[str, bool] = field(
        default_factory=lambda: dict.fromkeys(("graphics", "sprites", "terrain"), False)
    )
    #: Profile folders whose ``mods/`` the game uses (detected when empty).
    profiles: list[Path] = field(default_factory=list)
    #: The live game's enabled mod folders (``Info.enabledmoddirectories``).
    live_mods: list[Path] | None = None
    #: Extra folders from the UI's ``modDirectories`` setting.
    extra: list[Path] = field(default_factory=list)
    #: Folder scans by (settings, subfolder): (when, folders). See :meth:`_cached`.
    _scans: dict[Any, tuple[float, list[Path]]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _scans_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def _settings(self) -> tuple[Any, ...]:
        """Everything here a scan depends on (the fields are replaced or edited in
        place by the server, so they are read afresh each time)."""
        live = tuple(self.live_mods) if self.live_mods is not None else None
        return (tuple(self.profiles), live, tuple(self.extra))

    def _cached(self, sub: Path | None, scan: Any) -> list[Path]:
        """``scan()`` for these settings, reused for :data:`MOD_RESCAN_S`.

        With graphics or sprite mods on, every sprite request asked for the mod
        folders: a read of ``mod-status.json`` and a listing of the profile's mod
        folders each time. Settings changes take effect at once; a mod installed or
        enabled in the game is seen within the rescan interval.
        """
        key = (self._settings(), sub)
        now = time.monotonic()
        with self._scans_lock:
            got = self._scans.get(key)
        if got is not None and now - got[0] < MOD_RESCAN_S:
            return list(got[1])
        folders: list[Path] = scan()
        with self._scans_lock:
            if len(self._scans) > 64:  # settings that are long gone
                self._scans.clear()
            self._scans[key] = (now, folders)
        return list(folders)

    def mod_folders(self) -> list[Path]:
        """Mod folders in priority order (first wins)."""
        return self._cached(None, self._scan_folders)

    def subfolders(self, sub: Path) -> list[Path]:
        """``<mod>/<sub>`` for each mod folder that has one, in priority order."""
        return self._cached(
            sub, lambda: [m / sub for m in self.mod_folders() if (m / sub).is_dir()]
        )

    def _scan_folders(self) -> list[Path]:
        out: list[Path] = []
        if self.live_mods is not None:
            out += self.live_mods
        else:
            out += _profile_mods(self.profiles or profile_dirs())
        for d in self.extra:
            if (d / "resources").is_dir():
                out.append(d)
            elif d.is_dir():
                out += sorted(c for c in d.iterdir() if (c / "resources").is_dir())
        return list(dict.fromkeys(out))  # first occurrence wins


def _profile_mods(profiles: list[Path]) -> list[Path]:
    """Enabled mods of the most recently used profile, by the game's priority
    (``mods/mod-status.json``; without it every local and subscribed mod)."""
    statuses = [p / "mods" / "mod-status.json" for p in profiles]
    statuses = [s for s in statuses if s.is_file()]
    if statuses:
        newest = max(statuses, key=lambda s: s.stat().st_mtime)
        try:
            mods = json.loads(newest.read_text(encoding="utf-8", errors="replace")).get("Mods", [])
        except (OSError, ValueError):
            mods = []
        on = sorted(
            (m for m in mods if isinstance(m, dict) and m.get("Enabled")),
            key=lambda m: int(m.get("Priority", 0) or 0),
        )
        base = newest.parent
        return [base / Path(*re.split(r"[\\/]+", str(m.get("Path", "")))) for m in on]
    out: list[Path] = []
    for p in profiles:
        for sub in ("local", "subscribed"):
            d = p / "mods" / sub
            if d.is_dir():
                out += sorted(c for c in d.iterdir() if c.is_dir())
    return out


#: UI locale -> the game's resource language directory (the 17 DE languages).
LANGUAGES = {
    "en": "en", "de": "de", "es": "es", "es-MX": "mx", "fr": "fr", "hi": "hi", "it": "it",
    "ja": "jp", "ko": "ko", "ms": "ms", "pl": "pl", "pt-BR": "br", "ru": "ru", "tr": "tr",
    "vi": "vi", "zh-CN": "zh", "zh-TW": "tw",
}  # fmt: skip

#: ``Player.colorIdCurrent`` -> palette file (the game's eight player colours).
PLAYER_COLOR_FILES = (
    "blue",
    "red",
    "green",
    "yellow",
    "teal",
    "purple",
    "grey",
    "orange",
)


def find_game_dir(hint: str | None = None) -> Path | None:
    """Locate the AoE2 DE install. ``hint`` may be the game's own Windows path."""
    options: list[str] = []
    if os.environ.get("VANTAGE_GAME_DIR"):
        options.append(os.environ["VANTAGE_GAME_DIR"])
    if hint and sys.platform == "win32":
        options.append(hint)
    elif hint:
        # The game reports e.g. Z:\mnt\nvme\...; under Proton Z: is the host root.
        m = re.match(r"^[Zz]:\\(.*)$", hint)
        options.append("/" + m.group(1).replace("\\", "/") if m else hint)
    if not os.environ.get("VANTAGE_GAME_DIR"):
        options.extend(str(lib / "steamapps" / "common" / "AoE2DE") for lib in steam_libraries())
    options.extend(_WINDOWS_CANDIDATES if sys.platform == "win32" else _CANDIDATES)
    for opt in options:
        p = Path(opt).expanduser()
        if (p / "resources" / "_common").is_dir():
            return p
    return None


def _read_jasc(path: Path) -> list[tuple[int, int, int]]:
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    if not lines or not lines[0].startswith("JASC"):
        raise ValueError(f"{path} is not a JASC palette")
    n = int(lines[2])
    out = []
    for line in lines[3 : 3 + n]:
        parts = line.split()
        out.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return out


def _float_or(value: Any, default: float) -> float:
    return default if value is None else float(value)


def node_key(n: dict[str, Any]) -> str:
    """A CivTechTrees node's key: ``tech:<Node ID>`` for a tech, else
    ``trigger:<Trigger Tech ID>`` when one is set, else ``unit:<Node ID>``."""
    if n.get("Use Type") == "Tech":
        return f"tech:{n.get('Node ID')}"
    trig = n.get("Trigger Tech ID")
    if trig is not None and trig != -1:
        return f"trigger:{trig}"
    return f"unit:{n.get('Node ID')}"


#: A civ's description string when ``civilizations.json`` names none: civ id + this.
CIV_DESCRIPTION_BASE = 120149
#: Feudal, Castle and Imperial Age research ids (the same in both games).
AGE_TECH_IDS = (101, 102, 103)
#: Settlement building masters (an age requirement any one of which satisfies).
SETTLEMENT_MASTERS = (2556, 2558, 2560)
#: Final unit upgrades for the "Power Techs" strip (tech ids from the game's
#: tech trees): paladin, champion (both upgrade paths), arbalester, heavy cavalry
#: archer, halberdier, hussar, siege onager/ram, heavy scorpion, houfnice,
#: siege elephant, heavy demolition ship, heavy warships/galleon, fast fire ship,
#: bombard tower, elite cannon galleon, carrack, the regional elite lines,
#: winged hussar, savar, legionary, imperial skirmisher and camel, dragon ship.
POWER_TECHS = (
    265, 264, 1174, 237, 218, 429, 428, 320, 255, 239, 787, 838, 244, 35, 246, 64,
    376, 904, 434, 1352, 982, 1454, 481, 1451, 631, 236, 715, 1033, 980, 372,
    786, 526, 885, 655, 521, 1010,
)  # fmt: skip
#: The only hover-tree groups an antiquity civ shows (its economy row).
ANTIQUITY_ECONOMY = frozenset(
    {"lumber", "farm", "wheelCart", "goldMining", "stoneMining", "coinageBanking",
     "guilds", "caravan"}
)  # fmt: skip


def _g(key: str, *stages: str, regional: str | None = None,
       variants: tuple[tuple[str, tuple[str, ...]], ...] = ()) -> dict[str, Any]:  # fmt: skip
    return {"key": key, "stages": stages, "regional": regional, "variants": variants}


#: The hover tech tree's nine headed rows of named groups. Stages are
#: CivTechTrees node keys (:func:`node_key`) in tier order. ``regional`` drops
#: the group when that base node is regional-hidden for the civ; ``variants``
#: replace the stages when the variant's key is available to the civ.
TREE_LAYOUT: tuple[tuple[str, str, tuple[dict[str, Any], ...]], ...] = (
    ("economy", "Economy", (
        _g("loom", "tech:22"),
        _g("wheelCart", "tech:213", "tech:249"),
        _g("townWatch", "tech:8", "tech:280"),
        _g("lumber", "tech:202", "tech:203", "tech:221"),
        _g("farm", "tech:14", "tech:13", "tech:12",
           variants=(("tech:1014", ("tech:1014", "tech:1013", "tech:1012")),)),
        _g("goldMining", "tech:55", "tech:182"),
        _g("stoneMining", "tech:278", "tech:279"),
        _g("caravan", "tech:48"),
        _g("coinageBanking", "tech:23", "tech:17"),
        _g("guilds", "tech:15"),
    )),
    ("infantry", "Infantry", (
        _g("infantryLine", "unit:74", "trigger:222", "trigger:207", "trigger:217", "trigger:264",
           variants=(("trigger:885", ("unit:74", "trigger:222", "trigger:207", "trigger:885")),)),
        _g("spearLine", "unit:93", "trigger:197", "trigger:429"),
        _g("eagleLine", "unit:751", "trigger:384", "trigger:434", regional="unit:751"),
        _g("champiLine", "trigger:1350", "trigger:1402", "trigger:1351", "trigger:1352",
           regional="trigger:1350"),
        _g("fireLancerLine", "unit:1901", "trigger:982", regional="unit:1901"),
        _g("varangianGuardLine", "unit:2703", "trigger:1454", regional="unit:2703"),
        _g("meleeAttack", "tech:67", "tech:68", "tech:75"),
        _g("infantryArmor", "tech:74", "tech:76", "tech:77"),
        _g("squires", "tech:215"),
        _g("arson", "tech:602"),
        _g("gambesons", "tech:875"),
        _g("supplies", "tech:716"),
    )),
    ("archery", "Archery", (
        _g("archerLine", "unit:4", "trigger:100", "trigger:237"),
        _g("skirmisherLine", "unit:7", "trigger:98",
           variants=(("trigger:655", ("unit:7", "trigger:98", "trigger:655")),)),
        _g("cavalryArcherLine", "unit:39", "trigger:218"),
        _g("handCannoneer", "unit:5"),
        _g("eleArcherLine", "unit:873", "trigger:481", regional="unit:873"),
        _g("mountedCrossbowmanLine", "unit:2700", "trigger:1451", regional="unit:2700"),
        _g("slinger", "unit:185", regional="unit:185"),
        _g("rangedAttack", "tech:199", "tech:200", "tech:201"),
        _g("archerArmor", "tech:211", "tech:212", "tech:219"),
        _g("thumbRing", "tech:437"),
        _g("parthianTactics", "tech:436"),
        _g("cranequins", "tech:1452"),
    )),
    ("cavalry", "Cavalry", (
        _g("scoutLine", "unit:448", "trigger:254", "trigger:428",
           variants=(("trigger:786", ("unit:448", "trigger:254", "trigger:786")),)),
        _g("knightLine", "unit:38", "trigger:209", "trigger:265",
           variants=(("trigger:526", ("unit:38", "trigger:209", "trigger:526")),)),
        _g("camelLine", "unit:329", "trigger:236", regional="unit:329",
           variants=(("unit:1755", ("unit:1755", "unit:329", "trigger:236")),
                     ("trigger:521", ("unit:329", "trigger:236", "trigger:521")))),
        _g("battleEleLine", "trigger:630", "trigger:631", regional="trigger:630"),
        _g("steppeLancerLine", "unit:1370", "trigger:715", regional="unit:1370"),
        _g("heiGuangLine", "unit:1944", "trigger:1033", regional="unit:1944"),
        _g("cavalryArmor", "tech:81", "tech:82", "tech:80"),
        _g("bloodlines", "tech:435"),
        _g("husbandry", "tech:39"),
    )),
    ("siege", "Siege", (
        _g("ramLine", "unit:1258", "trigger:96", "trigger:255"),
        _g("mangonelLine", "unit:280", "trigger:257", "trigger:320"),
        _g("scorpionLine", "unit:279", "trigger:239"),
        _g("siegeTower", "unit:1105"),
        _g("bombardCannon", "unit:36", variants=(("trigger:787", ("unit:36", "trigger:787")),)),
        _g("siegeEleLine", "unit:1744", "trigger:838", regional="unit:1744"),
        _g("rocketCartLine", "unit:1904", "trigger:980", regional="unit:1904"),
        _g("tractionTreb", "unit:1942", regional="unit:1942"),
    )),
    ("naval", "Naval", (
        _g("fishingShip", "unit:13"),
        _g("gillnets", "tech:906", "tech:65"),
        _g("transportShip", "unit:545"),
        _g("tradeCog", "unit:17"),
        _g("galleyLine", "unit:539", "tech:34", "trigger:35"),
        _g("hulkLine", "unit:2626", "tech:34", "trigger:904"),
        _g("fireShipLine", "unit:1103", "trigger:34", "trigger:246",
           variants=(("trigger:1010", ("unit:1103", "trigger:34", "trigger:1010")),)),
        _g("demoShipLine", "unit:1104", "trigger:905", "trigger:244"),
        _g("cannonGalleonLine", "unit:420", "trigger:376"),
        _g("longshipLine", "unit:250", "trigger:372", regional="unit:250"),
        _g("dromon", "unit:1795", regional="unit:1795"),
        _g("catapultGalleon", "unit:2633", regional="unit:2633"),
        _g("louChuan", "unit:1948", regional="unit:1948"),
        _g("careening", "tech:374", "tech:375"),
        _g("shipwright", "tech:373"),
        _g("carvelHullClinkerConstruction", "tech:908", "tech:907"),
        _g("siphonsIncendiaries", "tech:909", "tech:910"),
    )),
    ("monastery", "Monastery", (
        _g("monk", "unit:125"),
        _g("redemption", "tech:316"),
        _g("atonement", "tech:319"),
        _g("herbalMedicine", "tech:441"),
        _g("heresy", "tech:439"),
        _g("sanctity", "tech:231"),
        _g("fervor", "tech:252"),
        _g("devotion", "tech:46"),
        _g("faith", "tech:45"),
        _g("illumination", "tech:233"),
        _g("blockPrinting", "tech:230"),
        _g("theocracy", "tech:438"),
    )),
    ("defensive", "Defensive", (
        _g("walls", "unit:72", "unit:117", "unit:155"),
        _g("gate", "unit:487"),
        _g("towerLine", "unit:79", "unit:234", "unit:235"),
        _g("bombardTower", "unit:236"),
        _g("masonry", "tech:50", "tech:51"),
        _g("murderHoles", "tech:322"),
        _g("arrowslits", "tech:608"),
        _g("heatedShot", "tech:380"),
        _g("hoardings", "tech:379"),
    )),
    ("misc", "Miscellaneous", (
        _g("petard", "unit:440"),
        _g("trebuchet", "unit:331"),
        _g("ballistics", "tech:93"),
        _g("chemistry", "tech:47"),
        _g("siegeEngineers", "tech:377"),
        _g("treadmillCrane", "tech:54"),
        _g("conscription", "tech:315"),
        _g("sappers", "tech:321"),
        _g("spiesTreason", "tech:408"),
    )),
)  # fmt: skip


@dataclass(frozen=True)
class TerrainType:
    """One row of the game's terrain table (same meaning as the stream's TerrainType)."""

    pict: str
    rows: int
    mask: str
    color: int


_DAT_STRING = b"\x60\x0a"
_TERRAIN_FIRST = _DAT_STRING + b"\x05\x00Grass" + _DAT_STRING + b"\x05\x00g_grs"
#: Bytes between the picture name and the mask name, and field offsets after the mask.
_TERRAIN_NAME_GAP = 28
_TERRAIN_COLOR_OFFSET = 1
_TERRAIN_ROWS_OFFSET = 146
_TERRAIN_COUNT = 200


def _dat_string(d: bytes, offset: int) -> tuple[str, int]:
    if d[offset : offset + 2] != _DAT_STRING:
        raise ValueError(f"no terrain string at {offset:#x}")
    size = struct.unpack_from("<H", d, offset + 2)[0]
    end = offset + 4 + size
    if end > len(d):
        raise ValueError("truncated terrain string")
    return d[offset + 4 : end].decode("latin-1"), end


def parse_terrain_types(d: bytes) -> list[TerrainType]:
    """Read the terrain table from a decompressed ``empires2_x2_p1.dat``.

    Layout was checked against a game-streamed table (134 of 134 rows) and is the
    same in the build 54800 and 57257 data files. Raises ValueError if it differs.
    """
    offset = d.find(_TERRAIN_FIRST)
    if offset < 0:
        raise ValueError("terrain table not found")
    rows: list[TerrainType] = []
    for index in range(_TERRAIN_COUNT):
        _name, offset = _dat_string(d, offset)
        pict, offset = _dat_string(d, offset)
        mask, tail = _dat_string(d, offset + _TERRAIN_NAME_GAP)
        rows.append(
            TerrainType(
                pict,
                struct.unpack_from("<H", d, tail + _TERRAIN_ROWS_OFFSET)[0],
                mask,
                d[tail + _TERRAIN_COLOR_OFFSET],
            )
        )
        if index + 1 < _TERRAIN_COUNT:
            offset = d.find(_DAT_STRING, tail)
            if offset < 0:
                raise ValueError("truncated terrain table")
    return rows


class GameData:
    """Lazily-loaded game assets. Every accessor degrades to a neutral default."""

    def __init__(
        self,
        game_dir: Path | None,
        cache_dir: Path | None = None,
        mode: str | None = None,
        mods: ModConfig | None = None,
    ) -> None:
        self.game_dir = game_dir
        if cache_dir is None and sys.platform == "win32":
            cache_dir = local_data_dir() / "cache"
        base = os.environ.get("XDG_CACHE_HOME", "~/.cache")
        self.cache_dir = cache_dir or Path(base).expanduser() / "vantage"
        #: Game mode folder under ``modes/`` (``Pompeii`` = Return of Rome), or
        #: None for Age of Empires II. A mode's data shadows the base game's.
        self.mode = mode if mode and re.fullmatch(r"\w+", mode) else None
        self._lang_strings: dict[str, dict[int, str]] = {}
        #: Mod settings, shared with every view of this install (``with_mode``).
        self.mods = mods if mods is not None else ModConfig()
        #: Conversions in progress by cache file: concurrent requests convert once.
        self._converting: SingleFlight[Any] = SingleFlight()
        self._upgrade_tables: dict[int, tuple[dict[str, list[int]], dict[int, dict[str, Any]]]] = {}

    def mod_roots(self, kind: str) -> list[Path]:
        """Folders holding ``kind`` content ('graphics', 'sprites', 'terrain',
        'particles') of the enabled mods, highest priority first; empty while
        that kind is off."""
        sub = MOD_SUBDIRS.get(kind)
        if sub is None or not any(self.mods.enabled.get(k) for k in _MOD_SWITCHES[kind]):
            return []
        return self.mods.subfolders(sub)

    @cached_property
    def build(self) -> int | None:
        """The installed game's build number (None when unknown)."""
        return installed_build(self.game_dir)

    @property
    def available(self) -> bool:
        return self.game_dir is not None

    @property
    def game(self) -> str:
        """``ror`` for Return of Rome, else ``aoe2``."""
        return "ror" if self.mode == "Pompeii" else "aoe2"

    def with_mode(self, mode: str | None) -> GameData:
        """The same install seen through a game mode (None = AoE2)."""
        if (mode or None) == self.mode:
            return self
        return GameData(self.game_dir, self.cache_dir, mode, self.mods)

    def roots(self) -> list[Path]:
        """Data roots in lookup order: the mode's folder first, then the base game."""
        if self.game_dir is None:
            return []
        roots = [self.game_dir]
        if self.mode is not None and (self.game_dir / "modes" / self.mode).is_dir():
            roots.insert(0, self.game_dir / "modes" / self.mode)
        return roots

    def dat_path(self, name: str) -> Path | None:
        """A file under ``resources/_common/dat``, the mode's copy winning."""
        for root in self.roots():
            p = root / "resources" / "_common" / "dat" / name
            if p.exists():
                return p
        return None

    @cached_property
    def _material_files(self) -> dict[str, Path]:
        """``widgetui/materials.json``: material name -> PNG file, through the
        material's texture ref (an atlas entry's own file or a plain texture)."""
        out: dict[str, Path] = {}
        for root in reversed(self.roots()):  # the mode's copy is read last, so it wins
            try:
                raw = json.loads((root / "widgetui" / "materials.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            files: dict[str, str] = {}
            for atlas in raw.get("AtlasTextures", ()):
                for tex in (atlas.get("AtlasDef") or {}).get("Textures", ()):
                    if isinstance(tex, dict) and tex.get("RefName") and tex.get("FileName"):
                        files[str(tex["RefName"])] = str(tex["FileName"])
            for tex_def in raw.get("GlobalTextures", ()):
                d = tex_def.get("TextureDef") if isinstance(tex_def, dict) else None
                if isinstance(d, dict) and d.get("Name") and d.get("FileName"):
                    files[str(d["Name"])] = str(d["FileName"])
            for mat in raw.get("Materials", ()):
                d = mat.get("MaterialDef") if isinstance(mat, dict) else None
                if not isinstance(d, dict) or not d.get("Name"):
                    continue
                rel = files.get(str(d.get("TextureRef") or d["Name"]))
                path = root / "widgetui" / rel if rel else None
                if path is not None and path.suffix.lower() == ".png" and path.is_file():
                    out[str(d["Name"])] = path
        return out

    def material_png(self, name: str) -> Path | None:
        """The PNG behind a UI material name (e.g. ``TTTechtreepanelArchaicAgeImage``)."""
        return self._material_files.get(name)

    # -- strings ------------------------------------------------------------

    @cached_property
    def strings(self) -> dict[int, str]:
        return self.strings_for("en")

    def strings_for(self, lang: str) -> dict[int, str]:
        """The game's string table in one of its languages (``LANGUAGES``)."""
        lang = LANGUAGES.get(lang, lang)
        cached = self._lang_strings.get(lang)
        if cached is not None:
            return cached
        out: dict[int, str] = {}
        if self.game_dir is None or not re.fullmatch(r"[a-z]{2}", lang):
            return out
        pat = re.compile(r'^(\d+)\s+"(.*)"\s*$')
        files: list[Path] = []
        for root in self.roots():
            kv = root / "resources" / lang / "strings" / "key-value"
            if root != self.game_dir:  # a mode ships its own table(s), which win
                files += sorted(kv.glob("*.txt")) if kv.is_dir() else []
            else:
                # The main tables first; the rest of the folder fills ids only
                # they carry (aura descriptions, the antiquity civs' names).
                names = ("key-value-strings-utf8.txt", "key-value-modded-strings-utf8.txt")
                files += [kv / n for n in names]
                rest = sorted(kv.glob("*.txt")) if kv.is_dir() else []
                files += [p for p in rest if p.name not in names]
        for path in files:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                m = pat.match(line)
                if m:
                    out.setdefault(int(m.group(1)), m.group(2).replace("\\n", "\n"))
        self._lang_strings[lang] = out
        return out

    def string(self, sid: int | None, default: str = "") -> str:
        if sid is None or sid < 0:
            return default
        return self.strings.get(int(sid), default)

    # -- civs -----------------------------------------------------------------

    @cached_property
    def civs(self) -> list[dict[str, Any]]:
        if self.game_dir is None:
            return []
        path = self.dat_path("civilizations.json")
        if path is None:
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        civs: list[dict[str, Any]] = data.get("civilization_list", [])
        return civs

    def civ_name(self, civ_id: int | None) -> str:
        if civ_id is None or not 0 <= civ_id < len(self.civs):
            return f"Civ {civ_id}"
        c = self.civs[civ_id]
        return self.string(c.get("name_string_id"), str(c.get("internal_name", civ_id)))

    def civ_era(self, civ_id: int | None) -> str:
        """``civilizations.json`` ``era`` of a civ: ``antiquity`` or ``base``."""
        if civ_id is None or not 0 <= civ_id < len(self.civs):
            return "base"
        return str(self.civs[civ_id].get("era") or "base")

    def eras(self, lang: str = "en") -> dict[str, dict[str, Any]]:
        """``dat/eras.json`` by era name: the age names/shields and, for the
        antiquity civs, the tech display overrides (name, icon, description)."""
        path = self.dat_path("eras.json")
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path is not None else []
        except (OSError, ValueError):
            raw = []
        table = self.strings_for(lang)
        out: dict[str, dict[str, Any]] = {}
        for era in raw if isinstance(raw, list) else ():
            if not isinstance(era, dict) or not era.get("Name"):
                continue
            ages = [
                {
                    "name_id": a.get("NameId"),
                    "name": table.get(int(a["NameId"]), "") if a.get("NameId") else "",
                    "shield": a.get("ShieldMaterialName", ""),
                    "icon_material": a.get("TechTreeIconMaterialName", ""),
                }
                for a in era.get("Ages", [])
                if isinstance(a, dict)
            ]
            for a in ages:
                # The age's own image (antiquity: Archaic/Civic/Classical/Paphos Imperial),
                # served by /ui/material/<name>.png; the generic shield names have none.
                for key in ("shield", "icon_material"):
                    if a[key] and self.material_png(str(a[key])) is not None:
                        a["icon"] = f"/ui/material/{a[key]}.png"
                        break
            techs: dict[str, dict[str, Any]] = {}
            for o in era.get("TechDisplayOverrides", []) or ():
                if not isinstance(o, dict) or o.get("TechId") is None:
                    continue
                entry: dict[str, Any] = {}
                if o.get("NameId") is not None:
                    entry["name"] = table.get(int(o["NameId"]), "")
                    entry["name_id"] = int(o["NameId"])
                if o.get("IconId") is not None:
                    entry["icon"] = int(o["IconId"])
                if o.get("DescriptionId") is not None:
                    entry["description"] = table.get(int(o["DescriptionId"]), "")
                techs[str(int(o["TechId"]))] = entry
            out[str(era["Name"])] = {"ages": ages, "techs": techs}
        return out

    # -- unit lines -------------------------------------------------------------

    @cached_property
    def _unit_lines_raw(self) -> list[dict[str, Any]]:
        path = self.dat_path("unitlines.json") or self.dat_path("unitLines.json")
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path is not None else {}
        except (OSError, ValueError):
            return []
        lines = raw.get("UnitLines", []) if isinstance(raw, dict) else []
        return [x for x in lines if isinstance(x, dict) and isinstance(x.get("IDChain"), list)]

    def unit_line_table(self) -> dict[str, dict[str, Any]]:
        """The game's unit lines (``dat/unitlines.json``) by line key ``l<LineID>``:
        ``{name, identifier, ids, building}``."""
        out: dict[str, dict[str, Any]] = {}
        for x in self._unit_lines_raw:
            ident = x.get("Identifier")
            first = ident[0] if isinstance(ident, list) and ident else ident
            out[f"l{x.get('LineID')}"] = {
                "name": str(x.get("Name", "")),
                "identifier": str(first or ""),
                "ids": [int(i) for i in x["IDChain"] if isinstance(i, int)],
                "building": bool(x.get("Building")),
            }
        return out

    @cached_property
    def unit_lines(self) -> dict[int, str]:
        """Master id -> unit-line key, for every id in a line's ``IDChain``."""
        out: dict[int, str] = {}
        for key, line in self.unit_line_table().items():
            for mid in line["ids"]:
                out.setdefault(mid, key)
        return out

    @cached_property
    def _upgrade_facts(self) -> dict[str, Any] | None:
        """Installed effects, cached by dat content and pinned parser version.

        Unsupported/missing data produces an explicit unavailable UI, never a
        fallback to tree-layout guesses. Concurrent tree requests parse once.
        """

        def load() -> dict[str, Any] | None:
            path = self.dat_path("empires2_x2_p1.dat")
            if path is None:
                return None
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                cache = self.cache_dir / "upgrades" / f"genie-0.1.2-v3-{digest}.json"
                try:
                    return json.loads(cache.read_text())  # type: ignore[no-any-return]
                except (OSError, ValueError):
                    pass
                from vantage.upgrades import read_effects

                facts = read_effects(str(path))
                atomic_write(cache, json.dumps(facts, separators=(",", ":")).encode())
                return facts
            except (OSError, ValueError, EOFError, struct.error, zlib.error, NotImplementedError):
                return None

        return cast(dict[str, Any] | None, self._converting.run("upgrade-facts", load))

    @cached_property
    def starting_resource_techs(self) -> dict[int, tuple[int, list[float]]]:
        """Automatic civilization techs that change the starting stockpile.

        Research id -> (civilization id, [food, wood, stone, gold]), read from
        the installed dat: effect commands that add to the starting-resource
        attributes 91-94 (Persians +50 food and wood, Chinese -200 food and
        -50 wood, Huns -100 wood ...). Empty when the dat is unavailable.
        """
        facts = self._upgrade_facts
        if not facts:
            return {}
        # The dat's order is food, wood, stone, gold: the same as ours.
        out: dict[int, tuple[int, list[float]]] = {}
        effects = facts["effects"]
        for tid, tech in enumerate(facts["techs"]):
            if not 0 <= tech["effect"] < len(effects):
                continue
            amounts = [0.0] * 4
            for kind, a, mode, _, value in effects[tech["effect"]]:
                if kind == 1 and 91 <= a <= 94 and mode == 1:
                    amounts[int(a) - 91] += float(value)
            if any(amounts):
                out[tid] = (int(tech["civ"]), amounts)
        return out

    def relevant_upgrades(self, civ_id: int) -> dict[str, list[int]]:
        """Object ID -> relevant research IDs, already gated and ordered for a civ."""
        return self._upgrade_table(civ_id)[0]

    def _upgrade_table(self, civ_id: int) -> tuple[dict[str, list[int]], dict[int, dict[str, Any]]]:
        tables = self._upgrade_tables
        if civ_id in tables:
            return tables[civ_id]

        def build() -> tuple[dict[str, list[int]], dict[int, dict[str, Any]]]:
            facts = self._upgrade_facts
            if facts is None or not 0 <= civ_id < len(facts["units"]):
                return {}, {}
            available: set[int] = set()
            ages: dict[int, int] = {}
            for node in self._all_trees.get(civ_id, {}).values():
                if node.get("Node Status") == "NotAvailable":
                    continue
                tid = (
                    node.get("Node ID")
                    if node.get("Use Type") == "Tech"
                    else node.get("Trigger Tech ID")
                )
                if tid is not None and int(tid) >= 0:
                    available.add(int(tid))
                    ages[int(tid)] = int(node.get("Age ID", 1) or 1)
            unique = {t for values in self.unique_tech_ids.get(civ_id, {}).values() for t in values}
            # Always use English game help for the semantic resource-flag rule;
            # switching the UI language must not change the upgrade IDs.
            descriptions = {
                int(uid): self.string(u["help"] - 79000)
                for uid, u in facts["units"][civ_id].items()
            }
            from vantage.upgrades import relevance

            town_centers = {
                int(uid)
                for uid, u in facts["units"][civ_id].items()
                if self.string(u["sid"]) == "Town Center"
            }
            mapping, order, line_units = relevance(
                facts, civ_id, available, unique, descriptions, town_centers
            )
            metadata = {}
            for tid in {t for ids in mapping.values() for t in ids}:
                tech = facts["techs"][tid]
                metadata[tid] = {
                    "id": tid,
                    "name": self.string(tech["sid"], tech["name"]),
                    "sid": tech["sid"],
                    "icon": tech["icon"],
                    "age": ages.get(tid, 1),
                    "order": order[tid],
                    "line_units": line_units.get(tid, []),
                    "status": "available",
                }
            result = mapping, metadata
            tables[civ_id] = result
            return result

        return cast(
            tuple[dict[str, list[int]], dict[int, dict[str, Any]]],
            self._converting.run(("upgrade-civ", civ_id), build),
        )

    # -- civ tech trees -----------------------------------------------------------

    def _tree_raw(self, civ_id: int) -> dict[str, Any] | None:
        if not 0 <= civ_id < len(self.civs):
            return None
        name = self.civs[civ_id].get("tech_tree_name")
        tree_dir = self.dat_path("CivTechTrees")
        if tree_dir is None or not name:
            return None
        try:
            raw = json.loads((tree_dir / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return raw if isinstance(raw, dict) else None

    @cached_property
    def _all_trees(self) -> dict[int, dict[str, dict[str, Any]]]:
        """civ id -> {node key -> raw node} for every civ with a tree (Gaia none)."""
        out: dict[int, dict[str, dict[str, Any]]] = {}
        for cid, civ in enumerate(self.civs):
            if str(civ.get("internal_name", "")).lower() == "gaia":
                continue
            raw = self._tree_raw(cid)
            if raw is None:
                continue
            nodes: dict[str, dict[str, Any]] = {}
            for n in [*raw.get("civ_techs_units", []), *raw.get("civ_techs_buildings", [])]:
                if isinstance(n, dict):
                    nodes.setdefault(node_key(n), n)
            out[cid] = nodes
        return out

    @cached_property
    def _never_struck(self) -> frozenset[str]:
        """Node keys some civ lists and no civ marks NotAvailable."""
        listed: set[str] = set()
        struck: set[str] = set()
        for nodes in self._all_trees.values():
            for k, n in nodes.items():
                listed.add(k)
                if n.get("Node Status") == "NotAvailable":
                    struck.add(k)
        return frozenset(listed - struck)

    @cached_property
    def _union_nodes(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for cid in sorted(self._all_trees):
            for k, n in self._all_trees[cid].items():
                if self.civ_era(cid) == "base" or k not in out:
                    out.setdefault(k, n)
        return out

    def availability(self, civ_id: int) -> tuple[set[str], set[str]]:
        """(not available, regional hidden) node keys of one civ.

        Not available = the civ's NotAvailable nodes plus every node another civ
        lists and this one does not. Regional hidden = the subset of those that
        no civ marks NotAvailable (regional content: hidden, not struck).
        """
        mine = self._all_trees.get(civ_id, {})
        na = {k for k, n in mine.items() if n.get("Node Status") == "NotAvailable"}
        absent = {k for nodes in self._all_trees.values() for k in nodes} - mine.keys()
        hidden = absent & self._never_struck
        return na | absent, hidden

    @cached_property
    def unique_tech_ids(self) -> dict[int, dict[str, list[int]]]:
        """civ id -> ``{castle: [...], imperial: [...]}`` unique techs: castle
        (building 82) techs of age 3 / 4 that exactly one civ lists; when a civ
        has none, ``civilizations.json`` unique_tech_id_2 / _1."""
        owners: dict[int, set[int]] = {}
        ages: dict[int, int] = {}
        for cid, nodes in self._all_trees.items():
            for n in nodes.values():
                if n.get("Use Type") == "Tech" and n.get("Building ID") == 82:
                    tid = int(n.get("Node ID", -1))
                    owners.setdefault(tid, set()).add(cid)
                    ages[tid] = int(n.get("Age ID", 0) or 0)
        out: dict[int, dict[str, list[int]]] = {}
        for cid, civ in enumerate(self.civs):
            if cid not in self._all_trees:
                continue
            castle = sorted(t for t, o in owners.items() if o == {cid} and ages[t] == 3)
            imperial = sorted(t for t, o in owners.items() if o == {cid} and ages[t] == 4)
            if not castle and int(civ.get("unique_tech_id_2", -1) or -1) >= 0:
                castle = [int(civ["unique_tech_id_2"])]
            if not imperial and int(civ.get("unique_tech_id_1", -1) or -1) >= 0:
                imperial = [int(civ["unique_tech_id_1"])]
            out[cid] = {"castle": castle, "imperial": imperial}
        return out

    def pasture_civs(self) -> list[int]:
        """Civs that farm with pastures: Transhumance (tech 1012) is available."""
        return [cid for cid in self._all_trees if "tech:1012" not in self.availability(cid)[0]]

    def power_tech_ids(self) -> list[int]:
        """The "Power Techs" strip: final unit upgrades, every civ's elite unique
        unit upgrade and unique techs, and the age techs."""
        out = set(POWER_TECHS) | set(AGE_TECH_IDS)
        for cid, ut in self.unique_tech_ids.items():
            out.update(ut["castle"])
            out.update(ut["imperial"])
            up = int(self.civs[cid].get("unique_unit_upgrade_id", -1) or -1)
            if up >= 0:
                out.add(up)
        return sorted(out)

    def tech_tree(self, civ_id: int, lang: str = "en") -> dict[str, Any] | None:
        """A civ's tech tree from ``dat/CivTechTrees``: buildings and the units and
        techs each offers, by age, with the civ's availability, plus the hover
        tree's nine-row layout (see :data:`TREE_LAYOUT`)."""
        if self.game_dir is None or not 0 <= civ_id < len(self.civs):
            return None
        table = self.strings_for(lang)

        def string(sid: Any, default: str) -> str:
            return table.get(int(sid), default) if sid is not None else default

        raw = self._tree_raw(civ_id)
        if raw is None:
            return None
        not_available, hidden = self.availability(civ_id)

        def status(key: str, n: dict[str, Any] | None) -> str:
            if key in hidden:
                return "hidden"
            if key in not_available or (n is not None and n.get("Node Status") == "NotAvailable"):
                return "struck"
            return "available"

        buildings = []
        for b in raw.get("civ_techs_buildings", []):
            key = node_key(b)
            buildings.append(
                {
                    "id": b.get("Node ID"),
                    "key": key,
                    "name": string(b.get("Name String ID"), b.get("Name", "")),
                    "icon": b.get("Picture Index", -1),
                    "age": b.get("Age ID", 1),
                    "available": b.get("Node Status") != "NotAvailable",
                    "status": status(key, b),
                }
            )
        nodes = []
        for n in raw.get("civ_techs_units", []):
            kind = "unit" if n.get("Use Type") == "Unit" else "tech"
            key = node_key(n)
            nodes.append(
                {
                    "id": n.get("Node ID"),
                    "key": key,
                    "kind": kind,
                    "name": string(n.get("Name String ID"), n.get("Name", "")),
                    "building": n.get("Building ID"),
                    "age": n.get("Age ID", 1),
                    "icon": n.get("Picture Index", -1),
                    "available": n.get("Node Status") != "NotAvailable",
                    "status": status(key, n),
                    # The node this one upgrades from / the tech that unlocks it.
                    "link": n.get("Link ID"),
                    "trigger_tech": n.get("Trigger Tech ID"),
                }
            )
        civ = self.civs[civ_id]
        desc_id = civ.get("tech_tree_description_string_id")
        if desc_id is None:
            desc_id = civ_id + CIV_DESCRIPTION_BASE
        uts = self.unique_tech_ids.get(civ_id, {"castle": [], "imperial": []})
        era = self.civ_era(civ_id)
        relevant, upgrade_techs = self._upgrade_table(civ_id)
        return {
            "civ": civ_id,
            "name": string(civ.get("name_string_id"), self.civ_name(civ_id)),
            "era": era,
            # The civ's help text (bonuses, unique units and techs, team bonus);
            # line breaks are kept, the game's <b> markup too.
            "description": string(desc_id, ""),
            "description_string_id": int(desc_id),
            "unique_units": self._unique_units(civ, string),
            "buildings": buildings,
            "nodes": nodes,
            "not_available": sorted(not_available),
            "regional_hidden": sorted(hidden),
            "unique_techs": uts,
            "relevant_upgrades": relevant,
            "upgrade_relevance_available": self._upgrade_facts is not None,
            "upgrade_techs": {
                tid: {**tech, "name": string(tech["sid"], tech["name"])}
                for tid, tech in upgrade_techs.items()
            },
            "layout": None
            if self.game == "ror"
            else self._layout(civ_id, era, uts, not_available, hidden, string),
        }

    @staticmethod
    def _unique_units(civ: dict[str, Any], string: Any) -> list[dict[str, Any]]:
        """Unique-unit icons (``unique_unit_image_paths``: the digits before the
        ``_`` are the unit icon id) with their name and description strings."""
        out: list[dict[str, Any]] = []
        texts = civ.get("unique_unit_string_ids") or []
        for i, path in enumerate(civ.get("unique_unit_image_paths") or []):
            m = re.match(r"^(\d+)_", Path(str(path)).name)
            if m is None:
                continue
            t = texts[i] if i < len(texts) and isinstance(texts[i], dict) else {}
            out.append(
                {
                    "icon": int(m.group(1)),
                    "name": string(t.get("name"), ""),
                    "description": string(t.get("description"), ""),
                }
            )
        return out

    def _layout(
        self,
        civ_id: int,
        era: str,
        uts: dict[str, list[int]],
        not_available: set[str],
        hidden: set[str],
        string: Any,
    ) -> dict[str, Any]:
        """The hover tree: nine headed rows of named groups, each a list of tier
        stages with ``available`` / ``struck`` / ``hidden`` status."""
        mine = self._all_trees.get(civ_id, {})
        union = self._union_nodes

        def available(key: str) -> bool:
            return key in mine and key not in not_available

        def stage(key: str) -> dict[str, Any] | None:
            n = mine.get(key) or union.get(key)
            if n is None:
                return None
            kind, _, num = key.partition(":")
            sid = n.get("Name String ID")
            name = string(sid, "") if sid is not None else ""
            if not name and sid is not None:
                name = string(int(sid) - 9000, str(n.get("Name", "")))
            st = (
                "hidden"
                if key in hidden
                else "struck"
                if key in not_available or n.get("Node Status") == "NotAvailable"
                else "available"
            )
            is_unit = n.get("Use Type") == "Unit"
            return {
                "key": key,
                "kind": "unit" if is_unit else "tech",
                "id": int(n.get("Node ID", -1)),
                "tech": int(num) if kind in ("tech", "trigger") else None,
                "unit": int(n.get("Node ID", -1)) if is_unit else None,
                "name": name or str(n.get("Name", "")),
                "icon": int(n.get("Picture Index", -1)),
                "icon_kind": "unit" if is_unit else "tech",
                "age": int(n.get("Age ID", 1) or 1),
                "status": st,
            }

        rows: list[dict[str, Any]] = []
        for row_key, row_name, groups in TREE_LAYOUT:
            if era == "antiquity" and row_key != "economy":
                continue
            out_groups: list[dict[str, Any]] = []
            for g in groups:
                gkey = str(g["key"])
                if era == "antiquity" and gkey not in ANTIQUITY_ECONOMY:
                    continue
                base = g.get("regional")
                if base is not None and str(base) in hidden:
                    continue
                keys: list[str] = list(g["stages"])
                for var_key, var_stages in g.get("variants", ()):
                    if available(var_key):
                        keys = list(var_stages)
                        break
                stages = [s for s in (stage(k) for k in keys) if s is not None]
                # A later tier is unavailable when the tier it builds on is.
                for prev, cur in itertools.pairwise(stages):
                    cur["base_key"] = prev["key"]
                    if prev["status"] != "available" and cur["status"] == "available":
                        cur["status"] = "struck"
                if not stages or all(s["status"] == "hidden" for s in stages):
                    continue
                out_groups.append({"key": gkey, "stages": stages})
            if row_key == "misc" and era != "antiquity":
                for gkey, ids in (
                    ("castleAgeUniqueTech", uts.get("castle", [])),
                    ("imperialAgeUniqueTech", uts.get("imperial", [])),
                ):
                    stages = [s for s in (stage(f"tech:{t}") for t in ids) if s is not None]
                    if stages:
                        out_groups.append({"key": gkey, "stages": stages})
            if out_groups:
                rows.append({"key": row_key, "name": row_name, "groups": out_groups})
        return {"rows": rows}

    @cached_property
    def particle_definitions(self) -> list[str]:
        """Names of the game's particle effects (``resources/_common/particles``).

        The game only streams particles whose definition is whitelisted in the
        Frames request; an empty whitelist streams inert slots (measured).
        """
        if self.game_dir is None:
            return []
        d = self.game_dir / "resources" / "_common" / "particles"
        return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []

    def _particles_dirs(self) -> list[Path]:
        """Particle folders in lookup order: enabled sprite mods first, then the game."""
        if self.game_dir is None:
            return []
        base = self.game_dir / "resources" / "_common" / "particles"
        return [*self.mod_roots("particles"), *([base] if base.is_dir() else [])]

    def particle_definitions_table(self) -> dict[str, dict[str, Any]]:
        """Every particle effect: its atlas, frame range and fade/scale settings
        (a sprite mod's definition of the same name wins)."""
        out: dict[str, dict[str, Any]] = {}
        for d in self._particles_dirs():
            for p in sorted(d.glob("*.json")):
                if p.stem in out:
                    continue
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(raw, dict):
                    continue
                atlas = str(raw.get("AtlasFile", "")).replace("\\", "/")
                out[p.stem] = {
                    "atlas": atlas,
                    "first": int(raw.get("ImageFirst", 0) or 0),
                    "count": int(raw.get("ImageCount", 1) or 1),
                    "scale": float(raw.get("Scale", 1.0) or 1.0),
                    "alpha_start": _float_or(raw.get("AlphaStart"), 1.0),
                    "alpha_end": _float_or(raw.get("AlphaEnd"), 1.0),
                    "duration": float(raw.get("Duration", 1.0) or 1.0),
                    "type": raw.get("Type", ""),
                    # A looping emitter's life (it restarts after a random time in
                    # [Duration1, Duration2]) and its fade in / out at either end.
                    "life": [
                        _float_or(raw.get("Duration1"), 0.0),
                        _float_or(raw.get("Duration2"), 0.0),
                    ],
                    "fade_in": _float_or(raw.get("StartDuration"), 0.0)
                    if raw.get("StartMode") == "Fade"
                    else 0.0,
                    "fade_out": _float_or(raw.get("StopDuration"), 0.0)
                    if raw.get("StopMode") == "Fade"
                    else 0.0,
                    # A building's fire (the game streams these when particles are on).
                    "fire": bool(raw.get("IsFire")),
                }
        return out

    def particle_atlas(self, rel: str) -> tuple[bytes, str, dict[str, Any]] | None:
        """(image bytes, mime, frames) for a particle atlas path from a definition.

        Enabled sprite mods are searched before the game. Big atlases are
        decoded at a lower mip level; ``frames`` carries the rectangles
        rescaled to that image.
        """
        if ".." in rel or not re.fullmatch(r"[\w/.-]+", rel):
            return None
        base = (
            self.game_dir / "resources" / "_common" / "particles"
            if self.game_dir is not None
            else None
        )
        for d in self._particles_dirs():
            if (d / rel).is_file():
                return self._particle_atlas_from(d, rel, "" if d == base else _cache_key(d))
        return None

    def _particle_atlas_from(
        self, d: Path, rel: str, key_prefix: str
    ) -> tuple[bytes, str, dict[str, Any]] | None:
        src = d / rel
        frames_path = src.with_suffix(".json")
        try:
            frames_doc = (
                json.loads(frames_path.read_text(encoding="utf-8")) if frames_path.is_file() else {}
            )
        except ValueError:
            frames_doc = {}
        if src.suffix.lower() == ".png":
            meta_png = {"scale": 1.0, "frames": frames_doc.get("frames", [])}
            return src.read_bytes(), "image/png", meta_png
        key = (f"{key_prefix}-" if key_prefix else "") + rel.replace("/", "_")
        cached = self.cache_dir / "particles" / f"{key}.v2.png"
        meta_path = self.cache_dir / "particles" / f"{key}.v2.json"
        if cached.is_file() and meta_path.is_file():
            return (
                cached.read_bytes(),
                "image/png",
                json.loads(meta_path.read_text(encoding="utf-8")),
            )
        got: tuple[bytes, str, dict[str, Any]] | None = self._converting.run(
            cached, lambda: self._convert_particle_atlas(src, frames_doc, cached, meta_path)
        )
        return got

    def _convert_particle_atlas(
        self, src: Path, frames_doc: dict[str, Any], cached: Path, meta_path: Path
    ) -> tuple[bytes, str, dict[str, Any]] | None:
        if cached.is_file() and meta_path.is_file():  # finished just before this call
            return (
                cached.read_bytes(),
                "image/png",
                json.loads(meta_path.read_text(encoding="utf-8")),
            )
        data = src.read_bytes()
        (width,) = struct.unpack_from("<I", data, 16)
        mip = 2 if width >= 4096 else 1 if width >= 2048 else 0
        try:
            png = dds_to_png(data, mip=mip)
        except (ValueError, struct.error):
            return None
        # The scale of the image actually returned: a DDS with fewer mip
        # levels than asked for (or an uncompressed one) comes back larger.
        (png_width,) = struct.unpack_from(">I", png, 16)
        scale = png_width / width if width else 1.0
        meta = {"scale": scale, "frames": frames_doc.get("frames", [])}
        if atomic_write(cached, png):  # the image first: cached once the meta exists
            atomic_write(meta_path, json.dumps(meta).encode())
        return png, "image/png", meta

    def civ_emblem(self, civ_id: int | None) -> Path | None:
        if self.game_dir is None or civ_id is None or not 0 <= civ_id < len(self.civs):
            return None
        rel = str(self.civs[civ_id].get("emblem_image_path") or "")
        if not rel:
            return None
        # The in-game medallion (menu/civs) reads on a dark HUD; the wpfg emblem
        # is a pale line drawing meant for light menus. Same file name in both.
        for root in self.roots():
            medal = root / "widgetui" / "textures" / "menu" / "civs" / Path(rel).name
            if medal.is_file():
                return medal
        for root in self.roots():
            p = root / "resources" / "_common" / "wpfg" / rel.lstrip("/")
            if p.is_file():
                return p
        return None

    # -- colours --------------------------------------------------------------

    @cached_property
    def terrain_types(self) -> list[TerrainType]:
        """The game's terrain table, for recordings whose stream does not carry one."""
        if self.game_dir is None:
            return []
        path = self.game_dir / "resources" / "_common" / "dat" / "empires2_x2_p1.dat"
        try:
            return parse_terrain_types(zlib.decompress(path.read_bytes(), -15))
        except (OSError, zlib.error, ValueError, struct.error):
            return []

    @cached_property
    def interface_palette(self) -> list[tuple[int, int, int]]:
        """The 256-entry palette that ``TerrainType.mapFlatColor`` indexes."""
        if self.game_dir is not None:
            path = self.game_dir / "resources" / "_common" / "palettes" / "original.pal"
            if path.is_file():
                return _read_jasc(path)
        return [(i, i, i) for i in range(256)]

    @cached_property
    def player_colors(self) -> list[tuple[int, int, int]]:
        fallback = [
            (0, 0, 255),
            (255, 0, 0),
            (0, 255, 0),
            (255, 255, 0),
            (0, 255, 255),
            (255, 0, 255),
            (67, 67, 67),
            (255, 130, 1),
        ]
        if self.game_dir is None:
            return fallback
        pal_dir = self.game_dir / "resources" / "_common" / "palettes"
        out = []
        for i, name in enumerate(PLAYER_COLOR_FILES):
            path = pal_dir / f"playercolor_{name}.pal"
            try:
                out.append(_read_jasc(path)[0])
            except (OSError, ValueError, IndexError):
                out.append(fallback[i])
        return out

    # -- icons ----------------------------------------------------------------

    _ICON_DIRS: ClassVar[dict[str, str]] = {
        "unit": "units",
        "building": "buildings",
        "tech": "tech",
    }

    def icon_png(self, kind: str, icon_id: int) -> bytes | None:
        """PNG bytes for a unit/building/tech icon id, or None if absent."""
        if self.game_dir is None or icon_id < 0 or kind not in self._ICON_DIRS:
            return None
        prefix = f"{self.mode}-" if self.mode else ""
        cached = self.cache_dir / "icons" / f"{prefix}{kind}-{icon_id}.png"
        if cached.is_file():
            return cached.read_bytes()
        src = self._icon_source(self._ICON_DIRS[kind], icon_id)
        if src is None:
            return None
        got: bytes | None = self._converting.run(cached, lambda: _convert_dds(src, cached))
        return got

    @cached_property
    def _icon_index(self) -> dict[str, dict[int, Path]]:
        out: dict[str, dict[int, Path]] = {}
        if self.game_dir is None:
            return out
        # The active mode's icons win (Return of Rome reuses ids for other
        # pictures); other modes then fill ids the base game lacks.
        roots = [r / "widgetui" / "textures" / "ingame" for r in self.roots()]
        roots += sorted(self.game_dir.glob("modes/*/widgetui/textures/ingame"))
        for sub in ("units", "buildings", "tech"):
            idx: dict[int, Path] = {}
            for root in roots:
                d = root / sub
                if d.is_dir():
                    for p in sorted(d.iterdir()):
                        m = re.match(r"^(\d+)_", p.name)
                        if m and p.suffix.lower() == ".dds":
                            idx.setdefault(int(m.group(1)), p)
            out[sub] = idx
        return out

    def _icon_source(self, sub: str, icon_id: int) -> Path | None:
        return self._icon_index.get(sub, {}).get(icon_id)

    def terrain_png(self, name: str) -> bytes | None:
        """A terrain texture (mip 2 of the 2048px DDS: ~51px per tile), as PNG."""
        if self.game_dir is None or not re.fullmatch(r"[\w-]+", name):
            return None
        # A terrain mod's texture wins (cached under its own folder's key).
        for root in self.mod_roots("terrain"):
            for cand in (root / "2x" / f"{name}.dds", root / f"{name}.dds"):
                if cand.is_file():
                    return self._terrain_from(cand, name, _cache_key(root))
        rel = Path("resources") / "_common" / "terrain" / "textures" / "2x" / f"{name}.dds"
        modes = sorted(self.game_dir.glob("modes/*"))
        candidates = [self.game_dir / rel, *(m / rel for m in modes)]
        src = next((c for c in candidates if c.is_file()), None)
        if src is None:
            return None
        return self._terrain_from(src, name, "")

    @cached_property
    def color_grades(self) -> list[dict[str, Any]]:
        """The game's colour-correction presets (``terrain/colorcorrection_json``), in
        the order map scripts number them (``CC_DEFAULT`` 0 ... ``CC_DARKNESS`` 18)."""
        if self.game_dir is None:
            return []
        p = self.game_dir / "resources" / "_common" / "terrain" / "colorcorrection_json"
        try:
            raw = json.loads((p / "colorcorrection.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        keep = ("name", "saturation", "contrast", "brightness", "tint_factor", "tint_color",
                "terrain_tint_color", "distance_fog_color",
                "distance_fog_visible_intensity")  # fmt: skip
        return [
            {k: c[k] for k in keep if k in c}
            for c in raw.get("correction_types", [])
            if isinstance(c, dict)
        ]

    def color_grade_names(self, lang: str) -> dict[str, str]:
        """Each colour-grade preset's name in the game's own words for ``lang``."""
        if self.game_dir is None:
            return {}
        p = self.game_dir / "resources" / "_common" / "terrain" / "colorcorrection_json"
        try:
            raw = json.loads((p / "colorcorrection.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        strings = self.strings_for(lang)
        out: dict[str, str] = {}
        for c in raw.get("correction_types", []):
            sid = str(c.get("localisedname", ""))
            if isinstance(c, dict) and c.get("name") and sid.isdigit() and int(sid) in strings:
                out[str(c["name"])] = strings[int(sid)]
        return out

    def map_color_grade(self, map_file: str) -> int | None:
        """The colour-correction preset a map script sets, if it can be known: the
        ``color_correction`` command outside any ``if``/``start_random`` block, or
        0 (Default) for a script without one. None when the script chooses it by
        condition or at random (biome flags, ``percent_chance``) or is not found."""
        text = self._map_script(map_file)
        if text is None:
            return None
        consts = self._cc_constants()
        depth = 0
        found: int | None = None
        conditional = False
        for line in re.sub(r"/\*.*?\*/", " ", text, flags=re.S).splitlines():
            words = line.split()
            if not words:
                continue
            w0 = words[0].lower()
            if w0 in ("if", "start_random"):
                depth += 1
            elif w0 in ("endif", "end_random"):
                depth = max(0, depth - 1)
            lower = [w.lower() for w in words]
            if "color_correction" in lower:
                i = lower.index("color_correction")
                arg = words[i + 1] if i + 1 < len(words) else ""
                val = int(arg) if arg.isdigit() else consts.get(arg.upper())
                # Inside a block, after a percent_chance, or a name set elsewhere
                # (COLOUR_MOOD from the biome): not knowable from the script.
                if depth or i > 0 or val is None:
                    conditional = True
                elif found is None:
                    found = val
        if found is not None:
            return found
        return None if conditional else 0

    def _cc_constants(self) -> dict[str, int]:
        out: dict[str, int] = {}
        if self.game_dir is None:
            return out
        base = self.game_dir / "resources" / "_common" / "drs" / "gamedata_x2" / "random_map.def"
        try:
            for m in re.finditer(
                r"#const\s+(CC_\w+)\s+(\d+)", base.read_text(encoding="utf-8", errors="replace")
            ):
                out[m.group(1).upper()] = int(m.group(2))
        except OSError:
            pass
        return out

    def _map_script(self, map_file: str) -> str | None:
        name = Path(map_file).name
        if not name or not name.lower().endswith(".rms") or self.game_dir is None:
            return None
        common = self.game_dir / "resources" / "_common"
        dirs = [common / "drs" / "gamedata_x2", common / "random-map-scripts"]
        dirs += [
            m / "resources" / "_common" / "random-map-scripts" for m in self.mods.mod_folders()
        ]
        for d in dirs:
            try:
                for f in d.iterdir():
                    if f.name.lower() == name.lower():
                        return f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        return None

    def terrain_mask_png(self, name: str) -> bytes | None:
        """A terrain overlay mask (``terrain/masks/<name>.png``, greyscale noise): the
        game draws a tile's layer terrain through it over the base terrain."""
        if self.game_dir is None or not re.fullmatch(r"[\w-]+", name):
            return None
        for root in self.mod_roots("terrain"):
            cand = root.parent / "masks" / f"{name}.png"
            if cand.is_file():
                return cand.read_bytes()
        src = self.game_dir / "resources" / "_common" / "terrain" / "masks" / f"{name}.png"
        return src.read_bytes() if src.is_file() else None

    def _terrain_from(self, src: Path, name: str, key: str) -> bytes | None:
        cached = self.cache_dir / "terrain" / (f"{key}-{name}.png" if key else f"{name}.png")
        if cached.is_file():
            return cached.read_bytes()
        got: bytes | None = self._converting.run(cached, lambda: _convert_dds(src, cached, mip=2))
        return got

    def emblem_png(self, civ_id: int) -> bytes | None:
        p = self.civ_emblem(civ_id)
        return p.read_bytes() if p is not None else None


def _convert_dds(src: Path, cached: Path, mip: int = 0) -> bytes | None:
    """A DDS converted to PNG and stored at ``cached`` (once per file at a time,
    through :attr:`GameData._converting`)."""
    if cached.is_file():  # finished just before this call
        return cached.read_bytes()
    try:
        png = dds_to_png(src.read_bytes(), mip=mip)
    except (ValueError, struct.error):
        return None
    atomic_write(cached, png)
    return png


def _cache_key(p: Path) -> str:
    return hashlib.sha1(str(p).encode()).hexdigest()[:12]


# -- DDS -> PNG ----------------------------------------------------------------


def _png(width: int, height: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def _rgb565(c: int) -> tuple[int, int, int]:
    r = (c >> 11) & 31
    g = (c >> 5) & 63
    b = c & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def _color_block(
    blk: bytes,
    out: bytearray,
    x0: int,
    y0: int,
    w: int,
    h: int,
    alpha: list[int] | None,
    dxt1: bool,
) -> None:
    c0, c1, bits = struct.unpack("<HHI", blk)
    p0, p1 = _rgb565(c0), _rgb565(c1)
    if c0 > c1 or not dxt1:
        p2 = tuple((2 * a + b) // 3 for a, b in zip(p0, p1, strict=True))
        p3 = tuple((a + 2 * b) // 3 for a, b in zip(p0, p1, strict=True))
        pal = [(*p0, 255), (*p1, 255), (*p2, 255), (*p3, 255)]
    else:
        p2 = tuple((a + b) // 2 for a, b in zip(p0, p1, strict=True))
        pal = [(*p0, 255), (*p1, 255), (*p2, 255), (0, 0, 0, 0)]
    for i in range(16):
        x, y = x0 + (i & 3), y0 + (i >> 2)
        if x >= w or y >= h:
            continue
        r, g, b, a = pal[(bits >> (2 * i)) & 3]
        if alpha is not None:
            a = alpha[i]
        o = (y * w + x) * 4
        out[o : o + 4] = bytes((r, g, b, a))


def _dxt5_alpha(blk: bytes) -> list[int]:
    a0, a1 = blk[0], blk[1]
    bits = int.from_bytes(blk[2:8], "little")
    if a0 > a1:
        pal = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    else:
        pal = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
    return [pal[(bits >> (3 * i)) & 7] for i in range(16)]


# DX10-header DXGI formats we can decode, mapped onto the legacy FourCC paths.
_DXGI_FOURCC = {
    71: b"DXT1",
    72: b"DXT1",
    74: b"DXT3",
    75: b"DXT3",
    77: b"DXT5",
    78: b"DXT5",
    98: b"BC7",
    99: b"BC7",
}


def dds_to_png(data: bytes, mip: int = 0) -> bytes:
    """Decode one mip level of an uncompressed, DXT1/3/5 or BC7 (DX10) DDS to PNG."""
    if data[:4] != b"DDS ":
        raise ValueError("not a DDS file")
    height, width = struct.unpack_from("<II", data, 12)
    (mips,) = struct.unpack_from("<I", data, 28)
    pf_flags, fourcc, bitcount = struct.unpack_from("<I4sI", data, 80)
    rmask, gmask, bmask, amask = struct.unpack_from("<IIII", data, 92)
    body = data[128:]
    if fourcc == b"DX10":
        if len(data) < 148:
            raise ValueError("truncated DX10 DDS header")
        (dxgi,) = struct.unpack_from("<I", data, 128)
        body = data[148:]
        mapped = _DXGI_FOURCC.get(dxgi)
        if mapped is None:
            raise ValueError(f"unsupported DDS pixel format {fourcc!r}/{dxgi}")
        fourcc = mapped
    if mip and fourcc in (b"DXT1", b"DXT3", b"DXT5", b"BC7"):
        mip = min(mip, max(0, mips - 1))
        bsize = 8 if fourcc == b"DXT1" else 16
        for _ in range(mip):
            body = body[max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * bsize :]
            width, height = max(1, width // 2), max(1, height // 2)
    if fourcc == b"BC7":
        return _png(width, height, decode_bc7(body, width, height))
    out = bytearray(width * height * 4)
    if fourcc in (b"DXT1", b"DXT3", b"DXT5"):
        dxt1 = fourcc == b"DXT1"
        bsize = 8 if dxt1 else 16
        bw = (width + 3) // 4
        bh = (height + 3) // 4
        for by in range(bh):
            for bx in range(bw):
                o = (by * bw + bx) * bsize
                if dxt1:
                    _color_block(body[o : o + 8], out, bx * 4, by * 4, width, height, None, True)
                elif fourcc == b"DXT3":
                    raw = int.from_bytes(body[o : o + 8], "little")
                    alpha = [((raw >> (4 * i)) & 15) * 17 for i in range(16)]
                    _color_block(
                        body[o + 8 : o + 16], out, bx * 4, by * 4, width, height, alpha, False
                    )
                    continue
                else:
                    alpha = _dxt5_alpha(body[o : o + 8])
                    _color_block(
                        body[o + 8 : o + 16], out, bx * 4, by * 4, width, height, alpha, False
                    )
        return _png(width, height, bytes(out))
    if pf_flags & 0x40 and bitcount == 32:  # DDPF_RGB, 32-bit with masks

        def shift(mask: int) -> int:
            return (mask & -mask).bit_length() - 1 if mask else 0

        sh = [shift(m) for m in (rmask, gmask, bmask, amask)]
        px = struct.unpack_from(f"<{width * height}I", body)
        for i, v in enumerate(px):
            a = (v & amask) >> sh[3] if amask else 255
            out[i * 4 : i * 4 + 4] = bytes(
                ((v & rmask) >> sh[0], (v & gmask) >> sh[1], (v & bmask) >> sh[2], a)
            )
        return _png(width, height, bytes(out))
    raise ValueError(f"unsupported DDS pixel format {fourcc!r}/{bitcount}")
