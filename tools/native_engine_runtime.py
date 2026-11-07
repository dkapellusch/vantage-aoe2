#!/usr/bin/env python3
"""Capture, verify or run a package using a runtime capsule atop an empty root."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vantage.native_engine_runtime import (
    export_runtime_capsule,
    run_capsule,
    verify_runtime_capsule,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    export = sub.add_parser("export")
    export.add_argument("--package", required=True, type=Path)
    export.add_argument("--destination", required=True, type=Path)
    export.add_argument("--tree", action="append", type=Path, default=[])
    export.add_argument("--file", action="append", type=Path, default=[])
    export.add_argument("--trusted-host-root", action="append", type=Path, default=[])
    export.add_argument("--trace", type=Path)
    check = sub.add_parser("verify")
    check.add_argument("--capsule", required=True, type=Path)
    check.add_argument("--package", type=Path)
    run = sub.add_parser("run")
    run.add_argument("--capsule", required=True, type=Path)
    run.add_argument("--package", required=True, type=Path)
    run.add_argument("--writable-root", action="append", type=Path, default=[])
    run.add_argument("--receipt", required=True, type=Path)
    run.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.operation == "export":
        result = export_runtime_capsule(
            args.package,
            args.destination,
            trees=args.tree,
            files=args.file,
            trace=args.trace,
            trusted_roots=args.trusted_host_root,
        )
        print(
            json.dumps(
                {
                    "capsule_content_id": result["capsule_content_id"],
                    "files": len(result["files"]),
                    "bytes": result["unique_blob_bytes"],
                    "issues": len(result["issues"]),
                }
            )
        )
    elif args.operation == "verify":
        result = verify_runtime_capsule(args.capsule, args.package)
        print(json.dumps({"verified": True, "capsule_content_id": result["capsule_content_id"]}))
    else:
        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        if not argv:
            parser.error("run requires a command")
        result = run_capsule(args.capsule, args.package, argv, writable_roots=args.writable_root)
        with args.receipt.open("x") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        return result["exit_code"]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
