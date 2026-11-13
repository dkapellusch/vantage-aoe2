# Development

## Setup

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), and (for the browser tests) Node.js 22 or newer.

```sh
git clone https://github.com/dkapellusch/vantage-aoe2
cd vantage
uv sync                      # creates .venv with Vantage and the dev tools
npm ci --ignore-scripts       # pinned browser lint tools (development only)
uv run vantage serve --open
```

The browser code in `src/vantage/web/` is plain JavaScript modules served as they are. There is no bundler and no build step:

- After changing **JavaScript or CSS**, reload the browser tab.
- After changing **Python**, restart `vantage serve`.

You do not need the game to work on most of Vantage. Any `.vrec` recording exercises the whole pipeline except the live connection. Set `VANTAGE_NO_LAUNCH=1` while developing so that "Start Age II" can never start the game by accident.

## Tests

```sh
uv run pytest                # everything (Python, plus the browser tests if Node is installed)
uv run pytest tests/test_patch.py -q
node --test tests/*.test.mjs # the browser tests, including the no-undef gate
npm run lint:web            # no-undef only, all src/vantage/web/*.js modules
```

- The tests are **offline and deterministic**. They need neither the game, nor the certificates, nor a network.
- There is one test file per module: `tests/test_<module>.py`.
- `tests/helpers.py` has a patch **encoder** that builds exact forward and reverse streams, and a small synthetic match.
- `tests/fixtures/` holds captured stream frames and replay headers (compressed). These are recorded game data, not game assets.
- Live mode is tested against an in-process fake gRPC server. SLD, SMX and DDS decoding is tested with synthetic files. Windows-only code paths (registry, link handlers) are tested with fakes, so the suite also runs on Linux.
- `tests/test_web.py` runs the DOM-free browser tests (`tests/*.test.mjs`) with Node's built-in test runner. It is skipped if `node` is not on your `PATH`. These tests cover playback timing, interpolation, the view cache, ground-cache invalidation, sprite readiness and GPU atlas packing.

