"""Synthetic original and positive-first replay terminal fixtures."""

from vantage.native_bootstrap_policy import FRAME_STAGES, positive_plan


def descriptor(positive=True):
    deltas, times = (
        ([104, 104, 104], [104, 208, 312]) if positive else ([0, 104, 104], [0, 104, 208])
    )
    return dict(
        recording_sha256="a" * 64,
        inflated_save_sha256="b" * 64,
        recording_bytes=1000,
        inflated_save_bytes=2000,
        initial_clock_ms=0,
        body_clock_origin_ms=0,
        first_operation_kind="sync",
        first_operation_offset=100,
        body_offset=100,
        body_metadata_words=[5, 500, int(positive), 1, 1, 0, 0, 0],
        bootstrap_syncs=[
            dict(offset=100 + 24 * i, delta_ms=d, time_ms=t, payload_bytes=4)
            for i, (d, t) in enumerate(zip(deltas, times, strict=True))
        ],
        operation_counts=[["sync", 3], ["viewlock", 3], ["postgame", 1]],
        sync_deltas_ms=[[104, 3]] if positive else [[0, 1], [104, 2]],
        final_clock_ms=times[-1],
        postgame_offset=900,
        postgame_marker_end=904,
        postgame_remaining_bytes=96,
    )


def fixture(positive=True, ended=True):
    d = descriptor(positive)
    rows = [positive_plan(d).declaration()] if positive else []

    def frames(clock, kind):
        return [dict(stage=stage, time_ms=clock, kind=kind) for stage in FRAME_STAGES]

    rows += frames(0, "snapshot")
    for index, clock in enumerate([104, 208, 312] if positive else [0, 104, 208], 1):
        row = dict(
            stage="native_world_update_returned",
            ordinal=index,
            world_time_ms=clock,
            native_log_ms=clock,
            status=int(ended and index == 3),
            file_position={1: 124, 2: 148, 3: 904}[index],
            clock_cycles=index,
        )
        if positive or index > 1:
            row["recorded_delta_ms"] = 104
        rows.append(row)
        if positive or index > 1:
            rows += frames(clock, "delta")
    end = d["final_clock_ms"]
    rows += [
        dict(
            stage="owned_recording_postgame_close",
            marker=6,
            position=904,
            file_bytes=1000,
            unread_tail_bytes=96,
            source_final_clock=end,
            native_log_ms=end,
            native_file_fields_changed=False,
        ),
        dict(
            stage="native_replay_terminal_state",
            world_status=int(ended),
            world_time_ms=end,
            native_log_ms=end,
            replay_active=0,
            replay_file_present=False,
            owned_recording_closed=True,
            file_cursor=904,
            checksum_ignore_global=0,
            original_terminal_status_observed=ended,
            recording_eof_observed=not ended,
            recording_end_reason="world_terminal" if ended else "recording_eof",
        ),
        dict(
            stage="native_original_terminal_status_admitted"
            if ended
            else "native_recording_eof_admitted",
            returned_status=int(ended),
            world_status=int(ended),
            world_time_ms=end,
            completed_updates=3,
            native_replay_closed=True,
            checksum_ignore_global=0,
            host_native_status_write=False,
            game_ended=ended,
            recording_completed=True,
        ),
        dict(
            stage="native_simulation_prefix_complete",
            completed_world_updates=3,
            projected_frames=4 if positive else 3,
            world_time_ms=end,
            audio_requests=0,
            native_audio_initialized=False,
        ),
        dict(ok=True),
    ]
    return d, rows
