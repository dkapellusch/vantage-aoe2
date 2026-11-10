"""The ``cade_api`` state schema: model ids, field ids, names and wire types.

``cade_schema.json`` was derived once from CaptureAge 1.26's generated patch
tables (see ``docs/design/cade-patch-decode.md`` §6); it holds only facts --
which model has which numbered field, what it is called and how wide it is on
the wire. Everything that interprets the stream lives in
:mod:`vantage.patch`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from importlib import resources
from typing import Any


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field of one model."""

    fid: int
    name: str
    kind: str  # scalar | object | map | array | scalar_array
    wire: str  # scalar wire type ('' for containers of objects)
    model: int | None  # declared model of object/map/array elements
    contiguous_model: int | None  # model a RESIZE fills new slots with


class Schema:
    """Indexed view of ``cade_schema.json``."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._names: dict[int, str] = {}
        self._fields: dict[int, dict[int, FieldSpec]] = {}
        self._by_name: dict[int, dict[str, int]] = {}
        for mid, m in data["models"].items():
            mt = int(mid)
            self._names[mt] = m["name"]
            specs = {
                int(fid): FieldSpec(
                    fid=int(fid),
                    name=f["name"],
                    kind=f["kind"],
                    wire=f.get("type", ""),
                    model=f.get("model"),
                    contiguous_model=f.get("contiguous_model"),
                )
                for fid, f in m["fields"].items()
            }
            self._fields[mt] = specs
            self._by_name[mt] = {s.name: s.fid for s in specs.values()}

    def name(self, model: int) -> str:
        return self._names.get(model, f"Model{model}")

    def model_id(self, name: str) -> int:
        for mt, n in self._names.items():
            if n == name:
                return mt
        raise KeyError(name)

    def field(self, model: int, fid: int) -> FieldSpec | None:
        return self._fields.get(model, {}).get(fid)

    def fields(self, model: int) -> dict[int, FieldSpec]:
        return self._fields.get(model, {})

    def fid(self, model: int, name: str) -> int:
        """Field id of ``name`` on ``model`` (raises ``KeyError`` if absent)."""
        return self._by_name[model][name]

    @cached_property
    def _subtypes(self) -> dict[int, list[int]]:
        """Models whose field table is a strict superset of each model's."""
        out: dict[int, list[int]] = {}
        for base, bf in self._fields.items():
            names = {(f.fid, f.name) for f in bf.values()}
            subs = [
                mt
                for mt, mf in self._fields.items()
                if mt != base and names < {(f.fid, f.name) for f in mf.values()}
            ]
            out[base] = sorted(subs, key=lambda mt: len(self._fields[mt]))
        return out

    def narrow(
        self,
        model: int,
        fid: int,
        kinds: frozenset[str] | None = None,
        seen: Iterable[int] = (),
    ) -> int | None:
        """Smallest subtype of ``model`` declaring ``fid`` (of one of ``kinds``).

        Only lenient decoding needs this: a placeholder's concrete model is
        unknown, and subtypes disagree on what a high field id means (field 23
        is a scalar on ``DoppleEntity`` but an object on ``BuildingEntity``).
        Candidates must also declare every field id in ``seen``.
        """
        need = set(seen)
        for mt in self._subtypes.get(model, []):
            table = self._fields[mt]
            spec = table.get(fid)
            if spec is not None and (kinds is None or spec.kind in kinds) and need <= table.keys():
                return mt
        return None


def load() -> Schema:
    text = resources.files("vantage").joinpath("cade_schema.json").read_text()
    return Schema(json.loads(text))


SCHEMA = load()
