// Full-screen overlays: statistics, home (overview / replays / recordings / live),
// settings (tabbed), quick reference, end of game.
// drawChart is exported for the HUD's graph slide-out.

import { ECO_TECHS, MIL_TECHS } from './games.js';
import {
  S, SPEEDS, settings, saveSettings, resetSettings, replaceSettings, DEFAULT_SETTINGS, api, fetchView, fmtTime, fmtNum, esc, players,
  gameKey, playerName, playerMarkColor, playerTextColor, teams, sideTeams, teamName, unitInfo, unitIcon, AGE_NAMES, toast, tip, tooltipLevel,
  refreshSeries,
} from './state.js';
import * as HK from './hotkeys.js';
import { DASH_HISTORY } from './player-review.js';
import { investigationHtml, wireInvestigation } from './review-workspace.js';
import { t, LANGS, language, setLanguage, keyLabel } from './i18n.js';
import * as PN from './panels.js';
import { patchHtml } from './dom.js';
import { bonusIncomeHtml } from './resource-review.js';

const $ = (id) => document.getElementById(id);
// app.js publishes its actions (pause, seek, speed, …) on window.vantage.
const actions = () => (window.vantage && window.vantage.actions) || {};
const seekFn = (s) => s || (window.vantage && window.vantage.seek) || null;
const baseName = (p) => String(p || '').split(/[\\/]/).pop();
const ordinal = (n) => (n === 1 ? t('1st') : n === 2 ? t('2nd') : n === 3 ? t('3rd') : t('{n}th', { n }));
let openId = null;
let nativeReplays = false;

export const REPO_URL = 'https://github.com/dkapellusch/vantage-aoe2';
const LIVE_DOCS_URL = `${REPO_URL}/wiki/Live-games`;
const extLink = (href, label) => `<a href="${esc(href)}" target="_blank" rel="noopener">${label}</a>`;

export function isOpen(id) { return openId === id; }
export function closeAll() {
  document.querySelectorAll('.overlay').forEach((o) => o.classList.add('hidden'));
  openId = null;
}
function open(id) {
  closeAll();
  const el = $(id);
  if (!el) return;
  el.classList.remove('hidden');
  openId = id;
}
export function toggle(id, render) {
  if (openId === id) { closeAll(); return; }
  open(id);
  render();
}
function closeBtn() { return `<button class="close" data-close ${tip(t('Close'), t('Esc closes every overlay'))}>${t('✕ Esc')}</button>`; }
function wireClose(el) { el.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', closeAll)); }
function cssVar(name, fallback) {
  const v = getComputedStyle(document.body).getPropertyValue(name).trim();
  return v || fallback;
}

// A small in-page confirmation dialog (never window.confirm: it blocks the
// render loop). Resolves true when the user agrees.
export function confirmDialog(title, message, okLabel) {
  return new Promise((resolve) => {
    const box = document.createElement('div');
    box.className = 'ovl-modal';
    box.innerHTML = `<div class="ovl-modal-box" role="dialog" aria-modal="true"><h3>${esc(title)}</h3><p>${message}</p>
      <div class="ovl-modal-buttons"><button data-no>${t('Cancel')}</button><button class="on" data-yes>${esc(okLabel || t('Continue'))}</button></div></div>`;
    const done = (v) => { window.removeEventListener('keydown', onKey, true); box.remove(); resolve(v); };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); done(false); }
      if (e.key === 'Enter') { e.preventDefault(); e.stopImmediatePropagation(); done(true); }
    };
    window.addEventListener('keydown', onKey, true);
    box.querySelector('[data-no]').addEventListener('click', () => done(false));
    box.querySelector('[data-yes]').addEventListener('click', () => done(true));
    box.addEventListener('click', (e) => { if (e.target === box) done(false); });
    document.body.appendChild(box);
    box.querySelector('[data-yes]').focus();
  });
}

// =====================================================================================
// statistics
// =====================================================================================

const TABS = {
  score: { title: 'Score', series: ['score', 'col_total', 'army_value', 'pop'] },
  military: { title: 'Military', series: ['military', 'mil_pop', 'army_value', 'kills', 'deaths', 'razings'] },
  economy: {
    title: 'Economy',
    series: ['villagers', 'eco_pop', 'efficiency_lm', 'productive_lm', 'unproductive_lm', 'gather_food_lm', 'gather_wood_lm',
      'gather_gold_lm', 'gather_stone_lm', 'col_total', 'col_food', 'col_wood', 'col_gold', 'col_stone', 'idle', 'fishing_ships',
      'trade_units', 'eco_units'],
  },
  technology: { title: 'Technology', series: ['techs', 'age'] },
  bonus: { title: 'Bonus resources', series: ['bonus_total', 'bonus_food', 'bonus_wood', 'bonus_gold', 'bonus_stone'] },
  society: { title: 'Society', series: ['explored', 'relics', 'pop', 'eco_pop', 'mil_pop'] },
  apm: { title: 'APM', series: ['apm', 'apm_eco', 'apm_mil'] },
  timeline: {
    title: 'Timeline',
    series: ['villagers', 'military', 'pop', 'eco_pop', 'mil_pop', 'eco_units', 'army_value', 'col_total', 'res_food', 'res_wood',
      'res_gold', 'res_stone', 'explored', 'apm', 'task_food', 'task_wood', 'task_gold', 'task_stone', 'task_idle', 'gather_food_lm',
      'gather_wood_lm', 'gather_gold_lm', 'gather_stone_lm', 'tc_idle', 'housed'],
  },
};
export const SERIES_LABEL = {
  bonus_total: 'Bonus resources', bonus_food: 'Bonus food', bonus_wood: 'Bonus wood', bonus_gold: 'Bonus gold', bonus_stone: 'Bonus stone',
  score: 'Score', col_total: 'Resources collected', army_value: 'Military value', military: 'Military units',
  kills: 'Kills', deaths: 'Losses', razings: 'Buildings razed', villagers: 'Villagers', col_food: 'Food collected',
  col_wood: 'Wood collected', col_gold: 'Gold collected', col_stone: 'Stone collected', idle: 'Idle villagers',
  fishing_ships: 'Fishing ships', trade_units: 'Trade units', eco_units: 'Economy units', techs: 'Techs researched',
  age: 'Age', explored: 'Map explored %', relics: 'Relics', pop: 'Population', apm: 'APM', apm_eco: 'eAPM (eco)',
  apm_mil: 'eAPM (military)', res_food: 'Food banked', res_wood: 'Wood banked', res_gold: 'Gold banked',
  res_stone: 'Stone banked', task_food: 'Villagers on food', task_wood: 'Villagers on wood',
  task_gold: 'Villagers on gold', task_stone: 'Villagers on stone', task_idle: 'Idle villagers',
  efficiency: 'Worker efficiency %', efficiency_lm: 'Worker efficiency % (last minute)',
  productive_lm: 'Productive worker time (last minute)', unproductive_lm: 'Unproductive worker time (last minute)',
  gather_food_lm: 'Food gathering time (last minute, s)', gather_wood_lm: 'Wood gathering time (last minute, s)',
  gather_gold_lm: 'Gold gathering time (last minute, s)', gather_stone_lm: 'Stone gathering time (last minute, s)',
  mil_pop: 'Military population', eco_pop: 'Economy population',
  tc_idle: 'Idle TC time', housed: 'Housed time',
};
export function seriesLabel(key) { return t(SERIES_LABEL[key] || key); }

const chartState = {
  tab: 'score', key: 'score', type: 'line', transform: 'actual', hidden: new Set(), techMarks: true, ecoTechs: false, milTechs: false,
  span: 0, from: 0, // zoom window: span 0 = the whole game
};
const SAVED_CHART_KEYS = ['key', 'type', 'transform', 'techMarks', 'ecoTechs', 'milTechs'];

function loadChartDefinition(tab) {
  const d = (settings.chartDefinitions || {})[tab];
  if (!d) return;
  for (const k of SAVED_CHART_KEYS) if (d[k] !== undefined) chartState[k] = d[k];
  chartState.hidden = new Set(d.hidden || []);
}

function exportStats() {
  const data = { match: S.match, summary: S.summary, series: S.series, events: S.events };
  const dl = (name, text, type) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  dl('vantage-stats.json', JSON.stringify(data, null, 1), 'application/json');
  const keys = new Set();
  for (const rows of Object.values(S.series || {})) for (const r of rows) Object.keys(r).forEach((k) => keys.add(k));
  const cols = ['player', ...keys];
  const lines = [cols.join(',')];
  for (const [pid, rows] of Object.entries(S.series || {})) for (const r of rows) lines.push(cols.map((c) => (c === 'player' ? pid : r[c] ?? '')).join(','));
  dl('vantage-series.csv', lines.join('\n'), 'text/csv');
}

// Series keys the backend actually sends (new ones may not exist on an older server).
let keysRef = null, keysSeen = new Set();
function availableKeys() {
  if (S.series !== keysRef) {
    keysRef = S.series;
    keysSeen = new Set();
    for (const [pid, rows] of Object.entries(S.series || {})) {
      if (pid === '0' || !rows || !rows.length) continue;
      Object.keys(rows[rows.length - 1]).forEach((k) => keysSeen.add(k));
    }
  }
  return keysSeen;
}
function tabSeries(tab) {
  const list = TABS[tab].series;
  const have = availableKeys();
  if (!have.size) return list;
  const got = list.filter((k) => have.has(k));
  return got.length ? got : list;
}

// Whole-game time range covered by the series.
export function fullRange() {
  let a = Infinity, b = -Infinity;
  for (const p of players()) {
    const rows = S.series && S.series[p.id];
    if (rows && rows.length) { a = Math.min(a, rows[0].t); b = Math.max(b, rows[rows.length - 1].t); }
  }
  if (!Number.isFinite(a)) return [S.start || 0, Math.max(1, S.end || 1)];
  return [a, Math.max(b, a + 1)];
}
function chartWindow() {
  const [a, b] = fullRange();
  if (!chartState.span || chartState.span >= b - a) return [a, b];
  const from = Math.max(a, Math.min(b - chartState.span, chartState.from));
  return [from, from + chartState.span];
}
// Zoom by factor f (0.5 = in) keeping time `at` (default: the viewed time) in place.
function zoomChart(f, at) {
  const [a, b] = fullRange();
  const [w0, w1] = chartWindow();
  const cur = w1 - w0;
  const span = Math.max(60000, cur * f);
  if (span >= b - a) { chartState.span = 0; chartState.from = a; return; }
  const c = at ?? (S.t >= w0 && S.t <= w1 ? S.t : (w0 + w1) / 2);
  const frac = (c - w0) / Math.max(1, cur);
  chartState.span = span;
  chartState.from = Math.max(a, Math.min(b - span, c - frac * span));
}
function pageChart(dir) {
  if (!chartState.span) return;
  const [a, b] = fullRange();
  chartState.from = Math.max(a, Math.min(b - chartState.span, chartWindow()[0] + dir * chartState.span));
}

function lowerBound(rows, tm) {
  let lo = 0, hi = rows.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (rows[m].t < tm) lo = m + 1; else hi = m; }
  return lo;
}
const TICK_STEPS = [15000, 30000, 60000, 120000, 300000, 600000, 900000, 1800000, 3600000];

// The round step (1, 2, 2.5 or 5 times a power of ten) giving about `ticks` grid lines up to `max`.
export function niceStep(max, ticks) {
  const raw = Math.max(max, 1e-9) / Math.max(1, ticks);
  const pow = 10 ** Math.floor(Math.log10(raw));
  const f = raw / pow;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * pow;
}

/**
 * Draw a per-player time-series chart.
 *   drawChart(canvas?, opts?, seek?)
 * canvas: a <canvas> (default: the statistics overlay's #chart).
 * opts (all optional; defaults are the statistics screen's current options):
 *   key        series key (see SERIES_LABEL), e.g. 'score', 'villagers'
 *   type       'line' | 'stacked'
 *   transform  'actual' | 'percent' | 'relative'
 *   hidden     Set or array of player ids to leave out
 *   techMarks / ecoTechs / milTechs   age-up / eco / military tech markers
 *   range      [t0, t1] in game ms (default: the stats zoom window for #chart,
 *              the whole game for any other canvas)
 *   until      draw only up to this time (e.g. S.t, so a slide-out shows no spoilers)
 *   compact    small margins and fonts (also automatic below 420 px wide)
 *   clickSeek  true: left click also seeks (right click always does)
 *   onSeek(t)  called after a seek
 * seek: function(t) (default: window.vantage.seek).
 * Returns {tMin, tMax}, or null when there was nothing to draw.
 */
export function drawChart(canvas, opts, seek) {
  if (typeof canvas === 'function') { seek = canvas; canvas = null; } // legacy drawChart(seek)
  const c = canvas || $('chart');
  if (!c || !c.isConnected) return null;
  const o = { ...chartState, ...(opts || {}) };
  const hidden = o.hidden instanceof Set ? o.hidden : new Set(o.hidden || []);
  const rect = c.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const dpr = window.devicePixelRatio || 1;
  c.width = Math.round(rect.width * dpr); c.height = Math.round(rect.height * dpr);
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = rect.width, H = rect.height, small = !!o.compact || W < 420;
  const L = small ? 38 : 54, R = 10, T = small ? 8 : 12, B = small ? 18 : 26;
  const font = small ? '10px sans-serif' : '11px sans-serif';
  const muted = cssVar('--muted', '#9a958a');
  const key = o.key || 'score';
  let [tMin, tMax] = o.range || (c.id === 'chart' ? chartWindow() : fullRange());
  if (o.until != null) tMax = Math.max(tMin + 1, Math.min(tMax, o.until));
  const ps = players().filter((p) => !hidden.has(p.id));
  const series = ps.map((p) => {
    const rows = (S.series && S.series[p.id]) || [];
    const lo = Math.max(0, lowerBound(rows, tMin) - 1), hi = Math.min(rows.length, lowerBound(rows, tMax) + 1);
    return { p, rows: rows.slice(lo, hi) };
  });
  g.clearRect(0, 0, W, H);
  g.font = font;
  const ref = series.reduce((a, s) => (s.rows.length > a.length ? s.rows : a), []);
  const times = ref.map((r) => r.t);
  if (!times.length) {
    g.fillStyle = muted; g.textAlign = 'center'; g.fillText(t('No data yet'), W / 2, H / 2); g.textAlign = 'left';
    c.onmousemove = null; c.oncontextmenu = null; c.onclick = null;
    return null;
  }
  const n = times.length;
  const matrix = series.map((s) => {
    const by = s.rows.length === n ? null : new Map(s.rows.map((r) => [r.t, r]));
    return times.map((tm, i) => { const r = by ? by.get(tm) : s.rows[i]; return r ? +r[key] || 0 : 0; });
  });
  if (o.transform === 'percent') {
    for (let i = 0; i < n; i++) {
      const tot = matrix.reduce((a, m) => a + m[i], 0) || 1;
      matrix.forEach((m) => { m[i] = 100 * m[i] / tot; });
    }
  } else if (o.transform === 'relative') {
    matrix.forEach((m) => { const mx = Math.max(...m) || 1; for (let i = 0; i < n; i++) m[i] = 100 * m[i] / mx; });
  }
  const stacked = o.type === 'stacked';
  const tops = matrix.map((m) => m.slice());
  if (stacked) for (let s = 1; s < tops.length; s++) for (let i = 0; i < n; i++) tops[s][i] += tops[s - 1][i];
  const yMax = Math.max(1, ...tops.flat()) * 1.05;
  const span = Math.max(1, tMax - tMin);
  const xOf = (tm) => L + (tm - tMin) / span * (W - L - R);
  const yOf = (v) => H - B - v / yMax * (H - T - B);
  const tAt = (clientX) => tMin + (clientX - c.getBoundingClientRect().left - L) / (W - L - R) * span;
  g.strokeStyle = 'rgba(255,255,255,.08)'; g.fillStyle = muted;
  const yTicks = small ? 2 : 4;
  // One format for every tick of the axis (not "8425" beside "16.8k").
  const kAxis = yMax >= 10000;
  // Grid lines on round values (500, 1000, 1500), not on quarters of whatever
  // the maximum happens to be (480, 960, 1440).
  const yStep = niceStep(yMax, yTicks);
  for (let v = 0; v <= yMax + 1e-9; v += yStep) {
    const y = yOf(v);
    g.beginPath(); g.moveTo(L, y); g.lineTo(W - R, y); g.stroke();
    g.fillText(!v ? '0' : kAxis ? `${+(v / 1000).toFixed(v < 100000 ? 1 : 0)}k` : String(+v.toFixed(yStep < 1 ? 1 : 0)), 4, y + 4);
  }
  const maxTicks = small ? 4 : 8;
  const step = TICK_STEPS.find((s) => span / s <= maxTicks) || TICK_STEPS[TICK_STEPS.length - 1];
  // The origin is always labelled; then every step.
  if (tMin % step && xOf(Math.ceil(tMin / step) * step) - xOf(tMin) > 50) g.fillText(fmtTime(tMin), xOf(tMin), H - (small ? 5 : 8));
  for (let tm = Math.ceil(tMin / step) * step; tm <= tMax; tm += step) g.fillText(fmtTime(tm), Math.max(L, xOf(tm) - 14), H - (small ? 5 : 8));
  g.save();
  g.beginPath(); g.rect(L, T - 2, W - L - R, H - T - B + 2); g.clip();
  for (let s = tops.length - 1; s >= 0; s--) {
    const color = playerMarkColor(series[s].p.id);
    g.beginPath();
    for (let i = 0; i < n; i++) { const x = xOf(times[i]), y = yOf(tops[s][i]); if (i) g.lineTo(x, y); else g.moveTo(x, y); }
    if (stacked) {
      for (let i = n - 1; i >= 0; i--) g.lineTo(xOf(times[i]), yOf(s ? tops[s - 1][i] : 0));
      g.closePath(); g.globalAlpha = 0.55; g.fillStyle = color; g.fill(); g.globalAlpha = 1;
    } else { g.lineWidth = small ? 1.5 : 2; g.strokeStyle = color; g.stroke(); }
  }
  const inRange = (tm) => tm >= tMin && tm <= tMax;
  if (o.techMarks) {
    const ageLabelX = [];
    const ages = (S.events || []).filter((e) => e.kind === 'age_up' && !hidden.has(e.player) && inRange(e.t));
    for (const e of ages) {
      g.strokeStyle = playerMarkColor(e.player); g.setLineDash([3, 3]);
      g.beginPath(); g.moveTo(xOf(e.t), T); g.lineTo(xOf(e.t), H - B); g.stroke(); g.setLineDash([]);
    }
    // Labels after every line, on a dark backing; ones close together step down
    // instead of printing over each other.
    for (const e of ages) {
      const x = xOf(e.t), label = ['', 'II', 'III', 'IV'][e.age] || '';
      let row = 0;
      while (ageLabelX.some(([px, r]) => r === row && Math.abs(px - x) < 22)) row++;
      ageLabelX.push([x, row]);
      const y = T + 10 + row * 11;
      g.fillStyle = 'rgba(10,12,16,.8)'; g.fillRect(x + 1, y - 9, g.measureText(label).width + 3, 11);
      g.fillStyle = playerMarkColor(e.player); g.fillText(label, x + 2, y);
    }
  }
  if (o.ecoTechs || o.milTechs) {
    for (const e of S.events || []) {
      if (e.kind !== 'researched' || hidden.has(e.player) || !inRange(e.t)) continue;
      const eco = ECO_TECHS.has(e.tech), mil = MIL_TECHS.has(e.tech);
      if (!((eco && o.ecoTechs) || (mil && o.milTechs))) continue;
      g.fillStyle = playerMarkColor(e.player);
      g.beginPath(); g.arc(xOf(e.t), H - B - 4, 3, 0, Math.PI * 2); g.fill();
    }
  }
  if (inRange(S.t)) { g.strokeStyle = '#fff'; g.lineWidth = 1; g.beginPath(); g.moveTo(xOf(S.t), T); g.lineTo(xOf(S.t), H - B); g.stroke(); }
  g.restore();
  const tipEl = $('tooltip');
  const pct = o.transform === 'actual' ? '' : '%';
  c.onmousemove = (ev) => {
    if (!tipEl) return;
    const at = tAt(ev.clientX);
    let i = 0; while (i < n - 1 && times[i + 1] <= at) i++;
    tipEl.classList.remove('hidden');
    patchHtml(tipEl, `<b>${fmtTime(times[i])}</b> · ${esc(seriesLabel(key))}<br>` + series.map((s, k) => `<span style="color:${playerTextColor(s.p.id)}">${esc(playerName(s.p.id))}</span> ${fmtNum(matrix[k][i])}${pct}`).join('<br>'));
    // Beside the pointer, flipped to the other side near the window's edges.
    const r = tipEl.getBoundingClientRect();
    const x = ev.clientX + 14 + r.width > window.innerWidth - 4 ? ev.clientX - 14 - r.width : ev.clientX + 14;
    const y = ev.clientY + 10 + r.height > window.innerHeight - 4 ? ev.clientY - 10 - r.height : ev.clientY + 10;
    tipEl.style.left = Math.max(4, x) + 'px'; tipEl.style.top = Math.max(4, y) + 'px';
  };
  c.onmouseleave = () => tipEl && tipEl.classList.add('hidden');
  const doSeek = (ev) => {
    const f = seekFn(seek);
    if (!f) return;
    const at = Math.max(tMin, Math.min(tMax, tAt(ev.clientX)));
    f(at);
    toast(t('Jumped to {time}', { time: fmtTime(at) }));
    if (o.onSeek) o.onSeek(at);
  };
  c.oncontextmenu = (ev) => { ev.preventDefault(); doSeek(ev); };
  c.onclick = o.clickSeek ? doSeek : null;
  c._tAt = tAt;
  return { tMin, tMax };
}

// -- statistics overlay -------------------------------------------------------------------

let statsSeek = null, statsTimer = null, aggAt = -1e12, aggPending = false, statsRenderVersion = 0;
const statsDrawn = { t: -1, end: -1, series: null, span: -1, from: -1 };

function summaryUrl(at) {
  const following = S.session && S.session.mode === 'live' && S.followLive;
  return following || at == null ? '/api/summary' : `/api/summary?t=${Math.max(0, Math.round(at))}`;
}

function timeStrip() {
  const b = (act, label, name, detail) => `<button data-tc="${act}" ${tip(t(name), detail ? t(detail) : '')}>${label}</button>`;
  return `<div class="stats-tc" id="stats-tc">
    ${b('jumpStart', '⏮', 'Jump to start')}${b('skipBack', '−30s', 'Skip back 30s')}
    <button data-tc="playPause" id="stc-play" ${tip(t('Pause / play'))}>⏯</button>
    ${b('skipForward', '+30s', 'Skip forward 30s')}${b('jumpLive', '⏭', 'Jump to live / end')}
    ${b('speedStepDown', '«', 'Slower', 'Below pause the replay plays in reverse')}<span id="stc-speed" class="num"></span>${b('speedStepUp', '»', 'Faster')}
    <input type="range" id="stc-range" min="0" max="1" step="100" ${settings.disableScrubbing ? 'disabled' : ''} ${tip(t('View time'), t('Charts and tables show the values at this time'))}>
    <span id="stc-time" class="num"></span>
    <button class="link" id="stc-hide" ${tip(t('Hide time controls'), t('Turn them back on in Settings → Interface'))}>${t('Hide')}</button>
  </div>`;
}

