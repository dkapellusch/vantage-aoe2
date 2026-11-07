#!/usr/bin/env python3
"""Acquire and assess explicitly selected update inputs without engine activation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vantage.native_engine_update import main

if __name__ == "__main__":
    main()
