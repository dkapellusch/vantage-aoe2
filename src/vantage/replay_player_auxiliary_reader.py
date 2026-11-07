"""Original auxiliary reader1414aea70, all four normal record families.

This finite sequential current-storage profile preserves78 literal Input setups,
shared live logical locals and current helper/import effects. Each nonzero fixed
Result status refuses at its exact original diagnostic entry. The35008B reader's
diagnostic/TLS/cookie/native stack/EH/fault/concurrency behavior is unimplemented.
Source: player-aux-reader-source-v1 plus this stage's home-alias addendum.
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
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _atomic, _release

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_WINDOW_BYTES = 0xF18
_VERSION = 0x1440A0D94
_CALLOC_IAT = 0x143199DC0
_Operation = tuple[str, str, tuple[tuple[str, int], ...], int, int]


class UnimplementedReplayPlayerAuxiliaryDiagnostic(UnresolvedReplayTaskRebuild):
    """A nonzero local status reached an original, unimplemented diagnostic."""

    def __init__(self, source_entry: int, input_site: int, status: int) -> None:
        self.source_entry, self.input_site, self.status = source_entry, input_site, status
        super().__init__(
            f"unimplemented auxiliary diagnostic{source_entry:x} after Input{input_site:x} "
            f"with status{status:x}"
        )


@dataclass(frozen=True, slots=True)
class ReplayPlayerAuxiliaryReaderScratch:
    """Explicit3864B window [native postRSP28,f40), including holes/homes.

    Logical+0 is reused QWORDhome28, +8 the loopDWORD30, +68h savedQWORD90,
    +70h oldcountDWORD98; Result slots occupy+a0h-28h through+f40h-28h.
    No native cookie/saved-register region or blanket zero seed is inferred.
    """

    frame: bytes

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != _WINDOW_BYTES:
            raise ValueError("explicit3864-byte auxiliary reader logical-window seed required")


@dataclass(frozen=True, slots=True)
class ReplayPlayerAuxiliaryReaderProfile:
    """Explicit finite iteration domain; no target class/build identity inference.

    Current native-width counts still gate each iteration. Aliased index homes
    must remain nonnegative and increments must not wrap signedDWORD. A reset
    index can repeat rows only within this explicit total record budget.
    """

    maximum_records: int

    def __post_init__(self) -> None:
        if type(self.maximum_records) is not int or not 0 <= self.maximum_records <= 33532:
            raise ValueError("explicit auxiliary record budget in0..33532 required")


@dataclass(frozen=True, slots=True)
class _Site:
    result: int
    error: int
    cleanup: int
    operations: tuple[_Operation, ...]


@dataclass(slots=True)
class _Reader:
    context: ReplayTaskRebuildStorage
    address: int
    output: int
    stream: int
    calls: ReplayTaskRebuildCalls
    imports: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics
    frame: int
    profile: ReplayPlayerAuxiliaryReaderProfile
    registers: dict[str, int]
    records: int = 0

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def home(self, native_offset: int, width: int = 8) -> int:
        return self.read(self.frame + native_offset - 0x28, width)

    def put_home(self, native_offset: int, width: int, value: int) -> None:
        self.write(self.frame + native_offset - 0x28, width, value)

    def version(self) -> int:
        return _signed(self.read(_VERSION, 4), 4)

    def calloc(self, count: int, size: int) -> int:
        target = self.read(_CALLOC_IAT)
        return _call(self.imports, target, (count, size), width=8)

    def input(self, site: int) -> None:
        specification = _SITES[site]
        for kind, destination, terms, constant, width in specification.operations:
            value = (sum(self.registers[name] * scale for name, scale in terms) + constant) & _U64
            if kind == "zero":
                self.write(value, width, 0)
            elif kind == "load":
                self.registers[destination] = self.read(value, width)
            elif kind == "signed32":
                self.registers[destination] = _signed(value & _U32, 4) & _U64
            else:
                # Only source arithmetic/value operations are admitted in data.
                if kind != "value":
                    raise ValueError("invalid finite original Input setup operation")
                self.registers[destination] = value & ((1 << (width * 8)) - 1)
        result = (self.frame + specification.result) & _U64
        _call(
            self.calls,
            self.registers["r10"],
            (
                self.registers["rcx"],
                self.registers["rdx"],
                self.registers["r8"],
                self.registers["r9"],
            ),
        )
        status = self.read(result + 0x18)
        if status:
            raise UnimplementedReplayPlayerAuxiliaryDiagnostic(specification.error, site, status)
        self.write(result + 0x28, 1, 1)
        if specification.cleanup == 0:
            _call(self.calls, 0x140900620, (result,))
        elif specification.cleanup == 1:
            _call(self.calls, 0x1408EE150, ((result + 0x18) & _U64,))
            _call(self.calls, 0x1402BD890, (result,))
        else:
            control = self.read(result + 0x20)
            if specification.cleanup == 2:
                # Family3 holds R12, independent of home28 callback mutation.
                self.registers["r12"] = control
                if control:
                    _release(self.context, control, self.calls, self.atomics)
            else:
                # Family4 explicitly reloads CURRENT home28 after strong destroy.
                self.put_home(0x28, 8, control)
                if control and _atomic(self.atomics, control + 8, _U32) == 1:
                    target = self.read(self.read(control))
                    _call(self.calls, target, (control,))
                    weak_control = self.home(0x28)
                    if _atomic(self.atomics, weak_control + 12, _U32) == 1:
                        target = self.read(self.read(weak_control) + 8)
                        _call(self.calls, target, (weak_control,))
            _call(self.calls, 0x1402BD890, (result,))

    def begin_record(self) -> None:
        index = self.registers["rcx"]
        if index > 0x7FFFFFFF:
            raise UnresolvedReplayTaskRebuild(
                "auxiliary loop index outside nonnegative finite profile"
            )
        if self.records >= self.profile.maximum_records:
            raise UnresolvedReplayTaskRebuild("auxiliary record budget exhausted before next row")
        self.records += 1

    def start_loop(self) -> None:
        self.registers["rcx"] = 0
        self.put_home(0x30, 4, 0)

    def advance_index(self) -> int:
        current = self.home(0x30, 4)
        if current >= 0x7FFFFFFF:
            raise UnresolvedReplayTaskRebuild(
                "auxiliary loop index increment outside nonwrap profile"
            )
        index = current + 1
        self.registers["rcx"] = index
        self.put_home(0x30, 4, index)
        return index

    def dynamic(self, header: int, count: int, pointer: int, offset_register: str) -> None:
        base = self.read(self.address + header)
        amount = self.read(base + self.registers[offset_register] + count, 1)
        if amount:
            allocation = self.calloc(amount, 4)
            current_base = self.read(self.address + header)
            self.write(current_base + self.registers[offset_register] + pointer, 8, allocation)

    def legacy_three(self, header: int, offset_register: str, pointers: tuple[int, ...]) -> None:
        amount = self.home(0x98, 4)
        self.put_home(0x90, 8, amount)
        for number, pointer in enumerate(pointers):
            count = amount if number == 0 else self.home(0x90)
            allocation = self.calloc(count, 4)
            current_base = self.read(self.address + header)
            self.write(current_base + self.registers[offset_register] + pointer, 8, allocation)

    def header(self) -> None:
        self.put_home(0x28, 8, self.output)
        self.input(0x1414AEAEA)
        self.input(0x1414AEC82)
        self.registers["r8"] = (self.address + 0x20) & _U64
        self.registers["rcx"] = self.stream
        self.input(0x1414AEE1D if self.version() >= 0x43E666 else 0x1414AEF93)
        self.input(0x1414AF12C)
        self.registers["rsi"] = 4
        version = self.version()
        if version >= 0x963D7:
            self.input(0x1414AF2DC)
            version = self.version()
        self.put_home(0x98, 4, 0)
        self.registers["r13"] = 10
        if version < 0xA6147:
            self.put_home(0x98, 4, 40)
            self.put_home(0x28, 8, 3)
        else:
            self.put_home(0x28, 8, 10)
            if version < 0xAD70A:
                self.put_home(0x98, 4, 100)
                self.put_home(0x28, 8, 10)

    def first(self) -> None:
        allocation = self.calloc(self.read(self.address, 1), 0xA8)
        self.write(self.address + 8, 8, allocation)
        self.start_loop()
        if self.read(self.address, 1):
            self.registers["r15"] = 0
            while True:
                self.begin_record()
                self.input(0x1414AF4FD)
                self.input(0x1414AF568)
                if self.version() >= 0xAD70A:
                    for count_site, array_site, count, pointer in (
                        (0x1414AF5D7, 0x1414AF658, 0xC, 0x10),
                        (0x1414AF6B7, 0x1414AF738, 0x18, 0x20),
                        (0x1414AF797, 0x1414AF81C, 0x28, 0x30),
                    ):
                        self.input(count_site)
                        base = self.read(self.address + 8)
                        amount = self.read(base + self.registers["r15"] + count, 1)
                        if amount:
                            allocation = self.calloc(amount, 4)
                            base = self.read(self.address + 8)
                            self.write(base + self.registers["r15"] + pointer, 8, allocation)
                            self.input(array_site)
                else:
                    self.legacy_three(8, "r15", (0x10, 0x20, 0x30))
                    for site in (
                        0x1414AF8C2,
                        0x1414AF925,
                        0x1414AF984,
                        0x1414AF9E7,
                        0x1414AFA46,
                        0x1414AFAA9,
                    ):
                        self.input(site)
                self.input(0x1414AFB08)
                version = self.version()
                if version >= 0x963D7:
                    for site in (0x1414AFB7B, 0x1414AFBDC, 0x1414AFC3D, 0x1414AFC9F):
                        self.input(site)
                    version = self.version()
                if version >= 0x9828F:
                    self.input(0x1414AFD08)
                index = self.advance_index()
                self.registers["r15"] = (self.registers["r15"] + 0xA8) & _U64
                if index >= self.read(self.address, 1):
                    break
            self.registers["r15"] = (self.address + 0x10) & _U64
            self.registers["r12"] = 0

    def second(self) -> None:
        allocation = self.calloc(self.read(self.registers["r15"], 1), 0xA0)
        self.write(self.address + 0x18, 8, allocation)
        self.start_loop()
        if self.read(self.registers["r15"], 1):
            self.registers["r15"] = 0
            self.registers["r13"] = 5
            while True:
                self.begin_record()
                self.input(0x1414AFDB2)
                self.input(0x1414AFE11)
                if self.version() >= 0xAD70A:
                    for count_site, array_site, count, pointer in (
                        (0x1414AFE8C, 0x1414AFF19, 0x10, 0x18),
                        (0x1414AFF78, 0x1414AFFF9, 0x20, 0x28),
                        (0x1414B0058, 0x1414B00DD, 0x30, 0x38),
                    ):
                        self.input(count_site)
                        base = self.read(self.address + 0x18)
                        amount = self.read(base + self.registers["r15"] + count, 1)
                        if amount:
                            allocation = self.calloc(amount, 4)
                            base = self.read(self.address + 0x18)
                            self.write(base + self.registers["r15"] + pointer, 8, allocation)
                            self.input(array_site)
                else:
                    self.legacy_three(0x18, "r15", (0x18, 0x28, 0x38))
                    for site in (
                        0x1414B15C6,
                        0x1414B1635,
                        0x1414B1694,
                        0x1414B16F7,
                        0x1414B1756,
                        0x1414B17B9,
                    ):
                        self.input(site)
                self.input(0x1414B1818)
                version = self.version()
                if version >= 0x963D7:
                    self.input(0x1414B188B)
                    self.input(0x1414B18EA)
                    version = self.version()
                if version >= 0x96B85:
                    self.input(0x1414B1956)
                    version = self.version()
                if version >= 0x9828F:
                    self.input(0x1414B19BF)
                    version = self.version()
                if version >= 0x9E8F5:
                    self.input(0x1414B1A28)
                index = self.advance_index()
                self.registers["r15"] = (self.registers["r15"] + 0xA0) & _U64
                if index >= self.read(self.address + 0x10, 1):
                    break
            self.registers["r12"] = 0

    def third(self) -> None:
        count = _signed(self.read(self.address + 0x20, 2), 2) & _U64
        allocation = self.calloc(count, 0x88)
        self.write(self.address + 0x28, 8, allocation)
        self.start_loop()
        self.registers["r15"] = _U32
        if _signed(self.read(self.address + 0x20, 2), 2) > 0:
            self.put_home(0x28, 8, self.registers["r12"])
            while True:
                self.begin_record()
                for site in (0x1414B1AD4, 0x1414B1B64, 0x1414B1BEB, 0x1414B1C4A):
                    self.input(site)
                if self.version() >= 0x963D7:
                    self.input(0x1414B1CC2)
                    if self.version() >= 0xAD70A:
                        self.input(0x1414B1D3D)
                        base = self.read(self.address + 0x28)
                        self.registers["r12"] = self.home(0x28)
                        amount = self.read(base + self.registers["r12"] + 0x18, 1)
                        if amount:
                            allocation = self.calloc(amount, 4)
                            base = self.read(self.address + 0x28)
                            self.write(base + self.registers["r12"] + 0x20, 8, allocation)
                            self.input(0x1414B1DC7)
                    else:
                        allocation = self.calloc(self.home(0x98, 4), 4)
                        base = self.read(self.address + 0x28)
                        self.registers["r12"] = self.home(0x28)
                        self.write(base + self.registers["r12"] + 0x20, 8, allocation)
                        self.input(0x1414B3509)
                        self.input(0x1414B356B)
                else:
                    # Original JL1414b3592 skips the entire7c/18h/20h block.
                    self.registers["r12"] = self.home(0x28)
                for threshold, site in (
                    (0x975C2, 0x1414B35DA),
                    (0x98000, 0x1414B3642),
                    (0x9828F, 0x1414B36AA),
                    (0x9E8F5, 0x1414B3712),
                ):
                    if self.version() >= threshold:
                        self.input(site)
                index = self.advance_index()
                self.registers["r12"] = (self.registers["r12"] + 0x88) & _U64
                self.put_home(0x28, 8, self.registers["r12"])
                if index >= _signed(self.read(self.address + 0x20, 2), 2):
                    break
            self.registers["r12"] = 0

    def fourth(self) -> None:
        allocation = self.calloc(self.read(self.address + 0x30, 1), 0xA0)
        self.write(self.address + 0x38, 8, allocation)
        self.start_loop()
        if self.read(self.address + 0x30, 1):
            while True:
                self.begin_record()
                self.input(0x1414B37BE)
                self.input(0x1414B385E)
                self.input(0x1414B38FB)
                if self.version() >= 0xAD70A:
                    for count_site, array_site, count, pointer in (
                        (0x1414B39AB, 0x1414B3A6D, 0x10, 0x18),
                        (0x1414B3AD8, 0x1414B3B65, 0x20, 0x28),
                        (0x1414B3BD0, 0x1414B3C61, 0x30, 0x38),
                    ):
                        self.input(count_site)
                        base = self.read(self.address + 0x38)
                        amount = self.read(base + self.registers["r12"] + count, 1)
                        if amount:
                            allocation = self.calloc(amount, 4)
                            base = self.read(self.address + 0x38)
                            self.write(base + self.registers["r12"] + pointer, 8, allocation)
                            self.input(array_site)
                else:
                    self.legacy_three(0x38, "r12", (0x18, 0x28, 0x38))
                    for site in (
                        0x1414B4D7B,
                        0x1414B4E1F,
                        0x1414B4E8A,
                        0x1414B4EF9,
                        0x1414B4F64,
                        0x1414B4FC7,
                    ):
                        self.input(site)
                self.input(0x1414B5026)
                version = self.version()
                if version >= 0x963D7:
                    self.input(0x1414B509E)
                    version = self.version()
                if version >= 0x975C2:
                    self.input(0x1414B510A)
                    version = self.version()
                if version >= 0x9828F:
                    self.input(0x1414B5173)
                index = self.advance_index()
                self.registers["r12"] = (self.registers["r12"] + 0xA0) & _U64
                if index >= self.read(self.address + 0x30, 1):
                    break
            self.registers["r12"] = 0


def read_replay_player_auxiliary(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAuxiliaryReaderScratch,
    profile: ReplayPlayerAuxiliaryReaderProfile,
) -> int:
    """All78 normal Input sites; nonzero status is an explicit diagnostic frontier.

    Actual imports, stream/Result callbacks and coherent seeded logical backing
    are required. The shared window retains home/Result aliases through cleanup.
    It is unmapped by the caller's local manager after completion/refusal.
    """
    _validate(context, calls, address, output, stream)
    _validate(context, imports)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual auxiliary reader atomic/local bindings required")
    if not isinstance(scratch, ReplayPlayerAuxiliaryReaderScratch):
        raise ValueError("explicit auxiliary reader window scratch required")
    if not isinstance(profile, ReplayPlayerAuxiliaryReaderProfile):
        raise ValueError("explicit finite auxiliary reader profile required")
    with _local(memoryview(bytearray(scratch.frame)), bind_local) as frame:
        registers = {
            "rdi": address,
            "rbx": stream,
            "r14": output,
            "r12": 0,
            "r8": stream,
            "rcx": address,
            "rdx": output,
            "rsp": (frame - 0x28) & _U64,
            "rbp": (frame + 0xD8) & _U64,
        }
        reader = _Reader(
            context, address, output, stream, calls, imports, atomics, frame, profile, registers
        )
        reader.header()
        reader.first()
        reader.second()
        reader.third()
        reader.fourth()
        for offset in (0, 8, 0x10, 0x18, 0x20):
            reader.write(output + offset, 8, 0)
        reader.write(output + 0x28, 1, 0)
        return output


def bind_replay_player_auxiliary_reader(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    imports: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayPlayerAuxiliaryReaderScratch,
    profile: ReplayPlayerAuxiliaryReaderProfile,
) -> ReplayTaskRebuildCalls:
    """Own only1414aea70 normal profile; unknown targets delegate unchanged."""
    _validate(context, calls)
    _validate(context, imports)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual auxiliary reader atomic/local bindings required")
    if not isinstance(scratch, ReplayPlayerAuxiliaryReaderScratch):
        raise ValueError("explicit auxiliary reader window scratch required")
    if not isinstance(profile, ReplayPlayerAuxiliaryReaderProfile):
        raise ValueError("explicit finite auxiliary reader profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != 0x1414AEA70:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 3 or data is not None:
            raise ValueError("malformed auxiliary reader call")
        return read_replay_player_auxiliary(
            context,
            *args,
            calls=bound,
            imports=imports,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
            profile=profile,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound


# Literal finite setup data; generated only from pinned original ASM.
_SITES = {
    0x1414AEAEA: _Site(
        120,
        0x1414AEAF8,
        1,
        (
            ("zero", "", (("rbp", 1),), -96, 16),
            ("zero", "", (("rbp", 1),), -80, 16),
            ("zero", "", (("rbp", 1),), -64, 16),
            ("load", "rax", (("r8", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "r8", (("rcx", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), -96, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AEC82: _Site(
        1272,
        0x1414AEC94,
        0,
        (
            ("zero", "", (("rbp", 1),), 1056, 16),
            ("zero", "", (("rbp", 1),), 1072, 16),
            ("zero", "", (("rbp", 1),), 1088, 16),
            ("value", "r15", (("rdi", 1),), 16, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "r8", (("r15", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 1056, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AEE1D: _Site(
        1320,
        0x1414AEE2F,
        0,
        (
            ("zero", "", (("rbp", 1),), 1104, 16),
            ("zero", "", (("rbp", 1),), 1120, 16),
            ("zero", "", (("rbp", 1),), 1136, 16),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 2, 4),
            ("value", "rdx", (("rbp", 1),), 1104, 8),
        ),
    ),
    0x1414AEF93: _Site(
        1368,
        0x1414AEFA5,
        0,
        (
            ("zero", "", (("rbp", 1),), 1152, 16),
            ("zero", "", (("rbp", 1),), 1168, 16),
            ("zero", "", (("rbp", 1),), 1184, 16),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 1152, 8),
        ),
    ),
    0x1414AF12C: _Site(
        1416,
        0x1414AF13E,
        0,
        (
            ("zero", "", (("rbp", 1),), 1200, 16),
            ("zero", "", (("rbp", 1),), 1216, 16),
            ("zero", "", (("rbp", 1),), 1232, 16),
            ("value", "r8", (("rdi", 1),), 48, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 1200, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF2DC: _Site(
        1464,
        0x1414AF2EE,
        0,
        (
            ("zero", "", (("rbp", 1),), 1248, 16),
            ("zero", "", (("rbp", 1),), 1264, 16),
            ("zero", "", (("rbp", 1),), 1280, 16),
            ("value", "r8", (("rdi", 1),), 68, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 4),
            ("value", "rdx", (("rbp", 1),), 1248, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF4FD: _Site(
        648,
        0x1414B13D6,
        1,
        (
            ("zero", "", (("rbp", 1),), 432, 16),
            ("zero", "", (("rbp", 1),), 448, 16),
            ("zero", "", (("rbp", 1),), 464, 16),
            ("signed32", "rax", (("rcx", 1),), 0, 8),
            ("value", "r12", (("rax", 168),), 0, 8),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 432, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF568: _Site(
        2376,
        0x1414B1273,
        0,
        (
            ("zero", "", (("rbp", 1),), 2160, 16),
            ("zero", "", (("rbp", 1),), 2176, 16),
            ("zero", "", (("rbp", 1),), 2192, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 4, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 2160, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF5D7: _Site(
        1752,
        0x1414B05C3,
        0,
        (
            ("zero", "", (("rbp", 1),), 1536, 16),
            ("zero", "", (("rbp", 1),), 1552, 16),
            ("zero", "", (("rbp", 1),), 1568, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 12, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 1536, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF658: _Site(
        1512,
        0x1414B0102,
        0,
        (
            ("zero", "", (("rbp", 1),), 1296, 16),
            ("zero", "", (("rbp", 1),), 1312, 16),
            ("zero", "", (("rbp", 1),), 1328, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("load", "r9", (("r15", 1), ("r8", 1)), 12, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 16, 8),
            ("value", "rdx", (("rbp", 1),), 1296, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF6B7: _Site(
        1704,
        0x1414B04B9,
        0,
        (
            ("zero", "", (("rbp", 1),), 1488, 16),
            ("zero", "", (("rbp", 1),), 1504, 16),
            ("zero", "", (("rbp", 1),), 1520, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 24, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 1488, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF738: _Site(
        1560,
        0x1414B0223,
        0,
        (
            ("zero", "", (("rbp", 1),), 1344, 16),
            ("zero", "", (("rbp", 1),), 1360, 16),
            ("zero", "", (("rbp", 1),), 1376, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("load", "r9", (("r15", 1), ("r8", 1)), 24, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 32, 8),
            ("value", "rdx", (("rbp", 1),), 1344, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF797: _Site(
        1656,
        0x1414B0453,
        0,
        (
            ("zero", "", (("rbp", 1),), 1440, 16),
            ("zero", "", (("rbp", 1),), 1456, 16),
            ("zero", "", (("rbp", 1),), 1472, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 40, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 1440, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF81C: _Site(
        1608,
        0x1414B0343,
        0,
        (
            ("zero", "", (("rbp", 1),), 1392, 16),
            ("zero", "", (("rbp", 1),), 1408, 16),
            ("zero", "", (("rbp", 1),), 1424, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("load", "r9", (("r15", 1), ("r8", 1)), 40, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 48, 8),
            ("value", "rdx", (("rbp", 1),), 1392, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF8C2: _Site(
        2328,
        0x1414B1143,
        0,
        (
            ("zero", "", (("rbp", 1),), 2112, 16),
            ("zero", "", (("rbp", 1),), 2128, 16),
            ("zero", "", (("rbp", 1),), 2144, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 12, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 2112, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF925: _Site(
        2280,
        0x1414B1013,
        0,
        (
            ("zero", "", (("rbp", 1),), 2064, 16),
            ("zero", "", (("rbp", 1),), 2080, 16),
            ("zero", "", (("rbp", 1),), 2096, 16),
            ("load", "rax", (("rbp", 1),), -112, 8),
            ("value", "r9", (("rax", 4),), 0, 8),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 16, 8),
            ("value", "rdx", (("rbp", 1),), 2064, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF984: _Site(
        2232,
        0x1414B0F13,
        0,
        (
            ("zero", "", (("rbp", 1),), 2016, 16),
            ("zero", "", (("rbp", 1),), 2032, 16),
            ("zero", "", (("rbp", 1),), 2048, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 24, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 2016, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AF9E7: _Site(
        2184,
        0x1414B0DF3,
        0,
        (
            ("zero", "", (("rbp", 1),), 1968, 16),
            ("zero", "", (("rbp", 1),), 1984, 16),
            ("zero", "", (("rbp", 1),), 2000, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "rax", (("rbp", 1),), -112, 8),
            ("value", "r9", (("rax", 4),), 0, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 32, 8),
            ("value", "rdx", (("rbp", 1),), 1968, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFA46: _Site(
        2136,
        0x1414B0CE9,
        0,
        (
            ("zero", "", (("rbp", 1),), 1920, 16),
            ("zero", "", (("rbp", 1),), 1936, 16),
            ("zero", "", (("rbp", 1),), 1952, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 40, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 1920, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFAA9: _Site(
        2088,
        0x1414B0C23,
        0,
        (
            ("zero", "", (("rbp", 1),), 1872, 16),
            ("zero", "", (("rbp", 1),), 1888, 16),
            ("zero", "", (("rbp", 1),), 1904, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r9", (("rbp", 1),), -112, 8),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 48, 8),
            ("value", "rdx", (("rbp", 1),), 1872, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFB08: _Site(
        2040,
        0x1414B0B0B,
        0,
        (
            ("zero", "", (("rbp", 1),), 1824, 16),
            ("zero", "", (("rbp", 1),), 1840, 16),
            ("zero", "", (("rbp", 1),), 1856, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 56, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 84, 4),
            ("value", "rdx", (("rbp", 1),), 1824, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFB7B: _Site(
        1944,
        0x1414B0998,
        0,
        (
            ("zero", "", (("rbp", 1),), 1728, 16),
            ("zero", "", (("rbp", 1),), 1744, 16),
            ("zero", "", (("rbp", 1),), 1760, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 140, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 1728, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFBDC: _Site(
        1896,
        0x1414B08C8,
        0,
        (
            ("zero", "", (("rbp", 1),), 1680, 16),
            ("zero", "", (("rbp", 1),), 1696, 16),
            ("zero", "", (("rbp", 1),), 1712, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 141, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r9", (("rsp", 1),), 40, 8),
            ("value", "rdx", (("rbp", 1),), 1680, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFC3D: _Site(
        1848,
        0x1414B07F8,
        0,
        (
            ("zero", "", (("rbp", 1),), 1632, 16),
            ("zero", "", (("rbp", 1),), 1648, 16),
            ("zero", "", (("rbp", 1),), 1664, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 151, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r9", (("rsp", 1),), 40, 8),
            ("value", "rdx", (("rbp", 1),), 1632, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFC9F: _Site(
        1800,
        0x1414B06E4,
        0,
        (
            ("zero", "", (("rbp", 1),), 1584, 16),
            ("zero", "", (("rbp", 1),), 1600, 16),
            ("zero", "", (("rbp", 1),), 1616, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 161, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 1584, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFD08: _Site(
        1992,
        0x1414B09F8,
        0,
        (
            ("zero", "", (("rbp", 1),), 1776, 16),
            ("zero", "", (("rbp", 1),), 1792, 16),
            ("zero", "", (("rbp", 1),), 1808, 16),
            ("load", "r8", (("rdi", 1),), 8, 8),
            ("value", "r8", (("r8", 1),), 8, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 1776, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFDB2: _Site(
        168,
        0x1414B3353,
        1,
        (
            ("zero", "", (("rbp", 1),), -48, 16),
            ("zero", "", (("rbp", 1),), -32, 16),
            ("zero", "", (("rbp", 1),), -16, 16),
            ("signed32", "rax", (("rcx", 1),), 0, 8),
            ("value", "r12", (("rax", 1), ("rax", 4)), 0, 8),
            ("value", "r12", (("r12", 32),), 0, 8),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), -48, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFE11: _Site(
        792,
        0x1414B3236,
        1,
        (
            ("zero", "", (("rbp", 1),), 576, 16),
            ("zero", "", (("rbp", 1),), 592, 16),
            ("zero", "", (("rbp", 1),), 608, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 8, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 576, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFE8C: _Site(
        696,
        0x1414B23A3,
        1,
        (
            ("zero", "", (("rbp", 1),), 480, 16),
            ("zero", "", (("rbp", 1),), 496, 16),
            ("zero", "", (("rbp", 1),), 512, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 16, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 480, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFF19: _Site(
        2424,
        0x1414B1DF1,
        0,
        (
            ("zero", "", (("rbp", 1),), 2208, 16),
            ("zero", "", (("rbp", 1),), 2224, 16),
            ("zero", "", (("rbp", 1),), 2240, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("load", "r9", (("r15", 1), ("r8", 1)), 16, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 24, 8),
            ("value", "rdx", (("rbp", 1),), 2208, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFF78: _Site(
        2616,
        0x1414B2283,
        0,
        (
            ("zero", "", (("rbp", 1),), 2400, 16),
            ("zero", "", (("rbp", 1),), 2416, 16),
            ("zero", "", (("rbp", 1),), 2432, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 32, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 2400, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414AFFF9: _Site(
        2472,
        0x1414B1F23,
        0,
        (
            ("zero", "", (("rbp", 1),), 2256, 16),
            ("zero", "", (("rbp", 1),), 2272, 16),
            ("zero", "", (("rbp", 1),), 2288, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("load", "r9", (("r15", 1), ("r8", 1)), 32, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 40, 8),
            ("value", "rdx", (("rbp", 1),), 2256, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B0058: _Site(
        2568,
        0x1414B2163,
        0,
        (
            ("zero", "", (("rbp", 1),), 2352, 16),
            ("zero", "", (("rbp", 1),), 2368, 16),
            ("zero", "", (("rbp", 1),), 2384, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 48, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 2352, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B00DD: _Site(
        2520,
        0x1414B2043,
        0,
        (
            ("zero", "", (("rbp", 1),), 2304, 16),
            ("zero", "", (("rbp", 1),), 2320, 16),
            ("zero", "", (("rbp", 1),), 2336, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("load", "r9", (("r15", 1), ("r8", 1)), 48, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 56, 8),
            ("value", "rdx", (("rbp", 1),), 2304, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B15C6: _Site(
        744,
        0x1414B3123,
        1,
        (
            ("zero", "", (("rbp", 1),), 528, 16),
            ("zero", "", (("rbp", 1),), 544, 16),
            ("zero", "", (("rbp", 1),), 560, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 16, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 528, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1635: _Site(
        3144,
        0x1414B2FF3,
        0,
        (
            ("zero", "", (("rbp", 1),), 2928, 16),
            ("zero", "", (("rbp", 1),), 2944, 16),
            ("zero", "", (("rbp", 1),), 2960, 16),
            ("load", "rax", (("rbp", 1),), -112, 8),
            ("value", "r9", (("rax", 4),), 0, 8),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 24, 8),
            ("value", "rdx", (("rbp", 1),), 2928, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1694: _Site(
        3096,
        0x1414B2ED3,
        0,
        (
            ("zero", "", (("rbp", 1),), 2880, 16),
            ("zero", "", (("rbp", 1),), 2896, 16),
            ("zero", "", (("rbp", 1),), 2912, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 32, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 2880, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B16F7: _Site(
        3048,
        0x1414B2DB3,
        0,
        (
            ("zero", "", (("rbp", 1),), 2832, 16),
            ("zero", "", (("rbp", 1),), 2848, 16),
            ("zero", "", (("rbp", 1),), 2864, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "rax", (("rbp", 1),), -112, 8),
            ("value", "r9", (("rax", 4),), 0, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 40, 8),
            ("value", "rdx", (("rbp", 1),), 2832, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1756: _Site(
        3000,
        0x1414B2CB3,
        0,
        (
            ("zero", "", (("rbp", 1),), 2784, 16),
            ("zero", "", (("rbp", 1),), 2800, 16),
            ("zero", "", (("rbp", 1),), 2816, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 48, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 2784, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B17B9: _Site(
        2952,
        0x1414B2B93,
        0,
        (
            ("zero", "", (("rbp", 1),), 2736, 16),
            ("zero", "", (("rbp", 1),), 2752, 16),
            ("zero", "", (("rbp", 1),), 2768, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r9", (("rbp", 1),), -112, 8),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "r8", (("r15", 1), ("r8", 1)), 56, 8),
            ("value", "rdx", (("rbp", 1),), 2736, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1818: _Site(
        2904,
        0x1414B2A68,
        0,
        (
            ("zero", "", (("rbp", 1),), 2688, 16),
            ("zero", "", (("rbp", 1),), 2704, 16),
            ("zero", "", (("rbp", 1),), 2720, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 64, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 84, 4),
            ("value", "rdx", (("rbp", 1),), 2688, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B188B: _Site(
        2712,
        0x1414B25E3,
        0,
        (
            ("zero", "", (("rbp", 1),), 2496, 16),
            ("zero", "", (("rbp", 1),), 2512, 16),
            ("zero", "", (("rbp", 1),), 2528, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 148, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 2496, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B18EA: _Site(
        2664,
        0x1414B24C4,
        0,
        (
            ("zero", "", (("rbp", 1),), 2448, 16),
            ("zero", "", (("rbp", 1),), 2464, 16),
            ("zero", "", (("rbp", 1),), 2480, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 149, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("r13", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 2448, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1956: _Site(
        2760,
        0x1414B2753,
        0,
        (
            ("zero", "", (("rbp", 1),), 2544, 16),
            ("zero", "", (("rbp", 1),), 2560, 16),
            ("zero", "", (("rbp", 1),), 2576, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 154, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("r13", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 2544, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B19BF: _Site(
        2808,
        0x1414B2884,
        0,
        (
            ("zero", "", (("rbp", 1),), 2592, 16),
            ("zero", "", (("rbp", 1),), 2608, 16),
            ("zero", "", (("rbp", 1),), 2624, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 12, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 2592, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1A28: _Site(
        2856,
        0x1414B29A3,
        0,
        (
            ("zero", "", (("rbp", 1),), 2640, 16),
            ("zero", "", (("rbp", 1),), 2656, 16),
            ("zero", "", (("rbp", 1),), 2672, 16),
            ("load", "r8", (("rdi", 1),), 24, 8),
            ("value", "r8", (("r8", 1),), 4, 8),
            ("value", "r8", (("r8", 1), ("r12", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 2640, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1AD4: _Site(
        312,
        0x1414B4B73,
        2,
        (
            ("zero", "", (("rbp", 1),), 96, 16),
            ("zero", "", (("rbp", 1),), 112, 16),
            ("zero", "", (("rbp", 1),), 128, 16),
            ("signed32", "rax", (("rcx", 1),), 0, 8),
            ("value", "r13", (("rax", 136),), 0, 8),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 96, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1B64: _Site(
        264,
        0x1414B49D3,
        2,
        (
            ("zero", "", (("rbp", 1),), 48, 16),
            ("zero", "", (("rbp", 1),), 64, 16),
            ("zero", "", (("rbp", 1),), 80, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), 8, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 48, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1BEB: _Site(
        216,
        0x1414B4863,
        1,
        (
            ("zero", "", (("rbp", 1),), 0, 16),
            ("zero", "", (("rbp", 1),), 16, 16),
            ("zero", "", (("rbp", 1),), 32, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), 16, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 0, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1C4A: _Site(
        888,
        0x1414B4753,
        1,
        (
            ("zero", "", (("rbp", 1),), 672, 16),
            ("zero", "", (("rbp", 1),), 688, 16),
            ("zero", "", (("rbp", 1),), 704, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), 40, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 84, 4),
            ("value", "rdx", (("rbp", 1),), 672, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1CC2: _Site(
        840,
        0x1414B40A6,
        1,
        (
            ("zero", "", (("rbp", 1),), 624, 16),
            ("zero", "", (("rbp", 1),), 640, 16),
            ("zero", "", (("rbp", 1),), 656, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), 124, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 624, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1D3D: _Site(
        3240,
        0x1414B3D86,
        0,
        (
            ("zero", "", (("rbp", 1),), 3024, 16),
            ("zero", "", (("rbp", 1),), 3040, 16),
            ("zero", "", (("rbp", 1),), 3056, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), 24, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 3024, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B1DC7: _Site(
        3192,
        0x1414B3C86,
        0,
        (
            ("zero", "", (("rbp", 1),), 2976, 16),
            ("zero", "", (("rbp", 1),), 2992, 16),
            ("zero", "", (("rbp", 1),), 3008, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("load", "r9", (("r12", 1), ("r8", 1)), 24, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r12", 1), ("r8", 1)), 32, 8),
            ("value", "rdx", (("rbp", 1),), 2976, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B3509: _Site(
        3336,
        0x1414B3FA3,
        0,
        (
            ("zero", "", (("rbp", 1),), 3120, 16),
            ("zero", "", (("rbp", 1),), 3136, 16),
            ("zero", "", (("rbp", 1),), 3152, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), 24, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 3120, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B356B: _Site(
        3288,
        0x1414B3E83,
        0,
        (
            ("zero", "", (("rbp", 1),), 3072, 16),
            ("zero", "", (("rbp", 1),), 3088, 16),
            ("zero", "", (("rbp", 1),), 3104, 16),
            ("load", "rax", (("rbp", 1),), -104, 4),
            ("value", "r9", (("rax", 4),), 0, 8),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r12", 1), ("r8", 1)), 32, 8),
            ("value", "rdx", (("rbp", 1),), 3072, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B35DA: _Site(
        3384,
        0x1414B4213,
        0,
        (
            ("zero", "", (("rbp", 1),), 3168, 16),
            ("zero", "", (("rbp", 1),), 3184, 16),
            ("zero", "", (("rbp", 1),), 3200, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), -18446744073709551488, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 3168, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B3642: _Site(
        3432,
        0x1414B4367,
        0,
        (
            ("zero", "", (("rbp", 1),), 3216, 16),
            ("zero", "", (("rbp", 1),), 3232, 16),
            ("zero", "", (("rbp", 1),), 3248, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), 20, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 3216, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B36AA: _Site(
        3480,
        0x1414B44D6,
        0,
        (
            ("zero", "", (("rbp", 1),), 3264, 16),
            ("zero", "", (("rbp", 1),), 3280, 16),
            ("zero", "", (("rbp", 1),), 3296, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), 12, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 3264, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B3712: _Site(
        3528,
        0x1414B4642,
        0,
        (
            ("zero", "", (("rbp", 1),), 3312, 16),
            ("zero", "", (("rbp", 1),), 3328, 16),
            ("zero", "", (("rbp", 1),), 3344, 16),
            ("load", "r8", (("rdi", 1),), 40, 8),
            ("value", "r8", (("r8", 1),), 4, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 3312, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B37BE: _Site(
        600,
        0x1414B6802,
        3,
        (
            ("zero", "", (("rbp", 1),), 384, 16),
            ("zero", "", (("rbp", 1),), 400, 16),
            ("zero", "", (("rbp", 1),), 416, 16),
            ("signed32", "rax", (("rcx", 1),), 0, 8),
            ("value", "r13", (("rax", 1), ("rax", 4)), 0, 8),
            ("value", "r13", (("r13", 32),), 0, 8),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 384, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B385E: _Site(
        552,
        0x1414B665F,
        3,
        (
            ("zero", "", (("rbp", 1),), 336, 16),
            ("zero", "", (("rbp", 1),), 352, 16),
            ("zero", "", (("rbp", 1),), 368, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 4, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 336, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B38FB: _Site(
        504,
        0x1414B64AF,
        3,
        (
            ("zero", "", (("rbp", 1),), 288, 16),
            ("zero", "", (("rbp", 1),), 304, 16),
            ("zero", "", (("rbp", 1),), 320, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 12, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 288, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B39AB: _Site(
        360,
        0x1414B5755,
        3,
        (
            ("zero", "", (("rbp", 1),), 144, 16),
            ("zero", "", (("rbp", 1),), 160, 16),
            ("zero", "", (("rbp", 1),), 176, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 16, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 144, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B3A6D: _Site(
        936,
        0x1414B5211,
        1,
        (
            ("zero", "", (("rbp", 1),), 720, 16),
            ("zero", "", (("rbp", 1),), 736, 16),
            ("zero", "", (("rbp", 1),), 752, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("load", "r9", (("r12", 1), ("r8", 1)), 16, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r12", 1), ("r8", 1)), 24, 8),
            ("value", "rdx", (("rbp", 1),), 720, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B3AD8: _Site(
        1080,
        0x1414B5666,
        1,
        (
            ("zero", "", (("rbp", 1),), 864, 16),
            ("zero", "", (("rbp", 1),), 880, 16),
            ("zero", "", (("rbp", 1),), 896, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 32, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 864, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B3B65: _Site(
        984,
        0x1414B5333,
        1,
        (
            ("zero", "", (("rbp", 1),), 768, 16),
            ("zero", "", (("rbp", 1),), 784, 16),
            ("zero", "", (("rbp", 1),), 800, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("load", "r9", (("r12", 1), ("r8", 1)), 32, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r12", 1), ("r8", 1)), 40, 8),
            ("value", "rdx", (("rbp", 1),), 768, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B3BD0: _Site(
        1032,
        0x1414B5563,
        1,
        (
            ("zero", "", (("rbp", 1),), 816, 16),
            ("zero", "", (("rbp", 1),), 832, 16),
            ("zero", "", (("rbp", 1),), 848, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 48, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 816, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B3C61: _Site(
        3576,
        0x1414B5443,
        0,
        (
            ("zero", "", (("rbp", 1),), 3360, 16),
            ("zero", "", (("rbp", 1),), 3376, 16),
            ("zero", "", (("rbp", 1),), 3392, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("load", "r9", (("r12", 1), ("r8", 1)), 48, 1),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r12", 1), ("r8", 1)), 56, 8),
            ("value", "rdx", (("rbp", 1),), 3360, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B4D7B: _Site(
        456,
        0x1414B636F,
        3,
        (
            ("zero", "", (("rbp", 1),), 240, 16),
            ("zero", "", (("rbp", 1),), 256, 16),
            ("zero", "", (("rbp", 1),), 272, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 16, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 240, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B4E1F: _Site(
        408,
        0x1414B6233,
        1,
        (
            ("zero", "", (("rbp", 1),), 192, 16),
            ("zero", "", (("rbp", 1),), 208, 16),
            ("zero", "", (("rbp", 1),), 224, 16),
            ("load", "rax", (("rbp", 1),), -112, 8),
            ("value", "r9", (("rax", 4),), 0, 8),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r8", (("r12", 1), ("r8", 1)), 24, 8),
            ("value", "rdx", (("rbp", 1),), 192, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B4E8A: _Site(
        1224,
        0x1414B6133,
        1,
        (
            ("zero", "", (("rbp", 1),), 1008, 16),
            ("zero", "", (("rbp", 1),), 1024, 16),
            ("zero", "", (("rbp", 1),), 1040, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 32, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 1008, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B4EF9: _Site(
        1176,
        0x1414B6003,
        1,
        (
            ("zero", "", (("rbp", 1),), 960, 16),
            ("zero", "", (("rbp", 1),), 976, 16),
            ("zero", "", (("rbp", 1),), 992, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "rax", (("rbp", 1),), -112, 8),
            ("value", "r9", (("rax", 4),), 0, 8),
            ("load", "r8", (("r12", 1), ("r8", 1)), 40, 8),
            ("value", "rdx", (("rbp", 1),), 960, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B4F64: _Site(
        3816,
        0x1414B5F03,
        0,
        (
            ("zero", "", (("rbp", 1),), 3600, 16),
            ("zero", "", (("rbp", 1),), 3616, 16),
            ("zero", "", (("rbp", 1),), 3632, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 48, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 1, 4),
            ("value", "rdx", (("rbp", 1),), 3600, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B4FC7: _Site(
        3768,
        0x1414B5DE6,
        0,
        (
            ("zero", "", (("rbp", 1),), 3552, 16),
            ("zero", "", (("rbp", 1),), 3568, 16),
            ("zero", "", (("rbp", 1),), 3584, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("load", "r9", (("rbp", 1),), -112, 8),
            ("value", "r9", (("r9", 4),), 0, 8),
            ("load", "r8", (("r12", 1), ("r8", 1)), 56, 8),
            ("value", "rdx", (("rbp", 1),), 3552, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B5026: _Site(
        1128,
        0x1414B5CD6,
        1,
        (
            ("zero", "", (("rbp", 1),), 912, 16),
            ("zero", "", (("rbp", 1),), 928, 16),
            ("zero", "", (("rbp", 1),), 944, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 64, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (), 84, 4),
            ("value", "rdx", (("rbp", 1),), 912, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B509E: _Site(
        3624,
        0x1414B589F,
        0,
        (
            ("zero", "", (("rbp", 1),), 3408, 16),
            ("zero", "", (("rbp", 1),), 3424, 16),
            ("zero", "", (("rbp", 1),), 3440, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 148, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 3408, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B510A: _Site(
        3672,
        0x1414B5A13,
        0,
        (
            ("zero", "", (("rbp", 1),), 3456, 16),
            ("zero", "", (("rbp", 1),), 3472, 16),
            ("zero", "", (("rbp", 1),), 3488, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 152, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 3456, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
    0x1414B5173: _Site(
        3720,
        0x1414B5B67,
        0,
        (
            ("zero", "", (("rbp", 1),), 3504, 16),
            ("zero", "", (("rbp", 1),), 3520, 16),
            ("zero", "", (("rbp", 1),), 3536, 16),
            ("load", "r8", (("rdi", 1),), 56, 8),
            ("value", "r8", (("r8", 1),), 8, 8),
            ("value", "r8", (("r8", 1), ("r13", 1)), 0, 8),
            ("load", "rax", (("rbx", 1),), 0, 8),
            ("load", "r10", (("rax", 1),), 24, 8),
            ("value", "r9", (("rsi", 1),), 0, 8),
            ("value", "rdx", (("rbp", 1),), 3504, 8),
            ("value", "rcx", (("rbx", 1),), 0, 8),
        ),
    ),
}
