// Widgets for the layout editor's library: six single metrics, a chart of any
// series, the series score and a text or image. Each is an ordinary HUD panel
// (movable, resizable, per scene); none shows unless it was added.

import { S, fmtTime, fmtNum, esc, playerStats, playerMarkColor, playerTextColor, playerName, teamName, isTwoTeamLayout, sideTeams } from './state.js';
import { t } from './i18n.js';
import { HUD_PARTS } from './panels.js';
import { METRICS, KILLS_LOSSES } from './metrics.js';
import { sumStat } from './team-board.js';
import { sideValue } from './story.js';
import { seriesLabel } from './overlays.js';
import { hud } from './layout.js';

function sides() {
  const teams = HUD_PARTS.orderedTeams();
  if (isTwoTeamLayout() && teams.length === 2) return sideTeams();
  return teams.flatMap((tm) => tm.players.map((p) => ({ key: `p${p.id}`, players: [p], solo: true })));
}
const stats = (side) => side.players.map((p) => playerStats(p.id)).filter(Boolean);
const name = (side) => (side.solo || side.players.length === 1 ? playerName(side.players[0].id) : teamName(side));

// id -> { label, value(side) -> number | null, text?(side, value) -> string, delta?: show the lead, lower? }
const METRIC_WIDGETS = {
  'w-army': { label: METRICS.army_value.label, value: (s) => sumStat(stats(s), METRICS.army_value.f), delta: true },
  'w-vil': { label: METRICS.villagers.label, value: (s) => sumStat(stats(s), METRICS.villagers.f), delta: true },
  'w-bank': { label: 'Bank + rate', value: (s) => sumStat(stats(s), METRICS.banked.f),
    text: (s, v) => `${fmtNum(Math.floor(v))} <small>+${fmtNum(sumStat(stats(s), METRICS.rate.f) ?? 0)}/${t('min')}</small>` },
  'w-idletc': { label: METRICS.tc_idle.label, value: (s) => sideValue(S.series, s, 'tc_idle', S.t), text: (s, v) => fmtTime(v * 1000), lower: true },
  'w-kd': { label: KILLS_LOSSES.label, value: (s) => sumStat(stats(s), METRICS.kills.f), text: (s, v) => `${v}/${sumStat(stats(s), METRICS.losses.f) ?? 0}` },
  'w-eapm': { label: METRICS.eapm.label, value: (s) => {
    const vs = s.players.map((p) => S.view && S.view.apm && S.view.apm[p.id] && S.view.apm[p.id].effective).filter((v) => typeof v === 'number');
    return vs.length ? Math.round(vs.reduce((a, b) => a + b, 0) / vs.length) : null;
  } },
};

function renderMetric(id) {
  const def = METRIC_WIDGETS[id];
  return (el) => {
    if (!S.view) { HUD_PARTS.setHtml(el, ''); return; }
    const list = sides(), values = list.map(def.value);
    const two = list.length === 2 && values.every((v) => v != null);
    const diff = two ? values[0] - values[1] : 0;
    const cell = (side, v, i) => `<span class="wm-side" data-ui-key="side-${i}"><i style="background:${playerMarkColor(side.players[0].id)}"></i>${two ? '' : `<span class="wm-name">${esc(name(side))}</span>`}<b style="color:${playerTextColor(side.players[0].id)}">${v == null ? '–' : def.text ? def.text(side, v) : fmtNum(v)}</b></span>`;
    const lead = two && def.delta && diff !== 0 ? `<em class="wm-delta" style="color:${playerTextColor(list[diff > 0 ? 0 : 1].players[0].id)}">${diff > 0 ? '◀' : ''}${fmtNum(Math.abs(diff))}${diff < 0 ? '▶' : ''}</em>` : '';
    const spoken = `${t(def.label)}: ${list.map((s, i) => `${name(s)} ${values[i] == null ? t('unknown') : String(def.text ? def.text(s, values[i]) : values[i]).replace(/<[^>]+>/g, '')}`).join(', ')}`;
    HUD_PARTS.setHtml(el, `<div class="wm${two ? ' two' : ''}" role="img" aria-label="${esc(spoken)}"><span class="wm-label">${esc(t(def.label))}</span><span class="wm-values">${two ? `${cell(list[0], values[0], 0)}${lead}${cell(list[1], values[1], 1)}` : list.map((s, i) => cell(s, values[i], i)).join('')}</span></div>`);
  };
}

const chartState = { key: '', at: -1, w: 0 };
function renderChart(el) {
  const key = (hud().widgets['w-chart'] || {}).series || 'army_value';
  if (el.dataset.series !== key) {
    el.dataset.series = key;
    el.innerHTML = `<div class="wc-title">${esc(seriesLabel(key))}</div><canvas role="img" aria-label="${esc(t('Chart: {series}', { series: seriesLabel(key) }))}"></canvas>`;
    new ResizeObserver(() => { chartState.at = -1; }).observe(el);
    chartState.at = -1;
  }
  // A redraw a second of game time at most, and after a resize.
  const canvas = el.querySelector('canvas'), w = canvas.clientWidth;
  if (chartState.key === key && Math.abs(S.t - chartState.at) < 1000 && chartState.w === w) return;
  Object.assign(chartState, { key, at: S.t, w });
  HUD_PARTS.miniChart(canvas, key);
}

function safeImage(url) { return typeof url === 'string' && /^(https?:\/\/|data:image\/|\/)/i.test(url.trim()) ? url.trim() : ''; }
function renderText(el) {
  const w = hud().widgets['w-text'] || {}, image = safeImage(w.image);
  const body = `${image ? `<img src="${esc(image)}" alt="">` : ''}${w.text ? `<span>${esc(w.text)}</span>` : ''}`;
  HUD_PARTS.setHtml(el, body || `<span class="hint wt-empty">${esc(t('Text or image: set it in Edit layout (Alt+L)'))}</span>`);
}

function renderSeries(el) {
  const sr = HUD_PARTS.series(), list = sides();
  if (!sr.n && !sr.text) { HUD_PARTS.setHtml(el, `<span class="hint wt-empty">${esc(t('No series set: Settings → Casting'))}</span>`); return; }
  const score = list.length === 2 && sr.n && !sr.override
    ? `<span class="ws-score"><b style="color:${playerTextColor(list[0].players[0].id)}">${sr.wins[HUD_PARTS.sideKey(list[0])] || 0}</b> – <b style="color:${playerTextColor(list[1].players[0].id)}">${sr.wins[HUD_PARTS.sideKey(list[1])] || 0}</b></span>` : '';
  HUD_PARTS.setHtml(el, `<span class="ws-text">${esc(sr.text)}</span>${score}`);
}

let index = 0;
function make(id, label, cls = '') {
  return () => {
    const el = document.createElement('section');
    el.id = id; el.className = `panel hud-widget ${cls}`.trim();
    el.style.setProperty('--w-i', String(index++));
    el.setAttribute('role', 'region'); el.setAttribute('aria-label', t(label));
    document.getElementById('hud').appendChild(el);
    return el;
  };
}

export const PANEL_RENDERERS = {
  ...Object.fromEntries(Object.entries(METRIC_WIDGETS).map(([id, def]) => [id, { create: make(id, def.label, 'hud-metric'), render: renderMetric(id) }])),
  'w-chart': { create: make('w-chart', 'Chart', 'hud-chart'), render: renderChart },
  'w-text': { create: make('w-text', 'Text or image', 'hud-text'), render: renderText },
  'w-series': { create: make('w-series', 'Series score', 'hud-series'), render: renderSeries },
};
