# Live games

In a live game, Vantage connects to the running game's built-in spectator API on `127.0.0.1:4341`. It streams the match as it happens, and you can pause, seek back and rewind while the game carries on. The same connection is used when the game plays a [replay](Replays.md) for Vantage.

## Certificates

The game's spectator API uses mutual TLS. The game only accepts a client that presents a certificate issued by the authority it trusts. **Vantage does not include that certificate and cannot provide it.** If you have the files, put all three in Vantage's certificate folder:

| File | What it is |
|---|---|
| `certificate-authority.pem` | the authority the game's server certificate is issued by |
| `cade-client.pem` | the client certificate |
| `cade-client.key` | the client certificate's private key |

The folder is:

- `$VANTAGE_CERTS`, if that environment variable is set, otherwise
- `~/.config/vantage/certs` on Linux (`$XDG_CONFIG_HOME/vantage/certs` if that is set), or
- `%APPDATA%\Vantage\certs` on Windows.

Run `vantage doctor` to check that Vantage sees them. The `vantage serve` start-up message and the home screen also say when files are missing and which folder they belong in. Without them the **Watch live** and replay buttons are disabled, and a connection attempt shows a *Certificate files needed* card instead of connecting. Vantage keeps trying, and connects as soon as the files are in place.

These files are private to you. **Never commit them to a repository or share them.** Without them you can still watch `.vrec` [recordings](Recordings.md).

## Connecting

1. Start Age of Empires II: DE. Vantage can also start it: use **Start Age II** in the ⛨ menu or on the connection card. That starts the game through Steam and follows it until Vantage is connected.
2. Connect, in either of these ways:
   - in the browser, open the home screen (<kbd>Ctrl+O</kbd>), go to **Live game** and press **Connect**, or
   - start Vantage with `vantage serve --open --live`.

The **Live game** tab has these options:

| Field | Meaning |
|---|---|
| Host : port | Where the game's API listens. The default is `127.0.0.1` : `4341`. |
| Spectate lobby id (optional) | Join that lobby as a spectator. Leave it empty to watch whatever the game is showing. |
| Record to .vrec | Save the session as a [recording](Recordings.md) while you watch. It starts ticked when the "Record live games to .vrec" setting is on (off by default). |

