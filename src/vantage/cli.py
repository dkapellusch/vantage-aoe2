"""The ``vantage`` command: run the spectator, record a game, inspect a recording."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from vantage.paths import local_data_dir

DEFAULT_RECORDINGS = local_data_dir() / "recordings"
#: The scheme the game's own "Spectate with CaptureAge" buttons open.
CAPTUREAGE_SCHEME = "captureage"
#: The URL scheme and recording MIME type ``register-handler`` installs.
SCHEME = "vantage"
RECORDING_MIME = "application/x-vantage-recording"
DESKTOP_FILE = "vantage.desktop"
#: Windows: per-user classes key, and the ProgID ``.vrec`` files point at.
CLASSES_KEY = "Software\\Classes"
RECORDING_PROGID = "Vantage.Recording"


def build_parser() -> argparse.ArgumentParser:
    from vantage import __version__

    p = argparse.ArgumentParser(
        prog="vantage",
        description="Vantage: spectate and replay Age of Empires II: DE games in the browser.",
        epilog="Start with 'vantage serve --open'; 'vantage doctor' checks your setup.",
    )
    p.add_argument("--version", action="version", version=f"vantage {__version__}")
    ss = p.add_subparsers(dest="command", metavar="COMMAND")

    s = ss.add_parser("serve", help="start the spectator UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8740)
    src = s.add_mutually_exclusive_group()
    src.add_argument(
        "--recording", "--start-file", type=Path, dest="recording", help="open a .vrec recording"
    )
    src.add_argument("--live", action="store_true", help="connect to the running game")
    # Local replay playback (experimental, from the development copy): a replay is
    # converted on this machine with a pinned profile, without the running game.
    src.add_argument(
        "--native-replay", type=Path, help="convert and watch a local replay (experimental)"
    )
    s.add_argument("--native-profile", type=Path, help="local conversion profile")
    s.add_argument("--native-profile-sha256", help="expected SHA256 of the conversion profile")
    s.add_argument("--native-cache-dir", type=Path, help="local conversion cache folder")
    s.add_argument(
        "--native-replay-root",
        type=Path,
        action="append",
        help="replay folder for local playback (repeatable)",
    )
    s.add_argument(
        "--native-timeout",
        type=float,
        help="local conversion limit per phase in seconds (default: 900)",
    )
    s.add_argument(
        "start_file",
        nargs="?",
        type=Path,
        metavar="FILE.vrec",
        help="a recording to open (as a file manager passes it)",
    )
    s.add_argument(
        "--replay", help="with --live: Windows path of a .aoe2record for the game to play"
    )
    s.add_argument("--cloud", action="store_true", help="with --replay: a cloud replay name")
    s.add_argument(
        "--game",
        choices=("aoe2", "ror"),
        help="with --live: switch the game first (Age of Empires II or Return of Rome)",
    )
    s.add_argument("--lobby", help="with --live: lobby id to spectate")
    s.add_argument("--lobby-source", help=argparse.SUPPRESS)
    s.add_argument("--no-record", action="store_true", help="with --live: do not write a .vrec")
    s.add_argument("--recordings-dir", type=Path, default=DEFAULT_RECORDINGS)
    s.add_argument("--game-dir", type=Path, help="AoE2 DE install (default: auto-detect)")
    s.add_argument(
        "--replay-dir",
        type=Path,
        action="append",
        help="replay folder for the replay browser (repeatable; default: every AoE2 "
        "profile in every Steam library, plus the live game's profile)",
    )
    s.add_argument("--open", action="store_true", help="open the UI in a browser")
    s.add_argument(
        "--exit-on-stream-end",
        action="store_true",
        help="stop when the game's stream ends (--live) or a recording finishes playing",
    )
    s.add_argument("--patch-config", help="JSON object of UI settings to force on every browser")
    s.add_argument(
        "--force-default-config",
        action="store_true",
        help="browsers ignore their saved settings this session",
    )
    s.add_argument("--minimize-game", action="store_true", help="with --live: minimise the game")
    s.add_argument(
        "--recording-only",
        action="store_true",
        help="open recordings without launching or discovering the game or using its API; "
        "--game-dir still supplies graphics from an explicit local directory",
    )
    s.add_argument("--native-worker", type=Path, help="imported native engine client descriptor")
    s.add_argument("--native-worker-sha256", help="expected native engine descriptor SHA256")
    s.add_argument(
        "--experimental-native",
        action="store_true",
        help="enable experimental native replay conversion",
    )

    o = ss.add_parser(
        "open-url",
        help="handle a vantage:// / captureage:// spectate or replay link, or a .vrec file; "
        "hands it to a running Vantage when there is one",
    )
    o.add_argument("url")
    o.add_argument("--port", type=int, default=8740)

    h = ss.add_parser(
        "register-handler",
        help="register Vantage for vantage:// links and .vrec files (writes "
        "$XDG_DATA_HOME/applications/vantage.desktop and a MIME type; on Windows, "
        "per-user keys under HKCU\\Software\\Classes)",
    )
    h.add_argument("--port", type=int, default=8740)
    h.add_argument(
        "--no-update",
        action="store_true",
        help="only write the files; do not run xdg-mime / update-*-database "
        "(on Windows: do not tell Explorer associations changed)",
    )
    h.add_argument(
        "--captureage",
        action="store_true",
        help="also take over captureage:// links, so the game's own 'Spectate with "
        "CaptureAge' buttons open Vantage (the previous handler is remembered)",
    )
    h.add_argument(
        "--release-captureage",
        action="store_true",
        help="give captureage:// links back to the handler they had before --captureage",
    )

    r = ss.add_parser("record", help="record the running game's stream to a .vrec (no UI)")
    r.add_argument("out", type=Path)
    r.add_argument("--replay", help="Windows path of a .aoe2record for the game to play first")
    r.add_argument(
        "--seconds",
        type=float,
        default=0,
        help="stop after this many seconds (0 = until the stream ends)",
    )
    r.add_argument(
        "--quiet-seconds", type=float, default=20, help="stop when no frame arrives for this long"
    )
    r.add_argument("--resolution-ms", type=int, default=100)
    r.add_argument(
        "--speed",
        choices=("SLOW", "NORMAL", "FAST", "EXTRA_FAST"),
        help="replay speed to set once the replay is loaded",
    )
    r.add_argument(
        "--light",
        action="store_true",
        help="the fast-replay stream profile (server.LIGHT_STREAM_*): low-priority and"
        " sleeping units every 2 s, state particles only; --resolution-ms still applies",
    )
    r.add_argument(
        "--minimize", action="store_true", help="minimise the game window while recording"
    )
    r.add_argument(
        "--no-particles",
        action="store_true",
        help="leave out particle effects (smoke, fire, dust): a smaller file",
    )

    i = ss.add_parser("info", help="summarise a .vrec recording")
    i.add_argument("recording", type=Path)
    i.add_argument("--json", action="store_true")

    d = ss.add_parser("doctor", help="check what Vantage can use on this machine")
    d.add_argument("--recordings-dir", type=Path, default=DEFAULT_RECORDINGS)
    d.add_argument("--game-dir", type=Path, help="AoE2 DE install (default: auto-detect)")
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point of the ``vantage`` command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    return run(args)


def run(args: argparse.Namespace) -> int:
    cmd: str = args.command
    if cmd == "serve":
        return _serve(args)
    if cmd == "record":
        return _record(args)
    if cmd == "info":
        return _info(args)
    if cmd == "open-url":
        return _open_url(args)
    if cmd == "register-handler":
        return _register_handler(args)
    if cmd == "doctor":
        return _doctor(args)
    return 2


def parse_spectate_url(url: str) -> dict[str, str]:
    """``captureage://spectate/?lobbyid=…`` or ``?aoe2record=…`` (also ``vantage://``)."""
    from urllib.parse import parse_qs, urlparse

    u = urlparse(url)
    query = u.query or (u.path.lstrip("/?") if "=" in u.path else "")
    return {k: v[0] for k, v in parse_qs(query).items()}


