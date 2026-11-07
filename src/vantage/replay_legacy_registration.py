"""Isolated kind2/5 registration using explicit shared pool and native context.

Modern registration is disabled in this API. Kind2 additionally requires the
genuine empty-listener callback premise on every call. Kind5 never executes
tile/callback/fmod work. Complete World binding and modern composition remain
separate from these supported legacy effects.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from .replay_legacy_kind2 import (
    LegacyKind2Pool,
    LegacyKind2State,
    LegacyRegistrationRefresh,
    UnsupportedLegacyKind2,
    _integer,
    _LegacyRegistrationPhase,
)

# Runtime constructor aliases preserve the existing value types and identity.
LegacyRegistrationPool = LegacyKind2Pool
LegacyRegistrationState = LegacyKind2State


class UnsupportedLegacyRegistration(UnsupportedLegacyKind2):
    """Current context or an operation is outside isolated legacy registration."""


@dataclass(frozen=True, slots=True)
class LegacyRegistrationContext:
    modern_enabled: bool
    genuine_empty_listener_callback: bool
    disjoint_backing: bool
    mxcsr: int

    def __post_init__(self) -> None:
        for name in ("modern_enabled", "genuine_empty_listener_callback", "disjoint_backing"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"explicit bool required for {name}")
        _integer(self.mxcsr, 0, 0xFFFFFFFF, "MXCSR")
        if self.modern_enabled or not self.disjoint_backing:
            raise UnsupportedLegacyRegistration("isolated legacy and disjoint backing required")
        if self.mxcsr & ~0x3F != 0x1F80:
            raise UnsupportedLegacyRegistration(
                "masked nearest-even controls with DAZ/FTZ off required"
            )


class LegacyRegistrationRegistry(_LegacyRegistrationPhase):
    """Successful kind2/5 refresh with the full block/cursor/LIFO pool state.

    An unestablished empty-listener premise permits kind5, whose original branch
    skips the callback. Each later kind2 call must establish that premise too.
    Capacity/support refusals precede mutation; excluded native failure effects,
    kind2 World/tile removal and modern-enabled composition remain separate.
    """

    def __init__(self, state: LegacyRegistrationState, context: LegacyRegistrationContext) -> None:
        if (
            type(state) is not LegacyRegistrationState
            or type(context) is not LegacyRegistrationContext
        ):
            raise ValueError("explicit typed shared legacy state and context required")
        self._registration_context = context
        super().__init__(state)

    def refresh(
        self,
        object_token: int,
        *,
        position_bits: tuple[int, int],
        radius_bits: tuple[int, int],
        kind: int,
        mode: int,
        owner: int,
    ) -> LegacyRegistrationRefresh:
        if (
            type(kind) is int
            and kind == 2
            and not (self._registration_context.genuine_empty_listener_callback)
        ):
            raise UnsupportedLegacyRegistration("kind2 requires the genuine empty callback premise")
        try:
            return self._refresh(
                object_token,
                position_bits=position_bits,
                radius_bits=radius_bits,
                kind=kind,
                mode=mode,
                owner=owner,
            )
        except UnsupportedLegacyKind2 as error:
            raise UnsupportedLegacyRegistration(str(error)) from error

    def remove(self, object_token: int, *, kind: int) -> bool:
        """Native141121960 isolated kind5 removal; return only its defined AL.

        Kind is the current master kind, independent of the stored record kind.
        Kind2 needs current World tile/occupant/owner/callback context and is
        refused even when its legacy link is null. F2 is not an admission gate.
        Record payload and stale bucket tails survive; only free-next is reused.
        """
        _integer(object_token, 1, (1 << 64) - 1, "object token")
        if object_token not in self._objects:
            raise ValueError("object token is not registered")
        if type(kind) is not int or kind != 5:
            raise UnsupportedLegacyRegistration("current master kind5 removal required")
        token = self._links[object_token]
        if not token:
            return False
        raw = self._records[token]
        bucket = struct.unpack_from("<i", raw, 4)[0]
        row = struct.unpack_from("<i", raw, 0x1C)[0]
        used = self._used[bucket]
        if row + 1 < used:
            last_token = self._slots[bucket][used - 1]
            self._slots[bucket][row] = last_token
            struct.pack_into("<i", self._records[last_token], 0x1C, row)
        self._used[bucket] -= 1
        struct.pack_into("<Q", raw, 0x10, self._free)
        self._available += 1
        self._free = token
        self._links[object_token] = 0
        return True

    def action_end_flags(self, object_token: int, *, mode: Literal[0, 16]) -> None:
        """Native141121110 explicit-mode leaf with modern registration disabled.

        The outer virtual610/Game-clock wrapper is separate. Mode0/16 is an
        explicit caller input, not inferred from movement or the current kind.
        The leaf has no defined native return, including for a null record link.
        """
        _integer(object_token, 1, (1 << 64) - 1, "object token")
        if object_token not in self._objects:
            raise ValueError("object token is not registered")
        if type(mode) is not int or mode not in (0, 16):
            raise UnsupportedLegacyRegistration("explicit action-end flag mode0 or16 required")
        token = self._links[object_token]
        if token:
            raw = self._records[token]
            raw[3] = (raw[3] & 0x0F) | mode
