# Changelog

All notable changes to Vantage are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Experimental local replay playback from the development copy (`--native-replay`,
  `--native-profile`, `--native-profile-sha256`, `--native-cache-dir`, `--native-replay-root`,
  `--native-timeout`; `vantage-native.py`, `vantage-v32.py`). It converts a replay on this machine
  with a pinned profile, without the running game. Alongside it: the native engine tools
  (`tools/native_*.py`) and the replay-simulation modules, with their tests.
- `native_v32_pipeline --preview-on-checksum-failure`: when a conversion stops at a failing original
  checksum, it converts the part of the match up to the last passing checksum as an incomplete
  preview.
- Approximate-checksum conversion (`native_v32_pipeline --approximate-checksums`, or
  `--approximate-on-checksum-failure` to rerun after a checksum stop): the derived host sets the
  game's ignore-checksum byte and runs to the end of the replay. The recording is labelled
  approximate (`native_v32_approximate.py`).

### Fixed

- A forager that became a builder or farmer before delivering its berries lost the secondary
  (bonus) wood already earned on that load; it now follows the carried berries.

- A completed timeline reopened from the playback index answered the resource and healing review
  queries as if nothing had been observed: those histories are now stored in the index (schema 3).
- The session event stream could end a recording's load without sending its final state.
- Local replay conversion runs its pinned research renderer and encoder in the repository holding
  their artifacts (it used this package's folder, where their imports do not resolve).

### Changed

- Brought up to date with the development copy of the viewer: the review workspace, player,
  combat, healing and resource reviews, review moments, panel resizing, camera follow and Autocast
  focus, and the DOM patcher for HUD panels.
- The GPU sprite atlas grows with the game, from 128 MB up to the *Sprite memory* setting (at most
  1 GB). It no longer evicts and re-uploads sprites in a late eight-player game at 8×, where
  playback used to stop at keyframes to wait for graphics.
- Less work every frame:
  - The minimap is drawn from cached layers.
  - The colour grade is baked into the cached ground when that gives the same picture.
  - Atlas uploads are capped per frame: a seek into a big battle no longer makes one long frame.
  - The fog canvases are reused and each view's fog is decoded once.
  - The event log appends rows instead of rebuilding them.
  - Per-entity bookkeeping no longer allocates.
  - The painter's sort computes each depth once.
  - Sound, Autocast and hero tracking no longer scan the whole event log.
  - The particle lighting pass is one canvas filter.
  - The dashboard is placed only when a panel changes size.
- Fewer and better-ordered requests:
  - Views are fetched and parsed in a worker, with high priority.
  - Sprites come over a second set of connections (the server's other loopback name).
  - Asset URLs carry the server's asset version and are cached for good.
  - Session updates no longer overlap.
  - The time series is fetched incrementally.
  - Dragging the time bar seeks at most every 80 ms on the 1 s view grid and cancels outdated
    requests.
  - A seek keeps showing the current picture until the new one arrives.
- *Sprite memory* defaults to 1536 MB (was 768; a saved 768 moves up). Decoded strips fill it
  only as a game needs them. At 768 MB, the whole-map view of a late eight-player game at 8× held
  for graphics on about 11 % of frames; at 1536 MB, on about 2 %.
- Settings → Graphics notes that bloom, anti-aliasing and the colour channel sliders turn off the
  GPU sprite batch.

- A live session left open on a paused or ended game no longer re-applies and re-records the
  game's full snapshot on every reconnect (one session wrote 514 identical 23 MB snapshots, a
  1.5 GB recording), and reconnects back off up to 60 s once the game is over. Recordings that
  already hold such repeats load them as no-ops: the first 40 frames of that recording now load
  in 5 s instead of 118 s.
- `/api/view` is answered from the stored JSON without parsing it again, and recent final views
  are kept: seeking late in a large game answers in a fraction of the time, also while a recording
  loads.
- Event and statistics requests no longer wait for frame ingestion; `/api/series?from=` returns
  only the rows a browser does not have yet, and the full series is encoded once per change.
- The session event stream sends timeline progress at most four times a second.
- Concurrent requests for the same sprite strip, icon, terrain texture or particle atlas convert
  it once; cache files are written whole; missing assets no longer close the connection; with
  mods enabled the mod folders are no longer rescanned for every sprite.
- Faster keyframes: the forest layer and the resources-left series read each Gaia master once.

### Added

- `/api/view` marks the newest keyframe of a growing timeline `"final": false`.
- `/api/config` reports `asset_version`; asset URLs that carry it as `av=` are cached by the
  browser for good (`immutable`).
- Sprites and `/api/config` allow the other loopback name of the same server (`localhost` and
  `127.0.0.1`) as a CORS origin, so a page can load sprites over a second connection pool.

## [0.1.0] - 2026-10-21

First public release.

### Added

- Live spectating of Age of Empires II: DE games, and replays played through the running game.
- `.vrec` recordings: every live session can be saved and played back without the game.
- Scoreboard, dashboards, statistics, tech trees, unit panel, minimap, event log and end-game
  summary.
- Time controls: scrubbing, rewind, fast forward, bookmarks.
- Casting tools: autocast camera director, OBS overlay mode, skins, hotkeys.
- Interface in 17 languages.
- Commands: `serve`, `record`, `info`, `open-url`, `register-handler`, `doctor`.

[Unreleased]: https://github.com/dkapellusch/vantage-aoe2/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dkapellusch/vantage-aoe2/releases/tag/v0.1.0
