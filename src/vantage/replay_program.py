"""Native replay bootstrap and bounded input inspection, before simulation.

Saved state, proposed input clocks and committed simulation time are separate.
No method here executes a World pass, emits a Frame, resolves communications
selection caches or clears the original assembly's initialization-pending flags.
Evidence: world-envelope/input-frontier-integration and replay-program-bootstrap.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .replay_ai_clock import ReplayAIClock
from .replay_clock import ReplayClockStep, advance_replay_clock
from .replay_command_players import ReplayCommandPlayerTable, initial_replay_command_players
from .replay_commands import ReplayCommandError, decode_replay_command
from .replay_game_data import GameDataGraphic, GameDataMaster
from .replay_saved_world import SavedReplayWorld, load_replay_world
from .replay_stream import ReplayOperation, iter_replay_operations
from .replay_world_assembly import (
    ReplayInitialWorldAssembly,
    ReplayInitialWorldPending,
    assemble_replay_initial_world,
)
from .replay_world_tail import SavedTailCommandCache

_MASK = 0xFFFFFFFF
_MAX_RECORD_BYTES = 64 << 20
_KINDS = {"sync", "viewlock", "action", "chat", "chapter", "postgame"}


class ReplayProgramError(ValueError):
    """Input preparation failed; no simulation or logical inspection was committed."""

    def __init__(self, code: str, message: str, offset: int | None = None) -> None:
        self.code, self.offset = code, offset
        super().__init__(
            f"{code}: {message}" + (f" (file offset {offset:#x})" if offset is not None else "")
        )


@dataclass(frozen=True, slots=True)
class ReplayProgramFrontier:
    code: str
    phase: str
    message: str
    operation: ReplayOperation | None = None
    object_id: int | None = None
    owner: int | None = None
    master_index: int | None = None
    requested_master_index: int | None = None

    @property
    def offset(self) -> int | None:
        return None if self.operation is None else self.operation.offset


@dataclass(frozen=True, slots=True)
class ReplayProgramSourceIdentity:
    """Ordinary path stability, not an atomic immutable-file binding."""

    path: Path
    stat_words: tuple[int, int, int, int, int]

    @classmethod
    def capture(cls, path: Path) -> ReplayProgramSourceIdentity:
        observed = path.stat()
        return cls(
            path,
            (
                observed.st_dev,
                observed.st_ino,
                observed.st_size,
                observed.st_mtime_ns,
                observed.st_ctime_ns,
            ),
        )

    def verify(self) -> None:
        try:
            observed = self.capture(self.path)
        except OSError as error:
            raise ReplayProgramError(
                "source_changed", "recording identity is unavailable"
            ) from error
        if observed != self:
            raise ReplayProgramError(
                "source_changed", "recording changed after initial identity capture"
            )


@dataclass(frozen=True, slots=True)
class ReplayProgramBootstrap:
    assembly: ReplayInitialWorldAssembly
    initial_clock_ms: int
    saved_clock_fields: Mapping[int, int]
    command_cache: SavedTailCommandCache
    ai_clock: ReplayAIClock
    srand_seed: int
    frame_random_seed: int
    source: str | None
    file_identity: ReplayProgramSourceIdentity | None = None
    initial_command_players: ReplayCommandPlayerTable | None = None

    @property
    def pending(self) -> ReplayInitialWorldPending:
        return self.assembly.pending


@dataclass(frozen=True, slots=True)
class ReplayPlannedCommand:
    operation: ReplayOperation
    decoded: Mapping[str, Any] | None
    frontier: ReplayProgramFrontier


@dataclass(frozen=True, slots=True)
class ReplayInputPlan:
    """One inspected sync/drain window, or one non-sync record.

    Operations/bytes are authoritative input, while decoded dictionaries are
    inspection views. A sync includes at most one optional viewlock and only
    consecutive action records. Its following boundary remains buffered.
    The proposed clock is not permission to enter or complete a World pass.
    """

    operations: tuple[ReplayOperation, ...]
    proposed_clock: ReplayClockStep | None
    commands: tuple[ReplayPlannedCommand, ...]
    frontier: ReplayProgramFrontier
    following: ReplayOperation | None
    terminal: bool = False


def _u32(value: int, label: str) -> None:
    if type(value) is not int or not 0 <= value <= _MASK:
        raise ReplayProgramError("saved_state", f"{label} must be a u32")


def _limits(operations: int, payload_bytes: int) -> None:
    if type(operations) is not int or not 1 <= operations <= 65536:
        raise ReplayProgramError("limits", "plan operation limit must be an integer1..65536")
    if type(payload_bytes) is not int or not 1 <= payload_bytes <= _MAX_RECORD_BYTES:
        raise ReplayProgramError("limits", "plan payload byte limit must be an integer1..64MiB")


class ReplayProgram:
    """A loaded logical world plus a lossless bounded read-ahead cursor.

    Successful reads move only ``input_position``/``input_time_ms``. Failed
    reads preserve both, the original state, and every fetched valid operation.
    Physical lookahead can grow the buffer before failure. At most one record
    beyond the configured window is retained: max_plan_operations+1 records
    and max_plan_bytes+64MiB payload bytes. Overflow poisons further fetching;
    it cannot silently skip the offending record. Original iterator framing
    has its own64MiB record bound. EOF is not simulation completion.
    """

    def __init__(
        self,
        bootstrap: ReplayProgramBootstrap,
        operations: Iterable[ReplayOperation],
        *,
        max_plan_operations: int = 4096,
        max_plan_bytes: int = 16 << 20,
    ) -> None:
        _limits(max_plan_operations, max_plan_bytes)
        if not isinstance(bootstrap, ReplayProgramBootstrap):
            raise ReplayProgramError("saved_state", "a typed program bootstrap is required")
        self._bootstrap = bootstrap
        self._source = iter(operations)
        self._buffer: list[ReplayOperation] = []
        self._buffer_bytes = 0
        self._error: Exception | None = None
        self._eof = False
        self._closed = False
        self._owns_source = False
        self._source_closed = False
        self._terminal: ReplayInputPlan | None = None
        self._position = 0
        self._input_time_ms = bootstrap.initial_clock_ms
        self._max_operations, self._max_bytes = max_plan_operations, max_plan_bytes

    @property
    def bootstrap(self) -> ReplayProgramBootstrap:
        return self._bootstrap

    @property
    def committed_time_ms(self) -> int:
        """The saved clock; this infrastructure exposes no simulation commit API."""
        return self.bootstrap.initial_clock_ms

    @property
    def input_time_ms(self) -> int:
        return self._input_time_ms

    @property
    def input_position(self) -> int:
        return self._position

    @property
    def buffered_operations(self) -> tuple[ReplayOperation, ...]:
        return tuple(self._buffer)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def owned_source_closed(self) -> bool:
        return self._owns_source and self._source_closed

    def _close_owned_source(self) -> None:
        if self._owns_source and not self._source_closed:
            close = getattr(self._source, "close", None)
            try:
                if callable(close):
                    close()
            except Exception as error:
                failure = ReplayProgramError("source_close", "owned input source could not close")
                self._error = failure
                raise failure from error
            self._source_closed = True

    def close(self) -> None:
        """Stop inspection and close only a source owned by the path loader.

        All bootstrap/buffer/terminal diagnostics remain available. A direct
        caller-supplied iterable remains caller-owned, including its cleanup.
        Closing is neither EOF nor simulation completion; later reads fail.
        """
        self._closed = True
        self._close_owned_source()

    def __enter__(self) -> ReplayProgram:
        if self._closed:
            raise ReplayProgramError("closed", "input inspection is explicitly closed")
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def initialization_frontier(self) -> ReplayProgramFrontier:
        return ReplayProgramFrontier(
            "initialization_pending",
            "initialization",
            "Saved reference/lifecycle/spatial effects remain pending on the original assembly",
        )

    def _check_source(self) -> None:
        identity = self.bootstrap.file_identity
        if identity is not None:
            try:
                identity.verify()
            except ReplayProgramError as error:
                self._error = error
                raise

    def _at(self, index: int) -> ReplayOperation | None:
        while len(self._buffer) <= index:
            if self._error is not None:
                raise self._error
            if self._eof:
                return None
            try:
                self._check_source()
                operation = next(self._source)
                self._check_source()
                if (
                    not isinstance(operation, ReplayOperation)
                    or operation.kind not in _KINDS
                    or type(operation.offset) is not int
                    or operation.offset < 0
                    or type(operation.time_ms) is not int
                    or operation.time_ms < 0
                    or type(operation.payload) is not bytes
                    or len(operation.payload) > _MAX_RECORD_BYTES
                ):
                    raise ReplayProgramError("operation", "unsupported or malformed input record")
                self._buffer.append(operation)
                self._buffer_bytes += len(operation.payload)
                if (
                    len(self._buffer) > self._max_operations + 1
                    or self._buffer_bytes > self._max_bytes + _MAX_RECORD_BYTES
                ):
                    raise ReplayProgramError(
                        "buffer_limit", "bounded input lookahead exceeded", operation.offset
                    )
            except StopIteration:
                self._check_source()
                self._close_owned_source()
                self._eof = True
                return None
            except Exception as error:
                self._check_source()
                self._error = error
                raise
        return self._buffer[index]

    def _command(self, operation: ReplayOperation) -> ReplayPlannedCommand:
        try:
            # SavedTailCommandCache is intentionally NOT passed as selection:
            # its communications-key mapping has not been established here.
            decoded = decode_replay_command(operation.payload)
        except ReplayCommandError as error:
            raise ReplayProgramError("command", str(error), operation.offset) from error
        obj = None
        requested = None
        if decoded is not None and decoded.get("kind") == "transformobject":
            raw_id = decoded.get("objid")
            if type(raw_id) is int and 0 <= raw_id <= _MASK:
                obj = self.bootstrap.assembly.objects_by_raw_id.get(raw_id)
            requested = decoded.get("masterid")
        frontier = ReplayProgramFrontier(
            "unsupported_command_variant" if decoded is None else "command_execution_unsupported",
            "command",
            "Wire decoding does not execute issuer validation or state changes",
            operation,
            obj.saved.object_id if obj is not None else None,
            obj.saved.owner if obj is not None else None,
            obj.saved.master_id if obj is not None else None,
            requested,
        )
        return ReplayPlannedCommand(
            operation, None if decoded is None else MappingProxyType(decoded), frontier
        )

    def read_next_input(self) -> ReplayInputPlan | None:
        """Prepare/read one inspection window, atomically with respect to its cursor.

        Chat, chapter, viewlock outside a sync, and standalone action each form
        their own window. Chapter and postgame stop further read-ahead. Their
        plan is retained on repeat calls; no chapter restore/end result follows.
        Action timestamps are provenance; native dispatch does not sort or
        schedule commands by them. Sync clocks cross-check the saved origin.
        """
        if self._closed:
            raise ReplayProgramError("closed", "input inspection is explicitly closed")
        if self._error is not None:
            raise self._error
        self._check_source()
        if self._terminal is not None:
            return self._terminal
        first = self._at(0)
        if first is None:
            return None
        if len(first.payload) > self._max_bytes:
            raise ReplayProgramError(
                "plan_limit", "first record exceeds payload budget", first.offset
            )
        records = [first]
        included_bytes = len(first.payload)
        step = None
        commands: list[ReplayPlannedCommand] = []
        following = None
        terminal = first.kind in {"chapter", "postgame"}
        if first.kind == "sync":
            if len(first.payload) not in (4, 364) or (
                len(first.payload) == 364 and first.payload[4:8] != bytes(4)
            ):
                raise ReplayProgramError("sync", "invalid delta/checksum payload", first.offset)
            delta = int(struct.unpack_from("<I", first.payload)[0])
            step = advance_replay_clock(self._input_time_ms, delta)
            if first.time_ms & _MASK != step.time_ms:
                raise ReplayProgramError(
                    "clock_origin", "sync disagrees with saved/input clock", first.offset
                )
            following = self._at(1)
            if following is not None and following.kind == "viewlock":
                if len(records) >= self._max_operations:
                    raise ReplayProgramError(
                        "plan_limit", "viewlock exceeds operation limit", following.offset
                    )
                if included_bytes + len(following.payload) > self._max_bytes:
                    raise ReplayProgramError(
                        "plan_limit", "viewlock exceeds payload budget", following.offset
                    )
                if len(following.payload) != 12:
                    raise ReplayProgramError(
                        "viewlock", "expected12 payload bytes", following.offset
                    )
                records.append(following)
                included_bytes += len(following.payload)
                following = self._at(len(records))
            while following is not None and following.kind == "action":
                if len(records) >= self._max_operations:
                    raise ReplayProgramError(
                        "plan_limit", "action drain exceeds operation limit", following.offset
                    )
                if included_bytes + len(following.payload) > self._max_bytes:
                    raise ReplayProgramError(
                        "plan_limit", "included action exceeds payload budget", following.offset
                    )
                records.append(following)
                included_bytes += len(following.payload)
                commands.append(self._command(following))
                following = self._at(len(records))
            frontier = ReplayProgramFrontier(
                "world_pass_unproved",
                "world_entry",
                "A recorded sync proposes a clock; entered/completed World phases remain unproved",
                first,
            )
        else:
            if first.kind == "action":
                commands.append(self._command(first))
            code = {
                "chapter": "chapter_restore_required",
                "postgame": "postgame_not_simulated",
            }.get(first.kind, "input_delivery_unsupported")
            frontier = ReplayProgramFrontier(
                code, first.kind, "Record retained without simulation effects", first
            )
        if (
            len(records) > self._max_operations
            or sum(len(row.payload) for row in records) > self._max_bytes
        ):
            raise ReplayProgramError(
                "plan_limit", "input window exceeds configured bounds", first.offset
            )
        plan = ReplayInputPlan(tuple(records), step, tuple(commands), frontier, following, terminal)
        self._check_source()
        if terminal:
            self._close_owned_source()
        # Only this read-ahead cursor changes. Bootstrap, caches, clocks/banks
        # and every assembly pending flag retain their original identities.
        del self._buffer[: len(records)]
        self._buffer_bytes -= sum(len(row.payload) for row in records)
        self._position += len(records)
        if step is not None:
            self._input_time_ms = step.time_ms
        if terminal:
            self._terminal = plan
        return plan


def prepare_replay_program(
    saved: SavedReplayWorld,
    operations: Iterable[ReplayOperation],
    selected_baselines: Sequence[Mapping[int, GameDataMaster | None]],
    *,
    graphics: Mapping[int, GameDataGraphic | None],
    source: str | None = None,
    max_plan_operations: int = 4096,
    max_plan_bytes: int = 16 << 20,
) -> ReplayProgram:
    """Bind actual saved data and input without consuming input or running effects.

    Baseline/civilization/graphics selection remains the caller's explicit
    build-matched input. Mutable source dictionaries keep their existing
    contracts; no deep immutability or runtime-ready world is asserted. This
    direct entry's iterable/source lifetime and consistency are caller-owned.
    """
    _limits(max_plan_operations, max_plan_bytes)
    if not isinstance(saved, SavedReplayWorld):
        raise ReplayProgramError("saved_state", "a parsed complete saved world is required")
    assembly = assemble_replay_initial_world(saved, selected_baselines, graphics=graphics)
    prefix = saved.prefix.world.prefix
    clock = prefix.clock_fields.get(0x18)
    frame_seed = prefix.fields.get(0x7D0)
    for word, label in (
        (clock, "clock18"),
        (frame_seed, "frame seed7d0"),
        (prefix.srand_seed, "srand seed"),
    ):
        if type(word) is not int:
            raise ReplayProgramError("saved_state", f"missing/invalid {label}")
        _u32(word, label)
    assert clock is not None and frame_seed is not None
    if len(prefix.player_words) != len(assembly.players):
        raise ReplayProgramError("saved_state", "owner elapsed bank does not match players")
    try:
        ai_clock = ReplayAIClock(prefix.fields[0x188], prefix.player_words)
    except (ValueError, KeyError) as error:
        raise ReplayProgramError("saved_state", "invalid saved owner clock") from error
    cache = saved.tail.base.command_cache
    if not isinstance(cache, SavedTailCommandCache):
        raise ReplayProgramError("saved_state", "the saved unresolved command cache is required")
    try:
        initial_players = initial_replay_command_players(
            saved.prefix.header.options, len(assembly.players)
        )
    except ValueError as error:
        raise ReplayProgramError("saved_state", "invalid initial command-player context") from error
    bootstrap = ReplayProgramBootstrap(
        assembly,
        clock,
        MappingProxyType(prefix.clock_fields),
        cache,
        ai_clock,
        prefix.srand_seed,
        frame_seed,
        source,
        initial_command_players=initial_players,
    )
    return ReplayProgram(
        bootstrap,
        operations,
        max_plan_operations=max_plan_operations,
        max_plan_bytes=max_plan_bytes,
    )


def load_replay_program(
    path: str | Path,
    selected_baselines: Sequence[Mapping[int, GameDataMaster | None]],
    *,
    graphics: Mapping[int, GameDataGraphic | None],
    max_inflated_bytes: int = 256 << 20,
    max_compressed_bytes: int = 64 << 20,
    max_plan_operations: int = 4096,
    max_plan_bytes: int = 16 << 20,
) -> ReplayProgram:
    """Load initial world/body with ordinary stat identity guards, without DE.

    Canonical dev/inode/size/mtime_ns/ctime_ns are checked around initial load,
    assembly, lazy operation reads and inspection-window commits. This detects
    ordinary replacement/edits; it is not a lock or atomic immutable snapshot.
    """
    _limits(max_plan_operations, max_plan_bytes)
    path = Path(path).expanduser().resolve()
    identity = ReplayProgramSourceIdentity.capture(path)
    try:
        saved = load_replay_world(
            path, max_inflated_bytes=max_inflated_bytes, max_compressed_bytes=max_compressed_bytes
        )
    except Exception:
        identity.verify()
        raise
    identity.verify()
    program = prepare_replay_program(
        saved,
        iter_replay_operations(path),
        selected_baselines,
        graphics=graphics,
        source=str(Path(path)),
        max_plan_operations=max_plan_operations,
        max_plan_bytes=max_plan_bytes,
    )
    identity.verify()
    program._bootstrap = replace(program.bootstrap, file_identity=identity)
    program._owns_source = True
    return program
