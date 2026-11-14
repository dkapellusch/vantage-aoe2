import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { gzipSync } from 'node:zlib';
import { applyDelta, PackChunk, PackStore, keyframeIndex, tilesAt, gunzipText, PACK_VERSION, PACK_CACHE, PACKS_KEPT, PACK_BYTES } from '../src/vantage/web/timeline-pack.js';
import { createHandler, QUICK_MS } from '../src/vantage/web/view-worker.js';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/viewpack-chunk.json', import.meta.url), 'utf8'));
const fromB64 = (s) => new Uint8Array(Buffer.from(s, 'base64'));

test('a delta copies, patches, adds and drops rows, and keeps what did not change', () => {
  const old = [[1, 0, 5, [[7, 0]]], [2, 0, 6, [[7, 1]]], [3, 1, 1, 0], [4, 1, 2, 0], [-9, 1, 0, 0]];
  const delta = [2, [0, 0, 1, 1, 1, [2, 6.5, 3, [[7, 2]]], 2, 3, 5, [4, 'x'], 3, [5, 2, 0, 0], 0, 4, 1]];
  const got = applyDelta(old, delta);
  assert.deepEqual(got, [[1, 0, 5, [[7, 0]]], [2, 0, 6.5, [[7, 2]]], [4, 1, 2, 0, 'x'], [5, 2, 0, 0], [-9, 1, 0, 0]]);
  assert.equal(got[0], old[0]); // shared, not copied
  assert.deepEqual(old[1], [2, 0, 6, [[7, 1]]]); // and the old list is as it was
  // a row that got shorter
  assert.deepEqual(applyDelta([[1, 2, 3, 4]], [2, [2, 0, 2, [1, 9]]]), [[1, 9]]);
});

test('object and positional deltas', () => {
  const old = { a: 1, b: { x: 1, y: [1, 2] }, c: 3 };
  const got = applyDelta(old, [1, { b: [1, { x: [0, 2] }, []], d: [0, 4] }, ['c']]);
  assert.deepEqual(got, { a: 1, b: { x: 2, y: [1, 2] }, d: 4 });
  assert.deepEqual(Object.keys(got), ['a', 'b', 'd']);
  assert.equal(got.b.y, old.b.y);
  assert.deepEqual(applyDelta([[1.5, 'a'], [1.5, 'b']], [3, [1, [3, [1, [0, 'x']]]]]), [[1.5, 'a'], [1.5, 'x']]);
  assert.deepEqual(applyDelta(old, [0, null]), null);
  assert.throws(() => applyDelta(old, [9]));
});

test('the keyframe a time resolves to, as the server picks it', () => {
  const times = [50, 1050, 2050, 2050, 3050];
  assert.deepEqual([-5, 50, 51, 1049, 1050, 2050, 2999, 3050, 99999].map((t) => keyframeIndex(times, t)), [0, 0, 0, 0, 1, 3, 3, 4, 4]);
});

test("the encoder's chunk (viewpack.py) is rebuilt view for view, and its tile snapshots", async () => {
  const doc = JSON.parse(await gunzipText(fromB64(fixture.gzip)));
  assert.equal(doc.v, PACK_VERSION);
  const chunk = new PackChunk(doc);
  assert.equal(chunk.length, fixture.views.length);
  // out of order on purpose: a view is built from the nearest one before it
  for (const k of [3, 0, 9, 5, 1, 2, 4, 6, 7, 8]) assert.deepEqual(chunk.view(k), fixture.views[k]);
  assert.equal(JSON.stringify(chunk.view(9)), JSON.stringify(fixture.views[9])); // key order too
  for (const [kind, rows, want] of [['trees', doc.trees, fixture.trees], ['terrain', doc.terrain, fixture.terrain]]) {
    assert.ok(want.length, kind);
    for (const [t, b64, kinds] of want) {
      const got = tilesAt(rows, t + 1);
      assert.equal(got.t, t);
      assert.deepEqual(got.bytes, fromB64(b64));
      if (kinds) assert.deepEqual(got.kinds, kinds);
    }
    assert.equal(tilesAt(rows, want[0][0] - 1), null);
  }
  assert.throws(() => new PackChunk({ v: 99 }));
});

