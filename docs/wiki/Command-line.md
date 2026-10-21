# Command line

```
vantage [--version] COMMAND ...
```

| Command | What it does |
|---|---|
| [`serve`](#vantage-serve) | Start the Vantage server and interface |
| [`record`](#vantage-record) | Record the running game's stream to a `.vrec`, with no interface |
| [`info`](#vantage-info) | Summarise a `.vrec` recording |
| [`open-url`](#vantage-open-url) | Handle a `vantage://` or `captureage://` link, or a `.vrec` file |
| [`register-handler`](#vantage-register-handler) | Make Vantage the handler for links and `.vrec` files |
| [`doctor`](#vantage-doctor) | Check what Vantage can find on this machine |

`vantage` on its own prints this list. `vantage COMMAND --help` lists a command's options. `python -m vantage` is the same as `vantage`.

## vantage serve

```
vantage serve [options] [FILE.vrec]
```

Starts the HTTP server and serves the interface at `http://HOST:PORT/`. With no source it starts idle, and you pick a source on the home screen.

**Source** (choose at most one):

| Option | Meaning |
|---|---|
| `FILE.vrec` | Open this recording (as a file manager passes it). |
| `--recording FILE`, `--start-file FILE` | Open this recording. |
| `--live` | Connect to the running game on `127.0.0.1:4341`. |

**With `--live`:**

| Option | Meaning |
|---|---|
| `--replay PATH` | Ask the game to play this `.aoe2record`. The path is **as the game sees it**: a Windows path, or under Proton a `C:\…` path inside the game's prefix or `Z:\…` for the rest of your file system. See [Replays](Replays.md#from-the-command-line). |
| `--cloud` | With `--replay`: the value is a cloud replay name. |
| `--game {aoe2,ror}` | Switch the game to Age of Empires II or Return of Rome first. |
| `--lobby ID` | Join this lobby as a spectator. |
| `--no-record` | Do not save the session as a `.vrec`. By default `--live` records. |
| `--minimize-game` | Minimise the game window. |

If the game would have to leave a game in progress to do what you asked, the browser asks you first.

**Server and folders:**

| Option | Default | Meaning |
|---|---|---|
| `--host HOST` | `127.0.0.1` | Address to listen on. Vantage has no authentication, so only listen beyond localhost on a network you trust. |
| `--port PORT` | `8740` | Port to listen on. |
| `--open` | | Open the interface in your default browser. |
| `--recordings-dir DIR` | `~/.local/share/vantage/recordings` (Linux), `%LOCALAPPDATA%\Vantage\recordings` (Windows) | Where recordings are written and listed. |
| `--game-dir DIR` | detected | The game's install folder. See [Troubleshooting](Troubleshooting.md#game-not-found). |
| `--replay-dir DIR` | detected | A replay folder for the replay browser. Repeat it for several folders. When given, it replaces the automatic list (every AoE2 profile in every Steam library, plus the live game's profile). |

**Session behaviour:**

| Option | Meaning |
|---|---|
| `--exit-on-stream-end` | Stop the server when the game's stream ends (`--live`) or when the browser reaches the end of the recording. |
| `--patch-config JSON` | A JSON object of [settings](Settings.md) applied on every browser that opens Vantage, on top of its saved settings. |
| `--force-default-config` | Browsers ignore their saved settings for this session. |

At start-up Vantage prints its address, the recordings folder, the game install it found, and what is missing for live games and replays:

```
Vantage is running at http://127.0.0.1:8740/
  Open that address in your browser (or start with --open).
  Recordings: /home/you/.local/share/vantage/recordings
  Game install: /home/you/.local/share/Steam/steamapps/common/AoE2DE
Press Ctrl+C to stop.
```

Examples:

```sh
vantage serve --open
vantage serve --open match.vrec
vantage serve --open --live --lobby 123456789
vantage serve --live --replay 'C:\users\steamuser\Games\Age of Empires 2 DE\0\savegame\x.aoe2record' --no-record
vantage serve match.vrec --exit-on-stream-end --force-default-config --patch-config '{"useMinimalUi": true}'
```

## vantage record

```
vantage record OUT.vrec [options]
```

Connects to the running game and writes its stream to `OUT.vrec`, with no interface. It stops when the stream ends, after `--seconds`, after `--quiet-seconds` with no data, or on <kbd>Ctrl+C</kbd> (also <kbd>Ctrl+Break</kbd> on Windows). The file is complete in every case.

| Option | Default | Meaning |
|---|---|---|
| `--replay PATH` | | Ask the game to play this `.aoe2record` first (a path as the game sees it). If the game is in a game, it is left without asking: running the command counts as your agreement. |
| `--seconds N` | `0` | Stop after N seconds (0 = until the stream ends). |
| `--quiet-seconds N` | `20` | Stop when no frame has arrived for N seconds. |
| `--resolution-ms N` | `100` | Game milliseconds per frame. Larger values give smaller files and coarser movement, and nothing is lost between frames. |
| `--speed {SLOW,NORMAL,FAST,EXTRA_FAST}` | | Set the replay speed once the replay is running. |
| `--light` | | The fast-replay stream: low-priority and sleeping units every 2 s, and only particle effects that show game state. `--resolution-ms` still applies. |
| `--minimize` | | Minimise the game window while recording. A minimised game streams fewer particle effects. |
| `--no-particles` | | Leave out particle effects (smoke, fire, dust) for a smaller file. |

It needs the [certificates](Live-games.md#certificates) and prints progress every 10 seconds:

```sh
vantage record final.vrec --replay 'Z:\home\you\final.aoe2record' --speed EXTRA_FAST --light --minimize
```

## vantage info

```
vantage info RECORDING.vrec [--json]
```

Prints a summary of a recording: frames, game minutes, decoding errors, the map, and a line per player with status, kills and deaths, resources collected and age-up times. `--json` prints the header, status, match information, summary and event count as JSON. See [Recordings](Recordings.md#inspecting-a-recording).

## vantage open-url

```
vantage open-url URL [--port PORT]
```

Handles one of these:

- `vantage://spectate/?lobbyid=ID[&source=PLATFORM]`: spectate a lobby.
- `vantage://spectate/?aoe2record=NAME_OR_PATH[&cloud=1]`: play a replay. A bare name is looked up in your replay folders, and a replay in a Return of Rome folder switches the game to Return of Rome.
- `vantage://spectate/`: watch whatever the game is showing.
- the same links with `captureage://`, as the game's own Spectate buttons send them.
- a path to a `.vrec` file.

If Vantage is already running on `--port` (default `8740`), the link is handed to that instance and a browser tab is opened. Otherwise Vantage starts (`serve --open`) with that source. A link never ends a game in progress without asking you in the browser.

This is the command the link handlers run. See [Live games](Live-games.md#the-in-game-spectate-button).

## vantage register-handler

```
vantage register-handler [--port PORT] [--no-update] [--captureage | --release-captureage]
```

Registers Vantage to open `vantage://` links and `.vrec` files.

| Option | Meaning |
|---|---|
| `--port PORT` | The port the handler passes to `open-url` (default `8740`). |
| `--captureage` | Also take over `captureage://` links, so the game's own Spectate buttons open Vantage. The previous handler is remembered. |
| `--release-captureage` | Give `captureage://` back to the handler it had before `--captureage`. |
| `--no-update` | Linux: only write the files, and do not run `xdg-mime` or update the desktop and MIME databases. Windows: do not tell Explorer that associations changed. |

**Linux**: writes `$XDG_DATA_HOME/applications/vantage.desktop` (normally `~/.local/share/applications/`) and a MIME type for `*.vrec` (`application/x-vantage-recording`). It then makes them the defaults with `xdg-mime` and refreshes the databases. With `--captureage` it also records Vantage as xdg-desktop-portal's remembered choice for `captureage://`, so no app chooser appears. Missing tools are skipped with a message.

**Windows** (new, less tested): writes per-user keys under `HKEY_CURRENT_USER\Software\Classes`: the `vantage` protocol, `.vrec` (as `Vantage.Recording`), and with `--captureage` the `captureage` protocol's command. The command it replaces is remembered for `--release-captureage`. If there was no per-user handler before, `--release-captureage` removes the per-user key instead.

## vantage doctor

```
vantage doctor [--game-dir DIR] [--recordings-dir DIR]
```

Checks what Vantage can use on this machine and prints a checklist. Each line is `ok`, `warn` or `FAIL`, and every problem comes with a hint:

| Check | What it looks at |
|---|---|
| Python | version 3.12 or newer |
| gRPC and protobuf | the libraries live games need can be imported |
| Game install | the game folder (from `--game-dir` or auto-detection) contains `AoE2DE_s.exe` |
| Certificates | all three certificate files are in the certificate folder |
| Game running | something answers on `127.0.0.1:4341` |
| Replay folders | how many replay folders and replays were found |
| Recordings folder | the recordings folder (from `--recordings-dir` or the default) and how many recordings it holds |

The last line sums up what you can watch, for example *Ready for recordings (.vrec). Live games and replays: see the warnings.* The exit status is 0 unless a check failed outright. Run it first when something does not work, and include its output in bug reports. There is an example in [Installation](Installation.md#check-the-installation).

## Environment variables

| Variable | Effect |
|---|---|
| `VANTAGE_CERTS` | Folder holding the three certificate files. |
| `VANTAGE_GAME_DIR` | The game's install folder. It replaces the Steam library search, the same as `--game-dir`. |
| `VANTAGE_DATA_DIR` | Vantage's data folder for profiles, skins and casting images (default `~/.local/share/vantage` on Linux, `%LOCALAPPDATA%\Vantage` on Windows). |
| `VANTAGE_VGMSTREAM` | Full path to `vgmstream-cli`, for game sounds. |
| `VANTAGE_SPRITE_WORKERS` | Number of processes that prepare sprites (default: CPU count − 2, between 1 and 8; `0` renders in the server process). |
| `VANTAGE_NO_LAUNCH` | When set, Vantage refuses to start the game ("Start Age II" fails). Useful on shared machines and in tests. |
| `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME` | Linux: the standard locations for the certificate folder, the cache of converted game assets (`$XDG_CACHE_HOME/vantage`) and the link handler files. |
| `APPDATA`, `LOCALAPPDATA` | Windows: the certificate folder is `%APPDATA%\Vantage\certs`; recordings, the cache and user content are under `%LOCALAPPDATA%\Vantage`. |
