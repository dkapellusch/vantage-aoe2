import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chooseFight, fightParticipants, FightSelection, highlightParticipants } from '../src/vantage/web/autocast-focus.js';
const ref = (id, owner=1) => ({id,owner,master:4});
const kill = (id,x=20,t=10000) => ({kind:'kill',t,x,y:20,killer:ref(id),victim:ref(id+100,2)});
const row = (id,owner=1,activity=8,x=20) => [id,owner,4,x,20,1,2,0,[],activity];

test('director chooses the recent dense fight, never a future event', () => {
  const events=[kill(1,20),kill(2,22),kill(3,100),kill(4,100,12000)];
  assert.equal(chooseFight(events,10000).x,20);
  assert.equal(chooseFight(events,40000),null);
});
test('attack alerts provide a focus before the first kill', () => {
  const event={kind:'under_attack',t:10000,x:20,y:20,unit:ref(8,2)};
  assert.equal(chooseFight([event],10000),event);
  assert.deepEqual([...fightParticipants(event,[event],[row(5)],10000).keys()],[8,5]);
});
test('fight selection includes both owners, dead victims and healers, excluding bystanders', () => {
  const events=[kill(1),kill(9,100),kill(8,20,12000)];
  const rows=[row(1),row(2,2),row(3,1,15),row(4,1,0),row(5,2,8,100),row(6,0)];
  assert.deepEqual([...fightParticipants(events[0],events,rows,10000).keys()],[1,101,2,3]);
});
test('selection stays stable as a fight moves slightly and reinforcements arrive', () => {
  const selection=new FightSelection(),events=[kill(1)];
  const info=selection.select(events[0],events,[row(1)],10000);
  assert.ok(info.has(101));
  assert.equal(selection.select({...events[0],x:22},events,[row(1),row(3)],14000),null);
  assert.deepEqual([...selection.owned],[1,101]);
});
test('manual selection holds until resumed, including in-place Set changes', () => {
  const control=new FightSelection(),events=[kill(1)];
  control.select(events[0],events,[row(1)],10000);
  const manual=new Set(control.owned);manual.delete(101);control.observe(manual);
  assert.equal(control.enabled,false);
  assert.equal(control.select(kill(5,60),[kill(5,60)],[],20000),null);
  control.resume(manual);
  assert.ok(control.select(kill(5,60),[kill(5,60)],[],20000).has(5));
});
test('a new fight and a rewind refresh the selected participants', () => {
  const control=new FightSelection();
  control.select(kill(1),[kill(1)],[],10000);
  assert.ok(control.select(kill(5,60,14000),[kill(5,60,14000)],[],14000).has(5));
  assert.ok(control.select(kill(6,60,5000),[kill(6,60,5000)],[],5000).has(6));
});

test('hero highlights include the live victim before the blow, with a stable element selection', () => {
  const event=kill(1,20,10000);
  const info=highlightParticipants(ref(1),{kind:'kill',kills:[event]},event,[],[row(1),row(101,2,1)],5000);
  assert.deepEqual([...info.keys()],[1,101]);
  assert.deepEqual(info.get(101),{owner:2,mid:4});
  assert.deepEqual([...highlightParticipants(ref(1),{kind:'birth',kills:[]},event,[],[row(2)],5000).keys()],[1]);
});
