"""Build54800 current observer/index/settings helpers (438 original bytes).

Complete source is frozen in player-color-context-source-v1. These bodies read
actual current storage; they do not initialize a Game, infer viewer settings or
choose an observer. Actual special-key setter calls remain mandatory. Native
physical stack/register, fault/EH and concurrent-writer parity are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_task_group_storage import LocalBinding
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _write,
)
from vantage.replay_unit_ai_base import _validate
from vantage.replay_unit_ai_construction import _local

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_OBSERVER, _INDEX, _OWNER, _SETTING = 0x141603D70, 0x141603DB0, 0x141734F30, 0x14097FB40


@dataclass(frozen=True, slots=True)
class ReplayPlayerColorContextScratch:
    """Explicit4B logical output home for owner predicate workingRSP+30.

    The real12B getter overwrites its entire extent before returning its held
    address. The parent reads the actual returned pointer, even if another
    explicitly supplied getter binding returns a different backed address.
    """

    owner_index: bytes

    def __post_init__(self) -> None:
        if type(self.owner_index) is not bytes or len(self.owner_index) != 4:
            raise ValueError("explicit4B Player color owner-index local required")


def read_replay_player_color_observer(context: ReplayTaskRebuildStorage, world: int) -> int:
    """Full53B141603d70; unsigned index versus wrapped signed-SAR count bits."""
    _validate(context, ReplayTaskRebuildCalls(None), world)
    index = _read(context, world + 0x6B0, 4)
    if _read(context, 0x143DA5054, 4) == index:
        return 0
    begin = _read(context, world + 0x768, 8)
    end = _read(context, world + 0x770, 8)
    count = (_signed((end - begin) & _U64, 8) >> 4) & _U64
    return _read(context, begin + index * 16, 8) if index < count else 0


def copy_replay_player_color_observer_index(
    context: ReplayTaskRebuildStorage,
    world: int,
    output: int,
) -> int:
    """Full12B141603db0: readDWORD, storeDWORD, return held output pointer."""
    _validate(context, ReplayTaskRebuildCalls(None), world, output)
    value = _read(context, world + 0x6B0, 4)
    _write(context, output, 4, value)
    return output


def is_replay_player_color_observer(
    context: ReplayTaskRebuildStorage,
    player: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: ReplayPlayerColorContextScratch,
) -> int:
    """Full40B141734f30: actual getter result DWORD before current Player ID."""
    _validate(context, calls, player)
    if not callable(bind_local) or not isinstance(scratch, ReplayPlayerColorContextScratch):
        raise ValueError("actual local binding and Player color context seed required")
    with _local(memoryview(bytearray(scratch.owner_index)), bind_local) as output:
        world = _read(context, player + 8, 8)
        returned = _call(calls, _INDEX, (world, output), width=8)
        selected = _read(context, returned, 4)
        return int(_read(context, player + 0x648, 4) == selected)


def read_replay_player_color_setting(
    context: ReplayTaskRebuildStorage,
    settings: int,
    key: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Full333B14097fb40; current FNV bucket lookup and mandatory special setter.

    The entry settings pointer is held through the special-key callback, whose
    receiver is separately read from the current global. A missing key's zero
    result comes from the actual inclusive traversal, not a provider default.
    """
    _validate(context, calls, settings, key)
    key &= _U32
    enabled = _read(context, 0x144287088, 1)
    if not enabled:
        if key in (0x94, 0x9A):
            return 1
    elif key == 0x94 and not _read(context, 0x1442870D0, 1):
        receiver = _read(context, 0x14425B930, 8)
        _write(context, 0x1442870D0, 1, 1)
        _call(calls, 0x140984210, (receiver, key, 0))
    hashed = 0xCBF29CE484222325
    for shift in (0, 8, 16, 24):
        hashed = (hashed ^ (key >> shift & 255)) * 0x100000001B3 & _U64
    head = _read(context, settings + 0x50, 8)
    mask = _read(context, settings + 0x78, 8)
    bucket = _read(context, settings + 0x60, 8) + ((hashed & mask) << 4)
    node = _read(context, bucket + 8, 8)
    if node == head:
        node = 0
    else:
        terminal = _read(context, bucket, 8)
        while _read(context, node + 0x10, 4) != key:
            if node == terminal:
                node = 0
                break
            node = _read(context, node + 8, 8)
    if not node:
        node = head
    if node == head:
        return 0
    value = _read(context, node + 0x14, 4)
    if key == 0xDE and value == _U32:
        derived = _call(calls, _SETTING, (settings, 0x3B), width=4)
        return 1 + int(derived != 0)
    return value


def bind_replay_player_color_context(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: ReplayPlayerColorContextScratch,
) -> ReplayTaskRebuildCalls:
    """Bind four complete callers; existing17B Game mode provider is composed below."""
    _validate(context, calls)
    if not callable(bind_local) or not isinstance(scratch, ReplayPlayerColorContextScratch):
        raise ValueError("actual local binding and Player color context seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {_OBSERVER: 1, _INDEX: 2, _OWNER: 1, _SETTING: 2}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Player color context call")
        _validate(context, calls, *args)
        if target == _OBSERVER:
            return read_replay_player_color_observer(context, *args)
        if target == _INDEX:
            return copy_replay_player_color_observer_index(context, *args)
        if target == _OWNER:
            return is_replay_player_color_observer(
                context, *args, calls=bound, bind_local=bind_local, scratch=scratch
            )
        return read_replay_player_color_setting(context, *args, calls=bound)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
