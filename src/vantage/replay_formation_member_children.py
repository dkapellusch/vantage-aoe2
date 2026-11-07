"""Six complete formation member callers over explicit current storage.

Source: world-formation-member-children-source-v1, 1911B/466 instructions.
Current children, globals and virtuals remain mandatory. The mode2 virtual's
owned Calls result is explicitly raw XMM0 low32, not native RAX. Physical
cookies/saves, EH, fault equivalence and concurrency are outside this profile.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass

from .replay_binary32 import add_binary32, compare_binary32, multiply_binary32
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

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_TAIL, _RECOMPUTE, _LEADER = 0x140B88AF0, 0x1410D9990, 0x1410DC6B0
_REMOVE, _RESERVE, _MODE = 0x1410F6A50, 0x1410F78E0, 0x141252DA0
_GAME, _GET_WORLD, _LOOKUP = 0x144353698, 0x140D6ACC0, 0x141617DB0
_IDS, _COUNTS = 0x144376530, 0x144376600
_MASTER_A, _MASTER_B = 0x6A586EB28AC201FC, 0x0CF19788B2554E70


@dataclass(frozen=True, slots=True)
class ReplayFormationMemberChildrenProfile:
    """Explicit58/40/48h seeds, bound only on reached semantic scratch paths.

    Recompute uses live QWORD50; leader has coherent output homes20 and30;
    mode1 repeatedly uses QWORD40. Unwritten seed bytes remain untouched.
    Physical saves, return homes and the leader cookie/check are excluded.
    Finite backed arrays/lists and progressing nonwrapping indices are required.
    """

    recompute: bytes
    leader: bytes
    mode: bytes

    def __post_init__(self) -> None:
        if any(
            type(seed) is not bytes or len(seed) != size
            for seed, size in (
                (self.recompute, 0x58),
                (self.leader, 0x40),
                (self.mode, 0x48),
            )
        ):
            raise ValueError("explicit58/40/48-hex-byte member scratch seeds required")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


@dataclass(slots=True)
class _Children:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    bind_local: LocalBinding
    profile: ReplayFormationMemberChildrenProfile

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def pointer(self, target: int, *args: int) -> int:
        return _call(self.calls, target, args, width=8)

    def world(self) -> int:
        return self.pointer(_GET_WORLD, self.read(_GAME))

    def finish_master(self, scratch: int) -> int:
        self.write(scratch, 8, self.read(scratch) - _MASTER_A)
        self.write(scratch, 8, self.read(scratch) - _MASTER_B)
        return self.read(scratch)

    def master(self, unit: int, scratch: int) -> int:
        self.write(scratch, 8, self.read(unit + 0x10))
        return self.finish_master(scratch)

    def identifier_tail(self, scratch: int) -> int:
        master = self.finish_master(scratch)
        self.write(scratch, 8, self.read(master + 0x18))
        self.write(scratch, 8, self.read(scratch) ^ 0x349E37847AD69F19)
        self.write(scratch, 8, self.read(scratch) - 0x47E37DFF0616CE4F)
        return _signed(self.read(scratch) & 0xFFFF, 2) & _U32

    def pair(self, source: int, destination: int, offset: int, width: int) -> None:
        value = self.read(source + offset, width)
        self.write(destination + offset, width, value)

    def copy200(self, source: int, destination: int) -> None:
        self.pair(source, destination, 0x00, 16)
        self.pair(source, destination, 0x10, 16)
        self.pair(source, destination, 0x20, 16)
        self.pair(source, destination, 0x30, 16)
        self.pair(source, destination, 0x40, 16)
        self.pair(source, destination, 0x50, 16)
        self.pair(source, destination, 0x60, 16)
        self.pair(source, destination, 0x70, 16)
        self.pair(source, destination, 0x80, 16)
        self.pair(source, destination, 0x90, 16)
        self.pair(source, destination, 0xA0, 16)
        self.pair(source, destination, 0xB0, 16)
        self.pair(source, destination, 0xC0, 8)

    def copy_error(self) -> None:
        error_pointer = self.pointer(self.read(0x14319A058))
        self.write(error_pointer, 4, 0x16)
        _invoke(self.calls, self.read(0x14319A030), ())

    def recompute(self, node: int) -> None:
        _invoke(self.calls, 0x142D6E3B7, (_COUNTS, 0, 0xC8))
        unique_count, unique_index, outer_index, offset = 0, 0, 0, 0
        with ExitStack() as stack:
            frame: int | None = None
            if _signed(self.read(node + 0x14, 4), 4) > 0:
                while True:
                    world = self.world()
                    array = self.read(node + 0x20)
                    identifier = self.read(array + offset, 4)
                    unit = self.pointer(_LOOKUP, world, identifier)
                    if unit:
                        if frame is None:
                            frame = stack.enter_context(
                                _local(
                                    memoryview(bytearray(self.profile.recompute)),
                                    self.bind_local,
                                )
                            )
                        scratch = (frame + 0x50) & _U64
                        match = 0
                        while match < unique_index:
                            self.write(scratch, 8, self.read(unit + 0x10))
                            decoded = self.identifier_tail(scratch)
                            if self.read(_IDS + match * 4, 4) == decoded:
                                address = _COUNTS + match * 4
                                self.write(address, 4, self.read(address, 4) + 1)
                                break
                            match += 1
                        else:
                            self.write(scratch, 8, self.read(unit + 0x10))
                            unique_count = (unique_count + 1) & _U32
                            decoded = self.identifier_tail(scratch)
                            self.write(_IDS + unique_index * 4, 4, decoded)
                            self.write(_COUNTS + unique_index * 4, 4, 1)
                            unique_index += 1
                            if unique_index > 0x32:
                                break
                    outer_index = (outer_index + 1) & _U32
                    offset = (offset + 4) & _U64
                    if _signed(outer_index, 4) >= _signed(self.read(node + 0x14, 4), 4):
                        break
            destination = (node + 0x38) & _U64
            if destination:
                self.copy200(_IDS, destination)
            else:
                self.copy_error()
            destination = (node + 0x100) & _U64
            if destination:
                self.copy200(_COUNTS, destination)
            else:
                self.copy_error()
            self.write(node + 0x34, 4, unique_count)

    def leader(self, group: int) -> None:
        minimum = self.read(0x1436A030C, 4)
        self.write(group + 0xC4, 4, _U32)
        if _signed(self.read(group + 0xE4, 4), 4) <= 0:
            return
        index, offset = 0, 0
        with ExitStack() as stack:
            frame: int | None = None
            while True:
                world = self.world()
                array = self.read(group + 0xF0)
                unit = self.pointer(_LOOKUP, world, self.read(array + offset, 4))
                if unit:
                    vtable = self.read(unit)
                    if frame is None:
                        frame = stack.enter_context(
                            _local(
                                memoryview(bytearray(self.profile.leader)),
                                self.bind_local,
                            )
                        )
                    target = self.read(vtable + 0x568)
                    position = self.pointer(target, unit, (frame + 0x20) & _U64)
                    _invoke(
                        self.calls,
                        0x14096D4D0,
                        (
                            position,
                            (frame + 0x30) & _U64,
                            (group + 0x3D0) & _U64,
                        ),
                    )
                    y = self.read(frame + 0x34, 4)
                    x = self.read(frame + 0x30, 4)
                    z = self.read(frame + 0x38, 4)
                    y2 = multiply_binary32(y, y)
                    x2 = multiply_binary32(x, x)
                    z2 = multiply_binary32(z, z)
                    distance = add_binary32(add_binary32(y2, x2), z2)
                    if compare_binary32(minimum, distance) == 1:
                        identifier = self.read(unit + 8, 4)
                        minimum = distance
                        self.write(group + 0xC4, 4, identifier)
                index = (index + 1) & _U32
                offset = (offset + 4) & _U64
                if _signed(index, 4) >= _signed(self.read(group + 0xE4, 4), 4):
                    break

    def remove(self, header: int, group: int, identifier: int, reference: int) -> int | None:
        identifier, reference = identifier & _U32, reference & _U32
        unit = self.pointer(_LOOKUP, self.world(), identifier)
        if unit:
            other = self.pointer(_LOOKUP, self.world(), reference)
            classification = self.pointer(0x1410D95F0, unit, other) & _U32
            if classification == _U32:
                return 0
            node = self.read(header + 8)
            sentinel = (header + 8) & _U64
            while node != sentinel:
                if self.read(node + 0x10, 4) == classification:
                    return _invoke(self.calls, 0x1410F69C0, (node, group, identifier))
                node = self.read(node)
            return 0
        node = self.read(header + 8)
        sentinel = (header + 8) & _U64
        while node != sentinel:
            count = self.read(node + 0x14, 4)
            index, wide_index = 0, 0
            if _signed(count, 4) > 0:
                array = self.read(node + 0x20)
                while True:
                    if self.read(array + wide_index * 4, 4) == identifier:
                        if _signed(index, 4) < _signed((count - 1) & _U32, 4):
                            offset = wide_index * 4 & _U64
                            while True:
                                current = self.read(node + 0x20)
                                offset = (offset + 4) & _U64
                                index = (index + 1) & _U32
                                value = self.read(current + offset, 4)
                                self.write(current + wide_index * 4, 4, value)
                                wide_index = (wide_index + 1) & _U64
                                bound = (self.read(node + 0x14, 4) - 1) & _U32
                                if _signed(index, 4) >= _signed(bound, 4):
                                    break
                        current = self.read(node + 0x20)
                        self.write(current + wide_index * 4, 4, _U32)
                        self.write(node + 0x14, 4, self.read(node + 0x14, 4) - 1)
                        _invoke(self.calls, _RECOMPUTE, (node,))
                        return 1
                    index = (index + 1) & _U32
                    wide_index = (wide_index + 1) & _U64
                    if _signed(index, 4) >= _signed(count, 4):
                        break
            node = self.read(node)
        return 0

    def reserve(self, node: int, requested: int) -> int:
        requested = _signed(requested & _U32, 4)
        if requested <= 0 or _signed(self.read(node + 0x18, 4), 4) >= requested:
            return 0
        allocation = self.pointer(0x142D6C268, min(requested * 4, _U64))
        if not allocation:
            return 0
        copied = 0
        if self.read(node + 0x20):
            index = 0
            while _signed(copied, 4) < _signed(self.read(node + 0x14, 4), 4):
                source = self.read(node + 0x20)
                copied = (copied + 1) & _U32
                value = self.read(source + index * 4, 4)
                self.write(allocation + index * 4, 4, value)
                index = (index + 1) & _U64
                if index >= requested:
                    break
            _invoke(self.calls, 0x142D6C270, (self.read(node + 0x20),))
        index = _signed(copied, 4)
        while index < requested:
            if _signed(copied, 4) >= _signed(self.read(node + 0x18, 4), 4):
                break
            self.write(allocation + index * 4, 4, _U32)
            copied = (copied + 1) & _U32
            index += 1
        self.write(node + 0x20, 8, allocation)
        self.write(node + 0x18, 4, requested)
        return 1

    def mode(self, unit: int, mode: int) -> int:
        mode &= _U32
        if mode == 2:
            target = self.read(self.read(unit) + 0x220)
            # Explicit owned XMM0-low32 channel, never an inferred RAX result.
            raw = _call(self.calls, target, (unit,), width=4)
            return int(compare_binary32(raw, 0) == 0)
        if mode != 1:
            return int(mode in (3, 4))
        with _local(memoryview(bytearray(self.profile.mode)), self.bind_local) as frame:
            scratch = (frame + 0x40) & _U64
            master = self.master(unit, scratch)
            compared = compare_binary32(0, self.read(master + 0x80, 4))
            if compared is not None and compared >= 0:
                return 0
            master = self.master(unit, scratch)
            compared = compare_binary32(0, self.read(master + 0x78, 4))
            if compared is not None and compared >= 0:
                return 0
            master = self.master(unit, scratch)
            compared = compare_binary32(0, self.read(master + 0x7C, 4))
            return int(compared is None or compared == -1)


def bind_replay_formation_member_children(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    bind_local: LocalBinding,
    profile: ReplayFormationMemberChildrenProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind all six entries; unknown target/args/data/result pass unchanged.

    Incidental RAX of recompute/leader is unowned and represented by None.
    1410f69c0 returns opaquely, including None; ignored child returns are never
    validated. Existing descriptor-tail composition needs explicit routing to
    this one-argument leaf. All reached unowned children remain actual calls.
    """
    _validate(context, calls)
    if not callable(bind_local) or not isinstance(profile, ReplayFormationMemberChildrenProfile):
        raise ValueError("actual local binding and member profile required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("exact masked MXCSR1f80 profile required")
    arities = {_TAIL: 1, _RECOMPUTE: 1, _LEADER: 1, _REMOVE: 4, _RESERVE: 2, _MODE: 2}

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed formation member child call")
        _validate(context, calls, *args)
        subject = args[0]
        if target == _TAIL:
            pointer = _read(context, subject + 0x10, 8)
            return _read(context, pointer, 8) if pointer else 0
        if target == _RECOMPUTE:
            helpers.recompute(subject)
            return None
        if target == _LEADER:
            helpers.leader(subject)
            return None
        if target == _REMOVE:
            return helpers.remove(subject, args[1], args[2], args[3])
        if target == _RESERVE:
            return helpers.reserve(subject, args[1])
        return helpers.mode(subject, args[1])

    bound = ReplayTaskRebuildCalls(dispatch)
    helpers = _Children(context, bound, bind_local, profile)
    return bound
