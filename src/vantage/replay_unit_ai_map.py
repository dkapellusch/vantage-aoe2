"""Build54800 UnitAI map cache/acquisition, coordinate query and shared releases.

Source: tc-unit-ai15-map-acquisition-source-v1, normal-leaves-source-v1 and
world-tile-map-preservation-source-v1. Reached map construction/virtual effects
and engine atomic operations are mandatory. Cookie/EH/native stack identity,
concurrent memory and native fault equivalence are outside this interface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _cvtt,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _coordinate, _validate
from .replay_unit_ai_construction import _local

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_MASTER_ADD = 0x6A586EB28AC201FC + 0xCF19788B2554E70


@dataclass(frozen=True, slots=True)
class ReplayUnitAIMapAtomics:
    """Explicit engine DWORD CMPXCHG/XADD, each returning its prior word.

    These callbacks are indivisible in the sequential engine. Missing bindings
    refuse when reached; there is no non-atomic scalar fallback. Native thread
    ordering/alignment/faults are not inferred from the Python implementation.
    """

    compare_exchange: Callable[[int, int, int], int] | None
    fetch_add: Callable[[int, int], int] | None

    def __post_init__(self) -> None:
        if any(
            value is not None and not callable(value)
            for value in (self.compare_exchange, self.fetch_add)
        ):
            raise ValueError("actual atomic effect callbacks or unavailable bindings required")


def _atomic(
    atomics: ReplayUnitAIMapAtomics,
    address: int,
    value: int,
    desired: int | None = None,
) -> int:
    if desired is None:
        if atomics.fetch_add is None:
            raise UnresolvedReplayTaskRebuild("UnitAI shared count atomic effect unavailable")
        previous = atomics.fetch_add(address & _U64, value & _U32)
    else:
        if atomics.compare_exchange is None:
            raise UnresolvedReplayTaskRebuild("UnitAI shared count atomic effect unavailable")
        previous = atomics.compare_exchange(address & _U64, value & _U32, desired & _U32)
    _unsigned(previous, 4, "atomic prior word")
    return previous


def _release(
    context: ReplayTaskRebuildStorage,
    control: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    *,
    weak_only: bool = False,
) -> None:
    if not weak_only:
        if _atomic(atomics, control + 8, _U32) != 1:
            return
        _call(calls, _read(context, _read(context, control, 8), 8), (control,))
    if _atomic(atomics, control + 12, _U32) == 1:
        _call(calls, _read(context, _read(context, control, 8) + 8, 8), (control,))


def acquire_replay_unit_ai_map(
    context: ReplayTaskRebuildStorage,
    subject: int,
    output: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Full509B141251f70, excluding cookie protection and native EH.

    A live cached object transfers its acquired strong hold to the output.
    Misses require the actual World descriptor and map acquisition effects.
    The24B temporary uses explicit initial scratch, not an inferred zero seed;
    it remains live through all releases. Current/held control identities and
    reloads follow the assembly, including null-object/nonzero-control aliases.
    """
    _validate(context, calls, subject, output)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual shared count and local bindings required")
    if type(scratch) is not bytes or len(scratch) != 24:
        raise ValueError("explicit24-byte map temporary scratch required")
    old_hold = 0
    cached_object = 0
    cached_control = _read(context, subject + 0x1E0, 8)
    if cached_control:
        expected = _read(context, cached_control + 8, 4)
        while expected:
            prior = _atomic(atomics, cached_control + 8, expected, expected + 1)
            if prior == expected:
                cached_object = _read(context, subject + 0x1D8, 8)
                old_hold = _read(context, subject + 0x1E0, 8)
                break
            expected = prior
    if cached_object:
        _write(context, output, 8, cached_object)
        _write(context, output + 8, 8, old_hold)
        return output
    master = (_read(context, subject + 0x10, 8) - _MASTER_ADD) & _U64
    selector = _signed(_read(context, master + 0xA6, 2), 2)
    world = _read(context, _read(context, subject + 0x18, 8) + 8, 8)
    descriptor = _call(calls, 0x141604030, (world,), width=8)
    entry = (_read(context, descriptor, 8) + selector * 24) & _U64
    world = _read(context, _read(context, subject + 0x18, 8) + 8, 8)
    world_maps = _read(context, world + 0x98, 8)
    with _local(memoryview(bytearray(scratch)), bind_local) as temporary:
        maps = _read(context, world_maps + 0x5BC0, 8)
        _call(calls, 0x1414ECF90, (maps, temporary, entry, 0))
        control = _read(context, temporary + 16, 8)
        obj, cache = 0, 0
        if control:
            obj = _read(context, temporary + 8, 8)
            _atomic(atomics, control + 12, 1)
            cache = control
            control = _read(context, temporary + 16, 8)
        _write(context, subject + 0x1D8, 8, obj)
        previous = _read(context, subject + 0x1E0, 8)
        _write(context, subject + 0x1E0, 8, cache)
        if previous:
            _release(context, previous, calls, atomics, weak_only=True)
            control = _read(context, temporary + 16, 8)
        _write(context, output, 8, 0)
        _write(context, output + 8, 8, 0)
        if control:
            _atomic(atomics, control + 8, 1)
            control = _read(context, temporary + 16, 8)
        _write(context, output, 8, _read(context, temporary + 8, 8))
        _write(context, output + 8, 8, control)
        if control:
            _release(context, control, calls, atomics)
        if old_hold:
            _release(context, old_hold, calls, atomics)
    return output


