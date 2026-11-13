import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ShelfAtlas, available, draw } from '../src/vantage/web/sprite-gl.js';

test('frames pack side by side on shelves, then on new shelves, then in the next layer', () => {
  const a = new ShelfAtlas(2, 100);
  assert.deepEqual(a.place(40, 30, 1), [0, 0, 0]);
  assert.deepEqual(a.place(40, 25, 1), [0, 40, 0]); // fits the 30-high shelf
  assert.deepEqual(a.place(40, 30, 1), [0, 0, 30]); // that shelf is full: a new one below
  assert.deepEqual(a.place(30, 10, 1), [0, 0, 60]); // under 60 % of a shelf's height: its own shelf
  assert.deepEqual(a.place(50, 40, 1), [1, 0, 0]); // layer 0 has no room left
  assert.equal(a.usedLayers(), 2);
  assert.equal(a.place(101, 1, 1), null); // larger than a layer
});

test('a full atlas empties its least recently used layer, never one drawn this frame', () => {
  const a = new ShelfAtlas(2, 100);
  a.place(100, 60, 1);
  a.place(100, 60, 1); // layer 1
  a.touch(1, 2);
  assert.equal(a.gen(0), 0);
  // Frame 3: layer 0 (last used in frame 1) is emptied and reused.
  assert.deepEqual(a.place(100, 100, 3), [0, 0, 0]);
  assert.equal(a.gen(0), 1);
  assert.equal(a.gen(1), 0);
  assert.equal(a.evictions, 1);
  // Still frame 3, layer 1 last used in frame 2: emptied in turn.
  assert.deepEqual(a.place(100, 100, 3), [1, 0, 0]);
  // Both layers hold frame 3's pictures: nothing can be evicted.
  assert.equal(a.place(100, 100, 3), null);
  assert.equal(a.evictions, 2);
});

test('without WebGL2 the batch reports unavailable and draws nothing', () => {
  const warn = console.warn;
  console.warn = () => {};
  try {
    assert.equal(available(), false);
    assert.equal(draw({ width: 1 }, 0, 1, 1, 0, 0, 1, 1), false);
  } finally { console.warn = warn; }
});

test('a full atlas grows (doubling, up to its budget) before it evicts anything', () => {
  const a = new ShelfAtlas(1, 100, 4);
  assert.deepEqual(a.place(100, 100, 1), [0, 0, 0]);
  // Layer 0 is full and in use this frame: the atlas doubles instead of evicting.
  assert.deepEqual(a.place(100, 100, 1), [1, 0, 0]);
  assert.equal(a.layers.length, 2);
  assert.deepEqual(a.place(100, 100, 2), [2, 0, 0]);
  assert.equal(a.layers.length, 4); // doubled again, to the budget
  assert.deepEqual(a.place(100, 100, 2), [3, 0, 0]);
  assert.equal(a.evictions, 0);
  assert.equal(a.grows, 2);
  // At the budget: the least recently used layer (0, frame 1) is emptied as before.
  assert.deepEqual(a.place(100, 100, 3), [0, 0, 0]);
  assert.equal(a.evictions, 1);
  assert.equal(a.layers.length, 4);
});

test('an atlas without a larger budget keeps its size', () => {
  const a = new ShelfAtlas(1, 100);
  a.place(100, 100, 1);
  assert.deepEqual(a.place(100, 100, 2), [0, 0, 0]);
  assert.equal(a.layers.length, 1);
  assert.equal(a.evictions, 1);
});

test('a full atlas empties the layer with the least area drawn lately, not the least recently touched', () => {
  const a = new ShelfAtlas(3, 100);
  // Three full layers of four 50 x 50 frames each.
  const slots = [];
  for (let i = 0; i < 12; i++) { const [layer] = a.place(50, 50, 1); const s = { layer, w: 50, h: 50 }; a.use(s, 1); slots.push(s); }
  assert.deepEqual(slots.map((s) => s.layer), [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2]);
  // Later: all of layer 0 is still drawn, one frame of layer 1, two of layer 2.
  // Layer 1 was touched most recently of all.
  for (const s of slots.slice(0, 4)) a.use(s, 400);
  for (const s of slots.slice(8, 10)) a.use(s, 400);
  a.use(slots[4], 401);
  assert.deepEqual(a.place(50, 50, 402), [1, 0, 0]);
  assert.equal(a.gen(1), 1);
  assert.equal(a.evictions, 1);
  // A frame drawn many times in a window counts once.
  const b = new ShelfAtlas(2, 100);
  const one = { layer: b.place(100, 100, 1)[0], w: 100, h: 100 }, two = { layer: b.place(50, 100, 1)[0], w: 50, h: 100 };
  const small = { layer: b.place(40, 100, 1)[0], w: 40, h: 100 };
  assert.deepEqual([one.layer, two.layer, small.layer], [0, 1, 1]);
  b.use(one, 2); b.use(two, 2);
  for (let i = 0; i < 50; i++) b.use(small, 2);
  assert.deepEqual(b.place(100, 100, 3), [1, 0, 0]); // 50 + 40 columns drawn once each < 100
});

test('heat fades: a layer not drawn for two windows is emptied before a warm one', () => {
  const a = new ShelfAtlas(2, 100);
  const cold = { layer: a.place(100, 100, 1)[0], w: 100, h: 100 }, warm = { layer: a.place(10, 100, 1)[0], w: 10, h: 100 };
  a.use(cold, 1); a.use(warm, 1);
  a.use(warm, 500); // frame 500 is two windows on: the big frame's heat is gone
  a.touch(0, 501);  // touched later than the warm layer, but nothing of it drawn
  assert.deepEqual(a.place(100, 100, 502), [0, 0, 0]);
});