function runTimeAction(act) {
  const fn = actions()[act];
  if (fn) { fn(); return; }
  const sk = seekFn(statsSeek);
  if (act === 'playPause') S.playing = !S.playing;
  else if (act === 'skipBack' && sk) sk(S.t - 30000);
  else if (act === 'skipForward' && sk) sk(S.t + 30000);
  else if (act === 'jumpStart' && sk) sk(S.start);
  else if (act === 'jumpLive') { if (sk) sk(S.end); S.followLive = true; }
}

function updateStrip() {
  const r = $('stc-range');
  if (!r) return;
  r.min = String(Math.floor(S.start || 0)); r.max = String(Math.ceil(Math.max(S.end, (S.start || 0) + 1)));
  if (document.activeElement !== r) r.value = String(Math.round(S.t));
  const live = S.session && S.session.mode === 'live' && S.followLive;
  $('stc-time').textContent = `${fmtTime(S.t)} / ${fmtTime(S.end)}`;
  $('stc-speed').textContent = live ? t('LIVE') : `${S.playing ? '' : '❚❚ '}${SPEEDS[S.speedIndex]}×`;
  $('stc-play').textContent = S.playing ? '❚❚' : '▶';
}

function windowLabel() {
  const w = $('ch-window');
  if (!w) return;
  const [a, b] = chartWindow();
  w.textContent = chartState.span ? `${fmtTime(a)}–${fmtTime(b)}` : t('Whole game');
  const prev = $('ch-prev'), next = $('ch-next'), [f0, f1] = fullRange();
  if (prev) prev.disabled = !chartState.span || a <= f0;
  if (next) next.disabled = !chartState.span || b >= f1;
}

function drawStatsChart() {
  drawChart($('chart'), {}, statsSeek);
  Object.assign(statsDrawn, { t: S.t, end: S.end, series: S.series, span: chartState.span, from: chartState.from });
  windowLabel();
}

function refreshAggregates(force) {
  if (aggPending || (!force && Math.abs(S.t - aggAt) < 2000)) return;
  aggPending = true;
  const at = S.t;
  api(summaryUrl(at)).then((sm) => {
    S.summary = sm; aggAt = at;
    const box = $('stats-agg');
    if (box && isOpen('overlay-stats')) patchHtml(box, aggregates(chartState.tab));
  }).catch(() => {}).finally(() => { aggPending = false; });
}

function statsTick() {
  if (!isOpen('overlay-stats')) { clearInterval(statsTimer); statsTimer = null; return; }
  const moved = Math.abs(S.t - statsDrawn.t) > 250 || S.end !== statsDrawn.end || S.series !== statsDrawn.series;
  if (moved) drawStatsChart();
  updateStrip();
  refreshAggregates(false);
}

export async function renderStats(seek, metric = null) {
  const mapped = DASH_HISTORY[metric] || metric;
  const tab = mapped && Object.keys(TABS).find((key) => TABS[key].series.includes(mapped));
  if (tab) { chartState.tab = tab; chartState.key = mapped; }
  if (seek) statsSeek = seek;
  const el = $('overlay-stats'), version = ++statsRenderVersion, generation = S.session?.generation;
  el.setAttribute('aria-busy', 'true');
  if (!el.querySelector('#chart') || el._statsGeneration !== generation) {
    el.innerHTML = `${closeBtn()}<div role="status" class="review-loading" aria-label="${t('Loading')}">◌</div>`;
  }
  wireClose(el);
  const needSeries = !S.series || S.seriesAt < S.end - 5000 || !S.complete;
  const [series, summary] = await Promise.all([
    needSeries ? refreshSeries().catch(() => S.series) : Promise.resolve(S.series),
    api(summaryUrl(S.t)).catch(() => S.summary),
  ]);
  if (version !== statsRenderVersion || generation !== S.session?.generation) return;
  S.series = series; S.summary = summary;
  el._statsGeneration = generation;
  aggAt = S.t;
  const keys = tabSeries(chartState.tab);
  if (!keys.includes(chartState.key)) chartState.key = keys[0];
  const zb = (id, label, name, detail) => `<button id="${id}" ${tip(t(name), detail ? t(detail) : '')}>${label}</button>`;
  // Statistics opens on the whole game for every player. Investigating (one
  // interval, two players) takes over the chart only when it was asked for: a
  // value clicked on the dashboard, or an interval already chosen.
  const investigating = !!metric || !!S.reviewRange;
  el.innerHTML = `${closeBtn()}<h2>${t('Statistics')}</h2>
    <div class="tabs">${Object.entries(TABS).map(([k, tab]) => `<button data-tab="${k}" class="${k === chartState.tab ? 'on' : ''}">${t(tab.title)}</button>`).join('')}</div>
    ${settings.showStatsTimeControls ? timeStrip() : ''}
    <div class="chart-controls">
      <select id="ch-key" ${tip(t('Chart'), t('The value plotted for every player'))}>${keys.map((k) => `<option value="${k}" ${k === chartState.key ? 'selected' : ''}>${esc(seriesLabel(k))}</option>`).join('')}</select>
      <details class="review-chart-options"><summary>${t('Chart options')}</summary><div>
      <select id="ch-type"><option value="line">${t('Line')}</option><option value="stacked">${t('Stacked')}</option></select>
      <select id="ch-transform"><option value="actual">${t('Actual')}</option><option value="percent">${t('% of current total')}</option><option value="relative">${t('Relative to max')}</option></select>
      <label><input type="checkbox" id="ch-techs" ${chartState.techMarks ? 'checked' : ''}> ${t('Age-ups')}</label>
      <label><input type="checkbox" id="ch-eco" ${chartState.ecoTechs ? 'checked' : ''}> ${t('Eco techs')}</label>
      <label><input type="checkbox" id="ch-mil" ${chartState.milTechs ? 'checked' : ''}> ${t('Military techs')}</label>
      <button id="ch-save">${t('Save options')}</button><button id="ch-reset">${t('Reset')}</button><button id="ch-export" ${tip(t('Export stats'), t('Download the statistics as JSON and the series as CSV'))}>${t('Export stats')}</button>
      </div></details>
      <span class="chart-zoom">
        ${zb('ch-prev', '◀', 'Previous', 'Page to the earlier part of the game')}
        ${zb('ch-zoomout', '−', 'Zoom out')}
        <span id="ch-window" class="num"></span>
        ${zb('ch-zoomin', '+', 'Zoom in', 'Narrow the chart to a shorter stretch of time around the viewed time')}
        ${zb('ch-next', '▶', 'Next', 'Page to the later part of the game')}
        ${zb('ch-zoomreset', t('All'), 'Whole game')}
      </span>
    </div>
    <div class="legend">${players().map((p) => `<label><input type="checkbox" data-pid="${p.id}" ${chartState.hidden.has(p.id) ? '' : 'checked'}><i style="background:${playerMarkColor(p.id)}"></i>${esc(playerName(p.id))}</label>`).join('')}
      <span class="hint">${t('Hover to compare · wheel to zoom · right-click to jump to that time')}</span></div>
    ${chartState.tab === 'bonus' ? `<div id="stats-agg">${aggregates('bonus')}</div><details class="review-chart-options"><summary>${t('Investigate')}</summary>${investigationHtml(chartState.key)}</details>` : ''}
    <div class="chart-wrap"><canvas id="chart"></canvas></div>
    ${chartState.tab === 'bonus' ? '' : `<details class="review-details review-investigate" ${investigating ? 'open' : ''}><summary>${t('Investigate')}</summary>${investigationHtml(chartState.key)}</details>
    <details class="review-details" open><summary>${t('Totals')}</summary><div id="stats-agg">${aggregates(chartState.tab)}</div></details>`}`;
  el.setAttribute('aria-busy', 'false');
  wireClose(el);
  const investigateRange = (from, to, pids) => {
    chartState.from = from; chartState.span = Math.max(1, to - from);
    chartState.hidden = new Set(players().map((p) => p.id).filter((pid) => !pids.includes(pid)));
    el.querySelectorAll('.legend input').forEach((checkbox) => { checkbox.checked = !chartState.hidden.has(+checkbox.dataset.pid); });
    drawStatsChart();
  };
  wireInvestigation(el, chartState.key, seekFn(statsSeek), closeAll, investigateRange, investigating);
  $('ch-type').value = chartState.type;
  $('ch-transform').value = chartState.transform;
  const redraw = () => drawStatsChart();
  // A new tab opens on its own first chart (keeping the old key showed the same
  // chart under a different tab).
  el.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => { if (chartState.tab !== b.dataset.tab) chartState.key = null; chartState.tab = b.dataset.tab; loadChartDefinition(chartState.tab); renderStats(); }));
  $('ch-key').addEventListener('change', (e) => {
    chartState.key = e.target.value;
    el.querySelector('.review-investigation').outerHTML = investigationHtml(chartState.key);
    wireInvestigation(el, chartState.key, seekFn(statsSeek), closeAll, investigateRange, !!S.reviewRange); redraw();
  });
  $('ch-type').addEventListener('change', (e) => { chartState.type = e.target.value; redraw(); });
  $('ch-transform').addEventListener('change', (e) => { chartState.transform = e.target.value; redraw(); });
  $('ch-techs').addEventListener('change', (e) => { chartState.techMarks = e.target.checked; redraw(); });
  $('ch-eco').addEventListener('change', (e) => { chartState.ecoTechs = e.target.checked; redraw(); });
  $('ch-mil').addEventListener('change', (e) => { chartState.milTechs = e.target.checked; redraw(); });
  $('ch-zoomin').addEventListener('click', () => { zoomChart(0.5); redraw(); });
  $('ch-zoomout').addEventListener('click', () => { zoomChart(2); redraw(); });
  $('ch-prev').addEventListener('click', () => { pageChart(-1); redraw(); });
  $('ch-next').addEventListener('click', () => { pageChart(1); redraw(); });
  $('ch-zoomreset').addEventListener('click', () => { chartState.span = 0; redraw(); });
  $('chart').addEventListener('wheel', (e) => {
    e.preventDefault();
    const c = $('chart');
    zoomChart(e.deltaY < 0 ? 0.5 : 2, c && c._tAt ? c._tAt(e.clientX) : undefined);
    redraw();
  }, { passive: false });
  $('ch-save').addEventListener('click', () => {
    const def = { hidden: [...chartState.hidden] };
    for (const k of SAVED_CHART_KEYS) def[k] = chartState[k];
    settings.chartDefinitions = { ...(settings.chartDefinitions || {}), [chartState.tab]: def };
    saveSettings(); toast(t('Chart options saved'));
  });
  $('ch-reset').addEventListener('click', () => {
    const defs = { ...(settings.chartDefinitions || {}) }; delete defs[chartState.tab];
    settings.chartDefinitions = defs; saveSettings();
    Object.assign(chartState, { type: 'line', transform: 'actual', techMarks: true, ecoTechs: false, milTechs: false, hidden: new Set(), span: 0 });
    renderStats();
  });
  $('ch-export').addEventListener('click', exportStats);
  el.querySelectorAll('.legend input').forEach((cb) => cb.addEventListener('change', () => {
    const pid = +cb.dataset.pid;
    if (cb.checked) chartState.hidden.delete(pid); else chartState.hidden.add(pid);
    redraw();
  }));
  el.querySelectorAll('[data-tc]').forEach((b) => b.addEventListener('click', () => { runTimeAction(b.dataset.tc); statsTick(); }));
  const range = $('stc-range');
  if (range) range.addEventListener('input', () => { const sk = seekFn(statsSeek); if (sk) sk(+range.value); statsTick(); });
  const hide = $('stc-hide');
  if (hide) hide.addEventListener('click', () => { settings.showStatsTimeControls = false; saveSettings(); renderStats(); });
  drawStatsChart();
  updateStrip();
  if (!statsTimer) statsTimer = setInterval(statsTick, 250);
}

// -- aggregate tables ---------------------------------------------------------------------------

const nv = (x) => (x == null || Number.isNaN(x) ? undefined : fmtNum(x));
const pair = (a, b) => (a == null && b == null ? undefined : `${fmtNum(a ?? 0)} / ${fmtNum(b ?? 0)}`);
const tm = (s) => (s == null ? undefined : fmtTime(s * 1000));
const scoreParts = (v) => v.score_parts || v.score || null;
const unitImg = (mid) => {
  const src = unitIcon(+mid);
  const name = unitInfo(+mid).name;
  return src ? `<img class="agg-icon" src="${src}" alt="" ${tip(name)}>` : esc(name);
};
const apmOf = (pid) => (S.view && S.view.apm && S.view.apm[pid]) || null;

// Row = [label, (summary, view player, player) -> html | undefined, tooltip detail, opts].
// opts.best ('max' | 'min') + opts.num (same arguments -> number) mark the best
// value of the row (best-value highlight); opts.sub indents the
// row under the one above it (the score sub-columns).
// Counters the keyframe carries come from the view (always at the viewed time);
// whole-game aggregates (peaks, averages, floating) come from /api/summary?t=.
const numOf = (x) => (x == null || x === '' || Number.isNaN(+x) ? undefined : +x);
const N = (label, get, detail, best = 'max', extra = {}) => [label, (s, v, p) => nv(numOf(get(s, v, p))), detail, { best, num: (s, v, p) => numOf(get(s, v, p)), ...extra }];
const scoreSub = (s, v) => v.score_sub || s.score_sub || {};
const scoreTotal = (s, v) => { const sp = scoreParts(v); return sp ? Object.values(sp).reduce((a, x) => a + (+x || 0), 0) : (s.score ?? undefined); };
const AGG = {
  score: [
    ['Placing', (s) => (s.placing ? ordinal(s.placing) : undefined), 'By result, then by score', { best: 'min', num: (s) => s.placing || undefined }],
    N('Score', scoreTotal),
    N('Military score', (s, v) => (scoreParts(v) || {}).military),
    N('Economy score', (s, v) => (scoreParts(v) || {}).economy),
    N('Units & buildings', (s, v) => scoreSub(s, v).units_buildings, 'Score for the units and buildings you own', 'max', { sub: true }),
    N('Resources banked', (s, v) => scoreSub(s, v).resources_banked, 'Score for resources collected and kept', 'max', { sub: true }),
    N('Technology score', (s, v) => (scoreParts(v) || {}).technology),
    N('Exploration', (s, v) => scoreSub(s, v).exploration, 'Score for exploring the map', 'max', { sub: true }),
    N('Research', (s, v) => scoreSub(s, v).research, 'Score for technologies researched', 'max', { sub: true }),
    N('Society score', (s, v) => (scoreParts(v) || {}).society),
    ['Kills / losses', (s, v) => pair(v.kills ?? s.kills, v.deaths ?? s.deaths)],
    N('Resources collected', (s, v) => (v.collected || s.collected || {}).total),
    N('Techs', (s, v) => v.techs_researched ?? s.techs),
  ],
  military: [
    N('Kills', (s, v) => v.kills ?? s.kills),
    N('Losses', (s, v) => v.deaths ?? s.deaths, '', 'min'),
    ['K/D ratio', (s, v) => { const k = v.kills ?? s.kills; return k == null ? undefined : (k / Math.max(1, v.deaths ?? s.deaths ?? 0)).toFixed(2); }, '',
      { best: 'max', num: (s, v) => { const k = v.kills ?? s.kills; return k == null ? undefined : k / Math.max(1, v.deaths ?? s.deaths ?? 0); } }],
    ['Most kills (single unit)', (s) => (s.most_kills && s.most_kills.kills ? `${unitImg(s.most_kills.unit_master)} ${s.most_kills.kills}` : undefined), 'The one unit that killed the most',
      { best: 'max', num: (s) => (s.most_kills ? s.most_kills.kills : undefined) }],
    ['Kills / deaths incl. buildings', (s, v) => pair(v.kills_total ?? s.kills_total, v.deaths_total ?? s.deaths_total)],
    ['Eco kills / eco deaths', (s, v) => pair(v.eco_kills ?? s.eco_kills, v.eco_deaths ?? s.eco_deaths), 'Villagers, trade units and fishing ships'],
    ['R/D (buildings razed / lost)', (s, v) => pair(v.razings ?? s.razings, v.buildings_lost ?? s.buildings_lost)],
    ['C/D (conversions / units lost to conversion)', (s, v) => ((v.desertions ?? s.desertions) == null ? undefined : pair(v.conversions ?? s.conversions, v.desertions ?? s.desertions))],
    N('Kill value', (s, v) => v.kill_value ?? s.kill_value),
    N('Army high (units)', (s) => s.peak_military),
    N('Army value now', (s, v) => v.army_value),
    N('Peak army value', (s, v) => s.peak_army_value ?? v.peak_army_value),
    N('Castles built', (s, v) => v.castles_built ?? s.castles_built),
    N('Wonders built', (s, v) => v.wonders_built ?? s.wonders_built),
  ],
  economy: [
    N('Current villagers', (s, v) => v.villagers),
    N('Peak villagers', (s) => s.peak_villagers),
    N('Fishing ships', (s, v) => v.fishing_ships),
    N('Trade units', (s, v) => v.trade_units),
    N('Trade profit', (s, v) => v.trade_profit ?? s.trade_profit),
    N('Food', (s, v) => (v.collected || s.collected || {}).food),
    N('Wood', (s, v) => (v.collected || s.collected || {}).wood),
    N('Gold', (s, v) => (v.collected || s.collected || {}).gold),
    N('Stone', (s, v) => (v.collected || s.collected || {}).stone),
    N('Total collected', (s, v) => (v.collected || s.collected || {}).total),
    N('Value spent', (s, v) => v.value_spent ?? s.value_spent),
    N('Relic gold', (s, v) => v.relic_gold ?? s.relic_gold),
    ['Tribute sent / received', (s, v) => pair(v.tribute_sent ?? s.tribute_sent, v.tribute_received ?? s.tribute_received)],
    ['Market sold / bought', (s, v) => pair(v.market_sold ?? s.market_sold, v.market_bought ?? s.market_bought)],
    ['Market gold gained / spent', (s, v) => pair(v.market_gold_gained ?? s.market_gold_gained, v.market_gold_spent ?? s.market_gold_spent)],
    ['Floating (avg / peak)', (s) => (s.floating ? pair(s.floating.avg, s.floating.peak) : undefined), 'Unspent resources'],
    ['FloatHrs', (s) => (s.float_hrs == null ? undefined : (+s.float_hrs).toFixed(1)), 'Unspent resources summed over time, in resource-hours', { best: 'min', num: (s) => numOf(s.float_hrs) }],
    ['Villager idle time', (s) => (s.idle_seconds == null ? undefined : `${fmtNum(Math.round(s.idle_seconds / 60))} ${t('vil·min')}`), 'Villager-minutes idle (villagers × minutes)', { best: 'min', num: (s) => numOf(s.idle_seconds) }],
    ['Worker efficiency', (s) => (s.efficiency == null ? undefined : s.efficiency + '%'), '', { best: 'max', num: (s) => numOf(s.efficiency) }],
    ['Worst minute efficiency', (s) => (s.worst_minute_efficiency == null ? undefined : s.worst_minute_efficiency + '%'), '', { best: 'max', num: (s) => numOf(s.worst_minute_efficiency) }],
    ['Idle TC time', (s) => tm(s.tc_idle_seconds), '', { best: 'min', num: (s) => numOf(s.tc_idle_seconds) }],
    ['Housed time', (s) => tm(s.housed_seconds), '', { best: 'min', num: (s) => numOf(s.housed_seconds) }],
  ],
  technology: [
    ['Current age', (s, v) => (v.age == null ? undefined : esc(AGE_NAMES[v.age] || String(v.age)))],
    [() => `${AGE_NAMES[1]} Age`, (s) => (s.age_times ? (s.age_times[1] ? fmtTime(s.age_times[1]) : '–') : undefined), '', { best: 'min', num: (s) => (s.age_times ? s.age_times[1] || undefined : undefined) }],
    [() => `${AGE_NAMES[2]} Age`, (s) => (s.age_times ? (s.age_times[2] ? fmtTime(s.age_times[2]) : '–') : undefined), '', { best: 'min', num: (s) => (s.age_times ? s.age_times[2] || undefined : undefined) }],
    [() => `${AGE_NAMES[3]} Age`, (s) => (s.age_times ? (s.age_times[3] ? fmtTime(s.age_times[3]) : '–') : undefined), '', { best: 'min', num: (s) => (s.age_times ? s.age_times[3] || undefined : undefined) }],
    N('Techs researched', (s, v) => v.techs_researched ?? s.techs),
  ],
  society: [
    ['Map explored', (s) => (s.explored == null ? undefined : s.explored + '%'), '', { best: 'max', num: (s) => numOf(s.explored) }],
    ['Relics (current / max)', (s, v) => pair(v.relics, v.relics_max ?? s.relics_max)],
    N('Relic gold', (s, v) => v.relic_gold ?? s.relic_gold),
    N('Conversions', (s, v) => v.conversions ?? s.conversions),
    ['Tribute sent / received', (s, v) => pair(v.tribute_sent ?? s.tribute_sent, v.tribute_received ?? s.tribute_received)],
    N('Castles built', (s, v) => v.castles_built ?? s.castles_built),
    N('Wonders built', (s, v) => v.wonders_built ?? s.wonders_built),
    ['Status', (s, v) => (v.status ?? s.status) && esc(t(v.status ?? s.status))],
  ],
  apm: [
    N('Current APM', (s, v, p) => (apmOf(p.id) || {}).total),
    N('Average APM', (s, v) => s.avg_apm ?? v.apm_avg),
    N('Peak APM', (s, v) => s.peak_apm ?? v.apm_peak),
    N('eAPM', (s, v) => v.eapm ?? s.eapm, 'Effective actions per minute: commands that change something'),
    N('geAPM', (s) => s.geapm, 'Game-effective APM: eAPM without repeated or spammed commands'),
    ['eAPM eco / military', (s, v, p) => { const a = apmOf(p.id); return a ? pair(a.effective_eco ?? a.eco, a.effective_military ?? a.military) : undefined; }],
  ],
  timeline: [],
};

// Indexes of the best cells of a row: the highest (or lowest) value, only when
// at least two players have one and not everyone ties.
function bestCells(nums, dir) {
  const vals = nums.filter((x) => Number.isFinite(x));
  if (!dir || vals.length < 2) return new Set();
  const target = dir === 'min' ? Math.min(...vals) : Math.max(...vals);
  if (vals.every((x) => x === target)) return new Set();
  return new Set(nums.map((x, i) => (x === target ? i : -1)).filter((i) => i >= 0));
}

