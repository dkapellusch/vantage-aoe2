"""Build54800 complete normal Building saved reader141297f00.

Source: building-saved-reader-source-v1, whole34284-byte span. Every reached
Unit/Input/Result/behavior/production/owner/vector/RTTI/runtime child is real
and mandatory. Nonzero Result decoration/TLS and native faults/EH refuse at
their frontier. No physical stack/register/cookie/concurrency or World parity.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from .replay_binary32 import compare_binary32, signed16_binary32
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

_U64 = (1 << 64) - 1
_ENTRY, _VERSION = 0x141297F00, 0x1440A0D94
_Destination = int | Callable[[], int]


@dataclass(frozen=True, slots=True)
class ReplayBuildingSavedScratch:
    """E18-byte coherent working-RSP seed; RBP is frame+100.

    All 67 independent Result48 locals, scalar/count/tuple/decode locals and
    explicit argument slots remain live/current. Cookie atE18, saved registers
    and physical nested-call stack aliases are excluded. Untouched bytes and
    padding preserve their explicit seeds. Opaque R9 is not an inferred World.
    """

    reader: bytes

    def __post_init__(self) -> None:
        if type(self.reader) is not bytes or len(self.reader) != 0xE18:
            raise ValueError("explicit E18-byte Building reader seed required")


class _BuildingRead:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        imports: ReplayTaskRebuildCalls,
        atomics: ReplayUnitAIMapAtomics,
        frame: int,
        subject: int,
        output: int,
        stream: int,
    ) -> None:
        self.c, self.calls, self.imports, self.atomics = context, calls, imports, atomics
        self.frame, self.b, self.s, self.out, self.stream = (
            frame,
            frame + 0x100,
            subject,
            output,
            stream,
        )

    def r(self, address: int, width: int) -> int:
        return _read(self.c, address, width)

    def w(self, address: int, width: int, value: int) -> None:
        _write(self.c, address, width, value)

    def call(self, target: int, args: tuple[int, ...], width: int | None = None) -> int:
        return _call(self.calls, target, args, width=width)

    def terminal(self, slot: int, args: tuple[int, ...], width: int | None = None) -> int:
        return _call(self.imports, self.r(slot, 8), args, width=width)

    def version(self) -> int:
        return _signed(self.r(_VERSION, 4), 4)

    def zero(self, offset: int) -> int:
        result = self.b + offset
        for delta in (0, 16, 32):
            self.w(result + delta, 16, 0)
        return result

    def done(self, result: int, cleanup: str = "final") -> None:
        if self.r(result + 24, 8):
            raise UnresolvedReplayTaskRebuild(
                "Building saved reader reached returned-error metadata/TLS frontier"
            )
        self.w(result + 40, 1, 1)
        if cleanup == "inline":
            control = self.r(result + 32, 8)
            if control:
                _release(self.c, control, self.calls, self.atomics)
            self.call(0x1402BD890, (result,))
        elif cleanup == "pair":
            self.call(0x1408EE150, ((result + 24) & _U64,))
            self.call(0x1402BD890, (result,))
        else:
            self.call(0x140900620, (result,))

    def io(
        self, offset: int, destination: _Destination, width: int, cleanup: str = "final"
    ) -> None:
        result = self.zero(offset)
        destination = destination() if callable(destination) else destination
        target = self.r(self.r(self.stream, 8) + 24, 8)
        self.call(target, (self.stream, result, destination & _U64, width))
        self.done(result, cleanup)

    def child(
        self,
        offset: int,
        target: int,
        args: Callable[[int], tuple[int, ...]],
        cleanup: str = "final",
    ) -> None:
        result = self.zero(offset)
        self.call(target, args(result))
        self.done(result, cleanup)

    def wrap(
        self, offset: int, destination: _Destination, line: int, detail: int, cleanup: str = "final"
    ) -> None:
        result = self.zero(offset)
        destination = destination() if callable(destination) else destination
        self.w(self.frame + 0x28, 8, destination)
        self.w(self.frame + 0x20, 8, self.stream)
        self.call(0x140B81D60, (result, 0x1432B6990, line, detail, self.stream, destination))
        self.done(result, cleanup)

    def stage(self, value: int, operations: tuple[tuple[str, int], ...]) -> int:
        slot = self.b - 0x70
        self.w(slot, 8, value)
        for operation, literal in operations:
            current = self.r(slot, 8)
            self.w(slot, 8, current ^ literal if operation == "^" else current - literal)
        return self.r(slot, 8)

    def master(self) -> int:
        return self.stage(
            self.r(self.s + 16, 8),
            (
                ("-", 0x6A586EB28AC201FC),
                ("-", 0xCF19788B2554E70),
            ),
        )

    def master_id(self) -> int:
        master = self.master()
        return self.stage(
            self.r(master + 24, 8),
            (
                ("^", 0x349E37847AD69F19),
                ("-", 0x47E37DFF0616CE4F),
            ),
        )

    def resource_slot(self, index: int) -> int:
        return (self.r(self.s + 0x860, 8) + 4 + index * 4) & _U64

    def row(self, offset: int) -> int:
        return (self.r(self.s + 0x898, 8) + offset) & _U64

    def append4(self, header: int, value: int) -> None:
        end = self.r(header + 8, 8)
        if end != self.r(header + 16, 8):
            self.w(end, 4, self.r(value, 4))
            self.w(header + 8, 8, self.r(header + 8, 8) + 4)
        else:
            self.call(0x1402B9F50, (header, end, value & _U64))

    def scalar_list(
        self,
        result: int,
        count_slot: int,
        item_result: int,
        value_slot: int,
        width: int,
        header: int,
        target: int,
        *,
        unsigned: bool = False,
        clear: bool = False,
    ) -> None:
        if clear:
            self.w(self.b + count_slot, 4, 0)
        self.io(result, self.b + count_slot, 4)
        index = 0
        count = self.r(self.b + count_slot, 4)
        while index < (count if unsigned else _signed(count, 4)):
            self.io(item_result, self.b + value_slot, width)
            self.call(target, ((self.s + header) & _U64, (self.b + value_slot) & _U64))
            index = (index + 1) & 0xFFFFFFFF
            count = self.r(self.b + count_slot, 4)

    def production_rows(self, recovered: int) -> None:
        self.io(0x538, self.s + 0x8A0, 2)
        count = (self.r(self.s + 0x8A0, 2) + (recovered & 0xFFFF)) & 0xFFFF
        self.w(self.s + 0x8A0, 2, count)
        if _signed(count, 2) <= 0:
            return
        pointer = self.terminal(0x143199DC0, (_signed(count, 2) & _U64, 48), 8)
        self.w(self.s + 0x898, 8, pointer)
        # R12W is the held initial counter; its current backing is reread at
        # the actual end of each iteration, not before the first comparison.
        index = recovered & 0xFFFF
        while _signed(index, 2) < _signed(self.r(self.s + 0x8A0, 2), 2):
            offset = (_signed(index, 2) * 48) & _U64
            self.io(0x238, partial(self.row, offset), 2, "pair")
            self.io(0x658, partial(self.row, offset + 2), 2)
            if self.version() >= 0xC87AE:
                self.io(0x568, partial(self.row, offset + 4), 2)
            else:
                self.w(self.row(offset) + 4, 2, 0xFFFF)
            if self.version() >= 0x419999:
                self.io(0x5C8, partial(self.row, offset + 44), 2)
                self.io(0x598, partial(self.row, offset + 40), 4)
            else:
                pointer = self.r(self.s + 0x898, 8)
                if self.r(pointer + offset + 4, 2) == 0xFFFF:
                    owner = self.r(self.s + 24, 8)
                    unit = _signed(self.r(pointer + offset, 2), 2)
                    table = self.r(owner + 40, 8)
                    self.w(self.frame + 0x20, 4, 0)
                    selected = self.r(table + unit * 8, 8)
                    cast = self.call(0x142D6E3D5, (selected, 0, 0x14411E1B8, 0x14411E1E8, 0), 8)
                    if cast:
                        value = self.call(0x140BB9290, (cast, 0), 2)
                        slot = _signed(self.r(self.s + 0x8A2, 2), 2) * 48
                        self.w(self.row(slot) + 44, 2, value)
            if self.version() >= 0x3E9999:
                self.io(0x5F8, partial(self.row, offset + 8), 24)
            elif self.version() >= 0xD07AE:
                self.w(self.b - 0x48, 8, 0)
                self.io(0x628, self.b + 0x38, 16)
                used = 0
                for kind in range(4):
                    raw = self.r(self.b + 0x38 + kind * 4, 4)
                    if compare_binary32(raw, 0) == 1:
                        self.w(self.b - 0x70, 4, kind)
                        self.w(self.b - 0x6C, 4, raw)
                        # First positive write uses the earlier held row base;
                        # each later element computes its new selected slot.
                        self.w(self.row(offset + used * 8) + 8, 8, self.r(self.b - 0x70, 8))
                        used += 1
                    elif kind == 0:
                        used = self.r(self.b - 0x48, 8)
            else:
                pointer = self.r(self.s + 0x898, 8)
                self.w(self.b - 0x50, 4, 0xFFFFFFFF)
                self.w(self.b - 0x4C, 4, 0)
                raw = self.r(self.b - 0x50, 8)
                for delta in (8, 16, 24):
                    self.w(pointer + offset + delta, 8, raw)
                pointer = self.r(self.s + 0x898, 8)
                unit = _signed(self.r(pointer + offset, 2), 2)
                research = _signed(self.r(pointer + offset + 4, 2), 2)
                slot = _signed(self.r(self.b - 0x68, 2), 2)
                self.w(self.frame + 0x20, 8, 0)
                self.call(
                    0x14127C410,
                    (self.s, slot & 0xFFFFFFFF, research & 0xFFFFFFFF, unit & 0xFFFFFFFF, 0),
                )
            sequence = self.r(self.s + 0x988, 8)
            self.w(self.s + 0x988, 8, sequence + 1)
            self.w(self.row(offset) + 32, 8, sequence)
            current = self.r(self.b - 0x68, 4)
            index = ((current & 0xFFFF) + 1) & 0xFFFF
            self.w(self.b - 0x68, 4, current & 0xFFFF0000 | index)

    def pending(self) -> None:
        self.io(0x688, self.s + 0x8A2, 2)
        self.io(0x6B8, self.s + 0x8A4, 2)
        self.io(0x6E8, self.s + 0x8A6, 1)
        self.w(self.b - 0x68, 4, 0)
        if _signed(self.r(self.s + 0x8A2, 2), 2) <= 0:
            return
        pointer, offset, index = self.r(self.s + 0x898, 8), 0, 0
        while True:
            if (
                _signed(self.r(pointer + offset, 2), 2) > 0
                and _signed(self.r(pointer + offset + 2, 2), 2) > 0
            ):
                item = 0
                while True:
                    unit = _signed(self.r(pointer + offset, 2), 2)
                    owner = self.r(self.s + 24, 8)
                    descriptor = self.call(
                        0x141729140, (owner, self.b - 0x38, unit & 0xFFFFFFFF), 8
                    )
                    value = self.r(descriptor + 4, 4)
                    pointer = self.r(self.s + 0x898, 8)
                    unit = _signed(self.r(pointer + offset, 2), 2)
                    owner = self.r(self.s + 24, 8)
                    catalog = self.r(owner + 24, 8)
                    self.call(0x14111BC60, (catalog, unit & 0xFFFFFFFF, value))
                    catalog = self.r(self.r(self.s + 24, 8) + 24, 8)
                    self.call(0x14111B550, (catalog, 1))
                    item = (item + 1) & 0xFFFFFFFF
                    pointer = self.r(self.s + 0x898, 8)
                    if _signed(item, 4) >= _signed(self.r(pointer + offset + 2, 2), 2):
                        break
                index = self.r(self.b - 0x68, 4)
            index = (index + 1) & 0xFFFFFFFF
            self.w(self.b - 0x68, 4, index)
            offset = (offset + 48) & _U64
            if _signed(index, 4) >= _signed(self.r(self.s + 0x8A2, 2), 2):
                break
        self.out = self.r(self.b - 0x58, 8)

    def restore_recovered(self) -> None:
        recovered = self.r(self.b - 0x60, 8)
        if recovered:
            pointer = self.r(self.s + 0x898, 8)
            self.w(pointer, 2, self.r(recovered + 0x6C, 2))
            self.w(self.r(self.s + 0x898, 8) + 2, 2, 1)
            pointer = self.r(self.s + 0x898, 8)
            self.w(pointer + 4, 2, self.r(recovered + 0x68, 2))
            pointer = self.r(self.s + 0x898, 8)
            self.w(self.b - 0x60, 4, 0xFFFFFFFF)
            self.w(self.b - 0x5C, 4, 0)
            raw = self.r(self.b - 0x60, 8)
            for offset in (8, 16, 24):
                self.w(pointer + offset, 8, raw)
            research = _signed(self.r(recovered + 0x68, 2), 2)
            self.w(self.frame + 0x20, 8, 0)
            unit = self.r(recovered + 0x6C, 4)
            self.call(0x14127C410, (self.s, 0, research & 0xFFFFFFFF, unit, 0))
            self.w(self.s + 0x8A2, 2, self.r(self.s + 0x8A2, 2) + 1)
            self.w(self.s + 0x8A4, 2, self.r(self.s + 0x8A4, 2) + 1)
            self.call(0x140B87D60, (self.r(self.s + 0x8A8, 8), recovered))

    def optional_object(self) -> None:
        self.io(0xAD8, self.b - 0x13, 1)
        if not self.r(self.b - 0x13, 1):
            return
        self.w(self.b + 0x68, 16, 0)
        self.w(self.b + 0x48, 16, 0)
        self.w(self.b + 0x58, 16, 0)
        self.w(self.b + 0x68, 8, 0)
        self.w(self.b + 0x70, 1, 0)
        self.io(0xB08, self.b - 0xB, 1)
        allocated = self.call(0x142D6BA78, (0x4A0,), 8)
        self.w(self.frame + 0x38, 8, allocated)
        if allocated:
            self.call(0x142D6E3B7, (allocated, 0, 0x4A0))
            world = self.r(self.r(self.s + 24, 8) + 8, 8)
            self.w(self.frame + 0x28, 4, 1)
            self.w(self.frame + 0x20, 8, world + 0xA0)
            result = self.call(
                0x1412E1CA0,
                (
                    allocated,
                    self.b + 0x48,
                    self.stream,
                    (world + 0xC0) & _U64,
                    (world + 0xA0) & _U64,
                    1,
                ),
                8,
            )
        else:
            result = 0
        self.w(self.s + 0x908, 8, result)
        self.call(0x1411DF830, (result, self.r(self.s + 24, 8), 1))
        self.child(0xB38, 0x1409076B0, lambda local: (local, self.b + 0x48))
        self.call(0x1408EE150, (self.b + 0x60,))
        self.call(0x1402BD890, (self.b + 0x48,))

    def reserve_words(self) -> None:
        self.w(self.b - 0x10, 4, 0)
        self.io(0xC88, self.b - 0x10, 4)
        header = (self.s + 0x9C8) & _U64
        requested = self.r(self.b - 0x10, 4)
        self.w(self.frame + 0x38, 8, requested)
        begin = self.r(header, 8)
        capacity = (_signed((self.r(header + 16, 8) - begin) & _U64, 8) >> 1) & _U64
        if requested > capacity:
            length = (_signed((self.r(header + 8, 8) - begin) & _U64, 8) >> 1) & _U64
            self.w(self.b - 0x58, 8, length)
            size = requested * 2 & _U64
            if not size:
                allocated = 0
            elif size >= 0x1000:
                expanded = size + 39 & _U64
                if expanded <= size:
                    self.call(0x1402A9460, ())
                    raise UnresolvedReplayTaskRebuild(
                        "native bad-array helper unexpectedly returned"
                    )
                raw = self.call(0x142D6BA78, (expanded,), 8)
                if not raw:
                    self.w(self.frame + 0x20, 8, 0)
                    self.terminal(0x14319A060, (0, 0, 0, 0, 0))
                    raise UnresolvedReplayTaskRebuild("native Watson helper unexpectedly returned")
                allocated = (raw + 39) & _U64 & ~31
                self.w(allocated - 8, 8, raw)
            else:
                allocated = self.call(0x142D6BA78, (size,), 8)
            current_begin = self.r(header, 8)
            copy_size = self.r(header + 8, 8) - current_begin & _U64
            self.call(0x142D6E3DB, (allocated, current_begin, copy_size))
            count = self.r(self.frame + 0x38, 8)
            old_size = self.r(self.b - 0x58, 8)
            self.call(0x140F2D200, (header, allocated, old_size, count))
            requested = self.r(self.b - 0x10, 4)
        index = 0
        while index < requested:
            self.io(0xCB8, self.b, 2)
            self.call(0x14116C430, (self.s + 0x9C8, self.b))
            index = (index + 1) & 0xFFFFFFFF
            requested = self.r(self.b - 0x10, 4)

    def run(self, opaque: int) -> int:
        s, b = self.s, self.b
        self.w(self.frame + 0x38, 8, opaque)
        self.w(b - 0x58, 8, self.out)
        self.w(b - 0x48, 8, self.out)
        self.child(0x88, 0x1412D4F50, lambda result: (s, result, self.stream, opaque), "inline")
        # The parent also uses inline cleanup; preserve its distinct actual
        # sequence rather than the finalizer used by later children.
        self.w(s + 15, 1, 0x50)
        for result, offset, width in (
            (0xB8, 0x951, 1),
            (0xE8, 0x900, 4),
            (0x118, 0x94C, 4),
            (0x148, 0x950, 1),
            (0x178, 0x844, 1),
            (0x1A8, 0x848, 4),
            (0x1D8, 0x890, 4),
            (0x208, 0x8D0, 4),
        ):
            self.io(result, s + offset, width, "inline")
        self.io(0x298, s + 0x8D4, 4)
        self.w(s + 0x8D0, 8, 0)
        for result, offset, width in (
            (0x2C8, 0x8E0, 4),
            (0x2F8, 0x8E4, 4),
            (0x328, 0x8E8, 4),
            (0x358, 0x8EC, 4),
            (0x388, 0x8F0, 4),
            (0x3B8, 0x8F4, 2),
            (0x3E8, 0x910, 1),
        ):
            self.io(result, s + offset, width)
        version = self.version()
        if version < 0xBFDB2:
            if version >= 0xBFD70:
                self.io(0x418, b + 0x78, 4)
            elif version >= 0xA8A3D:
                self.io(0x448, b + 0x7C, 4)
        allocated = self.call(0x142D6BA78, (20,), 8)
        if allocated:
            self.w(allocated, 16, 0)
            self.w(allocated + 16, 4, 0)
        old = self.r(s + 0x860, 8)
        self.w(s + 0x860, 8, allocated)
        if old:
            self.call(0x142D6BAB4, (old, 20))
        self.wrap(0x478, lambda: self.r(s + 0x860, 8), 0x341, 0x1432B6958)
        for index in range(4):
            self.wrap(
                0x268,
                partial(self.resource_slot, index),
                0x345,
                0x1432B69F8,
                "pair",
            )
        for offset in (0x850, 0x8A8):
            target = self.r(self.r(s, 8) + 0x8F8, 8)
            self.w(s + offset, 8, self.call(target, (s,), 8))
        self.io(0x4A8, s + 0x84D, 1)
        self.child(0x4D8, 0x140B88C50, lambda result: (self.r(s + 0x850, 8), result, self.stream))
        self.w(b - 0x60, 8, 0)
        self.w(b - 0x68, 4, 0)
        recovered = 0
        if self.version() < 0xC87AE:
            self.child(
                0x508, 0x140B88C50, lambda result: (self.r(s + 0x8A8, 8), result, self.stream)
            )
            action = self.call(0x140B89440, (self.r(s + 0x8A8, 8),), 8)
            self.w(b - 0x60, 8, action)
            if action:
                recovered = 1
                self.w(b - 0x68, 4, 1)
        self.production_rows(recovered)
        self.pending()
        self.child(0x718, 0x140B88C50, lambda result: (self.r(s + 0x8A8, 8), result, self.stream))
        self.restore_recovered()
        if self.master_id() & 0xFFFF == 0x114:
            world = self.r(self.r(s + 24, 8) + 8, 8)
            registry = self.r(world + 0x900, 8)
            if registry:
                self.w(s + 0x8F8, 8, self.call(0x141229A90, (registry, s), 8))
        version = self.version()
        if version == 0xAA3D7:
            self.w(b + 4, 4, 0)
            self.io(0x748, b + 4, 4)
            index = 0
            while _signed(index, 4) < _signed(self.r(b + 4, 4), 4):
                self.io(0x778, b + 0x80, 4)
                index = index + 1 & 0xFFFFFFFF
            self.w(b + 0x28, 8, 0)
            self.w(b + 0x30, 4, 0)
            self.io(0x7A8, b + 0x28, 12)
            self.io(0x7D8, b + 0x28, 12)
            version = self.version()
        if version >= 0xAA666:
            self.io(0x808, s + 0x914, 12)
            self.io(0x838, s + 0x914, 12)
            self.io(0x868, s + 0x92C, 4)
            self.io(0x898, s + 0x930, 4)
            version = self.version()
            if version >= 0xAA666:
                self.io(0x8C8, s + 0x934, 4)
            else:
                self.w(s + 0x934, 4, 0)
        else:
            self.w(s + 0x934, 4, 0)
        version = self.version()
        if version >= 0xAAB85:
            self.io(0x8F8, b - 0xC, 1)
            version = self.version()
        if version >= 0xB6E14:
            self.io(0x928, b - 0x14, 1)
            flag = self.r(b - 0x14, 1)
        else:
            flag = 0
            self.w(b - 0x14, 1, 0)
        self.call(0x141296B90, (s, flag))
        if self.version() >= 0xB8A3D:
            self.io(0x958, s + 0x911, 1)
        else:
            self.w(s + 0x911, 1, 0)
        if self.version() >= 0xCDEB8:
            self.io(0x988, s + 0x938, 1)
        if self.version() >= 0x142147:
            self.io(0x9B8, b - 0x18, 2)
            index = _signed(self.r(b - 0x18, 2), 2)
            pointer = 0
            if index >= 0:
                opaque = self.r(self.frame + 0x38, 8)
                table = self.r(opaque + 0xC0, 8)
                pointer = self.r(table + index * 8, 8)
            self.w(s + 0x940, 8, pointer)
        if self.version() >= 0x1A028F:
            self.io(0x9E8, s + 0x8D8, 4)
            self.w(s + 0x8D8, 4, 0)
        for gate, result, count, item, value, header in (
            (0x3D07AE, 0xA18, 0x14, 0xA48, 0x10, 0x828),
            (0x3F4CCC, 0xA78, 0x1C, 0xAA8, 0x18, 0x968),
        ):
            if self.version() >= gate:
                self.io(result, b + count, 4)
                index = 0
                while _signed(index, 4) < _signed(self.r(b + count, 4), 4):
                    self.io(item, b + value, 4)
                    self.append4(s + header, b + value)
                    index = index + 1 & 0xFFFFFFFF
        if self.version() >= 0x19147A:
            self.optional_object()
        if self.version() >= 0x326666:
            self.scalar_list(0xB68, 0x20, 0xB98, 0x24, 4, 0x990, 0x140B53800)
        threshold = _signed(self.call(0x140BB9290, (self.master(), 0), 2), 2)
        comparison = compare_binary32(self.r(s + 0x900, 4), signed16_binary32(threshold))
        if comparison is not None and comparison >= 0:
            catalog = self.r(self.r(s + 24, 8) + 24, 8)
            self.call(0x14111B540, (catalog, 1))
            owner = self.r(s + 24, 8)
            catalog = self.r(owner + 24, 8)
            unit = _signed(self.master_id() & 0xFFFF, 2)
            descriptor = self.call(0x141729140, (owner, b - 0x28, unit & 0xFFFFFFFF), 8)
            self.call(0x14111A520, (catalog, self.r(s + 8, 4), descriptor))
        if self.version() >= 0x3D3333:
            self.scalar_list(
                0xBC8, 0xC, 0xBF8, -8, 2, 0x9B0, 0x14116C430, unsigned=True, clear=True
            )
            self.scalar_list(0xC28, 8, 0xC58, -4, 2, 0x9E0, 0x14116C430, unsigned=True, clear=True)
        if self.version() >= 0x40B333:
            self.reserve_words()
        if self.version() >= 0x421999:
            self.io(0xCE8, s + 0x980, 1)
        for offset in (0, 8, 16, 24, 32):
            self.w(self.out + offset, 8, 0)
        self.w(self.out + 40, 1, 0)
        return self.out


def read_replay_saved_building(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    opaque: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayBuildingSavedScratch,
    mxcsr: int,
    imports: ReplayTaskRebuildCalls | None = None,
) -> int:
    """All normal current/historical branches with explicit mandatory children.

    Numerical comparisons use masked MXCSR1f80 with DAZ/FTZ off. Direct IAT
    calloc/Watson calls use explicit terminal imports, separately from recursive
    ordinary child dispatch. Source-written stack tuples admit their scalar
    operands, not arbitrary physical nested-stack argument aliases.
    """
    _validate(context, calls, address, output, stream, opaque)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Building atomic/local providers required")
    if not isinstance(scratch, ReplayBuildingSavedScratch):
        raise ValueError("explicit Building reader seed required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("Building reader requires masked default MXCSR1f80")
    with _local(memoryview(bytearray(scratch.reader)), bind_local) as frame:
        return _BuildingRead(context, calls, terminal, atomics, frame, address, output, stream).run(
            opaque
        )


def bind_replay_building_saved(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: ReplayBuildingSavedScratch,
    mxcsr: int,
    imports: ReplayTaskRebuildCalls | None = None,
) -> ReplayTaskRebuildCalls:
    """Bind only the actual four-argument Building reader, no semantic stubs."""
    _validate(context, calls)
    terminal = calls if imports is None else imports
    _validate(context, terminal)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Building atomic/local providers required")
    if not isinstance(scratch, ReplayBuildingSavedScratch) or mxcsr != 0x1F80:
        raise ValueError("explicit Building reader seed and MXCSR1f80 required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target != _ENTRY:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 4 or data is not None:
            raise ValueError("Building saved reader requires four scalar arguments")
        return read_replay_saved_building(
            context,
            *args,
            calls=bound,
            atomics=atomics,
            bind_local=bind_local,
            scratch=scratch,
            mxcsr=mxcsr,
            imports=terminal,
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
