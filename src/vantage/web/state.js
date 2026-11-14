import { requestResource } from './startup-assets.js';
// Shared state, server API, persisted settings and small helpers.

import { t } from './i18n.js';
import { ViewCache, mergeSeries, seriesEnd } from './playback.js';
import { compactTeamLabels, memberLabel } from './team-names.js';
import { defaultHud, normalizeHud, initialPreset, normalizeSelectionPanel, SELECTION_DEFAULTS } from './hud-model.js';

export const S = {
  upcoming: [],   // read-ahead views (fast playback): their strips are requested early
  scrubbing: false, // the time bar is being dragged: no look-ahead until it is released
  session: null,
  version: '',         // the server's Vantage version (/api/config)
  game: 'aoe2',        // 'aoe2' or 'ror' (Return of Rome)
  match: { players: {} },
  map: null,
  catalog: { units: {}, techs: {} },
  catalogVersion: -1,
  view: null,          // keyframe at/below t
  nextView: null,      // keyframe after, for interpolation
  skipViews: [],       // the views a 30 s skip either way lands on, when the pack holds them: their graphics are fetched early
  t: 0,                // playback clock, game ms
  playing: true,
  speedIndex: 2,       // into SPEEDS
  followLive: true,
  start: 0,
  end: 0,
  complete: false,
  perspective: 0,      // 0 = everyone (no fog)
  fogMode: 'off',      // off | standard | explored
  combinedFog: false,
  colorMode: 'game',   // game | team
  colorOverride: {},
  selection: new Set(),
  selectionInfo: new Map(), // id -> {mid, owner}, so dead units stay listed
  followSelection: false,
  controlGroups: {},
  camera: { x: 60, y: 60, zoom: 1.0 },
  dashPage: 0,
  events: [],
  eventsTo: -1,
  bookmarks: [],
  reviewScope: 'life',
  seekVersion: 0,
  reviewRange: null,
  minimapMode: 'standard', // standard | military | resource
  rangeCircles: true,
  flipSides: false,
  showFps: false,
  fps: 0,
  summary: null,
  series: null,
  seriesAt: -1,
};

// Playback speeds; reverse playback (negative) is reached by stepping below pause.
export const SPEEDS = [-8, -4, -2, -1, -0.5, 0.5, 1, 2, 4, 8];
S.speedIndex = SPEEDS.indexOf(1);

const SETTINGS_KEY = 'vantage.settings.v1';
export const DEFAULT_SETTINGS = {
  showStaticTechs: false,       // the 57-icon grid: a toggle (and slide-out); off, the left column fits 1080p
  showProduction: true,
  showDashboard: true,
  showEvents: true,
  hiddenPanels: [],             // HUD panels hidden from the Panels menu or their ✕ (layout.js)
  collapsedPanels: [],          // HUD panels collapsed to their top strip
  eventFilterOut: ['train_research'],
  zoomLevels: { one: 1.6, two: 1.0, three: 0.55 },
  cameraSmoothMs: 1250,       // how long camera moves and wheel zooms ease
  edgeScroll: true,           // scroll at the screen edges
  edgeScrollSpeed: 1,
  zoomSpeed: 1,
  mapResolution: 0,           // most device pixels per CSS pixel the map is drawn at (0: the display's own; 1.5, 1: fewer pixels on a Retina display)
  twoFingerScroll: 'auto',    // wheel events in pixels (a trackpad): 'auto' moves the map and leaves zoom to a mouse wheel; 'pan' / 'zoom' force one
  showElo: true,
  hideScore: false,
  teamScore: 'sum',            // two-team scoreboard: sum | average | off
  hudLayout: 'caster',         // default panel placement: caster (scoreboard bar, board bottom left) | classic
  teamBoardView: 'teams',      // team overview in team games: teams (comparison) | players
  teamBoardCollapsed: [],      // team board sections folded to their heading
  panelOrder: [],              // moved panels, last-dragged on top (panel-resize.js)
  rangeCircleModeBuildings: 'always', // always | selected | none
  keepDeadInSelection: true,
  showUnitPanelWhenNothingSelected: false,
  entityNames: {},     // entity id -> custom name
  playerImages: {},    // pid -> image URL (flag / custom picture) shown on the scoreboard
  teamCaptains: {},    // team key -> pid whose colour the team uses in team-colour mode
  mainText: '',
  secondaryText: '',
  post: { brightness: 1, contrast: 1, saturation: 1, gamma: 1 },
  smallTrees: false,
  chartDefinitions: {},
  seenTutorial: false,
  seenRorTutorial: false,
  enhancedGraphics: false,
  language: '',        // '' = follow the browser
  soundOutputVolume: 1,
  soundVolumes: { events: 1, units: 0.8, combat: 1, selection: 1, taunts: 1 },
  soundEventConfig: { train: 'selectedPlayer', research: 'selectedPlayer', attack: 'screenOrSelectedOwners', conversion: 'screenOrSelectedOwners' },
  soundAlertInterval: 3000,
  chatEventSoundOption: 'chatAlertAndTaunt',
  tooltips: true,
  autoRecord: false,   // live sessions started with --live still record
  playerNames: {},     // casting overrides: pid -> name
  teamNames: {},       // team key -> name
  stageName: '',
  seriesType: '',
  seriesScore: '',
  customHotkeys: {},
  terrainGrid: 0,
  gameGraphics: true, // draw the game's own sprites when zoomed in
  skin: 'default',     // default | classic | contrast | clean
  dashboardColumns: {}, // page key -> column keys (empty = the page's defaults)
  // -- dashboard, scoreboard, graphics, skins ---------------------------------------
  dashboardMirror: {},          // page key -> mirror columns for the right-hand team
  dashboardSelection: {},       // layout -> page key last shown
  useMiniDashboard: false,
  // [up, right] in 1080p reference pixels per panel (no clamp,
  // negatives allowed) plus the team overview's top padding. Older settings with
  // overviewTop/scoreBottom/scoreRight/dashboardBottom are migrated on load.
  panelOffsets: { overviewTop: 0, dashboard: [0, 0], score: [0, 0], minimap: [0, 0], selectionPanel: [0, 0], eventNotifications: [0, 0] },
  customDashboardConfig: {},    // layout -> [{id, columns:[colKey…], mirror?}] (dashboard editor)
  useCommunityGameSkin: false,  // alternative FFA scoreboard layout
  disableScoreboard: false,
  hideScoreDots: false,
  showRankedEloForUnrankedGames: true,
  flipSidesByGame: {},          // game id -> true when sides are flipped
  scoreboard: { seriesType: 'bestOf', numberOfMatches: 3, matches: [], seeds: {} },
  tooltipShowMode: ['iconNames', 'detailedHelp'], // two independent flags
  lastUsedGameDirectory: '',    // pushed to the server (POST /api/game_dir); '' = auto-detect
  baseColorMode: 'default',     // default | coldWarm | warmCold
  rangeCircleModeSelectedEntities: 'always', // always | none
  clipCursorInGame: false,      // in a browser pointer lock steals every click, so opt-in
  limitToSixtyFps: false,       // GPU rendering keeps up with high-refresh screens
  filtering: { unitShadow: false, unitColor: false, unitDamage: false, particle: false, terrain: false }, // default: off
  // Bloom defaults: off, threshold 0.9, scale 1, brightness 1, blur 8, quality 4 (= 'medium').
  postExtra: { red: 1, green: 1, blue: 1, alpha: 1, fxaa: false, bloomEnable: false, bloomThreshold: 0.9, bloomBlur: 8, bloomScale: 1, bloomBrightness: 1, bloomQuality: 'medium' },
  enableGraphicsMods: false,
  enableSpriteMods: false,
  enableTerrainMods: false,
  modDirectories: [],
  soundVolumesExtra: { villagers: 1, critters: 1, ambience: 0.5, reverb: 0, combatImpacts: 1 },
  tauntLanguage: '',             // '' = interface language
  disableScrubbing: false,
  colorGrade: 'auto',           // the map's colour grade: auto (from its script) or a preset name
  colorGradeByGame: {},         // game id -> preset picked for that game (random-grade maps)
  waitForGraphics: true,        // hold playback a moment until new graphics are in (no pop-in)
  localTimeline: true,          // keep a finished match in this browser: seeks and playback need no view requests ('always': also beside a fast server, where asking is quicker)
  gpuSprites: true,             // draw sprites with WebGL2 in one batch (sprite-gl.js); off: Canvas 2D
  gpuTint: true,                // with gpuSprites: one uncoloured strip per sprite, coloured on the GPU (no UI)
  healthBars: 'damaged',        // damaged | always | never (the game's own Health Bars option)
  replayReadAhead: true,        // replays the game plays: run them at its fastest speed, watch from the buffer
  autoMinimizeGame: true,       // minimise the game while Vantage has focus (live)
  toggleForScience: false,      // experimental features: renderings inferred, not documented
  atlasMemoryNormal: 1536,      // MB of decoded sprite strips kept (standard graphics); filled only as a game needs it
  atlasMemoryUhd: 1536,         // MB when UHD (x2) graphics are on
  gameWarningsDismissed: false, // the game-version compatibility warning was hidden
  htmlServerInfo: true,         // show the OBS browser-source URL in Casting
  fullStaticTechs: false,       // append the castle and imperial unique techs to the static techs panel
  endgameAutoClose: '0',        // seconds; '0' = close manually
  castingByIdentity: true,      // casting name/image overrides follow the player, not the slot
  showStatsTimeControls: true,  // the full-screen Statistics page (a phone); the Statistics window has none
  replayFilters: { game: '', civ: '', mode: '', players: '', count: '', player: '', strict: false, compatible: false, spoilers: true },
  autocastHighlights: true,
  toggleHTMLServer: false,      // skin-debugging HTTP server (live reload + /stats-dump)
  enabledSkins: [],             // several user skins merged (names); [] = default look
  // The Selection panel's memory: open sections, the upgrades overflow, the activity scope, chip or full panel.
  selectionPanel: { ...SELECTION_DEFAULTS, open: {} },
  statsWindow: { docked: false }, // the Statistics window: docked right or floating (its rectangle is in panelSizes)
  // The customizable HUD (hud-model.js): the preset, each preset's edits, the layout options.
  hud: defaultHud(),
  settingsVersion: 10,
};

