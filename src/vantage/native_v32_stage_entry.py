"""Run V32 staging as an owned, cancellable process for the Session backend."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from typing import Any

from . import native_v32_prepare


def main() -> None:
    original = subprocess.Popen
    compiler = None

    def spawn(*args: Any, **kwargs: Any) -> Any:
        nonlocal compiler
        # No cancellation may arrive between creating and recording the exact
        # child handle. The stager creates this child in its own process group.
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        try:
            compiler = original(*args, **kwargs)
            return compiler
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)

    def cancel(_signum: Any, _frame: Any) -> None:
        # Repeated cancellation must not interrupt the stager's reap/cleanup.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if compiler is not None and compiler.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(compiler.pid, signal.SIGTERM)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, cancel)
    setattr(subprocess, "Popen", spawn)  # noqa: B010  (patched for this stage only)
    try:
        native_v32_prepare.main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    finally:
        setattr(subprocess, "Popen", original)  # noqa: B010
        if compiler is not None and compiler.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(compiler.pid, signal.SIGTERM)
            try:
                compiler.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(compiler.pid, signal.SIGKILL)
                compiler.wait()


if __name__ == "__main__":
    main()
