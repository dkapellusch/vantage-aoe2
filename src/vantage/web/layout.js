// Panel layout: which HUD panels show and which are collapsed to their top
// strip. Every panel gets a hover toolbar (collapse, hide), and the Panels menu
// lists them all with presets, so a hidden panel is always one click from
// coming back. Panels whose visibility already was a setting (scoreboard,
// production, dashboard, events) keep that setting as the
// source of truth; the others are listed in settings.hiddenPanels.

import { settings, saveSettings, esc, tip } from './state.js';
import { t } from './i18n.js';
import { applyPanelSizes, resetPanelSizes, resetPanel, startMove, nudgePanel, arranging, setArranging } from './panel-resize.js';

const $ = (id) => document.getElementById(id);

// host: the element the toolbar sits on; el: what hiding hides (the minimap
// keeps its button row, which holds the Panels button itself).
export const PANELS = [
  { id: 'scoreboard', label: 'Scoreboard', setting: 'disableScoreboard', inverted: true },
  { id: 'overview', label: 'Team overview', collapse: true },
  { id: 'techs', label: 'Techs', collapse: true },
  { id: 'production', label: 'Production & composition', setting: 'showProduction', collapse: true },
  { id: 'dashboard', label: 'Dashboard', setting: 'showDashboard', collapse: true },
  { id: 'events', label: 'Event log', setting: 'showEvents', collapse: true },
  { id: 'unitpanel', label: 'Selection panel', collapse: true },
  { id: 'timebar', label: 'Time controls', collapse: true },
  { id: 'minimap', host: 'minimap-wrap', label: 'Minimap' },
];

export const PRESETS = {
  // The map, who is winning, the clock and what you click on.
  clean: ['scoreboard', 'unitpanel', 'timebar', 'minimap'],
  all: PANELS.map((p) => p.id),
};

const byId = new Map(PANELS.map((p) => [p.id, p]));
const list = (k) => (Array.isArray(settings[k]) ? settings[k] : []);

export function isVisible(id) {
  const p = byId.get(id);
  if (!p) return true;
  if (p.setting) return p.inverted ? !settings[p.setting] : !!settings[p.setting];
  return !list('hiddenPanels').includes(id);
}

export function isCollapsed(id) { return list('collapsedPanels').includes(id); }

export function setVisible(id, on) {
  const p = byId.get(id);
  if (!p) return;
  if (p.setting) settings[p.setting] = p.inverted ? !on : on;
  else settings.hiddenPanels = on ? list('hiddenPanels').filter((x) => x !== id) : [...new Set([...list('hiddenPanels'), id])];
  saveSettings();
  applyPanels();
}

export function setCollapsed(id, on) {
  settings.collapsedPanels = on ? [...new Set([...list('collapsedPanels'), id])] : list('collapsedPanels').filter((x) => x !== id);
  saveSettings();
  applyPanels();
}

export function applyPreset(name) {
  const keep = new Set(PRESETS[name] || PRESETS.all);
  for (const p of PANELS) {
    if (p.setting) settings[p.setting] = p.inverted ? !keep.has(p.id) : keep.has(p.id);
  }
  settings.hiddenPanels = PANELS.filter((p) => !p.setting && !keep.has(p.id)).map((p) => p.id);
  settings.collapsedPanels = [];
  saveSettings();
  applyPanels();
}

// Default placements (hud-layout.css): caster puts the scoreboard across the top,
// the team board bottom left and the minimap with the time controls bottom right;
// classic is the earlier layout (team board top left, minimap bottom left).
export const LAYOUTS = [['caster', 'Caster'], ['classic', 'Classic']];
export function hudLayout() { return settings.hudLayout === 'classic' ? 'classic' : 'caster'; }
export function setHudLayout(name) { settings.hudLayout = name; saveSettings(); applyPanels(); }
export function toggleArrange() { setArranging(!arranging()); }

/** Mirror the settings onto the panels (cheap; called with every HUD render). */
export function applyPanels() {
  if (document.body.dataset.hudLayout !== hudLayout()) document.body.dataset.hudLayout = hudLayout();
  for (const p of PANELS) {
    const el = $(p.id);
    if (!el) continue;
    el.classList.toggle('panel-off', !isVisible(p.id));
    el.classList.toggle('collapsed', !!p.collapse && isCollapsed(p.id));
  }
  applyPanelSizes();
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
  tools.innerHTML = `<button data-pt="move" ${tip(t('Move {p}', { p: t(p.label) }), t('Drag to move · Shift: no snapping · double-click: back to its place · arrow keys nudge · Alt+L: arrange every panel'))}>⠿</button>${p.collapse ? `<button data-pt="collapse" ${tip(coll ? t('Expand') : t('Collapse'))}>${coll ? '▾' : '▴'}</button>` : ''}<button data-pt="hide" ${tip(t('Hide {p}', { p: t(p.label) }), t('Bring it back from the Panels menu (▣ above the minimap, Alt+V)'))}>✕</button>`;
  tools.classList.remove('hidden');
  const w = tools.offsetWidth;
  tools.style.left = `${Math.max(0, Math.min(window.innerWidth - w, r.right - w - 2))}px`;
  // Just above the panel's corner, so it covers none of its content (inside at the top edge).
  const h = tools.offsetHeight;
  tools.style.top = `${r.top - h - 2 >= 0 ? r.top - h - 2 : r.top + 2}px`;
  current = p;
}