_TRUE = ("1", "true", "yes", "on")


def live_request(url: str) -> dict[str, Any] | None:
    """A spectate link -> :meth:`vantage.server.Session.open_live` arguments.

    ``lobbyid`` (with the lobby's ``source`` platform) spectates a lobby;
    ``aoe2record`` (``cloud=1`` for a cloud replay) plays a replay, switching to
    Return of Rome first when the replay lives in its folder; no parameters
    watch whatever the game shows. None when ``url`` is not a link at all.

    A link never ends a game in progress on its own:
    the game's question goes to the browser ("Continue with request?").
    """
    if "://" not in url and not url.startswith("?"):
        return None
    params = parse_spectate_url(url)
    req: dict[str, Any] = {"confirm": False}
    if params.get("lobbyid"):
        req["lobby"] = params["lobbyid"]
        if params.get("source"):
            req["lobby_source"] = params["source"]
    elif params.get("aoe2record"):
        cloud = params.get("cloud", "").lower() in _TRUE
        rec = params["aoe2record"]
        req["replay"] = rec if cloud else replay_windows_path(rec)
        req["cloud"] = cloud
        if not cloud:
            req["game"] = replay_game(req["replay"])
    return req


def _open_url(args: argparse.Namespace) -> int:
    target = args.url
    if target.lower().endswith(".vrec") and not target.startswith(("vantage:", "captureage:")):
        target = str(Path(target).expanduser().resolve())
    # Single instance: hand the link to a Vantage already serving on this port.
    reply = _post_running(args.port, "/api/open_url", {"url": target})
    if reply is not None:
        print(f"handed to the running Vantage on port {args.port}: {reply}", flush=True)
        if reply.get("ok"):
            # A click on the game's button must bring Vantage up; the server
            # alone has no window to raise.
            webbrowser.open(f"http://127.0.0.1:{args.port}/")
        return 0 if reply.get("ok") else 1
    serve_args = ["serve", "--open", "--port", str(args.port)]
    if target.lower().endswith(".vrec") and "://" not in target:
        serve_args.append(target)
    else:
        req = live_request(target)
        if req is None:
            print(f"not a spectate link or recording: {target}", file=sys.stderr)
            return 2
        serve_args.append("--live")
        if req.get("lobby"):
            serve_args += ["--lobby", req["lobby"]]
            if req.get("lobby_source"):
                serve_args += ["--lobby-source", req["lobby_source"]]
        elif req.get("replay"):
            serve_args += ["--replay", req["replay"]]
            if req.get("cloud"):
                serve_args.append("--cloud")
            if req.get("game"):
                serve_args += ["--game", "ror" if req["game"] == 1 else "aoe2"]
    return main(serve_args)


