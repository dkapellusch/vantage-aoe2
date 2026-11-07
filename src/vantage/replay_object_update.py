"""Addressed build54800 object-list dispatcher141229a20, complete100B/32insns.

Source: base-player-update-source-v1/141229a20.asm.tsv. The existing logical
replay_update helper establishes the traversal; this binding supplies current
addressed storage, raw AL tests and current virtual targets. Object behavior,
removal/list mutation, restored World readiness and scheduling are mandatory
separate effects. Native physical stack, incidental RAX, faults and threads
are outside this effective owned-call interface.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
)
from .replay_unit_ai_base import _validate

_ENTRY = 0x141229A20
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class ReplayObjectUpdateProfile:
    """Explicit update-iteration budget shared through synchronous reentry.

    Native code has no progress/cycle guard. At exhaustion the next reached
    iteration refuses before reading its buffer, after prior effects. Empty
    lists still read their signed count and return without spending work.
    """

    maximum_updates: int

    def __post_init__(self) -> None:
        if type(self.maximum_updates) is not int or self.maximum_updates < 0:
            raise ValueError("explicit nonnegative object-update work limit required")


@dataclass(slots=True)
class _State:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    profile: ReplayObjectUpdateProfile
    updates: int = 0

    def run(self, address: int) -> None:
        # The native entry and loop bottom each read count; no top reread.
        if _signed(_read(self.context, address + 0x10, 4), 4) <= 0:
            return
        index, offset = 0, 0
        while True:
            if self.updates >= self.profile.maximum_updates:
                raise UnresolvedReplayTaskRebuild("object-update work limit exhausted")
            self.updates += 1
            buffer = _read(self.context, address + 8, 8)
            current = _read(self.context, buffer + offset, 8)
            vtable = _read(self.context, current, 8)
            target = _read(self.context, vtable + 0x30, 8)
            result = _call(self.calls, target, (current,), width=8)
            if result & 0xFF:
                vtable = _read(self.context, current, 8)
                target = _read(self.context, vtable + 0x18, 8)
                _call(self.calls, target, (current,))
                index = (index - 1) & _U32
                offset = (offset - 8) & _U64
            index = (index + 1) & _U32
            offset = (offset + 8) & _U64
            count = _signed(_read(self.context, address + 0x10, 4), 4)
            if _signed(index, 4) >= count:
                return


def bind_replay_object_update(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    profile: ReplayObjectUpdateProfile,
) -> ReplayTaskRebuildCalls:
    """Own only141229a20(list); route every current virtual child through calls.

    Actual lower routing must reenter this binding for reached owned entries.
    An unknown target preserves raw arguments/payload/result identity when
    delegated. Known-body calls are void-like: no successful RAX is invented.
    The entry list is held independently of context.subject and every callback.
    No null-list/object skip, list compaction or successful removal is supplied.
    All mutations and child exceptions remain visible in source order.
    """
    _validate(context, calls)
    if not isinstance(profile, ReplayObjectUpdateProfile):
        raise ValueError("explicit object-update work profile required")
    active: _State | None = None

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        nonlocal active
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 1 or data is not None:
            raise ValueError("malformed addressed object-update call")
        _validate(context, calls, *args)
        outer = active is None
        if outer:
            active = _State(context, calls, profile)
        state = active
        assert state is not None
        try:
            state.run(args[0])
        finally:
            if outer:
                active = None
        return None

    return ReplayTaskRebuildCalls(dispatch)
