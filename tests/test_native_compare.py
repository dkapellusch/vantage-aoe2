"""Adversarial checks for closed-capture comparison; no game/runtime execution."""

import copy
import hashlib
import json

import pytest

from vantage import native_compare as N


def descriptor():
    return dict(
        recording_sha256="a" * 64,
        recording_bytes=1000,
        inflated_save_sha256="b" * 64,
        inflated_save_bytes=100,
        initial_clock_ms=0,
        body_clock_origin_ms=0,
        body_offset=100,
        body_metadata_words=[5, 500, 0, 1, 1, 0, 0, 0],
        first_operation_kind="sync",
        first_operation_offset=100,
        final_clock_ms=54,
        world_player_count=2,
        bootstrap_syncs=[
            dict(delta_ms=18, time_ms=time, offset=offset, payload_bytes=4)
            for time, offset in [(18, 100), (36, 112), (54, 124)]
        ],
        operation_counts=[["sync", 3], ["postgame", 1]],
        sync_deltas_ms=[[18, 3]],
        postgame_offset=992,
        postgame_marker_end=996,
        postgame_remaining_bytes=4,
    )


def events():
    rows = [dict(stage=name, columns=["exact_bits"]) for name in sorted(N.SCHEMAS)]
    rows += [dict(stage=name, rows=[]) for name in sorted(N.INITIAL_DATA)]
    rows.append(N.positive_plan(descriptor()).declaration())
    for clock, kind in [(0, "snapshot"), (18, "delta")]:
        if clock:
            rows.append(
                dict(
                    stage="native_world_update_returned",
                    ordinal=1,
                    world_time_ms=18,
                    recorded_delta_ms=18,
                    status=0,
                    native_log_ms=18,
                    file_position=112,
                    clock_cycles=1,
                )
            )
        for index, stage in enumerate(N.FRAME_STAGES):
            row = dict(stage=stage, time_ms=clock, kind=kind, rows=[[7, 1065353216]], removed=[])
            if stage == "native_research_frame":
                row.update(readability_queries=21, readability_regions=21)
            rows.append(row)
            if kind == "snapshot" and index == 1:
                rows.append(dict(stage="native_technology_catalog", rows=[]))
    rows.append(
        dict(stage="native_sync_stopped", status=3, world_time_ms=18, ignore_checksum_global=0)
    )
    rows += [
        dict(stage="native_player_checksum_projection", world_index=index, fields=[index] * 11)
        for index in range(2)
    ]
    rows.append(dict(stage="native_prefix_sync", ok=False, error=207))
    return rows


def job(tmp_path, name, rows=None, *, raw=None, receipt_changes=None, descriptor_changes=None):
    out = tmp_path / name
    (out / "source").mkdir(parents=True)
    capture = (
        raw
        if raw is not None
        else "".join(json.dumps(row) + "\n" for row in (events() if rows is None else rows))
    )
    (out / "native.stdout.log").write_text(capture)
    receipt = dict(
        receipt_kind="ordinary_owned_subprocess",
        exit_code=1,
        timed_out=False,
        cancelled=False,
        all_input_pins_unchanged=True,
        stdout_sha256=hashlib.sha256(capture.encode()).hexdigest(),
    )
    receipt.update(receipt_changes or {})
    (out / "execution.json").write_text(json.dumps(receipt))
    description = descriptor()
    description.update(descriptor_changes or {})
    (out / "source/descriptor.json").write_text(json.dumps(description))
    return out


def test_identical_closed_failure_is_never_playback_success(tmp_path):
    result = N.compare_jobs(job(tmp_path, "old"), job(tmp_path, "new"))
    assert result["independent_capture_paths"] is True
    assert result["left"]["outcome"] == "closed_checksum_failure_not_playback_success"
    assert result["left"]["boundaries"] == 2
    assert result["conversion_accepted"] is False
    assert result["checksum_failure_is_success"] is False


@pytest.mark.parametrize("stage", N.FRAME_STAGES + tuple(sorted(N.INITIAL_DATA)))
def test_each_output_stream_and_initial_catalog_value_is_compared(tmp_path, stage):
    changed = events()
    next(row for row in changed if row["stage"] == stage)["unexpected_field"] = 1
    with pytest.raises(N.CaptureError, match="difference"):
        N.compare_jobs(job(tmp_path, "old"), job(tmp_path, "new", changed))


@pytest.mark.parametrize(
    "stage",
    N.FRAME_STAGES + tuple(sorted(N.SCHEMAS | N.INITIAL_DATA)) + ("native_technology_catalog",),
)
def test_missing_data_on_both_sides_is_rejected(tmp_path, stage):
    removed = [row for row in events() if row["stage"] != stage]
    with pytest.raises(N.CaptureError):
        N.compare_jobs(job(tmp_path, "old", removed), job(tmp_path, "new", removed))


