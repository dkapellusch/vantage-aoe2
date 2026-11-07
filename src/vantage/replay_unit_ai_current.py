"""Build54800 AI2 current timer leaves and the opaque Unit+80c word getter.

Source: initial-ai2-current-virtual-source-v1, complete17/7/9-byte bodies.
Current scalar backing and reached setter effects are required. These logical
APIs do not expose incidental RAX, a numerical float, native CPU flags/faults,
or an inferred current object/vtable/field value.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _write,
)
from .replay_unit_ai_base import _validate

_U32 = (1 << 32) - 1


def set_replay_unit_ai_timeout(
    context: ReplayTaskRebuildStorage,
    address: int,
    value: int,
) -> None:
    """Full7B140d19dc0: store lowEDX at current AI+16c, without other accesses.

    value is raw incoming RDX; its upper32 bits are discarded. Native RAX
    passes through this leaf and is outside this effect-only return contract.
    """
    _validate(context, ReplayTaskRebuildCalls(None), address, value)
    _write(context, address + 0x16C, 4, value)


def update_replay_unit_ai2_timeout(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full17B140cf3300: current170, u32 product then shift, mandatory setter tail.

    The current DWORD is captured before the required140d19dc0 call. A missing
    binding refuses after that read; no inline store or RNG fallback is used.
    The setter and updater's incidental native RAX are not logical results.
    """
    _validate(context, calls, address)
    current = _read(context, address + 0x170, 4)
    scaled = ((current * 5) & _U32) >> 2
    _call(calls, 0x140D19DC0, (address, scaled))


def read_replay_unit_word80c(
    context: ReplayTaskRebuildStorage,
    subject: int,
) -> int:
    """Full9B1412b6240: current DWORD80c as the raw low-XMM0 word.

    All32 bits, including signed zero and NaN payloads, are preserved. This
    integer transports XMM bits; it is not a native RAX or numeric-float result.
    """
    _validate(context, ReplayTaskRebuildCalls(None), subject)
    return _read(context, subject + 0x80C, 4)


def bind_replay_unit_ai_current(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind the three complete leaves, delegating unknown actual targets.

    The timer wrapper forwards rawRDX to3300; this override consumes onlyRCX.
    Its binder accepts that two-register shape or the one consumed argument,
    validates optional RDX and replaces it with the computed setter input.
    """
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140CF3300: (1, 2), 0x140D19DC0: (2,), 0x1412B6240: (1,)}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) not in arities[target] or data is not None:
            raise ValueError("malformed UnitAI current call")
        _validate(context, calls, *args)
        if target == 0x140CF3300:
            update_replay_unit_ai2_timeout(context, args[0], calls=bound)
        elif target == 0x140D19DC0:
            set_replay_unit_ai_timeout(context, *args)
        else:
            return read_replay_unit_word80c(context, *args)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
