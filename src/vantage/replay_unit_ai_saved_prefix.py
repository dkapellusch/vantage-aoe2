"""Normal scalar prefix of build54800 common saved UnitAI reader140d267d0.

Retained entry-source review proves the phases through140d298f6:24 modern
reads, not27, followed by the first count at140d29929 (outside this prefix).
The legacy version interval inserts two4B reads to one private local. Current
I/O, Result cleanup and control effects remain mandatory. Returned-error/TLS
logging, stack identity, native faults, C++ EH and later restoration are excluded.
"""

from __future__ import annotations

from contextlib import ExitStack

from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_FIRST = (0x10, 0x3C, 0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x58, 0x5C)
_MIDDLE = (0x68, 0x64, 0x6C, 0x70, 0x164, 0x168, 0x170, 0x16C, 0x174, 0x178, 0x17C)


def read_replay_unit_ai_saved_prefix(
    context: ReplayTaskRebuildStorage,
    address: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    legacy_scratch: bytes,
) -> None:
    """Execute the actual scalar-read/cleanup sequence, stopping before count.

    This is a source prefix, not a binding for the entire27KB native body.
    Each current stream vptr/slot is sampled anew. Raw read RAX is ignored;
    current Result status controls continuation. Results remain live through
    the prefix. An error refuses at its returned-error frontier with earlier
    effects intact. The private legacy destination needs explicit4B scratch;
    no initial value is inferred for that uninitialized native stack word.
    """
    _validate(context, calls, address, stream)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual saved AI shared-count and local bindings required")
    if type(legacy_scratch) is not bytes or len(legacy_scratch) != 4:
        raise ValueError("explicit4B saved AI legacy scratch required")
    with ExitStack() as locals_:

        def read(destination: int, width: int, *, inline: bool = False) -> None:
            result = locals_.enter_context(_local(memoryview(bytearray(48)), bind_local))
            table = _read(context, stream, 8)
            target = _read(context, table + 0x18, 8)
            _call(calls, target, (stream, result, destination & _U64, width))
            if _read(context, result + 0x18, 8):
                raise UnresolvedReplayTaskRebuild(
                    "saved AI read reached native returned-error/logging frontier"
                )
            _write(context, result + 0x28, 1, 1)
            if inline:
                control = _read(context, result + 0x20, 8)
                if control:
                    _release(context, control, calls, atomics)
                _call(calls, 0x1402BD890, (result,))
            else:
                _call(calls, 0x140900620, (result,))

        for offset in _FIRST:
            read(address + offset, 4, inline=True)
        for offset in _MIDDLE:
            read(address + offset, 4)
        version = _read(context, 0x1440A0D94, 4)
        if (version - 0x1407AE) & 0xFFFFFFFF <= 0x62B84:
            legacy = locals_.enter_context(
                _local(memoryview(bytearray(legacy_scratch)), bind_local)
            )
            read(legacy, 4)
            read(legacy, 4)
        read(address + 0x60, 4)
        read(address + 0x194, 4)
        read(address + 0x184, 16)
