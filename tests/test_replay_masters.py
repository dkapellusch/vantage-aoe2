"""Native saved master bytes and independent initial spectator field values.

Original byte slices, hashes and inflated-header offsets are recorded in
artifacts/game-internals/2026-10-18-world-restore/master-layout/static-reader/report.json.
The bounded artifact comparison validates 3,876 complete static bodies across
both paired recordings. These cases keep ordinary, damaged, long-name and
inherited common bases as small regressions without requiring local captures.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import struct
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_binary import SaveDecodeError, SaveReader
from vantage.replay_masters import (
    SavedMaster,
    read_master,
    read_master_base,
    read_master_table,
    read_master_task,
)

_CASES: list[dict[str, Any]] = [
    {
        "offset": 4741429,
        "end_offset": 4741618,
        "raw_size": 189,
        "raw_sha256": "822e76ae4e5560e4ded8a965b8e47f6ed791ec1a4eb33f2cc1f0ae6d0a0d85db",
        "master_id": 59,
        "type_group": 10,
        "expected": {
            "saved_id": 59,
            "object_group": 7,
            "hp": 0,
            "string_id": 5401,
            "icon_id": 6,
            "radius_x": 0.5,
            "sprite_id": 2420,
        },
        "name": "FORAG",
        "resource_id": -2,
        "resource_string_hex": "00",
        "damage_sprites": [[2389, 33, 2], [2388, 66, 2]],
        "data": (
            "c$~9lum(eR21W)1u!mwG_~pd#|38=or5Ged85kHP85lSi<}<PZncOhR274w(h7!*IKyXO=ACP2($Up!C8en8"
            "#VPs?q<y2$};dEk3;9_NP^AB=#hiHH(U}8kl40Tfj%x(7n{{sMZDK3E"
        ),
    },
    {
        "offset": 5127271,
        "end_offset": 5127466,
        "raw_size": 195,
        "raw_sha256": "dd69897c8ffa9165ff0aff94772a40d9748a52d49b10cbf8df4d1bc9aa54ff3d",
        "master_id": 1089,
        "type_group": 10,
        "expected": {
            "saved_id": 1089,
            "object_group": 14,
            "hp": 500,
            "string_id": 5222,
            "icon_id": 60,
            "radius_x": 0.5,
            "sprite_id": 8570,
        },
        "name": "GRANARY",
        "resource_id": -2,
        "resource_string_hex": "00",
        "damage_sprites": [[8567, 25, 0], [8568, 50, 0], [8569, 75, 0]],
        "data": (
            "c${-&aRfs?1_p*Nj0_A19Doc4dkFsjAH+eU7}7)-82ls{7`Pa2v)V8)0U=bf!GVdHp-S;T82kfbMvx3YgEJ#"
            "YK)k;wI_;qA4F)J+Vq#`wVlG#dWT;RyVyIN~W=P;-XK)X4^m7b~gqQ(V#|$zY&WF0p!2!np{~rL?u{Tx"
        ),
    },
    {
        "offset": 5573671,
        "end_offset": 5573885,
        "raw_size": 214,
        "raw_sha256": "b9abcf4efef7636c9c78e48586af30ec98cc5a7fe16f3914f21a3dc29cd60c39",
        "master_id": 2380,
        "type_group": 10,
        "expected": {
            "saved_id": 2380,
            "object_group": 14,
            "hp": 1,
            "string_id": 421085,
            "icon_id": -1,
            "radius_x": 0.009999999776482582,
            "sprite_id": 15792,
        },
        "name": "Aura Quest Indicator (Gold and Shells)",
        "resource_id": -2,
        "resource_string_hex": "00",
        "damage_sprites": [],
        "data": (
            "c%1X$^Z`RY21XzR1Fq}JHXzKv@c%zp0F`36o5RMCA;rMJ4io{3F``H^Zm|6i2LFJV5h4Qt3|PQ_h6FA(2FKE"
            "(M1{c8)Z!8a&%Bh(<iwKvA_Wci{G1ep#Jm)R;EdFqoMKH>Q;<xxhhl`O{{dhkL)Z"
        ),
    },
    {
        "offset": 7003091,
        "end_offset": 7003272,
        "raw_size": 181,
        "raw_sha256": "93cad5abdc5c579f9cf817a38957faaf12e972e456aedaeda07741416737632c",
        "master_id": 112,
        "type_group": 10,
        "expected": {
            "saved_id": 112,
            "object_group": 30,
            "hp": 0,
            "string_id": 5316,
            "icon_id": -1,
            "radius_x": 1.0,
            "sprite_id": 1751,
        },
        "name": "FLARE",
        "resource_id": -2,
        "resource_string_hex": "00",
        "damage_sprites": [],
        "data": (
            "c$_O>C;&q_1_nk35O4tE273@@W#9p_A2=}l{|}adQVd5#7#P+_Kty0-a7o7NZ2$j*@IRm&BTNyJLKN_yA%Tm"
            "P!Oh1p$dw1#G$c(Bw?IT8?En7(_k=ax"
        ),
    },
    {
        "offset": 7819840,
        "end_offset": 7820048,
        "raw_size": 208,
        "raw_sha256": "8aa39a9e03fb6bcc552f4ef6cd9a04f71487a93278f889783e401174416395da",
        "master_id": 2476,
        "type_group": 10,
        "expected": {
            "saved_id": 2476,
            "object_group": 11,
            "hp": 0,
            "string_id": 0,
            "icon_id": -1,
            "radius_x": 0.0,
            "sprite_id": 16826,
        },
        "name": "Macedonian Command Post (Rubble)",
        "resource_id": -2,
        "resource_string_hex": "00",
        "damage_sprites": [],
        "data": (
            "c${0qxdsfm85kHDP=O9350ETyV)*|b%!g87P%I7+fs4TyjJq8FgTX%_W`rq1QiuZnGbC^+F!&}Wr>5lRWhUk"
            "+IOpf)Cg!Cm1mqW&C};$gCMD&hYVsgkgk;_Udk97{?>_*3(mos"
        ),
    },
    {
        "offset": 21151148,
        "end_offset": 21151343,
        "raw_size": 195,
        "raw_sha256": "abf1b340aa114b096f38d6638e0416638533f9c8b68e27dc9cfac7f4412a478e",
        "master_id": 1089,
        "type_group": 10,
        "expected": {
            "saved_id": 1089,
            "object_group": 14,
            "hp": 500,
            "string_id": 5222,
            "icon_id": 60,
            "radius_x": 0.5,
            "sprite_id": 8570,
        },
        "name": "GRANARY",
        "resource_id": -2,
        "resource_string_hex": "00",
        "damage_sprites": [[8567, 25, 0], [8568, 50, 0], [8569, 75, 0]],
        "data": (
            "c${-&aRfs?1_p*Nj0_A19Doc4dkFsjAH+eU7}7)-82ls{7+4r?v)V8)0U=bf!GVdHp-S;T82kfbMvx3YgEJ#"
            "YK)k;wI_;qA4F)J+Vq#`wVlG#dWT;RyVyIN~W=P;-XK)X4^m7b~gqQ(V#|$zY&WF0p!2!np{~rL<fj3Y"
        ),
    },
    {
        "offset": 20872226,
        "end_offset": 20872407,
        "raw_size": 181,
        "raw_sha256": "6d8622c1b52818d17f8a5237e5cf1e83be0c465d7ed5a6424264d93e9b4fb74a",
        "master_id": 201,
        "type_group": 10,
        "expected": {
            "saved_id": 201,
            "object_group": 30,
            "hp": 1,
            "string_id": 5651,
            "icon_id": -1,
            "radius_x": 1.0,
            "sprite_id": 5458,
        },
        "name": "FLR_R",
        "resource_id": -2,
        "resource_string_hex": "00",
        "damage_sprites": [],
        "data": (
            "c$_=Qa1spV7#J8C85kHG9DqcFJp}VGfWiO&$P|OH7z4v^Nr(tc3@*tSB>Mk92>%1hF~SrfDMSJP84|cy8Qgq"
            "=;)8gQO+(TIa|;99UH|_B0PA`+J^"
        ),
    },
    {
        "offset": 10909931,
        "end_offset": 10910118,
        "raw_size": 187,
        "raw_sha256": "a758990d08df95843449a78ea2ebae53b5a33ff8b5820f18d753a5f125cc11f6",
        "master_id": 0,
        "type_group": 70,
        "expected": {
            "saved_id": 0,
            "object_group": 11,
            "hp": 1,
            "string_id": 21090,
            "icon_id": -1,
            "radius_x": 0.0,
            "sprite_id": -1,
        },
        "name": "OLD-ACADEMY",
        "resource_id": -2,
        "resource_string_hex": "00",
        "damage_sprites": [],
        "data": (
            "c${NkfB<eFW&|-D7!ct9e=HP3QV;_}fjC42CdPoofPjBM%!n+&fCc<#NZ{gT@b_`ib#!)garKQvRf?q59*P-"
            "Y?En7(QQ$Vn"
        ),
    },
]


def _raw(case: dict[str, Any]) -> bytes:
    return zlib.decompress(base64.b85decode(case["data"]))


@pytest.mark.parametrize("case", _CASES, ids=lambda c: f"{c['offset']}-{c['name']}")
def test_real_master_bodies_match_independent_captured_fields(case: dict[str, Any]) -> None:
    raw = _raw(case)
    assert len(raw) == case["raw_size"]
    assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
    reader = SaveReader(b"prefix" + raw + b"derived", pos=6)
    master = read_master_base(reader, master_id=case["master_id"], type_group=case["type_group"])
    assert {
        "saved_id": master.saved_id,
        "object_group": master.object_group,
        "hp": master.hp,
        "string_id": master.string_id,
        "icon_id": master.icon_id,
        "radius_x": master.radius_x,
        "sprite_id": master.sprite_ids[0],
    } == case["expected"]
    assert master.master_id == case["master_id"]
    assert master.type_group == case["type_group"]
    assert master.name == case["name"]
    assert master.resource_id == case["resource_id"]
    assert master.resource_string_bytes == bytes.fromhex(case["resource_string_hex"])
    assert [(d.sprite_id, d.damage_percent, d.flags) for d in master.damage_sprites] == [
        tuple(d) for d in case["damage_sprites"]
    ]
    assert master.raw == b"".join(master.sections.values()) == raw
    assert master.offset == 6
    assert master.end_offset == reader.pos == 6 + case["end_offset"] - case["offset"]
    assert reader.take(7) == b"derived"


@pytest.mark.parametrize("case", [_CASES[0], _CASES[1], _CASES[-1]])
def test_every_truncation_rolls_back_to_common_base_start(case: dict[str, Any]) -> None:
    raw = _raw(case)
    for size in range(len(raw)):
        reader = SaveReader(b"prefix" + raw[:size], pos=6)
        with pytest.raises(SaveDecodeError):
            read_master_base(reader, type_group=case["type_group"])
        assert reader.pos == 6


def test_final_attribute_overrides_win_and_both_wire_occurrences_are_retained() -> None:
    raw = bytearray(_raw(_CASES[0]))
    # Native save 68.9 repeats type/flag fields in its final 44-byte block.
    # The initial berry record contains resource amount 125.0.
    struct.pack_into("<h", raw, 29, 6)
    struct.pack_into("<h", raw, len(raw) - 44, 7)
    raw[len(raw) - 38] = 9
    master = read_master_base(SaveReader(bytes(raw)))
    attr = master.attributes[0]
    assert (attr.type_id, attr.amount, attr.flags) == (7, 125.0, 9)
    assert master.fields[0xAA] == 7
    assert master.sections["member_aa.initial"] == struct.pack("<h", 6)
    assert master.sections["member_aa.final"] == struct.pack("<h", 7)
    assert struct.pack("<I", attr.amount_word) == struct.pack("<f", 125.0)


def test_native_resource_string_zero_length_omits_its_payload() -> None:
    raw = bytearray(_raw(_CASES[0]))
    # Resource substitution helper uses i32 ID, then u32 length at +93.
    assert raw[97] == 0
    struct.pack_into("<I", raw, 93, 0)
    del raw[97]
    reader = SaveReader(bytes(raw))
    master = read_master_base(reader)
    assert master.resource_string_bytes == b""
    assert master.name == "FORAG"
    assert reader.remaining == 0


def test_resource_id_does_not_control_whether_its_string_is_consumed() -> None:
    raw = bytearray(_raw(_CASES[0]))
    struct.pack_into("<i", raw, 89, 12345)
    master = read_master_base(SaveReader(bytes(raw)))
    assert master.resource_id == 12345
    assert master.resource_string_bytes == b"\0"
    assert master.name == "FORAG"


def test_invalid_native_resource_string_limit_rolls_back() -> None:
    raw = bytearray(_raw(_CASES[0]))
    struct.pack_into("<I", raw, 93, 0x2801)
    reader = SaveReader(b"prefix" + bytes(raw), pos=6)
    with pytest.raises(SaveDecodeError, match="resource string length") as error:
        read_master_base(reader)
    assert error.value.offset == 6 + 93
    assert reader.pos == 6


def test_invalid_de_name_marker_rolls_back() -> None:
    raw = bytearray(_raw(_CASES[0]))
    at = len(raw) - 44 - len("FORAG") - 4
    raw[at : at + 4] = b"bad!"
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError, match="DE string marker") as error:
        read_master_base(reader)
    assert error.value.offset == at
    assert reader.pos == 0


@pytest.mark.parametrize("version,kind", [(0x44E665, 10), (0x450000, 10), (0x44E666, 90)])
def test_unverified_version_or_factory_stops_before_reading(version: int, kind: int) -> None:
    reader = SaveReader(b"prefix" + _raw(_CASES[0]), pos=6, version=version)
    with pytest.raises(SaveDecodeError, match="unsupported master"):
        read_master_base(reader, type_group=kind)
    assert reader.pos == 6


def test_static_type_15_uses_same_native_common_reader() -> None:
    reader = SaveReader(_raw(_CASES[0]))
    # Shared native-reader call evidence, not a claim of a paired type-15 sample.
    master = read_master_base(reader, type_group=15)
    assert master.type_group == 15
    assert reader.remaining == 0


@lru_cache(maxsize=1)
def _table_fixture() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures/native_saved_master_tables_54800.json.gz"
    return json.loads(gzip.decompress(path.read_bytes()))  # type: ignore[no-any-return]


def _table_bytes(index: int = 0) -> bytes:
    fixture = _table_fixture()
    return bytes.fromhex(fixture["table_blobs_by_sha256"][fixture["samples"][index]["raw_sha256"]])


def _captured_master_values(master: SavedMaster) -> dict[str, Any]:
    base = master.base
    actual: dict[str, Any] = {
        "master_id": master.master_id,
        "type_group": master.type_group,
        "saved_id": base.saved_id,
        "object_group": base.object_group,
        "hp": base.hp,
        "string_id": base.string_id,
        "icon_id": base.icon_id,
        "radius_x": base.radius_x,
        "sprite_id": base.sprite_ids[0],
    }
    if master.type_group >= 50:
        actual["weapons"] = [list(row) for row in master.vectors[0x2B8]]
        actual["armor"] = [list(row) for row in master.vectors[0x2A8]]
        for name, offset in (("weapon_range", 0x2C8), ("reload", 0x2D8)):
            actual[name] = struct.unpack("<f", struct.pack("<I", master.fields[offset]))[0]
    if master.type_group in {70, 80}:
        actual["costs"] = [list(row[:3]) for row in master.vectors[0x320]]
        actual["train_building_ids"] = [row[1] for row in master.vectors[0x338]]
    return actual


@pytest.mark.parametrize("index", [0, 1], ids=["gaia-3p", "gaia-6p"])
def test_complete_gaia_tables_walk_without_searching_and_match_independent_fields(
    index: int,
) -> None:
    case = _table_fixture()["samples"][index]
    raw = _table_bytes(index)
    assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
    reader = SaveReader(b"prefix" + raw + b"\x0bvisibility", pos=6)
    table = read_master_table(reader)
    assert table.offset == 6
    assert table.end_offset == reader.pos == 6 + len(raw)
    assert reader.take(11) == b"\x0bvisibility"
    assert table.raw == raw
    assert table.count == len(table.presence) == 2750
    assert len(table.masters) == sum(bool(p) for p in table.presence) == 2693
    assert set(table.masters) == {row["master_id"] for row in case["expected"]}
    assert [_captured_master_values(master) for master in table.masters.values()] == case[
        "expected"
    ]
    assert len(raw) == 6 + 4 * table.count + sum(len(m.raw) + 3 for m in table.masters.values())
    for master in table.masters.values():
        assert master.raw == b"".join(master.sections.values())
    assert case["end_before_visibility_marker"] == [5713078, 11907432][index]


@pytest.mark.parametrize("position", [0, 1, 4, 11005, 11006, 11007, -1])
def test_truncated_master_table_restores_table_start(position: int) -> None:
    raw = _table_bytes()
    reader = SaveReader(b"prefix" + raw[:position], pos=6)
    with pytest.raises(SaveDecodeError):
        read_master_table(reader)
    assert reader.pos == 6


@pytest.mark.parametrize("position", [0, 11005, 11006, -1])
def test_invalid_table_markers_restore_table_start(position: int) -> None:
    raw = bytearray(_table_bytes())
    raw[position] = 99
    reader = SaveReader(b"prefix" + bytes(raw), pos=6)
    with pytest.raises(SaveDecodeError, match="expected marker"):
        read_master_table(reader)
    assert reader.pos == 6


def test_unknown_table_factory_does_not_scan_to_next_record() -> None:
    raw = bytearray(_table_bytes())
    raw[11007] = 90
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError, match="unsupported complete master type group 90"):
        read_master_table(reader)
    assert reader.pos == 0


def test_noncanonical_nonzero_presence_value_keeps_native_presence_semantics() -> None:
    raw = bytearray(_table_bytes())
    struct.pack_into("<i", raw, 5, 2)
    table = read_master_table(SaveReader(bytes(raw)))
    assert table.presence[0] == 2
    assert len(table.masters) == 2693


def test_impossible_presence_count_fails_before_allocating_or_walking_records() -> None:
    raw = bytearray(_table_bytes())
    struct.pack_into("<i", raw, 1, 0x7FFFFFFF)
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError, match="invalid array count"):
        read_master_table(reader)
    assert reader.pos == 0


@pytest.mark.parametrize("version", [0x44E665, 0x450000])
def test_table_version_guard_precedes_framing(version: int) -> None:
    reader = SaveReader(b"not a table", version=version)
    with pytest.raises(SaveDecodeError, match="unsupported master save version"):
        read_master_table(reader)
    assert reader.pos == 0


def test_inline_task_prefixes_match_all_thirty_independent_captured_task_fields() -> None:
    # These are exact through-Action slices of higher derived master records.
    # The task flags, task types and nonempty lists come from real saved data.
    native_members = {
        1: 0xA,
        2: 0xC,
        3: 0xE,
        4: 0x10,
        5: 0x12,
        6: 0x14,
        7: 0x15,
        8: 0x16,
        9: 0x18,
        10: 0x19,
        11: 0x1A,
        12: 0x20,
        13: 0x22,
        14: 0x24,
        15: 0x26,
        16: 0x28,
        17: 0x2C,
        18: 0x30,
        19: 0x1B,
        20: 0x1C,
        21: 0x34,
        22: 0x36,
        29: 0x38,
    }
    total = 0
    for case in _table_fixture()["task_prefix_samples"]:
        raw = bytes.fromhex(case["raw_hex"])
        assert hashlib.sha256(raw).hexdigest() == case["raw_sha256"]
        reader = SaveReader(raw + b"combat")
        master = read_master(reader, master_id=case["master_id"], type_group=40)
        assert reader.take(6) == b"combat"
        assert master.task_count == len(master.tasks) == case["task_count"]
        for task, oracle in zip(master.tasks, case["task_oracles"], strict=True):
            actual: dict[int, int | float] = {0: task.type_id}
            for fid, member in native_members.items():
                value = task.fields[member]
                actual[fid] = (
                    struct.unpack("<f", struct.pack("<I", value))[0]
                    if fid in {16, 17, 18, 20}
                    else value
                )
            actual.update({23 + i: sprite for i, sprite in enumerate(task.sprite_ids)})
            actual[27], actual[28] = task.fields[0x60], task.fields[0x78]
            assert actual == {int(fid): value for fid, value in oracle.items()}
            assert task.end_offset - task.offset == len(task.raw) == 69
            total += 1
        assert master.raw == raw == b"".join(master.sections.values())
    assert total > 100


def test_impossible_inline_task_count_rolls_back_the_entire_master() -> None:
    case = _table_fixture()["task_prefix_samples"][0]
    raw = bytearray.fromhex(case["raw_hex"])
    moving = read_master(SaveReader(bytes(raw)), type_group=30)
    count_offset = moving.end_offset + 13  # Three f32s and one task-flags byte.
    struct.pack_into("<h", raw, count_offset, 0x7FFF)
    reader = SaveReader(bytes(raw))
    with pytest.raises(SaveDecodeError, match="invalid master task count"):
        read_master(reader, type_group=40)
    assert reader.pos == 0


@pytest.mark.parametrize("version", [0x43E666, 0x44E666])
def test_public_task_reader_preserves_fields_and_leaves_next_bytes(version: int) -> None:
    case = _table_fixture()["task_prefix_samples"][0]
    master = read_master(SaveReader(bytes.fromhex(case["raw_hex"])), type_group=40)
    assert master.tasks
    for expected in master.tasks:
        reader = SaveReader(b"prefix" + expected.raw + b"next", 6, version=version)
        actual = read_master_task(reader)
        assert (actual.offset, actual.end_offset) == (6, 75)
        assert actual.type_id == expected.type_id
        assert actual.fields == expected.fields
        assert actual.sprite_ids == expected.sprite_ids
        assert actual.sound_numbers == expected.sound_numbers
        assert actual.raw == expected.raw
        assert reader.take(4) == b"next"


@pytest.mark.parametrize("version", [0x43E666, 0x44E666])
def test_public_task_reader_rolls_back_every_truncated_record(version: int) -> None:
    for size in range(69):
        reader = SaveReader(b"prefix" + bytes(size), 6, version=version)
        with pytest.raises(SaveDecodeError):
            read_master_task(reader)
        assert reader.pos == 6


@pytest.mark.parametrize("version", [0x43E665, 0x43E667, 0x44E665, 0x450000])
def test_public_task_reader_rejects_unmeasured_profiles_atomically(version: int) -> None:
    reader = SaveReader(b"prefix" + bytes(69), 6, version=version)
    with pytest.raises(SaveDecodeError, match="unsupported master-task version"):
        read_master_task(reader)
    assert reader.pos == 6
