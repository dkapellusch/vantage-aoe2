"""Native object-list traversal, without object behavior or clock advancement.

The 100-byte native dispatcher0x141229a20 calls each object's virtual+0x30
then, for a nonzero returned byte, virtual+0x18 on the same object. Ordinary
and dopple lists use this dispatcher in distinct native update phases. The
callbacks supplied here stand for those two methods; this does not implement
movement, actions, UnitAI, deletion, list compaction or replay scheduling.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class ObjectUpdateList[T]:
    """Mutable native list window: backing items and signed live count.

    Callbacks may replace the backing array, change later slots and change
    the count. Every positive live index must refer to a valid object. Slots
    beyond ``count`` represent unused capacity and are never visited.
    """

    items: list[T]
    count: int


def update_object_list[T](
    state: ObjectUpdateList[T], update: Callable[[T], bool], post_update: Callable[[T], None]
) -> None:
    """Apply the exact native mutable-list/callback traversal contract.

    A true update result calls post_update on that same object and revisits
    the same index. A false result advances one slot. The backing array and
    signed count are reread as traversal proceeds, so appends, replacements
    and count changes made by either callback affect this pass immediately.
    Callbacks own all list mutation; their exceptions propagate with prior
    mutations intact. There is no snapshot, automatic removal or retry cap.
    """
    index = 0
    while index < state.count:
        current = state.items[index]
        if update(current):
            post_update(current)
        else:
            index += 1
