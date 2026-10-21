import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ViewCache, RowInterpolator, shuttleSpeed, headingOf } from '../src/vantage/web/playback.js';

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
