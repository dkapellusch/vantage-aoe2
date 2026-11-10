# Replay farm

Converts many `.aoe2record` replays to `.vrec` recordings at once, by running
several isolated, headless copies of the installed game side by side. Linux
only; experimental.

```sh
python tools/farm/farm.py doctor
python tools/farm/farm.py convert ~/replays/*.aoe2record --out-dir ~/recordings -j 4
python tools/farm/farm.py down        # stop every farm process
```

A recording made here is the same thing `vantage record --replay ... --light`
writes: the game plays the replay and its frame stream is saved. The game still
does the simulating. What the farm adds is isolation, so that copies can run in
parallel and next to a game you are playing, and a set of fixes that make each
copy run as fast as the game allows.

## What each copy is

| Piece | Why |
|---|---|
| Its own Wine prefix (`~/.cache/vantage-farm/inst<N>`, about 600 MB) | Copied from the game's Proton prefix without saved games, mods and logs. One wineserver per copy, so copies share no game state with each other or with your own game. |
| Its own network namespace (`bwrap --unshare-net`) | The game's API port (4341) is fixed, so two copies cannot share a network stack. The namespace has no internet: a copy cannot sign in to the game's online services, and so cannot sign your own game out. |
| A dummy network card inside it | Without any network card the game spins for a minute and exits. |
| A bridge to the Steam client | The game will not start without Steam. Steam's client socket is TCP on the host's loopback (port 57343); `socat` carries it into the namespace over a unix socket. |
| The host's process ids (no pid namespace) | Steam tells its clients apart by process id. With a pid namespace per copy, copies show Steam the same ids and it drops them ("stalled cross-thread pipe"). |
| A headless display (`gamescope --backend headless`, 1024x720) | The game needs a window and refuses anything smaller than 1024x720. Each sandbox has a `/tmp` of its own, so its X server never appears among the desktop's. |
| The integrated GPU, when there is one | A copy holds about 2.4 GB of video memory whatever its graphics settings (it is the preloaded art). On the integrated GPU that is system RAM, so the number of copies is not bound by the discrete card, and the card stays free for your own game. Drawing is cheap enough (about 1 ms a frame) for it. |
| `fastclock.so` (`LD_PRELOAD`) | See below. |

## The fast clock

On a machine whose kernel clock source is HPET (`farm.py doctor` says which),
reading the clock is a hardware access of about 1.1 µs. The game reads it
constantly, through Wine's `QueryPerformanceCounter`. Measured on a Ryzen 9
7900X: about half of the game's main thread was spent reading the clock.

`fastclock.so` answers `clock_gettime()` from the CPU's time-stamp counter
instead (8 ns), calibrated once per boot against the kernel's clock. It applies
to the farm's copies only.

It can also run the clock Wine uses for `QueryPerformanceCounter` faster
(`--clock-scale`). The game caps replay speed at 16 times its 1.7 game speed
(about 27 game-seconds a second, with the `FASTREPLAY` launch option); a faster
clock lifts that cap. Only that one clock is changed, and nothing in the kernel
can wait on it, so real waits stay real. Steam's library inside the game is
left on real time. A higher scale makes every timer in the game and Wine fire
more often, which costs CPU in every copy. Only a single copy on a light game
reaches the cap (a ranked 1v1 opens at 58 instead of 27); with four copies in
parallel the scale made no measurable difference, so it is off by default.

If the counter is sound, booting the kernel with `tsc=reliable` fixes the slow
clock for everything on the machine, your own game included; the farm then
needs the preload only for `--clock-scale`.

## What limits speed

Measured on a busy desktop (a game being played, browsers open), Ryzen 9 7900X:

| | Game-seconds per second |
|---|---|
| One copy as before (`FASTREPLAY`, light stream), heavy 6-player game, first 10 minutes | 17 |
| The same with the fast clock | 26 to 29 |
| Whole 54-minute 6-player game, one copy | 518 s before, 331 s after |
| Ranked 1v1, 49 minutes, one copy | 26 (the game's cap): 112 s |
| The same, clock x4 | 58 early, 22 late: 91 s |
| Four copies at once, the 1v1 | 4 x 23 = 93 |
| Six copies at once, the 1v1 | 6 x 19 = 114 |
| Four copies at once, heavy game, first 10 minutes | 4 x 20 = 82 |
| Six copies at once, heavy game, first 10 minutes | 6 x 15 = 89 |

A copy takes 60 to 90 seconds to start (the game waits out a fixed timer when it
is offline), then converts replay after replay. Three different ranked games,
126 game-minutes together, took 208 seconds from a cold start with three copies.

- The game advances at most half a game-second per drawn frame, so it needs
  frames, but drawing is not the cost: paused, it draws about 790 frames a
  second on a third of a core.
- With the clock fixed, a copy is bound by the game's simulation on one thread.
  A late-game army fight simulates at 5 to 20 times real time whatever is done
  around it.
- The launch options `UNCAPPED_SIMULATION_SPEED` and a higher display refresh
  rate change nothing. A minimised window is slower, not faster.
- The stream's detail costs game time on that same thread: the full stream at
  100 ms is about 15% slower than the light one at 500 ms.
- Copies scale until the machine's physical cores are busy; on this machine,
  shared with a desktop in use, four to six. Each copy uses about 1.5 cores and
  5 GB of RAM while converting.

## Limits

- The installed game must be able to play the replay: a replay from an older
  game build than the installed one usually is not playable.
- Each copy needs the Steam client running and signed in to an account that owns
  the game. The copies are offline apart from that.
- Replays under `/tmp` are copied to the farm folder first (a copy has its own
  `/tmp`).
- A copy that fails to start or to load a replay is restarted; a replay that
  fails is reported and the others go on.
