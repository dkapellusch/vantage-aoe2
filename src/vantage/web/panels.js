// HUD panels: scoreboard, team overview, victory status, techs (and the
// slide-outs), production, dashboard, events, unit panel, resources left,
// time controls.
//
// Every newer backend field may be missing (older
// recordings, live sources that lack the data): features hide themselves
// rather than show zeros.

import {
  AGE_REQ, AGE_TECHS, STATIC_TECHS, TOWN_CENTERS, GOTO_BUILDINGS, TREE_CATEGORIES, TREE_CATEGORY_LABEL, TREE_ROW_KEYS,
  ARMOR_CLASSES, KING_MASTER, treeCategory, SETTLEMENT_MASTERS, FARM_TECHS, PASTURE_TECHS, POWER_TECHS, SHARED_CASTLE_TECHS,
} from './games.js';
import {
  S, settings, saveSettings, SPEEDS, fmtTime, fmtNum, fmtStock, esc, players, player, playerName, playerColor,
  teams, teamIcon, plainTeamName, teamMemberLabel, layoutKind, isTwoTeamLayout, sideTeams, teamName, unitInfo, entityStatsValid, entityStatsUsable, legacyStatsFresh, unitIcon, techInfo, techIcon, emblem, playerStats,
  cyclePlayerColor, playerTextColor, AGE_NAMES, RES, tip, techInfoFor, techIconFor, ageName, ageIcon, civEra,
  skinOption, skinAsset,
  withAssetVersion,
} from './state.js';
import { centerOn, currentRows, selectedRows, gatherersOf, isTreeId, rowForEntityId } from './world.js';
import { t, language } from './i18n.js';
import { setSelectionHtml } from './selection-panel.js';
import { patchHtml, listDelta } from './dom.js';
import { ownerIdentity, selectionHeader, militaryCard, wireReviewControls, reviewIcon, DASH_HISTORY, DASH_SELECTIONS } from './player-review.js';
import { resourceTotalsHtml } from './resource-review.js';
import { renderTeamBoard, toggleTeamBoardView } from './team-board.js';

const $ = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const has = (v) => v !== undefined && v !== null;

// An element the HUD needs but index.html does not declare: created on first use.
function hudEl(id, cls = 'panel hidden', tag = 'div') {
  let el = $(id);
  if (!el) {
    el = document.createElement(tag);
    el.id = id; el.className = cls;
    ($('hud') || document.body).appendChild(el);
  }
  return el;
}

// Delegated listeners, installed once per element. Panels re-render every
// 250 ms, so listeners added per render would miss clicks that straddle one.
// Rewrite an element only when its HTML changed. The panels re-render four
// times a second; replacing the nodes under the pointer between mousedown and
// mouseup swallowed clicks, and rewriting identical HTML is wasted layout at 8x.
function setHtml(el, html) {
  if (el.id === 'unitpanel') {
    const context = `${S.session?.generation}:${[...S.selection].sort((a, b) => a - b).join(',')}`;
    setSelectionHtml(el, html, context); return;
  }
  if (el._html !== html) { el._html = html; patchHtml(el, html); }
}

function setText(el, text) {
  if (el.textContent === text) return;
  if (el.childNodes.length === 1 && el.firstChild.nodeType === 3) el.firstChild.nodeValue = text;
  else el.textContent = text;
}

function delegate(el, type, selector, fn) {
  const k = `_vd_${type}_${selector}`;
  if (!el || el[k]) return;
  el[k] = true;
  el.addEventListener(type, (ev) => {
    const target = ev.target.closest && ev.target.closest(selector);
    if (target && el.contains(target)) fn(target, ev);
  });
}

const pn = (pid) => `<b style="color:${playerTextColor(pid)}">${esc(playerName(pid))}</b>`;
const costText = (cost) => Object.entries(cost || {}).filter(([, v]) => v > 0).map(([k, v]) => `${Math.round(v)} ${t(k)}`).join(', ');
const AGE_ICON = (age, pid) => ageIcon(clamp(age, 0, 3), pid);
const YEAR_MS = 5000; // 1 game-year = 5 s of game time
// "1 year" / "N years": round(ms / 5000).
function yearsText(ms, years) {
  const n = has(years) ? Math.round(+years) : Math.round((+ms || 0) / YEAR_MS);
  return n === 1 ? t('{n} year', { n }) : t('{n} years', { n });
}

function orderedTeams() { return isTwoTeamLayout() ? sideTeams() : teams(); }
function teamOf(pid) {
  const p = player(pid);
  return p ? teams().find((tm) => tm.key === p.team_key) || null : null;
}
function isDead(pid) {
  const s = playerStats(pid);
  return !!s && s.status !== 'playing' && s.status !== 'won';
}

// -- score & rating ----------------------------------------------------------------------

function scoreParts(s) {
  const p = (s && (s.score_parts || s.score)) || {};
  return { military: p.military || 0, economy: p.economy || 0, technology: p.technology || 0, society: p.society, total: p.total };
}
function playerScore(pid) {
  const p = scoreParts(playerStats(pid));
  return p.military + p.economy + p.technology + (p.society || 0);
}
// Score breakdown: Military; Economy with "Units & buildings" and
// "Resources banked"; Technology with "Exploration" and "Research"; Society.
// Sub-rows come from players[pid].score_sub (victoryPointMap) when present.
function scoreTip(s, title) {
  const p = scoreParts(s);
  const sub = (s && s.score_sub) || null;
  const lines = [`${t('Military')} ${fmtNum(p.military)}`, `${t('Economy')} ${fmtNum(p.economy)}`];
  if (sub) lines.push(`   ${t('Units & buildings')} ${fmtNum(sub.units_buildings || 0)}`, `   ${t('Resources banked')} ${fmtNum(sub.resources_banked || 0)}`);
  lines.push(`${t('Technology')} ${fmtNum(p.technology)}`);
  if (sub) lines.push(`   ${t('Exploration')} ${fmtNum(sub.exploration || 0)}`, `   ${t('Research')} ${fmtNum(sub.research || 0)}`);
  if (has(p.society)) lines.push(`${t('Society')} ${fmtNum(p.society)}`);
  return tip(title, '\n' + lines.join('\n'));
}
// Team values are summed (score parts and sub-rows).
function teamScoreStats(team) {
  const out = { score_parts: { military: 0, economy: 0, technology: 0, society: 0 }, score_sub: null };
  let anySociety = false;
  for (const p of team.players) {
    const s = playerStats(p.id);
    if (!s) continue;
    const sp = scoreParts(s);
    out.score_parts.military += sp.military; out.score_parts.economy += sp.economy; out.score_parts.technology += sp.technology;
    if (has(sp.society)) { anySociety = true; out.score_parts.society += sp.society; }
    if (s.score_sub) {
      out.score_sub = out.score_sub || { exploration: 0, research: 0, units_buildings: 0, resources_banked: 0 };
      for (const k of Object.keys(out.score_sub)) out.score_sub[k] += +s.score_sub[k] || 0;
    }
  }
  if (!anySociety) delete out.score_parts.society;
  return out;
}
// Players ranked as an FFA leaderboard: still playing first, then by score.
function rankedPlayers() {
  return players().slice().sort((a, b) => (isDead(a.id) - isDead(b.id)) || (playerScore(b.id) - playerScore(a.id)) || (a.id - b.id));
}

const ELO_TIP = 'Rating at the start of the game. In unranked games only the ranked (RM) rating is shown, and only when "Show ranked Elo for unranked games" is on.';
function eloOf(p) {
  const s = playerStats(p.id) || {};
  const rm = s.elo_rm ?? p.elo_rm;
  if (S.match.ranked) return p.elo ? { v: p.elo, kind: '' } : null;
  // An unranked game has no rating of its own; the toggle falls back to the RM ladder only.
  return settings.showRankedEloForUnrankedGames && rm ? { v: rm, kind: 'RM' } : null;
}

// -- casting series ----------------------------------------------------------------------
// settings.scoreboard = {seriesType: 'bestOf'|'playAll', numberOfMatches (<=21),
// matches: [{winner}], seeds: {}}. A two-team winner (and seed key) is 'A' for
// the first team in game order or 'B' for the second; an FFA winner is a pid.

function sideKey(team) { return teams().findIndex((x) => x.key === team.key) === 0 ? 'A' : 'B'; }

function series() {
  const sb = settings.scoreboard || {};
  // The series shows once the caster sets it up (enabled, or any winner entered).
  const on = sb.enabled ?? (sb.matches || []).some((m) => m != null && (typeof m !== 'object' || (m.winner != null && m.winner !== '')));
  const n = on ? clamp(Math.round(+sb.numberOfMatches || 0), 0, 21) : 0;
  const type = sb.seriesType === 'playAll' ? 'playAll' : 'bestOf';
  const wins = {};
  let played = 0;
  for (const m of (sb.matches || []).slice(0, n)) {
    const w = m && typeof m === 'object' ? m.winner : m;
    if (w == null || w === '') continue;
    played++;
    wins[String(w)] = (wins[String(w)] || 0) + 1;
  }
  let text = '';
  if (n) text = type === 'bestOf' ? t('Best of {n}', { n }) : t('Game {i} of {n}', { i: Math.min(n, played + 1), n });
  // The older free-text fields override the derived text.
  if (settings.seriesType || settings.seriesScore) text = `${settings.seriesType || ''} ${settings.seriesScore || ''}`.trim();
  return { n, type, wins, played, dots: type === 'bestOf' ? Math.floor(n / 2) + 1 : n, text, override: !!settings.seriesScore };
}

function dotsHtml(sr, key) {
  if (!sr.n || settings.hideScoreDots) return '';
  const w = sr.wins[key] || 0;
  return `<span class="sb-dots" ${tip(t('Series score'), t('{n} won', { n: w }))}>${Array.from({ length: sr.dots }, (_, i) => `<i class="${i < w ? 'on' : ''}"></i>`).join('')}</span>`;
}
function seedOf(key, alt) {
  const seeds = (settings.scoreboard || {}).seeds || {};
  return seeds[key] ?? seeds[alt] ?? '';
}

// -- kings (regicide) ----------------------------------------------------------------------

let regicideMatch = null;
function regicide() {
  if (regicideMatch === S.match) return true;
  const ks = S.view && S.view.kings;
  const yes = (Array.isArray(ks) && ks.length > 0)
    || players().some((p) => ((playerStats(p.id) || {}).units || {})[KING_MASTER])
    || S.events.some((e) => e.kind === 'king_killed');
  if (yes) regicideMatch = S.match;
  return yes;
}
function kingOf(pid) {
  const ks = S.view && S.view.kings;
  if (Array.isArray(ks)) return ks.find((k) => k.pid === pid) || null;
  const s = playerStats(pid);
  return s && s.units && s.units[KING_MASTER] ? { pid } : null;
}
// view.king_status {pid: {state: 'alive'|'dead'|'none', x?, y?}} tells "never
// had a King" (ban icon) from a dead one (death location); older data falls
// back to the king_killed events.
function kingStatus(pid) {
  const ks = S.view && S.view.king_status;
  const st = ks ? ks[pid] ?? ks[String(pid)] : null;
  if (st) return st;
  if (kingOf(pid)) return { state: 'alive' };
  const ev = S.events.slice().reverse().find((e) => e.kind === 'king_killed' && e.player === pid && e.t <= S.t);
  return ev ? { state: 'dead', x: ev.x, y: ev.y } : { state: 'none' };
}
function kingGlyph(pid) {
  const k = kingOf(pid);
  const st = kingStatus(pid);
  if (st.state === 'none') return `<span class="sb-king none" ${tip(t('No king found for this player'))}>⊘</span>`;
  if (!k || st.state === 'dead') {
    const at = has(st.x) ? `data-king="" data-x="${st.x}" data-y="${st.y}"` : '';
    return `<span class="sb-king dead" ${at} ${tip(t('King killed'), has(st.x) ? t('click: go to where the king died') : '')}>☠</span>`;
  }
  const hp = has(k.hp) ? (k.hp <= 1 ? Math.round(k.hp * 100) + '%' : Math.round(k.hp) + ' HP') : '';
  const where = k.garrisoned ? t('garrisoned') : '';
  return `<span class="sb-king" data-king="${k.id ?? ''}" data-x="${k.x ?? ''}" data-y="${k.y ?? ''}" ${tip(t('King'), [hp, where, has(k.x) ? t('click: go to the king') : ''].filter(Boolean).join(' · '))}>♔${k.garrisoned ? '⌂' : ''}</span>`;
}

// -- panel offsets (CSS variables) ----------------------------------------------------------

// settings.panelOffsets: {dashboard, score, minimap, selectionPanel,
// eventNotifications: [up, right]} in 1080p reference pixels (no clamp; index 0
// moves the panel up, index 1 right) plus overviewTop (team overview padding,
// also used by the end-game panel). Applied as CSS variables; hud.css turns
// them into `translate` so they compose with each panel's own transform.
let offsetsKey = '';
function applyPanelOffsets() {
  const o = settings.panelOffsets || {};
  const pair = (x) => (Array.isArray(x) ? [+x[0] || 0, +x[1] || 0] : [0, 0]);
  // Settings saved in the older shape (should be migrated already).
  const legacy = !Array.isArray(o.dashboard) && !Array.isArray(o.score);
  const dash = legacy ? [+o.dashboardBottom || 0, 0] : pair(o.dashboard);
  const score = legacy ? [+o.scoreBottom || 0, +o.scoreRight || 0] : pair(o.score);
  // UI scale (pixelSize): offsets are 1080p reference pixels times window height / 1080.
  const px = (window.innerHeight || 1080) / 1080;
  const v = { '--ov-top': (+o.overviewTop || 0) * px };
  for (const [name, [up, right]] of [['dash', dash], ['score', score], ['mm', pair(o.minimap)], ['up', pair(o.selectionPanel)], ['ev', pair(o.eventNotifications)]]) {
    v[`--${name}-up`] = up * px; v[`--${name}-right`] = right * px;
  }
  for (const n of Object.keys(v)) v[n] = Math.round(v[n] * 100) / 100;
  const k = JSON.stringify(v);
  if (k === offsetsKey) return;
  offsetsKey = k;
  for (const [name, px] of Object.entries(v)) document.documentElement.style.setProperty(name, px + 'px');
}

window.addEventListener('resize', () => applyPanelOffsets());

// -- civ tech tree (hover a civ emblem) --------------------------------------------------

const techTrees = new Map(); // `${game}:${civ}` -> tree | null | Promise
const buildingMeta = new Map(); // building master -> {icon, name}, from loaded trees

function treeKey(civ) { return `${S.game}:${civ}`; }
function loadTree(civ) {
  if (civ == null) return Promise.resolve(null);
  const key = treeKey(civ);
  if (techTrees.has(key)) return Promise.resolve(techTrees.get(key));
  const p = fetch(`/api/techtree/${civ}?lang=${encodeURIComponent(language || 'en')}`, { priority: 'low' }).then((r) => r.json()).catch(() => null).then((tree) => {
    const ok = tree && tree.nodes ? tree : null;
    techTrees.set(key, ok);
    // A failed or empty answer (the game data not ready yet) must not stick for the
    // whole session: forget it shortly, and the next render asks again.
    if (!ok) setTimeout(() => { if (techTrees.get(key) === null) techTrees.delete(key); }, 5000);
    for (const b of (ok && ok.buildings) || []) if (!buildingMeta.has(b.id)) buildingMeta.set(b.id, { icon: b.icon, name: b.name });
    return ok;
  });
  techTrees.set(key, p);
  return p;
}
function treeNow(civ) {
  const v = techTrees.get(treeKey(civ));
  return v instanceof Promise ? null : v;
}
function buildingIcon(mid) {
  if (unitInfo(mid).icon >= 0) return unitIcon(mid);
  const m = buildingMeta.get(mid);
  return m && m.icon >= 0 ? withAssetVersion(`/icon/building/${m.icon}.png?g=${S.game}`) : '';
}
function buildingName(mid) {
  const u = unitInfo(mid);
  return u.icon >= 0 || !buildingMeta.has(mid) ? u.name : buildingMeta.get(mid).name;
}

// Upgrade lines: from the tree's link ids when the server sends them, else by
// position (consecutive nodes of one building and kind with rising ages).
function treeLines(nodes) {
  const lines = [];
  if (nodes.some((n) => has(n.link))) {
    const byId = new Map(nodes.map((n) => [`${n.building}:${n.id}`, n]));
    const lineOf = new Map();
    for (const n of nodes) {
      const par = has(n.link) && n.link >= 0 ? byId.get(`${n.building}:${n.link}`) : null;
      const l = par && lineOf.get(par);
      if (l && (par.kind === n.kind)) { l.push(n); lineOf.set(n, l); } else { const nl = [n]; lines.push(nl); lineOf.set(n, nl); }
    }
    return lines;
  }
  let cur = null;
  for (const n of nodes) {
    const prev = cur && cur[cur.length - 1];
    if (prev && prev.building === n.building && prev.kind === n.kind && n.age > prev.age) cur.push(n);
    else { cur = [n]; lines.push(cur); }
  }
  return lines;
}
function nodeCost(n) {
  if (n.kind === 'tech') return techInfo(n.id).cost;
  if (has(n.trigger_tech) && n.trigger_tech >= 0) return techInfo(n.trigger_tech).cost;
  return unitInfo(n.id).cost;
}

let hoverPid = null, pinnedTree = false;
// Struck (not available to this civ) vs hidden (regional content no civ marks
// unavailable) follow the server's per-node status; older servers send only
// `available`, which reads as struck.
function nodeStatus(n) {
  if (n.status === 'hidden') return 'hidden';
  if (n.status === 'struck' || n.available === false) return 'struck';
  return 'available';
}
// Civ description: markup stripped, first line underlined.
function civDescHtml(desc) {
  const lines = String(desc || '').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '').split('\n').map((x) => x.trim());
  while (lines.length && !lines[0]) lines.shift();
  if (!lines.length) return '';
  const [first, ...rest] = lines;
  return `<div class="tt-desc"><u>${esc(first)}</u>${rest.length ? '<br>' + rest.map(esc).join('<br>') : ''}</div>`;
}
function uniqueUnitsHtml(tree) {
  const uu = Array.isArray(tree.unique_units) ? tree.unique_units : [];
  if (!uu.length) return '';
  return `<div class="tt-uu">${uu.map((u) => `<div class="tt-node" ${tip(u.name || '', String(u.description || '').replace(/<[^>]+>/g, ''))}><img src="/icon/unit/${u.icon}.png?g=${S.game}" alt=""></div>`).join('')}</div>`;
}

export async function showTechTree(pid) {
  const p = player(pid);
  if (!p || p.civ == null) return;
  hoverPid = pid;
  const tree = await loadTree(p.civ);
  if (hoverPid !== pid || !tree) return;
  const el = $('techtree');
  const s = playerStats(pid) || {};
  const done = new Set(s.research_done || []);
  const active = new Set((s.research_active || []).map((a) => a.tech));
  const units = s.units || {};
  const age = s.age ?? 0;
  // Stage state from the player's research: done / researching / reachable / later age.
  const progress = (kind, id, nAge, trigger) => {
    if (kind === 'tech') return done.has(id) ? 'done' : active.has(id) ? 'doing' : (nAge ?? 1) - 1 <= age ? '' : 'todo';
    if (units[id] || (has(trigger) && trigger >= 0 && done.has(trigger))) return 'done';
    return (nAge ?? 1) - 1 <= age ? '' : 'todo';
  };
  let body;
  if (tree.layout && Array.isArray(tree.layout.rows)) {
    // Nine headed rows of curated groups (antiquity civs: economy
    // only; regional-hidden groups and variant swaps already resolved server-side).
    const rows = tree.layout.rows.map((row) => {
      const groups = (row.groups || []).map((g) => {
        const stages = g.stages || [];
        const byKey = new Map(stages.map((st) => [st.key, st]));
        // A later tier is unavailable when its base tier is.
        const struck = (st) => st.status === 'struck' || (st.base_key && byKey.get(st.base_key) && byKey.get(st.base_key).status === 'struck');
        const top = [...stages].reverse().find((st) => !struck(st)) || stages[stages.length - 1];
        const cost = top ? costText(top.cost || (top.kind === 'tech' ? techInfo(top.id).cost : unitInfo(top.id).cost)) : '';
        const cells = stages.filter((st) => st.status !== 'hidden').map((st) => {
          const cls = struck(st) ? 'na' : progress(st.kind, st.id, st.age, st.trigger);
          const src = withAssetVersion(`/icon/${st.icon_kind === 'unit' ? 'unit' : 'tech'}/${st.icon}.png?g=${S.game}`);
          return `<div class="tt-node ${cls}" ${tip(st.name || '', cls === 'na' ? t('not available to this civilisation') : '')}><img src="${src}" alt=""></div>`;
        }).join('');
        return cells ? `<div class="tt-line">${cells}${cost ? `<span class="tt-cost" ${tip(t('Cost of the highest tier'), top.name || '')}>${esc(cost)}</span>` : ''}</div>` : '';
      }).join('');
      const label = TREE_ROW_KEYS[row.key] ? (TREE_CATEGORY_LABEL[TREE_ROW_KEYS[row.key]] || TREE_ROW_KEYS[row.key]) : (row.name || row.key);
      return groups ? `<div class="tt-cat"><div class="tt-cat-h">${esc(t(label))}</div><div class="tt-groups">${groups}</div></div>` : '';
    }).join('');
    body = `<div class="tt-cats tt-rows">${rows}</div>`;
  } else {
    // Older servers / Return of Rome: lines from the civ file, grouped by role.
    const byCat = new Map(TREE_CATEGORIES.map((c) => [c, []]));
    const economyOnly = (tree.era || civEra(p.civ)) === 'antiquity';
    for (const line of treeLines(tree.nodes)) {
      const shown = line.filter((n) => nodeStatus(n) !== 'hidden');
      if (!shown.length) continue; // regional content: hidden
      const cat = treeCategory(shown[0]);
      if (economyOnly && cat !== 'Economy') continue;
      byCat.get(cat).push(shown);
    }
    const rows = [...byCat.entries()].filter(([, ls]) => ls.length).map(([cat, ls]) => {
      const lines = ls.map((line) => {
        let baseStruck = false;
        const cells = line.map((n) => {
          const na = baseStruck || nodeStatus(n) === 'struck';
          baseStruck = na;
          const src = withAssetVersion(`/icon/${n.kind === 'unit' ? 'unit' : 'tech'}/${n.icon}.png?g=${S.game}`);
          return `<div class="tt-node ${na ? 'na' : progress(n.kind, n.id, n.age, n.trigger_tech)}" ${tip(n.name, na ? t('not available to this civilisation') : '')}><img src="${src}" alt=""></div>`;
        }).join('');
        const top = [...line].reverse().find((n) => nodeStatus(n) === 'available') || line[line.length - 1];
        const cost = costText(nodeCost(top));
        return `<div class="tt-line">${cells}${cost ? `<span class="tt-cost" ${tip(t('Cost of the highest tier'), top.name)}>${esc(cost)}</span>` : ''}</div>`;
      }).join('');
      return `<div class="tt-cat"><div class="tt-cat-h">${esc(t(TREE_CATEGORY_LABEL[cat] || cat))}</div><div class="tt-groups">${lines}</div></div>`;
    }).join('');
    body = `<div class="tt-cats${S.game === 'ror' ? '' : ' tt-rows'}">${rows}</div>`;
  }
  // The civ description is long: it shows only while Shift is held.
  const desc = civDescHtml(tree.description || tree.help || '');
  patchHtml(el, `<h3 style="color:${playerTextColor(pid)}">${esc(playerName(pid))} — ${esc(t('{civ} tech tree', { civ: tree.name }))}</h3>
    <button class="review-tree-close" aria-label="${t('Close')}">×</button>${desc}${uniqueUnitsHtml(tree)}${body}
    <div class="tt-age">${esc(t('Green outline: researched or trained · dim: later age · struck: not available to this civilisation'))}${desc ? ` · ${esc(t('hold Shift for civilisation bonuses'))}` : ''}</div>`);
  el.querySelector('.review-tree-close').onclick = () => { pinnedTree = false; hideTechTree(); };
  el.classList.remove('hidden');
  placeTechTree();
}
// Beside the scoreboard, never over it: below it (or above, when it sits low),
// horizontally centred on the hovered emblem and kept on screen.
function placeTechTree() {
  const el = $('techtree');
  const board = $('scoreboard');
  if (el.classList.contains('hidden') || !board) return;
  const b = board.getBoundingClientRect();
  // Found again each time: the scoreboard re-renders its emblems.
  const em = board.querySelector(`[data-pid="${hoverPid}"] img.emblem`);
  const a = em ? em.getBoundingClientRect() : b;
  const W = window.innerWidth, H = window.innerHeight, gap = 6, margin = 8;
  const below = H - b.bottom >= b.top;
  el.style.maxHeight = `${Math.max(120, (below ? H - b.bottom : b.top) - gap - margin)}px`;
  const w = el.offsetWidth;
  el.style.left = `${Math.round(Math.min(Math.max(margin, a.left + a.width / 2 - w / 2), Math.max(margin, W - w - margin)))}px`;
  el.style.top = below ? `${Math.round(b.bottom + gap)}px` : '';
  el.style.bottom = below ? '' : `${Math.round(H - b.top + gap)}px`;
}
function setTechTreeDesc(on) {
  const el = $('techtree');
  if (el.classList.contains('show-desc') === on) return;
  el.classList.toggle('show-desc', on);
  placeTechTree();
}
export function hideTechTree() { pinnedTree = false; hoverPid = null; $('techtree').classList.add('hidden'); }
window.addEventListener('mousemove', (e) => {
  if (!pinnedTree && hoverPid != null && !e.target.closest?.('#techtree, #scoreboard img.emblem')) hideTechTree();
});
window.addEventListener('keydown', (e) => { if (e.key === 'Shift') setTechTreeDesc(true); });
window.addEventListener('keyup', (e) => { if (e.key === 'Shift') setTechTreeDesc(false); });
window.addEventListener('blur', () => setTechTreeDesc(false));

