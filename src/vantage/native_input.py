"""Input-derived facts for the experimental DE54800 CPU replay host.

This module parses ordinary files only. A descriptor is not evidence that the
native worker supports the recording: binary/asset identity, reached native
paths, checksums and terminal cleanup still require separate verification.
Only complete, initial-clock-zero, base Random Map inputs are described here.
"""

from __future__ import annotations

import hashlib
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from vantage.replay_binary import SaveDecodeError
from vantage.replay_object_order import restore_runtime_object_lists
from vantage.replay_saved_world import SavedReplayWorld, load_replay_world
from vantage.replay_stream import ReplayStreamError, iter_replay_operations


class NativeInputError(ValueError):
    """An unsupported input or failed structural check, never a native result."""

    def __init__(
        self, code: str, message: str, *, offset: int | None = None, space: str = "file"
    ) -> None:
        self.code = code
        self.offset = offset
        self.offset_space = space
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class NativePlayerSlot:
    slot: int
    humanity: int
    world_player_index: int
    scenario_player_index: int
    civilization_mode_id: int
    civilization_id: int


@dataclass(frozen=True, slots=True)
class NativeInitialEntity:
    """Exact saved geometry, before native postload changes or simulation.

    Native list ownership comes from the outer player. Keep the independently
    saved owner too; neither is silently substituted for the other.
    """

    object_id: int
    owner: int
    saved_owner: int
    master_id: int
    family: int
    x_bits: int
    y_bits: int
    z_bits: int
    hp_bits: int


@dataclass(frozen=True, slots=True)
class NativeInitialList:
    player_id: int
    list_index: int  # Native Player+30/+38/+40: ordinary, sleeping, dopple.
    entities: tuple[NativeInitialEntity, ...]


@dataclass(frozen=True, slots=True)
class NativeSyncBoundary:
    offset: int
    delta_ms: int
    time_ms: int
    payload_bytes: int  # Four delta bytes plus an optional 360-byte checksum block.

    @property
    def cursor_after_delta(self) -> int:
        return self.offset + 8  # Operation word and delta; checksum remains unread.

    @property
    def checksum_offset(self) -> int | None:
        return self.cursor_after_delta if self.payload_bytes > 4 else None


@dataclass(frozen=True, slots=True)
class NativeReplayInput:
    path: Path
    recording_sha256: str
    recording_bytes: int
    inflated_save_sha256: str
    inflated_save_bytes: int
    build: int
    save_version: int
    options_version: int
    options_offset: int
    options_end_offset: int
    world_handoff_offset: int
    compressed_header_end: int
    body_offset: int
    body_metadata_words: tuple[int, ...]
    initial_clock_ms: int
    initial_clock_rate_bits: int
    dataset_id: int
    game_mode: int
    selected_content_mode: int
    map_width: int
    map_height: int
    map_tile_offset: int
    map_tile_bytes: int
    map_tile_sha256: str
    population_limit: int
    world_player_count: int
    local_player_index: int
    player_slots: tuple[NativePlayerSlot, ...]
    wire_lists: tuple[NativeInitialList, ...]
    runtime_lists: tuple[NativeInitialList, ...]
    operation_counts: tuple[tuple[str, int], ...]
    sync_deltas_ms: tuple[tuple[int, int], ...]
    body_clock_origin_ms: int
    bootstrap_syncs: tuple[NativeSyncBoundary, ...]
    checksum_sync_count: int
    first_operation_kind: str
    first_operation_offset: int
    postgame_offset: int
    postgame_marker_end: int
    postgame_remaining_bytes: int  # Includes the final-clock word after marker6.
    final_clock_ms: int
    native_compatibility_verified: Literal[False] = field(default=False, init=False)


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _profile(saved: SavedReplayWorld) -> None:
    options = saved.prefix.header.options
    selectors = (
        options.dlc.dataset_id,
        options.fields["mGameMode"].value,
        options.fields["mSelectedContentMode"].value,
    )
    if selectors != (1, 0, 2):
        raise NativeInputError(
            "UNSUPPORTED_MODE",
            f"unproven native dataset/game/content selectors {selectors}",
            offset=options.section.offset,
            space="inflated_save",
        )
    fields = options.fields
    if (
        fields["mModdedDatasetWorkshopId"].value
        or fields["mModdedDatasetCrc"].value
        or fields["mModdedDatasetTitle"].value
        or fields["mDatasetIsOfficial"].value != 1
    ):
        raise NativeInputError("UNSUPPORTED_DATASET", "modded simulation dataset is unproven")
    if saved.prefix.world.prefix.clock_fields[0x18] != 0:
        raise NativeInputError("UNSUPPORTED_RESUME", "nonzero saved initial clock is unproven")


