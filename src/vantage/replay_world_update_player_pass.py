"""Complete World per-player caller [141629e00,14162ab9e), 3486 bytes.

The six explicit service channels retain current targets, raw FP words and
live homes. This hands off at c90/ab9e; it does not complete a World tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    multiply_binary32,
    subtract_binary32,
)
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _cvtt,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate
from .replay_world_update_player_links import (
    ReplayWorldUpdatePlayerLinks,
    ReplayWorldUpdatePlayerLinksReentry,
)

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MASTER_A, _MASTER_B = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_LITERAL = 0x61501AA6ECFD980A


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdatePlayerPass:
    """Normal ab9e boundary: full R13 and source-qualified R14zero.

    XMM8/count/outer are exact observations, not claims of tail consumers.
    RDX is unprovided after the last real child and is deliberately omitted.
    """

    world: int
    logical_frame: int
    entry_time: int
    cycle: int
    status: int
    default_time: int
    control_flags: int
    outer_index: int
    held_r13: int
    raw_count: int
    xmm8_word: int
    next_address: int | None
    returned_status: int | None


def _invoke(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(arg & _U64 for arg in args), None)


def _value(value: int | None, width: int, name: str) -> int:
    if value is None:
        raise ValueError(f"{name} requires its actual scalar annotation")
    _unsigned(value, width, name)
    return value


def _count(end: int, begin: int) -> int:
    return (_signed((end - begin) & _U64, 8) >> 4) & _U64


class _PlayerPass:
    # These working words are assigned only on the source's reached unit arm.
    counter: int
    row_offset: int
    unit: int
    kind: int

    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        phase: ReplayWorldUpdatePlayerLinks,
        virtual_calls: ReplayTaskRebuildCalls,
        flag_calls: ReplayTaskRebuildCalls,
        policy_calls: ReplayTaskRebuildCalls,
        position_calls: ReplayTaskRebuildCalls,
        relationship_calls: ReplayTaskRebuildCalls,
        begin: int,
        xmm8: int,
    ) -> None:
        self.context, self.calls, self.phase = context, calls, phase
        self.virtual, self.flags, self.policy = virtual_calls, flag_calls, policy_calls
        self.position, self.relationship = position_calls, relationship_calls
        self.world, self.frame = phase.world, phase.logical_frame
        self.outer, self.selected = phase.outer_index, phase.held_r13
        self.begin, self.xmm8, self.default = begin, xmm8, phase.default_time

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

    def _additive(self, raw: int, first: int, second: int) -> int:
        """Two literal decode operations, preserving every live QWORD access."""
        self._fw(0x60, 8, raw)
        word = self._fr(0x60, 8)
        self._fw(0x60, 8, word + first)
        word = self._fr(0x60, 8)
        self._fw(0x60, 8, word + second)
        return self._fr(0x60, 8)

    def _master(self, unit: int) -> int:
        return self._additive(self._r(unit + 0x10, 8), -_MASTER_A, -_MASTER_B)

    def _kind(self, unit: int) -> int:
        master = self._master(unit)
        return self._additive(
            self._r(master + 0x38, 8),
            -0x50A06BCECEBEF905,
            0x5B32AA7995D95916,
        )

    def _id(self, unit: int) -> int:
        master = self._master(unit)
        self._fw(0x60, 8, self._r(master + 0x18, 8))
        word = self._fr(0x60, 8)
        self._fw(0x60, 8, word ^ 0x349E37847AD69F19)
        word = self._fr(0x60, 8)
        self._fw(0x60, 8, word - 0x47E37DFF0616CE4F)
        return self._fr(0x60, 8)

    def _field(self, unit: int, offset: int) -> int:
        if offset == 0x170:
            first, second = -0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1
        elif offset == 0x178:
            first, second = -_LITERAL, 0x6C5EAB60B426DD28
        elif offset == 0x180:
            first, second = 0x2B3719EF44DE99FF, 0x21D14A25ED7C802C
        else:
            raise ValueError("only the three source coordinate fields are admitted")
        return self._additive(self._r(unit + offset, 8), first, second)

    def _cvtt_field(self, offset: int) -> int:
        word = self._field(self.unit, offset)
        self._fw(0x60, 8, word)  # 9f75/9fbf: real duplicate QWORD stores.
        return _signed(_cvtt(self._fr(0x60, 4)), 4)

    def _lookup(self, identifier: int, *, policy: bool) -> int:
        """The two inline ID routes differ at the policy's explicit -1 gate."""
        if policy and identifier == _U32:
            return 0
        signed = _signed(identifier, 4)
        if signed < 0:
            if identifier == 0x80000000:
                return 0
            magnitude = (-identifier) & _U32
            if _signed(magnitude, 4) < _signed(self._r(self.world + 0x184, 4), 4):
                array = self._r(self.world + 0x178, 8)
                return self._r(array + _signed(magnitude, 4) * 8, 8)
        if signed <= -1:
            return 0
        if signed >= _signed(self._r(self.world + 0x174, 4), 4):
            return 0
        array = self._r(self.world + 0x168, 8)
        return self._r(array + signed * 8, 8) if array else 0

    def _position_tile(self, target_object: int) -> None:
        # a18a..a273: hold target before all field decoding.
        vptr = self._r(self.unit, 8)
        target = self._r(vptr + 0x150, 8)
        self._fw(0x208, 8, self._field(target_object, 0x180))
        self._fw(0x88, 8, self._field(target_object, 0x178))
        word = self._field(target_object, 0x170)
        self._fw(0x60, 8, word)
        z = self._fr(0x208, 4)
        self._fw(0x20, 4, z)
        x = self._fr(0x88, 4)
        y = self._fr(0x60, 4)
        _invoke(self.position, target, (self.unit, target_object, y, x, self._h(0x20)))

    def _position_selected(self, target_object: int) -> None:
        # a46e/a88a -> shared a532..a55e. No target reload after home stores.
        vptr = self._r(self.unit, 8)
        target = self._r(vptr + 0x150, 8)
        self._fw(0x250, 8, self._field(target_object, 0x180))
        self._fw(0x238, 8, self._field(target_object, 0x178))
        self._fw(0x88, 8, self._field(target_object, 0x170))
        z = self._fr(0x250, 4)
        y = self._fr(0x88, 4)
        x = self._fr(0x238, 4)
        self._fw(0x20, 4, z)
        _invoke(self.position, target, (self.unit, target_object, y, x, self._h(0x20)))

    def _grid(self) -> bool:
        # 9f2f..a129; a null computed tile is still dereferenced at +1b.
        grid = self._r(self.world + 0x98, 8)
        first = self._cvtt_field(0x178)
        second = self._cvtt_field(0x170)
        base = self._r(grid + 8, 8)
        tile = 0
        if base and first >= 0 and first < _signed(self._r(grid + 0x34, 4), 4) and second >= 0:
            columns = self._r(grid + 0x30, 4)
            if second < _signed(columns, 4):
                product = _signed((first * columns) & _U32, 4)
                tile = (base + (((product + second) & _U64) << 6)) & _U64
        index = 0
        if not self._r(tile + 0x1B, 1):
            return False
        while True:
            array = self._r(tile + 0x28, 8)
            member = self._r(array + index * 8, 8)
            if (
                member
                and self._kind(member) & 0xFFFF == 0x31
                and (self.kind & 0xFFFF != 0x15 or self._id(member) & 0xFFFF == 0xC7)
            ):
                self._position_tile(member)
                return True
            index = (index + 1) & _U64
            if index >= self._r(tile + 0x1B, 1):
                return False

    def _nearest(self) -> int:
        # a290..a468. A zero initial descriptor count skips saved-home reloads.
        threshold, chosen = self.xmm8, 0
        begin = self._r(self.world + 0x768, 8)
        player = self._r(begin + self.row_offset, 8)
        owner = self._r(player + 0x18, 8)
        descriptor = _value(_invoke(self.calls, 0x14111B3A0, (owner, 0x31)), 8, "descriptor RAX")
        if not self._r(descriptor + 0x10, 8):
            return 0
        index = 0
        while True:
            array = self._r(descriptor, 8)
            identifier = self._r(array + index * 4, 4)
            candidate = self._lookup(identifier, policy=False)
            # Source has no null guard before this access.
            if not self._r(candidate + 0x18C, 4):
                self._fw(0x238, 8, self._field(self.unit, 0x170))
                self._fw(0x88, 8, self._field(candidate, 0x170))
                first = self._fr(0x88, 4)
                first = subtract_binary32(first, self._fr(0x238, 4))
                self._fw(0x88, 8, self._field(self.unit, 0x178))
                self._fw(0x238, 8, self._field(candidate, 0x178))
                second = self._fr(0x238, 4)
                second = subtract_binary32(second, self._fr(0x88, 4))
                second = multiply_binary32(second, second)
                first = multiply_binary32(first, first)
                distance = add_binary32(second, first)
                comparison = compare_binary32(threshold, distance)
                if comparison is not None and comparison > 0:
                    threshold, chosen = distance, candidate
            index = (index + 1) & _U64
            if index >= self._r(descriptor + 0x10, 8):
                break
        # TEST chosen precedes these three current reads; held choice survives.
        self.kind = self._fr(0x250, 8)
        self.row_offset = self._fr(0x78, 8)
        self.counter = self._fr(0x208, 4)
        return chosen

    def _policy_invoke(self, receiver: int, target: int, rdx: int) -> int | None:
        return _invoke(
            self.policy,
            target,
            (
                receiver,
                rdx,
                _U32,
                _U32,
                self._h(0x20),
                self._h(0x28),
                self._h(0x30),
                self._h(0x38),
            ),
        )

    def _policy_selected(self) -> int:
        # a133..a185, then a622..a81e. Return is an EAX annotation, not full RAX.
        self._fw(0x208, 4, 0x63)
        selected = _U32
        receiver = self._r(self.unit + 0x1F0, 8)
        self._fw(0x38, 4, self.default)
        self._fw(0x30, 4, self.default)
        self._fw(0x28, 4, 2)
        if self.kind & 0xFFFF == 0x15:
            vptr = self._r(receiver, 8)
            output = self._h(0x208)
            self._fw(0x20, 8, output)
            target = self._r(vptr + 0x80, 8)
            returned = self._policy_invoke(receiver, target, (output & ~0xFF) | 2)
            return _value(returned, 4, "kind15 policy EAX")

        self._fw(0x200, 4, 0x63)
        vptr = self._r(receiver, 8)
        self._fw(0x20, 8, self._h(0x200))
        target = self._r(vptr + 0x80, 8)
        returned = self._policy_invoke(receiver, target, 0)
        score = self._fr(0x200, 4)
        best = self._fr(0x208, 4)
        if _signed(best, 4) > _signed(score, 4):
            selected = _value(returned, 4, "query0 policy EAX")
            self._fw(0x208, 4, score)

        # The original has these five fixed, unrolled groups; no dynamic bound.
        for selector in (1, 2, 3, 4, 5):
            self._fw(0x200, 4, 0x63)
            receiver = self._r(self.unit + 0x1F0, 8)
            vptr = self._r(receiver, 8)
            self._fw(0x38, 4, self.default)
            self._fw(0x30, 4, self.default)
            self._fw(0x28, 4, 2)
            output = self._h(0x200)
            self._fw(0x20, 8, output)
            target = self._r(vptr + 0x80, 8)
            returned = self._policy_invoke(receiver, target, (output & ~0xFF) | selector)
            score = self._fr(0x200, 4)
            best = self._fr(0x208, 4)
            if _signed(best, 4) > _signed(score, 4):
                if selector == 5:
                    self._fw(0x208, 4, score)
                    selected = _value(returned, 4, "query5 policy EAX")
                else:
                    selected = _value(returned, 4, "selected policy EAX")
                    self._fw(0x208, 4, score)
        return selected

    def _primary(self) -> None:
        # 9f01..a955, after the first AL/manager gates have actually passed.
        game = self._r(0x144353698, 8)
        output = _value(_invoke(self.calls, 0x140D6A530, (game, self._h(0xB0))), 8, "options RAX")
        options = self._r(output, 8)
        enabled = self._r(options + 0x69, 1)
        current = self._fr(0xB0, 8)
        if current:
            _invoke(self.calls, 0x140990140, (current,))
        if enabled:
            if self._grid():
                return
        elif self.kind & 0xFFFF == 4:
            nearest = self._nearest()
            if nearest:
                self._position_selected(nearest)
                return
        identifier = self._policy_selected()
        target_object = self._lookup(identifier, policy=True)
        if target_object:
            self._position_selected(target_object)

    def _secondary(self) -> None:
        # a96a..aa21: raw signed-WORD ID and full DWORD owner, then AL gates.
        identifier = _signed(self._id(self.unit) & 0xFFFF, 2) & _U32
        owner = self._r(self.unit + 0x18, 8)
        owner_id = self._r(owner + 0x648, 4)
        enabled = _value(
            _invoke(
                self.calls,
                0x141691140,
                (
                    self.world,
                    owner_id,
                    identifier,
                    0x99,
                ),
            ),
            1,
            "141691140 AL",
        )
        if not enabled:
            return
        vptr = self._r(self.unit, 8)
        target = self._r(vptr + 0x2E8, 8)
        enabled = _value(_invoke(self.flags, target, (self.unit, 1, 0xFF)), 1, "later2e8 AL")
        if not enabled:
            return
        receiver = self._r(self.unit + 0x1F0, 8)
        if receiver:
            vptr = self._r(receiver, 8)
            target = self._r(vptr + 0x1E8, 8)
            _invoke(self.virtual, target, (receiver,))

    def _units(self) -> None:
        # e0b..a5a2. No call on the false frame70 arm reaches this method.
        self.counter = 0
        self._fw(0x208, 4, self.counter)
        self.row_offset = self.outer << 4
        self._fw(0x78, 8, self.row_offset)
        player = self._r(self.begin + self.row_offset, 8)
        rows = self._r(player + 0x30, 8)
        if _signed(self._r(rows + 0x10, 4), 4) > 0:
            offset = 0
            self._fw(0x68, 8, 0)
            while True:
                player = self._r(self.begin + self.row_offset, 8)
                rows = self._r(player + 0x30, 8)
                array = self._r(rows + 8, 8)
                self.unit = self._r(array + offset, 8)
                self.kind = self._kind(self.unit)
                self._fw(0x250, 8, self.kind)
                primary = False
                if self.kind & 0xFFFF in (4, 0x15):
                    vptr = self._r(self.unit, 8)
                    target = self._r(vptr + 0x2E8, 8)
                    rdx = (self.begin & ~0xFF) | 1
                    enabled = _value(
                        _invoke(self.flags, target, (self.unit, rdx, _U64)), 1, "first2e8 AL"
                    )
                    if enabled and self._r(self.unit + 0x1F0, 8):
                        self._primary()
                        primary = True
                        offset = self._fr(0x68, 8)  # a56b
                    else:
                        offset = self._fr(0x68, 8)  # a95a, before BYTEf.
                if not primary and self._r(self.unit + 0xF, 1) == 0x50:
                    self._secondary()
                    offset = self._fr(0x68, 8)  # a56b after optional calls.
                self.counter = (self.counter + 1) & _U32
                self._fw(0x208, 4, self.counter)
                offset = (offset + 8) & _U64
                self._fw(0x68, 8, offset)
                self.begin = self._r(self.world + 0x768, 8)
                player = self._r(self.begin + self.row_offset, 8)
                rows = self._r(player + 0x30, 8)
                count = self._r(rows + 0x10, 4)
                if _signed(self.counter, 4) >= _signed(count, 4):
                    break
            self.outer = self._fr(0x210, 4)
        self.selected = self._fr(0x2B0, 8)

    def _delayed(self) -> None:
        # a5a9..a61d plus aa26..aa33, with held next/current links distinct.
        sentinel = self._r(self.world + 0x50, 8)
        node = self._r(sentinel + 0xC8, 8)
        if node == sentinel:
            return
        while True:
            following = self._r(node + 0xC8, 8)
            if self._r(node + 0xDC, 4) == self.outer:
                returned = _invoke(self.calls, 0x14110A5E0, (node,))
                if _value(returned, 4, "delayed-node EAX"):
                    vptr = self._r(node, 8)
                    target = self._r(vptr + 8, 8)
                    _invoke(self.virtual, target, (node,))
                else:
                    count = self._r(self.world + 0x58, 4)
                    self._w(self.world + 0x58, 4, count - 1)
                    next_now = self._r(node + 0xC8, 8)
                    prev_now = self._r(node + 0xD0, 8)
                    self._w(next_now + 0xD0, 8, prev_now)
                    prev_now = self._r(node + 0xD0, 8)
                    next_now = self._r(node + 0xC8, 8)
                    self._w(prev_now + 0xC8, 8, next_now)
                    vptr = self._r(node, 8)
                    target = self._r(vptr, 8)
                    _invoke(self.virtual, target, (node, 1))
            node = following
            if following == self._r(self.world + 0x50, 8):
                break

    def _player(self, begin: int, index: int) -> int:
        return self._r(begin + ((index + index) & _U64) * 8, 8)

    def _markers(self) -> None:
        # aa39..ab4a. Source keeps selected R13 across the real virtual100.
        begin = self._r(self.world + 0x768, 8)
        receiver = self._player(begin, self.outer)
        vptr = self._r(receiver, 8)
        target = self._r(vptr + 0x100, 8)
        _invoke(self.virtual, target, (receiver,))
        if not self._r(self.selected + 0x648, 4):
            return
        inner = 1
        begin = self._r(self.world + 0x768, 8)
        end = self._r(self.world + 0x770, 8)
        if _count(end, begin) & _U32 <= inner:
            return
        while True:
            marker = self._h(0x278 + inner * 4)
            if self._r(marker, 4):
                end = self._r(self.world + 0x770, 8)
                clear = self.outer == (_count(end, begin) - 1) & _U64
                if not clear:
                    next_outer = (self.outer + 1) & _U32
                    receiver = self._player(begin, next_outer)
                    self._fw(0xA4, 4, inner)
                    allowed = _value(
                        _invoke(
                            self.relationship,
                            0x141734D70,
                            (
                                receiver,
                                self._h(0xA4),
                                1,
                                0xFF,
                            ),
                        ),
                        1,
                        "first relationship AL",
                    )
                    clear = not allowed
                    if allowed:
                        fresh_begin = self._r(self.world + 0x768, 8)
                        receiver = self._player(fresh_begin, inner)
                        self._fw(0xA8, 4, next_outer)
                        allowed = _value(
                            _invoke(
                                self.relationship,
                                0x141734D70,
                                (
                                    receiver,
                                    self._h(0xA8),
                                    1,
                                    0xFF,
                                ),
                            ),
                            1,
                            "second relationship AL",
                        )
                        clear = not allowed
                if clear:
                    fresh_begin = self._r(self.world + 0x768, 8)
                    receiver = self._player(fresh_begin, inner)
                    vptr = self._r(receiver, 8)
                    self._fw(0x270, 4, self.outer)
                    target = self._r(vptr + 0x330, 8)
                    _invoke(self.virtual, target, (receiver, self._h(0x270)))
                    self._w(marker, 4, 0)
            inner = (inner + 1) & _U32
            begin = self._r(self.world + 0x768, 8)
            end = self._r(self.world + 0x770, 8)
            if inner >= _count(end, begin) & _U32:
                break

    def run(self) -> ReplayWorldUpdatePlayerLinksReentry | ReplayWorldUpdatePlayerPass:
        if self._fr(0x70, 1):
            self._units()
        self._delayed()
        self._markers()
        begin = self._r(self.world + 0x768, 8)
        receiver = self._player(begin, self.outer)
        _invoke(self.calls, 0x141731F00, ((receiver + 0xA0) & _U64,))
        self.outer = (self.outer + 1) & _U32
        self._fw(0x210, 4, self.outer)
        end = self._r(self.world + 0x770, 8)
        begin = self._r(self.world + 0x768, 8)
        raw_count = _count(end, begin)
        p = self.phase
        if self.outer < raw_count & _U32:
            return ReplayWorldUpdatePlayerLinksReentry(
                self.world,
                self.frame,
                p.entry_time,
                p.cycle,
                p.status,
                p.default_time,
                p.control_flags,
                self.outer,
                self.xmm8,
                0x141629C90,
                None,
            )
        return ReplayWorldUpdatePlayerPass(
            self.world,
            self.frame,
            p.entry_time,
            p.cycle,
            p.status,
            p.default_time,
            p.control_flags,
            self.outer,
            _LITERAL,
            raw_count,
            self.xmm8,
            0x14162AB9E,
            None,
        )