// One-off migrations for settings saved by older builds. Runs on every load
// path; idempotent.
export function migrateSettings(s) {
  const v = +s.settingsVersion || 1;
  const o = s.panelOffsets || {};
  const pair = (x) => (Array.isArray(x) ? [+x[0] || 0, +x[1] || 0] : [0, 0]);
  if (!Array.isArray(o.dashboard) || !Array.isArray(o.score) || ['scoreBottom', 'scoreRight', 'dashboardBottom'].some((k) => k in o)) {
    // Older keys: dashboard = [dashboardBottom, 0], score = [scoreBottom, scoreRight], others [0, 0].
    s.panelOffsets = {
      overviewTop: +o.overviewTop || 0,
      dashboard: Array.isArray(o.dashboard) ? pair(o.dashboard) : [+o.dashboardBottom || 0, 0],
      score: Array.isArray(o.score) ? pair(o.score) : [+o.scoreBottom || 0, +o.scoreRight || 0],
      minimap: pair(o.minimap), selectionPanel: pair(o.selectionPanel), eventNotifications: pair(o.eventNotifications),
    };
  }
  if (v < 2) {
    // Version 2 resets these for existing users.
    s.autoMinimizeGame = true;
    s.filtering = { unitShadow: false, unitColor: false, unitDamage: false, particle: false, terrain: false };
    s.showRankedEloForUnrankedGames = true;
    // The graphics-mods switch becomes sprite + terrain mods.
    if (s.enableGraphicsMods) { s.enableSpriteMods = true; s.enableTerrainMods = true; }
    if (!Array.isArray(s.enabledSkins)) s.enabledSkins = [];
    if (!s.customDashboardConfig || typeof s.customDashboardConfig !== 'object') s.customDashboardConfig = {};
    s.settingsVersion = 2;
  }
  if (v < 3) {
    // Bloom gets its own switch, a Brightness key and new defaults; the old
    // Picture "Bloom" amount (post.bloom) becomes enable + brightness.
    const px = { ...(s.postExtra || {}) };
    const amount = +(s.post && s.post.bloom) || 0;
    if (amount > 0) { px.bloomEnable = true; px.bloomBrightness = amount; }
    if (s.post && 'bloom' in s.post) { s.post = { ...s.post }; delete s.post.bloom; }
    if (px.bloomThreshold === 0.6) px.bloomThreshold = 0.9; // the old defaults, never touched
    if (px.bloomBlur === 6) px.bloomBlur = 8;
    s.postExtra = px;
    // Sound buses that still sit on the old defaults move to the new ones.
    const ex = { ...(s.soundVolumesExtra || {}) };
    for (const [k, was, now] of [['villagers', 0.6, 1], ['critters', 0.5, 1], ['reverb', 0.3, 0], ['combatImpacts', 0.6, 1]]) if (ex[k] === was) ex[k] = now;
    s.soundVolumesExtra = ex;
    if (s.soundVolumes && s.soundVolumes.combat === 0.6) s.soundVolumes = { ...s.soundVolumes, combat: 1 };
    s.settingsVersion = 3;
  }
  if (v < 4) {
    // Cursor lock was on by default: the first click into the map locked the
    // pointer and every button (tutorial, panels) stopped taking clicks.
    s.clipCursorInGame = false;
    s.settingsVersion = 4;
  }
  if (v < 5) {
    // The static tech grid next to the overview and production overflowed the left
    // column at 1080p (a scrollbar, production rows cut off): off by default.
    s.showStaticTechs = false;
    s.settingsVersion = 5;
  }
  if (v < 6) {
    // The sprite budget was below what a busy 8x battle keeps on screen: strips were
    // evicted and reloaded every frame. Raised, for anyone still on the old default.
    if (s.atlasMemoryNormal === 256) s.atlasMemoryNormal = 768;
    if (s.atlasMemoryUhd === 512) s.atlasMemoryUhd = 1536;
    s.settingsVersion = 6;
  }
  if (v < 7) {
    // With GPU rendering a busy 8-player battle draws in 2-3 ms: a 120 Hz screen can
    // show every frame it refreshes, and the 60 fps cap halved it. Off for everyone.
    s.limitToSixtyFps = false;
    s.settingsVersion = 7;
  }
  if (v < 8) {
    // At 768 MB the whole-map view of a late eight-player game at 8x evicted
    // strips it was about to draw: playback held for graphics on 11 % of frames
    // (2 % at 1536 MB) and fell to 90 % of the speed asked for. The memory is
    // used only as a game needs it. The old default moves up; a chosen value stays.
    if (s.atlasMemoryNormal === 768) s.atlasMemoryNormal = 1536;
    s.settingsVersion = 8;
  }
  if (v < 9) {
    // The team average becomes a team score that is summed by default, and the
    // caster layout (scoreboard bar on top, team board bottom left) the default.
    s.teamScore = s.teamAverageScore === false ? 'off' : 'sum';
    delete s.teamAverageScore;
    s.hudLayout = 'caster';
    s.settingsVersion = 9;
  }
  if (v < 10) {
    // The "Minimal UI" checkbox wrote this flag and nothing read it. The HUD
    // presets replace it; a saved setup stays on Full (the HUD as it was).
    delete s.useMinimalUi;
    s.settingsVersion = 10;
  }
  s.hud = normalizeHud(s.hud);
  s.selectionPanel = normalizeSelectionPanel(s.selectionPanel);
  // Team games now have one Overview. Do not reinterpret a custom page's id.
  if (s.dashboardSelection?.oppositional === 'overviewSmall'
    && !s.customDashboardConfig?.oppositional?.length) {
    s.dashboardSelection = { ...s.dashboardSelection, oppositional: 'overviewEcoLosses' };
  }
  // "Wonders & relics" folded into the King category.
  if (Array.isArray(s.eventFilterOut) && s.eventFilterOut.includes('victory')) {
    s.eventFilterOut = [...new Set(s.eventFilterOut.filter((k) => k !== 'victory').concat('king'))];
  }
  // The old 3-way tooltipMode select becomes tooltipShowMode's two flags.
  if ('tooltipMode' in s) {
    s.tooltipShowMode = { detailed: ['iconNames', 'detailedHelp'], names: ['iconNames'], off: [] }[s.tooltipMode] || ['iconNames', 'detailedHelp'];
    delete s.tooltipMode;
  }
  return s;
}