def _lists(saved: SavedReplayWorld, *, runtime: bool) -> tuple[NativeInitialList, ...]:
    result = []
    for player in saved.prefix.world.players:
        player_id = player.header.player_id
        if player_id is None:
            raise NativeInputError("INVALID_PLAYER_BINDING", "missing outer World player ID")
        lists = player.object_lists
        if runtime:
            restored = restore_runtime_object_lists(lists)
            groups = restored.ordinary, restored.sleeping, restored.dopple
        else:
            groups = lists.ordinary.objects, lists.sleeping.objects, lists.dopple.objects
        for index, objects in enumerate(groups):
            entities = []
            for obj in objects:
                # replay_objects reads hp at wire+10 and XYZ at wire+23. Read
                # raw uint32 words here to preserve IEEE-754 bits, including NaNs.
                hp_bits = struct.unpack_from("<I", obj.raw, 10)[0]
                x_bits, y_bits, z_bits = struct.unpack_from("<3I", obj.raw, 23)
                entities.append(
                    NativeInitialEntity(
                        obj.object_id,
                        player_id,
                        obj.owner,
                        obj.master_id,
                        obj.type_group,
                        x_bits,
                        y_bits,
                        z_bits,
                        hp_bits,
                    )
                )
            result.append(NativeInitialList(player_id, index, tuple(entities)))
    return tuple(result)