function aggregates(tab) {
  const sm = S.summary || {};
  const vp = (S.view && S.view.players) || {};
  const ps = players().filter((p) => sm[p.id] || vp[p.id]);
  if (!ps.length) return '';
  if (tab === 'bonus') return bonusIncomeHtml(ps.map((p) => ({ id: p.id, name: playerName(p.id), color: playerTextColor(p.id), income: vp[p.id]?.resource_income || sm[p.id]?.resource_income })));
  const data = ps.map((p) => ({ p, s: sm[p.id] || {}, v: vp[p.id] || {} }));
  const rows = (AGG[tab] || []).map(([lbl, f, detail, opts = {}]) => {
    const label = typeof lbl === 'function' ? lbl() : lbl;
    const cells = data.map((d) => { try { return f(d.s, d.v, d.p); } catch { return undefined; } });
    if (cells.every((x) => x === undefined || x === null)) return '';
    const best = opts.num ? bestCells(data.map((d) => { try { return opts.num(d.s, d.v, d.p); } catch { return undefined; } }), opts.best) : new Set();
    return `<tr class="${opts.sub ? 'agg-sub' : ''}"><td ${tip(t(label), detail ? t(detail) : '')}>${t(label)}</td>${cells.map((x, i) => `<td class="${best.has(i) ? 'best' : ''}">${x ?? '–'}</td>`).join('')}</tr>`;
  }).join('');
  if (!rows) return '';
  const head = `<tr><th></th>${ps.map((p) => `<th class="pname" style="color:${playerTextColor(p.id)}">${esc(playerName(p.id))}</th>`).join('')}</tr>`;
  return `<p class="hint agg-at">${t('Values at {time}', { time: fmtTime(S.t) })} · <span class="best-key">${t('best value')}</span></p><table class="agg">${head}${rows}</table>`;
}

// =====================================================================================
// home: overview, replays, recordings, live
// =====================================================================================

const REPLAY_PAGE = 100;
let homeTab = 'overview', homeFilter = '', replayLimit = REPLAY_PAGE, homeOpened = null;
let openReplay = null;

// Replay filters live in settings (so profiles carry them). Move the older
// localStorage copy over once. Its spoiler flag is dropped: the old default was
// off, the current one is on.
function migrateReplayFilters() {
  try {
    const raw = localStorage.getItem('vantage.replayFilters');
    if (raw == null) return;
    const old = JSON.parse(raw) || {};
    delete old.spoilers;
    settings.replayFilters = { ...DEFAULT_SETTINGS.replayFilters, ...(settings.replayFilters || {}), ...old };
    saveSettings();
    localStorage.removeItem('vantage.replayFilters');
  } catch { /* storage blocked or bad JSON: keep the defaults */ }
}
function replayFilters() {
  const rf = { ...DEFAULT_SETTINGS.replayFilters, ...(settings.replayFilters || {}) };
  settings.replayFilters = rf;
  return rf;
}

// Everything the free-text search looks at: file, map, mode, game, players, civs, AIs.
function replayText(r) {
  return [r.name, r.map, r.mode, r.game === 'ror' ? 'return of rome' : 'aoe2',
    ...(r.players || []).flatMap((p) => [p.name, p.civ, p.ai])].filter(Boolean).join(' ').toLowerCase();
}
// Every word of the query must match a word of the text: contained in it, or
// one typo away from its start (typo-tolerant fuzzy search).
function fuzzyMatch(query, text) {
  const words = text.split(/[\s,.()_@-]+/).filter(Boolean);
  return query.split(/\s+/).filter(Boolean).every((q) => text.includes(q)
    || (q.length >= 4 && words.some((w) => withinOneEdit(q, w.slice(0, q.length + 1)) || withinOneEdit(q, w.slice(0, q.length)))));
}
function withinOneEdit(a, b) {
  if (Math.abs(a.length - b.length) > 1) return false;
  let i = 0, j = 0, edits = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { i++; j++; continue; }
    if (++edits > 1) return false;
    if (a.length > b.length) i++; else if (b.length > a.length) j++; else { i++; j++; }
  }
  return edits + (a.length - i) + (b.length - j) <= 1;
}
const SETTING_LABELS = {
  map_size: 'Map size', difficulty: 'AI difficulty', speed_name: 'Game speed', population: 'Population',
  starting_resources_id: 'Starting resources', starting_age_id: 'Starting age', ending_age_id: 'Ending age',
  reveal_map_id: 'Reveal map', victory_type_id: 'Victory', treaty_minutes: 'Treaty (minutes)', lock_teams: 'Lock teams',
  lock_speed: 'Lock speed', team_positions: 'Team positions', shared_exploration: 'Shared exploration', cheats: 'Cheats',
  all_techs: 'Full tech tree', turbo: 'Turbo mode', handicap: 'Handicap', ranked: 'Ranked', multiplayer: 'Multiplayer',
  rms_file: 'Custom map script', scenario_file: 'Scenario', save_version: 'Save version', version: 'Format',
};
// Lobby values whose meaning was confirmed against the game's own lobby screen;
// anything else is shown as the raw id.
const SETTING_VALUES = {
  starting_resources_id: { 0: 'Standard' }, starting_age_id: { 0: 'Standard' }, ending_age_id: { 0: 'Standard' },
  reveal_map_id: { 0: 'Normal' }, victory_type_id: { 9: 'Standard' }, treaty_minutes: { 0: 'None' },
};
// Lobby colour ids (0 blue … 7 orange) for the replay list.
const COLOR_CSS = ['#2d5ce8', '#e2231a', '#00a651', '#ffd700', '#00c5cd', '#9b30ff', '#9a9a9a', '#ff8c00'];

// 'current' | 'old' | 'unknown' from the backend; older servers only say
// whether the build is the newest one among the replays.
function versionState(r) {
  if (r.version_state) return r.version_state;
  if (r.current_build === undefined) return 'unknown';
  return r.current_build ? 'current' : 'old';
}
function versionCell(r) {
  const vs = versionState(r);
  const build = esc(r.build || '?');
  if (vs === 'current') return `<td ${tip(r.compatible || '')}>${build}</td>`;
  const msg = vs === 'old'
    ? t('Old game version: recorded on build {b}; the running game (build {cur}) may refuse to load it', { b: r.build || '?', cur: r.newest_build || r.game_build || '?' })
    : t('Unknown game version: Vantage cannot tell whether the running game can load it');
  return `<td class="warn" ${tip(vs === 'old' ? t('Old version') : t('Unknown version'), msg)}>⚠ ${build} <span class="hint">${vs === 'old' ? t('old version') : t('unknown version')}</span></td>`;
}

function replayDetails(r, spoilers) {
  const yes = (k, v) => (v === true ? t('Yes') : v === false ? t('No') : SETTING_VALUES[k] && SETTING_VALUES[k][v] ? t(SETTING_VALUES[k][v]) : esc(String(v)));
  const settingsRows = Object.entries(r.settings || {}).map(([k, v]) => `<span class="kv"><b>${t(SETTING_LABELS[k] || k)}</b> ${yes(k, v)}</span>`).join('');
  const name = (n) => esc(((r.players || []).find((p) => p.number === n) || {}).name || `P${n}`);
  const result = !spoilers ? `<p class="hint">${t('Result hidden (spoilers off).')}</p>`
    : r.winners === undefined ? '<p class="hint">…</p>'
    : `<p><b>${t('Winner')}:</b> ${(r.winners || []).length ? r.winners.map(name).join(', ') : t('unknown')}
       ${(r.resigned || []).length ? `<br><b>${t('Resigned')}:</b> ${r.resigned.map(([n, ms]) => `${name(n)} (${fmtTime(ms)})`).join(', ')}` : ''}</p>`;
  const elo = (p) => (!spoilers ? t('hidden') : p.elo ? esc(p.elo) : '–');
  const ps = (r.players || []).map((p) => `<tr><td style="color:${COLOR_CSS[p.color] || '#888'}">${esc(p.name)}</td><td>${esc(p.civ)}</td><td>${p.team || '–'}</td><td>${p.human ? t('Human') : esc(p.ai || 'AI')}</td><td>${t('Elo')}: ${elo(p)}</td></tr>`).join('');
  const vs = versionState(r);
  const warn = vs === 'current' ? '' : `<p class="warn">⚠ ${vs === 'old' ? t('Recorded on an older game version; the game may refuse to load it.') : t('Unknown game version; loading may fail.')}</p>`;
  return `<div class="rdetails">${warn}<table class="list">${ps}</table>${result}<div class="kvs">${settingsRows}</div>
    <p class="hint">${esc(r.dir)}/${esc(r.name)}${(r.warnings || []).length ? ' · ' + esc(r.warnings.join('; ')) : ''}</p></div>`;
}

function playerChips(r, spoilers) {
  const won = (p) => (spoilers && (r.winners || []).includes(p.number) ? ' 🏆' : '');
  const elo = (p) => (spoilers && p.elo ? ` <span class="hint">(${esc(p.elo)})</span>` : '');
  return (r.players || []).map((p) => `<span class="rp" style="border-color:${COLOR_CSS[p.color] || '#888'}" ${tip((p.civ || '') + (p.ai ? ' · ' + p.ai : ''))}>${esc(p.name)}${p.team ? `<sup>${p.team}</sup>` : ''}${elo(p)} <span class="hint">${esc(p.civ)}</span>${won(p)}</span>`).join(' ');
}

function filterReplays(reps, rf, f) {
  const who = (rf.player || '').trim().toLowerCase();
  return reps.filter((r) => {
    const ps = r.players || [];
    if (f && !(rf.strict ? r.name.toLowerCase().includes(f) : fuzzyMatch(f, replayText(r)))) return false;
    if (who && !ps.some((p) => String(p.name || '').toLowerCase().includes(who))) return false;
    if (rf.game && (r.game || 'aoe2') !== rf.game) return false;
    if (rf.civ && !ps.some((p) => p.civ === rf.civ)) return false;
    if (rf.mode && r.mode !== rf.mode) return false;
    if (rf.players === 'humans' && ps.some((p) => !p.human)) return false;
    if (rf.players === 'ai' && !ps.some((p) => !p.human)) return false;
    if (rf.count && ps.length !== +rf.count) return false;
    if (rf.compatible && versionState(r) === 'old') return false;
    return true;
  });
}

// "9 Nov, 09:22": the year only when it is not this one, the full date and
// time on hover. toLocaleString's "11/9/2026, 9:22:33 AM" wrapped in every row.
function date(s) {
  if (!s) return '–';
  const d = new Date(s * 1000);
  const opts = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return `<span class="when" title="${esc(d.toLocaleString())}">${esc(d.toLocaleString(language || undefined, opts))}</span>`;
}

// One recording as the lists show it: who played (recording_summary on the
// server reads that in the background), else its file name.
function recordingGame(r) {
  const sm = r.summary;
  if (sm && sm.players && sm.players.length) {
    // Lobby teams are numbered in slot order, as the replay list numbers them
    // (a key of 100 or more is a player without a team).
    const keys = [...new Set(sm.players.map((p) => p.team).filter((k) => k && k < 100))];
    const team = (p) => (keys.includes(p.team) ? `<sup>${keys.indexOf(p.team) + 1}</sup>` : '');
    const chips = sm.players.map((p) => `<span class="rp" style="border-color:${esc(p.color || '#888')}">${esc(p.name)}${team(p)} <span class="hint">${esc(p.civ || '')}</span></span>`).join(' ');
    return `<div class="rec-game">${chips}</div><div class="rec-file hint">${esc(r.name)}</div>`;
  }
  return `<div class="rec-game">${esc(r.name)}</div>${r.summary_pending ? `<div class="rec-file hint">${t('Loading…')}</div>` : ''}`;
}
const recordingMap = (r) => esc((r.summary && r.summary.map) || '');
const recordingLength = (r) => (r.summary && r.summary.duration_ms ? fmtTime(r.summary.duration_ms) : '');
const mb = (n) => (n / 1048576).toFixed(1) + ' MB';
const gameName = (g) => (g === 'ror' ? t('Return of Rome') : 'AoE2');

// A replay whose header could not be read shows only "Missing rec data".
const missingData = (r) => !!(r.missing_data || r.error);

function replayRow(r, i, rf, withDetails) {
  if (missingData(r)) {
    return `<tr class="rrow missing" data-i="${i}" ${tip(r.name, r.error || '')}><td colspan="2"><span class="missing-rec">${t('Missing rec data')}</span> <span class="hint">${esc(r.name)}</span></td>
      <td>—</td><td>${date(r.started_at || r.mtime)}</td><td></td>
      <td><button data-play="${i}" ${watchAttrs()}>${t('Watch')}</button></td></tr>
      ${withDetails && openReplay === r.dir + '/' + r.name ? `<tr class="rdetail"><td colspan="6"><div class="rdetails"><p class="warn">⚠ ${t('Missing rec data')}${r.error ? ': ' + esc(r.error) : ''}</p><p class="hint">${esc(r.dir)}/${esc(r.name)}</p></div></td></tr>` : ''}`;
  }
  const dur = rf.spoilers ? (r.duration_ms ? fmtTime(r.duration_ms) + (r.complete ? '' : ' *') : '…') : '—';
  return `<tr class="rrow" data-i="${i}" ${tip(r.name)}><td>${r.error ? esc(r.name) : playerChips(r, rf.spoilers)}</td>
    <td>${esc(r.map || '')}<div class="hint">${esc(r.mode || '')}${r.game === 'ror' ? ' · ' + gameName('ror') : ''}</div></td>
    <td>${dur}</td><td>${date(r.started_at || r.mtime)}</td>${versionCell(r)}
    <td><button data-play="${i}" class="${versionState(r) === 'old' ? 'warn' : ''}" ${watchAttrs()}>${t('Watch')}</button></td></tr>
    ${withDetails && openReplay === r.dir + '/' + r.name ? `<tr class="rdetail"><td colspan="6">${replayDetails(r, rf.spoilers)}</td></tr>` : ''}`;
}

// -- first run: what live games and replays need ---------------------------------------
// /api/session reports the certificate folder and the files missing from it; with
// ?probe=1 also whether the game answers on its API port. Without the files the
// game refuses every connection, so the buttons that need it say why instead.
const certsMissing = (sess) => (sess && sess.certs && sess.certs.missing) || [];
let watchBlock = '';
function watchAttrs() {
  // Local replay playback converts the replay here: no game, no certificates.
  if (nativeReplays) return tip(t('Watch'), t('Convert and watch this replay'));
  return watchBlock ? `disabled ${tip(t('Watch'), watchBlock)}` : tip(t('Watch'), t('Ask the running game to open this replay and stream it here'));
}
const certsGuide = (sess) => extLink((sess.certs && sess.certs.docs) || LIVE_DOCS_URL, t('About the certificate files'));
function certsNote(sess) {
  const dir = `<code>${esc((sess.certs && sess.certs.dir) || '')}</code>`;
  const files = certsMissing(sess).map((f) => `<code>${esc(f)}</code>`).join(' ');
  return `<div class="setup-note"><b>⚠ ${t('Certificate files needed')}</b>
    <p>${t('Live games and replays go through the running game, which accepts only a spectator app holding its client certificate. Vantage cannot ship it: put these files in {dir}:', { dir })} ${files}</p>
    <p>${certsGuide(sess)} · <span class="hint">${t('Recordings (.vrec) play without them.')}</span></p></div>`;
}
function gameOffNote() {
  return `<div class="setup-note"><b>${t('Age II is not running')}</b>
    <p>${t('Live games and replays are streamed by the running game. Start it, then connect.')} <button data-start-game>▶ ${t('Start Age II')}</button></p></div>`;
}
function setupList(sess) {
  const row = (ok, label, detail) => `<li class="${ok ? 'ok' : 'warn'}"><span class="setup-mark">${ok ? '✔' : '⚠'}</span><b>${label}</b> <span class="hint">${detail}</span></li>`;
  const missing = certsMissing(sess);
  const dir = esc((sess.certs && sess.certs.dir) || '');
  const running = sess.game_api_open;
  return `<ul class="setup-list">
    ${row(!!sess.game_dir, t('Game install'), sess.game_dir ? esc(sess.game_dir) : `${t('Not found: icons, unit graphics and sounds come from it.')} <button class="link" data-settings>${t('Set the game folder')}</button>`)}
    ${row(!missing.length, t('Certificate files'), missing.length ? `${t('Missing from {dir}', { dir })} ${certsGuide(sess)}` : dir)}
    ${running === undefined ? '' : row(running, t('Age II'), running ? t('Running') : `${t('Not running')} <button class="link" data-start-game>${t('Start Age II')}</button>`)}
  </ul>`;
}
function startCard(recs, reps, sess) {
  const noCerts = certsMissing(sess).length > 0;
  const gameOff = sess.game_api_open === false;
  const liveWhy = noCerts ? t('Needs the certificate files (see below).')
    : gameOff ? t('Start Age II first; Vantage connects once it is running.')
      : t('Watch the game Age II is showing, or join a lobby as a spectator.');
  const repWhy = noCerts ? t('Watching one needs the certificate files.') : gameOff ? t('Watching one needs Age II running.') : '';
  return `<section class="ov-card ov-session"><h3>${t('Get started')}</h3>
    <div class="start-grid">
      <div><button class="on" data-goto="recordings">${t('Open a recording')}</button>
        <p class="hint">${t('Recordings (.vrec) play right away, without the game.')} ${recs.length ? t('{n} found.', { n: recs.length }) : ''}</p></div>
      <div><button data-goto="live" ${noCerts ? 'disabled' : ''}>${t('Watch live')}</button><p class="hint">${liveWhy}</p></div>
      <div><button data-goto="replays">${t('Browse replays')}</button>
        <p class="hint">${reps.length ? t('{n} replays in your profile folders.', { n: reps.length }) : t('No replays found in your profile folders.')} ${repWhy}</p></div>
    </div>
    ${setupList(sess)}</section>`;
}

// Connection errors in plain words; anything else is shown as the server said it.
export const gameUnreachable = (err) => /no CadeRemote server reachable|UNAVAILABLE|Connection refused|failed to connect/i.test(err);
export function friendlyError(err) {
  if (/certificate files missing/i.test(err)) return t('Certificate files missing: live games and replays cannot connect');
  if (/refused the secure connection/i.test(err)) return t('The game refused the connection: check the certificate files — retrying…');
  if (gameUnreachable(err)) return t('No game found. Start Age of Empires II: DE (Vantage connects to its spectator port 4341) — retrying…');
  if (/TSI_DATA_CORRUPTED|Stream removed/i.test(err)) return t('The game dropped the stream — reconnecting…');
  return t(err);
}

function sessionBox(sess, withRecording = true) {
  const src = sess.source || {};
  const lines = [];
  if (sess.mode === 'recording') lines.push(`<b>${t('Recording')}</b> ${esc(baseName(src.path))}`);
  else if (sess.mode === 'live') {
    lines.push(`<b>${t('Live game')}</b> ${esc(src.host || '127.0.0.1')}:${esc(src.port || 4341)}${src.status ? ' · ' + esc(t(String(src.status).replace(/_/g, ' '))) : ''}${sess.live_connected === false && src.status !== 'ended' ? ' · ' + t('reconnecting…') : ''}`);
    if (src.lobby) lines.push(`${t('Lobby')}: ${esc(typeof src.lobby === 'object' ? (src.lobby.name || src.lobby.id || JSON.stringify(src.lobby)) : src.lobby)}`);
    if (src.replay) lines.push(`${t('Replay')}: ${esc(baseName(src.replay))}`);
    if (src.waiting && (Array.isArray(src.waiting) ? src.waiting.length : true)) lines.push(`<span class="warn">${t('Waiting for players…')}</span>`);
  } else lines.push(t('Nothing open yet. Pick a replay or a recording below, or connect to a live game.'));
  if (src.load_result != null) lines.push(`${t('Game load result')}: <code>${esc(typeof src.load_result === 'object' ? JSON.stringify(src.load_result) : src.load_result)}</code>`);
  if (src.recording && withRecording) lines.push(`<span class="rec-dot">●</span> ${t('Recording to {file}', { file: esc(baseName(src.recording)) })}`);
  if (src.recording_saved) lines.push(savedLine(src.recording_saved));
  // Once stopped, the last connection error is history, not a problem to fix.
  if (sess.error && !(sess.mode === 'live' && src.status === 'ended')) lines.push(`<span class="warn">⚠ ${esc(friendlyError(sess.error))}</span>`);
  return lines.map((l) => `<div>${l}</div>`).join('');
}
function savedLine(path) {
  return `<span class="saved">✔ ${t('Saved to vault: {file}', { file: esc(baseName(path)) })}</span> <button class="link" data-folder="recordings">${t('Open vault folder')}</button>`;
}

function overviewBody(recs, reps, sess) {
  const rf = replayFilters();
  const recent = reps.filter((r) => !missingData(r)).slice(0, 6);
  const idle = !sess.mode || sess.mode === 'idle';
  return `<div class="home-overview">
    ${idle ? startCard(recs, reps, sess) : `<section class="ov-card ov-session"><h3>${t('Current session')}</h3>${sessionBox(sess)}
      <p><button data-close class="on">${t('Back to watching')}</button></p>${sess.game_dir ? '' : setupList(sess)}</section>`}
    <section class="ov-card"><h3>${t('Recent replays')}</h3>
      ${recent.length ? `<table class="list">${recent.map((r) => `<tr><td>${playerChips(r, rf.spoilers)}</td><td>${esc(r.map || '')}</td><td class="hint">${date(r.started_at || r.mtime)}</td>
        <td><button data-play-ov="${esc(r.dir)}\n${esc(r.name)}" ${watchAttrs()}>${t('Watch')}</button></td></tr>`).join('')}</table>` : `<p class="hint">${t('No replays found in your profile folder.')}</p>`}
      <button class="link" data-goto="replays">${t('All replays ({n})', { n: reps.length })}</button></section>
    <section class="ov-card"><h3>${t('Recent recordings')}</h3>
      ${recs.length ? `<table class="list">${recs.slice(0, 6).map((r) => `<tr><td>${recordingGame(r)}</td><td class="nw">${recordingMap(r)}</td><td class="hint">${date(r.mtime)}</td>
        <td><button data-open="${esc(r.path)}">${t('Open')}</button></td></tr>`).join('')}</table>` : `<p class="hint">${t('No recordings yet. Live sessions can be saved to the vault from the Live game tab.')}</p>`}
      <button class="link" data-goto="recordings">${t('All recordings ({n})', { n: recs.length })}</button></section>
  </div>`;
}

function recordingsBody(recs, f) {
  const rows = recs.filter((r) => !f || r.name.toLowerCase().includes(f) || JSON.stringify([r.header, r.summary]).toLowerCase().includes(f));
  return `<p class="hint">${t('Vantage recordings (.vrec) play back without the game.')}
      <button class="link" data-folder="recordings">${t('Open recordings folder')}</button>
      <button class="link" data-folder="images">${t('Open images folder')}</button></p>
    <table class="list"><tr><th>${t('Recording')}</th><th>${t('Map')}</th><th>${t('Duration')}</th><th>${t('Source')}</th><th>${t('Date')}</th><th>${t('Size')}</th><th></th></tr>
    ${rows.map((r) => `<tr><td>${recordingGame(r)}</td><td class="nw">${recordingMap(r)}</td><td class="num">${recordingLength(r)}</td><td class="hint">${esc(baseName((r.header || {}).replay || (r.header || {}).source || ''))}</td><td>${date(r.mtime)}</td><td class="num">${mb(r.size)}</td>
    <td><button data-open="${esc(r.path)}">${t('Open')}</button></td></tr>`).join('')}</table>
    <div class="form-row"><label>${t('Open a .vrec by path')}</label><input id="open-path" size="60"><button id="open-go">${t('Open')}</button></div>`;
}

