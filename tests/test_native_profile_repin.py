from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "native_profile_repin", Path(__file__).resolve().parents[1] / "tools/native_profile_repin.py"
)
assert spec is not None and spec.loader is not None
repin_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repin_tool)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_changed_aliased_dropped_and_cross_referenced_pins(tmp_path: Path) -> None:
    wine = _write(tmp_path / "bin/wine", "old")
    old_wine = repin_tool.pin(wine)
    wine.write_text("upgraded")
    legacy = _write(tmp_path / "dev/forge/spectate/frames.py", "x")
    legacy_pin = repin_tool.pin(legacy)
    legacy.unlink()
    target = _write(tmp_path / "vantage/src/vantage/frames.py", "frames")
    test = _write(tmp_path / "dev/tests/test_spectate_frames.py", "t")
    test_pin = repin_tool.pin(test)
    test.unlink()
    leaf = _write(tmp_path / "profiles/encoder.json", json.dumps({"pins": [old_wine]}))
    root = _write(
        tmp_path / "profiles/runtime.json",
        json.dumps({"encoder": repin_tool.pin(leaf), "pins": [legacy_pin, test_pin, old_wine]}),
    )
    out = tmp_path / "out"
    result = repin_tool.repin(
        [root, leaf],
        out,
        (tmp_path / "dev/forge/spectate", tmp_path / "vantage/src/vantage"),
        [tmp_path / "dev/tests"],
        "2026-11-07",
    )
    new_leaf = json.loads((out / "encoder.json").read_text())
    new_root = json.loads((out / "runtime.json").read_text())
    assert new_leaf["pins"] == [repin_tool.pin(wine)]
    assert new_root["encoder"] == repin_tool.pin(out / "encoder.json")
    assert new_root["pins"] == [repin_tool.pin(target), repin_tool.pin(wine)]
    kinds = sorted(c["kind"] for c in new_root["repinned"]["changes"])
    assert kinds == ["alias", "changed", "dropped", "profile"]
    assert result[str(root)] == repin_tool.pin(out / "runtime.json")
    # The originals are untouched evidence.
    assert json.loads(leaf.read_text()) == {"pins": [old_wine]}


def test_an_unresolvable_missing_input_is_an_error(tmp_path: Path) -> None:
    gone = _write(tmp_path / "gone.py", "x")
    row = repin_tool.pin(gone)
    gone.unlink()
    profile = _write(tmp_path / "p/profile.json", json.dumps({"pins": [row]}))
    with pytest.raises(SystemExit, match="cannot be resolved"):
        repin_tool.repin([profile], tmp_path / "out", None, [], "2026-11-07")


def test_a_profile_that_still_holds_is_not_copied(tmp_path: Path) -> None:
    ok = _write(tmp_path / "ok.py", "x")
    profile = _write(tmp_path / "p/profile.json", json.dumps({"pins": [repin_tool.pin(ok)]}))
    assert repin_tool.repin([profile], tmp_path / "out", None, [], "2026-11-07") == {}
    assert not (tmp_path / "out/profile.json").exists()
