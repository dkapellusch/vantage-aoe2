from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from vantage.native_conversion import pin
from vantage.native_player_attributes import (
    NATIVE_FUNCTION_VA,
    WRITER_VA,
    AttributeProjectionError,
    generate_attribute_mapping,
    mapping_from_asm,
    mapping_from_c,
    native_helper,
    prepare_attribute_candidate,
)


def _witnesses(tmp_path):
    c = tmp_path / "original.c"
    c.write_text(
        "\n".join(f"if (*param_2 < {i + 1}) {{}} FUN_142596e40(*param_1,{i});" for i in range(253))
    )
    records, code = [], bytearray()

    def emit(raw):
        address = NATIVE_FUNCTION_VA + len(code)
        records.append(f"{address:x}\t{raw.hex()}\tINTENTIONALLY WRONG MNEMONIC")
        code.extend(raw)

    for op, value in [
        (0xBE, 0x6AE24D3352F04511),
        (0xBF, 0xC22D6B496D833977),
        (0xBC, 0x042AC42976FCCEF5),
        (0xBD, 0xA9834B738A7DD167),
    ]:
        emit(bytes([0x49, op]) + struct.pack("<Q", value))
    for index in range(253):
        emit(
            (b"\x83\x3a\x00" if index == 0 else b"\x83\x3f" + bytes([index]))
            if index < 128
            else b"\x81\x3f" + struct.pack("<i", index)
        )
        emit(b"\x33\xd2" if index == 0 else bytes([0xB2, index]))
        emit(b"\xe8" + struct.pack("<i", WRITER_VA - (NATIVE_FUNCTION_VA + len(code) + 5)))
    asm = tmp_path / "original.asm.tsv"
    asm.write_text("\n".join(records) + "\n")
    rva = NATIVE_FUNCTION_VA - 0x140000000
    data = bytearray(512 + len(code))
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 1)
    struct.pack_into("<H", data, 0x94, 240)
    struct.pack_into("<H", data, 0x98, 0x20B)
    struct.pack_into("<Q", data, 0x98 + 24, 0x140000000)
    section = 0x98 + 240
    data[section : section + 5] = b".text"
    struct.pack_into("<IIII", data, section + 8, len(code), rva, len(code), 512)
    struct.pack_into("<I", data, section + 36, 0x60000020)
    data[512:] = code
    image = tmp_path / "image.dll"
    image.write_bytes(data)
    return c, asm, image


def test_independent_bytes_decode_ignores_mnemonic_text_and_checks_entire_image_span(tmp_path):
    c, asm, image = _witnesses(tmp_path)
    result = generate_attribute_mapping(c, asm, image)
    assert len(result["fields"]) == 253
    assert (
        result["mapping_independently_agrees"]
        and result["all_instruction_bytes_match_runtime_image"]
    )
    assert result["fields"][252]["native_index"] == 252
    assert result["fields"][18]["name"] == "unitsKilled"
    data = bytearray(image.read_bytes())
    data[-1] ^= 1
    image.write_bytes(data)
    with pytest.raises(AttributeProjectionError, match="instruction bytes"):
        generate_attribute_mapping(c, asm, image)


def test_c_and_asm_mapping_disagreement_is_rejected(tmp_path):
    c, asm, image = _witnesses(tmp_path)
    c.write_text(c.read_text().replace("param_2 < 19", "param_2 < 20"))
    with pytest.raises(AttributeProjectionError, match="disagreement"):
        generate_attribute_mapping(c, asm, image)


def test_asm_gap_and_missing_field_rejected(tmp_path):
    c, asm, _image = _witnesses(tmp_path)
    text = asm.read_text()
    lines = text.splitlines()
    lines[1] = lines[1].replace(lines[1].split("\t")[0], "14187fcff")
    with pytest.raises(AttributeProjectionError, match="gap"):
        mapping_from_asm("\n".join(lines))
    with pytest.raises(AttributeProjectionError, match="writer"):
        mapping_from_c(
            c.read_text().replace("FUN_142596e40(*param_1,252)", "DIFFERENT(*param_1,252)")
        )


