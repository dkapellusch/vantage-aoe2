"""Source-backed research display rows from an explicitly resolved eras asset.

140f930a0/140f91d40 select TechDisplayOverrides; 140f90370 writes five DWORDs.
See civilization-era-rows-static-source-v1. This is a data projection, not a
native JSON-loader binding or proof of a replay's build/mod asset selection.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from typing import cast

_FIELDS = ("TechId", "NameId", "IconId", "DescriptionId", "ExtendedDescriptionId")
_DEFAULTS = (-1, -2, -1, -2, -2)


@dataclass(frozen=True, slots=True)
class ReplayEraDefinition:
    name: str
    research_rows: bytes

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name or "\0" in self.name:
            raise ValueError("explicit nonempty era name without NUL required")
        if type(self.research_rows) is not bytes or len(self.research_rows) % 20:
            raise ValueError("complete twenty-byte era research rows required")


@dataclass(frozen=True, slots=True)
class ReplayEraData:
    definitions: tuple[ReplayEraDefinition, ...]
    source_sha256: str

    def __post_init__(self) -> None:
        if type(self.definitions) is not tuple or any(
            not isinstance(row, ReplayEraDefinition) for row in self.definitions
        ):
            raise ValueError("ordered era definitions required")
        if (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_sha256)
        ):
            raise ValueError("explicit lowercase era source SHA256 required")

    def research_rows(self, name: str) -> bytes:
        """Admit an explicit exact match; the first matching source row wins.

        Missing/unknown civilization era selection is outside this projection;
        the original loader's fallback descriptors are not inferred here.
        """
        if type(name) is not str:
            raise ValueError("explicit matching civilization era required")
        for definition in self.definitions:
            if definition.name == name:
                return definition.research_rows
        raise ValueError(f"civilization era {name!r} has no admitted exact match")


def read_replay_era_data(raw: bytes) -> ReplayEraData:
    """Project ordered array/object rows with signed32 integer fields only.

    Missing TechDisplayOverrides uses the source-initialized empty vector.
    A present empty array is also empty; null and other wrong types refuse.
    Boolean, floating, out-of-range and diagnostic JSON conversions are outside
    the finite admitted domain. Unused semantic fields do not affect these rows.
    """
    if type(raw) is not bytes:
        raise ValueError("explicit era JSON bytes required")
    document: object = json.loads(raw)
    if not isinstance(document, list):
        raise ValueError("era JSON root must be an array")
    definitions = []
    for row in cast(list[object], document):
        if not isinstance(row, dict):
            raise ValueError("era row must be an object")
        fields = cast(dict[str, object], row)
        name = fields.get("Name")
        if type(name) is not str:
            raise ValueError("era row requires Name string")
        overrides = fields.get("TechDisplayOverrides", [])
        if not isinstance(overrides, list):
            raise ValueError("present TechDisplayOverrides must be an array")
        encoded = bytearray()
        for override in cast(list[object], overrides):
            if not isinstance(override, dict):
                raise ValueError("research override must be an object")
            values = []
            for key, default in zip(_FIELDS, _DEFAULTS, strict=True):
                value = override.get(key, default)
                if type(value) is not int or not -(1 << 31) <= value < 1 << 31:
                    raise ValueError("research override fields require signed32 integers")
                values.append(value)
            encoded.extend(struct.pack("<5i", *values))
        definitions.append(ReplayEraDefinition(name, bytes(encoded)))
    return ReplayEraData(tuple(definitions), hashlib.sha256(raw).hexdigest())
