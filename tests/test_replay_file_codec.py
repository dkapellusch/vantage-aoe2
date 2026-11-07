"""Source-led codec controls; all memory and CRT identities are authored.

Valid output oracles use known bytes and the independent stdlib compressor.
Source-specific statuses, staging and publication order use retained ASM.
"""

from __future__ import annotations

import struct
import zlib
from contextlib import contextmanager

import pytest

from vantage import replay_file_codec as codec
from vantage import replay_file_decoder as decoder
from vantage.replay_file_read import ReplayFileReadProfile, bind_replay_file_read
from vantage.replay_file_support import ReplayFileSupportProfile, bind_replay_file_support
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

MAIN, HELPER, COPY, SET = 0x14257FC20, 0x14257FB90, 0x142D6E3B1, 0x142D6E3B7
COPY_IAT, SET_IAT, COPY_TOKEN, SET_TOKEN = 0x143199930, 0x143199938, 0xCA01, 0xCA02
U32, U64 = (1 << 32) - 1, (1 << 64) - 1
# Explicit retained source-data bytes; production binding provides no data defaults.
TABLES = bytes.fromhex(
    "03000400050006000700080009000a000b000d000f001100130017001b001f0023002b0033003b0043005300"
    "630073008300a300c300e3000201000000000000000000000000000001010101020202020303030304040404"
    "0505050500000000000000000000000001000200030004000500070009000d00110019002100310041006100"
    "8100c1000101810101020103010401060108010c011001180120013001400160000000000000000001010202"
    "03030404050506060707080809090a0a0b0b0c0c0d0d000010111200080709060a050b040c030d020e010f00"
    "0101010004000000050504000203070003030b00000000000000000005050505050505050505050505050505"
    "0707070707070707070707070707070708080808080808080808080808080808090909090909090909090909"
    "09090909"
)
JUMPS = bytes.fromhex(
    "9efd5702d8fd570202fe5702d0065802101158022307580267075802a1075802101158026408580203105802"
    "0a0a58021011580210115802b70a580210115802d9ff5702d60f5802bcfe57021011580210115802f10f5802"
    "101158028b0258023e035802ad0358026b0458024705580210115802101158021011580210115802d00e5802"
    "10115802e4105802bf0f5802b0fe570215105802800858028d0f580210115802601058023010580210115802"
    "101158021011580210115802101158021011580210115802101158021108580245085802f0055802"
)


