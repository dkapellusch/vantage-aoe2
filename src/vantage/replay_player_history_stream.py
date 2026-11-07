"""Complete normal build54800 26142B141634b00 history stream caller.

All legacy/death/array branches and 46 fixed Result checks are retained. Each
unsupported returned-error branch refuses before its first diagnostic/TLS
instruction, with earlier effects preserved. Actual Input/marker/Result/vector,
atomic and selected current calloc effects are mandatory. Explicit958B logical
locals exclude native physical homes, cookie/EH/fault/concurrency and incidental
volatile registers. Mixed FP uses the actual provider under maskedMXCSR1f80;
no host floating arithmetic or successful unknown child is supplied.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .replay_player_construction_support import (
    ReplayPlayerMarkerCall,
    ReplayPlayerSupportFloatingCalls,
)
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
_VERSION = 0x1440A0D94

# site: (logical fixed Result, width, cleanup, first unsupported error instruction)
_SITES: dict[int, tuple[int, int, str, int]] = {
    0x141634DA7: (0xE8, 4, "inline", 0x141634DB6),
    0x141634FAC: (0x118, 4, "inline", 0x141634FBB),
    0x1416351C8: (0x448, 4, "finalize", 0x1416351DA),
    0x14163558E: (0x328, 2, "pair", 0x141635933),
    0x1416355F9: (0x2F8, 2, "pair", 0x1416357D3),
    0x14163566D: (0x4D8, 4, "finalize", 0x14163567F),
    0x141635AF9: (0x4A8, 2, "finalize", 0x141635B27),
    0x141635CE9: (0x358, 1, "pair", 0x141635D23),
    0x141635EE7: (0x148, 1, "inline", 0x141636CB6),
    0x141635F70: (0x3B8, 4, "pair", 0x141636BAA),
    0x141635FE4: (0x388, 4, "pair", 0x141636543),
    0x141636048: (0x508, 4, "finalize", 0x1416363E3),
    0x1416360B7: (0x538, 4, "finalize", 0x141636683),
    0x141636118: (0x568, 1, "finalize", 0x1416367C3),
    0x141636187: (0x598, 4, "finalize", 0x141636913),
    0x1416361E8: (0x5C8, 4, "finalize", 0x141636A64),
    0x141636277: (0x5F8, 4, "finalize", 0x141636289),
    0x141636E68: (0x628, 4, "finalize", 0x141636E7A),
    0x141636FE9: (0x658, 4, "finalize", 0x141636FFB),
    0x14163719F: (0x688, 4, "finalize", 0x1416371B1),
    0x14163734F: (0x6B8, 4, "finalize", 0x141637361),
    0x1416374F9: (0x6E8, 4, "finalize", 0x14163750B),
    0x1416376C9: (0x718, 4, "finalize", 0x1416376DB),
    0x141637899: (0x748, 4, "finalize", 0x1416378AB),
    0x141637A59: (0x778, 4, "finalize", 0x141637A6B),
    0x141637C09: (0x7A8, 4, "finalize", 0x141637C1B),
    0x141637DA9: (0x7D8, 4, "finalize", 0x141637DBB),
    0x141637EEE: (0x808, 4, "finalize", 0x141637F00),
    0x14163803E: (0x838, 4, "finalize", 0x141638050),
    0x14163813F: (0x868, 4, "finalize", 0x141638151),
    0x14163827E: (0x898, 4, "finalize", 0x141638290),
    0x1416383EF: (0x8C8, 4, "finalize", 0x141638401),
    0x14163859D: (0x8F8, 4, "finalize", 0x1416385AF),
    0x14163878F: (0x928, 4, "finalize", 0x1416387A0),
    0x141638953: (0x3E8, 2, "pair", 0x141638DFC),
    0x1416389F4: (0x178, 4, "inline", 0x141638F53),
    0x141638AC3: (0x1A8, 2, "inline", 0x141639103),
    0x141638B9B: (0x1D8, 4, "inline", 0x14163928C),
    0x141638C45: (0x208, 4, "inline", 0x141638C57),
    0x1416394D0: (0x238, 4, "inline", 0x1416394E2),
    0x141639720: (0x268, 4, "inline", 0x141639732),
    0x141639950: (0x298, 2, "inline", 0x141639962),
    0x141639B70: (0x2C8, 2, "inline", 0x141639B82),
}


@dataclass(frozen=True, slots=True)
class ReplayHistoryStreamScratch:
    """Live logical958B data seed, native RBP=frame100.

    History home98, output homeA0 (later first vector header), index90,
    death counterAC and narrow legacy discardB0/B4 share this actual backing.
    Only reached source stores replace seeds. Cookie958 and physical register/
    incoming homes are excluded; live effective aliases are preserved.
    """

    frame: bytes

    def __post_init__(self) -> None:
        if type(self.frame) is not bytes or len(self.frame) != 0x958:
            raise ValueError("explicit958-byte history stream frame required")


@dataclass(slots=True)
class _HistoryStream:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    imports: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics
    floating: ReplayPlayerSupportFloatingCalls
    history: int
    output: int
    stream: int
    frame: int
    marker_word: int = 0

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def local(self, offset: int) -> int:
        return (self.frame + offset) & _U64

    def invoke(self, target: int, *args: int, result: bool = False) -> int:
        return _call(self.calls, target, args, width=8 if result else None)

    def version(self) -> int:
        return _signed(self.read(_VERSION, 4), 4)

    def zero(self, result: int) -> None:
        for delta in (0, 16, 32):
            self.write(result + delta, 16, 0)

    def finish(self, offset: int, cleanup: str, error: int) -> None:
        result = self.local(offset)
        if self.read(result + 24):
            raise UnresolvedReplayTaskRebuild(
                f"history returned-error frontier{error:x} before diagnostic/TLS instruction"
            )
        self.write(result + 40, 1, 1)
        if cleanup == "inline":
            control = self.read(result + 32)
            if control:
                _release(self.context, control, self.calls, self.atomics)
            self.invoke(0x1402BD890, result)
        elif cleanup == "pair":
            self.invoke(0x1408EE150, result + 24)
            self.invoke(0x1402BD890, result)
        else:
            self.invoke(0x140900620, result)

    def input(self, site: int, destination: Callable[[], int]) -> None:
        offset, width, cleanup, error = _SITES[site]
        result = self.local(offset)
        self.zero(result)
        # Where destination computation consumes backing, source loads it before
        # the current stream vptr/virtual18. Pure LEA changes no memory ordering.
        target_destination = destination() & _U64
        table = self.read(self.stream)
        target = self.read(table + 24)
        self.invoke(target, self.stream, result, target_destination, width)
        # Both InputRAX and markerRAX are unconsumed by this native caller.
        self.finish(offset, cleanup, error)

    def field(self, site: int, offset: int) -> None:
        self.input(site, lambda: self.history + offset)

    def marker(self, ordinal: int) -> None:
        offset, label, cleanup, error = (
            (0xB8, 0x1432ED6C0, "inline", 0x141634B98),
            (0x478, 0x1432ED6D0, "finalize", 0x141635391),
            (0x418, 0x1432ED6E0, "finalize", 0x141639DB5),
        )[ordinal]
        self.zero(self.local(offset))
        expected = self.read(0x1440A0DAE + ordinal, 1)
        self.write(self.local(0x20), 1, expected)
        if ordinal == 0:
            self.marker_word = self.read(0x1432ED700, 4)
        invocation = ReplayPlayerMarkerCall(
            self.local(offset),
            self.stream,
            label,
            self.marker_word,
            expected,
        )
        if self.floating.call is None:
            raise UnresolvedReplayTaskRebuild(
                "reached history marker mixed-FP provider unavailable"
            )
        self.floating.call(0x14162CD70, invocation)
        self.finish(offset, cleanup, error)

    def calloc(self, count: int, width: int) -> int:
        target = self.read(0x143199DC0)
        return _call(self.imports, target, (count & _U64, width), width=8)

    def rows(self) -> None:
        capacity = _signed(self.read(self.history + 0x20, 4), 4) & _U64
        allocated = self.calloc(capacity, 4)
        self.write(self.history, 8, allocated)
        version = self.version()
        index = 0
        count = _signed(self.read(self.history + 0x1C, 4), 4)
        if version >= 0xA91EB:
            while _signed(index, 4) < count:
                held_index = _signed(index, 4)
                self.input(0x14163558E, lambda: self.read(self.history) + held_index * 4)  # noqa: B023 - input evaluates this immediately; it never escapes
                self.input(0x1416355F9, lambda: self.read(self.history) + 2 + held_index * 4)  # noqa: B023 - input evaluates this immediately; it never escapes
                index = (index + 1) & _U32
                count = _signed(self.read(self.history + 0x1C, 4), 4)
        else:
            site = 0x141635AF9 if version >= 0x9D47A else 0x141635CE9
            while _signed(index, 4) < count:
                self.input(site, lambda: self.read(self.history) + _signed(index, 4) * 4)  # noqa: B023 - input evaluates this immediately; it never escapes
                index = (index + 1) & _U32
                count = _signed(self.read(self.history + 0x1C, 4), 4)

    def deaths(self) -> None:
        link = (self.history + 8) & _U64
        self.input(0x14163566D, lambda: self.local(0xAC))
        if _signed(self.read(self.local(0xAC), 4), 4) <= 0:
            return
        while True:
            node = self.calloc(1, 32)
            self.input(0x141635EE7, lambda: node)  # noqa: B023 - input evaluates this immediately; it never escapes
            self.input(0x141635F70, lambda: node + 4)  # noqa: B023 - input evaluates this immediately; it never escapes
            if self.version() >= 0x951EB:
                self.input(0x141635FE4, lambda: node + 12)  # noqa: B023 - input evaluates this immediately; it never escapes
                self.input(0x141636048, lambda: node + 16)  # noqa: B023 - input evaluates this immediately; it never escapes
            else:
                self.write(node + 12, 8, 0)
            version = self.version()
            if version >= 0x95999:
                self.input(0x1416360B7, lambda: node + 20)  # noqa: B023 - input evaluates this immediately; it never escapes
            elif version >= 0x9570A:
                self.input(0x141636118, lambda: node + 20)  # noqa: B023 - input evaluates this immediately; it never escapes
            else:
                self.write(node + 20, 4, 0)
            version = self.version()
            if version >= 0x9D47A:
                self.input(0x141636187, lambda: node + 8)  # noqa: B023 - input evaluates this immediately; it never escapes
            elif version >= 0x95EB8:
                self.input(0x1416361E8, lambda: node + 8)  # noqa: B023 - input evaluates this immediately; it never escapes
            else:
                self.write(node + 8, 4, 0)
            self.write(link, 8, node)
            link = (node + 24) & _U64
            count = (self.read(self.local(0xAC), 4) - 1) & _U32
            self.write(self.local(0xAC), 4, count)
            if _signed(count, 4) <= 0:
                break
        # The source skips this reload if the first death-count test failed.
        self.history = self.read(self.local(0x98))

    def arrays(self) -> None:
        start = 0
        count_pointer = (self.history + 0x24) & _U64
        if self.version() >= 0x3D0000:
            self.input(0x14163878F, lambda: count_pointer)
        else:
            self.write(count_pointer, 4, 9)
            start = 1
        if self.version() < 0x3D0000:
            self.write(self.local(0x90), 4, start)
            count = _signed(self.read(count_pointer, 4), 4)
            index = start
            while _signed(index, 4) < count:
                self.input(0x141638953, lambda: self.local(0xB0))
                index = (self.read(self.local(0x90), 4) + 1) & _U32
                self.write(self.local(0x90), 4, index)
                count = _signed(self.read(count_pointer, 4), 4)
        header = (self.history + 0xB0) & _U64
        self.write(self.local(0xA0), 8, header)
        requested = _signed(self.read(count_pointer, 4), 4) & _U64
        self.invoke(0x14162CB30, header, requested, self.local(0x30))
        index = start
        self.write(self.local(0x90), 4, index)
        count_word = self.read(count_pointer, 4)
        while _signed(index, 4) < _signed(count_word, 4):
            self.input(0x1416389F4, lambda: self.read(header) + _signed(index, 4) * 4)  # noqa: B023 - input evaluates this immediately; it never escapes
            index = (self.read(self.local(0x90), 4) + 1) & _U32
            self.write(self.local(0x90), 4, index)
            count_word = self.read(count_pointer, 4)
            header = self.read(self.local(0xA0))
        # Native EAX holds this count through the following version read. If the
        # legacy loop executes, its last read replaces EAX. No later count read
        # is inserted before the second resize's sign extension at141638b48.
        if self.version() < 0x3D0000:
            self.write(self.local(0x90), 4, start)
            index = start
            while _signed(index, 4) < _signed(count_word, 4):
                self.input(0x141638AC3, lambda: self.local(0xB4))
                index = (self.read(self.local(0x90), 4) + 1) & _U32
                self.write(self.local(0x90), 4, index)
                count_word = self.read(count_pointer, 4)
        self.history = self.read(self.local(0x98))
        header = (self.history + 0xC8) & _U64
        self.invoke(0x14162CB30, header, _signed(count_word, 4) & _U64, self.local(0x30))
        index = start
        count = _signed(self.read(count_pointer, 4), 4)
        while _signed(index, 4) < count:
            self.input(0x141638B9B, lambda: self.read(header) + _signed(index, 4) * 4)  # noqa: B023 - input evaluates this immediately; it never escapes
            index = (index + 1) & _U32
            count = _signed(self.read(count_pointer, 4), 4)
            header = (self.history + 0xC8) & _U64

    def run(self) -> int:
        self.write(self.local(0x98), 8, self.history)
        self.write(self.local(0xA0), 8, self.output)
        self.marker(0)
        self.field(0x141634DA7, 0x1C)
        self.field(0x141634FAC, 0x18)
        self.field(0x1416351C8, 0x20)
        self.marker(1)
        self.rows()
        self.deaths()
        version = self.version()
        if version >= 0xA91EB:
            for site, offset in (
                (0x141636277, 0x2C),
                (0x141636E68, 0x30),
                (0x141636FE9, 0x34),
                (0x14163719F, 0x38),
                (0x14163734F, 0x3C),
                (0x1416374F9, 0x40),
                (0x1416376C9, 0x44),
                (0x141637899, 0x48),
                (0x141637A59, 0x4C),
                (0x141637C09, 0x50),
                (0x141637DA9, 0x54),
                (0x141637EEE, 0x58),
                (0x14163803E, 0x5C),
                (0x14163813F, 0x60),
                (0x14163827E, 0x28),
            ):
                self.field(site, offset)
            version = self.version()
        if version >= 0xAD47A:
            self.field(0x1416383EF, 0x64)
            self.field(0x14163859D, 0x68)
            self.arrays()
            for site, offset in (
                (0x141638C45, 0xE0),
                (0x1416394D0, 0xE4),
                (0x141639720, 0xE8),
                (0x141639950, 0xEC),
                (0x141639B70, 0xF0),
            ):
                self.field(site, offset)
        self.marker(2)
        for offset in (0, 8, 16, 24, 32):
            self.write(self.output + offset, 8, 0)
        self.write(self.output + 40, 1, 0)
        return self.output


def read_replay_history_stream(
    context: ReplayTaskRebuildStorage,
    history: int,
    output: int,
    stream: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayHistoryStreamScratch,
    floating: ReplayPlayerSupportFloatingCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> int:
    """Complete normal caller, with actual reached providers and live local aliases.

    Returned Input/marker RAX is ignored. Fixed Result status alone selects
    success/diagnostic paths; diagnostics refuse before their first instruction.
    The 958B frame remains live through every last marker/cleanup and success
    output write. Native stack/cookie and physical incoming-home aliases remain
    explicitly excluded. Source child providers carry masked defaultMXCSR1f80,
    DAZ/FTZ-off FP behavior; status/unmasked traps are excluded.
    """
    _validate(context, calls, history, output, stream)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if (
        not isinstance(atomics, ReplayUnitAIMapAtomics)
        or not callable(bind_local)
        or not isinstance(scratch, ReplayHistoryStreamScratch)
        or not isinstance(floating, ReplayPlayerSupportFloatingCalls)
    ):
        raise ValueError("actual history atomics/local seed/mixed-FP providers required")
    with _local(memoryview(bytearray(scratch.frame)), bind_local) as frame:
        state = _HistoryStream(
            context, calls, terminal, atomics, floating, history, output, stream, frame
        )
        return state.run()


def bind_replay_history_stream(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayHistoryStreamScratch,
    floating: ReplayPlayerSupportFloatingCalls,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind only141634b00; current IAT-selected targets use terminal imports."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        _validate(context, calls, target)
        if target != 0x141634B00:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 3 or data is not None:
            raise ValueError("malformed three-operand history stream call")
        return read_replay_history_stream(
            context,
            *args,
            calls=calls,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
            floating=floating,
            imports=terminal,
        )

    return ReplayTaskRebuildCalls(dispatch)