def _post_running(port: int, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
    """POST to a Vantage server on localhost, or None when none answers."""
    import urllib.error
    import urllib.request

    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + "/api/session", timeout=2) as r:
            if "mode" not in json.loads(r.read() or b"{}"):
                return None  # something else listens on that port
        req = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            got: dict[str, Any] = json.loads(r.read() or b"{}")
            return got
    except (OSError, ValueError, urllib.error.URLError):
        return None


def replay_windows_path(rec: str) -> str:
    """A bare replay name (as the game's button sends) -> its path as the game sees it."""
    if "\\" in rec or "/" in rec:
        return rec
    from vantage.gamedata import windows_path
    from vantage.server import default_replay_dirs

    name = rec if rec.endswith(".aoe2record") else f"{rec}.aoe2record"
    for d in default_replay_dirs():
        if (d / name).is_file():
            return windows_path(d / name)
    return rec


def replay_game(path: str) -> int | None:
    """1 (Return of Rome) for a replay in a ``modes\\Pompeii`` folder, 2 for
    another known replay path, None when it cannot be told."""
    from vantage.server import GAME_AOE2, GAME_ROR

    low = path.replace("/", "\\").lower()
    if "\\modes\\pompeii\\" in low:
        return GAME_ROR
    return GAME_AOE2 if "\\savegame\\" in low else None