class Rig:
    def __init__(self, payload=b"", *, output_size=65536):
        self.memory = ReplayMemory()
        self.state = self.memory.calloc(0xA0C8, 1)
        self.input = self.memory.allocate(max(1, len(payload)))
        self.memory.write_bytes(self.input, payload or b"\0")
        self.output = self.memory.allocate(output_size)
        self.memory.write_bytes(self.output, b"\xb7" * output_size)
        self.counts, self.homes = self.memory.calloc(16, 1), self.memory.calloc(24, 1)
        self.memory.write(self.homes, 8, self.output)
        self.memory.write(self.homes + 8, 8, self.counts + 8)
        self.memory.write(self.homes + 16, 4, 4)
        self.memory.map_bytes(COPY_IAT, COPY_TOKEN.to_bytes(8, "little"))
        self.memory.map_bytes(SET_IAT, SET_TOKEN.to_bytes(8, "little"))
        self.memory.map_bytes(0x143506A48, TABLES)
        self.memory.map_bytes(0x142581310, JUMPS)
        self.events, self.locals, self.active = [], [], []
        self.after_read, self.after_write = None, None
        self.payload_size, self.output_size = len(payload), output_size
        self.import_return = "destination"

        def read(address, width):
            self.events.append(("r", address, width))
            value = self.memory.read(address, width)
            if self.after_read is not None:
                self.after_read(address, width)
            return value

        def write(address, width, value):
            self.events.append(("w", address, width, value))
            self.memory.write(address, width, value)
            if self.after_write is not None:
                self.after_write(address, width, value)

        def imported(target, args, data):
            assert data is None and len(args) == 3
            self.events.append(("i", target, args))
            if target == COPY_TOKEN:
                result = self.memory.move(*args)
            elif target == SET_TOKEN:
                result = self.memory.fill(*args)
            else:
                raise UnresolvedReplayTaskRebuild(f"authored import{target:x} unavailable")
            return result if self.import_return == "destination" else self.import_return

        self.storage = ReplayTaskRebuildStorage(1, read, write)
        self.imports = ReplayTaskRebuildCalls(imported)
        self.bind()

    @contextmanager
    def bind_local(self, view):
        with self.memory.bind_local(view) as address:
            self.locals.append((address, len(view)))
            self.active.append(address)
            try:
                yield address
            finally:
                self.active.remove(address)

    def bind(self, *, imports=None, calls=None):
        self.bound = codec.bind_replay_file_codec_homes(
            self.storage,
            ReplayTaskRebuildCalls(None) if calls is None else calls,
            imports=self.imports if imports is None else imports,
            bind_local=self.bind_local,
            profile=codec.ReplayFileCodecProfile(b"\xa5" * 0x180),
        )

    def run(self, *, input_offset=0, input_count=None, output_offset=0, output_count=None, flags=4):
        self.memory.write(
            self.counts, 8, self.payload_size - input_offset if input_count is None else input_count
        )
        self.memory.write(
            self.counts + 8,
            8,
            self.output_size - output_offset if output_count is None else output_count,
        )
        self.memory.write(self.homes, 8, self.output + output_offset)
        self.memory.write(self.homes + 16, 4, flags)
        result = self.bound.call(
            MAIN,
            (
                self.state,
                self.input + input_offset,
                self.counts,
                self.output,
                self.homes,
                self.homes + 8,
                self.homes + 16,
            ),
            None,
        )
        assert not self.active
        return result, self.memory.read(self.counts, 8), self.memory.read(self.counts + 8, 8)

    def expired(self):
        assert not self.active
        for address, _ in self.locals:
            with pytest.raises(ReplayMemoryError):
                self.memory.read(address, 1)


def compressed(payload, *, level=6, strategy=zlib.Z_DEFAULT_STRATEGY, wrapped=False):
    stream = zlib.compressobj(level, zlib.DEFLATED, 15 if wrapped else -15, 8, strategy)
    return stream.compress(payload) + stream.flush()


@pytest.mark.parametrize("level,strategy,block", [(0, 0, 0), (6, zlib.Z_FIXED, 1), (6, 0, 2)])
@pytest.mark.parametrize("wrapped", [False, True])
def test_all_block_types_known_bytes_and_checksum(level, strategy, block, wrapped):
    payload = bytes(range(32)) * 100
    encoded = compressed(payload, level=level, strategy=strategy, wrapped=wrapped)
    assert (encoded[2 if wrapped else 0] >> 1) & 3 == block
    r = Rig(encoded)
    result, consumed, produced = r.run(flags=5 if wrapped else 12)
    assert (result, consumed, produced) == (0, len(encoded), len(payload))
    assert r.memory.read_bytes(r.output, produced) == payload
    assert r.memory.read(r.state, 4) == 34
    assert r.memory.read(r.state + 0x1C, 4) == zlib.adler32(payload)
    assert r.memory.read_bytes(r.output + produced, 7) == b"\xb7" * 7
    r.expired()


def test_stored_input_starvation_and_one_byte_resumptions():
    payload = b"Vantage"
    encoded = b"\x01\x07\x00\xf8\xff" + payload
    r = Rig(encoded)
    taken, emitted, statuses = 0, 0, []
    for _ in range(len(encoded)):
        result, count, output = r.run(
            input_offset=taken, input_count=1, output_offset=emitted, flags=6
        )
        assert count == 1
        taken += count
        emitted += output
        statuses.append(result)
    assert statuses[:-1] == [1] * (len(encoded) - 1)
    assert statuses[-1] == 0
    assert (taken, emitted) == (len(encoded), len(payload))
    assert r.memory.read_bytes(r.output, emitted) == payload
    r.expired()


