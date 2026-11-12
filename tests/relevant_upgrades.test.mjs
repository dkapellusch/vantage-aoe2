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
    37:{nodes:[],upgrade_relevance_available:true,relevant_upgrades:{38:[757]},upgrade_techs:{757:meta(757,4,0)}},
    999:{nodes:[],upgrade_relevance_available:false},
  };
  const old=globalThis.fetch;
  globalThis.fetch=async url=>({json:async()=>trees[Number(url.match(/techtree\/(\d+)/)[1])]});
  try{
    S.catalog={techs:{},civ_eras:{}};
    S.match={players:{1:{id:1,civ:26},2:{id:2,civ:37},3:{id:3,civ:999}}};
    S.view={players:{1:{age:2,research_done:[67],research_active:[{tech:81,remaining:4}]},2:{age:3}}};
    const row=pid=>[[123,pid,38]];
    assert.match(relevantUpgrades(row(1)),/Loading…/);await new Promise(r=>setImmediate(r));
    const html=relevantUpgrades(row(1));
    assert.deepEqual([...html.matchAll(/data-tech="(\d+)"/g)].map(m=>+m[1]),[209,67,81,435,577]);
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