// Where this page runs: inside another page (a hub embed) or under a hub match
// path. A new viewer there starts on Minimal; the desktop app starts on Full.
export function hudEnvironment() {
  let embedded = false, hosted = false, phone = false, requested = null;
  try { embedded = typeof window !== 'undefined' && window.self !== window.top; } catch (e) { embedded = true; }
  try {
    hosted = typeof location !== 'undefined' && /^\/v\//.test(location.pathname || '');
    requested = typeof location !== 'undefined' ? new URLSearchParams(location.search || '').get('hud') : null;
  } catch (e) { /* no location: a test or a worker */ }
  // A phone: a touch screen that is narrow, or short (held sideways).
  try { phone = typeof matchMedia === 'function' && matchMedia('(pointer: coarse) and (max-width: 700px), (pointer: coarse) and (max-height: 500px)').matches; } catch (e) { /* no media queries */ }
  return { embedded, hosted, phone, requested };
}

/** True when this browser had saved settings when the page loaded. */
export let settingsWereSaved = false;

// The settings of a viewer with nothing saved: the defaults, on the preset for this environment.
function freshSettings() {
  const env = hudEnvironment();
  return { ...DEFAULT_SETTINGS, hud: { ...defaultHud(), preset: initialPreset({ ...env, hasSaved: false }) } };
}

export let settings = loadSettings();

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
        settingsWereSaved = true;
        return migrateSettings({ ...DEFAULT_SETTINGS, settingsVersion: 1, ...saved });
      }
    }
  } catch (e) { /* storage blocked or unreadable: defaults */ }
  return freshSettings();
}

// Server-side launch config: --patch-config overrides, --force-default-config.
export function applyServerConfig(cfg) {
  if (!cfg) return;
  assetVersion = typeof cfg.asset_version === 'string' ? cfg.asset_version : '';
  S.gameArt = cfg.game_art !== false;
  if (cfg.force_default) settings = freshSettings();
  Object.assign(settings, cfg.patch || {});
  migrateSettings(settings);
}

export function saveSettings() {
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (e) { /* ignore */ }
}

// Replace every setting (a loaded profile or an imported file), keeping defaults
// for anything the source does not mention.
export function replaceSettings(next) {
  settings = migrateSettings({ ...DEFAULT_SETTINGS, settingsVersion: 1, ...next });
  saveSettings();
}

export function resetSettings() {
  settings = freshSettings();
  saveSettings();
}

// -- API ----------------------------------------------------------------------

/**
 * JSON from the server. `priority` ('high' | 'low') is the fetch priority: the
 * browser's few connections to the server go to the views playback is waiting
 * for before statistics and unit details.
 */
export async function api(path, body, { priority, signal } = {}) {
  const opts = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  };
  if (priority) opts.priority = priority;
  if (signal) opts.signal = signal;
  return requestResource(path, opts);
}