// A pack of 25 views in chunks of 10, served from memory.
function fakeServer({ views = 25, chunkViews = 10, key = 'k1', failChunk = -1 } = {}) {
  const all = Array.from({ length: views }, (_, i) => ({ time: i * 1000, entities: [[1, i], [2, 0]], n: i }));
  const index = { v: PACK_VERSION, key, chunk_views: chunkViews, times: all.map((v) => v.time) };
  const chunk = (i) => {
    const mine = all.slice(i * chunkViews, (i + 1) * chunkViews);
    const deltas = mine.slice(1).map((v) => [1, { time: [0, v.time], entities: [2, [1, 0, [1, v.n], 0, 1, 1]], n: [0, v.n] }, []]);
    const trees = [[mine[0].time, 0, Buffer.from([i, 0, 0, 0]).toString('base64'), [7]], [mine[0].time + 500, 1, Buffer.from([0, 1, 0, 0]).toString('base64'), [7, 8]]];
    return gzipSync(JSON.stringify({ v: PACK_VERSION, times: mine.map((v) => v.time), base: mine[0], deltas, trees, terrain: [] }));
  };
  const log = [];
  const fetchImpl = async (url, opts = {}) => {
    const u = new URL(url);
    log.push(u.pathname + u.search);
    if (opts.signal && opts.signal.aborted) throw new DOMException('aborted', 'AbortError');
    if (u.pathname === '/api/pack') return new Response(JSON.stringify(index));
    if (u.pathname === '/api/pack/chunk') {
      const i = Number(u.searchParams.get('i'));
      if (u.searchParams.get('k') !== key || i === failChunk) return new Response('', { status: 404 });
      return new Response(chunk(i));
    }
    if (u.pathname === '/api/view') return new Response(JSON.stringify({ time: Number(u.searchParams.get('t')), net: true }));
    if (u.pathname === '/api/trees') return new Response(JSON.stringify({ t: 5, tiles: Buffer.from([9, 9]).toString('base64'), kinds: [1] }));
    return new Response('{}');
  };
  return { all, index, fetchImpl, log };
}

// The Cache Storage a worker has, as far as PackStore uses it.
function fakeCaches() {
  const stores = new Map();
  return {
    stores,
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Map());
      const m = stores.get(name);
      const href = (r) => new URL(typeof r === 'string' ? r : r.url, 'http://x').href;
      return {
        async put(req, res) { m.set(href(req), await res.arrayBuffer()); },
        async match(req) { const b = m.get(href(req)); return b ? new Response(b) : undefined; },
        async keys() { return [...m.keys()].map((url) => ({ url })); },
        async delete(req) { return m.delete(href(req)); },
      };
    },
  };
}

test('the store downloads from the playhead on, then the rest, and answers from what it holds', async () => {
  const { all, fetchImpl, log } = fakeServer();
  const seen = [];
  const store = new PackStore({ fetchImpl, cacheStorage: fakeCaches(), notify: (s) => seen.push(s) });
  await store.start('http://x/api/pack', 12000);
  await store.pump;
  assert.deepEqual(log, ['/api/pack', '/api/pack/chunk?i=1&k=k1', '/api/pack/chunk?i=2&k=k1', '/api/pack/chunk?i=0&k=k1']);
  assert.equal(store.status().state, 'complete');
  assert.equal(seen.at(-1).have, 3);
  for (const t of [0, 999, 1000, 9999, 10000, 17500, 24000, 99999, -3]) {
    assert.ok(store.holds(t));
    assert.deepEqual(await store.view(t), all[Math.max(0, Math.min(24, Math.floor(t / 1000)))]);
  }
  assert.deepEqual(await store.tiles('trees', 10600), { t: 10500, bytes: new Uint8Array([1, 1, 0, 0]), kinds: [7, 8] });
  assert.deepEqual(await store.tiles('trees', 10400), { t: 10000, bytes: new Uint8Array([1, 0, 0, 0]), kinds: [7] });
  assert.equal(await store.tiles('terrain', 10400), null);
  assert.equal(log.length, 4); // nothing more was fetched
});

