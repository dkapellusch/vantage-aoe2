"""Build54800 civilization selector, registry traversals and comparator835B.

These five complete bodies use explicit current scalar backing and mandatory
actual effects. They do not populate registries, infer default context identity
or bypass the current memcmp import. The effective logical API models consumed
u32/AL results, not incidental volatile registers, physical homes/cookies/faults,
C++ exception machinery or concurrency. Prior reached effects survive refusal.
"""

from __future__ import annotations

from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)
from vantage.replay_unit_ai_base import _validate

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1


def read_replay_civilization_descriptor(
    context: ReplayTaskRebuildStorage,
    output: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Whole40B140fa3420; hold global once and preserve partial home padding."""
    _validate(context, calls, output)
    current = _read(context, 0x144353698, 8)
    if current:
        value = _read(context, current + 0x680, 8)
        _write(context, output, 8, value)
    else:
        _write(context, output, 4, 2)
        _write(context, output + 4, 1, 0)
    return output


def select_replay_civilization_family(
    context: ReplayTaskRebuildStorage,
    descriptor: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Whole46B140fa36a0; current tag first, conditional current DWORD load.

    Invalid tag reaches the actual fatal child with no consumed logical scalar
    operands; incidental incoming volatile registers are not an effective ABI.
    If that child returns, the independently verified adjacentCC terminates.
    """
    _validate(context, calls, descriptor)
    tag = _read(context, descriptor + 4, 1)
    if tag == 0:
        return _read(context, descriptor, 4)
    if tag == 1:
        return 2 if _read(context, descriptor, 4) == 3 else 0
    _call(calls, 0x1408F56B0, ())
    raise UnresolvedReplayTaskRebuild("returned fatal1408f56b0 reaches CC140fa36ce")


def less_replay_civilization_names(
    context: ReplayTaskRebuildStorage,
    left: int,
    right: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Whole98B140a162a0; asymmetric empty gates and held unsigned lengths.

    Read right length before left; for two nonempty values read current right
    pointer before current left pointer. Actual142d6e3bd remains mandatory and
    must itself route its current IAT; only raw signed EAX sign/zero is consumed.
    """
    _validate(context, calls, left, right)
    right_length = _read(context, right + 8, 8)
    if not right_length:
        return 0
    left_length = _read(context, left + 8, 8)
    if not left_length:
        return 1
    right_pointer = _read(context, right, 8)
    left_pointer = _read(context, left, 8)
    result = _call(
        calls, 0x142D6E3BD, (left_pointer, right_pointer, min(left_length, right_length)), width=4
    )
    if result & 0x80000000:
        return 1
    if result:
        return 0
    return int(left_length < right_length)


def find_replay_civilization_name(
    context: ReplayTaskRebuildStorage,
    name: int,
    selector: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Whole254B140f6a690; two actual searches with a current header reload.

    selector is the consumed raw EDX, with no source context/class inference.
    The first equivalent candidate triggers a fresh second search. Each actual
    comparator can mutate backing; the second candidate value is read only
    after its final reverse comparison. Missing second key calls the real
    fatal child, followed by the verified adjacentCC if it returns.
    """
    _validate(context, calls, name)
    _unsigned(selector, 4, "civilization selector")
    header = 0x1442E9720 if selector == 2 else 0x1442E9730

    def lower_bound() -> int:
        candidate = _read(context, header, 8)
        node = _read(context, candidate + 8, 8)
        while _read(context, node + 0x19, 1) == 0:
            less = _call(calls, 0x140A162A0, ((node + 0x20) & _U64, name), width=1)
            if not less:
                candidate = node
            node = _read(context, node + (0x10 if less else 0), 8)
        return candidate

    candidate = lower_bound()
    if _read(context, candidate + 0x19, 1):
        return 0
    if _call(calls, 0x140A162A0, (name, (candidate + 0x20) & _U64), width=1):
        return 0
    candidate = lower_bound()
    if not _read(context, candidate + 0x19, 1) and not _call(
        calls,
        0x140A162A0,
        (name, (candidate + 0x20) & _U64),
        width=1,
    ):
        return _read(context, candidate + 0x38, 4)
    _call(calls, 0x142D6AA55, (0x1436802B0,))
    raise UnresolvedReplayTaskRebuild("returned fatal142d6aa55 reaches CC140f6a78e")


def find_replay_civilization_resource(
    context: ReplayTaskRebuildStorage,
    index: int,
    selector: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Whole397B140f6a320; wrapped signed-DWORD routing and predecessor scan.

    Hold the initial current root. The two source families perform the same
    ordered storage operations with distinct roots/sentinels/ancestor headers.
    Compare equality of duplicate keys without subtraction on the predecessor
    walk. The returned record is the last matching held node minus1b0; no
    record construction, initialized registry or successful empty default is
    inferred. Invalid/unknown backing fails at its first reached access.
    """
    _validate(context, calls)
    _unsigned(index, 4, "civilization numeric ID")
    _unsigned(selector, 4, "civilization selector")
    header = 0x143DB06C0 if selector == 1 else 0x143DB0680
    sentinel = header + 0x20
    node = _read(context, header + 8, 8)
    if node == sentinel:
        return 0
    difference = (_read(context, node - 0x19C, 4) - index) & _U32
    while difference:
        node = _read(context, node + (0x10 if difference & 0x80000000 else 8), 8)
        if node == sentinel:
            return 0
        difference = (_read(context, node - 0x19C, 4) - index) & _U32
    while True:
        predecessor = _read(context, node + 8, 8)
        if predecessor != sentinel:
            following = _read(context, predecessor + 0x10, 8)
            while following != sentinel:
                predecessor = following
                following = _read(context, predecessor + 0x10, 8)
        else:
            predecessor = _read(context, node + 0x18, 8)
            if node == _read(context, predecessor + 8, 8):
                while True:
                    if predecessor == header:
                        return (node - 0x1B0) & _U64
                    child = predecessor
                    predecessor = _read(context, predecessor + 0x18, 8)
                    if child != _read(context, predecessor + 8, 8):
                        break
        if predecessor == sentinel or _read(context, predecessor - 0x19C, 4) != index:
            return (node - 0x1B0) & _U64
        node = predecessor


def bind_replay_civilization_providers(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Own exactly five bodies; actual memcmp/fatal/runtime effects delegate."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140FA3420: 1, 0x140FA36A0: 1, 0x140F6A690: 2, 0x140F6A320: 2, 0x140A162A0: 2}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed civilization provider call")
        if target == 0x140FA3420:
            return read_replay_civilization_descriptor(context, *args, calls=bound)
        if target == 0x140FA36A0:
            return select_replay_civilization_family(context, *args, calls=bound)
        if target == 0x140F6A690:
            return find_replay_civilization_name(context, *args, calls=bound)
        if target == 0x140F6A320:
            return find_replay_civilization_resource(context, *args, calls=bound)
        return less_replay_civilization_names(context, *args, calls=bound)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
