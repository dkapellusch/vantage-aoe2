import assert from 'node:assert/strict';
import { test } from 'node:test';
import { basename } from 'node:path';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { ESLint } from 'eslint';

const lint = new ESLint({ cwd: fileURLToPath(new URL('..', import.meta.url)) });

test('all browser modules have no undefined names', async () => {
  const results = await lint.lintFiles(['src/vantage/web/*.js']);
  const files = readdirSync(new URL('../src/vantage/web/', import.meta.url)).filter((f) => f.endsWith('.js'));
  assert.equal(results.length, files.length, 'lint every browser module');
  assert.ok(results.some((r) => basename(r.filePath) === 'world.js'));
  const errors = results.reduce((n, r) => n + r.errorCount, 0);
  const formatter = await lint.loadFormatter('stylish');
  assert.equal(errors, 0, formatter.format(results));
});

test('no-undef catches the missing drawSprites counter even in an unexecuted branch', async () => {
  const [result] = await lint.lintText(
    'function drawSprites() { let drew = false; if (!drew && !failed) return; }',
    { filePath: 'src/vantage/web/world.js' },
  );
  assert.equal(result.errorCount, 1);
  assert.equal(result.messages[0].ruleId, 'no-undef');
  assert.match(result.messages[0].message, /failed.*not defined/);
});
