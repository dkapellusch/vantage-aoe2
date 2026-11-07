#!/usr/bin/env python3
"""Serve an experimental local replay through Vantage's isolated native backend."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts/game-internals/2026-10-18-world-envelope"
LAUNCHER = (
    ROOT / "src/vantage/native_isolated_launch.py"
)  # this package's port of the research launcher
# Re-pinned 2026-11-07 (tools/native_profile_repin.py): Wine was upgraded, and the development
# copy's forge/spectate became an alias of this package, so the exact sources each profile was
# verified with are restored into its repinned-2026-11-07/frozen-sources (research_root).
# The originals are kept as evidence.
DEFAULT_PROFILE = (
    ARTIFACTS
    / "native-local-conversion-current-encoder-v1/repinned-2026-11-07/experimental-profile.json"
)
DEFAULT_SHA = "7ff27c0446d9f919d2671fc99eb6c382f1d36f689c3d71b6b392c75944870a93"
LOCALIZED_PROFILE = (
    ARTIFACTS
    / "native-current-localization-candidate-v1/repinned-2026-11-07"
    / "master-storage-profile.proposed.json"
)
LOCALIZED_SHA = "a1e5199cbb7babbb44a08ba82b56ec5e8d2301d3f0cc4ff02df555871edbe737"
BUILTIN_PROFILES = {
    "default": (DEFAULT_PROFILE, DEFAULT_SHA),
    "localized": (LOCALIZED_PROFILE, LOCALIZED_SHA),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Experimental: this exact profile supports one pinned game build; "
            "multiplayer conversions may fail and initial conversion can take many minutes. "
            "The server uses localhost; open its displayed URL in your browser."
        ),
    )
    parser.add_argument("replay", type=Path, help="local .aoe2record file")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "vantage-native",
    )
    parser.add_argument("--game-dir", type=Path, help="installed game data directory")
    parser.add_argument(
        "--replay-root",
        type=Path,
        action="append",
        default=[],
        help="directory available to the replay browser; repeat as needed",
    )
    parser.add_argument("--port", type=int, default=8740)
    parser.add_argument("--timeout", type=float, default=1800, help="per-phase timeout in seconds")
    profile_choice = parser.add_mutually_exclusive_group()
    profile_choice.add_argument(
        "--profile-name",
        choices=BUILTIN_PROFILES,
        help="built-in experimental profile (default: default)",
    )
    profile_choice.add_argument("--profile", type=Path, help="alternative experimental profile")
    parser.add_argument("--profile-sha256", help="exact SHA-256 of the alternative profile")
    args = parser.parse_args()
    if (args.profile is None) != (args.profile_sha256 is None):
        parser.error("--profile and --profile-sha256 must be supplied together")
    profile, expected = (
        (args.profile, args.profile_sha256)
        if args.profile
        else BUILTIN_PROFILES[args.profile_name or "default"]
    )
    try:
        profile = profile.expanduser().resolve(strict=True)
        with profile.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        replay = args.replay.expanduser().resolve(strict=True)
    except OSError as error:
        parser.error(str(error))
    if actual != expected:
        parser.error("profile hash differs; use a validated profile and its exact SHA-256")
    if not replay.is_file() or replay.suffix.lower() != ".aoe2record":
        parser.error("replay must be an existing .aoe2record file")
    if not LAUNCHER.is_file():
        parser.error("isolated native launcher is missing from this checkout")
    argv = [
        sys.executable,
        "-B",
        str(LAUNCHER),
        "--replay",
        str(replay),
        "--profile",
        str(profile),
        "--profile-sha256",
        expected,
        "--cache-dir",
        str(args.cache_dir),
        "--port",
        str(args.port),
        "--timeout",
        str(args.timeout),
    ]
    if args.profile is None and args.profile_name is None:
        taunt_profile, taunt_sha = BUILTIN_PROFILES["localized"]
        argv += ["--taunt-profile", str(taunt_profile), "--taunt-profile-sha256", taunt_sha]
    if args.game_dir is not None:
        argv += ["--game-dir", str(args.game_dir)]
    for root in args.replay_root:
        argv += ["--replay-root", str(root)]
    environment = dict(os.environ)
    environment.pop("DISPLAY", None)
    environment.pop("WAYLAND_DISPLAY", None)
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + existing if existing else "")
    os.execve(sys.executable, argv, environment)


if __name__ == "__main__":
    main()
