import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

test('building idle tooltip and population-block activity labels have every locale', () => {
  const source = readFileSync(new URL('../src/vantage/web/panels.js', import.meta.url), 'utf8');
  const detail = source.match(/const TC_IDLE_TIP = '([^']+)';/)[1];
  assert.match(detail, /neither training nor researching/);
  assert.match(detail, /housed time is separate/);
  const names = JSON.parse(source.match(/const ACT_NAMES = (\[[^;]+\]);/)[1].replaceAll("'", '"'));
  assert.equal(names[16], 'Housed');
  assert.equal(names[17], 'Population limit');
  const dir = new URL('../src/vantage/web/i18n/', import.meta.url);
  for (const name of readdirSync(dir).filter(n => !n.startsWith('_') && n.endsWith('.json'))) {
    const dict = JSON.parse(readFileSync(new URL(name, dir), 'utf8'));
    for (const key of [detail, 'Housed', 'Population limit']) assert.ok(dict[key], `${name}: ${key}`);
  }
});
