"""Build54800 initial UnitAI variant constructors and saved-reader callers.

Source: initial-ai-variant-source-review-v1 and retained ai-and-shared ASM.
Normal caller phases require actual common/stream/cleanup descendants. This
is not a complete native error/EH/fault implementation or saved World restore.
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics
from .replay_unit_ai_saved import _output, _record, _release_result, _request

_U64 = (1 << 64) - 1
_MASTER_SUBS = (0x6A586EB28AC201FC, 0x0CF19788B2554E70)
_CLASS_ADDS = (-0x50A06BCECEBEF905, 0x5B32AA7995D95916)
_COMMON_CLASSES = (0x143239D80, 0x143239D70, 0x143239DA0, 0x143239D90, 0x143239D60, 0x143239DB0)
_CONSTRUCTORS = {
    0x140CEE930: (
        0x143245A58,
        (0x14324AC60, 0x14324ABD0, 0x14324ACD0, 0x14324AD00, 0x14324AD40, 0x14324ADB0, 0x14324ADE0),
        (),
    ),
    0x140CEE750: (0x143245F18, (), ()),
    0x140CEEC20: (0x143246178, (0x14324AC50, 0x14324ACC0, 0x14324AD10, 0x14324ADD0), (57, 9)),
    0x140CEE630: (
        0x143246898,
        (
            0x14324ABC0,
            0x14324AC10,
            0x14324AD50,
            0x14324AE20,
            0x14324AC80,
            0x143239D70,
            0x14324ACA0,
            0x14324AD20,
            0x14324ADA0,
            0x14324ADF0,
        ),
        (66, 67),
    ),
    0x140CEF230: (
        0x143247490,
        (*_COMMON_CLASSES, 0x14324AD80, 0x14324ACF0, 0x14324ADE0, 0x14324AE40),
        (67,),
    ),
    0x140CEE510: (
        0x143247E18,
        (*_COMMON_CLASSES, 0x143239DD0, 0x143239DE0, 0x143239DC0, 0x14324AE30),
        (67,),
    ),
    0x140CEED70: (0x1432482D8, (), ()),
}


@dataclass(frozen=True, slots=True)
class ReplayUnitAIVariantScratch:
    """Explicit whole-local backing; native metadata/register/cookie slots excluded."""

    constructor: bytes
    ai4: bytes
    ai17: bytes

    def __post_init__(self) -> None:
        for value, size in ((self.constructor, 0x140), (self.ai4, 0xC0), (self.ai17, 0xD0)):
            if type(value) is not bytes or len(value) != size:
                raise ValueError("explicit0x140/0xc0/0xd0-byte variant local seeds required")


def _decode_local(
    context: ReplayTaskRebuildStorage,
    local: int,
    source: int,
    additions: tuple[int, ...],
    *,
    duplicate: bool = False,
) -> int:
    _write(context, local, 8, _read(context, source, 8))
    for addition in additions:
        _write(context, local, 8, (_read(context, local, 8) + addition) & _U64)
    value = _read(context, local, 8)
    if duplicate:
        _write(context, local, 8, value)
        value = _read(context, local, 4)
    return value


def _master(context: ReplayTaskRebuildStorage, subject: int, local: int) -> int:
    return _decode_local(context, local, subject + 16, tuple(-v for v in _MASTER_SUBS))


def _kind(context: ReplayTaskRebuildStorage, subject: int, local: int) -> int:
    master = _master(context, subject, local)
    return _decode_local(context, local, master + 0x38, _CLASS_ADDS) & 0xFFFF


def _coordinates(
    context: ReplayTaskRebuildStorage,
    address: int,
    subject: int,
    local: int,
) -> None:
    for destination, source, additions in (
        (0x1F8, 0x170, (-0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1)),
        (0x1FC, 0x178, (-0x61501AA6ECFD980A, 0x6C5EAB60B426DD28)),
        (0x200, 0x180, (0x2B3719EF44DE99FF, 0x21D14A25ED7C802C)),
    ):
        word = _decode_local(context, local, subject + source, additions, duplicate=True)
        _write(context, address + destination, 4, word)


def _player_mode(
    context: ReplayTaskRebuildStorage,
    subject: int,
    calls: ReplayTaskRebuildCalls,
) -> int:
    return _call(calls, 0x14172AC80, (_read(context, subject + 24, 8),), width=4)


def _construct_ai13_tail(
    context: ReplayTaskRebuildStorage,
    address: int,
    subject: int,
    frame: int,
    calls: ReplayTaskRebuildCalls,
) -> None:
    local = frame + 0x128
    if _player_mode(context, _read(context, address + 8, 8), calls):
        _write(context, local, 4, 10)
        _call(calls, 0x1402B89C0, (address + 0x198, local))
    held_kind = _kind(context, subject, local)
    mode = _player_mode(context, _read(context, address + 8, 8), calls)
    _call(calls, 0x140D19DD0, (address, 1500 if mode else 500))

    def master_id() -> int:
        master = _master(context, subject, local)
        _write(context, local, 8, _read(context, master + 24, 8))
        _write(context, local, 8, _read(context, local, 8) ^ 0x349E37847AD69F19)
        _write(context, local, 8, (_read(context, local, 8) - 0x47E37DFF0616CE4F) & _U64)
        return _read(context, local, 8) & 0xFFFF

    flag: int | None = None
    if not _player_mode(context, subject, calls):
        for special in (0x20F, 0x210, 0x450):
            if master_id() == special:
                flag = 1
                break
    if flag is None:
        if not _player_mode(context, subject, calls) and held_kind in (35, 64):
            flag = 3
        else:
            first = _read(context, _master(context, subject, local) + 0x379, 1)
            if first & 9:
                second = _read(context, _master(context, subject, local) + 0x379, 1)
                if (
                    _signed(second, 1) >= 0
                    or not _read(context, _master(context, subject, local) + 0x379, 1) & 8
                ):
                    flag = 1
            if flag is None:
                if _kind(context, subject, local) == 61:
                    flag = 3
                else:
                    player = _read(context, subject + 24, 8)
                    target = _read(context, _read(context, player, 8) + 0x90, 8)
                    flag = _call(calls, target, (player,), width=8) & 255
    _write(context, address + 0x1B1, 1, flag)


def construct_replay_initial_unit_ai(
    context: ReplayTaskRebuildStorage,
    entry: int,
    address: int,
    subject: int,
    mode: int,
    *,
    calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Complete scalar phases of seven actual initial-AI constructors.

    Each original entry selects its verified constants and stores. The common
    constructor and reached class append/current virtuals are mandatory. Class
    descriptor/range and reused scalar slots share coherent live local backing;
    no constructor RAX is substituted for the held destination. Private native
    metadata, register saves, original stack identity, faults and EH are excluded.
    """
    _validate(context, calls, entry, address, subject, mode)
    if entry not in _CONSTRUCTORS:
        raise ValueError("unsupported initial UnitAI constructor entry")
    if type(scratch) is not bytes or len(scratch) != 0x140 or not callable(bind_local):
        raise ValueError("explicit0x140-byte constructor local seed and binding required")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        _call(calls, 0x140D094C0, (address, subject, mode, 7 if entry == 0x140CEE630 else 0))
        table, sources, suffix = _CONSTRUCTORS[entry]
        if entry in (0x140CEE750, 0x140CEED70):
            _write(context, address + 0x1B1, 1, int(entry == 0x140CEED70))
        _write(context, address, 8, table)
        if entry == 0x140CEE930:
            _write(context, address + 0x204, 4, 0)
        elif entry == 0x140CEE630:
            _write(context, address + 0x1F8, 4, 4500)
        elif entry == 0x140CEE510:
            for offset in (0x1F8, 0x200, 0x208):
                _write(context, address + offset, 8, 0)
        if sources:
            begin = frame + 0x30
            for index, source in enumerate(sources):
                _write(context, begin + index * 16, 16, _read(context, source, 16))
            for index, value in enumerate(suffix):
                _write(context, begin + len(sources) * 16 + index * 4, 4, value)
            size = len(sources) * 16 + len(suffix) * 4
            _write(context, frame + 0x20, 8, begin)
            _write(context, frame + 0x28, 8, (begin + size) & _U64)
            _call(calls, 0x140CEFB30, (address + 0x198, frame + 0x20))
        if entry == 0x140CEE930:
            _call(calls, 0x140D19DD0, (address, 4000))
            _coordinates(context, address, subject, frame + 0xB8)
            if _kind(context, subject, frame + 0xB8) == 59:
                _write(context, address + 0x1B1, 1, 0)
            current = _read(context, address + 8, 8)
            target = _read(context, _read(context, current, 8) + 0x860, 8)
            _write(context, address + 0x204, 4, _call(calls, target, (current,), width=4))
        elif entry == 0x140CEE750:
            _coordinates(context, address, subject, frame + 0x30)
            _write(context, address + 0x204, 2, 0)
        elif entry == 0x140CEEC20:
            game = _read(context, 0x144353698, 8)
            world = _call(calls, 0x140D6ACC0, (game,), width=8)
            if _read(context, world + 0x6B4, 4) == 1:
                for kind in (47, 18, 13, 55):
                    _write(context, frame + 0xA8, 4, kind)
                    _call(calls, 0x1402B89C0, (address + 0x198, frame + 0xA8))
            _write(context, address + 0x1B1, 1, 0)
            _call(calls, 0x140D19DD0, (address, 6000))
        elif entry in (0x140CEE630, 0x140CEE510):
            _write(context, address + 0x1B1, 1, 0)
        elif entry == 0x140CEF230:
            _construct_ai13_tail(context, address, subject, frame, calls)
        return address