// -- scoreboard ---------------------------------------------------------------------------

function civName(p) { return S.catalog.civs?.[p.civ] || p.civ_name || ''; }

function playerTile(p, opts = {}) {
  const s = playerStats(p.id);
  const e = settings.showElo ? eloOf(p) : null;
  const elo = e ? ` · <span class="sb-elo" ${tip(t('Elo'), t(ELO_TIP))}>${e.v}${e.kind ? ' ' + e.kind : ''}</span>` : '';
  const score = settings.hideScore ? '' : `<span class="sb-score" ${scoreTip(s, t('Score'))}>${fmtNum(playerScore(p.id))}</span>`;
  const tm = teamOf(p.id);
  const captain = tm && tm.players.length > 1 && settings.teamCaptains[p.team_key] === p.id ? `<span class="sb-captain" ${tip(t('Team captain'))}>★</span>` : '';
  const flag = settings.playerImages[p.id] ? `<img class="flag" src="${esc(settings.playerImages[p.id])}" alt="">` : '';
  const rank = opts.rank ? `<span class="sb-rank" ${tip(t('Rank'), t('By score; defeated players last'))}>${opts.rank}</span>` : '';
  const persp = S.fogMode !== 'off' && S.perspective === p.id ? ' persp' : '';
  return `<div class="sb-player ${isDead(p.id) ? 'dead' : ''}${persp}" data-pid="${p.id}" style="border-color:${playerColor(p.id)}" ${tip(t('Click: change colour'), t('Click the name for team details (Ctrl+Alt+R) · hover the emblem for the tech tree'))}>
    ${rank}${flag}<img class="emblem" src="${emblem(p.civ)}" alt="">
    <div><div class="sb-name"><span class="sb-pname" data-details="1">${captain}${esc(playerName(p.id, true))}</span> ${opts.king || ''}</div><div class="sb-sub">${esc(civName(p))}${elo}${opts.dots || ''}</div></div>${score}</div>`;
}

function centerBlock(speedLabel, sr, scoreLine = '', extra = '') {
  const stage = settings.stageName ? ' · ' + esc(settings.stageName) : '';
  const seriesTxt = sr.text ? `<div class="sb-series">${esc(sr.text)}${scoreLine}</div>` : '';
  return `<div class="sb-center">${seriesTxt}<div class="sb-clock">${fmtTime(S.t)}</div>${extra}<div class="sb-speed">${esc(speedLabel)}${stage}</div></div>`;
}

// -- two-team scoreboard: team label and score total per side, players as chips,
// the score share and lead under the clock ------------------------------------------------

const teamScoreOn = () => !settings.hideScore && settings.teamScore !== 'off';
function teamScoreValue(team) {
  const total = team.players.reduce((x, p) => x + playerScore(p.id), 0);
  return settings.teamScore === 'average' ? total / Math.max(1, team.players.length) : total;
}

function teamChip(p, opts) {
  const s = playerStats(p.id);
  const e = settings.showElo ? eloOf(p) : null;
  const tm = teamOf(p.id);
  const solo = !tm || tm.players.length === 1;
  const captain = !solo && settings.teamCaptains[p.team_key] === p.id ? `<span class="sb-captain" ${tip(t('Team captain'))}>★</span>` : '';
  const flag = settings.playerImages[p.id] ? `<img class="flag" src="${esc(settings.playerImages[p.id])}" alt="">` : '';
  const persp = S.fogMode !== 'off' && S.perspective === p.id ? ' persp' : '';
  // A one-player side already shows the name in its heading: the chip shows the civ.
  const label = solo ? civName(p) : teamMemberLabel(p.id);
  const elo = e ? `<span class="sb-elo" ${tip(t('Elo'), t(ELO_TIP))}>${e.v}${e.kind ? ' ' + e.kind : ''}</span>` : '';
  const score = settings.hideScore || solo ? '' : `<span class="sb-score" ${scoreTip(s, t('Score'))}>${fmtNum(playerScore(p.id))}</span>`;
  const full = `${playerName(p.id, true)} · ${civName(p)}`;
  return `<div class="sb-player sb-chip ${isDead(p.id) ? 'dead' : ''}${persp}" data-pid="${p.id}" style="--pc:${playerColor(p.id)}" ${tip(full, t('Click: change colour · click the name for team details (Ctrl+Alt+R) · hover the emblem for the tech tree'))}>
    ${flag}<img class="emblem" src="${emblem(p.civ)}" alt=""><span class="sb-pname" data-details="1">${captain}${esc(label)}</span>${opts.king || ''}${elo}${score}</div>`;
}

function teamSide(team, right, sr, kingFor) {
  const key = sideKey(team);
  const seed = seedOf(key, team.key);
  const ico = teamIcon(team);
  const names = team.players.map((p) => playerName(p.id, true));
  const twins = names.length > 1 && new Set(names).size === 1 && !settings.teamNames[team.key];
  const avg = settings.teamScore === 'average';
  const total = teamScoreOn() ? `<span class="sb-total" ${scoreTip(teamScoreStats(team), t(avg ? 'Team average score' : 'Team score'))}>${avg && team.players.length > 1 ? '⌀ ' : ''}${fmtNum(teamScoreValue(team))}</span>` : '';
  const label = `<span class="sb-tname" data-details="1" ${tip(plainTeamName(team), t('Click: team details (Ctrl+Alt+R)'))}>${esc(teamName(team))}${twins ? `<small class="sb-count">×${names.length}</small>` : ''}</span>`;
  const head = `<div class="sb-teamhead" style="--tc:${playerColor(team.players[0].id)}"><i class="sb-strip"></i>${ico ? `<img class="sb-team-ico" src="${esc(ico)}" alt="">` : ''}${label}${seed ? `<span class="sb-seed" ${tip(t('Seed'))}>${esc(seed)}</span>` : ''}${dotsHtml(sr, key)}${total}</div>`;
  return `<div class="sb-side ${right ? 'right' : ''}">${head}<div class="team ${right ? 'right' : ''}">${team.players.map((p) => teamChip(p, { king: kingFor(p) })).join('')}</div></div>`;
}

function leadHtml(a, b) {
  if (!teamScoreOn()) return '';
  const va = teamScoreValue(a), vb = teamScoreValue(b), tot = va + vb;
  if (!(tot > 0)) return '';
  const d = va - vb, ahead = d > 0 ? a : b;
  const lead = Math.round(d) === 0 ? `<div class="sb-lead even">${esc(t('even'))}</div>`
    : `<div class="sb-lead" style="color:${playerTextColor(ahead.players[0].id)}" ${tip(t('Lead'), teamName(ahead))}>${d > 0 ? '<b class="arr">◀</b>' : ''}${fmtNum(Math.abs(d))}${d < 0 ? '<b class="arr">▶</b>' : ''}</div>`;
  const share = (100 * va) / tot;
  return `<div class="sb-share" ${tip(t('Score share'), `${Math.round(share)}% – ${Math.round(100 - share)}%`)}><i style="width:${share.toFixed(1)}%;background:${playerColor(a.players[0].id)}"></i><i style="background:${playerColor(b.players[0].id)}"></i></div>${lead}`;
}

export function renderScoreboard(speedLabel) {
  applyPanelOffsets();
  const victory = victoryHtml();
  renderVictory(victory);
  const el = $('scoreboard');
  el.classList.toggle('hidden', !!settings.disableScoreboard);
  if (settings.disableScoreboard) return;
  const kind = layoutKind();
  const ps = players();
  const sr = series();
  const kings = ps.length && regicide();
  const kingFor = (p) => (kings ? kingGlyph(p.id) : '');
  let html;
  if (!ps.length) {
    // Idle: nothing is open, so there are no players to wait for.
    const idle = !S.session || S.session.mode === 'idle';
    html = `${centerBlock(speedLabel, sr)}<div class="sb-empty">${esc(idle ? t('Nothing open') : t('Waiting for players…'))}</div>`;
  } else if (isTwoTeamLayout(kind)) {
    const [a, b] = sideTeams();
    const scoreLine = sr.n && !sr.override ? ` · <b>${sr.wins[sideKey(a)] || 0} – ${sr.wins[sideKey(b)] || 0}</b>` : '';
    html = `${teamSide(a, false, sr, kingFor)}${centerBlock(speedLabel, sr, scoreLine, leadHtml(a, b))}${teamSide(b, true, sr, kingFor)}${rbw4Timer()}`;
  } else if (kind === 'community') {
    const ranked = rankedPlayers();
    html = `${centerBlock(speedLabel, sr)}<table class="sb-community">${ranked.map((p, i) => {
      const s = playerStats(p.id) || {};
      return `<tr class="sb-player ${isDead(p.id) ? 'dead' : ''}" data-pid="${p.id}" ${tip(t('Click: change colour'), t('Click the name for team details'))}>
        <td class="sb-rank">${i + 1}</td><td><i class="sb-swatch" style="background:${playerColor(p.id)}"></i></td>
        <td><img class="emblem" src="${emblem(p.civ)}" alt=""></td>
        <td class="sb-name"><span class="sb-pname" data-details="1" style="color:${playerTextColor(p.id)}">${esc(playerName(p.id))}</span> ${kingFor(p)}${dotsHtml(sr, String(p.id))}</td>
        <td class="sb-sub">${esc(civName(p))}</td><td>${has(s.age) ? `<img class="sb-age" src="${AGE_ICON(s.age, p.id)}" alt="" ${tip(ageName(s.age, p.id))}>` : ''}</td>
        <td class="num" ${tip(t('Villagers'))}>${s.villagers ?? '–'}</td><td class="num" ${tip(t('Military units'))}>${s.military ?? '–'}</td>
        <td>${settings.hideScore ? '' : `<span class="sb-score" ${scoreTip(s, t('Score'))}>${fmtNum(playerScore(p.id))}</span>`}</td>
        <td class="sb-power">${powerTechsHtml(p.id, s)}</td></tr>`;
    }).join('')}</table>`;
    if (ranked.some((p) => powerTechsHtml(p.id, playerStats(p.id) || {}))) html = html.replace('<table class="sb-community">', `<table class="sb-community"><tr class="sb-comm-head"><td colspan="9"></td><td>${esc(t('Power Techs'))}</td></tr>`);
  } else {
    // ffa / battleRoyale: one tile per player in seat order, with a rank badge.
    const ranked = rankedPlayers();
    const rankOf = new Map(ranked.map((p, i) => [p.id, i + 1]));
    let shown = ps;
    let extra = '';
    if (kind === 'battleRoyale') {
      shown = ranked.slice(0, 8);
      const alive = ps.filter((p) => !isDead(p.id)).length;
      extra = `<div class="sb-br" ${tip(t('Players still alive'))}>${esc(t('{n} / {m} alive', { n: alive, m: ps.length }))}</div>`;
    }
    const cols = Math.min(shown.length, shown.length > 4 ? Math.ceil(shown.length / 2) : 4);
    html = `${centerBlock(speedLabel, sr)}<div class="sb-ffa" style="grid-template-columns:repeat(${cols}, auto)">${shown.map((p) => playerTile(p, {
      rank: settings.hideScore ? 0 : rankOf.get(p.id), king: kingFor(p), dots: dotsHtml(sr, teams().length === 2 ? sideKey(teamOf(p.id)) : String(p.id)),
    })).join('')}</div>${extra}`;
  }
  const allies = [];
  for (const a of ps) {
    const s = playerStats(a.id);
    if (!s || !s.diplomacy) continue;
    for (const b of ps) if (b.id > a.id && s.diplomacy[b.id] === 'ally' && (playerStats(b.id) || {}).diplomacy?.[a.id] === 'ally') allies.push([a.id, b.id]);
  }
  // An "Allies" header shows whenever the lobby's teams are not locked.
  const unlocked = teamsLocked() === false;
  if (isTwoTeamLayout(kind)) {
    // Team games: alliances inside the lobby teams are the norm, so only the
    // ones across teams are listed; unlocked teams get a one-line note.
    const across = allies.filter(([x, y]) => player(x)?.team_key !== player(y)?.team_key);
    const pair = ([x, y]) => `<span style="color:${playerTextColor(x)}">${esc(playerName(x))}</span>–<span style="color:${playerTextColor(y)}">${esc(playerName(y))}</span>`;
    if (across.length) html += `<div class="sb-allies" ${tip(t('Allies across teams'), t('Teams are not locked: alliances can change during the game'))}><b class="sb-allies-h">${esc(t('Allies across teams'))}</b> ${across.map(pair).join(' · ')}</div>`;
    else if (unlocked && teams().some((tm) => tm.players.length > 1)) html += `<div class="sb-allies sb-unlocked" ${tip(t('Teams are not locked'), allies.map(([x, y]) => `${playerName(x)} – ${playerName(y)}`).join('\n') || t('none'))}>${esc(t('Teams are not locked'))}</div>`;
  } else if (unlocked || allies.length) {
    const pairs = allies.map(([a, b]) => `<span style="color:${playerTextColor(a)}">${esc(playerName(a))}</span>–<span style="color:${playerTextColor(b)}">${esc(playerName(b))}</span>`).join(' · ');
    html += `<div class="sb-allies" ${tip(t('Allies'), t('Teams are not locked: alliances can change during the game'))}>${unlocked ? `<b class="sb-allies-h">${esc(t('Allies'))}</b> ` : '🤝 '}${pairs || `<span class="hint">${esc(t('none'))}</span>`}</div>`;
  }
  if (victory) html += `<div class="sb-victory">${victory}</div>`;
  if (settings.mainText || settings.secondaryText) {
    html = `<div class="sb-texts"><b>${esc(settings.mainText)}</b> <span>${esc(settings.secondaryText)}</span></div>` + html;
  }
  el.dataset.layout = kind;
  if (el._html === html) return;
  setHtml(el, html);
  delegate(el, 'click', '.sb-player, .sb-tname', (d, ev) => {
    const king = ev.target.closest('.sb-king[data-x]');
    if (king && king.dataset.x !== '') {
      centerOn(+king.dataset.x, +king.dataset.y);
      if (king.dataset.king !== '') S.selection = new Set([+king.dataset.king]);
      return;
    }
    if (ev.target.closest('[data-details]')) { toggleTeamBoardView(); renderOverview(); return; }
    if (d.dataset.pid) cyclePlayerColor(+d.dataset.pid);
  });
  delegate(el, 'mouseover', 'img.emblem', (im) => {
    const host = im.closest('[data-pid]');
    if (!pinnedTree && host && hoverPid !== +host.dataset.pid) showTechTree(+host.dataset.pid);
  });
}

// Lobby "lock teams" (match lock_teams / teams_locked); null when unknown.
function teamsLocked() {
  const m = S.match || {};
  const src = (S.session && S.session.source) || {};
  const opts = m.settings || m.game_options || {};
  const v = m.teams_locked ?? m.lock_teams ?? opts.teams_locked ?? opts.lock_teams
    ?? (src.lobby && (src.lobby.teams_locked ?? src.lobby.lock_teams)) ?? (src.replay_info && src.replay_info.lock_teams);
  return v == null ? null : !!v;
}

// RBW4 broadcast timer (skin option useRbw4Components): a countdown to the
// fixed game time (902·5 − 8) s, shown in the last 100 years with a bar that
// shrinks with the time left.
const RBW4_END_MS = (902 * 5 - 8) * 1000;
function rbw4Timer() {
  if (!skinOption('useRbw4Components')) return '';
  const left = RBW4_END_MS - S.t;
  if (left <= 0 || left > 100 * YEAR_MS) return '';
  const years = Math.ceil(left / YEAR_MS);
  return `<div class="sb-rbw4" ${tip(t('Tournament timer'), t('Game time left until the fixed end time'))}><span>${esc(years === 1 ? t('{n} year', { n: years }) : t('{n} years', { n: years }))}</span><div class="sb-rbw4-bar"><i style="width:${(100 * left / RBW4_END_MS).toFixed(2)}%"></i></div></div>`;
}

// "Power Techs" (community FFA layout): researched and researching final unit
// upgrades, unique techs and age techs.
function powerTechSet(pid) {
  const set = new Set(Array.isArray(S.catalog.power_techs) ? S.catalog.power_techs : POWER_TECHS);
  const ut = uniqueTechs((player(pid) || {}).civ);
  for (const x of [...ut.castle, ...ut.imperial]) set.add(x);
  return set;
}
function powerTechsHtml(pid, s) {
  const set = powerTechSet(pid);
  const done = (s.research_done || []).filter((x) => set.has(x));
  const doing = (s.research_active || []).filter((a) => set.has(a.tech));
  if (!done.length && !doing.length) return '';
  const cell = (tid, a) => `<div class="tech ${a ? 'doing' : 'yes'}" data-tech="${tid}" data-pid="${pid}" ${tip(techInfoFor(tid, pid).name, a ? t('researching {p}%', { p: Math.round(a.progress * 100) }) : t('researched'))}><img src="${techIconFor(tid, pid)}" alt="">${a ? `<div class="prog" style="width:${Math.round(a.progress * 100)}%"></div>` : ''}</div>`;
  return `<div class="sb-power-strip" ${tip(t('Power Techs'))}>${done.map((x) => cell(x)).join('')}${doing.map((a) => cell(a.tech, a)).join('')}</div>`;
}

function teamSum(team, key) {
  return team.players.reduce((acc, p) => acc + ((playerStats(p.id) || {})[key] || 0), 0);
}

// -- victory status: King of the Hill, wonder / relic countdowns ---------------------------

const VICTORY_LABEL = { wonder: 'Wonder victory', relic: 'Relic victory', relics: 'Relic victory', koth: 'King of the Hill victory' };

function countdownInfo(v) {
  const c = v.countdown;
  if (c == null || c === false) return null;
  if (typeof c === 'object') return { kind: c.kind || c.type || c.victory, player: c.player, years: c.years_left ?? c.years ?? c.remaining };
  // A bare clock value: credit the latest countdown, wonder or relic event.
  let src = null;
  for (let i = S.events.length - 1; i >= 0 && !src; i--) {
    const e = S.events[i];
    if (e.t <= S.t && (e.kind === 'countdown' || /wonder|relic/.test(e.kind))) src = e;
  }
  const kind = src ? (src.victory || src.type || (src.kind === 'countdown' ? '' : /wonder/.test(src.kind) ? 'wonder' : 'relic')) : '';
  return { kind, player: src ? src.player : null, years: c };
}

