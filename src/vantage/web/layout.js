// The HUD layout: which panels show, which are collapsed, the presets
// (Minimal, Caster, Review, Analyst, Full), the scene in force and the
// hold-to-peek state. hud-model.js holds the rules; this module applies them
// to the page. Every panel gets a hover toolbar (name, move, collapse, hide),
// and the Customize drawer (customize.js, loaded on first use) lists them all,
// so a hidden panel is always one click from coming back.
//
// Full is the HUD exactly as the settings describe it: panels whose visibility
// already was a setting (scoreboard, production, dashboard, events) keep that
// setting as the source of truth, the others are listed in
// settings.hiddenPanels. Every other preset has its own panel list
// (settings.hud.edits holds what the viewer changed in it), so switching
// presets never rewrites Full.

import { S, settings, saveSettings, tip } from './state.js';
import { t } from './i18n.js';
import { applyPanelSizes, resetPanelSizes, resetPanel, startMove, nudgePanel, arranging, setArranging } from './panel-resize.js';
import {
  PRESETS as STOCK, PRESET_ORDER, CUSTOM, presetPanels, presetMetrics, presetChanged, withPanels, withMetrics, restorePreset,
  normalizeHud, defaultHud, initialPreset, applyDecoded, decodeHud, parseHash, encodeHud, activeScene, fightAt,
} from './hud-model.js';
import { hudEnvironment } from './state.js';
import { binding } from './hotkeys.js';

const $ = (id) => document.getElementById(id);

// host: the element the toolbar sits on; el: what hiding hides (the minimap
// keeps its button row, which holds the Customize button itself).
// extra: a panel newer than Full's flags; module: loaded when first shown.
export const PANELS = [
  { id: 'scoreboard', label: 'Scoreboard', setting: 'disableScoreboard', inverted: true, action: 'toggleScoreboard' },
  { id: 'pulse', label: 'Pulse strip', extra: true, module: 'pulse', action: 'toggleScoreboard', detail: 'One row per side: age, villagers, military, army value, idle and the bank with its rate' },
  { id: 'overview', label: 'Team board', collapse: true, action: 'toggleOverview' },
  { id: 'techs', label: 'Techs', collapse: true, gate: 'showStaticTechs', action: 'toggleStaticTechnologies' },
  { id: 'production', label: 'Production & composition', setting: 'showProduction', collapse: true, action: 'toggleProduction' },
  { id: 'dashboard', label: 'Dashboard', setting: 'showDashboard', collapse: true, action: 'toggleDashboard' },
  { id: 'events', label: 'Event log', setting: 'showEvents', collapse: true, action: 'toggleEvents' },
  { id: 'unitpanel', label: 'Selection panel', collapse: true, action: 'toggleSelectionPanel' },
  { id: 'timebar', label: 'Time controls', collapse: true, action: 'toggleScrubbingBar' },
  { id: 'minimap', host: 'minimap-wrap', label: 'Minimap' },
  { id: 'focus', label: 'Focus slot', extra: true, module: 'focus-slot', action: 'toggleFocusSlot', detail: 'One card at a time: production, techs, economy or the last fight' },
  { id: 'ticker', label: 'Event ticker', extra: true, module: 'focus-slot', detail: 'Key events only, two lines, fading after 8 seconds' },
  { id: 'selchip', label: 'Selection chip', extra: true, module: 'focus-slot', detail: 'One line for the selection; opens the Selection panel' },
  { id: 'reviewcards', label: 'Review cards', extra: true, module: 'story', detail: 'Six mistake metrics, side against side' },
  { id: 'story', label: 'Match story timeline', extra: true, module: 'story', action: 'toggleStory', detail: 'Lead, age-ups, fights, idle town centres and bookmarks on one time axis, with the playback buttons' },
  { id: 'w-army', label: 'Army value Δ', extra: true, module: 'widgets', widget: 'metric' },
  { id: 'w-vil', label: 'Villagers', extra: true, module: 'widgets', widget: 'metric' },
  { id: 'w-bank', label: 'Bank + rate', extra: true, module: 'widgets', widget: 'metric' },
  { id: 'w-idletc', label: 'Idle TC', extra: true, module: 'widgets', widget: 'metric' },
  { id: 'w-kd', label: 'Kills / Losses', extra: true, module: 'widgets', widget: 'metric' },
  { id: 'w-eapm', label: 'eAPM', extra: true, module: 'widgets', widget: 'metric' },
  { id: 'w-chart', label: 'Chart: any series', extra: true, module: 'widgets', widget: 'chart' },
  { id: 'w-series', label: 'Series score', extra: true, module: 'widgets', widget: 'casting' },
  { id: 'w-text', label: 'Text or image', extra: true, module: 'widgets', widget: 'casting' },
];

