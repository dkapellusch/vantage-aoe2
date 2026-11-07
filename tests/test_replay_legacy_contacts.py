"""Unchanged native legacy contact geometry and bounded contact-buffer writes."""

from __future__ import annotations

import gzip
import json
import struct
from functools import cache
from pathlib import Path

import pytest

from vantage import replay_legacy_contacts as legacy

FIXTURE = Path(__file__).parent / "fixtures/native_legacy_segment_contacts_17312.json.gz"


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def quad(*values: float) -> tuple[int, int, int, int]:
    assert len(values) == 4
    return tuple(map(bits, values))


@cache
def native():
    data = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    assert data["rea_evidence_id"] == (
        "ev_dacd5cf9cf82363cc1c41a7ea073bf84647dd78d0417e19d627a70550e11d4f8"
    )
    assert data["rea_native_exit"] == {"code": 0, "reason": "exited"}
    assert data["original_corpus_sha256"] == (
        "57e1ce0a79d359e1ee25ae3f41f0604ed85f2e289937b0be5df6d8bc81720988"
    )
    assert data["original_instructions_changed"] is False
    assert data["executable_holes"] == "INT3"
    assert data["unmapped_other_image_pages"] is True
    assert data["mxcsr"] == 0x1F80
    assert len(data["inputs"]) == len(data["native"]) == 17312
    return data


@pytest.mark.parametrize("mode", range(5))
def test_all_unchanged_original_native_geometry_and_contact_bytes(mode):
    corpus = native()
    observations = 0
    for ordinal, (row, expected) in enumerate(zip(corpus["inputs"], corpus["native"], strict=True)):
        if row[0] != mode:
            continue
        _, expand, emit, capacity, count, identifier = row[:6]
        bounds, segment, edge, radius = (
            tuple(row[6:10]),
            tuple(row[10:14]),
            tuple(row[14:18]),
            row[18],
        )
        buffer = bytes([0xA5]) * (capacity * 24)
        object_id = struct.unpack("<i", struct.pack("<I", identifier))[0]
        if mode < 2:
            result = legacy.legacy_segment_contacts(
                bounds,
                segment,
                shape="rectangle" if mode == 0 else "type5",
                expand=bool(expand),
                expansion_bits=radius,
                emit_contacts=bool(emit),
                entry_token=corpus["entry_token"],
                object_id=object_id,
                contact_buffer=buffer,
                contact_count=count,
            )
            actual = int(result.hit), result.contact_count, result.contact_buffer.hex()
        elif mode == 2:
            output = bytearray(buffer)
            hit, count = legacy._edge(
                bounds, segment, edge, bool(emit), corpus["entry_token"], object_id, output, count
            )
            actual = int(hit), count, bytes(output).hex()
        elif mode == 3:
            actual = int(legacy.legacy_segments_intersect(segment, edge)), count, buffer.hex()
        else:
            orientation = legacy._orientation(segment[:2], segment[2:], edge[:2])
            assert orientation & 0xFFFFFFFF == expected["result"], ordinal
            actual = orientation & 0xFF, count, buffer.hex()
        assert actual == (expected["al"], expected["count"], expected["records_hex"]), ordinal
        observations += 1
    assert observations == (6200, 6198, 1638, 1638, 1638)[mode]


def test_native_contact_points_repeat_entry_diagonal_and_preserve_record_tails():
    result = legacy.legacy_segment_contacts(
        quad(0, 0, 1, 1),
        quad(-1, 0.5, 2, 0.5),
        emit_contacts=True,
        entry_token=0x6000000100,
        object_id=-1,
        contact_buffer=b"\xa5" * 96,
    )
    assert result.hit and result.contact_count == 2
    # Native uses the complete entry diagonal for each hit, producing this same
    # interior point twice; these are not generic edge-intersection coordinates.
    for i in range(2):
        assert struct.unpack_from("<QiII", result.contact_buffer, i * 24) == (
            0x6000000100,
            -1,
            bits(0.5),
            bits(0.5),
        )
        assert result.contact_buffer[i * 24 + 20 : (i + 1) * 24] == b"\xa5" * 4
    assert result.contact_buffer[48:] == b"\xa5" * 48


def test_native_collinear_emission_preserves_negative_indefinite_nan_words():
    result = legacy.legacy_segment_contacts(
        quad(0, 0, 1, 1),
        quad(-1, -1, 2, 2),
        emit_contacts=True,
        contact_buffer=b"\xa5" * 96,
    )
    assert result.hit and result.contact_count == 4
    for i in range(4):
        assert struct.unpack_from("<II", result.contact_buffer, i * 24 + 12) == (
            0xFFC00000,
            0xFFC00000,
        )


def test_inside_endpoint_hits_without_emitting_and_reversed_shapes_remain_distinct():
    segment, buffer = quad(0.25, 0.25, 0.75, 0.75), b"\xa5" * 96
    normal = legacy.legacy_segment_contacts(
        quad(0, 0, 1, 1), segment, emit_contacts=True, contact_buffer=buffer
    )
    rectangle = legacy.legacy_segment_contacts(quad(1, 1, 0, 0), segment)
    type5 = legacy.legacy_segment_contacts(quad(1, 1, 0, 0), segment, shape="type5")
    assert normal.hit and normal.contact_count == 0 and normal.contact_buffer == buffer
    assert rectangle.hit and not type5.hit


def test_full_buffer_hits_without_overwriting_existing_records():
    buffer = bytes(range(48))
    result = legacy.legacy_segment_contacts(
        quad(0, 0, 1, 1),
        quad(-1, 0.5, 2, 0.5),
        emit_contacts=True,
        contact_count=2,
        contact_buffer=buffer,
    )
    assert result.hit and result.contact_count == 2 and result.contact_buffer == buffer


@pytest.mark.parametrize(
    "invalid",
    [
        dict(bounds=(0, 0, 0x7F800000, 0)),
        dict(bounds=(0, 0, 0x7FC01234, 0)),
        dict(segment=(0, 0, bits(65537), 0)),
        dict(segment=(0, 0, True, 0)),
        dict(segment=[0, 0, 0, 0]),
        dict(expansion_bits=bits(-0.3)),
        dict(expansion_bits=bits(4097)),
        dict(shape="unknown"),
        dict(expand=1),
        dict(emit_contacts=1),
        dict(entry_token=1 << 64),
        dict(object_id=1 << 31),
        dict(contact_buffer=b"\0" * 23),
        dict(contact_buffer=b"\0" * (65 * 24)),
        dict(contact_count=-1),
        dict(contact_count=1),
    ],
)
def test_unsupported_profile_rejects_without_mutating_supplied_bytes(invalid):
    args = dict(bounds=quad(0, 0, 1, 1), segment=quad(-1, 0.5, 2, 0.5))
    args.update(invalid)
    with pytest.raises(ValueError):
        legacy.legacy_segment_contacts(**args)


def test_intersection_public_api_rejects_nonfinite_or_mutable_segments():
    with pytest.raises(ValueError):
        legacy.legacy_segments_intersect(quad(0, 0, 1, 1), (0, 0, 0xFF800000, 0))
    with pytest.raises(ValueError):
        legacy.legacy_segments_intersect([0, 0, 0, 0], quad(0, 0, 1, 1))
