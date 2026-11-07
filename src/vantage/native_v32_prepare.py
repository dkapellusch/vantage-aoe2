"""Experimental V32 source staging from a caller-pinned local asset profile.

This prepares and compiles an isolated worker; it does not run the worker,
validate replay fidelity, publish a VREC, or configure the normal game.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import signal
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from vantage import native_v32_input
from vantage.native_conversion import pin
from vantage.native_v32_input import prepare_v32_input


class V32PreparationError(RuntimeError):
    """No compiled worker is admitted if staging fails."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V32PreparationError(message)


def _checked_pin(row: dict[Any, Any]) -> dict[Any, Any]:
    _require(
        type(row) is dict
        and set(row) == {"path", "bytes", "sha256"}
        and type(row["path"]) is str
        and type(row["bytes"]) is int
        and row["bytes"] >= 0
        and type(row["sha256"]) is str
        and len(row["sha256"]) == 64
        and all(c in "0123456789abcdef" for c in row["sha256"]),
        "Invalid source pin",
    )
    path = Path(row["path"])
    _require(path.is_absolute() and path.resolve(strict=True) == path, "Noncanonical source path")
    _require(pin(path) == row, f"Pinned source changed: {path}")
    return row


def _relative(name: str) -> Path:
    _require(type(name) is str and name != "", "Empty source path")
    path = PurePosixPath(name)
    _require(
        not path.is_absolute()
        and str(path) == name
        and all(x not in (".", "..") for x in path.parts),
        "Invalid source-relative path",
    )
    return Path(*path.parts)


