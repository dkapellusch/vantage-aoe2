"""Exact wire prerequisites and undefined-field boundaries in owned DAT backing."""

from __future__ import annotations

import struct
from dataclasses import replace

import pytest

from vantage.replay_binary import SaveReader
from vantage.replay_game_data import (
    GameDataResearchCatalog,
    read_game_data_research_catalog,
)
from vantage.replay_memory import ReplayMemory, ReplayMemoryError
from vantage.replay_research_data import build_replay_research_catalog_backing


def catalog_fixture() -> GameDataResearchCatalog:
    """Public DAT parser on explicit variable-length wire rows, not native defaults."""
    raw = bytearray(struct.pack("<h", 3))
    for bits, name, locations in (
        ((0xFFFF, 0, 1, 0x8000, 0x7FFF, 2), b"", b""),
        ((2, 1, 0, 0xFFFE, 0xFFFF, 0xABCD), b"\xffA\0", b"\xa5" * 9),
        ((0x8001, 2, 2, 1, 0, 0xFFFF), b"third", b"\x5a" * 18),
    ):
        raw += struct.pack("<6H", *bits) + bytes(15 + 28)
        raw += struct.pack("<HH", 0xA60, len(name)) + name + b"\xa5"
        raw += struct.pack("<h", len(locations) // 9) + locations
    reader = SaveReader(bytes(raw), version=0x43E666)
    catalog = read_game_data_research_catalog(reader)
    assert reader.remaining == 0
    return catalog


def test_exact_raw_words_stride_count_and_variable_length_rows() -> None:
    memory = ReplayMemory()
    catalog = catalog_fixture()
    backing = build_replay_research_catalog_backing(memory, catalog)
    assert memory.read(backing.catalog, 8) == backing.definitions
    assert memory.read(backing.catalog + 8, 2) == 3
    assert backing.prerequisite_bits == tuple(row.prerequisite_bits for row in catalog.definitions)
    assert backing.raw_rows == tuple(row.raw for row in catalog.definitions)
    assert [len(row) for row in backing.raw_rows] == [62, 74, 85]
    for index, row in enumerate(catalog.definitions):
        assert memory.read_bytes(backing.definitions + index * 0x88 + 0x18, 12) == row.raw[:12]
        assert (
            tuple(
                memory.read(backing.definitions + index * 0x88 + 0x18 + 2 * i, 2) for i in range(6)
            )
            == row.prerequisite_bits
        )


def test_every_unconsumed_header_and_definition_byte_is_undefined() -> None:
    memory = ReplayMemory()
    backing = build_replay_research_catalog_backing(memory, catalog_fixture())
    for offset in range(10, 0x18):
        with pytest.raises(ReplayMemoryError, match="undefined"):
            memory.read(backing.catalog + offset, 1)
    for index in range(3):
        for offset in (*range(0x18), *range(0x24, 0x88)):
            with pytest.raises(ReplayMemoryError, match="undefined"):
                memory.read(backing.definitions + index * 0x88 + offset, 1)


def test_empty_catalog_has_defined_null_pointer_and_only_two_header_fields() -> None:
    memory = ReplayMemory()
    reader = SaveReader(b"\0\0", version=0x43E666)
    backing = build_replay_research_catalog_backing(memory, read_game_data_research_catalog(reader))
    assert backing.definitions == 0 and backing.prerequisite_bits == backing.raw_rows == ()
    assert memory.read_bytes(backing.catalog, 10) == bytes(10)
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(backing.catalog + 10, 1)


@pytest.mark.parametrize("count", [True, -1, 0x8000, 2])
def test_invalid_count_fails_without_memory_effects(count: int) -> None:
    memory = ReplayMemory()
    before = memory.snapshot()
    with pytest.raises(ValueError, match="count"):
        build_replay_research_catalog_backing(memory, replace(catalog_fixture(), count=count))
    assert memory.snapshot() == before


@pytest.mark.parametrize(
    "which",
    [
        "tuple",
        "bits-short",
        "bits-long",
        "bool",
        "negative",
        "wide",
        "raw-short",
        "raw-type",
        "sections",
        "section-type",
        "section-bits",
        "row-bits",
        "catalog-raw",
        "catalog-type",
    ],
)
def test_inconsistent_last_row_fails_before_any_allocation(which: str) -> None:
    memory = ReplayMemory()
    catalog = catalog_fixture()
    row = catalog.definitions[-1]
    bits = row.prerequisite_bits
    if which == "tuple":
        catalog = replace(catalog, definitions=list(catalog.definitions))
    elif which == "bits-short":
        row = replace(row, prerequisite_bits=bits[:-1])
    elif which == "bits-long":
        row = replace(row, prerequisite_bits=(*bits, 0))
    elif which in ("bool", "negative", "wide"):
        row = replace(
            row,
            prerequisite_bits=(*bits[:-1], {"bool": True, "negative": -1, "wide": 0x10000}[which]),
        )
    elif which == "raw-short":
        row = replace(row, raw=row.raw[:12])
    elif which == "raw-type":
        row = replace(row, raw=bytearray(row.raw))
    elif which == "sections":
        row = replace(row, sections={})
    elif which == "section-type":
        row = replace(row, sections={**row.sections, "prerequisites": bytearray(row.raw[:12])})
    elif which == "section-bits":
        row = replace(row, sections={**row.sections, "prerequisites": bytes(12)})
    elif which == "row-bits":
        row = replace(row, prerequisite_bits=(1, *bits[1:]))
    elif which == "catalog-raw":
        catalog = replace(catalog, raw=catalog.raw + b"extra")
    elif which == "catalog-type":
        catalog = replace(catalog, raw=bytearray(catalog.raw))
    if which not in ("tuple", "catalog-raw", "catalog-type"):
        catalog = replace(catalog, definitions=(*catalog.definitions[:-1], row))
    before = memory.snapshot()
    with pytest.raises(ValueError):
        build_replay_research_catalog_backing(memory, catalog)
    assert memory.snapshot() == before


def test_fresh_backings_are_distinct_and_unconsumed_metadata_is_not_invented() -> None:
    memory = ReplayMemory()
    catalog = catalog_fixture()
    first = build_replay_research_catalog_backing(memory, catalog)
    second = build_replay_research_catalog_backing(memory, catalog)
    assert first.catalog != second.catalog and first.definitions != second.definitions
    memory.write(first.definitions + 0x18, 2, 123)
    assert memory.read(second.definitions + 0x18, 2) == 0xFFFF
    assert first.prerequisite_bits[0][0] == 0xFFFF


def test_failure_keeps_actual_prior_allocations_without_publishing_a_catalog() -> None:
    class FailingMemory(ReplayMemory):
        def __init__(self) -> None:
            super().__init__()
            self.allocations: list[int] = []

        def allocate(self, size: int) -> int:
            if self.allocations:
                raise ReplayMemoryError("explicit allocation failure")
            address = super().allocate(size)
            self.allocations.append(address)
            return address

    memory = FailingMemory()
    with pytest.raises(ReplayMemoryError, match="explicit allocation failure"):
        build_replay_research_catalog_backing(memory, catalog_fixture())
    assert len(memory.allocations) == 1
    with pytest.raises(ReplayMemoryError, match="undefined"):
        memory.read(memory.allocations[0], 1)
