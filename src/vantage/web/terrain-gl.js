// The ground as the game shapes it: a height field over the tile grid, drawn with
// WebGL into an offscreen canvas that the world view copies in.
//
// Heights are in elevation levels. A tile corner stands at the highest elevation
// of the four tiles that meet there; each tile is two triangles, split along the
// diagonal its slope shape names (shapes 1, 2, 11-14 along the x+y corners, 3, 4,
// 9, 10, 15, 16 along the x-y corners; flat shapes either way). Fitted to the
// game's own object heights (Entity.worldZ): every object of a 6-player map lies
// on this surface within 0.05 levels. One level lifts a point by half a tile's
// screen height (8 px at zoom 1).

const ANTI = new Set([1, 2, 11, 12, 13, 14]);

let gl = null, canvas = null, prog = null, loc = null;
let mapW = 0, mapH = 0, corner = null, shape = null;
const chunkMesh = new Map(); // "cx,cy" -> { buf, n }
let fullMesh = null;
const textures = new Map(); // key -> { tex, src, w, h, used }
let frameNo = 0;

/** Lift in levels at a map point (x, y): the ground surface's height there. */
export function heightAt(x, y) {
  if (!corner) return 0;
  const cx = Math.floor(x), cy = Math.floor(y);
  if (cx < 0 || cy < 0 || cx >= mapW || cy >= mapH) return 0;
  const u = x - cx, v = y - cy;
  const W = mapW + 1;
  const a = corner[cy * W + cx], b = corner[cy * W + cx + 1];
  const c = corner[(cy + 1) * W + cx], d = corner[(cy + 1) * W + cx + 1];
  if (ANTI.has(shape[cy * mapW + cx])) {
    return u + v <= 1 ? a + (b - a) * u + (c - a) * v : d + (c - d) * (1 - u) + (b - d) * (1 - v);
  }
  return u >= v ? a + (b - a) * u + (d - b) * v : a + (d - c) * u + (c - a) * v;
}

/** Set the map's elevation (one byte per tile, row-major) and slope shapes. */
export function setHeights(elev, shapes, w, h) {
  mapW = w; mapH = h;
  shape = shapes && shapes.length === w * h ? shapes : new Uint8Array(w * h);
  const E = (x, y) => elev[Math.min(h - 1, Math.max(0, y)) * w + Math.min(w - 1, Math.max(0, x))];
  corner = new Float32Array((w + 1) * (h + 1));
  for (let y = 0; y <= h; y++) {
    for (let x = 0; x <= w; x++) {
      corner[y * (w + 1) + x] = Math.max(E(x - 1, y - 1), E(x, y - 1), E(x - 1, y), E(x, y));
    }
  }
  for (const m of chunkMesh.values()) if (gl) gl.deleteBuffer(m.buf);
  chunkMesh.clear();
  if (fullMesh && gl) for (const m of fullMesh) gl.deleteBuffer(m.buf);
  fullMesh = null;
}

export function hasHeights() { return !!corner; }

function init() {
  if (gl) return true;
  canvas = document.createElement('canvas');
  gl = canvas.getContext('webgl', { premultipliedAlpha: true, alpha: true, antialias: false });
  if (!gl) return false;
  canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); lost(); });
  const vs = `attribute vec3 p; uniform vec4 cam; uniform vec4 view; varying vec2 uv; uniform vec4 uvMap;
    void main() {
      // cam: x, y (tile), zoom, unused; view: w, h (css px), tile w, tile h
      float sx = ((p.x + p.y) - (cam.x + cam.y)) * view.z * 0.5 * cam.z + view.x * 0.5;
      float sy = ((p.y - p.x) - (cam.y - cam.x)) * view.w * 0.5 * cam.z + view.y * 0.5 - p.z * view.w * 0.5 * cam.z;
      gl_Position = vec4(sx / view.x * 2.0 - 1.0, 1.0 - sy / view.y * 2.0, 0.0, 1.0);
      uv = vec2((p.x - uvMap.x) / uvMap.z, (p.y - uvMap.y) / uvMap.w);
    }`;
  const fs = `precision mediump float; varying vec2 uv; uniform sampler2D tex; uniform vec4 tint; uniform float mode; uniform vec3 groundTint;
    void main() {
      vec4 c = texture2D(tex, uv);
      // mode 0: colour texture; 1: fog (alpha only, tinted)
      gl_FragColor = mode < 0.5 ? vec4(c.rgb * groundTint * c.a, c.a) : vec4(tint.rgb * c.a, c.a);
    }`;
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
  prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, vs));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { gl = null; return false; }
  loc = {
    p: gl.getAttribLocation(prog, 'p'), cam: gl.getUniformLocation(prog, 'cam'), view: gl.getUniformLocation(prog, 'view'),
    uvMap: gl.getUniformLocation(prog, 'uvMap'), tex: gl.getUniformLocation(prog, 'tex'),
    tint: gl.getUniformLocation(prog, 'tint'), mode: gl.getUniformLocation(prog, 'mode'),
    groundTint: gl.getUniformLocation(prog, 'groundTint'),
  };
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  return true;
}

