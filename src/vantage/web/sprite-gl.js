// Sprites drawn on the GPU. The 2D canvas spends most of a busy frame inside
// drawImage (~800 calls per frame late in an 8-player game, a third of the main
// thread), so sprite pictures are queued here instead, with drawImage's own
// arguments, and drawn in one instanced WebGL2 call onto a canvas stacked over
// the world canvas (the ground) and under the overlay canvas (bars, flames,
// range circles, particles, fog). It is shown as it is: copying a WebGL canvas
// into a 2D one read the picture back to the CPU under ANGLE/Vulkan (7.6 ms a
// frame, measured). The map's distance haze and colour grade, which the 2D path
// applies to the finished frame, are applied here per pixel: both are affine
// colour maps, which commute with alpha blending, so grading each layer equals
// grading the whole.
//
// Every animation frame a queue entry names is copied once into an atlas: a
// texture array of ATLAS x ATLAS layers, packed in shelves. When the atlas is
// full the least recently used layer is emptied and its frames are uploaded
// again when next drawn. Instances draw in queue order, so the painter's order
// of the 2D path is kept exactly.
//
// Units behind buildings (world.js drawOccludedOutlines on the 2D path): the
// game outlines a unit in its player colour where a building drawn after it
// covers it. Here unit and building silhouettes are drawn into two offscreen
// targets that keep, per pixel, the draw order (group) of the last one drawn
// there; a full-screen pass then puts a unit's colour on every pixel next to
// the unit (but not on it) where a building drawn later stands.

const ATLAS = 2048;
const PAD = 1; // transparent border around each frame (linear filtering)
// Per instance: dst x,y,w,h; uv x0,y0,x1,y1; layer, alpha, smooth, role;
// group, outline rgb, player tint rgb (-1: none), mask offset (uv rows below the frame)
const FLOATS = 16;
/** Instance roles for the outline pass. */
export const ROLE_NONE = 0, ROLE_OUTLINED = 1, ROLE_OCCLUDER = 2;

let gl = null, canvas = null, prog = null, ringProg = null, vao = null, emptyVao = null, instBuf = null;
let tex = null, nearest = null, linear = null, layers = 0;
let unavailable = false;
/** Why GPU sprites are off here (empty while they work), for the performance view. */
export let initError = '';
const loc = {}, ringLoc = {};
// Outline targets: unit groups + colours (one framebuffer, two attachments) and
// building groups.
let targets = null;

// How long a frame counts as in use for eviction: two windows of this many
// drawn frames (3 to 6 s at 60 fps).
const HEAT_FRAMES = 180;

/**
 * Where frames go in the atlas: per layer, shelves of frames side by side. A
 * layer's generation changes when it is emptied, which invalidates every slot
 * packed in it. Pure bookkeeping (no WebGL), so it is tested on its own.
 *
 * Which layer is emptied when the atlas is full: the one with the least area
 * drawn lately (`use`), not the one touched longest ago. Layers fill in the
 * order frames first appear, so each holds a mix of animations still on screen
 * and ones long gone, and nearly every layer is touched every frame: least
 * recently touched then picked layers at random, full of frames in use, which
 * were uploaded again at once (late in an eight-player game at 8x half of all
 * uploads were repeats, 30 M texels a second). Emptying the coldest layer
 * re-uploads only its few live frames, next to each other.
 */
export class ShelfAtlas {
  /** `maxLayers`: the budget it may grow to (doubling) before it evicts. */
  constructor(layers, size, maxLayers = layers) {
    this.size = size;
    this.maxLayers = Math.max(layers, maxLayers);
    this.layers = Array.from({ length: layers }, () => ShelfAtlas.empty());
    this.evictions = 0;
    this.grows = 0;
    this.window = 0;
  }

  static empty() { return { shelves: [], used: -1, gen: 0, top: 0, heat: 0, heatPrev: 0 }; }

