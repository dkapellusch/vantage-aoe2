"""Discover a narrow native role chain from reviewed bytes; never execute it.

Candidates are bounded static evidence, not qualified adapters. Calling
conventions, startup dependencies and layouts remain reviewed assumptions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
from typing import TYPE_CHECKING

from .native_compare import decode
from .native_reference_compare import pin

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TYPE_CHECKING, Any


SCHEMA = "vantage-native-binding-manifest-v1"


class BindingError(ValueError):
    """A source witness, code view, mapping or binding is unsuitable."""


def require(
    condition: Any,
    message: str,
) -> None:
    if not condition:
        raise BindingError(message)


def verify_pin(record: Any) -> None:
    require(type(record) is dict and pin(record["path"]) == record, "Pinned input changed")


class PE:
    """Strict file-backed AMD64 PE mapping, without loading code or libraries."""

    def __init__(self, path: Any) -> None:
        self.pin = pin(path)
        self.data = Path(path).read_bytes()
        require(hashlib.sha256(self.data).hexdigest() == self.pin["sha256"], "PE changed")
        b = self.data
        require(len(b) >= 64 and b[:2] == b"MZ", "Missing DOS header")
        offset = struct.unpack_from("<I", b, 0x3C)[0]
        require(offset + 24 <= len(b) and b[offset : offset + 4] == b"PE\0\0", "Invalid PE header")
        machine, count = struct.unpack_from("<HH", b, offset + 4)
        size = struct.unpack_from("<H", b, offset + 20)[0]
        optional = offset + 24
        require(
            machine == 0x8664 and size >= 240 and optional + size <= len(b),
            "Only complete AMD64 PE32+ images supported",
        )
        require(struct.unpack_from("<H", b, optional)[0] == 0x20B, "Not PE32+")
        require(0 < count <= 96 and optional + size + 40 * count <= len(b), "Invalid sections")
        self.base = struct.unpack_from("<Q", b, optional + 24)[0]
        self.sections: list[Any] = []
        for index in range(count):
            at = optional + size + index * 40
            virtual_size, rva, raw_size, raw = struct.unpack_from("<IIII", b, at + 8)
            flags = struct.unpack_from("<I", b, at + 36)[0]
            require(raw + raw_size <= len(b), "Section bytes extend past EOF")
            section = dict(
                name=b[at : at + 8].rstrip(b"\0").decode("ascii", errors="strict"),
                rva=rva,
                raw=raw,
                raw_size=raw_size,
                virtual_size=virtual_size,
                executable=bool(flags & 0x20000000),
            )
            for prior in self.sections:
                require(
                    not (rva < prior["rva"] + prior["raw_size"] and prior["rva"] < rva + raw_size),
                    "Overlapping PE RVA mappings",
                )
                require(
                    not (
                        raw_size
                        and prior["raw_size"]
                        and raw < prior["raw"] + prior["raw_size"]
                        and prior["raw"] < raw + raw_size
                    ),
                    "Overlapping PE file mappings",
                )
            self.sections.append(section)

    def region(self, rva: int, length: int, *, executable: Any = False) -> tuple[Any, ...]:
        require(
            type(rva) is int and type(length) is int and rva >= 0 and length > 0, "Invalid region"
        )
        matches = [
            s for s in self.sections if s["rva"] <= rva and rva + length <= s["rva"] + s["raw_size"]
        ]
        require(len(matches) == 1, "RVA span is not uniquely file-backed")
        section = matches[0]
        require(not executable or section["executable"], "Code is not in an executable section")
        offset = section["raw"] + rva - section["rva"]
        return offset, self.data[offset : offset + length], section["name"]


def source_bytes(witness: Any) -> bytes:
    verify_pin(witness["pin"])
    raw = Path(witness["pin"]["path"]).read_bytes()
    start = witness["start_va"]
    require(type(start) is int and start >= 0, "Invalid witness VA")
    if witness["format"] == "raw":
        result: Any = raw
    elif witness["format"] == "asm_tsv":
        result = bytearray()
        for line in raw.decode().splitlines():
            parts = line.split("\t")
            require(len(parts) >= 3, "Malformed instruction witness")
            address = int(parts[0], 16)
            require(address == start + len(result), "Instruction witness has gap or overlap")
            result.extend(bytes.fromhex(parts[1]))
        result = bytes(result)
    else:
        raise BindingError("Unknown source witness format")
    require(
        result and hashlib.sha256(result).hexdigest() == witness["span_sha256"],
        "Source span digest differs",
    )
    return bytes(result)


def _pattern(
    role: Any,
) -> Any:
    tokens = role["pattern"].split()
    require(8 <= len(tokens) <= 256, "Signature length out of bounds")
    require(
        all(t == "??" or re.fullmatch(r"[0-9a-f]{2}", t) for t in tokens), "Malformed signature"
    )
    require(sum(t != "??" for t in tokens) >= 8, "Insufficient fixed signature bytes")
    return [None if t == "??" else int(t, 16) for t in tokens]


def discover(
    manifest: dict[Any, Any], image: Any, *, diagnostic_unverified: Any = False
) -> dict[Any, Any]:
    """Verify reviewed baseline spans, then match only declared bounded windows.

    A usable-code-view witness must identify target bytes; unknown protected
    images are rejected before matching. Exact unique patterns remain candidates.
    """
    require(manifest.get("schema") == SCHEMA, "Unknown binding manifest")
    require(type(manifest.get("build_identity")) is dict, "Missing build identity")
    require(
        type(manifest.get("unsupported_bindings")) is list and manifest["unsupported_bindings"],
        "Undeclared residual bindings",
    )
    roles: Any = manifest.get("roles")
    require(type(roles) is list and roles, "Missing roles")
    require(len({r["name"] for r in roles}) == len(roles), "Duplicate roles")
    require(all(re.fullmatch(r"[a-z][a-z0-9_]*", r["name"]) for r in roles), "Invalid role name")
    verify_pin(manifest["baseline_image"])
    baseline = PE(manifest["baseline_image"]["path"])
    target = PE(image)
    views = [
        v
        for v in manifest.get("usable_code_views", [])
        if v.get("image_sha256") == target.pin["sha256"]
    ]
    require(len(views) <= 1, "Ambiguous usable code-view witnesses")
    if not views:
        require(diagnostic_unverified, "Target lacks a unique verified usable code-view witness")
        view = {
            "image_sha256": target.pin["sha256"],
            "kind": "unverified_on_disk_PE",
            "qualification": "Diagnostic anchor survival only; no generated table permitted",
        }
    else:
        view = views[0]
        require(
            view.get("kind") in {"reviewed_recovered_PE", "synthetic_fixture"},
            "Unsupported code-view provenance",
        )
        verify_pin(view["provenance"])
    bindings = []
    for role in roles:
        require(
            type(role.get("assumptions")) is dict
            and all(
                role["assumptions"].get(k) for k in ("calling_convention", "startup", "layout")
            ),
            "Missing reviewed calling/startup/layout assumptions",
        )
        for witness in role.get("semantic_witnesses", []):
            verify_pin(witness)
        require(role.get("semantic_witnesses"), "Missing semantic witness")
        reviewed = source_bytes(role["source_witness"])
        baseline_rva = role["source_witness"]["start_va"] - baseline.base
        _, actual, _ = baseline.region(baseline_rva, len(reviewed), executable=True)
        require(actual == reviewed, f"Reviewed source differs from baseline: {role['name']}")
        pattern = _pattern(role)
        require(len(pattern) <= len(reviewed), "Signature exceeds reviewed span")
        require(
            all(p is None or reviewed[i] == p for i, p in enumerate(pattern)),
            "Pattern differs from reviewed source",
        )
        start, end = role["search_rva"]
        require(
            type(start) is int and type(end) is int and 0 < end - start <= (1 << 20),
            "Search exceeds declared 1 MiB bound",
        )
        offset, data, section = target.region(start, end - start, executable=True)
        fixed = next(i for i, value in enumerate(pattern) if value is not None)
        candidates = []
        pos = 0
        while True:
            anchor = data.find(bytes([pattern[fixed]]), pos)
            if anchor < 0:
                break
            pos = anchor + 1
            at = anchor - fixed
            if at < 0 or at + len(pattern) > len(data):
                continue
            if all(p is None or data[at + i] == p for i, p in enumerate(pattern)):
                candidates.append(
                    {
                        "rva": start + at,
                        "preferred_va": target.base + start + at,
                        "file_offset": offset + at,
                        "section": section,
                        "context_hex": data[at : at + len(pattern)].hex(),
                    }
                )
                if len(candidates) >= 32:
                    break
        bindings.append(
            {
                "role": role["name"],
                "status": "unique_candidate"
                if len(candidates) == 1
                else "missing"
                if not candidates
                else "ambiguous",
                "candidates": candidates,
                "candidate_count_capped_at": 32,
                "search_rva": [start, end],
                "pattern": role["pattern"],
                "baseline_source_span_sha256": role["source_witness"]["span_sha256"],
                "assumptions": role["assumptions"],
                "source_witness": role["source_witness"],
                "semantic_witnesses": role["semantic_witnesses"],
            }
        )
    by_role = {row["role"]: row for row in bindings}
    # A unique reviewed caller can distinguish byte-identical getter bodies.
    # Preserve eliminated candidates and the exact rel32 instruction as evidence.
    for relation in manifest.get("relationships", []):
        require(relation.get("kind") == "direct_rel32_call", "Unsupported role relationship")
        require(
            type(relation.get("offset")) is int and 0 <= relation["offset"] < 65536,
            "Invalid relation offset",
        )
        caller, callee = by_role[relation["caller"]], by_role[relation["callee"]]
        if caller["status"] == "unique_candidate" and callee["status"] == "ambiguous":
            site = caller["candidates"][0]["rva"] + relation["offset"]
            _, code, _ = target.region(site, 5, executable=True)
            observed = site + 5 + struct.unpack_from("<i", code, 1)[0] if code[0] == 0xE8 else None
            matches = [c for c in callee["candidates"] if c["rva"] == observed]
            callee["unfiltered_candidates"] = callee["candidates"]
            callee["candidates"] = matches
            callee["status"] = (
                "unique_candidate"
                if len(matches) == 1
                else "missing"
                if not matches
                else "ambiguous"
            )
            callee["relationship_disambiguation"] = {
                "caller": relation["caller"],
                "call_site_rva": site,
                "instruction_hex": code.hex(),
                "observed_target_rva": observed,
            }
    relations = []
    for relation in manifest.get("relationships", []):
        require(relation.get("kind") == "direct_rel32_call", "Unsupported role relationship")
        caller, callee = by_role[relation["caller"]], by_role[relation["callee"]]
        item = {**relation, "status": "unresolved_role"}
        if caller["status"] == callee["status"] == "unique_candidate":
            site = caller["candidates"][0]["rva"] + relation["offset"]
            require(
                type(relation["offset"]) is int and 0 <= relation["offset"] < 65536,
                "Invalid relation offset",
            )
            _, code, _ = target.region(site, 5, executable=True)
            observed = site + 5 + struct.unpack_from("<i", code, 1)[0] if code[0] == 0xE8 else None
            item.update(
                status="matched"
                if observed == callee["candidates"][0]["rva"]
                else "relationship_mismatch",
                call_site_rva=site,
                instruction_hex=code.hex(),
                observed_target_rva=observed,
            )
        relations.append(item)
    ready = (
        bool(views)
        and all(x["status"] == "unique_candidate" for x in bindings)
        and all(x["status"] == "matched" for x in relations)
    )
    require(pin(image) == target.pin, "Target changed during discovery")
    return {
        "schema": "vantage-native-binding-candidates-v1",
        "baseline_build_identity": manifest["build_identity"],
        "target_build_identity": (
            manifest["build_identity"]
            if target.pin["sha256"] == baseline.pin["sha256"]
            else view.get("build_identity")
        ),
        "target_image": target.pin,
        "baseline_image": baseline.pin,
        "target_preferred_base": target.base,
        "code_view": view,
        "status": (
            "static_candidate_table_ready"
            if ready
            else "unverified_code_view_diagnostic_only"
            if not views
            else "rejected_unresolved_bindings"
        ),
        "image_changed": target.pin["sha256"] != baseline.pin["sha256"],
        "bindings": bindings,
        "relationships": relations,
        "unsupported_bindings": manifest["unsupported_bindings"],
        "executable_qualified": False,
        "native_execution_performed": False,
        "real_second_build_demonstrated": False,
        "limits": [
            "Bounded source-byte matching proposes addresses, not compatible engine behavior",
            "Known baseline layouts/calling conventions/startup dependencies remain assumptions "
            "on new builds",
            "Synthetic rebasing/role movement is not a second real game version",
            "Protected images require independently reviewed usable code views",
            "Residual hardcoded bindings remain outside this narrow generated table",
        ],
    }


def generate_header(result: dict[Any, Any]) -> str:
    require(result.get("status") == "static_candidate_table_ready", "Unresolved table rejected")
    lines = [
        "/* Static candidates only. No adapter qualification or execution is implied. */",
        "#pragma once",
        "#include <stdint.h>",
        f'#define VANTAGE_BINDING_IMAGE_SHA256 "{result["target_image"]["sha256"]}"',
    ]
    for row in result["bindings"]:
        require(row["status"] == "unique_candidate", "Ambiguous binding rejected")
        lines.append(
            f"#define VANTAGE_RVA_{row['role'].upper()} UINT64_C(0x{row['candidates'][0]['rva']:x})"
        )
    lines.append("#define VANTAGE_BINDINGS_EXECUTABLE_QUALIFIED 0")
    return "\n".join(lines) + "\n"


def main(argv: Any = None) -> Any:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--header", type=Path)
    parser.add_argument("--diagnostic-unverified", action="store_true")
    args = parser.parse_args(argv)
    manifest_pin = pin(args.manifest)
    manifest = decode(args.manifest.read_bytes())
    result = discover(manifest, args.image, diagnostic_unverified=args.diagnostic_unverified)
    result["manifest"] = manifest_pin
    require(pin(args.manifest) == manifest_pin, "Manifest changed during discovery")
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    if args.header:
        generated = generate_header(result)
        with args.header.open("x") as stream:
            stream.write(generated)
    return 0 if result["status"] == "static_candidate_table_ready" else 1
