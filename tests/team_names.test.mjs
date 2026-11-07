import assert from 'node:assert/strict';
import { test } from 'node:test';
const { baseTeamLabel, compactTeamLabels, memberLabel } = await import('../src/vantage/web/team-names.js');

test('a twin team is named once; mixed teams show two names and a count', () => {
  assert.equal(baseTeamLabel(['Immortal v0d10f', 'Immortal v0d10f']), 'Immortal v0d10f');
  assert.equal(baseTeamLabel(['Ash', 'Birch']), 'Ash + Birch');
  assert.equal(baseTeamLabel(['Ash', 'Birch', 'Cedar', 'Dune']), 'Ash + Birch +2');
  assert.equal(baseTeamLabel(['Solo']), 'Solo');
});

test('words every twin team shares are dropped', () => {
  const ai = (n, v) => Array(n).fill(`Immortal ${v}`);
  assert.deepEqual(compactTeamLabels([ai(2, 'v0d10f'), ai(2, 'v0d9')]), ['v0d10f', 'v0d9']);
  assert.deepEqual(compactTeamLabels([ai(4, 'v0d10f'), ['Extreme AI', 'Extreme AI']]), ['Immortal v0d10f', 'Extreme AI']);
});

test('mixed teams keep their names; colliding labels fall back to team numbers', () => {
  assert.deepEqual(compactTeamLabels([['Ash', 'Birch'], ['Cedar']]), ['Ash + Birch', 'Cedar']);
  const mirror = [['Immortal', 'Immortal'], ['Immortal', 'Immortal']];
  assert.deepEqual(compactTeamLabels(mirror), ['Team 1', 'Team 2']);
  assert.deepEqual(compactTeamLabels(mirror, (i) => `T${i + 1}`), ['T1', 'T2']);
});

test('a member sharing its name with a teammate is labelled by civilisation, then number', () => {
  const team = [{ id: 1, name: 'Immortal', civ: 'Franks' }, { id: 3, name: 'Immortal', civ: 'Mongols' }, { id: 5, name: 'Hera', civ: 'Franks' }];
  assert.equal(memberLabel(team[0], team), 'Franks');
  assert.equal(memberLabel(team[2], team), 'Hera');
  const sameCiv = [{ id: 2, name: 'AI', civ: 'Huns' }, { id: 4, name: 'AI', civ: 'Huns' }];
  assert.equal(memberLabel(sameCiv[1], sameCiv), 'P4');
});
