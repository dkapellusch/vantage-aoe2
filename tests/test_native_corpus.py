"""Corpus reports keep historical observations and executed qualification separate."""

import json
from pathlib import Path

import pytest

from vantage import native_corpus as corpus
from vantage.native_conversion import pin


def write(path, value):
    path.write_text(json.dumps(value))
    return pin(path)


def checksum_fixture(tmp_path):
    replay = tmp_path / "replay.aoe2record"
    replay.write_bytes(b"fixture, never a real native compatibility result")
    host = tmp_path / "host.cpp"
    host.write_bytes(b"fixture producer")
    capture = tmp_path / "native.stdout.log"
    stop = {
        "stage": "native_sync_stopped",
        "status": 3,
        "world_time_ms": 1310937,
        "ignore_checksum_global": 0,
    }
    failure = {"stage": "native_prefix_sync", "error": 207, "ok": False}
    capture.write_text(json.dumps(stop) + "\n" + json.dumps(failure) + "\n")
    receipt = write(
        tmp_path / "native.process-exit.json",
        {
            "exit_code": 1,
            "timed_out": False,
            "cancelled": False,
            "stdout_sha256": pin(capture)["sha256"],
        },
    )
    evidence = write(
        tmp_path / "evidence.json",
        {"capture": pin(capture), "receipt": receipt, "stop": stop, "failure": failure},
    )
    entry = {
        "id": "public-1v1",
        "scope": "unit fixture",
        "evidence_kind": "native_worker_baseline",
        "replay": pin(replay),
        "evidence": evidence,
        "import_format": "checksum_report",
        "producer": {"name": "fixture-producer", "pins": {"host": pin(host)}},
        "expected": {
            "outcome": "checksum_rejection",
            "world_time_ms": 1310937,
            "original_checksum_enforced": True,
        },
        "execution_tiers": [],
    }
    manifest = tmp_path / "manifest.json"
    write(manifest, {"kind": "vantage_native_replay_corpus", "version": 1, "entries": [entry]})
    return manifest, entry


def test_metadata_is_not_a_reproduced_runtime_result(tmp_path):
    manifest, _ = checksum_fixture(tmp_path)
    report = corpus.scorecard(manifest)
    row = report["entries"][0]
    assert row["status"] == "metadata_verified"
    assert row["observation"]["outcome"] == "checksum_rejection"
    assert row["origin"] == "retained_import"
    assert not row["baseline_reproduced"]
    assert not report["fresh_poc0_runtime_gate_satisfied"]
    assert not row["evidence"]["raw_evidence_revalidated"]


def test_closed_checksum_capture_revalidated_without_becoming_fresh(tmp_path):
    manifest, _ = checksum_fixture(tmp_path)
    report = corpus.scorecard(manifest, verify_retained=True)
    row = report["entries"][0]
    assert row["status"] == "passed"
    assert row["evidence"]["raw_evidence_revalidated"]
    assert not row["baseline_reproduced"]
    assert report["summary"]["passed"] == 1
    assert not report["fresh_poc0_runtime_gate_satisfied"]


def test_repeat_preserves_result_identity_and_checksum_outcome(tmp_path):
    manifest, _ = checksum_fixture(tmp_path)
    first, second = (corpus.scorecard(manifest, verify_retained=True) for _ in range(2))
    assert first["entries"][0]["result_identity"] == second["entries"][0]["result_identity"]
    assert first["entries"][0]["observation"] == second["entries"][0]["observation"]


def test_changed_input_fails_and_missing_input_skips(tmp_path):
    manifest, entry = checksum_fixture(tmp_path)
    replay = Path(entry["replay"]["path"])
    replay.write_bytes(b"changed")
    row = corpus.scorecard(manifest)["entries"][0]
    assert row["status"] == "failed" and "Pinned input changed" in row["error"]
    replay.unlink()
    row = corpus.scorecard(manifest)["entries"][0]
    assert row["status"] == "skipped" and row["skip_reason"]
    assert not row["baseline_reproduced"]


