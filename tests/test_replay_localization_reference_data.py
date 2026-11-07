"""Authored finite reference-data controls; no selected replay/profile inference."""

import hashlib

import pytest

from vantage.replay_localization_alias import (
    ReplayLocalizationAliasProfile,
    ReplayLocalizationAliasScratch,
    bind_replay_localization_alias,
)
from vantage.replay_localization_alias_growth import (
    ReplayLocalizationAliasGrowthProfile,
    ReplayLocalizationAliasGrowthScratch,
    bind_replay_localization_alias_growth,
)
from vantage.replay_localization_reference_data import (
    ReplayLocalizationReferenceData,
    ReplayLocalizationReferenceEntry,
    ReplayLocalizationReferenceRecord,
    create_replay_localization_reference_context,
    populate_replay_localization_references,
    read_replay_localization_references_ascii,
)
from vantage.replay_localization_runtime import (
    ReplayLocalizationRuntime,
    ReplayLocalizationTargets,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_memory_compare import (
    bind_replay_memcmp_thunk,
    replay_memory_comparison_calls,
)
from vantage.replay_player_localization_catalog import (
    ReplayLocalizationCatalogProfile,
    bind_replay_player_localization_catalog,
)
from vantage.replay_saved_string import bind_replay_saved_string
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)
from vantage.replay_unit_constructor_support import bind_replay_unit_constructor_support

INSERT_VALUE, DESTROY = 0x140962270, 0x1402A88A0
TOKENS = ReplayLocalizationTargets(0xE00010, 0xE00020, 0xE00030, 0xE00040, 0xE00050)


def runtime(memory):
    return ReplayLocalizationRuntime(memory, TOKENS, delegate=memory.runtime_calls())


def test_full_root_integer_reader_sorts_byte_keys_and_keeps_last_duplicate_with_offsets():
    raw = b' \r\n{ "z": -0, "A": -2147483648,\t"b":2147483647, "A":1001 }\n'
    data = read_replay_localization_references_ascii(raw)
    assert tuple((entry.key, entry.value) for entry in data.entries) == (
        (b"A", 1001),
        (b"b", 2147483647),
        (b"z", 0),
    )
    assert data.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert [record.entry.value for record in data.records] == [0, -2147483648, 2147483647, 1001]
    for record in data.records:
        assert raw[record.record_offset : record.key_offset] == b'"'
        assert (
            raw[record.key_offset : record.key_offset + len(record.entry.key)] == record.entry.key
        )
        assert raw[record.key_offset + len(record.entry.key)] == 0x22
        token = raw[record.value_offset : record.record_end]
        assert int(token) == record.entry.value
    assert raw[data.records[0].value_offset : data.records[0].record_end] == b"-0"
    assert data.records[1].record_offset == raw.index(b'"A"')
    assert data.records[-1].record_offset == raw.rindex(b'"A"')


def test_authored_genuine_reference_pairs_preserve_exact_key_bytes_and_ids():
    # Exact key/ID pairs in pinned installed stringreference.json. This raw
    # sample is authored unit data, not the selected native resource/profile.
    raw = b'{"IDS_TEXT_CLOSE_BUTTON":1002,"IDS_PROGRAM_TITLE":1001,"IDS_MSG_LOADING_DATA":1101}'
    data = read_replay_localization_references_ascii(raw)
    assert tuple((entry.key, entry.value) for entry in data.entries) == (
        (b"IDS_MSG_LOADING_DATA", 1101),
        (b"IDS_PROGRAM_TITLE", 1001),
        (b"IDS_TEXT_CLOSE_BUTTON", 1002),
    )
    assert data.records[0].record_offset == 1
    assert data.records[0].key_offset == 2
    assert data.records[0].value_offset == raw.index(b"1002")
    assert data.records[0].record_end == raw.index(b",")


@pytest.mark.parametrize("raw", [b"{}", b" \t{\r\n}\n"])
def test_explicit_empty_root_is_data_without_inferred_active_or_catalog_state(raw):
    data = read_replay_localization_references_ascii(raw)
    assert data.entries == data.records == ()
    assert data.source_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("key", [b" ", b"0", b"punctuation !#$%&()*+,-./:;<=>?@[]^_`{|}~"])
