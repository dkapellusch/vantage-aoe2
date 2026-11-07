"""Current per-object modifier collection used by native terrain effects.

Build54800 sources141242a60/141247c60 and14122d4b0/14122d970: category
selects a vector, sorted by signed operation. A record's native words are
(operation, category, amount), represented by existing ReplayStatModifier as
(operation, amount_bits, unknown_bits). Current storage must be well formed.
This implements logical successful collection mutations and their notification
order, not native allocators, protected words or physical hash/vector backing.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType

from .replay_movement_cap import ReplayStatModifier, apply_replay_stat_modifiers


class UnresolvedReplayModifierCallbacks(ValueError):
    """A category1 mutation needs actual subject virtual1f0/1e8 bindings."""


class UnsupportedReplayModifierReentrancy(ValueError):
    """The current callback violates this collection's stable-storage premise."""


def _word(value: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{name} must be a raw u32 word")


def _record(value: ReplayStatModifier) -> None:
    if not isinstance(value, ReplayStatModifier):
        raise ValueError("an explicit ReplayStatModifier is required")
    _word(value.operation, "modifier operation")
    _word(value.unknown_bits, "modifier category")
    _word(value.amount_bits, "modifier amount")


def _operation_key(value: ReplayStatModifier) -> int:
    word = value.operation
    return word if word < 0x80000000 else word - 0x100000000


def _ordered_equal(left: int, right: int) -> bool:
    # UCOMISS/JP/JZ: any NaN is unequal, either signed zero compares equal.
    # Integer classification avoids changing host FP status for signaling NaNs.
    left_abs, right_abs = left & 0x7FFFFFFF, right & 0x7FFFFFFF
    if left_abs > 0x7F800000 or right_abs > 0x7F800000:
        return False
    return left == right or left_abs == right_abs == 0


@dataclass(frozen=True, slots=True)
class ReplayModifierCallbacks:
    """Actual subject notifications before and after a category1 change.

    Callers bind current subject virtual1f0 and1e8, respectively, including
    current owner and native argument semantics. They may query this collection
    to observe old/new values, but must not mutate its records or backing.
    No callbacks or subject/owner identities are synthesized by this module.
    """

    before_change: Callable[[], None]
    after_change: Callable[[], None]

    def __post_init__(self) -> None:
        if not callable(self.before_change) or not callable(self.after_change):
            raise ValueError("both modifier notifications must be callable")


class ReplayAttributeModifiers:
    """Mutable current category vectors, with immutable inspection snapshots.

    The initial mapping is required: an empty mapping explicitly establishes
    no current records. It is not inferred from a save or absent terrain data.
    Inputs are copied and must be sorted by signed operation within each exact
    category. Equal operations retain their given order. Empty categories are
    retained after removal, matching the native method's unerased map node.

    Stable descriptor/storage and ordinary successful allocation are premises.
    Reentrant collection mutation from notifications is explicitly refused;
    native pointer invalidation and arbitrary callback mutation are not modeled.
    Callback exceptions propagate with already completed mutations retained.
    """

    def __init__(self, initial: Mapping[int, tuple[ReplayStatModifier, ...]]) -> None:
        if not isinstance(initial, Mapping):
            raise ValueError("an explicit current modifier mapping is required")
        vectors = {}
        for category, records in initial.items():
            _word(category, "modifier category")
            if type(records) is not tuple:
                raise ValueError("initial modifier vectors must be immutable tuples")
            for record in records:
                _record(record)
                if record.unknown_bits != category:
                    raise ValueError("modifier category disagrees with containing vector")
            if any(_operation_key(a) > _operation_key(b) for a, b in pairwise(records)):
                raise ValueError("initial modifier vector is not signed-operation sorted")
            vectors[category] = list(records)
        self._vectors: dict[int, list[ReplayStatModifier]] = vectors
        self._in_callback = False

    def snapshot(self) -> Mapping[int, tuple[ReplayStatModifier, ...]]:
        """Copy logical categories/vectors; native hash iteration order is excluded."""
        return MappingProxyType({key: tuple(records) for key, records in self._vectors.items()})

    def records(self, category: int) -> tuple[ReplayStatModifier, ...]:
        _word(category, "modifier category")
        return tuple(self._vectors.get(category, ()))

    def apply(self, category: int, value_bits: int) -> int:
        """1412428d0: apply this current category vector in its stored order."""
        _word(value_bits, "unmodified stat")
        return apply_replay_stat_modifiers(value_bits, self.records(category))

    def _admit(self, modifier: ReplayStatModifier) -> None:
        if self._in_callback:
            raise UnsupportedReplayModifierReentrancy(
                "modifier notification changed its collection"
            )
        _record(modifier)

    @staticmethod
    def _callbacks(
        category: int, callbacks: ReplayModifierCallbacks | None
    ) -> ReplayModifierCallbacks | None:
        if callbacks is not None and not isinstance(callbacks, ReplayModifierCallbacks):
            raise ValueError("modifier callbacks must be explicitly bound or unavailable")
        if category == 1:
            if callbacks is None:
                raise UnresolvedReplayModifierCallbacks(
                    "category1 requires both subject notifications"
                )
            return callbacks
        return None

    def _notify(self, callback: Callable[[], None]) -> None:
        self._in_callback = True
        try:
            callback()
        finally:
            self._in_callback = False

    def add(
        self, modifier: ReplayStatModifier, *, callbacks: ReplayModifierCallbacks | None
    ) -> None:
        """Insert before existing equal signed operations, with category1 notifications."""
        self._admit(modifier)
        bound = self._callbacks(modifier.unknown_bits, callbacks)
        if bound is not None:
            self._notify(bound.before_change)
        records = self._vectors.setdefault(modifier.unknown_bits, [])
        index = bisect_left(records, _operation_key(modifier), key=_operation_key)
        records.insert(index, modifier)
        if bound is not None:
            self._notify(bound.after_change)

    def remove(
        self, modifier: ReplayStatModifier, *, callbacks: ReplayModifierCallbacks | None
    ) -> bool:
        """Remove the first equal operation/category/ordered-float amount, if any.

        Missing categories/records perform no notification or map insertion.
        NaN amounts cannot match; positive and negative zero can match. Removal
        keeps every other record in order and retains an emptied category.
        """
        self._admit(modifier)
        records = self._vectors.get(modifier.unknown_bits)
        if not records:
            return False
        operation = _operation_key(modifier)
        start = bisect_left(records, operation, key=_operation_key)
        end = bisect_right(records, operation, key=_operation_key)
        for index in range(start, end):
            if _ordered_equal(records[index].amount_bits, modifier.amount_bits):
                bound = self._callbacks(modifier.unknown_bits, callbacks)
                if bound is not None:
                    self._notify(bound.before_change)
                records.pop(index)
                if bound is not None:
                    self._notify(bound.after_change)
                return True
        return False
