// The Match story timeline (#story) and the Review cards (#reviewcards).
//
// Match story: one time axis instead of a chart per tab. The army-value lead
// (above the centre line the left side leads, below it the right side),
// age-ups, fights (bars sized by the resources lost), idle town centres and
// bookmarks, with the playhead and the playback buttons docked into it. Click
// to jump; drag across a span to open Investigate on that interval; arrow keys
// step. It redraws when its data, size or the playhead's pixel changes, never
// per frame.
//
// Review cards: six mistake metrics, side against side, the worse side in
// amber; each opens Statistics on its series.

import { S, SPEEDS, fmtTime, fmtNum, esc, playerMarkColor, playerName, playerStats, isTwoTeamLayout, sideTeams } from './state.js';
import { t } from './i18n.js';
import { HUD_PARTS } from './panels.js';
import { METRICS } from './metrics.js';
import { sumStat } from './team-board.js';
import { fightsOf } from './fights.js';
import { compareTableHtml, sideStats } from './compare-table.js';

function sides() {
  const teams = HUD_PARTS.orderedTeams();
  if (isTwoTeamLayout() && teams.length === 2) return sideTeams();
  return teams.flatMap((tm) => tm.players.map((p) => ({ key: `p${p.id}`, players: [p], solo: true })));
}

// -- series helpers (pure; exported for the tests) ---------------------------------------------------

/** The last row at or before `at` (binary search over time-sorted rows). */
export function rowAt(rows, at) {
  if (!rows || !rows.length) return null;
  let lo = 0, hi = rows.length - 1, hit = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (rows[mid].t <= at) { hit = mid; lo = mid + 1; } else hi = mid - 1; }
  return hit < 0 ? null : rows[hit];
}

/** A side's value of one series key at a time: the sum over its players (null when unknown). */
export function sideValue(series, side, key, at) {
  let total = null;
  for (const p of side.players) {
    const row = rowAt(series && series[p.id], at), v = row ? row[key] : null;
    if (typeof v === 'number') total = (total || 0) + v;
  }
  return total;
}

/** [{ t, d }]: side A's value minus side B's at every sample of A's first player. */
export function leadCurve(series, a, b, key = 'army_value') {
  const base = (series && series[a.players[0].id]) || [];
  const out = [];
  for (const row of base) {
    const va = sideValue(series, a, key, row.t), vb = sideValue(series, b, key, row.t);
    if (va != null && vb != null) out.push({ t: row.t, d: va - vb });
  }
  return out;
}

/** The stretches where a cumulative series (idle TC seconds) grows: [{ from, to }]. */
export function growthSpans(rows, key) {
  const out = [];
  let open = null;
  for (let i = 1; i < (rows || []).length; i++) {
    const grew = typeof rows[i][key] === 'number' && typeof rows[i - 1][key] === 'number' && rows[i][key] > rows[i - 1][key];
    if (grew) { if (!open) open = { from: rows[i - 1].t, to: rows[i].t }; else open.to = rows[i].t; }
    else if (open) { out.push(open); open = null; }
  }
  if (open) out.push(open);
  return out;
}

/** The first age-up event of each age per player: [{ t, player, age }]. */
export function ageMarks(events) {
  const seen = new Set(), out = [];
  for (const e of events || []) {
    if (e.kind !== 'age_up') continue;
    const k = `${e.player}:${e.age}`;
    if (!seen.has(k)) { seen.add(k); out.push({ t: e.t, player: e.player, age: e.age }); }
  }
  return out;
}

// -- Match story ---------------------------------------------------------------------------------------

const ROMAN = ['I', 'II', 'III', 'IV', 'V'];
const state = { size: null, key: '', base: null, baseKey: '', drag: null, hoverX: null, observer: null };

function span() { return Math.max(1, S.end - S.start); }
const xOf = (time, W) => ((time - S.start) / span()) * W;
const tOf = (x, W) => S.start + Math.max(0, Math.min(1, x / W)) * span();