function replaysBody(reps, f, sess) {
  const rf = replayFilters();
  const civs = [...new Set(reps.flatMap((r) => (r.players || []).map((p) => p.civ)))].filter(Boolean).sort();
  const modes = [...new Set(reps.map((r) => r.mode).filter(Boolean))].sort();
  const counts = [...new Set(reps.map((r) => (r.players || []).length).filter(Boolean))].sort((a, b) => a - b);
  const rows = filterReplays(reps, rf, f);
  renderHome._rows = rows;
  const opt = (v, label, cur) => `<option value="${esc(v)}" ${String(v) === String(cur) ? 'selected' : ''}>${esc(label)}</option>`;
  const shown = rows.slice(0, replayLimit);
  const more = rows.length - shown.length;
  return `${watchBlock ? `<p class="warn">⚠ ${esc(watchBlock)} ${certsGuide(sess)}</p>` : ''}
    <p class="hint">${t(nativeReplays ? 'Replays are converted locally before playback.' : 'Recorded games from your profile. Playing one asks the running game to open it and streams it here (the game must be running).')}
      <button class="link" data-folder="profile">${t('Open profile folder')}</button></p>
    <div class="form-row rf-row">
      <select id="rf-game">${opt('', t('All games'), rf.game)}${opt('aoe2', 'AoE2', rf.game)}${opt('ror', t('Return of Rome'), rf.game)}</select>
      <select id="rf-civ">${opt('', t('All civilisations'), rf.civ)}${civs.map((c) => opt(c, c, rf.civ)).join('')}</select>
      <select id="rf-mode">${opt('', t('All modes'), rf.mode)}${modes.map((m) => opt(m, m, rf.mode)).join('')}</select>
      <select id="rf-players">${opt('', t('Any players'), rf.players)}${opt('humans', t('Humans only'), rf.players)}${opt('ai', t('Includes AI'), rf.players)}</select>
      <select id="rf-count">${opt('', t('Any size'), rf.count)}${counts.map((n) => opt(n, t('{n} players', { n }), rf.count)).join('')}</select>
      <input id="rf-player" size="16" placeholder="${esc(t('Player name…'))}" value="${esc(rf.player || '')}" ${tip(t('Player name'), t('Only replays with a player whose name contains this text'))}>
    </div>
    <div class="form-row rf-row">
      <label class="inline"><input type="checkbox" id="rf-strict" ${rf.strict ? 'checked' : ''}> ${t('Search file names only')}</label>
      <label class="inline" ${tip(t('Hide incompatible'), t('Hide replays recorded on an older game version'))}><input type="checkbox" id="rf-compat" ${rf.compatible ? 'checked' : ''}> ${t('Hide incompatible')}</label>
      <label class="inline" ${tip(t('Spoilers'), t('Show Elo, duration and winner'))}><input type="checkbox" id="rf-spoil" ${rf.spoilers ? 'checked' : ''}> ${t('Show spoilers (Elo, duration, winner)')}</label>
      <button class="link" id="rf-clear">${t('Clear filters')}</button>
    </div>
    <p class="hint">${t('Showing {n} of {m}', { n: rows.length, m: reps.length })}</p>
    <table class="list"><tr><th>${t('Players')}</th><th>${t('Map')}</th><th>${t('Duration')}</th><th>${t('Date')}</th><th>${t('Version')}</th><th></th></tr>
    ${shown.map((r, i) => replayRow(r, i, rf, true)).join('')}</table>
    ${more > 0 ? `<div class="form-row more-row"><span class="hint">${t('{n} more', { n: more })}</span>
      <button id="rf-more">${t('Show {n} more', { n: Math.min(REPLAY_PAGE, more) })}</button><button id="rf-all">${t('Show all')}</button></div>` : ''}`;
}

function liveBody(sess) {
  const src = sess.source || {};
  const live = sess.mode === 'live';
  let rec = '';
  if (live) {
    rec = src.recording
      ? `<p><span class="rec-dot">●</span> ${t('Recording to {file}', { file: esc(baseName(src.recording)) })}
          <button id="rec-stop" ${tip(t('Stop and save'), t('Finish the .vrec and keep it in the vault'))}>${t('Stop and save recording')}</button></p>`
      : `<p><button id="rec-start" class="on" ${tip(t('Save recording now'), t('Start writing this live session to a .vrec in the vault'))}>${t('Save recording now')}</button>
          <span class="hint">${t('Auto-recording is off; nothing of this session is being saved yet.')}</span></p>`;
  }
  const noCerts = certsMissing(sess).length > 0;
  const note = noCerts ? certsNote(sess) : sess.game_api_open === false && !live ? gameOffNote() : '';
  return `${note}<p class="hint">${t("Connect to the game's spectator server (localhost:4341). Works for a match in progress, a replay the game is playing, or a lobby you spectate.")}</p>
    <div class="form-row"><label>${t('Host : port')}</label><input id="live-host" value="${esc(src.host || '127.0.0.1')}" size="14"> <input id="live-port" value="${esc(src.port || 4341)}" size="6"></div>
    <div class="form-row"><label>${t('Spectate lobby id (optional)')}</label><input id="live-lobby" size="20"></div>
    <div class="form-row"><label ${tip(t('Record to .vrec'), t('Save the session to the vault as it streams'))}>${t('Record to .vrec')}</label><input type="checkbox" id="live-record" ${settings.autoRecord ? 'checked' : ''}></div>
    <button id="live-go" class="on" ${noCerts ? `disabled ${tip(t('Connect'), t('Needs the certificate files (see above).'))}` : ''}>${t('Connect')}</button>
    ${live ? `<button id="live-stop" ${tip(t('Stop watching'), t('Disconnect from the game'))}>${t('Stop watching')}</button>` : ''}
    <h3>${t('Session')}</h3><div class="ov-card">${sessionBox(sess, false)}</div>${rec}`;
}

async function playReplay(r, confirmed = false) {
  const body = { name: r.name, dir: r.dir, record: settings.autoRecord };
  if (confirmed) body.confirm = true;
  const res = await api('/api/play_replay', body).catch((e) => ({ ok: false, error: String(e) }));
  if (res && res.needs_confirm) {
    const code = res.code != null ? `<br><span class="hint">${t('Game says')}: <code>${esc(res.code)}</code></span>` : '';
    const yes = await confirmDialog(t('Load this replay?'),
      t('The game is busy: a single-player, multiplayer or ranked game may be in progress. Loading the replay will leave it.') + code,
      t('Leave it and load the replay'));
    if (yes) return playReplay(r, true);
    toast(t('Replay not loaded'));
    return;
  }
  if (res && res.needs_certs) { toast(t('Certificate files missing: live games and replays cannot connect')); return; }
  if (!res || !res.ok) { toast(t('Could not load the replay: {error}', { error: (res && (res.error || res.code)) || t('failed') })); return; }
  const result = res.load_result ?? res.code;
  if (res.state === 'queued') toast(t('Replay queued'));
  else toast(result != null ? t('Game load result: {code}', { code: typeof result === 'object' ? JSON.stringify(result) : result }) : t('Asked the game to load the replay…'));
  closeAll();
  if (homeOpened) homeOpened();
}

// The home screen's lists as last fetched. Reopening the screen, switching its
// tabs and typing in its search box paint from here at once; a fresh copy is
// fetched behind that (listing replays and recordings takes about a second
// while a recording is still loading).
let homeData = null, homeLoading = null;
function loadHome() {
  if (!homeLoading) {
    const arr = (x) => (Array.isArray(x) ? x : []);
    homeLoading = Promise.all([
      api('/api/recordings').then(arr, () => []), api('/api/replays').then(arr, () => []), api('/api/session?probe=1').catch(() => ({})),
      api('/api/config').catch(() => ({})),
    ]).then(([recs, reps, sess, config]) => { homeData = { recs, reps, sess, config }; return homeData; })
      .finally(() => { homeLoading = null; });
  }
  return homeLoading;
}

// Fetch the lists again; repaint only when something changed, and never under
// the user's typing.
async function refreshHome(el) {
  const shown = JSON.stringify(homeData);
  const next = await loadHome();
  const typing = el.contains(document.activeElement) && document.activeElement.matches('input, select, textarea');
  if (JSON.stringify(next) !== shown && !el.classList.contains('hidden') && !typing) paintHome(el, next);
}

/** `cached`: paint what is already known without asking the server again. */
export async function renderHome(onOpened, cached = false) {
  if (onOpened) homeOpened = onOpened;
  const el = $('overlay-home');
  if (homeData) {
    paintHome(el, homeData);
    if (!cached) await refreshHome(el);
    return;
  }
  // Listing the replays reads every header: show something on the first open.
  if (!el.innerHTML.trim()) { el.innerHTML = `${closeBtn()}<h2>${t('Vantage')}</h2><p class="hint">${t('Loading…')}</p>`; wireClose(el); }
  paintHome(el, await loadHome());
}

function paintHome(el, { recs, reps, sess, config }) {
  nativeReplays = config.native_replays === true;
  if (nativeReplays && homeTab === 'live') homeTab = 'replays';
  watchBlock = !nativeReplays && certsMissing(sess).length ? t('Watching a replay needs the certificate files, missing from {dir}.', { dir: sess.certs.dir }) : '';
  const f = homeFilter.toLowerCase();
  const body = homeTab === 'overview' ? overviewBody(recs, reps, sess)
    : homeTab === 'recordings' ? recordingsBody(recs, f)
      : homeTab === 'replays' ? replaysBody(reps, f, sess) : liveBody(sess);
  const tabBtn = (k, label) => `<button data-tab="${k}" class="${homeTab === k ? 'on' : ''}">${t(label)}</button>`;
  el.innerHTML = `${closeBtn()}<h2>${t('Vantage')}</h2>
    <div class="tabs">${tabBtn('overview', 'Overview')}${tabBtn('replays', 'Replays')}${tabBtn('recordings', 'Recordings')}${nativeReplays ? '' : tabBtn('live', 'Live game')}
      ${homeTab === 'replays' || homeTab === 'recordings' ? `<input id="home-filter" placeholder="${esc(t('Search…'))}" value="${esc(homeFilter)}" style="margin-left:auto">` : ''}
    </div>${body}`;
  wireClose(el);
  // Tabs, filters and row clicks repaint from what is known; the polls ask again.
  const rerender = () => renderHome(null, true);
  const refresh = () => refreshHome(el);
  el.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => { homeTab = b.dataset.tab; rerender(); }));
  el.querySelectorAll('[data-goto]').forEach((b) => b.addEventListener('click', () => { homeTab = b.dataset.goto; rerender(); }));
  const filt = $('home-filter');
  if (filt) {
    filt.addEventListener('input', () => {
      homeFilter = filt.value; replayLimit = REPLAY_PAGE; clearTimeout(filt._t);
      filt._t = setTimeout(() => renderHome(null, true).then(() => { const n = $('home-filter'); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }), 250);
    });
  }
  el.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', async () => {
    const r = await api('/api/open', { path: b.dataset.open }).catch((e) => ({ ok: false, error: String(e) }));
    if (r && r.ok === false) { toast(t(r.error) || t('failed')); return; }
    closeAll(); if (homeOpened) homeOpened();
  }));
  el.querySelectorAll('[data-play]').forEach((b) => b.addEventListener('click', () => playReplay(renderHome._rows[+b.dataset.play])));
  el.querySelectorAll('[data-play-ov]').forEach((b) => b.addEventListener('click', () => {
    const [dir, name] = b.dataset.playOv.split('\n');
    playReplay({ dir, name });
  }));
  // replay filters
  const rf = replayFilters();
  const saveRf = () => { settings.replayFilters = { ...rf }; replayLimit = REPLAY_PAGE; saveSettings(); rerender(); };
  for (const [id, key, prop] of [['rf-game', 'game', 'value'], ['rf-civ', 'civ', 'value'], ['rf-mode', 'mode', 'value'], ['rf-players', 'players', 'value'], ['rf-count', 'count', 'value'], ['rf-strict', 'strict', 'checked'], ['rf-compat', 'compatible', 'checked'], ['rf-spoil', 'spoilers', 'checked'], ['rf-player', 'player', 'value']]) {
    const e = $(id);
    if (e) e.addEventListener('change', () => { rf[key] = e[prop]; saveRf(); });
  }
  const clr = $('rf-clear');
  if (clr) clr.addEventListener('click', () => { Object.assign(rf, { ...DEFAULT_SETTINGS.replayFilters, spoilers: rf.spoilers }); saveRf(); });
  const more = $('rf-more');
  if (more) more.addEventListener('click', () => { replayLimit += REPLAY_PAGE; rerender(); });
  const all = $('rf-all');
  if (all) all.addEventListener('click', () => { replayLimit = Infinity; rerender(); });
  if (homeTab === 'replays' && reps.some((r) => !missingData(r) && r.duration_ms === undefined) && rf.spoilers) {
    clearTimeout(renderHome._poll);
    renderHome._poll = setTimeout(() => { if (!el.classList.contains('hidden') && homeTab === 'replays') refresh(); }, 3000);
  }
  // Recordings still being read (who played): look again shortly, unless a field has the focus.
  if ((homeTab === 'recordings' || homeTab === 'overview') && recs.some((r) => r.summary_pending)) {
    clearTimeout(renderHome._recPoll);
    renderHome._recPoll = setTimeout(() => {
      if (!el.classList.contains('hidden') && (homeTab === 'recordings' || homeTab === 'overview')) refresh();
    }, 3000);
  }
  el.querySelectorAll('tr.rrow').forEach((tr) => tr.addEventListener('click', (ev) => {
    if (ev.target.closest('button')) return;
    const r = renderHome._rows[+tr.dataset.i];
    openReplay = openReplay === r.dir + '/' + r.name ? null : r.dir + '/' + r.name;
    rerender();
  }));
  wireFolders(el);
  el.querySelectorAll('[data-start-game]').forEach((b) => b.addEventListener('click', () => {
    closeAll(); document.dispatchEvent(new CustomEvent('vantage:start-game'));
  }));
  el.querySelectorAll('[data-settings]').forEach((b) => b.addEventListener('click', () => {
    closeAll(); const f = actions().openSettings; if (f) f();
  }));
  const og = $('open-go');
  if (og) og.addEventListener('click', async () => { await api('/api/open', { path: $('open-path').value }).catch(() => null); closeAll(); if (homeOpened) homeOpened(); });
  const lg = $('live-go');
  if (lg) lg.addEventListener('click', async () => {
    const body = {
      host: $('live-host').value, port: +$('live-port').value, lobby: $('live-lobby').value || null,
      record: $('live-record').checked,
    };
    let res = await api('/api/live', body).catch((e) => ({ ok: false, error: String(e) }));
    if (res && res.needs_confirm) {
      // Joining a lobby can end a game in progress: ask, as for replays.
      const yes = await confirmDialog(t('Join this lobby?'),
        t('The game is busy: a single-player, multiplayer or ranked game may be in progress. Joining the lobby will leave it.'),
        t('Leave it and join'));
      if (!yes) { toast(t('Not joined')); return; }
      res = await api('/api/live', { ...body, confirm: true }).catch((e) => ({ ok: false, error: String(e) }));
    }
    if (res && res.needs_certs) { toast(t('Certificate files missing: live games and replays cannot connect')); rerender(); return; }
    if (res && res.ok === false && !res.needs_confirm) toast(t(res.error) || res.code || t('failed'));
    closeAll(); if (homeOpened) homeOpened();
  });
  const ls = $('live-stop');
  if (ls) ls.addEventListener('click', async () => { await api('/api/stop', {}).catch(() => null); rerender(); });
  for (const [id, on] of [['rec-start', true], ['rec-stop', false]]) {
    const b = $(id);
    if (b) b.addEventListener('click', async () => {
      const r = await api('/api/record', { on }).catch((e) => ({ ok: false, error: String(e) }));
      if (r && r.ok === false) toast(t(r.error) || t('failed'));
      else toast(on ? t('Recording started') : t('Recording saved'));
      rerender();
    });
  }
}

function wireFolders(el) {
  el.querySelectorAll('[data-folder]').forEach((b) => b.addEventListener('click', async () => {
    const r = await api('/api/open_folder', { which: b.dataset.folder }).catch(() => ({ ok: false }));
    if (!r.ok) toast(t(r.error) || t('failed'));
  }));
}

// =====================================================================================
// casting: name overrides / images / seeds keyed by player identity
// =====================================================================================

// Overrides follow the player (platform profile id, else name), not the lobby
// slot. The HUD reads them by slot (settings.playerNames[pid]), so the slot keys
// are a mirror rebuilt from the identity keys whenever the match's players change.
export function castingKey(p) {
  if (!p) return '';
  return p.profile_id ? `id:${p.profile_id}` : `name:${p.name}`;
}
const CASTING_MAPS = [['playerNames'], ['playerImages']];
function castingMap(path) {
  const obj = path.reduce((o, k) => (o ? o[k] : undefined), settings);
  return obj && typeof obj === 'object' ? obj : {};
}
function setCastingMap(path, map) {
  if (path.length === 1) settings[path[0]] = map;
  else settings[path[0]] = { ...(settings[path[0]] || DEFAULT_SETTINGS[path[0]] || {}), [path[1]]: map };
}
export function syncCastingMaps() {
  const ps = players();
  if (!ps.length) return false;
  let changed = false;
  for (const path of CASTING_MAPS) {
    const before = castingMap(path);
    const map = { ...before };
    if (!settings.castingByIdentity) {
      // one-off migration of old slot-keyed overrides to the players now in those slots
      for (const p of ps) if (map[p.id] && map[castingKey(p)] == null) map[castingKey(p)] = map[p.id];
    }
    for (const k of Object.keys(map)) if (/^\d+$/.test(k)) delete map[k];
    for (const p of ps) { const v = map[castingKey(p)]; if (v) map[p.id] = v; }
    if (JSON.stringify(map) !== JSON.stringify(before)) { setCastingMap(path, map); changed = true; }
  }
  if (!settings.castingByIdentity) { settings.castingByIdentity = true; changed = true; }
  if (changed) saveSettings();
  return changed;
}
function setCasting(path, p, value) {
  const map = { ...castingMap(path) };
  if (value) { map[castingKey(p)] = value; map[p.id] = value; } else { delete map[castingKey(p)]; delete map[p.id]; }
  setCastingMap(path, map);
}

// Built-in country flags: emoji regional-indicator pairs drawn into an SVG data
// URL, so they work anywhere an image URL does (no bundled assets).
const FLAG_CODES = ('AR AT AU BE BG BR BY CA CH CL CN CO CZ DE DK EE EG ES FI FR GB GR HK HR HU ID IE IL IN IR IS IT JP KR KZ LT LV '
  + 'MA MN MX MY NL NO NZ PE PH PK PL PT RO RS RU SA SE SG SK SI TH TR TW UA US UY VE VN ZA').split(' ');
function flagEmoji(cc) { return String.fromCodePoint(...[...cc].map((c) => 0x1F1E6 + c.charCodeAt(0) - 65)); }
export function flagUrl(cc) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 48"><text x="32" y="40" font-size="40" text-anchor="middle">${flagEmoji(cc)}</text></svg>`;
  return 'data:image/svg+xml,' + encodeURIComponent(svg);
}
let imagesCache = null;
async function loadImages(force) {
  if (!imagesCache || force) {
    const r = await api('/api/images').catch(() => []);
    imagesCache = Array.isArray(r) ? r.map((x) => (typeof x === 'string' ? x : x && x.name)).filter(Boolean) : [];
  }
  return imagesCache;
}

// =====================================================================================
// skins
// =====================================================================================

const BUILTIN_SKINS = [['default', 'Default'], ['classic', 'Classic'], ['contrast', 'High contrast'], ['clean', 'Clean']];
let skinsCache = null, skinsVersion = null;
async function loadSkins(force) {
  if (!skinsCache || force) {
    const r = await api('/api/skins').catch(() => []);
    skinsCache = Array.isArray(r) ? r.filter((s) => s && s.name) : [];
  }
  return skinsCache;
}

// settings.enabledSkins: user skin names in enable order (later skins
// override earlier ones). The older single choice settings.skin = 'user:<name>'
// moves over once; settings.skin keeps the built-in look.
export function enabledSkins() {
  if (typeof settings.skin === 'string' && settings.skin.startsWith('user:')) {
    const name = settings.skin.slice(5);
    settings.enabledSkins = [...new Set([...(settings.enabledSkins || []), name])];
    settings.skin = 'default';
    saveSettings();
  }
  return Array.isArray(settings.enabledSkins) ? settings.enabledSkins.filter((x) => typeof x === 'string') : [];
}
function setEnabledSkins(list) { settings.enabledSkins = [...new Set(list)]; saveSettings(); }

// Several enabled skins merge: boolean options OR-ed, lists
// concatenated, later assets override earlier ones. The server does it
// (/api/skins/merged); this is the fallback for servers without that route.
function mergeLocally(rows) {
  const out = { options: {}, stylesheets: [], assets: {} };
  for (const sk of rows) {
    for (const [k, v] of Object.entries(sk.options || {})) {
      if (Array.isArray(v)) out.options[k] = [...(out.options[k] || []), ...v];
      else if (typeof v === 'boolean') out.options[k] = !!out.options[k] || v;
      else if (v != null) out.options[k] = v;
    }
    const css = Array.isArray(sk.stylesheets) && sk.stylesheets.length ? sk.stylesheets : [sk.css_url || sk.css].filter(Boolean);
    out.stylesheets.push(...css);
    Object.assign(out.assets, sk.assets || {});
  }
  return out;
}

// showSkinLogo + the skin's `logo` asset: a logo drawn over the game (CSS #skin-logo
// positions it; a skin stylesheet may move it).
function applySkinLogo() {
  const url = S.skin.options && S.skin.options.showSkinLogo ? S.skin.assets && S.skin.assets.logo : null;
  let el = document.getElementById('skin-logo');
  if (!url) { if (el) el.remove(); return; }
  if (!el) {
    el = Object.assign(document.createElement('img'), { id: 'skin-logo', alt: '' });
    document.body.appendChild(el);
  }
  if (el.getAttribute('src') !== url) el.src = url;
}

const APP_STYLES = 'link[rel=stylesheet]:not(.vantage-user-skin)';
// Apply the enabled user skins: one <link> per stylesheet, cache-busted on
// reload. The merged skin (options, assets) is published as S.skin and with a
// 'vantage:skin' document event for the panels (T90/RBW4 switches, header icons…).
export async function applySkin(bust) {
  const names = enabledSkins();
  document.querySelectorAll('link.vantage-user-skin').forEach((l) => l.remove());
  const legacy = document.getElementById('vantage-user-skin');
  if (legacy) legacy.remove();
  const known = await loadSkins(!!bust);
  const rows = names.map((n) => known.find((k) => k.name === n)).filter((k) => k && k.status !== 'error');
  let merged = null;
  if (rows.length) {
    merged = await api(`/api/skins/merged?enabled=${rows.map((r) => encodeURIComponent(r.name)).join(',')}`).catch(() => null);
    if (!merged || typeof merged !== 'object' || !Array.isArray(merged.stylesheets)) merged = mergeLocally(rows);
  }
  const v = bust ? `v=${Date.now()}` : '';
  for (const href of (merged && merged.stylesheets) || []) {
    const link = Object.assign(document.createElement('link'), { rel: 'stylesheet', className: 'vantage-user-skin', href: v ? href + (href.includes('?') ? '&' : '?') + v : href });
    document.head.appendChild(link);
  }
  const full = !!(merged && merged.options && merged.options.hasFullAppStyle && merged.stylesheets.length);
  // hasFullAppStyle: the skin's CSS replaces the app's stylesheets instead of layering on them.
  document.querySelectorAll(APP_STYLES).forEach((l) => { l.disabled = full; });
  if (rows.length) document.body.dataset.userSkin = rows.map((r) => r.name).join(' ');
  else delete document.body.dataset.userSkin;
  // Same shape as state.js refreshSkinState() (HUD reads S.skin.options / .assets).
  S.skin = { options: (merged && merged.options) || {}, assets: (merged && merged.assets) || {}, stylesheets: (merged && merged.stylesheets) || [], enabled: rows.map((r) => r.name) };
  applySkinLogo();
  document.dispatchEvent(new CustomEvent('vantage:skin', { detail: S.skin }));
  return S.skin;
}

