"""Complete1318B/269instruction File refill140915600 caller.

Source: replay-file-read-seek-contract-v1. Current backend, variadic error
construction, Result cleanup, TLS/guards/registration/augmentation and data
effects are mandatory. No stream, codec, File initialization or I/O is supplied.
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
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_REFILL, _READ, _SEEK = 0x140915600, 0x14093A930, 0x14093A990
_CPP, _FORMAT = 0x1431F7B10, 0x1431F7B68


@dataclass(frozen=True, slots=True)
class ReplayFileRefillProfile:
    """Explicit88h live seed and optional owned engine GS base address.

    Home80 is output then seek position/read actual. Result50..7f, partial
    variadic20Q/28D and encoded40D/44W share this backing. Cookie88/XMM90 and
    native save areas are excluded. None refuses only at reached GS58 after
    actual error-local control/vector cleanup; no host GS is consulted.
    """

    frame: bytes
    gs_base: int | None

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 0x88:
            raise ValueError("explicit88-hex-byte File refill local seed required")
        if self.gs_base is not None:
            _unsigned(self.gs_base, 8, "owned engine GS base")


def _raw(value: int | None, description: str) -> int:
    if value is None:
        raise ValueError(f"{description} requires rawRAX at its source consumption")
    _unsigned(value, 8, description)
    return value


@dataclass(slots=True)
class _Refill:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    variadic: ReplayTaskRebuildCalls
    imports: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics
    profile: ReplayFileRefillProfile
    frame: int
    output: int

    def at(self, offset: int) -> int:
        return (self.frame + offset) & _U64

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def call(self, target: int, *args: int) -> None:
        _call(self.calls, target, args)

    def invoke(self, target: int, *args: int, imported: bool = False) -> int | None:
        receiver = self.imports if imported else self.calls
        if receiver.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return receiver.call(target, tuple(value & _U64 for value in args), None)

    def success(self) -> int:
        for offset in (0, 8, 16, 24, 32):
            self.write(self.output + offset, 8, 0)
        self.write(self.output + 40, 1, 0)
        return self.output

    def discard(self) -> None:
        control = self.read(self.at(0x70))
        if control:
            _release(self.context, control, self.calls, self.atomics)
        self.call(0x1402BD890, self.at(0x50))

    def gs_index(self) -> tuple[int, int]:
        if self.profile.gs_base is None:
            raise UnresolvedReplayTaskRebuild("File refill reached missing engine GS58 backing")
        array = self.read(self.profile.gs_base + 0x58)
        index = self.read(0x144C9C828, 4)
        return array, index

    def begin_initialization(self, guard: int, epoch: int) -> bool:
        if _signed(self.read(guard, 4), 4) > _signed(epoch, 4):
            self.call(0x142D6BF80, guard)
            return self.read(guard, 4) == _U32
        return False

    def register(self, guard: int, destructor: int) -> None:
        self.call(0x142D6BD04, destructor)
        self.call(0x142D6BF14, guard)

    def augment(self, line: int, text: int) -> int:
        self.call(0x1408ED8F0, self.output, _CPP, line, text)
        return self.output

    def diagnostic31(self) -> int:
        array, index = self.gs_index()
        held_block = self.read(0x1431F8190, 16)
        self.write(self.at(0x40), 4, 0xD2DBD5D6)
        thread = self.read(array + index * 8)
        self.write(self.at(0x44), 2, 0xB7D3)
        epoch = self.read(thread + 0x3B4, 4)
        guard, text = 0x14427F950, 0x14427F938
        if self.begin_initialization(guard, epoch):
            self.write(text + 0x10, 4, self.read(self.at(0x40), 4))
            self.write(text + 0x14, 2, self.read(self.at(0x44), 2))
            self.write(text, 16, held_block)
            self.register(guard, 0x1430575A0)
        if self.read(text + 0x15, 1):
            block = self.read(text, 16)
            mask = self.read(0x1431AC380, 16)
            self.write(text, 16, block ^ mask)
            for offset in range(0x10, 0x16):
                self.write(text + offset, 1, self.read(text + offset, 1) ^ 0xB7)
        return self.augment(0x498, text)

    def diagnostic20(self) -> int:
        array, index = self.gs_index()
        held_block = self.read(0x1431F8290, 16)
        thread = self.read(array + index * 8)
        epoch = self.read(thread + 0x3B4, 4)
        guard, text = 0x14427F968, 0x14427F958
        if self.begin_initialization(guard, epoch):
            self.write(text, 16, held_block)
            self.register(guard, 0x1430579E0)
        if self.read(text + 0xF, 1):
            block = self.read(text, 16)
            mask = self.read(0x1431AD060, 16)
            self.write(text, 16, block ^ mask)
        return self.augment(0x4B3, text)

    def diagnostic25(self) -> int:
        array, index = self.gs_index()
        thread = self.read(array + index * 8)
        epoch = self.read(thread + 0x3B4, 4)
        guard, text = 0x14427F96C, 0x143DA78B8
        if self.begin_initialization(guard, epoch):
            for offset, width, value in (
                (0, 4, 0xFEFBFFC8),
                (4, 4, 0xE8E8FFBA),
                (8, 2, 0xE8F5),
                (10, 1, 0x9A),
            ):
                self.write(text + offset, width, value)
            self.register(guard, 0x143057A10)
        flag = self.read(text + 10, 1)
        if flag:
            for offset in range(10):
                self.write(text + offset, 1, self.read(text + offset, 1) ^ 0x9A)
            self.write(text + 10, 1, flag ^ 0x9A)
        return self.augment(0x4CA, text)

    def error(self, file: int, code: int) -> int:
        self.write(file + 0x48, 4, code)
        self.write(file + 0x4C, 4, code)
        error = None
        if code != 0x31:
            error = self.invoke(self.read(0x143198A88), imported=True)
        self.write(self.at(0x28), 4, code)
        if code != 0x31:
            self.write(file + 0x50, 4, _raw(error, "GetLastError at File50 store"))
        self.write(self.at(0x20), 8, _FORMAT)
        _call(
            self.variadic,
            0x140A08840,
            (
                self.at(0x50),
                0,
                _CPP,
                0xD7,
                self.at(0x20),
                self.at(0x28),
            ),
        )
        self.discard()
        if code == 0x31:
            return self.diagnostic31()
        if code == 0x20:
            return self.diagnostic20()
        return self.diagnostic25()

    def run(self, file: int) -> int:
        self.write(self.at(0x80), 8, self.output)
        if not self.read(file + 0x56, 1):
            return self.error(file, 0x31)
        buffer = self.read(file + 0x68)
        position = self.read(file + 0x40)
        length = self.read(file + 0x30)
        planned = (length - position) & _U64
        self.write(file + 0x70, 8, buffer)
        self.write(file + 0x78, 8, position)
        planned = min(planned, 0x8000)
        if self.read(file + 0x57, 1):
            self.write(file + 0x57, 1, 0)
            handle = self.read(file + 0x28)
            seek = self.invoke(_SEEK, handle, self.at(0x80), 0, position)
            if not _raw(seek, "File refill seek at AL test") & 0xFF:
                return self.error(file, 0x20)
            actual_position = self.read(self.at(0x80))
            if self.read(file + 0x40) != actual_position:
                return self.error(file, 0x20)
        self.write(file + 0x58, 8, planned)
        if not planned:
            return self.success()
        buffer = self.read(file + 0x68)
        handle = self.read(file + 0x28)
        self.write(self.at(0x80), 8, 0)
        read = self.invoke(_READ, handle, buffer, planned & _U32, self.at(0x80))
        actual = self.read(self.at(0x80)) & _U32
        self.write(file + 0x60, 8, actual)
        if _raw(read, "File refill read at AL test") & 0xFF and actual == planned & _U32:
            return self.success()
        self.write(file + 0x58, 8, actual)
        return self.error(file, 0x25)


def bind_replay_file_refill(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    variadic_calls: ReplayTaskRebuildCalls,
    imports: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayFileRefillProfile,
) -> ReplayTaskRebuildCalls:
    """Own complete140915600, arity(File,heldOutput), over explicit current backing.

    Scalar backend seek/read, actualconstructor via20/28 HOME locations, inline
    held-control atomics/currentvirtuals, actual1402bd890 and erroraugmentation
    remain mandatory. No callerstatus/processed reads or stores are inserted.
    Error constructors receive seededResult50 without a preceding blanketzero.
    The three source TLS/currentdata paths and registration calls remain real.

    GSbase is ownedengine address only. MissingGS refuses after reached cleanup.
    GetLastError selects its current IAT then required imports; all other child
    calls use calls/variadic_calls without defaultservices. Seek AL0 skips its
    home80/position comparison. Read validates rawAL only AFTERFile60 publication;
    plannedFile58 and heldactualDWORD remain distinct. There is no File40 advance
    for the read, no File48 success reset or inferred stream/backend readiness.

    Successful output writes41bytes, preserving padding; every normal return
    holds entryoutput even though home80 is reused. All source aliases must have
    coherent logical backing. Physicalstack/cookies/XMM saves/escapedlocals,
    native faults/EH/concurrency are excluded. Unknown targets delegate unchanged.
    """
    _validate(context, calls)
    _validate(context, variadic_calls)
    _validate(context, imports)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual refill local/atomic effects required")
    if not isinstance(profile, ReplayFileRefillProfile):
        raise ValueError("explicit refill local/GS profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _REFILL:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 2 or data is not None:
            raise ValueError("File refill requires two scalar arguments")
        _validate(context, calls, *args)
        with _local(memoryview(bytearray(profile.frame)), bind_local) as frame:
            state = _Refill(
                context, calls, variadic_calls, imports, atomics, profile, frame, args[1]
            )
            return state.run(args[0])

    return ReplayTaskRebuildCalls(dispatch)
