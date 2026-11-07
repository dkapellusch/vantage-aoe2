"""Positive-first successor; inherited receipt/audio/close/terminal guards retained."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .native_bootstrap_policy import FRAME_STAGES, BoundaryOrder, Updates, exact, positive_plan
from .native_conversion import ConversionError, pin, require


def positive_terminal_evidence(
    capture: Path, receipt_path: Path, descriptor: dict[Any, Any]
) -> dict[Any, Any]:
    """Check source-pinned closure and actual update/projection cadence, not sync counts."""
    plan = positive_plan(descriptor)
    updates, boundaries = Updates(plan), BoundaryOrder()
    declaration_seen = False
    expected_cadence = hashlib.sha256(b"0,")
    receipt = json.loads(receipt_path.read_text())
    capture_pin = pin(capture)
    require(
        receipt.get("receipt_kind") == "ordinary_owned_subprocess"
        and type(receipt.get("exit_code")) is int
        and receipt["exit_code"] == 0
        and receipt.get("timed_out") is False
        and receipt.get("cancelled") is False
        and receipt.get("all_input_pins_unchanged") is True
        and receipt.get("stdout_sha256") == capture_pin["sha256"],
        "Native receipt rejected",
    )
    stages = FRAME_STAGES
    cadence = {name: hashlib.sha256() for name in (*stages, "updates")}
    counts = dict.fromkeys(cadence, 0)
    selected = {}
    audio_bindings, audio_requests, audio_after_updates = [], [], []
    last_update: Any = None
    ok = 0
    recovered_prefixes = []
    # Exact bounded grammar already used by reviewed v8/v11 capture readers.
    resign_prefix = re.compile(r"^(?:[0-9]+ ResignPlayer)+")
    for number, raw in enumerate(capture.open(), 1):
        match = resign_prefix.match(raw)
        line = raw
        if match:
            recovered_prefixes.append(dict(line=number, prefix=match[0], characters=match.end()))
            line = raw[match.end() :]
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ConversionError(f"Malformed native output at line {number}") from error
        require(isinstance(event, dict), f"Non-object native event at line {number}")
        require("error" not in event and event.get("ok") is not False, "Native failure event")
        stage = event.get("stage")
        if stage == "native_replay_bootstrap_policy":
            require(
                not declaration_seen
                and boundaries.boundaries == 0
                and not boundaries.pending
                and updates.count == 0,
                "Duplicate or late bootstrap policy",
            )
            require(exact(event, plan.declaration()), "Descriptor-bound bootstrap policy differs")
            declaration_seen = True
        if stage in (*stages, "native_world_update_returned"):
            require(declaration_seen, "Descriptor-bound positive-first policy is absent")
        if stage == "headless_audio_adapter_bound":
            audio_bindings.append(event)
        elif stage == "headless_audio_request":
            audio_requests.append(event)
        elif stage == "headless_audio_state_after_update":
            audio_after_updates.append(event)
        if event.get("ok") is True:
            ok += 1
        if stage == "native_world_update_returned":
            boundaries.before_update(updates.count)
            updates.accept(event)
            expected_cadence.update(f"{updates.clock},".encode())
            ordinal, clock = event["ordinal"], event["world_time_ms"]
            require(
                ordinal == counts["updates"] + 1
                and type(clock) is int
                and 0 <= clock <= descriptor["final_clock_ms"]
                and (last_update is None or clock >= last_update["world_time_ms"])
                and event["status"] in (0, 1),
                "Native update sequence rejected",
            )
            if last_update is not None:
                require(last_update["status"] == 0, "Updates continued after game terminal")
            last_update = event
            counts["updates"] += 1
            cadence["updates"].update(f"{clock},".encode())
        elif stage in stages:
            boundaries.accept(event, updates.count, updates.clock)
            counts[stage] += 1
            cadence[stage].update(f"{event['time_ms']},".encode())
        if stage in (
            "native_recording_eof_admitted",
            "native_original_terminal_status_admitted",
            "native_replay_terminal_state",
            "native_simulation_prefix_complete",
            "owned_recording_postgame_close",
        ):
            require(stage not in selected, f"Duplicate terminal event: {stage}")
            selected[stage] = event
    updates.finish()
    boundaries.finish(updates.count)
    count, end = counts["updates"], descriptor["final_clock_ms"]
    require(declaration_seen, "Descriptor-bound positive-first policy is absent")
    require(
        count > 0 and last_update is not None and last_update["world_time_ms"] == end and ok == 1,
        "Native completion is absent",
    )
    require(
        all(
            counts[name] == count + 1 and cadence[name].digest() == expected_cadence.digest()
            for name in stages
        ),
        "Native projection cadence differs from actual updates",
    )
    completion = selected.get("native_simulation_prefix_complete", {})
    require(
        completion.get("completed_world_updates") == count
        and completion.get("world_time_ms") == end
        and completion.get("projected_frames") == count + 1
        and type(completion.get("audio_requests")) is int
        and 0 <= completion["audio_requests"] <= 0xFFFFFFFF
        and completion.get("native_audio_initialized") is False,
        "Completion contract rejected",
    )
    if completion["audio_requests"]:
        # The source-bound adapter counts disabled requests and returns no playing
        # ID. Only its first sixteen requests are logged. A zero counter retains
        # the existing fixture contract without requiring diagnostic events.
        require(
            len(audio_bindings) == 1 and len(audio_after_updates) == 1,
            "Disabled audio adapter observations rejected",
        )
        binding, after_update = audio_bindings[0], audio_after_updates[0]
        require(
            binding
            == dict(
                stage="headless_audio_adapter_bound",
                native_entry="140b277d0",
                playing_id_on_disabled_output=0,
                native_audio_initialized=False,
                native_audio_success_claim=False,
            )
            and type(binding.get("playing_id_on_disabled_output")) is int
            and binding.get("native_audio_initialized") is False
            and binding.get("native_audio_success_claim") is False
            and after_update.get("native_audio_initialized") is False
            and type(after_update.get("requests")) is int
            and 0 <= after_update["requests"] <= completion["audio_requests"]
            and len(audio_requests) == min(completion["audio_requests"], 16),
            "Disabled audio adapter evidence rejected",
        )
        for ordinal, request in enumerate(audio_requests, 1):
            require(
                type(request.get("ordinal")) is int
                and request["ordinal"] == ordinal
                and request.get("backend") == "disabled"
                and type(request.get("playing_id")) is int
                and request["playing_id"] == 0,
                "Disabled audio request evidence rejected",
            )
    close = selected.get("owned_recording_postgame_close", {})
    require(
        close.get("marker") == 6
        and close.get("position") == descriptor["postgame_marker_end"]
        and close.get("file_bytes") == descriptor["recording_bytes"]
        and close.get("unread_tail_bytes") == descriptor["postgame_remaining_bytes"]
        and close.get("source_final_clock") == end
        and close.get("native_log_ms") == end
        and close.get("native_file_fields_changed") is False,
        "Original recording close rejected",
    )
    terminal = selected.get("native_replay_terminal_state", {})
    ended = terminal.get("world_status") == 1
    require(
        type(terminal.get("world_status")) is int
        and terminal["world_status"] in (0, 1)
        and terminal.get("world_time_ms") == end
        and terminal.get("native_log_ms") == end
        and terminal.get("replay_active") == 0
        and terminal.get("replay_file_present") is False
        and terminal.get("owned_recording_closed") is True
        and terminal.get("file_cursor") == descriptor["postgame_marker_end"]
        and terminal.get("checksum_ignore_global") == 0
        and terminal.get("original_terminal_status_observed") is ended
        and terminal.get("recording_eof_observed") is (not ended)
        and terminal.get("recording_end_reason")
        == ("world_terminal" if ended else "recording_eof"),
        "Actual native terminal state rejected",
    )
    name = "native_original_terminal_status_admitted" if ended else "native_recording_eof_admitted"
    other = "native_recording_eof_admitted" if ended else "native_original_terminal_status_admitted"
    admission = selected.get(name, {})
    require(
        other not in selected
        and admission.get("returned_status") == int(ended)
        and last_update["status"] == int(ended)
        and admission.get("world_status") == int(ended)
        and admission.get("world_time_ms") == end
        and admission.get("completed_updates") == count
        and admission.get("native_replay_closed") is True
        and admission.get("checksum_ignore_global") == 0
        and admission.get("host_native_status_write") is False,
        "Source closure admission rejected",
    )
    if not ended:
        require(
            admission.get("game_ended") is False and admission.get("recording_completed") is True,
            "EOF was confused with game end",
        )
    return dict(
        capture=capture_pin,
        terminal_receipt=pin(receipt_path),
        expected_frames=count + 1,
        actual_native_updates=count,
        bootstrap_policy=plan.declaration(),
        initial_snapshot_is_returned_update=False,
        expected_end_ms=end,
        game_ended=ended,
        game_end_inferred_from_EOF=False,
        recording_end_reason="native_game_end" if ended else "recording_eof",
        original_EOF_event=admission if not ended else None,
        original_terminal_event=admission,
        original_capture_completion=completion,
        native_terminal_state=terminal,
        original_close_event=close,
        source_guard_qualification="refs0/byte80/registry ownership checked by pinned host; "
        "closure event is not an independent native field dump",
        recovered_known_resign_prefixes=recovered_prefixes,
    )
