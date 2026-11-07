"""Whole original helper outputs, real saved/DAT joins and profile rejection."""

from __future__ import annotations

import copy
import gzip
import json
from dataclasses import replace
from functools import cache
from pathlib import Path

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_default107 import (
    ReplayDefault107Error,
    install_replay_human_default107,
)
from vantage.replay_game_data import read_game_data_graphics, read_game_data_master
from vantage.replay_master_common import restore_replay_master_components
from vantage.replay_masters import read_master
from vantage.replay_objects import read_saved_object
from vantage.replay_world_assembly import ReplayInitialObjectBinding

FIXTURE = Path(__file__).parent / "fixtures/native_default107_install_54800.json.gz"


@cache
def _fixture():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _binding():
    profile = _fixture()["profile"]
    reader = SaveReader(bytes.fromhex(profile["object_hex"]))
    obj = read_saved_object(reader)
    assert reader.remaining == 0
    reader = SaveReader(bytes.fromhex(profile["saved_master_hex"]))
    saved = read_master(reader, master_id=profile["master_index"], type_group=70)
    assert reader.remaining == 0
    reader = SaveReader(bytes.fromhex(profile["baseline_hex"]), version=0x43E666)
    baseline = read_game_data_master(reader)
    assert reader.remaining == 0
    reader = SaveReader(bytes.fromhex(profile["graphics_hex"]), version=0x43E666)
    graphics = read_game_data_graphics(reader).graphics
    assert reader.remaining == 0
    master = restore_replay_master_components(
        saved, {profile["master_index"]: baseline}, graphics=graphics
    )
    return ReplayInitialObjectBinding(obj, obj.owner, master, None, None, None)


def _install(binding, **changes):
    return install_replay_human_default107(
        binding,
        **{"owner_runtime_type": 1, "cached_options_present": True, "options_mode": 0, **changes},
    )


@pytest.mark.parametrize(
    "row", _fixture()["outputs"], ids=lambda row: f"{row['case']}-{row['repeat']}"
)
def test_all_twelve_original_returns_and_duplicate_payload_preservation(row):
    binding = _binding()
    before = copy.deepcopy(binding)
    initial = None
    if row["repeat"]:
        initial = _install(binding, options_mode=row["mode"], task_index=row["index"]).action
    result = _install(binding, options_mode=row["mode"], task_index=row["index"], current=initial)
    assert result.world_initialization_pending is True
    assert binding == before
    assert row["reference_relations_verified"] and row["object_and_contexts_unchanged"]
    assert row["options_refcount"] == 8
    assert row["outer_scalar_hex"] == bytes(24).hex()
    if row["parent_scalar_hex"] is None:
        assert result.action is None and result.outcome == "no_task"
        return
    action = result.action
    assert action is not None and action.scalar_bytes.hex() == row["parent_scalar_hex"]
    tasks = binding.master.tasks
    assert tasks is not None
    assert action.binding is binding and action.task is tasks.tasks[0]
    assert action.task_index == 0 and action.type_id == 107 and action.state == 6
    assert action.timer_bits == 0 and action.child_head is None
    assert row["child_scalar_hex"] == bytes(24).hex()
    assert row["node_scalar_hex"] == bytes(16).hex()
    assert result.outcome == ("existing" if initial is not None else "installed")
    if initial is not None:
        assert action is initial and action.scalar_bytes is initial.scalar_bytes


def test_real_saved_master_and_inherited_positional_default_binding():
    binding = _binding()
    tasks = binding.master.tasks
    assert tasks is not None
    assert (binding.saved.object_id, binding.saved.owner, binding.saved.master_id) == (
        10449,
        1,
        1245,
    )
    assert tasks.inherited and tasks.default_index == 0 and len(tasks.tasks) == 4
    assert [task.fields[0xE] for task in tasks.tasks] == [107, 6, 3, 3]
    assert tasks.default_task is tasks.tasks[0]
    default = replace(tasks.tasks[0], fields={**tasks.tasks[0].fields, 0xA: 111})
    binding = replace(
        binding,
        master=replace(binding.master, tasks=replace(tasks, tasks=(default, *tasks.tasks[1:]))),
    )
    result = _install(binding)
    assert result.action is not None and result.action.task is default
    assert result.action.task_index == 0 and result.action.task.fields[0xA] == 111


@pytest.mark.parametrize("index", [-32768, -1, 4, 32767])
def test_signed_no_task_indices_do_not_replace_an_existing_action(index):
    binding = _binding()
    existing = _install(binding).action
    assert existing is not None
    result = _install(binding, current=existing, task_index=index)
    assert result.action is existing and result.outcome == "no_task"


def test_default_minus_one_returns_no_action_without_creating_one():
    binding = _binding()
    tasks = binding.master.tasks
    assert tasks is not None
    binding = replace(
        binding, master=replace(binding.master, tasks=replace(tasks, default_index=-1))
    )
    result = _install(binding)
    assert result.action is None and result.outcome == "no_task"


