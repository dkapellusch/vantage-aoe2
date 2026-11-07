"""Build54800 whole Building constructor14126daa0, five scalar arguments.

Every reached Unit/reader/Result/current callback remains mandatory. Source:
building-saved-reader-source-v1. The logical frame preserves the current late
fifth flag and protected-coordinate temporaries; physical stack/register/EH,
cookies, faults, concurrency and whole World completion are not represented.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_base_saved_registration import _cvtt32
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics
from .replay_unit_construction import _propagate, _step, _stores

_ENTRY = 0x14126DAA0


@dataclass(frozen=True, slots=True)
class ReplayBuildingConstructionScratch:
    """D4-byte seed, including current fifth DWORD atD0 and local Result38.

    Scalar30 and protected decodeB8 retain their actual current backing. The
    constructor materializes only the low32 incoming flag at entry; a later
    child mutation of that declared slot affects the actual gate.
    """

    constructor: bytes

    def __post_init__(self) -> None:
        if type(self.constructor) is not bytes or len(self.constructor) != 0xD4:
            raise ValueError("explicit D4-byte Building constructor seed required")


def construct_replay_building_object(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    opaque: int,
    read_flag: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayBuildingConstructionScratch,
    mxcsr: int,
) -> int:
    """The complete normal caller; inherited and returned errors stay real.

    The optional reader returns a Result identity, while this caller returns
    the subject. COMISS/CVTT use masked MXCSR1f80, DAZ/FTZ off. Unknown children
    delegate/refuse after prior effects; no status or owner/master is inferred.
    """
    _validate(context, calls, address, output, stream, opaque, read_flag)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Building atomic/local providers required")
    if not isinstance(scratch, ReplayBuildingConstructionScratch):
        raise ValueError("explicit Building constructor local seed required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("Building constructor requires masked default MXCSR1f80")
    with _local(memoryview(bytearray(scratch.constructor)), bind_local) as frame:
        _write(context, frame + 0xD0, 4, read_flag & 0xFFFFFFFF)
        _write(context, frame + 0x20, 4, 0)
        _call(calls, 0x1412A5D60, (address, output, stream, opaque, 0))
        _stores(
            context,
            address,
            (
                (0, 8, 0x1432B5FC8),
                *((offset, 8, 0) for offset in (0x828, 0x830, 0x838)),
                (0x84C, 2, 0),
                (0x850, 8, 0),
                (0x858, 4, 0),
                (0x860, 8, 0),
                (0x868, 8, 0),
                (0x898, 8, 0),
                (0x8A0, 4, 0),
                (0x8A4, 2, 0),
                (0x8A6, 1, 1),
                (0x8A8, 8, 0),
                (0x8B0, 8, 0xFFFFFFFFFFFF0000),
                *(
                    (offset, 4, value)
                    for offset, value in (
                        (0x8B8, 0),
                        (0x8BC, 0xFFFFFFFF),
                        (0x8C0, 0),
                        (0x8C4, 0xFFFFFFFF),
                        (0x8C8, 0),
                        (0x8CC, 0xFFFFFFFF),
                    )
                ),
                (0x8D0, 8, 0),
                (0x8D8, 8, 0),
                (0x8F8, 8, 0),
                (0x900, 4, 0),
                (0x904, 1, 0),
                (0x908, 8, 0),
                (0x910, 2, 0),
                (0x914, 8, 0),
                (0x91C, 8, 0),
                (0x924, 8, 0),
                (0x92C, 4, 0),
                (0x930, 8, 1),
                (0x938, 1, 0xFF),
                (0x940, 8, 0),
                (0x948, 1, 0),
                (0x954, 4, 0),
                (0x95C, 1, 0),
                (0x960, 4, 0xFFFFFFFF),
                (0x968, 8, 0),
                (0x970, 8, 0),
                (0x978, 8, 0),
                (0x980, 1, 0),
                *((offset, 8, 0) for offset in (0x988, 0x990, 0x998, 0x9A0)),
                (0x9A8, 8, 32),
                *((offset, 8, 0) for offset in range(0x9B0, 0x9F8, 8)),
            ),
        )
        local = frame + 0x38
        returned = _call(calls, 0x1409076B0, (local, output), width=8)
        _propagate(context, output, local, returned, 0x1402BD890, calls, atomics)
        if _read(context, output + 24, 8):
            return address
        _stores(
            context,
            address,
            (
                *((offset, 8, 0) for offset in (0x870, 0x878, 0x880, 0x888, 0x8E0, 0x8E8)),
                (0x8F0, 4, 0xFFFFFFFF),
                (0x8F4, 2, 0xFFFF),
            ),
        )
        for offset in (0x828, 0x968):
            begin = _read(context, address + offset, 8)
            if begin != _read(context, address + offset + 8, 8):
                _write(context, address + offset + 8, 8, begin)
        if _read(context, frame + 0xD0, 4):
            returned = _call(calls, 0x141297F00, (address, local, stream, opaque), width=8)
            _propagate(context, output, local, returned, 0x1402BD890, calls, atomics)
            if _read(context, output + 24, 8):
                return address
        active = True
        if not _read(context, address + 0x951, 1):
            raw = _read(context, address + 0x900, 4)
            active = bool(raw & 0x7FFFFFFF)
        _write(context, address + 0x1C4, 1, int(active))
        if _call(calls, 0x141285450, (address,), width=1):
            owner = _read(context, address + 0x18, 8)
            recipient = _read(context, owner + 0x78, 8)
            slot = frame + 0xB8
            _write(context, slot, 8, _read(context, address + 0x178, 8))
            _step(context, slot, "-", 0x61501AA6ECFD980A)
            _step(context, slot, "+", 0x6C5EAB60B426DD28)
            _write(context, frame + 0x30, 8, _read(context, slot, 8))
            _write(context, slot, 8, _read(context, address + 0x170, 8))
            _step(context, slot, "-", 0x183CAC30D2441D0E)
            _step(context, slot, "+", 0x4C3FBA69E4EA7FD1)
            _write(context, slot, 8, _read(context, slot, 8))
            y = _cvtt32(_read(context, frame + 0x30, 4))
            x = _cvtt32(_read(context, slot, 4))
            value = _call(calls, 0x14115F0A0, (recipient, address, x, y), width=4)
            _write(context, address + 0x954, 4, value)
        return address


def bind_replay_building_construction(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayBuildingConstructionScratch,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind only the complete five-argument Building caller."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Building atomic/local providers required")
    if not isinstance(scratch, ReplayBuildingConstructionScratch) or mxcsr != 0x1F80:
        raise ValueError("explicit Building constructor seed and MXCSR1f80 required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 5 or data is not None:
            raise ValueError("Building constructor requires five scalar arguments")
        return construct_replay_building_object(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
            mxcsr=mxcsr,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
