import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { replayBufferWait } from '../src/vantage/web/playback.js';

// 10-minute replay; the game has produced 2 min of it at 2 game s per wall s while
// the viewer watches at 8x: the viewer is ahead of the game and must wait.
const base = { total: 600_000, end: 120_000, t: 100_000, watch: 8, rate: 2, samples: 6, producing: true };

test('waits for a game that is producing slower than the viewer watches', () => {
  assert.ok(replayBufferWait(base) > 0);
});

test('plays at once when the game keeps up, has not been measured, or is at its end', () => {
  assert.equal(replayBufferWait({ ...base, rate: 8 }), 0);
  assert.equal(replayBufferWait({ ...base, samples: 2 }), 0);
  assert.equal(replayBufferWait({ ...base, end: 599_500 }), 0);
});

test('never waits for a game that has stopped producing (paused at the replay end, or ended)', () => {
  // The game paused itself 4 s short of the header length: its rate decays to ~0,
  // which used to ask for an hours-long wait and froze the viewer.
  const stalled = { ...base, end: 596_000, t: 590_000, rate: 0 };
  assert.ok(replayBufferWait({ ...stalled, producing: true }) > 1e6);
  assert.equal(replayBufferWait({ ...stalled, producing: false }), 0);
});
