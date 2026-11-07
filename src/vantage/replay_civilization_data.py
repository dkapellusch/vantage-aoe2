"""Owned civilization data and source-shaped ID/name registry initialization.

JSON ordinals/data_name and the query layouts are source-proven. This builds
engine backing through real insertion/comparison providers; it does not execute
or impersonate the game's record constructor, JSON loader, or global initializer.
Only required record fields are defined. Other record bytes remain undefined.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import ExitStack
from dataclasses import dataclass
from typing import cast

from vantage.replay_era_data import ReplayEraData
from vantage.replay_memory import ReplayMemory
from vantage.replay_task_rebuild import ReplayTaskRebuildCalls, _call


@dataclass(frozen=True, slots=True)
class ReplayCivilizationDefinition:
    """One selected source JSON row; ordinal is the actual parser's ID input."""

    ordinal: int
    data_name: bytes
    source_row: bytes
    research_rows: bytes | None = None

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or not 0 <= self.ordinal <= 0xFFFFFFFF:
            raise ValueError("civilization ordinal must be raw DWORD")
        if type(self.data_name) is not bytes or not self.data_name or b"\0" in self.data_name:
            raise ValueError("explicit nonempty civilization name bytes without NUL required")
        if type(self.source_row) is not bytes:
            raise ValueError("explicit source JSON row bytes required")
        if self.research_rows is not None and (
            type(self.research_rows) is not bytes or len(self.research_rows) % 20
        ):
            raise ValueError("explicit complete twenty-byte research rows required")


@dataclass(frozen=True, slots=True)
class ReplayCivilizationData:
    definitions: tuple[ReplayCivilizationDefinition, ...]
    source_sha256: str
    total_rows: int
    era_source_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.definitions) is not tuple or any(
            not isinstance(row, ReplayCivilizationDefinition) or row.ordinal != index
            for index, row in enumerate(self.definitions)
        ):
            raise ValueError("ordered civilization definitions with original ordinals required")
        if type(self.total_rows) is not int or self.total_rows < len(self.definitions):
            raise ValueError("actual source row count must include selected definitions")
        if (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.source_sha256)
        ):
            raise ValueError("explicit lowercase source SHA256 required")
        if self.era_source_sha256 is not None and (
            type(self.era_source_sha256) is not str
            or len(self.era_source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.era_source_sha256)
        ):
            raise ValueError("explicit lowercase era source SHA256 required")
        if any(
            (row.research_rows is None) != (self.era_source_sha256 is None)
            for row in self.definitions
        ):
            raise ValueError("research backing requires the explicit resolved era source")


@dataclass(frozen=True, slots=True)
class ReplayCivilizationRegistry:
    """Engine-owned prefix backing, never a native object-identity certificate."""

    writer_family: int
    numeric_header: int
    name_header: int
    sentinel: int
    records: tuple[int, ...]
    name_nodes: tuple[int, ...]
    data: ReplayCivilizationData


