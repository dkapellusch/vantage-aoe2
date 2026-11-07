"""Build54800 eight Base Player callers plus the source-proven4B ID getter.

Real current backing and reached helper effects are required. Explicit78/60-byte
logical reader frames preserve current locals; native stack/home/register,
cookie/fault/EH/TLS/concurrency parity is excluded. No World or default resource
identity is inferred. Current imported targets go to the explicit terminal.
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
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_CONTEXT = 0x14425B930
_TABLE = 0x1432F46B0


@dataclass(frozen=True, slots=True)
class ReplayPlayerBaseChildrenScratch:
    """Explicit78-byte byte-reader and60-byte other-reader frame seeds."""

    byte_reader: bytes
    scalar_reader: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.byte_reader, 0x78),
                (self.scalar_reader, 0x60),
            )
        ):
            raise ValueError("explicit78/60-byte Player reader frames required")


def _zero(context: ReplayTaskRebuildStorage, output: int, *, success: bool = False) -> None:
    for offset in (0, 8, 16, 24, 32) if success else (0, 16, 32):
        _write(context, output + offset, 8 if success else 16, 0)
    if success:
        _write(context, output + 40, 1, 0)


def _reader_bindings(
    atomics: ReplayUnitAIMapAtomics, bind_local: LocalBinding, scratch: bytes, size: int
) -> None:
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Player reader atomics/live locals required")
    if type(scratch) is not bytes or len(scratch) != size:
        raise ValueError("explicit Player reader logical frame required")


def _clean(
    context: ReplayTaskRebuildStorage,
    result: int,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
) -> None:
    control = _read(context, result + 32, 8)
    if control:
        _release(context, control, calls, atomics)
    _call(calls, 0x1402BD7F0, (result,))


def read_replay_player_index(
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
    scratch: bytes,
) -> int:
    """748B141711c20 normal typedBYTE to currentDWORD, with reached TLS refusal.

    The child140daf040 is real. Its returned RAX is ignored, fixed Result48 is
    inspected. On status zero, cleanup precedes the current BYTE40 reload.
    Nonzero status reads all three source literals then refuses at GS58.
    """
    _validate(context, calls, output, metadata, line, detail, stream, destination)
    _reader_bindings(atomics, bind_local, scratch, 0x78)
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        _write(context, frame + 0x38, 8, output)
        _zero(context, frame + 0x48)
        _write(context, frame + 0x28, 8, frame + 0x40)
        _write(context, frame + 0x20, 8, stream)
        _call(calls, 0x140DAF040, (frame + 0x48, metadata, line, detail, stream, frame + 0x40))
        if _read(context, frame + 0x60, 8):
            for literal in (0x14325DF50, 0x14325D6D0, 0x14325DE60):
                _read(context, literal, 16)
            raise UnresolvedReplayTaskRebuild(
                "Player index reader reached native GS58/TLS frontier"
            )
        _write(context, frame + 0x70, 1, 1)
        _clean(context, frame + 0x48, calls, atomics)
        _write(context, destination, 4, _read(context, frame + 0x40, 1))
        _zero(context, output, success=True)
    return output


def _scalar_reader(
    context: ReplayTaskRebuildStorage,
    output: int,
    metadata: int,
    line: int,
    detail: int,
    stream: int,
    destination: int,
    *,
    delegated: bool,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    _validate(context, calls, output, metadata, line, detail, stream, destination)
    _reader_bindings(atomics, bind_local, scratch, 0x60)
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        _write(context, frame + 0x28, 8, output)
        raw = frame + 0x30
        _zero(context, raw)
        if delegated:
            _call(calls, 0x140E6A9C0, (raw, stream, destination))
        else:
            table = _read(context, stream, 8)
            target = _read(context, table + 24, 8)
            _call(calls, target, (stream, raw, destination, 4))
        _zero(context, output)
        _write(context, raw + 40, 1, 1)
        if _read(context, raw + 24, 8):
            _call(calls, 0x140900ED0, (raw, metadata, line & _U32, detail))
        _call(calls, 0x1409076B0, (output, raw))
        _clean(context, raw, calls, atomics)
    return output


def read_replay_player_delegated_value(
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
    scratch: bytes,
) -> int:
    """245B141712290; actual three-argument140e6a9c0 child, no raw-I/O substitution."""
    return _scalar_reader(
        context,
        output,
        metadata,
        line,
        detail,
        stream,
        destination,
        delegated=True,
        calls=calls,
        atomics=atomics,
        bind_local=bind_local,
        scratch=scratch,
    )


def read_replay_player_name_mode(
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
    scratch: bytes,
) -> int:
    """252B141712390; current virtual18 raw4B, actual Result/BD7F0 phases."""
    return _scalar_reader(
        context,
        output,
        metadata,
        line,
        detail,
        stream,
        destination,
        delegated=False,
        calls=calls,
        atomics=atomics,
        bind_local=bind_local,
        scratch=scratch,
    )


def move_replay_player_catalog(
    context: ReplayTaskRebuildStorage,
    destination: int,
    source: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """47B141711bf0; source clear before destination read, including identity."""
    _validate(context, calls, destination, source)
    incoming = _read(context, source, 8)
    _write(context, source, 8, 0)
    previous = _read(context, destination, 8)
    _write(context, destination, 8, incoming)
    if previous:
        _call(calls, 0x141727C80, (destination, previous))
    return destination


def create_replay_player_catalog(
    context: ReplayTaskRebuildStorage,
    output: int,
    count_pointer: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> int:
    """99B141712ae0; actual allocation/zero/constructor result, late current count."""
    _validate(context, calls, output, count_pointer)
    allocated = _call(calls, 0x142D6BA78, (0xB8,), width=8)
    result = 0
    if allocated:
        _call(calls, 0x142D6E3B7, (allocated, 0, 0xB8))
        count = _read(context, count_pointer, 4)
        result = _call(calls, 0x141119BE0, (allocated, count), width=8)
    _write(context, output, 8, result)
    return output


def release_replay_player_catalog(
    context: ReplayTaskRebuildStorage,
    ignored_holder: int,
    address: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> None:
    """280B141727c80; RDXobject held, actual nested destruction and current frees."""
    _validate(context, calls, ignored_holder, address)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not address:
        return
    _call(calls, 0x1417178D0, ((address + 0x70) & _U64,))
    pointer = _read(context, address + 0x40, 8)
    if pointer and _read(context, address + 0x48, 8):
        _call(terminal, _read(context, 0x143199DD0, 8), (pointer,))
    _write(context, address + 0x40, 8, 0)
    pointer = _read(context, address + 0x18, 8)
    if pointer:
        size = (_read(context, address + 0x28, 8) - pointer) & _U64 & ~7
        freed = pointer
        if size >= 0x1000:
            freed = _read(context, pointer - 8, 8)
            size = size + 0x27 & _U64
            if (pointer - freed - 8) & _U64 > 0x1F:
                _call(terminal, _read(context, 0x14319A060, 8), (0, 0, 0, 0, 0))
                raise UnresolvedReplayTaskRebuild("Player catalog Watson returned before INT3")
        _call(calls, 0x142D6BAB4, (freed, size))
        for offset in (0x18, 0x20, 0x28):
            _write(context, address + offset, 8, 0)
    head = _read(context, address + 8, 8)
    tail = _read(context, head + 8, 8)
    _write(context, tail, 8, 0)
    node = _read(context, head, 8)
    while node:
        pointer = _read(context, node + 0x18, 8)
        following = _read(context, node, 8)
        if pointer and _read(context, node + 0x20, 8):
            _call(terminal, _read(context, 0x143199DD0, 8), (pointer,))
        _write(context, node + 0x18, 8, 0)
        _call(calls, 0x142D6BAB4, (node, 0x38))
        node = following
    head = _read(context, address + 8, 8)
    _call(calls, 0x142D6BAB4, (head, 0x38))
    _call(calls, 0x142D6BAB4, (address, 0xB8))


def read_replay_player_civilization_id(context: ReplayTaskRebuildStorage, address: int) -> int:
    """4B140f6bd90; full EAX result, no additional argument or RAX padding claim."""
    _validate(context, ReplayTaskRebuildCalls(None), address)
    return _read(context, address + 0x14, 4)


def set_replay_player_civilization(
    context: ReplayTaskRebuildStorage,
    player: int,
    resource: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """80B14174a0c0; actual no-argument default helper, held ID/current World table."""
    _validate(context, calls, player, resource)
    if not resource:
        resource = _call(calls, 0x140F6AB00, (), width=8)
    index = _call(calls, 0x140F6BD90, (resource,), width=4)
    _write(context, player + 0x6A8, 8, resource)
    world = _read(context, player + 8, 8)
    table = _read(context, world + 0x110, 8)
    value = _read(context, table + _signed(index, 4) * 8, 8)
    _write(context, player + 0x6A0, 8, value)


def set_replay_player_color(
    context: ReplayTaskRebuildStorage,
    player: int,
    color: int,
    *,
    calls: ReplayTaskRebuildCalls,
) -> None:
    """538B14174a2c0; raw integer/current-setting/table phases, no index clamp."""
    _validate(context, calls, player, color)
    initial_zero = _read(context, player + 0x648, 4) == 0
    world = _read(context, player + 8, 8)
    _write(context, player + 0x1F4, 4, color)
    table = _read(context, world + 0xE8, 8)
    selected = _read(context, table + _signed(color & _U32, 4) * 8, 8)
    _write(context, player + 0x200, 8, selected)
    _write(context, player + 0x1F8, 8, selected)
    if not initial_zero:
        mode = _call(calls, 0x140D6A940, (_read(context, 0x144353698, 8),), width=4)
        if mode != 4:
            human = _call(calls, 0x141603D70, (_read(context, player + 8, 8),), width=8)
            if human:
                settings = _read(context, _CONTEXT, 8)
                skip = False
                if settings and _read(context, settings + 0x151, 1):
                    skip = _call(calls, 0x14097FB40, (settings, 0x6A), width=4) != 0
                if not skip:
                    index = _signed(_read(context, player + 0x648, 4), 4)
                    relations = _read(context, human + 0x180, 8)
                    held_world = _read(context, player + 8, 8)
                    relation = _read(context, relations + index, 1)
                    same = _call(calls, 0x141734F30, (player,), width=1)
                    offset = (
                        0
                        if same
                        else 0x18
                        if relation == 0
                        else 0x30
                        if relation == 1
                        else 8
                        if (relation - 3) & 255 <= 1
                        else None
                    )
                    if offset is not None:
                        current = _read(context, held_world + 0xE8, 8)
                        _write(context, player + 0x1F8, 8, _read(context, current + offset, 8))
    settings = _read(context, _CONTEXT, 8)
    override = 0
    if settings and _read(context, settings + 0x151, 1):
        override = _call(calls, 0x14097FB40, (settings, 0x49), width=4)
        settings = _read(context, _CONTEXT, 8)
    palette = _TABLE
    if _read(context, player + 0x648, 4) == 0:
        baseline = 0xFF
    else:
        if settings and _read(context, settings + 0x151, 1):
            mode = _call(calls, 0x14097FB40, (settings, 0x3C), width=4)
            palette = {2: 0x1432F46F0, 1: 0x1432F4730, 3: 0x1432F4770}.get(mode, _TABLE)
        current = _read(context, player + 0x1F8, 8)
        index = _signed(_read(context, current + 4, 4), 4) if current else -1
        baseline = _read(context, palette + index * 4 + 4, 4)
    if override == 1:
        value = _read(context, 0x1440955E5, 1)
        flag = _read(context, 0x1440955E4, 1)
    else:
        if not override:
            value = baseline
        else:
            signed = _signed(override, 4)
            index = min(signed, 16) if signed >= 0 else 0
            value = _read(context, _TABLE + index * 4 - 4, 4)
        flag = _read(context, 0x1444167AF, 1)
    _write(context, player + 0x650, 4, value)
    _write(context, player + 0x654, 4, flag)
    _write(context, player + 0x658, 4, baseline)


def bind_replay_player_base_children(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerBaseChildrenScratch,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind only nine exact entries; all other targets delegate or refuse."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(scratch, ReplayPlayerBaseChildrenScratch):
        raise ValueError("explicit Player child scratch required")
    _reader_bindings(atomics, bind_local, scratch.byte_reader, 0x78)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        arities = {
            0x141711C20: 6,
            0x141712290: 6,
            0x141712390: 6,
            0x141711BF0: 2,
            0x141712AE0: 2,
            0x141727C80: 2,
            0x14174A0C0: 2,
            0x14174A2C0: 2,
            0x140F6BD90: 1,
        }
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed Player Base child call")
        if target in (0x141711C20, 0x141712290, 0x141712390):
            function = {
                0x141711C20: read_replay_player_index,
                0x141712290: read_replay_player_delegated_value,
                0x141712390: read_replay_player_name_mode,
            }[target]
            return function(
                context,
                *args,
                calls=bound,
                atomics=atomics,
                bind_local=bind_local,
                scratch=scratch.byte_reader if target == 0x141711C20 else scratch.scalar_reader,
            )
        if target == 0x141711BF0:
            return move_replay_player_catalog(context, *args, calls=bound)
        if target == 0x141712AE0:
            return create_replay_player_catalog(context, *args, calls=bound)
        if target == 0x141727C80:
            release_replay_player_catalog(context, *args, calls=bound, imports=terminal)
        elif target == 0x14174A0C0:
            set_replay_player_civilization(context, *args, calls=bound)
        elif target == 0x14174A2C0:
            set_replay_player_color(context, *args, calls=bound)
        else:
            return read_replay_player_civilization_id(context, *args)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
