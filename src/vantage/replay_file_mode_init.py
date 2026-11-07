"""Complete File mode initializer140916040 and size leaf14178ae20.

Source: replay-file-read-seek-contract-v1,448B102instructions and6B2instructions.
Current allocation/backend/error-constructor effects remain mandatory. No File
state, codec, native backend, IAT mapping or successful child is inferred.
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
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_MODE, _SIZE, _BACKEND = 0x140916040, 0x14178AE20, 0x14093A930
_CALLOC_IAT, _MALLOC_IAT, _ERROR_IAT = 0x143199DC0, 0x143199DB0, 0x143198A88


@dataclass(frozen=True, slots=True)
class ReplayFileModeInitProfile:
    """Live40h seed, excluding physical cookie40 and conditional savedRSI80.

    QWORD38 is entry output then backend actual-count backing. QWORD20 and
    DWORD28 are live variadic format/code homes; their unwritten bytes retain
    the explicit seed. No local Result or implicit blanket zero is supplied.
    """

    frame: bytes

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 0x40:
            raise ValueError("explicit40-hex-byte mode-initializer local seed required")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _raw(value: int | None, description: str) -> int:
    if value is None:
        raise ValueError(f"{description} must supply rawRAX at its source consumption")
    _unsigned(value, 8, description)
    return value


def _construct(
    variadic_calls: ReplayTaskRebuildCalls,
    output: int,
    frame: int,
    line: int,
) -> None:
    _call(
        variadic_calls,
        0x140A08840,
        (
            output,
            0,
            0x1431F7B10,
            line,
            (frame + 0x20) & _U64,
            (frame + 0x28) & _U64,
        ),
    )


def _initialize(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    variadic_calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    file: int,
    output: int,
    *,
    bind_local: LocalBinding,
    profile: ReplayFileModeInitProfile,
) -> int:
    with _local(memoryview(bytearray(profile.frame)), bind_local) as frame:
        _write(context, frame + 0x38, 8, output)
        mode = _read(context, file + 0x80, 4)
        if mode not in (0, 1):
            _write(context, frame + 0x20, 8, 0x1431F7B80)
            _construct(variadic_calls, output, frame, 0x1FE)
            return output

        # Keep the actual leaf CALL and MOVSXD EAX, even though its body is6B.
        size_rax = _invoke(calls, _SIZE, (file,))
        size = _signed(_raw(size_rax, "decoder-state size leaf") & _U32, 4) & _U64
        state = _invoke(imports, _read(context, _CALLOC_IAT, 8), (size, 1))
        remaining = _read(context, file + 0x98, 8)
        _write(context, file + 0x88, 8, _raw(state, "calloc allocation"))
        if not remaining:
            length = _read(context, file + 0x30, 8)
            remaining = (length - _read(context, file + 0x40, 8)) & _U64
            _write(context, file + 0x98, 8, remaining)
        position = _read(context, file + 0x40, 8)
        if (position + remaining) & _U64 > _read(context, file + 0x30, 8):
            _write(context, frame + 0x28, 4, 0x24)
            _write(context, frame + 0x20, 8, 0x1431F7B68)
            _write(context, file + 0x80, 4, 0)
            _write(context, file + 0x48, 4, 0x24)
            _write(context, file + 0x4C, 4, 0x24)
            _construct(variadic_calls, output, frame, 0xD7)
            return output

        allocation = _invoke(imports, _read(context, _MALLOC_IAT, 8), (remaining,))
        expected = _read(context, file + 0x98, 4)
        handle = _read(context, file + 0x28, 8)
        buffer = _raw(allocation, "malloc allocation")
        _write(context, file + 0x90, 8, buffer)
        _write(context, frame + 0x38, 8, 0)
        backend = _invoke(
            calls,
            _BACKEND,
            (
                handle,
                buffer,
                expected,
                (frame + 0x38) & _U64,
            ),
        )
        actual = _read(context, frame + 0x38, 8) & _U32
        _write(context, file + 0x40, 8, _read(context, file + 0x40, 8) + actual)
        # Source TESTAL follows the count read and current cursor publication.
        backend_raw = _raw(backend, "File backend at AL test")
        if backend_raw & 0xFF and actual == expected:
            _write(context, file + 0xA0, 8, 0)
            _write(context, file + 0x80, 4, 2)
            _write(context, file + 0x48, 4, 0)
            for offset in (0, 8, 16, 24, 32):
                _write(context, output + offset, 8, 0)
            _write(context, output + 40, 1, 0)
            return output

        _write(context, file + 0x80, 4, 0)
        _write(context, file + 0x48, 4, 0x25)
        _write(context, file + 0x4C, 4, 0x25)
        error = _invoke(imports, _read(context, _ERROR_IAT, 8), ())
        _write(context, frame + 0x28, 4, 0x25)
        _write(context, file + 0x50, 4, _raw(error, "GetLastError at File50 store"))
        _write(context, frame + 0x20, 8, 0x1431F7B68)
        _construct(variadic_calls, output, frame, 0xD7)
        return output


def bind_replay_file_mode_init(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    variadic_calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayFileModeInitProfile,
) -> ReplayTaskRebuildCalls:
    """Own full mode initializer and actual6B size leaf; no successful defaults.

    Mode initializer takes(File,heldOutput). Size leaf accepts0 or1 incidental
    RCX annotations; it ignores them and returns actualMOV EAX,a0c8. The mode
    caller explicitly invokes that owned leaf through bound Calls before its
    signedEAX-to-calloc argument conversion. Allocation and GetLastError current
    IAT targets bypass these body bindings through required imports. Their raw
    RAX validates only at its first reached source consumption, after earlier
    reads/stores. Null allocation is an actual0 pointer, never an error shortcut.

    Backend14093a930 remains an actual four-scalar wrapper capability. Its raw
    return may stay opaque through current actual-count/cursor effects; TESTAL
    then requires rawu64. Current File98 lowDWORD after malloc is held expected,
    distinct from prior held64 allocation size and held88-publication input.
    All constructors target heldoutput directly through separate variadic Calls,
    with actual live20/28 HOME locations, source store order and ignored RAX.
    There is no local Result cleanup, old-allocation free or inferred statezero.

    Every normal return is heldoutput. Only41 success bytes are initialized.
    Physical stack/cookies/savedregisters, escaped locals, native faults/EH and
    concurrent behavior are excluded. No runtime File/backend/codec readiness
    or current-memory defaults are implied. Unknown targets delegate unchanged.
    """
    _validate(context, calls)
    _validate(context, variadic_calls)
    _validate(context, imports)
    if not callable(bind_local) or not isinstance(profile, ReplayFileModeInitProfile):
        raise ValueError("explicit mode-initializer local binding and profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (_MODE, _SIZE):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        allowed = (2,) if target == _MODE else (0, 1)
        if len(args) not in allowed or data is not None:
            raise ValueError("malformed File mode initializer/size leaf call")
        _validate(context, calls, *args)
        if target == _SIZE:
            return 0xA0C8
        return _initialize(
            context, bound, variadic_calls, imports, *args, bind_local=bind_local, profile=profile
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
