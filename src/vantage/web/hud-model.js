// The HUD model: presets, the per-preset edits, the share hash, the choice of
// the first preset and the layout schema (anchors and fractions). Pure data and
// functions with no DOM and no imports, so every rule here is unit-tested
// (tests/hud_model.test.mjs). layout.js applies it to the page.

export const HUD_VERSION = 2;

/** Every panel the HUD can show: id, its two-letter code in a share hash. */
export const PANEL_CODES = {
  scoreboard: 'sb', pulse: 'pu', overview: 'tb', techs: 'te', production: 'pr', dashboard: 'da', events: 'ev',
  unitpanel: 'se', timebar: 'tc', minimap: 'mm', focus: 'fo', ticker: 'et', selchip: 'sc', reviewcards: 'rc',
  story: 'st', 'w-army': 'wa', 'w-vil': 'wv', 'w-bank': 'wb', 'w-idletc': 'wi', 'w-kd': 'wk', 'w-eapm': 'we',
  'w-chart': 'wc', 'w-text': 'wt', 'w-series': 'ws',
};
const PANEL_BY_CODE = Object.fromEntries(Object.entries(PANEL_CODES).map(([id, code]) => [code, id]));

/** The Pulse strip's metrics, in display order: id -> code in a share hash. */
export const PULSE_METRICS = ['age', 'vil', 'mil', 'army', 'idle', 'pop', 'bank', 'rate', 'banksum', 'ratesum', 'kd', 'score', 'eapm'];
/** What the strip itself prints for a metric, where that is not the start of its name. */
export const PULSE_METRIC_SHORT = { banksum: 'Bank', ratesum: '/min', kd: 'K / L', rate: '+n/min', pop: 'Pop', army: 'Army', vil: 'Vil', mil: 'Mil', idle: 'Idle' };
export const PULSE_METRIC_LABELS = {
  age: 'Age', vil: 'Villagers', mil: 'Military', army: 'Army value', idle: 'Idle villagers', pop: 'Population',
  bank: 'Banked resources', rate: 'Collection rate beside each resource', banksum: 'Banked, total', ratesum: 'Collection rate, total',
  kd: 'Kills / Losses', score: 'Score', eapm: 'eAPM',
};

/**
 * The stock presets. Full has no panel list: it is the HUD exactly as the
 * settings describe it (the legacy show/hide flags), so nothing a preset does
 * can change it. `auto`: panels that appear by themselves (time controls near
 * the bottom edge or while paused).
 */
export const PRESETS = {
  minimal: { label: 'Minimal', action: 'hudPresetMinimal', detail: 'The Pulse strip and the minimap',
    panels: ['pulse', 'selchip', 'minimap'], auto: ['timebar'],
    metrics: ['age', 'vil', 'mil', 'army', 'idle', 'pop', 'bank', 'rate'] },
  caster: { label: 'Caster', action: 'hudPresetCaster', detail: 'Pulse strip, one Focus card, key events and the minimap',
    panels: ['pulse', 'focus', 'ticker', 'selchip', 'minimap'], auto: ['timebar'],
    metrics: ['age', 'vil', 'mil', 'army', 'idle', 'pop', 'bank', 'rate'] },
  review: { label: 'Review', action: 'hudPresetReview', detail: 'Mistake cards, the Match story timeline and the Selection panel',
    panels: ['pulse', 'reviewcards', 'story', 'unitpanel', 'minimap'], auto: [],
    metrics: ['age', 'vil', 'army', 'idle', 'banksum', 'ratesum'] },
  analyst: { label: 'Analyst', action: 'hudPresetAnalyst', detail: 'Tables: Scoreboard, Team board, Dashboard and Statistics docked right',
    panels: ['scoreboard', 'overview', 'dashboard', 'unitpanel', 'timebar', 'minimap'], auto: [],
    metrics: ['age', 'vil', 'mil', 'army', 'idle', 'pop', 'bank', 'rate'], stats: 'dock' },
  full: { label: 'Full', action: 'hudPresetFull', detail: 'Every panel, as your settings have them',
    panels: null, auto: [], metrics: ['age', 'vil', 'mil', 'army', 'idle', 'pop', 'bank', 'rate'] },
};
export const PRESET_ORDER = ['minimal', 'caster', 'review', 'analyst', 'full'];
/** A preset made from a share link whose panels match no stock preset. */
export const CUSTOM = 'custom';

export const SCENES = [['game', 'In-game'], ['fight', 'Fight'], ['break', 'Break'], ['post', 'Post-game']];
const SCENE_IDS = SCENES.map(([id]) => id);

