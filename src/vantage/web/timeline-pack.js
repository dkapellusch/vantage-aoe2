// The browser's side of a view pack (viewpack.py): a whole match's keyframe
// views in gzip-compressed chunks, each the first view in full and the rest as
// structural deltas. Rebuilding a view from a chunk held locally takes a few
// milliseconds in a worker, where /api/view is a network round trip.
//
// Nothing here touches the DOM or the network: view-worker.js fetches and keeps
// the chunks, tests feed them from memory.

export const PACK_VERSION = 1;

/** `old` with `delta` applied (viewpack.py's `apply`); `old` is left as it was
 * and what did not change is shared with it. */
export function applyDelta(old, delta) {
  switch (delta[0]) {
    case 0: return delta[1];
    case 1: {
      const patch = delta[1], removed = delta[2];
      const gone = removed.length ? new Set(removed) : null;
      const out = {};
      for (const k in old) {
        if (gone && gone.has(k)) continue;
        const d = patch[k];
        out[k] = d === undefined ? old[k] : applyDelta(old[k], d);
      }
      for (const k in patch) if (!(k in old)) out[k] = patch[k][1];
      return out;
    }
    case 2: {
      const ops = delta[1], rows = [];
      for (let p = 0; p < ops.length;) {
        const op = ops[p];
        if (op === 0) {
          const from = ops[p + 1], to = from + ops[p + 2];
          for (let i = from; i < to; i++) rows.push(old[i]);
          p += 3;
        } else if (op === 3) {
          rows.push(ops[p + 1]);
          p += 2;
        } else {
          const row = old[ops[p + 1]].slice();
          if (op === 2) {
            const n = ops[p + 2];
            while (row.length < n) row.push(null);
            row.length = n;
            p += 1;
          }
          const patch = ops[p + 2];
          for (let c = 0; c < patch.length; c += 2) row[patch[c]] = patch[c + 1];
          rows.push(row);
          p += 3;
        }
      }
      return rows;
    }
    case 3: {
      const out = old.slice(), patch = delta[1];
      for (let c = 0; c < patch.length; c += 2) out[patch[c]] = applyDelta(old[patch[c]], patch[c + 1]);
      return out;
    }
    default: throw new Error(`unknown delta kind ${delta[0]}`);
  }
}

/** gzip bytes -> text, with the platform's DecompressionStream. */
export async function gunzipText(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}

/** A parsed chunk: rebuilds its views on demand and keeps the ones it has built
 * (they share everything that did not change, so 30 of them cost little). */
export class PackChunk {
  constructor(doc) {
    if (!doc || doc.v !== PACK_VERSION) throw new Error(`unsupported pack version ${doc && doc.v}`);
    this.times = doc.times;
    this.deltas = doc.deltas;
    this.views = [doc.base];
  }

  get length() { return this.times.length; }

  /** The view of keyframe `k` of this chunk (0-based). */
  view(k) {
    const views = this.views;
    for (let i = views.length; i <= k; i++) views.push(applyDelta(views[i - 1], this.deltas[i - 1]));
    return views[k];
  }
}

/** Index of the keyframe a request for time `t` resolves to, as the server's
 * Timeline._keyframe_index: the one at or before `t`, the first for earlier. */
export function keyframeIndex(times, t) {
  let lo = 0, hi = times.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (times[m] <= t) lo = m + 1; else hi = m; }
  return Math.max(0, lo - 1);
}

const b64 = (text) => {
  const s = atob(text), out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
};

/** The snapshot in force at `t` among a chunk's tile rows ([time, mode, base64,
 * kinds?], viewpack.py), as { t, bytes, kinds }, or null when none is. Rows are
 * decoded (and un-XORed against the one before) once, up to the one asked for. */
export function tilesAt(rows, t) {
  let at = -1;
  for (let i = 0; i < rows.length && rows[i][0] <= t; i++) at = i;
  if (at < 0) return null;
  for (let i = 0; i <= at; i++) {
    const row = rows[i];
    if (row.bytes) continue;
    const raw = b64(row[2]);
    if (row[1] === 1) { const prev = rows[i - 1].bytes; for (let j = 0; j < raw.length; j++) raw[j] ^= prev[j]; }
    row.bytes = raw;
  }
  const row = rows[at];
  return { t: row[0], bytes: row.bytes, kinds: row[3] || [] };
}

