"""Experimental encoder refuses unpinned input and scopes cancellation."""

from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from vantage import native_v32_encode as encoder
from vantage.native_conversion import pin


def test_bad_configuration_hash_is_rejected_before_output(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"kind": "vantage_experimental_v32_encoder", "version": 1}))
    worker = encoder.V32Encoder()
    with pytest.raises(encoder.V32EncodeError, match="configuration differs"):
        worker.encode(
            tmp_path,
            {},
            stage_sha256="0" * 64,
            runtime_profile=config,
            runtime_profile_sha256="0" * 64,
            encoder_config=config,
            encoder_config_sha256="0" * 64,
        )
    assert not (tmp_path / "encodes").exists()
    with pytest.raises(encoder.V32EncodeError, match="single-use"):
        worker.encode(
            tmp_path,
            {},
            stage_sha256="0" * 64,
            runtime_profile=config,
            runtime_profile_sha256="0" * 64,
            encoder_config=config,
            encoder_config_sha256=pin(config)["sha256"],
        )


def test_cancellation_signals_only_owned_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = encoder.V32Encoder()
    calls = []

    class Child:
        pid = 424242

        def poll(self):
            return None

    worker._child = Child()
    monkeypatch.setattr(encoder.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    worker.cancel()
    assert calls == [(424242, signal.SIGTERM)] and worker._cancelled.is_set()


def test_tracked_join_runtime_binds_sources_and_reversible_substitution(tmp_path: Path) -> None:
    bundle = tmp_path / "fast"
    bundle.mkdir()
    wrapper, candidate = bundle / "encoder_wrapper.py", bundle / "candidate.py"
    wrapper.write_text("wrapper")
    candidate.write_text("candidate")
    original = tmp_path / "native-positive-sync-encoder-source-v3/encoder/convert.py"
    original.parent.mkdir(parents=True)
    original.write_text("def f():\n    geometry, presentation = {}, {}\n")
    config = {
        "encoder": pin(wrapper),
        "experimental_runtime": {
            "kind": "tracked_geometry_join_v1",
            "original": pin(original),
            "candidate": pin(candidate),
        },
    }
    contract = encoder._tracked_join_contract(config)
    assert contract["candidate"] == pin(candidate)
    assert len(contract["derived_source_sha256"]) == 64
    original.write_text(original.read_text() + "    geometry, presentation = {}, {}\n")
    config["experimental_runtime"]["original"] = pin(original)
    with pytest.raises(encoder.V32EncodeError, match="substitution differs"):
        encoder._tracked_join_contract(config)


def test_tracked_join_requires_matching_start_and_finish_provenance(tmp_path: Path) -> None:
    contract = {
        "original": {"sha256": "a" * 64},
        "candidate": {"sha256": "b" * 64},
        "derived_source_sha256": "c" * 64,
    }
    before = {
        "stage": "incremental_join_provenance",
        "original_encoder_sha256": "a" * 64,
        "candidate_sha256": "b" * 64,
        "derived_source_sha256": "c" * 64,
        "original_file_pin_represents_runtime_source": False,
        "shipping_profile_adopted": False,
    }
    after = {
        "stage": "incremental_join_verified",
        "candidate_sha256": "b" * 64,
        "inputs_unchanged": True,
    }
    output = tmp_path / "stdout"
    output.write_text(json.dumps(before) + "\n" + json.dumps(after) + "\n")
    assert encoder._verify_tracked_join_output(output, contract)["verified"] == after
    for records in (
        [before],
        [after, before],
        [before, dict(after, inputs_unchanged=False)],
        [before, dict(after, candidate_sha256="wrong")],
    ):
        output.write_text("".join(json.dumps(record) + "\n" for record in records))
        with pytest.raises(encoder.V32EncodeError):
            encoder._verify_tracked_join_output(output, contract)


def test_pinned_research_encoder_runs_in_the_repository_holding_it():
    from pathlib import Path

    from vantage.native_v32_encode import research_repository

    config = {"encoder": {"path": "/research/repo/artifacts/game-internals/x/encoder/convert.py"}}
    assert research_repository(config) == Path("/research/repo")
    own = research_repository({"encoder": {"path": "/elsewhere/convert.py"}})
    assert own == Path(__file__).resolve().parents[1]  # this package's repository
