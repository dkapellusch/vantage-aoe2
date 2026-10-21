"""Start Age of Empires II: DE from the spectator.

``GameLauncher.launch`` checks that ``AoE2DE_s.exe`` exists (status
``noGameExe`` otherwise), runs Steam with ``-applaunch 813780 SKIPINTRO`` (falling
back to ``steam://rungameid/813780``; ``launchFailed`` if both fail) and then
watches the game: ``running`` once Steam / the process says so, ``exited`` if it
closes before the API connects, ``launchFailed`` after 5 minutes without a start
(the deadline restarts while Steam reports the app updating). A connected live
stream is ``connected``. Statuses: unknown, noGameExe, opening, running,
runningPlayer, runningCadeNeedsUpdate, connected, launchFailed, exited.

On Windows the fallback opens the link with ``os.startfile`` (:data:`OPEN`),
Steam's state comes from its registry key and the process probe from
``tasklist``.

Setting ``VANTAGE_NO_LAUNCH`` makes the default runner refuse (``launchFailed``),
so test and agent runs can never start the game by accident.

Everything that touches the machine is injected (the runner that starts Steam,
the Steam app-state reader, the process probe, the clock), so tests never start
the game. The default runner is only used by a real ``/api/launch_game`` POST.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

APP_ID = 813780
STATUSES = (
    "unknown",
    "noGameExe",
    "opening",
    "running",
    "runningPlayer",
    "runningCadeNeedsUpdate",
    "connected",
    "launchFailed",
    "exited",
)
#: The launch deadline (game not started), and how often the watcher polls.
LAUNCH_DEADLINE_S = 300.0
POLL_S = 2.0
EXE = "AoE2DE_s.exe"

#: ``runner(argv) -> started`` -- spawn a command without waiting for it.
Runner = Callable[[list[str]], bool]
#: The desktop's "open this link" command; on Windows a name for ``os.startfile``.
OPEN = "startfile" if sys.platform == "win32" else "xdg-open"


def default_runner(argv: list[str]) -> bool:
    """Spawn ``argv`` detached; True when the process started.
    ``["startfile", target]`` opens ``target`` through the Windows shell."""
    if sys.platform == "win32" and argv[0] == "startfile":
        try:
            os.startfile(argv[1])
        except OSError:
            return False
        return True
    exe = shutil.which(argv[0])
    if exe is None:
        return False
    try:
        subprocess.Popen(
            [exe, *argv[1:]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def steam_app_state(app_id: int = APP_ID, home: Path | None = None) -> str:
    """Steam's registry view of the app: ``running``, ``updating`` or ``stopped``
    (``unknown`` when Steam's ``registry.vdf`` cannot be read). On Windows,
    without ``home``, Steam's registry key is read instead."""
    if sys.platform == "win32" and home is None:
        return _windows_app_state(app_id)
    base = home if home is not None else Path.home()
    for rel in (
        ".steam/registry.vdf",
        ".steam/steam/registry.vdf",
        ".local/share/Steam/registry.vdf",
    ):
        try:
            text = (base / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(rf'"{app_id}"\s*\{{(.*?)\n\s*\}}', text, re.S)
        if m is None:
            return "stopped"
        block = m.group(1)

        def flag(key: str, block: str = block) -> bool:
            f = re.search(rf'"{key}"\s+"(\d+)"', block)
            return bool(f and f.group(1) != "0")

        if flag("Updating"):
            return "updating"
        return "running" if flag("Running") else "stopped"
    return "unknown"


def _windows_app_state(app_id: int) -> str:
    """``HKCU\\Software\\Valve\\Steam\\Apps\\<id>``: Steam's ``Running`` and
    ``Updating`` flags (DWORDs)."""
    from vantage.gamedata import registry_value

    if registry_value("HKCU", r"Software\Valve\Steam", "SteamPath") is None:
        return "unknown"
    key = rf"Software\Valve\Steam\Apps\{app_id}"
    if registry_value("HKCU", key, "Updating"):
        return "updating"
    return "running" if registry_value("HKCU", key, "Running") else "stopped"


def game_process_running(proc: Path = Path("/proc")) -> bool:
    """Whether an ``AoE2DE_s.exe`` process exists (a read-only /proc scan, or
    ``tasklist`` on Windows, which has no /proc)."""
    if sys.platform == "win32" and not proc.is_dir():
        return _tasklist_has(EXE)
    try:
        entries = list(proc.iterdir())
    except OSError:
        return False
    for d in entries:
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / "cmdline").read_bytes()
        except OSError:
            continue
        if EXE.encode().lower() in cmd.lower():
            return True
    return False


def _tasklist_has(image: str) -> bool:
    """Whether Windows' ``tasklist`` shows a process with this image name. Its
    CSV rows quote the name; the "no tasks" notice (localised) does not."""
    try:
        done = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return f'"{image.lower()}"' in done.stdout.lower()


class GameLauncher:
    """The launch state machine behind ``/api/launch_game``."""

    def __init__(
        self,
        game_dir: Callable[[], Path | None],
        runner: Runner = default_runner,
        app_state: Callable[[], str] = steam_app_state,
        process_running: Callable[[], bool] = game_process_running,
        clock: Callable[[], float] = time.monotonic,
        remove_legacy: bool = True,
    ) -> None:
        self._game_dir = game_dir
        self._runner = runner
        self._app_state = app_state
        self._running = process_running
        self._clock = clock
        self._remove_legacy = remove_legacy
        self._lock = threading.Lock()
        self._status = "unknown"
        self._detail = ""
        self._deadline = 0.0
        self._polled = -1e9
        self._was_connected = False

    # -- public ---------------------------------------------------------------

    def launch(self, connected: bool = False) -> dict[str, Any]:
        """Start the game (unless it is running); returns the new status."""
        with self._lock:
            if connected:
                return self._report("connected")
            gd = self._game_dir()
            if gd is None or not (gd / EXE).is_file():
                return self._set("noGameExe", f"{EXE} not found")
            if self._app_state() == "running" or self._running():
                return self._set("running", "the game is already running")
            if self._runner is default_runner and os.environ.get("VANTAGE_NO_LAUNCH"):
                # A guard for tests, agents and shared machines: no real launch.
                return self._set("launchFailed", "launching is disabled (VANTAGE_NO_LAUNCH)")
            if self._remove_legacy:
                # A legacy steam_appid marker (left by older setups) can get in
                # the way of a Steam launch, so it is removed first. Only that
                # marker is removed: a file holding exactly the app id.
                marker = gd / "steam_appid.txt"
                with contextlib.suppress(OSError, UnicodeDecodeError):
                    if marker.read_text(encoding="utf-8").strip() == str(APP_ID):
                        marker.unlink()
            started = self._runner(["steam", "-applaunch", str(APP_ID), "SKIPINTRO"])
            if not started:
                started = self._runner([OPEN, f"steam://rungameid/{APP_ID}"])
            if not started:
                return self._set("launchFailed", "Steam could not be started")
            self._deadline = self._clock() + LAUNCH_DEADLINE_S
            self._polled = -1e9
            return self._set("opening", "launching through Steam")

    def status(self, connected: bool = False, stream: str | None = None) -> dict[str, Any]:
        """The current status, polling Steam / the process at most every 2 s.

        ``connected`` is whether the live stream is up; ``stream`` optionally
        maps the gRPC stream state (``closed-player``, ``closed-needs-update``,
        ``connected-hiccup``) onto its status."""
        with self._lock:
            if connected or stream in ("connected", "connected-hiccup"):
                self._was_connected = True
                return self._report("connected")
            if stream == "closed-player":
                return self._report("runningPlayer")
            if stream == "closed-needs-update":
                return self._report("runningCadeNeedsUpdate")
            self._poll()
            if self._was_connected and self._status == "connected":
                # Connected before, not now: the game has probably closed.
                self._was_connected = False
                gone = not (self._app_state() == "running" or self._running())
                return self._set(
                    "exited" if gone else "running",
                    "Age II connection lost, the game has probably closed." if gone else "",
                )
            return self._report(self._status)

    # -- internals --------------------------------------------------------------

    def _poll(self) -> None:
        now = self._clock()
        if now - self._polled < POLL_S:
            return
        self._polled = now
        state = self._app_state()
        alive = state == "running" or self._running()
        if self._status == "opening":
            if alive:
                self._set("running", "")
            elif state == "updating":
                self._deadline = now + LAUNCH_DEADLINE_S  # the deadline restarts
            elif now > self._deadline:
                self._set("launchFailed", "the game did not start within 5 minutes")
        elif self._status in ("running", "runningPlayer", "runningCadeNeedsUpdate") and not alive:
            self._set("exited", "the game closed before the API connected")

    def _set(self, status: str, detail: str = "") -> dict[str, Any]:
        self._status, self._detail = status, detail
        return self._report(status)

    def _report(self, status: str) -> dict[str, Any]:
        if status == "connected":
            self._status = "connected"
        out: dict[str, Any] = {"status": status}
        if self._detail and status == self._status:
            out["detail"] = self._detail
        return out
