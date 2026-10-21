# Vantage

Vantage is a spectator and replay viewer for **Age of Empires II: Definitive Edition** that runs in your browser. It reads the game's own spectator stream, rebuilds the full state of the match and draws it with your installed game's graphics. On top of that it adds a casting HUD, statistics and time controls.

It has three sources:

| Source | Needs the game running? | Needs certificates? | Page |
|---|---|---|---|
| A **live game** you are spectating | Yes | Yes | [Live games](Live-games.md) |
| A **replay** (`.aoe2record`), played by the game | Yes | Yes | [Replays](Replays.md) |
| A **recording** (`.vrec`), Vantage's own format | No | No | [Recordings](Recordings.md) |

Vantage reads graphics, icons, names and sounds from your **installed** game. Without an install it still plays recordings, but with plain graphics and no sound.

## Start here

1. [Installation](Installation.md): install Vantage with `uv` or `pipx`.
2. [Quick start](Quick-start.md): run `vantage serve --open` and pick a source.
3. [Interface tour](Interface-tour.md): what every panel shows.

## Reference

- [Time controls](Time-controls.md): seeking, speeds, reverse playback and bookmarks
- [Hotkeys](Hotkeys.md): every default key, and how to rebind them
- [Settings](Settings.md): every setting and its default
- [Casting and OBS](Casting-and-OBS.md): names, series, overlays and the OBS browser source
- [Command line](Command-line.md): every `vantage` command and flag
- [Translations](Translations.md): how the interface is translated

## Help

- [Troubleshooting](Troubleshooting.md)
- [FAQ](FAQ.md)

## For developers

The repository's `docs/` folder has the [architecture](https://github.com/dkapellusch/vantage-aoe2/blob/main/docs/architecture.md), the [wire format](https://github.com/dkapellusch/vantage-aoe2/blob/main/docs/wire-format.md) and the [development guide](https://github.com/dkapellusch/vantage-aoe2/blob/main/docs/development.md).

---

Vantage is not affiliated with or endorsed by Microsoft, World's Edge, Forgotten Empires or CaptureAge. Age of Empires is a trademark of Microsoft.
