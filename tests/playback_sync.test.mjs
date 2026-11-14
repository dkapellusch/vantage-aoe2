import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import {
  RowInterpolator, followingView, playableUntil, pacePlayback, chainedView, viewGridTime,
} from '../src/vantage/web/playback.js';

// Keyframes about a second apart, at most one in each second (timeline.py), off
// the whole seconds, sometimes on one (k = 150: 150000) and so less than a
// second after the one before.
const KEYS = Array.from({ length: 400 }, (_, k) => ({ time: 1000 * k + ((k * 37) % 150), entities: [] }));
const floorKey = (t) => { let v = null; for (const k of KEYS) if (k.time <= t) v = k; return v; };
// A cache of answered grid requests (the view cache's peek).
const answered = (times) => { const m = new Map(times.map((t) => [t, floorKey(t)])); return (t) => m.get(t) || null; };

test('the grid asks for the last millisecond of each second', () => {
  assert.equal(viewGridTime(5185, 1), 5999);
  assert.equal(viewGridTime(5185, 2), 6999);
  assert.equal(viewGridTime(5000, 0), 4999);
  // Each request answers with that second's keyframe, also one on a whole second.
  assert.equal(floorKey(viewGridTime(149113, 2)), KEYS[150]);
  assert.equal(floorKey(viewGridTime(148076, 2)), KEYS[149]);
});

test('the view after a keyframe is the one right after it, never one past a request under way', () => {
  const v = KEYS[5]; // 5185
  assert.equal(followingView(v, answered([6999, 7999, 8999])).next, KEYS[6]);
  // 6999 still under way: 7999's keyframe is not the next one, whatever answered.
  assert.deepEqual(followingView(v, answered([7999, 8999])), {});
  // A second without a keyframe (the game paused): its request answers with v.
  const gap = [{ time: 5185 }, { time: 7109 }];
  const peek = (t) => [...gap].reverse().find((k) => k.time <= t) || null;
  assert.equal(followingView(gap[0], peek).next, gap[1]);
  assert.equal(followingView(gap[0], (t) => (t < 7000 ? peek(t) : null)).next, undefined);
});

test('the last keyframe of a recording has an end, not a missing next view', () => {
  const end = KEYS[10].time + 400; // the recording stops before another keyframe
  const last = KEYS[10];
  const peek = (t) => (t <= end ? floorKey(t) : null);
  assert.deepEqual(followingView(last, peek, { end }), { end: true });
  assert.equal(playableUntil(last, null, (x) => followingView(x, peek, { end })), Infinity);
});

test('the clock may run as far as the chain of keyframes in hand reaches', () => {
  const peek = answered([6999, 7999, 8999]);
  const follow = (x) => followingView(x, peek);
  // view 5, next 6, then 7 and 8 in hand; 9 (request 9999) is not.
  assert.equal(playableUntil(KEYS[5], KEYS[6], follow), KEYS[8].time);
  // No next view: the clock stays on the view.
  assert.equal(playableUntil(KEYS[5], null, follow), KEYS[5].time);
  assert.equal(playableUntil(null, null, follow), -Infinity);
});

test('a frame that crosses several keyframes lands on the one the clock is in', () => {
  const follow = (x) => followingView(x, answered([6999, 7999, 8999, 9999]));
  assert.equal(chainedView(KEYS[7].time + 50, KEYS[5], KEYS[6], follow), KEYS[7]);
  assert.equal(chainedView(KEYS[6].time - 1, KEYS[5], KEYS[6], follow), null);
  // Far past what is in hand: not a view for this moment.
  assert.equal(chainedView(KEYS[9].time + 1600, KEYS[5], KEYS[6], follow), null);
  assert.equal(chainedView(KEYS[9].time + 1400, KEYS[5], KEYS[6], follow), KEYS[9]);
});

test('playback slows as the keyframes ahead run short and never passes them', () => {
  const rate = 13.6; // 8x at the game's 1.7
  const step = 16.7 * rate;
  assert.equal(pacePlayback(0, step, rate, Infinity), step);
  assert.equal(pacePlayback(0, step, rate, 10000), step); // plenty ahead
  const slow = pacePlayback(0, step, rate, 1000); // a second ahead, ~4 s wanted
  assert.ok(slow > 0 && slow < step / 2, String(slow));
  assert.equal(pacePlayback(990, step, rate, 1000) <= 10, true);
  assert.equal(pacePlayback(1000, step, rate, 1000), 0);
  assert.equal(pacePlayback(1200, step, rate, 1000), 0);
  assert.equal(pacePlayback(0, -step, rate, 1000), -step); // backwards: not paced here
});

/**
 * 8x playback through a slow link, frame by frame, as app.js plays it: the clock
 * advances (paced or not), then the view is chosen (chainedView, or a request for
 * the clock's own moment when the chain does not reach it), and look-ahead
 * requests go out on the shared grid. Requests answer `latency` ms after they are
 * made, `lanes` at a time. Returns per frame whether the units were drawn from a
 * pair of keyframes around the clock (or exactly on a keyframe), and the order.
 */