def prepare_v32_worker(
    replay: Path,
    out: Path,
    *,
    profile: Path,
    profile_sha256: str,
    update_cap: int = 262144,
    runtime_source_root: Path | None = None,
    compile_timeout: float = 180,
) -> dict[Any, Any]:
    """Prepare one fresh source tree and compile its pinned worker.

    The profile is an explicitly pinned local recipe, not a compatibility claim.
    Failures preserve the job directory and do not produce a success receipt.
    The optional runtime path supports a separately managed private mount alias.
    """
    profile = profile.resolve(strict=True)
    profile_pin = pin(profile)
    stager_sources = [pin(Path(__file__).resolve()), pin(Path(native_v32_input.__file__).resolve())]
    _require(profile_pin["sha256"] == profile_sha256, "Staging profile hash differs")
    profile_bytes = profile.read_bytes()
    _require(
        hashlib.sha256(profile_bytes).hexdigest() == profile_pin["sha256"],
        "Staging profile changed while reading",
    )
    recipe = json.loads(profile_bytes)
    _require(
        type(recipe) is dict
        and recipe.get("kind") == "vantage_experimental_v32_source"
        and type(recipe.get("version")) is int
        and recipe.get("version") == 1,
        "Unsupported staging profile",
    )
    _require(
        type(compile_timeout) in (int, float) and 0 < compile_timeout <= 3600, "Invalid timeout"
    )
    host = _checked_pin(recipe["host"])
    config = _checked_pin(recipe["config_template"])
    compiler = _checked_pin(recipe["compiler"])
    _require(
        Path(compiler["path"]) == Path("/usr/bin/x86_64-w64-mingw32-g++").resolve(),
        "Unsupported compiler",
    )
    base = Path(recipe["source_root"])
    _require(
        base.is_absolute() and base.resolve(strict=True) == base and base.is_dir(),
        "Invalid source root",
    )
    rows = recipe["sources"]
    _require(type(rows) is list and bool(rows), "Missing pinned sources")
    names: set[str] = set()
    source_pins = []
    generated_names = {
        "host.cpp",
        "prepared_config.h",
        "entity_expectations.h",
        "input-save.inflated.bin",
        "native_input_profile.h",
        "descriptor.json",
        "vantage-native-input-derived.exe",
    }
    for row in rows:
        _require(type(row) is dict and set(row) == {"relative", "pin"}, "Invalid source entry")
        relative = _relative(row["relative"])
        _require(
            row["relative"] not in names and row["relative"] not in generated_names,
            "Duplicate or generated source",
        )
        names.add(row["relative"])
        expected = _checked_pin(row["pin"])
        _require(Path(expected["path"]) == base / relative, "Source is outside its declared root")
        source_pins.append(expected)
    raw_placeholder = _relative(recipe["raw_dat_placeholder"])
    _require(str(raw_placeholder) in names, "Raw DAT placeholder is not pinned")
    replay = replay.resolve(strict=True)
    replay_pin = pin(replay)
    out = out.resolve()
    source = out / "source"
    generated = out / "generated"
    runtime_source_root = source if runtime_source_root is None else runtime_source_root.resolve()
    _require(not out.exists(), "Output directory already exists")
    out.mkdir(parents=True, exist_ok=False)
    source.mkdir()
    copies = []
    for row, original in zip(rows, source_pins, strict=True):
        target = source / _relative(row["relative"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original["path"], target)
        copy = pin(target)
        _require(
            (copy["bytes"], copy["sha256"]) == (original["bytes"], original["sha256"]),
            "Source copy differs",
        )
        copies.append(copy)
    _require((source / raw_placeholder).stat().st_size == 0, "Raw DAT placeholder must be empty")
    (source / "owned-localization").mkdir(exist_ok=True)
    facts = prepare_v32_input(
        replay,
        generated,
        config_template=Path(config["path"]),
        update_cap=update_cap,
        source_root=runtime_source_root,
    )
    _require(facts["recording_sha256"] == replay_pin["sha256"], "Recording changed")
    input_names = generated_names - {"host.cpp", "vantage-native-input-derived.exe"}
    generated_paths = list(generated.iterdir())
    _require(
        {path.name for path in generated_paths} == input_names
        and all(path.is_file() for path in generated_paths),
        "Unexpected generated input",
    )
    for path in generated_paths:
        shutil.copyfile(path, source / path.name)
    shutil.copyfile(host["path"], source / "host.cpp")
    host_copy = pin(source / "host.cpp")
    _require(
        (host_copy["bytes"], host_copy["sha256"]) == (host["bytes"], host["sha256"]),
        "Host copy differs",
    )
    worker = source / "vantage-native-input-derived.exe"
    command = [
        compiler["path"],
        "-std=c++20",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-static",
        "-municode",
        "-Wl,--image-base,0x180000000",
        str(source / "host.cpp"),
        "-lbcrypt",
        "-o",
        str(worker),
    ]
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TMPDIR": str(out)}
    child = subprocess.Popen(
        command,
        cwd=out,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        try:
            stdout, stderr = child.communicate(timeout=compile_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGTERM)
            try:
                stdout, stderr = child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                stdout, stderr = child.communicate()
    except BaseException:
        if child.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        raise
    (out / "compile.stdout").write_bytes(stdout)
    (out / "compile.stderr").write_bytes(stderr)
    _require(not timed_out, "Compiler timed out")
    _require(child.returncode == 0, "Worker compilation failed; see compile.stderr")
    _require(
        pin(profile) == profile_pin and pin(replay) == replay_pin, "Profile or recording changed"
    )
    _require(
        all(pin(Path(row["path"])) == row for row in stager_sources),
        "Staging source changed",
    )
    for row in (host, config, compiler, *source_pins):
        _checked_pin(row)
    for row in copies:
        _require(pin(Path(row["path"])) == row, "Copied source changed")
    _require(pin(source / "host.cpp") == host_copy, "Host copy changed")
    generated_pins = [pin(path) for path in sorted(generated.iterdir())]
    for row in generated_pins:
        actual = pin(source / Path(row["path"]).name)
        _require(
            (actual["bytes"], actual["sha256"]) == (row["bytes"], row["sha256"]),
            "Generated input changed",
        )
    result = {
        "kind": "vantage_experimental_v32_staged_worker",
        "profile": profile_pin,
        "stager_sources": stager_sources,
        "recording": replay_pin,
        "host": pin(source / "host.cpp"),
        "worker": pin(worker),
        "source_root": str(source),
        "runtime_source_root": str(runtime_source_root),
        "generated": generated_pins,
        "copied_sources": copies,
        "input_facts": facts,
        "compiler_command": command,
        "native_execution": False,
        "native_compatibility_verified": False,
    }
    with (out / "stage.json").open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--update-cap", type=int, default=262144)
    parser.add_argument("--runtime-source-root", type=Path)
    parser.add_argument("--compile-timeout", type=float, default=180)
    args = parser.parse_args()
    result = prepare_v32_worker(
        args.replay,
        args.out,
        profile=args.profile,
        profile_sha256=args.profile_sha256,
        update_cap=args.update_cap,
        runtime_source_root=args.runtime_source_root,
        compile_timeout=args.compile_timeout,
    )
    print(
        json.dumps(
            {
                "stage_receipt": str(args.out.resolve() / "stage.json"),
                "worker": result["worker"],
                "native_compatibility_verified": False,
            },
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
