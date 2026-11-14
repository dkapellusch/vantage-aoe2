// Playback helpers kept independent of the DOM so timing and interpolation can
// be checked with synthetic snapshots as well as real recordings.

export class ViewCache {
  /** `provisionalMs`: how long a view marked `final: false` (the newest keyframe,
   * its movement track still filling) is reused before it is fetched again. */
  constructor(load, limit = 40, provisionalMs = 1000) {
    this.load = load;
    this.limit = limit;
    this.provisionalMs = provisionalMs;
    this.entries = new Map();
  }

  key(t) { return Math.max(0, Math.round(t)); }
  peek(t) { return this.entries.get(this.key(t))?.value || null; }
  at(t) {
    let nearest = null;
    for (const { value } of this.entries.values()) {
      if (value && value.time <= t && (!nearest || value.time > nearest.time)) nearest = value;
    }
    return nearest;
  }
  clear() { this.entries.clear(); }

  fetch(t) {
    const key = this.key(t);
    const cached = this.entries.get(key);
    if (cached) return cached.promise;
    const entry = { value: null, promise: null };
    entry.promise = this.load(key).catch(() => null).then((value) => {
      // Before the first keyframe the server returns {}. It is not a view;
      // caching it would pin a paused startup clock at t=0 forever.
      if (!Number.isFinite(value?.time)) value = null;
      entry.value = value;
      // Failed requests may be retried; an old request must not remove a new
      // session's entry after clear().
      if (!value && this.entries.get(key) === entry) this.entries.delete(key);
      if (value && value.final === false) {
        setTimeout(() => { if (this.entries.get(key) === entry) this.entries.delete(key); }, this.provisionalMs);
      }
      return value;
    });
    this.entries.set(key, entry);
    if (this.entries.size > this.limit) this.entries.delete(this.entries.keys().next().value);
    return entry.promise;
  }
}

// -- keyframes in order, and a clock that never runs past them ---------------------
// Views are asked for on a shared grid (app.js viewRequests): the request at t
// answers with the keyframe at or before t. The timeline keeps at most one
// keyframe in each second of game time (timeline.py: the first frame at or after
// the next whole second), so a request at the last millisecond of a second
// answers with that second's keyframe, or an earlier one if it has none: no
// keyframe falls between two grid requests unseen. Interpolation needs the view
// the clock is in and the very next keyframe; a later one with a request still
// under way before it would interpolate across a keyframe that is not in.

/** The grid request `k` seconds on from the second of `time` (k = 1: its own). */
export function viewGridTime(time, k) {
  return Math.floor(time / 1000) * 1000 + k * 1000 - 1;
}

/**
 * The keyframe right after `view`, from the answered grid requests (`peek(t)`: the
 * cached answer to the request at t, or null): { next } when found; { end: true }
 * when the recording has no later keyframe (the request at `end` answered with
 * `view` or one before it); {} while a request before the next keyframe is still
 * unanswered. `steps` bounds how many grid seconds are searched.
 */
export function followingView(view, peek, { start = 0, end = Infinity, steps = 6 } = {}) {
  if (!view) return {};
  for (let k = 2; k <= steps + 1; k++) {
    const at = Math.max(start, Math.min(end, viewGridTime(view.time, k)));
    const a = peek(at);
    if (!a) return {};
    if (a.time > view.time) return { next: a };
    if (at >= end) return { end: true };
  }
  return {};
}

/**
 * How far the clock may run on the keyframes in hand, in game ms: to the last of
 * the chain `next`, its following view, that one's... (`follow(v)` is
 * followingView of v), Infinity once the chain reaches the recording's end.
 * Without a next view the clock stays at the view (units drawn from one keyframe
 * only hold still: the clock must not run on while their walk animates).
 */
export function playableUntil(view, next, follow, links = 8) {
  if (!view) return -Infinity;
  if (!next || next.time <= view.time) return follow(view).end ? Infinity : view.time;
  let last = next;
  for (let i = 0; i < links; i++) {
    const f = follow(last);
    if (f.end) return Infinity;
    if (!f.next) break;
    last = f.next;
  }
  return last.time;
}