// Sprite strips come from the other name of this loopback server (127.0.0.1 <->
// localhost): another origin has its own six HTTP/1.1 connections, so a burst of
// strips for a new battle never queues the next view behind it. Used only once
// the server answers that origin with CORS (probeAssetOrigin); else same origin.
let assetBase = '';
// The server's asset version (/api/config): converted game assets requested
// with it are cached by the browser for good (the version changes whenever the
// game build, mods or Vantage could change them), not re-validated daily.
let assetVersion = '';
export function withAssetVersion(path) {
  return assetVersion ? `${path}${path.includes('?') ? '&' : '?'}av=${assetVersion}` : path;
}
export function assetUrl(path) { return assetBase + withAssetVersion(path); }
export function pairedOrigin(loc) {
  // A hub match needs its authenticated origin and match-scoped worker. The
  // desktop's optional second-host connection pool cannot work behind a proxy.
  if (loc.pathname?.startsWith('/v/')) return '';
  const alt = { '127.0.0.1': 'localhost', localhost: '127.0.0.1' }[loc.hostname];
  return alt && loc.protocol === 'http:' ? `http://${alt}${loc.port ? `:${loc.port}` : ''}` : '';
}
export async function probeAssetOrigin() {
  const alt = pairedOrigin(location);
  if (!alt) return '';
  try {
    const r = await fetch(`${alt}/api/config`, { mode: 'cors', cache: 'no-store', signal: AbortSignal.timeout(1500) });
    if (r.ok) assetBase = alt;
  } catch { /* other name unreachable or no CORS: stay on this origin */ }
  return assetBase;
}

/**
 * Bring S.series up to date with only the rows since the newest one held (the
 * whole series is megabytes in a long game). A reply for an earlier session is
 * dropped.
 */
export async function refreshSeries() {
  const gen = S.session && S.session.generation;
  const from = seriesEnd(S.series);
  const add = await api(from < 0 ? '/api/series' : `/api/series?from=${from}`, undefined, { priority: 'low' });
  if ((S.session && S.session.generation) !== gen) return S.series;
  S.series = from < 0 ? add : mergeSeries(S.series, add, from);
  S.seriesAt = S.end;
  return S.series;
}

// Keep exact request times: keyframes need not align with whole seconds. Two
// queries in one second can straddle a keyframe and return different views.
// View requests of one seek share an AbortController: the next seek cancels the
// ones still queued (dragging the scrub bar issued a request per mouse move, and
// each kept a connection busy long after the playhead had moved on).
// Cancellation lags one seek behind: a seek cancels the requests of the seek
// before the previous one, so the newest view still arriving (slower than the
// 80 ms scrub step in a large late game) lands instead of being cancelled too.
let viewAbort = new AbortController(), previousAbort = null;
export function abortViews() {
  if (previousAbort) previousAbort.abort();
  previousAbort = viewAbort;
  viewAbort = new AbortController();
}
const viewCache = new ViewCache((t) => viewJson(`/api/view?t=${t}`, viewAbort.signal, t));

// Views come from a worker (view-worker.js): rebuilt from the match's pack when
// this browser holds that stretch of it (startPack; no network at all), else
// fetched and parsed there: at 8x that is ~14 documents of a few hundred KB a
// second kept off the main thread. Without workers (or if it fails) they are
// fetched here as before.
let viewWorker = null, workerTried = false, workerSeq = 0;
const workerCalls = new Map();
/** View request timings (ms, newest last) for the performance view, and totals. */
export const viewTimings = [];
export const viewStats = { issued: 0, requests: 0, ms: 0, local: 0 }; // issued: including cancelled ones; local: answered from the pack
/** The match's pack in this browser: { state, chunks, have, bytes, key } (PackStore.status). */
export const packStatus = { state: 'off', chunks: 0, have: 0, bytes: 0, key: null, building: false };
function startViewWorker() {
  workerTried = true;
  try {
    viewWorker = new Worker(new URL('./view-worker.js', import.meta.url), { type: 'module' });
    viewWorker.onmessage = (e) => {
      if (e.data.pack) { Object.assign(packStatus, e.data.pack); return; }
      const call = workerCalls.get(e.data.id);
      if (!call) return;
      workerCalls.delete(e.data.id);
      if (e.data.local) viewStats.local++;
      if (e.data.error != null) call.reject(new Error(e.data.error)); else call.resolve(e.data.value);
    };
    viewWorker.onerror = () => {
      viewWorker = null;
      packStatus.state = 'off';
      for (const call of workerCalls.values()) call.reject(new Error('view worker failed'));
      workerCalls.clear();
    };
  } catch { viewWorker = null; }
}
// One request to the worker: `extra` is merged into the message ({ t } for a
// view, { t, tiles } for a snapshot of the forest or the terrain).
function workerCall(path, signal, extra) {
  return new Promise((resolve, reject) => {
    const id = ++workerSeq;
    workerCalls.set(id, { resolve, reject });
    viewWorker.postMessage({ id, url: viewRequestUrl(path, location.href), ...extra });
    if (signal) {
      signal.addEventListener('abort', () => {
        if (!workerCalls.delete(id)) return;
        if (viewWorker) viewWorker.postMessage({ abort: id });
        reject(new DOMException('view request cancelled', 'AbortError'));
      }, { once: true });
    }
  });
}
function viewJson(path, signal, t) {
  if (!workerTried) startViewWorker();
  viewStats.issued++;
  const t0 = performance.now();
  const done = (v) => {
    const ms = performance.now() - t0;
    viewTimings.push(ms); if (viewTimings.length > 120) viewTimings.shift();
    viewStats.requests++; viewStats.ms += ms;
    return v;
  };
  if (!viewWorker) return api(path, undefined, { priority: 'high', signal }).then(done);
  return workerCall(path, signal, { t }).then(done);
}
/**
 * Keep the whole match in this browser (its pack: timeline-pack.js), so seeks,
 * scrubbing and playback stop asking the server for views. Only a finished
 * match has one; `t` is where to start downloading from. Safe to call again
 * (every frame): true the first time it starts.
 */