  /** A w x h rectangle for a frame drawn in frame `frame`: [layer, x, y] or null. */
  place(w, h, frame) {
    if (w > this.size || h > this.size) return null;
    for (let pass = 0; pass < 2; pass++) {
      for (let i = 0; i < this.layers.length; i++) {
        const L = this.layers[i];
        // A shelf takes frames up to its height, down to 60 % of it (less wastes it).
        for (const s of L.shelves) {
          if (h <= s.h && h >= s.h * 0.6 && s.x + w <= this.size) { const x = s.x; s.x += w; L.used = frame; return [i, x, s.y]; }
        }
        if (L.top + h <= this.size) {
          L.shelves.push({ y: L.top, h, x: w });
          const y = L.top; L.top += h; L.used = frame;
          return [i, 0, y];
        }
      }
      // Full: grow while the budget allows (the caller copies the texture over),
      // which keeps everything packed so far; only then evict.
      if (this.layers.length < this.maxLayers) {
        const n = Math.min(this.maxLayers, this.layers.length * 2) - this.layers.length;
        for (let i = 0; i < n; i++) this.layers.push(ShelfAtlas.empty());
        this.grows++;
        pass--;
        continue;
      }
      // At the budget: empty the layer with the least area drawn lately (ties:
      // the least recently used), never one needed in this frame.
      this.roll(frame);
      let pick = -1;
      for (let i = 0; i < this.layers.length; i++) {
        const L = this.layers[i];
        if (L.used >= frame) continue;
        if (pick < 0) { pick = i; continue; }
        const P = this.layers[pick], a = L.heat + L.heatPrev, b = P.heat + P.heatPrev;
        if (a < b || (a === b && L.used < P.used)) pick = i;
      }
      if (pick < 0) return null; // the whole atlas is in use by this one frame
      const L = this.layers[pick];
      L.shelves = []; L.top = 0; L.gen++; L.heat = 0; L.heatPrev = 0;
      this.evictions++;
    }
    return null;
  }

  // Heat is counted per window of HEAT_FRAMES frames; the last two windows count.
  roll(frame) {
    const w = Math.floor(frame / HEAT_FRAMES);
    if (w === this.window) return;
    const next = w === this.window + 1;
    for (const L of this.layers) { L.heatPrev = next ? L.heat : 0; L.heat = 0; }
    this.window = w;
  }

  /** A packed frame (`slot`: { layer, w, h }) is drawn in frame `frame`. */
  use(slot, frame) {
    this.roll(frame);
    const L = this.layers[slot.layer];
    L.used = frame;
    // Each frame counts once per window, however many times it is drawn.
    if (slot.window !== this.window) { slot.window = this.window; L.heat += slot.w * slot.h; }
  }

  gen(layer) { return this.layers[layer].gen; }
  touch(layer, frame) { this.layers[layer].used = frame; }
  usedLayers() { return this.layers.filter((L) => L.top > 0).length; }
}

let atlasSlots = null;
// Texels uploaded into the atlas this frame, and the most a frame uploads before
// strips fall back on frames they already have (8 M texels, 32 MB).
let uploadedPx = 0, uploadBudgetPx = 8 * 1048576;
/** Per-frame upload budget in texels (tests). */
export function setUploadBudget(px) { uploadBudgetPx = px; }
// One 2048² RGBA layer is 16 MB. The atlas starts at START_LAYERS and doubles up
// to the budget (setAtlasBudget, the "Sprite memory" setting). A fixed 16-layer
// atlas thrashed in late eight-player games at 8x: ~3,000 re-uploads and ~200
// whole-layer evictions per 15 s, and the playback clock waited on graphics.
const LAYER_MB = (ATLAS * ATLAS * 4) / 1048576;
const START_LAYERS = 8;
let budgetMb = 768, glMaxLayers = 0;
// The atlas never exceeds GPU_CAP_MB whatever the sprite memory setting (up to
// 8 GB): growing needs the old and the new texture at once. A lost context
// (often how a browser reports running out of video memory) halves the cap
// for the rest of the session, so the rebuilt atlas does not grow into it again.
const GPU_CAP_MB = 1024;
let lostCapMb = Infinity;
function budgetLayers() {
  const mb = Math.min(budgetMb, GPU_CAP_MB, lostCapMb);
  const want = Math.max(START_LAYERS, Math.floor(mb / LAYER_MB));
  return glMaxLayers ? Math.min(want, glMaxLayers) : want;
}

