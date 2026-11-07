"""Apply the native worker's Linux resource policy before its first exec."""

from __future__ import annotations

import os
import sys


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] != "--":
        raise SystemExit("Expected -- followed by the explicit worker command")
    if not hasattr(os, "sched_getaffinity"):
        raise SystemExit("This native engine runtime requires Linux")
    allowed = os.sched_getaffinity(0)
    if not allowed:
        raise SystemExit("No CPU is available for the native engine")
    os.sched_setaffinity(0, {min(allowed)})
    os.setpriority(os.PRIO_PROCESS, 0, 19)
    os.execv(sys.argv[2], sys.argv[2:])


if __name__ == "__main__":
    main()
