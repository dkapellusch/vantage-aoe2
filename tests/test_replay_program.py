"""Complete original saved headers/DAT selection and bounded unexecuted input plans."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import _graphic, read_game_data_master
from vantage.replay_program import (
    ReplayProgram,
    ReplayProgramError,
    ReplayProgramSourceIdentity,
    load_replay_program,
    prepare_replay_program,
)
from vantage.replay_stream import ReplayOperation, iter_replay_operations
from vantage.replay_world_assembly import ReplayWorldAssemblyError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    """All current slots, not the older intentionally sparse assembly fixture."""
    directory = tmp_path_factory.mktemp("complete-replay-program")
    with zipfile.ZipFile(FIXTURES / "native_replay_program_54800.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        bodies = archive.read("bodies.bin")
        masters, graphics, result = {}, {}, {}
        for case in manifest["cases"]:
            tables = []
            for row in case["selected_baselines"]:
                table = {}
                for index, key in row.items():
                    if key not in masters:
                        at, size = manifest["bodies"][key]
                        raw = bodies[at : at + size]
                        assert hashlib.sha256(raw).hexdigest() == key
                        reader = SaveReader(raw, version=0x43E666)
                        masters[key] = read_game_data_master(reader)
                        assert reader.remaining == 0
                    table[int(index)] = masters[key]
                tables.append(table)
            sprites = {}
            for index, key in case["graphics"].items():
                if key is None:
                    sprites[int(index)] = None
                    continue
                if key not in graphics:
                    at, size = manifest["bodies"][key]
                    raw = bodies[at : at + size]
                    assert hashlib.sha256(raw).hexdigest() == key
                    reader = SaveReader(raw, version=0x43E666)
                    graphics[key] = _graphic(reader)
                    assert reader.remaining == 0
                sprites[int(index)] = graphics[key]
            window = archive.read(case["window_member"])
            assert len(window) == case["window_bytes"]
            assert hashlib.sha256(window).hexdigest() == case["window_sha256"]
            path = directory / case["window_member"]
            path.write_bytes(window)
            program = load_replay_program(path, tables, graphics=sprites)
            result[case["sample"]] = (program.bootstrap, path, tables, sprites, case)
            program.close()
    return result


def _sync(time, delta, offset=100):
    return ReplayOperation("sync", offset, time, struct.pack("<I", delta))


def _action(time=0, offset=108, payload=b"\xfe\x01\x01\0x"):
    return ReplayOperation("action", offset, time, payload)


def _program(inputs, operations, **limits):
    return ReplayProgram(inputs["6p"][0], operations, **limits)


@pytest.mark.parametrize("sample", ["3p", "6p"])
def test_complete_original_header_all_current_master_slots_and_input_frontier(inputs, sample):
    bootstrap, path, tables, graphics, case = inputs[sample]
    program = load_replay_program(path, tables, graphics=graphics)
    assembly = program.bootstrap.assembly
    expected = case["expected"]
    assert len(assembly.objects_by_raw_id) == expected["objects"]
    assert (
        sum(sum(m is not None for m in p.masters) for p in assembly.players) == expected["masters"]
    )
    assert len(assembly.players) == expected["players"]
    assert program.bootstrap.command_cache is assembly.saved.tail.base.command_cache
    assert program.bootstrap.pending is assembly.pending
    issuers = program.bootstrap.initial_command_players
    assert issuers is not None
    issuer = issuers.resolve_non_gaia(1)
    assert issuer is not None and (issuer.options_slot, issuer.world_player_index) == (0, 1)
    assert program.bootstrap.pending.reference_callbacks is True
    assert program.bootstrap.pending.lifecycle_updates is True
    assert program.bootstrap.pending.spatial_registries is True
    assert program.bootstrap.ai_clock == bootstrap.ai_clock
    assert program.bootstrap.srand_seed == expected["srand_seed"]
    assert program.bootstrap.frame_random_seed == expected["frame_random_seed"]
    assert (
        hashlib.sha256(program.bootstrap.command_cache.raw).hexdigest()
        == expected["saved_cache_sha256"]
    )
    before_cache, before_banks = program.bootstrap.command_cache, program.bootstrap.ai_clock
    plans = []
    while True:
        plan = program.read_next_input()
        assert plan is not None
        plans.append(plan)
        if plan.commands:
            break
    assert program.committed_time_ms == 0 and program.input_time_ms == expected["input_time_ms"]
    assert program.input_position == expected["input_position"]
    assert (
        program.bootstrap.command_cache is before_cache
        and program.bootstrap.ai_clock is before_banks
    )
    command = plans[-1].commands[0]
    assert dict(command.decoded) == expected["first_command"]
    assert command.frontier.offset == expected["first_command_offset"]
    assert (
        command.frontier.owner,
        command.frontier.master_index,
        command.frontier.requested_master_index,
    ) == (1, 1649, 1652)
    assert command.frontier.object_id == expected["first_command"]["objid"]
    assert command.frontier.code == "command_execution_unsupported"
    assert plans[0].proposed_clock.delta_ms == 0
    assert plans[0].frontier.code == "world_pass_unproved"
    assert program.initialization_frontier.code == "initialization_pending"
    flattened = tuple(record for plan in plans for record in plan.operations)
    source = tuple(iter_replay_operations(path))
    original_prefix = next(
        row
        for row in json.loads(
            gzip.decompress(
                (FIXTURES / "native_replay_program_prefixes_54800.json.gz").read_bytes()
            )
        )["cases"]
        if row["sample"] == sample
    )
    assert source == tuple(
        ReplayOperation(
            row["kind"], row["offset"], row["time_ms"], bytes.fromhex(row["payload_hex"])
        )
        for row in original_prefix["operations"]
    )
    assert flattened == source[:-1]
    assert program.buffered_operations == (source[-1],)
    last = program.read_next_input()
    assert last is not None and last.frontier.code == "world_pass_unproved"
    assert program.read_next_input() is None
    # A bounded fixture file's EOF proves no game/world completion.
    assert program.committed_time_ms == 0 and program.bootstrap.pending is assembly.pending


def test_chat_boundary_prevents_same_time_actions_from_entering_previous_drain(inputs):
    chat = ReplayOperation("chat", 120, 0, b"\xff" * 4 + b"message")
    records = (_sync(0, 0), _action(offset=108), chat, _action(offset=140))
    program = _program(inputs, records)
    first = program.read_next_input()
    assert first.operations == records[:2] and first.following is chat
    second = program.read_next_input()
    assert second.operations == (chat,) and not second.commands and second.proposed_clock is None
    third = program.read_next_input()
    assert third.operations == (records[3],) and third.commands[0].operation is records[3]
    assert program.committed_time_ms == program.input_time_ms == 0


def test_only_one_optional_viewlock_is_in_a_sync_window(inputs):
    first, second = (ReplayOperation("viewlock", offset, 0, bytes(12)) for offset in (108, 124))
    program = _program(inputs, (_sync(0, 0), first, second, _action(offset=140)))
    plan = program.read_next_input()
    assert plan.operations == (_sync(0, 0), first) and plan.following is second
    assert program.read_next_input().operations == (second,)


@pytest.mark.parametrize(
    ("origin", "delta", "after"), [(100000, 28, 100028), (100000, 0, 100000), (0xFFFFFFFF, 1, 0)]
)
def test_nonzero_and_zero_origins_and_native_wrap_are_proposals_only(inputs, origin, delta, after):
    bootstrap = replace(inputs["6p"][0], initial_clock_ms=origin)
    # Explicit counterfactual cursor clock; no changed native saved bytes are claimed.
    program = ReplayProgram(bootstrap, (_sync(origin + delta, delta),))
    plan = program.read_next_input()
    assert plan.proposed_clock.time_ms == after and program.input_time_ms == after
    assert program.committed_time_ms == origin
    assert program.bootstrap.ai_clock is bootstrap.ai_clock


def test_action_timestamp_does_not_schedule_or_change_the_proposed_clock(inputs):
    record = _action(time=999999)
    program = _program(inputs, (_sync(28, 28), record))
    plan = program.read_next_input()
    assert plan.commands[0].operation is record and record.time_ms == 999999
    assert (
        plan.commands[0].decoded is None
        and plan.commands[0].frontier.code == "unsupported_command_variant"
    )
    assert program.input_time_ms == 28 and program.committed_time_ms == 0


def test_saved_selection_cache_is_retained_without_guessing_communications_keys(inputs):
    bootstrap = inputs["6p"][0]
    cache = replace(bootstrap.command_cache, selected_units=((9669,),) * 9)
    bootstrap = replace(bootstrap, command_cache=cache)
    raw = bytearray(24)
    struct.pack_into("<BBHi", raw, 0, 3, 1, 20, -1)
    struct.pack_into("<H", raw, 16, 0xFFFF)
    program = ReplayProgram(bootstrap, (_sync(0, 0), _action(payload=bytes(raw))))
    plan = program.read_next_input()
    assert plan.commands[0].decoded is None
    assert plan.commands[0].operation.payload == bytes(raw)
    assert program.bootstrap.command_cache is cache and cache.selected_units == ((9669,),) * 9


@pytest.mark.parametrize("kind", ["chapter", "postgame"])
def test_chapter_and_postgame_are_retained_terminal_frontiers_not_restore_or_completion(
    inputs, kind
):
    record = ReplayOperation(kind, 100, 0, struct.pack("<II", 300, 0))
    consumed = []

    def source():
        consumed.append(1)
        yield record
        consumed.append(2)
        yield _sync(100, 100)

    program = _program(inputs, source())
    plan = program.read_next_input()
    assert plan.terminal and plan.operations == (record,) and plan.frontier.offset == 100
    assert program.read_next_input() is plan and consumed == [1]
    assert program.input_position == 1 and program.committed_time_ms == program.input_time_ms == 0


def test_valid_plan_allows_one_larger_boundary_lookahead_and_keeps_it_unexecuted(inputs):
    chat = ReplayOperation("chat", 108, 0, b"c" * 50)
    program = _program(inputs, (_sync(0, 0), chat), max_plan_bytes=4)
    plan = program.read_next_input()
    assert plan.operations == (_sync(0, 0),) and plan.following is chat
    assert program.input_position == 1 and program.buffered_operations == (chat,)
    with pytest.raises(ReplayProgramError, match="payload budget"):
        program.read_next_input()
    assert program.input_position == 1 and program.buffered_operations == (chat,)
    assert program.committed_time_ms == 0


def test_oversized_included_action_preserves_cursor_clock_and_buffer_without_further_read(inputs):
    records = (_sync(28, 28), _action(time=28))
    seen = []

    def source():
        for row in records:
            seen.append(row)
            yield row
        raise AssertionError("must not read beyond the over-budget included action")

    program = _program(inputs, source(), max_plan_bytes=4)
    for _ in range(2):
        with pytest.raises(ReplayProgramError, match="included action") as error:
            program.read_next_input()
        assert error.value.offset == 108
    assert program.input_position == 0 and program.committed_time_ms == program.input_time_ms == 0
    assert program.buffered_operations == records and seen == list(records)


@pytest.mark.parametrize("operation_limit", [1, 2, 3])
def test_pathological_action_drain_has_bounded_lookahead_and_no_partial_cursor_commit(
    inputs, operation_limit
):
    seen = []

    def source():
        yield _sync(28, 28)
        for offset in range(108, 1000, 8):
            seen.append(offset)
            yield _action(time=28, offset=offset)

    program = _program(inputs, source(), max_plan_operations=operation_limit)
    with pytest.raises(ReplayProgramError, match="operation limit"):
        program.read_next_input()
    assert len(program.buffered_operations) == operation_limit + 1
    assert len(seen) == operation_limit
    assert program.input_position == 0 and program.input_time_ms == 0


def test_viewlock_cannot_add_an_extra_record_beyond_the_operation_bound(inputs):
    lock = ReplayOperation("viewlock", 108, 0, bytes(12))
    program = _program(inputs, (_sync(0, 0), lock, _action(offset=124)), max_plan_operations=1)
    with pytest.raises(ReplayProgramError, match="viewlock exceeds"):
        program.read_next_input()
    assert program.buffered_operations == (_sync(0, 0), lock)


@pytest.mark.parametrize(
    "records,code",
    [
        ((_sync(30, 28),), "clock_origin"),
        ((ReplayOperation("sync", 100, 0, b"x"),), "sync"),
        ((_sync(0, 0), _action(payload=b"\x01")), "command"),
        ((_sync(0, 0), ReplayOperation("viewlock", 108, 0, b"x")), "viewlock"),
        ((ReplayOperation("unsupported", 100, 0, b"x"),), "operation"),
    ],
)
def test_failed_input_preparation_preserves_saved_state_and_logical_cursor(inputs, records, code):
    program = _program(inputs, records)
    bootstrap = program.bootstrap
    for _ in range(2):
        with pytest.raises(ReplayProgramError) as error:
            program.read_next_input()
        assert error.value.code == code
    assert program.input_position == 0 and program.input_time_ms == program.committed_time_ms == 0
    assert program.bootstrap is bootstrap and bootstrap.pending is bootstrap.assembly.pending
    assert bootstrap.command_cache is bootstrap.assembly.saved.tail.base.command_cache


def test_source_failure_is_sticky_and_keeps_fetched_prefix(inputs):
    record = _sync(28, 28)

    def source():
        yield record
        raise ValueError("source failed after sync")

    program = _program(inputs, source())
    for _ in range(2):
        with pytest.raises(ValueError, match="source failed"):
            program.read_next_input()
    assert program.input_position == 0 and program.buffered_operations == (record,)


def test_checksum_bytes_remain_attached_and_unknown_command_bytes_are_lossless(inputs):
    raw = struct.pack("<I", 28) + bytes(360)
    sync = ReplayOperation("sync", 100, 28, raw)
    command = _action(time=28)
    program = _program(inputs, (sync, command))
    plan = program.read_next_input()
    assert plan.operations == (sync, command) and plan.operations[0].payload is raw
    assert plan.commands[0].operation.payload is command.payload


def test_failed_bootstrap_never_consumes_source_or_changes_existing_program(inputs):
    bootstrap, _path, tables, graphics, _case = inputs["3p"]
    touched = []

    def source():
        touched.append(True)
        yield _sync(0, 0)

    wrong = list(tables)
    wrong[0] = {}
    with pytest.raises(ReplayWorldAssemblyError):
        prepare_replay_program(bootstrap.assembly.saved, source(), wrong, graphics=graphics)
    assert touched == []
    assert bootstrap.pending is bootstrap.assembly.pending


@pytest.mark.parametrize(
    "limits",
    [
        {"max_plan_operations": 0},
        {"max_plan_operations": True},
        {"max_plan_operations": 65537},
        {"max_plan_bytes": 0},
        {"max_plan_bytes": True},
        {"max_plan_bytes": (64 << 20) + 1},
    ],
)
def test_invalid_bounds_reject_before_file_open(inputs, tmp_path, limits):
    with pytest.raises(ReplayProgramError, match="limits"):
        load_replay_program(
            tmp_path / "absent", inputs["3p"][2], graphics=inputs["3p"][3], **limits
        )


def test_actual_stream_chapter_boundary_is_not_followed_into_old_world(inputs, tmp_path):
    _bootstrap, original, tables, graphics, _case = inputs["3p"]
    wire = bytearray(original.read_bytes())
    at = len(wire)
    checkpoint = b"a separate checkpoint payload; not an operation stream"
    struct.pack_into("<I", wire, 4, at)
    wire.extend(struct.pack("<II", at + 8 + len(checkpoint), 0) + checkpoint)
    wire.extend(struct.pack("<I", 97))  # Reading beyond the chapter would fail.
    path = tmp_path / "with-chapter.aoe2record"
    path.write_bytes(wire)
    program = load_replay_program(path, tables, graphics=graphics)
    while True:
        plan = program.read_next_input()
        assert plan is not None
        if plan.terminal:
            break
    assert plan.frontier.code == "chapter_restore_required" and plan.frontier.offset == at
    assert program.read_next_input() is plan and program.committed_time_ms == 0


@pytest.mark.parametrize("change", ["replace", "inplace"])
def test_path_backed_loader_detects_replacement_or_inplace_edit_before_lazy_body_open(
    inputs, tmp_path, change
):
    _bootstrap, original, tables, graphics, _case = inputs["3p"]
    path = tmp_path / "changing.aoe2record"
    path.write_bytes(original.read_bytes())
    program = load_replay_program(path, tables, graphics=graphics)
    identity = program.bootstrap.file_identity
    assert identity is not None
    if change == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    else:
        with path.open("r+b") as stream:
            stream.seek(-1, 2)
            stream.write(b"x")
    assert ReplayProgramSourceIdentity.capture(path) != identity
    for _ in range(2):
        with pytest.raises(ReplayProgramError, match="source_changed"):
            program.read_next_input()
    assert program.input_position == 0 and program.buffered_operations == ()
    assert program.committed_time_ms == program.input_time_ms == 0


def test_source_change_also_rejects_buffered_only_window_without_losing_boundary(inputs, tmp_path):
    _bootstrap, original, tables, graphics, _case = inputs["3p"]
    path = tmp_path / "buffered-change.aoe2record"
    path.write_bytes(original.read_bytes())
    program = load_replay_program(path, tables, graphics=graphics)
    first = program.read_next_input()
    assert first.following.kind == "chat"
    before = program.buffered_operations
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ReplayProgramError, match="source_changed"):
        program.read_next_input()
    assert program.input_position == len(first.operations)
    assert program.buffered_operations == before and before[0] is first.following
    assert program.committed_time_ms == 0


def test_source_check_after_lazy_next_catches_change_before_admitting_record(inputs, tmp_path):
    path = tmp_path / "source-token"
    path.write_bytes(b"initial")
    bootstrap = replace(inputs["3p"][0], file_identity=ReplayProgramSourceIdentity.capture(path))

    def changed_source():
        path.write_bytes(b"replacement")
        yield _sync(0, 0)

    program = ReplayProgram(bootstrap, changed_source())
    with pytest.raises(ReplayProgramError, match="source_changed"):
        program.read_next_input()
    assert program.input_position == 0 and program.buffered_operations == ()


def test_source_change_during_initial_world_load_is_detected_before_body_is_bound(
    inputs, tmp_path, monkeypatch
):
    import vantage.replay_program as module

    _bootstrap, original, tables, graphics, _case = inputs["3p"]
    path = tmp_path / "during-initial-load.aoe2record"
    path.write_bytes(original.read_bytes())
    original_loader = module.load_replay_world

    def changed_after_load(path, **kwargs):
        saved = original_loader(path, **kwargs)
        with path.open("ab") as stream:
            stream.write(b"appended after header load")
        return saved

    monkeypatch.setattr(module, "load_replay_world", changed_after_load)
    with pytest.raises(ReplayProgramError, match="source_changed"):
        module.load_replay_program(path, tables, graphics=graphics)


def test_source_change_before_standalone_window_commit_preserves_buffer(
    inputs, tmp_path, monkeypatch
):
    import vantage.replay_program as module

    path = tmp_path / "before-commit"
    path.write_bytes(b"original")
    bootstrap = replace(inputs["3p"][0], file_identity=ReplayProgramSourceIdentity.capture(path))
    command = _action()
    decoder = module.decode_replay_command

    def changed_during_inspection(raw):
        value = decoder(raw)
        path.write_bytes(b"changed during command view preparation")
        return value

    monkeypatch.setattr(module, "decode_replay_command", changed_during_inspection)
    program = ReplayProgram(bootstrap, (command,))
    with pytest.raises(ReplayProgramError, match="source_changed"):
        program.read_next_input()
    assert program.input_position == 0 and program.buffered_operations == (command,)


@pytest.mark.parametrize("context", [False, True])
def test_partial_path_backed_inspection_closes_actual_lazy_file_on_caller_exit(
    inputs, monkeypatch, context
):
    _bootstrap, path, tables, graphics, _case = inputs["3p"]
    original_open = Path.open
    opened = []

    def tracked_open(self, *args, **kwargs):
        stream = original_open(self, *args, **kwargs)
        if self == path:
            opened.append(stream)
        return stream

    monkeypatch.setattr(Path, "open", tracked_open)
    program = load_replay_program(path, tables, graphics=graphics)
    assert opened and all(stream.closed for stream in opened)
    if context:
        with program:
            plan = program.read_next_input()
            assert not opened[-1].closed
    else:
        plan = program.read_next_input()
        assert not opened[-1].closed
        program.close()
    assert all(stream.closed for stream in opened) and program.owned_source_closed
    assert program.buffered_operations == (plan.following,)
    assert program.committed_time_ms == 0 and program.closed
    program.close()  # Idempotent cleanup does not discard the diagnostic boundary.
    with pytest.raises(ReplayProgramError, match="closed"):
        program.read_next_input()


@pytest.mark.parametrize("terminal", ["chapter", "postgame"])
def test_path_backed_terminal_closes_lazy_file_but_keeps_terminal_plan(
    inputs, tmp_path, monkeypatch, terminal
):
    _bootstrap, original, tables, graphics, _case = inputs["3p"]
    window = original.read_bytes()
    header_end = int.from_bytes(window[:4], "little")
    body_at = header_end + 32
    if terminal == "postgame":
        body = struct.pack("<II", 6, 0)
        wire = window[:body_at] + body
    else:
        wire = bytearray(window[:body_at])
        struct.pack_into("<I", wire, 4, body_at)
        wire.extend(struct.pack("<II", body_at + 8, 0))
    path = tmp_path / (terminal + ".aoe2record")
    path.write_bytes(wire)
    original_open = Path.open
    opened = []

    def tracked_open(self, *args, **kwargs):
        stream = original_open(self, *args, **kwargs)
        if self == path:
            opened.append(stream)
        return stream

    monkeypatch.setattr(Path, "open", tracked_open)
    program = load_replay_program(path, tables, graphics=graphics)
    plan = program.read_next_input()
    assert plan.terminal and all(stream.closed for stream in opened)
    assert program.owned_source_closed and not program.closed
    assert program.read_next_input() is plan and program.committed_time_ms == 0
    program.close()
    with pytest.raises(ReplayProgramError, match="closed"):
        program.read_next_input()


def test_direct_caller_iterable_cleanup_is_not_silently_owned(inputs):
    finished = []

    def source():
        try:
            yield _sync(0, 0)
            yield ReplayOperation("chat", 108, 0, b"chat boundary")
            yield _sync(28, 28, 116)
        finally:
            finished.append(True)

    external = source()
    program = _program(inputs, external)
    plan = program.read_next_input()
    program.close()
    assert finished == [] and not program.owned_source_closed
    assert program.buffered_operations == (plan.following,)
    external.close()
    assert finished == [True]
