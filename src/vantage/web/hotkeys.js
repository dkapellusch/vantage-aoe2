// Keyboard bindings. Every action can be rebound via settings.customHotkeys,
// as one combo ("Ctrl+B"), several (["F11", "Alt+Enter"]) or none ("" / []).

import { settings } from './state.js';

export const KEYMAP = {
  toggleScrubbingBar: ['T', 'Show/hide time controls'],
  pause: ['F3', 'Pause / play'],
  // Space is "centre on selection"; play/pause stays on F3.
  playPause: [[], 'Pause / play (second key, unbound by default)'],
  speedStepUp: [']', 'Faster'],
  speedStepDown: ['[', 'Slower (past pause: reverse)'],
  skipForward: ['=', 'Skip forward 30s'],
  skipBack: ['-', 'Skip back 30s'],
  bookmark: ['F4', 'Bookmark 30s ago'],
  bookmarkPrev: ['Shift+[', 'Previous bookmark'],
  bookmarkNext: ['Shift+]', 'Next bookmark'],
  jumpLive: ['End', 'Jump to live / end'],
  jumpStart: ['Home', 'Jump to start'],
  followSelection: ['F', 'Follow selection'],
  unFollowSelection: ['Ctrl+F', 'Stop following'],
  focusSelection: ['Space', 'Centre on selection'],
  showAchievements: ['Ctrl+Alt+S', 'Statistics'],
  cycleDashboardForward: ['Alt+C', 'Next dashboard page'],
  cycleDashboardBackward: ['Alt+X', 'Previous dashboard page'],
  swapScoreboardTeamSides: ['Alt+S', 'Flip team sides'],
  toggleStaticTechnologies: ['Alt+T', 'Static techs'],
  toggleSlideoutStaticTechs: ['Alt+P', 'Slide-out: all technologies'],
  toggleSlideoutGraph: ['Ctrl+Alt+P', 'Slide-out: graph'],
  toggleProduction: ['Alt+Shift+P', 'Production & composition'],
  toggleResourcesLeft: ['Alt+R', 'Resources left'],
  togglePlayerResources: ['Ctrl+Alt+R', 'Team board: switch Teams / Players'],
  toggleOverview: ['Alt+Shift+R', 'Show/hide team overview'],
  cycleFogOfWar: ['Alt+F', 'Cycle fog mode (off / spy / standard)'],
  toggleFogOfWar: ['Alt+Shift+F', 'Fog on/off'],
  toggleCombinedFogOfWar: ['Alt+D', 'Combined team fog'],
  setPerspectiveForSelected: ['Ctrl+Space', "Perspective: selection's owner"],
  setPlayer0: ['Ctrl+Shift+F9', 'Perspective: Gaia (whole map)'],
  setPlayer1: ['Ctrl+Shift+F1', 'Perspective: player 1'],
  setPlayer2: ['Ctrl+Shift+F2', 'Perspective: player 2'],
  setPlayer3: ['Ctrl+Shift+F3', 'Perspective: player 3'],
  setPlayer4: ['Ctrl+Shift+F4', 'Perspective: player 4'],
  setPlayer5: ['Ctrl+Shift+F5', 'Perspective: player 5'],
  setPlayer6: ['Ctrl+Shift+F6', 'Perspective: player 6'],
  setPlayer7: ['Ctrl+Shift+F7', 'Perspective: player 7'],
  setPlayer8: ['Ctrl+Shift+F8', 'Perspective: player 8'],
  cycleMinimapMode: ['Alt+M', 'Minimap mode'],
  toggleRangeCircles: ['Alt+Q', 'Range circles'],
  cycleBaseColorMode: ['Ctrl+Alt+C', 'Colour scheme (game / cold-warm / warm-cold)'],
  cycleColorMode: ['Ctrl+Alt+G', 'Team colours'],
  setZoomLevelOne: ['Alt+1', 'Zoom preset 1'],
  setZoomLevelTwo: ['Alt+2', 'Zoom preset 2'],
  setZoomLevelThree: ['Alt+3', 'Zoom preset 3'],
  updateZoomLevelOne: ['Alt+Shift+1', 'Save zoom preset 1'],
  updateZoomLevelTwo: ['Alt+Shift+2', 'Save zoom preset 2'],
  updateZoomLevelThree: ['Alt+Shift+3', 'Save zoom preset 3'],
  toggleOverlayDisplay: ['Alt+O', 'Hide UI'],
  toggleMinimapDisplayWhenNoOverlay: ['Alt+Shift+O', 'Keep minimap when UI hidden'],
  notificationsPageUp: ['PageUp', 'Events: page up'],
  notificationsPageDown: ['PageDown', 'Events: page down'],
  notificationsTopPage: ['Shift+PageUp', 'Events: oldest'],
  notificationsBottomPage: ['Shift+PageDown', 'Events: newest'],
  showGameSpeedAndFps: ['F10', 'Show FPS and real speed'],
  toggleFullScreen: [['F11', 'Alt+Enter'], 'Full screen'],
  openHome: ['Ctrl+O', 'Replays & recordings'],
  openHelp: ['?', 'Quick reference'],
  openDocs: ['Shift+F1', 'Documentation'],
  escape: ['Escape', 'Close the top layer, or open the menu'],
  gotoIdleVillager: ['.', 'Next idle villager'],
  gotoIdleMilitary: [',', 'Next idle military'],
  gotoTownCenter: ['Ctrl+H', 'Next town centre'],
  gotoBarracks: ['Ctrl+B', 'Next barracks'],
  gotoArcheryRange: ['Ctrl+A', 'Next archery range'],
  gotoStable: ['Ctrl+L', 'Next stable'],
  gotoSiegeWorkshop: ['Ctrl+K', 'Next siege workshop'],
  gotoCastle: ['Ctrl+V', 'Next castle'],
  gotoKrepost: ['Ctrl+T', 'Next krepost'],
  gotoMonastery: ['Ctrl+Y', 'Next monastery'],
  gotoMarket: ['Ctrl+M', 'Next market'],
  gotoBlacksmith: ['Ctrl+S', 'Next blacksmith'],
  gotoUniversity: ['Ctrl+U', 'Next university'],
  gotoDock: ['Ctrl+D', 'Next dock'],
  gotoMill: ['Ctrl+I', 'Next mill'],
  gotoLumberCamp: ['Ctrl+Z', 'Next lumber camp'],
  selectAllTownCenter: ['Ctrl+Shift+H', 'Select all town centres'],
  selectAllBarracks: ['Ctrl+Shift+B', 'Select all barracks'],
  selectAllArcheryRange: ['Ctrl+Shift+A', 'Select all archery ranges'],
  selectAllStable: ['Ctrl+Shift+L', 'Select all stables'],
  selectAllSiegeWorkshop: ['Ctrl+Shift+K', 'Select all siege workshops'],
  selectAllCastle: ['Ctrl+Shift+V', 'Select all castles'],
  selectAllKrepost: ['Ctrl+Shift+T', 'Select all kreposts'],
  selectAllMonastery: ['Ctrl+Shift+Y', 'Select all monasteries'],
  selectAllMarket: ['Ctrl+Shift+M', 'Select all markets'],
  selectAllBlacksmith: ['Ctrl+Shift+S', 'Select all blacksmiths'],
  selectAllUniversity: ['Ctrl+Shift+U', 'Select all universities'],
  selectAllDock: ['Ctrl+Shift+D', 'Select all docks'],
  selectAllMill: ['Ctrl+Shift+I', 'Select all mills'],
  selectAllLumberCamp: ['Ctrl+Shift+Z', 'Select all lumber camps'],
  gotoKing: ['Ctrl+Alt+,', 'Go to king'],
  toggleCursorClip: ['Alt+Shift+C', 'Lock the mouse to the window'],
  holdFogOfWar: ['Tab (hold)', "Peek at the selection owner's fog"],
  toggleAutocast: ['Alt+A', 'Autocast (automatic camera director)'],
  showHighlights: ['Alt+Shift+A', 'Autocast: show all heroes'],
  showTutorial: ['F1', 'Tutorial'],
  togglePanelsMenu: ['Alt+V', 'Panels: show, hide and collapse HUD panels'],
  arrangePanels: ['Alt+L', 'Arrange panels: drag any panel to move it'],
  toggleCrossThreadProfiling: ['Ctrl+Alt+Shift+P', 'Performance view (frame times, data fetches, memory)'],
};

