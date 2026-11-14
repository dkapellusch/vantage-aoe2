// Three small caster panels:
//
// Focus slot (#focus)  one card at a time: Production, Eco or a fight (the
//                      latest, or one picked from every fight so far). Alt+C /
//                      Alt+X cycle it (when the dashboard is hidden); empty is
//                      a valid state.
// Event ticker (#ticker) the event log cut down to key events (age-ups, a town
//                      centre or castle lost, wonders, resignations), two
//                      lines, fading after about 8 seconds.
// Selection chip (#selchip) one line for the selection; opens the full
//                      Selection panel.

import { S, SPEEDS, fmtTime, fmtNum, esc, playerStats, playerMarkColor, playerTextColor, playerName, unitInfo, unitIcon, isTwoTeamLayout, sideTeams, RES } from './state.js';
import { t } from './i18n.js';
import { HUD_PARTS } from './panels.js';
import { centerOn, selectedRows } from './world.js';
import { METRICS } from './metrics.js';
import { sumStat } from './team-board.js';
import { fightsOf, fightsUpTo, tickerEvents } from './fights.js';
import { compareTableHtml, sideStats } from './compare-table.js';
import { hud, setHud, expandSelection, selectionExpanded, isVisible } from './layout.js';

// The card titles say "Focus": the production card is not the Production & composition panel.
// (The research card is gone: the Live research panel shows the same.)
const CARDS = [['production', 'Prod', 'Focus: production'], ['eco', 'Eco', 'Focus: economy'], ['fight', 'Fight', 'Focus: fights']];

function sides() {
  const teams = HUD_PARTS.orderedTeams();
  if (isTwoTeamLayout() && teams.length === 2) return sideTeams();
  return teams.flatMap((tm) => tm.players.map((p) => ({ key: `p${p.id}`, players: [p], solo: true })));
}

// -- Focus slot --------------------------------------------------------------------------------

// The activities that count as work in worker efficiency (timeline.py _PRODUCTIVE).
const PRODUCTIVE = ['gather_food', 'gather_wood', 'gather_gold', 'gather_stone', 'building', 'repairing'];

/**
 * A side's worker efficiency (%), whole game (`all`) or over the last minute (`last_minute`).
 * One player: the game's own figure. A team: its players' villager-seconds pooled (productive
 * over all, garrisoned left out, as timeline.py counts them), so a player with more villagers
 * weighs more; when a player's breakdown is missing, the plain mean of the percentages.
 */
export function sideEfficiency(stats, window = 'all') {
  const pctKey = window === 'all' ? 'pct' : 'pct_lm';
  const effs = stats.map((s) => s && s.efficiency).filter((e) => e && typeof e[pctKey] === 'number');
  if (!effs.length) return null;
  if (effs.length === 1) return effs[0][pctKey];
  if (effs.every((e) => e[window] && typeof e[window] === 'object')) {
    let work = 0, time = 0;
    for (const e of effs) {
      for (const [k, v] of Object.entries(e[window])) if (k !== 'garrisoned' && Number.isFinite(v)) time += v;
      for (const k of PRODUCTIVE) work += Number.isFinite(e[window][k]) ? e[window][k] : 0;
    }
    return time > 0 ? Math.round(1000 * work / time) / 10 : null;
  }
  return effs.reduce((a, e) => a + e[pctKey], 0) / effs.length;
}

// As on the Review cards.
const TC_IDLE_DETAIL = 'Town centre time without a villager in production, while still growing';