/**
 * The keyframe the clock `t` is in once it has passed `next`, following the chain
 * (a slow frame at 8x crosses more than one keyframe), or null when `t` has not
 * reached `next` or lies more than `maxLag` ms past the last keyframe in hand.
 */
export function chainedView(t, view, next, follow, maxLag = 1500) {
  if (!view || !next || next.time <= view.time || t < next.time) return null;
  let v = next;
  for (let f = follow(v).next; f && f.time <= t; f = follow(v).next) v = f;
  return t - v.time < maxLag ? v : null;
}

/** Wall ms of data ahead of the clock below which playback slows down (pacePlayback). */
export const PACE_LEAD_MS = 300;

/**
 * The game ms the clock advances this frame: `step` (rate × frame time) when the
 * keyframes in hand reach well ahead, less as they run short, never past
 * `horizon` (playableUntil). Slowing in proportion to the lead makes playback
 * settle at the pace the views arrive, smoothly, instead of running up to the
 * last keyframe and stopping there until the next one lands.
 */
export function pacePlayback(t, step, rate, horizon, leadMs = PACE_LEAD_MS) {
  if (!(step > 0)) return step;
  const lead = horizon - t;
  if (!(lead > 0)) return 0;
  if (lead === Infinity) return step;
  const want = Math.abs(rate) * leadMs;
  const scaled = want > 0 && lead < want ? step * (lead / want) : step;
  return Math.min(scaled, lead);
}

const ACT_MOVING = 1; // world.py ACT_MOVING (row column 9)
// Slower than this (tiles per second) a unit is nudged or shuffling, not walking:
// it keeps the game's own facing. Measured on game2.vrec at the game's own
// in-between headings: under 0.1 tiles/s the direction of travel was wrong 82 %
// of the time (the snapshot's facing 28 %), from 0.3 tiles/s up 3-26 % (the
// snapshot's 15-60 %).
const MIN_TURN_SPEED = 0.15;

// The same pictures (sprite ids and offsets; the frame index advances anyway).
function samePose(a, b) {
  if (!a || !b || a.length !== b.length) return a === b;
  for (let i = 0; i < a.length; i++) {
    const p = a[i], q = b[i];
    if (p[0] !== q[0] || p[2] !== q[2] || p[3] !== q[3]) return false;
  }
  return true;
}

/**
 * The game heading (0..n-1) of a unit moving by (dx, dy) tiles. Facings are evenly
 * spaced in map angle, offset by 45 degrees: fitted on game2.vrec, 96 % of 9,101
 * units moving straight between two snapshots carry exactly this heading (within
 * half a step), the rest are on curved paths.
 */
export function headingOf(dx, dy, n) {
  const g = Math.round(Math.atan2(dy - dx, dx + dy) / (2 * Math.PI / n));
  return ((g % n) + n) % n;
}

/**
 * Rows between two snapshots (a second apart). The game turns, curves and changes
 * animation within that second; drawn as a straight slide in the pose and facing
 * of its start, a unit walked sideways or backwards (moonwalked) or slid in its
 * idle pose. Now
 * - a unit follows the snapshot's unit track (`unit_track`, [[t, [[id, x, y,
 *   heading], ...]], ...]: where units were between the snapshots, when the
 *   stream had frames in between), else a straight line;
 * - while it moves it faces along the current stretch of its path (headingOf;
 *   the number of facings from `facetsOf(row)`, 0 when unknown);
 * - while it moves it keeps its moving pose, from whichever snapshot shows it
 *   moving (column 9, the activity), until it arrives: a unit that has stopped by
 *   the later snapshot takes that snapshot's pose where its path ends (it walked
 *   on the spot until the next keyframe); otherwise facing and pose switch to
 *   the later snapshot's halfway through.
 * A pose taken from the later snapshot carries that snapshot's time in column 11
 * (the animation clock's origin). Buildings and projectiles are left alone.
 */
