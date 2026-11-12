import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.window = { addEventListener() {} };
globalThis.document = { getElementById() { return null; }, addEventListener() {} };
const { farmReviewHtml } = await import('../src/vantage/web/farm-review.js');
const { bonusIncomeHtml } = await import('../src/vantage/web/resource-review.js');

test('farm shows recorded capacities, research times, age and inspectable workers, without invented remaining food', () => {
  const html = farmReviewHtml({ farm: {capacity:375,capacity_at_build:250,age_ms:1500,auto_reseed:true,
    upgrades:[{tech:14,done:true,researched_ms:1300503},{tech:13,done:false}],grants:[]}},
    {techName:id=>id===14?'Horse Collar':'Heavy Plow',farmers:[123]});
  assert.match(html,/Food remaining.*Not recorded/s);
  assert.match(html,/New farm capacity.*375 food/s);
  assert.match(html,/Capacity when built.*250 food/s);
  assert.match(html,/Horse Collar.*21:40/s);
  assert.match(html,/Heavy Plow.*Not yet/s);
  assert.match(html,/data-inspect="123"/);
  assert.doesNotMatch(html,/undefined|NaN/);
});

test('Folwark shows exact decimals and overlapping-range uncertainty without duplicate grant attribution', () => {
  const html = farmReviewHtml({folwark:{food:492.5,farms:18,shared_food:37.5,next_food:55,reach:4,
    grants:[{time:1000,farm:7,food:37.5,folwarks:[1,2]}]}});
  assert.match(html,/Granted food.*492\.5/s);
  assert.match(html,/Farms triggered.*18/s);
  assert.match(html,/attribution unknown.*37\.5/s);
  assert.match(html,/Farm #7/);
  assert.match(html,/separate from gathering and collection rates/);
  const income = bonusIncomeHtml([{id:2,name:'Poles',color:'#f00',income:{sources:[
    {source:'Poles Folwark bonus food',category:'bonus',resources:{food:942.5},total:942.5}],total:942.5}}]);
  assert.match(income,/>942\.5<\/td>/);
  assert.match(income,/Excluded from gathered food and collection rates/);
  assert.equal(farmReviewHtml({}), '');
});