def lookup_replay_ai_zone(
    context: ReplayTaskRebuildStorage,
    zone_map: int,
    x: int,
    y: int,
) -> int:
    """Full54B1414ecf50, signed low32 bounds and exact row-pointer read order."""
    _validate(context, ReplayTaskRebuildCalls(None), zone_map, x, y)
    x, y = _signed(x & _U32, 4), _signed(y & _U32, 4)
    if y < 0:
        return 0
    dimensions = _read(context, zone_map + 0x830, 8)
    if y >= _signed(_read(context, dimensions + 0x34, 4), 4) or x < 0:
        return 0
    if x >= _signed(_read(context, dimensions + 0x30, 4), 4):
        return 0
    rows = _read(context, zone_map + 0x810, 8)
    row = _read(context, rows + y * 8, 8)
    return _read(context, row + x * 2, 2)


def read_replay_unit_ai_position_kind(
    context: ReplayTaskRebuildStorage,
    subject: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
) -> int:
    """Full285B14124dd50 caller; live output pair through lookup and final release."""
    _validate(context, calls, subject)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual shared count and local bindings required")
    with _local(memoryview(bytearray(16)), bind_local) as pair:
        _call(calls, 0x141251F70, (subject, pair))
        zone_map = _read(context, pair, 8)
        result = 0
        if zone_map:
            y = _coordinate(context, subject, 0x178)
            x = _coordinate(context, subject, 0x170)
            result = _call(calls, 0x1414ECF50, (zone_map, _cvtt(x), _cvtt(y)), width=8) & 0xFFFF
        control = _read(context, pair + 8, 8)
        if control:
            _release(context, control, calls, atomics)
    return result


def bind_replay_unit_ai_map(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> ReplayTaskRebuildCalls:
    """Bind acquisition, position-kind caller and map lookup with actual descendants."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual shared count and local bindings required")
    if type(scratch) is not bytes or len(scratch) != 24:
        raise ValueError("explicit24-byte map temporary scratch required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x141251F70: 2, 0x14124DD50: 1, 0x1414ECF50: 3}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed UnitAI map call")
        if target == 0x141251F70:
            return acquire_replay_unit_ai_map(
                context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
            )
        if target == 0x14124DD50:
            return read_replay_unit_ai_position_kind(
                context, *args, calls=bound, atomics=atomics, bind_local=bind_local
            )
        return lookup_replay_ai_zone(context, *args)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
