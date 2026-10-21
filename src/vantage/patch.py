"""Complete decoder for ``cade_api.rpc.Frame.patch`` / ``Frame.reversePatch``.

The game streams its world to a spectator as a sequence of *instructions* over
a typed object tree rooted at ``Root`` (model 0); this module decodes it.

Wire format (all integers little-endian):

* An instruction is one opcode byte followed by operands. ``fid`` is a u8
  field id, ``model`` a u8 model id, ``key``/``index``/``count`` an i32.
* Scalar widths are *not* in the stream; they come from the per-model field
  table in ``cade_schema.json`` (see :mod:`vantage.schema`).
* A *reverse* patch starts with a ``0x00`` marker and is read back-to-front:
  the opcode is the last byte, its operands precede it, and every multi-byte
  value is read ending at the cursor. The game emits these so a recording can be
  stepped backwards without re-simulating.

==  =========================  =========================================
op  name                       operands (forward order)
==  =========================  =========================================
1   POP                        --
2   ASSIGN_FIELD               fid, value
3   PUSH_FIELD                 fid
4   PUSH_CREATE_FIELD          fid, model
5   RESET_FIELD                fid
6   ASSIGN_KEY                 fid, key, value        (scalar arrays)
7   PUSH_KEY                   fid, key
8   PUSH_CREATE_KEY            fid, model, key
9   RESET_KEY                  fid, key
10  INSERT                     fid, index, value      (scalar arrays)
11  PUSH_CREATE_INSERT         fid, model, index
12  REMOVE                     fid, index
13  SWAP                       fid, index, index
14  RESIZE                     fid, count
==  =========================  =========================================

The tree is plain data: :class:`Node` holds ``model`` and a ``fields`` dict
keyed by field id; map fields are ``dict[int, Node]``, array fields are
``list[Node | None]``, scalar-array fields are ``list`` of scalars.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from vantage.schema import SCHEMA, FieldSpec, Schema

POP = 1
ASSIGN_FIELD = 2
PUSH_FIELD = 3
PUSH_CREATE_FIELD = 4
RESET_FIELD = 5
ASSIGN_KEY = 6
PUSH_KEY = 7
PUSH_CREATE_KEY = 8
RESET_KEY = 9
INSERT = 10
PUSH_CREATE_INSERT = 11
REMOVE = 12
SWAP = 13
RESIZE = 14

_OBJ = frozenset({"object"})
_SCALAR = frozenset({"scalar"})
_COLL = frozenset({"map", "array"})
_SEQ = frozenset({"array", "scalar_array"})
#: Field kinds each opcode can legally address.
_OP_KINDS: dict[int, frozenset[str]] = {
    ASSIGN_FIELD: _SCALAR,
    PUSH_FIELD: _OBJ,
    PUSH_CREATE_FIELD: _OBJ,
    RESET_FIELD: _OBJ,
    ASSIGN_KEY: frozenset({"scalar_array"}),
    PUSH_KEY: _COLL,
    PUSH_CREATE_KEY: _COLL,
    RESET_KEY: _COLL,
    INSERT: frozenset({"scalar_array"}),
    PUSH_CREATE_INSERT: frozenset({"array"}),
    REMOVE: _SEQ,
    SWAP: _SEQ,
    RESIZE: _SEQ,
}

#: Maximum nesting the game uses (the reference patcher pre-allocates 10 levels).
MAX_DEPTH = 10


class PatchError(ValueError):
    """The bytes do not describe a valid edit of the current tree."""


@dataclass(slots=True)
class Node:
    """One object in the state tree."""

    model: int
    fields: dict[int, Any] = field(default_factory=dict)
    #: Set whenever a patch descends into this node (an edit below it); consumers
    #: that cache work per node (master statistics) clear it after reading.
    touched: bool = True

    def get(self, fid: int, default: Any = None) -> Any:
        return self.fields.get(fid, default)


_FMT: dict[str, tuple[str, int]] = {
    "Int8": ("<b", 1),
    "UInt8": ("<B", 1),
    "Boolean": ("<B", 1),
    "Int16": ("<h", 2),
    "UInt16": ("<H", 2),
    "Int32": ("<i", 4),
    "UInt32": ("<I", 4),
    "Int64": ("<q", 8),
    "UInt64": ("<Q", 8),
    "Float": ("<f", 4),
    "Double": ("<d", 8),
}


class _Reader:
    """Cursor over a patch, forward or (for reverse patches) backward."""

    __slots__ = ("backward", "buf", "end", "pos")

    def __init__(self, buf: bytes | memoryview, backward: bool) -> None:
        self.buf = memoryview(buf)
        self.backward = backward
        if backward:
            self.pos = len(self.buf)
            self.end = 1  # byte 0 is the reverse marker
        else:
            self.pos = 0
            self.end = len(self.buf)

    @property
    def remaining(self) -> int:
        return self.pos - self.end if self.backward else self.end - self.pos

    def _take(self, n: int) -> int:
        if self.remaining < n:
            raise PatchError("patch ends inside an instruction")
        if self.backward:
            self.pos -= n
            return self.pos
        at = self.pos
        self.pos += n
        return at

    def u8(self) -> int:
        return self.buf[self._take(1)]

    def i32(self) -> int:
        return int(struct.unpack_from("<i", self.buf, self._take(4))[0])

    def value(self, wire: str) -> Any:
        if wire == "String":
            n = (
                int(struct.unpack_from("<I", self.buf, self._take(4))[0])
                if not self.backward
                else self._backward_len()
            )
            at = self._take(n)
            return bytes(self.buf[at : at + n]).decode("utf-8", errors="replace")
        fmt, size = _FMT[wire]
        v = struct.unpack_from(fmt, self.buf, self._take(size))[0]
        return bool(v) if wire == "Boolean" else v

    def _backward_len(self) -> int:
        # Backward strings store the length *after* the bytes, so it is read first.
        return int(struct.unpack_from("<I", self.buf, self._take(4))[0])


_I32 = struct.Struct("<i").unpack_from
_U32 = struct.Struct("<I").unpack_from
#: wire -> (unpack_from, size) for the fast forward reader.
_UNPACK: dict[str, tuple[Any, int]] = {
    w: (struct.Struct(fmt).unpack_from, size) for w, (fmt, size) in _FMT.items()
}


def _read_value(buf: bytes, pos: int, wire: str) -> tuple[Any, int]:
    """A forward scalar at ``pos``: (value, position after it)."""
    if wire == "String":
        n = _U32(buf, pos)[0]
        pos += 4
        end = pos + n
        if end > len(buf):
            raise PatchError("patch ends inside an instruction")
        return buf[pos:end].decode("utf-8", errors="replace"), end
    unpack, size = _UNPACK[wire]
    v = unpack(buf, pos)[0]
    return (bool(v) if wire == "Boolean" else v), pos + size


def _default_scalar(wire: str) -> Any:
    if wire == "String":
        return ""
    if wire == "Boolean":
        return False
    return 0.0 if wire in ("Float", "Double") else 0


class Patcher:
    """Applies patches to a tree, keeping it as the authoritative world state.

    ``lenient`` exists for analysing *delta-only* captures (no initial
    snapshot): edits that reach into objects the tree does not hold yet create
    placeholders instead of failing, and a placeholder whose concrete model is
    unknown is narrowed to the most specific model that declares the field
    being edited. Never use it for a live view -- a strict failure there means
    the stream is out of sync and must be resynchronised from a snapshot.
    """

    def __init__(self, schema: Schema = SCHEMA, lenient: bool = False) -> None:
        self.schema = schema
        self.lenient = lenient
        self.root = Node(0)
        self.ops = 0
        #: Lenient placeholders -> the declared model they were created as.
        self._guessed: dict[int, int] = {}

    # -- public -------------------------------------------------------------

    def apply(self, patch: bytes | memoryview) -> None:
        """Apply one ``Frame.patch`` (forward) or ``Frame.reversePatch``."""
        if len(patch) == 0:
            return
        backward = patch[0] == 0
        if not backward and not self.lenient:
            self._apply_forward(bytes(patch))
            return
        r = _Reader(patch, backward)
        self._run(r, self.root, 0)
        if r.remaining:
            raise PatchError(f"{r.remaining} trailing bytes after root POP")

    # -- fast forward interpreter -------------------------------------------
    # The live stream and every recording load go through here: one loop with
    # the read position in a local and an explicit stack instead of a reader
    # object and recursion (method calls per byte made decoding the main cost
    # of fast replay). Same semantics as ``_run`` for strict forward patches.

    def _apply_forward(self, buf: bytes) -> None:
        fields_of = self.schema._fields
        empty: dict[int, FieldSpec] = {}
        n = len(buf)
        pos = 0
        ops = 0
        stack: list[Node] = []
        node = self.root
        f = node.fields
        specs = fields_of.get(node.model, empty)
        i32 = _I32
        unpack_of = _UNPACK
        try:
            while pos < n:
                op = buf[pos]
                pos += 1
                ops += 1
                if op == POP:
                    if not stack:
                        raise PatchError("POP at root")
                    node = stack.pop()
                    f = node.fields
                    specs = fields_of.get(node.model, empty)
                    continue
                if not ASSIGN_FIELD <= op <= RESIZE:
                    raise PatchError(f"unknown opcode {op}")
                fid = buf[pos]
                pos += 1
                spec = specs.get(fid)
                if spec is None:
                    raise PatchError(f"model {self.schema.name(node.model)} has no field {fid}")
                child: Any = None
                if op == ASSIGN_FIELD:
                    wire = spec.wire
                    if wire == "String":
                        f[fid], pos = _read_value(buf, pos, wire)
                    else:
                        unpack, size = unpack_of[wire]
                        v = unpack(buf, pos)[0]
                        pos += size
                        f[fid] = bool(v) if wire == "Boolean" else v
                    continue
                if op == PUSH_FIELD:
                    child = f.get(fid)
                    if not isinstance(child, Node):
                        child = self._placeholder(spec)
                        f[fid] = child
                elif op == PUSH_CREATE_FIELD:
                    child = Node(buf[pos])
                    pos += 1
                    f[fid] = child
                elif op == RESET_FIELD:
                    f[fid] = None
                    continue
                elif op == ASSIGN_KEY:
                    key = i32(buf, pos)[0]
                    seq = self._seq(f, fid)
                    val, pos = _read_value(buf, pos + 4, spec.wire)
                    self._check(seq, key, insert=False, fill=None)
                    seq[key] = val
                    continue
                elif op == PUSH_KEY:
                    key = i32(buf, pos)[0]
                    pos += 4
                    coll = f.get(fid)
                    if type(coll) is dict:
                        child = coll.get(key)
                    elif type(coll) is list and 0 <= key < len(coll):
                        child = coll[key]
                    if type(child) is not Node:
                        child = self._get_key(f, fid, spec, key)  # error/creation paths
                elif op == PUSH_CREATE_KEY:
                    model = buf[pos]
                    key = i32(buf, pos + 1)[0]
                    pos += 5
                    child = Node(model)
                    if spec.kind == "map":
                        self._map(f, fid)[key] = child
                    else:
                        seq = self._seq(f, fid)
                        self._check(seq, key, insert=False, fill=None)
                        seq[key] = child
                elif op == RESET_KEY:
                    key = i32(buf, pos)[0]
                    pos += 4
                    if spec.kind == "map":
                        if self._map(f, fid).pop(key, None) is None:
                            raise PatchError(f"{spec.name}[{key}] reset but absent")
                    else:
                        seq = self._seq(f, fid)
                        self._check(seq, key, insert=False, fill=None)
                        seq[key] = None
                    continue
                elif op == INSERT:
                    idx = i32(buf, pos)[0]
                    val, pos = _read_value(buf, pos + 4, spec.wire)
                    seq = self._seq(f, fid)
                    self._check(seq, idx, insert=True, fill=None)
                    seq.insert(idx, val)
                    continue
                elif op == PUSH_CREATE_INSERT:
                    model = buf[pos]
                    idx = i32(buf, pos + 1)[0]
                    pos += 5
                    seq = self._seq(f, fid)
                    self._check(seq, idx, insert=True, fill=None)
                    child = Node(model)
                    seq.insert(idx, child)
                elif op == REMOVE:
                    idx = i32(buf, pos)[0]
                    pos += 4
                    seq = self._seq(f, fid)
                    self._check(seq, idx, insert=False, fill=None)
                    del seq[idx]
                    continue
                elif op == SWAP:
                    a = i32(buf, pos)[0]
                    b = i32(buf, pos + 4)[0]
                    pos += 8
                    seq = self._seq(f, fid)
                    self._check(seq, max(a, b), insert=False, fill=None)
                    seq[a], seq[b] = seq[b], seq[a]
                    continue
                else:  # RESIZE
                    count = i32(buf, pos)[0]
                    pos += 4
                    if count < 0:
                        raise PatchError("negative resize")
                    seq = self._seq(f, fid)
                    if len(seq) > count:
                        del seq[count:]
                    else:
                        seq.extend(self._fill(spec) for _ in range(count - len(seq)))
                    continue
                # A PUSH: descend into the child.
                if len(stack) >= MAX_DEPTH:
                    raise PatchError("nesting deeper than the format allows")
                stack.append(node)
                node = child
                node.touched = True
                f = node.fields
                specs = fields_of.get(node.model, empty)
        except (IndexError, struct.error) as e:
            raise PatchError("patch ends inside an instruction") from e
        finally:
            self.ops += ops
        if pos > n:
            raise PatchError("patch ends inside an instruction")
        if stack:
            raise PatchError("patch ended without closing every PUSH")

    # -- interpreter --------------------------------------------------------

    def _spec(self, node: Node, fid: int, op: int) -> FieldSpec:
        spec = self.schema.field(node.model, fid)
        if spec is not None and (not self.lenient or spec.kind in _OP_KINDS[op]):
            return spec
        if self.lenient:
            base = self._guessed.get(id(node), node.model)
            narrowed = self.schema.narrow(base, fid, _OP_KINDS[op], seen=node.fields.keys())
            if narrowed is not None:
                node.model = narrowed
                spec = self.schema.field(narrowed, fid)
                if spec is not None:
                    return spec
        raise PatchError(f"model {self.schema.name(node.model)} has no field {fid}")

    def _placeholder(self, spec: FieldSpec) -> Node:
        if not self.lenient or spec.model is None:
            raise PatchError(f"edit reaches missing object at {spec.name}")
        node = Node(spec.model)
        self._guessed[id(node)] = spec.model
        return node

    def _run(self, r: _Reader, node: Node, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise PatchError("nesting deeper than the format allows")
        node.touched = True
        f = node.fields
        while r.remaining > 0:
            op = r.u8()
            self.ops += 1
            if op == POP:
                if depth == 0:
                    raise PatchError("POP at root")
                return
            if not ASSIGN_FIELD <= op <= RESIZE:
                raise PatchError(f"unknown opcode {op}")
            fid = r.u8()
            spec = self._spec(node, fid, op)
            if op == ASSIGN_FIELD:
                f[fid] = r.value(spec.wire)
            elif op == PUSH_FIELD:
                child = f.get(fid)
                if not isinstance(child, Node):
                    child = self._placeholder(spec)
                    f[fid] = child
                self._run(r, child, depth + 1)
            elif op == PUSH_CREATE_FIELD:
                child = Node(r.u8())
                f[fid] = child
                self._run(r, child, depth + 1)
            elif op == RESET_FIELD:
                f[fid] = None
            elif op == ASSIGN_KEY:
                key = r.i32()
                seq = self._seq(f, fid)
                val = r.value(spec.wire)
                self._check(seq, key, insert=False, fill=_default_scalar(spec.wire))
                seq[key] = val
            elif op == PUSH_KEY:
                key = r.i32()
                child = self._get_key(f, fid, spec, key)
                self._run(r, child, depth + 1)
            elif op == PUSH_CREATE_KEY:
                model = r.u8()
                key = r.i32()
                child = Node(model)
                if spec.kind == "map":
                    self._map(f, fid)[key] = child
                else:
                    seq = self._seq(f, fid)
                    self._check(seq, key, insert=False, fill=None)
                    seq[key] = child
                self._run(r, child, depth + 1)
            elif op == RESET_KEY:
                key = r.i32()
                if spec.kind == "map":
                    m = self._map(f, fid)
                    if m.pop(key, None) is None and not self.lenient:
                        raise PatchError(f"{spec.name}[{key}] reset but absent")
                else:
                    seq = self._seq(f, fid)
                    self._check(seq, key, insert=False, fill=None)
                    seq[key] = None
            elif op == INSERT:
                idx = r.i32()
                val = r.value(spec.wire)
                seq = self._seq(f, fid)
                self._check(seq, idx, insert=True, fill=_default_scalar(spec.wire))
                seq.insert(idx, val)
            elif op == PUSH_CREATE_INSERT:
                model = r.u8()
                idx = r.i32()
                seq = self._seq(f, fid)
                self._check(seq, idx, insert=True, fill=None)
                child = Node(model)
                seq.insert(idx, child)
                self._run(r, child, depth + 1)
            elif op == REMOVE:
                idx = r.i32()
                seq = self._seq(f, fid)
                self._check(seq, idx, insert=False, fill=None)
                del seq[idx]
            elif op == SWAP:
                a = r.i32()
                b = r.i32()
                seq = self._seq(f, fid)
                self._check(seq, max(a, b), insert=False, fill=None)
                seq[a], seq[b] = seq[b], seq[a]
            elif op == RESIZE:
                n = r.i32()
                if n < 0:
                    raise PatchError("negative resize")
                seq = self._seq(f, fid)
                if len(seq) > n:
                    del seq[n:]
                else:
                    seq.extend(self._fill(spec) for _ in range(n - len(seq)))
            else:
                raise PatchError(f"unknown opcode {op}")
        if depth > 0:
            raise PatchError("patch ended without closing every PUSH")

    def _fill(self, spec: FieldSpec) -> Any:
        if spec.kind == "scalar_array":
            return _default_scalar(spec.wire)
        if spec.contiguous_model is not None:
            return Node(spec.contiguous_model)
        return None

    @staticmethod
    def _seq(f: dict[int, Any], fid: int) -> list[Any]:
        seq = f.get(fid)
        if not isinstance(seq, list):
            seq = []
            f[fid] = seq
        return seq

    @staticmethod
    def _map(f: dict[int, Any], fid: int) -> dict[int, Node]:
        m = f.get(fid)
        if not isinstance(m, dict):
            m = {}
            f[fid] = m
        return m

    def _check(self, seq: list[Any], idx: int, *, insert: bool, fill: Any) -> None:
        limit = len(seq) if insert else len(seq) - 1
        if 0 <= idx <= limit:
            return
        if self.lenient and idx >= 0:
            seq.extend([fill] * (idx - limit))
            return
        raise PatchError(f"index {idx} out of range for length {len(seq)}")

    def _get_key(self, f: dict[int, Any], fid: int, spec: FieldSpec, key: int) -> Node:
        if spec.kind == "map":
            m = self._map(f, fid)
            child = m.get(key)
            if child is None:
                child = self._placeholder(spec)
                m[key] = child
            return child
        seq = self._seq(f, fid)
        self._check(seq, key, insert=False, fill=None)
        item = seq[key]
        if not isinstance(item, Node):
            item = self._placeholder(spec)
            seq[key] = item
        return item
