import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

// Use the actual definitions; importing panels.js would start the DOM renderer.
const source = readFileSync(new URL('../src/vantage/web/panels.js', import.meta.url), 'utf8');
const definitions = source.slice(source.indexOf('const OVERVIEW_COLS ='), source.indexOf('// The dashboard layout (page-set key)'));
const { DASH_PAGES: pages, DASH_LAYOUTS: layouts } = new Function(`${definitions.replaceAll('export const ', 'const ')}; return {DASH_PAGES,DASH_LAYOUTS};`)();
const oldColumns = ['vils', 'idle', 'pop', 'mil', 'milValue', 'kd', 'ecoKills', 'ecoDeaths', 'idleTcHoused', 'tcCastle'];
test('team Overview keeps eco-loss columns in order and appends total collected', () => {
  const overview = pages.find(p => p.key === 'overviewEcoLosses');
  assert.equal(overview.title, 'Overview');
  assert.deepEqual(overview.cols, [...oldColumns, 'colT']);
  assert.ok(!pages.some(p => p.key === 'overviewSmall'));
  assert.deepEqual(layouts.oppositional, ['overviewEcoLosses', 'ecoInfo', 'stockpiles', 'apmPaired', 'workerEfficiencyOverall', 'workerEfficiencyBreakdown', 'military', 'trade']);
  assert.ok(Object.values(layouts).flat().every(key => pages.some(p => p.key === key)));
});
test('1v1 and the independently retained FFA pages do not change', () => {
  assert.deepEqual(layouts.nonOppositional, ['overview', 'apm', 'ecoActivity', 'ecoInfo', 'stockpiles', 'military', 'trade']);
  assert.deepEqual(pages.find(p => p.key === 'overview').cols, ['wFood', 'wWood', 'wGold', 'wStone', 'build', 'idle', 'pop', 'mil', 'milValue', 'kd', 'tc', 'idleTcHoused']);
  assert.deepEqual(pages.find(p => p.key === 'overviewEcoLossesFfa').cols, oldColumns);
  assert.equal(pages.find(p => p.key === 'overviewEcoLossesFfa').title, 'Overview & eco losses');
  assert.ok(layouts.ffa.includes('overviewSmallFfa'));
});
test('Overview and Collected already have translations in every shipped locale', () => {
  const dir = new URL('../src/vantage/web/i18n/', import.meta.url);
  for (const name of readdirSync(dir).filter(n => !n.startsWith('_') && n.endsWith('.json'))) {
    const dict = JSON.parse(readFileSync(new URL(name, dir), 'utf8'));
    for (const key of ['Overview', 'Collected', 'Overview & eco losses']) assert.ok(dict[key], `${name}: ${key}`);
  }
});

globalThis.window = { addEventListener() {} };
globalThis.document = { getElementById() { return null; }, addEventListener() {} };
const { migrateSettings } = await import('../src/vantage/web/state.js');
test('a saved removed team-page selection migrates without changing 1v1, FFA or custom pages', () => {
  const before = { settingsVersion: 9, dashboardSelection: { oppositional: 'overviewSmall', nonOppositional: 'overview', ffa: 'overviewSmallFfa' } };
  const after = migrateSettings(before);
  assert.deepEqual(after.dashboardSelection, { oppositional: 'overviewEcoLosses', nonOppositional: 'overview', ffa: 'overviewSmallFfa' });
  const custom = migrateSettings({ settingsVersion: 9, dashboardSelection: { oppositional: 'overviewSmall' }, customDashboardConfig: { oppositional: [{ id: 'overviewSmall', columns: ['vils'] }] } });
  assert.equal(custom.dashboardSelection.oppositional, 'overviewSmall');
});