const MANIFEST = '/__vantage_pack_manifest';
/** Packs kept in the browser (Cache Storage): the ones opened longest ago go first. */
export const PACKS_KEPT = 12;
export const PACK_CACHE = 'vantage-pack-v1';

/**
 * A match's pack in this browser: downloads its chunks in the background (one at
 * a time, low priority, from the playhead on), keeps them in Cache Storage under
 * the pack's key so the next visit needs no download, and rebuilds views and
 * tile snapshots from the chunks it holds.
 *
 * `fetchImpl(url, opts)` and `cacheStorage` (the `caches` global, or null) are
 * injected; `notify(status)` hears about progress.
 */
export class PackStore {
  constructor({ fetchImpl, cacheStorage = null, notify = () => {}, parsedLimit = 3, memoryLimit = 128 * 1048576 }) {
    this.fetchImpl = fetchImpl;
    this.cacheStorage = cacheStorage;
    this.notify = notify;
    this.parsedLimit = parsedLimit;
    this.memoryLimit = memoryLimit;
    this.index = null;      // { key, times, chunk_views }
    this.base = '';         // URL prefix of /api/pack
    this.cache = null;      // Cache, when storage is available
    this.have = new Set();  // chunk numbers held (in the cache or in memory)
    this.memory = new Map(); // chunk number -> bytes, without Cache Storage
    this.memoryBytes = 0;
    this.parsed = new Map(); // chunk number -> Promise<PackChunk>, most recent last
    this.focus = 0;
    this.bytes = 0;         // downloaded this session
    this.failed = 0;
    this.state = 'off';     // off | loading | ready (index held) | complete | stopped
    this.pump = null;
  }

  get chunks() { return this.index ? Math.ceil(this.index.times.length / this.index.chunk_views) : 0; }
  status() { return { state: this.state, chunks: this.chunks, have: this.have.size, bytes: this.bytes, key: this.index ? this.index.key : null }; }
  chunkUrl(i) { return `${this.base}/chunk?i=${i}&k=${this.index.key}`; }
  chunkOf(t) { return Math.floor(keyframeIndex(this.index.times, t) / this.index.chunk_views); }
  /** Can a request for time `t` be answered without the network? */
  holds(t) { return !!this.index && this.have.has(this.chunkOf(t)); }

  /** Start with the pack at `base` (…/api/pack). A match without one (still
   * growing, or a server that has none) leaves the store off. */
  async start(base, focus = 0) {
    if (this.state !== 'off') return;
    this.state = 'loading';
    this.base = base;
    try {
      const r = await this.fetchImpl(base, { priority: 'low' });
      const index = r.ok ? await r.json() : null;
      if (!index || index.v !== PACK_VERSION || !index.key || !Array.isArray(index.times) || !index.times.length) { this.state = 'off'; return; }
      this.index = index;
    } catch { this.state = 'off'; return; }
    try {
      if (this.cacheStorage) {
        this.cache = await this.cacheStorage.open(PACK_CACHE);
        const mark = `k=${this.index.key}`;
        for (const req of await this.cache.keys()) {
          const url = new URL(req.url);
          if (url.pathname.endsWith('/chunk') && url.search.includes(mark)) this.have.add(Number(url.searchParams.get('i')));
        }
        await this.touchManifest();
      }
    } catch { this.cache = null; this.have.clear(); }
    this.state = 'ready';
    this.setFocus(focus);
    this.notify(this.status());
    this.pump = this.download();
  }

  setFocus(t) { if (this.index) this.focus = this.chunkOf(t); }

  /** The next chunk to fetch: the playhead's and its neighbours (where a skip
   * either way lands), then on to the end, then back to the start. */
  nextMissing() {
    const n = this.chunks, f = Math.min(this.focus, n - 1);
    for (const d of [0, 1, -1, 2, -2, 3, -3]) {
      const i = f + d;
      if (i >= 0 && i < n && !this.have.has(i)) return i;
    }
    for (let i = f; i < n; i++) if (!this.have.has(i)) return i;
    for (let i = f - 1; i >= 0; i--) if (!this.have.has(i)) return i;
    return -1;
  }

