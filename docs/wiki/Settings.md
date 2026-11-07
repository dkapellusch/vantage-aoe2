# Settings

Open **Settings** from the ⛨ menu (<kbd>Esc</kbd>) or the Settings button by the minimap. The tabs are **Interface, Dashboard pages, Graphics, Sound, Casting, Skins, Hotkeys, Profiles** and **Help**. Changes apply at once.

The tables below give each control's label, the setting's name (the key you use with `--patch-config` or in an exported settings file), and its default.

## Where settings are stored

- Your settings live **in your browser** (local storage, under `vantage.settings.v1`). They belong to that browser and to the address you open Vantage on. A different browser, or a different `--port`, starts from the defaults.
- **Profiles** are saved by the Vantage server, so any browser can load them (see [below](#profiles-import-and-export)).
- To force settings from the command line, start Vantage with:
  - `--patch-config '{"language": "de", "showElo": false}'`, which applies those settings on every browser that opens Vantage this session, on top of the browser's own.
  - `--force-default-config`, which makes browsers ignore their saved settings this session.

## Interface

### Panels

| Control | Setting | Default |
|---|---|---|
| Static techs panel (Alt+T) | `showStaticTechs` | off |
| Full static techs: every tech line, not just the key ones | `fullStaticTechs` | off |
| Production & composition | `showProduction` | on |
| Dashboard | `showDashboard` | on |
| Mini dashboard: a compact dashboard with fewer columns | `useMiniDashboard` | off |
| Event log | `showEvents` | on |
| Minimal UI | `useMinimalUi` | off |
| Alternative FFA layout: the community scoreboard for free-for-all games | `useCommunityGameSkin` | off |
| Show map info when nothing is selected | `showUnitPanelWhenNothingSelected` | off |
| Keep dead units in selection | `keepDeadInSelection` | on |
| Autocast highlights: replay the most exciting moments automatically | `autocastHighlights` | on |

Which panels are hidden or collapsed from the Panels menu is kept in `hiddenPanels` and `collapsedPanels`. The layout (Panels menu → Layout) is `hudLayout` (`caster`, the default, or `classic`). Moved and resized panels are kept in `panelSizes`, and the team board's view and folded sections in `teamBoardView` and `teamBoardCollapsed`.

### Scoreboard

| Control | Setting | Default |
|---|---|---|
| Show scoreboard | `disableScoreboard` (inverted) | shown |
| Show Elo | `showElo` | on |
| Show ranked Elo in unranked games: use the random-map ladder rating when the lobby is unranked | `showRankedEloForUnrankedGames` | on |
| Hide score | `hideScore` | off |
| Hide score dots: the series dots next to team names | `hideScoreDots` | off |
| Team score: each team's score on the scoreboard, with the lead between them | `teamScore` (`sum`, `average`, `off`) | `sum` |

### Look

| Control | Setting | Default |
|---|---|---|
| Language | `language` | follow the browser (`""`). See [Translations](Translations.md) |
| Look: Default, Classic, High contrast, Clean | `skin` | `default` |
| Show icon name tooltips / Show detailed help tooltips | `tooltipShowMode` | both on (`["iconNames", "detailedHelp"]`) |
| Game directory: the install Vantage reads game data from (must contain `AoE2DE_s.exe`) | `lastUsedGameDirectory` | detect automatically (`""`) |
| Colour scheme (Ctrl+Alt+C): Game colours, Cold vs warm, Warm vs cold | `baseColorMode` | `default` |
| Range circles for buildings: Always, Selected only, None | `rangeCircleModeBuildings` | `always` |
| Range circles for selected units: Always, None | `rangeCircleModeSelectedEntities` | `always` |

The tab also links the OBS overlay page, `/?overlay=1`. See [Casting and OBS](Casting-and-OBS.md).

### Camera

| Control | Setting | Default |
|---|---|---|
| Edge scrolling | `edgeScroll` | on |
| Edge scroll speed (0.25–3) | `edgeScrollSpeed` | 1 |
| Zoom speed (0.25–3) | `zoomSpeed` | 1 |
| Zoom / camera move duration (0–3000 ms; 0 = instant) | `cameraSmoothMs` | 1250 |
| Zoom presets 1, 2, 3 (Alt+1/2/3) | `zoomLevels.one`, `.two`, `.three` | 1.6, 1.0, 0.55 |
| Lock the mouse to the window (Alt+Shift+C): keeps edge scrolling working on several monitors | `clipCursorInGame` | off |

`clipCursorInGame` is off by default in Vantage. In a browser, a pointer lock captures every click until you release it.

### Playback

| Control | Setting | Default |
|---|---|---|
| Disable scrubbing: the time bar no longer seeks when clicked | `disableScrubbing` | off |
| Time controls on the statistics screen | `showStatsTimeControls` | on |
| Close the end-of-game screen: Manually, after 10 s, 30 s, 1 min | `endgameAutoClose` | `"0"` (manually) |
| Minimise Age II automatically while Vantage has focus | `autoMinimizeGame` | on |
| Health bars: Damaged only, Always, Never | `healthBars` | `damaged` |
| Read replays ahead at full speed (see [Replays](Replays.md#fast-replay-and-read-ahead)) | `replayReadAhead` | on |
| Record live games to .vrec | `autoRecord` | off |
| Hide game compatibility warnings | `gameWarningsDismissed` | off |

`autoRecord` only affects sessions started from the browser. `vantage serve --live` records unless you pass `--no-record`.

## Dashboard pages

The dashboard picks a list of pages by game type. For **1v1**, **Team games** and **FFA** you can customise the list: add, delete, reorder and rename pages, choose each page's columns, and choose whether the right-hand team's columns are mirrored. **Other layouts** (Battle Royale, the mini dashboard and Return of Rome) keep their built-in page lists, but you can still change each page's columns. These settings are stored in `customDashboardConfig`, `dashboardColumns`, `dashboardMirror` and `dashboardSelection`.

## Graphics

### Renderer

| Control | Setting | Default |
|---|---|---|
| Game graphics (sprites) when zoomed in | `gameGraphics` | on |
| Enhanced (UHD) graphics | `enhancedGraphics` | off |
| Small trees | `smallTrees` | off |
| Terrain grid intensity (0–100 %; the button resets to the recommended 50 %) | `terrainGrid` | 0 |
| Wait for graphics: hold playback until new units' graphics are loaded | `waitForGraphics` | on |
| GPU rendering: sprites, outlines and terrain with WebGL2; off uses Canvas 2D | `gpuSprites` | on |
| Limit to 60 FPS | `limitToSixtyFps` | off |
| Sprite memory (MB) | `atlasMemoryNormal` | 1536 |
| Sprite memory, UHD graphics (MB) | `atlasMemoryUhd` | 1536 |

### Texture filtering

| Control | Setting | Default |
|---|---|---|
| Smooth unit shadows | `filtering.unitShadow` | off |
| Smooth unit sprites | `filtering.unitColor` | off |
| Smooth damage sprites | `filtering.unitDamage` | off |
| Smooth particles | `filtering.particle` | off |
| Smooth terrain | `filtering.terrain` | off |

### Mods

| Control | Setting | Default |
|---|---|---|
| Enable graphics mods (the mods you have enabled in the game): unit, building and particle sprites | `enableSpriteMods` | off |
| Enable terrain mods (the mods you have enabled in the game) | `enableTerrainMods` | off |
| Extra mod folders: one per line, searched before the game's own files | `modDirectories` | none |

### Picture

| Control | Setting | Default |
|---|---|---|
| Map colour grade: Auto (from the map script) or a named preset | `colorGrade` | `auto` |
| Brightness, Contrast, Saturation, Gamma (0.5–1.6) | `post.brightness`, `post.contrast`, `post.saturation`, `post.gamma` | 1 |
| Red, Green, Blue (0.5–1.5) | `postExtra.red`, `.green`, `.blue` | 1 |
| Opacity (0–1) | `postExtra.alpha` | 1 |

Some maps choose their colour grade at random, so Vantage cannot know which one the game used. For those, the grade you pick is remembered per game (`colorGradeByGame`).

### Bloom and anti-aliasing

| Control | Setting | Default |
|---|---|---|
| Enable bloom | `postExtra.bloomEnable` | off |
| Bloom brightness (0–2) | `postExtra.bloomBrightness` | 1 |
| Bloom threshold (0–1) | `postExtra.bloomThreshold` | 0.9 |
| Bloom blur (0–20) | `postExtra.bloomBlur` | 8 |
| Bloom scale (0.25–2) | `postExtra.bloomScale` | 1 |
| Bloom quality: Low, Medium, High | `postExtra.bloomQuality` | `medium` |
| Anti-aliasing (FXAA) | `postExtra.fxaa` | off |

## Sound

Sound needs `vgmstream-cli` (see [Installation](Installation.md#optional-game-sounds)).

| Control | Setting | Default |
|---|---|---|
| Output volume | `soundOutputVolume` | 1 |
| Events, Units, Combat, Selection, Taunts | `soundVolumes.events`, `.units`, `.combat`, `.selection`, `.taunts` | 1, 0.8, 1, 1, 1 |
| Villager work, Animals, Ambience, Outdoor reverb, Combat impacts | `soundVolumesExtra.villagers`, `.critters`, `.ambience`, `.reverb`, `.combatImpacts` | 1, 1, 0.5, 0, 1 |
| Units trained, Research done, Under attack, Conversions: All players, Current player, None | `soundEventConfig.train`, `.research`, `.attack`, `.conversion` | Current player (`selectedPlayer`) |
| Chat event sounds: None, Sound only, Sound and taunt | `chatEventSoundOption` | `chatAlertAndTaunt` (sound and taunt) |
| Taunt language | `tauntLanguage` | same as the interface (`""`) |

## Casting

Names, flags, the series and panel positions are described in [Casting and OBS](Casting-and-OBS.md).

## Skins

A **skin** changes Vantage's look with your own CSS and images. **Settings → Skins** lists the skins Vantage has found:

- every sub-folder or `.zip` in the `skins` folder of Vantage's data directory (**Open skins folder** opens it), and
- any folder or `.zip` you add by path with **Add a skin**.

You can enable several skins at once (`enabledSkins`). Their options combine, and later skins override earlier ones. **Use the default look** turns them all off. Enabled skins reload by themselves when their files change.

A skin is a folder or `.zip` with a `skin.json` manifest:

```json
{
  "name": "My league",
  "options": { "showSkinLogo": true },
  "stylesheets": ["skin.css"],
  "assets": { "logo": "logo.png" }
}
```

`stylesheets` are loaded after Vantage's own CSS. `assets` replaces Vantage's images by key (for example `logo`, or the dashboard column icons `colWorkersFood` and friends). The tab's **Active skin options** section shows what the enabled skins set.

**Enable HTTP Server for skin debugging** (`toggleHTMLServer`, off): Vantage already runs in a browser, so this reloads skin stylesheets in every open tab as soon as a skin file changes, and adds **Open webpage** to the ⛨ menu, which opens Vantage in a new tab where you can use the browser's developer tools on your skin. The statistics are always available as one JSON document at `/stats-dump`.

## Hotkeys

See [Hotkeys](Hotkeys.md#changing-keys). Custom bindings are stored in `customHotkeys`.

## Profiles, import and export

- **Save as profile** stores all your settings on the Vantage server under a name. Names can use letters, digits, spaces, `-` and `_`, up to 40 characters. They are saved in `profiles/<name>.json` in Vantage's data directory.
- **Load** applies a saved profile, in this or any other browser.
- **Export to file** downloads `vantage-settings.json`. **Import from file** loads one, for example on another computer.
- **Reset all settings** returns every setting, hotkey and casting override to its default.

Replay filters, casting overrides and hotkeys travel with profiles and exported files.

## Vantage's data directory

Profiles, skins and custom casting images are stored in Vantage's data directory. It is `~/.local/share/vantage` on Linux and `%LOCALAPPDATA%\Vantage` on Windows, and the `VANTAGE_DATA_DIR` environment variable moves it:

| Folder | Contents |
|---|---|
| `profiles/` | saved settings profiles |
| `skins/` | skins (folders or `.zip` files) |
| `images/` | pictures for casting (flags, logos) |

Recordings go to the `recordings` folder of the default data directory unless you pass `--recordings-dir`. `VANTAGE_DATA_DIR` does not move them.

## Other stored state

These are saved with your settings but have no control of their own:

| Setting | What it holds |
|---|---|
| `eventFilterOut` | event-log categories you have hidden (default: `["train_research"]`) |
| `entityNames` | names you gave individual units (click a unit's name in the selection panel to rename it) |
| `flipSidesByGame` | games where you swapped the team sides (Alt+S) |
| `chartDefinitions` | saved chart options on the statistics screen |
| `replayFilters` | the replay browser's filters |
| `panelOffsets` | panel positions (Settings → Casting) |
| `playerNames`, `teamNames`, `playerImages`, `teamCaptains`, `scoreboard`, `mainText`, `secondaryText`, `stageName`, `seriesType`, `seriesScore` | casting overrides (see [Casting and OBS](Casting-and-OBS.md)) |
| `gpuTint` | with GPU rendering, colour sprites by player on the GPU (default on) |
| `seenTutorial`, `seenRorTutorial` | whether the tutorials have been shown |
