"""Run the playback and raster-cache regressions with Node's built-in runner."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_browser_playback() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the browser playback regression tests")
    result = subprocess.run(
        [
            node,
            "--test",
            # Every DOM-free browser test: tests/*.test.mjs and tests/*.test.cjs.
            *sorted(str(f) for f in Path(__file__).parent.glob("*.test.[mc]js")),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
