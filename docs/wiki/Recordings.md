# Recordings

A **recording** (`.vrec`) is Vantage's own file format. It holds the game's spectator stream exactly as Vantage received it: every frame of world changes, plus the game's events and the players' commands.

Because the match is already simulated, a recording:

- plays **without the game running** and **without the API certificates**,
- loads in the background, so you can start watching straight away,
- can be **shared**. Anyone with Vantage can watch it.

A recording contains no game assets. Vantage draws it with the graphics, names, icons and sounds of the game installed on the computer that plays it. Without an install it still plays, but with plain graphics and no sound.

## Making a recording

### While watching live

- **`vantage serve --live`** records automatically. Add `--no-record` to turn that off.
- **In the browser**, tick **Record to .vrec** before connecting on the home screen's **Live game** tab. The setting *Record live games to .vrec* (off by default) ticks it for you.
- **During a session**, the ● REC button starts and stops recording. A recording must begin with a full snapshot of the world, so starting one asks the game for a fresh stream. Your view does not jump.

If the game moves on to a different match during a session, Vantage closes the current file and starts a new one.

### From a replay

Replays the game plays for you are live sessions too, so the same options apply. See [Replays](Replays.md#playing-a-replay). To record without opening the interface:

```sh
vantage record match.vrec --replay 'Z:\home\you\MyGame.aoe2record' --speed EXTRA_FAST
```

`vantage record` without `--replay` records whatever the game is streaming, such as a match you are spectating. It stops when the stream ends, after `--seconds`, or after `--quiet-seconds` with no data. <kbd>Ctrl+C</kbd> stops it cleanly, and the file is complete up to that point. See [Command line](Command-line.md#vantage-record) for every flag.

A minimised game streams far fewer particle effects (smoke, dust and so on). If you want them all in the recording, keep the game window open while recording.

## Where recordings go

By default, recordings go to `~/.local/share/vantage/recordings` on Linux and `%LOCALAPPDATA%\Vantage\recordings` on Windows. `vantage serve` prints the folder in use at start-up, and `--recordings-dir` changes it. Live recordings are named `live-YYYYMMDD-HHMMSS-N.vrec`.

The home screen's **Recordings** tab lists that folder, newest first, and has **Open recordings folder**.

## Opening a recording

- Home screen → **Recordings** → **Open**, or type a path into "Open a .vrec by path".
- `vantage serve --open match.vrec`
- Double-click it in your file manager, after `vantage register-handler`. See [Live games](Live-games.md#the-in-game-spectate-button).
- `vantage open-url /path/to/match.vrec`, which hands the file to a Vantage that is already running.

**Bookmarks** you set are saved next to the recording as `match.vrec.bookmarks.json`. Share that file too if you want the other person to have them.

## Inspecting a recording

```sh
vantage info match.vrec
```

```
match.vrec: 6284 frames, 10.5 game-min, errors=0
map: Arabia.rms  size: [120, 120]
  P1 Alice                  Khitans      playing   K/D 3/1  collected 2505  ages [9.3]
  P2 Bob                    Danes        playing   K/D 1/3  collected 2711  ages []
```

Each player line shows the player's status at the end of the recording (`playing`, `won`, `lost` or `resigned`), kills and deaths, total resources collected, and the game minute at which each new age was reached. `--json` prints everything as JSON instead: the header, status, match information, the per-player summary and the number of events.

## Good to know

- **Interrupted recordings still work.** Frames are appended as they arrive. If Vantage or the computer stops mid-game, the file plays up to its last complete frame.
- **Size.** Recordings are gzip-compressed and grow with the number of players and the length of the game. The light stream (`--light`, or a replay being read ahead) and `--no-particles` make them smaller. For example, an 8-player, 47-minute game recorded with the light stream was about 130 MB.
- **Game versions.** A recording stores the game build and the game mode (Age of Empires II or Return of Rome) it was made with. Graphics and names come from the installation of whoever watches it.
- **Format.** The layout is described in the [architecture notes](https://github.com/dkapellusch/vantage-aoe2/blob/main/docs/architecture.md#the-vrec-recording-format).
