// The Pulse strip: one row per side with the numbers a caster reads every ten
// seconds: name, age, villagers, military, army value, idle, population, and
// the bank with its per-minute rate beside it. A delta is printed on the
// leading side only, with an arrow as well as the leader's colour. Which
// metrics show is the viewer's choice (Customize → Pulse strip metrics).
//
// Every value is a button with a spoken label ("Army value 1360, ahead by
// 50"); pressing it opens Statistics on that series. The strip is not a live
// region: it changes four times a second.

import { S, settings, SPEEDS, fmtTime, fmtNum, fmtStock, esc, playerStats, playerMarkColor, playerTextColor, playerName, teamName, plainTeamName, isTwoTeamLayout, sideTeams, RES } from './state.js';
import { t } from './i18n.js';
import { HUD_PARTS } from './panels.js';
import { METRICS, KILLS_LOSSES } from './metrics.js';
import { sumStat, compare } from './team-board.js';
import { pulseMetrics } from './layout.js';
import { cellModel } from './pulse-model.js';

const RES_LABEL = { food: 'Food', wood: 'Wood', gold: 'Gold', stone: 'Stone' };
const PHONE = ['age', 'vil', 'mil', 'army', 'idle'];

const eapmOf = (pid) => { const a = S.view && S.view.apm && S.view.apm[pid]; return a && typeof a.effective === 'number' ? a.effective : null; };

/** The sides of the strip: two teams (left and right), or one row per player in a free-for-all. */
export function pulseSides() {
  const teams = HUD_PARTS.orderedTeams();
  if (isTwoTeamLayout() && teams.length === 2) return { two: true, sides: sideTeams() };
  return { two: false, sides: teams.flatMap((tm) => tm.players.map((p) => ({ key: `p${p.id}`, players: [p], solo: true }))) };
}

function label(team) { return team.solo || team.players.length === 1 ? playerName(team.players[0].id) : teamName(team); }

function cellHtml(c, pid, color, right) {
  const delta = c.delta ? `<em style="color:${color}" aria-hidden="true">${right ? '' : '▲'}${c.delta}${right ? '▲' : ''}</em>` : '';
  const cap = c.cap != null ? `<small>/${c.cap}</small>` : '';
  return `<button type="button" class="pm${c.warn ? ' warn' : ''}${c.housed ? ' housed' : ''}" data-ui-key="${c.id}" data-series="${c.series || ''}" data-pid="${pid}" aria-label="${esc(c.spoken)}"><span class="pm-l">${esc(t(c.short))}</span><b class="pm-v">${c.shown}${cap}</b>${delta}</button>`;
}

function bankHtml(stats, pid, showBank, showRate) {
  return RES.map((r) => {
    const bank = sumStat(stats, (s) => s.resources?.[r]), rate = sumStat(stats, (s) => s.collected_rate?.[r]);
    if (bank == null && rate == null) return '';
    const spoken = `${t(RES_LABEL[r])}${showBank && bank != null ? ` ${fmtStock(bank)} ${t('banked')}` : ''}${showRate && rate != null ? `, ${t('{n} per minute', { n: fmtNum(rate) })}` : ''}`;
    return `<button type="button" class="pm res ${r}" data-ui-key="res-${r}" data-series="${showBank ? `res_${r}` : `rate_${r}`}" data-pid="${pid}" aria-label="${esc(spoken)}"><img src="/ui/resource_${r}.png" alt="">${showBank && bank != null ? `<b class="pm-v">${fmtStock(bank)}</b>` : ''}${showRate && rate != null ? `<small class="pm-rate">+${fmtNum(rate)}<span class="pm-unit">/${t('min')}</span></small>` : ''}</button>`;
  }).join('');
}

