"""Build54800 health-triggered transform handler1412b7f00 over current storage.

Implements dynamic48-byte rule iteration, resource/health gates, the concrete
14172acb0 table-presence predicate and ordered reached callback dispatch.
Callbacks implement the actual helpers/current virtuals; no successful transform
or callback effects are synthesized. Reads use caller-bound scalar addresses,
not a live process or saved defaults. FPstatus/traps/upper lanes are excluded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .replay_binary32 import add_binary32, compare_binary32, multiply_binary32, signed16_binary32

_QWORD = (1 << 64) - 1
_MASTER_ADD = 0x6A586EB28AC201FC + 0x0CF19788B2554E70
_BASE_XOR = 0xD978539418047C54 ^ 0xABAA7F7397F61E6C


class UnresolvedReplayHealthTransform(ValueError):
    """A reached helper/current virtual implementation is unavailable."""


def _unsigned(value: int, width: int, name: str) -> None:
    if type(value) is not int or not 0 <= value < 1 << (width * 8):
        raise ValueError(f"{name} must be a raw unsigned{width * 8} word")


def _signed(value: int, width: int) -> int:
    sign = 1 << (width * 8 - 1)
    return value - (sign << 1) if value & sign else value


@dataclass(frozen=True, slots=True)
class ReplayHealthTransformStorage:
    """Subject token and coherent readable scalar backing for native addresses.

    read(address,width) returns the exact unsigned scalar. Addresses are raw
    u64 tokens; pointer arithmetic wraps as native64-bit arithmetic. Subject,
    owner, current master, vectors, tables and global144297830 must have actual
    current bindings whenever reached. A successful scalar read does not prove
    backing for another read. The subject's current native target and readable,
    properly backed vector storage are caller premises; none is inferred here.

    Callbacks can mutate these bindings. Every subsequent read follows native
    order, including cached iteration-begin versus refreshed rule phases.
    Concurrent/incoherent storage and native fault equivalence are excluded.
    """

    subject: int
    read: Callable[[int, int], int]

    def __post_init__(self) -> None:
        _unsigned(self.subject, 8, "subject token")
        if not self.subject or not callable(self.read):
            raise ValueError("nonnull subject token and actual scalar reader required")


@dataclass(frozen=True, slots=True)
class ReplayHealthTransformCallbacks:
    """Actual helper and current-subject virtual bindings, required if reached.

    special_index is140a81440(signed16 index)->raw EAX; special_owner_flag is
    1416f7940(captured owner,EAX)->raw AL. announce is140b42480(global,oldID,newID).
    transform dispatches current virtual98(targetMaster,True); payload dispatches
    current virtual508(rawType,payloadAddress); post_transform dispatches current
    virtual960(raw currentMaster228). Bind virtual dispatch at invocation time.
    The payload is an address, not a copied or decoded snapshot.

    None explicitly marks unavailable work and raises at its reached call,
    after preceding reads/callback effects. Callback exceptions and mutations
    propagate without rollback. No return from a void callback proves success.
    """

    special_index: Callable[[int], int] | None
    special_owner_flag: Callable[[int, int], int] | None
    announce: Callable[[int, int, int], None] | None
    transform: Callable[[int, bool], None] | None
    payload: Callable[[int, int], None] | None
    post_transform: Callable[[int], None] | None

    def __post_init__(self) -> None:
        if any(
            value is not None and not callable(value)
            for value in (
                self.special_index,
                self.special_owner_flag,
                self.announce,
                self.transform,
                self.payload,
                self.post_transform,
            )
        ):
            raise ValueError("health transform callbacks must be callable or unavailable")


def _read(context: ReplayHealthTransformStorage, address: int, width: int) -> int:
    value = context.read(address & _QWORD, width)
    _unsigned(value, width, "current health-transform read")
    return value


def _subject(context: ReplayHealthTransformStorage, offset: int, width: int) -> int:
    return _read(context, context.subject + offset, width)


def _master(context: ReplayHealthTransformStorage) -> int:
    return (_subject(context, 0x10, 8) - _MASTER_ADD) & _QWORD


def _resource(context: ReplayHealthTransformStorage, index: int) -> int:
    owner = _subject(context, 0x18, 8)
    table = _read(context, owner + 0x98, 8)
    raw = _read(context, table + index * 8, 8)
    decoded = (
        ((raw ^ 0x6AE24D3352F04511 ^ 0xC22D6B496D833977) - 0x042AC42976FCCEF5) & _QWORD
    ) ^ 0xA9834B738A7DD167
    return decoded & 0xFFFFFFFF


def _hp(context: ReplayHealthTransformStorage) -> int:
    raw = _subject(context, 0x130, 8)
    return ((raw ^ 0x0F2A55F7A61DD00E) - 0x147B5E081EC087D9) & 0xFFFFFFFF


def _saved_id(context: ReplayHealthTransformStorage, master: int) -> int:
    raw = _read(context, master + 0x18, 8)
    decoded = ((raw ^ 0x349E37847AD69F19) - 0x47E37DFF0616CE4F) & 0xFFFF
    return _signed(decoded, 2)


def _available(context: ReplayHealthTransformStorage, owner: int, index: int) -> bool:
    # 14172acb0: signed bounds and a nonnull slot, not a tech-enabled predicate.
    if index < 0:
        return False
    count = _signed(_read(context, owner + 0x20, 4), 4)
    if index >= count:
        return False
    table = _read(context, owner + 0x28, 8)
    return _read(context, table + index * 8, 8) != 0


def _count(begin: int, end: int) -> int:
    difference = _signed((end - begin) & _QWORD, 8)
    quotient = abs(difference) // 48
    return (-quotient if difference < 0 else quotient) & _QWORD


def _visit(
    context: ReplayHealthTransformStorage,
    callbacks: ReplayHealthTransformCallbacks,
    cached_begin: int,
    offset: int,
) -> bool:
    gate_index = _signed(_read(context, cached_begin + offset + 8, 2), 2)
    if gate_index != -1 and compare_binary32(0, _resource(context, gate_index)) in (0, 1):
        return False
    begin = _subject(context, 0x7A8, 8)
    extra_index = _signed(_read(context, begin + offset + 0xA, 2), 2)
    threshold = _read(context, begin + offset + 4, 4)
    if extra_index != -1:
        threshold = add_binary32(threshold, _resource(context, extra_index))
    begin = _subject(context, 0x7A8, 8)
    if _read(context, begin + offset + 0xC, 1):
        base = _read(context, _master(context) + 0x68, 8) ^ _BASE_XOR
        threshold = multiply_binary32(threshold, signed16_binary32(_signed(base & 0xFFFF, 2)))
    begin = _subject(context, 0x7A8, 8)
    captured_owner = _subject(context, 0x18, 8)
    special_index = _signed(_read(context, begin + offset + 0xA, 2), 2)
    if special_index < -1:
        if callbacks.special_index is None:
            raise UnresolvedReplayHealthTransform("reached140a81440 is unavailable")
        translated = callbacks.special_index(special_index)
        _unsigned(translated, 4, "special index return EAX")
        if callbacks.special_owner_flag is None:
            raise UnresolvedReplayHealthTransform("reached1416f7940 is unavailable")
        flag = callbacks.special_owner_flag(captured_owner, translated)
        _unsigned(flag, 1, "special owner flag return AL")
        if flag:
            return False
    order = compare_binary32(threshold, 0)
    if order == 1:
        if compare_binary32(_hp(context), threshold) != 1:
            return False
    elif order == -1:
        if compare_binary32(threshold & 0x7FFFFFFF, _hp(context)) != 1:
            return False
    else:
        return False
    begin = _subject(context, 0x7A8, 8)
    owner = _subject(context, 0x18, 8)
    index = _signed(_read(context, begin + offset, 4), 4)
    if not _available(context, owner, index):
        return False
    begin = _subject(context, 0x7A8, 8)
    index = _signed(_read(context, begin + offset, 4), 4)
    owner = _subject(context, 0x18, 8)
    table = _read(context, owner + 0x28, 8)
    target = _read(context, table + index * 8, 8)
    notification = _read(context, 0x144297830, 8)
    if notification:
        new_id = _saved_id(context, target)
        old_id = _saved_id(context, _master(context))
        if callbacks.announce is None:
            raise UnresolvedReplayHealthTransform("reached140b42480 is unavailable")
        callbacks.announce(notification, old_id, new_id)
    if callbacks.transform is None:
        raise UnresolvedReplayHealthTransform("reached current virtual98 is unavailable")
    callbacks.transform(target, True)
    begin = _subject(context, 0x7A8, 8)
    payload_type = _read(context, begin + offset + 0x10, 4)
    if callbacks.payload is None:
        raise UnresolvedReplayHealthTransform("reached current virtual508 is unavailable")
    callbacks.payload(payload_type, (begin + offset + 0x18) & _QWORD)
    post_value = _read(context, _master(context) + 0x228, 8)
    if callbacks.post_transform is None:
        raise UnresolvedReplayHealthTransform("reached current virtual960 is unavailable")
    callbacks.post_transform(post_value)
    return True


def run_replay_health_transforms(
    context: ReplayHealthTransformStorage,
    *,
    mxcsr: int,
    callbacks: ReplayHealthTransformCallbacks,
) -> None:
    """Run1412b7f00 with dynamic rules; return after the first selected sequence.

    Rule+8 gates on owner resources (unordered passes). Rule+a optionally adds
    a resource BEFORE special negative-index helper calls; any nonzero+c scales
    the threshold by signed16 master HP. Only strict ordered health/threshold
    comparisons can select a rule. The row's target is a signed table index.

    Begin/end and counts are reread after skipped rules, including callback
    mutations. The source's cached begin for the first+8 read differs from
    refreshed begin reads in later phases. Empty vector returns before owner,
    master, resource, global or callback reads. Native well-formed backing is a
    premise; no iteration clamp or guessed initialization is substituted.
    """
    if not isinstance(context, ReplayHealthTransformStorage):
        raise ValueError("explicit current health-transform storage required")
    if not isinstance(callbacks, ReplayHealthTransformCallbacks):
        raise ValueError("explicit current health-transform callback bindings required")
    _unsigned(mxcsr, 4, "MXCSR")
    if mxcsr & ~0x3F != 0x1F80:
        raise ValueError("masked nearest-even MXCSR, DAZ/FTZoff required")
    begin = _subject(context, 0x7A8, 8)
    end = _subject(context, 0x7B0, 8)
    if not _count(begin, end):
        return
    index, offset = 0, 0
    while True:
        if _visit(context, callbacks, begin, offset):
            return
        begin = _subject(context, 0x7A8, 8)
        end = _subject(context, 0x7B0, 8)
        index = (index + 1) & _QWORD
        offset = (offset + 48) & _QWORD
        if index >= _count(begin, end):
            return
