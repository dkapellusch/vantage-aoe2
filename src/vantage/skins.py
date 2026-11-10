"""Vantage skins: ``skin.json`` packages in a folder or a ``.zip``.

A skin is a manifest ``skin.json`` ``{name, options, stylesheets[], assets{}}``
next to the files it names (the older single ``"css"`` key is still read).
Skins live in ``<data dir>/skins`` (a sub-folder or a ``.zip`` each) or
anywhere on disk once registered with :meth:`SkinStore.add` (the "..." button:
*Folder* / *ZIP file*). Several enabled skins merge
(:meth:`SkinStore.merged`): boolean options are OR-ed, list options are
concatenated and later stylesheets and assets override earlier ones. Files
are served from ``/skins/<name>/<file>`` whichever way the skin is stored, and
:meth:`SkinStore.version` changes whenever any skin file does, so the browser
can live-reload.
"""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

#: Skin names are URL path segments.
NAME_RE = re.compile(r"[\w -]{1,40}")
MANIFEST = "skin.json"
#: A skin file larger than this is not served.
MAX_FILE_BYTES = 32 * 1024 * 1024
#: Asset keys the app skins; others are passed through with a warning.
KNOWN_ASSETS = frozenset(
    {
        "logo",
        "colWorkersFood",
        "colWorkersWood",
        "colWorkersGold",
        "colWorkersStone",
        "colEcoEapgm",
        "colMilitaryEapgm",
        "colTotalEapgm",
        "colMovingEco",
        "colBuildingRepairEco",
        "colGatheringEco",
        "colWorkerEfficiency",
        "colEconomyCount",
        "colApm",
    }
)
#: Asset keys a skin may not replace (branding logos and the country-flag
#: set); they raise an "Unskinnable assets" warning and are not served.
UNSKINNABLE_ASSETS = frozenset(
    {
        "assets/ca/skin-logo.svg",
        "assets/ca/ca-logo.png",
        "assets/ca/ca-logo.svg",
        "assets/ca/ca-logo-diamond.svg",
        "assets/ca/ca-logo-diamond.png",
        "assets/ca/ca-logo-heart.svg",
        "assets/ca/ca-logo-heart.png",
    }
)
_FLAG_ASSET = re.compile(r"flag-[a-z0-9-]+-1x1")
#: Manifest keys that are not passed through as extra row fields.
_MANIFEST_KEYS = frozenset({"css", "assets", "options", "stylesheets"})