def _serve(args: argparse.Namespace) -> int:
    from vantage.gamedata import GameData
    from vantage.native_jobs import NativeConfig
    from vantage.native_session import NativeSession as Session
    from vantage.server import GAME_AOE2, GAME_ROR, default_replay_dirs, serve

    recording = args.recording
    native_replay = getattr(args, "native_replay", None)
    if args.start_file is not None:
        if recording is not None or args.live or native_replay is not None:
            print(
                "give one source: a FILE, --recording, --native-replay or --live", file=sys.stderr
            )
            return 2
        recording = args.start_file
    recording_only = bool(getattr(args, "recording_only", False))
    if recording_only and (args.live or args.replay or args.lobby):
        print("--recording-only cannot open a live game", file=sys.stderr)
        return 2
    native_jobs = None
    native_descriptor = getattr(args, "native_worker", None)
    if native_descriptor is not None:
        if not getattr(args, "experimental_native", False) or not getattr(
            args, "native_worker_sha256", None
        ):
            print(
                "native conversion needs --experimental-native and --native-worker-sha256",
                file=sys.stderr,
            )
            return 2
        from vantage.native import NativeJobs, NativeWorker

        try:
            worker = NativeWorker(native_descriptor.expanduser(), args.native_worker_sha256)
            native_jobs = NativeJobs(worker, args.recordings_dir.expanduser() / "native-cache")
        except (ValueError, OSError) as exc:
            print(f"Cannot import native engine: {exc}", file=sys.stderr)
            return 2
    game_dir = resolve_game_dir(args.game_dir, recording_only=recording_only)
    data = GameData(game_dir)
    rec_dir = args.recordings_dir.expanduser()
    rec_dir.mkdir(parents=True, exist_ok=True)
    session = Session(data, rec_dir)
    # The recordings list names who played: read in the background, cached per file.
    session.summaries.enabled = True
    server = browser_timer = None
    # Every exit below closes what was opened, in this order: a failure before
    # the server is bound submits no conversion and leaves no socket behind.
    try:
        native_options = (
            getattr(args, "native_profile", None),
            getattr(args, "native_profile_sha256", None),
            getattr(args, "native_cache_dir", None),
        )
        native_roots = tuple(getattr(args, "native_replay_root", None) or ())
        native_timeout = getattr(args, "native_timeout", None)
        if (
            any(value is not None for value in native_options)
            or native_replay is not None
            or native_roots
            or native_timeout is not None
        ):
            if not all(value is not None for value in native_options):
                raise ValueError(
                    "local replay playback needs --native-profile, "
                    "--native-profile-sha256 and --native-cache-dir"
                )
            profile, profile_sha256, cache_dir = native_options
            assert profile is not None and profile_sha256 is not None and cache_dir is not None
            session.configure_native(
                NativeConfig(
                    profile,
                    profile_sha256,
                    cache_dir,
                    native_roots,
                    900 if native_timeout is None else native_timeout,
                )
            )
        config = {
            "patch": json.loads(args.patch_config) if args.patch_config else {},
            "force_default": bool(args.force_default_config),
            # The browser reports the end of a recording so the server can exit.
            "exit_on_stream_end": bool(args.exit_on_stream_end),
        }
        override = [d.expanduser() for d in args.replay_dir or ()]
        native_config = getattr(session, "native_config", None)
        dirs = (
            list(native_config.replay_roots)
            if getattr(session, "native", None) is not None and native_config is not None
            else (override or default_replay_dirs())
        )
        server = serve(
            args.host,
            args.port,
            session,
            dirs,
            config,
            follow_live=not override and not recording_only,
            native_jobs=native_jobs,
            recording_only=recording_only,
        )
        if recording:
            session.open_recording(str(recording))
        elif native_replay is not None:
            # The conversion starts once the server is bound.
            session.open_native_replay(native_replay)
        elif args.live:
            session.open_live(
                replay=args.replay,
                lobby=args.lobby,
                record=not args.no_record,
                minimize=args.minimize_game,
                exit_on_end=args.exit_on_stream_end,
                # Ask first: when the game would leave a game
                # in progress, the browser shows "Continue with request?".
                confirm=False,
                game={"aoe2": GAME_AOE2, "ror": GAME_ROR}.get(args.game or ""),
                cloud=args.cloud,
                lobby_source=args.lobby_source,
            )
        if args.exit_on_stream_end:
            bound = server

            def stop_server() -> None:
                threading.Thread(target=bound.shutdown, daemon=True).start()

            if args.live:

                def watch() -> None:
                    session.ended.wait()
                    bound.shutdown()

                threading.Thread(target=watch, daemon=True).start()
            else:
                # A recording ends when the browser reaches its end.
                server.app.on_playback_ended = stop_server  # type: ignore[attr-defined]  # set by serve()
        url = f"http://{args.host}:{args.port}/"
        print(serve_banner(url, game_dir, rec_dir, opening=args.open), flush=True)
        if args.open:
            browser_timer = threading.Timer(0.5, webbrowser.open, (url,))
            browser_timer.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, RuntimeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2
    finally:
        if browser_timer is not None:
            browser_timer.cancel()
        if native_jobs is not None:
            native_jobs.close()
        session.close_native()
        session.stop()
        if server is not None:
            server.server_close()
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from vantage import __version__
    from vantage.doctor import report, run_checks
    from vantage.gamedata import find_game_dir
    from vantage.server import default_replay_dirs

    checks = run_checks(
        args.recordings_dir.expanduser(),
        args.game_dir or find_game_dir(),
        default_replay_dirs(),
    )
    text, code = report(checks)
    print(f"Vantage {__version__}\n\n{text}", flush=True)
    return code


