// The hub chart's pure helpers (tools/hub/web/chart.js).
import assert from 'node:assert/strict';
import test from 'node:test';
import { niceStep, rowAt, METRICS } from '../tools/hub/web/chart.js';

test('grid steps are round numbers', () => {
  assert.equal(niceStep(2931, 4), 1000);
  assert.equal(niceStep(65, 4), 20);
  assert.equal(niceStep(9, 4), 2.5);
  assert.equal(niceStep(0, 4) > 0, true);
});

test('rowAt finds the row at or before a time', () => {
  const rows = [{ t: 0, v: 1 }, { t: 5000, v: 2 }, { t: 10000, v: 3 }];
  assert.equal(rowAt(rows, 7000).v, 2);
  assert.equal(rowAt(rows, 10000).v, 3);
  assert.equal(rowAt(rows, 99999).v, 3);
  assert.equal(rowAt([{ t: 100 }], 50), null);
  assert.equal(rowAt([], 50), null);
});

test('every metric has a label', () => {
  for (const def of Object.values(METRICS)) assert.ok(def.label);
});
