"""Source-led Building phases with real owned Input/Result/behavior effects.

Unit and the named owner/cache/optional-object callbacks are explicit isolated
fixture boundaries. They do not stand in for successful native children in the
shipping binder. No recording, native IStream or complete World is inferred.
"""

from __future__ import annotations

import struct
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_base_saved_leaves import release_replay_base_saved_pair_control
from vantage.replay_behavior_factory import bind_replay_behavior_factory
from vantage.replay_behavior_saved import (
    ReplayBehaviorSavedScratch,
    bind_replay_behavior_saved,
)
from vantage.replay_building_construction import (
    ReplayBuildingConstructionScratch,
    bind_replay_building_construction,
)
from vantage.replay_building_saved import (
    ReplayBuildingSavedScratch,
    bind_replay_building_saved,
    read_replay_saved_building,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_pair import bind_replay_saved_pair
from vantage.replay_saved_position import bind_replay_saved_position
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

ENTRY, UNIT, IO, IO2 = 0x141297F00, 0x1412D4F50, 0xBE01, 0xBE02
VERSION, CALLOC, MODERN = 0x1440A0D94, 0xBE03, 0x44E666
U64 = (1 << 64) - 1
SCRATCH = ReplayBuildingSavedScratch(bytes((i * 7 + 3) & 255 for i in range(0xE18)))


def plan_for(
    version=MODERN,
    *,
    rows=(),
    pending=0,
    recovered=False,
    vectors=(),
    optional=False,
    floats=(1.0, -2.0, 3.0, 0.0),
    words=(),
    progress=0,
):
    """Hand-written constant-version request recipe; values are independent inputs."""
    result = []

    def add(kind, offset, width, value=0, label=None):
        raw = (
            value
            if type(value) is bytes
            else (value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")
        )
        assert len(raw) == width
        result.append(
            dict(kind=kind, offset=offset, width=width, raw=raw, label=label or f"{kind}{offset:x}")
        )

    v = version if version < 0x80000000 else version - (1 << 32)
    for offset, width, value in (
        (0x951, 1, 0),
        (0x900, 4, progress),
        (0x94C, 4, 0x3F800000),
        (0x950, 1, 0x81),
        (0x844, 1, 7),
        (0x848, 4, 0x89ABCDEF),
        (0x890, 4, 0xFFC00001),
        (0x8D0, 4, 123),
        (0x8D4, 4, 456),
        (0x8E0, 4, 10),
        (0x8E4, 4, 11),
        (0x8E8, 4, 12),
        (0x8EC, 4, 13),
        (0x8F0, 4, 0xFFFFFFFF),
        (0x8F4, 2, 0xFFFF),
        (0x910, 1, 2),
    ):
        add("object", offset, width, value)
    if 0xBFD70 <= v < 0xBFDB2:
        add("rbp", 0x78, 4)
    elif 0xA8A3D <= v < 0xBFD70:
        add("rbp", 0x7C, 4)
    for offset in range(0, 20, 4):
        add("resource", offset, 4, 0x80000000 + offset)
    add("object", 0x84D, 1, 3)
    add("behavior", 0x68, 2, label="behavior850")
    if v < 0xC87AE:
        add("behavior", 0x68, 2, label="behaviorOld")
    add("object", 0x8A0, 2, len(rows))
    for index, (unit, count, research) in enumerate(rows):
        start = (index + int(recovered)) * 48
        add("row", start, 2, unit)
        add("row", start + 2, 2, count)
        if v >= 0xC87AE:
            add("row", start + 4, 2, research)
        if v >= 0x419999:
            add("row", start + 44, 2, 3)
            add("row", start + 40, 4, 0xDEADBEEF)
        if v >= 0x3E9999:
            add("row", start + 8, 24, bytes(range(24)))
        elif v >= 0xD07AE:
            add("rbp", 0x38, 16, struct.pack("<4f", *floats))
    add("object", 0x8A2, 2, pending)
    add("object", 0x8A4, 2, 4)
    add("object", 0x8A6, 1, 1)
    add("behavior", 0x68, 2, label="behavior8a8")
    if v == 0xAA3D7:
        add("rbp", 4, 4, 1)
        add("rbp", 0x80, 4, 0xFA123456)
        add("rbp", 0x28, 12, bytes(range(12)))
        add("rbp", 0x28, 12, bytes(range(12, 24)))
    if v >= 0xAA666:
        add("object", 0x914, 12, bytes(range(12)))
        add("object", 0x914, 12, bytes(range(12, 24)))
        for offset in (0x92C, 0x930, 0x934):
            add("object", offset, 4, 0x80000000 + offset)
    if v >= 0xAAB85:
        add("rbp", -0xC, 1, 0xFE)
    if v >= 0xB6E14:
        add("rbp", -0x14, 1, 0x81)
    if v >= 0xB8A3D:
        add("object", 0x911, 1, 0x91)
    if v >= 0xCDEB8:
        add("object", 0x938, 1, 0xFF)
    if v >= 0x142147:
        add("rbp", -0x18, 2, 0xFFFF)
    if v >= 0x1A028F:
        add("object", 0x8D8, 4, 0xDEADBEEF)
    for gate, count, value, tag in ((0x3D07AE, 0x14, 0x10, 0), (0x3F4CCC, 0x1C, 0x18, 1)):
        if v >= gate:
            items = vectors[tag] if vectors else ()
            add("rbp", count, 4, len(items))
            for item in items:
                add("rbp", value, 4, item)
    if v >= 0x19147A:
        add("rbp", -0x13, 1, int(optional))
        if optional:
            add("rbp", -0xB, 1, 0xAB)
    if v >= 0x326666:
        add("rbp", 0x20, 4, 0)
    if v >= 0x3D3333:
        add("rbp", 0xC, 4, 1 if vectors else 0)
        if vectors:
            add("rbp", -8, 2, 0xFEDC)
        add("rbp", 8, 4, 1 if vectors else 0)
        if vectors:
            add("rbp", -4, 2, 0x89AB)
    if v >= 0x40B333:
        add("rbp", -0x10, 4, len(words))
        for word in words:
            add("rbp", 0, 2, word)
    if v >= 0x421999:
        add("object", 0x980, 1, 0x83)
    return result


def setup(
    *,
    version=MODERN,
    rows=(),
    pending=0,
    recovered=False,
    vectors=(),
    words=(),
    optional=False,
    floats=(1.0, -2.0, 3.0, 0.0),
    progress=0,
    before=None,
    after=None,
    on_read=None,
    on_write=None,
    truncate=None,
):
    h = SimpleNamespace()
    h.m = m = ReplayMemory()
    h.obj, h.out, h.stream, h.table, h.master, h.owner, h.world, h.opaque = (
        m.allocate(n) for n in (0xA00, 48, 8, 0x1000, 0x400, 0x100, 0x1000, 0xD0)
    )
    m.write_bytes(h.obj, bytes(0xA00))
    m.write_bytes(h.out, b"O" * 48)
    m.write(h.obj, 8, h.table)
    m.write(h.obj + 16, 8, (h.master + 0x774A063B3D17506C) & U64)
    m.write(h.obj + 24, 8, h.owner)
    m.write(h.obj + 0x188, 1, 1)
    m.write(h.owner + 8, 8, h.world)
    h.master_table = m.calloc(1300, 8)
    m.write(h.owner + 40, 8, h.master_table)
    for unit in (109, 1245):
        m.write(h.master_table + unit * 8, 8, h.master)
    h.catalog = m.allocate(0x100)
    m.write(h.owner + 24, 8, h.catalog)
    h.master_id = 109
    m.write(h.master + 24, 8, (h.master_id + 0x47E37DFF0616CE4F) ^ 0x349E37847AD69F19)
    m.write(h.table + 0x8F8, 8, 0x1412C5A30)  # Explicit selected Unit-factory profile.
    m.write(h.table + 24, 8, IO)
    m.write(h.stream, 8, h.table)
    for header in (0x828, 0x968, 0x990, 0x9B0, 0x9E0, 0x9C8):
        pointer = m.allocate(128)
        for delta, value in ((0, pointer), (8, pointer), (16, pointer + 128)):
            m.write(h.obj + header + delta, 8, value)
    for address, width, value in (
        (VERSION, 4, version & 0xFFFFFFFF),
        (0x143199DD0, 8, 0x142D6BAB4),
        (0x143199DC0, 8, CALLOC),
        (0x14319A060, 8, 0xBE04),
    ):
        m.map_bytes(address, value.to_bytes(width, "little"))
    h.frames, h.finished, h.events, h.operations, h.reads, h.managers = [], [], [], [], [], []
    h.handlers, h.missing = {}, set()
    h.recovered = m.calloc(1, 0x80) if recovered else 0
    if recovered:
        m.write(h.recovered + 0x68, 2, 0xFFFF)
        m.write(h.recovered + 0x6C, 4, 1245)
    h.threshold, h.cast = 1, 0
    h.plan = plan_for(
        version,
        rows=rows,
        pending=pending,
        recovered=recovered,
        vectors=vectors,
        optional=optional,
        floats=floats,
        words=words,
        progress=progress,
    )
    wire = b"".join(row["raw"] for row in h.plan)
    h.source = ReplaySavedInput(wire if truncate is None else wire[:truncate])

    def read(address, width):
        value = m.read(address, width)
        h.operations.append(("read", address, width, value))
        if on_read:
            replacement = on_read(h, address, width, value)
            if replacement is not None:
                return replacement
        return value

    def write(address, width, value):
        m.write(address, width, value)
        h.operations.append(("write", address, width, value))
        if on_write:
            on_write(h, address, width, value)

    h.context = ReplayTaskRebuildStorage(h.obj, read, write)
    h.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)

    @contextmanager
    def local(view):
        with m.bind_local(view) as address:
            h.frames.append((address, view))
            try:
                yield address
            finally:
                h.finished.append((address, bytes(view)))
                h.frames.pop()

    h.local = local
    h.runtime = m.runtime_calls(calloc_target=CALLOC)
    h.imports = h.runtime

    def dispatch(target, args, data):
        h.events.append((target, args))
        if target in h.missing:
            raise UnresolvedReplayTaskRebuild(f"missing actual child {target:x}")
        if before:
            before(h, target, args)
        if target in (IO, IO2):
            row = h.plan[len(h.reads)]
            bases = {
                "object": h.obj,
                "row": m.read(h.obj + 0x898, 8),
                "resource": m.read(h.obj + 0x860, 8),
            }
            if row["kind"] == "rbp":
                base = next(p for p, v in h.frames if len(v) == 0xE18) + 0x100
            elif row["kind"] == "behavior":
                base = next(p for p, v in h.frames if len(v) == 0xD0)
            else:
                base = bases[row["kind"]]
            assert args[2:] == (base + row["offset"], row["width"]), (row, args)
            h.reads.append((row["label"], args))
        if target == UNIT:
            reader_frame = next(p for p, v in h.frames if len(v) == 0xE18)
            assert args == (h.obj, reader_frame + 0x188, h.stream, h.opaque)
            answer = 0xDEADBEEF  # Explicit isolated Unit predecessor effect.
        elif target == 0x1408EE150:
            release_replay_base_saved_pair_control(
                h.context, args[0], calls=h.graph, atomics=h.atomics
            )
            answer = None
        elif target == 0x140B89440:
            answer = h.recovered  # Explicit historical recovery callback fixture.
        elif target == 0x142D6E3D5:
            answer = h.cast  # Explicit RTTI provider fixture, not a native RTTI claim.
        elif target == 0x140BB9290:
            answer = h.threshold  # Explicit required classifier fixture.
        elif target == 0x141296B90:
            answer = None  # Named setter boundary; mutations are tested separately.
        elif target == 0x141729140:
            answer = m.calloc(1, 16)
            m.write(answer + 4, 4, 6)
        elif target in (
            0x14111BC60,
            0x14111B550,
            0x14111B540,
            0x14111A520,
            0x14127C410,
            0x140B87D60,
            0x1411DF830,
        ):
            answer = None  # Explicit owner/cache/attachment fixture boundaries.
        elif target == 0x1412E1CA0:
            answer = args[0]  # Explicit optional-object constructor fixture.
        elif target == 0x140F2D200:
            header, pointer, length, capacity = args
            old = m.read(header, 8)
            m.free(old)
            m.write(header, 8, pointer)
            m.write(header + 8, 8, pointer + length * 2)
            m.write(header + 16, 8, pointer + capacity * 2)
            answer = header  # Source-bound commit boundary fixture.
        elif target == 0x14116C430:
            header, value = args
            end = m.read(header + 8, 8)
            m.write(end, 2, m.read(value, 2))
            m.write(header + 8, 8, end + 2)
            answer = end
        elif target == 0x140B53800:
            header, value = args
            end = m.read(header + 8, 8)
            m.write(end, 4, m.read(value, 4))
            m.write(header + 8, 8, end + 4)
            answer = end
        elif target in h.handlers:
            answer = h.handlers[target](target, args, data)
        else:
            assert h.runtime.call
            answer = h.runtime.call(target, args, data)
        if after:
            replacement = after(h, target, args, answer)
            if replacement is not None:
                answer = replacement
        return answer

    h.graph = ReplayTaskRebuildCalls(dispatch)

    def register(bound, targets):
        assert bound.call
        for target in targets:
            h.handlers[target] = bound.call

    register(
        bind_replay_saved_result(h.context, h.graph, atomics=h.atomics, imports=h.imports),
        (0x1402BD7F0, 0x1402BD890, 0x140900620),
    )
    register(
        bind_replay_saved_apply(h.context, h.graph, atomics=h.atomics, imports=h.imports),
        (0x1409076B0, 0x1402B9080),
    )
    register(
        bind_replay_saved_position(h.context, h.graph, atomics=h.atomics, bind_local=local),
        (0x140B81D60,),
    )
    register(
        bind_replay_behavior_factory(h.context, h.graph), (0x1412C5A30, 0x140BB6EC0, 0x140B875A0)
    )
    register(
        bind_replay_behavior_saved(
            h.context,
            h.graph,
            atomics=h.atomics,
            bind_local=local,
            scratch=ReplayBehaviorSavedScratch(bytes(0xD0)),
        ),
        (0x140B88C50,),
    )
    for target in (IO, IO2):
        register(
            bind_replay_saved_input(
                h.context, h.graph, h.source, stream=h.stream, target=target, result_bytes=bytes(48)
            ),
            (target,),
        )
    h.bound = bind_replay_building_saved(
        h.context,
        h.graph,
        atomics=h.atomics,
        bind_local=local,
        scratch=SCRATCH,
        mxcsr=0x1F80,
        imports=h.imports,
    )
    return h


def invoke(h, *, direct=False):
    if direct:
        return read_replay_saved_building(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            calls=h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
            mxcsr=0x1F80,
            imports=h.imports,
        )
    assert h.bound.call
    return h.bound.call(ENTRY, (h.obj, h.out, h.stream, h.opaque), None)


@pytest.mark.parametrize("direct", (False, True))
def test_modern_complete_normal_component(direct):
    h = setup()
    assert invoke(h, direct=direct) == h.out
    assert len(h.reads) == len(h.plan)
    assert h.m.read_bytes(h.out, 48) == bytes(41) + b"O" * 7
    assert h.m.read(h.obj + 15, 1) == 0x50
    assert h.m.read(h.obj + 0x8D0, 8) == 0
    assert h.m.read(h.obj + 0x8D8, 4) == 0
    assert h.m.read_bytes(h.obj + 0x914, 12) == bytes(range(12, 24))
    assert [target for target, _ in h.events].count(0x1412C5A30) == 2
    assert [target for target, _ in h.events].count(0x140B88C50) == 2
    assert h.finished[-1][1][0x78] == SCRATCH.reader[0x78]


@pytest.mark.parametrize(
    "version",
    (
        0,
        0xA8A3C,
        0xA8A3D,
        0xAA3D7,
        0xAA665,
        0xAA666,
        0xAAB84,
        0xAAB85,
        0xB6E13,
        0xB6E14,
        0xB8A3C,
        0xB8A3D,
        0xBFD6F,
        0xBFD70,
        0xBFDB1,
        0xBFDB2,
        0xC87AD,
        0xC87AE,
        0xCDEB7,
        0xCDEB8,
        0x142146,
        0x142147,
        0x191479,
        0x19147A,
        0x1A028E,
        0x1A028F,
        0x326665,
        0x326666,
        0x3D07AD,
        0x3D07AE,
        0x3D3332,
        0x3D3333,
        0x3F4CCB,
        0x3F4CCC,
        0x40B332,
        0x40B333,
        0x421998,
        0x421999,
        0xFFFFFFFF,
    ),
)
def test_all_version_boundaries(version):
    h = setup(version=version)
    assert invoke(h) == h.out
    assert len(h.reads) == len(h.plan)


def test_modern_positive_rows_pending_owner_order_and_sequence():
    h = setup(
        rows=((1245, 2, -1), (109, 0, 3)),
        pending=1,
        vectors=((11, 22), (33,)),
        words=(0x1234, 0xFEDC),
    )
    h.m.write(h.obj + 0x988, 8, U64)
    assert invoke(h) == h.out
    base = h.m.read(h.obj + 0x898, 8)
    assert h.m.read(base + 32, 8) == U64
    assert h.m.read(base + 80, 8) == 0
    assert h.m.read(h.obj + 0x988, 8) == 1
    assert h.m.read_bytes(base + 8, 24) == bytes(range(24))
    events = [target for target, _ in h.events if target in (0x141729140, 0x14111BC60, 0x14111B550)]
    assert events == [0x141729140, 0x14111BC60, 0x14111B550] * 2
    for header, width, expected in (
        (0x828, 4, (11, 22)),
        (0x968, 4, (33,)),
        (0x9B0, 2, (0xFEDC,)),
        (0x9E0, 2, (0x89AB,)),
        (0x9C8, 2, (0x1234, 0xFEDC)),
    ):
        pointer = h.m.read(h.obj + header, 8)
        assert tuple(h.m.read(pointer + i * width, width) for i in range(len(expected))) == expected


@pytest.mark.parametrize(
    "version", (0xC87AD, 0xC87AE, 0xD07AD, 0xD07AE, 0x3E9998, 0x3E9999, 0x419998, 0x419999)
)
def test_positive_production_historical_branches(version):
    h = setup(version=version, rows=((1245, 0, 3),))
    invoke(h)
    base = h.m.read(h.obj + 0x898, 8)
    assert h.m.read(base, 2) == 1245
    if 0xD07AE <= version < 0x3E9999:
        assert h.m.read(base + 8, 8) == (0x3F800000 << 32)
        assert h.m.read(base + 16, 8) == (0x40400000 << 32) | 2
    elif version < 0xD07AE:
        assert h.m.read(base + 8, 8) == 0xFFFFFFFF
        assert any(target == 0x14127C410 for target, _ in h.events)
    else:
        assert h.m.read_bytes(base + 8, 24) == bytes(range(24))


def test_old_behavior_recovery_keeps_first_slot_and_real_transfer_frontier():
    h = setup(version=0xC87AD, recovered=True, rows=((109, 0, -1),))
    invoke(h)
    base = h.m.read(h.obj + 0x898, 8)
    assert h.m.read(base, 2) == 1245
    assert h.m.read(base + 2, 2) == 1
    assert h.m.read(base + 48, 2) == 109
    assert h.m.read(h.obj + 0x8A2, 2) == 1
    transfer = [(target, args) for target, args in h.events if target == 0x140B87D60]
    assert transfer == [(0x140B87D60, (h.m.read(h.obj + 0x8A8, 8), h.recovered))]


def test_optional_object_full_call_tuple_and_cleanup():
    h = setup(optional=True)
    invoke(h)
    constructor = next(args for target, args in h.events if target == 0x1412E1CA0)
    assert constructor[0] == h.m.read(h.obj + 0x908, 8)
    assert constructor[2:] == (h.stream, h.world + 0xC0, h.world + 0xA0, 1)
    assert any(target == 0x1411DF830 for target, _ in h.events)


@pytest.mark.parametrize(
    "raw,complete",
    ((0, False), (0x3F800000, True), (0x7FC01234, False), (0x7F800000, True), (0xFF800000, False)),
)
def test_completion_float_comparison(raw, complete):
    h = setup(progress=raw)
    invoke(h)
    assert any(t == 0x14111B540 for t, _ in h.events) is complete
    assert any(t == 0x14111A520 for t, _ in h.events) is complete


@pytest.mark.parametrize(
    "missing", (UNIT, 0x140B81D60, 0x1412C5A30, 0x140B88C50, 0x141296B90, 0x140BB9290)
)
def test_unknown_actual_children_refuse_with_prior_effects(missing):
    h = setup()
    h.missing.add(missing)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="missing actual child"):
        invoke(h)
    assert h.frames == []
    assert h.m.read_bytes(h.out, 48) == b"O" * 48


