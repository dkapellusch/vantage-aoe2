"""Ordered owner-catalog promotion with explicitly resolved classifications.

This models native14111b570's logical vectors under successful allocation.
The caller supplies the current Player+18 catalog and classifications returned
by141729140. It does not infer variant mappings, initialize the catalog, execute
a transform, or reproduce allocation failures and diagnostic logging.
Evidence: world-envelope/first-building-transform-owner-bookkeeping/README.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

_MASK = 0xFFFFFFFF


def _word(value: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= _MASK:
        raise ValueError(f"{name} must be a raw unsigned32 word")


def _signed(value: int, name: str) -> None:
    if type(value) is not int or not -(1 << 31) <= value < 1 << 31:
        raise ValueError(f"{name} must be a signed32 integer")


@dataclass(frozen=True, slots=True)
class ReplayOwnerClassification:
    """The resolved12-byte tuple; promotion reads only its first two words.

    Native initialization uses the low flags byte for pending90000 groups.
    Promotion ignores flags and uses the ordinary master/class keys directly.
    No native validity check or class derivation is performed here.
    """

    master_id: int
    class_id: int = -1
    flags: int = 0

    def __post_init__(self) -> None:
        _signed(self.master_id, "classification master ID")
        _signed(self.class_id, "classification class ID")
        _word(self.flags, "classification flags")


@dataclass(frozen=True, slots=True)
class ReplayOwnerPromotion:
    """Logical groups after promotion; catalog counters are unaffected.

    Each tuple retains the native vector's active raw-ID order and duplicates.
    Mapping iteration order does not model the native unordered-map order.
    """

    groups: Mapping[int, tuple[int, ...]]
    tracked: bool


def promote_replay_owner_object(
    catalog: Mapping[int, tuple[int, ...]],
    object_id: int,
    old: ReplayOwnerClassification,
    new: ReplayOwnerClassification,
) -> ReplayOwnerPromotion:
    """Apply the five original phases against one logical catalog snapshot.

    Lookup creates an empty old-key group even for an untracked object. A
    tracked object loses its first old-master occurrence and is appended to
    the new-master group without deduplication. Old-class erase and new-class
    append follow, skipping exactly class=-1 and wrapping key additions to32
    bits. Equal/colliding keys observe every earlier mutation in this order.

    Inputs remain unchanged. Native node storage, capacity/growth, stale
    inactive vector words and failure-time partial effects are outside this
    successful-allocation logical view. Counter fields60/64/68/6c, the separate
    tracker40 vector and second map70 are untouched by this native component.
    """
    _word(object_id, "object ID")
    if not isinstance(old, ReplayOwnerClassification) or not isinstance(
        new, ReplayOwnerClassification
    ):
        raise ValueError("promotion requires resolved old and new classifications")
    if not isinstance(catalog, Mapping):
        raise ValueError("catalog must map raw keys to ordered raw-ID tuples")
    groups: dict[int, tuple[int, ...]] = {}
    for key, values in catalog.items():
        _word(key, "catalog key")
        if not isinstance(values, tuple):
            raise ValueError("catalog groups must be ordered raw-ID tuples")
        for value in values:
            _word(value, "catalog object ID")
        groups[key] = values

    def erase(key: int) -> None:
        values = groups.setdefault(key & _MASK, ())
        try:
            index = values.index(object_id)
        except ValueError:
            return
        groups[key & _MASK] = values[:index] + values[index + 1 :]

    def append(key: int) -> None:
        key &= _MASK
        groups[key] = (*groups.get(key, ()), object_id)

    initial = groups.setdefault(old.master_id & _MASK, ())
    if object_id not in initial:
        return ReplayOwnerPromotion(MappingProxyType(groups), False)
    erase(old.master_id)
    append(new.master_id)
    if old.class_id != -1:
        erase(old.class_id + 900)
    if new.class_id != -1:
        append(new.class_id + 900)
    return ReplayOwnerPromotion(MappingProxyType(groups), True)
