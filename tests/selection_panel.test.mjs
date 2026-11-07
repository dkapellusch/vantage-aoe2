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
test('selection or game changes reset inspection state even with identical markup', () => {
  const el = panel(), html = markup(1,'mechanics');
  setSelectionHtml(el,html,'1:42'); el.details[0].open=true; el.scrollTop=60;
  setSelectionHtml(el,html,'1:43'); assert.equal(el.details[0].open,false); assert.equal(el.scrollTop,0);
  el.details[0].open=true;
  setSelectionHtml(el,html,'2:43'); assert.equal(el.details[0].open,false);
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