def resolve_game_dir(explicit: Path | None, *, recording_only: bool) -> Path | None:
    """Choose presentation assets: recording-only reads an explicit pack, never discovers one."""
    from vantage.gamedata import find_game_dir

    if explicit is not None:
        return explicit
    return None if recording_only else find_game_dir()


def serve_banner(url: str, game_dir: Path | None, rec_dir: Path, opening: bool) -> str:
    """What ``vantage serve`` prints at start: where to point the browser, and
    what is missing for the full experience."""
    from vantage.certs import LIVE_GAMES_DOCS, certs_dir, missing_cert_files

    lines = [f"Vantage is running at {url}"]
    if not opening:
        lines.append("  Open that address in your browser (or start with --open).")
    lines.append(f"  Recordings: {rec_dir}")
    if game_dir is None:
        lines.append("  Game install: not found -- plainer graphics, no sounds (see --game-dir)")
    elif not (game_dir / "AoE2DE_s.exe").is_file():
        lines.append(f"  Game install: no AoE2DE_s.exe in {game_dir} -- is that the game folder?")
    else:
        lines.append(f"  Game install: {game_dir}")
    missing = missing_cert_files()
    if missing:
        lines.append(f"  Live games and replays: certificate files missing from {certs_dir()}")
        lines.append(f"    ({', '.join(missing)}; see {LIVE_GAMES_DOCS})")
    lines.append("Press Ctrl+C to stop.")
    return "\n".join(lines)


def _command_prefix() -> list[str]:
    """How to run ``vantage`` again from a desktop entry."""
    exe = shutil.which("vantage")
    if exe:
        return [exe]
    return [sys.executable, "-m", "vantage"]