@pytest.mark.parametrize("truncate", (0, 1, 4, 15, 25, 45, 80))
def test_input_failure_preserves_prefix_and_does_not_publish_success(truncate):
    h = setup(truncate=truncate)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        invoke(h)
    assert h.m.read_bytes(h.out, 48) == b"O" * 48
    assert h.frames == []


def test_parent_nonzero_status_refuses_before_processed_or_cleanup():
    def after(h, target, args, answer):
        if target == UNIT:
            h.m.write(args[1] + 24, 8, 7)

    h = setup(after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="metadata/TLS"):
        invoke(h)
    parent = next(args for target, args in h.events if target == UNIT)[1]
    frame, raw = h.finished[-1]
    assert raw[parent - frame + 40] == 0
    assert h.events == [(UNIT, (h.obj, parent, h.stream, h.opaque))]


def test_current_stream_and_encoded_decode_mutations_are_observed():
    def after(h, target, args, answer):
        if target == 0x140900620 and len(h.reads) == 9:
            table = h.m.allocate(0x20)
            h.m.write(table + 24, 8, IO2)
            h.m.write(h.stream, 8, table)

    h = setup(after=after)
    invoke(h)
    assert any(target == IO2 for target, _ in h.events)


def test_direct_null_call_provider_fails_without_output_publication():
    h = setup()
    with pytest.raises(UnresolvedReplayTaskRebuild):
        read_replay_saved_building(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            calls=ReplayTaskRebuildCalls(None),
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
            mxcsr=0x1F80,
        )
    assert h.m.read_bytes(h.out, 48) == b"O" * 48