@pytest.mark.parametrize(
    "changes",
    [
        {"owner_runtime_type": 0},
        {"owner_runtime_type": 3},
        {"owner_runtime_type": True},
        {"cached_options_present": False},
        {"cached_options_present": 1},
        {"options_mode": 1},
        {"options_mode": True},
        {"options_mode": 0.0},
        {"task_index": 32768},
        {"task_index": -32769},
        {"task_index": True},
        {"task_index": 0.0},
        {"task_index": 1},
        {"task_index": 2},
        {"task_index": 3},
    ],
)
def test_runtime_premises_index_widths_and_other_factories_rejected(changes):
    with pytest.raises(ReplayDefault107Error):
        _install(_binding(), **changes)


@pytest.mark.parametrize(
    "change",
    [
        {"type_group": 80},
        {"owner": 2},
        {"master_id": 83},
        {"object_id": -1},
        {"flags": (1, 0, 0, 0)},
        {"flags": (True, 0, 0, 0)},
        {"flags": (2,)},
        {"action": None},
    ],
)
def test_inconsistent_saved_context_is_not_silently_admitted(change):
    binding = _binding()
    binding = replace(binding, saved=replace(binding.saved, **change))
    with pytest.raises(ReplayDefault107Error):
        _install(binding)


def test_nonempty_or_unproved_saved_action_variants_rejected():
    binding = _binding()
    action = binding.saved.action
    assert action is not None
    for change in ({"object_map": ((1, 2),)}, {"raw": b""}, {"raw": b"\x01\0"}):
        changed = replace(binding, saved=replace(binding.saved, action=replace(action, **change)))
        with pytest.raises(ReplayDefault107Error):
            _install(changed)


def test_missing_or_wrong_selected_baseline_and_other_task_records_rejected():
    binding = _binding()
    tasks = binding.master.tasks
    assert tasks is not None
    wrong_tag = replace(tasks.tasks[0], definition=replace(tasks.tasks[0].definition, type_id=2))
    for changed in (None, replace(tasks, baseline_index=71), replace(tasks, tasks=(wrong_tag,))):
        with pytest.raises(ReplayDefault107Error):
            _install(replace(binding, master=replace(binding.master, tasks=changed)))


def test_duplicate_requires_same_logical_binding_and_unchanged_initial_profile():
    binding = _binding()
    action = _install(binding).action
    assert action is not None
    tasks = binding.master.tasks
    assert tasks is not None
    changed = bytearray(action.scalar_bytes)
    changed[0x44] = 1
    for current in (
        replace(action, binding=_binding()),
        replace(action, scalar_bytes=bytes(changed)),
        replace(action, task_index=-1),
        replace(action, task=replace(action.task, fields=dict(action.task.fields))),
        replace(action, task_index=1, task=tasks.tasks[1]),
    ):
        with pytest.raises(ReplayDefault107Error):
            _install(binding, current=current)


def test_portable_native_proof_retains_three_exact_omission_controls():
    assert _fixture()["omission_controls"] == [
        {
            "control": i,
            "execute_fault_exact": True,
            "fault_site": site,
            "original_return_verified": True,
        }
        for i, site in enumerate(("helper-entry", "constructor-entry", "allocator-import"), 1)
    ]


@pytest.mark.parametrize(
    "part",
    [
        "binding",
        "saved",
        "master",
        "master_saved",
        "common",
        "tasks",
        "task_tuple",
        "task_entry",
        "task_definition",
        "task_fields",
        "action",
        "action_raw",
        "action_map",
        "flags",
    ],
)
def test_malformed_components_raise_contextual_profile_error_before_dereference(part):
    binding = _binding()
    tasks = binding.master.tasks
    action = binding.saved.action
    assert tasks is not None and action is not None
    if part == "binding":
        changed = None
    elif part in ("saved", "master"):
        changed = replace(binding, **{part: None})
    elif part in ("master_saved", "common", "tasks"):
        key = "saved" if part == "master_saved" else part
        changed = replace(binding, master=replace(binding.master, **{key: None}))
    elif part in ("task_tuple", "task_entry", "task_definition", "task_fields"):
        entry = tasks.tasks[0]
        if part == "task_tuple":
            entries = None
        elif part == "task_entry":
            entries = (None,)
        elif part == "task_definition":
            entries = (replace(entry, definition=None),)
        else:
            entries = (replace(entry, fields=None),)
        changed = replace(
            binding, master=replace(binding.master, tasks=replace(tasks, tasks=entries))
        )
    elif part == "action":
        changed = replace(binding, saved=replace(binding.saved, action=object()))
    elif part in ("action_raw", "action_map"):
        key = "raw" if part == "action_raw" else "object_map"
        changed = replace(
            binding, saved=replace(binding.saved, action=replace(action, **{key: None}))
        )
    else:
        changed = replace(binding, saved=replace(binding.saved, flags=None))
    with pytest.raises(ReplayDefault107Error) as captured:
        _install(changed)
    error = captured.value
    if part not in ("binding", "saved"):
        assert (error.object_id, error.owner, error.master_index) == (10449, 1, 1245)
        assert "object=10449, owner=1, master=1245" in str(error)
    elif part == "saved":
        assert error.owner == 1


def test_action_object_map_has_an_independent_narrow_empty_precondition():
    binding = _binding()
    action = binding.saved.action
    assert action is not None and action.raw[-2:] == b"\0\0"
    changed = replace(
        binding, saved=replace(binding.saved, action=replace(action, object_map=((1, 2),)))
    )
    with pytest.raises(ReplayDefault107Error, match=r"independent saved Action\.object_map"):
        _install(changed)
