"""Six whole build54800 Moving, Animated, motion and scalar update bodies.

Source/API: object-virtual-update-source-v1,2328 instruction bytes/512 rows.
Actual Base update, virtual, spatial, logging, lookup, RNG and exceptional
sqrt effects remain mandatory. This does not restore or tick a recording.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import add_binary32, compare_binary32, multiply_binary32
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

_MOVING, _ANIMATED, _MOTION = 0x14120E560, 0x141141E60, 0x141075310
_COUNTER, _ELAPSED, _SQRT = 0x1410BCE10, 0x141604200, 0x140A82E00
_ARITIES = {_MOVING: 1, _ANIMATED: 1, _MOTION: 3, _COUNTER: 0, _ELAPSED: 1, _SQRT: 1}
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MASTER_A, _MASTER_B = 0x6A586EB28AC201FC, 0x0CF19788B2554E70


@dataclass(frozen=True, slots=True)
class ReplayMovingUpdateProfile:
    """Explicit logical prefixes, including Animated40 and motione8 homes.

    Those two homes are physical caller shadow space in the originals. These
    views retain semantic offsets, without physical saves or stack adjacency.
    Moving's cookie40, native EH/faults, FP flags and upper lanes are excluded.
    """

    moving: bytes
    animated: bytes
    motion: bytes

    def __post_init__(self) -> None:
        for value, size in ((self.moving, 0x40), (self.animated, 0x48), (self.motion, 0xF0)):
            if type(value) is not bytes or len(value) != size:
                raise ValueError("explicit40/48/f0-hex-byte Moving update seeds required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _word(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual low-XMM binary32 word")
    _unsigned(value, 4, label)
    return value


class _Moving:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        virtual: ReplayTaskRebuildCalls,
        scalar_fp: ReplayTaskRebuildCalls,
        motion_fp: ReplayTaskRebuildCalls,
        virtual_fp: ReplayTaskRebuildCalls,
        virtual_fp_home: ReplayTaskRebuildCalls,
        logger: ReplayTaskRebuildCalls,
        bind_local: LocalBinding,
        profile: ReplayMovingUpdateProfile,
    ) -> None:
        self.context, self.calls, self.virtual = context, calls, virtual
        self.scalar_fp, self.motion_fp, self.virtual_fp = scalar_fp, motion_fp, virtual_fp
        self.virtual_fp_home, self.logger = virtual_fp_home, logger
        self.bind_local, self.profile = bind_local, profile

    def r(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def w(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def invoke(self, channel: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
        if channel.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return channel.call(target, tuple(value & _U64 for value in args), None)

    def call(self, target: int, *args: int) -> int | None:
        return self.invoke(self.calls, target, *args)

    def raw(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} RAX")

    def al(self, target: int, *args: int) -> int:
        return self.raw(target, *args) & 255

    def fp(self, target: int, *args: int) -> int:
        return _word(self.invoke(self.scalar_fp, target, *args), f"{target:x} low-XMM0")

    def virtual_call(self, receiver: int, slot: int, *args: int) -> int | None:
        return self.invoke(self.virtual, self.r(self.r(receiver) + slot), receiver, *args)

    def frame(self, seed: bytes) -> _Frame:
        return _Frame(self.context, self.bind_local, seed)

    def master(self, f: _Frame, home: int, subject: int) -> int:
        f.w(home, 8, self.r(subject + 0x10))
        f.w(home, 8, f.r(home, 8) - _MASTER_A)
        f.w(home, 8, f.r(home, 8) - _MASTER_B)
        return f.r(home, 8)

    def sqrt(self, word: int) -> int:
        bits = word
        if ((bits - 0x800000) & _U32) >= 0x7F000000:
            if not (bits + bits) & _U32 or bits == 0x7F800000:
                return word
            if bits > 0x7F800000:
                return self.fp(0x140A80320, word)
            bits = (multiply_binary32(word, self.r(0x143217EA0, 4)) + 0xF4800000) & _U32
        alternate = ((bits & 0xFFFFFF) << 7) & _U32
        fixed = ((bits | 0xFF800000) << 8) & _U32
        if bits & 0x800000:
            fixed = alternate
        index = bits >> 17 & 0x7F
        exponent = ((bits >> 1) + 0x1FC00000) & 0x7F800000
        product = fixed
        fixed = fixed << 16 & _U32
        table = self.r(0x143218010 + index * 2, 2) << 16
        product = (product * table & _U64) >> 32
        correction = (product * table & _U64) >> 32
        residual = (0xC0000000 - correction) & _U32
        first = (residual * product & _U64) >> 32
        second = (residual * table & _U64) >> 32
        twice = first * 2 & _U32
        second = second * 2 & _U32
        correction = (second * twice & _U64) >> 32
        residual = (0xC0000000 - correction) & _U32
        approximation = (residual * twice & _U64) >> 32
        approximation = ((approximation - 1) & _U32) >> 6
        error = ((approximation + 1) * approximation - fixed) & _U32
        rounded = ((approximation + (error >> 31)) & 0x7FFFFF) | exponent
        delta = (error + 1 + approximation) & _U32
        adjustment = ((delta ^ error) & 0x80000000) | (0x1000000 if delta else 0)
        return add_binary32(adjustment, rounded)

    def magnitude(self, subject: int) -> int:
        motion = self.r(subject + 0x400)
        x, y, z = self.r(motion, 4), self.r(motion + 4, 4), self.r(motion + 8, 4)
        y = multiply_binary32(y, y)
        x = multiply_binary32(x, x)
        z = multiply_binary32(z, z)
        return self.fp(_SQRT, add_binary32(add_binary32(y, x), z))

    def buffer(self, f: _Frame, subject: int) -> None:
        receiver = self.r(subject + 0x3B0)
        if not receiver:
            return
        if self.al(0x140B2CFF0, receiver):
            comparison = compare_binary32(self.r(subject + 0x350, 4), 0)
            if comparison is None or comparison < 0:
                return
            enabled = self.r(subject + 0x3B8, 1)
            receiver = self.r(subject + 0x3B0)
            if enabled:
                table = self.r(subject)
                value = self.fp(self.r(table + 0x218), subject)
                height, z, x = (self.r(subject + offset, 4) for offset in (0x3C0, 0x3C4, 0x3BC))
                f.w(0x20, 4, value)
                self.invoke(self.virtual_fp_home, 0x140B2D140, receiver, x, z, height, f.h(0x20))
            else:
                height, z, x = (self.r(subject + offset, 4) for offset in (0x3C0, 0x3C4, 0x3BC))
                self.invoke(self.virtual_fp, 0x140B2D060, receiver, x, z, height)
        else:
            previous = self.r(subject + 0x3A8, 4)
            now = self.raw(0x140A71140) & _U32
            if ((now - previous) & _U32) >= 30000:
                receiver = self.r(subject + 0x3B0)
                if receiver:
                    self.call(0x140B2CFC0, receiver)
                    self.call(0x142D6BAB4, receiver, 8)
                self.w(subject + 0x3B0, 8, 0)

    def target(self, f: _Frame, subject: int) -> None:
        if self.r(subject + 0x3A0, 4) == _U32:
            return
        owner = self.r(subject + 0x18)
        f.w(0x30, 8, self.r(self.r(owner + 0x98) + 0x800))
        f.w(0x30, 8, f.r(0x30, 8) ^ 0x6AE24D3352F04511)
        f.w(0x30, 8, f.r(0x30, 8) ^ 0xC22D6B496D833977)
        f.w(0x30, 8, f.r(0x30, 8) - 0x042AC42976FCCEF5)
        f.w(0x30, 8, f.r(0x30, 8) ^ 0xA9834B738A7DD167)
        held = f.r(0x30, 8)
        game = self.r(0x144353698)
        f.w(0x30, 8, held)
        world = self.raw(0x140D6ACC0, game)
        target = self.raw(0x141617DB0, world, self.r(subject + 0x3A0, 4))
        if target:
            distance = self.fp(0x14124E840, subject, target)
            limit = f.r(0x30, 4)
            comparison = compare_binary32(distance, multiply_binary32(limit, limit))
            if comparison is None or comparison <= 0:
                return
        self.w(subject + 0x3A0, 4, _U32)
        self.w(subject + 0x3A4, 4, 0)

    def moving(self, subject: int) -> int:
        with self.frame(self.profile.moving) as f:
            held = self.r(subject + 0x198, 4)
            if held <= self.raw(_COUNTER) & _U32:
                clock = self.r(self.r(subject + 0x18) + 8)
                self.w(subject + 0x198, 4, max(held - self.r(clock + 0x7C, 4), 0))
            motion = self.r(subject + 0x400)
            if motion:
                clock = self.r(self.r(subject + 0x18) + 8)
                elapsed = self.fp(_ELAPSED, clock)
                self.invoke(self.motion_fp, _MOTION, motion, subject, elapsed)
                value = self.magnitude(subject)
                comparison = compare_binary32(value, self.r(0x1431FE590, 4))
                if comparison is not None and comparison > 0:
                    self.w(subject + 0x350, 4, self.magnitude(subject))
                if self.r(subject + 0x3B9, 1) == 1:
                    self.virtual_call(subject, 0x600, subject + 0x3E0)
                    self.w(subject + 0x410, 4, self.r(subject + 0x410, 4) + 1)
                    self.w(subject + 0x3B9, 1, 0)
                else:
                    self.w(subject + 0x410, 4, 0)
            refresh = bool(self.r(subject + 0x58))
            if not refresh:
                refresh = ((self.r(subject + 0x68) - self.r(subject + 0x60)) & _U64) >= 8
            if not refresh:
                refresh = ((self.r(subject + 0x80) - self.r(subject + 0x78)) & _U64) >= 8
            if refresh:
                x, z = self.r(subject + 0x3BC, 4), self.r(subject + 0x3C4, 4)
                f.w(0x30, 4, x)
                height = self.r(subject + 0x3C0, 4)
                f.w(0x38, 4, height)
                f.w(0x34, 4, z)
                self.call(0x141248570, subject, f.h(0x30))
            self.buffer(f, subject)
            self.target(f, subject)
            if _raw(self.virtual_call(subject, 0x620), "Moving virtual620 AL") & 255:
                encoded = self.r(subject + 0x10)
                held = self.r(subject + 0x20)
                f.w(0x30, 8, encoded)
                f.w(0x30, 8, f.r(0x30, 8) - _MASTER_A)
                f.w(0x30, 8, f.r(0x30, 8) - _MASTER_B)
                if self.r(f.r(0x30, 8) + 0x48) == held:
                    animation = self.r(subject + 0x28)
                    current = self.r(subject + 0x20)
                    if _raw(self.virtual_call(animation, 0x40, current), "animation40 AL") & 255:
                        self.call(0x141247F00, subject, 0, 0x7FFF)
            return self.al(_ANIMATED, subject)

    def animated(self, subject: int) -> int:
        with self.frame(self.profile.animated) as f:
            result = self.al(0x141249740, subject)
            state = self.r(subject + 0x188, 1)
            if state == 4:
                animation = self.r(subject + 0x28)
                table = self.r(animation)
                target = self.r(table + 0x20)
                current = self.r(subject + 0x20)
                if (
                    not _raw(
                        self.invoke(self.virtual, target, animation, current), "animation20 AL"
                    )
                    & 255
                ):
                    kind = self.r(subject + 0xF, 1)
                    self.w(subject + 0x188, 1, 5)
                    self.w(subject + 0x350, 4, 0)
                    if kind < 0x50:
                        self.call(0x141265AC0, subject)
            elif state == 3:
                selected = _raw(self.virtual_call(subject, 0x850), "Animated virtual850 RAX")
                table = self.r(subject)
                target = self.r(table + 0xA8)
                self.invoke(self.virtual, target, subject, 4 if selected else 5)
            owner = self.r(subject + 0x18)
            animation = self.r(subject + 0x28)
            speed = self.r(subject + 0x350, 4)
            clock = self.r(owner + 8)
            table = self.r(animation)
            elapsed = self.r(clock + 0x164, 4)
            self.invoke(self.virtual_fp, self.r(table + 0x10), animation, elapsed, speed)
            master = self.master(f, 0x40, subject)
            if not self.r(master + 0x48):
                return result
            if _raw(self.virtual_call(subject, 0x620), "Animated virtual620 AL") & 255:
                return result
            master = self.master(f, 0x40, subject)
            current = self.r(subject + 0x20)
            if current != self.r(master + 0x40):
                master = self.master(f, 0x40, subject)
                current = self.r(subject + 0x20)
                if current != self.r(master + 0x48):
                    return result
            animation = self.r(subject + 0x28)
            selected = _raw(self.virtual_call(animation, 0x40, current), "Animated animation40 AL")
            if not selected & 255:
                return result
            random = self.raw(0x140903E40, 0x144352FD0, 0x14329E98C, 0xB0) & _U32
            if _signed(random, 4) > 0x3FFF:
                self.call(0x141247F00, subject, int(self.r(subject + 0x2CC, 4) == 0), 0x7FFF)
            return result

    def motion(self, motion: int, subject: int, elapsed: int) -> int:
        if not subject:
            return 0
        with self.frame(self.profile.motion) as f:
            table = self.r(subject)
            pointer = self.invoke(self.virtual, self.r(table + 0x568), subject, f.h(0x60))
            acceleration = self.r(motion + 0x14, 4)
            velocity = self.r(motion + 8, 4)
            f.w(0x20, 8, _raw(pointer, "motion position RAX"))
            velocity = _word(
                self.invoke(
                    self.virtual_fp_home,
                    self.r(table + 0x628),
                    subject,
                    velocity,
                    acceleration,
                    elapsed,
                    f.h(0x20),
                ),
                "motion virtual628 low-XMM0",
            )
            acceleration = self.r(motion + 0x14, 4)
            self.w(motion + 8, 4, velocity)
            encoded = self.r(subject + 0x10)
            held_id = self.r(subject + 8, 4)
            f.w(0xE8, 8, encoded)
            f.w(0xE8, 8, f.r(0xE8, 8) - _MASTER_A)
            f.w(0xE8, 8, f.r(0xE8, 8) - _MASTER_B)
            f.w(0xE8, 8, self.r(f.r(0xE8, 8) + 0x18))
            f.w(0xE8, 8, f.r(0xE8, 8) ^ 0x349E37847AD69F19)
            f.w(0xE8, 8, f.r(0xE8, 8) - 0x47E37DFF0616CE4F)
            kind = _signed(f.r(0xE8, 8) & 0xFFFF, 2) & _U32
            master = self.master(f, 0xE8, subject)
            name = self.raw(0x140A4B870, master)
            current_id = self.r(subject + 8, 4)
            global_id = self.r(0x14435A264, 4)
            string = self.r(name)
            f.w(0x50, 8, _widen(velocity))
            f.w(0x48, 8, _widen(acceleration))
            f.w(0x40, 8, _widen(elapsed))
            f.w(0x38, 4, held_id)
            f.w(0x30, 4, kind)
            f.w(0x28, 8, string)
            f.w(0x20, 8, 0x14329D690)
            self.invoke(self.logger, 0x140B6EF80, 0x17, 1, global_id, current_id, f.h(0x20))
            for home in (0x60, 0x6C, 0x78):
                self.virtual_call(subject, 0x568, f.h(home))
            displacement = multiply_binary32(elapsed, self.r(motion + 8, 4))
            table = self.r(subject)
            self.invoke(self.virtual_fp, self.r(table + 0x5F8), subject, displacement)
            return 1


def bind_replay_moving_update(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    virtual_calls: ReplayTaskRebuildCalls,
    scalar_fp_calls: ReplayTaskRebuildCalls,
    motion_fp_calls: ReplayTaskRebuildCalls,
    virtual_fp_calls: ReplayTaskRebuildCalls,
    virtual_fp_home_calls: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayMovingUpdateProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind six complete logical bodies, with explicit reached typed effects.

    Known FP return annotations are raw low-XMM words, never GP reinterpretation.
    Actual FP category routing must reenter known addressed implementations.
    Unknown calls preserve arguments, payload and returned identity unchanged.
    Native physical stack, cookies, faults/EH, threads and FP flags are excluded.
    """
    for channel in (
        calls,
        virtual_calls,
        scalar_fp_calls,
        motion_fp_calls,
        virtual_fp_calls,
        virtual_fp_home_calls,
        logger_home_calls,
    ):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayMovingUpdateProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual locals/profile and exact MXCSR1f80 Moving update required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed Moving update call")
        _validate(context, calls, *args)
        if target == _MOTION:
            _unsigned(args[2], 4, "motion low-XMM2 elapsed")
        elif target == _SQRT:
            _unsigned(args[0], 4, "sqrt low-XMM0")
        body = _Moving(
            context,
            bound,
            virtual_calls,
            scalar_fp_calls,
            motion_fp_calls,
            virtual_fp_calls,
            virtual_fp_home_calls,
            logger_home_calls,
            bind_local,
            profile,
        )
        if target == _MOVING:
            return body.moving(args[0])
        if target == _ANIMATED:
            return body.animated(args[0])
        if target == _MOTION:
            return body.motion(*args)
        if target == _SQRT:
            return body.sqrt(args[0])
        if target == _ELAPSED:
            return body.r(args[0] + 0x164, 4)
        return 5000

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
