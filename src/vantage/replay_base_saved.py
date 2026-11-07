"""Normal build54800 Base saved reader14125d730 and44B context resolver.

Source: base-saved-reader-source-review-v1, including1831 omitted normal bytes.
The four effective inputs do not establish owner/World identity. Every reached
Input, Result, allocator, master/sprite/object/string and registration child is
mandatory. Error metadata/TLS branches refuse at their first reached frontier;
native stack identity, cookies, C++ EH, faults and concurrency are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _call,
    _cvtt,
    _read,
    _signed,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U64 = (1 << 64) - 1
_U32 = (1 << 32) - 1
_VERSION = 0x1440A0D94
_MASTER_A = 0x0CF19788B2554E70
_MASTER_B = 0x6A586EB28AC201FC
# One-based source ordinals: Result RBP offset, destination is subject/local,
# destination offset, byte width, raw Input CALL site. Ordinal72 has dynamic R8/R9.
_REQUESTS = (
    (0xE0, 0, -0x78, 1, 0x14125D7C7),  # 1
    (0x110, 0, -0x7C, 2, 0x14125DA11),  # 2
    (0x140, 0, -0x7C, 2, 0x14125DC91),  # 3
    (0x170, 0, -0x74, 4, 0x14125DEE8),  # 4
    (0x1A0, 0, -0x38, 4, 0x14125E13C),  # 5
    (0x1D0, 1, 0x188, 1, 0x14125E3B4),  # 6
    (0x230, 1, 0x189, 1, 0x14125E5A8),  # 7
    (0x260, 1, 0x18A, 1, 0x14125E76C),  # 8
    (0x290, 1, 0x18B, 1, 0x14125E92C),  # 9
    (0x2C0, 1, 0x8, 4, 0x14125EAA6),  # 10
    (0x2F0, 1, 0xE, 1, 0x14125EC49),  # 11
    (0x320, 0, -0x34, 4, 0x14125EDF6),  # 12
    (0x350, 0, -0x30, 4, 0x14125EF96),  # 13
    (0x380, 0, -0x2C, 4, 0x14125F136),  # 14
    (0x3B0, 1, 0x158, 2, 0x14125F3E7),  # 15
    (0x3E0, 1, 0x15A, 2, 0x14125F54E),  # 16
    (0x410, 1, 0x15C, 2, 0x14125F6FC),  # 17
    (0x440, 1, 0x15E, 2, 0x14125F8AC),  # 18
    (0x470, 0, -0x4C, 1, 0x14125FA79),  # 19
    (0x4A0, 1, 0x160, 2, 0x14125FC2C),  # 20
    (0x4D0, 1, 0x168, 4, 0x14125FDE9),  # 21
    (0xFB0, 0, -0x58, 2, 0x14125FFCE),  # 22
    (0x500, 0, -0x54, 2, 0x1412601E7),  # 23
    (0xFE0, 0, -0x44, 4, 0x1412602C7),  # 24
    (0x530, 1, 0x18C, 4, 0x1412603A9),  # 25
    (0x560, 0, 0xDC, 4, 0x1412607AF),  # 26
    (0x590, 1, 0xD, 1, 0x14126094C),  # 27
    (0x5C0, 1, 0x165, 1, 0x141260B0C),  # 28
    (0x5F0, 0, -0x7C, 2, 0x141260CEF),  # 29
    (0x620, 1, 0x190, 4, 0x141260E9D),  # 30
    (0x650, 1, 0x1C5, 1, 0x14126101D),  # 31
    (0x680, 0, -0x28, 4, 0x1412611F1),  # 32
    (0x6B0, 0, -0x28, 4, 0x141261386),  # 33
    (0x6E0, 0, -0x40, 4, 0x1412614CD),  # 34
    (0x710, 0, -0x40, 4, 0x14126161B),  # 35
    (0x740, 0, -0x40, 4, 0x14126175D),  # 36
    (0x770, 0, 0xD0, 4, 0x141261811),  # 37
    (0x7A0, 0, -0x24, 4, 0x1412618C2),  # 38
    (0x7D0, 0, -0x24, 4, 0x141261973),  # 39
    (0x800, 0, -0x50, 4, 0x141261A35),  # 40
    (0x830, 0, 0xD4, 4, 0x141261B33),  # 41
    (0x860, 0, -0x50, 4, 0x141261B91),  # 42
    (0x890, 0, -0x3C, 4, 0x141261D45),  # 43
    (0x8C0, 0, 0xD8, 4, 0x141261DC9),  # 44
    (0x8F0, 1, 0x210, 4, 0x141261EF2),  # 45
    (0x920, 1, 0x214, 4, 0x141261FB7),  # 46
    (0x950, 1, 0x1C7, 1, 0x14126207F),  # 47
    (0x980, 1, 0x1C6, 1, 0x141262147),  # 48
    (0x9B0, 0, -0x60, 1, 0x141262214),  # 49
    (0x9E0, 0, -0x5E, 1, 0x1412622C8),  # 50
    (0xA10, 0, -0x5F, 1, 0x14126238D),  # 51
    (0xA70, 0, -0x5D, 1, 0x141262839),  # 52
    (0xAD0, 0, -0x5C, 1, 0x141262D1C),  # 53
    (0xB60, 0, -0x7C, 2, 0x141262FBD),  # 54
    (0xBC0, 0, -0x7C, 2, 0x14126314B),  # 55
    (0xC20, 0, -0x7C, 2, 0x1412632AF),  # 56
    (0xC80, 1, 0x198, 4, 0x141263481),  # 57
    (0xCB0, 1, 0x294, 1, 0x1412635AD),  # 58
    (0xCE0, 1, 0x290, 4, 0x141263661),  # 59
    (0xD10, 1, 0x2C8, 2, 0x141263738),  # 60
    (0xD40, 1, 0x1E8, 2, 0x141263809),  # 61
    (0xDD0, 1, 0x1C9, 1, 0x141263A66),  # 62
    (0xE00, 1, 0x1CA, 1, 0x141263B36),  # 63
    (0xE30, 1, 0x1CB, 1, 0x141263C06),  # 64
    (0xE60, 1, 0x295, 1, 0x141263CD6),  # 65
    (0xE90, 1, 0x2D0, 4, 0x141263DA4),  # 66
    (0xEC0, 1, 0x2D4, 4, 0x141263E58),  # 67
    (0xEF0, 1, 0x162, 2, 0x141263F20),  # 68
    (0xF20, 1, 0x16C, 4, 0x141263FD4),  # 69
    (0xF50, 1, 0x30, 4, 0x141264096),  # 70
    (0xF80, 0, -0x48, 4, 0x14126415B),  # 71
    (0x200, 0, 0x0, 0, 0x141264229),  # 72
)
_MASTER_TYPES = (
    (0x1E0, 0x1411B2820),
    (0x1E8, 0x1411745B0),
    (0x228, 0x1411A10A0),
    (0x298, 0x1411639B0),
    (0x330, 0x141199960),
    (0x3E8, 0x14130AF90),
    (0x4A0, 0x1412E1CA0),
)
_MASTER_BRANCHES = (
    (0x141262453, 0x1412624B2, 0x141262511, 0x141262570, 0x1412625CF, 0x14126262E, 0x14126268A),
    (0x14126295B, 0x1412629BA, 0x141262A19, 0x141262A78, 0x141262AD7, 0x141262B36, 0x141262B92),
)


def resolve_replay_saved_base_owner(
    context: ReplayTaskRebuildStorage,
    resolver: int,
    index: int,
) -> int:
    """Full44B141603f60; current16-byte-entry vector, signed low32 index."""
    _validate(context, ReplayTaskRebuildCalls(None), resolver, index)
    signed_index = _signed(index & _U32, 4)
    if signed_index < 0:
        return 0
    begin = _read(context, resolver + 0x768, 8)
    end = _read(context, resolver + 0x770, 8)
    if signed_index >= _signed((end - begin) & _U64, 8) >> 4:
        return 0
    return _read(context, begin + signed_index * 16, 8)


@dataclass(slots=True)
class _Reader:
    context: ReplayTaskRebuildStorage
    subject: int
    output: int
    stream: int
    resolver: int
    frame: int
    calls: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics

    @property
    def bp(self) -> int:
        return self.frame + 0x100 & _U64

    @property
    def scratch(self) -> int:
        return self.frame + 0x40 & _U64

    def local(self, offset: int) -> int:
        return self.bp + offset & _U64

    def read_local(self, offset: int, width: int) -> int:
        return _read(self.context, self.local(offset), width)

    def write_local(self, offset: int, width: int, value: int) -> None:
        _write(self.context, self.local(offset), width, value)

    def version(self) -> int:
        return _read(self.context, _VERSION, 4)

    def zero(self, result: int) -> None:
        for offset in (0, 16, 32):
            _write(self.context, result + offset, 16, 0)

    def error(self, site: int) -> None:
        raise UnresolvedReplayTaskRebuild(
            f"Base saved reader reached returned-error/metadata frontier after source{site:x}"
        )

    def finish(self, result: int, site: int, *, inline: bool = False) -> None:
        if _read(self.context, result + 24, 8):
            self.error(site)
        _write(self.context, result + 40, 1, 1)
        if inline:
            control = _read(self.context, result + 32, 8)
            if control:
                _release(self.context, control, self.calls, self.atomics)
            _call(self.calls, 0x1402BD7F0, (result,))
        else:
            _call(self.calls, 0x140900620, (result,))

    def request(self, ordinal: int) -> None:
        slot, object_field, offset, width, site = _REQUESTS[ordinal - 1]
        result = self.local(slot)
        self.zero(result)
        table = _read(self.context, self.stream, 8)
        target = _read(self.context, table + 24, 8)
        destination = (self.subject if object_field else self.bp) + offset
        _call(self.calls, target, (self.stream, result, destination, width))
        self.finish(result, site, inline=ordinal <= 5)

    def composite_request(self, ordinal: int, forwarded_offset: int) -> None:
        slot, _, offset, width, site = _REQUESTS[ordinal - 1]
        raw, forwarded = self.local(slot), self.local(forwarded_offset)
        self.zero(forwarded)
        self.zero(raw)
        target = _read(self.context, _read(self.context, self.stream, 8) + 24, 8)
        _call(self.calls, target, (self.stream, raw, self.local(offset), width))
        self.zero(forwarded)
        _write(self.context, raw + 40, 1, 1)
        if _read(self.context, raw + 24, 8):
            self.error(site)
        _call(self.calls, 0x1409076B0, (forwarded, raw))
        if ordinal == 23:
            _call(self.calls, 0x1408EE150, ((raw + 24) & _U64,))
            _call(self.calls, 0x1402BD7F0, (raw,))
        else:
            _call(self.calls, 0x140900620, (raw,))
        self.finish(forwarded, site)

    def scratch_copy(self) -> None:
        _write(self.context, self.scratch, 8, _read(self.context, self.scratch, 8))

    def scratch_add(self, value: int) -> None:
        _write(self.context, self.scratch, 8, _read(self.context, self.scratch, 8) + value)

    def scratch_xor(self, value: int) -> None:
        _write(self.context, self.scratch, 8, _read(self.context, self.scratch, 8) ^ value)

    def encode_master(self, pointer: int) -> None:
        _write(self.context, self.scratch, 8, pointer)
        self.scratch_add(_MASTER_A)
        self.scratch_add(_MASTER_B)
        _write(self.context, self.subject + 16, 8, _read(self.context, self.scratch, 8))

    def decode_master(self) -> int:
        _write(self.context, self.scratch, 8, _read(self.context, self.subject + 16, 8))
        self.scratch_add(-_MASTER_B)
        self.scratch_add(-_MASTER_A)
        return _read(self.context, self.scratch, 8)

    def encoded_coordinate(self, local: int, field: int, first: int, second: int) -> None:
        _write(self.context, self.scratch, 4, self.read_local(local, 4))
        self.scratch_copy()
        self.scratch_add(-first)
        self.scratch_add(second)
        self.scratch_copy()
        _write(self.context, self.subject + field, 8, _read(self.context, self.scratch, 8))

    def nested_master(self, which: int) -> None:
        ordinal = 51 + which
        self.request(ordinal)
        raw = self.local(0x10 if which == 0 else -0x20)
        # Source initializes the tail before the first two16B chunks, then
        # explicitly initializes the control and processed fields again.
        for offset in (32, 0, 16):
            _write(self.context, raw + offset, 16, 0)
        _write(self.context, raw + 32, 8, 0)
        _write(self.context, raw + 40, 1, 0)
        kind = self.read_local(-0x5F if which == 0 else -0x5D, 1)
        index = kind - 10 & _U32
        if index > 70:
            self.error(0x1412628AB if which == 0 else 0x141262D8E)
        selector = _read(self.context, (0x1412651C8, 0x141265230)[which] + index, 1)
        branch = 0x140000000 + _read(
            self.context, (0x1412651A8, 0x141265210)[which] + selector * 4, 4
        )
        if branch not in _MASTER_BRANCHES[which]:
            self.error(branch)
        size, constructor = _MASTER_TYPES[_MASTER_BRANCHES[which].index(branch)]
        allocation = _call(self.calls, 0x142D6BA78, (size,), width=8)
        _write(self.context, self.frame + 0x38, 8, allocation)
        pointer = 0
        if allocation:
            _call(self.calls, 0x142D6E3B7, (allocation, 0, size))
            world = _read(self.context, _read(self.context, self.subject + 24, 8) + 8, 8)
            _write(self.context, self.frame + 0x28, 4, 1)
            _write(self.context, self.frame + 0x20, 8, world + 0xA0)
            pointer = _call(
                self.calls,
                constructor,
                (allocation, raw, self.stream, world + 0xC0, world + 0xA0, 1),
                width=8,
            )
        if which == 0:
            self.encode_master(pointer)
            _call(self.calls, 0x1412429D0, ((self.subject + 0x200) & _U64, self.subject))
        else:
            _write(self.context, self.subject + 0x1F8, 8, pointer)
            owner = _read(self.context, self.subject + 24, 8)
            _call(self.calls, 0x1411DF830, (pointer, owner, 1))
        forwarded = self.local(0xA40 if which == 0 else 0xAA0)
        self.zero(forwarded)
        _call(self.calls, 0x1409076B0, (forwarded, raw))
        self.finish(forwarded, 0x14126272C if which == 0 else 0x141262C13)
        if which == 0:
            control = _read(self.context, raw + 32, 8)
            if control:
                _call(self.calls, 0x1402AAA80, (control,))
        else:
            _call(self.calls, 0x1408EE150, ((raw + 24) & _U64,))
        _call(self.calls, 0x1402BD7F0, (raw,))

    def sprite(self, modern: bool) -> None:
        if modern:
            self.request(53)
            if not self.read_local(-0x5C, 1):
                _write(self.context, self.subject + 0x28, 8, 0)
                return
        pointer = _call(self.calls, 0x14124DD00, (self.subject,), width=8)
        _write(self.context, self.subject + 0x28, 8, pointer)
        result = self.local(0xB00 if modern else 0xB30)
        self.zero(result)
        sprite = _read(self.context, self.subject + 0x28, 8)
        _call(self.calls, 0x141483140, (sprite, result, self.stream, self.resolver + 0xC0))
        self.finish(result, 0x141262E31 if modern else 0x141262EF9)

    def dynamic_object(self, result_offset: int, destination: int) -> None:
        result = self.local(result_offset)
        self.zero(result)
        world = _read(self.context, _read(self.context, self.subject + 24, 8) + 8, 8)
        _write(self.context, self.frame + 0x28, 8, self.subject)
        _write(self.context, self.frame + 0x20, 8, world + 0xC0)
        manager = _read(self.context, 0x144289738, 8)
        _call(
            self.calls,
            0x1409BDA80,
            (manager, result, destination & _U64, self.stream, world + 0xC0, self.subject),
        )
        self.finish(result, 0x141263030 if result_offset == 0xB90 else 0x141263233)

    def payload(self) -> None:
        result = self.local(0x200)
        self.zero(result)
        target = _read(self.context, _read(self.context, self.stream, 8) + 24, 8)
        width = _signed(self.read_local(-0x48, 4), 4) & _U64
        destination = self.subject + 0x38 & _U64
        if _read(self.context, destination + 24, 8) > 15:
            destination = _read(self.context, destination, 8)
        _call(self.calls, target, (self.stream, result, destination, width))
        self.finish(result, 0x141264232)

    def registration(self) -> None:
        c, s = self.context, self.subject
        _call(self.calls, 0x141868CB0, (s,))
        owner = _read(c, s + 24, 8)
        if _read(c, owner + 0x648, 4) == 0:
            second, first = _read(c, s + 0x18A, 1), _read(c, s + 0x189, 1)
            target = _read(c, _read(c, owner, 8) + 0x2D8, 8)
            _call(self.calls, target, (owner, s, first, second))
            for field in (0x160, 0x162):
                category = _signed(_read(c, s + field, 2), 2) & _U32
                index = _call(self.calls, 0x1410B9490, (category,), width=4)
                if _signed(index, 4) >= 0:
                    _call(self.calls, 0x141727E10, (_read(c, s + 24, 8), index, s))
        else:
            if _read(c, s + 0x189, 1):
                offset = 0x38
            elif _read(c, s + 0x18A, 1):
                offset = 0x40
            else:
                offset = 0x30
            _call(self.calls, 0x141228090, (_read(c, owner + offset, 8), s))
            world = _read(c, _read(c, s + 24, 8) + 8, 8)
            target = _read(c, _read(c, world, 8) + 0x88, 8)
            _call(self.calls, target, (world, s))
            owner = _read(c, s + 24, 8)
            master = self.decode_master()
            _write(c, self.scratch, 8, _read(c, master + 24, 8))
            self.scratch_xor(0x349E37847AD69F19)
            self.scratch_add(-0x47E37DFF0616CE4F)
            identifier = _signed(_read(c, self.scratch, 8) & 0xFFFF, 2) & _U32
            _call(self.calls, 0x141729140, (owner, self.local(0x1010), identifier))
            owner = _read(c, s + 24, 8)
            identifier = _read(c, s + 8, 4)
            tracker = _read(c, owner + 24, 8)
            _call(self.calls, 0x14111A250, (tracker, identifier, self.local(0x1010)))
        _write(c, s + 0x150, 8, 0)
        _write(c, s + 0x164, 1, 0)
        master = self.decode_master()
        if _read(c, master + 0x122, 1) == 2 and _read(c, s + 0x188, 1) >= 3:
            contact = _read(c, _read(c, s + 24, 8) + 0x78, 8)
            _write(c, self.scratch, 8, _read(c, s + 0x178, 8))
            self.scratch_add(-0x61501AA6ECFD980A)
            self.scratch_add(0x6C5EAB60B426DD28)
            _write(c, self.frame + 0x38, 8, _read(c, self.scratch, 8))
            _write(c, self.scratch, 8, _read(c, s + 0x170, 8))
            self.scratch_add(-0x183CAC30D2441D0E)
            self.scratch_add(0x4C3FBA69E4EA7FD1)
            self.scratch_copy()
            y = _cvtt(_read(c, self.frame + 0x38, 4))
            x = _cvtt(_read(c, self.scratch, 4))
            _call(self.calls, 0x14115F0A0, (contact, s, x, y))
        _call(self.calls, 0x1412488E0, (s,))
        master = self.decode_master()
        if _read(c, master + 0xCD, 1) >= 10:
            _write(c, s + 0x1C9, 1, 0)

    def prefix(self) -> None:
        c, s = self.context, self.subject
        _write(c, s + 15, 1, 10)
        self.request(1)
        owner = _call(self.calls, 0x141603F60, (self.resolver, self.read_local(-0x78, 1)), width=8)
        _write(c, s + 24, 8, owner)
        self.request(2)
        index = _signed(self.read_local(-0x7C, 2), 2)
        owner = _read(c, s + 24, 8)
        masters = _read(c, owner + 0x28, 8)
        self.encode_master(_read(c, masters + index * 8, 8))
        self.request(3)
        index = _signed(self.read_local(-0x7C, 2), 2)
        graphic = 0
        if index >= 0:
            graphics = _read(c, self.resolver + 0xC0, 8)
            graphic = _read(c, graphics + index * 8, 8)
        _write(c, s + 32, 8, graphic)
        self.request(4)
        identifier = self.read_local(-0x74, 4)
        if identifier == _U32:
            _write(c, s + 0x148, 8, 0)
        else:
            _write(c, self.scratch, 4, identifier + 1)
            _write(c, s + 0x148, 8, _read(c, self.scratch, 8))
        self.request(5)
        _write(c, self.scratch, 4, self.read_local(-0x38, 4))
        self.scratch_copy()
        self.scratch_add(0x147B5E081EC087D9)
        self.scratch_xor(0x0F2A55F7A61DD00E)
        self.scratch_copy()
        _write(c, s + 0x130, 8, _read(c, self.scratch, 8))
        self.request(6)
        self.request(7)
        if _signed(self.version(), 4) >= 0x7170A:
            self.request(8)
        self.request(9)
        if _read(c, s + 0x18B, 1):
            _write(c, s + 0x189, 1, 0)
        for ordinal in range(10, 15):
            self.request(ordinal)
        self.encoded_coordinate(-0x34, 0x170, 0x4C3FBA69E4EA7FD1, 0x183CAC30D2441D0E)
        self.encoded_coordinate(-0x30, 0x178, 0x6C5EAB60B426DD28, 0x61501AA6ECFD980A)
        self.encoded_coordinate(-0x2C, 0x180, 0x21D14A25ED7C802C, -0x2B3719EF44DE99FF)
        for ordinal in range(15, 19):
            self.request(ordinal)
        if _signed(self.version(), 4) < 0xB947A:
            self.request(19)
        self.request(20)
        self.request(21)
        if _signed(self.version(), 4) >= 0x420000:
            self.write_local(-0x58, 2, 0)
            self.composite_request(22, 0x40)
            index = 0
            if self.read_local(-0x58, 2):
                while True:
                    self.write_local(-0x54, 2, 0xFFFF)
                    self.write_local(-0x44, 4, 0)
                    self.composite_request(23, 0xA0)
                    self.composite_request(24, 0x70)
                    value = self.read_local(-0x44, 4)
                    slot = _call(
                        self.calls, 0x14122F320, ((s + 0x2E0) & _U64, self.local(-0x54)), width=8
                    )
                    _write(c, slot, 4, value)
                    index = index + 1 & _U64
                    if index >= self.read_local(-0x58, 2):
                        break
        self.request(25)

    def historical_middle(self) -> None:
        c, s = self.context, self.subject
        version = self.version()
        if (version - 0xCEB85) & _U32 <= 0x15147B:
            self.request(26)
        self.request(27)
        if _signed(self.version(), 4) >= 0x9D999:
            self.request(28)
        else:
            _write(c, s + 0x165, 1, 0)
        _write(c, s + 0x1C0, 2, 0xFF)
        version = self.version()
        if _signed(version, 4) >= 0xC8CCC:
            self.request(29)
            version = self.version()
        # The skip edge jumps past the preceding version reload.
        if _signed(version, 4) >= 0xC6B85:
            self.request(30)
        else:
            _write(c, s + 0x190, 4, 0)
        self.request(31)
        _call(self.calls, 0x141248810, (s, 0))
        version = self.version()
        if _signed(version, 4) < 0xAD999:
            self.request(32)
            self.request(33)
            version = self.version()
        if version == 0x6FDB2:
            for ordinal in range(34, 40):
                self.request(ordinal)
            version = self.version()
        if _signed(version, 4) < 0xAD999:
            self.request(40)
            index = 0
            if _signed(self.read_local(-0x50, 4), 4) > 0:
                while True:
                    self.request(41)
                    index = index + 1 & _U32
                    if _signed(index, 4) >= _signed(self.read_local(-0x50, 4), 4):
                        break
        self.request(42)
        index = 0
        if _signed(self.read_local(-0x50, 4), 4) > 0:
            while True:
                self.request(43)
                _call(self.calls, 0x14124B760, (s, self.read_local(-0x3C, 4)))
                index = index + 1 & _U32
                if _signed(index, 4) >= _signed(self.read_local(-0x50, 4), 4):
                    break
        version = self.version()
        if (version - 0x91C28) & _U32 <= 0x8290:
            self.request(44)
            version = self.version()
        for threshold, ordinal in ((0x9A8F5, 45), (0xCB0A3, 46), (0x19428F, 47)):
            if _signed(version, 4) >= threshold:
                self.request(ordinal)
                version = self.version()
        if _signed(version, 4) >= 0xB547A:
            self.request(48)
        else:
            _write(c, s + 0x1C6, 1, 0)

    def children(self) -> int:
        s = self.subject
        if _signed(self.version(), 4) >= 0xCCF5C:
            self.request(49)
            self.request(50)
            if self.read_local(-0x60, 1):
                self.nested_master(0)
            if self.read_local(-0x5E, 1):
                self.nested_master(1)
        self.sprite(_signed(self.version(), 4) >= 0xB1C28)
        version = self.version()
        if _signed(version, 4) >= 0xCB333:
            self.request(54)
            if self.read_local(-0x7C, 2):
                self.dynamic_object(0xB90, s + 0x58)
            self.request(55)
            for result, local, vector in ((0xBF0, -0x70, 0x78), (0xC50, -0x68, 0x60)):
                remaining = self.read_local(-0x7C, 2)
                while remaining:
                    self.write_local(-0x7C, 2, remaining - 1)
                    self.dynamic_object(result, self.local(local))
                    if self.read_local(local, 8):
                        _call(self.calls, 0x141255B00, ((s + vector) & _U64, self.local(local)))
                    remaining = self.read_local(-0x7C, 2)
                self.write_local(-0x7C, 2, 0xFFFF)
                if vector == 0x78:
                    self.request(56)
            version = self.version()
        return version

    def tail(self, version: int) -> None:
        c, s = self.context, self.subject
        if _signed(version, 4) >= 0xCE8F5:
            self.request(57)
            version = self.version()
        if _signed(version, 4) >= 0xD2666:
            self.request(58)
            self.request(59)
        else:
            _write(c, s + 0x294, 1, 0)
            _write(c, s + 0x290, 4, _U32)
        for threshold, ordinal, field in ((0xD28F5, 60, 0x2C8), (0xD3AE1, 61, 0x1E8)):
            if _signed(self.version(), 4) >= threshold:
                self.request(ordinal)
            else:
                _write(c, s + field, 2, 0xFFFF)
        for threshold, field, result, fallback in (
            (0xD3D70, 0x298, 0xD70, 0x141248070),
            (0xD4000, 0x2B0, 0xDA0, 0x1412480D0),
        ):
            if _signed(self.version(), 4) >= threshold:
                self.zero(self.local(result))
                _call(
                    self.calls, 0x140A1BDF0, ((s + field) & _U64, self.local(result), self.stream)
                )
                self.finish(self.local(result), 0x1412638D3 if field == 0x298 else 0x141263999)
            else:
                _call(self.calls, fallback, (s,))
        for threshold, ordinal, field, fallback in (
            (0xD428F, 62, 0x1C9, 1),
            (0x3F1999, 63, 0x1CA, 1),
            (0xD51EB, 64, 0x1CB, 1),
            (0x141999, 65, 0x295, 0),
        ):
            if _signed(self.version(), 4) >= threshold:
                self.request(ordinal)
            else:
                _write(c, s + field, 1, fallback)
        version = self.version()
        if _signed(version, 4) >= 0x3D07AE:
            self.request(66)
            self.request(67)
            version = self.version()
        if _signed(version, 4) >= 0x3D3333:
            self.request(68)
            self.request(69)
            version = self.version()
        if _signed(version, 4) >= 0x3DB333:
            self.request(70)
            if _signed(self.version(), 4) >= 0x416666:
                self.write_local(-0x48, 4, 0)
                self.request(71)
                count = _signed(self.read_local(-0x48, 4), 4) & _U64
                _call(self.calls, 0x1402BB570, ((s + 0x38) & _U64, count, 0))
                self.payload()


def read_replay_saved_base(
    context: ReplayTaskRebuildStorage,
    address: int,
    output: int,
    stream: int,
    opaque: int,
    *,
    calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> int:
    """Full normal Base chronology,72 sites and all historical/current branches.

    Explicit0x1168-byte seeds preserve uninitialized local bytes and coherent
    reused slots; RBP is frame+100 and shared encoded scratch is frame+40.
    The local view stays live through final callbacks/return. Ordinary mapped
    current tables, valid vectors and synchronous callbacks are required; no
    native physical-stack alias, masked-FP status or unmasked-trap parity claim.
    Current static switch tables are read only if a nested master is reached.
    Unknown/error-metadata effects refuse with all preceding effects retained.
    """
    _validate(context, calls, address, output, stream, opaque)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Base saved atomic/local bindings required")
    if type(scratch) is not bytes or len(scratch) != 0x1168:
        raise ValueError("explicit0x1168-byte Base saved local seeds required")
    with _local(memoryview(bytearray(scratch)), bind_local) as frame:
        _write(context, frame + 0x38, 8, output)
        reader = _Reader(context, address, output, stream, opaque, frame, calls, atomics)
        reader.prefix()
        reader.historical_middle()
        reader.tail(reader.children())
        reader.registration()
        for offset in (0, 8, 16, 24, 32):
            _write(context, output + offset, 8, 0)
        _write(context, output + 40, 1, 0)
        return output


def bind_replay_saved_base(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    scratch: bytes,
) -> ReplayTaskRebuildCalls:
    """Bind14125d730/fourargs and actual44B141603f60/twoargs; children delegate."""
    _validate(context, calls)
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual Base saved atomic/local bindings required")
    if type(scratch) is not bytes or len(scratch) != 0x1168:
        raise ValueError("explicit0x1168-byte Base saved local seeds required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (0x14125D730, 0x141603F60):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != (4 if target == 0x14125D730 else 2) or data is not None:
            raise ValueError("malformed Base saved call")
        _validate(context, calls, *args)
        if target == 0x141603F60:
            return resolve_replay_saved_base_owner(context, *args)
        return read_replay_saved_base(
            context, *args, calls=bound, atomics=atomics, bind_local=bind_local, scratch=scratch
        )

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
