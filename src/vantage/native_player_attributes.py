"""Source-bound full PlayerAttributes mapping and passive projection POC.

Retained original C and independently decoded instruction bytes must agree.
Generated native code only reads the owned worker and writes a separate stream.
Original V32 admission and all pre-existing projection fields remain mandatory.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .native_conversion import pin
from .native_engine_bindings import PE
from .schema import SCHEMA

if TYPE_CHECKING:
    from typing import TYPE_CHECKING


SCHEMA_NAME = "vantage_native_player_attributes_v1"
ORIGINAL_FIELDS = {0, 1, 2, 3, 4, 6, 11, 30, 32}
NATIVE_FUNCTION_VA = 0x14187FC90
WRITER_VA = 0x142596E40


class AttributeProjectionError(ValueError):
    pass


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AttributeProjectionError(message)


def mapping_from_c(text: str) -> list[dict[Any, Any]]:
    thresholds = list(re.finditer(r"if \(\*param_2 < (0x[0-9a-f]+|[0-9]+)\)", text))
    result = []
    for ordinal, match in enumerate(thresholds):
        end = thresholds[ordinal + 1].start() if ordinal + 1 < len(thresholds) else len(text)
        block = text[match.start() : end]
        writers = re.findall(r"FUN_142596e40\(\*param_1,(0x[0-9a-f]+|[0-9]+)\)", block)
        require(len(writers) == 1, "C field block must have exactly one writer")
        result.append(
            {
                "field_id": int(writers[0], 0),
                "native_index": int(match[1], 0) - 1,
                "c_line": text.count("\n", 0, match.start()) + 1,
            }
        )
    require(
        len(result) == 253 and [r["field_id"] for r in result] == list(range(253)),
        "C field coverage differs",
    )
    return result


def mapping_from_asm(text: str) -> tuple[list[dict[Any, Any]], bytes, list[dict[Any, Any]]]:
    """Interpret selected x86 opcodes from bytes; never use mnemonic text."""
    instructions, code = [], bytearray()
    for ordinal, text_line in enumerate(text.splitlines()):
        columns = text_line.split("\t")
        require(len(columns) >= 2, "Malformed instruction witness")
        address, raw = int(columns[0], 16), bytes.fromhex(columns[1])
        require(
            address == NATIVE_FUNCTION_VA + len(code) and raw, "Instruction witness gap or overlap"
        )
        instructions.append((address, raw, ordinal + 1))
        code.extend(raw)
    result, active_index, constants = [], None, []
    for ordinal, (address, raw, line) in enumerate(instructions):
        if raw[:2] in {b"\x83\x3f", b"\x83\x3a"} and len(raw) == 3:
            active_index = struct.unpack("<b", raw[2:])[0]
        elif raw[:2] == b"\x81\x3f" and len(raw) == 6:
            active_index = struct.unpack("<i", raw[2:])[0]
        if len(raw) == 10 and raw[:2] in {b"\x49\xbe", b"\x49\xbf", b"\x49\xbc", b"\x49\xbd"}:
            constants.append(
                {
                    "address": address,
                    "register_opcode": raw[:2].hex(),
                    "value": struct.unpack("<Q", raw[2:])[0],
                }
            )
        if (
            len(raw) != 5
            or raw[0] != 0xE8
            or address + 5 + struct.unpack("<i", raw[1:])[0] != WRITER_VA
        ):
            continue
        require(
            ordinal > 0 and active_index is not None and active_index >= 0,
            "ASM writer lacks count index",
        )
        previous = instructions[ordinal - 1][1]
        if previous == b"\x33\xd2":
            field = 0
        else:
            require(
                len(previous) == 2 and previous[0] == 0xB2,
                "Writer field is not independently decoded MOV DL/zero",
            )
            field = previous[1]
        result.append(
            {
                "field_id": field,
                "native_index": active_index,
                "asm_line": line,
                "writer_call_va": address,
                "writer_call_bytes": raw.hex(),
            }
        )
        active_index = None
    require(
        len(result) == 253 and [r["field_id"] for r in result] == list(range(253)),
        "ASM field coverage differs",
    )
    return result, bytes(code), constants


def generate_attribute_mapping(c_path: Path, asm_path: Path, image: Path) -> dict[Any, Any]:
    before = [pin(p) for p in (c_path, asm_path, image)]
    c_rows = mapping_from_c(c_path.read_text())
    asm_rows, code, constants = mapping_from_asm(asm_path.read_text())
    require(
        [(r["field_id"], r["native_index"]) for r in c_rows]
        == [(r["field_id"], r["native_index"]) for r in asm_rows],
        "C/ASM attribute mapping disagreement",
    )
    pe = PE(image)
    offset, actual, section = pe.region(
        NATIVE_FUNCTION_VA - 0x140000000, len(code), executable=True
    )
    require(actual == code, "Original serializer instruction bytes differ from runtime image")
    expected_constants = {
        "49be": 0x6AE24D3352F04511,
        "49bf": 0xC22D6B496D833977,
        "49bc": 0x042AC42976FCCEF5,
        "49bd": 0xA9834B738A7DD167,
    }
    require(
        {r["register_opcode"]: r["value"] for r in constants} == expected_constants,
        "Attribute decoder constants differ",
    )
    model = SCHEMA.model_id("PlayerAttributes")
    rows = []
    for c_row, asm_row in zip(c_rows, asm_rows, strict=True):
        spec = SCHEMA.field(model, c_row["field_id"])
        require(
            spec is not None and spec.kind == "scalar" and spec.wire == "Float",
            "Attribute wire schema differs",
        )
        assert spec is not None  # require() raised otherwise; narrows the type
        rows.append(
            dict(
                c_row,
                **{k: v for k, v in asm_row.items() if k not in c_row},
                name=spec.name,
                wire=spec.wire,
                preexisting=c_row["field_id"] in ORIGINAL_FIELDS,
            )
        )
    require([pin(p) for p in (c_path, asm_path, image)] == before, "Mapping inputs changed")
    return {
        "schema": SCHEMA_NAME,
        "version": 1,
        "sources": before,
        "original_function_va": NATIVE_FUNCTION_VA,
        "original_writer_va": WRITER_VA,
        "code_file_offset": offset,
        "code_section": section,
        "code_bytes": len(code),
        "code_sha256": hashlib.sha256(code).hexdigest(),
        "instruction_count": len(asm_path.read_text().splitlines()),
        "decoder_constants": constants,
        "fields": rows,
        "mapping_independently_agrees": True,
        "all_instruction_bytes_match_runtime_image": True,
        "native_execution": False,
        "semantic_names_source": pin(Path(__file__).with_name("cade_schema.json")),
        "limitations": [
            "Names come from the retained typed schema; no new field semantics are inferred.",
            "Matching serialization bytes proves mapping provenance, not simulation parity.",
        ],
    }


def native_helper(mapping: dict[Any, Any]) -> str:
    indices = ",".join(str(r["native_index"]) for r in mapping["fields"])
    schema = json.dumps(
        {
            "stage": "vantage_player_attributes_schema_v1",
            "version": 1,
            "field_ids": [r["field_id"] for r in mapping["fields"]],
            "native_indices": [r["native_index"] for r in mapping["fields"]],
            "wire": "raw_f32_bits_or_null",
            "unavailable": None,
            "native_control_or_state_writes": False,
        },
        separators=(",", ":"),
    )
    # JSON literal encoded with a C++ raw string whose delimiter is fixed and absent.
    return (
        r"""// Passive source-bound attributes; generated, no native writes/calls.