/** The GPU atlas may grow to `mb` megabytes (it never shrinks while in use). */
export function setAtlasBudget(mb) {
  if (!(mb > 0) || mb === budgetMb) return;
  budgetMb = mb;
  if (atlasSlots) atlasSlots.maxLayers = Math.max(atlasSlots.layers.length, budgetLayers());
}

// The bookkeeping grew: reallocate the texture array at the new size and copy
// the packed layers across on the GPU (slots keep their layer and position).
function growTexture() {
  const n = atlasSlots.layers.length;
  const next = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D_ARRAY, next);
  gl.getError(); // clear: the next read must be this allocation's
  gl.texStorage3D(gl.TEXTURE_2D_ARRAY, 1, gl.RGBA8, ATLAS, ATLAS, n);
  const err = gl.getError();
  if (err && err !== gl.NO_ERROR) {
    // Out of video memory: stay at the current size from now on.
    gl.deleteTexture(next);
    gl.bindTexture(gl.TEXTURE_2D_ARRAY, tex);
    atlasSlots.layers.length = layers;
    atlasSlots.maxLayers = layers;
    return false;
  }
  const fb = gl.createFramebuffer();
  const prevRead = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING);
  gl.bindFramebuffer(gl.READ_FRAMEBUFFER, fb);
  for (let i = 0; i < layers; i++) {
    gl.framebufferTextureLayer(gl.READ_FRAMEBUFFER, gl.COLOR_ATTACHMENT0, tex, 0, i);
    gl.copyTexSubImage3D(gl.TEXTURE_2D_ARRAY, 0, 0, 0, i, 0, 0, ATLAS, ATLAS);
  }
  gl.bindFramebuffer(gl.READ_FRAMEBUFFER, prevRead);
  gl.deleteFramebuffer(fb);
  gl.deleteTexture(tex);
  tex = next;
  layers = n;
  stats.grows++;
  return true;
}
let frameNo = 0;
// ImageBitmap -> Map(sx [| rows] -> slot { layer, gen, x, y, w, h })
let slots = new WeakMap();

let inst = new Float32Array(FLOATS * 1024);
let count = 0, group = 0, outlined = 0, occluders = 0;
let instCapacity = 0; // bytes allocated for instBuf on the GPU
let view = { w: 1, h: 1, dpr: 1 };
let frameLook = {}, cleared = false;
/** Counters for the performance view. */
export const stats = { draws: 0, uploads: 0, deferred: 0, evictions: 0, grows: 0, tooLarge: 0, full: 0, flushes: 0, instances: 0, glMs: 0, outlinePasses: 0 };

function compile(type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'shader');
  return s;
}

function link(vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl.VERTEX_SHADER, vs));
  gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || 'link');
  return p;
}

// The grade as world.js hazePass and gradePass apply it: haze added (most at the
// top of the view), then a 'saturation' blend towards the Rec.601 grey, a
// multiply and an add.
const GRADE_GLSL = `
  uniform vec3 haze; uniform float height; // haze colour at the top of the view; device px
  uniform vec3 grade; uniform vec3 offset; // saturation, scale, on; offset (0-1)
  vec3 graded(vec3 k) {
    k = min(k + haze * (gl_FragCoord.y / height), 1.0);
    k = mix(vec3(dot(k, vec3(0.3, 0.59, 0.11))), k, grade.x);
    return min(k * grade.y + offset, 1.0);
  }`;