def test_plain_nonempty_printable_ascii_keys_are_byte_exact(key):
    data = read_replay_localization_references_ascii(b'{"' + key + b'":-1}')
    assert data.entries == (ReplayLocalizationReferenceEntry(key, -1),)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"null",
        b"1",
        b'"x"',
        b"{",
        b'{"a"}',
        b"{a:1}",
        b'{"":1}',
        b'{"a":}',
        b'{"a":+1}',
        b'{"a":01}',
        b'{"a":-01}',
        b'{"a":--1}',
        b'{"a":1.0}',
        b'{"a":1e2}',
        b'{"a":true}',
        b'{"a":false}',
        b'{"a":null}',
        b'{"a":[]}',
        b'{"a":{}}',
        b'{"a":2147483648}',
        b'{"a":-2147483649}',
        b'{"a":999999999999999999999999999999999999999999999999999}',
        b'{"a":1,}',
        b'{"a":1 "b":2}',
        b'{"a":1}{}',
        b'{"a":1}\0',
        b'\xef\xbb\xbf{"a":1}',
        b'{"a":1}//comment',
        b'{/*x*/"a":1}',
        b'{"a\\b":1}',
        b'{"a\\u0041":1}',
        b'{"a\\"b":1}',
        b'{"a\nb":1}',
        b'{"a\x00b":1}',
        b'{"a\x7fb":1}',
        b'{"a\x80b":1}',
        b'{"a":1}\v',
    ],
)
def test_outside_finite_complete_json_domain_refuses(raw):
    with pytest.raises(ValueError):
        read_replay_localization_references_ascii(raw)


@pytest.mark.parametrize("raw", ["", bytearray(b"{}"), memoryview(b"{}"), None])
def test_reader_requires_explicit_bytes(raw):
    with pytest.raises(ValueError):
        read_replay_localization_references_ascii(raw)


@pytest.mark.parametrize(
    "key,value",
    [
        (b"", 1),
        ("a", 1),
        (b"\0", 1),
        (b"\\", 1),
        (b'"', 1),
        (b"\xff", 1),
        (b"a", True),
        (b"a", 1.0),
        (b"a", 1 << 31),
        (b"a", -(1 << 31) - 1),
    ],
)
def test_entry_direct_construction_requires_exact_key_and_signed32_domain(key, value):
    with pytest.raises(ValueError):
        ReplayLocalizationReferenceEntry(key, value)


def test_direct_data_checks_order_uniqueness_digest_and_last_occurrence_consistency():
    first = ReplayLocalizationReferenceEntry(b"a", 1)
    second = ReplayLocalizationReferenceEntry(b"b", 2)
    digest = "a" * 64
    for entries, supplied in (
        ((second, first), digest),
        ((first, first), digest),
        ((first,), "A" * 64),
        ((first,), "x" * 64),
        ((first,), "a" * 63),
        ([first], digest),
    ):
        with pytest.raises(ValueError):
            ReplayLocalizationReferenceData(entries, supplied)
    record = ReplayLocalizationReferenceRecord(first, 1, 2, 5, 6)
    with pytest.raises(ValueError, match="last occurrence"):
        ReplayLocalizationReferenceData((second,), digest, (record,))
    with pytest.raises(ValueError, match="source order"):
        ReplayLocalizationReferenceData((first,), digest, (record, record))
    with pytest.raises(ValueError, match="spans"):
        ReplayLocalizationReferenceRecord(first, 1, 2, 3, 6)


def test_sparse_reference_context_matches_map_shape_and_leaves_all_unproved_fields_undefined():
    memory = ReplayMemory()
    services = runtime(memory)
    context = create_replay_localization_reference_context(memory, runtime=services)
    manager, table = context.subject, context.subject + 0x240
    sentinel, buckets = memory.read(table + 8, 8), memory.read(table + 0x18, 8)
    assert context.read == memory.read and context.write == memory.write
    assert memory.mapped_bytes == 0x2D0 + 56 + 128
    assert memory.read(table, 4) == 0x3F800000
    assert memory.read(table + 0x10, 8) == 0
    assert memory.read(table + 0x20, 8) == memory.read(table + 0x28, 8) == buckets + 128
    assert memory.read(table + 0x30, 8) == 7
    assert memory.read(table + 0x38, 8) == 8
    assert memory.read(sentinel, 8) == memory.read(sentinel + 8, 8) == sentinel
    assert [memory.read(buckets + index * 8, 8) for index in range(16)] == [sentinel] * 16
    assert memory.read(manager + 0x2CC, 4) == 0
    for address, width in (
        (manager, 8),
        (manager + 8, 4),
        (manager + 0x70, 8),
        (manager + 0x88, 8),
        (manager + 0xA0, 8),
        (manager + 0x1C0, 8),
        (manager + 0x239, 1),
        (manager + 0x280, 4),
        (table + 4, 4),
        (sentinel + 0x10, 8),
        (0x1442842E8, 8),
        (0x143199940, 8),
        (0x143199DD0, 8),
    ):
        with pytest.raises(ReplayMemoryError):
            memory.read(address, width)
    calls = services.calls()
    assert calls.call(TOKENS.lock, (manager + 0x280,), None) == 0
    assert memory.read(manager + 0x2CC, 4) == 1
    assert calls.call(TOKENS.unlock, (manager + 0x280,), None) == 0


