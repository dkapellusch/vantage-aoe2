# Changelog

All notable changes to Vantage are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- HUD presets: **Minimal** (<kbd>F6</kbd>), **Caster** (<kbd>F7</kbd>), **Review** (<kbd>F8</kbd>),
  **Analyst** (<kbd>F9</kbd>) and **Full** (<kbd>Shift+F6</kbd>, the HUD as it was), with a hold-to-peek
  key (<kbd>`</kbd>) that shows Full while it is down. Each preset keeps its own edits; Full is never
  rewritten by another. A new viewer starts on Minimal when Vantage is embedded or hosted by a hub and
  on Full in the desktop app; saved settings keep what they had.
- The **Pulse strip**, a new panel beside the Scoreboard: one row per side with age, villagers,
  military, army value (the lead on the leading side), idle villagers, population, and each banked
  resource with its per-minute rate. Every value is a labelled button that opens Statistics.
- The **Focus slot** (one card at a time: production, research, economy, the last fight), the
  **Event ticker** (key events, two lines, fading), the **Selection chip**, the **Match story
  timeline** (army lead, age-ups, fights sized by resources lost, idle town centres and bookmarks on
  one axis, with the playback buttons; drag a span to investigate it) and **Review cards** (six
  mistake metrics side against side).
- **Customize** (<kbd>Alt+V</kbd>) replaces the Panels menu: presets, panels with their toggle keys,
  Pulse metrics, Team board rows, saved layouts (save, load, export, import, publish for OBS), a
  stream check, and a share link. The link (`#hud=caster`, `#hud=c1.pu-fo-mm.age-vil`) opens the same
  HUD for anyone and drives the `?overlay=1` OBS page, with a scene per OBS source (`#hud=caster.fight`).
- **Edit layout** (<kbd>Alt+L</kbd>): a separate mode with a library of panels and widgets (six single
  metrics, a chart of any series, the series score, a text or image), an inspector (size, scale,
  opacity, anchor, scenes, content, stream checks), a snap grid, a safe-area frame, a reserved webcam
  zone and undo. Every drag has a keyboard equivalent.
- A new viewer on a phone (a narrow touch screen) starts on Minimal, as embeds do: Full has no
  phone layout.
- Skip links (the first Tab stops) to the time controls, the toolbar, Customize and Statistics;
  spoken names for the controls drawn as a glyph (time controls, paging, event filters).
- A phone layout for every preset but Full: the map, two Pulse rows, the Match story and tabs that
  open a bottom sheet (a right-hand drawer in landscape).
- Toggle keys for the Dashboard (<kbd>Alt+B</kbd>), Event log (<kbd>Alt+E</kbd>), Selection panel
  (<kbd>Alt+U</kbd>), Scoreboard or Pulse strip (<kbd>Alt+G</kbd>), Focus slot (<kbd>Alt+K</kbd>) and
  Match story (<kbd>Alt+Y</kbd>).
- The recordings list says who played each recording, on what map and (once it has been opened)
  for how long, instead of only its file name. The match is read from each recording's first
  snapshot by a low-priority helper process and cached per file, so the list appears at once and
  fills in. Search matches player, civilisation and map names too.
- The quick reference (`?`) is grouped into sections laid out in columns.
- The minimap toolbar shows which modes are on (fog, minimap mode, resources left).

- Team board: in team games and 1v1s the team overview compares the two sides stat by stat,
  with bars and the leader's margin. It adds the collection rate (resources per minute over the
  last game minute, a new `collected_rate` view field and `rate_*` series) and resources
  collected over the whole game. A Players view gives a per-player table with team totals.
- Panels can be moved as well as resized: drag the ⠿ button in a panel's hover toolbar, or
  every panel in arrange mode (Alt+L). Panels snap to the window and to each other (Shift: no
  snapping).
- The Caster layout, now the default: the scoreboard across the top, the team overview bottom
  left, the minimap and time controls bottom right. Classic stays in the Panels menu.

- `tools/audit_resource_sources.py`, the resource-income inventory scanner, and a `py.typed`
  marker so projects importing `vantage` type-check against it.

### Fixed

- Resource accounting is complete and counted once ([docs/resources.md](docs/resources.md)).
  **Collected** is now what villagers and fishing ships gathered: relic, trade, market-sale and
  bonus income that the game's counter also includes is no longer in it or in the `/min` rates.
  **Bonus resources** gains the **Starting bonus** (Persians, Aztecs, Sicilians, Tupi; negative for
  Chinese, Huns and Maya; the Lithuanian Town Center food), also when it arrives with the first
  Town Center on a Nomad start, plus Tribute rows. Khmer farm food that the game's own counter
  drops above 8192 food is still collected. A new **Stockpile accounts** table per player lists
  starting resources, collected, bonus, trade, market, tribute, refunds and spending, which add up
  to the stockpile; an increase nothing explains is shown as **Unexplained gain**.
  `tools/reconcile_resources.py` checks a recording.
