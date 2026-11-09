import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ViewCache, RowInterpolator, shuttleSpeed, headingOf, mergeSeries, seriesEnd, sortByKey, eventIndexAfter } from '../src/vantage/web/playback.js';

test('view requests on opposite sides of a keyframe in one second stay distinct', async () => {
  const cache = new ViewCache(async (t) => ({ time: t < 1100 ? 100 : 1100 }));
  assert.equal((await cache.fetch(1050)).time, 100);
  assert.equal((await cache.fetch(1150)).time, 1100);
  assert.equal(cache.peek(1150).time, 1100);
});

test('look-ahead deduplicates requests and exposes resolved views synchronously', async () => {
  let finish, requests = 0;
  const cache = new ViewCache(() => { requests++; return new Promise((r) => { finish = r; }); });
  const first = cache.fetch(1000);
  assert.equal(cache.fetch(1000), first);
  assert.equal(cache.peek(1000), null);
  const view = { time: 995 };
  finish(view);
  await first;
  assert.equal(cache.peek(1000), view);
  assert.equal(requests, 1);
});

test('failed fetches retry and an old session cannot remove new cache entries', async () => {
  let finish;
  const cache = new ViewCache(() => new Promise((r) => { finish = r; }));
  const old = cache.fetch(1000), finishOld = finish;
  cache.clear();
  const current = cache.fetch(1000);
  finishOld(null);
  await old;
  finish({ time: 1000 });
  await current;
  assert.equal(cache.peek(1000).time, 1000);

  let requests = 0;
  const retry = new ViewCache(async () => { if (++requests === 1) throw Error('offline'); return { time: 2000 }; });
  assert.equal(await retry.fetch(2000), null);
  assert.equal((await retry.fetch(2000)).time, 2000);
  assert.equal(requests, 2);
});

test('view cache bounds retained requests', async () => {
  const cache = new ViewCache(async (t) => ({ time: t }), 2);
  await cache.fetch(1000); await cache.fetch(2000); await cache.fetch(3000);
  assert.equal(cache.peek(1000), null);
  assert.equal(cache.peek(2000).time, 2000);
});

test('reverse playback and cached seeks pick the nearest snapshot at or below the clock', async () => {
  const cache = new ViewCache(async (t) => ({ time: t - 10 }));
  await cache.fetch(1000); await cache.fetch(2000); await cache.fetch(3000);
  assert.equal(cache.at(1995).time, 1990);
  assert.equal(cache.at(1990).time, 1990);
  assert.equal(cache.at(1989).time, 990);
  assert.equal(cache.at(900), null);
  cache.clear();
  assert.equal(cache.at(3000), null);
});

const row = (id, x, y) => [id, 1, 83, x, y, 1, 4, 2, [[10, 3, 0, 0]], 2];
test('interpolation follows game time in both directions without changing snapshots', () => {
  const source = row(1, 10, 10), target = row(1, 14, 12);
  const v = { time: 100, entities: [source] }, n = { time: 2100, entities: [target] };
  const saved = structuredClone([v, n]);
  const lerp = new RowInterpolator();
  const out = lerp.at(v, n, 1100);
  assert.deepEqual(out[0].slice(3, 5), [12, 11]);
  assert.deepEqual(out[0].slice(5), source.slice(5));
  assert.equal(lerp.at(v, n, 1600), out); // buffers are reused between frames
  assert.deepEqual(out[0].slice(3, 5), [13, 11.5]);
  assert.deepEqual(lerp.at(v, n, 600)[0].slice(3, 5), [11, 10.5]);
  assert.deepEqual(lerp.at(v, n, 3000)[0].slice(3, 5), [14, 12]);
  assert.deepEqual([v, n], saved);
});

