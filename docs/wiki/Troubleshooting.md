# Troubleshooting

## Start with `vantage doctor`

```sh
vantage doctor
```

This checks Python, the gRPC libraries, the game install, the certificate files, whether the game is answering on port 4341, and your replay and recordings folders. It says what to fix for each problem. The terminal running `vantage serve` is the next place to look: Vantage prints its errors there, and its start-up message lists what is missing.

## Vantage cannot connect to the game

The connection card on the home screen says what is wrong:

| Message | Meaning |
|---|---|
| *Certificate files needed* / *Certificate files missing: live games and replays cannot connect* | One or more of the three certificate files is not in the certificate folder. The card names the files and the folder. See [Live games → Certificates](Live-games.md#certificates). Vantage cannot help you obtain these files. It keeps trying and connects once they are in place. |
| *No game found. Start Age of Empires II: DE (Vantage connects to its spectator port 4341) — retrying…* | Nothing answers on port 4341. |
| *The game refused the connection: check the certificate files — retrying…* | The game is running, but it rejected the secure connection. The certificate files are present but not ones the game accepts. |
| *Running — you are playing a game, not spectating* | The game refuses the spectator API to a player in the current match. Vantage can watch matches you spectate, and replays. |
| *Running — this game version needs a newer Vantage* | The game's API is newer than this Vantage. [Upgrade](Installation.md#upgrade). |

If the game is not found on port 4341:

1. **Is the game running?** The game serves its spectator API on port `4341` while it runs. After launching it, give it time to reach the main menu. Vantage keeps retrying every few seconds, so you can start Vantage first. `vantage doctor` reports whether anything answers on the port, or check by hand:

   ```sh
   ss -ltn | grep 4341                 # Linux
   netstat -ano | findstr :4341        # Windows
   ```

2. **Is another program using port 4341?** If so, the game cannot open its API. Close that program and restart the game.
3. **Are both on the same computer?** Vantage connects to `127.0.0.1`. Under Proton this works as is, because the game and Vantage share the machine's network.

## Game not found

`vantage serve` says `Game install: not found` (or `vantage doctor` warns about it). The browser shows *Age of Empires II: DE install not found: showing plain graphics without sound*. Recordings still play, but without the game's graphics, icons and sounds.

Vantage looks for the install in this order:

1. `$VANTAGE_GAME_DIR`, if set,
2. the folder the running game reports, once Vantage has connected to it,
3. `steamapps/common/AoE2DE` in every Steam library. Libraries are read from `libraryfolders.vdf` in Steam's own folder: `~/.steam/steam`, `~/.local/share/Steam` or `~/.steam/root` on Linux. On Windows, that is the folder Steam's registry keys name, or `C:\Program Files (x86)\Steam`.

A folder counts as the game if it contains `resources/_common`. If yours is elsewhere, use any of these:

- `vantage serve --game-dir /path/to/AoE2DE`
- `export VANTAGE_GAME_DIR=/path/to/AoE2DE`
- **Settings → Interface → Game directory**, which must be a folder containing `AoE2DE_s.exe`.

**Flatpak Steam** keeps its libraries under `~/.var/app/com.valvesoftware.Steam/`, which Vantage does not search. Point `--game-dir` at the game folder and `--replay-dir` at your replay folders.

## No replays in the replay browser

On Linux, replays are found inside the game's Proton prefix in each Steam library (`steamapps/compatdata/813780/pfx/drive_c/users/steamuser/Games/Age of Empires 2 DE/<profile>/savegame`). On Windows they are found in `%USERPROFILE%\Games\Age of Empires 2 DE\<profile>\savegame`. Once Vantage has connected to the running game, the profile folder the game reports is added too. If yours are elsewhere, use `--replay-dir DIR`; you can repeat it. Note that `--replay-dir` replaces the automatic list.

## A replay does not load

- **"Load this replay?"** The game is in a game it would have to leave. Agree, or finish that game first.
- **The replay is marked *old*.** It was recorded with an older game build, and the game generally cannot play those.
- **From the command line**, `--replay` needs the path **as the game sees it**: a Windows path. Under Proton that is `C:\…` inside the prefix or `Z:\…` for anything else on your Linux file system. See [Replays](Replays.md#from-the-command-line).

## The in-game Spectate button does nothing

On Linux:

1. Run `vantage register-handler --captureage`, then check:

   ```sh
   xdg-mime query default x-scheme-handler/captureage    # should print vantage.desktop
   ```

2. The game's Wine prefix needs the `captureage` scheme registered. See [Live games](Live-games.md#making-the-button-open-vantage-linux). A Proton update can reset the prefix, so re-import the registry file afterwards.
3. If a "Choose application" dialog appears somewhere on your desktop, run `register-handler --captureage` again. It records Vantage as the remembered choice.
4. Test with the real button. A link opened from a terminal can be treated differently by the desktop portal.

To undo: `vantage register-handler --release-captureage`.

On Windows (new), run `vantage register-handler --captureage` and try the button again. Please report what happens.

## No sound

Sound needs `vgmstream-cli`. Install it and make sure it is on your `PATH`, or set `VANTAGE_VGMSTREAM`. See [Installation](Installation.md#optional-game-sounds). Also check **Settings → Sound** and that the browser tab is not muted. Browsers only play sound after you have clicked in the page.

## Slow or stuttering playback

- Keep **Settings → Graphics → GPU rendering** on, and make sure hardware acceleration is enabled in your browser. On Linux, check `chrome://gpu` or `about:support`: software rendering is much slower.
- Chromium-based browsers draw large battles faster than Firefox.
- "Loading graphics…" while fast-forwarding means new units' graphics are being prepared. It settles after the first time a scene is shown. Turn off **Wait for graphics** if you would rather never pause.
- A browser that is covered or minimised throttles the page heavily. If the game window covers the browser, keep **Minimise Age II automatically** on.
- At 8× late in a large replay, the game itself may not keep up. See [Replays](Replays.md#fast-replay-and-read-ahead).
- <kbd>F10</kbd> shows the frame rate and the real speed. <kbd>Ctrl+Alt+Shift+P</kbd> opens a performance view.

## Missing particles (smoke, dust) in a recording

A minimised game streams far fewer particle effects. Fast replays use a lighter stream that leaves out cosmetic effects. For a complete recording, keep the game window open and record at normal speed.

## An empty `.vrec` file

A recording starts with the first full snapshot the game sends. If a session ended before the game sent anything, the file has no frames. It is safe to delete.

## Port 8740 is in use

Another program, or another Vantage, is using it. Start with `--port 8750` (and pass the same `--port` to `open-url` and `register-handler` if you use them).

## My settings disappeared

Settings are stored in the browser, per browser and per address. A different browser, a private window or a different `--port` starts fresh. Use **Settings → Profiles** to save and load them. See [Settings](Settings.md#where-settings-are-stored).

## Proton notes

- The game runs inside Proton's Wine prefix, `steamapps/compatdata/813780/`. Vantage runs natively on Linux and talks to the game over `127.0.0.1`.
- Paths the game reports or expects are Windows paths. `C:\` is the prefix's `drive_c`, and `Z:\` is your Linux root. Vantage translates between them for the replay browser and links. You only need to write such paths yourself when you use `--replay` on the command line.

## Reporting a bug

Please open an issue at <https://github.com/dkapellusch/vantage/issues> and include:

- the output of `vantage doctor`,
- what the terminal running `vantage serve` printed,
- your browser, and any errors in its developer console (<kbd>F12</kbd>),
- whether it happens with a live game, a replay or a recording (and, if you can share it, the `.vrec`).

**Never attach your certificate files.**