@pytest.mark.parametrize("size", (0, 0xE17, 0xE19))
def test_seed_exact_size(size):
    with pytest.raises(ValueError):
        ReplayBuildingSavedScratch(bytes(size))


@pytest.mark.parametrize("mxcsr", (0, 0x9FC0, True, 0x1F81))
def test_fp_profile_rejection_before_mutation(mxcsr):
    h = setup()
    before = h.m.read_bytes(h.obj, 0xA00)
    with pytest.raises(ValueError):
        read_replay_saved_building(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            calls=h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
            mxcsr=mxcsr,
        )
    assert h.m.read_bytes(h.obj, 0xA00) == before
    assert h.events == []


def test_binder_arity_data_and_delegate():
    h = setup()
    assert h.bound.call
    for args, data in (((h.obj,), None), ((h.obj, h.out, h.stream, h.opaque), memoryview(b"x"))):
        with pytest.raises(ValueError):
            h.bound.call(ENTRY, args, data)
    with pytest.raises((ReplayMemoryError, UnresolvedReplayTaskRebuild)):
        h.bound.call(0xBADBAD, (), None)


def test_current_end_rmw_after_append_write_is_not_held_end_plus_four():
    def write(h, address, width, value):
        pointer = h.m.read(h.obj + 0x828, 8)
        if address == pointer and width == 4 and value == 11:
            h.m.write(h.obj + 0x830, 8, pointer + 8)

    h = setup(vectors=((11,), ()), on_write=write)
    begin = h.m.read(h.obj + 0x828, 8)
    invoke(h)
    assert h.m.read(h.obj + 0x830, 8) == begin + 12


