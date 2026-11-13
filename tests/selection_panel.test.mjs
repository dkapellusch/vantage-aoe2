import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setSelectionHtml } from '../src/vantage/web/selection-panel.js';
import { Element } from './dom_helper.mjs';

// Parsing creates fresh nodes; rendering must preserve the existing ones.
function panel() {
  return new Element();
}
const markup = (revision, ...keys) => JSON.stringify({revision,keys});

test('expanded building details, scroll position and keyboard focus survive a production refresh', () => {
  const el = panel();
  setSelectionHtml(el, markup(1,'mechanics'), '1:castle42');
  const original = el.details[0]; original.open = true;
  el.scrollTop = 75; original.summary.focus();
  setSelectionHtml(el, markup(2,'mechanics'), '1:castle42');
  assert.equal(el.details[0], original);
  assert.equal(el.details[0].open,true); assert.equal(el.scrollTop,75);
  assert.equal(el.ownerDocument.activeElement,el.details[0].summary);
});
test('explicitly closing a section stays closed across refreshes', () => {
  const el = panel(); setSelectionHtml(el,markup(1,'mechanics'),'1:42');
  el.details[0].open=true; setSelectionHtml(el,markup(2,'mechanics'),'1:42');
  el.details[0].open=false; setSelectionHtml(el,markup(3,'mechanics'),'1:42');
  assert.equal(el.details[0].open,false);
});
test('mixed-owner sections retain their own state when their order changes', () => {
  const el = panel(); setSelectionHtml(el,markup(1,'owner-1-units','owner-2-units'),'1:42,43');
  el.details[0].open=true;
  setSelectionHtml(el,markup(2,'owner-2-units','owner-1-units'),'1:42,43');
  assert.deepEqual(el.details.map(d=>d.open),[false,true]);
});
test('an opened section stays open when another object is selected; scroll starts at the top', () => {
  const el = panel(), html = markup(1,'mechanics');
  setSelectionHtml(el,html,'1:42'); el.details[0].open=true; el.scrollTop=60;
  setSelectionHtml(el,html,'1:43'); assert.equal(el.details[0].open,true); assert.equal(el.scrollTop,0);
  setSelectionHtml(el,html,'2:44'); assert.equal(el.details[0].open,true);
});
test('a section toggled just before the selection changes is remembered', () => {
  const el = panel(), html = markup(1,'mechanics');
  setSelectionHtml(el,html,'1:42'); el.details[0].open=true;
  setSelectionHtml(el,html,'1:43'); el.details[0].open=false;
  setSelectionHtml(el,html,'1:44'); assert.equal(el.details[0].open,false);
});
test('the Details section is one setting across economic and military objects', () => {
  const el = panel();
  setSelectionHtml(el,markup(1,'mechanics'),'1:villager'); el.details[0].open=true;
  setSelectionHtml(el,markup(1,'activity'),'1:knight'); assert.equal(el.details[0].open,true);
  el.details[0].open=false;
  setSelectionHtml(el,markup(1,'mechanics'),'1:villager2'); assert.equal(el.details[0].open,false);
});
test('temporarily missing sections can return without losing the user’s open state', () => {
  const el = panel(); setSelectionHtml(el,markup(1,'activity'),'1:42'); el.details[0].open=true;
  setSelectionHtml(el,markup(2),'1:42'); setSelectionHtml(el,markup(3,'activity'),'1:42');
  assert.equal(el.details[0].open,true);
});

test('finishing an inline edit restores markup even when its source is unchanged', () => {
  const el=panel(),html=markup(1,'mechanics');setSelectionHtml(el,html,'1:42');
  const detail=el.details[0];detail.open=true;
  el.firstChild.nodeValue='inline editor';el._html=null;
  setSelectionHtml(el,html,'1:42');
  assert.equal(el.firstChild.nodeValue,'1');assert.equal(el.details[0],detail);assert.equal(detail.open,true);
});

test('open sections are one choice for every selection, kept in the store given', async () => {
  const { sectionKey } = await import('../src/vantage/web/selection-panel.js');
  assert.equal(sectionKey('mechanics'), 'details'); assert.equal(sectionKey('activity'), 'details');
  assert.equal(sectionKey('owner-1-units'), 'group-units'); assert.equal(sectionKey('owner-1-2-lifetime'), 'group-lifetime');
  assert.equal(sectionKey('farm-grants'), 'farm-grants');
  const saved = new Map(), writes = [];
  const store = { get: (k) => saved.get(k), set: (k, v) => { saved.set(k, v); writes.push([k, v]); } };
  const el = panel();
  setSelectionHtml(el, markup(1, 'mechanics'), '1:villager', store);
  assert.equal(el.details[0].open, false); assert.deepEqual(writes, [], 'showing a panel writes nothing');
  el.details[0].open = true;
  setSelectionHtml(el, markup(2, 'mechanics'), '1:villager', store);
  assert.deepEqual(writes, [['details', true]]);
  // A building, a military unit, a farm: Details is open; a section never touched stays as authored.
  setSelectionHtml(el, markup(1, 'activity', 'farm-grants'), '1:knight', store);
  assert.deepEqual(el.details.map((d) => d.open), [true, false]);
  // A group of one owner opens its units; the next group, of another owner, shows them too.
  setSelectionHtml(el, markup(1, 'owner-1-units'), '1:a,b', store);
  el.details[0].open = true;
  setSelectionHtml(el, markup(1, 'owner-2-units'), '1:c,d', store);
  assert.equal(el.details[0].open, true); assert.equal(saved.get('group-units'), true);
  // Closing is remembered the same way.
  setSelectionHtml(el, markup(1, 'mechanics'), '1:tc', store);
  el.details[0].open = false;
  setSelectionHtml(el, markup(1, 'activity'), '1:scout', store);
  assert.equal(el.details[0].open, false); assert.equal(saved.get('details'), false);
});

test('a reload starts from the stored sections: a new panel element reads the same store', () => {
  const saved = new Map([['details', true]]);
  const store = { get: (k) => saved.get(k), set: (k, v) => saved.set(k, v) };
  const el = panel();
  setSelectionHtml(el, markup(1, 'mechanics'), '1:42', store);
  assert.equal(el.details[0].open, true);
});

test('a reset closes what is on screen and starts again from the store', async () => {
  const { forgetSelectionState } = await import('../src/vantage/web/selection-panel.js');
  const saved = new Map();
  const store = { get: (k) => saved.get(k), set: (k, v) => saved.set(k, v) };
  const el = panel();
  setSelectionHtml(el, markup(1, 'mechanics'), '1:42', store);
  el.details[0].open = true;
  setSelectionHtml(el, markup(2, 'mechanics'), '1:42', store);
  assert.equal(saved.get('details'), true);
  saved.clear(); forgetSelectionState(el);
  setSelectionHtml(el, markup(2, 'mechanics'), '1:42', store);
  assert.equal(el.details[0].open, false);
  assert.equal(saved.has('details'), false, 'closing them for the reset is not the viewer\'s choice');
});