// Rendered as a row of the scoreboard; standalone (#victory) when the
// scoreboard is disabled.
function victoryHtml() {
  const v = S.view || {};
  const parts = [];
  const k = v.koth;
  if (k && typeof k === 'object') {
    // "{N} years left" for the holder, a bar of remaining / 550
    // years with a 100-year band centred on it; nothing while no one holds it.
    const own = k.holder ?? k.owner;
    const remMs = has(k.remaining_ms) ? +k.remaining_ms : (k.required_ms ? Math.max(0, k.required_ms - (k.held_ms || 0)) : null);
    if (own && has(remMs)) {
      const yrs = remMs / YEAR_MS;
      const time = yrs < 10 ? `${(Math.round(yrs * 10) / 10).toFixed(1)}` : `${Math.round(yrs)}`;
      const frac = clamp(yrs / 550, 0, 1);
      parts.push(`<div class="vic-row" ${tip(t('King of the Hill'), t('Who holds the monument and how long until they win'))}>
        <span class="vic-ico">⛰</span><span>${pn(own)}</span>
        <span class="num">${esc(t('{time} left', { time: t('{n} years', { n: time }) }))}</span>
        <div class="vic-bar koth"><i style="width:${(frac * 100).toFixed(2)}%;background:${playerColor(own)}"></i><b class="koth-band" style="width:${(100 / 550 * 100).toFixed(2)}%"></b></div></div>`);
    }
  }
  const cd = countdownInfo(v);
  if (cd && has(cd.years)) {
    parts.push(`<div class="vic-row" ${tip(t(VICTORY_LABEL[cd.kind] || 'Victory countdown'), t('Years left until the victory'))}>
      <span class="vic-ico">⏳</span><span>${cd.player ? pn(cd.player) + ' · ' : ''}${esc(t(VICTORY_LABEL[cd.kind] || 'Victory countdown'))}</span>
      <span class="num">${esc(t('{n} years', { n: Math.max(0, Math.ceil(+cd.years || 0)) }))}</span></div>`);
  }
  return parts.join('');
}

function renderVictory(html) {
  const el = hudEl('victory', 'panel hidden');
  const show = settings.disableScoreboard ? html : '';
  el.classList.toggle('hidden', !show);
  if (el._html !== show) { el._html = show; patchHtml(el, show); }
}

// -- team overview -------------------------------------------------------------------

function ensureTrees() { for (const p of players()) if (p.civ != null && !techTrees.has(treeKey(p.civ))) loadTree(p.civ); }

function popCell(s) {
  const limit = S.match.pop_limit || 200;
  const housed = has(s.housed_ms) ? s.housed_ms > 0 : (s.pop >= s.pop_cap && s.pop < limit);
  const timer = has(s.housed_ms) && s.housed_ms > 0 ? `<small class="housed-t" ${tip(t('Housed'), t('Time housed in the current streak'))}>⌂ ${Math.floor(s.housed_ms / 1000)}s</small>`
    : `<small>${s.trade_units ? t('{n} trade', { n: s.trade_units }) : ''}</small>`;
  return `<span class="pop ${housed ? 'housed' : ''}" ${tip(t('Population / cap'), t('Counts units in training, as the game does · flashes while housed'))}>${s.pop}/${s.pop_cap}${timer}</span>`;
}

function ageShield(s, pid) {
  const ageTech = (s.research_active || []).find((a) => AGE_TECHS.includes(a.tech));
  const name = ageName(s.age, pid);
  const pct = ageTech ? Math.round(ageTech.progress * 100) : 0;
  const cur = `<div class="ov-age" data-pid="${pid}" ${tip(name, t('Click: go to the oldest town center'))}><img src="${AGE_ICON(s.age, pid)}" alt="${esc(name)}">${ageTech ? `<div class="age-prog" style="width:${pct}%"></div>` : ''}</div>`;
  if (!ageTech) return `<div class="ov-shield">${cur}</div>`;
  // Researching style: antiquity civs' in-progress age icon is
  // grayscale(80%) at .8 opacity.
  const antiq = civEra((player(pid) || {}).civ) === 'antiquity';
  const left = ageTech.remaining != null ? ` · ${Math.ceil(ageTech.remaining)}s` : '';
  return `<div class="ov-shield">${cur}<div class="ov-next${antiq ? ' antiq' : ''}" ${tip(t('Advancing to: {age}', { age: ageName(s.age + 1, pid) }), `${pct}%${left}`)}><img src="${AGE_ICON(s.age + 1, pid)}" alt=""><i style="height:${pct}%"></i></div></div>`;
}

// panels.js helpers the team board (team-board.js) draws with.
const boardCtx = {
  setHtml: (el, html) => setHtml(el, html), delegate: (...a) => delegate(...a),
  ageShield: (s, pid) => ageShield(s, pid),
  ageRequirements: (s, pid) => ((s.research_active || []).some((a) => AGE_TECHS.includes(a.tech)) ? '' : ageRequirements(s, pid)),
  isDead: (pid) => isDead(pid), fullName: (p) => `${playerName(p.id, true)} · ${civName(p)}`,
  onAge: (pid) => goToBuilding(pid, TOWN_CENTERS), rerender: () => renderOverview(),
};

export function renderOverview() {
  const el = $('overview');
  ensureTrees();
  if (isTwoTeamLayout() && orderedTeams().length === 2) {
    el.classList.add('team-board-host');
    renderTeamBoard(el, orderedTeams(), boardCtx);
    return;
  }
  el.classList.remove('team-board-host');
  delegate(el, 'click', '.ov-age', (d) => {
    if (!el.classList.contains('team-board-host')) goToBuilding(+d.dataset.pid, TOWN_CENTERS);
  });
  const rows = [];
  const resHead = `<div class="ov-res">${RES.map((r) => `<span><img src="/ui/resource_${r}.png" alt="${r}" ${tip(t(r), t('banked / workers'))}></span>`).join('')}<span><img src="/ui/pop.png" alt="pop" ${tip(t('Population / cap'))}></span></div>`;
  for (const team of orderedTeams()) {
    for (const p of team.players) {
      const s = playerStats(p.id);
      if (!s) continue;
      const ageTech = (s.research_active || []).find((a) => AGE_TECHS.includes(a.tech));
      const reqs = ageTech ? '' : ageRequirements(s, p.id);
      const tasks = s.tasks || {};
      const res = RES.map((r) => `<span class="${r}" ${tip(t(r), t('{n} banked, {w} workers', { n: fmtStock(s.resources[r]), w: tasks[r] || 0 }))}>${fmtStock(s.resources[r])}<small>${tasks[r] || 0}</small></span>`).join('');
      rows.push(`<div class="ov-row${isDead(p.id) ? ' dead' : ''}" data-pid="${p.id}">
        <div class="ov-color" style="background:${playerColor(p.id)}"></div>
        ${ageShield(s, p.id)}
        <div><div class="ov-name">${esc(playerName(p.id))}</div>
          <div class="ov-civ"><span ${tip(t('Villagers'), t('Including garrisoned ones, as the game counts them'))}>${t('{n} vil', { n: s.villagers })}</span> · ${t('{n} mil', { n: s.military })} · <span ${tip(t('idle villagers'))} style="color:${s.idle_villagers ? 'var(--bad)' : 'inherit'}">${t('{n} idle', { n: s.idle_villagers })}</span></div>${reqs}</div>
        <div class="ov-res">${res}${popCell(s)}</div>
      </div>`);
    }
  }
  const head = `<div class="ov-row ov-head"><div></div><div></div><div></div>${resHead}</div>`;
  const idle = !S.session || S.session.mode === 'idle';
  setHtml(el, rows.length ? head + rows.join('') : `<span class="hint">${idle ? t('Nothing open') : t('waiting for game data…')}</span>`);
}

// Next-age requirements: food/gold bars and the qualifying buildings as icons
// that light up once built (game rules in games.js).
function ageRequirements(s) {
  const req = AGE_REQ[s.age];
  if (!req) return '';
  const owned = new Set(Object.keys(s.buildings || {}).map(Number));
  let have = req.buildings.filter((b) => owned.has(b)).length;
  if (req.castleCounts && owned.has(req.castleCounts)) have = req.need;
  // Settlement group: one built settlement satisfies the
  // requirement, so every other building pip is drawn filled and the
  // settlement itself is not drawn.
  const settle = (S.catalog.building_groups && S.catalog.building_groups.settlement) || SETTLEMENT_MASTERS;
  if (settle.some((b) => owned.has(b))) { have = req.need; for (const b of req.buildings) owned.add(b); }
  const bar = (v, max, color, res) => max ? `<span class="req" ${tip(t(res), `${Math.round(v)} / ${max}`)}><i style="width:${Math.min(100, 100 * v / max)}%;background:${color}"></i></span>` : '';
  const icons = req.buildings.map((b) => {
    const on = owned.has(b);
    const src = buildingIcon(b);
    const label = tip(buildingName(b), on ? t('built') : t('not built yet'));
    return src ? `<img class="${on ? 'on' : ''}" src="${src}" alt="" ${label}>` : `<b class="${on ? 'on' : ''}" ${label}></b>`;
  }).join('');
  const detail = t('{food} food{gold}, and {n} of these buildings', { food: req.food, gold: req.gold ? `, ${req.gold} ${t('gold')}` : '', n: req.need });
  return `<div class="ov-req" ${tip(t('Next age'), detail)}>${bar(s.resources.food, req.food, 'var(--food)', 'food')}${bar(s.resources.gold, req.gold, 'var(--gold)', 'gold')}<span class="ov-bld">${icons}</span><span class="ov-have ${have >= req.need ? 'ok' : ''}">${Math.min(have, req.need)}/${req.need}</span></div>`;
}

// Cycles through the player's buildings of those types, oldest first.
export function goToBuilding(pid, masters) {
  const rows = currentRows().filter((r) => r[1] === pid && masters.includes(r[2]));
  if (!rows.length) return false;
  rows.sort((a, b) => a[0] - b[0]);
  const key = `goto${pid}${masters[0]}`;
  S[key] = S[key] == null ? 0 : (S[key] + 1) % rows.length;
  const r = rows[S[key] % rows.length];
  centerOn(r[3], r[4]);
  S.selection = new Set([r[0]]);
  return true;
}

// -- static / dynamic techs ------------------------------------------------------------

const LINGER_MS = 5000; // finished dynamic techs stay this long (game time)

function techRows() {
  if (isTwoTeamLayout() && players().length > 2) return bestOfTeams();
  return orderedTeams().flatMap((tm) => tm.players.map((p) => ({ pid: p.id, s: playerStats(p.id), pids: [p.id] })));
}

function bestOfTeams() {
  // In team games each team shows its best: the union of researched techs.
  return orderedTeams().map((tm) => {
    const merged = { research_done: [], research_active: [] };
    for (const p of tm.players) {
      const s = playerStats(p.id);
      if (!s) continue;
      merged.research_done.push(...(s.research_done || []));
      merged.research_active.push(...(s.research_active || []).map((a) => ({ ...a, player: p.id })));
    }
    return { pid: tm.players[0].id, s: merged, pids: tm.players.map((p) => p.id) };
  });
}

function isStatic(tid) { return STATIC_TECHS.some((g) => g.includes(tid)) || PASTURE_TECHS.includes(tid); }

// A civ's castle / imperial unique techs: catalog unique_techs, the tech tree's,
// else the castle techs of its tree that every civ does not share.
function uniqueTechs(civ) {
  const empty = { castle: [], imperial: [] };
  if (civ == null) return empty;
  const cat = S.catalog.unique_techs && (S.catalog.unique_techs[civ] || S.catalog.unique_techs[String(civ)]);
  if (cat) return { castle: cat.castle || [], imperial: cat.imperial || [] };
  const tree = treeNow(civ);
  if (!tree) { loadTree(civ); return empty; }
  if (tree.unique_techs) return { castle: tree.unique_techs.castle || [], imperial: tree.unique_techs.imperial || [] };
  const pick = (age) => (tree.nodes || []).filter((n) => n.kind === 'tech' && n.building === 82 && n.age === age && n.available !== false && !SHARED_CASTLE_TECHS.includes(n.id)).map((n) => n.id);
  return { castle: pick(3), imperial: pick(4) };
}

// Pasture civs (transhumance 1012 available) get pasture instead of farm techs
// in the static row; a team row swaps only when every member is one.
function isPastureCiv(civ) {
  if (civ == null) return false;
  if (Array.isArray(S.catalog.pasture_civs)) return S.catalog.pasture_civs.includes(civ) || S.catalog.pasture_civs.includes(String(civ));
  const tree = treeNow(civ);
  if (!tree) { loadTree(civ); return false; }
  return (tree.nodes || []).some((n) => n.kind === 'tech' && n.id === 1012 && nodeStatus(n) === 'available');
}
function staticGroups(pids) {
  const pasture = pids.length > 0 && pids.every((q) => isPastureCiv((player(q) || {}).civ));
  return STATIC_TECHS.map((g) => (pasture ? g.map((tid) => { const i = FARM_TECHS.indexOf(tid); return i >= 0 ? PASTURE_TECHS[i] : tid; }) : g));
}

function lingering(pids, skip) {
  const out = [];
  for (let i = S.events.length - 1; i >= 0; i--) {
    const e = S.events[i];
    if (e.t > S.t) continue;
    if (e.t < S.t - LINGER_MS) break;
    if (e.kind === 'researched' && pids.includes(e.player) && !isStatic(e.tech) && !skip.has(e.tech)) { out.push(e); skip.add(e.tech); }
  }
  return out;
}

function staticTechCell(tid, pid, done, active, big = false) {
  const a = active.get(tid);
  const cls = done.has(tid) ? 'yes' : a ? 'doing' : 'no';
  const prog = a ? `<div class="prog" style="width:${Math.round(a.progress * 100)}%"></div>` : '';
  const state = done.has(tid) ? t('researched') : a ? t('researching {p}%', { p: Math.round(a.progress * 100) }) : t('not researched');
  const ti = techInfoFor(tid, pid);
  const cost = costText(ti.cost);
  return `<div class="tech ${cls}${big ? ' big' : ''}" data-tech="${tid}" data-pid="${a && a.player ? a.player : pid}" data-building="${a && a.building ? a.building : ''}" ${tip(ti.name, `${state}${cost ? ' · ' + cost : ''} · ${t('click: go to its building')}`)}><img src="${techIconFor(tid, pid)}" alt="">${prog}</div>`;
}

export function renderTechs() {
  renderSlideout();
  const el = $('techs');
  delegate(el, 'click', '.tech', techClick);
  delegate(el, 'contextmenu', '.tech', techClick);
  if (!settings.showStaticTechs) { el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  const rows = [];
  let widest = 0;
  for (const { pid, s, pids } of techRows()) {
    if (!s) continue;
    widest = Math.max(widest, [...staticGroups(pids || [pid]), ...fullTechGroups(pids || [pid])].flat().length);
    const done = new Set(s.research_done || []);
    const active = new Map((s.research_active || []).map((a) => [a.tech, a]));
    const ut = fullTechGroups(pids || [pid]);
    const utSet = new Set(ut.flat());
    const groups = [...staticGroups(pids || [pid]), ...ut].map((g) => g.map((tid) => staticTechCell(tid, pid, done, active)).join('')).join('<div class="tech-gap"></div>');
    const dynActive = (s.research_active || []).filter((a) => !isStatic(a.tech) && !utSet.has(a.tech));
    const dyn = dynActive.map((a) => `<div class="tech doing" data-tech="${a.tech}" data-pid="${a.player || pid}" data-building="${a.building || ''}" ${tip(techInfoFor(a.tech, a.player || pid).name, `${t('researching {p}%', { p: Math.round(a.progress * 100) })} · ${t('click: go to its building')}`)}><img src="${techIconFor(a.tech, a.player || pid)}" alt=""><div class="prog" style="width:${Math.round(a.progress * 100)}%"></div></div>`).join('');
    const linger = lingering(pids, new Set([...dynActive.map((a) => a.tech), ...utSet])).map((e) => `<div class="tech yes linger" data-tech="${e.tech}" data-pid="${e.player}" data-x="${e.x ?? ''}" data-y="${e.y ?? ''}" ${tip(techInfoFor(e.tech, e.player).name, t('researched'))}><img src="${techIconFor(e.tech, e.player)}" alt=""></div>`).join('');
    rows.push(`<div class="tech-row${isDead(pid) ? ' dead' : ''}"><div class="who" style="background:${playerColor(pid)}"></div>${groups}<div class="dyn-techs">${dyn}${linger}</div></div>`);
  }
  // Square icons, as large as fit a row (min 12 px): never squashed into slivers.
  const room = Math.min(window.innerWidth * 0.55, 1100) - 80;
  el.style.setProperty('--tc', `${Math.max(12, Math.min(20, Math.floor(room / Math.max(1, widest + 2)) - 2))}px`);
  setHtml(el, rows.join(''));
}

// "Full static techs" (setting fullStaticTechs, or the skin
// options useFullStaticTechs / useT90Components / useRbw4Components): the
// castle unique tech and the imperial unique tech are appended to the static
// rows, each as a single stage. (The older Vantage meaning, every civ tech, is gone.)
function fullStaticTechsOn() {
  return !!(settings.fullStaticTechs || skinOption('useFullStaticTechs') || skinOption('useT90Components') || skinOption('useRbw4Components'));
}
function fullTechGroups(pids) {
  if (!fullStaticTechsOn() || S.game === 'ror') return [];
  const castle = [], imperial = [];
  for (const q of pids) {
    const ut = uniqueTechs((player(q) || {}).civ);
    for (const x of ut.castle) if (!castle.includes(x)) castle.push(x);
    for (const x of ut.imperial) if (!imperial.includes(x)) imperial.push(x);
  }
  return [castle, imperial].filter((g) => g.length);
}

function techClick(d, ev) {
  ev.preventDefault();
  const xy = d.dataset.x ? [+d.dataset.x, +d.dataset.y] : null;
  goToTech(+d.dataset.pid, +d.dataset.tech, +d.dataset.building || 0, xy);
}

// Select and centre the building that researches (or researched) a tech.
function goToTech(pid, tid, bid, xy) {
  const rows = currentRows();
  const pick = (r) => { centerOn(r[3], r[4]); S.selection = new Set([r[0]]); };
  if (bid) { const r = rows.find((x) => x[0] === bid); if (r) return pick(r); }
  const team = teamOf(pid);
  const pids = team ? [pid, ...team.players.map((p) => p.id).filter((q) => q !== pid)] : [pid];
  for (const q of pids) {
    const a = ((playerStats(q) || {}).research_active || []).find((x) => x.tech === tid && x.building);
    const r = a && rows.find((x) => x[0] === a.building);
    if (r) return pick(r);
  }
  if (xy && Number.isFinite(xy[0])) { centerOn(xy[0], xy[1]); return null; }
  const m = techInfo(tid).building;
  if (m == null || m < 0) return null;
  const masters = TOWN_CENTERS.includes(m) ? TOWN_CENTERS : (Object.values(GOTO_BUILDINGS).find((l) => l.includes(m)) || [m]);
  for (const q of pids) if (goToBuilding(q, masters)) return null;
  return null;
}

// -- slide-out panels: static techs (Alt+P) and graph (Ctrl+Alt+P) ---------------------------

const GRAPH_KEYS = [
  ['score', 'Score'], ['military', 'Military units'], ['villagers', 'Villagers'], ['army_value', 'Army value'],
  ['col_total', 'Resources collected'], ['apm', 'APM'], ['efficiency', 'Worker efficiency'], ['explored', 'Explored %'],
];
let graphKey = 'score';
let overlaysMod = null;
let overlaysLoading = false;
function overlaysModule() {
  // Loaded lazily: overlays.js imports this module, so a static import would be circular.
  if (!overlaysMod && !overlaysLoading) {
    overlaysLoading = true;
    import('./overlays.js').then((m) => { overlaysMod = m; }).catch(() => {});
  }
  return overlaysMod;
}

function renderSlideout() {
  const el = hudEl('slideout', 'panel hidden');
  const mode = S.slideout === 'techs' || S.slideout === 'graph' ? S.slideout : null;
  el.classList.toggle('hidden', !mode);
  if (!mode) { el.dataset.mode = ''; return; }
  delegate(el, 'click', '.tech', techClick);
  delegate(el, 'contextmenu', '.tech', techClick);
  if (mode === 'techs') {
    el.dataset.mode = 'techs';
    const rows = orderedTeams().flatMap((tm) => tm.players).map((p) => {
      const s = playerStats(p.id);
      if (!s) return '';
      const done = new Set(s.research_done || []);
      const active = new Map((s.research_active || []).map((a) => [a.tech, a]));
      return `<div class="so-row"><div class="so-name" style="border-color:${playerColor(p.id)}">${esc(playerName(p.id))}</div>${[...staticGroups([p.id]), ...fullTechGroups([p.id])].map((g) => `<div class="so-group">${g.map((tid) => staticTechCell(tid, p.id, done, active, true)).join('')}</div>`).join('')}</div>`;
    }).join('');
    const html = `<div class="so-head"><span class="title">${t('Technologies')}</span><span class="hint">Alt+P</span></div>${rows}`;
    if (el._html !== html) { el._html = html; patchHtml(el, html); }
    return;
  }
  if (el.dataset.mode !== 'graph') {
    el.dataset.mode = 'graph'; el._html = '';
    el.innerHTML = `<div class="so-head"><span class="title">${t('Graph')}</span><select id="so-key">${GRAPH_KEYS.map(([k, l]) => `<option value="${k}">${t(l)}</option>`).join('')}</select><span class="hint">Ctrl+Alt+P</span></div><canvas id="so-canvas"></canvas><div class="so-legend" id="so-legend"></div>`;
    const sel = $('so-key');
    sel.value = graphKey;
    sel.addEventListener('change', () => { graphKey = sel.value; });
    sel.addEventListener('keydown', (e) => e.stopPropagation());
  }
  drawGraph($('so-canvas'));
}

function drawGraph(canvas) {
  // OVL's drawChart(canvas, opts, seek) when available; the built-in chart otherwise.
  const m = overlaysModule();
  let drawn = false;
  if (m && typeof m.drawChart === 'function' && m.drawChart.length >= 2) {
    try { drawn = !!m.drawChart(canvas, { key: graphKey, compact: true, until: S.t, type: 'line', transform: 'actual', techMarks: false, ecoTechs: false, milTechs: false }); } catch (e) { drawn = false; }
  }
  if (!drawn) miniChart(canvas, graphKey);
  graphLegend(graphKey);
}

function graphLegend(key) {
  const legend = $('so-legend');
  if (!legend) return;
  const html = players().map((p) => { const v = lastSeries(p.id, key); return `<span style="color:${playerTextColor(p.id)}">${esc(playerName(p.id))} ${v != null ? fmtNum(+v) : '–'}</span>`; }).join(' · ');
  if (legend._html !== html) { legend._html = html; patchHtml(legend, html); }
}

// A compact line chart of one series per player, up to the viewed time.
function miniChart(canvas, key) {
  const r = canvas.getBoundingClientRect();
  if (!r.width) return;
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(r.width * dpr)) { canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr); }
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = r.width, H = r.height, L = 34, B = 14;
  g.clearRect(0, 0, W, H);
  const ps = players();
  const data = ps.map((p) => ((S.series && S.series[p.id]) || []).filter((x) => x.t <= S.t && x[key] != null));
  const t1 = Math.max(S.t, 1), t0 = S.start || 0;
  let max = 1;
  for (const rows of data) for (const x of rows) max = Math.max(max, +x[key] || 0);
  const xOf = (tt) => L + ((tt - t0) / Math.max(1, t1 - t0)) * (W - L - 4);
  const yOf = (v) => 4 + (1 - v / max) * (H - B - 8);
  g.strokeStyle = 'rgba(255,255,255,.12)'; g.fillStyle = 'rgba(255,255,255,.55)'; g.font = '10px sans-serif';
  for (const f of [0, 0.5, 1]) { const y = yOf(max * f); g.beginPath(); g.moveTo(L, y); g.lineTo(W - 4, y); g.stroke(); g.fillText(fmtNum(max * f), 2, y + 3); }
  g.fillText(fmtTime(t0), L, H - 2); g.fillText(fmtTime(t1), W - 40, H - 2);
  data.forEach((rows, i) => {
    if (!rows.length) return;
    g.strokeStyle = playerColor(ps[i].id); g.lineWidth = 1.6; g.beginPath();
    rows.forEach((x, k) => { const px = xOf(x.t), py = yOf(+x[key] || 0); if (k) g.lineTo(px, py); else g.moveTo(px, py); });
    g.stroke();
  });
}