export function installPanelTools(onChange, toast) {
  tools = document.createElement('div');
  tools.id = 'panel-tools';
  tools.className = 'hidden';
  document.body.appendChild(tools);
  document.addEventListener('mouseover', (e) => {
    if (tools.contains(e.target)) { clearTimeout(hideTimer); return; }
    const p = hostOf(e.target);
    if (p && isVisible(p.id)) { clearTimeout(hideTimer); if (p !== current || tools.classList.contains('hidden')) placeTools(p); return; }
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
      toast(t('{p} hidden · ▣ Panels (Alt+V) brings it back', { p: t(p.label) }));
    }
    if (current) placeTools(current);
    onChange();
  });
}

// -- the Panels menu -----------------------------------------------------------------------

export function panelsMenuOpen() { return !$('panels-menu').classList.contains('hidden'); }
export function closePanelsMenu() { $('panels-menu').classList.add('hidden'); }

function renderMenu() {
  const el = $('panels-menu');
  el.innerHTML = `<div class="omni-title">${t('Panels')}</div>
    ${PANELS.map((p) => `<div class="pm-row"><label><input type="checkbox" data-pm-show="${p.id}" ${isVisible(p.id) ? 'checked' : ''}> ${esc(t(p.label))}</label>${p.collapse ? `<button data-pm-collapse="${p.id}" class="${isCollapsed(p.id) ? 'on' : ''}" ${tip(t('Collapse to its top strip'))}>${isCollapsed(p.id) ? '▾' : '▴'}</button>` : ''}</div>`).join('')}
    <div class="pm-presets"><button data-pm-preset="clean" ${tip(t('Clean'), t('Scoreboard, selection, time controls and minimap'))}>${t('Clean')}</button><button data-pm-preset="all" ${tip(t('Everything'), t('Every panel, none collapsed'))}>${t('Everything')}</button><button data-pm-reset-sizes ${tip(t('Reset layout'), t('Every panel back to its place and size'))}>${t('Reset layout')}</button></div>
    <div class="pm-presets pm-layouts"><span class="hint">${t('Layout')}</span>${LAYOUTS.map(([k, l]) => `<button data-pm-layout="${k}" class="${hudLayout() === k ? 'on' : ''}">${t(l)}</button>`).join('')}<button data-pm-arrange class="${arranging() ? 'on' : ''}" ${tip(t('Arrange panels (Alt+L)'), t('Drag any panel to move it'))}>${t('Arrange')}</button></div>`;
}

export function togglePanelsMenu(anchor) {
  const el = $('panels-menu');
  if (panelsMenuOpen()) { closePanelsMenu(); return; }
  renderMenu();
  const r = (anchor || $('btn-panels')).getBoundingClientRect();
  el.style.left = `${Math.max(8, r.left)}px`;
  el.style.bottom = `${Math.max(8, window.innerHeight - r.top + 4)}px`;
  el.classList.remove('hidden');
}

export function installPanelsMenu(onChange) {
  const el = $('panels-menu');
  el.addEventListener('change', (e) => {
    const id = e.target.dataset && e.target.dataset.pmShow;
    if (!id) return;
    setVisible(id, e.target.checked);
    onChange();
  });
  el.addEventListener('click', (e) => {
    if (e.target.closest('[data-pm-reset-sizes]')) { resetPanelSizes(); onChange(); return; }
    const lay = e.target.closest('[data-pm-layout]');
    if (lay) { setHudLayout(lay.dataset.pmLayout); renderMenu(); onChange(); return; }
    if (e.target.closest('[data-pm-arrange]')) { toggleArrange(); closePanelsMenu(); onChange(); return; }
    const c = e.target.closest('[data-pm-collapse]');
    const pr = e.target.closest('[data-pm-preset]');
    if (c) setCollapsed(c.dataset.pmCollapse, !isCollapsed(c.dataset.pmCollapse));
    else if (pr) applyPreset(pr.dataset.pmPreset);
    else return;
    renderMenu();
    onChange();
  });
  document.addEventListener('mousedown', (e) => {
    if (panelsMenuOpen() && !e.target.closest('#panels-menu, #btn-panels')) closePanelsMenu();
  });
}