def test_pending_positive_loop_reloads_current_output_home_at_actual_endpoint():
    alternate = []

    def after(h, target, args, answer):
        if target == 0x141729140 and not alternate:
            pointer = h.m.allocate(48)
            h.m.write_bytes(pointer, b"X" * 48)
            alternate.append(pointer)
            frame = next(p for p, v in h.frames if len(v) == 0xE18)
            h.m.write(frame + 0xA8, 8, pointer)

    h = setup(rows=((1245, 1, -1),), pending=1, after=after)
    assert invoke(h) == alternate[0]
    assert h.m.read_bytes(h.out, 48) == b"O" * 48
    assert h.m.read_bytes(alternate[0], 48) == bytes(41) + b"X" * 7


def test_positive_queue_reads_current_count_after_sequence_publication():
    def after(h, target, args, answer):
        if target == 0x140900620 and h.reads[-1][0] == "object8a0":
            h.m.write(h.obj + 0x8A0, 2, 2)

    def write(h, address, width, value):
        if address == h.obj + 0x988 and width == 8:
            h.m.write(h.obj + 0x8A0, 2, 1)

    h = setup(rows=((1245, 0, -1),), after=after, on_write=write)
    invoke(h)
    base = h.m.read(h.obj + 0x898, 8)
    assert h.m.read_bytes(base + 48, 48) == bytes(48)  # Actual allocation admitted two rows.
    assert h.m.read(h.obj + 0x8A0, 2) == 1
    assert h.m.read(h.obj + 0x988, 8) == 1


