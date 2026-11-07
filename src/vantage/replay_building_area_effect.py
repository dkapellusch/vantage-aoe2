"""Whole build54800 cell effect and three complete effect/relationship leaves.

Source: building-area-cell-source-v1 and building-area-cell-leaves-source-v1.
The new bodies cover2146B/507 assembly rows. Selectors, Game World and nested
relationship checks stay with existing owners; all reached effects are required.
No restored recording World, physical native stack or complete tick is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    divide_binary32,
    multiply_binary32,
    signed16_binary32,
)
from .replay_manager_queues import _Frame
from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate

_CELL, _RELATION, _RELATION_INNER = 0x14127DC70, 0x141734D40, 0x141734D70
_EFFECT13, _EFFECT5 = 0x141138F30, 0x14120D2D0
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MA, _MB = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_KX, _KS = 0x349E37847AD69F19, 0x47E37DFF0616CE4F
_CA, _CB = 0x50A06BCECEBEF905, 0x5B32AA7995D95916
_HX, _HA = 0x0F2A55F7A61DD00E, 0x147B5E081EC087D9
_MAX_A, _MAX_B = 0xD978539418047C54, 0xABAA7F7397F61E6C


@dataclass(frozen=True, slots=True)
class ReplayBuildingAreaCellProfile:
    """Explicit50h prefix;20/28/2c/30/38/40/48 remain current and aliased."""

    cell: bytes

    def __post_init__(self) -> None:
        if type(self.cell) is not bytes or len(self.cell) != 0x50:
            raise ValueError("explicit50h-byte area cell seed required")


@dataclass(frozen=True, slots=True)
class ReplayBuildingAreaLeavesProfile:
    """Eight explicit bytes: relation sourceH38 maps to logical0."""

    relation: bytes

    def __post_init__(self) -> None:
        if type(self.relation) is not bytes or len(self.relation) != 8:
            raise ValueError("explicit8-byte relationship caller seed required")


def _raw(value: int | None, label: str, width: int = 8) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual raw annotation")
    _unsigned(value, width, label)
    return value


def _invoke(calls: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


class _Cell:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        channels: tuple[ReplayTaskRebuildCalls, ...],
        bind_local: LocalBinding,
        profile: ReplayBuildingAreaCellProfile,
    ) -> None:
        self.context, self.calls = context, calls
        self.relationships, self.getters, self.apply, self.members = channels
        self.bind_local, self.profile = bind_local, profile

    def r(self, at: int, width: int = 8) -> int:
        return _read(self.context, at, width)

    def w(self, at: int, width: int, value: int) -> None:
        _write(self.context, at, width, value)

    def call(self, target: int, *args: int) -> int | None:
        return _invoke(self.calls, target, *args)

    def master(self, f: _Frame, member: int) -> int:
        f.w(0x20, 8, self.r(member + 0x10))
        f.w(0x20, 8, f.r(0x20, 8) - _MA)
        f.w(0x20, 8, f.r(0x20, 8) - _MB)
        return f.r(0x20, 8)

    def kind(self, f: _Frame, master: int) -> int:
        f.w(0x20, 8, self.r(master + 0x18))
        f.w(0x20, 8, f.r(0x20, 8) ^ _KX)
        f.w(0x20, 8, f.r(0x20, 8) - _KS)
        return f.r(0x20, 8)

    def kind_matches(self, f: _Frame, master: int) -> bool:
        kind = _signed(self.kind(f, master) & 0xFFFF, 2) & _U32
        return kind == f.r(0x2C, 4)

    def class_matches(self, f: _Frame, master: int) -> bool:
        f.w(0x20, 8, self.r(master + 0x38))
        f.w(0x20, 8, f.r(0x20, 8) - _CA)
        held = f.r(0x20, 8) + _CB
        selector = f.r(0x2C, 4)
        f.w(0x20, 8, held)
        object_class = _signed(f.r(0x20, 8) & 0xFFFF, 2) & _U32
        result = self.call(0x1410BD060, selector)
        return object_class == _raw(result, "area class EAX") & _U32

    def maximum(self, f: _Frame, master: int) -> int:
        f.w(0x20, 8, self.r(master + 0x68))
        f.w(0x20, 8, f.r(0x20, 8) ^ _MAX_A)
        f.w(0x20, 8, f.r(0x20, 8) ^ _MAX_B)
        return _signed(f.r(0x20, 8) & 0xFFFF, 2)

    def hp_comparison(self, f: _Frame, member: int) -> int | None:
        f.w(0x20, 8, self.r(member + 0x130))
        f.w(0x20, 8, f.r(0x20, 8) ^ _HX)
        f.w(0x20, 8, f.r(0x20, 8) - _HA)
        f.w(0x38, 8, f.r(0x20, 8))
        encoded = self.r(member + 0x10)
        hp = f.r(0x38, 4)
        f.w(0x20, 8, encoded)
        f.w(0x20, 8, f.r(0x20, 8) - _MA)
        f.w(0x20, 8, f.r(0x20, 8) - _MB)
        maximum = self.maximum(f, f.r(0x20, 8))
        return compare_binary32(hp, signed16_binary32(maximum))

    def clamp(self, f: _Frame, member: int) -> None:
        maximum = self.maximum(f, self.master(f, member))
        f.w(0x48, 4, signed16_binary32(maximum))
        f.w(0x20, 8, f.r(0x48, 8))
        f.w(0x20, 8, f.r(0x20, 8) + _HA)
        f.w(0x20, 8, f.r(0x20, 8) ^ _HX)
        f.w(0x38, 8, f.r(0x20, 8))
        self.w(member + 0x130, 8, f.r(0x38, 8))

    def effect_member(self, f: _Frame, target: int, member: int, amount: int) -> None:
        caster = f.r(0x30, 8)
        identifier = self.r(caster + 8, 4)
        _invoke(self.members, target, member, amount, identifier)

    def heal(self, f: _Frame, obj: int, tile: int, amount: int) -> None:
        if not self.r(tile + 0x1B, 1):
            return
        sixty = self.r(0x1436A02E0, 4)
        f.w(0x40, 8, 0)
        index, offset, caster = 0, 0, obj
        while True:
            member = self.r(self.r(tile + 0x28) + offset)
            owner, other = self.r(caster + 0x18), self.r(member + 0x18)
            related = _invoke(self.relationships, _RELATION, owner, other, 1, 255)
            if _raw(related, "area healing relationship AL") & 255:
                f.w(0x20, 8, self.r(member + 0x10))
                f.w(0x20, 8, f.r(0x20, 8) - _MA)
                held = f.r(0x20, 8) - _MB
                mode = f.r(0x28, 1)
                f.w(0x20, 8, held)
                master = f.r(0x20, 8)
                matched = self.class_matches(f, master) if mode else self.kind_matches(f, master)
                if matched:
                    member_table = self.r(member)
                    current = f.r(0x30, 8)
                    target = self.r(member_table + 0xC0)
                    world = self.r(self.r(current + 0x18) + 8)
                    first_raw = _invoke(self.getters, self.r(self.r(current) + 0x750), current)
                    current = f.r(0x30, 8)
                    first = add_binary32(_raw(first_raw, "area first getter XMM0", 4), amount)
                    second_raw = _invoke(self.getters, self.r(self.r(current) + 0x7B0), current)
                    total = add_binary32(_raw(second_raw, "area second getter XMM0", 4), first)
                    delta = divide_binary32(sixty, total)
                    delta = multiply_binary32(delta, self.r(world + 0x164, 4))
                    _invoke(self.apply, target, member, delta)
                    if self.r(member + 0xF, 1) >= 0x46:
                        comparison = self.hp_comparison(f, member)
                        if comparison is not None and comparison >= 0:
                            self.call(0x1412BAED0, member)
                    if self.hp_comparison(f, member) == 1:
                        self.clamp(f, member)
                    caster = f.r(0x30, 8)
            offset = f.r(0x40, 8)
            index = (index + 1) & _U32
            count = self.r(tile + 0x1B, 1)
            offset = (offset + 8) & _U64
            f.w(0x40, 8, offset)
            if _signed(index, 4) >= count:
                break

    def effect13(self, f: _Frame, tile: int, amount: int, mode: int) -> None:
        if not self.r(tile + 0x1B, 1):
            return
        index, offset, carried = 0, 0, mode
        while True:
            member = self.r(self.r(tile + 0x28) + offset)
            excluded = False
            if carried:
                if self.kind(f, self.master(f, member)) & 0xFFFF == 0x6D:
                    carried = f.r(0x28, 1)
                    excluded = True
                else:
                    master = self.master(f, member)
                    f.w(0x20, 8, self.r(master + 0x18))
                    held = f.r(0x20, 8)
                    carried = f.r(0x28, 1)
                    f.w(0x20, 8, held ^ _KX)
                    f.w(0x20, 8, f.r(0x20, 8) - _KS)
                    excluded = f.r(0x20, 8) & 0xFFFF == 0x52
            if not excluded and self.r(member + 0xF, 1) >= 0x28:
                caster = f.r(0x30, 8)
                other = self.r(member + 0x18)
                owner = self.r(caster + 0x18)
                related = _invoke(self.relationships, _RELATION, owner, other, 1, 255)
                carried = f.r(0x28, 1)
                if _raw(related, "area effect13 relationship AL") & 255:
                    if carried:
                        if self.class_matches(f, self.master(f, member)):
                            self.effect_member(f, _EFFECT13, member, amount)
                        carried = f.r(0x28, 1)
                    elif self.r(member + 0xF, 1) >= 0x1E:
                        if self.kind_matches(f, self.master(f, member)):
                            self.effect_member(f, _EFFECT13, member, amount)
                        carried = f.r(0x28, 1)
            count = self.r(tile + 0x1B, 1)
            index, offset = (index + 1) & _U32, (offset + 8) & _U64
            if _signed(index, 4) >= count:
                break

    def effect5(self, f: _Frame, tile: int, amount: int, x: int, y: int) -> None:
        header = self.r(0x1443563C0)
        product = (y * self.r(header + 0xA0, 4)) & _U32
        array = self.r(header + 0x98)
        index = (product + x) & _U32
        mask = self.r(array + _signed(index, 4) * 8)
        if mask >> 23 & _U32 or not self.r(tile + 0x1B, 1):
            return
        index, offset = 0, 0
        while True:
            member = self.r(self.r(tile + 0x28) + offset)
            if self.r(member + 0xF, 1) >= 0x1E:
                caster = f.r(0x30, 8)
                other = self.r(member + 0x18)
                owner = self.r(caster + 0x18)
                related = _invoke(self.relationships, _RELATION, owner, other, 1, 255)
                if _raw(related, "area effect5 relationship AL") & 255:
                    if f.r(0x28, 1):
                        matched = self.class_matches(f, self.master(f, member))
                    else:
                        matched = self.r(member + 0xF, 1) >= 0x1E and self.kind_matches(
                            f, self.master(f, member)
                        )
                    if matched:
                        self.effect_member(f, _EFFECT5, member, amount)
            count = self.r(tile + 0x1B, 1)
            index, offset = (index + 1) & _U32, (offset + 8) & _U64
            if _signed(index, 4) >= count:
                break

    def run(
        self, obj: int, effect: int, selector: int, amount: int, x_home: int, y_home: int
    ) -> None:
        x, y = _signed(self.r(x_home, 4), 4), self.r(y_home, 4)
        effect, selector = effect & _U32, selector & _U32
        with _Frame(self.context, self.bind_local, self.profile.cell) as f:
            f.w(0x30, 8, obj)
            game = self.r(0x144353698)
            f.w(0x2C, 4, selector)
            returned = self.call(0x140D6ACC0, game)
            terrain = self.r(_raw(returned, "area Game World RAX") + 0x98)
            data = self.r(terrain + 8)
            tile = 0
            if (
                data
                and _signed(y, 4) >= 0
                and _signed(y, 4) < _signed(self.r(terrain + 0x34, 4), 4)
                and x >= 0
            ):
                width = self.r(terrain + 0x30, 4)
                if x < _signed(width, 4):
                    index = _signed(width * y & _U32, 4) + x
                    tile = (data + (index << 6)) & _U64
            mode = _raw(self.call(0x1410BA3D0, selector), "area selector AL") & 255
            f.w(0x28, 1, mode)
            if effect == 0x6D:
                self.heal(f, obj, tile, amount)
            elif effect == 13:
                self.effect13(f, tile, amount, mode)
            elif effect == 5:
                self.effect5(f, tile, amount, x & _U32, y)


def bind_replay_building_area_cell(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    relationship_calls: ReplayTaskRebuildCalls,
    scalar_fp_calls: ReplayTaskRebuildCalls,
    virtual_fp_apply_calls: ReplayTaskRebuildCalls,
    member_fp_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayBuildingAreaCellProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind the full mixed-FP/home cell API; every reached effect is required."""
    channels = (relationship_calls, scalar_fp_calls, virtual_fp_apply_calls, member_fp_calls)
    for channel in (calls, *channels):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayBuildingAreaCellProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual locals/profile and exact MXCSR1f80 area effect required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _CELL:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 6 or data is not None:
            raise ValueError("malformed addressed area effect FP/home call")
        _validate(context, calls, *args)
        _unsigned(args[3], 4, "raw area XMM3")
        _Cell(context, calls, channels, bind_local, profile).run(*args)
        return None

    return ReplayTaskRebuildCalls(dispatch)


