// The phone layout: no free-floating panels. The map, two Pulse rows, the
// Match story with a thumb-sized scrubber, and a tab bar whose tabs open a
// bottom sheet (a right-hand drawer in landscape): Bank, the Team board, the
// selection, and More (Customize, Statistics, replays, settings). Every
// target is at least 44 px; nothing scrolls sideways.
//
// Loaded the first time the phone layout applies (layout.js isPhone): any
// preset but Full, in a narrow or short touch window.

import { S, fmtNum, fmtStock, esc, RES } from './state.js';
import { t } from './i18n.js';
import { HUD_PARTS } from './panels.js';
import { METRICS, KILLS_LOSSES } from './metrics.js';
import { sumStat } from './team-board.js';
import { compareTableHtml, sideStats } from './compare-table.js';
import { pulseSides } from './pulse.js';
import { setPhoneTab, phoneTab, togglePanelsMenu, applyPreset, activePreset, PRESETS } from './layout.js';

const $ = (id) => document.getElementById(id);
const TABS = [['pulse', 'Pulse', 'Watch: close the sheet'], ['bank', 'Bank', 'Resources, gatherers and rates'], ['table', 'Table', 'The Team board'], ['unit', 'Unit', 'The selection'], ['more', 'More', 'Customize, statistics, replays, settings']];
const RES_LABEL = { food: 'Food', wood: 'Wood', gold: 'Gold', stone: 'Stone' };
const homes = new Map(); // moved panel id -> { parent, next }
let ctx = null, tabs = null, sheet = null, size = 'half';

export function bankRows(list) {
  const stats = list.map(sideStats);
  const of = (f) => stats.map((s) => sumStat(s, f));
  const rows = RES.map((r) => {
    const bank = of((s) => s.resources?.[r]), rate = of((s) => s.collected_rate?.[r]);
    return { label: RES_LABEL[r], values: bank, text: bank.map((v, i) => `${fmtStock(v ?? 0)} +${fmtNum(rate[i] ?? 0)}`) };
  });
  const gather = stats.map((s) => RES.map((r) => sumStat(s, (x) => x.tasks?.[r] ?? 0) ?? 0));
  const pop = of(METRICS.population.f), cap = of(METRICS.population.cap);
  const kills = of(METRICS.kills.f), losses = of(METRICS.losses.f);
  return [
    ...rows,
    { label: 'Gatherers F / W / G / S', values: gather.map((g) => g.reduce((a, b) => a + b, 0)), text: gather.map((g) => g.join('/')) },
    { label: 'Collection rate · last minute', values: of(METRICS.rate.f), text: of(METRICS.rate.f).map((v) => fmtNum(v ?? 0)) },
    { label: 'Collected · whole game', values: of(METRICS.collected.f), text: of(METRICS.collected.f).map((v) => fmtNum(v ?? 0)) },
    { label: METRICS.population.label, values: pop, text: pop.map((v, i) => `${v ?? '–'}/${cap[i] ?? '–'}`) },
    { label: KILLS_LOSSES.label, values: kills, text: kills.map((v, i) => `${v ?? 0} / ${losses[i] ?? 0}`) },
  ];
}

function moreHtml() {
  const b = (act, label) => `<button type="button" data-more="${act}">${esc(t(label))}</button>`;
  const presets = ['minimal', 'caster', 'review', 'full'].map((name) => `<button type="button" data-more-preset="${name}" aria-pressed="${activePreset() === name}">${esc(t(PRESETS[name].label))}</button>`).join('');
  return `<div class="ph-more"><h3>${esc(t('HUD'))}</h3><div class="ph-grid">${presets}</div>
    <div class="ph-grid">${b('customize', 'Customize…')}${b('stats', 'Statistics')}${b('home', 'Replays & recordings')}${b('fog', 'Fog of war')}${b('settings', 'Settings')}${b('help', 'Quick reference')}${b('fullscreen', 'Full screen')}</div></div>`;
}

function renderSheet() {
  const tab = phoneTab();
  for (const b of tabs.querySelectorAll('[data-tab]')) {
    const on = b.dataset.tab === tab;
    b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1;
  }
  const unit = tabs.querySelector('[data-tab="unit"]');
  unit.classList.toggle('has', S.selection.size > 0);
  unit.setAttribute('aria-label', S.selection.size ? t('Unit: {n} selected', { n: S.selection.size }) : t('Unit'));
  const open = tab !== 'pulse';
  sheet.classList.toggle('hidden', !open);
  document.body.classList.toggle('phone-sheet-open', open);
  if (!open) return;
  sheet.dataset.size = size;
  const info = TABS.find(([id]) => id === tab);
  HUD_PARTS.setText(sheet.querySelector('.ph-title'), t(tab === 'table' ? 'Team board' : tab === 'unit' ? 'Selection' : tab === 'bank' ? 'Bank and economy' : info[1]));
  sheet.setAttribute('aria-label', t(info[2]));
  const body = sheet.querySelector('.ph-body'), own = sheet.querySelector('.ph-own');
  // The Team board and the Selection panel are the real panels, moved into the sheet.
  for (const [id, forTab] of [['overview', 'table'], ['unitpanel', 'unit']]) {
    const el = $(id);
    if (el && el.parentElement === body) el.classList.toggle('ph-off', tab !== forTab);
  }
  let html = '';
  if (tab === 'bank' && S.view) html = compareTableHtml(pulseSides().sides.slice(0, 4), bankRows(pulseSides().sides.slice(0, 4)));
  else if (tab === 'more') html = moreHtml();
  else if (tab === 'unit' && !S.selection.size) html = `<p class="hint ph-empty">${esc(t('Tap a unit or a building on the map to see it here.'))}</p>`;
  HUD_PARTS.setHtml(own, html);
}