def test_builder_rejects_different_owned_memory_before_allocations_or_writes():
    memory, other = ReplayMemory(), ReplayMemory()
    before, other_before = memory.snapshot(), other.snapshot()
    with pytest.raises(ValueError, match="same owned memory"):
        create_replay_localization_reference_context(memory, runtime=runtime(other))
    assert memory.snapshot() == before and other.snapshot() == other_before


def test_builder_preserves_prior_allocations_on_later_budget_failure():
    memory = ReplayMemory(max_bytes=800)
    with pytest.raises(MemoryError):
        create_replay_localization_reference_context(memory, runtime=runtime(memory))
    assert memory.mapped_bytes == 0x2D0 + 56
    assert len(memory.snapshot().regions) == 2


@pytest.mark.parametrize("binding", ["foreign", "wrapped-read", "wrapped-write"])
def test_populator_requires_same_direct_memory_bindings_before_any_effect(binding):
    memory, other = ReplayMemory(), ReplayMemory()
    context = create_replay_localization_reference_context(memory, runtime=runtime(memory))
    if binding == "foreign":
        context = ReplayTaskRebuildStorage(context.subject, other.read, other.write)
    elif binding == "wrapped-read":
        context = ReplayTaskRebuildStorage(
            context.subject, lambda a, n: memory.read(a, n), memory.write
        )
    else:
        context = ReplayTaskRebuildStorage(
            context.subject,
            memory.read,
            lambda a, n, v: memory.write(a, n, v),
        )
    data = read_replay_localization_references_ascii(b'{"a":1}')
    before = memory.snapshot()
    with pytest.raises(ValueError, match="direct context methods"):
        populate_replay_localization_references(
            memory, context, data, calls=ReplayTaskRebuildCalls(None)
        )
    assert memory.snapshot() == before


def test_explicit_empty_data_population_has_no_helper_or_memory_effect():
    memory = ReplayMemory()
    context = create_replay_localization_reference_context(memory, runtime=runtime(memory))
    before = memory.snapshot()
    populate_replay_localization_references(
        memory,
        context,
        read_replay_localization_references_ascii(b"{}"),
        calls=ReplayTaskRebuildCalls(None),
    )
    assert memory.snapshot() == before


@pytest.mark.parametrize("key,value", [(b"alpha", -1), (b"IDS_PROGRAM_TITLE", 1001)])
def test_reached_insert_requires_actual_child_with_live_descriptor_output_and_no_fake_cleanup(
    key, value
):
    memory = ReplayMemory()
    context = create_replay_localization_reference_context(memory, runtime=runtime(memory))
    data = ReplayLocalizationReferenceData(
        (ReplayLocalizationReferenceEntry(key, value),), "a" * 64
    )
    before = memory.mapped_bytes
    observed = []
    heap = []

    def refuse(target, args, payload):
        observed.append((target, args, payload))
        assert target == INSERT_VALUE and payload is None
        table, output, source = args
        assert table == context.subject + 0x240
        assert memory.read(source + 0x10, 8) == len(key)
        assert memory.read(source + 0x20, 4) == value & 0xFFFFFFFF
        assert memory.read_bytes(output, 16) == bytes(16)
        if len(key) > 15:
            assert memory.read(source + 0x18, 8) == len(key)
            heap.append(memory.read(source, 8))
            assert memory.read_bytes(heap[0], len(key) + 1) == key + b"\0"
        else:
            assert memory.read(source + 0x18, 8) == 15
            assert memory.read_bytes(source, len(key) + 1) == key + b"\0"
        raise UnresolvedReplayTaskRebuild("actual insertion not supplied by this interface control")

    with pytest.raises(UnresolvedReplayTaskRebuild, match="actual insertion not supplied"):
        populate_replay_localization_references(
            memory, context, data, calls=ReplayTaskRebuildCalls(refuse)
        )
    assert len(observed) == 1  # The refuser never returns fake child success.
    assert all(target != DESTROY for target, _, _ in observed)
    for local in observed[0][1][1:]:
        with pytest.raises(ReplayMemoryError):
            memory.read(local, 1)
    assert memory.read(context.subject + 0x250, 8) == 0
    assert memory.mapped_bytes == before + (len(key) + 1 if heap else 0)
    if heap:
        assert memory.read_bytes(heap[0], len(key) + 1) == key + b"\0"


