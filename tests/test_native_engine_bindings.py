"""Static PE and generated-binding controls; never call the generated roles."""

import copy
import json
import struct

import pytest

from vantage import native_engine_bindings as N


def image(
    path,
    *,
    base=0x140000000,
    shift=0,
    duplicate=False,
    missing=False,
    wrong_call=False,
    executable=True,
):
    raw = bytearray(0x1200)
    raw[:2] = b"MZ"
    struct.pack_into("<I", raw, 0x3C, 0x80)
    raw[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", raw, 0x84, 0x8664, 1)
    struct.pack_into("<H", raw, 0x94, 240)
    optional = 0x98
    struct.pack_into("<H", raw, optional, 0x20B)
    struct.pack_into("<Q", raw, optional + 24, base)
    section = optional + 240
    raw[section : section + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", raw, section + 8, 0x1000, 0x1000, 0x1000, 0x200)
    struct.pack_into("<I", raw, section + 36, 0x60000020 if executable else 0x40000040)
    caller, callee = 0x1100 + shift, 0x1200 + shift
    call = b"\xe8" + struct.pack("<i", callee - caller - 5 + int(wrong_call))
    caller_bytes = call + bytes.fromhex("4883ec28488bc14883c428c3")
    callee_bytes = bytes.fromhex("488b81280200004885c0c3")
    raw[caller - 0x1000 + 0x200 : caller - 0x1000 + 0x200 + len(caller_bytes)] = caller_bytes
    if not missing:
        raw[callee - 0x1000 + 0x200 : callee - 0x1000 + 0x200 + len(callee_bytes)] = callee_bytes
    if duplicate:
        raw[0x600 : 0x600 + len(caller_bytes)] = caller_bytes
    path.write_bytes(raw)
    return path


def manifest(tmp_path):
    baseline = image(tmp_path / "baseline.exe")
    pe = N.PE(baseline)
    semantic = tmp_path / "review.json"
    semantic.write_text(json.dumps({"synthetic": True, "calling": "fixture only"}))
    roles = []
    for name, rva, length, pattern in [
        ("step", 0x1100, 16, "e8 ?? ?? ?? ?? 48 83 ec 28 48 8b c1 48 83 c4 28"),
        ("clock", 0x1200, 11, "48 8b 81 28 02 00 00 48 85 c0 c3"),
    ]:
        source = tmp_path / (name + ".bin")
        source.write_bytes(pe.region(rva, length)[1])
        roles.append(
            {
                "name": name,
                "pattern": pattern,
                "search_rva": [0x1000, 0x1800],
                "source_witness": {
                    "pin": N.pin(source),
                    "start_va": pe.base + rva,
                    "format": "raw",
                    "span_sha256": N.pin(source)["sha256"],
                },
                "semantic_witnesses": [N.pin(semantic)],
                "assumptions": {
                    "calling_convention": "synthetic Windows x64",
                    "startup": "synthetic only",
                    "layout": {"clock": 0x228},
                },
            }
        )
    return {
        "schema": N.SCHEMA,
        "build_identity": {"fixture": True},
        "baseline_image": pe.pin,
        "roles": roles,
        "usable_code_views": [
            {
                "image_sha256": pe.pin["sha256"],
                "kind": "synthetic_fixture",
                "provenance": N.pin(semantic),
            }
        ],
        "relationships": [
            {"kind": "direct_rel32_call", "caller": "step", "callee": "clock", "offset": 0}
        ],
        "unsupported_bindings": ["all real game bindings"],
    }


def target_view(m, path):
    m["usable_code_views"].append(
        {
            "image_sha256": N.pin(path)["sha256"],
            "kind": "synthetic_fixture",
            "provenance": m["roles"][0]["semantic_witnesses"][0],
        }
    )


def test_known_image_exact_matches_and_candidate_header(tmp_path):
    m = manifest(tmp_path)
    result = N.discover(m, m["baseline_image"]["path"])
    assert result == N.discover(m, m["baseline_image"]["path"])
    assert result["status"] == "static_candidate_table_ready"
    assert [x["candidates"][0]["rva"] for x in result["bindings"]] == [0x1100, 0x1200]
    assert result["relationships"][0]["status"] == "matched"
    assert "VANTAGE_RVA_STEP UINT64_C(0x1100)" in N.generate_header(result)
    assert result["executable_qualified"] is False
    assert result["real_second_build_demonstrated"] is False


def test_synthetic_aslr_rebase_and_function_movement_are_not_second_game_build(tmp_path):
    m = manifest(tmp_path)
    rebased = image(tmp_path / "rebased.exe", base=0x180000000)
    target_view(m, rebased)
    first = N.discover(m, rebased)
    assert first["bindings"][0]["candidates"][0]["rva"] == 0x1100
    assert first["bindings"][0]["candidates"][0]["preferred_va"] == 0x180001100
    moved = image(tmp_path / "moved.exe", base=0x180000000, shift=0x80)
    target_view(m, moved)
    second = N.discover(m, moved)
    assert second["status"] == "static_candidate_table_ready"
    assert [x["candidates"][0]["rva"] for x in second["bindings"]] == [0x1180, 0x1280]
    assert second["relationships"][0]["status"] == "matched"
    assert second["real_second_build_demonstrated"] is False


@pytest.mark.parametrize(
    "change,status",
    [("duplicate", "ambiguous"), ("missing", "missing"), ("wrong_call", "unique_candidate")],
)
def test_missing_ambiguous_and_relationship_failures_refuse_generation(tmp_path, change, status):
    m = manifest(tmp_path)
    changed = image(tmp_path / "changed.exe", **{change: True})
    target_view(m, changed)
    result = N.discover(m, changed)
    assert result["status"] == "rejected_unresolved_bindings"
    assert result["bindings"][1 if change == "missing" else 0]["status"] == status
    if change == "wrong_call":
        assert result["relationships"][0]["status"] == "relationship_mismatch"
    with pytest.raises(N.BindingError, match="Unresolved"):
        N.generate_header(result)


@pytest.mark.parametrize(
    "change",
    [
        "unknown_view",
        "changed_source",
        "nonexecutable",
        "too_broad",
        "missing_assumptions",
        "false_source",
        "weak_signature",
    ],
)
def test_untrusted_inputs_fail_closed(tmp_path, change):
    m = manifest(tmp_path)
    path = m["baseline_image"]["path"]
    if change == "unknown_view":
        m["usable_code_views"] = []
    if change == "changed_source":
        N.Path(m["roles"][0]["source_witness"]["pin"]["path"]).write_bytes(b"changed")
    if change == "nonexecutable":
        path = image(tmp_path / "data.exe", executable=False)
        target_view(m, path)
    if change == "too_broad":
        m["roles"][0]["search_rva"] = [0x1000, 0x200000]
    if change == "missing_assumptions":
        del m["roles"][0]["assumptions"]["layout"]
    if change == "false_source":
        m["roles"][0]["source_witness"]["start_va"] += 1
    if change == "weak_signature":
        m["roles"][0]["pattern"] = "?? " * 20
    with pytest.raises(N.BindingError):
        N.discover(m, path)


def test_tsv_byte_witness_must_be_contiguous_and_equal_baseline(tmp_path):
    m = manifest(tmp_path)
    witness = copy.deepcopy(m["roles"][1]["source_witness"])
    raw = N.source_bytes(witness)
    path = tmp_path / "clock.asm.tsv"
    path.write_text(
        f"{witness['start_va']:x}\t{raw[:7].hex()}\tmov rax,[rcx+0x228]\n"
        f"{witness['start_va'] + 7:x}\t{raw[7:].hex()}\ttest/ret\n"
    )
    witness.update(pin=N.pin(path), format="asm_tsv")
    assert N.source_bytes(witness) == raw
    witness["start_va"] += 1
    with pytest.raises(N.BindingError, match="gap"):
        N.source_bytes(witness)


def test_direct_call_relationship_disambiguates_identical_getter_bodies(tmp_path):
    m = manifest(tmp_path)
    path = image(tmp_path / "duplicate_getter.exe")
    raw = bytearray(path.read_bytes())
    raw[0x600:0x60B] = raw[0x400:0x40B]
    path.write_bytes(raw)
    target_view(m, path)
    result = N.discover(m, path)
    assert result["status"] == "static_candidate_table_ready"
    getter = result["bindings"][1]
    assert len(getter["unfiltered_candidates"]) == 2
    assert getter["candidates"][0]["rva"] == 0x1200
    assert getter["relationship_disambiguation"]["observed_target_rva"] == 0x1200


def test_unverified_target_can_report_diagnostic_candidates_but_publish_no_header(tmp_path):
    m = manifest(tmp_path)
    path = image(tmp_path / "unknown.exe", base=0x180000000)
    result = N.discover(m, path, diagnostic_unverified=True)
    assert result["status"] == "unverified_code_view_diagnostic_only"
    assert all(x["status"] == "unique_candidate" for x in result["bindings"])
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(m))
    header = tmp_path / "rejected.h"
    with pytest.raises(N.BindingError, match="Unresolved"):
        N.main(
            [
                "--manifest",
                str(manifest_path),
                "--image",
                str(path),
                "--output",
                str(tmp_path / "diagnostic.json"),
                "--header",
                str(header),
                "--diagnostic-unverified",
            ]
        )
    assert not header.exists()