def test_missing_recipe_never_runs_a_different_producer(tmp_path, monkeypatch):
    manifest, _ = checksum_fixture(tmp_path)
    monkeypatch.setattr(corpus, "execute_v32", lambda *a, **k: pytest.fail("wrong worker launched"))
    report = corpus.scorecard(manifest, tier="full", execute=True, work_root=tmp_path / "work")
    assert report["entries"][0]["status"] == "skipped"
    assert report["summary"]["passed"] == 0


def test_raw_receipt_cannot_be_replaced_by_retained_success_label(tmp_path):
    manifest, _ = checksum_fixture(tmp_path)
    # A changed raw log is rejected, even though the imported JSON says the known stop occurred.
    (tmp_path / "native.stdout.log").write_text("no terminal evidence\n")
    row = corpus.scorecard(manifest, verify_retained=True)["entries"][0]
    assert row["status"] == "failed"
    assert not row["baseline_reproduced"]


def test_checksum_tail_must_match_pinned_report(tmp_path):
    manifest, entry = checksum_fixture(tmp_path)
    capture = tmp_path / "native.stdout.log"
    capture.write_text(capture.read_text().replace("1310937", "1310955"))
    receipt = tmp_path / "native.process-exit.json"
    r = json.loads(receipt.read_text())
    r["stdout_sha256"] = pin(capture)["sha256"]
    write(receipt, r)
    evidence = Path(entry["evidence"]["path"])
    e = json.loads(evidence.read_text())
    e["capture"] = pin(capture)
    e["receipt"] = pin(receipt)
    entry["evidence"] = write(evidence, e)
    doc = json.loads(manifest.read_text())
    doc["entries"] = [entry]
    write(manifest, doc)
    row = corpus.scorecard(manifest, verify_retained=True)["entries"][0]
    assert row["status"] == "failed" and "differs from closed capture" in row["error"]


@pytest.mark.parametrize(
    "receipt,expected",
    [
        ({"exit_code": 1, "cancelled": True}, "cancelled"),
        ({"exit_code": 1, "timed_out": True}, "timeout"),
        ({"exit_code": -11}, "crash"),
        ({"exit_code": 1}, "checksum_rejection"),
    ],
)
def test_closed_process_outcomes_are_distinct(receipt, expected):
    stop = {"status": 3, "ignore_checksum_global": 0}
    failure = {"stage": "native_prefix_sync", "error": 207, "ok": False}
    assert corpus.classify_process(receipt, stop=stop, failure=failure) == expected


@pytest.mark.parametrize(
    "reason,ended,expected",
    [
        ("native_game_end", True, "native_game_end"),
        ("recording_eof", False, "recording_eof"),
        ("recording_eof", True, "unverified"),
    ],
)
def test_eof_is_not_game_end(reason, ended, expected):
    terminal = {
        "recording_end_reason": reason,
        "game_ended": ended,
        "original_terminal_event": {"checksum_ignore_global": 0},
    }
    assert corpus.classify_process({"exit_code": 0}, terminal=terminal) == expected
    terminal["original_terminal_event"]["checksum_ignore_global"] = 1
    assert corpus.classify_process({"exit_code": 0}, terminal=terminal) == "unverified"


def test_checksum_bypass_or_successful_exit_cannot_count_as_rejection():
    failure = {"stage": "native_prefix_sync", "error": 207, "ok": False}
    assert (
        corpus.classify_process(
            {"exit_code": 1}, stop={"status": 3, "ignore_checksum_global": 1}, failure=failure
        )
        == "crash"
    )
    assert (
        corpus.classify_process(
            {"exit_code": 0}, stop={"status": 3, "ignore_checksum_global": 0}, failure=failure
        )
        == "unverified"
    )


def test_execution_requires_explicit_work_root_and_nonmetadata_tier(tmp_path):
    manifest, _ = checksum_fixture(tmp_path)
    with pytest.raises(ValueError, match="Execution needs"):
        corpus.scorecard(manifest, execute=True, work_root=tmp_path)
    with pytest.raises(ValueError, match="Execution needs"):
        corpus.scorecard(manifest, execute=True, tier="short")


