"""Native signed-ID ordering of restored player object lists.

Saved records retain their wire order and raw flags. This separate runtime
view follows common reader 0x14125d730 and sorted insert 0x141228090. It does
not construct the World's ID lookup arrays or apply object reference fixups.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from vantage.replay_object_lists import SavedPlayerObjectLists
from vantage.replay_objects import SavedObject

ObjectListName = Literal["ordinary", "sleeping", "dopple"]


def signed_object_id(raw_id: int) -> int:
    """Interpret the saved u32 at native object+8 as the signed ordering key.

    ID zero is valid. Spectator-assigned negative presentation IDs are not
    saved u32 values and must not be substituted for this native member.
    """
    if type(raw_id) is not int or not 0 <= raw_id <= 0xFFFFFFFF:
        raise ValueError("object ID must contain the raw unsigned 32-bit member")
    return raw_id if raw_id < 0x80000000 else raw_id - 0x100000000


def runtime_object_list_name(obj: SavedObject) -> ObjectListName:
    """Classify the runtime bytes after the common saved-reader override.

    The saved bytes are +188/+189/+18a/+18b. A nonzero +18b clears runtime
    +189 before insertion; sleeping then has precedence over dopple. The
    object's saved flags and its original wire list remain unchanged.
    """
    if len(obj.flags) != 4 or any(type(x) is not int or not 0 <= x <= 255 for x in obj.flags):
        raise ValueError("saved object flags must contain four raw bytes")
    if obj.flags[1] and not obj.flags[3]:
        return "sleeping"
    return "dopple" if obj.flags[2] else "ordinary"


def insert_runtime_object(
    ordered: tuple[SavedObject, ...], obj: SavedObject
) -> tuple[SavedObject, ...]:
    """Return native sorted insertion into an already sorted unique list.

    Comparison uses signed object+8. An equal ID preserves the existing
    object, even when the new object has different fields. Native allocation
    capacity/growth and the independent World lookup registration are outside
    this value-level helper. Invalid input fails without changing either tuple.
    """
    keys = tuple(signed_object_id(item.object_id) for item in ordered)
    if any(left >= right for left, right in pairwise(keys)):
        raise ValueError("runtime list must have strictly increasing signed object IDs")
    key = signed_object_id(obj.object_id)
    low, high = 0, len(keys)
    while low < high:
        middle = (low + high) // 2
        if keys[middle] < key:
            low = middle + 1
        else:
            high = middle
    if low < len(keys) and keys[low] == key:
        return ordered
    return (*ordered[:low], obj, *ordered[low:])


@dataclass(frozen=True, slots=True)
class RuntimePlayerObjectLists:
    """Three effective native lists; duplicates are suppressed per list."""

    ordinary: tuple[SavedObject, ...]
    sleeping: tuple[SavedObject, ...]
    dopple: tuple[SavedObject, ...]

    @property
    def update_order(self) -> tuple[SavedObject, ...]:
        """Player second-pass traversal: ordinary, sleeping, then dopple."""
        return (*self.ordinary, *self.sleeping, *self.dopple)


def restore_runtime_object_lists(saved: SavedPlayerObjectLists) -> RuntimePlayerObjectLists:
    """Construct effective lists in native saved-reader construction order.

    Readers consume ordinary, sleeping and dopple wire lists in that order.
    Each object's runtime flags select its destination independently of the
    wire list. Within that destination, retain the first equal raw ID and sort
    by signed ID. This yields the same list contents as repeated native insert
    without modeling its backing allocation. Saved records are never mutated.
    """
    ordinary: dict[int, SavedObject] = {}
    sleeping: dict[int, SavedObject] = {}
    dopple: dict[int, SavedObject] = {}
    groups = {"ordinary": ordinary, "sleeping": sleeping, "dopple": dopple}
    for wire_list in (saved.ordinary, saved.sleeping, saved.dopple):
        for obj in wire_list.objects:
            key = signed_object_id(obj.object_id)
            groups[runtime_object_list_name(obj)].setdefault(key, obj)
    return RuntimePlayerObjectLists(
        tuple(ordinary[key] for key in sorted(ordinary)),
        tuple(sleeping[key] for key in sorted(sleeping)),
        tuple(dopple[key] for key in sorted(dopple)),
    )