test('stationary, missing and teleporting units stay fixed; seeks reset interpolation', () => {
  const still = row(1, 10, 10), gone = row(2, 11, 11), teleport = row(3, 12, 12);
  const v = { time: 0, entities: [still, gone, teleport] };
  const n = { time: 1000, entities: [row(1, 10, 10), row(3, 100, 100)] };
  const lerp = new RowInterpolator();
  assert.deepEqual(lerp.at(v, n, 500), v.entities);
  assert.equal(lerp.at(v, n, 500)[0], still);
  assert.equal(lerp.at(v, null, 500), v.entities);
  assert.deepEqual(lerp.at(null, n, 500), []);
  const seek = { time: 5000, entities: [row(1, 50, 50)] };
  const after = { time: 6000, entities: [row(1, 52, 50)] };
  assert.deepEqual(lerp.at(seek, after, 5500)[0].slice(3, 5), [51, 50]);
});

test('rewind and fast forward step 2x, 4x, 8x in their direction, then start over', () => {
  assert.equal(shuttleSpeed(1, true, 1), 2); // playing normally: fast forward at 2x
  assert.equal(shuttleSpeed(2, true, 1), 4);
  assert.equal(shuttleSpeed(4, true, 1), 8);
  assert.equal(shuttleSpeed(8, true, 1), 2); // past 8x: back to 2x
  assert.equal(shuttleSpeed(4, true, -1), -2); // going forward, rewind starts at 2x backwards
  assert.equal(shuttleSpeed(-2, true, -1), -4);
  assert.equal(shuttleSpeed(-8, true, -1), -2);
  assert.equal(shuttleSpeed(-4, false, -1), -2); // paused: starts again at 2x
});

test('a moving unit faces where it goes and keeps its moving pose', () => {
  const facets = () => 16;
  const walkStart = [5, 1, 83, 10, 10, 1, 4, 3, [[10, 0, 0, 0]], 0]; // idle pose (activity 0)
  const walkEnd = [5, 1, 83, 12, 10, 1, 4, 9, [[11, 4, 0, 0]], 1]; // walking (activity 1)
  const v = { time: 0, entities: [walkStart] }, n = { time: 1000, entities: [walkEnd] };
  const lerp = new RowInterpolator(facets);
  const early = lerp.at(v, n, 100)[0];
  assert.equal(early[7], headingOf(2, 0, 16)); // facing its travel, not the stale 3
  assert.deepEqual(early[8], [[11, 4, 0, 0]]); // the walking pose for the whole slide
  assert.equal(early[11], 1000); // whose animation clock starts at the next snapshot
  assert.deepEqual(walkStart, [5, 1, 83, 10, 10, 1, 4, 3, [[10, 0, 0, 0]], 0]); // snapshots untouched
});

test('turning in place switches facing and pose halfway; buildings never change', () => {
  const v = { time: 0, entities: [[6, 1, 83, 10, 10, 1, 2, 3, [[20, 0, 0, 0]], 8], [7, 1, 70, 5, 5, 1, 1, 0, [[30, 0, 0, 0]], 10]] };
  const n = { time: 1000, entities: [[6, 1, 83, 10, 10, 1, 2, 6, [[21, 0, 0, 0]], 8], [7, 1, 70, 5, 5, 1, 1, 2, [[31, 0, 0, 0]], 10]] };
  const lerp = new RowInterpolator(() => 16);
  let rows = lerp.at(v, n, 400);
  assert.equal(rows[0][7], 3);
  assert.equal(rows[1], v.entities[1]); // a building row is the snapshot's own
  rows = lerp.at(v, n, 600);
  assert.equal(rows[0][7], 6);
  assert.deepEqual(rows[0][8], [[21, 0, 0, 0]]);
});

test('headings: the map-angle convention (16 facings)', () => {
  assert.equal(headingOf(1, 1, 16), 0); // down the screen-right diagonal of the map
  assert.equal(headingOf(1, -1, 16), 12);
  assert.equal(headingOf(-1, -1, 16), 8);
  assert.equal(headingOf(-1, 1, 16), 4);
  assert.equal(headingOf(1, 0, 16), 14); // 45° steps are two facings apart
});