def read_replay_saved_unit_ai4(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Normal140cf9460; unconditional common cleanup, versioned thirteen-byte tail.

    The common Result is not zeroed or checked here before its actual call and
    cleanup. Four later requests share one live48B local. Current version is
    read after cleanup; older versions preserve all derived fields. The final
    output writes fiveQWORDs and oneBYTE, retaining its trailing seven bytes.
    """
    _validate(context, calls, address, output, stream)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual variant atomic/local effects required")
    if type(scratch) is not bytes or len(scratch) != 0xC0:
        raise ValueError("explicit0xc0-byte AI4 local seed required")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        result = frame + 0x68
        _write(context, frame + 0x60, 8, output)
        _call(calls, 0x140D267D0, (address, result, stream))
        _release_result(context, result, 0x1402BD7F0, calls, atomics)
        if _signed(_read(context, 0x1440A0D94, 4), 4) >= 0xD0F5C:
            for offset, width in ((0x1F8, 4), (0x1FC, 4), (0x200, 4), (0x204, 1)):
                _request(
                    context, stream, result, address + offset, width, calls, atomics, 0x1402BD7F0
                )
        return _output(context, output)


def read_replay_saved_unit_ai17(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Normal140cf8f00, including positive52B appends and current count/end effects.

    Common status is not checked. The shared Result/count/record slots retain
    their original offsets and lifetime; only the count's lowDWORD is cleared.
    Row padding45..47 keeps the explicit seed until a stream effect changes it.
    """
    _validate(context, calls, address, output, stream)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual variant atomic/local effects required")
    if type(scratch) is not bytes or len(scratch) != 0xD0:
        raise ValueError("explicit0xd0-byte AI17 local seed required")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        count, result, descriptor = frame + 0x28, frame + 0x30, frame + 0x60
        _write(context, count, 8, output)
        _call(calls, 0x140D267D0, (address, result, stream))
        _release_result(context, result, 0x1402BD7F0, calls, atomics)
        if _signed(_read(context, 0x1440A0D94, 4), 4) >= 0x3E6666:
            _write(context, count, 4, 0)
            _request(context, stream, result, count, 4, calls, atomics, 0x1402BD7F0)
            index = 0
            if _signed(_read(context, count, 4), 4) > 0:
                floats = _read(context, 0x14324ABA0, 16)
                first = _read(context, 0x14324B1D0, 16)
                while True:
                    _record(context, descriptor, first, floats)
                    _request(context, stream, result, descriptor, 52, calls, atomics, 0x1402BD7F0)
                    vector = address + 0x1F8 & _U64
                    end = _read(context, vector + 8, 8)
                    if end == _read(context, vector + 16, 8):
                        _call(calls, 0x140CEDD60, (vector, end, descriptor))
                    else:
                        for offset, width in ((0, 16), (16, 16), (32, 16), (48, 4)):
                            _write(
                                context,
                                end + offset,
                                width,
                                _read(context, descriptor + offset, width),
                            )
                        _write(context, vector + 8, 8, _read(context, vector + 8, 8) + 52)
                    index = index + 1 & 0xFFFFFFFF
                    if _signed(index, 4) >= _signed(_read(context, count, 4), 4):
                        break
        return _output(context, output)


def bind_replay_unit_ai_variants(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayUnitAIVariantScratch,
) -> ReplayTaskRebuildCalls:
    """Bind seven constructors, two readers and verified game/player getter leaves.

    Original entry identity selects each body. Common construction, class
    assignment/append, timer virtuals, stream and other actual callbacks remain
    required, with unknown identities delegated unchanged or refused.
    """
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual variant atomic/local effects required")
    if not isinstance(scratch, ReplayUnitAIVariantScratch):
        raise ValueError("explicit variant local seeds required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        constructors = target in _CONSTRUCTORS
        reader = target in (0x140CF9460, 0x140CF8F00)
        getter = target in (0x140D6ACC0, 0x14172AC80)
        if not (constructors or reader or getter):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (1 if getter else 3) or data is not None:
            raise ValueError("malformed UnitAI variant call")
        _validate(context, calls, *args)
        if target == 0x140D6ACC0:
            return _read(context, args[0] + 0x5C0, 8)
        if target == 0x14172AC80:
            return int(_read(context, args[0] + 16, 4) == 3)
        if constructors:
            return construct_replay_initial_unit_ai(
                context,
                target,
                *args,
                calls=bound,
                bind_local=bind_local,
                scratch=scratch.constructor,
            )
        body = read_replay_saved_unit_ai4 if target == 0x140CF9460 else read_replay_saved_unit_ai17
        seed = scratch.ai4 if target == 0x140CF9460 else scratch.ai17
        return body(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=seed
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
