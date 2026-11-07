"""Area caller/cell/leaf composition over owned units and terrain.

Game/World lookup, selectors, relationship decisions and effect stores use
existing source ports. Count/predicate inputs, scalar getters and HP addition
are explicit authored providers, not observed native execution or a full World.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest
from test_replay_action_object_update import MA, MB, U32, U64, encoded
from test_replay_building_object_update import MAX_A, MAX_B
from test_replay_building_production import AREA, DATA
from test_replay_building_production import Rig as ProductionRig
from test_replay_unit_object_update import HEAL, bits, health_decoded, health_encoded

from vantage.replay_building_area_effect import (
    ReplayBuildingAreaCellProfile,
    ReplayBuildingAreaLeavesProfile,
    bind_replay_building_area_cell,
    bind_replay_building_area_leaves,
)
from vantage.replay_memory import ReplayMemoryError
from vantage.replay_player_relationship_check import bind_replay_player_relationship_check
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_task_rows import bind_replay_task_rows

CELL, RELATION, INNER, EFFECT13, EFFECT5 = (
    0x14127DC70,
    0x141734D40,
    0x141734D70,
    0x141138F30,
    0x14120D2D0,
)
GET_WORLD, MODE, CLASS, RESET = 0x140D6ACC0, 0x1410BA3D0, 0x1410BD060, 0x1412BAED0
FIRST, SECOND, COUNT, PREDICATE = 0xF70750, 0xF707B0, 0x141603F30, 0x1416B69F0
CHANNELS = ("relationship_calls", "scalar_fp_calls", "virtual_fp_apply_calls", "member_fp_calls")


class Rig(ProductionRig):
    def __init__(self) -> None:
        super().__init__()
        self.tiles = self.alloc(25 * 64)
        self.homes = self.alloc(16)
        self.mask_header, self.masks = self.alloc(0xA8), self.alloc(25 * 8)
        self.mem.write(self.terrain + 8, 8, self.tiles)
        self.mem.write(0x1443563C0, 8, self.mask_header)
        self.mem.write(self.mask_header + 0x98, 8, self.masks)
        self.mem.write(self.mask_header + 0xA0, 4, 5)
        self.mem.write(self.owner + 0x648, 4, 3)
        self.mem.write(self.table + 0x750, 8, FIRST)
        self.mem.write(self.table + 0x7B0, 8, SECOND)
        sixty = (DATA / "building-area-cell-source-v1/constant-1436a02e0.bin").read_bytes()
        assert self.mem.read_bytes(0x1436A02E0, 4) == sixty
        self.cell_profile = ReplayBuildingAreaCellProfile(bytes([0xE1]) * 0x50)
        self.leaf_profile = ReplayBuildingAreaLeavesProfile(bytes([0xE2]) * 8)
        self.getters = {FIRST: bits(1.0), SECOND: bits(1.0)}
        self.relationship_count, self.relationship_predicate = 4, 0
        self.base_cell_calls = bind_replay_task_rows(
            self.context, self.services, bind_local=self.local
        )
        self.cell_calls = ReplayTaskRebuildCalls(self.cell_ordinary)
        self.leaves = self.bind_leaves()
        self.cell = self.bind_cell()

    def bind_leaves(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {
            "calls": self.cell_calls,
            "relationship_home_calls": ReplayTaskRebuildCalls(self.relationship_home),
        }
        channels.update(overrides)
        calls = channels.pop("calls")
        return bind_replay_building_area_leaves(
            self.context, calls, **channels, bind_local=self.local, profile=self.leaf_profile
        )

    def bind_cell(self, **overrides: ReplayTaskRebuildCalls) -> ReplayTaskRebuildCalls:
        channels = {name: ReplayTaskRebuildCalls(self.cell_channel(name)) for name in CHANNELS}
        channels["calls"] = self.cell_calls
        channels.update(overrides)
        calls = channels.pop("calls")
        return bind_replay_building_area_cell(
            self.context,
            calls,
            **channels,
            bind_local=self.local,
            profile=self.cell_profile,
            mxcsr=0x1F80,
        )

    def cell_ordinary(
        self,
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
    ) -> int | None:
        assert data is None
        if handler := self.record("area_calls", target, args):
            return handler(args)
        assert self.base_cell_calls.call is not None
        return self.base_cell_calls.call(target, args, data)

    def relationship_home(
        self,
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
    ) -> int | None:
        assert target == INNER and data is None
        if handler := self.record("relationship_home_calls", target, args):
            return handler(args)
        with self.local(memoryview(bytearray(4))) as home:
            bound = bind_replay_player_relationship_check(
                self.context, ReplayTaskRebuildCalls(self.relationship_child), count_home=home
            )
            assert bound.call is not None
            return bound.call(target, args, None)

    def relationship_child(
        self,
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
    ) -> int:
        assert data is None
        if handler := self.record("relationship_children", target, args):
            return cast(int, handler(args))
        if target == COUNT:
            self.mem.write(args[1], 4, self.relationship_count)
            return args[1]
        if target == PREDICATE:
            return self.relationship_predicate
        raise UnresolvedReplayTaskRebuild(f"authored relationship child missing{target:x}")

    def cell_channel(
        self, name: str
    ) -> Callable[
        [int, tuple[int, ...], memoryview | None],
        int | None,
    ]:
        def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            if handler := self.record(name, target, args):
                return handler(args)
            if name in ("relationship_calls", "member_fp_calls"):
                assert self.leaves.call is not None
                return self.leaves.call(target, args, None)
            if name == "scalar_fp_calls" and target in self.getters:
                return self.getters[target]
            if name == "virtual_fp_apply_calls" and target == HEAL:
                self.apply_health(args)
                return None
            raise UnresolvedReplayTaskRebuild(f"authored {name} missing{target:x}")

        return dispatch

    def member(
        self,
        *,
        kind: int = 7,
        object_class: int = 7,
        hp: float = 5.0,
        family: int = 0x50,
        owner: int | None = None,
    ) -> tuple[int, int]:
        member, master = self.alloc(0xA00), self.alloc(0x600)
        self.mem.write(member, 8, self.table)
        self.mem.write(member + 0x10, 8, (master + MA + MB) & U64)
        self.mem.write(member + 0x18, 8, self.owner if owner is None else owner)
        self.mem.write(member + 0xF, 1, family)
        self.mem.write(member + 0x130, 8, health_encoded(0x1122334400000000 | bits(hp)))
        self.mem.write(member + 0x66C, 4, 99)
        self.mem.write(
            master + 0x18, 8, (((kind & 0xFFFF) + 0x47E37DFF0616CE4F) & U64) ^ 0x349E37847AD69F19
        )
        self.mem.write(
            master + 0x38,
            8,
            ((object_class & 0xFFFF) - 0x5B32AA7995D95916 + 0x50A06BCECEBEF905) & U64,
        )
        self.mem.write(master + 0x68, 8, 100 ^ MAX_A ^ MAX_B)
        return member, master

    def populate(self, members: list[int], x: int = 0, y: int = 0) -> int:
        tile = self.tiles + (y * 5 + x) * 64
        array = self.alloc(max(8, 8 * len(members)))
        for index, member in enumerate(members):
            self.mem.write(array + 8 * index, 8, member)
        self.mem.write(tile + 0x28, 8, array)
        self.mem.write(tile + 0x1B, 1, len(members))
        return tile

    def run_cell(
        self,
        effect: int = 109,
        selector: int = 7,
        amount: int | None = None,
        x: int = 0,
        y: int = 0,
    ) -> None:
        self.mem.write(self.homes, 4, x & U32)
        self.mem.write(self.homes + 8, 4, y & U32)
        assert self.cell.call is not None
        assert (
            self.cell.call(
                CELL,
                (
                    self.obj,
                    effect,
                    selector,
                    bits(2.0) if amount is None else amount,
                    self.homes,
                    self.homes + 8,
                ),
                None,
            )
            is None
        )

    def health(self, member: int) -> int:
        return health_decoded(self.mem.read(member + 0x130, 8))


@pytest.mark.parametrize("size", [0, 0x4F, 0x51])
def test_cell_profile_requires_exact_seed(size: int) -> None:
    with pytest.raises(ValueError):
        ReplayBuildingAreaCellProfile(bytes(size))


def test_profiles_reject_mutable_seed_and_leaf_wrong_length() -> None:
    with pytest.raises(ValueError):
        ReplayBuildingAreaCellProfile(cast(bytes, bytearray(0x50)))
    with pytest.raises(ValueError):
        ReplayBuildingAreaLeavesProfile(cast(bytes, bytearray(8)))
    with pytest.raises(ValueError):
        ReplayBuildingAreaLeavesProfile(bytes(4))


@pytest.mark.parametrize("mxcsr", [0, 0x9FC0, True])
def test_cell_rejects_unsupported_fp_profile(mxcsr: int) -> None:
    r = Rig()
    channels = {name: r.cell_calls for name in CHANNELS}
    with pytest.raises(ValueError):
        bind_replay_building_area_cell(
            r.context,
            r.cell_calls,
            **channels,
            bind_local=r.local,
            profile=r.cell_profile,
            mxcsr=mxcsr,
        )
    assert not r.calls and not r.events


@pytest.mark.parametrize(
    ("target", "arity"), [(CELL, 6), (EFFECT13, 3), (EFFECT5, 3), (RELATION, 4)]
)
def test_entry_shape_refuses_before_memory_effects(target: int, arity: int) -> None:
    r = Rig()
    bound = r.cell if target == CELL else r.leaves
    assert bound.call is not None
    for args, data in (((), None), ((-1,) * arity, None), ((0,) * arity, memoryview(b"payload"))):
        with pytest.raises(ValueError):
            bound.call(target, args, data)
    assert not r.calls and not r.events


@pytest.mark.parametrize("target", [CELL, EFFECT13, EFFECT5])
def test_raw_fp_requires_dword(target: int) -> None:
    r = Rig()
    bound = r.cell if target == CELL else r.leaves
    args = (r.obj, 109, 7, 1 << 32, r.homes, r.homes + 8) if target == CELL else (r.obj, 1 << 32, 1)
    assert bound.call is not None
    with pytest.raises(ValueError):
        bound.call(target, args, None)
    assert not r.calls and not r.events


@pytest.mark.parametrize("cell", [True, False])
def test_unknown_dispatch_preserves_argument_payload_and_return_identity(cell: bool) -> None:
    r = Rig()
    args, data, result = (-1, 9), memoryview(b"unchanged"), 0x123456789ABCDEF

    def fallback(target: int, actual: tuple[int, ...], payload: memoryview | None) -> int:
        assert target == 42 and actual is args and payload is data
        return result

    bound = (r.bind_cell if cell else r.bind_leaves)(calls=ReplayTaskRebuildCalls(fallback))
    assert bound.call is not None and bound.call(42, args, data) is result


@pytest.mark.parametrize(("target", "offset"), [(EFFECT13, 0x434), (EFFECT5, 0x3A4)])
@pytest.mark.parametrize("word", [0x80000000, 0x7FC01234, 0x7F801234])
def test_effect_leaves_preserve_raw_bits_and_store_amount_before_source_id(
    target: int,
    offset: int,
    word: int,
) -> None:
    r = Rig()
    assert r.leaves.call is not None
    assert r.leaves.call(target, (r.obj, word, 0xABCDEF0012345678), None) is None
    assert r.events == [("w", r.obj + offset, 4, word), ("w", r.obj + offset - 4, 4, 0x12345678)]


def test_relationship_null_other_needs_no_receiver_backing_or_home() -> None:
    r = Rig()
    assert r.leaves.call is not None
    assert r.leaves.call(RELATION, (0, 0, 1, 255), None) == 0
    assert not r.events and not r.snapshots
    with pytest.raises(ValueError):
        r.leaves.call(RELATION, (0, 0, 1, 254), None)


@pytest.mark.parametrize("result", [None, 0x1234567800, 0x1234567801])
def test_relationship_preserves_child_identity_and_partial_home(result: int | None) -> None:
    r = Rig()

    def inner(args: tuple[int, ...]) -> int | None:
        assert args[0] == r.owner and args[2:] == (0x123400000001, 0xFF)
        assert r.mem.read_bytes(args[1], 8) == b"\x03\0\0\0" + bytes([0xE2]) * 4
        return result

    r.handlers["relationship_home_calls", INNER] = inner
    assert r.leaves.call is not None
    assert r.leaves.call(RELATION, (r.owner, r.owner, 0x123400000001, 255), None) is result


@pytest.mark.parametrize(("effect", "offset"), [(13, 0x434), (5, 0x3A4)])
@pytest.mark.parametrize("selector", [7, 907])
def test_area_effects_reach_actual_leaf_with_current_caster_id(
    effect: int, offset: int, selector: int
) -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member], 2, 3)
    r.run_cell(effect, selector, 0x7FC01234, 2, 3)
    assert r.mem.read(member + offset, 4) == 0x7FC01234
    assert r.mem.read(member + offset - 4, 4) == 100
    assert r.called(INNER, "relationship_home_calls")
    assert not r.called(COUNT, "relationship_children")


@pytest.mark.parametrize(
    ("selector", "kind", "expected"),
    [
        (907, 109, False),
        (907, 82, False),
        (907, 7, True),
        (109, 109, True),
        (82, 82, True),
        (7, 8, False),
    ],
)
def test_effect13_class_mode_exclusions_and_exact_kind_mode(
    selector: int, kind: int, expected: bool
) -> None:
    r = Rig()
    member, _ = r.member(kind=kind)
    r.populate([member])
    r.run_cell(13, selector)
    assert bool(r.called(EFFECT13, "member_fp_calls")) == expected


@pytest.mark.parametrize(
    ("effect", "family", "expected"),
    [(13, 39, False), (13, 40, True), (5, 29, False), (5, 30, True), (109, 0, True)],
)
def test_effect_family_thresholds(effect: int, family: int, expected: bool) -> None:
    r = Rig()
    member, _ = r.member(family=family)
    r.populate([member])
    r.run_cell(effect)
    target = HEAL if effect == 109 else EFFECT13 if effect == 13 else EFFECT5
    channel = "virtual_fp_apply_calls" if effect == 109 else "member_fp_calls"
    assert bool(r.called(target, channel)) == expected


@pytest.mark.parametrize(
    ("bit", "expected"), [(22, True), (23, False), (54, False), (55, True), (63, True)]
)
def test_effect5_checks_only_mask_bits_23_through_54(bit: int, expected: bool) -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member])
    r.mem.write(r.masks, 8, 1 << bit)
    r.run_cell(5)
    assert bool(r.called(EFFECT5, "member_fp_calls")) == expected


def test_healing_composes_getters_health_add_and_exact_binary32_delta() -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member])
    r.run_cell()
    assert r.called(HEAL, "virtual_fp_apply_calls") == [(member, bits(3.75))]
    assert r.health(member) == 0x1122334400000000 | bits(8.75)


@pytest.mark.parametrize(
    ("hp", "family", "reset", "clamp"),
    [
        (96.25, 70, True, False),
        (99.0, 70, True, True),
        (99.0, 69, False, True),
        (5.0, 70, False, False),
    ],
)
def test_healing_reset_and_clamp_use_live_health_and_partial_h48_seed(
    hp: float,
    family: int,
    reset: bool,
    clamp: bool,
) -> None:
    r = Rig()
    member, _ = r.member(hp=hp, family=family)
    r.populate([member])
    r.run_cell()
    assert r.mem.read(member + 0x66C, 4) == (0 if reset else 99)
    expected_high = 0xE1E1E1E1 if clamp else 0x11223344
    expected_hp = 100.0 if clamp else hp + 3.75
    assert r.health(member) == expected_high << 32 | bits(expected_hp)


def test_nan_health_does_not_reset_or_clamp() -> None:
    r = Rig()
    member, _ = r.member()
    r.mem.write(member + 0x130, 8, health_encoded(0x112233447FC01234))
    r.populate([member])
    r.run_cell()
    assert r.mem.read(member + 0x66C, 4) == 99
    assert r.health(member) == 0x112233447FC01234


def test_heal_captures_caster_between_member_table_and_apply_target_reads() -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member])
    other_table = r.alloc(0x900)
    r.mem.write(r.other, 8, other_table)
    r.mem.write(other_table + 0x7B0, 8, SECOND)

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.table + 0xC0:
            r.mem.write(r.frame(0x50) + 0x30, 8, r.other)

    r.after_read = mutate
    r.run_cell()
    assert r.called(FIRST, "scalar_fp_calls") == [(r.obj,)]
    assert r.called(SECOND, "scalar_fp_calls") == [(r.other,)]


def test_heal_keeps_selected_apply_target_and_world_across_getter_mutations() -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member])
    other_world = r.alloc(0x300)
    r.mem.write(other_world + 0x164, 4, bits(100.0))

    def first(args: tuple[int, ...]) -> int:
        r.mem.write(r.table + 0xC0, 8, 42)
        r.mem.write(r.owner + 8, 8, other_world)
        return bits(1.0)

    r.handlers["scalar_fp_calls", FIRST] = first
    r.run_cell()
    assert r.called(HEAL, "virtual_fp_apply_calls") == [(member, bits(3.75))]


def test_first_getter_result_is_consumed_after_current_caster_home_read() -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member])
    homes: list[int] = []

    def missing(args: tuple[int, ...]) -> None:
        homes.append(r.frame(0x50) + 0x30)
        return None

    r.handlers["scalar_fp_calls", FIRST] = missing
    with pytest.raises(ValueError, match="first getter"):
        r.run_cell()
    call_index = next(i for i, event in enumerate(r.events) if event[:2] == ("call", FIRST))
    assert r.events[call_index + 1] == ("r", homes[0], 8, r.obj)
    assert not r.called(SECOND, "scalar_fp_calls")


def test_live_cell_array_and_count_are_reloaded_between_members() -> None:
    r = Rig()
    first, _ = r.member()
    second, _ = r.member()
    third, _ = r.member()
    tile = r.populate([first, second])
    replacement = r.alloc(16)
    r.mem.write(replacement + 8, 8, third)

    def change(args: tuple[int, ...]) -> None:
        assert r.leaves.call is not None
        r.leaves.call(EFFECT13, args, None)
        r.mem.write(tile + 0x28, 8, replacement)
        return None

    r.handlers["member_fp_calls", EFFECT13] = change
    r.run_cell(13)
    assert [args[0] for args in r.called(EFFECT13, "member_fp_calls")] == [first, third]


def test_effect13_carries_mode_across_low_family_skip_instead_of_rereading_it() -> None:
    r = Rig()
    first, _ = r.member(family=10)
    second, _ = r.member(kind=109)
    r.populate([first, second])
    modified = False

    def change(at: int, width: int, value: int) -> None:
        nonlocal modified
        if at == first + 0xF and not modified:
            modified = True
            r.mem.write(r.frame(0x50) + 0x28, 1, 1)
            r.mem.write(r.frame(0x50) + 0x2C, 4, 907)

    r.after_read = change
    r.run_cell(13, 109)
    assert modified
    assert r.called(EFFECT13, "member_fp_calls") == [(second, bits(2.0), 100)]


@pytest.mark.parametrize("effect", [13, 5])
def test_effects_repeat_family_check_after_relationship_in_kind_mode(effect: int) -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member])

    def change(args: tuple[int, ...]) -> int:
        r.mem.write(member + 0xF, 1, 29)
        return 1

    r.handlers["relationship_calls", RELATION] = change
    r.run_cell(effect)
    assert not r.called(EFFECT13, "member_fp_calls")
    assert not r.called(EFFECT5, "member_fp_calls")


def test_effect13_reads_current_mode_even_when_relationship_return_is_undefined() -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member])
    homes: list[int] = []

    def missing(args: tuple[int, ...]) -> None:
        homes.append(r.frame(0x50) + 0x28)
        return None

    r.handlers["relationship_calls", RELATION] = missing
    with pytest.raises(ValueError, match="relationship AL"):
        r.run_cell(13)
    call_index = next(i for i, event in enumerate(r.events) if event[:2] == ("call", RELATION))
    assert r.events[call_index + 1] == ("r", homes[0], 1, 0)


def test_healing_mode_is_held_before_last_master_decode_store() -> None:
    r = Rig()
    member, master = r.member(kind=8)
    r.populate([member])

    def change(at: int, width: int, value: int) -> None:
        if r.live and at == r.frame(0x50) + 0x20 and value == master:
            r.mem.write(r.frame(0x50) + 0x28, 1, 0)

    r.after_write = change
    r.run_cell(109, 907)
    assert r.called(CLASS, "area_calls") == [(907,)]
    assert r.called(HEAL, "virtual_fp_apply_calls")


@pytest.mark.parametrize("effect", [13, 5, 109])
def test_kind_selection_sign_extends_word_and_consumes_low_register_dwords(effect: int) -> None:
    r = Rig()
    member, _ = r.member(kind=-2)
    r.populate([member])
    r.run_cell((0xABCD << 32) | effect, (0x1234 << 32) | (U32 - 1))
    target = HEAL if effect == 109 else EFFECT13 if effect == 13 else EFFECT5
    channel = "virtual_fp_apply_calls" if effect == 109 else "member_fp_calls"
    assert r.called(target, channel)
    assert r.called(MODE, "area_calls") == [(U32 - 1,)]


def test_tile_address_uses_wrapped_dword_row_product_before_signed_extension() -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member])
    # 0x40000000 * 4 wraps to zero; no enormous allocation is needed.
    r.mem.write(r.terrain + 0x30, 4, 0x40000000)
    r.mem.write(r.terrain + 0x34, 4, 5)
    r.run_cell(13, y=4)
    assert r.called(EFFECT13, "member_fp_calls") == [(member, bits(2.0), 100)]


def test_healing_loads_offset_before_live_count_read() -> None:
    r = Rig()
    members = [r.member()[0] for _ in range(3)]
    tile = r.populate(members)
    advanced = False

    def count(at: int, width: int, value: int) -> None:
        nonlocal advanced
        if at == tile + 0x1B and r.called(HEAL, "virtual_fp_apply_calls") and not advanced:
            advanced = True
            r.mem.write(r.frame(0x50) + 0x40, 8, 8)
            r.mem.write(tile + 0x1B, 1, 2)

    r.after_read = count
    r.run_cell()
    assert [args[0] for args in r.called(HEAL, "virtual_fp_apply_calls")] == members[:2]


@pytest.mark.parametrize(
    ("effect", "x", "y"),
    [(99, -1, 0), (99, 5, 0), (99, 0, -1), (99, 0, 5), (13, -1, 0), (109, 0, 5)],
)
def test_invalid_tile_still_selects_mode_and_recognized_effect_requires_backing(
    effect: int,
    x: int,
    y: int,
) -> None:
    r = Rig()
    if effect == 99:
        r.run_cell(effect, x=x, y=y)
    else:
        with pytest.raises(ReplayMemoryError):
            r.run_cell(effect, x=x, y=y)
    assert r.called(MODE, "area_calls") == [(7,)]


def test_caller_coordinate_homes_are_read_before_private_initialization() -> None:
    r = Rig()

    def mutate(at: int, width: int, value: int) -> None:
        if at == r.homes:
            r.mem.write(r.homes + 8, 4, 3)

    r.after_read = mutate
    member, _ = r.member()
    r.populate([member], 0, 3)
    r.run_cell(13)
    assert r.mem.read(member + 0x434, 4) == bits(2.0)
    assert r.events[:2] == [("r", r.homes, 4, 0), ("r", r.homes + 8, 4, 3)]


def test_class_selector_is_captured_before_last_crypto_store() -> None:
    r = Rig()
    member, master = r.member()
    r.populate([member])
    class_loaded = False

    def loaded(at: int, width: int, value: int) -> None:
        nonlocal class_loaded
        if at == master + 0x38:
            class_loaded = True

    def change(at: int, width: int, value: int) -> None:
        if class_loaded and at == r.frame(0x50) + 0x20 and value == 7:
            r.mem.write(r.frame(0x50) + 0x2C, 4, 908)

    r.after_read = loaded
    r.after_write = change
    r.run_cell(13, 907)
    assert r.called(CLASS, "area_calls") == [(907,)]
    assert r.called(EFFECT13, "member_fp_calls")


@pytest.mark.parametrize(
    ("effect", "channel"),
    [
        (109, "relationship_calls"),
        (109, "scalar_fp_calls"),
        (109, "virtual_fp_apply_calls"),
        (13, "member_fp_calls"),
    ],
)
def test_reached_child_capabilities_are_required(effect: int, channel: str) -> None:
    r = Rig()
    member, _ = r.member()
    r.populate([member])
    r.cell = r.bind_cell(**{channel: ReplayTaskRebuildCalls(None)})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.run_cell(effect)


def test_relationship_port_uses_explicit_count_and_relation_table() -> None:
    r = Rig()
    owner = r.alloc(0xA00)
    relations = r.alloc(4)
    r.mem.write(owner + 0x648, 4, 2)
    r.mem.write(r.owner + 0x180, 8, relations)
    r.mem.write(relations + 2, 1, 4)
    member, _ = r.member(owner=owner)
    r.populate([member])
    r.run_cell(13)
    assert r.called(COUNT, "relationship_children")
    assert r.called(EFFECT13, "member_fp_calls")
    r.mem.write(relations + 2, 1, 3)
    r.calls.clear()
    r.run_cell(13)
    assert r.called(PREDICATE, "relationship_children")
    assert not r.called(EFFECT13, "member_fp_calls")


def test_actual_production_area_caller_reaches_real_cells_and_unit_effects() -> None:
    r = Rig()
    r.area_data()
    for offset, value in ((0x810, 7.0), (0x818, 13.0), (0x820, 109.0)):
        r.mem.write(r.resource + offset, 8, encoded(bits(value)))
    members = [r.member()[0] for _ in range(4)]
    for member, (x, y) in zip(members, ((1, 2), (2, 2), (1, 3), (2, 3)), strict=True):
        r.populate([member], x, y)
    r.production = r.bind_production(area_fp_home_calls=r.cell)
    assert r.run_production(AREA) is None
    assert all(r.mem.read(member + 0x434, 4) != 0 for member in members)
    assert all(r.mem.read(member + 0x430, 4) == 100 for member in members)
    assert all(r.health(member) & U32 == bits(8.0) for member in members)
    assert not r.area_cells
