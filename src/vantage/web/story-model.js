// The Match story's data, derived from S.series and the event log. Pure
// (no DOM, no imports), so it is unit-tested (tests/hud_panels.test.mjs).

/** The last row at or before `at` (binary search over time-sorted rows). */
export function rowAt(rows, at) {
  if (!rows || !rows.length) return null;
  let lo = 0, hi = rows.length - 1, hit = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (rows[mid].t <= at) { hit = mid; lo = mid + 1; } else hi = mid - 1; }
  return hit < 0 ? null : rows[hit];
}

/** A side's value of one series key at a time: the sum over its players (null when unknown). */
export function sideValue(series, side, key, at) {
  let total = null;
  for (const p of side.players) {
    const row = rowAt(series && series[p.id], at), v = row ? row[key] : null;
    if (typeof v === 'number') total = (total || 0) + v;
  }
  return total;
}

/** [{ t, d }]: side A's value minus side B's at every sample of A's first player. */
export function leadCurve(series, a, b, key = 'army_value') {
  const base = (series && series[a.players[0].id]) || [];
  const out = [];
  for (const row of base) {
    const va = sideValue(series, a, key, row.t), vb = sideValue(series, b, key, row.t);
    if (va != null && vb != null) out.push({ t: row.t, d: va - vb });
  }
  return out;
}

/** The stretches where a cumulative series (idle TC seconds) grows: [{ from, to }]. */
export function growthSpans(rows, key) {
  const out = [];
  let open = null;
  for (let i = 1; i < (rows || []).length; i++) {
    const grew = typeof rows[i][key] === 'number' && typeof rows[i - 1][key] === 'number' && rows[i][key] > rows[i - 1][key];
    if (grew) { if (!open) open = { from: rows[i - 1].t, to: rows[i].t }; else open.to = rows[i].t; }
    else if (open) { out.push(open); open = null; }
  }
  if (open) out.push(open);
  return out;
}

/** The first age-up event of each age per player: [{ t, player, age }]. */
export function ageMarks(events) {
  const seen = new Set(), out = [];
  for (const e of events || []) {
    if (e.kind !== 'age_up') continue;
    const k = `${e.player}:${e.age}`;
    if (!seen.has(k)) { seen.add(k); out.push({ t: e.t, player: e.player, age: e.age }); }
  }
  return out;
}
