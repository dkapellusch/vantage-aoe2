"""Bounded comparison of retained game/native observations; never runs a target.

NDJSON contract: one header, then strictly increasing clocked snapshots. Fields
carry a shared semantic name and wire encoding. Missing fields remain unavailable.
Positive entity IDs are join candidates, not proof of allocation equivalence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from .native_compare import canonical, decode

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TYPE_CHECKING, Any


FORMAT = "vantage-reference-observations-v1"
ENTITY_FIELDS = {
    "owner": (2, 1),
    "master": (1, 2),
    "x_bits": (3, 4),
    "y_bits": (4, 5),
    "z_bits": (5, 6),
    "hp_bits": (12, 7),
}
FIELD_TYPES = {
    name: ("float32_bits" if name.endswith("_bits") else "int32") for name in ENTITY_FIELDS
}
PHASES = {"unknown", "before_world_update", "after_world_update", "after_publication"}


class ReferenceError(ValueError):
    """Unusable or incomparable observation evidence."""


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ReferenceError(message)


def pin(path: Any) -> Any:
    path = Path(path).resolve(strict=True)
    before = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    require(
        (before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns),
        "Input changed while hashing",
    )
    return {"path": str(path), "bytes": after.st_size, "sha256": digest}


def header(
    source: Path,
    replay_sha256: str,
    producer: str,
    association: str,
    *,
    fields: Any = None,
    provenance: Any = None,
) -> Any:
    require(re.fullmatch(r"[0-9a-f]{64}", replay_sha256) is not None, "Invalid replay digest")
    require(producer in {"game", "native", "synthetic"}, "Unknown producer")
    require(association in {"authenticated", "inferred", "synthetic"}, "Unknown association")
    return {
        "format": FORMAT,
        "replay_sha256": replay_sha256,
        "replay_association": association,
        "producer": producer,
        "source": pin(source),
        "fields": fields or FIELD_TYPES,
        "provenance": provenance or {},
        "entity_identity": "positive_id_join_candidate",
        "missing_fields": "unavailable_never_implicit_zero",
    }


class Observations:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.pin = pin(self.path)
        with self.path.open("rb") as stream:
            self.header = decode(stream.readline())
        h = self.header
        require(h.get("format") == FORMAT, "Unknown observation contract")
        require(
            re.fullmatch(r"[0-9a-f]{64}", h.get("replay_sha256", "")) is not None,
            "Missing replay identity",
        )
        require(h.get("producer") in {"game", "native", "synthetic"}, "Unknown producer")
        require(
            h.get("replay_association") in {"authenticated", "inferred", "synthetic"},
            "Missing replay association strength",
        )
        require(type(h.get("fields")) is dict and h["fields"], "Missing field semantics")
        require(
            type(h.get("source")) is dict
            and re.fullmatch(r"[0-9a-f]{64}", h["source"].get("sha256", "")),
            "Missing source provenance",
        )
        self.count = 0
        self.last = -1

    def __iter__(
        self,
    ) -> Any:
        stream = self.path.open("rb")
        stream.readline()
        try:
            for raw in stream:
                row = decode(raw)
                require(type(row) is dict, "Observation must be an object")
                clock = row.get("time_ms")
                require(
                    type(clock) is int and clock >= 0 and clock > self.last,
                    "Observation clocks must strictly increase",
                )
                self.last = clock
                require(row.get("phase") in PHASES, "Missing publication phase")
                require(type(row.get("entities")) is dict, "Missing entities")
                require(type(row.get("commands", [])) is list, "Invalid commands")
                for key, fields in row["entities"].items():
                    require(re.fullmatch(r"[1-9][0-9]*", key), "Only stable positive IDs join")
                    require(
                        type(fields) is dict and set(fields) <= self.header["fields"].keys(),
                        "Undeclared entity field",
                    )
                    for name, value in fields.items():
                        encoding = self.header["fields"][name]
                        require(
                            encoding in {"int32", "float32_bits", "bool", "string"},
                            "Unsupported field encoding",
                        )
                        valid = (
                            (type(value) is int and -(1 << 31) <= value < (1 << 31))
                            if encoding == "int32"
                            else (type(value) is int and 0 <= value < (1 << 32))
                            if encoding == "float32_bits"
                            else type(value) is (bool if encoding == "bool" else str)
                        )
                        require(valid, f"Invalid field value: {name}")
                self.count += 1
                yield row
        finally:
            stream.close()

    def unchanged(self) -> None:
        require(pin(self.path) == self.pin, "Observation input changed during comparison")


def compare(reference_path: Path, native_path: Path, *, example_limit: Any = 12) -> dict[Any, Any]:
    """Merge exact clocks; retain bounded first-difference witnesses and coverage."""
    require(type(example_limit) is int and 1 <= example_limit <= 100, "Invalid example bound")
    left, right = Observations(reference_path), Observations(native_path)
    require(
        left.header["replay_sha256"] == right.header["replay_sha256"], "Replay identity differs"
    )
    fields = sorted(
        k for k, v in left.header["fields"].items() if right.header["fields"].get(k) == v
    )
    require(fields, "No fields with shared semantics and encoding")
    authenticated = all(x.header["replay_association"] == "authenticated" for x in (left, right))
    independent_game = {left.header["producer"], right.header["producer"]} == {"game", "native"}
    counts: Counter[Any] = Counter()
    available: Counter[Any] = Counter()
    absent: Counter[Any] = Counter()
    first = confirmed = preceding_match = None
    li, ri = iter(left), iter(right)
    a, b = next(li, None), next(ri, None)
    while a is not None and b is not None:
        if a["time_ms"] != b["time_ms"]:
            if a["time_ms"] < b["time_ms"]:
                counts["reference_unjoined_clocks"] += 1
                a = next(li, None)
            else:
                counts["native_unjoined_clocks"] += 1
                b = next(ri, None)
            continue
        counts["shared_clocks"] += 1
        same_phase = a["phase"] == b["phase"] != "unknown"
        counts["known_equal_phase_clocks" if same_phase else "phase_uncertain_clocks"] += 1
        ae, be = a["entities"], b["entities"]
        witnesses: list[Any] = []
        differences, comparisons = 0, 0
        for eid in sorted(ae.keys() & be.keys(), key=int):
            counts["joined_entities"] += 1
            for name in fields:
                if name not in ae[eid] or name not in be[eid]:
                    absent[name] += 1
                    continue
                available[name] += 1
                comparisons += 1
                if canonical(ae[eid][name]) != canonical(be[eid][name]):
                    differences += 1
                    if len(witnesses) < example_limit:
                        witnesses.append(
                            {
                                "entity_id": int(eid),
                                "field": name,
                                "reference": ae[eid][name],
                                "native": be[eid][name],
                            }
                        )
        counts["reference_only_entities"] += len(ae.keys() - be.keys())
        counts["native_only_entities"] += len(be.keys() - ae.keys())
        counts["field_comparisons"] += comparisons
        counts["field_differences"] += differences
        if differences:
            observation = {
                "time_ms": a["time_ms"],
                "differences": differences,
                "examples": witnesses,
                "preceding_matching_observation": preceding_match,
                "reference_phase": a["phase"],
                "native_phase": b["phase"],
                "reference_only_ids": sorted(map(int, ae.keys() - be.keys()))[:example_limit],
                "native_only_ids": sorted(map(int, be.keys() - ae.keys()))[:example_limit],
                "reference_commands": a.get("commands", [])[:example_limit],
                "native_commands": b.get("commands", [])[:example_limit],
                "classification": (
                    "comparable_published_field_difference"
                    if same_phase
                    else "publication_phase_ambiguous_difference"
                ),
            }
            if first is None:
                first = observation
            if confirmed is None and same_phase and authenticated and independent_game:
                confirmed = observation
        elif comparisons and ae.keys() == be.keys():
            preceding_match = {
                "time_ms": a["time_ms"],
                "field_comparisons": comparisons,
                "phase_known_equal": same_phase,
                "scope": "shared_available_fields_only",
            }
            counts["shared_field_matching_clocks"] += 1
        a, b = next(li, None), next(ri, None)
    # Consume tails to check monotonicity and capture all coverage gaps.
    while a is not None:
        counts["reference_unjoined_clocks"] += 1
        a = next(li, None)
    while b is not None:
        counts["native_unjoined_clocks"] += 1
        b = next(ri, None)
    left.unchanged()
    right.unchanged()
    return {
        "format": "vantage-reference-difference-v1",
        "status": (
            "published_field_difference_observed"
            if first
            else "available_shared_fields_equal_only"
            if counts["field_comparisons"]
            else "no_comparable_observations"
        ),
        "replay_sha256": left.header["replay_sha256"],
        "reference": {"observations": left.pin, "header": left.header, "frames": left.count},
        "native": {"observations": right.pin, "header": right.header, "frames": right.count},
        "shared_fields": fields,
        "incomparable_fields": sorted(
            (left.header["fields"].keys() | right.header["fields"].keys()) - set(fields)
        ),
        "counts": dict(counts),
        "available_comparisons": dict(available),
        "unavailable_field_pairs": dict(absent),
        "first_observable_difference": first,
        "first_phase_aligned_difference_with_authenticated_replay": confirmed,
        "reference_identity_authenticated": authenticated,
        "independent_game_reference": independent_game,
        "simulation_accuracy_proven": False,
        "limits": [
            "Only exact shared clocks and declared comparable fields are compared",
            "Missing fields are unavailable; membership is reported without inferring lifecycle",
            "Positive IDs alone do not authenticate allocation identity across executions",
            "Unknown publication phases cannot establish a state mismatch",
            "Published projection differences alone do not establish checksum cause",
            "VREC torn tails are ignored by its reader; imported observations are bounded evidence",
        ],
    }


def _write(
    path: Path,
    meta: Any,
    rows: Any,
) -> None:
    with Path(path).open("x") as stream:
        stream.write(json.dumps(meta, sort_keys=True) + "\n")
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    require(pin(meta["source"]["path"]) == meta["source"], "Source mutated during import")


def export_vrec(
    source: Path,
    output: Path,
    *,
    replay_sha256: Any,
    producer: Any = "game",
    association: Any = "inferred",
    phase: Any = "unknown",
    start_ms: Any = 0,
    end_ms: Any = None,
    provenance: Any = None,
) -> None:
    """Decode every patch from zero; emit only fields actually present in the tree."""
    from . import world as W
    from .frames import read_frames, read_header
    from .patch import Node, Patcher

    require(phase in PHASES, "Unknown phase")
    meta = header(
        source,
        replay_sha256,
        producer,
        association,
        provenance={"vrec_header": read_header(source), **(provenance or {})},
    )

    def rows() -> Any:
        patcher = Patcher()
        for frame in read_frames(source):
            if end_ms is not None and frame.time > end_ms:
                break
            patcher.apply(frame.patch)
            if frame.time < start_ms:
                continue
            world: Any = W.world_of(patcher.root)
            require(isinstance(world, Node), "Missing decoded world")
            entities = {}
            for eid, node in W.entities_of(world).items():
                if eid <= 0:
                    continue
                values = {}
                for name, (fid, _) in ENTITY_FIELDS.items():
                    if fid in node.fields and node.fields[fid] is not None:
                        value = node.fields[fid]
                        values[name] = (
                            struct.unpack("<I", struct.pack("<f", value))[0]
                            if name.endswith("_bits")
                            else value
                        )
                entities[str(eid)] = values
            yield {
                "time_ms": frame.time,
                "phase": phase,
                "entities": entities,
                "commands": frame.commands,
                "skipped": frame.skipped,
            }

    _write(output, meta, rows())


def export_native(
    source: Path,
    output: Path,
    *,
    replay_sha256: Any,
    association: Any = "authenticated",
    phase: Any = "unknown",
    start_ms: Any = 0,
    end_ms: Any = None,
    times: Any = None,
    provenance: Any = None,
) -> None:
    """Replay retained native entity snapshot/deltas from zero, without a native worker."""
    require(phase in PHASES, "Unknown phase")
    meta = header(source, replay_sha256, "native", association, provenance=provenance)

    def rows() -> Any:
        entities: dict[Any, Any] = {}
        previous, seen_snapshot = -1, False
        with Path(source).open("rb") as stream:
            for raw in stream:
                raw = re.sub(rb"^(?:[0-9]+ ResignPlayer)+", b"", raw)
                if b'"native_entity_frame"' not in raw:
                    continue
                row = decode(raw)
                if row.get("stage") != "native_entity_frame":
                    continue
                clock = row["time_ms"]
                require(type(clock) is int and clock > previous, "Native clocks do not increase")
                previous = clock
                if end_ms is not None and clock > end_ms:
                    break
                if not seen_snapshot:
                    require(row["kind"] == "snapshot", "Native import must start at snapshot")
                    seen_snapshot = True
                else:
                    require(row["kind"] == "delta", "Unexpected second snapshot")
                for eid in row["removed"]:
                    entities.pop(str(eid), None)
                for item in row["entities"]:
                    require(len(item) == 8, "Unknown native entity layout")
                    if item[0] > 0:
                        entities[str(item[0])] = {
                            name: item[index] for name, (_, index) in ENTITY_FIELDS.items()
                        }
                if clock >= start_ms and (times is None or clock in times):
                    yield {"time_ms": clock, "phase": phase, "entities": entities.copy()}
        require(seen_snapshot, "No native entity snapshot")

    _write(output, meta, rows())


def main(argv: Any = None) -> Any:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cmp = sub.add_parser("compare")
    cmp.add_argument("reference", type=Path)
    cmp.add_argument("native", type=Path)
    cmp.add_argument("--output", type=Path, required=True)
    for kind in ("import-vrec", "import-native"):
        cmd = sub.add_parser(kind)
        cmd.add_argument("source", type=Path)
        cmd.add_argument("--output", type=Path, required=True)
        cmd.add_argument("--replay-sha256", required=True)
        cmd.add_argument(
            "--association", choices=("authenticated", "inferred", "synthetic"), default="inferred"
        )
        cmd.add_argument("--phase", choices=sorted(PHASES), default="unknown")
        cmd.add_argument("--start-ms", type=int, default=0)
        cmd.add_argument("--end-ms", type=int)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if command == "compare":
        output = args.pop("output")
        result = compare(args.pop("reference"), args.pop("native"))
        with output.open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    else:
        source, output = args.pop("source"), args.pop("output")
        (export_vrec if command == "import-vrec" else export_native)(source, output, **args)
    return 0