test('a unit follows its track between snapshots and faces each stretch', () => {
  // Around a corner: east along x to (12, 10) by t=500, then along y to (12, 12).
  const v = {
    time: 0, entities: [[8, 1, 83, 10, 10, 1, 2, 0, [[11, 0, 0, 0]], 1]],
    unit_track: [[500, [[8, 12, 10, 14]]]],
  };
  const n = { time: 1000, entities: [[8, 1, 83, 12, 12, 1, 2, 2, [[11, 4, 0, 0]], 1]] };
  const lerp = new RowInterpolator(() => 16);
  let r = lerp.at(v, n, 250)[0];
  assert.deepEqual(r.slice(3, 5), [11, 10]); // half way along the first stretch, not cutting the corner
  assert.equal(r[7], headingOf(2, 0, 16));
  r = lerp.at(v, n, 750)[0];
  assert.deepEqual(r.slice(3, 5), [12, 11]);
  assert.equal(r[7], headingOf(0, 2, 16)); // turned with the path
});

test('a stats response without a validity interval survives the clock moving on', async () => {
  const { entityStatsValid } = await import('../src/vantage/web/state.js');
  const legacy = { owner: 2, master: 214, stats: { hp: 25 } };
  const row = [4981, 2, 214];
  assert.equal(entityStatsValid(legacy, 4981, row, 600250, undefined, 600000), true);
  assert.equal(entityStatsValid(legacy, 4981, row, 608000, undefined, 600000), true);
  // A seek far from the query time, or a converted unit, still needs a refresh.
  assert.equal(entityStatsValid(legacy, 4981, row, 900000, undefined, 600000), false);
  assert.equal(entityStatsValid(legacy, 4981, [4981, 1, 214], 600250, undefined, 600000), false);
});

test('a bounded stats response is only valid inside its interval', async () => {
  const { entityStatsValid } = await import('../src/vantage/web/state.js');
  const bounded = { entity_stats_validity_version: 1, generation: 1, entity_id: 7, owner: 1, master: 4,
    valid_from_ms: 1000, valid_until_ms: 2000 };
  assert.equal(entityStatsValid(bounded, 7, [7, 1, 4], 1500, 1, 1000), true);
  assert.equal(entityStatsValid(bounded, 7, [7, 1, 4], 2000, 1, 1000), false);
});

test('playing forward past a bounded response keeps showing it until the refetch lands', async () => {
  const { entityStatsUsable } = await import('../src/vantage/web/state.js');
  const bounded = { entity_stats_validity_version: 1, generation: 1, entity_id: 7, owner: 1, master: 4,
    valid_from_ms: 1000, valid_until_ms: 2000 };
  const row = [7, 1, 4];
  assert.equal(entityStatsUsable(bounded, 7, row, 1500, 1, 1000), true); // inside
  assert.equal(entityStatsUsable(bounded, 7, row, 3500, 1, 1000), true); // a little past the end: live playback
  assert.equal(entityStatsUsable(bounded, 7, row, 20000, 1, 1000), false); // a jump far ahead
  assert.equal(entityStatsUsable(bounded, 7, row, 900, 1, 1000), false); // rewound: never stale
  assert.equal(entityStatsUsable(bounded, 7, [7, 2, 4], 3500, 1, 1000), false); // converted: new owner
  assert.equal(entityStatsUsable(bounded, 7, row, 3500, 2, 1000), false); // another game
  assert.equal(entityStatsUsable(bounded, 8, row, 3500, 1, 1000), false); // another unit
  assert.equal(entityStatsUsable(null, 7, row, 1500, 1, 1000), false);
});