export class RowInterpolator {
  constructor(facetsOf = null) {
    this.facetsOf = facetsOf;
    this.view = null;
    this.next = null;
    this.rows = [];
    this.moving = [];
  }

  at(view, next, time) {
    if (!view) return [];
    if (!next || next.time <= view.time || time <= view.time) return view.entities;
    if (this.view !== view || this.next !== next) {
      this.view = view; this.next = next;
      this.moving = [];
      const targets = new Map(next.entities.map((r) => [r[0], r]));
      const tracks = new Map();
      for (const [t, units] of view.unit_track || []) {
        if (t <= view.time || t >= next.time) continue;
        for (const [id, x, y, h] of units) {
          let w = tracks.get(id);
          if (!w) tracks.set(id, (w = []));
          w.push([t, x, y, h]);
        }
      }
      this.rows = view.entities.map((r) => {
        const q = targets.get(r[0]);
        if (!q) return r;
        const dx = q[3] - r[3], dy = q[4] - r[4];
        const unit = !(r[6] & 1) && r[0] >= 0;
        const track = unit ? tracks.get(r[0]) : null;
        const changes = unit && (q[7] !== r[7] || !samePose(r[8], q[8]));
        // Teleport/garrison: don't slide across the map.
        if (dx * dx + dy * dy > 36) return r;
        // Rows that neither move nor turn need neither a copy nor per-frame work.
        if (!dx && !dy && !changes && !track) return r;
        const out = r.slice();
        const path = [[view.time, r[3], r[4], r[7]], ...(track || []), [next.time, q[3], q[4], q[7]]];
        const moves = path.some((p) => p[1] !== r[3] || p[2] !== r[4]);
        let n = 0, pose = null, arrive = Infinity;
        if (unit && moves) {
          n = this.facetsOf ? this.facetsOf(r) : 0;
          if (!samePose(r[8], q[8])) pose = r[9] === ACT_MOVING ? 'start' : q[9] === ACT_MOVING ? 'end' : null;
          else pose = 'start';
          // Walking at the start and stopped at the end: where the path stops moving.
          if (pose === 'start' && q[9] !== ACT_MOVING) {
            let j = path.length - 1;
            while (j > 0 && path[j - 1][1] === path[j][1] && path[j - 1][2] === path[j][2]) j--;
            arrive = path[j][0];
          }
        }
        this.moving.push([out, r, q, path, n, pose, unit, arrive]);
        return out;
      });
    }
    const f = Math.min(1, (time - view.time) / (next.time - view.time));
    for (const [out, r, q, path, n, pose, unit, arrive] of this.moving) {
      // The stretch of the path the time falls in.
      let k = 0;
      while (k < path.length - 2 && time >= path[k + 1][0]) k++;
      const a = path[k], b = path[k + 1];
      const g = Math.max(0, Math.min(1, (time - a[0]) / Math.max(1, b[0] - a[0])));
      const sx = b[1] - a[1], sy = b[2] - a[2];
      out[3] = a[1] + sx * g; out[4] = a[2] + sy * g;
      if (!unit) continue;
      // Arrived (and stopped by the later snapshot): its pose and activity, not a walk on the spot.
      const arrived = time >= arrive;
      const late = pose ? pose === 'end' || arrived : f >= 0.5;
      out[8] = late ? q[8] : r[8];
      out[9] = arrived ? q[9] : r[9];
      if (late) out[11] = next.time;
      else if (out.length > r.length) out.length = r.length;
      // Facing: along the stretch while walking it, else the game's own at its start.
      const span = Math.max(1, b[0] - a[0]) / 1000;
      if (n >= 4 && sx * sx + sy * sy > (MIN_TURN_SPEED * span) ** 2) out[7] = headingOf(sx, sy, n);
      else out[7] = path.length > 2 ? a[3] : late ? q[7] : r[7];
    }
    return this.rows;
  }
}