export { STOCK as PRESETS, PRESET_ORDER };

const byId = new Map(PANELS.map((p) => [p.id, p]));
const list = (k) => (Array.isArray(settings[k]) ? settings[k] : []);
export function panelInfo(id) { return byId.get(id) || null; }

// -- the HUD object: saved settings, plus a link's choice for this visit ---------------------------

let link = null;        // a decoded #hud= / ?hud= link: applies until the viewer changes the HUD
let linkScene = null;   // the scene a link asks for (an OBS scene's browser source)
let peek = false;       // hold-to-peek: the Full HUD while the key is down
let editorScene = null; // the scene being edited (layout editor)
let selExpanded = false; // the Selection chip was opened into the full Selection panel

/** The HUD in force: the saved one with this visit's link applied. */
export function hud() {
  const saved = settings.hud || defaultHud();
  return link ? applyDecoded(saved, link) : saved;
}

/** Replace the HUD (immutably) and save it. A link's choice becomes the viewer's own once they edit. */
export function setHud(next, { save = true } = {}) {
  link = null;
  settings.hud = normalizeHud(next);
  if (save) saveSettings();
  applyPanels();
  document.dispatchEvent(new CustomEvent('vantage:hud-changed'));
}

/** Read #hud= (and ?hud=) once at start, and again when the hash changes. */
export function readLink() {
  const hash = parseHash(typeof location !== 'undefined' ? location.hash : '');
  const decoded = decodeHud(hash.hud || hudEnvironment().requested || '');
  link = decoded && !(decoded.preset === (settings.hud || {}).preset && !decoded.panels) ? decoded : null;
  linkScene = decoded && decoded.scene ? decoded.scene : null;
  return { decoded, layout: hash.layout || null };
}

export function activePreset() { return peek ? 'full' : hud().preset; }
export function setPeek(on) { if (peek !== !!on) { peek = !!on; applyPanels(); } }
export function peeking() { return peek; }

// -- scenes --------------------------------------------------------------------------------------

let killCache = { events: null, n: 0, times: [] };
function killTimes() {
  if (killCache.events !== S.events || killCache.n !== S.events.length) {
    killCache = { events: S.events, n: S.events.length, times: S.events.filter((e) => e.kind === 'kill' && !e.friendly).map((e) => e.t) };
  }
  return killCache.times;
}
export function setEditorScene(scene) { editorScene = scene; applyPanels(); }
export function scene() {
  const h = hud();
  const forced = editorScene || linkScene || h.scene;
  if (forced && forced !== 'auto') return forced;
  // Auto scenes only matter once a panel is tied to one.
  if (!Object.keys(h.sceneHide || {}).length) return 'game';
  return activeScene({ ended: !!(S.view && S.view.game_ended), idle: !S.session || S.session.mode === 'idle', fighting: fightAt(killTimes(), S.t) });
}

// -- visibility -------------------------------------------------------------------------------------

// The phone layout shows a fixed set: the Pulse strip, the Match story (its
// scrubber and playback buttons), and whichever panel the open tab holds.
const PHONE_PANELS = new Set(['pulse', 'story']);
const PHONE_TABS = { table: 'overview', unit: 'unitpanel' };
let phoneOn = false, tab = 'pulse';
export function phoneTab() { return tab; }
export function setPhoneTab(next) { tab = next; applyPanels(); }

function wanted(id, preset = activePreset()) {
  const p = byId.get(id), h = hud();
  if (phoneOn && preset !== 'full') return PHONE_PANELS.has(id) || PHONE_TABS[tab] === id;
  if (preset === 'full') {
    if (p.extra) return ((h.edits.full || {}).panels || []).includes(id);
    if (p.gate && !settings[p.gate]) return false;
    if (p.setting) return p.inverted ? !settings[p.setting] : !!settings[p.setting];
    return !list('hiddenPanels').includes(id);
  }
  if (id === 'unitpanel' && selExpanded && S.selection.size) return true;
  return (presetPanels(h, preset) || []).includes(id);
}