function init() {
  if (gl || unavailable) return !!gl;
  try {
    canvas = document.createElement('canvas');
    canvas.id = 'world-gl';
    gl = canvas.getContext('webgl2', { premultipliedAlpha: true, alpha: true, antialias: false, depth: false, stencil: false, preserveDrawingBuffer: false });
    if (!gl) throw new Error('no webgl2');
    const vs = `#version 300 es
      layout(location=0) in vec2 corner;
      layout(location=1) in vec4 dst;
      layout(location=2) in vec4 src;
      layout(location=3) in vec4 extra; // layer, alpha, smooth, role
      layout(location=4) in vec4 meta;  // group, outline rgb, tint rgb, mask offset
      uniform vec2 size; // target size in CSS px
      uniform float atlas; // atlas edge in texels
      uniform int pass; // 0 colour, 1 outlined-unit silhouettes, 2 occluder silhouettes
      out vec3 uv; out float alpha; out float smoothing; out vec4 bounds; out vec2 tag; out vec2 paint;
      void main() {
        // A silhouette pass draws only its own role (the rest lands off screen).
        if (pass != 0 && int(extra.w) != pass) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
        vec2 p = dst.xy + corner * dst.zw;
        gl_Position = vec4(p.x / size.x * 2.0 - 1.0, 1.0 - p.y / size.y * 2.0, 0.0, 1.0);
        uv = vec3(mix(src.xy, src.zw, corner), extra.x);
        alpha = extra.y; smoothing = extra.z;
        // Filtering stays inside the frame, as drawImage does with a source rectangle.
        float h = 0.5 / atlas;
        bounds = vec4(src.xy + h, src.zw - h);
        tag = meta.xy;
        paint = meta.zw;
      }`;
    const fs = `#version 300 es
      precision highp float; // atlas coordinates need more than mediump's 11 bits
      precision highp int; // as the vertex shader's (uniform 'pass' is shared)
      precision mediump sampler2DArray;
      uniform sampler2DArray texN; uniform sampler2DArray texL;
      uniform int pass;
      ${GRADE_GLSL}
      in vec3 uv; in float alpha; in float smoothing; in vec4 bounds; in vec2 tag; in vec2 paint;
      layout(location=0) out vec4 color;
      layout(location=1) out vec4 tint;
      void main() {
        if (pass != 0) {
          // Silhouettes: the group (draw order, 16 bits) and the player colour.
          if (texture(texN, uv).a < 0.5) discard;
          color = vec4(mod(tag.x, 256.0), floor(tag.x / 256.0), 0.0, 255.0) / 255.0;
          tint = vec4(floor(tag.y / 65536.0), mod(floor(tag.y / 256.0), 256.0), mod(tag.y, 256.0), 255.0) / 255.0;
          return;
        }
        // Texels are premultiplied (the strips are decoded with premultiplyAlpha).
        vec4 c = smoothing > 0.5 ? texture(texL, vec3(clamp(uv.xy, bounds.xy, bounds.zw), uv.z)) : texture(texN, uv);
        if (paint.x >= 0.0 && c.a > 0.0) {
          // The player colour, as the server tints a strip (sld.py _tint): the mask
          // (in the band below the frame) blends towards the colour times the
          // pixel's luminance x 1.6.
          vec3 pc = vec3(floor(paint.x / 65536.0), mod(floor(paint.x / 256.0), 256.0), mod(paint.x, 256.0)) / 255.0;
          vec2 mu = uv.xy + vec2(0.0, paint.y);
          float m = (smoothing > 0.5 ? texture(texL, vec3(clamp(mu, bounds.xy + vec2(0.0, paint.y), bounds.zw + vec2(0.0, paint.y)), uv.z)) : texture(texN, vec3(mu, uv.z))).r;
          vec3 b = c.rgb / c.a;
          float lum = dot(b, vec3(0.3, 0.6, 0.1)) * 1.6;
          c = vec4(min(b * (1.0 - m) + pc * lum * m, 1.0) * c.a, c.a);
        }
        if (grade.z > 0.5 && c.a > 0.0) c = vec4(graded(c.rgb / c.a) * c.a, c.a);
        color = c * alpha;
        tint = vec4(0.0);
      }`;
    prog = link(vs, fs);
    for (const k of ['size', 'atlas', 'pass', 'haze', 'height', 'grade', 'offset', 'texN', 'texL']) loc[k] = gl.getUniformLocation(prog, k);
    // The ring pass: one full-screen triangle.
    ringProg = link(`#version 300 es
      void main() { vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2)); gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0); }`,
    `#version 300 es
      precision highp float;
      precision highp int;
      uniform highp sampler2D units; uniform highp sampler2D colors; uniform highp sampler2D blds;
      uniform int d; // ring width in device px
      ${GRADE_GLSL}
      out vec4 color;
      float groupAt(highp sampler2D t, ivec2 p) { vec4 v = texelFetch(t, p, 0); return floor(v.r * 255.0 + 0.5) + floor(v.g * 255.0 + 0.5) * 256.0; }
      void main() {
        ivec2 p = ivec2(gl_FragCoord.xy), last = textureSize(units, 0) - 1;
        float b = groupAt(blds, p);
        if (b == 0.0) discard;
        float here = groupAt(units, p);
        ivec2 offs[4] = ivec2[4](ivec2(d, 0), ivec2(-d, 0), ivec2(0, d), ivec2(0, -d));
        for (int i = 0; i < 4; i++) {
          ivec2 q = clamp(p + offs[i], ivec2(0), last);
          float u = groupAt(units, q);
          // Next to a unit, not on it, under a building drawn after it.
          if (u > 0.0 && u != here && u < b) {
            vec3 c = texelFetch(colors, q, 0).rgb;
            color = vec4(grade.z > 0.5 ? graded(c) : c, 1.0);
            return;
          }
        }
        discard;
      }`);
    for (const k of ['units', 'colors', 'blds', 'd', 'haze', 'height', 'grade', 'offset']) ringLoc[k] = gl.getUniformLocation(ringProg, k);
    vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    instBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, instBuf);
    for (let i = 0; i < 4; i++) {
      gl.enableVertexAttribArray(1 + i);
      gl.vertexAttribPointer(1 + i, 4, gl.FLOAT, false, FLOATS * 4, i * 16);
      gl.vertexAttribDivisor(1 + i, 1);
    }
    gl.bindVertexArray(null);
    emptyVao = gl.createVertexArray();
    // Start small (128 MB) and grow towards the sprite memory budget as a game
    // needs it: a 1v1 never pays for an eight-player late game's atlas.
    glMaxLayers = gl.getParameter(gl.MAX_ARRAY_TEXTURE_LAYERS) || 256; // WebGL2's guaranteed minimum
    layers = Math.min(START_LAYERS, glMaxLayers);
    tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D_ARRAY, tex);
    gl.texStorage3D(gl.TEXTURE_2D_ARRAY, 1, gl.RGBA8, ATLAS, ATLAS, layers);
    nearest = gl.createSampler();
    linear = gl.createSampler();
    for (const [s, f] of [[nearest, gl.NEAREST], [linear, gl.LINEAR]]) {
      gl.samplerParameteri(s, gl.TEXTURE_MIN_FILTER, f);
      gl.samplerParameteri(s, gl.TEXTURE_MAG_FILTER, f);
      gl.samplerParameteri(s, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.samplerParameteri(s, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    }
    atlasSlots = new ShelfAtlas(layers, ATLAS, budgetLayers());
    canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); lost(); });
    return true;
  } catch (err) {
    initError = String((err && err.message) || err);
    console.warn('[vantage] GPU sprites unavailable:', initError);
    gl = null; unavailable = true;
    return false;
  }
}