def test_historical_rtti_call_and_current_pending_slot_write():
    h = setup(version=0xC87AD, rows=((1245, 0, -1),))
    h.cast, h.threshold = h.master, 7
    invoke(h)
    call = next(args for target, args in h.events if target == 0x142D6E3D5)
    assert call == (h.master, 0, 0x14411E1B8, 0x14411E1E8, 0)
    assert h.m.read(h.m.read(h.obj + 0x898, 8) + 44, 2) == 7


def test_historical_cache_abi_zero_extends_signed_dword_registers():
    h = setup(version=0xC87AE, rows=((-2, 0, -3),))
    invoke(h)
    args = next(args for target, args in h.events if target == 0x14127C410)
    assert args == (h.obj, 0, 0xFFFFFFFD, 0xFFFFFFFE, 0)


@pytest.mark.parametrize("count", (65, 2048))
def test_word_reserve_small_and_aligned_large_paths_full_contents(count):
    h = setup(words=tuple(range(count)))
    old = h.m.read(h.obj + 0x9C8, 8)
    invoke(h)
    begin = h.m.read(h.obj + 0x9C8, 8)
    assert begin != old
    assert h.m.read_bytes(begin, count * 2) == b"".join(
        i.to_bytes(2, "little") for i in range(count)
    )
    assert h.m.read(h.obj + 0x9D0, 8) == begin + count * 2
    assert h.m.read(h.obj + 0x9D8, 8) == begin + count * 2
    if count == 2048:
        assert begin % 32 == 0
        assert h.m.read(begin - 8, 8) < begin
    commit = next(args for target, args in h.events if target == 0x140F2D200)
    assert commit == (h.obj + 0x9C8, begin, 0, count)


