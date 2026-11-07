"""Concrete File backend141756ea0/141757120 under explicit HOME ABI.

Complete150B/167B caller bodies under an explicit logical HOME-LOCATION ABI.
Source: replay-file-backend-provenance-source-v1,45pins/25staticproducts.
OS capabilities/logger/current IATs and caller homes remain mandatory. This
does not select or construct the runtime backend, open files or implement I/O.
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

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_READ, _SEEK = 0x141756EA0, 0x141757120
_READ_IAT, _SEEK_IAT, _ERROR_IAT = 0x143198988, 0x1431989A8, 0x143198A88
_LOGGER = 0x1417583C0


@dataclass(frozen=True, slots=True)
class ReplayFileBackendProfile:
    """Explicit seeded logical prefixes, excluding native cookie/save cells.

    Read38h includes actualQWORD20 andDWORD30; seek28h includes actualQWORD20.
    Every other byte keeps its supplied seed. The caller fifth home is a
    separate explicit current-storage address, not a copied scalar value.
    Relative native stack adjacency and escaped/derived physical-stack aliases
    are excluded; all admitted home/local aliases must use coherent storage.
    """

    read: bytes
    seek: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.read, 0x38),
                (self.seek, 0x28),
            )
        ):
            raise ValueError("explicit38/28-hex-byte backend local seeds required")


def _failure(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    os_calls: ReplayTaskRebuildCalls,
    text: int,
) -> int:
    error = _call(os_calls, _read(context, _ERROR_IAT, 8), (), width=8)
    raw = _call(calls, _LOGGER, (text, error & _U32), width=8)
    return raw & ~0xFF


def _read_backend(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    os_calls: ReplayTaskRebuildCalls,
    handle: int,
    destination: int,
    count: int,
    fifth_home: int,
    *,
    bind_local: LocalBinding,
    profile: ReplayFileBackendProfile,
) -> int:
    with _local(memoryview(bytearray(profile.read)), bind_local) as frame:
        # Source141756eb5 captures this BEFORE even the invalid-handle test.
        output = _read(context, fifth_home, 8)
        if handle == _U64:
            return handle & ~0xFF
        _write(context, frame + 0x30, 4, 0)
        _write(context, frame + 0x20, 8, 0)
        target = _read(context, _READ_IAT, 8)
        # The OS capability receives the current outgoing fifth value after
        # target selection, not an inferred zero from the earlier store.
        raw = _call(
            os_calls,
            target,
            (
                handle,
                destination,
                count & _U32,
                (frame + 0x30) & _U64,
                _read(context, frame + 0x20, 8),
            ),
            width=8,
        )
        if not raw & _U32:
            return _failure(context, calls, os_calls, 0x1432F7F10)
        if output:
            raw = _read(context, frame + 0x30, 4)
            _write(context, output, 8, raw)
        return (raw & ~0xFF) | 1


def _seek_backend(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    os_calls: ReplayTaskRebuildCalls,
    handle: int,
    output: int,
    mode: int,
    fifth_home: int,
    *,
    bind_local: LocalBinding,
    profile: ReplayFileBackendProfile,
) -> int:
    with _local(memoryview(bytearray(profile.seek)), bind_local) as frame:
        if handle == _U64:
            return handle & ~0xFF
        reduced = (mode - 1) & _U32
        mapped = 2 if reduced == 0 else reduced if reduced == 1 else 0
        _write(context, frame + 0x20, 8, 0)
        # Source141757165 consumes CURRENTcaller home after the local store.
        requested = _read(context, fifth_home, 8)
        target = _read(context, _SEEK_IAT, 8)
        raw = _call(
            os_calls,
            target,
            (
                handle,
                requested,
                (frame + 0x20) & _U64,
                mapped,
            ),
            width=8,
        )
        if not raw & _U32:
            return _failure(context, calls, os_calls, 0x1432F7F40)
        if output:
            raw = _read(context, frame + 0x20, 8)
            _write(context, output, 8, raw)
        return (raw & ~0xFF) | 1


def bind_replay_file_backend_homes(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    os_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayFileBackendProfile,
) -> ReplayTaskRebuildCalls:
    """Own two complete bodies through a dedicated HOME-LOCATION Calls channel.

    Effective args are the first4 native register values plus FIFTH_HOME_ADDRESS
    in engine current storage. This fifth argument is NEVER its scalar value.
    Incoming serviceRCX is validated as a raw word but its backing is not read.
    Read holds its output pointer before invalid-handle testing. Seek does not
    read its requested home for invalid -1 and otherwise waits until local20=0.

    Current IAT targets dispatch to the explicit os_calls channel, bypassing
    these body bindings; no imports, handles or native I/O are supplied. ReadFile
    receives five effective scalar args, with the outgoing overlapped value
    sampled after current IAT selection. SetFilePointerEx receives four scalar
    args. GetLastError receives zero. All must return rawu64 RAX at its first
    source consumption; fullEAX, notAL, decides OS success. Actual logger1417583c0
    receives(formatAddress,lowDWORDerror) and must likewise supply rawRAX. Missing
    providers refuse when reached, retaining earlier local/provider effects.

    Return tracks caller-body RAX at its final MOVAL1/XORAL0, retaining its upper
    bits from handle, OS return, output-local load or logger as the source does.
    Only AL is the method's semantic success result; no full0/1 value is inferred.
    Physical prologue/security-cookie epilogue, native faults/EH/thread behavior,
    escaped locals and physical caller-frame adjacency are outside this profile.

    FileSupport must explicitly select backend_home_calls to pass live homes;
    its scalar default remains a separate ABI. Configure calls to reject unknown
    HOME targets rather than use a generic scalar fallback. No global/vptr
    construction, selected runtime backend or OS capability is inferred here.
    Unknown targets delegate unchanged to calls or refuse when unavailable.
    """
    _validate(context, calls)
    _validate(context, os_calls)
    if not callable(bind_local) or not isinstance(profile, ReplayFileBackendProfile):
        raise ValueError("explicit backend local binding and profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (_READ, _SEEK):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 5 or data is not None:
            raise ValueError("backend HOME channel requires4registers and fifthHOMEaddress")
        _validate(context, calls, *args)
        body = _read_backend if target == _READ else _seek_backend
        return body(context, calls, os_calls, *args[1:], bind_local=bind_local, profile=profile)

    return ReplayTaskRebuildCalls(dispatch)