let packStarted = false, packTries = 0, packTriedAt = 0;
export function startPack(t) {
  if (settings.localTimeline === false) return false;
  if (packStarted) {
    // The index did not arrive (the store is still off a while later): ask
    // again, a few times. A server without packs answers each time the same.
    // While the server is still building the pack it is asked every 20 s, for
    // as long as that takes (a long team game: minutes, once).
    if (packStatus.state !== 'off' || performance.now() - packTriedAt < (packStatus.building ? 20000 : 10000)) return false;
    if (!packStatus.building && packTries >= 3) return false;
  }
  if (!workerTried) startViewWorker();
  if (!viewWorker) return false;
  const first = !packStarted;
  packStarted = true; packTries++; packTriedAt = performance.now();
  viewWorker.postMessage({ pack: viewRequestUrl('/api/pack', location.href), t, always: settings.localTimeline === 'always' });
  return first;
}
/** Another match was opened in this page: its views are not the pack's. The
 * worker is replaced (requests under way are rejected and asked again). */
export function resetPack() {
  if (!packStarted) return;
  packStarted = false; packTries = 0;
  Object.assign(packStatus, { state: 'off', chunks: 0, have: 0, bytes: 0, key: null, building: false });
  if (viewWorker) viewWorker.terminate();
  viewWorker = null; workerTried = false;
  for (const call of workerCalls.values()) call.reject(new Error('view worker replaced'));
  workerCalls.clear();
}
/** The playhead jumped to `t`: the pack downloads from there on. */
export function packFocus(t) {
  if (packStarted && viewWorker && packStatus.state === 'ready') viewWorker.postMessage({ focus: t });
}
/**
 * The forest ('trees') or terrain snapshot in force at `t`: { t, bytes, kinds }
 * (the tile bytes of /api/trees or /api/terrain), or null when there is none.
 * From the pack when it is held, else from the server.
 */
export async function fetchTiles(kind, t) {
  const path = `/api/${kind}?t=${Math.round(t)}`;
  if (!workerTried) startViewWorker();
  if (viewWorker) {
    try { return await workerCall(path, null, { t: Math.round(t), tiles: kind }); } catch { /* the worker failed: ask here */ }
  }
  const r = await api(path);
  if (!r || !r.tiles) return null;
  return { t: r.t, bytes: Uint8Array.from(atob(r.tiles), (c) => c.charCodeAt(0)), kinds: r.kinds || [] };
}
export function fetchView(t) { return viewCache.fetch(t); }
/** The view of `t` if the pack holds it (no request is made for it), else null.
 * Not kept in the view cache: playback takes a cached view up to 3 s old as the
 * current one, and a lone view from here must never stand in for the moment. */
export function fetchLocalView(t) {
  if (!packStarted || !viewWorker || (packStatus.state !== 'ready' && packStatus.state !== 'complete')) return Promise.resolve(null);
  return workerCall(`/api/view?t=${t}`, viewAbort.signal, { t, localOnly: true }).catch(() => null);
}
export function cachedView(t) { return viewCache.peek(t); }
export function cachedViewAt(t) { return viewCache.at(t); }
export function clearViewCache() { viewCache.clear(); }

// -- tooltips ---------------------------------------------------------------------
// Two independent tooltip flags, icon names and detailed help
// (settings.tooltipShowMode). tooltipLevel() folds them into one word:
// 'detailed' (both), 'names', 'detail' (help without the name) or 'off'.
export function tooltipLevel() {
  const m = settings.tooltipShowMode;
  const flags = Array.isArray(m) ? m : ['iconNames', 'detailedHelp'];
  const names = flags.includes('iconNames'), help = flags.includes('detailedHelp');
  return names && help ? 'detailed' : names ? 'names' : help ? 'detail' : 'off';
}
// Every title= in the UI goes through tip(name, detail). Returns an attribute string.
export function tip(name, detail = '') {
  const mode = tooltipLevel();
  if (mode === 'off') return '';
  const text = mode === 'detailed' && detail ? `${name}${name ? ' — ' : ''}${detail}`
    : mode === 'detail' ? (detail || name) : name;
  // data-tip: already translated by the caller, so translateStatic() must not look it up again.
  return text ? `title="${esc(text)}" data-tip` : '';
}

// -- formatting -----------------------------------------------------------------

export function fmtTime(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = h ? String(m).padStart(2, '0') : String(m);
  return (h ? h + ':' : '') + mm + ':' + String(sec).padStart(2, '0');
}

export function fmtNum(n) {
  if (n == null || Number.isNaN(n)) return '–';
  const a = Math.abs(n);
  if (a >= 10000) { const k = n / 1000; return (Math.abs(k) >= 99.95 ? k.toFixed(0) : k.toFixed(1)) + 'k'; }
  return String(Math.round(n));
}
/** A stockpile as the game shows it: whole units, rounded down (499.6 food is not 500). */
export function fmtStock(n) {
  return n == null || Number.isNaN(n) ? '–' : fmtNum(Math.floor(n));
}

export { AGE_NAMES } from './games.js';
import { AGE_NAMES as AGE_LIST } from './games.js';
export const RES = ['food', 'wood', 'gold', 'stone'];

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// -- players & colours ------------------------------------------------------------

const BASE_COLORS = ['#0000ff', '#ff0000', '#04a514', '#d7d71e', '#7ef2e1', '#960ffa', '#636770', '#ff9605'];
const TEAM_COLORS = ['#3b7dd8', '#d84b3b', '#4bb34b', '#d8c33b', '#3bc2d8', '#a43bd8', '#8a8f96', '#e08a2e'];

export function players() {
  return Object.values(S.match.players || {})
    .filter((p) => p.id > 0)
    .sort((a, b) => a.id - b.id);
}

export function player(pid) { return (S.match.players || {})[pid]; }

// Name resolution: casting override, then the world player name;
// no owner is "Gaia", an id that resolves to no player is "Unknown".
/** The player's display name; ``plain`` skips the civilisation added to tell two
 *  players with the same name apart (for places that show the civ next to it). */
export function playerName(pid, plain = false) {
  const o = settings.playerNames[pid];
  if (o) return o;
  if (pid === 0) return t('Gaia');
  const p = player(pid);
  if (!p || !p.name) return t('Unknown');
  if (plain) return p.name;
  // Two players with one name (two copies of the same AI): add the civilisation,
  // or the player number when that is shared too, so every panel tells them apart.
  const twins = Object.values((S.match && S.match.players) || {}).filter((q) => q && q.id > 0 && q.id !== pid && q.name === p.name && !settings.playerNames[q.id]);
  if (!twins.length) return p.name;
  return twins.some((q) => q.civ_name === p.civ_name) || !p.civ_name ? `${p.name} (P${pid})` : `${p.name} (${p.civ_name})`;
}