export function isVisible(id) {
  const p = byId.get(id);
  if (!p) return true;
  const hide = (hud().sceneHide || {})[id];
  if (hide && hide.includes(scene())) return false;
  return wanted(id);
}

/** A panel that appears by itself in this preset (the time controls near the bottom edge). */
export function isAuto(id) {
  const preset = activePreset(), stock = STOCK[preset];
  if (preset === 'full' || phoneOn || wanted(id, preset)) return false;
  // A custom HUD (a shared link) without time controls or the Match story gets them the same way.
  const auto = stock ? stock.auto || [] : wanted('story', preset) ? [] : ['timebar'];
  return auto.includes(id);
}

export function isCollapsed(id) { return list('collapsedPanels').includes(id); }

/** The Selection chip opens the full Selection panel until the selection is cleared. */
export function expandSelection(on) { if (selExpanded !== !!on) { selExpanded = !!on; applyPanels(); } }
export function selectionExpanded() { return selExpanded; }

export function setVisible(id, on) {
  const p = byId.get(id);
  if (!p) return;
  const h = hud(), preset = h.preset;
  if (preset === 'full') {
    if (p.extra) {
      const extras = ((h.edits.full || {}).panels || []).filter((x) => x !== id);
      setHud(withPanels(h, 'full', on ? [...extras, id] : extras));
      return;
    }
    if (p.gate) {
      // The techs grid has its own switch (Alt+T): ticking the panel turns it on too.
      settings[p.gate] = on;
      if (on) settings.hiddenPanels = list('hiddenPanels').filter((x) => x !== id);
    } else if (p.setting) settings[p.setting] = p.inverted ? !on : on;
    else settings.hiddenPanels = on ? list('hiddenPanels').filter((x) => x !== id) : [...new Set([...list('hiddenPanels'), id])];
    saveSettings();
    applyPanels();
    return;
  }
  const now = (presetPanels(h, preset) || []).filter((x) => x !== id);
  if (id === 'unitpanel' && !on) selExpanded = false;
  setHud(withPanels(h, preset, on ? [...now, id] : now));
}

export function toggleVisible(id) { setVisible(id, !isVisible(id)); }

/** Alt+G: the Pulse strip where the preset uses it, the Scoreboard elsewhere. */
export function headlinePanel() {
  const h = hud();
  return h.preset !== 'full' && !(presetPanels(h, h.preset) || []).includes('scoreboard') ? 'pulse' : 'scoreboard';
}

export function setCollapsed(id, on) {
  settings.collapsedPanels = on ? [...new Set([...list('collapsedPanels'), id])] : list('collapsedPanels').filter((x) => x !== id);
  saveSettings();
  applyPanels();
}

// -- presets -----------------------------------------------------------------------------------------

let context = { onChange() {}, toast() {}, openStats() {}, closeStats() {} };
/** app.js hands over what the layout needs from it: re-render, toast, the Statistics window. */
export function setContext(ctx) { context = { ...context, ...ctx }; }
export function layoutContext() { return context; }

export function applyPreset(name) {
  if (!STOCK[name] && name !== CUSTOM) return;
  peek = false; selExpanded = false;
  setHud({ ...hud(), preset: name });
  // Analyst opens Statistics docked beside the map (a wide window only); leaving it puts things back.
  if (STOCK[name] && STOCK[name].stats === 'dock' && window.innerWidth >= 1500) context.openStats({ dock: true, preset: true });
  else context.closeStats();
  maybeHint(true);
}
export function presetIsChanged(name) { return presetChanged(hud(), name); }
export function restorePresetDefault(name) { setHud(restorePreset(hud(), name)); }

/** Every Full panel on, none collapsed (the old "Everything" button). */
export function showEverything() {
  for (const p of PANELS) {
    if (p.extra) continue;
    if (p.setting) settings[p.setting] = !p.inverted;
    if (p.gate) settings[p.gate] = true;
  }
  settings.hiddenPanels = [];
  settings.collapsedPanels = [];
  saveSettings();
  applyPanels();
}

