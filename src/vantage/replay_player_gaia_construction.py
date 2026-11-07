"""Complete3160B Gaia outer14174fa70, finite sequential normal effects.

The208B coherent logical seed retains current homes and the uninitialized
Input Result. Actual Derived, Input, forwarding, allocation, finalization and
shared-count providers remain mandatory. Native cookie/protection, physical
stack, faults/EH/concurrency and whole restoration are not modeled.
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


@dataclass(frozen=True, slots=True)
class ReplayPlayerGaiaScratch:
    """Explicit postRSP20h..efh seed, including all current source homes."""

    frame: bytes

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 208:
            raise ValueError("explicit208-byte Gaia outer logical frame required")


@dataclass(frozen=True, slots=True)
class ReplayPlayerGaiaProfile:
    """A supplied budget bounds aliases that reset the mutable loop counter.

    Indexes must remain nonnegative and allow a signed nonwrapping increment.
    Domain refusals retain prior effects; they do not emulate native overflow,
    infinite loops, physical stack aliases or fault/unwind completion.
    """

    maximum_list_iterations: int

    def __post_init__(self) -> None:
        value = self.maximum_list_iterations
        if type(value) is not int or not 0 <= value <= 0x7FFFFFFF:
            raise ValueError("explicit0..7fffffff Gaia list-iteration budget required")


class _ReturnedStatus(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _Input:
    width: int
    destination: str
    offset: int
    vptr_first: bool
    manual: bool
    check: bool = True


_INPUTS = {
    0x14174FC5F: _Input(4, "field", 0x13F0, True, True),
    0x14174FCF5: _Input(4, "field", 0x13F4, True, True),
    0x14174FD98: _Input(4, "local", 0xE8, True, False),
    0x14174FE05: _Input(4, "local", 0xE8, True, False),
    0x14174FED5: _Input(4, "loop", 0x1400, False, True),
    0x14174FF74: _Input(4, "loop", 0x1404, False, True),
    0x141750013: _Input(4, "loop", 0x1408, False, True),
    0x1417500E1: _Input(4, "home", 0x88, True, True),
    0x141750174: _Input(4, "home", 0x90, True, False),
    0x1417501E1: _Input(4, "home", 0x98, True, False),
    0x14175024E: _Input(4, "home", 0xA0, True, False),
    0x1417502BB: _Input(36, "home", 0xA8, True, False),
    0x141750328: _Input(36, "home", 0xB0, True, False),
    0x1417503CF: _Input(4, "held8", 0, True, False),
    0x14175043C: _Input(40, "home", 0xB8, True, False),
    0x1417504A8: _Input(4, "held12", 0, True, False),
    0x141750515: _Input(4, "home", 0xC0, True, False),
    0x141750582: _Input(200, "home", 0xC8, True, False),
    0x1417505EE: _Input(4, "held13", 0, True, False),
    0x141750657: _Input(40, "home", 0xD0, True, False, False),
}

# Literal ordered initialization effects; home values are relative to entrythis.
# The actual first16B store is14174fae0, qualifying old catalog's fade typo.
_INITIAL = (
    ("field", 0, 8, 0x1432F6C88),
    ("field", 0x13F0, 8, 0),
    ("field", 0x13F8, 16, 0),
    ("field", 0x1408, 16, 0),
    ("field", 0x1418, 16, 0),
    ("field", 0x1428, 16, 0),
    ("field", 0x1438, 16, 0),
    ("field", 0x1448, 16, 0),
    ("field", 0x1458, 16, 0),
    ("field", 0x1468, 8, 0),
    ("home", 0x88, 8, 0x1474),
    ("field", 0x1474, 4, 0),
    ("home", 0x90, 8, 0x1478),
    ("field", 0x1478, 4, 0),
    ("home", 0x98, 8, 0x147C),
    ("field", 0x147C, 4, 0),
    ("home", 0xA0, 8, 0x1480),
    ("field", 0x1480, 4, 0),
    ("home", 0xA8, 8, 0x1484),
    ("field", 0x1484, 4, 0),
    ("field", 0x1488, 16, 0),
    ("field", 0x1498, 16, 0),
    ("home", 0xB0, 8, 0x14A8),
    ("field", 0x14A8, 4, 0),
    ("field", 0x14AC, 16, 0),
    ("field", 0x14BC, 16, 0),
    ("home", 0x70, 8, 0x14CC),
    ("field", 0x14CC, 4, 0),
    ("home", 0xB8, 8, 0x14D0),
    ("field", 0x14D0, 16, 0),
    ("field", 0x14E0, 16, 0),
    ("field", 0x14F0, 8, 0),
    ("home", 0x78, 8, 0x14F8),
    ("field", 0x14F8, 4, 0),
    ("home", 0xC0, 8, 0x14FC),
    ("field", 0x14FC, 4, 0),
    ("home", 0xC8, 8, 0x1500),
    ("field", 0x1500, 8, 0),
    ("field", 0x1508, 16, 0),
    ("field", 0x1518, 16, 0),
    ("memset", 0x1528, 0x168, 0),
    ("home", 0x80, 8, 0x1690),
    ("field", 0x1690, 4, 0),
    ("home", 0xD0, 8, 0x1694),
    ("field", 0x1694, 16, 0),
    ("field", 0x16A4, 16, 0),
    ("field", 0x16B4, 8, 0),
    ("field", 0x16BC, 4, _U32),
    ("field", 0x16C0, 8, 0),
    ("field", 0x16C8, 8, 0),
    ("field", 0x16D0, 8, 0),
    ("field", 0x10, 4, 2),
    ("field", 0x1470, 1, 0),
)


@dataclass(slots=True)
class _Gaia:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics
    subject: int
    output: int
    stream: int
    frame: int
    profile: ReplayPlayerGaiaProfile
    wire_index: int = 0
    held8: int = 0
    held12: int = 0
    held13: int = 0

    def local(self, offset: int) -> int:
        return (self.frame + offset - 0x20) & _U64

    def home(self, offset: int, width: int = 8) -> int:
        return _read(self.context, self.local(offset), width)

    def put(self, offset: int, width: int, value: int) -> None:
        _write(self.context, self.local(offset), width, value)

    def invoke(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def version(self) -> int:
        return _signed(_read(self.context, 0x1440A0D94, 4), 4)

    def initialize(self) -> None:
        for kind, offset, width, value in _INITIAL:
            if kind == "home":
                self.put(offset, width, self.subject + value)
            elif kind == "field":
                _write(self.context, self.subject + offset, width, value)
            else:
                self.invoke(0x142D6E3B7, self.subject + offset, value, width)

    def destination(self, spec: _Input) -> int:
        if spec.destination == "field":
            return (self.subject + spec.offset) & _U64
        if spec.destination == "local":
            return self.local(spec.offset)
        if spec.destination == "home":
            return self.home(spec.offset)
        if spec.destination == "loop":
            return (self.home(0x68) + spec.offset + 8 * self.wire_index) & _U64
        if spec.destination == "held8":
            return self.held8
        if spec.destination == "held12":
            return self.held12
        return self.held13

    def input(self, site: int) -> None:
        spec = _INPUTS[site]
        if spec.vptr_first:
            table = _read(self.context, self.stream, 8)
            destination = self.destination(spec)
        else:
            destination = self.destination(spec)
            table = _read(self.context, self.stream, 8)
        # CALL[rax+18] reads the slot only AFTER the remaining current setup.
        target = _read(self.context, table + 24, 8)
        returned = self.invoke(
            target, self.stream, self.local(0x38), destination, spec.width, result=True
        )
        if spec.manual:
            _write(self.context, returned + 40, 1, 1)
            self.invoke(0x14090D270, self.output + 24, returned + 24)
            if self.output != returned:
                begin = _read(self.context, returned, 8)
                end = _read(self.context, returned + 8, 8)
                count = (_signed((end - begin) & _U64, 8) >> 5) & _U64
                self.invoke(0x1402B9080, self.output, begin, count)
            _write(self.context, self.output + 40, 1, 0)
        else:
            self.invoke(0x140991CE0, self.output, returned)
        control = self.home(0x58)
        if control:
            _release(self.context, control, self.calls, self.atomics)
        self.invoke(0x1402BD890, self.local(0x38))
        if spec.check and _read(self.context, self.output + 24, 8):
            raise _ReturnedStatus

    @staticmethod
    def index_domain(index: int) -> None:
        if not 0 <= index <= 0x7FFFFFFE:
            raise UnresolvedReplayTaskRebuild("Gaia counter negative/wrapping profile frontier")

    def lists(self) -> None:
        index, iterations = 0, 0
        self.put(0x30, 4, 0)
        cursor = (self.subject + 0x1400) & _U64
        while True:
            self.index_domain(index)
            if iterations >= self.profile.maximum_list_iterations:
                raise UnresolvedReplayTaskRebuild("Gaia list-iteration budget exhausted")
            iterations += 1
            allocated = self.invoke(0x142D6BA78, 24, result=True)
            self.put(0xE0, 8, allocated)
            if allocated:
                _write(self.context, allocated, 16, 0)
                _write(self.context, allocated + 16, 8, 0)
                allocated = self.invoke(0x141227140, allocated, result=True)
            _write(self.context, cursor - 8, 8, allocated)
            if self.version() > 0x911EB:
                self.wire_index = 3 * _signed(index, 4)
                for site in (0x14174FED5, 0x14174FF74, 0x141750013):
                    self.input(site)
                index = self.home(0x30, 4)
                self.index_domain(index)
            else:
                _write(self.context, cursor, 4, 0)
                _write(self.context, cursor + 8, 4, 0)
            index += 1
            self.put(0x30, 4, index)
            cursor = (cursor + 24) & _U64
            if index >= 5:
                break

    def body(self, world: int, index_pointer: int) -> None:
        self.put(0x68, 8, self.subject)
        self.put(0xD8, 8, self.subject)
        index = _read(self.context, index_pointer, 4)
        self.put(0x30, 4, index)
        self.put(0x20, 8, self.local(0x30))
        self.invoke(0x1416C2440, self.subject, self.output, self.stream, world, self.local(0x30))
        self.initialize()
        self.input(0x14174FC5F)
        self.input(0x14174FCF5)
        if self.version() <= 0x911EB:
            self.input(0x14174FD98)
            self.input(0x14174FE05)
        self.lists()
        version = self.version()
        if version >= 0x9F851:
            for site in (
                0x1417500E1,
                0x141750174,
                0x1417501E1,
                0x14175024E,
                0x1417502BB,
                0x141750328,
            ):
                self.input(site)
            self.held8 = self.home(0x70)
            _write(self.context, self.held8, 4, 0)
            self.held12 = self.home(0x78)
            _write(self.context, self.held12, 4, _U32)
            self.held13 = self.home(0x80)
            _write(self.context, self.held13, 4, _U32)
            version = self.version()
        else:
            self.held8 = self.home(0x70)
            self.held12 = self.home(0x78)
            self.held13 = self.home(0x80)
        if version > 0x9FAE1:
            for site in (
                0x1417503CF,
                0x14175043C,
                0x1417504A8,
                0x141750515,
                0x141750582,
                0x1417505EE,
                0x141750657,
            ):
                self.input(site)


def construct_replay_saved_gaia_player(
    context: ReplayTaskRebuildStorage,
    subject: int,
    output: int,
    stream: int,
    world: int,
    index_pointer: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerGaiaScratch,
    profile: ReplayPlayerGaiaProfile,
) -> int:
    """Only3160B14174fa70; current home68 supplies every common return.

    Returned status shortcuts only after source cleanup; missing effects retain
    preceding writes. Derived return/status is not checked before Gaia work.
    """
    _validate(context, calls, subject, output, stream, world, index_pointer)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Gaia shared-count and local bindings required")
    if not isinstance(scratch, ReplayPlayerGaiaScratch) or not isinstance(
        profile, ReplayPlayerGaiaProfile
    ):
        raise ValueError("explicit Gaia scratch and finite profile required")
    with _local(memoryview(bytearray(scratch.frame)), bind_local) as frame:
        state = _Gaia(context, calls, atomics, subject, output, stream, frame, profile)
        try:
            state.body(world, index_pointer)
        except _ReturnedStatus:
            return state.home(0x68)
        return state.home(0x68)


def bind_replay_saved_gaia_player(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerGaiaScratch,
    profile: ReplayPlayerGaiaProfile,
) -> ReplayTaskRebuildCalls:
    """Bind only actual14174fa70; all reached children delegate unchanged."""
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != 0x14174FA70:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 5 or data is not None:
            raise ValueError("malformed Gaia saved-constructor call")
        return construct_replay_saved_gaia_player(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
            profile=profile,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
