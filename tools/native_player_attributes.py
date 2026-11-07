#!/usr/bin/env python3
"""Generate and qualify passive expanded native PlayerAttributes projections."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vantage.native_player_attributes import (
    compare_attribute_reference,
    compare_original_projection_streams,
    enrich_recording,
    generate_attribute_mapping,
    native_helper,
    prepare_attribute_candidate,
)
from vantage.native_v32_reuse import verified_recording


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    mapping = commands.add_parser("map")
    mapping.add_argument("--c-source", type=Path, required=True)
    mapping.add_argument("--asm-source", type=Path, required=True)
    mapping.add_argument("--image", type=Path, required=True)
    mapping.add_argument("--output", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--mapping", type=Path, required=True)
    prepare.add_argument("--source-profile", type=Path, required=True)
    prepare.add_argument("--runtime-profile", type=Path, required=True)
    prepare.add_argument("--destination", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    enrich = commands.add_parser("enrich")
    enrich.add_argument("--mapping", type=Path, required=True)
    enrich.add_argument("--candidate", type=Path, required=True)
    enrich.add_argument("--job", type=Path, required=True)
    enrich.add_argument("--recording", type=Path, required=True)
    enrich.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare-original")
    compare.add_argument("--baseline-job", type=Path, required=True)
    compare.add_argument("--candidate-job", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    reference = commands.add_parser("compare-reference")
    reference.add_argument("--mapping", type=Path, required=True)
    reference.add_argument("--capture", type=Path, required=True)
    reference.add_argument("--reference", type=Path, required=True)
    reference.add_argument("--process-receipt", type=Path)
    reference.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; preserve previous evidence")
    if args.action == "map":
        result = generate_attribute_mapping(args.c_source, args.asm_source, args.image)
    elif args.action == "prepare":
        result = prepare_attribute_candidate(
            json.loads(args.mapping.read_bytes()),
            args.source_profile,
            args.runtime_profile,
            args.destination,
        )
    elif args.action == "compare-original":
        result = compare_original_projection_streams(args.baseline_job, args.candidate_job)
    elif args.action == "compare-reference":
        result = compare_attribute_reference(
            args.capture,
            json.loads(args.mapping.read_bytes()),
            args.reference,
            process_receipt=args.process_receipt,
        )
    else:
        mapping = json.loads(args.mapping.read_bytes())
        c_source, asm_source, image = [Path(row["path"]) for row in mapping["sources"]]
        if generate_attribute_mapping(c_source, asm_source, image) != mapping:
            parser.error("Mapping differs from independently regenerated source witnesses")
        candidate = json.loads(args.candidate.read_bytes())
        if Path(candidate["helper"]["path"]).read_text() != native_helper(mapping):
            parser.error("Passive helper differs from source-bound mapping")
        pipeline = json.loads((args.job / "pipeline-result.json").read_bytes())
        runtime = candidate["runtime_profile"]
        encoder = pipeline["encoding"]["encoder_config"]
        admission = verified_recording(
            args.job,
            pipeline,
            runtime_profile=Path(runtime["path"]),
            runtime_profile_sha256=runtime["sha256"],
            encoder_config=Path(encoder["path"]),
            encoder_config_sha256=encoder["sha256"],
        )
        result = enrich_recording(
            Path(admission["recording"]["path"]),
            Path(pipeline["run"]["capture"]["path"]),
            mapping,
            args.recording,
        )
        result["original_v32_admission_revalidated"] = admission
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output)}))


if __name__ == "__main__":
    main()
