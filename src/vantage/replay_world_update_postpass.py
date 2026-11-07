"""Complete logical World tail [14162ab9e,14162ba9f) and shared94a9.

All nine service categories are explicit. The existing frame remains live;
physical cookie/save/return traffic is excluded, never simulated or bound away.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_world_update_player_links import ReplayWorldUpdatePlayerLinks
from .replay_world_update_player_pass import ReplayWorldUpdatePlayerPass

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_LITERAL = 0x61501AA6ECFD980A


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdatePostpass:
    """Prepared logical EAX return, with unchanged historical phase metadata."""

    world: int
    logical_frame: int
    entry_time: int
    cycle: int
    status: int
    default_time: int
    control_flags: int
    next_address: int | None
    returned_status: int | None


def _invoke(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _value(raw: int | None, width: int, name: str) -> int:
    if raw is None:
        raise ValueError(f"{name} requires its actual scalar annotation")
    _unsigned(raw, width, name)
    return raw


def _eax(raw: int | None, name: str) -> int:
    # Accept a real u64 service word; only the source-consumed low EAX is owned.
    return _value(raw, 8, name) & _U32


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 4) & _U64


class _Postpass:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        phase: ReplayWorldUpdatePlayerLinks | ReplayWorldUpdatePlayerPass,
        virtual: ReplayTaskRebuildCalls,
        cleanup: ReplayTaskRebuildCalls,
        unit_fp: ReplayTaskRebuildCalls,
        geometry: ReplayTaskRebuildCalls,
        format_home: ReplayTaskRebuildCalls,
        record_home: ReplayTaskRebuildCalls,
        runtime: ReplayTaskRebuildCalls,
        watson_home: ReplayTaskRebuildCalls,
    ) -> None:
        self.context, self.calls, self.phase = context, calls, phase
        self.world, self.frame, self.r13 = phase.world, phase.logical_frame, phase.held_r13
        self.virtual, self.cleanup, self.unit_fp = virtual, cleanup, unit_fp
        self.geometry, self.format_home, self.record_home = geometry, format_home, record_home
        self.runtime, self.watson_home = runtime, watson_home

    def _r(self, address: int, width: int) -> int:
        return _read(self.context, address, width)

    def _w(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def _h(self, offset: int) -> int:
        return (self.frame + offset) & _U64

    def _fr(self, offset: int, width: int) -> int:
        return self._r(self._h(offset), width)

    def _fw(self, offset: int, width: int, value: int) -> None:
        self._w(self._h(offset), width, value)

    def _call(self, target: int, args: tuple[int, ...]) -> int | None:
        return _invoke(self.calls, target, args)

    def _stream(self) -> int:
        raw = self._call(0x140E15770, (self._r(self.world + 0x70, 8),))
        return _value(raw, 8, "actual140e15770 RAX")

    def _clock(self) -> int | None:
        # Each caller owns the first EAX consumption, sometimes after a store/read.
        return self._call(0x140E68F70, (self._r(self.world + 0x228, 8),))

    def _postpasses(self) -> None:
        """ab9e..acf2: three differently sampled mutable player headers."""
        self._call(0x140F558A0, (self._r(self.world + 0x130, 8),))
        self._call(0x140F52130, (self._r(self.world + 0x130, 8),))
        self._call(0x140E07CC0, (self._r(0x1442DA8A0, 8),))
        index = 0
        begin = self._r(self.world + 0x768, 8)
        end = self._r(self.world + 0x770, 8)
        if _count(end, begin):
            while True:
                player = self._r(begin + index * 16, 8)
                if player:
                    self._call(0x14114B470, (self._r(player + 0x80, 8),))
                index = (index + 1) & _U32
                begin = self._r(self.world + 0x768, 8)
                end = self._r(self.world + 0x770, 8)
                if not index < _count(end, begin):
                    break
        timing = _eax(
            self._call(
                0x140903E40,
                (
                    0x144353060,
                    0x14369A1D0,
                    0x1191,
                ),
            ),
            "ac31 timing EAX",
        )
        index = 0
        end = self._r(self.world + 0x770, 8)
        begin = self._r(self.world + 0x768, 8)
        if _count(end, begin):
            while True:
                player = self._r(begin + index * 16, 8)
                if player:
                    self._call(0x141229A20, (self._r(player + 0x40, 8),))
                index = (index + 1) & _U32
                end = self._r(self.world + 0x770, 8)
                begin = self._r(self.world + 0x768, 8)
                if not index < _count(end, begin):
                    break
        # ac96 starts with the HELD preceding R8=end/RDX=begin; no new reads.
        index = 0
        if _count(end, begin):
            while True:
                player = self._r(begin + index * 16, 8)
                if player:
                    self._call(0x14115F240, (self._r(player + 0x78, 8),))
                index = (index + 1) & _U32
                begin = self._r(self.world + 0x768, 8)
                end = self._r(self.world + 0x770, 8)
                if not index < _count(end, begin):
                    break
        self._call(0x1416938B0, (self.world,))
        self._call(0x140FDDBF0, (timing,))

    def _round_robin(self) -> None:
        """acf2..ad8e: write before bounds; preserve current RMW and return order."""
        index = _signed(self._r(self.world + 0x188, 4), 4)
        self._w(self.world + index * 4 + 0x18C, 4, 0)
        current = self._r(self.world + 0x188, 4)
        self._w(self.world + 0x188, 4, current + 1)
        end = self._r(self.world + 0x770, 8)
        begin = self._r(self.world + 0x768, 8)
        count = _count(end, begin)
        current = self._r(self.world + 0x188, 4)
        if not _signed(current, 4) < _signed(count & _U32, 4):
            self._w(self.world + 0x188, 4, 0)
        vptr = self._r(self.world, 8)
        target = self._r(vptr + 0x70, 8)
        _invoke(self.virtual, target, (self.world,))
        raw = self._call(0x140903E40, (0x144353060, 0x14369A1D0, 0x11D6))
        self._w(self.world + 0x7D0, 4, _eax(raw, "ad4a timing EAX"))
        raw = self._call(0x141021E00, ())
        self._fw(0x20, 4, 0x11D7)
        receiver = _value(raw, 8, "ad6d actual141021e00 RAX")
        _invoke(
            self.format_home,
            0x1410242D0,
            (
                receiver,
                0,
                0x1432EA178,
                0x1432E98F0,
                self._h(0x20),
            ),
        )
        manager = self._r(self.world + 0x130, 8)
        value = self._r(self.world + 0x7D0, 4)
        manager = self._r(manager + 0x2008, 8)
        self._call(0x140E27920, (manager, value))

    @staticmethod
    def _quotients(clock: int) -> tuple[int, int, int]:
        """ae5c..aebe literal MUL32/IMUL32/high/shift/wrap operations."""
        seconds = ((0x10624DD3 * clock) >> 32) >> 6
        minutes, hours = 0, 0
        if _signed(seconds, 4) > 0x3B:
            high = ((_signed(0x88888889, 4) * _signed(seconds, 4)) >> 32) & _U32
            minutes = (_signed((seconds + high) & _U32, 4) >> 5) & _U32
            minutes = (minutes + (minutes >> 31)) & _U32
            seconds = (seconds + minutes * -60) & _U32
            if _signed(minutes, 4) > 0x3B:
                high = ((_signed(0x88888889, 4) * _signed(minutes, 4)) >> 32) & _U32
                hours = (_signed((minutes + high) & _U32, 4) >> 5) & _U32
                hours = (hours + (hours >> 31)) & _U32
                minutes = (minutes + hours * -60) & _U32
        return hours, minutes, seconds

    def _periodic_output(self) -> None:
        """ae50..af86: current global reads, held slot310 and exact low clock."""
        clock = _eax(self._clock(), "ae5c clock EAX")
        hours, minutes, seconds = self._quotients(clock)
        if not self._r(0x144418590, 4):
            vptr = self._r(self.world, 8)
            receiver = self._r(0x144418588, 8)
            target = self._r(vptr + 0x140, 8)
            _invoke(self.virtual, target, (self.world, receiver, 1))
        else:
            self._fw(0x20, 4, seconds)
            receiver = self._r(0x144418588, 8)
            _invoke(
                self.format_home,
                0x140F3EB40,
                (
                    receiver,
                    0x1432EA230,
                    hours,
                    minutes,
                    self._h(0x20),
                ),
            )
        index = 1
        begin = self._r(self.world + 0x768, 8)
        end = self._r(self.world + 0x770, 8)
        if _count(end, begin) > index:
            while True:
                player = self._r(begin + index * 16, 8)
                if player:
                    vptr = self._r(player, 8)
                    target = self._r(vptr + 0x310, 8)
                    receiver = self._r(0x144418588, 8)
                    first = 1 if not self._r(0x144418590, 4) else 0
                    _invoke(self.virtual, target, (player, receiver, first))
                index = (index + 1) & _U32
                begin = self._r(self.world + 0x768, 8)
                end = self._r(self.world + 0x770, 8)
                if not index < _count(end, begin):
                    break
        stamp = (_eax(self._clock(), "af7e clock EAX") + 1) & _U32
        self._w(0x144418590, 4, stamp)

    def _logging(self) -> bool:
        """ad8e..b044; True means the null-construction jump directly to ba53."""
        skip_world88_read = False
        if self._r(0x1442C3FB4, 4) == 1:
            if self._r(self.world + 0x88, 4) == 1:
                skip_world88_read = True  # ada2 -> af93, not af86.
            else:
                raw = self._clock()
                previous = self._r(0x144418590, 4)
                elapsed = (_eax(raw, "adba clock EAX") - previous) & _U32
                if elapsed > 0x7530 or not previous:
                    if not self._r(0x144418588, 8):
                        owner = self._r(0x1443E4E20, 8)
                        raw = self._call(0x140808540, (owner, self._h(0x78)))
                        output = self._r(_value(raw, 8, "adf1 output RAX"), 8)
                        raw = self._call(0x141451610, (output, self._h(0x218), 0))
                        output = self._r(_value(raw, 8, "adf9 output RAX"), 8)
                        self._call(0x1409002E0, (self._h(0x2C0), 0x1432EA220, output))
                        self._call(0x140A1B220, (self._h(0x218),))
                        owner = self._fr(0x78, 8)
                        if owner:
                            self._call(0x140990140, (owner,))
                        raw = self._call(0x141017300, (self._h(0x2C0), 0x143202350))
                        handle = _value(raw, 8, "ae40 output RAX")
                        self._w(0x144418588, 8, handle)
                        if not handle:
                            return True
                    self._periodic_output()
        if not skip_world88_read and self._r(self.world + 0x88, 4) != 1:
            return False
        if self._r(0x1442C3FB4, 4) != 1:
            return False
        receiver = self._r(0x144418588, 8)
        if not receiver:
            return False
        _invoke(self.format_home, 0x140F3EB40, (receiver, 0x1432EA260))
        index = 1
        begin = self._r(self.world + 0x768, 8)
        end = self._r(self.world + 0x770, 8)
        if _count(end, begin) > index:
            while True:
                player = self._r(begin + index * 16, 8)
                if player:
                    receiver = self._r(0x144418588, 8)
                    text = 0x1432EA270 if self._r(player + 0x89, 1) == 1 else 0x1432EA288
                    _invoke(self.format_home, 0x140F3EB40, (receiver, text, index))
                index = (index + 1) & _U32
                begin = self._r(self.world + 0x768, 8)
                end = self._r(self.world + 0x770, 8)
                if not index < _count(end, begin):
                    break
        receiver = self._r(0x144418588, 8)
        target = self._r(0x14319A228, 8)
        _invoke(self.runtime, target, (receiver,))
        self._w(0x144418588, 8, 0)
        return False

    def _watson(self, fifth: int) -> None:
        self._fw(0x20, 8, fifth)
        target = self._r(0x14319A060, 8)
        _invoke(self.watson_home, target, (0, 0, 0, 0, self._h(0x20)))

    def _cleanup_string(self, offset: int, constant: int, bad_site: int, r14: int) -> bool:
        """Actual free/reset, or returning Watson's source jump to b670."""
        capacity = self._fr(offset + 0x18, 8)
        if capacity > 0xF:
            size = (capacity + 1) & _U64
            pointer = self._fr(offset, 8)
            original = pointer
            if size >= 0x1000:
                size = (size + 0x27) & _U64
                pointer = self._r(pointer - 8, 8)
                delta = (original - pointer - 8) & _U64
                if delta > 0x1F:
                    if bad_site in (0x14162B329, 0x14162B343):
                        self._watson(0)
                        raise UnresolvedReplayTaskRebuild(
                            f"source INT3 after returning Watson at {bad_site:x}"
                        )
                    if bad_site == 0x14162B640:
                        self._watson(0)  # b653 -> NOP -> b65a, no trap here.
                    self._watson(r14)  # b669 -> NOP -> b670.
                    return True
            self._call(0x142D6BAB4, (pointer, size))
        self._fw(offset + 0x10, 16, constant)
        self._fw(offset, 1, 0)
        return False

    def _output_record(self, index: int, constant: int, bad_site: int) -> None:
        manager = self._r(0x1442C3F90, 8)
        record = _value(self._call(0x140DD4880, (manager, index)), 8, "record RAX")
        if not record:
            return
        value = self._r(record + 0x30, 8)
        sentinel = self._r(0x143DADE30, 8)
        if value == sentinel or value >= 9:
            return
        stream = self._stream()
        raw = self._call(0x141869A90, ((record + 0x30) & _U64, self._h(0x218), record))
        text = _value(raw, 8, "actual141869a90 returned string")
        if self._r(text + 0x18, 8) > 0xF:
            text = self._r(text, 8)
        self._call(0x140DEE6B0, (stream, text, _U32))
        self._cleanup_string(0x218, constant, bad_site, 0)

    def _output_records(self) -> None:
        """b056..b266: signed wrap scan and held new bound, not cached maxima."""
        manager = self._r(0x1442C3F90, 8)
        new = _eax(self._call(0x140DD48B0, (manager,)), "b062 record index EAX")
        index = self._r(0x144418584, 4)
        if new == index:
            return
        constant = self._r(0x1436A03A0, 16)
        if _signed(new, 4) < _signed(index, 4):
            index = (index + 1) & _U32
            manager = self._r(0x1442C3F90, 8)
            maximum = _eax(self._call(0x140DD48C0, (manager,)), "b08f max EAX")
            while _signed(index, 4) <= _signed(maximum, 4):
                self._output_record(index, constant, 0x14162B329)
                index = (index + 1) & _U32
                manager = self._r(0x1442C3F90, 8)
                maximum = _eax(self._call(0x140DD48C0, (manager,)), "b16f max EAX")
            index = _U32
            self._w(0x144418584, 4, index)
        index = (index + 1) & _U32
        while _signed(index, 4) <= _signed(new, 4):
            self._output_record(index, constant, 0x14162B343)
            index = (index + 1) & _U32
        self._w(0x144418584, 4, new)

    def _message(self, r14: int) -> int:
        """b670..b7b9 including the partial homes and current holder cleanup."""
        self._fw(0x238, 16, 0)
        self._fw(0x248, 8, 0)
        raw = self._clock()
        self._fw(0x80, 4, 7)
        self._fw(0x78, 4, _eax(raw, "b696 clock EAX"))
        target = self._r(0x143199CA0, 8)
        _invoke(self.runtime, target, (0x2336, self._h(0x250), 0x10, 0xA))
        raw = self._call(0x140803EA0, (self._h(0x250),))
        self._fw(0x220, 4, 0xF)
        self._fw(0x218, 8, _value(raw, 8, "b6ce localization RAX"))
        self._fw(0x238, 8, 0x14428BB30)
        self._fw(0x240, 8, r14)
        self._fw(0x248, 8, r14)
        self._fw(0x250, 8, self._h(0x218))
        self._fw(0x258, 8, self._h(0x78))
        self._call(0x140A1BA10, (self._h(0x238), 0x1432EA160, 2, self._h(0x250)))
        self._fw(0x60, 4, 1)
        self._fw(0x64, 1, 1)
        self._fw(0x1C0, 8, 0x1432EA988)
        self._fw(0x1F8, 8, self._h(0x1C0))
        flags = self._fr(0x60, 8)
        manager = self._r(0x144415600, 8)
        self._call(0x141581360, (manager, self._h(0x238), self._h(0x1C0), flags))
        holder = self._fr(0x1F8, 8)
        if holder:
            dl = int(holder != self._h(0x1C0))
            vptr = self._r(holder, 8)
            target = self._r(vptr + 0x20, 8)
            _invoke(self.cleanup, target, (holder, dl, 0xFF))
        manager = self._r(0x144415600, 8)
        self._w(manager + 0x1252, 1, 1)
        self._call(0x140A1B220, (self._h(0x238),))
        return 4

    def _reader(self) -> int | None:
        """b373..b670: None goes to blocks; other return is prepared logical4."""
        maximum, minimum = 0x7FFFFFFFFFFFFFFF, 0x16
        constant = self._r(0x1436A03A0, 16)
        while True:
            sentinel = self._r(0x143DADE30, 8)
            self._fw(0x2B0, 8, sentinel)
            self._call(0x142D6E3B7, (0x144419060, 0, 0x400))
            stream = self._stream()
            raw = self._call(0x140DEC000, (stream, 0x144419060, self._h(0x2B0)))
            status = _eax(raw, "b3d1 reader EAX")
            if status != 1:
                if status in (4, _U32):
                    return None
                if status == 2:
                    return self._message(0)
                if not status:
                    stream = self._stream()
                    self._call(0x140DF2670, (stream,))
                    return 4
                continue
            self._fw(0x278, 8, _U64)
            self._fw(0x288, 16, 0)
            self._fw(0x298, 16, constant)
            self._fw(0x288, 1, 0)
            self._fw(0x250, 16, 0)
            self._fw(0x260, 16, constant)
            self._fw(0x250, 1, 0)
            self._fw(0x218, 16, 0)
            self._fw(0x228, 16, 0)
            length = _value(self._call(0x142D6E44D, (0x144419060,)), 8, "b432 length RAX")
            if length > maximum:
                self._call(0x1402A91E0, ())
                raise UnresolvedReplayTaskRebuild("source INT3 at14162ba9e after length error")
            if length <= 0xF:
                self._fw(0x228, 8, length)
                self._fw(0x230, 8, 0xF)
                self._call(0x142D6E3B1, (self._h(0x218), 0x144419060, length))
                self._w(self._h(0x218) + length, 1, 0)
            else:
                capacity = length | 0xF
                if capacity > maximum:
                    capacity = maximum
                elif capacity < minimum:
                    capacity = minimum
                allocation = _value(
                    self._call(0x1402A94D0, ((capacity + 1) & _U64,)), 8, "b499 allocation RAX"
                )
                self._fw(0x218, 8, allocation)
                self._fw(0x228, 8, length)
                self._fw(0x230, 8, capacity)
                self._call(0x142D6E3B1, (allocation, 0x144419060, length))
                self._w(allocation + length, 1, 0)
            raw = self._call(0x141869660, (self._h(0x278), self._h(0x218), self._h(0x250)))
            parsed = _value(raw, 1, "b4e2 actual parser AL")
            if self._cleanup_string(0x218, constant, 0x14162B640, length):
                return self._message(length)
            output = self._fr(0x2B0, 8)
            self._fw(0x50, 1, 0)
            self._fw(0x78, 8, output)
            if parsed:
                flag = self._fr(0x2AC, 1) & 1
                capacity = self._fr(0x268, 8)
                pointer = self._fr(0x250, 8)  # CMOVA memory operand reads even if unselected.
                text = pointer if capacity > 0xF else self._h(0x250)
                self._fw(0x48, 8, self._h(0x278))
                self._fw(0x40, 1, flag)
            else:
                self._fw(0x48, 8, 0)
                self._fw(0x40, 1, 0)
                text = 0x144419060
            self._fw(0x38, 4, 0)
            self._fw(0x30, 4, 0)
            self._fw(0x28, 4, 1)
            self._fw(0x20, 4, 0)
            manager = self._r(0x1442C3F90, 8)
            _invoke(
                self.record_home,
                0x140DD3E80,
                (
                    manager,
                    0,
                    text,
                    self._h(0x78),
                    self._h(0x20),
                    self._h(0x28),
                    self._h(0x30),
                    self._h(0x38),
                    self._h(0x40),
                    self._h(0x48),
                    self._h(0x50),
                ),
            )
            if self._cleanup_string(0x250, constant, 0x14162B65A, 0):
                return self._message(0)
            self._call(0x1402A88A0, (self._h(0x288),))

    def _lookup_unit(self, cursor: int) -> int:
        word = self._r(cursor, 4)
        signed = _signed(word, 4)
        if signed < 0:
            if word == 0x80000000:
                return 0
            magnitude = (-word) & _U32
            limit = self._r(self.world + 0x184, 4)
            if _signed(magnitude, 4) < _signed(limit, 4):
                table = self._r(self.world + 0x178, 8)
                return self._r(table + _signed(magnitude, 4) * 8, 8)
        if signed <= -1:
            return 0
        if signed >= _signed(self._r(self.world + 0x174, 4), 4):
            return 0
        table = self._r(self.world + 0x168, 8)
        if not table:
            return 0
        return self._r(table + signed * 8, 8)

    def _decode(self, raw: int, first: int, second: int) -> int:
        self._fw(0x60, 8, raw)
        value = self._fr(0x60, 8)
        self._fw(0x60, 8, value + first)
        value = self._fr(0x60, 8)
        self._fw(0x60, 8, value + second)
        return self._fr(0x60, 8)

    def _geometry(self, block: int, unit: int, index: int) -> None:
        has_virtual = self._r(block + 0xFA, 1) != 0
        raw_fp = None
        if has_virtual:
            vptr = self._r(unit, 8)
            target = self._r(vptr + 0x218, 8)
            raw_fp = _invoke(self.unit_fp, target, (unit,))
        value = self._decode(self._r(unit + 0x180, 8), 0x2B3719EF44DE99FF, 0x21D14A25ED7C802C)
        self._fw(0x78, 8, value)
        value = self._decode(self._r(unit + 0x178, 8), -self.r13, 0x6C5EAB60B426DD28)
        self._fw(0x250, 8, value)
        value = self._decode(self._r(unit + 0x170, 8), -0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1)
        self._fw(0x238, 8, value)
        row = (self._h(0x2C0) + _signed(index, 4) * 48) & _U64
        if has_virtual:
            self._fw(0x20, 4, _value(raw_fp, 4, "b8d6 actual virtual218 XMM0 word"))
        xmm3 = self._fr(0x78, 4)
        xmm2 = self._fr(0x250, 4)
        xmm1 = self._fr(0x238, 4)
        if has_virtual:
            _invoke(self.geometry, 0x140B2D200, (row, xmm1, xmm2, xmm3, self._h(0x20)))
        else:
            _invoke(self.geometry, 0x140B2D0F0, (row, xmm1, xmm2, xmm3))

    def _blocks(self) -> None:
        """b266 prefix/b270 loop with b9ff's positive-loop-only offset reload."""
        offset = 0
        self._fw(0x2B0, 8, offset)
        while True:
            block = (self._r(self.world + 0x800, 8) + offset) & _U64
            if self._r(block + 0xFB, 1):
                raw = self._call(0x140B2CFF0, (block,))
                admitted = _value(raw, 1, "b290 actual block AL")
                if not admitted:
                    self._w(block + 0xFB, 1, 0)
                else:
                    self._fw(0x2C0, 16, 0)
                    self._fw(0x2D0, 16, 0)
                    self._fw(0x2E0, 16, 0)
                    self._call(0x142D6E3B7, (self._h(0x2F0), 0, 0xB10))
                    cursor, index = (block + 8) & _U64, 0
                    count = self._r(block + 0xF8, 2)
                    if _signed(count, 2) > 0:
                        while True:
                            unit = self._lookup_unit(cursor)
                            if unit:
                                self._geometry(block, unit, index)
                            index = (index + 1) & _U32
                            cursor = (cursor + 4) & _U64
                            count = self._r(block + 0xF8, 2)
                            if not _signed(index, 4) < _signed(count, 2):
                                break
                        offset = self._fr(0x2B0, 8)
                    self._call(0x140B2D040, (block, self._h(0x2C0)))
            offset = (offset + 0x100) & _U64
            self._fw(0x2B0, 8, offset)
            if not _signed(offset, 8) < 0x500:
                break

    def run(self) -> int:
        self._postpasses()
        self._round_robin()
        if self._logging():
            return self._r(self.world + 0x88, 4)
        stream = self._stream()
        if self._r(stream, 1):
            self._output_records()
        else:
            stream = self._stream()
            if self._r(stream + 1, 1):
                returned = self._reader()
                if returned is not None:
                    return returned
        self._blocks()
        return self._r(self.world + 0x88, 4)


