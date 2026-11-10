#!/usr/bin/env python3
"""Replay farm: convert many .aoe2record replays to .vrec at once, headless.

Runs several isolated copies of the installed game side by side, each playing one
replay at the game's fastest speed while its frame stream is recorded. Nothing
here touches a game the user is running: every copy has its own Wine prefix,
its own headless display and its own network namespace (no internet; only the
Steam client's local socket and the game's API are bridged).

    farm.py doctor                         what this machine can use
    farm.py convert A.aoe2record ... -j 4  convert with four game copies
    farm.py down                           stop every farm process

Linux only. Needs bwrap, gamescope, socat, a C compiler, a running Steam client
that owns the game, and Proton. See README.md in this folder for what was
measured and why each piece is there.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP_ID = 813780
API_PORT = 4341  # the game's fixed port, inside each instance's own network namespace
STEAM_IPC_PORT = 57343  # the Steam client's local IPC port
MIN_W, MIN_H = 1024, 720  # the game refuses to start on anything smaller

#: Graphics options at their cheapest (the game keeps them in its registry key).
LOW_GRAPHICS = {
    "AntiAlias": 0,
    "AntiAlias Text": 0,
    "AntiAlias UI": 0,
    "Beach Waves": 0,
    "Blood": 0,
    "Bloom": 0,
    "Color Correction": 0,
    "Cool Destructions": 0,
    "Distance Fog": 0,
    "EdgeBlur": 0,
    "Fog Border": 0,
    "Render 3D Water": 0,
    "Unsharp": 0,
    "Vignette": 0,
    "Particles": 0,
    "Game Render Scale": 50,
    "Graphics 2x": 0,
    "Graphics Preset": 0,
    "SmallTrees": 1,
    "Render Vsync": 0,
    "Mute on Focus Lost": 0,
}
REG_SECTION = r"[Software\\Microsoft\\Microsoft Games\\Age of Empires II DE]"


def farm_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "vantage-farm"


# -- what the machine has -------------------------------------------------------------


def clocksource() -> str:
    try:
        path = "/sys/devices/system/clocksource/clocksource0/current_clocksource"
        return Path(path).read_text().strip()
    except OSError:
        return "?"


def find_game() -> Path | None:
    sys.path.insert(0, str(ROOT / "src"))
    from vantage.gamedata import find_game_dir

    found = find_game_dir()
    return Path(found) if found else None


def find_compatdata(game: Path) -> Path | None:
    """The game's Proton prefix: ``steamapps/compatdata/<app id>`` next to its install."""
    path = game.parent.parent / "compatdata" / str(APP_ID)
    return path if (path / "pfx").is_dir() else None


def find_proton() -> Path | None:
    """The Proton build Steam is set to use for the game, else the newest installed."""
    steam = Path.home() / ".local/share/Steam"
    tools = steam / "compatibilitytools.d"
    with contextlib.suppress(OSError):
        config = (steam / "config/config.vdf").read_text("utf-8", "replace")
        m = re.search(rf'"{APP_ID}"\s*\{{[^}}]*?"name"\s*"([^"]+)"', config)
        if m and (tools / m.group(1) / "proton").is_file():
            return tools / m.group(1)
    found = sorted(p.parent for p in tools.glob("*/proton")) if tools.is_dir() else []
    found += sorted(p.parent for p in (steam / "steamapps/common").glob("Proton*/proton"))
    return found[-1] if found else None


def integrated_gpu() -> str | None:
    """PCI id of an AMD integrated GPU. Its memory is system RAM, so game copies drawn
    there do not compete for the discrete card's memory (about 2.4 GB a copy)."""
    try:
        out = subprocess.run(["lspci", "-n"], capture_output=True, text=True, check=False).stdout
    except OSError:
        return None
    rows = [line.split() for line in out.splitlines()]
    amd = [r[2] for r in rows if len(r) > 2 and r[1] == "0300:" and r[2].startswith("1002:")]
    other = [r for r in rows if len(r) > 2 and r[1] in ("0300:", "0302:")]
    return amd[0] if amd and len(other) > 1 else None


def steam_running() -> bool:
    import socket

    with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", STEAM_IPC_PORT), 1):
        return True
    return False


