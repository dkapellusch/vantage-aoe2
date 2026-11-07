"""Exact serialized payloads and paired timing evidence are separate gates."""

import gzip
import importlib.util
from pathlib import Path

import pytest

from vantage.frames import Frame, RecordingWriter

spec = importlib.util.spec_from_file_location(
    "native_replay_benchmark",
    Path(__file__).resolve().parents[1] / "tools/native_replay_benchmark.py",
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_raw_frame_digest_includes_envelope_and_all_four_blobs(tmp_path):
    reference = tmp_path / "a.vrec"
    candidate = tmp_path / "b.vrec"
    original = Frame(
        13, b"patch", reverse=b"reverse", events=[{"hit": 1}], commands=[{"move": 3}], skipped=2
    )
    with RecordingWriter(reference, {"created": 1}) as writer:
        writer.write(original)
    expected = benchmark.scan_serialized_frames(reference)
    for field, changed in [
        ("time", 14),
        ("skipped", 1),
        ("patch", b"changed"),
        ("reverse", b"changed"),
        ("events", [{"hit": 2}]),
        ("commands", [{"move": 4}]),
    ]:
        values = {
            name: getattr(original, name)
            for name in ("time", "skipped", "patch", "reverse", "events", "commands")
        }
        values[field] = changed
        with RecordingWriter(candidate, {"created": 1}) as writer:
            writer.write(Frame(**values))
        assert (
            benchmark.scan_serialized_frames(candidate)["serialized_frame_payload_sha256"]
            != expected["serialized_frame_payload_sha256"]
        )
    with RecordingWriter(candidate, {"created": 2}) as writer:
        writer.write(original)
    assert (
        benchmark.scan_serialized_frames(candidate)["serialized_frame_payload_sha256"]
        == expected["serialized_frame_payload_sha256"]
    )


def test_reader_rejects_torn_serialized_tail_instead_of_comparing_prefix(tmp_path):
    path = tmp_path / "broken.vrec"
    with RecordingWriter(path) as writer:
        writer.write(Frame(0, b"full"))
    raw = gzip.decompress(path.read_bytes())
    with gzip.open(path, "wb") as stream:
        stream.write(raw[:-1])
    with pytest.raises(ValueError, match="Truncated"):
        benchmark.scan_serialized_frames(path)


def test_frame_count_and_final_clock_are_retained(tmp_path):
    path = tmp_path / "a.vrec"
    with RecordingWriter(path) as writer:
        writer.write(Frame(0, b"first"))
        writer.write(Frame(17, b"last"))
    result = benchmark.scan_serialized_frames(path)
    assert result["frames"] == 2 and result["end_ms"] == 17 and result["all_frames_consumed"]


def runs(times):
    return [
        {
            "label": label,
            "frames": {"frames": 513, "end_ms": 8840, "serialized_frame_payload_sha256": "same"},
            "timings": {
                "encoder_child_seconds": value,
                "admission_and_encoding_seconds": value + 1,
            },
        }
        for label, value in zip(benchmark.ORDER, times, strict=False)
    ]


def test_improvement_requires_exact_payloads_and_both_candidate_runs_faster():
    result = benchmark.evaluate_runs(runs([10, 8, 8.1, 10.1]), minimum_improvement=0.05)
    assert result["repeatable_encoder_component_improvement_observed"]
    changed = runs([10, 8, 8, 10])
    changed[1]["frames"]["serialized_frame_payload_sha256"] = "different"
    assert not benchmark.evaluate_runs(changed, minimum_improvement=0.05)[
        "repeatable_encoder_component_improvement_observed"
    ]
    noisy = benchmark.evaluate_runs(runs([10, 6, 10.2, 11]), minimum_improvement=0.05)
    assert not noisy["repeatable_encoder_component_improvement_observed"]


def test_equal_or_slower_candidate_is_not_a_success():
    for values in ([10, 10, 10, 10], [10, 11, 11, 10]):
        report = benchmark.evaluate_runs(runs(values), minimum_improvement=0.05)
        assert report["all_exact_frame_envelopes_and_four_payloads_equal"]
        assert not report["repeatable_encoder_component_improvement_observed"]
        assert not report["complete_simulation_conversion_speedup_claimed"]


def test_partial_out_of_order_or_invalid_timing_cannot_pass():
    with pytest.raises(ValueError, match="Complete A/B/B/A"):
        benchmark.evaluate_runs(runs([10, 8]), minimum_improvement=0.05)
    invalid = runs([10, 8, 8, 10])
    invalid[1]["timings"]["encoder_child_seconds"] = 0
    with pytest.raises(ValueError, match="Positive measured"):
        benchmark.evaluate_runs(invalid, minimum_improvement=0.05)