// -- production & composition -------------------------------------------------------------

// Unit lines (the game's dat/unitlines.json): composition,
// production queues and click-to-select group by catalog `line`; fishing ships
// share identity 13. Without line data every master is its own group.
export function lineOf(mid) {
  const u = unitInfo(mid);
  // Every villager role (lumberjack, farmer, miner...) is one "Villager" group.
  if (u.cls === 4 && u.kind === 'unit') return 'villager';
  if (u.line) return String(u.line);
  return `m${has(u.identity) ? u.identity : mid}`;
}
// Groups {mid: n} by line. The icon/name is the most numerous actual variant
// (villagers keep the line's reference unit).
function byLine(units, owner) {
  const groups = new Map();
  for (const [k, n] of Object.entries(units)) {
    const mid = +k;
    if (unitInfo(mid).kind !== 'unit' || !n) continue;
    const key = lineOf(mid);
    const g = groups.get(key) || { key, n: 0, variants: new Map() };
    g.n += n;
    g.variants.set(mid, (g.variants.get(mid) || 0) + n);
    groups.set(key, g);
  }
  for (const g of groups.values()) {
    const top = [...g.variants.entries()].sort((a, b) => b[1] - a[1])[0][0];
    const line = (S.catalog.unit_lines || {})[g.key];
    const ref = g.key === 'villager' ? 83 : line && Array.isArray(line.ids) && line.ids.length ? line.ids[0] : top;
    g.mid = unitInfo(top).cls === 4 && unitInfo(ref).icon >= 0 ? ref : top;
    g.owner = owner;
  }
  return [...groups.values()].sort((a, b) => b.n - a.n);
}

function compIcons(units, pid, team) {
  // Names and icons as this player has them (Cavalier, not Knight); a team total uses
  // the base names.
  const own = pid > 0 ? pid : undefined;
  return byLine(units, own).map((g) => {
    const detail = g.variants.size > 1 ? [...g.variants.entries()].map(([m, n]) => `${unitInfo(m, own).name} ${n}`).join(', ') + ' · ' : '';
    const name = g.key === 'villager' ? t('Villagers') : unitInfo(g.mid, own).name;
    return `<div class="icon-count" data-line="${esc(g.key)}" ${team ? `data-team="${esc(team)}"` : `data-pid="${pid}"`} ${tip(name, detail + t('click: select them'))}><img src="${unitIcon(g.mid, own)}" alt=""><b>${g.n}</b></div>`;
  }).join('');
}

// Production grouped into queue entries: one icon per unit line or
// technology being made, with how many buildings make it; clicking cycles
// through those buildings.
function productionHtml(prodList, pid) {
  const groups = new Map();
  for (const b of prodList) {
    const c = b.current || {};
    const key = c.tech != null ? `t${c.tech}` : c.unit != null ? lineOf(c.unit) : `b${b.master}`;
    const g = groups.get(key) || { key, c, items: [] };
    g.items.push(b);
    groups.set(key, g);
  }
  return [...groups.values()].map((g) => {
    const c = g.c;
    const icon = c.tech != null ? techIconFor(c.tech, pid) : c.unit != null ? unitIcon(c.unit, pid) : unitIcon(g.items[0].master, pid);
    const name = c.tech != null ? techInfoFor(c.tech, pid).name : c.unit != null ? unitInfo(c.unit, pid).name : unitInfo(g.items[0].master, pid).name;
    // Only this group's entries: a town centre's queue also holds the villagers
    // after its age-up. The game's queue lists the item being made first.
    const same = (q) => (c.tech != null ? q.tech === c.tech : c.unit != null ? q.unit >= 0 && lineOf(q.unit) === g.key : false);
    const queued = g.items.reduce((n, b) => n + Math.max(1, (b.queue || []).reduce((m, q) => m + (same(q) ? q.count : 0), 0)), 0);
    const progress = Math.max(...g.items.map((b) => (b.current || {}).progress || 0));
    const rem = g.items.map((b) => (b.current || {}).remaining).filter(has);
    const where = g.items.map((b) => `${b.x},${b.y}`).join(';');
    // The badge is always the number in production (queued, the one being made
    // included); how many buildings make it is in the tooltip.
    const count = queued > 1 ? queued : '';
    const detail = `${t('{n} queued', { n: queued })} · ${g.items.length > 1 ? t('{n} buildings', { n: g.items.length }) + ' · ' : ''}${rem.length ? `${Math.ceil(Math.min(...rem))}s · ` : ''}${t('click: go to the building')}`;
    return `<div class="icon-count" data-ui-key="queue-${pid}-${esc(g.key)}" data-buildings="${g.items.map((b) => b.id).join(',')}" data-where="${where}" ${tip(`${unitInfo(g.items[0].master, pid).name}: ${name}`, detail)}><img src="${icon}" alt=""><b>${count}</b><div class="prog" style="width:${Math.round(progress * 100)}%"></div></div>`;
  }).join('');
}

export function renderProduction() {
  const el = $('production');
  delegate(el, 'click', '.icon-count', (d) => {
    if (d.dataset.where) {
      const spots = d.dataset.where.split(';').map((xy) => xy.split(',').map(Number));
      d._i = ((d._i ?? -1) + 1) % spots.length;
      const key = d.dataset.where;
      S._prodCycle = S._prodCycle && S._prodCycle.key === key ? { key, i: (S._prodCycle.i + 1) % spots.length } : { key, i: 0 };
      const [x, y] = spots[S._prodCycle.i];
      centerOn(x, y);
      const bid = d.dataset.buildings?.split(',').map(Number)[S._prodCycle.i];
      if (bid != null) S.selection = new Set([bid]);
      return;
    }
    const line = d.dataset.line;
    let owners;
    if (d.dataset.team != null) { const tm = teams().find((x) => String(x.key) === d.dataset.team); owners = new Set(tm ? tm.players.map((p) => p.id) : []); }
    else owners = new Set([+d.dataset.pid]);
    S.selection = new Set(currentRows().filter((r) => owners.has(r[1]) && lineOf(r[2]) === line).map((r) => r[0]));
  });
  if (!settings.showProduction) { el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  const rows = [];
  for (const team of orderedTeams()) {
    const total = {};
    for (const p of team.players) {
      const s = playerStats(p.id);
      if (!s) continue;
      for (const [mid, n] of Object.entries(s.units || {})) total[mid] = (total[mid] || 0) + n;
      rows.push(`<div class="prod-row${isDead(p.id) ? ' dead' : ''}" data-ui-key="player-${p.id}"><span class="dot" style="background:${playerColor(p.id)}"></span>${compIcons(s.units || {}, p.id)}<span class="tech-gap"></span>${productionHtml(s.production || [], p.id)}</div>`);
    }
    if (team.players.length > 1 && Object.keys(total).length) {
      rows.push(`<div class="prod-row team-total" data-ui-key="team-${esc(team.key)}"><span class="tt-label" ${tip(t('Team composition'), teamName(team))}>Σ</span>${compIcons(total, 0, String(team.key))}</div>`);
    }
  }
  setHtml(el, rows.join(''));
}

// -- dashboard --------------------------------------------------------------------------

const secs = (v) => (v == null ? null : fmtTime(v * 1000));
// Villager-seconds (summed over every villager), shown as villager-minutes: as a
// clock time a 40-minute game would read "24:42:59" of gathering.
const vilMin = (v) => (v == null ? null : `${fmtNum(Math.round(v / 60))} ${t('vil·min')}`);
function effAll(s, keys) {
  const a = s.efficiency && s.efficiency.all;
  return a ? keys.reduce((x, k) => x + (a[k] || 0), 0) : null;
}
const effTotal = (s, k, keys) => (s.efficiency_all && has(s.efficiency_all[k]) ? s.efficiency_all[k] : effAll(s, keys));

// h: header (short), tip: what it measures. A value of null renders as '–'.
const COL = {
  food: { h: 'Food', tip: 'Food in stockpile', v: (s) => Math.floor(s.resources.food) },
  wood: { h: 'Wood', tip: 'Wood in stockpile', v: (s) => Math.floor(s.resources.wood) },
  gold: { h: 'Gold', tip: 'Gold in stockpile', v: (s) => Math.floor(s.resources.gold) },
  stone: { h: 'Stone', tip: 'Stone in stockpile', v: (s) => Math.floor(s.resources.stone) },
  wFood: { h: 'F wkr', tip: 'Workers on food', v: (s) => s.tasks.food || 0 },
  wWood: { h: 'W wkr', tip: 'Workers on wood', v: (s) => s.tasks.wood || 0 },
  wGold: { h: 'G wkr', tip: 'Workers on gold', v: (s) => s.tasks.gold || 0 },
  wStone: { h: 'S wkr', tip: 'Workers on stone', v: (s) => s.tasks.stone || 0 },
  build: { h: 'Build', tip: 'Villagers building or repairing', v: (s) => (s.tasks.build || 0) + (s.tasks.repair || 0) },
  idle: { h: 'Idle', tip: 'Idle villagers', v: (s) => s.idle_villagers },
  pop: { h: 'Pop/Cap', tip: 'Population and population cap', v: (s) => `${s.pop}/${s.pop_cap}` },
  popOnly: { h: 'Pop', tip: 'Population', v: (s) => s.pop },
  vils: { h: 'Vils', tip: 'Villagers', v: (s) => s.villagers },
  eco: { h: 'Eco', tip: 'Economy units: villagers, fishing ships and trade units', v: (s) => s.eco_units },
  mil: { h: 'Mil', tip: 'Military units', v: (s) => s.military },
  milValue: { h: 'Mil value', tip: 'Resources spent on the living army', v: (s) => s.army_value },
  milGold: { h: '% gold', tip: 'Share of the army value paid in gold', v: (s) => s.army_value ? Math.round(100 * s.army_gold / s.army_value) + '%' : '–' },
  peakArmy: { h: 'Peak army', tip: 'Highest army value so far', v: (s) => s.peak_army_value },
  kd: { h: 'K / D', tip: 'Units killed / units lost (losses include those to animals and other non-player causes)', v: (s) => `${s.kills} / ${s.deaths}` },
  ecoKills: { h: 'Eco kills', tip: 'Enemy villagers, fishing ships and trade units killed', v: (s) => s.eco_kills },
  ecoDeaths: { h: 'Eco deaths', tip: 'Own villagers, fishing ships and trade units lost', v: (s) => s.eco_deaths },
  ecoKD: { h: 'Eco K / D', tip: 'Economy units killed / lost', v: (s) => (has(s.eco_kills) ? `${s.eco_kills} / ${s.eco_deaths ?? 0}` : null) },
  killsTotal: { h: 'Total kills', tip: 'Units and buildings destroyed', v: (s) => s.kills_total },
  deathsTotal: { h: 'Total deaths', tip: 'Units and buildings lost', v: (s) => s.deaths_total },
  razings: { h: 'Razed', tip: 'Buildings razed / buildings lost', v: (s) => `${s.razings} / ${s.buildings_lost}` },
  tc: { h: 'TC', tip: 'Town centers', v: (s) => s.town_centers },
  castles: { h: 'Castles', tip: 'Castles', v: (s) => s.castles },
  tcCastle: { h: 'TC/Castle', tip: 'Town centers / castles', v: (s) => `${s.town_centers ?? 0}/${s.castles ?? 0}` },
  relics: { h: 'Relics', tip: 'Relics held', v: (s) => s.relics },
  trade: { h: 'Trade', tip: 'Trade units', v: (s) => s.trade_units },
  tradeWorkshops: { h: 'Workshops', tip: 'Trade workshops', v: (s) => s.trade_workshops },
  colF: { h: 'Col F', tip: 'Food collected', v: (s) => s.collected.food },
  colW: { h: 'Col W', tip: 'Wood collected', v: (s) => s.collected.wood },
  colG: { h: 'Col G', tip: 'Gold collected', v: (s) => s.collected.gold },
  colS: { h: 'Col S', tip: 'Stone collected', v: (s) => s.collected.stone },
  colT: { h: 'Collected', tip: 'Resources collected', v: (s) => s.collected.total },
  farm: { h: 'Farm', tip: 'Villagers farming', v: (s) => (s.food_tasks || {}).farm || 0 },
  sheep: { h: 'Sheep', tip: 'Villagers on sheep', v: (s) => (s.food_tasks || {}).sheep || 0 },
  hunt: { h: 'Hunt', tip: 'Villagers hunting', v: (s) => (s.food_tasks || {}).hunt || 0 },
  berries: { h: 'Berries', tip: 'Villagers on berries', v: (s) => (s.food_tasks || {}).berries || 0 },
  fish: { h: 'Fish', tip: 'Villagers fishing', v: (s) => (s.food_tasks || {}).fish || 0 },
  idleTime: { h: 'Idle time', tip: 'Villager-minutes idle (villagers × minutes), whole game', v: (s) => vilMin(effTotal(s, 'idle', ['idle'])) },
  gatherTime: { h: 'Gather time', tip: 'Villager-minutes spent gathering (villagers × minutes), whole game', v: (s) => vilMin(effTotal(s, 'gather', ['gather_food', 'gather_wood', 'gather_gold', 'gather_stone'])) },
  moveTime: { h: 'Move time', tip: 'Villager-minutes spent moving (villagers × minutes), whole game', v: (s) => vilMin(effTotal(s, 'move', ['moving'])) },
  buildTime: { h: 'Build time', tip: 'Villager-minutes spent building and repairing (villagers × minutes), whole game', v: (s) => vilMin(effTotal(s, 'build', ['building', 'repairing'])) },
  idleEcoTime: { h: 'Idle eco', tip: 'Villager-minutes idle (villagers × minutes), whole game', v: (s) => vilMin(effTotal(s, 'idle', ['idle'])) },
  apm: { h: 'APM', tip: 'Actions per minute (last game minute)', v: (s, pid) => ((S.view.apm || {})[pid] || {}).total || 0 },
  apmEco: { h: 'eAPM eco', tip: 'Effective economy actions per minute (repeated commands removed)', v: (s, pid) => { const a = (S.view.apm || {})[pid] || {}; return a.effective_eco ?? a.eco ?? 0; } },
  apmMil: { h: 'eAPM mil', tip: 'Effective military actions per minute (repeated commands removed)', v: (s, pid) => { const a = (S.view.apm || {})[pid] || {}; return a.effective_military ?? a.military ?? 0; } },
  apmPeak: { h: 'APM peak', tip: 'Highest APM so far', v: (s) => s.apm_peak },
  apmAvg: { h: 'APM avg', tip: 'Average APM so far', v: (s) => (has(s.apm_avg) ? Math.round(s.apm_avg) : null) },
  eapm: { h: 'eAPM', tip: 'Effective actions per minute (repeated commands removed)', v: (s) => s.eapm },
  d3Agg: { h: 'Truce F+W', tip: 'Food and wood gathered during the truce (Return of Rome D3 mode)', v: (s) => s.d3_resource_aggregate },
  killValue: { h: 'Kill value', tip: 'Value of enemy objects destroyed', v: (s) => s.kill_value },
  valueSpent: { h: 'Spent', tip: 'Resources spent on units, buildings and technologies', v: (s) => s.value_spent },
  techs: { h: 'Techs', tip: 'Technologies researched', v: (s) => s.techs_researched },
  relicGold: { h: 'Relic gold', tip: 'Gold generated by relics', v: (s) => s.relic_gold },
  explored: { h: 'Explored', tip: 'Share of the map explored', v: (s, pid) => (lastSeries(pid, 'explored') ?? '–') + '%' },
  eff: { h: 'Efficiency', tip: 'Worker efficiency: productive share of villager time, whole game', v: (s) => (s.efficiency ? s.efficiency.pct : 0) + '%' },
  effLm: { h: 'Eff. LM', tip: 'Worker efficiency over the last minute', v: (s) => (s.efficiency ? s.efficiency.pct_lm : 0) + '%' },
  gatherLm: { h: 'Gather LM', tip: 'Share of villager time gathering, last minute', v: (s) => lmSum(s, ['gather_food', 'gather_wood', 'gather_gold', 'gather_stone']) },
  moveLm: { h: 'Move LM', tip: 'Share of villager time moving, last minute', v: (s) => lmSum(s, ['moving']) },
  buildLm: { h: 'Build LM', tip: 'Share of villager time building or repairing, last minute', v: (s) => lmSum(s, ['building', 'repairing']) },
  idleLm: { h: 'Idle LM', tip: 'Share of villager time idle, last minute', v: (s) => lmSum(s, ['idle']) },
  gFoodLm: { h: 'F time LM', tip: 'Share of villager time on food, last minute', v: (s) => lmSum(s, ['gather_food']) },
  gWoodLm: { h: 'W time LM', tip: 'Share of villager time on wood, last minute', v: (s) => lmSum(s, ['gather_wood']) },
  gGoldLm: { h: 'G time LM', tip: 'Share of villager time on gold, last minute', v: (s) => lmSum(s, ['gather_gold']) },
  gStoneLm: { h: 'S time LM', tip: 'Share of villager time on stone, last minute', v: (s) => lmSum(s, ['gather_stone']) },
  tcIdle: { h: 'Idle TC', tip: 'Time with a town center idle (producing nothing), whole game', v: (s) => fmtTime((s.tc_idle_seconds || 0) * 1000) },
  housed: { h: 'Housed', tip: 'Time spent housed', v: (s) => fmtTime((s.housed_seconds || 0) * 1000) },
  // "Idle TC / Housed Time": idle TC time with the housed time on a second line.
  idleTcHoused: { h: 'Idle TC / Housed', abbr: 'Idl TC/Hsd', tip: 'Town center idle time, and below it the time spent housed', icons: ['tc', 'pop'],
    v: (s) => { const a = Array.isArray(s.idle_tc_housed) ? s.idle_tc_housed : [s.tc_idle_seconds || 0, s.housed_seconds || 0];
      return { html: `${esc(fmtTime((a[0] || 0) * 1000))}<small class="dash-sub">${esc(fmtTime((a[1] || 0) * 1000))}</small>` }; } },
  tribute: { h: 'Tribute in', tip: 'Tribute received', v: (s) => s.tribute_received },
  tributeSent: { h: 'Tribute out', tip: 'Tribute sent', v: (s) => s.tribute_sent },
  marketBought: { h: 'Bought', tip: 'Resources bought at the market', v: (s) => s.market_bought },
  marketSold: { h: 'Sold', tip: 'Resources sold at the market', v: (s) => s.market_sold },
  conversions: { h: 'Conversions', tip: 'Enemy units converted', v: (s) => s.conversions },
  desertions: { h: 'Desertions', tip: 'Own units lost to conversion', v: (s) => s.desertions },
  score: { h: 'Score', tip: 'Game score', v: (s, pid) => playerScore(+pid) },
};

// Villager-seconds over the last game minute -> "%"-style share of the window.
function lmSum(s, keys) {
  const lm = (s.efficiency && s.efficiency.last_minute) || {};
  const total = Object.entries(lm).filter(([k]) => k !== 'garrisoned').reduce((a, [, v]) => a + v, 0) || 1;
  return Math.round(100 * keys.reduce((a, k) => a + (lm[k] || 0), 0) / total) + '%';
}

// T90 components (skin option useT90Components): the 1v1 dashboard becomes two pages
// with fixed short labels. These columns reuse Vantage's values under the
// T90 labels and are never offered by the custom-page picker.
const T90_COLS = {
  t90EcoKd: ['ecoKD', 'Eco K/D'], t90Kd: ['kd', 'Kills Deaths'], t90TcIdle: ['tcIdle', 'TC Idle'],
  t90EcoIdle: ['idleEcoTime', 'Eco Idle'], t90Relics: ['relics', 'Relics'], t90RelicGold: ['relicGold', 'Rel Gold'],
  t90ResColl: ['colT', 'Res Coll'], t90ValueGold: ['milGold', 'Value%Gold'], t90Gather: ['gatherLm', 'Gth Eco'],
  t90WeLm: ['effLm', 'WE LM %'], t90WeAll: ['eff', 'WE All %'], t90ValueDestroyed: ['killValue', 'Value destroyed'],
};
for (const [k, [src, abbr]] of Object.entries(T90_COLS)) COL[k] = { ...COL[src], abbr };
COL.t90ConvDes = { h: 'Conversions / desertions', abbr: 'Conv / Des', tip: 'Enemy units converted / own units lost to conversion',
  v: (s) => `${s.conversions ?? 0} / ${s.desertions ?? 0}` };

export const DASH_COLUMNS = COL;
// Columns the custom-page picker never offers.
export const DASH_HIDDEN_COLUMNS = [...Object.keys(T90_COLS), 't90ConvDes'];

// Skin header icons (`placeholderIcon`): drawn only when the active
// skin provides every named asset, otherwise the text label stays.
const COL_ASSETS = {
  wFood: ['colWorkersFood'], wWood: ['colWorkersWood'], wGold: ['colWorkersGold'], wStone: ['colWorkersStone'],
  apmEco: ['colEcoEapgm'], apmMil: ['colMilitaryEapgm'], eapm: ['colTotalEapgm'], moveLm: ['colMovingEco'], buildLm: ['colBuildingRepairEco'],
  gatherLm: ['colGatheringEco'], eff: ['colWorkerEfficiency'], eco: ['colEconomyCount'], apm: ['colApm'],
};
function headerIcons(c) {
  const m = COL[c];
  if (m.icons) {
    // Always-on icon kinds (never for abbreviated headers).
    return m.icons.map((k) => (k === 'pop' ? '<img class="dash-ico" src="/ui/pop.png" alt="">' : `<img class="dash-ico" src="${buildingIcon(109)}" alt="">`)).join('');
  }
  const need = COL_ASSETS[c];
  const urls = need ? need.map((k) => skinAsset(k)) : [];
  return need && urls.every(Boolean) ? urls.map((u) => `<img class="dash-ico" src="${esc(u)}" alt="">`).join('') : '';
}

// Mirroring defaults on unless every column is a stockpile column.
const STOCKPILE_KEYS = new Set(['food', 'wood', 'gold', 'stone']);
export function defaultMirror(columns) { return !(columns || []).every((c) => STOCKPILE_KEYS.has(c)); }
// 1v1 pages swap Idle eco / worker efficiency (last minute) for combined two-value variants.
const COMBINED = { idleLm: 'effLm', effLm: 'idleLm' };

const OVERVIEW_COLS = ['wFood', 'wWood', 'wGold', 'wStone', 'build', 'idle', 'pop', 'mil', 'milValue', 'kd', 'tc', 'idleTcHoused'];
const BASE_PAGES = [
  // 1v1 (nonOppositional)
  { key: 'overview', title: 'Overview', cols: OVERVIEW_COLS },
  { key: 'apm', title: 'APM', cols: ['apm', 'apmEco', 'apmMil', 'apmPeak', 'apmAvg', 'eapm', 'techs', 'explored'] },
  { key: 'ecoActivity', title: 'Eco activity', cols: ['gatherLm', 'moveLm', 'buildLm', 'idleLm', 'gatherTime', 'moveTime', 'buildTime', 'idleEcoTime', 'eff', 'effLm'] },
  // T90 variants of the two 1v1 pages (APM page dropped)
  { key: 'overviewT90', title: 'Overview', cols: ['t90EcoKd', 't90Kd', 't90TcIdle', 't90EcoIdle', 't90Relics', 't90RelicGold', 't90ResColl', 't90ValueGold'] },
  { key: 'ecoActivityT90', title: 'Eco activity', cols: ['t90Gather', 't90WeLm', 't90WeAll', 't90ConvDes', 't90ValueDestroyed'] },
  // team games (oppositional)
  { key: 'overviewSmall', title: 'Overview', cols: ['vils', 'idle', 'popOnly', 'mil', 'milValue', 'kd', 'tcCastle'] },
  { key: 'overviewEcoLosses', title: 'Overview & eco losses', cols: ['vils', 'idle', 'pop', 'mil', 'milValue', 'kd', 'ecoKills', 'ecoDeaths', 'idleTcHoused', 'tcCastle'] },
  { key: 'ecoInfo', title: 'Economy', cols: ['vils', 'farm', 'sheep', 'hunt', 'berries', 'fish', 'wWood', 'wGold', 'wStone', 'idle', 'idleTime', 'trade', 'tradeWorkshops'] },
  { key: 'stockpiles', title: 'Stockpiles', cols: ['food', 'wood', 'gold', 'stone', 'colF', 'colW', 'colG', 'colS', 'colT'] },
  { key: 'apmPaired', title: 'APM', cols: ['apm', 'apmEco', 'apmMil', 'apmPeak', 'apmAvg', 'eapm'], paired: true },
  { key: 'workerEfficiencyOverall', title: 'Worker efficiency', cols: ['eff', 'effLm', 'gatherTime', 'moveTime', 'buildTime', 'idleEcoTime', 'tcIdle', 'housed'] },
  { key: 'workerEfficiencyBreakdown', title: 'Worker efficiency breakdown', cols: ['gatherLm', 'moveLm', 'buildLm', 'idleLm', 'gFoodLm', 'gWoodLm', 'gGoldLm', 'gStoneLm'] },
  // Further pages (shown after the standard ones)
  { key: 'military', title: 'Military', cols: ['mil', 'milValue', 'milGold', 'peakArmy', 'kd', 'killsTotal', 'deathsTotal', 'killValue', 'razings', 'castles', 'relics', 'relicGold'] },
  { key: 'workerEfficiency', title: 'Worker efficiency', cols: ['eff', 'effLm', 'gatherLm', 'moveLm', 'buildLm', 'idleLm', 'gFoodLm', 'gWoodLm', 'gGoldLm', 'gStoneLm', 'tcIdle', 'housed'] },
  { key: 'trade', title: 'Trade & tribute', cols: ['trade', 'tradeWorkshops', 'tribute', 'tributeSent', 'marketBought', 'marketSold', 'valueSpent', 'conversions', 'desertions'] },
  // battle royale
  { key: 'top4', title: 'Top 4', cols: ['score', 'vils', 'mil', 'milValue', 'kd', 'killsTotal'], top: 4 },
  { key: 'top8', title: 'Top 8', cols: ['score', 'vils', 'mil', 'milValue', 'kd'], top: 8 },
  { key: 'apmBr', title: 'APM', cols: ['apm', 'apmPeak', 'apmAvg', 'eapm'] },
  // mini FFA (mini dashboard in FFA games)
  { key: 'militaryMiniFfa', title: 'Military', cols: ['mil', 'milValue', 'kd'] },
  { key: 'ecoMiniFfa', title: 'Economy', cols: ['vils', 'idle', 'colT'] },
  { key: 'stockpilesAndWorkersMiniFfa', title: 'Stockpiles & workers', cols: ['food', 'wood', 'gold', 'stone', 'vils'] },
  // Return of Rome (pompeii)
  { key: 'default', title: 'Overview', cols: ['wFood', 'wWood', 'wGold', 'wStone', 'build', 'idle', 'pop', 'mil', 'milValue', 'kd', 'tc', 'd3Agg'] },
  { key: 'economyEfficiency', title: 'Economy efficiency', cols: ['eff', 'effLm', 'gatherLm', 'moveLm', 'buildLm', 'idleLm', 'gatherTime', 'tcIdle', 'housed'] },
];
// FFA variants of the team pages: the same columns, rows ranked by score.
const FFA_OF = ['overviewSmall', 'overviewEcoLosses', 'ecoInfo', 'stockpiles', 'workerEfficiencyOverall', 'workerEfficiencyBreakdown'];
export const DASH_PAGES = [
  ...BASE_PAGES,
  ...FFA_OF.map((k) => { const p = BASE_PAGES.find((x) => x.key === k); return { ...p, key: `${k}Ffa`, title: p.title }; }),
  { key: 'apmFfa', title: 'APM', cols: ['apm', 'apmEco', 'apmMil', 'apmPeak', 'apmAvg', 'eapm'] },
];
export const DASH_LAYOUTS = {
  nonOppositional: ['overview', 'apm', 'ecoActivity', 'ecoInfo', 'stockpiles', 'military', 'trade'],
  oppositional: ['overviewSmall', 'overviewEcoLosses', 'ecoInfo', 'stockpiles', 'apmPaired', 'workerEfficiencyOverall', 'workerEfficiencyBreakdown', 'military', 'trade'],
  ffa: ['overviewSmallFfa', 'overviewEcoLossesFfa', 'ecoInfoFfa', 'stockpilesFfa', 'apmFfa', 'workerEfficiencyOverallFfa', 'workerEfficiencyBreakdownFfa', 'military'],
  battleRoyale: ['top4', 'top8', 'stockpiles', 'military', 'apmBr'],
  miniFfa: ['militaryMiniFfa', 'ecoMiniFfa', 'stockpilesAndWorkersMiniFfa'],
  pompeii: ['default', 'economyEfficiency', 'apm'],
};

// The dashboard layout (page-set key) for the game being watched.
export function dashLayout() {
  const kind = layoutKind();
  if (S.game === 'ror') return 'pompeii';
  const ffaLike = kind === 'ffa' || kind === 'community' || kind === 'battleRoyale';
  // The mini dashboard applies only inside the community FFA layout.
  if (kind === 'community' && settings.useMiniDashboard) return 'miniFfa';
  if (kind === 'battleRoyale') return 'battleRoyale';
  if (ffaLike) return 'ffa';
  return players().length <= 2 ? 'nonOppositional' : 'oppositional';
}

// Custom pages (settings.customDashboardConfig[layout] = [{id, columns, mirror?}],
// written by the dashboard editor) replace the built-in ones for the three
// editable layouts when the list is non-empty.
const EDITABLE = ['nonOppositional', 'oppositional', 'ffa'];
export function customPages(layout) {
  const all = settings.customDashboardConfig;
  const list = all && typeof all === 'object' ? all[layout] : null;
  if (!EDITABLE.includes(layout) || !Array.isArray(list)) return [];
  return list.filter((p) => p && p.id != null && Array.isArray(p.columns))
    .map((p, i) => ({ key: String(p.id), title: 'Page', num: i + 1, cols: p.columns, mirror: p.mirror, custom: true }));
}
export function builtinPages(layout) {
  if (layout === 'nonOppositional' && skinOption('useT90Components')) {
    return ['overviewT90', 'ecoActivityT90'].map((k) => DASH_PAGES.find((p) => p.key === k));
  }
  return (DASH_LAYOUTS[layout] || DASH_LAYOUTS.nonOppositional).map((k) => DASH_PAGES.find((p) => p.key === k)).filter(Boolean);
}
export function dashPages() {
  const layout = dashLayout();
  const custom = customPages(layout);
  return custom.length ? custom : builtinPages(layout);
}

// Alt+C / Alt+X move S.dashPage; the chosen page is remembered per layout in
// settings.dashboardSelection.
let lastDashPage = S.dashPage;
function selectedPage(layout, pages) {
  const sel = settings.dashboardSelection || (settings.dashboardSelection = {});
  let i = Math.max(0, pages.findIndex((p) => p.key === sel[layout]));
  if (S.dashPage !== lastDashPage) {
    i = (((i + S.dashPage - lastDashPage) % pages.length) + pages.length) % pages.length;
    lastDashPage = S.dashPage;
    sel[layout] = pages[i].key;
    saveSettings();
  }
  return { page: pages[i], index: i };
}

function lastSeries(pid, key) {
  const rows = S.series && S.series[pid];
  if (!rows || !rows.length) return null;
  let lo = 0, hi = rows.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (rows[m].t <= S.t) lo = m; else hi = m - 1; }
  return rows[lo][key];
}

