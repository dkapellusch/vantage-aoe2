"""Source-led owned Python byte controls; no native/allocator identity claim."""

from __future__ import annotations

import pytest

from vantage.replay_player_name_skins_storage import (
    bind_replay_player_name_skins_storage,
    commit_replay_player_skins,
    grow_replay_player_sso,
    release_replay_player_sso,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

U64 = (1 << 64) - 1


class Bytes:
    """Finite defined-byte fixture; actual copy/fill effects and ordered events."""

    def __init__(self):
        self.cells, self.events = {}, []
        self.hook, self.extra = None, {}
        self.freed = []
        self.h, self.old, self.new = 0x1000, 0x2000, 0x4000
        self.map(self.h, 32)
        self.map(self.old - 8, 0x100)
        self.map(0x14319A060, 8)
        self.put(0x14319A060, 8, 0xFEED)
        self.storage = ReplayTaskRebuildStorage(self.h, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.effect)
        self.imports = ReplayTaskRebuildCalls(self.imported)

    def map(self, pointer, size, value=0):
        for index in range(size):
            self.cells[(pointer + index) & U64] = value

    def get(self, pointer, size):
        return int.from_bytes(
            bytes(self.cells[(pointer + index) & U64] for index in range(size)), "little"
        )

    def put(self, pointer, size, value):
        raw = (value & ((1 << (size * 8)) - 1)).to_bytes(size, "little")
        for index, byte in enumerate(raw):
            at = (pointer + index) & U64
            assert at in self.cells
            self.cells[at] = byte

    def read(self, pointer, size):
        value = self.get(pointer, size)
        self.events.append(("read", pointer, size, value))
        if self.hook:
            self.hook("read", pointer, size, value)
        return value

    def write(self, pointer, size, value):
        self.put(pointer, size, value)
        self.events.append(("write", pointer, size, value))
        if self.hook:
            self.hook("write", pointer, size, value)

    def effect(self, target, args, data):
        assert data is None
        self.events.append(("call", target, args))
        if target in self.extra:
            return self.extra[target](args)
        if target == 0x1402A94D0:
            assert args[0] < 0x10000, "fixture allocator size bound"
            self.map(self.new, args[0], 0xA3)
            return self.new
        if target == 0x142D6E3B1:
            destination, source, size = args
            self.put(destination, size, self.get(source, size))
            return 0xBAADF00D  # Source ignores both copy/fill return registers.
        if target == 0x142D6E3B7:
            destination, character, size = args
            self.put(destination, size, int.from_bytes(bytes([character & 255]) * size, "little"))
            return 0xBAADF00D
        if target == 0x142D6BAB4:
            self.freed.append(args)
            return None
        raise UnresolvedReplayTaskRebuild(f"required child{target:x}")

    def imported(self, target, args, data):
        assert data is None
        self.events.append(("terminal", target, args))
        return None

    def sso(self, length=4, capacity=15, raw=b"ABCD"):
        if capacity > 15:
            self.put(self.h, 8, self.old)
            self.put(self.old, len(raw), int.from_bytes(raw, "little"))
        else:
            self.put(self.h, len(raw), int.from_bytes(raw, "little"))
        self.put(self.h + 16, 8, length)
        self.put(self.h + 24, 8, capacity)

    def growth(self, increment=20, fill=20, character=0, ignored=0xBEEF, *, bound=False):
        if bound:
            calls = bind_replay_player_name_skins_storage(
                self.storage, self.calls, imports=self.imports
            )
            return calls.call(0x1402BB300, (self.h, increment, ignored, fill, character), None)
        # Growth's heap branch composes its real sibling release, not a fake effect.
        calls = bind_replay_player_name_skins_storage(
            self.storage, self.calls, imports=self.imports
        )
        return grow_replay_player_sso(
            self.storage, self.h, increment, ignored, fill, character, calls=calls
        )


@pytest.mark.parametrize("capacity", [15, 16])
@pytest.mark.parametrize(
    "character,word", [(0, 0), (127, 127), (128, 0xFFFFFF80), (255, 0xFFFFFFFF), (0x10042, 66)]
)
def test_sso_and_heap_copy_fill_publication(capacity, character, word):
    c = Bytes()
    c.sso(capacity=capacity)
    assert c.growth(character=character, bound=bool(capacity & 1)) == c.h
    assert c.get(c.h, 8) == c.new and c.get(c.h + 16, 8) == 24
    assert c.get(c.h + 24, 8) == 31
    assert c.get(c.new, 4) == int.from_bytes(b"ABCD", "little")
    assert c.get(c.new + 4, 20) == int.from_bytes(bytes([character & 255]) * 20, "little")
    assert c.get(c.new + 24, 1) == 0
    calls = [row for row in c.events if row[0] == "call"]
    assert calls[0] == ("call", 0x1402A94D0, (32,))
    assert ("call", 0x142D6E3B7, (c.new + 4, word, 20)) in calls
    assert c.freed == ([(c.old, 17)] if capacity > 15 else [])
    assert c.events[-1] == ("write", c.h, 8, c.new)


def test_growth_independent_increment_and_fill():
    c = Bytes()
    c.sso(capacity=40)
    c.growth(increment=3, fill=1, character=0x61)
    assert c.get(c.h + 16, 8) == 7 and c.get(c.h + 24, 8) == 60
    assert c.get(c.new + 4, 1) == 0x61 and c.get(c.new + 5, 1) == 0
    assert c.get(c.new + 6, 1) == 0xA3
    assert c.freed == [(c.old, 41)]


def test_zero_copy_and_fill_still_calls():
    c = Bytes()
    c.sso(length=0, capacity=0, raw=b"")
    c.growth(increment=0, fill=0)
    assert ("call", 0x142D6E3B1, (c.new, c.h, 0)) in c.events
    assert ("call", 0x142D6E3B7, (c.new, 0, 0)) in c.events
    assert c.get(c.h + 24, 8) == 15 and c.get(c.new, 1) == 0


def test_old_length_held_but_capacity_and_pointer_current():
    c = Bytes()
    c.sso(capacity=15)
    alternate = 0x3000
    c.map(alternate, 8)
    c.put(alternate, 4, int.from_bytes(b"WXYZ", "little"))

    def hook(kind, address, width, value):
        if kind == "read" and address == c.h + 16:
            c.put(c.h + 24, 8, 40)
            c.put(c.h + 16, 8, 99)
        if kind == "write" and address == c.h + 24:
            c.put(c.h, 8, alternate)

    c.hook = hook
    c.growth(increment=1, fill=1)
    assert c.get(c.h + 16, 8) == 5 and c.get(c.h + 24, 8) == 60
    assert c.get(c.new, 4) == int.from_bytes(b"WXYZ", "little")
    assert c.freed == [(alternate, 41)]


@pytest.mark.parametrize("target", [0x142D6E3B1, 0x142D6E3B7, 0x142D6BAB4])
def test_growth_failure_preserves_prior_fields_and_old_pointer(target):
    c = Bytes()
    c.sso(capacity=16)

    def fail(args):
        raise UnresolvedReplayTaskRebuild(f"stopped{target:x}")

    c.extra[target] = fail
    with pytest.raises(UnresolvedReplayTaskRebuild, match="stopped"):
        c.growth()
    assert c.get(c.h, 8) == c.old
    assert c.get(c.h + 16, 8) == 24 and c.get(c.h + 24, 8) == 31
    assert not any(row == ("write", c.h, 8, c.new) for row in c.events)


def test_allocator_failure_before_header_publication():
    c = Bytes()
    c.sso()
    before = c.get(c.h, 32)
    c.extra[0x1402A94D0] = lambda args: (_ for _ in ()).throw(ValueError("allocator"))
    with pytest.raises(ValueError, match="allocator"):
        c.growth()
    assert c.get(c.h, 32) == before
    assert not any(row[0] == "write" for row in c.events)


@pytest.mark.parametrize("old_length,increment", [((1 << 63) - 1, 1), ((1 << 63) - 2, 2)])
def test_length_error_before_capacity_read(old_length, increment):
    c = Bytes()
    c.put(c.h + 16, 8, old_length)
    for at in range(c.h + 24, c.h + 32):
        del c.cells[at]
    c.extra[0x1402A91E0] = lambda args: None
    with pytest.raises(UnresolvedReplayTaskRebuild, match="length error returned"):
        c.growth(increment=increment)
    assert c.events == [("read", c.h + 16, 8, old_length), ("call", 0x1402A91E0, ())]


@pytest.mark.parametrize("length,capacity", [(0, (1 << 63) - 1), ((1 << 63) - 1, 15), (U64, 15)])
def test_saturating_capacity_and_wrapped_length_gate(length, capacity):
    c = Bytes()
    c.sso(length=length, capacity=capacity)
    requests = []

    def stop(args):
        requests.append(args)
        raise ValueError("finite fixture allocation frontier")

    c.extra[0x1402A94D0] = stop
    with pytest.raises(ValueError, match="frontier"):
        c.growth(increment=0, fill=0)
    assert requests == [(1 << 63,)]
    assert not any(row[0] == "write" for row in c.events)


def test_null_allocator_has_no_invented_early_success():
    c = Bytes()
    c.sso()
    c.extra[0x1402A94D0] = lambda args: 0
    c.extra[0x142D6E3B1] = lambda args: (_ for _ in ()).throw(ValueError("copy atNULL"))
    with pytest.raises(ValueError, match="copy atNULL"):
        c.growth()
    assert c.get(c.h + 16, 8) == 24 and c.get(c.h + 24, 8) == 31
    assert c.get(c.h, 4) == int.from_bytes(b"ABCD", "little")


@pytest.mark.parametrize("previous,size", [(0, 0), (0x2000, 0), (0x2000, 15), (0x2000, 0xFF8)])
def test_commit_null_small_mask_and_three_held_stores(previous, size):
    c = Bytes()
    c.put(c.h, 8, previous)
    c.put(c.h + 16, 8, previous + size)
    commit_replay_player_skins(c.storage, c.h, c.new, 3, 9, calls=c.calls)
    assert c.get(c.h, 8) == c.new and c.get(c.h + 8, 8) == c.new + 24
    assert c.get(c.h + 16, 8) == c.new + 72
    assert c.freed == ([(previous, size & ~7)] if previous else [])
    assert [row[1] for row in c.events if row[0] == "write"] == [c.h, c.h + 8, c.h + 16]


def test_commit_null_skips_capacity_and_wraps_new_headers():
    c = Bytes()
    for at in range(c.h + 16, c.h + 24):
        del c.cells[at]
    # Writes still have valid backing; the read hook proves no capacity read.
    c.map(c.h + 16, 8)
    commit_replay_player_skins(c.storage, c.h, U64 - 3, 1, 2, calls=c.calls)
    assert not any(row[0] == "read" and row[1] == c.h + 16 for row in c.events)
    assert c.get(c.h + 8, 8) == 4 and c.get(c.h + 16, 8) == 12


@pytest.mark.parametrize("delta", [0, 31, 32, -1])
@pytest.mark.parametrize("entry", ["commit", "release"])
def test_large_backpointer_guard_and_terminal_Watson(delta, entry):
    c = Bytes()
    base = c.old - 8 - delta
    c.put(c.old - 8, 8, base)
    c.put(c.h, 8, c.old)
    c.put(c.h + 16, 8, c.old + 0x1000)
    before = c.get(c.h, 24)

    def operation():
        if entry == "commit":
            commit_replay_player_skins(
                c.storage, c.h, c.new, 1, 2, calls=c.calls, imports=c.imports
            )
        else:
            release_replay_player_sso(c.storage, 0, c.old, 0xFFF, calls=c.calls, imports=c.imports)

    if 0 <= delta <= 31:
        operation()
        assert c.freed == [(base, 0x1027)]
    else:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned"):
            operation()
        assert c.get(c.h, 24) == before and not c.freed
        assert c.events[-1] == ("terminal", 0xFEED, (0, 0, 0, 0, 0))


@pytest.mark.parametrize(
    "previous,capacity,size", [(0, 0, 1), (0, U64, 0), (0x2000, 15, 16), (0x2000, 0xFFE, 0xFFF)]
)
def test_release_ignores_holder_and_has_no_header_or_null_reset(previous, capacity, size):
    c = Bytes()
    release_replay_player_sso(c.storage, U64, previous, capacity, calls=c.calls)
    assert c.freed == [(previous, size)]
    assert c.events == [("call", 0x142D6BAB4, (previous, size))]


def test_commit_free_mutation_cannot_replace_held_replacement():
    c = Bytes()
    c.put(c.h, 8, c.old)
    c.put(c.h + 16, 8, c.old + 8)

    def changed(args):
        c.put(c.h, 24, (1 << 192) - 1)

    c.extra[0x142D6BAB4] = changed
    commit_replay_player_skins(c.storage, c.h, c.new, 1, 2, calls=c.calls)
    assert [c.get(c.h + offset, 8) for offset in (0, 8, 16)] == [c.new, c.new + 8, c.new + 16]


def test_commit_failure_before_any_header_write():
    c = Bytes()
    c.put(c.h, 8, c.old)
    c.put(c.h + 16, 8, c.old + 8)
    before = c.get(c.h, 24)
    c.extra[0x142D6BAB4] = lambda args: (_ for _ in ()).throw(ValueError("realfree"))
    with pytest.raises(ValueError, match="realfree"):
        commit_replay_player_skins(c.storage, c.h, c.new, 1, 2, calls=c.calls)
    assert c.get(c.h, 24) == before


@pytest.mark.parametrize(
    "target,args", [(0x1402BB300, (1, 2, 3, 4)), (0x1402BA970, (1, 2, 3)), (0x1402A8840, (1, 2))]
)
def test_binder_actual_arities_and_data(target, args):
    c = Bytes()
    bound = bind_replay_player_name_skins_storage(c.storage, c.calls)
    with pytest.raises(ValueError, match="malformed"):
        bound.call(target, args, None)
    count = {0x1402BB300: 5, 0x1402BA970: 4, 0x1402A8840: 3}[target]
    with pytest.raises(ValueError, match="malformed"):
        bound.call(target, (0,) * count, memoryview(b"x"))
    assert not c.events


def test_binder_current_Watson_alias_stays_terminal():
    c = Bytes()
    c.put(c.old - 8, 8, c.old)
    c.put(0x14319A060, 8, 0x1402BB300)
    bound = bind_replay_player_name_skins_storage(c.storage, c.calls, imports=c.imports)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="Watson returned"):
        bound.call(0x1402A8840, (0, c.old, 0xFFF), None)
    assert c.events[-1] == ("terminal", 0x1402BB300, (0, 0, 0, 0, 0))


def test_binder_missing_children_and_unknown_delegation():
    c = Bytes()
    unavailable = bind_replay_player_name_skins_storage(c.storage, ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        unavailable.call(0x1402A8840, (0, 0, 0), None)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        unavailable.call(0x111, (), None)
    c.extra[0x111] = lambda args: 9
    assert bind_replay_player_name_skins_storage(c.storage, c.calls).call(0x111, (7,), None) == 9
