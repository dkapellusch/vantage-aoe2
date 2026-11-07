"""Serve a completed V32 VREC using the validated persistent playback index.

The caller is responsible for verifying conversion provenance. This server only
loads an already-produced recording and never starts a game or native worker.
"""

from __future__ import annotations

import argparse
import sys
import time
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vantage.frames import read_header
from vantage.gamedata import GameData, find_game_dir
from vantage.native_session import NativeSession
from vantage.playback_index import ReadOnlyTimeline, load_completed
from vantage.server import WEB_PACKAGE, _bytes, serve
from vantage.sprites import _drop_pool

if TYPE_CHECKING:
    from typing import TYPE_CHECKING


_INCOMPLETE_TITLE = "INCOMPLETE-checksum-prefix"
_PREVIEW_NOTICE = b"""
<div id="vantage-incomplete-preview" role="status"
 style="position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:9999;
 background:#382900;color:#fff3b0;border:1px solid #e9b949;border-radius:5px;
 padding:7px 12px;font:600 14px sans-serif;pointer-events:none">
 Incomplete replay preview \xe2\x80\x94 the match continues beyond this recording
</div>
<script>
const previewNotice = document.getElementById('vantage-incomplete-preview');
const previewEvents = new EventSource('/api/stream');
previewEvents.onmessage = (event) => {
  try {
    const state = JSON.parse(event.data);
    previewNotice.hidden = !(state.mode === 'recording' &&
      state.source?.header?.title === 'INCOMPLETE-checksum-prefix');
  } catch {}
};
</script>
"""


def _mark_incomplete_preview(server: Any, header: dict[Any, Any]) -> None:
    """Label this experimental server's preview without changing shared web assets."""
    if header.get("title") != _INCOMPLETE_TITLE:
        return
    app = server.app
    ordinary_static = app._static

    def static(handler: Any, name: Any) -> Any:
        if name != "index.html":
            return ordinary_static(handler, name)
        body = resources.files(WEB_PACKAGE).joinpath("web", "index.html").read_bytes()
        if body.count(b"</body>") != 1:
            raise ValueError("Vantage index has an unexpected body")
        _bytes(handler, body.replace(b"</body>", _PREVIEW_NOTICE + b"</body>"), "text/html")

    app._static = static


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8740)
    parser.add_argument("--game-dir", type=Path)
    parser.add_argument(
        "--recordings-dir", type=Path, default=Path("~/.local/share/vantage/recordings")
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    recording = args.recording.expanduser().resolve(strict=True)
    data = GameData(args.game_dir or find_game_dir())
    rec_dir = args.recordings_dir.expanduser()
    rec_dir.mkdir(parents=True, exist_ok=True)
    session = NativeSession(data, rec_dir)
    server = timeline = None
    try:
        header = read_header(recording)
        count, end = header.get("expected_frames"), header.get("end_ms")
        if type(count) is not int or count <= 0 or type(end) is not int or end < 0:
            raise ValueError("V32 recording has no verified frame extent")
        ticket, _ = session._reserve("recording", {"path": str(recording), "status": "loading"})
        print("Loading or building the playback index…", file=sys.stderr, flush=True)
        started = time.monotonic()
        indexed_data, timeline = load_completed(
            recording,
            ticket.data.with_mode(header.get("game_mode")),
            args.index_root.expanduser(),
            ticket.stop,
        )
        status = timeline.status()
        if (
            not status["complete"]
            or status["errors"]
            or status["desynced"]
            or status["frames"] != count
            or status["time"] != end
        ):
            raise ValueError("Indexed recording is incomplete or has an unexpected extent")
        kind = "cached" if isinstance(timeline, ReadOnlyTimeline) else "ingested"
        print(
            f"Playback index {kind} in {time.monotonic() - started:.3f}s",
            file=sys.stderr,
            flush=True,
        )
        with session.lock:
            if (
                session.generation != ticket.generation
                or session.source is not ticket.source
                or ticket.stop.is_set()
            ):
                raise RuntimeError("Recording selection changed while loading")
            session.data, session.timeline = indexed_data, timeline
            session.source.update(header=header, game=indexed_data.game, status="ready")
            session.ended.set()
        server = serve(
            "127.0.0.1",
            args.port,
            session,
            [],
            {"patch": {}, "force_default": False},
            follow_live=False,
        )
        _mark_incomplete_preview(server, header)
        print(
            f"Vantage on http://127.0.0.1:{args.port}/ (indexed recording: {recording})", flush=True
        )
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, RuntimeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2
    finally:
        session.stop()
        session.close_native()
        if server is not None:
            server.server_close()
        # The lazy index closes via its finalizer after outstanding readers drop
        # their Timeline references; do not close it while a request may use it.
        if isinstance(timeline, ReadOnlyTimeline) and session.timeline is not timeline:
            timeline.close()
        _drop_pool()
    return 0


if __name__ == "__main__":
    sys.exit(main())
