"""Build54800 cycle modes, notifications, policy and diagnostic services.

cycle-services-source-v1 retains22 whole originals and the prepared-call ABI.
Existing lifecycle settings/cell getters remain delegated to their owner.
Owned storage/GS and actual reached virtual, TLS, format and send effects are
required; this does not restore a recording or execute the game.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_METRIC, _OVERRIDE, _OWNED, _SPECIAL = 0x1409738C0, 0x140E05160, 0x140E051E0, 0x140E053D0
_NOTIFY, _HOUSEKEEP, _QUEUE, _PRIMARY = 0x140E08110, 0x140E0CA00, 0x140E16870, 0x140E169D0
_FLAGS, _ADMISSION, _SUMMARY = 0x140E16E00, 0x140E469E0, 0x140E64A70
_LIMIT, _CELL, _MODE = 0x140E68F60, 0x140E57AC0, 0x140E16880
_ROSTER, _ROW_READY, _ROW_ACTIVE = 0x140E4FD40, 0x140E50750, 0x140E50490
_DISPATCH, _COUNT, _RECORD, _LOOKUP, _RECORD_ALIAS = (
    0x140DF6100,
    0x1413D3E20,
    0x1413D3FA0,
    0x140E4FB80,
    0x1413D3F30,
)
_SETTINGS, _GAME, _EXTERNAL = 0x1442DA8A0, 0x144353698, 0x1442846F0
_CLOCK, _HOST, _SECOND, _LOG, _LOGGER = (
    0x140E68F80,
    0x140A71140,
    0x143266E00,
    0x14101ADB0,
    0x144355068,
)
_ARITIES = {
    _METRIC: 2,
    _OVERRIDE: 1,
    _OWNED: 1,
    _SPECIAL: 1,
    _NOTIFY: 3,
    _HOUSEKEEP: 1,
    _QUEUE: 1,
    _PRIMARY: 1,
    _FLAGS: 1,
    _ADMISSION: 1,
    _SUMMARY: 1,
    _LIMIT: 1,
    _CELL: 1,
    _MODE: 1,
    _ROSTER: 2,
    _ROW_READY: 1,
    _ROW_ACTIVE: 1,
    _DISPATCH: 4,
    _COUNT: 2,
    _RECORD: 2,
    _LOOKUP: 1,
    _RECORD_ALIAS: 2,
}


@dataclass(frozen=True, slots=True)
class ReplayCycleServicesProfile:
    """Explicit semantic prefixes and owned engine GS base, never host GS."""

    owned: bytes
    special: bytes
    notify: bytes
    housekeeping: bytes
    primary: bytes
    flags: bytes
    admission: bytes
    row_lookup: bytes
    row_ready: bytes
    row_active: bytes
    dispatch: bytes
    gs_base: int

    def __post_init__(self) -> None:
        for seed, size in (
            (self.owned, 0x30),
            (self.special, 8),
            (self.notify, 0xB8),
            (self.housekeeping, 0x38),
            (self.primary, 0x14),
            (self.flags, 8),
            (self.admission, 0x38),
            (self.row_lookup, 0x40),
            (self.row_ready, 0x24),
            (self.row_active, 0x28),
            (self.dispatch, 0x90),
        ):
            if type(seed) is not bytes or len(seed) != size:
                raise ValueError("explicit30/8/b8/38/14/8/38/40/24/28/90-hex-byte seeds required")
        _unsigned(self.gs_base, 8, "owned engine GS base")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _eax(value: int | None, label: str) -> int:
    return _raw(value, label) & _U32


def _al(value: int | None, label: str) -> int:
    return _raw(value, label) & 255


class _Services:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        imports: ReplayTaskRebuildCalls,
        virtual: ReplayTaskRebuildCalls,
        logger: ReplayTaskRebuildCalls,
        error: ReplayTaskRebuildCalls,
        popup: ReplayTaskRebuildCalls,
        send: ReplayTaskRebuildCalls,
        formatter: ReplayTaskRebuildCalls,
        atomics: ReplayUnitAIMapAtomics,
        bind_local: LocalBinding,
        profile: ReplayCycleServicesProfile,
    ) -> None:
        self.context, self.calls, self.imports, self.virtual = context, calls, imports, virtual
        self.logger, self.error, self.popup, self.send = logger, error, popup, send
        self.formatter, self.atomics, self.bind_local = formatter, atomics, bind_local
        self.profile = profile

    def r(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def w(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def frame(self, seed: bytes) -> _Frame:
        return _Frame(self.context, self.bind_local, seed)

    def invoke(self, channel: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
        if channel.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return channel.call(target, tuple(value & _U64 for value in args), None)

    def call(self, target: int, *args: int) -> int | None:
        return self.invoke(self.calls, target, *args)

    def eax(self, target: int, *args: int) -> int:
        return _eax(self.call(target, *args), f"{target:x} EAX")

    def al(self, target: int, *args: int) -> int:
        return _al(self.call(target, *args), f"{target:x} AL")

    def virtual_call(self, receiver: int, slot: int, *args: int) -> int | None:
        return self.invoke(self.virtual, self.r(self.r(receiver) + slot), receiver, *args)

    def metric(self, receiver: int, selector: int) -> int:
        kind = self.r(receiver + 8, 4)
        if kind not in (0, 1, 2, 3):
            return 0
        index = _signed(selector & _U32, 4)
        data = self.r(receiver)
        return self.r(data + index * 48 + (0x2C if kind == 0 else 0x28), 4)

    def override(self, manager: int) -> int:
        clock = self.r(manager + 0x358)
        first = self.eax(_CLOCK, clock)
        following = self.eax(_LIMIT, clock)
        if ((following - first) & _U32) > 1:
            return 1
        receiver = self.r(manager + 0x2E8)
        return int(_eax(self.virtual_call(receiver, 0x1E0), "override virtual1e0 EAX") != 0)

    def owned(self, manager: int) -> int:
        with self.frame(self.profile.owned) as f:
            cell = _raw(self.call(_CELL, manager + 0xCB8), "owned session cell RAX")
            if not self.r(cell):
                return 0
            mode = self.r(manager + 0x318, 4)
            f.w(0x20, 4, 7)
            f.w(0x24, 4, 8)
            if f.contains(0x20, 2, mode):
                return 0
            cell = _raw(self.call(0x140E15A80, manager, f.h(0x28)), "owned role cell RAX")
            selected = self.r(cell)
            return int(self.r(manager + 0xD18) == selected)

    def special(self, manager: int) -> int:
        with self.frame(self.profile.special) as f:
            mode = self.r(manager + 0x318, 4)
            f.w(0, 4, 7)
            f.w(4, 4, 8)
            return int(f.contains(0, 2, mode))

    def primary(self, manager: int) -> int:
        with self.frame(self.profile.primary) as f:
            mode = self.r(manager + 0x318, 4)
            f.w(0, 16, self.r(_SECOND, 16))
            f.w(0x10, 4, 8)
            return int(f.contains(0, 5, mode))

    def flags(self, manager: int) -> int:
        if self.r(self.r(manager + 0x398) + 1, 1):
            return 1
        if self.r(self.r(manager + 0x398) + 2, 1):
            return 1
        with self.frame(self.profile.flags) as f:
            mode = self.r(manager + 0x318, 4)
            f.w(0, 4, 7)
            f.w(4, 4, 8)
            return int(f.contains(0, 2, mode))

    def descriptor(self, f: _Frame, at: int) -> None:
        f.w(at, 16, 0)
        f.w(at + 8, 4, 0)
        f.w(at, 8, 0x143218B60)
        f.w(at + 0x10, 16, 0)
        f.w(at + 0x20, 8, 0)

    def serialize(self, f: _Frame, result: int, descriptor: int, record: int) -> None:
        registry = _raw(self.call(0x14098F250), "cycle registry RAX")
        service = _raw(self.call(0x140942110, registry, 0x144121850), "cycle serializer RAX")
        if service:
            self.virtual_call(service, 0x18, f.h(result), f.h(descriptor), record)
        else:
            name = self.call(0x142D6E3ED, 0x144121858, 0x144C9CDB0)
            f.w(0x28, 8, _raw(name, "cycle RTTI name RAX"))
            f.w(0x20, 8, 0x1431FAC58)
            self.invoke(
                self.error, 0x140A08840, f.h(result), 0, 0x1431FAC00, 0x2F5, f.h(0x20), f.h(0x28)
            )
        self.call(0x14096B890, f.h(result))
        control = f.r(result + 0x20, 8)
        if control:
            _release(self.context, control, self.virtual, self.atomics)
        self.call(0x1402BD7F0, f.h(result))

    def packet(self, f: _Frame, count: int, width: int, time: int) -> None:
        f.w(0x80, 1, 0x53)
        f.w(0x82, 2, count)
        f.w(0x84, 2, width)
        f.w(0x88, 4, time)

    def notify(self, manager: int, count: int, width: int) -> None:
        with self.frame(self.profile.notify) as f:
            if not self.al(_OWNED, manager):
                return
            mode = self.r(manager + 0x318, 4)
            f.w(0x38, 16, self.r(_SECOND, 16))
            f.w(0x48, 4, 8)
            if not f.contains(0x38, 5, mode):
                return
            clock = self.r(manager + 0x358)
            if self.r(clock + 8, 4) == 2:
                self.packet(f, count, width, 0)
                self.descriptor(f, 0x90)
                self.serialize(f, 0x50, 0x90, f.h(0x80))
                receiver = self.r(manager + 0x2E8)
                length = (f.r(0xA8, 4) - f.r(0xA0, 4)) & _U32
                table = self.r(receiver)
                data = f.r(0xA0, 8)
                self.invoke(self.virtual, self.r(table + 0xE8), receiver, data, length)
                clock = self.r(manager + 0x358)
                self.w(clock + 0x50, 4, self.eax(_HOST))
                self.call(0x1402A8630, f.h(0xA0))
            else:
                time = (self.eax(_CLOCK, clock) + 2) & _U32
                self.packet(f, count, width, time)
                self.call(_DISPATCH, manager, f.h(0x80), 0, 1)
            clock = self.r(manager + 0x358)
            mode = self.r(clock + 8, 4)
            time = self.eax(_CLOCK, clock)
            self.w(manager + 0x418, 4, time + (8 if mode == 2 else 2))

    def dispatch(self, manager: int, record: int, value: int, flag: int) -> None:
        with self.frame(self.profile.dispatch) as f:
            receiver = self.r(manager + 0x2E8)
            token = _raw(self.virtual_call(receiver, 0x28, 1), "dispatch virtual28 RAX")
            self.descriptor(f, 0x68)
            self.serialize(f, 0x38, 0x68, record)
            receiver = self.r(manager + 0x2E8)
            length = (f.r(0x80, 4) - f.r(0x78, 4)) & _U32
            table = self.r(receiver)
            f.w(0x28, 1, flag)
            f.w(0x20, 4, value)
            data = f.r(0x78, 8)
            self.invoke(
                self.send, self.r(table + 0xE0), receiver, token, data, length, f.h(0x20), f.h(0x28)
            )
            self.call(0x1402A8630, f.h(0x78))

    def housekeeping(self, manager: int) -> None:
        with self.frame(self.profile.housekeeping) as f:
            initial = self.eax(_HOST)
            clock = self.r(manager + 0x358)
            if self.r(clock + 8, 4) == 2:
                limit = self.r(clock + 0x54, 4)
                external = self.r(_EXTERNAL)
                distance = (limit - self.r(clock + 0x30, 4)) & _U32
                if distance > self.eax(_METRIC, external, 16):
                    external = self.r(_EXTERNAL)
                    now = self.eax(_HOST)
                    elapsed = (now - self.r(manager + 0x2590, 4)) & _U32
                    if elapsed > self.eax(_METRIC, external, 17):
                        game = self.r(_GAME)
                        f.w(0x28, 4, 0)
                        f.w(0x20, 4, 0)
                        self.invoke(self.popup, 0x140D6C3D0, game, 0x9D, 0, 0, f.h(0x20), f.h(0x28))
                        self.w(manager + 0x2590, 4, self.eax(_HOST))
            else:
                previous = self.r(manager + 0x2594, 4)
                if previous:
                    if ((initial - previous) & _U32) >= 15000:
                        self.w(manager + 0x2598, 4, initial)
                    else:
                        older = self.r(manager + 0x2598, 4)
                        if older and ((initial - older) & _U32) > 45000:
                            self.call(_ROSTER, 0x1442DE060, f.h(0x30))
                            index, row, complete = 0, 0x1442DE068, True
                            if f.r(0x30, 8):
                                while True:
                                    if self.al(_ROW_READY, row) and not self.al(0x140E506E0, row):
                                        receiver = self.r(row + 8)
                                        if (
                                            receiver
                                            and _eax(
                                                self.virtual_call(receiver, 0x18),
                                                "housekeeping virtual18 EAX",
                                            )
                                            != 1
                                        ):
                                            complete = False
                                            break
                                    index = (index + 1) & _U64
                                    row = (row + 0x30) & _U64
                                    if index >= f.r(0x30, 8):
                                        break
                            if complete:
                                self.w(manager + 0x2598, 4, 0)
            self.w(manager + 0x2594, 4, initial)

    def admission_log(self, f: _Frame, format_address: int) -> None:
        logger = self.r(_LOGGER)
        f.w(0x20, 8, 0)
        self.invoke(self.logger, _LOG, logger, 0x1F, format_address, 0, f.h(0x20))

    def admission(self, subject: int) -> int:
        with self.frame(self.profile.admission) as f:
            self.call(0x140E462F0, subject)
            cell = _raw(self.call(0x140E15890, self.r(_SETTINGS)), "admission cell RAX")
            if not self.r(cell) or not self.eax(_MODE, self.r(_SETTINGS)):
                return 0
            f.w(0x30, 4, 8)
            registry = _raw(self.call(0x140AED2D0), "policy registry RAX")
            self.call(0x140AEDA20, registry, 0x143268988, f.h(0x30))
            if f.r(0x30, 4) != 5 and not self.al(0x140E46B80, subject):
                return 0
            registry = _raw(self.call(0x140AED2D0), "second policy registry RAX")
            self.call(0x140AEDA20, registry, 0x143268988, f.h(0x30))
            if f.r(0x30, 4) != 5:
                return 1
            result = self.al(0x140E46E10, subject)
            if result:
                if self.r(subject + 4, 1) and not self.al(0x140E03790, self.r(subject + 8)):
                    if self.r(0x144355057, 1) >= 1:
                        self.admission_log(f, 0x1432689A0)
                    self.w(subject + 4, 1, 0)
                    return 0
                if result == 1 and self.r(0x144355057, 1) >= result:
                    self.admission_log(f, 0x1432689C0)
            self.w(subject + 4, 1, 0)
            return result

    def lookup(self, row: int) -> int | None:
        with self.frame(self.profile.row_lookup) as f:
            cell = _raw(self.call(0x140E15890, self.r(_SETTINGS)), "row lookup cell RAX")
            session = self.r(cell)
            if session:
                f.w(0x38, 8, self.r(row + 0x20))
                return self.call(_RECORD_ALIAS, session, f.h(0x38))
            vector = self.r(self.profile.gs_base + 0x58)
            tls_index = self.r(0x144C9C828, 4)
            thread = self.r(vector + tls_index * 8)
            epoch = self.r(thread + 0x3B4, 4)
            guard = self.r(0x1442DE308, 4)
            if _signed(guard, 4) > _signed(epoch, 4):
                self.call(0x142D6BF80, 0x1442DE308)
                if self.r(0x1442DE308, 4) == _U32:
                    self.call(0x1413E4B20, 0x1442DE1F0)
                    self.call(0x142D6BD04, 0x143094B70)
                    self.call(0x142D6BF14, 0x1442DE308)
            return 0x1442DE1F0

    def row_test(self, row: int, active: bool) -> int:
        seed = self.profile.row_active if active else self.profile.row_ready
        with self.frame(seed) as f:
            record = self.call(_LOOKUP, row)
            f.w(0x20, 4, 2)
            if active:
                f.w(0x24, 4, 4)
            kind = self.r(_raw(record, "row context RAX") + 0xB8, 4)
            return int(f.contains(0x20, 2 if active else 1, kind))

    def roster(self, output: int) -> int:
        cell = _raw(self.call(0x140E15890, self.r(_SETTINGS)), "roster session cell RAX")
        if self.r(cell):
            cell = _raw(self.call(0x140E15890, self.r(_SETTINGS)), "second roster cell RAX")
            self.call(_COUNT, self.r(cell), output)
        else:
            self.w(output, 8, 0)
        return output

    def append(self, queue: int, scratch: int, value: int) -> None:
        self.invoke(self.formatter, 0x1409002E0, scratch, 0x14326A660, value)
        target = self.r(0x14319A2F8)
        self.invoke(self.imports, target, queue + 0x7B8, 0x800, scratch)

    def summary(self, queue: int) -> int:
        self.w(queue + 0x7B8, 1, 0)
        scratch = (queue + 0xFB8) & _U64
        for index in range(1, 9):
            if self.r(0x1442DE070 + (index - 1) * 0x30):
                self.append(queue, scratch, self.r(queue + 0x47C + index * 4, 4))
        for index in range(1, 9):
            if self.al(_ROW_ACTIVE, 0x1442DE068 + (index - 1) * 0x30):
                self.append(queue, scratch, self.r(queue + 0x410 + index * 4, 4))
        self.append(queue, scratch, self.r(queue + 0x3E4, 4))
        self.append(queue, scratch, self.r(queue + 0x3F0, 4))
        return (queue + 0x7B8) & _U64


def bind_replay_cycle_services(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls,
    virtual_calls: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    error_home_calls: ReplayTaskRebuildCalls,
    popup_home_calls: ReplayTaskRebuildCalls,
    send_home_calls: ReplayTaskRebuildCalls,
    format_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayCycleServicesProfile,
) -> ReplayTaskRebuildCalls:
    """Bind22 whole callers with actual state and mandatory reached effects.

    The profile's GS address belongs to supplied owned storage. No host GS,
    initialized TLS, default metrics, packet success or child effect is inferred.
    Native saves/cookies/faults/EH/concurrency/incidental registers excluded.
    Unknown call arguments, payload and returned object pass through unchanged.
    """
    for channel in (
        calls,
        imports,
        virtual_calls,
        logger_home_calls,
        error_home_calls,
        popup_home_calls,
        send_home_calls,
        format_calls,
    ):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayCycleServicesProfile)
        or not isinstance(atomics, ReplayUnitAIMapAtomics)
    ):
        raise ValueError("actual cycle-service local/profile/atomic capabilities required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed cycle service call")
        _validate(context, calls, *args)
        body = _Services(
            context,
            bound,
            imports,
            virtual_calls,
            logger_home_calls,
            error_home_calls,
            popup_home_calls,
            send_home_calls,
            format_calls,
            atomics,
            bind_local,
            profile,
        )
        if target == _METRIC:
            return body.metric(*args)
        if target == _OVERRIDE:
            return body.override(args[0])
        if target == _OWNED:
            return body.owned(args[0])
        if target == _SPECIAL:
            return body.special(args[0])
        if target == _NOTIFY:
            body.notify(*args)
        elif target == _HOUSEKEEP:
            body.housekeeping(args[0])
        elif target == _QUEUE:
            return body.r(args[0] + 0x388)
        elif target == _PRIMARY:
            return body.primary(args[0])
        elif target == _FLAGS:
            return body.flags(args[0])
        elif target == _ADMISSION:
            return body.admission(args[0])
        elif target == _SUMMARY:
            return body.summary(args[0])
        elif target == _LIMIT:
            return body.r(args[0] + 0x54, 4)
        elif target == _CELL:
            return (args[0] + 0x58) & _U64
        elif target == _MODE:
            return body.r(args[0] + 0x318, 4)
        elif target == _ROSTER:
            return body.roster(args[1])
        elif target in (_ROW_READY, _ROW_ACTIVE):
            return body.row_test(args[0], target == _ROW_ACTIVE)
        elif target == _DISPATCH:
            body.dispatch(*args)
        elif target == _COUNT:
            body.w(args[1], 8, body.r(args[0] + 0x1148))
            return args[1]
        elif target in (_RECORD, _RECORD_ALIAS):
            return (args[0] + 0x858 + body.r(args[1]) * 0x118) & _U64
        else:
            return body.lookup(args[0])
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
