"""Source-led423B controls, authored before implementation over owned storage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_update_control_flags import ReplayWorldUpdateControlFlags
from vantage.replay_world_update_player_links import (
    ReplayWorldUpdatePlayerLinks,
    ReplayWorldUpdatePlayerLinksReentry,
    run_replay_world_update_player_links,
)

U32, U64 = (1 << 32) - 1, (1 << 64) - 1
CONSTANT, GATE, LOGGER = 0x143219E04, 0x14435505D, 0x144355068
CHILD, RELATION, LOG = 0x141711B80, 0x141734D70, 0x14101ADB0
VIRTUAL = 0xA328
Handler = Callable[[int, tuple[int, ...]], int | None]
Channel = Callable[[int, tuple[int, ...], memoryview | None], int | None]


class Rig:
    def __init__(self, n: int = 2) -> None:
        self.memory = ReplayMemory(start=0x10000)
        self.events: list[tuple] = []
        self.after_read: Callable[[int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.handlers: dict[str, Handler] = {}
        self.rel_results: list[int | None] = [1, 1]
        self.world, self.frame = self.alloc(0xA00), self.alloc(0x400)
        self.players = [self.player() for _ in range(n)]
        self.array = self.new_array(self.players)
        self.header(self.array, n)
        self.put(self.world + 0x7C, 4, 7)
        for i in range(n):
            self.put(self.world + 0x18C + i * 4, 4, 10)
        for address, raw in (
            (CONSTANT, (0x7FC01234).to_bytes(4, "little")),
            (GATE, b"\0"),
            (LOGGER, (0xABCD).to_bytes(8, "little")),
        ):
            self.memory.map_bytes(address, raw)
        self.meta = (self.world, self.frame, 0x12345, 7, 9, 0x3F800001, 3)
        self.phase = ReplayWorldUpdateControlFlags(*self.meta, 0x141629C59, None)
        self.context = ReplayTaskRebuildStorage(self.world, self.read, self.write)
        self.channels = {
            key: ReplayTaskRebuildCalls(self.channel(key))
            for key in ("calls", "logger_home_calls", "relationship_calls", "virtual_calls")
        }

    def alloc(self, size: int, fill: int = 0xA5) -> int:
        pointer = self.memory.allocate(size)
        self.memory.write_bytes(pointer, bytes([fill]) * size)
        return pointer

    def put(self, address: int, width: int, value: int) -> None:
        self.memory.write(address & U64, width, value & ((1 << (8 * width)) - 1))

    def get(self, address: int, width: int = 8) -> int:
        return self.memory.read(address & U64, width)

    def read(self, address: int, width: int) -> int:
        self.events.append(("read", address, width))
        value = self.get(address, width)
        if self.after_read:
            self.after_read(address, width)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("write", address, width, value))
        self.put(address, width, value)
        if self.after_write:
            self.after_write(address, width, value)

    def player(self, address: int | None = None) -> int:
        if address is None:
            address = self.alloc(0x700)
        else:
            self.memory.map_bytes(address, b"\xa5" * 0x700)
        vptr = self.alloc(0x330)
        self.put(address, 8, vptr)
        self.put(vptr + 0x328, 8, VIRTUAL)
        self.put(address + 0x648, 4, 0)
        return address

    def new_array(self, players: list[int]) -> int:
        array = self.alloc(max(1, len(players)) * 16)
        for i, player in enumerate(players):
            self.put(array + i * 16, 8, player)
        return array

    def header(self, begin: int, count: int) -> None:
        self.put(self.world + 0x768, 8, begin)
        self.put(self.world + 0x770, 8, begin + (count << 4))

    def active(self, outer: int = 0, marker: int = 1) -> None:
        self.put(self.players[outer] + 0x648, 4, 1)
        self.put(self.frame + 0x278 + marker * 4, 4, 0)

    def reentry(
        self,
        outer: int = 1,
        word: int = 0x80000001,
    ) -> ReplayWorldUpdatePlayerLinksReentry:
        return ReplayWorldUpdatePlayerLinksReentry(*self.meta, outer, word, 0x141629C90, None)

    def channel(self, name: str) -> Channel:
        def invoke(
            target: int,
            args: tuple[int, ...],
            data: memoryview | None,
        ) -> int | None:
            assert data is None
            self.events.append((name, target, args))
            if name == "calls":
                assert target == CHILD and len(args) == 1
            elif name == "logger_home_calls":
                assert target == LOG and len(args) == 5
            elif name == "relationship_calls":
                assert target == RELATION and len(args) == 4 and args[2:] == (1, 255)
            else:
                assert len(args) == 2
            if name in self.handlers:
                return self.handlers[name](target, args)
            return self.rel_results.pop(0) if name == "relationship_calls" else None

        return invoke

    def run(self, phase: object | None = None, **overrides: object) -> ReplayWorldUpdatePlayerLinks:
        channels = self.channels | overrides
        return run_replay_world_update_player_links(
            self.context,
            channels.pop("calls"),
            self.phase if phase is None else phase,
            **channels,
        )

    def calls(self, name: str) -> list[tuple[int, tuple[int, ...]]]:
        return [(e[1], e[2]) for e in self.events if e[0] == name]


@pytest.mark.parametrize("count", [0, 1 << 32, 0xFFFFFFFF00000000])
def test_primary_low_dword_zero_keeps_full_count_and_unknown_incoming_words(count: int) -> None:
    r = Rig()
    r.header(r.array, count)
    result = r.run()
    assert result == ReplayWorldUpdatePlayerLinks(
        *r.meta,
        0,
        0x61501AA6ECFD980A,
        count,
        None,
        None,
        None,
        None,
        0x14162AB9E,
        None,
    )
    assert r.events == [
        ("write", r.frame + 0x210, 4, 0),
        ("read", r.world + 0x770, 8),
        ("read", r.world + 0x768, 8),
    ]
    assert r.get(r.frame + 0x210) == 0xA5A5A5A500000000
    assert r.get(r.frame + 0x70, 1) == 0xA5
    assert r.get(r.frame + 0x208, 4) == 0xA5A5A5A5


def test_primary_reads_end_before_begin_and_holds_the_sampled_end() -> None:
    r = Rig()
    end = r.get(r.world + 0x770)
    r.after_read = lambda at, width: (
        r.put(r.world + 0x768, 8, end) if (at == r.world + 0x770 and width == 8) else None
    )
    assert r.run().next_address == 0x14162AB9E
    assert r.events[-1] == ("read", r.world + 0x768, 8)


@pytest.mark.parametrize("word", [0, 0x80000000, 0x7FC01234, U32])
def test_nonzero_primary_samples_raw_xmm8_once_without_using_default_time(word: int) -> None:
    r = Rig()
    r.put(CONSTANT, 4, word)
    r.after_read = lambda at, width: r.put(CONSTANT, 4, 0x1234) if at == CONSTANT else None
    result = r.run()
    assert result.xmm8_word == word and result.default_time == r.meta[5]
    assert r.events.count(("read", CONSTANT, 4)) == 1
    assert result.next_address == 0x141629E00 and result.returned_status is None


def test_reentry_skips_initialization_count_gate_and_xmm8_reload() -> None:
    r = Rig()
    r.put(r.frame + 0x210, 4, 0xDEAD)
    result = r.run(r.reentry())
    assert r.events[0] == ("read", GATE, 1)
    assert ("read", CONSTANT, 4) not in r.events
    assert ("write", r.frame + 0x210, 4, 0) not in r.events
    assert r.get(r.frame + 0x210, 4) == 0xDEAD
    assert result.outer_index == 1 and result.xmm8_word == 0x80000001
    assert result.held_r13 == r.players[1] and result.raw_count == 2
    assert result.inner_index is None and result.marker_address is None


def test_logger_uses_live_home_address_after_exact_width_stores_and_current_receiver() -> None:
    r = Rig()
    r.put(GATE, 1, 255)

    def after(at: int, width: int, value: int) -> None:
        if at == r.frame + 0x20:
            r.put(LOGGER, 8, 0xCCDD)
            r.put(r.frame + 0x218, 4, 73)

    r.after_write = after

    def logger(target: int, args: tuple[int, ...]) -> int:
        assert args == (0xCCDD, 0x25, 0x1432EA200, 1, r.frame + 0x20)
        assert r.get(r.get(args[4])) == r.frame + 0x218
        assert r.get(r.frame + 0x218, 4) == 73
        r.put(r.world + 0x7C, 4, 11)
        return 1 << 100

    r.handlers["logger_home_calls"] = logger
    r.run()
    assert r.events[5:11] == [
        ("write", r.frame + 0x220, 4, 7),
        ("write", r.frame + 0x218, 4, 0),
        ("write", r.frame + 0x2B0, 8, r.frame + 0x218),
        ("write", r.frame + 0x20, 8, r.frame + 0x2B0),
        ("read", LOGGER, 8),
        ("logger_home_calls", LOG, (0xCCDD, 0x25, 0x1432EA200, 1, r.frame + 0x20)),
    ]
    assert r.get(r.world + 0x18C, 4) == 21
    assert r.get(r.frame + 0x218) == 0xA5A5A5A500000049


@pytest.mark.parametrize("increment", [0, 1, U32])
def test_world_counter_has_ordinary_read_write_even_for_zero_increment(increment: int) -> None:
    r = Rig()
    r.put(r.world + 0x7C, 4, increment)
    r.put(r.world + 0x18C, 4, U32)
    r.run()
    at = r.events.index(("read", r.world + 0x7C, 4))
    assert r.events[at : at + 3] == [
        ("read", r.world + 0x7C, 4),
        ("read", r.world + 0x18C, 4),
        ("write", r.world + 0x18C, 4, (U32 + increment) & U32),
    ]


def test_counter_load_order_holds_tick_but_samples_current_counter() -> None:
    r = Rig()

    def after(at: int, width: int) -> None:
        if at == r.world + 0x7C:
            r.put(r.world + 0x18C, 4, 80)
        if at == r.world + 0x18C:
            r.put(r.world + 0x7C, 4, 1234)

    r.after_read = after
    r.run()
    assert r.get(r.world + 0x18C, 4) == 87


def test_range_selection_compares_unsigned_full_count_not_low_dword() -> None:
    r = Rig()
    r.header(r.array, (1 << 32) + 1)
    result = r.run(r.reentry())
    assert result.held_r13 == r.players[1] and result.raw_count == (1 << 32) + 1
    assert result.held_begin == r.array


def test_out_of_range_selection_still_publishes_zero_then_reads_actual_648() -> None:
    r = Rig()
    with pytest.raises(ReplayMemoryError):
        r.run(r.reentry(2))
    assert r.events[-2:] == [("write", r.frame + 0x2B0, 8, 0), ("read", 0x648, 4)]
    assert not r.calls("calls")


def test_child_receiver_rereads_held_begin_but_output_keeps_selected_r13() -> None:
    r = Rig()
    r.active()
    alternate = r.new_array([r.players[1], r.players[0]])

    def after(at: int, width: int, value: int) -> None:
        if at == r.frame + 0x2B0:
            r.put(r.array, 8, r.players[1])
            r.header(alternate, 1)

    r.after_write = after

    def child(target: int, args: tuple[int, ...]) -> None:
        r.put(r.frame + 0x2B0, 8, 0xDEAD)
        return None

    r.handlers["calls"] = child
    result = r.run()
    assert r.calls("calls") == [(CHILD, (r.players[1],))]
    assert result.held_r13 == r.players[0] and r.get(r.frame + 0x2B0) == 0xDEAD
    assert result.held_begin == alternate and result.inner_index == 1


def test_648_zero_exit_carries_begin_sampled_before_end_callback() -> None:
    r = Rig()
    changed = r.new_array(r.players[::-1])
    samples = 0

    def after(at: int, width: int) -> None:
        nonlocal samples
        if at == r.world + 0x770:
            samples += 1
            if samples == 2:
                r.put(r.world + 0x768, 8, changed)

    r.after_read = after
    result = r.run()
    assert result.held_begin == r.array and result.held_r13 == r.players[0]
    assert result.raw_count == 2 and result.inner_index is None


@pytest.mark.parametrize("low", [0, 1])
def test_after_child_low_dword_count_gate_skips_inner_pass(low: int) -> None:
    r = Rig()
    r.active()
    r.handlers["calls"] = lambda target, args: r.header(r.array, (1 << 32) + low)
    result = r.run()
    assert result.raw_count == (1 << 32) + low and result.inner_index == 1
    assert result.marker_address is None
    assert not r.calls("relationship_calls") and not r.calls("virtual_calls")


def test_nonzero_markers_skip_work_and_preserve_last_marker_address() -> None:
    r = Rig(3)
    r.put(r.players[0] + 0x648, 4, 1)
    result = r.run()
    assert not r.calls("relationship_calls") and not r.calls("virtual_calls")
    assert result.inner_index == 3 and result.marker_address == r.frame + 0x280
    assert ("read", r.frame + 0x27C, 4) in r.events
    assert ("read", r.frame + 0x280, 4) in r.events


def test_self_index_skips_both_relations_but_calls_virtual_and_sets_original_marker() -> None:
    r = Rig()
    r.active(outer=1)
    result = r.run(r.reentry())
    assert not r.calls("relationship_calls")
    assert r.calls("virtual_calls") == [(VIRTUAL, (r.players[1], r.frame + 0xA0))]
    assert r.get(r.frame + 0xA0, 4) == 1 and r.get(r.frame + 0x27C, 4) == 1
    assert r.get(r.frame + 0x280, 4) == 0xA5A5A5A5
    assert result.marker_address == r.frame + 0x27C and result.inner_index == 2


@pytest.mark.parametrize("answers", [(0,), (2, 0), (2, 128), (255, 1)])
def test_relationships_use_whole_al_and_known_r8_masks(answers: tuple[int, ...]) -> None:
    r = Rig()
    r.active()
    r.rel_results = list(answers)
    r.run()
    expected = [(RELATION, (r.players[0], r.frame + 0x94, 1, 255))]
    if answers[0]:
        expected.append((RELATION, (r.players[1], r.frame + 0x90, 1, 255)))
    assert r.calls("relationship_calls") == expected
    success = len(answers) == 2 and bool(answers[1])
    assert bool(r.calls("virtual_calls")) == success
    assert r.get(r.frame + 0x27C, 4) == int(success)
    assert r.get(r.frame + 0x94) == 0xA5A5A5A500000001


def test_first_relation_uses_held_begin_second_and_virtual_refresh_their_receivers() -> None:
    r = Rig()
    r.active()
    second, third = r.player(), r.player()
    array2 = r.new_array([r.players[1], second])
    array3 = r.new_array([r.players[1], third])

    def after(at: int, width: int) -> None:
        if at == r.frame + 0x27C:
            r.header(array2, 2)

    r.after_read = after

    def relation(target: int, args: tuple[int, ...]) -> int:
        if args[1] == r.frame + 0x90:
            r.header(array3, 2)
        return 1

    r.handlers["relationship_calls"] = relation
    result = r.run()
    assert r.calls("relationship_calls") == [
        (RELATION, (r.players[0], r.frame + 0x94, 1, 255)),
        (RELATION, (second, r.frame + 0x90, 1, 255)),
    ]
    assert r.calls("virtual_calls") == [(VIRTUAL, (third, r.frame + 0xA0))]
    assert result.held_begin == array3 and result.held_r13 == r.players[0]


@pytest.mark.parametrize("home", [0x94, 0x90])
def test_relation_receiver_is_loaded_before_its_index_home_store(home: int) -> None:
    r = Rig()
    r.active()
    other = r.player()
    slot = r.array if home == 0x94 else r.array + 16
    r.after_write = lambda at, width, value: (
        r.put(slot, 8, other) if (at == r.frame + home) else None
    )
    r.run()
    at = 0 if home == 0x94 else 1
    assert r.calls("relationship_calls")[at][1][0] == r.players[at]


@pytest.mark.parametrize("ignored", [None, -1, 1 << 100, True])
def test_virtual_target_is_late_at_held_vptr_and_ignored_return_does_not_change_marker(
    ignored: int | None,
) -> None:
    r = Rig()
    r.active(outer=1)
    old = r.get(r.players[1])
    new = r.alloc(0x330)
    r.put(new + 0x328, 8, 0xEE328)

    def after_read(at: int, width: int) -> None:
        if at == r.players[1]:
            r.put(r.players[1], 8, new)
            r.put(old + 0x328, 8, 0xDD328)

    def after_write(at: int, width: int, value: int) -> None:
        if at == r.frame + 0xA0:
            r.put(old + 0x328, 8, 0xCC328)

    r.after_read, r.after_write = after_read, after_write
    r.handlers["virtual_calls"] = lambda target, args: ignored
    r.run(r.reentry())
    assert r.calls("virtual_calls") == [(0xCC328, (r.players[1], r.frame + 0xA0))]
    assert r.get(r.frame + 0x27C, 4) == 1


@pytest.mark.parametrize("index,address", [(14, 0x100000000), (15, 0x100000)])
def test_marker_alias_writes_publication_half_but_preserves_held_selected_pointer(
    index: int,
    address: int,
) -> None:
    r = Rig(index + 1)
    selected = r.player(address)
    r.players[0] = selected
    r.put(r.array, 8, selected)
    r.put(selected + 0x648, 4, 1)
    result = r.run()
    assert result.held_r13 == selected and result.marker_address == r.frame + 0x278 + index * 4
    expected = (selected & ~U32) | 1 if index == 14 else (1 << 32) | selected
    assert r.get(r.frame + 0x2B0) == expected
    assert len(r.calls("virtual_calls")) == 1 and len(r.calls("relationship_calls")) == 2


def test_loop_exit_carries_final_bound_begin_even_if_end_read_changes_current_header() -> None:
    r = Rig()
    r.active()
    changed = r.new_array(r.players[::-1])
    ready = False

    def written(at: int, width: int, value: int) -> None:
        nonlocal ready
        if at == r.frame + 0x27C:
            ready = True

    def read(at: int, width: int) -> None:
        if ready and at == r.world + 0x770:
            r.put(r.world + 0x768, 8, changed)

    r.after_write, r.after_read = written, read
    result = r.run()
    assert result.held_begin == r.array and r.get(r.world + 0x768) == changed
    assert result.inner_index == 2 and result.raw_count == 2


@pytest.mark.parametrize(
    "channel",
    [
        "calls",
        "logger_home_calls",
        "relationship_calls",
        "virtual_calls",
    ],
)
def test_missing_reached_channel_refuses_without_normal_fallback(channel: str) -> None:
    r = Rig()
    r.active()
    if channel == "logger_home_calls":
        r.put(GATE, 1, 1)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run(**{channel: ReplayTaskRebuildCalls(None)})
    assert not r.calls(channel)
    assert all(e[1] == CHILD for e in r.events if e[0] == "calls")
    if channel in ("relationship_calls", "virtual_calls"):
        assert r.get(r.frame + 0x94, 4) == 1
        assert r.get(r.frame + 0x27C, 4) == 0


@pytest.mark.parametrize("al", [None, -1, 256, True])
def test_invalid_consumed_al_refuses_after_first_home_before_later_effects(
    al: int | None,
) -> None:
    r = Rig()
    r.active()
    r.rel_results = [al]
    with pytest.raises(ValueError):
        r.run()
    assert len(r.calls("relationship_calls")) == 1
    assert not r.calls("virtual_calls")
    assert r.events[-1] == ("relationship_calls", RELATION, (r.players[0], r.frame + 0x94, 1, 255))
    assert r.get(r.frame + 0x27C, 4) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("world", -1),
        ("logical_frame", 1 << 64),
        ("entry_time", True),
        ("cycle", -1),
        ("status", 1 << 32),
        ("default_time", -1),
        ("control_flags", 1 << 32),
        ("next_address", 0x141629C90),
        ("returned_status", 0),
    ],
)
def test_primary_validation_precedes_all_source_effects(field: str, value: int) -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.run(replace(r.phase, **{field: value}))
    assert not r.events


@pytest.mark.parametrize(
    "field,value",
    [
        ("outer_index", -1),
        ("outer_index", 1 << 32),
        ("xmm8_word", True),
        ("xmm8_word", 1 << 32),
        ("next_address", 0x141629C59),
        ("returned_status", 0),
    ],
)
def test_reentry_validation_precedes_all_source_effects(field: str, value: int) -> None:
    r = Rig()
    with pytest.raises(ValueError):
        r.run(replace(r.reentry(), **{field: value}))
    assert not r.events


@pytest.mark.parametrize("phase", [None, {}, "wrong"])
def test_input_requires_an_actual_source_entry_record(phase: object) -> None:
    r = Rig()
    with pytest.raises(ValueError):
        run_replay_world_update_player_links(
            r.context,
            r.channels["calls"],
            phase,
            **{k: v for k, v in r.channels.items() if k != "calls"},
        )
    assert not r.events


@pytest.mark.parametrize(
    "channel",
    [
        "calls",
        "logger_home_calls",
        "relationship_calls",
        "virtual_calls",
    ],
)
def test_invalid_channel_container_is_rejected_even_on_early_empty_gate(channel: str) -> None:
    r = Rig()
    r.header(r.array, 0)
    with pytest.raises(ValueError):
        r.run(**{channel: object()})
    assert not r.events


def test_invalid_storage_is_rejected_before_source_effects() -> None:
    r = Rig()
    with pytest.raises(ValueError):
        run_replay_world_update_player_links(
            None,
            r.channels["calls"],
            r.phase,
            **{k: v for k, v in r.channels.items() if k != "calls"},
        )
    assert not r.events


def test_unavailable_but_unreached_services_do_not_block_the_early_empty_gate() -> None:
    r = Rig()
    r.header(r.array, 0)
    result = r.run(**dict.fromkeys(r.channels, ReplayTaskRebuildCalls(None)))
    assert result.next_address == 0x14162AB9E
    assert r.events == [
        ("write", r.frame + 0x210, 4, 0),
        ("read", r.world + 0x770, 8),
        ("read", r.world + 0x768, 8),
    ]