// Hot reload: skins are watched by the server (/api/skins/version changes when
// an enabled skin's files change; SHELL may also forward the SSE 'skins' event
// as 'vantage:skins-changed'). Shows "Skin Reload Error" on failure.
let lastSkinReload = 0;
export async function reloadSkins(quiet) {
  if (Date.now() - lastSkinReload < 1500) return; // SSE event and version poll can both fire
  lastSkinReload = Date.now();
  const prev = JSON.stringify((skinsCache || []).map((s) => [s.name, s.status, s.error]));
  const skin = await applySkin(true).catch(() => null);
  const bad = (skinsCache || []).filter((s) => enabledSkins().includes(s.name) && s.status === 'error');
  if (bad.length) toast(`${t('Skin Reload Error')}: ${bad.map((s) => `${s.name}${s.error ? ' (' + s.error + ')' : ''}`).join(', ')}`);
  else if (!quiet && skin && skin.enabled.length) toast(t('Skins reloaded'));
  if (isOpen('overlay-settings') && setTab === 'skins' && prev !== JSON.stringify((skinsCache || []).map((s) => [s.name, s.status, s.error]))) renderSettings();
}
let skinPollDead = false;
async function pollSkins() {
  if (skinPollDead || !enabledSkins().length) return;
  const r = await fetch('/api/skins/version').catch(() => null);
  if (!r || r.status === 404) { if (r) skinPollDead = true; return; }
  const j = await r.json().catch(() => null);
  const ver = j && j.version;
  if (ver == null) return;
  if (skinsVersion !== null && ver !== skinsVersion) { skinsVersion = ver; reloadSkins(); return; }
  skinsVersion = ver;
}
// 'vantage:skins' is the live-reload notification state.js also listens to.
document.addEventListener('vantage:skins', () => reloadSkins());
document.addEventListener('vantage:skins-changed', () => reloadSkins());

// The old "graphics mods" switch is now split into sprite mods (sprites and
// particles) and terrain mods; the old switch is copied into both once.
function migrateMods() {
  if (settings.enableGraphicsMods) {
    settings.enableSpriteMods = true; settings.enableTerrainMods = true;
    settings.enableGraphicsMods = false;
    saveSettings();
  }
}
function pushMods() {
  return api('/api/mods', {
    graphics: !!settings.enableSpriteMods, sprites: !!settings.enableSpriteMods, terrain: !!settings.enableTerrainMods,
    dirs: settings.modDirectories || [],
  }).catch(() => null);
}

// =====================================================================================
// settings
// =====================================================================================

const SET_TABS = [['interface', 'Interface'], ['dashboard', 'Dashboard pages'], ['graphics', 'Graphics'], ['sound', 'Sound'], ['casting', 'Casting'], ['skins', 'Skins'], ['hotkeys', 'Hotkeys'], ['profiles', 'Profiles'], ['help', 'Help']];
let setTab = 'interface';

function getPath(path, root = settings) { return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), root); }
function getSetting(path) { const v = getPath(path); return v === undefined ? getPath(path, DEFAULT_SETTINGS) : v; }
function setPath(path, value) {
  const keys = path.split('.');
  if (keys.length === 1) { settings[path] = value; return; }
  const clone = (o) => (o && typeof o === 'object' && !Array.isArray(o) ? { ...o } : {});
  const root = clone(settings[keys[0]] ?? DEFAULT_SETTINGS[keys[0]]);
  let cur = root;
  for (let i = 1; i < keys.length - 1; i++) { cur[keys[i]] = clone(cur[keys[i]]); cur = cur[keys[i]]; }
  cur[keys[keys.length - 1]] = value;
  settings[keys[0]] = root;
}

const lab = (label, detail) => `<label ${tip(t(label), detail ? t(detail) : '')}>${t(label)}</label>`;
function chk(path, label, detail = '', invert = false) {
  const v = !!getSetting(path);
  return `<div class="form-row">${lab(label, detail)}<input type="checkbox" data-set="${path}" data-type="${invert ? 'bool-inv' : 'bool'}" ${(invert ? !v : v) ? 'checked' : ''}></div>`;
}
// One flag of a list setting (tooltipShowMode: ['iconNames', 'detailedHelp']).
function flagChk(path, flag, label) {
  const on = (getSetting(path) || []).includes(flag);
  return `<div class="form-row">${lab(label)}<input type="checkbox" data-set="${path}" data-type="flag" data-flag="${flag}" ${on ? 'checked' : ''}></div>`;
}
function fmtSetting(path, v) {
  if (path === 'cameraSmoothMs') return `${v} ms`;
  if (path.startsWith('panelOffsets.')) return `${v} px`;
  if (path === 'terrainGrid') return `${Math.round(v * 100)} %`;
  return String(Math.round(v * 100) / 100);
}
function rng(path, label, min, max, step, detail = '') {
  const v = getSetting(path) ?? min;
  return `<div class="form-row">${lab(label, detail)}<input type="range" min="${min}" max="${max}" step="${step}" data-set="${path}" data-type="num" value="${v}"><output class="num">${fmtSetting(path, +v)}</output></div>`;
}
function numIn(path, label, min, max, step, detail = '') {
  return `<div class="form-row">${lab(label, detail)}<input type="number" min="${min}" max="${max}" step="${step}" data-set="${path}" data-type="num" value="${esc(getSetting(path) ?? '')}" style="width:80px"></div>`;
}
function sel(path, label, options, detail = '') {
  const cur = String(getSetting(path) ?? '');
  return `<div class="form-row">${lab(label, detail)}<select data-set="${path}" data-type="str">${options.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === cur ? 'selected' : ''}>${esc(t(l))}</option>`).join('')}</select></div>`;
}
function txt(path, label, placeholder = '', detail = '') {
  return `<div class="form-row">${lab(label, detail)}<input data-set="${path}" data-type="str" value="${esc(getSetting(path) ?? '')}" placeholder="${esc(placeholder)}"></div>`;
}

function interfaceTab() {
  return `<div class="grid2"><div>
    <h3>${t('Panels')}</h3>
    ${chk('showStaticTechs', 'Static techs panel (Alt+T)')}
    ${chk('fullStaticTechs', 'Full static techs', 'Show every tech line in the static techs panel, not just the key ones')}
    ${chk('showProduction', 'Production & composition')}${chk('showDashboard', 'Dashboard')}
    ${chk('useMiniDashboard', 'Mini dashboard', 'A compact dashboard with fewer columns')}
    ${chk('showEvents', 'Event log')}${chk('useMinimalUi', 'Minimal UI')}
    ${chk('useCommunityGameSkin', 'Alternative FFA layout', 'The community scoreboard layout for free-for-all games')}
    ${chk('showUnitPanelWhenNothingSelected', 'Show map info when nothing is selected')}${chk('keepDeadInSelection', 'Keep dead units in selection')}
    ${chk('autocastHighlights', 'Autocast highlights', 'Let autocast replay the most exciting moments')}
    <h3>${t('Scoreboard')}</h3>
    ${chk('disableScoreboard', 'Show scoreboard', '', true)}
    ${chk('showElo', 'Show Elo')}${chk('showRankedEloForUnrankedGames', 'Show ranked Elo in unranked games', 'Use the random-map ladder rating when the lobby is unranked')}
    ${chk('hideScore', 'Hide score')}${chk('hideScoreDots', 'Hide score dots', 'The series score dots next to team names')}
    ${sel('teamScore', 'Team score', [['sum', 'Total'], ['average', 'Average'], ['off', 'Off']], 'Team games: each team\'s score on the scoreboard, with the lead between them')}
    <h3>${t('Look')}</h3>
    <div class="form-row">${lab('Language')}<select id="lang-select">${Object.entries(LANGS).map(([c, n]) => `<option value="${c}" ${c === language ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
    ${sel('skin', 'Look', BUILTIN_SKINS, 'Built-in looks; custom skins are in Settings → Skins')}
    ${flagChk('tooltipShowMode', 'iconNames', 'Show icon name tooltips')}
    ${flagChk('tooltipShowMode', 'detailedHelp', 'Show detailed help tooltips')}
    <div class="form-row">${lab('Game directory', 'The Age of Empires II: DE install Vantage reads game data from; it must contain AoE2DE_s.exe. Empty = detect it automatically.')}<input id="game-dir" value="${esc(settings.lastUsedGameDirectory || '')}" placeholder="${esc((S.session && S.session.game_dir) || t('detected automatically'))}" style="flex:1"><button id="game-dir-save">${t('Apply')}</button></div>
    ${sel('baseColorMode', 'Colour scheme (Ctrl+Alt+C)', [['default', 'Game colours'], ['coldWarm', 'Cold vs warm'], ['warmCold', 'Warm vs cold']], 'Cold vs warm: one team in cool hues, the other in warm')}
    ${sel('rangeCircleModeBuildings', 'Range circles for buildings', [['always', 'Always'], ['selected', 'Selected only'], ['none', 'None']])}
    ${sel('rangeCircleModeSelectedEntities', 'Range circles for selected units', [['always', 'Always'], ['none', 'None']])}
    <div class="form-row">${lab('Overlay for OBS (HUD only, transparent)')}<a href="/?overlay=1" target="_blank">/?overlay=1</a></div>
    <p class="hint">${t('Panel positions are in Settings → Casting; dashboard pages have their own tab.')}</p>
  </div><div>
    <h3>${t('Camera')}</h3>
    ${chk('edgeScroll', 'Edge scrolling')}
    ${rng('edgeScrollSpeed', 'Edge scroll speed', 0.25, 3, 0.25)}
    ${rng('zoomSpeed', 'Zoom speed', 0.25, 3, 0.25)}
    ${rng('cameraSmoothMs', 'Zoom / camera move duration', 0, 3000, 50, 'How long smooth zooms and camera moves take; 0 = instant')}
    ${numIn('zoomLevels.one', 'Zoom preset 1 (Alt+1)', 0.1, 6, 0.05)}${numIn('zoomLevels.two', 'Zoom preset 2 (Alt+2)', 0.1, 6, 0.05)}${numIn('zoomLevels.three', 'Zoom preset 3 (Alt+3)', 0.1, 6, 0.05)}
    ${chk('clipCursorInGame', 'Lock the mouse to the window', 'Keeps edge scrolling working on multi-monitor setups (Alt+Shift+C)')}
    <h3>${t('Playback')}</h3>
    ${chk('disableScrubbing', 'Disable scrubbing', 'The time bar no longer seeks when clicked')}
    ${chk('showStatsTimeControls', 'Time controls on the statistics screen')}
    ${sel('endgameAutoClose', 'Close the end-of-game screen', [['0', 'Manually'], ['10', 'After 10 s'], ['30', 'After 30 s'], ['60', 'After 1 min']])}
    ${chk('autoMinimizeGame', 'Minimise Age II automatically', 'Minimise the game while Vantage has focus')}
    ${sel('healthBars', 'Health bars', [['damaged', 'Damaged only'], ['always', 'Always'], ['never', 'Never']], 'As the game\'s own option')}
    ${chk('replayReadAhead', 'Read replays ahead at full speed', 'Replays the game plays for Vantage run at its fastest speed from the start and you watch from the buffer: smooth 4-8x, without cosmetic effects such as dust and blood')}
    ${chk('autoRecord', 'Record live games to .vrec', 'Save every live session to the vault automatically')}
    ${chk('gameWarningsDismissed', 'Hide game compatibility warnings')}
  </div></div>`;
}

// -- dashboard pages (custom dashboard editor) ------------------------------------------
// settings.customDashboardConfig[layout] = [{id, columns: [colKey…], mirror?}] for
// the three editable layouts; the HUD shows those pages instead of the built-in
// ones when the list is non-empty, and settings.dashboardSelection[layout] holds
// the shown page id. Column metadata comes from panels.js (DASH_COLUMNS,
// DASH_PAGES, DASH_LAYOUTS).

const LAYOUT_LABELS = {
  nonOppositional: '1v1', oppositional: 'Team Games', ffa: 'FFA', battleRoyale: 'Battle royale',
  miniFfa: 'Mini dashboard (FFA)', pompeii: 'Return of Rome',
};
const EDITABLE_LAYOUTS = ['nonOppositional', 'oppositional', 'ffa'];
const STOCKPILE_COLS = new Set(['food', 'wood', 'gold', 'stone']);
const GRID_PAGE = 36;
const dashEd = { layout: null, id: null, draft: [], grid: 0 };
const dashOpen = new Set();
let legacyLayout = null;

function dashCols() { return PN.DASH_COLUMNS || {}; }
function hiddenCols() { return new Set([...(PN.DASH_HIDDEN_COLUMNS || []), 'd3Agg']); }
function colLabel(c) { const m = dashCols()[c]; return m ? t(m.h || c) : c; }
// Mirroring defaults on unless every column is a stockpile column.
export function defaultMirror(columns) { return !(columns || []).every((c) => STOCKPILE_COLS.has(c)); }
function builtinPages(layout) {
  return ((PN.DASH_LAYOUTS || {})[layout] || []).map((k) => (PN.DASH_PAGES || []).find((p) => p.key === k)).filter(Boolean);
}
function dashConfig(layout) {
  const all = settings.customDashboardConfig;
  const list = all && typeof all === 'object' ? all[layout] : null;
  return Array.isArray(list) ? list.filter((p) => p && p.id != null) : [];
}
function setDashConfig(layout, pages) {
  settings.customDashboardConfig = { ...(settings.customDashboardConfig || {}), [layout]: pages };
}
function dashSelected(layout) { return (settings.dashboardSelection || {})[layout]; }
function selectDashPage(layout, id) { settings.dashboardSelection = { ...(settings.dashboardSelection || {}), [layout]: id }; }
function freshPageId() { return `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`; }
// A layout's built-in pages as editable pages; `carry` keeps the older
// per-page column edits (dashboardColumns / dashboardMirror) when customising.
function copyBuiltins(layout, carry) {
  const C = dashCols();
  return builtinPages(layout).map((pg) => {
    const old = carry ? (settings.dashboardColumns || {})[pg.key] : null;
    const columns = (old && old.length ? old : pg.cols).filter((c) => C[c]);
    const page = { id: freshPageId(), columns };
    if (layout === 'oppositional') {
      const m = carry ? (settings.dashboardMirror || {})[pg.key] : undefined;
      page.mirror = m === undefined ? defaultMirror(columns) : !!m;
    }
    return page;
  });
}
function colsLine(cols) { return cols.length ? cols.map((c) => esc(colLabel(c))).join(' – ') : `<i>${t('No columns')}</i>`; }

function dashGrid(layout) {
  const C = dashCols(), hidden = hiddenCols();
  const keys = Object.keys(C).filter((c) => !hidden.has(c));
  const pages = Math.max(1, Math.ceil(keys.length / GRID_PAGE));
  dashEd.grid = Math.max(0, Math.min(pages - 1, dashEd.grid));
  const shown = keys.slice(dashEd.grid * GRID_PAGE, (dashEd.grid + 1) * GRID_PAGE);
  return `<div class="dgrid-wrap">
    <p class="hint">${t('Tick columns in the order they should appear.')}</p>
    <div class="dgrid">${shown.map((c) => {
      const i = dashEd.draft.indexOf(c);
      return `<label class="dcol${i >= 0 ? ' on' : ''}" ${tip(colLabel(c), C[c].tip ? t(C[c].tip) : '')}><input type="checkbox" data-dcol="${esc(c)}" ${i >= 0 ? 'checked' : ''}><span class="dord">${i >= 0 ? i + 1 : ''}</span>${esc(colLabel(c))}</label>`;
    }).join('')}</div>
    <div class="dgrid-foot">
      ${pages > 1 ? `<button data-dgrid="-1" ${dashEd.grid ? '' : 'disabled'}>${t('Previous')}</button><span class="hint">${dashEd.grid + 1} / ${pages}</span><button data-dgrid="1" ${dashEd.grid < pages - 1 ? '' : 'disabled'}>${t('Next')}</button>` : ''}
      <span class="dsel-line hint">${colsLine(dashEd.draft)}</span>
      <button data-dcancel>${t('Cancel')}</button><button class="on" data-dsave>${t('Save')}</button>
    </div></div>`;
}

function dashBody(layout) {
  const pages = dashConfig(layout);
  if (!pages.length) {
    return `<ol class="dpages-builtin">${builtinPages(layout).map((pg, i) => `<li>${t('Page {n}', { n: i + 1 })}: <span class="hint">${colsLine(pg.cols.filter((c) => dashCols()[c]))}</span></li>`).join('')}</ol>
      <div class="form-row"><button class="on" data-dcustomise ${tip(t('Customise'), t('Copy the built-in pages so you can add, delete, reorder and edit them'))}>${t('Customise')}</button></div>`;
  }
  const sel = dashSelected(layout);
  const selId = pages.some((p) => p.id === sel) ? sel : pages[0].id;
  const opp = layout === 'oppositional';
  return `<div class="dpages" data-dlist>${pages.map((pg, i) => {
    const cols = (pg.columns || []).filter((c) => dashCols()[c]);
    const mirror = pg.mirror ?? defaultMirror(cols);
    const editing = dashEd.layout === layout && dashEd.id === pg.id;
    return `<div class="dpage${pg.id === selId ? ' selected' : ''}${editing ? ' editing' : ''}" data-pid="${esc(pg.id)}">
      <div class="dpage-row">
        <button class="dhandle" data-dhandle ${tip(t('Drag to reorder'), t('Arrow keys move the page too'))}>⠿</button>
        <button class="link dname" data-dselect ${tip(t('Show this page'), t('The dashboard shows this page now'))}>${t('Page {n}', { n: i + 1 })}</button>
        <span class="dcols hint">${colsLine(cols)}</span>
        ${opp ? `<label class="inline" ${tip(t('Mirror'), t('Right-hand team: columns in reverse order, so both teams read outwards from the middle'))}><input type="checkbox" data-dmirror ${mirror ? 'checked' : ''}> ${t('Mirror')}</label>` : ''}
        <button data-dedit ${editing ? 'disabled' : ''}>${t('Edit')}</button>
        <button class="dtrash" data-ddelete ${pages.length <= 1 ? 'disabled' : ''} ${tip(t('Delete page'), pages.length <= 1 ? t('A layout needs at least one page') : '')}>🗑</button>
      </div>
      ${editing ? dashGrid(layout) : ''}
    </div>`;
  }).join('')}</div>
    <div class="form-row dpage-actions"><button data-dpageadd>＋ ${t('Add Page')}</button><button class="warn" data-dreset>${t('Reset to Defaults')}</button></div>`;
}

function dashboardTab() {
  let cur = null;
  try { cur = typeof PN.dashLayout === 'function' ? PN.dashLayout() : null; } catch { cur = null; }
  if (!dashOpen.size) dashOpen.add(EDITABLE_LAYOUTS.includes(cur) ? cur : EDITABLE_LAYOUTS[0]);
  const sections = EDITABLE_LAYOUTS.map((layout) => {
    const custom = dashConfig(layout).length > 0;
    return `<details class="dlayout" data-dlayout="${layout}" ${dashOpen.has(layout) ? 'open' : ''}>
      <summary><b>${t(LAYOUT_LABELS[layout])}</b> <span class="hint">${custom ? t('custom pages') : t('built-in pages')}${layout === cur ? ' · ' + t('this game') : ''}</span></summary>
      <div class="dlayout-body">${dashBody(layout)}</div></details>`;
  }).join('');
  return `<p class="hint">${t('The dashboard picks a page list by game type. Customise a list to add, delete, reorder and edit its pages; Alt+C / Alt+X cycle through them.')}</p>
    ${sections}
    <details class="dlayout" data-dlegacy><summary><b>${t('Other layouts')}</b> <span class="hint">${t('battle royale, mini dashboard, Return of Rome: columns per page')}</span></summary>${legacyEditor()}</details>`;
}

// Battle royale / mini FFA / Return of Rome keep their built-in page lists
// (they are not editable); their columns stay editable per page.
function legacyEditor() {
  const C = dashCols();
  const layouts = Object.keys(PN.DASH_LAYOUTS || {}).filter((k) => !EDITABLE_LAYOUTS.includes(k));
  if (!layouts.length) return '';
  if (!legacyLayout || !layouts.includes(legacyLayout)) legacyLayout = layouts[0];
  const pages = builtinPages(legacyLayout);
  return `<div class="form-row">${lab('Page set')}<select id="dash-layout">${layouts.map((k) => `<option value="${k}" ${k === legacyLayout ? 'selected' : ''}>${esc(t(LAYOUT_LABELS[k] || k))}</option>`).join('')}</select></div>`
    + pages.map((pg) => {
      const custom = (settings.dashboardColumns || {})[pg.key];
      const cols = (custom && custom.length ? custom : pg.cols).filter((c) => C[c]);
      const rest = Object.keys(C).filter((c) => !cols.includes(c));
      return `<div class="dash-ed" data-page="${pg.key}">
        <div class="dash-ed-head"><b>${t(pg.title)}</b>
          ${custom && custom.length ? `<button class="link" data-dlreset>${t('Default columns')}</button>` : ''}</div>
        <div class="chips">${cols.map((c, i) => `<span class="chip" ${tip(colLabel(c), C[c] && C[c].tip ? t(C[c].tip) : '')}><button data-dmove="-1" data-i="${i}" ${i ? '' : 'disabled'} ${tip(t('Move left'))}>‹</button>${esc(colLabel(c))}<button data-dmove="1" data-i="${i}" ${i < cols.length - 1 ? '' : 'disabled'} ${tip(t('Move right'))}>›</button><button data-ddel="${i}" ${tip(t('Remove'))}>✕</button></span>`).join('')}
          <select data-dadd><option value="">${t('+ Add column…')}</option>${rest.map((c) => `<option value="${c}">${esc(colLabel(c))}</option>`).join('')}</select></div>
      </div>`;
    }).join('');
}

function wireLegacyDash(el, doApply, rerender) {
  const dl = el.querySelector('#dash-layout');
  if (dl) dl.addEventListener('change', () => { legacyLayout = dl.value; rerender(); });
  const C = dashCols();
  el.querySelectorAll('.dash-ed').forEach((box) => {
    const key = box.dataset.page;
    const page = (PN.DASH_PAGES || []).find((p) => p.key === key);
    if (!page) return;
    const current = () => { const c = (settings.dashboardColumns || {})[key]; return (c && c.length ? c : page.cols).filter((x) => C[x]); };
    const store = (cols) => {
      const next = { ...(settings.dashboardColumns || {}) };
      if (cols && cols.length && cols.join() !== page.cols.join()) next[key] = cols; else delete next[key];
      settings.dashboardColumns = next; saveSettings(); doApply(); rerender();
    };
    box.querySelectorAll('[data-dmove]').forEach((b) => b.addEventListener('click', () => {
      const cols = current(), i = +b.dataset.i, j = i + +b.dataset.dmove;
      if (j < 0 || j >= cols.length) return;
      [cols[i], cols[j]] = [cols[j], cols[i]]; store(cols);
    }));
    box.querySelectorAll('[data-ddel]').forEach((b) => b.addEventListener('click', () => { const cols = current(); cols.splice(+b.dataset.ddel, 1); if (!cols.length) { toast(t('A page needs at least one column')); return; } store(cols); }));
    const add = box.querySelector('[data-dadd]');
    add.addEventListener('change', () => { if (add.value) store([...current(), add.value]); });
    const rs = box.querySelector('[data-dlreset]');
    if (rs) rs.addEventListener('click', () => store(null));
  });
}

function wireDashboard(el, doApply) {
  el.querySelectorAll('details[data-dlayout]').forEach((d) => d.addEventListener('toggle', () => {
    if (d.open) dashOpen.add(d.dataset.dlayout); else dashOpen.delete(d.dataset.dlayout);
  }));
  el.querySelectorAll('details[data-dlayout]').forEach((d) => wireDashBody(d.querySelector('.dlayout-body'), d.dataset.dlayout, doApply));
}

function wireDashBody(box, layout, doApply) {
  const refresh = () => {
    box.innerHTML = dashBody(layout);
    const sum = box.parentElement && box.parentElement.querySelector('summary .hint');
    if (sum) sum.textContent = (dashConfig(layout).length ? t('custom pages') : t('built-in pages'));
    wireDashBody(box, layout, doApply);
  };
  const commit = (pages) => { setDashConfig(layout, pages); saveSettings(); doApply(); refresh(); };
  const pages = dashConfig(layout);
  const idOf = (node) => node.closest('[data-pid]').dataset.pid;
  const indexOf = (id) => pages.findIndex((p) => p.id === id);
  const cus = box.querySelector('[data-dcustomise]');
  if (cus) cus.addEventListener('click', () => {
    const copy = copyBuiltins(layout, true);
    if (!copy.length) return;
    selectDashPage(layout, copy[0].id);
    commit(copy);
  });
  box.querySelectorAll('[data-dselect]').forEach((b) => b.addEventListener('click', () => {
    selectDashPage(layout, idOf(b)); saveSettings(); doApply(); refresh();
  }));
  box.querySelectorAll('[data-dmirror]').forEach((cb) => cb.addEventListener('change', () => {
    const i = indexOf(idOf(cb));
    if (i < 0) return;
    const next = pages.slice(); next[i] = { ...next[i], mirror: cb.checked };
    commit(next);
  }));
  box.querySelectorAll('[data-dedit]').forEach((b) => b.addEventListener('click', () => {
    const pg = pages[indexOf(idOf(b))];
    if (!pg) return;
    Object.assign(dashEd, { layout, id: pg.id, draft: (pg.columns || []).filter((c) => dashCols()[c]), grid: 0 });
    refresh();
  }));
  box.querySelectorAll('[data-ddelete]').forEach((b) => b.addEventListener('click', async () => {
    const id = idOf(b), i = indexOf(id);
    if (i < 0 || pages.length <= 1) return;
    if (!await confirmDialog(t('Delete Page {n}?', { n: i + 1 }), t('Deleted pages cannot be recovered.'), t('Delete'))) return;
    const next = pages.filter((p) => p.id !== id);
    if (dashSelected(layout) === id) selectDashPage(layout, next[Math.min(i, next.length - 1)].id);
    if (dashEd.id === id) Object.assign(dashEd, { layout: null, id: null, draft: [] });
    commit(next);
  }));
  const add = box.querySelector('[data-dpageadd]');
  if (add) add.addEventListener('click', () => {
    const pg = { id: freshPageId(), columns: [] };
    Object.assign(dashEd, { layout, id: pg.id, draft: [], grid: 0 });
    commit([...pages, pg]);
    const row = box.querySelector(`[data-pid="${CSS.escape(pg.id)}"]`);
    if (row) row.scrollIntoView({ block: 'nearest' });
  });
  const rs = box.querySelector('[data-dreset]');
  if (rs) rs.addEventListener('click', async () => {
    const name = t(LAYOUT_LABELS[layout]);
    if (!await confirmDialog(t('Reset {name} Dashboard?', { name }), t('Resetting this dashboard will remove all edits.'), t('Reset'))) return;
    const copy = copyBuiltins(layout, false);
    if (dashEd.layout === layout) Object.assign(dashEd, { layout: null, id: null, draft: [] });
    if (copy.length) selectDashPage(layout, copy[0].id);
    commit(copy);
  });
  // column grid: tick order = column order
  box.querySelectorAll('[data-dcol]').forEach((cb) => cb.addEventListener('change', () => {
    const c = cb.dataset.dcol;
    dashEd.draft = cb.checked ? [...dashEd.draft.filter((x) => x !== c), c] : dashEd.draft.filter((x) => x !== c);
    refresh();
  }));
  box.querySelectorAll('[data-dgrid]').forEach((b) => b.addEventListener('click', () => { dashEd.grid += +b.dataset.dgrid; refresh(); }));
  const cancel = box.querySelector('[data-dcancel]');
  if (cancel) cancel.addEventListener('click', () => { Object.assign(dashEd, { layout: null, id: null, draft: [] }); refresh(); });
  const save = box.querySelector('[data-dsave]');
  if (save) save.addEventListener('click', () => {
    const i = indexOf(dashEd.id);
    if (i < 0) return;
    const next = pages.slice(); next[i] = { ...next[i], columns: dashEd.draft.slice() };
    Object.assign(dashEd, { layout: null, id: null, draft: [] });
    commit(next);
    toast(t('Saved'));
  });
  // drag-and-drop reorder by the handle (the selected page is kept by id)
  const list = box.querySelector('[data-dlist]');
  if (!list) return;
  const move = (id, to) => {
    const from = indexOf(id);
    if (from < 0 || to === from) return;
    const next = pages.slice();
    const [pg] = next.splice(from, 1);
    next.splice(Math.max(0, Math.min(next.length, to)), 0, pg);
    commit(next);
  };
  let dragId = null;
  list.querySelectorAll('[data-dhandle]').forEach((h) => {
    const row = h.closest('[data-pid]');
    h.addEventListener('mousedown', () => { row.draggable = true; });
    h.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      e.preventDefault();
      const id = row.dataset.pid;
      move(id, indexOf(id) + (e.key === 'ArrowUp' ? -1 : 1));
      const again = box.querySelector(`[data-pid="${CSS.escape(id)}"] [data-dhandle]`);
      if (again) again.focus();
    });
  });
  list.querySelectorAll('[data-pid]').forEach((row) => {
    row.addEventListener('dragstart', (e) => {
      if (!row.draggable) { e.preventDefault(); return; }
      dragId = row.dataset.pid;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', dragId);
      row.classList.add('dragging');
    });
    row.addEventListener('dragend', () => {
      row.draggable = false; row.classList.remove('dragging'); dragId = null;
      list.querySelectorAll('.drop-before, .drop-after').forEach((r) => r.classList.remove('drop-before', 'drop-after'));
    });
    row.addEventListener('dragover', (e) => {
      if (!dragId) return;
      e.preventDefault();
      const r = row.getBoundingClientRect();
      const after = e.clientY > r.top + r.height / 2;
      list.querySelectorAll('.drop-before, .drop-after').forEach((x) => x.classList.remove('drop-before', 'drop-after'));
      row.classList.add(after ? 'drop-after' : 'drop-before');
    });
    row.addEventListener('drop', (e) => {
      if (!dragId) return;
      e.preventDefault();
      const r = row.getBoundingClientRect();
      const after = e.clientY > r.top + r.height / 2;
      const from = indexOf(dragId);
      let to = indexOf(row.dataset.pid) + (after ? 1 : 0);
      if (from < to) to -= 1;
      move(dragId, to);
    });
  });
  document.addEventListener('mouseup', () => list.querySelectorAll('[draggable="true"]').forEach((r) => { if (!r.classList.contains('dragging')) r.draggable = false; }), { once: true });
}

