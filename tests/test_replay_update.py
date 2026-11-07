"""Portable oracles captured by executing the original bounded native helper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from vantage.replay_update import ObjectUpdateList, update_object_list

FIXTURE = Path(__file__).parent / "fixtures/native_object_update_dispatch_54800.json"
ORACLE = json.loads(FIXTURE.read_text())


@dataclass
class _Object:
    id: int
    updates: int = 0


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda case: case["name"])
def test_dispatch_matches_original100_byte_native_helper(case) -> None:
    name = case["name"]
    objects = [_Object(i) for i in range(5)]
    count = 0 if name == "empty" else -1 if name == "negative_count" else 3
    if name in ("append_reallocate", "post_without_removal"):
        count = 2
    state = ObjectUpdateList([objects[1], objects[2], objects[3], objects[0]], count)
    trace = []

    def update(obj: _Object) -> bool:
        trace.append(f"U{obj.id}")
        obj.updates += 1
        if obj.id == 1 and obj.updates == 1:
            if name == "update_removes_itself":
                state.items[: state.count - 1] = state.items[1 : state.count]
                state.count -= 1
                return True
            if name in ("post_swap_remove", "post_shift_remove", "post_without_removal"):
                return True
            if name == "append_reallocate":
                state.items = [*state.items[: state.count], objects[3], *([objects[0]] * 5)]
                state.count += 1
            if name == "shrink_count":
                state.count = 1
            if name == "replace_later":
                state.items[1] = objects[4]
            if name == "negative_during_update":
                state.count = -1
        return False

    def post_update(obj: _Object) -> None:
        trace.append(f"P{obj.id}")
        if name == "update_removes_itself":
            return
        at = next(i for i in range(state.count) if state.items[i] is obj)
        if name == "post_swap_remove":
            state.count -= 1
            state.items[at] = state.items[state.count]
        elif name == "post_shift_remove":
            state.items[at : state.count - 1] = state.items[at + 1 : state.count]
            state.count -= 1

    update_object_list(state, update, post_update)
    assert ",".join(trace) == case["trace"]
    assert state.count == case["final_count"]
    assert [state.items[i].id for i in range(max(0, state.count))] == case["active_ids"]
    assert [o.updates for o in objects[1:]] == case["updates"]


def test_callback_exception_preserves_already_applied_mutations() -> None:
    state = ObjectUpdateList([1, 2, 3], 3)

    def update(obj: int) -> bool:
        state.items[2] = 99
        state.count = 2
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        update_object_list(state, update, lambda obj: None)
    assert state.items == [1, 2, 99] and state.count == 2


def test_oracle_has_pinned_original_bytes_and_controlled_execution_scope() -> None:
    import hashlib

    assert ORACLE["target_sha256"] == (
        "69832b9d51145a4bb280da876880198ee0347947098e77098016b9bcbb8d8788"
    )
    raw = bytes.fromhex(ORACLE["code_hex"])
    assert len(raw) == ORACLE["code_bytes"] == 100
    assert hashlib.sha256(raw).hexdigest() == ORACLE["code_sha256"]
    assert ORACLE["game_launched"] is False
    assert ORACLE["original_imports_or_globals_used"] is False
