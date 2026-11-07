"""Complete build54800 Building area, production reset and production apply.

Source/API: building-update-services-source-v1 production packet,4089B/952 rows.
Known GP entries use explicit owned storage, raw FP annotations and required
effects. Physical stack/saves/cookie, FP status/upper lanes and concurrency are
excluded. This does not restore a recording World or commit a complete tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    multiply_binary32,
    signed16_binary32,
    subtract_binary32,
)
from .replay_manager_queues import _Frame
from .replay_task_group_storage import LocalBinding
from .replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
    _cvtt,
    _read,
    _signed,
    _unsigned,
    _write,
)
from .replay_unit_ai_base import _validate

_AREA, _RESET, _APPLY = 0x14127CC00, 0x141288160, 0x1412A2C70
_TOP, _CLEAR, _QUERY, _POP = 0x140B88AF0, 0x140B88A20, 0x140B899F0, 0x140B893D0
_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_MA, _MB = 0x6A586EB28AC201FC, 0x0CF19788B2554E70
_RA, _RB, _RC, _RD = (
    0x6AE24D3352F04511,
    0xC22D6B496D833977,
    0x042AC42976FCCEF5,
    0xA9834B738A7DD167,
)
_XA, _XB = 0x183CAC30D2441D0E, 0x4C3FBA69E4EA7FD1
_YA, _YB = 0x61501AA6ECFD980A, 0x6C5EAB60B426DD28


@dataclass(frozen=True, slots=True)
class ReplayBuildingProductionProfile:
    """Explicit D0/88/70h semantic prefixes, with unwritten bytes supplied.

    Area uses20/28/30/B0/B8/C0/C8; reset20/28/30/80; apply20/28/30/40/48/
    50/58/60/64/68. Native saves and apply cookie70 are excluded. Partial
    stores and every reached current read retain their original widths.
    """

    area: bytes
    reset: bytes
    apply: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or len(value) != size
            for value, size in ((self.area, 0xD0), (self.reset, 0x88), (self.apply, 0x70))
        ):
            raise ValueError("explicitD0/88/70h-byte Building production seeds required")


def _raw(value: int | None, label: str, width: int = 8) -> int:
    if value is None:
        raise ValueError(f"{label} requires actual raw annotation")
    _unsigned(value, width, label)
    return value


class _Production:
    def __init__(
        self,
        context: ReplayTaskRebuildStorage,
        calls: ReplayTaskRebuildCalls,
        channels: tuple[ReplayTaskRebuildCalls, ...],
        bind_local: LocalBinding,
        profile: ReplayBuildingProductionProfile,
    ) -> None:
        self.context, self.calls = context, calls
        (
            self.area_calls,
            self.scalar,
            self.resource_calls,
            self.messages,
            self.selection,
            self.constructors,
        ) = channels
        self.bind_local, self.profile = bind_local, profile

    def r(self, at: int, width: int = 8) -> int:
        return _read(self.context, at, width)

    def w(self, at: int, width: int, value: int) -> None:
        _write(self.context, at, width, value)

    def invoke(self, calls: ReplayTaskRebuildCalls, target: int, *args: int) -> int | None:
        if calls.call is None:
            raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
        return calls.call(target, tuple(value & _U64 for value in args), None)

    def call(self, target: int, *args: int) -> int | None:
        return self.invoke(self.calls, target, *args)

    def pointer(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} RAX")

    def eax(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} EAX") & _U32

    def al(self, target: int, *args: int) -> int:
        return _raw(self.call(target, *args), f"{target:x} AL") & 255

    def finish_master(self, f: _Frame, at: int) -> int:
        f.w(at, 8, f.r(at, 8) - _MA)
        f.w(at, 8, f.r(at, 8) - _MB)
        return f.r(at, 8)

    def master(self, f: _Frame, at: int, obj: int) -> int:
        f.w(at, 8, self.r(obj + 0x10))
        return self.finish_master(f, at)

    def resource(self, f: _Frame, at: int, encoded: int) -> int:
        f.w(at, 8, encoded)
        f.w(at, 8, f.r(at, 8) ^ _RA)
        f.w(at, 8, f.r(at, 8) ^ _RB)
        f.w(at, 8, f.r(at, 8) - _RC)
        f.w(at, 8, f.r(at, 8) ^ _RD)
        return f.r(at, 8)

    def current_resource(self, f: _Frame, obj: int, offset: int, stage: int) -> None:
        resources = self.r(self.r(obj + 0x18) + 0x98)
        f.w(stage, 8, self.resource(f, 0x40, self.r(resources + offset)))

    def area(self, obj: int) -> None:
        with _Frame(self.context, self.bind_local, self.profile.area) as f:
            resources = self.r(self.r(obj + 0x18) + 0x98)
            f.w(0xB8, 8, self.resource(f, 0xB0, self.r(resources + 0x7F8)))
            encoded = self.r(obj + 0x10)
            wanted = f.r(0xB8, 4)
            f.w(0xB0, 8, encoded)
            master = self.finish_master(f, 0xB0)
            f.w(0xB0, 8, self.r(master + 0x18))
            f.w(0xB0, 8, f.r(0xB0, 8) ^ 0x349E37847AD69F19)
            f.w(0xB0, 8, f.r(0xB0, 8) - 0x47E37DFF0616CE4F)
            kind = _signed(f.r(0xB0, 8) & 0xFFFF, 2)
            if compare_binary32(wanted, signed16_binary32(kind)) != 0:
                return
            for offset, stage in ((0x800, 0xB8), (0x808, 0xC8), (0x828, 0x30), (0x810, 0xB0)):
                resources = self.r(self.r(obj + 0x18) + 0x98)
                f.w(stage, 8, self.resource(f, 0xB0, self.r(resources + offset)))

            encoded = self.r(obj + 0x170)
            selector = _cvtt(f.r(0xB0, 4))
            f.w(0xB0, 8, encoded)
            f.w(0xB0, 8, f.r(0xB0, 8) - _XA)
            held = f.r(0xB0, 8) + _XB
            radius = f.r(0xB8, 4)
            f.w(0xB0, 8, held)
            f.w(0xC0, 8, f.r(0xB0, 8))
            f.w(0xB0, 8, self.r(obj + 0x10))
            held = f.r(0xB0, 8) - _MA
            x = f.r(0xC0, 4)
            f.w(0xB0, 8, held)
            f.w(0xB0, 8, f.r(0xB0, 8) - _MB)
            master = f.r(0xB0, 8)
            extent = add_binary32(radius, self.r(master + 0x78, 4))
            f.w(0xB0, 8, self.r(obj + 0x178))
            f.w(0xB0, 8, f.r(0xB0, 8) - _YA)
            left = subtract_binary32(x, extent)
            f.w(0xB0, 8, f.r(0xB0, 8) + _YB)
            f.w(0xB8, 8, f.r(0xB0, 8))
            master = self.master(f, 0xB0, obj)
            min_x = _cvtt(left)
            extent = add_binary32(radius, self.r(master + 0x7C, 4))
            encoded = self.r(obj + 0x170)
            y = f.r(0xB8, 4)
            f.w(0xB0, 8, encoded)
            held = f.r(0xB0, 8) - _XA
            lower = subtract_binary32(y, extent)
            f.w(0xB0, 8, held)
            f.w(0xB0, 8, f.r(0xB0, 8) + _XB)
            f.w(0xB8, 8, f.r(0xB0, 8))
            master = self.master(f, 0xB0, obj)
            min_y = _cvtt(lower)
            right = add_binary32(radius, self.r(master + 0x78, 4))
            f.w(0xB0, 8, self.r(obj + 0x178))
            held = f.r(0xB0, 8) - _YA
            right = add_binary32(right, f.r(0xB8, 4))
            f.w(0xB0, 8, held)
            f.w(0xB0, 8, f.r(0xB0, 8) + _YB)
            right = subtract_binary32(right, self.r(0x1431FF7BC, 4))
            f.w(0xB8, 8, f.r(0xB0, 8))
            max_x = _cvtt(right)
            master = self.master(f, 0xB0, obj)
            owner = self.r(obj + 0x18)
            upper = add_binary32(radius, self.r(master + 0x7C, 4))
            terrain = self.r(self.r(owner + 8) + 0x98)
            upper = add_binary32(upper, f.r(0xB8, 4))
            width, height = self.r(terrain + 0x30, 4), self.r(terrain + 0x34, 4)
            upper = subtract_binary32(upper, self.r(0x1431FF7BC, 4))
            f.w(0xB0, 4, min_x if _signed(min_x, 4) >= 0 else 0)
            resources = self.r(owner + 0x98)
            max_x = max_x if _signed(max_x, 4) < _signed(width, 4) else (width - 1) & _U32
            max_y = _cvtt(upper)
            max_y = max_y if _signed(max_y, 4) < _signed(height, 4) else (height - 1) & _U32
            f.w(0xC0, 8, self.r(resources + 0x818))
            f.w(0xC0, 8, f.r(0xC0, 8) ^ _RA)
            held = f.r(0xC0, 8) ^ _RB
            f.w(0xB8, 4, max_y)
            f.w(0xC0, 8, held)
            f.w(0xC0, 8, f.r(0xC0, 8) - _RC)
            f.w(0xC0, 8, f.r(0xC0, 8) ^ _RD)
            f.w(0xC0, 8, f.r(0xC0, 8))
            owner = self.r(obj + 0x18)
            first_id = _cvtt(f.r(0xC0, 4))
            resources = self.r(owner + 0x98)
            second_raw = self.resource(f, 0xC0, self.r(resources + 0x820))
            y_index = min_y if _signed(min_y, 4) >= 0 else 0
            f.w(0xC0, 8, second_raw)
            second_id = _cvtt(f.r(0xC0, 4))
            if _signed(y_index, 4) > _signed(max_y, 4):
                return
            start_x = f.r(0xB0, 4)
            first_amount, second_amount = f.r(0xC8, 4), f.r(0x30, 4)
            while True:
                x_index = start_x
                if _signed(x_index, 4) <= _signed(max_x, 4):
                    while True:
                        for resource_id, amount in (
                            (first_id, first_amount),
                            (second_id, second_amount),
                        ):
                            f.w(0x28, 4, y_index)
                            f.w(0x20, 4, x_index)
                            self.invoke(
                                self.area_calls,
                                0x14127DC70,
                                obj,
                                resource_id,
                                selector,
                                amount,
                                f.h(0x20),
                                f.h(0x28),
                            )
                        x_index = (x_index + 1) & _U32
                        if _signed(x_index, 4) > _signed(max_x, 4):
                            break
                    max_y = f.r(0xB8, 4)
                    start_x = f.r(0xB0, 4)
                y_index = (y_index + 1) & _U32
                if _signed(y_index, 4) > _signed(max_y, 4):
                    break

    def scalar_amount(self, owner: int, item: int) -> int | None:
        return self.invoke(self.scalar, 0x1417102A0, owner, item & _U32, 1, 255)

    def credit(self, f: _Frame, target: int, owner: int, amount: int) -> None:
        self.invoke(self.resource_calls, target, owner, 80, amount, 0, _U64, f.h(0x20))

    def apply_message(self, f: _Frame, obj: int, message: int, notice: int) -> None:
        owner = self.r(obj + 0x18)
        f.w(0x28, 4, 0)
        f.w(0x20, 4, 0)
        identifier = self.r(owner + 0x648, 4)
        game = self.r(0x144353698)
        self.invoke(
            self.messages,
            0x140D6C3D0,
            game,
            message,
            identifier,
            notice & _U32,
            f.h(0x20),
            f.h(0x28),
        )

    def reset(self, obj: int) -> None:
        with _Frame(self.context, self.bind_local, self.profile.reset) as f:
            if _signed(self.r(obj + 0x8A2, 2), 2) > 0:
                sign_mask = self.r(0x1431D37E0, 4)
                index, offset = 0, 0
                while True:
                    rows = self.r(obj + 0x898)
                    quantity = self.r(rows + offset + 2, 2)
                    association = self.r(rows + offset + 4, 2)
                    item = _signed(self.r(rows + offset, 2), 2) & _U32
                    f.w(0x80, 2, quantity)
                    if association == 0xFFFF:
                        if _signed(quantity, 2) > 0:
                            remaining = quantity
                            while remaining:
                                current_rows = self.r(obj + 0x898)
                                owner = self.r(obj + 0x18)
                                record = current_rows + 8 + _signed(index, 4) * 48
                                self.call(0x141702A00, owner, record, item)
                                catalog = self.r(self.r(obj + 0x18) + 0x18)
                                self.call(0x14111B550, catalog, _U32)
                                owner = self.r(obj + 0x18)
                                catalog = self.r(owner + 0x18)
                                returned = self.call(0x141729140, owner, f.h(0x30), item)
                                unit = self.r(_raw(returned, "catalog item RAX") + 4, 4)
                                self.call(0x14111ADE0, catalog, item, unit)
                                remaining -= 1
                            quantity = f.r(0x80, 2)
                        owner = self.r(obj + 0x18)
                        target = self.r(self.r(owner) + 0xF8)
                        amount = _raw(self.scalar_amount(owner, item), "reset scalar XMM0", 4)
                        amount ^= sign_mask
                        f.w(0x20, 1, 1)
                        amount = multiply_binary32(amount, signed16_binary32(_signed(quantity, 2)))
                        self.credit(f, target, owner, amount)
                        catalog = self.r(self.r(obj + 0x18) + 0x18)
                        self.call(0x14111B550, catalog, (-quantity) & 0xFFFF)
                    else:
                        manager = self.r(self.r(obj + 0x18) + 0x6D0)
                        if manager:
                            record = rows + 8 + _signed(index, 4) * 48
                            self.call(
                                0x1414987A0,
                                manager,
                                record,
                                _signed(association, 2) & _U32,
                                quantity,
                            )
                            current = self.r(obj + 0x898)
                            self.call(0x14127FF00, obj, self.r(current + offset + 4, 2))
                            current = self.r(obj + 0x898)
                            self.call(0x14127E490, obj, self.r(current + offset + 4, 2))
                            current = self.r(obj + 0x898)
                            associated = _signed(self.r(current + offset + 4, 2), 2)
                            manager = self.r(self.r(obj + 0x18) + 0x6D0)
                            at = self.r(manager) + associated * 0x98 + 0x70
                            self.w(at, 2, self.r(at, 2) - quantity)
                    index, offset = (index + 1) & _U32, (offset + 48) & _U64
                    if _signed(index, 4) >= _signed(self.r(obj + 0x8A2, 2), 2):
                        break
            notice = self.r(obj + 0x8B2, 2)
            if notice != 0xFFFF:
                owner = self.r(obj + 0x18)
                game = self.r(0x144353698)
                f.w(0x28, 4, 0)
                f.w(0x20, 4, 0)
                identifier = self.r(owner + 0x648, 4)
                self.invoke(
                    self.messages,
                    0x140D6C3D0,
                    game,
                    125,
                    identifier,
                    _signed(notice, 2) & _U32,
                    f.h(0x20),
                    f.h(0x28),
                )
                self.w(obj + 0x8B2, 2, 0xFFFF)
            queue = self.r(obj + 0x8A8)
            self.w(obj + 0x8A2, 2, 0)
            self.call(_CLEAR, queue)
            self.w(obj + 0x8B0, 1, self.r(obj + 0x8B0, 1) + 1)
            self.w(obj + 0x8A4, 2, 0)

    def select(self, f: _Frame, obj: int) -> bool:
        """Return whether source choice checks at2d85 are reached."""
        f.w(0x60, 2, 0xFFFF)
        if self.eax(0x14172AC80, self.r(obj + 0x18)):
            f.w(0x64, 2, 0xFFFF)
            f.w(0x68, 2, 0)
            action = self.pointer(_TOP, self.r(obj + 0x8A8))
            if action:
                kind = self.r(action + 8, 2)
                f.w(0x60, 2, kind)
                if kind in (0x66, 0x67):
                    f.w(0x20, 2, 0)
                    target = 0x140BB9EF0 if kind == 0x66 else 0x140BBCA50
                    self.invoke(self.selection, target, action, f.h(0x64), f.h(0x68), 0, f.h(0x20))
                    return True
            if _signed(self.r(obj + 0x8A2, 2), 2) > 0:
                f.w(0x60, 2, 0x66)
                rows = self.r(obj + 0x898)
                f.w(0x64, 2, self.r(rows, 2))
                return True
        f.w(0x28, 2, 0)
        f.w(0x20, 8, 0)
        result = self.invoke(
            self.selection, 0x1412E03A0, obj, f.h(0x60), f.h(0x64), f.h(0x68), f.h(0x20), f.h(0x28)
        )
        return _raw(result, "production selection EAX") & _U32 != 0

    def limited(self, f: _Frame, obj: int, status: int) -> bool:
        if self.eax(0x14172AC80, self.r(obj + 0x18)):
            self.reset(obj)
            return False
        notice = self.r(obj + 0x8B2, 2)
        if notice == status:
            return False
        if notice != 0xFFFF:
            self.apply_message(f, obj, 125, _signed(notice, 2))
        self.w(obj + 0x8B2, 2, status)
        self.apply_message(f, obj, 124, status)
        return False

    def capacity(self, f: _Frame, obj: int) -> bool:
        rows = self.r(obj + 0x898)
        if self.r(rows + 4, 2) == 0xFFFF:
            item = _signed(self.r(rows, 2), 2) & _U32
            owner = self.r(obj + 0x18)
            amount = _raw(self.scalar_amount(owner, item), "production capacity XMM0", 4)
            if compare_binary32(amount, 0) == 1:
                self.current_resource(f, obj, 0x58, 0x50)
                self.current_resource(f, obj, 0x288, 0x58)
                self.current_resource(f, obj, 0x100, 0x40)
                total = add_binary32(f.r(0x58, 4), f.r(0x50, 4))
                total = add_binary32(total, amount)
                if compare_binary32(total, f.r(0x40, 4)) == 1:
                    return self.limited(f, obj, 32)
                self.current_resource(f, obj, 0x20, 0x50)
                self.current_resource(f, obj, 0x288, 0x58)
                remaining = subtract_binary32(f.r(0x50, 4), f.r(0x58, 4))
                remaining = subtract_binary32(remaining, amount)
                if compare_binary32(0, remaining) == 1:
                    return self.limited(f, obj, 4)
            notice = self.r(obj + 0x8B2, 2)
            if notice != 0xFFFF:
                self.apply_message(f, obj, 125, _signed(notice, 2))
                self.w(obj + 0x8B2, 2, 0xFFFF)
        return True

    def prepare(self, f: _Frame, obj: int) -> None:
        rows = self.r(obj + 0x898)
        if self.r(rows + 4, 2) == 0xFFFF:
            allocation = self.pointer(0x142D6BA78, 0x80)
            f.w(0x50, 8, allocation)
            if allocation:
                for offset in range(0, 0x80, 16):
                    self.w(allocation + offset, 16, 0)
                rows = self.r(obj + 0x898)
                f.w(0x30, 4, self.r(rows + 0x28, 4))
                f.w(0x28, 2, self.r(rows + 0x2C, 2))
                f.w(0x20, 1, 0)
                item = self.r(rows, 2)
                action = self.invoke(
                    self.constructors,
                    0x140BB8550,
                    allocation,
                    obj,
                    item,
                    _U32,
                    f.h(0x20),
                    f.h(0x28),
                    f.h(0x30),
                )
            else:
                action = 0
            self.current_resource(f, obj, 0x20, 0x50)
            level = (_cvtt(f.r(0x50, 4)) - 1) & _U32
            settings = self.r(0x14425B930)
            result = self.call(0x14097F980, settings, 0x6D)
            if level <= 3 and _raw(result, "training notification AL") & 255:
                self.apply_message(f, obj, 169, 0)
        else:
            allocation = self.pointer(0x142D6BA78, 0x78)
            f.w(0x50, 8, allocation)
            if allocation:
                for offset in range(0, 0x70, 16):
                    self.w(allocation + offset, 16, 0)
                self.w(allocation + 0x70, 8, 0)
                rows = self.r(obj + 0x898)
                item = _signed(self.r(rows, 2), 2) & _U32
                f.w(0x20, 1, 0)
                association = self.r(rows + 4, 2)
                action = self.invoke(
                    self.constructors, 0x140BBB720, allocation, obj, association, item, f.h(0x20)
                )
            else:
                action = 0
        pointer = _raw(action, "production constructor RAX")
        if pointer:
            self.call(0x140B87C40, self.r(obj + 0x8A8), pointer)

    def append_if_absent(
        self, f: _Frame, obj: int, begin_offset: int, end_offset: int, association: int
    ) -> bool:
        end, begin = self.r(obj + end_offset), self.r(obj + begin_offset)
        returned = self.call(0x142D6A0C0, begin, end, association)
        current_end = self.r(obj + end_offset)
        if _raw(returned, "research find RAX") != current_end:
            return False
        self.call(0x14116C430, obj + begin_offset, f.h(0x48))
        return True

    def finish(self, f: _Frame, obj: int) -> None:
        status = self.al(_QUERY, self.r(obj + 0x8A8))
        if status == 1:
            rows = self.r(obj + 0x898)
            association = _signed(self.r(rows + 4, 2), 2)
            if association >= 0:
                owner = self.r(obj + 0x18)
                if owner:
                    manager = self.r(owner + 0x6D0)
                    if manager and self.al(0x141498220, manager, association & _U32):
                        rows = self.r(obj + 0x898)
                        association = self.r(rows + 4, 2)
                        f.w(0x48, 2, association)
                        if self.append_if_absent(f, obj, 0x9C8, 0x9D0, association):
                            f.w(0x48, 2, association)
                            self.append_if_absent(f, obj, 0x9B0, 0x9B8, association)
        elif ((status - 2) & 255) > 1:
            return
        self.call(_POP, self.r(obj + 0x8A8))
        if self.r(obj + 0x8A2, 2) == 0:
            return
        rows = self.r(obj + 0x898)
        if self.r(rows + 4, 2) == 0xFFFF:
            owner = self.r(obj + 0x18)
            target = self.r(self.r(owner) + 0xF8)
            item = _signed(self.r(rows, 2), 2) & _U32
            raw_amount = self.scalar_amount(owner, item)
            sign_mask = self.r(0x1431D37E0, 16) & _U32
            amount = _raw(raw_amount, "completion scalar XMM0", 4) ^ sign_mask
            f.w(0x20, 1, 1)
            self.credit(f, target, owner, amount)
        rows = self.r(obj + 0x898)
        self.w(rows + 2, 2, self.r(rows + 2, 2) - 1)
        self.w(obj + 0x8A4, 2, self.r(obj + 0x8A4, 2) - 1)
        self.w(obj + 0x8B0, 1, self.r(obj + 0x8B0, 1) + 1)
        rows = self.r(obj + 0x898)
        if _signed(self.r(rows + 2, 2), 2) > 0:
            return
        count = (self.r(obj + 0x8A2, 2) - 1) & 0xFFFF
        self.w(obj + 0x8A2, 2, count)
        if _signed(count, 2) <= 0:
            return
        index, offset = 0, 0
        while True:
            for member in (0, 2, 4):
                rows = self.r(obj + 0x898)
                value = self.r(rows + offset + member + 48, 2)
                self.w(rows + offset + member, 2, value)
            rows = self.r(obj + 0x898)
            value = self.r(rows + offset + 0x38, 16)
            self.w(rows + offset + 8, 16, value)
            value = self.r(rows + offset + 0x48, 8)
            self.w(rows + offset + 0x18, 8, value)
            for member, width in ((0x28, 4), (0x2C, 2)):
                rows = self.r(obj + 0x898)
                value = self.r(rows + offset + member + 48, width)
                self.w(rows + offset + member, width, value)
            index, offset = (index + 1) & _U32, (offset + 48) & _U64
            if _signed(index, 4) >= _signed(self.r(obj + 0x8A2, 2), 2):
                break

    def apply(self, obj: int) -> None:
        if not self.r(obj + 0x8A6, 1) or not self.r(obj + 0x8A2, 2):
            return
        with _Frame(self.context, self.bind_local, self.profile.apply) as f:
            if self.select(f, obj):
                for kind in (0x66, 0x67):
                    if f.r(0x60, 2) == kind and not self.eax(0x14172AC80, self.r(obj + 0x18)):
                        self.w(obj + 0x8B1, 1, 1)
                        return
                if (f.r(0x60, 2) - 0x7B) & 0xFFFF <= 2:
                    self.w(obj + 0x8B1, 1, 1)
                    return
            if _signed(self.al(0x14122CC30, obj), 1) < 0:
                self.w(obj + 0x8B1, 1, 1)
                return
            self.w(obj + 0x8B1, 1, 0)
            queue = self.r(obj + 0x8A8)
            if not self.r(queue + 0x10):
                if not self.capacity(f, obj):
                    return
                self.prepare(f, obj)
            self.finish(f, obj)


def bind_replay_building_production(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    area_fp_home_calls: ReplayTaskRebuildCalls,
    scalar_fp_calls: ReplayTaskRebuildCalls,
    resource_fp_home_calls: ReplayTaskRebuildCalls,
    message_home_calls: ReplayTaskRebuildCalls,
    selection_home_calls: ReplayTaskRebuildCalls,
    constructor_home_calls: ReplayTaskRebuildCalls,
    bind_local: LocalBinding,
    profile: ReplayBuildingProductionProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind all three whole callers with the frozen mixed/home capability API.

    Native physical stack/saves/cookie, faults/EH, FP status/upper lanes and
    concurrency remain excluded. Known returns are semantic void. Unknown
    target/arguments/payload/result identities pass through unchanged.
    """
    channels = (
        area_fp_home_calls,
        scalar_fp_calls,
        resource_fp_home_calls,
        message_home_calls,
        selection_home_calls,
        constructor_home_calls,
    )
    for channel in (calls, *channels):
        _validate(context, channel)
    if (
        not callable(bind_local)
        or not isinstance(profile, ReplayBuildingProductionProfile)
        or type(mxcsr) is not int
        or mxcsr != 0x1F80
    ):
        raise ValueError("actual locals/profile and exact MXCSR1f80 Building production required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in (_AREA, _RESET, _APPLY):
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != 1 or data is not None:
            raise ValueError("malformed addressed Building production call")
        _validate(context, calls, *args)
        state = _Production(context, calls, channels, bind_local, profile)
        if target == _AREA:
            state.area(args[0])
        elif target == _RESET:
            state.reset(args[0])
        else:
            state.apply(args[0])
        return None

    return ReplayTaskRebuildCalls(dispatch)
