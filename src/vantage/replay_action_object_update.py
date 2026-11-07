"""Ten whole build54800 Action/controller/worker/notification bodies.

Source/API: action-object-update-source-v1,3039 bytes/726 assembly rows.
Existing Moving/Base and clock bodies remain delegated. Actual action methods,
lookup, nested cleanup, notification, current free imports and logs are required.
This does not restore a World or commit a recording tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    divide_binary32,
    multiply_binary32,
    signed32_binary32,
    unsigned64_binary32,
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

_ACTION, _CLEAR, _CANCEL, _POP, _QUERY = (
    0x1411399A0,
    0x140B88A20,
    0x140B88B90,
    0x140B893D0,
    0x140B899F0,
)
_WORKER, _NOTIFY, _PAUSE, _ABORT, _CLEANUP = (
    0x141140430,
    0x141226E30,
    0x140B68080,
    0x140B68090,
    0x140B680B0,
)
_TARGETS = {_ACTION, _CLEAR, _CANCEL, _POP, _QUERY, _WORKER, _NOTIFY, _PAUSE, _ABORT, _CLEANUP}
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MASTER_A, _MASTER_B = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_A, _B, _C, _D = (0x6AE24D3352F04511, 0xC22D6B496D833977, 0x042AC42976FCCEF5, 0xA9834B738A7DD167)
_CLOCK, _LOGGER, _DEBUG = 0x1416041F0, 0x144355068, 0x14435505B


@dataclass(frozen=True, slots=True)
class ReplayActionObjectUpdateProfile:
    """Explicit90/48/38h views; cookies and physical stack identity excluded.

    Worker HOME30 lies in physical caller shadow space. The logical38-byte
    view preserves its semantic offset, without native stack adjacency.
    """

    action: bytes
    query: bytes
    worker: bytes

    def __post_init__(self) -> None:
        for value, size in ((self.action, 0x90), (self.query, 0x48), (self.worker, 0x38)):
            if type(value) is not bytes or len(value) != size:
                raise ValueError("explicit90/48/38-hex-byte Action update seeds required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


class _Action:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        virtual: ReplayTaskRebuildCalls,
        imports: ReplayTaskRebuildCalls,
        logger: ReplayTaskRebuildCalls,
        fp: ReplayTaskRebuildCalls,
        bind_local: LocalBinding,
        profile: ReplayActionObjectUpdateProfile,
    ) -> None:
        self.context, self.calls, self.virtual = context, calls, virtual
        self.imports, self.logger, self.fp = imports, logger, fp
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

    def eax(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} EAX") & _U32

    def al(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} AL") & 255

    def virtual_call(self, obj: int, slot: int, *args: int) -> int | None:
        return self.invoke(self.virtual, self.r(self.r(obj) + slot), obj, *args)

    def frame(self, seed: bytes) -> _Frame:
        return _Frame(self.context, self.bind_local, seed)

    def master_value(self, f: _Frame, encoded: int) -> int:
        f.w(0x60, 8, encoded)
        f.w(0x60, 8, f.r(0x60, 8) - _MASTER_A)
        f.w(0x60, 8, f.r(0x60, 8) - _MASTER_B)
        return f.r(0x60, 8)

    def master(self, f: _Frame, obj: int) -> int:
        return self.master_value(f, self.r(obj + 0x10))

    def decode(self, f: _Frame, home: int, encoded: int) -> None:
        f.w(home, 8, encoded)
        f.w(home, 8, f.r(home, 8) ^ _A)
        f.w(home, 8, f.r(home, 8) ^ _B)
        f.w(home, 8, f.r(home, 8) - _C)
        f.w(home, 8, f.r(home, 8) ^ _D)
        held = f.r(home, 8)
        f.w(home, 8, held)

    def encode(self, f: _Frame) -> int:
        held = f.r(0x30, 8)
        f.w(0x30, 8, held)
        f.w(0x30, 8, f.r(0x30, 8) ^ _D)
        f.w(0x30, 8, f.r(0x30, 8) + _C)
        f.w(0x30, 8, f.r(0x30, 8) ^ _B)
        f.w(0x30, 8, f.r(0x30, 8) ^ _A)
        return f.r(0x30, 8)

    def log_zero(self, f: _Frame, format_address: int, level: int) -> None:
        logger = self.r(_LOGGER)
        f.w(0x20, 8, 0)
        self.invoke(self.logger, 0x14101ADB0, logger, level, format_address, 0, f.h(0x20))

    def initial(self, f: _Frame, obj: int) -> None:
        name = self.call(0x140A4B870, self.master(f, obj))
        owner = self.r(obj + 0x18)
        name = self.r(_raw(name, "Action name cell RAX"))
        time = self.call(_CLOCK, self.r(owner + 8))
        if self.r(_DEBUG, 1) < 1:
            return
        timer = self.r(obj + 0x168, 4)
        logger = self.r(_LOGGER)
        f.w(0x40, 4, _raw(time, "Action diagnostic clock EAX") & _U32)
        state = self.r(obj + 0x188, 1)
        f.w(0x60, 1, state)
        for home, target in ((0x70, 0x60), (0x78, 0x40), (0x80, 0x50), (0x88, 0x30)):
            f.w(home, 8, f.h(target))
        f.w(0x20, 8, f.h(0x70))
        f.w(0x50, 4, timer)
        f.w(0x38, 4, 15)
        f.w(0x30, 8, name)
        f.w(0x58, 4, 10)
        f.w(0x48, 4, 7)
        f.w(0x68, 4, 5)
        self.invoke(self.logger, 0x14101ADB0, logger, 0x23, 0x1432A6290, 4, f.h(0x20))

    def actions(self, f: _Frame, obj: int, encoded_master: int) -> None:
        master = self.master_value(f, encoded_master)
        f.w(0x60, 8, self.r(master + 0x18))
        f.w(0x60, 8, f.r(0x60, 8) ^ 0x349E37847AD69F19)
        f.w(0x60, 8, f.r(0x60, 8) - 0x47E37DFF0616CE4F)
        threshold = 5 if f.r(0x60, 8) & 0xFFFF == 0x114 else 2
        if self.r(obj + 0x188, 1) > threshold:
            debug = self.r(_DEBUG, 1)
            if debug >= 1:
                self.log_zero(f, 0x1432A62E8, 0x23)
                debug = self.r(_DEBUG, 1)
            if not self.r(self.r(obj + 0x420) + 0x10):
                return
            if debug >= 1:
                self.log_zero(f, 0x1432A6300, 0x23)
            self.call(_CLEAR, self.r(obj + 0x420))
            return
        head = self.r(self.r(obj + 0x420) + 0x10)
        debug = self.r(_DEBUG, 1)
        if not head:
            if debug >= 1:
                self.log_zero(f, 0x1432A6318, 0x23)
                debug = self.r(_DEBUG, 1)
            if self.r(obj + 0x188, 1) != 2:
                return
            if debug >= 1:
                self.log_zero(f, 0x1432A6330, 0x23)
            task = self.r(self.master(f, obj) + 0x230, 2)
            if task == 0xFFFF:
                return
            if self.r(_DEBUG, 1) >= 1:
                self.log_zero(f, 0x1432A6350, 0x23)
            self.virtual_call(obj, 0x8A8, task)
            return
        if debug >= 1:
            self.log_zero(f, 0x1432A6370, 0x23)
            debug = self.r(_DEBUG, 1)
        if self.r(obj + 0x148):
            if debug >= 1:
                self.log_zero(f, 0x1432A6390, 0x23)
            self.call(_CANCEL, self.r(obj + 0x420))
            return
        if debug >= 1:
            self.log_zero(f, 0x1432A63B0, 0x23)
        result = self.al(_QUERY, self.r(obj + 0x420))
        debug = self.r(_DEBUG, 1)
        if debug >= 1:
            logger = self.r(_LOGGER)
            f.w(0x60, 8, f.h(0x30))
            f.w(0x38, 4, 5)
            f.w(0x20, 8, f.h(0x60))
            f.w(0x30, 1, result)
            self.invoke(self.logger, 0x14101ADB0, logger, 0x23, 0x1432A63C8, 1, f.h(0x20))
            debug = self.r(_DEBUG, 1)
        if not ((result - 1) & 255) & 0xFD:
            if debug >= 1:
                self.log_zero(f, 0x1432A63E0, 0x23)
            self.call(_POP, self.r(obj + 0x420))

    def work_state(self, f: _Frame, obj: int) -> None:
        master = self.master(f, obj)
        f.w(0x60, 8, self.r(master + 0x38))
        f.w(0x60, 8, f.r(0x60, 8) - 0x50A06BCECEBEF905)
        f.w(0x60, 8, f.r(0x60, 8) + 0x5B32AA7995D95916)
        if f.r(0x60, 8) & 0xFFFF != 4:
            return
        active = _raw(self.virtual_call(obj, 0x2E8, 1), "worker virtual2e8 AL") & 255
        if active and self.r(obj + 0x188, 1) == 2:
            if not self.r(obj + 0x438, 4):
                owner = self.r(obj + 0x18)
                self.w(obj + 0x440, 4, self.r(obj + 0x440, 4) + 1)
                self.w(obj + 0x438, 4, self.eax(_CLOCK, self.r(owner + 8)))
        else:
            previous = self.r(obj + 0x438, 4)
            if previous:
                now = self.eax(_CLOCK, self.r(self.r(obj + 0x18) + 8))
                elapsed = (now - previous) & _U32
                self.w(obj + 0x438, 4, 0)
                self.w(obj + 0x43C, 4, self.r(obj + 0x43C, 4) + elapsed)
        if self.r(obj + 0x188, 1) > 2 and self.r(obj + 0x43C, 4) > 0:
            self.call(_WORKER, obj)

    def target(self, f: _Frame, obj: int) -> None:
        owner = self.r(obj + 0x18)
        target_id = self.r(obj + 0x430, 4)
        target = self.call(0x141617DB0, self.r(owner + 8), target_id)
        resource = self.r(self.r(obj + 0x18) + 0x98)
        self.decode(f, 0x60, self.r(resource + 0x800))
        target = _raw(target, "Action target RAX")
        if target:
            distance = self.invoke(self.fp, 0x14124E840, obj, target)
            if distance is None:
                raise ValueError("Action distance requires actual low-XMM0 binary32")
            _unsigned(distance, 4, "Action distance low-XMM0")
            limit = f.r(0x60, 4)
            comparison = compare_binary32(distance, multiply_binary32(limit, limit))
            if comparison is None or comparison < 0:
                return
        self.w(obj + 0x430, 4, _U32)
        self.w(obj + 0x434, 4, 0)

    def action(self, obj: int) -> int:
        with self.frame(self.profile.action) as f:
            self.initial(f, obj)
            self.w(obj + 0x42A, 2, 0)
            value = self.call(0x14120E560, obj)
            encoded_master = self.r(obj + 0x10)
            result = _raw(value, "Moving update AL") & 255
            self.actions(f, obj, encoded_master)
            self.work_state(f, obj)
            self.target(f, obj)
            self.call(_NOTIFY, obj)
            return result

    def remove(self, stack: int, node: int) -> None:
        self.w(stack + 0x10, 8, self.r(node + 8))
        action = self.r(node)
        if action:
            self.virtual_call(action, 0, 1)
        self.invoke(self.imports, self.r(0x143199DD0), node)
        head = self.r(stack + 0x10)
        if head and self.r(self.r(stack + 8) + 0x188, 1) < 3:
            self.virtual_call(self.r(head), 0x28, 0)

    def clear(self, stack: int) -> None:
        node = self.r(stack + 0x10)
        while node:
            self.remove(stack, node)
            node = self.r(stack + 0x10)

    def pop(self, stack: int) -> None:
        node = self.r(stack + 0x10)
        if node:
            self.remove(stack, node)

    def cancel(self, stack: int) -> int:
        head = self.r(stack + 0x10)
        if not head:
            return 1
        result = self.al(_ABORT, self.r(head))
        node = self.r(self.r(stack + 0x10) + 8)
        while node:
            self.call(_PAUSE, self.r(node))
            node = self.r(node + 8)
        if result == 1:
            node = self.r(stack + 0x10)
            if node:
                self.remove(stack, node)
        return result

    def query(self, stack: int) -> int:
        with self.frame(self.profile.query) as f:
            debug = self.r(0x144355056, 1)
            if debug >= 1:
                self.log_zero(f, 0x1432269A8, 0x1E)
                debug = self.r(0x144355056, 1)
            head = self.r(stack + 0x10)
            if not head:
                if debug >= 1:
                    self.log_zero(f, 0x1432269C0, 0x1E)
                return 1
            value = self.virtual_call(self.r(head), 0x30)
            debug = self.r(0x144355056, 1)
            result = _raw(value, "action virtual30 AL") & 255
            if debug >= 1:
                logger = self.r(_LOGGER)
                f.w(0x30, 1, result)
                f.w(0x38, 4, 5)
                f.w(0x40, 8, f.h(0x30))
                f.w(0x20, 8, f.h(0x40))
                self.invoke(self.logger, 0x14101ADB0, logger, 0x1E, 0x1432269D8, 1, f.h(0x20))
                debug = self.r(0x144355056, 1)
            head = self.r(stack + 0x10)
            if not head:
                if debug >= 1:
                    self.log_zero(f, 0x1432269F8, 0x1E)
                return result
            node = self.r(head + 8)
            while node:
                if debug >= 1:
                    self.log_zero(f, 0x143226A08, 0x1E)
                self.call(_PAUSE, self.r(node))
                node = self.r(node + 8)
                debug = self.r(0x144355056, 1)
            if debug >= 1:
                self.log_zero(f, 0x143226A20, 0x1E)
            return result

    def cleanup(self, action: int) -> int | None:
        target = self.r(action + 0x20)
        if target and self.r(target + 0x188, 1) >= 7:
            self.virtual_call(action, 0x68, 0)
        target = self.r(action + 0x28)
        if target and self.r(target + 0x188, 1) >= 7:
            obj = self.r(action + 0x10)
            target_id = self.r(action + 0x34, 4)
            world = self.r(self.r(obj + 0x18) + 8)
            found = _raw(self.call(0x141617DB0, world, target_id), "cleanup target RAX")
            if found:
                table = self.r(found)
                kind = self.r(action + 8, 2)
                obj = self.r(action + 0x10)
                self.invoke(self.virtual, self.r(table + 0x190), found, obj, kind)
            if self.r(action + 0x28):
                self.w(action + 0x28, 8, 0)
                self.w(action + 0x34, 4, _U32)
        stack = self.r(action + 0x50)
        if stack and self.r(stack + 0x10):
            return self.call(0x140B890D0, stack)
        return None

    def worker(self, obj: int) -> int:
        with self.frame(self.profile.worker) as f:
            previous = self.r(obj + 0x438, 4)
            if previous:
                now = self.eax(_CLOCK, self.r(self.r(obj + 0x18) + 8))
                owner = self.r(obj + 0x18)
                self.w(obj + 0x43C, 4, self.r(obj + 0x43C, 4) + now - previous)
                self.w(obj + 0x438, 4, self.eax(_CLOCK, self.r(owner + 8)))
            owner = self.r(obj + 0x18)
            if owner:
                elapsed = self.r(obj + 0x43C, 4)
                resource = self.r(owner + 0x98)
                value = unsigned64_binary32(elapsed)
                f.w(0x30, 8, self.r(resource + 0x7D0))
                f.w(0x30, 8, f.r(0x30, 8) ^ _A)
                f.w(0x30, 8, f.r(0x30, 8) ^ _B)
                held = f.r(0x30, 8)
                value = divide_binary32(value, self.r(0x1436A02F8, 4))
                f.w(0x30, 8, held - _C)
                f.w(0x30, 8, f.r(0x30, 8) ^ _D)
                held = f.r(0x30, 8)
                f.w(0x30, 8, held)
                f.w(0x30, 4, add_binary32(value, f.r(0x30, 4)))
                self.w(resource + 0x7D0, 8, self.encode(f))
                owner = self.r(obj + 0x18)
                value = signed32_binary32(_signed(self.r(obj + 0x440, 4), 4))
                resource = self.r(owner + 0x98)
                self.decode(f, 0x30, self.r(resource + 0x7C8))
                f.w(0x30, 4, add_binary32(value, f.r(0x30, 4)))
                self.w(resource + 0x7C8, 8, self.encode(f))
            self.w(obj + 0x43C, 8, 0)
            return 0

    def notify(self, obj: int) -> int | None:
        result = self.virtual_call(obj, 0x610)
        game = self.r(0x144353698)
        flag = 0x10 if _raw(result, "notification virtual610 EAX") & _U32 == 1 else 0
        self.call(0x140D6A880, game)
        return self.call(0x141121110, self.r(0x1443563C0), obj, flag)


def bind_replay_action_object_update(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    virtual_calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    logger_home_calls: ReplayTaskRebuildCalls,
    scalar_fp_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayActionObjectUpdateProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind ten complete callers with reached effects and exact raw FP words.

    Native stack/cookies/faults/EH/concurrency,FP status and upper lanes excluded.
    No default free,action method,clock,lookup,notification or success is inferred.
    Unknown arguments,payload and returned identity pass through unchanged.
    """
    for channel in (calls, virtual_calls, imports, logger_home_calls, scalar_fp_calls):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayActionObjectUpdateProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual locals/profile and exact MXCSR1f80 Action update required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _TARGETS:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 1 or data is not None:
            raise ValueError("malformed addressed Action update call")
        _validate(context, calls, *args)
        body = _Action(
            context,
            bound,
            virtual_calls,
            imports,
            logger_home_calls,
            scalar_fp_calls,
            bind_local,
            profile,
        )
        obj = args[0]
        if target == _ACTION:
            return body.action(obj)
        if target == _CLEAR:
            body.clear(obj)
        elif target == _POP:
            body.pop(obj)
        elif target == _CANCEL:
            return body.cancel(obj)
        elif target == _QUERY:
            return body.query(obj)
        elif target in (_PAUSE, _ABORT):
            body.call(_CLEANUP, obj)
            return 1
        elif target == _CLEANUP:
            return body.cleanup(obj)
        elif target == _WORKER:
            return body.worker(obj)
        else:
            return body.notify(obj)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