function cellValue(c, s, pid) {
  let v;
  try { v = COL[c].v(s, String(pid)); } catch (e) { v = null; }
  if (v && typeof v === 'object' && 'html' in v) return v.html;
  return v == null ? '–' : typeof v === 'number' ? fmtNum(v) : esc(v);
}
// One-value cell, or the combined two-value variant (1v1 pages).
function cellHtml(c, s, pid, combine) {
  const first = cellValue(c, s, pid);
  const other = combine && COMBINED[c];
  return other ? `${first}<small class="dash-sub" ${tip(t(COL[other].h))}>${cellValue(other, s, pid)}</small>` : first;
}

export function renderDashboard() {
  const el = $('dashboard');
  if (!settings.showDashboard || !S.view) { el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  const layout = dashLayout();
  el.dataset.dashLayout = layout;
  delegate(el, 'click', '[data-dash-page]', (d) => {
    // Route to the layout that owns the visible tabs, including the brief
    // interval between new match metadata arriving and the next HUD render.
    settings.dashboardSelection[el.dataset.dashLayout] = d.dataset.dashPage; saveSettings(); renderDashboard();
  });
  delegate(el, 'click', '[data-dash-metric]', (d) => {
    const pid = +d.dataset.pid, metric = d.dataset.dashMetric;
    const acts = { wFood: [2], wWood: [3], wGold: [4], wStone: [5], build: [6, 7], idle: [0] };
    if (['tc', 'castles', 'tcCastle'].includes(metric)) {
      const masters = new Set([...(metric === 'castles' ? [] : TOWN_CENTERS), ...(metric === 'tc' ? [] : GOTO_BUILDINGS.gotoCastle || [])]);
      S.selection = new Set(currentRows().filter((r) => r[1] === pid && masters.has(r[2])).map((r) => r[0]));
    } else if (acts[metric] || ['vils', 'mil', 'milValue'].includes(metric)) {
      S.selection = new Set(currentRows().filter((r) => r[1] === pid && (acts[metric] ? !!(r[6] & 4) && acts[metric].includes(r[9]) : metric === 'vils' ? !!(r[6] & 4) : !!(r[6] & 2))).map((r) => r[0]));
    } else window.dispatchEvent(new CustomEvent('vantage-investigate', { detail: { pid, metric } }));
  });
  el.classList.toggle('mini', layout === 'miniFfa');
  const pages = dashPages();
  // Keep a compact, fixed viewport across mirrored and full-list pages.
  // Longer tables scroll inside it without moving the tabs.
  el.style.setProperty('--dash-rows', Math.min(4, players().length));
  const { page: base, index } = selectedPage(layout, pages);
  // Older per-page column edits still apply to built-in pages.
  const legacy = base.custom ? null : (settings.dashboardColumns || {})[base.key];
  // The truce column only appears in games that had a truce (D3 mode).
  const hadTruce = players().some((p) => has((playerStats(p.id) || {}).d3_resource_aggregate));
  let cols = (legacy && legacy.length ? legacy : base.cols).filter((c) => COL[c] && (c !== 'd3Agg' || hadTruce));
  const title = base.custom ? `${t('Page')} ${base.num}` : t(base.title);
  setText($('dash-title'), `${title}${pages.length > 1 ? ` · ${index + 1}/${pages.length}` : ''}`);
  let tabs = el.querySelector('.review-dash-tabs');
  if (!tabs) { tabs = document.createElement('div'); tabs.className = 'review-dash-tabs'; el.querySelector('.dash-head').after(tabs); }
  const tabsHtml = pages.map((p) => `<button data-dash-page="${p.key}" aria-pressed="${p.key === base.key}">${esc(p.custom ? `${t('Page')} ${p.num}` : t(p.title))}</button>`).join('');
  patchHtml(tabs, tabsHtml);
  const th = (c) => {
    const m = COL[c];
    const icons = headerIcons(c);
    return `<th ${tip(t(m.h), t(m.tip || ''))}>${icons || t(m.abbr || m.h)}</th>`;
  };
  const nameTd = (pid, right) => `<td class="pname${right ? ' r' : ''}" style="border-color:${playerColor(pid)}">${esc(playerName(pid))}</td>`;
  const two = isTwoTeamLayout() && teams().length === 2;
  const combine = layout === 'nonOppositional';
  const td = (c, s, pid) => {
    const value = cellHtml(c, s, pid, combine && !cols.includes(COMBINED[c]));
    return `<td>${DASH_HISTORY[c] || DASH_SELECTIONS.has(c) ? `<button class="review-dash-value" data-dash-metric="${c}" data-pid="${pid}" ${tip(t(COL[c].h), t('Inspect'))}>${value}</button>` : value}</td>`;
  };
  // Team games mirror by default (unless every column is a stockpile one): left
  // team, a divider, then the right team's columns reversed.
  let mirror = false;
  if (two && layout === 'oppositional' && !base.paired) {
    const m = base.custom ? base.mirror : (settings.dashboardMirror || {})[base.key];
    mirror = m == null ? defaultMirror(cols) : !!m;
  }
  let html;
  if (mirror) {
    const [a, b] = sideTeams();
    const rcols = cols.slice().reverse();
    const head = `<tr><th>${t('Player')}</th>${cols.map(th).join('')}<th class="dash-gap"></th>${rcols.map(th).join('')}<th class="r">${t('Player')}</th></tr>`;
    const body = [];
    for (let i = 0; i < Math.max(a.players.length, b.players.length); i++) {
      const pa = a.players[i], pb = b.players[i];
      const sa = pa && playerStats(pa.id), sb = pb && playerStats(pb.id);
      const left = sa ? nameTd(pa.id) + cols.map((c) => td(c, sa, pa.id)).join('') : `<td></td>${cols.map(() => '<td></td>').join('')}`;
      const right = sb ? rcols.map((c) => td(c, sb, pb.id)).join('') + nameTd(pb.id, true) : `${rcols.map(() => '<td></td>').join('')}<td></td>`;
      body.push(`<tr data-ui-key="pair-${pa?.id ?? 'none'}-${pb?.id ?? 'none'}">${left}<td class="dash-gap"></td>${right}</tr>`);
    }
    html = head + body.join('');
  } else {
    let order;
    const ranked = layout === 'ffa' || layout === 'battleRoyale' || layout === 'miniFfa';
    if (ranked) order = rankedPlayers().map((p) => p.id);
    else if (two && base.paired) {
      const [a, b] = sideTeams();
      order = [];
      for (let i = 0; i < Math.max(a.players.length, b.players.length); i++) {
        if (a.players[i]) order.push(a.players[i].id);
        if (b.players[i]) order.push(b.players[i].id);
      }
    } else order = orderedTeams().flatMap((tm) => tm.players.map((p) => p.id));
    if (base.top) order = order.slice(0, base.top);
    const head = `<tr><th>${t('Player')}</th>${cols.map(th).join('')}</tr>`;
    const body = order.map((pid, i) => {
      const s = playerStats(pid);
      if (!s) return '';
      const cls = [isDead(pid) ? 'dead' : '', two && base.paired && i % 2 === 1 ? 'pair-end' : ''].join(' ').trim();
      return `<tr data-ui-key="player-${pid}" class="${cls}">${nameTd(pid)}${cols.map((c) => td(c, s, pid)).join('')}</tr>`;
    });
    html = head + body.join('');
  }
  const table = $('dash-table');
  if (table._html !== html) { table._html = html; patchHtml(table, html); }
}

// -- events ---------------------------------------------------------------------------------

export const EVENT_CATS = [
  ['combat', '⚔', 'Combat & attacks'], ['train_research', '⚒', 'Training & research'], ['age', '⬆', 'Age ups'],
  ['chat', '💬', 'Chat'], ['tribute', '⇄', 'Tribute'], ['market', '⚖', 'Market'],
  ['conversion', '✝', 'Conversions'], ['king', '♔', 'Kings, wonders, relics & King of the Hill'],
  ['countdown', '⏳', 'Victory countdowns'], ['diplomacy', '🤝', 'Diplomacy'], ['status', '⚑', 'Resign / defeat'],
];

// Category of an event for the filter; the newer kinds may arrive without one.
export function eventCat(e) {
  // Wonder and relic events are filed under kingNotification too.
  if (/^king_|^refuge_|^wonder_|^relics_|^ruins_/.test(e.kind) || e.kind === 'treason' || e.kind === 'koth_owner') return 'king';
  if (e.kind === 'countdown') return 'countdown';
  if (e.kind === 'waiting') return 'status';
  return e.cat;
}

export function renderEventFilters(onChange) {
  const el = $('event-filters');
  patchHtml(el, EVENT_CATS.map(([k, icon, title]) => `<button data-cat="${k}" ${tip(t(title), t('click: show or hide'))} class="${settings.eventFilterOut.includes(k) ? '' : 'on'}">${icon}</button>`).join(''));
  el.querySelectorAll('button').forEach((b) => { b.onclick = () => {
    const k = b.dataset.cat;
    const i = settings.eventFilterOut.indexOf(k);
    if (i >= 0) settings.eventFilterOut.splice(i, 1); else settings.eventFilterOut.push(k);
    saveSettings();
    renderEventFilters(onChange);
    onChange();
  }; });
}

function playersList(ids) { return (ids || []).map((id) => pn(id)).join(', '); }

// Unit-ref helper for event texts: {id, owner, master} -> name (from the live master).
function unitName(ref, fallbackMaster, owner) {
  const mid = ref && ref.master != null ? ref.master : fallbackMaster;
  return mid != null ? esc(unitInfo(mid, ref && ref.owner != null ? ref.owner : owner).name) : '';
}
const STANCE_NOUN = { ally: 'friendship', neutral: 'neutrality', enemy: 'enmity' };
// "{p}'s {unit}" or the bare unit/"unknown" wording when no name resolves.
function ownedUnit(owner, name) { return name ? t("{p}'s {u}", { p: owner != null ? pn(owner) : '', u: name }) : ''; }
// "by <attacker/>'s {unit}" suffix of the king events; empty without an attacker.
function byAttacker(e) {
  const a = e.attacker;
  const owner = e.by ?? (a && a.owner);
  const name = unitName(a);
  if (owner == null && !name) return '';
  return ' ' + (name && owner != null ? t('by {x}', { x: ownedUnit(owner, name) }) : t('by {x}', { x: owner != null ? pn(owner) : name }));
}
function refugeName(e) {
  const mid = e.refuge_master ?? (e.refuge && e.refuge.master);
  return mid != null ? esc(unitInfo(mid, e.player).name) : t('building');
}

function eventText(e) {
  const ui = (mid, owner) => { const u = unitInfo(mid, owner); return `<img src="${unitIcon(mid, owner)}" alt=""> ${esc(u.name)}`; };
  switch (e.kind) {
    case 'kill': {
      const v = e.victim || {}, k = e.killer || {};
      const victim = v.master != null ? ui(v.master, v.owner) : 'unit';
      const killer = k.master != null ? ui(k.master, k.owner) : '?';
      const ff = e.friendly ? ` <span class="hint">(${t('friendly fire')})</span>` : '';
      return t('{killer} killed {victim}', { killer: `${k.owner ? pn(k.owner) : ''} ${killer}`, victim: `${v.owner ? pn(v.owner) + "'s" : ''} ${victim}` }) + ff;
    }
    case 'trained': return t('{u} created by {p}', { u: e.master != null ? ui(e.master, e.player) : esc(t('Unknown Unit<{id}>', { id: e.unit ?? '?' })), p: pn(e.player) });
    case 'researched': {
      const known = S.catalog.techs && S.catalog.techs[e.tech];
      const x = known ? `<img src="${techIconFor(e.tech, e.player)}" alt=""> ${esc(techInfoFor(e.tech, e.player).name)}` : esc(t('UnknownTech<{id}>', { id: e.tech }));
      return t('{x} researched by {p}', { x, p: pn(e.player) });
    }
    case 'age_up': return t('{p} reached the {age}', { p: pn(e.player), age: ageName(e.age, e.player) });
    case 'chat': {
      const to = Array.isArray(e.to) && e.to.length ? ` <span class="hint">→</span> ${playersList(e.to)}` : e.channel === 2 ? ` <span class="hint">(${t('team')})</span>` : e.channel === 3 ? ` <span class="hint">(${t('enemies')})</span>` : '';
      return `${pn(e.player)}${to}${e.paused ? ` <span class="hint">(${t('paused')})</span>` : ''}: ${esc(String(e.text || '').replace(/<player_id,(\d+),[-\d]+>/g, (_, id) => playerName(+id)))}`;
    }
    case 'tribute': {
      const amount = has(e.amount) ? Math.round(e.amount) : 0;
      const tax = has(e.tax) ? Math.round(e.tax) : null;
      if (tax == null) return t('{p} tributed {n} {res} to {to}', { p: pn(e.player), n: amount, res: t(e.resource), to: pn(e.to) });
      return t('{p} sent {n} {res} to {to} and paid {tax} in tax.', { p: pn(e.player), n: amount, res: t(e.resource), to: pn(e.to), tax });
    }
    case 'buy': case 'sell': return t(e.kind === 'buy' ? '{p} bought {n} {res} for {g} gold' : '{p} sold {n} {res} for {g} gold', { p: pn(e.player), n: Math.round(e.amount), res: t(e.resource), g: Math.round(e.gold) });
    case 'conversion': {
      // "<owner/>'s {target} was converted by <monk/>"; no display info -> "unit/building".
      const owner = e.from ?? (e.target && e.target.owner);
      const name = e.target && e.target.master != null ? unitInfo(e.target.master, owner).name : '';
      return name ? t("{owner}'s {target} was converted by {monk}", { owner: owner != null ? pn(owner) : '', target: esc(name), monk: pn(e.player) })
        : t("{owner}'s unit/building was converted by {monk}", { owner: owner != null ? pn(owner) : '', monk: pn(e.player) });
    }
    case 'under_attack': {
      const mid = e.master ?? (e.unit && e.unit.master);
      if (mid == null) return t(e.alert === 2 ? '{p} is under attack (town)' : '{p} is under attack', { p: pn(e.player) });
      return t("{p}'s {u} is under attack.", { p: pn(e.player), u: esc(unitInfo(mid, e.player).name) });
    }
    case 'resigned': return t('{p} resigned', { p: pn(e.player) });
    case 'dropped': return t('{p} dropped', { p: pn(e.player) });
    case 'lost': return t('{p} was defeated', { p: pn(e.player) });
    case 'won': return t('{who} is victorious!', { who: pn(e.player) });
    case 'farm_expired': return t('{p}: a farm expired', { p: pn(e.player) });
    case 'diplomacy': {
      // After >= 100 years in the previous stance: "after {duration} of {previousStance}".
      const long = (has(e.duration_years) || has(e.duration_ms)) && STANCE_NOUN[e.previous];
      const duration = long ? yearsText(e.duration_ms, e.duration_years) : '';
      const prev = long ? t(STANCE_NOUN[e.previous]) : '';
      const who = { p: pn(e.player), to: pn(e.to), duration, prev };
      if (e.stance === 'ally') return t(long ? '{p} allied themselves with {to} after {duration} of {prev}' : '{p} allied themselves with {to}', who);
      if (e.stance === 'neutral') return t(long ? '{p} declared neutrality towards {to} after {duration} of {prev}' : '{p} declared neutrality towards {to}', who);
      return t(long ? '{p} declared war on {to} after {duration} of {prev}' : '{p} declared war on {to}', who);
    }
    case 'trap_expired': return t('{p}: a fish trap expired', { p: pn(e.player) });
    case 'king_garrisoned': {
      const x = { p: pn(e.player), owner: pn(e.refuge_owner ?? (e.refuge && e.refuge.owner) ?? e.player), refuge: refugeName(e) };
      return `<span class="ev-ico">${e.boarded ? '⛵' : '⌂'}</span> ` + t("{p}'s King garrisoned {owner}'s {refuge}.", x);
    }
    case 'king_ungarrisoned': {
      if (!e.forced) return t("{p}'s King ungarrisoned voluntarily", { p: pn(e.player) });
      const name = unitName(e.attacker);
      const by = e.by ?? (e.attacker && e.attacker.owner);
      return name && by != null ? t("{p}'s King was forced to ungarrison by {x}", { p: pn(e.player), x: ownedUnit(by, name) }) : t("{p}'s King was forced to ungarrison.", { p: pn(e.player) });
    }
    case 'king_attacked': return t("{p}'s King is under attack", { p: pn(e.player) }) + byAttacker(e);
    case 'king_threatened': return e.by != null ? t("{p}'s King is threatened by {by}", { p: pn(e.player), by: pn(e.by) }) : t("{p}'s King is threatened", { p: pn(e.player) });
    case 'king_killed': return e.mysterious ? t("{p}'s King died in mysterious circumstances", { p: pn(e.player) })
      : t("{p}'s King has been killed", { p: pn(e.player) }) + byAttacker({ ...e, by: e.by ?? (e.killer && e.killer.owner), attacker: e.attacker || e.killer });
    case 'refuge_attacked': return t("{p}'s King's refuge is under attack", { p: pn(e.player) }) + byAttacker(e);
    case 'treason': return t('{p} researched treason and revealed the position of all enemy kings.', { p: pn(e.player) });
    case 'koth_owner': {
      const prev = e.previous ? pn(e.previous) : `<b>${esc(t('Gaia'))}</b>`;
      const nu = e.player ? pn(e.player) : `<b>${esc(t('Gaia'))}</b>`;
      const rem = e.previous && (has(e.previous_remaining_years) || has(e.previous_remaining_ms)) ? yearsText(e.previous_remaining_ms, e.previous_remaining_years) : '';
      return rem ? t('{p} seized control of the Monument from {prev}, who had {duration} remaining before victory', { p: nu, prev, duration: rem })
        : t('{p} seized control of the Monument from {prev}', { p: nu, prev });
    }
    case 'relics_held': return t('{p} has collected all Relics.', { p: pn(e.player) });
    case 'relics_lost': return t('{p} has lost control over the Relics.', { p: pn(e.player) });
    // Vantage-only kinds: `remaining` is game years (1 year = 5 s), not seconds.
    case 'ruins_held': return has(e.remaining) ? t('{p} holds the Monument: {duration} remaining before victory', { p: pn(e.player), duration: yearsText(0, e.remaining) })
      : t('{p} holds the Monument', { p: pn(e.player) });
    case 'ruins_lost': return t('{p} has lost control of the Monument', { p: pn(e.player) });
    case 'wonder_started': return t('{p} has started building a Wonder.', { p: pn(e.player) });
    case 'wonder_completed': return t('{p} has completed building a Wonder.', { p: pn(e.player) });
    case 'wonder_destroyed': return t("{p}'s Wonder has been destroyed.", { p: pn(e.player) });
    case 'countdown': {
      const what = e.victory || e.type || e.what || (typeof e.kind_detail === 'string' ? e.kind_detail : '');
      return t('{p}: {what} in {n} years', { p: e.player ? pn(e.player) : '', what: t(VICTORY_LABEL[what] || 'Victory'), n: Math.ceil(+(e.years_left ?? e.remaining ?? 0)) });
    }
    case 'waiting': return Array.isArray(e.players) && e.players.length ? t('Waiting for {who}', { who: playersList(e.players) }) : t('Waiting for players');
    default: return `${e.player ? pn(e.player) + ': ' : ''}${esc(e.kind.replace(/_/g, ' '))}${e.remaining != null ? ` (${Math.round(e.remaining)}s)` : ''}`;
  }
}

// Kinds whose priority comes from the server: high only when it says so.
// Other kinds (age ups, status, countdowns, ruins) keep the local rule.
const RULE_KINDS = new Set(['market', 'buy', 'sell', 'chat', 'tribute', 'king_garrisoned', 'king_ungarrisoned', 'diplomacy', 'koth_owner', 'kill',
  'trained', 'researched', 'conversion', 'under_attack', 'king_attacked', 'king_killed', 'king_threatened', 'refuge_attacked', 'treason',
  'wonder_started', 'wonder_completed', 'wonder_destroyed', 'relics_held', 'relics_lost']);
function isHigh(e) {
  if (RULE_KINDS.has(e.kind)) return e.priority === 'high';
  return e.priority === 'high' || e.kind === 'countdown' || e.cat === 'victory' || e.cat === 'status' || e.kind === 'age_up';
}

function eventLi(e, i, attr = 'data-i') {
  return `<li data-ui-key="${esc(JSON.stringify([e.t, e.kind, e.player, e.x, e.y, e.unit, e.killer, e.victim]))}" class="${isHigh(e) ? 'high' : ''}" ${attr}="${i}">
    <span class="et" data-t="${e.t}" ${tip(t('Jump to this moment'))}>${fmtTime(e.t)}</span>
    <span class="ec" style="background:${playerColor(e.player)}"></span><span>${eventText(e)}</span></li>`;
}

let shownEvents = '';
let eventsPinnedToBottom = true;
let recentEvents = [];
// The log's rows -> their events (rows are appended and dropped, so no indices).
const listRowEvent = new WeakMap();
let highEvents = [];

// The last `limit` events at or before the current time that pass the filter.
// S.events is in time order, so this walks back from the current time instead of
// filtering the whole game (thousands of rows, four times a second at 8x).
function recentVisibleEvents(limit) {
  const ev = S.events;
  let lo = 0, hi = ev.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (ev[m].t <= S.t) lo = m + 1; else hi = m; }
  const out = [];
  const hidden = settings.eventFilterOut;
  for (let i = lo - 1; i >= 0 && out.length < limit; i--) if (!ageUpRepeat(ev, i) && !hidden.includes(eventCat(ev[i]))) out.push(ev[i]);
  return out.reverse();
}