// -- panel offsets ([up, right] per panel + overviewTop) --------------------------------

const OFFSET_PANELS = [
  ['dashboard', 'Dashboard offset'], ['score', 'Score offset'], ['minimap', 'Minimap offset'],
  ['selectionPanel', 'Unit panel offset'], ['eventNotifications', 'Event notifications offset'],
];
// The current offsets in the [up, right] shape, whatever shape is stored (the
// older per-panel keys map as the settings migration in state.js does).
export function panelOffsetsNow() {
  const o = settings.panelOffsets || {};
  const n = (x) => (Number.isFinite(+x) ? +x : 0);
  const pairOf = (x) => (Array.isArray(x) ? [n(x[0]), n(x[1])] : null);
  return {
    overviewTop: n(Array.isArray(o.overviewTop) ? o.overviewTop[0] : o.overviewTop),
    dashboard: pairOf(o.dashboard) || [n(o.dashboardBottom), 0],
    score: pairOf(o.score) || [n(o.scoreBottom), n(o.scoreRight)],
    minimap: pairOf(o.minimap) || [0, 0],
    selectionPanel: pairOf(o.selectionPanel) || [0, 0],
    eventNotifications: pairOf(o.eventNotifications) || [0, 0],
  };
}
const off2 = (v) => (Math.round(v * 100) / 100).toFixed(2);
function offsetsSection() {
  const o = panelOffsetsNow();
  const inp = (k, i, v, name) => `<input type="number" step="0.01" class="off-in num" data-off="${k}" ${i == null ? '' : `data-ix="${i}"`} value="${off2(v)}" ${tip(t(name))}>`;
  return `<h3>${t('Panel offsets')}</h3>
    <p class="hint">${t('In 1080p pixels, scaled with the interface. Positive values move a panel up and to the right; negative values move it down and to the left.')}</p>
    <div class="form-row">${lab('Team overview offset', 'Moves the team overview (and the end-of-game panel) down')}<span class="off-pair">${inp('overviewTop', null, o.overviewTop, 'Down')}</span></div>
    ${OFFSET_PANELS.map(([k, label]) => `<div class="form-row">${lab(label)}<span class="off-pair"><span class="off-l">${t('Up')}</span>${inp(k, 0, o[k][0], 'Up')}<span class="off-l">${t('Right')}</span>${inp(k, 1, o[k][1], 'Right')}</span></div>`).join('')}
    <div class="form-row"><label></label><button id="off-reset">${t('Reset offsets')}</button></div>`;
}
function wireOffsets(el, doApply, rerender) {
  el.querySelectorAll('[data-off]').forEach((inp) => inp.addEventListener('change', () => {
    const raw = String(inp.value).trim();
    let v = raw === '' ? 0 : Math.round(+raw * 100) / 100; // blank = 0; free values, 2 decimals
    if (!Number.isFinite(v)) v = 0;
    inp.value = off2(v);
    const o = panelOffsetsNow();
    if (inp.dataset.ix == null) o[inp.dataset.off] = v;
    else { const pr = o[inp.dataset.off].slice(); pr[+inp.dataset.ix] = v; o[inp.dataset.off] = pr; }
    settings.panelOffsets = o;
    saveSettings(); doApply();
  }));
  const r = el.querySelector('#off-reset');
  if (r) r.addEventListener('click', () => {
    settings.panelOffsets = { overviewTop: 0, ...Object.fromEntries(OFFSET_PANELS.map(([k]) => [k, [0, 0]])) };
    saveSettings(); doApply(); rerender();
  });
}

// -- skins tab -------------------------------------------------------------------------