- The ground stays drawn after the browser loses the WebGL context (a driver reset, the GPU
  process restarting): the terrain renderer starts over as the sprite renderer already did,
  instead of leaving the map black.
- Player colours too dark to read on the panels (pure blue above all) are lifted for bars,
  strips, chart lines and swatches.
- The Panels menu and the ⛨ menu stay inside the window, and the chosen layout's name is readable.
- The dashboard makes room at once when the team board switches to its wider Players view; the
  technology and graph slide-outs stop above the time controls instead of covering them.
- The selection panel's five metric labels no longer run into each other.
- A panel's toolbar and resize handles no longer show through an open overlay, and the
  scoreboard's toolbar no longer covers the right team's name.

- A forager that became a builder or farmer before delivering its berries lost the secondary
  (bonus) wood already earned on that load; it now follows the carried berries.

- A completed timeline reopened from the playback index answered the resource and healing review
  queries as if nothing had been observed: those histories are now stored in the index (schema 3).
- The session event stream could end a recording's load without sending its final state.

### Changed

- The Selection panel remembers what you set up, for every later selection and across reloads:
  which sections are open (Details, the group sections, farm grants), the Relevant upgrades list,
  Life or 60s, and where you dragged it and how big you made it. Left at its natural size it holds
  on to a corner, so a taller or shorter panel no longer shifts from where you put it. In Minimal
  and Caster the full panel opened from the chip stays the full panel until you press "compact".
  Customize → Layout has **Reset Selection panel**, and saved layouts carry all of it. Statistics
  reopens on the tab and series last looked at.
- **Statistics is a window**, not a page over the map: no dimming, a title bar that drags, resize
  from every edge and corner, **Dock right** (<kbd>Ctrl+Alt+D</kbd>), a remembered rectangle, and a
  chart that follows its size. Its own playback bar is gone (the main time controls are beside it);
  it remains where Statistics fills the screen, on a phone.
- Placed panels are stored as an anchor and fractions of the window, so a layout survives a resize
  and an OBS source of another size. Pixel rectangles from older versions convert on first use.
- Panels resize from all four edges as well as the corners, the bottom-right grip is visible, and
  the hover toolbar names its panel.
- In a small window (a 720p stream, a 1366x768 laptop) no text is drawn under 12 px. At 1080p and
  up sizes are unchanged.
- Player names are lightened until they reach 4.5:1 on the panels (the game's blue was 4.15:1).
- Farms name their working farmers instead of listing entity ids; a villager group has one row
  per role; armour rows say "Arm"; tooltips no longer show the game's unused armour classes or an
  empty cost slot.
- One name per metric everywhere: Army value (was also "MIL VALUE" and "Military value"), Military,
  Villagers, Idle villagers, Collected, Kills / Losses. The "Team overview" panel is the Team board.
- The **Minimal UI** checkbox picks the Minimal preset (it wrote a setting nothing read).
- Shortcuts work while a button has the focus (it keeps Tab, Enter, Space and plain arrows), and Esc
  closes the top layer from wherever the focus is. With nothing selected, Tab moves the focus into
  the HUD instead of doing nothing (hold-Tab still peeks at the selection owner's fog).
- Selection panel: "Idle for" and "Raid idle" instead of "Idle" beside the clock and "Forced".
  Bonus resources: a player with no bonus income is one line. Composition rows carry a colour bar.
- `vantage serve` and the server take plugins (`cli.main(argv, plugin=...)`,
  `server.App(..., plugins=[...])`): code outside this package can add `serve` options, a
  session class and routes of its own.
- Statistics opens on the whole game for every player. It used to narrow the chart to the last
  minute and two players on every open, and switch the selection panel to its "fight" scope;
  that now happens only when you investigate an interval or click a dashboard value. Totals are
  open below the chart, grid lines sit on round values, and the interval's event list names the
  unit or technology and whose it was.
- The event log shows one "under attack" alert per player per half minute (kings and other
  high-priority alerts always show), in a quieter style, so a raid no longer pushes the kills
  out of view. Its filter buttons no longer outweigh the log.
- The dashboard is one control row (previous, pages, next) over a table that fills the panel.
- The transport and the minimap toolbar use one set of drawn icons instead of Unicode symbols,
  which some systems showed as colour emoji.
- The home screen reopens at once: it shows the lists it last fetched and refreshes them behind,
  so reopening it, switching its tabs and typing in its search box no longer wait for the server.
- "Resources left" is a one-line strip with the game's resource icons, placed above the time
  controls in the Caster layout. Dates in the home lists are short and stay on one line.

- The two-team scoreboard shows a team score total per side (Settings → *Team score*: total,
  average or off; replaces *Team average score*) with the score share and lead under the clock.
  Team names are shortened, and players with a teammate's name are labelled by civilisation.
  The balance bars moved into the team board. Only alliances across lobby teams are listed.

- The review workspace, with player, combat, healing and resource reviews, review moments, panel
  resizing, camera follow and Autocast focus, and the DOM patcher for HUD panels.
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