export function ecoRows(list) {
  const stats = list.map(sideStats);
  const of = (f) => stats.map((s) => sumStat(s, f));
  const num = (vals, f = (v) => v) => vals.map((v) => fmtNum(f(v ?? 0)));
  const time = (vals) => vals.map((v) => (v == null ? '–' : fmtTime(v * 1000)));
  const pct = (vals) => vals.map((v) => (v == null ? '–' : `${Math.round(v)}%`));
  const gather = stats.map((s) => RES.map((r) => sumStat(s, (x) => x.tasks?.[r] ?? 0) ?? 0));
  const rate = of(METRICS.rate.f), collected = of(METRICS.collected.f), bonus = of(METRICS.bonus.f), banked = of(METRICS.banked.f);
  const tcIdle = of((s) => s.tc_idle_seconds);
  const effLm = stats.map((s) => sideEfficiency(s, 'last_minute')), eff = stats.map((s) => sideEfficiency(s, 'all'));
  return [
    { label: 'Gatherers F / W / G / S', values: gather.map((g) => g.reduce((a, b) => a + b, 0)), text: gather.map((g) => g.join('/')) },
    { label: METRICS.rate.label, detail: METRICS.rate.detail, values: rate, text: num(rate), series: 'rate_total' },
    { label: METRICS.collected.label, detail: METRICS.collected.detail, values: collected, text: num(collected), series: 'col_total' },
    { label: METRICS.bonus.label, detail: METRICS.bonus.detail, values: bonus, text: num(bonus, Math.round), series: METRICS.bonus.series },
    { label: METRICS.idle_villagers.label, values: of(METRICS.idle_villagers.f), lower: true, warnWorst: true, series: 'idle' },
    { label: METRICS.tc_idle.label, detail: TC_IDLE_DETAIL, values: tcIdle, text: time(tcIdle), lower: true, warnWorst: true, series: METRICS.tc_idle.series },
    { label: 'Worker efficiency (last minute)', detail: METRICS.efficiency.detail, values: effLm, text: pct(effLm), margin: 3, series: 'efficiency_lm' },
    { label: 'Worker efficiency (whole game)', detail: METRICS.efficiency.detail, values: eff, text: pct(eff), margin: 3, series: METRICS.efficiency.series },
    { label: METRICS.banked.label, detail: METRICS.banked.detail, values: banked, text: num(banked, Math.floor), lower: true },
  ];
}

// The fight picked in the Fight card ({ from, events }), or null to follow the latest. It
// lasts until a seek goes back before the fight began (or another recording opens).
let pinned = null;

/** The Fight card's dropdown entry for a fight: "12:34–13:10 · 23 kills · 4120 res". */
export function fightLabel(f) {
  return `${fmtTime(f.from)}–${fmtTime(f.to)} · ${t('{n} kills', { n: f.kills })} · ${fmtNum(f.value)} ${t('res')}`;
}

function fightHtml() {
  const list = fightsUpTo(S.events, fightsOf(S.events), S.t);
  if (pinned && (pinned.events !== S.events || !list.some((x) => x.from === pinned.from))) pinned = null;
  if (!list.length) return `<p class="hint fs-empty">${t('No fight yet')}</p>`;
  const f = pinned ? list.find((x) => x.from === pinned.from) : list[0];
  // Keyed options: a new fight is inserted, the open list is not rebuilt on every tick.
  const options = [`<option value="latest" data-ui-key="latest"${pinned ? '' : ' selected'}>${esc(t('Latest'))}</option>`]
    .concat(list.map((x) => `<option value="${x.from}" data-ui-key="fight-${x.from}"${pinned && x === f ? ' selected' : ''}>${esc(fightLabel(x))}</option>`)).join('');
  const pick = `<select id="fs-fight-pick" class="fs-fight-pick" data-fight-pick aria-label="${esc(t('Fight to recap'))}">${options}</select>`;
  const rows = Object.entries(f.lost).sort((a, b) => b[1].value - a[1].value).map(([pid, lost]) => {
    const units = Object.entries(lost.masters).sort((a, b) => b[1] - a[1]).slice(0, 6)
      .map(([mid, n]) => `<span class="icon-count" title="${esc(unitInfo(+mid, +pid).name)}"><img src="${unitIcon(+mid, +pid)}" alt="${esc(unitInfo(+mid, +pid).name)}"><b>${n}</b></span>`).join('');
    return `<div class="fs-fight-row" data-ui-key="lost-${pid}"><i style="background:${playerMarkColor(+pid)}"></i><span class="fs-who" style="color:${playerTextColor(+pid)}">${esc(playerName(+pid))}</span>
      <span class="fs-lost">${t('lost {n}', { n: lost.n })} · <b>${fmtNum(lost.value)}</b> ${t('res')}</span><span class="fs-units">${units}</span></div>`;
  }).join('');
  return `${pick}<button type="button" class="fs-fight-when" data-fight-t="${f.from}" data-x="${f.x}" data-y="${f.y}" aria-label="${esc(t('Jump to the fight at {time}', { time: fmtTime(f.from) }))}">${fmtTime(f.from)}–${fmtTime(f.to)} · ${t('{n} kills', { n: f.kills })} ▸</button>${rows}`;
}