def test_passive_helper_retains_indices_and_explicit_availability_bounds(tmp_path):
    result = generate_attribute_mapping(*_witnesses(tmp_path))
    helper = native_helper(result)
    assert "EXT_ATTRIBUTE_INDICES{{0,1,2" in helper
    assert "EXT_ATTRIBUTE_INDICES.size()" in helper
    assert "VirtualQuery" in helper and "PAGE_GUARD" in helper
    assert "null" in helper and "read_bounds" in helper
    assert "write_word" not in helper and "VirtualProtect" not in helper


def test_candidate_preserves_original_helpers_and_function_prefix(tmp_path):
    mapping = generate_attribute_mapping(*_witnesses(tmp_path))
    source = tmp_path / "source"
    source.mkdir()
    players = source / "native_players.inc"
    players.write_text("original helper")
    host = tmp_path / "host.cpp.in"
    host.write_text(
        "static void original() {}\nint wmain(int argc, wchar_t** argv) {\n"
        + "\n".join(
            f"emit_native_entity_frame({x});"
            for x in ["0", "INPUT_FIRST_SYNC_TIME", "second_time", "advanced_time"]
        )
        + "\n}\n"
    )
    profile = tmp_path / "source-profile.json"
    profile.write_text(
        json.dumps(
            {
                "source_root": str(source),
                "host": pin(host),
                "sources": [{"relative": players.name, "pin": pin(players)}],
            }
        )
    )
    runtime = tmp_path / "runtime-profile.json"
    runtime.write_text(json.dumps({"staging_profile": pin(profile)}))
    result = prepare_attribute_candidate(mapping, profile, runtime, tmp_path / "candidate")
    assert result["original_native_players_unchanged"] and result["additional_call_sites"] == 4
    candidate = Path(result["host"]["path"]).read_text()
    assert candidate.startswith(
        'static void original() {}\n#include "native_player_attributes.inc"\n\nint wmain'
    )
    assert candidate.count("emit_extended_player_attributes(") == 4
    assert host.read_text().count("emit_extended_player_attributes(") == 0


def _capture(tmp_path, mapping, *, count=253, second_zero=True):
    fields = [r["native_index"] for r in mapping["fields"]]
    schema = {
        "stage": "vantage_player_attributes_schema_v1",
        "version": 1,
        "field_ids": list(range(253)),
        "native_indices": fields,
        "wire": "raw_f32_bits_or_null",
        "native_control_or_state_writes": False,
    }
    rows = [schema]
    for time, value in [(0, 2.0), (1000, 0.0)] if second_zero else [(0, 2.0)]:
        bits = [0 if count > index else None for index in fields]
        bits[18] = struct.unpack("<I", struct.pack("<f", value))[0]
        rows.append(
            {"stage": "native_player_frame", "time_ms": time, "players": [[0] * 18], "removed": []}
        )
        rows.append(
            {
                "stage": "vantage_player_attributes_frame_v1",
                "time_ms": time,
                "kind": "snapshot" if not time else "delta",
                "player_count": 1,
                "players": [[0, count, bits]],
                "read_bounds": [[0, "10", "20", min(count, max(fields) + 1) * 8]],
            }
        )
    path = tmp_path / "capture.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def test_availability_null_and_observed_zero_are_distinct(tmp_path):
    from vantage.native_player_attributes import attribute_frames

    mapping = generate_attribute_mapping(*_witnesses(tmp_path))
    events = list(attribute_frames(_capture(tmp_path, mapping, count=252), mapping))
    assert events[0]["players"][0]["bits"][252] is None
    assert events[1]["players"][0]["bits"][18] == 0
    assert events[1]["players"][0]["bits"][252] is None


def test_mapped_maximum_read_span_and_underreported_bounds_rejected(tmp_path):
    from vantage.native_player_attributes import attribute_frames

    mapping = generate_attribute_mapping(*_witnesses(tmp_path))
    mapping["fields"][246]["native_index"] = 563
    helper = native_helper(mapping)
    assert "static_cast<unsigned>(count),564u" in helper
    path = _capture(tmp_path, mapping, count=601)
    text = path.read_text().replace("4512", "2280")
    path.write_text(text)
    with pytest.raises(AttributeProjectionError, match="read span"):
        list(attribute_frames(path, mapping))


