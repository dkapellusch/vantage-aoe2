"""Source-led mode initializer controls over explicit owned storage/capabilities."""

from __future__ import annotations

import io
from contextlib import contextmanager

import pytest

from vantage.replay_file_backend import (
    ReplayFileBackendProfile,
    bind_replay_file_backend_homes,
)
from vantage.replay_file_mode_init import (
    ReplayFileModeInitProfile,
    bind_replay_file_mode_init,
)
from vantage.replay_file_support import ReplayFileSupportProfile, bind_replay_file_support
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

MODE, SIZE, BACKEND, CTOR = 0x140916040, 0x14178AE20, 0x14093A930, 0x140A08840
CALLOC_IAT, MALLOC_IAT, ERROR_IAT = 0x143199DC0, 0x143199DB0, 0x143198A88
CALLOC, MALLOC, ERROR = 0xFA11, 0xFA12, 0xFA13
U64 = (1 << 64) - 1


class Rig:
    def __init__(self):
        self.memory = ReplayMemory()
        self.file, self.output = self.memory.allocate(0xB0), self.memory.allocate(48)
        self.memory.write_bytes(self.file, b"F" * 0xB0)
        self.memory.write_bytes(self.output, b"O" * 48)
        for offset, width, value in (
            (0x80, 4, 0),
            (0x98, 8, 4),
            (0x30, 8, 16),
            (0x40, 8, 2),
            (0x28, 8, 7),
        ):
            self.memory.write(self.file + offset, width, value)
        for address, target in ((CALLOC_IAT, CALLOC), (MALLOC_IAT, MALLOC), (ERROR_IAT, ERROR)):
            self.memory.map_bytes(address, target.to_bytes(8, "little"))
        self.events, self.locals, self.frames, self.active = [], [], [], []
        self.after_read, self.after_write = None, None
        self.profile = ReplayFileModeInitProfile(bytes(range(0x40)))
        self.actual, self.backend_raw, self.error_raw = 4, 1, 0x1122334455667788
        self.constructor_observations = []
        self.import_handlers = {
            CALLOC: lambda args: self.memory.calloc(*args),
            MALLOC: lambda args: self.memory.allocate(*args),
            ERROR: lambda args: self.error_raw,
        }
        self.body_handlers = {BACKEND: self.backend}
        self.variadic_handlers = {CTOR: self.construct}

        def read(address, width):
            self.events.append(("read", address, width))
            value = self.memory.read(address, width)
            if self.after_read is not None:
                self.after_read(address, width)
            return value

        def write(address, width, value):
            self.events.append(("write", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write is not None:
                self.after_write(address, width, value)

        self.storage = ReplayTaskRebuildStorage(self.file, read, write)
        self.ordinary = self.channel("body", self.body_handlers)
        self.imports = self.channel("import", self.import_handlers)
        self.variadic = self.channel("variadic", self.variadic_handlers)
        self.bind()

    def channel(self, name, handlers):
        def dispatch(target, args, data):
            assert data is None
            self.events.append((name, target, args))
            if target not in handlers:
                raise UnresolvedReplayTaskRebuild(f"missing {name} capability{target:x}")
            return handlers[target](args)

        return ReplayTaskRebuildCalls(dispatch)

    def bind(self, *, calls=None, imports=None, variadic=None):
        self.bound = bind_replay_file_mode_init(
            self.storage,
            self.ordinary if calls is None else calls,
            imports=self.imports if imports is None else imports,
            variadic_calls=self.variadic if variadic is None else variadic,
            bind_local=self.bind_local,
            profile=self.profile,
        )

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.locals.append((address, len(view), bytes(view)))
            self.active.append(address)
            self.events.append(("map", address, len(view)))
            try:
                yield address
            finally:
                self.frames.append(bytes(view))
                self.events.append(("unmap", address, len(view)))
                self.active.pop()

    def backend(self, args):
        assert len(args) == 4
        self.memory.write(args[3], 8, self.actual)
        return self.backend_raw

    def construct(self, args):
        assert len(args) == 6 and args[0] == self.output
        self.constructor_observations.append(
            (args, self.memory.read(args[4], 8), self.memory.read(args[5], 8))
        )
        # Explicit observation fixture: no invented successful Result output.
        return 0xDEADBEEF

    def invoke(self):
        return self.bound.call(MODE, (self.file, self.output), None)

    def field(self, offset, width=8):
        return self.memory.read(self.file + offset, width)

    def set_field(self, offset, value, width=8):
        self.memory.write(self.file + offset, width, value)

    def calls_to(self, target):
        return [
            e[2]
            for e in self.events
            if e[0] in ("body", "import", "variadic", "os") and e[1] == target
        ]

    def writes(self):
        return [e[1:] for e in self.events if e[0] == "write"]

    def assert_expired(self):
        assert not self.active
        for address, _, _ in self.locals:
            with pytest.raises(ReplayMemoryError, match="unmapped"):
                self.memory.read(address, 1)


@pytest.mark.parametrize("args", [(), (0,), (U64,)])
def test_actual_size_leaf_has_no_storage_or_child_effects(args):
    r = Rig()
    assert r.bound.call(SIZE, args, None) == 0xA0C8
    assert r.events == []


@pytest.mark.parametrize("mode", [0, 1])
def test_success_allocates_and_publishes_exact_fields_and_41_output_bytes(mode):
    r = Rig()
    r.set_field(0x80, mode, 4)
    old_error = r.field(0x4C, 4)
    assert r.invoke() == r.output
    frame, size, seed = r.locals[0]
    assert (size, seed) == (0x40, bytes(range(0x40)))
    assert r.events[:3] == [
        ("map", frame, 0x40),
        ("write", frame + 0x38, 8, r.output),
        ("read", r.file + 0x80, 4),
    ]
    assert r.calls_to(CALLOC) == [(0xA0C8, 1)]
    assert r.calls_to(MALLOC) == [(4,)]
    assert r.memory.read_bytes(r.field(0x88), 0xA0C8) == b"\0" * 0xA0C8
    with pytest.raises(ReplayMemoryError, match="undefined"):
        r.memory.read(r.field(0x90), 1)
    assert r.calls_to(BACKEND) == [(7, r.field(0x90), 4, frame + 0x38)]
    assert (r.field(0x40), r.field(0x80, 4), r.field(0x48, 4), r.field(0xA0)) == (6, 2, 0, 0)
    assert r.field(0x4C, 4) == old_error
    assert r.memory.read_bytes(r.output, 48) == b"\0" * 41 + b"O" * 7
    writes = r.writes()
    assert writes[-9:] == [
        (r.file + 0xA0, 8, 0),
        (r.file + 0x80, 4, 2),
        (r.file + 0x48, 4, 0),
        *((r.output + offset, 8, 0) for offset in (0, 8, 16, 24, 32)),
        (r.output + 40, 1, 0),
    ]
    assert not r.calls_to(CTOR) and not r.calls_to(ERROR)
    r.assert_expired()


@pytest.mark.parametrize("mode", [2, 3, 0xFFFFFFFF])
def test_invalid_mode_direct_constructor_preserves_code_home_and_file(mode):
    r = Rig()
    r.set_field(0x80, mode, 4)
    before = r.memory.read_bytes(r.file, 0xA8)
    assert r.invoke() == r.output
    frame = r.locals[0][0]
    assert r.writes() == [(frame + 0x38, 8, r.output), (frame + 0x20, 8, 0x1431F7B80)]
    assert r.constructor_observations == [
        (
            (r.output, 0, 0x1431F7B10, 0x1FE, frame + 0x20, frame + 0x28),
            0x1431F7B80,
            int.from_bytes(bytes(range(0x28, 0x30)), "little"),
        )
    ]
    assert r.memory.read_bytes(r.file, 0xA8) == before
    assert r.memory.read_bytes(r.output, 48) == b"O" * 48
    assert not r.calls_to(CALLOC)
    r.assert_expired()


@pytest.mark.parametrize("mode", [1, 2])
def test_entry_output_home_store_precedes_current_mode_read(mode):
    r = Rig()

    def change(address, width, value):
        if r.active and (address, width) == (r.active[0] + 0x38, 8) and value == r.output:
            r.set_field(0x80, mode, 4)

    r.after_write = change
    assert r.invoke() == r.output
    assert bool(r.calls_to(CALLOC)) == (mode == 1)
    assert bool(r.calls_to(CTOR)) == (mode == 2)


def test_held_nonzero_length_survives_state_publication_but_expected_is_fresh():
    r = Rig()

    def change(address, width, value):
        if address == r.file + 0x88:
            r.set_field(0x98, 8)

    r.after_write = change
    r.actual = 8
    r.invoke()
    assert r.calls_to(MALLOC) == [(4,)]
    assert r.calls_to(BACKEND)[0][2] == 8
    assert r.field(0x40) == 10 and r.field(0x80, 4) == 2


def test_zero_held_length_uses_fresh_fields_and_holds_computed_subtraction():
    r = Rig()
    r.set_field(0x98, 0)

    def change(address, width, value):
        if address == r.file + 0x88:
            r.set_field(0x30, 32)
            r.set_field(0x40, 4)
            r.set_field(0x98, 99)
        elif address == r.file + 0x98:
            r.set_field(0x98, 7)

    r.after_write = change
    r.actual = 7
    r.invoke()
    assert (r.file + 0x98, 8, 28) in r.writes()
    assert r.calls_to(MALLOC) == [(28,)]
    assert r.calls_to(BACKEND)[0][2] == 7
    assert r.field(0x40) == 11 and r.field(0x80, 4) == 2


@pytest.mark.parametrize(
    "position,length,remaining,actual,expected_position",
    [
        (U64 - 2, U64, 4, 4, 1),
        (9, 3, 0, 0, 9),
        (16, 16, 0, 0, 16),
    ],
)
def test_unsigned_wrapping_bounds_and_zero_length_keep_actual_calls(
    position,
    length,
    remaining,
    actual,
    expected_position,
):
    r = Rig()
    r.set_field(0x40, position)
    r.set_field(0x30, length)
    r.set_field(0x98, remaining)
    # Underflow is admitted by wrapped bounds, but its huge malloc remains an
    # explicit fixture capability rather than an actual owned huge allocation.
    r.import_handlers[MALLOC] = lambda args: 0
    r.actual = actual
    if position == 9:
        # Current lowDWORD expected is fffffffa; short count reaches error25.
        r.backend_raw = 0
    r.invoke()
    assert r.calls_to(MALLOC) == [(remaining if remaining else (length - position) & U64,)]
    assert r.calls_to(BACKEND)[0][1] == 0
    assert r.field(0x40) == expected_position
    if position == 16:
        assert r.field(0x80, 4) == 2 and r.calls_to(BACKEND)[0][2] == 0


def test_bounds_error_home_order_partial_code_and_no_malloc_or_backend():
    r = Rig()
    r.set_field(0x98, 20)
    r.invoke()
    frame = r.locals[0][0]
    assert r.writes()[2:] == [
        (frame + 0x28, 4, 0x24),
        (frame + 0x20, 8, 0x1431F7B68),
        (r.file + 0x80, 4, 0),
        (r.file + 0x48, 4, 0x24),
        (r.file + 0x4C, 4, 0x24),
    ]
    args, fmt, code = r.constructor_observations[0]
    assert args == (r.output, 0, 0x1431F7B10, 0xD7, frame + 0x20, frame + 0x28)
    expected_code = int.from_bytes(b"\x24\0\0\0" + bytes(range(0x2C, 0x30)), "little")
    assert (fmt, code) == (0x1431F7B68, expected_code)
    assert not r.calls_to(MALLOC) and not r.calls_to(BACKEND) and not r.calls_to(ERROR)
    assert r.memory.read_bytes(r.output, 48) == b"O" * 48
    r.assert_expired()


def test_malloc_effects_are_sampled_before_buffer_publication_then_held():
    r = Rig()
    allocated = r.memory.allocate(4)

    def malloc(args):
        r.set_field(0x98, (9 << 32) | 3)
        r.set_field(0x28, 9)
        return allocated

    def change(address, width, value):
        if address == r.file + 0x90:
            r.set_field(0x98, 17)
            r.set_field(0x28, 19)
            r.set_field(0x90, 0)

    r.import_handlers[MALLOC], r.after_write, r.actual = malloc, change, 3
    r.invoke()
    assert r.calls_to(MALLOC) == [(4,)]
    assert r.calls_to(BACKEND)[0][:3] == (9, allocated, 3)
    assert r.field(0x90) == 0 and r.field(0x80, 4) == 2


@pytest.mark.parametrize(
    "raw,success",
    [(1, True), (0x101, True), (U64, True), (0, False), (0x100, False), (1 << 32, False)],
)
def test_backend_al_and_low_count_decide_after_current_cursor_publication(raw, success):
    r = Rig()
    r.backend_raw, r.actual = raw, (0xABCDEF << 32) | 4

    def backend(args):
        r.set_field(0x40, 100)
        return r.backend(args)

    def change(address, width, value):
        if address == r.file + 0x40:
            r.set_field(0x98, 99)
            r.memory.write(r.active[0] + 0x38, 8, 1)

    r.body_handlers[BACKEND], r.after_write = backend, change
    r.invoke()
    assert r.field(0x40) == 104
    assert (r.field(0x80, 4) == 2) == success
    assert bool(r.calls_to(CTOR)) != success


def test_failure_selects_current_last_error_after_file_stores_and_orders_homes():
    r = Rig()
    r.actual = 3
    other_error = ERROR + 1
    r.import_handlers[other_error] = lambda args: r.error_raw

    def change(address, width, value):
        if (address, value) == (r.file + 0x4C, 0x25):
            r.memory.write(ERROR_IAT, 8, other_error)

    r.after_write = change
    assert r.invoke() == r.output
    frame = r.locals[0][0]
    assert r.writes()[-6:] == [
        (r.file + 0x80, 4, 0),
        (r.file + 0x48, 4, 0x25),
        (r.file + 0x4C, 4, 0x25),
        (frame + 0x28, 4, 0x25),
        (r.file + 0x50, 4, 0x55667788),
        (frame + 0x20, 8, 0x1431F7B68),
    ]
    assert r.calls_to(ERROR) == [] and r.calls_to(other_error) == [()]
    args, fmt, code = r.constructor_observations[0]
    assert args == (r.output, 0, 0x1431F7B10, 0xD7, frame + 0x20, frame + 0x28)
    assert fmt == 0x1431F7B68 and code & 0xFFFFFFFF == 0x25
    assert code >> 32 == int.from_bytes(bytes(range(0x2C, 0x30)), "little")
    assert r.field(0x50) == 0x4646464655667788
    r.assert_expired()


@pytest.mark.parametrize("allocator", [CALLOC, MALLOC])
def test_null_allocations_are_published_without_invented_failure(allocator):
    r = Rig()
    r.import_handlers[allocator] = lambda args: 0
    r.invoke()
    assert r.field(0x88 if allocator == CALLOC else 0x90) == 0
    assert r.field(0x80, 4) == 2
    assert r.calls_to(BACKEND)


@pytest.mark.parametrize("raw", [None, -1, U64 + 1, True])
@pytest.mark.parametrize("target", [CALLOC, MALLOC, BACKEND, ERROR])
def test_raw_returns_refuse_only_at_first_source_consumption(target, raw):
    r = Rig()
    if target in (CALLOC, MALLOC, ERROR):
        r.import_handlers[target] = lambda args: raw
    else:

        def backend(args):
            r.backend(args)
            return raw

        r.body_handlers[target] = backend
    if target == ERROR:
        r.backend_raw = 0
    with pytest.raises(ValueError):
        r.invoke()
    frame = r.locals[0][0]
    index = next(
        i
        for i, event in enumerate(r.events)
        if event[0] in ("body", "import") and event[1] == target
    )
    following = r.events[index + 1 :]
    if target == CALLOC:
        assert following[:1] == [("read", r.file + 0x98, 8)]
        assert not any(w[0] == r.file + 0x88 for w in r.writes())
    elif target == MALLOC:
        assert following[:2] == [("read", r.file + 0x98, 4), ("read", r.file + 0x28, 8)]
        assert not any(w[0] == r.file + 0x90 for w in r.writes())
    elif target == BACKEND:
        assert following[:3] == [
            ("read", frame + 0x38, 8),
            ("read", r.file + 0x40, 8),
            ("write", r.file + 0x40, 8, 6),
        ]
        assert r.field(0x40) == 6 and not r.calls_to(ERROR)
    else:
        assert following[:1] == [("write", frame + 0x28, 4, 0x25)]
        assert not any(w[0] == r.file + 0x50 for w in r.writes())
        assert not any(w[0] == frame + 0x20 for w in r.writes())
    r.assert_expired()


@pytest.mark.parametrize("missing", [CALLOC, MALLOC, BACKEND, ERROR, CTOR])
def test_missing_capabilities_refuse_at_reach_without_fabricated_output(missing):
    r = Rig()
    if missing in r.import_handlers:
        del r.import_handlers[missing]
    elif missing == BACKEND:
        del r.body_handlers[missing]
    else:
        del r.variadic_handlers[missing]
    if missing in (ERROR, CTOR):
        r.backend_raw = 0
    with pytest.raises(UnresolvedReplayTaskRebuild, match="missing"):
        r.invoke()
    assert r.calls_to(missing)
    assert r.memory.read_bytes(r.output, 48) == b"O" * 48
    r.assert_expired()


@pytest.mark.parametrize(
    "target,args,data",
    [
        (MODE, (), None),
        (MODE, (0,), None),
        (MODE, (0, 0, 0), None),
        (MODE, (0, 0), memoryview(b"x")),
        (SIZE, (0, 0), None),
        (SIZE, (), memoryview(b"x")),
        (MODE, (-1, 0), None),
        (SIZE, (True,), None),
    ],
)
def test_malformed_owned_calls_refuse_before_local_binding(target, args, data):
    r = Rig()
    with pytest.raises(ValueError):
        r.bound.call(target, args, data)
    assert r.events == []


def test_unknown_target_preserves_original_args_and_data_or_refuses():
    r = Rig()
    token, view, seen = object(), memoryview(b"x"), []

    def dispatch(target, args, data):
        seen.append((target, args, data))
        return 47

    r.bind(calls=ReplayTaskRebuildCalls(dispatch))
    original_args = (token,)
    assert r.bound.call(0xABCD, original_args, view) == 47
    assert seen == [(0xABCD, (token,), view)] and not r.events
    assert seen[0][1] is original_args and seen[0][2] is view
    r.bind(calls=ReplayTaskRebuildCalls(None))
    with pytest.raises(UnresolvedReplayTaskRebuild):
        r.bound.call(0xABCD, (), None)


@pytest.mark.parametrize("frame", [b"", b"F" * 63, b"F" * 65, bytearray(64), None])
def test_profile_requires_exact_explicit_immutable_seed(frame):
    with pytest.raises(ValueError, match="seed"):
        ReplayFileModeInitProfile(frame)


def test_output_aliases_file_without_reordering_success_publications():
    r = Rig()
    r.output = r.file + 0x80
    r.invoke()
    assert r.field(0x40) == 6
    assert r.memory.read_bytes(r.output, 41) == b"\0" * 41
    # The held output overwrites mode/state/buffer/remaining/A0 only after their
    # source publications; no post-output mode repair is added by the caller.
    assert r.field(0x80, 4) == 0 and r.field(0x88) == 0 and r.field(0x90) == 0
    assert r.writes()[-6:] == [
        *((r.output + off, 8, 0) for off in (0, 8, 16, 24, 32)),
        (r.output + 40, 1, 0),
    ]


def test_composed_mode_support_backend_reads_real_owned_stream_into_allocated_buffer():
    r = Rig()
    stream = io.BytesIO(b"abcdefghijklmnop")
    stream.seek(2)
    service, vptr = r.memory.allocate(8), r.memory.allocate(0x48)
    r.memory.write(service, 8, vptr)
    r.memory.write(vptr + 0x38, 8, 0x141756EA0)
    r.memory.map_bytes(0x144281D30, service.to_bytes(8, "little"))
    r.memory.map_bytes(0x143198988, (0xFA14).to_bytes(8, "little"))

    def os_read(target, args, data):
        assert (target, len(args), data) == (0xFA14, 5, None)
        handle, destination, count, actual, overlapped = args
        assert (handle, overlapped) == (7, 0)
        payload = stream.read(count)
        r.memory.write_bytes(destination, payload)
        r.memory.write(actual, 4, len(payload))
        r.events.append(("os", target, args))
        return 0x100  # Real caller tests full EAX; backend changes only AL.

    strict = ReplayTaskRebuildCalls(None)
    backend = bind_replay_file_backend_homes(
        r.storage,
        strict,
        os_calls=ReplayTaskRebuildCalls(os_read),
        bind_local=r.bind_local,
        profile=ReplayFileBackendProfile(b"R" * 0x38, b"S" * 0x28),
    )
    support = bind_replay_file_support(
        r.storage,
        strict,
        variadic_calls=ReplayTaskRebuildCalls(None),
        atomics=ReplayUnitAIMapAtomics(None, None),
        bind_local=r.bind_local,
        profile=ReplayFileSupportProfile(b"P" * 0x68, b"W" * 0x28, None),
        backend_home_calls=backend,
    )
    r.bind(calls=support)
    assert r.invoke() == r.output
    assert r.memory.read_bytes(r.field(0x90), 4) == b"cdef"
    assert r.field(0x40) == stream.tell() == 6 and r.field(0x80, 4) == 2
    assert [size for _, size, _ in r.locals] == [0x40, 0x28, 0x38]
    assert not r.calls_to(CTOR)
    r.assert_expired()
