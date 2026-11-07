"""Retained observation comparison: no native, Wine, game or API execution."""

import copy
import json

import pytest

from vantage import native_reference_compare as N


def write(tmp_path, name, rows, *, producer="game", association="authenticated", fields=None):
    source = tmp_path / (name + ".source")
    source.write_text("fixture " + name)
    path = tmp_path / (name + ".ndjson")
    N._write(
        path,
        N.header(
            source,
            "a" * 64,
            producer,
            association,
            fields=fields or {"hp_bits": "float32_bits", "owner": "int32"},
        ),
        rows,
    )
    return path


def observations():
    return [
        dict(
            time_ms=t,
            phase="after_world_update",
            entities={"7": {"hp_bits": 1065353216, "owner": 1}},
        )
        for t in (0, 18, 36)
    ]


def test_deliberately_altered_reference_has_exact_first_clock_entity_field_and_repeatability(
    tmp_path,
):
    original = observations()
    altered = copy.deepcopy(original)
    altered[1]["entities"]["7"]["hp_bits"] += 1
    reference = write(tmp_path, "reference", altered)
    native = write(tmp_path, "native", original, producer="native")
    result = N.compare(reference, native)
    assert result == N.compare(reference, native)
    first = result["first_observable_difference"]
    assert first["time_ms"] == 18
    assert first["examples"] == [
        dict(entity_id=7, field="hp_bits", reference=1065353217, native=1065353216)
    ]
    assert first["preceding_matching_observation"]["time_ms"] == 0
    assert result["first_phase_aligned_difference_with_authenticated_replay"] == first
    assert result["simulation_accuracy_proven"] is False


def test_unknown_phase_retains_difference_without_claiming_state_mismatch(tmp_path):
    altered = observations()
    altered[0]["entities"]["7"]["owner"] = 2
    altered[0]["phase"] = "unknown"
    result = N.compare(
        write(tmp_path, "reference", altered),
        write(tmp_path, "native", observations(), producer="native"),
    )
    assert (
        result["first_observable_difference"]["classification"]
        == "publication_phase_ambiguous_difference"
    )
    assert result["first_phase_aligned_difference_with_authenticated_replay"] is None


def test_no_missing_equals_zero_and_incomparable_producer_fields(tmp_path):
    reference = observations()
    for row in reference:
        del row["entities"]["7"]["owner"]
    native = observations()
    for row in native:
        row["entities"]["7"]["owner"] = 0
    result = N.compare(
        write(tmp_path, "reference", reference),
        write(tmp_path, "native", native, producer="native"),
    )
    assert result["first_observable_difference"] is None
    assert result["unavailable_field_pairs"] == {"owner": 3}
    result = N.compare(
        write(tmp_path, "reference2", reference),
        write(
            tmp_path,
            "native2",
            native,
            producer="native",
            fields={"hp_bits": "int32", "owner": "int32"},
        ),
    )
    assert result["shared_fields"] == ["owner"]
    assert result["incomparable_fields"] == ["hp_bits"]


def test_inferred_replay_and_native_vs_native_never_confirm_game_state_difference(tmp_path):
    original, altered = observations(), observations()
    altered[0]["entities"]["7"]["owner"] = 2
    result = N.compare(
        write(tmp_path, "reference", altered, association="inferred"),
        write(tmp_path, "native", original, producer="native"),
    )
    assert result["first_phase_aligned_difference_with_authenticated_replay"] is None
    result = N.compare(
        write(tmp_path, "reference2", altered, producer="native"),
        write(tmp_path, "native2", original, producer="native"),
    )
    assert result["independent_game_reference"] is False
    assert result["first_phase_aligned_difference_with_authenticated_replay"] is None


def test_exact_clock_join_and_bounded_examples(tmp_path):
    rows = observations()
    rows[1]["time_ms"] = 19
    altered = observations()
    altered[2]["entities"] = {str(i): {"owner": 2} for i in range(1, 100)}
    rows[2]["entities"] = {str(i): {"owner": 1} for i in range(1, 100)}
    result = N.compare(
        write(tmp_path, "reference", altered),
        write(tmp_path, "native", rows, producer="native"),
        example_limit=2,
    )
    assert result["first_observable_difference"]["time_ms"] == 36
    assert len(result["first_observable_difference"]["examples"]) == 2
    assert result["first_observable_difference"]["differences"] == 99
    assert result["counts"]["reference_unjoined_clocks"] == 1
    assert result["counts"]["native_unjoined_clocks"] == 1


@pytest.mark.parametrize(
    "change",
    ["replay", "duplicate_clock", "duplicate_key", "nonpositive_id", "bool_as_int", "nonfinite"],
)
def test_invalid_inputs_rejected(tmp_path, change):
    reference = write(tmp_path, "reference", observations())
    rows = observations()
    if change == "duplicate_clock":
        rows[2]["time_ms"] = rows[1]["time_ms"]
    if change == "nonpositive_id":
        rows[0]["entities"]["0"] = {}
    if change == "bool_as_int":
        rows[0]["entities"]["7"]["owner"] = True
    native = write(tmp_path, "native", rows, producer="native")
    if change == "replay":
        native.write_text(native.read_text().replace('"a' + "a" * 63 + '"', '"' + "b" * 64 + '"'))
    if change == "duplicate_key":
        native.write_text(native.read_text().replace('"time_ms":0', '"time_ms":0,"time_ms":1'))
    if change == "nonfinite":
        native.write_text(native.read_text().replace('"owner":1', '"owner":NaN'))
    with pytest.raises(ValueError):
        N.compare(reference, native)


def test_native_import_applies_snapshot_deltas_and_filters_exact_samples(tmp_path):
    source = tmp_path / "native.log"
    rows = [
        dict(stage="native_entity_frame", time_ms=t, kind=kind, removed=removed, entities=entities)
        for t, kind, removed, entities in [
            (0, "snapshot", [], [[7, 1, 83, 10, 1, 2, 3, 4]]),
            (18, "delta", [], [[7, 1, 83, 10, 1, 2, 3, 5]]),
            (36, "delta", [7], []),
        ]
    ]
    source.write_text("".join(json.dumps(row) + "\n" for row in rows))
    output = tmp_path / "native.ndjson"
    N.export_native(source, output, replay_sha256="a" * 64, times={18, 36})
    result = list(N.Observations(output))
    assert result[0]["entities"]["7"]["hp_bits"] == 5
    assert result[1]["entities"] == {}
    assert result[0]["time_ms"] == 18


def test_vrec_import_uses_decoded_field_presence_and_float_bits(tmp_path):
    from tests.helpers import PatchBuilder, fid
    from vantage.frames import Frame, RecordingWriter
    from vantage.schema import SCHEMA

    builder = PatchBuilder().create(fid("Root", "world"), SCHEMA.model_id("World"))
    builder.create_key(fid("World", "entities"), SCHEMA.model_id("Entity"), 7)
    builder.assign(fid("Entity", "hp"), "Float", 1.0)
    builder.assign(fid("Entity", "worldX"), "Float", 0.0)
    builder.pop().pop()
    source = tmp_path / "game.vrec"
    with RecordingWriter(source, {"source": "test"}) as writer:
        writer.write(Frame(0, builder.forward()))
    output = tmp_path / "game.ndjson"
    N.export_vrec(source, output, replay_sha256="a" * 64)
    result = list(N.Observations(output))
    assert result[0]["entities"] == {"7": {"hp_bits": 1065353216, "x_bits": 0}}
    assert result[0]["phase"] == "unknown"