test('an incremental series fetch replaces rows from its start and keeps the rest', () => {
  const old = { 1: [{ t: 0, a: 1 }, { t: 5000, a: 2 }, { t: 10000, a: 3 }], 2: [{ t: 0, b: 1 }] };
  const merged = mergeSeries(old, { 1: [{ t: 10000, a: 4 }, { t: 15000, a: 5 }], 3: [{ t: 15000, c: 1 }] }, 10000);
  assert.deepEqual(merged[1].map((r) => r.a), [1, 2, 4, 5]);
  assert.deepEqual(merged[2], old[2]);
  assert.deepEqual(merged[3], [{ t: 15000, c: 1 }]);
  assert.notEqual(merged, old); // a new object: screens compare S.series by identity
  assert.equal(old[1].length, 3); // the old series is not modified
  // A server that ignores ?from= answers with everything: still no duplicates.
  const full = mergeSeries(old, { 1: [{ t: 0, a: 1 }, { t: 5000, a: 2 }, { t: 10000, a: 9 }] }, 10000);
  assert.deepEqual(full[1].map((r) => r.a), [1, 2, 9]);
  assert.equal(seriesEnd(old), 10000);
  assert.equal(seriesEnd(null), -1);
});

test('sorting by a precomputed key matches a stable comparator sort', () => {
  const rows = Array.from({ length: 500 }, (_, i) => [i, (i * 7919) % 13, (i * 104729) % 17]);
  const key = (r) => r[2] - r[1];
  const expected = rows.slice().sort((a, b) => key(a) - key(b));
  let calls = 0;
  const got = sortByKey(rows, (r) => { calls++; return key(r); });
  assert.deepEqual(got, expected); // ties keep their input order, as Array#sort does
  assert.equal(calls, rows.length); // one key per row, not two per comparison
  assert.deepEqual(sortByKey([], key), []);
});

test('the first event after a time is found by bisection', () => {
  const ev = [{ t: 0 }, { t: 100 }, { t: 100 }, { t: 250 }, { t: 900 }];
  assert.equal(eventIndexAfter(ev, -1), 0);
  assert.equal(eventIndexAfter(ev, 0), 1);
  assert.equal(eventIndexAfter(ev, 100), 3);
  assert.equal(eventIndexAfter(ev, 899), 4);
  assert.equal(eventIndexAfter(ev, 900), 5);
  assert.equal(eventIndexAfter([], 5), 0);
});

test('a view the server marks as not final is fetched again after a while', async () => {
  let loads = 0;
  const cache = new ViewCache(async (t) => { loads++; return { time: t, final: loads > 1 }; }, 40, 20);
  assert.equal((await cache.fetch(1000)).final, false);
  await cache.fetch(1000);
  assert.equal(loads, 1); // still served from the cache meanwhile
  await new Promise((r) => setTimeout(r, 40));
  assert.equal((await cache.fetch(1000)).final, true); // its track has filled in since
  assert.equal(loads, 2);
  await new Promise((r) => setTimeout(r, 40));
  await cache.fetch(1000);
  assert.equal(loads, 2); // final views stay
});

test('a recording header drives its fidelity notice and an ordinary recording has none', async () => {
  const { fidelityNotice, INCOMPLETE_TITLE } = await import('../src/vantage/web/recording-fidelity.js');
  const session = (header, mode = 'recording') => ({ mode, source: { header } });
  assert.match(fidelityNotice(session({ fidelity: { simulation: 'approximate' } })), /Approximate replay/);
  assert.match(fidelityNotice(session({ title: INCOMPLETE_TITLE })), /Incomplete replay preview/);
  assert.match(fidelityNotice(session({ fidelity: { simulation: 'approximate' } }, 'native_replay')), /Approximate/);
  assert.equal(fidelityNotice(session({ title: 'ordinary', fidelity: {} })), null);
  assert.equal(fidelityNotice(session({ fidelity: { simulation: 'approximate' } }, 'live')), null);
  assert.equal(fidelityNotice({ mode: 'recording' }), null);
  assert.equal(fidelityNotice(null), null);
});