const SKIN_OPTION_LABELS = {
  hasFullAppStyle: 'Replaces the app style', showSkinLogo: 'Skin logo', alwaysShowUnitPanel: 'Always show the unit panel',
  useT90Components: 'T90 components', useRbw4Components: 'RBW4 components', useFullStaticTechs: 'Full static techs',
  customPlayerInfos: 'Custom player infos', standardColorOverrides: 'Colour overrides',
};
function optionChips(opts) {
  return Object.entries(opts || {}).filter(([, v]) => (Array.isArray(v) ? v.length : !!v)).map(([k, v]) =>
    `<span class="chip" ${tip(k)}>${esc(t(SKIN_OPTION_LABELS[k] || k))}${Array.isArray(v) ? ` (${v.length})` : typeof v === 'boolean' ? '' : `: ${esc(String(v))}`}</span>`).join('');
}
function skinsTab() {
  const list = skinsCache;
  const on = enabledSkins();
  const statusOf = (sk) => (sk.status === 'error'
    ? `<span class="warn" ${tip(t('Error'), sk.error || '')}>⚠ ${t('Error')}</span>`
    : sk.status === 'loading' ? `<span class="hint">${t('Loading…')}</span>` : `<span class="saved">${t('Ready')}</span>`);
  const rows = (list || []).map((sk) => {
    const i = on.indexOf(sk.name);
    const kind = sk.kind === 'zip' ? t('ZIP file') : t('Folder');
    return `<tr class="${i >= 0 ? 'on' : ''}"><td><input type="checkbox" data-skin="${esc(sk.name)}" ${i >= 0 ? 'checked' : ''} ${sk.status === 'error' ? 'disabled' : ''}></td>
      <td><b>${esc(sk.title || sk.name)}</b><div class="hint">${esc(sk.path || sk.name)}</div>${(sk.warnings || []).length ? `<div class="warn">⚠ ${esc(sk.warnings.join('; '))}</div>` : ''}</td>
      <td><span class="badge">${kind}</span></td><td>${statusOf(sk)}</td>
      <td class="chips">${optionChips(sk.options)}</td>
      <td class="nowrap">${i >= 0 ? `<span class="hint">#${i + 1}</span> <button data-skinmove="-1" data-name="${esc(sk.name)}" ${i ? '' : 'disabled'} ${tip(t('Earlier'), t('Later skins override earlier ones'))}>↑</button><button data-skinmove="1" data-name="${esc(sk.name)}" ${i < on.length - 1 ? '' : 'disabled'} ${tip(t('Later'))}>↓</button>` : ''}</td></tr>`;
  }).join('');
  const missing = on.filter((n) => list && !list.some((s) => s.name === n));
  const merged = S.skin && S.skin.options ? optionChips(S.skin.options) : '';
  const http = !!getSetting('toggleHTMLServer');
  return `<div class="grid2"><div>
    <h3>${t('Look')}</h3>
    ${sel('skin', 'Look', BUILTIN_SKINS, 'Built-in looks; custom skins below are layered on top')}
    <h3>${t('Custom skins')}</h3>
    <p class="hint">${t('A skin is a folder or a .zip file with a skin.json (name, options, stylesheets, assets). Several skins can be enabled at once: their options combine and later skins override earlier ones. Enabled skins reload by themselves when their files change.')}</p>
    ${list == null ? `<p class="hint">${t('Loading…')}</p>` : list.length ? `<table class="list skins-list"><tr><th></th><th>${t('Skin')}</th><th>${t('Type')}</th><th>${t('Status')}</th><th>${t('Options')}</th><th>${t('Order')}</th></tr>${rows}</table>` : `<p class="hint">${t('No custom skins found. Put skin folders or .zip files in the skins folder.')}</p>`}
    ${missing.length ? `<p class="warn">⚠ ${t('Enabled but not found: {names}', { names: esc(missing.join(', ')) })} <button class="link" id="skins-prune">${t('Remove')}</button></p>` : ''}
    <div class="form-row"><button id="skins-refresh">↻ ${t('Refresh')}</button><button data-folder="skins">${t('Open skins folder')}</button>
      ${on.length ? `<button id="skins-none">${t('Use the default look')}</button>` : ''}</div>
    <div class="form-row">${lab('Add a skin', 'A skin folder or .zip file anywhere on this computer')}<select id="skin-add-kind"><option value="folder">${t('Folder')}</option><option value="zip">${t('ZIP file')}</option></select>
      <input id="skin-add-path" size="28" placeholder="${esc(t('Path to the folder or .zip'))}"><button id="skin-add">${t('Add')}</button></div>
    ${merged ? `<h3>${t('Active skin options')}</h3><div class="chips">${merged}</div>` : ''}
  </div><div>
    <h3>${t('Skin debugging')}</h3>
    ${chk('toggleHTMLServer', 'Enable HTTP Server for skin debugging', 'Live-reloads skin stylesheets in any browser tab and serves the statistics as JSON at /stats-dump')}
    <div class="form-row"><label></label><button id="html-open" ${http ? '' : 'disabled'} ${tip(t('Open webpage'), t('Open Vantage in your browser to inspect and edit skin CSS with its developer tools'))}>${t('Open webpage')}</button>
      ${http ? `<a href="/stats-dump" target="_blank" rel="noopener">/stats-dump</a>` : ''}</div>
    <p class="hint">${t('Vantage already runs in a browser: open it in a normal tab, edit the skin files, and the page picks the changes up without a restart.')}</p>
  </div></div>`;
}
function wireSkins(el, doApply, rerender) {
  el.querySelectorAll('[data-skin]').forEach((cb) => cb.addEventListener('change', async () => {
    const name = cb.dataset.skin;
    const list = enabledSkins().filter((n) => n !== name);
    setEnabledSkins(cb.checked ? [...list, name] : list);
    await applySkin(); doApply(); rerender();
  }));
  el.querySelectorAll('[data-skinmove]').forEach((b) => b.addEventListener('click', async () => {
    const list = enabledSkins(), i = list.indexOf(b.dataset.name), j = i + +b.dataset.skinmove;
    if (i < 0 || j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    setEnabledSkins(list); await applySkin(); doApply(); rerender();
  }));
  const none = el.querySelector('#skins-none');
  if (none) none.addEventListener('click', async () => { setEnabledSkins([]); await applySkin(); doApply(); rerender(); });
  const prune = el.querySelector('#skins-prune');
  if (prune) prune.addEventListener('click', async () => { setEnabledSkins(enabledSkins().filter((n) => (skinsCache || []).some((s) => s.name === n))); await applySkin(); rerender(); });
  const ref = el.querySelector('#skins-refresh');
  if (ref) ref.addEventListener('click', async () => { await loadSkins(true); await applySkin(true); rerender(); toast(t('{n} custom skin(s)', { n: skinsCache.length })); });
  const add = el.querySelector('#skin-add');
  if (add) add.addEventListener('click', async () => {
    const path = el.querySelector('#skin-add-path').value.trim();
    if (!path) { toast(t('Enter the path of a skin folder or .zip file')); return; }
    const kind = el.querySelector('#skin-add-kind').value;
    const r = await api('/api/skins/add', { path, kind }).catch((e) => ({ ok: false, error: /404/.test(String(e)) ? t('this server cannot add skins from a path; copy the skin into the skins folder') : String(e) }));
    if (!r || r.ok === false) { toast(t('Could not add the skin: {error}', { error: (r && r.error) || t('failed') })); return; }
    await loadSkins(true);
    if (r.name && !enabledSkins().includes(r.name)) setEnabledSkins([...enabledSkins(), r.name]);
    await applySkin(); rerender(); toast(t('Skin added'));
  });
  const ho = el.querySelector('#html-open');
  if (ho) ho.addEventListener('click', () => {
    const f = actions().openHtmlServer || actions().openWebpage;
    if (typeof f === 'function') { f(); return; }
    window.open(location.origin + '/', '_blank', 'noopener');
  });
}

// The map's colour grade (the game's colour-correction presets). Auto: what the map
// script sets; a script that picks one at random cannot be followed, so it can be
// chosen here.
function gradeSelect() {
  const presets = (S.match && S.match.color_grades) || [];
  const names = (S.catalog && S.catalog.color_grade_names) || {};
  const label = (n) => names[n] || n; // the game's own name for the preset
  const known = S.match && S.match.color_grade != null;
  const auto = known ? t('Auto ({name})', { name: label((presets[S.match.color_grade] || {}).name || 'Default') })
    : t('Auto (Default: this map picks its grade at random)');
  const opts = [['auto', auto], ...presets.map((p) => [p.name, label(p.name)])];
  return sel('colorGrade', 'Map colour grade', opts,
    'The game\'s colour grade for the map. Some map scripts choose it at random; pick it here to match the game.')
    + sel(`colorGradeByGame.${gameKey()}`, 'Colour grade for this game', [['auto', t('Same as above')], ...opts.slice(1)],
      'Remembered for this game only: for maps that pick their grade at random.');
}

function graphicsTab() {
  return `<div class="grid2"><div>
    <h3>${t('Renderer')}</h3>
    ${chk('gameGraphics', 'Game graphics (sprites) when zoomed in')}
    ${chk('enhancedGraphics', 'Enhanced (UHD) graphics')}${chk('smallTrees', 'Small trees')}
    <div class="form-row">${lab('Terrain grid intensity', 'Lines along the tile edges; 0 % = off')}<input type="range" min="0" max="1" step="0.05" data-set="terrainGrid" data-type="num" value="${+getSetting('terrainGrid') || 0}"><output class="num">${fmtSetting('terrainGrid', +getSetting('terrainGrid') || 0)}</output>
      <button class="link" id="grid-recommended" ${tip(t('Reset to recommended (50 %)'))}>${t('Reset to recommended (50 %)')}</button></div>
    ${chk('waitForGraphics', 'Wait for graphics', 'Playback holds a moment until new units\' graphics are loaded, so nothing pops in')}
    ${chk('gpuSprites', 'GPU rendering', 'Draw sprites, unit outlines and terrain with WebGL2 (much faster); off draws them with Canvas 2D')}
    ${chk('limitToSixtyFps', 'Limit to 60 FPS', 'Saves power and GPU time')}
    ${numIn('atlasMemoryNormal', 'Sprite memory (MB)', 32, 4096, 32, 'Decoded game graphics kept in memory; older ones are reloaded when needed')}
    ${numIn('atlasMemoryUhd', 'Sprite memory, UHD graphics (MB)', 64, 8192, 64)}
    <h3>${t('Texture filtering')}</h3>
    ${chk('filtering.unitShadow', 'Smooth unit shadows')}${chk('filtering.unitColor', 'Smooth unit sprites')}
    ${chk('filtering.unitDamage', 'Smooth damage sprites')}${chk('filtering.particle', 'Smooth particles')}${chk('filtering.terrain', 'Smooth terrain')}
    <h3>${t('Mods')}</h3>
    ${chk('enableSpriteMods', 'Enable graphics mods (uses the mods you have enabled in-game)', 'Unit, building and particle sprites from your mods')}
    ${chk('enableTerrainMods', 'Enable terrain mods (uses the mods you have enabled in-game)', 'Terrain textures from your mods')}
    <div class="form-row">${lab('Extra mod folders', 'One folder per line, searched before the game\'s own files')}<textarea id="mod-dirs" rows="3" style="flex:1">${esc((settings.modDirectories || []).join('\n'))}</textarea></div>
    <div class="form-row"><label></label><button id="mod-dirs-save">${t('Save mod folders')}</button></div>
  </div><div>
    <h3>${t('Picture')}</h3>
    ${gradeSelect()}
    ${['brightness', 'contrast', 'saturation', 'gamma'].map((k) => rng(`post.${k}`, k[0].toUpperCase() + k.slice(1), 0.5, 1.6, 0.05)).join('')}
    ${rng('postExtra.red', 'Red', 0.5, 1.5, 0.05)}${rng('postExtra.green', 'Green', 0.5, 1.5, 0.05)}${rng('postExtra.blue', 'Blue', 0.5, 1.5, 0.05)}
    ${rng('postExtra.alpha', 'Opacity', 0, 1, 0.05)}
    <h3>${t('Bloom & anti-aliasing')}</h3>
    <p class="hint">${t('Bloom, anti-aliasing and the red, green, blue and opacity sliders draw units without the GPU sprite batch: much slower in large battles at high speed.')}</p>
    ${chk('postExtra.bloomEnable', 'Enable bloom')}
    ${rng('postExtra.bloomBrightness', 'Bloom brightness', 0, 2, 0.05)}
    ${rng('postExtra.bloomThreshold', 'Bloom threshold', 0, 1, 0.05)}
    ${rng('postExtra.bloomBlur', 'Bloom blur', 0, 20, 1)}
    ${rng('postExtra.bloomScale', 'Bloom scale', 0.25, 2, 0.05)}
    ${sel('postExtra.bloomQuality', 'Bloom quality', [['low', 'Low'], ['medium', 'Medium'], ['high', 'High']])}
    ${chk('postExtra.fxaa', 'Anti-aliasing (FXAA)')}
  </div></div>`;
}

function soundTab() {
  const BUS = { events: 'Events', units: 'Units', combat: 'Combat', selection: 'Selection', taunts: 'Taunts' };
  const EXTRA = { villagers: 'Villager work', critters: 'Animals', ambience: 'Ambience', reverb: 'Outdoor reverb', combatImpacts: 'Combat impacts' };
  const SEV = { train: 'Units trained', research: 'Research done', attack: 'Under attack', conversion: 'Conversions' };
  const modes = [['screen', 'On screen'], ['selectedOwners', 'Selected owners'], ['screenOrSelectedOwners', 'On screen or selected owners'], ['selectedPlayer', 'Perspective'], ['all', 'All players'], ['none', 'None']];
  return `<div class="grid2"><div>
    <h3>${t('Volume')}</h3>
    ${rng('soundOutputVolume', 'Output volume', 0, 1, 0.05)}
    ${Object.entries(BUS).map(([k, l]) => rng(`soundVolumes.${k}`, l, 0, 1, 0.05)).join('')}
    ${Object.entries(EXTRA).map(([k, l]) => rng(`soundVolumesExtra.${k}`, l, 0, 1, 0.05)).join('')}
  </div><div>
    <h3>${t('Event sounds')}</h3>
    ${Object.entries(SEV).map(([k, l]) => sel(`soundEventConfig.${k}`, l, modes)).join('')}
    ${sel('soundAlertInterval', 'Attack / conversion spacing', [[0, 'No limit'], [1000, '1 second'], [3000, '3 seconds'], [5000, '5 seconds']])}
    ${sel('chatEventSoundOption', 'Chat event sounds', [['none', 'None'], ['chatAlert', 'Sound only'], ['chatAlertAndTaunt', 'Sound and taunt']])}
    ${sel('tauntLanguage', 'Taunt language', [['', 'Same as the interface'], ...Object.entries(LANGS)])}
  </div></div>`;
}

function seriesMatches(sb, n) {
  return Array.from({ length: n }, (_, i) => {
    const m = (sb.matches || [])[i];
    return m && typeof m === 'object' ? m : { winner: m ?? null };
  });
}
function seriesSides(ts) {
  if (ts.length === 2) return [['A', teamName(ts[0])], ['B', teamName(ts[1])]];
  return players().map((p) => [String(p.id), playerName(p.id)]);
}

function castingTab() {
  const ps = players();
  const ts = teams();
  const sb = { ...DEFAULT_SETTINGS.scoreboard, ...(settings.scoreboard || {}) };
  const nMatches = Math.max(1, Math.min(21, +sb.numberOfMatches || 1));
  const matches = seriesMatches(sb, nMatches);
  // Winners as the HUD reads them: 'A' / 'B' for the first / second team, a pid in FFA.
  const sides = seriesSides(ts);
  const wins = sides.map(([k]) => matches.filter((m) => String(m.winner) === k).length);
  const need = Math.floor(nMatches / 2) + 1;
  const champ = sb.seriesType === 'bestOf' ? wins.findIndex((w) => w >= need) : -1;
  const shown = sb.enabled ?? matches.some((m) => m.winner != null && m.winner !== '');
  const images = imagesCache || [];
  const imgOptions = (cur) => {
    const opt = (v, l) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(l)}</option>`;
    const known = new Set(['', ...images.map((f) => `/images/${f}`), ...FLAG_CODES.map(flagUrl)]);
    return opt('', t('None'))
      + (images.length ? `<optgroup label="${esc(t('Custom images'))}">${images.map((f) => opt(`/images/${f}`, f)).join('')}</optgroup>` : '')
      + `<optgroup label="${esc(t('Flags'))}">${FLAG_CODES.map((cc) => opt(flagUrl(cc), `${flagEmoji(cc)} ${cc}`)).join('')}</optgroup>`
      + (cur && !known.has(cur) ? opt(cur, t('Custom URL')) : '');
  };
  const seeds = (settings.scoreboard && settings.scoreboard.seeds) || {};
  return `<div class="grid2"><div>
    <h3>${t('Browser source')}</h3>
    <p class="hint">${t('Add this address as a browser source in OBS: the interface without the map background, for overlaying on the game capture.')}</p>
    <div class="form-row"><input readonly size="40" value="${esc(location.origin + '/?overlay=1')}" id="obs-url"><button id="obs-copy">${t('Copy')}</button></div>
    ${offsetsSection()}
    <h3>${t('Scoreboard')}</h3>
    ${chk('disableScoreboard', 'Show scoreboard', '', true)}${chk('hideScore', 'Hide score')}${chk('hideScoreDots', 'Hide score dots')}
    ${txt('mainText', 'Main text')}${txt('secondaryText', 'Secondary text')}${txt('stageName', 'Tournament stage', 'Grand final')}
    <h3>${t('Series')}</h3>
    ${sel('scoreboard.seriesType', 'Series type', [['bestOf', 'Best of N'], ['playAll', 'Play all N']], 'Best of: the series ends when a team wins a majority')}
    ${numIn('scoreboard.numberOfMatches', 'Number of games', 1, 21, 1)}
    <div class="form-row">${lab('Show the series on the scoreboard', 'Off until you set it up: turns on by itself once a game has a winner')}<input type="checkbox" id="sb-enabled" ${shown ? 'checked' : ''}></div>
    <div class="series-games">${matches.map((m, i) => `<div class="form-row"><label>${t('Game {n}', { n: i + 1 })}</label>
      <select data-match="${i}"><option value="">${t('Not played')}</option>${sides.map(([k, name]) => `<option value="${esc(k)}" ${String(m.winner) === k ? 'selected' : ''}>${esc(t('{team} won', { team: name }))}</option>`).join('')}</select></div>`).join('')}</div>
    <p class="series-score">${sides.length ? sides.map(([, name], k) => `<b>${esc(name)}</b> ${wins[k]}`).join(' – ') : `<span class="hint">${t('Open a game to enter winners.')}</span>`}${champ >= 0 ? ` · ${t('{team} wins the series', { team: esc(sides[champ][1]) })}` : ''}</p>
    ${txt('seriesType', 'Series text override', 'Bo5', 'Shown instead of the series type when set')}${txt('seriesScore', 'Score text override', '2 - 1')}
    <h3>${t('Teams')}</h3>
    ${ts.map((tm, i) => `<div class="form-row">${lab('Team name')}<input data-tname="${tm.key}" value="${esc(settings.teamNames[tm.key] || '')}" placeholder="${esc(tm.players.map((p) => p.name).join(' + '))}"></div>
      ${ts.length === 2 ? `<div class="form-row">${lab('Seed / Elo text', 'Shown next to the team name, e.g. "#1 seed"')}<input data-seed="${i ? 'B' : 'A'}" value="${esc(seeds[i ? 'B' : 'A'] ?? seeds[tm.key] ?? '')}" size="12"></div>` : ''}
      <div class="form-row">${lab('Team captain (team colour)', 'The team uses the captain\'s colour in team-colour mode')}<select data-captain="${tm.key}"><option value="">—</option>${tm.players.map((p) => `<option value="${p.id}" ${settings.teamCaptains[tm.key] == p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>`).join('') || `<p class="hint">${t('Open a game to name its teams.')}</p>`}
  </div><div>
    <h3>${t('Players')}</h3>
    <p class="hint">${t('Overrides follow the player (by profile or name) into later games, not the lobby slot.')}</p>
    ${ps.map((p) => {
      const key = castingKey(p);
      const img = castingMap(['playerImages'])[key] || '';
      return `<div class="cast-player" style="border-color:${playerMarkColor(p.id)}">
        <div class="cast-head">${img ? `<img class="cast-img" src="${esc(img)}" alt="">` : '<span class="cast-img"></span>'}<b>${esc(p.name)}</b><span class="hint">${esc(key)}</span></div>
        <div class="form-row">${lab('Display name')}<input data-pname="${p.id}" value="${esc(castingMap(['playerNames'])[key] || '')}" placeholder="${esc(p.name)}"></div>
        <div class="form-row">${lab('Flag / image')}<select data-pimgsel="${p.id}">${imgOptions(img)}</select></div>
        <div class="form-row">${lab('Image URL')}<input data-pimg="${p.id}" value="${esc(img.startsWith('data:') ? '' : img)}" placeholder="/images/logo.png or https://…"></div>
      </div>`;
    }).join('') || `<p class="hint">${t('Open a game to set player names and flags.')}</p>`}
    <h3>${t('Custom images')}</h3>
    <p class="hint">${t('Put pictures in the images folder of the Vantage data directory; they appear in the lists above.')}</p>
    <div class="img-grid">${images.map((f) => `<img src="/images/${encodeURIComponent(f)}" alt="" ${tip(f)}>`).join('') || `<span class="hint">${t('No custom images yet.')}</span>`}</div>
    <div class="form-row"><button id="img-refresh">${t('Refresh')}</button><button data-folder="images">${t('Open images folder')}</button></div>
  </div></div>`;
}

function comboFromEvent(e) {
  if (['Control', 'Alt', 'Shift', 'Meta', 'AltGraph'].includes(e.key)) return null;
  if (e.key === '?') return '?';
  const named = { BracketLeft: '[', BracketRight: ']', Equal: '=', Minus: '-', Comma: ',', Period: '.', Slash: '/', Semicolon: ';', Quote: "'", Backquote: '`', Backslash: '\\', Space: 'Space', Enter: 'Enter', NumpadEnter: 'Enter' };
  let key;
  if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3);
  else if (/^Digit\d$/.test(e.code)) key = e.code.slice(5);
  else if (named[e.code]) key = named[e.code];
  else key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
  return [e.ctrlKey || e.metaKey ? 'Ctrl' : '', e.altKey ? 'Alt' : '', e.shiftKey ? 'Shift' : '', key].filter(Boolean).join('+');
}
function bindingsOf(action) {
  if (typeof HK.bindings === 'function') return HK.bindings(action);
  const v = (settings.customHotkeys || {})[action] ?? HK.KEYMAP[action][0];
  return (Array.isArray(v) ? v : [v]).filter(Boolean);
}
// action -> [conflicting combos], via hotkeys.js when it can tell us, else locally.
function hotkeyConflictMap() {
  const out = new Map();
  let list = null;
  if (typeof HK.hotkeyConflicts === 'function') { try { list = HK.hotkeyConflicts(settings.customHotkeys || {}); } catch { list = null; } }
  if (!list) {
    const norm = (c) => { const parts = c.split('+'); const k = parts.pop().toLowerCase(); const m = new Set(parts.map((x) => x.toLowerCase())); return `${m.has('ctrl') ? 'C' : ''}${m.has('alt') ? 'A' : ''}${m.has('shift') ? 'S' : ''}|${k}`; };
    const claims = new Map();
    for (const a of Object.keys(HK.KEYMAP)) {
      if (a === 'holdFogOfWar') continue;
      for (const c of bindingsOf(a)) { const n = norm(c); if (!claims.has(n)) claims.set(n, { combo: c, actions: [] }); claims.get(n).actions.push(a); }
    }
    list = [...claims.values()].filter((c) => c.actions.length > 1);
  }
  for (const c of list) for (const a of c.actions) {
    if (!out.has(a)) out.set(a, []);
    out.get(a).push(c.unknown ? t('unknown action') : `${c.combo}: ${c.actions.filter((x) => x !== a).map((x) => t((HK.KEYMAP[x] || [, x])[1])).join(', ')}`);
  }
  out.list = list;
  return out;
}

function hotkeysTab() {
  const conflicts = hotkeyConflictMap();
  const custom = settings.customHotkeys || {};
  const acts = Object.keys(HK.KEYMAP).filter((a) => !/ControlGroup[1-9]/.test(a));
  const confList = conflicts.list || [];
  return `<p class="hint">${t('Click a binding and press the new key combination. Backspace unbinds, Esc cancels. Use + to add a second key.')}</p>
    ${confList.length ? `<div class="hk-warn-box">⚠ ${t('{n} key conflict(s): the first action listed keeps the key.', { n: confList.length })}
      <ul>${(typeof HK.describeConflicts === 'function' ? HK.describeConflicts(confList, t) : confList.map((c) => `${c.combo}: ${c.actions.join(' ↔ ')}`)).map((l) => `<li>${esc(l)}</li>`).join('')}</ul></div>` : ''}
    <div class="form-row"><input id="hk-filter" placeholder="${esc(t('Filter…'))}" size="30"><button id="hk-reset-all">${t('Reset all hotkeys')}</button></div>
    <table class="keys hk-table">${acts.map((a) => {
      const list = bindingsOf(a);
      const isCustom = Object.prototype.hasOwnProperty.call(custom, a);
      const warn = conflicts.get(a);
      return `<tr data-hkrow="${a}" class="${warn ? 'conflict' : ''}"><td>${esc(t(HK.KEYMAP[a][1]))}</td>
        <td><input class="hk-input" data-hk="${a}" value="${esc(list.join(' / ') || '—')}" readonly ${a === 'holdFogOfWar' ? 'disabled' : ''}></td>
        <td class="hk-btns"><button data-hkadd="${a}" ${tip(t('Add another key'))}>+</button>${isCustom ? `<button data-hkreset="${a}" ${tip(t('Default'), HK.KEYMAP[a][0])}>↺</button>` : ''}</td>
        <td class="hk-warn">${warn ? `⚠ ${esc(warn.join('; '))}` : ''}</td></tr>`;
    }).join('')}</table>
    <details><summary>${t('Advanced: edit as JSON')}</summary>
      <textarea id="hk-json" rows="5" style="width:100%">${esc(JSON.stringify(custom, null, 1))}</textarea>
      <button id="hk-save">${t('Save hotkeys')}</button></details>`;
}

function profilesTab() {
  return `<h3>${t('Settings profiles')}</h3>
    <p class="hint">${t('Save your settings under a name to switch between setups, or export them to a file to use on another machine. Replay filters, casting overrides and hotkeys travel with them.')}</p>
    <div class="form-row"><select id="prof-list"><option value="">${t('Saved profiles…')}</option></select><button id="prof-load">${t('Load')}</button></div>
    <div class="form-row"><input id="prof-name" size="20" placeholder="${esc(t('Profile name'))}"><button id="prof-save">${t('Save as profile')}</button></div>
    <div class="form-row"><button id="prof-export">${t('Export to file')}</button><label class="filebtn">${t('Import from file')}<input type="file" id="prof-import" accept=".json,application/json" hidden></label></div>
    <h3>${t('Reset')}</h3>
    <div class="form-row"><button id="reset-all" class="warn">${t('Reset all settings')}</button></div>`;
}

// "Vantage 0.1.0 · GitHub · Wiki · Report a problem", for the help pages.
export function aboutLine() {
  const v = S.version ? t('Vantage {version}', { version: esc(S.version) }) : 'Vantage';
  return `<p class="hint about">${v} · ${extLink(REPO_URL, 'GitHub')} · ${extLink(`${REPO_URL}/wiki`, t('Wiki'))} · ${extLink(`${REPO_URL}/issues`, t('Report a problem'))}</p>`;
}

function helpTab() {
  return `${aboutLine()}<div class="help-links">
    <button id="help-docs" class="on">${t('Documentation')}</button>
    <button id="help-quick">${t('Quick reference')}</button>
    <button id="help-tutorial">${t('Tutorial')}</button>
  </div>
  <p class="hint">${t('The documentation explains every panel and setting. The quick reference lists the keys and mouse actions.')}</p>`;
}

export function openDocs() {
  const a = actions();
  for (const name of ['openDocs', 'showDocs', 'openDocumentation']) if (typeof a[name] === 'function') { closeAll(); a[name](); return; }
  if ($('overlay-docs')) { open('overlay-docs'); return; }
  toggle('overlay-help', renderHelp);
}

function wireProfiles() {
  const list = $('prof-list');
  if (!list) return;
  api('/api/profiles').then((names) => {
    list.insertAdjacentHTML('beforeend', (names || []).map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join(''));
  }).catch(() => {});
  const adopt = (obj) => { replaceSettings(obj); toast(t('Settings loaded')); location.reload(); };
  $('prof-load').addEventListener('click', async () => {
    if (!list.value) return;
    const obj = await api(`/api/profile/${encodeURIComponent(list.value)}`).catch(() => null);
    if (obj) adopt(obj); else toast(t('failed'));
  });
  $('prof-save').addEventListener('click', async () => {
    const name = $('prof-name').value.trim();
    const r = await api('/api/profile', { name, settings }).catch(() => ({ ok: false }));
    toast(r.ok ? t('Saved') : (t(r.error) || t('failed')));
    if (r.ok && ![...list.options].some((o) => o.value === name)) list.insertAdjacentHTML('beforeend', `<option value="${esc(name)}">${esc(name)}</option>`);
  });
  $('prof-export').addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(settings, null, 1)], { type: 'application/json' }));
    a.download = 'vantage-settings.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  $('prof-import').addEventListener('change', async (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    try {
      const obj = JSON.parse(await file.text());
      if (!obj || typeof obj !== 'object' || Array.isArray(obj)) throw new Error('not a settings object');
      adopt(obj);
    } catch (e) { toast(t('Not a Vantage settings file')); }
  });
  $('reset-all').addEventListener('click', async () => {
    if (!await confirmDialog(t('Reset all settings?'), t('Every setting, hotkey and casting override goes back to its default.'), t('Reset'))) return;
    resetSettings(); toast(t('Settings reset')); location.reload();
  });
}

// Side effects of particular settings beyond saving them.
function afterSet(path) {
  if (path === 'tooltipShowMode') {
    settings.tooltips = tooltipLevel() !== 'off';
    document.body.dataset.tooltips = tooltipLevel();
    return 'rerender';
  }
  if (path === 'toggleHTMLServer') return 'rerender';
  if (/^enable(Sprite|Terrain)Mods$/.test(path)) pushMods();
  if (path.startsWith('scoreboard.')) {
    const sb = settings.scoreboard;
    sb.numberOfMatches = Math.max(1, Math.min(21, Math.round(+sb.numberOfMatches || 1)));
    return 'rerender';
  }
  return null;
}

export function renderSettings(apply) {
  if (apply) renderSettings._apply = apply;
  const doApply = () => { const f = renderSettings._apply; if (f) f(); };
  const rerender = () => renderSettings();
  const el = $('overlay-settings');
  syncCastingMaps();
  if (!SET_TABS.some(([k]) => k === setTab)) setTab = 'interface';
  const body = { interface: interfaceTab, dashboard: dashboardTab, graphics: graphicsTab, sound: soundTab, casting: castingTab, skins: skinsTab, hotkeys: hotkeysTab, profiles: profilesTab, help: helpTab }[setTab]();
  el.innerHTML = `${closeBtn()}<h2>${t('Settings')}</h2>
    <div class="tabs set-tabs">${SET_TABS.map(([k, l]) => `<button data-stab="${k}" class="${k === setTab ? 'on' : ''}">${t(l)}</button>`).join('')}</div>
    <div class="set-body">${body}</div>`;
  wireClose(el);
  el.querySelectorAll('[data-stab]').forEach((b) => b.addEventListener('click', () => { setTab = b.dataset.stab; rerender(); }));
  // generic settings controls
  el.querySelectorAll('[data-set]').forEach((inp) => {
    const ev = inp.type === 'range' ? 'input' : 'change';
    inp.addEventListener(ev, () => {
      const type = inp.dataset.type, path = inp.dataset.set;
      let v;
      if (type === 'bool') v = inp.checked;
      else if (type === 'bool-inv') v = !inp.checked;
      else if (type === 'flag') {
        const cur = (getSetting(path) || []).filter((f) => f !== inp.dataset.flag);
        v = inp.checked ? [...cur, inp.dataset.flag] : cur;
      }
      else if (type === 'num') {
        v = +inp.value;
        if (inp.type === 'number') {
          if (inp.value === '' || Number.isNaN(v)) return;
          v = Math.max(+inp.min, Math.min(+inp.max, v));
        }
      } else v = inp.value;
      if (path === 'endgameAutoClose') v = +v;
      setPath(path, v);
      const out = inp.nextElementSibling;
      if (out && out.tagName === 'OUTPUT') out.textContent = fmtSetting(path, v);
      const next = afterSet(path);
      saveSettings(); doApply();
      if (next === 'rerender') rerender();
    });
  });
  const ls = $('lang-select');
  if (ls) ls.addEventListener('change', async (e) => {
    settings.language = e.target.value; saveSettings();
    await setLanguage(settings.language);
    // Unit, building and tech names come from the game's strings in that language.
    const cat = await api(`/api/catalog?lang=${settings.language}`).catch(() => null);
    if (cat) S.catalog = cat;
    rerender(); doApply();
  });
  if (setTab === 'skins') {
    wireSkins(el, doApply, rerender);
    if (!skinsCache) loadSkins().then(() => { if (isOpen('overlay-settings') && setTab === 'skins') rerender(); });
  }
  // dashboard pages
  if (setTab === 'dashboard') { wireDashboard(el, doApply); wireLegacyDash(el, doApply, rerender); }
  // panel offsets (casting)
  if (setTab === 'casting') wireOffsets(el, doApply, rerender);
  // graphics: terrain grid
  const gr = $('grid-recommended');
  if (gr) gr.addEventListener('click', () => { settings.terrainGrid = 0.5; saveSettings(); doApply(); rerender(); });
  // game directory: the server validates it (AoE2DE_s.exe) and re-points its game data
  const gd = $('game-dir-save');
  if (gd) gd.addEventListener('click', async () => {
    const path = $('game-dir').value.trim();
    const r = await api('/api/game_dir', { path }).catch(() => null);
    if (!r || !r.ok) { toast(t((r && r.error) || 'Could not reach the Vantage server')); return; }
    settings.lastUsedGameDirectory = path; saveSettings();
    S.catalogVersion = -1; toast(t('Game directory applied'));
  });
  // graphics: mod folders
  const md = $('mod-dirs-save');
  if (md) md.addEventListener('click', () => {
    settings.modDirectories = $('mod-dirs').value.split('\n').map((s) => s.trim()).filter(Boolean);
    saveSettings(); pushMods(); toast(t('Saved'));
  });
  // casting
  el.querySelectorAll('[data-match]').forEach((s) => s.addEventListener('change', () => {
    const sb = { ...DEFAULT_SETTINGS.scoreboard, ...(settings.scoreboard || {}) };
    const n = Math.max(1, Math.min(21, +sb.numberOfMatches || 1));
    const matches = seriesMatches(sb, n);
    const v = s.value;
    matches[+s.dataset.match] = { winner: v === '' ? null : /^\d+$/.test(v) ? +v : v };
    settings.scoreboard = { ...sb, matches };
    saveSettings(); doApply(); rerender();
  }));
  const sbe = $('sb-enabled');
  if (sbe) sbe.addEventListener('change', () => { settings.scoreboard = { ...(settings.scoreboard || {}), enabled: sbe.checked }; saveSettings(); doApply(); });
  el.querySelectorAll('[data-seed]').forEach((inp) => inp.addEventListener('change', () => {
    const sb = { ...DEFAULT_SETTINGS.scoreboard, ...(settings.scoreboard || {}) };
    const seeds = { ...(sb.seeds || {}) };
    if (inp.value.trim()) seeds[inp.dataset.seed] = inp.value.trim(); else delete seeds[inp.dataset.seed];
    settings.scoreboard = { ...sb, seeds };
    saveSettings(); doApply();
  }));
  const pOf = (id) => players().find((p) => String(p.id) === String(id)) || { id, name: `P${id}` };
  el.querySelectorAll('[data-pname]').forEach((inp) => inp.addEventListener('change', () => { setCasting(['playerNames'], pOf(inp.dataset.pname), inp.value.trim()); saveSettings(); doApply(); }));
  el.querySelectorAll('[data-pimgsel]').forEach((s) => s.addEventListener('change', () => { setCasting(['playerImages'], pOf(s.dataset.pimgsel), s.value); saveSettings(); doApply(); rerender(); }));
  el.querySelectorAll('[data-pimg]').forEach((inp) => inp.addEventListener('change', () => { setCasting(['playerImages'], pOf(inp.dataset.pimg), inp.value.trim()); saveSettings(); doApply(); rerender(); }));
  el.querySelectorAll('[data-tname]').forEach((inp) => inp.addEventListener('change', () => {
    const names = { ...settings.teamNames };
    if (inp.value) names[inp.dataset.tname] = inp.value; else delete names[inp.dataset.tname];
    settings.teamNames = names; saveSettings(); doApply();
  }));
  el.querySelectorAll('[data-captain]').forEach((s) => s.addEventListener('change', () => {
    const caps = { ...settings.teamCaptains };
    if (s.value) caps[s.dataset.captain] = +s.value; else delete caps[s.dataset.captain];
    settings.teamCaptains = caps;
    settings.scoreboard = { ...(settings.scoreboard || {}), captains: { ...caps } };
    saveSettings(); doApply();
  }));
  const ir = $('img-refresh');
  if (ir) ir.addEventListener('click', async () => { await loadImages(true); rerender(); });
  if (setTab === 'casting' && !imagesCache) loadImages().then((imgs) => { if (imgs.length && isOpen('overlay-settings') && setTab === 'casting') rerender(); });
  wireFolders(el);
  // hotkeys
  if (setTab === 'hotkeys') wireHotkeys(el, doApply, rerender);
  // profiles / help
  if (setTab === 'profiles') wireProfiles();
  const hd = $('help-docs');
  if (hd) hd.addEventListener('click', openDocs);
  const hq = $('help-quick');
  if (hq) hq.addEventListener('click', () => toggle('overlay-help', renderHelp));
  const ht = $('help-tutorial');
  if (ht) ht.addEventListener('click', () => { closeAll(); const f = actions().showTutorial; if (f) f(); });
}