def run_replay_world_update_postpass(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    phase: ReplayWorldUpdatePlayerLinks | ReplayWorldUpdatePlayerPass,
    *,
    virtual_calls: ReplayTaskRebuildCalls,
    cleanup_virtual_calls: ReplayTaskRebuildCalls,
    unit_fp_calls: ReplayTaskRebuildCalls,
    geometry_calls: ReplayTaskRebuildCalls,
    format_home_calls: ReplayTaskRebuildCalls,
    record_home_calls: ReplayTaskRebuildCalls,
    runtime_calls: ReplayTaskRebuildCalls,
    watson_home_calls: ReplayTaskRebuildCalls,
) -> ReplayWorldUpdatePostpass:
    """Complete source-owned normal-ab9e tail over the existing live frame.

    Source-category dispatch never falls back to another channel. Live HOME
    annotations are addresses, not snapshots; actual unprovided ABI/backing
    remains mandatory. Ignored returns stay opaque. Parser AL is validated at
    its b4e2 capture; virtual218 XMM0 is consumed only at b8d6 after decode.

    No new local mapping/seed, clock, child success, count clamp or loop budget
    is supplied. Caller FP operations are raw word moves only. Physical cookie,
    GP/XMM save traffic, native faults/EH/concurrency and full native RAX are
    excluded. This returns prepared logical EAX, not World readiness or proof
    of a complete integrated tick. ba3c/ba59 alternate arrivals are not entries.
    """
    if not isinstance(phase, (ReplayWorldUpdatePlayerLinks, ReplayWorldUpdatePlayerPass)):
        raise ValueError("actual player-links or player-pass normal ab9e phase required")
    if (
        type(phase.next_address) is not int
        or phase.next_address != 0x14162AB9E
        or phase.returned_status is not None
    ):
        raise ValueError("actual ab9e handoff without a prior return required")
    _validate(context, calls, phase.world, phase.logical_frame)
    for channel in (
        virtual_calls,
        cleanup_virtual_calls,
        unit_fp_calls,
        geometry_calls,
        format_home_calls,
        record_home_calls,
        runtime_calls,
        watson_home_calls,
    ):
        if not isinstance(channel, ReplayTaskRebuildCalls):
            raise ValueError("actual category-specific World postpass channels required")
    for value in (
        phase.entry_time,
        phase.cycle,
        phase.status,
        phase.default_time,
        phase.control_flags,
        phase.outer_index,
    ):
        _unsigned(value, 4, "World tail historical DWORD")
    _unsigned(phase.raw_count, 8, "World tail raw count observation")
    _unsigned(phase.held_r13, 8, "World tail full held R13")
    if phase.held_r13 != _LITERAL:
        raise ValueError("source-qualified full normal-ab9e R13 required")
    if isinstance(phase, ReplayWorldUpdatePlayerLinks):
        if phase.outer_index or phase.raw_count & _U32:
            raise ValueError("player-links ab9e requires initial zero-low-count shortcut")
        for observation, width in (
            (phase.held_begin, 8),
            (phase.xmm8_word, 4),
            (phase.inner_index, 4),
            (phase.marker_address, 8),
        ):
            if observation is not None:
                _unsigned(observation, width, "optional player-links observation")
    else:
        _unsigned(phase.xmm8_word, 4, "held player-pass XMM8 observation")
    engine = _Postpass(
        context,
        calls,
        phase,
        virtual_calls,
        cleanup_virtual_calls,
        unit_fp_calls,
        geometry_calls,
        format_home_calls,
        record_home_calls,
        runtime_calls,
        watson_home_calls,
    )
    result = engine.run()
    return ReplayWorldUpdatePostpass(
        phase.world,
        phase.logical_frame,
        phase.entry_time,
        phase.cycle,
        phase.status,
        phase.default_time,
        phase.control_flags,
        None,
        result,
    )
