# Time controls

Every source in Vantage can be paused, sped up, slowed down, rewound and seeked, including a live game. While you look back, the live game carries on, and you can return to the live edge whenever you like.

Vantage stores a snapshot of the whole match every second of game time. A jump to any moment is therefore a lookup and needs no re-simulation, and between snapshots units move smoothly.

## The time bar

The bar sits above the minimap. <kbd>T</kbd> shows or hides it. From left to right it has:

| Control | Key | What it does |
|---|---|---|
| ↺30 | <kbd>-</kbd> | Skip back 30 seconds |
| ⏪ | | Play backwards. Press again for 2×, 4×, 8× |
| Play / pause | <kbd>F3</kbd> | Pause or resume |
| ⏩ | | Fast forward. Press again for 2×, 4×, 8× |
| ↻30 | <kbd>=</kbd> | Skip forward 30 seconds |
| − *speed* + | <kbd>[</kbd> / <kbd>]</kbd> | Step the speed down or up. The current speed is shown between the buttons |
| ⚑ | <kbd>F4</kbd> | Bookmark the moment 30 seconds ago |
| ◂⚑ / ⚑▸ | <kbd>Shift+[</kbd> / <kbd>Shift+]</kbd> | Previous / next bookmark |
| LIVE | <kbd>End</kbd> | Jump to the live edge (or the end of a recording) and follow it |
| Clock | | The game time being shown |
| | <kbd>Home</kbd> | Jump to the start |
| Real speed | | Game time actually advanced per real second, against the target speed |
| ● REC / ■ | | Live sessions only: record to `.vrec`, stop watching |

Hover the bar to see the time under the pointer, and click or drag to jump there. Hatched red marks show where the game's stream skipped time. The real-speed readout turns orange when playback falls behind the target speed, either because your computer cannot keep up or because the game is slower than the speed you asked for.

## Speeds

The speeds are **×0.5, ×1, ×2, ×4 and ×8**, forwards and backwards. <kbd>]</kbd> steps up. <kbd>[</kbd> steps down, and stepping below the slowest forward speed switches to **reverse playback** (−×0.5 down to −×8). ⏪ and ⏩ go straight to playing backwards or forwards and get faster with each press.

In a live game you cannot play past the live edge. Playback waits there and carries on as new data arrives. Picking a speed keeps it, and <kbd>End</kbd> or **LIVE** goes back to following the live edge.

For replays the game plays, see [Replays: fast replay and read-ahead](Replays.md#fast-replay-and-read-ahead).

### "Loading graphics…"

When new units come into view, their graphics are prepared on demand. With *Wait for graphics* on (the default), playback holds for a moment until they are ready, like a video buffering, so nothing pops in half drawn. You will see "Loading graphics…" if that takes more than a moment. It is most common at the start of a fast-forwarded battle. Turn the setting off in Settings → Graphics if you would rather never wait.

## Bookmarks

- <kbd>F4</kbd> bookmarks the moment **30 seconds ago**, so you can mark something just after it happened.
- Right-click the time bar to add a bookmark there, or to remove one.
- <kbd>Shift+[</kbd> and <kbd>Shift+]</kbd>, or the ◂⚑ ⚑▸ buttons, step between bookmarks.

Bookmarks are saved for each game in a file next to its recording (`<recording>.vrec.bookmarks.json`). A live session that is not being recorded has no file, so its bookmarks last only while you watch.

## Jumping from elsewhere

- Click an event's time in the event log to jump to it.
- Right-click a chart on the statistics screen to jump to that moment.
- Click a moment on the end-game screen to jump back to it.
- Autocast's **Previous / Current / Next** step between a hero's moments.

## Settings

In **Settings → Interface → Playback**:

- **Disable scrubbing**: clicking the time bar no longer seeks. This is useful on stream so a stray click does not jump.
- **Time controls on the statistics screen**: show the time strip on the statistics screen, so its values follow the moment you choose.
- **Read replays ahead at full speed**: see [Replays](Replays.md#fast-replay-and-read-ahead).
