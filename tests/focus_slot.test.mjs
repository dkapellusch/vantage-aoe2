import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
const canvas = { getContext: () => new Proxy({}, { get: () => () => {} }), style: {}, addEventListener() {} };
globalThis.document = { getElementById: () => canvas, createElement: () => canvas, addEventListener() {}, documentElement: { style: { setProperty() {} } } };
globalThis.window = { addEventListener() {}, devicePixelRatio: 1, innerWidth: 1920, innerHeight: 1080 };
const { S } = await import('../src/vantage/web/state.js');
const { ecoRows, sideEfficiency, fightLabel } = await import('../src/vantage/web/focus-slot.js');
const { METRICS } = await import('../src/vantage/web/metrics.js');
const F = await import('../src/vantage/web/fights.js');
const M = await import('../src/vantage/web/hud-model.js');

// Villager-seconds as timeline.py integrates them: 3 of 4 working, and 1 of 4.
const eff = (pct, all, pctLm = pct, lm = all) => ({ pct, pct_lm: pctLm, all, last_minute: lm });
const player = (o) => ({ resources: { food: 100, wood: 50, gold: 0, stone: 0 }, tasks: { food: 3, wood: 2 }, idle_villagers: 1, ...o });

test('Eco card: bonus resources, idle TC time and worker efficiency, beside the old rows', () => {
  S.view = { players: {
    1: player({ collected_rate: { total: 600 }, collected: { total: 4000 }, resource_income: { total: 350.4 }, tc_idle_seconds: 75, efficiency: eff(75, { gather_food: 300, idle: 100 }, 50, { gather_wood: 30, moving: 30 }) }),
    2: player({ collected_rate: { total: 500 }, collected: { total: 3800 }, resource_income: { total: 200 }, tc_idle_seconds: 12, efficiency: eff(60, { building: 60, idle: 40 }, 90, { gather_gold: 54, idle: 6 }) }),
  } };
  const rows = ecoRows([{ players: [{ id: 1 }], solo: true }, { players: [{ id: 2 }], solo: true }]);
  assert.deepEqual(rows.map((r) => r.label), ['Gatherers F / W / G / S', 'Collection rate', 'Collected', 'Bonus resources', 'Idle villagers', 'Idle TC (growth)', 'Worker efficiency (last minute)', 'Worker efficiency (whole game)', 'Banked']);
  const by = Object.fromEntries(rows.map((r) => [r.label, r]));
  // Labels, details and series come from the metric registry.
  assert.equal(by['Bonus resources'].detail, METRICS.bonus.detail);
  assert.equal(by['Bonus resources'].series, 'bonus_total');
  assert.deepEqual(by['Bonus resources'].text, ['350', '200']);
  const tc = by[METRICS.tc_idle.label];
  assert.deepEqual(tc.values, [75, 12]); assert.deepEqual(tc.text, ['1:15', '0:12']);
  assert.equal(tc.lower, true); assert.equal(tc.warnWorst, true); assert.equal(tc.series, 'tc_idle');
  assert.deepEqual(by['Worker efficiency (last minute)'].values, [50, 90]);
  assert.deepEqual(by['Worker efficiency (last minute)'].text, ['50%', '90%']);
  assert.equal(by['Worker efficiency (last minute)'].series, 'efficiency_lm');
  assert.deepEqual(by['Worker efficiency (whole game)'].values, [75, 60]);
  assert.equal(by['Worker efficiency (whole game)'].series, 'efficiency');
  assert.ok(!rows.some((r) => /\/min|per minute/i.test(r.label) && r.label !== METRICS.rate.label), 'no per-resource rate rows');
});