function drawBase(W, H) {
  const dpr = window.devicePixelRatio || 1;
  const c = state.base || (state.base = document.createElement('canvas'));
  c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const list = sides(), two = list.length === 2;
  const top = 14, laneH = H - top - 16, mid = top + laneH / 2;
  // The lane and its centre line.
  g.fillStyle = 'rgba(255,255,255,.05)'; g.fillRect(0, top, W, laneH);
  if (two) {
    const curve = leadCurve(S.series, list[0], list[1]);
    const max = Math.max(1, ...curve.map((p) => Math.abs(p.d)));
    for (const [sign, side] of [[1, list[0]], [-1, list[1]]]) {
      g.fillStyle = playerMarkColor(side.players[0].id); g.globalAlpha = 0.75;
      g.beginPath(); g.moveTo(0, mid);
      // A square-root scale: an early lead of 50 still reads beside a late lead of 2000.
      for (const p of curve) g.lineTo(xOf(p.t, W), mid - Math.sqrt(Math.max(0, sign * p.d) / max) * (laneH / 2 - 1) * sign);
      g.lineTo(curve.length ? xOf(curve[curve.length - 1].t, W) : 0, mid); g.closePath(); g.fill();
    }
    g.globalAlpha = 1;
    // Idle town centres: a thin track per side at the lane's edges.
    for (const [i, side] of list.entries()) {
      g.fillStyle = '#e0a030';
      for (const p of side.players) for (const s of growthSpans(S.series && S.series[p.id], 'tc_idle')) g.fillRect(xOf(s.from, W), i === 0 ? top : top + laneH - 3, Math.max(1.5, xOf(s.to, W) - xOf(s.from, W)), 3);
    }
  } else {
    // A free-for-all: each player's army value as a line.
    let max = 1;
    for (const side of list) for (const row of (S.series && S.series[side.players[0].id]) || []) max = Math.max(max, row.army_value || 0);
    for (const side of list) {
      const rows = (S.series && S.series[side.players[0].id]) || [];
      g.strokeStyle = playerMarkColor(side.players[0].id); g.lineWidth = 1.5; g.beginPath();
      rows.forEach((row, i) => { const x = xOf(row.t, W), y = top + laneH - ((row.army_value || 0) / max) * (laneH - 2) - 1; if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      g.stroke();
    }
  }
  g.fillStyle = 'rgba(255,255,255,.35)'; g.fillRect(0, Math.round(mid), W, 1);
  // Fights: bars sized by the resources lost.
  const fights = fightsOf(S.events), worst = Math.max(1, ...fights.map((f) => f.value));
  g.fillStyle = 'rgba(255,255,255,.85)';
  for (const f of fights) {
    const h = 3 + (f.value / worst) * 11, x = xOf(f.from, W);
    g.fillRect(x, H - h, Math.max(3, xOf(f.to, W) - x), h);
  }
  // Age-ups: a tick and the age's numeral in the player's colour.
  g.font = '700 10px ui-monospace, monospace'; g.textAlign = 'center'; g.textBaseline = 'top';
  for (const m of ageMarks(S.events)) {
    const x = xOf(m.t, W);
    g.fillStyle = playerMarkColor(m.player);
    g.fillRect(x - 1, top - 3, 2, laneH + 3);
    g.fillText(ROMAN[m.age] || String(m.age + 1), Math.max(8, Math.min(W - 8, x)), 1);
  }
  // Bookmarks.
  g.fillStyle = '#6fb3d2';
  for (const b of S.bookmarks) { const x = xOf(b, W); g.beginPath(); g.moveTo(x, top - 2); g.lineTo(x + 6, top + 2); g.lineTo(x, top + 6); g.fill(); g.fillRect(x - 0.5, top - 2, 1, laneH + 2); }
}

function draw(canvas) {
  const r = state.size;
  if (!r || r.width < 2 || r.height < 2) return;
  const dpr = window.devicePixelRatio || 1, W = r.width, H = r.height;
  if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) { canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); state.baseKey = ''; }
  const list = sides();
  const baseKey = [W, H, S.start, S.end, S.series ? Object.values(S.series).reduce((n, rows) => n + rows.length, 0) : 0, S.events.length, S.bookmarks.join(','),
    list.map((s) => playerMarkColor(s.players[0].id)).join(','), S.session && S.session.generation].join('|');
  if (baseKey !== state.baseKey) { state.baseKey = baseKey; drawBase(W, H); }
  const g = canvas.getContext('2d');
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, canvas.width, canvas.height);
  g.drawImage(state.base, 0, 0);
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const px = xOf(S.t, W);
  // What is still to come is dimmed; the playhead is a white line.
  g.fillStyle = 'rgba(8,10,13,.45)'; g.fillRect(px, 14, W - px, H - 30);
  if (state.drag && state.drag.range) {
    const a = Math.min(state.drag.x0, state.drag.x1), b = Math.max(state.drag.x0, state.drag.x1);
    g.fillStyle = 'rgba(217,180,90,.28)'; g.fillRect(a, 12, b - a, H - 26);
    g.strokeStyle = '#d9b45a'; g.lineWidth = 1; g.strokeRect(a + 0.5, 12.5, b - a - 1, H - 27);
  }
  g.fillStyle = '#fff'; g.fillRect(Math.round(px) - 1, 10, 2, H - 12);
}