// Base colour schemes: one side in cool hues, the other in warm ones
// (settings.baseColorMode 'coldWarm' = left team cool, 'warmCold' = reversed).
const COLD_COLORS = ['#2f6fe0', '#25b9cf', '#3fae5a', '#8a63e8'];
const WARM_COLORS = ['#e2412f', '#f08a1c', '#e8c21e', '#d8459c'];

// playerColor runs per drawn entity, so the scheme is computed once per change.
const schemeCache = { key: '', match: null, colors: {} };
function baseSchemeColor(p) {
  const mode = settings.baseColorMode;
  if (mode !== 'coldWarm' && mode !== 'warmCold') return null;
  const key = `${mode}|${sidesFlipped()}`;
  if (schemeCache.key !== key || schemeCache.match !== S.match) {
    schemeCache.key = key; schemeCache.match = S.match; schemeCache.colors = {};
    const ts = sideTeams();
    ts.forEach((tm, ti) => {
      // Two teams: left side vs right side. More teams: alternate cool/warm.
      const pal = ((ti % 2 === 0) === (mode === 'coldWarm')) ? COLD_COLORS : WARM_COLORS;
      const mates = ts.filter((_, i) => i % 2 === ti % 2).flatMap((x) => x.players);
      for (const q of tm.players) schemeCache.colors[q.id] = pal[mates.indexOf(q) % pal.length];
    });
  }
  return schemeCache.colors[p.id] || null;
}

// Skin option standardColorOverrides [{id, key, color}]: `id` names a
// game colour (gameBlue … gameOrange, gameGaia), `key` which of its shades. Vantage reads
// primary (the player colour), primaryBright (text on dark panels) and minimap; the
// rest (secondary, dark, fade, minimapDark, iconMultiply) are accepted but not used.
const GAME_COLOR_IDS = ['gameBlue', 'gameRed', 'gameGreen', 'gameYellow', 'gameTeal', 'gamePink', 'gameGrey', 'gameOrange'];
let colorSrc = null;
let colorMap = new Map();
function skinColor(pid, key, colorId) {
  const list = S.skin && S.skin.options ? S.skin.options.standardColorOverrides : null;
  if (!Array.isArray(list) || !list.length) return null;
  if (list !== colorSrc) {
    colorSrc = list;
    colorMap = new Map();
    for (const o of list) if (o && typeof o.color === 'string') colorMap.set(`${o.id}|${o.key}`, o.color); // later wins
  }
  const id = pid === 0 ? 'gameGaia' : GAME_COLOR_IDS[(colorId ?? 0) % 8];
  return colorMap.get(`${id}|${key}`) || null;
}

export function playerColor(pid, key = 'primary') {
  if (pid === 0 || pid == null) return skinColor(0, key) || '#c8c8c8';
  const p = player(pid);
  if (S.colorOverride[pid] != null) return skinColor(pid, key, S.colorOverride[pid]) || BASE_COLORS[S.colorOverride[pid] % 8];
  if (!p) return '#888';
  if (S.colorMode === 'team') {
    const captain = settings.teamCaptains[p.team_key];
    if (captain != null && captain !== pid && S.match.players[captain]) return playerColor(captain);
    if (captain === pid) return baseSchemeColor(p) || p.color;
    const keys = teams().map((t) => t.key);
    return TEAM_COLORS[keys.indexOf(p.team_key) % TEAM_COLORS.length];
  }
  const scheme = baseSchemeColor(p);
  return scheme || skinColor(pid, key, p.color_id) || p.color;
}

