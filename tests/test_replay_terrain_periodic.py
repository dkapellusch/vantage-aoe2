"""Source-derived periodic arithmetic/phase cases; no native runtime corpus."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from vantage.replay_terrain_periodic import (
    ReplayTerrainPeriodicProperties,
    ReplayTerrainPeriodicSample,
    UnresolvedReplayTerrainPeriodicContext,
    count_replay_terrain_periodic,
    cumulative_replay_terrain_periodic,
    decide_replay_terrain_periodic_expiry,
    replay_terrain_periodic_expiry_threshold,
)

_MAX = 0xFFFFFFFF


@pytest.mark.parametrize(
    "flags,delay,interval,limit,clock,start,expected",
    [
        (0, 999, 0, 0, 100, 100, 0),
        (1, 0, 0, 0, 100, 100, 1),
        (2, 0, 0, 99, 100, 100, 0),
        (0, 999, 10, 0, 109, 100, 0),
        (0, 999, 10, 0, 110, 100, 1),
        (1, 5, 10, 0, 104, 100, 0),
        (1, 5, 10, 0, 105, 100, 1),
        (1, 5, 10, 0, 114, 100, 1),
        (1, 5, 10, 0, 115, 100, 2),
        (1, 5, 10, 1, 115, 100, 1),
        (1, 5, 0, 0, 104, 100, 0),
        (1, 5, 0, 0, 105, 100, 1),
        (0, 0, 1, 0, _MAX, 0, _MAX),
        (1, 0, 1, 0, _MAX, 0, 0),
        (1, 0, 1, 7, _MAX, 0, 0),
        (1, 1, 1, 7, _MAX, 0, 7),
        (128, _MAX, 1, 0, _MAX, 0, _MAX),
        (255, _MAX, 1, 0, _MAX, 0, 1),
        (255, _MAX, 1, 0, _MAX - 1, 0, 0),
        (0, 0, 1, 0, 0, _MAX, 0),
        (0, 0, 1, 0, 0x80000000, 0x7FFFFFFF, 1),
        (1, 0, 1, 0, _MAX, _MAX, 1),
    ],
)
def test_cumulative_source_boundaries(flags, delay, interval, limit, clock, start, expected):
    properties = ReplayTerrainPeriodicProperties(flags, delay, interval, limit)
    assert (
        cumulative_replay_terrain_periodic(
            properties,
            sample=ReplayTerrainPeriodicSample(clock, start),
        )
        == expected
    )


def test_full_flag_byte_is_retained_and_only_bit_zero_controls_initial_delay():
    for flags in range(256):
        properties = ReplayTerrainPeriodicProperties(flags, 5, 10, 0)
        assert properties.flags == flags
        assert cumulative_replay_terrain_periodic(
            properties,
            sample=ReplayTerrainPeriodicSample(16, 0),
        ) == (2 if flags & 1 else 1)
        assert (
            replay_terrain_periodic_expiry_threshold(
                ReplayTerrainPeriodicProperties(flags, 5, 0, 17),
            )
            == flags & 1
        )
        assert replay_terrain_periodic_expiry_threshold(properties) == 0


@pytest.mark.parametrize(
    "clock,delta,expected",
    [
        (104, 1, (0, 0, 103, 0)),
        (105, 1, (1, 0, 104, 1)),
        (114, 1, (1, 1, 113, 0)),
        (115, 1, (2, 1, 114, 1)),
        (125, 10, (3, 2, 115, 1)),
        (125, 0, (3, 3, 125, 0)),
    ],
)
def test_two_sample_count_at_delay_and_interval_boundaries(clock, delta, expected):
    properties = ReplayTerrainPeriodicProperties(1, 5, 10, 0)
    result = count_replay_terrain_periodic(
        properties,
        properties,
        first=ReplayTerrainPeriodicSample(clock, 100),
        second=ReplayTerrainPeriodicSample(clock, 100),
        later_world_delta=delta,
    )
    assert (
        result.first_cumulative_count,
        result.second_cumulative_count,
        result.second_reference_clock,
        result.application_count,
    ) == expected


def test_distinct_clock_returns_preserve_wrapped_negative_application_count():
    properties = ReplayTerrainPeriodicProperties(0, 0, 10, 0)
    result = count_replay_terrain_periodic(
        properties,
        properties,
        first=ReplayTerrainPeriodicSample(100, 0),
        second=ReplayTerrainPeriodicSample(120, 0),
        later_world_delta=10,
    )
    assert result.first_cumulative_count == 10
    assert result.second_cumulative_count == 11
    assert result.application_count == _MAX
    assert result.application_count > (1 << 31)  # Native zero-extends this loop count.


def test_later_delta_subtraction_wraps_before_unsigned_start_comparison():
    properties = ReplayTerrainPeriodicProperties(0, 0, 1, 0)
    result = count_replay_terrain_periodic(
        properties,
        properties,
        first=ReplayTerrainPeriodicSample(5, 0),
        second=ReplayTerrainPeriodicSample(5, 0),
        later_world_delta=10,
    )
    assert result.second_reference_clock == 0xFFFFFFFB
    assert result.second_cumulative_count == 0xFFFFFFFB
    assert result.application_count == 10


def test_separate_start_cell_reads_are_not_replaced_by_one_stable_timestamp():
    properties = ReplayTerrainPeriodicProperties(0, 0, 10, 0)
    result = count_replay_terrain_periodic(
        properties,
        properties,
        first=ReplayTerrainPeriodicSample(100, 90),
        second=ReplayTerrainPeriodicSample(100, 0),
        later_world_delta=10,
    )
    assert result.first_cumulative_count == 1
    assert result.second_cumulative_count == 9
    assert result.application_count == 0xFFFFFFF8


def test_each_count_phase_consumes_its_supplied_current_properties():
    first = ReplayTerrainPeriodicProperties(1, 0, 0, 0)
    second = ReplayTerrainPeriodicProperties(0, 0, 0, 0)
    result = count_replay_terrain_periodic(
        first,
        second,
        first=ReplayTerrainPeriodicSample(100, 100),
        second=ReplayTerrainPeriodicSample(100, 100),
        later_world_delta=0,
    )
    assert result.first_cumulative_count == 1
    assert result.second_cumulative_count == 0
    assert result.application_count == 1


def test_unsigned_cumulative_addition_wraps_before_limit_and_final_difference():
    properties = ReplayTerrainPeriodicProperties(1, 0, 1, 7)
    result = count_replay_terrain_periodic(
        properties,
        properties,
        first=ReplayTerrainPeriodicSample(_MAX, 0),
        second=ReplayTerrainPeriodicSample(0, 0),
        later_world_delta=0,
    )
    assert result.first_cumulative_count == 0  # MAX+1 wraps before min(...,7).
    assert result.second_cumulative_count == 1
    assert result.application_count == _MAX


def test_first_zero_does_not_skip_the_second_clock_phase():
    result = count_replay_terrain_periodic(
        None,
        ReplayTerrainPeriodicProperties(0, 0, 1, 0),
        first=ReplayTerrainPeriodicSample(0, 100),
        second=ReplayTerrainPeriodicSample(100, 0),
        later_world_delta=1,
    )
    assert result.first_cumulative_count == 0 and result.second_cumulative_count == 99
    assert result.application_count == (1 << 32) - 99


def test_property_reads_before_start_are_skipped_without_fabricating_defaults():
    assert (
        cumulative_replay_terrain_periodic(
            None,
            sample=ReplayTerrainPeriodicSample(99, 100),
        )
        == 0
    )
    result = count_replay_terrain_periodic(
        None,
        None,
        first=ReplayTerrainPeriodicSample(99, 100),
        second=ReplayTerrainPeriodicSample(101, 100),
        later_world_delta=2,
    )
    assert result.application_count == 0
    with pytest.raises(UnresolvedReplayTerrainPeriodicContext):
        cumulative_replay_terrain_periodic(None, sample=ReplayTerrainPeriodicSample(100, 100))


@pytest.mark.parametrize(
    "flags,interval,limit,threshold",
    [
        (0, 0, 99, 0),
        (1, 0, 99, 1),
        (2, 0, _MAX, 0),
        (255, 0, 0, 1),
        (0, 1, 0, 0),
        (1, 1, 0, 0),
        (0, 1, _MAX, _MAX),
        (255, 17, 5, 5),
    ],
)
def test_expiry_threshold_uses_interval_then_flag_or_limit(flags, interval, limit, threshold):
    assert (
        replay_terrain_periodic_expiry_threshold(
            ReplayTerrainPeriodicProperties(flags, 99, interval, limit),
        )
        == threshold
    )


@pytest.mark.parametrize(
    "properties",
    [
        ReplayTerrainPeriodicProperties(0, 1, 0, 99),
        ReplayTerrainPeriodicProperties(255, 1, 10, 0),
    ],
)
def test_zero_threshold_skips_later_clock_start_and_count_reads(properties):
    result = decide_replay_terrain_periodic_expiry(
        properties,
        sample=None,
        count_properties=None,
    )
    assert result.threshold == 0 and result.cumulative_count is None
    assert not result.removal_requested


@pytest.mark.parametrize(
    "clock,count,remove", [(99, None, False), (100, 0, False), (104, 0, False), (105, 1, True)]
)
def test_later_expiry_delay_gate_is_independent_of_prior_application_count(clock, count, remove):
    properties = ReplayTerrainPeriodicProperties(1, 5, 0, 99)
    result = decide_replay_terrain_periodic_expiry(
        properties,
        sample=ReplayTerrainPeriodicSample(clock, 100),
        count_properties=properties if clock >= 100 else None,
    )
    assert result.threshold == 1 and result.cumulative_count == count
    assert result.removal_requested is remove


def test_later_threshold_and_count_property_rereads_remain_distinct():
    threshold = ReplayTerrainPeriodicProperties(0, 0, 10, 2)
    changed = ReplayTerrainPeriodicProperties(1, 0, 0, 0)
    result = decide_replay_terrain_periodic_expiry(
        threshold,
        sample=ReplayTerrainPeriodicSample(100, 0),
        count_properties=changed,
    )
    assert result.threshold == 2 and result.cumulative_count == 1
    assert not result.removal_requested


def test_expiry_recomputes_after_callbacks_instead_of_reusing_earlier_count():
    properties = ReplayTerrainPeriodicProperties(0, 0, 10, 2)
    early = count_replay_terrain_periodic(
        properties,
        properties,
        first=ReplayTerrainPeriodicSample(10, 0),
        second=ReplayTerrainPeriodicSample(10, 0),
        later_world_delta=0,
    )
    assert early.application_count == 0
    late = decide_replay_terrain_periodic_expiry(
        properties,
        sample=ReplayTerrainPeriodicSample(20, 0),
        count_properties=properties,
    )
    assert late.cumulative_count == 2 and late.removal_requested


def test_expiry_count_wrap_is_preserved_before_finite_limit():
    properties = ReplayTerrainPeriodicProperties(1, 0, 1, 7)
    result = decide_replay_terrain_periodic_expiry(
        properties,
        sample=ReplayTerrainPeriodicSample(_MAX, 0),
        count_properties=properties,
    )
    assert result.threshold == 7 and result.cumulative_count == 0
    assert not result.removal_requested


def test_reached_later_reads_require_actual_samples_and_properties():
    properties = ReplayTerrainPeriodicProperties(1, 0, 0, 0)
    with pytest.raises(UnresolvedReplayTerrainPeriodicContext):
        decide_replay_terrain_periodic_expiry(properties, sample=None, count_properties=properties)
    with pytest.raises(UnresolvedReplayTerrainPeriodicContext):
        decide_replay_terrain_periodic_expiry(
            properties,
            sample=ReplayTerrainPeriodicSample(100, 100),
            count_properties=None,
        )


@pytest.mark.parametrize(
    "values",
    [
        (True, 0, 0, 0),
        (-1, 0, 0, 0),
        (256, 0, 0, 0),
        (0, -1, 0, 0),
        (0, 1 << 32, 0, 0),
        (0, 0, False, 0),
        (0, 0, 1.0, 0),
        (0, 0, 0, -1),
    ],
)
def test_properties_require_full_native_unsigned_domains(values):
    with pytest.raises(ValueError):
        ReplayTerrainPeriodicProperties(*values)


@pytest.mark.parametrize(
    "values", [(True, 0), (-1, 0), (1 << 32, 0), (0, False), (0, -1), (0, 1 << 32), (0, 1.0)]
)
def test_clock_start_samples_require_explicit_u32_words(values):
    with pytest.raises(ValueError):
        ReplayTerrainPeriodicSample(*values)


@pytest.mark.parametrize("delta", [True, -1, 1 << 32, 1.0])
def test_later_world_delta_is_a_strict_u32_word(delta):
    with pytest.raises(ValueError):
        count_replay_terrain_periodic(
            None,
            None,
            first=ReplayTerrainPeriodicSample(0, 1),
            second=ReplayTerrainPeriodicSample(0, 1),
            later_world_delta=delta,
        )


def test_inputs_and_outputs_are_immutable_and_untyped_bindings_refuse():
    properties = ReplayTerrainPeriodicProperties(255, 0, 0, 0)
    sample = ReplayTerrainPeriodicSample(100, 100)
    result = count_replay_terrain_periodic(
        properties,
        properties,
        first=sample,
        second=sample,
        later_world_delta=0,
    )
    expiry = decide_replay_terrain_periodic_expiry(
        properties,
        sample=sample,
        count_properties=properties,
    )
    for value, name in (
        (properties, "flags"),
        (sample, "clock"),
        (result, "application_count"),
        (expiry, "threshold"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, 0)
    with pytest.raises(ValueError):
        cumulative_replay_terrain_periodic(properties, sample=(100, 100))
    with pytest.raises(ValueError):
        cumulative_replay_terrain_periodic(object(), sample=sample)
    with pytest.raises(ValueError):
        replay_terrain_periodic_expiry_threshold(None)
    with pytest.raises(ValueError):
        decide_replay_terrain_periodic_expiry(properties, sample=(), count_properties=properties)
