"""Normal build54800 DE string reader140a1bdf0 over actual current storage.

The complete2157B source proves the normal two-WORD header and byte-payload
flow. Input virtuals, free/growth, Result forwarding/cleanup and shared control
effects remain mandatory. Reached error-metadata/TLS branches refuse with
prior effects intact. Native stack/cookies, faults/EH and concurrency are excluded.
"""

from __future__ import annotations

from contextlib import ExitStack
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


@dataclass(frozen=True, slots=True)
class ReplayDEStringSavedScratch:
    """Explicit initial contents of the two native uninitialized WORD locals."""

    signature: bytes
    length: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != 2 for value in (self.signature, self.length)
        ):
            raise ValueError("explicit signature/length2B saved-string scratch required")


def read_replay_de_string_saved(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayDEStringSavedScratch,
) -> int:
    """Execute all normal branches of140a1bdf0; return the held output address.

    Capacity is read before pointer and both must be nonzero to free/reset.
    Both header reads are mandatory. Either WORD can contain sentinel0xa60;
    the other supplies unsigned length. Zero length skips payload and all
    terminator/length stores, preserving what prior source phases left behind.
    Results and WORD locals stay live through the call. No successful I/O or
    cleanup is inferred from their explicit source initialization.
    """
    _validate(context, calls, address, output, stream)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(scratch, ReplayDEStringSavedScratch)
    ):
        raise ValueError("actual saved-string atomics/local bindings and WORD seeds required")
    if _read(context, address + 16, 8):
        pointer = _read(context, address, 8)
        if pointer:
            _call(calls, 0x142D6C270, (pointer,))
            _write(context, address, 8, 0x14428BB30)
            _write(context, address + 16, 8, 0)
            _write(context, address + 8, 8, 0)
    with ExitStack() as locals_:
        signature = locals_.enter_context(
            _local(memoryview(bytearray(scratch.signature)), bind_local)
        )
        length_word = locals_.enter_context(
            _local(memoryview(bytearray(scratch.length)), bind_local)
        )
        result_a = locals_.enter_context(_local(memoryview(bytearray(48)), bind_local))
        result_b = locals_.enter_context(_local(memoryview(bytearray(48)), bind_local))

        def zero(result: int) -> None:
            for offset in (0, 16, 32):
                _write(context, result + offset, 16, 0)

        def release_and_clear(result: int) -> None:
            control = _read(context, result + 32, 8)
            if control:
                _release(context, control, calls, atomics)
            _call(calls, 0x1402BD890, (result,))

        def header(destination: int, name: str) -> None:
            zero(result_a)
            zero(result_b)
            table = _read(context, stream, 8)
            target = _read(context, table + 0x18, 8)
            _call(calls, target, (stream, result_b, destination, 2))
            zero(result_a)
            _write(context, result_b + 40, 1, 1)
            if _read(context, result_b + 24, 8):
                raise UnresolvedReplayTaskRebuild(f"DE string {name} read error metadata frontier")
            _call(calls, 0x1409076B0, (result_a, result_b))
            release_and_clear(result_b)
            if _read(context, result_a + 24, 8):
                raise UnresolvedReplayTaskRebuild(f"DE string {name} forwarded-error frontier")
            _write(context, result_a + 40, 1, 1)
            release_and_clear(result_a)

        header(signature, "signature")
        header(length_word, "length")
        signature_value = _read(context, signature, 2)
        if signature_value == 0xA60:
            length = _read(context, length_word, 2)
        elif _read(context, length_word, 2) == 0xA60:
            _write(context, length_word, 2, signature_value)
            length = signature_value
        else:
            raise UnresolvedReplayTaskRebuild("DE string header signature TLS/error frontier")
        if length:
            _call(calls, 0x140A1A5E0, (address, length + 1))
            zero(result_a)
            table = _read(context, stream, 8)
            destination = _read(context, address, 8)
            target = _read(context, table + 0x18, 8)
            _call(calls, target, (stream, result_a, destination, length))
            if _read(context, result_a + 24, 8):
                raise UnresolvedReplayTaskRebuild("DE string payload read TLS/error frontier")
            _write(context, result_a + 40, 1, 1)
            release_and_clear(result_a)
            destination = _read(context, address, 8)
            _write(context, destination + length, 1, 0)
            _write(context, address + 8, 8, length)
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
    return output


def bind_replay_de_string_saved(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayDEStringSavedScratch,
) -> ReplayTaskRebuildCalls:
    """Bind the normal reader; retain real child/input effects and error refusals."""
    _validate(context, calls)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(scratch, ReplayDEStringSavedScratch)
    ):
        raise ValueError("actual saved-string atomics/local bindings and WORD seeds required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != 0x140A1BDF0:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 3 or data is not None:
            raise ValueError("malformed DE string saved read call")
        return read_replay_de_string_saved(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
