"""Build54800 normal Player wire-type Input and current registry dispatch.

Three complete original bodies748/252/1288B are frozen in
player-wire-factory-input-source-v1. Actual stream, Result/control/vector
effects and current handlers remain mandatory. No registry setup, current
class identity or whole Player restore is inferred. Reached outer metadata/TLS,
private physical stacks/registers/cookies, faults/EH and concurrency are outside
this logical normal profile. Local aliases retain source current-read order.
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
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U32 = (1 << 32) - 1
_INPUT, _BYTE, _FACTORY = 0x1415E5830, 0x140DAF040, 0x14174F3D0


@dataclass(frozen=True, slots=True)
class ReplayPlayerWireFactoryScratch:
    """Explicit78/60/118-byte coherent logical caller frames.

    Input BYTE40 has no default. Byte-wrapper fixed Result lives at30;
    outer Input fixed Result at48; factory fixed Result at68. Factory incoming
    fifth-argument pointer is materialized once at110 on logical ABI ingress,
    then reloaded at its actual late source phase. Its cookie/saved-register
    gap98..10f is merely retained seed storage, not native register identity.
    Arbitrary aliases into nested physical callee stacks are not inferred.
    """

    input: bytes
    byte_wrapper: bytes
    factory: bytes

    def __post_init__(self) -> None:
        for value, size in ((self.input, 0x78), (self.byte_wrapper, 0x60), (self.factory, 0x118)):
            if type(value) is not bytes or len(value) != size:
                raise ValueError("explicit78/60/118-byte Player wire/factory frames required")


def _admit(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerWireFactoryScratch,
    *arguments: int,
) -> None:
    _validate(context, calls, *arguments)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Player wire shared-count and local bindings required")
    if not isinstance(scratch, ReplayPlayerWireFactoryScratch):
        raise ValueError("explicit Player wire/factory frame seeds required")


def _zero(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 16, 32):
        _write(context, result + offset, 16, 0)


def _output(context: ReplayTaskRebuildStorage, result: int) -> None:
    for offset in (0, 8, 16, 24, 32):
        _write(context, result + offset, 8, 0)
    _write(context, result + 40, 1, 0)


def _cleanup(
    context: ReplayTaskRebuildStorage,
    result: int,
    vector: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, vector, (result,))


def read_replay_player_wire_byte(
    context: ReplayTaskRebuildStorage,
    output: int,
    filename: int,
    line: int,
    detail: int,
    stream: int,
    destination: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerWireFactoryScratch,
) -> int:
    """Full normal252B140daf040; stream width1 and fixed local Result identity.

    Output48 is cleared after Input, before processed/status. A nonzero raw
    status requires real140900ed0; it is not erased into successful I/O. The
    actual Result forward runs even when status0. Child RAX is ignored.
    """
    _admit(
        context,
        calls,
        atomics,
        bind_local,
        scratch,
        output,
        filename,
        line,
        detail,
        stream,
        destination,
    )
    with _local(memoryview(bytearray(scratch.byte_wrapper)), bind_local) as frame:
        _write(context, frame + 0x28, 8, output)
        result = frame + 0x30
        _zero(context, result)
        target = _read(context, _read(context, stream, 8) + 0x18, 8)
        _call(calls, target, (stream, result, destination, 1))
        _zero(context, output)
        _write(context, result + 40, 1, 1)
        if _read(context, result + 24, 8):
            _call(calls, 0x140900ED0, (result, filename, line & _U32, detail))
        _call(calls, 0x1409076B0, (output, result))
        _cleanup(context, result, 0x1402BD890, calls, atomics)
        return output


def read_replay_player_wire_type(
    context: ReplayTaskRebuildStorage,
    output: int,
    filename: int,
    line: int,
    detail: int,
    stream: int,
    destination: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerWireFactoryScratch,
) -> int:
    """Full normal748B1415e5830: publish zeroextended byte after real cleanup.

    The scratch byte is not initialized. Cleanup can mutate it before its
    current reload. The destination DWORD store precedes41-byte output clear;
    an admitted destination/output alias follows those exact stores.
    """
    _admit(
        context,
        calls,
        atomics,
        bind_local,
        scratch,
        output,
        filename,
        line,
        detail,
        stream,
        destination,
    )
    with _local(memoryview(bytearray(scratch.input)), bind_local) as frame:
        _write(context, frame + 0x38, 8, output)
        result = frame + 0x48
        _zero(context, result)
        _write(context, frame + 0x28, 8, frame + 0x40)
        _write(context, frame + 0x20, 8, stream)
        _call(calls, _BYTE, (result, filename, line & _U32, detail, stream, frame + 0x40))
        if _read(context, result + 24, 8):
            raise UnresolvedReplayTaskRebuild("Player wire Input metadata/TLS frontier")
        _write(context, result + 40, 1, 1)
        _cleanup(context, result, 0x1402BD7F0, calls, atomics)
        value = _read(context, frame + 0x40, 1)
        _write(context, destination, 4, value)
        _output(context, output)
        return output


def create_replay_player_wire_factory(
    context: ReplayTaskRebuildStorage,
    output: int,
    stream: int,
    auxiliary: int,
    world: int,
    index_pointer: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerWireFactoryScratch,
) -> int:
    """Full normal1288B14174f3d0 with current signed lookup and actual dispatch.

    No registry/current-handler identity, pointer bounds or missing-key fallback
    is manufactured. The current fifth-pointer slot is read after both cleanup
    phases. No status check or cleanup is added after the handler call.
    """
    _admit(
        context,
        calls,
        atomics,
        bind_local,
        scratch,
        output,
        stream,
        auxiliary,
        world,
        index_pointer,
    )
    with _local(memoryview(bytearray(scratch.factory)), bind_local) as frame:
        _write(context, frame + 0x110, 8, index_pointer)  # Logical incoming ABI slot.
        local, result = frame + 0x38, frame + 0x68
        _write(context, local, 8, output)
        _zero(context, result)
        _write(context, frame + 0x28, 8, local)
        _write(context, frame + 0x20, 8, stream)
        _call(calls, _INPUT, (result, 0x1432F6A30, 0x73, 0x1432E9944, stream, local))
        if _read(context, result + 24, 8):
            raise UnresolvedReplayTaskRebuild("Player factory Input metadata/TLS frontier")
        _write(context, result + 40, 1, 1)
        _cleanup(context, result, 0x1402BD890, calls, atomics)
        _zero(context, result)
        sentinel = _read(context, 0x144440968, 8)
        node = _read(context, sentinel + 8, 8)
        candidate = sentinel
        key = _read(context, local, 4)
        while not _read(context, node + 0x19, 1):
            if _signed(_read(context, node + 0x20, 4), 4) >= _signed(key, 4):
                candidate = node
                node = _read(context, node, 8)
            else:
                node = _read(context, node + 0x10, 8)
        if _read(context, candidate + 0x19, 1) or (
            _signed(key, 4) < _signed(_read(context, candidate + 0x20, 4), 4)
        ):
            candidate = sentinel
        held_control = 0
        if candidate == sentinel:
            handler = 0
            _write(context, frame + 0x28, 4, key)
            _write(context, frame + 0x20, 8, 0x1432F6A10)
            _call(calls, 0x140A08840, (result, 0, 0x1432F6A30, 0x5C, 0x1432F6A10, key))
            held_control = _read(context, result + 32, 8)
        else:
            handler = _read(context, candidate + 0x28, 8)
            _write(context, result, 16, 0)
            _write(context, result + 16, 16, 0)
            _write(context, result + 32, 8, 0)
            _write(context, result + 40, 1, 0)
        if _read(context, result + 24, 8):
            raise UnresolvedReplayTaskRebuild("Player factory lookup metadata/TLS frontier")
        _write(context, result + 40, 1, 1)
        if held_control:
            _release(context, held_control, calls, atomics)
        _call(calls, 0x1402BD890, (result,))
        current_index = _read(context, frame + 0x110, 8)
        index = _read(context, current_index, 4)
        _write(context, local, 4, index)
        vptr = _read(context, handler, 8)
        _write(context, frame + 0x28, 8, local)
        _write(context, frame + 0x20, 8, world)
        target = _read(context, vptr + 8, 8)
        _call(calls, target, (handler, output, stream, auxiliary, world, local))
        return output


def bind_replay_player_wire_factory(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerWireFactoryScratch,
) -> ReplayTaskRebuildCalls:
    """Bind three source bodies; all ordinary callees remain actual dependencies."""
    _admit(context, calls, atomics, bind_local, scratch)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (_INPUT, _BYTE, _FACTORY):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if data is not None or len(args) != (5 if target == _FACTORY else 6):
            raise ValueError("malformed Player wire/factory call")
        if target == _INPUT:
            return read_replay_player_wire_type(
                context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
            )
        if target == _BYTE:
            return read_replay_player_wire_byte(
                context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
            )
        return create_replay_player_wire_factory(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
