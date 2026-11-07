import assert from 'node:assert/strict';
import { test } from 'node:test';
globalThis.window = { addEventListener() {} };
globalThis.document = { getElementById() { return null; }, addEventListener() {} };
const {resizeRect,fitRect}=await import('../src/vantage/web/panel-resize.js');
const rect={left:300,top:200,width:400,height:300},viewport={width:1200,height:800};
test('each corner preserves its opposite corner while resizing',()=>{
  assert.deepEqual(resizeRect(rect,'se',50,30,viewport),{left:300,top:200,width:450,height:330});
  assert.deepEqual(resizeRect(rect,'nw',-50,-30,viewport),{left:250,top:170,width:450,height:330});
  assert.deepEqual(resizeRect(rect,'ne',50,-30,viewport),{left:300,top:170,width:450,height:330});
  assert.deepEqual(resizeRect(rect,'sw',-50,30,viewport),{left:250,top:200,width:450,height:330});
});
test('resize minimum and viewport limits keep handles reachable',()=>{
  assert.deepEqual(resizeRect(rect,'nw',1000,1000,viewport),{left:500,top:420,width:200,height:80});
  assert.deepEqual(resizeRect(rect,'se',2000,2000,viewport),{left:300,top:200,width:892,height:592});
  assert.deepEqual(fitRect({left:1100,top:750,width:600,height:400},viewport),{left:592,top:392,width:600,height:400});
});
test('saved layouts fit a smaller window without losing their original rectangles',()=>{
  const saved={left:1500,top:600,width:900,height:700};
  assert.deepEqual(fitRect(saved,{width:640,height:480}),{left:8,top:8,width:624,height:464});
  assert.equal(saved.width,900);
});
