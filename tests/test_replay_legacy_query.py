from __future__ import annotations

import gzip
import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from vantage.replay_legacy_query import (
    LegacyQueryIndex,
    LegacyQueryLevel,
    LegacyQueryRecord,
    UnsupportedLegacyQuery,
    legacy_query_segment,
)

FIXTURE = Path(__file__).parent / "fixtures/native_legacy_query_25.json.gz"
RAW = FIXTURE.read_bytes()
DATA = json.loads(gzip.decompress(RAW))


def index_for(context: dict) -> LegacyQueryIndex:
    return LegacyQueryIndex(
        context["width"],
        context["height"],
        tuple(context["lookup_words"]),
        tuple(LegacyQueryLevel(*row) for row in context["levels"]),
        tuple(tuple(bucket) for bucket in context["buckets"]),
        tuple(
            LegacyQueryRecord(
                row["token"], row["kind"], row["flags"], row["id_or_terrain"], tuple(row["bounds"])
            )
            for row in context["records"]
        ),
    )


INDICES = tuple(index_for(context) for context in DATA["contexts"])


def query(row: dict, **changes):
    case = row["input"]
    arguments = dict(
        radius_bits=case["radius"],
        expand=bool(case["expand"]),
        ignore_ids=tuple(case["ignore_ids"]),
        ignore_enabled=bool(case["ignore_enabled"]),
        emit_contacts=bool(case["emit"]),
        contact_count=case["initial_contacts"],
        contact_buffer=b"\xa5" * (case["contact_capacity"] * 24),
        collision_buffer=b"\xa5" * 200,
    )
    arguments.update(changes)
    return legacy_query_segment(INDICES[case["context"]], tuple(case["segment"]), **arguments)


def candidate_rows():
    return [row for row in DATA["cases"] if row["input"].get("name") == "conditional-v11-candidate"]


def test_fixture_binds_closed_original_code_and_address_free_observed_state():
    assert hashlib.sha256(RAW).hexdigest() == (
        "05caa1cec26d5903428ed935d2d76e9216d09d32605a7bbeb5a15750111bc6d3"
    )
    assert (
        DATA["evidence_id"] == "ev_85d67de756d18c9634db3cbc7101b9abb5164adc70039cbaa10dcc62aeda73dc"
    )
    assert not DATA["original_bodies_changed"] and not DATA["native_callbacks_executed"]
    assert DATA["canonical_address_free_state_sha256"] == (
        "b6f17aebc9a4119b13013c65e27fc8a51a12143bd11bfa1671f64bfc4e50007c"
    )
    assert len(DATA["cases"]) == 202
    assert [len(context["records"]) for context in DATA["contexts"][:2]] == [4205, 4209]
    assert all(len(context["buckets"]) == 1365 for context in DATA["contexts"])
    assert all(
        set(record) == {"token", "kind", "flags", "id_or_terrain", "bounds"}
        for context in DATA["contexts"]
        for record in context["records"]
    )


@pytest.mark.parametrize("context", range(6), ids=[row["name"] for row in DATA["contexts"]])
def test_original_native_full_ordered_buffers_and_manager_mutations(context):
    cases = [row for row in DATA["cases"] if row["input"]["context"] == context]
    assert cases
    for row in cases:
        result = query(row)
        expected = row["expected"]
        assert int(result.exhausted) == expected["al"], row["ordinal"]
        assert result.collision_count == expected["hits"], row["ordinal"]
        assert (struct.pack("<2I", 25, result.collision_count) + result.collision_buffer).hex() == (
            expected["collision_hex"]
        ), row["ordinal"]
        assert result.contact_count == expected["contact_count"], row["ordinal"]
        assert result.contact_buffer.hex() == expected["contacts_hex"], row["ordinal"]
        assert result.manager_flag_bytes.hex() == expected["manager_flags_hex"], row["ordinal"]
        assert result.manager_parameter_bytes.hex() == expected["manager_parameters_hex"], row[
            "ordinal"
        ]


