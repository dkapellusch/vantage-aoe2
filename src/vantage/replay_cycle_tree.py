"""Six complete logical build54800 cycle-queue red-black tree bodies.

cycle-tree-source-v1 retains whole originals and the pre-code API. This owns
source-ordered storage and balancing; actual sized-free effects are required.
It initializes no header/nodes and does not restore a recording World.
"""

from __future__ import annotations

from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _read,
    _write,
)
from .replay_unit_ai_base import _validate

_U64 = (1 << 64) - 1
_EXTRACT, _LINK, _CLEAR = 0x140E642F0, 0x140E646E0, 0x140E64A00
_SUBTREE, _LEFT, _RIGHT, _FREE = 0x140E62D90, 0x140E64940, 0x140E649A0, 0x142D6BAB4
_ARITIES = {_EXTRACT: 2, _LINK: 3, _CLEAR: 1, _SUBTREE: 3, _LEFT: 2, _RIGHT: 2}


class _Tree:
    def __init__(self, context: ReplayTaskRebuildStorage, calls: ReplayTaskRebuildCalls) -> None:
        self.context, self.calls = context, calls

    def r(self, address: int, width: int = 8) -> int:
        return _read(self.context, address, width)

    def w(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def call(self, target: int, *args: int) -> int | None:
        if self.calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return self.calls.call(target, tuple(value & _U64 for value in args), None)

    def left(self, tree: int, node: int, pivot: int | None = None) -> None:
        # The inline forms already hold the pivot. Addressed64940 loads it.
        if pivot is None:
            pivot = self.r(node + 0x10)
        self.w(node + 0x10, 8, self.r(pivot))
        child = self.r(pivot)
        if not self.r(child + 0x19, 1):
            self.w(child + 8, 8, node)
        self.w(pivot + 8, 8, self.r(node + 8))
        header = self.r(tree)
        if node == self.r(header + 8):
            self.w(header + 8, 8, pivot)
        else:
            parent = self.r(node + 8)
            if node == self.r(parent):
                self.w(parent, 8, pivot)
            else:
                self.w(parent + 0x10, 8, pivot)
        self.w(pivot, 8, node)
        self.w(node + 8, 8, pivot)

    def right(self, tree: int, node: int, pivot: int | None = None) -> None:
        if pivot is None:
            pivot = self.r(node)
        self.w(node, 8, self.r(pivot + 0x10))
        child = self.r(pivot + 0x10)
        if not self.r(child + 0x19, 1):
            self.w(child + 8, 8, node)
        self.w(pivot + 8, 8, self.r(node + 8))
        header = self.r(tree)
        if node == self.r(header + 8):
            self.w(header + 8, 8, pivot)
        else:
            parent = self.r(node + 8)
            if node == self.r(parent + 0x10):
                self.w(parent + 0x10, 8, pivot)
            else:
                self.w(parent, 8, pivot)
        self.w(pivot + 0x10, 8, node)
        self.w(node + 8, 8, pivot)

    def link(self, tree: int, position: int, node: int) -> int:
        self.w(tree + 8, 8, self.r(tree + 8) + 1)
        header = self.r(tree)
        parent = self.r(position)
        self.w(node + 8, 8, parent)
        if parent == header:
            self.w(header, 8, node)
            self.w(header + 8, 8, node)
            self.w(header + 0x10, 8, node)
            self.w(node + 0x18, 1, 1)
            return node
        if self.r(position + 8, 4):
            self.w(parent, 8, node)
            if parent == self.r(header):
                self.w(header, 8, node)
        else:
            self.w(parent + 0x10, 8, node)
            if parent == self.r(header + 0x10):
                self.w(header + 0x10, 8, node)
        current = node
        parent = self.r(node + 8)
        while self.r(parent + 0x18, 1) == 0:
            parent = self.r(current + 8)
            grand = self.r(parent + 8)
            left = self.r(grand)
            if parent == left:
                uncle = self.r(grand + 0x10)
                if self.r(uncle + 0x18, 1) == 0:
                    self.w(parent + 0x18, 1, 1)
                    self.w(uncle + 0x18, 1, 1)
                    grand = self.r(self.r(current + 8) + 8)
                    self.w(grand + 0x18, 1, 0)
                    current = self.r(self.r(current + 8) + 8)
                else:
                    pivot = self.r(parent + 0x10)
                    if current == pivot:
                        current = parent
                        self.left(tree, parent, pivot)
                    self.w(self.r(current + 8) + 0x18, 1, 1)
                    grand = self.r(self.r(current + 8) + 8)
                    self.w(grand + 0x18, 1, 0)
                    grand = self.r(self.r(current + 8) + 8)
                    pivot = self.r(grand)
                    self.right(tree, grand, pivot)
            elif self.r(left + 0x18, 1) == 0:
                self.w(parent + 0x18, 1, 1)
                self.w(left + 0x18, 1, 1)
                grand = self.r(self.r(current + 8) + 8)
                self.w(grand + 0x18, 1, 0)
                current = self.r(self.r(current + 8) + 8)
            else:
                pivot = self.r(parent)
                if current == pivot:
                    current = parent
                    self.right(tree, parent, pivot)
                self.w(self.r(current + 8) + 0x18, 1, 1)
                grand = self.r(self.r(current + 8) + 8)
                self.w(grand + 0x18, 1, 0)
                grand = self.r(self.r(current + 8) + 8)
                pivot = self.r(grand + 0x10)
                self.left(tree, grand, pivot)
            parent = self.r(current + 8)
        self.w(self.r(header + 8) + 0x18, 1, 1)
        return node

    def fix(self, tree: int, child: int, parent: int) -> None:
        header = self.r(tree)
        if child != self.r(header + 8) and self.r(child + 0x18, 1) == 1:
            held_parent = parent
            while True:
                left = self.r(parent)
                if child == left:
                    sibling = self.r(parent + 0x10)
                    if self.r(sibling + 0x18, 1) == 0:
                        self.w(sibling + 0x18, 1, 1)
                        sibling = self.r(parent + 0x10)
                        self.w(parent + 0x18, 1, 0)
                        self.left(tree, parent, sibling)
                        sibling = self.r(parent + 0x10)
                    parent_home = (parent + 8) & _U64
                    propagate = bool(self.r(sibling + 0x19, 1))
                    if not propagate:
                        near = self.r(sibling)
                        if self.r(near + 0x18, 1) == 1:
                            far = self.r(sibling + 0x10)
                            propagate = self.r(far + 0x18, 1) == 1
                        if propagate:
                            self.w(sibling + 0x18, 1, 0)
                        else:
                            far = self.r(sibling + 0x10)
                            if self.r(far + 0x18, 1) == 1:
                                self.w(near + 0x18, 1, 1)
                                self.w(sibling + 0x18, 1, 0)
                                self.call(_RIGHT, tree, sibling)
                                sibling = self.r(parent + 0x10)
                            self.w(sibling + 0x18, 1, self.r(parent + 0x18, 1))
                            self.w(parent + 0x18, 1, 1)
                            self.w(self.r(sibling + 0x10) + 0x18, 1, 1)
                            self.call(_LEFT, tree, parent)
                            break
                else:
                    sibling = left
                    if self.r(sibling + 0x18, 1) == 0:
                        self.w(sibling + 0x18, 1, 1)
                        sibling = self.r(parent)
                        self.w(parent + 0x18, 1, 0)
                        self.right(tree, parent, sibling)
                        sibling = self.r(parent)
                    parent_home = (parent + 8) & _U64
                    propagate = bool(self.r(sibling + 0x19, 1))
                    if not propagate:
                        near = self.r(sibling + 0x10)
                        if self.r(near + 0x18, 1) == 1:
                            far = self.r(sibling)
                            propagate = self.r(far + 0x18, 1) == 1
                        if propagate:
                            self.w(sibling + 0x18, 1, 0)
                        else:
                            far = self.r(sibling)
                            if self.r(far + 0x18, 1) == 1:
                                self.w(near + 0x18, 1, 1)
                                self.w(sibling + 0x18, 1, 0)
                                self.call(_LEFT, tree, sibling)
                                sibling = self.r(parent)
                            self.w(sibling + 0x18, 1, self.r(parent + 0x18, 1))
                            self.w(parent + 0x18, 1, 1)
                            self.w(self.r(sibling) + 0x18, 1, 1)
                            self.call(_RIGHT, tree, parent)
                            break
                header = self.r(tree)
                child = held_parent
                parent = self.r(parent_home)
                if child == self.r(header + 8):
                    break
                color = self.r(child + 0x18, 1)
                held_parent = parent
                if color != 1:
                    break
        self.w(child + 0x18, 1, 1)

    def extract(self, tree: int, original: int) -> int:
        right = self.r(original + 0x10)
        child = right
        right_nil = self.r(right + 0x19, 1)
        if right_nil:
            successor = self.r(original + 8)
            cursor = original
            if not self.r(successor + 0x19, 1):
                while cursor == self.r(successor + 0x10):
                    cursor = successor
                    successor = self.r(successor + 8)
                    if self.r(successor + 0x19, 1):
                        break
        else:
            cursor = self.r(right)
            successor = right
            if not self.r(cursor + 0x19, 1):
                while True:
                    following = self.r(cursor)
                    successor, cursor = cursor, following
                    if self.r(cursor + 0x19, 1):
                        break
        parent_home = (original + 8) & _U64
        left = self.r(original)
        relocate = False
        if not self.r(left + 0x19, 1):
            if right_nil:
                child = left
            else:
                child = self.r(successor + 0x10)
                relocate = successor != original
        if relocate:
            self.w(left + 8, 8, successor)
            self.w(successor, 8, self.r(original))
            if successor == self.r(original + 0x10):
                parent = successor
            else:
                child_nil = self.r(child + 0x19, 1)
                parent = self.r(successor + 8)
                if not child_nil:
                    self.w(child + 8, 8, parent)
                self.w(parent, 8, child)
                self.w(successor + 0x10, 8, self.r(original + 0x10))
                self.w(self.r(original + 0x10) + 8, 8, successor)
            header = self.r(tree)
            if original == self.r(header + 8):
                self.w(header + 8, 8, successor)
            else:
                old_parent = self.r(parent_home)
                if original == self.r(old_parent):
                    self.w(old_parent, 8, successor)
                else:
                    self.w(old_parent + 0x10, 8, successor)
            old_parent = self.r(parent_home)
            old_color = self.r(successor + 0x18, 1)
            self.w(successor + 8, 8, old_parent)
            self.w(successor + 0x18, 1, self.r(original + 0x18, 1))
            self.w(original + 0x18, 1, old_color)
        else:
            child_nil = self.r(child + 0x19, 1)
            parent = self.r(parent_home)
            if not child_nil:
                self.w(child + 8, 8, parent)
            header = self.r(tree)
            if original == self.r(header + 8):
                self.w(header + 8, 8, child)
            elif original == self.r(parent):
                self.w(parent, 8, child)
            else:
                self.w(parent + 0x10, 8, child)
            header = self.r(tree)
            if original == self.r(header):
                if self.r(child + 0x19, 1):
                    smallest = parent
                else:
                    cursor = self.r(child)
                    smallest = child
                    if not self.r(cursor + 0x19, 1):
                        while True:
                            following = self.r(cursor)
                            smallest, cursor = cursor, following
                            if self.r(cursor + 0x19, 1):
                                break
                self.w(header, 8, smallest)
            header = self.r(tree)
            if original == self.r(header + 0x10):
                if self.r(child + 0x19, 1):
                    self.w(header + 0x10, 8, parent)
                else:
                    cursor = self.r(child + 0x10)
                    largest = child
                    if not self.r(cursor + 0x19, 1):
                        while True:
                            largest = cursor
                            cursor = self.r(cursor + 0x10)
                            if self.r(cursor + 0x19, 1):
                                break
                    self.w(header + 0x10, 8, largest)
        if self.r(original + 0x18, 1) == 1:
            self.fix(tree, child, parent)
        size = self.r(tree + 8)
        if size:
            self.w(tree + 8, 8, size - 1)
        return original

    def subtree(self, first: int, middle: int, node: int) -> None:
        if not self.r(node + 0x19, 1):
            while True:
                self.call(_SUBTREE, first, middle, self.r(node + 0x10))
                freed, node = node, self.r(node)
                self.call(_FREE, freed, 0x28)
                if self.r(node + 0x19, 1):
                    break

    def clear(self, tree: int) -> None:
        header = self.r(tree)
        node = self.r(header + 8)
        if not self.r(node + 0x19, 1):
            while True:
                self.call(_SUBTREE, tree, tree, self.r(node + 0x10))
                freed, node = node, self.r(node)
                self.call(_FREE, freed, 0x28)
                if self.r(node + 0x19, 1):
                    break
        self.w(header + 8, 8, header)
        self.w(header, 8, header)
        self.w(header + 0x10, 8, header)
        self.w(tree + 8, 8, 0)


def bind_replay_cycle_tree(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
) -> ReplayTaskRebuildCalls:
    """Bind six complete storage bodies, with mandatory reached sized-free.

    No private semantic homes, FP or atomic state are consumed. Physical saves,
    native faults/EH/concurrency and incidental register state are excluded.
    Earlier pointer/count/color effects survive any actual child refusal.
    """
    _validate(context, calls)

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError("malformed addressed cycle tree call")
        _validate(context, calls, *args)
        body = _Tree(context, bound)
        if target == _EXTRACT:
            return body.extract(*args)
        if target == _LINK:
            return body.link(*args)
        if target == _CLEAR:
            body.clear(args[0])
        elif target == _SUBTREE:
            body.subtree(*args)
        elif target == _LEFT:
            body.left(*args)
        else:
            body.right(*args)
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    return bound