def test_large_null_allocation_calls_actual_current_watson_and_never_commits():
    def after(h, target, args, answer):
        if target == 0x142D6BA78 and args == (4135,):
            return 0

    h = setup(words=tuple(range(2048)), after=after)
    old = h.m.read(h.obj + 0x9C8, 8)
    seen = []

    def terminal(target, args, data):
        if target == 0xBE04:
            seen.append(args)
            raise RuntimeError("actual fixture Watson terminal")
        assert h.runtime.call
        return h.runtime.call(target, args, data)

    with pytest.raises(RuntimeError, match="Watson terminal"):
        read_replay_saved_building(
            h.context,
            h.obj,
            h.out,
            h.stream,
            h.opaque,
            calls=h.graph,
            atomics=h.atomics,
            bind_local=h.local,
            scratch=SCRATCH,
            mxcsr=0x1F80,
            imports=ReplayTaskRebuildCalls(terminal),
        )
    assert seen == [(0, 0, 0, 0, 0)]
    assert h.m.read(h.obj + 0x9C8, 8) == old
    assert not any(t == 0x140F2D200 for t, _ in h.events)


def test_positive_index_reads_actual_opaque_table_and_negative_skips_it():
    h = setup()
    selected = h.m.allocate(8)
    table = h.m.allocate(16)
    h.m.write(table + 8, 8, selected)
    h.m.write(h.opaque + 0xC0, 8, table)

    def after(h, target, args, answer):
        if target == IO and h.reads[-1][0] == "rbp-18":
            h.m.write(args[2], 2, 1)

    h2 = setup(after=after)
    table2 = h2.m.allocate(16)
    h2.m.write(table2 + 8, 8, 0x12345678)
    h2.m.write(h2.opaque + 0xC0, 8, table2)
    invoke(h2)
    assert h2.m.read(h2.obj + 0x940, 8) == 0x12345678
    # The default -1 requires no opaque table bytes at all.
    invoke(h)
    assert h.m.read(h.obj + 0x940, 8) == 0