function simulate({ paced, latency = 450, lanes = 2, seconds = 30, frameMs = 1000 / 60, rate = 13.6 }) {
  const cache = new Map(); // grid or exact time -> view, once answered
  const queue = []; const inflight = []; // [time, done at]
  const asked = new Set();
  const ask = (t) => { if (!asked.has(t)) { asked.add(t); queue.push(t); } };
  const peek = (t) => cache.get(t) || null;
  const follow = (x) => followingView(x, peek, { steps: 20 });
  const prime = (v) => { for (let k = 2; k <= 17; k++) ask(viewGridTime(v.time, k)); };
  let now = 0, t = 100000, view = floorKey(t), next = null, waiting = null;
  cache.set(t, view);
  t = view.time;
  prime(view);
  const frames = [];
  for (; now < seconds * 1000; now += frameMs) {
    // The network.
    while (inflight.length < lanes && queue.length) inflight.push([queue.shift(), now + latency]);
    for (let i = inflight.length - 1; i >= 0; i--) {
      if (inflight[i][1] <= now) { cache.set(inflight[i][0], floorKey(inflight[i][0])); inflight.splice(i, 1); }
    }
    if (!next) next = follow(view).next || null;
    // The clock.
    const prev = t, step = frameMs * rate;
    t += paced ? pacePlayback(t, step, rate, t >= view.time ? playableUntil(view, next, follow) : -Infinity) : step;
    // The view.
    if (!(next && t >= view.time && t < next.time) && !(t >= view.time && !next && t === view.time)) {
      const chained = chainedView(t, view, next, follow);
      if (chained) { view = chained; next = follow(view).next || null; prime(view); waiting = null; }
      else if (t >= view.time + (next ? next.time - view.time : 0) || t < view.time) {
        // Not in hand: ask for the clock's own moment (app.js fetchView(S.t)).
        if (waiting == null) { waiting = Math.round(t); ask(waiting); }
        else if (cache.has(waiting)) { view = cache.get(waiting); next = follow(view).next || null; prime(view); waiting = null; }
      }
    }
    const synced = (next && view.time <= t && t <= next.time) || t === view.time;
    const adjacent = !next || KEYS.indexOf(next) === KEYS.indexOf(view) + 1;
    frames.push({ synced, adjacent, back: t < prev, t });
  }
  return { frames, game: t - 100000 };
}

test('8x through a slow link: the old clock outruns the views, the paced one stays in step', () => {
  const old = simulate({ paced: false });
  const unsynced = old.frames.filter((f) => !f.synced).length;
  assert.ok(unsynced > old.frames.length / 2, `the unpaced clock drew ${unsynced} of ${old.frames.length} frames without a pair of keyframes`);

  const fixed = simulate({ paced: true });
  assert.equal(fixed.frames.filter((f) => !f.synced).length, 0);
  assert.equal(fixed.frames.filter((f) => !f.adjacent).length, 0);
  assert.equal(fixed.frames.filter((f) => f.back).length, 0);
  // It still plays: at the pace the views arrive (2 lanes, 0.45 s each: ~4 views a
  // second), not stopped.
  assert.ok(fixed.game > 30 * 3000, `played ${fixed.game} game ms in 30 s`);
});

test('on a fast link pacing changes nothing: 8x plays at 8x', () => {
  const fast = simulate({ paced: true, latency: 20, lanes: 6, seconds: 10 });
  assert.equal(fast.frames.filter((f) => !f.synced).length, 0);
  assert.ok(fast.game > 10 * 13600 * 0.97, `played ${fast.game} game ms in 10 s`);
});

test('a walker that stops before the next keyframe takes that keyframe\'s pose where it arrives', () => {
  const WALK = [[70, 0, 0, 0]], WORK = [[71, 0, 0, 0]];
  const a = [500, 1, 83, 10, 10, 1, 4, 0, WALK, 1];
  const b = [500, 1, 83, 12, 10, 1, 4, 0, WORK, 2];
  // The track: at 12,10 already half way through the second.
  const view = { time: 1000, entities: [a], unit_track: [[1500, [[500, 12, 10, 0]]]] };
  const next = { time: 2000, entities: [b] };
  const lerp = new RowInterpolator(() => 8);
  let r = lerp.at(view, next, 1250)[0];
  assert.deepEqual([r[3], r[8], r[9]], [11, WALK, 1]); // walking there
  r = lerp.at(view, next, 1600)[0];
  assert.deepEqual([r[3], r[8], r[9]], [12, WORK, 2]); // arrived: no walk on the spot
  assert.equal(r[11], 2000);
  r = lerp.at(view, next, 1400)[0];
  assert.deepEqual([r[8], r[9]], [WALK, 1]);
  assert.equal(r.length, a.length);
  // Still walking at the next keyframe: the walk is kept throughout.
  const c = [500, 1, 83, 12, 10, 1, 4, 0, [[72, 0, 0, 0]], 1];
  const r2 = new RowInterpolator(() => 8).at(view, { time: 2000, entities: [c] }, 1700)[0];
  assert.deepEqual([r2[8], r2[9]], [WALK, 1]);
});
