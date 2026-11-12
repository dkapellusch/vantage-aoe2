// Team board: the team panel (#overview) in two-team games.
//
// Teams view: one row per stat, team A's value and bar on the left, team B's on
// the right, the difference in the leader's colour between them. Players view:
// a compact table grouped by team, with team totals and each column's best
// value marked. Sections fold to their heading (settings.teamBoardCollapsed).
// Fields a recording lacks (older builds) leave their rows out.

import { settings, saveSettings, esc, tip, fmtNum, fmtStock, playerStats, playerMarkColor, playerTextColor, teamName, plainTeamName, teamMemberLabel, RES } from './state.js';
import { t } from './i18n.js';
import { METRICS } from './metrics.js';

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const RES_LABEL = { food: 'Food', wood: 'Wood', gold: 'Gold', stone: 'Stone' };

/** Compare two team values; `lower` when fewer is better. Bars are relative to the larger. */
export function compare(a, b, lower = false) {
  const max = Math.max(Math.abs(a), Math.abs(b)) || 1;
  const d = a - b;
  const lead = d === 0 ? null : (lower ? d < 0 : d > 0) ? 'a' : 'b';
  return { diff: Math.abs(d), lead, aPct: (100 * Math.max(0, a)) / max, bPct: (100 * Math.max(0, b)) / max };
}

/** Sum a stat over players; null when no player has it (the row is left out). */
export function sumStat(stats, f) {
  let total = null;
  for (const s of stats) {
    const v = s ? num(f(s)) : null;
    if (v != null) total = (total || 0) + v;
  }
  return total;
}

// A Team board row for a registered metric (metrics.js): its name, value and direction.
const row = (id, extra = {}) => { const m = METRICS[id]; return { id, label: m.label, f: m.f, ...(m.lower ? { lower: true } : {}), ...(m.warnEach ? { warnEach: m.warnEach } : {}), ...(m.cap ? { cap: m.cap } : {}), ...(m.detail ? { detail: m.detail } : {}), ...extra }; };

export const SECTIONS = [
  { key: 'army', rows: [
    row('villagers'), row('military'), row('army_value'), row('idle_villagers'),
  ] },
  { key: 'banked', title: 'Banked · gatherers', rows: RES.map((r) => ({ label: RES_LABEL[r], res: r, f: (s) => s.resources?.[r], sub: (s) => s.tasks?.[r] ?? 0, stock: true, detail: 'banked / workers' })) },
  { key: 'rate', title: 'Collection rate · last minute', rows: [
    row('rate', { label: 'Total /min', strong: true }),
    ...RES.map((r) => ({ label: `${RES_LABEL[r]} /min`, res: r, f: (s) => s.collected_rate?.[r] })),
  ] },
  { key: 'collected', title: 'Collected · whole game', rows: [
    row('collected', { label: 'Total collected', strong: true }),
    ...RES.map((r) => ({ label: RES_LABEL[r], res: r, f: (s) => s.collected?.[r] })),
  ] },
  { key: 'fights', title: 'Population · fights', rows: [
    row('population'), row('kills'), row('losses'),
  ] },
];

export function teamBoardView() { return settings.teamBoardView === 'players' ? 'players' : 'teams'; }
export function toggleTeamBoardView(view) {
  settings.teamBoardView = view || (teamBoardView() === 'players' ? 'teams' : 'players');
  saveSettings();
}
function toggleSection(key) {
  const list = Array.isArray(settings.teamBoardCollapsed) ? settings.teamBoardCollapsed : [];
  settings.teamBoardCollapsed = list.includes(key) ? list.filter((k) => k !== key) : [...list, key];
  saveSettings();
}
const folded = (key) => Array.isArray(settings.teamBoardCollapsed) && settings.teamBoardCollapsed.includes(key);

function head(a, b) {
  const side = (team, right) => {
    const c = playerMarkColor(team.players[0].id);
    return `<span class="tb-team${right ? ' right' : ''}" data-details="1" ${tip(plainTeamName(team), t('Click: switch Teams / Players (Ctrl+Alt+R)'))}><i style="background:${c}"></i><span>${esc(teamName(team))}</span></span>`;
  };
  const view = teamBoardView();
  const seg = `<span class="tb-seg" role="group" aria-label="${esc(t('Team board view'))}">${['teams', 'players'].map((v) => `<button type="button" data-view="${v}" aria-pressed="${view === v}">${esc(t(v === 'teams' ? 'Teams' : 'Players'))}</button>`).join('')}</span>`;
  return `<div class="tb-head">${side(a, false)}${seg}${side(b, true)}</div>`;
}

