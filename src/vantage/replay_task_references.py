"""Build54800 task sound descriptors and their exact two membership predicates.

Sources: task-facet-constructor-source-v1/14147b6e0 and
task-record-construction-source-v1/140b25ec0,140b245d0. Current sound/registry
storage is explicit; wire IDs and DAT content do not stand in for pointers.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _unsigned,
    _write,
)

_U64 = (1 << 64) - 1
_FLAG_KEYS = frozenset(
    (
        0x76835F7D,
        0x365A7AE7,
        0x2C833F3E,
        0x060DC0F4,
        0x14D3ACCE,
        0x1716EBB5,
        0x236DCC97,
        0x2D2B16C2,
        0x3077F4A6,
        0x3567EACB,
        0x41F42F0A,
        0x3C09EEC2,
        0x3C1613FC,
        0x3F8C83A5,
        0x41193214,
        0x428CD3DC,
        0x49986E2E,
        0x6531D189,
        0xCD9A7723,
        0x9D70A540,
        0x7A7339A7,
        0x81BEDC81,
        0x89302157,
        0x90149FA1,
        0x909E25E1,
        0xA32DB00E,
        0xA39957AA,
        0xAEAFD969,
        0xC2F6D6C9,
        0xC372A22A,
        0xE14E765C,
        0xD15FEA9C,
        0xD26376BB,
        0xD87171D2,
        0xDF537AD7,
        0xE0372167,
        0xE3771939,
        0xE9692A25,
        0xF4FA624E,
        0xFA26EE2A,
    )
)


def task_sound_has_flag(primary: int) -> int:
    """Full140b245d0: exact ECX whitelist, returning defined AL only."""
    _unsigned(primary, 8, "task primary register")
    return int(primary & 0xFFFFFFFF in _FLAG_KEYS)


def task_sound_is_registered(context: ReplayTaskRebuildStorage, primary: int) -> int:
    """Full140b25ec0: FNV1a4 lookup with inclusive terminal and held head.

    Return value represents AL only. The actual finite registry's head, mask,
    buckets and reachable nodes must be backed. No native cycle/null checks or
    inferred empty registry are introduced.
    """
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task reference storage required")
    _unsigned(primary, 8, "task primary register")
    primary &= 0xFFFFFFFF
    hashed = 0xCBF29CE484222325
    for byte in primary.to_bytes(4, "little"):
        hashed = ((hashed ^ byte) * 0x100000001B3) & _U64
    head = _read(context, 0x1442976B8, 8)
    mask = _read(context, 0x1442976E0, 8)
    bucket = (_read(context, 0x1442976C8, 8) + ((hashed & mask) << 4)) & _U64
    node = _read(context, bucket + 8, 8)
    if node == head:
        return 0
    terminal = _read(context, bucket, 8)
    while True:
        if _read(context, node + 0x10, 4) == primary:
            return int(node != 0 and node != head)
        if node == terminal:
            return 0
        node = _read(context, node + 8, 8)


def resolve_replay_task_sound(
    context: ReplayTaskRebuildStorage,
    descriptor: int,
    sounds: int,
    sound_id: int,
    fallback: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full14147b6e0: actual selected sound pointer/ranges and registry membership.

    Negative signed WORD IDs skip sound context access. Invalid/empty sounds
    clear only pointer+8. Nonempty primary0 installs fallback in both DWORDs;
    otherwise membership chooses held fallback or the reread current primary.
    Flags and trailing padding remain untouched. Earlier writes survive failure.
    """
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task reference storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit actual task reference calls required")
    for value in (descriptor, sounds, sound_id, fallback):
        _unsigned(value, 8, "task sound argument")
    index = _signed(sound_id & 0xFFFF, 2)
    fallback &= 0xFFFFFFFF
    if index < 0 or index >= _signed(_read(context, sounds + 0x10, 4), 4):
        _write(context, descriptor + 8, 8, 0)
        return
    begin = _read(context, sounds, 8)
    sound = _read(context, begin + index * 8, 8)
    _write(context, descriptor + 8, 8, sound)
    end = _read(context, sound + 0x10, 8)
    if _read(context, sound + 8, 8) == end:
        other_end = _read(context, sound + 0x30, 8)
        if _read(context, sound + 0x28, 8) == other_end:
            _write(context, descriptor + 8, 8, 0)
            return
    primary = _read(context, descriptor, 4)
    if primary == 0:
        _write(context, descriptor, 4, fallback)
        _write(context, descriptor + 4, 4, fallback)
        return
    if _call(calls, 0x140B25EC0, (primary,), width=8) & 255:
        fallback = _read(context, descriptor, 4)
    _write(context, descriptor + 4, 4, fallback)


def bind_replay_task_references(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind all three actual entries; unavailable other targets refuse at reach."""
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current task reference storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("explicit actual task reference calls required")
    arities = {0x14147B6E0: 4, 0x140B25EC0: 1, 0x140B245D0: 1}

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed task reference call")
        if target == 0x140B245D0:
            return task_sound_has_flag(args[0])
        if target == 0x140B25EC0:
            return task_sound_is_registered(context, args[0])
        resolve_replay_task_sound(context, *args, calls=bound)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