@pytest.mark.parametrize("replacement", [True, 1.0, 1065353217])
def test_coordinate_bits_and_numeric_types_are_exact(tmp_path, replacement):
    changed = events()
    next(row for row in changed if row["stage"] == "native_entity_frame")["rows"][0][1] = (
        replacement
    )
    with pytest.raises(N.CaptureError, match="difference"):
        N.compare_jobs(job(tmp_path, "old"), job(tmp_path, "new", changed))


def test_readability_diagnostics_are_separate_and_not_silently_lost(tmp_path):
    changed = events()
    for row in changed:
        if row["stage"] == "native_research_frame":
            row.update(readability_queries=33, readability_regions=33)
    result = N.compare_jobs(job(tmp_path, "old"), job(tmp_path, "new", changed))
    assert result["left"]["observed_data_sha256"] == result["right"]["observed_data_sha256"]
    assert result["left"]["diagnostics"] != result["right"]["diagnostics"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("timed_out", True),
        ("cancelled", True),
        ("all_input_pins_unchanged", False),
        ("exit_code", True),
        ("exit_code", 9),
        ("stdout_sha256", "0" * 64),
    ],
)
def test_receipt_rejections(tmp_path, field, value):
    with pytest.raises(N.CaptureError, match="receipt"):
        N.compare_jobs(job(tmp_path, "old"), job(tmp_path, "new", receipt_changes={field: value}))


@pytest.mark.parametrize(
    "bad",
    [
        '{"stage":"x","stage":"y"}\n',
        '{"stage":"x","value":NaN}\n',
        '{"stage":"x","value":1e999}\n',
        "unrecognized output\n",
        "[1,2]\n",
    ],
)
def test_malformed_ignored_rows_are_also_rejected(tmp_path, bad):
    with pytest.raises(N.CaptureError):
        list(N.Capture(job(tmp_path, "bad", raw=bad)).records())


def test_known_resign_prefix_and_whitespace_only_rows(tmp_path):
    text = "\n".join(json.dumps(row) for row in events())
    text = "   \n2 ResignPlayer7 ResignPlayer" + text + "\n\t\n"
    result = N.compare_jobs(job(tmp_path, "old"), job(tmp_path, "new", raw=text))
    assert result["right"]["recovered_known_resign_prefixes"] == [
        dict(line=2, prefix="2 ResignPlayer7 ResignPlayer")
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_failure",
        "checksum_changed",
        "checksum_missing",
        "duplicate_update",
        "missing_frame",
        "reordered_frame",
        "ignore_checksum",
        "late_frame",
        "bad_diagnostic",
    ],
)
def test_trajectory_rejections(tmp_path, mutation):
    rows = events()
    if mutation == "missing_failure":
        rows.pop()
    elif mutation == "checksum_changed":
        next(row for row in rows if row["stage"] == "native_player_checksum_projection")["fields"][
            9
        ] += 1
    elif mutation == "checksum_missing":
        rows = [row for row in rows if row.get("world_index") != 1]
    elif mutation == "duplicate_update":
        update = next(row for row in rows if row["stage"] == "native_world_update_returned")
        rows.insert(rows.index(update), copy.deepcopy(update))
    elif mutation == "missing_frame":
        rows.remove(next(row for row in rows if row["stage"] == "native_activity_frame"))
    elif mutation == "reordered_frame":
        first = next(i for i, row in enumerate(rows) if row["stage"] == "native_master_frame")
        rows[first], rows[first + 1] = rows[first + 1], rows[first]
    elif mutation == "ignore_checksum":
        next(row for row in rows if row["stage"] == "native_sync_stopped")[
            "ignore_checksum_global"
        ] = 1
    elif mutation == "late_frame":
        rows.append(copy.deepcopy(next(row for row in rows if row["stage"] in N.FRAME_STAGES)))
    else:
        next(row for row in rows if row["stage"] == "native_research_frame")[
            "readability_queries"
        ] = True
    with pytest.raises(N.CaptureError):
        N.compare_jobs(job(tmp_path, "old"), job(tmp_path, "new", rows))


def test_replay_identity_mismatch(tmp_path):
    with pytest.raises(N.CaptureError, match="identity differs"):
        N.compare_jobs(
            job(tmp_path, "old"),
            job(tmp_path, "new", descriptor_changes={"recording_sha256": "c" * 64}),
        )


def test_source_shaped_legacy_snapshot_precedes_zero_update(tmp_path):
    rows = [row for row in events() if row["stage"] != "native_replay_bootstrap_policy"]
    index = next(i for i, row in enumerate(rows) if row["stage"] == "native_world_update_returned")
    rows.insert(
        index,
        dict(
            stage="native_world_update_returned",
            ordinal=1,
            world_time_ms=0,
            status=0,
            native_log_ms=0,
            file_position=112,
            clock_cycles=1,
        ),
    )
    rows[index + 1] = dict(
        stage="native_world_update_returned",
        ordinal=2,
        world_time_ms=18,
        status=0,
        native_log_ms=18,
        file_position=124,
        clock_cycles=2,
    )
    descriptor = dict(
        bootstrap_syncs=[
            dict(delta_ms=0, time_ms=0),
            dict(delta_ms=18, time_ms=18),
            dict(delta_ms=18, time_ms=36),
        ]
    )
    old = job(tmp_path, "old", rows, descriptor_changes=descriptor)
    new = job(tmp_path, "new", rows, descriptor_changes=descriptor)
    result = N.compare_jobs(old, new)
    assert result["left"]["boundaries"] == result["left"]["returned_updates"] == 2


