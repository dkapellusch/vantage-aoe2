#!/usr/bin/env python3
"""Report consecutive sampled difference runs from retained observations."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vantage.native_reference_window import difference_runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("native", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-samples", type=int, default=2)
    args = parser.parse_args()
    result = difference_runs(args.reference, args.native, minimum_samples=args.minimum_samples)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
