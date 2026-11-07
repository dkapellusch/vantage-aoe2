// Execute pure functions extracted from actual app.js; no browser or app startup.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, parse } from 'node:path';
import { fileURLToPath } from 'node:url';

// Works both here in the artifact and after copying this file into repo/tests.
let root = dirname(fileURLToPath(import.meta.url));
while (!existsSync(join(root, 'src/vantage/web/app.js'))) {
  assert.notEqual(root, parse(root).root, 'repository source root not found');
  root = dirname(root);
}
const actualPath = process.argv[2] || join(root, 'src/vantage/web/app.js');
const proposed = readFileSync(actualPath, 'utf8');
const extract = (text, name, next) => text.slice(text.indexOf(`function ${name}`), text.indexOf(next, text.indexOf(`function ${name}`)));
const report = extract(proposed, 'reportPlaybackEnd(live)', '\nfunction gameOver(live)');
const gameOver = extract(proposed, 'gameOver(live)', '\nconst GFX_HOLD_MS');
const evaluate = new Function('S', 'source', 'performance', 'gameOverCheckAt', `${gameOver}\nreturn gameOver(false);`);
assert.equal(evaluate({ complete: true, view: { game_ended: false } }), false);
assert.equal(evaluate({ complete: false, view: { game_ended: true } }), true);
assert.equal(evaluate({ complete: true, view: null }), false);
const playback = new Function('S', 'serverConfig', 'live', `
  let playbackEndedSent = false, calls = 0;
  const api = () => { calls++; return Promise.resolve(); };
  ${report}
  reportPlaybackEnd(live); reportPlaybackEnd(live);
  return calls;
`);
assert.equal(playback({ complete: true, view: { game_ended: false } }, { exit_on_stream_end: true }, false), 1);
assert.equal(playback({ complete: false }, { exit_on_stream_end: true }, false), 0);
assert.equal(playback({ complete: true }, { exit_on_stream_end: true }, true), 0);
assert.equal(playback({ complete: true }, { exit_on_stream_end: false }, false), 0);
console.log(JSON.stringify({ pure_function_cases: 7, ingestion_does_not_imply_game_over: true, playback_end_file_completion_semantics_preserved: true }));
// Status presentation must not hide cancellation/failure behind a stale phase.
const status = extract(proposed, 'statusText(desc)', '\n// -- starting the game');
const describe = new Function('desc', 't', `${status}\nreturn statusText(desc);`);
assert.equal(describe({ mode: 'native_replay', source: { status: 'converting', phase: 'loading' } }, x => x), 'Loading replay…');
assert.equal(describe({ mode: 'native_replay', source: { status: 'cancelled', phase: 'loading' } }, x => x), 'Replay conversion cancelled');
assert.equal(describe({ mode: 'native_replay', source: { status: 'failed', phase: 'loading' } }, x => x), 'Replay conversion failed');
// Both user/event launch and polling return before API access when configured.
for (const [name, next] of [['pollLaunch()', '\nasync function startGame'], ['startGame()', '\n// "{map}']]) {
  const code = proposed.slice(proposed.indexOf(`async function ${name}`), proposed.indexOf(next, proposed.indexOf(`async function ${name}`)));
  const run = new Function('serverConfig', 'api', `return (async () => { ${code}\n await ${name}; })();`);
  await run({ native_replays: true }, () => assert.fail('game API request'));
}
console.log(JSON.stringify({ additional_status_cases: 3, configured_launch_and_poll_guard_cases: 2 }));
