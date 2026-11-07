"""Source-derived owned controls; opaque helper programs are component fixtures."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vantage.replay_base_saved_registration import (
    ReplayBaseSavedRegistrationFP,
    ReplayBaseSavedRegistrationScratch,
    bind_replay_base_saved_registration,
)
from vantage.replay_memory import ReplayMemory
from vantage.replay_player_base_children import (
    ReplayPlayerBaseChildrenScratch,
    bind_replay_player_base_children,
    create_replay_player_catalog,
    move_replay_player_catalog,
    read_replay_player_index,
    release_replay_player_catalog,
)
from vantage.replay_player_wire_factory import (
    ReplayPlayerWireFactoryScratch,
    bind_replay_player_wire_factory,
)
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

SCRATCH = ReplayPlayerBaseChildrenScratch(b"\xa5" * 0x78, b"\x96" * 0x60)
IO = 0x515151


class Harness:
    def __init__(self) -> None:
        self.memory = ReplayMemory()
        self.player = self.memory.allocate(0x800)
        self.memory.write_bytes(self.player, b"\xa5" * 0x800)
        self.context = ReplayTaskRebuildStorage(self.player, self.memory.read, self.memory.write)
        self.atomics = ReplayUnitAIMapAtomics(
            self.memory.compare_exchange_u32, self.memory.fetch_add_u32
        )
        self.events: list[tuple[int, tuple[int, ...]]] = []
        self.programs: dict[int, Callable[[tuple[int, ...]], int | None]] = {}
        self.runtime = self.memory.runtime_calls()
        self.lower = ReplayTaskRebuildCalls(self.dispatch)
        self.bound = bind_replay_player_base_children(
            self.context,
            self.lower,
            atomics=self.atomics,
            bind_local=self.memory.bind_local,
            scratch=SCRATCH,
            imports=self.lower,
        )

    def allocate(self, size: int, byte: int = 0) -> int:
        pointer = self.memory.allocate(size)
        self.memory.write_bytes(pointer, bytes([byte]) * size)
        return pointer

    def dispatch(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append((target, args))
        if target in self.programs:
            return self.programs[target](args)
        assert self.runtime.call
        return self.runtime.call(target, args, data)

    def call(self, target: int, *args: int) -> int | None:
        assert self.bound.call
        return self.bound.call(target, args, None)


@pytest.mark.parametrize("byte_size,scalar_size", [(0, 0x60), (0x77, 0x60), (0x78, 0x61)])
def test_explicit_scratch(byte_size: int, scalar_size: int) -> None:
    with pytest.raises(ValueError):
        ReplayPlayerBaseChildrenScratch(bytes(byte_size), bytes(scalar_size))


@pytest.mark.parametrize("word", [0, 1, 0x80000000, 0xFFFFFFFF])
def test_actual_id_leaf(word: int) -> None:
    h = Harness()
    resource = h.allocate(24)
    h.memory.write(resource + 20, 4, word)
    assert h.call(0x140F6BD90, resource) == word
    assert not h.events


@pytest.mark.parametrize(
    "target,arity",
    [
        (0x141711C20, 6),
        (0x141712290, 6),
        (0x141712390, 6),
        (0x141711BF0, 2),
        (0x141712AE0, 2),
        (0x141727C80, 2),
        (0x14174A0C0, 2),
        (0x14174A2C0, 2),
        (0x140F6BD90, 1),
    ],
)
def test_exact_bound_arity(target: int, arity: int) -> None:
    h = Harness()
    with pytest.raises(ValueError):
        h.call(target, *([0] * (arity - 1)))
    assert not h.events


def test_unknown_delegate_is_real() -> None:
    h = Harness()
    h.programs[123] = lambda args: args[0] + 1
    assert h.call(123, 9) == 10
    with pytest.raises(UnresolvedReplayTaskRebuild):
        h.call(124)


def test_move_identity_and_source_before_destination() -> None:
    h = Harness()
    slot = h.allocate(8)
    h.memory.write(slot, 8, 0x1234)
    assert move_replay_player_catalog(h.context, slot, slot, calls=h.lower) == slot
    assert h.memory.read(slot, 8) == 0x1234 and not h.events
    destination = h.allocate(8)
    h.memory.write(destination, 8, 0xABCD)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1417178d0"):
        h.call(0x141711BF0, destination, slot)
    assert h.memory.read(slot, 8) == 0
    assert h.memory.read(destination, 8) == 0x1234
    assert h.events[-1] == (0x1417178D0, (0xABCD + 0x70,))


def test_allocation_zero_skips_count_read() -> None:
    h = Harness()
    output = h.allocate(8, 0xEE)
    h.programs[0x142D6BA78] = lambda args: 0
    assert create_replay_player_catalog(h.context, output, 0xDEAD, calls=h.lower) == output
    assert h.memory.read(output, 8) == 0
    assert h.events == [(0x142D6BA78, (0xB8,))]


def test_constructor_rereads_count_after_real_zero_and_publishes_actual_return() -> None:
    h = Harness()
    output, count, actual = h.allocate(8), h.allocate(4), h.allocate(8)
    h.memory.write(count, 4, 17)

    def zero(args: tuple[int, ...]) -> None:
        assert h.runtime.call
        h.runtime.call(0x142D6E3B7, args, None)
        h.memory.write(count, 4, 0xFFFFFFFF)

    def constructor(args: tuple[int, ...]) -> int:
        assert args[1] == 0xFFFFFFFF
        assert h.memory.read_bytes(args[0], 0xB8) == bytes(0xB8)
        return actual

    h.programs[0x142D6E3B7] = zero
    h.programs[0x141119BE0] = constructor  # Explicit isolated required-child effect.
    assert h.call(0x141712AE0, output, count) == output
    assert h.memory.read(output, 8) == actual


def test_missing_constructor_keeps_allocation_zeroing_and_prior_output() -> None:
    h = Harness()
    output, count = h.allocate(8, 0xEE), h.allocate(4)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141119be0"):
        h.call(0x141712AE0, output, count)
    allocation = h.events[-2][1][0]
    assert h.memory.read_bytes(allocation, 0xB8) == bytes(0xB8)
    assert h.memory.read_bytes(output, 8) == b"\xee" * 8


def test_null_release_does_not_read_ignored_holder() -> None:
    h = Harness()
    release_replay_player_catalog(h.context, 0xDEAD, 0, calls=h.lower)
    assert not h.events


def test_actual_outer_release_empty_chain_and_ignored_holder() -> None:
    h = Harness()
    obj, head, holder = h.allocate(0xB8), h.allocate(0x38), h.allocate(8, 0xEE)
    h.memory.write(obj + 8, 8, head)
    h.memory.write(head, 8, head)
    h.memory.write(head + 8, 8, head)
    h.programs[0x1417178D0] = lambda args: None  # Isolated nested-map fixture only.
    assert h.call(0x141727C80, holder, obj) is None
    assert h.memory.read_bytes(holder, 8) == b"\xee" * 8
    assert h.events == [
        (0x1417178D0, (obj + 0x70,)),
        (0x142D6BAB4, (head, 0x38)),
        (0x142D6BAB4, (obj, 0xB8)),
    ]


def test_release_held_next_and_current_head_after_free_callback() -> None:
    h = Harness()
    obj, head, replacement = h.allocate(0xB8), h.allocate(0x38), h.allocate(0x38)
    first, second = h.allocate(0x38), h.allocate(0x38)
    h.memory.write(obj + 8, 8, head)
    h.memory.write(head, 8, first)
    h.memory.write(head + 8, 8, second)
    h.memory.write(first, 8, second)
    h.memory.write(second, 8, head)
    h.programs[0x1417178D0] = lambda args: None

    def free(args: tuple[int, ...]) -> None:
        if args[0] == first:
            h.memory.write(first, 8, 0xBAD)  # Held-next already captured.
            h.memory.write(obj + 8, 8, replacement)
        assert h.runtime.call
        h.runtime.call(0x142D6BAB4, args, None)

    h.programs[0x142D6BAB4] = free
    h.call(0x141727C80, 0, obj)
    assert [args[0] for target, args in h.events if target == 0x142D6BAB4] == [
        first,
        second,
        replacement,
        obj,
    ]
    assert h.memory.read(head, 8) == first  # Old sentinel was not guessed as current.


def test_release_watson_current_terminal_preserves_prior_clear() -> None:
    h = Harness()
    obj = h.allocate(0xB8)
    allocation = h.allocate(0x2000)
    pointer = allocation + 0x100
    h.memory.write(pointer - 8, 8, allocation)
    h.memory.write(obj + 0x18, 8, pointer)
    h.memory.write(obj + 0x28, 8, pointer + 0x1000)
    h.memory.map_bytes(0x14319A060, (0x140F6BD90).to_bytes(8, "little"))
    h.programs[0x1417178D0] = lambda args: None
    h.programs[0x140F6BD90] = lambda args: None  # Terminal alias must bypass owned leaf.
    with pytest.raises(UnresolvedReplayTaskRebuild, match="INT3"):
        h.call(0x141727C80, 0, obj)
    assert h.events[-1] == (0x140F6BD90, (0, 0, 0, 0, 0))
    assert h.memory.read(obj + 0x40, 8) == 0
    assert h.memory.read(obj + 0x18, 8) == pointer


@pytest.mark.parametrize("index", [-1, 0, 1])
def test_civilization_real_id_leaf_signed_index_and_current_world(index: int) -> None:
    h = Harness()
    resource, world, table = h.allocate(24), h.allocate(0x118), h.allocate(32)
    h.memory.write(resource + 20, 4, index & 0xFFFFFFFF)
    h.memory.write(h.player + 8, 8, world)
    h.memory.write(world + 0x110, 8, table + 8)
    h.memory.write(table + 8 + index * 8, 8, 0xF00D)
    h.call(0x14174A0C0, h.player, resource)
    assert h.memory.read(h.player + 0x6A8, 8) == resource
    assert h.memory.read(h.player + 0x6A0, 8) == 0xF00D
    assert not h.events


def reader_chain(h: Harness, data: bytes) -> tuple[ReplayTaskRebuildCalls, int, ReplaySavedInput]:
    stream, table = h.allocate(8), h.allocate(32)
    h.memory.write(stream, 8, table)
    h.memory.write(table + 24, 8, IO)
    source = ReplaySavedInput(data)
    lower = bind_replay_saved_input(
        h.context, h.lower, source, stream=stream, target=IO, result_bytes=bytes(48)
    )
    lower = bind_replay_saved_apply(h.context, lower, atomics=h.atomics)
    lower = bind_replay_saved_result(h.context, lower, atomics=h.atomics)
    lower = bind_replay_player_wire_factory(
        h.context,
        lower,
        atomics=h.atomics,
        bind_local=h.memory.bind_local,
        scratch=ReplayPlayerWireFactoryScratch(bytes(0x78), bytes(0x60), bytes(0x118)),
    )
    bound = bind_replay_player_base_children(
        h.context,
        lower,
        atomics=h.atomics,
        bind_local=h.memory.bind_local,
        scratch=SCRATCH,
        imports=h.lower,
    )
    return bound, stream, source


@pytest.mark.parametrize("raw", [b"\x00", b"\x7f", b"\xff"])
def test_index_actual_input_byte_wrapper_and_cleanup(raw: bytes) -> None:
    h = Harness()
    bound, stream, source = reader_chain(h, raw)
    out, destination = h.allocate(48, 0xEE), h.allocate(4, 0xFF)
    assert bound.call
    assert bound.call(0x141711C20, (out, 1, 2, 3, stream, destination), None) == out
    assert source.position == 1
    assert h.memory.read(destination, 4) == raw[0]
    assert h.memory.read_bytes(out, 48) == bytes(41) + b"\xee" * 7


@pytest.mark.parametrize("raw", [bytes(4), b"\x00\x00\x00\x80", b"\xff" * 4])
def test_name_mode_actual_current_input_and_cleanup(raw: bytes) -> None:
    h = Harness()
    bound, stream, source = reader_chain(h, raw)
    out, destination = h.allocate(48, 0xEE), h.allocate(4, 0xFF)
    assert bound.call
    assert bound.call(0x141712390, (out, 1, 2, 3, stream, destination), None) == out
    assert source.position == 4 and h.memory.read_bytes(destination, 4) == raw
    assert h.memory.read_bytes(out, 48) == bytes(48)


def test_index_current_byte_after_cleanup() -> None:
    h = Harness()
    out, destination = h.allocate(48), h.allocate(4)
    raw_slot = []

    def child(args: tuple[int, ...]) -> None:
        raw_slot.append(args[-1])
        h.memory.write(args[-1], 1, 3)

    def cleanup(args: tuple[int, ...]) -> None:
        h.memory.write(raw_slot[0], 1, 0xFE)

    h.programs[0x140DAF040] = child
    h.programs[0x1402BD7F0] = cleanup
    assert (
        read_replay_player_index(
            h.context,
            out,
            1,
            2,
            3,
            0,
            destination,
            calls=h.lower,
            atomics=h.atomics,
            bind_local=h.memory.bind_local,
            scratch=SCRATCH.byte_reader,
        )
        == out
    )
    assert h.memory.read(destination, 4) == 0xFE


def test_delegated_reader_requires_real_child_and_preserves_output_on_failure() -> None:
    h = Harness()
    out = h.allocate(48, 0xEE)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140e6a9c0"):
        h.call(0x141712290, out, 1, 2, 3, 4, 5)
    assert h.memory.read_bytes(out, 48) == b"\xee" * 48
    target, args = h.events[-1]
    assert target == 0x140E6A9C0 and args[1:] == (4, 5)


def color_setup(h: Harness, index: int, override: int, mode: int = 0) -> dict[int, int]:
    world, game, mode_ptr, colors, settings = (
        h.allocate(size) for size in (0x120, 0x568, 16, 64, 0x160)
    )
    selected = h.allocate(16)
    h.memory.write(selected + 4, 4, 2)
    h.memory.write(colors + 8, 8, selected)
    h.memory.write(world + 0xE8, 8, colors)
    h.memory.write(h.player + 8, 8, world)
    h.memory.write(h.player + 0x648, 4, index)
    h.memory.write(game + 0x560, 8, mode_ptr)
    h.memory.write(mode_ptr + 8, 4, 4)  # Actual existing getter skips first relation block.
    h.memory.write(settings + 0x151, 1, 1)
    h.memory.map_bytes(0x144353698, game.to_bytes(8, "little"))
    h.memory.map_bytes(0x14425B930, settings.to_bytes(8, "little"))
    h.memory.map_bytes(0x1444167AF, b"\x55")
    h.memory.map_bytes(0x1440955E5, b"\x77")
    h.memory.map_bytes(0x1440955E4, b"\x88")
    values = {}
    for table in (0x1432F46B0, 0x1432F46F0, 0x1432F4730, 0x1432F4770):
        for offset in range(-4 if table == 0x1432F46B0 else 0, 64, 4):
            value = (table + offset) & 0xFFFFFFFF
            values[table + offset] = value
            h.memory.map_bytes(table + offset, value.to_bytes(4, "little"))
    h.programs[0x14097FB40] = lambda args: override & 0xFFFFFFFF if args[1] == 0x49 else mode
    lower = bind_replay_base_saved_registration(
        h.context,
        h.lower,
        imports=h.lower,
        fp_calls=ReplayBaseSavedRegistrationFP(None),
        bind_local=h.memory.bind_local,
        scratch=ReplayBaseSavedRegistrationScratch(bytes(0xB0)),
    )
    h.bound = bind_replay_player_base_children(
        h.context,
        lower,
        atomics=h.atomics,
        bind_local=h.memory.bind_local,
        scratch=SCRATCH,
        imports=h.lower,
    )
    return values


@pytest.mark.parametrize(
    "index,override,mode",
    [
        (0, 0, 0),
        (0, 1, 0),
        (1, 0, 0),
        (1, 0, 1),
        (1, 0, 2),
        (1, 0, 3),
        (1, 0, 4),
        (1, 1, 0),
        (1, -1, 0),
        (1, -0x80000000, 0),
        (1, 2, 0),
        (1, 16, 0),
        (1, 17, 0),
    ],
)
def test_color_existing_mode_getter_and_raw_setting_tables(
    index: int,
    override: int,
    mode: int,
) -> None:
    h = Harness()
    values = color_setup(h, index, override, mode)
    h.call(0x14174A2C0, h.player, 1)
    palette = {1: 0x1432F4730, 2: 0x1432F46F0, 3: 0x1432F4770}.get(mode, 0x1432F46B0)
    baseline = 255 if not index else values[palette + 12]
    if override == 1:
        expected, flag = 0x77, 0x88
    elif override == 0:
        expected, flag = baseline, 0x55
    else:
        offset = min(override, 16) if override >= 0 else 0
        expected, flag = values[0x1432F46B0 + offset * 4 - 4], 0x55
    assert h.memory.read(h.player + 0x650, 4) == expected
    assert h.memory.read(h.player + 0x654, 4) == flag
    assert h.memory.read(h.player + 0x658, 4) == baseline
    assert not any(target == 0x140D6A940 for target, _ in h.events)


def test_color_missing_current_setting_stops_after_initial_pointer_writes() -> None:
    h = Harness()
    color_setup(h, 1, 0)
    h.programs.pop(0x14097FB40)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="14097fb40"):
        h.call(0x14174A2C0, h.player, 1)
    assert h.memory.read(h.player + 0x1F8, 8) == h.memory.read(h.player + 0x200, 8)
    assert h.memory.read(h.player + 0x650, 4) == 0xA5A5A5A5


@pytest.mark.parametrize(
    "relation,same,slot",
    [(0, 0, 3), (1, 0, 6), (2, 0, 1), (3, 0, 1), (4, 0, 1), (255, 0, 1), (2, 255, 0)],
)
def test_color_relation_override_and_raw_AL(relation: int, same: int, slot: int) -> None:
    h = Harness()
    values = color_setup(h, 1, 0)
    game = h.memory.read(0x144353698, 8)
    h.memory.write(h.memory.read(game + 0x560, 8) + 8, 4, 0)
    world = h.memory.read(h.player + 8, 8)
    colors = h.memory.read(world + 0xE8, 8)
    for current in (0, 3, 6):
        pointer = h.allocate(16)
        h.memory.write(pointer + 4, 4, current)
        h.memory.write(colors + current * 8, 8, pointer)
    human, relations = h.allocate(0x188), h.allocate(4)
    h.memory.write(human + 0x180, 8, relations)
    h.memory.write(relations + 1, 1, relation)
    h.programs[0x141603D70] = lambda args: human
    h.programs[0x141734F30] = lambda args: same
    h.call(0x14174A2C0, h.player, 1)
    chosen = h.memory.read(colors + slot * 8, 8)
    assert h.memory.read(h.player + 0x1F8, 8) == chosen
    assert h.memory.read(h.player + 0x200, 8) == h.memory.read(colors + 8, 8)
    index = h.memory.read(chosen + 4, 4)
    assert h.memory.read(h.player + 0x658, 4) == values[0x1432F46B0 + 4 + index * 4]


def test_color_reloads_global_after49_but_holds_its_new_pointer() -> None:
    h = Harness()
    values = color_setup(h, 1, 0)
    original = h.memory.read(0x14425B930, 8)
    replacement = h.allocate(0x160)
    h.memory.write(replacement + 0x151, 1, 1)

    def setting(args: tuple[int, ...]) -> int:
        if args[1] == 0x49:
            assert args[0] == original
            h.memory.write(0x14425B930, 8, replacement)
            return 0
        assert args == (replacement, 0x3C)
        return 2

    h.programs[0x14097FB40] = setting
    h.call(0x14174A2C0, h.player, 1)
    assert h.memory.read(h.player + 0x650, 4) == values[0x1432F46F0 + 12]


def test_index_error_reads_three_literals_then_stops_before_cleanup() -> None:
    h = Harness()
    out, destination = h.allocate(48, 0xEE), h.allocate(4, 0xAA)
    for literal in (0x14325DF50, 0x14325D6D0, 0x14325DE60):
        h.memory.map_bytes(literal, bytes(16))
    reads = []

    def read(address: int, width: int) -> int:
        reads.append((address, width))
        return h.memory.read(address, width)

    def child(args: tuple[int, ...]) -> None:
        h.memory.write(args[0] + 24, 8, 1)

    h.programs[0x140DAF040] = child
    context = ReplayTaskRebuildStorage(h.player, read, h.memory.write)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="GS58"):
        read_replay_player_index(
            context,
            out,
            1,
            2,
            3,
            0,
            destination,
            calls=h.lower,
            atomics=h.atomics,
            bind_local=h.memory.bind_local,
            scratch=SCRATCH.byte_reader,
        )
    assert reads[-3:] == [(0x14325DF50, 16), (0x14325D6D0, 16), (0x14325DE60, 16)]
    assert h.memory.read_bytes(out, 48) == b"\xee" * 48
    assert h.memory.read_bytes(destination, 4) == b"\xaa" * 4
    assert [target for target, _ in h.events] == [0x140DAF040]


def test_delegated_metadata_forward_and_output_clear_after_child() -> None:
    h = Harness()
    output = h.allocate(48, 0xEE)

    def child(args: tuple[int, ...]) -> None:
        assert h.memory.read_bytes(output, 48) == b"\xee" * 48
        assert args[1:] == (0x123, 0x456)
        h.memory.write(args[0] + 24, 8, 0xABC)

    def metadata(args: tuple[int, ...]) -> None:
        assert args[1:] == (9, 0xFFFFFFFF, 11)
        assert h.memory.read_bytes(output, 48) == bytes(48)
        assert h.memory.read(args[0] + 40, 1) == 1

    def forward(args: tuple[int, ...]) -> None:
        h.memory.write(args[0] + 24, 8, h.memory.read(args[1] + 24, 8))

    h.programs.update(
        {
            0x140E6A9C0: child,
            0x140900ED0: metadata,
            0x1409076B0: forward,
            0x1402BD7F0: lambda args: None,
        }
    )
    assert h.call(0x141712290, output, 9, 0xFFFFFFFFFFFFFFFF, 11, 0x123, 0x456) == output
    assert h.memory.read(output + 24, 8) == 0xABC
    assert [target for target, _ in h.events] == [
        0x140E6A9C0,
        0x140900ED0,
        0x1409076B0,
        0x1402BD7F0,
    ]
