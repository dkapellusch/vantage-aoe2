"""Silent completion gate regression; synthetic JSON only, no target or encoder."""

import pytest
from test_native_conversion import capture_events, synthetic_capture

from vantage import native_conversion as N

UINT32_MAX = (1 << 32) - 1


def completion(events):
    return next(e for e in events if e.get("stage") == "native_simulation_prefix_complete")


def audio_capture_events(*, ended=False, requests=0):
    events = capture_events(ended=ended)
    completion(events)["audio_requests"] = requests
    # Keep zero-request historical fixtures unmodified. Nonzero requests need
    # the actual adapter's bounded diagnostics, not an audio success assertion.
    if requests:
        events.insert(
            0,
            dict(
                stage="headless_audio_adapter_bound",
                native_entry="140b277d0",
                playing_id_on_disabled_output=0,
                native_audio_initialized=False,
                native_audio_success_claim=False,
            ),
        )
        position = next(
            i for i, e in enumerate(events) if e.get("stage") == "native_simulation_prefix_complete"
        )
        evidence = [
            dict(
                stage="headless_audio_request",
                ordinal=i,
                object=123,
                category=0,
                flags=0,
                playing_id=0,
                backend="disabled",
                name_hex="",
            )
            for i in range(1, min(requests, 16) + 1)
        ]
        evidence.append(
            dict(
                stage="headless_audio_state_after_update",
                requests=min(requests, 2),
                native_audio_initialized=False,
            )
        )
        events[position:position] = evidence
    return events


@pytest.mark.parametrize("ended", [False, True], ids=["eof", "game-end"])
@pytest.mark.parametrize("requests", [0, 1, 77, UINT32_MAX])
def test_disabled_audio_requests_do_not_prevent_completed_silent_replay(tmp_path, ended, requests):
    events = audio_capture_events(ended=ended, requests=requests)
    result = N.terminal_evidence(*synthetic_capture(tmp_path, events=events))
    assert result["expected_frames"] == 3
    assert result["expected_end_ms"] == 31
    assert result["game_ended"] is ended
    assert result["game_end_inferred_from_EOF"] is False
    assert result["recording_end_reason"] == ("native_game_end" if ended else "recording_eof")
    assert result["original_capture_completion"]["audio_requests"] == requests
    assert result["original_capture_completion"]["native_audio_initialized"] is False


@pytest.mark.parametrize("ended", [False, True], ids=["eof", "game-end"])
@pytest.mark.parametrize("bad_count", [-1, UINT32_MAX + 1, False, True, 0.0, 77.0, "77", None])
def test_audio_request_counter_requires_unsigned_integer(tmp_path, ended, bad_count):
    events = capture_events(ended=ended)
    completion(events)["audio_requests"] = bad_count
    with pytest.raises(N.ConversionError, match="Completion contract rejected"):
        N.terminal_evidence(*synthetic_capture(tmp_path, events=events))


@pytest.mark.parametrize("ended", [False, True], ids=["eof", "game-end"])
def test_missing_audio_request_counter_is_rejected(tmp_path, ended):
    events = capture_events(ended=ended)
    del completion(events)["audio_requests"]
    with pytest.raises(N.ConversionError, match="Completion contract rejected"):
        N.terminal_evidence(*synthetic_capture(tmp_path, events=events))


@pytest.mark.parametrize("ended", [False, True], ids=["eof", "game-end"])
@pytest.mark.parametrize("initialized", [True, 0, 1, None, "false"])
def test_audio_initialization_must_be_exact_false(tmp_path, ended, initialized):
    events = capture_events(ended=ended)
    completion(events)["native_audio_initialized"] = initialized
    with pytest.raises(N.ConversionError, match="Completion contract rejected"):
        N.terminal_evidence(*synthetic_capture(tmp_path, events=events))