# -- the fast clock -------------------------------------------------------------------


def build_fastclock(farm: Path) -> tuple[Path, int] | None:
    """Compile fastclock.so and measure the time-stamp counter once per boot.
    None when there is no compiler: the farm still works, more slowly."""
    lib = farm / "lib/fastclock.so"
    cal = farm / "bin/tsccal"
    cc = shutil.which("cc") or shutil.which("gcc")
    src = HERE / "fastclock.c"
    try:
        if not lib.exists() or lib.stat().st_mtime < src.stat().st_mtime:
            if not cc:
                return None
            lib.parent.mkdir(parents=True, exist_ok=True)
            cal.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([cc, "-O2", "-fPIC", "-shared", "-o", str(lib), str(src)], check=True)
            subprocess.run([cc, "-O2", "-o", str(cal), str(HERE / "tsccal.c")], check=True)
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        cache = farm / "tsc_hz.json"
        with contextlib.suppress(OSError, ValueError, KeyError):
            saved = json.loads(cache.read_text())
            if saved["boot"] == boot:
                return lib, int(saved["hz"])
        hz = int(subprocess.run([str(cal), "5"], capture_output=True, text=True, check=True).stdout)
        cache.write_text(json.dumps({"boot": boot, "hz": hz}))
        return lib, hz
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


# -- one instance ---------------------------------------------------------------------


def set_low_graphics(prefix: Path) -> None:
    reg = prefix / "pfx/user.reg"
    text = reg.read_text("latin1")
    try:
        a = text.index(REG_SECTION)
    except ValueError:
        return  # the game has never been run in this prefix: its own defaults apply
    b = text.find("\n\n", a)
    b = len(text) if b < 0 else b
    section = text[a:b]
    for key, value in LOW_GRAPHICS.items():
        line = f'"{key}"=dword:{value & 0xFFFFFFFF:08x}'
        section, n = re.subn(rf'^"{re.escape(key)}"=dword:[0-9a-f]+$', line, section, flags=re.M)
        if not n:
            section += "\n" + line
    reg.write_text(text[:a] + section + text[b:], "latin1")


def make_prefix(source: Path, target: Path) -> None:
    """A private copy of the game's Wine prefix, without saved games, mods and logs
    (which are most of its size): about 600 MB."""
    if (target / "pfx").is_dir():
        return

    def skip(folder: str, names: list[str]) -> list[str]:
        inside_profile = "Age of Empires 2 DE" in folder
        return [n for n in names if inside_profile and n in ("mods", "savegame", "logs")]

    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(source, tmp, symlinks=True, ignore=skip)
    set_low_graphics(tmp)
    tmp.rename(target)


INNER = rf"""
set -u
# A network card with an address and a route, going nowhere: the game looks for one
# and exits without it.
ip link add eth0 type dummy && ip addr add 10.77.0.2/24 dev eth0 && ip link set eth0 up \
  && ip route add default via 10.77.0.1
socat TCP-LISTEN:{STEAM_IPC_PORT},bind=127.0.0.1,fork,reuseaddr \
  UNIX-CONNECT:"$FARM_INST/steam.sock" &
socat UNIX-LISTEN:"$FARM_INST/api.sock",fork,unlink-early TCP:127.0.0.1:{API_PORT} &
unset WAYLAND_DISPLAY DISPLAY
cd "$STEAM_COMPAT_INSTALL_PATH"
exec gamescope --backend headless $FARM_GS_DEV -W {MIN_W} -H {MIN_H} -r 60 -- \
  "$FARM_PROTON/proton" run "$STEAM_COMPAT_INSTALL_PATH/AoE2DE_s.exe" SKIPINTRO NOMODS FASTREPLAY
"""


