import assert from 'node:assert/strict';
import { test } from 'node:test';
globalThis.window = { addEventListener() {}, dispatchEvent() {} };
globalThis.document = { getElementById() { return null; }, addEventListener() {} };
const { S } = await import('../src/vantage/web/state.js');
const { applyGame } = await import('../src/vantage/web/games.js');
const { ownerIdentity, performanceCells, militaryQuery, healingCells } = await import('../src/vantage/web/player-review.js');
const { captureMoment, restoreMoment, parseReviewTime, intervalDelta } = await import('../src/vantage/web/review-workspace.js');
applyGame('aoe2');

test('healing has a compact HP and replacement-value card with resource breakdown', () => {
  const html = healingCells({healer_count:1,hp:60,value:67.5,known_value:67.5,
    resources:{food:30,wood:0,gold:37.5,stone:0},unpriced_hp:0});
  assert.match(html,/HP healed/); assert.match(html,/Restored value/);
  assert.match(html,/30 food/); assert.match(html,/37.5 gold/);
  assert.match(html,/not resources added to the stockpile/);
  assert.match(html,/data-ui-key="healing-performance"/);
  assert.equal(healingCells({healer_count:0}), '');
  assert.match(healingCells({healer_count:1,hp:10,value:null,known_value:0,
    unpriced_hp:10,partial:true}),/≥0\+\?/);
});

test('military windows are canonical and follow replay time including rewinds', () => {
  S.start = 100; S.t = 120000; S.view = { time: 100000 }; S.reviewScope = 'minute';
  assert.equal(militaryQuery([3, 1, 3, -2]).url, '/api/group?ids=1,3&t=100000&since=40000');
  S.reviewRange = { from: 50000, to: 80000 }; S.reviewScope = 'fight';
  assert.deepEqual(militaryQuery([1]), { ids: [1], end: 80000, since: 50000, url: '/api/group?ids=1&t=80000&since=50000' });
  S.view.time = 30000;
  assert.equal(militaryQuery([1]).url, '/api/group?ids=1&t=30000&since=30000');
  S.reviewScope = 'life'; assert.equal(militaryQuery([1]).url, '/api/group?ids=1&t=30000');
});
test('owner header follows the owner age in the displayed snapshot', () => {
  S.match = { players: { 1: { id: 1, name: 'Alice', civ: 1, civ_name: 'Britons', color: '#2244ff', color_id: 0 } } };
  S.view = { players: { 1: { age: 2 } } };
  assert.match(ownerIdentity(1), /Alice/); assert.match(ownerIdentity(1), /Britons/);
  assert.match(ownerIdentity(1), /Castle/);
  S.view.players[1].age = 0; assert.match(ownerIdentity(1), /Dark/); assert.doesNotMatch(ownerIdentity(1), /Castle/);
});
test('unknown destruction is explicit and summed unit idle differs from forced villager time', () => {
  const html = performanceCells({ totals: { kills: 7, deaths: 2 }, destroyed_value: null, destroyed_known_value: 135,
    destroyed_unknown: 1, resources_destroyed: { food: 60, gold: 75 }, activity_scope: { idle: 120 }, forced_idle_seconds: 90 }, true);
  assert.match(html, /135\+\?/); assert.match(html, /Idle · unit·min/); assert.match(html, /≈1.5/);
  assert.match(html, /directly attacked workers/); assert.match(html, /2.0/);
  assert.doesNotMatch(performanceCells(null, false), />0<\/b>/);
});
test('review moments freeze selection, camera and interval and restore through seek', () => {
  S.t = 70000; S.camera = { x: 20, y: 30, zoom: 1.5 }; S.perspective = 1; S.fogMode = 'standard';
  S.selection = new Set([8, 9]); S.reviewRange = { from: 60000, to: 80000 };
  const moment = captureMoment(' Raid ', ' two workers ');
  S.selection.add(10); S.camera.x = 50; S.reviewRange.from = 0;
  assert.deepEqual(moment.selection, [8, 9]); assert.equal(moment.camera.x, 20); assert.equal(moment.range.from, 60000);
  let sought; restoreMoment(moment, (at) => { sought = at; });
  assert.equal(sought, 70000); assert.equal(S.camera.x, 20); assert.equal(S.playing, false);
  assert.equal(S.reviewScope, 'fight'); assert.deepEqual([...S.selection], [8, 9]); assert.equal(moment.name, 'Raid');
});
test('investigation parses time and measures only numeric changes inside interval', () => {
  assert.equal(parseReviewTime('1:02:03'), 3723000); assert.equal(parseReviewTime('18:30'), 1110000);
  for (const value of ['', '-1', 'x', '2.5', '1:2:3:4']) assert.equal(parseReviewTime(value), null);
  S.series = { 1: [{ t: 0, kills: 0 }, { t: 1000, kills: 2 }, { t: 3000, kills: 5 }] };
  assert.equal(intervalDelta(1, 'kills', 1000, 4000), 3);
  assert.equal(intervalDelta(1, 'absent', 1000, 4000), null);
});