function leadText() {
  const list = sides();
  if (list.length !== 2 || !S.view) return '';
  const a = sumStat(sideStats(list[0]), METRICS.army_value.f), b = sumStat(sideStats(list[1]), METRICS.army_value.f);
  if (a == null || b == null || a === b) return t('Army value even');
  const lead = a > b ? list[0] : list[1];
  return t('{name} ahead by {n} army value', { name: playerName(lead.players[0].id, true), n: fmtNum(Math.abs(a - b)) });
}

function wireTrack(el, ctx) {
  const track = el.querySelector('.st-track'), canvas = track.querySelector('canvas');
  state.size = canvas.getBoundingClientRect();
  if (state.observer) state.observer.disconnect();
  state.observer = new ResizeObserver(() => {
    state.size = canvas.getBoundingClientRect(); state.key = ''; draw(canvas);
    // Panels that stack above the story (Review cards, Focus slot) read its height.
    const top = el.getBoundingClientRect().top;
    if (top > 0) document.documentElement.style.setProperty('--story-above', `${Math.round(window.innerHeight - top + 6)}px`);
  });
  state.observer.observe(canvas); state.observer.observe(el);
  const local = (e) => e.clientX - track.getBoundingClientRect().left;
  track.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    track.setPointerCapture(e.pointerId);
    // Touch scrubs; a mouse drag marks an interval to investigate.
    state.drag = { x0: local(e), x1: local(e), range: false, touch: e.pointerType === 'touch' };
    S.scrubbing = true;
    if (state.drag.touch) ctx.seek(tOf(local(e), state.size.width));
    e.preventDefault(); track.focus({ preventScroll: true });
  });
  track.addEventListener('pointermove', (e) => {
    if (!state.drag) return;
    state.drag.x1 = local(e);
    if (state.drag.touch) ctx.seek(tOf(state.drag.x1, state.size.width));
    else if (Math.abs(state.drag.x1 - state.drag.x0) > 8) state.drag.range = true;
    draw(canvas);
  });
  const end = (e, cancel) => {
    const d = state.drag;
    if (!d) return;
    state.drag = null; S.scrubbing = false;
    const W = state.size.width;
    if (!cancel && d.range) {
      const from = Math.round(tOf(Math.min(d.x0, d.x1), W)), to = Math.round(tOf(Math.max(d.x0, d.x1), W));
      S.reviewRange = { from, to }; S.reviewScope = 'fight';
      window.dispatchEvent(new CustomEvent('vantage-investigate', { detail: { pid: sides()[0]?.players[0].id, metric: 'army_value' } }));
    } else if (!cancel && !d.touch) ctx.seek(tOf(d.x1, W));
    draw(canvas); ctx.onChange();
  };
  track.addEventListener('pointerup', (e) => end(e, false));
  track.addEventListener('pointercancel', (e) => end(e, true));
  track.addEventListener('keydown', (e) => {
    const step = { ArrowLeft: -5000, ArrowRight: 5000, PageDown: -30000, PageUp: 30000 }[e.key];
    if (e.key === 'Escape' && state.drag) { end(e, true); e.stopPropagation(); return; }
    if (step == null && e.key !== 'Home' && e.key !== 'End') return;
    e.preventDefault(); e.stopPropagation();
    ctx.seek(e.key === 'Home' ? S.start : e.key === 'End' ? S.end : Math.max(S.start, Math.min(S.end, S.t + step)));
    ctx.onChange();
  });
  el.addEventListener('click', (e) => {
    const b = e.target.closest('[data-st]');
    if (!b) return;
    const a = ctx.actions, act = b.dataset.st;
    if (act === 'back') a.skipBack(); else if (act === 'fwd') a.skipForward(); else if (act === 'play') a.pause();
    else if (act === 'slower') a.speedStepDown(); else if (act === 'faster') a.speedStepUp(); else if (act === 'mark') a.bookmark();
    ctx.onChange();
  });
}

