"""Non-Gaia command issuer lookup from an explicit logical options/world view.

Original140e15e30 ->140e4fb80 ->140e501b0 separates wire selector, descriptor
slot and World player-array index. Evidence: world-envelope/command-issuer-resolution.
This lookup assumes a present global context and GameOptions. Their native
missing-options fallback and command-processor World/Gaia route are separate.
"""

from __future__ import annotations

from dataclasses import dataclass

from .replay_file_header import SavedReplayGameOptions

_U32 = 0xFFFFFFFF
_INITIAL_SLOTS = tuple(range(8))


class ReplayCommandPlayerError(ValueError):
    """The logical context is malformed or the native route is unsupported."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _u32(value: int, label: str) -> None:
    if type(value) is not int or not 0 <= value <= _U32:
        raise ReplayCommandPlayerError("word", f"{label} must be a u32")


@dataclass(frozen=True, slots=True)
class ReplayCommandPlayerSlot:
    humanity: int
    world_player_index: int

    def __post_init__(self) -> None:
        _u32(self.humanity, "humanity")
        _u32(self.world_player_index, "world player index")


@dataclass(frozen=True, slots=True)
class ReplayCommandPlayerBinding:
    selector: int
    options_slot: int
    world_player_index: int


@dataclass(frozen=True, slots=True)
class ReplayCommandPlayerTable:
    """One caller-supplied coherent lookup context, with native null outcomes.

    Eight descriptor slots select eight GameOptions records. A None record is
    unknown/unrestored, not inactive. A None World, empty vector, absent player,
    inactive humanity, invalid index or out-of-range index returns no binding.
    A binding identifies a vector slot, not command acceptance or an object owner.
    """

    players: tuple[ReplayCommandPlayerSlot | None, ...]
    world_player_present: tuple[bool, ...] | None
    descriptor_slots: tuple[int, ...] = _INITIAL_SLOTS

    def __post_init__(self) -> None:
        if (
            type(self.players) is not tuple
            or len(self.players) != 8
            or any(
                p is not None and not isinstance(p, ReplayCommandPlayerSlot) for p in self.players
            )
        ):
            raise ReplayCommandPlayerError("options", "eight typed or unknown slots are required")
        if (
            type(self.descriptor_slots) is not tuple
            or len(self.descriptor_slots) != 8
            or any(type(i) is not int or not 0 <= i < 8 for i in self.descriptor_slots)
        ):
            raise ReplayCommandPlayerError(
                "descriptors", "eight bounded lobby indices are required"
            )
        if self.world_player_present is not None and (
            type(self.world_player_present) is not tuple
            or any(type(p) is not bool for p in self.world_player_present)
        ):
            raise ReplayCommandPlayerError("world", "World presence must be a tuple of booleans")

    def resolve_non_gaia(self, selector: int) -> ReplayCommandPlayerBinding | None:
        """Resolve wire1..8 through descriptor+20 and options+b8/b4.

        Native address helpers have no bounds checks. Unsupported selectors
        fail explicitly here. Selector0 uses a different command-World pointer
        in the dispatcher and is deliberately outside this helper's contract.
        """
        if type(selector) is not int or not 1 <= selector <= 8:
            raise ReplayCommandPlayerError(
                "selector", "only non-Gaia wire selectors1..8 are supported"
            )
        slot = self.descriptor_slots[selector - 1]
        player = self.players[slot]
        if player is None:
            raise ReplayCommandPlayerError("unrestored_slot", f"lobby slot{slot} is unknown")
        if player.humanity not in (2, 3, 4):
            return None
        world = self.world_player_present
        index = player.world_player_index
        if world is None or not world or index == _U32 or index >= len(world) or not world[index]:
            return None
        return ReplayCommandPlayerBinding(selector, slot, index)


def initial_replay_command_players(
    options: SavedReplayGameOptions, world_player_count: int
) -> ReplayCommandPlayerTable:
    """Bind saved slots to the static initializer's canonical descriptor order.

    This is an initial logical association. It does not assert preservation
    through native loading, reference callbacks, startup or later commands.
    All saved World players are present; absent saved lobby records remain
    unknown. Signed saved indices retain their exact u32 native interpretation.
    """
    if not isinstance(options, SavedReplayGameOptions) or options.version_word != 0x448C6000:
        raise ReplayCommandPlayerError("options", "saved options1123 are required")
    count = options.max_players_for_lobby
    if (
        type(count) is not int
        or not 0 <= count <= 8
        or len(options.players) != count
        or any(
            type(p.slot) is not int or p.slot != i or p.version != 15
            for i, p in enumerate(options.players)
        )
    ):
        raise ReplayCommandPlayerError("options", "saved lobby slots are inconsistent")
    if type(world_player_count) is not int or not 0 <= world_player_count <= 0xFFFF:
        raise ReplayCommandPlayerError("world", "saved World player count must be a u16")
    rows: list[ReplayCommandPlayerSlot | None] = []
    for p in options.players:
        if (
            type(p.world_player_index) is not int
            or not -(1 << 31) <= p.world_player_index < 1 << 31
        ):
            raise ReplayCommandPlayerError("word", "saved world player index must be an i32")
        rows.append(ReplayCommandPlayerSlot(p.humanity, p.world_player_index & _U32))
    rows.extend([None] * (8 - len(rows)))
    return ReplayCommandPlayerTable(tuple(rows), (True,) * world_player_count)