def test_output_full_keeps_match_and_continues_forward_overlapping_copy():
    payload = b"A" * 600 + b"bc" * 90
    encoded = compressed(payload, strategy=zlib.Z_FIXED)
    r = Rig(encoded)
    result, taken, emitted = r.run(output_count=11)
    assert result == 2 and emitted == 11
    assert r.memory.read_bytes(r.output, emitted) == payload[:11]
    result, count, output = r.run(input_offset=taken, output_offset=emitted)
    assert (result, taken + count, emitted + output) == (0, len(encoded), len(payload))
    assert r.memory.read_bytes(r.output, len(payload)) == payload


@pytest.mark.parametrize("wrapped", [False, True])
def test_prefetched_trailing_bytes_are_unread_at_completion(wrapped):
    payload = b"abc" * 37
    encoded = compressed(payload, wrapped=wrapped)
    r = Rig(encoded + b"TAIL")
    assert r.run(flags=5 if wrapped else 4) == (0, len(encoded), len(payload))
    assert r.memory.read_bytes(r.output, len(payload)) == payload


@pytest.mark.parametrize("flags,expected", [(4, U32 - 3), (6, 1)])
def test_no_input_distinguishes_final_and_more_input_status(flags, expected):
    r = Rig()
    assert r.run(flags=flags) == (expected, 0, 0)
    assert r.memory.read(r.state, 4) == 3


@pytest.mark.parametrize("encoded,state", [(b"\x07", 10), (b"\x01\x01\0\0\0X", 39)])
def test_malformed_block_and_stored_length_have_source_error_status(encoded, state):
    r = Rig(encoded)
    result, _, produced = r.run()
    assert result == U32 and produced == 0
    assert r.memory.read(r.state, 4) == state


def test_bad_checksum_retains_completion_and_published_counts():
    payload = b"checksum side effects"
    encoded = compressed(payload, wrapped=True)
    encoded = encoded[:-1] + bytes([encoded[-1] ^ 1])
    r = Rig(encoded)
    assert r.run(flags=5) == (U32 - 1, len(encoded), len(payload))
    assert r.memory.read_bytes(r.output, len(payload)) == payload
    assert r.memory.read(r.state, 4) == 34
    assert r.memory.read(r.state + 0x1C, 4) == zlib.adler32(payload)
    writes = [e for e in r.events if e[0] == "w"]
    publications = [(e[1], e[2]) for e in writes]
    assert publications.index((r.counts, 8)) < publications.index((r.counts + 8, 8))
    checksum_writes = [(i, e[3]) for i, e in enumerate(writes) if e[1] == r.state + 0x1C]
    assert [value for _, value in checksum_writes] == [1, zlib.adler32(payload)]
    assert publications.index((r.counts + 8, 8)) < checksum_writes[-1][0]


@pytest.mark.parametrize("payload,expected", [(b"", U32 - 1), (b"abc", 0)])
def test_checksum_flags_reload_only_after_positive_output(payload, expected):
    encoded = compressed(payload, wrapped=True)
    r = Rig(encoded[:-1] + bytes([encoded[-1] ^ 1]))

    def after_write(address, width, value):
        if (address, width) == (r.counts + 8, 8):
            r.memory.write(r.homes + 16, 4, 4)

    r.after_write = after_write
    assert r.run(flags=5) == (expected, len(encoded), len(payload))
    assert r.memory.read(r.state + 0x1C, 4) == zlib.adler32(payload)


def test_checksum_reads_current_output_after_count_alias_effects():
    payload = b"checksum current bytes"
    encoded = compressed(payload, wrapped=True)
    r = Rig(encoded)

    def after_write(address, width, value):
        if (address, width) == (r.counts + 8, 8):
            r.memory.write_bytes(r.output, b"Z" * len(payload))

    r.after_write = after_write
    assert r.run(flags=5) == (U32 - 1, len(encoded), len(payload))
    assert r.memory.read(r.state + 0x1C, 4) == zlib.adler32(b"Z" * len(payload))