// A lost context (a driver reset, the GPU process restarting, memory pressure)
// takes every buffer, texture and program with it: forget them all and start
// over with a new canvas on the next frame, as the sprite renderer does.
let lostListener = null;
function lost() {
  gl = null; canvas = null; prog = null; loc = null; compose = null;
  chunkMesh.clear(); fullMesh = null; textures.clear(); composed.clear(); imageTex.clear();
  if (lostListener) lostListener();
}
/** Call `fn` after the context is lost, so the caller drops what it drew with it. */
export function onContextLost(fn) { lostListener = fn; }

/** Can the height-mapped ground be drawn (WebGL available, heights set)? */
export function available() { return !!corner && init(); }

// Triangles of the tiles [x0, x1) x [y0, y1): x, y, height per vertex.
function meshFor(x0, y0, x1, y1) {
  const W = mapW + 1;
  const out = new Float32Array((x1 - x0) * (y1 - y0) * 18);
  let k = 0;
  const put = (x, y) => { out[k++] = x; out[k++] = y; out[k++] = corner[y * W + x]; };
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      if (ANTI.has(shape[y * mapW + x])) {
        put(x, y); put(x + 1, y); put(x, y + 1);
        put(x + 1, y); put(x + 1, y + 1); put(x, y + 1);
      } else {
        put(x, y); put(x + 1, y); put(x + 1, y + 1);
        put(x, y); put(x + 1, y + 1); put(x, y + 1);
      }
    }
  }
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, out, gl.STATIC_DRAW);
  return { buf, n: k / 3 };
}

function chunkMeshAt(cx, cy, size) {
  const key = `${cx},${cy}`;
  let m = chunkMesh.get(key);
  if (!m) {
    const x0 = cx * size, y0 = cy * size;
    m = meshFor(x0, y0, Math.min(mapW, x0 + size), Math.min(mapH, y0 + size));
    chunkMesh.set(key, m);
  }
  return m;
}

/** Start a frame: size the canvas to the view (device px) and clear it. */
export function begin(w, h, dpr) {
  const cw = Math.max(1, Math.round(w * dpr)), ch = Math.max(1, Math.round(h * dpr));
  if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
  gl.viewport(0, 0, cw, ch);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  frameNo++;
}

function texFor(key, src, linear) {
  let t = textures.get(key);
  if (!t) {
    t = { tex: gl.createTexture(), src: null, used: 0 };
    textures.set(key, t);
    if (textures.size > 160) {
      // Drop the least recently used (not this frame's).
      let old = null;
      for (const [k, v] of textures) if (v.used < frameNo && (!old || v.used < old[1].used)) old = [k, v];
      if (old) { gl.deleteTexture(old[1].tex); textures.delete(old[0]); }
    }
  }
  gl.bindTexture(gl.TEXTURE_2D, t.tex);
  if (t.src !== src || src._dirty) {
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    const f = linear ? gl.LINEAR : gl.NEAREST;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, f);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, f);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    t.src = src;
    if (src._dirty) src._dirty = false;
  }
  t.used = frameNo;
  return t.tex;
}

let groundTint = [1, 1, 1];
/** The map's terrain tint (colour-grade preset), multiplied into the ground. */
export function setTint(t) { groundTint = t; }

function use(camera, w, h, tw, th) {
  gl.useProgram(prog);
  gl.uniform3f(loc.groundTint, groundTint[0], groundTint[1], groundTint[2]);
  gl.uniform4f(loc.cam, camera.x, camera.y, camera.zoom, 0);
  gl.uniform4f(loc.view, w, h, tw, th);
  gl.uniform1i(loc.tex, 0);
  gl.activeTexture(gl.TEXTURE0);
}

function drawMesh(m) {
  gl.bindBuffer(gl.ARRAY_BUFFER, m.buf);
  gl.enableVertexAttribArray(loc.p);
  gl.vertexAttribPointer(loc.p, 3, gl.FLOAT, false, 0, 0);
  gl.drawArrays(gl.TRIANGLES, 0, m.n);
}

const FULL = 32; // the whole-map passes are drawn in blocks of this many tiles

