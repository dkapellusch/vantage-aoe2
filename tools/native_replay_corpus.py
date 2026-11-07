#!/usr/bin/env python3
"""Run with the repository Python environment; never launches a game client."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vantage.native_corpus import main

if __name__ == "__main__":
    main()
