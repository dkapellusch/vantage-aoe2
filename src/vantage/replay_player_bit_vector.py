"""Build54800 complete Player Boolean-vector assignment and six small helpers.

Source: game-world-count-consumer-source-v1. Live initialized16B iterator and4B
zero locals expose real child addresses. Current headers, returned bit position,
scalar aliases and backward bit read order follow the original ASM. Finite
nonwrapping scalar/bit iteration ranges are admitted; native stack/EH/fault/
concurrency parity and whole Player restoration remain outside this port.
"""

from __future__ import annotations

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

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_MAX = (1 << 62) - 1


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 2) & _U64


def _iterator(begin: int, position: int) -> tuple[int, int]:
    """Source signed64 quotient with floor toward negative infinity."""
    return (begin + (_signed(position, 8) // 32) * 4) & _U64, position & 31


def _advance(word: int, bit: int, count: int) -> tuple[int, int]:
    total = (bit + count) & _U64
    if count & (1 << 63) and bit < (-count & _U64):
        word -= (((~total & _U64) >> 5) + 1) * 4
    else:
        word += (total >> 5) * 4
    return word & _U64, total & 31


def _span_words(begin: int, count: int) -> None:
    if begin + count * 4 > _U64:
        raise ValueError("Player bit words require nonwrapping finite iteration span")


def _backward_span(
    begin_word: int,
    begin_bit: int,
    end_word: int,
    end_bit: int,
    destination_word: int,
    destination_bit: int,
) -> int:
    if end_word < begin_word or (end_word - begin_word) & 3:
        raise ValueError("Player bit insertion requires ordered wholeDWORD iterator range")
    steps = (end_word - begin_word) // 4 * 32 + end_bit - begin_bit
    if steps < 0 or destination_word < max(0, (steps + 31 - destination_bit) // 32) * 4:
        raise ValueError("Player bit insertion requires finite nonwrapping backward range")
    return steps


def _error(calls: ReplayTaskRebuildCalls, target: int) -> None:
    _call(calls, target, ())
    raise UnresolvedReplayTaskRebuild(
        f"nonreturning Player bit error{target:x} returned before INT3"
    )


def raise_replay_player_bit_length(
    context: ReplayTaskRebuildStorage,
    *,
    imports: ReplayTaskRebuildCalls,
    boolean: bool,
) -> None:
    """Whole17B140322090/1402ba820; actual current terminal IAT and source label."""
    _validate(context, imports)
    if type(boolean) is not bool:
        raise ValueError("explicit Boolean/vector terminal selection required")
    _call(imports, _read(context, 0x1431992A0, 8), (0x14367D8E8 if boolean else 0x1436794B0,))
    raise UnresolvedReplayTaskRebuild(
        "nonreturning Player bit length terminal returned before INT3"
    )


def commit_replay_player_bit_words(
    context: ReplayTaskRebuildStorage,
    header: int,
    replacement: int,
    requested: int,
    capacity: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """Whole157B1402ba740: current old allocation frees before held header commit."""
    _validate(context, calls, header, replacement, requested, capacity)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    pointer = _read(context, header, 8)
    if pointer:
        size = (_read(context, header + 16, 8) - pointer) & (_U64 - 3)
        if size >= 0x1000:
            base = _read(context, pointer - 8, 8)
            size = (size + 0x27) & _U64
            if (pointer - base - 8) & _U64 > 31:
                _call(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
                raise UnresolvedReplayTaskRebuild(
                    "nonreturning Player bit Watson returned before INT3"
                )
            pointer = base
        _call(calls, 0x142D6BAB4, (pointer, size))
    _write(context, header, 8, replacement)
    _write(context, header + 8, 8, replacement + requested * 4)
    _write(context, header + 16, 8, replacement + capacity * 4)


def append_replay_player_bit_words(
    context: ReplayTaskRebuildStorage,
    begin: int,
    count: int,
    source: int,
    ignored_owner: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """Whole88B140321870; source branch read occurs even for empty append."""
    _validate(context, calls, begin, count, source, ignored_owner)
    if _read(context, source, 4) == 0:
        size = count * 4 & _U64
        _call(calls, 0x142D6E3B7, (begin, 0, size))
        return (begin + size) & _U64
    _span_words(begin, count)
    for _ in range(count):
        _write(context, begin, 4, _read(context, source, 4))
        begin += 4
    return begin


def resize_replay_player_bit_words(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Whole347B140321420; source/current memmove/actual commit ordering intact."""
    _validate(context, calls, header, requested, source)
    old_end = _read(context, header + 8, 8)
    begin = _read(context, header, 8)
    old_size = _count(old_end, begin)
    if requested < old_size:
        _write(context, header + 8, 8, begin + requested * 4)
        return
    if requested == old_size:
        return
    capacity = _count(_read(context, header + 16, 8), begin)
    if requested <= capacity:
        end = _call(
            calls, 0x140321870, (old_end, (requested - old_size) & _U64, source, header), width=8
        )
        _write(context, header + 8, 8, end)
        return
    if requested > _MAX:
        _error(calls, 0x1402BA820)
    half = capacity >> 1
    if capacity > (_MAX - half) & _U64:
        growth = _MAX
    else:
        growth = max((capacity + half) & _U64, requested)
        if growth > _MAX:
            _error(calls, 0x1402A9460)
    replacement = _call(calls, 0x1402A94D0, (growth * 4 & _U64,), width=8)
    count = (requested - old_size) & _U64
    tail = (replacement + old_size * 4) & _U64
    if _read(context, source, 4) == 0:
        _call(calls, 0x142D6E3B7, (tail, 0, count * 4 & _U64))
    else:
        _span_words(tail, count)
        for _ in range(count):
            _write(context, tail, 4, _read(context, source, 4))
            tail += 4
    current_begin = _read(context, header, 8)
    current_end = _read(context, header + 8, 8)
    _call(calls, 0x142D6E3DB, (replacement, current_begin, (current_end - current_begin) & _U64))
    _call(calls, 0x1402BA740, (header, replacement, requested, growth))


def insert_replay_player_bits(
    context: ReplayTaskRebuildStorage,
    header: int,
    iterator: int,
    count: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
) -> int:
    """Whole430B1403209e0; live zero local and backward destination-before-source."""
    _validate(context, calls, header, iterator, count)
    if not callable(bind_local):
        raise ValueError("actual Player bit local binding required")
    position = (_count(_read(context, iterator, 8), _read(context, header, 8)) << 5) & _U64
    position = (position + _read(context, iterator + 8, 8)) & _U64
    if not count:
        return position
    bit_count = _read(context, header + 24, 8)
    if ((1 << 63) - 1 - bit_count) & _U64 < count:
        _error(calls, 0x140322090)
    with _local(memoryview(bytearray(4)), bind_local) as zero:
        _write(context, zero, 4, 0)
        words = ((count + 31 + bit_count) & _U64) >> 5
        _call(calls, 0x140321420, (header, words, zero))
        bit_count = _read(context, header + 24, 8)
        if not bit_count:
            _write(context, header + 24, 8, count)
            return position
        begin = _read(context, header, 8)
        old_word, old_bit = _iterator(begin, bit_count)
        new_count = (bit_count + count) & _U64
        _write(context, header + 24, 8, new_count)
        new_word, new_bit = _iterator(begin, new_count)
        first_word, first_bit = _iterator(begin, position)
        steps = _backward_span(first_word, first_bit, old_word, old_bit, new_word, new_bit)
        for _ in range(steps):
            if old_bit:
                old_bit -= 1
            else:
                old_bit = 31
                old_word = (old_word - 4) & _U64
            if new_bit:
                new_bit -= 1
            else:
                new_bit = 31
                new_word = (new_word - 4) & _U64
            destination = _read(context, new_word, 4)
            source = _read(context, old_word, 4)
            mask = 1 << new_bit
            _write(
                context,
                new_word,
                4,
                destination | mask if source & (1 << old_bit) else destination & ~mask,
            )
        return position


def assign_replay_player_bits(
    context: ReplayTaskRebuildStorage,
    header: int,
    count: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
) -> None:
    """Whole376B1416e4c30; actual insert return and held Boolean fill across memset."""
    _validate(context, calls, header, count, source)
    if not callable(bind_local):
        raise ValueError("actual Player bit local binding required")
    begin = _read(context, header, 8)
    if begin != _read(context, header + 8, 8):
        _write(context, header + 8, 8, begin)
    with _local(memoryview(bytearray(16)), bind_local) as iterator:
        _write(context, iterator, 8, begin)
        _write(context, header + 24, 8, 0)
        _write(context, iterator + 8, 8, 0)
        position = _call(calls, 0x1403209E0, (header, iterator, count), width=8)
        current_begin = _read(context, header, 8)
        first_word, first_bit = _iterator(current_begin, position)
        if not count:
            return
        end_word, end_bit = _advance(first_word, first_bit, count)
        boolean = _read(context, source, 1)
        if (first_word, first_bit) == (end_word, end_bit):
            return
        word = _read(context, first_word, 4)
        start_mask = _U32 << first_bit & _U32
        value_mask = _U32 if boolean else 0
        if first_word == end_word:
            end_mask = _U32 >> ((32 - end_bit) & 31)
            mask = start_mask & end_mask
            _write(context, first_word, 4, (word & ~mask) | (value_mask & mask))
            return
        _write(context, first_word, 4, (word & ~start_mask) | (value_mask & start_mask))
        interior = (first_word + 4) & _U64
        _call(calls, 0x142D6E3B7, (interior, 255 if boolean else 0, (end_word - interior) & _U64))
        if end_bit:
            end_mask = _U32 >> ((32 - end_bit) & 31)
            word = _read(context, end_word, 4)
            _write(context, end_word, 4, (word & ~end_mask) | (value_mask & end_mask))


def bind_replay_player_bit_vector(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind seven complete bodies; actual allocator/CRT/fatal effects delegate."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not callable(bind_local):
        raise ValueError("actual Player bit local binding required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x1416E4C30: 3,
            0x1403209E0: 3,
            0x140321420: 3,
            0x140321870: 4,
            0x1402BA740: 4,
            0x140322090: 0,
            0x1402BA820: 0,
        }
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Player bit vector call")
        _validate(context, calls, *args)
        if target == 0x1416E4C30:
            assign_replay_player_bits(context, *args, calls=bound, bind_local=bind_local)
        elif target == 0x1403209E0:
            return insert_replay_player_bits(context, *args, calls=bound, bind_local=bind_local)
        elif target == 0x140321420:
            resize_replay_player_bit_words(context, *args, calls=bound)
        elif target == 0x140321870:
            return append_replay_player_bit_words(context, *args, calls=bound)
        elif target == 0x1402BA740:
            commit_replay_player_bit_words(context, *args, calls=bound, imports=terminal)
        else:
            raise_replay_player_bit_length(context, imports=terminal, boolean=target == 0x140322090)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