On the command line the equivalents are `--lobby ID` and `--no-record`. `vantage serve --live` **records by default**. See [Command line](Command-line.md#vantage-serve).

### What you can watch

- **A match you are spectating** in the game, including the spectator lobby. Vantage shows "Waiting for players…" and the spectator delay until the match starts.
- **A replay the game is playing.** See [Replays](Replays.md).
- **A lobby by id**, with `--lobby` or the lobby field. Vantage asks the game to join it as a spectator.

You cannot watch a game you are playing in. The game refuses the spectator API to a player, and Vantage shows *Running — you are playing a game, not spectating*.

### Status while connecting

The connection card shows what is happening: connecting, joining a spectator lobby, waiting in the lobby, loading a replay, and finally *Ready to watch* with the map and the number of players. In a spectator lobby it also shows the spectator delay.

### "Continue with request?"

Joining a lobby, loading a replay or switching between Age of Empires II and Return of Rome can make the game leave a game that is still running. When the game reports that, Vantage stops and asks you first. It never agrees on your behalf. (`vantage record --replay` is the one exception: running that command counts as your agreement.)

### While you watch

- **Pause, speed, fog and perspective** are passed on to the game as well, so the game's own view follows what you choose in Vantage. The exception is a replay being read ahead (see [Replays](Replays.md#fast-replay-and-read-ahead)): pausing there only pauses your view.
- **Minimise the game.** With the "Minimise Age II automatically" setting (on by default), the game window minimises while Vantage has focus. Use `--minimize-game` to do it from the command line.
- **Recording.** The ● REC button starts or stops saving the session. Starting a recording asks the game for a fresh full snapshot, because a recording must begin with one. The view carries on without a jump.
- **Dropped connections** reconnect by themselves every few seconds. The new stream starts with a full snapshot, so nothing is lost.
- **Waiting for players.** If no data arrives for three seconds while the game is neither paused nor over, Vantage shows that the game is waiting for a lagging or dropped player and logs it in the event log.
- **Stop watching** (■, or the ⛨ menu) disconnects. The game keeps running.

### "This game version needs a newer Vantage"

The game reports the version of its spectator API. If it is newer than Vantage knows, Vantage says so instead of showing broken data. Upgrade Vantage (see [Installation](Installation.md#upgrade)).

## The in-game Spectate button

The game has buttons that open a spectator app: **Spectate & Replays**, and **Spectate with CA** in the lobby browser and the replay list. They open a link such as:

```
captureage://spectate/?lobbyid=123456789&source=…
captureage://spectate/?aoe2record=MyReplay&source=gclient
captureage://spectate/
```

A `lobbyid` link spectates a lobby. An `aoe2record` link plays a replay (with `cloud=1` for a cloud replay). A link with no parameters watches whatever the game shows. Vantage accepts the same links with its own `vantage://` scheme.

`vantage open-url LINK` handles such a link. If Vantage is already running on that port, it hands the link to the running instance and opens a browser tab. Otherwise it starts Vantage. As with every other source, a link never ends a game in progress without asking.

### Making the button open Vantage (Linux)

```sh
vantage register-handler               # vantage:// links and .vrec files
vantage register-handler --captureage  # also the game's captureage:// links
```

`register-handler` writes `~/.local/share/applications/vantage.desktop` and a MIME type for `.vrec` files, and makes them the defaults with `xdg-mime`. `--captureage` also takes over `captureage://` links. Vantage remembers which program handled them before.

- The game's links reach your desktop through `xdg-desktop-portal`. When two programs claim `captureage://`, the portal shows an "open with" chooser instead of opening either. `--captureage` therefore also records Vantage as the portal's remembered choice.
- If `systemd-run` is available, Vantage runs in its own systemd scope. Otherwise it would inherit the portal's resource limits.
- `vantage register-handler --release-captureage` gives `captureage://` back to the previous program and clears the remembered choice.
- `--no-update` only writes the files and leaves `xdg-mime` and the desktop databases alone.

**Under Proton, the game's Wine prefix must know the scheme too.** The game runs inside Proton's Wine prefix (`steamapps/compatdata/813780`). Wine looks up URL schemes in `HKEY_LOCAL_MACHINE\Software\Classes` of that prefix. The game itself checks `HKEY_CURRENT_USER\Software\Classes\captureage` to decide whether to act on the button at all. If a spectator app is already installed in that prefix, the keys are there. Otherwise one way to add them is to save this as `captureage.reg`:

```
REGEDIT4

[HKEY_LOCAL_MACHINE\Software\Classes\captureage]
"URL Protocol"=""

[HKEY_LOCAL_MACHINE\Software\Classes\captureage\shell\open\command]
@="\"C:\\windows\\system32\\winebrowser.exe\" \"%1\""

[HKEY_CURRENT_USER\Software\Classes\captureage]
"URL Protocol"=""

[HKEY_CURRENT_USER\Software\Classes\captureage\shell\open\command]
@="\"C:\\windows\\system32\\winebrowser.exe\" \"%1\""
```

Then import it into the game's prefix, for example with [protontricks](https://github.com/Matoking/protontricks):

```sh
protontricks -c 'wine regedit /path/to/captureage.reg' 813780
```

`winebrowser` passes the link to `xdg-open`, which hands it to Vantage. A Proton update can reset the prefix, so re-import the file if the button stops working. Vantage does not change the Wine prefix for you.

### Making the button open Vantage (Windows)

*New and less tested.*

```
vantage register-handler
vantage register-handler --captureage
```

The first registers `vantage://` links and `.vrec` files. The second also takes over the game's `captureage://` links.

On Windows, `register-handler` writes keys under `HKEY_CURRENT_USER\Software\Classes`: the `vantage` URL protocol, `.vrec` (as `Vantage.Recording`) and, with `--captureage`, the `captureage` protocol's open command. It then tells Explorer that associations changed (skip that with `--no-update`). Everything is per user, so no administrator rights are needed. The game runs natively, so no Wine prefix is involved.

`--captureage` remembers the per-user `captureage` command it replaced. `vantage register-handler --release-captureage` puts that command back. If there was no per-user handler before, it removes the per-user key, so a machine-wide registration (for example, from another spectator app installed for all users) applies again.

## Troubleshooting

If Vantage does not connect, see [Troubleshooting](Troubleshooting.md#vantage-cannot-connect-to-the-game).
