import assert from 'node:assert/strict';
import { test } from 'node:test';

test('a full GPU atlas flushes queued sprites without dropping masks, clearing earlier draws or losing outlines', async () => {
  const trace=[], constants=new Map(); let constant=0;
  const calls={
    getShaderParameter:()=>true, getProgramParameter:()=>true,
    createShader:()=>({}), createProgram:()=>({}), createBuffer:()=>({}),
    createVertexArray:()=>({}), createTexture:()=>({}), createSampler:()=>({}), createFramebuffer:()=>({}),
    getUniformLocation:(_program,name)=>name,
    clear:()=>trace.push(['clear']), clearBufferfv:()=>trace.push(['clearTarget']),
    texSubImage3D:()=>trace.push(['upload']),
    drawArraysInstanced:(_mode,_first,_vertices,count)=>trace.push(['batch',count]),
    drawArrays:()=>trace.push(['outline']),
  };
  const gl=new Proxy(calls,{get:(target,key)=>{
    if(key in target)return target[key];
    if(/^[A-Z_0-9]+$/.test(key)) { if(!constants.has(key))constants.set(key,++constant);return constants.get(key); }
    return ()=>{};
  }});
  const original=globalThis.document;
  globalThis.document={createElement:()=>({getContext:()=>gl,classList:{add(){}},addEventListener(){}})};
  try {
    const gpu=await import('../src/vantage/web/sprite-gl.js?atlas-pressure-test');
    const look={outline:1};
    gpu.setAtlasBudget(256); // sixteen 2048² layers: the atlas grows to them, then must flush
    assert.equal(gpu.begin(800,600,1,look),true);
    // Each mask-bearing frame fills one of the sixteen atlas layers. The
    // seventeenth must be drawn after the first batch releases its references.
    for(let i=0;i<17;i++) {
      assert.equal(gpu.draw({width:2046,height:2044},0,2046,1022,0,0,100,50,1,false,
        i%2?gpu.ROLE_OCCLUDER:gpu.ROLE_OUTLINED,0,0xff0000,1022),true);
    }
    gpu.present(look);
    assert.equal(gpu.stats.full,0); assert.equal(gpu.stats.flushes,1);
    assert.equal(gpu.stats.instances,17);
    assert.deepEqual(trace.filter(x=>x[0]==='batch').map(x=>x[1]),[16,16,16,1,1,1]);
    assert.equal(trace.filter(x=>x[0]==='clear').length,1);
    assert.equal(trace.filter(x=>x[0]==='clearTarget').length,3);
    assert.equal(trace.filter(x=>x[0]==='outline').length,1);
    assert.ok(trace.findIndex(x=>x[0]==='batch') < trace.findLastIndex(x=>x[0]==='upload'));
  } finally {
    if(original===undefined)delete globalThis.document;else globalThis.document=original;
  }
});

test('a full atlas under its budget grows on the GPU (layers copied across) instead of flushing', async () => {
  const trace=[], constants=new Map(); let constant=0, textures=0;
  const calls={
    getShaderParameter:()=>true, getProgramParameter:()=>true,
    createShader:()=>({}), createProgram:()=>({}), createBuffer:()=>({}),
    createVertexArray:()=>({}), createTexture:()=>({id:++textures}), createSampler:()=>({}), createFramebuffer:()=>({}),
    getUniformLocation:(_program,name)=>name, getError:()=>0,
    texStorage3D:(_t,_l,_f,_w,_h,depth)=>trace.push(['storage',depth]),
    copyTexSubImage3D:(_t,_l,_x,_y,layer)=>trace.push(['copy',layer]),
    deleteTexture:()=>trace.push(['delete']),
    texSubImage3D:()=>trace.push(['upload']),
    drawArraysInstanced:(_mode,_first,_vertices,count)=>trace.push(['batch',count]),
  };
  const gl=new Proxy(calls,{get:(target,key)=>{
    if(key in target)return target[key];
    if(/^[A-Z_0-9]+$/.test(key)) { if(!constants.has(key))constants.set(key,++constant);return constants.get(key); }
    return ()=>{};
  }});
  const original=globalThis.document;
  globalThis.document={createElement:()=>({getContext:()=>gl,classList:{add(){}},addEventListener(){}})};
  try {
    const gpu=await import('../src/vantage/web/sprite-gl.js?atlas-growth-test');
    gpu.setAtlasBudget(512); // up to 32 layers
    assert.equal(gpu.begin(800,600,1,{}),true);
    for(let i=0;i<9;i++) assert.equal(gpu.draw({width:2046,height:2046},0,2046,2046,0,0,100,50),true);
    gpu.present({});
    assert.deepEqual(trace.filter(x=>x[0]==='storage').map(x=>x[1]),[8,16]); // started at 8, doubled once
    assert.deepEqual(trace.filter(x=>x[0]==='copy').map(x=>x[1]),[0,1,2,3,4,5,6,7]);
    assert.equal(trace.filter(x=>x[0]==='delete').length,1); // the old texture
    assert.equal(gpu.stats.grows,1); assert.equal(gpu.stats.flushes,0); assert.equal(gpu.stats.evictions,0);
    assert.deepEqual(trace.filter(x=>x[0]==='batch').map(x=>x[1]),[9]); // one batch, nothing flushed early
    assert.equal(gpu.memory().layers,16);
  } finally {
    if(original===undefined)delete globalThis.document;else globalThis.document=original;
  }
});

