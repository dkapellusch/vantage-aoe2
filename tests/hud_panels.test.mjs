import assert from 'node:assert/strict';
import { test } from 'node:test';
globalThis.window = { addEventListener() {}, innerWidth: 1920, innerHeight: 1080 };
globalThis.document = { getElementById() { return null; }, addEventListener() {}, documentElement: { style: { setProperty() {} } } };
const { METRICS, metricLabel, seriesMetricLabel, KILLS_LOSSES } = await import('../src/vantage/web/metrics.js');
const { SECTIONS } = await import('../src/vantage/web/team-board.js');
const { cellModel } = await import('../src/vantage/web/pulse-model.js');
const F = await import('../src/vantage/web/fights.js');
const ST = await import('../src/vantage/web/story-model.js');
const { rank } = await import('../src/vantage/web/compare-table.js');
const { applyGame, TOWN_CENTERS } = await import('../src/vantage/web/games.js');
const { readFileSync } = await import('node:fs');
const web = (name) => readFileSync(new URL(`../src/vantage/web/${name}`, import.meta.url), 'utf8');

test('one name per metric: the Team board, the dashboard and Statistics use the registry', () => {
  assert.equal(metricLabel('army_value'), 'Army value');
  assert.equal(seriesMetricLabel('army_value'), 'Army value');
  assert.equal(seriesMetricLabel('military'), 'Military');
  assert.equal(seriesMetricLabel('deaths'), 'Losses');
  assert.equal(seriesMetricLabel('col_total'), 'Collected');
  assert.equal(seriesMetricLabel('unknown_series'), null);
  const rows = SECTIONS.flatMap((s) => s.rows).filter((r) => r.id);
  assert.deepEqual(rows.map((r) => r.id), ['villagers', 'military', 'army_value', 'idle_villagers', 'rate', 'collected', 'population', 'kills', 'losses']);
  for (const r of rows.filter((x) => !x.strong)) assert.equal(r.label, METRICS[r.id].label, r.id);
  // The names that drifted are gone from the panels.
  const panels = web('panels.js'), overlays = web('overlays.js');
  for (const old of ["'Mil value'", "'K / D'", "'Vils'"]) assert.ok(!panels.includes(old), `${old} in panels.js`);
  for (const old of ["'Military value'", "'Military units',", "'Resources collected'"]) assert.ok(!overlays.includes(`army_value: ${old}`) && !overlays.includes(`military: ${old}`) && !overlays.includes(`col_total: ${old}`), old);
  assert.match(panels, /milValue: \{ h: METRICS\.army_value\.label/);
  assert.equal(KILLS_LOSSES.label, 'Kills / Losses');
  assert.ok(!web('layout.js').includes("'Team overview'"), 'the panel is the Team board everywhere');
});

test('a Pulse cell: the value, a delta on the leading side only, warnings, and a spoken label', () => {
  const a = [{ army_value: 1360, idle_villagers: 3, pop: 59, pop_cap: 85, villagers: 40, housed: false }];
  const b = [{ army_value: 1310, idle_villagers: 1, pop: 59, pop_cap: 60, villagers: 40, housed: true }];
  const lead = cellModel('army', a, b, 1), trail = cellModel('army', b, a, 1);
  assert.equal(lead.shown, '1360'); assert.equal(lead.delta, '50'); assert.equal(lead.series, 'army_value');
  assert.equal(lead.spoken, 'Army value 1360, ahead by 50');
  assert.equal(trail.delta, null); assert.equal(trail.spoken, 'Army value 1310');
  // Idle turns amber above two per player (as on the Team board); no delta where lower is better.
  const idle = cellModel('idle', a, b, 1);
  assert.equal(idle.warn, true); assert.equal(idle.delta, null); assert.equal(idle.spoken, 'Idle villagers 3, more than 2 per player');
  assert.equal(cellModel('idle', b, a, 1).warn, false);
  assert.equal(cellModel('idle', [{ idle_villagers: 2 }], null, 1).warn, false, 'two idle in a 1v1 is ordinary');
  assert.equal(cellModel('idle', [{ idle_villagers: 4 }, { idle_villagers: 0 }], null, 2).warn, false, 'a team of two needs five');
  // Population: the cap, and housed is said as well as shown.
  const pop = cellModel('pop', b, a, 1);
  assert.equal(pop.cap, 60); assert.equal(pop.housed, true); assert.equal(pop.spoken, 'Population 59 of 60, Housed');
  assert.equal(cellModel('vil', a, b, 1).delta, null, 'equal sides have no delta');
  assert.equal(cellModel('army', [{}], b, 1), null, 'a stat the recording lacks leaves its cell out');
  assert.equal(cellModel('army', a, null, 1).delta, null, 'a free-for-all has no opposing side');
  assert.equal(cellModel('nope', a, b, 1), null);
});

const kill = (t, owner, master, cost, extra = {}) => ({ t, kind: 'kill', cat: 'combat', friendly: false, x: 10, y: 20, victim: { owner, master, kind: 'unit', cost }, ...extra });

test('fights: kills within ten seconds form one, with what each side lost', () => {
  const events = [
    kill(10000, 2, 93, { food: 35, wood: 25 }), kill(14000, 2, 93, { food: 35, wood: 25 }), kill(19000, 1, 448, { food: 80 }),
    { t: 20000, kind: 'trained', cat: 'train_research' },
    kill(60000, 1, 83, { food: 50 }), // alone: not a fight
    kill(100000, 2, 83, { food: 50 }), kill(101000, 1, 83, { food: 50 }, { friendly: true }), kill(105000, 2, 74, { food: 60, gold: 20 }),
  ];
  const fights = F.findFights(events);
  assert.equal(fights.length, 2);
  assert.deepEqual({ from: fights[0].from, to: fights[0].to, kills: fights[0].kills, value: fights[0].value }, { from: 10000, to: 19000, kills: 3, value: 200 });
  assert.deepEqual(fights[0].lost, { 2: { n: 2, value: 120, masters: { 93: 2 } }, 1: { n: 1, value: 80, masters: { 448: 1 } } });
  assert.equal(fights[1].kills, 2, 'a friendly kill is not counted');
  assert.equal(fights[1].value, 130);
  assert.deepEqual(F.findFights([]), []);
  // The Fight card lists them all, newest first, with no cut-off after a fight ends (focus_slot.test.mjs).
  assert.deepEqual(F.fightsUpTo(events, fights, 200000), [fights[1], fights[0]]);
  assert.deepEqual(F.fightsUpTo(events, fights, 5000), []);
  assert.equal(F.fightsOf(events), F.fightsOf(events), 'cached per event list');
});

test('the Event ticker keeps key events only, the last two, within its window', () => {
  applyGame('aoe2');
  assert.ok(TOWN_CENTERS.length);
  const tc = kill(50000, 1, TOWN_CENTERS[0], {}, { victim: { owner: 1, master: TOWN_CENTERS[0], kind: 'building' } });
  const events = [
    { t: 10000, cat: 'age', kind: 'age_up', player: 1, age: 1 }, { t: 10000, cat: 'age', kind: 'researched', player: 1 },
    { t: 30000, cat: 'train_research', kind: 'trained', player: 1 }, kill(40000, 2, 83, { food: 50 }),
    tc, { t: 52000, cat: 'status', kind: 'resigned', player: 2 }, { t: 53000, cat: 'chat', kind: 'chat', player: 2 }, { t: 60000, cat: 'age', kind: 'age_up', player: 2, age: 1 },
  ];
  assert.deepEqual(events.filter(F.isKeyEvent).map((e) => e.t), [10000, 50000, 52000, 60000]);
  const at = F.tickerEvents(events, 55000, 13600);
  assert.deepEqual(at.map((x) => x.e.t), [50000, 52000]);
  assert.ok(at[0].age > at[1].age && at[1].age > 0 && at[0].age < 1);
  assert.deepEqual(F.tickerEvents(events, 100000, 13600), [], 'old events have faded');
  assert.deepEqual(F.tickerEvents(events, 60000, 100000).map((x) => x.e.t), [52000, 60000], 'two lines at most');
  assert.deepEqual(F.tickerEvents(events, 5000, 13600), []);
});

test('the Match story: lead curve, idle-TC spans, age marks, and values at a time', () => {
  const series = {
    1: [{ t: 0, army_value: 0, tc_idle: 0 }, { t: 5000, army_value: 100, tc_idle: 0 }, { t: 10000, army_value: 300, tc_idle: 4 }, { t: 15000, army_value: 300, tc_idle: 9 }, { t: 20000, army_value: 50, tc_idle: 9 }],
    2: [{ t: 0, army_value: 0, tc_idle: 0 }, { t: 5000, army_value: 150, tc_idle: 0 }, { t: 10000, army_value: 150, tc_idle: 0 }, { t: 15000, army_value: 200, tc_idle: 0 }, { t: 20000, army_value: 400, tc_idle: 2 }],
    3: [{ t: 0, army_value: 10 }, { t: 10000, army_value: 20 }],
  };
  const a = { players: [{ id: 1 }] }, b = { players: [{ id: 2 }, { id: 3 }] };
  assert.equal(ST.rowAt(series[1], 12000).t, 10000);
  assert.equal(ST.rowAt(series[1], -1), null);
  assert.equal(ST.rowAt([], 5), null);
  assert.equal(ST.sideValue(series, b, 'army_value', 12000), 170, 'a team is the sum of its players');
  assert.equal(ST.sideValue(series, a, 'missing', 12000), null);
  assert.deepEqual(ST.leadCurve(series, a, b), [{ t: 0, d: -10 }, { t: 5000, d: -60 }, { t: 10000, d: 130 }, { t: 15000, d: 80 }, { t: 20000, d: -370 }]);
  assert.deepEqual(ST.growthSpans(series[1], 'tc_idle'), [{ from: 5000, to: 15000 }]);
  assert.deepEqual(ST.growthSpans(series[2], 'tc_idle'), [{ from: 15000, to: 20000 }]);
  assert.deepEqual(ST.growthSpans(undefined, 'tc_idle'), []);
  const ages = ST.ageMarks([{ t: 1, kind: 'age_up', player: 1, age: 1 }, { t: 2, kind: 'researched', player: 1 }, { t: 3, kind: 'age_up', player: 1, age: 1 }, { t: 9, kind: 'age_up', player: 2, age: 1 }]);
  assert.deepEqual(ages, [{ t: 1, player: 1, age: 1 }, { t: 9, player: 2, age: 1 }]);
});

test('side-against-side tables mark the best column and the worst', () => {
  assert.deepEqual(rank([3, 8]), { best: 1, worst: 0 });
  assert.deepEqual(rank([3, 8], true), { best: 0, worst: 1 });
  assert.deepEqual(rank([5, 5]), { best: null, worst: null });
  assert.deepEqual(rank([null, 5]), { best: null, worst: null });
  assert.deepEqual(rank([4, null, 9, 1], true), { best: 3, worst: 2 });
  // A gap within the row's margin is a tie: 89 % against 90 % is not a lead.
  assert.deepEqual(rank([89, 90], false, 3), { best: null, worst: null });
  assert.deepEqual(rank([84, 90], false, 3), { best: 1, worst: 0 });
});

test('the Statistics window and other placed panels stay inside the window; edges resize one axis', async () => {
  const { fitRect, resizeRect, moveRect } = await import('../src/vantage/web/panel-resize.js');
  const vp = { width: 1920, height: 1080 }, win = { left: 365, top: 151, width: 1190, height: 778 };
  // Dragged far off any side, the title bar stays reachable.
  for (const [dx, dy] of [[-5000, 0], [5000, 0], [0, -5000], [0, 5000], [5000, 5000]]) {
    const r = moveRect(win, dx, dy, vp);
    assert.ok(r.left >= 8 && r.top >= 8 && r.left + r.width <= vp.width - 8 && r.top + r.height <= vp.height - 8, JSON.stringify(r));
    assert.equal(r.width, win.width); assert.equal(r.height, win.height);
  }
  // An edge handle moves its own edge only (the caller zeroes the other axis).
  assert.deepEqual(resizeRect(win, 'e', 100, 0, vp), { ...win, width: 1290 });
  assert.deepEqual(resizeRect(win, 'w', -100, 0, vp), { ...win, left: 265, width: 1290 });
  assert.deepEqual(resizeRect(win, 's', 0, 60, vp), { ...win, height: 838 });
  assert.deepEqual(resizeRect(win, 'n', 0, -60, vp), { ...win, top: 91, height: 838 });
  // Limits: never smaller than the minimum, never past the window.
  assert.deepEqual(resizeRect(win, 'e', -5000, 0, vp, { width: 420, height: 200 }), { ...win, width: 420 });
  assert.deepEqual(resizeRect(win, 'e', 5000, 0, vp), { ...win, width: 1920 - 8 - 365 });
  assert.deepEqual(resizeRect(win, 'n', 0, -5000, vp), { ...win, top: 8, height: 921 });
  // A window saved on a big screen fits a small one.
  assert.deepEqual(fitRect({ left: 2000, top: 1200, width: 1600, height: 1000 }, { width: 1280, height: 720 }), { left: 8, top: 8, width: 1264, height: 704 });
});