@pytest.mark.parametrize("stage", ["native_unknown_frame", "native_unknown_catalog"])
def test_unknown_new_output_stream_requires_explicit_support(tmp_path, stage):
    rows = [dict(stage=stage), *events()]
    with pytest.raises(N.CaptureError, match="Unrecognized output stream"):
        N.compare_jobs(job(tmp_path, "old", rows), job(tmp_path, "new", rows))


def test_process_receipt_fallback_is_explicit_and_qualified(tmp_path):
    old, new = job(tmp_path, "old"), job(tmp_path, "new")
    for folder in (old, new):
        path = folder / "execution.json"
        receipt = json.loads(path.read_text())
        del receipt["all_input_pins_unchanged"]
        path.unlink()
        (folder / "native.process-exit.json").write_text(json.dumps(receipt))
    with pytest.raises(FileNotFoundError):
        N.compare_jobs(old, new)
    result = N.compare_jobs(old, new, allow_failed_process_receipt=True)
    assert result["left"]["process_receipt_only"] is True
    assert result["left"]["receipt_claims_source_input_stability"] is False
    assert result["conversion_accepted"] is False


@pytest.mark.parametrize("change", ["missing", "changed", "duplicate"])
def test_bootstrap_declaration_required_in_failed_capture_mode(tmp_path, change):
    rows = events()
    declaration = next(row for row in rows if row["stage"] == "native_replay_bootstrap_policy")
    if change == "missing":
        rows.remove(declaration)
    elif change == "changed":
        declaration["first_delta_ms"] = 19
    else:
        rows.insert(rows.index(declaration), copy.deepcopy(declaration))
    with pytest.raises(N.CaptureError):
        N.compare_jobs(job(tmp_path, "old", rows), job(tmp_path, "new", rows))


def test_descriptor_chronology_cannot_differ_even_for_same_recording(tmp_path):
    changed = copy.deepcopy(descriptor())
    changed["selected_content_mode"] = 2
    with pytest.raises(N.CaptureError, match="descriptor identity"):
        N.compare_jobs(job(tmp_path, "old"), job(tmp_path, "new", descriptor_changes=changed))


def test_game_terminal_status_cannot_be_followed_by_checksum_failure(tmp_path):
    rows = events()
    update = next(row for row in rows if row["stage"] == "native_world_update_returned")
    update["status"] = 1
    with pytest.raises(N.CaptureError, match="Early game terminal"):
        N.compare_jobs(job(tmp_path, "old", rows), job(tmp_path, "new", rows))


def test_final_game_terminal_status_cannot_be_followed_by_sync_stop(tmp_path):
    rows = events()
    first = next(i for i, row in enumerate(rows) if row["stage"] == "native_world_update_returned")
    stop = next(i for i, row in enumerate(rows) if row["stage"] == "native_sync_stopped")
    frame_template = rows[first + 1 : stop]
    assert len(frame_template) == len(N.FRAME_STAGES)
    extra = []
    for ordinal, clock, cursor in [(2, 36, 124), (3, 54, 136)]:
        extra.append(
            dict(
                stage="native_world_update_returned",
                ordinal=ordinal,
                world_time_ms=clock,
                recorded_delta_ms=18,
                status=int(ordinal == 3),
                native_log_ms=clock,
                file_position=cursor,
                clock_cycles=ordinal,
            )
        )
        for template in frame_template:
            extra.append(dict(copy.deepcopy(template), time_ms=clock))
    rows[stop:stop] = extra
    next(row for row in rows if row["stage"] == "native_sync_stopped")["world_time_ms"] = 54
    with pytest.raises(N.CaptureError, match="Checksum failure closure"):
        N.compare_jobs(job(tmp_path, "old", rows), job(tmp_path, "new", rows))


@pytest.mark.parametrize(
    "stage,field",
    [
        ("native_sync_stopped", "status"),
        ("native_sync_stopped", "world_time_ms"),
        ("native_prefix_sync", "error"),
    ],
)
def test_shared_float_closure_carriers_are_rejected(tmp_path, stage, field):
    rows = events()
    row = next(row for row in rows if row["stage"] == stage)
    row[field] = float(row[field])
    with pytest.raises(N.CaptureError, match="Checksum failure closure"):
        N.compare_jobs(job(tmp_path, "old", rows), job(tmp_path, "new", rows))
