"""Exercise an accepted VREC in a private recording-only browser server."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import MethodType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vantage.frames import read_header  # noqa: E402
from vantage.gamedata import GameData  # noqa: E402
from vantage.native_conversion import pin, write_json  # noqa: E402
from vantage.server import Session, _json, serve  # noqa: E402
from vantage.sprites import _drop_pool  # noqa: E402


def check(recording: Path, output: Path, *, node: str, game_dir: Path | None = None) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    recording = recording.resolve(strict=True)
    inputs = [pin(recording), pin(Path(__file__)), pin(Path(__file__).with_suffix(".cjs"))]
    os.environ["VANTAGE_DATA_DIR"] = str(output / "data")
    session = Session(GameData(game_dir, cache_dir=output / "graphics"), output / "recordings")
    session.open_recording(str(recording))
    if not session.ended.wait(120) or session.error is not None:
        session.stop()
        raise RuntimeError(f"Recording load failed: {session.error}")
    timeline = session.timeline
    if timeline is None or timeline.errors or timeline.desynced:
        session.stop()
        raise RuntimeError("Recording did not produce a clean timeline")
    server = serve("127.0.0.1", 0, session, [], {"force_default": True}, follow_live=False)
    app = server.app
    original_get = app.get

    def reject_post(self, handler):
        return _json(handler, {"error": "Recording-only evidence server"}, 403)

    def recording_get(self, handler):
        if handler.path.split("?")[0] in {"/api/launch_game", "/api/recordings", "/api/replays"}:
            return _json(handler, {"error": "Recording-only evidence server"}, 403)
        return original_get(handler)

    app.post, app.get = MethodType(reject_post, app), MethodType(recording_get, app)
    owner = threading.Thread(target=server.serve_forever, name="recording-evidence-server")
    owner.start()
    result = None
    try:
        command = [
            node,
            str(Path(__file__).with_suffix(".cjs")),
            f"http://127.0.0.1:{server.server_address[1]}/",
            str(output / "playback.png"),
        ]
        environment = dict(os.environ)
        environment.pop("DISPLAY", None)
        environment.pop("WAYLAND_DISPLAY", None)
        with (
            (output / "browser.stdout").open("xb") as stdout,
            (output / "browser.stderr").open("xb") as stderr,
        ):
            completed = subprocess.run(
                command, env=environment, stdout=stdout, stderr=stderr, timeout=100, check=False
            )
        if completed.returncode:
            raise RuntimeError(f"Browser failed; see {output / 'browser.stderr'}")
        result = json.loads((output / "browser.stdout").read_bytes())
        result.update(
            recording=inputs[0],
            inputs=inputs,
            frames=timeline.frames,
            end_ms=timeline.time,
            header=read_header(recording),
            ordinary_game_started=False,
            game_api_used=False,
            graphics="installed" if game_dir else "plain",
        )
    finally:
        server.shutdown()
        owner.join(timeout=10)
        server.server_close()
        session.stop()
        _drop_pool()
    if owner.is_alive() or [pin(Path(p["path"])) for p in inputs] != inputs:
        raise RuntimeError("Evidence server did not close or an input changed")
    result["server_closed"] = True
    result["screenshot"] = pin(output / "playback.png")
    write_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--node", default="node")
    parser.add_argument("--game-dir", type=Path)
    args = parser.parse_args()
    result = check(args.recording, args.output, node=args.node, game_dir=args.game_dir)
    print(json.dumps({key: result[key] for key in ("passed", "frames", "server_closed")}))


if __name__ == "__main__":
    main()
