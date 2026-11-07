"""Source-led seven-body controls; implementation is authored independently."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_world_special_mode_helpers import (
    ReplayWorldSpecialModeHelpersProfile,
    bind_replay_world_special_mode_helpers,
    set_replay_special_tile_byte39,
)

OPTIONS, SCALAR, UI, FLAG, TILE = 0x140D6A530, 0x1413D2980, 0x140D66C40, 0x140D63400, 0x1415F9740
SET9, SET39 = 0x14103C390, 0x14103C2C0
GET, ADD, RELEASE, ALLOC = 0x140E15890, 0x140990130, 0x140990140, 0x142D6BA78
CLEAR, CTOR, LOCK, UNLOCK, THROW = (
    0x142D6E3B7,
    0x1413B09A0,
    0x142D6AA5B,
    0x142D6AA61,
    0x142D6AA67,
)
SNAPSHOT, CONVERT, TEMP, APPLY = 0x140808540, 0x141451420, 0x1413D3720, 0x1413E2A50
SCREEN, RTTI, ACTION = 0x140FFD0A0, 0x142D6E3D5, 0x1414C2E70
TILE310, MAP_EFFECT, FINAL = 0x14103C310, 0x141040E60, 0x141868B80
GAME, OPT_GLOBAL, RESOURCE = 0x144353698, 0x1442C3F98, 0x1443E4E20
ONE, SIXTY, HALF = 0x1436A0294, 0x1436A02E0, 0x1431B2420
K1, K2, K3, K4 = (
    0x6A586EB28AC201FC,
    0x0CF19788B2554E70,
    0x349E37847AD69F19,
    0x47E37DFF0616CE4F,
)
HP_XOR, HP_ADD = 0x0F2A55F7A61DD00E, 0x147B5E081EC087D9
ATTR_XOR = 0xD978539418047C54 ^ 0xABAA7F7397F61E6C
B8, A8, OWNER, PLAYER = 0xA8B8, 0xA8A8, 0xB2F8, 0xC1C8
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
Handler = Callable[[tuple[int, ...]], int | None]


class Rig:
    def __init__(self) -> None:
        self.memory = ReplayMemory()
        self.events: list[tuple] = []
        self.locals: list[tuple[int, memoryview]] = []
        self.handlers: dict[int, Handler] = {}
        self.channels: dict[tuple[str, int], Handler] = {}
        self.after_read: Callable[[int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.after_atomic: Callable[[int, int, int], None] | None = None
        self.ignore_increment_prior = False
        self.fail_alloc = False
        self.allocations: list[int] = []
        self.runtime = self.memory.runtime_calls()
        for address, width, value in (
            (GAME, 8, 0),
            (OPT_GLOBAL, 8, 0),
            (RESOURCE, 8, 0),
            (ONE, 4, 0x3F800000),
            (SIXTY, 4, 0x42700000),
            (HALF, 4, 0x3F000000),
        ):
            self.memory.map_bytes(address, value.to_bytes(width, "little"))
        self.storage = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.normal = ReplayTaskRebuildCalls(self.call)
        self.atomics = ReplayUnitAIMapAtomics(None, self.fetch_add)
        self.profile = ReplayWorldSpecialModeHelpersProfile(
            b"\xa1" * 0x80,
            b"\xb2" * 0x40,
            b"\xc3" * 0x68,
        )
        self.bound = self.bind()

    def bind(self, atomics: ReplayUnitAIMapAtomics | None = None) -> ReplayTaskRebuildCalls:
        return bind_replay_world_special_mode_helpers(
            self.storage,
            self.normal,
            rtti_home_calls=self.channel("rtti"),
            b8_fp_calls=self.channel("b8"),
            owner_home_calls=self.channel("owner"),
            player_fp_home_calls=self.channel("player"),
            atomics=atomics or self.atomics,
            bind_local=self.local,
            profile=self.profile,
            mxcsr=0x1F80,
        )

    def alloc(self, size: int, fill: int = 0) -> int:
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([fill]) * size)
        return address

    def put(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value & ((1 << (8 * width)) - 1))

    def get(self, address: int, width: int = 8) -> int:
        return self.memory.read(address, width)

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

    def call(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("normal", target, args, data))
        assert data is None
        if target in self.handlers:
            return self.handlers[target](args)
        if target == CLEAR:
            assert self.runtime.call is not None
            return self.runtime.call(target, args, data)
        if target == ALLOC:
            if self.fail_alloc:
                return 0
            result = self.alloc(args[0], 0xEE)
            self.allocations.append(result)
            return result
        raise UnresolvedReplayTaskRebuild(f"authored child {target:x} unavailable")

    def channel(self, name: str) -> ReplayTaskRebuildCalls:
        def call(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            self.events.append((name, target, args, data))
            assert data is None
            if (name, target) not in self.channels:
                raise UnresolvedReplayTaskRebuild(f"authored {name} target {target:x} unavailable")
            return self.channels[name, target](args)

        return ReplayTaskRebuildCalls(call)

    def fetch_add(self, address: int, value: int) -> int:
        prior = self.get(address, 4)
        self.events.append(("atomic", address, value, prior))
        self.put(address, 4, prior + value)
        if self.after_atomic:
            self.after_atomic(address, value, prior)
        return -1 if self.ignore_increment_prior and value == 1 else prior

    @contextmanager
    def local(self, view: memoryview) -> Iterator[int]:
        with self.memory.bind_local(view) as address:
            self.locals.append((address, memoryview(view)))
            self.events.append(("local+", address, len(view)))
            try:
                yield address
            finally:
                self.events.append(("local-", address))

    def invoke(self, target: int, *args: int) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def calls(self, target: int, channel: str = "normal") -> list[tuple[int, ...]]:
        return [e[2] for e in self.events if e[0] == channel and e[1] == target]

    def local_word(self, offset: int, width: int = 8) -> int:
        return int.from_bytes(self.locals[-1][1][offset : offset + width], "little")

    def options(self, cached: int = 0) -> tuple[int, int]:
        slot, output = self.alloc(8), self.alloc(8, 0xD4)
        self.put(slot, 8, cached)
        self.put(OPT_GLOBAL, 8, 0x123)
        self.handlers[GET] = lambda a: slot if a == (0x123,) else pytest.fail("wrong global")
        self.handlers[ADD] = self.handlers[RELEASE] = lambda _a: None
        return slot, output

    def tile(self, *, count: int = 0, kind: int = 0x45) -> tuple[int, int, int]:
        world, map_, tile = self.alloc(0x780), self.alloc(0x40), self.alloc(0x40)
        self.put(world + 0x98, 8, map_)
        self.put(map_ + 8, 8, tile)
        self.put(map_ + 0x30, 4, 1)
        self.put(map_ + 0x34, 4, 1)
        self.put(tile + 9, 1, kind)
        self.put(tile + 0x1B, 1, count)
        self.put(tile + 0x39, 1, 0xFF)
        return world, map_, tile

    def unit(
        self, *, health: int = 0x40000000, attribute: int = 60, kind: int = 7, category: int = 0x46
    ) -> tuple[int, int, int]:
        unit, master, vptr = self.alloc(0x900), self.alloc(0x380), self.alloc(0xC0)
        self.put(unit, 8, vptr)
        self.put(unit + 8, 4, 99)
        self.put(unit + 0xF, 1, category)
        self.put(unit + 0x10, 8, master + K1 + K2)
        self.put(master + 0x18, 8, ((kind + K4) & U64) ^ K3)
        self.put(master + 0x68, 8, (attribute & U64) ^ ATTR_XOR)
        self.put(unit + 0x130, 8, ((health + HP_ADD) & U64) ^ HP_XOR)
        self.put(vptr + 0xB8, 8, B8)
        self.put(vptr + 0xA8, 8, A8)
        return unit, master, vptr

    def members(self, tile: int, units: tuple[int, ...]) -> int:
        array = self.alloc(max(1, len(units)) * 8)
        for i, unit in enumerate(units):
            self.put(array + 8 * i, 8, unit)
        self.put(tile + 0x28, 8, array)
        self.put(tile + 0x1B, 1, len(units))
        return array


def test_unknown_dispatch_preserves_all_identity_and_does_not_validate_words() -> None:
    r = Rig()
    args, data, result = tuple([-1, True, 1 << 80]), memoryview(bytearray(b"x")), int("9" * 80)

    def unknown(t: int, a: tuple[int, ...], d: memoryview | None) -> int:
        assert t == 0xDEAD and a is args and d is data
        return result

    other = bind_replay_world_special_mode_helpers(
        r.storage,
        ReplayTaskRebuildCalls(unknown),
        rtti_home_calls=r.channel("rtti"),
        b8_fp_calls=r.channel("b8"),
        owner_home_calls=r.channel("owner"),
        player_fp_home_calls=r.channel("player"),
        atomics=r.atomics,
        bind_local=r.local,
        profile=r.profile,
        mxcsr=0x1F80,
    )
    assert other.call is not None and other.call(0xDEAD, args, data) is result
    assert r.events == []


@pytest.mark.parametrize("old,new,saved", [(4, 4, 255), (4, 69, 255), (4, 69, 9), (255, 0, 255)])
@pytest.mark.parametrize("upper", [0, 0xD3B1000000000000])
def test_byte9_only_dl_and_held_full_old_return(old: int, new: int, saved: int, upper: int) -> None:
    r = Rig()
    tile = r.alloc(0x40)
    r.put(tile + 9, 1, old)
    r.put(tile + 0x39, 1, saved)
    assert r.invoke(SET9, tile, upper | new) == old
    expected = [("read", tile + 9, 1)]
    if old != new:
        expected += [("read", tile + 0x39, 1)]
        if saved == 255:
            expected += [("write", tile + 0x39, 1, old)]
        expected += [("write", tile + 9, 1, new)]
    assert r.events == expected
    assert r.locals == []


def test_byte9_holds_old_across_current_saved_read_callback() -> None:
    r = Rig()
    tile = r.alloc(0x40)
    r.put(tile + 9, 1, 12)
    r.put(tile + 0x39, 1, 255)

    def after(a: int, _n: int) -> None:
        if a == tile + 0x39:
            r.put(tile + 9, 1, 42)

    r.after_read = after
    assert r.invoke(SET9, tile, 69) == 12
    assert r.get(tile + 0x39, 1) == 12 and r.get(tile + 9, 1) == 69


@pytest.mark.parametrize("old,new", [(69, 69), (12, 69)])
@pytest.mark.parametrize("upper", [0, 0xFFFF000000000000])
def test_named_byte39_al_and_generic_ignored_return(old: int, new: int, upper: int) -> None:
    r = Rig()
    tile = r.alloc(0x40)
    r.put(tile + 0x39, 1, old)
    assert set_replay_special_tile_byte39(r.storage, tile, upper | new) == int(old != new)
    assert r.get(tile + 0x39, 1) == new
    assert not any(e[0] == "read" and e[1] == tile + 9 for e in r.events)
    assert r.invoke(SET39, tile, upper | new) is None
    assert r.locals == []


@pytest.mark.parametrize("value", [0, 1, 0x80000000, U32])
def test_config_scalar_full_zeroextended_eax(value: int) -> None:
    r = Rig()
    config = r.alloc(0x1160)
    r.put(config + 0x1158, 4, value)
    assert r.invoke(SCALAR, config) == value
    assert r.events == [("read", config + 0x1158, 4)]


@pytest.mark.parametrize("nonnull", [False, True])
def test_game_flag_leaf_returns_held_pointer(nonnull: bool) -> None:
    r = Rig()
    game, obj, other = r.alloc(0xA88), r.alloc(0x70), r.alloc(0x70)
    r.put(game + 0xA80, 8, obj if nonnull else 0)

    def after(a: int, _n: int, _v: int) -> None:
        if a == obj + 0x6D:
            r.put(game + 0xA80, 8, other)

    r.after_write = after
    assert r.invoke(FLAG, game) == (obj if nonnull else 0)
    assert r.get(obj + 0x6D, 1) == int(nonnull)
    assert r.get(other + 0x6D, 1) == 0 and r.locals == []


def test_cached_options_uses_actual_slot_and_retains_entry_spill_seed() -> None:
    r = Rig()
    token = r.alloc(8)
    _slot, output = r.options(token)
    assert r.invoke(OPTIONS, U64, output) == output
    assert r.calls(GET) == [(0x123,)] and r.calls(ADD) == [(token,)]
    assert r.get(output) == token and not r.calls(ALLOC)
    assert len(r.locals) == 1 and len(r.locals[0][1]) == 0x80
    assert r.local_word(0x68) == output and r.local_word(0x20, 4) == 1
    assert r.local_word(0x24, 4) == 0xA1A1A1A1
    assert r.events[-1] == ("local-", r.locals[0][0])


def test_options_rereads_output_after_addref_before_fallback() -> None:
    r = Rig()
    token = r.alloc(8)
    _slot, output = r.options(token)
    r.handlers[ADD] = lambda _a: r.put(output, 8, 0)
    r.handlers[ALLOC] = lambda _a: (_ for _ in ()).throw(UnresolvedReplayTaskRebuild("alloc"))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.invoke(OPTIONS, 0x777, output)
    assert r.get(output) == 0 and r.calls(ALLOC) == [(0x1178,)]
    assert r.local_word(0x20, 4) == 1


@pytest.mark.parametrize("fail", [False, True])
def test_options_fallback_keeps_original_allocation_distinct_from_constructor(fail: bool) -> None:
    r = Rig()
    _slot, output = r.options()
    constructed, previous = r.alloc(8), r.alloc(8)
    r.fail_alloc = fail

    def ctor(a: tuple[int, ...]) -> int:
        assert r.get(a[0], 16) == 0
        r.put(output, 8, previous)
        return constructed

    r.handlers[CTOR] = ctor
    assert r.invoke(OPTIONS, 0xBAD, output) == output
    assert r.get(output) == (0 if fail else constructed)
    assert r.calls(CLEAR) == ([] if fail else [(r.allocations[0], 0, 0x1178)])
    assert r.calls(RELEASE) == ([] if fail else [(previous,)])
    assert r.local_word(0x70) == (0 if fail else r.allocations[0])
    assert r.local_word(0x20, 4) == 1


def setup_resource(r: Rig, *, gate: int = 0) -> tuple[int, int, int, int, int]:
    _slot, output = r.options()
    r.fail_alloc = True
    manager, snapshot, returned, temporary = r.alloc(0x60), r.alloc(0x30), r.alloc(8), r.alloc(8)
    r.put(RESOURCE, 8, manager)
    r.put(manager, 8, snapshot)
    r.put(returned, 8, gate)
    r.handlers[LOCK] = lambda _a: 0
    r.handlers[UNLOCK] = lambda _a: None

    def snapshot_call(a: tuple[int, ...]) -> int:
        assert a[0] == manager
        r.put(a[1], 8, temporary)
        return returned

    r.handlers[SNAPSHOT] = snapshot_call
    return output, manager, snapshot, returned, temporary


def test_options_gate_reads_returned_slot_cleanup_reads_fixed_current_home() -> None:
    r = Rig()
    output, manager, snapshot, _returned, temporary = setup_resource(r)
    assert r.invoke(OPTIONS, 0, output) == output
    assert r.calls(LOCK) == [(manager + 8,)] and r.calls(UNLOCK) == [(manager + 8,)]
    assert r.calls(RELEASE) == [(temporary,), (snapshot,)]
    assert r.local_word(0x20, 4) == 9
    assert not r.calls(CONVERT)


@pytest.mark.parametrize("status,max_count,code", [(1, False, 5), (1 << 40, True, 6)])
def test_options_lock_low_eax_error_and_repair_prefix(
    status: int,
    max_count: bool,
    code: int,
) -> None:
    r = Rig()
    output, manager, _snapshot, _returned, _temporary = setup_resource(r)
    r.handlers[LOCK] = lambda _a: status
    if max_count:
        r.put(manager + 8 + 0x4C, 4, 0x7FFFFFFF)
    r.handlers[THROW] = lambda _a: None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.invoke(OPTIONS, 0, output)
    assert r.calls(THROW) == [(code,)] and not r.calls(UNLOCK)
    assert r.get(manager + 8 + 0x4C, 4) == (0x7FFFFFFE if max_count else 0)
    assert r.events[-1][0] == "local-"


@pytest.mark.parametrize("index", [-1, 0, 1])
def test_options_true_gate_fresh_manager_selection_and_held_destination(index: int) -> None:
    r = Rig()
    output, first, snapshot, _returned, temporary = setup_resource(r, gate=1)
    second, rows, array, selected = r.alloc(0x60), r.alloc(0x30), r.alloc(8), r.alloc(8)
    converted, destination, changed, transfer = (r.alloc(8) for _ in range(4))
    r.put(second, 8, rows)
    r.put(rows + 0x1C, 4, index)
    r.put(rows + 0x20, 8, array)
    r.put(rows + 0x28, 8, array + 8)
    r.put(array, 8, selected)

    def release(a: tuple[int, ...]) -> None:
        if a == (snapshot,):
            r.put(RESOURCE, 8, second)
            r.put(output, 8, destination)

    r.handlers[RELEASE] = release
    r.handlers[CONVERT] = lambda _a: converted

    def temp(a: tuple[int, ...]) -> int:
        assert a[0] == converted
        r.put(output, 8, changed)
        return transfer

    r.handlers[TEMP] = temp
    r.handlers[APPLY] = lambda _a: None
    assert r.invoke(OPTIONS, 0x987, output) == output
    assert r.calls(LOCK) == [(first + 8,), (second + 8,)]
    assert r.calls(CONVERT) == [(selected if index == 0 else 0,)]
    assert r.calls(APPLY) == [(destination, transfer)]
    assert r.calls(RELEASE) == [(temporary,), (snapshot,)] + (
        [(selected,)] if index == 0 else []
    ) + [(rows,), (converted,)]
    assert r.get(output) == changed


def setup_ui(r: Rig) -> tuple[int, int, int, int]:
    cast, payload, control, vptr = r.alloc(0x150), r.alloc(8), r.alloc(0x10), r.alloc(0x10)
    r.put(GAME, 8, 0x1234)
    r.put(cast + 0x140, 8, payload)
    r.put(cast + 0x148, 8, control)
    r.put(control, 8, vptr)
    r.put(control + 8, 4, 1)
    r.put(control + 12, 4, 1)
    r.handlers[SCREEN] = lambda a: 0x765 if a == (0x1234,) else pytest.fail("ignored Game used")

    def rtti(a: tuple[int, ...]) -> int:
        assert a[:4] == (0x765, 0, 0x1441754C8, 0x144120A20)
        assert r.get(a[4]) == 0xB2B2B2B200000000
        return cast

    r.channels["rtti", RTTI] = rtti
    r.handlers[ACTION] = lambda _a: None
    return cast, payload, control, vptr


def test_ui_null_cast_keeps_pair_seed_and_binds_after_actual_selector() -> None:
    r = Rig()
    setup_ui(r)
    r.channels["rtti", RTTI] = lambda _a: 0
    assert r.invoke(UI, U64) is None
    assert [e[0] for e in r.events[:3]] == ["read", "normal", "local+"]
    assert r.calls(SCREEN) == [(0x1234,)]
    assert bytes(r.locals[-1][1][0x30:0x40]) == b"\xb2" * 16
    assert not any(e[0] == "atomic" for e in r.events)
    assert not r.calls(ACTION)


def test_ui_first_control_acquire_second_control_release_and_fresh_weak_vptr() -> None:
    r = Rig()
    cast, _payload, first, _vptr = setup_ui(r)
    second, payload2, vptr2, new_vptr, other = (
        r.alloc(0x10),
        r.alloc(8),
        r.alloc(0x10),
        r.alloc(0x10),
        r.alloc(0x10),
    )
    r.put(first + 8, 4, 7)
    r.put(second, 8, vptr2)
    r.put(second + 8, 4, 1)
    r.put(second + 12, 4, 1)
    r.put(vptr2, 8, 0xD000)
    r.put(vptr2 + 8, 8, 0xD008)
    r.put(new_vptr + 8, 8, 0xD108)

    def atomic(a: int, value: int, _old: int) -> None:
        if a == first + 8 and value == 1:
            r.put(cast + 0x148, 8, second)
            r.put(cast + 0x140, 8, payload2)

    r.after_atomic = atomic
    r.ignore_increment_prior = True

    def action(a: tuple[int, ...]) -> int:
        assert a == (payload2,)
        r.put(r.locals[-1][0] + 0x38, 8, other)
        return -1

    r.handlers[ACTION] = action
    r.handlers[0xD000] = lambda _a: r.put(second, 8, new_vptr)
    r.handlers[0xD108] = lambda _a: None
    assert r.invoke(UI, 0xBAD) is None
    assert [e for e in r.events if e[0] == "atomic"] == [
        ("atomic", first + 8, 1, 7),
        ("atomic", second + 8, U32, 1),
        ("atomic", second + 12, U32, 1),
    ]
    assert r.calls(0xD000) == [(second,)] and r.calls(0xD108) == [(second,)]
    assert not r.calls(0xD008) and r.local_word(0x38) == other
    assert r.get(first + 8, 4) == 8 and r.get(second + 8, 4) == 0


@pytest.mark.parametrize("payload_present,control_present", [(False, True), (True, False)])
def test_ui_payload_and_control_are_independent(
    payload_present: bool,
    control_present: bool,
) -> None:
    r = Rig()
    cast, payload, control, _vptr = setup_ui(r)
    if not payload_present:
        r.put(cast + 0x140, 8, 0)
    if not control_present:
        r.put(cast + 0x148, 8, 0)
    assert r.invoke(UI, 0) is None
    assert r.calls(ACTION) == ([(payload,)] if payload_present else [])
    assert len([e for e in r.events if e[0] == "atomic"]) == (2 if control_present else 0)
    assert r.get(control + 8, 4) == 1


def test_ui_missing_atomic_refuses_after_pair_zero_before_payload_read() -> None:
    r = Rig()
    cast, _payload, _control, _vptr = setup_ui(r)
    r.bound = r.bind(ReplayUnitAIMapAtomics(None, None))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.invoke(UI, 0)
    assert r.local_word(0x30, 16) == 0 and not r.calls(ACTION)
    assert ("read", cast + 0x140, 8) not in r.events
    assert r.events[-1][0] == "local-"


@pytest.mark.parametrize("result", [None, -1, 1 << 64, True])
def test_ui_consumed_rtti_pointer_requires_actual_raw_rax(result: int | None) -> None:
    r = Rig()
    setup_ui(r)
    r.channels["rtti", RTTI] = lambda _a: result
    with pytest.raises(ValueError):
        r.invoke(UI, 0)
    assert bytes(r.locals[-1][1][0x30:0x40]) == b"\xb2" * 16


def test_empty_finished_tile_reads_inputs_before_local_and_skips_member_constants() -> None:
    r = Rig()
    world, map_, _tile = r.tile()
    assert r.invoke(TILE, U64, world, 0, 0) is None
    assert r.events[:3] == [
        ("read", world + 0x98, 8),
        ("read", map_ + 8, 8),
        ("local+", r.locals[0][0], 0x68),
    ]
    assert r.local_word(0x4C, 4) == 0 and r.local_word(0x50, 4) == 0
    assert r.local_word(0x60) == world
    assert not any(e[0] == "read" and e[1] in (ONE, SIXTY, HALF) for e in r.events)
    assert not r.calls(FINAL)


@pytest.mark.parametrize(
    "x,y,null_base", [(0, 0, True), (U32, 0, False), (0, U32, False), (1, 0, False), (0, 1, False)]
)
def test_failed_tile_selection_keeps_native_null_access_prefix(
    x: int,
    y: int,
    null_base: bool,
) -> None:
    r = Rig()
    world, map_, _tile = r.tile()
    if null_base:
        r.put(map_ + 8, 8, 0)
    with pytest.raises(ReplayMemoryError):
        r.invoke(TILE, 0, world, x, y)
    assert r.local_word(0x4C, 4) == y and r.local_word(0x50, 4) == x
    assert r.local_word(0x60) == world
    assert ("read", 0x1B, 1) in r.events and r.events[-1][0] == "local-"


@pytest.mark.parametrize("skip", ["null", "kind", "category"])
def test_tile_member_skip_arms(skip: str) -> None:
    r = Rig()
    world, _map, tile = r.tile()
    unit, _master, _vptr = r.unit(
        kind=0x64D if skip == "kind" else 7, category=0x50 if skip == "category" else 0x46
    )
    r.put(unit + 0x868, 8, 1)
    r.members(tile, (0 if skip == "null" else unit,))
    assert r.invoke(TILE, 0, world, 0, 0) is None
    assert not r.calls(B8, "b8") and not r.calls(A8)
    assert not any(e[0] == "owner" for e in r.events)


@pytest.mark.parametrize("health", [0, 0x80000000, 0x3F800000, 0x7FC01234, 0xFF800000])
def test_tile_reset_comiss_low_or_unordered_retains_upper_home_and_full_607(health: int) -> None:
    r = Rig()
    world, _map, tile = r.tile()
    unit, _master, _vptr = r.unit(health=health)
    r.members(tile, (unit,))
    r.handlers[A8] = lambda _a: -1
    assert r.invoke(TILE, 0, world, 0, 0) is None
    word = 0xC3C3C3C300000000
    assert r.local_word(0x58) == word
    assert r.get(unit + 0x130) == (((word + HP_ADD) & U64) ^ HP_XOR)
    assert r.calls(A8) == [(unit, 0x607)] and not r.calls(B8, "b8")


def test_tile_reset_reads_current_upper_word_after_partial_zero_store() -> None:
    r = Rig()
    world, _map, tile = r.tile()
    unit, _master, _vptr = r.unit(health=0)
    r.members(tile, (unit,))

    def after(a: int, n: int, _v: int) -> None:
        base = r.locals[-1][0]
        if (a, n) == (base + 0x58, 4):
            r.put(base + 0x5C, 4, 0xDEADBEEF)

    r.after_write = after
    r.handlers[A8] = lambda _a: None
    assert r.invoke(TILE, 0, world, 0, 0) is None
    assert r.get(unit + 0x130) == (((0xDEADBEEF00000000 + HP_ADD) & U64) ^ HP_XOR)


@pytest.mark.parametrize(
    "attribute,word", [(-1, 0x3F800000), (60, 0x3F800000), (61, 0x3F822222), (120, 0x40000000)]
)
def test_tile_b8_signed_attribute_and_binary32_argument(attribute: int, word: int) -> None:
    r = Rig()
    world, _map, tile = r.tile()
    unit, _master, _vptr = r.unit(attribute=attribute)
    r.members(tile, (unit,))
    r.channels["b8", B8] = lambda _a: None
    assert r.invoke(TILE, 0, world, 0, 0) is None
    assert r.calls(B8, "b8") == [(unit, word)] and not r.calls(A8)


def test_tile_b8_holds_target_but_redecodes_attribute_on_greater_arm() -> None:
    r = Rig()
    world, _map, tile = r.tile()
    unit, master, vptr = r.unit(attribute=61)
    other_vptr = r.alloc(0xC0)
    r.put(other_vptr + 0xB8, 8, 0xDDB8)
    r.members(tile, (unit,))

    def after(a: int, _n: int) -> None:
        if a == master + 0x68:
            r.put(master + 0x68, 8, 120 ^ ATTR_XOR)
        if a == vptr + 0xB8:
            r.put(unit, 8, other_vptr)

    r.after_read = after
    r.channels["b8", B8] = lambda _a: None
    assert r.invoke(TILE, 0, world, 0, 0) is None
    assert r.calls(B8, "b8") == [(unit, 0x40000000)]
    assert not r.calls(0xDDB8, "b8")


@pytest.mark.parametrize("initial_attribute", [60, 120])
def test_tile_owner_event_uses_post_b8_state_held_receiver_and_partial_homes(
    initial_attribute: int,
) -> None:
    r = Rig()
    world, _map, tile = r.tile()
    unit, master, _vptr = r.unit(attribute=initial_attribute)
    owner, owner_vptr, other = r.alloc(8), r.alloc(0x300), r.alloc(8)
    r.put(owner, 8, owner_vptr)
    r.put(owner_vptr + 0x2F8, 8, OWNER)
    r.put(unit + 0x18, 8, owner)
    r.members(tile, (unit,))

    def b8(_a: tuple[int, ...]) -> None:
        r.put(master + 8, 1, 0x46)
        r.put(master + 0x379, 1, 1)
        r.put(master + 0x68, 8, (U64 - 1) ^ ATTR_XOR)
        r.put(unit + 8, 4, U32)
        r.put(unit + 0x130, 8, ((0x40B00000 + HP_ADD) & U64) ^ HP_XOR)

    r.channels["b8", B8] = b8

    def after(a: int, _n: int) -> None:
        if a == owner_vptr + 0x2F8:
            r.put(unit + 0x18, 8, other)
            r.put(owner_vptr + 0x2F8, 8, 0xD2F8)

    r.after_read = after

    def owner_call(a: tuple[int, ...]) -> None:
        base = r.locals[-1][0]
        assert a == (owner, U32, U32, 0x213, base + 0x20, base + 0x28, base + 0x30)
        assert [r.get(p) for p in a[4:]] == [
            0xC3C3C3C3FFFFFFFF,
            0xC3C3C3C300000005,
            0xC3C3C3C3FFFFFFFE,
        ]

    r.channels["owner", OWNER] = owner_call
    assert r.invoke(TILE, 0, world, 0, 0) is None
    homes = [
        (e[1] - r.locals[-1][0], e[2])
        for e in r.events
        if e[0] == "write" and e[1] in (r.locals[-1][0] + i for i in (0x20, 0x28, 0x30))
    ]
    assert homes[-3:] == [(0x30, 4), (0x28, 4), (0x20, 4)]


@pytest.mark.parametrize("category,bit", [(0x45, 1), (0x46, 0)])
def test_tile_owner_event_post_b8_gates(category: int, bit: int) -> None:
    r = Rig()
    world, _map, tile = r.tile()
    unit, master, _vptr = r.unit()
    r.members(tile, (unit,))
    r.put(master + 8, 1, category)
    r.put(master + 0x379, 1, bit)
    r.channels["b8", B8] = lambda _a: None
    assert r.invoke(TILE, 0, world, 0, 0) is None
    assert len(r.calls(B8, "b8")) == 1 and not any(e[0] == "owner" for e in r.events)


def test_tile_member_array_and_count_are_current_but_fp_constants_are_held() -> None:
    r = Rig()
    world, _map, tile = r.tile()
    first, _master1, _vptr1 = r.unit()
    second, _master2, _vptr2 = r.unit()
    r.members(tile, (first,))
    replacement = r.alloc(16)
    r.put(replacement + 8, 8, second)

    def b8(a: tuple[int, ...]) -> None:
        if a[0] == first:
            r.put(tile + 0x28, 8, replacement)
            r.put(tile + 0x1B, 1, 2)
            r.put(ONE, 4, 0x41200000)
            r.put(SIXTY, 4, 0x3F800000)
        else:
            r.put(tile + 0x1B, 1, 1)

    r.channels["b8", B8] = b8
    assert r.invoke(TILE, 0, world, 0, 0) is None
    assert r.calls(B8, "b8") == [(first, 0x3F800000), (second, 0x3F800000)]
    for address in (ONE, SIXTY):
        assert r.events.count(("read", address, 4)) == 1


@pytest.mark.parametrize("nonempty", [False, True])
def test_tile_tail_reloads_homes_only_after_member_pass_and_routes_owned_setters(
    nonempty: bool,
) -> None:
    r = Rig()
    world, map_, tile = r.tile(kind=12)
    other_world, other_map = r.alloc(0x780), r.alloc(0x40)
    r.put(other_world + 0x98, 8, other_map)
    player, rows, vptr, new_vptr, entity = (
        r.alloc(8),
        r.alloc(8),
        r.alloc(0x1D0),
        r.alloc(0x1D0),
        r.alloc(0x170),
    )
    r.put(world + 0x768, 8, rows)
    r.put(other_world + 0x768, 8, rows)
    r.put(rows, 8, player)
    r.put(player, 8, vptr)
    r.put(vptr + 0x1C8, 8, PLAYER)
    r.put(new_vptr + 0x1C8, 8, 0xE1C8)

    def change_homes() -> None:
        base = r.locals[-1][0]
        r.put(base + 0x4C, 4, 4)
        r.put(base + 0x50, 4, 3)
        r.put(base + 0x60, 8, other_world)

    if nonempty:
        unit, _master, _unit_vptr = r.unit()
        r.members(tile, (unit,))
        r.channels["b8", B8] = lambda _a: change_homes()

    def after_write(a: int, n: int, _v: int) -> None:
        base = r.locals[-1][0]
        if not nonempty and (a, n) == (base + 0x60, 8):
            change_homes()
        if (a, n) == (base + 0x48, 1):
            r.put(player, 8, new_vptr)
            r.put(vptr + 0x1C8, 8, 0xD1C8)
            # Synthetic callback proves final held flag register is distinct from current home30.
            r.put(base + 0x30, 8, 0xF00D)

    r.after_write = after_write
    half_reads = 0

    def after_read(a: int, _n: int) -> None:
        nonlocal half_reads
        if a == HALF:
            half_reads += 1
            if half_reads == 1:
                r.put(HALF, 4, 0x3E800000)

    r.after_read = after_read
    r.handlers[TILE310] = r.handlers[MAP_EFFECT] = lambda _a: None
    x, y = (3, 4) if nonempty else (0, 0)

    def player_call(a: tuple[int, ...]) -> int:
        base = r.locals[-1][0]
        assert a == (
            player,
            0x64D,
            0x40500000 if nonempty else 0x3E800000,
            0x40900000 if nonempty else 0x3F000000,
            base + 0x20,
            base + 0x28,
            base + 0x30,
            base + 0x48,
        )
        assert [r.get(p) for p in a[4:7]] == [0xC3C3C3C300000000, 0xC3C3C3C300000000, 0xF00D]
        # The high DWORD overlaps the independently changed y home at +4c.
        assert r.get(a[7]) == 0x00000004C3C3C301
        return entity

    r.channels["player", 0xD1C8] = player_call

    def final(a: tuple[int, ...]) -> None:
        assert a == (x, y, x, y)
        assert r.get(entity + 0x160, 2) == 12 and r.get(entity + 0x168, 4) == 0x42F00000

    r.handlers[FINAL] = final
    assert r.invoke(TILE, U64, world, 0, 0) is None
    assert r.calls(TILE310) == [(tile, U32)]
    assert r.calls(MAP_EFFECT) == [(other_map if nonempty else map_, y, x)]
    assert not r.calls(SET9) and not r.calls(SET39)
    assert r.get(tile + 9, 1) == 69 and r.get(tile + 0x39, 1) == 69
    assert r.get(tile + 0xE, 2) == 0xFFFF and r.get(tile + 0x3C, 2) == 0xFFFF
    assert r.get(tile + 0x15, 1) == 0xCC and r.get(tile + 0x18, 1) == 0
    assert half_reads == 2 and not r.calls(PLAYER, "player")