test('a second visit finds the chunks in Cache Storage; old packs make room', async () => {
  const cacheStorage = fakeCaches();
  const first = fakeServer();
  const a = new PackStore({ fetchImpl: first.fetchImpl, cacheStorage });
  await a.start('http://x/api/pack'); await a.pump;
  const again = fakeServer();
  const b = new PackStore({ fetchImpl: again.fetchImpl, cacheStorage });
  await b.start('http://x/api/pack'); await b.pump;
  assert.deepEqual(again.log, ['/api/pack']); // the index only
  assert.deepEqual(await b.view(24000), again.all[24]);
  // More packs than are kept: the one opened longest ago goes, chunks and all.
  await new Promise((r) => setTimeout(r, 3)); // a later millisecond than that visit
  for (let i = 0; i < PACKS_KEPT; i++) {
    const s = new PackStore({ fetchImpl: fakeServer({ key: `other${i}`, views: 5 }).fetchImpl, cacheStorage });
    await s.start('http://x/api/pack'); await s.pump;
    await new Promise((r) => setTimeout(r, 2));
  }
  const urls = [...cacheStorage.stores.get(PACK_CACHE).keys()];
  assert.equal(urls.filter((u) => u.includes('k=k1')).length, 0);
  assert.equal(urls.filter((u) => u.includes('/chunk')).length, PACKS_KEPT);
});

test('packs are also removed by size: the oldest beyond the byte limit', async () => {
  const cacheStorage = fakeCaches();
  const open = async (key) => {
    const s = new PackStore({ fetchImpl: fakeServer({ key, views: 5 }).fetchImpl, cacheStorage });
    await s.start('http://x/api/pack'); await s.pump;
    await new Promise((r) => setTimeout(r, 2));
    return s;
  };
  const a = await open('a'); await open('b');
  const manifest = async () => JSON.parse(Buffer.from(cacheStorage.stores.get(PACK_CACHE).get('http://x/__vantage_pack_manifest')).toString());
  const sizes = await manifest();
  assert.equal(sizes.a[1], a.status().bytes); // what was stored is recorded
  // As if "a" and "b" were long team games: together over the limit.
  sizes.a[1] = sizes.b[1] = PACK_BYTES * 0.6;
  cacheStorage.stores.get(PACK_CACHE).set('http://x/__vantage_pack_manifest', new TextEncoder().encode(JSON.stringify(sizes)).buffer);
  await open('c');
  const left = await manifest();
  assert.deepEqual(Object.keys(left).sort(), ['b', 'c']);
  const urls = [...cacheStorage.stores.get(PACK_CACHE).keys()];
  assert.equal(urls.filter((u) => u.includes('k=a')).length, 0);
  assert.equal(urls.filter((u) => u.includes('k=b')).length, 1);
});

test('without Cache Storage the chunks are held in memory, up to a limit', async () => {
  const { fetchImpl, all } = fakeServer();
  const store = new PackStore({ fetchImpl });
  await store.start('http://x/api/pack'); await store.pump;
  assert.equal(store.status().have, 3);
  assert.deepEqual(await store.view(5000), all[5]);
  const small = new PackStore({ fetchImpl: fakeServer().fetchImpl, memoryLimit: 150 });
  await small.start('http://x/api/pack'); await small.pump;
  assert.equal(small.status().state, 'stopped');
  assert.ok(small.status().have < 3);
});

test('no pack (a growing match, an older server) leaves the store off; a missing chunk stops it', async () => {
  const off = new PackStore({ fetchImpl: async () => new Response('{}') });
  await off.start('http://x/api/pack');
  assert.equal(off.status().state, 'off');
  assert.equal(off.status().building, false);
  // A pack being built: off for now, and the page knows to ask again; then it is there.
  const server = fakeServer();
  let built = false;
  const later = new PackStore({ fetchImpl: async (url, opts) => (!built && url.endsWith('/api/pack') ? new Response('{"building":true}') : server.fetchImpl(url, opts)) });
  await later.start('http://x/api/pack');
  assert.deepEqual([later.status().state, later.status().building], ['off', true]);
  built = true;
  await later.start('http://x/api/pack'); await later.pump;
  assert.deepEqual([later.status().state, later.status().building, later.status().have], ['complete', false, 3]);
  assert.equal(off.holds(0), false);
  const old = new PackStore({ fetchImpl: async () => new Response('nope', { status: 404 }) });
  await old.start('http://x/api/pack');
  assert.equal(old.status().state, 'off');
  const broken = new PackStore({ fetchImpl: fakeServer({ failChunk: 1 }).fetchImpl });
  await broken.start('http://x/api/pack'); await broken.pump;
  assert.equal(broken.status().state, 'stopped');
  assert.ok(broken.holds(0) && !broken.holds(10000));
});

