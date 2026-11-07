"""Run explicit update acquisition, discovery and experimental replay stages."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vantage.native_update_workflow import main

if __name__ == "__main__":
    raise SystemExit(main())
