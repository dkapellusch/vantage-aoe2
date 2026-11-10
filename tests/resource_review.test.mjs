import assert from 'node:assert/strict';
import { test } from 'node:test';
globalThis.window = { addEventListener() {} };
globalThis.document = { getElementById() { return null; }, addEventListener() {} };
const { resourceTotalsHtml, bonusIncomeHtml } = await import('../src/vantage/web/resource-review.js');

test('worker collected and credited values differ while camps use the full receipt', () => {
  const data = { collected: {gold:10}, credited: {gold:11}, dropped_off: {gold:11}, is_drop_site:true, observed_from_ms:0 };
  const worker = resourceTotalsHtml(data, true);
  assert.match(worker,/Collected/); assert.match(worker,/Credited/);
  assert.match(worker,/>10<\/b>/); assert.match(worker,/>11<\/b>/);
  const camp = resourceTotalsHtml(data, false);
  assert.match(camp,/Delivered/); assert.match(camp,/>11<\/b>/); assert.doesNotMatch(camp,/>10<\/b>/);
  assert.match(resourceTotalsHtml({...data,has_gaps:true},false),/≥/);
  assert.equal(resourceTotalsHtml(null,true),'');
});

test('bonus source view distinguishes regular work, uncertain attribution and unresolved income', () => {
  const html = bonusIncomeHtml([{id:1,name:'Alice <admin>',color:'#f00',income:{total:5,bonus:{gold:5},sources:[
    {source:'villagers',category:'regular',resources:{gold:100},total:100},
    {source:'Relics',category:'bonus',resources:{gold:5},total:5,estimated:false},
    {source:'Unattributed',category:'unattributed',resources:{food:12},total:12,estimated:true},
  ]}}]);
  assert.match(html,/Alice &lt;admin&gt;/); assert.match(html,/Relics/); assert.match(html,/Unattributed/);
  assert.match(html,/Excluded from bonus totals/); assert.doesNotMatch(html,/villagers/);
  assert.match(html,/data-ui-key="income-player-1"/);
});

test('yield and discounts have their own groups and do not inflate income', () => {
  const html=bonusIncomeHtml([{id:1,name:'Maya',color:'#f00',income:{total:5,bonus:{gold:5},sources:[],effects:[
    {source:'Maya resource longevity',category:'yield',resources:{food:15},total:15,estimated:true},
    {source:'Free tech · Horse Collar',category:'savings',resources:{food:75,wood:75},total:150,estimated:true},
  ]}}]);
  assert.match(html,/Extra yield/); assert.match(html,/Saved/); assert.match(html,/Maya resource longevity/);
  assert.match(html,/Free tech/); assert.match(html,/cancelled queues are excluded/);
  assert.match(html,/gathered ×/); assert.match(html,/≈ 5/);
});

test('Khmer handicap is separate and old generic yield claims are suppressed', () => {
  const html=bonusIncomeHtml([{id:6,name:'Khmer',color:'#f0f',income:{total:0,bonus:{},sources:[],effects:[
    {source:'Handicap · 120%',category:'handicap',resources:{food:20,wood:10},total:30,estimated:true},
    {source:'Resource yield',category:'yield',resources:{food:384},total:589,estimated:true},
    {source:'Other resource yield',category:'yield',resources:{food:50},total:50,estimated:true},
  ]}}]);
  assert.match(html,/Handicap/); assert.match(html,/120%/);
  assert.match(html,/recorded lobby handicap/); assert.match(html,/work-speed effects/);
  assert.doesNotMatch(html,/Extra yield|Resource yield|589|384/);
  assert.match(html,/Income.*≈ 0/);
});

test('market received resources and payment are separate from generated income', () => {
  const html=bonusIncomeHtml([{id:1,name:'Portuguese',color:'#f00',income:{total:5,bonus:{gold:5},sources:[],exchanges:[
    {source:'Market sales',category:'exchange',resources:{gold:139},spent:{wood:200},total:139,estimated:false},
    {source:'Market purchases',category:'exchange',resources:{food:100},spent:{gold:146},total:100,estimated:false},
  ]}}]);
  assert.match(html,/Market/); assert.match(html,/Sales/); assert.match(html,/Purchases/);
  assert.match(html,/Paid: 200 wood/); assert.match(html,/Paid: 146 gold/);
  assert.match(html,/excluded from bonus income/); assert.match(html,/Income.*≈ 5/);
  assert.doesNotMatch(html,/Extra yield/);
});

test('small unresolved quantities remain legible and rounded zero rows are omitted', () => {
  const html=bonusIncomeHtml([{id:1,name:'Britons',color:'#00f',income:{total:0,bonus:{},sources:[
    {source:'Unattributed',category:'unattributed',resources:{wood:0.2},total:0.2},
    {source:'Rounded zero',category:'unattributed',resources:{wood:0},total:0},
  ]}}]);
  assert.match(html,/>0\.2<\/td>/); assert.doesNotMatch(html,/Rounded zero/);
});

test('free villager count and value stay separate from stockpile grants and savings', () => {
  const html = bonusIncomeHtml([{id:1,name:'Wei',color:'#00f',income:{total:0,bonus:{},sources:[],effects:[
    {source:'Free villager · Double-Bit Axe',category:'assets',resources:{food:50},total:50,count:1,estimated:true},
  ]}}]);
  assert.match(html,/Free units/); assert.match(html,/Free villager · Double-Bit Axe ×1/);
  assert.match(html,/neutral unit cost, not stockpile income/);
  assert.match(html,/Income.*≈ 0/); assert.doesNotMatch(html,/>Saved/);
});

test('construction grants explain direct stockpile accounting', () => {
  const html = bonusIncomeHtml([{id:1,name:'Saxons',color:'#00f',income:{total:45,bonus:{food:35,stone:10},sources:[
    {source:'Camp construction',category:'bonus',resources:{food:35,stone:10},total:45,estimated:true},
  ]}}]);
  assert.match(html,/Camp construction/); assert.match(html,/building owner’s resource storage/);
  assert.match(html,/separate from villager deliveries/); assert.match(html,/Income.*≈ 45/);
});

test('returned cargo is outside bonus income and market transactions', () => {
  const html = bonusIncomeHtml([{id:2,name:'Portuguese',color:'#f00',income:{total:5,bonus:{wood:5},sources:[],exchanges:[
    {source:'Returned cargo',category:'return',resources:{food:21,wood:78},spent:{},total:99,count:5,estimated:true},
  ]}}]);
  assert.match(html,/Returned/); assert.match(html,/when villagers were deleted/);
  assert.match(html,/Excluded from bonus income/); assert.doesNotMatch(html,/>Market/);
  assert.match(html,/Income.*≈ 5/);
});