def test_unavailable_dispatcher_refuses_at_actual_insert_after_preceding_heap_setup():
    memory = ReplayMemory()
    context = create_replay_localization_reference_context(memory, runtime=runtime(memory))
    before = memory.mapped_bytes
    data = read_replay_localization_references_ascii(b'{"IDS_PROGRAM_TITLE":1001}')
    with pytest.raises(UnresolvedReplayTaskRebuild, match="reached140962270 is unavailable"):
        populate_replay_localization_references(
            memory, context, data, calls=ReplayTaskRebuildCalls(None)
        )
    assert memory.mapped_bytes == before + len(b"IDS_PROGRAM_TITLE\0")
    assert memory.snapshot()  # Both borrowed local mappings have expired.


def source_reference_services(data, *, populate=True):
    """Explicit owned services for genuine payload insertion and alias lookup."""
    memory = ReplayMemory(max_bytes=8 << 20)
    service_runtime = ReplayLocalizationRuntime(
        memory,
        TOKENS,
        delegate=replay_memory_comparison_calls(
            memory,
            comparison_target=0xD00010,
            strlen_target=0xD00020,
        ),
    )
    context = create_replay_localization_reference_context(memory, runtime=service_runtime)
    for slot, target in (
        (0x143199940, 0xD00010),
        (0x14319A290, 0xD00020),
        (0x143199930, 0x142D6E3DB),
        (0x143199DD0, 0x142D6BAB4),
        (0x143199288, TOKENS.lock),
        (0x143199280, TOKENS.unlock),
        (0x143199278, TOKENS.error),
        (0x143199EF0, 0x142D6E453),
    ):
        memory.map_bytes(slot, target.to_bytes(8, "little"))
    memory.map_bytes(0x1436A0308, (0x5F000000).to_bytes(4, "little"))
    services = service_runtime.calls()
    routes, events = {}, []

    def dispatch(target, args, payload):
        events.append((target, args))
        selected = routes.get(target, services)
        assert selected.call is not None
        return selected.call(target, args, payload)

    calls = ReplayTaskRebuildCalls(dispatch)
    alias = bind_replay_localization_alias(
        context,
        calls,
        bind_local=memory.bind_local,
        scratch=ReplayLocalizationAliasScratch(bytes(0xA0), bytes(0x40)),
        profile=ReplayLocalizationAliasProfile(1 << 20, 1 << 16),
        imports=services,
    )
    growth = bind_replay_localization_alias_growth(
        context,
        calls,
        bind_local=memory.bind_local,
        scratch=ReplayLocalizationAliasGrowthScratch(bytes(8), bytes(32), bytes(8)),
        profile=ReplayLocalizationAliasGrowthProfile(1 << 20, 1 << 16, 1 << 20, 1 << 20, 0x1F80),
        imports=services,
    )
    compare = bind_replay_memcmp_thunk(context, calls, imports=services)
    catalog = bind_replay_player_localization_catalog(
        context,
        calls,
        profile=ReplayLocalizationCatalogProfile(0, 0, 0, 0),
        imports=services,
    )
    support = bind_replay_unit_constructor_support(
        context,
        calls,
        bind_local=memory.bind_local,
        imports=services,
    )
    strings = bind_replay_saved_string(context, calls, imports=services)
    for targets, selected in (
        ((0x140964460, 0x140961D10, 0x140961DE0, INSERT_VALUE), alias),
        ((0x140969420, 0x140969930, 0x1409691F0, 0x1409624E0, 0x140969EE0, 0x142D6E453), growth),
        ((0x142D6E3BD,), compare),
        ((0x142D6AA5B, 0x142D6AA61, 0x142D6AA67), catalog),
        ((0x142D6E44D, 0x142D6E3B1, 0x142D6C268, 0x142D6C270), support),
        ((DESTROY,), strings),
    ):
        routes.update(dict.fromkeys(targets, selected))
    if populate:
        populate_replay_localization_references(memory, context, data, calls=calls)
    return memory, context, calls, events


