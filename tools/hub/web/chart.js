// One line chart: a metric over game time, a line per player, on a canvas.
// One y axis, a legend outside (app.js), a name at each line's end, age-up ticks on
// the line, and a crosshair with every player's value on hover or arrow keys.

export const METRICS = {
  army_value: { label: 'Army value', unit: 'resources' },
  villagers: { label: 'Villagers', unit: '' },
  military: { label: 'Military units', unit: '' },
  rate_total: { label: 'Collection rate', unit: 'per minute' },
  col_total: { label: 'Resources collected', unit: '' },
  score: { label: 'Score', unit: '' },
  kills: { label: 'Kills', unit: '' },
  eapm: { label: 'eAPM', unit: 'actions per minute' },
};

const clock = (ms) => {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};
// A round step giving about `ticks` grid lines up to `max`.
export function niceStep(max, ticks) {
  const raw = Math.max(max, 1e-9) / ticks;
  const mag = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw);
}
// The row at or before time t (rows are in time order).
export function rowAt(rows, t) {
  let lo = 0;
  let hi = rows.length - 1;
  if (hi < 0 || rows[0].t > t) return null;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (rows[mid].t <= t) lo = mid; else hi = mid - 1;
  }
  return rows[lo];
}

const state = new WeakMap();

export function drawChart(canvas, tip, series, metric, end) {
  const css = getComputedStyle(canvas);
  const ink = css.getPropertyValue('--ink').trim() || '#e8e6df';
  const muted = css.getPropertyValue('--muted').trim() || '#8b93a1';
  const grid = css.getPropertyValue('--grid').trim() || '#262b35';
  const surface = css.getPropertyValue('--panel').trim() || '#14171d';
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (!w || !h) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.font = '12px system-ui, sans-serif';

  const labelW = Math.min(140, Math.max(...series.map((s) => g.measureText(s.name).width)) + 12);
  const box = { l: 48, r: w - labelW, t: 12, b: h - 26 };
  const max = Math.max(1, ...series.flatMap((s) => s.rows.map((r) => r[metric] ?? 0)));
  const step = niceStep(max, 4);
  const top = Math.ceil(max / step) * step;
  const x = (t) => box.l + (t / Math.max(end, 1)) * (box.r - box.l);
  const y = (v) => box.b - (v / top) * (box.b - box.t);

  g.clearRect(0, 0, w, h);
  g.textBaseline = 'middle';
  g.textAlign = 'right';
  for (let v = 0; v <= top + 1e-9; v += step) {
    g.strokeStyle = grid;
    g.lineWidth = 1;
    g.beginPath(); g.moveTo(box.l, Math.round(y(v)) + 0.5); g.lineTo(box.r, Math.round(y(v)) + 0.5); g.stroke();
    g.fillStyle = muted;
    g.fillText(v >= 10000 ? `${+(v / 1000).toFixed(1)}k` : String(+v.toFixed(1)), box.l - 8, y(v));
  }
  g.textAlign = 'center';
  g.textBaseline = 'top';
  const minutes = end / 60000;
  const every = [1, 2, 5, 10, 15, 20, 30, 60].find((m) => minutes / m <= 8) || 120;
  for (let m = 0; m <= minutes; m += every) g.fillText(`${m}:00`, x(m * 60000), box.b + 8);

  // Line-end names are nudged apart so they never overlap.
  const ends = series.map((s) => ({ s, y: s.rows.length ? y(s.rows[s.rows.length - 1][metric] ?? 0) : box.b }));
  ends.sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i += 1) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 14);
  for (let i = ends.length - 2, floor = box.b; i >= -1; i -= 1) {
    const e = ends[i + 1];
    if (e.y > floor) e.y = floor;
    floor = e.y - 14;
  }
  for (const s of series) {
    g.strokeStyle = s.color;
    g.lineWidth = 2;
    g.lineJoin = 'round';
    g.beginPath();
    s.rows.forEach((r, i) => (i ? g.lineTo(x(r.t), y(r[metric] ?? 0)) : g.moveTo(x(r.t), y(r[metric] ?? 0))));
    g.stroke();
    // Age-ups: a ringed dot on the line where the player reached each age.
    for (const t of Object.values(s.ages)) {
      const r = rowAt(s.rows, t);
      if (!r) continue;
      g.fillStyle = s.color;
      g.strokeStyle = surface;
      g.lineWidth = 2;
      g.beginPath(); g.arc(x(t), y(r[metric] ?? 0), 4.5, 0, Math.PI * 2); g.fill(); g.stroke();
    }
  }
  g.textAlign = 'left';
  g.textBaseline = 'middle';
  g.fillStyle = ink;
  if (series.length <= 4) for (const e of ends) g.fillText(e.s.name, box.r + 8, e.y, labelW - 10);

  const held = state.get(canvas) || {};
  state.set(canvas, { ...held, box, x, y, series, metric, end });
  if (held.at != null) crosshair(canvas, tip, held.at);
  if (!held.wired) {
    state.get(canvas).wired = true;
    const move = (px) => {
      const st = state.get(canvas);
      const t = Math.max(0, Math.min(st.end, ((px - st.box.l) / (st.box.r - st.box.l)) * st.end));
      st.at = t;
      drawChart(canvas, tip, st.series, st.metric, st.end);
    };
    canvas.addEventListener('pointermove', (e) => move(e.offsetX));
    canvas.addEventListener('pointerleave', () => { const st = state.get(canvas); st.at = null; tip.hidden = true; drawChart(canvas, tip, st.series, st.metric, st.end); });
    canvas.addEventListener('keydown', (e) => {
      const st = state.get(canvas);
      const dir = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
      if (!dir) return;
      e.preventDefault();
      st.at = Math.max(0, Math.min(st.end, (st.at ?? 0) + dir * 30000));
      drawChart(canvas, tip, st.series, st.metric, st.end);
    });
  }
  canvas.setAttribute('aria-label', `${METRICS[metric].label} over game time, ${series.map((s) => s.name).join(' and ')}. Arrow keys move the reading.`);
}