def test_parameter_rejection_publishes_output_then_input_without_state_reads():
    r = Rig()
    # Three-byte ring capacity produces mask2, which fails the source power-of-two test.
    result, consumed, produced = r.run(output_count=3, flags=0)
    assert (result, consumed, produced) == (U32 - 2, 0, 0)
    assert not any(e[0] == "r" and r.state <= e[1] < r.state + 0xA0C8 for e in r.events)
    assert [e[1:] for e in r.events if e[0] == "w"][-2:] == [(r.counts + 8, 8, 0), (r.counts, 8, 0)]


def test_maximum_repeat_writes_all_457_staging_bytes_before_overshoot_error():
    r = Rig(b"\x7f")
    r.memory.write_bytes(r.state + 0x1EEB, b"X" * 457)
    for offset, value in ((0, 18), (0x20, 18), (0x24, 319), (0x28, 7), (0x2C, 288), (0x30, 32)):
        r.memory.write(r.state + offset, 4, value)
    assert r.run() == (U32, 1, 0)
    assert r.memory.read(r.state, 4) == 21
    assert r.memory.read_bytes(r.state + 0x1EEB, 457) == b"X" * 319 + bytes(138)
    fill = ("i", SET_TOKEN, (r.state + 0x1EEB + 319, 0, 138))
    assert fill in r.events
    assert r.events.index(fill) < r.events.index(("w", r.state, 4, 21))


@pytest.mark.parametrize(
    "phase,start,size,raw", [(0, 0x1848, 0x480, None), (1, 0x1CC8, 0x80, 1), (2, 0x1D48, 0x4C, 0)]
)
def test_complete_helper_and_tail_import_real_effects(phase, start, size, raw):
    r = Rig()
    r.memory.write_bytes(r.state + 0x1847, b"X" * 0x552)
    r.memory.write(r.state + 0x18, 4, phase)
    r.import_return = None
    assert r.bound.call(HELPER, (r.state,), None) == raw
    assert r.memory.read_bytes(r.state + start, size) == bytes(size)
    assert r.memory.read(r.state + start - 1, 1) == ord("X")
    assert r.memory.read(r.state + start + size, 1) == ord("X")
    assert not r.locals


def test_home_capture_order_and_distinct_current_capacity_samples():
    r = Rig(b"\x07")
    assert r.run()[0] == U32
    reads = [e[1:] for e in r.events if e[0] == "r"]
    assert reads[:3] == [(r.homes + 8, 8), (r.homes, 8), (r.counts, 8)]
    assert reads.count((r.counts + 8, 8)) == 1  # flag4 skips the second ring-capacity sample.
    r = Rig()
    r.run(flags=2)
    reads = [e[1:] for e in r.events if e[0] == "r"]
    assert reads.count((r.counts + 8, 8)) == 2


def test_unknown_current_jump_target_refuses_after_initial_source_reads():
    r = Rig()
    r.memory.write(0x142581310, 4, 0x1234)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="control target140001234"):
        r.run()
    assert not any(e[0] == "w" and e[1] in (r.counts, r.counts + 8) for e in r.events)
    r.expired()


@pytest.mark.parametrize(
    "state",
    [4, 8, 12, 13, 15, 19, 20, 22, 28, 29, 30, 31, 33, 40, 43, 44, 45, 46, 47, 48, 49, 50, 54, U32],
)
def test_source_unused_resume_entries_and_out_of_range_state_return_error(state):
    r = Rig()
    r.memory.write(r.state, 4, state)
    assert r.run() == (U32, 0, 0)
    assert r.memory.read(r.state, 4) == state


def test_current_iat_is_mandatory_and_prior_staging_effects_survive_refusal():
    r = Rig()
    r.memory.write(r.state + 0x18, 4, 0)
    r.memory.write(SET_IAT, 8, 0xDEAD)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="importdead unavailable"):
        r.bound.call(HELPER, (r.state,), None)
    assert ("i", 0xDEAD, (r.state + 0x1848, 0, 0x480)) in r.events


