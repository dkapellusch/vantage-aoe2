"""Build54800 nine bounded Player construction supports (1964 original bytes).

Current scalar/local storage and actual reached child effects are mandatory.
Marker XMM3 is a raw binary32 word in an explicit mixed-ABI invocation, never
an inferred integer R9. Native physical stack/register/cookie/fault/EH/thread
and FP status/trap parity are excluded. No Player/World or RNG is fabricated.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .replay_binary32 import multiply_binary32
from .replay_task_containers import _cvtt64
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

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MARKER = 0x14162CD70


@dataclass(frozen=True, slots=True)
class ReplayPlayerSupportScratch:
    """Explicit markerB8 and reindex48 logical frame seeds.

    Marker RBP=frame+A1, Results58/88, rawBYTE50, output home48. Its native
    incoming fifth BYTE is an explicit entry operand, captured before threshold
    work; physical home/cookie aliases are excluded. Reindex uses current40
    DWORD writes preserving highword44, then current staged QWORD30 rereads.
    """

    marker: bytes
    reindex: bytes

    def __post_init__(self) -> None:
        if type(self.marker) is not bytes or len(self.marker) != 0xB8:
            raise ValueError("explicit B8-byte Player marker frame required")
        if type(self.reindex) is not bytes or len(self.reindex) != 0x48:
            raise ValueError("explicit48-byte Player resource frame required")


@dataclass(frozen=True, slots=True)
class ReplayPlayerMarkerCall:
    """Native RCX/RDX/R8, lowXMM3 and stack5 BYTE, with no integer R9 claim."""

    output: int
    stream: int
    label: int
    xmm3_u32: int
    expected_u8: int

    def __post_init__(self) -> None:
        for value in (self.output, self.stream, self.label):
            _unsigned(value, 8, "Player marker pointer")
        _unsigned(self.xmm3_u32, 4, "Player marker lowXMM3")
        _unsigned(self.expected_u8, 1, "Player marker expected byte")


@dataclass(frozen=True, slots=True)
class ReplayPlayerSupportFloatingCalls:
    """Actual mixed-ABI dispatcher, unavailable until reached if None."""

    call: Callable[[int, ReplayPlayerMarkerCall], int | None] | None

    def __post_init__(self) -> None:
        if self.call is not None and not callable(self.call):
            raise ValueError("actual Player mixed-FP call provider required")


def construct_replay_player_array(
    context: ReplayTaskRebuildStorage,
    address: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """147B141712b50; saturated allocation and separately wrapped memset size."""
    _validate(context, calls, address, capacity)
    count = _signed(capacity & _U32, 4) & _U64
    for offset in (0x30, 0x40, 0x50):
        _write(context, address + offset, 16, 0)
    for offset in (0x20, 0x28):
        _write(context, address + offset, 8, 0)
    _write(context, address + 0x60, 4, _U32)
    _write(context, address + 0x18, 4, 2)
    _write(context, address + 0x64, 4, 0)
    allocated = _call(calls, 0x142D6C268, (min(count * 8, _U64),), width=8)
    _write(context, address + 0x68, 8, allocated)
    _call(calls, 0x142D6E3B7, (allocated, 0, count * 8 & _U64))
    _write(context, address + 4, 8, 0)
    _write(context, address + 12, 8, 0)
    _write(context, address, 4, count)
    return address


def release_replay_player_hash_buckets(
    context: ReplayTaskRebuildStorage,
    ignored_header: int,
    begin: int,
    count: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """85B140c2d4d0, ignored RCX; current Watson IAT goes terminal once."""
    _validate(context, calls, ignored_header, begin, count)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    size = count * 8 & _U64
    pointer = begin
    if size >= 0x1000:
        base = _read(context, begin - 8, 8)
        size = size + 0x27 & _U64
        if (begin - base - 8) & _U64 > 0x1F:
            target = _read(context, 0x14319A060, 8)
            _call(terminal, target, (0, 0, 0, 0, 0))
            raise UnresolvedReplayTaskRebuild("Player hash Watson returned before native INT3")
        pointer = base
    _call(calls, 0x142D6BAB4, (pointer, size))


def construct_replay_player_hash(
    context: ReplayTaskRebuildStorage,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """238B140c2ae90; real node/bucket allocations, held sentinel/current headers.

    The alternate REP arm is unreachable with the source's initialized RDI0
    and native nonvolatile-register premise. The normal body fills16 QWORDs.
    """
    _validate(context, calls, address)
    _write(context, address, 4, 0)
    _write(context, address + 8, 8, 0)
    _write(context, address + 16, 8, 0)
    node = _call(calls, 0x142D6BA78, (24,), width=8)
    _write(context, node, 8, node)
    _write(context, node + 8, 8, node)
    _write(context, address + 8, 8, node)
    for offset, value in ((24, 0), (32, 0), (40, 0), (48, 7), (56, 8)):
        _write(context, address + offset, 8, value)
    _write(context, address, 4, 0x3F800000)
    sentinel = _read(context, address + 8, 8)
    buckets = _call(calls, 0x142D6BA78, (128,), width=8)
    old = _read(context, address + 24, 8)
    count = (_signed((_read(context, address + 40, 8) - old) & _U64, 8) >> 3) & _U64
    if count:
        _call(calls, 0x140C2D4D0, ((address + 24) & _U64, old, count))
    end = buckets + 128 & _U64
    _write(context, address + 24, 8, buckets)
    _write(context, address + 32, 8, end)
    _write(context, address + 40, 8, end)
    for index in range(16):
        _write(context, buckets + index * 8, 8, sentinel)
    return address


def construct_replay_player_rows(
    context: ReplayTaskRebuildStorage,
    address: int,
    owner: int,
    count: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> int:
    """74B14115d200; lowR8D sign extension, current calloc and ordered fields."""
    _validate(context, calls, address, owner, count)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    held_count = _signed(count & _U32, 4) & _U64
    target = _read(context, 0x143199DC0, 8)
    pointer = _call(terminal, target, (held_count, 32), width=8)
    _write(context, address + 16, 8, pointer)
    _write(context, address + 8, 4, held_count)
    _write(context, address + 12, 4, 0)
    _write(context, address, 8, owner)
    return address


def construct_replay_player_dual_arrays(
    context: ReplayTaskRebuildStorage,
    address: int,
    owner: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """167B141143df0; current count/pointers after allocations, copy/free/commit."""
    _validate(context, calls, address, owner)
    _write(context, address, 8, owner)
    for offset in (8, 16, 24):
        _write(context, address + offset, 8, 0)
    first = _call(calls, 0x142D6C268, (0x1800,), width=8)
    second = _call(calls, 0x142D6C268, (0x100,), width=8)
    count = _signed(_read(context, address + 12, 4), 4)
    if count > 0:
        source = _read(context, address + 16, 8)
        _call(calls, 0x142D6E3B1, (first, source, count * 24 & _U64))
        count = _signed(_read(context, address + 12, 4), 4)
        source = _read(context, address + 24, 8)
        _call(calls, 0x142D6E3B1, (second, source, count & _U64))
    previous = _read(context, address + 16, 8)
    if previous:
        _call(calls, 0x142D6C270, (previous,))
    previous = _read(context, address + 24, 8)
    if previous:
        _call(calls, 0x142D6C270, (previous,))
    _write(context, address + 24, 8, second)
    _write(context, address + 16, 8, first)
    _write(context, address + 8, 4, 256)
    return address


def count_replay_player_world_entries(context: ReplayTaskRebuildStorage, address: int) -> int:
    """19B141603ef0; end770 read BEFORE begin768, wrapped subtraction/SAR4."""
    _validate(context, ReplayTaskRebuildCalls(None), address)
    end = _read(context, address + 0x770, 8)
    begin = _read(context, address + 0x768, 8)
    return (_signed((end - begin) & _U64, 8) >> 4) & _U64


def construct_replay_player_list(context: ReplayTaskRebuildStorage, address: int) -> int:
    """24B141227140; exact8/8/2 stores leave six padding bytes untouched."""
    _validate(context, ReplayTaskRebuildCalls(None), address)
    _write(context, address, 8, 0x1432B3DA8)
    _write(context, address + 8, 8, 0)
    _write(context, address + 16, 2, 0)
    return address


def reindex_replay_player_resources(
    context: ReplayTaskRebuildStorage,
    address: int,
    count: int,
    *,
    bind_local: LocalBinding,
    scratch: bytes,
) -> None:
    """380B140fddce0, current table words, wrapping signed arithmetic and cipher.

    Null Player returns before any binding/read. Finite coherent admitted loops
    are required; current static-table backing is read at each source phase.
    """
    _validate(context, ReplayTaskRebuildCalls(None), address, count)
    if not address:
        return
    if not callable(bind_local) or type(scratch) is not bytes or len(scratch) != 0x48:
        raise ValueError("explicit48-byte resource frame and live binding required")
    limit = _signed(count & _U32, 4)
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        for pair in range(0x143296810, 0x143296850, 8):
            current = _read(context, pair, 4)
            if _signed(current, 4) >= _signed((current + 8) & _U32, 4):
                continue
            origin = previous = current
            while True:
                difference = (current - origin) & _U32
                correction = 7 if difference & 0x80000000 else 0
                adjusted = difference + correction & _U32
                remainder = (adjusted & 7) - correction
                quotient = _signed(adjusted, 4) >> 3
                target = (_read(context, pair + 4, 4) + quotient * 25 + remainder + 1) & _U32
                held = previous
                if _signed(target, 4) < limit and _signed(current, 4) < limit:
                    table = _read(context, address + 0x98, 8)
                    old_index, new_index = _signed(current, 4), _signed(target, 4)
                    _write(context, frame + 0x40, 4, 0)
                    seed = _read(context, frame + 0x40, 8)
                    value = _read(context, table + old_index * 8, 8)
                    _write(context, table + new_index * 8, 8, value)
                    table = _read(context, address + 0x98, 8)
                    _write(context, frame + 0x30, 8, seed)
                    for operation, literal in (
                        ("xor", 0xA9834B738A7DD167),
                        ("add", 0x042AC42976FCCEF5),
                        ("xor", 0xC22D6B496D833977),
                        ("xor", 0x6AE24D3352F04511),
                    ):
                        value = _read(context, frame + 0x30, 8)
                        value = value + literal if operation == "add" else value ^ literal
                        _write(context, frame + 0x30, 8, value)
                    _write(context, frame + 0x30, 8, _read(context, frame + 0x30, 8))
                    _write(context, table + old_index * 8, 8, _read(context, frame + 0x30, 8))
                    origin = _read(context, pair, 4)
                    held = origin
                previous = held
                current = current + 1 & _U32
                if _signed(current, 4) >= _signed((held + 8) & _U32, 4):
                    break


def _clean(
    context: ReplayTaskRebuildStorage,
    result: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD890, (result,))


def _success(context: ReplayTaskRebuildStorage, output: int) -> None:
    for offset in (0, 8, 16, 24, 32):
        _write(context, output + offset, 8, 0)
    _write(context, output + 40, 1, 0)


def _decode_marker_detail(
    context: ReplayTaskRebuildStorage,
    pointer: int,
    flag: int,
    tail: int,
) -> None:
    if _read(context, pointer + flag, 1):
        mask = _read(context, 0x1431F7FA0, 16)
        for offset in range(0, 80, 16):
            _write(context, pointer + offset, 16, _read(context, pointer + offset, 16) ^ mask)
        for offset in range(80, 80 + tail):
            _write(context, pointer + offset, 1, _read(context, pointer + offset, 1) ^ 0x9C)


def read_replay_player_marker(
    context: ReplayTaskRebuildStorage,
    invocation: ReplayPlayerMarkerCall,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
    mxcsr: int,
) -> int:
    """Full830B14162cd70 mixed-FP caller; unknown metadata children are required."""
    _validate(context, calls)
    if not isinstance(invocation, ReplayPlayerMarkerCall):
        raise ValueError("explicit mixed-FP Player marker invocation required")
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual marker atomics and live local binding required")
    if type(scratch) is not bytes or len(scratch) != 0xB8:
        raise ValueError("explicit B8-byte marker frame required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("Player marker requires masked default MXCSR1f80")
    output, stream = invocation.output, invocation.stream
    expected = invocation.expected_u8  # Native entry captures stack5 BYTE in R14B.
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        _write(context, frame + 0x48, 8, output)
        factor = _read(context, 0x143235268, 4)
        threshold = _cvtt64(multiply_binary32(invocation.xmm3_u32, factor)) & _U32
        version = _read(context, 0x1440A0D94, 4)
        if _signed(version, 4) < _signed(threshold, 4):
            _success(context, output)
            return output
        forwarded, raw = frame + 0x58, frame + 0x88
        for result in (forwarded, raw):
            for offset in (0, 16, 32):
                _write(context, result + offset, 16, 0)
        target = _read(context, _read(context, stream, 8) + 24, 8)
        _call(calls, target, (stream, raw, frame + 0x50, 1))
        for offset in (0, 16, 32):
            _write(context, forwarded + offset, 16, 0)
        _write(context, raw + 40, 1, 1)
        if _read(context, raw + 24, 8):
            _call(calls, 0x140900ED0, (raw, 0x1432351D0, 0x21, 0x143235228))
        _call(calls, 0x1409076B0, (forwarded, raw))
        _clean(context, raw, calls, atomics)
        if _read(context, forwarded + 24, 8):
            first = _call(calls, 0x14162F810, (frame + 0x40,), width=8)
            _decode_marker_detail(context, first, 0x59, 10)
            second = _call(calls, 0x14162E8D0, (frame + 0x40,), width=8)
            _decode_marker_detail(context, second, 0x53, 4)
            _call(calls, 0x140900ED0, (forwarded, second, 0x21, first))
            _call(calls, 0x1409076B0, (output, forwarded))
            _clean(context, forwarded, calls, atomics)
            return output
        _write(context, forwarded + 40, 1, 1)
        _clean(context, forwarded, calls, atomics)
        got = _read(context, frame + 0x50, 1)
        if got == expected:
            _success(context, output)
        else:
            _write(context, frame + 0x38, 4, expected)
            _write(context, frame + 0x30, 4, got)
            _write(context, frame + 0x28, 8, invocation.label)
            _write(context, frame + 0x20, 8, 0x143235238)
            _call(
                calls,
                0x140A08840,
                (output, 0, 0x1432351D0, 0x26, 0x143235238, invocation.label, got, expected),
            )
        return output


def bind_replay_player_construction_support(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    scratch: ReplayPlayerSupportScratch,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Eight scalar entries; current imported targets bypass owned body tokens."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not callable(bind_local) or not isinstance(scratch, ReplayPlayerSupportScratch):
        raise ValueError("explicit Player support local bindings and seeds required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x141712B50: 2,
            0x140C2AE90: 1,
            0x140C2D4D0: 3,
            0x14115D200: 3,
            0x141143DF0: 2,
            0x141603EF0: 1,
            0x141227140: 1,
            0x140FDDCE0: 2,
        }
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed scalar Player construction support call")
        if target == 0x141712B50:
            return construct_replay_player_array(context, *args, calls=bound)
        if target == 0x140C2AE90:
            return construct_replay_player_hash(context, *args, calls=bound)
        if target == 0x140C2D4D0:
            release_replay_player_hash_buckets(context, *args, calls=bound, imports=terminal)
        elif target == 0x14115D200:
            return construct_replay_player_rows(context, *args, calls=bound, imports=terminal)
        elif target == 0x141143DF0:
            return construct_replay_player_dual_arrays(context, *args, calls=bound)
        elif target == 0x141603EF0:
            return count_replay_player_world_entries(context, *args)
        elif target == 0x141227140:
            return construct_replay_player_list(context, *args)
        else:
            reindex_replay_player_resources(
                context, *args, bind_local=bind_local, scratch=scratch.reindex
            )
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound


def bind_replay_player_marker(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    floating: ReplayPlayerSupportFloatingCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerSupportScratch,
    mxcsr: int,
) -> ReplayPlayerSupportFloatingCalls:
    """Concrete selected marker body in a genuine mixed-ABI dispatcher."""
    _validate(context, calls)
    if not isinstance(floating, ReplayPlayerSupportFloatingCalls):
        raise ValueError("explicit Player floating dispatcher required")
    if not isinstance(scratch, ReplayPlayerSupportScratch) or not callable(bind_local):
        raise ValueError("explicit Player marker local seed/provider required")
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("actual marker atomics and masked default MXCSR1f80 required")

    def dispatch(target: int, invocation: ReplayPlayerMarkerCall) -> int | None:
        _unsigned(target, 8, "Player marker target")
        if target != _MARKER:
            if floating.call is None:
                raise UnresolvedReplayTaskRebuild(f"mixed-FP target{target:x} is unavailable")
            return floating.call(target, invocation)
        return read_replay_player_marker(
            context,
            invocation,
            calls=calls,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch.marker,
            mxcsr=mxcsr,
        )

    return ReplayPlayerSupportFloatingCalls(dispatch)
