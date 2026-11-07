#!/usr/bin/env python3
"""Export, verify or run a private engine package compatibility namespace."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vantage.native_engine_package import (
    export_engine_package,
    package_command,
    revalidate_relocated_job,
    verify_engine_package,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    export = commands.add_parser("export")
    export.add_argument("--source-profile", type=Path, required=True)
    export.add_argument("--runtime-profile", type=Path, required=True)
    export.add_argument("--encoder-config", type=Path, required=True)
    export.add_argument("--replay", type=Path, action="append", default=[])
    export.add_argument("--package", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--package", type=Path, required=True)
    reuse = commands.add_parser("reuse")
    reuse.add_argument("--package", type=Path, required=True)
    reuse.add_argument("--job", type=Path, required=True)
    reuse.add_argument("--logical-job", type=Path, required=True)
    reuse.add_argument("--receipt", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--package", type=Path, required=True)
    run.add_argument("--writable-root", type=Path, action="append", default=[])
    run.add_argument("--receipt", type=Path, required=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == "export":
        result = export_engine_package(
            args.source_profile,
            args.runtime_profile,
            args.encoder_config,
            args.package,
            replays=tuple(args.replay),
        )
        print(
            json.dumps(
                {
                    "package_content_id": result["package_content_id"],
                    "files": len(result["mappings"]),
                    "host_files": len(result["host_files"]),
                }
            )
        )
    elif args.action == "verify":
        result = verify_engine_package(args.package)
        print(
            json.dumps(
                {
                    "package_content_id": result["package_content_id"],
                    "verified": True,
                    "runtime_closure_proven": False,
                }
            )
        )
    elif args.action == "reuse":
        if args.receipt.exists():
            parser.error("Receipt already exists")
        result = revalidate_relocated_job(args.package, args.job, logical_job=args.logical_job)
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "recording": result["recording"],
                    "worker_launched": False,
                    "encoder_launched": False,
                }
            )
        )
    else:
        argv = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not argv:
            parser.error("run needs a command after --")
        command, receipt = package_command(
            args.package, argv, writable_roots=tuple(args.writable_root)
        )
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        if args.receipt.exists():
            parser.error("Receipt already exists")
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
        result = subprocess.run(command, check=False)
        verify_engine_package(args.package)
        receipt["package_reverified_after_run"] = True
        receipt["exit_code"] = result.returncode
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