def test_enrichment_preserves_base_prefix_and_updates_observed_zero(tmp_path):
    from vantage.frames import Frame, RecordingWriter, read_frames
    from vantage.native_player_attributes import enrich_recording
    from vantage.patch import Patcher

    mapping = generate_attribute_mapping(*_witnesses(tmp_path))
    capture = _capture(tmp_path, mapping)
    patch = bytes([4, 0, 1, 8, 2, 5]) + struct.pack("<i", 0) + bytes([4, 2, 8])
    for field in [0, 1, 2, 3, 4, 6, 11, 30, 32]:
        patch += bytes([2, field]) + struct.pack("<I", 0)
    patch += bytes([1, 1, 1])
    base = tmp_path / "base.vrec"
    with RecordingWriter(base) as writer:
        writer.write(Frame(0, patch))
        writer.write(Frame(1000, b""))
    output = tmp_path / "expanded.vrec"
    result = enrich_recording(base, capture, mapping, output)
    assert (
        result["new_attribute_fields"] == 244
        and result["all_original_patch_prefixes_and_envelopes_preserved"]
    )
    state = Patcher()
    values = []
    for frame in read_frames(output):
        state.apply(frame.patch)
        values.append(state.root.get(0).get(2)[0].get(2).get(18))
    assert values == [2.0, 0.0]
    assert next(read_frames(output)).patch.startswith(patch)


def test_unavailable_values_cannot_be_published_as_zero_in_existing_ui(tmp_path):
    from vantage.frames import Frame, RecordingWriter
    from vantage.native_player_attributes import enrich_recording

    mapping = generate_attribute_mapping(*_witnesses(tmp_path))
    capture = _capture(tmp_path, mapping, count=252)
    base = tmp_path / "base.vrec"
    with RecordingWriter(base) as writer:
        writer.write(Frame(0, b""))
    output = tmp_path / "expanded.vrec"
    with pytest.raises(AttributeProjectionError, match="unavailable values cannot"):
        enrich_recording(base, capture, mapping, output)
    assert not output.exists()


def test_nonempty_reverse_patch_never_publishes_qualified_recording(tmp_path):
    from vantage.frames import Frame, RecordingWriter
    from vantage.native_player_attributes import enrich_recording

    mapping = generate_attribute_mapping(*_witnesses(tmp_path))
    capture = _capture(tmp_path, mapping)
    base = tmp_path / "base.vrec"
    with RecordingWriter(base) as writer:
        writer.write(Frame(0, b"", reverse=b"\x00"))
    output = tmp_path / "expanded.vrec"
    with pytest.raises(AttributeProjectionError, match="reverse"):
        enrich_recording(base, capture, mapping, output)
    assert not output.exists()


def test_reference_absence_is_unavailable_and_filename_does_not_authenticate(tmp_path):
    from vantage.frames import Frame, RecordingWriter
    from vantage.native_player_attributes import compare_attribute_reference

    mapping = generate_attribute_mapping(*_witnesses(tmp_path))
    capture = _capture(tmp_path, mapping)
    patch = (
        bytes([4, 0, 1, 8, 2, 5])
        + struct.pack("<i", 0)
        + bytes([4, 2, 8, 2, 18])
        + struct.pack("<f", 2.0)
        + bytes([1, 1, 1])
    )
    reference = tmp_path / "reference.vrec"
    with RecordingWriter(reference, {"source": "live-replay", "replay": "hint-only"}) as writer:
        writer.write(Frame(0, patch))
    result = compare_attribute_reference(capture, mapping, reference)
    assert result["counts"]["available_comparisons"] == 1
    assert result["counts"]["reference_field_unavailable"] == 252
    assert result["counts"].get("differences", 0) == 0
    assert (
        not result["replay_identity_authenticated"]
        and not result["independent_reference_gate_passed"]
    )