function renderStory(el, ctx) {
  if (!el._wired) {
    el._wired = true;
    el.innerHTML = `<div class="st-bar">
        <button type="button" data-st="back" aria-label="${esc(t('Skip back 30s'))}">↺30</button>
        <button type="button" data-st="play" class="st-play"></button>
        <button type="button" data-st="fwd" aria-label="${esc(t('Skip forward 30s'))}">↻30</button>
        <button type="button" data-st="slower" aria-label="${esc(t('Slower'))}">−</button><span class="st-speed" aria-live="off"></span><button type="button" data-st="faster" aria-label="${esc(t('Faster'))}">+</button>
        <button type="button" data-st="mark" aria-label="${esc(t('Bookmark 30s ago'))}">⚑</button>
        <span class="st-clock"></span><span class="st-lead"></span>
        <span class="st-legend" aria-hidden="true"><i class="lg-lead"></i>${esc(t('army lead'))}<i class="lg-fight"></i>${esc(t('fights'))}<i class="lg-idle"></i>${esc(t('idle TC'))}<i class="lg-mark"></i>${esc(t('bookmarks'))}</span>
      </div>
      <div class="st-track" role="slider" tabindex="0" aria-label="${esc(t('Match time'))}" aria-orientation="horizontal"><canvas></canvas></div>`;
    wireTrack(el, ctx);
  }
  const sp = SPEEDS[S.speedIndex], live = S.session && S.session.mode === 'live' && S.followLive;
  const play = el.querySelector('.st-play');
  HUD_PARTS.setText(play, S.playing ? '❚❚' : '▶');
  play.setAttribute('aria-label', t(S.playing ? 'Pause' : 'Play'));
  HUD_PARTS.setText(el.querySelector('.st-speed'), live ? t('LIVE') : `${sp}×`);
  HUD_PARTS.setText(el.querySelector('.st-clock'), `${fmtTime(S.t)} / ${fmtTime(S.end)}`);
  const lead = leadText();
  HUD_PARTS.setText(el.querySelector('.st-lead'), lead);
  const track = el.querySelector('.st-track');
  // Spoken on focus and on a step, not on every tick: whole seconds only.
  const now = String(Math.round(S.t / 1000));
  if (track.getAttribute('aria-valuenow') !== now) {
    track.setAttribute('aria-valuemin', String(Math.round(S.start / 1000))); track.setAttribute('aria-valuemax', String(Math.round(S.end / 1000)));
    track.setAttribute('aria-valuenow', now);
    track.setAttribute('aria-valuetext', `${fmtTime(S.t)} ${t('of')} ${fmtTime(S.end)}${lead ? `. ${lead}` : ''}`);
  }
  const W = state.size ? state.size.width : 0;
  const key = `${Math.round(xOf(S.t, W))}|${S.events.length}|${S.bookmarks.length}|${S.end}|${S.series ? Object.keys(S.series).length : 0}|${S.seriesAt}`;
  if (key !== state.key || state.drag) { state.key = key; draw(track.querySelector('canvas')); }
}