@pytest.mark.parametrize("ended", [False, True], ids=["eof", "game-end"])
def test_missing_audio_initialization_is_rejected(tmp_path, ended):
    events = capture_events(ended=ended)
    del completion(events)["native_audio_initialized"]
    with pytest.raises(N.ConversionError, match="Completion contract rejected"):
        N.terminal_evidence(*synthetic_capture(tmp_path, events=events))


@pytest.mark.parametrize("ended", [False, True], ids=["eof", "game-end"])
@pytest.mark.parametrize("problem", ["cadence", "receipt", "close", "ignore", "status", "ok"])
def test_nonzero_disabled_audio_count_does_not_relax_other_completion_guards(
    tmp_path, ended, problem
):
    events = audio_capture_events(ended=ended, requests=77)
    receipt_changes = None
    if problem == "cadence":
        next(e for e in events if e.get("stage") == "native_player_frame")["time_ms"] = 1
    elif problem == "receipt":
        receipt_changes = {"exit_code": 1}
    elif problem == "close":
        next(e for e in events if e.get("stage") == "owned_recording_postgame_close")[
            "position"
        ] = 99
    elif problem == "ignore":
        next(e for e in events if e.get("stage") == "native_replay_terminal_state")[
            "checksum_ignore_global"
        ] = 1
    elif problem == "status":
        next(e for e in reversed(events) if e.get("stage") == "native_world_update_returned")[
            "status"
        ] = int(not ended)
    else:
        events.pop()
    with pytest.raises(N.ConversionError):
        N.terminal_evidence(
            *synthetic_capture(tmp_path, events=events, receipt_changes=receipt_changes)
        )


@pytest.mark.parametrize("ended", [False, True], ids=["eof", "game-end"])
@pytest.mark.parametrize(
    "problem",
    [
        "missing-bound",
        "duplicate-bound",
        "bound-entry",
        "bound-init",
        "bound-claim",
        "bound-id",
        "missing-state",
        "duplicate-state",
        "state-init",
        "state-negative",
        "state-overflow",
        "state-bool",
        "missing-request",
        "duplicate-ordinal",
        "reordered-ordinal",
        "request-backend",
        "request-id",
        "boolean-ordinal",
    ],
)
def test_nonzero_count_requires_disabled_adapter_evidence(tmp_path, ended, problem):
    events = audio_capture_events(ended=ended, requests=77)
    bound = next(e for e in events if e.get("stage") == "headless_audio_adapter_bound")
    state = next(e for e in events if e.get("stage") == "headless_audio_state_after_update")
    requests = [e for e in events if e.get("stage") == "headless_audio_request"]
    if problem == "missing-bound":
        events.remove(bound)
    elif problem == "duplicate-bound":
        events.append(bound.copy())
    elif problem.startswith("bound-"):
        field, value = {
            "bound-entry": ("native_entry", "140b277d1"),
            "bound-init": ("native_audio_initialized", True),
            "bound-claim": ("native_audio_success_claim", True),
            "bound-id": ("playing_id_on_disabled_output", 1),
        }[problem]
        bound[field] = value
    elif problem == "missing-state":
        events.remove(state)
    elif problem == "duplicate-state":
        events.append(state.copy())
    elif problem.startswith("state-"):
        field, value = {
            "state-init": ("native_audio_initialized", True),
            "state-negative": ("requests", -1),
            "state-overflow": ("requests", 78),
            "state-bool": ("requests", False),
        }[problem]
        state[field] = value
    elif problem == "missing-request":
        events.remove(requests[-1])
    elif problem == "duplicate-ordinal":
        requests[-1]["ordinal"] = 15
    elif problem == "reordered-ordinal":
        requests[0]["ordinal"], requests[1]["ordinal"] = 2, 1
    elif problem == "request-backend":
        requests[0]["backend"] = "sdk"
    elif problem == "request-id":
        requests[0]["playing_id"] = 1
    else:
        requests[0]["ordinal"] = True
    with pytest.raises(N.ConversionError):
        N.terminal_evidence(*synthetic_capture(tmp_path, events=events))
