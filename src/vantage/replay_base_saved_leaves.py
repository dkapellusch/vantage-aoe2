"""Five complete build54800 Base saved-reader leaf callers (307 bytes).

Source: base-saved-leaves-source-v1 regular-file, dual-image instruction and
switch-data checks. Actual growth/service factory/destruction, current backing
and shared atomics remain required. Native stack/register/fence/fault/EH and
concurrency equivalence are excluded; no current service identity is inferred.
"""

from __future__ import annotations

from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_GLOBAL = 0x1444585E8


def resize_replay_base_saved_name(
    context: ReplayTaskRebuildStorage,
    address: int,
    requested: int,
    fill: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full39B1402bb570; shrink stores length before current buffer selection.

    Grow tails to the actual child with requested-minus-held-length and raw
    incoming R8. The child's complete329B source consumes signed lowR8B; its
    allocation/copy behavior is mandatory, not replaced by a successful resize.
    This effect-only interface excludes incidental RAX on the shrink return.
    """
    _validate(context, calls, address, requested, fill)
    held = _read(context, address + 16, 8)
    if requested > held:
        _call(calls, 0x1402BB420, (address, (requested - held) & _U64, fill))
        return
    _write(context, address + 16, 8, requested)
    buffer = address
    if _read(context, address + 24, 8) > 15:
        buffer = _read(context, address, 8)
    _write(context, buffer + requested, 1, 0)


def release_replay_base_saved_pair_control(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    """Full75B1408ee150; read only pair+8, hold control through both releases."""
    _validate(context, calls, address)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual Base saved shared-count bindings required")
    control = _read(context, address + 8, 8)
    if control:
        _release(context, control, calls, atomics)


def classify_replay_base_saved_type(
    context: ReplayTaskRebuildStorage,
    category: int,
) -> int:
    """Full49B1410b9490 with current57-byte selector/three-target jump table.

    Unsigned lowECX above56 returns rawFFFFFFFF without data reads. Reached
    current tables must select one of the three original case entries.
    """
    _validate(context, ReplayTaskRebuildCalls(None), category)
    category &= 0xFFFFFFFF
    if category > 56:
        return 0xFFFFFFFF
    selected = _read(context, 0x1410B94D0 + category, 1)
    target = 0x140000000 + _read(context, 0x1410B94C4 + selected * 4, 4)
    if target == 0x1410B94B5:
        return 0
    if target == 0x1410B94B8:
        return category
    if target == 0x1410B94BB:
        return 0xFFFFFFFF
    raise UnresolvedReplayTaskRebuild(f"unadmitted saved type branch{target:x}")


def get_replay_base_saved_service(
    context: ReplayTaskRebuildStorage,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Full109B14185b6d0; preserve held return unless cleanup reloads global.

    A null current global requires an actual factory and explicit8-byte local
    seed. Its returned carrier can differ from that local. Both ownership
    cleanup calls preserve the source-explicit RCX/RDX, and each return reloads
    the current global. The factory/279B service destructor remain mandatory.
    """
    _validate(context, calls)
    if not callable(bind_local) or type(scratch) is not bytes or len(scratch) != 8:
        raise ValueError("actual Base service local binding and explicit8-byte seed required")
    held = _read(context, _GLOBAL, 8)
    if held:
        return held
    with _local(memoryview(bytearray(scratch)), bind_local) as local:
        carrier = _call(calls, 0x141856260, (local,), width=8)
        held = _read(context, carrier, 8)
        _write(context, carrier, 8, 0)
        previous = _read(context, _GLOBAL, 8)
        _write(context, _GLOBAL, 8, held)
        if previous:
            _call(calls, 0x1418535F0, (_GLOBAL, previous))
            held = _read(context, _GLOBAL, 8)
        previous = _read(context, local, 8)
        if previous:
            _call(calls, 0x1418535F0, (local, previous))
            held = _read(context, _GLOBAL, 8)
    return held


def record_replay_base_saved_notification(
    context: ReplayTaskRebuildStorage,
    service: int,
    subject: int,
) -> None:
    """Full35B14185ce10; active service gate, signed ID and current counter.

    Nonpositive object IDs decrement the wrapping DWORD counter and reread it
    before publishing subject2f0. A nonzero service1a1 skips all object reads.
    """
    _validate(context, ReplayTaskRebuildCalls(None), service, subject)
    if _read(context, service + 0x1A1, 1):
        return
    identifier = _read(context, subject + 8, 4)
    if _signed(identifier, 4) <= 0:
        counter = _read(context, service + 0x2CC, 4)
        _write(context, service + 0x2CC, 4, counter - 1)
        identifier = _read(context, service + 0x2CC, 4)
    _write(context, subject + 0x2F0, 4, identifier)


def bind_replay_base_saved_leaves(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> ReplayTaskRebuildCalls:
    """Bind all five complete normal leaves; unknown calls retain arguments."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics):
        raise ValueError("actual Base saved shared-count bindings required")
    if not callable(bind_local) or type(scratch) is not bytes or len(scratch) != 8:
        raise ValueError("actual Base service local binding and explicit8-byte seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x1402BB570: 3, 0x1408EE150: 1, 0x1410B9490: 1, 0x14185B6D0: 0, 0x14185CE10: 2}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Base saved leaf call")
        _validate(context, calls, *args)
        if target == 0x1402BB570:
            resize_replay_base_saved_name(context, *args, calls=bound)
        elif target == 0x1408EE150:
            release_replay_base_saved_pair_control(context, *args, calls=bound, atomics=atomics)
        elif target == 0x1410B9490:
            return classify_replay_base_saved_type(context, *args)
        elif target == 0x14185B6D0:
            return get_replay_base_saved_service(
                context, calls=bound, bind_local=bind_local, scratch=scratch
            )
        else:
            record_replay_base_saved_notification(context, *args)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
