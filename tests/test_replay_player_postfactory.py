"""Source-derived ordered reset cases; no native runtime or World claim."""

import pytest

from vantage.replay_memory import ReplayMemory
from vantage.replay_player_postfactory import (
    bind_replay_player_postfactory,
    reset_replay_player_postfactory,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)


def setup(fail=None):
    memory = ReplayMemory()
    subject = memory.allocate(0x520)
    memory.write_bytes(subject, b"S" * 0x520)
    stores = []

    def read(address, width):
        raise AssertionError("the reset has no memory load")

    def write(address, width, value):
        if len(stores) == fail:
            raise RuntimeError("provider frontier")
        stores.append((address - subject, width, value))
        memory.write(address, width, value)

    return memory, subject, stores, ReplayTaskRebuildStorage(subject, read, write)


def test_complete_sparse_reset_preserves_gaps_and_original_store_order():
    m, subject, stores, context = setup()
    reset_replay_player_postfactory(context, subject)
    assert len(stores) == 46
    assert sum(width for _, width, _ in stores) == 633
    assert stores[:5] == [
        (0x270, 8, (1 << 64) - 1),
        (0x27C, 2, 0xFFFF),
        (0x278, 4, 0xFFFFFFFF),
        (0x48C, 4, 0),
        (0x2A0, 8, 0),
    ]
    assert stores[5:35] == [(offset, 16, 0) for offset in range(0x2A8, 0x488, 16)]
    assert stores[35:42] == [(offset, 16, 0) for offset in range(0x491, 0x501, 16)]
    assert stores[42:] == [(0x501, 8, 0), (0x509, 4, 0), (0x50D, 2, 0), (0x50F, 1, 0)]
    assert m.read_bytes(subject + 0x270, 14) == b"\xff" * 14
    assert m.read_bytes(subject + 0x27E, 0x22) == b"S" * 0x22
    assert m.read_bytes(subject + 0x2A0, 0x1E8) == bytes(0x1E8)
    assert m.read_bytes(subject + 0x488, 4) == b"SSSS"
    assert m.read_bytes(subject + 0x48C, 4) == bytes(4)
    assert m.read_bytes(subject + 0x490, 1) == b"S"
    assert m.read_bytes(subject + 0x491, 0x7F) == bytes(0x7F)
    assert m.read_bytes(subject + 0x510, 16) == b"S" * 16


@pytest.mark.parametrize("fail", range(46))
def test_provider_failure_keeps_exact_preceding_stores(fail):
    _, original, stores, context = setup()
    reset_replay_player_postfactory(context, original)
    m, subject, partial, context = setup(fail)
    with pytest.raises(RuntimeError, match="provider frontier"):
        reset_replay_player_postfactory(context, subject)
    assert partial == stores[:fail]
    expected = bytearray(b"S" * 0x520)
    for offset, width, value in partial:
        expected[offset : offset + width] = value.to_bytes(width, "little")
    assert m.read_bytes(subject, 0x520) == expected


def test_binder_delegates_and_rejects_malformed_calls_before_mutation():
    _, subject, stores, context = setup()
    calls = bind_replay_player_postfactory(context, ReplayTaskRebuildCalls(None))
    assert calls.call
    with pytest.raises(ValueError, match="malformed"):
        calls.call(0x1417394D0, (), None)
    with pytest.raises(ValueError, match="malformed"):
        calls.call(0x1417394D0, (subject,), memoryview(b""))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        calls.call(0x123, (), None)
    assert stores == []
    assert calls.call(0x1417394D0, (subject,), None) is None
    assert len(stores) == 46