// Player colour for marks on the dark panels (bars, strips, chart lines, swatches):
// the game colour itself, lifted towards white only while it is too dark to
// read there. Pure blue (#0000ff) has a tenth of yellow's luminance and all but
// vanished as a thin bar or line; it becomes the lighter blue the game's own
// interface uses. Colours that already read (red, green, yellow...) are untouched.
const markCache = new Map();
export function playerMarkColor(pid) {
  const c = playerColor(pid);
  let out = markCache.get(c);
  if (out) return out;
  const m = /^#([0-9a-f]{6})$/i.exec(c || '');
  if (!m) return c;
  const n = parseInt(m[1], 16);
  let rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  const lin = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  for (let i = 0; i < 12 && lum(rgb) < 0.16; i++) rgb = rgb.map((v) => Math.round(v + (255 - v) * 0.08));
  out = `#${rgb.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
  markCache.set(c, out);
  return out;
}

// Player colour lifted towards white, for text on dark panels.
const PANEL_LUMINANCE = 0.0075; // --panel-solid (#14181e), the lightest ground the names sit on
export function playerTextColor(pid) {
  const bright = skinColor(pid, 'primaryBright', (S.colorOverride[pid] ?? (player(pid) || {}).color_id));
  if (bright) return bright;
  const c = playerColor(pid);
  const n = parseInt(c.slice(1), 16);
  // Lightened towards white until it reads on a dark panel: at least 4.5:1 against
  // the panel background (the game's blue at the old fixed 38 % was 4.15:1).
  const lin = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
  const base = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  let k = 0.38, rgb = base.map((v) => Math.round(v + (255 - v) * k));
  while (k < 0.8 && (lum(rgb) + 0.05) / (PANEL_LUMINANCE + 0.05) < 4.6) { k += 0.04; rgb = base.map((v) => Math.round(v + (255 - v) * k)); }
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
}

export function cyclePlayerColor(pid) {
  const p = player(pid);
  const cur = S.colorOverride[pid] ?? (p ? p.color_id : 0);
  S.colorOverride[pid] = (cur + 1) % 8;
}

export function teams() {
  const by = new Map();
  for (const p of players()) {
    if (!by.has(p.team_key)) by.set(p.team_key, []);
    by.get(p.team_key).push(p);
  }
  return [...by.entries()].map(([key, ps]) => ({ key, players: ps }));
}

// Layout auto-select: twoTeams (two teams, at most 4v4),
// pompeiiTwoTeams (the same in Return of Rome), battleRoyale (the game's
// Battle Royale mode), community (the alternative FFA skin) or ffa.
export function layoutKind() {
  const ts = teams();
  const mode = String(S.match.game_mode ?? S.match.mode ?? '');
  if (/battle\s*royale/i.test(mode)) return 'battleRoyale';
  if (ts.length === 2 && ts.every((tm) => tm.players.length <= 4)) return S.game === 'ror' ? 'pompeiiTwoTeams' : 'twoTeams';
  return settings.useCommunityGameSkin ? 'community' : 'ffa';
}
export function isTwoTeamLayout(kind = layoutKind()) { return kind === 'twoTeams' || kind === 'pompeiiTwoTeams'; }

// -- flip sides (Alt+S), remembered per game ------------------------------------------
// settings.flipSidesByGame[game_id] persists the swap. S.flipSides is the
// session toggle the hotkey flips; every change of it toggles the stored value.
let lastFlipToggle = S.flipSides;
export function gameKey() { return String((S.match && (S.match.game_id || S.match.seed)) || 'default').replace(/\./g, '_'); }
export function sidesFlipped() {
  const by = settings.flipSidesByGame || (settings.flipSidesByGame = {});
  if (S.flipSides !== lastFlipToggle) {
    lastFlipToggle = S.flipSides;
    if (by[gameKey()]) delete by[gameKey()]; else by[gameKey()] = true;
    saveSettings();
  }
  return !!by[gameKey()];
}
export function toggleFlipSides() { S.flipSides = !S.flipSides; return sidesFlipped(); }

// Teams in scoreboard order: in a two-team layout the flip swaps left and right.
export function sideTeams() {
  const ts = teams();
  return ts.length === 2 && sidesFlipped() ? [ts[1], ts[0]] : ts;
}

// Skin option customPlayerInfos [{referenceName, shortName?, icon?, pngIconName?}]: the
// entry whose referenceName is a team's name replaces that name with shortName and
// supplies the team's icon (pngIconName names a skin asset, else a unit icon).
export function customPlayerInfo(refName) {
  const list = S.skin && S.skin.options ? S.skin.options.customPlayerInfos : null;
  return Array.isArray(list) ? list.find((i) => i && i.referenceName === refName) || null : null;
}
export function plainTeamName(team) {
  return settings.teamNames[team.key] || team.players.map((p) => playerName(p.id)).join(' + ');
}
// The displayed name: a skin short name, a custom team name, else the compact
// label (team-names.js). plainTeamName stays the skin lookup key.
export function teamName(team) {
  const plain = plainTeamName(team);
  const info = customPlayerInfo(plain);
  if (info && info.shortName) return info.shortName;
  if (settings.teamNames[team.key]) return settings.teamNames[team.key];
  const ts = teams();
  const i = ts.findIndex((x) => x.key === team.key);
  if (i < 0) return plain;
  return compactTeamLabels(ts.map((x) => x.players.map((p) => playerName(p.id, true))), (n) => t('Team {n}', { n: n + 1 }))[i];
}
/** The full team name for tooltips when the shown one is shortened. */
export function teamFullName(team) { return plainTeamName(team); }
/** A player's label inside its team: its name, or its civ when teammates share the name. */
export function teamMemberLabel(pid) {
  if (settings.playerNames[pid]) return settings.playerNames[pid];
  const p = player(pid);
  const team = p ? teams().find((x) => x.key === p.team_key) : null;
  if (!p || !team) return playerName(pid);
  const m = (q) => ({ id: q.id, name: playerName(q.id, true), civ: q.civ_name || S.catalog.civs?.[q.civ] || '' });
  return memberLabel(m(p), team.players.map(m));
}
export function teamIcon(team) {
  const info = customPlayerInfo(plainTeamName(team));
  if (!info) return '';
  if (info.pngIconName && S.skin.assets && S.skin.assets[info.pngIconName]) return S.skin.assets[info.pngIconName];
  const id = info.icon && info.icon.tag === 'unit' ? info.icon.iconId : null;
  return id != null && id >= 0 ? withAssetVersion(`/icon/unit/${id}.png?g=${S.game}`) : '';
}

// -- catalog helpers ----------------------------------------------------------------

// With an owner, that player's own name and icon for the master at the time
// being watched win (view.owner_units: the Poles' Mill is their Folwark, an
// upgraded Archer is that player's Crossbowman).
// Asked for every entity on the map, every frame: the merged object for a
// player's own variant is built once per (override, catalog entry, names), not
// per call (a spread of the whole catalog entry each time, and its garbage).
const ownUnits = new WeakMap(); // override row or private unit -> { u, names, info }
function ownUnit(source, u, names, build) {
  if (typeof source !== 'object') return build();
  const hit = ownUnits.get(source);
  if (hit && hit.u === u && hit.names === names) return hit.info;
  const info = build();
  ownUnits.set(source, { u, names, info });
  return info;
}
export function unitInfo(mid, owner, entityId, view = S.view) {
  const names = S.catalog.unit_names;
  const privateUnit = entityId != null && view?.entity_units?.[entityId];
  if (privateUnit && privateUnit.owner === owner && privateUnit.master === mid) {
    return ownUnit(privateUnit, null, names, () => ({ ...privateUnit, name: names?.[privateUnit.string_id] ?? privateUnit.name }));
  }
  const u = S.catalog.units[mid] || { name: `#${mid}`, icon: -1, kind: 'other', cls: -1 };
  const own = owner != null && view && view.owner_units && view.owner_units[owner];
  const o = own && own[mid];
  if (!o) return u;
  return ownUnit(o, u, names, () => ({ ...u, name: (names && names[o[0]]) || u.name, icon: o[1], string_id: o[0] }));
}
export function techInfo(tid) { return S.catalog.techs[tid] || { name: `Tech ${tid}`, icon: -1, time: 0 }; }

export function entityInfo(row, view = S.view) { return unitInfo(row[2], row[1], row[0], view); }

export function unitIcon(mid, owner, entityId) {
  const u = unitInfo(mid, owner, entityId);
  if (u.icon < 0) return '';
  return withAssetVersion(`/icon/${u.kind === 'building' ? 'building' : 'unit'}/${u.icon}.png?g=${S.game}`);
}
// A response without a validity interval (a server older than these pages) is
// refreshed once a second; in between it stands while the clock is within one
// refresh at ×8 of its query, so playback does not blank the panel each frame.
const LEGACY_STATS_SLACK_MS = 10000;
export function legacyStatsFresh(queriedAt, at) {
  return Number.isFinite(queriedAt) && Math.abs(at - queriedAt) <= LEGACY_STATS_SLACK_MS;
}

// Effective Master numbers only: activity/combat counters retain their ordinary
// 1Hz refresh. A future/rewound/private-reset boundary never reuses stale stats.
export function entityStatsValid(data, id, row, at, generation, queriedAt) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return false;
  if (data.generation != null && data.generation !== generation) return false;
  if (row && (data.owner !== row[1] || data.master !== row[2])) return false;
  if (data.entity_stats_validity_version == null) return legacyStatsFresh(queriedAt, at);
  return data.entity_stats_validity_version === 1 && data.generation === generation
    && data.entity_id === id && Number.isInteger(data.valid_from_ms)
    && Number.isInteger(data.valid_until_ms) && data.valid_from_ms <= at && at < data.valid_until_ms;
}