def bind_replay_building_area_leaves(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    relationship_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayBuildingAreaLeavesProfile,
) -> ReplayTaskRebuildCalls:
    """Bind two ordered FP stores and the complete relationship caller.

    Relation input/output annotations preserve the known R8 mask and child
    return identity. The deeper relationship body owns its separate count home.
    The two FP bodies copy raw DWORDs and require no numerical MXCSR profile.
    """
    for channel in (calls, relationship_home_calls):
        _validate(context, channel)
    if not callable(bind_local) or not isinstance(profile, ReplayBuildingAreaLeavesProfile):
        raise ValueError("actual locals/profile required for area effect leaves")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (_EFFECT13, _EFFECT5, _RELATION):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (4 if target == _RELATION else 3) or data is not None:
            raise ValueError("malformed addressed area effect leaf call")
        _validate(context, calls, *args)
        if target != _RELATION:
            _unsigned(args[1], 4, "raw area leaf XMM1")
            offset = 0x434 if target == _EFFECT13 else 0x3A4
            _write(context, args[0] + offset, 4, args[1])
            _write(context, args[0] + offset - 4, 4, args[2])
            return None
        if args[3] & 255 != 255:
            raise ValueError("complete known R8B annotation required")
        if not args[1]:
            return 0
        identifier = _read(context, args[1] + 0x648, 4)
        with _Frame(context, bind_local, profile.relation) as f:
            f.w(0, 4, identifier)
            return _invoke(
                relationship_home_calls, _RELATION_INNER, args[0], f.h(0), args[2], args[3]
            )

    return ReplayTaskRebuildCalls(dispatch)