function crosshair(canvas, tip, t) {
  const { box, x, y, series, metric } = state.get(canvas);
  const g = canvas.getContext('2d');
  const css = getComputedStyle(canvas);
  g.strokeStyle = css.getPropertyValue('--muted').trim() || '#8b93a1';
  g.lineWidth = 1;
  g.beginPath(); g.moveTo(Math.round(x(t)) + 0.5, box.t); g.lineTo(Math.round(x(t)) + 0.5, box.b); g.stroke();
  const rows = series.map((s) => ({ s, r: rowAt(s.rows, t) })).filter((e) => e.r);
  for (const { s, r } of rows) {
    g.fillStyle = s.color;
    g.strokeStyle = css.getPropertyValue('--panel').trim() || '#14171d';
    g.lineWidth = 2;
    g.beginPath(); g.arc(x(t), y(r[metric] ?? 0), 4, 0, Math.PI * 2); g.fill(); g.stroke();
  }
  tip.replaceChildren();
  const head = document.createElement('b');
  head.textContent = `${clock(t)} · ${METRICS[metric].label}`;
  tip.append(head);
  rows.sort((a, b) => (b.r[metric] ?? 0) - (a.r[metric] ?? 0));
  for (const { s, r } of rows) {
    const line = document.createElement('div');
    const dot = document.createElement('i');
    dot.className = 'dot';
    dot.style.background = s.color;
    const value = document.createElement('span');
    value.textContent = Math.round(r[metric] ?? 0).toLocaleString('en');
    line.append(dot, s.name, value);
    tip.append(line);
  }
  tip.hidden = false;
  const left = x(t) + 12 + tip.offsetWidth > box.r ? x(t) - 12 - tip.offsetWidth : x(t) + 12;
  tip.style.transform = `translate(${Math.max(0, left)}px, ${box.t + 4}px)`;
}
