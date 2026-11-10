# FAQ

### Is Vantage affiliated with the game's developers or other spectator tools?

No. Vantage is an independent project. It is not affiliated with or endorsed by Microsoft, World's Edge, Forgotten Empires or CaptureAge.

### Does it cost anything? Are some features locked?

No. Vantage is free and open source (MIT). There are no accounts, subscriptions or locked features.

### Does Vantage send any data anywhere?

No. It has no telemetry and no accounts. It talks only to the game on `127.0.0.1` and to your browser. The one exception is a custom image URL you type into the casting settings, which your browser loads.

### Do I need the game installed?

For the full picture, yes. Vantage ships no game assets: graphics, sounds, civilisation and unit names, icons and tech trees are all read from your own installation while Vantage runs. Without an install, Vantage still plays recordings, but with plain graphics and no sound. The game only has to be **running** for live games and replays.

### Why does it need the game running to watch a replay?

A `.aoe2record` file holds the players' commands, not the result of them. Only the game's own simulation can turn those commands into a match, so Vantage asks the game to play the replay and watches what it streams. To watch a game again without the game running, save it as a `.vrec` [recording](Recordings.md).

### Where do I get the certificate files?

Vantage cannot provide them and does not explain how to obtain them. The game's spectator API only accepts clients with a certificate it trusts. If you have the three files, see [Live games](Live-games.md#certificates) for where to put them. Without them you can still watch `.vrec` recordings that other people share.

### Can I spectate a game I am playing in?

No. The game refuses its spectator API to players in the match. You can watch matches you spectate, and replays.

### Can I share a recording?

Yes. Send the `.vrec` file (and its `.bookmarks.json`, if you want to share your bookmarks). The other person needs Vantage, but no certificates. With the game installed they see its full graphics and hear its sounds.

### Does it work with Return of Rome?

Yes. Vantage reads Return of Rome's own names, civilisations, tech trees, icons and graphics, and switches the game to Return of Rome when you play one of its replays.

### Does it work on Windows? On the Microsoft Store version?

Native Windows support is new. The test suite passes on Windows, but it has not yet been used with the game on a Windows PC, so please report anything that does not work. Vantage finds Steam installs through the registry and `libraryfolders.vdf`. For an install elsewhere, give its folder with `--game-dir`. The Microsoft Store version has not been tested.

### Does it work on macOS?

No. The game does not run on macOS, and Vantage needs the game's files.

### Does Vantage change my game?

No. It reads the game's files and caches converted icons, sprites and sounds in its own cache folder (`~/.cache/vantage` on Linux, `%LOCALAPPDATA%\Vantage\cache` on Windows). It asks the running game, through the spectator API, to do what you ask: load a replay, join a lobby, pause, change speed, perspective or fog, minimise. It can start the game through Steam when you press "Start Age II". `register-handler --captureage` changes which program opens the game's Spectate links, and `--release-captureage` undoes that.

### Which browser should I use?

Any current browser with WebGL2. Chromium-based browsers draw the busiest battles fastest. Firefox works too.

### Can I use it in OBS?

Yes, either by capturing Vantage's window or as a browser source. `/?overlay=1` gives a transparent HUD-only page. See [Casting and OBS](Casting-and-OBS.md).

### Can my co-caster watch from another computer?

Each person can run Vantage on their own computer. To share one instance, start it with `--host 0.0.0.0` and open `http://<your computer>:8740/`, but only on a network you trust. Vantage has no login, and each browser keeps its own settings and its own playback position.

### How fast can it play?

Recordings play at up to 8×, forwards or backwards. For replays the game plays, the game's own speed is the limit: about 8× at best, and less late in big games. Vantage buffers ahead so you can still watch at 8×. See [Replays](Replays.md#fast-replay-and-read-ahead).

### How do I translate Vantage into my language?

See [Translations](Translations.md).