/** Back to the defaults for this environment: the first preset, stock presets, no scenes, panels in place. */
export function resetHud() {
  const keep = hud();
  const preset = initialPreset({ ...hudEnvironment(), requested: null, hasSaved: false });
  resetPanelSizes();
  setHud({ ...defaultHud(), preset, hintSeen: keep.hintSeen, layouts: keep.layouts });
}

export function pulseMetrics() { const h = hud(); return presetMetrics(h, activePreset() === 'full' ? 'full' : h.preset); }
export function setPulseMetric(id, on) {
  const h = hud(), now = presetMetrics(h, h.preset).filter((x) => x !== id);
  setHud(withMetrics(h, h.preset, on ? [...now, id] : now));
}

/** The share link's hash for the HUD on screen ('hud=caster', 'hud=c1.pu-mm.age-vil'). */
export function shareHash() {
  const h = hud();
  const fullPanels = h.preset === 'full' ? PANELS.filter((p) => wanted(p.id, 'full')).map((p) => p.id) : null;
  return `hud=${encodeHud(h, { fullPanels })}`;
}

// Default placements (hud-layout.css): caster puts the scoreboard across the top,
// the team board bottom left and the minimap with the time controls bottom right;
// classic is the earlier layout (team board top left, minimap bottom left).
export const LAYOUTS = [['caster', 'Caster'], ['classic', 'Classic']];
export function hudLayout() { return settings.hudLayout === 'classic' ? 'classic' : 'caster'; }
export function setHudLayout(name) { settings.hudLayout = name; saveSettings(); applyPanels(); }
export function toggleArrange() { setArranging(!arranging()); }

// -- newer panels: loaded when first shown, rendered only while visible -------------------------------

const modules = new Map(); // module name -> { state: 'loading' | 'ready' | 'failed', panels }
const LOADERS = {
  pulse: () => import('./pulse.js'),
  'focus-slot': () => import('./focus-slot.js'),
  story: () => import('./story.js'),
  widgets: () => import('./widgets.js'),
};
function ensureModule(name) {
  let m = modules.get(name);
  if (m) return m;
  m = { state: 'loading', panels: {} };
  modules.set(name, m);
  LOADERS[name]().then((mod) => { m.panels = mod.PANEL_RENDERERS || {}; m.state = 'ready'; context.onChange(); })
    .catch((error) => { m.state = 'failed'; console.error('Vantage: panel module failed to load', name, error); });
  return m;
}

/** Render the newer panels that are visible (called with every HUD render). Hidden ones cost nothing. */
export function renderExtras() {
  for (const p of PANELS) {
    if (!p.module) continue;
    const visible = isVisible(p.id);
    if (!visible && !modules.has(p.module)) continue;
    const m = ensureModule(p.module), r = m.panels[p.id];
    if (!r) continue;
    let el = $(p.id);
    if (!el && visible) { el = r.create(context); el.classList.add('panel-fade'); }
    // A panel that fails must not take the rest of the HUD down with it.
    if (el && visible) { try { r.render(el, context); } catch (error) { if (!r.failed) { r.failed = true; console.error('Vantage: panel failed to render', p.id, error); } } }
  }
}

// -- applying ---------------------------------------------------------------------------------------

const phoneQuery = typeof matchMedia === 'function' ? matchMedia('(max-width: 700px), (max-height: 500px) and (pointer: coarse)') : null;
/** The phone layout: a narrow or short touch window, any preset but Full, not the OBS overlay. */
export function isPhone() {
  return !!phoneQuery && phoneQuery.matches && activePreset() !== 'full' && !document.body.classList.contains('overlay-mode');
}
let phoneModule = null;