def run_replay_world_update_player_pass(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    phase: ReplayWorldUpdatePlayerLinks,
    *,
    virtual_calls: ReplayTaskRebuildCalls,
    virtual_2e8_calls: ReplayTaskRebuildCalls,
    policy_home_calls: ReplayTaskRebuildCalls,
    position_home_calls: ReplayTaskRebuildCalls,
    relationship_calls: ReplayTaskRebuildCalls,
    mxcsr: int,
) -> ReplayWorldUpdatePlayerLinksReentry | ReplayWorldUpdatePlayerPass:
    """Run all703 source rows under the fixed explicit six-channel interface.

    Policy returns are EAX annotations validated only at a selected consumer.
    HOME arguments are live addresses. The actual relationship provider must
    bind count_home=phase.logical_frame per invocation. Unknown true ABI or
    reached data/services must refuse; no dispatcher fallback is supplied.

    Source-qualified c90 re-entry and normal ab9e retain the same frame. No
    mapping, seed, bulk zero, count clamp or completed-tick status is provided.
    Native physical GP/save/stack, fault/EH/concurrency, unconsumed incidental
    ABI/FP lanes/status and identities remain outside this logical profile.
    """
    if not isinstance(phase, ReplayWorldUpdatePlayerLinks):
        raise ValueError("actual existing player-links e00 boundary required")
    if (
        type(phase.next_address) is not int
        or phase.next_address != 0x141629E00
        or phase.returned_status is not None
    ):
        raise ValueError("player pass requires actual e00 handoff without return status")
    _validate(context, calls, phase.world, phase.logical_frame, phase.held_r13, phase.raw_count)
    for channel in (
        virtual_calls,
        virtual_2e8_calls,
        policy_home_calls,
        position_home_calls,
        relationship_calls,
    ):
        if not isinstance(channel, ReplayTaskRebuildCalls):
            raise ValueError("all six actual Calls channels required")
    for value in (
        phase.outer_index,
        phase.entry_time,
        phase.cycle,
        phase.status,
        phase.default_time,
        phase.control_flags,
    ):
        _unsigned(value, 4, "held player-pass DWORD")
    if phase.held_begin is None or phase.xmm8_word is None:
        raise ValueError("e00 must provide held header begin and XMM8 word")
    _unsigned(phase.held_begin, 8, "held e00 begin")
    _unsigned(phase.xmm8_word, 4, "held e00 XMM8")
    if phase.inner_index is not None:
        _unsigned(phase.inner_index, 4, "earlier observed inner index")
    if phase.marker_address is not None:
        _unsigned(phase.marker_address, 8, "earlier observed marker address")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("explicit MXCSR1f80 logical arithmetic profile required")
    return _PlayerPass(
        context,
        calls,
        phase,
        virtual_calls,
        virtual_2e8_calls,
        policy_home_calls,
        position_home_calls,
        relationship_calls,
        phase.held_begin,
        phase.xmm8_word,
    ).run()
