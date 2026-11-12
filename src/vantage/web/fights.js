// Fights and key events, found in the event log: kills closer together than GAP form one
// fight. Each fight carries what every player lost (units, resource value,
// by unit type), so the Match story can size its bar by resources lost and the
// Focus slot can print a recap. Pure; cached per event list by the callers.

import { TOWN_CENTERS, GOTO_BUILDINGS } from './games.js';

const GAP_MS = 10000;
const MIN_KILLS = 2;

const costOf = (ref) => { const c = ref && ref.cost; return c ? (c.food || 0) + (c.wood || 0) + (c.gold || 0) + (c.stone || 0) : 0; };

/** [{ from, to, kills, value, x, y, lost: { pid: { n, value, masters: { mid: n } } } }], oldest first. */
export function findFights(events, gap = GAP_MS, minKills = MIN_KILLS) {
  const fights = [];
  let cur = null;
  const close = () => { if (cur && cur.kills >= minKills) { cur.x /= cur.kills; cur.y /= cur.kills; fights.push(cur); } cur = null; };
  for (const e of events || []) {
    if (e.kind !== 'kill' || e.friendly || !e.victim) continue;
    if (cur && e.t - cur.to > gap) close();
    if (!cur) cur = { from: e.t, to: e.t, kills: 0, value: 0, x: 0, y: 0, lost: {} };
    const v = e.victim, value = costOf(v);
    cur.to = e.t; cur.kills++; cur.value += value;
    cur.x += Number.isFinite(e.x) ? e.x : 0; cur.y += Number.isFinite(e.y) ? e.y : 0;
    const side = cur.lost[v.owner] || (cur.lost[v.owner] = { n: 0, value: 0, masters: {} });
    side.n++; side.value += value;
    side.masters[v.master] = (side.masters[v.master] || 0) + 1;
  }
  close();
  return fights;
}

/** The fight to recap at time `at`: the one under way, or the last that ended within `keep` ms. */
export function fightForRecap(fights, at, keep = 45000) {
  for (let i = fights.length - 1; i >= 0; i--) {
    const f = fights[i];
    if (f.from > at) continue;
    return at - f.to <= keep ? f : null;
  }
  return null;
}

let cache = { events: null, n: -1, fights: [] };
/** findFights, recomputed only when the event list grows or is replaced. */
export function fightsOf(events) {
  if (cache.events !== events || cache.n !== events.length) cache = { events, n: events.length, fights: findFights(events) };
  return cache.fights;
}

// -- key events (the Event ticker) -------------------------------------------------------------

const CASTLES = () => GOTO_BUILDINGS.gotoCastle || [];
const WONDER = 276;
/** A key event: an age-up, a resignation or win, a wonder or countdown, a town centre or castle lost. */
export function isKeyEvent(e) {
  if (e.kind === 'kill') return !!e.victim && e.victim.kind === 'building' && (TOWN_CENTERS.includes(e.victim.master) || CASTLES().includes(e.victim.master) || e.victim.master === WONDER);
  if (e.cat === 'age') return e.kind === 'age_up';
  return e.cat === 'status' || e.cat === 'victory' || e.kind === 'countdown';
}

/** The key events to show at `at`: the last `lines` within the window, with their age as 0..1. */
export function tickerEvents(events, at, windowMs, lines = 2) {
  const out = [];
  for (let i = events.length - 1; i >= 0 && out.length < lines; i--) {
    const e = events[i];
    if (e.t > at) continue;
    if (e.t < at - windowMs) break;
    if (isKeyEvent(e)) out.push({ e, age: (at - e.t) / windowMs });
  }
  return out.reverse();
}
