"""Source-led caller controls; authored before candidate implementation.

All child services here are explicit authored capabilities for caller tests.
They are not native observations or proof of descendant implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_relationship_check import (
    bind_replay_player_relationship_check,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_update_player_links import (
    ReplayWorldUpdatePlayerLinks,
    ReplayWorldUpdatePlayerLinksReentry,
    run_replay_world_update_player_links,
)
from vantage.replay_world_update_player_pass import (
    ReplayWorldUpdatePlayerPass,
    run_replay_world_update_player_pass,
)

U32, U64 = (1 << 32) - 1, (1 << 64) - 1
MASTER1, MASTER2 = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
KIND1, KIND2 = 0x50A06BCECEBEF905, 0x5B32AA7995D95916
ID1, ID2 = 0x349E37847AD69F19, 0x47E37DFF0616CE4F
X1, X2 = 0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1
Y1, Y2 = 0x61501AA6ECFD980A, 0x6C5EAB60B426DD28
Z1, Z2 = 0x2B3719EF44DE99FF, 0x21D14A25ED7C802C
OPTIONS, STRONG, DESCRIPTOR = 0x140D6A530, 0x140990140, 0x14111B3A0
NODE, OWNER, FINAL, RELATION = 0x14110A5E0, 0x141691140, 0x141731F00, 0x141734D70
V0, V8, V80, V100 = 0xA000, 0xA008, 0xA080, 0xA100
V150, V1E8, V2E8, V330 = 0xA150, 0xA1E8, 0xA2E8, 0xA330
Handler = Callable[[int, tuple[int, ...]], int | None]
Channel = Callable[[int, tuple[int, ...], memoryview | None], int | None]


class Rig:
    def __init__(self, count: int = 1, outer: int = 0) -> None:
        self.memory = ReplayMemory(start=0x10000)
        self.events: list[tuple] = []
        self.after_read: Callable[[int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.handlers: dict[str, Handler] = {}
        self.world, self.frame = self.alloc(0xA00), self.alloc(0x400)
        self.players = [self.player() for _ in range(count)]
        self.begin = self.array(self.players, stride=16)
        self.header(self.begin, count)
        self.sentinel = self.alloc(0xE0)
        self.put(self.sentinel + 0xC8, 8, self.sentinel)
        self.put(self.sentinel + 0xD0, 8, self.sentinel)
        self.put(self.world + 0x50, 8, self.sentinel)
        self.put(self.world + 0x58, 4, 0)
        for offset, width in ((0x168, 8), (0x174, 4), (0x178, 8), (0x184, 4)):
            self.put(self.world + offset, width, 0)
        self.put(self.frame + 0x70, 1, 0)
        self.put(self.frame + 0x210, 4, outer)
        self.put(self.frame + 0x2B0, 8, self.players[outer])
        for inner in range(1, count):
            self.put(self.frame + 0x278 + inner * 4, 4, 0)
        self.game, self.option, self.option_slot = (
            self.alloc(0x700),
            self.alloc(0x80),
            self.alloc(8),
        )
        self.memory.map_bytes(0x144353698, self.game.to_bytes(8, "little"))
        self.put(self.option + 0x69, 1, 0)
        self.put(self.option_slot, 8, self.option)
        self.put(self.frame + 0xB0, 8, 0)
        self.descriptor = self.alloc(0x18)
        self.put(self.descriptor + 0x10, 8, 0)
        self.meta = (self.world, self.frame, 0x12345, 7, 9, 0x3F800001, 3)
        self.phase = ReplayWorldUpdatePlayerLinks(
            *self.meta,
            outer,
            self.players[outer],
            count,
            self.begin,
            0x447A0000,
            None,
            None,
            0x141629E00,
            None,
        )
        self.context = ReplayTaskRebuildStorage(self.world, self.read, self.write)
        self.channels = {
            key: ReplayTaskRebuildCalls(self.channel(key))
            for key in (
                "calls",
                "virtual_calls",
                "virtual_2e8_calls",
                "policy_home_calls",
                "position_home_calls",
                "relationship_calls",
            )
        }

    def alloc(self, size: int, fill: int = 0xA5) -> int:
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([fill]) * size)
        return address

    def put(self, address: int, width: int, value: int) -> None:
        self.memory.write(address & U64, width, value & ((1 << (width * 8)) - 1))

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

    def array(self, values: list[int], stride: int = 8) -> int:
        address = self.alloc(max(1, len(values)) * stride)
        for i, value in enumerate(values):
            self.put(address + i * stride, 8, value)
        return address

    def header(self, begin: int, count: int) -> None:
        self.put(self.world + 0x768, 8, begin)
        self.put(self.world + 0x770, 8, begin + count * 16)

    def player(self) -> int:
        player, table, units = self.alloc(0x700), self.alloc(0x340), self.alloc(0x20)
        self.put(player, 8, table)
        self.put(table + 0x100, 8, V100)
        self.put(table + 0x330, 8, V330)
        self.put(player + 0x648, 4, 0)
        self.put(player + 0x30, 8, units)
        self.put(player + 0x18, 8, 0xEE18)
        self.put(units + 0x10, 4, 0)
        return player

    def object(self, kind: int = 4, identity: int = 0, x: int = 0, y: int = 0, z: int = 0) -> int:
        unit, table, master = self.alloc(0x220), self.alloc(0x340), self.alloc(0x40)
        manager, manager_table = self.alloc(0x20), self.alloc(0x200)
        self.put(unit, 8, table)
        self.put(table + 0x150, 8, V150)
        self.put(table + 0x2E8, 8, V2E8)
        self.put(unit + 0x10, 8, master + MASTER1 + MASTER2)
        self.put(master + 0x38, 8, kind + KIND1 - KIND2)
        self.put(master + 0x18, 8, (identity + ID2) ^ ID1)
        self.put(unit + 0x170, 8, x + X1 - X2)
        self.put(unit + 0x178, 8, y + Y1 - Y2)
        self.put(unit + 0x180, 8, z - Z1 - Z2)
        self.put(unit + 0x18C, 4, 0)
        self.put(unit + 0xF, 1, 0)
        self.put(unit + 0x18, 8, self.players[0])
        self.put(unit + 0x1F0, 8, manager)
        self.put(manager, 8, manager_table)
        self.put(manager_table + 0x80, 8, V80)
        self.put(manager_table + 0x1E8, 8, V1E8)
        return unit

    def units(self, values: list[int], count: int | None = None) -> None:
        row = self.get(self.players[self.phase.outer_index] + 0x30)
        self.put(row + 8, 8, self.array(values))
        self.put(row + 0x10, 4, len(values) if count is None else count)
        self.put(self.frame + 0x70, 1, 1)

    def lookup(self, values: dict[int, int]) -> None:
        for negative, pointer_offset, count_offset in ((False, 0x168, 0x174), (True, 0x178, 0x184)):
            subset = {abs(k): v for k, v in values.items() if (k < 0) == negative}
            if subset:
                count = max(subset) + 1
                address = self.alloc(count * 8, fill=0)
                for key, value in subset.items():
                    self.put(address + key * 8, 8, value)
                self.put(self.world + pointer_offset, 8, address)
                self.put(self.world + count_offset, 4, count)

    def descriptors(self, ids: list[int]) -> None:
        address = self.alloc(max(1, len(ids)) * 4)
        for i, value in enumerate(ids):
            self.put(address + i * 4, 4, value)
        self.put(self.descriptor, 8, address)
        self.put(self.descriptor + 0x10, 8, len(ids))

    def grid(self, members: list[int], width: int = 1, height: int = 1) -> tuple[int, int]:
        grid, tile = self.alloc(0x40), self.alloc(0x40)
        self.put(self.world + 0x98, 8, grid)
        self.put(grid + 8, 8, tile)
        self.put(grid + 0x30, 4, width)
        self.put(grid + 0x34, 4, height)
        self.put(tile + 0x1B, 1, len(members))
        self.put(tile + 0x28, 8, self.array(members))
        self.put(self.option + 0x69, 1, 1)
        self.handlers["virtual_2e8_calls"] = lambda target, args: 1
        return grid, tile

    def channel(self, name: str) -> Channel:
        def invoke(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            self.events.append((name, target, args))
            if name in self.handlers:
                return self.handlers[name](target, args)
            if name == "calls":
                assert target in (OPTIONS, STRONG, DESCRIPTOR, NODE, OWNER, FINAL)
                return {
                    OPTIONS: self.option_slot,
                    DESCRIPTOR: self.descriptor,
                    NODE: 0,
                    OWNER: 0,
                }.get(target)
            if name == "virtual_2e8_calls":
                return 0
            if name == "policy_home_calls":
                return U32
            if name == "relationship_calls":
                return 1
            return None

        return invoke

    def run(self, phase: object | None = None, **overrides: object) -> object:
        channels = self.channels | overrides
        calls = channels.pop("calls")
        mxcsr = channels.pop("mxcsr", 0x1F80)
        return run_replay_world_update_player_pass(
            self.context,
            calls,
            self.phase if phase is None else phase,
            **channels,
            mxcsr=mxcsr,
        )

    def invocations(self, name: str) -> list[tuple[int, tuple[int, ...]]]:
        return [(event[1], event[2]) for event in self.events if event[0] == name]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("next_address", 0x14162AB9E),
        ("next_address", True),
        ("returned_status", 0),
        ("world", -1),
        ("logical_frame", 1 << 64),
        ("held_r13", True),
        ("raw_count", -1),
        ("held_begin", None),
        ("xmm8_word", None),
        ("outer_index", 1 << 32),
        ("inner_index", -1),
        ("marker_address", 1 << 64),
        ("entry_time", True),
        ("cycle", -1),
        ("status", 1 << 32),
        ("default_time", -1),
        ("control_flags", True),
    ],
)
def test_invalid_boundary_rejects_before_effects(field: str, value: object) -> None:
    rig = Rig()
    with pytest.raises(ValueError):
        rig.run(replace(rig.phase, **{field: value}))
    assert rig.events == []


@pytest.mark.parametrize("mxcsr", [True, None, 0x1F81, 0x1FC0, 0x9F80, 0])
def test_explicit_arithmetic_profile_admission(mxcsr: object) -> None:
    rig = Rig()
    with pytest.raises(ValueError):
        rig.run(mxcsr=mxcsr)
    assert rig.events == []


@pytest.mark.parametrize(
    "channel",
    [
        "calls",
        "virtual_calls",
        "virtual_2e8_calls",
        "policy_home_calls",
        "position_home_calls",
        "relationship_calls",
    ],
)
def test_channel_container_admission(channel: str) -> None:
    rig = Rig()
    with pytest.raises(ValueError):
        rig.run(**{channel: None})
    assert rig.events == []


def test_false_gate_preserves_held_selected_and_outer_before_delayed_pass() -> None:
    rig = Rig(2)
    other = rig.player()
    rig.put(rig.frame + 0x2B0, 8, other)
    rig.put(rig.frame + 0x210, 4, 1)
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerLinksReentry)
    assert output.outer_index == 1 and output.xmm8_word == rig.phase.xmm8_word
    assert rig.events[0] == ("read", rig.frame + 0x70, 1)
    # Markers are inactive; these aliases cannot create legitimate later reads.
    assert not any(
        e[0] == "read" and e[1] in {rig.frame + o for o in (0x208, 0x78, 0x2B0, 0x210)}
        for e in rig.events
    )
    assert ("read", rig.players[0] + 0x648, 4) in rig.events
    assert ("read", other + 0x648, 4) not in rig.events
    assert rig.invocations("virtual_calls") == [(V100, (rig.players[0],))]
    assert rig.invocations("calls") == [(FINAL, (rig.players[0] + 0xA0,))]


@pytest.mark.parametrize("count", [0, 0x80000000, U32])
@pytest.mark.parametrize("gate", [1, 255])
def test_true_nonpositive_uses_current_selected_without_outer_restore(
    count: int,
    gate: int,
) -> None:
    rig = Rig(2)
    rig.units([], count)
    rig.put(rig.frame + 0x70, 1, gate)
    rig.put(rig.frame + 0x210, 4, 1)
    rig.put(rig.frame + 0x2B0, 8, rig.players[1])
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerLinksReentry)
    assert output.outer_index == 1
    assert rig.get(rig.frame + 0x208) == 0xA5A5A5A500000000
    assert rig.get(rig.frame + 0x78) == 0
    assert ("read", rig.frame + 0x210, 4) not in rig.events
    assert ("read", rig.players[1] + 0x648, 4) in rig.events
    assert rig.invocations("virtual_calls") == [(V100, (rig.players[0],))]


def test_actual_postpass_boundary_and_historical_metadata() -> None:
    rig = Rig()
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerPass)
    assert (
        output.world,
        output.logical_frame,
        output.entry_time,
        output.cycle,
        output.status,
        output.default_time,
        output.control_flags,
    ) == rig.meta
    assert (
        output.outer_index,
        output.held_r13,
        output.raw_count,
        output.xmm8_word,
        output.next_address,
        output.returned_status,
    ) == (
        1,
        Y1,
        1,
        0x447A0000,
        0x14162AB9E,
        None,
    )
    assert not hasattr(output, "held_begin")
    assert rig.get(rig.frame + 0x210, 4) == 1


def test_unavailable_dedicated_channel_refuses_at_reached_site() -> None:
    rig = Rig()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.run(virtual_calls=ReplayTaskRebuildCalls(None))
    assert rig.events[:2] == [
        ("read", rig.frame + 0x70, 1),
        ("read", rig.world + 0x50, 8),
    ]
    assert rig.invocations("calls") == []
    assert rig.get(rig.frame + 0x210, 4) == 0


@pytest.mark.parametrize("reload", [False, True])
def test_unit_r8_carry_and_a95a_current_reload_are_distinct(reload: bool) -> None:
    rig = Rig()
    unit = rig.object(kind=4 if reload else 2)
    rig.units([unit])
    if reload:

        def gate(target: int, args: tuple[int, ...]) -> int:
            assert target == V2E8
            assert args == (unit, (rig.begin & ~255) | 1, U64)
            rig.put(rig.frame + 0x68, 8, 0x50)
            return 0

        rig.handlers["virtual_2e8_calls"] = gate
    else:

        def mutate(address: int, width: int, value: int) -> None:
            if address == rig.frame + 0x250:
                rig.put(rig.frame + 0x68, 8, 0x50)

        rig.after_write = mutate
    rig.run()
    assert rig.get(rig.frame + 0x68) == (0x58 if reload else 8)
    assert rig.get(rig.frame + 0x208, 4) == 1
    assert not rig.invocations("policy_home_calls")


@pytest.mark.parametrize("al", [0x80, 255])
def test_first_gate_uses_whole_al_and_actual_options(al: int) -> None:
    rig = Rig()
    unit = rig.object(kind=0x15)
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: al
    rig.run()
    assert (OPTIONS, (rig.game, rig.frame + 0xB0)) in rig.invocations("calls")
    assert len(rig.invocations("policy_home_calls")) == 1


def test_first_nonnull_gate_is_current_and_skips_options_when_null() -> None:
    rig = Rig()
    unit = rig.object()
    rig.units([unit])

    def gate(target: int, args: tuple[int, ...]) -> int:
        rig.put(unit + 0x1F0, 8, 0)
        return 1

    rig.handlers["virtual_2e8_calls"] = gate
    rig.run()
    assert not rig.invocations("policy_home_calls")
    assert all(t != OPTIONS for t, _ in rig.invocations("calls"))


@pytest.mark.parametrize("al", [0, 0x80])
@pytest.mark.parametrize("second_al", [0, 0x80])
@pytest.mark.parametrize("manager_present", [False, True])
def test_owner_signed_word_and_later_partial_rdx(
    al: int,
    second_al: int,
    manager_present: bool,
) -> None:
    rig = Rig()
    unit = rig.object(kind=2, identity=0x8001)
    rig.put(unit + 0xF, 1, 0x50)
    rig.put(rig.players[0] + 0x648, 4, 0xFEDCBA98)
    rig.units([unit])

    def direct(target: int, args: tuple[int, ...]) -> int | None:
        if target == OWNER:
            assert args == (rig.world, 0xFEDCBA98, 0xFFFF8001, 0x99)
            rig.put(rig.frame + 0x68, 8, 0x50)
            return al
        assert target == FINAL
        return None

    rig.handlers["calls"] = direct

    def second_gate(target: int, args: tuple[int, ...]) -> int:
        if not manager_present:
            rig.put(unit + 0x1F0, 8, 0)
        return second_al

    rig.handlers["virtual_2e8_calls"] = second_gate
    rig.run()
    assert rig.get(rig.frame + 0x68) == 0x58
    assert rig.invocations("virtual_2e8_calls") == ([(V2E8, (unit, 1, 255))] if al else [])
    assert any(t == V1E8 for t, _ in rig.invocations("virtual_calls")) == bool(
        al and second_al and manager_present
    )


@pytest.mark.parametrize("kind", [4, 0x15])
def test_policy_prepared_gp_live_homes_and_raw_default(kind: int) -> None:
    rig = Rig()
    unit = rig.object(kind=kind)
    rig.units([unit])
    rig.phase = replace(rig.phase, default_time=0x7FC01234)
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    seen: list[tuple[int, ...]] = []

    def policy(target: int, args: tuple[int, ...]) -> int:
        assert target == V80 and len(args) == 8
        receiver, rdx, r8, r9, h20, h28, h30, h38 = args
        assert receiver == rig.get(unit + 0x1F0)
        assert (r8, r9) == (U32, U32)
        assert (h20, h28, h30, h38) == tuple(rig.frame + o for o in (0x20, 0x28, 0x30, 0x38))
        assert rig.get(h28) == 0xA5A5A5A500000002
        assert rig.get(h30) == rig.get(h38) == 0xA5A5A5A57FC01234
        output = rig.frame + (0x208 if kind == 0x15 else 0x200)
        assert rig.get(h20) == output
        expected = (
            ((output & ~255) | 2)
            if kind == 0x15
            else (0 if not seen else ((output & ~255) | len(seen)))
        )
        assert rdx == expected
        seen.append(args)
        return U32

    rig.handlers["policy_home_calls"] = policy
    rig.run()
    assert len(seen) == (1 if kind == 0x15 else 6)


@pytest.mark.parametrize("value", [None, -1, 1 << 32])
def test_unused_policy_eax_annotations_stay_opaque(value: int | None) -> None:
    rig = Rig()
    unit = rig.object()
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    rig.handlers["policy_home_calls"] = lambda target, args: value
    rig.run()
    assert len(rig.invocations("policy_home_calls")) == 6


@pytest.mark.parametrize("winner", range(6))
@pytest.mark.parametrize("value", [None, -1, 1 << 32])
def test_conditional_eax_validation_preserves_query5_store_order(
    winner: int,
    value: int | None,
) -> None:
    rig = Rig()
    unit = rig.object()
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1

    def policy(target: int, args: tuple[int, ...]) -> int | None:
        ordinal = len(rig.invocations("policy_home_calls")) - 1
        if ordinal == winner:
            rig.put(rig.frame + 0x200, 4, 0xFFFFFFFF)
        return value

    rig.handlers["policy_home_calls"] = policy
    with pytest.raises(ValueError):
        rig.run()
    assert len(rig.invocations("policy_home_calls")) == winner + 1
    assert rig.get(rig.frame + 0x208, 4) == (U32 if winner == 5 else 0x63)


@pytest.mark.parametrize("value", [None, -1, 1 << 32])
def test_kind15_eax_is_unconditionally_consumed(value: int | None) -> None:
    rig = Rig()
    unit = rig.object(kind=0x15)
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    rig.handlers["policy_home_calls"] = lambda target, args: value
    with pytest.raises(ValueError):
        rig.run()
    assert len(rig.invocations("policy_home_calls")) == 1


@pytest.mark.parametrize("identity", [U32, 0x80000000, 100])
def test_policy_id_skip_gates(identity: int) -> None:
    rig = Rig()
    unit = rig.object(kind=0x15)
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    rig.handlers["policy_home_calls"] = lambda target, args: identity
    rig.run()
    assert not rig.invocations("position_home_calls")


@pytest.mark.parametrize("identity", [0, -2])
def test_policy_id_resolves_actual_object_and_shared_decode_join(identity: int) -> None:
    rig = Rig()
    unit = rig.object(kind=0x15)
    target = rig.object(kind=0x31, x=0x40400000, y=0x40800000, z=0x3F800000)
    rig.lookup({identity: target})
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda address, args: 1
    rig.handlers["policy_home_calls"] = lambda address, args: identity & U32
    rig.run()
    assert rig.invocations("position_home_calls") == [
        (V150, (unit, target, 0x40400000, 0x40800000, rig.frame + 0x20)),
    ]
    assert rig.get(rig.frame + 0x20, 4) == 0x3F800000


@pytest.mark.parametrize("grid_route", [False, True])
def test_position_early_target_and_distinct_fp_home_sample_order(grid_route: bool) -> None:
    rig = Rig()
    unit = rig.object(kind=4 if grid_route else 0x15)
    target = rig.object(kind=0x31, x=0x40400000, y=0x40800000, z=0x3F800000)
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda address, args: 1
    if grid_route:
        rig.grid([target])
    else:
        rig.lookup({0: target})
        rig.handlers["policy_home_calls"] = lambda address, args: 0
    table = rig.get(unit)

    def mutate(address: int, width: int, value: int) -> None:
        if address == rig.frame + 0x60 and width == 8:
            rig.put(table + 0x150, 8, 0xB150)
        if address == rig.frame + 0x20 and width == 4:
            rig.put(rig.frame + (0x60 if grid_route else 0x88), 4, 0x41000000)
            rig.put(rig.frame + (0x88 if grid_route else 0x238), 4, 0x41100000)
            rig.put(address, 4, 0x41200000)

    # The initial decode precedes capture; arm target mutation only on target180.
    armed = False

    def read_hook(address: int, width: int) -> None:
        nonlocal armed
        if address == target + 0x180:
            armed = True

    rig.after_read = read_hook

    def write_hook(address: int, width: int, value: int) -> None:
        if armed:
            mutate(address, width, value)

    rig.after_write = write_hook
    rig.run()
    calls = rig.invocations("position_home_calls")
    assert len(calls) == 1 and calls[0][0] == V150
    expected = (0x41000000, 0x41100000) if grid_route else (0x40400000, 0x40800000)
    assert calls[0][1] == (unit, target, *expected, rig.frame + 0x20)
    assert rig.get(rig.frame + 0x20, 4) == 0x41200000


@pytest.mark.parametrize("threshold", [0x41C80000, 0x7FC01234, 0x447A0000])
def test_nearest_strict_ordered_distance_and_ties(threshold: int) -> None:
    rig = Rig()
    unit = rig.object()
    first = rig.object(x=0x40400000, y=0x40800000)
    second = rig.object(x=0x40400000, y=0x40800000)
    rig.lookup({0: first, 1: second})
    rig.descriptors([0, 1])
    rig.units([unit])
    rig.phase = replace(rig.phase, xmm8_word=threshold)
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    rig.run()
    positions = rig.invocations("position_home_calls")
    assert bool(positions) == (threshold == 0x447A0000)
    if positions:
        assert positions[0][1][1] == first


def test_nearest_minus1_negative_lookup_differs_from_policy_minus1() -> None:
    rig = Rig()
    unit, candidate = rig.object(), rig.object(x=0x3F800000)
    rig.lookup({-1: candidate})
    rig.descriptors([U32])
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    rig.run()
    assert rig.invocations("position_home_calls")[0][1][1] == candidate


def test_nearest_invalid_candidate_is_dereferenced() -> None:
    rig = Rig()
    unit = rig.object()
    rig.descriptors([0x80000000])
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    with pytest.raises(ReplayMemoryError):
        rig.run()
    assert rig.events[-1] == ("read", 0x18C, 4)
    assert not rig.invocations("policy_home_calls")


@pytest.mark.parametrize("word", [0xBF800000, 0x7FC01234, 0x7F800000, 0x4F000000])
def test_invalid_grid_access_retains_literal_null_read(word: int) -> None:
    rig = Rig()
    unit = rig.object(y=word)
    rig.units([unit])
    rig.grid([])
    with pytest.raises(ReplayMemoryError):
        rig.run()
    assert rig.events[-1] == ("read", 0x1B, 1)
    assert not rig.invocations("policy_home_calls")


def delayed_node(rig: Rig, owner: int = 0) -> int:
    node, table = rig.alloc(0xE0), rig.alloc(0x10)
    rig.put(node, 8, table)
    rig.put(table, 8, V0)
    rig.put(table + 8, 8, V8)
    rig.put(node + 0xC8, 8, rig.sentinel)
    rig.put(node + 0xD0, 8, rig.sentinel)
    rig.put(node + 0xDC, 4, owner)
    rig.put(rig.sentinel + 0xC8, 8, node)
    rig.put(rig.sentinel + 0xD0, 8, node)
    rig.put(rig.world + 0x58, 4, 1)
    return node


def test_delayed_owner_mismatch_skips_calls() -> None:
    rig = Rig()
    node = delayed_node(rig, owner=1)
    rig.run()
    assert all(target != NODE for target, _ in rig.invocations("calls"))
    assert rig.invocations("virtual_calls") == [(V100, (rig.players[0],))]
    next_read = rig.events.index(("read", node + 0xC8, 8))
    owner_read = rig.events.index(("read", node + 0xDC, 4))
    assert next_read < owner_read
    assert rig.get(rig.world + 0x58, 4) == 1


def test_delayed_whole_eax_uses_current_virtual8_and_held_next() -> None:
    rig = Rig()
    node = delayed_node(rig)
    new_table = rig.alloc(0x10)
    rig.put(new_table + 8, 8, 0xB008)

    def direct(target: int, args: tuple[int, ...]) -> int | None:
        if target == NODE:
            rig.put(node, 8, new_table)
            rig.put(node + 0xC8, 8, 0xBAD)
            return 0x100  # EAX true even though AL is zero.
        assert target == FINAL
        return -1  # Ignored returns stay opaque.

    rig.handlers["calls"] = direct
    rig.run()
    assert rig.invocations("virtual_calls") == [(0xB008, (node,)), (V100, (rig.players[0],))]
    assert rig.get(rig.world + 0x58, 4) == 1


def test_delayed_unlink_four_current_link_reads_and_counter_wrap() -> None:
    rig = Rig()
    node = delayed_node(rig)
    previous, following = rig.alloc(0xE0), rig.alloc(0xE0)
    rig.put(rig.world + 0x58, 4, 0)

    def mutate(address: int, width: int, value: int) -> None:
        if address == rig.sentinel + 0xD0:
            rig.put(node + 0xD0, 8, previous)
            rig.put(node + 0xC8, 8, following)

    rig.after_write = mutate
    rig.run()
    assert rig.get(rig.world + 0x58, 4) == U32
    assert rig.get(rig.sentinel + 0xD0) == rig.sentinel
    assert rig.get(previous + 0xC8) == following
    assert rig.invocations("virtual_calls") == [(V0, (node, 1)), (V100, (rig.players[0],))]
    call = rig.events.index(("calls", NODE, (node,)))
    relevant = [
        e
        for e in rig.events[call + 1 :]
        if e[0] == "read"
        and e[1]
        in {
            node + 0xC8,
            node + 0xD0,
        }
    ]
    assert relevant == [("read", node + o, 8) for o in (0xC8, 0xD0, 0xD0, 0xC8)]


def test_delayed_bottom_uses_fresh_sentinel() -> None:
    rig = Rig()
    node = delayed_node(rig)
    new_sentinel = rig.alloc(0xE0)
    rig.put(node + 0xC8, 8, new_sentinel)

    def direct(target: int, args: tuple[int, ...]) -> int | None:
        if target == NODE:
            rig.put(rig.world + 0x50, 8, new_sentinel)
            return 1
        assert target == FINAL
        return None

    rig.handlers["calls"] = direct
    rig.run()
    assert ("read", new_sentinel + 0xC8, 8) not in rig.events


@pytest.mark.parametrize("answers", [(0,), (1, 0), (0x80, 255)])
def test_marker_relationship_al_outcomes_and_original_marker(answers: tuple[int, ...]) -> None:
    rig = Rig(4, outer=1)
    rig.put(rig.players[1] + 0x648, 4, 1)
    marker = rig.frame + 0x27C
    rig.put(marker, 4, 7)
    remaining = list(answers)
    rig.handlers["relationship_calls"] = lambda target, args: remaining.pop(0)
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerLinksReentry)
    assert rig.get(marker, 4) == (7 if len(answers) == 2 and answers[1] else 0)
    assert rig.invocations("relationship_calls") == [
        (RELATION, (rig.players[2], rig.frame + 0xA4, 1, 255)),
        *([(RELATION, (rig.players[1], rig.frame + 0xA8, 1, 255))] if answers[0] else []),
    ]
    assert rig.get(rig.frame + 0xA4, 4) == 1
    if answers[0]:
        assert rig.get(rig.frame + 0xA8, 4) == 2


def test_marker_first_held_begin_then_fresh_begin_and_receiver_before_home() -> None:
    rig = Rig(4, outer=1)
    rig.put(rig.players[1] + 0x648, 4, 1)
    rig.put(rig.frame + 0x27C, 4, 1)
    replacement = [rig.player() for _ in range(4)]
    new_begin = rig.array(replacement, stride=16)

    def relationship(target: int, args: tuple[int, ...]) -> int:
        ordinal = len(rig.invocations("relationship_calls"))
        if ordinal == 1:
            assert args[0] == rig.players[2]
            rig.header(new_begin, 4)
        else:
            assert ordinal == 2 and args[0] == replacement[1]
        return 1

    rig.handlers["relationship_calls"] = relationship
    rig.run()
    assert rig.get(rig.frame + 0xA4, 4) == 1
    assert rig.get(rig.frame + 0xA8, 4) == 2
    assert rig.invocations("calls")[-1] == (FINAL, (replacement[1] + 0xA0,))
    first_receiver = rig.events.index(("read", rig.begin + 2 * 16, 8))
    first_home = rig.events.index(("write", rig.frame + 0xA4, 4, 1))
    second_receiver = rig.events.index(("read", new_begin + 16, 8))
    second_home = rig.events.index(("write", rig.frame + 0xA8, 4, 2))
    assert first_receiver < first_home < second_receiver < second_home


@pytest.mark.parametrize("raise_child", [False, True])
def test_last_marker_clear_holds_vptr_and_late_target_then_stores(raise_child: bool) -> None:
    rig = Rig(2, outer=1)
    player = rig.players[1]
    rig.put(player + 0x648, 4, 1)
    marker = rig.frame + 0x27C
    rig.put(marker, 4, 7)
    old_table, new_table = rig.get(player), rig.alloc(0x340)
    rig.put(new_table + 0x330, 8, 0xC330)

    def mutate(address: int, width: int, value: int) -> None:
        if address == rig.frame + 0x270:
            rig.put(player, 8, new_table)
            rig.put(old_table + 0x330, 8, 0xB330)

    rig.after_write = mutate

    def virtual(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0xB330:
            assert args == (player, rig.frame + 0x270)
            assert rig.get(marker, 4) == 7
            if raise_child:
                raise UnresolvedReplayTaskRebuild("authored reached clear refusal")
        else:
            assert target == V100
        return -1

    rig.handlers["virtual_calls"] = virtual
    if raise_child:
        with pytest.raises(UnresolvedReplayTaskRebuild):
            rig.run()
    else:
        rig.run()
    assert rig.get(marker, 4) == (7 if raise_child else 0)
    assert not rig.invocations("relationship_calls")
    assert rig.get(rig.frame + 0x270) == 0xA5A5A5A500000001


def test_last_row_compares_full_sar_count_not_low_dword() -> None:
    rig = Rig(3, outer=1)
    rig.header(rig.begin, (1 << 32) + 2)
    rig.put(rig.players[1] + 0x648, 4, 1)
    rig.put(rig.frame + 0x27C, 4, 7)
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerPass)
    assert output.raw_count == (1 << 32) + 2
    assert len(rig.invocations("relationship_calls")) == 2
    assert rig.get(rig.frame + 0x27C, 4) == 7


def test_marker_aliases_current_selected_slot_after_selected_gate() -> None:
    rig = Rig(16)
    selected = rig.players[0]
    rig.put(selected + 0x648, 4, 1)
    rig.put(rig.frame + 0x2B0, 4, 7)
    rig.put(rig.frame + 0x2B4, 4, 8)
    rig.handlers["relationship_calls"] = lambda target, args: 0
    rig.run()
    assert rig.get(rig.frame + 0x2B0) == 0
    assert [args[0] for target, args in rig.invocations("virtual_calls") if target == V330] == [
        rig.players[14],
        rig.players[15],
    ]
    gate = rig.events.index(("read", selected + 0x648, 4))
    marker = rig.events.index(("read", rig.frame + 0x2B0, 4))
    assert gate < marker
    assert ("read", rig.frame + 0x2B0, 8) not in rig.events
    # R13 is repurposed to outer at aa82; no selected-pointer register live-out is asserted.


def test_actual_relationship_caller_composes_with_explicit_parent_count_home() -> None:
    rig = Rig(4, outer=1)
    for i, player in enumerate(rig.players):
        rig.put(player + 8, 8, rig.game)
        rig.put(player + 0x648, 4, i)
        relation_bytes = rig.alloc(4, fill=4)
        rig.put(player + 0x180, 8, relation_bytes)
    rig.put(rig.frame + 0x27C, 4, 7)
    deep_calls: list[tuple[int, tuple[int, ...]]] = []

    def authored_count(target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        # A declared test capability, not an implementation claim for native141603f30.
        assert target == 0x141603F30 and args == (rig.game, rig.frame) and data is None
        deep_calls.append((target, args))
        rig.put(args[1], 4, 4)
        return args[1]

    bound = bind_replay_player_relationship_check(
        rig.context,
        ReplayTaskRebuildCalls(authored_count),
        count_home=rig.frame,
    )
    assert bound.call is not None
    rig.handlers["relationship_calls"] = lambda target, args: bound.call(target, args, None)
    rig.run()
    assert len(deep_calls) == 2 and rig.get(rig.frame, 4) == 4
    assert rig.get(rig.frame + 0x27C, 4) == 7


def test_outer_publishes_before_end_then_current_begin_sample() -> None:
    rig = Rig(2)

    def after_read(address: int, width: int) -> None:
        if address == rig.world + 0x770:
            assert rig.get(rig.frame + 0x210, 4) == 1
            rig.put(rig.world + 0x768, 8, rig.begin + 16)

    rig.after_read = after_read
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerPass) and output.raw_count == 1
    publish = rig.events.index(("write", rig.frame + 0x210, 4, 1))
    assert rig.events[publish + 1 : publish + 3] == [
        ("read", rig.world + 0x770, 8),
        ("read", rig.world + 0x768, 8),
    ]


def test_outer_dword_wrap_and_zero_low_count() -> None:
    rig = Rig()
    address = rig.begin + U32 * 16
    rig.memory.map_bytes(address, rig.players[0].to_bytes(8, "little"))
    rig.phase = replace(rig.phase, outer_index=U32)
    rig.header(rig.begin, 1 << 32)
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerPass)
    assert output.outer_index == 0 and output.raw_count == 1 << 32
    assert rig.get(rig.frame + 0x210, 4) == 0


def test_returned_c90_record_enters_existing_runner_without_xmm8_resample() -> None:
    rig = Rig(2)
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerLinksReentry)
    rig.put(rig.world + 0x7C, 4, 7)
    rig.put(rig.world + 0x190, 4, 10)
    rig.memory.map_bytes(0x14435505D, b"\x00")
    # Constant143219e04 is deliberately unbacked: c90 may not resample it.
    rig.events.clear()
    next_phase = run_replay_world_update_player_links(
        rig.context,
        rig.channels["calls"],
        output,
        logger_home_calls=ReplayTaskRebuildCalls(None),
        relationship_calls=ReplayTaskRebuildCalls(None),
        virtual_calls=ReplayTaskRebuildCalls(None),
    )
    assert next_phase.next_address == 0x141629E00
    assert next_phase.outer_index == 1 and next_phase.xmm8_word == rig.phase.xmm8_word
    assert rig.get(rig.world + 0x190, 4) == 17
    assert ("read", 0x143219E04, 4) not in rig.events


def test_equal_target_values_keep_source_chosen_dispatch_channel() -> None:
    rig = Rig()
    rig.put(rig.get(rig.players[0]) + 0x100, 8, FINAL)
    rig.run()
    assert rig.invocations("virtual_calls") == [(FINAL, (rig.players[0],))]
    assert rig.invocations("calls") == [(FINAL, (rig.players[0] + 0xA0,))]


def test_initial_unit_lookup_uses_held_begin_before_ordinary_bottom_resample() -> None:
    rig = Rig()
    unit = rig.object(kind=2)
    rig.units([unit])
    replacement = rig.player()
    new_begin = rig.array([replacement], stride=16)
    rig.header(new_begin, 1)
    rig.run()
    assert ("read", unit + 0x10, 8) in rig.events
    first_new_header = rig.events.index(("read", rig.world + 0x768, 8))
    bottom_store = rig.events.index(("write", rig.frame + 0x68, 8, 8))
    assert bottom_store < first_new_header
    assert rig.invocations("virtual_calls") == [(V100, (replacement,))]


def test_positive_loop_restores_current_outer_then_current_selected() -> None:
    rig = Rig(2)
    unit = rig.object(kind=2)
    rig.units([unit])

    def mutate(address: int, width: int, value: int) -> None:
        if address == rig.frame + 0x250:
            rig.put(rig.frame + 0x210, 4, 1)
            rig.put(rig.frame + 0x2B0, 8, rig.players[1])

    rig.after_write = mutate
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerPass) and output.outer_index == 2
    assert rig.invocations("virtual_calls") == [(V100, (rig.players[1],))]
    assert ("read", rig.players[1] + 0x648, 4) in rig.events
    first = rig.events.index(("read", rig.frame + 0x210, 4))
    assert rig.events[first + 1] == ("read", rig.frame + 0x2B0, 8)


def test_repeated_master_and_kind_decode_storage_operations_are_literal() -> None:
    rig = Rig()
    unit = rig.object(kind=2)
    rig.units([unit])
    encoded = rig.get(unit + 0x10)
    master = (encoded - MASTER1 - MASTER2) & U64
    kind = rig.get(master + 0x38)
    rig.run()
    start = rig.events.index(("read", unit + 0x10, 8))
    cell = rig.frame + 0x60
    assert rig.events[start : start + 15] == [
        ("read", unit + 0x10, 8),
        ("write", cell, 8, encoded),
        ("read", cell, 8),
        ("write", cell, 8, (encoded - MASTER1) & U64),
        ("read", cell, 8),
        ("write", cell, 8, master),
        ("read", cell, 8),
        ("read", master + 0x38, 8),
        ("write", cell, 8, kind),
        ("read", cell, 8),
        ("write", cell, 8, (kind - KIND1) & U64),
        ("read", cell, 8),
        ("write", cell, 8, 2),
        ("read", cell, 8),
        ("write", rig.frame + 0x250, 8, 2),
    ]


def test_options_holds_flag_but_resamples_strong_control_after_reads() -> None:
    rig = Rig()
    unit = rig.object()
    rig.units([unit])
    rig.grid([])
    before, after = rig.alloc(0x10), rig.alloc(0x10)
    rig.put(rig.frame + 0xB0, 8, before)

    def after_read(address: int, width: int) -> None:
        if address == rig.option + 0x69:
            rig.put(rig.frame + 0xB0, 8, after)

    rig.after_read = after_read

    def direct(target: int, args: tuple[int, ...]) -> int | None:
        if target == OPTIONS:
            return rig.option_slot
        if target == STRONG:
            assert args == (after,)
            rig.put(rig.option + 0x69, 1, 0)
            return -1
        assert target == FINAL
        return None

    rig.handlers["calls"] = direct
    rig.run()
    assert (STRONG, (after,)) in rig.invocations("calls")
    assert all(target != DESCRIPTOR for target, _ in rig.invocations("calls"))
    assert ("read", rig.world + 0x98, 8) in rig.events


def test_six_policy_queries_hold_manager_vptr_but_read_target_after_home_writes() -> None:
    rig = Rig()
    unit = rig.object()
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    managers = [rig.get(unit + 0x1F0)]
    managers.extend(rig.get(rig.object() + 0x1F0) for _ in range(5))
    old_tables = [rig.get(manager) for manager in managers]
    new_tables = [rig.alloc(0x200) for _ in managers]
    for i, table in enumerate(new_tables):
        rig.put(table + 0x80, 8, 0xC080 + i)
    first_score = True

    def mutate(address: int, width: int, value: int) -> None:
        nonlocal first_score
        if address == rig.frame + 0x200 and first_score:
            # Query0 already held RCX in a142; query1 must resample later.
            rig.put(unit + 0x1F0, 8, managers[1])
            first_score = False
        if address == rig.frame + 0x20 and width == 8:
            ordinal = len(rig.invocations("policy_home_calls"))
            rig.put(managers[ordinal], 8, new_tables[ordinal])
            rig.put(old_tables[ordinal] + 0x80, 8, 0xB080 + ordinal)

    rig.after_write = mutate

    def policy(target: int, args: tuple[int, ...]) -> None:
        ordinal = len(rig.invocations("policy_home_calls")) - 1
        assert args[0] == managers[ordinal]
        assert target == 0xB080 + ordinal
        if ordinal < 5:
            rig.put(unit + 0x1F0, 8, managers[ordinal + 1])
        return None

    rig.handlers["policy_home_calls"] = policy
    rig.run()
    assert len(rig.invocations("policy_home_calls")) == 6


@pytest.mark.parametrize(("last_score", "winner"), [(3, 5), (5, 2), (U32, 5)])
def test_signed_policy_score_improvement_is_strict(last_score: int, winner: int) -> None:
    rig = Rig()
    unit = rig.object()
    candidates = [rig.object(x=0x3F800000 + i * 0x800000) for i in range(6)]
    rig.lookup(dict(enumerate(candidates)))
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    scores, previous = [10, 10, 5, 5, 6, last_score], [99, 10, 10, 5, 5, 5]

    def policy(target: int, args: tuple[int, ...]) -> int:
        i = len(rig.invocations("policy_home_calls")) - 1
        assert rig.get(rig.frame + 0x208, 4) == previous[i]
        rig.put(rig.frame + 0x200, 4, scores[i])
        return i

    rig.handlers["policy_home_calls"] = policy
    rig.run()
    assert rig.invocations("position_home_calls")[0][1][1] == candidates[winner]


@pytest.mark.parametrize("identity", [0, -2])
def test_policy_null_lookup_slot_skips_position(identity: int) -> None:
    rig = Rig()
    unit = rig.object(kind=0x15)
    rig.lookup({identity: 0})
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    rig.handlers["policy_home_calls"] = lambda target, args: identity & U32
    rig.run()
    assert not rig.invocations("position_home_calls")


@pytest.mark.parametrize("change_master", [False, True])
def test_grid_kind15_id_uses_second_current_master_decode(change_master: bool) -> None:
    rig = Rig()
    unit = rig.object(kind=0x15)
    candidate = rig.object(kind=0x10031, identity=0xC6)
    other = rig.object(kind=2, identity=0x100C7)
    old_master = (rig.get(candidate + 0x10) - MASTER1 - MASTER2) & U64
    rig.units([unit])
    rig.grid([candidate])

    def mutate(address: int, width: int) -> None:
        if change_master and address == old_master + 0x38:
            rig.put(candidate + 0x10, 8, rig.get(other + 0x10))

    rig.after_read = mutate
    rig.run()
    positions = rig.invocations("position_home_calls")
    assert bool(positions) == change_master
    if positions:
        assert positions[0][1][1] == candidate


def test_grid_member_array_and_byte_bound_are_current_each_iteration() -> None:
    rig = Rig()
    unit, candidate = rig.object(), rig.object(kind=0x31)
    rig.units([unit])
    _, tile = rig.grid([0])
    replacement = rig.array([0, candidate])
    fired = False

    def mutate(address: int, width: int) -> None:
        nonlocal fired
        if address == tile + 0x28 and not fired:
            fired = True
            rig.put(tile + 0x28, 8, replacement)
            rig.put(tile + 0x1B, 1, 2)

    rig.after_read = mutate
    rig.run()
    assert rig.invocations("position_home_calls")[0][1][1] == candidate
    assert sum(e == ("read", tile + 0x28, 8) for e in rig.events) == 2


def test_grid_fractional_coordinates_truncate_instead_of_rounding() -> None:
    rig = Rig()
    unit = rig.object(x=0x3FC00000, y=0x3FC00000)
    rig.units([unit])
    grid, _ = rig.grid([], width=2, height=2)
    base, tile = 0x70000000, 0x700000C0  # (1*2+1)*40h, not rounded (2,2).
    rig.put(grid + 8, 8, base)
    rig.memory.map_bytes(tile, b"\xa5" * 0x40)
    rig.put(tile + 0x1B, 1, 0)
    rig.run()
    assert ("read", tile + 0x1B, 1) in rig.events
    assert ("read", 0x1B, 1) not in rig.events


def test_grid_pointer_is_held_and_imul32_is_sign_extended_before_shift() -> None:
    rig = Rig()
    unit = rig.object(y=0x40000000)  # ECX=2, EAX=0.
    rig.units([unit])
    grid, _ = rig.grid([], width=0x40000001, height=3)
    # IMUL32=80000002, MOVSXD=ffffffff80000002, then <<6 and add base.
    base, tile = 0x7000000000, 0x5000000080
    rig.put(grid + 8, 8, base)
    rig.memory.map_bytes(tile, b"\xa5" * 0x40)
    rig.put(tile + 0x1B, 1, 0)

    def mutate(address: int, width: int) -> None:
        if address == unit + 0x178:
            rig.put(rig.world + 0x98, 8, 0xBAD)

    rig.after_read = mutate
    rig.run()
    assert ("read", grid + 0x30, 4) in rig.events
    assert ("read", tile + 0x1B, 1) in rig.events
    assert rig.get(rig.world + 0x98) == 0xBAD


def test_nearest_dynamic_descriptor_base_bound_and_ineligible_skip() -> None:
    rig = Rig()
    unit, first, second = rig.object(), rig.object(), rig.object(x=0x3F800000)
    rig.put(first + 0x18C, 4, 1)
    rig.lookup({0: first, 2: second})
    rig.descriptors([0])
    replacement = rig.alloc(8)
    rig.put(replacement, 4, 0)
    rig.put(replacement + 4, 4, 2)
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1

    def mutate(address: int, width: int) -> None:
        if address == first + 0x18C:
            rig.put(rig.descriptor, 8, replacement)
            rig.put(rig.descriptor + 0x10, 8, 2)

    rig.after_read = mutate
    rig.run()
    assert ("read", first + 0x170, 8) not in rig.events
    assert rig.invocations("position_home_calls")[0][1][1] == second


@pytest.mark.parametrize("positive", [False, True])
def test_nearest_saved_cells_restore_only_after_positive_descriptor(positive: bool) -> None:
    rig = Rig(2)
    unit, candidate = rig.object(), rig.object()
    rig.put(candidate + 0x18C, 4, 1)
    rig.lookup({0: candidate})
    rig.descriptors([0] if positive else [])
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1

    def mutate(address: int, width: int) -> None:
        if address == rig.descriptor + 0x10:
            rig.put(rig.frame + 0x250, 8, 0x15)
            rig.put(rig.frame + 0x78, 8, 16)
            rig.put(rig.frame + 0x208, 4, U32)

    rig.after_read = mutate
    rig.run()
    assert len(rig.invocations("policy_home_calls")) == (1 if positive else 6)
    assert rig.get(rig.frame + 0x208, 4) == (0 if positive else 1)
    if positive:
        assert ("read", rig.players[1] + 0x30, 8) in rig.events


@pytest.mark.parametrize("restored", [0x7FFFFFFF, U32])
def test_unit_counter_wrap_uses_signed_current_count_comparison(restored: int) -> None:
    rig = Rig()
    unit, candidate = rig.object(), rig.object()
    rig.put(candidate + 0x18C, 4, 1)
    rig.lookup({0: candidate})
    rig.descriptors([0])
    rig.units([unit])
    row = rig.get(rig.players[0] + 0x30)
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1

    def mutate(address: int, width: int) -> None:
        if address == rig.descriptor + 0x10:
            rig.put(rig.frame + 0x208, 4, restored)
            rig.put(row + 0x10, 4, 0)

    rig.after_read = mutate
    if restored == 0x7FFFFFFF:
        # The signed continuation reaches the unbacked second pointer slot.
        with pytest.raises(ReplayMemoryError):
            rig.run()
    else:
        rig.run()
    assert rig.get(rig.frame + 0x208, 4) == ((restored + 1) & U32)
    assert rig.get(rig.frame + 0x68) == 8


def test_nominal_boundary_and_unavailable_gated_channels() -> None:
    rig = Rig()
    with pytest.raises(ValueError):
        rig.run(object())
    assert rig.events == []
    output = rig.run(
        **{
            key: ReplayTaskRebuildCalls(None)
            for key in (
                "virtual_2e8_calls",
                "policy_home_calls",
                "position_home_calls",
                "relationship_calls",
            )
        }
    )
    assert isinstance(output, ReplayWorldUpdatePlayerPass)


@pytest.mark.parametrize("zero", ["world", "logical_frame"])
def test_zero_logical_addresses_and_distinct_context_subject_are_admitted(zero: str) -> None:
    rig = Rig()
    rig.context = ReplayTaskRebuildStorage(0xAABB, rig.read, rig.write)
    if zero == "world":
        rig.memory.map_bytes(0, b"\xa5" * 0xA00)
        rig.put(0x50, 8, rig.sentinel)
        rig.put(0x768, 8, rig.begin)
        rig.put(0x770, 8, rig.begin + 16)
    else:
        rig.memory.map_bytes(0, b"\xa5" * 0x400)
        rig.put(0x70, 1, 0)
    rig.phase = replace(rig.phase, **{zero: 0})
    output = rig.run()
    assert isinstance(output, ReplayWorldUpdatePlayerPass)
    assert getattr(output, zero) == 0


@pytest.mark.parametrize("missing", [OPTIONS, STRONG, DESCRIPTOR, NODE, OWNER, FINAL])
def test_each_direct_service_remains_mandatory_at_reached_site(missing: int) -> None:
    rig = Rig()
    if missing in (OPTIONS, STRONG, DESCRIPTOR):
        unit = rig.object(kind=4 if missing == DESCRIPTOR else 0x15)
        rig.units([unit])
        rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
        if missing == STRONG:
            rig.put(rig.frame + 0xB0, 8, rig.alloc(0x10))
    elif missing == NODE:
        delayed_node(rig)
    elif missing == OWNER:
        unit = rig.object(kind=2)
        rig.put(unit + 0xF, 1, 0x50)
        rig.units([unit])

    def direct(target: int, args: tuple[int, ...]) -> int | None:
        if target == missing:
            raise UnresolvedReplayTaskRebuild("authored missing service")
        return {OPTIONS: rig.option_slot, DESCRIPTOR: rig.descriptor, NODE: 0, OWNER: 0}.get(target)

    rig.handlers["calls"] = direct
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.run()
    assert rig.invocations("calls")[-1][0] == missing


@pytest.mark.parametrize("invalid", ["null_base", "x_equal", "y_equal", "negative_height"])
def test_grid_admission_failures_still_read_literal_null_tile(invalid: str) -> None:
    rig = Rig()
    unit = rig.object(
        x=0x3F800000 if invalid == "x_equal" else 0, y=0x3F800000 if invalid == "y_equal" else 0
    )
    rig.units([unit])
    grid, _ = rig.grid([])
    if invalid == "null_base":
        rig.put(grid + 8, 8, 0)
    if invalid == "negative_height":
        rig.put(grid + 0x34, 4, U32)
    with pytest.raises(ReplayMemoryError):
        rig.run()
    assert rig.events[-1] == ("read", 0x1B, 1)


@pytest.mark.parametrize("first_x", [0x40400000, 0x7FC01234])
def test_nearest_smaller_second_candidate_and_unordered_first_are_handled(first_x: int) -> None:
    rig = Rig()
    unit = rig.object()
    first = rig.object(x=first_x, y=0x40800000)
    second = rig.object(y=0x40000000)
    rig.lookup({0: first, 1: second})
    rig.descriptors([0, 1])
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    rig.run()
    assert rig.invocations("position_home_calls")[0][1] == (
        unit,
        second,
        0,
        0x40000000,
        rig.frame + 0x20,
    )


def test_current_manager_null_on_next_query_is_not_silently_skipped() -> None:
    rig = Rig()
    unit = rig.object()
    rig.units([unit])
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1

    def policy(target: int, args: tuple[int, ...]) -> None:
        rig.put(unit + 0x1F0, 8, 0)
        return None

    rig.handlers["policy_home_calls"] = policy
    with pytest.raises(ReplayMemoryError):
        rig.run()
    assert len(rig.invocations("policy_home_calls")) == 1
    assert rig.events[-1] == ("read", 0, 8)


def test_positive_policy_count_with_null_table_skips_position() -> None:
    rig = Rig()
    unit = rig.object(kind=0x15)
    rig.units([unit])
    rig.put(rig.world + 0x174, 4, 1)
    rig.handlers["virtual_2e8_calls"] = lambda target, args: 1
    rig.handlers["policy_home_calls"] = lambda target, args: 0
    rig.run()
    assert not rig.invocations("position_home_calls")


def test_unit_loop_uses_fresh_array_for_later_unit() -> None:
    rig = Rig()
    first, obsolete, current = rig.object(kind=2), rig.object(kind=2), rig.object(kind=2)
    rig.units([first, obsolete])
    row = rig.get(rig.players[0] + 0x30)
    replacement = rig.array([first, current])

    def mutate(address: int, width: int, value: int) -> None:
        if address == rig.frame + 0x68 and value == 8:
            rig.put(row + 8, 8, replacement)

    rig.after_write = mutate
    rig.run()
    assert ("read", obsolete + 0x10, 8) not in rig.events
    assert ("read", current + 0x10, 8) in rig.events
    assert rig.get(rig.frame + 0x208, 4) == 2
    assert rig.get(rig.frame + 0x68) == 16


def test_player100_effect_precedes_selected_gate_and_fresh_marker_target() -> None:
    rig = Rig(2)
    rig.put(rig.frame + 0x27C, 4, 7)
    replacement = [rig.player(), rig.player()]
    new_begin = rig.array(replacement, stride=16)

    def virtual(target: int, args: tuple[int, ...]) -> None:
        if target == V100:
            assert args == (rig.players[0],)
            rig.put(rig.players[0] + 0x648, 4, 1)
            rig.header(new_begin, 2)
        else:
            assert target == V330 and args[0] == replacement[1]
        return None

    rig.handlers["virtual_calls"] = virtual
    rig.handlers["relationship_calls"] = lambda target, args: 0
    rig.run()
    assert rig.get(rig.frame + 0x27C, 4) == 0
    assert ("read", replacement[0] + 0x648, 4) not in rig.events
    assert rig.invocations("calls")[-1] == (FINAL, (replacement[0] + 0xA0,))