// age_up (derived a keyframe after the fact) repeats the age research event when
// the stream has one for the same player just before it.
function ageUpRepeat(ev, i) {
  const e = ev[i];
  if (e.kind !== 'age_up') return false;
  for (let j = i - 1; j >= 0 && e.t - ev[j].t <= 3000; j--) {
    if (ev[j].kind === 'researched' && ev[j].cat === 'age' && ev[j].player === e.player) return true;
  }
  return false;
}

export function renderEvents(seek) {
  const list = $('event-list');
  const pager = $('event-pager');
  let high = $('event-high');
  if (!high) {
    high = document.createElement('ol');
    high.id = 'event-high';
    list.parentElement.insertBefore(high, list);
  }
  const onRow = (rows) => (li, ev) => {
    const e = rows[+li.dataset.i];
    if (!e) return;
    if (ev.target.classList.contains('et')) seek(e.t - 3000);
    // Relics collected / lost: select that player's monasteries (there is no location).
    if (Array.isArray(e.monasteries) && e.monasteries.length) {
      const rows = currentRows().filter((r) => e.monasteries.includes(r[0]));
      if (rows.length) { S.selection = new Set(rows.map((r) => r[0])); centerOn(rows[0][3], rows[0][4]); return; }
    }
    if (e.x != null) centerOn(e.x, e.y);
  };
  delegate(list, 'click', 'li', (li, ev) => { const e = listRowEvent.get(li); if (e) onRow([e])({ dataset: { i: 0 } }, ev); });
  delegate(high, 'click', 'li', (li, ev) => onRow(highEvents)(li, ev));
  if (!pager._wired) {
    pager._wired = true;
    pager.addEventListener('click', () => { eventsPage(1, true); pager.classList.add('hidden'); eventsPinnedToBottom = true; });
    list.addEventListener('scroll', () => {
      // Kept here, not read at render time: reading the scroll position right after the
      // other panels were rewritten forced a full layout four times a second.
      eventsPinnedToBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 30;
      if (eventsPinnedToBottom) pager.classList.add('hidden');
    });
  }
  const recent = recentVisibleEvents(150);
  renderPinned(high, recent);
  // The log is a window of the last 150 events: while playing forward it only
  // slides, so append the new rows and drop as many from the top instead of
  // rebuilding (and re-parsing) all 150 every time an event arrives.
  // Anything that changes how existing rows read forces a rebuild.
  const key = [settings.eventFilterOut.join(), language, JSON.stringify(settings.playerNames || {}),
    JSON.stringify(settings.entityNames || {}), JSON.stringify(settings.teamCaptains || {}), settings.baseColorMode,
    settings.skin, S.colorMode, JSON.stringify(S.colorOverride || {}), S.catalogVersion,
    S.match && Object.values(S.match.players || {}).map((p) => p && p.name).join(',')].join('|');
  const delta = key === shownEvents ? listDelta(recentEvents, recent) : null;
  shownEvents = key;
  if (delta && !delta.drop && !delta.add.length) return;
  recentEvents = recent;
  if (delta) {
    for (let i = 0; i < delta.drop && list.firstElementChild; i++) list.firstElementChild.remove();
    if (delta.add.length) {
      list.insertAdjacentHTML('beforeend', delta.add.map((e) => eventLi(e, 0)).join(''));
      const rows = list.children;
      for (let i = 0; i < delta.add.length; i++) listRowEvent.set(rows[rows.length - delta.add.length + i], delta.add[i]);
    }
  } else {
    list.innerHTML = recent.map((e) => eventLi(e, 0)).join('');
    [...list.children].forEach((li, i) => listRowEvent.set(li, recent[i]));
  }
  if (eventsPinnedToBottom) list.scrollTop = list.scrollHeight;
  pager.classList.toggle('hidden', eventsPinnedToBottom);
}

// A notification stays "recent" for 15 s (normal) / 25 s (high priority)
// of game time and fades it during the last half second; the log below
// holds the last 150 events up to the current time (seek back for earlier ones).
const NOTE_MS = { low: 15000, high: 25000 };
const NOTE_FADE_MS = 500;
const NOTE_ROWS = 3;
const noteMs = (e) => (isHigh(e) ? NOTE_MS.high : NOTE_MS.low);
// High rows are tinted with the target player's colour: the one who lost something
// or was attacked, else the acting player.
function targetPlayer(e) {
  const o = (x) => (x && x.owner != null ? x.owner : null);
  return o(e.victim) ?? o(e.target) ?? o(e.unit) ?? (e.from != null ? e.from : null) ?? (e.to != null && typeof e.to === 'number' ? e.to : null) ?? e.player;
}
let shownPinned = '';
function renderPinned(box, vis) {
  // Only alerts are pinned above the log (the log right below already lists the rest).
  const live = vis.filter((e) => e.kind !== 'age_up' && e.cat !== 'status' && isHigh(e) && S.t - e.t < noteMs(e)).slice(-NOTE_ROWS);
  highEvents = live;
  const key = language + live.map((e) => e.t + e.kind + (e.player ?? '') + (isHigh(e) ? playerColor(targetPlayer(e)) : '')).join('|');
  if (key !== shownPinned) {
    shownPinned = key;
    patchHtml(box, live.map((e, i) => {
      const high = isHigh(e);
      const tint = high ? ` style="background:${playerColor(targetPlayer(e))}33"` : '';
      return eventLi(e, i).replace('<li ', `<li${tint} `);
    }).join(''));
  }
  box.classList.toggle('hidden', !live.length);
  [...box.children].forEach((li, i) => {
    const e = live[i];
    if (!e) return;
    const left = noteMs(e) - (S.t - e.t);
    li.style.opacity = left < NOTE_FADE_MS ? String(Math.max(0, left / NOTE_FADE_MS)) : '';
  });
}

export function eventsPage(dir, toEdge) {
  const list = $('event-list');
  if (toEdge) list.scrollTop = dir < 0 ? 0 : list.scrollHeight;
  else list.scrollTop += dir * list.clientHeight * 0.9;
}

// -- unit panel ------------------------------------------------------------------------------

const ACT_NAMES = ['idle', 'moving', 'gathering food', 'gathering wood', 'gathering gold', 'gathering stone', 'building', 'repairing', 'fighting', 'garrisoned', 'producing', 'researching', '', 'packing', 'unpacking', 'healing'];

export function rememberSelection() {
  // Keep what was selected so units that die stay listed (with a skull).
  for (const r of selectedRows()) S.selectionInfo.set(r[0], { mid: r[2], owner: r[1] });
}

function gaiaPanel(el) {
  const v = S.view || {};
  const m = v.market || {};
  const rl = (S.series && S.series['0']) || [];
  let left = rl[0];
  for (const x of rl) { if (x.t <= S.t) left = x; else break; }
  setHtml(el, `<div class="up-name">${esc((S.match.map_file || t('Map')).replace(/\.rms$/, ''))}</div>
    <div class="hint">${fmtTime(S.t)} · ${S.match.map_size ? S.match.map_size.join('×') : ''} ${t('tiles')}</div>
    <div class="up-stats" style="margin-top:6px" ${tip(t('Market prices'), t('Base price in gold per 100: buying costs more and selling earns less, by the market commission'))}><div><span>${t('food')}</span> ${m.food ? Math.round(m.food * 100) : '–'}</div><div><span>${t('wood')}</span> ${m.wood ? Math.round(m.wood * 100) : '–'}</div><div><span>${t('stone')}</span> ${m.stone ? Math.round(m.stone * 100) : '–'}</div></div>
    ${left ? `<div class="hint" style="margin-top:6px">${t('Left on map: {f} food · {w} wood · {g} gold · {s} stone · {r} relics', { f: fmtNum(left.food), w: fmtNum(left.wood), g: fmtNum(left.gold), s: fmtNum(left.stone), r: left.relics })}</div>` : ''}`);
}

function deadIcon(id) {
  const d = S.selectionInfo.get(id);
  return `<div class="icon-count" ${tip(unitInfo(d.mid, d.owner).name, t('dead'))} style="outline:2px solid ${playerColor(d.owner)}"><img src="${unitIcon(d.mid, d.owner)}" alt="" style="filter:grayscale(1) brightness(.6)"><b>☠</b></div>`;
}

// Kills, damage dealt/taken (with per-type breakdown on hover), conversions.
function combatHtml(us) {
  if (!us) return '';
  const breakdown = (by) => Object.entries(by || {}).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([m, d]) => `${unitInfo(+m).name} ${fmtNum(d)}`).join(', ');
  const parts = [];
  if (us.kills || us.dealt || us.taken || us.friendly_kills) {
    const ff = us.friendly_kills ? ` <span class="hint" ${tip(t('Friendly kills'), t('Own or allied units killed'))}>(${us.friendly_kills} ${t('friendly')})</span>` : '';
    parts.push(`<div ${tip(t('Kills'), t('Total, economy and friendly kills'))}><span>${t('Kills')}</span> ${fmtNum(us.kills)}${us.eco_kills ? ` (${fmtNum(us.eco_kills)} ${t('eco')})` : ''}${ff}</div>`);
    parts.push(`<div ${tip(t('Damage dealt'), breakdown(us.damage_by_target))}><span>${t('Dealt')}</span> ${fmtNum(us.dealt)}</div>`);
    parts.push(`<div ${tip(t('Damage taken'), breakdown(us.damage_by_attacker))}><span>${t('Taken')}</span> ${fmtNum(us.taken)}</div>`);
  }
  const mk = us.monk;
  if (mk && (mk.conversions || mk.eco || mk.heresy)) {
    parts.push(`<div ${tip(t('Conversions'), t('Total · economy units · lost to Heresy'))}><span>${t('Conversions')}</span> ${mk.conversions || 0} · ${mk.eco || 0} ${t('eco')} · ${mk.heresy || 0} ${t('heresy')}</div>`);
  }
  return parts.length ? `<div class="up-stats" style="margin-top:4px">${parts.join('')}</div>` : '';
}

function bar(frac, color, label) {
  return `<div class="up-bar" ${tip(label, Math.round(frac * 100) + '%')}><i style="width:${Math.round(clamp(frac, 0, 1) * 100)}%;background:${color}"></i></div>`;
}

// Attack / armour class names are the game's strings 12400 + class (catalog
// armor_classes, already localised); the English table is the fallback.
function className(c) {
  const m = S.catalog.armor_classes;
  const g = m && (m[c] ?? m[String(c)]);
  if (g) return g;
  return ARMOR_CLASSES[c] ? t(ARMOR_CLASSES[c]) : t('class {n}', { n: c });
}
const r2 = (v) => Math.round(v * 100) / 100;
// "base±delta" (e.g. 6+2): the base value, then the signed
// difference (coloured) when the live value differs from it.
function baseDelta(base, cur) {
  const b = has(base) ? base : cur;
  if (!has(b)) return '';
  if (!has(cur) || Math.abs(cur - b) < 0.005) return String(r2(b));
  const d = r2(cur - b);
  return `${r2(b)}<span class="up-delta ${d > 0 ? 'pos' : 'neg'}">${d > 0 ? '+' : '-'}${Math.abs(d)}</span>`;
}
// Plain-text variant for tooltips.
function baseDeltaText(base, cur) { return baseDelta(base, cur).replace(/<[^>]+>/g, ''); }
// Rows [[class, base, current]] with the entity's live values (view.unit_mods) folded in.
function modRows(rows, pairs) {
  const m = new Map((pairs || []).map(([c, v]) => [+c, v]));
  return (rows || []).map(([c, b, cur]) => [+c, b, m.has(+c) ? m.get(+c) : (has(cur) ? cur : b)]);
}
function classTip(rows) {
  return (rows || []).map(([c, b, cur]) => `${className(c)} ${baseDeltaText(b, cur)}`).join('\n');
}
const stripMarkup = (s) => String(s || '').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '');
// The live modifiers of one entity from the keyframe (power-ups, stingers, charge…).
function unitMods(id) {
  const m = S.view && S.view.unit_mods;
  return (m && (m[id] ?? m[String(id)])) || null;
}
// Carried resources: [res, amt] or [res, amt, res2, amt2] (secondary / transient).
function carryPairs(c) {
  if (!Array.isArray(c)) return [];
  const out = [];
  if (has(c[0]) && has(c[1])) out.push([c[0], c[1]]);
  if (has(c[2]) && has(c[3]) && c[3] > 0) out.push([c[2], c[3]]);
  return out;
}

// A Gaia resource (mine, bush, tree, fish, carcass): what is left of what it
// held, and who is gathering from it. Farms are left out: the stream carries
// only a farm's small food buffer, not the food left in it.
const FLAG_REMAINS = 256; // world.py: a row from view.remains
function isResource(r) { return r[1] === 0 && (Array.isArray(r[10]) || !!unitInfo(r[2], r[1], r[0]).storage); }

