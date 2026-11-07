"""Historical retention must preserve current work and exact original contracts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import native_encoder_retain as retain
from vantage.native_conversion import pin


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    source = tmp_path / "codec.py"
    source.write_bytes(b"historical codec\n")
    expected = pin(source)
    git("add", "codec.py")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Historical codec",
    )
    source.write_bytes(b"uncommitted user work\n")
    parent = tmp_path / "parent.json"
    parent.write_text(
        json.dumps(dict(source_evidence=expected, source_contracts=[], codec_pins=[]))
    )
    config = tmp_path / "config.json"
    config.write_text(json.dumps(dict(parent_profile=pin(parent), overlays=[])))
    monkeypatch.setattr(retain, "ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(retain, "verify_encoder_config", lambda *a, **kw: calls.append(a))
    return source, expected, parent, config, calls


def test_recovers_exact_committed_bytes_without_touching_current_work(repository, tmp_path):
    source, expected, _, config, calls = repository
    original, current = pin(config), pin(source)
    result = retain.retain_encoder(config, tmp_path / "retained")
    assert pin(source) == current and pin(config) == original
    assert len(result["recovered"]) == 1 and len(calls) == 1
    recovered = result["recovered"][0]["source"]
    assert (recovered["bytes"], recovered["sha256"]) == (expected["bytes"], expected["sha256"])
    derived = json.loads(Path(result["config"]["path"]).read_bytes())
    assert derived["overlays"][0]["expected_sha256"] == expected["sha256"]
    assert result["worktree_modified"] is False


def test_missing_exact_blob_fails_without_replacing_expected_digest(repository, tmp_path):
    source, expected, parent, config, calls = repository
    parent.write_text(
        json.dumps(
            dict(
                source_evidence=dict(expected, sha256="0" * 64), source_contracts=[], codec_pins=[]
            )
        )
    )
    config.write_text(json.dumps(dict(parent_profile=pin(parent), overlays=[])))
    current = pin(source)
    with pytest.raises(ValueError, match="No exact historical bytes"):
        retain.retain_encoder(config, tmp_path / "missing")
    assert not calls and pin(source) == current
    assert not (tmp_path / "missing" / "retention.json").exists()


def test_changed_parent_rejected_before_any_overlay_is_created(repository, tmp_path):
    _, _, parent, config, calls = repository
    parent.write_text("changed")
    output = tmp_path / "rejected"
    with pytest.raises(ValueError, match="parent profile changed"):
        retain.retain_encoder(config, output)
    assert not output.exists() and not calls
