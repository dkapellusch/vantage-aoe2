// The parity oracle of the view pack: what the browser rebuilds from the pack
// (timeline-pack.js, the code the page runs) against what the server answers,
// at many random times of a served recording.
//
//   node tools/perf/pack_parity.mjs http://127.0.0.1:8792 [--times 400] [--seed 1] [--out parity.json]
//
// Compared at every time: the view (/api/view?t=, deep equality and the same
// key order), the forest (/api/trees?t=) and the terrain (/api/terrain?t=)
// byte for byte. Times are random over the match plus its edges and the times
// either side of every chunk boundary. Exits 1 on any difference.
import { writeFileSync } from 'node:fs';
import { isDeepStrictEqual } from 'node:util';
import { PackStore } from '../../src/vantage/web/timeline-pack.js';

const args = process.argv.slice(2);
const base = args[0].replace(/\/$/, '');
const opt = (name, fallback) => { const i = args.indexOf(`--${name}`); return i < 0 ? fallback : args[i + 1]; };
const count = Number(opt('times', 400)), seed = Number(opt('seed', 1)), out = opt('out', null);

let state = seed >>> 0 || 1;
const random = () => { state ^= state << 13; state >>>= 0; state ^= state >> 17; state ^= state << 5; state >>>= 0; return state / 4294967296; };
const json = async (path) => (await fetch(base + path)).json();
const b64 = (s) => new Uint8Array(Buffer.from(s, 'base64'));

const t0 = performance.now();
const store = new PackStore({ fetchImpl: (url, opts) => fetch(url, opts), memoryLimit: 4 * 1024 ** 3 });
await store.start(`${base}/api/pack`);
if (store.status().state === 'off') { console.error('no pack here (is the recording still loading?)'); process.exit(2); }
await store.pump;
const status = store.status();
if (status.state !== 'complete') { console.error('the pack did not download', status); process.exit(2); }
const downloadS = (performance.now() - t0) / 1000;

const times = store.index.times, n = store.index.chunk_views;
const start = times[0], end = times[times.length - 1];
const at = new Set([start - 1000, start, start + 1, end - 1, end, end + 5000]);
for (let i = 0; i < count; i++) at.add(Math.round(start + random() * (end - start)));
// Either side of chunk boundaries (a sample of them when there are many).
const edges = [];
for (let k = n; k < times.length; k += n) edges.push(k);
for (let i = 0; i < Math.min(edges.length, Math.ceil(count / 8)); i++) {
  const k = edges[Math.floor(random() * edges.length)];
  at.add(times[k] - 1); at.add(times[k]); at.add(times[k - 1]);
}

const bad = [], ms = [];
let views = 0, trees = 0, terrain = 0;
for (const t of at) {
  const [want, wantTrees, wantTerrain] = await Promise.all([json(`/api/view?t=${t}`), json(`/api/trees?t=${t}`), json(`/api/terrain?t=${t}`)]);
  const a = performance.now();
  const got = await store.view(t);
  ms.push(performance.now() - a);
  views++;
  if (!isDeepStrictEqual(got, want) || JSON.stringify(got) !== JSON.stringify(want)) bad.push({ t, what: 'view', time: [got && got.time, want.time] });
  for (const [kind, wanted] of [['trees', wantTrees], ['terrain', wantTerrain]]) {
    const mine = await store.tiles(kind, t);
    if (kind === 'trees') trees++; else terrain++;
    if (!wanted.tiles) { if (mine) bad.push({ t, what: kind, why: 'the server has none' }); continue; }
    const same = mine && mine.t === wanted.t && Buffer.compare(Buffer.from(mine.bytes), Buffer.from(b64(wanted.tiles))) === 0
      && (kind !== 'trees' || isDeepStrictEqual(mine.kinds, wanted.kinds || []));
    if (!same) bad.push({ t, what: kind, snapshot: [mine && mine.t, wanted.t] });
  }
}
ms.sort((x, y) => x - y);
const result = {
  base, key: status.key, keyframes: times.length, chunks: status.chunks, pack_mb: +(status.bytes / 1048576).toFixed(2),
  download_s: +downloadS.toFixed(1), times: at.size, views, trees, terrain, different: bad.length, examples: bad.slice(0, 10),
  rebuild_ms: { p50: +ms[ms.length >> 1].toFixed(2), p95: +ms[Math.floor(ms.length * 0.95)].toFixed(2), max: +ms[ms.length - 1].toFixed(2) },
};
console.log(JSON.stringify(result, null, 1));
if (out) writeFileSync(out, JSON.stringify(result, null, 1));
process.exit(bad.length ? 1 : 0);
