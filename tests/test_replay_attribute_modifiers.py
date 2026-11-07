"""Source-defined mutation/order cases; no original native execution claim."""

from __future__ import annotations

from dataclasses import replace

import pytest

from vantage.replay_attribute_modifiers import (
    ReplayAttributeModifiers,
    ReplayModifierCallbacks,
    UnresolvedReplayModifierCallbacks,
    UnsupportedReplayModifierReentrancy,
)
from vantage.replay_movement_cap import ReplayStatModifier, replay_unit_speed_cap


def _modifier(operation=1, amount=0x3F800000, category=5):
    return ReplayStatModifier(operation, amount, category)


def test_signed_operation_order_and_new_equal_records_precede_old_ones():
    registry = ReplayAttributeModifiers({})
    old = _modifier(1, 0x40400000)
    new = _modifier(1, 0x40A00000)
    multiply = _modifier(2, 0x40000000)
    for record in (multiply, old, new):
        registry.add(record, callbacks=None)
    assert registry.records(5) == (new, old, multiply)
    # Native category lookup now feeds the existing real numeric stat consumer:
    # ((1 + 5) + 3) * 2 =18, rather than encounter-order multiplication first.
    assert registry.apply(5, 0x3F800000) == 0x41900000
    assert (
        replay_unit_speed_cap(
            0x3F800000,
            master_target_boost_bits=0,
            modifiers=registry.records(5),
        )
        == 0x41900000
    )
    for operation in (0, 0x7FFFFFFF, 0xFFFFFFFF, 0x80000000):
        registry.add(_modifier(operation), callbacks=None)
    assert [r.operation for r in registry.records(5)] == [
        0x80000000,
        0xFFFFFFFF,
        0,
        1,
        1,
        2,
        0x7FFFFFFF,
    ]


def test_equal_operation_order_changes_binary32_result_and_is_not_deduplicated():
    large, negative, one = (_modifier(1, word) for word in (0x4B800000, 0xCB800000, 0x3F800000))
    registry = ReplayAttributeModifiers({5: (large, one)})
    assert registry.apply(5, 0) == 0x4B800000
    registry.add(negative, callbacks=None)
    assert registry.records(5) == (negative, large, one)
    # Appending the negative value instead would round the result to zero.
    assert registry.apply(5, 0) == 0x3F800000
    registry.add(one, callbacks=None)
    assert registry.records(5) == (one, negative, large, one)
    assert registry.apply(5, 0) == 0x40000000
    assert len(registry.records(5)) == 4


def test_categories_use_full_middle_word_and_removal_leaves_empty_node():
    first, other = _modifier(category=0xFFFFFFFF), _modifier(category=0)
    registry = ReplayAttributeModifiers({})
    for record in (first, other):
        registry.add(record, callbacks=None)
    assert registry.apply(0xFFFFFFFF, 0) == 0x3F800000
    assert registry.remove(first, callbacks=None)
    assert registry.snapshot() == {0xFFFFFFFF: (), 0: (other,)}
    assert registry.apply(0xFFFFFFFF, 0x7FA12345) == 0x7FA12345
    assert registry.records(7) == () and 7 not in registry.snapshot()


@pytest.mark.parametrize(
    "stored,query,expected",
    [
        (0, 0x80000000, True),
        (0x80000000, 0, True),
        (0x7F800000, 0x7F800000, True),
        (0xFF800000, 0xFF800000, True),
        (0x7F800000, 0xFF800000, False),
        (0x7FC12345, 0x7FC12345, False),
        (0x7FA12345, 0x7FA12345, False),
        (0xFFC12345, 0x7FC12345, False),
        (0x3F800000, 0x3F800001, False),
    ],
)
def test_removal_uses_native_ordered_float_equality(stored, query, expected):
    record = _modifier(2, stored)
    registry = ReplayAttributeModifiers({5: (record,)})
    assert registry.remove(replace(record, amount_bits=query), callbacks=None) is expected
    assert registry.records(5) == (() if expected else (record,))


def test_remove_searches_equal_operation_only_and_deletes_first_matching_duplicate():
    first = _modifier(1, 0)
    second = _modifier(1, 0x80000000)
    other_operation = _modifier(2, 0)
    registry = ReplayAttributeModifiers({5: (first, second, other_operation)})
    assert registry.remove(first, callbacks=None)
    assert registry.records(5) == (second, other_operation)
    assert registry.remove(first, callbacks=None)
    assert registry.records(5) == (other_operation,)
    assert not registry.remove(first, callbacks=None)
    assert registry.records(5) == (other_operation,)


