"""Authored source controls; owned I/O/storage never claim a native oracle."""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from vantage import replay_research_saved as research
from vantage.replay_base_saved_leaves import bind_replay_base_saved_leaves
from vantage.replay_de_string_saved import (
    ReplayDEStringSavedScratch,
    bind_replay_de_string_saved,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_civilization_lookup import bind_replay_player_civilization_lookup
from vantage.replay_player_saved_children import bind_replay_player_saved_children
from vantage.replay_research_storage import (
    ReplayResearchStorageScratch,
    bind_replay_research_storage,
)
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

U64 = (1 << 64) - 1
SUBJECT, OUTPUT, STREAM, VTABLE, CATALOG, PLAYER = 0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000
VERSION, INPUT, ENTRY = 0x1440A0D94, 0xF001, 0x14148D110
APPEND, COMMIT, RECONCILE, CHANGE, RECOMPUTE = (
    0x14148CDD0,
    0x141493AA0,
    0x141492790,
    0x141494EA0,
    0x141493E60,
)
EMPTY_STRING = bytes.fromhex("600a0000")


def modern_row(
    *,
    state: int = 3,
    items: tuple[bytes, ...] = (),
    progress_width: int = 4,
    costs: bool = True,
    item_count: int | None = None,
    omit: frozenset[str] = frozenset(),
    cost_byte: bool = False,
    legacy_prefix: bytes = b"",
) -> bytes:
    """Independent wire fields from original source, no production wire parser."""
    out = (0x12345678 & ((1 << (8 * progress_width)) - 1)).to_bytes(progress_width, "little")
    out += struct.pack("<H", state)
    if costs:
        out += struct.pack("<HHH", 11, 12, 13)
    out += legacy_prefix
    if "rowC" not in omit:
        out += struct.pack("<H", 7)
    if "rowE" not in omit:
        out += bytes([8])
    out += EMPTY_STRING * 3
    if "row58" not in omit:
        out += bytes([9])
    if "row6E" not in omit:
        out += struct.pack("<HH", 14, 15)
    if "triplets" not in omit:
        for index in range(3):
            out += struct.pack("<HH", 16 + index, 20 + index)
            out += (24 + index).to_bytes(1 if cost_byte else 2, "little")
        out += struct.pack("<H", 30)
    for name, width, value in (("row74", 4, 31), ("row78", 1, 32), ("row7A", 2, 33)):
        if name not in omit:
            out += value.to_bytes(width, "little")
    out += struct.pack("<H", len(items) if item_count is None else item_count)
    out += b"".join(items) + struct.pack("<H", 34)
    return out


class Fixture:
    """Real owned helpers; mutation hooks are explicitly authored engine effects."""

    def __init__(
        self, wire: bytes, *, count: int = 1, result: bytes = bytes(48), version: int = 0x44E666
    ) -> None:
        self.memory = ReplayMemory(start=SUBJECT, max_bytes=4 << 20)
        self.events: list[tuple[object, ...]] = []
        self.before_call: Callable[[int, tuple[int, ...]], None] | None = None
        self.after_call: Callable[[int, tuple[int, ...], int | None], None] | None = None
        self.on_read: Callable[[int, int, int], None] | None = None
        self.on_write: Callable[[int, int, int], None] | None = None
        self.frame = 0
        self.frame_after = b""
        assert self.memory.allocate(0x58) == SUBJECT
        self.memory.map_bytes(OUTPUT, bytes(48))
        self.memory.map_bytes(STREAM, VTABLE.to_bytes(8, "little"))
        self.memory.map_bytes(VTABLE + 0x18, INPUT.to_bytes(8, "little"))
        self.memory.map_bytes(VERSION, version.to_bytes(4, "little"))
        self.context = ReplayTaskRebuildStorage(SUBJECT, self.read, self.write)
        self.atomics = ReplayUnitAIMapAtomics(
            self.memory.compare_exchange_u32, self.memory.fetch_add_u32
        )
        self.source = ReplaySavedInput(wire)
        self.routes: dict[int, ReplayTaskRebuildCalls] = {}
        self.terminal = self.memory.runtime_calls()
        self.router = ReplayTaskRebuildCalls(self.dispatch)
        for slot, target in (
            (0x143199DB0, 0x142D6BA78),
            (0x143199DD0, 0x142D6BAB4),
            (0x143199930, 0x142D6E3DB),
            (0x143199938, 0x142D6E3B7),
        ):
            self.memory.map_bytes(slot, target.to_bytes(8, "little"))
        self.catalog(CATALOG, count)
        self.route(
            (INPUT,),
            bind_replay_saved_input(
                self.context,
                self.router,
                self.source,
                stream=STREAM,
                target=INPUT,
                result_bytes=result,
            ),
        )
        self.route(
            (0x14090D270,), bind_replay_saved_pair(self.context, self.router, atomics=self.atomics)
        )
        self.route(
            (0x1402B9080, 0x1409076B0),
            bind_replay_saved_apply(
                self.context, self.router, atomics=self.atomics, imports=self.terminal
            ),
        )
        self.route(
            (0x1402BD7F0, 0x1402BD890, 0x140900620),
            bind_replay_saved_result(
                self.context, self.router, atomics=self.atomics, imports=self.terminal
            ),
        )
        self.route(
            (0x140991CE0,),
            bind_replay_player_saved_children(self.context, self.router, imports=self.terminal),
        )
        self.route(
            (0x1408EE150,),
            bind_replay_base_saved_leaves(
                self.context,
                self.router,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=bytes(8),
            ),
        )
        self.route(
            (0x140A1BDF0,),
            bind_replay_de_string_saved(
                self.context,
                self.router,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=ReplayDEStringSavedScratch(bytes(2), bytes(2)),
            ),
        )
        self.route(
            (0x140A1B220,),
            bind_replay_player_civilization_lookup(
                self.context, self.router, bind_local=self.bind_local, scratch=bytes(8)
            ),
        )
        self.route(
            (0x142D6E3B1,),
            bind_replay_unit_constructor_support(
                self.context, self.router, imports=self.terminal, bind_local=self.bind_local
            ),
        )
        storage = bind_replay_research_storage(
            self.context,
            self.router,
            imports=self.terminal,
            bind_local=self.bind_local,
            scratch=ReplayResearchStorageScratch(bytes(8)),
        )
        self.route((0x141492AE0, 0x1414929F0, 0x140B55580, 0x141491C50, 0x1414938A0), storage)

    def route(self, targets: tuple[int, ...], calls: ReplayTaskRebuildCalls) -> None:
        for target in targets:
            self.routes[target] = calls

    def catalog(self, address: int, count: int) -> int:
        size = max(count, 1) * 0x88
        definitions = self.memory.allocate(size)
        for index in range(max(count, 1)):
            self.memory.write_bytes(definitions + index * 0x88 + 0x18, b"\xff" * 12)
        self.memory.map_bytes(
            address,
            definitions.to_bytes(8, "little") + (count & 0xFFFF).to_bytes(2, "little") + bytes(6),
        )
        return definitions

    def read(self, address: int, width: int) -> int:
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.on_read is not None:
            self.on_read(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.on_write is not None:
            self.on_write(address, width, value)

    def dispatch(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("c", target, args, None if data is None else bytes(data)))
        if self.before_call is not None:
            self.before_call(target, args)
        handler = self.routes.get(target, self.terminal).call
        assert handler is not None
        result = handler(target, args, data)
        if self.after_call is not None:
            self.after_call(target, args, result)
        return result

    @contextmanager
    def bind_local(self, view: memoryview) -> Iterator[int]:
        with self.memory.bind_local(view) as address:
            if len(view) == 0x100:
                self.frame = address
            try:
                yield address
            finally:
                if len(view) == 0x100:
                    self.frame_after = bytes(view)

    def run(self, *, mode: int = 0, bound: bool = False) -> int:
        scratch = research.ReplayResearchSavedScratch(b"\xa5" * 0x100)
        if bound:
            calls = research.bind_replay_research_saved(
                self.context,
                self.router,
                atomics=self.atomics,
                bind_local=self.bind_local,
                scratch=scratch,
            )
            assert calls.call is not None
            result = calls.call(ENTRY, (SUBJECT, OUTPUT, STREAM, CATALOG, PLAYER, mode), None)
            assert result is not None
            return result
        return research.read_replay_saved_research(
            self.context,
            SUBJECT,
            OUTPUT,
            STREAM,
            CATALOG,
            PLAYER,
            mode,
            calls=self.router,
            atomics=self.atomics,
            bind_local=self.bind_local,
            scratch=scratch,
        )

    def calls(self, target: int) -> list[tuple[int, ...]]:
        return [row[2] for row in self.events if row[:2] == ("c", target)]

    def version_samples(self, values: dict[int, int]) -> None:
        """Explicit fixture mutation after each read, not source callback semantics."""
        sequence = 0
        self.memory.write(VERSION, 4, values.get(1, 0x44E666))

        def next_sample(address, _width, _value):
            nonlocal sequence
            if address == VERSION:
                sequence += 1
                self.memory.write(VERSION, 4, values.get(sequence + 1, 0x44E666))

        self.on_read = next_sample


@pytest.mark.parametrize("count", [0, 0x8000, 0xFFFF])
@pytest.mark.parametrize("bound", [False, True])
def test_nonpositive_saved_count_still_constructs_reverse_and_skips_mode(count, bound) -> None:
    f = Fixture(struct.pack("<H", count), count=0)
    assert f.run(mode=1, bound=bound) == SUBJECT
    assert f.source.position == 2
    assert f.calls(0x141492AE0) == [(SUBJECT + 0x38, 0)]
    assert not f.calls(0x1414929F0) and not f.calls(RECOMPUTE)
    assert f.memory.read(SUBJECT + 0x28, 8) == CATALOG
    assert f.memory.read(SUBJECT + 0x30, 8) == PLAYER


def test_missing_input_retains_only_reached_header_stores() -> None:
    f = Fixture(b"\0\0", count=0)
    del f.routes[INPUT]
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.source.position == 0
    assert [f.memory.read(SUBJECT + offset, 8) for offset in (0, 8, 16, 24)] == [0, 0, 0, 32]
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.memory.read(SUBJECT + 0x28, 8)


def test_reverse_child_is_required_even_when_saved_count_is_zero() -> None:
    f = Fixture(b"\0\0", count=0)
    del f.routes[0x141492AE0]
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.source.position == 2 and f.memory.read(SUBJECT + 0x28, 8) == CATALOG
    assert f.calls(0x141492AE0) == [(SUBJECT + 0x38, 0)]


def test_first_status_failure_cleans_then_returns_current_home_without_publication() -> None:
    profile = bytearray(48)
    profile[0x18:0x20] = (0xABC).to_bytes(8, "little")
    f = Fixture(b"\0\0", count=0, result=bytes(profile))

    def change_home(target, _args, _result):
        if target == 0x1402BD7F0:
            f.memory.write(f.frame + 0x70, 8, 0x9876)

    f.after_call = change_home
    assert f.run() == 0x9876
    assert f.source.position == 2 and f.memory.read(OUTPUT + 0x18, 8) == 0xABC
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.memory.read(SUBJECT + 0x28, 8)


@pytest.mark.parametrize("bound", [False, True])
def test_actual_modern_input_result_strings_and_storage_compose(bound) -> None:
    wire = b"\1\0" + modern_row()
    f = Fixture(wire)
    assert f.run(bound=bound) == SUBJECT
    assert f.source.position == len(wire) and f.source.remaining == 0
    row = f.memory.read(SUBJECT, 8)
    assert f.memory.read(SUBJECT + 16, 8) == 1
    expected = {
        0: (4, 0x12345678),
        4: (2, 3),
        6: (2, 11),
        8: (2, 12),
        10: (2, 13),
        12: (2, 7),
        14: (1, 8),
        0x58: (1, 9),
        0x6E: (2, 14),
        0x70: (2, 15),
        0x6C: (2, 30),
        0x74: (4, 31),
        0x78: (1, 32),
        0x7A: (2, 33),
        0x7C: (2, 34),
    }
    for offset, (width, value) in expected.items():
        assert f.memory.read(row + offset, width) == value
    for index in range(3):
        for start, value in ((0x5A, 16), (0x60, 20), (0x66, 24)):
            assert f.memory.read(row + start + index * 2, 2) == value + index
    for offset in (0x10, 0x28, 0x40):
        assert f.memory.read(row + offset, 8) == 0x14428BB30
        assert f.memory.read_bytes(row + offset + 8, 16) == bytes(16)
    for padding in (0xF, 0x59, 0x72, 0x73, 0x79, 0x7E, 0x7F):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            f.memory.read(row + padding, 1)
    assert len(f.calls(INPUT)) == 32
    cost_args = [args for args in f.calls(INPUT) if row + 0x66 <= args[2] <= row + 0x6A]
    assert [(args[1], args[3]) for args in cost_args] == [(f.frame + 0xB8, 2)] * 3
    assert len([event for event in f.events if event[:3] == ("r", VERSION, 4)]) == 17


def test_duplicate_prerequisites_use_actual_reserve_copy_and_ordered_append() -> None:
    f = Fixture(b"\0\0")
    definitions = f.memory.read(CATALOG, 8)
    f.memory.write_bytes(definitions + 0x18, bytes(12))
    assert f.run() == SUBJECT
    reverse = f.memory.read(SUBJECT + 0x38, 8)
    assert f.memory.read(reverse + 16, 8) == 6
    assert f.memory.read(reverse + 8, 8) == 8
    assert f.memory.read_bytes(f.memory.read(reverse, 8), 24) == bytes(24)
    assert [args[1] for args in f.calls(0x140B55580)] == [1, 2, 4, 8]


def test_more_saved_than_dat_rows_preserves_allocated_rows_but_updates_saved_word() -> None:
    f = Fixture(b"\2\0" + modern_row() * 2)
    assert f.run() == SUBJECT
    assert f.memory.read(SUBJECT + 0x20, 2) == 1
    assert f.memory.read(SUBJECT + 16, 8) == 2 and not f.calls(RECONCILE)


def test_missing_reconcile_preserves_completed_rows_and_saved_count() -> None:
    f = Fixture(b"\1\0" + modern_row(), count=2)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.calls(RECONCILE) == [(SUBJECT, 1)]
    assert f.source.remaining == 0 and f.memory.read(SUBJECT + 0x20, 2) == 1


@pytest.mark.parametrize("state,frontier", [(3, CHANGE), (2, RECOMPUTE)])
def test_mode_effects_are_actual_required_calls_after_state_store(state, frontier) -> None:
    f = Fixture(b"\1\0" + modern_row(state=state))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run(mode=1)
    assert f.source.remaining == 0 and len(f.calls(frontier)) == 1
    row = f.memory.read(SUBJECT, 8)
    assert f.memory.read(row + 4, 2) == (1 if state == 3 else 2)


def test_only_low_mode_byte_is_consumed() -> None:
    f = Fixture(b"\1\0" + modern_row())
    assert f.run(mode=0x100) == SUBJECT and not f.calls(CHANGE) and not f.calls(RECOMPUTE)


def test_modern_row_owner_and_stream_are_held_but_return_home_is_current() -> None:
    f = Fixture(b"\1\0" + modern_row())

    def mutate(target, args, _result):
        if target == INPUT and args[3] == 4 and args[2] == f.memory.read(SUBJECT, 8):
            f.memory.write(f.frame + 0x70, 8, 0x7777)
            f.memory.write(f.frame + 0x80, 8, 0x8888)

    f.after_call = mutate
    assert f.run() == 0x7777 and f.source.remaining == 0
    assert all(args[0] == STREAM for args in f.calls(INPUT))


@pytest.mark.parametrize("bound", [False, True])
def test_progress_target_is_held_before_version_read_then_later_input_target_is_current(bound):
    f = Fixture(b"\1\0" + modern_row())
    alternate = INPUT + 1
    f.route(
        (alternate,),
        bind_replay_saved_input(
            f.context, f.router, f.source, stream=STREAM, target=alternate, result_bytes=bytes(48)
        ),
    )

    def mutate(address, _width, _value):
        if address == VERSION:
            f.memory.write(VTABLE + 0x18, 8, alternate)

    f.on_read = mutate
    assert f.run(bound=bound) == SUBJECT and f.source.remaining == 0
    assert [args[3] for args in f.calls(INPUT)] == [2, 4]
    assert len(f.calls(alternate)) == 30


def test_final_catalog_home_is_current_and_negative_dat_count_is_not_clamped() -> None:
    f = Fixture(b"\1\0" + modern_row())
    alternate = 0x7000
    f.catalog(alternate, -1)

    def mutate(target, args, _result):
        if target == INPUT and args[2] == f.memory.read(SUBJECT, 8) + 0x7C:
            f.memory.write(f.frame + 0x88, 8, alternate)

    f.after_call = mutate
    assert f.run() == SUBJECT
    assert f.memory.read(SUBJECT + 0x20, 2) == 0xFFFF and not f.calls(RECONCILE)


def test_strings_have_cleanup_but_no_added_parent_status_forward_or_check() -> None:
    f = Fixture(b"\1\0" + modern_row())

    def annotate(target, args, _result):
        if target == 0x140A1BDF0:
            f.memory.write(args[1] + 0x18, 8, 0xBAD)

    f.after_call = annotate
    assert f.run() == SUBJECT and f.source.remaining == 0
    assert f.memory.read(OUTPUT + 0x18, 8) == 0


@pytest.mark.parametrize("width,initial", [(2, 0x707AE), (4, 0x707AF)])
def test_progress_threshold_holds_selected_width_before_later_current_versions(
    width,
    initial,
) -> None:
    f = Fixture(b"\1\0" + modern_row(progress_width=width), version=initial)

    def change(address, _width, _value):
        if address == VERSION:
            f.memory.write(VERSION, 4, 0x44E666)

    f.on_read = change
    assert f.run() == SUBJECT and f.source.remaining == 0
    assert f.calls(INPUT)[1][3] == width


@pytest.mark.parametrize("include,threshold", [(False, 0xA1709), (True, 0xA170A)])
def test_cost_gate_uses_its_own_current_version_sample(include, threshold) -> None:
    f = Fixture(b"\1\0" + modern_row(costs=include))
    versions = 0

    def change(address, _width, _value):
        nonlocal versions
        if address == VERSION:
            versions += 1
            f.memory.write(VERSION, 4, threshold if versions == 1 else 0x44E666)

    f.on_read = change
    assert f.run() == SUBJECT and f.source.remaining == 0
    row = f.memory.read(SUBJECT, 8)
    expected = [11, 12, 13] if include else [0] * 3
    assert [f.memory.read(row + at, 2) for at in (6, 8, 10)] == expected


@pytest.mark.parametrize(
    "tag,integer,raw", [(0, 0, 0), (0xFF, 0xFFFFFFFF, 0x7FC01234), (0x80, 0x80000000, 0x80000000)]
)
def test_modern_item_reaches_real_six_pointer_frontier_after_all_13_bytes(
    tag,
    integer,
    raw,
) -> None:
    item = struct.pack("<HHBII", 0xFFFF, 0xFFFE, tag, integer, raw)
    f = Fixture(b"\1\0" + modern_row(items=(item,)))
    seen = []

    def inspect(target, args):
        if target == APPEND:
            seen.append(
                tuple(
                    f.memory.read(pointer, width)
                    for pointer, width in zip(args[1:], (2, 2, 1, 4, 4), strict=True)
                )
            )

    f.before_call = inspect
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert seen == [(0xFFFF, 0xFFFE, tag, integer, raw)]
    assert f.source.remaining == 2 and len(f.calls(APPEND)[0]) == 6
    assert int.from_bytes(f.frame_after[0x20:0x28], "little") == f.frame + 0xFC
    assert int.from_bytes(f.frame_after[0x28:0x30], "little") == f.frame + 0xF8


def test_truncated_last_word_retains_completed_modern_rows_and_input_cursor() -> None:
    wire = b"\1\0" + modern_row()
    f = Fixture(wire[:-1])
    with pytest.raises(UnresolvedReplayTaskRebuild, match="remaining"):
        f.run()
    assert f.source.position == len(wire) - 2
    row = f.memory.read(SUBJECT, 8)
    assert f.memory.read(row + 0x7A, 2) == 33 and f.memory.read(row + 0x7C, 2) == 0xFFFF


@pytest.mark.parametrize(
    "name,sample,version,fields",
    [
        ("rowE", 4, 0xD1C27, ((0xE, 1, 1),)),
        ("row58", 8, 0xD4A3C, ((0x58, 1, 0),)),
        ("row6E", 9, 0x193D6F, ((0x6E, 2, 0xFFFF), (0x70, 2, 0xFFFF))),
        (
            "triplets",
            10,
            0x141709,
            ((0x5A, 2, 0xFFFF), (0x60, 2, 0xFFFF), (0x66, 2, 0xFFFE), (0x6C, 2, 0xFFFF)),
        ),
        ("row74", 14, 0x1A0F5B, ((0x74, 4, 1),)),
        ("row78", 15, 0x281998, ((0x78, 1, 0),)),
        ("row7A", 16, 0x3FB332, ((0x7A, 2, 0xFFFF),)),
    ],
)
def test_independent_legacy_field_skips_consume_no_bytes_and_write_source_defaults(
    name,
    sample,
    version,
    fields,
) -> None:
    f = Fixture(b"\1\0" + modern_row(omit=frozenset({name})))
    f.version_samples({sample: version})
    assert f.run() == SUBJECT and f.source.remaining == 0
    row = f.memory.read(SUBJECT, 8)
    for offset, width, value in fields:
        assert f.memory.read(row + offset, width) == value


def test_cost66_byte_branches_use_primary_result_and_leave_existing_high_bytes() -> None:
    f = Fixture(b"\1\0" + modern_row(cost_byte=True))
    f.version_samples({11: 0x1911EA, 12: 0x1911EA, 13: 0x1911EA})
    assert f.run() == SUBJECT and f.source.remaining == 0
    row = f.memory.read(SUBJECT, 8)
    for index in range(3):
        assert f.memory.read(row + 0x66 + index * 2, 2) == 24 + index
    cost_args = [args for args in f.calls(INPUT) if row + 0x66 <= args[2] <= row + 0x6A]
    assert [(args[1], args[3]) for args in cost_args] == [(f.frame + 0x38, 1)] * 3


@pytest.mark.parametrize(
    "sample,version,frontier,bytes_before",
    [
        (5, 0xD451D, 0x140A15BF0, 17),
        (6, 0xD47AD, 0x140A15BF0, 21),
        (7, 0x441998, 0x140A1A7E0, 25),
    ],
)
def test_old_string_fallbacks_refuse_at_real_required_child(
    sample,
    version,
    frontier,
    bytes_before,
):
    f = Fixture(b"\1\0" + modern_row())
    f.version_samples({sample: version})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.source.position == bytes_before and len(f.calls(frontier)) == 1


@pytest.mark.parametrize(
    "prefix,samples",
    [
        (b"", {3: 0xA7332}),
        (b"\x34\x12", {3: 0xA7333, 4: 0xCEE13}),
        (b"\x34\x12\x56\x78\x9a", {3: 0xCEE14, 4: 0xCEE14, 5: 0xD1709}),
    ],
)
def test_held_legacy_version_and_dat_pointer_seed_differ_from_later_current_version(
    prefix,
    samples,
):
    f = Fixture(b"\1\0" + modern_row(omit=frozenset({"rowC"}), legacy_prefix=prefix))
    definitions = f.memory.read(CATALOG, 8)
    legacy = f.memory.allocate(5)
    f.memory.write_bytes(legacy, b"\xbc\xde\xa5\xa5\xef")
    f.memory.write(definitions + 0x70, 8, legacy)
    f.version_samples(samples)
    assert f.run() == SUBJECT and f.source.remaining == 0
    row = f.memory.read(SUBJECT, 8)
    assert f.memory.read(row + 0xC, 2) == 1
    assert int.from_bytes(f.frame_after[0xF8:0xFC], "little") == (0x1234 if prefix else 0)
    assert int.from_bytes(f.frame_after[0xF0:0xF2], "little") == 0xFFFF
    if len(prefix) == 5:
        assert f.frame_after[0xE8] == 0x56
        assert int.from_bytes(f.frame_after[0xEC:0xEE], "little") == 0x9A78
    else:
        assert f.frame_after[0xE8] == 0xEF
        assert int.from_bytes(f.frame_after[0xEC:0xEE], "little") == 0xDEBC


@pytest.mark.parametrize("count", [0x8000, 0xFFFF])
def test_negative_modern_item_count_skips_loop_but_reads_trailing_word(count) -> None:
    f = Fixture(b"\1\0" + modern_row(item_count=count))
    assert f.run() == SUBJECT and f.source.remaining == 0 and not f.calls(APPEND)
    assert f.memory.read(f.memory.read(SUBJECT, 8) + 0x7C, 2) == 34


def test_control_release_failure_retains_real_pair_stores_before_current_virtual() -> None:
    f = Fixture(b"\0\0", count=0)
    control, vtable = f.memory.allocate(16), f.memory.allocate(16)
    f.memory.write(control, 8, vtable)
    f.memory.write(control + 8, 4, 0)
    f.memory.write(control + 12, 4, 1)
    f.memory.write(vtable, 8, 0xFA11)
    f.memory.write(vtable + 8, 8, 0xFA12)
    old = f.routes[INPUT].call
    assert old is not None

    def actual_then_annotate(target, args, data):
        result = old(target, args, data)
        f.memory.write(args[1] + 0x20, 8, control)
        return result

    f.routes[INPUT] = ReplayTaskRebuildCalls(actual_then_annotate)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert f.source.position == 2
    assert f.memory.read(OUTPUT + 0x20, 8) == control
    assert f.memory.read(control + 8, 4) == 0
    assert f.memory.read(control + 12, 4) == 1
    assert f.calls(0xFA11) == [(control,)] and not f.calls(0x1402BD7F0)


def test_legacy_inline_append_preserves_three_unwritten_bytes_without_commit_substitute() -> None:
    wire = b"\1\0" + modern_row()[:-4]
    f = Fixture(wire)
    payload = f.memory.allocate(16)
    f.memory.fill(payload, 0xD3, 16)

    def prepare(target, _args, _result):
        if target == 0x1414929F0:
            row = f.memory.read(SUBJECT, 8)
            for offset, value in ((0x80, payload), (0x88, payload), (0x90, payload + 16)):
                f.memory.write(row + offset, 8, value)

    versions = 0

    def final_legacy(address, _width, _value):
        nonlocal versions
        if address == VERSION:
            versions += 1
            if versions == 16:
                f.memory.write(VERSION, 4, 0x41B332)

    f.after_call, f.on_read = prepare, final_legacy
    assert f.run() == SUBJECT and f.source.remaining == 0
    assert f.memory.read_bytes(payload, 16) == bytes.fromhex("ffffffff00d3d3d3ffffffff00000000")
    assert f.memory.read(f.memory.read(SUBJECT, 8) + 0x88, 8) == payload + 16
    assert not f.calls(COMMIT) and not f.calls(APPEND)


def test_legacy_growth_requires_actual_commit_after_allocator_and_tail_move() -> None:
    f = Fixture(b"\1\0" + modern_row()[:-4])
    versions = 0

    def final_legacy(address, _width, _value):
        nonlocal versions
        if address == VERSION:
            versions += 1
            if versions == 16:
                f.memory.write(VERSION, 4, 0x41B332)

    f.on_read = final_legacy
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.run()
    assert len(f.calls(COMMIT)) == 1 and f.source.remaining == 0
    header, allocation, count, capacity = f.calls(COMMIT)[0]
    assert count == capacity == 1
    assert f.memory.read(allocation, 2) == 0xFFFF
    assert f.memory.read(allocation + 12, 4) == 0
    with pytest.raises(ReplayMemoryError, match="undefined"):
        f.memory.read(allocation + 5, 1)
    assert f.calls(0x142D6E3DB)[-1] == (allocation, 0, 0)
    assert f.memory.read(header + 8, 8) == 0


@pytest.mark.parametrize("payload", [bytes(0), bytes(255), bytes(257), bytearray(256)])
def test_explicit_frame_seed_shape_is_required(payload) -> None:
    with pytest.raises(ValueError):
        research.ReplayResearchSavedScratch(payload)


@pytest.mark.parametrize(
    "args,data",
    [
        ((SUBJECT,) * 5, None),
        ((SUBJECT,) * 7, None),
        ((SUBJECT,) * 6, memoryview(bytearray(1))),
        ((SUBJECT, OUTPUT, STREAM, CATALOG, PLAYER, -1), None),
    ],
)
def test_bound_entry_rejects_bad_arity_data_or_unsigned_scalars_before_effects(args, data) -> None:
    f = Fixture(b"\0\0", count=0)
    bound = research.bind_replay_research_saved(
        f.context,
        f.router,
        atomics=f.atomics,
        bind_local=f.bind_local,
        scratch=research.ReplayResearchSavedScratch(bytes(256)),
    )
    assert bound.call is not None
    with pytest.raises(ValueError):
        bound.call(ENTRY, args, data)
    assert f.events == [] and f.source.position == 0


def test_unknown_bound_target_delegates_exact_payload_and_return() -> None:
    f = Fixture(b"", count=0)
    payload, seen = memoryview(bytearray(b"xy")), []

    def lower(target, args, data):
        seen.append((target, args, data))
        return 77

    bound = research.bind_replay_research_saved(
        f.context,
        ReplayTaskRebuildCalls(lower),
        atomics=f.atomics,
        bind_local=f.bind_local,
        scratch=research.ReplayResearchSavedScratch(bytes(256)),
    )
    assert bound.call is not None and bound.call(9, (1, 2), payload) == 77
    assert seen == [(9, (1, 2), payload)] and f.events == []
