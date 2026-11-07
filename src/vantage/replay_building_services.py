"""Five complete build54800 queue, construction and object lookup services.

Source: building-update-services-source-v1, small API fixed before this port;
553 instruction bytes / 152 rows. All reached effects require capabilities.
No recording World, physical native stack or complete game tick is supplied.
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

_RUN, _THRESHOLD, _STAGE, _RESET, _LOOKUP = (
    0x140BB83E0,
    0x140BB9290,
    0x141286D70,
    0x1412BAED0,
    0x141617DB0,
)
_ARITIES = {_RUN: 1, _THRESHOLD: 2, _STAGE: 2, _RESET: 1, _LOOKUP: 2}
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class ReplayBuildingServicesProfile:
    """Eight explicit bytes; stage source RSP40 maps to logical offset0.

    Only the stage's mode4 path reaches this protected QWORD. The binding is
    lazy and remains live through the final required effect. Saves, physical
    stack identity and unobserved register/return bits are outside this view.
    """

    stage: bytes

    def __post_init__(self) -> None:
        if type(self.stage) is not bytes or len(self.stage) != 8:
            raise ValueError("explicit8-byte stage seed required")


def _raw(value: int | None, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual rawu64 annotation")
    _unsigned(value, 8, label)
    return value


def _count12(begin: int, end: int) -> int:
    span = _signed((end - begin) & _U64, 8)
    half = ((span * 0x2AAAAAAAAAAAAAAB) >> 64) >> 1
    return (half + ((half & _U64) >> 63)) & _U64


class _Services:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        virtual: ReplayTaskRebuildCalls,
        imports: ReplayTaskRebuildCalls,
        bind_local: LocalBinding,
        profile: ReplayBuildingServicesProfile,
    ) -> None:
        self.context, self.calls = context, calls
        self.virtual, self.imports = virtual, imports
        self.bind_local, self.profile = bind_local, profile

    def r(self, at: int, width: int = 8) -> int:
        return _read(self.context, at, width)

    def w(self, at: int, width: int, value: int) -> None:
        _write(self.context, at, width, value)

    def invoke(self, calls: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, tuple(value & _U64 for value in args), None)

    def run_queue(self, queue: int) -> int:
        node = self.r(queue + 0x10)
        kept, previous = 0, 0
        while node:
            action = self.r(node)
            result = self.invoke(self.virtual, self.r(self.r(action) + 0x30), action)
            status = _raw(result, "production action AL") & 255
            if ((status - 1) & 255) & 0xFD:
                previous = node
                kept = (kept + 1) & _U32
                node = self.r(node + 8)
            else:
                following = self.r(node + 8)
                self.w(previous + 8 if previous else queue + 0x10, 8, following)
                action = self.r(node)
                if action:
                    self.invoke(self.virtual, self.r(self.r(action)), action, 1)
                self.invoke(self.imports, self.r(0x143199DD0), node)
                node = following
        return kept

    def threshold(self, master: int, index: int) -> int:
        begin = self.r(master + 0x338)
        end = self.r(master + 0x340)
        if index >= _count12(begin, end):
            return 0
        return self.r(begin + index * 12 + 2, 2)

    def stage(self, obj: int, incoming: int) -> None:
        selected = incoming & 255
        game = self.r(0x144353698)
        mode = _raw(self.invoke(self.calls, 0x140D6A940, game), "Game mode EAX") & _U32
        with _Frame(self.context, self.bind_local, self.profile.stage) as f:
            if mode == 4:
                f.w(0, 8, self.r(obj + 0x10))
                f.w(0, 8, f.r(0, 8) - 0x6A586EB28AC201FC)
                f.w(0, 8, f.r(0, 8) - 0x0CF19788B2554E70)
                master = f.r(0, 8)
                f.w(0, 8, self.r(master + 0x18))
                f.w(0, 8, f.r(0, 8) ^ 0x349E37847AD69F19)
                f.w(0, 8, f.r(0, 8) - 0x47E37DFF0616CE4F)
                if f.r(0, 8) & 0xFFFF not in (0x32, 0x4A3):
                    return
            if selected == 0x1B:
                marker = self.r(obj + 0x138)
                if marker:
                    replacement = self.r(marker + 0xA, 1)
                    if replacement != 255:
                        selected = replacement
                        self.w(marker + 0xA, 1, 255)
            self.invoke(self.calls, 0x141296BF0, obj, selected)

    def lookup(self, world: int, raw_id: int) -> int:
        identifier = _signed(raw_id & _U32, 4)
        if identifier < 0:
            if identifier == -(1 << 31):
                return 0
            index = (-identifier) & _U32
            if _signed(index, 4) < _signed(self.r(world + 0x184, 4), 4):
                table = self.r(world + 0x178)
                return self.r(table + index * 8)
        if identifier <= -1 or identifier >= _signed(self.r(world + 0x174, 4), 4):
            return 0
        table = self.r(world + 0x168)
        return self.r(table + identifier * 8) if table else 0


def bind_replay_building_services(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    virtual_calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayBuildingServicesProfile,
) -> ReplayTaskRebuildCalls:
    """Bind the five complete source bodies with current storage and effects.

    Calls use the frozen small-service API's known GP inputs. Stage is semantic
    void; other results expose defined EAX/RAX values. Unknown call arguments,
    payloads and returned identities pass through without extra interpretation.
    """
    for channel in (calls, virtual_calls, imports):
        _validate(context, channel)
    if not callable(bind_local) or not isinstance(profile, ReplayBuildingServicesProfile):
        raise ValueError("actual locals/profile required for Building services")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed Building service call")
        _validate(context, calls, *args)
        state = _Services(context, calls, virtual_calls, imports, bind_local, profile)
        if target == _RUN:
            return state.run_queue(args[0])
        if target == _THRESHOLD:
            return state.threshold(args[0], args[1])
        if target == _STAGE:
            state.stage(args[0], args[1])
            return None
        if target == _RESET:
            state.w(args[0] + 0x66C, 4, 0)
            return 0
        return state.lookup(args[0], args[1])

    return ReplayTaskRebuildCalls(dispatch)