function fullBlocks() {
  if (!fullMesh) {
    fullMesh = [];
    for (let y = 0; y < mapH; y += FULL) for (let x = 0; x < mapW; x += FULL) {
      const m = meshFor(x, y, Math.min(mapW, x + FULL), Math.min(mapH, y + FULL));
      m.x0 = x; m.y0 = y;
      fullMesh.push(m);
    }
  }
  return fullMesh;
}

/**
 * A map-space texture (one texel per tile, ``src`` mapW x mapH) over the whole
 * map: the flat-colour ground (mode 0) or the fog (mode 1: its alpha, ``tint``).
 * ``range`` [minX, maxX, minY, maxY] skips blocks off screen.
 */
export function drawMapTexture(key, src, camera, view, range, { linear = false, fog = false, tint = [0, 0, 0] } = {}) {
  use(camera, view.w, view.h, view.tw, view.th);
  gl.bindTexture(gl.TEXTURE_2D, texFor(key, src, linear));
  gl.uniform4f(loc.uvMap, 0, 0, mapW, mapH);
  gl.uniform1f(loc.mode, fog ? 1 : 0);
  gl.uniform4f(loc.tint, tint[0], tint[1], tint[2], 1);
  for (const m of fullBlocks()) {
    if (m.x0 > range[1] || m.x0 + FULL < range[0] || m.y0 > range[3] || m.y0 + FULL < range[2]) continue;
    drawMesh(m);
  }
}

/** One terrain chunk (``size`` x ``size`` tiles; its canvas covers exactly those tiles). */
export function drawChunk(cx, cy, size, src, camera, view, linear) {
  use(camera, view.w, view.h, view.tw, view.th);
  if (src && src.composed) {
    const t = composed.get(src.composed);
    if (!t) return;
    gl.bindTexture(gl.TEXTURE_2D, t);
  } else gl.bindTexture(gl.TEXTURE_2D, texFor(`c${cx},${cy}`, src, linear));
  gl.uniform4f(loc.uvMap, cx * size, cy * size, size, size);
  gl.uniform1f(loc.mode, 0);
  drawMesh(chunkMeshAt(cx, cy, size));
}

/** The finished frame (draw it with drawImage at device pixels). */
export function output() { return canvas; }

// -- terrain chunks composited on the GPU ----------------------------------------------
// world.js buildChunk blends a chunk's terrains on a 2D canvas: every terrain
// type's texture through its bilinearly upscaled per-tile indicator, added up
// ('lighter'); layer terrains through their indicator times their overlay noise,
// laid over ('source-over'); then the elevation shading. Rebuilding a chunk that
// way took 10-30 ms (8x replay rebuilds one every few seconds as farms and
// foundations repaint tiles). Here the same passes are drawn into the chunk's
// texture: a few full-chunk quads.

let compose = null;
const composed = new Map(); // "cx,cy" -> texture
const imageTex = new Map(); // HTMLImageElement -> texture (repeat)

function initCompose() {
  if (compose) return compose;
  const vs = 'attribute vec2 a; void main() { gl_Position = vec4(a, 0.0, 1.0); }';
  // u: the chunk pixel (row 0 = the canvas's top row: textures upload unflipped).
  const fs = `precision highp float;
    uniform sampler2D tex; uniform sampler2D mask; uniform sampler2D noise;
    uniform vec3 texMap; uniform vec3 noiseMap; // offset x, y and period in chunk px
    uniform vec4 solid; // a flat colour instead of a texture (alpha 1)
    uniform float mode; // 0 base: added; 1 layer: laid over; 2 shading (premultiplied RGBA)
    uniform float useNoise; uniform float tile; uniform float pad;
    void main() {
      vec2 u = gl_FragCoord.xy;
      // drawImage(mask, -1.5 tiles, -1.5 tiles, pad tiles, pad tiles), smoothed.
      vec2 mu = (u / tile + 1.5) / pad;
      if (mode > 1.5) { gl_FragColor = texture2D(mask, mu); return; }
      float m = texture2D(mask, mu).a;
      vec3 c = solid.a > 0.0 ? solid.rgb : texture2D(tex, fract((u + texMap.xy) / texMap.z)).rgb;
      if (mode > 0.5) {
        float a = m * (useNoise > 0.5 ? texture2D(noise, fract((u + noiseMap.xy) / noiseMap.z)).r : 1.0);
        gl_FragColor = vec4(c * a, a);
      } else gl_FragColor = vec4(c * m, m);
    }`;
  const sh = (type, src) => { const x = gl.createShader(type); gl.shaderSource(x, src); gl.compileShader(x); return x; };
  const p = gl.createProgram();
  gl.attachShader(p, sh(gl.VERTEX_SHADER, vs));
  gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) { compose = false; return false; }
  const q = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, q);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
  const l = {};
  for (const k of ['tex', 'mask', 'noise', 'texMap', 'noiseMap', 'solid', 'mode', 'useNoise', 'tile', 'pad']) l[k] = gl.getUniformLocation(p, k);
  compose = { prog: p, quad: q, a: gl.getAttribLocation(p, 'a'), loc: l, fb: gl.createFramebuffer(), mask: gl.createTexture(), dummy: gl.createTexture() };
  gl.bindTexture(gl.TEXTURE_2D, compose.dummy);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
  return compose;
}