def test_result_identity_ignores_locations_but_pins_exact_producer(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    ma, _ = checksum_fixture(a)
    mb, _ = checksum_fixture(b)
    ra = corpus.scorecard(ma)["entries"][0]
    rb = corpus.scorecard(mb)["entries"][0]
    assert ra["result_identity"] == rb["result_identity"]
    assert ra["producer"]["identity"] == rb["producer"]["identity"]


def test_unknown_entry_rejected_and_duplicate_identity_rejected(tmp_path):
    manifest, entry = checksum_fixture(tmp_path)
    with pytest.raises(ValueError, match="Unknown corpus"):
        corpus.scorecard(manifest, entries=["does-not-exist"])
    doc = json.loads(manifest.read_text())
    doc["entries"].append(entry)
    write(manifest, doc)
    with pytest.raises(ValueError, match="Duplicate"):
        corpus.load_manifest(manifest)


def test_complete_frame_comparison_ignores_header_but_detects_events_and_extent(tmp_path):
    from vantage.frames import Frame, RecordingWriter

    candidate, reference = tmp_path / "a.vrec", tmp_path / "b.vrec"
    frames = [Frame(0, b"snapshot"), Frame(17, b"update", events=[{"event": "hit"}])]
    for path in (candidate, reference):
        with RecordingWriter(path, {"source": str(path)}) as writer:
            for frame in frames:
                writer.write(frame)
    comparison = corpus.compare_frame_payloads(candidate, reference, expected_frames=2)
    assert comparison["all_frame_envelopes_and_payloads_equal"]
    assert comparison["frames"] == 2 and comparison["end_ms"] == 17
    with RecordingWriter(candidate) as writer:
        writer.write(frames[0])
        writer.write(Frame(17, b"update", events=[{"event": "miss"}]))
    comparison = corpus.compare_frame_payloads(candidate, reference, expected_frames=2)
    assert not comparison["all_frame_envelopes_and_payloads_equal"]
    assert comparison["first_difference"]["frame_index"] == 1
    with RecordingWriter(candidate) as writer:
        for frame in frames:
            writer.write(frame)
        writer.write(Frame(18, b"extra"))
    comparison = corpus.compare_frame_payloads(candidate, reference, expected_frames=2)
    assert not comparison["all_frame_envelopes_and_payloads_equal"]
    assert comparison["first_difference"]["reference_time_ms"] is None


def test_revalidated_completed_job_has_explicit_origin(tmp_path, monkeypatch):
    manifest, _ = checksum_fixture(tmp_path)
    monkeypatch.setattr(
        corpus,
        "revalidate_completed_job",
        lambda *_a: (
            {
                "outcome": "checksum_rejection",
                "world_time_ms": 1310937,
                "original_checksum_enforced": True,
            },
            {"raw_evidence_revalidated": True},
        ),
    )
    report = corpus.scorecard(manifest, completed_jobs={"public-1v1": tmp_path / "closed"})
    row = report["entries"][0]
    assert row["status"] == "passed" and row["origin"] == "completed_job_revalidation"
    assert not row["baseline_reproduced"]
    assert not report["fresh_poc0_runtime_gate_satisfied"]


def test_manifest_mutation_during_observation_is_rejected(tmp_path, monkeypatch):
    manifest, _ = checksum_fixture(tmp_path)
    original = corpus.import_retained

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        manifest.write_text(manifest.read_text() + "\n")
        return result

    monkeypatch.setattr(corpus, "import_retained", mutate)
    with pytest.raises(ValueError, match="Manifest changed during"):
        corpus.scorecard(manifest)


def test_missing_or_boolean_exit_receipt_is_unverified():
    assert corpus.classify_process({}) == "unverified"
    assert corpus.classify_process({"exit_code": False}) == "unverified"


def test_boolean_numeric_fields_and_nonboolean_receipt_flags_cannot_be_evidence():
    failure = {"stage": "native_prefix_sync", "error": 207, "ok": False}
    stop = {"status": 3, "ignore_checksum_global": False}
    assert corpus.classify_process({"exit_code": 1}, stop=stop, failure=failure) == "crash"
    terminal = {
        "recording_end_reason": "recording_eof",
        "game_ended": False,
        "original_terminal_event": {"checksum_ignore_global": False},
    }
    assert corpus.classify_process({"exit_code": 0}, terminal=terminal) == "unverified"
    assert corpus.classify_process({"exit_code": 1, "timed_out": 0}) == "unverified"
