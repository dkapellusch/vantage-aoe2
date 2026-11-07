# Architecture

Vantage has two halves:

- a **Python server** (`src/vantage/`). It reads the game's spectator stream, keeps the match as a seekable history, and serves JSON and game assets over HTTP. It uses the standard library throughout, except for `grpcio` and `protobuf`, which talk to the game.
- a **browser interface** (`src/vantage/web/`). It is plain JavaScript modules with no build step. The browser owns the playback clock, asks the server for the state of the match at the moment it wants to show, and draws it.

The game's stream format is documented separately in [wire-format.md](wire-format.md).

## Data flow

```
 AoE2 DE ── gRPC, mutual TLS, 127.0.0.1:4341 ──► live.LiveGame ──┐
   (CadeRemote: Frames, Oracle, LoadGame, …)                     │
                                                                 ├──► frames.Frame ──► timeline.Timeline ──► server.App ──HTTP/SSE──► web/
 match.vrec ──────────────► frames.read_frames ──────────────────┘          │                 │                  │
                                                                     patch.Patcher        world.view()      gamedata, sprites,
       live frames are also written ──► frames.RecordingWriter ──► .vrec    (state tree)    (JSON per second)  sld/smx, audio, skins
```

1. **Frames in.** A live session opens a gRPC `Frames` stream on the game. Each message is converted to a `frames.Frame`, which holds the game time, a forward patch, a reverse patch, the frame's events and its player commands. A recording yields the same `Frame` objects from disk. Everything after this step cannot tell the two apart.
2. **State.** `patch.Patcher` applies each frame's patch to a typed object tree, the whole game world as the game describes it. A frame whose patch begins with a "create root" instruction is a **snapshot** and rebuilds the tree from nothing. Every new stream starts with one.
3. **History.** `timeline.Timeline` reads the tree after each frame. It keeps keyframes, time series, events and per-entity logs (see [below](#keyframes-and-seeking)).
4. **Serving.** `server.App` answers the browser's requests from the timeline, and converts the game's own icons, sprites, terrain and sounds from the installed game on demand.
5. **Drawing.** The browser fetches the keyframe at or before the moment it shows and the one after it, interpolates between them, and draws the world and the HUD.

While a live session runs, every frame is also appended to a `.vrec` (unless recording is off), so the session can be replayed later without the game.

## Sessions and threads

`server.Session` is the one thing being watched. Its `mode` is `idle`, `live` or `recording`. Opening a new source replaces the current timeline and increments `generation`, which tells the browser to start over.

- **Recording**: one loader thread reads the file and feeds the timeline. The browser can start watching while it loads.
- **Live**: a stream thread connects to the game, sends any load, join or switch request, then consumes `Frames`. If the stream breaks, it reconnects every 3 s, and the new stream's opening snapshot resynchronises the tree. A snapshot that repeats the state already held (byte for byte, at the same game time, with no patch since: a paused or ended game answers every reconnect so) is neither applied again nor written to the recording. Once the game is over, reconnects back off, doubling up to 60 s while the streams bring nothing new. If the first connection fails, the session names the likely cause: certificate files missing (status `needs_certs`), the game answering but refusing TLS, or nothing listening on the port. Two more threads run alongside it:
  - an **Oracle** thread on a second connection carries pause state (and who paused), the screen, lobby information, game state and chat sent while paused.
  - a watchdog flags a stalled stream as "waiting for players".

  Controls (pause, speed, fog, perspective, window state) go over the current connection, or over a short-lived one between streams. The game serves only one stream per connection, so each of these uses a connection of its own.
- **Fast replay**: when the game is set to FAST or EXTRA_FAST, the stream is reopened with a lighter profile (`server.LIGHT_STREAM_*`): 500 ms frames, low-priority and sleeping units every 2 s, and only particle effects that show game state.
- Request handling uses `ThreadingHTTPServer`. View, terrain, forest, event and time-series reads do not take the timeline's lock, and the unit and group panels decode their keyframe outside it. `/api/stream` sends a new timeline version at most four times a second (the latest state, coalesced); other session changes go out at once. The interpreter's thread switch interval is shortened while serving, so requests stay responsive while a large recording is being ingested.
- Sprite strips are decoded in a pool of worker processes (`VANTAGE_SPRITE_WORKERS`).

## Keyframes and seeking

The game streams forward patches only. In practice it sends no reverse patches, although the decoder supports them. History is therefore kept as **snapshots of the view**, not as patches to undo.

`Timeline.feed(frame)` applies the patch and then, as the frame's time requires:

| Data | Interval | Stored as |
|---|---|---|
| **Keyframe**: `world.view()`, everything the interface draws at one moment (entities with position, facing, sprite and state; players' economy, army, research and production; projectiles; remains) | every 1 s of game time (2 s in a live session that cannot keep up, back to 1 s when it can) | zlib-compressed JSON |
| Fog of war (per-player visibility and exploration bits) | with each keyframe | compressed bytes |
| Forest layer | every 3 s, when changed | compressed tiles |
| Terrain under farms and buildings | every 3 s, when changed | compressed tiles |
| Unit tracks and projectile tracks | every 100 ms between keyframes, for units that moved | compressed JSON per keyframe |
| Time series (economy, army, kills, exploration, APM, …) | every 5 s | arrays per player |
| Event log (kills, research, age-ups, chat, tribute, market, conversions, diplomacy, king and wonder alerts, countdowns) | as they happen | list |
| Per-entity logs (activity, damage, kills, conversions) and per-player master statistics | as they change | for the unit panel at any moment |

**Seeking is a lookup.** `Timeline.view_at(t)` binary-searches for the keyframe at or before `t`. It decompresses that keyframe and attaches the fog, the forest and terrain snapshot times, and the movement tracks that follow. Seek, skip, rewind, bookmarks and reverse playback are all the same request: `GET /api/view?t=…`. The server answers it with `Timeline.view_json(t)`, which splices the stored JSON text instead of parsing and re-encoding it (the same document byte for byte). A keyframe is **final** once the next one exists (or the timeline is complete): its tracks can no longer grow. The newest keyframe of a live game is not, and its view says `"final": false`. The last 64 final responses are kept per timeline.

**The browser interpolates.** Between two keyframes, units follow their 100 ms tracks and face along their path, and animations advance. At higher speeds the browser fetches several views ahead (more at 8×) and asks for their sprites early. With *Wait for graphics* on, it holds briefly at a keyframe until every sprite it is about to draw has loaded. Reverse playback fetches earlier keyframes the same way. View requests are cached by exact time, because two requests within one second can fall either side of a keyframe; a view marked `"final": false` is asked for again after a second, and replaces the one held for that time.

**Keeping the browser responsive.**

- *Requests.* Views are fetched and parsed in a worker (`view-worker.js`) with high priority, and statistics, events and unit details with low priority. Sprite strips come from the server's other loopback name (`localhost` for a page on `127.0.0.1`, and the other way round) when the server answers it with CORS, so they have their own six HTTP/1.1 connections. Asset URLs carry the server's `asset_version` (`av=`), so the browser keeps them for good.
- *Session updates.* Updates from `/api/stream` are applied one at a time, always the newest (a hidden tab applies only the newest when shown again). Events arrive by time range, and the time series with `/api/series?from=` since its newest row.
- *Seeking.* A seek keeps drawing the current view until the new one arrives. It cancels the view requests of the seek before the previous one. Dragging the time bar seeks at most every 80 ms, asks for views on the 1 s request grid, and does no look-ahead until it is released.
- *Sprites on the GPU* (`sprite-gl.js`). The atlas starts at eight 2048² layers (128 MB). It doubles, copying its layers on the GPU, up to the *Sprite memory* setting, at most 1 GB, before it evicts anything. A lost WebGL context halves that limit for the session. A frame uploads at most 8 M texels: past that, a strip shows one of its frames already in the atlas until the next frame.
- *Per-frame work.*
  - The minimap is three cached layers: the ground, redrawn when the terrain or the minimap view changes; the fog; and the entities, redrawn at most 15 times a second (in the same order as before). Only the camera frame is drawn every frame.
  - The fog image and its canvases are reused, and each view's fog is decoded once.
  - The event log appends new rows and drops old ones (`dom.js` `listDelta`) instead of rebuilding its 150 rows.
  - Sprite requirements per view are keyed on a coarse camera grid.
  - Painter's-order sorting computes each depth once (`playback.js` `sortByKey`).
  - Sound, Autocast and hero bookkeeping look up events by time (`eventIndexAfter`) instead of scanning the whole log.
  - With GPU sprites, no distance haze, nothing selected and no spy fog, the colour grade is baked into a copy of the cached ground: it is redone when the ground repaints, not every frame. The picture is the same.

**Errors.** If a patch fails to apply, the timeline counts an error and ignores frames until the next snapshot. A live stream resynchronises on reconnect, and a recording carries on from its next snapshot if it has one. A recording that holds the same snapshot many times over (a live session left open on an ended game wrote those) loads each repeat as a no-op.

## The `.vrec` recording format

A `.vrec` file is a single gzip stream. All integers are little-endian `u32`.

```
"VREC" 0x01                       magic and format version 1
u32 header_len, header_json       {"version": 1, "created": <unix time>, "source": "live",
                                   "replay": <path or null>, "game_version": <build>,
                                   "game_mode": null | "Pompeii"}
repeat until end of file:
  u32 time                        game time of the frame, ms
  u32 skipped                     time steps the game skipped before this frame
  u32 len, patch                  the forward patch (see wire-format.md)
  u32 len, reverse_patch          usually empty
  u32 len, events_json            the frame's game events as a JSON list (length 0 when none)
  u32 len, commands_json          the frame's player commands as a JSON list (length 0 when none)
```

- Frames are appended as they arrive. A file whose writer was interrupted reads correctly up to its last complete frame.
- A recording always begins with a snapshot frame.
- Events and commands are stored as JSON objects `{"kind": <oneof name>, ...fields}`, using the protobuf field names. A message shape Vantage does not know is stored as `{"kind": "raw", "b64": ...}` so nothing is lost.
- `game_mode` is `"Pompeii"` for Return of Rome, so playback reads that mode's names and graphics.

`frames.RecordingWriter` and `frames.read_frames` are the reference implementation.

## Game data

Nothing from the game is redistributed. `gamedata.GameData` reads from the installed game at run time:

- **strings**, in every language the game ships, for unit, technology and civilisation names.
- **civilisation data and tech trees**.
- **palettes, icons and terrain textures** (DDS, including BC7). These are converted to PNG and cached.
- **sprites** (SLD and the older SMX format). These are decoded to per-facing animation strips with the player colour applied, or with the player-colour mask beside them so the GPU can colour them.
- **particle definitions and atlases**, and **colour grades** (`terrain/colorcorrection_json`).
- **sounds**, from the game's Wwise packages (decoded with the external `vgmstream-cli`).

Return of Rome reads `modes/Pompeii` first and falls back to the base game. The two games reuse ids for different things, so caches are keyed by game. Converted assets are cached in `$XDG_CACHE_HOME/vantage` (`~/.cache/vantage`) on Linux and `%LOCALAPPDATA%\Vantage\cache` on Windows. Cache files are written to a temporary file and renamed into place, and concurrent requests for one sprite strip, icon, terrain texture or particle atlas convert it once (`assetcache.py`). With mods enabled, the mod folders are scanned at most every 5 s, and at once when the mod settings change.

The game install is found from `$VANTAGE_GAME_DIR`, the folder the running game reports, or the Steam libraries listed in `libraryfolders.vdf`. On Windows, Steam's own folder comes from its registry keys. On Linux, replay folders are found in each library's Proton prefix for the game (`steamapps/compatdata/813780`). On Windows they are in `%USERPROFILE%\Games\Age of Empires 2 DE`. In both cases the profile the live game reports is added. Under Proton, `gamedata.host_path` and `gamedata.windows_path` translate between the Windows paths the game uses (`C:\` is the prefix's `drive_c`, `Z:\` the host root) and host paths. On Windows they leave paths unchanged.

## Module map

### Python (`src/vantage/`)

| Module | Role |
|---|---|
| `cli.py` | The `vantage` command: `serve`, `record`, `info`, `open-url`, `register-handler`, `doctor`; parsing of spectate links; link handlers (xdg on Linux, per-user registry keys on Windows) |
| `server.py` | `Session` (live or recording source, recording, live controls) and `App` (the HTTP and SSE routes) |
| `live.py` | `LiveGame`: the client for the game's `CadeRemote` gRPC service (info, frames, Oracle, load, join, pause, speed, fog, perspective, window) |
| `certs.py` | Where the client certificate files are looked for, which are missing; gRPC TLS credentials |
| `paths.py` | Per-user folders by operating system (configuration, data) |
| `doctor.py` | `vantage doctor`: the environment checklist |
| `rpc/cade.proto`, `rpc/cade_pb2.py` | The service's message definitions, and the generated Python code (regenerate, never edit) |
| `frames.py` | `Frame`; the `.vrec` reader and writer |
| `schema.py`, `cade_schema.json` | The state-tree schema: 51 models and 1,349 fields with their ids, names, wire types and container kinds |
| `patch.py` | `Patcher`: the stack-machine interpreter that applies patches to the state tree |
| `world.py` | Named reading of the tree: players, economy, army, buildings, research, map layers; builds the per-moment `view()` and aggregates |
| `timeline.py` | Keyframes, time series, events, APM and effective APM, per-entity logs, summaries; `view_at(t)` |
| `gamedata.py` | Locating the install and profiles; strings, civilisations, tech trees, palettes, icons, terrain, particles from the game files |
| `sld.py`, `smx.py` | Decoders for the game's SLD and SMX sprite formats |
| `bc7.py` | BC7 texture block decoder (pure Python) |
| `sprites.py` | `SpriteStore`: sprite strips per (sprite, facing, player colour), damage level and layer, cached on disk; graphics mods |
| `assetcache.py` | One conversion per asset at a time (`SingleFlight`); whole-file cache writes (`atomic_write`) |
| `audio.py` | Resolving the game's Wwise sound events to audio files the browser can play |
| `skins.py` | `SkinStore`: skin packages (`skin.json` in a folder or `.zip`), merging and live reload |
| `launcher.py` | `GameLauncher`: starting the game through Steam and tracking its status |
| `combat_review.py`, `healing_review.py`, `resource_review.py`, `economy_benefits.py`, `review_moments.py` | The review panels' per-entity and per-player histories (military pressure, healing, resource income and bonuses), and saved review moments |

### Local replay playback (experimental)

Ported from the development copy: a replay converted on this machine, without the running game, with a pinned conversion profile (`vantage serve --native-replay FILE --native-profile … --native-profile-sha256 … --native-cache-dir …`, or `vantage-native.py` / `vantage-v32.py` at the repository root). `NativeSession` (`native_session.py`) replaces `Session` in `cli.py`. With no native option given it behaves exactly as `Session`.

| Modules | Role |
|---|---|
| `native_session.py`, `native_jobs.py` | The session and job coordinator: one conversion at a time, cancellable, then the recording opens as usual |
| `native_conversion.py`, `native_isolated.py`, `native_isolated_launch.py` | The converter (pinned inputs, a private Wine prefix, a Bubblewrap sandbox) and the isolated launcher `vantage-native.py` runs |
| `native_engine_*.py`, `native_v32_*.py`, `native_bootstrap_*.py`, `native_sdk_admission.py` | Engine packages and registry, the V32 backend and its pipeline, and the admission checks of a conversion's result |
| `native_input.py`, `native_player_attributes.py`, `native_compare.py`, `native_reference_*.py`, `native_corpus.py`, `native_update_workflow.py` | Research instruments: replay input decoding, attribute capture, comparison against reference recordings, corpus runs |
| `replay_*.py` | A reimplementation of the game's replay simulation, checked against research captures |
| `playback_index.py`, `playback_data.py`, `chat_playback.py`, `recorded_chat.py` | A completed timeline cached on disk (it reopens without replaying frames), and recorded chat |

The conversion's renderer and encoder are pinned research scripts that import the development copy's modules. They run in the repository holding the profile's or encoder's `artifacts/` folder (`native_conversion.profile_repository`, `native_v32_encode.research_repository`), so the code they were pinned with is the code they run. A replay, a profile or a cache under `/tmp` is not visible inside the conversion sandbox, which mounts a private `/tmp`.

These modules are type-checked in strict mode like the rest of the package, though many of their signatures use `Any` because they handle untyped JSON from native captures. Some of their tests read research captures from `artifacts/game-internals/` (the development copy's folder, linked as `artifacts/` and not committed); without it those tests are skipped (`tests/conftest.py`).

### Browser (`src/vantage/web/`)

| File | Role |
|---|---|
| `index.html`, `style.css`, `shell.css`, `hud.css`, `overlays.css`, `world.css` | Page structure and styles |
| `app.js` | Boot, the playback clock, data refresh, actions bound to keys and buttons, the tutorial and built-in documentation, Autocast |
| `state.js` | Shared state, settings (defaults and migrations), the API helper, players, colours and teams |
| `playback.js` | DOM-free playback helpers: the view cache, interpolation, headings, speed stepping |
| `world.js` | Isometric world view, minimap, camera, selection and fog |
| `terrain-gl.js` | The ground as a WebGL height field |
| `sprite-gl.js` | Batched WebGL2 sprite drawing with a texture-array atlas that grows on demand; player colours and outlines on the GPU |
| `graphics-cache.js`, `render-cache.js` | Sprite-readiness tracking and the last complete pose per entity; which map changes invalidate the cached ground, and dirty-rectangle merging |
| `dom.js` | Patching HUD markup in place, and sliding-window list updates |
| `view-worker.js` | Fetching and parsing keyframe views off the main thread |
| `panels.js` | HUD panels: scoreboard, overview, techs, production, dashboard, events, selection panel, resources left, time bar |
| `overlays.js` | Full-screen windows: home screen and replay browser, statistics, settings, quick reference, end of game |
| `layout.js` | The Panels menu: hiding and collapsing HUD panels |
| `hotkeys.js` | The default key table, rebinding and conflict detection |
| `audio.js` | Game sound playback as playback passes events |
| `games.js` | Per-game rules for Age of Empires II and Return of Rome |
| `i18n.js`, `i18n/*.json` | Interface translations |

## HTTP API

The server listens on `127.0.0.1:8740` by default. It has **no authentication**: it is meant for the local machine. JSON responses are uncached. Assets converted from the game are cached by the browser for a day (`max-age=86400`), or for good (`max-age=31536000, immutable`) when the URL carries `av=` with the current `asset_version` from `/api/config`. That version changes with Vantage, its sprite renderer, the installed build, the game mode and the mod folders in use, so such a URL never changes content. A POST with a bad body answers `400` with `{"ok": false, "error": "..."}`. A missing asset answers `404` with a short body on the same kept-alive connection.

The page may load sprites from the other loopback name (`localhost` for a page on `127.0.0.1`, and the other way round) for a second pool of browser connections. Sprite responses (`/sprite/…`, errors included) and `/api/config` answer a request whose `Origin` is `http://127.0.0.1:<port>`, `http://localhost:<port>` or `http://[::1]:<port>` of this server with `Access-Control-Allow-Origin: <that origin>` and `Access-Control-Expose-Headers: X-Sprite-Meta`; any other origin gets no CORS headers. Both send `Vary: Origin`. The server does not check the `Host` header, so either name reaches it.

### Session and data

| Request | Returns |
|---|---|
| `GET /api/session` | The session: `mode` (`idle`, `live`, `recording`), `source` (status, lobby, replay, recording path, pause state, …), `error`, `generation`, `live_connected`, `game` (`aoe2` or `ror`), `timeline` status, `installed_build`, `game_dir`, and `certs` (the certificate folder and the files missing from it). With `?probe=1` it also reports `game_api_open`, whether anything answers on the game's port |
| `GET /api/stream` | **Server-sent events.** A `data:` line with the session description whenever the source, the timeline or the connection changes (timeline progress alone at most every 250 ms). `event: skins` when skin files change. Keep-alive comments otherwise |
| `GET /api/match` | Static match information: players, teams, civilisations, map, game settings |
| `GET /api/map` | Map size and tiles |
| `GET /api/catalog?lang=` | Unit, technology and civilisation names and icons in a language, and colour-grade names |
| `GET /api/view?t=` | The keyframe at or before game time `t` (ms), with fog and movement tracks. Without `t`, the latest. `"final": false` while the keyframe is the newest of a timeline still growing: its tracks may grow, so ask again later (the key is absent otherwise) |
| `GET /api/unit/<id>?t=` | One entity's statistics and logs at `t` |
| `GET /api/group?ids=&t=` | Combined statistics for up to 600 entities |
| `GET /api/techtree/<civ>?lang=` | A civilisation's tech tree, with costs |
| `GET /api/trees?t=`, `GET /api/terrain?t=` | Forest and terrain tiles in force at `t` (base64) |
| `GET /api/events?from=&to=` | Events between two game times |
| `GET /api/series?from=` | Time series per player, `{pid: [rows…]}`. With `from` (ms), only rows with `t >= from`, every player still listed: a browser drops its own rows from `from` on and appends these |
| `GET /api/summary?t=` | Per-player summary (final, or at `t`) |
| `GET /stats-dump` | Everything the statistics screens use, as one document |
| `GET /api/recordings`, `GET /api/replays` | The recordings folder with headers; the replay browser's list with parsed headers |
| `GET /api/bookmarks` | Bookmarks of the current recording |
| `GET /api/config` | Settings forced by `--patch-config` and `--force-default-config`, Vantage's version, and `asset_version` (see above). Allowed from the paired loopback origin |
| `GET /api/profiles`, `GET /api/profile/<name>` | Saved settings profiles |
| `GET /api/launch_game` | Game launcher status |
| `GET /api/mods`, `GET /api/skins`, `GET /api/skins/merged?enabled=`, `GET /api/skins/version`, `GET /api/images`, `GET /api/particles` | Mod state, skins, custom images, particle definitions |
| `GET /sse` | Server-sent events for skin live reload (`event: skins`) |

### Actions

| Request | Body | Does |
|---|---|---|
| `POST /api/open` | `{path}` | Open a `.vrec` |
| `POST /api/live` | `{host, port, replay, lobby, record, game, confirm, cloud, source}` | Connect to the game. Optionally load a replay, join a lobby or switch game. Returns `needs_confirm` when the game would leave a game in progress; resend with `confirm: true` once the user agrees. Returns `needs_certs` when the certificate files are missing |
| `POST /api/play_replay` | `{name, dir, record, confirm}` | Play a replay from the replay browser |
| `POST /api/open_url` | `{url}` | Handle a `vantage://` or `captureage://` link or a `.vrec` path (used by `vantage open-url`) |
| `POST /api/control` | `{action, value}` | Live control: `pause` (bool), `speed` (`SLOW`, `NORMAL`, `FAST`, `EXTRA_FAST`), `fog` (bool), `perspective` (player number), `window` (`MINIMIZED`, …) |
| `POST /api/record` | `{on}` | Start or stop recording a live session |
| `POST /api/stop` | | Stop watching |
| `POST /api/bookmarks` | `{bookmarks}` | Save the current recording's bookmarks |
| `POST /api/game_dir` | `{path}` | Use another game install |
| `POST /api/mods` | `{graphics, sprites, terrain, dirs}` | Which mod content to read, and extra mod folders |
| `POST /api/profile` | `{name, settings}` | Save a settings profile |
| `POST /api/skins/add`, `POST /api/skins/remove` | `{path, kind}`, `{name}` | Register or forget a skin |
| `POST /api/launch_game` | | Start the game through Steam |
| `POST /api/open_folder` | `{which}` | Show the `recordings`, `profile`, `images` or `skins` folder in the file manager |
| `POST /api/playback_ended` | | The browser reached the end of a recording (for `--exit-on-stream-end`) |

### Assets

| Request | Returns |
|---|---|
| `GET /`, `GET /static/<file>` | The interface |
| `GET /icon/{unit,building,tech}/<id>.png` | A game icon |
| `GET /emblem/<civ>.png` | A civilisation emblem |
| `GET /sprite/<sprite>/<facing>/<colour>.png` | A sprite's animation strip for one facing. The layout comes in the `X-Sprite-Meta` header, also available as `.json`. Query options: `hd=1` (UHD graphics), `dmg=` (damage level), `layer=` (`main` or `shadow`), `pm=1` (uncoloured strip plus player mask), `dir=1` (unit facing convention), `av=` (asset version: cached for good). Allowed from the paired loopback origin |
| `GET /terrain/<name>.png`, `GET /terrain-mask/<name>.png` | Terrain textures and blend masks |
| `GET /particle_atlas.{png,json}?path=` | A particle atlas and its layout |
| `GET /ui/<name>.png`, `GET /ui/material/<name>.png` | The game's HUD art (age icons and so on) |
| `GET /audio/{event,taunt,notify}/<id>.ogg?v=&lang=` | A sound, one variant of an event |
| `GET /images/<file>` | A custom casting image |
| `GET /skins/<name>/<file>` | A file from a skin |
