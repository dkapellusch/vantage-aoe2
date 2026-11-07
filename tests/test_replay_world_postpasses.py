"""Source-led postpass controls over owned memory and explicit child capabilities."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import cast

import pytest

from vantage.replay_base_saved import resolve_replay_saved_base_owner
from vantage.replay_base_saved_registration import (
    ReplayBaseSavedRegistrationFP,
    ReplayBaseSavedRegistrationScratch,
    bind_replay_base_saved_registration,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_construction_support import count_replay_player_world_entries
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support
from vantage.replay_world_postpasses import (
    ReplayWorldPostpassesProfile,
    bind_replay_world_postpasses,
)

HOOK, VISIBLE, SEEN, RESET = 0x14151E9C0, 0x14114B470, 0x14115F240, 0x141731F00
TIMING, RULES, BITS = 0x140E27920, 0x1416938B0, 0x14188E440
VFOG, VEVENT, VRESOURCE = 0xFF00F8, 0xFF02F8, 0xFF01F8
FREE, BUS, EVENT = 0xFE0001, 0xFE0002, 0xFE0003
U64 = (1 << 64) - 1
Handler = Callable[[tuple[int, ...]], int | None]


class Rig:
    def __init__(self) -> None:
        self.mem = ReplayMemory()
        self.events: list[tuple[str, int, int, int]] = []
        self.calls: list[tuple[str, int, tuple[int, ...]]] = []
        self.handlers: dict[tuple[str, int], Handler] = {}
        self.live: list[tuple[int, int]] = []
        self.snapshots: list[tuple[int, bytes]] = []
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.world = self.alloc(0x1000)
        self.player, self.other = self.alloc(0x900), self.alloc(0x900)
        self.visible, self.seen, self.reset = self.alloc(0x30), self.alloc(0x30), self.alloc(0x70)
        self.terrain, self.grid = self.alloc(0x6000), self.alloc(0x18)
        self.cells, self.rows, self.flags = self.alloc(4 * 4 * 8), self.alloc(0x48), self.alloc(3)
        self.seen_rows, self.cell_word = self.alloc(0x60), self.alloc(8)
        self.unit, self.master = self.alloc(0x600), self.alloc(0x100)
        self.table, self.system = self.alloc(0x400), self.alloc(0x800)
        self.fog, self.fog_table = self.alloc(8), self.alloc(0x100)
        self.player_array = self.alloc(32)
        self.mem.map_bytes(0x1436A0294, (0x3F800000).to_bytes(4, "little"))
        self.mem.map_bytes(0x1443C9920, EVENT.to_bytes(8, "little"))
        self.mem.map_bytes(0x144414BC0, bytes(8))
        self.mem.map_bytes(0x143199DD0, FREE.to_bytes(8, "little"))
        for address, width, value in (
            (self.player + 8, 8, self.world),
            (self.other + 8, 8, self.world),
            (self.world + 0x98, 8, self.terrain),
            (self.terrain + 0x5BC8, 8, self.grid),
            (self.grid, 8, self.cells),
            (self.grid + 0x10, 4, 4),
            (self.visible, 8, self.player),
            (self.visible + 0x10, 8, self.rows),
            (self.visible + 0x18, 8, self.flags),
            (self.seen, 8, self.player),
            (self.seen + 0x10, 8, self.seen_rows),
            (self.world + 0x768, 8, self.player_array),
            (self.world + 0x770, 8, self.player_array + 32),
            (self.player_array, 8, self.player),
            (self.player_array + 16, 8, self.other),
            (self.other + 0x648, 4, 1),
            (self.other, 8, self.table),
            (self.table + 0xF8, 8, VRESOURCE),
            (self.table + 0x2F8, 8, VEVENT),
            (self.other + 0x28, 8, self.system),
            (self.system + 0x798, 8, self.fog),
            (self.fog, 8, self.fog_table),
            (self.fog_table + 0xF8, 8, VFOG),
            (self.unit + 8, 4, 42),
            (self.unit + 0x18, 8, self.player),
            (self.unit + 0x10, 8, (self.master + 0x6A586EB28AC201FC + 0x0CF19788B2554E70) & U64),
            (self.master + 0x38, 8, (17 + 0x50A06BCECEBEF905 - 0x5B32AA7995D95916) & U64),
            (self.master + 0x78, 4, 0x3F000000),
            (self.master + 0x7C, 4, 0x40000000),
            (self.world + 0x8E8, 4, 0x3F000000),
            (self.world + 0x164, 4, 0x40000000),
        ):
            self.mem.write(address, width, value)
        for field, word, first, second in (
            (0x170, 0xABCD00003F800000, -0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1),
            (0x178, 0xBCDE000040000000, -0x61501AA6ECFD980A, 0x6C5EAB60B426DD28),
            (0x180, 0xCDEF000040400000, 0x2B3719EF44DE99FF, 0x21D14A25ED7C802C),
        ):
            self.mem.write(self.unit + field, 8, (word - first - second) & U64)
        self.storage = ReplayTaskRebuildStorage(self.world, self.read, self.write)
        self.ordinary_calls = ReplayTaskRebuildCalls(self.ordinary)
        self.runtime = self.mem.runtime_calls(self.ordinary_calls)
        self.imports = ReplayTaskRebuildCalls(self.import_call)
        self.support = bind_replay_unit_constructor_support(
            self.storage, self.ordinary_calls, bind_local=self.local, imports=self.imports
        )
        self.registration = bind_replay_base_saved_registration(
            self.storage,
            self.ordinary_calls,
            imports=self.imports,
            fp_calls=ReplayBaseSavedRegistrationFP(None),
            bind_local=self.local,
            scratch=ReplayBaseSavedRegistrationScratch(bytes(0xB0)),
        )
        self.profile = ReplayWorldPostpassesProfile(
            bytes([0xA1]) * 0xF0, bytes([0xB2]) * 0xD0, bytes([0xC3]) * 0x34, bytes([0xD4]) * 0x54
        )
        self.bound = self.bind()
        self.samples: list[tuple[int, list[int]]] = []
        self.sample_counter = 10

    def alloc(self, size: int) -> int:
        address = self.mem.allocate(size)
        self.mem.fill(address, 0, size)
        return address

    def read(self, address: int, width: int) -> int:
        value = self.mem.read(address, width)
        self.events.append(("r", address, width, value))
        if self.after_read:
            self.after_read(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.mem.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.after_write:
            self.after_write(address, width, value)

    @contextmanager
    def local(self, view: memoryview) -> Iterator[int]:
        with self.mem.bind_local(view) as address:
            self.live.append((len(view), address))
            try:
                yield address
            finally:
                self.snapshots.append((len(view), bytes(view)))
                self.live.pop()

    def frame(self, size: int) -> int:
        return next(address for length, address in reversed(self.live) if length == size)

    def bind(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {
            name: ReplayTaskRebuildCalls(self.channel(name))
            for name in (
                "visibility_calls",
                "fog_home_calls",
                "player_event_home_calls",
                "resource_home_calls",
                "state_byte_calls",
                "rule_event_home_calls",
            )
        }
        channels.update(overrides)
        return bind_replay_world_postpasses(
            self.storage,
            self.ordinary_calls,
            **channels,
            bind_local=self.local,
            profile=self.profile,
            mxcsr=0x1F80,
        )

    def record(self, channel: str, target: int, args: tuple[int, ...]) -> Handler | None:
        self.calls.append((channel, target, args))
        return self.handlers.get((channel, target))

    def channel(self, name: str) -> Callable[[int, tuple[int, ...], memoryview | None], int | None]:
        def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            handler = self.record(name, target, args)
            if handler:
                return handler(args)
            allowed = {
                "visibility_calls": 0x141357E10,
                "fog_home_calls": VFOG,
                "player_event_home_calls": VEVENT,
                "resource_home_calls": VRESOURCE,
                "state_byte_calls": 0x14170E660,
                "rule_event_home_calls": 0x140A635D0,
            }
            if target != allowed[name]:
                raise UnresolvedReplayTaskRebuild(f"unprovided authored {name} service{target:x}")
            return None

        return call

    def import_call(
        self, target: int, args: tuple[int, ...], data: memoryview | None
    ) -> int | None:
        assert data is None
        handler = self.record("imports", target, args)
        if handler:
            return handler(args)
        if target == FREE:
            self.mem.free(args[0])
            return None
        raise UnresolvedReplayTaskRebuild(f"unprovided authored import{target:x}")

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        assert data is None
        handler = self.record("calls", target, args)
        if handler:
            return handler(args)
        owner: ReplayTaskRebuildCalls | None = None
        if target in (0x142D6BA78, 0x142D6E3B7):
            owner = self.runtime
        elif target in (0x142D6C268, 0x142D6C270):
            owner = self.support
        elif target == 0x141603FF0:
            owner = self.registration
        if owner is not None:
            assert owner.call is not None
            return owner.call(target, args, data)
        if target == 0x141603EF0:
            return count_replay_player_world_entries(self.storage, args[0])
        if target == 0x141603F60:
            return resolve_replay_saved_base_owner(self.storage, *args)
        if target == 0x141617DB0:
            return self.unit
        if target == 0x14172AC80:
            return 0
        if target == 0x14111AC10:
            return 1
        if target == 0x141734F30:
            return 0
        if target == 0x140A69450:
            return BUS
        if target == 0x140903E40:
            self.sample_counter += 1
            return self.sample_counter
        if target == 0x140E66530:
            self.samples.append((args[0], [self.mem.read(args[1] + i * 4, 4) for i in range(5)]))
            return None
        raise UnresolvedReplayTaskRebuild(f"unprovided authored child{target:x}")

    def run(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def called(self, channel: str, target: int) -> list[tuple[int, ...]]:
        return [args for ch, t, args in self.calls if ch == channel and t == target]

    def visible_row(self, *, old: int = 0, wide: bool = False) -> None:
        for at, width, value in (
            (self.visible + 0xC, 4, 1),
            (self.rows, 8, self.unit),
            (self.rows + 8, 4, 0x3F800000),
            (self.rows + 0xC, 4, 0x3F800000),
            (self.rows + 0x10, 8, old),
            (self.flags, 1, int(wide)),
        ):
            self.mem.write(at, width, value)

    def seen_row(self, *, old: int = 2, current: int = 0) -> None:
        for at, width, value in (
            (self.seen + 0xC, 4, 1),
            (self.seen_rows, 8, self.unit),
            (self.seen_rows + 8, 8, self.cell_word),
            (self.seen_rows + 0x10, 8, old),
            (self.seen_rows + 0x18, 4, 42),
            (self.cell_word, 8, current),
        ):
            self.mem.write(at, width, value)


def test_hook_null_and_actual_nonnull_tail_delegation() -> None:
    r = Rig()
    assert r.run(HOOK) is None
    assert not r.calls and not r.snapshots
    root, parent = r.alloc(0x20), r.alloc(0x1B0)
    r.mem.write(0x144414BC0, 8, root)
    r.mem.write(root + 0x18, 8, parent)
    r.mem.write(parent + 0x1A8, 8, 0xABCDEF)
    token = object()
    r.handlers["calls", 0x1414F75E0] = lambda _args: cast(int, token)
    assert r.run(HOOK) is token
    assert r.called("calls", 0x1414F75E0) == [(0xABCDEF,)]


@pytest.mark.parametrize("wide,mask", [(False, 0xFF000000FF), (True, 15)])
def test_visibility_reads_tiles_and_publishes_held_unit_mask(wide: bool, mask: int) -> None:
    r = Rig()
    r.visible_row(wide=wide)
    for cell, value in ((0, 1), (1, 2), (4, 4), (5, 0xFF000000FF if not wide else 8)):
        r.mem.write(r.cells + cell * 8, 8, value)
    assert r.run(VISIBLE, r.visible) is None
    expected = mask & 0x01FFFFFF01FFFFFF
    assert r.mem.read(r.rows + 0x10, 8) == expected
    assert r.mem.read(r.unit + 0x4F0, 8) == expected
    args = r.called("visibility_calls", 0x141357E10)[0]
    assert args[:5] == (EVENT, 42, 0, 0, 0x3F800000)
    snapshot = dict(r.snapshots)[0xF0]
    assert [
        int.from_bytes(snapshot[home : home + width], "little")
        for home, width in (
            (0x20, 4),
            (0x28, 4),
            (0x30, 4),
            (0x38, 4),
            (0x40, 8),
            (0x48, 8),
            (0x50, 8),
        )
    ] == [0x3F800000, 0x3F000000, 0x40000000, 17, 0, expected, r.unit + 0x4A8]
    assert len(args) == 12


def test_unchanged_mask_never_reads_unit_or_notifies() -> None:
    r = Rig()
    r.visible_row(old=3)
    r.mem.write(r.rows, 8, 0xDEADBEEF)
    r.mem.write(r.cells + 5 * 8, 8, 3)
    r.run(VISIBLE, r.visible)
    assert not r.called("visibility_calls", 0x141357E10)
    assert not any(k == "r" and at == r.rows for k, at, _w, _v in r.events)


def test_visibility_notification_cannot_redirect_held_unit_publication() -> None:
    r = Rig()
    r.visible_row()
    r.mem.write(r.cells + 5 * 8, 8, 3)
    r.handlers["visibility_calls", 0x141357E10] = lambda _args: r.mem.write(r.rows, 8, r.other)
    r.run(VISIBLE, r.visible)
    assert r.mem.read(r.rows, 8) == r.other
    assert r.mem.read(r.unit + 0x4F0, 8) == 3
    assert r.mem.read(r.other + 0x4F0, 8) == 0


def test_visibility_repeated_master_reads_are_current() -> None:
    r = Rig()
    r.visible_row()
    r.mem.write(r.cells + 5 * 8, 8, 1)
    second, third = r.alloc(0x100), r.alloc(0x100)
    r.mem.write(second + 0x7C, 4, 0x40400000)
    r.mem.write(third + 0x78, 4, 0x40800000)
    pending = iter((second, third))

    def read(at: int, width: int, _value: int) -> None:
        if at == r.unit + 0x10 and width == 8:
            following = next(pending, None)
            if following is not None:
                r.mem.write(at, 8, (following + 0x6A586EB28AC201FC + 0x0CF19788B2554E70) & U64)

    r.after_read = read
    r.run(VISIBLE, r.visible)
    image = dict(r.snapshots)[0xF0]
    assert int.from_bytes(image[0x30:0x34], "little") == 0x40400000
    assert int.from_bytes(image[0x28:0x2C], "little") == 0x40800000
    assert int.from_bytes(image[0x38:0x3C], "little") == 17


def test_visibility_holds_y_before_the_current_flag_read() -> None:
    r = Rig()
    r.visible_row()
    r.mem.write(r.cells + 5 * 8, 8, 1)
    r.mem.write(r.cells + 9 * 8, 8, 2)

    def read(at: int, _width: int, _value: int) -> None:
        if at == r.flags:
            r.mem.write(r.rows + 0xC, 4, 0x40000000)

    r.after_read = read
    r.run(VISIBLE, r.visible)
    assert r.mem.read(r.unit + 0x4F0, 8) == 1


def test_visibility_samples_current_array_under_the_held_grid() -> None:
    r = Rig()
    r.visible_row(wide=True)
    replacement, different_grid = r.alloc(128), r.alloc(0x18)
    r.mem.write(r.cells, 8, 1)
    for cell, word in ((1, 2), (4, 4), (5, 8)):
        r.mem.write(replacement + cell * 8, 8, word)

    def read(at: int, _width: int, _value: int) -> None:
        if at == r.cells:
            r.mem.write(r.grid, 8, replacement)
            r.mem.write(r.terrain + 0x5BC8, 8, different_grid)

    r.after_read = read
    r.run(VISIBLE, r.visible)
    assert r.mem.read(r.unit + 0x4F0, 8) == 15


@pytest.mark.parametrize("x", [0xCF000000, 0x7FC00000])
def test_visibility_unmapped_flat_coordinate_is_not_clamped_or_skipped(x: int) -> None:
    r = Rig()
    r.visible_row()
    r.mem.write(r.rows + 8, 4, x)
    with pytest.raises(ReplayMemoryError):
        r.run(VISIBLE, r.visible)
    assert not r.snapshots and not r.called("visibility_calls", 0x141357E10)


def test_missing_visibility_service_keeps_mask_unpublished() -> None:
    r = Rig()
    r.visible_row()
    r.mem.write(r.cells + 5 * 8, 8, 3)
    r.bound = r.bind(visibility_calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="141357e10"):
        r.run(VISIBLE, r.visible)
    assert r.mem.read(r.rows + 0x10, 8) == r.mem.read(r.unit + 0x4F0, 8) == 0


def test_seen_loss_uses_real_header_getters_and_live_homes() -> None:
    r = Rig()
    r.seen_row()
    observed: list[tuple[int, ...]] = []

    def fog(args: tuple[int, ...]) -> None:
        assert args[:4] == (r.fog, r.other, 0x3F800000, 0x40000000)
        assert r.mem.read(args[6], 8) == args[6] + 0x80
        assert r.mem.read(r.mem.read(args[6], 8), 1) == 1
        observed.append(tuple(r.mem.read(at, 8) for at in args[4:]))

    r.handlers["fog_home_calls", VFOG] = fog
    r.handlers["calls", 0x14172AC80] = lambda _args: 1
    r.run(SEEN, r.seen)
    assert len(observed) == 1
    assert observed[0][0] == 0xB2B2B2B240400000
    assert observed[0][1] == r.unit
    assert r.mem.read(r.seen_rows + 0x10, 8) == 0
    assert r.called("player_event_home_calls", VEVENT)[0][:4] == (r.other, 0xFFFFFFFF, 1, 0x20D)
    image = dict(r.snapshots)[0xD0]
    assert image[0xB0] == 1 and int.from_bytes(image[0xB8:0xBC], "little") == 1


def test_seen_header_return_is_consumed_after_bool_store() -> None:
    r = Rig()
    r.seen_row()
    r.handlers["calls", 0x141603FF0] = lambda _args: None
    with pytest.raises(ValueError, match="header RAX"):
        r.run(SEEN, r.seen)
    assert dict(r.snapshots)[0xD0][0xB0] == 1
    assert r.mem.read(r.seen_rows + 0x10, 8) == 2


def test_seen_fog_target_is_held_before_coordinate_stores() -> None:
    r = Rig()
    r.seen_row()

    def written(at: int, _width: int, _value: int) -> None:
        if r.live and at == r.frame(0xD0) + 0xC0:
            r.mem.write(r.fog_table + 0xF8, 8, 0xDEAD)

    r.after_write = written
    r.run(SEEN, r.seen)
    assert len(r.called("fog_home_calls", VFOG)) == 1


def test_seen_lookup_consumption_follows_current_row_read() -> None:
    r = Rig()
    r.seen_row()
    current = r.alloc(0x20)
    r.mem.move(current, r.seen_rows, 0x20)

    def lookup(_args: tuple[int, ...]) -> int | None:
        r.mem.write(r.seen + 0x10, 8, current)
        return None

    r.handlers["calls", 0x141617DB0] = lookup
    with pytest.raises(ValueError, match="lookup RAX"):
        r.run(SEEN, r.seen)
    assert any(k == "r" and at == current for k, at, _w, _v in r.events)
    assert r.mem.read(current + 0x10, 8) == 2


def test_seen_last_invalid_row_is_compacted_with_two_source_copies() -> None:
    r = Rig()
    r.seen_row(old=2)
    r.mem.write(r.seen + 0xC, 4, 2)
    r.mem.write_bytes(r.seen_rows + 0x20, bytes([0x77]) * 0x20)
    second_cell = r.alloc(8)
    r.mem.write(second_cell, 8, 0x01010101)
    r.mem.write(r.seen_rows + 0x28, 8, second_cell)
    r.mem.write(r.seen_rows + 0x30, 8, 0x01010101)
    held_second = r.mem.read_bytes(r.seen_rows + 0x20, 0x20)
    r.handlers["calls", 0x141617DB0] = lambda _args: 0
    r.run(SEEN, r.seen)
    assert r.mem.read(r.seen + 0xC, 4) == 1
    assert r.mem.read_bytes(r.seen_rows, 0x20) == held_second
    assert r.mem.read(r.seen_rows + 0x20, 8) == 0
    clears = [
        (at - r.seen_rows - 0x20, width)
        for k, at, width, _v in r.events
        if k == "w" and r.seen_rows + 0x20 <= at < r.seen_rows + 0x40
    ]
    assert clears == [(0, 8), (8, 8), (0x18, 4), (0x10, 8)]


def test_seen_null_invalid_overwrites_prior_nonnull_invalid() -> None:
    r = Rig()
    r.seen_row()
    r.mem.write(r.seen + 0xC, 4, 2)
    r.mem.write(r.seen_rows + 0x28, 8, r.cell_word)
    r.mem.write(r.seen_rows + 0x30, 8, 2)
    r.handlers["calls", 0x141617DB0] = lambda _args: 0
    r.run(SEEN, r.seen)
    assert r.mem.read(r.seen + 0xC, 4) == 2
    assert int.from_bytes(dict(r.snapshots)[0xD0][0xC8:0xD0], "little") == 0


def test_seen_tail_clears_resample_current_array_and_count() -> None:
    r = Rig()
    r.seen_row()
    r.mem.write(r.seen + 0xC, 4, 2)
    r.mem.write(r.seen_rows + 0x28, 8, r.cell_word)
    r.mem.write(r.seen_rows + 0x30, 8, 0)
    following = r.alloc(0x20)
    r.mem.fill(following, 0x99, 0x20)
    r.handlers["calls", 0x141617DB0] = lambda _args: 0

    def written(at: int, width: int, value: int) -> None:
        if at == r.seen_rows + 0x20 and width == 8 and value == 0:
            r.mem.write(r.seen + 0x10, 8, following)
            r.mem.write(r.seen + 0xC, 4, 0)

    r.after_write = written
    r.run(SEEN, r.seen)
    assert r.mem.read(following, 8) == 0x9999999999999999
    assert r.mem.read(following + 8, 8) == r.mem.read(following + 0x10, 8) == 0
    assert r.mem.read(following + 0x18, 4) == 0


@pytest.mark.parametrize(
    "active,count,capacity", [(1, 9, 999), (0, 0, 999), (0, 1, 512), (0, 1, 0xFFFFFFFF)]
)
def test_reset_gates_hold_original_count(active: int, count: int, capacity: int) -> None:
    r = Rig()
    r.mem.write(r.reset, 4, capacity)
    r.mem.write(r.reset + 4, 8, U64)
    r.mem.write(r.reset + 0xC, 4, count)
    r.mem.write(r.reset + 0x10, 4, active)
    r.run(RESET, r.reset)
    assert r.mem.read(r.reset + 4, 8) == (U64 if active else 0)
    assert r.mem.read(r.reset + 0xC, 4) == (count if active else 0)
    assert not r.calls


def test_reset_free_allocate_and_current_capacity_memset_are_real() -> None:
    r = Rig()
    old = r.alloc(8)
    r.mem.write(r.reset, 4, 513)
    r.mem.write(r.reset + 0xC, 4, 1)
    r.mem.write(r.reset + 0x68, 8, old)

    def allocate(args: tuple[int, ...]) -> int:
        assert args == (4096,)
        r.mem.write(r.reset, 4, 3)
        return r.mem.allocate(args[0])

    r.handlers["calls", 0x142D6BA78] = allocate
    r.run(RESET, r.reset)
    with pytest.raises(ReplayMemoryError):
        r.mem.read(old, 1)
    pointer = r.mem.read(r.reset + 0x68, 8)
    assert r.mem.read_bytes(pointer, 24) == bytes(24)
    assert r.called("calls", 0x142D6E3B7) == [(pointer, 0, 24)]
    assert r.mem.read(r.reset + 0xC, 4) == 0


def test_reset_null_allocation_publishes_before_actual_memset_refusal() -> None:
    r = Rig()
    old = r.alloc(8)
    r.mem.write(r.reset, 4, 513)
    r.mem.write(r.reset + 0xC, 4, 7)
    r.mem.write(r.reset + 0x68, 8, old)
    r.handlers["calls", 0x142D6BA78] = lambda _args: 0
    with pytest.raises(ReplayMemoryError):
        r.run(RESET, r.reset)
    assert r.mem.read(r.reset, 4) == 512
    assert r.mem.read(r.reset + 0x68, 8) == 0
    assert r.mem.read(r.reset + 0xC, 4) == 7


def test_reset_zero_count_comparison_precedes_clear_callback() -> None:
    r = Rig()

    def written(at: int, _width: int, _value: int) -> None:
        if at == r.reset + 4:
            r.mem.write(r.reset + 0xC, 4, 9)

    r.after_write = written
    r.run(RESET, r.reset)
    assert r.mem.read(r.reset + 0xC, 4) == 9


def test_timing_samples_form_current_contiguous_packet() -> None:
    r = Rig()
    subject = r.alloc(0x400)
    r.mem.write(subject + 0x390, 8, 0xCAFE)
    r.run(TIMING, subject, 0xAABBCCDD00000009)
    assert r.samples == [(0xCAFE, [9, 11, 12, 13, 14])]
    assert [args[2] for args in r.called("calls", 0x140903E40)] == list(range(0xF5A, 0xF5E))


def test_timing_invalid_fourth_result_refuses_after_current_receiver_read() -> None:
    r = Rig()
    subject = r.alloc(0x400)
    values = iter((1, 2, 3, None))
    r.handlers["calls", 0x140903E40] = lambda _args: next(values)
    with pytest.raises(ValueError, match="fourth timing"):
        r.run(TIMING, subject, 7)
    assert any(k == "r" and at == subject + 0x390 for k, at, _w, _v in r.events)
    assert dict(r.snapshots)[0x34][0x30:0x34] == bytes([0xC3]) * 4
    assert not r.samples


@pytest.mark.parametrize("rule", [0xFFFF, 0x8000])
def test_disabled_signed_rule_has_no_children_or_local_mapping(rule: int) -> None:
    r = Rig()
    r.mem.write(r.world + 0x8E2, 2, rule)
    r.run(RULES, r.world)
    assert not r.calls and not r.snapshots


@pytest.mark.parametrize(
    "flags,query,state,resource",
    [
        (0, None, False, False),
        (1, 0, True, False),
        (1, 1, False, False),
        (2, 1, False, True),
        (2, 0xFFFFFFFF, False, False),
        (6, 0xFFFFFFFF, False, True),
        (6, 1, False, False),
        (3, 0, True, False),
    ],
)
def test_rule_flags_consume_only_required_raw_query(
    flags: int, query: int | None, state: bool, resource: bool
) -> None:
    r = Rig()
    r.mem.write(r.world + 0x8EC, 2, flags)
    r.handlers["calls", 0x14111AC10] = lambda _args: query
    r.run(RULES, r.world)
    assert bool(r.called("state_byte_calls", 0x14170E660)) is state
    assert bool(r.called("resource_home_calls", VRESOURCE)) is resource
    if state:
        assert r.called("state_byte_calls", 0x14170E660) == [(r.other, 2, 255)]


@pytest.mark.parametrize("bad", [None, True, -1, 1 << 64])
def test_consumed_rule_query_refuses_after_current_flags_read(bad: int | None) -> None:
    r = Rig()
    r.mem.write(r.world + 0x8EC, 2, 1)
    r.handlers["calls", 0x14111AC10] = lambda _args: bad
    with pytest.raises(ValueError):
        r.run(RULES, r.world)
    assert any(k == "r" and at == r.world + 0x8EC for k, at, _w, _v in r.events)
    assert not r.snapshots


@pytest.mark.parametrize(
    "amount,double",
    [
        (0, 0),
        (0x80000000, 0x8000000000000000),
        (0x3F800000, 0x3FF0000000000000),
        (1, 0x36A0000000000000),
        (0x7F800000, 0x7FF0000000000000),
        (0x7FC12345, 0x7FF82468A0000000),
    ],
)
def test_rule_event_widens_held_amount_and_retains_signed_resource(
    amount: int,
    double: int,
) -> None:
    r = Rig()
    r.mem.write(r.world + 0x8EC, 2, 2)
    r.mem.write(r.world + 0x8E4, 2, 0x8001)
    r.mem.write(r.world + 0x8E8, 4, amount)
    r.mem.write(r.world + 0x164, 4, 0x3F800000)
    r.handlers["calls", 0x141734F30] = lambda _args: 1
    observed: list[tuple[int, ...]] = []

    def event(args: tuple[int, ...]) -> None:
        observed.append((args[0], r.mem.read(args[1], 4), args[2], args[3], r.mem.read(args[4], 8)))

    r.handlers["rule_event_home_calls", 0x140A635D0] = event
    r.run(RULES, r.world)
    assert observed == [(BUS, 1, 0xFFFF8001, 1, double)]
    resource_args = r.called("resource_home_calls", VRESOURCE)[0]
    assert resource_args[:5] == (r.other, 0x8001, amount, 1, 255)


def test_rule_invalid_bus_keeps_bool_home_but_publishes_identifier_home() -> None:
    r = Rig()
    r.mem.write(r.world + 0x8EC, 2, 2)
    r.handlers["calls", 0x141734F30] = lambda _args: 1
    r.handlers["calls", 0x140A69450] = lambda _args: None
    with pytest.raises(ValueError, match="rule bus"):
        r.run(RULES, r.world)
    image = dict(r.snapshots)[0x54]
    assert int.from_bytes(image[0x50:0x54], "little") == 1
    assert image[0x20:0x28] == b"\x01" + bytes([0xD4]) * 7


def test_rule_virtual_slot_is_current_under_held_vptr_after_bool_store() -> None:
    r = Rig()
    r.mem.write(r.world + 0x8EC, 2, 2)
    replacement = r.alloc(0x100)
    r.mem.write(replacement + 0xF8, 8, 0x9999)
    reached: list[tuple[int, ...]] = []

    def written(at: int, width: int, _value: int) -> None:
        if r.live and at == r.frame(0x54) + 0x20 and width == 1:
            r.mem.write(r.other, 8, replacement)
            r.mem.write(r.table + 0xF8, 8, 0x8888)

    r.after_write = written
    r.handlers["resource_home_calls", 0x8888] = lambda args: reached.append(args)
    r.run(RULES, r.world)
    assert len(reached) == 1 and reached[0][0] == r.other


@pytest.mark.parametrize(
    "channel",
    [
        "fog_home_calls",
        "player_event_home_calls",
        "resource_home_calls",
        "state_byte_calls",
        "rule_event_home_calls",
    ],
)
def test_missing_reached_category_never_falls_back_to_ordinary(channel: str) -> None:
    r = Rig()
    r.bound = r.bind(**{channel: ReplayTaskRebuildCalls(None)})
    if channel in ("fog_home_calls", "player_event_home_calls"):
        r.seen_row()
        r.handlers["calls", 0x14172AC80] = lambda _args: 1
        target, args = SEEN, (r.seen,)
        missing = VFOG if channel == "fog_home_calls" else VEVENT
    else:
        r.mem.write(r.world + 0x8EC, 2, 1 if channel == "state_byte_calls" else 2)
        r.handlers["calls", 0x14111AC10] = lambda _args: 0 if channel == "state_byte_calls" else 1
        r.handlers["calls", 0x141734F30] = lambda _args: 1
        target, args = RULES, (r.world,)
        missing = {
            "resource_home_calls": VRESOURCE,
            "state_byte_calls": 0x14170E660,
            "rule_event_home_calls": 0x140A635D0,
        }[channel]
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{missing:x}"):
        r.run(target, *args)
    assert not r.called("calls", missing)


def test_unknown_target_preserves_payload_arguments_and_result_identity() -> None:
    r = Rig()
    payload, result = memoryview(b"abc"), object()
    seen: list[tuple[int, tuple[int, ...], memoryview | None]] = []

    def lower(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        seen.append((target, args, data))
        return cast(int, result)

    unknown = bind_replay_world_postpasses(
        r.storage,
        ReplayTaskRebuildCalls(lower),
        **{
            name: ReplayTaskRebuildCalls(None)
            for name in (
                "visibility_calls",
                "fog_home_calls",
                "player_event_home_calls",
                "resource_home_calls",
                "state_byte_calls",
                "rule_event_home_calls",
            )
        },
        bind_local=r.local,
        profile=r.profile,
        mxcsr=0x1F80,
    )
    assert unknown.call is not None
    args = (-1,)
    assert unknown.call(0xDEAD, args, payload) is result
    assert seen == [(0xDEAD, args, payload)] and seen[0][2] is payload


@pytest.mark.parametrize("field", ["visibility", "seen", "timing", "rules"])
def test_private_profiles_require_exact_explicit_bytes(field: str) -> None:
    r = Rig()
    with pytest.raises(ValueError, match="seeds"):
        replace(r.profile, **{field: b""})