function renderFocus(el, ctx) {
  HUD_PARTS.delegate(el, 'click', '[data-focus]', (d) => { setHud({ ...hud(), focus: d.dataset.focus }); ctx.onChange(); });
  HUD_PARTS.delegate(el, 'click', '.icon-count[data-line], .icon-count[data-where]', HUD_PARTS.productionClick);
  HUD_PARTS.delegate(el, 'click', '[data-series]', (d) => window.dispatchEvent(new CustomEvent('vantage-investigate', { detail: { pid: +d.dataset.pid, metric: d.dataset.series } })));
  HUD_PARTS.delegate(el, 'change', '[data-fight-pick]', (d) => { pinned = d.value === 'latest' ? null : { from: +d.value, events: S.events }; ctx.onChange(); });
  HUD_PARTS.delegate(el, 'click', '[data-fight-t]', (d) => { ctx.seek(+d.dataset.fightT - 3000); centerOn(+d.dataset.x, +d.dataset.y); ctx.onChange(); });
  const card = hud().focus;
  const tabs = `<span class="fs-tabs" role="group" aria-label="${esc(t('Focus slot card'))}">${CARDS.map(([id, short, name]) => `<button type="button" data-focus="${id}" aria-pressed="${card === id}" aria-label="${esc(t(name))}">${esc(t(short))}</button>`).join('')}<button type="button" data-focus="none" aria-pressed="${card === 'none'}" aria-label="${esc(t('Empty the Focus slot'))}">–</button></span>`;
  const info = CARDS.find(([id]) => id === card);
  let body = '';
  if (S.view && info) {
    if (card === 'production') body = `<div class="fs-prod">${HUD_PARTS.productionRowsHtml()}</div>`;
    else if (card === 'eco') body = compareTableHtml(sides(), ecoRows(sides()));
    else if (card === 'fight') body = `<div class="fs-fight">${fightHtml()}</div>`;
  }
  el.classList.toggle('empty', !info);
  HUD_PARTS.setHtml(el, `<div class="fs-head"><span class="fs-title">${info ? esc(t(info[2])) : esc(t('Focus slot'))}</span>${tabs}</div>${info ? `<div class="fs-body">${body}</div>` : ''}`);
  // The selected option follows the pin even after the viewer's own pick made the list "dirty"
  // (a changed selected attribute no longer moves the selection then).
  const pick = card === 'fight' && el.querySelector('#fs-fight-pick');
  const want = pinned ? String(pinned.from) : 'latest';
  if (pick && pick.value !== want) pick.value = want;
}

// -- Event ticker --------------------------------------------------------------------------------

function renderTicker(el, ctx) {
  HUD_PARTS.delegate(el, 'click', '[data-t]', (d) => {
    ctx.seek(+d.dataset.t);
    if (d.dataset.x) centerOn(+d.dataset.x, +d.dataset.y);
    ctx.onChange();
  });
  // About 8 real seconds at the speed being watched.
  const speed = Math.max(1, Math.abs(SPEEDS[S.speedIndex] || 1)) * ((S.match && S.match.speed) || 1.7);
  const rows = tickerEvents(S.events, S.t, 8000 * speed);
  el.classList.toggle('empty', !rows.length);
  HUD_PARTS.setHtml(el, `<ol>${rows.map(({ e, age }) => {
    // Fades over the last quarter of its time, in a few steps (not a write per frame).
    const opacity = age < 0.75 ? 1 : Math.max(0.2, Math.round((1 - (age - 0.75) / 0.25) * 5) / 5);
    return `<li data-ui-key="${e.t}-${e.kind}-${e.player}" style="opacity:${opacity}"><button type="button" data-t="${e.t}" ${Number.isFinite(e.x) ? `data-x="${e.x}" data-y="${e.y}"` : ''} aria-label="${esc(t('Jump to {time}', { time: fmtTime(e.t) }))}">${fmtTime(e.t)}</button><i style="background:${playerMarkColor(e.player)}"></i><span>${HUD_PARTS.eventText(e)}</span></li>`;
  }).join('')}</ol>`);
}