def lookup_reference(memory, context, calls, key):
    pointer = memory.allocate(len(key) + 1)
    memory.write_bytes(pointer, key + b"\0")
    try:
        assert calls.call is not None
        return calls.call(0x140964460, (context.subject, pointer), None)
    finally:
        memory.free(pointer)


@pytest.mark.parametrize(
    "key,value",
    [
        (b"IDS_PROGRAM_TITLE", 1001),
        (b"IDS_TEXT_CLOSE_BUTTON", 1002),
        (b"negative", -2147483648),
        (b"zero", 0),
    ],
)
def test_reference_payload_population_and_numeric_lookup_use_actual_source_children(key, value):
    data = read_replay_localization_references_ascii(
        b'{"' + key + b'":' + str(value).encode() + b"}",
    )
    memory, context, calls, events = source_reference_services(data)
    assert lookup_reference(memory, context, calls, key) == value & 0xFFFFFFFF
    assert memory.read(context.subject + 0x250, 8) == 1
    assert memory.read(context.subject + 0x2CC, 4) == 0
    targets = [target for target, _ in events]
    assert INSERT_VALUE in targets and DESTROY in targets
    assert 0x140961DE0 in targets and 0x140961D10 in targets and 0x142D6E3BD in targets
    for address in (context.subject + 0x239, context.subject + 0x88, 0x1442842E8):
        with pytest.raises(ReplayMemoryError):
            memory.read(address, 1)


def test_reference_population_really_grows_twice_and_preserves_every_inserted_id():
    raw = (
        b"{"
        + b",".join(
            b'"IDS_KEY_' + f"{index:03d}".encode() + b'":' + str(index + 1).encode()
            for index in range(65)
        )
        + b"}"
    )
    data = read_replay_localization_references_ascii(raw)
    memory, context, calls, events = source_reference_services(data)
    assert memory.read(context.subject + 0x250, 8) == 65
    assert memory.read(context.subject + 0x270, 8) == 511
    assert memory.read(context.subject + 0x278, 8) == 512
    assert [args for target, args in events if target == 0x140969420] == [
        (context.subject + 0x240, 9),
        (context.subject + 0x240, 65),
    ]
    for entry in data.entries:
        assert lookup_reference(memory, context, calls, entry.key) == entry.value
    assert memory.read(context.subject + 0x2CC, 4) == 0


def test_repeated_existing_key_retains_native_id_and_really_destroys_unmoved_heap_temporary():
    data = read_replay_localization_references_ascii(b'{"IDS_PROGRAM_TITLE":1001}')
    memory, context, calls, events = source_reference_services(data)
    before = memory.mapped_bytes
    second = read_replay_localization_references_ascii(b'{"IDS_PROGRAM_TITLE":2002}')
    events.clear()
    assert calls.call is not None
    real_calls, temporary_heap = calls.call, []

    def observe_cleanup(target, args, payload):
        if target == DESTROY:
            temporary_heap.append(memory.read(args[0], 8))
        return real_calls(target, args, payload)

    populate_replay_localization_references(
        memory,
        context,
        second,
        calls=ReplayTaskRebuildCalls(observe_cleanup),
    )
    assert memory.mapped_bytes == before
    assert memory.read(context.subject + 0x250, 8) == 1
    assert lookup_reference(memory, context, calls, b"IDS_PROGRAM_TITLE") == 1001
    assert len(temporary_heap) == 1
    with pytest.raises(ReplayMemoryError):
        memory.read(temporary_heap[0], 1)


def test_required_string_cleanup_refusal_preserves_actual_inserted_node_and_expires_locals():
    data = read_replay_localization_references_ascii(b'{"IDS_PROGRAM_TITLE":1001}')
    memory, context, calls, events = source_reference_services(data, populate=False)
    assert calls.call is not None
    real_calls = calls.call

    def cleanup_refuser(target, args, payload):
        if target == DESTROY:
            raise UnresolvedReplayTaskRebuild("required string cleanup unavailable")
        return real_calls(target, args, payload)

    with pytest.raises(UnresolvedReplayTaskRebuild, match="required string cleanup unavailable"):
        populate_replay_localization_references(
            memory,
            context,
            data,
            calls=ReplayTaskRebuildCalls(cleanup_refuser),
        )
    assert memory.read(context.subject + 0x250, 8) == 1
    assert lookup_reference(memory, context, calls, b"IDS_PROGRAM_TITLE") == 1001
    output, source = next(args[1:] for target, args in events if target == INSERT_VALUE)
    for address in (output, source):
        with pytest.raises(ReplayMemoryError):
            memory.read(address, 1)
