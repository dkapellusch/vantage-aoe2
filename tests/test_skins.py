"""vantage.skins: skin.json packages in folders and zips, merging, reload."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from vantage.skins import SkinStore, safe_rel


def _folder(root: Path, name: str, manifest: dict[str, object], **files: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "skin.json").write_text(json.dumps(manifest))
    for rel, body in files.items():
        (d / rel).write_text(body)
    return d


def test_safe_rel_rejects_escapes() -> None:
    assert safe_rel("a/b.css") == "a/b.css" and safe_rel("./a.css") == "a.css"
    for bad in ("../x", "a/../../x", "/etc/passwd", "", "C:/x", "a//b", None, 3):
        assert safe_rel(bad) is None


def test_folder_skin_rows_validate_manifest_and_paths(tmp_path: Path) -> None:
    root = tmp_path / "skins"
    _folder(
        root,
        "Gold",
        {
            "options": {"showSkinLogo": True},
            "stylesheets": ["a.css", "missing.css", "../evil.css"],
            "assets": {"logo": "logo.png", "colApm": "apm.png", "weird": "w.png", "bad": "../x"},
            "extra": 1,
        },
        **{"a.css": "a{}", "logo.png": "P", "apm.png": "P", "w.png": "P"},
    )
    (root / "empty").mkdir()  # no manifest: not a skin
    (root / "broken").mkdir()
    (root / "broken" / "skin.json").write_text("{nope")
    store = SkinStore(root)
    rows = {r["name"]: r for r in store.rows()}
    assert set(rows) == {"Gold", "broken"}
    gold = rows["Gold"]
    assert gold["status"] == "ready" and gold["kind"] == "folder" and gold["extra"] == 1
    assert gold["stylesheets"] == ["/skins/Gold/a.css"] and gold["css_url"] == "/skins/Gold/a.css"
    assert gold["assets"] == {
        "logo": "/skins/Gold/logo.png",
        "colApm": "/skins/Gold/apm.png",
        "weird": "/skins/Gold/w.png",
    }
    text = " | ".join(gold["warnings"])
    assert "missing.css" in text and "not a relative path" in text
    assert "Unrecognized Asset Keys: weird" in text
    assert rows["broken"]["status"] == "error" and "JSON" in rows["broken"]["error"]


def test_unskinnable_assets_warn_and_are_not_served(tmp_path: Path) -> None:
    root = tmp_path / "skins"
    _folder(
        root,
        "Brand",
        {"assets": {"assets/ca/ca-logo.png": "l.png", "flag-de-1x1": "l.png", "logo": "l.png"}},
        **{"l.png": "P"},
    )
    row = SkinStore(root).rows()[0]
    assert row["assets"] == {"logo": "/skins/Brand/l.png"}
    text = " | ".join(row["warnings"])
    assert "Unskinnable assets: assets/ca/ca-logo.png, flag-de-1x1" in text
    assert "Unrecognized" not in text


def test_legacy_css_key_and_default_skin_css(tmp_path: Path) -> None:
    root = tmp_path / "skins"
    _folder(root, "old", {"css": "x.css"}, **{"x.css": "x{}"})
    _folder(root, "plain", {}, **{"skin.css": "s{}"})
    rows = {r["name"]: r for r in SkinStore(root).rows()}
    assert rows["old"]["stylesheets"] == ["/skins/old/x.css"]
    assert rows["plain"]["stylesheets"] == ["/skins/plain/skin.css"]


def test_zip_skin_with_wrapping_folder_and_served_files(tmp_path: Path) -> None:
    root = tmp_path / "skins"
    root.mkdir()
    with zipfile.ZipFile(root / "Pack.zip", "w") as z:
        z.writestr(
            "Pack/skin.json", json.dumps({"stylesheets": ["s.css"], "assets": {"logo": "i/l.png"}})
        )
        z.writestr("Pack/s.css", "z{}")
        z.writestr("Pack/i/l.png", b"PNG")
    store = SkinStore(root)
    (row,) = store.rows()
    assert row["name"] == "Pack" and row["kind"] == "zip" and row["status"] == "ready"
    assert row["assets"] == {"logo": "/skins/Pack/i/l.png"}
    assert store.file("Pack", "s.css") == (b"z{}", "text/css")
    assert store.file("Pack", "i/l.png") is not None
    assert store.file("Pack", "../s.css") is None and store.file("Pack", "nope") is None
    assert store.file("Nope", "s.css") is None


def test_several_skins_merge(tmp_path: Path) -> None:
    root = tmp_path / "skins"
    _folder(
        root,
        "a",
        {
            "options": {
                "useT90Components": True,
                "customPlayerInfos": [{"referenceName": "x"}],
                "alwaysShowUnitPanel": None,
                "size": 1,
            },
            "stylesheets": ["a.css"],
            "assets": {"logo": "l1.png", "colApm": "c.png"},
        },
        **{"a.css": "", "l1.png": "", "c.png": ""},
    )
    _folder(
        root,
        "b",
        {
            "options": {
                "useT90Components": False,
                "showSkinLogo": True,
                "customPlayerInfos": [{"referenceName": "y"}],
                "alwaysShowUnitPanel": True,
                "size": 2,
            },
            "stylesheets": ["b.css"],
            "assets": {"logo": "l2.png"},
        },
        **{"b.css": "", "l2.png": ""},
    )
    _folder(root, "bad", {"stylesheets": []})
    (root / "bad" / "skin.json").write_text("[]")
    store = SkinStore(root)
    m = store.merged(["a", "b", "bad", "ghost"])
    assert m["enabled"] == ["a", "b"]
    assert m["options"]["useT90Components"] is True  # OR-ed
    assert m["options"]["showSkinLogo"] is True and m["options"]["alwaysShowUnitPanel"] is True
    assert m["options"]["customPlayerInfos"] == [{"referenceName": "x"}, {"referenceName": "y"}]
    assert m["options"]["size"] == 2  # scalars: later wins
    assert m["stylesheets"] == ["/skins/a/a.css", "/skins/b/b.css"]
    assert m["assets"]["logo"] == "/skins/b/l2.png" and m["assets"]["colApm"] == "/skins/a/c.png"
    assert store.merged([]) == {"options": {}, "stylesheets": [], "assets": {}, "enabled": []}


def test_add_by_path_folder_and_zip_then_remove(tmp_path: Path) -> None:
    store = SkinStore(tmp_path / "skins", tmp_path / "added.json")
    ext = _folder(tmp_path / "elsewhere", "Mine", {"stylesheets": ["m.css"]}, **{"m.css": "m{}"})
    z = tmp_path / "Zipped.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("skin.json", "{}")
    assert store.add(str(ext), "folder") == {"ok": True, "name": "Mine", "kind": "folder"}
    assert store.add(str(z)) == {"ok": True, "name": "Zipped", "kind": "zip"}
    assert store.add(str(ext))["name"] == "Mine"  # idempotent
    assert [r["name"] for r in store.rows()] == ["Mine", "Zipped"]
    assert store.file("Mine", "m.css") == (b"m{}", "text/css")
    # a fresh store reads the registry back
    assert [r["name"] for r in SkinStore(tmp_path / "skins", tmp_path / "added.json").rows()] == [
        "Mine",
        "Zipped",
    ]
    assert store.add(str(tmp_path / "nope"))["ok"] is False
    assert store.add(str(ext), "zip")["ok"] is False  # wrong kind
    assert store.add(str(tmp_path / "elsewhere"))["ok"] is False  # no skin.json
    notzip = tmp_path / "x.zip"
    notzip.write_text("no")
    assert store.add(str(notzip))["ok"] is False
    assert store.remove("Mine") == {"ok": True}
    assert [r["name"] for r in store.rows()] == ["Zipped"]
    assert store.remove("ghost")["ok"] is False


def test_version_changes_when_a_skin_file_changes(tmp_path: Path) -> None:
    root = tmp_path / "skins"
    d = _folder(root, "S", {"stylesheets": ["s.css"]}, **{"s.css": "a{}"})
    store = SkinStore(root)
    v0 = store.version(max_age=0)
    assert store.version(max_age=0) == v0  # nothing changed
    (d / "s.css").write_text("a{color:red}")
    v1 = store.version(max_age=0)
    assert v1 > v0
    _folder(root, "T", {})  # a new skin shows up too
    assert store.version(max_age=0) > v1