def safe_rel(rel: Any) -> str | None:
    """A relative skin path without ``..`` or a leading slash, else None."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")):
        return None
    parts = rel.replace("\\", "/").split("/")
    if any(p in ("", "..") or ":" in p for p in parts if p != "."):
        return None
    return "/".join(p for p in parts if p != ".") or None


@dataclass
class Skin:
    """One skin on disk: its name, where it is and how to read its files."""

    name: str
    path: Path
    kind: str  # folder | zip
    #: Added by path (removable) rather than living in the skins folder.
    added: bool = False
    prefix: str = ""  # zip: folder inside the archive holding skin.json
    _zip_names: set[str] = field(default_factory=set)

    def read(self, rel: str) -> bytes | None:
        """The bytes of a file of the skin, or None when absent / unsafe."""
        rel = safe_rel(rel) or ""
        if not rel:
            return None
        try:
            if self.kind == "folder":
                f = (self.path / rel).resolve()
                f.relative_to(self.path.resolve())
                if not f.is_file() or f.stat().st_size > MAX_FILE_BYTES:
                    return None
                return f.read_bytes()
            with zipfile.ZipFile(self.path) as z:
                info = z.getinfo(self.prefix + rel)
                if info.is_dir() or info.file_size > MAX_FILE_BYTES:
                    return None
                return z.read(info)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            return None

    def exists(self, rel: str) -> bool:
        return self.read(rel) is not None

    def signature(self) -> list[tuple[str, int, int]]:
        """(path, mtime_ns, size) of everything the skin consists of."""
        out: list[tuple[str, int, int]] = []
        try:
            if self.kind == "zip":
                st = self.path.stat()
                return [(str(self.path), st.st_mtime_ns, st.st_size)]
            for i, f in enumerate(sorted(self.path.rglob("*"))):
                if i >= 2000:
                    break
                if f.is_file():
                    st = f.stat()
                    out.append((str(f), st.st_mtime_ns, st.st_size))
        except OSError:
            pass
        return out


class SkinStore:
    """The skins of one Vantage data directory plus the ones added by path."""

    def __init__(self, skins_dir: Path, registry: Path | None = None) -> None:
        self.skins_dir = skins_dir
        #: JSON file listing the paths of skins added with :meth:`add`.
        self.registry = registry
        self._lock = threading.Lock()
        self._sig: tuple[Any, ...] = ()
        self._checked = 0.0
        self._version = 0

    # -- discovery ------------------------------------------------------------

    def _registered(self) -> list[Path]:
        if self.registry is None:
            return []
        try:
            raw = json.loads(self.registry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        paths = raw.get("paths") if isinstance(raw, dict) else None
        return [Path(p) for p in paths if isinstance(p, str)] if isinstance(paths, list) else []

    def _save_registry(self, paths: list[Path]) -> None:
        if self.registry is None:
            return
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(json.dumps({"paths": [str(p) for p in paths]}), encoding="utf-8")

    def skins(self) -> list[Skin]:
        """Every skin: the skins folder (sorted), then the added ones."""
        found: list[Skin] = []
        taken: set[str] = set()

        def take(base: str, path: Path, kind: str, added: bool) -> None:
            stem = re.sub(r"[^\w -]", "_", base).strip()[:40] or "skin"
            name, n = stem, 2
            while name in taken:
                suffix = f" {n}"
                name, n = stem[: 40 - len(suffix)] + suffix, n + 1
            taken.add(name)
            found.append(
                Skin(
                    name,
                    path,
                    kind,
                    added,
                    prefix=(_zip_prefix(path) or "") if kind == "zip" else "",
                )
            )

        if self.skins_dir.is_dir():
            for d in sorted(self.skins_dir.iterdir()):
                if d.is_dir() and NAME_RE.fullmatch(d.name) and (d / MANIFEST).is_file():
                    take(d.name, d, "folder", False)
                elif d.is_file() and d.suffix.lower() == ".zip" and NAME_RE.fullmatch(d.stem):
                    take(d.stem, d, "zip", False)
        for p in self._registered():
            if p.is_dir():
                take(p.name, p, "folder", True)
            elif p.is_file():
                take(p.stem, p, "zip", True)
        return found

    def get(self, name: str) -> Skin | None:
        return next((s for s in self.skins() if s.name == name), None)

    # -- rows -------------------------------------------------------------------

    def rows(self) -> list[dict[str, Any]]:
        return [self.row(s) for s in self.skins()]

    def row(self, skin: Skin) -> dict[str, Any]:
        """The skin as ``/api/skins`` reports it (validated manifest)."""
        base = f"/skins/{quote(skin.name)}/"
        row: dict[str, Any] = {
            "name": skin.name,
            "title": skin.name,
            "path": str(skin.path),
            "kind": skin.kind,
            "added": skin.added,
            "status": "ready",
            "options": {},
            "stylesheets": [],
            "assets": {},
            "css_url": None,
            "warnings": [],
        }
        raw = skin.read(MANIFEST)
        if raw is None:
            return {**row, "status": "error", "error": f"{MANIFEST} not found"}
        try:
            meta = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as exc:
            return {**row, "status": "error", "error": f"{MANIFEST} is not valid JSON: {exc}"}
        if not isinstance(meta, dict):
            return {**row, "status": "error", "error": f"{MANIFEST} must be an object"}
        warnings: list[str] = row["warnings"]
        row["title"] = str(meta.get("title") or meta.get("name") or skin.name)
        options = meta.get("options")
        if options is not None and not isinstance(options, dict):
            warnings.append("options must be an object")
        row["options"] = options if isinstance(options, dict) else {}
        explicit = meta.get("stylesheets")
        sheets: list[Any]
        if isinstance(explicit, list):
            sheets = explicit
        elif meta.get("css"):
            sheets = [meta["css"]]
        else:
            sheets = ["skin.css"] if skin.exists("skin.css") else []
        for rel in sheets:
            ok = safe_rel(rel)
            if ok is None:
                warnings.append(f"stylesheet path is not a relative path: {rel!r}")
            elif not skin.exists(ok):
                warnings.append(f"stylesheet not found: {ok}")
            else:
                row["stylesheets"].append(base + quote(ok, safe="/"))
        row["css_url"] = row["stylesheets"][0] if row["stylesheets"] else None
        assets = meta.get("assets")
        if assets is not None and not isinstance(assets, dict):
            warnings.append("assets must be an object")
        unknown: list[str] = []
        unskinnable: list[str] = []
        for key, rel in (assets if isinstance(assets, dict) else {}).items():
            if str(key) in UNSKINNABLE_ASSETS or _FLAG_ASSET.fullmatch(str(key)):
                unskinnable.append(str(key))
                continue
            ok = safe_rel(rel)
            if ok is None:
                warnings.append(f"asset {key}: not a relative path: {rel!r}")
            elif not skin.exists(ok):
                warnings.append(f"asset {key}: file not found: {ok}")
            else:
                row["assets"][str(key)] = base + quote(ok, safe="/")
                if str(key) not in KNOWN_ASSETS:
                    unknown.append(str(key))
        if unknown:
            warnings.append("Unrecognized Asset Keys: " + ", ".join(sorted(unknown)))
        if unskinnable:
            warnings.append("Unskinnable assets: " + ", ".join(sorted(unskinnable)))
        for k, v in meta.items():
            if k not in _MANIFEST_KEYS and k not in ("name", "title"):
                row.setdefault(k, v)
        return row

    def merged(self, names: list[str]) -> dict[str, Any]:
        """The enabled skins as one: options OR-ed / concatenated / overridden,
        stylesheets in enable order, later assets overriding earlier ones."""
        by_name = {r["name"]: r for r in self.rows()}
        options: dict[str, Any] = {}
        sheets: list[str] = []
        assets: dict[str, str] = {}
        used: list[str] = []
        for n in names:
            r = by_name.get(n)
            if r is None or r["status"] == "error":
                continue
            used.append(n)
            for k, v in r["options"].items():
                if isinstance(v, bool):
                    options[k] = bool(options.get(k)) or v
                elif isinstance(v, list):
                    options[k] = [*(options.get(k) or []), *v]
                elif v is None:
                    options.setdefault(k, None)
                else:
                    options[k] = v
            sheets.extend(u for u in r["stylesheets"] if u not in sheets)
            assets.update(r["assets"])
        return {"options": options, "stylesheets": sheets, "assets": assets, "enabled": used}

    # -- mutation ---------------------------------------------------------------

    def add(self, path: str, kind: str | None = None) -> dict[str, Any]:
        """Register a skin folder or ``.zip`` anywhere on disk."""
        p = Path(path).expanduser()
        if not p.exists():
            return {"ok": False, "error": f"no such file or folder: {path}"}
        actual = "folder" if p.is_dir() else "zip"
        if kind in ("folder", "zip") and kind != actual:
            return {"ok": False, "error": f"{path} is not a {kind}"}
        if actual == "zip" and not zipfile.is_zipfile(p):
            return {"ok": False, "error": f"{path} is not a zip archive"}
        if actual == "folder" and not (p / MANIFEST).is_file():
            return {"ok": False, "error": f"{MANIFEST} not found in {path}"}
        if actual == "zip" and _zip_prefix(p) is None:
            return {"ok": False, "error": f"{MANIFEST} not found in {path}"}
        p = p.resolve()
        with self._lock:
            known = self._registered()
            if p not in known:
                self._save_registry([*known, p])
        for s in self.skins():
            if s.path.resolve() == p:
                return {"ok": True, "name": s.name, "kind": s.kind}
        return {"ok": False, "error": "the skin could not be registered"}

    def remove(self, name: str) -> dict[str, Any]:
        """Forget a skin added by path (skins in the skins folder stay)."""
        skin = self.get(name)
        if skin is None or not skin.added:
            return {"ok": False, "error": "not an added skin"}
        with self._lock:
            self._save_registry(
                [p for p in self._registered() if p.resolve() != skin.path.resolve()]
            )
        return {"ok": True}

    # -- files and hot reload ---------------------------------------------------

    def file(self, name: str, rel: str) -> tuple[bytes, str] | None:
        """``(bytes, content type)`` of ``/skins/<name>/<rel>``."""
        skin = self.get(name)
        if skin is None:
            return None
        body = skin.read(rel)
        if body is None:
            return None
        return body, mimetypes.guess_type(rel)[0] or "application/octet-stream"

    def version(self, max_age: float = 0.5) -> int:
        """A number that changes whenever any skin (or the list of skins) does."""
        with self._lock:
            now = time.monotonic()
            if now - self._checked < max_age:
                return self._version
            self._checked = now
        sig = tuple(
            (s.name, tuple(s.signature())) for s in self.skins()
        )  # outside the lock: it walks the disk
        with self._lock:
            if sig != self._sig:
                if self._sig:
                    self._version += 1
                self._sig = sig
            return self._version


def _zip_prefix(path: Path) -> str | None:
    """Where ``skin.json`` sits inside a zip: ``""`` (root) or ``"<dir>/"``
    (one wrapping folder); None when the archive has no manifest."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return None
    if MANIFEST in names:
        return ""
    for n in names:
        parts = n.split("/")
        if len(parts) == 2 and parts[1] == MANIFEST and parts[0] not in ("", ".."):
            return parts[0] + "/"
    return None
