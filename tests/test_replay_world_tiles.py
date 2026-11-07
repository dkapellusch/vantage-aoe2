"""Source-bound logical World tile order, count-plane and branch regressions."""

from __future__ import annotations

import pytest

from vantage.replay_world_tiles import (
    ReplayWorldTileRegistry,
    ReplayWorldTileSnapshot,
)

ONE, ZERO = 0x3F800000, 0


def test_empty_nonpositive_append_preserves_stale_plane_until_nonempty_recount():
    registry = ReplayWorldTileRegistry(ReplayWorldTileSnapshot(2, 1, {}, b"\x63\x08", {1: 0}))
    first = registry.append(0, 1, plane_coordinates=(0, 0))
    assert first.changed and first.count == 1 and not first.plane_written
    assert registry.tokens(0) == (1,) and registry.positive_count(0) == 99
    second = registry.append(0, 1, plane_coordinates=(0, 0))
    assert second.changed and second.plane_written and second.count == 2
    assert registry.tokens(0) == (1, 1)
    assert registry.snapshot().positive_counts == b"\0\x08"


def test_first_match_removal_swaps_last_and_retains_later_duplicate():
    registry = ReplayWorldTileRegistry(
        ReplayWorldTileSnapshot(
            1, 1, {0: (1, 2, 3, 4, 2, 5)}, b"\xff", {1: ONE, 2: ZERO, 3: ONE, 4: ZERO, 5: ONE}
        )
    )
    result = registry.remove(0, 2, plane_coordinates=(0, 0))
    assert result.changed and result.count == 5 and result.plane_written
    assert registry.tokens(0) == (1, 5, 3, 4, 2)
    assert registry.positive_count(0) == 3
    registry.remove(0, 2, plane_coordinates=(0, 0))
    assert registry.tokens(0) == (1, 5, 3, 4)
    before = registry.snapshot()
    absent = registry.remove(0, 2, plane_coordinates=(0, 0))
    assert not absent.changed and not absent.plane_written and absent.count == 4
    assert registry.snapshot() == before


def test_null_entries_append_and_remove_only_dereference_nonnull_occupants():
    registry = ReplayWorldTileRegistry.empty(1, 1, {1: ONE, 2: ONE})
    with pytest.raises(ValueError, match="dereferenced"):
        registry.append(0, 0, plane_coordinates=(0, 0))
    registry.append(0, 1, plane_coordinates=(0, 0))
    registry.append(0, 0, plane_coordinates=(0, 0))
    registry.append(0, 2, plane_coordinates=(0, 0))
    assert registry.tokens(0) == (1, 0, 2) and registry.positive_count(0) == 2
    registry.remove(0, 0, plane_coordinates=(0, 0))
    assert registry.tokens(0) == (1, 2) and registry.positive_count(0) == 2
    registry.remove(0, 1, plane_coordinates=(0, 0))
    registry.remove(0, 2, plane_coordinates=(0, 0))
    assert registry.tokens(0) == () and registry.positive_count(0) == 0
    assert dict(registry.snapshot().tiles) == {}


@pytest.mark.parametrize("count", [249, 250, 251, 255])
def test_append_cap_and_next_remove_recount_use_current_master_bits(count):
    registry = ReplayWorldTileRegistry(
        ReplayWorldTileSnapshot(1, 1, {0: (1,) * count}, b"\x11", {1: ONE, 2: ONE})
    )
    result = registry.append(0, 2, plane_coordinates=(0, 0))
    assert result.changed is (count == 249)
    assert result.plane_written is (count == 249)
    assert registry.positive_count(0) == (250 if count == 249 else 17)
    registry.bind_radius_z(1, ZERO)
    assert registry.positive_count(0) == (250 if count == 249 else 17)
    registry.remove(0, 1, plane_coordinates=(0, 0))
    assert registry.positive_count(0) == (1 if count == 249 else 0)


def test_full_tile_does_not_dereference_unbound_or_null_append_targets():
    registry = ReplayWorldTileRegistry(
        ReplayWorldTileSnapshot(1, 1, {0: (1,) * 250}, b"\x19", {1: ONE})
    )
    before = registry.snapshot()
    for target in (0, 900, 0xFFFFFFFFFFFFFFFF):
        result = registry.append(0, target, plane_coordinates=(0, 0))
        assert not result.changed and not result.plane_written and result.count == 250
        assert registry.snapshot() == before