  async download() {
    for (;;) {
      const i = this.nextMissing();
      if (i < 0) { this.state = 'complete'; this.notify(this.status()); return; }
      try {
        const r = await this.fetchImpl(this.chunkUrl(i), { priority: 'low' });
        if (!r.ok) { const e = new Error(`HTTP ${r.status}`); e.status = r.status; throw e; }
        const bytes = new Uint8Array(await r.arrayBuffer());
        await this.keep(i, bytes);
        this.bytes += bytes.length;
        this.failed = 0;
        this.notify(this.status());
      } catch (e) {
        // The pack is an optimisation: after a few failures (or a server that
        // no longer knows this pack) the views keep coming from /api/view.
        if (++this.failed >= 3 || (e && e.status >= 400 && e.status < 500) || e instanceof RangeError) { this.state = 'stopped'; this.notify(this.status()); return; }
        await new Promise((r) => setTimeout(r, 1000 * this.failed));
      }
    }
  }

  async keep(i, bytes) {
    if (this.cache) {
      try {
        await this.cache.put(this.chunkUrl(i), new Response(bytes, { headers: { 'Content-Type': 'application/octet-stream' } }));
        this.have.add(i);
        return;
      } catch { this.cache = null; } // quota, private mode: keep what fits in memory
    }
    if (this.memoryBytes + bytes.length > this.memoryLimit) throw new RangeError('pack memory limit');
    this.memory.set(i, bytes); this.memoryBytes += bytes.length;
    this.have.add(i);
  }

  async bytesOf(i) {
    const held = this.memory.get(i);
    if (held) return held;
    const hit = this.cache ? await this.cache.match(this.chunkUrl(i)) : null;
    if (!hit) { this.have.delete(i); throw new Error(`pack chunk ${i} is gone`); }
    return new Uint8Array(await hit.arrayBuffer());
  }

  /** Chunk `i`, parsed (a few are kept: playback and scrubbing stay in one or two). */
  open(i) {
    let p = this.parsed.get(i);
    if (p) { this.parsed.delete(i); this.parsed.set(i, p); return p; }
    p = this.bytesOf(i).then(gunzipText).then((text) => {
      const doc = JSON.parse(text);
      const chunk = new PackChunk(doc);
      chunk.trees = doc.trees || []; chunk.terrain = doc.terrain || [];
      return chunk;
    });
    p.catch(() => { if (this.parsed.get(i) === p) this.parsed.delete(i); });
    this.parsed.set(i, p);
    while (this.parsed.size > this.parsedLimit) this.parsed.delete(this.parsed.keys().next().value);
    return p;
  }

  /** The view a request for time `t` gets (as /api/view?t=). */
  async view(t) {
    const k = keyframeIndex(this.index.times, t), n = this.index.chunk_views;
    const chunk = await this.open(Math.floor(k / n));
    return chunk.view(k % n);
  }

  /** The forest ('trees') or terrain snapshot in force at `t`: { t, bytes, kinds } or null. */
  async tiles(kind, t) {
    const chunk = await this.open(this.chunkOf(t));
    const got = tilesAt(kind === 'trees' ? chunk.trees : chunk.terrain, t);
    return got && { t: got.t, bytes: got.bytes.slice(), kinds: got.kinds };
  }

  // Which packs this browser holds and when each was last opened; the oldest
  // beyond PACKS_KEPT are removed, chunk by chunk.
  async touchManifest() {
    const hit = await this.cache.match(MANIFEST);
    let packs = {};
    try { packs = hit ? await hit.json() : {}; } catch { packs = {}; }
    packs[this.index.key] = Date.now();
    const old = Object.keys(packs).sort((a, b) => packs[b] - packs[a]).slice(PACKS_KEPT);
    if (old.length) {
      const gone = new Set(old);
      for (const req of await this.cache.keys()) {
        const k = new URL(req.url).searchParams.get('k');
        if (k && gone.has(k)) await this.cache.delete(req);
      }
      for (const k of old) delete packs[k];
    }
    await this.cache.put(MANIFEST, new Response(JSON.stringify(packs), { headers: { 'Content-Type': 'application/json' } }));
  }
}