// -- Review cards ----------------------------------------------------------------------------------------

export function reviewRows(list, series, at, view) {
  const stats = list.map(sideStats);
  const ser = (key) => list.map((s) => sideValue(series, s, key, at));
  const time = (vals) => vals.map((v) => (v == null ? '–' : fmtTime(v * 1000)));
  const avg = (f) => stats.map((s) => { const vs = s.map(f).filter((v) => typeof v === 'number'); return vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null; });
  const idleTc = ser('tc_idle'), housed = ser('housed');
  const eff = avg((s) => s.efficiency && s.efficiency.pct);
  const eapm = list.map((s) => { const vs = s.players.map((p) => view && view.apm && view.apm[p.id] && view.apm[p.id].effective).filter((v) => typeof v === 'number'); return vs.length ? Math.round(vs.reduce((a, b) => a + b, 0) / vs.length) : null; });
  const bank = stats.map((s) => sumStat(s, METRICS.banked.f));
  const idle = stats.map((s) => sumStat(s, METRICS.idle_villagers.f));
  return [
    { label: METRICS.tc_idle.label, values: idleTc, text: time(idleTc), lower: true, warnWorst: true, series: 'tc_idle', detail: 'Town centre time without a villager in production, while still growing' },
    { label: METRICS.housed.label, values: housed, text: time(housed), lower: true, warnWorst: true, series: 'housed' },
    { label: 'Idle villagers now', values: idle, lower: true, warnWorst: true, series: 'idle' },
    { label: METRICS.efficiency.label, values: eff, text: eff.map((v) => (v == null ? '–' : `${Math.round(v)}%`)), warnWorst: true, series: 'efficiency_lm', detail: METRICS.efficiency.detail },
    { label: 'Banked, unspent', values: bank, text: bank.map((v) => (v == null ? '–' : fmtNum(Math.floor(v)))), lower: true, warnWorst: true, series: 'res_food', detail: METRICS.banked.detail },
    { label: METRICS.eapm.label, values: eapm, warnWorst: true, series: 'apm', detail: METRICS.eapm.detail },
  ];
}

function renderCards(el) {
  HUD_PARTS.delegate(el, 'click', '[data-series]', (d) => window.dispatchEvent(new CustomEvent('vantage-investigate', { detail: { pid: +d.dataset.pid, metric: d.dataset.series } })));
  if (!S.view) { HUD_PARTS.setHtml(el, ''); return; }
  const list = sides().slice(0, 4);
  HUD_PARTS.setHtml(el, `<div class="rc-head"><span class="rc-title">${esc(t('Review cards'))}</span><span class="hint">${esc(t('worse side in amber'))}</span></div>${compareTableHtml(list, reviewRows(list, S.series, S.t, S.view))}`);
}

function make(id, label) {
  return () => {
    const el = document.createElement('section');
    el.id = id; el.className = 'panel';
    el.setAttribute('role', 'region'); el.setAttribute('aria-label', t(label));
    document.getElementById('hud').appendChild(el);
    return el;
  };
}

export const PANEL_RENDERERS = {
  story: { create: make('story', 'Match story timeline'), render: renderStory },
  reviewcards: { create: make('reviewcards', 'Review cards'), render: renderCards },
};
