"""Native-derived logical owner registration, completion and counter updates.

Models14111a250/14111a520/14111b540 with caller-resolved classifications and
successful allocation. Ordered logical groups and raw counter words match all
88 original-code intermediate results in owner-registration-observed-v1.
Node storage, capacity, formatting, logging and failure effects remain outside
this helper. Initial catalog restoration and independent playback are unfinished.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from vantage.replay_owner_promotion import ReplayOwnerClassification

_MASK = 0xFFFFFFFF


def _word(value: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= _MASK:
        raise ValueError(f"{name} must be a raw unsigned32 word")


@dataclass(frozen=True, slots=True)
class ReplayOwnerCatalogState:
    """Logical ordered groups and the four raw tracker counter words.

    Map iteration order is not the native unordered-map order. Every active
    vector retains order and duplicate raw object IDs. Counter meanings are
    deliberately left at their native offsets; no new semantic names assumed.
    """

    groups: Mapping[int, tuple[int, ...]]
    counter60: int
    counter64: int
    counter68: int
    counter6c: int

    def __post_init__(self) -> None:
        if not isinstance(self.groups, Mapping):
            raise ValueError("catalog must map raw keys to ordered raw-ID tuples")
        groups = dict(self.groups)
        for key, values in groups.items():
            _word(key, "catalog key")
            if not isinstance(values, tuple):
                raise ValueError("catalog groups must be immutable raw-ID tuples")
            for value in values:
                _word(value, "catalog object ID")
        object.__setattr__(self, "groups", MappingProxyType(groups))
        for name in ("counter60", "counter64", "counter68", "counter6c"):
            _word(getattr(self, name), name)


def register_replay_owner_object(
    state: ReplayOwnerCatalogState,
    object_id: int,
    classification: ReplayOwnerClassification,
) -> ReplayOwnerCatalogState:
    """Append unit then optional class group, then update original raw counters.

    Any nonzero low flags byte selects the90000 pending offset. The high byte
    has no effect. Class=-1 alone omits the class append. Aliasing keys see both
    appends in original order. The reserved signed master900..999 formatting
    path remains unsupported; it executes even when debug logging is disabled.
    """
    _word(object_id, "object ID")
    if not isinstance(classification, ReplayOwnerClassification):
        raise ValueError("resolved classification required")
    if 900 <= classification.master_id < 1000:
        raise ValueError("reserved master formatting remains unsupported")
    pending = bool(classification.flags & 255)
    offset = 90000 if pending else 0
    groups = dict(state.groups)

    def append(key: int) -> None:
        key &= _MASK
        groups[key] = (*groups.get(key, ()), object_id)

    append(classification.master_id + offset)
    if classification.class_id != -1:
        append(classification.class_id + 900 + offset)
    return ReplayOwnerCatalogState(
        groups,
        (state.counter60 + (not pending)) & _MASK,
        (state.counter64 + pending) & _MASK,
        (state.counter68 + (not pending)) & _MASK,
        state.counter6c,
    )


def complete_replay_owner_object(
    state: ReplayOwnerCatalogState,
    object_id: int,
    classification: ReplayOwnerClassification,
) -> ReplayOwnerCatalogState:
    """First-erase pending, then append ordinary only if absent; counters unchanged.

    Unit phase precedes class phase, so colliding keys see earlier mutations.
    Both native lookup helpers create an empty group when absent under
    successful allocation; no pending presence or membership is assumed.
    A zero low flags byte performs no catalog lookup or counter update.
    """
    _word(object_id, "object ID")
    if not isinstance(classification, ReplayOwnerClassification):
        raise ValueError("resolved classification required")
    if not classification.flags & 255:
        return state
    groups = dict(state.groups)

    def move(pending: int, ordinary: int) -> None:
        pending, ordinary = pending & _MASK, ordinary & _MASK
        values = groups.setdefault(pending, ())
        if object_id in values:
            at = values.index(object_id)
            groups[pending] = values[:at] + values[at + 1 :]
        values = groups.setdefault(ordinary, ())
        if object_id not in values:
            groups[ordinary] = (*values, object_id)

    move(classification.master_id + 90000, classification.master_id)
    if classification.class_id != -1:
        move(classification.class_id + 90900, classification.class_id + 900)
    return replace(state, groups=groups)


def add_replay_owner_counter6c(
    state: ReplayOwnerCatalogState, delta: int
) -> ReplayOwnerCatalogState:
    """Sign-extend an already resolved native i16 delta and wrap the raw32 word."""
    if type(delta) is not int or not -32768 <= delta <= 32767:
        raise ValueError("counter6c delta must be signed16")
    return replace(state, counter6c=(state.counter6c + delta) & _MASK)
