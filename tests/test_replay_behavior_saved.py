"""Owned behavior reader I/O/CRT/Result effects and explicit virtual fixtures.

Payload destruction/activation and manager item factories below are named
first-party fixture boundaries, not native behavior implementations. Missing
factory/virtual cases refuse. Input, allocation/free and Result paths use real
owned engine effects; no native IStream, Game or whole restore is inferred.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vantage.replay_behavior_saved import (
    ReplayBehaviorSavedScratch,
    bind_replay_behavior_saved,
    read_replay_saved_behavior,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_saved_apply import bind_replay_saved_apply
from vantage.replay_saved_input import ReplaySavedInput, bind_replay_saved_input
from vantage.replay_saved_result import bind_replay_saved_result
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_ai_map import ReplayUnitAIMapAtomics

ENTRY, CLEANUP, FORWARD = 0x140B88C50, 0x1402BD890, 0x1409076B0
IO, IO2, FACTORY, FACTORY2 = 0xBA01, 0xBA02, 0xCA01, 0xCA02
DTOR, ACTIVATE, DESTROY, DISPOSE, DISPOSE2 = 0xDA01, 0xDA02, 0xEA01, 0xEA02, 0xEA03
FREE, FREE2, CALLOC, CALLOC2 = 0xFA01, 0xFA02, 0xFA03, 0xFA04
SCRATCH = ReplayBehaviorSavedScratch(bytes((i * 3 + 7) & 255 for i in range(0xD0)))


def setup(
    tags=(0,),
    *,
    old=(),
    owner_type=1,
    factory=False,
    before=None,
    after=None,
    on_read=None,
    on_write=None,
    control_effect=None,
):
    h = SimpleNamespace()
    h.memory = m = ReplayMemory()
    h.manager, h.output, h.owner, h.stream, h.table, h.table2 = (
        m.allocate(n) for n in (24, 48, 0x189, 8, 0x30, 0x30)
    )
    m.write_bytes(h.output, b"O" * 48)
    m.write_bytes(h.manager, bytes(24))
    m.write(h.manager, 8, h.table)
    m.write(h.manager + 8, 8, h.owner)
    m.write(h.owner + 0x188, 1, owner_type)
    for table, io, method in ((h.table, IO, FACTORY), (h.table2, IO2, FACTORY2)):
        m.write(table, 8, DTOR)
        m.write(table + 8, 8, method)
        m.write(table + 24, 8, io)
        m.write(table + 0x28, 8, ACTIVATE)
    m.write(h.stream, 8, h.table)
    m.map_bytes(0x143199DD0, FREE.to_bytes(8, "little"))
    m.map_bytes(0x143199DC0, CALLOC.to_bytes(8, "little"))
    h.old_nodes, h.old_payloads, h.nodes, h.payloads = [], [], [], []
    for nonnull in old:
        payload = m.allocate(8) if nonnull else 0
        if payload:
            m.write(payload, 8, h.table)
        h.old_payloads.append(payload)
        h.old_nodes.append(m.calloc(1, 16))
    for index, node in enumerate(h.old_nodes):
        m.write(node, 8, h.old_payloads[index])
        m.write(node + 8, 8, h.old_nodes[index + 1] if index + 1 < len(old) else 0)
    if h.old_nodes:
        m.write(h.manager + 0x10, 8, h.old_nodes[0])
    h.frames, h.finished, h.events, h.operations, h.reads, h.factory_tags = [], [], [], [], [], []
    h.tags = tags
    h.source = ReplaySavedInput(b"".join(tag.to_bytes(2, "little") for tag in tags))

    def read(pointer, width):
        value = m.read(pointer, width)
        h.operations.append(("read", pointer, width, value))
        if on_read:
            changed = on_read(h, pointer, width, value)
            if changed is not None:
                return changed
        return value

    def write(pointer, width, value):
        h.operations.append(("write", pointer, width, value))
        m.write(pointer, width, value)
        if on_write:
            on_write(h, pointer, width, value)

    h.context = ReplayTaskRebuildStorage(h.manager, read, write)
    h.atomics = ReplayUnitAIMapAtomics(m.compare_exchange_u32, m.fetch_add_u32)

    def controls(target, args, data):
        if target in (DESTROY, DISPOSE, DISPOSE2):
            if control_effect:
                return control_effect(h, target, args)
            return None  # Explicit shared-control destroy/dispose fixture.
        if target in (FREE, FREE2):
            m.free(args[0])
            return None
        if target == CALLOC2:
            node = m.calloc(*args)
            h.nodes.append(node)
            return node
        raise UnresolvedReplayTaskRebuild(f"unprovided fixture child{target:x}")

    runtime = m.runtime_calls(ReplayTaskRebuildCalls(controls), calloc_target=CALLOC)
    result = bind_replay_saved_result(h.context, runtime, atomics=h.atomics, imports=runtime)
    apply = bind_replay_saved_apply(h.context, result, atomics=h.atomics, imports=runtime)
    first = bind_replay_saved_input(
        h.context, apply, h.source, stream=h.stream, target=IO, result_bytes=bytes(48)
    )
    input_calls = bind_replay_saved_input(
        h.context, first, h.source, stream=h.stream, target=IO2, result_bytes=bytes(48)
    )

    @contextmanager
    def local(view):
        with m.bind_local(view) as pointer:
            h.frames.append((pointer, view))
            try:
                yield pointer
            finally:
                h.finished.append((pointer, view.tobytes()))
                h.frames.pop()

    h.bind_local = local

    def call(target, args, data):
        h.events.append((target, args, data))
        assert data is None
        if before:
            before(h, target, args)
        if target in (IO, IO2):
            frame = h.frames[-1][0]
            assert args == (h.stream, frame + 0x70, frame + 0x68, 2)
            assert m.read_bytes(args[1], 48) == bytes(48)
            h.reads.append(target)
            assert input_calls.call
            answer = input_calls.call(target, args, None)
        elif target in (FACTORY, FACTORY2):
            assert args[:3] == (h.manager, h.frames[-1][0] + 0xA0, h.stream)
            assert m.read_bytes(args[1], 48) == bytes(48)
            h.factory_tags.append(args[3])
            if not factory:
                raise UnresolvedReplayTaskRebuild("actual behavior item factory unavailable")
            if callable(factory):
                answer = factory(h, target, args)
            else:
                answer = m.allocate(8)
                m.write(answer, 8, h.table)
            h.payloads.append(answer)
        elif target in (DTOR, ACTIVATE):
            assert args[1] == (1 if target == DTOR else 0)
            answer = None  # Named payload virtual fixture; no native class claim.
        else:
            assert input_calls.call
            answer = input_calls.call(target, args, None)
            if target == CALLOC:
                h.nodes.append(answer)
        if after:
            changed = after(h, target, args, answer)
            if changed is not None:
                return changed
        return answer

    h.calls = ReplayTaskRebuildCalls(call)
    h.bound = bind_replay_behavior_saved(
        h.context, h.calls, atomics=h.atomics, bind_local=local, scratch=SCRATCH
    )
    return h


def run(h, *, bound=False, scratch=SCRATCH):
    if bound:
        assert h.bound.call
        return h.bound.call(ENTRY, (h.manager, h.output, h.stream), None)
    return read_replay_saved_behavior(
        h.context,
        h.manager,
        h.output,
        h.stream,
        calls=h.calls,
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=scratch,
    )


def control(h, *, strong=1, weak=1):
    m = h.memory
    address = m.allocate(16)
    table = m.allocate(16)
    m.write(table, 8, DESTROY)
    m.write(table + 8, 8, DISPOSE)
    m.write(address, 8, table)
    m.write(address + 8, 4, strong)
    m.write(address + 12, 4, weak)
    return address, table


def current_nodes(h):
    result = []
    pointer = h.memory.read(h.manager + 16, 8)
    while pointer:
        result.append((pointer, h.memory.read(pointer, 8)))
        pointer = h.memory.read(pointer + 8, 8)
    return result


def assert_output_zero(h):
    assert h.memory.read_bytes(h.output, 48) == bytes(41) + b"O" * 7


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("tags", [(0,), (1, 0), (0xFFFF, 2, 0), (7, 7, 1, 0)])
def test_real_owned_stream_allocation_and_ordered_append(tags, bound):
    h = setup(tags, factory=True)
    assert run(h, bound=bound) == h.output
    assert h.factory_tags == list(tags[:-1])
    assert h.source.position == len(tags) * 2
    assert current_nodes(h) == list(zip(h.nodes, h.payloads, strict=True))
    assert h.reads == [IO] * len(tags)
    assert_output_zero(h)
    frame, final = h.finished[0]
    assert int.from_bytes(final[0x60:0x68], "little") == h.output
    assert final[0x68:0x6A] == b"\0\0"
    assert final[0x6A:0x70] == SCRATCH.reader[0x6A:0x70]
    assert not h.frames and frame


@pytest.mark.parametrize("owner_type,activations", [(0, 2), (1, 2), (2, 2), (3, 0), (255, 0)])
def test_old_list_publishes_next_before_dtor_free_then_activation(owner_type, activations):
    h = setup(old=(True, True, True), owner_type=owner_type)
    run(h)
    assert current_nodes(h) == []
    actual = [(target, args) for target, args, _ in h.events if target in (DTOR, FREE, ACTIVATE)]
    expected = []
    for i, node in enumerate(h.old_nodes):
        expected.extend([(DTOR, (h.old_payloads[i], 1)), (FREE, (node,))])
        if i < 2 and owner_type < 3:
            expected.append((ACTIVATE, (h.old_payloads[i + 1], 0)))
    assert actual == expected
    assert sum(target == ACTIVATE for target, _, _ in h.events) == activations
    for node in h.old_nodes:
        with pytest.raises(ReplayMemoryError):
            h.memory.read(node, 8)


def test_null_old_payload_skips_destructor_but_still_frees():
    h = setup(old=(False,))
    run(h)
    assert (FREE, (h.old_nodes[0],), None) in h.events
    assert not any(target == DTOR for target, _, _ in h.events)


def test_current_free_target_after_destructor_and_current_owner_after_free():
    def after(h, target, args, answer):
        if target == DTOR:
            h.memory.write(0x143199DD0, 8, FREE2)
        if target == FREE2:
            h.memory.write(h.owner + 0x188, 1, 3)

    h = setup(old=(True, True), after=after)
    run(h)
    assert sum(target == FREE2 for target, _, _ in h.events) == 2
    assert not any(target == ACTIVATE for target, _, _ in h.events)


def test_activation_uses_held_head_but_next_iteration_reloads_current_head():
    def on_read(h, pointer, width, value):
        if pointer == h.owner + 0x188 and not getattr(h, "changed", False):
            h.changed = True
            h.memory.write(h.manager + 16, 8, 0)

    h = setup(old=(True, True), on_read=on_read)
    run(h)
    assert (ACTIVATE, (h.old_payloads[1], 0), None) in h.events
    assert (FREE, (h.old_nodes[1],), None) not in h.events
    assert h.memory.read(h.old_nodes[1], 8) == h.old_payloads[1]


def test_payload_is_current_after_head_publication_and_failure_keeps_publication():
    def on_write(h, pointer, width, value):
        if pointer == h.manager + 16 and value == h.old_nodes[1]:
            h.memory.write(h.old_nodes[0], 8, 0)

    h = setup(old=(True, True), owner_type=3, on_write=on_write)
    run(h)
    destroyed = [args[0] for target, args, _ in h.events if target == DTOR]
    assert destroyed == [h.old_payloads[1]]


@pytest.mark.parametrize("failure_target", [DTOR, FREE, ACTIVATE])
def test_old_clear_failure_preserves_prefix_and_never_reads_tag(failure_target):
    def before(h, target, args):
        if target == failure_target:
            raise RuntimeError("qualified child failure")

    h = setup(old=(True, True), before=before)
    with pytest.raises(RuntimeError, match="qualified child"):
        run(h)
    assert h.memory.read(h.manager + 16, 8) == h.old_nodes[1]
    assert h.source.position == 0
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48
    assert not h.frames


def test_tag_stays_seeded_until_actual_input_and_cleanup_can_replace_it():
    def before(h, target, args):
        if target == IO and not getattr(h, "seen", False):
            h.seen = True
            assert h.memory.read(args[2], 2) == int.from_bytes(SCRATCH.reader[0x68:0x6A], "little")
        if target == CLEANUP and args[0] == h.frames[-1][0] + 0x70:
            h.memory.write(h.frames[-1][0] + 0x68, 2, 0)

    h = setup((0xFFFF,), before=before)
    run(h)
    assert h.seen and not h.factory_tags
    assert_output_zero(h)


def test_item_clear_write_order_and_processed_before_status():
    h = setup((3, 0), factory=True)
    run(h)
    frame = h.finished[0][0]
    relevant = [row[:3] for row in h.operations if frame + 0xA0 <= row[1] < frame + 0xD0]
    assert relevant[:6] == [
        ("write", frame + 0xC0, 16),
        ("write", frame + 0xA0, 16),
        ("write", frame + 0xB0, 16),
        ("write", frame + 0xC0, 8),
        ("write", frame + 0xC8, 1),
        ("write", frame + 0xC8, 1),
    ]
    assert relevant[6] == ("read", frame + 0xB8, 8)


def test_current_manager_factory_and_calloc_target_not_cached():
    def after(h, target, args, answer):
        if target == CLEANUP and args[0] == h.frames[-1][0] + 0x70:
            h.memory.write(h.manager, 8, h.table2)
            h.memory.write(0x143199DC0, 8, CALLOC2)

    h = setup((11, 0), factory=True, after=after)
    run(h)
    assert h.factory_tags == [11]
    assert (FACTORY2, (h.manager, h.finished[0][0] + 0xA0, h.stream, 11), None) in h.events
    assert (CALLOC2, (1, 16), None) in h.events


def test_stream_virtual_reloaded_for_next_tag_after_item_cleanup():
    def after(h, target, args, answer):
        if target == CLEANUP and args[0] == h.frames[-1][0] + 0xA0:
            h.memory.write(h.stream, 8, h.table2)

    h = setup((4, 0), factory=True, after=after)
    run(h)
    assert h.reads == [IO, IO2]


def test_held_payload_across_processed_status_and_allocation_callbacks():
    def factory(h, target, args):
        return 0xFEDCBA9876543210

    def on_write(h, pointer, width, value):
        if h.frames and pointer == h.frames[-1][0] + 0xC8 and value == 1:
            frame = h.frames[-1][0]
            vector = h.memory.calloc(1, 32)
            h.memory.write(frame + 0xA0, 8, vector)
            h.memory.write(frame + 0xA8, 8, vector)
            h.memory.write(frame + 0xB0, 8, vector + 32)

    h = setup((5, 0), factory=factory, on_write=on_write)
    run(h)
    assert current_nodes(h)[0][1] == 0xFEDCBA9876543210


def test_held_tail_survives_cleanup_replacing_manager_head():
    def after(h, target, args, answer):
        if target == CLEANUP and args[0] == h.frames[-1][0] + 0xA0:
            h.memory.write(h.manager + 16, 8, 0)

    h = setup((5, 6, 0), factory=True, after=after)
    run(h)
    assert current_nodes(h) == []
    assert h.memory.read(h.nodes[0] + 8, 8) == h.nodes[1]
    assert h.memory.read(h.nodes[1], 8) == h.payloads[1]


def test_item_null_payload_still_appends_and_later_zero_returns():
    h = setup((5, 0), factory=lambda h, target, args: 0)
    run(h)
    assert current_nodes(h) == [(h.nodes[0], 0)]


@pytest.mark.parametrize("error_phase", ["first_tag", "later_tag"])
def test_tag_errors_refuse_before_processed_release_or_tls(error_phase):
    def after(h, target, args, answer):
        if target in (IO, IO2) and len(h.reads) == (1 if error_phase == "first_tag" else 2):
            h.bad_result = args[1]
            h.bad_control, _ = control(h)
            h.memory.write(args[1] + 24, 8, 9)
            h.memory.write(args[1] + 32, 8, h.bad_control)

    h = setup((3, 0), factory=True, after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="metadata/TLS"):
        run(h)
    raw = h.finished[0][1]
    assert raw[0x98] == 0
    assert h.memory.read(h.bad_control + 8, 4) == 1
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48
    assert len(current_nodes(h)) == (0 if error_phase == "first_tag" else 1)
    assert not any(target == FORWARD for target, _, _ in h.events)


def test_item_error_uses_real_forward_then_control_release_and_cleanup():
    def factory(h, target, args):
        h.item_control, _ = control(h)
        h.memory.write(args[1] + 24, 8, 0x1122334455667788)
        h.memory.write(args[1] + 32, 8, h.item_control)
        return 0x1234

    h = setup((5,), factory=factory)
    assert run(h) == h.output
    assert h.memory.read(h.output + 24, 8) == 0x1122334455667788
    assert h.memory.read(h.output + 32, 8) == h.item_control
    assert h.memory.read(h.item_control + 8, 4) == 1  # real +1 forward, then -1 release
    assert h.memory.read_bytes(h.output + 41, 7) == b"O" * 7
    assert current_nodes(h) == [] and h.nodes == []
    assert h.source.position == 2
    events = [target for target, _, _ in h.events]
    assert events.index(FORWARD) < len(events) - 1
    assert events[-1] == CLEANUP
    assert h.finished[0][1][0xC8] == 1


def test_item_error_forward_refusal_keeps_processed_and_no_extra_release():
    def factory(h, target, args):
        h.item_control, _ = control(h)
        h.memory.write(args[1] + 24, 8, 4)
        h.memory.write(args[1] + 32, 8, h.item_control)
        return 0

    def before(h, target, args):
        if target == FORWARD:
            raise UnresolvedReplayTaskRebuild("mandatory forward unavailable")

    h = setup((8,), factory=factory, before=before)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="mandatory forward"):
        run(h)
    assert h.finished[0][1][0xC8] == 1
    assert h.memory.read(h.item_control + 8, 4) == 1
    assert h.nodes == []


def test_item_status_observes_processed_store_mutation():
    def on_write(h, pointer, width, value):
        if h.frames and pointer == h.frames[-1][0] + 0xC8 and value == 1:
            h.memory.write(h.frames[-1][0] + 0xB8, 8, 7)

    h = setup((4,), factory=True, on_write=on_write)
    run(h)
    assert h.memory.read(h.output + 24, 8) == 7
    assert not h.nodes


@pytest.mark.parametrize(
    "strong,weak,expected", [(2, 1, []), (1, 2, [DESTROY]), (1, 1, [DESTROY, DISPOSE])]
)
def test_tag_real_atomic_control_release(strong, weak, expected):
    def after(h, target, args, answer):
        if target == IO:
            h.saved_control, _ = control(h, strong=strong, weak=weak)
            h.memory.write(args[1] + 32, 8, h.saved_control)

    h = setup(after=after)
    run(h)
    assert [target for target, _, _ in h.events if target in (DESTROY, DISPOSE)] == expected
    assert h.memory.read(h.saved_control + 8, 4) == strong - 1


def test_control_held_across_destroy_current_vtable_and_result_replacements():
    def after(h, target, args, answer):
        if target == IO:
            h.saved_control, h.control_table = control(h)
            h.replacement, _ = control(h, strong=9, weak=9)
            h.memory.write(args[1] + 32, 8, h.saved_control)

    def effect(h, target, args):
        if target == DESTROY:
            h.memory.write(h.frames[-1][0] + 0x90, 8, h.replacement)
            h.memory.write(h.control_table + 8, 8, DISPOSE2)

    h = setup(after=after, control_effect=effect)
    run(h)
    assert (DISPOSE2, (h.saved_control,), None) in h.events
    assert h.memory.read(h.saved_control + 12, 4) == 0
    assert h.memory.read(h.replacement + 8, 4) == 9


@pytest.mark.parametrize("failure_target", [CALLOC, CLEANUP])
def test_append_failure_preserves_exact_prefix(failure_target):
    def before(h, target, args):
        if target == failure_target and (target == CALLOC or args[0] == h.frames[-1][0] + 0xA0):
            raise RuntimeError("qualified failure")

    h = setup((3, 0), factory=True, before=before)
    with pytest.raises(RuntimeError, match="qualified failure"):
        run(h)
    assert len(current_nodes(h)) == (0 if failure_target == CALLOC else 1)
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48
    assert h.source.position == 2


def test_unterminated_stream_refuses_with_published_nodes_retained():
    h = setup((2,), factory=True)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="remaining bytes"):
        run(h)
    assert len(current_nodes(h)) == 1
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


def test_missing_factory_is_mandatory_before_allocation():
    h = setup((3,))
    with pytest.raises(UnresolvedReplayTaskRebuild, match="factory unavailable"):
        run(h)
    assert h.source.position == 2 and h.nodes == []
    assert h.finished[0][1][0xC8] == 0


@pytest.mark.parametrize("raw", [b"", bytes(0xCF), bytes(0xD1), bytearray(0xD0)])
def test_exact_seed_required(raw):
    with pytest.raises(ValueError, match="D0-byte"):
        ReplayBehaviorSavedScratch(raw)


@pytest.mark.parametrize(
    "args,data", [((1, 2), None), ((1, 2, 3, 4), None), ((1, 2, 3), memoryview(b"x"))]
)
def test_binder_strict_actual_arity(args, data):
    h = setup()
    assert h.bound.call
    with pytest.raises(ValueError, match="malformed"):
        h.bound.call(ENTRY, args, data)
    assert h.events == []


def test_binder_unknown_delegate_and_refusal():
    h = setup()
    assert h.bound.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unprovided fixture"):
        h.bound.call(0xDEADC0DE, (), None)
    bound = bind_replay_behavior_saved(
        h.context,
        ReplayTaskRebuildCalls(None),
        atomics=h.atomics,
        bind_local=h.bind_local,
        scratch=SCRATCH,
    )
    assert bound.call
    with pytest.raises(UnresolvedReplayTaskRebuild, match="unavailable"):
        bound.call(0xDEADC0DE, (), None)


def test_current_owner_pointer_and_head_after_actual_free_callback():
    def after(h, target, args, answer):
        if target == FREE and not getattr(h, "swapped", False):
            h.swapped = True
            owner = h.memory.allocate(0x189)
            h.memory.write(owner + 0x188, 1, 3)
            h.memory.write(h.manager + 8, 8, owner)
            h.memory.write(h.manager + 16, 8, 0)

    h = setup(old=(True, True), after=after)
    run(h)
    assert not any(target == ACTIVATE for target, _, _ in h.events)
    assert h.memory.read(h.old_nodes[1], 8) == h.old_payloads[1]
    assert h.source.position == 2


def test_tag_status_is_read_before_processed_store_and_not_retested():
    def on_write(h, pointer, width, value):
        if h.frames and pointer == h.frames[-1][0] + 0x98 and value == 1:
            h.memory.write(h.frames[-1][0] + 0x88, 8, 0xABCD)

    h = setup(on_write=on_write)
    run(h)
    assert_output_zero(h)
    assert h.finished[0][1][0x88:0x90] == (0xABCD).to_bytes(8, "little")


def test_tag_stream_target_is_read_after_all_three_result_clear_stores():
    def on_write(h, pointer, width, value):
        if h.frames and pointer == h.frames[-1][0] + 0x90 and width == 16:
            h.memory.write(h.stream, 8, h.table2)

    h = setup(on_write=on_write)
    run(h)
    assert h.reads == [IO2]


def test_item_control_reloaded_after_allocation_and_link_publication():
    def factory(h, target, args):
        h.before_control, _ = control(h)
        h.after_control, _ = control(h)
        h.memory.write(args[1] + 32, 8, h.before_control)
        return 0

    def after(h, target, args, answer):
        if target == CALLOC:
            h.memory.write(h.frames[-1][0] + 0xC0, 8, h.after_control)

    h = setup((3, 0), factory=factory, after=after)
    run(h)
    assert h.memory.read(h.before_control + 8, 4) == 1
    assert h.memory.read(h.after_control + 8, 4) == 0
    assert (DESTROY, (h.after_control,), None) in h.events
    assert current_nodes(h) == [(h.nodes[0], 0)]


def test_null_allocation_still_attempts_first_node_store_without_publication():
    def after(h, target, args, answer):
        if target == CALLOC:
            return 0

    h = setup((3, 0), factory=True, after=after)
    with pytest.raises(ReplayMemoryError):
        run(h)
    assert h.memory.read(h.manager + 16, 8) == 0
    assert h.operations[-1] == ("write", 0, 8, h.payloads[0])
    assert h.finished[0][1][0xC8] == 1
    assert h.source.position == 2


@pytest.mark.parametrize("field", [0, 8])
def test_node_store_failure_retains_allocation_and_prior_store_without_append(field):
    def on_write(h, pointer, width, value):
        if h.nodes and pointer == h.nodes[-1] + field:
            raise RuntimeError("after actual node store")

    h = setup((3, 0), factory=True, on_write=on_write)
    with pytest.raises(RuntimeError, match="actual node store"):
        run(h)
    assert h.memory.read(h.nodes[0], 8) == h.payloads[0]
    assert h.memory.read(h.manager + 16, 8) == 0
    assert h.source.position == 2
    assert len(h.nodes) == 1


def test_success_output_uses_held_argument_not_mutated_local_copy():
    def after(h, target, args, answer):
        if target == CLEANUP:
            h.memory.write(h.frames[-1][0] + 0x60, 8, 0)

    h = setup(after=after)
    assert run(h) == h.output
    assert_output_zero(h)
    assert h.finished[0][1][0x60:0x68] == bytes(8)


def test_input_rax_ignored_when_actual_result_is_success():
    def after(h, target, args, answer):
        if target == IO:
            return 0xBADBAD

    h = setup(after=after)
    run(h)
    assert_output_zero(h)


def test_atomic_missing_refuses_before_cleanup_and_tag_readback():
    def after(h, target, args, answer):
        if target == IO:
            h.saved_control, _ = control(h)
            h.memory.write(args[1] + 32, 8, h.saved_control)

    h = setup(after=after)
    h.atomics = ReplayUnitAIMapAtomics(None, None)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="atomic effect"):
        run(h)
    assert h.memory.read(h.saved_control + 8, 4) == 1
    assert h.finished[0][1][0x98] == 1
    assert not any(target == CLEANUP for target, _, _ in h.events)
    assert h.memory.read_bytes(h.output, 48) == b"O" * 48


def test_tag_vector_cleanup_failure_prevents_tag_test_without_fake_release():
    def after(h, target, args, answer):
        if target == IO:
            vector = h.memory.calloc(1, 32)
            h.memory.write(args[1], 8, vector)
            h.memory.write(args[1] + 8, 8, vector + 32)
            h.memory.write(args[1] + 16, 8, vector + 32)

    h = setup((2,), after=after)
    with pytest.raises(UnresolvedReplayTaskRebuild, match="1402a88a0"):
        run(h)
    assert h.factory_tags == [] and h.nodes == []
    assert h.finished[0][1][0x98] == 1


@pytest.mark.parametrize("old", [(False, True), (True, False)])
def test_old_activation_null_payload_has_no_invented_null_skip(old):
    h = setup(old=old)
    if old[1]:
        run(h)
        assert (ACTIVATE, (h.old_payloads[1], 0), None) in h.events
    else:
        with pytest.raises(ReplayMemoryError):
            run(h)
        assert h.source.position == 0
        assert h.memory.read(h.manager + 16, 8) == h.old_nodes[1]
