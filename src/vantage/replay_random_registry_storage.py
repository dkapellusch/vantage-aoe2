"""Addressed build54800 World RNG reseeding and full-word draws.

Complete source1808B/466instructions in world-random-registry-source-v1. Real
formatter calls remain required on enabled logging, with one coherent explicit
logical frame per reached wrapper. No registry/stream/global is initialized.
Physical stack/cookie, native faults/unwind and concurrency are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_random import seed_replay_random
from .replay_random_storage import _validate
from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)

_REGISTRY, _SEED, _DRAW = 0x140FDDBF0, 0x140903F20, 0x140903AF0
_ENGINE, _LOGGER, _FORMAT = 0x140904060, 0x140902830, 0x14101ADB0
_ENABLE, _SECONDARY, _LOG = 0x14435505E, 0x14427C9B0, 0x144355068
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class ReplayRandomRegistryStorageProfile:
    """Explicit finite registry work and initial shared logging-frame bytes.

    Each reached slot, including null, spends one work unit. Shared synchronous
    owned reentry spends the same budget; the next outer call starts fresh.
    Logging scratch is the explicit post-RSP00..8f logical window. Only reached
    native stores replace its supplied bytes; no native padding is guessed.
    """

    maximum_slots: int
    logging_scratch: bytes

    def __post_init__(self) -> None:
        if type(self.maximum_slots) is not int or self.maximum_slots < 0:
            raise ValueError("explicit nonnegative registry work limit required")
        if type(self.logging_scratch) is not bytes or len(self.logging_scratch) != 0x90:
            raise ValueError("explicit144-byte logging scratch required")


@dataclass(slots=True)
class _State:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    bind_local: LocalBinding
    profile: ReplayRandomRegistryStorageProfile
    slots: int = 0

    def engine(self, engine: int, seed: int) -> None:
        # Registers carry all recurrence inputs: no old engine or metadata read.
        words = seed_replay_random(seed).words
        for i, word in enumerate(words):
            _write(self.context, engine + 4 * i, 4, word)
        _write(self.context, engine + 0x40, 4, 0)

    def format(
        self,
        frame: int,
        name: int,
        secondary: int,
        label: int,
        line: int,
        value: int,
        *,
        seed: bool,
    ) -> None:
        c = self.context
        yes_no = 0x1431F50BC if secondary else 0x14368B9D4
        _write(c, frame + 0x48, 4, 0xF)
        _write(c, frame + 0x40, 8, name)
        _write(c, frame + 0x68, 4, 0xF)
        if not seed:
            _write(c, frame + 0x38, 4, 2)
        logger = _read(c, _LOG, 8)
        _write(c, frame + 0x60, 8, yes_no)
        for home, pointed in ((0x70, 0x60), (0x78, 0x40), (0x80, 0x50), (0x88, 0x30)):
            _write(c, frame + home, 8, frame + pointed)
        if seed:
            _write(c, frame + 0x38, 4, 2)
        _write(c, frame + 0x58, 4, 0xF)
        _write(c, frame + 0x30, 4, line)
        _write(c, frame + 0x50, 8, label)
        _write(c, frame + 0x20, 8, frame + 0x70)
        _call(self.calls, _FORMAT, (logger, 0x26, 0x1431F50C0, 4, (frame + 0x70) & _U64))
        if _read(c, _ENABLE, 1):
            logger = _read(c, _LOG, 8)
            _write(c, frame + 0x60, 8, frame + 0x30)
            _write(c, frame + 0x38, 4, 7)
            _write(c, frame + 0x20, 8, frame + 0x60)
            _write(c, frame + 0x30, 4, value)
            fmt = 0x1431F50D8 if seed else 0x1431F5100
            _call(self.calls, _FORMAT, (logger, 0x26, fmt, 1, (frame + 0x60) & _U64))

    def seed(self, stream: int, value: int, label: int, line: int) -> None:
        c = self.context
        if _read(c, stream + 0x20, 1) and _read(c, _ENABLE, 1):
            name = _read(c, stream, 8)
            secondary = _read(c, _SECONDARY, 1)
            raw = bytearray(self.profile.logging_scratch)
            with self.bind_local(memoryview(raw)) as frame:
                _unsigned(frame, 8, "logging local address")
                self.format(frame, name, secondary, label, line, value, seed=True)
                # The wrapper frame remains live through its engine child.
                _call(self.calls, _ENGINE, ((stream + 0x24) & _U64, value))
        else:
            _call(self.calls, _ENGINE, ((stream + 0x24) & _U64, value))

    def log(self, stream: int, value: int, label: int, line: int) -> None:
        c = self.context
        if not _read(c, stream + 0x20, 1):
            return
        enabled = _read(c, _ENABLE, 1)
        secondary = _read(c, _SECONDARY, 1)  # Reached even with enable0.
        if not enabled:
            return
        name = _read(c, stream, 8)
        raw = bytearray(self.profile.logging_scratch)
        with self.bind_local(memoryview(raw)) as frame:
            _unsigned(frame, 8, "logging local address")
            self.format(frame, name, secondary, label, line, value, seed=False)

    def draw(self, stream: int, label: int, line: int) -> int:
        c = self.context
        _write(c, stream + 0x18, 4, _read(c, stream + 0x18, 4) + 1)
        index = _read(c, stream + 0x64, 4)
        old = _read(c, stream + 0x24 + index * 4, 4)
        third = stream + 0x24 + ((index - 3) & 15) * 4
        b = (((old * 2) & _U32) ^ _read(c, third, 4)) << 15 & _U32
        b ^= _read(c, third, 4) ^ old
        seventh = stream + 0x24 + ((index - 7) & 15) * 4
        v = (_read(c, seventh, 4) >> 11) ^ _read(c, seventh, 4)
        combined = v ^ b
        transformed = (((v << 10) ^ b) << 13) & _U32
        _write(c, stream + 0x24 + index * 4, 4, combined)
        index = (_read(c, stream + 0x64, 4) - 1) & 15
        _write(c, stream + 0x64, 4, index)
        selected = stream + 0x24 + index * 4
        transformed = ((transformed ^ (combined & 0xFED22169)) << 3) & _U32
        transformed ^= _read(c, selected, 4)
        transformed = (transformed << 2) & _U32
        transformed ^= _read(c, selected, 4) ^ combined ^ b
        _write(c, selected, 4, transformed)
        current = _read(c, stream + 0x64, 4)
        held = _read(c, stream + 0x24 + current * 4, 4)
        _call(self.calls, _LOGGER, (stream, held, label, line))
        return held  # No last-masked88 publication in this full-word draw.

    def registry(self, seed: int) -> None:
        count = _read(self.context, 0x143DB0AC0, 8)
        index = 0
        while index < count:
            if self.slots >= self.profile.maximum_slots:
                raise UnresolvedReplayTaskRebuild("random registry work limit exhausted")
            self.slots += 1
            base = _read(self.context, 0x143DB0AB0, 8)
            stream = _read(self.context, base + index * 8, 8)
            if stream:
                _call(self.calls, _SEED, (stream, seed, 0x1432967FC, 0x23))
                value = _call(self.calls, _DRAW, (stream, 0x1432967FC, 0x24), width=4)
                count = _read(self.context, 0x143DB0AC0, 8)
                seed = value
            index = (index + 1) & _U64


def bind_replay_random_registry_storage(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    profile: ReplayRandomRegistryStorageProfile,
    bind_local: LocalBinding,
) -> ReplayTaskRebuildCalls:
    """Own registry/seed wrapper/engine/full draw/logger, with actual formatter.

    Arguments are raw u64 before native width truncation. All known bodies use
    data=None. Registry(seed), seed(stream,seed,label,line), engine(engine,seed),
    draw(stream,label,line) and logger(stream,value,label,line) have exact source
    children; only full draw promises raw EAX, other incidental RAX is excluded.
    Reached owned child calls route through this same binding, sharing registry
    work during synchronous formatter reentry. Unknown calls delegate unchanged.

    Enabled logging binds one live144-byte initialized view with the supplied
    scratch. Actual14101adb0 receives current logger, category26, source format,
    argument count and the real pointer-array address. Caller must provide the
    formatter and reached strings/backing; no successful formatting is faked.
    Local pointers cannot escape their wrapper lifetime. Prior storage and
    formatter effects survive failure; only scoped local cleanup/budget reset
    is guaranteed by this owned profile.
    """
    _validate(context, calls)
    if not isinstance(profile, ReplayRandomRegistryStorageProfile) or not callable(bind_local):
        raise ValueError("explicit registry profile and actual local binding required")
    active: _State | None = None
    arities = {_REGISTRY: 1, _SEED: 4, _ENGINE: 2, _DRAW: 3, _LOGGER: 4}

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        nonlocal active
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed random registry storage call")
        _validate(context, calls, *args)
        outer = active is None
        if outer:
            active = _State(context, bound, bind_local, profile)
        state = active
        assert state is not None
        try:
            if target == _REGISTRY:
                state.registry(args[0] & _U32)
            elif target == _SEED:
                state.seed(args[0], args[1] & _U32, args[2], args[3] & _U32)
            elif target == _ENGINE:
                state.engine(args[0], args[1] & _U32)
            elif target == _LOGGER:
                state.log(args[0], args[1] & _U32, args[2], args[3] & _U32)
            else:
                return state.draw(args[0], args[1], args[2] & _U32)
        finally:
            if outer:
                active = None
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