test('the atlas stops growing at the GPU cap whatever the sprite memory setting', async () => {
  const constants=new Map(); let constant=0;
  const calls={ getShaderParameter:()=>true, getProgramParameter:()=>true, createShader:()=>({}), createProgram:()=>({}),
    createBuffer:()=>({}), createVertexArray:()=>({}), createTexture:()=>({}), createSampler:()=>({}), createFramebuffer:()=>({}),
    getUniformLocation:(_p,name)=>name, getError:()=>0 };
  const gl=new Proxy(calls,{get:(t,k)=>{ if(k in t)return t[k]; if(/^[A-Z_0-9]+$/.test(k)){ if(!constants.has(k))constants.set(k,++constant); return constants.get(k);} return ()=>{}; }});
  const original=globalThis.document;
  globalThis.document={createElement:()=>({getContext:()=>gl,classList:{add(){}},addEventListener(){}})};
  try {
    const gpu=await import('../src/vantage/web/sprite-gl.js?atlas-cap-test');
    gpu.setAtlasBudget(8192);
    assert.equal(gpu.begin(800,600,1,{}),true);
    for(let i=0;i<70;i++) gpu.draw({width:2046,height:2046},0,2046,2046,0,0,10,10);
    gpu.present({});
    assert.equal(gpu.memory().layers,64); // 1 GB, not 8 GB
    assert.ok(gpu.stats.flushes > 0); // beyond it the atlas reuses layers as before
  } finally {
    if(original===undefined)delete globalThis.document;else globalThis.document=original;
  }
});

test('past the per-frame upload budget a strip shows a frame it already has, and uploads the next frame', async () => {
  const trace=[], constants=new Map(); let constant=0;
  const calls={ getShaderParameter:()=>true, getProgramParameter:()=>true, createShader:()=>({}), createProgram:()=>({}),
    createBuffer:()=>({}), createVertexArray:()=>({}), createTexture:()=>({}), createSampler:()=>({}), createFramebuffer:()=>({}),
    getUniformLocation:(_p,name)=>name, getError:()=>0, texSubImage3D:()=>trace.push('upload') };
  const gl=new Proxy(calls,{get:(t,k)=>{ if(k in t)return t[k]; if(/^[A-Z_0-9]+$/.test(k)){ if(!constants.has(k))constants.set(k,++constant); return constants.get(k);} return ()=>{}; }});
  const original=globalThis.document;
  globalThis.document={createElement:()=>({getContext:()=>gl,classList:{add(){}},addEventListener(){}})};
  try {
    const gpu=await import('../src/vantage/web/sprite-gl.js?upload-budget-test');
    gpu.setUploadBudget(100 * 100); // one 100x100 frame per drawn frame
    const strip={width:400,height:100}, other={width:100,height:100};
    assert.equal(gpu.begin(800,600,1,{}),true);
    assert.equal(gpu.draw(strip,0,100,100,0,0,10,10),true);   // frame 0: uploaded
    assert.equal(gpu.draw(strip,100,100,100,0,0,10,10),true); // frame 1: over budget, frame 0 stands in
    assert.equal(gpu.draw(other,0,100,100,0,0,10,10),true);   // a strip with nothing uploaded yet still uploads
    gpu.present({});
    assert.equal(trace.length,2); assert.equal(gpu.stats.deferred,1);
    assert.equal(gpu.begin(800,600,1,{}),true);
    assert.equal(gpu.draw(strip,100,100,100,0,0,10,10),true); // next frame: its own picture
    gpu.present({});
    assert.equal(trace.length,3);
  } finally {
    if(original===undefined)delete globalThis.document;else globalThis.document=original;
  }
});
