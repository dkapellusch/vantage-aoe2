"""Source-led tail controls, drafted before any candidate implementation.

Every service is an explicitly authored caller-test capability. These are
not native observations or evidence that any descendant is implemented.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_world_update_control_flags import ReplayWorldUpdateControlFlags
from vantage.replay_world_update_player_links import (
    ReplayWorldUpdatePlayerLinks,
    run_replay_world_update_player_links,
)
from vantage.replay_world_update_player_pass import (
    ReplayWorldUpdatePlayerPass,
    run_replay_world_update_player_pass,
)
from vantage.replay_world_update_postpass import (
    ReplayWorldUpdatePostpass,
    run_replay_world_update_postpass,
)

U32, U64 = (1 << 32) - 1, (1 << 64) - 1
R13 = 0x61501AA6ECFD980A
X1, X2 = 0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1
Y2 = 0x6C5EAB60B426DD28
Z1, Z2 = 0x2B3719EF44DE99FF, 0x21D14A25ED7C802C
GLOBAL_MODE, GLOBAL_NEW, GLOBAL_OUTPUT, GLOBAL_STAMP = (
    0x1442C3FB4,
    0x144418584,
    0x144418588,
    0x144418590,
)
GLOBAL_RECORDS, GLOBAL_SENTINEL = 0x1442C3F90, 0x143DADE30
GLOBAL_BUFFER, GLOBAL_CONTEXT, GLOBAL_CONSTANT = 0x144419060, 0x144415600, 0x1436A03A0
IAT_CLOSE, IAT_WATSON, IAT_CONVERT = 0x14319A228, 0x14319A060, 0x143199CA0
V70, V140, V310, V20, V218 = 0xA070, 0xA140, 0xA310, 0xA020, 0xA218
CLOSE, WATSON, CONVERT = 0x10A228, 0x10A060, 0x109CA0
CHANNELS = (
    "calls",
    "virtual_calls",
    "cleanup_virtual_calls",
    "unit_fp_calls",
    "geometry_calls",
    "format_home_calls",
    "record_home_calls",
    "runtime_calls",
    "watson_home_calls",
)
Handler = Callable[[int, tuple[int, ...]], int | None]
Channel = Callable[[int, tuple[int, ...], memoryview | None], int | None]


class Rig:
    def __init__(self, count: int = 1, *, links: bool = False) -> None:
        self.memory = ReplayMemory(start=0x10000)
        self.events: list[tuple] = []
        self.after_read: Callable[[int, int], None] | None = None
        self.after_write: Callable[[int, int, int], None] | None = None
        self.handlers: dict[str, Handler] = {}
        self.world, self.frame = self.alloc(0xA00), self.alloc(0xE00)
        gap = self.alloc(0x100)
        self.memory.free(gap)  # Cookie/save traffic remains genuinely unbacked.
        self.table = self.alloc(0x150)
        self.put(self.world, 8, self.table)
        self.put(self.table + 0x70, 8, V70)
        self.put(self.table + 0x140, 8, V140)
        self.players = [self.player() for _ in range(count)]
        self.begin = self.array(self.players, stride=16)
        self.header(self.begin, count)
        self.manager, self.manager_service = self.alloc(0x2010), 0xC2008
        self.put(self.manager + 0x2008, 8, self.manager_service)
        self.put(self.world + 0x130, 8, self.manager)
        self.handle, self.clock = self.alloc(0x20), self.alloc(0x10)
        self.put(self.world + 0x70, 8, self.handle)
        self.put(self.world + 0x228, 8, self.clock)
        self.put(self.world + 0x88, 4, 0x15)
        self.put(self.world + 0x188, 4, 0)
        self.put(self.world + 0x7D0, 4, 0xFFFFFFFF)
        for offset, width in ((0x168, 8), (0x174, 4), (0x178, 8), (0x184, 4)):
            self.put(self.world + offset, width, 0)
        self.blocks = self.alloc(0x500)
        self.put(self.world + 0x800, 8, self.blocks)
        for offset in range(0, 0x500, 0x100):
            self.put(self.blocks + offset + 0xFB, 1, 0)
            self.put(self.blocks + offset + 0xF8, 2, 0)
        self.stream = self.alloc(0x40)
        self.put(self.stream, 1, 0)
        self.put(self.stream + 1, 1, 0)
        self.game = self.alloc(0x1260)
        for address, width, value in (
            (0x1442DA8A0, 8, 0xDA8A0),
            (GLOBAL_MODE, 4, 0),
            (GLOBAL_NEW, 4, 0),
            (GLOBAL_OUTPUT, 8, 0),
            (GLOBAL_STAMP, 4, 0),
            (GLOBAL_RECORDS, 8, 0xCF90),
            (GLOBAL_SENTINEL, 8, 0xDEADBEEF),
            (GLOBAL_CONTEXT, 8, self.game),
            (0x1443E4E20, 8, 0xE4E20),
            (IAT_CLOSE, 8, CLOSE),
            (IAT_WATSON, 8, WATSON),
            (IAT_CONVERT, 8, CONVERT),
            (GLOBAL_CONSTANT, 16, 15 << 64),
        ):
            self.memory.map_bytes(address, value.to_bytes(width, "little"))
        self.memory.map_bytes(GLOBAL_BUFFER, bytes([0xA5]) * 0x400)
        self.memory.map_bytes(0x1432EA988, bytes([0xA5]) * 0x28)
        self.put(0x1432EA988 + 0x20, 8, V20)
        self.clock_word = 0
        self.reader_rows: list[tuple[int, bytes, int]] = []
        self.scan_new, self.scan_max = 0, 0
        self.records: dict[int, int] = {}
        self.meta = (self.world, self.frame, 0x12345, 7, 9, 0x3F800001, 3)
        self.phase: ReplayWorldUpdatePlayerLinks | ReplayWorldUpdatePlayerPass
        if links:
            self.phase = ReplayWorldUpdatePlayerLinks(
                *self.meta,
                0,
                R13,
                0,
                None,
                None,
                None,
                None,
                0x14162AB9E,
                None,
            )
        else:
            self.phase = ReplayWorldUpdatePlayerPass(
                *self.meta,
                0,
                R13,
                count,
                0x447A0000,
                0x14162AB9E,
                None,
            )
        self.context = ReplayTaskRebuildStorage(self.world, self.read, self.write)
        self.channels = {key: ReplayTaskRebuildCalls(self.channel(key)) for key in CHANNELS}

    def alloc(self, size: int, fill: int = 0xA5) -> int:
        address = self.memory.allocate(size)
        self.memory.write_bytes(address, bytes([fill]) * size)
        return address

    def put(self, address: int, width: int, value: int) -> None:
        self.memory.write(address & U64, width, value & ((1 << (width * 8)) - 1))

    def get(self, address: int, width: int = 8) -> int:
        return self.memory.read(address & U64, width)

    def read(self, address: int, width: int) -> int:
        self.events.append(("read", address, width))
        value = self.get(address, width)
        if self.after_read:
            self.after_read(address, width)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.events.append(("write", address, width, value))
        self.put(address, width, value)
        if self.after_write:
            self.after_write(address, width, value)

    def array(self, values: list[int], stride: int = 8) -> int:
        address = self.alloc(max(1, len(values)) * stride)
        for index, value in enumerate(values):
            self.put(address + index * stride, 8, value)
        return address

    def header(self, begin: int, count: int) -> None:
        self.put(self.world + 0x768, 8, begin)
        self.put(self.world + 0x770, 8, begin + count * 16)

    def player(self) -> int:
        address, table = self.alloc(0x100), self.alloc(0x320)
        self.put(address, 8, table)
        self.put(table + 0x310, 8, V310)
        for offset in (0x40, 0x78, 0x80):
            self.put(address + offset, 8, address + 0x1000 + offset)
        self.put(address + 0x89, 1, 0)
        return address

    def channel(self, key: str) -> Channel:
        def invoke(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert data is None
            self.events.append(("call", key, target, args))
            handler = self.handlers.get(key)
            return handler(target, args) if handler else self.default(key, target, args)

        return invoke

    def default(self, key: str, target: int, args: tuple[int, ...]) -> int | None:
        # Finite, explicitly authored capabilities for these caller fixtures.
        # Every unlisted target fails; there is no generic successful service.
        if key == "calls":
            return self.scalar(target, args)
        if key == "virtual_calls":
            assert target in (V70, V140, V310)
            return None
        if key == "cleanup_virtual_calls":
            assert target == V20 and len(args) == 3 and args[2] == 0xFF
            return None
        if key == "unit_fp_calls":
            assert target == V218 and len(args) == 1
            return 0x7FC01234
        if key == "geometry_calls":
            assert (target, len(args)) in ((0x140B2D200, 5), (0x140B2D0F0, 4))
            return None
        if key == "format_home_calls":
            assert (target == 0x1410242D0 and len(args) == 5) or (
                target == 0x140F3EB40 and len(args) in (2, 3, 5)
            )
            return None
        if key == "record_home_calls":
            assert target == 0x140DD3E80 and len(args) == 11
            return None
        if key == "runtime_calls":
            assert (target, len(args)) in ((CLOSE, 1), (CONVERT, 4))
            return None
        if key == "watson_home_calls":
            assert target == WATSON and args[:4] == (0, 0, 0, 0) and len(args) == 5
            return None
        raise AssertionError((key, target, args))

    def scalar(self, target: int, args: tuple[int, ...]) -> int | None:
        ignored = {
            0x140F558A0,
            0x140F52130,
            0x140E07CC0,
            0x14114B470,
            0x141229A20,
            0x14115F240,
            0x1416938B0,
            0x140FDDBF0,
            0x140E27920,
            0x1409002E0,
            0x140A1B220,
            0x140990140,
            0x140DEE6B0,
            0x142D6BAB4,
            0x1402A88A0,
            0x140A1BA10,
            0x141581360,
            0x140B2D040,
            0x140DF2670,
        }
        if target in ignored:
            return None
        if target == 0x140903E40:
            assert args[:2] == (0x144353060, 0x14369A1D0)
            assert args[2] in (0x1191, 0x11D6)
            return 0x1122334400000005 if args[2] == 0x1191 else 0x5566778800000006
        if target == 0x141021E00:
            assert args == ()
            return 0xCA11
        if target == 0x140E68F70:
            assert args == (self.clock,)
            return self.clock_word
        if target == 0x140E15770:
            assert len(args) == 1
            return self.stream
        if target == 0x140B2CFF0:
            assert len(args) == 1
            return 0x64
        if target == 0x142D6E3B7:
            address, value, size = args
            assert value == 0 and size in (0x400, 0xB10)
            self.memory.write_bytes(address, bytes(size))
            return None
        if target == 0x142D6E44D:
            assert args == (GLOBAL_BUFFER,)
            return self.memory.c_string_length(GLOBAL_BUFFER)
        if target == 0x142D6E3B1:
            destination, source, size = args
            assert source == GLOBAL_BUFFER and size <= 0x400
            self.memory.write_bytes(destination, self.memory.read_bytes(source, size))
            return None
        if target == 0x1402A94D0:
            assert len(args) == 1 and 0 < args[0] <= 0x100
            return self.alloc(args[0])
        if target == 0x140DEC000:
            assert args == (self.stream, GLOBAL_BUFFER, self.frame + 0x2B0)
            assert self.reader_rows, "the fixture must declare its finite reader sequence"
            status, payload, flag = self.reader_rows.pop(0)
            assert len(payload) < 0x400
            self.memory.write_bytes(GLOBAL_BUFFER, payload + b"\0")
            self.put(args[2], 8, flag)
            return status
        if target == 0x141869660:
            assert args == (self.frame + 0x278, self.frame + 0x218, self.frame + 0x250)
            return 0
        if target == 0x140803EA0:
            assert args == (self.frame + 0x250,)
            return 0x10CA11
        if target == 0x140DD48B0:
            assert len(args) == 1
            return self.scan_new
        if target == 0x140DD48C0:
            assert len(args) == 1
            return self.scan_max
        if target == 0x140DD4880:
            assert len(args) == 2
            return self.records.get(args[1], 0)
        if target == 0x141869A90:
            assert args[0] == args[2] + 0x30 and args[1] == self.frame + 0x218
            self.put(args[1], 16, 0x78)
            self.put(args[1] + 0x10, 8, 1)
            self.put(args[1] + 0x18, 8, 15)
            return args[1]
        if target == 0x140808540:
            assert args == (0xE4E20, self.frame + 0x78)
            self.put(args[1], 8, 0)
            slot = self.alloc(8)
            self.put(slot, 8, 0x8500540)
            return slot
        if target == 0x141451610:
            assert args == (0x8500540, self.frame + 0x218, 0)
            slot = self.alloc(8)
            self.put(slot, 8, 0x451610)
            return slot
        if target == 0x141017300:
            assert args == (self.frame + 0x2C0, 0x143202350)
            return self.alloc(0x20)
        raise AssertionError((target, args))

    def run(self, **channels: ReplayTaskRebuildCalls) -> ReplayWorldUpdatePostpass:
        selected = dict(self.channels)
        selected.update(channels)
        calls = selected.pop("calls")
        return run_replay_world_update_postpass(self.context, calls, self.phase, **selected)

    def calls(self, key: str | None = None, target: int | None = None) -> list[tuple]:
        return [
            event
            for event in self.events
            if event[0] == "call"
            and (key is None or event[1] == key)
            and (target is None or event[2] == target)
        ]

    def block(self, index: int, identifiers: list[int], *, fp: bool = False) -> int:
        block = self.blocks + index * 0x100
        for i, identifier in enumerate(identifiers):
            self.put(block + 8 + i * 4, 4, identifier)
        self.put(block + 0xF8, 2, len(identifiers))
        self.put(block + 0xFA, 1, int(fp))
        self.put(block + 0xFB, 1, 1)
        return block

    def unit(self, x: int = 0x3F800000, y: int = 0x40000000, z: int = 0x40400000) -> int:
        address, table = self.alloc(0x200), self.alloc(0x220)
        self.put(address, 8, table)
        self.put(table + 0x218, 8, V218)
        self.put(address + 0x170, 8, x + X1 - X2)
        self.put(address + 0x178, 8, y + R13 - Y2)
        self.put(address + 0x180, 8, z - Z1 - Z2)
        return address

    def lookup(self, identifiers: dict[int, int]) -> None:
        for negative, pointer_offset, count_offset in (
            (False, 0x168, 0x174),
            (True, 0x178, 0x184),
        ):
            values = {abs(k): v for k, v in identifiers.items() if (k < 0) == negative}
            if values:
                count = max(values) + 1
                table = self.alloc(count * 8, fill=0)
                for index, value in values.items():
                    self.put(table + index * 8, 8, value)
                self.put(self.world + pointer_offset, 8, table)
                self.put(self.world + count_offset, 4, count)

    def read_mode(self, statuses: list[int], *, payload: bytes = b"abc") -> None:
        self.put(self.stream, 1, 0)
        self.put(self.stream + 1, 1, 1)
        self.reader_rows = [
            (status, payload if status & U32 == 1 else b"", i + 0x99)
            for i, status in enumerate(statuses)
        ]

    def scan_mode(self, new: int, old: int, records: dict[int, int]) -> None:
        self.put(self.stream, 1, 1)
        self.scan_new, self.scan_max = new & U32, max(records, default=0)
        self.put(GLOBAL_NEW, 4, old)
        self.records = records

    def record(self, kind: int) -> int:
        address = self.alloc(0x40)
        self.put(address + 0x30, 8, kind)
        return address


@pytest.mark.parametrize("links", [False, True])
def test_both_normal_arrivals_and_plain_logical_result(links: bool) -> None:
    rig = Rig(links=links)
    result = rig.run()
    assert isinstance(result, ReplayWorldUpdatePostpass)
    assert not hasattr(result, "__dict__")
    assert (
        result.world,
        result.logical_frame,
        result.entry_time,
        result.cycle,
        result.status,
        result.default_time,
        result.control_flags,
    ) == rig.meta
    assert result.next_address is None and result.returned_status == 0x15
    assert rig.events[0] == ("read", rig.world + 0x130, 8)
    assert not rig.calls(target=0x142D6C1C0)
    with pytest.raises(ReplayMemoryError):
        rig.get(rig.frame + 0xE00)
    assert not any(
        event[0] == "read" and rig.frame + 0xE00 <= event[1] < rig.frame + 0xE50
        for event in rig.events
    )
    assert rig.calls("calls", 0x1416938B0)[0][3] == (rig.world,)
    assert rig.calls("virtual_calls", V70)[0][3] == (rig.world,)
    assert rig.calls("format_home_calls", 0x1410242D0)[0][3] == (
        0xCA11,
        0,
        0x1432EA178,
        0x1432E98F0,
        rig.frame + 0x20,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("world", True),
        ("logical_frame", -1),
        ("held_r13", R13 ^ 1),
        ("held_r13", True),
        ("raw_count", 1 << 64),
        ("raw_count", False),
        ("outer_index", -1),
        ("outer_index", 1 << 32),
        ("xmm8_word", True),
        ("entry_time", -1),
        ("cycle", True),
        ("status", 1 << 32),
        ("default_time", False),
        ("control_flags", -1),
        ("next_address", 0x141629E00),
        ("next_address", 0x141629C90),
        ("next_address", 0x14162BA3C),
        ("next_address", 0x14162BA59),
        ("returned_status", 4),
    ],
)
def test_pass_admission_rejects_before_effects(field: str, value: int) -> None:
    rig = Rig()
    rig.phase = replace(rig.phase, **{field: value})
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outer_index", 1),
        ("raw_count", 1),
        ("held_begin", -1),
        ("xmm8_word", 1 << 32),
        ("inner_index", True),
        ("marker_address", -1),
    ],
)
def test_links_shortcut_domains_and_provenance(field: str, value: int) -> None:
    rig = Rig(links=True)
    rig.phase = replace(rig.phase, **{field: value})
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events == []


def test_links_nonzero_high_count_and_absent_observations_are_admitted() -> None:
    rig = Rig(links=True)
    rig.phase = replace(rig.phase, raw_count=1 << 32)
    assert rig.run().returned_status == 0x15
    assert rig.phase.held_begin is None and rig.phase.xmm8_word is None


@pytest.mark.parametrize("key", CHANNELS)
def test_wrong_channel_container_rejects_before_effects(key: str) -> None:
    rig = Rig()
    rig.channels[key] = None
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events == []


def test_wrong_nominal_phase_rejects_before_effects() -> None:
    rig = Rig()
    rig.phase = object()
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events == []


def test_gated_unavailable_channels_and_reached_first_refusal() -> None:
    rig = Rig()
    for key in CHANNELS:
        if key not in ("calls", "virtual_calls", "format_home_calls"):
            rig.channels[key] = ReplayTaskRebuildCalls(None)
    assert rig.run().returned_status == 0x15
    rig = Rig()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.run(calls=ReplayTaskRebuildCalls(None))
    assert rig.events == [("read", rig.world + 0x130, 8)]


@pytest.mark.parametrize("zero", ["world", "logical_frame"])
def test_zero_address_and_different_context_subject_are_admitted(zero: str) -> None:
    rig = Rig()
    address, size = (rig.world, 0xA00) if zero == "world" else (rig.frame, 0xE00)
    rig.memory.map_bytes(0, rig.memory.read_bytes(address, size))
    if zero == "world":
        rig.world = 0
    else:
        rig.frame = 0
    rig.phase = replace(rig.phase, **{zero: 0})
    rig.context = ReplayTaskRebuildStorage(0xFACE, rig.read, rig.write)
    result = rig.run()
    assert getattr(result, zero) == 0 and result.returned_status == 0x15


def test_initial_world_and_global_receivers_are_reread_and_returns_opaque() -> None:
    rig = Rig()
    replacement = rig.alloc(0x2010)
    rig.put(replacement + 0x2008, 8, 0xFEED)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140F558A0:
            assert args == (rig.manager,)
            rig.put(rig.world + 0x130, 8, replacement)
            return True
        if target == 0x140F52130:
            assert args == (replacement,)
            rig.put(0x1442DA8A0, 8, 0xBABE)
            return 1 << 100
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    assert rig.run().returned_status == 0x15
    assert rig.calls("calls", 0x140E07CC0)[0][3] == (0xBABE,)
    assert rig.calls("calls", 0x140E27920)[0][3] == (0xFEED, 6)


@pytest.mark.parametrize("count", [0, 1, 1 << 32, U64])
def test_first_postpass_full_unsigned_count_and_source_driven_exit(count: int) -> None:
    rig = Rig()
    rig.header(rig.begin, count)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x14114B470:
            rig.header(rig.begin, 0)
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    rig.run()
    calls = rig.calls("calls", 0x14114B470)
    assert len(calls) == int(count != 0)
    if calls:
        assert calls[0][3] == (rig.get(rig.players[0] + 0x80),)


def test_timing_words_use_low_eax_and_hold_first_sample() -> None:
    rig = Rig()
    rig.run()
    assert rig.calls("calls", 0x140FDDBF0)[0][3] == (5,)
    assert rig.get(rig.world + 0x7D0, 4) == 6
    assert rig.get(rig.world + 0x7D4, 4) == 0xA5A5A5A5


def test_first_postpass_resamples_current_rows_and_count() -> None:
    rig = Rig()
    second = rig.player()
    alternate = rig.array([0, second], stride=16)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x14114B470:
            if len(rig.calls("calls", target)) == 1:
                rig.header(alternate, 2)
            else:
                rig.header(alternate, 0)
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    rig.run()
    assert [call[3] for call in rig.calls("calls", 0x14114B470)] == [
        (rig.get(rig.players[0] + 0x80),),
        (rig.get(second + 0x80),),
    ]
    assert not rig.calls("calls", 0x141229A20)


def test_second_postpass_reads_end_before_begin_without_negative_clamp() -> None:
    rig = Rig()
    second = rig.player()
    alternate = rig.array([second], stride=16)
    armed = False

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal armed
        if target == 0x140903E40 and args[2] == 0x1191:
            armed = True
        if target == 0x141229A20:
            rig.header(alternate, 0)
        return rig.scalar(target, args)

    def after_read(address: int, width: int) -> None:
        nonlocal armed
        if armed and address == rig.world + 0x770:
            armed = False
            rig.put(rig.world + 0x768, 8, alternate)

    rig.handlers["calls"], rig.after_read = scalar, after_read
    rig.run()
    assert rig.calls("calls", 0x141229A20)[0][3] == (rig.get(second + 0x40),)


def test_third_postpass_starts_with_held_second_bound_headers() -> None:
    rig = Rig()
    alternate = rig.array([0], stride=16)
    armed = False

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal armed
        if target == 0x141229A20:
            armed = True
        return rig.scalar(target, args)

    def after_read(address: int, width: int) -> None:
        nonlocal armed
        if armed and address == rig.world + 0x768:
            armed = False
            rig.header(alternate, 0)

    rig.handlers["calls"], rig.after_read = scalar, after_read
    rig.run()
    assert rig.calls("calls", 0x14115F240)[0][3] == (rig.get(rig.players[0] + 0x78),)


@pytest.mark.parametrize("index", [0, 1, U32, 0x80000000])
def test_round_robin_indexed_store_precedes_any_range_check(index: int) -> None:
    rig = Rig()
    rig.put(rig.world + 0x188, 4, index)
    signed = index if index < 1 << 31 else index - (1 << 32)
    destination = (rig.world + 0x18C + 4 * signed) & U64
    if index == 0x80000000:
        rig.memory.map_bytes(destination, bytes([0xA5]) * 4)
    rig.run()
    own_stores = [event for event in rig.events if event[0] == "write"]
    assert own_stores[0] == ("write", destination, 4, 0)
    assert rig.get(rig.world + 0x188, 4) == (0x80000001 if index == 0x80000000 else 0)


def test_round_robin_increment_reads_current_value_after_alias_store() -> None:
    rig = Rig()
    rig.put(rig.world + 0x188, 4, U32)
    fired = False

    def after_write(address: int, width: int, value: int) -> None:
        nonlocal fired
        if not fired and address == rig.world + 0x188 and value == 0:
            fired = True
            rig.put(address, 4, 0xFFFFFFFE)

    rig.after_write = after_write
    rig.run()
    assert fired and rig.get(rig.world + 0x188, 4) == U32


def test_round_robin_count_comparison_is_signed_low_dword() -> None:
    rig = Rig()

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140FDDBF0:
            rig.header(rig.begin, U64)
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    rig.run()
    assert rig.get(rig.world + 0x188, 4) == 0


@pytest.mark.parametrize("invalid", [None, True, -1, 1 << 64])
def test_logger_return_is_consumed_after_home_write(invalid: int | None) -> None:
    rig = Rig()

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        return invalid if target == 0x141021E00 else rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events[-1] == ("write", rig.frame + 0x20, 4, 0x11D7)
    assert not rig.calls("format_home_calls")


def test_manager_receiver_and_timing_reads_keep_original_order() -> None:
    rig = Rig()
    other = rig.alloc(0x2010)
    rig.put(other + 0x2008, 8, 0xBAD)
    armed = False

    def home_call(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal armed
        assert target == 0x1410242D0
        armed = True
        return None

    def after_read(address: int, width: int) -> None:
        if armed and address == rig.world + 0x130:
            rig.put(rig.world + 0x130, 8, other)
            rig.put(rig.world + 0x7D0, 4, 0xABC)
        if armed and address == rig.world + 0x7D0:
            rig.put(rig.manager + 0x2008, 8, 0x12345678)

    rig.handlers["format_home_calls"], rig.after_read = home_call, after_read
    rig.run()
    assert rig.calls("calls", 0x140E27920)[0][3] == (0x12345678, 0xABC)


def test_all_three_postpasses_skip_actual_null_rows() -> None:
    rig = Rig(3)
    rig.put(rig.begin, 8, 0)
    rig.put(rig.begin + 32, 8, 0)
    rig.run()
    for target, offset in ((0x14114B470, 0x80), (0x141229A20, 0x40), (0x14115F240, 0x78)):
        assert [call[3] for call in rig.calls("calls", target)] == [
            (rig.get(rig.players[1] + offset),),
        ]


@pytest.mark.parametrize(
    (
        "mode",
        "state",
        "stamp",
        "clock",
        "output",
        "create",
        "format_",
        "close",
    ),
    [
        (0, 0x15, 0, 0, 0, False, False, False),
        (2, 0x15, 0, 0, 0, False, False, False),
        (1, 0x15, 0, 0, 0, True, True, False),
        (1, 0x15, 1, 1, 0, False, False, False),
        (1, 0x15, 1, 30001, 0, False, False, False),
        (1, 0x15, 1, 30002, 0, True, True, False),
        (1, 0x15, U32, 0, 0, False, False, False),
        (1, 0x15, 0xFFFFFF00, 0x7500, 0, True, True, False),
        (1, 0x15, 0, 0, 0xEE, False, True, False),
        (1, 1, 0, 0, 0, False, False, False),
        (1, 1, 0, 0, 0xEE, False, False, True),
        (0, 1, 0, 0, 0xEE, False, False, False),
    ],
)
def test_optional_output_gates_use_unsigned_elapsed_and_current_fields(
    mode: int,
    state: int,
    stamp: int,
    clock: int,
    output: int,
    create: bool,
    format_: bool,
    close: bool,
) -> None:
    rig = Rig()
    rig.put(GLOBAL_MODE, 4, mode)
    rig.put(rig.world + 0x88, 4, state)
    rig.put(GLOBAL_STAMP, 4, stamp)
    rig.put(GLOBAL_OUTPUT, 8, output)
    rig.clock_word = clock
    assert rig.run().returned_status == state
    assert bool(rig.calls("calls", 0x141017300)) == create
    formatting = rig.calls("virtual_calls", V140) + [
        event for event in rig.calls("format_home_calls", 0x140F3EB40) if len(event[3]) == 5
    ]
    assert bool(formatting) == format_
    if stamp == 0 and format_:
        assert rig.calls("virtual_calls", V140)[0][3] == (
            rig.world,
            rig.get(GLOBAL_OUTPUT),
            1,
        )
    assert bool(rig.calls("runtime_calls", CLOSE)) == close


@pytest.mark.parametrize("invalid", [None, True, -1, 1 << 64])
def test_optional_clock_consumer_follows_current_stamp_read(invalid: int | None) -> None:
    rig = Rig()
    rig.put(GLOBAL_MODE, 4, 1)
    rig.put(GLOBAL_STAMP, 4, 1)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        return invalid if target == 0x140E68F70 else rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events[-1] == ("read", GLOBAL_STAMP, 4)
    assert not rig.calls("calls", 0x140808540)


def test_optional_constructor_uses_actual_slots_and_current_strong_out() -> None:
    rig = Rig()
    rig.put(GLOBAL_MODE, 4, 1)
    first, second = rig.alloc(8), rig.alloc(8)
    strong1, strong2 = rig.alloc(0x20), rig.alloc(0x20)
    rig.put(first, 8, 0xBEEF)
    rig.put(second, 8, 0xCAFE)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140808540:
            assert args == (0xE4E20, rig.frame + 0x78)
            assert rig.get(rig.frame + 0x78) == 0xA5A5A5A5A5A5A5A5
            rig.put(rig.frame + 0x78, 8, strong1)
            return first
        if target == 0x141451610:
            assert args == (0xBEEF, rig.frame + 0x218, 0)
            return second
        if target == 0x140A1B220:
            assert args == (rig.frame + 0x218,)
            rig.put(rig.frame + 0x78, 8, strong2)
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    rig.run()
    assert rig.calls("calls", 0x1409002E0)[0][3] == (
        rig.frame + 0x2C0,
        0x1432EA220,
        0xCAFE,
    )
    assert rig.calls("calls", 0x140990140)[0][3] == (strong2,)


def test_null_constructed_output_publishes_before_held_test_and_returns_early() -> None:
    rig = Rig()
    rig.put(GLOBAL_MODE, 4, 1)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        return 0 if target == 0x141017300 else rig.scalar(target, args)

    def after_write(address: int, width: int, value: int) -> None:
        if address == GLOBAL_OUTPUT and width == 8 and value == 0:
            rig.put(GLOBAL_OUTPUT, 8, 0xDEAD)
            rig.put(rig.world + 0x88, 4, 0x77)

    rig.handlers["calls"], rig.after_write = scalar, after_write
    result = rig.run()
    assert result.returned_status == 0x77 and rig.get(GLOBAL_OUTPUT) == 0xDEAD
    assert len(rig.calls("calls", 0x140E68F70)) == 1
    assert not rig.calls("calls", 0x140E15770)
    assert not rig.calls("virtual_calls", V140)


@pytest.mark.parametrize("milliseconds", [0, 59999, 60000, 3599999, 3600000, U32])
def test_formatting_quotients_and_final_clock_increment(milliseconds: int) -> None:
    rig = Rig()
    rig.put(GLOBAL_MODE, 4, 1)
    rig.put(GLOBAL_STAMP, 4, 1)
    rig.put(GLOBAL_OUTPUT, 8, 0xEE)
    rig.clock_word = 0x1234567800000000 | milliseconds
    observed = []

    def home_call(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140F3EB40:
            observed.append((args, rig.get(args[4], 4), rig.get(args[4] + 4, 4)))
        return rig.default("format_home_calls", target, args)

    rig.handlers["format_home_calls"] = home_call
    rig.run()
    assert observed == [
        (
            (
                0xEE,
                0x1432EA230,
                milliseconds // 3600000,
                milliseconds // 60000 % 60,
                rig.frame + 0x20,
            ),
            milliseconds // 1000 % 60,
            0xA5A5A5A5,
        )
    ]
    assert rig.get(GLOBAL_STAMP, 4) == (milliseconds + 1) & U32


def test_player310_target_is_held_before_fresh_output_and_stamp() -> None:
    rig = Rig(3)
    rig.put(GLOBAL_MODE, 4, 1)
    rig.put(GLOBAL_OUTPUT, 8, 0xEE)
    rig.put(rig.begin + 32, 8, 0)
    player = rig.players[1]
    table, new_table = rig.get(player), rig.alloc(0x320)
    rig.put(new_table + 0x310, 8, 0xBAD)
    fired = False

    def after_read(address: int, width: int) -> None:
        nonlocal fired
        if not fired and address == table + 0x310:
            fired = True
            rig.put(player, 8, new_table)
            rig.put(table + 0x310, 8, 0xBAD)
            rig.put(GLOBAL_OUTPUT, 8, 0xBEE)
            rig.put(GLOBAL_STAMP, 4, U32)

    rig.after_read = after_read
    rig.run()
    assert fired
    assert rig.calls("virtual_calls", V310)[0][3] == (player, 0xBEE, 0)
    assert len(rig.calls("virtual_calls", V310)) == 1


@pytest.mark.parametrize("flag", [0, 1, 2, 0xFF])
def test_close_player_literal_uses_exact_current_byte_equality(flag: int) -> None:
    rig = Rig(3)
    rig.put(GLOBAL_MODE, 4, 1)
    rig.put(rig.world + 0x88, 4, 1)
    rig.put(GLOBAL_OUTPUT, 8, 0xEE)
    rig.put(rig.players[1] + 0x89, 1, flag)
    rig.put(rig.players[2] + 0x89, 1, 1)
    rig.run()
    assert [call[3] for call in rig.calls("format_home_calls", 0x140F3EB40)] == [
        (0xEE, 0x1432EA260),
        (0xEE, 0x1432EA270 if flag == 1 else 0x1432EA288, 1),
        (0xEE, 0x1432EA270, 2),
    ]
    assert not rig.calls("calls", 0x140E68F70)
    assert rig.get(GLOBAL_OUTPUT) == 0


@pytest.mark.parametrize("refuse", [False, True])
def test_close_uses_current_iat_and_clears_only_after_normal_return(refuse: bool) -> None:
    rig = Rig()
    rig.put(GLOBAL_MODE, 4, 1)
    rig.put(rig.world + 0x88, 4, 1)
    rig.put(GLOBAL_OUTPUT, 8, 0xEE)
    armed = False

    def home_call(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal armed
        if target == 0x140F3EB40 and args == (0xEE, 0x1432EA260):
            armed = True
        return rig.default("format_home_calls", target, args)

    def after_read(address: int, width: int) -> None:
        nonlocal armed
        if armed and address == GLOBAL_OUTPUT:
            armed = False
            rig.put(GLOBAL_OUTPUT, 8, 0xBB)
            rig.put(IAT_CLOSE, 8, 0x140F558A0)

    def runtime_call(target: int, args: tuple[int, ...]) -> int | None:
        assert target == 0x140F558A0 and args == (0xEE,)
        rig.put(GLOBAL_OUTPUT, 8, 0xCC)
        if refuse:
            raise UnresolvedReplayTaskRebuild("explicit close refusal")
        return 1 << 100

    rig.handlers["format_home_calls"] = home_call
    rig.handlers["runtime_calls"] = runtime_call
    rig.after_read = after_read
    if refuse:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="explicit close refusal"):
            rig.run()
        assert rig.get(GLOBAL_OUTPUT) == 0xCC
        assert not any(event[:3] == ("write", GLOBAL_OUTPUT, 8) for event in rig.events)
    else:
        assert rig.run().returned_status == 1
        assert rig.get(GLOBAL_OUTPUT) == 0
    assert len(rig.calls("runtime_calls", 0x140F558A0)) == 1


@pytest.mark.parametrize("status", [0, 2, 4, U32, 0x1234567800000000, 0xFEDCBA9800000004])
def test_reader_status_uses_whole_low_eax_and_distinct_return_paths(status: int) -> None:
    rig = Rig()
    rig.read_mode([status])
    result = rig.run()
    low = status & U32
    assert result.returned_status == (4 if low in (0, 2) else 0x15)
    assert bool(rig.calls("calls", 0x140DF2670)) == (low == 0)
    assert bool(rig.calls("runtime_calls", CONVERT)) == (low == 2)
    assert not rig.calls("calls", 0x141869660)


@pytest.mark.parametrize("unknown", [3, 5, 0x80000000, 0x1122334400000003])
def test_unknown_reader_status_retries_with_fresh_preparation(unknown: int) -> None:
    rig = Rig()
    rig.read_mode([unknown, 0])
    observed = []

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140DEC000:
            observed.append((rig.get(args[2]), rig.memory.read_bytes(GLOBAL_BUFFER, 0x400)))
            value = rig.scalar(target, args)
            rig.put(GLOBAL_SENTINEL, 8, 0x12345678)
            return value
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    assert rig.run().returned_status == 4
    assert observed == [(0xDEADBEEF, bytes(0x400)), (0x12345678, bytes(0x400))]
    assert len(rig.calls("calls", 0x140DEC000)) == 2


def test_stream_gates_use_two_actual_fresh_results() -> None:
    rig = Rig()
    first, second = rig.alloc(2), rig.alloc(2)
    rig.put(first, 1, 0)
    rig.put(first + 1, 1, 0xFF)
    rig.put(second + 1, 1, 0)
    seen = 0

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal seen
        if target == 0x140E15770:
            seen += 1
            return first if seen == 1 else second
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    assert rig.run().returned_status == 0x15
    assert seen == 2 and not rig.calls("calls", 0x140DEC000)


@pytest.mark.parametrize("refuse", [False, True])
def test_shared_stop_uses_fresh_accessor_and_returns_four_after_real_call(refuse: bool) -> None:
    rig = Rig()
    rig.read_mode([0])
    replacement = rig.alloc(0x20)
    shared_start = 0

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal shared_start
        if target == 0x140DEC000:
            value = rig.scalar(target, args)
            rig.put(rig.world + 0x70, 8, 0x7070)
            return value
        if target == 0x140E15770 and args == (0x7070,):
            return replacement
        if target == 0x140DF2670:
            assert args == (replacement,)
            shared_start = len(rig.events)
            rig.put(rig.world + 0x88, 4, 0xABC)
            if refuse:
                raise UnresolvedReplayTaskRebuild("explicit stop refusal")
            return 1 << 100
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    if refuse:
        with pytest.raises(UnresolvedReplayTaskRebuild, match="explicit stop refusal"):
            rig.run()
    else:
        assert rig.run().returned_status == 4
    assert rig.get(rig.world + 0x88, 4) == 0xABC
    assert not any(
        event[:3] == ("read", rig.world + 0x88, 4) for event in rig.events[shared_start:]
    )


@pytest.mark.parametrize("invalid", [None, True, -1, 1 << 64])
def test_reader_scalar_status_annotation_is_required_at_first_compare(invalid: int | None) -> None:
    rig = Rig()
    rig.read_mode([0])

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        return invalid if target == 0x140DEC000 else rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events[-1][0:3] == ("call", "calls", 0x140DEC000)
    assert rig.get(rig.frame + 0x278) == 0xA5A5A5A5A5A5A5A5


@pytest.mark.parametrize("length", [0, 15, 16, 22, 23])
def test_parser_string_small_and_heap_paths_publish_before_copy(length: int) -> None:
    rig = Rig()
    rig.read_mode([1, 0], payload=b"x" * length)
    observed = []

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x142D6E3B1:
            observed.append(
                (
                    args,
                    rig.get(rig.frame + 0x218),
                    rig.get(rig.frame + 0x228),
                    rig.get(rig.frame + 0x230),
                )
            )
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    assert rig.run().returned_status == 4
    assert len(observed) == 1
    args, pointer, size, capacity = observed[0]
    expected_capacity = 15 if length <= 15 else max(length | 15, 22)
    assert size == length and capacity == expected_capacity
    destination = rig.frame + 0x218 if length <= 15 else pointer
    assert args == (destination, GLOBAL_BUFFER, length)
    assert rig.memory.read_bytes(destination + length, 1) == b"\0"
    assert bool(rig.calls("calls", 0x1402A94D0)) == (length > 15)
    if length > 15:
        assert rig.calls("calls", 0x1402A94D0)[0][3] == (expected_capacity + 1,)


@pytest.mark.parametrize("length", [0x7FFFFFFFFFFFFFF0, 0x7FFFFFFFFFFFFFFF])
def test_huge_admitted_length_stops_at_exact_unavailable_allocation(length: int) -> None:
    rig = Rig()
    rig.read_mode([1])
    observed = []

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x142D6E44D:
            return length
        if target == 0x1402A94D0:
            observed.append(args)
            raise UnresolvedReplayTaskRebuild("large allocation unavailable")
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(UnresolvedReplayTaskRebuild, match="large allocation unavailable"):
        rig.run()
    assert observed == [(0x8000000000000000,)]
    assert not rig.calls("calls", 0x142D6E3B1)
    assert not rig.calls("calls", 0x141869660)


def test_finite_copy_refusal_preserves_actual_allocation_header() -> None:
    rig = Rig()
    rig.read_mode([1], payload=b"x" * 16)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x142D6E3B1:
            assert args[1:] == (GLOBAL_BUFFER, 16)
            assert rig.get(rig.frame + 0x218) == args[0]
            assert rig.get(rig.frame + 0x228) == 16
            assert rig.get(rig.frame + 0x230) == 31
            assert rig.memory.read_bytes(args[0], 32) == bytes([0xA5]) * 32
            raise UnresolvedReplayTaskRebuild("copy unavailable")
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(UnresolvedReplayTaskRebuild, match="copy unavailable"):
        rig.run()
    assert not rig.calls("calls", 0x141869660)


def test_over_max_length_invokes_error_child_then_reaches_source_trap() -> None:
    rig = Rig()
    rig.read_mode([1])

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x142D6E44D:
            return 0x8000000000000000
        if target == 0x1402A91E0:
            assert args == ()
            return None
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.run()
    assert rig.events[-1][0:3] == ("call", "calls", 0x1402A91E0)
    assert not rig.calls("calls", 0x1402A94D0)
    assert not rig.calls("calls", 0x141869660)


@pytest.mark.parametrize("target", [0x14114B470, 0x14115F240])
def test_first_and_third_bottoms_sample_begin_before_end(target: int) -> None:
    rig = Rig(2)
    armed = False

    def scalar(address: int, args: tuple[int, ...]) -> int | None:
        nonlocal armed
        if address == target:
            armed = True
        return rig.scalar(address, args)

    def after_read(address: int, width: int) -> None:
        nonlocal armed
        if armed and address == rig.world + 0x768:
            armed = False
            rig.put(rig.world + 0x770, 8, rig.begin + 16)

    rig.handlers["calls"], rig.after_read = scalar, after_read
    rig.run()
    assert len(rig.calls("calls", target)) == 1


def test_status_one_exact_initialization_precedes_length_and_holds_constant() -> None:
    rig = Rig()
    rig.read_mode([1, 0])
    constant = 15 << 64

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x142D6E44D:
            assert rig.events[-10:-1] == [
                ("write", rig.frame + offset, width, value)
                for offset, width, value in (
                    (0x278, 8, U64),
                    (0x288, 16, 0),
                    (0x298, 16, constant),
                    (0x288, 1, 0),
                    (0x250, 16, 0),
                    (0x260, 16, constant),
                    (0x250, 1, 0),
                    (0x218, 16, 0),
                    (0x228, 16, 0),
                )
            ]
            assert rig.get(rig.frame + 0x2AC, 1) == 0xA5
            rig.put(GLOBAL_CONSTANT, 16, 0x99887766)
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    assert rig.run().returned_status == 4
    assert rig.get(rig.frame + 0x228, 16) == constant
    assert rig.get(rig.frame + 0x260, 16) == constant
    assert sum(event[:3] == ("read", GLOBAL_CONSTANT, 16) for event in rig.events) == 1


@pytest.mark.parametrize("invalid", [None, True, -1, 0x100])
def test_parser_al_validation_precedes_current_cleanup(invalid: int | None) -> None:
    rig = Rig()
    rig.read_mode([1])

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x141869660:
            rig.put(rig.frame + 0x230, 8, 0xBAD)
            return invalid
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events[-1][0:3] == ("call", "calls", 0x141869660)
    assert rig.get(rig.frame + 0x230) == 0xBAD


@pytest.mark.parametrize(
    ("al", "capacity", "flag"), [(0, 16, 0xFF), (0x64, 15, 0xFE), (0x64, 16, 0xFF)]
)
def test_record_dispatch_uses_live_homes_partial_stores_and_parser_byte(
    al: int,
    capacity: int,
    flag: int,
) -> None:
    rig = Rig()
    rig.read_mode([1, 0])
    heap = rig.alloc(0x20)
    dispatched = False

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x141869660:
            rig.put(rig.frame + 0x2AC, 1, flag)
            rig.put(rig.frame + 0x268, 8, capacity)
            rig.put(rig.frame + 0x250, 8, heap)
            rig.put(GLOBAL_RECORDS, 8, 0xBEEF)
            return al
        return rig.scalar(target, args)

    def after_read(address: int, width: int) -> None:
        if address == rig.frame + 0x2B0:
            rig.put(address, width, 0xBBB)
        if not al and not dispatched:
            assert address not in (rig.frame + 0x2AC, rig.frame + 0x250)

    def record(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal dispatched
        dispatched = True
        expected_data = GLOBAL_BUFFER if al == 0 else (heap if capacity > 15 else rig.frame + 0x250)
        assert target == 0x140DD3E80
        assert args == (
            0xBEEF,
            0,
            expected_data,
            rig.frame + 0x78,
            *(rig.frame + offset for offset in (0x20, 0x28, 0x30, 0x38, 0x40, 0x48, 0x50)),
        )
        assert rig.get(rig.frame + 0x78) == 0x99
        for offset, value in ((0x20, 0), (0x28, 1), (0x30, 0), (0x38, 0)):
            assert rig.get(rig.frame + offset) == 0xA5A5A5A500000000 | value
        assert rig.get(rig.frame + 0x40) == 0xA5A5A5A5A5A5A500 | (flag & 1 if al else 0)
        assert rig.get(rig.frame + 0x48) == (rig.frame + 0x278 if al else 0)
        assert rig.get(rig.frame + 0x50) == 0xA5A5A5A5A5A5A500
        rig.put(args[-1], 8, 0x1122334455667788)
        return 1 << 100

    rig.handlers["calls"], rig.handlers["record_home_calls"] = scalar, record
    rig.after_read = after_read
    assert rig.run().returned_status == 4
    assert dispatched and rig.get(rig.frame + 0x50) == 0x1122334455667788
    if capacity > 15:
        assert rig.calls("calls", 0x142D6BAB4)[0][3] == (heap, 17)
    else:
        assert not rig.calls("calls", 0x142D6BAB4)


def test_true_parser_cmova_reads_unselected_memory_operand_after_initialization() -> None:
    rig = Rig()
    rig.read_mode([1])
    armed = False

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal armed
        if target == 0x141869660:
            armed = True
            return 0x64
        return rig.scalar(target, args)

    def after_read(address: int, width: int) -> None:
        if armed and address == rig.frame + 0x250 and width == 8:
            raise UnresolvedReplayTaskRebuild("explicit current CMOVA read refusal")

    rig.handlers["calls"], rig.after_read = scalar, after_read
    with pytest.raises(UnresolvedReplayTaskRebuild, match="current CMOVA read refusal"):
        rig.run()
    assert rig.get(rig.frame + 0x78) == 0x99
    assert rig.get(rig.frame + 0x50, 1) == 0
    assert rig.get(rig.frame + 0x48) == 0xA5A5A5A5A5A5A5A5
    assert not rig.calls("record_home_calls")


@pytest.mark.parametrize("which", ["first", "second"])
def test_returning_reader_watson_callbacks_continue_to_message(which: str) -> None:
    rig = Rig()
    rig.read_mode([1])
    payload, allocation = rig.alloc(0x40) + 8, rig.alloc(0x20)
    rig.put(payload - 8, 8, allocation)
    observed = []

    def bad_header(offset: int) -> None:
        rig.put(rig.frame + offset, 8, payload)
        rig.put(rig.frame + offset + 0x18, 8, 0xFFF)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x141869660:
            if which == "first":
                bad_header(0x218)
            return 0
        if target == 0x140A1BA10:
            assert rig.get(rig.frame + 0x240) == (3 if which == "first" else 0)
            assert rig.get(rig.frame + 0x248) == (3 if which == "first" else 0)
        return rig.scalar(target, args)

    def record(target: int, args: tuple[int, ...]) -> int | None:
        assert which == "second"
        bad_header(0x250)
        return None

    def watson(target: int, args: tuple[int, ...]) -> int | None:
        assert target == (WATSON if not observed else 0x140F558A0)
        assert args == (0, 0, 0, 0, rig.frame + 0x20)
        observed.append(rig.get(args[-1]))
        rig.put(IAT_WATSON, 8, 0x140F558A0)
        return None

    rig.handlers.update(calls=scalar, record_home_calls=record, watson_home_calls=watson)
    assert rig.run().returned_status == 4
    assert observed == ([0, 3] if which == "first" else [0])
    assert bool(rig.calls("record_home_calls")) == (which == "second")
    assert rig.get(rig.game + 0x1252, 1) == 1


@pytest.mark.parametrize(
    ("target", "last_offset", "last_width", "last_value"),
    [
        (0x140E68F70, 0x80, 4, 7),
        (0x140803EA0, 0x220, 4, 15),
    ],
)
@pytest.mark.parametrize("invalid", [None, True, -1, 1 << 64])
def test_message_annotations_validate_after_source_prefix(
    target: int,
    last_offset: int,
    last_width: int,
    last_value: int,
    invalid: int | None,
) -> None:
    rig = Rig()
    rig.read_mode([2])

    def scalar(address: int, args: tuple[int, ...]) -> int | None:
        return invalid if address == target else rig.scalar(address, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events[-1] == ("write", rig.frame + last_offset, last_width, last_value)


@pytest.mark.parametrize("holder_kind", ["default", "null", "replacement"])
@pytest.mark.parametrize("refuse_cleanup", [False, True])
def test_message_partial_flags_current_holder_and_fresh_context_marker(
    holder_kind: str,
    refuse_cleanup: bool,
) -> None:
    rig = Rig()
    rig.read_mode([2])
    new_game = rig.alloc(0x1260)
    holder, table = rig.alloc(8), rig.alloc(0x28)
    rig.put(holder, 8, table)
    rig.put(table + 0x20, 8, V20)
    cleanup_seen = False
    message_start = 0

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal message_start
        if target == 0x140A1BA10:
            assert args == (rig.frame + 0x238, 0x1432EA160, 2, rig.frame + 0x250)
            assert rig.get(rig.frame + 0x238) == 0x14428BB30
            assert rig.get(rig.frame + 0x240) == rig.get(rig.frame + 0x248) == 0
            assert rig.get(rig.frame + 0x250) == rig.frame + 0x218
            assert rig.get(rig.frame + 0x258) == rig.frame + 0x78
        if target == 0x141581360:
            message_start = len(rig.events)
            assert args == (rig.game, rig.frame + 0x238, rig.frame + 0x1C0, 0xA5A5A50100000001)
            if holder_kind != "default":
                rig.put(rig.frame + 0x1F8, 8, holder if holder_kind == "replacement" else 0)
            rig.put(GLOBAL_CONTEXT, 8, new_game)
        return rig.scalar(target, args)

    def cleanup(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal cleanup_seen
        cleanup_seen = True
        expected = rig.frame + 0x1C0 if holder_kind == "default" else holder
        assert (target, args) == (V20, (expected, int(holder_kind != "default"), 0xFF))
        rig.put(rig.world + 0x88, 4, 0xFEED)
        if refuse_cleanup:
            raise UnresolvedReplayTaskRebuild("message holder cleanup unavailable")
        return True

    rig.handlers.update(calls=scalar, cleanup_virtual_calls=cleanup)
    if refuse_cleanup and holder_kind != "null":
        with pytest.raises(UnresolvedReplayTaskRebuild, match="message holder cleanup unavailable"):
            rig.run()
        assert rig.get(new_game + 0x1252, 1) == 0xA5
    else:
        assert rig.run().returned_status == 4
        assert rig.get(new_game + 0x1252, 1) == 1
    assert cleanup_seen == (holder_kind != "null")
    assert rig.get(rig.game + 0x1252, 1) == 0xA5
    assert not any(
        event[:3] == ("read", rig.world + 0x88, 4) for event in rig.events[message_start:]
    )


def test_equal_record_indices_skip_constant_and_publication() -> None:
    rig = Rig()
    rig.scan_mode(0x80000000, 0x80000000, {})
    rig.run()
    assert not rig.calls("calls", 0x140DD4880)
    assert not any(event[:2] == ("read", GLOBAL_CONSTANT) for event in rig.events)
    assert not any(event[:2] == ("write", GLOBAL_NEW) for event in rig.events)


def test_wrapped_scan_uses_fresh_signed_maximum_then_publishes_held_new() -> None:
    rig = Rig()
    rig.scan_mode(1, 5, {})
    maxima = [6, 7, 7]

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140DD48B0:
            return 0xFEDCBA9800000001
        if target == 0x140DD48C0:
            assert args == (0xCF90,)
            return maxima.pop(0)
        if target == 0x140DD4880:
            assert args[0] == 0xCF90
            rig.put(GLOBAL_NEW, 4, 0x777)
            return 0
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    rig.run()
    assert not maxima
    assert [call[3][1] for call in rig.calls("calls", 0x140DD4880)] == [6, 7, 0, 1]
    assert [event[3] for event in rig.events if event[:3] == ("write", GLOBAL_NEW, 4)] == [U32, 1]
    assert rig.get(GLOBAL_NEW, 4) == 1


@pytest.mark.parametrize(
    ("new", "old", "expected"),
    [
        (0x80000000, 0x7FFFFFFF, [0x80000000]),
        (0x7FFFFFFF, 0x80000000, [0x80000001]),
    ],
)
def test_scan_indices_compare_signed_and_keep_raw_dword_arguments(
    new: int,
    old: int,
    expected: list[int],
) -> None:
    rig = Rig()
    rig.scan_mode(new, old, {})

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140DD48C0:
            return 0x80000000
        if target == 0x140DD4880:
            assert args[1] == expected[0]
            # The source admits a vast signed range; stop at a real child.
            raise UnresolvedReplayTaskRebuild("explicit wide scan boundary")
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(UnresolvedReplayTaskRebuild, match="wide scan boundary"):
        rig.run()
    assert [call[3][1] for call in rig.calls("calls", 0x140DD4880)] == expected


@pytest.mark.parametrize("old_range", [False, True])
@pytest.mark.parametrize(
    ("kind", "sentinel", "send"),
    [
        (0, 0xDEADBEEF, True),
        (8, 0xDEADBEEF, True),
        (9, 0xDEADBEEF, False),
        (U64, 0xDEADBEEF, False),
        (5, 5, False),
    ],
)
def test_record_kind_is_held_before_fresh_sentinel_then_compared_unsigned(
    old_range: bool,
    kind: int,
    sentinel: int,
    send: bool,
) -> None:
    rig = Rig()
    record = rig.record(kind)
    index = 6 if old_range else 1
    rig.scan_mode(0 if old_range else 1, 5 if old_range else 0, {index: record})
    sampled = False

    def after_read(address: int, width: int) -> None:
        nonlocal sampled
        if address == record + 0x30:
            assert not sampled
            sampled = True
            rig.put(address, width, 0x99)
            rig.put(GLOBAL_SENTINEL, 8, sentinel)

    rig.after_read = after_read
    rig.run()
    assert sampled and bool(rig.calls("calls", 0x140DEE6B0)) == send
    assert sum(event[:3] == ("read", record + 0x30, 8) for event in rig.events) == 1


@pytest.mark.parametrize("heap_result", [False, True])
def test_record_string_uses_actual_return_object_and_held_stream(heap_result: bool) -> None:
    rig = Rig()
    record = rig.record(1)
    rig.scan_mode(1, 0, {1: record})
    actual, data, stream = rig.alloc(0x20), rig.alloc(0x20), rig.alloc(0x20)
    rig.put(actual, 8, data)
    rig.put(actual + 0x18, 8, 16 if heap_result else 15)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x141869A90:
            assert args == (record + 0x30, rig.frame + 0x218, record)
            rig.put(rig.frame + 0x230, 8, 15)
            rig.put(rig.world + 0x70, 8, 0x7070)
            return actual
        if target == 0x140E15770 and rig.calls("calls", 0x140DD4880):
            return stream
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    rig.run()
    assert rig.calls("calls", 0x140DEE6B0)[0][3] == (
        stream,
        data if heap_result else actual,
        U32,
    )
    assert rig.get(rig.frame + 0x228, 16) == 15 << 64
    assert rig.get(rig.frame + 0x218, 1) == 0


@pytest.mark.parametrize("old_range", [False, True])
@pytest.mark.parametrize(
    ("capacity", "delta", "trap"),
    [
        (15, 0, False),
        (0xFFE, 0, False),
        (0xFFF, 0, False),
        (0xFFF, 0x1F, False),
        (0xFFF, 0x20, True),
        (0xFFF, U64, True),
        (U64, 0, False),
    ],
)
def test_scan_cleanup_uses_current_header_wrap_and_unsigned_allocation_delta(
    old_range: bool,
    capacity: int,
    delta: int,
    trap: bool,
) -> None:
    rig = Rig()
    record = rig.record(1)
    rig.scan_mode(0 if old_range else 1, 5 if old_range else 0, {6 if old_range else 1: record})
    header = rig.alloc(0x80)
    data = header + 0x40
    allocation = (data - 8 - delta) & U64
    rig.put(data - 8, 8, allocation)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140DEE6B0:
            rig.put(rig.frame + 0x230, 8, capacity)
            rig.put(rig.frame + 0x218, 8, data)
            rig.put(GLOBAL_CONSTANT, 16, 0xABCD)
            return None
        return rig.scalar(target, args)

    def watson(target: int, args: tuple[int, ...]) -> int | None:
        assert target == WATSON and args == (0, 0, 0, 0, rig.frame + 0x20)
        assert rig.get(args[-1]) == 0
        return None

    rig.handlers.update(calls=scalar, watson_home_calls=watson)
    if trap:
        with pytest.raises(UnresolvedReplayTaskRebuild):
            rig.run()
        assert rig.events[-1][0:3] == ("call", "watson_home_calls", WATSON)
        assert not rig.calls("calls", 0x142D6BAB4)
        assert rig.get(rig.frame + 0x230) == capacity
    else:
        rig.run()
        assert rig.get(rig.frame + 0x228, 16) == 15 << 64
        assert rig.get(rig.frame + 0x218, 1) == 0
        frees = rig.calls("calls", 0x142D6BAB4)
        if capacity == 15:
            assert not frees
        else:
            expected_pointer = allocation if capacity == 0xFFF else data
            expected_size = 0x1027 if capacity == 0xFFF else (capacity + 1) & U64
            assert frees[0][3] == (expected_pointer, expected_size)
    header_reads = sum(event[:3] == ("read", data - 8, 8) for event in rig.events)
    assert header_reads == int(capacity == 0xFFF)


def test_inactive_blocks_skip_children_and_follow_all_five_current_offsets() -> None:
    rig = Rig()
    rig.run()
    assert [
        event[1]
        for event in rig.events
        if event[0] == "read"
        and event[1] in {rig.blocks + offset + 0xFB for offset in range(0, 0x500, 0x100)}
    ] == [rig.blocks + offset + 0xFB for offset in range(0, 0x500, 0x100)]
    assert not rig.calls("calls", 0x140B2CFF0)
    assert not rig.calls("geometry_calls")
    assert rig.get(rig.frame + 0x2B0) == 0x500


@pytest.mark.parametrize("al", [0, 0x64])
def test_active_block_predicate_uses_whole_byte_and_held_block(al: int) -> None:
    rig = Rig()
    block = rig.block(0, [])

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140B2CFF0:
            assert args == (block,)
            return al
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    rig.run()
    assert rig.get(block + 0xFB, 1) == int(al != 0)
    assert bool(rig.calls("calls", 0x140B2D040)) == (al != 0)
    assert bool(rig.calls("calls", 0x142D6E3B7)) == (al != 0)


@pytest.mark.parametrize("invalid", [None, True, -1, 0x100])
def test_block_predicate_annotation_refuses_before_workspace(invalid: int | None) -> None:
    rig = Rig()
    block = rig.block(0, [])

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        return invalid if target == 0x140B2CFF0 else rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events[-1][0:3] == ("call", "calls", 0x140B2CFF0)
    assert rig.get(block + 0xFB, 1) == 1
    assert rig.memory.read_bytes(rig.frame + 0x2C0, 48) == bytes([0xA5]) * 48


def test_geometry_workspace_prefix_is_three_stores_then_actual_memset() -> None:
    rig = Rig()
    rig.block(0, [])

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x142D6E3B7:
            assert args == (rig.frame + 0x2F0, 0, 0xB10)
            assert rig.events[-4:-1] == [
                ("write", rig.frame + offset, 16, 0) for offset in (0x2C0, 0x2D0, 0x2E0)
            ]
            assert rig.memory.read_bytes(rig.frame + 0x2F0, 0xB10) == bytes([0xA5]) * 0xB10
            raise UnresolvedReplayTaskRebuild("explicit workspace memset unavailable")
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(UnresolvedReplayTaskRebuild, match="workspace memset unavailable"):
        rig.run()
    assert rig.memory.read_bytes(rig.frame + 0x2C0, 48) == bytes(48)
    assert not rig.calls("calls", 0x140B2D040)


@pytest.mark.parametrize("count", [0, 0x8000, 0xFFFF, 0x7FFF])
def test_geometry_count_is_signed_word_with_current_finite_exit(count: int) -> None:
    rig = Rig()
    block = rig.block(0, [0x80000000])
    rig.put(block + 0xF8, 2, count)
    count_reads = 0

    def after_read(address: int, width: int) -> None:
        nonlocal count_reads
        if address == block + 0xF8:
            count_reads += 1
            if count == 0x7FFF:
                rig.put(address, 2, 1)

    rig.after_read = after_read
    rig.run()
    assert count_reads == (2 if count == 0x7FFF else 1)
    entered = any(event[:3] == ("read", block + 8, 4) for event in rig.events)
    assert entered == (count == 0x7FFF)
    assert rig.calls("calls", 0x140B2D040)[0][3] == (block, rig.frame + 0x2C0)


@pytest.mark.parametrize("fp", [False, True])
def test_unit_coordinate_integer_decodes_preserve_every_scratch_access(fp: bool) -> None:
    rig = Rig()
    unit = rig.unit(x=0xDEADBEEF, y=0x7FC00001, z=0x80000000)
    block = rig.block(0, [1], fp=fp)
    rig.lookup({1: unit})
    rig.run()
    events = rig.events
    start = events.index(("read", unit + 0x180, 8))
    expected = []
    for field, first, second, destination in (
        (0x180, Z1, Z2, 0x78),
        (0x178, -R13, Y2, 0x250),
        (0x170, -X1, X2, 0x238),
    ):
        raw = rig.get(unit + field)
        expected.extend(
            [
                ("read", unit + field, 8),
                ("write", rig.frame + 0x60, 8, raw),
                ("read", rig.frame + 0x60, 8),
                ("write", rig.frame + 0x60, 8, (raw + first) & U64),
                ("read", rig.frame + 0x60, 8),
                ("write", rig.frame + 0x60, 8, (raw + first + second) & U64),
                ("read", rig.frame + 0x60, 8),
                ("write", rig.frame + destination, 8, (raw + first + second) & U64),
            ]
        )
    assert events[start : start + 24] == expected
    args = (rig.frame + 0x2C0, 0xDEADBEEF, 0x7FC00001, 0x80000000)
    if fp:
        args += (rig.frame + 0x20,)
        assert rig.get(rig.frame + 0x20) == 0xA5A5A5A57FC01234
        assert rig.calls("unit_fp_calls", V218)[0][3] == (unit,)
    assert rig.calls("geometry_calls")[0][3] == args
    assert rig.calls("calls", 0x140B2D040)[0][3] == (block, rig.frame + 0x2C0)


@pytest.mark.parametrize("fp", [False, True])
def test_coordinate_decode_reloads_current_scratch_before_full_qword_publication(fp: bool) -> None:
    rig = Rig()
    unit = rig.unit()
    rig.block(0, [1], fp=fp)
    rig.lookup({1: unit})
    writes = 0

    def after_write(address: int, width: int, value: int) -> None:
        nonlocal writes
        if address == rig.frame + 0x60:
            writes += 1
            if writes == 3:
                rig.put(address, 8, 0x1122334440400000)

    rig.after_write = after_write
    rig.run()
    assert rig.get(rig.frame + 0x78) == 0x1122334440400000
    assert rig.calls("geometry_calls")[0][3][3] == 0x40400000


@pytest.mark.parametrize("invalid", [None, True, -1, 1 << 32])
def test_fp_result_is_consumed_after_all_coordinate_decodes(invalid: int | None) -> None:
    rig = Rig()
    unit = rig.unit()
    rig.block(0, [1], fp=True)
    rig.lookup({1: unit})
    rig.handlers["unit_fp_calls"] = lambda target, args: invalid
    with pytest.raises(ValueError):
        rig.run()
    assert rig.events[-1] == ("write", rig.frame + 0x238, 8, 0x3F800000)
    assert rig.get(rig.frame + 0x78) == 0x40400000
    assert rig.get(rig.frame + 0x250) == 0x40000000
    assert not rig.calls("geometry_calls")


def test_unavailable_fp_channel_refuses_at_call_before_coordinates() -> None:
    rig = Rig()
    unit = rig.unit()
    rig.block(0, [1], fp=True)
    rig.lookup({1: unit})
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.run(unit_fp_calls=ReplayTaskRebuildCalls(None))
    assert rig.events[-1] == ("read", rig.get(unit) + 0x218, 8)
    assert ("read", unit + 0x180, 8) not in rig.events


def test_fp_home_store_precedes_current_coordinate_lanes_and_is_live() -> None:
    rig = Rig()
    unit = rig.unit()
    rig.block(0, [1], fp=True)
    rig.lookup({1: unit})

    def after_write(address: int, width: int, value: int) -> None:
        if address == rig.frame + 0x20 and value == 0x7FC01234:
            rig.put(rig.frame + 0x78, 4, 5)
            rig.put(rig.frame + 0x250, 4, 6)
            rig.put(rig.frame + 0x238, 4, 7)
            rig.put(address, 4, 0x41200000)

    def geometry(target: int, args: tuple[int, ...]) -> int | None:
        assert target == 0x140B2D200
        assert args == (rig.frame + 0x2C0, 7, 6, 5, rig.frame + 0x20)
        assert rig.get(args[-1], 4) == 0x41200000
        return None

    rig.after_write = after_write
    rig.handlers["geometry_calls"] = geometry
    rig.run()


def test_non_fp_geometry_does_not_prepare_fp_home_or_fifth_argument() -> None:
    rig = Rig()
    unit = rig.unit()
    rig.block(0, [1])
    rig.lookup({1: unit})
    start = 0

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal start
        if target == 0x140B2CFF0:
            rig.put(rig.frame + 0x20, 8, 0x1122334455667788)
            start = len(rig.events)
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    rig.run()
    assert rig.get(rig.frame + 0x20) == 0x1122334455667788
    assert not rig.calls("unit_fp_calls")
    assert rig.calls("geometry_calls")[0][2:] == (
        0x140B2D0F0,
        (rig.frame + 0x2C0, 0x3F800000, 0x40000000, 0x40400000),
    )
    assert not any(event[:2] == ("write", rig.frame + 0x20) for event in rig.events[start:])


@pytest.mark.parametrize("identifier", [-1, 0, 1, 2, 0x80000000])
def test_signed_lookup_guards_and_actual_null_elements(identifier: int) -> None:
    rig = Rig()
    unit = rig.unit()
    rig.block(0, [identifier])
    rig.lookup({-1: unit, 0: unit, 1: 0})
    rig.run()
    assert bool(rig.calls("geometry_calls")) == (identifier in (-1, 0))
    if identifier == 0x80000000:
        assert not any(
            event[0] == "read"
            and event[1]
            in (
                rig.world + 0x184,
                rig.world + 0x178,
                rig.world + 0x174,
                rig.world + 0x168,
            )
            for event in rig.events
        )


@pytest.mark.parametrize("negative", [False, True])
def test_negative_lookup_has_no_positive_array_null_guard(negative: bool) -> None:
    rig = Rig()
    rig.block(0, [-1 if negative else 1])
    rig.put(rig.world + (0x184 if negative else 0x174), 4, 2)
    if negative:
        with pytest.raises(ReplayMemoryError):
            rig.run()
        assert rig.events[-1] == ("read", 8, 8)
    else:
        rig.run()
        assert not rig.calls("geometry_calls")


def test_sparse_geometry_rows_keep_source_index_and_current_id_table() -> None:
    rig = Rig()
    first, second = rig.unit(), rig.unit(x=0x40E00000)
    block = rig.block(0, [0x80000000, 1, 2])
    rig.lookup({1: first, 2: first})

    def geometry(target: int, args: tuple[int, ...]) -> int | None:
        if len(rig.calls("geometry_calls")) == 1:
            rig.put(block + 16, 4, 3)
            rig.lookup({3: second})
        return None

    rig.handlers["geometry_calls"] = geometry
    rig.run()
    assert [call[3][:2] for call in rig.calls("geometry_calls")] == [
        (rig.frame + 0x2F0, 0x3F800000),
        (rig.frame + 0x320, 0x40E00000),
    ]


@pytest.mark.parametrize("grow", [False, True])
def test_unit_loop_resamples_signed_count_without_invented_cap(grow: bool) -> None:
    rig = Rig()
    unit = rig.unit()
    block = rig.block(0, [1, 1])
    rig.put(block + 0xF8, 2, 1 if grow else 2)
    rig.lookup({1: unit})

    def geometry(target: int, args: tuple[int, ...]) -> int | None:
        count = len(rig.calls("geometry_calls"))
        rig.put(block + 0xF8, 2, 2 if grow and count == 1 else 0xFFFF)
        return None

    rig.handlers["geometry_calls"] = geometry
    rig.run()
    assert len(rig.calls("geometry_calls")) == (2 if grow else 1)


@pytest.mark.parametrize("saved_offset", [0x300, 0x500, 0xFFFFFFFFFFFFFF00])
def test_positive_loop_reloads_saved_offset_before_finalizer_then_signed_wrap(
    saved_offset: int,
) -> None:
    rig = Rig()
    unit = rig.unit()
    block = rig.block(0, [1])
    rig.lookup({1: unit})

    def geometry(target: int, args: tuple[int, ...]) -> int | None:
        rig.put(
            rig.frame + 0x2B0, 8, saved_offset if len(rig.calls("geometry_calls")) == 1 else 0x500
        )
        return None

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140B2D040:
            assert args == (block, rig.frame + 0x2C0)
            rig.put(rig.frame + 0x2B0, 8, 0x999)
        return rig.scalar(target, args)

    rig.handlers.update(calls=scalar, geometry_calls=geometry)
    rig.run()
    assert len(rig.calls("geometry_calls")) == (2 if saved_offset == U64 - 0xFF else 1)
    assert rig.get(rig.frame + 0x2B0) == (0x500 if saved_offset == 0x300 else 0x600)


def test_empty_block_does_not_reload_saved_offset_and_next_base_is_current() -> None:
    rig = Rig()
    block = rig.block(0, [])
    replacement = rig.alloc(0x500, fill=0)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140B2D040:
            assert args == (block, rig.frame + 0x2C0)
            rig.put(rig.frame + 0x2B0, 8, 0x999)
            rig.put(rig.world + 0x800, 8, replacement)
            rig.put(rig.world + 0x88, 4, 0xFEED)
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    result = rig.run()
    assert result.returned_status == 0xFEED and result.status == 9
    assert rig.get(rig.frame + 0x2B0) == 0x500
    assert [("read", replacement + offset + 0xFB, 1) for offset in range(0x100, 0x500, 0x100)] == [
        event
        for event in rig.events
        if event[0] == "read" and replacement <= event[1] < replacement + 0x500
    ]


@pytest.mark.parametrize("which", ["first", "second"])
@pytest.mark.parametrize(
    ("capacity", "delta", "bad"),
    [
        (15, 0, False),
        (0xFFE, 0, False),
        (0xFFF, 0, False),
        (0xFFF, 0x1F, False),
        (0xFFF, 0x20, True),
        (0xFFF, U64, True),
        (U64, 0, False),
    ],
)
def test_reader_cleanup_current_headers_capacity_wrap_and_delta(
    which: str,
    capacity: int,
    delta: int,
    bad: bool,
) -> None:
    rig = Rig()
    rig.read_mode([1, 0])
    data = rig.alloc(0x80) + 0x40
    allocation = (data - 8 - delta) & U64
    rig.put(data - 8, 8, allocation)

    def header(offset: int) -> None:
        rig.put(rig.frame + offset, 8, data)
        rig.put(rig.frame + offset + 0x18, 8, capacity)

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x141869660:
            if which == "first":
                header(0x218)
            return 0
        return rig.scalar(target, args)

    def record(target: int, args: tuple[int, ...]) -> int | None:
        if which == "second":
            header(0x250)
        return None

    rig.handlers.update(calls=scalar, record_home_calls=record)
    assert rig.run().returned_status == 4
    assert len(rig.calls("watson_home_calls")) == ((2 if which == "first" else 1) if bad else 0)
    frees = rig.calls("calls", 0x142D6BAB4)
    if capacity == 15 or bad:
        assert not frees
    else:
        assert frees[0][3] == (
            allocation if capacity == 0xFFF else data,
            0x1027 if capacity == 0xFFF else (capacity + 1) & U64,
        )
    assert sum(event[:3] == ("read", data - 8, 8) for event in rig.events) == int(capacity == 0xFFF)
    if not bad:
        offset = 0x228 if which == "first" else 0x260
        assert rig.get(rig.frame + offset, 16) == 15 << 64
        assert rig.get(rig.frame + offset - 16, 1) == 0


@pytest.mark.parametrize("length", [3, 16])
def test_copy_mutation_does_not_replace_held_terminator_address(length: int) -> None:
    rig = Rig()
    rig.read_mode([1, 0], payload=b"x" * length)
    alternate = rig.alloc(0x20)
    destination = 0

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal destination
        if target == 0x142D6E3B1:
            destination = args[0]
            rig.scalar(target, args)
            rig.put(rig.frame + 0x228, 8, 1)
            if length > 15:
                rig.put(rig.frame + 0x218, 8, alternate)
            return None
        if target == 0x141869660:
            assert rig.get(destination + length, 1) == 0
            assert rig.get(rig.frame + 0x228) == 1
            if length > 15:
                assert rig.get(rig.frame + 0x218) == alternate
            return 0
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    rig.run()


def test_message_final_string_cleanup_refusal_preserves_published_marker() -> None:
    rig = Rig()
    rig.read_mode([2])

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        if target == 0x140A1B220:
            assert args == (rig.frame + 0x238,)
            assert rig.get(rig.game + 0x1252, 1) == 1
            rig.put(rig.world + 0x88, 4, 0xABCD)
            raise UnresolvedReplayTaskRebuild("explicit final message cleanup unavailable")
        return rig.scalar(target, args)

    rig.handlers["calls"] = scalar
    with pytest.raises(UnresolvedReplayTaskRebuild, match="final message cleanup unavailable"):
        rig.run()
    assert rig.events[-1][0:3] == ("call", "calls", 0x140A1B220)
    assert rig.get(rig.world + 0x88, 4) == 0xABCD


def test_current_block_flag_and_virtual_target_use_distinct_fp_category() -> None:
    rig = Rig()
    first, second = rig.unit(), rig.unit()
    block = rig.block(0, [1, 2])
    rig.lookup({1: first, 2: second})
    table = rig.get(second)
    rig.put(table + 0x218, 8, 0x140F558A0)

    def geometry(target: int, args: tuple[int, ...]) -> int | None:
        if len(rig.calls("geometry_calls")) == 1:
            rig.put(block + 0xFA, 1, 1)
        return None

    def fp(target: int, args: tuple[int, ...]) -> int | None:
        assert target == 0x140F558A0 and args == (second,)
        return 0x80000000

    rig.handlers.update(geometry_calls=geometry, unit_fp_calls=fp)
    rig.run()
    assert [call[2] for call in rig.calls("geometry_calls")] == [0x140B2D0F0, 0x140B2D200]
    assert len(rig.calls("unit_fp_calls")) == 1
    assert len(rig.calls("calls", 0x140F558A0)) == 1


def test_positive_block_finalizes_held_receiver_after_unit_changes_world_base() -> None:
    rig = Rig()
    unit = rig.unit()
    block = rig.block(0, [1])
    rig.lookup({1: unit})
    replacement = rig.alloc(0x500, fill=0)

    def geometry(target: int, args: tuple[int, ...]) -> int | None:
        rig.put(rig.world + 0x800, 8, replacement)
        return None

    rig.handlers["geometry_calls"] = geometry
    rig.run()
    assert rig.calls("calls", 0x140B2D040)[0][3] == (block, rig.frame + 0x2C0)
    assert [("read", replacement + offset + 0xFB, 1) for offset in range(0x100, 0x500, 0x100)] == [
        event
        for event in rig.events
        if event[0] == "read" and replacement <= event[1] < replacement + 0x500
    ]


@pytest.mark.parametrize("key", CHANNELS)
def test_each_reached_channel_refuses_after_its_actual_preparation(key: str) -> None:
    rig = Rig()
    if key == "calls":
        last = ("read", rig.world + 0x130, 8)
    elif key == "virtual_calls":
        last = ("read", rig.table + 0x70, 8)
    elif key == "format_home_calls":
        last = ("write", rig.frame + 0x20, 4, 0x11D7)
    elif key == "runtime_calls":
        rig.put(GLOBAL_MODE, 4, 1)
        rig.put(rig.world + 0x88, 4, 1)
        rig.put(GLOBAL_OUTPUT, 8, 0xEE)
        last = ("read", IAT_CLOSE, 8)
    elif key == "record_home_calls":
        rig.read_mode([1])
        last = ("read", GLOBAL_RECORDS, 8)
    elif key == "cleanup_virtual_calls":
        rig.read_mode([2])
        last = ("read", 0x1432EA988 + 0x20, 8)
    elif key == "watson_home_calls":
        record = rig.record(1)
        rig.scan_mode(1, 0, {1: record})
        data = rig.alloc(0x40) + 8
        rig.put(data - 8, 8, data + 8)

        def scalar(target: int, args: tuple[int, ...]) -> int | None:
            if target == 0x140DEE6B0:
                rig.put(rig.frame + 0x218, 8, data)
                rig.put(rig.frame + 0x230, 8, 0xFFF)
                return None
            return rig.scalar(target, args)

        rig.handlers["calls"] = scalar
        last = ("read", IAT_WATSON, 8)
    else:
        unit = rig.unit()
        rig.block(0, [1], fp=key == "unit_fp_calls")
        rig.lookup({1: unit})
        last = (
            ("read", rig.get(unit) + 0x218, 8)
            if key == "unit_fp_calls"
            else (
                "read",
                rig.frame + 0x238,
                4,
            )
        )
    with pytest.raises(UnresolvedReplayTaskRebuild):
        rig.run(**{key: ReplayTaskRebuildCalls(None)})
    assert rig.events[-1] == last


@pytest.mark.parametrize("through_player_pass", [False, True])
def test_actual_predecessor_runners_compose_on_same_frame(through_player_pass: bool) -> None:
    rig = Rig()
    unavailable = ReplayTaskRebuildCalls(None)
    if through_player_pass:
        selected, table = rig.alloc(0x700), rig.alloc(0x340)
        rig.memory.write_bytes(selected, rig.memory.read_bytes(rig.players[0], 0x100))
        rig.put(selected, 8, table)
        rig.put(table + 0x100, 8, 0xA100)
        rig.put(table + 0x310, 8, V310)
        rig.put(selected + 0x648, 4, 0)
        rig.put(rig.begin, 8, selected)
        rig.memory.map_bytes(0x143219E04, (0x447A0000).to_bytes(4, "little"))
        rig.memory.map_bytes(0x14435505D, b"\0")
        rig.put(rig.world + 0x7C, 4, 0)
        rig.put(rig.world + 0x18C, 4, 0)
        rig.put(rig.frame + 0x70, 1, 0)
        sentinel = rig.alloc(0xE0)
        rig.put(sentinel + 0xC8, 8, sentinel)
        rig.put(rig.world + 0x50, 8, sentinel)
    else:
        rig.header(rig.begin, 0)
    primary = ReplayWorldUpdateControlFlags(*rig.meta, 0x141629C59, None)
    links = run_replay_world_update_player_links(
        rig.context,
        unavailable,
        primary,
        logger_home_calls=unavailable,
        relationship_calls=unavailable,
        virtual_calls=unavailable,
    )
    if through_player_pass:

        def ordinary(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert target == 0x141731F00 and args == (selected + 0xA0,) and data is None
            return None

        def virtual(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
            assert target == 0xA100 and args == (selected,) and data is None
            return None

        phase = run_replay_world_update_player_pass(
            rig.context,
            ReplayTaskRebuildCalls(ordinary),
            links,
            virtual_calls=ReplayTaskRebuildCalls(virtual),
            virtual_2e8_calls=unavailable,
            policy_home_calls=unavailable,
            position_home_calls=unavailable,
            relationship_calls=unavailable,
            mxcsr=0x1F80,
        )
        assert isinstance(phase, ReplayWorldUpdatePlayerPass)
        assert phase.outer_index == 1 and phase.held_r13 == R13
        rig.phase = phase
    else:
        assert links.next_address == 0x14162AB9E
        assert links.held_begin is None and links.xmm8_word is None
        rig.phase = links
    rig.events.clear()
    result = rig.run()
    assert result.returned_status == 0x15
    assert result.logical_frame == rig.frame and result.entry_time == rig.meta[2]
    assert rig.events[0] == ("read", rig.world + 0x130, 8)


def test_message_conversion_uses_current_iat_and_exact_prepared_tuple() -> None:
    rig = Rig()
    rig.read_mode([2])
    rig.clock_word = 0x1234567800005555

    def after_write(address: int, width: int, value: int) -> None:
        if address == rig.frame + 0x80:
            rig.put(IAT_CONVERT, 8, 0x140F558A0)

    def runtime(target: int, args: tuple[int, ...]) -> int | None:
        assert target == 0x140F558A0
        assert args == (0x2336, rig.frame + 0x250, 0x10, 10)
        assert rig.get(rig.frame + 0x78, 4) == 0x5555
        assert rig.get(rig.frame + 0x80, 4) == 7
        return 1 << 100

    rig.after_write = after_write
    rig.handlers["runtime_calls"] = runtime
    assert rig.run().returned_status == 4
    assert len(rig.calls("runtime_calls")) == 1


def test_world_virtual_uses_held_vptr_with_current_slot_at_call() -> None:
    rig = Rig()
    replacement = rig.alloc(0x150)
    rig.put(replacement + 0x70, 8, 0xBAD70)
    armed = True

    def after_read(address: int, width: int) -> None:
        nonlocal armed
        if armed and address == rig.world:
            armed = False
            rig.put(rig.world, 8, replacement)
            rig.put(rig.table + 0x70, 8, 0xB070)

    def virtual(target: int, args: tuple[int, ...]) -> int | None:
        assert target == 0xB070 and args == (rig.world,)
        return 1 << 100

    rig.after_read = after_read
    rig.handlers["virtual_calls"] = virtual
    rig.run()
    assert len(rig.calls("virtual_calls")) == 1


def test_second_postpass_bottom_reads_end_before_current_begin() -> None:
    rig = Rig(2)
    second = rig.player()
    alternate = rig.array([0, second], stride=16)
    armed = False

    def scalar(target: int, args: tuple[int, ...]) -> int | None:
        nonlocal armed
        if target == 0x141229A20:
            armed = len(rig.calls("calls", target)) == 1
            if not armed:
                rig.header(alternate, 0)
        return rig.scalar(target, args)

    def after_read(address: int, width: int) -> None:
        nonlocal armed
        if armed and address == rig.world + 0x770:
            armed = False
            rig.header(alternate, 0)

    rig.handlers["calls"], rig.after_read = scalar, after_read
    rig.run()
    assert [call[3] for call in rig.calls("calls", 0x141229A20)] == [
        (rig.get(rig.players[0] + 0x40),),
        (rig.get(second + 0x40),),
    ]