@pytest.mark.parametrize("target,args", [(MAIN, (1,)), (HELPER, ()), (COPY, (1, 2)), (SET, ())])
def test_malformed_owned_abi_refuses_before_binding(target, args):
    r = Rig()
    with pytest.raises(ValueError, match="malformed"):
        r.bound.call(target, args, None)
    assert not r.locals and not r.events


def test_unknown_target_preserves_argument_and_data_identity():
    r = Rig()
    args, data, seen = (5, 6), memoryview(b"x"), []

    def delegate(target, values, view):
        seen.append((target, values is args, view is data))
        return None

    r.bind(calls=ReplayTaskRebuildCalls(delegate))
    assert r.bound.call(0xD00D, args, data) is None
    assert seen == [(0xD00D, True, True)]


def composed_wrapper(r):
    r.memory.map_bytes(0x143199E80, (0xCA03).to_bytes(8, "little"))

    def minimum(target, args, data):
        assert (target, data, len(args)) == (0xCA03, None, 2)
        values = [struct.unpack("<d", word.to_bytes(8, "little"))[0] for word in args]
        assert all(0 <= value <= U32 for value in values)
        return int.from_bytes(struct.pack("<d", min(values)), "little")

    return decoder.bind_replay_file_decoder_homes(
        r.storage,
        r.bound,
        math_calls=ReplayTaskRebuildCalls(minimum),
        core_home_calls=r.bound,
        bind_local=r.bind_local,
        profile=decoder.ReplayFileDecoderProfile(b"\xc6" * 0x68),
    )


def test_actual_codec_wrapper_and_current_ring_copy_compose():
    payload = b"Vantage camera movement " * 9
    encoded = compressed(payload)
    r = Rig(encoded)
    wrapper = composed_wrapper(r)
    homes = r.memory.calloc(32, 1)
    for address, value in (
        (homes + 8, r.counts + 8),
        (homes + 16, r.state),
        (homes + 24, 1),
        (r.counts, len(encoded)),
        (r.counts + 8, len(payload)),
    ):
        r.memory.write(address, 8, value)
    assert (
        wrapper.call(
            0x14178AE30,
            (
                r.input,
                0,
                r.counts,
                r.output,
                homes,
                homes + 8,
                homes + 16,
                homes + 24,
            ),
            None,
        )
        == 0
    )
    assert r.memory.read_bytes(r.output, len(payload)) == payload
    assert (r.memory.read(r.counts, 8), r.memory.read(r.counts + 8, 8)) == (
        len(encoded),
        len(payload),
    )
    assert r.memory.read(r.state + 0xA0B8, 4) == len(payload)
    assert r.memory.read(r.state + 0xA0BC, 4) == len(payload)
    assert r.memory.read(r.state + 0xA0C0, 1) == 1
    assert [size for _, size in r.locals] == [0x68, 0x180]
    r.expired()


