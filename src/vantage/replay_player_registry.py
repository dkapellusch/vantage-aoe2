"""Build54800 full owner-registry construction and relocated container helpers.

Sources: player-base-final-registry-source-v1. Four new entry profiles use
the exact source-proved resize/release/fill/Action-rehash bodies, with explicit
native child identity routing. Actual allocation/free/current imports and
coherent storage remain required. No initialized Player/World is inferred.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from vantage.replay_action_saved_map import rehash_replay_action_saved_map
from vantage.replay_binary32 import (
    compare_binary32,
    divide_binary32,
    subtract_binary32,
    unsigned64_binary32,
)
from vantage.replay_task_bucket_storage import (
    release_replay_task_byte_buckets,
    release_replay_task_pair_buckets,
    resize_replay_task_byte_buckets,
    resize_replay_task_pair_buckets,
)
from vantage.replay_task_buckets import fill_replay_task_buckets
from vantage.replay_task_containers import ReplayTaskContainerCalls, _cvtt64, _view
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _signed,
    _unsigned,
    _write,
)

_U64 = (1 << 64) - 1


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    mxcsr: int,
    *values: int,
) -> ReplayTaskContainerCalls:
    if not isinstance(context, ReplayTaskRebuildStorage) or not isinstance(
        calls,
        ReplayTaskRebuildCalls,
    ):
        raise ValueError("explicit current registry storage and actual helper calls required")
    for value in values:
        _unsigned(value, 8, "registry raw scalar/address")
    return ReplayTaskContainerCalls(calls.call, mxcsr)


def _relocated(
    calls: ReplayTaskRebuildCalls,
    mxcsr: int,
    targets: dict[int, int],
) -> ReplayTaskContainerCalls:
    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        actual = targets.get(target, target)
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{actual:x} unavailable")
        return calls.call(actual, args, data)

    return ReplayTaskContainerCalls(dispatch, mxcsr)


def resize_replay_player_registry_primary_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    value: int,
    *,
    calls: ReplayTaskRebuildCalls,
    mxcsr: int,
) -> None:
    """Full193B14111bd20: actual R8 VALUE and current allocation/release phases."""
    _validate(context, calls, mxcsr, header, requested, value)
    relocated = _relocated(
        calls,
        mxcsr,
        {
            0x1411526A0: 0x14111C560,
            0x141143790: 0x141119AC0,
        },
    )
    resize_replay_task_pair_buckets(context, header, requested, value, calls=relocated)


def resize_replay_player_registry_secondary_buckets(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    value: int,
    *,
    calls: ReplayTaskRebuildCalls,
    mxcsr: int,
) -> None:
    """Full193B14111bdf0; distinct native release/fill identities are retained."""
    _validate(context, calls, mxcsr, header, requested, value)
    relocated = _relocated(
        calls,
        mxcsr,
        {
            0x141152700: 0x14111C5C0,
            0x141143820: 0x141119B50,
        },
    )
    resize_replay_task_byte_buckets(context, header, requested, value, calls=relocated)


def rehash_replay_player_registry_primary(
    context: ReplayTaskRebuildStorage,
    header: int,
    requested: int,
    *,
    calls: ReplayTaskRebuildCalls,
    mxcsr: int,
) -> None:
    """Full429B14111bf00; no minimum8 and no count10 update.

    Whole byte/edge proof permits reuse of the same DWORD-key Action rehash
    body. The required bucket helper is14111bd20. Finite coherent linked-list
    traversal is required; native malformed-cycle/nontermination is excluded.
    """
    _validate(context, calls, mxcsr, header, requested)
    rehash_replay_action_saved_map(
        context,
        header,
        requested,
        calls=_relocated(calls, mxcsr, {0x14113A360: 0x14111BD20}),
    )


def _converted_request(word: int, threshold: int) -> int:
    offset = 0
    order = compare_binary32(word, threshold)
    if order is not None and order >= 0:
        word = subtract_binary32(word, threshold)
        order = compare_binary32(word, threshold)
        if order is None or order < 0:
            offset = 1 << 63
    return (_cvtt64(word) + offset) & _U64


def construct_replay_player_registry(
    context: ReplayTaskRebuildStorage,
    subject: int,
    raw_rdx: int,
    *,
    calls: ReplayTaskRebuildCalls,
    mxcsr: int,
) -> int:
    """Complete378B141119be0; signedlowEDX held before any current effects.

    All reached children remain real required calls. The low XMM0 ceil result
    and current threshold are raw binary32 words; arithmetic is integer-only
    under masked nearest-even controls, DAZ/FTZoff. Sticky status/upper lanes,
    native faults/EH, physical stack/home aliases and concurrency are excluded.
    Unlisted padding/sentinel payload is untouched. Exceptions retain every
    preceding body/helper effect, without fabricated rollback or later stores.
    """
    _validate(context, calls, mxcsr, subject, raw_rdx)
    held_request = _signed(raw_rdx & 0xFFFFFFFF, 4) & _U64
    _write(context, subject, 4, 0)
    _write(context, subject + 8, 8, 0)
    _write(context, subject + 0x10, 8, 0)
    head = _call(calls, 0x142D6BA78, (0x38,), width=8)
    _write(context, head, 8, head)
    _write(context, head + 8, 8, head)
    _write(context, subject + 8, 8, head)
    for offset in (0x18, 0x20, 0x28):
        _write(context, subject + offset, 8, 0)
    _write(context, subject + 0x30, 8, 7)
    _write(context, subject + 0x38, 8, 8)
    _write(context, subject, 4, 0x3F800000)
    current_head = _read(context, subject + 8, 8)
    _call(calls, 0x14111BD20, ((subject + 0x18) & _U64, 16, current_head))
    total = unsigned64_binary32(_read(context, subject + 0x10, 8))
    word = divide_binary32(total, _read(context, subject, 4))
    ceiling = _call(calls, 0x142D6E453, (word,), width=4)
    requested = max(_converted_request(ceiling, _read(context, 0x1436A0308, 4)), held_request)
    if requested > _read(context, subject + 0x38, 8):
        _call(calls, 0x14111BF00, (subject, requested))
    for offset in (0x40, 0x48, 0x50):
        _write(context, subject + offset, 8, 0)
    _write(context, subject + 0x58, 8, 0x20)
    _write(context, subject + 0x60, 8, 0)
    _write(context, subject + 0x68, 8, 0)
    second = (subject + 0x70) & _U64
    _write(context, second, 4, 0)
    _write(context, second + 8, 8, 0)
    _write(context, second + 0x10, 8, 0)
    head = _call(calls, 0x142D6BA78, (0x58,), width=8)
    _write(context, head, 8, head)
    _write(context, head + 8, 8, head)
    _write(context, second + 8, 8, head)
    for offset in (0x18, 0x20, 0x28):
        _write(context, second + offset, 8, 0)
    _write(context, second + 0x30, 8, 7)
    _write(context, second + 0x38, 8, 8)
    _write(context, second, 4, 0x3F800000)
    current_head = _read(context, second + 8, 8)
    _call(calls, 0x14111BDF0, ((second + 0x18) & _U64, 16, current_head))
    _write(context, subject + 0xB0, 1, 0)
    return subject


def bind_replay_player_registry(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    mxcsr: int,
    bind_local: Callable[[memoryview], AbstractContextManager[int]],
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind ten complete native entries, including four proven child aliases.

    bind_local must expose the actual LIVE8B resize VALUE local through this
    same storage; nested mappings restore unrelated backing. Truthy __exit__
    cannot suppress an error. Current selected ceil/length/Watson targets use
    terminal imports directly, even when their scalar token equals an owned
    entry. The terminal must ALSO implement actual sizedfree142d6bab4: both
    that direct tail and selected Watson targets use this terminal provider.
    No original import/provider identity or fallback success is inferred.
    """
    _validate(context, calls, mxcsr)
    terminal = calls if imports is None else imports
    _validate(context, terminal, mxcsr)
    if not callable(bind_local):
        raise ValueError("actual scoped live8B local address mapping required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target in (0x141119AC0, 0x141119B50):
            if len(args) == 3 and data is None:
                fill_replay_task_buckets(context, *args)
                return None
            if len(args) != 2 or data is None:
                raise ValueError("registry fill requires three addresses or live8B local")
            for value in args:
                _unsigned(value, 8, "registry fill address")
            _view(data, 8)
            manager = bind_local(data)
            address = manager.__enter__()
            try:
                _unsigned(address, 8, "bound registry fill local address")
                fill_replay_task_buckets(context, args[0], args[1], address)
            except BaseException as error:
                manager.__exit__(type(error), error, error.__traceback__)
                raise
            else:
                manager.__exit__(None, None, None)
            return None
        arities = {
            0x141119BE0: 2,
            0x14111BD20: 3,
            0x14111BDF0: 3,
            0x14111BF00: 2,
            0x14111C560: 3,
            0x14111C5C0: 3,
            0x142D6E453: 1,
            0x142D66698: 1,
        }
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed native registry call")
        for value in args:
            _unsigned(value, 8, "registry raw argument")
        if target == 0x141119BE0:
            return construct_replay_player_registry(context, *args, calls=bound, mxcsr=mxcsr)
        if target in (0x14111BD20, 0x14111BDF0):
            resize = (
                resize_replay_player_registry_primary_buckets
                if target == 0x14111BD20
                else resize_replay_player_registry_secondary_buckets
            )
            resize(context, *args, calls=bound, mxcsr=mxcsr)
        elif target == 0x14111BF00:
            rehash_replay_player_registry_primary(context, *args, calls=bound, mxcsr=mxcsr)
        elif target in (0x14111C560, 0x14111C5C0):
            release = (
                release_replay_task_pair_buckets
                if target == 0x14111C560
                else release_replay_task_byte_buckets
            )
            release(context, *args, calls=ReplayTaskContainerCalls(terminal.call, mxcsr))
        elif target == 0x142D6E453:
            _unsigned(args[0], 4, "ceil XMM0 low word")
            return _call(terminal, _read(context, 0x143199EF0, 8), args, width=4)
        else:
            _call(terminal, _read(context, 0x1431992A0, 8), args)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