static constexpr std::array<unsigned,253> EXT_ATTRIBUTE_INDICES{{INDICES}};
struct ExtAttributeRow {
    unsigned count;
    std::array<std::uint32_t,253> bits{};
    std::array<bool,253> available{};
    bool operator==(const ExtAttributeRow&) const = default;
};
static std::map<unsigned,ExtAttributeRow> ext_attribute_previous;
static bool ext_attribute_schema_emitted=false;
static bool ext_attribute_readable(const BYTE* begin,std::size_t bytes) {
    if (!begin || !bytes) return false;
    const auto start=reinterpret_cast<std::uintptr_t>(begin);
    if (start>UINTPTR_MAX-bytes) return false;
    const auto end=start+bytes;
    auto cursor=start;
    while(cursor<end) {
        MEMORY_BASIC_INFORMATION info{};
        if (!VirtualQuery(reinterpret_cast<const void*>(cursor),&info,sizeof(info))
            || info.State!=MEM_COMMIT || (info.Protect&(PAGE_NOACCESS|PAGE_GUARD))) return false;
        const auto region=reinterpret_cast<std::uintptr_t>(info.BaseAddress);
        if (!info.RegionSize || region>UINTPTR_MAX-info.RegionSize) return false;
        const auto next=region+info.RegionSize;
        if (next<=cursor) return false;
        cursor=next;
    }
    return true;
}
static void emit_extended_player_attributes(DWORD time) {
    if(!ext_attribute_schema_emitted) {
        if(time) ExitProcess(881);
        std::puts(R"ATTR(SCHEMA_JSON)ATTR");
        ext_attribute_schema_emitted=true;
    }
    if(!ext_attribute_readable(diagnostic_world,0x778)) ExitProcess(882);
    const auto begin=read_word<const BYTE*>(diagnostic_world+0x768);
    const auto end=read_word<const BYTE*>(diagnostic_world+0x770);
    if(!begin || end<begin || (end-begin)%16 || end-begin>16*9
       || !ext_attribute_readable(begin,static_cast<std::size_t>(end-begin))) ExitProcess(883);
    std::map<unsigned,ExtAttributeRow> current;
    struct Bounds {unsigned id;const BYTE* player;const BYTE* cells;std::size_t bytes;};
    std::vector<Bounds> bounds;
    for(auto entry=begin;entry<end;entry+=16) {
        const auto player=read_word<const BYTE*>(entry);
        if(!ext_attribute_readable(player,0x64c)) ExitProcess(884);
        const auto id=read_word<DWORD>(player+0x648);
        const auto count=read_word<std::int32_t>(player+0x90);
        if(id>8 || id!=static_cast<unsigned>((entry-begin)/16) || current.count(id)
           || count<0 || count>65536) ExitProcess(885);
        const auto cells=read_word<const BYTE*>(player+0x98);
        const auto required=std::min<unsigned>(static_cast<unsigned>(count),MAX_NATIVE_READ_COUNTu)*8u;
        if(required && !ext_attribute_readable(cells,required)) ExitProcess(886);
        ExtAttributeRow row{};row.count=static_cast<unsigned>(count);
        for(unsigned i=0;i<EXT_ATTRIBUTE_INDICES.size();++i) {
            const auto index=EXT_ATTRIBUTE_INDICES[i];
            row.available[i]=static_cast<unsigned>(count)>index;
            if(row.available[i]) row.bits[i]=native_player_attribute_bits(player,index);
        }
        bounds.push_back({id,player,cells,required});
        current.emplace(id,row);
    }
    std::printf("{\"stage\":\"vantage_player_attributes_frame_v1\",\"time_ms\":%lu,\"kind\":\"%s\",\"player_count\":%llu,\"players\":[",
        static_cast<unsigned long>(time),ext_attribute_previous.empty()?"snapshot":"delta",
        static_cast<unsigned long long>(current.size()));
    bool first=true;
    for(const auto& entry:current) {
        const auto prior=ext_attribute_previous.find(entry.first);
        if(prior!=ext_attribute_previous.end() && prior->second==entry.second) continue;
        std::printf("%s[%u,%u,[",first?"":",",entry.first,entry.second.count);first=false;
        for(unsigned i=0;i<253;++i) {
            if(i)std::printf(",");
            if(entry.second.available[i])std::printf("%lu",static_cast<unsigned long>(entry.second.bits[i]));
            else std::printf("null");
        }
        std::printf("]]");
    }
    std::printf("],\"read_bounds\":[");first=true;
    for(const auto& b:bounds) {
        std::printf("%s[%u,\"%p\",\"%p\",%llu]",first?"":",",b.id,
            static_cast<const void*>(b.player),static_cast<const void*>(b.cells),static_cast<unsigned long long>(b.bytes));first=false;
    }
    std::puts("]}");std::fflush(stdout);
    ext_attribute_previous=std::move(current);
}
""".replace("{{INDICES}}", "{{" + indices + "}}")
        .replace("SCHEMA_JSON", schema)
        .replace(
            "MAX_NATIVE_READ_COUNT", str(max(r["native_index"] for r in mapping["fields"]) + 1)
        )
    )


def prepare_attribute_candidate(
    mapping: dict[Any, Any], source_profile: Path, runtime_profile: Path, destination: Path
) -> dict[Any, Any]:
    require(not destination.exists(), "Candidate destination already exists")
    source_doc = json.loads(source_profile.read_bytes())
    runtime_doc = json.loads(runtime_profile.read_bytes())
    destination.mkdir(parents=True)
    root = destination / "source"
    root.mkdir()
    for row in source_doc["sources"]:
        original = Path(row["pin"]["path"])
        require(pin(original) == row["pin"], "Original source pin differs")
        relative = Path(row["relative"])
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            "Invalid source relative path",
        )
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        row["pin"] = pin(target)
    helper = root / "native_player_attributes.inc"
    helper.write_text(native_helper(mapping))
    source_doc["sources"].append({"relative": helper.name, "pin": pin(helper)})
    original_host = Path(source_doc["host"]["path"])
    host = original_host.read_text()
    marker = "int wmain(int argc, wchar_t** argv) {"
    require(host.count(marker) == 1, "Host entry marker differs")
    host = host.replace(marker, '#include "native_player_attributes.inc"\n\n' + marker)
    expressions = ["0", "INPUT_FIRST_SYNC_TIME", "second_time", "advanced_time"]
    for expression in expressions:
        call = f"emit_native_entity_frame({expression});"
        require(host.count(call) == 1, "Original projection callsite differs")
        host = host.replace(call, call + f"\n    emit_extended_player_attributes({expression});")
    candidate_host = destination / "host-attributes.cpp.in"
    candidate_host.write_text(host)
    source_doc["host"] = pin(candidate_host)
    source_doc["source_root"] = str(root.resolve())
    candidate_source = destination / "source-profile.json"
    candidate_source.write_text(json.dumps(source_doc, indent=2) + "\n")
    runtime_doc["staging_profile"] = pin(candidate_source)
    candidate_runtime = destination / "runtime-profile.json"
    candidate_runtime.write_text(json.dumps(runtime_doc, indent=2) + "\n")
    return {
        "source_profile": pin(candidate_source),
        "runtime_profile": pin(candidate_runtime),
        "helper": pin(helper),
        "host": pin(candidate_host),
        "original_host": pin(original_host),
        "original_native_players_unchanged": pin(root / "native_players.inc")["sha256"]
        == pin(Path(json.loads(source_profile.read_bytes())["source_root"]) / "native_players.inc")[
            "sha256"
        ],
        "additional_call_sites": 4,
        "native_state_writes": False,
    }


def attribute_frames(capture: Path, mapping: dict[Any, Any]) -> Any:
    """Validate sidecar deltas, availability and paired original nine attributes."""
    schema_seen, previous_time, count = False, -1, 0
    legacy_time = -1
    current, legacy = {}, {}
    existing = [0, 1, 2, 3, 4, 6, 11, 30, 32]
    native = [row["native_index"] for row in mapping["fields"]]
    maximum = max(native) + 1
    for number, raw in enumerate(capture.open(), 1):
        if not any(
            stage in raw
            for stage in (
                "native_player_frame",
                "vantage_player_attributes_schema_v1",
                "vantage_player_attributes_frame_v1",
            )
        ):
            continue
        try:
            item = json.loads(raw)
        except ValueError as error:
            raise AttributeProjectionError(
                f"Malformed paired attribute JSON at line {number}"
            ) from error
        stage = item.get("stage")
        if stage == "native_player_frame":
            legacy_time = item["time_ms"]
            for row in item["players"]:
                require(len(row) == 18, "Original Player row width differs")
                legacy[row[0]] = row
            for player in item["removed"]:
                legacy.pop(player, None)
            continue
        if stage == "vantage_player_attributes_schema_v1":
            require(
                not schema_seen
                and not count
                and item.get("version") == 1
                and item.get("field_ids") == list(range(253))
                and item.get("native_indices") == native
                and item.get("wire") == "raw_f32_bits_or_null"
                and item.get("native_control_or_state_writes") is False,
                "Expanded attribute schema differs",
            )
            schema_seen = True
            continue
        require(
            stage == "vantage_player_attributes_frame_v1" and schema_seen,
            "Missing expanded attribute schema",
        )
        time = item.get("time_ms")
        require(
            type(time) is int
            and 0 <= time <= 0xFFFFFFFF
            and time == legacy_time
            and time > previous_time
            and (count or time == 0),
            "Expanded attribute clock differs",
        )
        require(
            item.get("kind") == ("snapshot" if not count else "delta"),
            "Expanded attribute cadence differs",
        )
        seen = set()
        for row in item.get("players", []):
            require(type(row) is list and len(row) == 3, "Expanded attribute row width differs")
            player, cell_count, values = row
            require(
                type(player) is int and 0 <= player <= 8 and player not in seen,
                "Duplicate/invalid attribute player",
            )
            require(
                type(cell_count) is int
                and 0 <= cell_count <= 65536
                and type(values) is list
                and len(values) == 253,
                "Invalid expanded attribute count",
            )
            for field, value in enumerate(values):
                require(
                    (value is None and cell_count <= native[field])
                    or (
                        type(value) is int
                        and 0 <= value <= 0xFFFFFFFF
                        and cell_count > native[field]
                    ),
                    "Expanded attribute availability/value differs",
                )
            require(
                not count or player in current,
                "Expanded attribute player appeared without snapshot metadata",
            )
            current[player] = {"native_count": cell_count, "bits": values}
            seen.add(player)
        require(
            type(item.get("player_count")) is int
            and len(current) == item["player_count"] <= 9
            and set(current) == set(legacy),
            "Expanded/original player slots differ",
        )
        bounds = item.get("read_bounds")
        require(
            type(bounds) is list and len(bounds) == len(current), "Missing exact player read bounds"
        )
        bound_ids = set()
        for bound in bounds:
            require(type(bound) is list and len(bound) == 4, "Invalid player read bounds")
            player, object_pointer, cells_pointer, span = bound
            require(
                player in current
                and player not in bound_ids
                and type(span) is int
                and span == min(current[player]["native_count"], maximum) * 8,
                "Attribute read span differs",
            )
            require(
                type(object_pointer) is str
                and re.fullmatch(r"(?:0x)?[0-9a-fA-F]{1,16}", object_pointer)
                and int(object_pointer, 16) != 0
                and type(cells_pointer) is str
                and re.fullmatch(r"(?:0x)?[0-9a-fA-F]{1,16}", cells_pointer)
                and (not span or int(cells_pointer, 16) != 0),
                "Invalid attribute pointer bounds",
            )
            bound_ids.add(player)
        for player, row in current.items():
            for column, field in enumerate(existing, 9):
                value = row["bits"][field]
                require(
                    legacy[player][column] == (0 if value is None else value),
                    "Existing attribute bits changed",
                )
        previous_time = time
        count += 1
        yield {
            "time_ms": time,
            "kind": item["kind"],
            "players": {key: dict(row) for key, row in current.items()},
            "read_bounds": bounds,
        }
    require(schema_seen and count > 0, "No expanded attribute frames")


def _float_bits(value: float) -> int:
    bits: int = struct.unpack("<I", struct.pack("<f", value))[0]
    return bits


def enrich_recording(
    base_recording: Path, capture: Path, mapping: dict[Any, Any], output: Path
) -> dict[Any, Any]:
    """Append source-bound extra attributes, preserving every original patch prefix.

    Existing V32 recordings use empty reverse patches and rebuild when seeking.
    Other reverse-patch producers require separate extension support and fail.
    """
    from itertools import zip_longest

    from .frames import Frame, RecordingWriter, read_frames, read_header
    from .patch import Patcher

    require(not output.exists(), "Expanded recording output already exists")
    before = [pin(base_recording), pin(capture)]
    base_state, extended_state = Patcher(), Patcher()
    attrs = list(attribute_frames(capture, mapping))
    require(
        all(
            value is not None
            for event in attrs
            for row in event["players"].values()
            for value in row["bits"]
        ),
        "Expanded consumer requires complete253-field availability; unavailable values cannot be displayed as zero",
    )
    available = {
        str(player): [field for field, value in enumerate(row["bits"]) if value is not None]
        for player, row in attrs[0]["players"].items()
    }
    header = read_header(base_recording)
    header["projection_extensions"] = [
        *header.get("projection_extensions", []),
        {
            "schema": SCHEMA_NAME,
            "version": 1,
            "field_ids": list(range(253)),
            "new_field_ids": sorted(set(range(253)) - ORIGINAL_FIELDS),
            "available_at_start": available,
            "unavailable_encoding": "null in pinned capture sidecar; absent in patches",
            "capture": before[1],
            "source_mapping_digest": hashlib.sha256(
                json.dumps(mapping, sort_keys=True).encode()
            ).hexdigest(),
            "original_patch_prefix_preserved": True,
            "reverse_patches_supported": False,
        },
    ]
    if all(len(fields) == 253 for fields in available.values()):
        header["missing_fields"] = [
            text.replace("Player attributes beyond captured cells0/1/2/3/4/6/11/37/40, ", "")
            for text in header.get("missing_fields", [])
        ]
    import os
    import uuid

    provisional = output.with_name(output.name + ".unverified-" + uuid.uuid4().hex)
    previous: dict[Any, Any] = {}
    changes: dict[Any, Any] = {}
    frames, added = 0, 0
    with RecordingWriter(provisional, header) as writer:
        for frame, extra in zip_longest(read_frames(base_recording), attrs):
            require(
                frame is not None and extra is not None and frame.time == extra["time_ms"],
                "VREC/attribute cadence differs",
            )
            require(not frame.reverse, "Nonempty reverse patches need expanded reverse support")
            base_state.apply(frame.patch)
            world = base_state.root.get(0)
            players = world.get(2)
            require(
                set(players) == set(extra["players"]),
                "VREC player slots differ from captured attributes",
            )
            suffix = bytearray([3, 0])  # Root.world
            wrote = False
            for player, row in extra["players"].items():
                base_attrs = players[player].get(2)
                require(base_attrs is not None, "Original Player attributes absent")
                player_patch = bytearray([7, 2]) + struct.pack("<i", player) + bytearray([3, 2])
                fields_written = 0
                for field, value in enumerate(row["bits"]):
                    if field in base_attrs.fields:
                        require(
                            value is None or _float_bits(base_attrs.get(field)) == value,
                            "Original VREC attribute differs from expanded native bits",
                        )
                        continue
                    old = previous.get(player, {}).get(field)
                    require(
                        value is not None or old is None,
                        "Attribute became unavailable; explicit reset policy required",
                    )
                    if value is None or (not frame.is_snapshot and old == value):
                        continue
                    player_patch.extend(bytes([2, field]) + struct.pack("<I", value))
                    fields_written += 1
                    changes[field] = changes.get(field, 0) + 1
                if fields_written:
                    suffix.extend(player_patch + bytes([1, 1]))
                    wrote = True
                    added += fields_written
                previous[player] = {
                    field: value for field, value in enumerate(row["bits"]) if value is not None
                }
            tail = bytes(suffix + bytes([1])) if wrote else b""
            patch = frame.patch + tail
            extended_state.apply(patch)
            current_players = extended_state.root.get(0).get(2)
            for player, row in extra["players"].items():
                output_attrs = current_players[player].get(2)
                for field, value in enumerate(row["bits"]):
                    if value is not None:
                        require(
                            _float_bits(output_attrs.get(field)) == value,
                            "Expanded typed consumer value differs",
                        )
                for field, value in players[player].get(2).fields.items():
                    require(
                        _float_bits(output_attrs.get(field)) == _float_bits(value),
                        "Pre-existing attribute was overwritten",
                    )
            writer.write(
                Frame(frame.time, patch, frame.reverse, frame.events, frame.commands, frame.skipped)
            )
            frames += 1
    require([pin(base_recording), pin(capture)] == before, "Enrichment inputs changed")
    # Independently reread the saved VREC and verify exact prefix/envelope retention.
    for original, expanded in zip_longest(read_frames(base_recording), read_frames(provisional)):
        require(
            original is not None
            and expanded is not None
            and expanded.time == original.time
            and expanded.skipped == original.skipped
            and expanded.events == original.events
            and expanded.commands == original.commands
            and expanded.reverse == original.reverse
            and expanded.patch.startswith(original.patch),
            "Stored original VREC prefix/envelope changed",
        )
    os.link(provisional, output)  # publish exclusively; never replace an existing recording
    provisional.unlink()
    return {
        "schema": "vantage_native_attribute_enrichment_result_v1",
        "recording": pin(output),
        "base_recording": before[0],
        "capture": before[1],
        "frames": frames,
        "end_ms": attrs[-1]["time_ms"],
        "new_attribute_fields": 244,
        "new_assignments": added,
        "assignment_counts": {str(k): v for k, v in sorted(changes.items())},
        "all_original_patch_prefixes_and_envelopes_preserved": True,
        "all_original_attributes_unchanged": True,
        "all_captured_available_fields_verified_in_typed_consumer": True,
        "independent_source_game_reference_checked": False,
        "general_simulation_parity_claimed": False,
    }


def compare_original_projection_streams(baseline_job: Path, candidate_job: Path) -> dict[Any, Any]:
    """Compare V32 original streams with both original admission paths intact.

    native_compare's legacy closure requires two historical saved-projection
    stages absent from both V32 captures. This adapter uses its canonical JSON,
    frame family and diagnostic exclusions, following fresh V32 re-admission.
    """
    from collections import Counter
    from itertools import zip_longest

    from .native_bootstrap_policy import FRAME_STAGES, NORMALIZE
    from .native_compare import DIAGNOSTICS, INITIAL_DATA, TERMINAL_STAGES, canonical, decode
    from .native_v32_reuse import verified_recording

    jobs, inputs, admitted = [], [], []
    for job in (baseline_job, candidate_job):
        pipeline = json.loads((job / "pipeline-result.json").read_bytes())
        process = json.loads(Path(pipeline["run"]["receipt"]["path"]).read_bytes())
        runtime, encoder = process["runtime_profile"], pipeline["encoding"]["encoder_config"]
        admitted.append(
            verified_recording(
                job,
                pipeline,
                runtime_profile=Path(runtime["path"]),
                runtime_profile_sha256=runtime["sha256"],
                encoder_config=Path(encoder["path"]),
                encoder_config_sha256=encoder["sha256"],
            )
        )
        capture = Path(pipeline["run"]["capture"]["path"])
        jobs.append(capture)
        inputs.append(pin(capture))
    counts: list[Counter[Any]] = [Counter(), Counter()]

    def records(path: Any, counter: Any) -> Any:
        for number, raw in enumerate(path.open(), 1):
            match = NORMALIZE.match(raw)
            if match:
                raw = raw[match.end() :]
            if not raw.strip():
                continue
            event = decode(raw)
            stage = event.get("stage", "")
            success = event.get("ok") is True and event.get("scope") in {
                "native_simulation_prefix_and_entity_projection",
                "native_simulation_with_frame_projection",
            }
            selected = (
                stage in FRAME_STAGES
                or stage in TERMINAL_STAGES
                or stage in INITIAL_DATA
                or stage
                in {
                    "native_world_update_returned",
                    "native_technology_catalog",
                    "native_replay_bootstrap_policy",
                }
                or stage.endswith("_projection_schema")
                or success
            )
            if not selected:
                continue
            for key in DIAGNOSTICS.get(stage, ()):
                require(key in event, "Missing declared observer diagnostic")
                event.pop(key)
            if success:
                event.pop("preferred_base", None)
            counter[stage or "terminal_success"] += 1
            yield number, canonical(event)

    digest, records_compared = hashlib.sha256(), 0
    for left, right in zip_longest(records(jobs[0], counts[0]), records(jobs[1], counts[1])):
        require(
            left is not None and right is not None and left[1] == right[1],
            f"Original emitted record differs at lines {left[0] if left else None}/{right[0] if right else None}",
        )
        digest.update(left[1] + b"\n")
        records_compared += 1
    require(
        counts[0] == counts[1]
        and all(counts[0][stage] == admitted[0]["frames"] for stage in FRAME_STAGES),
        "Original eight-stream coverage differs",
    )
    require(
        [pin(path) for path in jobs] == inputs, "Original capture changed during paired comparison"
    )
    return {
        "schema": "vantage_paired_original_projection_comparison_v1",
        "equal": True,
        "inputs": inputs,
        "records_compared": records_compared,
        "digest": digest.hexdigest(),
        "stage_counts": dict(counts[0]),
        "original_v32_admissions_revalidated": admitted,
        "compared_scope": "all eight original streams, schemas, catalogs, updates and terminal observations",
        "excluded_diagnostics": DIAGNOSTICS,
        "extra_sidecar_stages_excluded": True,
        "unobserved_simulation_state_equality_proven": False,
    }


def compare_attribute_reference(
    capture: Path, mapping: dict[Any, Any], reference: Path, *, process_receipt: Path | None = None
) -> dict[Any, Any]:
    """Bounded source-game comparison; header hints never authenticate replay bytes."""
    from collections import Counter

    from .frames import read_frames, read_header
    from .patch import Patcher

    before = [pin(capture), pin(reference)]
    native = {row["time_ms"]: row for row in attribute_frames(capture, mapping)}
    state = Patcher()
    counts: Counter[Any] = Counter()
    fields: Counter[Any] = Counter()
    differences: list[Any] = []
    clocks: list[Any] = []
    for frame in read_frames(reference):
        if frame.time > max(native):
            break
        state.apply(frame.patch)
        if frame.time not in native:
            continue
        clocks.append(frame.time)
        players = state.root.get(0).get(2)
        for player, row in native[frame.time]["players"].items():
            if player not in players or players[player].get(2) is None:
                counts["missing_reference_player"] += 1
                continue
            attrs = players[player].get(2)
            for field, actual in enumerate(row["bits"]):
                if field not in attrs.fields:
                    counts["reference_field_unavailable"] += 1
                    continue
                if actual is None:
                    counts["native_field_unavailable"] += 1
                    continue
                value = _float_bits(attrs.get(field))
                counts["available_comparisons"] += 1
                fields[field] += 1
                if value != actual:
                    counts["differences"] += 1
                    if len(differences) < 30:
                        differences.append(
                            {
                                "time_ms": frame.time,
                                "player": player,
                                "field_id": field,
                                "name": mapping["fields"][field]["name"],
                                "reference_bits": value,
                                "native_bits": actual,
                            }
                        )
    require([pin(capture), pin(reference)] == before, "Attribute reference inputs changed")
    result = {
        "schema": "vantage_attribute_source_game_reference_comparison_v1",
        "reference": before[1],
        "reference_header": read_header(reference),
        "native_capture": before[0],
        "exact_shared_clocks": clocks,
        "counts": dict(counts),
        "available_field_counts": {str(k): v for k, v in sorted(fields.items())},
        "difference_examples": differences,
        "association": "historical replay-header hint only; replay digest not authenticated",
        "replay_identity_authenticated": False,
        "publication_phase_alignment": "unknown",
        "reference_environment_identity": "not established",
        "independent_reference_gate_passed": False,
        "limits": [
            "A header path is not a digest or independent replay authentication.",
            "Absent reference fields remain unavailable rather than treated as zero.",
            "Only available fields at exact shared clocks compared.",
            "Equal observed fields do not establish full simulation parity.",
        ],
    }
    if process_receipt is not None:
        process = json.loads(process_receipt.read_bytes())
        result["native_original_process"] = pin(process_receipt)
        result["native_diagnostic_stop"] = {
            "exit_code": process["exit_code"],
            "accepted_conversion": False,
            "bounded_last_clock_ms": max(native),
        }
    return result
