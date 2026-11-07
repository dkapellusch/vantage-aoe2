"""Convert one recording using an explicit native engine registry."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vantage.native_conversion import write_json
from vantage.native_engine_protocol import ConversionRequest, ConversionResult
from vantage.native_engine_registry import EngineRegistry
from vantage.native_engine_v32 import V32Engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--experimental", action="store_true")
    parser.add_argument("--require-capability", action="append", default=[])
    parser.add_argument("--reuse-job", type=Path)
    parser.add_argument("--runtime-timeout", type=float, default=2400)
    parser.add_argument("--encoder-timeout", type=float, default=1800)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; retain previous evidence")
    registry = EngineRegistry.load(args.registry, args.registry_sha256)
    engine = V32Engine(
        registry,
        cache_dir=args.cache_dir,
        reuse_job=args.reuse_job,
        runtime_timeout=args.runtime_timeout,
        encoder_timeout=args.encoder_timeout,
    )
    request = ConversionRequest(
        args.replay,
        required_capabilities=tuple(args.require_capability),
        allow_experimental=args.experimental,
    )

    # Python signal handlers execute on the main thread and can interrupt it
    # while V32Engine holds its lock. Record intent here; a separate thread
    # calls the locking cancellation method after the handler has returned.
    cancel_requested = False
    monitor_stopped = threading.Event()

    def request_cancel(_signum, _frame):
        nonlocal cancel_requested
        cancel_requested = True

    def monitor_cancel():
        while True:
            stopped = monitor_stopped.wait(0.05)
            if cancel_requested:
                engine.cancel()
                return
            if stopped:
                return

    monitor = threading.Thread(target=monitor_cancel, name="native-conversion-cancel")
    previous = {sig: signal.signal(sig, request_cancel) for sig in (signal.SIGINT, signal.SIGTERM)}
    monitor.start()
    try:
        result = engine.convert(request)
    finally:
        monitor_stopped.set()
        monitor.join()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if cancel_requested and result.status == "ready":
        # A cache hit may finish before the monitor's first timer wakeup.
        # Cancellation still suppresses the returned recording.
        result = ConversionResult("cancelled", result.engine_id, result.replay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result.to_json())
    print(json.dumps(result.to_json(), indent=2))
    if result.status != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