/** Mirror the settings onto the panels (cheap; called with every HUD render). */
export function applyPanels() {
  const body = document.body, preset = activePreset();
  // The presets are designed around the caster placement; Full keeps the viewer's own (caster or classic).
  const placement = preset === 'full' ? hudLayout() : 'caster';
  if (body.dataset.hudLayout !== placement) body.dataset.hudLayout = placement;
  if (body.dataset.hudPreset !== preset) body.dataset.hudPreset = preset;
  const sc = scene();
  if (body.dataset.hudScene !== sc) body.dataset.hudScene = sc;
  body.classList.toggle('hud-peek', peek);
  body.classList.toggle('hud-paused', !S.playing);
  body.classList.toggle('hud-locked', !!hud().lock || body.classList.contains('overlay-mode'));
  const phone = isPhone();
  phoneOn = phone;
  if (body.classList.contains('hud-phone') !== phone) body.classList.toggle('hud-phone', phone);
  if (phone && !phoneModule) phoneModule = import('./phone.js').then((m) => { phoneModule = m; m.installPhone(context); context.onChange(); }).catch(console.error);
  if (phoneModule && phoneModule.syncPhone) phoneModule.syncPhone(phone);
  for (const p of PANELS) {
    const el = $(p.id);
    if (!el) continue;
    const auto = isAuto(p.id);
    el.classList.toggle('panel-off', !isVisible(p.id) && !auto);
    el.classList.toggle('panel-auto', auto);
    el.classList.toggle('collapsed', !!p.collapse && isCollapsed(p.id));
  }
  applyPanelSizes();
}

// The time controls of Minimal and Caster appear when the pointer nears the
// bottom edge, while paused, and while one of their buttons has the focus.
export function installAutoReveal() {
  const set = (on) => document.body.classList.toggle('hud-reveal-bottom', on);
  window.addEventListener('mousemove', (e) => set(e.clientY > window.innerHeight - 150), { passive: true });
  document.documentElement.addEventListener('mouseleave', () => set(false));
}

// -- first-run hint ------------------------------------------------------------------------------------

/** The presets hint: shown once, dismissible, never on the OBS overlay. `used`: a preset was just picked. */
export function maybeHint(used = false) {
  const h = hud();
  if (h.hintSeen) { const old = $('hud-hint'); if (old) old.remove(); return; }
  if (used) { settings.hud = { ...(settings.hud || defaultHud()), hintSeen: true }; saveSettings(); const old = $('hud-hint'); if (old) old.remove(); return; }
  if (document.body.classList.contains('overlay-mode') || $('hud-hint')) return;
  const el = document.createElement('div');
  el.id = 'hud-hint'; el.className = 'panel'; el.setAttribute('role', 'status');
  const keys = PRESET_ORDER.map((name) => `<span><kbd>${binding(STOCK[name].action)}</kbd> ${t(STOCK[name].label)}</span>`).join('');
  el.innerHTML = `<b>${t('Pick how much HUD you want')}</b>
    <span class="hint-keys">${keys}<span><kbd>${binding('peekFullHud')}</kbd> ${t('hold: peek at Full')}</span></span>
    <span class="hint-phone">${t('The tabs below open the tables; More has Customize.')}</span>
    <button type="button" data-hint="customize">${t('Customize…')}</button>
    <button type="button" data-hint="dismiss" aria-label="${t('Dismiss this hint')}">${t('Got it')}</button>`;
  document.body.appendChild(el);
  el.addEventListener('click', (e) => {
    const b = e.target.closest('[data-hint]');
    if (!b) return;
    maybeHint(true);
    if (b.dataset.hint === 'customize') togglePanelsMenu();
  });
}

// -- hover toolbar -------------------------------------------------------------------------

let tools = null, current = null, hideTimer = 0;

function hostOf(target) {
  for (const p of PANELS) {
    const host = $(p.host || p.id);
    if (host && host.contains(target)) return p;
  }
  return null;
}

function placeTools(p) {
  const host = $(p.host || p.id);
  const r = host.getBoundingClientRect();
  if (!r.width || !r.height) { tools.classList.add('hidden'); return; }
  const coll = isCollapsed(p.id);
  tools.innerHTML = `<span class="pt-name" aria-hidden="true">${t(p.label)}</span><button data-pt="move" aria-label="${t('Move {p}', { p: t(p.label) })}" ${tip(t('Move {p}', { p: t(p.label) }), t('Drag to move · Shift: no snapping · double-click: back to its place · arrow keys nudge · Alt+L: edit the whole layout'))}>⠿</button>${p.collapse ? `<button data-pt="collapse" aria-label="${coll ? t('Expand') : t('Collapse')}" ${tip(coll ? t('Expand') : t('Collapse'))}>${coll ? '▾' : '▴'}</button>` : ''}<button data-pt="hide" aria-label="${t('Hide {p}', { p: t(p.label) })}" ${tip(t('Hide {p}', { p: t(p.label) }), t('Bring it back from Customize (▣ above the minimap, Alt+V)'))}>✕</button>`;
  tools.classList.remove('hidden');
  const w = tools.offsetWidth;
  tools.style.left = `${Math.max(0, Math.min(window.innerWidth - w, r.right - w - 2))}px`;
  // Just above the panel's corner, so it covers none of its content (inside at the top edge).
  const h = tools.offsetHeight;
  // A panel at the window's top edge (the scoreboard) has no room above: the
  // tools go inside its bottom corner, which is clear, not over its first line.
  tools.style.top = `${r.top - h - 2 >= 0 ? r.top - h - 2 : r.height >= 56 ? r.bottom - h - 2 : r.top + 2}px`;
  current = p;
}

