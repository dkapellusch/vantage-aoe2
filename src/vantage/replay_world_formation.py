"""Seven complete formation/group caller bodies over explicit current storage.

Originals: world-formation-batch-{children-,}source-v1. Deeper lookup,
growth, detach, unit-AI, event, string and FP children remain actual effects.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    multiply_binary32,
    subtract_binary32,
)
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

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MAIN, _DISTANCE, _MISSING, _COMPAT = 0x14162BAB0, 0x14096D4D0, 0x1410F67B0, 0x1410D2680
_PREDICATE, _TRANSFER, _RECOMPUTE = 0x1410D2750, 0x1410D3AB0, 0x1410D4E50
_GAME, _GET_WORLD, _LOOKUP = 0x144353698, 0x140D6ACC0, 0x141617DB0
_EMPTY, _FORMAT, _DESTROY, _ASSIGN = 0x14428BB30, 0x140A1BA10, 0x140A1B220, 0x140A1A660
_LOGGER, _LOG = 0x140901D20, 0x140902570


@dataclass(frozen=True, slots=True)
class ReplayWorldFormationProfile:
    """Explicit B0/D8/44h local prefixes; cookies/saves/dead tails excluded.

    formation: coherent typed arguments/descriptors50..af and HOME20;
    transfer: partial argument homes20..40, saved reference50, scratch/strings
    58..b7 and live pointer listb8..d7; recompute: nine DWORD counters20..43.
    Finite valid backing/progress required, without an artificial loop cutoff.
    """

    formation: bytes
    transfer: bytes
    recompute: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in (
                (self.formation, 0xB0),
                (self.transfer, 0xD8),
                (self.recompute, 0x44),
            )
        ):
            raise ValueError("explicit B0/D8/44-hex-byte formation seeds required")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _eax(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int:
    return _call(calls, target, args, width=8) & _U32


def _al(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int:
    return _call(calls, target, args, width=8) & 255


def _world(context: ReplayTaskRebuildStorage, calls: ReplayTaskRebuildCalls) -> int:
    return _call(calls, _GET_WORLD, (_read(context, _GAME, 8),), width=8)


def _distance(context: ReplayTaskRebuildStorage, left: int, output: int, right: int) -> int:
    first = subtract_binary32(_read(context, left, 4), _read(context, right, 4))
    second = subtract_binary32(_read(context, left + 4, 4), _read(context, right + 4, 4))
    _write(context, output, 4, first)
    third = subtract_binary32(_read(context, left + 8, 4), _read(context, right + 8, 4))
    _write(context, output + 4, 4, second)
    _write(context, output + 8, 4, third)
    return output


def _missing(context: ReplayTaskRebuildStorage, row: int, identifier: int) -> int:
    count = _signed(_read(context, row + 0x110, 4), 4)
    if count <= 0:
        return 0
    pointer = _read(context, row + 0x108, 8)
    index = 0
    identifier &= _U32
    while index < count:
        if _read(context, pointer + index * 4, 4) == identifier:
            _write(context, pointer + index * 4, 4, _U32)
            return 1
        index += 1
    return 0


def _compatible(context: ReplayTaskRebuildStorage, left: int, right: int) -> int:
    first = _read(context, right + 0x3B0, 4)
    if _read(context, left + 0x3B0, 4) != first:
        return 0
    negated = -_read(context, right + 0x460, 4) & _U32
    # CMOVS fetches its memory operand even when the register is not selected.
    current = _read(context, right + 0x460, 4)
    chosen = current if negated & 0x80000000 else negated
    if _read(context, left + 0x460, 4) != chosen:
        return 0
    a = _read(context, left + 0x450, 8)
    sentinel_a, sentinel_b = (left + 0x430) & _U64, (right + 0x430) & _U64
    b = _read(context, sentinel_b + 0x20, 8)
    while a != sentinel_a:
        if b == sentinel_b:
            return 0
        word = _read(context, b, 4)
        if _read(context, a, 4) != word:
            return 0
        word = _read(context, b + 4, 4)
        if _read(context, a + 4, 4) != word:
            return 0
        a = _read(context, a + 0x20, 8)
        b = _read(context, b + 0x20, 8)
    return int(b == sentinel_b)


def _predicate(context: ReplayTaskRebuildStorage, calls: ReplayTaskRebuildCalls, row: int) -> int:
    if _read(context, row + 0xE4, 4) == 0:
        return 0
    world = _world(context, calls)
    if _signed(_read(context, row + 0xE4, 4), 4) <= 0:
        return 0
    index, offset = 0, 0
    while True:
        data = _read(context, row + 0xF0, 8)
        unit = _call(calls, _LOOKUP, (world, _read(context, data + offset, 4)), width=8)
        if unit and _read(context, unit + 0xF, 1) >= 0x28:
            descriptor = _call(calls, 0x141139140, (unit,), width=8)
            if descriptor and _read(context, descriptor + 8, 2) in (0x7C, 0x7D):
                return 1
        index = index + 1 & _U32
        offset = offset + 4 & _U64
        if _signed(index, 4) >= _signed(_read(context, row + 0xE4, 4), 4):
            return 0


@dataclass(slots=True)
class _Frame:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    logger: ReplayTaskRebuildCalls
    events: ReplayTaskRebuildCalls
    frame: int

    def at(self, offset: int) -> int:
        return self.frame + offset & _U64

    def read(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def call(self, target: int, *args: int) -> None:
        _call(self.calls, target, args)

    def pointer(self, target: int, *args: int) -> int:
        return _call(self.calls, target, args, width=8)

    def word(self, target: int, *args: int) -> int:
        return _eax(self.calls, target, args)

    def log(self, logger: int, cpp: int, line: int, pointer: int) -> None:
        self.write(self.at(0x20), 8, pointer)
        _invoke(self.logger, _LOG, (logger, cpp, line, 1, self.at(0x20)))

    def string(self, offset: int, token: int = _EMPTY) -> None:
        self.write(self.at(offset), 16, 0)
        self.write(self.at(offset), 8, token)
        self.write(self.at(offset + 8), 8, 0)
        self.write(self.at(offset + 16), 8, 0)

    def literal_error(self, literal: int, line: int) -> None:
        logger = self.pointer(_LOGGER, self.read(0x14427C720), 0x14325B614)
        self.string(0x78)
        self.call(_ASSIGN, self.at(0x78), literal)
        self.log(logger, 0x1432A0A30, line, self.read(self.at(0x78)))
        self.call(_DESTROY, self.at(0x78))

    def decode_master(self, unit: int) -> int:
        self.write(self.at(0xA8), 8, self.read(unit + 0x10))
        self.write(self.at(0xA8), 8, self.read(self.at(0xA8)) - 0x6A586EB28AC201FC)
        self.write(self.at(0xA8), 8, self.read(self.at(0xA8)) - 0x0CF19788B2554E70)
        return self.read(self.at(0xA8))

    def transfer_notice(self, destination: int, unit: int, identifier: int, flag: int) -> None:
        if not flag:
            descriptor = self.pointer(0x140A4B870, self.decode_master(unit))
            value = self.read(descriptor)
            self.write(self.at(0x40), 8, value)
            self.write(self.at(0x38), 4, identifier)
            self.write(self.at(0x30), 8, 0x1432A0B00)
            self.write(self.at(0x28), 4, identifier)
            self.write(self.at(0x20), 4, self.read(destination + 0xD8, 4))
            fourth = self.read(0x144363500, 4)
            third = self.read(0x144363504, 4)
            _invoke(
                self.events,
                0x140B6EF80,
                (
                    0x15,
                    0,
                    third,
                    fourth,
                    self.at(0x20),
                    self.at(0x28),
                    self.at(0x30),
                    self.at(0x38),
                    self.at(0x40),
                ),
            )
            return
        held_logger = self.read(0x14427C720)
        for field, subtract, add, output in (
            (0x178, 0x61501AA6ECFD980A, 0x6C5EAB60B426DD28, 0x68),
            (0x170, 0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1, 0x58),
        ):
            self.write(self.at(0xA8), 8, self.read(unit + field))
            self.write(self.at(0xA8), 8, self.read(self.at(0xA8)) - subtract)
            self.write(self.at(0xA8), 8, self.read(self.at(0xA8)) + add)
            self.write(self.at(output), 8, self.read(self.at(0xA8)))
        master = self.decode_master(unit)
        name = self.pointer(0x140803E30, self.read(master + 0xC, 4))
        logger = self.pointer(_LOGGER, held_logger, 0x14325B614)
        self.write(self.at(0x78), 16, 0)
        self.write(self.at(0x98), 4, 10)
        self.write(self.at(0x90), 4, self.read(self.at(0x68), 4))
        self.write(self.at(0xB0), 4, 10)
        self.write(self.at(0xA8), 4, self.read(self.at(0x58), 4))
        self.write(self.at(0x70), 4, 15)
        self.write(self.at(0x68), 8, name)
        self.write(self.at(0x60), 4, 2)
        self.write(self.at(0x58), 4, identifier)
        self.write(self.at(0x78), 8, _EMPTY)
        self.write(self.at(0x80), 8, 0)
        self.write(self.at(0x88), 8, 0)
        for home, argument in ((0xB8, 0x58), (0xC0, 0x68), (0xC8, 0xA8), (0xD0, 0x90)):
            self.write(self.at(home), 8, self.at(argument))
        self.call(_FORMAT, self.at(0x78), 0x1432A0AD8, 4, self.at(0xB8))
        self.log(logger, 0x1432A0A30, 0x1A94, self.read(self.at(0x78)))
        self.call(_DESTROY, self.at(0x78))

    def transfer(self, destination: int, identifier: int, reference: int, flag: int) -> int:
        identifier, reference, flag = identifier & _U32, reference & _U32, flag & 255
        self.write(self.at(0x50), 4, reference)
        unit = self.pointer(_LOOKUP, _world(self.context, self.calls), identifier)
        if not unit:
            if flag:
                logger = self.pointer(_LOGGER, self.read(0x14427C720), 0x14325B614)
                self.write(self.at(0x90), 16, 0)
                self.write(self.at(0x60), 4, 2)
                self.write(self.at(0x58), 4, identifier)
                self.write(self.at(0x90), 8, _EMPTY)
                self.write(self.at(0x98), 8, 0)
                self.write(self.at(0xA0), 8, 0)
                self.write(self.at(0xA8), 8, self.at(0x58))
                self.call(_FORMAT, self.at(0x90), 0x1432A0A00, 1, self.at(0xA8))
                self.log(logger, 0x1432A0A30, 0x1A86, self.read(self.at(0x90)))
                self.call(_DESTROY, self.at(0x90))
            return 0
        self.transfer_notice(destination, unit, identifier, flag)
        if flag:
            reference = self.read(self.at(0x50), 4)
        if self.word(0x1410D95F0, unit, 0) == _U32:
            if flag:
                self.literal_error(0x1432A0B20, 0x1AA3)
            return 0
        count = self.read(destination + 0xE4, 4)
        duplicate = False
        if _signed(count, 4) > 0:
            data = self.read(destination + 0xF0)
            index = 0
            while _signed(index, 4) < _signed(count, 4):
                if self.read(data, 4) == identifier:
                    duplicate = True
                    break
                index = index + 1 & _U32
                data = data + 4 & _U64
        if duplicate:
            if flag:
                self.literal_error(0x1432A0B48, 0x1AAF)
            return 1
        if _signed(count, 4) >= 70:
            if flag:
                self.literal_error(0x1432A0B70, 0x1ABA)
            return 0
        capacity = self.read(destination + 0xE8, 4)
        if _signed(count, 4) >= _signed(capacity, 4) or not capacity:
            if not capacity and not self.word(0x1410F7C20, destination, 10):
                if flag:
                    self.literal_error(0x1432A0B98, 0x1ACC)
                return 0
            capacity = self.read(destination + 0xE8, 4) * 2 & _U32
            if not self.word(0x1410F7C20, destination, capacity):
                if flag:
                    self.literal_error(0x1432A0BB8, 0x1AD7)
                return 0
        if self.read(unit + 0x210, 4) != _U32:
            world = _world(self.context, self.calls)
            previous = self.pointer(0x141604060, world, self.read(unit + 0x210, 4))
            if (
                previous
                and self.word(0x1410F6800, previous, self.read(unit + 8, 4), reference, 0) == 1
            ):
                self.write(unit + 0x210, 4, _U32)
        self.write(unit + 0x210, 4, self.read(destination + 0xD8, 4))
        stop = False
        for getter, value in (
            (0x140D23D40, 0x259),
            (0x140D23D50, 0x2BD),
            (0x140D23D40, 0x2BF),
            (0x140D23D50, 0x323),
            (0x140D23D40, 0x2C0),
            (0x140D23D50, 0x324),
        ):
            if self.word(getter, self.read(unit + 0x1F0)) == value:
                stop = True
                break
        if stop:
            self.call(0x140D3EA00, self.read(unit + 0x1F0), _U32)
            self.call(0x140D3EA10, self.read(unit + 0x1F0), _U32, 1)
        self.call(0x140D36E70, self.read(unit + 0x1F0))
        index = _signed(self.read(destination + 0xE4, 4), 4)
        data = self.read(destination + 0xF0)
        self.write(data + index * 4, 4, identifier)
        index = _signed(self.read(destination + 0xE4, 4), 4)
        data = self.read(destination + 0xF8)
        record = data + index * 48 & _U64
        for offset, width, value in (
            (0, 4, 0),
            (4, 8, _U64),
            (12, 8, 0),
            (20, 8, 0),
            (28, 8, 0),
            (36, 8, 0),
            (44, 4, 0),
        ):
            self.write(record + offset, width, value)
        self.write(destination + 0xE4, 4, self.read(destination + 0xE4, 4) + 1)
        first = self.pointer(_LOOKUP, _world(self.context, self.calls), identifier)
        if first:
            world = _world(self.context, self.calls)
            second = self.pointer(_LOOKUP, world, self.read(self.at(0x50), 4))
            key = self.word(0x1410D95F0, first, second)
            if key != _U32:
                self.auxiliary(destination, identifier, key)
        amount = self.word(0x1410EEF50, unit)
        amount = add_binary32(amount, amount)
        compared = compare_binary32(amount, self.read(destination + 0x15C, 4))
        if compared == 1:
            self.write(destination + 0x15C, 4, amount)
        flags = self.read(destination + 0x140, 4) | 2
        self.write(destination + 0x140, 4, flags)
        if not self.read(destination + 0xB8, 1) & 2:
            self.write(destination + 0x140, 4, flags | 0x10000)
        return 1

    def auxiliary(self, destination: int, identifier: int, key: int) -> None:
        sentinel = destination + 0x1D8 & _U64
        node = self.read(sentinel)
        while node != sentinel:
            if self.read(node + 0x10, 4) == key:
                self.call(0x1410D43A0, node, identifier)
                return
            node = self.read(node)
        node = self.pointer(0x142D6BA78, 0x1C8)
        self.write(self.at(0x58), 8, node)
        if not node:
            return
        self.call(0x142D6E3B7, node, 0, 0x1C8)
        for offset, width, value in (
            (0x10, 4, _U32),
            (0x14, 8, 0),
            (0x20, 8, 0),
            (0x28, 8, 0),
            (0x30, 8, 0),
            (0, 8, node),
            (8, 8, node),
        ):
            self.write(node + offset, width, value)
        self.call(0x142D6E3B7, node + 0x38, 0, 0xC8)
        self.call(0x142D6E3B7, node + 0x100, 0, 0xC8)
        self.call(0x1410D43A0, node, identifier)
        self.write(node, 8, sentinel)
        self.write(node + 8, 8, self.read(destination + 0x1E0))
        self.write(self.read(destination + 0x1E0), 8, node)
        self.write(destination + 0x1E0, 8, node)
        self.write(destination + 0x1D0, 4, self.read(destination + 0x1D0, 4) + 1)
        self.write(node + 0x10, 4, key)

    def recompute(self, row: int) -> None:
        self.write(self.at(0x40), 4, 0)
        self.write(self.at(0x20), 16, 0)
        self.write(self.at(0x30), 16, 0)
        ninth = 0
        if _signed(self.read(row + 0xE4, 4), 4) > 0:
            index, offset = 0, 0
            while True:
                world = _world(self.context, self.calls)
                data = self.read(row + 0xF0)
                unit = self.pointer(_LOOKUP, world, self.read(data + offset, 4))
                if unit:
                    ai = self.read(unit + 0x1F0)
                    if ai:
                        category = self.read(ai + 0x1DC, 1)
                        if category < 9:
                            cell = self.at(0x20 + category * 4)
                            self.write(cell, 4, self.read(cell, 4) + 1)
                index = index + 1 & _U32
                offset = offset + 4 & _U64
                if _signed(index, 4) >= _signed(self.read(row + 0xE4, 4), 4):
                    break
            ninth = self.read(self.at(0x40), 4)
        first = self.read(self.at(0x20), 4)
        selected = int(_signed(self.read(self.at(0x24), 4), 4) > _signed(first, 4))
        for category in range(2, 8):
            held = self.read(self.at(0x20 + selected * 4), 4)
            current = self.read(self.at(0x20 + category * 4), 4)
            if _signed(current, 4) > _signed(held, 4):
                selected = category
        if _signed(ninth, 4) > _signed(self.read(self.at(0x20 + selected * 4), 4), 4):
            selected = 8
        if selected >= 3:
            owner = self.pointer(0x140A69450)
            world = _world(self.context, self.calls)
            player = self.pointer(0x141603F60, world, self.read(row + 0xDC, 4))
            self.call(0x140A4AFD0, owner, player, 0xE, selected)
            self.write(row + 0x138, 4, selected)
            self.call(0x14110CFC0, row, selected)
            self.call(0x1410D6670, row, 1, selected)
            return
        self.write(row + 0x138, 4, 0)
        self.call(0x14110CFC0, row, _U32)
        self.call(0x1410D6670, row, 1, self.read(row + 0x138, 4))
        if _signed(self.read(row + 0xE4, 4), 4) <= 0:
            return
        index, offset = 0, 0
        while True:
            world = _world(self.context, self.calls)
            data = self.read(row + 0xF0)
            unit = self.pointer(_LOOKUP, world, self.read(data + offset, 4))
            if unit:
                ai = self.read(unit + 0x1F0)
                if ai:
                    self.write(ai + 0x1DC, 1, 0)
            index = index + 1 & _U32
            offset = offset + 4 & _U64
            if _signed(index, 4) >= _signed(self.read(row + 0xE4, 4), 4):
                return

    def merge_diagnostic(self, world: int, source: int, *, over_limit: bool) -> None:
        formatted, copied = (0x68, 0x80) if over_limit else (0x80, 0x68)
        argument, tag = (0x40, 0x48) if over_limit else (0x30, 0x38)
        self.write(self.at(formatted), 16, 0)
        self.write(self.at(formatted + 16), 8, 0)
        index = _signed(self.read(source + 0xDC, 4), 4)
        players = self.read(world + 0x768)
        player = self.read(players + index * 16)
        returned = self.pointer(0x141732B10, player, self.at(0x50), 0, 0x1432F47B0)
        text = self.read(returned)
        self.write(self.at(tag), 4, 15)
        self.write(self.at(argument), 8, text)
        self.write(self.at(formatted), 8, _EMPTY)
        self.write(self.at(formatted + 8), 8, 0)
        self.write(self.at(formatted + 16), 8, 0)
        self.write(self.at(0xA8), 8, self.at(argument))
        self.call(
            _FORMAT,
            self.at(formatted),
            0x1432EA7E0 if over_limit else 0x1432EA6B0,
            1,
            self.at(0xA8),
        )
        self.call(_DESTROY, self.at(0x50))
        text = self.read(self.at(formatted))
        logger = self.pointer(_LOGGER, self.read(0x14427C720), 0x14325B614)
        self.string(copied)
        self.call(_ASSIGN, self.at(copied), text)
        self.log(logger, 0x1432EA730, 0x1E4B if over_limit else 0x1E3A, self.read(self.at(copied)))
        self.call(_DESTROY, self.at(copied))
        self.call(_DESTROY, self.at(formatted))

    def consider(self, world: int, source: int, peer: int, mask: int, radius: int) -> None:
        player_index = _signed(self.read(source + 0xDC, 4), 4)
        players = self.read(world + 0x768)
        player = self.read(players + player_index * 16)
        if self.read(player + 0x5F8, 4) == 1:
            difference = subtract_binary32(self.read(source + 0xBC, 4), self.read(peer + 0xBC, 4))
            compared = compare_binary32(difference & mask, self.read(0x14408CA88, 4))
            if compared == 1:
                return
        self.call(_DISTANCE, source + 8, self.at(0x98), peer + 8)
        self.write(self.at(0x9C), 4, 0)
        x = self.read(self.at(0x98), 4)
        total = add_binary32(multiply_binary32(x, x), 0)
        z = self.read(self.at(0xA0), 4)
        total = add_binary32(total, multiply_binary32(z, z))
        if compare_binary32(radius, total) != 1:
            return
        if not _al(self.calls, _COMPAT, (source, peer)):
            return
        if _al(self.calls, _PREDICATE, (source,)) or _al(self.calls, _PREDICATE, (peer,)):
            return
        if self.read(source + 0x13C, 1) or self.read(peer + 0x13C, 1):
            return
        peer_count = self.read(peer + 0xE4, 4)
        combined = self.read(source + 0xE4, 4) + peer_count & _U32
        if _signed(combined, 4) > 60:
            self.merge_diagnostic(world, source, over_limit=True)
            return
        previous = _U32
        if _signed(peer_count, 4) > 0:
            while True:
                data = self.read(peer + 0xF0)
                identifier = self.read(data, 4)
                self.call(_TRANSFER, source, identifier, _U32, 0)
                if identifier == previous and previous != _U32:
                    self.merge_diagnostic(world, source, over_limit=False)
                    break
                previous = identifier
                if _signed(self.read(peer + 0xE4, 4), 4) <= 0:
                    break
        self.call(_RECOMPUTE, source)

    def formation(self, world: int, source: int) -> None:
        mask = self.read(0x1431B7530, 16) & _U32
        radius = self.read(0x1436A0294, 4)
        while True:
            if (
                _signed(self.read(source + 0xE4, 4), 4) > 0
                and self.read(source + 0x3B0, 4) != 0x2713
            ):
                data = self.read(source + 0x108)
                if _signed(self.read(source + 0x110, 4), 4) > 0:
                    index = 0
                    while True:
                        identifier = self.read(data, 4)
                        if identifier != _U32 and identifier != self.read(source + 0xD8, 4):
                            head = self.read(world + 0x50)
                            peer = self.read(head + 0xC8)
                            while peer != head:
                                if self.read(peer + 0xD8, 4) == identifier:
                                    break
                                peer = self.read(peer + 0xC8)
                            if peer == head or not peer:
                                self.call(_MISSING, source, identifier)
                            else:
                                self.consider(world, source, peer, mask, radius)
                        index = index + 1 & _U32
                        data = data + 4 & _U64
                        if _signed(index, 4) >= _signed(self.read(source + 0x110, 4), 4):
                            break
            source = self.read(source + 0xC8)
            if source == self.read(world + 0x50):
                return


def bind_replay_world_formation(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    logger_home_calls: ReplayTaskRebuildCalls,
    event_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayWorldFormationProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Own7 complete callers; unknown calls/args/data/results delegate unchanged.

    Logger gets4effective registers+HOME20 address. Event gets4registers+
    HOME20/28/30/38/40 addresses with their original partial widths. Reached
    descendants remain mandatory; unused callee incidental registers, physical
    frames/cookies, faults/EH/concurrency and escaped locals are excluded.
    Empty World does not bind a semantic local. No World readiness/defaults.
    """
    for channel in (calls, logger_home_calls, event_home_calls):
        _validate(context, channel)
    _unsigned(mxcsr, 4, "MXCSR")
    if (
        mxcsr != 0x1F80
        or not callable(bind_local)
        or not isinstance(profile, ReplayWorldFormationProfile)
    ):
        raise ValueError("explicit formation locals/profile and MXCSR1f80 required")
    arities = {
        _MAIN: 1,
        _DISTANCE: 3,
        _MISSING: 2,
        _COMPAT: 2,
        _PREDICATE: 1,
        _TRANSFER: 4,
        _RECOMPUTE: 1,
    }

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in arities:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != arities[target] or data is not None:
            raise ValueError("malformed formation call")
        _validate(context, calls, *args)
        if target == _DISTANCE:
            return _distance(context, *args)
        if target == _MISSING:
            return _missing(context, *args)
        if target == _COMPAT:
            return _compatible(context, *args)
        if target == _PREDICATE:
            return _predicate(context, bound, *args)
        first = 0
        if target == _MAIN:
            head = _read(context, args[0] + 0x50, 8)
            first = _read(context, head + 0xC8, 8)
            if first == head:
                return None
        seed = {
            _MAIN: profile.formation,
            _TRANSFER: profile.transfer,
            _RECOMPUTE: profile.recompute,
        }[target]
        with _local(memoryview(bytearray(seed)), bind_local) as frame:
            state = _Frame(context, bound, logger_home_calls, event_home_calls, frame)
            if target == _MAIN:
                state.formation(args[0], first)
            elif target == _TRANSFER:
                return state.transfer(*args)
            else:
                state.recompute(*args)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