@pytest.mark.parametrize(
    "word,positive",
    [
        (0, False),
        (0x80000000, False),
        (1, True),
        (0x80000001, False),
        (0x7F800000, True),
        (0xFF800000, False),
        (0x7FC12345, False),
        (0x7F800001, False),
    ],
)
def test_native_ordered_float_comparison_and_recount(word, positive):
    registry = ReplayWorldTileRegistry.empty(1, 1, {1: word})
    receipt = registry.append(0, 1, plane_coordinates=(0, 0))
    assert receipt.plane_written is positive
    assert registry.positive_count(0) == int(positive)
    registry.append(0, 1, plane_coordinates=(0, 0))
    assert registry.positive_count(0) == 2 * positive


def test_plane_address_is_separate_from_tile_identity_and_wraps_as_signed32():
    registry = ReplayWorldTileRegistry.empty(3, 2, {1: ONE})
    added = registry.append(0, 1, plane_coordinates=(-1, 1))
    assert added.plane_index == 2 and registry.tokens(0) == (1,)
    assert registry.snapshot().positive_counts == b"\0\0\x01\0\0\0"
    registry.remove(0, 1, plane_coordinates=(2, 1))
    assert registry.positive_count(2) == 1 and registry.positive_count(5) == 0
    wrapped = ReplayWorldTileRegistry.empty(2, 1, {1: ONE})
    receipt = wrapped.append(1, 1, plane_coordinates=(-(1 << 31), 1 << 30))
    assert receipt.plane_index == 0 and wrapped.tokens(1) == (1,)
    assert wrapped.snapshot().positive_counts == b"\x01\0"


def test_snapshot_owns_mapping_inputs_and_does_not_normalize_plane_counts():
    tiles, radii = {0: (1,), 1: ()}, {1: ONE}
    original = ReplayWorldTileSnapshot(2, 1, tiles, b"\x9a\x03", radii)
    registry = ReplayWorldTileRegistry(original)
    tiles.clear()
    radii[1] = ZERO
    assert registry.tokens(0) == (1,) and registry.positive_count(0) == 154
    registry.bind_radius_z(1, ZERO)
    registry.bind_radius_z(2, ONE)
    registry.append(0, 2, plane_coordinates=(0, 0))
    assert original.tiles[0] == (1,) and original.radius_z_bits[1] == ONE
    assert registry.tokens(0) == (1, 2) and registry.positive_count(0) == 1
    assert original.positive_counts == b"\x9a\x03"


@pytest.mark.parametrize(
    "tile,token,coordinates",
    [
        (True, 1, (0, 0)),
        (-1, 1, (0, 0)),
        (1, 1, (0, 0)),
        (0, True, (0, 0)),
        (0, -1, (0, 0)),
        (0, 1 << 64, (0, 0)),
        (0, 1, (-1, 0)),
        (0, 1, (1, 0)),
        (0, 1, (False, 0)),
        (0, 1, (0, 1 << 31)),
    ],
)
def test_invalid_backing_and_widths_fail_without_changing_state(tile, token, coordinates):
    registry = ReplayWorldTileRegistry.empty(1, 1, {1: ONE})
    before = registry.snapshot()
    for method in (registry.append, registry.remove):
        with pytest.raises(ValueError):
            method(tile, token, plane_coordinates=coordinates)
        assert registry.snapshot() == before


def test_unknown_dereferenced_master_is_rejected_before_append():
    registry = ReplayWorldTileRegistry.empty(1, 1, {})
    before = registry.snapshot()
    with pytest.raises(ValueError, match="dereferenced"):
        registry.append(0, 3, plane_coordinates=(0, 0))
    assert registry.snapshot() == before
    registry.bind_radius_z(3, ONE)
    registry.append(0, 3, plane_coordinates=(0, 0))
    assert registry.tokens(0) == (3,)


@pytest.mark.parametrize(
    "width,height,tiles,plane,radii",
    [
        (0, 1, {}, b"", {}),
        (True, 1, {}, b"\0", {}),
        (1 << 24, 2, {}, b"", {}),
        (1, 1, {}, b"", {}),
        (1, 1, {1: ()}, b"\0", {}),
        (1, 1, {0: [1]}, b"\0", {1: ONE}),
        (1, 1, {0: (1,) * 256}, b"\0", {1: ONE}),
        (1, 1, {0: (1,)}, b"\0", {}),
        (1, 1, {}, b"\0", {0: ZERO}),
        (1, 1, {}, b"\0", {1: True}),
    ],
)
def test_invalid_initial_snapshot(width, height, tiles, plane, radii):
    with pytest.raises(ValueError):
        ReplayWorldTileSnapshot(width, height, tiles, plane, radii)
