"""Complete Build54800 File Seek caller, 1502B/335 instructions.

Owns1409179e0 only. Actual preflight/buffered/backend, Result append/forward,
variadic construction, details getter, guard/runtime/IAT and cleanup are
mandatory. No File state, native global identity or backend is synthesized.
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

_SEEK, _CPP, _FORMAT = 0x1409179E0, 0x1431F7B10, 0x1431F7B68


@dataclass(frozen=True, slots=True)
class ReplayFileSeekProfile:
    """Explicit live70h semantic stack prefix and optional owned engine GS base.

    Prefix20/28 are live variadic homes;30 is incidental getter RCX backing;
    38 holds entry output;40..6f is the source Result/tail workspace. Native
    stack/cookie/nonvolatile spill identity and asynchronous effects excluded.
    """

    frame: bytes
    gs_base: int | None

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 0x70:
            raise ValueError("explicit70-hex-byte File Seek local seed required")
        if self.gs_base is not None:
            _unsigned(self.gs_base, 8, "engine GS base")


def _initializing(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    profile: ReplayFileSeekProfile,
    guard: int,
) -> bool:
    if profile.gs_base is None:
        raise UnresolvedReplayTaskRebuild("File Seek reached missing engine GS58 backing")
    array = _read(context, profile.gs_base + 0x58, 8)
    index = _read(context, 0x144C9C828, 4)
    thread = _read(context, array + index * 8, 8)
    epoch = _read(context, thread + 0x3B4, 4)
    if _signed(_read(context, guard, 4), 4) <= _signed(epoch, 4):
        return False
    _call(calls, 0x142D6BF80, (guard,))
    return _read(context, guard, 4) == 0xFFFFFFFF


def _registered(calls: ReplayTaskRebuildCalls, guard: int, destructor: int) -> None:
    _call(calls, 0x142D6BD04, (destructor,))
    _call(calls, 0x142D6BF14, (guard,))


def _cleanup(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    result: int,
) -> None:
    control = _read(context, result + 0x20, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD890, (result,))


def _error(
    context: ReplayTaskRebuildStorage,
    variadic_calls: ReplayTaskRebuildCalls,
    frame: int,
    output: int,
    code: int,
) -> None:
    _write(context, frame + 0x28, 4, code)
    _write(context, frame + 0x20, 8, _FORMAT)
    _call(
        variadic_calls,
        0x140A08840,
        (
            output,
            0,
            _CPP,
            0xD7,
            frame + 0x20,
            frame + 0x28,
        ),
    )


def _success(context: ReplayTaskRebuildStorage, output: int) -> None:
    for offset in (0, 8, 16, 24, 32):
        _write(context, output + offset, 8, 0)
    _write(context, output + 40, 1, 0)


def _decode(
    context: ReplayTaskRebuildStorage,
    address: int,
    mask_address: int,
    chunks: int,
    tail: int,
    xor: int,
) -> None:
    # Source loads its vector mask once, then each current16B chunk in order.
    mask = _read(context, mask_address, 16)
    for offset in range(0, chunks * 16, 16):
        _write(context, address + offset, 16, _read(context, address + offset, 16) ^ mask)
    for offset in range(chunks * 16, chunks * 16 + tail):
        _write(context, address + offset, 1, _read(context, address + offset, 1) ^ xor)


def _seek(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    variadic_calls: ReplayTaskRebuildCalls,
    file: int,
    output: int,
    requested: int,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayFileSeekProfile,
) -> int:
    with _local(memoryview(bytearray(profile.frame)), bind_local) as frame:
        result = frame + 0x40
        _write(context, frame + 0x38, 8, output)
        for offset in (0, 16, 32):
            _write(context, result + offset, 16, 0)
        _call(calls, 0x140916440, (file, result))
        if _read(context, result + 0x18, 8):
            guard, text = 0x14427F1BC, 0x143DA7808
            if _initializing(context, calls, profile, guard):
                for offset, value in ((0, 0x0B00152A), (4, 0x06000D26), (8, 0x654C4D0E)):
                    _write(context, text + offset, 4, value)
                _registered(calls, guard, 0x143057940)
            if _read(context, 0x143DA7813, 1):
                for offset in range(12):
                    _write(context, text + offset, 1, _read(context, text + offset, 1) ^ 0x65)
            detail = _call(calls, 0x140913C80, (frame + 0x30,), width=8)
            if _read(context, detail + 0x54, 1):
                _decode(context, detail, 0x1431AB3D0, 5, 5, 0x65)
            _call(calls, 0x140900ED0, (result, detail, 0x13E, text))
            _call(calls, 0x1409076B0, (output, result))
            _cleanup(context, calls, atomics, result)
            return output
        _write(context, result + 0x28, 1, 1)
        _cleanup(context, calls, atomics, result)
        if _read(context, file + 0x80, 4):
            _write(context, file + 0x48, 4, 0x30)
            _write(context, file + 0x4C, 4, 0x30)
            _error(context, variadic_calls, frame, result, 0x30)
            _cleanup(context, calls, atomics, result)
            held = _read(context, 0x1431F8130, 16)
            _write(context, frame + 0x50, 4, 0xD2C4C4D2)
            _write(context, frame + 0x54, 4, 0xDED197D3)
            _write(context, frame + 0x58, 2, 0xD2DB)
            guard, text = 0x14427F1DC, 0x14427F1C0
            if _initializing(context, calls, profile, guard):
                _write(context, text, 16, held)
                _write(context, text + 16, 8, _read(context, frame + 0x50, 8))
                _write(context, text + 24, 2, _read(context, frame + 0x58, 2))
                _write(context, text + 26, 1, 0xB7)
                _registered(calls, guard, 0x143057B10)
            if _read(context, text + 26, 1):
                _decode(context, text, 0x1431AC380, 1, 11, 0xB7)
            _call(calls, 0x1408ED8F0, (output, _CPP, 0x143, text))
            return output
        if requested > _read(context, file + 0x30, 8):
            _write(context, file + 0x48, 4, 0x22)
            _write(context, file + 0x4C, 4, 0x22)
            last_error = _call(calls, _read(context, 0x143198A88, 8), (), width=8)
            _write(context, file + 0x50, 4, last_error)
            _error(context, variadic_calls, frame, result, 0x22)
            _cleanup(context, calls, atomics, result)
            held = _read(context, 0x1431F7ED0, 16)
            _write(context, frame + 0x50, 4, 0x8D8B968B)
            _write(context, frame + 0x54, 2, 0xE28C)
            guard, text = 0x14427F1F8, 0x14427F1E0
            if _initializing(context, calls, profile, guard):
                _write(context, text, 16, held)
                _write(context, text + 16, 4, _read(context, frame + 0x50, 4))
                _write(context, text + 20, 2, _read(context, frame + 0x54, 2))
                _registered(calls, guard, 0x143057C70)
            if _read(context, text + 21, 1):
                _decode(context, text, 0x1431F8200, 1, 6, 0xE2)
            _call(calls, 0x1408ED8F0, (output, _CPP, 0x149, text))
            return output
        if requested != _read(context, file + 0x40, 8):
            if _read(context, file + 0x56, 1):
                _call(calls, 0x1409166C0, (file, output, requested))
                return output
            raw = _call(
                calls,
                0x14093A990,
                (
                    _read(context, file + 0x28, 8),
                    file + 0x40,
                    0,
                    requested,
                ),
                width=8,
            )
            if not raw & 255 or requested != _read(context, file + 0x40, 8):
                _write(context, file + 0x48, 4, 0x20)
                _write(context, file + 0x4C, 4, 0x20)
                last_error = _call(calls, _read(context, 0x143198A88, 8), (), width=8)
                _write(context, file + 0x50, 4, last_error)
                _error(context, variadic_calls, frame, output, 0x20)
                return output
            _write(context, file + 0x48, 4, 0)
        _success(context, output)
        return output


def bind_replay_file_seek(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    variadic_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayFileSeekProfile,
) -> ReplayTaskRebuildCalls:
    """Bind complete1502B1409179e0 with mandatory reached child services.

    variadic_calls original140a08840 uses(tempResult,0,cpp,line,FORMAT_HOME,
    VA_LIST_HOME). Home addresses remain live through child calls; the
    ordinary six-scalar constructor convention is not used or inferred.
    Last-error IAT, all text constants/backing, TLS guards, details getter,
    Result append/forward, controls and final augmentation remain required.
    No error Result/formatting/zero globals or file backend is provided.

    Source41B successful output, temp status/processed/control order, cleanup,
    held/mutated text constants and unsigned positioning are preserved. Frame
    remains live through all descendants and expires after return or refusal.
    Earlier effects survive refusal; no transaction, native faults/EH/thread
    or physical stack/register/spill equivalence is claimed. This does not
    implement File read, complete a World tick or establish replay readiness.
    """
    _validate(context, calls)
    _validate(context, variadic_calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual File Seek atomic/local effects required")
    if not isinstance(profile, ReplayFileSeekProfile):
        raise ValueError("explicit File Seek local/GS profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _SEEK:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 3 or data is not None:
            raise ValueError("malformed File Seek call")
        _validate(context, calls, *args)
        return _seek(
            context,
            bound,
            variadic_calls,
            *args,
            atomics=atomics,
            bind_local=bind_local,
            profile=profile,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
