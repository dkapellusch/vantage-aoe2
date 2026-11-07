"""Original structural-name rules over owned memory, without native execution."""

from __future__ import annotations

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_player_name_validation import (
    bind_replay_player_name_validation,
    scan_replay_player_name_bytes,
    validate_replay_player_name_bytes,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

TEXT, COUNT, ERROR = 0x10000, 0x20000, 0x30000


class Case:
    def __init__(self, raw):
        self.memory = ReplayMemory()
        self.memory.map_bytes(TEXT, raw)
        self.memory.map_bytes(COUNT, bytes([0xA5]) * 4)
        self.memory.map_bytes(ERROR, bytes([0x5A]) * 4)
        self.events = []
        self.hook = None
        self.context = ReplayTaskRebuildStorage(TEXT, self.read, self.write)

    def read(self, address, width):
        value = self.memory.read(address, width)
        self.events.append(("read", address, width, value))
        if self.hook:
            self.hook(address, width, value)
        return value

    def write(self, address, width, value):
        self.events.append(("write", address, width, value))
        self.memory.write(address, width, value)

    def scan(self, count=COUNT, error=ERROR):
        return scan_replay_player_name_bytes(self.context, TEXT, count, error)


@pytest.mark.parametrize(
    ("raw", "count"),
    [
        (b"\0", 0),
        (b"A\0", 1),
        (b"Gaia\0", 4),
        (b"\x7f\0", 1),
        (b"\xc2\x80\0", 1),
        (b"\xdf\xbf\0", 1),
        (b"\xe0\xa0\x80\0", 1),
        (b"\xef\xbf\xbf\0", 1),
        (b"\xf0\x90\x80\x80\0", 1),
        (b"\xf4\x8f\xbf\xbf\0", 1),
        (b"A\xc2\xa2\xe2\x82\xac\xf0\x9f\x98\x80Z\0", 5),
    ],
)
def test_structural_sequences_and_completed_count(raw, count):
    case = Case(raw)
    assert case.scan() == 1
    assert case.memory.read(COUNT, 4) == count
    assert case.memory.read(ERROR, 4) == 0xFFFFFFFF


@pytest.mark.parametrize(
    "raw",
    [
        b"\xc0\x80\0",
        b"\xc1\xbf\0",
        b"\xe0\x80\x80\0",
        b"\xed\xa0\x80\0",
        b"\xf0\x80\x80\x80\0",
        b"\xf5\x80\x80\x80\0",
        b"\xf7\xbf\xbf\xbf\0",
    ],
)
def test_source_accepts_sequences_rejected_by_strict_unicode(raw):
    case = Case(raw)
    assert case.scan() == 1
    assert case.memory.read(COUNT, 4) == 1
    with pytest.raises(UnicodeDecodeError):
        raw[:-1].decode("utf-8")


@pytest.mark.parametrize(
    ("raw", "index"),
    [
        (b"\x80\0", 0),
        (b"\xbf\0", 0),
        (b"\xf8\0", 0),
        (b"\xff\0", 0),
        (b"\xc2\0", 0),
        (b"\xc2A\0", 0),
        (b"\xe2\x82\0", 0),
        (b"\xf0\x90\x80\0", 0),
        (b"A\x80\0", 1),
        (b"A\xc2\x80Z\xf8\0", 3),
    ],
)
def test_failure_preserves_initial_count_and_reports_completed_sequences(raw, index):
    case = Case(raw)
    assert case.scan() == 0
    assert case.memory.read(COUNT, 4) == 0
    assert case.memory.read(ERROR, 4) == index


def test_ascii_reads_and_output_writes_have_source_order():
    case = Case(b"A\0")
    assert case.scan() == 1
    assert case.events == [
        ("write", COUNT, 4, 0),
        ("write", ERROR, 4, 0xFFFFFFFF),
        ("read", TEXT, 1, 65),
        ("read", TEXT, 1, 65),
        ("read", TEXT + 1, 1, 0),
        ("write", COUNT, 4, 1),
    ]


def test_initial_output_alias_can_make_input_empty():
    case = Case(b"ABCD\0")
    assert case.scan(count=TEXT) == 1
    assert case.events[0] == ("write", TEXT, 4, 0)
    assert case.events[2] == ("read", TEXT, 1, 0)


def test_error_initialization_aliases_input_before_first_read():
    case = Case(b"ABCD\0")
    assert case.scan(error=TEXT) == 0
    assert case.events[1] == ("write", TEXT, 4, 0xFFFFFFFF)
    assert case.events[-1] == ("write", TEXT, 4, 0)


def test_aliased_outputs_follow_actual_failure_write_order():
    case = Case(b"A\x80\0")
    assert case.scan(error=COUNT) == 0
    assert case.memory.read(COUNT, 4) == 1
    assert [row for row in case.events if row[0] == "write"] == [
        ("write", COUNT, 4, 0),
        ("write", COUNT, 4, 0xFFFFFFFF),
        ("write", COUNT, 4, 1),
    ]


def test_null_optional_error_pointer_requires_no_backing():
    case = Case(b"\xff\0")
    assert case.scan(error=0) == 0
    assert case.events == [("write", COUNT, 4, 0), ("read", TEXT, 1, 255)]


def test_ascii_sample_and_current_lead_reread_are_distinct():
    case = Case(b"A\0")
    reads = 0

    def change(address, width, value):
        nonlocal reads
        if address == TEXT:
            reads += 1
            if reads == 1:
                case.memory.write(TEXT, 1, 0xC0)

    case.hook = change
    assert case.scan() == 1
    assert case.memory.read(COUNT, 4) == 1
    assert [row[3] for row in case.events if row[0] == "read"] == [65, 192, 0]


def test_multibyte_length_is_held_over_current_first_byte_reread():
    case = Case(b"\xe0\x80\x80\0")
    changed = False

    def change(address, width, value):
        nonlocal changed
        if address == TEXT and not changed:
            changed = True
            case.memory.write(TEXT, 1, 65)

    case.hook = change
    assert case.scan() == 1
    assert case.memory.read(COUNT, 4) == 1
    assert [row[3] for row in case.events if row[0] == "read"] == [224, 65, 128, 128, 0]


def test_missing_input_keeps_prior_output_effects():
    case = Case(b"A")
    with pytest.raises(ReplayMemoryError):
        case.scan()
    assert case.memory.read(COUNT, 4) == 0
    assert case.memory.read(ERROR, 4) == 0xFFFFFFFF


def test_bound_wrapper_uses_real_leaf_and_live_local_count():
    case = Case(b"Gaia\0")
    bound = bind_replay_player_name_validation(
        case.context,
        ReplayTaskRebuildCalls(None),
        bind_local=case.memory.bind_local,
        scratch=bytes([0xA5]) * 0x44,
    )
    assert bound.call(0x140A84390, (TEXT, ERROR), None) == 1
    count_writes = [row for row in case.events if row[0] == "write" and row[1] != ERROR]
    assert [(row[2], row[3]) for row in count_writes] == [(4, 0), (4, 4)]
    with pytest.raises(ReplayMemoryError):
        case.memory.read(count_writes[0][1], 4)


def test_direct_wrapper_preserves_actual_child_low_byte_and_arguments():
    case = Case(b"unused\0")
    seen = []

    def child(target, args, data):
        assert target == 0x140A830B0 and data is None
        assert args[0] == TEXT and args[2] == ERROR
        assert case.memory.read(args[1], 4) == 0xA5A5A5A5
        seen.append(args)
        return 7

    assert (
        validate_replay_player_name_bytes(
            case.context,
            TEXT,
            ERROR,
            calls=ReplayTaskRebuildCalls(child),
            bind_local=case.memory.bind_local,
            scratch=bytes([0xA5]) * 0x44,
        )
        == 7
    )
    assert len(seen) == 1


@pytest.mark.parametrize("scratch", [b"", bytes(0x43), bytes(0x45), bytearray(0x44)])
def test_wrapper_requires_explicit_exact_frame(scratch):
    case = Case(b"\0")
    with pytest.raises(ValueError, match="0x44-byte"):
        bind_replay_player_name_validation(
            case.context,
            ReplayTaskRebuildCalls(None),
            bind_local=case.memory.bind_local,
            scratch=scratch,
        )


def test_unknown_and_malformed_bound_calls_do_not_succeed():
    case = Case(b"\0")
    bound = bind_replay_player_name_validation(
        case.context,
        ReplayTaskRebuildCalls(None),
        bind_local=case.memory.bind_local,
        scratch=bytes(0x44),
    )
    with pytest.raises(UnresolvedReplayTaskRebuild):
        bound.call(0xABCDEF, (), None)
    with pytest.raises(ValueError):
        bound.call(0x140A830B0, (TEXT, COUNT), None)
    with pytest.raises(ValueError):
        bound.call(0x140A84390, (TEXT, ERROR), memoryview(bytearray()))
