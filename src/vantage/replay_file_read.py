"""Complete Build54800 File Read caller140916db0, 3038B/675 instructions.

Source: replay-file-read-seek-contract-v1. Only this caller is owned.
Mode/refill/backend, codec, variadic, diagnostic, Result, runtime, atomic
and current-data services remain mandatory when reached.
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

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_READ, _CPP, _FORMAT = 0x140916DB0, 0x1431F7B10, 0x1431F7B68


@dataclass(frozen=True, slots=True)
class ReplayFileReadProfile:
    """Liveb8h seed, optional owned GS base, explicit buffer-loop resource bound.

    RBP=frame+c9. Results50/80, output/count home48, decoder sizeB0 and
    variadic/decoder20/28/30/38 homes share this current backing. Reused90/94/A0
    staging cells remain aliases. CookieB8 and physical native homes excluded.
    Budget exhaustion refuses at140917480 before its next File58 read.
    """

    frame: bytes
    gs_base: int | None
    maximum_buffer_iterations: int

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 0xB8:
            raise ValueError("explicitb8-hex-byte File Read local seed required")
        if self.gs_base is not None:
            _unsigned(self.gs_base, 8, "engine GS base")
        if type(self.maximum_buffer_iterations) is not int or self.maximum_buffer_iterations < 0:
            raise ValueError("explicit nonnegative File Read buffer-iteration budget required")


@dataclass(slots=True)
class _Read:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    variadic_calls: ReplayTaskRebuildCalls
    decoder_calls: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics
    profile: ReplayFileReadProfile
    file: int
    output: int
    destination: int
    remaining: int
    frame: int

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def at(self, offset: int) -> int:
        return (self.frame + offset) & _U64

    def invoke(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def invoke_opaque(self, target: int, *args: int) -> int | None:
        if self.calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return self.calls.call(target, tuple(value & _U64 for value in args), None)

    def zero(self, result: int) -> None:
        for offset in (0, 16, 32):
            self.write(result + offset, 16, 0)

    def success(self) -> int:
        for offset in (0, 8, 16, 24, 32):
            self.write(self.output + offset, 8, 0)
        self.write(self.output + 40, 1, 0)
        return self.output

    def cleanup(self, result: int) -> None:
        control = self.read(result + 32)
        if control:
            _release(self.context, control, self.calls, self.atomics)
        self.invoke(0x1402BD890, result)

    def error(self, output: int, code: int) -> None:
        self.write(self.at(0x28), 4, code)
        self.write(self.at(0x20), 8, _FORMAT)
        _call(
            self.variadic_calls,
            0x140A08840,
            (
                output,
                0,
                _CPP,
                0xD7,
                self.at(0x20),
                self.at(0x28),
            ),
        )

    def initializing(self, guard: int) -> bool:
        if self.profile.gs_base is None:
            raise UnresolvedReplayTaskRebuild("File Read reached missing engine GS58 backing")
        array = self.read(self.profile.gs_base + 0x58)
        index = self.read(0x144C9C828, 4)
        thread = self.read(array + index * 8)
        epoch = self.read(thread + 0x3B4, 4)
        if _signed(self.read(guard, 4), 4) <= _signed(epoch, 4):
            return False
        self.invoke(0x142D6BF80, guard)
        return self.read(guard, 4) == _U32

    def registered(self, guard: int, destructor: int) -> None:
        self.invoke(0x142D6BD04, destructor)
        self.invoke(0x142D6BF14, guard)

    def decode(self, address: int, mask_address: int, chunks: int, tail: int, xor: int) -> None:
        mask = self.read(mask_address, 16)
        for offset in range(0, chunks * 16, 16):
            self.write(address + offset, 16, self.read(address + offset, 16) ^ mask)
        for offset in range(chunks * 16, chunks * 16 + tail):
            self.write(address + offset, 1, self.read(address + offset, 1) ^ xor)

    def append_forward(
        self,
        result: int,
        getter: int,
        text: int,
        line: int,
        mask: int,
        xor: int,
    ) -> int:
        detail = self.invoke(getter, self.at(0x40), result=True)
        if self.read(detail + 0x54, 1):
            self.decode(detail, mask, 5, 5, xor)
        self.invoke(0x140900ED0, result, detail, line, text)
        self.invoke(0x1409076B0, self.output, result)
        # Forwarding can replace the control: capture only now.
        self.cleanup(result)
        return self.output

    def preflight_error(self) -> int:
        guard, text = 0x14427F41C, 0x143DA7848
        if self.initializing(guard):
            for offset, value in ((0, 0x171C0936), (4, 0x1A1C113A), (8, 0x79505112)):
                self.write(text + offset, 4, value)
            self.registered(guard, 0x143057930)
        if self.read(text + 11, 1):
            for offset in range(12):
                self.write(text + offset, 1, self.read(text + offset, 1) ^ 0x79)
        return self.append_forward(self.at(0x80), 0x140913B70, text, 0x2AB, 0x1431AB6E0, 0x79)

    def mode_error(self) -> int:
        self.write(self.file + 0x48, 4, 0x2F)
        self.write(self.file + 0x4C, 4, 0x2F)
        self.error(self.at(0x50), 0x2F)
        self.cleanup(self.at(0x50))
        first = self.read(0x1431F7CA0, 16)
        second = self.read(0x1431F7C10, 16)
        self.write(self.at(0xA0), 4, 0x1F1E1802)
        guard, text = 0x14427F448, 0x14427F420
        if self.initializing(guard):
            self.write(text, 16, first)
            self.write(text + 16, 16, second)
            self.write(text + 32, 4, self.read(self.at(0xA0), 4))
            self.write(text + 36, 1, 0x51)
            self.registered(guard, 0x1430579F0)
        if self.read(text + 36, 1):
            # Original XORPS memory operands: current chunk BEFORE current mask,
            # and the mask is fetched anew for the second block.
            for offset in (0, 16):
                chunk = self.read(text + offset, 16)
                mask = self.read(0x1431F7D90, 16)
                self.write(text + offset, 16, chunk ^ mask)
            for offset in range(32, 37):
                self.write(text + offset, 1, self.read(text + offset, 1) ^ 0x51)
        self.invoke(0x1408ED8F0, self.output, _CPP, 0x2BA, text)
        return self.output

    def mode_child_error(self) -> int:
        held = self.read(0x1431F7FE0, 16)
        self.write(self.at(0x90), 4, 0xF0D9D89E)
        guard, text = 0x14427F4C4, 0x14427F4B0
        if self.initializing(guard):
            self.write(text, 16, held)
            self.write(text + 16, 4, self.read(self.at(0x90), 4))
            self.registered(guard, 0x143057C90)
        if self.read(text + 19, 1):
            self.decode(text, 0x1431F8270, 1, 4, 0xF0)
        return self.append_forward(self.at(0x50), 0x140914610, text, 0x2C0, 0x1431F8270, 0xF0)

    def decoder_error(self) -> int:
        self.write(self.file + 0x80, 4, 0)
        self.write(self.file + 0x48, 4, 0x2E)
        self.write(self.file + 0x4C, 4, 0x2E)
        self.error(self.at(0x50), 0x2E)
        self.cleanup(self.at(0x50))
        held = self.read(0x1431F8180, 16)
        self.write(self.at(0x90), 4, 0xD7D296D1)
        self.write(self.at(0x94), 2, 0xD7C2)
        guard, text = 0x14427F4E0, 0x14427F4C8
        if self.initializing(guard):
            self.write(text, 16, held)
            self.write(text + 16, 4, self.read(self.at(0x90), 4))
            self.write(text + 20, 2, self.read(self.at(0x94), 2))
            self.write(text + 22, 1, 0xB6)
            self.registered(guard, 0x143057DB0)
        if self.read(text + 22, 1):
            self.decode(text, 0x1431F6E20, 1, 7, 0xB6)
        self.invoke(0x1408ED8F0, self.output, _CPP, 0x2D7, text)
        return self.output

    def refill_error(self) -> int:
        held = self.read(0x1431F81E0, 16)
        guard, text = 0x14427F564, 0x14427F550
        if self.initializing(guard):
            self.write(text, 16, held)
            self.write(text + 16, 1, 0xF6)
            self.registered(guard, 0x143057EB0)
        flag = self.read(text + 16, 1)
        if flag:
            mask = self.read(0x1431AD060, 16)
            self.write(text, 16, self.read(text, 16) ^ mask)
            self.write(text + 16, 1, flag ^ 0xF6)
        return self.append_forward(self.at(0x50), 0x140914B60, text, 0x2FA, 0x1431AD060, 0xF6)

    def direct_error(self) -> int:
        self.write(self.file + 0x48, 4, 0x25)
        self.write(self.file + 0x4C, 4, 0x25)
        last = self.invoke(self.read(0x143198A88), result=True)
        self.write(self.file + 0x50, 4, last)
        self.error(self.at(0x50), 0x25)
        self.cleanup(self.at(0x50))
        guard, text = 0x14427F568, 0x143DA7858
        if self.initializing(guard):
            self.write(text, 4, 0x53565265)
            self.write(text + 4, 4, 0x45455217)
            self.write(text + 8, 2, 0x4558)
            self.write(text + 10, 1, 0x37)
            self.registered(guard, 0x143057ED0)
        flag = self.read(text + 10, 1)
        if flag:
            for offset in range(10):
                self.write(text + offset, 1, self.read(text + offset, 1) ^ 0x37)
            self.write(text + 10, 1, flag ^ 0x37)
        self.invoke(0x1408ED8F0, self.output, _CPP, 0x30D, text)
        return self.output

    def decoder(self) -> int:
        offset = self.read(self.file + 0xA0)
        end = self.read(self.file + 0x98)
        self.write(self.at(0x48), 8, end - offset)
        self.write(self.at(0xB0), 8, self.remaining)
        self.write(self.at(0x38), 4, 1)
        state = self.read(self.file + 0x88)
        self.write(self.at(0x30), 8, state)
        self.write(self.at(0x28), 8, self.at(0xB0))
        self.write(self.at(0x20), 4, 0)
        base = self.read(self.file + 0x90)
        raw = _call(
            self.decoder_calls,
            0x14178AE30,
            (
                base,
                offset,
                self.at(0x48),
                self.destination,
                self.at(0x20),
                self.at(0x28),
                self.at(0x30),
                self.at(0x38),
            ),
            width=8,
        )
        if raw & _U32 == 0xFFFFFFFE or self.read(self.at(0xB0)) != self.remaining:
            return self.decoder_error()
        consumed = self.read(self.at(0x48))
        self.write(self.file + 0xA0, 8, self.read(self.file + 0xA0) + consumed)
        self.write(self.file + 0x48, 4, 0)
        self.write(self.at(0x50), 16, 0)
        self.write(self.at(0x60), 16, 0)
        self.write(self.at(0x70), 8, 0)
        self.write(self.at(0x78), 1, 0)
        self.invoke(0x1402BD890, self.at(0x50))
        return self.success()

    def buffered(self) -> int:
        budget = self.profile.maximum_buffer_iterations
        while True:
            if not budget:
                raise UnresolvedReplayTaskRebuild("File Read buffer-iteration budget exhausted")
            budget -= 1
            chunk = min(self.remaining, self.read(self.file + 0x58))
            source = self.read(self.file + 0x70)
            self.invoke(0x142D6E3B1, self.destination, source, chunk)
            self.destination = (self.destination + chunk) & _U64
            held_remainder = (self.read(self.file + 0x58) - chunk) & _U64
            self.write(self.file + 0x58, 8, held_remainder)
            self.write(self.file + 0x70, 8, self.read(self.file + 0x70) + chunk)
            self.write(self.file + 0x40, 8, self.read(self.file + 0x40) + chunk)
            self.remaining = (self.remaining - chunk) & _U64
            if not self.remaining:
                return self.success()
            if held_remainder:
                continue
            self.zero(self.at(0x50))
            self.invoke(0x140915600, self.file, self.at(0x50))
            if self.read(self.at(0x68)):
                return self.refill_error()
            self.write(self.at(0x78), 1, 1)
            self.cleanup(self.at(0x50))

    def run(self) -> int:
        self.write(self.at(0x48), 8, self.output)
        self.zero(self.at(0x80))
        self.invoke(0x140916440, self.file, self.at(0x80))
        if self.read(self.at(0x98)):
            return self.preflight_error()
        self.write(self.at(0xA8), 1, 1)
        self.cleanup(self.at(0x80))
        if not self.remaining:
            return self.success()
        mode = self.read(self.file + 0x80, 4)
        if mode:
            if mode == 3:
                return self.mode_error()
            if mode == 1:
                self.zero(self.at(0x50))
                self.invoke(0x140916040, self.file, self.at(0x50))
                if self.read(self.at(0x68)):
                    return self.mode_child_error()
                self.write(self.at(0x78), 1, 1)
                self.cleanup(self.at(0x50))
            return self.decoder()
        end = (self.read(self.file + 0x40) + self.remaining) & _U64
        if end > self.read(self.file + 0x30):
            self.write(self.file + 0x48, 4, 0x24)
            self.write(self.file + 0x4C, 4, 0x24)
            self.error(self.output, 0x24)
            return self.output
        if self.read(self.file + 0x56, 1):
            return self.buffered()
        expected = self.remaining & _U32
        self.write(self.at(0x48), 8, 0)
        raw = self.invoke_opaque(
            0x14093A930, self.read(self.file + 0x28), self.destination, expected, self.at(0x48)
        )
        actual = self.read(self.at(0x48)) & _U32
        self.write(self.file + 0x40, 8, self.read(self.file + 0x40) + actual)
        if raw is None:
            raise ValueError("File Read backend must supply rawRAX when source consumes AL")
        _unsigned(raw, 8, "File Read backend rawRAX")
        if not raw & 255 or actual != expected:
            return self.direct_error()
        self.write(self.file + 0x48, 4, 0)
        return self.success()


def bind_replay_file_read(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    variadic_calls: ReplayTaskRebuildCalls,
    decoder_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayFileReadProfile,
) -> ReplayTaskRebuildCalls:
    """Own only complete140916db0, never default a missing reached child to success.

    variadic_calls140a08840 takes(out,0,cpp,line,FORMAT_HOME,VA_LIST_HOME).
    decoder_calls14178ae30 takes the four native register args followed by
    HOME ADDRESSES20/28/30/38, not their eagerly sampled values. The provider
    owns actual entry read ordering/widths and the repeated lateflaghome38 read.
    These dedicated channels do not change ordinary Calls users of either body.

    All GS/TLS/current data, constructor/codec, mode/refill/backend, memcpy,
    details/append/forward/augmentation, atomic virtual and Result cleanup
    services remain actual required effects. No native backend, empty globals,
    error Result, formatter, codec or restored File/World state is supplied.
    Logical frame remains live through every callback and unmaps on failure.
    Earlier effects survive refusal. Native physical stack/cookie, concurrent
    mutation, exceptions/unwinding and fault equivalence are excluded.
    """
    _validate(context, calls)
    _validate(context, variadic_calls)
    _validate(context, decoder_calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual File Read atomic/local effects required")
    if not isinstance(profile, ReplayFileReadProfile):
        raise ValueError("explicit File Read local/GS/budget profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _READ:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 4 or data is not None:
            raise ValueError("malformed File Read call")
        _validate(context, calls, *args)
        with _local(memoryview(bytearray(profile.frame)), bind_local) as frame:
            return _Read(
                context, bound, variadic_calls, decoder_calls, atomics, profile, *args, frame
            ).run()

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