export function defaultHud() {
  return {
    v: HUD_VERSION,
    preset: 'full',
    edits: {},          // preset -> { panels?: [ids], metrics?: [ids] }: only what differs from stock
    hintSeen: false,    // the first-run presets hint was shown
    lock: false,        // panels move and resize only in Edit layout
    focus: 'production', // the Focus slot's card: production | eco | fight | none
    sceneHide: {},      // panel id -> scenes it is hidden in
    scene: 'auto',      // auto, or a scene forced by hand
    snap: true, safeArea: false, // layout editor options
    reserved: null,     // a zone panels keep out of (the webcam): { x, y, w, h } as fractions
    hiddenRows: [],     // Team board rows (metric ids) ticked off in Customize
    dedupe: false,      // drop the dashboard Overview columns the Team board already shows
    widgets: {},        // widget id -> its content ({ series }, { text, image })
    layouts: {},        // name -> a saved layout (snapshotLayout)
    layoutName: '',
    drawerLeft: false,  // the Customize drawer on the left edge (it covers what is under it)
    link: '',           // the share link the viewer last made their own (not re-applied over their changes)
  };
}

const uniq = (list) => [...new Set(list)];
const idList = (v, allowed) => (Array.isArray(v) ? uniq(v.filter((x) => typeof x === 'string' && allowed(x))) : null);
const isPanel = (id) => Object.prototype.hasOwnProperty.call(PANEL_CODES, id);
const isMetric = (id) => PULSE_METRICS.includes(id);
const isPreset = (id) => id === CUSTOM || Object.prototype.hasOwnProperty.call(PRESETS, id);

/** A saved or shared HUD object made safe: unknown ids dropped, missing keys defaulted. */
export function normalizeHud(raw) {
  const base = defaultHud();
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return base;
  const out = { ...base };
  if (isPreset(raw.preset)) out.preset = raw.preset;
  if (raw.edits && typeof raw.edits === 'object') {
    for (const [name, e] of Object.entries(raw.edits)) {
      if (!isPreset(name) || !e || typeof e !== 'object') continue;
      const panels = idList(e.panels, isPanel), metrics = idList(e.metrics, isMetric);
      const edit = { ...(panels ? { panels } : {}), ...(metrics ? { metrics } : {}) };
      if (Object.keys(edit).length) out.edits[name] = edit;
    }
  }
  if (out.preset === CUSTOM && !out.edits[CUSTOM]) out.preset = 'full';
  for (const key of ['hintSeen', 'lock', 'snap', 'safeArea', 'dedupe', 'drawerLeft']) if (typeof raw[key] === 'boolean') out[key] = raw[key];
  if (['production', 'eco', 'fight', 'none'].includes(raw.focus)) out.focus = raw.focus;
  // The research card was removed (the Live research panel shows the same): its slot shows fights.
  else if (raw.focus === 'techs') out.focus = 'fight';
  if (raw.scene === 'auto' || SCENE_IDS.includes(raw.scene)) out.scene = raw.scene;
  if (raw.sceneHide && typeof raw.sceneHide === 'object') {
    for (const [id, scenes] of Object.entries(raw.sceneHide)) {
      const list = idList(scenes, (s) => SCENE_IDS.includes(s));
      if (isPanel(id) && list && list.length) out.sceneHide[id] = list;
    }
  }
  const z = raw.reserved;
  if (z && [z.x, z.y, z.w, z.h].every((n) => typeof n === 'number' && Number.isFinite(n))) {
    out.reserved = { x: clamp01(z.x), y: clamp01(z.y), w: clamp01(z.w), h: clamp01(z.h) };
  }
  out.hiddenRows = idList(raw.hiddenRows, () => true) || [];
  if (raw.widgets && typeof raw.widgets === 'object' && !Array.isArray(raw.widgets)) out.widgets = { ...raw.widgets };
  if (raw.layouts && typeof raw.layouts === 'object' && !Array.isArray(raw.layouts)) out.layouts = { ...raw.layouts };
  if (typeof raw.layoutName === 'string') out.layoutName = raw.layoutName.slice(0, 40);
  if (typeof raw.link === 'string') out.link = raw.link.slice(0, 400);
  return out;
}

function clamp01(n) { return Math.max(0, Math.min(1, n)); }

/**
 * The preset a viewer starts on. Saved settings always win (an existing setup
 * keeps Full, today's HUD); a link (?hud= or #hud=) picks for this visit; a
 * new viewer gets Minimal when the viewer is hosted (a hub embed or a hub
 * match page) or on a phone (a narrow touch screen), and Full in the desktop app.
 */
