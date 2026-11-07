"""Recover exact historical codec sources into a private encoder overlay.

Never changes the worktree or replaces an expected digest with current bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vantage.native_conversion import pin  # noqa: E402
from vantage.native_v32_encode import verify_encoder_config  # noqa: E402


def retain_encoder(config_path: Path, output: Path) -> dict:
    """Create a new configuration only after every historical overlay verifies."""
    original = pin(config_path)
    config = json.loads(config_path.read_bytes())
    parent_pin = config["parent_profile"]
    if pin(Path(parent_pin["path"])) != parent_pin:
        raise ValueError("Encoder parent profile changed")
    parent = json.loads(Path(parent_pin["path"]).read_bytes())
    contracts = [parent["source_evidence"], *parent["source_contracts"], *parent["codec_pins"]]
    covered = {row["target"] for row in config["overlays"]}
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    recovered = []
    for expected in contracts:
        target = Path(expected["path"])
        if str(target) in covered or pin(target) == expected:
            continue
        relative = target.relative_to(ROOT)
        history = subprocess.run(
            ["git", "log", "--all", "--format=%H", "--", str(relative)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        for revision in history.stdout.splitlines():
            blob = subprocess.run(
                ["git", "show", f"{revision}:{relative}"],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
            if (
                blob.returncode == 0
                and len(blob.stdout) == expected["bytes"]
                and hashlib.sha256(blob.stdout).hexdigest() == expected["sha256"]
            ):
                retained = output / "sources" / relative
                retained.parent.mkdir(parents=True, exist_ok=True)
                retained.write_bytes(blob.stdout)
                config["overlays"].append(
                    {
                        "target": str(target),
                        "source": pin(retained),
                        "expected_sha256": expected["sha256"],
                    }
                )
                recovered.append(
                    {"target": str(target), "source": pin(retained), "git_revision": revision}
                )
                break
        else:
            raise ValueError(f"No exact historical bytes found: {target}")
    derived = output / "encoder-config.json"
    derived.write_text(json.dumps(config, indent=2) + "\n")
    selected = pin(derived)
    verify_encoder_config(derived, selected["sha256"])
    if pin(config_path) != original:
        raise ValueError("Original configuration changed during retention")
    receipt = {
        "kind": "exact_historical_encoder_overlays",
        "original": original,
        "config": selected,
        "recovered": recovered,
        "worktree_modified": False,
    }
    (output / "retention.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(retain_encoder(args.config, args.output), indent=2))


if __name__ == "__main__":
    main()
