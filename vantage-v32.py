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
# The runtime and encoder profiles were re-pinned on 2026-11-07 (tools/native_profile_repin.py)
# after a system upgrade replaced the pinned Wine, bwrap and Xvfb. The encoder runs the exact
# development-copy sources it was verified with, restored into repinned-2026-11-07/frozen-sources
# (that copy's forge.spectate is now an alias of this package). The originals beside them are
# kept as evidence; the source profile still holds as pinned.
REPINNED = PROFILES / "repinned-2026-11-07"
SOURCE_SHA = "8304b4c3823e94eb935fcbb68e8345e22af5be9c5619728df3bae23a02a959c2"
RUNTIME_SHA = "f025eb4a0982fc1a06127730c17142976db28b715f2a753c3bb0f1d5c76044bd"
ENCODER_SHA = "8b4d1d2cabf3181f11b85bd5f69101d7d4ad575a37c631021dac7d5138ba9818"
FAST_ENCODER_SHA = "771664e68dbcb22c9f389924600e7368e1da954b054612870dd1ce68824c7e3d"


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
        str(REPINNED / "runtime-profile.json"),
        "--runtime-profile-sha256",
        RUNTIME_SHA,
        "--encoder-config",
        str(REPINNED / encoder),
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