for (let i = 0; i <= 9; i++) {
  KEYMAP[`setControlGroup${i}`] = [`Ctrl+${i}`, `Set control group ${i}`];
  KEYMAP[`callControlGroup${i}`] = [`${i}`, `Select control group ${i}`];
}

// Bindings that are handled outside the table (hold-to-peek).
const DISPLAY_ONLY = new Set(['holdFogOfWar']);

function asList(v) {
  if (v == null) return [];
  return (Array.isArray(v) ? v : [v]).map((c) => String(c).trim()).filter(Boolean);
}

// Every combo bound to `action`, honouring a custom map (default: settings).
export function bindings(action, custom = settings.customHotkeys) {
  if (custom && Object.prototype.hasOwnProperty.call(custom, action)) return asList(custom[action]);
  return KEYMAP[action] ? asList(KEYMAP[action][0]) : [];
}

// Display text: "F11 / Alt+Enter", or "—" when unbound.
export function binding(action, custom) {
  const list = bindings(action, custom);
  return list.length ? list.join(' / ') : '—';
}

function normalize(combo) {
  const parts = combo.split('+').map((p) => p.trim());
  let key = parts.pop();
  if (key === '' && parts.length && parts[parts.length - 1] === '') { parts.pop(); key = '+'; } // "Ctrl++"
  const mods = new Set(parts.map((p) => p.toLowerCase()));
  if (key === '?') return '|?';
  if (key.toLowerCase() === 'esc') key = 'Escape';
  if (key.toLowerCase() === 'return') key = 'Enter';
  return `${mods.has('ctrl') || mods.has('cmd') ? 'C' : ''}${mods.has('alt') ? 'A' : ''}${mods.has('shift') ? 'S' : ''}|${key.toLowerCase()}`;
}

