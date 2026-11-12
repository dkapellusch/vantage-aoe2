# Casting and OBS

Vantage was built to be shown on stream. This page covers the casting settings, the clean-feed keys and the two ways to bring Vantage into OBS (or any streaming software that has a browser source).

## Casting settings

Open **Settings → Casting**. Open a game first, because team and player rows only appear when there is a game to name.

### Browser source

This section shows the address of the HUD-only overlay page, with a **Copy** button. See [OBS](#obs) below.

### Panel offsets

These move panels away from their default positions, so they do not cover your webcam, a sponsor bar or the game's own interface. The values are in 1080p pixels and scale with the interface. Positive values move a panel up and to the right, and negative values move it down and to the left.

| Offset | Moves |
|---|---|
| Team overview offset | the team overview (and the end-of-game panel), downwards |
| Dashboard offset | the dashboard |
| Score offset | the scoreboard |
| Minimap offset | the minimap |
| Unit panel offset | the selection panel |
| Event notifications offset | the event log |

**Reset offsets** puts them all back.

### Scoreboard

| Control | What it does |
|---|---|
| Show scoreboard | Turn the scoreboard on or off |
| Hide score | Hide the score |
| Hide score dots | Hide the series dots next to team names |
| Main text, Secondary text | Free text on the scoreboard, such as the event and the round |
| Tournament stage | For example "Grand final" |

### Series

| Control | What it does |
|---|---|
| Series type | **Best of N** (the series ends when a side wins a majority) or **Play all N** |
| Number of games | 1 to 21 |
| Game winners | Pick the winner of each game. Two-team games use the two teams, and FFA uses the players |
| Show the series on the scoreboard | Off until you set it up. It turns on by itself once a game has a winner |
| Series text override | Replace the series label, for example "Bo5" |
| Score text override | Replace the score, for example "2 - 1" |

### Teams

For each team you can set a **team name** (the default joins the player names), a **seed or Elo text** shown next to the name (for example "#1 seed", in two-team games), and a **team captain**. In team-colour mode (<kbd>Ctrl+Alt+G</kbd>) the team uses its captain's colour.

### Players

For each player you can set a **display name** and a **flag or image**. Pick a country flag, one of your custom images, or enter an image URL.

Overrides follow the player into later games: they are keyed by the player's profile or name, not by the lobby slot. So a tournament's names and flags carry over from game to game.

### Custom images

Put pictures (PNG, JPEG, GIF, WebP or SVG) in the `images` folder of Vantage's data directory (`~/.local/share/vantage/images` on Linux and `%LOCALAPPDATA%\Vantage\images` on Windows, by default). **Open images folder** opens it. Press **Refresh** and they appear in the players' image lists. Vantage serves them at `/images/<file name>`.

## A clean feed

| Key | Effect |
|---|---|
| <kbd>Alt+O</kbd> | Hide the whole interface |
| <kbd>Alt+Shift+O</kbd> | Keep the minimap while the interface is hidden |
| <kbd>F6</kbd> / <kbd>F7</kbd> | The Minimal or Caster HUD preset; hold <kbd>`</kbd> to peek at Full |
| <kbd>Alt+A</kbd> | Autocast: let Vantage direct the camera |
| <kbd>F11</kbd> | Full screen |

These settings are also useful on stream:

- **Interface → Look → tooltips**: turn off icon names or detailed help, so tooltips do not pop up over the feed.
- **Interface → Playback → Disable scrubbing**: a stray click on the time bar will not jump in time.
- **Interface → Panels → Minimal UI** and **Mini dashboard**: less on screen.
- **Skins**: your league's colours and logo. See [Settings](Settings.md#skins).
- Hold <kbd>Tab</kbd> to show the audience a player's fog for a moment. Use <kbd>Ctrl+Shift+F1</kbd>–<kbd>F8</kbd> to stay in a player's perspective.

## OBS

There are two ways to bring Vantage into OBS.

### 1. Capture Vantage itself

Show the whole Vantage view, map included, as your game picture. Either:

- add a **Window Capture** of the browser window running Vantage, or
- add a **Browser** source with the URL `http://127.0.0.1:8740/` and your stream's resolution. Use **Interact** to click and type in it.

### 2. Overlay the HUD on the game

Add a **Browser** source with:

```
http://127.0.0.1:8740/?overlay=1
```

This page draws the interface (scoreboard, panels, minimap) without the map, on a transparent background. Place it above a capture of the game itself.

### The same HUD in OBS, by link

The overlay page takes the HUD from its address, so it does not need a profile loaded by hand. In your own browser open **Customize** (<kbd>Alt+V</kbd>) → **Share link** and copy the second link into the Browser source:

```
http://127.0.0.1:8740/?overlay=1#hud=caster
http://127.0.0.1:8740/?overlay=1#hud=c1.pu-fo-et-mm.age-vil-mil-army-idle-bank-rate
```

The first is a stock preset, the second a HUD you ticked together (panels, then Pulse strip metrics, as short codes). Positions do not travel in the link. For those, save the layout under a name in Customize → **Layout**, press **Publish for OBS**, and add its name:

```
http://127.0.0.1:8740/?overlay=1#hud=caster&layout=Spring%20Cup
```

**A HUD per OBS scene.** In **Edit layout** (<kbd>Alt+L</kbd>) each panel has **Show in scenes**: In-game, Fight, Break, Post-game. Give each OBS scene its own Browser source and name the scene after the preset:

```
http://127.0.0.1:8740/?overlay=1#hud=caster.fight
http://127.0.0.1:8740/?overlay=1#hud=caster.post
```

Without a scene in the link the page follows the match by itself (Fight while kills cluster, Post-game once it ends). On the overlay page nothing can be dragged or resized, no hover toolbars appear, and the first-run hint is never shown.

### Each browser has its own settings and clock

Your settings are kept per browser, and OBS's browser source is a browser of its own. The overlay page therefore starts with default settings, and its playback runs separately from the tab you are using. To give it your casting setup:

- In your normal browser, save a profile (**Settings → Profiles → Save as profile**). Then, in OBS, right-click the source → **Interact**, press <kbd>Esc</kbd>, open **Settings → Profiles** and **Load** it. Or
- start Vantage with `--patch-config` to push the same settings to every browser that opens it:

  ```sh
  vantage serve --live --patch-config '{"mainText": "Spring Cup", "stageName": "Grand final", "showElo": false}'
  ```

For a live game, both pages follow the live edge by default, so they stay together. If you seek or pause in one, the other is not affected.

### Remote OBS

Vantage listens on `127.0.0.1` only. To reach it from another computer you can start it with `--host 0.0.0.0`. **Do this only on a network you trust.** Vantage has no login, and anyone who can reach the port can use it, including asking it to open files on your computer and to start the game.

## Statistics for graphics

`http://127.0.0.1:8740/stats-dump` returns everything the statistics screens show as one JSON document: the match, the per-player summary, the time series and the event log. Use it to drive your own graphics. The statistics screen's **Export stats** downloads the same data as JSON plus a CSV of the time series.