def test_actual_file_read_support_result_wrapper_codec_repeat_reads():
    payload = b"Vantage replay without the game " * 11
    encoded = compressed(payload)
    r = Rig(encoded)
    wrapper = composed_wrapper(r)
    strict, atomics = ReplayTaskRebuildCalls(None), ReplayUnitAIMapAtomics(None, None)
    strings = bind_replay_saved_string(r.storage, strict, imports=r.imports)
    results = bind_replay_saved_result(r.storage, strings, atomics=atomics, imports=r.imports)
    support = bind_replay_file_support(
        r.storage,
        results,
        variadic_calls=strict,
        atomics=atomics,
        bind_local=r.bind_local,
        profile=ReplayFileSupportProfile(b"\xa5" * 0x68, b"\xb6" * 0x28, None),
    )
    calls = bind_replay_file_read(
        r.storage,
        support,
        variadic_calls=strict,
        decoder_calls=wrapper,
        atomics=atomics,
        bind_local=r.bind_local,
        profile=ReplayFileReadProfile(b"\xc7" * 0xB8, None, 1),
    )
    file, result = r.memory.calloc(0xA8, 1), r.memory.allocate(48)
    r.memory.write_bytes(result, b"\xb7" * 48)
    for offset, width, value in (
        (0x54, 1, 1),
        (0x80, 4, 2),
        (0x88, 8, r.state),
        (0x90, 8, r.input),
        (0x98, 8, len(encoded)),
    ):
        r.memory.write(file + offset, width, value)
    offset = 0
    for size in (3, 5, len(payload) - 8):
        assert calls.call(0x140916DB0, (file, result, r.output + offset, size), None) == result
        offset += size
        assert r.memory.read_bytes(r.output, offset) == payload[:offset]
        assert r.memory.read(file + 0xA0, 8) == len(encoded)
        assert r.memory.read_bytes(result, 48) == bytes(41) + b"\xb7" * 7
    assert r.memory.read(r.state + 0xA0B8, 4) == len(payload)
    assert r.memory.read(r.state + 0xA0BC, 4) == len(payload)
    assert [size for _, size in r.locals].count(0x180) == 1
    r.expired()


@pytest.mark.parametrize("bits", [8, 16, 32, 64])
@pytest.mark.parametrize("kind", ["carry-add", "overflow-add", "borrow-sub", "overflow-sub"])
def test_integer_flags_independent_boundary_oracles(bits, kind):
    r = Rig()
    machine = codec._Machine(r.storage, r.imports, ())
    high, mask = 1 << (bits - 1), (1 << bits) - 1
    vectors = {
        "carry-add": ("add", mask, 1, 0, True, False, True, False),
        "overflow-add": ("add", high - 1, 1, high, False, True, False, True),
        "borrow-sub": ("sub", 0, 1, mask, True, False, False, True),
        "overflow-sub": ("sub", high, 1, high - 1, False, True, False, False),
    }
    op, left, right, expected, carry, overflow, zero, sign = vectors[kind]
    machine.registers.write("rax", 64, left)
    machine.binary(op, ("r", "rax", bits), ("i", right))
    assert machine.registers.read("rax", bits, 0) == expected
    assert (
        machine.flags.carry,
        machine.flags.overflow,
        machine.flags.zero,
        machine.flags.sign,
    ) == (carry, overflow, zero, sign)


@pytest.mark.parametrize("bits", [32, 64])
def test_multiply_high_half_and_undefined_flags(bits):
    r = Rig()
    machine = codec._Machine(r.storage, r.imports, ())
    mask = (1 << bits) - 1
    machine.registers.write("rax", 64, mask)
    machine.registers.write("rcx", 64, mask)
    machine.multiply((("r", "rcx", bits),), signed=False)
    assert machine.registers.read("rax", 64, 0) == 1
    assert machine.registers.read("rdx", 64, 0) == mask - 1
    assert machine.flags.carry is True and machine.flags.overflow is True
    with pytest.raises(UnresolvedReplayTaskRebuild, match="undefined zero"):
        machine.flags.condition("e", 0)


@pytest.mark.parametrize("bits", [32, 64])
@pytest.mark.parametrize("overflow", [False, True])
def test_signed_imul_independent_products(bits, overflow):
    r = Rig()
    machine = codec._Machine(r.storage, r.imports, ())
    mask, high = (1 << bits) - 1, 1 << (bits - 1)
    machine.registers.write("rcx", 64, high if overflow else mask)
    machine.multiply(
        (("r", "rax", bits), ("r", "rcx", bits), ("i", -1 if overflow else 2)), signed=True
    )
    assert machine.registers.read("rax", 64, 0) == (high if overflow else mask - 1)
    assert machine.flags.carry is overflow and machine.flags.overflow is overflow


