#!/usr/bin/env python3
"""Open a local replay with the experimental, isolated V32 backend."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROFILES = (
    ROOT
    / "artifacts/game-internals/2026-10-18-world-envelope"
    / "native-v32-file-diagnostics-stderr-v1"
)
SOURCE_SHA = "8304b4c3823e94eb935fcbb68e8345e22af5be9c5619728df3bae23a02a959c2"
RUNTIME_SHA = "b9227cb713737fe8dea8a3c4d5776baf051b56f55281eea42f96774b4b477d31"
ENCODER_SHA = "0c30e4d16c400b3d38d58377c2b1dc443340ee5bc51c38cb2d890ccb5c7f1946"
FAST_ENCODER_SHA = "5b08fd2ee6a91b9eed1987fd3ba8b02ad8ec9d4d52d716204f5b2e8b57465e20"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "This experimental entry point uses research profiles pinned to this host. "
            "Multiplayer replays can fail their original checksums; initial conversion "
            "can take many minutes. Open the displayed localhost URL in a browser."
        ),
    )
    parser.add_argument("replay", type=Path, help="local .aoe2record file")
    parser.add_argument("--game-dir", type=Path, help="installed game data directory")
    parser.add_argument(
        "--replay-root",
        type=Path,
        action="append",
        default=[],
        help="directory available in the replay browser; repeat as needed",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
        / "vantage"
        / "v32",
    )
    parser.add_argument("--port", type=int, default=8740)
    parser.add_argument("--runtime-timeout", type=float, help="override runtime timeout in seconds")
    parser.add_argument("--encoder-timeout", type=float, help="override encoder timeout in seconds")
    parser.add_argument("--update-cap", type=int, help="maximum simulation updates for new jobs")
    parser.add_argument(
        "--fast-encoder",
        action="store_true",
        help="use the separately verified experimental faster encoder",
    )
    parser.add_argument("--reuse-job", type=Path, help="revalidate one existing completed V32 job")
    args = parser.parse_args()
    try:
        replay = args.replay.expanduser().resolve(strict=True)
    except OSError as error:
        parser.error(str(error))
    if not replay.is_file() or replay.suffix.lower() != ".aoe2record":
        parser.error("replay must be an existing .aoe2record file")

    encoder = "encoder-fast-config.json" if args.fast_encoder else "encoder-config.json"
    encoder_sha = FAST_ENCODER_SHA if args.fast_encoder else ENCODER_SHA
    argv = [
        sys.executable,
        "-B",
        "-m",
        "vantage.native_v32_serve",
        "--replay",
        str(replay),
        "--replay-root",
        str(replay.parent),
        "--source-profile",
        str(PROFILES / "source-profile.json"),
        "--source-profile-sha256",
        SOURCE_SHA,
        "--runtime-profile",
        str(PROFILES / "runtime-profile.json"),
        "--runtime-profile-sha256",
        RUNTIME_SHA,
        "--encoder-config",
        str(PROFILES / encoder),
        "--encoder-config-sha256",
        encoder_sha,
        "--cache-dir",
        str(args.cache_dir),
        "--port",
        str(args.port),
    ]
    if args.runtime_timeout is not None:
        argv += ["--runtime-timeout", str(args.runtime_timeout)]
    if args.encoder_timeout is not None:
        argv += ["--encoder-timeout", str(args.encoder_timeout)]
    if args.update_cap is not None:
        argv += ["--update-cap", str(args.update_cap)]
    roots = {replay.parent}
    for root in args.replay_root:
        try:
            resolved = root.expanduser().resolve(strict=True)
        except OSError as error:
            parser.error(str(error))
        if not resolved.is_dir():
            parser.error(f"replay root is not a directory: {resolved}")
        if resolved not in roots:
            argv += ["--replay-root", str(resolved)]
            roots.add(resolved)
    if args.game_dir is not None:
        argv += ["--game-dir", str(args.game_dir)]
    if args.reuse_job is not None:
        argv += ["--reuse-job", str(args.reuse_job)]
    environment = dict(os.environ)
    environment.pop("DISPLAY", None)
    environment.pop("WAYLAND_DISPLAY", None)
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + existing if existing else "")
    os.execve(sys.executable, argv, environment)


if __name__ == "__main__":
    main()
