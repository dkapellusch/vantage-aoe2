"""Owned prerequisite backing for the saved research reader, not native loading.

The original reader consumes a catalog QWORD at0, signed WORD at8 and six
prerequisite WORDs at18..22 in each88-byte definition. Only those fields are
defined. Source: research-catalog-backing-frontier-v1 (590 selected bytes).
No original function is bound by this authored data projection.
"""

from __future__ import annotations

from dataclasses import dataclass

from vantage.replay_game_data import GameDataResearchCatalog, GameDataResearchDefinition
from vantage.replay_memory import ReplayMemory


@dataclass(frozen=True, slots=True)
class ReplayResearchCatalogBacking:
    """Fresh owned storage; native class, balance and lifecycle identity unproved."""

    catalog: int
    definitions: int
    prerequisite_bits: tuple[tuple[int, ...], ...]
    raw_rows: tuple[bytes, ...]


def build_replay_research_catalog_backing(
    memory: ReplayMemory, catalog: GameDataResearchCatalog
) -> ReplayResearchCatalogBacking:
    """Validate exact prerequisite wire bits before allocating sparse backing.

    The caller publishes the returned catalog explicitly, if appropriate. This
    function does not set World+828 or catalog+10, allocate native array cookies,
    initialize other definition fields, or replace a native DAT constructor.
    Unconsumed definition metadata is retained as raw bytes, without claiming
    validation of its native meaning. Empty definitions use a null pointer.
    Allocation failure preserves earlier owned allocations and writes.
    """
    if not isinstance(memory, ReplayMemory) or not isinstance(catalog, GameDataResearchCatalog):
        raise ValueError("owned memory and typed DAT research catalog required")
    if (
        type(catalog.count) is not int
        or not 0 <= catalog.count <= 0x7FFF
        or type(catalog.definitions) is not tuple
        or len(catalog.definitions) != catalog.count
        or type(catalog.raw) is not bytes
    ):
        raise ValueError("complete signed-WORD research count and definitions required")
    rows, prerequisites = [], []
    for row in catalog.definitions:
        if (
            not isinstance(row, GameDataResearchDefinition)
            or type(row.raw) is not bytes
            or len(row.raw) < 62
            or type(row.prerequisite_bits) is not tuple
            or len(row.prerequisite_bits) != 6
            or any(
                type(value) is not int or not 0 <= value <= 0xFFFF
                for value in row.prerequisite_bits
            )
            or type(row.sections) is not dict
            or type(row.sections.get("prerequisites")) is not bytes
        ):
            raise ValueError("complete typed six-WORD prerequisite definition required")
        raw = b"".join(value.to_bytes(2, "little") for value in row.prerequisite_bits)
        if raw != row.raw[:12] or raw != row.sections["prerequisites"]:
            raise ValueError("typed research prerequisites must match exact raw words")
        prerequisites.append(row.prerequisite_bits)
        rows.append(row.raw)
    if catalog.raw != catalog.count.to_bytes(2, "little") + b"".join(rows):
        raise ValueError("typed research catalog must match its complete raw bytes")
    header = memory.allocate(0x18)
    definitions = memory.allocate(catalog.count * 0x88) if catalog.count else 0
    memory.write(header, 8, definitions)
    memory.write(header + 8, 2, catalog.count)
    for index, bits in enumerate(prerequisites):
        for position, value in enumerate(bits):
            memory.write(definitions + index * 0x88 + 0x18 + 2 * position, 2, value)
    return ReplayResearchCatalogBacking(header, definitions, tuple(prerequisites), tuple(rows))