@pytest.mark.parametrize(
    "operation,value,count,expected,carry",
    [
        ("shl", 0x80000001, 1, 2, True),
        ("shr", 0x80000001, 1, 0x40000000, True),
        ("sar", 0x80000001, 1, 0xC0000000, True),
        ("shl", 1, 33, 2, False),
        ("shr", 0x80000000, 31, 1, False),
    ],
)
def test_shifts_independent_literals(operation, value, count, expected, carry):
    r = Rig()
    machine = codec._Machine(r.storage, r.imports, ())
    machine.registers.write("rax", 64, value)
    machine.shift(operation, ("r", "rax", 32), ("i", count))
    assert machine.registers.read("rax", 64, 0) == expected
    assert machine.flags.carry is carry


def test_partial_defined_registers_and_zero_shift_preserve_flags():
    r = codec._Registers()
    r.write("rax", 8, 0x81)
    assert r.read("rax", 8, 0) == 0x81
    with pytest.raises(UnresolvedReplayTaskRebuild, match="undefined rax/16"):
        r.read("rax", 16, 0)
    r.write("rax", 64, U64)
    r.write("rax", 16, 0x1234)
    assert r.read("rax", 64, 0) == 0xFFFFFFFFFFFF1234
    r.write("rax", 32, 0x80000001)
    assert r.read("rax", 64, 0) == 0x80000001
    rig = Rig()
    machine = codec._Machine(rig.storage, rig.imports, (), registers=r)
    machine.flags = codec._Flags(True, False, True, True)
    machine.shift("shl", ("r", "rax", 32), ("i", 32))
    assert r.read("rax", 64, 0) == 0x80000001
    assert machine.flags == codec._Flags(True, False, True, True)


def test_inc_preserves_carry_and_cmov_keeps_flags(monkeypatch):
    r = Rig()
    machine = codec._Machine(r.storage, r.imports, ())
    machine.registers.write("rax", 64, U32)
    machine.flags.carry = True
    monkeypatch.setitem(
        codec._PROGRAM, codec._START, (codec._START + 1, "inc", (("r", "rax", 32),))
    )
    monkeypatch.setitem(
        codec._PROGRAM, codec._START + 1, (codec._EXIT, "cmovae", (("r", "rax", 32), ("i", 7)))
    )
    assert machine.run(codec._START) == 0
    assert machine.flags.carry is True and machine.flags.zero is True


@pytest.mark.parametrize("extend_to_64,expected", [(False, 0xFFFF8001), (True, 0xFFFFFFFFFFFF8001)])
def test_movsx_dword_and_cdqe_distinct_extensions(monkeypatch, extend_to_64, expected):
    r = Rig()
    machine = codec._Machine(r.storage, r.imports, ())
    machine.registers.write("rbx", 64, 0x8001)
    monkeypatch.setitem(
        codec._PROGRAM,
        codec._START,
        (codec._START + 1, "movsx", (("r", "rax", 32), ("r", "rbx", 16))),
    )
    monkeypatch.setitem(
        codec._PROGRAM,
        codec._START + 1,
        (codec._EXIT, "cdqe", ()) if extend_to_64 else (codec._EXIT, "nop", ()),
    )
    assert machine.run(codec._START) == 0xFFFF8001
    assert machine.registers.read("rax", 64, 0) == expected


def test_external_volatile_definedness_and_ignored_opaque_return():
    r = codec._Registers()
    for name in ("rax", "rcx", "rdx", "r8", "r9", "r10", "r11", "rbx", "rsi"):
        r.write(name, 64, 99)
    r.imported_return(None)
    assert r.return_rax() is None
    assert r.read("rbx", 64, 0) == r.read("rsi", 64, 0) == 99
    for name in ("rax", "rcx", "rdx", "r8", "r9", "r10", "r11"):
        with pytest.raises(UnresolvedReplayTaskRebuild, match="undefined"):
            r.read(name, 64, 0)


@pytest.mark.parametrize("seed", [b"", bytes(0x17F), bytes(0x181), bytearray(0x180)])
def test_profile_requires_explicit_exact_local_seed(seed):
    with pytest.raises(ValueError, match="seed"):
        codec.ReplayFileCodecProfile(seed)
