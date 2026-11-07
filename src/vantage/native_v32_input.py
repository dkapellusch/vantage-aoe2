"""Prepare replay-specific inputs for the experimental DE54800 V32 worker.

This module only parses files and emits input facts. It does not choose or run a
native image, select game assets, establish compatibility, or publish a replay.
A caller must independently bind a verified V32 worker and compatible assets.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from vantage.native_input import NativeInputError, describe_native_input
from vantage.replay_saved_world import load_replay_world


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise NativeInputError(code, message)


def prepare_v32_input(
    replay: Path,
    out: Path,
    *,
    config_template: Path,
    update_cap: int = 262144,
    source_root: Path | None = None,
) -> dict[Any, Any]:
    """Write a fresh V32 input bundle, without invoking native code.

    The caller supplies the checked, compatible configuration template and must
    validate its identity separately. A successfully prepared bundle is not a
    completed conversion and says nothing about multiplayer checksum fidelity.
    """
    replay = replay.resolve(strict=True)
    out = out.resolve()
    source_root = out if source_root is None else source_root.resolve()
    config_template = config_template.resolve(strict=True)
    _require(
        replay.suffix.lower() == ".aoe2record", "UNSUPPORTED_INPUT", "Expected an .aoe2record file"
    )
    descriptor = describe_native_input(replay)
    syncs = descriptor.bootstrap_syncs
    _require(
        len(syncs) == 3
        and descriptor.first_operation_kind == "sync"
        and syncs[0].offset == descriptor.body_offset == descriptor.first_operation_offset
        and descriptor.initial_clock_ms == descriptor.body_clock_origin_ms == 0,
        "UNSUPPORTED_BOOTSTRAP",
        "Requires an origin-zero replay with three initial sync boundaries",
    )
    first, second, third = syncs
    _require(
        0 <= first.delta_ms <= 1000
        and first.time_ms == first.delta_ms
        and first.payload_bytes == 4
        and 0 < second.delta_ms <= 1000
        and second.time_ms == first.time_ms + second.delta_ms
        and third.time_ms == second.time_ms + third.delta_ms > second.time_ms
        and first.offset < second.offset < third.offset
        and descriptor.final_clock_ms > third.time_ms,
        "UNSUPPORTED_BOOTSTRAP",
        "Initial sync clocks or positions are outside the V32 startup contract",
    )
    counts = dict(descriptor.operation_counts)
    _require(
        type(update_cap) is int and counts["sync"] + 2 <= update_cap <= 0xFFFFFFFF,
        "INVALID_UPDATE_CAP",
        "Update cap must cover the input syncs and fit a DWORD",
    )
    if first.delta_ms:
        _require(
            update_cap <= 0xFFFFFFFE, "INVALID_UPDATE_CAP", "Projection count must fit a DWORD"
        )
        _require(
            all(
                type(d) is int and 0 < d <= 1000 and type(n) is int and n > 0
                for d, n in descriptor.sync_deltas_ms
            )
            and sum(n for _, n in descriptor.sync_deltas_ms) == counts["sync"]
            and sum(d * n for d, n in descriptor.sync_deltas_ms) == descriptor.final_clock_ms,
            "UNSUPPORTED_SYNC_SEQUENCE",
            "Positive-first replays require positive bounded sync deltas throughout",
        )
    _require(
        len(descriptor.player_slots) == 8, "UNSUPPORTED_SLOT_CAPACITY", "V32 expects eight slots"
    )
    _require(descriptor.postgame_remaining_bytes >= 4, "INVALID_POSTGAME", "Final clock is missing")
    _require(
        descriptor.postgame_marker_end + descriptor.postgame_remaining_bytes
        == descriptor.recording_bytes,
        "INVALID_POSTGAME",
        "Postgame bounds do not match the recording",
    )
    _require(
        descriptor.map_tile_offset + descriptor.map_tile_bytes <= descriptor.inflated_save_bytes,
        "INVALID_MAP",
        "Map tiles exceed the saved world",
    )
    saved = load_replay_world(replay)
    _require(
        len(saved.raw) == descriptor.inflated_save_bytes
        and hashlib.sha256(saved.raw).hexdigest() == descriptor.inflated_save_sha256,
        "INPUT_CHANGED",
        "Saved-world bytes changed between input reads",
    )
    entities = [entity for group in descriptor.runtime_lists for entity in group.entities]
    _require(
        all(entity.owner == entity.saved_owner for entity in entities),
        "UNSUPPORTED_SAVED_OWNER",
        "Saved owner must match the runtime list owner",
    )
    _require(
        all(
            group.player_id == index // 3
            and group.list_index == index % 3
            and all(entity.owner == group.player_id for entity in group.entities)
            for index, group in enumerate(descriptor.runtime_lists)
        ),
        "INVALID_RUNTIME_PLAYER_BINDING",
        "Runtime list order does not match world players",
    )
    _require(
        len({entity.object_id for entity in entities}) == len(entities),
        "UNSUPPORTED_ENTITY_IDS",
        "Runtime entity IDs must be globally unique",
    )
    config = config_template.read_text()
    config, changed = re.subn(
        r'(static constexpr const char\* PREPARED_SAVED_SHA256 = ")[0-9a-f]{64}(";)',
        lambda match: match[1] + descriptor.inflated_save_sha256 + match[2],
        config,
    )
    _require(changed == 1, "INVALID_CONFIG_TEMPLATE", "Expected exactly one saved-world hash")
    values = {
        "INPUT_SAVE_BYTES": descriptor.inflated_save_bytes,
        "INPUT_SCENARIO_OFFSET": saved.scenario.offset,
        "INPUT_MAP_TILE_OFFSET": descriptor.map_tile_offset,
        "INPUT_MAP_TILE_COUNT": descriptor.map_width * descriptor.map_height,
        "INPUT_MAP_WIDTH": descriptor.map_width,
        "INPUT_MAP_HEIGHT": descriptor.map_height,
        "INPUT_WORLD_PLAYER_COUNT": descriptor.world_player_count,
        "INPUT_ENTITY_COUNT": len(entities),
        "INPUT_OPTIONS_OFFSET": descriptor.options_offset,
        "INPUT_OPTIONS_END": descriptor.options_end_offset,
        "INPUT_WORLD_HANDOFF": descriptor.world_handoff_offset,
        "INPUT_POPULATION_LIMIT": descriptor.population_limit,
        "INPUT_SLOT_COUNT": len(descriptor.player_slots),
        "INPUT_DATASET_FIELD_OFFSET": saved.prefix.header.options.fields[
            "dlc_options.dataset"
        ].offset,
        "INPUT_CLOCK_RATE_BITS": descriptor.initial_clock_rate_bits,
        "INPUT_RECORDING_BYTES": descriptor.recording_bytes,
        "INPUT_POSTGAME_MARKER_END": descriptor.postgame_marker_end,
        "INPUT_POSTGAME_REMAINING_BYTES": descriptor.postgame_remaining_bytes,
        "INPUT_FINAL_CLOCK_MS": descriptor.final_clock_ms,
        "INPUT_HEADER_END": descriptor.compressed_header_end,
        "INPUT_BODY_OFFSET": descriptor.body_offset,
        "INPUT_FIRST_SYNC_CURSOR": first.cursor_after_delta,
        "INPUT_SECOND_SYNC_OFFSET": second.offset,
        "INPUT_SECOND_SYNC_CURSOR": second.cursor_after_delta,
        "INPUT_SECOND_SYNC_DELTA": second.delta_ms,
        "INPUT_SECOND_SYNC_TIME": second.time_ms,
        "INPUT_THIRD_SYNC_OFFSET": third.offset,
        "INPUT_UPDATE_CAP": update_cap,
    }
    descriptor_json = json.loads(json.dumps(asdict(descriptor), default=str, allow_nan=False))
    canonical = json.dumps(descriptor_json, sort_keys=True, separators=(",", ":"), allow_nan=False)
    identity = hashlib.sha256(canonical.encode()).hexdigest()
    header = [
        "// Input facts only. Native engine-family/profile choices remain unchanged.",
        "#pragma once",
    ]
    for name, value in values.items():
        header.extend((f"#define {name} {value}", f'#define {name}_JSON "{value}"'))
    header.append(f'#define INPUT_RECORDING_SHA256 "{descriptor.recording_sha256}"')
    for name, entries in (
        ("INPUT_SLOT_HUMANITY", [slot.humanity for slot in descriptor.player_slots]),
        (
            "INPUT_SLOT_WORLD_INDEX",
            [slot.world_player_index & 0xFFFFFFFF for slot in descriptor.player_slots],
        ),
    ):
        header.append(
            "static constexpr DWORD " + name + "[] = {" + ",".join(f"{v}u" for v in entries) + "};"
        )
    header.extend(
        (
            'static_assert(INPUT_SLOT_COUNT == 8, "native protocol capacity is eight");',
            'static_assert(INPUT_POSTGAME_REMAINING_BYTES >= 4, "terminal clock must fit");',
            "static_assert(INPUT_POSTGAME_MARKER_END + INPUT_POSTGAME_REMAINING_BYTES "
            '== INPUT_RECORDING_BYTES, "terminal bounds");',
            f"#define INPUT_FIRST_SYNC_DELTA {first.delta_ms}",
            f'#define INPUT_FIRST_SYNC_DELTA_JSON "{first.delta_ms}"',
            f"#define INPUT_FIRST_SYNC_TIME {first.time_ms}",
            f'#define INPUT_FIRST_SYNC_TIME_JSON "{first.time_ms}"',
            f'#define INPUT_DESCRIPTOR_IDENTITY_SHA256 "{identity}"',
            "#define LOCALIZATION_EXPECTED_SOURCE_ROOT "
            + json.dumps("Z:" + str(source_root).replace("/", "\\") + "\\"),
        )
    )
    entity_lines = [
        "// Exact current-input effective runtime lists, before postload/ticks.",
        "struct ExpectedEntity { std::uint32_t id, owner, master, family, x, y, z, hp; };",
        "struct ExpectedEntityList { unsigned player, list, begin, count; };",
        "static constexpr ExpectedEntity EXPECTED_ENTITIES[] = {",
    ]
    for entity in entities:
        words = (
            entity.object_id,
            entity.owner,
            entity.master_id,
            entity.family,
            entity.x_bits,
            entity.y_bits,
            entity.z_bits,
            entity.hp_bits,
        )
        entity_lines.append(
            "    {" + ", ".join(f"0x{word & 0xFFFFFFFF:x}u" for word in words) + "},"
        )
    entity_lines.extend(("};", "static constexpr ExpectedEntityList EXPECTED_ENTITY_LISTS[] = {"))
    start = 0
    for group in descriptor.runtime_lists:
        entity_lines.append(
            f"    {{{group.player_id}, {group.list_index}, {start}, {len(group.entities)}}},"
        )
        start += len(group.entities)
    entity_lines.append("};")
    with replay.open("rb") as stream:
        recording_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    _require(
        replay.stat().st_size == descriptor.recording_bytes
        and recording_sha256 == descriptor.recording_sha256,
        "INPUT_CHANGED",
        "Recording changed during input preparation",
    )
    out.mkdir(parents=True, exist_ok=False)
    files = {
        "input-save.inflated.bin": saved.raw,
        "prepared_config.h": config.encode(),
        "native_input_profile.h": ("\n".join(header) + "\n").encode(),
        "entity_expectations.h": ("\n".join(entity_lines) + "\n").encode(),
        "descriptor.json": (json.dumps(descriptor_json, indent=2, allow_nan=False) + "\n").encode(),
    }
    for name, data in files.items():
        with (out / name).open("xb") as stream:
            stream.write(data)
    return {
        "recording_sha256": descriptor.recording_sha256,
        "descriptor_identity_sha256": identity,
        "first_sync_delta_ms": first.delta_ms,
        "output": str(out),
        "native_compatibility_verified": False,
    }
