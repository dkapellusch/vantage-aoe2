"""Experimental localhost Vantage server using only isolated native replay jobs.

What vantage-native.py runs. Ported from the development copy's research launcher
(artifacts/.../native-isolated-session-v1/launch_vantage.py) to start this
package's own server (``vantage serve``) instead of the development CLI.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from vantage.native_isolated import IsolatedConversion


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--taunt-profile", type=Path)
    parser.add_argument("--taunt-profile-sha256")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, action="append", default=[])
    parser.add_argument("--game-dir", type=Path)
    parser.add_argument("--port", type=int, default=8740)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    if (args.taunt_profile is None) != (args.taunt_profile_sha256 is None):
        parser.error("--taunt-profile and --taunt-profile-sha256 must be supplied together")
    replay = args.replay.expanduser().resolve(strict=True)
    profile = args.profile.expanduser().resolve(strict=True)
    cache = args.cache_dir.expanduser().resolve()
    repo = Path(__file__).resolve().parents[2]  # src/vantage/this.py -> the repository
    protected: tuple[Any, ...] = (repo, replay, profile, Path("/usr"), Path("/etc"), Path("/var"))
    if args.taunt_profile is not None:
        protected += (args.taunt_profile.expanduser().resolve(),)
    if any(path.is_relative_to(cache) for path in protected):
        parser.error("cache directory overlaps a protected input or system directory")
    if not 1 <= args.port <= 65535 or not 0 < args.timeout <= 86400:
        parser.error("invalid port or conversion timeout")
    roots = args.replay_root or [replay.parent]
    os.environ["XDG_CACHE_HOME"] = str(cache / "app-cache")
    os.environ["VANTAGE_DATA_DIR"] = str(cache / "app-data")
    # This process-local injection leaves the profile-pinned application files untouched.
    from vantage.native_jobs import NativeConfig

    taunt_profile = (
        (args.taunt_profile.expanduser().resolve(), args.taunt_profile_sha256)
        if args.taunt_profile is not None
        else None
    )
    # Injected for this process only.
    NativeConfig.converter = lambda config: IsolatedConversion(  # type: ignore[method-assign,assignment]
        config, taunt_profile=taunt_profile
    )
    from vantage.cli import main as serve_main

    argv = [
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
        "--native-replay",
        str(replay),
        "--native-profile",
        str(profile),
        "--native-profile-sha256",
        args.profile_sha256,
        "--native-cache-dir",
        str(cache),
        "--native-timeout",
        str(args.timeout),
        "--recordings-dir",
        str(cache / "recordings"),
    ]
    for root in roots:
        argv += ["--native-replay-root", str(root)]
    if args.game_dir is not None:
        argv += ["--game-dir", str(args.game_dir.expanduser().resolve(strict=True))]
    return serve_main(argv)


if __name__ == "__main__":
    sys.exit(main())