// No hover tools where nothing may move: a locked layout, the OBS overlay, the
// phone layout, and the layout editor (which has its own).
const toolsOff = () => document.body.matches('.hud-locked, .hud-phone, .hud-arrange');

export function installPanelTools(onChange, toast) {
  context.onChange = onChange; context.toast = toast;
  tools = document.createElement('div');
  tools.id = 'panel-tools';
  tools.className = 'hidden';
  document.body.appendChild(tools);
  document.addEventListener('mouseover', (e) => {
    if (tools.contains(e.target)) { clearTimeout(hideTimer); return; }
    const p = toolsOff() ? null : hostOf(e.target);
    if (p && (isVisible(p.id) || isAuto(p.id))) { clearTimeout(hideTimer); if (p !== current || tools.classList.contains('hidden')) placeTools(p); return; }
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { tools.classList.add('hidden'); current = null; }, 250);
  });
  tools.addEventListener('pointerdown', (e) => {
    if (!e.target.closest('[data-pt="move"]') || !current) return;
    const p = current;
    tools.classList.add('hidden');
    startMove($(p.host || p.id), e);
  });
  tools.addEventListener('dblclick', (e) => {
    if (!e.target.closest('[data-pt="move"]') || !current) return;
    resetPanel(current.host || current.id); onChange();
  });
  tools.addEventListener('keydown', (e) => {
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!d || !e.target.closest('[data-pt="move"]') || !current) return;
    e.preventDefault(); e.stopPropagation();
    const step = e.shiftKey ? 1 : 10;
    nudgePanel($(current.host || current.id), d[0] * step, d[1] * step);
    placeTools(current);
  });
  tools.addEventListener('click', (e) => {
    const b = e.target.closest('[data-pt]');
    if (!b || !current || b.dataset.pt === 'move') return;
    const p = current;
    if (b.dataset.pt === 'collapse') setCollapsed(p.id, !isCollapsed(p.id));
    else {
      setVisible(p.id, false);
      tools.classList.add('hidden'); current = null;
      toast(t('{p} hidden · ▣ Customize (Alt+V) brings it back', { p: t(p.label) }));
    }
    if (current) placeTools(current);
    onChange();
  });
}

// -- the Customize drawer (customize.js) ---------------------------------------------------------------

let drawer = null, drawerLoading = null;
export function panelsMenuOpen() { const el = $('panels-menu'); return !!el && !el.classList.contains('hidden'); }
export function closePanelsMenu() { if (drawer) drawer.close(); else if ($('panels-menu')) $('panels-menu').classList.add('hidden'); }

export function togglePanelsMenu() {
  if (drawer) { drawer.toggle(); return; }
  if (!drawerLoading) {
    drawerLoading = import('./customize.js').then((m) => { drawer = m.installCustomize(context); drawer.toggle(); })
      .catch((error) => { drawerLoading = null; console.error(error); context.toast(t('failed')); });
  }
}

export function installPanelsMenu(onChange) { context.onChange = onChange; }

// -- the layout editor (layout-editor.js) ----------------------------------------------------------------

let editor = null;
/** Alt+L: edit the layout (the editor is loaded on first use). */
export function toggleEditLayout() {
  if (document.body.classList.contains('hud-phone')) { context.toast(t('The layout editor needs a wider window')); return; }
  if (editor) { editor.toggle(); return; }
  editor = { toggle() {} };
  import('./layout-editor.js').then((m) => { editor = m.installLayoutEditor(context); editor.toggle(); })
    .catch((error) => { editor = null; console.error(error); context.toast(t('failed')); });
}