def test_category1_callbacks_observe_actual_old_then_new_stat_values():
    registry = ReplayAttributeModifiers({})
    values = []
    callbacks = ReplayModifierCallbacks(
        lambda: values.append(("before", registry.apply(1, 0x41200000))),
        lambda: values.append(("after", registry.apply(1, 0x41200000))),
    )
    record = _modifier(2, 0x40000000, 1)
    registry.add(record, callbacks=callbacks)
    assert values == [("before", 0x41200000), ("after", 0x41A00000)]
    registry.remove(record, callbacks=callbacks)
    assert values[-2:] == [("before", 0x41A00000), ("after", 0x41200000)]
    assert registry.snapshot() == {1: ()}


def test_missing_or_nan_category1_record_does_not_require_or_invoke_callbacks():
    record = _modifier(1, 0x7FA12345, 1)
    registry = ReplayAttributeModifiers({1: (record,)})
    assert not registry.remove(record, callbacks=None)
    assert not registry.remove(replace(record, unknown_bits=7), callbacks=None)
    assert not registry.remove(replace(record, amount_bits=0), callbacks=None)
    assert registry.snapshot() == {1: (record,)}


def test_reached_category1_change_requires_real_callback_bindings_before_mutation():
    registry = ReplayAttributeModifiers({})
    record = _modifier(category=1)
    with pytest.raises(UnresolvedReplayModifierCallbacks):
        registry.add(record, callbacks=None)
    assert registry.snapshot() == {}
    registry = ReplayAttributeModifiers({1: (record,)})
    with pytest.raises(UnresolvedReplayModifierCallbacks):
        registry.remove(record, callbacks=None)
    assert registry.records(1) == (record,)


def test_other_categories_do_not_invoke_even_provided_notifications():
    def unexpected():
        pytest.fail("only category1 can notify")

    registry = ReplayAttributeModifiers({})
    callbacks = ReplayModifierCallbacks(unexpected, unexpected)
    record = _modifier(category=2)
    registry.add(record, callbacks=callbacks)
    assert registry.remove(record, callbacks=callbacks)


@pytest.mark.parametrize("phase", ["before", "after"])
def test_notification_exception_retains_completed_changes_and_restores_guard(phase):
    registry = ReplayAttributeModifiers({})
    record = _modifier(category=1)

    def fail():
        raise RuntimeError("notification failed")

    def observe():
        registry.records(1)

    callbacks = ReplayModifierCallbacks(
        fail if phase == "before" else observe, fail if phase == "after" else observe
    )
    with pytest.raises(RuntimeError, match="notification failed"):
        registry.add(record, callbacks=callbacks)
    assert registry.snapshot() == ({} if phase == "before" else {1: (record,)})
    registry.add(_modifier(category=5), callbacks=None)
    assert len(registry.records(5)) == 1


def test_notification_cannot_reentrantly_invalidate_collection_backing():
    registry = ReplayAttributeModifiers({})

    def before():
        registry.add(_modifier(), callbacks=None)

    callbacks = ReplayModifierCallbacks(before, lambda: None)
    with pytest.raises(UnsupportedReplayModifierReentrancy):
        registry.add(_modifier(category=1), callbacks=callbacks)
    assert registry.snapshot() == {}


def test_initial_vectors_and_snapshots_do_not_alias_mutable_inputs():
    record = _modifier()
    initial = {5: (record,)}
    registry = ReplayAttributeModifiers(initial)
    snapshot = registry.snapshot()
    initial.clear()
    registry.add(record, callbacks=None)
    assert snapshot == {5: (record,)}
    with pytest.raises(TypeError):
        snapshot[7] = ()
    assert registry.records(5) == (record, record)


@pytest.mark.parametrize(
    "initial",
    [
        None,
        [],
        {True: ()},
        {-1: ()},
        {1 << 32: ()},
        {5: []},
        {5: (None,)},
        {5: (_modifier(category=6),)},
        {5: (_modifier(1), _modifier(0xFFFFFFFF))},
        {5: (_modifier(True),)},
        {5: (_modifier(amount=1 << 32),)},
    ],
)
def test_import_requires_explicit_well_formed_current_native_collection(initial):
    with pytest.raises(ValueError):
        ReplayAttributeModifiers(initial)


def test_invalid_current_words_and_bindings_fail_without_editing_vectors():
    registry = ReplayAttributeModifiers({})
    with pytest.raises(ValueError):
        registry.add(_modifier(category=True), callbacks=None)
    with pytest.raises(ValueError):
        registry.add(_modifier(), callbacks=object())
    with pytest.raises(ValueError):
        registry.records(-1)
    with pytest.raises(ValueError):
        registry.apply(5, False)
    with pytest.raises(ValueError):
        ReplayModifierCallbacks(None, None)
    assert registry.snapshot() == {}
