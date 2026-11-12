import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.window = {addEventListener() {}};
globalThis.document = {addEventListener() {}};
const {tcIdleTooltip} = await import('../src/vantage/web/tc-idle.js');
const {DASH_HISTORY} = await import('../src/vantage/web/player-review.js');

test('real replay tooltip totals, definition and cutoff use shared server metadata', () => {
  for (const [whole, cutoff, time] of [[725,1912558,'31:52'],[1193,2118080,'35:18'],[43,null,'22:48']]) {
    const tip = tcIdleTooltip({tc_idle_whole_seconds:whole,tc_idle_growth:{
      villager_target:120,cutoff_ms:cutoff,reason:cutoff?'villagers':null,through_ms:cutoff??1368499}});
    assert.match(tip,/at least one completed TC neither training nor researching/);
    assert.match(tip,/first reaches 120 living villagers or the match population limit/);
    assert.match(tip,/Overlapping idle TCs count once/);
    assert.ok(tip.includes(time));
    assert.ok(tip.includes({725:'12:05',1193:'19:53',43:'0:43'}[whole]));
    assert.match(tip,cutoff?/Cutoff:/ : /Cutoff not reached/);
  }
});
test('custom target and population-limit reason are displayed without a fixed 120', () => {
  const tip=tcIdleTooltip({tc_idle_growth:{villager_target:100,cutoff_ms:300000,reason:'population'}});
  assert.match(tip,/100 living villagers/);assert.match(tip,/Cutoff: 5:00 \(Match population limit\)/);
  assert.doesNotMatch(tip,/120/);
  for(const col of ['tcIdle','idleTcHoused','t90TcIdle']) assert.equal(DASH_HISTORY[col],'tc_idle');
});
