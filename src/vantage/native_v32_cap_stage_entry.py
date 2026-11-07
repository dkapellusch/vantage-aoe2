"""Select an input-bound update cap in the owned staging process."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import native_v32_stage_entry
from .native_input import describe_native_input


def automatic_cap(sync_count: int) -> int:
    # The positive-first worker can emit one more projected frame than updates.
    if type(sync_count) is not int or not 3 <= sync_count <= 0xFFFFFFFC:
        raise ValueError("V32 sync count exceeds its update/projection DWORD limit")
    return max(262144, sync_count + 2)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--update-cap", type=int)
    args, _ = parser.parse_known_args()
    if args.update_cap is None:
        descriptor = describe_native_input(args.replay)
        cap = automatic_cap(dict(descriptor.operation_counts)["sync"])
        sys.argv.extend(["--update-cap", str(cap)])
    native_v32_stage_entry.main()


if __name__ == "__main__":
    main()