function eventCombo(e) {
  let key = e.key;
  if (key === ' ') key = 'Space';
  if (/^Digit\d$/.test(e.code)) key = e.code.slice(5);
  if (e.code === 'BracketLeft') key = '[';
  if (e.code === 'BracketRight') key = ']';
  if (e.code === 'Equal') key = '=';
  if (e.code === 'Minus') key = '-';
  if (e.code === 'Comma') key = ',';
  if (e.code === 'Period') key = '.';
  if (e.code === 'Enter' || e.code === 'NumpadEnter') key = 'Enter';
  if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3);
  // '?' is typed with Shift on most layouts; match it without requiring the modifier.
  if (key === '?') return '|?';
  return `${e.ctrlKey || e.metaKey ? 'C' : ''}${e.altKey ? 'A' : ''}${e.shiftKey ? 'S' : ''}|${key.toLowerCase()}`;
}

// Build combo -> action. Custom bindings register first so a remapped action
// takes a key from a default one; any key claimed twice is a conflict.
function build(custom) {
  const map = new Map();
  const claims = new Map(); // normalized combo -> {combo, actions[]}
  const actions = Object.keys(KEYMAP).filter((a) => !DISPLAY_ONLY.has(a));
  const isCustom = (a) => custom && Object.prototype.hasOwnProperty.call(custom, a);
  const order = [...actions.filter(isCustom), ...actions.filter((a) => !isCustom(a))];
  for (const action of order) {
    for (const combo of bindings(action, custom)) {
      const n = normalize(combo);
      if (!claims.has(n)) claims.set(n, { combo, actions: [] });
      const c = claims.get(n);
      if (!c.actions.includes(action)) c.actions.push(action);
      if (!map.has(n)) map.set(n, action);
    }
  }
  const conflicts = [...claims.values()].filter((c) => c.actions.length > 1);
  return { map, conflicts };
}

