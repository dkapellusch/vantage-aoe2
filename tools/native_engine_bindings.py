#!/usr/bin/env python3
"""Generate a static native role candidate table; does not execute candidates."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vantage.native_engine_bindings import main

if __name__ == "__main__":
    raise SystemExit(main())
