import assert from 'node:assert/strict';
import { test } from 'node:test';
const canvas={getContext:()=>new Proxy({},{get:()=>()=>{}}),style:{},addEventListener(){}};
globalThis.document={getElementById:()=>canvas,createElement:()=>canvas,addEventListener(){}};
globalThis.window={addEventListener(){},devicePixelRatio:1};
const {S}=await import('../src/vantage/web/state.js');
const {applyGame}=await import('../src/vantage/web/games.js');
const {relevantUpgrades}=await import('../src/vantage/web/panels.js');
applyGame('aoe2');

test('real chip renderer uses effect IDs, orders groups, preserves statuses and gates by owner',async()=>{
  const meta=(id,category,rank,age=1,line_units=[])=>({id,name:`Upgrade ${id}`,icon:1,status:'available',age,order:[category,rank],line_units});
  const trees={
    26:{nodes:[],upgrade_relevance_available:true,relevant_upgrades:{38:[577,435,81,67,209]},upgrade_techs:{
      209:meta(209,3,100,3,[38]),67:meta(67,1,0),81:meta(81,2,0),435:meta(435,3,0,4),577:meta(577,4,0)},
      layout:{rows:[{groups:[{stages:[{tech:999,status:'available'}]}]}]}},
    37:{nodes:[],upgrade_relevance_available:true,relevant_upgrades:{38:[757],39:[1001,1002]},upgrade_techs:{757:meta(757,4,0),1001:{...meta(1001,3,0),status:"struck"},1002:{...meta(1002,4,0),status:"unavailable"}}},
    999:{nodes:[],upgrade_relevance_available:false},
  };
  const old=globalThis.fetch;
  globalThis.fetch=async url=>({json:async()=>trees[Number(url.match(/techtree\/(\d+)/)[1])]});
  try{
    S.catalog={techs:{},civ_eras:{}};
    S.match={players:{1:{id:1,civ:26},2:{id:2,civ:37},3:{id:3,civ:999}}};
    S.view={players:{1:{age:2,research_done:[67],research_active:[{tech:81,remaining:4,progress:.4}]},2:{age:3}}};
    const row=pid=>[[123,pid,38]];
    assert.match(relevantUpgrades(row(1)),/Loading…/);await new Promise(r=>setImmediate(r));
    const html=relevantUpgrades(row(1));
    assert.deepEqual([...html.matchAll(/data-tech="(\d+)"/g)].map(m=>+m[1]),[67,81,209,435,577]);
    assert.match(html,/data-upgrades-visible>.*data-tech="67".*data-tech="81"/);
    assert.match(html,/id="relevant-upgrades-overflow-1" hidden>.*data-tech="209".*data-tech="435".*data-tech="577"/);
    assert.match(html,/type="button" data-upgrades-toggle data-upgrades-count="3" aria-expanded="false" aria-controls="relevant-upgrades-overflow-1"/);
    assert.match(html,/>\+3 more<\/button>/);
    assert.match(html,/progress.*value="0.4"/);
    assert.doesNotMatch(html,/None researched yet/);
    assert.match(html,/review-upgrade done" data-tech="67"/);
    assert.match(html,/review-upgrade doing" data-tech="81"/);
    assert.match(html,/review-upgrade later" data-tech="435"/);
    assert.match(html,/review-upgrade available" data-tech="577"/);
    assert.doesNotMatch(html,/999/);
    relevantUpgrades(row(2));await new Promise(r=>setImmediate(r));
    assert.match(relevantUpgrades(row(2)),/data-tech="757"/);
    assert.doesNotMatch(relevantUpgrades(row(2)),/data-tech="577"/);
    relevantUpgrades(row(3));await new Promise(r=>setImmediate(r));
    assert.match(relevantUpgrades(row(3)),/Relevant upgrades unavailable/);
  } finally {globalThis.fetch=old;}
});


test('a server with no game art keeps metadata but overrides saved graphics preferences',async()=>{
  const {applyServerConfig,settings}=await import('../src/vantage/web/state.js');
  const {spritesOn}=await import('../src/vantage/web/world.js');
  const oldZoom=S.camera.zoom,oldGraphics=settings.gameGraphics;S.camera.zoom=1;
  applyServerConfig({game_art:false,patch:{gameGraphics:true}});
  assert.equal(spritesOn(),false);
  const text=relevantUpgrades([[123,1,38]]);
  assert.match(text,/review-upgrade-name/);assert.match(text,/Upgrade 209/);
  assert.doesNotMatch(text,/<img/);
  applyServerConfig({game_art:true});assert.equal(spritesOn(),true);
  S.camera.zoom=oldZoom;settings.gameGraphics=oldGraphics;
});


test('unresearched selections have a message, counted overflow and no empty visible row',()=>{
  const html=relevantUpgrades([[1,2,38],[2,2,38]]);
  assert.match(html,/None researched yet/);
  assert.match(html,/>\+1 more<\/button>/);
  assert.doesNotMatch(html,/data-upgrades-visible/);
  assert.equal([...html.matchAll(/data-tech="757"/g)].length,1);
  assert.match(html,/Full tree/);
  const owner1=relevantUpgrades([[1,1,38],[2,1,38]]);
  assert.match(owner1,/aria-controls="relevant-upgrades-overflow-1"/);
  assert.match(html,/aria-controls="relevant-upgrades-overflow-2"/);
});

test('overflow preference defaults collapsed and persists both directions, surviving blocked storage',async()=>{
  const {readUpgradeOverflow,writeUpgradeOverflow}=await import('../src/vantage/web/upgrade-overflow.js');
  const descriptor=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  const store=new Map();
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:k=>store.get(k)??null,setItem:(k,v)=>store.set(k,v)}});
  try {
    assert.equal(readUpgradeOverflow(),false);
    writeUpgradeOverflow(true);assert.equal(readUpgradeOverflow(),true);
    writeUpgradeOverflow(false);assert.equal(readUpgradeOverflow(),false);
    store.set('vantage.relevantUpgrades.expanded','garbage');assert.equal(readUpgradeOverflow(),false);
    Object.defineProperty(globalThis,'localStorage',{configurable:true,get(){throw Error('blocked');}});
    assert.equal(readUpgradeOverflow(),false);assert.doesNotThrow(()=>writeUpgradeOverflow(true));
    Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>null,setItem(){throw Error('full');}}});
    assert.doesNotThrow(()=>writeUpgradeOverflow(false));
  } finally {
    if(descriptor) Object.defineProperty(globalThis,'localStorage',descriptor);
    else delete globalThis.localStorage;
  }
});


test('relevant struck and unavailable entries stay in the collapsed overflow',()=>{
  const html=relevantUpgrades([[1,2,39]]);
  assert.match(html,/>\+2 more<\/button>/);
  assert.match(html,/id="relevant-upgrades-overflow-2" hidden>/);
  assert.match(html,/unavailable" data-tech="1001"[^>]* disabled/);
  assert.match(html,/unavailable" data-tech="1002"[^>]* disabled/);
  assert.doesNotMatch(html,/data-upgrades-visible/);
});

test('an entirely researched set needs neither an empty message nor overflow control',()=>{
  S.view.players[2].research_done=[757];
  const html=relevantUpgrades([[1,2,38]]);
  assert.match(html,/done" data-tech="757"/);
  assert.doesNotMatch(html,/data-upgrades-toggle|None researched yet|review-upgrade-overflow/);
  S.view.players[2].research_done=[];
});