// Actions whose keys collide, for a candidate custom map (the settings page
// calls this before saving): [{combo, actions: [first (wins), …others]}].
// Unknown action names in the map are reported with combo ''.
export function hotkeyConflicts(custom = settings.customHotkeys) {
  const { conflicts } = build(custom || {});
  const unknown = Object.keys(custom || {}).filter((a) => !KEYMAP[a]);
  return [...conflicts, ...unknown.map((a) => ({ combo: '', actions: [a], unknown: true }))];
}

// Human-readable conflict lines ("Ctrl+B: Next barracks ↔ …").
export function describeConflicts(conflicts, tr = (s) => s) {
  return conflicts.map((c) => (c.unknown
    ? `${tr('Unknown action')}: ${c.actions[0]}`
    : `${c.combo}: ${c.actions.map((a) => tr(KEYMAP[a][1])).join(' ↔ ')}`));
}

let table = null;
export let lastConflicts = [];
// Rebuild the lookup table; returns the conflicts it found (first binding wins).
export function rebuild() {
  const { map, conflicts } = build(settings.customHotkeys || {});
  table = map;
  lastConflicts = conflicts;
  if (conflicts.length) console.warn('Vantage: hotkey conflict(s):', describeConflicts(conflicts).join('; '));
  return conflicts;
}

export function actionFor(e) {
  if (!table) rebuild();
  return table.get(eventCombo(e)) || null;
}

// The quick reference's sections, in reading order. An action belongs to the first
// group whose test accepts it; "Panels" takes the rest.
const KEY_GROUPS = [
  ['Time controls', /^(toggleScrubbingBar|pause|playPause|speedStep|skip|bookmark|jump)/],
  ['Selecting and following', /^(followSelection|unFollowSelection|focusSelection|setZoomLevel|updateZoomLevel|gotoIdle|gotoKing|toggleCursorClip)/],
  ['Fog of war and perspective', /FogOfWar|^setPerspective|^setPlayer\d/],
  ['Colours and display', /^(cycleMinimapMode|toggleRangeCircles|cycleBaseColorMode|cycleColorMode|toggleOverlayDisplay|toggleMinimapDisplayWhenNoOverlay|showGameSpeedAndFps|toggleFullScreen|toggleCrossThreadProfiling)$/],
  ['Autocast', /^(toggleAutocast|showHighlights)$/],
  ['Go to the next building', /^goto/],
  ['Select every building of a type', /^selectAll/],
  ['Control groups', /ControlGroup/],
  ['Panels', /./],
];

/** describeKeys() in sections: [[title, [[binding, description], ...]], ...]. */
export function describeKeyGroups() {
  const groups = KEY_GROUPS.map(([title]) => [title, []]);
  for (const a of Object.keys(KEYMAP)) {
    if (/ControlGroup[1-9]/.test(a)) continue;
    groups[KEY_GROUPS.findIndex(([, test]) => test.test(a))][1].push([binding(a), KEYMAP[a][1]]);
  }
  // "Panels" (everything else) reads best right after the time controls.
  const rest = groups.pop();
  groups.splice(1, 0, rest);
  return groups.filter(([, rows]) => rows.length);
}

export function describeKeys() {
  return Object.keys(KEYMAP).filter((a) => !/ControlGroup[1-9]/.test(a)).map((a) => [binding(a), KEYMAP[a][1]]);
}