def test_building_constructor_real_reader_result_and_behavior_composition():
    h = setup()
    h.m.write_bytes(h.out, bytes(41) + b"padding")
    h.m.map_bytes(0x1432B5FC8 + 0x8F8, (0x1412C5A30).to_bytes(8, "little"))
    assert h.bound.call
    h.handlers[ENTRY] = h.bound.call

    def unit_constructor(target, args, data):
        assert args == (h.obj, h.out, h.stream, h.opaque, 0)
        return 0xDEADBEEF  # Explicit Unit constructor predecessor boundary.

    h.handlers[0x1412A5D60] = unit_constructor
    h.handlers[0x141285450] = lambda target, args, data: 0
    pair = bind_replay_saved_pair(h.context, h.graph, atomics=h.atomics)
    assert pair.call
    h.handlers[0x14090D270] = pair.call
    bound = bind_replay_building_construction(
        h.context,
        h.graph,
        atomics=h.atomics,
        bind_local=h.local,
        scratch=ReplayBuildingConstructionScratch(bytes(0xD4)),
        mxcsr=0x1F80,
    )
    assert bound.call
    assert bound.call(0x14126DAA0, (h.obj, h.out, h.stream, h.opaque, 1), None) == h.obj
    assert len(h.reads) == len(h.plan)
    assert h.m.read(h.out + 24, 8) == 0
    assert h.m.read(h.obj + 0x1C4, 1) == 0
    assert h.m.read_bytes(h.out + 41, 7) == b"padding"


