#!/usr/bin/env python3
"""Read-only native engine inventory; never launches inspected code."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vantage.native_engine_manifest import inspect_engine_profiles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-profile", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--encoder-config", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=20000)
    parser.add_argument("--max-total-bytes", type=int, default=8 << 30)
    parser.add_argument("--max-text-bytes", type=int, default=16 << 20)
    args = parser.parse_args()
    result = inspect_engine_profiles(
        args.source_profile,
        args.runtime_profile,
        args.encoder_config,
        replay=args.replay,
        max_files=args.max_files,
        max_total_bytes=args.max_total_bytes,
        max_text_bytes=args.max_text_bytes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "inventory_content_id": result["inventory_content_id"],
                "summary": result["summary"],
                "dependency_closure_proven": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