function move(on) {
  const body = sheet.querySelector('.ph-body');
  for (const id of ['overview', 'unitpanel']) {
    const el = $(id);
    if (!el) continue;
    if (on && el.parentElement !== body) { homes.set(id, { parent: el.parentElement, next: el.nextSibling }); body.appendChild(el); }
    else if (!on && homes.has(id)) {
      const home = homes.get(id); homes.delete(id);
      el.classList.remove('ph-off');
      if (home.next && home.next.parentNode === home.parent) home.parent.insertBefore(el, home.next); else home.parent.appendChild(el);
    }
  }
}

/** Called with every HUD render: enter or leave the phone layout, and refresh the sheet. */
export function syncPhone(on) {
  if (!tabs) return;
  tabs.classList.toggle('hidden', !on);
  if (!on) { sheet.classList.add('hidden'); document.body.classList.remove('phone-sheet-open'); move(false); return; }
  move(true);
  renderSheet();
}

export function installPhone(context) {
  ctx = context;
  tabs = document.createElement('nav');
  tabs.id = 'phone-tabs'; tabs.className = 'hidden';
  tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', t('HUD'));
  tabs.innerHTML = TABS.map(([id, label, detail]) => `<button type="button" role="tab" data-tab="${id}" aria-controls="phone-sheet" aria-selected="false" title="${esc(t(detail))}">${esc(t(label))}</button>`).join('');
  sheet = document.createElement('section');
  sheet.id = 'phone-sheet'; sheet.className = 'panel hidden';
  sheet.setAttribute('role', 'tabpanel');
  sheet.innerHTML = `<button type="button" class="ph-handle" aria-label="${esc(t('Sheet size: tap to make it taller or shorter, drag to resize'))}"><i></i></button>
    <div class="ph-head"><h2 class="ph-title"></h2><button type="button" class="ph-close" aria-label="${esc(t('Close'))}">✕</button></div>
    <div class="ph-body"><div class="ph-own"></div></div>`;
  document.body.append(sheet, tabs);

  const pick = (tab) => { setPhoneTab(tab === phoneTab() && tab !== 'pulse' ? 'pulse' : tab); ctx.onChange(); };
  tabs.addEventListener('click', (e) => { const b = e.target.closest('[data-tab]'); if (b) pick(b.dataset.tab); });
  tabs.addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    const all = [...tabs.querySelectorAll('[data-tab]')], i = all.indexOf(document.activeElement);
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : (i + (e.key === 'ArrowLeft' ? -1 : 1) + all.length) % all.length;
    all[next].focus(); pick(all[next].dataset.tab);
  });
  sheet.querySelector('.ph-close').addEventListener('click', () => { setPhoneTab('pulse'); ctx.onChange(); tabs.querySelector('[data-tab="pulse"]').focus(); });
  sheet.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); setPhoneTab('pulse'); ctx.onChange(); } });

  // The handle: a tap switches between half and full height; a drag follows the thumb and settles.
  const handle = sheet.querySelector('.ph-handle');
  let drag = null;
  handle.addEventListener('pointerdown', (e) => { drag = { y: e.clientY, h: sheet.getBoundingClientRect().height, moved: false }; handle.setPointerCapture(e.pointerId); });
  handle.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dy = drag.y - e.clientY;
    if (Math.abs(dy) > 6) drag.moved = true;
    if (drag.moved) sheet.style.height = `${Math.max(120, Math.min(window.innerHeight - 120, drag.h + dy))}px`;
  });
  const settle = () => {
    if (!drag) return;
    const h = sheet.getBoundingClientRect().height, moved = drag.moved;
    drag = null; sheet.style.height = '';
    if (!moved) size = size === 'half' ? 'full' : 'half';
    else if (h < window.innerHeight * 0.22) { setPhoneTab('pulse'); size = 'half'; }
    else size = h > window.innerHeight * 0.58 ? 'full' : 'half';
    ctx.onChange();
  };
  handle.addEventListener('pointerup', settle);
  handle.addEventListener('pointercancel', settle);

  sheet.addEventListener('click', (e) => {
    const preset = e.target.closest('[data-more-preset]');
    if (preset) { applyPreset(preset.dataset.morePreset); ctx.onChange(); return; }
    const b = e.target.closest('[data-more]');
    if (!b) return;
    const a = ctx.actions, act = b.dataset.more;
    setPhoneTab('pulse');
    if (act === 'customize') togglePanelsMenu();
    else if (act === 'stats') a.showAchievements();
    else if (act === 'home') a.openHome();
    else if (act === 'fog') a.cycleFogOfWar();
    else if (act === 'settings') a.openSettings();
    else if (act === 'help') a.openHelp();
    else if (act === 'fullscreen') a.toggleFullScreen();
    ctx.onChange();
  });
}
