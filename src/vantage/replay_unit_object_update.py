"""Six whole build54800 Unit update/math/predicate caller bodies.

Source/API: unit-object-update-source-v1,3172B/707 assembly rows. Existing
Combat,clock,stack and owner predicates remain delegated; reached graphic,
position,health,FP import and suffix effects are mandatory capabilities.
This does not restore a recording World or commit a complete game tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    divide_binary32,
    multiply_binary32,
    subtract_binary32,
)
from .replay_command_batch import _multiply64, _parts64, _round64
from .replay_manager_queues import _Frame
from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _cvtt,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate

_UNIT, _ABS, _FMOD, _MASTER_PRED, _PERCENT, _IDLE = (
    0x1412BD4C0,
    0x140A81F80,
    0x142D6E53D,
    0x14114B320,
    0x14114C340,
    0x140D1B180,
)
_ARITIES = {_UNIT: 1, _ABS: 1, _FMOD: 2, _MASTER_PRED: 1, _PERCENT: 1, _IDLE: 1}
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MA, _MB = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_HX, _HA = 0x0F2A55F7A61DD00E, 0x147B5E081EC087D9
_RA, _RB, _RC, _RD = (
    0x6AE24D3352F04511,
    0xC22D6B496D833977,
    0x042AC42976FCCEF5,
    0xA9834B738A7DD167,
)


@dataclass(frozen=True, slots=True)
class ReplayUnitObjectUpdateProfile:
    """Explicit90/10/0ch semantic views, no native saves/stack adjacency."""

    unit: bytes
    master_predicate: bytes
    fabs: bytes

    def __post_init__(self) -> None:
        for seed, size in ((self.unit, 0x90), (self.master_predicate, 0x10), (self.fabs, 0xC)):
            if type(seed) is not bytes or len(seed) != size:
                raise ValueError("explicit90/10/0c-hex-byte Unit update seeds required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _word(value: int | None, label: str) -> int:
    value = _raw(value, label)
    _unsigned(value, 4, label)
    return value


def _ratio64(numerator: int, denominator: int) -> int:
    """One DIVSD of two exact zero-extended u32 conversions, using integers."""
    if not denominator:
        return 0x7FF0000000000000 if numerator else 0xFFF8000000000000
    if not numerator:
        return 0
    top = numerator.bit_length() - denominator.bit_length()
    if top >= 0:
        top -= numerator < denominator << top
    else:
        top -= numerator << -top < denominator
    scale = top - 52
    rounded, remainder = divmod(numerator << -scale, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and rounded & 1):
        rounded += 1
    return _round64(rounded, scale, False)


def _cvtt32_double(word: int) -> int:
    if word >> 52 & 0x7FF == 0x7FF:
        return 0x80000000
    significand, scale = _parts64(word)
    magnitude = significand << scale if scale >= 0 else significand >> -scale
    value = -magnitude if word >> 63 else magnitude
    return value & _U32 if -(1 << 31) <= value < 1 << 31 else 0x80000000


def _minss(destination: int, source: int) -> int:
    return destination if compare_binary32(destination, source) == -1 else source


def _maxss(destination: int, source: int) -> int:
    return destination if compare_binary32(destination, source) == 1 else source


class _Unit:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        channels: tuple[ReplayTaskRebuildCalls, ...],
        bind_local: LocalBinding,
        profile: ReplayUnitObjectUpdateProfile,
    ) -> None:
        self.context, self.calls = context, calls
        (self.fp, self.imports_fp, self.virtual_fp, self.apply_fp, self.position, self.graphic) = (
            channels
        )
        self.bind_local, self.profile = bind_local, profile

    def r(self, at: int, width: int = 8) -> int:
        return _read(self.context, at, width)

    def w(self, at: int, width: int, value: int) -> None:
        _write(self.context, at, width, value)

    def invoke(self, channel: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
        if channel.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return channel.call(target, tuple(value & _U64 for value in args), None)

    def call(self, target: int, *args: int) -> int | None:
        return self.invoke(self.calls, target, *args)

    def al(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} AL") & 255

    def world(self, obj: int) -> int:
        return self.r(self.r(obj + 0x18) + 8)

    def master_value(self, f: _Frame, value: int, home: int = 0x50) -> int:
        f.w(home, 8, value)
        f.w(home, 8, f.r(home, 8) - _MA)
        f.w(home, 8, f.r(home, 8) - _MB)
        return f.r(home, 8)

    def master(self, f: _Frame, obj: int) -> int:
        return self.master_value(f, self.r(obj + 0x10))

    def class_value(self, f: _Frame, master: int) -> int:
        f.w(0x50, 8, self.r(master + 0x38))
        f.w(0x50, 8, f.r(0x50, 8) - 0x50A06BCECEBEF905)
        f.w(0x50, 8, f.r(0x50, 8) + 0x5B32AA7995D95916)
        return f.r(0x50, 8) & 0xFFFF

    def object_class(self, f: _Frame, obj: int) -> int:
        return self.class_value(f, self.master(f, obj))

    def kind(self, f: _Frame, obj: int) -> int:
        master = self.master(f, obj)
        f.w(0x50, 8, self.r(master + 0x18))
        f.w(0x50, 8, f.r(0x50, 8) ^ 0x349E37847AD69F19)
        f.w(0x50, 8, f.r(0x50, 8) - 0x47E37DFF0616CE4F)
        return f.r(0x50, 8) & 0xFFFF

    def resource(self, f: _Frame, encoded: int) -> None:
        f.w(0x50, 8, encoded)
        f.w(0x50, 8, f.r(0x50, 8) ^ _RA)
        f.w(0x50, 8, f.r(0x50, 8) ^ _RB)
        f.w(0x50, 8, f.r(0x50, 8) - _RC)
        f.w(0x50, 8, f.r(0x50, 8) ^ _RD)
        held = f.r(0x50, 8)
        f.w(0x50, 8, held)

    def health(self, f: _Frame, encoded: int) -> int:
        f.w(0x50, 8, encoded)
        return self.health_current(f)

    def health_current(self, f: _Frame) -> int:
        f.w(0x50, 8, f.r(0x50, 8) ^ _HX)
        f.w(0x50, 8, f.r(0x50, 8) - _HA)
        return f.r(0x50, 8)

    def encode_health(self, f: _Frame) -> int:
        f.w(0x50, 8, f.r(0x58, 8))
        f.w(0x50, 8, f.r(0x50, 8) + _HA)
        f.w(0x50, 8, f.r(0x50, 8) ^ _HX)
        return f.r(0x50, 8)

    def regeneration(self, f: _Frame, obj: int) -> None:
        special = self.object_class(f, obj) == 0x12 or self.object_class(f, obj) == 0x35
        if special and self.r(obj + 0x188, 1) == 2:
            master = self.master(f, obj)
            value = self.r(self.world(obj) + 0x164, 4)
            value = multiply_binary32(value, self.r(master + 0x2D8, 4))
        else:
            world = self.world(obj)
            kind = self.kind(f, obj)
            owner = self.r(obj + 0x18)
            owner_id = self.r(owner + 0x648, 4)
            if not self.al(0x141691140, world, owner_id, _signed(kind, 2) & _U32, 0x68):
                return
            if self.r(obj + 0x188, 1) != 2:
                return
            resource = self.r(self.r(obj + 0x18) + 0x98)
            self.resource(f, self.r(resource + 0x8D0))
            owner = self.r(obj + 0x18)
            value = f.r(0x50, 4)
            elapsed = self.r(self.r(owner + 8) + 0x164, 4)
            value = multiply_binary32(value, elapsed)
        value = add_binary32(value, self.r(obj + 0x168, 4))
        comparison = compare_binary32(value, self.r(0x1436A02E4, 4))
        self.w(obj + 0x168, 4, value)
        if comparison is not None and comparison >= 0:
            self.w(obj + 0x168, 4, 0x42C80000)
        self.w(obj + 0x160, 2, 0x22)

    def counters(self, f: _Frame, obj: int) -> int:
        encoded = self.r(obj + 0x10)
        one = self.r(0x1436A0294, 4)
        master = self.master_value(f, encoded)
        if self.class_value(f, master) != 0x28:
            return one
        value = self.r(obj + 0x168, 4)
        if compare_binary32(value, 0) != 1:
            return one
        owner = self.r(obj + 0x18)
        elapsed = self.r(self.r(owner + 8) + 0x7C, 2)
        self.w(obj + 0x624, 2, self.r(obj + 0x624, 2) - elapsed)
        if _signed(self.r(obj + 0x624, 2), 2) > 0:
            return one
        self.w(obj + 0x168, 4, subtract_binary32(value, one))
        for member in (0x618, 0x61A, 0x61C, 0x61E, 0x620, 0x622):
            self.w(obj + member, 2, self.r(obj + member, 2) - 1)
        resource = self.r(owner + 0x98)
        self.resource(f, self.r(resource + 0x208))
        value = f.r(0x50, 4)
        value = multiply_binary32(value, self.r(0x1436A02F8, 4))
        self.w(obj + 0x624, 2, _cvtt(value))
        return one

    def stance(self, f: _Frame, obj: int) -> None:
        if self.r(self.master(f, obj) + 0x378, 1) != 2:
            return
        if not self.r(self.master(f, obj) + 0x388):
            return
        script = self.r(obj + 0x1F0)
        idle = bool(script) and bool(_raw(self.call(_IDLE, script), "script idle EAX") & _U32)
        if idle and not self.al(0x140B88B30, self.r(obj + 0x420)):
            if self.r(obj + 0x68D, 1):
                return
            encoded = self.r(obj + 0x10)
            kind = self.r(obj + 0xE, 1)
            animation = self.r(obj + 0x28)
            f.w(0x50, 8, encoded)
            held = f.r(0x50, 8) - _MA
            f.w(0x28, 2, kind)
            f.w(0x50, 8, held)
            held = f.r(0x50, 8) - _MB
            f.w(0x20, 4, 0)
            f.w(0x50, 8, held)
            master = f.r(0x50, 8)
            self.invoke(
                self.graphic,
                0x1414826E0,
                animation,
                self.r(master + 0x388),
                0x3C,
                0,
                f.h(0x20),
                f.h(0x28),
            )
            encoded = self.r(obj + 0x10)
            animation = self.r(obj + 0x28)
            master = self.master_value(f, encoded)
            self.call(0x141485F70, animation, self.r(master + 0x388), 2)
            self.w(obj + 0x68D, 1, 1)
        elif self.r(obj + 0x68D, 1):
            encoded = self.r(obj + 0x10)
            animation = self.r(obj + 0x28)
            master = self.master_value(f, encoded)
            self.call(0x141484E80, animation, self.r(master + 0x388))
            self.w(obj + 0x68D, 1, 0)

    def low_health(self, f: _Frame, obj: int, one: int) -> None:
        flag = self.object_class(f, obj) in (0x23, 0x40)
        f.w(0x50, 8, self.health(f, self.r(obj + 0x130)))
        if compare_binary32(one, f.r(0x50, 4)) != 1 or self.r(obj + 0x188, 1) != 2:
            return
        kind = self.kind(f, obj)
        if kind not in (0x20F, 0x210, 0x450) and (kind - 0x855) & 0xFFFF > 2 and not flag:
            return
        table = self.r(obj)
        f.w(0x48, 1, 0)
        f.w(0x70, 16, 0)
        f.w(0x80, 4, 0)
        target = self.r(table + 0x900)
        f.w(0x50, 8, self.r(obj + 0x180))
        held = f.r(0x50, 8) + 0x2B3719EF44DE99FF
        f.w(0x84, 8, _U64)
        f.w(0x50, 8, held)
        held = f.r(0x50, 8) + 0x21D14A25ED7C802C
        f.w(0x8C, 4, _U32)
        f.w(0x50, 8, held)
        f.w(0x60, 8, f.r(0x50, 8))
        encoded = self.r(obj + 0x178)
        z = f.r(0x60, 4)
        f.w(0x50, 8, encoded)
        f.w(0x50, 8, f.r(0x50, 8) - 0x61501AA6ECFD980A)
        f.w(0x50, 8, f.r(0x50, 8) + 0x6C5EAB60B426DD28)
        f.w(0x58, 8, f.r(0x50, 8))
        encoded = self.r(obj + 0x170)
        y = f.r(0x58, 4)
        f.w(0x50, 8, encoded)
        f.w(0x50, 8, f.r(0x50, 8) - 0x183CAC30D2441D0E)
        f.w(0x50, 8, f.r(0x50, 8) + 0x4C3FBA69E4EA7FD1)
        f.w(0x50, 8, f.r(0x50, 8))
        x = f.r(0x50, 4)
        f.w(0x40, 8, f.h(0x70))
        f.w(0x38, 4, one)
        f.w(0x30, 8, 0)
        f.w(0x28, 8, 0)
        f.w(0x20, 8, obj)
        self.invoke(
            self.position,
            target,
            obj,
            x,
            y,
            z,
            *(f.h(home) for home in (0x20, 0x28, 0x30, 0x38, 0x40, 0x48)),
        )

    def vfp(self, obj: int, slot: int) -> int | None:
        return self.invoke(self.virtual_fp, self.r(self.r(obj) + slot), obj)

    def periodic_health(self, obj: int, rate: int | None, one: int) -> None:
        rate_word = _word(rate, "virtual278 low-XMM0")
        magnitude = self.invoke(self.fp, _ABS, rate_word)
        epsilon = self.r(0x1432A1058, 4)
        comparison = compare_binary32(epsilon, _word(magnitude, "rate fabs low-XMM0"))
        if comparison is not None and comparison >= 0:
            return
        owner = self.r(obj + 0x18)
        interval = divide_binary32(self.r(0x1436A02E0, 4), rate_word)
        elapsed = self.r(self.r(owner + 8) + 0x164, 4)
        accumulated = add_binary32(elapsed, self.r(obj + 0x698, 4))
        interval &= self.r(0x1431B7530, 16) & _U32
        self.w(obj + 0x698, 4, accumulated)
        magnitude = self.invoke(self.fp, _ABS, interval)
        comparison = compare_binary32(epsilon, _word(magnitude, "interval fabs low-XMM0"))
        quotient = (
            divide_binary32(self.r(obj + 0x698, 4), interval)
            if comparison is None or comparison < 0
            else 0
        )
        fraction = self.invoke(self.fp, _FMOD, quotient, one)
        fraction_word = _word(fraction, "fmod low-XMM0")
        whole = subtract_binary32(quotient, fraction_word)
        self.w(obj + 0x698, 4, multiply_binary32(fraction_word, interval))
        if compare_binary32(whole, 0) != 1:
            return
        maximum = self.vfp(obj, 0xD0)
        health = self.vfp(obj, 0xC8)
        if compare_binary32(rate_word, 0) == 1:
            difference = subtract_binary32(
                _word(maximum, "maximum low-XMM0"), _word(health, "health low-XMM0")
            )
            amount = _minss(difference, whole)
            slot = 0xC0
        else:
            amount = _minss(_word(health, "health low-XMM0"), whole)
            slot = 0xB8
        if compare_binary32(amount, 0) == 1:
            self.invoke(self.apply_fp, self.r(self.r(obj) + slot), obj, amount)
        health = self.vfp(obj, 0xC8)
        comparison = compare_binary32(
            _word(health, "current health low-XMM0"), _word(maximum, "held maximum low-XMM0")
        )
        if comparison is not None and comparison >= 0:
            self.w(obj + 0x66C, 4, 0)

    def accumulate(self, f: _Frame, obj: int) -> None:
        bound = self.r(self.master(f, obj) + 0x3B8, 4)
        if compare_binary32(bound, self.r(obj + 0x668, 4)) != 1:
            return
        if self.al(_MASTER_PRED, obj) and _signed(self.al(_PERCENT, obj), 1) > 0:
            return
        master = self.master(f, obj)
        world = self.world(obj)
        encoded = self.r(obj + 0x10)
        elapsed = self.r(world + 0x164, 4)
        value = multiply_binary32(elapsed, self.r(master + 0x3BC, 4))
        value = add_binary32(value, self.r(obj + 0x668, 4))
        self.w(obj + 0x668, 4, value)
        master = self.master_value(f, encoded)
        value = self.r(obj + 0x668, 4)
        comparison = compare_binary32(value, self.r(master + 0x3B8, 4))
        if comparison is not None and comparison >= 0 and self.al(0x141734F30, self.r(obj + 0x18)):
            self.w(self.r(0x144415600) + 0x1874, 1, 1)

    def shield(self, f: _Frame, obj: int, one: int) -> None:
        current = self.r(obj + 0x6C4, 4)
        previous = self.r(obj + 0x6C0, 4)
        if compare_binary32(previous, current) != 1:
            return
        encoded = self.r(obj + 0x130)
        difference = subtract_binary32(current, previous)
        f.w(0x50, 8, encoded)
        f.w(0x50, 8, f.r(0x50, 8) ^ _HX)
        held = f.r(0x50, 8)
        difference &= self.r(0x1431B7530, 16) & _U32
        f.w(0x50, 8, held - _HA)
        f.w(0x58, 8, f.r(0x50, 8))
        value = subtract_binary32(f.r(0x58, 4), difference)
        f.w(0x58, 4, value)
        f.w(0x50, 8, self.encode_health(f))
        f.r(0x50, 8)
        f.w(0x50, 8, f.r(0x50, 8))
        f.w(0x58, 8, self.health_current(f))
        f.w(0x58, 4, _maxss(f.r(0x58, 4), one))
        f.w(0x58, 8, self.encode_health(f))
        self.w(obj + 0x130, 8, f.r(0x58, 8))
        self.w(obj + 0x6C0, 4, self.r(obj + 0x6C4, 4))

    def update(self, obj: int) -> int:
        with _Frame(self.context, self.bind_local, self.profile.unit) as f:
            self.regeneration(f, obj)
            one = self.counters(f, obj)
            self.stance(f, obj)
            self.low_health(f, obj, one)
            raw_parent = self.call(0x14114C3A0, obj)
            table = self.r(obj)
            parent = _raw(raw_parent, "Combat AL") & 255
            target = self.r(table + 0x278)
            rate = self.invoke(self.virtual_fp, target, obj)
            f.w(0x58, 8, self.health(f, self.r(obj + 0x130)))
            comparison = compare_binary32(f.r(0x58, 4), one)
            if comparison is not None and comparison >= 0 and self.r(obj + 0x188, 1) == 2:
                self.periodic_health(obj, rate, one)
            self.accumulate(f, obj)
            self.call(0x1412BC410, obj, parent)
            if not self.al(0x1412BD1D0, obj):
                pointer = self.r(obj + 0x818)
                if pointer:
                    self.w(obj + 0x818, 8, 0)
                    self.call(0x142D6BAB4, pointer, 8)
            for target in (0x1412B84C0, 0x1412BECC0, 0x1412BE050, 0x1412BC210):
                self.call(target, obj)
            self.shield(f, obj, one)
            if not self.al(0x1412B79B0, obj):
                self.call(0x1412BAB30, obj)
            return parent

    def percent(self, obj: int) -> int:
        start = self.r(obj + 0x510, 4)
        time = self.call(0x140D6AD50, self.r(0x144353698))
        interval = self.r(obj + 0x50C, 4)
        elapsed = ((_raw(time, "percentage clock EAX") & _U32) - start) & _U32
        numerator = 0 if elapsed > interval else (interval - elapsed) & _U32
        value = _ratio64(numerator, interval)
        value = _multiply64(value, self.r(0x1432A85D0, 8))
        return _cvtt32_double(value)


def bind_replay_unit_object_update(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    scalar_fp_calls: ReplayTaskRebuildCalls,
    imports_fp_calls: ReplayTaskRebuildCalls,
    virtual_fp_calls: ReplayTaskRebuildCalls,
    virtual_fp_apply_calls: ReplayTaskRebuildCalls,
    position_fp_home_calls: ReplayTaskRebuildCalls,
    graphic_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayUnitObjectUpdateProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind six entire callers with raw FP words, live homes and real effects.

    Exact masked MXCSR1f80 is required. Native FPflags/upperlanes,physicalstack,
    saves,faults/EH and concurrency are excluded. Unknown calls preserve their
    original argument,payload and returned identities. No default success/effect.
    """
    channels = (
        scalar_fp_calls,
        imports_fp_calls,
        virtual_fp_calls,
        virtual_fp_apply_calls,
        position_fp_home_calls,
        graphic_home_calls,
    )
    for channel in (calls, *channels):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayUnitObjectUpdateProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual locals/profile and exact MXCSR1f80 Unit update required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed Unit update call")
        _validate(context, calls, *args)
        body = _Unit(context, bound, channels, bind_local, profile)
        obj = args[0]
        if target == _UNIT:
            return body.update(obj)
        if target == _PERCENT:
            return body.percent(obj)
        if target == _IDLE:
            return int(
                body.r(obj + 0x1C0, 1) == 1
                and not body.r(obj + 0xD0, 4)
                and body.r(obj + 0x44, 4) == _U32
            )
        if target == _FMOD:
            for value in args:
                _unsigned(value, 4, "fmod raw low-XMM word")
            return body.invoke(imports_fp_calls, body.r(0x143199FA0), *args)
        if target == _ABS:
            _unsigned(obj, 4, "fabs raw low-XMM0")
            with _Frame(context, bind_local, profile.fabs) as f:
                f.w(8, 4, obj)
                f.w(8, 4, f.r(8, 4) & 0x7FFFFFFF)
                return f.r(8, 4)
        encoded = body.r(obj + 0x10)
        with _Frame(context, bind_local, profile.master_predicate) as f:
            master = body.master_value(f, encoded, 8)
            return int(body.r(master + 0x3C2, 2) == 0xFFFD)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
