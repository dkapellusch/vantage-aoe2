"""Complete build54800 health adjustment, special repair and repair cost bodies.

Source/API: object-health-repair-source-v1,2274B/500 assembly rows. Entry tuples
annotate actual mixed-FP positions. Current storage and every reached external
effect are required. This supplies no restored World or complete recording tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    divide_binary32,
    multiply_binary32,
    signed16_binary32,
    subtract_binary32,
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
from .replay_world_postpasses import _widen

_INCREMENT, _REPAIR, _COST = 0x141252890, 0x1412C8D20, 0x1417015D0
_ARITIES = {_INCREMENT: 2, _REPAIR: 2, _COST: 4}
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MA, _MB = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_HX, _HA = 0x0F2A55F7A61DD00E, 0x147B5E081EC087D9
_MAX_A, _MAX_B = 0xD978539418047C54, 0xABAA7F7397F61E6C
_RA, _RB, _RC, _RD = (
    0x6AE24D3352F04511,
    0xC22D6B496D833977,
    0x042AC42976FCCEF5,
    0xA9834B738A7DD167,
)


@dataclass(frozen=True, slots=True)
class ReplayObjectHealthRepairProfile:
    """Explicit private views: incrementH20,repairH60,costH20..57.

    The first two source QWORDs map to logical0 in separate8-byte views.
    Cost sourceH20 maps to logical0 in38h bytes; sourceH50 DWORD writes retain
    the live upperDWORD from the explicit seed. Native stack/saves excluded.
    """

    increment: bytes
    repair: bytes
    cost: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in ((self.increment, 8), (self.repair, 8), (self.cost, 0x38))
        ):
            raise ValueError("explicit8/8/38h-byte health/repair seeds required")


def _raw(value: int | None, label: str, width: int = 8) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual raw annotation")
    _unsigned(value, width, label)
    return value


def _count12(begin: int, end: int) -> int:
    span = _signed((end - begin) & _U64, 8)
    half = ((span * 0x2AAAAAAAAAAAAAAB) >> 64) >> 1
    return (half + ((half & _U64) >> 63)) & _U64


class _Health:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        channels: tuple[ReplayTaskRebuildCalls, ...],
        bind_local: LocalBinding,
        profile: ReplayObjectHealthRepairProfile,
    ) -> None:
        self.context, self.calls = context, calls
        self.getters, self.apply, self.check, self.events = channels
        self.bind_local, self.profile = bind_local, profile

    def r(self, at: int, width: int = 8) -> int:
        return _read(self.context, at, width)

    def w(self, at: int, width: int, value: int) -> None:
        _write(self.context, at, width, value)

    def invoke(self, calls: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, tuple(value & _U64 for value in args), None)

    def master(self, f: _Frame, obj: int) -> int:
        f.w(0, 8, self.r(obj + 0x10))
        f.w(0, 8, f.r(0, 8) - _MA)
        f.w(0, 8, f.r(0, 8) - _MB)
        return f.r(0, 8)

    def object_class(self, f: _Frame, obj: int) -> int:
        master = self.master(f, obj)
        f.w(0, 8, self.r(master + 0x38))
        f.w(0, 8, f.r(0, 8) - 0x50A06BCECEBEF905)
        f.w(0, 8, f.r(0, 8) + 0x5B32AA7995D95916)
        return f.r(0, 8) & 0xFFFF

    def maximum(self, f: _Frame, master: int) -> int:
        f.w(0, 8, self.r(master + 0x68))
        f.w(0, 8, f.r(0, 8) ^ _MAX_A)
        f.w(0, 8, f.r(0, 8) ^ _MAX_B)
        return _signed(f.r(0, 8) & 0xFFFF, 2)

    def health(self, f: _Frame, obj: int, encoded: int | None = None) -> int:
        f.w(0, 8, self.r(obj + 0x130) if encoded is None else encoded)
        f.w(0, 8, f.r(0, 8) ^ _HX)
        f.w(0, 8, f.r(0, 8) - _HA)
        return f.r(0, 8)

    def store_health(self, f: _Frame, obj: int) -> None:
        f.w(0, 8, f.r(0, 8))
        f.w(0, 8, f.r(0, 8) + _HA)
        f.w(0, 8, f.r(0, 8) ^ _HX)
        f.w(0, 8, f.r(0, 8))
        self.w(obj + 0x130, 8, f.r(0, 8))

    def increment(self, obj: int, amount: int) -> int:
        with _Frame(self.context, self.bind_local, self.profile.increment) as f:
            target = self.r(self.r(obj) + 0xC0)
            self.invoke(self.apply, target, obj, amount)
            if compare_binary32(0, amount) == 1:
                encoded = self.r(obj + 0x130)
                one = self.r(0x1436A0294, 4)
                f.w(0, 8, self.health(f, obj, encoded))
                if compare_binary32(one, f.r(0, 4)) == 1:
                    f.w(0, 4, 0x3F800000)
                    self.store_health(f, obj)
            table = self.r(obj)
            hp_target = self.r(table + 0xC8)
            maximum_target = self.r(table + 0xD0)
            hp = _raw(self.invoke(self.getters, hp_target, obj), "health getter XMM0", 4)
            maximum = _raw(self.invoke(self.getters, maximum_target, obj), "maximum getter XMM0", 4)
            comparison = compare_binary32(hp, maximum)
            if comparison is None or comparison < 0:
                return 0
            maximum_word = self.maximum(f, self.master(f, obj))
            f.w(0, 4, signed16_binary32(maximum_word))
            self.store_health(f, obj)
            return 1

    def resource(self, f: _Frame, at: int, encoded: int) -> int:
        f.w(at, 8, encoded)
        f.w(at, 8, f.r(at, 8) ^ _RA)
        f.w(at, 8, f.r(at, 8) ^ _RB)
        f.w(at, 8, f.r(at, 8) - _RC)
        f.w(at, 8, f.r(at, 8) ^ _RD)
        return f.r(at, 8)

    def repair(self, obj: int, amount: int) -> int:
        next_amount = amount
        with _Frame(self.context, self.bind_local, self.profile.repair) as f:
            special = False
            for kind in (0x14, 0x15, 0x16, 2, 0x35):
                if self.object_class(f, obj) == kind:
                    special = True
                    break
            if special:
                master = self.master(f, obj)
                begin, end = self.r(master + 0x338), self.r(master + 0x340)
                threshold = self.r(begin + 2, 2) if _count12(begin, end) else 0
                maximum = self.maximum(f, self.master(f, obj))
                delta = multiply_binary32(signed16_binary32(maximum), amount)
                delta = divide_binary32(delta, signed16_binary32(_signed(threshold, 2)))
                hp_raw = self.invoke(self.getters, self.r(self.r(obj) + 0xC8), obj)
                table = self.r(obj)
                hp = _raw(hp_raw, "repair health getter XMM0", 4)
                total = add_binary32(hp, delta)
                maximum_raw = self.invoke(self.getters, self.r(table + 0xD0), obj)
                maximum_fp = _raw(maximum_raw, "repair maximum getter XMM0", 4)
                if compare_binary32(total, maximum_fp) == 1:
                    maximum = self.maximum(f, self.master(f, obj))
                    f.w(0, 8, self.health(f, obj))
                    delta = subtract_binary32(signed16_binary32(maximum), f.r(0, 4))
                owner = self.r(obj + 0x18)
                resources = self.r(owner + 0x98)
                f.w(0, 8, self.resource(f, 0, self.r(resources + 0x870)))
                table = self.r(obj)
                numerator = multiply_binary32(f.r(0, 4), delta)
                maximum_raw = self.invoke(self.getters, self.r(table + 0xD0), obj)
                master = self.master(f, obj)
                cost = divide_binary32(numerator, _raw(maximum_raw, "repair cost maximum XMM0", 4))
                f.w(0, 8, self.r(master + 0x18))
                f.w(0, 8, f.r(0, 8) ^ 0x349E37847AD69F19)
                f.w(0, 8, f.r(0, 8) - 0x47E37DFF0616CE4F)
                identifier = f.r(0, 8)
                if self.cost(owner, identifier, cost, 1) == 0:
                    return 2
                next_amount = delta
        return self.increment(obj, next_amount)

    def cost(self, owner: int, identifier: int, amount: int, flags: int) -> int:
        index = _signed(identifier & 0xFFFF, 2)
        with _Frame(self.context, self.bind_local, self.profile.cost) as f:
            f.w(0x10, 4, 0)
            f.w(8, 4, 0)
            f.w(0, 4, flags & _U32)
            permitted = self.invoke(
                self.check,
                0x1416E59E0,
                owner,
                identifier & 0xFFFF,
                0,
                amount,
                f.h(0),
                f.h(8),
                f.h(0x10),
            )
            if _raw(permitted, "repair cost check AL") & 255 == 0:
                return 0
            masters = self.r(owner + 0x28)
            row = (self.r(masters + index * 8) + 0x324) & _U64
            for _ in range(3):
                resource_id = _signed(self.r(row - 4, 2), 2)
                if resource_id >= 0 and self.r(row, 1):
                    coefficient = _signed(self.r(row - 2, 2), 2)
                    resources = self.r(owner + 0x98)
                    f.w(0x28, 8, self.resource(f, 0x28, self.r(resources + resource_id * 8)))
                    current = f.r(0x28, 4)
                    paid = multiply_binary32(signed16_binary32(coefficient), amount)
                    f.w(0x30, 4, subtract_binary32(current, paid))
                    f.w(0x28, 8, f.r(0x30, 8))
                    f.w(0x28, 8, f.r(0x28, 8) ^ _RD)
                    f.w(0x28, 8, f.r(0x28, 8) + _RC)
                    f.w(0x28, 8, f.r(0x28, 8) ^ _RB)
                    f.w(0x28, 8, f.r(0x28, 8) ^ _RA)
                    self.w(resources + resource_id * 8, 8, f.r(0x28, 8))
                    colored = self.invoke(self.calls, 0x141734F30, owner)
                    publish = _raw(colored, "resource color AL") & 255 != 0
                    if not publish:
                        option = self.invoke(self.calls, 0x14172AC80, owner)
                        publish = _raw(option, "resource option EAX") & _U32 != 0
                    if publish:
                        bus = self.invoke(self.calls, 0x140A69450)
                        owner_id = self.r(owner + 0x648, 4)
                        f.w(0x20, 4, owner_id)
                        f.w(0, 8, _widen(paid))
                        self.invoke(
                            self.events,
                            0x140A635D0,
                            _raw(bus, "resource bus RAX"),
                            f.h(0x20),
                            resource_id,
                            2,
                            f.h(0),
                        )
                row = (row + 6) & _U64
            return 1


def bind_replay_object_health_repair(
    context: ReplayTaskRebuildStorage,
    fp_calls: ReplayTaskRebuildCalls,
    *,
    calls: ReplayTaskRebuildCalls,
    virtual_fp_calls: ReplayTaskRebuildCalls,
    virtual_fp_apply_calls: ReplayTaskRebuildCalls,
    cost_check_fp_home_calls: ReplayTaskRebuildCalls,
    resource_event_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayObjectHealthRepairProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind the frozen mixed-FP API with required effects and explicit storage.

    Return annotations expose known lowAL values; no native upper RAX bits are
    fabricated. Unknown FP target/arguments/payload/result identities pass to
    fp_calls unchanged. Physical stack, FP status and upper lanes are excluded.
    """
    channels = (
        virtual_fp_calls,
        virtual_fp_apply_calls,
        cost_check_fp_home_calls,
        resource_event_home_calls,
    )
    for channel in (fp_calls, calls, *channels):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayObjectHealthRepairProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual locals/profile and exact MXCSR1f80 required for health/repair")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if fp_calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return fp_calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed health/repair FP call")
        _validate(context, calls, *args)
        _unsigned(args[2 if target == _COST else 1], 4, "raw health/repair FP word")
        state = _Health(context, calls, channels, bind_local, profile)
        if target == _INCREMENT:
            return state.increment(*args)
        if target == _REPAIR:
            return state.repair(*args)
        return state.cost(*args)

    return ReplayTaskRebuildCalls(dispatch)
