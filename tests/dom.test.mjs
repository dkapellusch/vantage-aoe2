import assert from 'node:assert/strict';
import { test } from 'node:test';
import { patchChildren, listDelta } from '../src/vantage/web/dom.js';
import { Element, Text } from './dom_helper.mjs';
const e=(tag,attrs={},children=[])=>new Element(tag,attrs,children);

test('live text updates preserve the same image, text node and button under a held click',()=>{
  const text=new Text('12'),button=e('button',{'data-dash-page':'military'},[text]);
  const image=e('img',{src:'/unit.png'}),root=e('div',{},[image,button]);
  let clicked=0;button.onclick=()=>clicked++;
  patchChildren(root,e('div',{},[e('img',{src:'/unit.png'}),e('button',{'data-dash-page':'military','aria-pressed':'true'},[new Text('13')])]));
  assert.equal(root.childNodes[0],image);assert.equal(root.childNodes[1],button);
  assert.equal(button.firstChild,text);assert.equal(text.nodeValue,'13');button.onclick();assert.equal(clicked,1);
});
test('keyed controls survive insertion, reordering and removal of nearby rows',()=>{
  const a=e('button',{'data-dash-page':'a'}),b=e('button',{'data-dash-page':'b'}),root=e('div',{},[a,b]);
  patchChildren(root,e('div',{},[e('span',{},[new Text('new')]),e('button',{'data-dash-page':'b'}),e('button',{'data-dash-page':'a'})]));
  assert.equal(root.childNodes[1],b);assert.equal(root.childNodes[2],a);
  patchChildren(root,e('div',{},[e('button',{'data-dash-page':'b'})]));
  assert.deepEqual(root.childNodes,[b]);
});
test('open details remain open and SVG nodes retain their identity',()=>{
  const detail=e('details',{'data-panel-detail':'mechanics',open:''}),svg=e('svg',{},[e('path',{d:'M1 1'})]);
  const root=e('div',{},[detail,svg]);
  patchChildren(root,e('div',{},[e('details',{'data-panel-detail':'mechanics'}),e('svg',{},[e('path',{d:'M2 2'})])]));
  assert.equal(root.firstChild,detail);assert.equal(detail.open,true);
  assert.equal(root.childNodes[1],svg);assert.equal(svg.firstChild.getAttribute('d'),'M2 2');
});

test('composition icons keep their images when changing counts reorder unit lines',()=>{
  const a=e('div',{'data-line':'archer','data-pid':'1'},[e('img',{src:'/archer.png'})]);
  const b=e('div',{'data-line':'knight','data-pid':'1'},[e('img',{src:'/knight.png'})]);
  const ai=a.firstChild,bi=b.firstChild,root=e('div',{},[a,b]);
  patchChildren(root,e('div',{},[
    e('div',{'data-line':'knight','data-pid':'1'},[e('img',{src:'/knight.png'})]),
    e('div',{'data-line':'archer','data-pid':'1'},[e('img',{src:'/archer.png'})]),
  ]));
  assert.equal(root.firstChild,b);assert.equal(root.childNodes[1],a);
  assert.equal(a.firstChild,ai);assert.equal(b.firstChild,bi);
});

test('a sliding window of rows is a drop from the front plus an append', () => {
  const [a, b, c, d, f] = [{}, {}, {}, {}, {}];
  assert.deepEqual(listDelta([a, b, c], [a, b, c]), { drop: 0, add: [] });
  assert.deepEqual(listDelta([a, b, c], [a, b, c, d]), { drop: 0, add: [d] });
  assert.deepEqual(listDelta([a, b, c], [c, d, f]), { drop: 2, add: [d, f] });
  assert.deepEqual(listDelta([], [a, b]), { drop: 0, add: [a, b] });
  assert.deepEqual(listDelta([a], []), { drop: 1, add: [] });
  // Not a forward slide (a seek back, a filter change, a reload): rebuild.
  assert.equal(listDelta([b, c], [a, b, c]), null);
  assert.equal(listDelta([a, b, c], [a, c]), null);
  assert.equal(listDelta([a, b], [{}, {}]), null);
});
