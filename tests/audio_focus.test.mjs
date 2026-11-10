import assert from 'node:assert/strict';
import { test } from 'node:test';
import { selectedOwners, eventAllowed, AlertCadence } from '../src/vantage/web/audio-focus.js';

const attack = {kind:'under_attack',player:2};
test('screen alerts ignore off-screen attacks even in all-player perspective', () => {
  assert.equal(eventAllowed('screen',attack,0,new Set(),false),false);
  assert.equal(eventAllowed('screen',attack,0,new Set(),true),true);
});
test('selection audio follows all selected owners, with a current owner after conversion', () => {
  const state={selection:new Set([10,11,12,13]),selectionInfo:new Map([[10,{owner:1}],[11,{owner:2}],[12,{owner:0}],[13,{owner:4}]]),view:{entities:[[10,3]]}};
  assert.deepEqual([...selectedOwners(state)],[3,2,4]);
  assert.equal(eventAllowed('selectedOwners',attack,1,selectedOwners(state),false),true);
  assert.equal(eventAllowed('selectedOwners',attack,2,new Set(),true),false);
});
test('either side of a conversion can make an alert relevant', () => {
  const conversion={kind:'conversion',player:3,from:2};
  for(const owner of [2,3]) {
    assert.equal(eventAllowed('selectedOwners',conversion,0,new Set([owner]),false),true);
    assert.equal(eventAllowed('selectedPlayer',conversion,owner,new Set(),false),true);
  }
  assert.equal(eventAllowed('selectedOwners',conversion,0,new Set([1]),false),false);
});
test('screen-or-owners works with no selection and with mixed owners off screen', () => {
  assert.equal(eventAllowed('screenOrSelectedOwners',attack,0,new Set(),true),true);
  assert.equal(eventAllowed('screenOrSelectedOwners',attack,0,new Set(),false),false);
  assert.equal(eventAllowed('screenOrSelectedOwners',attack,0,new Set([1,2]),false),true);
  assert.equal(eventAllowed('none',attack,0,new Set([2]),true),false);
  assert.equal(eventAllowed('all',attack,1,new Set(),false),true);
});
test('attack and conversion bursts share a wall-clock cooldown at every replay speed', () => {
  const cadence=new AlertCadence();
  assert.equal(cadence.allow(0,3000),true);
  for(const ms of [60,250,1000,2999]) assert.equal(cadence.allow(ms,3000),false);
  assert.equal(cadence.allow(3000,3000),true);
  assert.equal(cadence.allow(3001,0),true);
});
