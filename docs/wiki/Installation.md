# Installation

Vantage is a Python package (`aoe2-vantage`) that installs a `vantage` command. It serves its interface to your browser on `http://127.0.0.1:8740/`.

## What you need

| | Required? | Notes |
|---|---|---|
| Age of Empires II: DE, installed through Steam | Strongly recommended | Vantage reads graphics, names, icons and sounds from it, and finds it automatically in every Steam library. Without it, recordings still play, with plain graphics and no sound. Live games and replays need it running. |
| Python 3.12 or newer | Yes | `uv` can install a suitable Python for you. |
| `uv` or `pipx` | Yes | Either installs Vantage into its own environment. |
| `git` | Yes | Needed to install from a GitHub URL. |
| A browser with WebGL2 | Yes | A current Chromium-based browser or Firefox. |
| Certificate files for the game's API | For live games and replays | See [Live games](Live-games.md#certificates). Recordings play without them. |
| `vgmstream-cli` | Optional | Decodes the game's sounds. Without it Vantage runs silently. |
| `ffmpeg` | Optional | With vgmstream, re-encodes sounds to Ogg Opus (smaller files). |

## Platforms

- **Linux, with the game running under Steam Proton.** This is the tested platform.
- **Windows (native).** *New and less tested.* Vantage finds Steam through the registry, reads replays from `%USERPROFILE%\Games\Age of Empires 2 DE`, and registers its link handlers for your user account only. Please report problems.

macOS is not supported, because the game does not run there.

## Install with uv

```sh
uv tool install git+https://github.com/dkapellusch/vantage-aoe2
```

If the `vantage` command is not found afterwards, run `uv tool update-shell` and open a new terminal.

## Install with pipx

```sh
pipx install git+https://github.com/dkapellusch/vantage-aoe2
```

If the `vantage` command is not found afterwards, run `pipx ensurepath` and open a new terminal.

## Check the installation

```sh
vantage --version
vantage doctor
```

`vantage doctor` prints a checklist:

```
Vantage 0.1.0

  ok    Python: 3.12.13
  ok    gRPC and protobuf: importable
  ok    Game install: /home/you/.local/share/Steam/steamapps/common/AoE2DE
  warn  Certificates: missing certificate-authority.pem, cade-client.pem, cade-client.key in /home/you/.config/vantage/certs
        -> live games and replays need them: https://github.com/dkapellusch/vantage-aoe2/wiki/Live-games
  warn  Game running: nothing answers on 127.0.0.1:4341
        -> start Age of Empires II: DE to watch live games and replays
  ok    Replay folders: 2 folders, 85 replays
  ok    Recordings folder: /home/you/.local/share/vantage/recordings (3 recordings)

Ready for recordings (.vrec). Live games and replays: see the warnings.
```

`ok` lines are fine. `warn` lines limit what you can watch, and each comes with a hint. A `FAIL` line means Vantage cannot run at all, and then the command exits with status 1. Run it whenever something does not work. See [Troubleshooting](Troubleshooting.md).

## Optional: game sounds

Vantage looks for `vgmstream-cli` in this order:

1. `$VANTAGE_VGMSTREAM` (the full path to the program)
2. `~/opt/vgmstream/vgmstream-cli`
3. `vgmstream-cli` on your `PATH`

Get vgmstream from [vgmstream.org](https://vgmstream.org/) or your distribution's packages. Vantage uses `ffmpeg` if it is on your `PATH`.

## Optional: open links and recordings with Vantage

`vantage register-handler` makes Vantage open `vantage://` links and `.vrec` files from your file manager. With `--captureage` it also handles the game's own "Spectate" buttons. See [Live games](Live-games.md#the-in-game-spectate-button).

## Upgrade

```sh
uv tool upgrade aoe2-vantage
# or
pipx upgrade aoe2-vantage
```

Restart `vantage serve` and reload the browser tab afterwards.

## Uninstall

1. If you used `register-handler --captureage`, run `vantage register-handler --release-captureage` first. This gives the game's Spectate links back to the program that had them before.
2. Remove the package:

   ```sh
   uv tool uninstall aoe2-vantage
   # or
   pipx uninstall aoe2-vantage
   ```

3. Optionally delete Vantage's files. With the default locations:

   | Linux | Windows | Contents |
   |---|---|---|
   | `~/.local/share/vantage/` | `%LOCALAPPDATA%\Vantage\` | recordings, custom images, settings profiles, skins |
   | `~/.cache/vantage/` | `%LOCALAPPDATA%\Vantage\cache\` | icons, sprites and sounds converted from the game (rebuilt on demand) |
   | `~/.config/vantage/certs/` | `%APPDATA%\Vantage\certs\` | the certificate files you added |
   | `~/.local/share/applications/vantage.desktop`, `~/.local/share/mime/packages/vantage-recording.xml` | `HKEY_CURRENT_USER\Software\Classes\vantage`, `…\.vrec`, `…\Vantage.Recording` | link and file handlers from `register-handler` |

   Your browser keeps Vantage's interface settings in local storage for `http://127.0.0.1:8740`. Clearing that site's data removes them.

## Running from a source checkout

```sh
git clone https://github.com/dkapellusch/vantage-aoe2
cd vantage
uv sync
uv run vantage serve --open
```

See the [development guide](https://github.com/dkapellusch/vantage-aoe2/blob/main/docs/development.md) for tests and linting.