def _register_handler(args: argparse.Namespace) -> int:
    """Register Vantage for ``vantage://`` links and ``*.vrec`` files.

    Writes ``$XDG_DATA_HOME/applications/vantage.desktop`` and
    ``$XDG_DATA_HOME/mime/packages/vantage-recording.xml``, then (unless
    ``--no-update``) makes them the defaults with ``xdg-mime`` and refreshes
    the desktop and MIME databases. ``captureage://`` is left alone unless
    ``--captureage`` is given. Windows: see :func:`_register_windows`.
    """
    if sys.platform == "win32":
        return _register_windows(args)
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    apps = home / "applications"
    mime_dir = home / "mime" / "packages"
    previous_file = home / "vantage" / "captureage-previous-handler"
    if args.release_captureage:
        previous = previous_file.read_text().strip() if previous_file.is_file() else ""
        if not previous:
            print("no previous captureage:// handler recorded; nothing to restore", flush=True)
            return 1
        _run_steps(
            [
                ["xdg-mime", "default", previous, f"x-scheme-handler/{CAPTUREAGE_SCHEME}"],
                _portal_choice("DeletePermission"),
            ]
        )
        print(f"captureage:// links go to {previous} again", flush=True)
        return 0
    apps.mkdir(parents=True, exist_ok=True)
    mime_dir.mkdir(parents=True, exist_ok=True)
    prefix = _command_prefix()
    if shutil.which("systemd-run") is not None:
        # Links from the game arrive through xdg-desktop-portal; without a scope
        # of its own Vantage would inherit the portal's cgroup and its memory cap.
        prefix = ["systemd-run", "--user", "--scope", "--slice=app.slice", "--quiet", *prefix]
    cmd = " ".join(shlex.quote(c) for c in prefix)
    desktop = apps / DESKTOP_FILE
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Vantage\n"
        "Comment=AoE2 DE spectator and replay analyser\n"
        f"Exec={cmd} open-url --port {args.port} %u\n"
        "Terminal=false\n"
        "NoDisplay=true\n"
        "Categories=Game;\n"
        f"MimeType=x-scheme-handler/{SCHEME};{RECORDING_MIME};"
        + (f"x-scheme-handler/{CAPTUREAGE_SCHEME};" if args.captureage else "")
        + "\n"
    )
    mime = mime_dir / "vantage-recording.xml"
    mime.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
        f'  <mime-type type="{RECORDING_MIME}">\n'
        "    <comment>Vantage recording</comment>\n"
        '    <glob pattern="*.vrec"/>\n'
        "  </mime-type>\n"
        "</mime-info>\n"
    )
    print(f"wrote {desktop}\nwrote {mime}", flush=True)
    if args.no_update:
        return 0
    steps = [
        ["update-mime-database", str(home / "mime")],
        ["update-desktop-database", str(apps)],
        ["xdg-mime", "default", DESKTOP_FILE, f"x-scheme-handler/{SCHEME}"],
        ["xdg-mime", "default", DESKTOP_FILE, RECORDING_MIME],
    ]
    if args.captureage:
        # Remember who handled captureage:// so --release-captureage can undo this.
        if shutil.which("xdg-mime") is not None:
            query = ["xdg-mime", "query", "default", f"x-scheme-handler/{CAPTUREAGE_SCHEME}"]
            got = subprocess.run(query, capture_output=True, text=True, check=False)
            current = got.stdout.strip()
            if current and current != DESKTOP_FILE:
                previous_file.parent.mkdir(parents=True, exist_ok=True)
                previous_file.write_text(current + "\n")
                print(f"captureage:// was handled by {current} (remembered)", flush=True)
        steps.append(["xdg-mime", "default", DESKTOP_FILE, f"x-scheme-handler/{CAPTUREAGE_SCHEME}"])
        steps.append(_portal_choice("SetPermission"))
    _run_steps(steps)
    return 0


def _register_windows(args: argparse.Namespace) -> int:
    """Per-user ``HKCU\\Software\\Classes`` keys: the ``vantage`` URL protocol,
    ``.vrec`` -> :data:`RECORDING_PROGID`, and with ``--captureage`` the
    ``captureage`` protocol's command. The command it replaces is saved so
    ``--release-captureage`` restores it, or, when there was no per-user one,
    deletes the per-user key so a machine-wide registration shows again."""
    from vantage.gamedata import registry_value

    previous_file = local_data_dir() / "captureage-previous-handler"
    ca_key = f"{CLASSES_KEY}\\{CAPTUREAGE_SCHEME}"
    ca_command_key = ca_key + "\\shell\\open\\command"
    if args.release_captureage:
        if not previous_file.is_file():
            print("no previous captureage:// handler recorded; nothing to restore", flush=True)
            return 1
        previous = previous_file.read_text(encoding="utf-8").strip()
        if previous:
            _reg_set(ca_command_key, "", previous)
            print(f"captureage:// links go to {previous} again", flush=True)
        else:
            for sub in ("\\shell\\open\\command", "\\shell\\open", "\\shell", ""):
                _reg_delete(ca_key + sub)
            print("captureage:// links go to the machine-wide handler (if any) again", flush=True)
        previous_file.unlink()
        if not args.no_update:
            _notify_associations_changed()
        return 0
    command = " ".join(f'"{c}"' for c in _command_prefix()) + f' open-url --port {args.port} "%1"'
    vantage_key = f"{CLASSES_KEY}\\{SCHEME}"
    _reg_set(vantage_key, "", "URL:Vantage link")
    _reg_set(vantage_key, "URL Protocol", "")
    _reg_set(vantage_key + "\\shell\\open\\command", "", command)
    progid_key = f"{CLASSES_KEY}\\{RECORDING_PROGID}"
    _reg_set(progid_key, "", "Vantage recording")
    _reg_set(progid_key + "\\shell\\open\\command", "", command)
    _reg_set(f"{CLASSES_KEY}\\.vrec", "", RECORDING_PROGID)
    print(f"registered {SCHEME}:// and .vrec: {command}", flush=True)
    if args.captureage:
        current = registry_value("HKCU", ca_command_key)
        if current != command:
            # Remember who handled captureage:// so --release-captureage can undo this.
            was = current if isinstance(current, str) else ""
            previous_file.parent.mkdir(parents=True, exist_ok=True)
            previous_file.write_text(was + "\n", encoding="utf-8")
            print(
                f"captureage:// was handled by {was or 'no per-user handler'} (remembered)",
                flush=True,
            )
        if registry_value("HKCU", ca_key) is None:
            _reg_set(ca_key, "", "URL:CaptureAge link")
        _reg_set(ca_key, "URL Protocol", "")
        _reg_set(ca_command_key, "", command)
        print(f"{CAPTUREAGE_SCHEME}:// links go to Vantage", flush=True)
    if not args.no_update:
        _notify_associations_changed()
    return 0


