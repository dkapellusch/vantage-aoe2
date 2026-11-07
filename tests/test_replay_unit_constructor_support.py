"""Source-derived Base/Moving support controls with actual owned byte effects."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_constructor_support import (
    assign_replay_constructor_string,
    bind_replay_unit_constructor_support,
    clear_replay_unit_support_tree,
    grow_replay_constructor_string,
    initialize_replay_unit_support_header,
    notify_replay_unit_support_registry,
    read_replay_constructor_string_length,
    reset_replay_unit_moving_buffer,
    return_replay_unit_support_token,
)

U64 = (1 << 64) - 1
HEADER, STRING, GROW, RESET = 0x1410B2A40, 0x140A1A660, 0x140A1A5E0, 0x141219F20
SCAN, COPY, FREE = 0x501, 0x502, 0x503
LENGTH_IAT, COPY_IAT, FREE_IAT = 0x14319A290, 0x143199930, 0x143199DD0
GLOBAL = 0x1442973E0


class Harness:
    def __init__(self):
        self.memory = ReplayMemory()
        self.events = []
        self.active = 0
        self.local_values = []
        self.after_read = lambda address, width, value: None
        self.after_write = lambda address, width, value: None
        self.on_call = lambda target, args, data: None
        self.on_import = lambda target, args: None
        self.runtime = self.memory.runtime_calls()
        for address, target in ((LENGTH_IAT, SCAN), (COPY_IAT, COPY), (FREE_IAT, FREE)):
            self.memory.map_bytes(address, target.to_bytes(8, "little"))
        self.context = ReplayTaskRebuildStorage(1, self.read, self.write)
        self.calls = ReplayTaskRebuildCalls(self.call)
        self.imports = ReplayTaskRebuildCalls(self.imported)
        self.bound = bind_replay_unit_constructor_support(
            self.context, self.calls, bind_local=self.bind_local, imports=self.imports
        )

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("read", address, width, value))
        self.after_read(address, width, value)
        return value

    def write(self, address, width, value):
        self.events.append(("write", address, width, value))
        self.memory.write(address, width, value)
        self.after_write(address, width, value)

    def call(self, target, args, data):
        self.events.append(("call", target, args, data))
        if target == 0x142D6BA78:
            assert self.runtime.call is not None
            return self.runtime.call(target, args, data)
        return self.on_call(target, args, data)

    def imported(self, target, args, data):
        assert data is None
        self.events.append(("import", target, args))
        self.on_import(target, args)
        if target == SCAN:
            length = 0
            while self.memory.read(args[0] + length, 1):
                length += 1
            return length
        if target == COPY:
            return self.memory.move(*args)
        if target == FREE:
            self.memory.free(args[0])
            return None
        raise UnresolvedReplayTaskRebuild("unknown test import")

    @contextmanager
    def bind_local(self, view):
        self.local_values.append(view.tobytes())
        self.active += 1
        try:
            with self.memory.bind_local(view) as address:
                yield address
        finally:
            self.active -= 1

    def invoke(self, target, *args):
        assert self.bound.call is not None
        return self.bound.call(target, args, None)

    def block(self, size, byte=0xA5):
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([byte]) * size)
        return address

    def string(self, pointer=0, length=0, capacity=0):
        address = self.block(40)
        for offset, value in ((0, pointer), (8, length), (16, capacity)):
            self.memory.write(address + offset, 8, value)
        return address

    def text(self, raw=b"hello\0"):
        return self.block(len(raw), 0) if not raw else self._text(raw)

    def _text(self, raw):
        address = self.memory.allocate(len(raw))
        self.memory.write_bytes(address, raw)
        return address


@pytest.mark.parametrize("word", [0, 1, 0xABCDEF0180000000, U64])
def test_header_order_raw_low_word_and_guard_bytes(word) -> None:
    h = Harness()
    address = h.block(56)
    assert h.invoke(HEADER, address, word) == address
    assert h.events == [
        ("write", address + 0x14, 4, word & 0xFFFFFFFF),
        ("write", address + 8, 8, 0),
        ("write", address, 8, 0x14329FE18),
        ("write", address + 0x10, 4, 0),
        ("write", address + 0x18, 8, U64),
        ("write", address + 0x20, 8, U64),
    ]
    assert h.memory.read_bytes(address + 40, 16) == b"\xa5" * 16


def test_header_partial_write_failure_retains_first_field() -> None:
    h = Harness()
    address = h.block(40)

    def write(at, width, value):
        if at == address + 8:
            raise RuntimeError("second store")
        h.memory.write(at, width, value)

    context = ReplayTaskRebuildStorage(1, h.read, write)
    with pytest.raises(RuntimeError, match="second store"):
        initialize_replay_unit_support_header(context, address, 0x123)
    assert h.memory.read(address + 0x14, 4) == 0x123
    assert h.memory.read_bytes(address, 16) == b"\xa5" * 16


@pytest.mark.parametrize(
    "requested,capacity",
    [
        (1, 32),
        (15, 32),
        (16, 16),
        (17, 32),
        (31, 32),
        (32, 32),
        (33, 64),
        (0x100000000, 0x100000000),
        (0x100000001, 0x1FFFFFFFF),
        (0x8000000000000001, 0xFFFFFFFF00000001),
        (U64, 0),
    ],
)
def test_growth_exact_five_shifts_no_extra_shift32(requested, capacity) -> None:
    h = Harness()
    address = h.string(0x123, 7, 0x999)
    seen = []

    def call(target, args, data):
        seen.append((target, args, data))
        return 0xF00D

    grow_replay_constructor_string(
        h.context, address, requested, calls=ReplayTaskRebuildCalls(call)
    )
    assert seen == [(0x142D6C268, (capacity,), None)]
    assert h.events == [("write", address + 16, 8, capacity), ("write", address, 8, 0xF00D)]
    assert h.memory.read(address + 8, 8) == 7


def test_zero_growth_no_access_or_provider_and_null_malloc_is_stored() -> None:
    h = Harness()
    grow_replay_constructor_string(h.context, 0, 0, calls=ReplayTaskRebuildCalls(None))
    assert h.events == []
    address = h.string(1, 2, 3)
    grow_replay_constructor_string(
        h.context, address, 16, calls=ReplayTaskRebuildCalls(lambda *args: 0)
    )
    assert h.memory.read(address, 8) == 0 and h.memory.read(address + 16, 8) == 16


def test_growth_failures_preserve_prior_effects() -> None:
    h = Harness()
    address = h.string(1, 2, 3)
    before = h.memory.snapshot()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        grow_replay_constructor_string(h.context, address, 16, calls=ReplayTaskRebuildCalls(None))
    assert h.memory.snapshot() == before

    def write(at, width, value):
        if at == address:
            raise RuntimeError("pointer store")
        h.memory.write(at, width, value)

    with pytest.raises(RuntimeError, match="pointer store"):
        grow_replay_constructor_string(
            ReplayTaskRebuildStorage(1, h.read, write),
            address,
            16,
            calls=ReplayTaskRebuildCalls(lambda *args: 0xABC),
        )
    assert h.memory.read(address + 16, 8) == 16
    assert h.memory.read(address, 8) == 1


@pytest.mark.parametrize("old_kind", ["null", "borrowed", "owned"])
@pytest.mark.parametrize("raw", [b"\0", b"hello\0", b"x" * 16 + b"\0"])
def test_actual_string_scan_allocate_copy_free_and_definedness(old_kind, raw) -> None:
    h = Harness()
    old = h.block(16, 0xCC) if old_kind != "null" else 0
    address = h.string(old, 7, 16 if old_kind == "owned" else 0)
    source = h.text(raw)
    assert h.invoke(STRING, address, source) is None
    length = len(raw) - 1
    assert h.local_values == [source.to_bytes(8, "little") + length.to_bytes(8, "little")]
    assert h.active == 0
    assert h.memory.read_bytes(address + 24, 16) == b"\xa5" * 16
    if old_kind == "owned":
        with pytest.raises(ReplayMemoryError, match="unmapped"):
            h.memory.read(old, 1)
    elif old:
        assert h.memory.read_bytes(old, 16) == b"\xcc" * 16
    if length:
        pointer = h.memory.read(address, 8)
        assert h.memory.read_bytes(pointer, length + 1) == raw
        assert h.memory.read(address + 8, 8) == length
        region = next(r for r in h.memory.snapshot().regions if r.address == pointer)
        assert region.defined[: length + 1] == b"\x01" * (length + 1)
        assert region.defined[length + 1 :] == bytes(len(region.defined) - length - 1)
    else:
        assert h.memory.read(address, 8) == (0x14428BB30 if old else 0)
        assert h.memory.read(address + 8, 8) == (0 if old else 7)
        assert not any(e[0] == "call" and e[1] == 0x142D6BA78 for e in h.events)


def test_direct_string_entry_composes_real_current_imports_and_growth() -> None:
    h = Harness()
    address, source = h.string(), h.text(b"direct\0")
    assign_replay_constructor_string(
        h.context, address, source, calls=h.bound, bind_local=h.bind_local
    )
    assert h.memory.read_bytes(h.memory.read(address, 8), 7) == b"direct\0"
    assert h.memory.read(address + 8, 8) == 6
    assert h.active == 0


def test_raw_length_wrap_skips_growth_without_inventing_overflow_guard() -> None:
    h = Harness()
    address = h.string()
    seen = []

    def child(target, args, data):
        seen.append((target, args))
        if target == 0x142D6E44D:
            return U64
        assert target == 0x142D6E3B1 and args == (0, 0xBAD, U64)
        raise RuntimeError("actual huge copy refused")

    with pytest.raises(RuntimeError, match="huge copy"):
        assign_replay_constructor_string(
            h.context,
            address,
            0xBAD,
            calls=ReplayTaskRebuildCalls(child),
            bind_local=h.bind_local,
        )
    assert seen == [(0x142D6E44D, (0xBAD,)), (0x142D6E3B1, (0, 0xBAD, U64))]
    assert h.memory.read(address + 16, 8) == 0
    assert h.active == 0


def test_null_old_pointer_skips_undefined_length_capacity_and_null_source_skips_local() -> None:
    h = Harness()
    address = h.memory.allocate(24)
    h.memory.write(address, 8, 0)
    h.invoke(STRING, address, 0)
    assert h.events == [("read", address, 8, 0)]
    assert h.local_values == []
    region = next(r for r in h.memory.snapshot().regions if r.address == address)
    assert region.defined == b"\x01" * 8 + bytes(16)


def test_nonnull_old_pointer_cap_zero_resets_without_free_or_bss_read() -> None:
    h = Harness()
    address = h.string(0x14428BB30, 99, 0)
    h.invoke(STRING, address, 0)
    assert h.events == [
        ("read", address, 8, 0x14428BB30),
        ("read", address + 16, 8, 0),
        ("write", address, 8, 0x14428BB30),
        ("write", address + 16, 8, 0),
        ("write", address + 8, 8, 0),
    ]


def test_old_source_alias_is_not_copied_before_actual_free() -> None:
    h = Harness()
    old = h.text(b"abc\0")
    address = h.string(old, 3, 4)
    with pytest.raises(ReplayMemoryError, match="unmapped"):
        h.invoke(STRING, address, old)
    assert h.memory.read(address, 8) == 0x14428BB30
    assert h.memory.read(address + 8, 8) == h.memory.read(address + 16, 8) == 0
    assert h.local_values == []


def test_copy_uses_held_length_source_but_terminator_rereads_current_pointer() -> None:
    h = Harness()
    address, source = h.string(), h.text(b"abc\0")
    replacement = h.block(16, 0xCC)

    def imported(target, args):
        if target == COPY:
            assert h.active == 1
            assert args[1:] == (source, 3)
            h.memory.write(address, 8, replacement)
            h.memory.write(address + 8, 8, 77)

    h.on_import = imported
    h.invoke(STRING, address, source)
    assert h.memory.read_bytes(replacement, 8) == b"\xcc\xcc\xcc\0" + b"\xcc" * 4
    assert h.memory.read(address + 8, 8) == 3
    copied = next(e[2][0] for e in h.events if e[0] == "import" and e[1] == COPY)
    assert h.memory.read_bytes(copied, 3) == b"abc"


def test_current_copy_iat_is_sampled_after_scan_and_bypasses_owned_alias_token() -> None:
    h = Harness()
    address, source = h.string(), h.text(b"ab\0")
    seen = []

    def terminal(target, args, data):
        seen.append((target, args))
        if target == SCAN:
            h.memory.write(COPY_IAT, 8, STRING)
            return h.imported(SCAN, args, data)
        assert target == STRING and len(args) == 3
        return h.memory.move(*args)

    bound = bind_replay_unit_constructor_support(
        h.context, h.calls, bind_local=h.bind_local, imports=ReplayTaskRebuildCalls(terminal)
    )
    assert bound.call is not None
    bound.call(STRING, (address, source), None)
    assert [target for target, _ in seen] == [SCAN, STRING]
    assert h.memory.read_bytes(h.memory.read(address, 8), 3) == b"ab\0"


@pytest.mark.parametrize("phase", ["free", "scan", "copy"])
def test_string_import_failures_preserve_reached_effects_and_release_local(phase) -> None:
    h = Harness()
    old, source = h.block(8), h.text(b"abc\0")
    address = h.string(old, 7, 8)

    def fail(target, args):
        if target == {"free": FREE, "scan": SCAN, "copy": COPY}[phase]:
            raise RuntimeError(phase)

    h.on_import = fail
    with pytest.raises(RuntimeError, match=phase):
        h.invoke(STRING, address, source)
    assert h.active == 0
    if phase == "free":
        assert h.memory.read(address, 8) == old
        assert h.memory.read(address + 8, 8) == 7
    else:
        assert h.memory.read(address + 8, 8) == 0
        assert h.memory.read(address, 8) == (
            0x14428BB30 if phase == "scan" else h.memory.snapshot().regions[-1].address
        )


def test_real_literal_nul_source_does_not_touch_unavailable_bss_contents() -> None:
    h = Harness()
    h.memory.map_bytes(0x143676DC8, b"\0")
    address = h.string(0x14428BB30, 1, 0)
    h.invoke(STRING, address, 0x143676DC8)
    assert h.memory.read(address, 8) == 0x14428BB30
    assert not any(e[0] == "read" and e[1] == 0x14428BB30 for e in h.events)


def test_descriptor_getter_reads_only_current_qword8_and_keeps_raw_word() -> None:
    h = Harness()
    descriptor = h.memory.allocate(16)
    h.memory.write(descriptor + 8, 8, U64)
    assert read_replay_constructor_string_length(h.context, descriptor) == U64
    assert h.events == [("read", descriptor + 8, 8, U64)]


@pytest.mark.parametrize("nonnull", [False, True])
def test_moving_reset_exact_conditional_store_and_real_free(nonnull) -> None:
    h = Harness()
    address, old = h.block(0x3B0), h.block(8)
    h.memory.write(address + 0x388, 8, old if nonnull else 0)
    assert h.invoke(RESET, address) == 0
    writes = [e for e in h.events if e[0] == "write"]
    assert writes == ([("write", address + 0x388, 8, 0)] if nonnull else []) + [
        ("write", address + 0x394, 8, 0)
    ]
    assert h.memory.read_bytes(address + 0x390, 4) == b"\xa5" * 4
    assert h.memory.read_bytes(address + 0x39C, 20) == b"\xa5" * 20


def test_moving_null_read_hook_can_install_pointer_that_source_does_not_clear() -> None:
    h = Harness()
    address = h.block(0x3A0)
    h.memory.write(address + 0x388, 8, 0)

    def mutate(at, width, value):
        if at == address + 0x388:
            h.memory.write(at, 8, 0x1234)

    h.after_read = mutate
    reset_replay_unit_moving_buffer(h.context, address, calls=ReplayTaskRebuildCalls(None))
    assert h.memory.read(address + 0x388, 8) == 0x1234
    assert h.memory.read(address + 0x394, 8) == 0


def test_moving_free_failure_keeps_fields_and_actual_callback_effects() -> None:
    h = Harness()
    address = h.block(0x3A0)
    h.memory.write(address + 0x388, 8, 0xBAD)

    def fail(target, args, data):
        h.memory.write(address + 0x394, 8, 99)
        raise RuntimeError("free failed")

    with pytest.raises(RuntimeError, match="free failed"):
        reset_replay_unit_moving_buffer(h.context, address, calls=ReplayTaskRebuildCalls(fail))
    assert h.memory.read(address + 0x388, 8) == 0xBAD
    assert h.memory.read(address + 0x394, 8) == 99


def test_tree_wrapper_requires_actual_child_and_preserves_its_failure() -> None:
    h = Harness()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        clear_replay_unit_support_tree(h.context, 0x123, calls=ReplayTaskRebuildCalls(None))
    assert h.events == []
    h.invoke(0x14106A330, 0x456)
    assert h.events == [("call", 0x141071EC0, (0x456,), None)]


def test_registry_false_gate_never_reads_holder_and_global_is_read_once() -> None:
    h = Harness()
    h.memory.map_bytes(GLOBAL, bytes(8))
    h.invoke(0x140B2CFC0, 0xBAD)
    assert h.events == [("read", GLOBAL, 8, 0)]


def test_registry_separate_global_reread_current_holder_child_and_count_reread() -> None:
    h = Harness()
    first, current = h.block(0x4260), h.block(0x4260)
    holder = h.block(8)
    h.memory.write(holder, 8, 0x111)
    h.memory.map_bytes(GLOBAL, first.to_bytes(8, "little"))

    def mutate(at, width, value):
        if at == GLOBAL:
            h.memory.write(GLOBAL, 8, current)
            h.memory.write(holder, 8, 0x222)

    def child(target, args, data):
        assert target == 0x142392890 and args == (0x222,)
        h.memory.write(current + 0x4258, 8, 3)

    def after_write(at, width, value):
        if at == current + 0x4258:
            h.memory.write(at, 8, 5)

    h.after_read, h.after_write, h.on_call = mutate, after_write, child
    h.invoke(0x140B2CFC0, holder)
    assert h.memory.read(current + 0x258 + 5 * 8, 8) == 0x222
    assert h.memory.read(current + 0x4258, 8) == 5
    assert not any(e[0] == "write" and first <= e[1] < first + 0x4260 for e in h.events)


def test_registry_token_zero_has_no_access_and_zero_count_underflows_before_index() -> None:
    h = Harness()
    return_replay_unit_support_token(h.context, 0, 0, calls=ReplayTaskRebuildCalls(None))
    assert h.events == []
    address = h.block(0x4260)
    h.memory.write(address + 0x4258, 8, 0)
    return_replay_unit_support_token(h.context, address, 0xABC, calls=h.calls)
    assert h.memory.read(address + 0x4258, 8) == U64
    assert h.memory.read(address + 0x250, 8) == 0xABC


def test_registry_missing_child_stops_before_any_count_access() -> None:
    h = Harness()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        return_replay_unit_support_token(h.context, 0xBAD, 1, calls=ReplayTaskRebuildCalls(None))
    assert h.events == []


@pytest.mark.parametrize(
    "target,args",
    [
        (HEADER, ()),
        (STRING, (1,)),
        (GROW, (1, 2, 3)),
        (RESET, ()),
        (0x140A13780, (True,)),
        (0x140B2BE40, (1, 2)),
        (0x140B2BD90, (1,)),
        (0x142D6E3B1, (1, 2)),
        (0x142D6C270, (-1,)),
    ],
)
def test_known_bound_arity_and_raw_arguments_refuse_before_any_access(target, args) -> None:
    h = Harness()
    with pytest.raises(ValueError):
        h.invoke(target, *args)
    assert h.events == []


def test_known_data_rejected_unknown_live_view_and_return_are_unchanged() -> None:
    h = Harness()
    assert h.bound.call is not None
    view = memoryview(bytearray(b"abc"))
    with pytest.raises(ValueError):
        h.bound.call(HEADER, (1, 2), view)

    def child(target, args, data):
        assert target == 0xABC and args == (U64,) and data is view
        data[0] = 0xEE
        return U64

    h.on_call = child
    assert h.bound.call(0xABC, (U64,), view) == U64
    assert view.tobytes() == b"\xeebc"


def test_missing_current_import_target_stops_after_its_real_iat_read() -> None:
    h = Harness()
    bound = bind_replay_unit_constructor_support(
        h.context, ReplayTaskRebuildCalls(None), bind_local=h.bind_local
    )
    assert bound.call is not None
    with pytest.raises(UnresolvedReplayTaskRebuild):
        bound.call(0x142D6E44D, (1,), None)
    assert h.events == [("read", LENGTH_IAT, 8, SCAN)]


@pytest.mark.parametrize("target", [0x142D6C270, 0x142D6C90C, 0x142D6E47D])
def test_free_chain_current_iat_is_terminal_even_when_target_is_owned(target) -> None:
    h = Harness()
    h.memory.write(FREE_IAT, 8, HEADER)
    received = []

    def terminal(actual, args, data):
        received.append((actual, args, data))

    bound = bind_replay_unit_constructor_support(
        h.context, h.calls, bind_local=h.bind_local, imports=ReplayTaskRebuildCalls(terminal)
    )
    assert bound.call is not None
    bound.call(target, (0xBAD,), None)
    assert h.events == [("read", FREE_IAT, 8, HEADER)]
    assert received == [(HEADER, (0xBAD,), None)]


def test_direct_notify_low_al_gate_and_current_holder_after_getter_callback() -> None:
    h = Harness()
    holder = h.block(8)

    def child(target, args, data):
        if target == 0x140B2BE40:
            assert args == (holder,)
            return 0x80
        if target == 0x140B2BD90:
            assert args == ()
            h.memory.write(holder, 8, 0x321)
            return 0x123
        assert target == 0x140B24580 and args == (0x123, 0x321)
        return None

    notify_replay_unit_support_registry(h.context, holder, calls=ReplayTaskRebuildCalls(child))
