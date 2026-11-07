// Sprite readiness is monotonic until an atlas entry is evicted. Compile each
// view's visible requirements once per camera/settings/catalog combination,
// then make an already-ready view a constant-time check.
export class ViewGraphics {
  constructor(collect, loaded, request) {
    this.collect = collect;
    this.loaded = loaded;
    this.request = request;
    this.views = new WeakMap();
    this.builds = 0;
    this.hits = 0;
  }

  // `collect(view)` returns the requirements, or { core, extra }: only the core
  // (what is on screen) holds playback; the extra (a margin around it) is
  // requested once the core is in, as prefetch.
  ready(view, context, catalog, revision) {
    let entry = this.views.get(view);
    if (!entry || entry.context !== context || entry.catalog !== catalog) {
      const built = this.collect(view);
      entry = { context, catalog, requests: Array.isArray(built) ? built : built.core, extra: (!Array.isArray(built) && built.extra) || [], readyRevision: -1 };
      this.views.set(view, entry);
      this.builds++;
    }
    if (entry.readyRevision === revision) { this.hits++; return true; }
    let ready = true;
    for (const request of entry.requests) {
      if (this.loaded(request)) continue;
      ready = false;
      this.request(request);
    }
    if (ready) {
      for (const request of entry.extra) if (!this.loaded(request)) this.request(request);
      entry.readyRevision = revision;
    }
    return ready;
  }
}

// Keep the last complete pose while another animation loads. A replay clock
// can advance many seconds during one asset request, so age is not a readiness
// signal. Identity checks keep rewinds, conversions and new games separate.
export class SpriteHistory {
  constructor() { this.frames = new Map(); this.prunedAt = -Infinity; }
  // Called for every entity drawn, every frame: compare the identity fields as
  // numbers and update the entry in place (no key string or object per frame).
  remember(row, generation, t, drawn) {
    const last = this.frames.get(row[0]);
    if (last) {
      last.generation = generation; last.owner = row[1]; last.master = row[2]; last.flag = row[6] & 256;
      last.at = t; last.drawn = drawn;
    } else {
      this.frames.set(row[0], { generation, owner: row[1], master: row[2], flag: row[6] & 256, at: t, drawn });
    }
  }
  get(row, generation, t) {
    const last = this.frames.get(row[0]);
    if (!last || last.generation !== generation || last.owner !== row[1] || last.master !== row[2]
      || last.flag !== (row[6] & 256) || t < last.at) return null;
    last.at = t;
    return last.drawn;
  }
  // Runs every frame; a large battle keeps thousands of entries alive, so scan at
  // most once per second of game time.
  prune(t) {
    if (this.frames.size < 4000 || Math.abs(t - this.prunedAt) < 1000) return;
    this.prunedAt = t;
    for (const [id, entry] of this.frames) if (Math.abs(t - entry.at) > 10000) this.frames.delete(id);
  }
}
