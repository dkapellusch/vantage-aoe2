"""Source-derived filter/selection checks; no captured native execution claim."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest

from vantage.replay_terrain_effects import (
    ReplayTerrainEffectDefinition,
    ReplayTerrainEffectMasterInput,
    ReplayTerrainEffectObjectContext,
    ReplayTerrainEffectSystem,
    UnresolvedReplayTerrainEffectContext,
    replay_terrain_effect_accepts_object,
    replay_terrain_effect_accepts_terrain,
    select_replay_terrain_effects,
)


def _definition(identity=1, flags=0, **memberships):
    values = {
        name: frozenset()
        for name in (
            "allow_terrain",
            "deny_terrain",
            "allow_saved_ids",
            "deny_saved_ids",
            "allow_object_groups",
            "deny_object_groups",
            "allow_families",
            "deny_families",
        )
    }
    values.update(memberships)
    return ReplayTerrainEffectDefinition(identity=identity, flags=flags, **values)


def test_entire_retained_source_membership_truth_table():
    # Frozen terrain-effect-context-review-v1/filter-cases.json exhausts these
    # 1024 abstract combinations. Its digest/45 accepted pairs are source facts,
    # not a native corpus or a formula copied from the shipping implementation.
    master = ReplayTerrainEffectMasterInput(-1, -32768, 255)
    context = ReplayTerrainEffectObjectContext(2, 255, master)
    names = (
        "deny_terrain",
        "allow_terrain",
        "deny_saved_ids",
        "deny_object_groups",
        "deny_families",
        "allow_saved_ids",
        "allow_object_groups",
        "allow_families",
    )
    keys = (255, 255, -1, -32768, 255, -1, -32768, 255)
    outputs = bytearray()
    for flags in range(4):
        for mask in range(256):
            definition = _definition(
                flags=flags,
                **{
                    name: frozenset((key,)) if mask & (1 << bit) else frozenset()
                    for bit, (name, key) in enumerate(zip(names, keys, strict=True))
                },
            )
            terrain = replay_terrain_effect_accepts_terrain(definition, 255)
            object_match = replay_terrain_effect_accepts_object(definition, master)
            actual = select_replay_terrain_effects(
                context,
                ReplayTerrainEffectSystem((definition,)),
            )
            selected = bool(actual)
            assert selected == (terrain and object_match)
            if selected:
                assert len(actual) == 1 and actual[0] is definition
            outputs.append(selected)
            high_flags = replace(definition, flags=flags | 0xFC)
            assert (
                bool(
                    select_replay_terrain_effects(
                        context,
                        ReplayTerrainEffectSystem((high_flags,)),
                    )
                )
                == selected
            )
    assert len(outputs) == 1024 and sum(outputs) == 45
    assert hashlib.sha256(outputs).hexdigest() == (
        "02d8a0bea7839a27a2a2252f8abb19b81bd9628ffbd0627487cb6dbc42886b4f"
    )


@pytest.mark.parametrize(
    "deny", ["deny_terrain", "deny_saved_ids", "deny_object_groups", "deny_families"]
)
def test_every_deny_overrides_both_global_accept_flags(deny):
    master = ReplayTerrainEffectMasterInput(42, 6, 80)
    key = {"deny_terrain": 7, "deny_saved_ids": 42, "deny_object_groups": 6, "deny_families": 80}[
        deny
    ]
    definition = _definition(flags=255, **{deny: frozenset((key,))})
    assert (
        select_replay_terrain_effects(
            ReplayTerrainEffectObjectContext(2, 7, master),
            ReplayTerrainEffectSystem((definition,)),
        )
        == ()
    )


@pytest.mark.parametrize(
    "saved_id,group,family,terrain",
    [
        (-32768, 32767, 0, 0),
        (-1, -1, 255, 255),
        (0, 0, 80, 128),
        (32767, -32768, 127, 127),
    ],
)
def test_current_master_and_terrain_keys_keep_signed_and_unsigned_domains(
    saved_id,
    group,
    family,
    terrain,
):
    definition = _definition(
        allow_terrain=frozenset((terrain,)),
        allow_saved_ids=frozenset((saved_id,)),
    )
    master = ReplayTerrainEffectMasterInput(saved_id, group, family)
    context = ReplayTerrainEffectObjectContext(2, terrain, master)
    assert select_replay_terrain_effects(context, ReplayTerrainEffectSystem((definition,))) == (
        definition,
    )
    denied = replace(definition, deny_object_groups=frozenset((group,)))
    assert not replay_terrain_effect_accepts_object(denied, master)


def test_unreachable_dword_keys_are_retained_without_truncating_into_hits():
    definition = _definition(
        flags=2,
        allow_saved_ids=frozenset((65535, -(1 << 31), (1 << 31) - 1)),
        allow_object_groups=frozenset((65535,)),
        allow_families=frozenset((-1, 256)),
    )
    assert definition.allow_saved_ids == frozenset((65535, -(1 << 31), (1 << 31) - 1))
    assert not replay_terrain_effect_accepts_object(
        definition,
        ReplayTerrainEffectMasterInput(-1, -1, 255),
    )
    assert replay_terrain_effect_accepts_object(
        replace(definition, allow_saved_ids=frozenset((-1,))),
        ReplayTerrainEffectMasterInput(-1, -1, 255),
    )


def test_selection_keeps_vector_order_duplicates_and_original_instances():
    first = _definition(identity=0x1000, flags=3)
    second = _definition(identity=0x2000, flags=3)
    equal_first = replace(first)
    rejected = _definition(identity=0x3000, flags=0)
    vector = (second, first, rejected, second, equal_first, first)
    context = ReplayTerrainEffectObjectContext(2, 17, ReplayTerrainEffectMasterInput(8, 9, 10))
    system = ReplayTerrainEffectSystem(vector)
    result = select_replay_terrain_effects(context, system)
    expected = (second, first, second, equal_first, first)
    assert len(result) == len(expected)
    assert all(actual is original for actual, original in zip(result, expected, strict=True))
    assert system.definitions is vector and context.object_188 == 2


def test_conflicting_identity_refused_only_when_system_is_consumed():
    first = _definition(identity=5, flags=3)
    conflicting = replace(first, deny_terrain=frozenset((7,)))
    system = ReplayTerrainEffectSystem((first, conflicting))
    disabled = ReplayTerrainEffectObjectContext(1, 7, None)
    assert select_replay_terrain_effects(disabled, system) == ()
    with pytest.raises(ValueError, match="conflicting"):
        select_replay_terrain_effects(replace(disabled, object_188=2), system)


@pytest.mark.parametrize("kind", [0, 1, 3, 255])
def test_object188_gate_skips_unavailable_master(kind):
    context = ReplayTerrainEffectObjectContext(kind, None, None)
    assert (
        select_replay_terrain_effects(
            context,
            ReplayTerrainEffectSystem((_definition(flags=3),)),
        )
        == ()
    )


def test_known_null_system_and_explicit_empty_system_need_no_master():
    context = ReplayTerrainEffectObjectContext(2, None, None)
    assert select_replay_terrain_effects(context, None) == ()
    assert select_replay_terrain_effects(context, ReplayTerrainEffectSystem(())) == ()


@pytest.mark.parametrize(
    "definition",
    [
        _definition(flags=3, deny_terrain=frozenset((255,))),
        _definition(flags=1, allow_terrain=frozenset((0,))),
    ],
)
def test_terrain_rejection_precedes_unavailable_master(definition):
    assert (
        select_replay_terrain_effects(
            ReplayTerrainEffectObjectContext(2, None, None),
            ReplayTerrainEffectSystem((definition,)),
        )
        == ()
    )


def test_known_null_tile_uses_255_and_does_not_substitute_zero_or_a_master():
    definition = _definition(flags=1, allow_terrain=frozenset((255,)))
    context = ReplayTerrainEffectObjectContext(2, None, None)
    system = ReplayTerrainEffectSystem((definition,))
    with pytest.raises(UnresolvedReplayTerrainEffectContext):
        select_replay_terrain_effects(context, system)
    current = replace(context, master=ReplayTerrainEffectMasterInput(12, 6, 80))
    assert select_replay_terrain_effects(current, system) == (definition,)
    assert select_replay_terrain_effects(replace(current, terrain_id=0), system) == ()


@pytest.mark.parametrize(
    "name,value",
    [
        ("identity", 0),
        ("identity", True),
        ("identity", 1 << 64),
        ("flags", -1),
        ("flags", 256),
        ("flags", False),
        ("allow_terrain", frozenset((-1,))),
        ("deny_terrain", frozenset((256,))),
        ("allow_terrain", {7}),
        ("allow_families", [80]),
        ("allow_saved_ids", frozenset((True,))),
        ("deny_object_groups", frozenset((1 << 31,))),
        ("deny_families", frozenset((-(1 << 31) - 1,))),
    ],
)
def test_definition_requires_explicit_strict_immutable_native_domains(name, value):
    with pytest.raises(ValueError):
        replace(_definition(), **{name: value})


@pytest.mark.parametrize(
    "values",
    [
        (True, 0, 0),
        (-32769, 0, 0),
        (32768, 0, 0),
        (0, -32769, 0),
        (0, 32768, 0),
        (0, 0, -1),
        (0, 0, 256),
        (0, 0, 80.0),
    ],
)
def test_master_requires_normalized_current_fields(values):
    with pytest.raises(ValueError):
        ReplayTerrainEffectMasterInput(*values)


@pytest.mark.parametrize(
    "values",
    [
        (True, 0, None),
        (256, 0, None),
        (-1, 0, None),
        (2, False, None),
        (2, -1, None),
        (2, 256, None),
        (2, 0, object()),
    ],
)
def test_context_rejects_untyped_or_out_of_range_bindings(values):
    with pytest.raises(ValueError):
        ReplayTerrainEffectObjectContext(*values)


@pytest.mark.parametrize("vector", [[], [_definition()], (None,), (object(),)])
def test_system_requires_an_explicit_immutable_definition_vector(vector):
    with pytest.raises(ValueError):
        ReplayTerrainEffectSystem(vector)


def test_inputs_are_immutable_and_system_must_be_supplied_explicitly():
    definition = _definition(identity=(1 << 64) - 1, flags=255)
    master = ReplayTerrainEffectMasterInput(1, 2, 3)
    context = ReplayTerrainEffectObjectContext(2, 4, master)
    system = ReplayTerrainEffectSystem((definition,))
    for value, name, replacement in (
        (definition, "flags", 0),
        (master, "saved_id", 0),
        (context, "object_188", 0),
        (system, "definitions", ()),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, replacement)
    with pytest.raises(TypeError):
        select_replay_terrain_effects(context)
    with pytest.raises(ValueError):
        select_replay_terrain_effects(context, ())
    with pytest.raises(ValueError):
        select_replay_terrain_effects(object(), system)
    with pytest.raises(ValueError):
        replay_terrain_effect_accepts_terrain(definition, True)
    with pytest.raises(ValueError):
        replay_terrain_effect_accepts_terrain(None, 0)
    with pytest.raises(ValueError):
        replay_terrain_effect_accepts_object(definition, None)
    with pytest.raises(ValueError):
        replay_terrain_effect_accepts_object(None, master)
