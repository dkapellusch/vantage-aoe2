"""Check a native-produced VREC with a retained standalone Vantage revision."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import resource
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path
from types import MethodType


def pin(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def write(path, value):
    with path.open("x") as output:
        json.dump(value, output, indent=2)
        output.write("\n")


def inside(work, node, load_timeout):
    from vantage.frames import read_header
    from vantage.gamedata import GameData
    from vantage.server import Session, _json, serve
    from vantage.sprites import _drop_pool

    for hidden in (
        "/home/dan/Code/AoeAI",
        "/home/dan/re",
        "/mnt/nvme/SteamLibrary",
        "/mnt/nvme/vantage-native-research",
    ):
        assert not Path(hidden).exists() or not any(Path(hidden).iterdir()), hidden
    try:
        with socket.create_connection(("127.0.0.1", 4341), timeout=1):
            raise RuntimeError("Game API unexpectedly reachable")
    except OSError:
        pass
    recording = work / "recording.vrec"
    before = pin(recording)
    session = Session(GameData(None, cache_dir=work / "graphics"), work / "recordings")
    started = time.monotonic()
    initial_usage = resource.getrusage(resource.RUSAGE_SELF)
    session.open_recording(str(recording))
    with (work / "load-progress.ndjson").open("x") as progress:
        while True:
            ended = session.ended.wait(min(5, max(0, load_timeout - (time.monotonic() - started))))
            timeline = session.timeline
            progress.write(
                json.dumps(
                    {
                        "seconds": time.monotonic() - started,
                        "frames": timeline.frames if timeline else None,
                        "time_ms": timeline.time if timeline else None,
                        "ended": ended,
                        "error": session.error,
                    }
                )
                + "\n"
            )
            progress.flush()
            if ended or time.monotonic() - started >= load_timeout:
                break
    final_usage = resource.getrusage(resource.RUSAGE_SELF)
    loading = {
        "seconds": time.monotonic() - started,
        "user_cpu_seconds": final_usage.ru_utime - initial_usage.ru_utime,
        "system_cpu_seconds": final_usage.ru_stime - initial_usage.ru_stime,
        "server_peak_rss_bytes": final_usage.ru_maxrss * 1024,
        "includes_decode_ingest_and_timeline_construction": True,
        "isolated_index_time_claimed": False,
        "ended": ended,
        "error": session.error,
    }
    write(work / "load-result.json", loading)
    if not ended or session.error is not None:
        session.stop()
        raise RuntimeError("Recording load did not finish cleanly; see load-result.json")
    timeline = session.timeline
    assert timeline is not None and not timeline.errors and not timeline.desynced
    server = serve("127.0.0.1", 0, session, [], {"force_default": True}, follow_live=False)
    original_get = server.app.get

    def reject_post(self, handler):
        return _json(handler, {"error": "Recording-only evidence server"}, 403)

    def recording_get(self, handler):
        if handler.path.split("?")[0] in {"/api/launch_game", "/api/recordings", "/api/replays"}:
            return _json(handler, {"error": "Recording-only evidence server"}, 403)
        return original_get(handler)

    server.app.post = MethodType(reject_post, server.app)
    server.app.get = MethodType(recording_get, server.app)
    owner = threading.Thread(target=server.serve_forever)
    owner.start()
    try:
        command = [
            node,
            str(work / "browser.cjs"),
            f"http://127.0.0.1:{server.server_address[1]}/",
            str(work / "playback.png"),
        ]
        with (
            (work / "browser.stdout").open("xb") as stdout,
            (work / "browser.stderr").open("xb") as stderr,
        ):
            process = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=100)
        assert process.returncode == 0, "Browser failed; retained browser.stderr"
        result = json.loads((work / "browser.stdout").read_text())
        result.update(
            recording=before,
            frames=timeline.frames,
            end_ms=timeline.time,
            header=read_header(recording),
            game_api_unreachable=True,
            ordinary_game_controlled=False,
            original_research_roots_hidden=True,
            standalone_import=pin(Path(sys.modules["vantage.server"].__file__)),
            graphics="plain",
            native_backend_integrated=False,
            complete_poc11_gate_passed=False,
            loading=loading,
        )
    finally:
        server.shutdown()
        owner.join(timeout=10)
        server.server_close()
        session.stop()
        _drop_pool()
    assert not owner.is_alive() and pin(recording) == before
    result["server_closed"] = True
    result["screenshot"] = pin(work / "playback.png")
    write(work / "result.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--recording", type=Path)
    parser.add_argument("--standalone", type=Path, default=Path("/home/dan/Code/vantage"))
    parser.add_argument("--node", required=True)
    parser.add_argument("--playwright-modules", type=Path, required=True)
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--load-timeout", type=float, default=120)
    args = parser.parse_args()
    work = args.work.resolve()
    if args.inside:
        inside(work, args.node, args.load_timeout)
        return
    if not 0 < args.load_timeout <= 3600:
        parser.error("Load timeout must be positive and at most 3600 seconds")
    work.mkdir(parents=True, exist_ok=False)
    standalone = args.standalone.resolve(strict=True)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=standalone, text=True
    ).strip()
    archive = subprocess.check_output(["git", "archive", commit, "src/vantage"], cwd=standalone)
    snapshot = work / "standalone"
    snapshot.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(snapshot, filter="data")
    write(
        work / "standalone-source.json",
        {"commit": commit, "files": [pin(p) for p in sorted(snapshot.rglob("*")) if p.is_file()]},
    )
    shutil.copyfile(args.recording, work / "recording.vrec")
    shutil.copyfile(Path(__file__), work / "runner.py")
    shutil.copyfile(Path(__file__).with_suffix(".cjs"), work / "browser.cjs")
    python = standalone / ".venv/bin/python"
    base_python = Path(sys.base_prefix).resolve()
    command = [
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--unshare-all",
        "--clearenv",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/home/dan",
        "--ro-bind",
        str(base_python),
        str(base_python),
        "--ro-bind",
        str(standalone / ".venv"),
        str(standalone / ".venv"),
        "--ro-bind",
        str(args.playwright_modules),
        str(args.playwright_modules),
        "--ro-bind",
        args.node,
        args.node,
        "--tmpfs",
        "/mnt/nvme/SteamLibrary",
        "--tmpfs",
        "/mnt/nvme/vantage-native-research",
        "--bind",
        str(work),
        str(work),
        "--chdir",
        str(work),
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "PYTHONPATH",
        str(snapshot / "src"),
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "XDG_CACHE_HOME",
        str(work / "cache"),
        "--setenv",
        "VANTAGE_DATA_DIR",
        str(work / "data"),
        "--setenv",
        "VANTAGE_PLAYWRIGHT_MODULE",
        str(args.playwright_modules / "playwright"),
        "--",
        str(python),
        str(work / "runner.py"),
        "--inside",
        "--work",
        str(work),
        "--node",
        args.node,
        "--playwright-modules",
        str(args.playwright_modules),
        "--load-timeout",
        str(args.load_timeout),
    ]
    # The venv's interpreter symlink may use uv's unversioned alias.
    alias = (standalone / ".venv/bin/python").readlink()
    if alias.is_absolute() and not alias.is_relative_to(base_python):
        parent = alias.parent.parent
        command[command.index("--bind") : command.index("--bind")] = [
            "--ro-bind",
            str(parent.resolve()),
            str(parent),
        ]
    write(
        work / "invocation.json",
        {
            "command": command,
            "input_recording": pin(args.recording),
            "source_commit": commit,
            "host_runtime_closure_claimed": False,
            "worktree_uncommitted_changes_included": False,
        },
    )
    with (
        (work / "process.stdout").open("xb") as stdout,
        (work / "process.stderr").open("xb") as stderr,
    ):
        process = subprocess.run(
            command, stdout=stdout, stderr=stderr, timeout=args.load_timeout + 150
        )
    write(
        work / "process-exit.json",
        {
            "exit_code": process.returncode,
            "stdout": pin(work / "process.stdout"),
            "stderr": pin(work / "process.stderr"),
        },
    )
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
