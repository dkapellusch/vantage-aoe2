# Hotkeys

These are Vantage's default keys. Every action can be rebound (see [Changing keys](#changing-keys)). Press <kbd>?</kbd> in Vantage to see the quick reference with **your** current bindings.

<kbd>Meta</kbd> (<kbd>Cmd</kbd>) counts as <kbd>Ctrl</kbd>. Letter, digit and punctuation keys are matched by their position on a US keyboard (so <kbd>[</kbd> is the key to the right of <kbd>P</kbd> whatever your layout prints on it). The exception is <kbd>?</kbd>, which is matched by the character typed.

The **Name** column is the action's name, which you use when rebinding keys as JSON.

### Time controls

| Key | Action | Name |
|---|---|---|
| <kbd>T</kbd> | Show/hide time controls | `toggleScrubbingBar` |
| <kbd>F3</kbd> | Pause / play | `pause` |
| (unbound) | Pause / play (second key, unbound by default) | `playPause` |
| <kbd>]</kbd> | Faster | `speedStepUp` |
| <kbd>[</kbd> | Slower (past pause: reverse) | `speedStepDown` |
| <kbd>=</kbd> | Skip forward 30s | `skipForward` |
| <kbd>-</kbd> | Skip back 30s | `skipBack` |
| <kbd>F4</kbd> | Bookmark 30s ago | `bookmark` |
| <kbd>Shift+[</kbd> | Previous bookmark | `bookmarkPrev` |
| <kbd>Shift+]</kbd> | Next bookmark | `bookmarkNext` |
| <kbd>End</kbd> | Jump to live / end | `jumpLive` |
| <kbd>Home</kbd> | Jump to start | `jumpStart` |

### Camera, selection and following

| Key | Action | Name |
|---|---|---|
| <kbd>F</kbd> | Follow selection | `followSelection` |
| <kbd>Ctrl+F</kbd> | Stop following | `unFollowSelection` |
| <kbd>Space</kbd> | Centre on selection | `focusSelection` |
| <kbd>Alt+1</kbd> | Zoom preset 1 | `setZoomLevelOne` |
| <kbd>Alt+2</kbd> | Zoom preset 2 | `setZoomLevelTwo` |
| <kbd>Alt+3</kbd> | Zoom preset 3 | `setZoomLevelThree` |
| <kbd>Alt+Shift+1</kbd> | Save zoom preset 1 | `updateZoomLevelOne` |
| <kbd>Alt+Shift+2</kbd> | Save zoom preset 2 | `updateZoomLevelTwo` |
| <kbd>Alt+Shift+3</kbd> | Save zoom preset 3 | `updateZoomLevelThree` |
| <kbd>.</kbd> | Next idle villager | `gotoIdleVillager` |
| <kbd>,</kbd> | Next idle military | `gotoIdleMilitary` |
| <kbd>Ctrl+Alt+,</kbd> | Go to king | `gotoKing` |
| <kbd>Alt+Shift+C</kbd> | Lock the mouse to the window | `toggleCursorClip` |

### Fog of war and perspective

| Key | Action | Name |
|---|---|---|
| <kbd>Alt+F</kbd> | Cycle fog mode (off / spy / standard) | `cycleFogOfWar` |
| <kbd>Alt+Shift+F</kbd> | Fog on/off | `toggleFogOfWar` |
| <kbd>Alt+D</kbd> | Combined team fog | `toggleCombinedFogOfWar` |
| <kbd>Ctrl+Space</kbd> | Perspective: selection's owner | `setPerspectiveForSelected` |
| <kbd>Ctrl+Shift+F9</kbd> | Perspective: Gaia (whole map) | `setPlayer0` |
| <kbd>Ctrl+Shift+F1</kbd> | Perspective: player 1 | `setPlayer1` |
| <kbd>Ctrl+Shift+F2</kbd> | Perspective: player 2 | `setPlayer2` |
| <kbd>Ctrl+Shift+F3</kbd> | Perspective: player 3 | `setPlayer3` |
| <kbd>Ctrl+Shift+F4</kbd> | Perspective: player 4 | `setPlayer4` |
| <kbd>Ctrl+Shift+F5</kbd> | Perspective: player 5 | `setPlayer5` |
| <kbd>Ctrl+Shift+F6</kbd> | Perspective: player 6 | `setPlayer6` |
| <kbd>Ctrl+Shift+F7</kbd> | Perspective: player 7 | `setPlayer7` |
| <kbd>Ctrl+Shift+F8</kbd> | Perspective: player 8 | `setPlayer8` |
| <kbd>Tab (hold)</kbd> | Peek at the selection owner's fog | `holdFogOfWar` |

### Panels and screens

| Key | Action | Name |
|---|---|---|
| <kbd>Ctrl+Alt+S</kbd> | Statistics | `showAchievements` |
| <kbd>Alt+C</kbd> | Next dashboard page | `cycleDashboardForward` |
| <kbd>Alt+X</kbd> | Previous dashboard page | `cycleDashboardBackward` |
| <kbd>Alt+S</kbd> | Flip team sides | `swapScoreboardTeamSides` |
| <kbd>Alt+T</kbd> | Static techs | `toggleStaticTechnologies` |
| <kbd>Alt+P</kbd> | Slide-out: all technologies | `toggleSlideoutStaticTechs` |
| <kbd>Ctrl+Alt+P</kbd> | Slide-out: graph | `toggleSlideoutGraph` |
| <kbd>Alt+Shift+P</kbd> | Production & composition | `toggleProduction` |
| <kbd>Alt+R</kbd> | Resources left | `toggleResourcesLeft` |
| <kbd>Ctrl+Alt+R</kbd> | Team board: switch Teams / Players | `togglePlayerResources` |
| <kbd>Alt+Shift+R</kbd> | Show/hide Team board | `toggleOverview` |
| <kbd>Alt+B</kbd> | Show/hide Dashboard | `toggleDashboard` |
| <kbd>Alt+E</kbd> | Show/hide Event log | `toggleEvents` |
| <kbd>Alt+U</kbd> | Show/hide Selection panel | `toggleSelectionPanel` |
| <kbd>Alt+G</kbd> | Show/hide Scoreboard (the Pulse strip in presets that use it) | `toggleScoreboard` |
| <kbd>Alt+K</kbd> | Show/hide Focus slot | `toggleFocusSlot` |
| <kbd>Alt+Y</kbd> | Show/hide Match story timeline | `toggleStory` |
| <kbd>PageUp</kbd> | Events: page up | `notificationsPageUp` |
| <kbd>PageDown</kbd> | Events: page down | `notificationsPageDown` |
| <kbd>Shift+PageUp</kbd> | Events: oldest | `notificationsTopPage` |
| <kbd>Shift+PageDown</kbd> | Events: newest | `notificationsBottomPage` |
| <kbd>Ctrl+O</kbd> | Replays & recordings | `openHome` |
| <kbd>?</kbd> | Quick reference | `openHelp` |
| <kbd>Shift+F1</kbd> | Documentation | `openDocs` |
| <kbd>Escape</kbd> | Close the top layer, or open the menu | `escape` |
| <kbd>F1</kbd> | Tutorial | `showTutorial` |

### HUD presets and layout

| Key | Action | Name |
|---|---|---|
| <kbd>F6</kbd> | HUD preset: Minimal | `hudPresetMinimal` |
| <kbd>F7</kbd> | HUD preset: Caster | `hudPresetCaster` |
| <kbd>F8</kbd> | HUD preset: Review | `hudPresetReview` |
| <kbd>F9</kbd> | HUD preset: Analyst | `hudPresetAnalyst` |
| <kbd>Shift+F6</kbd> | HUD preset: Full | `hudPresetFull` |
| <kbd>`</kbd> (hold) | Peek at the Full HUD | `peekFullHud` |
| <kbd>Alt+V</kbd> | Customize: presets, panels and metrics | `togglePanelsMenu` |
| <kbd>Alt+L</kbd> | Edit layout: move, resize and place panels | `arrangePanels` |
| <kbd>Ctrl+Alt+D</kbd> | Statistics window: dock right / float | `toggleStatsDock` |

<kbd>F6</kbd>–<kbd>F9</kbd> are free in browsers and in the game. Full sits on <kbd>Shift+F6</kbd> because <kbd>F10</kbd> shows the frame rate. If a Stream Deck or OBS already uses these keys, rebind them in Settings → Hotkeys. <kbd>Alt+C</kbd> / <kbd>Alt+X</kbd> cycle the Focus slot's card while the Dashboard is hidden.

### Display

| Key | Action | Name |
|---|---|---|
| <kbd>Alt+M</kbd> | Minimap mode | `cycleMinimapMode` |
| <kbd>Alt+Q</kbd> | Range circles | `toggleRangeCircles` |
| <kbd>Ctrl+Alt+C</kbd> | Colour scheme (game / cold-warm / warm-cold) | `cycleBaseColorMode` |
| <kbd>Ctrl+Alt+G</kbd> | Team colours | `cycleColorMode` |
| <kbd>Alt+O</kbd> | Hide UI | `toggleOverlayDisplay` |
| <kbd>Alt+Shift+O</kbd> | Keep minimap when UI hidden | `toggleMinimapDisplayWhenNoOverlay` |
| <kbd>F10</kbd> | Show FPS and real speed | `showGameSpeedAndFps` |
| <kbd>F11</kbd> / <kbd>Alt+Enter</kbd> | Full screen | `toggleFullScreen` |
| <kbd>Ctrl+Alt+Shift+P</kbd> | Performance view (frame times, data fetches, memory) | `toggleCrossThreadProfiling` |

### Autocast

| Key | Action | Name |
|---|---|---|
| <kbd>Alt+A</kbd> | Autocast (automatic camera director) | `toggleAutocast` |
| <kbd>Alt+Shift+A</kbd> | Autocast: show all heroes | `showHighlights` |

### Go to the next building

| Key | Action | Name |
|---|---|---|
| <kbd>Ctrl+H</kbd> | Next town centre | `gotoTownCenter` |
| <kbd>Ctrl+B</kbd> | Next barracks | `gotoBarracks` |
| <kbd>Ctrl+A</kbd> | Next archery range | `gotoArcheryRange` |
| <kbd>Ctrl+L</kbd> | Next stable | `gotoStable` |
| <kbd>Ctrl+K</kbd> | Next siege workshop | `gotoSiegeWorkshop` |
| <kbd>Ctrl+V</kbd> | Next castle | `gotoCastle` |
| <kbd>Ctrl+T</kbd> | Next krepost | `gotoKrepost` |
| <kbd>Ctrl+Y</kbd> | Next monastery | `gotoMonastery` |
| <kbd>Ctrl+M</kbd> | Next market | `gotoMarket` |
| <kbd>Ctrl+S</kbd> | Next blacksmith | `gotoBlacksmith` |
| <kbd>Ctrl+U</kbd> | Next university | `gotoUniversity` |
| <kbd>Ctrl+D</kbd> | Next dock | `gotoDock` |
| <kbd>Ctrl+I</kbd> | Next mill | `gotoMill` |
| <kbd>Ctrl+Z</kbd> | Next lumber camp | `gotoLumberCamp` |

### Select every building of a type

| Key | Action | Name |
|---|---|---|
| <kbd>Ctrl+Shift+H</kbd> | Select all town centres | `selectAllTownCenter` |
| <kbd>Ctrl+Shift+B</kbd> | Select all barracks | `selectAllBarracks` |
| <kbd>Ctrl+Shift+A</kbd> | Select all archery ranges | `selectAllArcheryRange` |
| <kbd>Ctrl+Shift+L</kbd> | Select all stables | `selectAllStable` |
| <kbd>Ctrl+Shift+K</kbd> | Select all siege workshops | `selectAllSiegeWorkshop` |
| <kbd>Ctrl+Shift+V</kbd> | Select all castles | `selectAllCastle` |
| <kbd>Ctrl+Shift+T</kbd> | Select all kreposts | `selectAllKrepost` |
| <kbd>Ctrl+Shift+Y</kbd> | Select all monasteries | `selectAllMonastery` |
| <kbd>Ctrl+Shift+M</kbd> | Select all markets | `selectAllMarket` |
| <kbd>Ctrl+Shift+S</kbd> | Select all blacksmiths | `selectAllBlacksmith` |
| <kbd>Ctrl+Shift+U</kbd> | Select all universities | `selectAllUniversity` |
| <kbd>Ctrl+Shift+D</kbd> | Select all docks | `selectAllDock` |
| <kbd>Ctrl+Shift+I</kbd> | Select all mills | `selectAllMill` |
| <kbd>Ctrl+Shift+Z</kbd> | Select all lumber camps | `selectAllLumberCamp` |

### Control groups

| Key | Action | Name |
|---|---|---|
| <kbd>Ctrl+0</kbd> … <kbd>Ctrl+9</kbd> | Set control group 0–9 | `setControlGroup0` … `setControlGroup9` |
| <kbd>0</kbd> … <kbd>9</kbd> | Select control group 0–9 | `callControlGroup0` … `callControlGroup9` |

### Other keys

| Key | Action |
|---|---|
| Arrow keys | Scroll the map: a step for a tap, steadily while held |

## Mouse

| Mouse | Action |
|---|---|
| Right-drag / middle-drag | Pan |
| Two fingers on a trackpad | Pan (a setting can make it zoom) |
| Pinch on a trackpad | Zoom at the pointer |
| Wheel | Zoom at the cursor |
| Click / drag | Select / box select |
| Double-click | Select all units of the same type on screen |
| <kbd>Shift</kbd> / <kbd>Ctrl</kbd> + select | Add to the selection / toggle in or out |
| <kbd>Shift</kbd> + right-click a unit | Switch perspective to its owner |
| Minimap click or drag | Move the camera |
| Player name (scoreboard) | Cycle that player's colour |
| Civilisation emblem (hover) | That civilisation's tech tree |
| Age icon | Go to the player's town centre |
| Event time | Jump to that moment |
| Event row | Move the camera to where it happened |
| Time bar click | Seek |
| Time bar right-click | Add or remove a bookmark |
| Chart right-click | Jump to that time |
| Chart wheel | Zoom the chart |
| Fog button: click or right-click / middle-click | Cycle the fog mode / combine team fog |

## Changing keys

Open **Settings → Hotkeys**:

- Click a binding and press the new key combination. <kbd>Backspace</kbd> unbinds it and <kbd>Esc</kbd> cancels.
- Use **+** to add a second key for the same action.
- **Reset all hotkeys** goes back to the defaults.
- **Advanced: edit as JSON** lets you edit the whole map at once.

The JSON maps an action's name to one key, a list of keys, or nothing:

```json
{
  "gotoKrepost": "Ctrl+Shift+K",
  "toggleFullScreen": ["F11", "Alt+Enter"],
  "playPause": "Space",
  "focusSelection": "",
  "showTutorial": []
}
```

Only the actions you list change. The rest keep their defaults. Write combinations as modifiers then key, joined with `+`: `Ctrl`, `Alt`, `Shift` (`Cmd` counts as `Ctrl`), then a key such as `A`, `F5`, `Space`, `Enter`, `Escape`, `Home`, `End`, `PageUp`, `[`, `=`, `,` or `.`.

If two actions end up on the same key, Vantage warns you (in Settings and when it starts). An action you rebound takes the key from one still on its default. Between two actions in the same situation, the one that comes first in Vantage's built-in action list (`web/hotkeys.js`) keeps the key.

Your bindings are stored with your other settings (`customHotkeys`), so they travel with [settings profiles](Settings.md#profiles-import-and-export).