const pot = (n) => n > 0 && (n & (n - 1)) === 0;
function textureOf(img) {
  let t = imageTex.get(img);
  if (t) return t;
  t = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, t);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
  // Canvas patterns repeat; WebGL 1 repeats power-of-two textures only (the
  // game's are 256 or 512), others clamp at the seam.
  const wrap = pot(img.width) && pot(img.height) ? gl.REPEAT : gl.CLAMP_TO_EDGE;
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrap);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap);
  imageTex.set(img, t);
  return t;
}

function maskUpload(data, pad, format) {
  gl.bindTexture(gl.TEXTURE_2D, compose.mask);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texImage2D(gl.TEXTURE_2D, 0, format, pad, pad, 0, format, gl.UNSIGNED_BYTE, data);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
}

/** Can chunks be composited here (WebGL, the program compiles)? */
export function canCompose() { return init() && !!initCompose(); }

/**
 * Composite chunk (cx, cy) as world.js buildChunk does. `spec`: { px (chunk edge
 * in px), tile (px per tile), pad (indicator texels per edge), x0, y0 (chunk
 * origin in px of the map), linear, base: [{ img | color: [r,g,b] (0-1), rows,
 * mask: Uint8Array pad² }], layers: [{ ..., noise: { img, rows } | null }],
 * shade: Uint8Array pad² RGBA, premultiplied }. Returns the token to pass as
 * drawChunk's `src`.
 */
export function composeChunk(cx, cy, spec) {
  if (!canCompose()) return null;
  const key = `${cx},${cy}`;
  let t = composed.get(key);
  if (!t) {
    t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, spec.px, spec.px, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    composed.set(key, t);
  }
  gl.bindTexture(gl.TEXTURE_2D, t);
  const f = spec.linear ? gl.LINEAR : gl.NEAREST;
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, f);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, f);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const c = compose, l = c.loc;
  gl.bindFramebuffer(gl.FRAMEBUFFER, c.fb);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0);
  gl.viewport(0, 0, spec.px, spec.px);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.useProgram(c.prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, c.quad);
  gl.enableVertexAttribArray(c.a);
  gl.vertexAttribPointer(c.a, 2, gl.FLOAT, false, 0, 0);
  gl.uniform1f(l.tile, spec.tile);
  gl.uniform1f(l.pad, spec.pad);
  gl.uniform1i(l.tex, 1); gl.uniform1i(l.mask, 0); gl.uniform1i(l.noise, 2);
  const period = (rows) => spec.tile * rows;
  const place = (u, rows) => {
    const P = period(rows);
    gl.uniform3f(u, ((spec.x0 % P) + P) % P, ((spec.y0 % P) + P) % P, P);
  };
  const pass = (e, mode) => {
    gl.activeTexture(gl.TEXTURE0);
    maskUpload(e.mask, spec.pad, gl.ALPHA);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, e.img ? textureOf(e.img) : c.dummy);
    gl.uniform4f(l.solid, ...(e.color || [0, 0, 0]), e.img ? 0 : 1);
    place(l.texMap, e.rows);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, e.noise ? textureOf(e.noise.img) : c.dummy);
    gl.uniform1f(l.useNoise, e.noise ? 1 : 0);
    if (e.noise) place(l.noiseMap, e.noise.rows);
    gl.uniform1f(l.mode, mode);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  };
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE);
  for (const e of spec.base) pass(e, 0);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  for (const e of spec.layers) pass(e, 1);
  gl.activeTexture(gl.TEXTURE0);
  maskUpload(spec.shade, spec.pad, gl.RGBA);
  gl.uniform1f(l.mode, 2);
  gl.drawArrays(gl.TRIANGLES, 0, 6);
  gl.disableVertexAttribArray(c.a);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.activeTexture(gl.TEXTURE0);
  return { composed: key };
}

/** Forget composited chunks (a new map, or chunks world.js dropped). */
export function dropChunks(keys = null) {
  for (const [k, t] of composed) if (!keys || keys.includes(k)) { gl.deleteTexture(t); composed.delete(k); }
}