// Playing forward, the clock leaves a bounded response's interval (a live game
// bounds it at the newest data it had) a moment before the refetch lands: the
// kills, deaths and idle time of the same unit stay up meanwhile instead of
// blanking. Rewinding, a far jump, a converted unit or another game never reuse it.
const FORWARD_STATS_SLACK_MS = 5000;
export function entityStatsUsable(data, id, row, at, generation, queriedAt) {
  if (entityStatsValid(data, id, row, at, generation, queriedAt)) return true;
  return !!data && data.entity_stats_validity_version === 1 && data.generation === generation
    && data.entity_id === id && (!row || (data.owner === row[1] && data.master === row[2]))
    && Number.isInteger(data.valid_from_ms) && Number.isInteger(data.valid_until_ms)
    && at >= data.valid_from_ms && at - data.valid_until_ms < FORWARD_STATS_SLACK_MS;
}

export function techIcon(tid) {
  const t = techInfo(tid);
  return t.icon >= 0 ? withAssetVersion(`/icon/tech/${t.icon}.png?g=${S.game}`) : '';
}
// -- antiquity civs (catalog civ_eras / eras: eras.json TechDisplayOverrides) ---------

export function civEra(civ) {
  const m = S.catalog.civ_eras;
  return (m && civ != null && (m[civ] ?? m[String(civ)])) || 'base';
}
function eraOverrides(pid) {
  const p = pid != null ? player(pid) : null;
  if (!p) return null;
  const era = civEra(p.civ);
  return era !== 'base' && S.catalog.eras ? S.catalog.eras[era] || null : null;
}
// A tech's name and icon as the player's civ shows them (antiquity overrides).
export function techInfoFor(tid, pid) {
  const base = techInfo(tid);
  const o = eraOverrides(pid);
  const ov = o && o.techs ? o.techs[tid] ?? o.techs[String(tid)] : null;
  if (!ov) return base;
  return { ...base, name: ov.name || base.name, icon: has0(ov.icon) ? ov.icon : base.icon, help: ov.description || base.help };
}
export function techIconFor(tid, pid) {
  const ti = techInfoFor(tid, pid);
  return ti.icon >= 0 ? withAssetVersion(`/icon/tech/${ti.icon}.png?g=${S.game}`) : '';
}
function has0(v) { return v !== undefined && v !== null && v !== ''; }
// Age names: Archaic/Civic/Classical/Imperial for antiquity civs.
export function ageName(age, pid) {
  const o = eraOverrides(pid);
  const a = o && Array.isArray(o.ages) ? o.ages[age] : null;
  if (a && a.name) return a.name;
  return t(`${AGE_LIST[age] || ''} Age`);
}
export function ageIcon(age, pid) {
  const o = eraOverrides(pid);
  const a = o && Array.isArray(o.ages) ? o.ages[Math.max(0, Math.min(age, o.ages.length - 1))] : null;
  if (a && typeof a.shield === 'string' && /^(\/|https?:)/.test(a.shield)) return a.shield;
  if (a && typeof a.icon === 'string' && /^(\/|https?:)/.test(a.icon)) return a.icon;
  return `/ui/age-${Math.max(1, Math.min(4, age + 1))}.png`;
}

export function emblem(civ) { return civ == null ? '' : withAssetVersion(`/emblem/${civ}.png`); }

export function playerStats(pid) {
  return S.view && S.view.players ? S.view.players[pid] : null;
}

// -- merged user skins (several enabled skins; options OR-ed, lists
// concatenated, later assets override earlier ones) ------------------------------------
// S.skin = {options, assets, stylesheets} for settings.enabledSkins (or the older
// single settings.skin = 'user:<name>'). Refreshed when the enabled list changes
// or on document event 'vantage:skins' (live reload).
S.skin = { options: {}, assets: {}, stylesheets: [] };
let skinKey = null;
export function enabledSkinNames() {
  const list = Array.isArray(settings.enabledSkins) ? settings.enabledSkins.filter(Boolean).map(String) : [];
  if (!list.length && typeof settings.skin === 'string' && settings.skin.startsWith('user:')) list.push(settings.skin.slice(5));
  return list;
}
function mergeSkins(rows) {
  const out = { options: {}, assets: {}, stylesheets: [] };
  for (const r of rows) {
    for (const [k, v] of Object.entries(r.options || {})) {
      if (typeof v === 'boolean') out.options[k] = !!out.options[k] || v;
      else if (Array.isArray(v)) out.options[k] = [...(out.options[k] || []), ...v];
      else if (v != null) out.options[k] = v;
    }
    Object.assign(out.assets, r.assets || {});
    out.stylesheets.push(...(r.stylesheets || (r.css_url ? [r.css_url] : [])));
  }
  return out;
}
export async function refreshSkinState(force = false) {
  const names = enabledSkinNames();
  const key = names.join('|');
  if (!force && key === skinKey) return S.skin;
  skinKey = key;
  if (!names.length) { S.skin = { options: {}, assets: {}, stylesheets: [] }; return S.skin; }
  let merged = await api(`/api/skins/merged?enabled=${encodeURIComponent(names.join(','))}`).catch(() => null);
  if (!merged || typeof merged !== 'object' || Array.isArray(merged)) {
    const rows = await api('/api/skins').catch(() => []);
    const by = new Map((Array.isArray(rows) ? rows : []).map((r) => [String(r.name), r]));
    merged = mergeSkins(names.map((n) => by.get(n)).filter(Boolean));
  }
  S.skin = { options: merged.options || {}, assets: merged.assets || {}, stylesheets: merged.stylesheets || [] };
  return S.skin;
}
export function skinOption(name) {
  if (skinKey !== enabledSkinNames().join('|')) refreshSkinState();
  return (S.skin.options || {})[name];
}
export function skinAsset(key) { return (S.skin.assets || {})[key] || null; }
if (typeof document !== 'undefined') document.addEventListener('vantage:skins', () => { refreshSkinState(true); });

// -- toast ------------------------------------------------------------------------

let toastTimer = null;
export function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 1600);
}

// Dedicated workers can bypass a page service worker. Scope their requests
// explicitly; a shared-origin match cookie belongs to whichever tab opened last.
export function viewRequestUrl(path, href) {
  const base = new URL(href), match = base.pathname.match(/^\/v\/m[a-z2-7]{12}(?=\/|$)/);
  return new URL(match ? match[0] + path : path, base).href;
}
