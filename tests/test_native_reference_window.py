"""Published-field persistence controls; no native/game target execution."""

from vantage import native_reference_compare as C
from vantage.native_reference_window import difference_runs


def observations(tmp_path, name, values, *, times=None):
    source = tmp_path / (name + ".source")
    source.write_text("fixture")
    output = tmp_path / (name + ".ndjson")
    C._write(
        output,
        C.header(source, "a" * 64, "synthetic", "synthetic", fields={"hp_bits": "float32_bits"}),
        [
            {
                "time_ms": clock,
                "phase": "unknown",
                "entities": {"7": {} if value is None else {"hp_bits": value}},
            }
            for clock, value in zip(times or range(len(values)), values, strict=True)
        ],
    )
    return output


def test_transient_mismatch_resolves_at_next_available_sample(tmp_path):
    result = difference_runs(
        observations(tmp_path, "r", [20, 20, 5, 5]), observations(tmp_path, "n", [20, 5, 5, 5])
    )
    assert result["first_persistent_field_difference"] is None
    run = result["bounded_run_examples"][0]
    assert (run["entity_id"], run["first_ms"], run["samples"]) == (7, 1, 1)
    assert run["next_observation_ms"] == 2 and run["end_reason"] == "shared_field_matches"


def test_persistent_means_two_consecutive_compared_samples(tmp_path):
    result = difference_runs(
        observations(tmp_path, "r", [20, 20, 20, 5]), observations(tmp_path, "n", [20, 5, 5, 5])
    )
    run = result["first_persistent_field_difference"]
    assert (run["first_ms"], run["last_ms"], run["samples"]) == (1, 2, 2)


def test_unavailable_is_not_matching_zero_and_interrupts_persistence(tmp_path):
    result = difference_runs(
        observations(tmp_path, "r", [20, None, 20]), observations(tmp_path, "n", [0, 0, 0])
    )
    assert result["total_field_difference_runs"] == 2
    assert result["first_persistent_field_difference"] is None
    assert result["bounded_run_examples"][0]["end_reason"] == "field_or_entity_unavailable"


def test_unjoined_clock_interrupts_comparability(tmp_path):
    result = difference_runs(
        observations(tmp_path, "r", [20, 20, 20], times=[0, 1, 2]),
        observations(tmp_path, "n", [0, 0], times=[0, 2]),
    )
    assert result["first_persistent_field_difference"] is None
    assert (
        result["bounded_run_examples"][0]["end_reason"] == "unjoined_clock_interrupts_comparability"
    )


def test_first_persistent_run_uses_start_clock_when_runs_close_in_different_order(tmp_path):
    import json

    reference = observations(tmp_path, "r", [20, 20, 20, 20])
    native = observations(tmp_path, "n", [0, 0, 0, 0])
    for path, values in ((reference, [20, 20, 20, 20]), (native, [20, 0, 0, 20])):
        lines = path.read_text().splitlines()
        for i, value in enumerate(values, 1):
            row = json.loads(lines[i])
            row["entities"]["8"] = {"hp_bits": value}
            lines[i] = json.dumps(row)
        path.write_text("\n".join(lines) + "\n")
    result = difference_runs(reference, native)
    assert result["first_persistent_field_difference"]["entity_id"] == 7
    assert result["first_persistent_field_difference"]["first_ms"] == 0