// A lost context starts over with a new canvas; the old one (its last picture)
// leaves the page.
function lost() {
  lostCapMb = Math.max(START_LAYERS * LAYER_MB, (layers * LAYER_MB) / 2);
  if (canvas && canvas.parentNode) canvas.remove();
  gl = null; unavailable = false; slots = new WeakMap(); count = 0; targets = null; instCapacity = 0;
}

/** Can sprites be drawn on the GPU here (WebGL2)? */
export function available() { return init(); }

/** The visible sprite canvas, placed after `el` in the page on first use. */
export function canvasAfter(el) {
  if (!init()) return null;
  if (!canvas.parentNode) el.after(canvas);
  return canvas;
}

/** Start a frame of w x h CSS pixels at pixel density dpr. */
export function begin(w, h, dpr, look = {}) {
  if (!init()) return false;
  view = { w, h, dpr };
  const pw = Math.max(1, Math.round(w * dpr)), ph = Math.max(1, Math.round(h * dpr));
  if (canvas.width !== pw || canvas.height !== ph) { canvas.width = pw; canvas.height = ph; }
  count = 0; group = 0; outlined = 0; occluders = 0;
  frameLook = look; cleared = false;
  uploadedPx = 0;
  frameNo++;
  return true;
}

/** Hide the sprite canvas (a frame drawn without it). */
export function hide() { if (canvas) canvas.classList.remove('on'); }