def read_replay_civilization_data(
    raw: bytes,
    *,
    count: int,
    eras: ReplayEraData | None = None,
) -> ReplayCivilizationData:
    """Decode an explicitly resolved asset and caller-selected prefix count.

    The original loader limits selected rows using its real data context. That
    limit is a required caller input here; a basename alone never proves build,
    balance, current Game identity or that every available row was registered.
    Complete semantic JSON rows are retained as compact serialized bytes,
    rather than original lexical byte spans. The current query projection
    consumes ID/data_name and, when explicit eras are supplied, exact era-name
    research overrides. That optional projection admits only existing named
    eras. Empty or NUL-containing names are not admitted. Source digests identify
    the supplied files; matching replay build/mod selection is still required.
    """
    if type(raw) is not bytes or type(count) is not int or not 0 <= count <= 0xFFFFFFFF:
        raise ValueError("explicit JSON bytes and raw DWORD selected row count required")
    if eras is not None and not isinstance(eras, ReplayEraData):
        raise ValueError("explicit resolved era data required")
    document: object = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("civilization JSON root must be an object")
    root = cast(dict[str, object], document)
    value = root.get("civilization_list")
    if not isinstance(value, list) or count > len(value):
        raise ValueError("selected civilization rows must exist in civilization_list")
    entries = cast(list[object], value)
    definitions = []
    for index, row in enumerate(entries[:count]):
        if not isinstance(row, dict):
            raise ValueError("selected civilization row must be an object")
        fields = cast(dict[str, object], row)
        name = fields.get("data_name")
        if not isinstance(name, str):
            raise ValueError("selected civilization row requires data_name string")
        research_rows = None
        if eras is not None:
            era = fields.get("era")
            if type(era) is not str:
                raise ValueError("explicit matching civilization era required")
            research_rows = eras.research_rows(era)
        definitions.append(
            ReplayCivilizationDefinition(
                index,
                name.encode("utf8"),
                json.dumps(
                    fields, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode("utf8"),
                research_rows,
            )
        )
    return ReplayCivilizationData(
        tuple(definitions),
        hashlib.sha256(raw).hexdigest(),
        len(entries),
        None if eras is None else eras.source_sha256,
    )


def build_replay_civilization_registry(
    memory: ReplayMemory,
    data: ReplayCivilizationData,
    *,
    writer_family: int,
    calls: ReplayTaskRebuildCalls,
) -> ReplayCivilizationRegistry:
    """Build populated engine indices with actual numeric/name insertion bodies.

    Family1 uses numeric06c0/name9730; family2 uses0680/9720. Source query selector0
    intentionally mixes those families and is not silently normalized. Fixed
    globals must be unoccupied; this fresh initialization does not reset a live
    registry. The caller separately supplies its real descriptor/Game profile.

    Record+8 refcount, +14 ID, +58 DEString and linkage+1b0 are backed. All other
    record fields stay undefined, except optional source-backed research rows
    at +138/+140/+148 copied through actual140f92070. No original674/840
    constructor/writer binding
    is supplied. Native lifecycle, full record/class identity and World restore
    require further data/implementation. Reached comparisons and insertion calls
    are real effects or failures, preserving prior writes on failure.
    """
    if (
        not isinstance(memory, ReplayMemory)
        or not isinstance(data, ReplayCivilizationData)
        or type(writer_family) is not int
        or writer_family not in (1, 2)
        or not isinstance(calls, ReplayTaskRebuildCalls)
    ):
        raise ValueError("owned memory/data, explicit family1/2 and actual providers required")
    numeric = 0x143DB06C0 if writer_family == 1 else 0x143DB0680
    names = 0x1442E9730 if writer_family == 1 else 0x1442E9720
    nil = numeric + 0x20
    # Sparse fixed backing defines only source-required fields; padding stays absent.
    memory.map_bytes(numeric, bytes(4))
    memory.map_bytes(numeric + 8, nil.to_bytes(8, "little"))
    memory.map_bytes(nil, bytes(4))
    sentinel = memory.allocate(0x40)
    for offset in (0, 8, 16):
        memory.write(sentinel + offset, 8, sentinel)
    memory.write(sentinel + 0x18, 2, 0x0101)
    memory.map_bytes(names, sentinel.to_bytes(8, "little") + bytes(8))
    records, nodes = [], []
    for definition in data.definitions:
        record = memory.allocate(0x1D0)
        records.append(record)
        memory.write(record + 8, 4, 0)
        memory.write(record + 0x14, 4, definition.ordinal)
        pointer = memory.allocate(len(definition.data_name) + 1)
        memory.write_bytes(pointer, definition.data_name + b"\0")
        for offset, value in (
            (0, pointer),
            (8, len(definition.data_name)),
            (16, len(definition.data_name) + 1),
        ):
            memory.write(record + 0x58 + offset, 8, value)
        if definition.research_rows is not None:
            # Engine data projection only: temporary descriptor backing feeds
            # the real row-copy body; no full native constructor is substituted.
            rows = definition.research_rows
            with ExitStack() as locals_:
                descriptor = bytearray(24)
                local = locals_.enter_context(memory.bind_local(memoryview(descriptor)))
                if rows:
                    source = locals_.enter_context(memory.bind_local(memoryview(bytearray(rows))))
                    memory.write(local, 8, source)
                    memory.write(local + 8, 8, source + len(rows))
                    memory.write(local + 16, 8, source + len(rows))
                _call(calls, 0x140F92070, (record + 0x138, local))
        _call(calls, 0x140F6AE70, (numeric, record))
        # The source writer searches for an equivalent name before linking it.
        parent, candidate, direction = sentinel, sentinel, 0
        node = memory.read(sentinel + 8, 8)
        while not memory.read(node + 0x19, 1):
            less = _call(calls, 0x140A162A0, (node + 0x20, record + 0x58), width=1)
            if not less:
                candidate = node
            parent = node
            direction = int(not less)
            node = memory.read(node if direction else node + 16, 8)
        if not memory.read(candidate + 0x19, 1) and not _call(
            calls,
            0x140A162A0,
            (record + 0x58, candidate + 0x20),
            width=1,
        ):
            continue  # First equivalent name survives; every numeric ID still exists.
        node = memory.allocate(0x40)
        nodes.append(node)
        for offset in (0, 8, 16):
            memory.write(node + offset, 8, sentinel)
        memory.write(node + 0x18, 2, 0)
        name_pointer = memory.allocate(len(definition.data_name) + 1)
        memory.write_bytes(name_pointer, definition.data_name + b"\0")
        for offset, value in (
            (0, name_pointer),
            (8, len(definition.data_name)),
            (16, len(definition.data_name) + 1),
        ):
            memory.write(node + 0x20 + offset, 8, value)
        memory.write(node + 0x38, 4, definition.ordinal)
        descriptor = bytearray(
            parent.to_bytes(8, "little") + direction.to_bytes(4, "little") + bytes(4)
        )
        with memory.bind_local(memoryview(descriptor)) as local:
            _call(calls, 0x140F6B790, (names, local, node), width=8)
    return ReplayCivilizationRegistry(
        writer_family, numeric, names, sentinel, tuple(records), tuple(nodes), data
    )