export function initialPreset({ hasSaved = false, savedPreset = null, embedded = false, hosted = false, phone = false, requested = null } = {}) {
  if (requested && isPreset(requested) && requested !== CUSTOM) return requested;
  if (hasSaved) return isPreset(savedPreset) ? savedPreset : 'full';
  // Full has no phone layout: on a narrow touch screen it would be cut off at both edges.
  return embedded || hosted || phone ? 'minimal' : 'full';
}

// -- panels and metrics of a preset ------------------------------------------------------------

/** The panels a preset shows (null for Full without edits: the legacy flags decide). */
export function presetPanels(hud, name) {
  const edit = hud.edits && hud.edits[name];
  if (edit && edit.panels) return edit.panels;
  const stock = PRESETS[name];
  return stock ? stock.panels : [];
}
export function presetMetrics(hud, name) {
  const edit = hud.edits && hud.edits[name];
  if (edit && edit.metrics) return edit.metrics;
  return (PRESETS[name] || PRESETS.minimal).metrics;
}
/** True when a preset differs from its stock definition (the dot in Customize). */
export function presetChanged(hud, name) { return !!(hud.edits && hud.edits[name]); }

const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

/** hud with one preset's panel list replaced; an edit equal to stock is dropped. */
export function withPanels(hud, name, panels) {
  const stock = PRESETS[name], list = uniq(panels.filter(isPanel));
  const edit = { ...((hud.edits || {})[name] || {}) };
  // Full keeps no list of its own panels (the settings flags decide them): its
  // edit lists only the newer panels switched on beside them.
  if (stock && !stock.panels ? !list.length : stock && sameSet(stock.panels, list)) delete edit.panels; else edit.panels = list;
  return withEdit(hud, name, edit);
}
export function withMetrics(hud, name, metrics) {
  const stock = PRESETS[name] || PRESETS.minimal, list = PULSE_METRICS.filter((m) => metrics.includes(m));
  const edit = { ...((hud.edits || {})[name] || {}) };
  if (sameSet(stock.metrics, list)) delete edit.metrics; else edit.metrics = list;
  return withEdit(hud, name, edit);
}
function withEdit(hud, name, edit) {
  const edits = { ...(hud.edits || {}) };
  if (Object.keys(edit).length) edits[name] = edit; else delete edits[name];
  return { ...hud, edits };
}
/** hud with one preset back to its stock definition. */
export function restorePreset(hud, name) { return withEdit(hud, name, {}); }

// -- the share hash ------------------------------------------------------------------------------
//
//   #hud=caster                 a stock preset
//   #hud=caster.fight           ... in one scene (an OBS scene's browser source)
//   #hud=c1.pu-fo-mm.age-vil    a custom HUD: panels, then Pulse metrics
//   #hud=c1.pu-fo-mm.age-vil.fight
//   #layout=Name                a saved layout (with positions) by name; may be combined: #hud=caster.fight&layout=Name
//
// Short codes and no positions, so a link stays well under 120 characters.

/** The hash value for the active HUD (without '#hud='). fullPanels: the visible panels when the preset is Full. */
export function encodeHud(hud, { scene = null, fullPanels = null } = {}) {
  const name = hud.preset, tail = scene && SCENE_IDS.includes(scene) ? `.${scene}` : '';
  if (name !== CUSTOM && !presetChanged(hud, name) && !(name === 'full' && fullPanels)) return `${name}${tail}`;
  const panels = (name === 'full' ? fullPanels : presetPanels(hud, name)) || [];
  const codes = panels.filter(isPanel).map((id) => PANEL_CODES[id]);
  return `c1.${codes.join('-') || '0'}.${presetMetrics(hud, name).join('-') || '0'}${tail}`;
}

