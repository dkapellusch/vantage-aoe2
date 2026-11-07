"""Sparse native visibility-circle effects under explicitly resolved premises.

Complete original141352430/141355210 matched602 controlled native cases.
This component covers counter/mask/tile writes and an already allocated dirty
queue. Observer callbacks, owner virtual88, tile neighbors, enabled/lazy API
notifications, logging and queue growth remain unsupported. It reconstructs
neither initial visibility nor current runtime callback premises.
Evidence: world-envelope/visibility-circle-native-root-review.json.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from vantage.replay_visibility_geometry import replay_visibility_rows


class UnsupportedReplayVisibilityCircle(ValueError):
    """The supplied state requires a visibility dependency outside this component."""


def _integer(value: int, name: str, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise UnsupportedReplayVisibilityCircle(f"{name} must be in [{low}, {high}]")


@dataclass(frozen=True, slots=True)
class ReplayVisibilityCircleContext:
    """Known native fields; the caller must obtain them from its current state.

    The observer index is World+6b0, owner type is owner+10, API presence is
    global1444585e8, and notification disable is API+1a1. Debug/disable are
    globals144355060/1443c9160. No default silently assumes a skipped callback.
    """

    observer_index: int
    owner_type: int
    api_context_present: bool
    notification_disable_byte: int
    debug_byte: int
    disable_word: int

    def __post_init__(self) -> None:
        _integer(self.observer_index, "observer index", 0, 0xFFFFFFFF)
        _integer(self.owner_type, "owner type", -0x80000000, 0x7FFFFFFF)
        if type(self.api_context_present) is not bool:
            raise UnsupportedReplayVisibilityCircle("API presence must be a known boolean")
        _integer(self.notification_disable_byte, "notification-disable byte", 0, 255)
        _integer(self.debug_byte, "debug byte", 0, 255)
        _integer(self.disable_word, "disable word", 0, 0xFFFFFFFF)


@dataclass(frozen=True, slots=True)
class ReplayVisibilityCircleState:
    """Immutable borrowed buffers and the scalar inputs read by the admitted path.

    Counters/tiles are dense width*height; masks use their separate native
    descriptor stride. Queue capacity/count are nonnegative signed32 storage
    premises. Queue contents and tile17 are never read, so they need no copy.
    The returned patch preserves their untouched prefix/slack automatically.
    """

    width: int
    height: int
    mask_stride: int
    counters_u16_le: bytes
    masks_u64_le: bytes
    tile_flags19: bytes
    explored_count: int
    dirty_capacity: int
    dirty_count: int
    dirty_activity: int
    explore_mask: int
    unexplore_mask: int
    permanent_mask: int

    def __post_init__(self) -> None:
        for name in ("width", "height", "mask_stride"):
            _integer(getattr(self, name), name, 1, 0x7FFFFFFF)
        if self.mask_stride < self.width or self.mask_stride * self.height > 0x7FFFFFFF:
            raise UnsupportedReplayVisibilityCircle("mask storage must cover each dense row")
        for name, size in (
            ("counters_u16_le", self.width * self.height * 2),
            ("masks_u64_le", self.mask_stride * self.height * 8),
            ("tile_flags19", self.width * self.height),
        ):
            data = getattr(self, name)
            if not isinstance(data, bytes) or len(data) != size:
                raise UnsupportedReplayVisibilityCircle(f"{name} must contain exactly{size} bytes")
        for name in ("explored_count", "dirty_activity"):
            _integer(getattr(self, name), name, 0, 0xFFFFFFFF)
        _integer(self.dirty_capacity, "dirty capacity", 0, 0x7FFFFFFF)
        _integer(self.dirty_count, "dirty count", 0, self.dirty_capacity)
        for name in ("explore_mask", "unexplore_mask", "permanent_mask"):
            _integer(getattr(self, name), name, 0, 0xFFFFFFFFFFFFFFFF)


@dataclass(frozen=True, slots=True)
class ReplayVisibilityCirclePatch:
    """Final writes, with dense cell indices and separate stride-based mask indices.

    Entries follow the original row/x visitation order. Mask entries contain
    the final word after all admitted OR/AND operations, including unchanged
    writes. This is an end-of-call patch, not a notification execution trace.
    Dirty appends preserve duplicates. Apply them at the input dirty count;
    untouched queue bytes and all other state remain unchanged. Unexplore has
    no specified native return value and therefore returns newly_explored=None.
    """

    counter_writes: tuple[tuple[int, int], ...]
    mask_writes: tuple[tuple[int, int], ...]
    tile17_writes: tuple[tuple[int, int], ...]
    dirty_appends: tuple[tuple[int, int], ...]
    explored_count: int
    dirty_count: int
    dirty_activity: int
    newly_explored: int | None


def explore_replay_visibility_circle(
    state: ReplayVisibilityCircleState,
    context: ReplayVisibilityCircleContext,
    x: int,
    y: int,
    radius: int,
    mode_flag: int,
    tile_update: int,
) -> ReplayVisibilityCirclePatch:
    """Return original exploration writes without copying any whole-map buffer."""
    return _circle(state, context, x, y, radius, mode_flag, tile_update, exploring=True)


def unexplore_replay_visibility_circle(
    state: ReplayVisibilityCircleState,
    context: ReplayVisibilityCircleContext,
    x: int,
    y: int,
    radius: int,
    mode_flag: int,
    tile_update: int,
) -> ReplayVisibilityCirclePatch:
    """Return original unexploration writes; an old zero still clears its mask."""
    return _circle(state, context, x, y, radius, mode_flag, tile_update, exploring=False)


def _circle(
    state: ReplayVisibilityCircleState,
    context: ReplayVisibilityCircleContext,
    x: int,
    y: int,
    radius: int,
    mode_flag: int,
    tile_update: int,
    *,
    exploring: bool,
) -> ReplayVisibilityCirclePatch:
    if not isinstance(state, ReplayVisibilityCircleState) or not isinstance(
        context, ReplayVisibilityCircleContext
    ):
        raise UnsupportedReplayVisibilityCircle("resolved visibility state/context required")
    for name, value in (
        ("x", x),
        ("y", y),
        ("radius", radius),
        ("mode", mode_flag),
        ("tile update", tile_update),
    ):
        _integer(value, name, -0x80000000, 0x7FFFFFFF)
    counters: list[tuple[int, int]] = []
    masks: dict[int, int] = {}
    tiles: list[tuple[int, int]] = []
    queue: list[tuple[int, int]] = []
    explored, count, activity = state.explored_count, state.dirty_count, state.dirty_activity
    if not context.disable_word:
        if context.observer_index != 0xFFFFFFFF:
            raise UnsupportedReplayVisibilityCircle("observer lookup/callback remains unresolved")
        rows = replay_visibility_rows(
            x, y, radius, mode_flag, width=state.width, height=state.height
        )
        for row_y, low, high in rows:
            for row_x in range(low, high + 1):
                index = row_y * state.width + row_x
                old = struct.unpack_from("<H", state.counters_u16_le, index * 2)[0]
                value = (old + 1) & 0xFFFF if exploring else ((old - 1) & 0xFFFF if old else 0)
                mask_bits: int | None = None
                if exploring:
                    if value in (0, 1) and context.owner_type == 3:
                        raise UnsupportedReplayVisibilityCircle(
                            "owner virtual88 remains unresolved"
                        )
                    if value == 0:
                        if count >= state.dirty_capacity:
                            raise UnsupportedReplayVisibilityCircle(
                                "dirty-queue growth unsupported"
                            )
                        if state.tile_flags19[index] & 0x60:
                            raise UnsupportedReplayVisibilityCircle(
                                "tile neighbors remain unresolved"
                            )
                        queue.append((row_x, row_y))
                        count += 1
                        activity = (activity + 1) & 0xFFFFFFFF
                        explored = (explored + 1) & 0xFFFFFFFF
                        mask_bits = state.permanent_mask | state.explore_mask
                        value = 1
                    elif value == 1:
                        mask_bits = state.explore_mask
                    if value == 1 and tile_update:
                        tiles.append((index, 0xF))
                    if value == 0x7FFF:
                        value = 0x7FFE
                elif value == 0:
                    mask_bits = state.unexplore_mask
                    if tile_update:
                        tiles.append((index, 0x80))
                if mask_bits is not None:
                    if not context.api_context_present or not context.notification_disable_byte:
                        raise UnsupportedReplayVisibilityCircle(
                            "API notifications remain unresolved"
                        )
                    if context.debug_byte:
                        raise UnsupportedReplayVisibilityCircle("debug logging remains unresolved")
                    mask_index = row_y * state.mask_stride + row_x
                    current = struct.unpack_from("<Q", state.masks_u64_le, mask_index * 8)[0]
                    masks[mask_index] = current | mask_bits if exploring else current & mask_bits
                counters.append((index, value))
    return ReplayVisibilityCirclePatch(
        tuple(counters),
        tuple(masks.items()),
        tuple(tiles),
        tuple(queue),
        explored,
        count,
        activity,
        len(queue) if exploring else None,
    )