test('slim status distinguishes source reconnection, usable buffer and omniscient statistics', async () => {
  const { reviewStatusHtml } = await import('../src/vantage/web/review-workspace.js');
  S.session = { mode:'live', live_connected:false }; S.t = 1200000; S.end = 2400000;
  S.playing = false; S.perspective = 1; S.fogMode = 'standard';
  const html = reviewStatusHtml('Free');
  assert.match(html, /Reconnecting/); assert.match(html, /20:00 \/ 40:00/);
  assert.match(html, /Alice · standard/); assert.match(html, /All-player stats/);
});

test('older running backends expose available idle data and an explicit restart message', () => {
  const old = {totals:{kills:8,deaths:2},activity:{idle:90},activity_lm:{idle:15}};
  const life = performanceCells(old,false,'life');
  assert.match(life,/Restart Vantage/); assert.match(life,/>1:30<\/b>/); assert.match(life,/>8<\/b>/);
  const minute = performanceCells(old,false,'minute');
  assert.match(minute,/>0:15<\/b>/); assert.doesNotMatch(minute,/>8<\/b>/);
  const fight = performanceCells(old,false,'fight');
  assert.doesNotMatch(fight,/>1:30<\/b>/); assert.doesNotMatch(fight,/>8<\/b>/);
  const current = performanceCells({...old,since_ms:null,destroyed_value:0,forced_idle_seconds:0,activity_scope:{idle:90}},false);
  assert.doesNotMatch(current,/Restart Vantage/);
});

test('military refresh retains resolved numbers without leaking across scopes, selections or rewinds', async () => {
  const {militaryResults}=await import('../src/vantage/web/player-review.js');
  const original=globalThis.fetch, requests=[];
  globalThis.fetch=()=>new Promise(resolve=>requests.push(data=>resolve({ok:true,json:async()=>data})));
  try {
    S.session={generation:555};S.start=0;S.view={time:10000};S.reviewScope='life';S.reviewRange=null;S.playing=false;S.seekVersion=0;
    assert.equal(militaryResults([42]),null);
    const first={generation:555,as_of_ms:10000,totals:{kills:3}};
    requests.shift()(first);await new Promise(resolve=>setImmediate(resolve));
    S.view.time=12000;assert.equal(militaryResults([42]),first);
    const second={generation:555,as_of_ms:12000,totals:{kills:4}};
    requests.shift()(second);await new Promise(resolve=>setImmediate(resolve));
    assert.equal(militaryResults([42]),second);
    S.view.time=30000;S.playing=true;assert.equal(militaryResults([42]),second);
    S.seekVersion++;assert.equal(militaryResults([42]),null);S.seekVersion--;S.playing=false;
    S.view.time=11000;assert.equal(militaryResults([42]),null);
    S.reviewScope='minute';assert.equal(militaryResults([42]),null);
    S.reviewScope='life';assert.equal(militaryResults([43]),null);
    S.session={generation:556};assert.equal(militaryResults([42]),null);
  } finally {globalThis.fetch=original;}
});
