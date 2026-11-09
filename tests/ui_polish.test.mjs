import assert from 'node:assert/strict';
import { test } from 'node:test';
globalThis.window = { addEventListener() {}, innerWidth: 1600, innerHeight: 900 };
globalThis.document = { getElementById() { return null; }, addEventListener() {}, documentElement: { style: { setProperty() {} } } };
const { S, playerColor, playerMarkColor } = await import('../src/vantage/web/state.js');
const HK = await import('../src/vantage/web/hotkeys.js');

function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const lin = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
}

test('a player colour too dark for the panels is lifted for marks; the others stay the game colour', () => {
  S.match = { players: {
    1: { id: 1, color: '#0000ff', color_id: 0, team_key: 101 },
    2: { id: 2, color: '#ff0000', color_id: 1, team_key: 102 },
    4: { id: 4, color: '#ffff00', color_id: 3, team_key: 104 },
  } };
  assert.equal(playerColor(1), '#0000ff');
  const blue = playerMarkColor(1);
  assert.notEqual(blue, '#0000ff');
  assert.ok(luminance(blue) >= 0.16, `${blue} reads on a dark panel`);
  const n = parseInt(blue.slice(1), 16);
  assert.ok((n & 255) > ((n >> 16) & 255), 'still a blue');
  assert.equal(playerMarkColor(2), playerColor(2));
  assert.equal(playerMarkColor(4), playerColor(4));
});

test('the quick reference files every action under exactly one section', () => {
  const groups = HK.describeKeyGroups();
  const titles = groups.map(([title]) => title);
  assert.deepEqual(titles.slice(0, 2), ['Time controls', 'Panels']);
  assert.equal(new Set(titles).size, titles.length);
  const listed = groups.reduce((sum, [, rows]) => sum + rows.length, 0);
  assert.equal(listed, HK.describeKeys().length);
  const of = (title) => groups.find(([name]) => name === title)[1].map(([, description]) => description);
  assert.ok(of('Time controls').includes('Pause / play'));
  assert.ok(of('Fog of war and perspective').includes('Perspective: player 8'));
  assert.ok(of('Go to the next building').includes('Next barracks'));
  assert.ok(!of('Go to the next building').includes('Next idle villager'));
  assert.ok(of('Selecting and following').includes('Go to king'));
  assert.ok(of('Panels').includes('Statistics'));
});