test('beside a fast server the worker asks it for a view whose chunk is not open yet', async () => {
  const { fetchImpl, all, log } = fakeServer();
  const posts = [];
  const handle = createHandler((m) => posts.push(m), fetchImpl, fakeCaches());
  await handle({ id: 1, url: 'http://x/api/view?t=3000', t: 3000 }); // measured: far under QUICK_MS
  assert.ok(QUICK_MS > 5);
  await handle({ pack: 'http://x/api/pack', t: 0 });
  await handle.store.pump;
  posts.length = 0; log.length = 0;
  await handle({ id: 2, url: 'http://x/api/view?t=12000', t: 12000 });
  assert.deepEqual(posts.pop(), { id: 2, value: { time: 12000, net: true } }); // the server, and the chunk opens
  await handle.store.open(1);
  await handle({ id: 3, url: 'http://x/api/view?t=13000', t: 13000 });
  assert.deepEqual(posts.pop(), { id: 3, value: all[13], local: true }); // open now: rebuilt here
  await handle({ id: 4, url: 'http://x/api/trees?t=600', t: 600, tiles: 'trees' }); // tiles are always local
  assert.equal(posts.pop().local, true);
  assert.deepEqual(log, ['/api/view?t=12000']);
});

// A server 30 ms away: every view of a held chunk is rebuilt locally.
const slow = (fetchImpl) => async (url, opts) => { if (url.includes('/api/view')) await new Promise((r) => setTimeout(r, 30)); return fetchImpl(url, opts); };

test('the worker answers a view from the pack when it holds it, else from /api/view', async () => {
  const server = fakeServer({ failChunk: 2 });
  const { all, log } = server, fetchImpl = slow(server.fetchImpl);
  const posts = [];
  const handle = createHandler((m, transfer) => posts.push([m, transfer]), fetchImpl, fakeCaches());
  await handle({ id: 1, url: 'http://x/api/view?t=3000', t: 3000 }); // before the pack: the network
  assert.deepEqual(posts.pop()[0], { id: 1, value: { time: 3000, net: true } });
  await handle({ pack: 'http://x/api/pack', t: 0 });
  await handle.store.pump;
  assert.ok(posts.some(([m]) => m.pack && m.pack.have === 2));
  posts.length = 0; log.length = 0;
  await handle({ id: 2, url: 'http://x/api/view?t=3000', t: 3000 });
  assert.deepEqual(posts.pop()[0], { id: 2, value: all[3], local: true });
  await handle({ id: 3, url: 'http://x/api/view?t=21000', t: 21000 }); // the chunk that failed
  assert.deepEqual(posts.pop()[0], { id: 3, value: { time: 21000, net: true } });
  await handle({ id: 4, url: 'http://x/api/trees?t=600', t: 600, tiles: 'trees' });
  const [local, transfer] = posts.pop();
  assert.deepEqual(local, { id: 4, value: { t: 500, bytes: new Uint8Array([0, 1, 0, 0]), kinds: [7, 8] }, local: true });
  assert.equal(transfer[0], local.value.bytes.buffer);
  await handle({ id: 5, url: 'http://x/api/trees?t=21000', t: 21000, tiles: 'trees' });
  assert.deepEqual(posts.pop()[0], { id: 5, value: { t: 5, bytes: new Uint8Array([9, 9]), kinds: [1] } });
  await handle({ id: 6, url: 'http://x/api/terrain?t=21000', t: 21000, tiles: 'terrain' });
  assert.deepEqual(posts.pop()[0], { id: 6, value: null });
  assert.deepEqual(log, ['/api/view?t=21000', '/api/trees?t=21000', '/api/terrain?t=21000']);
});
