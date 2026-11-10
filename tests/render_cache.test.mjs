import assert from 'node:assert/strict';
import { test } from 'node:test';
import { changedTilesInRegion, terrainRegion, changedTreeTiles, groundProjection, mergeDirtyRect, treeSpriteState, OutlineCache, coalesceRects } from '../src/vantage/web/render-cache.js';

test('tree fallback stops retrying permanent missing sprites but keeps retryable ones pending', () => {
  assert.equal(treeSpriteState(null), null); // request not yet admitted
  assert.equal(treeSpriteState({ failed: false }), null); // loading
  assert.equal(treeSpriteState({ failed: true, retryAt: 5000 }), null); // temporary error
  assert.equal(treeSpriteState({ failed: true }), false); // permanent 404 fallback
  const ready = { img: {}, meta: {} };
  assert.equal(treeSpriteState(ready), ready);
});

test('ground reprojection preserves centre, pan direction, and zoom coverage', () => {
  const cache = { x: 50, y: 50, zoom: 1, width: 1000, height: 600, padding: 128 };
  const project = (camera) => groundProjection(cache, camera, 1000, 600, 32, 16);
  assert.deepEqual(project({ x: 50, y: 50, zoom: 1 }), { x: -128, y: -128, scale: 1, covered: true });
  const pan = project({ x: 51, y: 50, zoom: 1 });
  assert.equal(pan.x, -144); assert.equal(pan.y, -120); assert.equal(pan.covered, true);
  assert.equal(project({ x: 60, y: 50, zoom: 1 }).covered, false);
  assert.equal(project({ x: 50, y: 50, zoom: 0.9 }).covered, true);
  assert.equal(project({ x: 50, y: 50, zoom: 0.7 }).covered, false);
  const zoom = project({ x: 50, y: 50, zoom: 1.1 });
  assert.equal(zoom.scale, 1.1); assert.equal(zoom.covered, true);
});

test('offscreen terrain changes keep the cache; changes on every boundary invalidate it', () => {
  const w = 100, bounds = [20, 40, 30, 50];
  assert.deepEqual(changedTilesInRegion([10, 80 * w + 80], w, bounds), []);
  for (const [x, y] of [[20, 30], [40, 30], [20, 50], [40, 50], [30, 40]]) {
    assert.deepEqual(changedTilesInRegion([y * w + x], w, bounds), [y * w + x]);
  }
  assert.deepEqual(changedTilesInRegion([10], w, null), [10]);
});

test('terrain blending invalidates when a neighbouring tile outside the last drawn chunk changes', () => {
  const bounds = terrainRegion([20, 40, 30, 50], 16), w = 100;
  assert.deepEqual(changedTilesInRegion([32 * w + 48], w, bounds), [32 * w + 48]);
  assert.deepEqual(changedTilesInRegion([32 * w + 15], w, bounds), [32 * w + 15]);
  assert.deepEqual(changedTilesInRegion([32 * w + 49], w, bounds), []);
});

test('dirty patches are clipped to the stored picture and merged without losing earlier changes', () => {
  const first = mergeDirtyRect(null, [10, 20, 30, 40], 1000, 600, 128);
  assert.deepEqual(first, [8, 18, 32, 42]);
  assert.equal(mergeDirtyRect(first, [2000, 2000, 2100, 2100], 1000, 600, 128), first);
  assert.deepEqual(mergeDirtyRect(first, [-500, -500, 0, 0], 1000, 600, 128), [-128, -128, 32, 42]);
  assert.deepEqual(first, [8, 18, 32, 42]);
});

const forest = () => ({ tiles: new Uint8Array(100), facets: new Uint8Array(100), kinds: [100, 200] });
test('offscreen trees update without invalidating the cached region', () => {
  const before = forest(), after = forest();
  before.tiles[11] = 1; // outside the cached picture
  before.tiles[55] = after.tiles[55] = 1;
  assert.deepEqual(changedTreeTiles(before, after, 10, [4, 6, 4, 6]), []);
  after.tiles[55] = 0;
  assert.deepEqual(changedTreeTiles(before, after, 10, [4, 6, 4, 6]), [55]);
});

