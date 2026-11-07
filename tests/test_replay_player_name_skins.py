"""Authored scalar/local caller controls; no native or Memory oracle."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from vantage.replay_player_name_skins import (
    ReplayPlayerNameSkinsScratch,
    bind_replay_player_name_skins,
)
from vantage.replay_player_name_skins_storage import bind_replay_player_name_skins_storage
from vantage.replay_player_name_validation import bind_replay_player_name_validation
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

U64 = (1 << 64) - 1
IO, FREE, COPY, FILL, STRLEN, WATSON, WATSON2 = range(0xA11001, 0xA11008)


class ScalarBytes:
    """Small initialized byte carrier, explicit scoped views and actual writes."""

    def __init__(self):
        self.next = 0x100000
        self.regions = {}
        self.events = []
        self.locals = []
        self.exited = []
        self.read_hook = None
        self.write_hook = None

    def allocate(self, size, seed=0):
        if size > 1 << 20:
            raise UnresolvedReplayTaskRebuild("authored allocation budget reached")
        address = self.next
        self.next += max(size, 1) + 0x100
        self.regions[address] = bytearray([seed]) * max(size, 1)
        return address

    def map(self, address, data):
        assert address not in self.regions
        self.regions[address] = bytearray(data)

    def region(self, address, width):
        for base, data in self.regions.items():
            if base <= address and address + width <= base + len(data):
                return data, address - base
        raise KeyError((address, width))

    def read(self, address, width):
        data, offset = self.region(address, width)
        value = int.from_bytes(data[offset : offset + width], "little")
        self.events.append(("read", address, width, value))
        if self.read_hook:
            self.read_hook(address, width, value)
        return value

    def write(self, address, width, value):
        data, offset = self.region(address, width)
        data[offset : offset + width] = (value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")
        self.events.append(("write", address, width, value))
        if self.write_hook:
            self.write_hook(address, width, value)

    @contextmanager
    def bind_local(self, view):
        address = self.allocate(len(view))
        self.regions[address] = view
        self.locals.append((address, len(view)))
        try:
            yield address
        finally:
            self.exited.append((address, bytes(view)))
            del self.regions[address]

    def fetch_add(self, address, value):
        old = self.read(address, 4)
        self.write(address, 4, old + value)
        return old

    def cas(self, address, expected, desired):
        old = self.read(address, 4)
        if old == expected:
            self.write(address, 4, desired)
        return old


class Environment:
    def __init__(self, payload=b""):
        self.memory = ScalarBytes()
        self.object = self.memory.allocate(32)
        self.output = self.memory.allocate(48, 0xA5)
        self.stream = self.memory.allocate(8)
        self.table = self.memory.allocate(32)
        self.memory.write(self.stream, 8, self.table)
        self.memory.write(self.table + 24, 8, IO)
        self.memory.map(0x14428BB30, b"\0")
        for slot, target in (
            (0x143199DD0, FREE),
            (0x143199930, COPY),
            (0x143199938, FILL),
            (0x14319A290, STRLEN),
            (0x14319A060, WATSON),
        ):
            self.memory.map(slot, target.to_bytes(8, "little"))
        self.context = ReplayTaskRebuildStorage(self.object, self.memory.read, self.memory.write)
        self.atomics = ReplayUnitAIMapAtomics(self.memory.cas, self.memory.fetch_add)
        self.routes = {}
        self.trace = []
        self.after_call = None
        self.overrides = {}
        self.calls = ReplayTaskRebuildCalls(self.dispatch)
        self.imports = ReplayTaskRebuildCalls(self.runtime)
        self.source = ReplaySavedInput(payload)
        self.register(
            bind_replay_saved_input(
                self.context,
                self.calls,
                self.source,
                stream=self.stream,
                target=IO,
                result_bytes=bytes(48),
            ),
            (IO,),
        )
        self.register(
            bind_replay_saved_pair(self.context, self.calls, atomics=self.atomics), (0x14090D270,)
        )
        self.register(
            bind_replay_saved_apply(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
            (0x1409076B0, 0x1402B9080),
        )
        self.register(
            bind_replay_saved_result(
                self.context, self.calls, atomics=self.atomics, imports=self.imports
            ),
            (0x1402BD7F0, 0x1402BD890),
        )
        self.register(
            bind_replay_saved_string(self.context, self.calls, imports=self.imports),
            (0x1402A8920, 0x1402A88A0, 0x142D6BAB4),
        )
        self.register(
            bind_replay_unit_constructor_support(
                self.context, self.calls, bind_local=self.memory.bind_local, imports=self.imports
            ),
            (0x140A13780, 0x140A1A5E0, 0x142D6C268, 0x142D6C270, 0x142D6E3B1, 0x142D6E44D),
        )
        self.register(
            bind_replay_player_name_validation(
                self.context, self.calls, bind_local=self.memory.bind_local, scratch=bytes(0x44)
            ),
            (0x140A84390, 0x140A830B0),
        )
        self.register(
            bind_replay_player_name_skins_storage(self.context, self.calls, imports=self.imports),
            (0x1402BB300, 0x1402BA970, 0x1402A8840),
        )
        self.bound = bind_replay_player_name_skins(
            self.context,
            self.calls,
            atomics=self.atomics,
            bind_local=self.memory.bind_local,
            scratch=ReplayPlayerNameSkinsScratch(
                *(bytes([0xA5]) * n for n in (0xE8, 0xA0, 0x60, 0xB8))
            ),
            imports=self.imports,
        )
        self.register(self.bound, (0x140A1D990, 0x140A150F0, 0x140A09540, 0x140E33410))

    def register(self, calls, targets):
        for target in targets:
            assert target not in self.routes
            self.routes[target] = calls.call

    def dispatch(self, target, args, data):
        self.trace.append((target, args))
        if target in self.overrides:
            result = self.overrides[target](args)
        elif target in self.routes:
            result = self.routes[target](target, args, data)
        else:
            result = self.runtime(target, args, data)
        if self.after_call:
            self.after_call(target, args)
        return result

    def runtime(self, target, args, data):
        assert data is None
        if target in (0x1402A94D0, 0x142D6BA78):
            return self.memory.allocate(args[0])
        if target in (0x142D6E3B1, 0x142D6E3DB, COPY):
            destination, source, size = args
            if size:
                word = self.memory.read(source, size)
                self.memory.write(destination, size, word)
            return destination
        if target in (0x142D6E3B7, FILL):
            destination, value, size = args
            if size:
                self.memory.write(destination, size, int.from_bytes(bytes([value & 255]) * size))
            return destination
        if target == FREE:
            if args[0]:
                del self.memory.regions[args[0]]
            return None
        if target == STRLEN:
            count = 0
            while self.memory.read(args[0] + count, 1):
                count += 1
            return count
        if target in (WATSON, WATSON2):
            self.trace.append((target, args))
            return None
        raise UnresolvedReplayTaskRebuild(f"authored reached{target:x} unavailable")

    def call(self, target, *args):
        return self.calls.call(target, args, None)

    def word(self, address, value, width=8):
        self.memory.write(address, width, value)

    def bytes(self, address, size):
        return self.memory.read(address, size).to_bytes(size, "little")

    def successful_output(self):
        assert self.bytes(self.output, 48) == bytes(41) + bytes([0xA5]) * 7

    def name(self):
        return self.call(0x140A1D990, self.object, self.output, self.stream)

    def skin_header(self, capacity=0):
        header = self.memory.allocate(24)
        if capacity:
            data = self.memory.allocate(capacity * 8)
            self.word(header, data)
            self.word(header + 8, data + capacity * 8)
            self.word(header + 16, data + capacity * 8)
        return header


@pytest.mark.parametrize(
    "value", [b"", b"A", b"Gaia", b"x" * 15, b"x" * 16, b"x" * 31, b"\xc0\x80", b"\xed\xa0\x80"]
)
def test_complete_name_uses_real_bytes_predicate_growth_cleanup(value):
    env = Environment((len(value) + 1).to_bytes(2, "little") + value + b"\0")
    assert env.name() == env.output
    length = env.memory.read(env.object + 8, 8)
    assert length == len(value)
    if value:
        assert env.bytes(env.memory.read(env.object, 8), length + 1) == value + b"\0"
    env.successful_output()
    assert env.source.remaining == 0
    assert not env.memory.locals or all(a not in env.memory.regions for a, _ in env.memory.locals)
    assert any(t == 0x1402A8920 for t, _ in env.trace)


@pytest.mark.parametrize("length", [0, -1, -32768])
def test_name_invalid_signed_word_refuses_after_actual_result_cleanup(length):
    env = Environment(length.to_bytes(2, "little", signed=True))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140a1dc59"):
        env.name()
    assert env.source.position == 2
    assert not any(t == 0x140A150F0 for t, _ in env.trace)
    assert [t for t, _ in env.trace].count(0x1402BD890) == 2


def test_name_truncated_payload_preserves_prefix_and_prior_byte_reads():
    env = Environment(b"\x05\0ab")
    with pytest.raises(UnresolvedReplayTaskRebuild, match="exact span"):
        env.name()
    assert env.source.position == 4
    assert len([1 for t, _ in env.trace if t == IO]) == 4
    assert not any(t == 0x140A09540 for t, _ in env.trace)


@pytest.mark.parametrize(
    "initial_pointer,capacity,freed",
    [(False, 0, False), (False, 4, False), (True, 0, False), (True, 4, True)],
)
def test_name_initial_free_capacity_then_pointer(initial_pointer, capacity, freed):
    env = Environment(b"\0\0")
    pointer = env.memory.allocate(4) if initial_pointer else 0
    env.word(env.object, pointer)
    env.word(env.object + 16, capacity)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        env.name()
    assert (pointer not in env.memory.regions) == freed if pointer else not freed
    if freed:
        assert env.memory.read(env.object, 8) == 0x14428BB30


@pytest.mark.parametrize("value", [b"", b"abc", b"a\0z"])
def test_byte_loop_reads_exact_span_including_nul(value):
    env = Environment(value)
    buffer = env.memory.allocate(max(1, len(value)), 0x55)
    assert (
        env.call(0x140A150F0, env.output, 7, U64, 9, env.stream, buffer, len(value)) == env.output
    )
    assert env.bytes(buffer, len(value)) == value
    assert [a[3] for t, a in env.trace if t == IO] == [1] * len(value)
    env.successful_output()


def test_byte_oversize_refuses_before_input_or_result_initialization():
    env = Environment()
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140a15151"):
        env.call(0x140A150F0, env.output, 0, 0, 0, env.stream, 0, 0xA00001)
    assert env.bytes(env.output, 48) == bytes([0xA5]) * 48
    assert not any(t == IO for t, _ in env.trace)


def test_name_conditional_move_memory_operand_read_even_for_inline_buffer():
    env = Environment(b"\x02\0a\0")
    env.name()
    name_frame = next(a for a, size in env.memory.locals if size == 0xE8)
    reads = [(a, w) for kind, a, w, _ in env.memory.events if kind == "read"]
    assert reads.count((name_frame + 0x98, 8)) >= 2


def test_name_rereads_required_word_after_growth_callback():
    env = Environment(b"\x11\0abc\0")

    def after(target, _args):
        if target == 0x1402BB300:
            frame = next(a for a, size in env.memory.locals if size == 0xE8)
            env.word(frame + 0x64, 4, 2)

    env.after_call = after
    env.name()
    assert [args[3] for target, args in env.trace if target == IO] == [2, 1, 1, 1, 1]
    assert env.memory.read(env.object + 8, 8) == 3


def test_name_getter_and_copy_destination_are_current_but_source_length_held():
    env = Environment(b"\x04\0abc\0")
    replacement = env.memory.allocate(8)

    def after(target, args):
        if target == 0x142D6E3B1:
            env.word(env.object, replacement)

    def written(address, width, value):
        frame = next((a for a, size in env.memory.locals if size == 0xE8), None)
        if frame and address == frame + 0x50 and width == 8 and value == 3:
            env.word(address, 2)

    env.after_call = after
    env.memory.write_hook = written
    env.name()
    assert env.memory.read(env.object + 8, 8) == 2
    assert env.bytes(replacement, 3) == b"\0\0\0"


def test_actual_predicate_invalid_sequence_requires_registry_not_ascii_shortcut():
    env = Environment(b"\x02\0\x80\0")
    with pytest.raises(KeyError, match=str(0x14428B910)):
        env.name()
    assert any(t == 0x140A84390 for t, _ in env.trace)


def prepare_repair(value=b"\x80\0", codes=(1,)):
    env = Environment()
    env.word(env.object, int.from_bytes(value, "little"), len(value))
    env.word(env.object + 16, len(value) - 1)
    env.word(env.object + 24, 15)
    registry = env.memory.allocate(max(4, len(codes) * 4))
    for index, code in enumerate(codes):
        env.word(registry + 4 * index, code, 4)
    env.memory.map(0x14428B910, registry.to_bytes(8, "little"))
    env.memory.map(0x14428B918, (registry + len(codes) * 4).to_bytes(8, "little"))
    return env, registry


def conversion(env, value, accepted=1):
    def convert(args):
        _code, _source, temporary = args
        if accepted:
            if len(value) > 15:
                pointer = env.memory.allocate(len(value) + 1)
                env.word(temporary, pointer)
                env.word(temporary + 24, len(value))
            else:
                pointer = temporary
            env.memory.write(pointer, len(value) + 1, int.from_bytes(value + b"\0", "little"))
            env.word(temporary + 16, len(value))
        return accepted

    return convert


@pytest.mark.parametrize("value", [b"", b"fixed", b"f" * 24])
def test_repair_actual_fallback_effects_inplace_or_reallocation(value):
    env, _ = prepare_repair()
    env.overrides[0x140960630] = conversion(env, value)
    env.call(0x140A09540, env.output, env.object)
    pointer = (
        env.object if env.memory.read(env.object + 24, 8) <= 15 else env.memory.read(env.object, 8)
    )
    assert env.bytes(pointer, len(value) + 1) == value + b"\0"
    assert env.memory.read(env.object + 16, 8) == len(value)
    env.successful_output()


def test_repair_holds_registry_end_and_uses_current_candidate_values():
    env, registry = prepare_repair(codes=(7, 8))
    seen = []

    def convert(args):
        seen.append(args[0])
        env.word(0x14428B918, registry)
        env.word(registry + 4, 99, 4)
        return conversion(env, b"ok")(args) if len(seen) == 2 else 0

    env.overrides[0x140960630] = convert
    env.call(0x140A09540, env.output, env.object)
    assert seen == [7, 99]


def test_repair_exhaustion_failure_builder_is_actual_and_held_output_returns():
    env, _ = prepare_repair(codes=())
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140a08840"):
        env.call(0x140A09540, env.output, env.object)
    assert env.trace[-1] == (0x140A08840, (env.output, 0, 0x1432088D0, 0x27, 0x143208930))


def test_repair_returned_watson_nops_select_current_iat_twice_then_refuse_volatile_free():
    env, _ = prepare_repair()
    allocation = env.memory.allocate(48)
    pointer = allocation + 40
    env.word(pointer - 8, allocation - 0x100)

    def bad(args):
        temporary = args[2]
        env.word(temporary, pointer)
        env.word(temporary + 24, 0xFFF)
        return 0

    env.overrides[0x140960630] = bad
    initial_runtime = env.runtime

    def imports(target, args, data):
        result = initial_runtime(target, args, data)
        if target == WATSON:
            env.word(0x14319A060, WATSON2)
        return result

    # The direct public function supplies an independently changed terminal.
    from vantage.replay_player_name_skins import repair_replay_player_name

    with pytest.raises(UnresolvedReplayTaskRebuild, match=r"NOP.*volatile"):
        repair_replay_player_name(
            env.context,
            env.output,
            env.object,
            calls=env.calls,
            bind_local=env.memory.bind_local,
            scratch=bytes(0x60),
            imports=ReplayTaskRebuildCalls(imports),
        )
    assert [target for target, _ in env.trace if target in (WATSON, WATSON2)] == [WATSON, WATSON2]


@pytest.mark.parametrize("count,capacity", [(0, 0), (0, 3), (1, 0), (1, 3), (3, 1), (4, 4)])
def test_skins_full_real_reserve_append_and_existing_end_clear(count, capacity):
    values = [0xFEDCBA9876540000 + n for n in range(count)]
    payload = count.to_bytes(4, "little") + b"".join(v.to_bytes(8, "little") for v in values)
    env = Environment(payload)
    header = env.skin_header(capacity)
    assert env.call(0x140E33410, env.output, env.stream, header) == env.output
    begin, end = env.memory.read(header, 8), env.memory.read(header + 8, 8)
    assert end - begin == count * 8
    if count:
        assert [env.memory.read(begin + n * 8, 8) for n in range(count)] == values
    env.successful_output()


def test_skins_oversize_refuses_before_header_read():
    env = Environment((0xC80001).to_bytes(4, "little"))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="140e336f5"):
        env.call(0x140E33410, env.output, env.stream, 0xBAD)
    assert not any(a == 0xBAD for _, a, _, _ in env.memory.events)


def test_skins_append_store_then_current_end_add_after_alias_effect():
    env = Environment(b"\x01\0\0\0" + (99).to_bytes(8, "little"))
    header = env.skin_header(3)
    begin = env.memory.read(header, 8)

    def changed(address, width, value):
        if address == begin and width == 8 and value == 99:
            env.word(header + 8, begin + 8)

    env.memory.write_hook = changed
    env.call(0x140E33410, env.output, env.stream, header)
    assert env.memory.read(header + 8, 8) == begin + 16


def test_skins_current_count_after_counter_store_controls_loop():
    env = Environment(b"\x02\0\0\0" + (77).to_bytes(8, "little"))
    header = env.skin_header(3)

    def changed(address, width, value):
        frame = next((a for a, size in env.memory.locals if size == 0xB8), None)
        if frame and address == frame + 0x34 and value == 1:
            env.word(frame + 0x48, 1, 4)

    env.memory.write_hook = changed
    env.call(0x140E33410, env.output, env.stream, header)
    assert env.source.position == 12


@pytest.mark.parametrize(
    "target,arity", [(0x140A1D990, 3), (0x140A150F0, 7), (0x140A09540, 2), (0x140E33410, 3)]
)
def test_binder_rejects_malformed_arity_data_and_delegates_unknown(target, arity):
    env = Environment()
    with pytest.raises(ValueError, match="malformed"):
        env.bound.call(target, (0,) * (arity - 1), None)
    with pytest.raises(ValueError, match="malformed"):
        env.bound.call(target, (0,) * arity, memoryview(b"x"))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1234"):
        env.bound.call(0x1234, (), None)


@pytest.mark.parametrize("metadata_bound", [False, True])
def test_raw_status_reaches_real_metadata_after_processed_before_forward(metadata_bound):
    env = Environment(b"x")
    buffer = env.memory.allocate(1)

    def read_status(target, args):
        if target == IO:
            env.word(args[1] + 24, 9)

    env.after_call = read_status
    if metadata_bound:

        def metadata(args):
            assert env.memory.read(args[0] + 40, 1) == 1
            env.word(args[0] + 24, 0)

        env.overrides[0x140900ED0] = metadata
        env.call(0x140A150F0, env.output, 0, 0, 0, env.stream, buffer, 1)
        env.successful_output()
    else:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="140900ed0"):
            env.call(0x140A150F0, env.output, 0, 0, 0, env.stream, buffer, 1)
        assert not any(target == 0x1409076B0 for target, _ in env.trace)
    assert env.source.position == 1


@pytest.mark.parametrize(
    "reader,frontier",
    [
        ("byte", "140a153af"),
        ("name", "140a1dac6"),
        ("skins-count", "140e3351f"),
        ("skins-item", "140e33a9f"),
    ],
)
def test_fixed_forward_status_checked_after_raw_cleanup(reader, frontier):
    payload = b"x" if reader == "byte" else b"\x02\0a\0"
    if reader.startswith("skins"):
        payload = b"\x01\0\0\0" + (88).to_bytes(8, "little")
    env = Environment(payload)

    def status(target, args):
        expected = 12 if reader == "skins-item" else (4 if reader == "skins-count" else None)
        if target == 0x1409076B0 and (expected is None or env.source.position == expected):
            env.word(args[0] + 24, 9)

    env.after_call = status
    with pytest.raises(UnresolvedReplayTaskRebuild, match=frontier):
        if reader == "byte":
            env.call(0x140A150F0, env.output, 0, 0, 0, env.stream, env.memory.allocate(1), 1)
        elif reader == "name":
            env.name()
        else:
            env.call(0x140E33410, env.output, env.stream, env.skin_header())
    last = env.trace[-1][0]
    assert last == (0x1402BD7F0 if reader.startswith("skins") else 0x1402BD890)


@pytest.mark.parametrize("stage,frontier", [(1, "140a1dda1"), (2, "140a1dfb5")])
def test_name_fixed_returned_child_results_refuse_before_detail_tls(stage, frontier):
    env = Environment(b"\x02\0a\0")
    seen = 0

    def changed(address, width, value):
        nonlocal seen
        frame = next((a for a, size in env.memory.locals if size == 0xE8), None)
        if (
            frame
            and address == frame + 0x90
            and width == 1
            and value == 0
            and env.source.position == 4
        ):
            seen += 1
            if seen == stage:
                env.word(frame + 0x80, 9)

    env.memory.write_hook = changed
    with pytest.raises(UnresolvedReplayTaskRebuild, match=frontier):
        env.name()
    assert seen == stage
    assert env.bytes(env.output, 48) == bytes([0xA5]) * 48


@pytest.mark.parametrize("destroy_bound", [False, True])
def test_real_control_release_keeps_held_control_and_reloads_weak_vptr(destroy_bound):
    env = Environment(b"x")
    control = env.memory.allocate(16)
    table1, table2 = env.memory.allocate(16), env.memory.allocate(16)
    env.word(control, table1)
    env.word(control + 8, 1, 4)
    env.word(control + 12, 1, 4)
    env.word(table1, 0xD001)
    env.word(table2 + 8, 0xD002)

    def control_result(target, args):
        if target == IO:
            env.word(args[1] + 32, control)

    env.after_call = control_result
    if destroy_bound:

        def destroy(args):
            assert args == (control,)
            env.word(control, table2)

        def dispose(args):
            assert args == (control,)
            env.word(control, 0xFEED)

        env.overrides[0xD001] = destroy
        env.overrides[0xD002] = dispose
        env.call(0x140A150F0, env.output, 0, 0, 0, env.stream, env.memory.allocate(1), 1)
        assert env.memory.read(control, 8) == 0xFEED
        assert env.memory.read(control + 12, 4) == 0
    else:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="d001"):
            env.call(0x140A150F0, env.output, 0, 0, 0, env.stream, env.memory.allocate(1), 1)
        assert env.memory.read(control + 12, 4) == 1
    assert env.memory.read(control + 8, 4) == 0


@pytest.mark.parametrize("reserve", [False, True])
def test_skins_held_initial_gate_vs_post_commit_current_count(reserve):
    env = Environment(b"\x01\0\0\0" + (99).to_bytes(8, "little"))
    header = env.skin_header(0 if reserve else 2)
    once = False

    def read_count(address, width, _value):
        nonlocal once
        if address == header + 16 and width == 8 and not once:
            once = True
            frame = next(a for a, size in env.memory.locals if size == 0xB8)
            env.word(frame + 0x48, 0, 4)

    env.memory.read_hook = read_count
    env.call(0x140E33410, env.output, env.stream, header)
    assert env.source.position == (4 if reserve else 12)


def test_skins_large_initial_allocation_aligns_actual_base_and_preserves_backpointer():
    count = 512
    env = Environment(count.to_bytes(4, "little") + bytes(count * 8))
    header = env.skin_header()
    env.call(0x140E33410, env.output, env.stream, header)
    pointer = env.memory.read(header, 8)
    assert pointer % 32 == 0
    base = env.memory.read(pointer - 8, 8)
    assert 8 <= pointer - base <= 39
    assert (0x142D6BA78, (count * 8 + 0x27,)) in env.trace
    env.successful_output()


def test_skins_growth_held_insert_vs_current_end_uses_two_real_moves():
    env = Environment(b"\x01\0\0\0" + (99).to_bytes(8, "little"))
    header = env.skin_header(3)
    begin = env.memory.read(header, 8)
    env.word(header + 16, begin + 8)
    env.overrides[0x1402A94D0] = lambda args: env.memory.allocate(max(32, args[0]))

    def after(target, args):
        if target == IO and args[3] == 8:
            env.word(header + 8, begin + 8)
        if target == 0x1402A94D0:
            env.word(header + 8, begin + 16)

    env.after_call = after
    env.call(0x140E33410, env.output, env.stream, header)
    moves = [args for target, args in env.trace if target == 0x142D6E3DB]
    assert len(moves) == 2
    assert moves[0][1:] == (begin, 8)
    assert moves[1][1:] == (begin + 8, 8)
    new_begin = env.memory.read(header, 8)
    assert env.memory.read(new_begin + 8, 8) == 99


@pytest.mark.parametrize("growth", [False, True])
def test_skins_only_growth_reloads_current_saved_stream(growth):
    env = Environment(b"\x02\0\0\0" + (11).to_bytes(8, "little") + (22).to_bytes(8, "little"))
    header = env.skin_header(3)
    begin = env.memory.read(header, 8)
    second_stream, second_table = env.memory.allocate(8), env.memory.allocate(32)
    env.word(second_stream, second_table)
    env.word(second_table + 24, IO + 100)
    second_source = ReplaySavedInput((33).to_bytes(8, "little"))
    env.register(
        bind_replay_saved_input(
            env.context,
            env.calls,
            second_source,
            stream=second_stream,
            target=IO + 100,
            result_bytes=bytes(48),
        ),
        (IO + 100,),
    )
    changed = False

    def after(target, args):
        nonlocal changed
        if target == IO and args[3] == 8 and not changed:
            changed = True
            frame = next(a for a, size in env.memory.locals if size == 0xB8)
            env.word(frame + 0x40, second_stream)
            if growth:
                env.word(header + 8, begin + 8)
                env.word(header + 16, begin + 8)

    env.after_call = after
    env.call(0x140E33410, env.output, env.stream, header)
    assert second_source.position == (8 if growth else 0)
    assert env.source.position == (12 if growth else 20)


@pytest.mark.parametrize("target", [0x1402BB300, 0x1402BA970])
def test_missing_storage_child_refuses_at_actual_call_with_prior_effects(target):
    payload = b"\x11\0" if target == 0x1402BB300 else b"\x01\0\0\0"
    env = Environment(payload)
    del env.routes[target]
    with pytest.raises(UnresolvedReplayTaskRebuild, match=f"{target:x}"):
        if target == 0x1402BB300:
            env.name()
        else:
            env.call(0x140E33410, env.output, env.stream, env.skin_header())
    assert env.source.position == len(payload)
    assert env.trace[-1][0] == target


@pytest.mark.parametrize("reader", ["repair", "skins"])
def test_public_direct_watson_import_alias_is_terminal_not_owned_body_recursion(reader):
    from vantage.replay_player_name_skins import (
        read_replay_player_skins,
        repair_replay_player_name,
    )

    received = []

    def terminal(target, args, data):
        received.append((target, args, data))
        raise UnresolvedReplayTaskRebuild("explicit terminal alias reached")

    if reader == "repair":
        env, _ = prepare_repair()
        base = env.memory.allocate(48)
        pointer = base + 40
        env.word(pointer - 8, base - 0x100)

        def bad(args):
            env.word(args[2], pointer)
            env.word(args[2] + 24, 0xFFF)
            return 0

        env.overrides[0x140960630] = bad
        selected = 0x140A09540
        env.word(0x14319A060, selected)
        with pytest.raises(UnresolvedReplayTaskRebuild, match="terminal alias"):
            repair_replay_player_name(
                env.context,
                env.output,
                env.object,
                calls=env.calls,
                bind_local=env.memory.bind_local,
                scratch=bytes(0x60),
                imports=ReplayTaskRebuildCalls(terminal),
            )
    else:
        env = Environment((512).to_bytes(4, "little"))
        env.overrides[0x142D6BA78] = lambda _args: 0
        selected = 0x140E33410
        env.word(0x14319A060, selected)
        with pytest.raises(UnresolvedReplayTaskRebuild, match="terminal alias"):
            read_replay_player_skins(
                env.context,
                env.output,
                env.stream,
                env.skin_header(),
                calls=env.calls,
                atomics=env.atomics,
                bind_local=env.memory.bind_local,
                scratch=bytes(0xB8),
                imports=ReplayTaskRebuildCalls(terminal),
            )
    assert received == [(selected, (0, 0, 0, 0, 0), None)]


def test_name_coherent_frame_stays_live_through_final_real_destructor():
    env = Environment(b"\x02\0a\0")
    observed = []

    def after(target, _args):
        if target == 0x1402A8920:
            frame = next(a for a, size in env.memory.locals if size == 0xE8)
            observed.append(env.memory.read(frame + 0xB0, 8))
            env.successful_output()

    env.after_call = after
    env.name()
    assert observed == [15]
