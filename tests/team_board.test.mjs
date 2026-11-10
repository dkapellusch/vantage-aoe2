import assert from 'node:assert/strict';
import { test } from 'node:test';
globalThis.window = { addEventListener() {}, innerWidth: 1600, innerHeight: 900 };
globalThis.document = { getElementById() { return null; }, addEventListener() {}, documentElement: { style: { setProperty() {} } } };
const { compare, sumStat, SECTIONS } = await import('../src/vantage/web/team-board.js');

test('the leader is the larger side, or the smaller one when fewer is better', () => {
  assert.deepEqual(compare(300, 200), { diff: 100, lead: 'a', aPct: 100, bPct: (100 * 200) / 300 });
  assert.equal(compare(3, 8, true).lead, 'a');
  assert.equal(compare(5, 5).lead, null);
  assert.deepEqual(compare(0, 0), { diff: 0, lead: null, aPct: 0, bPct: 0 });
});

test('team sums skip players without the stat; a stat nobody has leaves its row out', () => {
  const stats = [{ collected_rate: { total: 600 } }, { collected_rate: { total: 450 } }, null, {}];
  assert.equal(sumStat(stats, (s) => s.collected_rate?.total), 1050);
  assert.equal(sumStat([{}, {}], (s) => s.collected_rate?.total), null);
});

test('the board has the collection rate and whole-game collected sections', () => {
  const keys = SECTIONS.map((s) => s.key);
  assert.ok(keys.includes('rate') && keys.includes('collected'));
  const rate = SECTIONS.find((s) => s.key === 'rate');
  assert.deepEqual(rate.rows.map((r) => r.f({ collected_rate: { total: 9, food: 1, wood: 2, gold: 3, stone: 4 } })), [9, 1, 2, 3, 4]);
});
