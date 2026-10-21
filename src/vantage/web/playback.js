// Playback helpers kept independent of the DOM so timing and interpolation can
// be checked with synthetic snapshots as well as real recordings.

export class ViewCache {
  constructor(load, limit = 40) {
    this.load = load;
    this.limit = limit;
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
      entry.value = value;
      // Failed requests may be retried; an old request must not remove a new
      // session's entry after clear().
      if (!value && this.entries.get(key) === entry) this.entries.delete(key);
      return value;
    });
    this.entries.set(key, entry);
    if (this.entries.size > this.limit) this.entries.delete(this.entries.keys().next().value);
    return entry.promise;
  }
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
 *   moving (column 9, the activity); otherwise facing and pose switch to the
 *   later snapshot's halfway through.
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
        let n = 0, pose = null;
        if (unit && moves) {
          n = this.facetsOf ? this.facetsOf(r) : 0;
          if (!samePose(r[8], q[8])) pose = r[9] === ACT_MOVING ? 'start' : q[9] === ACT_MOVING ? 'end' : null;
          else pose = 'start';
        }
        this.moving.push([out, r, q, path, n, pose, unit]);
        return out;
      });
    }
    const f = Math.min(1, (time - view.time) / (next.time - view.time));
    for (const [out, r, q, path, n, pose, unit] of this.moving) {
      // The stretch of the path the time falls in.
      let k = 0;
      while (k < path.length - 2 && time >= path[k + 1][0]) k++;
      const a = path[k], b = path[k + 1];
      const g = Math.max(0, Math.min(1, (time - a[0]) / Math.max(1, b[0] - a[0])));
      const sx = b[1] - a[1], sy = b[2] - a[2];
      out[3] = a[1] + sx * g; out[4] = a[2] + sy * g;
      if (!unit) continue;
      const late = pose ? pose === 'end' : f >= 0.5;
      out[8] = late ? q[8] : r[8];
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