- `tests/test_hud_browser.py` drives the customizable HUD in headless Chromium (presets and their keys, the Customize drawer, the share link, the Statistics window, the layout editor, saved layouts, the phone layout, focus and text sizes). It needs [Playwright](https://playwright.dev/python/), which is not a dependency of Vantage, and is skipped without it:

  ```sh
  uv run --with playwright python -m playwright install chromium   # once
  uv run --with playwright pytest tests/test_hud_browser.py
  ```

- The zoomed game-art cases in `tests/test_hud_browser.py` use generated sprite strips
  and exercise both Canvas and WebGL at base zoom. They require completed frames,
  actual entity sprite draws and no page errors; a zero missing-sprite counter
  alone cannot pass. CI runs these cases with Chromium, independently of the
  optional local Playwright installation.
- `test_zoomed_game_art_big_scene_stays_within_frame_budgets` (same file) draws 3,000
  generated rows with game art, zoomed in and zoomed out, and checks that the zoomed-in
  frame draws only its own part and fits a frame-time budget, that a still picture
  uploads and fetches nothing, and that no HUD task is long. The budgets are eight to
  ten times what a development machine measures: they catch an all-rows pass that is
  no longer culled, not a slow runner.
- `tests/no_undef.test.mjs` runs ESLint's `no-undef` rule on every top-level browser
  module, including workers. Browser and worker globals are listed by the pinned
  `globals` package in `eslint.config.mjs`. Both Node and pytest run this gate.

All tests must pass before a change is merged. CI runs them on Linux and Windows. Tests of
Linux-only behaviour (Proton paths, the freedesktop link handler) pin `sys.platform` or are skipped on
Windows, so the suite passes on both.

### Running the suite on Windows Python from Linux

Without a Windows machine you can still run the tests on Windows' Python under Wine. Use a scratch Wine
prefix so your main one is untouched:

```sh
uv python list --all-platforms --output-format json   # find the cpython-3.12 windows-x86_64 download URL
curl -L -o py.tar.gz '<that url>' && tar -xzf py.tar.gz              # unpacks python/python.exe
uv pip install --python-platform x86_64-pc-windows-msvc --python-version 3.12 \
    --target winsite grpcio protobuf genieutils-py==0.1.2 pytest
export WINEPREFIX="$PWD/wineprefix"
PYTHONPATH="Z:$PWD/winsite;Z:$PWD/src;Z:$PWD" wine python/python.exe -m pytest -q -p no:cacheprovider
```

(Write the `Z:` paths with backslashes if your shell keeps the forward slashes; Wine maps `Z:` to `/`.)

## Performance

`tools/perf/` measures playback, panning, zooming and seeking in a real browser against a
served recording: frame times, long tasks, the HUD's tasks, sprite fetches and uploads,
memory, and the time to a complete picture after a seek or a camera jump. It also takes
CPU profiles and browser traces of a scenario, and compares screenshots at fixed moments
before and after a change. [tools/perf/README.md](../tools/perf/README.md) has the commands.
Measure on a real GPU (`--gpu vulkan`; every result records the renderer): software WebGL
says little about time spent in WebGL and canvas calls. Include a zoomed-in view of game
art and a zoomed-out one, over a late team game: they have different hot spots.

## Lint and type check

```sh
uv run ruff check .
uv run mypy
```

Both must be clean. mypy runs in strict mode over `src/vantage`, and ruff uses a line length of 100 (see `pyproject.toml`). The generated `rpc/cade_pb2.py` is excluded from both. Do not add `# type: ignore` without a comment explaining why.

## Project layout

```
src/vantage/
  cli.py            the vantage command
  doctor.py         vantage doctor
  server.py         session and HTTP/SSE routes
  live.py           gRPC client for the game
  certs.py          certificate lookup
  paths.py          per-user folders by operating system
  rpc/              cade.proto and the generated cade_pb2.py
  frames.py         Frame and the .vrec format
  schema.py         loads cade_schema.json (the state-tree schema)
  patch.py          the patch interpreter
  world.py          named view of the state tree
  timeline.py       keyframes, series, events
  gamedata.py       reading the installed game
  sld.py smx.py bc7.py sprites.py audio.py skins.py launcher.py
  web/              the browser interface (no build step)
    i18n/           translations
tests/              pytest tests, Node tests, fixtures
docs/               architecture, wire format, this guide
docs/wiki/          the user guide (published to the GitHub wiki)
```

[architecture.md](architecture.md) has a one-line description of every module, and [wire-format.md](wire-format.md) describes the game's stream.

## Ground rules

- **Runtime dependencies stay minimal.** `grpcio` and `protobuf` serve the game connection; pinned `genieutils-py==0.1.2` reads installed game effects for upgrade relevance. See [third-party license notes](../THIRD_PARTY.md). Other runtime code uses the Python standard library. Development-only tools go in the `dev` dependency group.
- **No game assets in the repository.** Graphics, sounds and strings are read from the user's installation at run time. Test fixtures must be synthetic or recorded stream data, never files copied from the game.
- **No certificates in the repository**, nor in issues, logs or test fixtures.
- **Your own work.** Do not copy code or assets from other software unless its licence allows it. Facts about the game's wire format belong in `cade_schema.json`, `rpc/cade.proto` and [wire-format.md](wire-format.md).
- **Every module ships with focused tests.**

## Regenerating `rpc/cade_pb2.py`

`src/vantage/rpc/cade.proto` is the source. `cade_pb2.py` is generated from it and is committed so that users do not need the protobuf compiler. After changing the `.proto`, regenerate it with `grpcio-tools` (in the dev group):

```sh
uv run python -m grpc_tools.protoc \
  -I src/vantage/rpc \
  --python_out=src/vantage/rpc \
  src/vantage/rpc/cade.proto
```

Never edit `cade_pb2.py` by hand. Vantage calls methods by their wire path, so no `_grpc` stub module is needed.

The generated file checks the protobuf runtime version when it is imported, against the version noted in its header (`# Protobuf Python Version: …`). If the `grpcio-tools` you generate with is newer than the `protobuf` floor in `pyproject.toml`, raise that floor to match.

## Adding a translation string

1. Write the English text in the code inside `t()`, imported from `./i18n.js`:

   ```js
   toast(t('Recording started'));
   toast(t('Saved to {path}', { path }));
   ```

   For static HTML, give the element a `title` or a `data-i18n` attribute holding the English text. `translateStatic()` translates both.

2. Add the English text to the source catalogue: one of `src/vantage/web/i18n/_source*.json` (JSON lists of strings).
3. Add the translation to every `src/vantage/web/i18n/<code>.json`. Until you do, that language shows the English text.
4. Check the result: switch the interface language, use the feature, and look at `[...window.__i18nMisses]` in the browser console. It should not list your string.

Game names (units, technologies, civilisations) never go through `t()`. They come from the game's string tables through `/api/catalog?lang=`. See the [Translations](wiki/Translations.md) page for the translator's view.

## Adding a setting

1. Add the key and its default to `DEFAULT_SETTINGS` in `web/state.js`. Saved settings are merged over the defaults, so existing users pick up the new key.
2. If an existing default changes meaning, add a step to `migrateSettings()` and bump `settingsVersion`.
3. Add a control to the right tab in `web/overlays.js` (`chk`, `rng`, `sel`, `numIn`, `txt`), with a translated label.
4. Document it in [wiki/Settings.md](wiki/Settings.md).

## Adding a hotkey

Add an entry to `KEYMAP` in `web/hotkeys.js` (`action: [defaultKeys, 'Description']`), handle the action in `web/app.js`, translate the description, and add it to [wiki/Hotkeys.md](wiki/Hotkeys.md). Check for conflicts with `hotkeyConflicts({})`.

## The wiki

`docs/wiki/` is the source of the GitHub wiki. File names are page names. Pages link to each other as `[Text](Page-Name.md)` so they also work when browsing the folder on GitHub; `scripts/publish-wiki.sh` rewrites those links to wiki form and pushes to the wiki repository. GitHub creates the wiki repository only after its first page is saved in the web UI, so create any page once before the first publish. `_Sidebar.md` and `_Footer.md` are the wiki's sidebar and footer.

## Release checklist

1. Make sure `main` is green: `uv run pytest`, `uv run ruff check .`, `uv run mypy`.
2. Smoke-test by hand:
   - a recording (`vantage serve --open some.vrec`): seek, reverse, statistics, end-game screen,
   - if you can, a live game and a replay,
   - `vantage doctor`, `vantage info`, `vantage --version`.
3. Bump the version in **both** `pyproject.toml` (`version`) and `src/vantage/__init__.py` (`__version__`).
4. Update `CHANGELOG.md` (create it for the first release; the source distribution includes it).
5. Build and inspect the packages:

   ```sh
   uv build
   unzip -l dist/aoe2_vantage-*.whl | grep -E 'web/index.html|cade_schema.json|i18n/de.json|rpc/cade_pb2.py'
   ```

   The wheel must contain the web interface, the schema, the translations and the generated protobuf module.
6. Test the install in a clean environment:

   ```sh
   uv tool install --force dist/aoe2_vantage-*.whl
   vantage --version
   ```

7. Commit, tag `vX.Y.Z`, and push the tag. Users install from the repository: `uv tool install git+https://github.com/dkapellusch/vantage-aoe2` (or `@vX.Y.Z` for a specific release).
8. Write the GitHub release notes, and publish any wiki changes.