class Instance:
    """One isolated, headless copy of the game, with its API on ``127.0.0.1:port``."""

    def __init__(self, farm: Path, index: int, opts: argparse.Namespace, env: dict[str, str]):
        self.index = index
        self.dir = farm / f"inst{index}"
        self.port = opts.base_port + index
        self.env = env
        self.procs: list[subprocess.Popen[bytes]] = []
        self.conversions = 0

    def start(self) -> None:
        self.stop()
        (self.dir / "log").mkdir(parents=True, exist_ok=True)
        for name in ("steam.sock", "api.sock"):
            with contextlib.suppress(OSError):
                (self.dir / name).unlink()
        env = dict(self.env, FARM_INST=str(self.dir), STEAM_COMPAT_DATA_PATH=str(self.dir))
        # Steam's client IPC is TCP on the host's loopback, and the game's API is TCP on the
        # namespace's: both cross through unix sockets in the instance folder.
        relays = [
            [
                "socat",
                f"UNIX-LISTEN:{self.dir}/steam.sock,fork,unlink-early",
                f"TCP:127.0.0.1:{STEAM_IPC_PORT}",
            ],
            [
                "socat",
                f"TCP-LISTEN:{self.port},bind=127.0.0.1,fork,reuseaddr",
                f"UNIX-CONNECT:{self.dir}/api.sock",
            ],
        ]
        log = (self.dir / "log/game.out").open("wb")
        for cmd in relays:
            self.procs.append(subprocess.Popen(cmd, env=env, stdout=log, stderr=log))
        # The sandbox keeps the host's process ids on purpose: Steam tells its clients
        # apart by pid, and drops a client whose pid another one already uses.
        # Everything is read-only except the instance's own folder, and the home folder is
        # hidden but for Steam (read-only) and the farm's library and staged replays: a
        # replay is a file from anyone, read by the game's own parser.
        home = str(Path.home())
        steam = str(Path(env["STEAM_COMPAT_CLIENT_INSTALL_PATH"]).resolve())
        farm = self.dir.parent
        for sub in ("run", "cache", "home"):
            (self.dir / sub).mkdir(exist_ok=True)
        (farm / "staging").mkdir(exist_ok=True)
        (farm / "lib").mkdir(exist_ok=True)
        env.update(XDG_RUNTIME_DIR=str(self.dir / "run"), XDG_CACHE_HOME=str(self.dir / "cache"))
        sandbox = ["bwrap", "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev"]
        sandbox += ["--tmpfs", "/tmp", "--tmpfs", home, "--ro-bind", steam, steam]
        dot_steam = Path.home() / ".steam"  # links into the Steam folder that its client reads
        if dot_steam.is_dir():
            sandbox += ["--ro-bind", str(dot_steam), str(dot_steam)]
        if not str(Path(env["FARM_PROTON"]).resolve()).startswith(steam + "/"):
            sandbox += ["--ro-bind", env["FARM_PROTON"], env["FARM_PROTON"]]
        sandbox += ["--ro-bind", str(farm / "lib"), str(farm / "lib")]
        sandbox += ["--ro-bind", str(farm / "staging"), str(farm / "staging")]
        sandbox += ["--bind", str(self.dir), str(self.dir)]
        sandbox += ["--unshare-user", "--unshare-net", "--cap-add", "CAP_NET_ADMIN"]
        sandbox += ["--die-with-parent", "bash", "-c", INNER]
        self.procs.append(
            subprocess.Popen(
                sandbox,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        )
        log.close()

    def alive(self) -> bool:
        return bool(self.procs) and self.procs[-1].poll() is None

    def wait_ready(self, timeout: float) -> bool:
        """True once the game answers its API and has reached its menu."""
        from vantage.live import LiveGame

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.alive():
            try:
                game = LiveGame(port=self.port).connect(timeout=2)
                try:
                    game.info()
                finally:
                    game.close()
                return True
            except Exception:
                time.sleep(1)
        return False

    def stop(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:
                with contextlib.suppress(OSError):
                    proc.terminate()
        stop_marked(self.dir)
        self.procs = []


def marked(inst: Path | None, farm: Path) -> list[int]:
    """Pids of farm processes: those whose environment names a farm instance as their
    prefix, and their descendants (Wine rewrites its own processes' environment)."""
    want = f"STEAM_COMPAT_DATA_PATH={inst}".encode() if inst else None
    prefix = f"STEAM_COMPAT_DATA_PATH={farm}/inst".encode()
    found: list[int] = []
    parents: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            stat = (entry / "stat").read_text()
            parents.setdefault(int(stat.rsplit(")", 1)[1].split()[1]), []).append(pid)
            env = (entry / "environ").read_bytes().split(b"\0")
        except (OSError, IndexError, ValueError):
            continue
        if any(e == want if want else e.startswith(prefix) for e in env):
            found.append(pid)
    todo = list(found)
    while todo:
        for child in parents.get(todo.pop(), []):
            if child not in found:
                found.append(child)
                todo.append(child)
    return [p for p in found if p != os.getpid()]


def stop_marked(inst: Path | None, farm: Path | None = None) -> int:
    farm = farm or farm_dir()
    count = 0
    for sig, pause in ((signal.SIGTERM, 1.5), (signal.SIGKILL, 0.3)):
        pids = marked(inst, farm)
        count = max(count, len(pids))
        for pid in pids:
            with contextlib.suppress(OSError):
                os.kill(pid, sig)
        if pids:
            time.sleep(pause)
    return count


# -- one conversion (a process of its own: its gzip and gRPC work off the others' GIL) --


def windows_path(path: Path) -> str:
    return "Z:" + str(path).replace("/", "\\")


def convert_one(args: argparse.Namespace) -> int:
    """Play ``args.replay`` in the instance at ``args.port`` and write ``args.out``."""
    sys.path.insert(0, str(ROOT / "src"))
    from vantage.frames import Frame, RecordingWriter
    from vantage.live import LiveGame
    from vantage.server import LIGHT_STREAM_CATEGORIES, light_particles, mode_from_path

    started = time.monotonic()
    game = LiveGame(port=args.port).connect(timeout=10)
    info = game.info()
    code = game.load_replay(windows_path(Path(args.replay)), confirm=True)
    result: dict[str, Any] = {"load": code, "frames": 0, "game_s": 0.0}
    if code != "SUCCESS":
        print(json.dumps(result))
        return 2
    whitelist: list[str] = []
    if args.particles != "none":
        from vantage.gamedata import GameData, find_game_dir

        whitelist = GameData(find_game_dir()).particle_definitions
        if args.particles == "light":
            whitelist = light_particles(whitelist)
    frames: queue.Queue[Frame | None] = queue.Queue(maxsize=20000)

    def pump() -> None:
        try:
            for frame in game.frames(
                resolution_ms=args.resolution_ms,
                particles=bool(whitelist),
                particle_whitelist=whitelist or None,
                category_ms=None if args.full else LIGHT_STREAM_CATEGORIES,
            ):
                frames.put(frame)
        finally:
            frames.put(None)

    threading.Thread(target=pump, daemon=True).start()
    header = {
        "source": "live",
        "replay": str(args.replay),
        "game_version": info.game_version,
        "game_mode": mode_from_path(info.selected_mode),
    }
    part = Path(str(args.out) + ".part")
    count = 0
    last_time = 0
    heard = time.monotonic()
    first: float | None = None
    speed_set = False
    speed_tried = 0.0
    with RecordingWriter(part, header) as writer:
        while True:
            try:
                frame = frames.get(timeout=0.5)
            except queue.Empty:
                # The stream goes quiet when the replay ends (and never starts when the
                # game could not play the file).
                if time.monotonic() - heard > (args.quiet_seconds if count else 90):
                    break
                continue
            if frame is None:
                break
            writer.write(frame)
            count += 1
            now = heard = time.monotonic()
            last_time = frame.time
            if first is None and frame.time > 0:
                first = now
            # The game takes a speed only once the replay runs, on a connection of its
            # own (it serves one stream per connection).
            if not speed_set and frame.time > 0 and now - speed_tried > 1:
                speed_tried = now
                with contextlib.suppress(Exception):
                    control = LiveGame(port=args.port).connect(timeout=3)
                    try:
                        speed_set = control.set_speed("EXTRA_FAST")
                    finally:
                        control.close()
    game.close()
    play = heard - (first or heard)
    result.update(
        frames=count,
        game_s=round(last_time / 1000, 1),
        play_s=round(play, 1),
        total_s=round(heard - started, 1),
        rate=round(last_time / 1000 / play, 1) if play > 0 else 0.0,
    )
    if count < 2 or last_time <= 0:
        part.unlink(missing_ok=True)
        print(json.dumps(result))
        return 3
    part.replace(args.out)
    print(json.dumps(result))
    return 0


# -- the farm -------------------------------------------------------------------------


def instance_env(opts: argparse.Namespace, farm: Path, game: Path, proton: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("LD_PRELOAD", "DISPLAY")}
    env.update(
        FARM_PROTON=str(proton),
        STEAM_COMPAT_CLIENT_INSTALL_PATH=str(Path.home() / ".local/share/Steam"),
        STEAM_COMPAT_INSTALL_PATH=str(game),
        STEAM_COMPAT_APP_ID=str(APP_ID),
        SteamAppId=str(APP_ID),
        SteamGameId=str(APP_ID),
        WINEDEBUG="-all",
        DXVK_LOG_LEVEL="none",
        PROTON_USE_XALIA="0",
        FARM_GS_DEV="",
    )
    gpu = integrated_gpu() if opts.gpu in ("auto", "integrated") else None
    if gpu:
        env.update(DXVK_FILTER_DEVICE_NAME="RADV", FARM_GS_DEV=f"--prefer-vk-device {gpu}")
    elif opts.gpu == "integrated":
        raise SystemExit("no integrated AMD GPU found (use --gpu discrete)")
    # The fast clock: always worth it when the kernel clock is not the TSC, and needed for
    # any speed-up of the game's clock.
    if opts.clock_scale > 1 or clocksource() != "tsc":
        built = build_fastclock(farm)
        if built:
            lib, hz = built
            env.update(
                LD_PRELOAD=str(lib),
                FASTCLOCK_TSC_HZ=str(hz),
                FASTCLOCK_RAW_SCALE=str(opts.clock_scale),
            )
        else:
            print("no C compiler: running without the fast clock (slower)", file=sys.stderr)
    return env


def stage(replay: Path, farm: Path) -> Path:
    """A copy of the replay in the one folder the game copies can read."""
    replay = replay.resolve()
    key = hashlib.sha1(str(replay).encode()).hexdigest()[:12]
    target = farm / "staging" / f"{key}-{replay.name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(replay, target)
    return target


class FarmError(RuntimeError):
    """The farm cannot run here; the message says what is missing."""


def options(**over: Any) -> argparse.Namespace:
    """The convert command's options with their defaults, for callers in Python."""
    opts = build_parser().parse_args(["convert", "-"])
    for key, value in over.items():
        setattr(opts, key, value)
    return opts


class Pool:
    """Game copies converting replays from a queue.

    ``on_result`` is called (from a worker thread) with one row per replay:
    ``ok``, ``replay``, ``target``, ``tag`` and the conversion's timings or
    error. A copy starts when its worker first has a replay. With
    ``idle_seconds`` set the pool is long-lived: a copy that has had nothing to
    do for that long is stopped, and started again on the next replay. Without
    it the workers end when the queue is empty (``join``).
    """

    def __init__(
        self,
        opts: argparse.Namespace,
        on_result: Any,
        idle_seconds: float | None = None,
        log: Any = print,
    ) -> None:
        self.opts = opts
        self.on_result = on_result
        self.idle_seconds = idle_seconds
        self.log = log
        self.farm = farm_dir()
        game = Path(opts.game_dir) if opts.game_dir else find_game()
        if not game or not (game / "AoE2DE_s.exe").is_file():
            raise FarmError("game install not found (use --game-dir)")
        compat = find_compatdata(game)
        proton = Path(opts.proton) if opts.proton else find_proton()
        if not compat or not proton:
            raise FarmError("the game's Proton prefix or Proton itself was not found")
        for tool in ("bwrap", "gamescope", "socat"):
            if not shutil.which(tool):
                raise FarmError(f"{tool} is not installed")
        if not steam_running():
            raise FarmError("the Steam client is not running (the game needs it to start)")
        self.compat = compat
        self.env = instance_env(opts, self.farm, game, proton)
        self.jobs: queue.Queue[tuple[Path, Path, Any, int]] = queue.Queue()
        self.instances: list[Instance] = []
        self.threads: list[threading.Thread] = []
        self.closed = threading.Event()
        self.busy = 0
        self.lock = threading.Lock()

    def describe(self) -> str:
        return (
            f"clock x{self.opts.clock_scale}, "
            f"{'integrated' if self.env['FARM_GS_DEV'] else 'discrete'} GPU, "
            f"fast clock {'on' if 'LD_PRELOAD' in self.env else 'off'}"
        )

    def submit(self, replay: Path, target: Path, tag: Any = None) -> None:
        self.jobs.put((replay, target, tag, 0))
        with self.lock:
            if len(self.threads) < self.opts.jobs and self.jobs.qsize() > 0:
                inst = Instance(self.farm, len(self.instances), self.opts, self.env)
                thread = threading.Thread(target=self._work, args=(inst,), daemon=True)
                self.instances.append(inst)
                self.threads.append(thread)
                thread.start()

    def pending(self) -> int:
        """Replays waiting or being converted."""
        return self.jobs.qsize() + self.busy

    def join(self) -> None:
        for thread in list(self.threads):
            while thread.is_alive():
                thread.join(0.5)

    def close(self) -> None:
        self.closed.set()
        for inst in self.instances:
            inst.stop()

    def _ensure(self, inst: Instance) -> bool:
        if inst.alive() and inst.conversions < self.opts.recycle:
            return True
        time.sleep(inst.index * self.opts.stagger if not inst.procs else 0)
        make_prefix(self.compat, inst.dir)
        inst.conversions = 0
        inst.start()
        if not inst.wait_ready(self.opts.start_timeout):
            self.log(f"[{inst.index}] game did not start (see {inst.dir}/log)")
            inst.stop()
            return False
        time.sleep(3)  # the menu settles
        return True

    def _convert(self, inst: Instance, replay: Path, target: Path) -> dict[str, Any]:
        opts = self.opts
        staged = stage(replay, self.farm)
        cmd = [sys.executable, __file__, "_convert", "--port", str(inst.port)]
        cmd += ["--replay", str(staged), "--out", str(target)]
        cmd += ["--resolution-ms", str(opts.resolution_ms), "--particles", opts.particles]
        cmd += ["--quiet-seconds", str(opts.quiet_seconds)] + (["--full"] if opts.full else [])
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        staged.unlink(missing_ok=True)
        inst.conversions += 1
        try:
            row: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            row = {"load": "ERROR", "error": proc.stderr.strip()[-300:]}
        row["ok"] = proc.returncode == 0
        return row

    def _work(self, inst: Instance) -> None:
        last = time.monotonic()
        while not self.closed.is_set():
            try:
                replay, target, tag, attempt = self.jobs.get(timeout=1)
            except queue.Empty:
                if self.idle_seconds is None:
                    break
                if inst.alive() and time.monotonic() - last > self.idle_seconds:
                    self.log(f"[{inst.index}] idle: stopping the game copy")
                    inst.stop()
                continue
            with self.lock:
                self.busy += 1
            try:
                if self._ensure(inst):
                    row = self._convert(inst, replay, target)
                else:
                    row = {"ok": False, "load": "NO_GAME", "error": "the game did not start"}
                if not row["ok"]:
                    inst.stop()  # a fresh game for the next one
                    if attempt < 1 and not self.closed.is_set():
                        self.jobs.put((replay, target, tag, attempt + 1))
                        continue
                row.update(replay=replay.name, target=str(target), tag=tag, instance=inst.index)
                self.on_result(row)
            finally:
                with self.lock:
                    self.busy -= 1
                last = time.monotonic()
        inst.stop()


def cmd_convert(opts: argparse.Namespace) -> int:
    replays = [Path(r) for r in opts.replays]
    missing = [r for r in replays if not r.is_file()]
    if missing:
        raise SystemExit(f"no such replay: {missing[0]}")
    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = []
    for replay in replays:
        target = out_dir / (replay.stem + ".vrec")
        if target.exists() and not opts.force:
            print(f"skip (exists): {target.name}")
            continue
        todo.append((replay, target))
    if not todo:
        return 0
    results: list[dict[str, Any]] = []

    def report(row: dict[str, Any]) -> None:
        results.append(row)
        if row["ok"]:
            print(
                f"[{row['instance']}] {row['replay']}: {row['game_s'] / 60:.1f} game-min in "
                f"{row['total_s']:.0f} s ({row['rate']}x)",
                flush=True,
            )
        else:
            print(
                f"[{row['instance']}] FAILED {row['replay']}: {row.get('load')} "
                f"{row.get('error', '')}",
                flush=True,
            )

    opts.jobs = max(1, min(opts.jobs, len(todo)))
    try:
        pool = Pool(opts, report, log=lambda text: print(text, flush=True))
    except FarmError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"farm: {opts.jobs} game copies, {pool.describe()}", flush=True)
    started = time.monotonic()
    try:
        for replay, target in todo:
            pool.submit(replay, target)
        pool.join()
    except KeyboardInterrupt:
        print("stopping...", flush=True)
    finally:
        pool.close()
    wall = time.monotonic() - started
    done = [r for r in results if r["ok"]]
    game_s = sum(r["game_s"] for r in done)
    print(
        f"converted {len(done)}/{len(todo)} replays, {game_s / 60:.0f} game-min in "
        f"{wall:.0f} s: {game_s / wall if wall else 0:.0f}x real time overall"
    )
    if opts.report:
        Path(opts.report).write_text(json.dumps({"wall_s": wall, "results": results}, indent=1))
    return 0 if len(done) == len(todo) else 1


def cmd_down(_: argparse.Namespace) -> int:
    print(f"stopped {stop_marked(None)} farm processes")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    game = find_game()
    rows = {
        "game install": game,
        "proton prefix": find_compatdata(game) if game else None,
        "proton": find_proton(),
        "steam client running": steam_running(),
        "integrated GPU": integrated_gpu(),
        "kernel clock source": clocksource(),
        "farm folder": farm_dir(),
    }
    for tool in ("bwrap", "gamescope", "socat", "cc"):
        rows[tool] = shutil.which(tool)
    for key, value in rows.items():
        print(f"{key:22} {value if value not in (None, False) else 'MISSING'}")
    if clocksource() != "tsc":
        print(
            "\nThe kernel clock source is not the TSC: every clock read is slow for every\n"
            "program on this machine. The farm works around it for its own game copies;\n"
            "booting with tsc=reliable (when the counter is sound) fixes it for all."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert replays to .vrec recordings")
    c.add_argument("replays", nargs="+")
    c.add_argument("--out-dir", default=".", help="where the .vrec files go")
    c.add_argument("-j", "--jobs", type=int, default=4, help="game copies to run at once")
    c.add_argument(
        "--clock-scale",
        type=int,
        default=1,
        choices=(1, 2, 3, 4),
        help="run the game's clock this many times faster: lifts its 27x replay ceiling,"
        " which only a single copy on a light game reaches (no gain with copies in parallel)",
    )
    c.add_argument("--gpu", choices=("auto", "integrated", "discrete"), default="auto")
    c.add_argument("--resolution-ms", type=int, default=500)
    c.add_argument("--particles", choices=("none", "light", "all"), default="light")
    c.add_argument("--full", action="store_true", help="every unit category at full rate")
    c.add_argument("--quiet-seconds", type=float, default=6)
    c.add_argument("--recycle", type=int, default=25, help="restart a copy after this many")
    c.add_argument("--stagger", type=float, default=4, help="seconds between copy starts")
    c.add_argument("--start-timeout", type=float, default=300)
    c.add_argument("--base-port", type=int, default=4400)
    c.add_argument("--force", action="store_true", help="overwrite existing recordings")
    c.add_argument("--game-dir")
    c.add_argument("--proton")
    c.add_argument("--report", help="write per-replay timings to this JSON file")
    c.set_defaults(func=cmd_convert)
    one = sub.add_parser("_convert")  # internal: one conversion against a running copy
    one.add_argument("--port", type=int, required=True)
    one.add_argument("--replay", required=True)
    one.add_argument("--out", type=Path, required=True)
    one.add_argument("--resolution-ms", type=int, default=500)
    one.add_argument("--particles", default="light")
    one.add_argument("--quiet-seconds", type=float, default=6)
    one.add_argument("--full", action="store_true")
    one.set_defaults(func=convert_one)
    sub.add_parser("down", help="stop every farm process").set_defaults(func=cmd_down)
    sub.add_parser("doctor", help="what this machine can use").set_defaults(func=cmd_doctor)
    return parser


def main() -> int:
    opts = build_parser().parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    return int(opts.func(opts))


if __name__ == "__main__":
    raise SystemExit(main())
