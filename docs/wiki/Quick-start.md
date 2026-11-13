# Quick start

## 1. Start Vantage

```sh
vantage serve --open
```

This starts the server on `http://127.0.0.1:8740/` and opens it in your browser. The terminal shows where recordings go, where Vantage found the game, and anything that is missing:

```
Vantage is running at http://127.0.0.1:8740/
  Recordings: /home/you/.local/share/vantage/recordings
  Game install: /home/you/.local/share/Steam/steamapps/common/AoE2DE
  Live games and replays: certificate files missing from /home/you/.config/vantage/certs
    (certificate-authority.pem, cade-client.pem, cade-client.key; see https://github.com/dkapellusch/vantage-aoe2/wiki/Live-games)
Press Ctrl+C to stop.
```

If it says `Game install: not found`, see [Troubleshooting](Troubleshooting.md#game-not-found). Leave the terminal open while you watch. <kbd>Ctrl+C</kbd> stops Vantage. `vantage doctor` gives the same information as a checklist.

## 2. Pick a source

With nothing loaded, Vantage opens the **home screen** (also <kbd>Ctrl+O</kbd>, or the ⌂ button). Its **Get started** card offers the three sources: **Open a recording**, **Watch live** and **Browse replays**. Each says what it still needs, such as the certificate files or the game running. The home screen has four tabs:

| Tab | What it does |
|---|---|
| **Overview** | The current session, recent replays (**Watch**) and recent recordings (**Open**). |
| **Replays** | Every `.aoe2record` in your game profiles, with players, civilisations, map and length. Playing one asks the running game to load it, and Vantage watches it. See [Replays](Replays.md). |
| **Recordings** | Your `.vrec` files. **Open** plays one at once, without the game. You can also open a `.vrec` by path. See [Recordings](Recordings.md). |
| **Live game** | Connects to the running game: the match you are spectating, a replay it is playing, or a lobby to spectate. See [Live games](Live-games.md). |

Live games and replays need the game running and the API [certificates](Live-games.md#certificates). Recordings need neither, and look best with the game installed.

## 3. Find your way around

- Press <kbd>?</kbd> for the quick reference, which lists every key and mouse action.
- Press <kbd>Esc</kbd> to close the top window. With nothing open, <kbd>Esc</kbd> opens the ⛨ menu (Home, Statistics, Settings, Panels, Quick reference, Documentation, Tutorial, Full screen).
- Right-drag or middle-drag pans the map, and the wheel zooms at the cursor. On a trackpad, two fingers move the map and a pinch zooms. Click the minimap to jump.
- Click a unit to see its stats. Drag a box to select a group.
- <kbd>F3</kbd> pauses. <kbd>[</kbd> and <kbd>]</kbd> change speed (below pause, playback runs backwards). Click the time bar to seek.
- <kbd>Ctrl+Alt+S</kbd> opens the statistics.

A short tutorial runs the first time you open a game. Replay it with <kbd>F1</kbd>. The [Interface tour](Interface-tour.md) explains every panel.

## From the command line

You can also go straight to a source:

```sh
vantage serve --open match.vrec                 # a recording
vantage serve --open --live                     # whatever the running game shows
vantage serve --open --live --lobby 123456789   # join a lobby as a spectator
```

See [Command line](Command-line.md) for every option.
