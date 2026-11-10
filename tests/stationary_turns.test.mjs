import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { RowInterpolator } from '../src/vantage/web/playback.js';

test('intermediate stationary turns are visible between identical keyframes', () => {
  const row = [104, 2, 38, 3, 3, 1, 2, 0, [], 1];
  const view = {
    time: 1000, entities: [row],
    unit_track: [[1100, [[104, 3, 3, 5]]], [1300, [[104, 3, 3, 0]]]],
  };
  const next = { time: 2000, entities: [row.slice()] };
  const interpolate = new RowInterpolator(() => 16);
  assert.equal(interpolate.at(view, next, 1050)[0][7], 0);
  assert.equal(interpolate.at(view, next, 1100)[0][7], 5);
  assert.equal(interpolate.at(view, next, 1250)[0][7], 5);
  assert.equal(interpolate.at(view, next, 1300)[0][7], 0);
  assert.equal(row[7], 0);
});