function wireHotkeys(el, doApply, rerender) {
  const save = (action, list) => {
    const custom = { ...(settings.customHotkeys || {}) };
    const def = HK.KEYMAP[action][0];
    if (list === null || (list.length === 1 && list[0] === def)) delete custom[action];
    else custom[action] = list.length === 1 ? list[0] : list;
    settings.customHotkeys = custom; saveSettings(); doApply(); rerender();
  };
  const capture = (inp, onCombo) => {
    const prev = inp.value;
    inp.value = t('Press keys…'); inp.classList.add('capturing');
    const stop = () => { inp.removeEventListener('keydown', onKey, true); inp.removeEventListener('blur', onBlur); inp.classList.remove('capturing'); };
    const onBlur = () => { stop(); inp.value = prev; };
    const onKey = (e) => {
      e.preventDefault(); e.stopPropagation();
      if (e.key === 'Escape') { stop(); inp.value = prev; inp.blur(); return; }
      if (e.key === 'Backspace' || e.key === 'Delete') { stop(); onCombo(''); return; }
      const combo = comboFromEvent(e);
      if (!combo) return;
      stop(); onCombo(combo);
    };
    inp.addEventListener('keydown', onKey, true);
    inp.addEventListener('blur', onBlur);
  };
  // Focusing a binding captures a replacement; the + button focuses it in "add" mode.
  el.querySelectorAll('[data-hk]').forEach((inp) => inp.addEventListener('focus', () => {
    const a = inp.dataset.hk, add = inp._add;
    inp._add = false;
    const existing = bindingsOf(a);
    capture(inp, (combo) => {
      if (!add) save(a, combo ? [combo] : []);
      else if (combo && !existing.includes(combo)) save(a, [...existing, combo]);
      else rerender();
    });
  }));
  el.querySelectorAll('[data-hkadd]').forEach((b) => b.addEventListener('click', () => {
    const inp = el.querySelector(`[data-hk="${b.dataset.hkadd}"]`);
    if (!inp || inp.disabled) return;
    inp.blur();
    inp._add = true;
    inp.focus();
  }));
  el.querySelectorAll('[data-hkreset]').forEach((b) => b.addEventListener('click', () => save(b.dataset.hkreset, null)));
  $('hk-reset-all').addEventListener('click', () => { settings.customHotkeys = {}; saveSettings(); doApply(); rerender(); toast(t('Hotkeys reset')); });
  const filt = $('hk-filter');
  filt.addEventListener('input', () => {
    const q = filt.value.toLowerCase();
    el.querySelectorAll('[data-hkrow]').forEach((tr) => { tr.style.display = !q || tr.textContent.toLowerCase().includes(q) || tr.querySelector('input').value.toLowerCase().includes(q) ? '' : 'none'; });
  });
  $('hk-save').addEventListener('click', () => {
    try { settings.customHotkeys = JSON.parse($('hk-json').value || '{}'); saveSettings(); toast(t('Hotkeys saved')); doApply(); rerender(); } catch (e) { toast(t('Invalid JSON')); }
  });
}

// =====================================================================================
// quick reference
// =====================================================================================

export function renderHelp() {
  $('overlay-help').classList.remove('tutorial-card');
  const el = $('overlay-help');
  const mouse = [
    ['Right-drag / middle-drag', 'Pan'], ['Wheel', 'Zoom at cursor'], ['Click / drag', 'Select / box select'],
    ['Double-click', 'Select same type on screen'], ['Shift / Ctrl + select', 'Add / toggle'],
    ['Shift + right-click unit', 'Switch perspective to its owner'], ['Minimap click/drag', 'Move camera'],
    ['Player name (scoreboard)', 'Cycle player colour'], ['Age icon', 'Go to town centre'],
    ['Event time', 'Jump to that moment'], ['Event row', 'Jump camera to location'],
    ['Time bar click', 'Seek'], ['Time bar right-click', 'Add / remove bookmark'], ['Chart right-click', 'Jump to time'],
    ['Chart wheel', 'Zoom the chart'],
  ];
  const keyCell = (k) => (k === '—' ? `<span class="hint">${t('unbound')}</span>` : `<kbd>${esc(keyLabel(k))}</kbd>`);
  const section = (title, rows) => `<section class="keys-group"><h3>${t(title)}</h3><table class="keys">${rows.join('')}</table></section>`;
  // Sections flow into as many columns as the window has room for, so the whole
  // reference is in view at once instead of one long list beside an empty half.
  const groups = HK.describeKeyGroups().map(([title, rows]) => section(title, rows.map(([k, d]) => `<tr><td>${keyCell(k)}</td><td>${esc(t(d))}</td></tr>`)));
  groups.splice(2, 0, section('Mouse', mouse.map(([k, d]) => `<tr><td><kbd>${esc(t(k))}</kbd></td><td>${esc(t(d))}</td></tr>`)));
  el.innerHTML = `${closeBtn()}<h2>${t('Quick reference')}</h2>
    ${aboutLine()}
    <p class="hint">${t('Change any key in Settings → Hotkeys.')} <button class="link" id="qr-docs">${t('Documentation')}</button></p>
    <div class="keys-groups">${groups.join('')}</div>`;
  wireClose(el);
  const d = $('qr-docs');
  if (d) d.addEventListener('click', openDocs);
}

// =====================================================================================
// end of game
// =====================================================================================

let egTimer = null;
const MEDALS = ['🥇', '🥈', '🥉'];

// -- commendations: "Most kills" (Autocast entry) and "Most created" per side ------------

// The single unit with the most kills in the game ("killsByEntity").
function topKiller(sm) {
  let best = null;
  for (const p of players()) {
    const mk = sm[p.id] && sm[p.id].most_kills;
    if (mk && mk.kills > 0 && (!best || mk.kills > best.kills)) best = { ...mk, pid: p.id };
  }
  return best;
}

// Unit-line name: catalog unit_lines (the game's unitlines.json), else the icon unit's name.
function lineName(key, mid) {
  const lines = (S.catalog && S.catalog.unit_lines) || {};
  const l = lines[key];
  // The game's line table is English-only: "Spearman Line" becomes "<first unit> line" in the chosen language.
  if (l && /^.+ Line$/.test(l.name || '') && Array.isArray(l.ids) && l.ids.length) return t('{unit} line', { unit: unitInfo(+l.ids[0]).name });
  return (l && l.name) || unitInfo(+mid).name;
}

// Unit classes that count as military when the catalog has no `military` flag
// (archer, soldier, cavalry, siege, monk, warship, conquistador, elephants, hero,
// petard, cavalry archer, hand cannoneer, swordsman, pikeman, scout, spearman,
// packed/unpacked siege, scorpion, raiders).
const MIL_CLASSES = new Set([0, 6, 12, 13, 18, 22, 23, 24, 25, 26, 28, 35, 36, 44, 45, 46, 47, 50, 51, 54, 55, 56, 57]);

// Client-side fallback for servers without most_created_lines: per-master
// counts merged by catalog line, military only, excluding masters 1252/1253.
function linesFromMasters(list) {
  const by = new Map();
  for (const [mid, n] of list || []) {
    const u = unitInfo(+mid);
    if (+mid === 1252 || +mid === 1253 || u.most_created_ok === false || u.military === false) continue;
    if (u.military === undefined && !MIL_CLASSES.has(u.cls)) continue;
    const key = u.line || `m${mid}`;
    const e = by.get(key) || { key, count: 0, best: -1, icon: +mid };
    e.count += n;
    if (n > e.best) { e.best = n; e.icon = +mid; }
    by.set(key, e);
  }
  return [...by.values()].sort((a, b) => b.count - a.count).map((e) => [e.key, e.count, e.icon]);
}

// Top 3 created unit lines of one side: the server's team list when it has one,
// else the members' per-player lists merged.
function sideCreated(sm, tm) {
  const byTeam = sm.teams_most_created || {};
  // The map is keyed by the lobby's team_key (never by a player id: key pid+1
  // of one side would collide with the first player id of another).
  if (Array.isArray(byTeam[String(tm.key)])) return byTeam[String(tm.key)].slice(0, 3);
  const merged = new Map();
  for (const p of tm.players) {
    const s = sm[p.id] || {};
    const rows = Array.isArray(s.most_created_lines) ? s.most_created_lines : linesFromMasters(s.most_created);
    for (const [key, n, icon] of rows) {
      const e = merged.get(key) || { n: 0, icon, top: 0 };
      e.n += n;
      if (n > e.top) { e.top = n; e.icon = icon; }
      merged.set(key, e);
    }
  }
  return [...merged.entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 3).map(([key, e]) => [key, e.n, e.icon]);
}

function commendations(sm, ps) {
  const killer = topKiller(sm);
  const ts = teams().filter((tm) => tm.players.some((p) => ps.some((q) => q.id === p.id)));
  const two = ts.length === 2;
  const sides = two ? sideTeams() : ts;
  const created = sides.map((tm, i) => {
    const rows = sideCreated(sm, tm);
    if (!rows.length) return '';
    const mirrored = two && i === 0; // the left side faces right, towards the other team
    return `<div class="eg-created-side"><div class="eg-side-name">${tm.players.map((p) => `<span style="color:${playerTextColor(p.id)}">${esc(playerName(p.id))}</span>`).join(' + ')}</div>
      <div class="eg-created-list">${rows.map(([key, n, icon], k) => {
        const src = unitIcon(+icon);
        const name = lineName(key, icon);
        return `<span class="eg-created" ${tip(name, t('{n} created', { n }))}><span class="eg-rank">#${k + 1}</span>${src ? `<img class="eg-unit${mirrored ? ' mirror' : ''}" src="${src}" alt="">` : ''}<b>${fmtNum(n)}</b><span class="hint">${esc(name)}</span></span>`;
      }).join('')}</div></div>`;
  }).join('');
  const kills = killer ? (() => {
    const u = unitInfo(+killer.unit_master);
    const src = unitIcon(+killer.unit_master);
    const can = killer.id != null;
    return `<div class="eg-card eg-mostkills"><h4>${t('Most kills')}</h4>
      <div class="eg-killer">${src ? `<img class="eg-unit" src="${src}" alt="">` : ''}<div><b>${esc(u.name)}</b>${killer.id != null ? ` <span class="hint">#${esc(killer.id)}</span>` : ''}
        <div><span style="color:${playerTextColor(killer.pid)}">${esc(playerName(killer.pid))}</span> · ${t('Total kills: {n}', { n: killer.kills })}</div></div></div>
      <button id="eg-autocast" class="on" data-unit="${can ? esc(killer.id) : ''}" ${can ? '' : 'disabled'} ${tip(t('Show all'), t('Autocast replays this unit\'s life: its birth, every kill and its death'))}>▶ ${t('Show all')}</button></div>`;
  })() : '';
  const most = created ? `<div class="eg-card eg-mostcreated"><h4 ${tip(t('Most created'), t('Military units created by each side, grouped by unit line'))}>${t('Most created')}</h4><div class="eg-created-sides${two ? ' two' : ''}">${created}</div></div>` : '';
  return kills || most ? `<div class="eg-commend">${kills}${most}</div>` : '';
}

export async function renderEndgame(seek) {
  const el = $('overlay-endgame');
  const sk = seekFn(seek);
  S.summary = await api('/api/summary').catch(() => S.summary);
  if (!S.series) S.series = await api('/api/series').catch(() => S.series);
  // Right after a jump the view is still loading: whether the game ended is read
  // from the last moment itself.
  const lastView = S.view || (await fetchView(S.end).catch(() => null));
  const ended = !!(lastView && lastView.game_ended);
  const src = (S.session && S.session.source) || {};
  const gameDone = Number(src.game_state) === 3; // the game itself reports the match over
  const replayed = !!(src.replay || (src.header && src.header.replay));
  const sm = S.summary || {};
  let ps = players().filter((p) => sm[p.id]);
  const placed = ps.some((p) => sm[p.id].placing);
  if (placed) ps = ps.slice().sort((a, b) => (sm[a.id].placing || 99) - (sm[b.id].placing || 99));
  const winners = ps.filter((p) => sm[p.id].status === 'won');
  const pname = (p) => `<span style="color:${playerTextColor(p.id)}">${esc(playerName(p.id))}</span>`;
  const banner = winners.length
    ? t('{who} is victorious!', { who: winners.map(pname).join(' & ') })
    : ps.length && ps.every((p) => sm[p.id].status !== 'playing') ? t('Everyone lost!')
    // A recording can stop before the game does: say so rather than "Game over". The
    // game's own "match over" signal wins, and a replay says only that it ends, as
    // its file does not say whether the match went on.
    : !ended && !gameDone && ps.some((p) => sm[p.id].status === 'playing')
      ? (replayed ? t('The replay ends here') : t('The recording ends here; the game went on'))
    : t('Game over');
  const podium = placed ? `<div class="placings">${ps.filter((p) => sm[p.id].placing && sm[p.id].placing <= 3).map((p) => {
    const pl = sm[p.id].placing;
    return `<div class="place place-${pl}"><span class="medal">${MEDALS[pl - 1]}</span><b>${ordinal(pl)}</b>${pname(p)}</div>`;
  }).join('')}</div>` : '';
  const row = (label, f, detail) => {
    const cells = ps.map((p) => { try { return f(sm[p.id], p); } catch { return undefined; } });
    if (cells.every((x) => x === undefined)) return '';
    return `<tr><td ${tip(t(label), detail ? t(detail) : '')}>${t(label)}</td>${cells.map((x) => `<td>${x ?? '–'}</td>`).join('')}</tr>`;
  };
  const ageCell = (s) => [1, 2, 3].map((a) => (s.age_times && s.age_times[a] ? `<a class="seek" data-seek="${s.age_times[a]}" ${tip(t('Jump to {time}', { time: fmtTime(s.age_times[a]) }))}>${fmtTime(s.age_times[a])}</a>` : '–')).join(' · ');
  const saved = src.recording_saved || (S.session && S.session.mode === 'live' ? src.recording : null);
  const autoClose = +(settings.endgameAutoClose || 0);
  el.innerHTML = `${closeBtn()}<div id="endgame-banner">${banner}</div>${podium}
    <h3 class="eg-sub">${t('Performance')}</h3>
    <table class="agg eg-table"><tr><th></th>${ps.map((p) => `<th style="color:${playerTextColor(p.id)}">${esc(playerName(p.id))}</th>`).join('')}</tr>
    ${row('Placing', (s) => (s.placing ? ordinal(s.placing) : undefined))}
    ${row('Result', (s) => esc(s.status === 'won' || (s.status === 'playing' && ended) ? t('Winner') : t(s.status)))}
    ${row('Kills / losses', (s) => `${s.kills} / ${s.deaths}`)}
    ${row('Resources collected', (s) => fmtNum(s.collected.total))}
    ${row('Floating resources (avg / peak)', (s) => `${fmtNum(s.floating.avg)} / ${fmtNum(s.floating.peak)}`, 'Unspent resources')}
    ${row('FloatHrs', (s) => (s.float_hrs == null ? undefined : (+s.float_hrs).toFixed(1)), 'Unspent resources summed over time, in resource-hours')}
    ${row('Average / peak APM', (s) => `${s.avg_apm} / ${s.peak_apm}`)}
    ${row('geAPM', (s) => (s.geapm == null ? undefined : fmtNum(s.geapm)), 'Game-effective APM: eAPM without repeated or spammed commands')}
    ${row('Villager idle time', (s) => `${fmtNum(Math.round(s.idle_seconds / 60))} ${t('vil·min')}`, 'Villager-minutes idle (villagers × minutes)')}
    ${row('Worker efficiency (worst minute)', (s) => `${s.efficiency}% (${s.worst_minute_efficiency}%)`)}
    ${row('Most kills (single unit)', (s) => (s.most_kills && s.most_kills.kills ? `${unitImg(s.most_kills.unit_master)} ${s.most_kills.kills}` : undefined))}
    ${row('Age-up times', ageCell)}
    </table>
    ${commendations(sm, ps)}
    <div class="chart-wrap eg-chart"><canvas id="eg-chart"></canvas></div>
    <p class="hint eg-hint">${t('Click the chart or an age-up time to jump back to that moment.')}</p>
    <div class="eg-foot">
      ${saved ? `<div>${savedLine(saved)}</div>` : ''}
      <div class="eg-actions">
        <button data-egseek="-60000">${t('Back 1 min')}</button><button data-egseek="-300000">${t('Back 5 min')}</button>
        <button id="eg-stats">${t('Statistics')}</button>
        <label class="inline" ${tip(t('Close the end-of-game screen'))}>${t('Auto-close')}
          <select id="eg-autoclose">${[[0, 'Never'], [10, '10 s'], [30, '30 s'], [60, '1 min']].map(([v, l]) => `<option value="${v}" ${v === autoClose ? 'selected' : ''}>${t(l)}</option>`).join('')}</select></label>
        <span id="eg-countdown" class="hint"></span>
      </div>
    </div>`;
  wireClose(el);
  wireFolders(el);
  const sa = $('eg-autocast');
  if (sa) sa.addEventListener('click', () => {
    const unitId = +sa.dataset.unit;
    closeAll();
    document.dispatchEvent(new CustomEvent('vantage:autocast', { detail: { unitId } }));
  });
  const jump = (at) => { if (!sk) return; sk(Math.max(S.start, Math.min(S.end, at))); toast(t('Jumped to {time}', { time: fmtTime(S.t) })); closeAll(); };
  el.querySelectorAll('[data-seek]').forEach((a) => a.addEventListener('click', () => jump(+a.dataset.seek)));
  el.querySelectorAll('[data-egseek]').forEach((b) => b.addEventListener('click', () => jump(S.end + +b.dataset.egseek)));
  $('eg-stats').addEventListener('click', () => toggle('overlay-stats', () => renderStats(sk)));
  $('eg-autoclose').addEventListener('change', (e) => { settings.endgameAutoClose = +e.target.value; saveSettings(); armAutoClose(); });
  requestAnimationFrame(() => drawChart($('eg-chart'), {
    key: 'score', type: 'line', transform: 'actual', hidden: new Set(), techMarks: true, ecoTechs: false, milTechs: false,
    range: fullRange(), clickSeek: true, onSeek: () => closeAll(),
  }, sk));
  armAutoClose();
}

function armAutoClose() {
  clearInterval(egTimer);
  const secs = +(settings.endgameAutoClose || 0);
  const cd = $('eg-countdown');
  if (cd) cd.textContent = '';
  if (!secs) return;
  const until = Date.now() + secs * 1000;
  egTimer = setInterval(() => {
    if (!isOpen('overlay-endgame')) { clearInterval(egTimer); return; }
    const left = Math.ceil((until - Date.now()) / 1000);
    const c = $('eg-countdown');
    if (c) c.textContent = t('closes in {n} s', { n: Math.max(0, left) });
    if (left <= 0) { clearInterval(egTimer); closeAll(); }
  }, 500);
}

// =====================================================================================
// background: one-off migrations, user skin, "saved to vault", casting identity sync
// =====================================================================================

migrateReplayFilters();
migrateMods();
applySkin();
setInterval(pollSkins, 3000);
if (settings.enableSpriteMods || settings.enableTerrainMods) pushMods();
if (settings.lastUsedGameDirectory) api('/api/game_dir', { path: settings.lastUsedGameDirectory }).catch(() => null);
{
  let lastSaved, lastSig = '';
  setInterval(() => {
    if (S.session) {
      const saved = (S.session.source && S.session.source.recording_saved) || null;
      if (lastSaved !== undefined && saved && saved !== lastSaved) toast(t('Saved to vault: {file}', { file: baseName(saved) }));
      lastSaved = saved;
    }
    const sig = players().map((p) => `${p.id}=${castingKey(p)}`).join('|');
    if (sig !== lastSig) { lastSig = sig; syncCastingMaps(); }
  }, 1000);
}

export { AGE_NAMES, DEFAULT_SETTINGS };
export { KEYMAP } from './hotkeys.js';

// Copy the OBS browser-source address (Casting tab).
document.addEventListener('click', (e) => {
  if (e.target && e.target.id === 'obs-copy') {
    const v = document.getElementById('obs-url').value;
    (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(() => toast(t('Copied'))).catch(() => { document.getElementById('obs-url').select(); });
  }
});
