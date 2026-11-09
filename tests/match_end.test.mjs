import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { matchEnded } from '../src/vantage/web/playback.js';

test('the match is over when the source says so or the game reports its state as done', () => {
  assert.equal(matchEnded({ status: 'ended' }), true);
  // A replay that reached its end: no flag in the world, the game's own state is DONE (3).
  assert.equal(matchEnded({ status: 'playing', game_state: 3 }), true);
  assert.equal(matchEnded({ status: 'ready', game_state: '3' }), true);
});

test('a running or unknown match is not over', () => {
  assert.equal(matchEnded({ status: 'playing', game_state: 2, paused: true }), false); // paused is not over
  assert.equal(matchEnded({ status: 'loading' }), false);
  assert.equal(matchEnded({}), false);
  assert.equal(matchEnded(null), false);
});