function sideHtml(team, other, metrics, right) {
  const stats = team.players.map((p) => playerStats(p.id)).filter(Boolean);
  if (!stats.length) return '';
  const otherStats = other ? other.players.map((p) => playerStats(p.id)).filter(Boolean) : null;
  const lead = team.players[0].id, color = playerTextColor(lead), n = team.players.length;
  const has = (id) => metrics.includes(id);
  const ages = has('age') ? `<span class="pl-age">${team.players.map((p) => { const s = playerStats(p.id); return s ? HUD_PARTS.ageShield(s, p.id) : ''; }).join('')}</span>` : '';
  const cells = [];
  for (const id of ['vil', 'mil', 'army', 'idle', 'pop', 'banksum', 'ratesum', 'score']) {
    if (!has(id) || (id === 'score' && settings.hideScore)) continue;
    const c = cellModel(id, stats, otherStats, n);
    if (c) cells.push(cellHtml(c, lead, color, right));
  }
  if (has('kd')) {
    const k = sumStat(stats, METRICS.kills.f), l = sumStat(stats, METRICS.losses.f);
    if (k != null || l != null) cells.push(`<button type="button" class="pm" data-ui-key="kd" data-series="kills" data-pid="${lead}" aria-label="${esc(`${t('Kills')} ${k ?? 0}, ${t('Losses')} ${l ?? 0}`)}"><span class="pm-l">${esc(t(KILLS_LOSSES.short))}</span><b class="pm-v">${k ?? 0}/${l ?? 0}</b></button>`);
  }
  if (has('eapm')) {
    const vals = team.players.map((p) => eapmOf(p.id)).filter((v) => v != null);
    if (vals.length) {
      const v = Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
      cells.push(`<button type="button" class="pm" data-ui-key="eapm" data-series="apm" data-pid="${lead}" aria-label="${esc(`${t('eAPM')} ${v}`)}"><span class="pm-l">eAPM</span><b class="pm-v">${v}</b></button>`);
    }
  }
  const bank = has('bank') || has('rate') ? `<span class="pl-bank">${bankHtml(stats, lead, has('bank'), has('rate'))}</span>` : '';
  const dead = team.players.every((p) => HUD_PARTS.isDead(p.id));
  return `<div class="pl-side${right ? ' right' : ''}${dead ? ' dead' : ''}" data-ui-key="side-${esc(String(team.key))}" role="group" aria-label="${esc(team.solo ? playerName(lead, true) : plainTeamName(team))}">
    <span class="pl-id"><i class="pl-color" style="background:${playerMarkColor(lead)}"></i><span class="pl-name" style="color:${color}">${esc(label(team))}</span>${ages}</span>
    <span class="pl-stats">${cells.join('')}</span>${bank}</div>`;
}

function centerHtml() {
  const live = S.session && S.session.mode === 'live' && S.followLive, sp = SPEEDS[S.speedIndex];
  const state = live ? t('LIVE') : `${S.playing ? '' : `${t('paused')} · `}${sp}×`;
  const sr = HUD_PARTS.series();
  const extra = [sr.text, settings.stageName].filter(Boolean).map(esc).join(' · ');
  const spoken = `${fmtTime(S.t)}, ${state}. ${t(S.playing ? 'Press to pause' : 'Press to play')}`;
  return `<button type="button" class="pl-center" data-pulse="pause" aria-label="${esc(spoken)}"><span class="pl-clock">${fmtTime(S.t)}</span><span class="pl-sub">${esc(state)}</span>${extra ? `<span class="pl-series">${extra}</span>` : ''}</button>`;
}

function render(el, ctx) {
  HUD_PARTS.delegate(el, 'click', '[data-series], [data-pulse]', (d) => {
    if (d.dataset.pulse === 'pause') { ctx.actions.pause(); ctx.onChange(); return; }
    if (d.dataset.series) window.dispatchEvent(new CustomEvent('vantage-investigate', { detail: { pid: +d.dataset.pid, metric: d.dataset.series } }));
  });
  if (!S.view) { HUD_PARTS.setHtml(el, ''); return; }
  const phone = document.body.classList.contains('hud-phone');
  const metrics = phone ? pulseMetrics().filter((m) => PHONE.includes(m)) : pulseMetrics();
  const { two, sides } = pulseSides();
  let html;
  if (two) html = `<div class="pulse two">${sideHtml(sides[0], sides[1], metrics, false)}${centerHtml()}${sideHtml(sides[1], sides[0], metrics, true)}</div>`;
  else html = `<div class="pulse multi">${centerHtml()}${sides.map((tm) => sideHtml(tm, null, metrics, false)).join('')}</div>`;
  HUD_PARTS.setHtml(el, html);
}

function create() {
  const el = document.createElement('header');
  el.id = 'pulse'; el.className = 'panel';
  el.setAttribute('role', 'region'); el.setAttribute('aria-label', t('Match pulse'));
  // First in the HUD: it is the first thing a keyboard or screen-reader user reaches.
  document.getElementById('hud').prepend(el);
  return el;
}

export const PANEL_RENDERERS = { pulse: { create, render } };
