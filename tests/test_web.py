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
            str(Path(__file__).with_name("web.test.mjs")),
            str(Path(__file__).with_name("render_cache.test.mjs")),
            str(Path(__file__).with_name("graphics_cache.test.mjs")),
            str(Path(__file__).with_name("sprite_gl.test.mjs")),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
