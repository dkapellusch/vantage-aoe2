"""Private genuine-SDK terminal admission. Never launch a worker or encode a Frame.

Callers must bind this source and the actual candidate host/profile before use.
Namespace/provider isolation is a source-bound declaration, not proven by JSON.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vantage.native_bootstrap_policy import (
    FRAME_STAGES,
    BoundaryOrder,
    Updates,
    exact,
    is_positive_first,
    positive_plan,
)
from vantage.native_conversion import ConversionError, pin, require

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import TYPE_CHECKING


SDK_STARTUP = dict(
    stage="native_offline_audio_initialized",
    memory_manager_ready=True,
    stream_manager_ready=True,
    sdk_initialized=True,
    offline_mode=1,
    bank_ids=[1355168291, 232745270],
    bank_results=[1, 1],
    bank_copy=True,
    router_original=True,
    physical_audio_provider_policy="private-linux-namespace-v1",
    audio_threads=[0, 1],
)
SDK_COMPLETION = dict(
    native_audio_initialized=True,
    offline_audio_mode=1,
    native_audio_bank_ids=[1355168291, 232745270],
    native_audio_bank_count=2,
    native_audio_router_original=True,
)
DISABLED_AUDIO_STAGES = frozenset(
    (
        "headless_audio_adapter_bound",
        "headless_audio_request",
        "headless_audio_state_after_update",
    )
)


def sdk_completion_matches(event: Any) -> bool:
    # Other completion fields retain their original gates or diagnostics.
    # Unknown audio configuration cannot silently become an equivalent mode.
    expected_keys = set(SDK_COMPLETION)
    actual_keys = {key for key in event if key.startswith(("native_audio_", "offline_audio_"))}
    return (
        actual_keys == expected_keys
        and "audio_requests" not in event
        and all(key in event and exact(event[key], value) for key, value in SDK_COMPLETION.items())
    )


def _legacy_terminal_evidence(
    capture: Path, receipt_path: Path, descriptor: dict[Any, Any], *, expected_ignore: int = 0
) -> dict[Any, Any]:
    """Check source-pinned closure and actual update/projection cadence, not sync counts."""
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
    stages = (
        "native_entity_frame",
        "native_world_frame",
        "native_player_frame",
        "native_entity_presentation_frame",
    )
    cadence = {name: hashlib.sha256() for name in (*stages, "updates")}
    counts = dict.fromkeys(cadence, 0)
    selected = {}
    audio_startups: list[Any] = []
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
        if stage == "native_offline_audio_initialized":
            require(
                not audio_startups and all(value == 0 for value in counts.values()),
                "Duplicate or late private SDK startup",
            )
            require(exact(event, SDK_STARTUP), "Private SDK startup contract rejected")
            audio_startups.append(event)
        elif stage in DISABLED_AUDIO_STAGES:
            raise ConversionError("Disabled adapter event in original SDK capture")
        if event.get("ok") is True:
            ok += 1
        if stage == "native_world_update_returned":
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
    count, end = counts["updates"], descriptor["final_clock_ms"]
    require(
        count > 0 and last_update is not None and last_update["world_time_ms"] == end and ok == 1,
        "Native completion is absent",
    )
    require(
        all(
            counts[name] == count and cadence[name].digest() == cadence["updates"].digest()
            for name in stages
        ),
        "Native projection cadence differs from actual updates",
    )
    completion = selected.get("native_simulation_prefix_complete", {})
    require(
        completion.get("completed_world_updates") == count
        and completion.get("world_time_ms") == end
        and completion.get("projected_frames") == count
        and sdk_completion_matches(completion),
        "Completion contract rejected",
    )
    require(len(audio_startups) == 1, "Private SDK startup is absent")
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
        and terminal.get("checksum_ignore_global") == expected_ignore
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
        and admission.get("checksum_ignore_global") == expected_ignore
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
        expected_frames=count,
        expected_end_ms=end,
        game_ended=ended,
        game_end_inferred_from_EOF=False,
        recording_end_reason="native_game_end" if ended else "recording_eof",
        original_EOF_event=admission if not ended else None,
        original_terminal_event=admission,
        original_capture_completion=completion,
        original_sdk_audio_startup=audio_startups[0],
        native_terminal_state=terminal,
        original_close_event=close,
        source_guard_qualification="refs0/byte80/registry ownership checked by pinned host; "
        "closure event is not an independent native field dump",
        recovered_known_resign_prefixes=recovered_prefixes,
    )


def _positive_terminal_evidence(
    capture: Path, receipt_path: Path, descriptor: dict[Any, Any], *, expected_ignore: int = 0
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
    audio_startups: list[Any] = []
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
        if stage == "native_offline_audio_initialized":
            require(
                not audio_startups and all(value == 0 for value in counts.values()),
                "Duplicate or late private SDK startup",
            )
            require(exact(event, SDK_STARTUP), "Private SDK startup contract rejected")
            audio_startups.append(event)
        elif stage in DISABLED_AUDIO_STAGES:
            raise ConversionError("Disabled adapter event in original SDK capture")
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
        and sdk_completion_matches(completion),
        "Completion contract rejected",
    )
    require(len(audio_startups) == 1, "Private SDK startup is absent")
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
        and terminal.get("checksum_ignore_global") == expected_ignore
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
        and admission.get("checksum_ignore_global") == expected_ignore
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
        original_sdk_audio_startup=audio_startups[0],
        native_terminal_state=terminal,
        original_close_event=close,
        source_guard_qualification="refs0/byte80/registry ownership checked by pinned host; "
        "closure event is not an independent native field dump",
        recovered_known_resign_prefixes=recovered_prefixes,
    )


def _bound(
    check: Callable[..., Any],
    capture: Path,
    receipt_path: Path,
    descriptor: dict[Any, Any],
    *,
    approximate_checksums: bool = False,
) -> dict[Any, Any]:
    capture, receipt_path = Path(capture), Path(receipt_path)
    root = Path(__file__).resolve().parents[2]
    sources = [
        Path(__file__).resolve(),
        root / "src/vantage/__init__.py",
        root / "src/vantage/native_conversion.py",
        root / "src/vantage/native_bootstrap_policy.py",
    ]
    identities = [pin(path) for path in (*sources, capture, receipt_path)]
    descriptor_bytes = json.dumps(
        descriptor, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    # Strict runs require the game's checksum-ignore byte to be 0; approximate runs, exactly 1.
    result: dict[Any, Any] = check(
        capture, receipt_path, descriptor, expected_ignore=int(approximate_checksums)
    )
    require(
        all(pin(Path(row["path"])) == row for row in identities),
        "Private SDK admission inputs changed during validation",
    )
    require(
        json.dumps(descriptor, sort_keys=True, separators=(",", ":"), allow_nan=False)
        == descriptor_bytes,
        "Descriptor changed during private SDK admission",
    )
    if approximate_checksums:
        result["approximate_checksums"] = True
    result["private_sdk_audio_admission"] = dict(
        version=1,
        source_pins=identities[:-2],
        configuration_fields_compared_to_disabled_baseline=False,
        physical_audio_provider_policy_is_source_bound_declaration=True,
        full_simulation_parity_claimed=False,
    )
    return result


def terminal_evidence(
    capture: Path,
    receipt_path: Path,
    descriptor: dict[Any, Any],
    *,
    approximate_checksums: bool = False,
) -> dict[Any, Any]:
    """Original legacy cadence, SDK-specific audio contract, native0 success only."""
    return _bound(
        _legacy_terminal_evidence,
        capture,
        receipt_path,
        descriptor,
        approximate_checksums=approximate_checksums,
    )


def positive_terminal_evidence(
    capture: Path,
    receipt_path: Path,
    descriptor: dict[Any, Any],
    *,
    approximate_checksums: bool = False,
) -> dict[Any, Any]:
    """Descriptor-bound positive cadence and strict original SDK configuration."""
    return _bound(
        _positive_terminal_evidence,
        capture,
        receipt_path,
        descriptor,
        approximate_checksums=approximate_checksums,
    )


def terminal_evidence_for_input(
    capture: Path,
    receipt_path: Path,
    descriptor: dict[Any, Any],
    *,
    approximate_checksums: bool = False,
) -> dict[Any, Any]:
    """Private drop-in API for the backend's completed-capture admission call."""
    try:
        positive = is_positive_first(descriptor)
    except ValueError as error:
        raise ConversionError(str(error)) from error
    try:
        return (positive_terminal_evidence if positive else terminal_evidence)(
            capture, receipt_path, descriptor, approximate_checksums=approximate_checksums
        )
    except ValueError as error:
        raise ConversionError(str(error)) from error
