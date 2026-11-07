"""Owned color-query backing from exact typed DAT rows, not native construction.

World+e8 points to ordered QWORD descriptor pointers. The original538B Player
color consumer reads the ninth serialized DWORD at descriptor+4. Only that
field is defined here; asset state and other descriptor/header fields remain
undefined. Source: player-world-color-descriptor-source-v1.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_game_data import GameDataColor, GameDataColors
from vantage.replay_memory import ReplayMemory

_OFFSETS = (0, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 4)


@dataclass(frozen=True, slots=True)
class ReplayColorBacking:
    """Fresh engine allocations; no native World/class/asset identity implied."""

    table: int
    descriptors: tuple[int, ...]
    palette_indices: tuple[int, ...]
    raw_rows: tuple[bytes, ...]


def build_replay_color_backing(memory: ReplayMemory, colors: GameDataColors) -> ReplayColorBacking:
    """Materialize consumed fields after validating the complete typed wire rows.

    The caller explicitly publishes table to its owned World+e8. This function
    does not replace an old table, set native capacity/count/quantum, load
    shadow.col, register native loaders or choose mode/settings/observer/flags.
    Every other reached color-consumer dependency remains mandatory.

    Empty data yields a null table. Allocation failure preserves prior owned
    allocations/writes; no rollback or fabricated successful pointer is added.
    """
    if not isinstance(memory, ReplayMemory) or not isinstance(colors, GameDataColors):
        raise ValueError("owned memory and typed DAT colors required")
    if (
        type(colors.count) is not int
        or not 0 <= colors.count <= 0x7FFF
        or type(colors.colors) is not tuple
        or len(colors.colors) != colors.count
        or type(colors.raw) is not bytes
    ):
        raise ValueError("complete signed-WORD color count and rows required")
    rows, indices = [], []
    for row in colors.colors:
        if (
            not isinstance(row, GameDataColor)
            or type(row.raw) is not bytes
            or len(row.raw) != 36
            or type(row.fields) is not dict
            or set(row.fields) != set(_OFFSETS)
            or any(type(key) is not int for key in row.fields)
        ):
            raise ValueError("complete nine-DWORD color row required")
        for position, offset in enumerate(_OFFSETS):
            value = row.fields[offset]
            if (
                type(value) is not int
                or not 0 <= value <= 0xFFFFFFFF
                or value != int.from_bytes(row.raw[position * 4 : position * 4 + 4], "little")
            ):
                raise ValueError("typed color fields must match exact raw row")
        rows.append(row.raw)
        indices.append(row.fields[4])
    if colors.raw != colors.count.to_bytes(2, "little") + b"".join(rows):
        raise ValueError("typed color section must match its complete raw bytes")
    table = memory.allocate(colors.count * 8) if colors.count else 0
    descriptors = []
    for index, value in enumerate(indices):
        descriptor = memory.allocate(0x38)
        descriptors.append(descriptor)
        memory.write(descriptor + 4, 4, value)
        memory.write(table + index * 8, 8, descriptor)
    return ReplayColorBacking(table, tuple(descriptors), tuple(indices), tuple(rows))
