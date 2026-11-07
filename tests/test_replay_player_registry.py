"""Source-derived owned registry controls; no native/runtime identity oracle."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from vantage import replay_player_registry as registry
from vantage.replay_memory import ReplayMemory, ReplayMemoryError, ReplayMemoryRuntimeError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

H, U64 = 0x10000, (1 << 64) - 1
CTOR, FIRST, SECOND, REHASH = 0x141119BE0, 0x14111BD20, 0x14111BDF0, 0x14111BF00
CEIL, LENGTH, ALLOC, VECTOR, FREE = 0xCE1101, 0xCE1102, 0x142D6BA78, 0x1402A94D0, 0x142D6BAB4


class Stop(RuntimeError):
    pass


class Fixture:
    def __init__(self, *, defined: bool = True) -> None:
        self.memory = ReplayMemory(max_bytes=1 << 20)
        if defined:
            self.memory.map_bytes(H, b"\xa5" * 0xB8)
        else:
            self.memory.map_bytes(H - 1, b"\x71")
            # Undefined owned allocation is used as subject by the separate test below.
        self.events: list[tuple[object, ...]] = []
        self.after_read: Callable[[int, int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.before_import: Callable[[int, tuple[int, ...]], None] | None = None
        self.after_import: Callable[[int, tuple[int, ...], int | None], None] | None = None
        self.after_target: Callable[[int, tuple[int, ...]], None] | None = None
        self.stop_target: int | None = None
        self.ceil_word: int | None = None
        self.return_null = False
        self.return_error = False
        self.context = ReplayTaskRebuildStorage(H, self.read, self.write)
        self.runtime = self.memory.runtime_calls()
        self.lower = ReplayTaskRebuildCalls(self.terminal)
        self.bound = registry.bind_replay_player_registry(
            self.context, self.lower, mxcsr=0x1F80, bind_local=self.bind_local, imports=self.lower
        )
        self.calls = ReplayTaskRebuildCalls(self.observe)
        for slot, target in ((0x143199EF0, CEIL), (0x1431992A0, LENGTH), (0x14319A060, 0xBAD111)):
            self.memory.map_bytes(slot, target.to_bytes(8, "little"))
        self.memory.map_bytes(0x1436A0308, bytes.fromhex("0000005f"))

    def read(self, address: int, width: int) -> int:
        value = self.memory.read(address, width)
        self.events.append(("r", address, width, value))
        if self.after_read:
            self.after_read(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.memory.write(address, width, value)
        self.events.append(("w", address, width, value))
        if self.after_write:
            self.after_write(address, width, value)

    def terminal(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("i", target, args))
        if self.before_import:
            self.before_import(target, args)
        if target == ALLOC and self.return_null:
            result = 0
        elif target == CEIL and self.ceil_word is not None:
            result = self.ceil_word
        elif self.return_error and target in (LENGTH, CTOR, 0x1402A9460):
            result = None
        else:
            assert self.runtime.call is not None
            result = self.runtime.call(
                0x142D6E453 if target == CEIL else 0x142D66698 if target == LENGTH else target,
                args,
                data,
            )
        if self.after_import:
            self.after_import(target, args, result)
        return result

    def observe(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        self.events.append(("c", target, args))
        if target == self.stop_target:
            raise Stop(f"actual reached{target:x}")
        assert self.bound.call is not None
        result = self.bound.call(target, args, data)
        if self.after_target:
            self.after_target(target, args)
        return result

    @contextmanager
    def bind_local(self, view: memoryview) -> Iterator[int]:
        with self.memory.bind_local(view) as address:
            self.events.append(("enter", address, bytes(view)))
            try:
                yield address
            finally:
                self.events.append(("exit", address, bytes(view)))

    def construct(self, requested: int = 0, *, bound: bool = False, subject: int = H) -> int:
        if bound:
            assert self.bound.call is not None
            result = self.bound.call(CTOR, (subject, requested), None)
        else:
            result = registry.construct_replay_player_registry(
                self.context, subject, requested, calls=self.calls, mxcsr=0x1F80
            )
        assert result == subject
        return result

    def call(
        self, target: int, args: tuple[int, ...], data: memoryview | None = None
    ) -> int | None:
        assert self.bound.call is not None
        return self.bound.call(target, args, data)

    def vector(self, header: int = H, count: int = 2, capacity: int = 4) -> int:
        begin = self.memory.allocate(capacity * 8)
        self.memory.fill(begin, 0xA7, capacity * 8)
        for offset, value in ((0, begin), (8, begin + count * 8), (16, begin + capacity * 8)):
            self.memory.write(header + offset, 8, value)
        return begin


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("requested,capacity", [(0, 8), (8, 8), (9, 16), (0x100000008, 8)])
def test_full_constructor_real_sentinels_buckets_rehash_and_untouched_bytes(
    bound,
    requested,
    capacity,
) -> None:
    f = Fixture()
    f.construct(requested, bound=bound)
    assert f.memory.read(H, 4) == f.memory.read(H + 0x70, 4) == 0x3F800000
    assert f.memory.read(H + 0x38, 8) == capacity and f.memory.read(H + 0x30, 8) == capacity - 1
    for base in (H, H + 0x70):
        head, table = f.memory.read(base + 8, 8), f.memory.read(base + 0x18, 8)
        assert f.memory.read(head, 8) == f.memory.read(head + 8, 8) == head
        qwords = f.memory.read(base + 0x38, 8) * 2
        assert f.memory.read_bytes(table, qwords * 8) == head.to_bytes(8, "little") * qwords
        with pytest.raises(ReplayMemoryError):
            f.memory.read(head + 16, 1)
    assert f.memory.read(H + 0x58, 8) == 32 and f.memory.read(H + 0xB0, 1) == 0
    for start, width in ((4, 4), (0x74, 4), (0xB1, 7)):
        assert f.memory.read_bytes(H + start, width) == b"\xa5" * width
    imports = [row[1] for row in f.events if row[0] == "i"]
    assert imports.count(CEIL) == 1 and imports.count(ALLOC) == 2
    assert imports.count(VECTOR) == (3 if capacity == 16 else 2)


def test_undefined_subject_padding_stays_undefined_without_blanket_initialization() -> None:
    f = Fixture()
    subject = f.memory.allocate(0xB8)
    f.construct(subject=subject)
    for offset in (4, 0x74, 0xB1):
        with pytest.raises(ReplayMemoryError):
            f.memory.read(subject + offset, 1)


@pytest.mark.parametrize(
    "count,load,expected",
    [(5, 0x40000000, 0x40200000), (1 << 63, 0x3F800000, 0x5F000000), (U64, 0x3F800000, 0x5F800000)],
)
def test_current_count_and_load_after_real_first_resize_reach_ceil_in_source_order(
    count,
    load,
    expected,
) -> None:
    f = Fixture()
    f.ceil_word = 0

    def mutate(target, args):
        if target == FIRST:
            f.memory.write(H + 0x10, 8, count)
            f.memory.write(H, 4, load)

    f.after_target = mutate
    f.construct()
    assert ("i", CEIL, (expected,)) in f.events
    read_count = next(i for i, row in enumerate(f.events) if row[:3] == ("r", H + 0x10, 8))
    read_load = next(i for i, row in enumerate(f.events) if row[:3] == ("r", H, 4))
    call_ceil = next(i for i, row in enumerate(f.events) if row[:2] == ("i", CEIL))
    read_threshold = next(i for i, row in enumerate(f.events) if row[:3] == ("r", 0x1436A0308, 4))
    assert read_count < read_load < call_ceil < read_threshold


@pytest.mark.parametrize(
    "ceil,threshold,expected",
    [
        (0, 0x5F000000, 0),
        (0x80000000, 0x5F000000, 0),
        (0x3FE00000, 0x5F000000, 1),
        (0xBF800000, 0x5F000000, U64),
        (0x5F000000, 0x5F000000, 1 << 63),
        (0x5F800000, 0x5F000000, 1 << 63),
        (0x7FC00001, 0x5F000000, 1 << 63),
        (0x7F800000, 0x5F000000, 1 << 63),
        (0xFF800000, 0x5F000000, 1 << 63),
        (0x40000000, 0x3F800000, 1),
        (0x3F800000, 0xBF800000, 2),
        (0, 0xBF800000, 1),
        (0x3F800000, 0x7FC01234, 1),
        (0x7F800000, 0x7F800000, 0),
        (0xFFC01234, 0x7F800000, 1 << 63),
    ],
)
def test_unsigned_conversion_raw_source_boundaries_no_minimum8(ceil, threshold, expected) -> None:
    assert registry._converted_request(ceil, threshold) == expected


@pytest.mark.parametrize(
    "threshold,expected", [(0x3F800000, 9), (0xBF800000, 11), (0x7FC00001, 10)]
)
def test_ceil_callback_changes_current_threshold_before_conversion(threshold, expected) -> None:
    f = Fixture()
    f.ceil_word = 0x41200000  # Explicit controlled ceil return10; not native observation.
    f.stop_target = REHASH

    def change(target, args, result):
        if target == CEIL:
            f.memory.write(0x1436A0308, 4, threshold)

    f.after_import = change
    with pytest.raises(Stop):
        f.construct()
    assert ("c", REHASH, (H, expected)) in f.events
    assert f.memory.read_bytes(H + 0x40, 8) == b"\xa5" * 8


def test_current_capacity_and_no_minimum8_are_not_replaced_by_initial8() -> None:
    f = Fixture()
    f.ceil_word = 0
    f.after_import = lambda target, args, result: (
        f.memory.write(H + 0x38, 8, 0) if target == CEIL else None
    )
    f.construct()
    assert not [row for row in f.events if row[:2] == ("c", REHASH)]
    assert f.memory.read(H + 0x38, 8) == 0


@pytest.mark.parametrize("raw", [0xFFFFFFFF, 0xFFFFFFFF80000000, 0x80000000])
def test_signed_low32_request_is_held_and_negative_hits_real_length_provider(raw) -> None:
    f = Fixture()
    with pytest.raises(ReplayMemoryRuntimeError):
        f.construct(raw)
    assert ("i", LENGTH, (0x143682938,)) in f.events
    assert f.memory.read_bytes(H + 0x40, 8) == b"\xa5" * 8
    assert not [row for row in f.events if row[:3] == ("w", H + 0x70, 4)]


def test_current_ceil_IAT_selected_owned_token_is_terminal_not_recursive() -> None:
    f = Fixture()
    f.memory.write(0x143199EF0, 8, CTOR)
    f.return_error = True
    with pytest.raises(ValueError, match="raw scalar"):
        f.construct(bound=True)
    assert ("i", CTOR, (0,)) in f.events
    assert len([row for row in f.events if row[:2] == ("r", 0x143199EF0)]) == 1


def test_missing_ceil_or_null_sentinel_retains_only_reached_prefix_writes() -> None:
    f = Fixture()
    f.memory.write(0x143199EF0, 8, 0xBAD)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.construct()
    assert f.memory.read(H, 4) == 0x3F800000
    assert f.memory.read_bytes(H + 0x40, 8) == b"\xa5" * 8
    f = Fixture()
    f.return_null = True
    with pytest.raises(ReplayMemoryError):
        f.construct(bound=True)
    assert f.memory.read(H, 4) == f.memory.read(H + 8, 8) == f.memory.read(H + 16, 8) == 0
    assert not [row for row in f.events if row[:2] == ("i", VECTOR)]


@pytest.mark.parametrize("primary", [False, True])
def test_resize_reuses_real_fill_then_grows_with_actual_release_target(primary) -> None:
    f = Fixture()
    old = f.vector()
    entry, release, fill = (
        (FIRST, 0x14111C560, 0x141119AC0) if primary else (SECOND, 0x14111C5C0, 0x141119B50)
    )
    resize = (
        registry.resize_replay_player_registry_primary_buckets
        if primary
        else registry.resize_replay_player_registry_secondary_buckets
    )
    resize(f.context, H, 1, 0x123456789ABCDEF0, calls=f.calls, mxcsr=0x1F80)
    assert ("c", fill, (old, old + 16)) in f.events
    assert f.memory.read_bytes(old, 16) == bytes.fromhex("f0debc9a78563412") * 2
    resize(f.context, H, 5, 7, calls=f.calls, mxcsr=0x1F80)
    assert ("c", release, (H, old, 4)) in f.events
    assert ("i", FREE, (old, 32)) in f.events
    with pytest.raises(ReplayMemoryError):
        f.memory.read(old, 1)
    begin = f.memory.read(H, 8)
    assert f.memory.read_bytes(begin, 40) == (7).to_bytes(8, "little") * 5
    assert f.call(entry, (H, 0, 9)) is None
    assert not [row for row in f.events if row[:2] == ("c", 0x141143790)]


def test_postallocation_current_begin_capacity_choose_real_free_before_commit() -> None:
    f = Fixture()
    old = f.vector()
    alternate = f.memory.allocate(16)

    def mutate(target, args, result):
        if target == VECTOR:
            f.memory.write(H, 8, alternate)
            f.memory.write(H + 16, 8, alternate + 16)

    f.after_import = mutate
    f.call(FIRST, (H, 6, 99))
    assert ("i", FREE, (alternate, 16)) in f.events
    assert f.memory.read(old, 1) == 0xA7
    with pytest.raises(ReplayMemoryError):
        f.memory.read(alternate, 1)


@pytest.mark.parametrize("target", [FIRST, SECOND])
def test_resize_returned_fatal_helper_stops_before_any_header_write(target) -> None:
    f = Fixture()
    f.vector(count=0)
    before = f.memory.read_bytes(H, 24)
    f.return_error = True
    with pytest.raises(RuntimeError, match="returned"):
        f.call(target, (H, 1 << 61, 7))
    assert f.memory.read_bytes(H, 24) == before
    assert ("i", 0x1402A9460, ()) in f.events


@pytest.mark.parametrize("target", [0x14111C560, 0x14111C5C0])
def test_release_current_Watson_selected_owned_token_is_terminal_and_no_free(target) -> None:
    f = Fixture()
    begin = f.memory.allocate_aligned(0x1000)
    f.memory.write(begin - 8, 8, begin - 0x28)
    f.memory.write(0x14319A060, 8, CTOR)
    f.return_error = True
    with pytest.raises(RuntimeError, match="returned"):
        f.call(target, (0xDEAD, begin, 512))
    assert ("i", CTOR, (0, 0, 0, 0, 0)) in f.events
    assert not [row for row in f.events if row[:2] == ("i", FREE)]


@pytest.mark.parametrize("target", [0x141119AC0, 0x141119B50])
def test_raw_fill_partial_alias_keeps_current_source_and_scalar_order(target) -> None:
    f = Fixture()
    begin = f.memory.allocate(24)
    f.memory.write_bytes(begin, bytes(range(24)))
    original = bytearray(f.memory.read_bytes(begin, 24))
    for at in (0, 8, 16):
        original[at : at + 8] = original[4:12]
    assert f.call(target, (begin, begin + 24, begin + 4)) is None
    assert f.memory.read_bytes(begin, 24) == original


def test_rehash_real_nodes_duplicate_order_and_count_preservation() -> None:
    f = Fixture()
    f.construct(bound=True)
    head = f.memory.read(H + 8, 8)
    nodes = [f.memory.allocate(24) for _ in range(4)]
    chain = [head, *nodes]
    for index, node in enumerate(chain):
        f.memory.write(node, 8, chain[(index + 1) % len(chain)])
        f.memory.write(node + 8, 8, chain[(index - 1) % len(chain)])
    for node, key in zip(nodes, (1, 2, 1, 17), strict=True):
        f.memory.write(node + 16, 4, key)
    f.memory.write(H + 16, 8, 4)
    f.call(REHASH, (H, 16))
    assert f.memory.read(H + 16, 8) == 4 and f.memory.read(H + 0x38, 8) == 16
    at, observed = f.memory.read(head, 8), []
    while at != head:
        observed.append(f.memory.read(at + 16, 4))
        after = f.memory.read(at, 8)
        assert f.memory.read(after + 8, 8) == at
        at = after
        assert len(observed) <= 4
    assert observed == [17, 1, 1, 2]


@pytest.mark.parametrize("requested,expected", [(0, 1), (1, 2), (2, 2), (3, 4), (8, 8)])
def test_direct_rehash_has_no_invented_minimum8(requested, expected) -> None:
    f = Fixture()
    f.construct(bound=True)
    f.call(REHASH, (H, requested))
    assert f.memory.read(H + 0x38, 8) == expected


@pytest.mark.parametrize(
    "target,args,data",
    [
        (CTOR, (H,), None),
        (FIRST, (H, 1), None),
        (SECOND, (H, 1, 0), memoryview(bytearray(8))),
        (REHASH, (H, True), None),
        (0x141119AC0, (H, H + 8), None),
        (0x14111C560, (H, H, 1, 2), None),
        (0x142D6E453, (1 << 32,), None),
    ],
)
def test_malformed_bound_ABI_refuses_before_body_effects(target, args, data) -> None:
    f = Fixture()
    before = f.memory.snapshot()
    with pytest.raises(ValueError):
        f.call(target, args, data)
    assert f.memory.snapshot() == before and not f.events


@pytest.mark.parametrize("mxcsr", [0, 0x3F80, 0x9F80, 0x1FC0])
def test_nondefault_FP_controls_reject_before_writes(mxcsr) -> None:
    f = Fixture()
    with pytest.raises(ValueError, match="MXCSR"):
        registry.construct_replay_player_registry(f.context, H, 0, calls=f.calls, mxcsr=mxcsr)
    assert not f.events


def test_unknown_binding_delegates_and_unavailable_binding_never_succeeds() -> None:
    f = Fixture()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        f.call(0xBADC0DE, (5,))
    assert ("i", 0xBADC0DE, (5,)) in f.events
    calls = registry.bind_replay_player_registry(
        f.context, ReplayTaskRebuildCalls(None), mxcsr=0x1F80, bind_local=f.bind_local
    )
    assert calls.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        calls.call(0xBADC0DE, (), None)


def test_distinct_lower_and_terminal_providers_execute_real_allocations_and_free() -> None:
    f = Fixture()
    lower_calls, terminal_calls = [], []
    runtime = f.memory.runtime_calls()

    def lower(target, args, data):
        lower_calls.append((target, args))
        assert target in (ALLOC, VECTOR)
        assert runtime.call is not None
        return runtime.call(target, args, data)

    def terminal(target, args, data):
        terminal_calls.append((target, args))
        assert target in (FIRST, FREE)
        assert runtime.call is not None
        return runtime.call(0x142D6E453 if target == FIRST else target, args, data)

    # The selected import token deliberately equals an owned resize entry.
    # Explicit terminal routing gives it engine-ceil meaning in this control.
    f.memory.write(0x143199EF0, 8, FIRST)
    bound = registry.bind_replay_player_registry(
        f.context,
        ReplayTaskRebuildCalls(lower),
        mxcsr=0x1F80,
        bind_local=f.bind_local,
        imports=ReplayTaskRebuildCalls(terminal),
    )
    assert bound.call is not None and bound.call(CTOR, (H, 9), None) == H
    assert [target for target, args in lower_calls] == [ALLOC, VECTOR, VECTOR, ALLOC, VECTOR]
    assert [target for target, args in terminal_calls] == [FIRST, FREE]
    assert terminal_calls[0] == (FIRST, (0,))
    old = terminal_calls[1][1][0]
    assert terminal_calls[1][1][1] == 128
    with pytest.raises(ReplayMemoryError):
        f.memory.read(old, 1)


def test_current_first_sentinel_read_after_publication_controls_real_bucket_values() -> None:
    f = Fixture()
    alternate = f.memory.allocate(0x38)
    f.memory.write(alternate, 8, alternate)
    f.memory.write(alternate + 8, 8, alternate)

    def change(address, width, value):
        if address == H + 8 and width == 8 and value:
            f.memory.write(H + 8, 8, alternate)

    f.after_write = change
    f.construct(bound=True)
    table = f.memory.read(H + 0x18, 8)
    assert f.memory.read_bytes(table, 128) == alternate.to_bytes(8, "little") * 16


def test_live_mapping_exit_cannot_suppress_actual_fill_failure() -> None:
    f = Fixture()

    @contextmanager
    def suppress(view):
        try:
            with f.memory.bind_local(view) as address:
                yield address
        except ReplayMemoryError:
            return

    bound = registry.bind_replay_player_registry(
        f.context, f.lower, mxcsr=0x1F80, bind_local=suppress
    )
    assert bound.call is not None
    before = f.memory.snapshot()
    with pytest.raises(ReplayMemoryError):
        bound.call(0x141119AC0, (0xBAD, 0xBB5), memoryview(bytearray(8)))
    after = f.memory.snapshot()
    assert after.regions == before.regions and after.next_address == before.next_address + 8


@pytest.mark.parametrize("mxcsr", [0x1F80, 0x1FBF])
def test_sticky_status_excluded_default_control_profile_is_accepted(mxcsr) -> None:
    f = Fixture()
    assert (
        registry.construct_replay_player_registry(f.context, H, 0, calls=f.calls, mxcsr=mxcsr) == H
    )
