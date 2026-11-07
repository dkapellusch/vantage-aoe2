#!/usr/bin/env python3
"""Compare closed game/native observations without launching either runtime."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vantage.native_reference_compare import main

if __name__ == "__main__":
    raise SystemExit(main())