test('tree facets invalidate the cache, but kind-index renumbering preserves the same picture', () => {
  const before = forest(), after = forest();
  before.tiles[55] = 1; after.tiles[55] = 2; after.kinds = [200, 100];
  assert.deepEqual(changedTreeTiles(before, after, 10, [4, 6, 4, 6]), []);
  after.facets[55] = 3;
  assert.deepEqual(changedTreeTiles(before, after, 10, [4, 6, 4, 6]), [55]);
  assert.equal(changedTreeTiles({ ...before, tiles: null }, after, 10, [4, 6, 4, 6]), null);
  assert.equal(changedTreeTiles(before, after, 10, null), null);
});

test('outline keys preserve subpixel geometry, sprite frames, image identity, colour and DPI', () => {
  const cache = new OutlineCache(), img = {};
  const p = [[img, 0, 20, 30, 100.25, 200.5, 10, 15]];
  const key = cache.key(p, '#00f', 98, 198, 1, 15, 20);
  const moved = [[img, 0, 20, 30, 110.25, 210.5, 10, 15]];
  assert.equal(cache.key(moved, '#00f', 108, 208, 1, 15, 20), key);
  assert.notEqual(cache.key(p, '#f00', 98, 198, 1, 15, 20), key);
  assert.notEqual(cache.key(p, '#00f', 98, 198, 2, 30, 40), key);
  for (const [field, value] of [[0, {}], [1, 20], [4, 100.3], [7, 16]]) {
    const changed = p[0].slice(); changed[field] = value;
    assert.notEqual(cache.key([changed], '#00f', 98, 198, 1, 15, 20), key);
  }
});

test('outline rasters use a bounded LRU and do not retain oversized entries', () => {
  const cache = new OutlineCache(16), a = {}, b = {}, c = {};
  cache.set('a', a, 8); cache.set('b', b, 8);
  assert.equal(cache.get('a'), a);
  cache.set('c', c, 8);
  assert.equal(cache.get('b'), null);
  assert.equal(cache.get('a'), a);
  assert.equal(cache.bytes, 16);
  cache.set('oversized', {}, 20);
  assert.equal(cache.bytes, 16); assert.equal(cache.get('oversized'), null);
  cache.set('a', a, 4); assert.equal(cache.bytes, 12);
});

test('changed tiles far apart repaint as separate rectangles, near ones as one', () => {
  // Two farms at opposite corners: two small rectangles, not the whole map.
  const far = coalesceRects([[0, 0, 10, 10], [990, 990, 1000, 1000]]);
  assert.deepEqual(far, [[0, 0, 10, 10], [990, 990, 1000, 1000]]);
  // Touching or overlapping rectangles merge when the union wastes little.
  assert.deepEqual(coalesceRects([[0, 0, 10, 10], [8, 0, 18, 10], [16, 0, 26, 10]]), [[0, 0, 26, 10]]);
  // A merge that would cover far more than the parts is not made.
  assert.equal(coalesceRects([[0, 0, 10, 10], [11, 40, 21, 50]]).length, 2);
  assert.deepEqual(coalesceRects([]), []);
  // Every input pixel stays covered.
  const rs = Array.from({ length: 60 }, (_, i) => [(i * 37) % 500, (i * 91) % 500, (i * 37) % 500 + 12, (i * 91) % 500 + 9]);
  const out = coalesceRects(rs);
  for (const [x0, y0, x1, y1] of rs) assert.ok(out.some(([a, b, c, d]) => a <= x0 && b <= y0 && c >= x1 && d >= y1));
  // A row of neighbouring tiles (a new field of farms) becomes one rectangle.
  assert.deepEqual(coalesceRects(Array.from({ length: 20 }, (_, i) => [i * 8, 0, i * 8 + 16, 16])), [[0, 0, 168, 16]]);
});

test('a thousand changed tiles coalesce quickly and stay covered', () => {
  const rs = Array.from({ length: 1200 }, (_, i) => [(i % 40) * 20, Math.floor(i / 40) * 12, (i % 40) * 20 + 24, Math.floor(i / 40) * 12 + 16]);
  const t0 = performance.now();
  const out = coalesceRects(rs);
  assert.ok(performance.now() - t0 < 50, 'fast');
  for (const [x0, y0, x1, y1] of rs) assert.ok(out.some(([a, b, c, d]) => a <= x0 && b <= y0 && c >= x1 && d >= y1));
  assert.ok(out.length <= 64);
});
