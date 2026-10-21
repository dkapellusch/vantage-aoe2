# Replays

A `.aoe2record` replay is a log of every player's commands, not a recording of what happened. Only the game can turn those commands back into a match. So Vantage **asks the running game to play the replay** and watches the stream the game produces, exactly as it watches a [live game](Live-games.md). In other words, the game is the converter.

You therefore need:

- the game running, and
- the API [certificates](Live-games.md#certificates).

To watch a match again without the game, save it as a [recording](Recordings.md) while it plays.

## The replay browser

Open the home screen (<kbd>Ctrl+O</kbd>) and go to **Replays**. Vantage lists every `.aoe2record` it finds in:

- the `savegame` and `savegame/multi` folders of every AoE2 profile. Under Proton these live inside the game's prefix in each Steam library: `steamapps/compatdata/813780/pfx/drive_c/users/steamuser/Games/Age of Empires 2 DE/<profile>/`. On Windows they are in `%USERPROFILE%\Games\Age of Empires 2 DE\<profile>\`.
- the Return of Rome folders, `modes/Pompeii/savegame`.
- the profile folder the running game reports, once Vantage has connected to it.

To list other folders instead, start Vantage with `--replay-dir` (you can repeat it). **Open profile folder** opens the profile in your file manager.

Each row shows the players and civilisations, the map, the length, the date and the game version. Click a row for a details card with teams, Elo, the result and the lobby settings (map size, speed, population, starting age, victory condition and so on). Lengths, ratings and winners are read in the background, so they appear a few seconds after the list.

### Version check

Every replay records the game build it was made with. Vantage compares it with your installed game:

- **current**: same build. The game can play it.
- **old**: made with an older build. The game usually cannot play these correctly.
- **unknown**: no build information, or a build newer than the installed game.

### Search and filters

The search box matches player names, civilisations, map, mode and file name, and allows small typos. The filters are:

| Filter | Options |
|---|---|
| Game | All games, AoE2, Return of Rome |
| Civilisation | any civilisation in the list |
| Mode | any game mode in the list |
| Players | Any players, Humans only, Includes AI |
| Size | number of players |
| Player name | only replays with a player whose name contains this text |
| Search file names only | match the search text against file names only |
| Hide incompatible | hide replays recorded on an older game version |
| Show spoilers | show Elo, length and winner (on by default) |

Your filters are saved with your settings.

## Playing a replay

Press the play button on a row (or **Watch** on the Overview tab). These buttons are disabled, with the reason shown, while the certificate files are missing. Vantage then:

1. connects to the game,
2. switches the game to Return of Rome first if the replay is from that mode (or back to Age of Empires II),
3. asks the game to load the replay, and
4. shows the match as it streams in.

If the game is in the middle of something it would have to leave (a single-player, multiplayer or ranked game), Vantage asks **"Load this replay?"** first. Nothing is left without your agreement.

When the "Record live games to .vrec" setting is on, the replay is also saved as a [recording](Recordings.md) as it plays.

## Fast replay and read-ahead

The game plays replays at most at about 8× real time ("extra fast"). Late in a large game it can be slower than that, because simulating the match takes real work.

With the setting **Read replays ahead at full speed** (Settings → Interface → Playback, on by default):

- From the start, Vantage asks the game to play the replay at its fastest speed, using a lighter stream. In the light stream, low-priority and sleeping units update every 2 seconds and only particle effects that show game state are kept (fire, smoke, explosions, conversions, construction). Cosmetic ones such as dust and blood are left out.
- You watch from Vantage's buffer at whatever speed you choose, and you can seek anywhere in what has arrived. Pausing your view does not pause the game, so the buffer keeps filling.
- If you pick a speed the game cannot keep up with, Vantage waits once ("Buffering for 8×: m:ss") for long enough that the rest of the match plays through without stopping.
- The game window shows itself when the replay starts. Vantage minimises it again, because a window covering the browser makes the browser slow the page down.

With read-ahead off, Vantage sets the game's replay speed to match the speed you pick, and pausing pauses the game.

## From the command line

```sh
vantage serve --open --live --replay 'C:\users\steamuser\Games\Age of Empires 2 DE\76561190000000000\savegame\MyGame.aoe2record'
```

`--replay` takes the path **as the game sees it**:

- **Windows**: the normal path.
- **Under Proton**, files inside the game's prefix are on `C:\` (as above). Files elsewhere on your Linux system are on `Z:\`, so `/home/you/x.aoe2record` becomes `Z:\home\you\x.aoe2record`.

Other options:

- `--game ror` switches to Return of Rome first.
- `--cloud` treats `--replay` as the name of a cloud replay.
- A link names a replay in your profile by its file name alone: `vantage open-url 'vantage://spectate/?aoe2record=MyGame'`.

To save a replay as a recording without opening the interface, use `vantage record`:

```sh
vantage record out.vrec --replay 'Z:\home\you\MyGame.aoe2record' --speed EXTRA_FAST --light --minimize
```

See [Command line](Command-line.md#vantage-record) for every flag.