/** Start the next entity: its pictures share one draw-order group (outline pass). */
export function nextGroup() { if (group < 65535) group++; }

// `rows`: texel rows to upload (a player-mask strip's frame and its mask band).
function slotFor(img, sx, sw, sh, rows = sh) {
  let m = slots.get(img);
  if (!m) { m = new Map(); slots.set(img, m); }
  // Keyed by the rows too: a strip may be drawn with and without its mask band.
  const key = rows === sh ? sx : `${sx}|${rows}`;
  let s = m.get(key);
  if (s && s.gen === atlasSlots.gen(s.layer)) { atlasSlots.use(s, frameNo); return s; }
  const w = Math.ceil(sw), h = Math.ceil(rows);
  if (w + PAD * 2 > ATLAS || h + PAD * 2 > ATLAS) { stats.tooLarge++; return null; }
  // Past this frame's upload budget (a seek into a big battle brings hundreds of
  // new animation frames at once), a strip shows a frame of its own that is
  // already in the atlas for this one picture; its new frame uploads next frame.
  // A strip with nothing uploaded yet always uploads.
  if (uploadedPx >= uploadBudgetPx) {
    for (const alt of m.values()) {
      if (alt.h === h && alt.w === w && alt.gen === atlasSlots.gen(alt.layer)) { atlasSlots.use(alt, frameNo); stats.deferred++; return alt; }
    }
  }
  const before = atlasSlots.evictions;
  const at = atlasSlots.place(w + PAD * 2, h + PAD * 2, frameNo);
  stats.evictions += atlasSlots.evictions - before;
  if (!at) return null;
  if (atlasSlots.layers.length !== layers && !growTexture()) return null;
  const [layer, x, y] = at;
  gl.bindTexture(gl.TEXTURE_2D_ARRAY, tex);
  // The frame is a sub-rectangle of the strip: the unpack skips select it.
  gl.pixelStorei(gl.UNPACK_ROW_LENGTH, img.width);
  gl.pixelStorei(gl.UNPACK_SKIP_PIXELS, Math.round(sx));
  gl.pixelStorei(gl.UNPACK_SKIP_ROWS, 0);
  gl.texSubImage3D(gl.TEXTURE_2D_ARRAY, 0, x + PAD, y + PAD, layer, w, h, 1, gl.RGBA, gl.UNSIGNED_BYTE, img);
  gl.pixelStorei(gl.UNPACK_ROW_LENGTH, 0);
  gl.pixelStorei(gl.UNPACK_SKIP_PIXELS, 0);
  stats.uploads++;
  uploadedPx += w * h;
  s = { layer, gen: atlasSlots.gen(layer), x: x + PAD, y: y + PAD, w, h, window: -1 };
  atlasSlots.use(s, frameNo);
  m.set(key, s);
  return s;
}