function sectionHead(sec) {
  const off = folded(sec.key);
  return `<div class="tb-sec${off ? ' off' : ''}" data-sec="${sec.key}" ${tip(t(sec.title), off ? t('Click: show') : t('Click: fold'))}>${off ? '▸' : '▾'} ${esc(t(sec.title))}</div>`;
}

function statRow(row, a, b, sa, sb) {
  const va = sumStat(sa, row.f), vb = sumStat(sb, row.f);
  if (va == null && vb == null) return '';
  const c = compare(va || 0, vb || 0, row.lower);
  const ca = playerMarkColor(a.players[0].id), cb = playerMarkColor(b.players[0].id);
  const lc = c.lead === 'a' ? playerTextColor(a.players[0].id) : playerTextColor(b.players[0].id);
  const fmt = row.stock ? fmtStock : fmtNum;
  const delta = c.lead == null ? `<em class="even">${esc(t('even'))}</em>` : `<em style="color:${lc}">${c.lead === 'a' ? '<b class="arr">◀</b>' : ''}${fmt(c.diff)}${c.lead === 'b' ? '<b class="arr">▶</b>' : ''}</em>`;
  const val = (v, stats, team, side) => {
    const warn = row.warnEach && v != null && v > row.warnEach * team.players.length;
    const sub = row.sub ? `<small>${sumStat(stats, row.sub) ?? 0}</small>` : '';
    const cap = row.cap ? `<small>/${sumStat(stats, row.cap) ?? '–'}</small>` : '';
    const housed = row.cap && stats.some((s) => s && s.housed_ms > 0) ? `<small class="housed" ${tip(t('Housed'))}>⌂</small>` : '';
    const body = side === 'a' ? `${sub}${housed}${fmt(v)}${cap}` : `${fmt(v)}${cap}${housed}${sub}`;
    return `<span class="tb-v ${side}${c.lead === side ? ' lead' : ''}${warn ? ' warn' : ''}">${body}</span>`;
  };
  const ico = row.res ? `<img src="/ui/resource_${row.res}.png" alt="">` : '';
  return `<div class="tb-row${row.strong ? ' strong' : ''}" ${row.detail ? tip(t(row.label), t(row.detail)) : ''}>
    ${val(va, sa, a, 'a')}<span class="tb-bar a"><i class="${c.lead === 'a' ? 'lead' : ''}" style="transform:scaleX(${(c.aPct / 100).toFixed(4)});background:${ca}"></i></span>
    <span class="tb-lab">${ico}${esc(t(row.label))}${delta}</span>
    <span class="tb-bar b"><i class="${c.lead === 'b' ? 'lead' : ''}" style="transform:scaleX(${(c.bPct / 100).toFixed(4)});background:${cb}"></i></span>${val(vb, sb, b, 'b')}</div>`;
}

function teamsView(a, b, ctx) {
  const sa = a.players.map((p) => playerStats(p.id)), sb = b.players.map((p) => playerStats(p.id));
  const ages = (team) => team.players.map((p) => { const s = playerStats(p.id); return s ? ctx.ageShield(s, p.id) : ''; }).join('');
  let html = `<div class="tb-row tb-ages"><span class="tb-side a">${ages(a)}</span><span class="tb-lab">${esc(t('Age'))}</span><span class="tb-side b">${ages(b)}</span></div>`;
  for (const sec of SECTIONS) {
    // Rows ticked off in Customize (settings.hud.hiddenRows) are left out.
    const off = (settings.hud && settings.hud.hiddenRows) || [];
    const rows = sec.rows.filter((r) => !r.id || !off.includes(r.id)).map((r) => statRow(r, a, b, sa, sb)).filter(Boolean);
    if (!rows.length) continue;
    if (sec.title) html += sectionHead(sec);
    if (!sec.title || !folded(sec.key)) html += rows.join('');
  }
  return html;
}