test('a team side pools its players\' villager time: efficiency is an average, never a sum', () => {
  // 30 villagers at 3/4 working, 10 at 1/4: (2250 + 250) / (3000 + 1000) = 62.5 %, not 125 % and not 50 %.
  const big = { efficiency: eff(75, { gather_food: 2000, building: 250, idle: 600, moving: 150, garrisoned: 900 }) };
  const small = { efficiency: eff(25, { gather_gold: 250, idle: 750 }) };
  assert.equal(sideEfficiency([big, small], 'all'), 62.5);
  assert.equal(sideEfficiency([big, small], 'last_minute'), 62.5);
  // One player: the game's own figure.
  assert.equal(sideEfficiency([small], 'all'), 25);
  // No villager time at all yet: no value, not 0 %.
  assert.equal(sideEfficiency([{ efficiency: eff(0, {}) }, { efficiency: eff(0, {}) }]), null);
  // A player without the breakdown: the plain mean of the percentages.
  assert.equal(sideEfficiency([big, { efficiency: { pct: 25, pct_lm: 25 } }], 'all'), 50);
  assert.equal(sideEfficiency([{}, null], 'all'), null);
  assert.equal(sideEfficiency([big, {}], 'all'), 75, 'a player without the stat is left out');

  S.view = { players: { 1: { ...big, tasks: {} }, 2: { ...small, tasks: {} }, 3: { efficiency: eff(50, { gather_food: 50, idle: 50 }), tasks: {} } } };
  const rows = ecoRows([{ players: [{ id: 1 }, { id: 2 }] }, { players: [{ id: 3 }] }]);
  const row = rows.find((r) => r.label === 'Worker efficiency (whole game)');
  assert.deepEqual(row.values, [62.5, 50]);
  assert.deepEqual(row.text, ['63%', '50%']);
});

const kill = (t, owner, master, cost) => ({ t, kind: 'kill', cat: 'combat', friendly: false, x: 10, y: 20, victim: { owner, master, kind: 'unit', cost } });

test('the Fight card lists every fight begun so far, newest first, the one under way cut at now', () => {
  const events = [
    kill(10000, 2, 93, { food: 35, wood: 25 }), kill(14000, 2, 93, { food: 35, wood: 25 }), kill(19000, 1, 448, { food: 80 }),
    { t: 30000, kind: 'age_up', cat: 'age' },
    kill(100000, 1, 4, { food: 25, wood: 45 }), kill(104000, 2, 4, { food: 25, wood: 45 }), kill(108000, 2, 4, { food: 25, wood: 45 }),
    kill(400000, 1, 4, { food: 25, wood: 45 }), kill(401000, 1, 4, { food: 25, wood: 45 }),
  ];
  const all = F.findFights(events);
  assert.equal(all.length, 3);
  assert.deepEqual(F.fightsUpTo(events, all, 5000), [], 'no fight yet');
  assert.deepEqual(F.fightsUpTo(events, all, 12000), [], 'one kill is not a fight yet');
  assert.deepEqual(F.fightsUpTo(events, all, 14000).map((f) => [f.from, f.to, f.kills]), [[10000, 14000, 2]], 'the kill still to come is not shown');
  const mid = F.fightsUpTo(events, all, 105000);
  assert.deepEqual(mid.map((f) => [f.from, f.to, f.kills, f.value]), [[100000, 104000, 2, 140], [10000, 19000, 3, 200]]);
  assert.equal(mid[1], all[0], 'a finished fight is the cached object');
  // Long after: every fight stays listed (no 45-second cut-off).
  const late = F.fightsUpTo(events, all, 3600000);
  assert.deepEqual(late.map((f) => f.from), [400000, 100000, 10000]);
  assert.deepEqual(late, [...all].reverse());
  assert.equal(fightLabel(all[1]), '1:40–1:48 · 3 kills · 210 res');
  assert.equal(fightLabel({ ...all[0], from: 754000, to: 790000, kills: 23, value: 4120 }), '12:34–13:10 · 23 kills · 4120 res');
});

test('a saved Tech card reads as the Fight card; the cycle has no Tech card', () => {
  assert.equal(M.normalizeHud({ focus: 'techs' }).focus, 'fight');
  for (const card of ['production', 'eco', 'fight', 'none']) assert.equal(M.normalizeHud({ focus: card }).focus, card);
  assert.equal(M.normalizeHud({ focus: 'nonsense' }).focus, 'production');
  const app = readFileSync(new URL('../src/vantage/web/app.js', import.meta.url), 'utf8');
  assert.match(app, /const FOCUS_CARDS = \['production', 'eco', 'fight', 'none'\];/);
});