def test_original_v11_candidate_ignores_self_and_has_no_other_geometry_contacts():
    rows = candidate_rows()
    assert len(rows) == 4
    assert DATA["later_candidate_confirmation"]["evidence_id"] == (
        "ev_d0cf24e32ea5518f70b5e70dfa6a30da9291dc4ab295718fbda7317e9ae8043b"
    )
    index = INDICES[1]
    for row in rows:
        assert row["input"]["segment"] == [1125946936, 1124102973, 1125947453, 1124102676]
        result = query(row)
        assert not result.exhausted and result.contact_count == 0
        if row["input"]["ignore_ids"]:
            assert result.collision_tokens == ()
        else:
            ids = {record.token: record.id_or_terrain for record in index.records}
            assert [ids[token] for token in result.collision_tokens] == [10449]
        # Self containment is a collision without an emitted edge point.
        assert result.contact_buffer == b"\xa5" * (64 * 24)
    assert not DATA["captured_state_is_game_call"]


def test_bucket_order_preserves_repeated_tokens_instead_of_deduplicating():
    rows = [row for row in DATA["cases"] if row["input"]["context"] == 4]
    duplicate = next(
        row for row in rows if len(set(query(row).collision_tokens)) < query(row).collision_count
    )
    result = query(duplicate)
    native = bytes.fromhex(duplicate["expected"]["collision_hex"])
    expected_tokens = tuple(
        value[0] for value in struct.iter_unpack("<Q", native[8 : 8 + result.collision_count * 8])
    )
    assert result.collision_tokens == expected_tokens
    assert len(set(result.collision_tokens)) < result.collision_count


def test_native_exhaustion_and_independent_contact_capacity_preserve_record_tails():
    row = next(
        row
        for row in DATA["cases"]
        if row["input"]["context"] == 3
        and row["expected"]["hits"] == 25
        and row["expected"]["contact_count"] == 4
    )
    result = query(row)
    assert result.exhausted and result.collision_count == 25 and result.contact_count == 4
    assert result.contact_buffer.hex() == row["expected"]["contacts_hex"]
    assert all(result.contact_buffer[i * 24 + 20 : (i + 1) * 24] == b"\xa5" * 4 for i in range(4))


@pytest.mark.parametrize(
    "changes",
    [
        {"flags": 0xB0},
        {"flags": 0x190},
        {"selector": 7},
        {"owner_id": 2},
        {"factor_bits": 0x40000000},
        {"terrain_insertion": True},
    ],
)
def test_unknown_call_branches_are_explicitly_unsupported(changes):
    with pytest.raises(UnsupportedLegacyQuery):
        query(candidate_rows()[0], **changes)


@pytest.mark.parametrize(
    "segment",
    [
        (0, 1, 1, 1),
        (0.1, 1, 1, 1),
        (1, 1, 200, 1),
        (1, 1, 199.9, 1),
        (-1, 1, 1, 1),
        (1, 0, 1, 1),
        (1, 1, 1, 200),
    ],
)
def test_border_queries_are_rejected_instead_of_fabricating_border_records(segment):
    words = tuple(struct.unpack("<I", struct.pack("<f", value))[0] for value in segment)
    with pytest.raises(UnsupportedLegacyQuery, match="border"):
        legacy_query_segment(INDICES[0], words, radius_bits=0x3E99999A)


@pytest.mark.parametrize(
    "change",
    [
        "lookup",
        "descriptor",
        "bucket-reference",
        "bucket-mutable",
        "duplicate-token",
        "extent",
    ],
)
def test_unproved_or_inconsistent_index_layout_is_rejected(change):
    index = INDICES[0]
    with pytest.raises(ValueError):
        if change == "lookup":
            replace(index, lookup_words=(4, *index.lookup_words[1:]))
        elif change == "descriptor":
            replace(index, levels=(replace(index.levels[0], base_index=1), *index.levels[1:]))
        elif change == "bucket-reference":
            replace(index, buckets=((len(index.records),), *index.buckets[1:]))
        elif change == "bucket-mutable":
            replace(index, buckets=([0], *index.buckets[1:]))
        elif change == "duplicate-token":
            replace(
                index,
                records=(
                    replace(index.records[0], token=index.records[1].token),
                    *index.records[1:],
                ),
            )
        else:
            replace(index, width=256)


@pytest.mark.parametrize(
    "changes",
    [
        {"radius_bits": 0x7FC00000},
        {"radius_bits": 0xBF800000},
        {"ignore_ids": (1 << 31,)},
        {"collision_buffer": bytes(24 * 8)},
        {"contact_buffer": b"x"},
        {"contact_count": 65},
        {"emit_contacts": 1},
    ],
)
def test_finite_profile_and_output_capacities_are_enforced(changes):
    with pytest.raises(ValueError):
        query(candidate_rows()[0], **changes)
