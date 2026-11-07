"""Build54800 complete normal Action saved-reader caller14113e920.

Authority: frozen action-saved-reader-source-review-v1,6259B/1360 instructions.
The Moving parent, real map lookup, current behavior factory/list reader and
Input/Result children require actual bindings. Returned-error decoration/TLS
refuses at its reached frontier. Coherent successful scalar backing and finite
loops are premises; physical stack/register/cookie/fault/EH/concurrency parity
and complete World restoration are outside this logical caller profile.
"""

from __future__ import annotations

from dataclasses import dataclass

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
_READER = 0x14113E920
_VERSION = 0x1440A0D94


@dataclass(frozen=True, slots=True)
class ReplayActionSavedScratch:
    """Explicit B0-byte logical frame using native post-prologue RSP offsets.

    OUT scratch28, Result48 at68, legacyBYTE98, valueDWORD9c, keyDWORDa0 and
    countQWORDa8 share one live backing. Count initially receives outputRDX;
    other unwritten bytes retain these seeds. Native cookie/register saves,
    parameter homes, nested physical-stack overlap and escaped local pointers
    after return are excluded. No tag/map count or key padding is inferred0.
    """

    reader: bytes

    def __post_init__(self) -> None:
        if type(self.reader) is not bytes or len(self.reader) != 0xB0:
            raise ValueError("explicit B0-byte Action reader local seed required")


def _zero(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _finish(
    context: ReplayTaskRebuildStorage,
    result: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    if _read(context, result + 24, 8):
        raise UnresolvedReplayTaskRebuild(
            "Action saved reader reached returned-error decoration/TLS frontier"
        )
    _write(context, result + 40, 1, 1)
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD890, (result,))


def _version(context: ReplayTaskRebuildStorage) -> int:
    return _signed(_read(context, _VERSION, 4), 4)


def read_replay_saved_action(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    opaque: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayActionSavedScratch,
) -> int:
    """Full normal14113e920 with opaque R9 and all historical version gates.

    Current version/count/virtual/result reads occur at their source phases.
    Lookup receives actual frame pointers and its raw RAX carrier selects the
    node; MOVSS value handling is rawu32, without host floating point. Even an
    old version or zero map count reaches the actual behavior factory/reader.
    Missing descendants refuse at their call; earlier writes are retained.
    """
    _validate(context, calls, address, output, stream, opaque)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Action atomic/local providers required")
    if not isinstance(scratch, ReplayActionSavedScratch):
        raise ValueError("explicit Action reader local seed required")
    with _local(memoryview(bytearray(scratch.reader)), bind_local) as frame:
        _write(context, frame + 0xA8, 8, output)
        result = (frame + 0x68) & _U64
        _zero(context, result)
        _call(calls, 0x14121F910, (address, result, stream, opaque))
        _finish(context, result, calls, atomics)
        _write(context, address + 15, 1, 0x28)

        def raw(destination: int, width: int) -> None:
            _zero(context, result)
            target = _read(context, _read(context, stream, 8) + 24, 8)
            _call(calls, target, (stream, result, destination & _U64, width))
            _finish(context, result, calls, atomics)

        version = _version(context)
        if version < 0x250000:
            raw(frame + 0x98, 1)
            version = _version(context)
        # Skipping the legacy byte skips the native version reload too.
        if version >= 0x68000:
            raw(address + 0x428, 1)
        else:
            _write(context, address + 0x428, 1, 0)
        version = _version(context)
        if version >= 0xBE666:
            raw(address + 0x42C, 4)
        elif version >= 0xB947A:
            # Same held EAX supplies both comparisons; upper two bytes persist.
            raw(address + 0x42C, 2)
        else:
            _write(context, address + 0x42C, 4, 0)
        _write(context, address + 0x42A, 2, 0)
        if _version(context) >= 0x1A170A:
            raw(address + 0x430, 4)
            raw(address + 0x434, 4)
        else:
            _write(context, address + 0x430, 4, 0xFFFFFFFF)
            _write(context, address + 0x434, 4, 0)
        if _version(context) >= 0x43CCCD:
            raw(frame + 0xA8, 8)
            counter = 0
            if _read(context, frame + 0xA8, 8):
                while True:
                    raw(frame + 0xA0, 4)
                    raw(frame + 0x9C, 4)
                    value = _read(context, frame + 0x9C, 4)
                    carrier = _call(
                        calls,
                        0x1411369A0,
                        (address + 0x460, frame + 0x28, frame + 0xA0),
                        width=8,
                    )
                    node = _read(context, carrier, 8)
                    _write(context, node + 0x14, 4, value)
                    counter = (counter + 1) & _U64
                    if counter >= _read(context, frame + 0xA8, 8):
                        break
        target = _read(context, _read(context, address, 8) + 0x8F8, 8)
        manager = _call(calls, target, (address,), width=8)
        _write(context, address + 0x420, 8, manager)
        _zero(context, result)
        _call(calls, 0x140B88C50, (manager, result, stream))
        _finish(context, result, calls, atomics)
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
        return output


def bind_replay_action_saved(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayActionSavedScratch,
) -> ReplayTaskRebuildCalls:
    """Bind only14113e920; all actual parents/children delegate or refuse."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Action atomic/local providers required")
    if not isinstance(scratch, ReplayActionSavedScratch):
        raise ValueError("explicit Action reader local seed required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _READER:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 4 or data is not None:
            raise ValueError("malformed Action saved-reader call")
        return read_replay_saved_action(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