def describe_native_input(
    path: str | Path,
    *,
    max_recording_bytes: int = 512 << 20,
    max_inflated_bytes: int = 256 << 20,
    max_compressed_bytes: int = 64 << 20,
    max_operations: int = 16_000_000,
) -> NativeReplayInput:
    """Derive an immutable plan without launching any game or worker.

    Unsupported chapters/resumed games/modes/partial files are rejected. A
    successful return certifies these file facts only, not native compatibility.
    Inputs are hashed before/after parsing so changed files cannot publish a plan.
    """
    limits = (max_recording_bytes, max_inflated_bytes, max_compressed_bytes, max_operations)
    if any(type(value) is not int or value <= 0 for value in limits):
        raise ValueError("native input limits must be positive integers")
    source = Path(path).expanduser().resolve(strict=True)
    before = _identity(source)
    size = before[2]
    if size > max_recording_bytes:
        raise NativeInputError("INPUT_LIMIT", "recording exceeds configured byte limit")
    source_sha = _sha(source)
    with source.open("rb") as stream:
        envelope = stream.read(8)
    if len(envelope) != 8:
        raise NativeInputError("INVALID_ENVELOPE", "truncated replay envelope", offset=0)
    header_end, chapter = struct.unpack("<II", envelope)
    if not 8 < header_end <= size - 32:
        raise NativeInputError("INVALID_ENVELOPE", "invalid compressed header end", offset=0)
    if chapter:
        raise NativeInputError("UNSUPPORTED_CHAPTER", "saved chapters are unproven", offset=4)
    with source.open("rb") as stream:
        stream.seek(header_end)
        raw_metadata = stream.read(32)
    if len(raw_metadata) != 32:
        raise NativeInputError("INVALID_BODY", "truncated body metadata", offset=header_end)
    body_metadata = struct.unpack("<8I", raw_metadata)
    counts: Counter[str] = Counter()
    deltas: Counter[int] = Counter()
    bootstrap_syncs: list[Any] = []
    checksum_sync_count = 0
    first = postgame = None
    clock_origin = None
    last_sync_clock = 0
    try:
        for ordinal, operation in enumerate(iter_replay_operations(source), 1):
            if ordinal > max_operations:
                raise NativeInputError("INPUT_LIMIT", "operation count exceeds configured limit")
            if first is None:
                first = operation
            counts[operation.kind] += 1
            if operation.kind == "sync":
                delta = struct.unpack_from("<I", operation.payload)[0]
                deltas[delta] += 1
                if clock_origin is None:
                    clock_origin = operation.time_ms - delta
                last_sync_clock = operation.time_ms
                if len(bootstrap_syncs) < 3:
                    bootstrap_syncs.append(
                        NativeSyncBoundary(
                            operation.offset, delta, operation.time_ms, len(operation.payload)
                        )
                    )
                checksum_sync_count += len(operation.payload) > 4
            elif operation.kind == "postgame":
                postgame = operation
    except ReplayStreamError as error:
        raise NativeInputError("INVALID_BODY", str(error), offset=error.offset) from error
    if postgame is None:
        raise NativeInputError("PARTIAL_INPUT", "recording has no terminal postgame record")
    if clock_origin != 0:
        raise NativeInputError(
            "UNSUPPORTED_RESUME", "nonzero or absent body sync origin is unproven"
        )
    if postgame.time_ms < last_sync_clock:
        raise NativeInputError("INVALID_BODY", "postgame clock precedes the final sync")
    try:
        saved = load_replay_world(
            source,
            max_inflated_bytes=max_inflated_bytes,
            max_compressed_bytes=max_compressed_bytes,
        )
    except SaveDecodeError as error:
        raise NativeInputError(
            "UNSUPPORTED_SAVE_PROFILE", str(error), offset=error.offset, space="inflated_save"
        ) from error
    except ReplayStreamError as error:
        raise NativeInputError("INVALID_SAVED_WORLD", str(error), offset=error.offset) from error
    _profile(saved)
    header, world = saved.prefix.header, saved.prefix.world
    options = header.options
    slots = tuple(
        NativePlayerSlot(
            p.slot,
            p.humanity,
            p.world_player_index,
            p.scenario_player_index,
            p.civilization_mode_id,
            p.civilization_id,
        )
        for p in options.players
    )
    active = [p.world_player_index for p in slots if p.humanity in (2, 4)]
    if (
        len(active) != options.num_players_excluding_gaia
        or len(set(active)) != len(active)
        or set(active) != set(range(1, world.prefix.num_players))
        or any(p.humanity not in (1, 2, 4) for p in slots)
        or any(p.world_player_index != -1 for p in slots if p.humanity == 1)
    ):
        raise NativeInputError("INVALID_PLAYER_BINDING", "unsupported lobby/World player mapping")
    wire_lists = _lists(saved, runtime=False)
    runtime_lists = _lists(saved, runtime=True)
    if _identity(source) != before or _sha(source) != source_sha:
        raise NativeInputError("INPUT_CHANGED", "recording changed while deriving native input")
    assert first is not None  # The required postgame itself is an operation.
    return NativeReplayInput(
        source,
        source_sha,
        size,
        hashlib.sha256(saved.raw).hexdigest(),
        len(saved.raw),
        header.build,
        header.save_version,
        options.version_word,
        options.section.offset,
        options.section.end_offset,
        header.end_offset,
        header_end,
        header_end + 32,
        body_metadata,
        world.prefix.clock_fields[0x18],
        world.prefix.clock_fields[0x10],
        options.dlc.dataset_id,
        int(options.fields["mGameMode"].value),
        int(options.fields["mSelectedContentMode"].value),
        world.map.width,
        world.map.height,
        world.map.tile_offset,
        len(world.map.tile_bytes),
        hashlib.sha256(world.map.tile_bytes).hexdigest(),
        int(options.fields["mPopulationLimit"].value),
        world.prefix.num_players,
        world.prefix.local_player_index,
        slots,
        wire_lists,
        runtime_lists,
        tuple(sorted(counts.items())),
        tuple(sorted(deltas.items())),
        clock_origin,
        tuple(bootstrap_syncs),
        checksum_sync_count,
        first.kind,
        first.offset,
        postgame.offset,
        postgame.offset + 4,
        len(postgame.payload),
        postgame.time_ms,
    )