@pytest.mark.parametrize(
    "raw,threshold,complete",
    [
        (0x00000001, 0, True),
        (0x80000001, 0, False),
        (0x80000000, 0, True),
        (0x00000000, 0, True),
        (0xBF800000, 0xFFFF, True),
        (0xBF800001, 0xFFFF, False),
        (0xC7000000, 0x8000, True),
        (0xC7000001, 0x8000, False),
        (0x46FFFE00, 0x7FFF, True),
        (0x46FFFDFF, 0x7FFF, False),
        (0x7F800001, 0, False),
        (0xFFC00001, 0x8000, False),
        (0xFF800000, 0x8000, False),
        (0x7F800000, 0x7FFF, True),
    ],
)
def test_completion_raw_binary32_and_signed16_classifier_edges(raw, threshold, complete):
    h = setup(progress=raw)
    h.threshold = threshold
    invoke(h)
    assert any(t == 0x14111B540 for t, _ in h.events) is complete
    assert any(t == 0x14111A520 for t, _ in h.events) is complete


@pytest.mark.parametrize(
    "raws,positive",
    [
        ((1, 0x80000001, 0x7F800000, 0x7F800001), ((0, 1), (2, 0x7F800000))),
        ((0x80000000, 0, 0xFF800000, 0xFFC00001), ()),
        ((0x7FC01234, 1, 0x7F800001, 0x3F800000), ((1, 1), (3, 0x3F800000))),
    ],
)
def test_legacy_resources_keep_exact_positive_raw_words(raws, positive):
    h = setup(version=0xD07AE, rows=((109, 1, 0xFFFF),), floats=(0.0,) * 4)
    row = next(row for row in h.plan if row["kind"] == "rbp" and row["offset"] == 0x38)
    row["raw"] = b"".join(raw.to_bytes(4, "little") for raw in raws)
    h.source = ReplaySavedInput(b"".join(row["raw"] for row in h.plan))
    for target in (IO, IO2):
        bound = bind_replay_saved_input(
            h.context, h.graph, h.source, stream=h.stream, target=target, result_bytes=bytes(48)
        )
        assert bound.call
        h.handlers[target] = bound.call
    invoke(h)
    pointer = h.m.read(h.obj + 0x898, 8)
    actual = h.m.read_bytes(pointer + 8, 24)
    expected = b"".join(
        kind.to_bytes(4, "little") + raw.to_bytes(4, "little") for kind, raw in positive
    )
    assert actual == expected + bytes(24 - len(expected))
