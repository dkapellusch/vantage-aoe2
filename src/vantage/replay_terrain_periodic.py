"""Pure build54800 terrain-effect periodic counts and expiry decisions.

Sources1414c85b0/1414cb1f0 and1414c8550/1414c8490/1414c8470. Clock/start reads and
property snapshots are explicit and independent. This module does not read a
World, run effects/particles, register/remove state or update pending flags.
Results describe the numerical decisions, not completed effect execution.
"""

from __future__ import annotations

from dataclasses import dataclass

_MASK = 0xFFFFFFFF


class UnresolvedReplayTerrainPeriodicContext(ValueError):
    """A reached native read has no supplied current sample or properties."""


def _integer(value: int, high: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= high:
        raise ValueError(f"{name} must be an integer in [0, {high}]")


@dataclass(frozen=True, slots=True)
class ReplayTerrainPeriodicProperties:
    """Current effect+30u8,+34u32,+38u32,+3cu32; no parser defaults.

    Every flag bit is retained, although counting uses only bit0. Each instance
    binds coherent property reads in one arithmetic block. Separate snapshots
    let the caller represent changed properties across intervening clock calls
    and the later effect/particle phase; equality is never inferred.
    """

    flags: int
    delay: int
    interval: int
    limit: int

    def __post_init__(self) -> None:
        _integer(self.flags, 255, "periodic flags")
        for name in ("delay", "interval", "limit"):
            _integer(getattr(self, name), _MASK, f"periodic {name}")


@dataclass(frozen=True, slots=True)
class ReplayTerrainPeriodicSample:
    """One clock return and the start-cell u32 read following that call.

    These are raw unsigned words, with no wall-clock/unit conversion or stable
    clock/start assumption. Neither word is generated from the other here.
    """

    clock: int
    start_timestamp: int

    def __post_init__(self) -> None:
        _integer(self.clock, _MASK, "periodic clock sample")
        _integer(self.start_timestamp, _MASK, "periodic start timestamp")


@dataclass(frozen=True, slots=True)
class ReplayTerrainPeriodicCount:
    """Two cumulative counts and their wrapped unsigned application count."""

    first_cumulative_count: int
    second_cumulative_count: int
    second_reference_clock: int
    application_count: int


@dataclass(frozen=True, slots=True)
class ReplayTerrainPeriodicExpiry:
    """Later expiry threshold/count and whether removal would be requested.

    cumulative_count=None means its arithmetic was skipped: threshold was zero
    or the supplied later clock preceded its start. This does not remove state
    or assert that native1414c81b0 could successfully resolve/remove anything.
    """

    threshold: int
    cumulative_count: int | None
    removal_requested: bool


def _optional_properties(properties: ReplayTerrainPeriodicProperties | None) -> None:
    if properties is not None and not isinstance(properties, ReplayTerrainPeriodicProperties):
        raise ValueError("periodic properties must be explicit current values or unavailable")


def _sample(sample: ReplayTerrainPeriodicSample) -> None:
    if not isinstance(sample, ReplayTerrainPeriodicSample):
        raise ValueError("an explicit current periodic clock/start sample is required")


def _elapsed_count(properties: ReplayTerrainPeriodicProperties, elapsed: int) -> int:
    delay = properties.delay if properties.flags & 1 else 0
    initial = int(bool(properties.flags & 1) and elapsed >= delay)
    numerator = elapsed - delay if elapsed >= delay else 0
    quotient = numerator // properties.interval if properties.interval else 0
    # Native32-bit LEA/ADD wraps before the unsigned nonzero-limit comparison.
    count = (quotient + initial) & _MASK
    return min(count, properties.limit) if properties.limit else count


def _cumulative(
    properties: ReplayTerrainPeriodicProperties | None, clock: int, start_timestamp: int
) -> int:
    # The native unsigned start comparison occurs before any property reads.
    if clock < start_timestamp:
        return 0
    if properties is None:
        raise UnresolvedReplayTerrainPeriodicContext(
            "current periodic count properties unavailable"
        )
    return _elapsed_count(properties, clock - start_timestamp)


def cumulative_replay_terrain_periodic(
    properties: ReplayTerrainPeriodicProperties | None, *, sample: ReplayTerrainPeriodicSample
) -> int:
    """1414c8550: cumulative u32 count at one explicit clock/start sample.

    An unsigned clock<start returns zero without consuming unavailable
    properties. There is no cyclic-time correction across that comparison.
    """
    _optional_properties(properties)
    _sample(sample)
    return _cumulative(properties, sample.clock, sample.start_timestamp)


def replay_terrain_periodic_expiry_threshold(properties: ReplayTerrainPeriodicProperties) -> int:
    """1414c8490: interval0 uses flags&1; nonzero interval uses limit."""
    if not isinstance(properties, ReplayTerrainPeriodicProperties):
        raise ValueError("explicit current periodic threshold properties are required")
    return properties.limit if properties.interval else properties.flags & 1


def count_replay_terrain_periodic(
    first_properties: ReplayTerrainPeriodicProperties | None,
    second_properties: ReplayTerrainPeriodicProperties | None,
    *,
    first: ReplayTerrainPeriodicSample,
    second: ReplayTerrainPeriodicSample,
    later_world_delta: int,
) -> ReplayTerrainPeriodicCount:
    """1414c85b0: preserve both clock/start reads and later World+7c delta.

    First cumulative count uses first.clock directly. Second first subtracts
    later_world_delta modulo2**32, then compares with second.start_timestamp.
    Each reached block uses its separately supplied current properties. None
    means unavailable properties and is accepted only when that block's clock
    precedes its start. Supplied values are validated even on skipped blocks.

    The final subtraction wraps to u32. Native1414cb1f0 zero-extends this value
    for its virtual18 loop; a wrapped negative difference can mean billions of
    applications. No signed reinterpretation, monotonicity clamp or loop runs
    here. Both samples remain required even when the first block returns zero.
    """
    _optional_properties(first_properties)
    _optional_properties(second_properties)
    _sample(first)
    _sample(second)
    _integer(later_world_delta, _MASK, "later World7c delta")
    first_count = _cumulative(first_properties, first.clock, first.start_timestamp)
    reference = (second.clock - later_world_delta) & _MASK
    second_count = _cumulative(second_properties, reference, second.start_timestamp)
    return ReplayTerrainPeriodicCount(
        first_count,
        second_count,
        reference,
        (first_count - second_count) & _MASK,
    )


def decide_replay_terrain_periodic_expiry(
    threshold_properties: ReplayTerrainPeriodicProperties,
    *,
    sample: ReplayTerrainPeriodicSample | None,
    count_properties: ReplayTerrainPeriodicProperties | None,
) -> ReplayTerrainPeriodicExpiry:
    """1414cb1f0's separate later expiry decision, after effect/particle calls.

    Before the later clock call, interval0 selects flags&1 as threshold;
    nonzero interval selects limit. Threshold0 skips that clock/start/count
    phase, so sample/count_properties may be None. Otherwise sample is required.
    A clock preceding start skips count arithmetic, allowing unavailable count
    properties. Reached arithmetic uses count_properties from after the clock
    call, not threshold_properties or either earlier count snapshot implicitly.

    removal_requested means unsigned cumulative_count>=threshold. It is only a
    numerical request; this helper neither executes nor fakes native removal.
    """
    threshold = replay_terrain_periodic_expiry_threshold(threshold_properties)
    _optional_properties(count_properties)
    if sample is not None:
        _sample(sample)
    if threshold == 0:
        return ReplayTerrainPeriodicExpiry(0, None, False)
    if sample is None:
        raise UnresolvedReplayTerrainPeriodicContext(
            "later periodic expiry clock/start unavailable"
        )
    if sample.clock < sample.start_timestamp:
        return ReplayTerrainPeriodicExpiry(threshold, None, False)
    count = _cumulative(count_properties, sample.clock, sample.start_timestamp)
    return ReplayTerrainPeriodicExpiry(threshold, count, count >= threshold)