/**
 * Queue drawImage(img, sx, 0, sw, sh, dx, dy, dw, dh) (CSS pixels of the
 * target). `role` and `rgb` (0xRRGGBB) feed the outline pass. `tint`
 * (0xRRGGBB, or -1) colours a player-mask strip, whose mask band lies `maskRows`
 * below the frame. False when the frame cannot be placed (the caller draws it).
 */
export function draw(img, sx, sw, sh, dx, dy, dw, dh, alpha = 1, smooth = false, role = ROLE_NONE, rgb = 0, tint = -1, maskRows = 0) {
  if (!gl) return false;
  const rows = maskRows ? sh + maskRows : sh;
  let s = slotFor(img, sx, sw, sh, rows);
  if (!s && count && sw + PAD * 2 <= ATLAS && rows + PAD * 2 <= ATLAS) {
    // Everything in the atlas is referenced by the pending batch. Draw it
    // before reusing its layers; otherwise player-mask sprites simply vanish.
    present(frameLook, false);
    frameNo++;
    stats.flushes++;
    s = slotFor(img, sx, sw, sh, rows);
  }
  if (!s) { stats.full++; return false; }
  if ((count + 1) * FLOATS > inst.length) {
    const grown = new Float32Array(inst.length * 2);
    grown.set(inst);
    inst = grown;
  }
  const o = count * FLOATS;
  inst[o] = dx; inst[o + 1] = dy; inst[o + 2] = dw; inst[o + 3] = dh;
  // A frame narrower than its slot (fractional source width) samples its own texels only.
  inst[o + 4] = s.x / ATLAS; inst[o + 5] = s.y / ATLAS;
  inst[o + 6] = (s.x + sw) / ATLAS; inst[o + 7] = (s.y + sh) / ATLAS;
  inst[o + 8] = s.layer; inst[o + 9] = alpha; inst[o + 10] = smooth ? 1 : 0; inst[o + 11] = role;
  inst[o + 12] = group; inst[o + 13] = rgb;
  inst[o + 14] = maskRows ? tint : -1; inst[o + 15] = maskRows / ATLAS;
  if (role === ROLE_OUTLINED) outlined++; else if (role === ROLE_OCCLUDER) occluders++;
  count++;
  return true;
}

function target(tw, th) {
  if (targets && targets.w === tw && targets.h === th) return targets;
  if (targets) { for (const t of targets.tex) gl.deleteTexture(t); for (const f of targets.fb) gl.deleteFramebuffer(f); }
  const make = () => {
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA8, tw, th);
    return t;
  };
  const tx = [make(), make(), make()];
  const fbU = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbU);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tx[0], 0);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT1, gl.TEXTURE_2D, tx[1], 0);
  gl.drawBuffers([gl.COLOR_ATTACHMENT0, gl.COLOR_ATTACHMENT1]);
  const fbB = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbB);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tx[2], 0);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  targets = { w: tw, h: th, tex: tx, fb: [fbU, fbB] };
  return targets;
}

function setLook(l, look) {
  const g = look.grade, hz = look.haze;
  gl.uniform3f(l.grade, g ? g.s : 1, g ? g.A : 1, g || hz ? 1 : 0);
  gl.uniform3f(l.offset, g ? g.O[0] / 255 : 0, g ? g.O[1] / 255 : 0, g ? g.O[2] / 255 : 0);
  gl.uniform3f(l.haze, hz ? hz[0] : 0, hz ? hz[1] : 0, hz ? hz[2] : 0);
  gl.uniform1f(l.height, canvas.height);
}

