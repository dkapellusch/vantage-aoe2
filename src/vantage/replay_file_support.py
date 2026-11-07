"""File preflight, buffered seek and two backend dispatch bodies.

Build54800 complete140916440/1409166c0/14093a930/14093a990:677B/168instr.
Actual variadic error construction, TLS runtime helpers, error augmentation,
current backend methods and memory/global identities remain required.
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_PREFLIGHT, _BUFFERED, _READ, _SEEK = 0x140916440, 0x1409166C0, 0x14093A930, 0x14093A990
_BACKEND, _GUARD, _TEXT = 0x144281D30, 0x14427F154, 0x143DA77F8


@dataclass(frozen=True, slots=True)
class ReplayFileSupportProfile:
    """Explicit live local seeds and optional current engine GS base address.

    preflight68h contains stack5format-home20, partial stack6varargs-home28
    and Result38..67. backend28h contains the live fifth-argument QWORD20.
    gs_base is an explicit engine address, not a detected host/native GS base;
    None refuses only at the reached GS58 read after error-temp cleanup.
    """

    preflight: bytes
    backend: bytes
    gs_base: int | None

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.preflight, 0x68),
                (self.backend, 0x28),
            )
        ):
            raise ValueError("explicit68/28-hex-byte File local seeds required")
        if self.gs_base is not None:
            _unsigned(self.gs_base, 8, "engine GS base")


def _success(context: ReplayTaskRebuildStorage, output: int) -> int:
    for offset in (0, 8, 16, 24, 32):
        _write(context, output + offset, 8, 0)
    _write(context, output + 40, 1, 0)
    return output


def _preflight(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    variadic_calls: ReplayTaskRebuildCalls,
    file: int,
    output: int,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayFileSupportProfile,
) -> int:
    if _read(context, file + 0x54, 1):
        return _success(context, output)
    _write(context, file + 0x48, 4, 0x1F)
    _write(context, file + 0x4C, 4, 0x1F)
    with _local(memoryview(bytearray(profile.preflight)), bind_local) as frame:
        _write(context, frame + 0x28, 4, 0x1F)
        _write(context, frame + 0x20, 8, 0x1431F7B68)
        # Separate effective HOME-LOCATION ABI, not six eager native values.
        _call(
            variadic_calls,
            0x140A08840,
            (
                frame + 0x38,
                0,
                0x1431F7B10,
                0xD7,
                frame + 0x20,
                frame + 0x28,
            ),
        )
        control = _read(context, frame + 0x58, 8)
        if control:
            _release(context, control, calls, atomics)
        _call(calls, 0x1402BD890, (frame + 0x38,))
        if profile.gs_base is None:
            raise UnresolvedReplayTaskRebuild("File preflight reached missing engine GS58 backing")
        array = _read(context, profile.gs_base + 0x58, 8)
        index = _read(context, 0x144C9C828, 4)
        thread = _read(context, array + index * 8, 8)
        epoch = _read(context, thread + 0x3B4, 4)
        if _signed(_read(context, _GUARD, 4), 4) > _signed(epoch, 4):
            _call(calls, 0x142D6BF80, (_GUARD,))
            if _read(context, _GUARD, 4) == 0xFFFFFFFF:
                for offset, width, value in (
                    (0, 4, 0x525B5E71),
                    (4, 4, 0x43585917),
                    (8, 4, 0x52475817),
                    (12, 2, 0x3759),
                ):
                    _write(context, _TEXT + offset, width, value)
                _call(calls, 0x142D6BD04, (0x1430575C0,))
                _call(calls, 0x142D6BF14, (_GUARD,))
        if _read(context, 0x143DA7805, 1):
            for offset in range(14):
                _write(context, _TEXT + offset, 1, _read(context, _TEXT + offset, 1) ^ 0x37)
        _call(calls, 0x1408ED8F0, (output, 0x1431F7B10, 0xB5, _TEXT))
        return output


def _buffered_seek(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    file: int,
    output: int,
    requested: int,
) -> int:
    if requested == _read(context, file + 0x40, 8):
        return _success(context, output)
    _write(context, file + 0x57, 1, 1)
    _write(context, file + 0x40, 8, requested)
    in_window = False
    if requested < _read(context, file + 0x30, 8):
        anchor = _read(context, file + 0x78, 8)
        if requested >= anchor:
            length = _read(context, file + 0x60, 8)
            if requested < (length + anchor) & _U64:
                base = _read(context, file + 0x68, 8)
                _write(context, file + 0x70, 8, base - anchor + requested)
                # Original SUB R9,RDX: length-anchor, not end-requested.
                _write(context, file + 0x58, 8, length - anchor)
                in_window = True
    if not in_window:
        _write(context, file + 0x70, 8, _read(context, file + 0x68, 8))
        _write(context, file + 0x58, 8, 0)
        _write(context, file + 0x78, 8, requested)
        if _read(context, file + 0x28, 8) != _U64:
            _call(calls, _SEEK, (_read(context, file + 0x28, 8), 0, 0, requested))
    return _success(context, output)


def bind_replay_file_support(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    variadic_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayFileSupportProfile,
    backend_home_calls: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Own four complete bodies with mandatory real reached child effects.

    variadic_calls is a separate dispatcher for original140a08840. Its six
    effective arguments are(tempResult,0,sourceFile,line,FORMAT_HOME,VA_LIST_HOME).
    The last two are addresses into the live parent frame, NOT format/code
    values. The actual variadic constructor service must preserve late current
    format QWORD reads and the live va_list pointer, including partial padding.
    Ordinary scalar callers of140a08840 keep their separate Calls contract.
    No error construction or successful missing variadic service is supplied.

    Backend shims hold current global backend BEFORE storing entryarg4 into
    QWORDhome20, then read current vptr/slot38 or40. Native wrapper source has
    no explicit fifth-home LOAD: CALL forwards that stack home to the method.
    The default scalar Calls ABI samples its current VALUE after slot selection,
    retaining the existing route. Explicit backend_home_calls instead receives
    the first4 register values plus the live frame20 ADDRESS, without a wrapper
    home read. That separate dispatcher owns each reached method's HOME ABI and
    must support it or refuse; no scalar-value reinterpretation is permitted.
    The wrapper frame stays bound throughout that call. Read retains full count;
    seek narrows mode to lowDWORD. Both routes transparently forward rawRAX/None
    until an actual consuming caller requires a result. No I/O/backend identity
    is inferred. Buffered seek still ignores backend RAX and writes41B success
    only after its reached backend call returns.

    All source globals/GS/TLS/local/output backing and actual guards, atexit,
    augmentation, atomic/current virtual and vector cleanup remain required.
    No File/global/Result initialization is inferred except reached source
    stores. Earlier effects survive refusal. Physical stack/register identity,
    escaped local pointers, native fault/EH/thread/lock ordering are excluded.
    These bodies do not own large File read/seek or establish replay readiness.
    """
    _validate(context, calls)
    _validate(context, variadic_calls)
    if backend_home_calls is not None:
        _validate(context, backend_home_calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual File atomic/local effects required")
    if not isinstance(profile, ReplayFileSupportProfile):
        raise ValueError("explicit File local/GS profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arity = {_PREFLIGHT: 2, _BUFFERED: 3, _READ: 4, _SEEK: 4}
        if target not in arity:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arity[target] or data is not None:
            raise ValueError("malformed File preflight/buffered/backend call")
        _validate(context, calls, *args)
        if target == _PREFLIGHT:
            return _preflight(
                context,
                bound,
                variadic_calls,
                *args,
                atomics=atomics,
                bind_local=bind_local,
                profile=profile,
            )
        if target == _BUFFERED:
            return _buffered_seek(context, bound, *args)
        with _local(memoryview(bytearray(profile.backend)), bind_local) as frame:
            backend = _read(context, _BACKEND, 8)
            _write(context, frame + 0x20, 8, args[3])
            vptr = _read(context, backend, 8)
            method = _read(context, vptr + (0x38 if target == _READ else 0x40), 8)
            third = args[2] if target == _READ else args[2] & 0xFFFFFFFF
            if backend_home_calls is not None:
                if backend_home_calls.call is None:
                    raise UnresolvedReplayTaskRebuild(
                        f"reached backend HOME method{method:x} is unavailable"
                    )
                return backend_home_calls.call(
                    method,
                    (
                        backend,
                        args[0],
                        args[1],
                        third,
                        (frame + 0x20) & _U64,
                    ),
                    None,
                )
            return dispatch(
                method,
                (
                    backend,
                    args[0],
                    args[1],
                    third,
                    _read(context, frame + 0x20, 8),
                ),
                None,
            )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