function resourcePanel(el, r) {
  const u = unitInfo(r[2], 0, r[0]);
  const [res, left] = Array.isArray(r[10]) ? r[10] : [(u.storage || [])[0] || 'food', 0];
  const full = u.storage && u.storage[0] === res ? u.storage[1] : null;
  const frac = full ? left / full : 1;
  const who = Object.entries(gatherersOf(r)).filter(([, n]) => n > 0);
  const lo = S.view && S.view.livestock_owner;
  const lastOwner = lo ? (lo[r[0]] ?? lo[String(r[0])]) : null;
  const what = isTreeId(r[0]) ? (r[11] != null ? t('Being cut') : t('Untouched')) : (r[6] & FLAG_REMAINS) ? t('Carcass') : t('Gaia');
  setHtml(el, `<div class="review-resource-head"><div class="up-res"><b style="color:var(--${res})">${fmtNum(Math.floor(left))}</b>${full ? ` <span class="hint">/ ${fmtNum(full)}</span>` : ''} <span style="color:var(--${res})">${esc(t(res))}</span></div><img src="${unitIcon(r[2], 0, r[0])}" alt=""></div>
    <div class="up-name">${esc(u.name)}</div><div class="hint">${what}${lastOwner ? ` · <span style="color:${playerTextColor(lastOwner)}">${esc(playerName(lastOwner))}</span>` : ''}</div>
    ${bar(frac, `var(--${res})`, t('{r} left', { r: t(res) }))}
    <div class="review-gatherers">${who.map(([o, n]) => `<button data-gatherers="${isTreeId(r[0]) ? r[11] : r[0]}" data-owner="${o}" ${tip(t('Select gatherers'), playerName(+o))}>${reviewIcon('workers')}<b style="color:${playerTextColor(+o)}">×${n}</b></button>`).join('') || `<span class="hint">${t('Nobody gathering')}</span>`}</div>`);
}

// Use the civ's own curated lines to identify upgrades for selected units.
function relevantUpgrades(rows) {
  if (!rows.length) return '';
  const pid = rows[0][1], p = player(pid);
  if (!pid || !p) return '';
  const tree = treeNow(p.civ);
  if (!tree) { loadTree(p.civ); return ''; }
  const layout = tree.layout?.rows || [];
  const selectedLines = new Set(rows.map((r) => lineOf(r[2])));
  const selectedIds = new Set(rows.map((r) => r[2]));
  const matchStage = (st) => st.unit != null && (selectedIds.has(st.unit) || selectedLines.has(lineOf(st.unit)));
  const isWorker = rows.every((r) => unitInfo(r[2], pid, r[0]).cls === 4);
  const isTC = rows.every((r) => TOWN_CENTERS.includes(r[2]));
  const groups = [];
  const common = new Set(['meleeAttack', 'infantryArmor', 'squires', 'arson', 'rangedAttack', 'archerArmor', 'thumbRing', 'cavalryArmor', 'bloodlines', 'husbandry']);
  for (const row of layout) {
    const matching = (row.groups || []).filter((g) => g.stages?.some(matchStage));
    if (matching.length) {
      groups.push(...matching);
      groups.push(...row.groups.filter((g) => common.has(g.key)));
      // Cavalry share melee attack upgrades, including when the tree lists them in Infantry.
      if (row.key === 'cavalry') groups.push(...layout.flatMap((r) => r.groups || []).filter((g) => g.key === 'meleeAttack'));
    }
    if (row.key === 'economy' && (isWorker || isTC)) {
      const keys = new Set(isTC ? ['loom', 'wheelCart', 'townWatch'] : ['loom', 'wheelCart']);
      for (const r of rows) { const key = ({ 3: 'lumber', 4: 'goldMining', 5: 'stoneMining' })[r[9]]; if (key) keys.add(key); }
      groups.push(...row.groups.filter((g) => keys.has(g.key)));
    }
  }
  const stats = playerStats(pid) || {}, done = new Set(stats.research_done || []);
  const active = new Map((stats.research_active || []).map((a) => [a.tech, a]));
  const stages = new Map();
  for (const group of groups) for (const stage of group.stages || []) {
    const tid = stage.tech ?? (stage.kind === 'tech' ? stage.id : null);
    if (tid != null && tid >= 0 && nodeStatus(stage) !== 'hidden') stages.set(tid, stage);
  }
  // A building's own research: every technology it researches that this civilisation can get.
  const buildingIds = new Set(rows.map((r) => r[2]));
  if (rows.every((r) => unitInfo(r[2], pid, r[0]).kind === 'building')) {
    for (const node of tree.nodes || []) {
      if (node.kind === 'tech' && buildingIds.has(node.building) && nodeStatus(node) === 'available' && !stages.has(node.id)) {
        stages.set(node.id, { ...node, tech: node.id });
      }
    }
  }
  return `<section class="review-upgrades"><div class="review-upgrades-head"><span>${t('Relevant upgrades')}</span><button data-full-tree="${pid}">${t('Full tree')} ↗</button></div><div class="review-upgrade-list">${[...stages.entries()].map(([tid, stage]) => {
    const a = active.get(tid), unavailable = nodeStatus(stage) === 'struck';
    const status = done.has(tid) ? 'done' : a ? 'doing' : unavailable ? 'unavailable' : (stage.age || 1) - 1 > (stats.age || 0) ? 'later' : 'available';
    const info = techInfoFor(tid, pid), detail = stripMarkup(info.help || info.description || '');
    return `<button class="review-upgrade ${status}" data-tech="${tid}" data-pid="${pid}" data-building="${a?.building || ''}" ${unavailable ? 'disabled' : ''} ${tip(info.name || stage.name, `${t(status)}${a?.remaining != null ? ' · ' + Math.ceil(a.remaining) + 's' : ''}${detail ? ' · ' + detail : ''}`)}><img src="${techIconFor(tid, pid)}" alt="${esc(info.name || stage.name)}"><small>${done.has(tid) ? '✓' : a?.remaining != null ? Math.ceil(a.remaining) + 's' : unavailable ? '×' : ''}</small></button>`;
  }).join('')}</div></section>`;
}

function singlePanel(el, r) {
  // Renaming: leave the panel alone while its name field has the focus.
  if (el.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return;
  if (isResource(r)) { resourcePanel(el, r); return; }
  const u = unitInfo(r[2], r[1], r[0]);
  const owner = r[1];
  const economic = u.cls === 4 || u.kind === 'building';
  const st = u.stats || {};
  const s = owner > 0 ? playerStats(owner) : null;
  const us = unitStats(r[0], r);
  const at = Math.round(S.view?.time ?? S.t);
  const identity = JSON.stringify([S.session?.generation, S.seekVersion, r[0], owner, r[2], S.reviewScope, S.reviewRange]);
  // Keep the last rendered snapshot while its replacement is being fetched.
  // This does not extend an entity-stats validity interval or mix stale stats
  // into a new snapshot. A changed selection/scope or rewind renders afresh.
  const retain = !us && owner > 0 && el._readyIdentity === identity
    && at >= el._readyAt && (S.playing || at - el._readyAt <= 5000);
  el.setAttribute('aria-busy', String(retain));
  if (retain) return;
  if (us) { el._readyIdentity = identity; el._readyAt = at; }
  const sv = (k) => (us && has(us[k]) ? us[k] : st[k]);
  const prod = s ? (s.production || []).find((b) => b.id === r[0]) : null;
  let prodHtml = '';
  if (prod) {
    const c = prod.current || {};
    const name = c.tech != null ? techInfo(c.tech).name : c.unit != null ? unitInfo(c.unit).name : '';
    const remaining = has(c.remaining) ? `${Math.ceil(c.remaining)}s` : c.progress != null ? Math.round(c.progress * 100) + '%' : '–';
    prodHtml = `<div class="review-production"><span>${esc(name)}</span> <b>${remaining}</b>
      <div class="up-multi">${(prod.queue || []).map((q) => `<div class="icon-count"><img src="${q.tech >= 0 ? techIcon(q.tech) : unitIcon(q.unit)}" alt=""><b>${q.count}</b></div>`).join('')}</div></div>`;
  }
  const mods = unitMods(r[0]) || {};
  const hpMax = has(mods.hp_max) ? mods.hp_max : (sv('hp') || u.hp);
  const base = (us && us.base) || {};
  const row = (label, value, detail = '') => (value === '' || value == null ? '' : `<div ${tip(t(label), detail)}><span>${t(label)}</span> ${value}</div>`);
  const nonZero = (v) => has(v) && v !== 0;
  // Attack / armour rows in the game's order as [class, base, current]; older
  // servers send only the master's pairs.
  const toRows = (pairs, drop0) => (pairs || []).filter(([, v]) => !drop0 || v).map(([c, v]) => [c, v, v]);
  let atkRows = modRows(us && (us.attack_rows || toRows(us.attacks, true)), mods.attacks);
  const armRows = modRows(us && (us.armor_rows || toRows(us.armors)), mods.armors);
  // Charged weapon: once the charge is full and applies, the attack row shows the
  // projectile unit's weapon (chargeType 6/7) or the charge value added to every shown class.
  const ch = (us && us.charge) || null;
  const chargeVal = has(mods.charge_value) ? mods.charge_value : ch && (ch.value ?? (ch.show === undefined ? ch.attack : 0));
  const chargeOn = has(mods.charge_fill) && mods.charge_fill >= 1 && mods.charge_applies !== false;
  if (chargeOn) {
    if (Array.isArray(mods.charged_weapon) && mods.charged_weapon.length) atkRows = mods.charged_weapon.map(([c, b, cur]) => [+c, b, cur ?? b]);
    else if (chargeVal > 0) atkRows = atkRows.map(([c, b, cur]) => [c, b, cur + Math.round(chargeVal)]);
  }
  const primary = (rows, ids) => {
    const cand = rows.filter(([c]) => ids.includes(c));
    return (cand.length ? cand : rows).slice().sort((x, y) => (y[2] ?? 0) - (x[2] ?? 0))[0] || null;
  };
  const atk = primary(atkRows, [3, 4]);
  const dot = us && us.dot > 0 ? us.dot : 0;
  const chargeShown = ch && (ch.show === undefined ? ch.attack : ch.show) && chargeVal > 0;
  const rechargeS = ch && (has(ch.recharge_time) ? ch.recharge_time : ch.recharge);
  const atkTip = [classTip(atkRows), dot ? `${t('Damage over time')} ${dot}` : '', chargeShown ? `${t('Charge attack')} ${Math.round(chargeVal)}` : ''].filter(Boolean).join('\n');
  const mArm = armRows.find(([c]) => c === 4), pArm = armRows.find(([c]) => c === 3);
  const armTip = classTip(armRows);
  const rng = { base: base.range ?? sv('range'), cur: has(mods.range) ? mods.range : sv('range') };
  const rel = { base: base.reload ?? sv('reload'), cur: has(mods.reload) ? mods.reload : sv('reload') };
  const regenBase = us && has(us.regen_display) ? us.regen_display : (base.regen ?? sv('regen'));
  const regen = { base: regenBase, cur: has(mods.regen) ? mods.regen : regenBase };
  let speedCur = has(mods.speed) ? mods.speed : sv('speed');
  const sp = { base: base.speed ?? sv('speed'), cur: speedCur };
  // The server's current speed already includes the charge multiplier (world.py).
  const aura = us && us.aura ? us.aura : null;
  const auraDesc = stripMarkup(u.aura_description || (us && us.aura_description));
  const auraHtml = aura ? `<div class="up-aura" ${tip(t('Aura'), auraDesc)}><span class="up-aura-ico">💪</span>${has(mods.powered_by) && mods.powered_by > 0 ? `<b>${mods.powered_by}</b>` : ''}</div>` : '';
  const chargeFillHtml = ch && chargeShown && has(mods.charge_fill) ? `<div class="hint">${t('Charge')}</div>${bar(mods.charge_fill, 'var(--accent)', t('Charge'))}` : '';
  const chargeRow = chargeShown ? row('Charge', Math.round(chargeVal), t('Charge attack') + (has(rechargeS) ? ` · ${t('Recharges in {n}s', { n: r2(rechargeS) })}` : '')) : '';
  const statsHtml = `${atk ? row('Atk', baseDelta(atk[1], atk[2]), atkTip) : ''}
    ${mArm ? row('Melee', baseDelta(mArm[1], mArm[2]), armTip) : nonZero(sv('melee_armor')) ? row('Melee', sv('melee_armor'), armTip) : ''}
    ${pArm ? row('Pierce', baseDelta(pArm[1], pArm[2]), armTip) : nonZero(sv('pierce_armor')) ? row('Pierce', sv('pierce_armor'), armTip) : ''}
    ${nonZero(rng.cur) || nonZero(rng.base) ? row('Range', baseDelta(rng.base, rng.cur)) : ''}${nonZero(sv('min_range')) ? row('Min range', sv('min_range')) : ''}
    ${nonZero(sp.cur) ? row('Speed', baseDelta(sp.base, sp.cur), mods.charging && us && us.charge_speed > 1 ? t('Charging') : '') : ''}
    ${nonZero(rel.cur) ? row('Reload', baseDelta(rel.base, rel.cur), t('Seconds between attacks')) : ''}
    ${nonZero(rng.cur) ? (nonZero(sv('accuracy')) ? row('Accuracy', (sv('accuracy') <= 1 ? Math.round(sv('accuracy') * 100) : Math.round(sv('accuracy'))) + '%') : '') + (nonZero(sv('projectiles')) ? row('Projectiles', sv('projectiles')) : '') : ''}
    ${nonZero(sv('aura_range')) ? row('Aura range', sv('aura_range'), t('Affects units within this many tiles')) : ''}
    ${nonZero(sv('blast_width')) ? row('Blast', sv('blast_width'), t('Blast radius')) : ''}${chargeRow}
    ${dot ? row('Damage over time', dot, t('Damage over time')) : ''}
    ${nonZero(regen.cur) ? row('Regen', baseDelta(regen.base, regen.cur), t('HP regenerated per minute')) : ''}`;
  // Both columns list the activities in one order (the lifetime ranking), each
  // under its own heading, so a row reads across.
  const actOrder = Object.entries((us && us.activity) || {}).sort((a, b) => b[1] - a[1]).map(([k]) => k);
  const actHtml = (acts, head) => {
    const tot = Object.values(acts || {}).reduce((a, b) => a + b, 0);
    const rows = actOrder.map((k) => `<div><span>${esc(t(k.replace('_', ' ')))}</span> ${tot ? Math.round(100 * ((acts || {})[k] || 0) / tot) + '%' : '–'}</div>`).join('');
    return `<div class="hint">${head}</div>${rows}`;
  };
  const eff = us && us.activity && Object.keys(us.activity).length
    ? `<div class="hint" style="margin-top:6px">${t('Activity')}</div><div class="grid2" style="gap:6px"><div class="up-stats" style="grid-template-columns:1fr">${actHtml(us.activity_lm, t('Last minute'))}</div><div class="up-stats" style="grid-template-columns:1fr">${actHtml(us.activity, t('Lifetime'))}</div></div>`
    : '';
  const nick = settings.entityNames[r[0]];
  // Gaia livestock and domestic animals show their last owner.
  const lo = S.view && S.view.livestock_owner;
  const lastOwner = !owner && lo ? (lo[r[0]] ?? lo[String(r[0])]) : null;
  const shownOwner = owner || lastOwner || 0;
  // Garrison: "n / capacity" (hidden for object group 12), per-unit HP bars when
  // the server sends them, else counts by type.
  let garHtml = '';
  const cap = us && has(us.garrison_capacity) ? us.garrison_capacity : u.garrison_capacity;
  const summary = us ? us.garrison_summary !== false : true;
  const gar = us && Array.isArray(us.garrison) ? us.garrison : null;
  const garPlain = s && s.garrisons ? s.garrisons[String(r[0])] : null;
  const garN = gar ? gar.length : garPlain ? garPlain.length : 0;
  const capHtml = cap > 0 && summary ? `<div class="hint up-garcap" style="margin-top:6px" ${tip(t('Garrisoned'), t('units inside / capacity'))}>⌂ ${t('Garrisoned')} ${garN} / ${cap}</div>` : garN ? `<div class="hint" style="margin-top:6px">${t('Garrisoned')} (${garN})</div>` : '';
  if (gar && gar.length) {
    const empty = cap > 0 && summary && cap <= 30 ? Array.from({ length: Math.max(0, cap - gar.length) }, () => '<div class="up-gar empty"></div>').join('') : '';
    garHtml = `${capHtml}<div class="up-garrison">${gar.map((g) => {
      const frac = g.max_hp ? g.hp / g.max_hp : 1;
      return `<div class="up-gar" ${tip(unitInfo(g.master).name, `${Math.round(g.hp)} / ${Math.round(g.max_hp || g.hp)} ${t('HP')}`)}><img src="${unitIcon(g.master)}" alt=""><div class="hpbar"><div style="width:${Math.round(frac * 100)}%"></div></div></div>`;
    }).join('')}${empty}</div>`;
  } else if (garPlain && garPlain.length) {
    garHtml = `${capHtml}<div class="up-multi">${Object.entries(garPlain.reduce((a, m) => { a[m] = (a[m] || 0) + 1; return a; }, {})).map(([m, n]) => `<div class="icon-count" ${tip(unitInfo(+m).name)}><img src="${unitIcon(+m)}" alt=""><b>${n}</b></div>`).join('')}</div>`;
  } else garHtml = capHtml;
  const isMarket = /market/i.test(u.name);
  const mk = S.view && S.view.market;
  const marketHtml = isMarket && mk ? `<div class="up-stats" style="margin-top:4px" ${tip(t('Market prices'), t('Base price in gold per 100: buying costs more and selling earns less, by the market commission'))}><div><span>${t('food')}</span> ${Math.round((mk.food || 0) * 100)}</div><div><span>${t('wood')}</span> ${Math.round((mk.wood || 0) * 100)}</div><div><span>${t('stone')}</span> ${Math.round((mk.stone || 0) * 100)}</div></div>` : '';
  const farmQ = s && (/mill|town center|folwark/i.test(u.name)) && s.farm_queue ? `<div class="hint">${t('Farm reseeds queued')}: ${s.farm_queue}</div>` : '';
  const doing = r[9] != null && ACT_NAMES[r[9]] ? ` · <b>${t(ACT_NAMES[r[9]])}</b>` : '';
  const carried = carryPairs(r[10]);
  const carry = carried.length ? `<div class="hint">${t('Carrying')} ${carried.map(([res, n]) => `${Math.round(n)} ${t(res)}`).join(' + ')}</div>` : '';
  const viewCons = S.view && S.view.construction ? S.view.construction[r[0]] ?? S.view.construction[String(r[0])] : null;
  const cons = us && has(us.construction_pct) ? us.construction_pct : viewCons;
  const consHtml = has(cons) && cons < 1 ? `<div class="hint">${t('Under construction')} ${Math.round(cons * 100)}%</div>${bar(cons, 'var(--accent)', t('Construction'))}` : '';
  const faithHtml = us && has(us.faith) ? `<div class="hint">${t('Faith')}</div>${bar(us.faith, '#b48cf0', t('Faith'))}` : '';
  const gateHtml = us && has(us.gate_locked) ? `<div class="hint">${us.gate_locked ? '🔒 ' + t('Gate locked') : '🔓 ' + t('Gate unlocked')}</div>` : '';
  const targetId = S.view?.gather_targets?.[r[0]];
  const targetRow = targetId != null ? rowForEntityId(targetId) : null;
  const targetHtml = u.cls === 4 ? `<div class="review-worker-task">${targetId != null ? `<button data-inspect="${targetId}" ${targetRow ? '' : 'disabled'} ${tip(targetRow ? t('Inspect target') : t('Target no longer present'))}>${reviewIcon('location')}${esc(targetRow ? unitInfo(targetRow[2], targetRow[1], targetRow[0]).name : t('Gathering target'))}</button>` : ''}<span ${tip(t('Lifetime idle'))}>${reviewIcon('idle')}${us?.activity ? fmtTime((us.activity.idle || 0) * 1000) : '–'}</span></div>` : '';
  const workingHtml = economic ? `${targetHtml}${prodHtml || (TOWN_CENTERS.includes(r[2]) ? `<div class="hint">${t('Idle')}</div>` : '')}${carry}${marketHtml}${farmQ}` : '';
  const numbersReady = owner <= 0 || !!us;
  const mechanics = numbersReady ? `<div class="up-stats">${statsHtml}</div>${auraHtml}` : '';
  setHtml(el, `${selectionHeader(r, { ...u, icon_url: unitIcon(r[2], r[1], r[0]) }, nick || u.name, shownOwner)}
    <div class="hpbar"><div style="width:${Math.round(r[5] * 100)}%"></div></div>
    <div class="hint">${t('HP')} ${numbersReady ? `${Math.round(r[5] * hpMax)} / ${baseDelta(base.hp ?? (sv('hp') || u.hp), hpMax)}` : '– / –'}${r[6] & 8 ? ` · <b style="color:var(--bad)">${t('idle')}</b>` : doing}${r[6] & 16 && !consHtml ? ` · ${t('under construction')}` : ''}</div>
    ${consHtml}${faithHtml}${chargeFillHtml}${gateHtml}
    ${economic && u.kind === 'building' && (nonZero(rng.cur) || us?.kills || us?.dealt) ? militaryCard([r[0]]) : ''}${workingHtml}${economic ? `<details class="review-details" data-panel-detail="mechanics"><summary>${t('Details')}</summary>${resourceTotalsHtml(us?.resource_totals, u.cls === 4)}${mechanics}${eff}${combatHtml(us)}</details>` : `${militaryCard([r[0]])}${mechanics}`}
    ${garHtml}${relevantUpgrades([r])}
    ${r[1] > 0 && u.cost && Object.keys(u.cost).length ? `<div class="hint" style="margin-top:4px">${t('Cost')}: ${costText(u.cost)}</div>` : ''}
    ${economic ? '' : `${carry}${marketHtml}${farmQ}${prodHtml}<details class="review-details" data-panel-detail="activity"><summary>${t('Details')}</summary>${eff}</details>`}`);
  const nameEl = $('up-name');
  if (nameEl) nameEl.onclick = () => {
    const inp = document.createElement('input');
    inp.value = nick || ''; inp.placeholder = u.name; inp.size = 18;
    nameEl.replaceWith(inp); inp.focus();
    const done = () => {
      if (inp.value.trim()) settings.entityNames[r[0]] = inp.value.trim(); else delete settings.entityNames[r[0]];
      saveSettings();
    };
    let cancelled = false;
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') inp.blur();
      else if (e.key === 'Escape') { cancelled = true; inp.blur(); } // Esc cancels the rename
      e.stopPropagation();
    });
    inp.addEventListener('blur', () => { if (!cancelled) done(); el._html = null; renderUnitPanel(); });
  };
}

