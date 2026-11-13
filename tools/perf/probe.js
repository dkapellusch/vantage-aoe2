// The page-side probe of the viewer benchmark (tools/perf): injected before the
// viewer's own scripts. It wraps requestAnimationFrame to time the viewer's frame
// callback (`tick`), records frame timestamps, long tasks, sprite decodes and,
// after each frame, the sprite counters that say whether the picture is complete.
(() => {
  // Saved settings for a first visit (the HUD preset and the tutorials already seen).
  if (window.__perfSettings && !localStorage.getItem(window.__perfSettings[0])) localStorage.setItem(...window.__perfSettings);
  const P = window.__perf = {
    on: false, frames: [], work: [], long: [], decode: [], hud: [], state: [],
    driver: null, watch: null, errors: [],
  };
  const raf = window.requestAnimationFrame.bind(window);
  let prev = null;
  const snap = () => {
    const v = window.vantage;
    if (!v || !v.world) return null;
    const s = v.world.spriteStats, g = v.world.gpuSpriteStats();
    return { missing: s.missing, stale: s.stale, standIn: s.standIn, uploads: g.uploads, deferred: g.deferred, full: g.full, evictions: g.evictions, instances: g.instances, draws: g.draws };
  };
  window.requestAnimationFrame = (fn) => raf((now) => {
    const isTick = fn.name === 'tick';
    if (isTick && P.driver) { try { P.driver(now); } catch (e) { P.errors.push(String(e)); P.driver = null; } }
    const a = performance.now();
    fn(now);
    const b = performance.now();
    if (!isTick) return;
    if (P.on) { P.frames.push(now); P.work.push(b - a); }
    if (P.on || P.watch) {
      const cur = snap();
      if (cur && prev) {
        const d = {};
        for (const k in cur) d[k] = cur[k] - prev[k];
        if (P.on) P.state.push([d.missing, d.stale, d.standIn, d.uploads, d.deferred, d.instances]);
        if (P.watch) { try { P.watch(now, b, d); } catch (e) { P.errors.push(String(e)); P.watch = null; } }
      }
      prev = cur;
    } else prev = null;
  });
  const si = window.setInterval.bind(window);
  window.setInterval = (fn, ms, ...rest) => si(ms === 250 ? () => { const a = performance.now(); fn(); if (P.on) P.hud.push(performance.now() - a); } : fn, ms, ...rest);
  // Builds that split the HUD refresh into parts run each part from a MessageChannel
  // (app.js hudStep): time those tasks too, so `hud` is "one HUD task" in every build.
  const MC = window.MessageChannel, onmessage = Object.getOwnPropertyDescriptor(MessagePort.prototype, 'onmessage');
  window.MessageChannel = function () {
    const ch = new MC();
    for (const port of [ch.port1, ch.port2]) {
      let handler = null;
      Object.defineProperty(port, 'onmessage', {
        get: () => handler,
        set(fn) {
          handler = fn;
          const timed = fn && fn.name === 'hudStep';
          onmessage.set.call(port, timed ? (e) => { const a = performance.now(); fn(e); if (P.on) P.hud.push(performance.now() - a); } : fn);
        },
      });
    }
    return ch;
  };
  try { new PerformanceObserver((l) => { if (P.on) for (const e of l.getEntries()) P.long.push([e.startTime, e.duration]); }).observe({ entryTypes: ['longtask'] }); } catch (e) { /* not supported */ }
  if (window.createImageBitmap) {
    const cib = window.createImageBitmap.bind(window);
    window.createImageBitmap = (...args) => { const a = performance.now(); const p = cib(...args); p.then(() => { if (P.on) P.decode.push(performance.now() - a); }, () => {}); return p; };
  }
  // After a jump (seek, camera jump): ms until the first frame showing the right
  // moment, and until the first of `settle` consecutive complete frames.
  P.afterJump = (target, settle = 3, timeout = 20000) => new Promise((resolve) => {
    const t0 = performance.now();
    let first = null, clean = 0, cleanAt = null, frames = 0, incomplete = 0;
    const waited = {}; // what was missing -> frames it was missing for
    P.watch = (now, end, d) => {
      const v = window.vantage, S = v.S;
      frames++;
      const right = target == null || (S.view && S.view.time <= target + 1 && target - S.view.time < 2500 && Math.abs(S.t - target) < 2500);
      if (right && first == null) first = end - t0;
      // d.missing is not part of it: an entity the game has no picture for counts there every frame.
      // framePending: newer builds say what is missing; older ones only whether.
      const pending = v.world.framePending ? v.world.framePending() : v.world.initialFrameReady() ? [] : ['?'];
      if (d.stale) pending.push('stale pose');
      if (d.standIn) pending.push('facing stand-in');
      if (d.deferred) pending.push('deferred upload');
      const whole = right && pending.length === 0;
      if (right && !whole) for (const k of pending) waited[k] = (waited[k] || 0) + 1;
      if (right && !whole) incomplete++;
      if (whole) { if (!clean) cleanAt = end - t0; clean++; } else { clean = 0; cleanAt = null; }
      if (clean >= settle || end - t0 > timeout) { P.watch = null; resolve({ first, full: clean >= settle ? cleanAt : null, frames, incomplete, waited }); }
    };
  });
  P.reset = () => { P.frames = []; P.work = []; P.long = []; P.decode = []; P.hud = []; P.state = []; };

  // -- helpers the Python side calls -------------------------------------------------
  P.renderer = () => {
    const gl = document.createElement('canvas').getContext('webgl2');
    if (!gl) return 'no webgl2';
    const e = gl.getExtension('WEBGL_debug_renderer_info');
    return e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
  };
  P.seek = async (t, playing, timeout) => {
    const v = window.vantage;
    v.S.playing = playing;
    const done = P.afterJump(t, 3, timeout);
    v.seek(t);
    v.S.playing = playing;
    return await done;
  };
  P.jump = async (x, y, zoom) => {
    const done = P.afterJump(null, 3, 20000);
    window.vantage.world.setCamera(x, y, zoom);
    return await done;
  };
  P.speed = (index) => {
    const v = window.vantage;
    for (let n = 0; n < 12 && v.S.speedIndex !== index; n++) {
      const i = v.S.speedIndex;
      if (i < index) v.actions.speedStepUp(); else v.actions.speedStepDown();
      if (v.S.speedIndex === i) break;
    }
  };
  P.start = () => { P.reset(); P.on = true; };
  P.collect = () => {
    const v = window.vantage, w = v.world, s = w.spriteStats;
    return {
      frames: P.frames, work: P.work, long: P.long, decode: P.decode, hud: P.hud, state: P.state, errors: P.errors,
      drawTimes: { ...w.drawTimes }, gpu: w.gpuSpriteStats(), sprites: w.spriteMemory(),
      spriteStats: { missing: s.missing, stale: s.stale, standIn: s.standIn },
      heap: performance.memory ? performance.memory.usedJSHeapSize : 0, t: v.S.t, speed: v.S.speedIndex,
      entities: v.S.view ? v.S.view.entities.length : 0, fps: v.S.fps,
    };
  };
  // A figure of eight about the start, `speed` screen px/s: every direction, and
  // new ground and new sprites coming in all the time.
  P.pan = (speed, radius) => {
    const w = window.vantage.world;
    let last = null, a = 0;
    P.driver = (now) => {
      const dt = last == null ? 0 : Math.min(0.1, (now - last) / 1000);
      last = now;
      const step = speed * dt;
      a += step / radius;
      w.pan(Math.cos(a) * step, Math.sin(2 * a) * step);
    };
  };
  // Keep a long run inside the recording: back to `lo` once past `hi`.
  P.loop = (lo, hi) => { const v = window.vantage; if (v.S.t > hi) v.seek(lo); v.S.playing = true; };
  // Nothing that moves on its own clock: the picture is a function of (t, camera).
  P.still = () => {
    const el = document.createElement('style');
    el.textContent = '*, *::before, *::after { animation: none !important; transition: none !important; } .toast, #toast { display: none !important; }';
    document.head.append(el);
  };
  P.shown = () => {
    const v = window.vantage;
    return { t: v.S.t, view: v.S.view.time, entities: v.S.view.entities.length, gpu: v.world.gpuSpriteStats().on };
  };
  // The world alone (its stacked canvases) as a PNG data URL, without the HUD.
  P.worldPng = () => {
    const base = document.getElementById('world');
    const c = document.createElement('canvas');
    c.width = base.width; c.height = base.height;
    const g = c.getContext('2d');
    for (const id of ['world', 'world-gl', 'world-top']) {
      const el = document.getElementById(id);
      if (el && (id === 'world' || el.classList.contains('on'))) g.drawImage(el, 0, 0);
    }
    return c.toDataURL('image/png');
  };
})();
