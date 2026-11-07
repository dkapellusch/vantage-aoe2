"""Seven source-shaped special-mode helpers over explicit current storage.

Owns2598B/624 instructions. Reached deeper methods, globals, current imports,
atomics and FP/HOME services remain mandatory. Logical seeds retain partial
homes; physical stack, EH/fault identity and concurrent execution are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_binary32 import (
    add_binary32,
    compare_binary32,
    divide_binary32,
    signed16_binary32,
    signed32_binary32,
)
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
from .replay_unit_ai_construction import _local
from .replay_unit_ai_map import ReplayUnitAIMapAtomics, _release

_U32, _U64 = (1 << 32) - 1, (1 << 64) - 1
_OPTIONS, _CONFIG, _UI, _REQUEST = 0x140D6A530, 0x1413D2980, 0x140D66C40, 0x140D63400
_TILE, _BYTE9, _BYTE39 = 0x1415F9740, 0x14103C390, 0x14103C2C0
_ADDREF, _STRONG_RELEASE = 0x140990130, 0x140990140
_RESOURCE, _GAME = 0x1443E4E20, 0x144353698
_ARITIES = {_OPTIONS: 2, _CONFIG: 1, _UI: 1, _REQUEST: 1, _TILE: 4, _BYTE9: 2, _BYTE39: 2}


@dataclass(frozen=True, slots=True)
class ReplayWorldSpecialModeHelpersProfile:
    """Explicit postRSP options80/UI40/tile68 seeds, never default zeroes."""

    options: bytes
    ui: bytes
    tile: bytes

    def __post_init__(self) -> None:
        if any(
            type(seed) is not bytes or len(seed) != size
            for seed, size in (
                (self.options, 0x80),
                (self.ui, 0x40),
                (self.tile, 0x68),
            )
        ):
            raise ValueError("explicit options80/UI40/tile68 byte seeds required")


def _invoke(
    calls: ReplayTaskRebuildCalls,
    target: int,
    args: tuple[int, ...],
) -> int | None:
    if calls.call is None:
        raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
    return calls.call(target, tuple(value & _U64 for value in args), None)


def _rax(calls: ReplayTaskRebuildCalls, target: int, args: tuple[int, ...]) -> int:
    value = _invoke(calls, target, args)
    if value is None:
        raise ValueError(f"helper{target:x} must supply raw RAX at source consumer")
    _unsigned(value, 8, f"helper{target:x} raw RAX")
    return value


def set_replay_special_tile_byte39(
    context: ReplayTaskRebuildStorage,
    receiver: int,
    value: int,
) -> int:
    """Complete14B14103c2c0; return defined AL0/1, never native full RAX.

    Both inputs are raw u64 annotations; only value's DL is consumed. The
    generic binder deliberately discards this AL result in its ignored-return
    domain rather than invent upper RAX. No scratch or child service is used.
    """
    _validate(context, ReplayTaskRebuildCalls(None), receiver, value)
    byte = value & 0xFF
    if _read(context, receiver + 0x39, 1) == byte:
        return 0
    _write(context, receiver + 0x39, 1, byte)
    return 1


@dataclass(slots=True)
class _Helpers:
    context: ReplayTaskRebuildStorage
    calls: ReplayTaskRebuildCalls
    rtti: ReplayTaskRebuildCalls
    b8: ReplayTaskRebuildCalls
    owner: ReplayTaskRebuildCalls
    player: ReplayTaskRebuildCalls
    atomics: ReplayUnitAIMapAtomics
    bind_local: LocalBinding
    profile: ReplayWorldSpecialModeHelpersProfile

    def read(self, address: int, width: int) -> int:
        return _read(self.context, address, width)

    def write(self, address: int, width: int, value: int) -> None:
        _write(self.context, address, width, value)

    def invoke(self, target: int, args: tuple[int, ...]) -> int | None:
        return _invoke(self.calls, target, args)

    def rax(self, target: int, args: tuple[int, ...]) -> int:
        return _rax(self.calls, target, args)

    def lock(self, mutex: int, error5_trap: int, error6_trap: int) -> None:
        if self.rax(0x142D6AA5B, (mutex,)) & _U32:
            self.invoke(0x142D6AA67, (5,))
            raise UnresolvedReplayTaskRebuild(
                f"returning Throw_Cpp_error reaches INT3{error5_trap:x}",
            )
        if self.read(mutex + 0x4C, 4) == 0x7FFFFFFF:
            self.write(mutex + 0x4C, 4, 0x7FFFFFFE)
            self.invoke(0x142D6AA67, (6,))
            raise UnresolvedReplayTaskRebuild(
                f"returning Throw_Cpp_error reaches INT3{error6_trap:x}",
            )

    def options(self, output: int) -> int:
        with _local(memoryview(bytearray(self.profile.options)), self.bind_local) as frame:
            self.write(frame + 0x68, 8, output)
            state = 0
            self.write(frame + 0x20, 4, state)
            self.write(output, 8, 0)
            returned = self.rax(0x140E15890, (self.read(0x1442C3F98, 8),))
            token = self.read(returned, 8)
            self.write(output, 8, token)
            if token:
                self.invoke(_ADDREF, (token,))
            state = 1
            self.write(frame + 0x20, 4, state)
            if self.read(output, 8):
                return output
            allocation = self.rax(0x142D6BA78, (0x1178,))
            self.write(frame + 0x70, 8, allocation)
            token = 0
            if allocation:
                self.invoke(0x142D6E3B7, (allocation, 0, 0x1178))
                token = self.rax(0x1413B09A0, (allocation,))
            if token:
                self.invoke(_ADDREF, (token,))
            old = self.read(output, 8)
            if old:
                self.invoke(_STRONG_RELEASE, (old,))
            self.write(output, 8, token)
            resource = self.read(_RESOURCE, 8)
            gate = False
            if resource:
                mutex = (resource + 8) & _U64
                self.write(frame + 0x28, 8, mutex)
                self.lock(mutex, 0x140D6A7C1, 0x140D6A7D3)
                obj = self.read(resource, 8)
                self.write(frame + 0x70, 8, obj)
                if obj:
                    self.invoke(_ADDREF, (obj,))
                self.invoke(0x142D6AA61, (mutex,))
                state = 0xB
                self.write(frame + 0x20, 4, state)
                if obj:
                    returned = self.rax(0x140808540, (self.read(_RESOURCE, 8), frame + 0x78))
                    state = 0xF
                    self.write(frame + 0x20, 4, state)
                    gate = self.read(returned, 8) != 0
            else:
                obj = self.read(frame + 0x70, 8)
            if state & 4:
                state &= ~4
                self.write(frame + 0x20, 4, state)
                old = self.read(frame + 0x78, 8)
                if old:
                    self.invoke(_STRONG_RELEASE, (old,))
            if state & 2:
                state &= ~2
                self.write(frame + 0x20, 4, state)
                if obj:
                    self.invoke(_STRONG_RELEASE, (obj,))
            if not gate:
                return output
            resource = self.read(_RESOURCE, 8)
            mutex = (resource + 8) & _U64
            self.write(frame + 0x70, 8, mutex)
            self.lock(mutex, 0x140D6A7DE, 0x140D6A7B6)
            snapshot = self.read(resource, 8)
            self.write(frame + 0x78, 8, snapshot)
            if snapshot:
                self.invoke(_ADDREF, (snapshot,))
            state |= 0x10
            self.write(frame + 0x20, 4, state)
            self.invoke(0x142D6AA61, (mutex,))
            index = _signed(self.read(snapshot + 0x1C, 4), 4)
            begin = self.read(snapshot + 0x20, 8)
            length = _signed((self.read(snapshot + 0x28, 8) - begin) & _U64, 8) >> 3
            selected = 0
            if index < length and index >= 0:
                selected = self.read(begin + index * 8, 8)
                self.write(frame + 0x70, 8, selected)
                if selected:
                    self.invoke(_ADDREF, (selected,))
            else:
                self.write(frame + 0x70, 8, selected)
            state |= 0x20
            self.write(frame + 0x20, 4, state)
            converted = self.rax(0x141451420, (selected,))
            self.write(frame + 0x28, 8, converted)
            if converted:
                self.invoke(_ADDREF, (converted,))
            if selected:
                self.invoke(_STRONG_RELEASE, (selected,))
            if snapshot:
                self.invoke(_STRONG_RELEASE, (snapshot,))
            held_output = self.read(output, 8)
            returned = self.rax(0x1413D3720, (converted, frame + 0x70))
            self.invoke(0x1413E2A50, (held_output, returned))
            if converted:
                self.invoke(_STRONG_RELEASE, (converted,))
            return output

    def ui(self) -> None:
        selector = self.rax(0x140FFD0A0, (self.read(_GAME, 8),))
        with _local(memoryview(bytearray(self.profile.ui)), self.bind_local) as frame:
            self.write(frame + 0x20, 4, 0)
            cast = _rax(
                self.rtti,
                0x142D6E3D5,
                (
                    selector,
                    0,
                    0x1441754C8,
                    0x144120A20,
                    frame + 0x20,
                ),
            )
            if not cast:
                return
            self.write(frame + 0x30, 16, 0)
            control = self.read(cast + 0x148, 8)
            if control:
                if self.atomics.fetch_add is None:
                    raise UnresolvedReplayTaskRebuild("UI LOCK INC DWORD effect unavailable")
                self.atomics.fetch_add((control + 8) & _U64, 1)
            payload = self.read(cast + 0x140, 8)
            self.write(frame + 0x30, 8, payload)
            control = self.read(cast + 0x148, 8)
            self.write(frame + 0x38, 8, control)
            if payload:
                self.invoke(0x1414C2E70, (payload,))
            if control:
                _release(self.context, control, self.calls, self.atomics)

    def master(self, unit: int, scratch: int) -> int:
        self.write(scratch, 8, self.read(unit + 0x10, 8))
        self.write(scratch, 8, self.read(scratch, 8) - 0x6A586EB28AC201FC)
        self.write(scratch, 8, self.read(scratch, 8) - 0x0CF19788B2554E70)
        return self.read(scratch, 8)

    def level(self, unit: int, scratch: int) -> int:
        self.write(scratch, 8, self.read(self.master(unit, scratch) + 0x68, 8))
        self.write(scratch, 8, self.read(scratch, 8) ^ 0xD978539418047C54)
        self.write(scratch, 8, self.read(scratch, 8) ^ 0xABAA7F7397F61E6C)
        return self.read(scratch, 8)

    def health(self, unit: int, scratch: int) -> int:
        self.write(scratch, 8, self.read(unit + 0x130, 8))
        self.write(scratch, 8, self.read(scratch, 8) ^ 0x0F2A55F7A61DD00E)
        self.write(scratch, 8, self.read(scratch, 8) - 0x147B5E081EC087D9)
        return self.read(scratch, 8)

    def owner_update(self, unit: int, frame: int) -> None:
        scratch = frame + 0x40
        if self.read(self.master(unit, scratch) + 8, 1) < 0x46:
            return
        if not self.read(self.master(unit, scratch) + 0x379, 1) & 1:
            return
        owner = self.read(unit + 0x18, 8)
        target = self.read(self.read(owner, 8) + 0x2F8, 8)
        level = self.level(unit, scratch)
        health = self.health(unit, scratch)
        identifier = self.read(unit + 8, 4)
        self.write(scratch, 8, health)
        signed_level = _signed(level & 0xFFFF, 2) & _U32
        value = _cvtt(self.read(scratch, 4))
        self.write(frame + 0x30, 4, signed_level)
        self.write(frame + 0x28, 4, value)
        self.write(frame + 0x20, 4, identifier)
        _invoke(
            self.owner,
            target,
            (
                owner,
                identifier,
                identifier,
                0x213,
                frame + 0x20,
                frame + 0x28,
                frame + 0x30,
            ),
        )

    def member(self, unit: int, frame: int, first: int, divisor: int) -> None:
        scratch = frame + 0x40
        master = self.master(unit, scratch)
        self.write(scratch, 8, self.read(master + 0x18, 8))
        self.write(scratch, 8, self.read(scratch, 8) ^ 0x349E37847AD69F19)
        self.write(scratch, 8, self.read(scratch, 8) - 0x47E37DFF0616CE4F)
        if self.read(scratch, 8) & 0xFFFF == 0x64D:
            return
        if self.read(unit + 0xF, 1) == 0x50 and self.read(unit + 0x868, 8):
            return
        self.write(scratch, 8, self.health(unit, scratch))
        if compare_binary32(self.read(scratch, 4), first) == 1:
            level = self.level(unit, scratch)
            target = self.read(self.read(unit, 8) + 0xB8, 8)
            value = first
            if _signed(level & 0xFFFF, 2) > 60:
                level = self.level(unit, scratch)
                value = divide_binary32(signed16_binary32(_signed(level & 0xFFFF, 2)), divisor)
            _invoke(self.b8, target, (unit, value))
            self.owner_update(unit, frame)
            return
        self.write(frame + 0x58, 4, 0)
        self.write(scratch, 8, self.read(frame + 0x58, 8))
        self.write(scratch, 8, self.read(scratch, 8) + 0x147B5E081EC087D9)
        self.write(scratch, 8, self.read(scratch, 8) ^ 0x0F2A55F7A61DD00E)
        self.write(scratch, 8, self.read(scratch, 8))
        self.write(unit + 0x130, 8, self.read(scratch, 8))
        target = self.read(self.read(unit, 8) + 0xA8, 8)
        self.invoke(target, (unit, 0x607))

    def tile(self, world: int, x: int, y: int) -> None:
        x, y = x & _U32, y & _U32
        signed_x, signed_y = _signed(x, 4), _signed(y, 4)
        data = self.read(world + 0x98, 8)
        base = self.read(data + 8, 8)
        with _local(memoryview(bytearray(self.profile.tile)), self.bind_local) as frame:
            self.write(frame + 0x4C, 4, y)
            self.write(frame + 0x50, 4, x)
            self.write(frame + 0x60, 8, world)
            tile = 0
            if (
                base
                and signed_y >= 0
                and signed_y < _signed(self.read(data + 0x34, 4), 4)
                and signed_x >= 0
            ):
                width = self.read(data + 0x30, 4)
                if signed_x < _signed(width, 4):
                    offset = _signed(width * y & _U32, 4) + signed_x
                    tile = (base + (offset << 6)) & _U64
            if self.read(tile + 0x1B, 1):
                first = self.read(0x1436A0294, 4)
                divisor = self.read(0x1436A02E0, 4)
                index = 0
                while True:
                    unit = self.read(self.read(tile + 0x28, 8) + index * 8, 8)
                    if unit:
                        self.member(unit, frame, first, divisor)
                    count = self.read(tile + 0x1B, 1)
                    index = (index + 1) & _U64
                    if index >= count:
                        break
                y = self.read(frame + 0x4C, 4)
                x = self.read(frame + 0x50, 4)
                world = self.read(frame + 0x60, 8)
            if self.read(tile + 9, 1) == 0x45:
                return
            self.invoke(0x14103C310, (tile, _U32))
            self.write(tile + 0xE, 2, 0xFFFF)
            self.invoke(_BYTE9, (tile, 0x45))
            self.invoke(0x141040E60, (self.read(world + 0x98, 8), y, x))
            self.write(tile + 0x15, 1, 0xCC)
            self.write(tile + 0x18, 1, 0)
            self.invoke(_BYTE39, (tile, 0x45))
            self.write(tile + 0x3C, 2, 0xFFFF)
            flag = (frame + 0x48) & _U64
            rows = self.read(world + 0x768, 8)
            self.write(frame + 0x30, 8, flag)
            player = self.read(rows, 8)
            fy = signed32_binary32(_signed(y, 4))
            self.write(frame + 0x28, 4, 0)
            vptr = self.read(player, 8)
            self.write(frame + 0x48, 1, 1)
            fx = signed32_binary32(_signed(x, 4))
            fy = add_binary32(fy, self.read(0x1431B2420, 4))
            fx = add_binary32(fx, self.read(0x1431B2420, 4))
            self.write(frame + 0x20, 4, 0)
            target = self.read(vptr + 0x1C8, 8)
            obj = _rax(
                self.player,
                target,
                (
                    player,
                    0x64D,
                    fx,
                    fy,
                    frame + 0x20,
                    frame + 0x28,
                    frame + 0x30,
                    flag,
                ),
            )
            self.write(obj + 0x160, 2, 0xC)
            self.write(obj + 0x168, 4, 0x42F00000)
            self.invoke(0x141868B80, (x, y, x, y))


def bind_replay_world_special_mode_helpers(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    *,
    rtti_home_calls: ReplayTaskRebuildCalls,
    b8_fp_calls: ReplayTaskRebuildCalls,
    owner_home_calls: ReplayTaskRebuildCalls,
    player_fp_home_calls: ReplayTaskRebuildCalls,
    atomics: ReplayUnitAIMapAtomics,
    bind_local: LocalBinding,
    profile: ReplayWorldSpecialModeHelpersProfile,
    mxcsr: int,
) -> ReplayTaskRebuildCalls:
    """Bind all seven complete bodies with explicit live FP/HOME channels.

    Incoming Game/RCX annotations can be ignored by the original body; no fake
    zero is required. Unknown target, argument tuple, data and result identity
    pass unchanged to the delegate. All normal owned child calls route through
    this binder, including the two DL-only leaves. No missing service succeeds.

    The four dedicated channels use the accepted API's prepared register/FP
    annotations followed by HOME LOCATIONS, never eager home values. Deeper
    incidental register consumption is outside that explicit effective ABI.
    Only masked MXCSR1f80 is admitted; FP status/upper lanes are not owned.
    Native physical stack/cookie/EH/fault/concurrency are excluded. Finite valid
    backing and source-terminating synchronous callbacks are required; no loop
    cap or blank backing is introduced. Exceptions preserve preceding effects.
    """
    _validate(context, calls)
    if not isinstance(profile, ReplayWorldSpecialModeHelpersProfile):
        raise ValueError("explicit special-mode helper profile required")
    if not isinstance(atomics, ReplayUnitAIMapAtomics) or not callable(bind_local):
        raise ValueError("actual DWORD atomics and scoped local binding required")
    if any(
        not isinstance(channel, ReplayTaskRebuildCalls)
        for channel in (
            rtti_home_calls,
            b8_fp_calls,
            owner_home_calls,
            player_fp_home_calls,
        )
    ):
        raise ValueError("four explicit FP/HOME channels required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("exact masked MXCSR1f80 profile required")

    def dispatch(target: int, args: tuple[int, ...], data: memoryview | None) -> int | None:
        if target not in _ARITIES:
            if calls.call is None:
                raise UnresolvedReplayTaskRebuild(f"reached{target:x} is unavailable")
            return calls.call(target, args, data)
        if len(args) != _ARITIES[target] or data is not None:
            raise ValueError(f"actual{target:x} prepared arity/data required")
        _validate(context, calls, *args)
        if target == _OPTIONS:
            return helpers.options(args[1])
        if target == _CONFIG:
            return helpers.read(args[0] + 0x1158, 4)
        if target == _UI:
            helpers.ui()
        elif target == _REQUEST:
            held = helpers.read(args[0] + 0xA80, 8)
            if held:
                helpers.write(held + 0x6D, 1, 1)
            return held
        elif target == _TILE:
            helpers.tile(args[1], args[2], args[3])
        elif target == _BYTE9:
            receiver, value = args[0], args[1] & 0xFF
            old = helpers.read(receiver + 9, 1)
            if old != value:
                if helpers.read(receiver + 0x39, 1) == 0xFF:
                    helpers.write(receiver + 0x39, 1, old)
                helpers.write(receiver + 9, 1, value)
            return old
        else:
            set_replay_special_tile_byte39(context, args[0], args[1])
        return None

    bound = ReplayTaskRebuildCalls(dispatch)
    helpers = _Helpers(
        context,
        bound,
        rtti_home_calls,
        b8_fp_calls,
        owner_home_calls,
        player_fp_home_calls,
        atomics,
        bind_local,
        profile,
    )
    return bound
