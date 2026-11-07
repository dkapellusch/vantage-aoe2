"""Portable byte-contiguous native replay sections reused by integration tests."""

from __future__ import annotations

import gzip
import json
import zipfile
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _gzip(name: str):
    return json.loads(gzip.decompress((FIXTURES / name).read_bytes()))


@lru_cache(maxsize=2)
def restore_prefix_case(sample: str):
    header = next(
        c
        for c in _gzip("native_saved_file_headers_54800.json.gz")["cases"]
        if c["sample"] == sample
    )
    with zipfile.ZipFile(FIXTURES / "native_saved_world_rules_54800.zip") as archive:
        rule_case = next(
            c for c in json.loads(archive.read("manifest.json"))["cases"] if c["sample"] == sample
        )
        rules = gzip.decompress(archive.read(rule_case["fixture_member"]))
    prefix = next(
        c
        for c in json.loads((FIXTURES / "native_saved_world_prefix_54800.json").read_text())[
            "cases"
        ]
        if c["sample"] == sample
    )
    saved_map = next(
        c for c in _gzip("native_saved_maps_54800.json.gz")["cases"] if c["sample"] == sample
    )
    players = [
        c
        for c in _gzip("native_saved_initial_players_54800.json.gz")["cases"]
        if c["sample"] == sample
    ]
    restore_fixture = _gzip("native_saved_player_restore_54800.json.gz")
    restores = [c for c in restore_fixture["cases"] if c["sample"] == sample]
    spans = [
        (0, header["end_offset"]),
        (rule_case["outer_world"]["offset"], rule_case["outer_world"]["end_offset"]),
        (prefix["offset"], prefix["end_offset"]),
        (saved_map["offset"], saved_map["end_offset"]),
        (saved_map["post_map"]["offset"], saved_map["post_map"]["end_offset"]),
        *((p["start"], p["end"]) for p in players),
        *((p["start"], p["end"]) for p in restores),
    ]
    for first, second in pairwise(spans):
        assert first[1] == second[0]
    raw = (
        bytes.fromhex(header["raw_hex"])
        + rules
        + b"".join(
            bytes.fromhex(c["raw_hex"])
            for c in (prefix, saved_map, saved_map["post_map"], *players)
        )
        + b"".join(bytes.fromhex(restore_fixture["bodies"][p["body_sha256"]]) for p in restores)
    )
    assert len(raw) == spans[-1][1]
    return raw, spans, players, restores


@lru_cache(maxsize=2)
def complete_world_case(sample: str):
    """Compose previously proven adjacent spans; never search for section markers."""
    prefix = restore_prefix_case(sample)[0]
    bases = _gzip("native_scenario_bases_159.json.gz")
    base = next(c for c in bases["cases"] if c["sample"] == sample)
    extensions = _gzip("native_saved_scenario_extensions_54800.json.gz")
    extension = next(c for c in extensions["cases"] if c["sample"] == sample)
    tails = _gzip("native_saved_world_tails_54800.json.gz")
    tail = next(c for c in tails["cases"] if c["sample"] == sample)
    base_raw = bytes.fromhex(base["raw_hex"])
    extension_raw = bytes.fromhex(extensions["bodies"][extension["body_sha256"]])
    tail_raw = bytes.fromhex(tails["bodies"][tail["body_sha256"]])
    assert len(prefix) == extension["offset"] - len(base_raw)
    assert extension["end_offset"] == tail["offset"]
    raw = prefix + base_raw + extension_raw + tail_raw
    assert len(raw) == tail["end_offset"] == tail["inflated_bytes"]
    return raw, tail
