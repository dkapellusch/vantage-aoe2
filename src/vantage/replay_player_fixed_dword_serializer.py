"""Build54800 complete normal fixed-DWORD serializer caller and scalar child.

591B140e6a9c0 wraps747B140d77490, which invokes the real six-input4B
wrapper140b81d60. Each explicit0x70 data frame excludes its cookie at70,
physical register saves/home aliases, TLS diagnostics, faults and C++ unwinding.
Known normal read/write/call order and partial effects remain observable; reached
returned-error paths refuse before unported metadata/TLS work. This is owned
logical storage with mandatory actual children, not native stack identity.
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
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release


@dataclass(frozen=True)
class ReplayPlayerFixedDwordScratch:
    """Explicit independently live data-frame seeds; no invented stack bytes."""

    wrapper: bytes
    scalar: bytes

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, bytes) or len(value) != 0x70
            for value in (self.wrapper, self.scalar)
        ):
            raise ValueError("fixed DWORD serializers require two explicit0x70 byte seeds")


def _providers(atomics: ReplayUnitAIMapAtomics, bind_local: LocalBinding) -> None:
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual fixed DWORD atomics and local binding required")


def _zero48(context: ReplayTaskRebuildStorage, address: int) -> None:
    for offset in (0, 16, 32):
        _write(context, address + offset, 16, 0)


def _success(context: ReplayTaskRebuildStorage, address: int) -> None:
    for offset in (0, 8, 16, 24, 32):
        _write(context, address + offset, 8, 0)
    _write(context, address + 40, 1, 0)


def _cleanup(
    context: ReplayTaskRebuildStorage,
    result: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD890, (result,))


def read_replay_fixed_dword_scalar(
    context: ReplayTaskRebuildStorage,
    output: int,
    metadata: int,
    line: int,
    detail: int,
    stream: int,
    destination: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerFixedDwordScratch,
) -> int:
    """Complete normal747B140d77490, six scalar operands with held output/dest.

    Current DWORD38 is copied only after current raw-control release/vector
    cleanup. QWORD38 starts as output identity and is the actual Input target;
    its high DWORD survives the4B read. The three metadata operands are forwarded
    to the actual4B wrapper, which consumes only line's low32 bits. That child's
    returned pointer is ignored. Normal success preserves output's last7 bytes.
    Native error loads three16B literals then reaches unported TLS at140d77526.
    """
    _validate(context, calls, output, metadata, line, detail, stream, destination)
    _providers(atomics, bind_local)
    if not isinstance(scratch, ReplayPlayerFixedDwordScratch):
        raise ValueError("actual fixed DWORD scratch required")
    with _local(memoryview(bytearray(scratch.scalar)), bind_local) as frame:
        _write(context, frame + 0x38, 8, output)
        _zero48(context, frame + 0x40)
        _write(context, frame + 0x28, 8, frame + 0x38)
        _write(context, frame + 0x20, 8, stream)
        _call(calls, 0x140B81D60, (frame + 0x40, metadata, line, detail, stream, frame + 0x38))
        if _read(context, frame + 0x58, 8):
            for literal in (0x14325DF50, 0x14325D6D0, 0x14325DE60):
                _read(context, literal, 16)
            raise UnresolvedReplayTaskRebuild(
                "fixed DWORD scalar reached error TLS frontier140d77526"
            )
        _write(context, frame + 0x68, 1, 1)
        _cleanup(context, frame + 0x40, calls, atomics)
        value = _read(context, frame + 0x38, 4)
        _write(context, destination, 4, value)
        _success(context, output)
        return output


def read_replay_player_fixed_dword(
    context: ReplayTaskRebuildStorage,
    output: int,
    stream: int,
    destination: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerFixedDwordScratch,
) -> int:
    """Complete normal591B140e6a9c0, retaining the actual nested serializer call.

    Metadata is source14325f510/line17/detail14326b458. The nested RAX is ignored;
    this caller checks its fixed Result40, marks it processed, releases its
    current control and destroys its vector before41B success on held output.
    Returned error refuses at140e6aa2e before the unported metadata getter.
    Logical locals remain live through all callbacks and return; they can alias
    through their published addresses, excluding raw native physical home aliases.
    """
    _validate(context, calls, output, stream, destination)
    _providers(atomics, bind_local)
    if not isinstance(scratch, ReplayPlayerFixedDwordScratch):
        raise ValueError("actual fixed DWORD scratch required")
    with _local(memoryview(bytearray(scratch.wrapper)), bind_local) as frame:
        _write(context, frame + 0x38, 8, output)
        _zero48(context, frame + 0x40)
        _write(context, frame + 0x28, 8, destination)
        _write(context, frame + 0x20, 8, stream)
        _call(
            calls, 0x140D77490, (frame + 0x40, 0x14325F510, 0x17, 0x14326B458, stream, destination)
        )
        if _read(context, frame + 0x58, 8):
            raise UnresolvedReplayTaskRebuild(
                "fixed DWORD wrapper reached metadata frontier140e6aa2e"
            )
        _write(context, frame + 0x68, 1, 1)
        _cleanup(context, frame + 0x40, calls, atomics)
        _success(context, output)
        return output


def bind_replay_player_fixed_dword_serializer(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerFixedDwordScratch,
) -> ReplayTaskRebuildCalls:
    """Bind both normal complete callers; metadata/TLS errors refuse at reach."""
    _validate(context, calls)
    _providers(atomics, bind_local)
    if not isinstance(scratch, ReplayPlayerFixedDwordScratch):
        raise ValueError("actual fixed DWORD scratch required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {0x140E6A9C0: 3, 0x140D77490: 6}
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed fixed DWORD serializer call")
        _validate(context, calls, *args)
        if target == 0x140E6A9C0:
            return read_replay_player_fixed_dword(
                context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
            )
        return read_replay_fixed_dword_scalar(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