// A group of selected units (one team's half in a split panel): who and what,
// the group's health and value, what it is doing, a row per unit type with the
// owner's upgraded numbers, and its combat record (/api/group).
const GROUP_ACTS = { 8: '⚔', 1: '➜', 0: '💤', 2: '🍖', 3: '🪵', 4: '🪙', 5: '🪨', 6: '🔨', 7: '🔧', 10: '⚙', 11: '⚗', 13: '📦', 14: '📦', 15: '✚' };
// Activity colours for the group's time bars (server ACTIVITY_NAMES).
const ACT_COLORS = {
  idle: 'var(--bad)', moving: '#6fb6ea', fighting: '#f0c94b', gather_food: 'var(--food)', gather_wood: 'var(--wood)',
  gather_gold: 'var(--gold)', gather_stone: 'var(--stone)', building: '#9d8cd6', repairing: '#9d8cd6', garrisoned: '#777',
  producing: '#8fbf6a', researching: '#8fbf6a', other: '#555', packing: '#c08850', unpacking: '#c08850',
};
// Where a group's time went: a stacked bar and its largest shares.
function timeBar(acts, label) {
  const tot = Object.values(acts || {}).reduce((a, b) => a + b, 0);
  if (!tot) return '';
  const parts = Object.entries(acts).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const name = (k) => t(k.replace('_', ' '));
  const tipText = parts.map(([k, v]) => `${name(k)} ${Math.round(100 * v / tot)}%`).join('\n');
  return `<div class="up-time" ${tip(label, tipText)}><span class="hint">${label}</span><span class="up-tbar">${parts.map(([k, v]) => `<i style="width:${(100 * v / tot).toFixed(1)}%;background:${ACT_COLORS[k] || '#555'}"></i>`).join('')}</span>
    <span class="up-tlegend">${parts.slice(0, 3).map(([k, v]) => `<b style="color:${ACT_COLORS[k] || 'inherit'}">${Math.round(100 * v / tot)}%</b> ${esc(name(k))}`).join(' · ')}</span></div>`;
}

// A present per-entity map is authoritative, even when this ID is missing/unknown.
// Only an actual old-server response lacking the field may use owner/master defaults.
function groupEntityStats(gs, r) {
  if (!gs) return { stats: null, authoritative: true };
  if (Object.prototype.hasOwnProperty.call(gs, 'entity_types')) {
    const entry = gs.entity_types && gs.entity_types[String(r[0])];
    const at = Math.round(S.view && has(S.view.time) ? S.view.time : S.t);
    const interval = gs.entity_stats_validity_version !== 1 || (entry
      && Number.isInteger(entry.valid_from_ms) && Number.isInteger(entry.valid_until_ms)
      && entry.valid_from_ms <= at && at < entry.valid_until_ms);
    const valid = interval && entry && entry.owner === r[1] && entry.master === r[2]
      && entry.stats && typeof entry.stats === 'object' && !Array.isArray(entry.stats);
    return { stats: valid ? entry.stats : null, authoritative: true };
  }
  return { stats: (gs.types && gs.types[`${r[1]}:${r[2]}`]) || null, authoritative: false };
}

function groupStatKey(stats, authoritative) {
  const st = stats || {};
  return JSON.stringify([authoritative, ...['hp', 'attack', 'melee_armor', 'pierce_armor',
    'range', 'speed', 'reload'].map((key) => st[key]),
    st.cost == null ? null : Object.entries(st.cost).sort(([a], [b]) => a.localeCompare(b))]);
}

function groupHtml(rows, deadIds, compact = false) {
  // The dead stay in the selection: their kills count, and they are its deaths.
  const gs = groupStats([...rows.map((r) => r[0]), ...deadIds], rows);
  const byOwner = new Map();
  for (const r of rows) byOwner.set(r[1], (byOwner.get(r[1]) || 0) + 1);
  // One entry per (owner, type): count, hp now / max, carried and resources left.
  const types = new Map();
  let hp = 0, hpMax = 0, unknownHP = 0, unknownValue = 0;
  const value = {}, acts = new Map(), carried = {}, left = {};
  for (const r of rows) {
    const u = unitInfo(r[2], r[1], r[0]);
    // By name: a villager's task variants (male/female gold miners) are one row.
    const resolved = groupEntityStats(gs, r);
    const st = resolved.stats || {}, authoritative = resolved.authoritative;
    const k = `${r[1]}:${u.name}:${u.icon}:${u.kind}${authoritative ? ':' + groupStatKey(resolved.stats, true) : ''}`;
    let e = types.get(k);
    if (!e) types.set(k, (e = { o: r[1], mid: r[2], mids: new Set(), ids: [], n: 0, hp: 0, max: 0, u, st, authoritative }));
    e.mids.add(r[2]); e.ids.push(r[0]);
    const mods = unitMods(r[0]) || {};
    const max = has(mods.hp_max) ? mods.hp_max : authoritative ? (st.hp ?? 0) : (st.hp || u.hp || 0);
    if (r[1] > 0 && authoritative && !has(mods.hp_max) && !has(st.hp)) unknownHP++;
    if (r[1] > 0 && authoritative && !has(st.cost)) unknownValue++;
    e.n++; e.hp += r[5] * max; e.max += max;
    if (r[1] > 0) { hp += r[5] * max; hpMax += max; }
    if (r[1] > 0) for (const [res, n] of Object.entries(st.cost || (authoritative ? {} : u.cost) || {})) if (n > 0) value[res] = (value[res] || 0) + n;
    if (r[1] > 0 && r[9] != null) acts.set(r[9], (acts.get(r[9]) || 0) + 1);
    for (const [res, n] of carryPairs(r[10])) (isResource(r) ? left : carried)[res] = ((isResource(r) ? left : carried)[res] || 0) + n;
  }
  const resList = (o) => Object.entries(o).map(([k, v]) => `<b style="color:var(--${k})">${fmtNum(Math.floor(v))}</b> ${esc(t(k))}`).join(' · ');
  const valueTot = Object.values(value).reduce((a, b) => a + b, 0);
  for (const id of deadIds) {
    const owner = S.selectionInfo.get(id)?.owner;
    if (owner != null) byOwner.set(owner, (byOwner.get(owner) || 0) + 1);
  }
  const head = `<div class="review-group-count">${t('{n} selected', { n: rows.length + deadIds.length })}${deadIds.length ? ` · ☠ ${deadIds.length}` : ''}</div>${[...byOwner.entries()].map(([o, n]) => ownerIdentity(o, n)).join('')}`;
  const hpHtml = hpMax ? `<div class="up-gsum"><span>${t('HP')} <b>${fmtNum(hp)}</b> / ${fmtNum(hpMax)}</span>${valueTot ? `<span ${tip(t('Value'), resList(value).replace(/<[^>]+>/g, ''))}>${t('Value')} <b>${fmtNum(valueTot)}</b></span>` : ''}</div>${bar(hp / hpMax, 'var(--good)', t('HP'))}` : '';
  const unknownHtml = unknownHP || unknownValue ? `<div class="hint">${unknownHP ? `${t('HP unknown')}: ${unknownHP}` : ''}${unknownHP && unknownValue ? ' · ' : ''}${unknownValue ? `${t('Value unknown')}: ${unknownValue}` : ''}</div>` : '';
  const actHtml = acts.size ? `<div class="up-acts">${[...acts.entries()].sort((a, b) => b[1] - a[1]).map(([a, n]) => `<span class="up-act${a === 0 ? ' idle' : a === 8 ? ' fight' : ''}" ${tip(t(ACT_NAMES[a] || 'other'))}>${GROUP_ACTS[a] || '·'} ${n} <small>${esc(t(ACT_NAMES[a] || 'other'))}</small></span>`).join('')}</div>` : '';
  const num = (v) => (has(v) && v !== 0 ? r2(v) : '–');
  const typeRows = [...types.values()].sort((a, b) => b.n - a.n).map((e) => {
    const st = e.st || {}, us = e.u.stats || {};
    const g = (k) => (has(st[k]) ? st[k] : e.authoritative ? null : us[k]);
    const frac = e.max ? e.hp / e.max : 1;
    return `<div class="up-trow" data-mid="${[...e.mids].join(',')}" data-owner="${e.o}" data-ids="${e.ids.join(',')}" ${tip(e.u.name, t('click: select one · Shift: select row · Ctrl: remove one · Ctrl+Shift: remove row'))}>
      <span class="up-ticon" style="outline:2px solid ${playerColor(e.o)}"><img src="${unitIcon(e.mid, e.o, e.ids[0])}" alt=""><b>${e.n}</b></span>
      <span class="up-tname">${esc(e.u.name)}<i class="up-thp"><i style="width:${Math.round(clamp(e.max ? frac : 0, 0, 1) * 100)}%"></i></i></span>
      <span ${tip(t('Attack'))}>${num(g('attack'))}</span><span ${tip(t('Melee / pierce armour'))}>${num(g('melee_armor'))}/${num(g('pierce_armor'))}</span><span ${tip(t('Range'))}>${num(g('range'))}</span>
    </div>`;
  }).join('');
  const tableHtml = `<div class="up-types"><div class="up-trow up-thead"><span></span><span></span><span>${t('Atk')}</span><span>${t('Arm')}</span><span>${t('Rng')}</span></div>${typeRows}${deadIds.length ? `<div class="up-multi">${deadIds.map(deadIcon).join('')}</div>` : ''}</div>`;
  const tot = gs && gs.totals;
  const deaths = tot ? tot.deaths || 0 : 0;
  // K/D: kills per death; with none lost yet, the kills themselves.
  const kd = tot && (tot.kills || deaths) ? (deaths ? (tot.kills / deaths).toFixed(tot.kills / deaths < 10 ? 2 : 1) : `${fmtNum(tot.kills)} : 0`) : '';
  const combat = tot && (tot.kills || deaths || tot.dealt || tot.taken || tot.conversions)
    ? `<div class="up-stats" style="margin-top:4px"><div><span>${t('Kills')}</span> ${fmtNum(tot.kills)}${tot.eco_kills ? ` <small>(${fmtNum(tot.eco_kills)} ${t('eco')})</small>` : ''}</div><div><span>${t('Deaths')}</span> ${fmtNum(deaths)}</div><div ${tip(t('K/D'), t('Kills per death of this selection (units that died while selected count)'))}><span>${t('K/D')}</span> ${kd || '–'}</div><div><span>${t('Dealt')}</span> ${fmtNum(tot.dealt)}</div><div><span>${t('Taken')}</span> ${fmtNum(tot.taken)}</div>${tot.conversions ? `<div><span>${t('Conversions')}</span> ${tot.conversions}</div>` : ''}</div>`
    : '';
  const timeHtml = gs ? `${timeBar(gs.activity_lm, t('Last minute'))}${timeBar(gs.activity, t('Lifetime'))}` : '';
  const carriedHtml = Object.keys(carried).length ? `<div class="hint">${t('Carrying')}: ${resList(carried)}</div>` : '';
  const leftHtml = Object.keys(left).length ? `<div class="hint">${t('Left')}: ${resList(left)}</div>` : '';
  const detailKey = `owner-${[...byOwner.keys()].sort((a, b) => a - b).join('-')}`;
  const record = militaryCard([...rows.map((r) => r[0]), ...deadIds]);
  if (compact) return `${[...byOwner.entries()].map(([owner, count]) => ownerIdentity(owner, count)).join('')}${record}<details class="review-details" data-panel-detail="${detailKey}-units"><summary>${t('Units & upgrades')}</summary>${hpHtml}${unknownHtml}${actHtml}${tableHtml}${relevantUpgrades(rows)}${combat}${timeHtml}${carriedHtml}${leftHtml}</details>`;
  return `${head}${hpHtml}${unknownHtml}${record}${actHtml}${tableHtml}<details class="review-details" data-panel-detail="${detailKey}-lifetime"><summary>${t('Lifetime details')}</summary>${combat}${timeHtml}</details>${relevantUpgrades(rows)}${carriedHtml}${leftHtml}`;
}

// Combat totals and per-type statistics of a group, refreshed once a second.
const groupCache = new Map();
function groupStats(ids, rows = []) {
  const generation = S.session && S.session.generation;
  const at = Math.round(S.view && has(S.view.time) ? S.view.time : S.t);
  const canonical = [...new Set(ids)].sort((a, b) => a - b);
  const wanted = canonical.filter((id) => id >= 0).slice(0, 600);
  const key = `${generation}:${canonical.join(',')}`;
  const now = performance.now();
  let c = groupCache.get(key);
  if (!c) {
    if (groupCache.size > 8) groupCache.delete(groupCache.keys().next().value);
    c = { data: null, queryAt: null, started: 0, sequence: 0, pending: false, failed: false };
    groupCache.set(key, c);
  }
  const bounded = c.data && c.data.entity_stats_validity_version === 1;
  const identities = new Map(rows.map((r) => [r[0], r]));
  const valid = bounded ? wanted.every((id) => {
    const e = c.data.entity_types && c.data.entity_types[String(id)], r = identities.get(id);
    return e && (!r || (e.owner === r[1] && e.master === r[2]))
      && Number.isInteger(e.valid_from_ms) && Number.isInteger(e.valid_until_ms)
      && e.valid_from_ms <= at && at < e.valid_until_ms;
  }) : c.data && legacyStatsFresh(c.queryAt, at);
  // Genuine stats/source changes may refresh immediately. Mere keyframe turnover
  // does not invalidate a proven interval; activity/totals refresh at most1Hz wall.
  const due = !valid || now - c.started >= 1000;
  if (!c.pending && due && (!c.failed || now - c.started >= 1000)) {
    c.started = now; c.pending = true; c.failed = false;
    const sequence = ++c.sequence;
    fetch(`/api/group?ids=${wanted.join(',')}&t=${at}`, { priority: 'low' }).then((r) => r.json()).then((d) => {
      if (groupCache.get(key) !== c || c.sequence !== sequence
          || (S.session && S.session.generation) !== generation) return;
      // A bounded response must identify the server Timeline's actual generation.
      if ((d.entity_stats_validity_version === 1 && d.generation !== generation)
          || (d.generation != null && d.generation !== generation)) { c.failed = true; return; }
      c.data = d; c.queryAt = at;
    }).catch(() => { c.failed = true; }).finally(() => {
      if (groupCache.get(key) === c && c.sequence === sequence) c.pending = false;
    });
  }
  // Preserve bounded data during refresh. The renderer checks each interval and
  // owner/MID, so expired/unknown entries cannot revive a shared/catalog fallback.
  return bounded || valid ? c.data : null;
}

let unitRows = [];
export function renderUnitPanel() {
  const el = $('unitpanel');
  wireReviewControls(el);
  delegate(el, 'click', '[data-full-tree]', (d) => { pinnedTree = true; showTechTree(+d.dataset.fullTree); });
  delegate(el, 'click', '.review-upgrade', techClick);
  delegate(el, 'click', '[data-inspect]', (d) => {
    const id = +d.dataset.inspect, row = rowForEntityId(id);
    if (row) { S.selection = new Set([row[0]]); centerOn(row[3], row[4]); }
  });
  delegate(el, 'click', '[data-gatherers]', (d) => {
    const target = +d.dataset.gatherers, owner = +d.dataset.owner;
    S.selection = new Set(currentRows().filter((row) => row[1] === owner && row[0] !== target
      && S.view?.gather_targets?.[row[0]] === target).map((row) => row[0]));
  });
  delegate(el, 'click', '[data-mid]', (d, ev) => {
    const mids = d.dataset.mid.split(',').map(Number), o = +d.dataset.owner;
    const rows = unitRows;
    const ids = d.dataset.ids == null ? null : new Set(d.dataset.ids.split(',').map(Number));
    const match = (r) => ids ? ids.has(r[0]) : mids.includes(r[2]) && r[1] === o;
    if (ev.ctrlKey && ev.shiftKey) S.selection = new Set(rows.filter((r) => !match(r)).map((r) => r[0]));
    else if (ev.shiftKey) S.selection = new Set(rows.filter(match).map((r) => r[0]));
    else if (ev.ctrlKey) { const one = rows.find(match); if (one) S.selection.delete(one[0]); }
    else { const one = rows.find(match); if (one) S.selection = new Set([one[0]]); }
  });
  const live = selectedRows();
  const liveIds = new Set(live.map((r) => r[0]));
  const dead = settings.keepDeadInSelection ? [...S.selection].filter((id) => !liveIds.has(id) && S.selectionInfo.has(id)) : [];
  unitRows = live;
  el.classList.remove('split');
  if (!live.length && !dead.length) {
    // A skin's alwaysShowUnitPanel (true/false) overrides the setting; null/absent defers to it.
    const always = skinOption('alwaysShowUnitPanel');
    if ((always ?? settings.showUnitPanelWhenNothingSelected) && S.view) { el.classList.remove('hidden'); gaiaPanel(el); return; }
    el.classList.add('hidden'); return;
  }
  el.classList.remove('hidden');
  if (live.length === 1 && !dead.length) { singlePanel(el, live[0]); return; }
  // Keep each owner's identity and results separate, including same-team owners.
  const groups = new Map();
  for (const r of live) {
    const k = r[1];
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  }
  for (const id of dead) {
    const owner = S.selectionInfo.get(id)?.owner;
    if (owner != null && !groups.has(owner)) groups.set(owner, []);
  }
  if (groups.size >= 2) {
    const order = players().map((p) => p.id);
    const keys = [...groups.keys()].sort((a, b) => ((order.indexOf(a) + 1) || 99) - ((order.indexOf(b) + 1) || 99));
    el.classList.remove('split');
    setHtml(el, `<div class="up-sides">${keys.map((k) => {
      const deadHere = dead.filter((id) => S.selectionInfo.get(id)?.owner === k);
      return `<div class="up-side">${groupHtml(groups.get(k), deadHere, true)}</div>`;
    }).join('')}</div>`);
    return;
  }
  setHtml(el, groupHtml(live, dead));
}

const unitStatCache = new Map();
function unitStats(id, row) {
  const generation = S.session && S.session.generation;
  const at = Math.round(S.view && has(S.view.time) ? S.view.time : S.t);
  const key = `${generation}:${id}`, now = performance.now();
  let c = unitStatCache.get(key);
  if (!c) {
    if (unitStatCache.size > 8) unitStatCache.delete(unitStatCache.keys().next().value);
    c = { data: null, queryAt: null, started: 0, sequence: 0, pending: false, failed: false };
    unitStatCache.set(key, c);
  }
  const valid = entityStatsValid(c.data, id, row, at, generation, c.queryAt);
  const usable = valid || entityStatsUsable(c.data, id, row, at, generation, c.queryAt);
  if (!c.pending && (!valid || now - c.started >= 1000) && (!c.failed || now - c.started >= 1000)) {
    c.started = now; c.pending = true; c.failed = false;
    const sequence = ++c.sequence;
    fetch(`/api/unit/${id}?t=${at}`, { priority: 'low' }).then((r) => r.json()).then((d) => {
      if (unitStatCache.get(key) !== c || c.sequence !== sequence
          || (S.session && S.session.generation) !== generation) return;
      if ((d.entity_stats_validity_version === 1 && d.generation !== generation)
          || (d.generation != null && d.generation !== generation)) { c.failed = true; return; }
      c.data = d; c.queryAt = at;
    }).catch(() => { c.failed = true; }).finally(() => {
      if (unitStatCache.get(key) === c && c.sequence === sequence) c.pending = false;
    });
  }
  return usable ? c.data : null;
}

// -- resources left --------------------------------------------------------------------------

export function renderResourcesLeft(show) {
  const el = $('resleft');
  if (!show) { el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  const rows = S.series && S.series['0'];
  if (!rows || !rows.length) { setHtml(el, `<span class="hint">${t('no data yet')}</span>`); return; }
  let r = rows[0];
  for (const x of rows) { if (x.t <= S.t) r = x; else break; }
  setHtml(el, `<div class="title">${t('Resources left on map')}</div>
    <div style="color:var(--food)">${t('Food')} ${fmtNum(r.food)}</div><div style="color:var(--wood)">${t('Wood')} ${fmtNum(r.wood)}</div>
    <div style="color:var(--gold)">${t('Gold')} ${fmtNum(r.gold)}</div><div style="color:var(--stone)">${t('Stone')} ${fmtNum(r.stone)}</div>
    <div>${t('Relics')} ${r.relics}</div>`);
}

// -- time controls -----------------------------------------------------------------------------

export function renderTimebar() {
  const sp = SPEEDS[S.speedIndex];
  setText($('tc-speed'), (S.playing ? '' : '❚❚ ') + (sp < 0 ? '◀ ' : '') + Math.abs(sp) + '×');
  setText($('tc-play'), S.playing ? '⏸' : '▶');
  // The shuttle buttons light up while playing fast in their direction.
  $('tc-rew').classList.toggle('on', S.playing && sp < 0);
  $('tc-ff').classList.toggle('on', S.playing && sp > 1);
  setText($('tc-clock'), `${fmtTime(S.t)} / ${fmtTime(S.end)}`);
  $('tc-live').classList.toggle('on', S.session && S.session.mode === 'live' && S.followLive);
  $('tc-live').classList.toggle('hidden', !(S.session && S.session.mode === 'live'));
  drawScrub();
}

// The time bar's size, kept by a ResizeObserver (getBoundingClientRect on every
// redraw forced a layout four times a second).
let scrubSize = null;
export function drawScrub() {
  const c = $('scrub-canvas');
  if (!scrubSize) {
    scrubSize = c.getBoundingClientRect();
    new ResizeObserver(() => { scrubSize = c.getBoundingClientRect(); }).observe(c);
  }
  const r = scrubSize;
  if (!r.width) return;
  const dpr = window.devicePixelRatio || 1;
  if (c.width !== Math.round(r.width * dpr)) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); }
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = r.width, H = r.height;
  g.clearRect(0, 0, W, H);
  const span = Math.max(1, S.end - S.start);
  const xOf = (t) => ((t - S.start) / span) * W;
  g.fillStyle = 'rgba(255,255,255,.08)';
  g.fillRect(0, H / 2 - 3, W, 6);
  g.fillStyle = 'rgba(217,180,90,.55)';
  g.fillRect(0, H / 2 - 3, xOf(S.t), 6);
  for (let i = 0; i < S.events.length; i++) {
    const e = S.events[i];
    if (ageUpRepeat(S.events, i)) continue; // one tick per age
    if (e.cat !== 'age' && e.cat !== 'status' && e.cat !== 'victory' && !(e.kind === 'kill' && e.victim && (e.victim.kind === 'building'))) continue;
    g.fillStyle = playerColor(e.player);
    g.fillRect(xOf(e.t) - 1, e.cat === 'age' ? 2 : H - 8, 2, 6);
  }
  for (const b of S.bookmarks) {
    g.fillStyle = '#6fb3d2';
    g.beginPath(); g.moveTo(xOf(b), 0); g.lineTo(xOf(b) + 5, 5); g.lineTo(xOf(b), 10); g.fill();
  }
  g.fillStyle = '#fff';
  g.fillRect(xOf(S.t) - 1, 0, 2, H);
}

export function scrubTime(ev) {
  const c = $('scrub-canvas');
  const r = c.getBoundingClientRect();
  const f = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
  return S.start + f * (S.end - S.start);
}

export { player, setText };