/**
 * Rewind / fast forward, as a video player's buttons: the first press plays at 2x
 * in that direction (`dir` -1 or 1), each further press doubles it up to 8x, then
 * it starts again at 2x. `speed` and `playing` are the current state.
 */
export function shuttleSpeed(speed, playing, dir) {
  const steps = [2, 4, 8];
  const cur = playing && Math.sign(speed) === dir ? Math.abs(speed) : 0;
  return dir * (steps.find((v) => v > cur) || steps[0]);
}

/**
 * Time series fetched incrementally (/api/series?from=): the rows from `from` on
 * replace the ones held, per player. Returns a new object (screens compare
 * S.series by identity to know it changed); the old one is left as it was.
 */
export function mergeSeries(old, add, from) {
  const out = { ...(old || {}) };
  for (const [pid, rows] of Object.entries(add || {})) {
    const kept = (out[pid] || []).filter((r) => r.t < from);
    out[pid] = kept.concat(rows.filter((r) => r.t >= from));
  }
  return out;
}

/** The time of the newest sample in a series (-1 when there is none). */
export function seriesEnd(series) {
  let end = -1;
  for (const rows of Object.values(series || {})) if (rows.length) end = Math.max(end, rows[rows.length - 1].t);
  return end;
}

// Scratch buffers for sortByKey, grown as needed and reused every frame.
let sortKeys = new Float64Array(1024), sortIdx = new Uint32Array(1024);
/**
 * `rows` ordered by `key(row)` ascending, ties in input order (as a stable
 * Array#sort). Each key is computed once: the world's painter's-order sort ran
 * its depth function twice per comparison, ~50k times a frame in a large game.
 */
export function sortByKey(rows, key) {
  const n = rows.length;
  if (sortKeys.length < n) { sortKeys = new Float64Array(n * 2); sortIdx = new Uint32Array(n * 2); }
  const keys = sortKeys, idx = sortIdx.subarray(0, n);
  for (let i = 0; i < n; i++) { keys[i] = key(rows[i]); idx[i] = i; }
  idx.sort((a, b) => keys[a] - keys[b] || a - b);
  const out = new Array(n);
  for (let i = 0; i < n; i++) out[i] = rows[idx[i]];
  return out;
}

/** Index of the first event with t > `time` in a list sorted by time. */
export function eventIndexAfter(events, time) {
  let lo = 0, hi = events.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (events[m].t <= time) lo = m + 1; else hi = m; }
  return lo;
}

/**
 * Wall ms a replay read ahead by the game should still wait before the viewer
 * plays on, so it never catches up with the game (0 = play).
 *
 * `total` is the replay's length from its header, `end` how far the game has got,
 * `t` the viewer's position, `watch` the viewer's game ms per wall ms, `rate` the
 * game's measured production in the same unit. `producing` is false once the game
 * has stopped sending frames (paused, ended, stalled): its rate then decays to 0
 * and the wait would grow without bound for data that will never arrive, so the
 * viewer plays what it has instead.
 */
export function replayBufferWait({ total, end, t, watch, rate, samples, producing }) {
  if (!total || !producing) return 0;
  if (rate == null || samples < 4) return 0; // measure ~12 s first
  // Keeping up (within 5 %): no buffering; the live-edge hold covers small gaps.
  if (watch <= 0 || rate >= watch * 0.95 || end >= total - 1000) return 0;
  // At the current pace the game reaches the end after (total - end) / rate and
  // playback after (total - t) / watch: wait the difference, once.
  return Math.max(0, (total - end) / Math.max(rate, 1e-3) - (total - t) / watch);
}

/**
 * The match is over, as far as the game says. A replay that played to its end
 * sets no `gameEnded` in the world: the game's own state (`GameState.DONE` = 3)
 * and the session's status are what tell.
 */
export function matchEnded(src) {
  return !!src && (src.status === 'ended' || Number(src.game_state) === 3);
}