def _reg_set(key: str, name: str, value: str) -> None:
    """Write a string value under ``HKCU\\<key>``, creating the key."""
    if sys.platform == "win32":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _reg_delete(key: str) -> None:
    """Delete ``HKCU\\<key>`` when it exists and has no subkeys."""
    if sys.platform == "win32":
        import winreg

        with contextlib.suppress(OSError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


def _notify_associations_changed() -> None:
    """``SHChangeNotify(SHCNE_ASSOCCHANGED)``: Explorer re-reads associations."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def _portal_choice(method: str) -> list[str]:
    """The game's links reach the desktop through xdg-desktop-portal's OpenURI.
    With two apps claiming ``captureage://`` (Vantage and the previous handler)
    and no remembered choice, the portal shows an app chooser instead of opening
    either. Record Vantage as the remembered choice for unsandboxed callers
    (app id "", as the game under Steam is): ``[app, count, threshold]`` with
    count >= threshold skips the chooser. ``DeletePermission`` forgets it."""
    store = "org.freedesktop.impl.portal.PermissionStore"
    base = ["busctl", "--user", "call", store, "/" + store.replace(".", "/"), store, method]
    content = f"x-scheme-handler/{CAPTUREAGE_SCHEME}"
    app = DESKTOP_FILE.removesuffix(".desktop")
    if method == "SetPermission":
        return [*base, "sbssas", "desktop-used-apps", "true", content, "", "3", app, "3", "3"]
    return [*base, "sss", "desktop-used-apps", content, ""]


def _run_steps(steps: list[list[str]]) -> None:
    for step in steps:
        if shutil.which(step[0]) is None:
            print(f"skipped (not installed): {' '.join(step)}", flush=True)
            continue
        done = subprocess.run(step, capture_output=True, text=True, check=False)
        print(f"{' '.join(step)} -> {done.returncode}", flush=True)


def _record(args: argparse.Namespace) -> int:
    import queue

    from vantage.frames import Frame, RecordingWriter
    from vantage.live import LiveGame
    from vantage.server import mode_from_path

    game = LiveGame().connect(timeout=10)
    info = game.info()
    print(f"connected: game {info.game_version}, api {info.api_version}", flush=True)
    if args.replay:
        # The command itself is the user's agreement to leave a running game:
        # load_replay's default (confirm=None) asks, then confirms.
        print(f"LoadGame -> {game.load_replay(args.replay)}", flush=True)
    if args.minimize:
        with contextlib.suppress(Exception):
            game.set_window("MINIMIZED")
    q: queue.Queue[Frame | None] = queue.Queue(maxsize=5000)

    # Particle effects (smoke, fire, dust, impacts) are streamed only when asked
    # for by name: every effect the installed game defines.
    whitelist: list[str] = []
    if not args.no_particles:
        from vantage.gamedata import GameData, find_game_dir

        whitelist = GameData(find_game_dir()).particle_definitions
        if args.light:
            from vantage.server import light_particles

            whitelist = light_particles(whitelist)

    def pump() -> None:
        try:
            from vantage.server import LIGHT_STREAM_CATEGORIES

            for f in game.frames(
                resolution_ms=args.resolution_ms,
                particles=bool(whitelist),
                particle_whitelist=whitelist or None,
                **({"category_ms": LIGHT_STREAM_CATEGORIES} if args.light else {}),
            ):
                q.put(f)
        finally:
            q.put(None)

    threading.Thread(target=pump, daemon=True).start()
    # Ctrl+C / SIGTERM end the recording cleanly (the file is closed and
    # complete). A plain KeyboardInterrupt is not reliable here: the gRPC
    # stream thread can keep the main thread from seeing it.
    stop = threading.Event()
    signals = [signal.SIGINT, signal.SIGTERM]
    if sys.platform == "win32":
        signals.append(signal.SIGBREAK)  # Ctrl+Break in a Windows console
    previous = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in signals}
    n = 0
    t0 = time.monotonic()
    last = t0
    heard = t0
    # The game takes a speed only once the replay is running: asked again every
    # 2 s once frames flow, on a short-lived connection of its own (the game
    # serves one stream per connection).
    speed_set = not args.speed
    speed_tried = 0.0
    with RecordingWriter(
        args.out,
        {
            "source": "live",
            "replay": args.replay,
            "game_version": info.game_version,
            "game_mode": mode_from_path(info.selected_mode),
        },
    ) as w:
        while not stop.is_set():
            try:
                f = q.get(timeout=0.5)
            except queue.Empty:
                if time.monotonic() - heard > args.quiet_seconds:
                    print("stream quiet: stopping", flush=True)
                    break
                continue
            if f is None:
                break
            w.write(f)
            n += 1
            now = heard = time.monotonic()
            if not speed_set and now - speed_tried > 2:
                speed_tried = now
                with contextlib.suppress(Exception):
                    ctl = LiveGame().connect(timeout=3)
                    try:
                        speed_set = ctl.set_speed(args.speed)
                    finally:
                        ctl.close()
                if speed_set:
                    at = f"{now - t0:6.0f}s  speed {args.speed} set at game {f.time / 1000:.0f}s"
                    print(at, flush=True)
            if now - last > 10:
                w.flush()
                last = now
                print(f"{now - t0:6.0f}s  frames={n}  game={f.time / 1000:.0f}s", flush=True)
            if args.seconds and now - t0 > args.seconds:
                break
    for sig, handler in previous.items():
        signal.signal(sig, handler)
    game.close()
    print(f"wrote {n} frames to {args.out}", flush=True)
    return 0


def _info(args: argparse.Namespace) -> int:
    from vantage.frames import read_header
    from vantage.gamedata import GameData, find_game_dir
    from vantage.timeline import load_recording

    header = read_header(args.recording)
    data = GameData(find_game_dir(), mode=header.get("game_mode"))
    tl = load_recording(str(args.recording), data)
    out: dict[str, Any] = {
        "header": header,
        "status": tl.status(),
        "match": tl.match,
        "summary": tl.summary(),
        "events": len(tl.events),
    }
    if args.json:
        json.dump(out, sys.stdout, indent=1, default=str)
        print()
        return 0
    st = tl.status()
    minutes = st["end"] / 60000
    print(f"{args.recording}: {st['frames']} frames, {minutes:.1f} game-min, errors={st['errors']}")
    print(f"map: {tl.match.get('map_file')}  size: {tl.match.get('map_size')}")
    for pid, s in out["summary"].items():
        if not pid.isdigit():
            continue  # "teams_most_created" rides along at the top level
        p = tl.match["players"].get(int(pid), {})
        print(
            f"  P{pid} {p.get('name', '?'):<22} {p.get('civ_name', ''):<12} {s['status']:<9} "
            f"K/D {s['kills']}/{s['deaths']}  collected {s['collected']['total']}  "
            f"ages {[round(t / 60000, 1) for t in s['age_times'].values()]}"
        )
    return 0
