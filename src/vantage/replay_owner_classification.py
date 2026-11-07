"""Native owner classification using explicitly known current context.

Models141729140 and its two variant getters without selecting runtime files or
initializing a catalog. Unknown context fails at the read that requires it.
Pointer reads before numeric gates are retained as explicit known-slot lookups;
no null padding or completed initialization is inferred.
Evidence: world-envelope/owner-classifier-observed-v1 and
owner-classification-variant-inputs. Independent playback remains unfinished.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from vantage.replay_owner_promotion import ReplayOwnerClassification

_MASK = 0xFFFFFFFF
_HIGH_CLASSES = frozenset(
    (
        0,
        6,
        12,
        17,
        18,
        20,
        22,
        23,
        24,
        25,
        26,
        28,
        35,
        36,
        43,
        44,
        45,
        46,
        47,
        50,
        52,
        53,
        56,
        57,
        59,
    )
)


class UnresolvedReplayOwnerClassification(ValueError):
    """Required current storage or scalar is not explicitly known."""


def _integer(value: int, low: int, high: int, name: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")


def _i32(value: int) -> int:
    value &= _MASK
    return value - 0x100000000 if value & 0x80000000 else value


@dataclass(frozen=True, slots=True)
class ReplayOwnerMasterClassificationInput:
    """Explicit current fields; class is already decoded from protected storage.

    None denotes unknown. A non-Building never reads the three Building fields;
    a suppressed class never consumes decoded_class. Saved scalar values need
    an independent restoration/preservation binding before being supplied here.
    """

    family: int
    decoded_class: int | None = None
    member_426: int | None = None
    member_458: int | None = None
    member_430: int | None = None

    def __post_init__(self) -> None:
        _integer(self.family, 0, 255, "master family")
        for name in ("decoded_class", "member_426", "member_458", "member_430"):
            value = getattr(self, name)
            if value is not None:
                _integer(value, -32768, 32767, name)

    def required(self, name: str) -> int:
        value = getattr(self, name)
        if value is None:
            raise UnresolvedReplayOwnerClassification(f"unknown current master field {name}")
        assert isinstance(value, int)
        return value


@dataclass(frozen=True, slots=True)
class ReplayOwnerClassificationContext:
    """Known current storage, allowing explicit sparse payload observations.

    A present slot with None is known null; an absent key is unknown. Negative
    slots are accepted only when explicitly supplied as backed storage, as in
    the bounded oracle. They are not native array-safety guarantees. Counts
    retain full qword bits; getters compare only their signed low32 words.
    Group/selections may be None when their pointers are unavailable; a gate
    that would read them then fails explicitly instead of assuming -1 values.
    Selection keys are physical array indices, not negative LineID values.
    """

    master_slots: Mapping[int, ReplayOwnerMasterClassificationInput | None]
    row_count: int
    selection_count: int
    groups: Mapping[int, int] | None
    selections: Mapping[int, int] | None

    def __post_init__(self) -> None:
        _integer(self.row_count, 0, (1 << 64) - 1, "variant row count")
        _integer(self.selection_count, 0, (1 << 64) - 1, "canonical selection count")
        if not isinstance(self.master_slots, Mapping):
            raise ValueError("explicit known master slots are required")
        slots = dict(self.master_slots)
        for key, value in slots.items():
            _integer(key, -(1 << 31), (1 << 31) - 1, "master slot")
            if value is not None and not isinstance(value, ReplayOwnerMasterClassificationInput):
                raise ValueError("master slots must contain explicit inputs or known nulls")
        object.__setattr__(self, "master_slots", MappingProxyType(slots))
        for name in ("groups", "selections"):
            mapping = getattr(self, name)
            if mapping is None:
                continue
            if not isinstance(mapping, Mapping):
                raise ValueError(f"{name} must be explicit known indexed values")
            values = dict(mapping)
            for key, value in values.items():
                _integer(key, 0, (1 << 31) - 1, f"{name} index")
                _integer(value, -(1 << 31), (1 << 31) - 1, f"{name} value")
            object.__setattr__(self, name, MappingProxyType(values))

    def slot(self, index: int) -> ReplayOwnerMasterClassificationInput | None:
        if index not in self.master_slots:
            raise UnresolvedReplayOwnerClassification(f"unknown current master slot {index}")
        return self.master_slots[index]


def _known(mapping: Mapping[int, int] | None, index: int, name: str) -> int:
    if mapping is None or index not in mapping:
        raise UnresolvedReplayOwnerClassification(f"unknown current {name}[{index}]")
    return mapping[index]


def classify_replay_owner_master(
    context: ReplayOwnerClassificationContext, master_id: int
) -> ReplayOwnerClassification:
    """Resolve the original logical tuple using explicit current read premises.

    Numeric invalidity yields the native invalid tuple only after every earlier
    storage read is resolved. This helper neither initializes the catalog nor
    changes any context or saved state. It does not select/load unitlines.json.
    """
    _integer(master_id, 0, _MASK, "requested raw master ID")
    invalid = ReplayOwnerClassification(-1, -1, 0)
    if master_id >= 9000:
        return invalid
    if not isinstance(context, ReplayOwnerClassificationContext):
        raise ValueError("explicit current classification context is required")
    original = context.slot(master_id)
    if original is None:
        return invalid
    candidate, flags, allow_class = master_id, 0, True
    if original.family == 80:
        annex = original.required("member_426")
        if annex != -1:
            candidate = annex
            if context.slot(candidate) is None or (annex & 0xFFFF) >= 9000:
                return invalid
        if original.required("member_458") != -1:
            allow_class = original.required("member_430") != -1
        flags = 1
    if 0 <= candidate < _i32(context.row_count):
        group = _known(context.groups, candidate, "variant group")
        if group != -1:
            index = _i32(group + 399)
            candidate = (
                _known(context.selections, group + 399, "canonical selection")
                if 0 <= index < _i32(context.selection_count)
                else -1
            )
    final = context.slot(candidate)
    if final is None or (candidate & _MASK) >= 9000:
        return invalid
    class_id = final.required("decoded_class") if allow_class else -1
    if not 0 <= class_id < 100:
        return ReplayOwnerClassification(candidate, -1, flags)
    if class_id in (51, 54, 68):
        flags = 0
    if class_id in _HIGH_CLASSES:
        flags |= 256
    return ReplayOwnerClassification(candidate, class_id, flags)