// -- Selection chip ------------------------------------------------------------------------------

function renderChip(el, ctx) {
  HUD_PARTS.delegate(el, 'click', '[data-chip]', () => { expandSelection(true); ctx.onChange(); });
  HUD_PARTS.delegate(el, 'click', '[data-chip-back]', () => { expandSelection(false); ctx.onChange(); });
  const rows = S.view ? selectedRows() : [];
  // The full panel replaces the chip once it is open (or when the preset shows it anyway).
  if (!rows.length) { el.classList.add('empty'); el.classList.remove('back'); HUD_PARTS.setHtml(el, ''); return; }
  // Opened into the full panel from the chip: the chip becomes the way back, just above the panel.
  if (selectionExpanded()) {
    const up = document.getElementById('unitpanel'), r = up && up.getClientRects().length ? up.getBoundingClientRect() : null;
    el.classList.remove('empty'); el.classList.add('back');
    if (r && !el.classList.contains('hud-custom-size')) { el.style.bottom = `${Math.round(window.innerHeight - r.top + 6)}px`; el.style.right = `${Math.round(window.innerWidth - r.right)}px`; }
    HUD_PARTS.setHtml(el, `<button type="button" data-chip-back aria-label="${esc(t('Back to the one-line selection chip'))}">▾ ${esc(t('compact'))}</button>`);
    return;
  }
  el.classList.remove('back'); el.style.bottom = ''; el.style.right = '';
  if (isVisible('unitpanel')) { el.classList.add('empty'); HUD_PARTS.setHtml(el, ''); return; }
  el.classList.remove('empty');
  const r = rows[0], info = unitInfo(r[2], r[1], r[0]);
  const owners = [...new Set(rows.map((x) => x[1]))];
  const name = rows.length === 1 ? info.name : t('{n} selected', { n: rows.length });
  const owner = owners.length === 1 && owners[0] > 0 ? `<span class="sc-owner" style="color:${playerTextColor(owners[0])}">${esc(playerName(owners[0]))}</span>` : '';
  const hp = rows.length === 1 && r[1] > 0 && typeof r[5] === 'number' ? `<span class="sc-hp"><i style="width:${Math.round(Math.max(0, Math.min(1, r[5])) * 100)}%"></i></span>` : '';
  const s = owners.length === 1 ? playerStats(owners[0]) : null;
  const idle = rows.length === 1 && s && (r[6] & 8) ? `<span class="sc-idle">${t('idle')}</span>` : '';
  HUD_PARTS.setHtml(el, `<button type="button" data-chip aria-label="${esc(`${name}${owners.length === 1 && owners[0] > 0 ? `, ${playerName(owners[0], true)}` : ''}. ${t('Open the Selection panel')}`)}">
    <img src="${unitIcon(r[2], r[1], r[0])}" alt=""><b>${esc(name)}</b>${owner}${hp}${idle}<span class="sc-more">${t('details')} ▸</span></button>`);
}

function make(id, tag, label, live = false) {
  return () => {
    const el = document.createElement(tag);
    el.id = id; el.className = 'panel';
    el.setAttribute('role', live ? 'log' : 'region'); el.setAttribute('aria-label', t(label));
    document.getElementById('hud').appendChild(el);
    return el;
  };
}

export const PANEL_RENDERERS = {
  focus: { create: make('focus', 'section', 'Focus slot'), render: renderFocus },
  ticker: { create: make('ticker', 'section', 'Key events', true), render: renderTicker },
  selchip: { create: make('selchip', 'section', 'Selection'), render: renderChip },
};