/** Parse a hash value: { preset, panels?, metrics?, scene? } or null when it is not a HUD link. */
export function decodeHud(value) {
  if (typeof value !== 'string' || !value || value.length > 400) return null;
  const parts = value.trim().toLowerCase().split('.');
  let scene = null;
  if (parts.length > 1 && SCENE_IDS.includes(parts[parts.length - 1])) scene = parts.pop();
  if (parts[0] === 'c1') {
    if (parts.length !== 3) return null;
    const panels = parts[1] === '0' ? [] : uniq(parts[1].split('-').map((c) => PANEL_BY_CODE[c]).filter(Boolean));
    const metrics = parts[2] === '0' ? [] : PULSE_METRICS.filter((m) => parts[2].split('-').includes(m));
    // A custom HUD that equals a stock preset is that preset.
    const stock = PRESET_ORDER.find((n) => PRESETS[n].panels && sameSet(PRESETS[n].panels, panels) && sameSet(PRESETS[n].metrics, metrics));
    return stock ? { preset: stock, scene } : { preset: CUSTOM, panels, metrics, scene };
  }
  if (parts.length !== 1 || !Object.prototype.hasOwnProperty.call(PRESETS, parts[0])) return null;
  return { preset: parts[0], scene };
}

/** The key=value pairs of a location hash ('#hud=caster&layout=Cast'). */
export function parseHash(hash) {
  const out = {};
  for (const pair of String(hash || '').replace(/^#/, '').split('&')) {
    const i = pair.indexOf('=');
    if (i <= 0) continue;
    try { out[decodeURIComponent(pair.slice(0, i))] = decodeURIComponent(pair.slice(i + 1)); } catch { /* a malformed escape: skip the pair */ }
  }
  return out;
}

/** hud with a decoded link applied (the link's preset becomes the active one; its scene is the caller's to hold, never saved). */
export function applyDecoded(hud, decoded) {
  if (!decoded) return hud;
  let next = { ...hud, preset: decoded.preset };
  if (decoded.preset === CUSTOM) next = { ...next, edits: { ...(hud.edits || {}), [CUSTOM]: { panels: decoded.panels, metrics: decoded.metrics } } };
  return next;
}

// -- layout schema v2: anchors and fractions -------------------------------------------------------
//
// A placed panel is stored as an anchor (which corner or edge of the window it
// holds on to) and fractions of the window, so a layout made at 2560x1440
// lands in the same place in a 1920x1080 OBS source:
//   { anchor: 'br', x, y, w, h, moved?, auto?, scale?, opacity? }
// x, y: the gap between the panel and its anchor edges, as a fraction of the
// window; w, h: its size as a fraction of the window. Rectangles saved by
// older builds ({left, top, width, height} in pixels) are converted on load.

export const ANCHORS = ['tl', 't', 'tr', 'l', 'c', 'r', 'bl', 'b', 'br'];
const r5 = (n) => Math.round(n * 1e5) / 1e5;
const FLAGS = ['moved', 'auto', 'fixed']; // fixed: the anchor was chosen by hand and stays

export function isAnchored(rect) { return !!rect && typeof rect.anchor === 'string' && typeof rect.w === 'number'; }

/** The anchor nearest to a pixel rectangle: the third of the window its centre is in. */
export function nearestAnchor(rect, viewport) {
  const cx = (rect.left + rect.width / 2) / viewport.width, cy = (rect.top + rect.height / 2) / viewport.height;
  const col = cx < 1 / 3 ? 0 : cx > 2 / 3 ? 2 : 1, row = cy < 1 / 3 ? 0 : cy > 2 / 3 ? 2 : 1;
  return ANCHORS[row * 3 + col];
}

function extras(rect) {
  const out = {};
  for (const f of FLAGS) if (rect[f]) out[f] = true;
  if (typeof rect.scale === 'number' && rect.scale !== 1) out.scale = rect.scale;
  if (typeof rect.opacity === 'number' && rect.opacity !== 1) out.opacity = rect.opacity;
  return out;
}

/**
 * The corner a natural-size panel holds on to: the half of the window its
 * centre is in, never the middle. Its content changes height from one moment
 * (or one selection) to the next; anchored to a corner, one edge stays where
 * the viewer put it and the panel grows away from it. Anchored to the centre,
 * both edges would move.
 */
export function cornerAnchor(rect, viewport) {
  const cx = (rect.left + rect.width / 2) / viewport.width, cy = (rect.top + rect.height / 2) / viewport.height;
  return `${cy <= 0.5 ? 't' : 'b'}${cx <= 0.5 ? 'l' : 'r'}`;
}

/** A pixel rectangle as an anchored one (anchor: keep this anchor; default: the nearest, a corner for a natural-size panel). */
export function toAnchored(rect, viewport, anchor = null) {
  const a = ANCHORS.includes(anchor) ? anchor : rect.auto ? cornerAnchor(rect, viewport) : nearestAnchor(rect, viewport);
  const W = viewport.width || 1, H = viewport.height || 1;
  const right = W - rect.left - rect.width, bottom = H - rect.top - rect.height;
  const x = a.includes('l') ? rect.left : a.includes('r') ? right : rect.left + rect.width / 2 - W / 2;
  const y = a.includes('t') ? rect.top : a.includes('b') ? bottom : rect.top + rect.height / 2 - H / 2;
  return { anchor: a, x: r5(x / W), y: r5(y / H), w: r5(rect.width / W), h: r5(rect.height / H), ...extras(rect) };
}

/** An anchored rectangle in pixels for a window size (a legacy pixel rectangle passes through). */
export function fromAnchored(rect, viewport, size = null) {
  if (!isAnchored(rect)) return rect;
  const W = viewport.width, H = viewport.height, a = rect.anchor;
  // size: the panel's own size when it keeps its natural one (auto), so its
  // anchored edge, not its top-left corner, is what stays put.
  const width = size ? size.width : rect.w * W, height = size ? size.height : rect.h * H;
  const left = a.includes('l') ? rect.x * W : a.includes('r') ? W - rect.x * W - width : W / 2 + rect.x * W - width / 2;
  const top = a.includes('t') ? rect.y * H : a.includes('b') ? H - rect.y * H - height : H / 2 + rect.y * H - height / 2;
  return { left: Math.round(left), top: Math.round(top), width: Math.round(width), height: Math.round(height), ...extras(rect) };
}

/**
 * Natural-size panels saved on an edge or centre anchor (before they were
 * always corner-anchored) move to the corner anchor, at the place they were
 * dragged to. One whose anchor was chosen by hand keeps it.
 */
export function reanchorAutoPanels(sizes, viewport) {
  const out = {};
  for (const [id, rect] of Object.entries(sizes || {})) {
    const corner = isAnchored(rect) && rect.anchor.length === 2;
    out[id] = isAnchored(rect) && rect.auto && !rect.fixed && !corner ? toAnchored(fromAnchored(rect, viewport), viewport) : rect;
  }
  return out;
}

/** Every saved rectangle in schema v2 (pixel ones converted against this window). */
export function migratePanelSizes(sizes, viewport) {
  const out = {};
  for (const [id, rect] of Object.entries(sizes || {})) {
    if (!rect || typeof rect !== 'object') continue;
    if (isAnchored(rect)) out[id] = rect;
    else if ([rect.left, rect.top, rect.width, rect.height].every((n) => typeof n === 'number' && Number.isFinite(n))) out[id] = toAnchored(rect, viewport);
  }
  return out;
}

// -- the Selection panel's memory (selection-memory.js) ------------------------------------------------

export const SELECTION_DEFAULTS = { open: {}, upgrades: null, scope: 'life', expanded: false };

/** A stored selectionPanel object made safe (unknown shapes dropped). */
export function normalizeSelectionPanel(raw) {
  const out = { ...SELECTION_DEFAULTS, open: {} };
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out;
  if (raw.open && typeof raw.open === 'object' && !Array.isArray(raw.open)) {
    for (const [key, value] of Object.entries(raw.open)) if (typeof value === 'boolean' && key.length <= 40) out.open[key] = value;
  }
  if (typeof raw.upgrades === 'boolean') out.upgrades = raw.upgrades;
  if (raw.scope === 'minute') out.scope = 'minute';
  if (raw.expanded === true) out.expanded = true;
  return out;
}

// -- saved layouts ----------------------------------------------------------------------------------

/** The settings keys that make up a layout (what a saved layout or a profile's layout carries). */
export const LAYOUT_KEYS = ['hud', 'panelSizes', 'panelOrder', 'hudLayout', 'hiddenPanels', 'collapsedPanels',
  'showProduction', 'showDashboard', 'showEvents', 'showStaticTechs', 'disableScoreboard', 'selectionPanel'];

/** A named layout: the layout keys of the settings, without the list of saved layouts itself. */
export function snapshotLayout(settings, name = '') {
  const snap = { vantageLayout: HUD_VERSION, name: String(name).slice(0, 40) };
  for (const key of LAYOUT_KEYS) if (settings[key] !== undefined) snap[key] = JSON.parse(JSON.stringify(settings[key]));
  if (snap.hud) { delete snap.hud.layouts; snap.hud.layoutName = snap.name; }
  return snap;
}

/** The settings patch a saved layout (or a whole settings profile) applies; null when it holds no layout. */
export function layoutPatch(source, current = {}) {
  if (!source || typeof source !== 'object' || Array.isArray(source) || !source.hud) return null;
  const patch = {};
  for (const key of LAYOUT_KEYS) if (source[key] !== undefined) patch[key] = JSON.parse(JSON.stringify(source[key]));
  // The viewer's own saved layouts and first-run state stay; only the layout itself is replaced.
  const mine = current.hud || {};
  patch.hud = { ...normalizeHud(patch.hud), layouts: mine.layouts || {}, hintSeen: !!mine.hintSeen };
  return patch;
}

// -- scenes -------------------------------------------------------------------------------------------

/** The scene in force: a forced one, else post-game, break (nothing open), a fight, or in-game. */
export function activeScene({ forced = 'auto', ended = false, idle = false, fighting = false } = {}) {
  if (SCENE_IDS.includes(forced)) return forced;
  if (idle) return 'break';
  if (ended) return 'post';
  return fighting ? 'fight' : 'game';
}

/** True when kills cluster around `at`: three or more within the last 15 game seconds. */
export function fightAt(killTimes, at, windowMs = 15000, need = 3) {
  let n = 0;
  for (let i = killTimes.length - 1; i >= 0; i--) {
    const t = killTimes[i];
    if (t > at) continue;
    if (t < at - windowMs) break;
    n++;
  }
  return n >= need;
}

// -- stream-safe checks ---------------------------------------------------------------------------------

/** Minimum text sizes on a stream: 18 px values and 14 px labels at 1080p, 16 and 12 at 720p. */
export function minTextPx(viewportHeight) {
  return viewportHeight >= 1000 ? { value: 18, label: 14 } : { value: 16, label: 12 };
}

/** The title-safe frame: 2.5 % in from every edge. */
export function safeFrame(viewport, inset = 0.025) {
  const dx = Math.round(viewport.width * inset), dy = Math.round(viewport.height * inset);
  return { left: dx, top: dy, width: viewport.width - 2 * dx, height: viewport.height - 2 * dy };
}

/**
 * Checks for one placed panel. texts: [{ px, kind: 'value' | 'label' }] (its
 * computed font sizes). Returns [{ ok, text, args }] for the editor's list.
 */
export function streamChecks(rect, viewport, texts = []) {
  const min = minTextPx(viewport.height), out = [];
  const small = texts.filter((x) => x.px < (x.kind === 'value' ? min.value : min.label) - 0.01);
  const smallest = small.length ? Math.min(...small.map((x) => x.px)) : null;
  out.push(small.length
    ? { ok: false, text: 'Text down to {px} px: values need {v} px, labels {l} px', args: { px: Math.round(smallest * 10) / 10, v: min.value, l: min.label } }
    : { ok: true, text: 'Text is at least {v} px (values) and {l} px (labels)', args: { v: min.value, l: min.label } });
  const safe = safeFrame(viewport);
  const out_px = Math.max(safe.left - rect.left, safe.top - rect.top, rect.left + rect.width - safe.left - safe.width, rect.top + rect.height - safe.top - safe.height);
  out.push(out_px > 0.5 ? { ok: false, text: '{px} px outside the safe area', args: { px: Math.round(out_px) } } : { ok: true, text: 'Inside the safe area', args: {} });
  const share = Math.round((100 * rect.width * rect.height) / Math.max(1, viewport.width * viewport.height));
  out.push({ ok: share <= 15, text: 'Covers {n}% of the map', args: { n: share } });
  return out;
}

/** A rectangle moved out of a reserved zone by the shortest way (unchanged when they do not overlap). */
export function avoidZone(rect, zone) {
  if (!zone) return rect;
  const overlapX = Math.min(rect.left + rect.width, zone.left + zone.width) - Math.max(rect.left, zone.left);
  const overlapY = Math.min(rect.top + rect.height, zone.top + zone.height) - Math.max(rect.top, zone.top);
  if (overlapX <= 0 || overlapY <= 0) return rect;
  const moves = [
    { left: zone.left - rect.width, top: rect.top, d: rect.left + rect.width - zone.left },
    { left: zone.left + zone.width, top: rect.top, d: zone.left + zone.width - rect.left },
    { left: rect.left, top: zone.top - rect.height, d: rect.top + rect.height - zone.top },
    { left: rect.left, top: zone.top + zone.height, d: zone.top + zone.height - rect.top },
  ].sort((a, b) => a.d - b.d);
  return { ...rect, left: moves[0].left, top: moves[0].top };
}

/** Round a rectangle's position to a grid (the layout editor's snap grid). */
export function snapToGrid(rect, grid = 8) {
  return { ...rect, left: Math.round(rect.left / grid) * grid, top: Math.round(rect.top / grid) * grid };
}