/**
 * Draw the queued sprites onto the visible canvas. `look`: { haze: [r, g, b]
 * (0-1, at the top of the view) | null, grade: { s, A, O: [bytes] } | null,
 * outline: ring width in device px (0: none) }.
 */
export function present(look = {}, final = true) {
  if (!gl) return;
  const t0 = performance.now();
  const { w, h } = view;
  const W = canvas.width, H = canvas.height;
  gl.viewport(0, 0, W, H);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  const first = !cleared;
  if (first) {
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }
  cleared = true;
  canvas.classList.add('on');
  if (!count) { if (final) presentOutlines(look); return; }
  gl.useProgram(prog);
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, instBuf);
  // Reallocate the instance buffer only when it must grow; otherwise overwrite
  // the part this batch uses (bufferData every frame reallocated it).
  const bytes = count * FLOATS * 4;
  if (bytes > instCapacity) {
    instCapacity = Math.max(bytes, instCapacity * 2, FLOATS * 4 * 1024);
    gl.bufferData(gl.ARRAY_BUFFER, instCapacity, gl.STREAM_DRAW);
  }
  gl.bufferSubData(gl.ARRAY_BUFFER, 0, inst.subarray(0, count * FLOATS));
  gl.uniform2f(loc.size, w, h);
  gl.uniform1f(loc.atlas, ATLAS);
  setLook(loc, look);
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D_ARRAY, tex);
  gl.bindSampler(0, nearest);
  gl.activeTexture(gl.TEXTURE1);
  gl.bindTexture(gl.TEXTURE_2D_ARRAY, tex);
  gl.bindSampler(1, linear);
  gl.uniform1i(loc.texN, 0);
  gl.uniform1i(loc.texL, 1);
  const rings = look.outline > 0;
  if (rings) {
    // Silhouettes, in draw order (the last drawn keeps the pixel), no blending.
    const t = target(W, H);
    gl.disable(gl.BLEND);
    gl.bindFramebuffer(gl.FRAMEBUFFER, t.fb[0]);
    if (first) {
      gl.clearBufferfv(gl.COLOR, 0, [0, 0, 0, 0]);
      gl.clearBufferfv(gl.COLOR, 1, [0, 0, 0, 0]);
    }
    gl.uniform1i(loc.pass, ROLE_OUTLINED);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
    gl.bindFramebuffer(gl.FRAMEBUFFER, t.fb[1]);
    if (first) gl.clearBufferfv(gl.COLOR, 0, [0, 0, 0, 0]);
    gl.uniform1i(loc.pass, ROLE_OCCLUDER);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  gl.uniform1i(loc.pass, 0);
  gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
  if (final) presentOutlines(look);
  gl.bindVertexArray(null);
  stats.draws++;
  stats.instances += count;
  count = 0;
  stats.glMs += performance.now() - t0;
}

function presentOutlines(look) {
  if (look.outline > 0 && outlined && occluders && targets) {
    const t = targets;
    gl.useProgram(ringProg);
    gl.bindVertexArray(emptyVao);
    t.tex.forEach((tx, i) => {
      gl.activeTexture(gl.TEXTURE2 + i);
      gl.bindTexture(gl.TEXTURE_2D, tx);
      gl.bindSampler(2 + i, nearest);
    });
    gl.uniform1i(ringLoc.units, 2); gl.uniform1i(ringLoc.colors, 3); gl.uniform1i(ringLoc.blds, 4);
    gl.uniform1i(ringLoc.d, look.outline);
    setLook(ringLoc, look);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    stats.outlinePasses++;
  }
}

/** GPU memory held by the atlas, for the performance view. */
export function memory() {
  if (!gl) return { bytes: 0, layers: 0, used: 0 };
  return { bytes: layers * ATLAS * ATLAS * 4, layers, used: atlasSlots.usedLayers() };
}
