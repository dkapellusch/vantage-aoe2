"""Serve the normal Vantage replay Session with an explicit V32 backend.

This experimental local entrypoint does not start or connect to the game.
"""

from __future__ import annotations

import argparse
import functools
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .chat_playback import load_with_recorded_chat
from .cli import DEFAULT_RECORDINGS
from .gamedata import GameData, find_game_dir
from .native_session import NativeSession
from .native_v32_config import V32Config
from .server import serve

if TYPE_CHECKING:
    from typing import TYPE_CHECKING


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, help="queue a local .aoe2record at startup")
    parser.add_argument("--replay-root", type=Path, action="append", default=[])
    parser.add_argument("--source-profile", type=Path, required=True)
    parser.add_argument("--source-profile-sha256", required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--runtime-profile-sha256", required=True)
    parser.add_argument("--encoder-config", type=Path, required=True)
    parser.add_argument("--encoder-config-sha256", required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--reuse-job", type=Path, help="revalidate a completed V32 job")
    parser.add_argument("--runtime-timeout", type=float, default=2400)
    parser.add_argument("--encoder-timeout", type=float, default=1800)
    parser.add_argument(
        "--update-cap",
        type=int,
        help="override the automatically selected update limit for new jobs",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8740)
    parser.add_argument("--game-dir", type=Path)
    parser.add_argument("--recordings-dir", type=Path, default=DEFAULT_RECORDINGS)
    return parser


def main(argv: Any = None) -> None:
    args = build_parser().parse_args(argv)
    config = V32Config(
        args.source_profile,
        args.source_profile_sha256,
        args.cache_dir,
        tuple(args.replay_root),
        args.runtime_profile,
        args.runtime_profile_sha256,
        args.encoder_config,
        args.encoder_config_sha256,
        runtime_timeout=args.runtime_timeout,
        encoder_timeout=args.encoder_timeout,
        reuse_job=args.reuse_job,
        update_cap=args.update_cap,
    )
    game_dir = args.game_dir or find_game_dir()
    recordings = args.recordings_dir.expanduser()
    recordings.mkdir(parents=True, exist_ok=True)
    session = NativeSession(GameData(game_dir), recordings)
    server = None
    try:
        session.configure_native(
            config,
            loader=functools.partial(
                load_with_recorded_chat, chat_cache_root=config.cache_dir / "recorded-chat-v1"
            ),
        )
        server = serve(
            args.host,
            args.port,
            session,
            list(config.replay_roots),
            {"patch": {}, "force_default": False, "exit_on_stream_end": False},
            follow_live=False,
        )
        if args.replay is not None:
            session.open_native_replay(args.replay)
        print(f"Vantage on http://{args.host}:{args.port}/ (experimental V32 replay)", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        session.close_native()
        session.stop()
        if server is not None:
            server.server_close()


if __name__ == "__main__":
    main()
