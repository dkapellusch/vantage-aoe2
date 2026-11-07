"""Build54800 UnitAI replacement factory and complete tag15 constructor caller.

Sources: world-restore/native/ai-and-shared/1412ca880 and the verified
tc-unit-ai15-constructor-source-v1. Actual constructor descendants, virtuals,
CRT targets and scoped local backing remain mandatory when reached. This does
not restore a complete saved AI, object or World.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _read,
    _unsigned,
    _write,
)

_U64 = (1 << 64) - 1
# Current jump-table RVA selects an original case entry, not a guessed AI tag.
_BRANCHES = {
    0x1412CAA14: (0x208, 0x140CEE930, 10),
    0x1412CAC94: (0x1F8, 0x140CEEDA0, 10),
    0x1412CAA54: (0x208, 0x140CEE750, 10),
    0x1412CAA94: (0x1F8, 0x140CEEC20, 10),
    0x1412CACD1: (0x1F8, 0x140CEEF40, 10),
    0x1412CAD0E: (0x1F8, 0x140CEEF10, 10),
    0x1412CA994: (0x200, 0x140CEE630, 10),
    0x1412CA9D4: (0x1F8, 0x140CEEE10, 10),
    0x1412CAB14: (0x1F8, 0x140CEF760, 10),
    0x1412CAB54: (0x1F8, 0x140CEF890, 10),
    0x1412CAAD4: (0x1F8, 0x140CEE890, 10),
    0x1412CAC54: (0x1F8, 0x140CEF230, 10),
    0x1412CA954: (0x1F8, 0x140CEE420, 5),
    0x1412CAB94: (0x210, 0x140CEF620, 10),
    0x1412CA8D4: (0x1F8, 0x140CEEFE0, 10),
    0x1412CABD4: (0x210, 0x140CEE510, 10),
    0x1412CA914: (0x1F8, 0x140CEEF70, 10),
    0x1412CAC14: (0x1F8, 0x140CEED70, 5),
}
_CONSTANTS = (
    0x143239D80,
    0x143239D70,
    0x143239DA0,
    0x143239D90,
    0x143239D60,
    0x143239DB0,
    0x14324AD80,
    0x14324ACF0,
    0x14324ADE0,
    0x14324AE00,
)


def _validate(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *values: int,
) -> None:
    if not isinstance(context, ReplayTaskRebuildStorage):
        raise ValueError("explicit current UnitAI storage required")
    if not isinstance(calls, ReplayTaskRebuildCalls):
        raise ValueError("actual UnitAI helper effects required")
    for value in values:
        _unsigned(value, 8, "UnitAI argument")


@contextmanager
def _local(view: memoryview, bind_local: LocalBinding) -> Iterator[int]:
    manager = bind_local(view)
    address = manager.__enter__()
    try:
        _unsigned(address, 8, "bound UnitAI local address")
        yield address
    except BaseException as error:
        manager.__exit__(type(error), error, error.__traceback__)
        raise
    else:
        manager.__exit__(None, None, None)


def replace_replay_unit_ai(
    context: ReplayTaskRebuildStorage,
    subject: int,
    tag: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """Full1412ca880 with current old-AI virtual, jump table and reached effects.

    LowEDX selects2..19. Other values still delete an old AI, then return without
    a final pointer store or table access. Admitted table RVAs name original
    case starts; other selected code targets refuse before allocation. Valid
    arms commit constructor RAX (or null allocation result) only at the end.
    CRT memset return is ignored; the held original allocation reaches the
    constructor. Failures retain earlier effects; native faults/EH are excluded.
    """
    _validate(context, calls, subject, tag)
    previous = _read(context, subject + 0x1F0, 8)
    if previous:
        target = _read(context, _read(context, previous, 8), 8)
        _call(calls, target, (previous, 1))
        _write(context, subject + 0x1F0, 8, 0)
    index = (tag - 2) & 0xFFFFFFFF
    if index > 17:
        return
    branch = 0x140000000 + _read(context, 0x1412CAD60 + index * 4, 4)
    if branch not in _BRANCHES:
        raise UnresolvedReplayTaskRebuild(f"unsupported UnitAI factory branch{branch:x}")
    size, constructor, mode = _BRANCHES[branch]
    allocation = _call(calls, 0x142D6BA78, (size,), width=8)
    result = 0
    if allocation:
        _call(calls, 0x142D6E3B7, (allocation, 0, size))
        result = _call(calls, constructor, (allocation, subject, mode), width=8)
    _write(context, subject + 0x1F0, 8, result)


def construct_replay_unit_ai15(
    context: ReplayTaskRebuildStorage,
    address: int,
    subject: int,
    mode: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
) -> int:
    """Full140cef620 caller; all three descendants must execute actual effects.

    Incoming mode is rawR8, unchanged. Read ten current16B static operands in
    original order; stage168B including immediates66/67. The second child gets
    an address of a LIVE16B begin/end descriptor, whose range is also live.
    Both locals remain mapped through the final virtual-dispatching helper.
    Scoped exits cannot suppress body failures. Raw native stack aliases,
    escaped local use after return, faults/EH and upper-register state are
    excluded. No preservation of fields across later callbacks is inferred.
    """
    _validate(context, calls, address, subject, mode)
    if not callable(bind_local):
        raise ValueError("actual scoped UnitAI local binding required")
    _call(calls, 0x140D094C0, (address, subject, mode, 0))
    _write(context, address, 8, 0x143247958)
    for offset in (0x1F8, 0x200, 0x208):
        _write(context, address + offset, 8, 0)
    values = bytearray()
    for source in _CONSTANTS:
        values += _read(context, source, 16).to_bytes(16, "little")
    values += (66).to_bytes(4, "little") + (67).to_bytes(4, "little")
    with _local(memoryview(values), bind_local) as begin:
        end = (begin + 168) & _U64
        descriptor = bytearray(begin.to_bytes(8, "little") + end.to_bytes(8, "little"))
        with _local(memoryview(descriptor), bind_local) as header:
            _call(calls, 0x140CEFB30, ((address + 0x198) & _U64, header))
            _write(context, address + 0x1B1, 1, 0)
            _call(calls, 0x140D19DD0, (address, 1000))
            return address


def bind_replay_unit_ai_construction(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind factory/AI15 caller and current memset thunk; unknown entries refuse/delegate.

    The memset import is read once at reach and its selected target delegated
    directly, even when it equals the engine's memset primitive identity.
    Known constructors cannot silently fall through to an external success.
    Explicit imports bypass other composed body binders after the IAT read;
    this keeps an engine primitive token from being resolved as a thunk again.
    """
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not callable(bind_local):
        raise ValueError("actual scoped UnitAI local binding required")

    def delegate(
        target: int,
        args: tuple[int, ...],
        data: memoryview | None,
        *,
        imported: bool = False,
    ) -> int | None:
        receiver = terminal if imported else calls
        if receiver.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return receiver.call(target, args, data)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (0x1412CA880, 0x140CEF620, 0x142D6E3B7):
            return delegate(target, args, data)
        arity = 2 if target == 0x1412CA880 else 3
        if len(args) != arity or data is not None:
            raise ValueError("malformed UnitAI construction call")
        if target == 0x1412CA880:
            replace_replay_unit_ai(context, *args, calls=bound)
            return None
        if target == 0x140CEF620:
            return construct_replay_unit_ai15(context, *args, calls=bound, bind_local=bind_local)
        for value in args:
            _unsigned(value, 8, "UnitAI memset argument")
        return delegate(_read(context, 0x143199938, 8), args, None, imported=True)

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
