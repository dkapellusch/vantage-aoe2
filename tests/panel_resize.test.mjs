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
const { moveRect, snapRect } = await import('../src/vantage/web/panel-resize.js');
const vp = { width: 1200, height: 800 };
test('a moved panel stays inside the window', () => {
  assert.deepEqual(moveRect(rect, 50, -20, vp), { left: 350, top: 180, width: 400, height: 300 });
  assert.deepEqual(moveRect(rect, 5000, 5000, vp), { left: 792, top: 492, width: 400, height: 300 });
});
test('moving snaps the nearest edge to the window margin and to other panels', () => {
  const near = { left: 13, top: 200, width: 100, height: 100 };
  assert.deepEqual(snapRect(near, [], vp).rect, { left: 8, top: 200, width: 100, height: 100 });
  const other = { left: 500, top: 100, width: 200, height: 150 };
  // Right edge 4 px from the other's left minus the gap: snaps to sit 6 px beside it.
  const beside = snapRect({ left: 300, top: 103, width: 190, height: 80 }, [other], vp);
  assert.deepEqual(beside.rect, { left: 304, top: 100, width: 190, height: 80 });
  assert.deepEqual(beside.guides, [{ axis: 'x', at: 494 }, { axis: 'y', at: 100 }]);
  // Out of reach: unchanged, no guides.
  assert.deepEqual(snapRect({ left: 300, top: 400, width: 100, height: 100 }, [other], vp), { rect: { left: 300, top: 400, width: 100, height: 100 }, guides: [] });
});
test('resizing snaps only the dragged edges', () => {
  const other = { left: 500, top: 100, width: 200, height: 150 };
  const { rect: r } = snapRect({ left: 100, top: 100, width: 393, height: 144 }, [other], vp, 'se');
  assert.deepEqual(r, { left: 100, top: 100, width: 394, height: 150 });
  const { rect: w } = snapRect({ left: 12, top: 300, width: 200, height: 100 }, [], vp, 'nw');
  assert.deepEqual(w, { left: 8, top: 300, width: 204, height: 100 });
});