const PLAYER_COLS = [
  { h: METRICS.villagers.short, f: METRICS.villagers.f, detail: METRICS.villagers.label },
  { h: METRICS.military.short, f: METRICS.military.f, detail: METRICS.military.label },
  { h: METRICS.idle_villagers.short, f: METRICS.idle_villagers.f, lower: true, warn: 5, detail: METRICS.idle_villagers.label },
  ...RES.map((r) => ({ res: r, f: (s) => s.resources?.[r], sub: (s) => s.tasks?.[r] ?? 0, stock: true, detail: `${RES_LABEL[r]}: banked (workers)` })),
  { h: METRICS.population.short, f: METRICS.population.f, cap: METRICS.population.cap, detail: 'Population / cap' },
  { h: '/min', f: (s) => s.collected_rate?.total, detail: 'Resources collected per minute, last minute' },
  { h: METRICS.collected.short, f: METRICS.collected.f, detail: 'Resources collected, whole game' },
];

function playersView(sides, ctx) {
  const all = sides.flatMap((tm) => tm.players.map((p) => playerStats(p.id))).filter(Boolean);
  const cols = PLAYER_COLS.filter((c) => all.some((s) => num(c.f(s)) != null));
  const best = cols.map((c) => { const vs = all.map((s) => num(c.f(s))).filter((v) => v != null); return vs.length > 1 ? (c.lower ? Math.min : Math.max)(...vs) : null; });
  const th = cols.map((c) => `<th ${tip(t(c.detail))}>${c.res ? `<img src="/ui/resource_${c.res}.png" alt="${esc(t(c.res))}">` : esc(t(c.h))}</th>`).join('');
  const cell = (c, i, s) => {
    const v = num(c.f(s));
    const cls = c.warn && v != null && v >= c.warn ? 'warn' : best[i] != null && v === best[i] ? 'best' : '';
    const sub = c.sub ? ` ${tip(t(c.detail), t('{w} workers', { w: c.sub(s) }))}` : '';
    return `<td class="${cls}"${sub}>${v == null ? '–' : (c.stock ? fmtStock : fmtNum)(v)}${c.cap ? `<small>/${c.cap(s) ?? '–'}</small>` : ''}</td>`;
  };
  let rows = '';
  for (const team of sides) {
    const color = playerMarkColor(team.players[0].id);
    rows += `<tr class="tb-tm"><td colspan="${cols.length + 2}"><i style="background:${color}"></i>${esc(teamName(team))}</td></tr>`;
    for (const p of team.players) {
      const s = playerStats(p.id);
      if (!s) continue;
      rows += `<tr class="tb-pl${ctx.isDead(p.id) ? ' dead' : ''}" data-pid="${p.id}"><td class="who"><i style="background:${playerMarkColor(p.id)}"></i><span ${tip(ctx.fullName(p))}>${esc(teamMemberLabel(p.id))}</span></td><td class="age">${ctx.ageShield(s, p.id)}</td>${cols.map((c, i) => cell(c, i, s)).join('')}</tr>`;
      const req = ctx.ageRequirements(s, p.id);
      if (req) rows += `<tr class="tb-req"><td></td><td colspan="${cols.length + 1}">${req}</td></tr>`;
    }
    if (team.players.length > 1) {
      const stats = team.players.map((p) => playerStats(p.id));
      rows += `<tr class="tb-sum"><td class="who">Σ</td><td></td>${cols.map((c) => { const v = sumStat(stats, c.f); return `<td>${v == null ? '–' : (c.stock ? fmtStock : fmtNum)(v)}</td>`; }).join('')}</tr>`;
    }
  }
  return `<table class="tb-players"><thead><tr><th class="who">${esc(t('Player'))}</th><th>${esc(t('Age'))}</th>${th}</tr></thead><tbody>${rows}</tbody></table>`;
}

/**
 * Render the board into el. ctx supplies panels.js helpers: setHtml, delegate,
 * ageShield(s, pid), ageRequirements(s, pid), isDead(pid), fullName(player),
 * onAge(pid) (click on an age shield) and rerender().
 */
export function renderTeamBoard(el, [a, b], ctx) {
  ctx.delegate(el, 'click', '[data-view], [data-sec], [data-details], .ov-age', (d) => {
    if (!el.classList.contains('team-board-host')) return; // a free-for-all game since: its own handler
    if (d.dataset.view) toggleTeamBoardView(d.dataset.view);
    else if (d.dataset.sec) toggleSection(d.dataset.sec);
    else if (d.dataset.details) toggleTeamBoardView();
    else if (d.dataset.pid) { ctx.onAge(+d.dataset.pid); return; }
    ctx.rerender();
  });
  const body = teamBoardView() === 'players' ? playersView([a, b], ctx) : teamsView(a, b, ctx);
  ctx.setHtml(el, `<div class="team-board">${head(a, b)}${body}</div>`);
}
